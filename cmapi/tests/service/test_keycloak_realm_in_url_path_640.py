"""A Keycloak realm's name is one path segment, encoded exactly once on the wire (#640).

Keycloak puts the realm's name into the issuer as a percent-encoded path segment: Urls.realmIssuer builds it with
UriBuilder.build, and Jakarta REST's UriBuilder says "All '%' characters in the stringified values will be encoded" and "By
default all '/' characters in the stringified values will be encoded in path templates". A realm `cmapi 640` has the issuer
`.../realms/cmapi%20640` (measured on Keycloak 26.6.4, the record of #640). cmapi took that segment as the name, so the user
lookups, which quote the name, sent `cmapi%2520640`: a realm that does not exist, and every lookup came back empty. RFC 3986,
section 2.4: "Implementations must not percent-encode or decode the same string more than once".

Keycloak refuses ":/?#@!$&()*+,;=[]\\" in a realm name (ReservedCharValidator, called by RealmManager on create) and allows
a space, "%" and any other character. The names with "/", "#" and "?" are here because the encoding must not depend on that
rule: a name stays one segment whatever it holds, except "", "." and "..", which realm_segment refuses (a dot-segment is
removed by the HTTP client, RFC 3986, section 5.2.4).

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

from conftest import AUDIENCE, DB_URL, FakeGit, FakeValidator, OneSecret
from cmapi.core import context as context_mod
from cmapi.core.errors import Problem
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
    jwks: list[dict]

    def _answer(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        target = self.path.encode("iso-8859-1")          # http.server keeps the request line's target undecoded
        self.seen.append((self.command, target))
        path = target.split(b"?", 1)[0]
        if self.command == "POST" and path.endswith(b"/protocol/openid-connect/token"):
            status, body = 200, {"access_token": "t", "expires_in": 300}
        elif path.startswith(b"/admin/realms/") and path.endswith(b"/users"):
            status, body = 200, [USER]
        elif path.startswith(b"/realms/") and path.endswith(b"/protocol/openid-connect/certs"):
            status, body = 200, {"keys": self.jwks}
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
def keycloak(keys):
    """A local HTTP server standing in for Keycloak: yields (base URL, the requests it received)."""
    seen: list[tuple[str, bytes]] = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                             type("Handler", (_Keycloak,), {"seen": seen, "jwks": [keys.jwk]}))
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


@pytest.mark.parametrize("issuer", [
    "https://sso.example.test/auth", "https://sso.example.test/realms/",
    "https://sso.example.test/realms/caf%E9",           # Latin-1 "é": not UTF-8
    "https://sso.example.test/realms/cmapi/",           # a trailing "/": never equal to a token's iss
    "https://sso.example.test/realms/cmapi/account",    # a path under the realm
    "https://sso.example.test/realms/cmapi?x=1", "https://sso.example.test/realms/cmapi#x",
    "https://sso.example.test/realms/other?x=/realms/cmapi",   # a query or fragment before the last /realms/ too
    "https://sso.example.test/realms/other#/realms/cmapi",     # (deploy/secrets-test.sh refuses both)
    "https://sso.example.test/realms/cmapi 640",        # the name typed where the segment belongs
    "https://sso.example.test/realms/100%", "https://sso.example.test/realms/a%zzb",   # "%" that starts no encoded octet
    "https://sso.example.test/realms/.", "https://sso.example.test/realms/..", "https://sso.example.test/realms/%2E%2E",
])
def test_split_issuer_refuses_what_names_no_realm(issuer):
    """A query or fragment anywhere, or anything but one percent-encoded, UTF-8 path segment after `/realms/`: an error at
    start that names the issuer, never a request outside the realm's path. OpenID Connect Discovery 1.0, section 3: the issuer
    has "no query or fragment components". RFC 3986, section 3.3: "/", "?" and "#" end a segment; section 2.1: pct-encoded is
    "%" and two hexadecimal digits."""
    with pytest.raises(ValueError) as refused:
        keycloak_admin.split_issuer(issuer)
    assert "not a Keycloak issuer" in str(refused.value) and repr(issuer) in str(refused.value)


@pytest.mark.parametrize(("issuer", "base", "name"), [
    ("https://sso.example.test/realms/realms", "https://sso.example.test", "realms"),
    ("https://sso.example.test/realms/realms/realms", "https://sso.example.test/realms", "realms"),    # http-relative-path
    ("https://sso.example.test/realms/a/realms/b", "https://sso.example.test/realms/a", "b"),
    ("https://sso.example.test/realms/caf%c3%a9", "https://sso.example.test", "café"),            # RFC 3986, 2.1: a-f as A-F
])
def test_split_issuer_takes_the_last_realms_segment(issuer, base, name):
    """The realm is the segment after the last `/realms/`: Keycloak's own path may hold the word (http-relative-path)."""
    assert keycloak_admin.split_issuer(issuer) == (base, name)


