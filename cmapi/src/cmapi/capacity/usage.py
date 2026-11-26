"""Namespace usage over the last 14 days, read live (#310; docs/03, "Collection"; docs/01, "Quota changes on existing namespaces").

A UsageSource answers two questions:

    namespace(cluster, ns)   one namespace, for a quota-change plan: now, 7-day average, 14-day p95 and peak, for CPU and
                             memory, with the window's coverage. Cached 10 minutes (docs/02: "cached 10 minutes").
    cluster(cluster, ...)    every namespace of one cluster at one instant, for the daily sweep: the same figures, the p95
                             over the environment's idle period, and the history of requests ÷ quota.

Two implementations: PromUsage over a MetricsSource (thanos.py in production, a fake in the tests), and NoUsage when
capacity.yaml names no source (`usage.source: none`, the default). NoUsage says so in every answer: insufficient data,
never a guess.

The PromQL is docs/03's, "Queries": "Every query is evaluated at one instant over [14d:5m] ... container!="" drops the
pod-level cgroup that would double-count, and image!="" drops the pause container." The functions, from
https://prometheus.io/docs/prometheus/latest/querying/functions/ (read 2026-11-25): avg_over_time "the average value of all
float or histogram samples in the specified interval", max_over_time "the maximum value of all float samples in the
specified interval", quantile_over_time "the φ-quantile (0 ≤ φ ≤ 1) of all float samples in the specified interval",
count_over_time "the count of all samples in the specified interval", rate "the per-second average rate of increase of the
time series in the range vector". A subquery (querying/basics/, same day): "Subquery allows you to run an instant query for a
given range and resolution. The result of a subquery is a range vector."

The metrics: cAdvisor's container_cpu_usage_seconds_total ("Counter | Cumulative cpu time consumed | seconds") and
container_memory_working_set_bytes ("Gauge | Current working set | bytes"), https://github.com/google/cadvisor/blob/master/
docs/storage/prometheus.md; kube-state-metrics' kube_resourcequota (labels resourcequota, namespace, resource, type; `type` is
"hard" or "used", internal/store/resourcequota.go) and kube_pod_status_phase ("The pods current phase", phase Pending,
Running, Succeeded, Failed or Unknown), https://github.com/kubernetes/kube-state-metrics/tree/main/docs/metrics; all read
2026-11-25.
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Literal, Mapping, Protocol, runtime_checkable

from cmapi.core.ports import MetricsSource
from cmapi.core.tiers import qty

WINDOW = "14d"
WINDOW_DAYS = 14
EXPECTED_STEPS = WINDOW_DAYS * 24 * 12          # 4,032 five-minute steps: docs/03, "Coverage"
MIN_COVERAGE = 0.8                              # docs/03: "a namespace needs at least 80% of the window's steps"
CACHE_SECONDS = 600                             # docs/02: live usage "cached 10 minutes"
RESOURCES = ("cpu", "memory")
QUOTA_KEYS = {"cpu": "requests.cpu", "memory": "requests.memory"}

State = Literal["ok", "insufficient-data", "unavailable"]


class MetricsUnavailable(RuntimeError):
    """A query that did not answer with data that can be trusted: no route, a transport error, a refusal, an error or a
    warning. Its text names the cluster and the cause, never a token."""


def sample(series: dict[str, Any]) -> float | None:
    """A series' value, or None for NaN, an infinity or a value of another shape: a sample that is not a number is missing,
    never zero."""
    value = series.get("value")
    if not isinstance(value, list) or len(value) != 2:
        return None
    try:
        v = float(value[1])
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


CPU = 'sum by (namespace) (rate(container_cpu_usage_seconds_total{{container!="", image!=""{sel}}}[5m]))'
MEMORY = 'sum by (namespace) (container_memory_working_set_bytes{{container!="", image!=""{sel}}})'
RUNNING = 'sum by (namespace) (kube_pod_status_phase{{phase="Running"{sel}}})'
# requests ÷ quota per namespace and resource: the highest used over the smallest hard, as docs/03's "Hours near the quota".
RATIO = ('(max by (namespace, resource) (kube_resourcequota{{type="used", resource=~"requests.cpu|requests.memory"{sel}}})'
         ' / min by (namespace, resource) (kube_resourcequota{{type="hard", resource=~"requests.cpu|requests.memory"{sel}}}))')


def selector(namespace: str | None) -> str:
    """The extra label matcher of one namespace. `namespace` is a DNS label (core/naming.py), so it has no quote to escape."""
    return f', namespace="{namespace}"' if namespace else ""


def usage_queries(sel: str) -> dict[str, str]:
    """The figures of the plan's "Live usage · last 14 days": now, 7-day average, 14-day p95 and peak, and the coverage."""
    out: dict[str, str] = {}
    for r, expr in (("cpu", CPU), ("memory", MEMORY)):
        e = expr.format(sel=sel)
        out[f"{r}.now"] = e
        out[f"{r}.avg7d"] = f"avg_over_time(({e})[7d:5m])"
        out[f"{r}.p95"] = f"quantile_over_time(0.95, ({e})[{WINDOW}:5m])"
        out[f"{r}.peak"] = f"max_over_time(({e})[{WINDOW}:5m])"
    out["coverage"] = f"count_over_time(({RUNNING.format(sel=sel)})[{WINDOW}:5m])"
    return out


