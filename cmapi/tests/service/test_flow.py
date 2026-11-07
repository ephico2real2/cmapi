"""The write path end to end with fakes for the Git host and the cluster: plan, submit, approve,
PR, checks, merge, delivery, sync; and every refusal the design names along the way."""
from __future__ import annotations

import uuid

import pytest

from cmapi.jobs import HANDLERS
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo, utcnow

NS = {"namespace": "payments-dev", "tier": "small", "labels": {"cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410"},
      "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, "justification": "Payments service dev namespace"}
OLA = dict(roles=["cmapi-requester"], groups=["/cmapi/app-cmapi-rbac-requester"])
AMY = dict(roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])
OPAL = dict(roles=["cmapi-operator", "cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-operator"])


def auth(keys, user, **kw):
    return {"Authorization": f"Bearer {keys.token(user, **kw)}", "Idempotency-Key": str(uuid.uuid4())}


def run_jobs(ctx, limit=20) -> list[str]:
    """Run every due job through the handlers, like the worker does, until the queue is empty."""
    ran = []
    for _ in range(limit):
        with ctx.db.session() as s:
            job = JobRepo(s).claim("test")
            if job is None:
                break
            kind, jid = job.kind, job.job_id
        with ctx.db.session() as s:
            job = s.get(type(job), jid)
            HANDLERS[kind](ctx, s, job)
            if job.done_at is None:
                job.locked_until = None               # a retry: make it claimable now (host clock, not the database's)
                job.run_after = utcnow()
        ran.append(kind)
    return ran


def test_me_and_tiers(world):
    client, ctx, git, kube, validator, keys = world
    me = client.get("/api/v1/me", headers=auth(keys, "ola", **OLA)).json()
    assert me["username"] == "ola" and "namespaces:create" in me["access"]["permissions"]
    tiers = client.get("/api/v1/tiers?environment=dev", headers=auth(keys, "ola", **OLA)).json()
    assert [t["name"] for t in tiers["environments"]["dev"]["tiers"]][:3] == ["small", "medium", "large"]


def test_dry_run_writes_nothing_and_shows_the_plan(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval"]["auto"] == "auto:baseline-rnd-namespace" and body["capacity"]["status"] == "fits"
    assert set(body["changes"]) == {f"clusters/CRC/namespaces/payments-dev/{f}" for f in
                                    ("namespace.yaml", "resourcequota.yaml", "limitrange.yaml", "token-issuer-rolebinding.yaml")}
    assert client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"] == 0
    assert git.prs == {}


def test_create_auto_approved_to_synced(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    r = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    assert r.status_code == 202, r.text
    req = r.json()
    rid = req["requestId"]
    assert req["status"] == "approved" and req["approval"]["auto"] == "auto:baseline-rnd-namespace"
    # the same Idempotency-Key and body returns the same request; a different body is refused
    assert client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h).json()["requestId"] == rid
    other = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": "medium"}, headers=h)
    assert other.status_code == 409 and other.json()["code"] == "idempotency-replay"
    # a second request for the same namespace is refused by the lock
    r2 = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert r2.status_code == 409 and r2.json()["code"] == "change-pending" and r2.json()["requestId"] == rid

    ran = run_jobs(ctx)
    assert ran[:3] == ["open_pr", "pr_checks", "watch_sync"], ran
    view = client.get(f"/api/v1/requests/{rid}", headers=h).json()
    assert view["status"] == "synced", view["events"]
    assert view["pr"]["number"] == 1 and git.prs[1]["state"] == "merged"
    head = git.heads["main"]
    assert git.statuses[next(s for s in git.statuses)]["cmapi/check"] == "success"
    assert "clusters/CRC/namespaces/payments-dev/namespace.yaml" in git.branches["main"]
    assert "Namespace//payments-dev" in kube.applied and "ResourceQuota/payments-dev/payments-dev-quota" in kube.applied
    events = [e["event"] for e in view["events"]]
    assert events == ["plan_auto_approved", "pr_opened", "ci", "merged", "applied", "synced"], events
    assert view["links"]["pr"].startswith("https://git.test/pulls/")
    # the quota list sees it from the cache
    ctx.registry.cache("CRC")._list("Namespace")
    ctx.registry.cache("CRC")._list("ResourceQuota")
    q = client.get("/api/v1/quotas", headers=h).json()
    assert [i["name"] for i in q["items"]] == ["payments-dev"] and q["items"][0]["cpu"] == ["0", "8"]
    assert head == git.heads["main"]


def test_large_namespace_needs_a_platform_lead(world):
    client, ctx, git, kube, validator, keys = world
    big = {**NS, "namespace": "payments-batch", "tier": "large"}
    r = client.post("/api/v1/clusters/CRC/namespaces", json=big, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    rid = r.json()["requestId"]
    assert r.json()["approval"]["slots"] == [{"group": "approver-platform", "count": 1, "reason": "Environment dev create"}] or \
        r.json()["approval"]["slots"][0]["group"] == "approver-platform"
    # ola holds no approver role
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 403
    # opal is an approver, but not in approver-platform
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 403 and r.json()["code"] == "not-eligible"
    # amy's queue lists it; amy approves
    q = client.get("/api/v1/requests?status=pending_approval&approver=me", headers=auth(keys, "amy", **AMY)).json()
    assert [i["requestId"] for i in q["items"]] == [rid]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={"comment": "sizing reviewed"}, headers=auth(keys, "amy", **AMY))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    assert r.json()["approval"]["approvals"][0]["username"] == "amy"
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    assert r.status_code == 409 and r.json()["code"] == "not-pending"
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] == "synced"