@pytest.mark.parametrize("name", ["", ".", ".."])
def test_a_dot_segment_is_not_sent_as_a_realm(keycloak, name):
    """quote() leaves "." and "..", and httpx removes a dot-segment from the path (RFC 3986, section 5.2.4): realm ".." was
    sent as GET /admin/users, outside any realm. Nothing is sent now."""
    base, seen = keycloak
    with pytest.raises(ValueError):
        keycloak_admin.realm_segment(name)
    with pytest.raises(ValueError):
        KeycloakAdminDirectory(base, name, "cmapi-directory", "s", context_mod._http_for_directory(True)).get_user("ola")
    with pytest.raises(ValueError):
        realm_sync.Realm(base, name, "cmapi-realm-admin", "s", False).get("/users")
    assert seen == []


@pytest.mark.parametrize(("name", "segment"), NAMES)
def test_the_directory_sends_the_realm_name_once_encoded(keycloak, name, segment):
    """KeycloakAdminDirectory over the HTTP function the API pods use (core/context.py, httpx)."""
    base, seen = keycloak
    d = KeycloakAdminDirectory(base, name, "cmapi-directory", "s", context_mod._http_for_directory(True))
    assert d.get_user("ola").employee_id == "1001"
    assert paths(seen) == [("POST", b"/realms/" + segment + b"/protocol/openid-connect/token"),
                           ("GET", b"/admin/realms/" + segment + b"/users")]


def context_for(issuer: str, test_config, tmp_path, monkeypatch):
    """build_context on the test configuration with this issuer in instance.yaml, and the Keycloak directory on."""
    config = tmp_path / "config"
    shutil.copytree(test_config, config)
    instance = config / "instance.yaml"
    instance.write_text(instance.read_text().replace("https://keycloak.test/realms/cmapi", issuer))
    monkeypatch.setenv("CMAPI_DATABASE_URL", DB_URL)
    monkeypatch.setattr(context_mod, "make_provider", lambda *a, **k: FakeGit())
    monkeypatch.setattr(context_mod, "CliValidator", lambda *a, **k: FakeValidator())
    settings = Settings(config_dir=config, database_url=DB_URL,
                        git_provider="gitea", git_url="https://git.test/api/v1", git_token="t", cursor_key="k",
                        link_key="l", metrics_port=0, imports_dir=None, kube_token_file=Path("/nonexistent"),
                        kube_ca_file=Path("/nonexistent"), directory_client_secret="s")
    return context_mod.build_context(settings, start_registry=False, import_source=OneSecret())


@pytest.mark.parametrize(("name", "segment"), NAMES[:4])
def test_build_context_looks_up_users_in_the_issuers_realm(keycloak, test_config, database, tmp_path, monkeypatch,
                                                           name, segment):
    """The whole path the API takes: instance.yaml's issuer, as Keycloak serves it, to the directory build_context makes."""
    base, seen = keycloak
    ctx = context_for(f"{base}/realms/{segment.decode()}", test_config, tmp_path, monkeypatch)
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


