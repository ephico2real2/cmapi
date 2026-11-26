"""#62: the capacity guard of auto-approval against the cluster's real commitment and the capacity that open requests hold.

What must hold (the issue): the capacity answer comes from measured data, never only from clusters.yaml; `reserve` and
`release` change the reservations, so a request that does not fit is refused, or routed to approval, by the guard; and the
facts `requestToPeakRatio` and `openRequestOnNamespace` are set from measured data.

The design: docs/01, "Quota headroom = allocatable × overcommit − committed − reserved"; docs/02, Placement, "Reservations":
"Placement takes a reservation inside the same transaction as the capacity check, under a per-cluster advisory lock, so
concurrent requests see each other. The reservation ends when the namespace's ResourceQuota appears in cmapi's watch cache of
that cluster. Committed quota counts it from then on, so it is never counted twice. It also ends when the request is rejected,
cancelled or times out." The lifecycle's Reservation column (docs/01) says which states hold it.

The cluster of `world`: simulatedCapacity 64 cores and 256Gi, dev overcommit 2.0 and 1.25, so 128 cores and 320Gi; warn at
0.85. The owner kept simulatedCapacity as the size until cmapi-capacity's snapshots (#21; 2026-11-18). What is committed is
measured: the cluster's quota ledger, fed by the watch of its ResourceQuotas (#302). A small namespace is 8 cores and 16Gi.
"""
from __future__ import annotations

import threading
import uuid
from datetime import date, timedelta

import pytest
import yaml
from types import SimpleNamespace

from sqlalchemy import select, text

from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.lifecycle import Event as E
from test_flow import AMY, OLA, auth, run_jobs

GiB = 2**30
SMALL = {"tier": "small", "labels": {"cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410"},
         "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, "justification": "Payments service namespace"}


def body(name: str, tier: str = "small") -> dict:
    return {**SMALL, "namespace": name, "tier": tier}


def committed(ctx, cpu: int, memory: str = "1Gi", name: str = "busy") -> None:
    """Another namespace's managed quota, through the watch's own ADDED path: what the cluster's ledger counts as committed."""
    ctx.registry.cache("CRC")._event("ResourceQuota", {"type": "ADDED", "object": {
        "kind": "ResourceQuota", "metadata": {"name": f"{name}-quota", "namespace": name, "labels": {"cmapi.net/managed": "true"}},
        "spec": {"hard": {"requests.cpu": str(cpu), "requests.memory": memory}}}})


def create(world, name: str, tier: str = "small"):
    client, ctx, git, kube, validator, keys = world
    return client.post("/api/v1/clusters/CRC/namespaces", json=body(name, tier), headers=auth(keys, "ola", **OLA))


def holds(ctx, *, active: bool = True) -> list[SimpleNamespace]:
    """The rows of capacity_reservations (migration 0011), read in SQL so that this file also runs on a tree without the table:
    there, each test that reads a hold fails on the missing table, as it should."""
    with ctx.db.session() as s:
        rows = s.execute(text("SELECT * FROM capacity_reservations" + (" WHERE released_at IS NULL" if active else "")
                              + " ORDER BY created_at")).mappings().all()
        return [SimpleNamespace(**r) for r in rows]


def who() -> Identity:
    return Identity("sub-ola", "ola", "user", "cmapi-portal", "ola@example.test", employee_id="E1",
                    roles=frozenset(OLA["roles"]), groups=frozenset(OLA["groups"]))


# ---- criterion 1: the answer is the cluster's measured commitment, and more than is free is refused

def test_a_request_for_more_than_the_cluster_has_free_is_refused(world):
    """Guard, true before and after #62: the committed quota is the ledger's (measured from the watch), not a static size. With
    120 of 128 cores committed, a medium namespace (16) does not fit: 422 capacity-exceeded, nothing recorded. With nothing
    committed the same request is planned."""
    client, ctx, git, kube, validator, keys = world
    dry = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=body("payments-big", "medium"),
                      headers=auth(keys, "ola", **OLA))
    assert dry.status_code == 200 and dry.json()["capacity"]["status"] == "fits", dry.text
    committed(ctx, 120)
    r = create(world, "payments-big", "medium")
    assert r.status_code == 422 and r.json()["code"] == "capacity-exceeded", r.text
    assert r.json()["capacity"]["cpu"] == 1.062, r.json()["capacity"]                     # (120 + 16) / 128
    with ctx.db.session() as s:
        assert s.scalars(select(ChangeRequestRow)).all() == []


# ---- criterion 2: reserve and release change the reservations, and the guard counts them

