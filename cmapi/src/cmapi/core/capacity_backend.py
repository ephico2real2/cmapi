"""CapacityBackend adapters (core/ports.py).

SimulatedCapacity is the phase 1 and 2 backend: the cluster's size comes from
clusters.yaml (simulatedCapacity) and the commitment from the cluster's quota ledger
(core/capacity_ledger.py), which the watch cache keeps as each ResourceQuota arrives: per
namespace the smallest unscoped managed quota, scoped quotas left out (#302). The arithmetic is
core/capacity.py's, the one that GET /api/v1/capacity shows. It answers fresh=True only while that quota list is
current: when the cluster has no cache, its ResourceQuotas have not listed, or their watch
is stale, the commitment is not known and the answer is unknown, never a ratio over 0 (#393).
It is named so that no reader mistakes it for measured capacity. Phase 3 replaces it with
cmapi-capacity's snapshots from Thanos (capacity/).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from cmapi.core.capacity import CapacitySettings, limit_of
from cmapi.core.capacity_ledger import CapacityLedger, LedgerTotals
from cmapi.core.clients.kube import WatchCache
from cmapi.core.errors import Problem
from cmapi.core.ports import CapacityResult
from cmapi.core.registry import ClusterRegistry, ClusterState
from cmapi.core.tiers import qty


@dataclass(frozen=True)
class QuotaRead:
    """What can be said of one cluster's committed quota: the plan's check and GET /api/v1/capacity read it here, so they agree
    on what is known."""
    state: str                                  # ok, loading, forbidden, stale or unreachable
    detail: str | None
    last_good: float | None                     # the ResourceQuota kind's last good read
    totals: LedgerTotals | None                 # with ok, and the last ones read with stale; None otherwise


def read_quotas(registry: ClusterRegistry, cluster_id: str) -> QuotaRead:
    try:
        cache, ledger = registry.quota_watch(cluster_id)
    except Problem as exc:
        return QuotaRead("unreachable", f"no watch cache for this cluster: {exc.detail}", None, None)
    return _read_cached_quotas(cache, ledger)


def read_snapshot_quotas(st: ClusterState) -> QuotaRead:
    cache, ledger = st.cache, st.ledger
    if cache is None:
        detail = f"{st.cluster_id} is {st.status}: {'; '.join(st.findings)}"
        return QuotaRead("unreachable", f"no watch cache for this cluster: {detail}", None, None)
    return _read_cached_quotas(cache, ledger)


def _read_cached_quotas(cache: WatchCache, ledger: CapacityLedger | None) -> QuotaRead:
    stale, last = cache.kind_stale("ResourceQuota")
    status, error = cache.kind_error("ResourceQuota")
    if status in (401, 403):
        # The API server refuses the reader (a revoked grant, a rotated token): no relist can succeed, so the items held from
        # before are not current, however recent their last good read. Transient errors stay bounded by the relist window
        # instead, so a dropped watch does not flap the answer.
        return QuotaRead("forbidden", f"the API server refuses the reader's ResourceQuota reads ({status}): {error}", last, None)
    if last is None:
        return QuotaRead("loading", "the cluster's ResourceQuotas have not listed yet" + (f": {error}" if error else ""), None,
                         None)
    if ledger is None:
        return QuotaRead("loading", "the cluster's quota ledger has not started", last, None)
    if stale:
        return QuotaRead("stale", f"the ResourceQuota watch is stale: no good read for over {cache.RELIST_SECONDS}s", last,
                         ledger.totals())
    return QuotaRead("ok", None, last, ledger.totals())


class SimulatedCapacity:
    def __init__(self, registry: ClusterRegistry, settings: CapacitySettings):
        self.registry, self.settings = registry, settings

    def check(self, cluster_id: str, environment: str, cpu_delta: float, memory_delta: float) -> CapacityResult:
        st = self.registry.get(cluster_id)
        size = st.policy.simulated_capacity if st.policy else None
        if not size:
            return CapacityResult("unknown", False, None, {"reason": "no simulatedCapacity for this cluster"})
        read = read_quotas(self.registry, cluster_id)
        if read.state != "ok" or read.totals is None:
            return CapacityResult("unknown", False, None, {"reason": read.detail, "source": "simulated",
                                                           "clusterId": cluster_id})
        env = self.settings.env(environment)
        deltas = {"cpu": Decimal(str(cpu_delta)), "memory": Decimal(str(memory_delta))}
        ratios = {r: (read.totals.committed[r] + deltas[r]) / limit_of(qty(size[r]), env.overcommit[r]) for r in deltas}
        worst = max(ratios, key=ratios.get)
        r = float(ratios[worst])                                   # compared as before #302, in floats
        status = "exceeded" if r > 1 else "warn" if r >= float(env.warn) else "fits"
        return CapacityResult(status, True, worst, {k: round(float(v), 3) for k, v in ratios.items()} |
                              {"source": "simulated", "clusterId": cluster_id})

    def place(self, environment: str, team: str, tier: str, constraints: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("placement arrives with cmapi-capacity (phase 3)")

    def reserve(self, request_id: str, cluster_id: str, cpu: float, memory: float) -> None:
        return None

    def release(self, request_id: str) -> None:
        return None
