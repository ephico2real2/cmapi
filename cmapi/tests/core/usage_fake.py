"""A MetricsSource fake for the usage tests (#310): it answers the PromQL that cmapi/capacity/usage.py builds from per-namespace
figures, as a Thanos Querier would answer it, so the tests run the real queries, the real parsing and the real verdicts with
no Thanos. It reads which figure a query asks for from the query's text, and fails the test on a query it cannot place.

    NS = {"payments-dev": Fake(cpu=(now, avg7d, p95, peak, idle_p95), memory=(...), steps=4032,
                               quota={"cpu": (p95, hours_at_ceiling, peak), "memory": (...)})}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cmapi.capacity.usage import MetricsUnavailable

GiB = 2**30


@dataclass
class Fake:
    cpu: tuple[float | None, ...] = (1.0, 1.0, 1.0, 1.0, None)          # now, avg7d, p95, peak, idle p95 (None: the p95)
    memory: tuple[float | None, ...] = (GiB, GiB, GiB, GiB, None)
    steps: float | None = 4032
    quota: dict[str, tuple[float | None, float | None, float | None]] = field(default_factory=dict)


class FakeMetrics:
    def __init__(self, namespaces: dict[str, Fake] | None = None):
        self.namespaces = namespaces or {}
        self.fail: str | None = None            # the text of MetricsUnavailable on every query
        self.calls: list[tuple[str, str, datetime | None]] = []

    def query(self, cluster_id: str, promql: str, at: datetime | None = None) -> list[dict[str, Any]]:
        self.calls.append((cluster_id, promql, at))
        if self.fail:
            raise MetricsUnavailable(f"{cluster_id}: {self.fail}")
        m = re.search(r'namespace="([^"]+)"', promql)
        wanted = [m.group(1)] if m else list(self.namespaces)
        out = []
        for ns in wanted:
            f = self.namespaces.get(ns)
            if f is None:
                continue
            for labels, value in self._values(promql, f):
                if value is not None:
                    out.append({"metric": {"namespace": ns, **labels}, "value": [0, str(value)]})
        return out

    @staticmethod
    def _values(q: str, f: Fake) -> list[tuple[dict[str, str], float | None]]:
        if "kube_pod_status_phase" in q:
            return [({}, f.steps)]
        if "kube_resourcequota" in q:
            idx = 1 if ">= bool" in q else 0 if q.startswith("quantile_over_time") else 2 if q.startswith("max_over_time") else None
            assert idx is not None, f"a quota query the fake cannot place: {q}"
            return [({"resource": f"requests.{r}"}, v[idx]) for r, v in f.quota.items()]
        figures = f.cpu if "container_cpu_usage_seconds_total" in q else f.memory if "container_memory_working_set_bytes" in q else None
        assert figures is not None, f"a query the fake cannot place: {q}"
        if q.startswith("avg_over_time"):
            return [({}, figures[1])]
        if q.startswith("quantile_over_time"):
            if "[14d:5m]" in q:
                return [({}, figures[2])]
            return [({}, figures[4] if figures[4] is not None else figures[2])]
        if q.startswith("max_over_time"):
            return [({}, figures[3])]
        assert q.startswith("sum by (namespace)"), f"a query the fake cannot place: {q}"
        return [({}, figures[0])]