def sweep_queries(idle_days: int, ceiling: float) -> dict[str, str]:
    """The sweep's queries over every namespace of a cluster: the usage figures, the p95 over the idle period when it is
    shorter than the window, and requests ÷ quota over the window (its hourly p95, the share of hours at or above the
    environment's ceiling, and its peak)."""
    out = usage_queries("")
    if idle_days != WINDOW_DAYS:
        for r, expr in (("cpu", CPU), ("memory", MEMORY)):
            out[f"{r}.idleP95"] = f"quantile_over_time(0.95, ({expr.format(sel='')})[{idle_days}d:5m])"
    ratio = RATIO.format(sel="")
    out["quota.p95"] = f"quantile_over_time(0.95, ({ratio})[{WINDOW}:1h])"
    out["quota.hoursAtCeiling"] = f"avg_over_time(({ratio} >= bool {ceiling})[{WINDOW}:1h])"
    out["quota.peak"] = f"max_over_time(({ratio})[{WINDOW}:5m])"
    return out


@dataclass(frozen=True)
class Figures:
    """One resource's usage over the window: CPU in cores, memory in bytes. None where Thanos had no sample."""
    now: float | None
    avg7d: float | None
    p95: float | None
    peak: float | None
    idle_p95: float | None = None       # the p95 over the environment's idle period; the window's p95 when they are equal


@dataclass(frozen=True)
class QuotaHistory:
    """requests ÷ quota of one resource over the window, from kube_resourcequota."""
    p95: float | None
    hours_at_ceiling: float | None      # the share of hours at or above the environment's ceiling, 0 to 1
    peak: float | None


@dataclass(frozen=True)
class NamespaceUsage:
    state: State
    reason: str | None                  # why the state is not ok, in a sentence
    coverage: float | None              # steps with a running-pod sample ÷ 4,032
    cpu: Figures | None = None
    memory: Figures | None = None
    quota: Mapping[str, QuotaHistory] = field(default_factory=dict)     # cpu, memory; the sweep's only
    evaluated_at: datetime | None = None

    def figures(self, resource: str) -> Figures | None:
        return self.cpu if resource == "cpu" else self.memory


@runtime_checkable
class UsageSource(Protocol):
    configured: bool

    def namespace(self, cluster_id: str, namespace: str) -> NamespaceUsage: ...

    def cluster(self, cluster_id: str, *, idle_days: int, ceiling: float, at: datetime) -> dict[str, NamespaceUsage]: ...


NOT_CONFIGURED = "No usage source is configured on this instance (capacity.yaml usage.source is none), so there is no 14-day usage."


class NoUsage:
    """capacity.yaml `usage.source: none`: every answer is insufficient data, and says why."""
    configured = False

    def namespace(self, cluster_id: str, namespace: str) -> NamespaceUsage:
        return NamespaceUsage("insufficient-data", NOT_CONFIGURED, None)

    def cluster(self, cluster_id: str, *, idle_days: int, ceiling: float, at: datetime) -> dict[str, NamespaceUsage]:
        return {}


