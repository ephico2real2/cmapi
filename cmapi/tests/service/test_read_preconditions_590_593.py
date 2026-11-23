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
first Vary line and replaced them all, so a second line was lost.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from cmapi.core.cors import OriginVaryCORSMiddleware

# ---------------------------------------------------------------- #590 If-Match before If-None-Match

STALE = '"stale"'

# (If-Match lines, If-None-Match lines, status). "{etag}" is the answer's current ETag, quoted as its header gives it.
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
    lines = [("If-Match", v.format(etag=etag)) for v in if_match] + \
            [("If-None-Match", v.format(etag=etag)) for v in if_none_match]
    r = client.get(path, headers=[*credentials.items(), *lines])
    assert r.status_code == status, (lines, r.status_code, r.text[:300])
    if status == 412:
        # The same problem as a namespace's 412 (core/pipeline.py, check_if_match): the current tag without its quotes.
        assert r.headers["content-type"] == "application/problem+json"
        body = r.json()
        assert (body["code"], body["status"], body["etag"]) == ("precondition-failed", 412, etag[1:-1])
    elif status == 304:
        assert (r.content, r.headers["etag"]) == (b"", etag)
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


# ---------------------------------------------------------------- #593 Vary in the CORS middleware


def _vary_after_cors(vary: str | list[str] | None) -> list[bytes]:
    """The Vary lines that the middleware sends for an answer with these Vary lines, read from the raw ASGI message:
    TestClient would re-encode a latin-1 byte such as A0 as UTF-8 (C2 A0), so the bytes are taken from httpx's
    ASGITransport. The request has no Origin, so only cmapi's part of the middleware writes Vary."""
    lines = [vary] if isinstance(vary, str) else vary or []

    async def upstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"vary", line.encode("latin-1")) for line in lines]})
        await send({"type": "http.response.body", "body": b""})

    async def get():
        app = OriginVaryCORSMiddleware(upstream, allow_origins=["https://portal.example"])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/")

    return [v for k, v in asyncio.run(get()).headers.raw if k.lower() == b"vary"]


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
