"""#21 review regressions (reviewer 1, Codex; narrowed by reviewer 2, Opus). Each test before the last three fails on the branch
head before its fix. The last three are the live checks of the review on PostgreSQL, and pass before and after: a placement
and a direct create competing for the last headroom, a create that fails after it claimed its placement, and a claimed
placement's replay and release. The world is the service suite's (test_placement_21.py's docstring has its figures)."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib import import_module
from threading import Barrier
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

from cmapi.capacity import snapshots
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.errors import Problem
from cmapi.core.lifecycle import Event
from cmapi.core.placement import Ask, Candidate, PlacementSettings
from cmapi.plugins.capacity import placement
from test_capacity_302 import load_crc, unsized  # noqa: F401  (unsized is a fixture)
from test_capacity_ledger_302 import node
from test_capacity_reservations_62 import body, committed, holds, who
from test_placement_21 import headers, nodes, place, snapshot


# ---- the capacity check and placement measure one size (D3)

def test_a_direct_create_on_a_node_sized_cluster_counts_a_placement_s_hold(unsized):  # noqa: F811
    """No simulatedCapacity: the size is the counted nodes' 8 cores and 16Gi, a limit of 16 cores and 20Gi in dev. A small
    placement holds 8 cores and 16Gi. A direct create of another small namespace would take memory to 32Gi of 20Gi: it is
    refused, as placement would refuse it. On the branch head the check had no size, answered unknown, and recorded it."""
    client, ctx, git, kube, validator, keys = unsized
    nodes(kube)
    load_crc(ctx, kube, quotas=(), nodes=())
    snapshot(unsized)
    placed = place(unsized)
    assert placed.status_code == 201 and placed.json()["ranked"][0]["basis"] == "allocatable", placed.text
    r = client.post("/api/v1/clusters/CRC/namespaces", json=body("payments-b"), headers=headers(keys))
    assert (r.status_code, r.json()["code"]) == (422, "capacity-exceeded"), r.text
    assert r.json()["capacity"]["source"] == "allocatable"


# ---- zone-failure headroom needs every counted node's zone

def test_zone_failure_headroom_needs_a_zone_for_every_counted_node(world):
    """test_placement_21's nodes (zone a 6 cores, zone b 2) and a third worker with no zone label, which may sit in zone a.
    The branch head left it out, took the limit as 64 × (1 − 6/8) × 2.0 = 32 cores, and placed a small namespace."""
    client, ctx, git, kube, validator, keys = world
    ctx.placement = PlacementSettings({"zoneFailureEnvironments": ["dev"]})
    nodes(kube)
    w3 = node("w3", cpu="6", memory="12Gi")
    w3["metadata"]["labels"]["node-role.kubernetes.io/worker"] = ""
    kube.objects[("Node", "", "w3")] = w3
    snapshot(world)
    r = place(world, dry=True).json()
    assert (r["ranked"], r["excluded"]) == ([], [{"clusterId": "CRC", "reason": "partial-data",
                                                  "detail": "zone-failure headroom needs a zone for every counted node"}]), r


# ---- exact arithmetic: the amount ranked is the amount held

def test_the_ranking_checks_the_amount_the_hold_stores():
    tier = {"requests.cpu": "500.1m", "requests.memory": "1.1Gi"}
    ctx = NS(cfg=NS(tiers=NS(quota_for=lambda *_: tier)))
    ask = placement.ask_of(ctx, {"environment": "dev", "tier": "custom"})
    assert (ask.cpu, ask.memory) == (Decimal("0.501"), Decimal(1181116007))


# ---- a sample that is not a number

def test_an_invalid_sample_marks_the_snapshot_incomplete_never_zero(monkeypatch):
    monkeypatch.setattr(snapshots.PromUsage, "_run", lambda *_: {"cpu.usedAvg": [{"value": [0, "NaN"]}]})
    at = datetime.now(timezone.utc)
    [row] = snapshots.build_rows("CRC", at, 1800, [], snapshots.measure(None, "CRC", 1800, at), None)
    assert not row["complete"] and row["cpu"]["usedAvg"] is None


# ---- the locked re-check decides on the time it holds the lock

def _candidate(at: datetime) -> Candidate:
    size = dict.fromkeys(("cpu", "memory"), Decimal(100))
    zero = dict.fromkeys(size, Decimal(0))
    return Candidate("CRC", None, {}, True, None, True, None, 1, size, "simulated", dict.fromkeys(size, Decimal(1)),
                     zero, None, 0, zero, at, None, {}, None, 0)


@pytest.mark.parametrize("wait", [0, 3601])
def test_the_locked_recheck_reads_freshness_when_it_holds_the_lock(monkeypatch, wait):
    """The snapshot is fresh when ranked. `wait` seconds pass before the cluster's lock is held: past the 3600 s limit, the
    cluster is excluded as stale-data and nothing is held."""
    at = datetime.now(timezone.utc)
    facts = _candidate(at)
    s, repo = MagicMock(), MagicMock()
    repo.active_placements.return_value = 0
    repo.hold.side_effect = lambda row: row
    ctx = NS(db=NS(session=lambda: nullcontext(s)), registry=NS(get=lambda _: None), capacity=NS(stale_after_seconds=3600))
    monkeypatch.setattr(placement, "candidates", lambda *_: [facts])
    monkeypatch.setattr(placement, "ReservationRepo", lambda _: repo)
    monkeypatch.setattr(placement.SnapshotRepo, "latest", lambda *_: {"CRC": None})
    monkeypatch.setattr(placement, "candidate", lambda *_: facts)
    monkeypatch.setattr(placement, "utcnow", lambda: at + timedelta(seconds=wait))
    ask = Ask("dev", "team", Decimal(1), Decimal(1), 1)
    if wait:
        with pytest.raises(Problem) as error:
            placement.place(ctx, ask, PlacementSettings(None), reserve=True)
        assert [x["reason"] for x in error.value.extra["excluded"]] == ["stale-data"]
        repo.hold.assert_not_called()
    else:
        ranked, excluded, held, _ = placement.place(ctx, ask, PlacementSettings(None), reserve=True)
        assert [r.cluster_id for r in ranked] == ["CRC"] and excluded == [] and held.cluster_id == "CRC"


# ---- the snapshot job keeps to the interval's boundaries

def test_the_next_snapshot_is_due_on_the_next_boundary_after_a_slow_collection(monkeypatch):
    """A 15-minute interval, started on its boundary; the collection takes 3 minutes. The next run is due 12 minutes later, on
    the next boundary, not 15."""
    job = import_module("cmapi.jobs.capacity_snapshot")
    at = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
    clock = MagicMock()
    clock.now.side_effect = [at, at + timedelta(minutes=3)]
    monkeypatch.setattr(job, "datetime", clock)
    queue = MagicMock()
    monkeypatch.setattr(job, "JobRepo", lambda _: queue)
    ctx = NS(capacity=NS(snapshot_seconds=900), usage=NS(configured=False), registry=NS(connected=lambda: []))
    job.capacity_snapshot(ctx, MagicMock(), NS(payload={}))
    queue.enqueue.assert_called_once_with("capacity_snapshot", delay=720, payload={"every": 900})


# ---- live checks on PostgreSQL (they pass on the head and after the fixes)

def test_a_placement_and_a_direct_create_compete_for_the_last_headroom(world, monkeypatch):
    """104 of 128 cores committed: room for one medium namespace (16). A direct create's plan and a placement's first ranking
    both see that room; then both take #725's per-cluster lock. One wins, the other is refused, and one hold of 16 remains."""
    _, ctx, _, kube, *_ = world
    nodes(kube)
    snapshot(world)
    committed(ctx, 104)
    plan = ctx.pipeline.plan_namespace(who(), "CRC", body("payments-a", "medium"), action="create")
    ask = placement.ask_of(ctx, {"environment": "dev", "tier": "medium", "team": "payments"})
    both_ranked = Barrier(2)
    rank_first = placement.candidates

    def ranked_then_wait(*args):
        found = rank_first(*args)
        both_ranked.wait(10)
        return found

    monkeypatch.setattr(placement, "candidates", ranked_then_wait)

    def submit() -> str:
        both_ranked.wait(10)
        try:
            with ctx.db.session() as s:
                ctx.pipeline.submit(who(), plan, RequestRepo(s), JobRepo(s), idempotency_key=None, body_fingerprint="test",
                                    justification=None)
            return "created"
        except Problem as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(submit)
        try:
            placement.place(ctx, ask, ctx.placement, reserve=True, placed_by="ola")
            outcome = "placed"
        except Problem as exc:
            outcome = exc.code
        assert (outcome, pending.result(timeout=15)) in {("placed", "capacity-exceeded"), ("no-placement", "created")}
    assert [h.cpu for h in holds(ctx)] == [16]