def test_a_request_holds_its_increase_and_a_second_that_fits_alone_is_refused(world):
    """116 of 128 cores committed. One small namespace fits (124, warn: routed to approval). A second fits alone, but not with
    the first one's hold (132): refused. Before #62 the hold was a no-op and both were recorded, 136 cores on a 128 one."""
    client, ctx, git, kube, validator, keys = world
    committed(ctx, 116)
    a = create(world, "payments-a")
    assert a.status_code == 202 and a.json()["status"] == "pending_approval", a.text
    assert a.json()["approval"]["auto"] is None, "warn: the guard routes it to a person"
    [h] = holds(ctx)
    assert (h.request_id, h.namespace, float(h.cpu), h.memory, h.pods) == (a.json()["requestId"], "payments-a", 8.0, 16 * GiB, 50)
    assert (float(h.target_cpu), h.target_memory) == (8.0, 16 * GiB)
    b = create(world, "payments-b")
    assert b.status_code == 422 and b.json()["code"] == "capacity-exceeded", b.text
    assert b.json()["capacity"]["reserved"] == {"cpu": 8.0, "memory": 16 * GiB}, b.json()["capacity"]


def test_the_auto_approval_guard_counts_the_holds_of_open_requests(world):
    """96 of 128 cores committed. The first small namespace fits (104, 0.81) and the policy approves it. The second fits alone
    (0.81 again) but not beside the first one's hold (112, 0.875, warn): the guard stops auto-approval and a person decides.
    Before #62 both were auto-approved."""
    client, ctx, git, kube, validator, keys = world
    committed(ctx, 96)
    a = create(world, "payments-a")
    assert a.status_code == 202 and a.json()["status"] == "approved", a.text
    assert a.json()["approval"]["auto"] == "auto:baseline-rnd-namespace"
    b = create(world, "payments-b")
    assert b.status_code == 202, b.text
    assert b.json()["status"] == "pending_approval" and b.json()["approval"]["auto"] is None, b.json()["approval"]
    dry = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=body("payments-c"), headers=auth(keys, "ola", **OLA))
    assert dry.json()["capacity"]["reserved"] == {"cpu": 16.0, "memory": 32 * GiB}, "a dry run counts the holds, and takes none"
    assert len(holds(ctx)) == 2


def test_two_plans_made_before_either_submits_are_checked_again_under_the_lock(world):
    """Both plans read the cluster before either hold exists, and each fits alone. Submit checks again under the cluster's lock,
    with every hold taken since the plan: the second is refused and nothing of it is recorded."""
    client, ctx, git, kube, validator, keys = world
    committed(ctx, 116)
    first = ctx.pipeline.plan_namespace(who(), "CRC", body("payments-a"), action="create")
    second = ctx.pipeline.plan_namespace(who(), "CRC", body("payments-b"), action="create")
    assert (first.capacity.status, second.capacity.status) == ("warn", "warn")
    with ctx.db.session() as s:
        ctx.pipeline.submit(who(), first, RequestRepo(s), JobRepo(s), idempotency_key=None, body_fingerprint="a",
                            justification=None)
    with pytest.raises(Problem) as exc, ctx.db.session() as s:
        ctx.pipeline.submit(who(), second, RequestRepo(s), JobRepo(s), idempotency_key=None, body_fingerprint="b",
                            justification=None)
    assert exc.value.code == "capacity-exceeded"
    with ctx.db.session() as s:
        assert [r.namespace for r in s.scalars(select(ChangeRequestRow))] == ["payments-a"]


