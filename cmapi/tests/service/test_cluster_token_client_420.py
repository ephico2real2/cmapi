"""#420: no form of a cluster token reaches an error message, a cluster finding or a log line (docs/02 "Client rules": "The
token, and its JSON-escaped forms, are redacted from every error message before it is truncated").

A real HTTP server on 127.0.0.1 echoes the Authorization header it received, as some proxies do: raw, JSON-escaped (Python
and Go), escaped twice, cut short by the server, and placed so that cmapi's own 300-character cut would split it. The
clients are real KubeClients over a real socket. It lives with the service tests for their dependencies (structlog, which the
reference-code job does not install) and needs no database:

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_cluster_token_client_420.py -q -W ignore
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Iterator

import httpx
import pytest

from cmapi.core.clients.kube import ClusterUnreachable, KubeClient, KubeError
from cmapi.core.registry import ClusterPolicy, ClusterRegistry, HubImportSource, ImportSource

JWT = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjQyMCJ9.eyJzdWIiOiJzeXN0ZW06c2VydmljZWFjY291bnQ6Y21hcGktc3lzdGVtOmNtYXBpLXJlYWRlciJ9.SeCrEtSiGnAtUrE-420_xyz"
ODD = 'SeCrEt"quote\\back/slash<lt>&amp-420-0123456789'    # every character a JSON encoder escapes, and Go's <, >, &


def go_escape(text: str) -> str:
    """The body of a JSON string as Go's encoding/json writes it (the Kubernetes API server is Go)."""
    return json.dumps(text)[1:-1].replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# body(authorization header, token) -> the error body the server answers with
BODIES: dict[str, Callable[[str, str], str]] = {
    "raw": lambda auth, tok: f"rejected credential {auth}",
    "json": lambda auth, tok: json.dumps({"kind": "Status", "message": f"bad header {auth}"}),
    "go-json": lambda auth, tok: '{"kind":"Status","message":"bad header ' + go_escape(auth) + '"}',
    "json-twice": lambda auth, tok: json.dumps({"message": json.dumps({"echo": auth})}),
    "split-by-the-cut": lambda auth, tok: "x" * (300 - 7 - len(tok) // 2) + f"Bearer {tok}",
    "cut-by-the-server": lambda auth, tok: "proxy said: " + auth[: len(auth) - 9],
}


def leaked(text: str, token: str) -> list[str]:
    """Each 8-character piece of the token, or of one of its escaped forms, that the text holds."""
    return sorted({form[i:i + 8] for form in (token, json.dumps(token)[1:-1], go_escape(token))
                   for i in range(len(form) - 7) if form[i:i + 8] in text})


@pytest.fixture
def echo() -> Iterator[Callable[[int, str], str]]:
    """A server answering every request with `status` and BODIES[shape]; returns a function setting both, giving its URL."""
    answer = {"status": 401, "shape": "raw"}

    class Handler(BaseHTTPRequestHandler):
        def _reply(self) -> None:
            auth = self.headers.get("Authorization", "")
            body = BODIES[answer["shape"]](auth, auth.removeprefix("Bearer ")).encode()
            self.send_response(answer["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_PATCH = do_DELETE = _reply

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def set_answer(status: int, shape: str) -> str:
        answer.update(status=status, shape=shape)
        return f"http://127.0.0.1:{server.server_port}"
    try:
        yield set_answer
    finally:
        server.shutdown()


@pytest.mark.parametrize("token", [JWT, ODD], ids=["jwt", "escaped-chars"])
@pytest.mark.parametrize("shape", list(BODIES))
@pytest.mark.parametrize("status", [401, 500])
def test_no_error_of_the_client_holds_the_token(echo, status, shape, token):
    client = KubeClient("C", echo(status, shape), token)
    calls = [client.version, client.whoami, lambda: client.list("Namespace"), lambda: client.served("wgpolicyk8s.io/v1alpha2"),
             lambda: client.apply({"kind": "Namespace", "metadata": {"name": "n"}}), lambda: client.delete("Namespace", None, "n")]
    for call in calls:
        with pytest.raises(KubeError) as caught:
            call()
        assert caught.value.status == status
        assert leaked(str(caught.value), token) == [], str(caught.value)


@pytest.mark.parametrize("shape", list(BODIES))
@pytest.mark.parametrize("status", [401, 500])
def test_a_finding_and_its_log_line_hold_no_token(echo, capsys, status, shape):
    """Through the registry's checks: the finding GET /api/v1/clusters serves, and the warning `cluster_import`."""
    url = echo(status, shape)

    class Source(ImportSource):
        def list(self):
            return [{"name": "cmapi-cluster-c", "labels": {"cmapi.net/cluster-id": "C"}, "annotations": {},
                     "data": {"apiUrl": "https://c.example:6443", "token": ODD}}]

    reg = ClusterRegistry({"C": ClusterPolicy("C", "rnd", "clusters/C")}, Source(), start_caches=False,
                          client_factory=lambda cid, api_url, token, ca, *, insecure=False: KubeClient(cid, url, token))
    reg.refresh()
    st = reg.clusters["C"]
    assert st.status == ("auth_failed" if status == 401 else "unreachable")
    assert st.findings and "***" in st.findings[0], st.findings
    assert leaked(json.dumps(st.view(), default=str), ODD) == [], st.findings
    assert leaked(capsys.readouterr().out, ODD) == []


def test_a_transport_error_that_shows_the_header_holds_no_token(echo):
    """h11 refuses a header value with a newline and names it: "Illegal header value b'Bearer ...'"."""
    token = "SeCrEt-token-with\nnewline-0123456789"
    with pytest.raises(ClusterUnreachable) as caught:
        KubeClient("C", echo(401, "raw"), token).version()
    assert "Illegal header value" in str(caught.value)
    assert "SeCrEt-token-with" not in str(caught.value) and "newline-0123456789" not in str(caught.value), str(caught.value)


def test_the_hub_token_never_reaches_the_import_list_error(tmp_path):
    """The hub's own ServiceAccount token, in HubImportSource: its error is what `imports_list_failed` logs."""
    token = "SeCrEt-hub-token\nwith-newline-0123456789"
    (tmp_path / "token").write_text(token)
    source = HubImportSource("https://127.0.0.1:9", tmp_path / "token", tmp_path / "no-ca.crt", "cmapi-imports")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError(f"Illegal header value {request.headers['authorization'].encode()!r}")
    source.client = httpx.Client(base_url="http://hub", headers=source.client.headers, transport=httpx.MockTransport(refuse))
    with pytest.raises(RuntimeError) as caught:
        source.list()
    assert "SeCrEt-hub-token" not in str(caught.value) and "with-newline" not in str(caught.value), str(caught.value)


@pytest.mark.parametrize("text, expected", [
    ("a " + ODD + " b", "a *** b"),
    ("ends in " + ODD[:12], "ends in ***"),
    ("ends in " + ODD[:7], "ends in " + ODD[:7]),          # 7 characters: below MIN_PREFIX, no credential
    ("nothing here", "nothing here"),
])
def test_redact(text, expected):
    from cmapi.core.clients.redact import redact, secret_forms      # here, so the tests above run on a head without it
    assert redact(text, secret_forms(ODD)) == expected


def test_a_value_too_short_to_be_a_credential_is_not_redacted():
    from cmapi.core.clients.redact import redact, secret_forms
    assert secret_forms("t") == () and redact("missing field token", secret_forms("t")) == "missing field token"
