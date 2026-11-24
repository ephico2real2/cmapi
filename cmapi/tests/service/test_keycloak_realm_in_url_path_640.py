"""A Keycloak realm's name is one path segment, encoded exactly once on the wire (#640).

Keycloak puts the realm's name into the issuer as a percent-encoded path segment: Urls.realmIssuer builds it with
UriBuilder.build, and Jakarta REST's UriBuilder says "All '%' characters in the stringified values will be encoded" and "By
default all '/' characters in the stringified values will be encoded in path templates". A realm `cmapi 640` has the issuer
`.../realms/cmapi%20640` (measured on Keycloak 26.6.4, the record of #640). cmapi took that segment as the name, so the user
lookups, which quote the name, sent `cmapi%2520640`: a realm that does not exist, and every lookup came back empty. RFC 3986,
section 2.4: "Implementations must not percent-encode or decode the same string more than once".

Keycloak refuses ":/?#@!$&()*+,;=[]\\" in a realm name (ReservedCharValidator, called by RealmManager on create) and allows
a space, "%" and any other character. The names with "/", "#" and "?" are here because the encoding must not depend on that
rule: a name stays one segment whatever it holds.

Each test asserts the raw request target a real HTTP server received, the bytes on the request line, not a decoded path:
"cmapi%20640" and "cmapi%2520640" differ only there.
"""
from __future__ import annotations

import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest

from conftest import DB_URL, FakeGit, FakeValidator, OneSecret
from cmapi.core import context as context_mod
from cmapi.core.identity import keycloak_admin
from cmapi.core.identity.keycloak_admin import KeycloakAdminDirectory
from cmapi.settings import Settings
from cmapi.tools import realm_sync

# (the realm's name, its one path segment: what Keycloak writes in the issuer and what cmapi must send)
NAMES = [
    ("cmapi", b"cmapi"),                    # cmapi's own realm: the same bytes as before #640
    ("cmapi 640", b"cmapi%20640"),
    ("pct%41", b"pct%2541"),                # a literal "%": "%41" must not reach Keycloak as "A"
    ("café", b"caf%C3%A9"),            # UTF-8, as UriBuilder encodes it
    ("a/b", b"a%2Fb"),
    ("a#b", b"a%23b"),
    ("a?b", b"a%3Fb"),
]
USER = {"id": "u1", "username": "ola", "email": "ola@example.test", "enabled": True, "firstName": "Ola",
        "lastName": "Adeyemi", "attributes": {"employeeId": ["1001"]}}


class _Keycloak(http.server.BaseHTTPRequestHandler):
    """Answers like Keycloak for the calls cmapi makes, and records (method, raw request target) of each request."""
    seen: list[tuple[str, bytes]]

    def _answer(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        target = self.path.encode("iso-8859-1")          # http.server keeps the request line's target undecoded
        self.seen.append((self.command, target))
        path = target.split(b"?", 1)[0]
        if self.command == "POST" and path.endswith(b"/protocol/openid-connect/token"):
            status, body = 200, {"access_token": "t", "expires_in": 300}
        elif path.startswith(b"/admin/realms/") and path.endswith(b"/users"):
            status, body = 200, [USER]
        elif path.startswith(b"/realms/"):
            status, body = 200, {"realm": "r"}
        else:
            status, body = 404, {"error": "unexpected"}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _answer

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def keycloak():
    """A local HTTP server standing in for Keycloak: yields (base URL, the requests it received)."""
    seen: list[tuple[str, bytes]] = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), type("Handler", (_Keycloak,), {"seen": seen}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()
        server.server_close()


def paths(seen: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    return [(method, target.split(b"?", 1)[0]) for method, target in seen]


@pytest.mark.parametrize(("name", "segment"), NAMES)
def test_split_issuer_decodes_the_segment_once(name, segment):
    base = "https://sso.example.test/auth"
    assert keycloak_admin.split_issuer(f"{base}/realms/{segment.decode()}") == (base, name)
    assert keycloak_admin.realm_segment(name) == segment.decode()


@pytest.mark.parametrize("issuer", ["https://sso.example.test/auth", "https://sso.example.test/realms/",
                                    "https://sso.example.test/realms/caf%E9"])
def test_split_issuer_refuses_what_names_no_realm(issuer):
    """No realm segment, or one that is not UTF-8 (Latin-1 "é"): an error at start, never a lookup in another realm."""
    with pytest.raises(ValueError):
        keycloak_admin.split_issuer(issuer)


@pytest.mark.parametrize(("name", "segment"), NAMES)
def test_the_directory_sends_the_realm_name_once_encoded(keycloak, name, segment):
    """KeycloakAdminDirectory over the HTTP function the API pods use (core/context.py, httpx)."""
    base, seen = keycloak
    d = KeycloakAdminDirectory(base, name, "cmapi-directory", "s", context_mod._http_for_directory(True))
    assert d.get_user("ola").employee_id == "1001"
    assert paths(seen) == [("POST", b"/realms/" + segment + b"/protocol/openid-connect/token"),
                           ("GET", b"/admin/realms/" + segment + b"/users")]


@pytest.mark.parametrize(("name", "segment"), NAMES[:4])
def test_build_context_looks_up_users_in_the_issuers_realm(keycloak, test_config, database, tmp_path, monkeypatch,
                                                           name, segment):
    """The whole path the API takes: instance.yaml's issuer, as Keycloak serves it, to the directory build_context makes."""
    base, seen = keycloak
    config = tmp_path / "config"
    shutil.copytree(test_config, config)
    instance = config / "instance.yaml"
    instance.write_text(instance.read_text().replace("https://keycloak.test/realms/cmapi",
                                                     f"{base}/realms/{segment.decode()}"))
    monkeypatch.setenv("CMAPI_DATABASE_URL", DB_URL)
    monkeypatch.setattr(context_mod, "make_provider", lambda *a, **k: FakeGit())
    monkeypatch.setattr(context_mod, "CliValidator", lambda *a, **k: FakeValidator())
    settings = Settings(config_dir=config, database_url=DB_URL,
                        git_provider="gitea", git_url="https://git.test/api/v1", git_token="t", cursor_key="k",
                        link_key="l", metrics_port=0, imports_dir=None, kube_token_file=Path("/nonexistent"),
                        kube_ca_file=Path("/nonexistent"), directory_client_secret="s")
    ctx = context_mod.build_context(settings, start_registry=False, import_source=OneSecret())
    try:
        assert ctx.directory.get_user("ola").employee_id == "1001"
    finally:
        ctx.registry.stop()
    assert paths(seen) == [("POST", b"/realms/" + segment + b"/protocol/openid-connect/token"),
                           ("GET", b"/admin/realms/" + segment + b"/users")]


@pytest.mark.parametrize(("name", "segment"), NAMES)
def test_realm_sync_sends_the_realm_name_once_encoded(keycloak, name, segment):
    """The realm-sync Job, given the realm's name (main takes it from split_issuer): the wait for the realm, the sign-in and
    an admin call."""
    base, seen = keycloak
    realm_sync.wait_for_realm(base, name, False, attempts=1)
    assert realm_sync.Realm(base, name, "cmapi-realm-admin", "s", False).get("/users", params={"username": "ola"})
    assert paths(seen) == [("GET", b"/realms/" + segment),
                           ("POST", b"/realms/" + segment + b"/protocol/openid-connect/token"),
                           ("GET", b"/admin/realms/" + segment + b"/users")]
