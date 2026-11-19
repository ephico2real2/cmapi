"""The review of #435 (cluster TLS trust, #434): reviewer 1's findings F1 to F3 and reviewer 2's N1 to N3, each a test that fails
on the pull request's head and passes with the fix, and the guards that keep two rejected fixes (F4, F5) from coming back.

    F1  the hub reader and the deliverer refuse an http API URL before they hold the token
    F2  a rotated token that ends in the same 12 characters gives the caches the new client
    F3  a bundle that cannot be read (not one that is missing) stops the trusted clusters with a finding naming it
    N1  tlsServerName holds through an HTTP proxy's CONNECT tunnel, where httpcore ignores the request's sni_hostname
    N2  a caData or a bundle that holds an intermediate CA without its root verifies, as a client-go CertPool does
    N3  a tlsServerName with a root dot is the same host, not a name no certificate matches

Real TLS servers on 127.0.0.1 and a CONNECT proxy on 127.0.0.1; no database:

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_cluster_trust_review_435.py -q -W ignore
"""
from __future__ import annotations

import datetime as dt
import errno
import os
import socket
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from test_cluster_trust_434 import (CA, LOCAL, NAMED_ONLY, TOKEN, Recorder, Server, Source, check, registry, secret, servers,
                                    system_store)

from cmapi.core.clients import trust as t
from cmapi.core.clients.kube import KubeClient
from cmapi.core.registry import HubImportSource

__all__ = ["servers", "system_store"]                   # fixtures of test_cluster_trust_434, used here by name


# --------------------------------------------------------------------------- helpers


class ConnectProxy:
    """An HTTP proxy that only tunnels (CONNECT), as a corporate egress proxy does for https. `tunnels` lists each target."""

    def __init__(self):
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.listener.getsockname()[1]}"
        self.tunnels: list[str] = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._tunnel, args=(conn,), daemon=True).start()

    def _tunnel(self, conn: socket.socket):
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = conn.recv(4096)
            if not chunk:
                conn.close()
                return
            head += chunk
        target = head.split(b" ", 2)[1].decode()
        self.tunnels.append(target)
        host, port = target.rsplit(":", 1)
        upstream = socket.create_connection((host, int(port)))
        conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")

        def pump(src: socket.socket, dst: socket.socket):
            try:
                while data := src.recv(65536):
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        threading.Thread(target=pump, args=(conn, upstream), daemon=True).start()
        pump(upstream, conn)

    def close(self):
        self.listener.close()


@pytest.fixture
def proxy(monkeypatch):
    """HTTPS_PROXY for every client built in the test, as an operator sets it on the pods behind an egress proxy."""
    p = ConnectProxy()
    for name in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", p.url)
    monkeypatch.setenv("https_proxy", p.url)
    yield p
    p.close()


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, cn)])


def _cert(subject: str, issuer: str, public_key, signer, ca: bool, sans: list[x509.GeneralName] | None = None) -> x509.Certificate:
    now = dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(_name(issuer)).public_key(public_key)
         .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
         .not_valid_after(now + dt.timedelta(days=1))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if sans:
        b = b.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    return b.sign(signer, hashes.SHA256())


