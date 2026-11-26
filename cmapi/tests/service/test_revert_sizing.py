"""A revert is sized and reviewed as a quota change (separate issue, found reviewing PR #714).

docs/01, the state reverted: ":revert on a sync_failed request; the revert is a new request through the same approval rules",
and the request's capacity is "Released, so the revert request can take it". Before the fix the revert job set capacity
"fits" without a check and gave the approval rules no quota facts: the revert of a move from large to small wrote large back,
24 CPUs more, auto-approved, where the same raise asked by a person needs approver-platform (quotaIncreasePct > 100).
"""
from __future__ import annotations

from sqlalchemy import text

from cmapi.core.ports import CapacityResult
from cmapi.worker import Worker
from test_catalog_drift_710 import capacity_deltas, created, patch, stored_facts
from test_flow import AMY, OPAL, auth, run_jobs

GI = float(2**30)


def view(world, rid):
    client, ctx, git, kube, validator, keys = world
    return client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "opal", **OPAL)).json()


def lowered_then_sync_failed(world) -> str:
    """payments-dev moved small -> large (approved), then large -> small; the second request ends sync_failed."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    up = patch(world, {"tier": "large"}, dry_run=False)
    assert up.json()["status"] == "pending_approval", up.json()
    assert client.post(f"/api/v1/requests/{up.json()['requestId']}:approve", json={},
                       headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx)
    assert view(world, up.json()["requestId"])["status"] == "synced"
    low = patch(world, {"tier": "small"}, dry_run=False).json()["requestId"]
    run_jobs(ctx)
    assert view(world, low)["status"] == "synced"
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": low})
    return low


def test_the_revert_of_a_lowering_is_sized_and_approved_as_a_raise(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    low = lowered_then_sync_failed(world)
    asked = capacity_deltas(world, monkeypatch)
    assert client.post(f"/api/v1/requests/{low}:revert", headers=auth(keys, "opal", **OPAL)).status_code == 200
    run_jobs(ctx, limit=1)
    opened = [e["note"] for e in view(world, low)["events"] if e["event"] == "revert_opened"]
    assert len(opened) == 1, view(world, low)["events"]
    assert asked == [(24.0, 48 * GI)], "restoring large takes back 24 CPUs and 48Gi"
    facts = stored_facts(world, opened[0])
    assert facts["quotaIncreasePct"] == 300.0 and facts["tierChange"] == "up", facts
    assert facts["capacity"] == "fits" and not facts["networkExposure"], facts
    revert = view(world, opened[0])
    assert revert["status"] == "pending_approval", revert


def test_a_revert_that_the_cluster_has_no_room_for_is_not_opened(world, monkeypatch):
    """capacity-exceeded, as a plan answers it: the job fails and is retried, and the request stays sync_failed."""
    client, ctx, git, kube, validator, keys = world
    low = lowered_then_sync_failed(world)
    monkeypatch.setattr(ctx.pipeline.capacity, "check",
                        lambda *a: CapacityResult("exceeded", True, "cpu", {"cpu": {"requested": 24}}))
    assert client.post(f"/api/v1/requests/{low}:revert", headers=auth(keys, "opal", **OPAL)).status_code == 200
    assert Worker(ctx, "w").run_one()          # the worker, which records a job's failure and retries it later
    after = view(world, low)
    assert after["status"] == "sync_failed", after["status"]
    assert not [e for e in after["events"] if e["event"] == "revert_opened"], after["events"]
    assert any(e["event"] == "error" and "open_revert" in e["note"] and "would exceed the cluster" in e["note"]
               for e in after["events"]), after["events"]


def test_the_revert_of_a_sensitive_label_change_needs_its_approval(world):
    """The same rules for the metadata it writes back: cmapi.net/team is a sensitive key (metadata-keys.yaml sensitiveKeys),
    so the revert that changes it back needs the approval that any change of it needs."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    moved = patch(world, {"labels": {"cmapi.net/team": "billing"}}, dry_run=False)
    assert moved.json()["status"] == "pending_approval", moved.json()
    rid = moved.json()["requestId"]
    assert client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx)
    assert view(world, rid)["status"] == "synced"
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": rid})
    assert client.post(f"/api/v1/requests/{rid}:revert", headers=auth(keys, "opal", **OPAL)).status_code == 200
    run_jobs(ctx, limit=1)
    opened = [e["note"] for e in view(world, rid)["events"] if e["event"] == "revert_opened"]
    assert len(opened) == 1, view(world, rid)["events"]
    facts = stored_facts(world, opened[0])
    assert facts["sensitiveKeyChanged"] is True, facts
    assert view(world, opened[0])["status"] == "pending_approval"
