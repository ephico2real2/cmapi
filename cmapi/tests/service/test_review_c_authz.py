"""C2: every route, three callers; environments; self-approval through a second identity."""
from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from cmapi.core.authz import ROLE_PERMISSIONS, RolePolicy
from cmapi.core.identity.claims import Person
from cmapi.core.identity.directory import CachedDirectory, InMemoryDirectory
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs

PUBLIC = {("GET", "/api/v1/version"), ("GET", "/healthz"), ("GET", "/readyz"), ("GET", "/docs"), ("GET", "/docs/oauth2-redirect"),
          ("GET", "/openapi.json"), ("GET", "/openapi.yaml"), ("GET", "/redoc"), ("GET", "/docs/changelog"),
          # The page of a problem type: a caller with no token gets `unauthenticated`, and its type must resolve for that caller (#182).
          ("GET", "/problems"), ("GET", "/problems/{code}")}


def closure_permission(route):
    """The permission the route's require() dependency actually enforces."""
    for dep in route.dependant.dependencies:
        fn = dep.call
        if fn.__name__ == "dep" and fn.__closure__:
            for cell in fn.__closure__:
                if isinstance(cell.cell_contents, str):
                    return cell.cell_contents
    return None


def table(app):
    out = []
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods:
                out.append((m, r.path, (r.openapi_extra or {}).get("x-cmapi-permission"), closure_permission(r), r))
    return out


def test_declared_permission_is_the_enforced_one_and_every_route_answers(world, capsys):
    client, ctx, git, kube, validator, keys = world
    c = TestClient(client.app, raise_server_exceptions=False)
    rows, bad = [], []
    viewer = dict(roles=["cmapi-viewer"], groups=[])
    onb = dict(roles=["cmapi-onboarding"], groups=[])
    for m, path, declared, enforced, r in sorted(table(client.app), key=lambda x: x[1]):
        url = path.replace("{cluster_id}", "CRC").replace("{ns}", "nope").replace("{request_id}", "req-x").replace("{username}", "x")
        kw = {"json": {}} if m in ("POST", "PATCH") else {}
        no = c.request(m, url, **kw).status_code
        vi = c.request(m, url, headers=auth(keys, "vi", **viewer), **kw).status_code
        ob = c.request(m, url, headers=auth(keys, "ob", **onb), **kw).status_code
        rows.append(f"{m:6} {path:58} decl={declared} enforced={enforced} none={no} viewer={vi} onboarding={ob}")
        if (m, path) in PUBLIC:
            continue
        if declared != enforced and declared is not None:
            bad.append(("mismatch", m, path, declared, enforced))
        if no != 401:
            bad.append(("no token", m, path, no))
        allowed_v = declared is None or declared in ROLE_PERMISSIONS["cmapi-viewer"]
        allowed_o = declared is None or declared in ROLE_PERMISSIONS["cmapi-onboarding"]
        if not allowed_v and vi != 403:
            bad.append(("viewer", m, path, vi))
        if not allowed_o and ob != 403:
            bad.append(("onboarding", m, path, ob))
    with capsys.disabled():
        print("\n" + "\n".join(rows))
    assert not bad, bad


def test_onboarding_creates_only(world):
    client, ctx, git, kube, validator, keys = world
    ob = dict(roles=["cmapi-onboarding"], groups=[])
    ola = auth(keys, "ola", **OLA)
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=ola).json()["requestId"]
    run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=ola).json()["etag"]
    h = {**auth(keys, "bot-user", **ob), "If-Match": etag}
    assert client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"}, headers=h).status_code == 403
    assert client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).status_code == 403
    assert client.post("/api/v1/clusters/CRC/namespaces/payments-dev/expiration:extend", json={"days": 3}, headers=h).status_code == 403
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": "bot-made"}, headers=auth(keys, "bot-user", **ob))
    assert r.status_code == 202, r.text


def test_onboarding_cannot_cancel_someone_elses_request(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": "large"}, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    r = client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "bot-user", roles=["cmapi-onboarding"]))
    assert r.status_code == 403, r.text


@pytest.fixture
def rnd_only(world):
    """Role policy with operator-like and viewer-like roles limited to rnd, while the request lives in dev."""
    client, ctx, git, kube, validator, keys = world
    ctx.cfg.roles = RolePolicy({"roles": {"op-rnd": {"inherits": ["cmapi-operator"], "environments": ["rnd"]},
                                          "view-rnd": {"inherits": ["cmapi-viewer"], "environments": ["rnd"]},
                                          "appr-rnd": {"inherits": ["cmapi-approver"], "environments": ["rnd"]},
                                          "cmapi-operator": {"environments": ["rnd"]}}}, {"rnd", "dev"})
    return world


def dev_request(world, tier="large"):
    client, ctx, git, kube, validator, keys = world
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": tier}, headers=auth(keys, "ola", **OLA))
    return r.json()["requestId"]


def test_environment_role_cannot_read_status_in_another_environment(rnd_only):
    client, ctx, git, kube, validator, keys = rnd_only
    rid = dev_request(rnd_only)
    h = auth(keys, "v", roles=["view-rnd"])
    assert client.get(f"/api/v1/requests/{rid}", headers=h).status_code == 403
    assert client.get(f"/api/v1/requests/{rid}/events", headers=h).status_code == 403
    r = client.get(f"/api/v1/requests/{rid}/approval-status", headers=h)
    assert r.status_code == 403, f"approval-status answered {r.status_code} {r.text[:120]}"


def test_environment_role_cannot_approve_or_reject_in_another_environment(rnd_only):
    client, ctx, git, kube, validator, keys = rnd_only
    rid = dev_request(rnd_only)
    h = auth(keys, "a", roles=["appr-rnd"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])
    assert client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=h).status_code == 403
    assert client.post(f"/api/v1/requests/{rid}:reject", json={"comment": "x"}, headers=h).status_code == 403


