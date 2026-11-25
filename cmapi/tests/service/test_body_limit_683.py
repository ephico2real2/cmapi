"""#683: the API reads at most instance.yaml `http.maxRequestBodyBytes` of request content (default 1 MiB), and a 422
validation-failed names at most 20 errors.

Before the fix nothing limited a body: a 2.3 MB body of unknown members was answered with a 15.7 MB 422 in 2.1 s, on the event
loop (docs/reviews/2026-11-25-issue-683/README.md). RFC 9110, section 15.5.14: 413 "indicates that the server is refusing to
process a request because the request content is larger than the server is willing or able to process". OWASP API Security
Top 10 2023, API4: "Define and enforce a maximum size of data on all incoming parameters and payloads".

The cases a test client cannot send (chunked content in several messages, content longer than its Content-Length) go to the
application as ASGI messages (`asgi` below). A real uvicorn, with each of its two HTTP/1.1 parsers, proves the wire
(`test_on_a_real_server`).
"""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
import yaml

from cmapi.core.bodylimit import DEFAULT_MAX_REQUEST_BODY_BYTES, parse_http
from cmapi.core.config import ConfigError, load_instance
from conftest import build_world
from test_custom_tier_change import URL
from test_flow import NS, OLA, auth

LIMIT = 4096
DRY_RUN = URL + "?dryRun=true"
REPO = Path(__file__).resolve().parents[3]
NONPROD = REPO / "examples" / "instances" / "nonprod"
KEYS = REPO / "examples" / "cluster-configs" / "policies" / "metadata-keys.yaml"


def _config(test_config: Path, tmp_path: Path, http) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    for f in test_config.iterdir():
        (d / f.name).write_text(f.read_text())
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["http"] = http
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    return d


@pytest.fixture
def small(test_config, tmp_path, fresh_db, keys, monkeypatch):
    """The app with a limit of 4096 bytes, set in instance.yaml."""
    with build_world(_config(test_config, tmp_path, {"maxRequestBodyBytes": LIMIT}), keys, monkeypatch) as w:
        yield w


def padded(body: dict, size: int) -> bytes:
    """The body as JSON of exactly `size` bytes: JSON allows whitespace after the value (RFC 8259, section 2)."""
    content = json.dumps(body).encode()
    assert len(content) <= size
    return content + b" " * (size - len(content))


def headers(keys, **extra) -> dict[str, str]:
    return {**auth(keys, "ola", **OLA), "Content-Type": "application/json", **extra}


def recorded(world) -> int:
    client, ctx, git, kube, validator, keys = world
    return client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"]


def assert_too_large(status: int, content_type: str, body: bytes, limit: int = LIMIT) -> None:
    assert status == 413, body[:500]
    assert content_type == "application/problem+json"
    problem = json.loads(body)
    assert problem["code"] == "content-too-large" and problem["status"] == 413, problem
    assert problem["maxBytes"] == limit, problem
    assert problem["type"].endswith("/content-too-large"), problem
    assert problem["detail"] == f"The request content is larger than {limit} bytes, the most that this instance reads"


async def asgi(app, method: str, path: str, header_list: list[tuple[str, str]], chunks: list[bytes]):
    """Send one request to the application as ASGI messages: each chunk is one http.request message. Returns the status,
    the headers, the answer and how many messages of the content the application read."""
    pending = list(chunks)
    reads = 0
    sent: list[dict] = []
    raw_path, _, query = path.partition("?")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": raw_path, "raw_path": raw_path.encode(), "query_string": query.encode(), "root_path": "",
             "headers": [(k.lower().encode(), v.encode()) for k, v in header_list],
             "client": ("127.0.0.1", 50000), "server": ("testserver", 80), "state": {}}

    async def receive():
        nonlocal reads
        if pending:
            reads += 1
            chunk = pending.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(pending)}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    answer_headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], answer_headers, body, reads


# ---- a declared Content-Length over the limit


def test_a_content_length_over_the_limit_is_refused_before_the_application_runs(small):
    """No byte of the content is read, and no route runs: without a token the answer is still 413, not the 401 that the
    route's sign-in gives."""
    client, ctx, git, kube, validator, keys = small
    status, answer_headers, body, reads = asyncio.run(asgi(
        client.app, "POST", URL, [("Content-Type", "application/json"), ("Content-Length", str(LIMIT + 1))],
        [b"x" * (LIMIT + 1)]))
    assert_too_large(status, answer_headers["content-type"], body)
    assert reads == 0
    assert answer_headers.get("x-request-id")
    assert recorded(small) == 0 and git.prs == {}


def test_a_body_over_the_limit_with_its_length_is_refused_through_the_client(small):
    client, ctx, git, kube, validator, keys = small
    r = client.post(URL, content=padded(NS, LIMIT + 1), headers=headers(keys))
    assert_too_large(r.status_code, r.headers["content-type"], r.content)
    assert r.headers["x-request-id"]
    assert recorded(small) == 0 and git.prs == {}


