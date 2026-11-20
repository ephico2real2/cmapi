"""#434: how cmapi trusts a cluster's API server (docs/02, "TLS: one mode per cluster"; the analysis and the owner's decisions are
in docs/reviews/2026-11-18-issue-434/).

Exactly one mode per cluster: `insecure` (allowed per environment by instance.clusterTLS), `caData` (that CA alone), or
`trusted` (the image's system store, then each bundle of CMAPI_TRUSTED_CA_FILE). Real TLS servers on 127.0.0.1, each signed by its
own test CA, answer the three calls of the check; TLS is verified in every test but the insecure ones. The image's system store is
the OpenSSL build-time default (`ssl.get_default_verify_paths`), which a test points at a test CA. Needs no database:

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_cluster_trust_434.py -q -W ignore
"""
from __future__ import annotations

import datetime as dt
import http.server
import ipaddress
import json
import ssl
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from cmapi.core import registry as registry_module
from cmapi.core.registry import READER_IDENTITY, ClusterPolicy, ClusterRegistry, ImportSource

TOKEN = "eyJhbGciOiJSUzI1NiJ9.reader-token-434"


# --------------------------------------------------------------------------- certificates and servers


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


class CA:
    def __init__(self, tmp: Path, cn: str):
        self.key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.timezone.utc)
        self.cert = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(_name(cn)).public_key(self.key.public_key())
                     .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
                     .not_valid_after(now + dt.timedelta(days=1))
                     .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                     .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                                  content_commitment=False, key_encipherment=False, data_encipherment=False,
                                                  key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                     .sign(self.key, hashes.SHA256()))
        self.pem = self.cert.public_bytes(serialization.Encoding.PEM).decode()
        self.path = tmp / f"{cn}.pem"
        self.path.write_text(self.pem)

    def server_files(self, tmp: Path, sans: list[x509.GeneralName]) -> tuple[Path, Path]:
        key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(_name("kube-apiserver")).issuer_name(self.cert.subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                .add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(self.key, hashes.SHA256()))
        crt, pem = tmp / f"server-{id(cert)}.crt", tmp / f"server-{id(cert)}.key"
        crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        return crt, pem

    def server(self, tmp: Path, sans: list[x509.GeneralName]) -> "Server":
        return Server(*self.server_files(tmp, sans))