def _judge_coverage(coverage: float | None, cpu: Figures, memory: Figures) -> tuple[State, str | None]:
    """docs/03: "Coverage: a namespace needs at least 80% of the window's steps, or it gets insufficient-data"; and a window
    with no usage sample has nothing to judge, never a zero."""
    if coverage is None:
        return "insufficient-data", "Thanos has no running-pod sample of this namespace in the last 14 days."
    if coverage < MIN_COVERAGE:
        return "insufficient-data", (f"Pods were seen in {coverage:.0%} of the 14-day window's {EXPECTED_STEPS:,} five-minute "
                                     f"steps; {MIN_COVERAGE:.0%} are needed.")
    missing = [r for r, f in (("CPU", cpu), ("memory", memory)) if f.p95 is None or f.peak is None]
    if missing:
        return "insufficient-data", f"Thanos has no {' or '.join(missing)} usage sample of this namespace in the last 14 days."
    return "ok", None


class PromUsage:
    """Usage from PromQL over a MetricsSource. The queries of one answer run in parallel, so a plan waits for the slowest
    one, within the source's timeout."""
    configured = True

    def __init__(self, metrics: MetricsSource, clock: Callable[[], float] = time.time, cache_seconds: float = CACHE_SECONDS,
                 sweep_metrics: MetricsSource | None = None):
        """`sweep_metrics`: the source the sweep reads with, when its timeout differs from a plan's (thanos.py)."""
        self.metrics, self.clock, self.cache_seconds = metrics, clock, cache_seconds
        self.sweep_metrics = sweep_metrics or metrics
        self._cache: dict[tuple[str, str], tuple[float, NamespaceUsage]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _run(metrics: MetricsSource, cluster_id: str, queries: Mapping[str, str], at: datetime) -> dict[str, list[dict[str, Any]]]:
        """Every query at the one instant `at`; MetricsUnavailable when any fails, so no answer mixes data and gaps."""
        with ThreadPoolExecutor(max_workers=min(8, len(queries))) as pool:
            futures = {name: pool.submit(metrics.query, cluster_id, q, at) for name, q in queries.items()}
            return {name: f.result() for name, f in futures.items()}

    def namespace(self, cluster_id: str, namespace: str) -> NamespaceUsage:
        now = self.clock()
        with self._lock:
            hit = self._cache.get((cluster_id, namespace))
        if hit and now - hit[0] < self.cache_seconds:
            return hit[1]
        at = datetime.fromtimestamp(now, timezone.utc)
        try:
            answers = self._run(self.metrics, cluster_id, usage_queries(selector(namespace)), at)
        except MetricsUnavailable as exc:
            # Not cached: the next plan asks again. docs/02: "the plan carries usage: unavailable".
            return NamespaceUsage("unavailable", f"Thanos did not answer: {exc}", None, evaluated_at=at)
        result = _assemble(answers, at).get(namespace) or NamespaceUsage(
            "insufficient-data", "Thanos has no running-pod sample of this namespace in the last 14 days.", None, evaluated_at=at)
        with self._lock:
            # Expired answers go as a new one comes in, so the cache holds at most the namespaces planned in 10 minutes.
            self._cache = {k: v for k, v in self._cache.items() if now - v[0] < self.cache_seconds}
            self._cache[(cluster_id, namespace)] = (now, result)
        return result

    def cluster(self, cluster_id: str, *, idle_days: int, ceiling: float, at: datetime) -> dict[str, NamespaceUsage]:
        """Every namespace that any figure names. MetricsUnavailable when a query fails: docs/03, "A failed or warned query
        gives that cluster's namespaces insufficient-data for the day"; the sweep writes that."""
        return _assemble(self._run(self.sweep_metrics, cluster_id, sweep_queries(idle_days, ceiling), at), at)


def _by_namespace(series: list[dict[str, Any]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for s in series:
        ns = (s.get("metric") or {}).get("namespace")
        if isinstance(ns, str):
            out[ns] = sample(s)
    return out


def _assemble(answers: Mapping[str, list[dict[str, Any]]], at: datetime) -> dict[str, NamespaceUsage]:
    values = {name: _by_namespace(series) for name, series in answers.items() if not name.startswith("quota.")}
    quota: dict[str, dict[str, dict[str, float | None]]] = {}       # ns -> resource -> measure -> value
    for name, series in answers.items():
        if not name.startswith("quota."):
            continue
        measure = name.split(".", 1)[1]
        for s in series:
            m = s.get("metric") or {}
            resource = next((r for r, key in QUOTA_KEYS.items() if m.get("resource") == key), None)
            if isinstance(m.get("namespace"), str) and resource:
                quota.setdefault(m["namespace"], {}).setdefault(resource, {})[measure] = sample(s)
    namespaces = set(quota).union(*(v.keys() for v in values.values()))
    out: dict[str, NamespaceUsage] = {}
    for ns in namespaces:
        def get(name: str) -> float | None:
            return values.get(name, {}).get(ns)

        figs = {r: Figures(get(f"{r}.now"), get(f"{r}.avg7d"), get(f"{r}.p95"), get(f"{r}.peak"),
                           get(f"{r}.idleP95") if f"{r}.idleP95" in values else get(f"{r}.p95")) for r in RESOURCES}
        steps = get("coverage")
        coverage = None if steps is None else min(1.0, steps / EXPECTED_STEPS)
        state, reason = _judge_coverage(coverage, figs["cpu"], figs["memory"])
        history = {r: QuotaHistory(q.get("p95"), q.get("hoursAtCeiling"), q.get("peak")) for r, q in quota.get(ns, {}).items()}
        out[ns] = NamespaceUsage(state, reason, coverage, figs["cpu"], figs["memory"], history, at)
    return out


SOURCES = ("none", "thanos")


def usage_source(raw: Mapping[str, Any] | None, registry: Any) -> UsageSource:
    """capacity.yaml `usage.source`: `thanos` reads each cluster's Thanos Querier (thanos.py), `none` (the default) reads
    nothing and says so. None is the default so that an instance whose reader has no cluster-monitoring-view grant, or a
    cluster with monitoring off (CRC, #489), shows insufficient data instead of a failure on every plan. A value of another
    kind stops the start."""
    block = (raw or {}).get("usage") or {}
    if not isinstance(block, Mapping) or set(block) - {"source"}:
        raise ValueError("capacity.yaml: usage takes the one key source")
    source = block.get("source", "none")
    if source not in SOURCES:
        raise ValueError(f"capacity.yaml: usage.source is one of {list(SOURCES)}, not {source!r}")
    if source == "none":
        return NoUsage()
    from cmapi.capacity.thanos import SWEEP_TIMEOUT_SECONDS, ThanosQuerier
    return PromUsage(ThanosQuerier(registry), sweep_metrics=ThanosQuerier(registry, SWEEP_TIMEOUT_SECONDS))


UNITS = {"cpu": "millicores", "memory": "bytes"}


def _whole(resource: str, value: float | Decimal | None) -> int | None:
    """An amount of the contract: CPU in millicores and memory in bytes, whole numbers (core/capacity.py, UNITS)."""
    if value is None:
        return None
    return int(round(float(value) * 1000)) if resource == "cpu" else int(round(float(value)))


def plan_usage(u: NamespaceUsage, old_hard: Mapping[str, str], new_hard: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The plan's "Live usage · last 14 days" (mockups/portal/Main.dc.html, qc.usage) and its approval facts.

    Each resource: now, 7-day average, 14-day p95 and peak, the quota now and planned, and the planned quota over the peak.
    The figures are null unless the state is ok: insufficient data is said, never shown as numbers to judge by. The facts are
    `usage` (the state) and, when the usage is known, `requestToPeakRatio`: the largest planned quota over the 14-day peak of
    a resource the change raises (docs/02, approval-rules.yaml: "requestToPeakRatio > 3   # namespace peak over 14 days, read
    live when the change is planned")."""
    ok = u.state == "ok"
    rows: dict[str, Any] = {}
    ratios: list[float] = []
    for r in RESOURCES:
        key = QUOTA_KEYS[r]
        before = qty(old_hard[key]) if key in old_hard else None
        after = qty(new_hard[key]) if key in new_hard else None
        f = u.figures(r) if ok else None
        over = float(after) / f.peak if f and f.peak and after is not None else None
        rows[r] = {"now": _whole(r, f.now if f else None), "avg7d": _whole(r, f.avg7d if f else None),
                   "p95": _whole(r, f.p95 if f else None), "peak": _whole(r, f.peak if f else None),
                   "quota": _whole(r, before), "newQuota": _whole(r, after),
                   "newOverPeak": round(over, 2) if over is not None else None}
        if over is not None and before is not None and after is not None and after > before:
            ratios.append(over)
    view = {"state": u.state, "reason": u.reason, "window": WINDOW,
            "coverage": round(u.coverage, 3) if u.coverage is not None else None,
            "evaluatedAt": u.evaluated_at.isoformat() if u.evaluated_at else None, "units": dict(UNITS), **rows}
    facts: dict[str, Any] = {"usage": u.state}
    if ratios:
        facts["requestToPeakRatio"] = round(max(ratios), 3)
    return view, facts
