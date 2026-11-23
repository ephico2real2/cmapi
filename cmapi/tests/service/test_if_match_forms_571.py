"""#571: every form of If-Match on a write to an existing namespace, as the owner decided on 2026-11-23 ("Lists yes, * refused").

RFC 9110 section 13.1.1 (https://www.rfc-editor.org/rfc/rfc9110.txt, read 2026-11-23): `If-Match = "*" / #entity-tag`, and
"If the field value is a list of entity tags, the condition is true if any of the listed tags match", by the strong
comparison, so a weak tag never matches; "Otherwise, the condition is false", so a value that is not a list of entity
tags is 412. cmapi departs from step 1 on purpose: `*` proves no read, and cmapi requires If-Match so that clients "are
working with the correct copies" (RFC 6585 section 3), so `*` is 428 `precondition-required`, on a replay too.

An entity-tag may hold a comma inside its quotes (section 8.8.3, `etagc`), so a list is read tag by tag, never split on ",";
a recipient skips empty list elements (section 5.6.1.2); and a field sent on several lines is one list (section 5.3).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from test_flow import NS, OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces/payments-dev"
CHANGED = "The namespace changed in Git since you read it"
NO_TAG = "If-Match lists no strong entity tag"


def _created(client, ctx, keys) -> str:
    """Creates payments-dev in the test world and returns its etag, unquoted, as the body gives it."""
    assert client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).status_code == 202
    run_jobs(ctx)
    got = client.get(URL, headers=auth(keys, "ola", **OLA))
    assert got.headers["etag"] == f'"{got.json()["etag"]}"'
    return got.json()["etag"]


# (form, status, code, start of the detail). {tag} is the namespace's etag; "0" and "1" are tags it does not have.
FORMS = [
    ('"{tag}"', 200, None, None),                                   # the current tag
    ("{tag}", 200, None, None),                                     # without its quotes, as cmapi always took it
    ('"0", "{tag}"', 200, None, None),                              # a list that contains it, last
    ('"{tag}", "0"', 200, None, None),                              # and first
    ('"0",,"{tag}" ,', 200, None, None),                            # with empty elements and spaces (section 5.6.1.2)
    ('"0", "1"', 412, "precondition-failed", CHANGED),              # a list without it
    ('"x,{tag}"', 412, "precondition-failed", CHANGED),             # one tag that holds a comma: never split on ","
    ('W/"{tag}"', 412, "precondition-failed", NO_TAG),              # a weak tag never matches (strong comparison)
    ('W/"{tag}", W/"0"', 412, "precondition-failed", NO_TAG),       # nor a list of only weak tags
    ("*", 428, "precondition-required", "If-Match must name the namespace's etag"),
    ('"{tag}', 412, "precondition-failed", NO_TAG),                 # malformed: a quote not closed
    ('"{tag}" "0"', 412, "precondition-failed", NO_TAG),            # malformed: two tags with no comma
    ('"{tag}", *', 412, "precondition-failed", NO_TAG),             # malformed: * inside a list (section 13.1.1)
    ('{tag}, "0"', 412, "precondition-failed", NO_TAG),             # malformed: a tag without quotes in a list
]


@pytest.mark.parametrize("form, status, code, detail", FORMS, ids=[f[0] for f in FORMS])
def test_each_if_match_form_on_a_change(world, form, status, code, detail):
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    if_match = form.format(tag=tag)
    r = client.patch(f"{URL}?dryRun=true", json={"tier": "medium"}, headers={**auth(keys, "ola", **OLA), "If-Match": if_match})
    assert r.status_code == status, (if_match, r.text)
    if code:
        assert r.json()["code"] == code and r.json()["detail"].startswith(detail), (if_match, r.text)
    if status == 412:
        assert r.json()["etag"] == tag, "a 412 carries the current etag, so the caller can read again"
    if status == 428:
        assert "GET" in r.json()["detail"], "the 428 says to GET the namespace first (RFC 6585 section 3: explain how)"


def test_a_field_sent_on_two_lines_is_one_list(world):
    """RFC 9110 section 5.3: several field lines of one name are one list, as if joined with commas."""
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    headers = [*auth(keys, "ola", **OLA).items(), ("If-Match", '"0"'), ("If-Match", f'"{tag}"')]
    r = client.patch(f"{URL}?dryRun=true", json={"tier": "medium"}, headers=headers)
    assert r.status_code == 200, r.text


def test_a_delete_takes_a_list_and_refuses_star(world):
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    star = client.delete(URL, headers={**auth(keys, "ola", **OLA), "If-Match": "*"})
    assert star.status_code == 428 and star.json()["code"] == "precondition-required", star.text
    listed = client.delete(URL, headers={**auth(keys, "ola", **OLA), "If-Match": f'"0", "{tag}"'})
    assert listed.status_code == 202, listed.text


def test_an_expiry_write_takes_a_list(world):
    """:extend, :set and :makePermanent plan through the same comparison as PATCH (_expiry_write -> plan_namespace)."""
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    until = (date.today() + timedelta(days=20)).isoformat()
    r = client.post(f"{URL}/expiration:set?dryRun=true", json={"until": until, "justification": "One sprint"},
                    headers={**auth(keys, "ola", **OLA), "If-Match": f'"0", "{tag}"'})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_a_replay_with_star_is_428(world, method):
    """The replay path checks If-Match as the first request would (#495), so * is refused there as everywhere."""
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    key = str(uuid.uuid4())
    send = (lambda h: client.patch(URL, json={"tier": "medium"}, headers=h)) if method == "patch" else \
        (lambda h: client.delete(URL, headers=h))
    first = send({**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"{tag}"'})
    assert first.status_code == 202, first.text
    replay = send({**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": "*"})
    assert replay.status_code == 428 and replay.json()["code"] == "precondition-required", replay.text
    listed = send({**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"0", "{tag}"'})
    assert listed.status_code == 202 and listed.json()["requestId"] == first.json()["requestId"], listed.text


@pytest.mark.parametrize("value, tags", [
    ('"a"', ["a"]), ('"a", "b"', ["a", "b"]), ('"a,b"', ["a,b"]), ('"a,b" , "c"', ["a,b", "c"]), ('""', [""]),
    ('W/"a", "b"', ["b"]), (', ,"a",', ["a"]), ("a", ["a"]), ("", []), (",", []), ("*", []), ('"a"x', []),
    ('"a', []), ('"a" "b"', []), ("W/", []), ("W/a", []), ('a, "b"', []), ('"a", *', []),
    ('"a b"', []), ('"a\tb"', []),                      # etagc is %x21 / %x23-7E / obs-text: no space or tab in a tag
])
def test_the_parser_reads_rfc_9110s_grammar(value, tags):
    from cmapi.core.etag import if_match_tags      # imported here, so the service tests above also run on main
    assert if_match_tags(value) == tags



def test_the_document_says_how_each_form_is_read(world):
    """The behaviour above is what the If-Match parameter and both etag properties promise (#571): a list, * and a weak tag."""
    client, *_ = world
    spec = client.get("/openapi.json").json()
    params = [p for path in spec["paths"].values() for op in path.values() if isinstance(op, dict)
              for p in op.get("parameters", []) if p.get("name") == "If-Match"]
    assert len(params) == 5, "PATCH, DELETE, :extend, :set and :makePermanent take If-Match"
    schemas = spec["components"]["schemas"]
    for description in [p["description"] for p in params] + [schemas[s]["properties"]["etag"]["description"]
                                                               for s in ("NamespaceView", "PlanView")]:
        assert "A list of tags passes" in description and "`*` is 428" in description, description
        assert "weak tag" in description and "never matches" in description, description
