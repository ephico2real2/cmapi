"""CapacityBackend adapters (core/ports.py).

SimulatedCapacity is the phase 1 and 2 backend: the cluster's size comes from
clusters.yaml (simulatedCapacity) and the commitment from the ResourceQuotas in the watch
cache, exactly as examples/local did. It answers fresh=True because its data is the live
quota list, and it is named so that no reader mistakes it for measured capacity. Phase 3
replaces it with cmapi-capacity's snapshots from Thanos (capacity/).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from cmapi.core.ports import CapacityResult
from cmapi.core.registry import ClusterRegistry
from cmapi.core.tiers import qty


class SimulatedCapacity:
    def __init__(self, registry: ClusterRegistry, overcommit: Mapping[str, Mapping[str, float]],
                 targets: Mapping[str, Mapping[str, Any]]):
        self.registry, self.overcommit, self.targets = registry, overcommit, targets

    def _committed(self, cluster_id: str) -> tuple[Decimal, Decimal]:
        cpu = mem = Decimal(0)
        try:
            cache = self.registry.cache(cluster_id)
        except Exception:                                           # noqa: BLE001 - no cache: nothing committed is known
            return cpu, mem
        for q in cache.all("ResourceQuota"):
            if q.get("metadata", {}).get("labels", {}).get("cmapi.net/managed") != "true":
                continue
            hard = q.get("spec", {}).get("hard", {})
            cpu += qty(hard.get("requests.cpu", "0"))
            mem += qty(hard.get("requests.memory", "0"))
        return cpu, mem

    def check(self, cluster_id: str, environment: str, cpu_delta: float, memory_delta: float) -> CapacityResult:
        st = self.registry.get(cluster_id)
        size = st.policy.simulated_capacity if st.policy else None
        if not size:
            return CapacityResult("unknown", False, None, {"reason": "no simulatedCapacity for this cluster"})
        over = self.overcommit.get(environment) or {"cpu": 1.0, "memory": 1.0}
        warn = ((self.targets.get(environment) or {}).get("commitment") or {}).get("warn", 0.85)
        committed_cpu, committed_mem = self._committed(cluster_id)
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