LOCAL = [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
NAMED_ONLY = [x509.DNSName("api.example.test")]            # the kind case: reached by an address the certificate does not name


class _Reader(http.server.BaseHTTPRequestHandler):
    """The three calls of checks 4 to 6, answered as a healthy cluster with the reader's token."""

    def do_GET(self):  # noqa: N802 - the stdlib's name
        if self.path == "/version":
            body = {"gitVersion": "v1.35.6"}
        elif self.path.endswith("/users/~"):
            body = {"metadata": {"name": READER_IDENTITY}}
        elif self.path.startswith("/api/v1/namespaces"):
            body = {"items": [], "metadata": {"resourceVersion": "1"}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class Server:
    def __init__(self, crt: Path, key: Path):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Reader)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"https://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def servers():
    made: list[Server] = []
    yield made
    for s in made:
        s.close()


@pytest.fixture
def system_store(tmp_path, monkeypatch):
    """The image's system store, as the OpenSSL build-time default cafile, holding CA "system" alone. SSL_CERT_FILE points at a
    second CA, "keycloak", as the pods point it at cmapi-trust: the system store must not be what that variable names (D7)."""
    system, keycloak = CA(tmp_path, "system"), CA(tmp_path, "keycloak")
    real = ssl.get_default_verify_paths()
    monkeypatch.setattr(ssl, "get_default_verify_paths", lambda: real._replace(
        cafile=str(system.path), capath=None, openssl_cafile=str(system.path), openssl_capath=str(tmp_path / "no-capath")))
    monkeypatch.setenv("SSL_CERT_FILE", str(keycloak.path))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.delenv("CMAPI_TRUSTED_CA_FILE", raising=False)
    return system, keycloak


class Source(ImportSource):
    def __init__(self, *secrets):
        self.secrets = list(secrets)

    def list(self):
        return list(self.secrets)


def secret(cid: str, url: str, **data: str) -> dict:
    return {"name": f"cmapi-cluster-{cid.lower()}", "labels": {"cmapi.net/cluster-id": cid}, "annotations": {},
            "data": {"apiUrl": url, "token": TOKEN, **data}}


def registry(source: ImportSource, env: str = "dev", **kw) -> ClusterRegistry:
    policies = {s["labels"]["cmapi.net/cluster-id"]: ClusterPolicy(s["labels"]["cmapi.net/cluster-id"], env, "clusters/x")
                for s in source.list()}
    return ClusterRegistry(policies, source, start_caches=False, **kw)


def check(source: ImportSource, cid: str = "C1", env: str = "dev", **kw):
    reg = registry(source, env, **kw)
    reg.refresh()
    return reg.clusters[cid]


# --------------------------------------------------------------------------- trusted: the system store and the bundles


def test_a_cluster_signed_by_a_system_ca_connects_with_no_caData(tmp_path, servers, system_store):
    """Before: with no caData the trust was CMAPI_CA_BUNDLE alone, else httpx's verify=True (certifi or SSL_CERT_FILE)."""
    system, _ = system_store
    servers.append(srv := system.server(tmp_path, LOCAL))
    st = check(Source(secret("C1", srv.url)))
    assert (st.status, st.findings) == ("connected", [])


def test_ssl_cert_file_is_not_the_system_store(tmp_path, servers, system_store):
    """D7: the pods set SSL_CERT_FILE to cmapi-trust (Keycloak's CA); a cluster signed by that CA alone is not trusted by it."""
    _, keycloak = system_store
    servers.append(srv := keycloak.server(tmp_path, LOCAL))
    st = check(Source(secret("C1", srv.url)))
    assert st.status == "cert-verify-failed"


def test_a_cluster_signed_by_an_operator_bundle_connects(tmp_path, servers, system_store, monkeypatch):
    operator = CA(tmp_path, "operator")
    servers.append(srv := operator.server(tmp_path, LOCAL))
    monkeypatch.setenv("CMAPI_TRUSTED_CA_FILE", f"{tmp_path / 'injected-not-filled-yet.crt'}:{operator.path}")
    st = check(Source(secret("C1", srv.url)))
    assert (st.status, st.findings) == ("connected", [])


def test_a_missing_injected_bundle_is_read_again_at_the_next_check(tmp_path, servers, system_store, monkeypatch):
    """OpenShift fills the injected ConfigMap after the pod starts: its absence is never cached."""
    injected = CA(tmp_path, "injected")
    servers.append(srv := injected.server(tmp_path, LOCAL))
    bundle = tmp_path / "mounted" / "ca-bundle.crt"
    monkeypatch.setenv("CMAPI_TRUSTED_CA_FILE", str(bundle))
    reg = registry(Source(secret("C1", srv.url)))
    reg.refresh()
    assert reg.clusters["C1"].status == "cert-verify-failed"
    bundle.parent.mkdir()
    bundle.write_text(injected.pem)
    reg.refresh()
    assert (reg.clusters["C1"].status, reg.clusters["C1"].findings) == ("connected", [])


def test_a_bundle_that_does_not_load_is_a_finding_that_names_it(tmp_path, servers, system_store, monkeypatch):
    system, _ = system_store
    servers.append(srv := system.server(tmp_path, LOCAL))
    bad = tmp_path / "operator-ca.crt"
    bad.write_text("-----BEGIN CERTIFICATE-----\naGVsbG8gd29ybGQ=\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("CMAPI_TRUSTED_CA_FILE", str(bad))
    st = check(Source(secret("C1", srv.url)))
    assert st.status == "cert-verify-failed"
    assert str(bad) in st.findings[0] and "CMAPI_TRUSTED_CA_FILE" in st.findings[0]


def test_the_keycloak_bundle_is_no_longer_cluster_trust(tmp_path, servers, system_store, monkeypatch):
    """D4: CMAPI_CA_BUNDLE is Keycloak's trust; a cluster signed by it alone, with no caData, is not trusted."""
    _, keycloak = system_store
    servers.append(srv := keycloak.server(tmp_path, LOCAL))
    monkeypatch.setenv("CMAPI_CA_BUNDLE", str(keycloak.path))
    st = check(Source(secret("C1", srv.url)))
    assert st.status == "cert-verify-failed"


# --------------------------------------------------------------------------- caData


def test_caData_is_the_only_trust_and_never_widens_to_the_system_store(tmp_path, servers, system_store):
    """A guard, true before and after: client-go's rule (caData is the ONLY information in the pool)."""
    system, _ = system_store
    servers.append(srv := system.server(tmp_path, LOCAL))
    other = CA(tmp_path, "other")
    st = check(Source(secret("C1", srv.url, caData=other.pem)))
    assert st.status == "cert-verify-failed"


def test_caData_connects_and_writes_no_file(tmp_path, servers, system_store, monkeypatch):
    """G5: caData was written to a temporary file per change and never removed; it is now loaded in memory."""
    own = CA(tmp_path, "own")
    servers.append(srv := own.server(tmp_path, LOCAL))
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    st = check(Source(secret("C1", srv.url, caData=own.pem)))
    assert (st.status, st.findings) == ("connected", [])
    assert list(temp.iterdir()) == []


# --------------------------------------------------------------------------- tlsServerName


def test_tls_server_name_verifies_a_cluster_reached_by_an_address_it_does_not_name(tmp_path, servers, system_store):
    own = CA(tmp_path, "own")
    servers.append(srv := own.server(tmp_path, NAMED_ONLY))
    assert check(Source(secret("C1", srv.url, caData=own.pem))).status == "cert-verify-failed"
    st = check(Source(secret("C1", srv.url, caData=own.pem, tlsServerName="api.example.test")))
    assert (st.status, st.findings) == ("connected", [])
    assert st.view()["trust"] == {"source": "caData", "downgrade": False, "serverName": "api.example.test"}


def test_tls_server_name_never_changes_the_anchors(tmp_path, servers, system_store):
    own, other = CA(tmp_path, "own"), CA(tmp_path, "other")
    servers.append(srv := own.server(tmp_path, NAMED_ONLY))
    st = check(Source(secret("C1", srv.url, caData=other.pem, tlsServerName="api.example.test")))
    assert st.status == "cert-verify-failed"


@pytest.mark.parametrize("name", ["api example", "https://api.example.test", "api.example.test:6443", "-bad.example", "a" * 64 + ".x"])
def test_a_tls_server_name_that_is_no_host_name_is_refused(tmp_path, name):
    st = check(Source(secret("C1", "https://192.0.2.1:6443", tlsServerName=name)))
    assert st.status == "invalid-secret"
    assert st.findings == ["tlsServerName is not a DNS name or an IP address"]


# --------------------------------------------------------------------------- insecure, per environment


def test_insecure_is_refused_where_the_environment_does_not_allow_it_even_rnd(tmp_path):
    """G1: rnd was allowed by a constant; now no environment is, unless instance.clusterTLS says so. No client is built."""
    made = []
    st = check(Source(secret("C1", "https://192.0.2.1:6443", insecure="true")), env="rnd",
               client_factory=lambda *a, **k: made.append(a))
    assert st.status == "invalid-secret"
    assert st.findings == ["insecure is not allowed for environment rnd: "
                           "instance.clusterTLS.environments.rnd.insecureSkipTLSVerify is false"]
    assert made == []


def test_insecure_connects_where_the_environment_allows_it_and_is_shown_as_a_downgrade(tmp_path, servers, system_store):
    stranger = CA(tmp_path, "stranger")
    servers.append(srv := stranger.server(tmp_path, LOCAL))
    st = check(Source(secret("C1", srv.url, insecure="true")), env="prod", insecure_environments={"prod"})
    assert (st.status, st.findings) == ("connected", [])
    assert st.view()["trust"] == {"source": "insecure", "downgrade": True, "serverName": None}


def test_insecure_with_caData_is_refused(tmp_path, system_store):
    own = CA(tmp_path, "own")
    st = check(Source(secret("C1", "https://192.0.2.1:6443", insecure="true", caData=own.pem)), insecure_environments={"dev"})
    assert st.status == "invalid-secret" and "insecure with caData" in st.findings


@pytest.mark.parametrize("value", ["yes", "1", "on", ""])
def test_insecure_is_true_or_false(tmp_path, value):
    st = check(Source(secret("C1", "https://192.0.2.1:6443", insecure=value)))
    assert st.status == "invalid-secret"
    assert st.findings == ['insecure is "true" or "false"']


def test_the_insecure_metric_and_one_log_line_per_change_of_mode(tmp_path, servers, system_store, monkeypatch):
    from cmapi.core.observability import CLUSTER_TLS_INSECURE

    events: list[tuple[str, dict]] = []

    class Log:
        def __getattr__(self, level):
            return lambda event, **kw: events.append((event, kw))

    monkeypatch.setattr(registry_module, "log", Log())
    own = CA(tmp_path, "own")
    servers.append(srv := own.server(tmp_path, LOCAL))
    source = Source(secret("C9", srv.url, insecure="true"))
    reg = registry(source, insecure_environments={"dev"})
    reg.refresh()
    reg.refresh()
    assert CLUSTER_TLS_INSECURE.labels("C9")._value.get() == 1
    source.secrets = [secret("C9", srv.url, caData=own.pem)]
    reg.refresh()
    reg.refresh()
    assert CLUSTER_TLS_INSECURE.labels("C9")._value.get() == 0
    modes = [(kw["mode"], kw["previous"]) for e, kw in events if e == "cluster_tls_mode"]
    assert modes == [("insecure", None), ("caData", "insecure")]


# --------------------------------------------------------------------------- G6: a change of trust rebuilds the client


class Recorder:
    made: list["Recorder"] = []

    def __init__(self, *args, **kw):
        self.args, self.kw = args, kw
        Recorder.made.append(self)

    def version(self):
        return "v1.35.6"

    def whoami(self):
        return READER_IDENTITY

    def list(self, kind, **kw):
        return {"items": []}

    def close(self):
        pass


@pytest.mark.parametrize("change", [{"caData": "rotated"}, {"tlsServerName": "api.example.test"}, {"insecure": "true"}])
def test_a_change_of_trust_with_the_same_token_rebuilds_the_client_the_caches_hold(tmp_path, monkeypatch, change):
    """G6: the fingerprint was apiUrl|token[-12:]|bool(caData), so a rotated CA kept the old client in the watch caches."""
    monkeypatch.setattr("cmapi.core.registry.WatchCache", lambda client, **kw: type("C", (), {"client": client, "stop": lambda s: None})())
    first = CA(tmp_path, "first").pem
    second = CA(tmp_path, "second").pem
    before = {"caData": first} if "insecure" not in change else {}
    after = dict(before, **{k: (second if v == "rotated" else v) for k, v in change.items()})
    if "insecure" in change:
        after.pop("caData", None)
    Recorder.made = []
    source = Source(secret("C1", "https://192.0.2.1:6443", **before))
    extra = {"insecure_environments": {"dev"}} if "insecure" in change else {}
    reg = registry(source, client_factory=Recorder, **extra)
    reg.refresh()
    held = reg.clusters["C1"].cache.client
    source.secrets = [secret("C1", "https://192.0.2.1:6443", **after)]
    reg.refresh()
    assert reg.clusters["C1"].status == "connected"
    assert reg.clusters["C1"].cache.client is not held
    assert reg.clusters["C1"].cache.client is Recorder.made[-1]


def test_the_view_names_the_trusted_source(tmp_path, servers, system_store):
    system, _ = system_store
    servers.append(srv := system.server(tmp_path, LOCAL))
    st = check(Source(secret("C1", srv.url)))
    assert st.view()["trust"] == {"source": "trusted", "downgrade": False, "serverName": None}


def test_a_refused_secret_reports_no_trust(tmp_path):
    st = check(Source(secret("C1", "http://192.0.2.1:6443")))
    assert st.status == "invalid-secret" and st.view()["trust"] is None


# --------------------------------------------------------------------------- instance.yaml clusterTLS


def test_cluster_tls_allows_insecure_per_environment_prod_included():
    """D2: any served environment may allow it, prod included; the default is false everywhere."""
    from cmapi.core.clustertls import ClusterTLSSettings

    tls, problems = ClusterTLSSettings.parse({"environments": {"prod": {"insecureSkipTLSVerify": True},
                                                               "dev": {"insecureSkipTLSVerify": False}}}, {"prod", "dev", "rnd"})
    assert problems == [] and tls.insecure_environments == {"prod"}
    assert tls.view({"prod", "dev", "rnd"}) == {"dev": False, "prod": True, "rnd": False}
    assert ClusterTLSSettings.parse(None, {"rnd"}) == (ClusterTLSSettings(), [])


@pytest.mark.parametrize("raw, problem", [
    ([], "instance.yaml: clusterTLS must be a mapping"),
    ({"insecure": True}, "instance.yaml: clusterTLS has unknown fields ['insecure']"),
    ({"environments": {"qa": {"insecureSkipTLSVerify": True}}}, "instance.yaml: clusterTLS.environments.qa is not an environment this instance serves"),
    ({"environments": {"rnd": {"insecureSkipVerify": True}}}, "instance.yaml: clusterTLS.environments.rnd has the one key insecureSkipTLSVerify"),
    ({"environments": {"rnd": {"insecureSkipTLSVerify": "true"}}}, "instance.yaml: clusterTLS.environments.rnd.insecureSkipTLSVerify is true or false, not 'true'"),
], ids=["not-a-mapping", "unknown-key", "not-served", "wrong-name", "not-a-boolean"])
def test_a_bad_cluster_tls_stops_the_start(raw, problem):
    from cmapi.core.clustertls import ClusterTLSSettings

    tls, problems = ClusterTLSSettings.parse(raw, {"rnd", "dev"})
    assert problems == [problem] and tls.insecure_environments == frozenset()


def test_load_instance_reads_cluster_tls(tmp_path, monkeypatch):
    """load_instance reads clusterTLS from instance.yaml; core/context.py hands `insecure_environments` to the registry."""
    import shutil

    import yaml

    from cmapi.core.config import ConfigError, load_instance

    src = Path(__file__).resolve().parents[3] / "examples" / "instances" / "nonprod"
    shutil.copytree(src, tmp_path / "cfg")
    inst = yaml.safe_load((tmp_path / "cfg" / "instance.yaml").read_text())
    env = sorted(inst["instance"]["allowedEnvironments"])[0]
    keys = Path(__file__).resolve().parents[3] / "examples" / "cluster-configs" / "policies" / "metadata-keys.yaml"
    assert load_instance(tmp_path / "cfg", keys).cluster_tls.insecure_environments == frozenset()
    inst["instance"]["clusterTLS"] = {"environments": {env: {"insecureSkipTLSVerify": True}}}
    (tmp_path / "cfg" / "instance.yaml").write_text(yaml.safe_dump(inst))
    assert load_instance(tmp_path / "cfg", keys).cluster_tls.insecure_environments == {env}
    inst["instance"]["clusterTLS"] = {"environments": {"nowhere": {"insecureSkipTLSVerify": True}}}
    (tmp_path / "cfg" / "instance.yaml").write_text(yaml.safe_dump(inst))
    with pytest.raises(ConfigError, match="clusterTLS.environments.nowhere is not an environment this instance serves"):
        load_instance(tmp_path / "cfg", keys)