def test_concurrent_submits_cannot_overbook(world):
    """Eight small namespaces planned at once on a cluster with room for three (104 of 128 cores committed: 104 + 3 × 8 =
    128, and a ratio of exactly 1 is not over). Each plan alone answers warn (112 of 128). Submitted from eight threads together,
    each in its own transaction: the cluster's lock lets exactly three hold."""
    client, ctx, git, kube, validator, keys = world
    committed(ctx, 104)
    plans = [ctx.pipeline.plan_namespace(who(), "CRC", body(f"payments-{i}"), action="create") for i in range(8)]
    assert {p.capacity.status for p in plans} == {"warn"}
    start, outcomes = threading.Barrier(len(plans)), []

    def submit(i, plan):
        start.wait()
        try:
            with ctx.db.session() as s:
                ctx.pipeline.submit(who(), plan, RequestRepo(s), JobRepo(s), idempotency_key=None, body_fingerprint=str(i),
                                    justification=None)
            outcomes.append("held")
        except Problem as exc:
            outcomes.append(exc.code)
    threads = [threading.Thread(target=submit, args=(i, p)) for i, p in enumerate(plans)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(outcomes) == ["capacity-exceeded"] * 5 + ["held"] * 3, outcomes
    assert sum(float(h.cpu) for h in holds(ctx)) == 24.0


@pytest.mark.parametrize("end", ["reject", "cancel", "timeout"])
def test_a_request_that_ends_releases_its_hold(world, end):
    """docs/02: "It also ends when the request is rejected, cancelled or times out." Then the next request fits again."""
    client, ctx, git, kube, validator, keys = world
    committed(ctx, 116)
    rid = create(world, "payments-a").json()["requestId"]
    assert create(world, "payments-b").json()["code"] == "capacity-exceeded"
    if end == "reject":
        r = client.post(f"/api/v1/requests/{rid}:reject", json={"comment": "no room"}, headers=auth(keys, "amy", **AMY))
    elif end == "cancel":
        r = client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "ola", **OLA))
    else:
        with ctx.db.session() as s:
            repo = RequestRepo(s)
            repo.move(repo.get(rid), E.APPROVAL_TIMEOUT, "worker", "test")
        r = None
    assert r is None or r.status_code == 200, r.text
    [h] = holds(ctx, active=False)
    assert h.released_why == {"reject": "rejected", "cancel": "cancelled", "timeout": "timeout"}[end]
    assert holds(ctx) == []
    assert create(world, "payments-b").status_code == 202


def test_a_synced_request_releases_its_hold_and_its_quota_is_counted_once(world):
    """The whole lifecycle: the hold is taken at submit, kept through the PR and the apply, and ends at synced. While the
    ledger already shows the namespace's quota (applied, before synced), the hold no longer counts: never twice."""
    client, ctx, git, kube, validator, keys = world
    committed(ctx, 96)
    rid = create(world, "payments-a").json()["requestId"]
    assert ctx.pipeline.capacity.check("CRC", "dev", 0, 0).detail["cpu"] == 0.812            # (96 + 8 held) / 128
    with ctx.db.session() as s:                         # the request's own quota reaches the watch, as after the apply
        files = s.get(ChangeRequestRow, rid).plan["files"]
    quota = yaml.safe_load(next(t for p, t in files.items() if "/resourcequota-" in p))
    ctx.registry.cache("CRC")._event("ResourceQuota", {"type": "ADDED", "object": quota})
    cap = ctx.pipeline.capacity.check("CRC", "dev", 0, 0)
    assert (cap.detail["cpu"], cap.detail["reserved"]) == (0.812, {"cpu": 0.0, "memory": 0}), "observed: counted once"
    ran = run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "synced", (ran, [(e["event"], e["note"]) for e in view["events"]])
    [h] = holds(ctx, active=False)
    assert h.released_why in ("synced", "observed"), h.released_why


def test_an_expired_hold_is_reclaimed(world):
    """A hold whose term has passed (a request that stopped moving: a lost worker) no longer counts, and the next hold taken
    on the cluster marks it released as expired."""
    client, ctx, git, kube, validator, keys = world
    committed(ctx, 116)
    first = create(world, "payments-a").json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("UPDATE capacity_reservations SET expires_at = now() - interval '1 minute'"))
    second = create(world, "payments-b")
    assert second.status_code == 202, second.text
    rows = {h.request_id: h for h in holds(ctx, active=False)}
    assert rows[first].released_why == "expired" and rows[second.json()["requestId"]].released_at is None


def test_the_last_approval_checks_the_hold_again(world):
    """docs/01: "approved: The count is met (auto or :approve) and capacity still fits". 116 of 128 cores committed and one
    small namespace pending (124, warn: two approvers of approver-platform). The first approval is recorded. Then another
    quota lands on the cluster outside cmapi (6 cores: 130 with the hold). The last approval is refused with 422
    capacity-exceeded, and neither it nor the state change is recorded; once the room is back it approves."""
    client, ctx, git, kube, validator, keys = world
    ben = dict(AMY)
    committed(ctx, 116)
    rid = create(world, "payments-a").json()["requestId"]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    assert r.status_code == 200 and r.json()["status"] == "pending_approval", r.text
    committed(ctx, 6, name="outside")
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "ben", **ben))
    assert r.status_code == 422 and r.json()["code"] == "capacity-exceeded", r.text
    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "pending_approval", view["status"]
    assert [a["username"] for a in view["approval"]["approvals"]] == ["amy"], view["approval"]
    ctx.registry.cache("CRC")._event("ResourceQuota", {"type": "DELETED", "object": {
        "kind": "ResourceQuota", "metadata": {"name": "outside-quota", "namespace": "outside"}}})
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "ben", **ben))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text


