"""Three readers of request and response fields: two found by the Codex reviews of PRs #588 and #589, one while fixing them.

#590, If-Match on the conditional reads (core/etag.py, not_modified). RFC 9110 (https://www.rfc-editor.org/rfc/rfc9110.txt,
read 2026-11-23), section 13.2.2: "When recipient is the origin server and If-Match is present, evaluate the If-Match
precondition: ... if false, respond 412 (Precondition Failed)", before If-None-Match. Section 13.1.1: "If the field value
is "*", the condition is true if the origin server has a current representation", and "An origin server MUST use the
strong comparison function when comparing entity tags for If-Match". The reads only read If-None-Match, so a stale
If-Match with a matching If-None-Match answered 304.

#593, Vary in the CORS middleware (core/cors.py). Section 5.6.3: `OWS = *( SP / HTAB )`. str.strip() also removes U+00A0
and U+0085, which Starlette's latin-1 decode gives for the bytes A0 and 85.

#596, the same reader. Section 5.3: a field on several lines is one list. Starlette 0.41.3's add_vary_header read only the
first Vary line and replaced them all, so a second line was lost. It runs for an allowed origin (allow_explicit_origin), so
the answers to a listed origin are tested too.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest

from cmapi.core.cors import OriginVaryCORSMiddleware
from cmapi.core.problem_docs import problem_html

ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------- #590 If-Match before If-None-Match

STALE = '"stale"'

# (If-Match lines, If-None-Match lines, status). "{etag}" is the answer's current ETag, quoted as its header gives it, and
# "{tag}" the same without its quotes.
CASES = [
    ([STALE], ["{etag}"], 412),                       # 13.2.2 step 1: a false If-Match is 412 before If-None-Match
    ([STALE], ["*"], 412),
    ([STALE], ['"older"', "{etag}"], 412),            # If-None-Match on two lines still comes second
    (["{etag}"], ["{etag}"], 304),                    # a true If-Match: If-None-Match is evaluated next
    (["*"], ["{etag}"], 304),                         # `*` holds on a read: the answer exists (13.1.1, step 1)
    (["W/{etag}"], [], 412),                          # strong comparison: a weak tag never matches
    ([""], [], 412),                                  # an empty value lists no tag (13.1.1, step 3)
    ([STALE, "{etag}"], [], 200),                     # two lines are one list (section 5.3)
    (["{etag}"], [], 200),
    ([], [], 200),
    (["{etag}", STALE], [], 200),                     # ... in either order: the current tag on the first line
    (["*"], [], 200),
    (["*"], ['"old"', "W/{etag}"], 304),              # If-None-Match on two lines: the match is on the second
    (["*"], ["W/{etag}"], 304),                       # If-None-Match uses the weak comparison (13.1.2)
    (["{etag}, junk"], [], 412),                      # not a list of entity tags: lists none (13.1.1)
    (["*, {etag}"], [], 412),                         # `*` holds only alone
    ([], ["*, {etag}"], 200),                         # ... in If-None-Match too: matches nothing
    (["{tag}"], [], 200),                             # one tag without its quotes, read as on a write (#571; RFC 9110, 2.4)
    (["{tag}"], ["{etag}"], 304),
]

PATHS = ["/openapi.json", "/openapi.yaml", "/api/v1/metadata-keys", "/api/v1/capacity"]


def _credentials(path, keys):
    from test_flow import OLA, auth
    return auth(keys, "ola", **OLA) if path.startswith("/api/") else {}


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("if_match, if_none_match, status", CASES)
def test_a_conditional_read_evaluates_if_match_first(world, path, if_match, if_none_match, status):
    client, *_, keys = world
    credentials = _credentials(path, keys)
    first = client.get(path, headers=credentials)
    assert first.status_code == 200, first.text
    etag = first.headers["etag"]
    lines = [("If-Match", v.format(etag=etag, tag=etag[1:-1])) for v in if_match] + \
            [("If-None-Match", v.format(etag=etag, tag=etag[1:-1])) for v in if_none_match]
    r = client.get(path, headers=[*credentials.items(), *lines])
    assert r.status_code == status, (lines, r.status_code, r.text[:300])
    if status == 412:
        # The same problem as a namespace's 412 (core/pipeline.py, check_if_match): the current tag without its quotes.
        assert r.headers["content-type"] == "application/problem+json"
        body = r.json()
        assert (body["code"], body["status"], body["etag"]) == ("precondition-failed", 412, etag[1:-1])
    elif status == 304:
        # RFC 9110, 15.4.5: a 304 sends the Cache-Control and ETag that its 200 would have sent.
        assert (r.content, r.headers["etag"], r.headers["cache-control"]) == (b"", etag, first.headers["cache-control"])
    else:
        assert r.content == first.content and r.headers["etag"] == etag


def test_the_two_reads_document_if_match_and_its_412(world):
    """The document says what the route answers: If-Match is an optional parameter, and 412 a problem with the current
    `etag`. The curl sample does not send If-Match, which a read does not need."""
    client, *_ = world
    spec = client.get("/openapi.json").json()
    for path, op_id in (("/api/v1/metadata-keys", "core_metadata_keys"), ("/api/v1/capacity", "capacity_capacity")):
        op = spec["paths"][path]["get"]
        assert op["operationId"] == op_id
        params = {p["name"]: p for p in op["parameters"] if p["in"] == "header"}
        assert params["If-Match"]["required"] is False and params["If-None-Match"]["required"] is False
        example = op["responses"]["412"]["content"]["application/problem+json"]["examples"]["precondition-failed"]["value"]
        assert example["code"] == "precondition-failed" and example["etag"]
        assert "If-Match" not in op["x-codeSamples"][0]["source"]
    assert "422" not in spec["paths"]["/api/v1/metadata-keys"]["get"]["responses"]    # If-Match is not validated input
    # Only these two reads take If-Match: a read that documents it reads it (core/etag.py, not_modified).
    reads = {path for path, methods in spec["paths"].items()
             if any(p["in"] == "header" and p["name"].lower() == "if-match"
                    for p in methods.get("get", {}).get("parameters", []))}
    assert reads == {"/api/v1/metadata-keys", "/api/v1/capacity"}


def test_the_docs_say_what_a_conditional_read_answers():
    """docs/18 and docs/08 say what the code does: `If-Match: *` passes on a read, the metadata-keys answer is built at its
    first request, and a read's curl sample sends no optional precondition; docs/08 counts the operations of the contract."""
    config = (ROOT / "docs/18-configuration.md").read_text()
    assert "`If-Match: *` passes" in config and "The first request builds the answer and caches it" in config
    assert "built once at start" not in config
    status = (ROOT / "docs/08-code-status.md").read_text()
    spec = json.loads((ROOT / "cmapi/contract/openapi.json").read_text())
    count = sum(1 for methods in spec["paths"].values() for m in methods if m in ("get", "post", "put", "patch", "delete"))
    assert re.findall(r"Each of the (\d+) operations has one `x-codeSamples` entry", status) == [str(count)]
    assert "A conditional read sends neither optional precondition" in status


