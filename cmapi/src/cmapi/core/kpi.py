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


_registered = False


def register_collectors() -> None:
    global _registered
    if not _registered:
        REGISTRY.register(CgroupCollector())
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
            out["sizeBytes"] = c.execute(text("SELECT pg_database_size(current_database())")).scalar()
            oldest = c.execute(text("SELECT extract(epoch FROM now() - min(xact_start)) FROM pg_stat_activity "
                                    "WHERE state <> 'idle' AND xact_start IS NOT NULL")).scalar()
            out["oldestTransactionSeconds"] = float(oldest) if oldest is not None else 0.0
            try:
                out["walBytes"] = c.execute(text("SELECT coalesce(sum(size), 0) FROM pg_ls_waldir()")).scalar()
            except Exception:                                         # noqa: BLE001 - needs pg_monitor
                out["walBytes"] = None
    except Exception:                                                 # noqa: BLE001
        pass
    return out


def kpi_report(ctx: Any) -> dict[str, Any]:
    thresholds = ((ctx.capacity_cfg or {}).get("kpi") or {}).get("thresholds") or {
        "memoryPercent": 80, "cpuPercent": 80, "throttledPercent": 1, "dbConnectionsPercent": 80, "dbVolumePercent": 80,
        "backupMaxAgeHours": 26}
    comp = cgroup_figures()
    comp["measuredAt"] = time.time()
    db = database_figures(ctx.db)
    kpis: list[dict[str, Any]] = []
    try:
        with ctx.db.session() as s:
            total = s.execute(text("SELECT count(*) FROM change_requests")).scalar() or 0
            merged = s.execute(text("SELECT count(*) FROM change_requests WHERE merged_at IS NOT NULL")).scalar() or 0
            bad = s.execute(text("SELECT count(*) FROM change_requests WHERE status IN ('failed','sync_failed','reverted')")).scalar() or 0
            auto = s.execute(text("SELECT count(*) FROM change_requests WHERE requirement->>'auto' LIKE 'auto:%'")).scalar() or 0
            synced = s.execute(text("SELECT count(*) FROM change_requests WHERE status='synced'")).scalar() or 0
            human_touch = s.execute(text("SELECT count(DISTINCT request_id) FROM approvals")).scalar() or 0
            lead = s.execute(text("SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - created_at)) "
                                  "FROM change_requests WHERE status='synced'")).scalar()
        kpis = [
            {"name": "Change failure rate", "value": (bad / merged) if merged else None, "unit": "ratio", "target": "under 5%",
             "source": "database: failed, sync_failed or reverted over merged"},
            {"name": "Self-service rate", "value": ((synced - human_touch) / synced) if synced else None, "unit": "ratio",
             "target": "over 80%", "source": "database: synced requests with no human approval"},
            {"name": "Auto-approval rate", "value": (auto / total) if total else None, "unit": "ratio", "target": "tracked",
             "source": "database: requests approved at plan time"},
            {"name": "Lead time p90 (all)", "value": float(lead) if lead is not None else None, "unit": "seconds",
             "target": "under 10 min auto-approved", "source": "database: submit to synced"},
        ]
    except Exception:                                                 # noqa: BLE001
        kpis = []
    return {"instance": ctx.cfg.name, "thresholds": thresholds, "components": [comp], "database": db, "kpis": kpis,
            "unavailable": "a null value means not measured, never zero"}
