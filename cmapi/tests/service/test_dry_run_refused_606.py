"""#606: a write that has no dry run refuses `dryRun`, so a preview never runs for real.

FastAPI ignores a query parameter that a route does not declare. Before the fix `POST .../req:approve?dryRun=true`
approved the request and `:cancel?dryRun=true` cancelled it. Now every write without a dry run answers 400
`dry-run-not-supported` to any `dryRun` and changes nothing, as the Kubernetes API server refuses a dry run on a call that
cannot honour one (apiserver, endpoints/handlers/rest.go, ConnectResource: "dryRun is not supported").
"""
from __future__ import annotations

from fastapi.routing import APIRoute
from sqlalchemy import text

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
    for route in client.app.routes:
        if not isinstance(route, APIRoute) or not route.methods & WRITES:
            continue
        query = {p.alias for p in route.dependant.query_params}
        calls = {d.call.__name__ for d in route.dependant.dependencies if d.call is not None}
        op = spec["paths"][route.path_format][next(iter(route.methods & WRITES)).lower()]
        declared = op["responses"].get("400", {}).get("content", {}).get("application/problem+json", {}).get("examples", {})
        if "dryRun" in query:
            planned.append(route.path_format)
            assert "refuse_dry_run" not in calls and "dry-run-not-supported" not in declared, route.path_format
        else:
            guarded.append(route.path_format)
            assert "refuse_dry_run" in calls, f"{route.path_format} takes no dryRun and does not refuse one"
            assert "dry-run-not-supported" in declared, f"{route.path_format} does not declare 400 dry-run-not-supported"
    assert len(planned) == 6 and "/api/v1/requests/{request_id}:approve" in guarded, (planned, guarded)


def test_the_writes_that_have_a_dry_run_still_answer_it(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and "planHash" in r.json(), r.text