def test_a_create_that_fails_after_claiming_its_placement_leaves_the_placement_as_it_was(world, monkeypatch):
    """The create's transaction claims the placement, then its job cannot be queued: the transaction is undone, and the
    placement is unclaimed again, with its own 15 minutes, for the create to be sent again."""
    _, ctx, _, kube, *_ = world
    nodes(kube)
    snapshot(world)
    pid = place(world).json()["placementId"]
    plan = ctx.pipeline.plan_namespace(who(), "CRC", {**body("payments-a"), "placementId": pid}, action="create")

    def unavailable(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    with pytest.raises(RuntimeError, match="queue unavailable"):
        with ctx.db.session() as s:
            jobs = JobRepo(s)
            monkeypatch.setattr(jobs, "enqueue", unavailable)
            ctx.pipeline.submit(who(), plan, RequestRepo(s), jobs, idempotency_key=None, body_fingerprint="test",
                                justification=None)
    [row] = holds(ctx)
    assert (row.request_id, row.placement_id, row.expires_at - row.created_at) == (None, pid, timedelta(minutes=15))


def test_a_claimed_placement_replays_with_its_key_and_ends_with_its_request(world):
    """The create with its placementId and an Idempotency-Key, sent again, answers the same request; with a changed body, 409
    idempotency-replay. When the request fails, the hold it took from the placement is released as failed."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    committed(ctx, 96)
    pid = place(world).json()["placementId"]
    path, payload, hdr = "/api/v1/clusters/CRC/namespaces", {**body("payments-a"), "placementId": pid}, headers(keys)
    first = client.post(path, json=payload, headers=hdr)
    assert first.status_code == 202, first.text
    rid = first.json()["requestId"]
    assert client.post(path, json=payload, headers=hdr).json()["requestId"] == rid
    changed = client.post(path, json={**payload, "placementId": "pl-changed"}, headers=hdr)
    assert (changed.status_code, changed.json()["code"]) == (409, "idempotency-replay")
    with ctx.db.session() as s:
        repo = RequestRepo(s)
        repo.move(repo.get(rid), Event.PR_FAILED, "worker", "test")
    assert not holds(ctx)
    [row] = holds(ctx, active=False)
    assert (row.placement_id, row.released_why) == (pid, "failed")
