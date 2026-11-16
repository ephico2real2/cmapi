"""System metrics, self-reported (docs/01, "System metrics, self-reported"): one definition per
figure, rendered to /metrics by prometheus_client collectors and to GET /admin/kpi as JSON, so
the page and Prometheus read one collector and cannot drift.

The pod's own cgroup v2 files are what the kernel limits and OOM-kills on. A value that cannot
be measured (cgroup v1, a limit of max, a database that does not answer) is omitted from
/metrics and reads unavailable in the JSON, never 0.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from prometheus_client import REGISTRY
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from sqlalchemy import text

from cmapi.core.naming import reserved

CGROUP = Path("/sys/fs/cgroup")
COMPONENT = os.environ.get("CMAPI_COMPONENT", "api")


def _read(name: str) -> str | None:
    try:
        return (CGROUP / name).read_text().strip()
    except OSError:
        return None


def cgroup_figures() -> dict[str, Any]:
    """memory.current, memory.max, cpu.max and cpu.stat, or unavailable where the file or value is not there."""
    out: dict[str, Any] = {"component": COMPONENT, "memoryBytes": None, "memoryLimitBytes": None, "cpuUsageSeconds": None,
                           "cpuLimitCores": None, "cpuPeriods": None, "cpuThrottledPeriods": None, "cpuThrottledSeconds": None}
    mem = _read("memory.current")
    if mem is not None and mem.isdigit():
        out["memoryBytes"] = int(mem)
    lim = _read("memory.max")
    if lim is not None and lim.isdigit():
        out["memoryLimitBytes"] = int(lim)
    cpu_max = _read("cpu.max")
    if cpu_max:
        quota, _, period = cpu_max.partition(" ")
        if quota.isdigit() and period.isdigit():
            out["cpuLimitCores"] = int(quota) / int(period)
    stat = _read("cpu.stat")
    if stat:
        kv = dict(line.split(" ", 1) for line in stat.splitlines() if " " in line)
        if "usage_usec" in kv:
            out["cpuUsageSeconds"] = int(kv["usage_usec"]) / 1e6
        if "nr_periods" in kv:
            out["cpuPeriods"] = int(kv["nr_periods"])
            out["cpuThrottledPeriods"] = int(kv.get("nr_throttled", 0))
            out["cpuThrottledSeconds"] = int(kv.get("throttled_usec", 0)) / 1e6
    return out


class CgroupCollector:
    """Exports the cgroup figures as cmapi_process_* with the component label; absent when unavailable."""

    def collect(self):
        f = cgroup_figures()
        labels = ["component"]
        if f["memoryBytes"] is not None:
            g = GaugeMetricFamily("cmapi_process_memory_bytes", "cgroup memory.current", labels=labels)
            g.add_metric([f["component"]], f["memoryBytes"])
            yield g
        if f["memoryLimitBytes"] is not None:
            g = GaugeMetricFamily("cmapi_process_memory_limit_bytes", "cgroup memory.max", labels=labels)
            g.add_metric([f["component"]], f["memoryLimitBytes"])
            yield g
        if f["cpuUsageSeconds"] is not None:
            c = CounterMetricFamily("cmapi_process_cpu_usage_seconds", "cgroup cpu.stat usage", labels=labels)
            c.add_metric([f["component"]], f["cpuUsageSeconds"])
            yield c
        if f["cpuLimitCores"] is not None:
            g = GaugeMetricFamily("cmapi_process_cpu_limit_cores", "cgroup cpu.max", labels=labels)
            g.add_metric([f["component"]], f["cpuLimitCores"])
            yield g
        if f["cpuPeriods"] is not None:
            for name, key in (("cmapi_process_cpu_periods", "cpuPeriods"),
                              ("cmapi_process_cpu_throttled_periods", "cpuThrottledPeriods"),
                              ("cmapi_process_cpu_throttled_seconds", "cpuThrottledSeconds")):
                c = CounterMetricFamily(name, "cgroup cpu.stat", labels=labels)
                c.add_metric([f["component"]], f[key])
                yield c


def namespace_counts(registry: Any, reserved_patterns: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """cluster ID -> {managed, unmanaged, excluded}, from the watch cache of each cluster whose namespaces are listed.

    managed: the label cmapi.net/managed=true. excluded: a name that nobody may ask for (core/naming.py: the built-in names
    and the instance's reservedPatterns), so cmapi can never manage it. unmanaged: each other namespace. A cluster with no
    cache, or whose first list has not ended, has no entry: not measured, never 0. docs/17, "Managed coverage"."""
    out: dict[str, dict[str, int]] = {}
    for cluster_id, st in sorted(registry.clusters.items()):
        cache = st.cache
        if cache is None or cache.state["Namespace"].last_good is None:
            continue
        counts = {"managed": 0, "unmanaged": 0, "excluded": 0}
        for obj in cache.all("Namespace"):
            meta = obj["metadata"]
            if (meta.get("labels") or {}).get("cmapi.net/managed") == "true":
                counts["managed"] += 1
            elif reserved(meta["name"], reserved_patterns) is not None:
                counts["excluded"] += 1
            else:
                counts["unmanaged"] += 1
        out[cluster_id] = counts
    return out


class NamespacesCollector:
    """Exports cmapi_namespaces{cluster_id, state} from the watch caches at each scrape (#172). The source is set by
    register_collectors, so a process with no registry exports no sample."""

    def __init__(self) -> None:
        self.registry: Any = None
        self.reserved_patterns: tuple[str, ...] = ()

    def collect(self):
        g = GaugeMetricFamily("cmapi_namespaces", "Namespaces by management state: managed, unmanaged or excluded",
                              labels=["cluster_id", "state"])
        if self.registry is not None:
            for cluster_id, counts in namespace_counts(self.registry, self.reserved_patterns).items():
                for state, n in counts.items():
                    g.add_metric([cluster_id, state], n)
        yield g


_namespaces = NamespacesCollector()
_registered = False


def register_collectors(registry: Any = None, reserved_patterns: tuple[str, ...] = ()) -> None:
    """Registers the collectors one time for the process. `registry` is the ClusterRegistry whose watch caches give
    cmapi_namespaces; the last caller's registry is the one that is read (a process has one)."""
    global _registered
    if registry is not None:
        _namespaces.registry, _namespaces.reserved_patterns = registry, tuple(reserved_patterns)
    if not _registered:
        REGISTRY.register(CgroupCollector())
        REGISTRY.register(_namespaces)
        _registered = True


def database_figures(db: Any) -> dict[str, Any]:
    """Pool, connections, size and WAL; each unavailable when the query cannot run."""
    out: dict[str, Any] = {"poolSize": None, "poolInUse": None, "connections": None, "connectionsMax": None,
                           "sizeBytes": None, "walBytes": None, "oldestTransactionSeconds": None}
    try:
        pool = db.engine.pool
        out["poolSize"] = pool.size()
        out["poolInUse"] = pool.checkedout()
    except Exception:                                                 # noqa: BLE001
        pass
    try:
        with db.engine.connect() as c:
            out["connections"] = c.execute(text("SELECT count(*) FROM pg_stat_activity")).scalar()
            out["connectionsMax"] = int(c.execute(text("SHOW max_connections")).scalar())
            out["sizeBytes"] = int(c.execute(text("SELECT pg_database_size(current_database())")).scalar())
            oldest = c.execute(text("SELECT extract(epoch FROM now() - min(xact_start)) FROM pg_stat_activity "
                                    "WHERE state <> 'idle' AND xact_start IS NOT NULL")).scalar()
            out["oldestTransactionSeconds"] = float(oldest) if oldest is not None else 0.0
            try:
                out["walBytes"] = int(c.execute(text("SELECT coalesce(sum(size), 0) FROM pg_ls_waldir()")).scalar())
            except Exception:                                         # noqa: BLE001 - needs pg_monitor
                out["walBytes"] = None
    except Exception:                                                 # noqa: BLE001
        pass
    return out


# The KPIs that GET /admin/kpi computes from the database (docs/17-kpis.md, status "live"). The id is the contract: docs/17 and
# the portal name a KPI by it, and tests/service/test_kpis.py fails when a live KPI of docs/17 is not here. A target is
# "proposed" until the owner agrees it.
OPEN_TO_SYNCED = "extract(epoch FROM finished_at - created_at)"
SUBMIT_TO_APPROVED = "extract(epoch FROM approved_at - created_at)"
AUTO = "requirement->>'auto' LIKE 'auto:%'"


def _row(kpi_id: str, name: str, value: float | None, unit: str, target: str, source: str) -> dict[str, Any]:
    return {"id": kpi_id, "name": name, "value": value, "unit": unit, "target": target, "targetStatus": "proposed", "source": source}


def database_kpis(session: Any, platform_group: str) -> list[dict[str, Any]]:
    """Each live KPI, from change_requests. A value is None when no request is in its denominator: not measured, never 0.

    `platform_group` is the approving group of the platform team: approval-rules.yaml `defaults.group`, the group that each
    threshold adds. The self-service rate counts the requests that needed no approval from it."""
    def one(sql: str, **params: Any) -> Any:
        return session.execute(text(sql), params).scalar()

    def ratio(numerator: str, denominator: str) -> float | None:
        bottom = one(f"SELECT count(*) FROM change_requests WHERE {denominator}") or 0
        return ((one(f"SELECT count(*) FROM change_requests WHERE {numerator}") or 0) / bottom) if bottom else None

    def percentile(p: float, expression: str, where: str) -> float | None:
        value = one(f"SELECT percentile_cont({p}) WITHIN GROUP (ORDER BY {expression}) FROM change_requests WHERE {where}")
        return float(value) if value is not None else None

    synced = "status = 'synced' AND finished_at IS NOT NULL"
    # A request with an approval from before migration 0004 has no stored slot, so it is in neither part of the rate.
    slot_known = ("NOT EXISTS (SELECT 1 FROM approvals a WHERE a.request_id = change_requests.request_id "
                  "AND a.counted_for IS NULL)")
    synced_known = one(f"SELECT count(*) FROM change_requests WHERE {synced} AND {slot_known}") or 0
    without_platform = one(
        f"SELECT count(*) FROM change_requests WHERE {synced} AND {slot_known} AND NOT EXISTS (SELECT 1 FROM approvals a "
        "WHERE a.request_id = change_requests.request_id AND a.counted_for = :platform)", platform=platform_group) or 0
    approved_by_people = f"approved_at IS NOT NULL AND NOT coalesce({AUTO}, false)"
    return [
        _row("lead-time-auto-p90", "Lead time, auto-approved (p90)", percentile(0.9, OPEN_TO_SYNCED, f"{synced} AND {AUTO}"),
             "seconds", "under 10 min", "database: submit to synced, requests that a policy approved"),
        _row("lead-time-approved-p90", "Lead time, with approval (p90)",
             percentile(0.9, OPEN_TO_SYNCED, f"{synced} AND NOT coalesce({AUTO}, false)"),
             "seconds", "under 1 business day", "database: submit to synced, requests that people approved"),
        _row("approval-turnaround-p50", "Approval turnaround (p50)", percentile(0.5, SUBMIT_TO_APPROVED, approved_by_people),
             "seconds", "4 h", "database: submit to approved, requests that people approved"),
        _row("approval-turnaround-p90", "Approval turnaround (p90)", percentile(0.9, SUBMIT_TO_APPROVED, approved_by_people),
             "seconds", "24 h", "database: submit to approved, requests that people approved"),
        _row("auto-approval-rate", "Auto-approval rate",
             ratio(AUTO, f"({AUTO}) OR requirement->>'autoFallback' IS NOT NULL"),
             "ratio", "tracked", "database: requests that a policy approved over requests that matched a policy"),
        _row("self-service-rate", "Self-service rate", (without_platform / synced_known) if synced_known else None,
             "ratio", "over 80%", f"database: synced requests with no approval that counted for {platform_group}, over synced requests"),
        _row("change-failure-rate", "Change failure rate",
             ratio("status IN ('failed', 'sync_failed', 'reverted')", "merged_at IS NOT NULL"),
             "ratio", "under 5%", "database: failed, sync_failed or reverted requests over merged requests"),
    ]


def kpi_report(ctx: Any) -> dict[str, Any]:
    thresholds = ((ctx.capacity_cfg or {}).get("kpi") or {}).get("thresholds") or {
        "memoryPercent": 80, "cpuPercent": 80, "throttledPercent": 1, "dbConnectionsPercent": 80, "dbVolumePercent": 80,
        "backupMaxAgeHours": 26}
    comp = cgroup_figures()
    comp["measuredAt"] = time.time()
    db = database_figures(ctx.db)
    try:
        with ctx.db.session() as s:
            kpis = database_kpis(s, ctx.cfg.approvals.defaults["group"])
    except Exception:                                                 # noqa: BLE001 - a database that does not answer: no row, not a zero
        kpis = []
    return {"instance": ctx.cfg.name, "thresholds": thresholds, "components": [comp], "database": db, "kpis": kpis,
            "unavailable": "a null value means not measured, never zero"}
