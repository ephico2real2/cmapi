"""#393: the capacity check answers `unknown`, never `fits` on fresh data, when the cluster's committed quota is not known;
and it counts a quota written with `cpu`/`memory`, which Kubernetes treats as `requests.cpu`/`requests.memory`.

The cluster in `world` has simulatedCapacity 64 cores and 256Gi, with dev overcommit 2.0 and 1.25: 128 cores and 320Gi."""
from __future__ import annotations

import time
import uuid

from cmapi.core.clients.kube import CacheState, WatchCache
from cmapi.core.errors import Problem

NS = {"namespace": "payments-dev", "tier": "small", "labels": {"cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410"},
      "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, "justification": "Payments service dev namespace"}
OLA = dict(roles=["cmapi-requester"], groups=["/cmapi/app-cmapi-rbac-requester"])


def auth(keys):
    return {"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())}


def quota(name: str, hard: dict[str, str], managed: bool = True) -> dict:
    return {"kind": "ResourceQuota",
            "metadata": {"name": f"{name}-quota", "namespace": name,
                         "labels": {"cmapi.net/managed": "true"} if managed else {}},
            "spec": {"hard": hard}}


def put_quota(ctx, q: dict) -> None:
    """A quota in the cache as the watch would hold it after an ADDED event."""
    cache = ctx.registry.cache("CRC")
    with cache._lock:
        cache.state["ResourceQuota"].items[WatchCache._key(q)] = q


def facts_for(cap) -> dict:
    """The facts of a small create on CRC that baseline-rnd-namespace matches, with this capacity answer."""
    return {"plugin": "namespaces", "action": "create", "environment": "dev", "namespace": "payments-dev", "clusterId": "CRC",
            "team": "payments", "tier": "small", "capacity": cap.status, "capacityFresh": cap.fresh, "automated": False,
            "requesterClient": None, "clusterLabels": {"region": "us-central"}, "warnings": [], "reason": None,
            "beyondTier": False, "beyondTierKeys": [], "networkExposure": False}


def assert_unknown(cap, reason_part: str) -> None:
    assert cap.status == "unknown" and cap.fresh is False, cap
    assert cap.binding_resource is None
    assert "cpu" not in cap.detail and "memory" not in cap.detail, "an unknown commitment is not shown as a ratio"
    assert reason_part in cap.detail["reason"], cap.detail


def assert_dry_run_unknown(client, keys) -> None:
    r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["capacity"]["status"] == "unknown" and body["capacity"]["fresh"] is False, body["capacity"]
    assert "cpu" not in body["capacity"] and "memory" not in body["capacity"], body["capacity"]
    assert body["approval"]["auto"] is None and body["approval"]["autoFallback"] == "capacity", body["approval"]


# ---- the control: a listed, current cache with no quotas fits, and the policy auto-approves
def test_listed_cache_fits_and_auto_approves(world):
    client, ctx, git, kube, validator, keys = world
    cap = ctx.pipeline.capacity.check("CRC", "dev", 2, 2 * 2**30)
    assert cap.status == "fits" and cap.fresh is True, cap
    assert ctx.pipeline.cfg.approvals.decide(facts_for(cap)).auto == "auto:baseline-rnd-namespace"
    body = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys)).json()
    assert body["capacity"]["status"] == "fits" and body["approval"]["auto"] == "auto:baseline-rnd-namespace"


