"""A revert is sized and reviewed as a quota change (separate issue, found reviewing PR #714).

docs/01, the state reverted: ":revert on a sync_failed request; the revert is a new request through the same approval rules",
and the request's capacity is "Released, so the revert request can take it". Before the fix the revert job set capacity
"fits" without a check and gave the approval rules no quota facts: the revert of a move from large to small wrote large back,
24 CPUs more, auto-approved, where the same raise asked by a person needs approver-platform (quotaIncreasePct > 100).
"""
from __future__ import annotations

import shutil

import pytest
import yaml
from sqlalchemy import text

from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.ports import CapacityResult
from cmapi.worker import Worker
from conftest import build_world
from test_catalog_drift_710 import ONE, QUOTA_FILE, capacity_deltas, created, patch, stored_facts
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs

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
    relist_quotas(world)                       # the ledger holds what the cluster commits: small's 8 CPUs
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": low})
    return low


def relist_quotas(world) -> None:
    """The fake cluster sends no watch events: the ledger reads what the cluster holds now, as the watch keeps it."""
    client, ctx, git, kube, validator, keys = world
    ctx.registry.cache("CRC")._list("ResourceQuota")


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
                        lambda *a, **kw: CapacityResult("exceeded", True, "cpu", {"cpu": {"requested": 24}}))
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


# ---- reviewer 2 of #718: what the review of this PR found in restore_facts


def stored_plan(world, request_id: str) -> dict:
    client, ctx, git, kube, validator, keys = world
    with ctx.db.session() as s:
        return dict(s.get(ChangeRequestRow, request_id).plan)


def revert_once(world, rid: str) -> str | None:
    """The request ends sync_failed and is reverted; the worker runs the job once. The new request's id, or None."""
    client, ctx, git, kube, validator, keys = world
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": rid})
    assert client.post(f"/api/v1/requests/{rid}:revert", headers=auth(keys, "opal", **OPAL)).status_code == 200
    assert Worker(ctx, "w").run_one()
    opened = [e["note"] for e in view(world, rid)["events"] if e["event"] == "revert_opened"]
    return opened[0] if opened else None


def approve_all(world, rid: str) -> None:
    client, ctx, git, kube, validator, keys = world
    for who in ("amy", "pat", "pia"):
        if view(world, rid)["status"] != "pending_approval":
            return
        assert client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, who, **AMY)).status_code == 200


@pytest.fixture
def cluster_of_40(test_config, tmp_path, fresh_db, keys, monkeypatch):
    """CRC with 20 CPUs: at the suite's overcommit of 2.0 it commits at most 40."""
    config = tmp_path / "config"
    shutil.copytree(test_config, config)
    clusters = config / "clusters.yaml"
    clusters.write_text(clusters.read_text().replace("simulatedCapacity: {cpu: 64", "simulatedCapacity: {cpu: 20"))
    with build_world(config, keys, monkeypatch) as world:
        yield world


