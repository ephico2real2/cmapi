"""The If-Match surface after #571: what the header bytes mean (#581), what the document promises (#586, #582) and what a
replay returns (#587).

#581. RFC 9110 section 5.6.3 (https://www.rfc-editor.org/rfc/rfc9110.txt, read 2026-11-23): `OWS = *( SP / HTAB )`.
Section 5.5: `obs-text = %x80-FF`, and "A recipient SHOULD treat other allowed octets in field content (i.e., obs-text) as
opaque data." Starlette 0.41.3 decodes each header value as latin-1 (`datastructures.py`, `Headers.getlist`), so the
octets 0x85 and 0xA0 arrive as U+0085 and U+00A0, and Python's str.strip() with no argument removes both ("A character is
whitespace if ... its general category is Zs ... or its bidirectional class is one of WS, B, or S", docs.python.org,
str.isspace). So only SP and HTAB may pad `*`.

#586. OpenAPI 3.1.0, Parameter Object (https://spec.openapis.org/oas/v3.1.0.html): `required` "Determines whether this
parameter is mandatory ... its default value is false". The route requires If-Match (428), so the document says so.

#582. nginx 1.30.6 registers If-Match with ngx_http_process_unique_header_line, which answers 400 to a second line
(src/http/ngx_http_request.c at release-1.30.6, lines 93-95 and 1835-1856). deploy/tests/front-door-test.py measures it;
this file checks that the document tells a caller to send one field.

#587. A replay returns `request_view` of the original request row (plugins/namespaces/router.py, `_replay`), so its body
is that request as it is now, not a stored copy of the first response.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import httpx
import pytest

from cmapi.plugins.expiration.rules import utc_today
from test_expirations import created_namespace, write
from test_flow import NS, OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces/payments-dev"
NS_PATH = "/api/v1/clusters/{cluster_id}/namespaces/{ns}"
CURRENT_STATE = "original request in its current state"


def _created(client, ctx, keys) -> str:
    """Creates payments-dev in the test world and returns its etag, unquoted, as the body gives it."""
    assert client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).status_code == 202
    run_jobs(ctx)
    return client.get(URL, headers=auth(keys, "ola", **OLA)).json()["etag"]


def _move_git(client, git, keys, tag: str) -> None:
    git.branches["main"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"] += "# edited in Git\n"
    git._sha("main")
    assert client.get(URL, headers=auth(keys, "ola", **OLA)).json()["etag"] != tag, "Git moved: the tag is stale"


# The header value as raw octets. Starlette's TestClient re-encodes a header value as UTF-8 (b"\xa0" reaches the app as
# b"\xc2\xa0"), so these requests go through httpx's ASGITransport, which passes the supplied octets unchanged. uvicorn's
# HTTP/1.1 parsers (h11 and httptools) pass the obs-text octets 0xA0 and 0x85 unchanged too; around the value they drop
# SP and HTAB, which the guard strips anyway. Starlette's Request then decodes them as latin-1 for the real if_match
# dependency.
OBS_TEXT_STAR = [b"\xa0*\xa0", b"\x85*\x85"]
OWS_STAR = b" \t*\t "


def _raw_patch(client, url: str, headers: dict, body: dict) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://testserver") as raw:
            return await raw.patch(url, json=body, headers=headers)
    return asyncio.run(send())


def test_the_raw_transport_delivers_the_octets_unchanged():
    """The premise of the HTTP tests below: _raw_patch hands the app the octets it was given, not the UTF-8 form that
    TestClient would send (0xC2 0xA0 for 0xA0). An app that echoes the If-Match octets it received tells the two apart,
    where a status cannot: the value names no tag either way, so both forms answer the same 412."""
    from starlette.responses import Response
    from starlette.testclient import TestClient

    async def echo(scope, receive, send):
        await Response(dict(scope["headers"])[b"if-match"])(scope, receive, send)

    for value in OBS_TEXT_STAR:
        assert _raw_patch(TestClient(echo), "/", {"If-Match": value}, {}).content == value


@pytest.mark.parametrize("value", OBS_TEXT_STAR, ids=["nbsp", "nel"])
def test_obs_text_around_star_is_an_opaque_value_not_a_wildcard(world, value):
    """#581: 0xA0 and 0x85 are obs-text, not OWS, so the value is not `*`. It names no tag that matches: 412 with the
    current etag, as any stale value gets. On main, str.strip() made it `*` and the answer was 428."""
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    r = _raw_patch(client, f"{URL}?dryRun=true", {**auth(keys, "ola", **OLA), "If-Match": value}, {"tier": "medium"})
    assert r.status_code == 412, (value, r.text)
    assert r.json()["code"] == "precondition-failed" and r.json()["etag"] == tag, r.text


def test_sp_and_htab_around_star_still_make_the_wildcard(world):
    """#581, the other side: SP and HTAB are OWS (RFC 9110 section 5.6.3), so ` \\t*\\t ` is `*`, refused with 428."""
    client, ctx, git, kube, validator, keys = world
    _created(client, ctx, keys)
    r = _raw_patch(client, f"{URL}?dryRun=true", {**auth(keys, "ola", **OLA), "If-Match": OWS_STAR}, {"tier": "medium"})
    assert r.status_code == 428 and r.json()["code"] == "precondition-required", r.text


