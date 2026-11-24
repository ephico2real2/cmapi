"""#653: a client's value answered 500 internal-error, on main a2a55f3 and on PR #652's head alike.

NUL. PostgreSQL stores no U+0000: "the character with code zero (sometimes called NUL) cannot be stored" in text, and "The
jsonb type also rejects \\u0000" (docs 16, sections 8.3 and 8.14). psycopg refuses one in a text parameter before the query
(psycopg/types/string.py), and the server refuses one in jsonb (UntranslatableCharacter). Os.stat refuses one in the path
of a static file (ValueError). Now a NUL is refused where it enters: a path or a query in main.py's RefuseNulMiddleware, a
JSON body, at any depth, in core/models.py's RequestBody. A header cannot carry one: uvicorn's h11 and httptools answer 400.

Dates. :extend moved the date before it checked the step, so a count of days past what a date holds was an OverflowError.
A date in the last grace period before 9999-12-31 made GET /expirations fail for everyone (graceEnds).
"""
from __future__ import annotations

import typing
from datetime import date, timedelta

import pytest

from cmapi.core.docs import api_routes
from conftest import build_world
from test_api_docs import bundles  # noqa: F401  (the fixture of the static files)
from test_custom_tier_change import SIZES, URL, approve_and_sync, custom, synced
from test_flow import AMY, NS, OLA, auth

ONE = f"{URL}/{NS['namespace']}"
ADMIN = dict(roles=["cmapi-admin"], groups=["/cmapi/app-cmapi-rbac-admin"])
NUL_REFUSED = "A value of the request holds the character NUL (U+0000), which cmapi does not take"
BODY_DETAIL = f"The request is not valid: body: Value error, {NUL_REFUSED}"


def assert_nul_refused(r, detail: str = NUL_REFUSED) -> None:
    assert r.status_code == 422, r.text
    assert (r.json()["code"], r.json()["detail"]) == ("validation-failed", detail), r.text


def recorded(world) -> int:
    client, ctx, git, kube, validator, keys = world
    return client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"]


# ---- a NUL in the path or the query

@pytest.mark.parametrize("url", ["/api/v1/requests?status=%00", "/api/v1/requests?clusterId=a%00", "/api/v1/requests?a%00=1",
                                 "/api/v1/requests/req%00x", "/api/v1/requests/req%00x/events", f"{URL}/a%00b"],
                         ids=["query-status", "query-cluster", "query-key", "path", "path-events", "path-namespace"])
def test_a_nul_in_a_query_or_a_path_is_validation_failed(world, url):
    client, ctx, git, kube, validator, keys = world
    assert_nul_refused(client.get(url, headers=auth(keys, "ola", **OLA)))


def test_a_nul_in_the_path_of_a_static_file_is_validation_failed(bundles, test_config, fresh_db, keys, monkeypatch):  # noqa: F811
    """os.stat raised ValueError("embedded null byte"): 422 with lstat's text on a2a55f3, 500 once #648 removed the
    ValueError handler. Starlette fixed it upstream in 51057d574 (#3139), after 0.41.3."""
    with build_world(test_config, keys, monkeypatch) as (client, *_):
        assert client.get("/static/swagger/swagger-ui.css").status_code == 200
        assert_nul_refused(client.get("/static/swagger/swagger-ui.css%00"))


# ---- a NUL in a JSON body, at the top or nested in labels and annotations

@pytest.mark.parametrize("body", [
    {**NS, "justification": "why\u0000"},
    {**NS, "annotations": {**NS["annotations"], "note": "a\u0000b"}},
    {**NS, "annotations": {**NS["annotations"], "no\u0000te": "x"}},
    {**NS, "labels": {**NS["labels"], "team2": "a\u0000b"}},
    custom(quota={**SIZES, "requests.cpu": "1\u0000"}),
    custom(limitRange={"container": {"max": {"cpu\u0000": "1"}}}),
], ids=["justification", "annotation-value", "annotation-key", "label-value", "quota-value", "limit-key"])
@pytest.mark.parametrize("dry_run", [False, True], ids=["submit", "dry-run"])
def test_a_nul_in_a_create_is_validation_failed_and_records_nothing(world, body, dry_run):
    """The dry run answers what the submit answers: before, it planned a body that the submit could not store."""
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL + ("?dryRun=true" if dry_run else ""), json=body, headers=auth(keys, "ola", **OLA))
    assert_nul_refused(r, BODY_DETAIL)
    assert recorded(world) == 0 and git.prs == {}