def _pem(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def intermediate_chain(tmp: Path, sans: list[x509.GeneralName]) -> tuple[str, Server]:
    """A root, an intermediate it signs, and a server the intermediate signs that sends leaf and intermediate, as an API server
    behind a corporate PKI does. Returns the intermediate's PEM alone (no root) and the running server."""
    root_key, inter_key, leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    inter = _cert("intermediate", "root", inter_key.public_key(), root_key, True)
    leaf = _cert("kube-apiserver", "intermediate", leaf_key.public_key(), inter_key, False, sans)
    crt, key = tmp / "chain.crt", tmp / "leaf.key"
    crt.write_text(_pem(leaf) + _pem(inter))
    key.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return _pem(inter), Server(crt, key)


# --------------------------------------------------------------------------- F1: no bearer token over http


@pytest.mark.parametrize("kind", ["hub", "deliverer-setting", "deliverer-file"])
def test_the_hub_reader_and_the_deliverer_refuse_an_http_api_url_before_holding_the_token(tmp_path, monkeypatch, kind):
    """Before: an http CMAPI_KUBE_API_URL, or an http apiUrl in a deliverer Secret, built a client that sends the bearer token
    in clear text. The managed imports refuse the same in the registry's parse ("apiUrl is not https")."""
    from cmapi.jobs.watch_sync import _deliverer

    token_file = tmp_path / "token"
    token_file.write_text("auxiliary-sensitive-token")
    built: list[dict] = []
    monkeypatch.setattr(httpx, "Client", lambda **kw: built.append(kw) or SimpleNamespace())
    settings = SimpleNamespace(kube_token_file=token_file, kube_ca_file=tmp_path / "no-ca.crt",
                               kube_api_url="http://hub.example.test")
    deliverer_dir = tmp_path / "deliverer" / "C1"
    if kind == "deliverer-file":
        deliverer_dir.mkdir(parents=True)
        (deliverer_dir / "token").write_text("deliverer-sensitive-token")
        (deliverer_dir / "apiUrl").write_text("http://spoke.example.test:6443\n")
    if kind != "hub":
        # `_deliverer` reads /etc/cmapi/deliverer/<cluster>; the test's directory stands in for it.
        monkeypatch.setattr("pathlib.Path", lambda p: Path(str(p).replace("/etc/cmapi/deliverer", str(tmp_path / "deliverer"))))
    with pytest.raises(ValueError) as caught:
        if kind == "hub":
            HubImportSource("http://hub.example.test", token_file, tmp_path / "no-ca.crt", "cmapi-imports")
        else:
            _deliverer(SimpleNamespace(deliverer_factory=None, settings=settings), "C1")
    named = str(deliverer_dir / "apiUrl") if kind == "deliverer-file" else "CMAPI_KUBE_API_URL"
    assert str(caught.value) == f"{named} must be an https URL with a host and no userinfo"
    assert "hub.example.test" not in str(caught.value) and "spoke.example.test" not in str(caught.value)
    assert built == []


def test_the_in_cluster_hub_url_is_still_accepted(tmp_path):
    """CRC's and every pod's hub URL, the setting's default: https://kubernetes.default.svc."""
    (tmp_path / "token").write_text("hub-token-0123456789")
    source = HubImportSource("https://kubernetes.default.svc", tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")
    try:
        assert str(source.client.base_url) == "https://kubernetes.default.svc"
    finally:
        source.client.close()


# --------------------------------------------------------------------------- F2: the whole token in the fingerprint


def test_a_rotated_token_with_the_same_last_12_characters_replaces_the_client_and_every_cache(tmp_path):
    """Before: the fingerprint held token[-12:], so a rotated token ending the same kept the old client in the watch, node and
    report caches while the check reported connected with the new one."""
    ca = CA(tmp_path, "rotation")
    source = Source(secret("C1", "https://example.test", caData=ca.pem))
    source.secrets[0]["data"]["token"] = "old-prefix-123456789012"

    class Cache:
        def __init__(self, client):
            self.client, self.stopped = client, False

        def stop(self):
            self.stopped = True

    reg = registry(source, client_factory=Recorder, reports_factory=lambda st, client: Cache(client),
                   nodes_factory=lambda st, client: Cache(client))
    try:
        reg.refresh()
        st = reg.clusters["C1"]
        old_client, old_cache, old_reports, old_nodes = st.client, st.cache, st.reports, st.nodes
        source.secrets[0]["data"]["token"] = "new-prefix-123456789012"
        reg.refresh()
        assert st.status == "connected"
        assert st.client is not old_client and st.cache is not old_cache
        assert old_reports.stopped and old_nodes.stopped
        assert st.cache.client is st.reports.client is st.nodes.client is st.client
        assert all("123456789012" not in fp for fp in reg._fingerprints.values())
    finally:
        reg.stop()


# --------------------------------------------------------------------------- F3: unreadable is not missing


def test_a_bundle_that_cannot_be_read_stops_the_trusted_clusters_with_a_finding_naming_it(tmp_path, servers, system_store,
                                                                                         monkeypatch):
    """Before: any OSError of stat (EACCES on a directory the pod cannot enter) read as "not there", so the bundle silently left
    the store. Now only a missing file is skipped; the trusted cluster is cert-verify-failed naming the file, and a caData
    cluster is checked as before."""
    system, _ = system_store
    servers.append(trusted := system.server(tmp_path, LOCAL))
    own = CA(tmp_path, "own")
    servers.append(pinned := own.server(tmp_path, LOCAL))
    blocked = str(tmp_path / "unreadable" / "ca-bundle.crt")
    real_stat = os.stat

    def stat(path, *args, **kw):
        if str(path) == blocked:
            raise PermissionError(errno.EACCES, "Permission denied", blocked)
        return real_stat(path, *args, **kw)

    monkeypatch.setattr(t.os, "stat", stat)
    monkeypatch.setenv("CMAPI_TRUSTED_CA_FILE", blocked)
    source = Source(secret("C1", trusted.url), secret("C2", pinned.url, caData=own.pem))
    reg = registry(source)
    reg.refresh()
    assert reg.clusters["C1"].status == "cert-verify-failed"
    assert blocked in reg.clusters["C1"].findings[0] and "Permission denied" in reg.clusters["C1"].findings[0]
    assert (reg.clusters["C2"].status, reg.clusters["C2"].findings) == ("connected", [])


# --------------------------------------------------------------------------- F4 rejected: the keyed cache stays


def test_a_missing_bundle_keeps_one_shared_context(tmp_path, system_store):
    """CRC mounts the operator's ConfigMap optional and absent. The signature already changes when it appears (the test
    test_a_missing_injected_bundle_is_read_again_at_the_next_check), so the context with it missing is cached and shared:
    not cached, every trusted cluster would build and hold its own copy of the system store at each check (review of #435)."""
    present = CA(tmp_path, "present")
    raw = f"{present.path}:{tmp_path / 'operator' / 'ca-bundle.crt'}"
    assert t.trusted_context(raw) is t.trusted_context(raw)


# --------------------------------------------------------------------------- N1: tlsServerName through an HTTP proxy


@pytest.mark.parametrize("mode", ["caData", "trusted"])
def test_tls_server_name_holds_through_an_http_proxy_tunnel(tmp_path, servers, system_store, proxy, mode):
    """Before: httpcore's CONNECT tunnel starts TLS with the URL's host and ignores the request's sni_hostname, so behind
    HTTPS_PROXY a cluster reached by 127.0.0.1 with tlsServerName api.example.test failed: IP address mismatch."""
    system, _ = system_store
    ca = system if mode == "trusted" else CA(tmp_path, "cluster")
    servers.append(srv := ca.server(tmp_path, NAMED_ONLY))
    extra = {"caData": ca.pem} if mode == "caData" else {}
    st = check(Source(secret("C1", srv.url, tlsServerName="api.example.test", **extra)))
    assert (st.status, st.findings) == ("connected", [])
    assert proxy.tunnels and set(proxy.tunnels) == {srv.url.removeprefix("https://")}


def test_tls_server_name_still_guards_the_anchors_through_the_proxy(tmp_path, servers, system_store, proxy):
    """The name in the context never trusts more: the same server, caData of another CA, still fails behind the proxy."""
    servers.append(srv := CA(tmp_path, "cluster").server(tmp_path, NAMED_ONLY))
    st = check(Source(secret("C1", srv.url, tlsServerName="api.example.test", caData=CA(tmp_path, "other").pem)))
    assert st.status == "cert-verify-failed"


@pytest.mark.parametrize("through_proxy", [False, True], ids=["direct", "proxy"])
def test_a_watch_stream_uses_tls_server_name(tmp_path, servers, system_store, request, through_proxy):
    """The watch caches read with `stream`, not `request`: the name holds there too, directly and through the proxy."""
    if through_proxy:
        request.getfixturevalue("proxy")
    ca = CA(tmp_path, "cluster")
    servers.append(srv := ca.server(tmp_path, NAMED_ONLY))
    client = KubeClient("C1", srv.url, TOKEN, t.Trust("caData", ca_data=ca.pem, server_name="api.example.test"))
    try:
        events = list(client.watch("Namespace", "1", timeout_seconds=1))
    finally:
        client.close()
    assert events and events[0]["metadata"]["resourceVersion"] == "1"


# --------------------------------------------------------------------------- N2: an intermediate CA is an anchor


@pytest.mark.parametrize("mode", ["caData", "trusted"])
def test_an_intermediate_ca_without_its_root_is_an_anchor(tmp_path, servers, system_store, monkeypatch, mode):
    """Before: OpenSSL without VERIFY_X509_PARTIAL_CHAIN built the chain to a self-signed root, so a kubeconfig whose
    certificate-authority-data is the issuing intermediate (which kubectl, client-go and Argo CD accept) was cert-verify-failed."""
    inter, srv = intermediate_chain(tmp_path, LOCAL)
    servers.append(srv)
    if mode == "caData":
        st = check(Source(secret("C1", srv.url, caData=inter)))
    else:
        (bundle := tmp_path / "operator.pem").write_text(inter)
        monkeypatch.setenv("CMAPI_TRUSTED_CA_FILE", str(bundle))
        st = check(Source(secret("C1", srv.url)))
    assert (st.status, st.findings) == ("connected", [])


def test_partial_chain_never_trusts_an_unrelated_ca(tmp_path, servers, system_store):
    _, srv = intermediate_chain(tmp_path, LOCAL)
    servers.append(srv)
    st = check(Source(secret("C1", srv.url, caData=CA(tmp_path, "unrelated").pem)))
    assert st.status == "cert-verify-failed"


# --------------------------------------------------------------------------- N3: a root dot


def test_a_tls_server_name_with_a_root_dot_names_the_same_host(tmp_path, servers, system_store):
    """Before: tlsServerName "api.example.test." passed the parse and OpenSSL matched it as written, so no certificate for
    api.example.test ever verified (cert-verify-failed). The fully qualified form is the same host."""
    ca = CA(tmp_path, "cluster")
    servers.append(srv := ca.server(tmp_path, NAMED_ONLY))
    st = check(Source(secret("C1", srv.url, caData=ca.pem, tlsServerName="api.example.test.")))
    assert (st.status, st.findings) == ("connected", [])
    assert st.trust.server_name == "api.example.test"


def test_a_tls_server_name_with_two_trailing_dots_is_refused(tmp_path):
    st = check(Source(secret("C1", "https://127.0.0.1:9", tlsServerName="api.example.test..")))
    assert st.status == "invalid-secret"
    assert st.findings == ["tlsServerName is not a DNS name or an IP address"]


# --------------------------------------------------------------------------- guards from reviewer 1, kept


@pytest.mark.parametrize("data", [{"caData": "not base64!"}, {"caData": "aGVsbG8="}, {"insecure": "yes"},
                                  {"tlsServerName": "https://bad"}, {"insecure": "true"}],
                         ids=["caData-not-base64", "caData-no-certificate", "insecure-not-boolean", "bad-server-name",
                              "insecure-not-allowed"])
def test_a_refused_import_builds_no_http_client(data, monkeypatch):
    """Every refusal of the parse and of the TLS mode ends before an HTTP client, so the token is never sent."""
    def no_client(**kw):
        raise AssertionError("an HTTP client was built")

    monkeypatch.setattr(httpx, "Client", no_client)
    st = check(Source(secret("C1", "https://example.test", **data)))
    assert (st.status, st.client) == ("invalid-secret", None)


def test_the_trusted_cache_is_safe_across_threads_and_follows_a_rotation(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives.serialization import Encoding

    a, b, c = (CA(tmp_path, n) for n in ("a", "b", "c"))
    monkeypatch.setattr(t, "_system_locations", lambda: (str(a.path), None))
    raw = f"{b.path}:{c.path}"
    with ThreadPoolExecutor(max_workers=8) as pool:
        contexts = list(pool.map(lambda _: t.trusted_context(raw), range(32)))
    expected = {ca.cert.public_bytes(Encoding.DER) for ca in (a, b, c)}
    assert all(set(ctx.get_ca_certs(binary_form=True)) == expected for ctx in contexts)
    old = t.trusted_context(raw)
    c.path.write_text(a.pem + b.pem)
    new = t.trusted_context(raw)
    assert new is not old
    assert set(new.get_ca_certs(binary_form=True)) == expected - {c.cert.public_bytes(Encoding.DER)}


def test_the_verifying_contexts_check_the_chain_and_the_name_at_tls_1_2_or_later(tmp_path):
    """The flags every verifying mode starts from (`_client_context`): the hub's and the deliverer's ca.crt too."""
    ca = CA(tmp_path, "flags")
    for ctx in (t.ca_data_context(ca.pem), t.file_context(str(ca.path)), t.trusted_context(str(ca.path)),
                t.ca_data_context(ca.pem, "api.example.test")):
        assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
        assert ctx.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