@pytest.mark.parametrize("tail", ["cmapi/", "cmapi/account", "cmapi%20640?x=1", "..", "100%", "other?x=/realms/cmapi"])
def test_build_context_refuses_a_bad_issuer_at_start(keycloak, test_config, database, tmp_path, monkeypatch, tail):
    """An issuer that is not Keycloak's stops the start, with its text in the error, before any request for it is sent."""
    base, seen = keycloak
    with pytest.raises(ValueError, match="not a Keycloak issuer"):
        context_for(f"{base}/realms/{tail}", test_config, tmp_path, monkeypatch)
    assert seen == []


@pytest.mark.parametrize(("name", "segment"), NAMES[:4])
def test_a_tokens_iss_is_compared_with_the_issuer_as_written(keycloak, keys, test_config, database, tmp_path, monkeypatch,
                                                             name, segment):
    """Decoding the issuer for the realm's name changes nothing in the check of `iss`: it stays the issuer as instance.yaml
    writes it, compared as a string (OpenID Connect Discovery 1.0, section 4.3: "MUST be identical"; RFC 9068, section 4:
    "MUST exactly match"; RFC 7519, section 2: "no transformations or canonicalizations applied"). The signing keys are read
    from the issuer as written too."""
    base, seen = keycloak
    issuer = f"{base}/realms/{segment.decode()}"
    ctx = context_for(issuer, test_config, tmp_path, monkeypatch)
    try:
        assert ctx.issuer == ctx.auth.issuer == issuer
        assert ctx.auth.authenticate(keys.token("ola", iss=issuer)).username == "ola"
        others = {f"{base}/realms/{name}", f"{base}/realms/{segment.decode().lower()}", issuer + "/",
                  f"{base}/realms/{keycloak_admin.realm_segment(segment.decode())}"} - {issuer}
        assert others, "every case needs a second spelling of its issuer"
        for other in sorted(others):                    # the decoded name, other hex digits, a slash, encoded twice
            with pytest.raises(Problem) as refused:
                ctx.auth.authenticate(keys.token("ola", iss=other))
            assert (refused.value.status, refused.value.detail) == (401, "Token issuer is not trusted"), other
    finally:
        ctx.registry.stop()
    assert paths(seen) == [("GET", b"/realms/" + segment + b"/protocol/openid-connect/certs")]


@pytest.mark.parametrize("ending", ["", "/"])
@pytest.mark.parametrize(("name", "segment"), NAMES[:4])
def test_realm_sync_main_takes_the_realm_from_the_issuer(keycloak, monkeypatch, capsys, name, segment, ending):
    """The Job from its environment, as the chart sets it (CMAPI_REALM_ISSUER is auth.issuer): main decodes the issuer's
    segment and Realm encodes the name, so the wire carries the issuer's own bytes. A "/" after the issuer is dropped, as
    before #640. The steps are replaced by one admin call: they build their paths through the same Realm.call."""
    base, seen = keycloak
    monkeypatch.setenv("CMAPI_REALM_ISSUER", f"{base}/realms/{segment.decode()}{ending}")
    monkeypatch.setenv("CMAPI_REALM_ADMIN_CLIENT_SECRET", "s")
    for unset in ("CMAPI_REALM_ADMIN_URL", "CMAPI_CA_BUNDLE", "CMAPI_REALM_TEST_USERS", "CMAPI_REALM_GROUPS",
                  "CMAPI_REALM_LDAP"):
        monkeypatch.delenv(unset, raising=False)
    monkeypatch.setattr(realm_sync, "user_profile", lambda rm: rm.get("/users", params={"username": "ola"}))
    for step in ("no_password_grant", "retire_legacy_bot", "access_token_type", "service_roles", "ldap"):
        monkeypatch.setattr(realm_sync, step, lambda *a, **k: None)
    monkeypatch.setattr(realm_sync, "groups", lambda *a, **k: {})
    realm_sync.main([])
    assert paths(seen) == [("GET", b"/realms/" + segment),
                           ("POST", b"/realms/" + segment + b"/protocol/openid-connect/token"),
                           ("GET", b"/admin/realms/" + segment + b"/users")]
    assert capsys.readouterr().out.splitlines()[-1] == f"realm {name} at {base}: in sync"
