"""#424: no form of the Git bot's credential reaches an error, a request event, a log line or an API answer.

A Git host, or a proxy in front of it, may echo the request in an error body, the Authorization header included: raw, JSON-
escaped (Python and Go, once or twice), cut short by the host, or placed so that cmapi's own cut (200 or 300 characters) would
split it. The adapters are the real GitHubProvider and GiteaProvider over an httpx MockTransport; the end-to-end case runs the
worker and the API of the service on them. The realm sync (tools/realm_sync.py) prints Keycloak's answer, so it is here too.

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_git_host_redaction_424.py -q -W ignore
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote_plus

import httpx
import pytest

from cmapi.core.db.repo import JobRepo, utcnow
from cmapi.core.git.base import BranchRequest, GitUnavailable
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.core.ports import PrRef
from cmapi.tools.realm_sync import Realm, ldap
from test_cluster_token_client_420 import echo  # noqa: F401  (the fixture: a real HTTP server on 127.0.0.1)
from test_flow import NS, OLA, OPAL, auth

API = "https://git.test"
SHA = "c" * 40
PR = PrRef(7, f"{API}/o/r/pull/7", "cmapi/CRC/req-1", SHA)
# Every character a JSON encoder escapes, Go's <, > and &, and the "/" some encoders escape as "\/"; 47 characters.
TOKEN = 'GhToKeN"quote\\back/slash<lt>&amp-424-0123456789'
USER, PASSWORD = "cmapi-bot", 'Pa55"word\\with/odd<chars>&more-424'
BASIC = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()


def go_escape(text: str) -> str:
    return json.dumps(text)[1:-1].replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def straddle(cut: int) -> Callable[[str], str]:
    """A body in which cmapi's cut at `cut` characters falls in the middle of the credential."""
    def body(auth_header: str) -> str:
        scheme, _, credential = auth_header.partition(" ")
        return "x" * (cut - len(scheme) - 1 - len(credential) // 2) + auth_header
    return body


# body(the Authorization header as received) -> the error body the host answers with
BODIES: dict[str, Callable[[str], str]] = {
    "raw": lambda a: f"Bad credentials: {a}",
    "json": lambda a: json.dumps({"message": f"Bad credentials {a}", "documentation_url": "https://docs.git.test"}),
    "go-json": lambda a: '{"message":"bad header ' + go_escape(a) + '"}',
    "json-twice": lambda a: json.dumps({"message": json.dumps({"echo": a})}),
    "split-by-the-cut-at-300": straddle(300),
    "split-by-the-cut-at-200": straddle(200),
    "cut-by-the-host": lambda a: "proxy said: " + a[: len(a) - 9],
}


def leaked(text: str, *secrets: str) -> list[str]:
    """Each 8-character piece of a secret, or of one of its escaped forms, that the text holds."""
    return sorted({form[i:i + 8] for s in secrets for form in (s, json.dumps(s)[1:-1], go_escape(s))
                   for i in range(len(form) - 7) if form[i:i + 8] in text})


def echoing(status: int, shape: str, seen: list[str] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.headers.get("authorization", ""))
        return httpx.Response(status, text=BODIES[shape](request.headers.get("authorization", "")))
    return httpx.MockTransport(handle)


def github(transport: httpx.MockTransport) -> tuple[GitHubProvider, tuple[str, ...]]:
    git = GitHubProvider(API, "o/r", TOKEN)
    git._client = httpx.Client(base_url=API, headers=git._client.headers, transport=transport)
    return git, (TOKEN,)


def gitea(transport: httpx.MockTransport) -> tuple[GiteaProvider, tuple[str, ...]]:
    git = GiteaProvider(API, "o/r", TOKEN)
    git._client = httpx.Client(base_url=API, headers=git._client.headers, transport=transport)
    return git, (TOKEN,)


def gitea_basic(transport: httpx.MockTransport) -> tuple[GiteaProvider, tuple[str, ...]]:
    """The Gitea stand-in with Basic auth: the header carries base64 of user:password, which is the credential as sent."""
    git = GiteaProvider(API, "o/r", "", basic_auth=(USER, PASSWORD))
    git._client = httpx.Client(base_url=API, headers=git._client.headers, auth=(USER, PASSWORD), transport=transport)
    return git, (PASSWORD, BASIC)


REQ = BranchRequest("CRC", "req-1", "clusters/CRC/namespaces/n", "h", "m", {"clusters/CRC/namespaces/n/namespace.yaml": "x"}, {},
                    datetime(2026, 11, 18, tzinfo=timezone.utc))
CALLS: dict[str, Callable[[Any], Any]] = {
    "branch_head": lambda g: g.branch_head("main"),
    "read_folder": lambda g: g.read_folder("clusters/CRC/namespaces/n"),
    "log": lambda g: g.log(),
    "find_pr": lambda g: g.find_pr(PR.branch),
    "open_pr": lambda g: g.open_pr(PR.branch, SHA, "t", "b"),
    "pr_status": lambda g: g.pr_status(PR),
    "merge": lambda g: g.merge(PR, SHA),
    "comment": lambda g: g.comment(PR, "c"),
    "close": lambda g: g.close(PR, "c"),
    "set_check": lambda g: g.set_check(SHA, "cmapi/check", "success", "d"),
    "list_open": lambda g: g.list_open("cmapi/"),
}
GITEA_CALLS: dict[str, Callable[[Any], Any]] = {
    "push_request_branch": lambda g: g.push_request_branch(REQ),
    "contains": lambda g: g.contains("a" * 40, SHA),
    "changed_paths": lambda g: g.changed_paths(SHA),
    "list_branches": lambda g: g.list_branches("cmapi/"),
    "delete_branch": lambda g: g.delete_branch(PR.branch, SHA),
    "protect_default_branch": lambda g: g.protect_default_branch(["cmapi/check"]),
}


@pytest.mark.parametrize("shape", list(BODIES))
@pytest.mark.parametrize("status", [403, 405, 409, 422, 500, 429])
@pytest.mark.parametrize("make", [github, gitea, gitea_basic], ids=["github", "gitea", "gitea-basic"])
def test_no_error_or_log_line_of_an_adapter_holds_the_credential(capsys, make, status, shape):
    seen: list[str] = []
    git, secrets = make(echoing(status, shape, seen))
    calls = {**CALLS, **(GITEA_CALLS if isinstance(git, GiteaProvider) else {})}
    capsys.readouterr()
    texts: dict[str, str] = {}
    for name, call in calls.items():
        try:
            call(git)
        except Exception as exc:                                    # noqa: BLE001 - every error an adapter can raise
            texts[name] = f"{type(exc).__name__}: {exc} | {getattr(exc, 'host_message', '')}"
    logged = capsys.readouterr().out
    assert seen and all(any(s in h for s in secrets) for h in seen), "the host saw the credential, so its echo holds it"
    assert {name: leaked(text, *secrets) for name, text in texts.items() if leaked(text, *secrets)} == {}, texts
    assert leaked(logged, *secrets) == [], logged
    # The host's message did reach the errors and the log, redacted: the checks above are not vacuous. (A message cut at
    # 200 characters can end before the mask when the body put the credential past it; the log's 300 never does here.)
    assert texts and "git_op" in logged and "message" in logged and "***" in logged, logged


def test_a_transport_error_that_shows_the_header_holds_no_token(echo, capsys):
    """h11 refuses a header value with a newline and names it: "Illegal header value b'Bearer ...'". A real socket: the
    MockTransport never reaches h11."""
    token = "GhToKeN-with\nnewline-0123456789"
    git = GitHubProvider(echo(401, "raw"), "o/r", token)
    capsys.readouterr()
    with pytest.raises(GitUnavailable) as caught:
        git.branch_head("main")
    logged = capsys.readouterr().out
    assert "Illegal header value" in str(caught.value) and "git_op" in logged, str(caught.value)
    for text in (str(caught.value), logged):
        assert "GhToKeN-with" not in text and "newline-0123456789" not in text, text


@pytest.mark.parametrize("shape", ["raw", "json", "go-json", "split-by-the-cut-at-200", "cut-by-the-host"])
def test_no_request_event_api_answer_or_log_line_holds_the_token(world, capsys, shape):
    """The worker's push_branch reads main through the host, which answers 500 echoing the header, five times: the request
    fails with an `error` event. GET /api/v1/requests/{id} (the Requests tab) and GET /api/v1/admin/git-log show the host's
    message, redacted, and so does every log line of the run."""
    client, ctx, fake, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h).json()["requestId"]
    ctx.git, _ = github(echoing(500, shape))
    from cmapi.worker import Worker
    w = Worker(ctx, "w1", poll_seconds=0)
    capsys.readouterr()
    for _ in range(5):
        assert w.run_one()
        with ctx.db.session() as s:
            job = JobRepo(s).pending("push_branch", rid)
            if job is not None:
                job.run_after, job.locked_until = utcnow(), None
    view = client.get(f"/api/v1/requests/{rid}", headers=h)
    assert view.json()["status"] == "failed", view.json()["events"]
    notes = [e["note"] for e in view.json()["events"] if e["event"] == "error"]
    assert notes and "the Git host answered 500" in notes[0], notes
    # The worker keeps 300 characters of the error, so a body that puts the token past them ends the note before its mask.
    assert "***" in notes[0] or shape.startswith("split"), notes
    assert leaked(view.text, TOKEN) == [], view.text
    gl = client.get("/api/v1/admin/git-log", headers=auth(keys, "opal", **OPAL))
    assert gl.status_code == 502 and "***" in gl.json()["detail"], gl.text
    assert leaked(gl.text, TOKEN) == [], gl.text
    assert leaked(capsys.readouterr().out, TOKEN) == []