def test_the_precondition_failed_page_says_what_a_read_and_a_change_do():
    """The 412 of a read has the same `type` as a write's, so its page tells both callers what to do (problem_docs.py)."""
    page = problem_html("precondition-failed", "https://x.test/problems/", "t")
    action = re.search(r'<td id="action">(.*?)</td>', page)[1]
    assert "For a read, send it again without <code>If-Match</code>." in action
    assert "For a change, read the object again" in action


# ---------------------------------------------------------------- #593 Vary in the CORS middleware


ALLOWED = "https://portal.example"


def _cors_answer(vary: str | list[str] | None, origin: str | None = None) -> httpx.Response:
    """The answer of the middleware to a request from `origin`, for an upstream answer with these Vary lines. The bytes are
    taken from httpx's ASGITransport: TestClient would re-encode a latin-1 byte such as A0 as UTF-8 (C2 A0)."""
    lines = [vary] if isinstance(vary, str) else vary or []

    async def upstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"vary", line.encode("latin-1")) for line in lines]})
        await send({"type": "http.response.body", "body": b""})

    async def get():
        app = OriginVaryCORSMiddleware(upstream, allow_origins=[ALLOWED])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/", headers={"Origin": origin} if origin else {})

    return asyncio.run(get())


def _vary_after_cors(vary: str | list[str] | None, origin: str | None = None) -> list[bytes]:
    """The Vary lines of _cors_answer, as raw bytes. With no Origin, only cmapi's part of the middleware writes Vary."""
    return [v for k, v in _cors_answer(vary, origin).headers.raw if k.lower() == b"vary"]