@pytest.mark.parametrize("value", OBS_TEXT_STAR, ids=["nbsp", "nel"])
def test_a_replay_with_obs_text_around_star_returns_the_original_request(world, value):
    """#581 on the replay path: require_if_match is the only check there (#495), so a value that is not `*` passes it and
    the replay returns the original request. On main the same value was 428."""
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    key = str(uuid.uuid4())
    first = client.patch(URL, json={"tier": "medium"},
                         headers={**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"{tag}"'})
    assert first.status_code == 202, first.text
    _move_git(client, git, keys, tag)
    replay = _raw_patch(client, URL, {**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": value},
                        {"tier": "medium"})
    assert replay.status_code == 202 and replay.json()["requestId"] == first.json()["requestId"], replay.text
    star = _raw_patch(client, URL, {**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": OWS_STAR},
                      {"tier": "medium"})
    assert star.status_code == 428 and star.json()["code"] == "precondition-required", star.text


def test_the_if_match_dependency_reads_the_octets_as_starlette_decodes_them():
    """#581 below the routes: the real Starlette Request and if_match dependency, then both guards of core/pipeline.py."""
    from starlette.requests import Request

    from cmapi.core.errors import Problem
    from cmapi.core.pipeline import check_if_match, require_if_match
    from cmapi.routers import if_match

    for raw in OBS_TEXT_STAR:
        value = if_match(Request({"type": "http", "headers": [(b"if-match", raw)]}), None)
        assert value == raw.decode("latin-1")
        require_if_match(value, "change")                   # the replay's check passes
        with pytest.raises(Problem) as fresh:
            check_if_match(value, "0123456789abcdef", "change")
        assert fresh.value.status == 412 and fresh.value.extra["etag"] == "0123456789abcdef"
    value = if_match(Request({"type": "http", "headers": [(b"if-match", OWS_STAR)]}), None)
    with pytest.raises(Problem) as star:
        require_if_match(value, "change")
    assert star.value.status == 428


def _if_match_params(spec: dict, writes_only: bool = False) -> list[dict]:
    """Each If-Match parameter of the document; with writes_only, a write's, without the conditional reads' (#590)."""
    return [p for path in spec["paths"].values() for method, op in path.items() if isinstance(op, dict)
            and not (writes_only and method == "get") for p in op.get("parameters", []) if p.get("name") == "If-Match"]


def test_the_document_marks_if_match_required_on_the_five_writes(world):
    """#586: PATCH, DELETE, :extend, :set and :makePermanent require If-Match, and a create takes none."""
    client, *_ = world
    spec = client.get("/openapi.json").json()
    ns = spec["paths"][NS_PATH]
    expected = [(NS_PATH, "patch"), (NS_PATH, "delete"),
                *[(f"{NS_PATH}/expiration:{op}", "post") for op in ("extend", "set", "makePermanent")]]
    for path, method in expected:
        params = [p for p in spec["paths"][path][method]["parameters"] if p["name"] == "If-Match"]
        assert len(params) == 1, (path, method)
        param = params[0]
        assert param["in"] == "header" and param["required"] is True, (path, method, param)
        assert param["schema"]["type"] == "string" and "anyOf" not in param["schema"], (path, method, param["schema"])
    assert len(_if_match_params(spec, writes_only=True)) == len(expected), "no other write takes If-Match"
    create = spec["paths"]["/api/v1/clusters/{cluster_id}/namespaces"]["post"]
    assert all(p["name"] != "If-Match" for p in create.get("parameters", [])), "a create takes no If-Match"
    assert "put" not in ns, "there is no namespace PUT"


def test_the_document_marks_it_required_and_the_route_still_answers_404_before_428(world):
    """#586, behaviour kept: only the document changed. FastAPI does not refuse the missing header with 422, so a
    namespace missing from Git is still 404 and an existing one without If-Match is still 428 (RFC 9110 section 13.2.1)."""
    client, ctx, git, kube, validator, keys = world
    missing = client.patch(f"{URL}?dryRun=true", json={"tier": "medium"}, headers=auth(keys, "ola", **OLA))
    assert missing.status_code == 404 and missing.json()["code"] == "object-not-found", missing.text
    _created(client, ctx, keys)
    bare = client.patch(f"{URL}?dryRun=true", json={"tier": "medium"}, headers=auth(keys, "ola", **OLA))
    assert bare.status_code == 428 and bare.json()["code"] == "precondition-required", bare.text


def test_the_document_says_to_send_the_tags_in_one_field(world):
    """#582: the front door refuses a second If-Match line, so the parameter tells a caller to send one field."""
    client, *_ = world
    for param in _if_match_params(client.get("/openapi.json").json()):
        assert "one comma-separated If-Match field" in param["description"], param["description"]
        assert "400 to a second If-Match line" in param["description"], param["description"]


def test_the_document_describes_a_replay_as_the_original_request_in_its_current_state(world):
    """#587: the PATCH operation, the If-Match parameter and both Idempotency-Key parameters promise what `_replay`
    returns, and none promises a stored first answer."""
    client, *_ = world
    spec = client.get("/openapi.json").json()
    patch = spec["paths"][NS_PATH]["patch"]
    assert CURRENT_STATE in patch["description"], patch["description"]
    # A write's If-Match and Idempotency-Key: a conditional read's If-Match (#590) has no replay.
    texts = [patch["description"]] + [p["description"] for path in spec["paths"].values() for method, op in path.items()
                                      if isinstance(op, dict) and method != "get" for p in op.get("parameters", [])
                                      if p["name"] in ("If-Match", "Idempotency-Key")]
    assert sum(1 for t in texts if CURRENT_STATE in t) == len(texts), [t for t in texts if CURRENT_STATE not in t]
    for text in texts:
        for stale in ("first answer", "stored answer", "first response", "request that its key opened"):
            assert stale not in text, (stale, text)


def test_a_replay_returns_the_request_as_it_is_now(world):
    """#587, the behaviour the words describe: after the requester cancels the request, a replay's body is the cancelled
    request with its cancel event, not the 202 body of the first response."""
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    key = str(uuid.uuid4())
    headers = {**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"{tag}"'}
    first = client.patch(URL, json={"tier": "medium"}, headers=headers)
    assert first.status_code == 202, first.text
    rid = first.json()["requestId"]
    cancelled = client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "ola", **OLA))
    assert cancelled.status_code == 200 and cancelled.json()["status"] != first.json()["status"], cancelled.text
    replay = client.patch(URL, json={"tier": "medium"}, headers=headers)
    assert replay.status_code == 202, replay.text
    assert replay.json()["requestId"] == rid
    assert replay.json()["status"] == cancelled.json()["status"], "the replay is the request now, not the first response"
    assert replay.json()["events"] == cancelled.json()["events"], "it carries the events added since"
    assert "cancel" not in [e["event"] for e in first.json()["events"]]
    assert "cancel" in [e["event"] for e in replay.json()["events"]], replay.json()["events"]


def test_the_expiry_writes_do_not_compare_the_justification_and_a_change_does(world):
    """#587, what the Idempotency-Key description says: an expiry write's fingerprint leaves out `justification`
    (plugins/namespaces/router.py, _expiry_write), so a retry that changes only it gets the original request, with the
    first justification. A change's fingerprint holds its whole body, so there the same retry is 409."""
    client, ctx, git, kube, validator, keys = world
    tag = created_namespace(client, ctx, keys, expiresAt=(utc_today() + timedelta(days=10)).isoformat())
    key = str(uuid.uuid4())
    first = write(client, keys, "extend", {"days": 7, "justification": "One sprint"}, tag, key=key)
    assert first.status_code == 202, first.text
    retry = write(client, keys, "extend", {"days": 7, "justification": "Another reason"}, tag, key=key)
    assert retry.status_code == 202 and retry.json()["requestId"] == first.json()["requestId"], retry.text
    assert retry.json()["justification"] == "One sprint"
    client.post(f"/api/v1/requests/{first.json()['requestId']}:cancel", headers=auth(keys, "ola", **OLA))
    key = str(uuid.uuid4())
    headers = {**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"{tag}"'}
    change = client.patch(URL, json={"tier": "medium", "justification": "One sprint"}, headers=headers)
    assert change.status_code == 202, change.text
    again = client.patch(URL, json={"tier": "medium", "justification": "Another reason"}, headers=headers)
    assert again.status_code == 409 and again.json()["code"] == "idempotency-replay", again.text


def _row(path: str, term: str) -> str:
    """The table row of a hand-written doc whose first cell is `term`."""
    from pathlib import Path

    lines = (Path(__file__).resolve().parents[3] / path).read_text().splitlines()
    rows = [line for line in lines if line.startswith(f"| {term} |")]
    assert len(rows) == 1, (path, term, rows)
    return rows[0]


@pytest.mark.parametrize("path", ["docs/04-api-examples.md", "docs/GLOSSARY.md"])
def test_the_api_docs_describe_the_replay_and_the_one_field(path):
    """#587 and #582 in the hand-written docs: the `If-Match` row of docs/04's rules table and of the glossary says to send
    one field, and the `Idempotency-Key` row says what a replay returns, whose key it is (#592), and when a retry is not
    one (the expiry writes' fingerprint without `justification`)."""
    match, idem = _row(path, "`If-Match`"), _row(path, "`Idempotency-Key`")
    assert "one comma-separated" in match and "second `If-Match` line" in match, match
    assert CURRENT_STATE in idem, idem
    assert "`onBehalfOf`" in idem and "#592" in idem, idem
    assert "gets 409 `idempotency-replay` instead" not in idem, ("#592 is fixed: a delegated retry replays", path)
    assert "do not compare `justification`" in idem, idem
    for row in (match, idem):
        for stale in ("first answer", "first response again", "stored answer"):
            assert stale not in row, (path, stale)


def test_the_document_tightens_only_the_five_writes_and_keeps_the_string_rules():
    """#586: _document_if_match_required changes If-Match on the five writes only, and drops only the null of
    `str | None`, so a rule of the string (here a maxLength) stays. Another operation's If-Match keeps its declaration."""
    import copy

    from cmapi.core.docs import _document_if_match_required

    declared = {"in": "header", "name": "If-Match", "required": False,
                "schema": {"anyOf": [{"type": "string", "maxLength": 128}, {"type": "null"}], "title": "If-Match"}}

    def op(operation_id: str) -> dict:
        return {"operationId": operation_id, "parameters": [copy.deepcopy(declared)]}

    spec = {"paths": {NS_PATH: {"get": op("namespaces_get_namespace"), "patch": op("namespaces_update_namespace")},
                      "/probe": {"post": op("probe_write")}}}
    _document_if_match_required(spec)
    assert spec["paths"][NS_PATH]["get"]["parameters"] == [declared]
    assert spec["paths"]["/probe"]["post"]["parameters"] == [declared]
    (patch,) = spec["paths"][NS_PATH]["patch"]["parameters"]
    assert patch["required"] is True
    assert patch["schema"] == {"type": "string", "maxLength": 128, "title": "If-Match"}, patch["schema"]


def test_the_design_rows_name_the_writes_that_the_api_serves(world):
    """#587: docs/02's concurrency row names the five writes that take If-Match, as the served document has them, and no
    namespace PUT; it says what the hash is and what a replay returns. Its idempotency row says when a retry is not one."""
    client, *_ = world
    spec = client.get("/openapi.json").json()
    ns = spec["paths"][NS_PATH]
    assert "put" not in ns and {"patch", "delete"} <= ns.keys()
    row = _row("docs/02-technical-design-v2.md", "Optimistic concurrency")
    assert "PATCH" in row and "DELETE" in row and "POST" in row and "PUT" not in row, row
    for op in ("extend", "set", "makePermanent"):
        assert f"expiration:{op}" in row and "post" in spec["paths"][f"{NS_PATH}/expiration:{op}"]
    assert "`plan_hash`" in row and "`<deleted>`" in row and "as JSON" in row and "16" in row, row
    assert "404 first" in row and "A namespace create takes no If-Match" in row, row
    assert "replay of one of these five writes still needs If-Match" in row, row
    assert CURRENT_STATE in row and "stored answer" not in row
    assert "one comma-separated If-Match field" in row
    idem = _row("docs/02-technical-design-v2.md", "Idempotency")
    assert "current state" in idem and "`onBehalfOf`" in idem and "#592" in idem, idem