# ---------------------------------------------------------------- the realm sync's Job log (tools/realm_sync.py)

SECRET = 'KcSeCrEt/with+plus&amp"quote-424'
BEARER = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJjbWFwaS1yZWFsbS1hZG1pbiJ9.SiGnAtUrE-424_abcdef"
BIND = 'Bind"Pass\\word/424<x>&y'


def realm(handler: Callable[[httpx.Request], httpx.Response]) -> Realm:
    rm = Realm("https://kc.test", "cmapi", "cmapi-realm-admin", SECRET, True)
    rm.http = httpx.Client(transport=httpx.MockTransport(handler))
    return rm


@pytest.mark.parametrize("shape", ["raw", "json", "form", "split-by-the-cut-at-200"])
def test_a_refused_sign_in_never_prints_the_client_secret(shape):
    def handle(request: httpx.Request) -> httpx.Response:
        form = request.content.decode()                       # client_secret=<quote_plus(secret)>&...
        body = {"raw": f"invalid client {SECRET}", "json": json.dumps({"error": "unauthorized_client", "echo": SECRET}),
                "form": f"rejected form: {form}", "split-by-the-cut-at-200": "x" * (200 - len(SECRET) // 2) + SECRET}[shape]
        return httpx.Response(401, text=body)
    with pytest.raises(SystemExit) as caught:
        realm(handle)._bearer()
    message = str(caught.value.code)
    assert "***" in message and leaked(message, SECRET, quote_plus(SECRET)) == [], message


@pytest.mark.parametrize("shape", list(BODIES))
def test_a_refused_admin_call_never_prints_the_access_token(shape):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": BEARER, "expires_in": 300})
        return httpx.Response(403, text=BODIES[shape](request.headers["authorization"]))
    with pytest.raises(SystemExit) as caught:
        realm(handle).call("GET", "/users")
    message = str(caught.value.code)
    assert "***" in message and leaked(message, BEARER) == [], message


def test_the_full_sync_line_never_prints_the_bind_password(monkeypatch, capsys):
    """Keycloak's answer to the full sync is printed; a 500 that echoes the federation's configuration must not show the
    bind password, and neither may the line that stops the Job."""
    monkeypatch.setenv("CMAPI_LDAP_BIND_DN", "cn=cmapi,dc=example")
    monkeypatch.setenv("CMAPI_LDAP_BIND_PASSWORD", BIND)
    created: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/token"):
            return httpx.Response(200, json={"access_token": BEARER, "expires_in": 300})
        if path.endswith("/sync"):
            sent = created[0]["config"]["bindCredential"]           # the bind password, escaped twice, within the 120 printed
            return httpx.Response(500, text=json.dumps({"errorMessage": f"bind failed: {json.dumps(sent)}"}))
        if request.method == "POST":
            if not created:
                created.append(json.loads(request.content))
            return httpx.Response(201)
        if path == "/admin/realms/cmapi":
            return httpx.Response(200, json={"id": "realm-id"})
        if path.endswith("/components") and request.url.params.get("parent") is None and created:
            return httpx.Response(200, json=[{"name": "ldap", "id": "ldap-id"}])
        return httpx.Response(200, json=[])
    with pytest.raises(SystemExit) as caught:
        ldap(realm(handle), {"enabled": True, "requireSync": True, "connectionUrl": "ldaps://ldap.test", "usersDn": "ou=p",
                             "groupsDn": "ou=g"})
    printed = capsys.readouterr().out + str(caught.value.code)
    assert "LDAP full sync: 500" in printed and "***" in printed, printed
    assert leaked(printed, BIND) == [], printed