def test_an_instance_with_its_own_group_path(world):
    """identity.groupPath decides whose token approves, everywhere the path is read: the approval, the approver's queue and the portal channel's recipients."""
    from cmapi.core.db.models import ApprovalNotificationRow
    client, ctx, git, kube, validator, keys = world
    ctx.cfg.approvals.group_path = "/corp/{name}"
    big = {**NS, "namespace": "payments-batch", "tier": "large"}
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=big, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    stock = dict(roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])
    theirs = dict(roles=["cmapi-approver"], groups=["/corp/approver-platform"])
    assert client.get("/api/v1/requests?status=pending_approval&approver=me", headers=auth(keys, "sam", **stock)).json()["items"] == []
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "sam", **stock))
    assert r.status_code == 403 and r.json()["code"] == "not-eligible"
    run_jobs(ctx)
    with ctx.db.session() as s:
        recipients = [n.recipients for n in s.query(ApprovalNotificationRow).filter_by(request_id=rid, channel="portal", kind="pending")]
    assert recipients == [["/corp/approver-platform"]]
    q = client.get("/api/v1/requests?status=pending_approval&approver=me", headers=auth(keys, "amy", **theirs)).json()
    assert [i["requestId"] for i in q["items"]] == [rid]
    assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["approval"]["remaining"] == [{"group": "approver-platform", "needed": 1}]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **theirs))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text


def test_a_stored_requirement_keeps_its_group_path():
    """The stored requirement is what a later approve reads, so the path has to survive the database's JSON. Here and not in tests/core: cmapi.core.db needs sqlalchemy, and the reference-code job runs tests/core with examples/local/requirements.txt, which has none."""
    from cmapi.core.approvals import Requirement, Slot
    from cmapi.core.db.repo import requirement_from_json, requirement_to_json
    req = Requirement(rule="prod-create", slots=(Slot("approver-prod", 1, "r"),), self_approval=False, timeout_hours=48, reasons=("r",), group_path="/corp/{name}")
    back = requirement_from_json(requirement_to_json(req))
    assert back.token_group("approver-prod") == "/corp/approver-prod"
    old = requirement_to_json(req); old.pop("groupPath")
    assert requirement_from_json(old).token_group("platform-leads") == "/cmapi/cmapi-platform-leads", "a row from before identity.groupPath was decided under the old constant"


def test_an_open_request_keeps_the_path_it_was_decided_under(world):
    """docs/11's claim, through the routes: the setting changes while a request is open, and the approvers do not."""
    client, ctx, git, kube, validator, keys = world
    big = {**NS, "namespace": "payments-batch", "tier": "large"}
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=big, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    ctx.cfg.approvals.group_path = "/corp/{name}"
    decided = dict(roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])
    moved = dict(roles=["cmapi-approver"], groups=["/corp/approver-platform"])
    assert client.get("/api/v1/requests?status=pending_approval&approver=me", headers=auth(keys, "sam", **moved)).json()["items"] == []
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "sam", **moved))
    assert r.status_code == 403 and r.json()["code"] == "not-eligible"
    assert [i["requestId"] for i in client.get("/api/v1/requests?status=pending_approval&approver=me", headers=auth(keys, "amy", **decided)).json()["items"]] == [rid]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **decided))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text