def test_an_approval_in_another_environment_says_so_like_a_rejection(rnd_only):
    """#141: both answers name the environments the role covers. A caller with no approving role gets the plain forbidden."""
    client, ctx, git, kube, validator, keys = rnd_only
    rid = dev_request(rnd_only)
    h = auth(keys, "a", roles=["appr-rnd"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])
    approve = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=h)
    reject = client.post(f"/api/v1/requests/{rid}:reject", json={"comment": "x"}, headers=h)
    assert (approve.status_code, approve.json()["code"]) == (403, "environment-forbidden"), approve.text
    assert (reject.status_code, reject.json()["code"]) == (403, "environment-forbidden"), reject.text
    assert "['rnd'], not dev" in approve.json()["detail"]
    none = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "v", roles=["view-rnd"]))
    assert (none.status_code, none.json()["code"]) == (403, "forbidden"), none.text
    assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] == "pending_approval"


def test_environment_role_cannot_cancel_in_another_environment(rnd_only):
    client, ctx, git, kube, validator, keys = rnd_only
    rid = dev_request(rnd_only)
    # the built-in role limited to rnd: actor_is_operator matches it by name, whatever its environments
    r = client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "o", roles=["cmapi-operator"]))
    assert r.status_code == 403, f"{r.status_code} status {r.json().get('status')}"


def test_environment_role_cannot_retry_in_another_environment(rnd_only):
    client, ctx, git, kube, validator, keys = rnd_only
    rid = dev_request(rnd_only, tier="small")
    git.down = True
    from sqlalchemy import text
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='failed' where request_id=:r"), {"r": rid})
    git.down = False
    r = client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "o", roles=["op-rnd"]))
    assert r.status_code == 403, f"{r.status_code} {r.text[:150]}"


def test_environment_role_cannot_revert_in_another_environment(rnd_only):
    client, ctx, git, kube, validator, keys = rnd_only
    rid = dev_request(rnd_only, tier="small")
    from sqlalchemy import text
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": rid})
    r = client.post(f"/api/v1/requests/{rid}:revert", headers=auth(keys, "o", roles=["op-rnd"]))
    assert r.status_code == 403, f"{r.status_code} {r.text[:150]}"


def test_environment_role_cannot_confirm_a_prune_in_another_environment(rnd_only):
    client, ctx, git, kube, validator, keys = rnd_only
    rid = dev_request(rnd_only, tier="small")
    from sqlalchemy import text
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='awaiting_prune', action='delete' where request_id=:r"), {"r": rid})
    r = client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev", "clusterId": "CRC"}, headers=auth(keys, "o", roles=["op-rnd"]))
    assert r.status_code == 403, f"{r.status_code} {r.text[:150]}"


def strict(ctx):
    for e in ctx.cfg.approvals.environments.values():
        e["selfApproval"] = False


def test_self_approval_refused_when_the_environment_forbids_it(world):
    client, ctx, git, kube, validator, keys = world
    strict(ctx)
    jane = dict(roles=["cmapi-requester", "cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"], sub="sub-jane")
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": "large"}, headers=auth(keys, "jane", **jane))
    rid = r.json()["requestId"]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "jane", **jane))
    assert r.status_code == 409 and r.json()["code"] == "self-approval", r.text


def test_submitter_cannot_approve_what_it_filed_on_behalf_of_someone(world):
    """The second identity path: an automation account files for jane, then approves its own submission."""
    client, ctx, git, kube, validator, keys = world
    strict(ctx)
    ctx.pipeline.directory = CachedDirectory(InMemoryDirectory([Person(username="jane", email="jane@ephico2real.com", sub="sub-jane")]))
    bot = dict(roles=["cmapi-onboarding", "cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"], sub="sub-bot")
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": "large", "onBehalfOf": "jane"}, headers=auth(keys, "bot-user", **bot))
    assert r.status_code == 202 and r.json()["requester"]["requester"]["username"] == "jane", r.text
    rid = r.json()["requestId"]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "bot-user", **bot))
    assert r.status_code == 409 and r.json()["code"] == "self-approval", f"{r.status_code}: status {r.json().get('status')}"
    # and the person named cannot approve either
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "jane", roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"], sub="sub-jane"))
    assert r.status_code == 409 and r.json()["code"] == "self-approval"


def test_null_in_a_merge_patch_removes_the_key(world):
    """docs: 'null removes a key'."""
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "labels": {**NS["labels"], "mylabel": "x"}}, headers=h)
    run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    r = client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"labels": {"mylabel": None}}, headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 202, r.text
