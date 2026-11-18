"""CapacityBackend adapters (core/ports.py).

SimulatedCapacity is the phase 1 and 2 backend: the cluster's size comes from
clusters.yaml (simulatedCapacity) and the commitment from the ResourceQuotas in the watch
cache, exactly as examples/local did. It answers fresh=True only while that quota list is
current: when the cluster has no cache, its ResourceQuotas have not listed, or their watch
is stale, the commitment is not known and the answer is unknown, never a ratio over 0 (#393).
It is named so that no reader mistakes it for measured capacity. Phase 3 replaces it with
cmapi-capacity's snapshots from Thanos (capacity/).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from cmapi.core.errors import Problem
from cmapi.core.ports import CapacityResult
from cmapi.core.registry import ClusterRegistry
from cmapi.core.tiers import qty

# A quota's `cpu` and `memory` are the same resources as `requests.cpu` and `requests.memory`
# (https://kubernetes.io/docs/concepts/policy/resource-quotas/): the pod evaluator charges a pod's requests to both names,
# and quota admission refuses a pod that exceeds either hard value (kubernetes v1.34.0, pkg/quota/v1/evaluator/core/pods.go,
# podComputeUsageHelper; staging/src/k8s.io/apiserver/pkg/quota/v1/resources.go, LessThanOrEqual). So a quota with both
# lets the namespace commit the smaller of the two, and that is what is counted, once.
REQUEST_KEYS = {"cpu": ("requests.cpu", "cpu"), "memory": ("requests.memory", "memory")}


def committed_by(hard: Mapping[str, Any], resource: str) -> Decimal:
    """What one quota's hard values let its namespace commit of `resource` (cpu or memory) in requests: the smallest bound
    the API server enforces, or 0 when the quota bounds neither name."""
    bounds = [qty(hard[k]) for k in REQUEST_KEYS[resource] if k in hard]
    return min(bounds, default=Decimal(0))


class SimulatedCapacity:
    def __init__(self, registry: ClusterRegistry, overcommit: Mapping[str, Mapping[str, float]],
                 targets: Mapping[str, Mapping[str, Any]]):
        self.registry, self.overcommit, self.targets = registry, overcommit, targets

    def _committed(self, cluster_id: str) -> tuple[Decimal, Decimal] | str:
        """The requests (cores, bytes) that cmapi's quotas on the cluster commit, or why they are not known."""
        try:
            cache = self.registry.cache(cluster_id)
        except Problem as exc:
            return f"no watch cache for this cluster: {exc.detail}"
        stale, last = cache.kind_stale("ResourceQuota")
        status, error = cache.kind_error("ResourceQuota")
        if status in (401, 403):
            # The API server refuses the reader (a revoked grant, a rotated token): no relist can succeed, so the items
            # held from before are not current, however recent their last good read. Transient errors stay bounded by
            # the relist window instead, so a dropped watch does not flap the answer.
            return f"the API server refuses the reader's ResourceQuota reads ({status}): {error}"
        if last is None:
            return "the cluster's ResourceQuotas have not listed yet" + (f": {error}" if error else "")
        if stale:
            return f"the ResourceQuota watch is stale: no good read for over {cache.RELIST_SECONDS}s"
        cpu = mem = Decimal(0)
        for q in cache.all("ResourceQuota"):
            if q.get("metadata", {}).get("labels", {}).get("cmapi.net/managed") != "true":
                continue
            hard = q.get("spec", {}).get("hard", {})
            cpu += committed_by(hard, "cpu")
            mem += committed_by(hard, "memory")
        return cpu, mem

    def check(self, cluster_id: str, environment: str, cpu_delta: float, memory_delta: float) -> CapacityResult:
        st = self.registry.get(cluster_id)
        size = st.policy.simulated_capacity if st.policy else None
        if not size:
            return CapacityResult("unknown", False, None, {"reason": "no simulatedCapacity for this cluster"})
        committed = self._committed(cluster_id)
        if isinstance(committed, str):
            return CapacityResult("unknown", False, None, {"reason": committed, "source": "simulated",
                                                           "clusterId": cluster_id})
        committed_cpu, committed_mem = committed
        over = self.overcommit.get(environment) or {"cpu": 1.0, "memory": 1.0}
        warn = ((self.targets.get(environment) or {}).get("commitment") or {}).get("warn", 0.85)
        cap_cpu = qty(size["cpu"]) * Decimal(str(over["cpu"]))
        cap_mem = qty(size["memory"]) * Decimal(str(over["memory"]))
        ratios = {"cpu": (committed_cpu + Decimal(str(cpu_delta))) / cap_cpu,
                  "memory": (committed_mem + Decimal(str(memory_delta))) / cap_mem}
        worst = max(ratios, key=ratios.get)
        r = float(ratios[worst])
        status = "exceeded" if r > 1 else "warn" if r >= warn else "fits"
        return CapacityResult(status, True, worst, {k: round(float(v), 3) for k, v in ratios.items()} |
                              {"source": "simulated", "clusterId": cluster_id})

    def place(self, environment: str, team: str, tier: str, constraints: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("placement arrives with cmapi-capacity (phase 3)")

    def reserve(self, request_id: str, cluster_id: str, cpu: float, memory: float) -> None:
        return None

    def release(self, request_id: str) -> None:
        return None