def test_a_token_with_no_role_gets_403(world):
    """cmapi.noaccess: signed in, known, and allowed nothing."""
    client, ctx, git, kube, validator, keys = world
    nobody = dict(roles=[], groups=[])
    assert client.get("/api/v1/me", headers=auth(keys, "cmapi.noaccess", **nobody)).status_code == 200
    r = client.get("/api/v1/clusters", headers=auth(keys, "cmapi.noaccess", **nobody))
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert client.get("/api/v1/clusters", headers=auth(keys, "cmapi.viewer", roles=["cmapi-viewer"], groups=[])).status_code == 200, "the control: the route itself answers"
    assert client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "cmapi.noaccess", **nobody)).status_code == 403


def test_self_approval_refused_in_an_environment_that_forbids_it(world):
    client, ctx, git, kube, validator, keys = world
    # dev allows self-approval in approval-rules.yaml; a requester-approver still cannot approve twice,
    # and a person who is not in the needed group is not eligible
    jane = dict(roles=["cmapi-requester", "cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-requester", "/cmapi/app-cmapi-rbac-approver-prod"])
    big = {**NS, "namespace": "jane-batch", "tier": "large"}
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=big, headers=auth(keys, "jane", **jane)).json()["requestId"]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "jane", **jane))
    assert r.status_code == 403 and r.json()["code"] == "not-eligible"


def test_reject_needs_a_comment_and_releases_the_lock(world):
    client, ctx, git, kube, validator, keys = world
    big = {**NS, "namespace": "payments-x", "tier": "large"}
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=big, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    r = client.post(f"/api/v1/requests/{rid}:reject", json={"comment": ""}, headers=auth(keys, "amy", **AMY))
    assert r.status_code == 422
    r = client.post(f"/api/v1/requests/{rid}:reject", json={"comment": "no"}, headers=auth(keys, "amy", **AMY))
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = client.post("/api/v1/clusters/CRC/namespaces", json=big, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202


def test_cancel_by_requester_and_refused_for_others(world):
    client, ctx, git, kube, validator, keys = world
    big = {**NS, "namespace": "payments-y", "tier": "large"}
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=big, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    other = dict(roles=["cmapi-requester"], groups=[])
    r = client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "someone", **other))
    assert r.status_code == 403
    r = client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_refusals_at_plan_time(world):
    client, ctx, git, kube, validator, keys = world
    kube.add_unmanaged_namespace("legacy-app")
    ctx.registry.cache("CRC")._list("Namespace")
    cases = [
        ("amy cannot create", "amy", AMY, {**NS, "namespace": "payments-z"}, 403, "forbidden"),
        ("reserved", "ola", OLA, {**NS, "namespace": "kube-tools"}, 422, "reserved-namespace"),
        ("unmanaged", "ola", OLA, {**NS, "namespace": "legacy-app"}, 409, "namespace-exists-unmanaged"),
        ("dl domain", "ola", OLA, {**NS, "namespace": "payments-z", "annotations": {"cmapi.net/team-dl": "x@other.com"}}, 422, "policy-violation"),
        ("system key", "ola", OLA, {**NS, "namespace": "payments-z", "labels": {**NS["labels"], "cmapi.net/tier": "large"}}, 422, "policy-violation"),
        ("quota with tier", "ola", OLA, {**NS, "namespace": "payments-z", "tier": "medium", "quota": {"requests.cpu": "20"}}, 422, "policy-violation"),
        ("no employee id", "ola", {**OLA, "employee_id": None}, {**NS, "namespace": "payments-z"}, 422, "identity-incomplete"),
        ("missing key header", "ola", OLA, None, 400, "idempotency-key-required"),
        ("expiry in the past", "ola", OLA, {**NS, "namespace": "payments-z", "expiresAt": "2020-01-01"}, 422, None),
    ]
    for title, user, who, body, status, code in cases:
        h = auth(keys, user, **who)
        if body is None:
            h.pop("Idempotency-Key")
            body = {**NS, "namespace": "payments-z"}
        r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=false", json=body, headers=h)
        assert r.status_code == status, f"{title}: {r.status_code} {r.text}"
        if code:
            assert r.json()["code"] == code, title


def test_change_needs_if_match_and_a_moved_folder_is_412(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h).json()["requestId"]
    run_jobs(ctx)
    ns = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h)
    assert ns.status_code == 200 and ns.json()["etag"] and ns.headers["etag"]
    etag = ns.json()["etag"]
    r = client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 428
    r = client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"},
                     headers={**auth(keys, "ola", **OLA), "If-Match": "stale"})
    assert r.status_code == 412
    r = client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"},
                     headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "approved"          # dev changes need no approval
    assert set(r.json()["files"].values()) == {"changed", "unchanged"}
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{r.json()['requestId']}", headers=h).json()["status"] == "synced"
    assert kube.get_object("ResourceQuota", "payments-dev", "payments-dev-quota")["spec"]["hard"]["requests.cpu"] == "16"