def small_large_small(world) -> str:
    """payments-dev small -> large (approved, synced), then large -> small merged. The second request's id."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    up = patch(world, {"tier": "large"}, dry_run=False).json()["requestId"]
    approve_all(world, up)
    run_jobs(ctx)
    low = patch(world, {"tier": "small"}, dry_run=False).json()["requestId"]
    run_jobs(ctx)
    return low


def test_a_failed_lowering_is_restored_over_the_quota_that_is_still_live(cluster_of_40):
    """Codex's H1. The lowering large -> small merged and its sync did not finish: the cluster still enforces large's 32 CPUs,
    and Git holds small's 8. Restoring 32 commits nothing more, 32 of 40 (0.8). Before the fix the Git delta of 24 was added to
    the live 32, 56 of 40, and the revert was refused capacity-exceeded. The approval still compares with Git (#710)."""
    world = cluster_of_40
    client, ctx, git, kube, validator, keys = world
    low = small_large_small(world)
    rq = yaml.safe_load(git.branches["main"][QUOTA_FILE])
    rq["spec"]["hard"].update({"requests.cpu": "32", "requests.memory": "64Gi", "pods": "200"})
    kube.apply(rq)
    relist_quotas(world)
    child = revert_once(world, low)
    assert child, view(world, low)["events"]
    plan = stored_plan(world, child)
    assert plan["capacity"]["status"] == "fits" and plan["capacity"]["cpu"] == 0.8, plan["capacity"]
    assert plan["facts"]["quotaIncreasePct"] == 300.0, plan["facts"]


def test_a_restored_raise_over_a_live_lower_quota_is_counted(cluster_of_40):
    """The guard of the other side: the cluster and Git hold 8, the restore asks 32, so the cluster commits 32 of 40."""
    world = cluster_of_40
    low = small_large_small(world)
    relist_quotas(world)
    child = revert_once(world, low)
    assert stored_plan(world, child)["capacity"]["cpu"] == 0.8


def test_the_revert_of_a_delete_that_was_not_pruned_counts_the_live_quota_once(world):
    """The same count for a delete: merged, it waits for the prune (awaiting_prune) and the cluster still enforces its 8 CPUs.
    Restoring the folder commits nothing more, 8 of the 128 that CRC commits (64 CPUs at 2.0), 0.0625 (the check rounds to
    0.062); over Git's empty folder it was 16, 0.125."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    tag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    gone = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": tag})
    assert gone.status_code == 202, gone.text
    approve_all(world, gone.json()["requestId"])
    run_jobs(ctx)
    assert view(world, gone.json()["requestId"])["status"] == "awaiting_prune"
    relist_quotas(world)
    assert ctx.registry.quota_watch("CRC")[1].totals().committed["cpu"] == 8
    child = revert_once(world, gone.json()["requestId"])
    assert stored_plan(world, child)["capacity"]["cpu"] == 0.062, stored_plan(world, child)["capacity"]


def custom_on(world, quota: dict[str, str]) -> None:
    """payments-dev created on the custom tier with these values, approved and synced."""
    client, ctx, git, kube, validator, keys = world
    body = {**NS, "tier": "custom", "quota": {"requests.cpu": "4", "requests.memory": "8Gi", "pods": "20", **quota}}
    r = client.post("/api/v1/clusters/CRC/namespaces", json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    approve_all(world, r.json()["requestId"])
    run_jobs(ctx)
    assert view(world, r.json()["requestId"])["status"] == "synced"


def patched(world, body: dict) -> str:
    client, ctx, git, kube, validator, keys = world
    tag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    r = client.patch(ONE, json=body, headers={**auth(keys, "ola", **OLA), "If-Match": tag})
    assert r.status_code == 202, r.text
    approve_all(world, r.json()["requestId"])
    run_jobs(ctx)
    return r.json()["requestId"]


def test_a_restored_value_beyond_todays_tier_needs_its_approval_without_an_annotation(world):
    """Codex's H3. The folder holds requests.storage 400Gi, rendered while 400Gi was the custom tier's default, so no
    cmapi.net/beyond-tier names it. The catalog's default is now 200Gi: a label change renders 200Gi, and its revert writes
    400Gi back. A PATCH asking 400Gi is beyond the tier (TierCatalog.beyond); before the fix the revert read only the
    annotation, and asked for no approval."""
    client, ctx, git, kube, validator, keys = world
    custom_on(world, {})
    rq = yaml.safe_load(git.branches["main"][QUOTA_FILE])
    assert "cmapi.net/beyond-tier" not in (rq["metadata"].get("annotations") or {})
    rq["spec"]["hard"]["requests.storage"] = "400Gi"
    git.branches["main"][QUOTA_FILE] = yaml.safe_dump(rq, sort_keys=False)
    git._sha("main")
    low = patched(world, {"labels": {"cmapi.net/cost-center": "cc-9000"}})
    assert yaml.safe_load(git.branches["main"][QUOTA_FILE])["spec"]["hard"]["requests.storage"] == "200Gi"
    child = revert_once(world, low)
    plan = stored_plan(world, child)
    assert plan["facts"]["beyondTierKeys"] == ["requests.storage"], plan["facts"]
    assert plan["beyondTier"]["keys"] == [{"key": "requests.storage", "tier": "200Gi", "requested": "400Gi"}], plan["beyondTier"]
    assert view(world, child)["status"] == "pending_approval"


def test_a_value_that_git_holds_and_the_revert_keeps_is_not_beyond_the_tier_again(world):
    """The guard: services.nodeports 2 was approved beyond the tier, and a label change keeps it. The revert writes the label
    back and the same 2: no beyond-tier approval, before and after the fix."""
    client, ctx, git, kube, validator, keys = world
    custom_on(world, {"services.nodeports": "2"})
    low = patched(world, {"labels": {"cmapi.net/cost-center": "cc-9000"}})
    child = revert_once(world, low)
    plan = stored_plan(world, child)
    assert plan["facts"]["beyondTier"] is False and plan["beyondTier"] is None, plan["facts"]


def test_the_approver_sees_the_value_beyond_the_tier_that_a_revert_restores(world):
    """Codex's L2. The revert of services.nodeports 2 -> 0 writes 2 back: its facts said beyondTier, and the request an
    approver reads held beyondTier null ("null when the request has none"). It now holds the key, the tier's value, the
    requested value and the approvals the rules add for it, as a plan's does."""
    client, ctx, git, kube, validator, keys = world
    custom_on(world, {"services.nodeports": "2"})
    low = patched(world, {"quota": {"services.nodeports": "0"}})
    child = revert_once(world, low)
    plan = stored_plan(world, child)
    assert plan["facts"]["beyondTierKeys"] == ["services.nodeports"], plan["facts"]
    assert plan["beyondTier"] == {"keys": [{"key": "services.nodeports", "tier": "0", "requested": "2"}],
                                  "approvals": [{"group": "approver-platform", "count": 1, "reason": "Value beyond the tier"},
                                                {"group": "approver-platform", "count": 1, "reason": "Network exposure"}]}
    assert view(world, child)["beyondTier"] == plan["beyondTier"]
