"""BUG-12 (#97): the Git host is verified against its own trust, not against cmapi-trust.

cmapi-trust (CMAPI_CA_BUNDLE) holds Keycloak's private CA alone (docs/reviews/2026-11-06-wave1-design, ruling 2), and the pods
also set SSL_CERT_FILE to it, which httpx 0.28.1 honours for verify=True (httpx/_config.py, create_ssl_context). So before the
fix a call to github.com could not verify. CMAPI_GIT_CA_BUNDLE names the bundle the Git provider trusts, as an explicit
SSLContext that no environment variable changes; unset, the provider keeps today's trust (CMAPI_CA_BUNDLE, else the default).

Real TLS servers on 127.0.0.1, each signed by its own test CA: "private" stands for Keycloak's CA, "public" for the public roots
GitHub's certificate chains to, and "stranger" for a CA in neither set. TLS verification is never turned off here.
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

from cmapi.core.git import GitUnavailable, make_provider
from cmapi.settings import Settings


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _ca(tmp: Path, cn: str):
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(_name(cn)).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    path = tmp / f"{cn}.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert, path


def _server_cert(tmp: Path, ca_key, ca_cert, cn: str) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    crt, pem = tmp / f"{cn}.crt", tmp / f"{cn}.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return crt, pem


class _GitHubBranch(http.server.BaseHTTPRequestHandler):
    """Answers the one call branch_head makes: GET /repos/{o}/{r}/branches/{b}."""

    def do_GET(self):  # noqa: N802 - the stdlib's name
        body = json.dumps({"name": "main", "commit": {"sha": "a" * 40}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def pki(tmp_path):
    out = {}
    for name in ("private", "public", "stranger"):
        key, cert, path = _ca(tmp_path, f"{name}-ca")
        out[name] = (key, cert, path)
    return out


@pytest.fixture
def https(tmp_path):
    servers = []

    def start(ca) -> str:
        crt, key = _server_cert(tmp_path, ca[0], ca[1], f"git-{len(servers)}")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _GitHubBranch)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"https://127.0.0.1:{srv.server_address[1]}"

    yield start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _head(settings: Settings, url: str) -> str | None:
    # The same arguments core/context.py's build_context passes, so the test reads the trust the service would use.
    return make_provider("github", url, "ephico2real2/cmapi-cluster-configs", "not-a-token",
                         verify=settings.git_verify).branch_head("main")


def test_the_git_host_verifies_against_its_own_bundle_whatever_ssl_cert_file_says(pki, https, monkeypatch):
    """The CRC pod's environment: CMAPI_CA_BUNDLE and SSL_CERT_FILE both name the private CA. GitHub's chain is in the Git bundle."""
    monkeypatch.setenv("SSL_CERT_FILE", str(pki["private"][2]))
    settings = Settings(ca_bundle=pki["private"][2], git_ca_bundle=pki["public"][2])
    assert _head(settings, https(pki["public"])) == "a" * 40


def test_a_git_host_outside_the_git_bundle_is_refused(pki, https, monkeypatch):
    """Not in the Git bundle, so refused, even when its CA is the one cmapi-trust and SSL_CERT_FILE hold: Keycloak's CA mints for no Git host."""
    monkeypatch.setenv("SSL_CERT_FILE", str(pki["private"][2]))
    settings = Settings(ca_bundle=pki["private"][2], git_ca_bundle=pki["public"][2])
    for ca in ("stranger", "private"):
        with pytest.raises(GitUnavailable, match="CERTIFICATE_VERIFY_FAILED"):
            _head(settings, https(pki[ca]))


def test_unset_the_git_host_keeps_the_trust_it_had(pki, https):
    """No CMAPI_GIT_CA_BUNDLE: a site whose Git host is signed by the CA in CMAPI_CA_BUNDLE works as before, and nothing else does."""
    settings = Settings(ca_bundle=pki["private"][2])
    assert _head(settings, https(pki["private"])) == "a" * 40
    with pytest.raises(GitUnavailable, match="CERTIFICATE_VERIFY_FAILED"):
        _head(settings, https(pki["public"]))


def test_a_git_bundle_that_is_not_there_stops_the_process():
    """A missing file must not fall back to some other trust: the process fails at start, naming the file."""
    with pytest.raises(FileNotFoundError):
        Settings(git_ca_bundle=Path("/nonexistent/git-ca.pem")).git_verify


def test_build_context_hands_the_git_trust_to_the_provider(monkeypatch, tmp_path, pki):
    """The wiring itself: build_context gives make_provider settings.git_verify, not settings.verify."""
    import cmapi.core.context as context_mod

    seen = {}

    class Stop(Exception):
        pass

    def capture(*args, **kwargs):
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(context_mod, "make_provider", capture)
    from conftest import DB_URL, EXAMPLES

    settings = Settings(config_dir=EXAMPLES / "local" / "config", database_url=DB_URL, ca_bundle=pki["private"][2],
                        git_ca_bundle=pki["public"][2], imports_dir=tmp_path, kube_token_file=Path("/nonexistent"))
    with pytest.raises(Stop):
        context_mod.build_context(settings, start_registry=False)
    verify = seen["verify"]
    assert isinstance(verify, ssl.SSLContext) and verify.verify_mode == ssl.CERT_REQUIRED and verify.check_hostname
    assert {c["subject"] for c in verify.get_ca_certs()} == {((("commonName", "public-ca"),),)}