def test_a_nul_in_a_decision_or_a_switch_is_validation_failed(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post(URL, json={**NS, "tier": "large"}, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    for action in ("approve", "reject"):
        r = client.post(f"/api/v1/requests/{rid}:{action}", json={"comment": "c\u0000"}, headers=auth(keys, "amy", **AMY))
        assert_nul_refused(r, BODY_DETAIL)
    assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] == "pending_approval"
    r = client.post("/api/v1/admin/auto-approval:pause", json={"reason": "r\u0000"}, headers=auth(keys, "root", **ADMIN))
    assert_nul_refused(r, BODY_DETAIL)
    assert client.get("/api/v1/admin/auto-approval", headers=auth(keys, "ola", **OLA)).json()["paused"] is False


@pytest.mark.parametrize("method,path,body", [
    ("PATCH", "", {"annotations": {"note": "a\u0000"}}),
    ("PATCH", "", {"labels": {"cmapi.net/cost-center": "cc-1234"}, "justification": "w\u0000"}),
    ("POST", "/expiration:extend", {"days": 1, "justification": "w\u0000"}),
], ids=["patch-annotation", "patch-justification", "extend-justification"])
def test_a_nul_in_a_change_is_validation_failed(world, method, path, body):
    client, ctx, git, kube, validator, keys = world
    etag = synced(world, {**custom(), "expiresAt": (date.today() + timedelta(days=10)).isoformat()}, approvals=1)
    r = client.request(method, ONE + path, json=body, headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert_nul_refused(r, BODY_DETAIL)


def test_every_request_body_is_a_request_body(world):
    """A new body model that does not inherit RequestBody would let a NUL reach PostgreSQL again."""
    from cmapi.core.models import RequestBody

    client, *_ = world
    bodies = {}
    for route in api_routes(client.app):
        if route.body_field is not None:
            annotation = route.body_field.field_info.annotation
            bodies[route.path] = [t for t in (typing.get_args(annotation) or (annotation,)) if t is not type(None)]
    assert len(bodies) >= 10, bodies
    assert {p: m for p, models in bodies.items() for m in models if not issubclass(m, RequestBody)} == {}


# ---- dates past what a date holds

@pytest.mark.parametrize("days", [10 ** 10, 999_999_999, 3_000_000])
def test_extend_by_more_days_than_a_date_can_hold_is_expiration_limit(world, days):
    client, ctx, git, kube, validator, keys = world
    etag = synced(world, {**custom(), "expiresAt": (date.today() + timedelta(days=10)).isoformat()}, approvals=1)
    r = client.post(f"{ONE}/expiration:extend?dryRun=true", json={"days": days},
                    headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 422 and r.json()["code"] == "expiration-limit", r.text


def created_to(world, expires: str) -> str:
    """A namespace created with this expiry, past the lifetime limit, so approved by approver-platform. Returns its etag."""
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json={**NS, "expiresAt": expires}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    approve_and_sync(world, r.json()["requestId"], sum(s["count"] for s in r.json()["approval"]["slots"]))
    ctx.registry.cache("CRC")._list("Namespace")
    return client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]


def test_an_expiry_in_the_last_grace_period_is_refused_and_the_last_day_lists(world):
    """The grace period of the example rules is 7 days, so 9999-12-24 is the last expiry: GET /expirations shows its
    graceEnds, 9999-12-31. Before, 9999-12-31 was accepted, and GET /expirations answered 500 to everyone."""
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL + "?dryRun=true", json={**NS, "expiresAt": "9999-12-25"}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422, r.text
    assert (r.json()["code"], r.json()["detail"]) == ("validation-failed", "The expiry must be on or before 9999-12-24")
    etag = created_to(world, "9999-12-24")
    listed = client.get("/api/v1/expirations", headers=auth(keys, "ola", **OLA))
    assert listed.status_code == 200, listed.text
    assert [(i["name"], i["graceEnds"]) for i in listed.json()["items"]] == [(NS["namespace"], "9999-12-31")]
    r = client.post(f"{ONE}/expiration:extend?dryRun=true", json={"days": 1}, headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 422, r.text
    assert (r.json()["code"], r.json()["detail"]) == ("validation-failed", "The new date must be on or before 9999-12-24")


def test_extend_past_the_last_date_is_validation_failed_not_an_overflow(world):
    """9999-12-20 + 15 days is past 9999-12-31: base + timedelta raised OverflowError (500), within maxExtensionDays."""
    client, ctx, git, kube, validator, keys = world
    etag = created_to(world, "9999-12-20")
    r = client.post(f"{ONE}/expiration:extend?dryRun=true", json={"days": 15},
                    headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 422, r.text
    assert (r.json()["code"], r.json()["detail"]) == ("validation-failed", "The new date must be on or before 9999-12-24")
