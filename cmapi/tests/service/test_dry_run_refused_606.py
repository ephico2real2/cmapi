"""#606: a write that has no dry run refuses `dryRun`, so a preview never runs for real.

FastAPI ignores a query parameter that a route does not declare. Before the fix `POST .../req:approve?dryRun=true`
approved the request and `:cancel?dryRun=true` cancelled it. Now every write without a dry run answers 400
`dry-run-not-supported` to any `dryRun` and changes nothing, as the Kubernetes API server refuses a dry run on a call that
cannot honour one (apiserver, endpoints/handlers/rest.go, ConnectResource: "dryRun is not supported").
"""
from __future__ import annotations

from sqlalchemy import text

from cmapi.core.docs import api_routes
from test_flow import AMY, NS, OLA, OPAL, auth

WRITES = {"POST", "PUT", "PATCH", "DELETE"}
ADMIN = dict(roles=["cmapi-admin"], groups=["/cmapi/app-cmapi-rbac-admin"])


def rows(ctx) -> dict[str, int]:
    with ctx.db.session() as s:
        return {t: s.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
                for t in ("change_requests", "request_events", "approvals", "audit_events", "jobs", "admin_switches")}


def pending(client, keys, name="payments-dev") -> str:
    """A large create, which waits for an approver."""
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": name, "tier": "large"}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    return r.json()["requestId"]


def refused(r) -> None:
    assert r.status_code == 400, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "dry-run-not-supported", r.text


def test_an_approve_or_a_cancel_with_dry_run_is_refused_and_changes_nothing(world):
    client, ctx, git, kube, validator, keys = world
    rid = pending(client, keys)
    before = rows(ctx)
    for value in ("true", "false", "All", ""):            # any dryRun: the call has none (Kubernetes' isDryRun)
        refused(client.post(f"/api/v1/requests/{rid}:approve?dryRun={value}", json={}, headers=auth(keys, "amy", **AMY)))
    # Repeated too, in either order: the guard tests that the parameter is present, not that it is there once.
    for query in ("dryRun=true&dryRun=false", "dryRun=false&dryRun=true"):
        refused(client.post(f"/api/v1/requests/{rid}:approve?{query}", json={}, headers=auth(keys, "amy", **AMY)))
    refused(client.post(f"/api/v1/requests/{rid}:reject?dryRun=true", json={"comment": "no"}, headers=auth(keys, "amy", **AMY)))
    refused(client.post(f"/api/v1/requests/{rid}:cancel?dryRun=true", json={}, headers=auth(keys, "ola", **OLA)))
    assert rows(ctx) == before
    assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] == "pending_approval"
    # Without dryRun each call is what it was.
    r = client.post(f"/api/v1/requests/{rid}:cancel", json={}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text


def test_the_admin_writes_with_dry_run_are_refused_and_change_nothing(world):
    client, ctx, git, kube, validator, keys = world
    before = rows(ctx)
    refused(client.post("/api/v1/admin/auto-approval:pause?dryRun=true", json={"reason": "incident 1234"},
                        headers=auth(keys, "ada", **ADMIN)))
    assert client.get("/api/v1/admin/auto-approval", headers=auth(keys, "ola", **OLA)).json()["paused"] is False
    refused(client.post("/api/v1/admin/prune:confirm?dryRun=true", json={"namespace": "payments-dev", "clusterId": "CRC"},
                        headers=auth(keys, "opal", **OPAL)))
    refused(client.post("/api/v1/clusters/CRC:probe?dryRun=true", headers=auth(keys, "opal", **OPAL)))
    assert rows(ctx) == before


def test_every_write_without_a_dry_run_refuses_one(world):
    """Each route of the app: a write that declares no `dryRun` has the guard, and the document declares its 400. A new
    write cannot forget it, because DocumentedRouter adds it."""
    client, ctx, *_ = world
    spec = client.get("/openapi.json").json()
    guarded, planned = [], []
    for route in api_routes(client.app):
        if not route.methods & WRITES:
            continue
        query = {p.alias for p in route.dependant.query_params}
        calls = {d.call.__name__ for d in route.dependant.dependencies if d.call is not None}
        op = spec["paths"][route.path_format][next(iter(route.methods & WRITES)).lower()]
        declared = op["responses"].get("400", {}).get("content", {}).get("application/problem+json", {}).get("examples", {})
        if "dryRun" in query:
            planned.append(route.path_format)
            assert "refuse_dry_run" not in calls and "dry-run-not-supported" not in declared, route.path_format
            assert "refuse_repeated_dry_run" in calls, f"{route.path_format} takes dryRun and does not refuse it repeated"
        else:
            guarded.append(route.path_format)
            assert "refuse_dry_run" in calls, f"{route.path_format} takes no dryRun and does not refuse one"
            assert "dry-run-not-supported" in declared, f"{route.path_format} does not declare 400 dry-run-not-supported"
    # The namespace writes and, since story #26, the adoption of one namespace.
    assert len(planned) == 7 and "/api/v1/clusters/{cluster_id}/namespaces/{ns}:adopt" in planned, (planned, guarded)
    assert "/api/v1/requests/{request_id}:approve" in guarded, (planned, guarded)


def test_the_writes_that_have_a_dry_run_still_answer_it(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and "planHash" in r.json(), r.text


def test_sign_in_comes_first_then_the_guard_then_the_permission(world):
    """The router's sign-in runs before a route's own dependencies (main.py, include_router), so a call without a token is
    401 with or without dryRun. A signed-in caller meets the guard before the route's permission check (#607 review)."""
    client, ctx, git, kube, validator, keys = world
    rid = pending(client, keys)
    path = f"/api/v1/requests/{rid}:approve"
    for query in ("", "?dryRun=true", "?dryRun=true&dryRun=false"):
        r = client.post(f"{path}{query}", json={})
        assert (r.status_code, r.json()["code"]) == (401, "unauthenticated"), (query, r.text)
        assert "www-authenticate" in r.headers
    requester = auth(keys, "ola", **OLA)                  # no requests:approve
    refused(client.post(f"{path}?dryRun=true", json={}, headers=requester))
    r = client.post(path, json={}, headers=requester)
    assert (r.status_code, r.json()["code"]) == (403, "forbidden"), r.text
    assert client.get(f"/api/v1/requests/{rid}", headers=requester).json()["status"] == "pending_approval"
