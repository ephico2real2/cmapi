"""How a cluster's API server is trusted: one mode per cluster (docs/02, "TLS: one mode per cluster"; #434).

    insecure  no verification at all, allowed only where instance.clusterTLS lets the cluster's environment have it
    caData    the import Secret's CA certificates, and nothing else (client-go's rule: caData is the ONLY anchor)
    trusted   neither: the image's system store, then each bundle of CMAPI_TRUSTED_CA_FILE, loaded in turn into one context

The system store is the image's own, OpenSSL's build-time cafile and capath, loaded by path. It is not what SSL_CERT_FILE names:
the pods point that variable at cmapi-trust, Keycloak's CA alone, and `ssl.create_default_context()` lets it replace the OpenSSL
bundle (measured, docs/reviews/2026-11-18-issue-434/analysis.md), so it would narrow cluster trust to Keycloak's CA.

CMAPI_TRUSTED_CA_FILE is colon-separated, like SSL_CERT_FILE, so that two sources can be mounted: the bundle OpenShift injects
into an empty ConfigMap labelled config.openshift.io/inject-trusted-cabundle, and a ConfigMap the operator makes. The bundles are
loaded in turn, never concatenated into a temporary file. A path that is not there, or an empty file, is skipped, because OpenShift
fills the injected ConfigMap after the pod starts; the context is cached by the size and modification time of every path, so a
bundle that appears or changes is read at the next check without a restart.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import ssl
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

TRUSTED_CA_ENV = "CMAPI_TRUSTED_CA_FILE"
# RFC 1123 host names: labels of letters, digits and hyphens, neither first nor last a hyphen; at most 253 characters.
_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
# A line with its end, CRLF, CR or LF (RFC 7468 section 3), as the registry's caData check splits it; the last may have none.
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")


class TrustBundleError(OSError):
    """A bundle of CMAPI_TRUSTED_CA_FILE that is there and does not load. An OSError, as ssl.SSLError and a missing file are, so
    the registry's net for a client that cannot be made catches it; the message names the file and the variable."""


def require_https(api_url: str, source: str) -> None:
    """Refuses an API URL that would carry a bearer token in clear text, before any client holds the token. The managed
    imports refuse the same in the registry's parse; this is for the hub reader and the deliverer, whose URL comes from
    `source` (a setting or a mounted file), named in the error. The URL itself is not echoed: it may hold userinfo."""
    try:
        parsed = urlsplit(api_url)
        valid = parsed.scheme == "https" and bool(parsed.hostname) and not (parsed.username or parsed.password)
    except ValueError:                      # a malformed IPv6 host, such as https://[::1:6443
        valid = False
    if not valid:
        raise ValueError(f"{source} must be an https URL with a host and no userinfo")


def valid_server_name(name: str) -> bool:
    """Whether `name` can be kubeconfig's tls-server-name: a DNS name or an IP address literal (RFC 9525's DNS-ID and IP-ID).
    A DNS name may end in one root dot, which the registry drops before use (OpenSSL does not match api.example.test. to a
    certificate for api.example.test)."""
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return 0 < len(name) <= 253 and all(_LABEL.fullmatch(label) for label in name.removesuffix(".").split("."))


class _NamedContext(ssl.SSLContext):
    """A client context that sends and checks one server name, whatever host the transport hands it.

    kubeconfig's tls-server-name has to hold on every path to the cluster. httpcore takes the request extension
    `sni_hostname` on a direct or SOCKS connection, but its HTTP-proxy tunnel starts TLS with the URL's host (httpcore 1.0.9,
    _sync/http_proxy.py, TunnelHTTPConnection.handle_request), so with HTTPS_PROXY set the name would be dropped and a
    cluster reached by an address its certificate does not name would fail. httpcore's sync backend calls `wrap_socket`,
    and `wrap_bio` for TLS inside a TLS proxy, so the name set here is the TLS server_hostname on each of those paths."""

    server_name: str | None = None

    def wrap_socket(self, sock, server_side=False, do_handshake_on_connect=True, suppress_ragged_eofs=True,
                    server_hostname=None, session=None):
        return super().wrap_socket(sock, server_side, do_handshake_on_connect, suppress_ragged_eofs,
                                   self.server_name or server_hostname, session)

    def wrap_bio(self, incoming, outgoing, server_side=False, server_hostname=None, session=None):
        return super().wrap_bio(incoming, outgoing, server_side, self.server_name or server_hostname, session)


def _client_context(server_name: str | None = None) -> ssl.SSLContext:
    """A client context with no anchors: PROTOCOL_TLS_CLIENT verifies the chain and the host name, TLS 1.2 at least.

    VERIFY_X509_PARTIAL_CHAIN makes every certificate loaded an anchor, as client-go's CertPool does: a caData or a bundle
    that holds an intermediate CA and not its root verifies, as it does for kubectl and Argo CD. Python 3.13's
    create_default_context sets the same flag; 3.12, the image's, does not."""
    ctx = _NamedContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.server_name = server_name
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


def _ascii_lines(ca_data: str) -> str:
    """caData as Python's loader takes it: "an ASCII string of one or more PEM-encoded certificates" (the ssl docs), since a
    bytes value is read as DER. A line that is not ASCII, such as an issuer's name above a certificate (RFC 7468 section 5.2's
    explanatory text), raised TypeError (#591); OpenSSL and client-go skip such text, so that line is left out. The registry
    has refused a value with one inside a CERTIFICATE block, so no certificate line is lost. An ASCII value is unchanged."""
    if ca_data.isascii():
        return ca_data
    return "".join(line for line in _LINE.findall(ca_data) if line.isascii())