def _tokens(lines: list[bytes]) -> list[bytes]:
    return [t.strip(b" \t").lower() for line in lines for t in line.split(b",")]


def test_a_vary_token_wrapped_in_nbsp_is_not_the_origin_token():
    """Bytes A0 around Origin are not OWS (RFC 9110, 5.6.3), so the token is not `Origin`, and the middleware adds one."""
    lines = _vary_after_cors("\xa0Origin\xa0")
    assert lines == [b"\xa0Origin\xa0, Origin"]
    assert b"origin" in _tokens(lines)


def test_a_vary_token_wrapped_in_nel_is_not_the_origin_token():
    lines = _vary_after_cors("\x85Origin\x85")
    assert b"origin" in _tokens(lines)


@pytest.mark.parametrize("vary", [" \tOrigin\t ", "Accept, origin", "*"])
def test_a_vary_that_has_origin_or_star_is_kept_as_it_is(vary):
    """SP and HTAB are OWS, so these already vary on Origin (or on everything): nothing is added."""
    assert _vary_after_cors(vary) == [vary.encode("latin-1")]


def test_an_answer_without_vary_gets_origin():
    assert _vary_after_cors(None) == [b"Origin"]


def test_each_vary_line_is_kept_when_origin_is_added():
    """Two Vary lines are one list (RFC 9110, 5.3): Origin joins them, and neither is lost (#596)."""
    lines = _vary_after_cors(["Accept", "Cookie"])
    assert lines == [b"Accept, Cookie, Origin"]


def test_origin_on_a_second_vary_line_is_read():
    """Origin on the second line already varies on Origin: nothing is added, and both lines stay."""
    assert _vary_after_cors(["Accept", "Origin"]) == [b"Accept", b"Origin"]


@pytest.mark.parametrize("origin", [None, "https://other.example", ALLOWED])
@pytest.mark.parametrize("upstream, expected", [
    (["Accept", "Cookie"], [b"Accept, Cookie, Origin"]),
    (["oRiGiN", "Cookie"], [b"oRiGiN", b"Cookie"]),
    (["Accept", "OrIgIn"], [b"Accept", b"OrIgIn"]),
    (["Origin"], [b"Origin"]),
    (["Accept", "*"], [b"Accept", b"*"]),
    (["*"], [b"*"]),
    ([], [b"Origin"]),
])
def test_each_origin_gets_every_vary_line_and_one_origin(upstream, expected, origin):
    """The same Vary for no origin, a denied one and the listed one: Starlette's allow_explicit_origin, which runs for the
    listed origin only, no longer rewrites Vary (#596). Only the listed origin gets Access-Control-Allow-Origin."""
    r = _cors_answer(upstream, origin)
    assert [v for k, v in r.headers.raw if k.lower() == b"vary"] == expected
    assert r.headers.get("access-control-allow-origin") == (ALLOWED if origin == ALLOWED else None)