def test_a_retry_from_failed_holds_again_only_when_it_still_fits(world):
    """failed releases the hold; :retry re-enters approved, which holds it (docs/01, the failed row: "re-acquires lock and
    reservation"). When the cluster filled meanwhile the retry is refused and the request stays failed."""
    client, ctx, git, kube, validator, keys = world
    committed(ctx, 96)
    rid = create(world, "payments-a").json()["requestId"]
    with ctx.db.session() as s:
        repo = RequestRepo(s)
        repo.move(repo.get(rid), E.PR_FAILED, "worker", "test")
    assert holds(ctx) == [] and holds(ctx, active=False)[0].released_why == "failed"
    committed(ctx, 30, name="outside")                                                        # 126 + 8 > 128
    opal = dict(roles=["cmapi-operator", "cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-operator"])
    r = client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **opal))
    assert r.status_code == 422 and r.json()["code"] == "capacity-exceeded", r.text
    assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] == "failed"
    assert holds(ctx) == []
    committed(ctx, 10, name="outside")                                                        # 106 + 8 fits
    r = client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **opal))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    [h] = holds(ctx)
    assert (h.request_id, float(h.cpu)) == (rid, 8.0)


# ---- criterion 3: the two facts come from measured data

def test_open_request_on_namespace_is_read_from_the_open_requests(world, monkeypatch):
    """Guard, true before and after #62: expire_check sets `openRequestOnNamespace` from the requests that hold the namespace
    (RequestRepo.open_namespaces, the database), so the expiry delete is held by the guard noOpenRequest and not opened."""
    import importlib

    from test_expirations import created_namespace

    client, ctx, git, kube, validator, keys = world
    day = date.today() + timedelta(days=20)
    created_namespace(client, ctx, keys, expiresAt=day.isoformat())
    seen = []
    real = ctx.cfg.expiration.expire_check

    def spy(infos, today):
        out = real(infos, today)
        seen.append(([(i.namespace, i.open_request) for i in infos], list(out.held)))
        return out
    monkeypatch.setattr(ctx.cfg.expiration, "expire_check", spy)
    expire_check = importlib.import_module("cmapi.jobs.expire_check")
    expire_check.check(ctx, day - timedelta(days=1))                   # a notice day: nothing holds the namespace
    assert seen == [([("payments-dev", False)], [])]
    with ctx.db.session() as s:                                        # an open change of the namespace, as the lock sees it
        s.add(ChangeRequestRow(request_id="req-20990101-0001", instance=ctx.cfg.name, cluster_id="CRC", namespace="payments-dev",
                               env="dev", plugin="namespaces", action="update", status="pending_approval", plan={},
                               plan_hash="x", base_sha="x", requester={}, requester_sub="sub-ola", requester_kind="user",
                               requester_client="cmapi-portal", requester_username="ola"))
    seen.clear()
    expire_check.check(ctx, day + timedelta(days=30))                  # past grace: the delete is due, and held
    assert seen == [([("payments-dev", True)], [("payments-dev", "noOpenRequest")])]
    with ctx.db.session() as s:
        assert s.scalars(select(ChangeRequestRow).where(ChangeRequestRow.reason == "expired")).all() == []


def test_request_to_peak_ratio_is_the_planned_quota_over_the_measured_peak(world):
    """Guard, true before and after #62 (#310, #707): `requestToPeakRatio` is the planned quota over the namespace's measured
    14-day peak, from the usage source, and `requestToPeakRatio > 3` adds an approver. Without a measured peak it is absent."""
    from test_usage_verdicts_310 import Fake, FakeMetrics, ONE, PromUsage, synced_namespace

    client, ctx, git, kube, validator, keys = world
    etag = synced_namespace(world)
    ctx.pipeline.usage = PromUsage(FakeMetrics({"payments-dev": Fake(cpu=(1.0, 1.0, 1.5, 2.0, None),
                                                                     memory=(3 * GiB, 3 * GiB, 4 * GiB, 5 * GiB, None))}))
    r = client.patch(ONE + "?dryRun=true", json={"tier": "medium"}, headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 200, r.text
    assert r.json()["usage"]["cpu"]["newOverPeak"] == 8.0, "16 planned cores over a measured peak of 2"
    assert {"group": "approver-platform", "count": 1, "reason": "Possible over-provisioning"} in r.json()["approval"]["slots"]