def test_the_default_limit_is_one_mebibyte(world):
    client, ctx, git, kube, validator, keys = world
    assert DEFAULT_MAX_REQUEST_BODY_BYTES == 1024 * 1024
    r = client.post(DRY_RUN, content=padded(NS, DEFAULT_MAX_REQUEST_BODY_BYTES + 1), headers=headers(keys))
    assert_too_large(r.status_code, r.headers["content-type"], r.content, DEFAULT_MAX_REQUEST_BODY_BYTES)


# ---- content with no Content-Length (chunked), or more content than it declares


def test_chunked_content_over_the_limit_is_refused_at_the_message_that_passes_it(small):
    """RFC 9112, section 7.1: chunked content has no length up front. The count stops at the second message, which passes the
    limit; the third is never read."""
    client, ctx, git, kube, validator, keys = small
    status, answer_headers, body, reads = asyncio.run(asgi(
        client.app, "POST", URL, [*headers(keys).items(), ("Transfer-Encoding", "chunked")],
        [b" " * (LIMIT - 10), b" " * 11, b" " * 100]))
    assert_too_large(status, answer_headers["content-type"], body)
    assert reads == 2
    assert answer_headers.get("x-request-id")
    assert recorded(small) == 0 and git.prs == {}


def test_content_longer_than_its_content_length_is_counted_as_it_arrives(small):
    """A Content-Length of 10 that comes with LIMIT + 1 bytes: what is read counts, not what is declared. uvicorn itself
    passes only the declared bytes (test_on_a_real_server); this holds for any server or proxy that would pass more."""
    client, ctx, git, kube, validator, keys = small
    status, answer_headers, body, reads = asyncio.run(asgi(
        client.app, "POST", URL, [*headers(keys).items(), ("Content-Length", "10")],
        [padded(NS, LIMIT // 2), b" " * (LIMIT // 2 + 1)]))
    assert_too_large(status, answer_headers["content-type"], body)
    assert reads == 2
    assert recorded(small) == 0 and git.prs == {}


def test_the_middleware_answers_an_over_limit_read_that_no_handler_takes():
    """Without create_app's 413 handler (an application that reads its own body), the middleware answers the problem itself."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse, PlainTextResponse

    from cmapi.core.bodylimit import RequestBodyLimitMiddleware

    async def reader(scope, receive, send):
        body = await Request(scope, receive).body()
        await PlainTextResponse(f"read {len(body)}")(scope, receive, send)

    def problem_response(p):
        return JSONResponse(p.body(), status_code=p.status, media_type="application/problem+json")

    app = RequestBodyLimitMiddleware(reader, problem_response, LIMIT)
    status, answer_headers, body, reads = asyncio.run(asgi(app, "POST", "/", [("Transfer-Encoding", "chunked")],
                                                           [b"x" * LIMIT, b"x"]))
    assert_too_large(status, answer_headers["content-type"], body)
    assert reads == 2
    status, _, body, _ = asyncio.run(asgi(app, "POST", "/", [("Transfer-Encoding", "chunked")], [b"x" * 10, b"x" * 10]))
    assert (status, body) == (200, b"read 20")


# ---- the limit itself


def test_a_body_of_exactly_the_limit_is_read_and_one_byte_more_is_not(small):
    """The limit is the most bytes read: a create of exactly LIMIT bytes is planned (200 dry run), and so is the same create
    sent in chunks; one byte more is refused."""
    client, ctx, git, kube, validator, keys = small
    content = padded(NS, LIMIT)
    r = client.post(DRY_RUN, content=content, headers=headers(keys))
    assert r.status_code == 200, r.text
    assert "clusters/CRC/namespaces/payments-dev/namespace.yaml" in r.json()["changes"], r.text
    status, _, body, reads = asyncio.run(asgi(client.app, "POST", DRY_RUN, list(headers(keys).items()),
                                              [content[:1000], content[1000:]]))
    assert status == 200, body[:500]
    assert reads == 2
    r = client.post(DRY_RUN, content=padded(NS, LIMIT + 1), headers=headers(keys))
    assert_too_large(r.status_code, r.headers["content-type"], r.content)


def test_the_largest_real_create_fits_the_default_limit(world):
    """The measurement the default rests on (core/bodylimit.py): 50 team labels and 50 team annotations of the reference
    metadata-keys.yaml at their longest keys, and 64 KiB of annotation values, each byte a control character that json.dumps
    writes as a six-byte escape. The create is planned, and it is under half the default."""
    client, ctx, git, kube, validator, keys = world
    content = json.dumps(largest_create("\u0001"), indent=2).encode()
    assert len(content) * 2 < DEFAULT_MAX_REQUEST_BODY_BYTES, len(content)
    r = client.post(DRY_RUN, content=content, headers=headers(keys))
    assert r.status_code == 200, r.text[:2000]


def test_a_request_without_content_is_answered_as_before(small):
    """A guard: it passes before the fix too. A GET has no content, and a route that does not read its content is never
    counted, so a GET with chunked content over the limit is answered too."""
    client, ctx, git, kube, validator, keys = small
    r = client.get("/api/v1/version")
    assert r.status_code == 200 and r.json()["version"]
    status, _, body, reads = asyncio.run(asgi(client.app, "GET", "/api/v1/version", [("Transfer-Encoding", "chunked")],
                                              [b"x" * (LIMIT + 1)]))
    assert status == 200, body[:500]
    assert reads == 0


# ---- the answer of a 422 has at most 20 errors


def test_a_validation_failure_names_at_most_twenty_errors(world):
    """pydantic reports one error for each unknown member. Before the fix each was named: 60,000 members, 5.5 MB."""
    client, ctx, git, kube, validator, keys = world
    body = {**NS, **{f"x{i}": 0 for i in range(60_000)}}
    content = json.dumps(body).encode()
    assert len(content) < DEFAULT_MAX_REQUEST_BODY_BYTES
    r = client.post(DRY_RUN, content=content, headers=headers(keys))
    assert r.status_code == 422, r.text[:500]
    problem = r.json()
    assert problem["code"] == "validation-failed"
    assert problem["errors"] == [{"field": f"body.x{i}", "message": "Extra inputs are not permitted", "code": "extra_forbidden"}
                                 for i in range(20)]
    assert len(r.content) < 10_000, len(r.content)


# ---- instance.yaml http


@pytest.mark.parametrize("http, problem", [
    ("1048576", "http must be a mapping"),
    ({"maxRequestBodyBytes": 0}, "http.maxRequestBodyBytes is a whole number of bytes, 1 or more, not 0"),
    ({"maxRequestBodyBytes": -1}, "http.maxRequestBodyBytes is a whole number of bytes, 1 or more, not -1"),
    ({"maxRequestBodyBytes": True}, "http.maxRequestBodyBytes is a whole number of bytes, 1 or more, not True"),
    ({"maxRequestBodyBytes": "1m"}, "http.maxRequestBodyBytes is a whole number of bytes, 1 or more, not '1m'"),
    ({"maxRequestBodyBytes": 1.5}, "http.maxRequestBodyBytes is a whole number of bytes, 1 or more, not 1.5"),
    ({"maxBodyBytes": 4096}, "http has unknown fields ['maxBodyBytes']"),
])
def test_a_limit_that_is_not_one_stops_the_start(tmp_path, http, problem):
    with pytest.raises(ConfigError) as err:
        load_instance(_config(NONPROD, tmp_path, http), KEYS)
    assert [p for p in err.value.problems if p.startswith(f"instance.yaml: {problem}")], err.value.problems


@pytest.mark.parametrize("http, limit", [(None, 1024 * 1024), ({}, 1024 * 1024), ({"maxRequestBodyBytes": 1}, 1),
                                         ({"maxRequestBodyBytes": 3 * 1024 * 1024}, 3 * 1024 * 1024)])
def test_the_limit_comes_from_instance_yaml(tmp_path, http, limit):
    assert parse_http(http) == (limit, [])
    assert load_instance(_config(NONPROD, tmp_path, http), KEYS).max_request_body_bytes == limit


# ---- the chart writes instance.yaml http


def helm(tmp_path: Path, *sets: str) -> subprocess.CompletedProcess:
    """`helm template` against CRC's values, as test_cluster_trust_chart_434.py renders it."""
    (tmp_path / "ca.crt").write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    args = ["helm", "template", "cmapi", str(REPO / "deploy/helm/cmapi"), "-n", "cmapi", "-f",
            str(REPO / "deploy/environments/crc.yaml"), "--set", "cmapi.digest=sha256:" + "a" * 64,
            "--set", "cmapi_portal.digest=sha256:" + "b" * 64, "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}"]
    for s in sets:
        args += ["--set-json", s]
    return subprocess.run(args, capture_output=True, text=True)


def rendered_http(tmp_path: Path, *sets: str):
    r = helm(tmp_path, *sets)
    assert r.returncode == 0, r.stderr
    config = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "ConfigMap"
                  and d["metadata"]["name"] == "cmapi-config")
    return yaml.safe_load(config["data"]["instance.yaml"])["instance"]["http"]


def test_the_chart_writes_the_limit_and_its_schema_refuses_one_that_is_not(tmp_path):
    assert rendered_http(tmp_path) == {}
    assert parse_http({}) == (DEFAULT_MAX_REQUEST_BODY_BYTES, [])
    assert rendered_http(tmp_path, 'instance.http={"maxRequestBodyBytes":2097152}') == {"maxRequestBodyBytes": 2097152}
    for bad in ('instance.http={"maxRequestBodyBytes":0}', 'instance.http={"maxRequestBodyBytes":"1m"}',
                'instance.http={"maxBodyBytes":4096}'):
        r = helm(tmp_path, bad)
        assert r.returncode != 0 and "/instance/http" in r.stderr, (bad, r.stderr)


# ---- the wire


class Server:
    """uvicorn on 127.0.0.1 in a thread, with one of its HTTP/1.1 parsers."""

    def __init__(self, app, http: str):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, http=http, lifespan="off",
                                                    log_level="warning", access_log=False))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> int:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert time.monotonic() < deadline, "uvicorn did not start"
            time.sleep(0.02)
        return self.server.servers[0].sockets[0].getsockname()[1]

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(10)


def read_answer(sock: socket.socket) -> tuple[int, dict[str, str], bytes]:
    """One HTTP/1.1 answer with a Content-Length, read from the socket."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        assert chunk, data
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    fields = {k.strip().lower(): v.strip() for k, v in (line.split(":", 1) for line in lines[1:])}
    length = int(fields["content-length"])
    while len(rest) < length:
        chunk = sock.recv(65536)
        assert chunk, rest
        rest += chunk
    return int(lines[0].split()[1]), fields, rest[:length]


def request_head(method: str, path: str, fields: dict[str, str]) -> bytes:
    return (f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in fields.items())
            + "\r\n").encode()


@pytest.mark.parametrize("http", ["h11", "httptools"])
def test_on_a_real_server(small, http):
    """Over TCP to uvicorn 0.32.1:
    - a Content-Length over the limit is answered without any content sent: no 100 Continue is needed;
    - chunked content over the limit is answered 413, and the connection then serves the next request;
    - a Content-Length smaller than the content: uvicorn passes the declared bytes only (RFC 9112, section 6.3), and reads
      the rest as the next request. h11 answers the declared create first (200); httptools fails to parse the rest and
      answers its own 400 at once, before the application's answer. Neither passes the rest to the application (no 413)."""
    client, ctx, git, kube, validator, keys = small
    with Server(client.app, http) as port:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            sock.sendall(request_head("POST", URL, {**headers(keys), "Content-Length": str(LIMIT + 1)}))
            status, fields, body = read_answer(sock)
            assert_too_large(status, fields["content-type"], body)

        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            sock.sendall(request_head("POST", URL, {**headers(keys), "Transfer-Encoding": "chunked"}))
            for _ in range(3):
                sock.sendall(b"%x\r\n%s\r\n" % (LIMIT // 2, b" " * (LIMIT // 2)))
            sock.sendall(b"0\r\n\r\n")
            status, fields, body = read_answer(sock)
            assert_too_large(status, fields["content-type"], body)
            sock.sendall(request_head("GET", "/api/v1/version", {}))
            status, fields, body = read_answer(sock)
            assert status == 200 and json.loads(body)["version"]

        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            content = padded(NS, LIMIT * 2)
            sock.sendall(request_head("POST", DRY_RUN, {**headers(keys), "Content-Length": str(len(json.dumps(NS)))}))
            sock.sendall(content)
            status, fields, body = read_answer(sock)
            if http == "h11":
                assert status == 200, body[:500]
            else:
                assert (status, body) == (400, b"Invalid HTTP request received."), body[:500]
    assert recorded(small) == 0 and git.prs == {}


def label_key(i: int) -> str:
    """A key of allowOther at its longest: a DNS subdomain of ephico2real.com of 253 characters, '/', a name of 63."""
    tail = f".k{i:03d}.ephico2real.com"
    head = "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "."
    prefix = (head + "d" * 253)[: 253 - len(tail)] + tail
    return prefix + "/" + "n" * 60 + f"{i:03d}"


def largest_create(value_char: str) -> dict:
    """The reference metadata-keys.yaml at its maximums: 50 team labels and 50 team annotations at the longest key, labels at
    63 characters, annotation values at maxValueBytes 4096 each until maxBytesTotal 65536, the governed keys at their
    longest, a justification of 1000 characters."""
    per = 4096 // len(value_char.encode())
    values = [value_char * per] * 16 + [""] * 34
    labels = {"cmapi.net/team": "t" * 40, "cmapi.net/cost-center": "cc-4410", "cmapi.net/app": "a" * 40,
              "cmapi.net/rightsizing": "manual"}
    labels |= {label_key(i): "v" * 63 for i in range(50)}
    annotations = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}
    annotations |= {label_key(100 + i): values[i] for i in range(50)}
    return {"namespace": "p" * 63, "tier": "small", "labels": labels, "annotations": annotations,
            "justification": "j" * 1000}