# ---- unknown committed quota
def test_no_cache_is_unknown_and_not_auto_approved(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world

    def no_cache(cluster_id):
        raise Problem(503, "cluster-unreachable", f"{cluster_id} is unreachable: test", extra={"retryAfter": 30})
    monkeypatch.setattr(ctx.registry, "cache", no_cache)
    cap = ctx.pipeline.capacity.check("CRC", "dev", 16, 0)
    assert_unknown(cap, "no watch cache")
    req = ctx.pipeline.cfg.approvals.decide(facts_for(cap))
    assert req.auto is None and req.auto_fallback == "capacity", req


def test_quota_not_listed_is_unknown_and_not_auto_approved(world):
    client, ctx, git, kube, validator, keys = world
    cache = ctx.registry.cache("CRC")
    with cache._lock:
        cache.state["ResourceQuota"] = CacheState()           # the first list has not completed (or keeps failing)
    assert cache.state["Namespace"].last_good is not None
    cap = ctx.pipeline.capacity.check("CRC", "dev", 16, 0)
    assert_unknown(cap, "not listed")
    req = ctx.pipeline.cfg.approvals.decide(facts_for(cap))
    assert req.auto is None and req.auto_fallback == "capacity", req
    assert_dry_run_unknown(client, keys)


def test_stale_quota_watch_is_unknown_and_not_auto_approved(world):
    client, ctx, git, kube, validator, keys = world
    cache = ctx.registry.cache("CRC")
    with cache._lock:
        cache.state["ResourceQuota"].last_good = time.time() - cache.RELIST_SECONDS - 5
        cache.state["ResourceQuota"].error = "connection refused"
    cap = ctx.pipeline.capacity.check("CRC", "dev", 16, 0)
    assert_unknown(cap, "stale")
    req = ctx.pipeline.cfg.approvals.decide(facts_for(cap))
    assert req.auto is None and req.auto_fallback == "capacity", req
    assert_dry_run_unknown(client, keys)


def test_whole_cache_stale_ignores_a_kind_that_never_listed(world):
    """The premise (#393, design B): WatchCache.stale() takes the oldest good read of the kinds that have listed, so a kind
    that never listed does not make it stale. Its one caller (policy reports) checks listing itself; the capacity check
    reads the ResourceQuota kind's own state instead."""
    client, ctx, git, kube, validator, keys = world
    cache = ctx.registry.cache("CRC")
    with cache._lock:
        cache.state["ResourceQuota"] = CacheState()
    assert cache.stale()[0] is False
    assert cache.kind_stale("ResourceQuota") == (True, None)
    assert cache.kind_stale("Namespace")[0] is False


# ---- the quota keys Kubernetes treats as the same resource
def test_cpu_key_is_counted(world):
    client, ctx, git, kube, validator, keys = world
    put_quota(ctx, quota("big", {"cpu": "120"}))
    cap = ctx.pipeline.capacity.check("CRC", "dev", 16, 0)
    assert cap.status == "exceeded" and cap.binding_resource == "cpu" and cap.detail["cpu"] == round(136 / 128, 3), cap


def test_memory_key_is_counted(world):
    client, ctx, git, kube, validator, keys = world
    put_quota(ctx, quota("big", {"memory": "300Gi"}))
    cap = ctx.pipeline.capacity.check("CRC", "dev", 0, 0)
    assert cap.status == "warn" and cap.binding_resource == "memory" and cap.detail["memory"] == round(300 / 320, 3), cap


def test_both_keys_count_once_at_the_bound_the_api_server_enforces(world):
    """Both keys limit the same sum of pod requests, and the quota admission refuses a pod that exceeds either: the
    namespace can commit no more than the smaller one. Neither the sum nor the larger is counted."""
    client, ctx, git, kube, validator, keys = world
    put_quota(ctx, quota("both", {"requests.cpu": "100", "cpu": "10", "requests.memory": "64Gi", "memory": "128Gi"}))
    cap = ctx.pipeline.capacity.check("CRC", "dev", 0, 0)
    assert cap.detail["cpu"] == round(10 / 128, 3) and cap.detail["memory"] == round(64 / 320, 3), cap
    assert cap.status == "fits" and cap.fresh is True


def test_unmanaged_quota_is_still_not_counted(world):
    client, ctx, git, kube, validator, keys = world
    put_quota(ctx, quota("theirs", {"cpu": "120", "requests.cpu": "120"}, managed=False))
    cap = ctx.pipeline.capacity.check("CRC", "dev", 0, 0)
    assert cap.status == "fits" and cap.detail["cpu"] == 0.0, cap