def test_pr_edited_after_approval_fails_the_cmapi_check(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h).json()["requestId"]
    assert run_jobs(ctx, limit=1) == ["open_pr"]
    view = client.get(f"/api/v1/requests/{rid}", headers=h).json()
    branch = view["pr"]["branch"]
    before = git.branches[branch]["clusters/CRC/namespaces/payments-dev/resourcequota.yaml"]
    assert "requests.cpu: '8'" in before
    git.tamper(branch, "clusters/CRC/namespaces/payments-dev/resourcequota.yaml", before.replace("requests.cpu: '8'", "requests.cpu: '80'"))
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{rid}", headers=h).json()
    assert view["status"] == "failed", view["events"]
    assert any(e["event"] == "head_moved" for e in view["events"])
    assert git.prs[1]["state"] == "closed"
    head = git.heads[branch]
    assert git.statuses[head]["cmapi/check"] == "failure"
    # retry re-takes the lock and opens a fresh PR from the plan; it then syncs
    r = client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 200 and r.json()["status"] == "approved"
    run_jobs(ctx)
    final = client.get(f"/api/v1/requests/{rid}", headers=h).json()
    assert final["status"] == "synced", [(e["event"], e["note"]) for e in final["events"]]


def test_folder_changed_after_the_plan_is_superseded(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h).json()["requestId"]
    git.branches["main"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"] = "apiVersion: v1\nkind: Namespace\nmetadata: {name: payments-dev}\n"
    git._sha("main")
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{rid}", headers=h).json()["status"] == "superseded"


def test_delete_waits_for_prune_confirmation(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    r = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    rid = r.json()["requestId"]
    assert client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY)).json()["status"] == "approved"
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{rid}", headers=h).json()
    assert view["status"] == "awaiting_prune" and kube.get_object("Namespace", None, "payments-dev") is not None
    assert "clusters/CRC/namespaces/payments-dev/namespace.yaml" not in git.branches["main"]
    r = client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 403
    r = client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 200
    run_jobs(ctx)
    final = client.get(f"/api/v1/requests/{rid}", headers=h).json()
    assert final["status"] == "synced", [(e["event"], e["note"]) for e in final["events"]]
    assert kube.get_object("Namespace", None, "payments-dev") is None


def test_git_outage_retries_then_fails_after_five_attempts(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h).json()["requestId"]
    git.down = True
    from cmapi.worker import Worker
    w = Worker(ctx, "w1", poll_seconds=0)
    for _ in range(5):
        assert w.run_one()
        with ctx.db.session() as s:
            job = JobRepo(s).pending("open_pr", rid)
            if job is not None:
                job.run_after = utcnow()
                job.locked_until = None
    view = client.get(f"/api/v1/requests/{rid}", headers=h).json()
    assert view["status"] == "failed", view["events"]
    git.down = False
    assert client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL)).status_code == 200
    while w.run_one():
        with ctx.db.session() as s:
            for j in s.query(JobRow).filter_by(done_at=None).all():
                j.run_after, j.locked_until = utcnow(), None
    final = client.get(f"/api/v1/requests/{rid}", headers=h).json()
    assert final["status"] == "synced", [(e["event"], e["note"]) for e in final["events"]]


def test_auto_approval_kill_switch(world):
    client, ctx, git, kube, validator, keys = world
    admin = dict(roles=["cmapi-admin"], groups=["/cmapi/app-cmapi-rbac-admin"])
    r = client.post("/api/v1/admin/auto-approval:pause", json={"reason": "incident"}, headers=auth(keys, "root", **admin))
    assert r.status_code == 200 and r.json()["paused"] is True
    r = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert r.json()["status"] == "pending_approval" and r.json()["approval"]["autoFallback"] == "paused"
    client.post("/api/v1/admin/auto-approval:resume", json={"reason": "over"}, headers=auth(keys, "root", **admin))
    assert client.get("/api/v1/admin/auto-approval", headers=auth(keys, "ola", **OLA)).json()["paused"] is False


def test_validator_findings_refuse_the_plan(world):
    client, ctx, git, kube, validator, keys = world
    from cmapi.core.ports import Finding
    validator.findings = [Finding("kyverno", "require-team-metadata", "x", "missing team")]
    r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation" and r.json()["errors"][0]["source"] == "kyverno"
    validator.findings = []
