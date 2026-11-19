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

TRUSTED_CA_ENV = "CMAPI_TRUSTED_CA_FILE"
# RFC 1123 host names: labels of letters, digits and hyphens, neither first nor last a hyphen; at most 253 characters.
_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")


class TrustBundleError(OSError):
    """A bundle of CMAPI_TRUSTED_CA_FILE that is there and does not load. An OSError, as ssl.SSLError and a missing file are, so
    the registry's net for a client that cannot be made catches it; the message names the file and the variable."""


def valid_server_name(name: str) -> bool:
    """Whether `name` can be kubeconfig's tls-server-name: a DNS name or an IP address literal (RFC 9525's DNS-ID and IP-ID)."""
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return 0 < len(name) <= 253 and all(_LABEL.fullmatch(label) for label in name.rstrip(".").split("."))


def _client_context() -> ssl.SSLContext:
    """A client context with no anchors: PROTOCOL_TLS_CLIENT verifies the chain and the host name by default."""
    return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def ca_data_context(ca_data: str) -> ssl.SSLContext:
    """The caData of an import Secret as the only anchors, in memory. ssl.SSLError when it holds no certificate."""
    ctx = _client_context()
    ctx.load_verify_locations(cadata=ca_data)
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
    try:
        st = os.stat(path)                  # follows the ..data symlink of a ConfigMap volume, so a refill changes it
    except OSError:
        return None
    return (path, st.st_size, st.st_mtime_ns) if st.st_size else None


# One entry for each list of paths: the signature it was built from and the context.
_cache: dict[tuple[str, ...], tuple[tuple, ssl.SSLContext]] = {}
_cache_lock = threading.Lock()


def bundle_paths(raw: str | None) -> list[str]:
    raw = os.environ.get(TRUSTED_CA_ENV, "") if raw is None else raw
    return [p for p in (part.strip() for part in raw.split(":")) if p]


def trusted_signature(raw: str | None = None) -> tuple:
    """What the trusted context is built from: the system store's locations and each bundle that is there, with its size and
    time. A change of it means a new context, and a new client for a cluster that uses it."""
    return (_system_locations(), tuple(s for s in (_signature(p) for p in bundle_paths(raw)) if s))


def trusted_context(raw: str | None = None) -> ssl.SSLContext:
    """The system store, then each bundle of `raw` (default: CMAPI_TRUSTED_CA_FILE) that is there, in turn."""
    paths = tuple(bundle_paths(raw))
    key = trusted_signature(raw)
    with _cache_lock:
        cached = _cache.get(paths)
    if cached is not None and cached[0] == key:
        return cached[1]
    (cafile, capath), bundles = key
    ctx = _client_context()
    if cafile or capath:
        ctx.load_verify_locations(cafile=cafile, capath=capath)
    for path, _, _ in bundles:
        try:
            ctx.load_verify_locations(cafile=path)
        except (OSError, ValueError) as exc:
            raise TrustBundleError(f"the trusted CA bundle {path} ({TRUSTED_CA_ENV}) does not load: {exc}") from exc
    with _cache_lock:
        _cache[paths] = (key, ctx)
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
            return ca_data_context(self.ca_data or "")
        return trusted_context(self.bundles)

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