def ca_data_context(ca_data: str, server_name: str | None = None) -> ssl.SSLContext:
    """The caData of an import Secret as the only anchors, in memory. ssl.SSLError when it holds no certificate."""
    ctx = _client_context(server_name)
    ctx.load_verify_locations(cadata=_ascii_lines(ca_data))
    return ctx


def file_context(path: str) -> ssl.SSLContext:
    """One PEM file as the only anchors: the hub's own ServiceAccount ca.crt, a deliverer's ca.crt."""
    ctx = _client_context()
    ctx.load_verify_locations(cafile=path)
    return ctx


def _system_locations() -> tuple[str | None, str | None]:
    paths = ssl.get_default_verify_paths()
    cafile = paths.openssl_cafile if paths.openssl_cafile and os.path.isfile(paths.openssl_cafile) else None
    capath = paths.openssl_capath if paths.openssl_capath and os.path.isdir(paths.openssl_capath) else None
    return cafile, capath


def _signature(path: str) -> tuple[str, int, int] | None:
    """A bundle's (path, size, mtime), or None for one that is not there or is empty. Any other failure to stat it (a
    directory the process cannot enter, a symlink loop) is no absence: it raises TrustBundleError naming the file, so the
    trusted clusters stop with that finding instead of being verified against a smaller store."""
    try:
        st = os.stat(path)                  # follows the ..data symlink of a ConfigMap volume, so a refill changes it
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TrustBundleError(f"the trusted CA bundle {path} ({TRUSTED_CA_ENV}) cannot be read: {exc}") from exc
    return (path, st.st_size, st.st_mtime_ns) if st.st_size else None


# One entry for each list of paths and server name: the signature it was built from and the context. A bundle that is not
# there is cached too: the signature changes when it appears, so it is read at the next check either way.
_cache: dict[tuple[tuple[str, ...], str | None], tuple[tuple, ssl.SSLContext]] = {}
_cache_lock = threading.Lock()


def bundle_paths(raw: str | None) -> list[str]:
    raw = os.environ.get(TRUSTED_CA_ENV, "") if raw is None else raw
    return [p for p in (part.strip() for part in raw.split(":")) if p]


def trusted_signature(raw: str | None = None) -> tuple:
    """What the trusted context is built from: the system store's locations and each bundle that is there, with its size and
    time. A change of it means a new context, and a new client for a cluster that uses it."""
    return (_system_locations(), tuple(s for s in (_signature(p) for p in bundle_paths(raw)) if s))


def trusted_context(raw: str | None = None, server_name: str | None = None) -> ssl.SSLContext:
    """The system store, then each bundle of `raw` (default: CMAPI_TRUSTED_CA_FILE) that is there, in turn."""
    entry = (tuple(bundle_paths(raw)), server_name)
    key = trusted_signature(raw)
    with _cache_lock:
        cached = _cache.get(entry)
    if cached is not None and cached[0] == key:
        return cached[1]
    (cafile, capath), bundles = key
    ctx = _client_context(server_name)
    if cafile or capath:
        ctx.load_verify_locations(cafile=cafile, capath=capath)
    for path, _, _ in bundles:
        try:
            ctx.load_verify_locations(cafile=path)
        except (OSError, ValueError) as exc:
            raise TrustBundleError(f"the trusted CA bundle {path} ({TRUSTED_CA_ENV}) does not load: {exc}") from exc
    with _cache_lock:
        _cache[entry] = (key, ctx)
    return ctx


@dataclass(frozen=True)
class Trust:
    """The trust mode of one cluster, decided from its import Secret by the registry and turned into an SSL context by the client.

    The client builds the context, so that a caData that is valid base64 and no certificate fails where the client is made
    (#419), and so a test's stand-in client never has to load one."""

    source: str                             # "caData", "trusted" or "insecure"
    ca_data: str | None = None
    server_name: str | None = None          # kubeconfig's tls-server-name: SNI and the name checked; never the anchors
    bundles: str | None = None              # CMAPI_TRUSTED_CA_FILE's value; None reads the variable

    def verify(self) -> ssl.SSLContext | bool:
        if self.source == "insecure":
            return False
        if self.source == "caData":
            return ca_data_context(self.ca_data or "", self.server_name)
        return trusted_context(self.bundles, self.server_name)

    def fingerprint(self) -> str:
        """Changes when anything the client verifies with changes (G6): the mode, the caData, the server name, the bundles."""
        parts = [self.source, self.server_name or ""]
        if self.source == "caData":
            parts.append(hashlib.sha256((self.ca_data or "").encode()).hexdigest())
        elif self.source == "trusted":
            parts.append(repr(trusted_signature(self.bundles)))
        return "|".join(parts)

    def view(self) -> dict[str, object]:
        return {"source": self.source, "downgrade": self.source == "insecure", "serverName": self.server_name}

    def store_name(self) -> str:
        """The trust store, as a finding names it."""
        if self.source == "caData":
            return "caData"
        if self.source == "insecure":
            return "insecure"
        return f"trusted (the system store and {TRUSTED_CA_ENV})"

