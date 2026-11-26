"""#353: a string of a JSON body that holds a surrogate code point (U+D800 to U+DFFF) is refused, with the field named.

RFC 8259, section 8.2: the grammar "allows member names and string values to contain bit sequences that cannot encode Unicode
characters; for example, "\\uDEAD" (a single unpaired UTF-16 surrogate)", and "The behavior of software that receives JSON
texts containing such values is unpredictable". RFC 7493 (I-JSON), section 2.1: names and string values "MUST NOT include
code points that identify Surrogates", escaped or not. Python's json.loads, which FastAPI 0.162.2 reads a body with, keeps
such a code point, from a `\\ud800` escape and from the bytes ED A0 80 alike (it decodes with "surrogatepass").

Before the fix, such a value went on: PyYAML wrote it to the Git manifest as "a\\uD800", which sigs.k8s.io/yaml v1.6.0 does
not read ("found invalid Unicode character escape code"), and Kubernetes' JSON decoder (sigs.k8s.io/json) reads as U+FFFD,
another value than Git holds (both measured with Go 1.27.4; docs/reviews/2026-11-25-issue-353/README.md). Now
core/models.py's RequestBody refuses it before a route reads the body: 422 validation-failed, one error for each place, its
field the place in the body. Every body model is a RequestBody (test_client_input_653.py guards that).

A path or a query cannot carry one: uvicorn and Starlette decode each with urllib's unquote and parse_qsl, which replace
bytes that are not UTF-8 with U+FFFD. The last test proves the query and the path here.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from cmapi.plugins.expiration.rules import utc_today
from test_client_input_653 import NUL_REFUSED
from test_custom_tier_change import URL, custom, synced
from test_flow import AMY, NS, OLA, auth

ONE = f"{URL}/{NS['namespace']}"
MESSAGE = "holds U+D800, a surrogate code point, which is not a Unicode character"


def raw(body: dict) -> bytes:
    """The body as JSON bytes. json.dumps escapes U+D800 as `\\ud800`, so these are the bytes a client sends."""
    return json.dumps(body).encode("ascii")


def send(world, method: str, url: str, content: bytes, user: str = "ola", role: dict = OLA, **headers):
    client, ctx, git, kube, validator, keys = world
    return client.request(method, url, content=content,
                          headers={**auth(keys, user, **role), "Content-Type": "application/json", **headers})


def assert_refused(r, *fields: str, message: str = MESSAGE) -> None:
    assert r.status_code == 422, r.text
    problem = r.json()
    assert problem["code"] == "validation-failed", r.text
    assert problem["errors"] == [{"field": f, "message": message, "code": "string_surrogate"} for f in fields], r.text
    assert problem["detail"] == "The request is not valid: " + "; ".join(f"{f}: {message}" for f in fields), r.text


def recorded(world) -> int:
    client, ctx, git, kube, validator, keys = world
    return client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"]


# ---- a create

TEAM_ANNOTATION = {**NS, "annotations": {**NS["annotations"], "note": "a\ud800"}}


@pytest.mark.parametrize("dry_run", [False, True], ids=["submit", "dry-run"])
def test_a_create_with_a_team_annotation_holding_a_lone_surrogate_is_refused(world, dry_run):
    """The allowOther annotation `note` has no pattern, so nothing else looks at its value."""
    client, ctx, git, kube, validator, keys = world
    content = raw(TEAM_ANNOTATION)
    assert b'"a\\ud800"' in content
    r = send(world, "POST", URL + ("?dryRun=true" if dry_run else ""), content)
    assert_refused(r, "body.annotations.note")
    assert recorded(world) == 0 and git.prs == {}


def test_a_surrogate_sent_as_bytes_not_as_an_escape_is_refused_too(world):
    """ED A0 80 is U+D800 encoded as if it were a character: not UTF-8 (RFC 3629, section 3), and json.loads keeps it."""
    client, ctx, git, kube, validator, keys = world
    content = raw({**NS, "annotations": {**NS["annotations"], "note": "a"}}).replace(b'"note": "a"', b'"note": "a\xed\xa0\x80"')
    r = send(world, "POST", URL, content)
    assert_refused(r, "body.annotations.note")
    assert recorded(world) == 0 and git.prs == {}


def test_a_pair_sent_as_cesu_8_bytes_is_two_lone_surrogates_and_is_refused(world):
    """U+1F600 as CESU-8, each half of its UTF-16 pair as three bytes (ED A0 BD, ED B8 80): not UTF-8 (RFC 3629, section 3,
    "The definition of UTF-8 prohibits encoding character numbers between U+D800 and U+DFFF"). json.loads decodes the bytes
    with "surrogatepass" and does not join the two halves, as it joins a `\\ud83d\\ude00` escape: the place is named once,
    with the first."""
    client, ctx, git, kube, validator, keys = world
    content = raw({**NS, "justification": "a"}).replace(b'"justification": "a"', b'"justification": "a\xed\xa0\xbd\xed\xb8\x80"')
    assert json.loads(content)["justification"] == "a\ud83d\ude00"
    r = send(world, "POST", URL, content)
    assert_refused(r, "body.justification", message="holds U+D83D, a surrogate code point, which is not a Unicode character")
    assert recorded(world) == 0 and git.prs == {}


def message(code_point: str) -> str:
    return f"holds {code_point}, a surrogate code point, which is not a Unicode character"


@pytest.mark.parametrize("body,errors", [
    ({**NS, "labels": {**NS["labels"], "team2": "a\ud800"}}, [("body.labels.team2", "U+D800")]),
    ({**NS, "justification": "why\ud800"}, [("body.justification", "U+D800")]),
    ({**NS, "annotations": {**NS["annotations"], "no\ud800te": "x"}}, [("body.annotations.no\\ud800te.[key]", "U+D800")]),
    ({**NS, "x\ud800": 1}, [("body.x\\ud800.[key]", "U+D800")]),
    (custom(limitRange={"container": {"max": {"cpu": "1\udfff"}}}), [("body.limitRange.container.max.cpu", "U+DFFF")]),
    ({**NS, "labels": {**NS["labels"], "team2": "\ud800"}, "justification": "\ude00\ud83d"},
     [("body.labels.team2", "U+D800"), ("body.justification", "U+DE00")]),
    ({**NS, "x": {"a": [{"\udfff": {"b\ud800": "\udc00"}}]}},
     [("body.x.a.0.\\udfff.[key]", "U+DFFF"), ("body.x.a.0.\\udfff.b\\ud800.[key]", "U+D800"),
      ("body.x.a.0.\\udfff.b\\ud800", "U+DC00")]),
], ids=["label-value", "justification", "annotation-key", "unknown-member", "nested-limit", "each-place-named",
        "keys-at-depth"])
def test_a_surrogate_anywhere_in_a_create_is_refused_with_its_field(world, body, errors):
    """A key's place ends in `[key]`, as pydantic names a key's error. A key is shown with its surrogate escaped: the answer
    is UTF-8, which cannot carry one. A reversed pair is two lone surrogates: its place is named once, with the first."""
    client, ctx, git, kube, validator, keys = world
    r = send(world, "POST", URL, raw(body))
    assert r.status_code == 422, r.text
    expected = [{"field": f, "message": message(cp), "code": "string_surrogate"} for f, cp in errors]
    assert (r.json()["code"], r.json()["errors"]) == ("validation-failed", expected), r.text
    assert r.json()["detail"] == "The request is not valid: " + "; ".join(f"{e['field']}: {e['message']}" for e in expected)
    assert recorded(world) == 0 and git.prs == {}


def test_a_surrogate_pair_is_one_character_and_is_taken(world):
    """`\\ud83d\\ude00` is U+1F600: json.loads joins the pair, so the value is Unicode text and the create goes on."""
    client, ctx, git, kube, validator, keys = world
    content = raw({**NS, "justification": "ok \U0001F600"})
    assert b"\\ud83d\\ude00" in content
    r = send(world, "POST", URL + "?dryRun=true", content)
    assert r.status_code == 200, r.text


# ---- a change and a decision

def test_a_patch_with_a_team_annotation_holding_a_lone_surrogate_is_refused(world):
    client, ctx, git, kube, validator, keys = world
    etag = synced(world, {**custom(), "expiresAt": (utc_today() + timedelta(days=10)).isoformat()}, approvals=1)
    before, prs = recorded(world), dict(git.prs)
    for dry_run in (True, False):
        r = send(world, "PATCH", ONE + ("?dryRun=true" if dry_run else ""), raw({"annotations": {"note": "a\ud800"}}),
                 **{"If-Match": etag})
        assert_refused(r, "body.annotations.note")
    assert recorded(world) == before and git.prs == prs


def test_a_decision_comment_holding_a_lone_surrogate_is_refused(world):
    client, ctx, git, kube, validator, keys = world
    created = send(world, "POST", URL, raw({**NS, "tier": "large"}))
    assert created.status_code == 202, created.text
    rid = created.json()["requestId"]
    r = send(world, "POST", f"/api/v1/requests/{rid}:approve", raw({"comment": "c\ud800"}), user="amy", role=AMY)
    assert_refused(r, "body.comment")
    assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] == "pending_approval"


# ---- a query and a path

def test_a_surrogate_in_a_query_or_a_path_arrives_as_u_fffd(world):
    """Not a lone surrogate: urllib replaces the three bytes with U+FFFD, a character. A filter on it matches nothing, and
    no namespace has such a name. A guard, not a test of the fix: it passes before the fix too."""
    client, ctx, git, kube, validator, keys = world
    listed = client.get("/api/v1/requests?clusterId=%ED%A0%80", headers=auth(keys, "ola", **OLA))
    assert (listed.status_code, listed.json()["items"]) == (200, []), listed.text
    one = client.get(f"{URL}/a%ED%A0%80b", headers=auth(keys, "ola", **OLA))
    assert one.status_code == 404, one.text


# ---- bounds: a deep body, and a body of many places

def nested(depth: int, leaf: bytes) -> bytes:
    """NS with a member `x` that holds the leaf `depth` lists deep, as bytes: json.dumps itself recurses."""
    return raw(NS)[:-1] + b', "x": ' + b"[" * depth + leaf + b"]" * depth + b"}"


@pytest.mark.parametrize("depth", [600, 5000, 8000])
def test_a_body_nested_deeper_than_python_recurses_is_refused_with_422_not_500(world, depth):
    """json.loads parses it: its decoder counts its depth against CPython's C recursion limit, 10000 on this platform
    (CPython 3.12.14 Include/cpython/pystate.h C_RECURSION_LIMIT; Modules/_json.c _Py_EnterRecursiveCall), not against
    sys.getrecursionlimit(), 1000 (measured: depth 9900 parses, 10100 is json_invalid). The recursive walks of RequestBody
    raised RecursionError from about depth 600 here, which answered 500 internal-error; the walk is a loop now. A NUL leaf
    is found at any depth too."""
    plain = send(world, "POST", URL + "?dryRun=true", nested(depth, b'"a"'))
    assert plain.status_code == 422, plain.text
    assert plain.json()["errors"] == [{"field": "body.x", "message": "Extra inputs are not permitted", "code": "extra_forbidden"}]
    nul = send(world, "POST", URL + "?dryRun=true", nested(depth, b'"a\\u0000"'))
    assert nul.status_code == 422, nul.text
    assert nul.json()["errors"] == [{"field": "body", "message": "Value error, " + NUL_REFUSED, "code": "value_error"}]
    r = send(world, "POST", URL + "?dryRun=true", nested(depth, b'"a\\ud800"'))
    assert r.status_code == 422, r.text
    assert r.json()["errors"] == [{"field": "body.x" + ".0" * depth, "message": MESSAGE, "code": "string_surrogate"}]


def test_a_refusal_names_the_first_twenty_places_only(world):
    """One error for each place, the first 20 (MAX_PLACES of core/models.py): unbounded, a 1 MB body of 100,000 lone
    surrogates nested 400 deep was answered with 93 MB in 15 s."""
    client, ctx, git, kube, validator, keys = world
    r = send(world, "POST", URL + "?dryRun=true", raw({**NS, "x": ["\ud800"] * 1000}))
    assert r.status_code == 422, r.text[:400]
    assert [e["field"] for e in r.json()["errors"]] == [f"body.x.{i}" for i in range(20)], r.text[:400]
