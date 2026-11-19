"""Review of #453 (#424, #454): Codex's F1-F3 as OB3 corrected them. Offline: httpx.MockTransport, and one real local socket
for the h11 error a refused header value raises. Each test fails on #453's head (a9f219e) and passes with fixes-453.patch."""
from __future__ import annotations

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote_plus

import httpx
import pytest

import cmapi.core.git.oplog as oplog
import cmapi.tools.realm_sync as realm_sync
from cmapi.core.clients.redact import MASK, secret_forms
from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.tools.realm_sync import Realm

SPECIAL = "Credential/with+special&characters-123"     # a password or token with characters a form encoding changes
PLAIN = "ghp_0123456789abcdefABCDEF0123456789abcd"      # a GitHub token's alphabet: form encoding leaves it as it is


@pytest.fixture(autouse=True)
def registries(monkeypatch):
    """Each test with empty registries: oplog's and the realm sync's are process-global."""
    monkeypatch.setattr(oplog, "_FORMS", ())
    monkeypatch.setattr(realm_sync, "_SENT", ())


def offline(provider, handler, **kw):
    git = provider("https://git.test", "o/r", kw.pop("token", SPECIAL), **kw)
    git._client.close()
    git._client = httpx.Client(base_url="https://git.test", transport=httpx.MockTransport(handler))
    return git


# ---------------------------------------------------------------- F1: the form-encoded spelling, in one definition

@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
def test_a_form_encoded_echo_of_the_token_is_redacted(provider):
    git = offline(provider, lambda r: httpx.Response(500, text="rejected credential=" + quote_plus(SPECIAL)))
    with pytest.raises(GitUnavailable) as caught:
        git.branch_head("main")
    assert "the Git host answered 500: rejected credential=" + MASK in str(caught.value)
    assert quote_plus(SPECIAL) not in str(caught.value)


def test_a_form_encoded_echo_of_a_basic_auth_password_is_redacted():
    git = offline(GiteaProvider, lambda r: httpx.Response(502, text="denied password=" + quote_plus(SPECIAL)),
                  token="", basic_auth=("bot", SPECIAL))
    with pytest.raises(GitUnavailable) as caught:
        git.branch_head("main")
    assert quote_plus(SPECIAL) not in str(caught.value) and "denied password=" + MASK in str(caught.value)


def test_the_git_log_registry_takes_the_same_forms():
    """oplog.redact covers every request event and the Git layer's stderr: the same forms as the provider's own."""
    oplog.register_secret(SPECIAL)
    assert oplog.redact("remote: " + quote_plus(SPECIAL)) == "remote: " + MASK


def test_one_definition_for_the_git_hosts_the_git_log_and_the_realm_sync():
    git = offline(GitHubProvider, lambda r: httpx.Response(200))
    realm_sync.sends(SPECIAL)
    both = tuple(sorted({*secret_forms(SPECIAL), *secret_forms(quote_plus(SPECIAL))}, key=len, reverse=True))
    assert git._forms == oplog._FORMS == realm_sync._SENT == both


def test_a_value_shorter_than_eight_characters_has_no_form_in_any_spelling():
    """MIN_SECRET applies to the credential, not to a spelling of it: "a/b&c+d" is 7 characters, its quote_plus 13."""
    realm_sync.sends("a/b&c+d")
    oplog.register_secret("a/b&c+d")
    assert realm_sync._SENT == () and oplog._FORMS == ()


def test_control_a_token_form_encoding_leaves_unchanged_adds_no_form():
    """A control (passes on the head too): no over-redaction and no extra cost for the usual token."""
    git = offline(GitHubProvider, lambda r: httpx.Response(200), token=PLAIN)
    assert git._forms == oplog._FORMS == secret_forms(PLAIN)


# ---------------------------------------------------------------- F2: realm sync's transport errors

@pytest.mark.parametrize("stage", ["token", "admin"])
def test_a_realm_transport_error_ends_the_job_redacted(stage):
    secret, bearer = "RealmSecret-with-special-123", "AccessToken-with-special-456"
    rm = Realm("https://kc.test", "cmapi", "cmapi-realm-admin", secret, True)

    def handle(request):
        if request.url.path.endswith("/token") and stage == "admin":
            return httpx.Response(200, json={"access_token": bearer})
        raise httpx.LocalProtocolError("Illegal header value " + repr((secret if stage == "token" else bearer).encode()))
    rm.http = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(SystemExit) as caught:
        rm.call("GET", "/users")
    message = str(caught.value.code)
    assert "LocalProtocolError" in message and MASK in message
    assert ("GET /users" if stage == "admin" else "sign in as cmapi-realm-admin") in message
    assert secret not in message and bearer not in message


def test_a_refused_bearer_header_on_a_real_socket_never_reaches_the_printed_traceback():
    """h11 refuses a header value with a newline and names it: "Illegal header value b'Bearer <token>\\n'". The token is
    Keycloak's text. Real httpx, h11 and a local socket; the printed traceback is what the Job log would hold."""
    bearer = "BearerSecret-0123456789"

    class Keycloak(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            body = json.dumps({"access_token": bearer + "\n", "expires_in": 300}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Keycloak)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        rm = Realm(f"http://127.0.0.1:{server.server_port}", "cmapi", "cmapi-realm-admin", "client-secret-0123456789", False)
        with pytest.raises(SystemExit) as caught:
            rm.call("GET", "/users")
    finally:
        server.shutdown()
        server.server_close()
    printed = "".join(traceback.format_exception(caught.value))
    assert "LocalProtocolError" in printed and bearer not in printed


# ---------------------------------------------------------------- F3: a successful answer's commit subjects

@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
def test_a_commit_subject_that_holds_the_token_is_redacted(provider):
    commits = [{"sha": "a" * 40, "commit": {"message": "proxy echoed " + SPECIAL + "\n\nbody"}},
               {"sha": "b" * 40, "commit": {"message": "Merge cmapi/CRC/r1"}}]
    git = offline(provider, lambda r: httpx.Response(200, json=commits))
    assert git.log() == ["aaaaaaaa proxy echoed " + MASK, "bbbbbbbb Merge cmapi/CRC/r1"]


def test_the_git_layer_log_is_redacted_with_the_git_layer_token():
    """The worker's GitHub provider reads the log through its Git layer, whose token oplog holds (not the provider's)."""
    layer_token = "git-layer-token-0123456789"
    oplog.register_secret(layer_token)

    class Layer:
        def log(self, n):
            return ["cccccccc echoed " + layer_token, "dddddddd ordinary"]
    git = offline(GitHubProvider, lambda r: httpx.Response(200), token=PLAIN)
    git.workspace = Layer()
    assert git.log() == ["cccccccc echoed " + MASK, "dddddddd ordinary"]
