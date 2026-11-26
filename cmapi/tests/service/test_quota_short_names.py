"""A quota in Git that bounds CPU and memory by the short names `cpu` and `memory` (separate issue, found reviewing PR #714).

Kubernetes, "Resource Quotas": `cpu` is the same resource as `requests.cpu`, and `memory` as `requests.memory`; a quota that
sets both is enforced at the smaller (capacity_ledger.REQUEST_KEYS, #393). The planner sizes a change from what Git holds
(#710), so it must read the short names too. Before the fix it read `requests.cpu` alone: a quota of `cpu: 1` counted as no
bound, so a move to 16 CPUs was 100% and auto-approved, and a `cpu: 1` beside `requests.cpu: 8` was a raise of nothing.
"""
from __future__ import annotations

import yaml

from test_catalog_drift_710 import LABEL, QUOTA_FILE, capacity_deltas, created, patch, stored_facts
from test_multidoc_quota_250 import one_file, quota

GI = float(2**30)


def test_a_lone_quota_in_the_short_names_is_the_baseline_of_a_tier_move(world, monkeypatch):
    """A hand-written folder: one ResourceQuota, `cpu: 1` and `memory: 2Gi`. The move to medium (16 CPUs, 32Gi) is a raise
    of 15 CPUs and 30Gi, 1500%, which approval-rules.yaml sends to approver-platform."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    one_file(world, [quota("compute", {"cpu": "1", "memory": "2Gi"})], keep_own=False)
    asked = capacity_deltas(world, monkeypatch)
    r = patch(world, {"tier": "medium"}, dry_run=False)
    assert r.status_code == 202, r.text
    assert asked == [(15.0, 30 * GI)], asked
    facts = stored_facts(world, r.json()["requestId"])
    assert facts["quotaIncreasePct"] == 1500.0, facts
    assert r.json()["status"] == "pending_approval", r.json()


def test_a_short_name_tighter_than_the_long_one_binds(world, monkeypatch):
    """cmapi's own quota with `cpu: 1` added beside `requests.cpu: 8`: the namespace is held to 1 CPU. A label change renders
    the tier without `cpu`, which lifts it to 8: a raise of 7 CPUs, 700%."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    main = git.branches["main"]
    rq = yaml.safe_load(main[QUOTA_FILE])
    rq["spec"]["hard"]["cpu"] = "1"
    main[QUOTA_FILE] = yaml.safe_dump(rq, sort_keys=False)
    git._sha("main")
    asked = capacity_deltas(world, monkeypatch)
    plan = patch(world, LABEL, dry_run=True)
    assert plan.status_code == 200, plan.text
    assert "cpu" not in yaml.safe_load(plan.json()["files"][QUOTA_FILE])["spec"]["hard"], "the tier renders no short name"
    r = patch(world, LABEL, dry_run=False)
    assert r.status_code == 202, r.text
    assert asked == [(7.0, 0.0), (7.0, 0.0)], asked
    facts = stored_facts(world, r.json()["requestId"])
    assert facts["quotaIncreasePct"] == 700.0, facts
    assert r.json()["status"] == "pending_approval", r.json()
