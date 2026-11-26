"""The daily usage sweep and the verdicts it stores (#310; docs/03, "Running the sweep", "Data model and API").

    "Off-peak in each cluster's region, one cluster at a time ... One evaluation instant per sweep, so all of a cluster's
    measures describe the same window ... A failed or warned query gives that cluster's namespaces insufficient-data for the
    day, never a zero ... Only the day's verdicts, with their numbers, and the recommendations are stored."

The worker runs it once a day (jobs/usage_sweep.py), in the embedded mode of docs/01. GET /api/v1/quotas reads the latest
sweep of each cluster in one query and joins it in memory (docs/01, Lists: "Rows come from the watch cache joined in memory
with the latest verdicts ... nothing calls Thanos and nothing queries the database per row"). A missed sweep leaves the
previous day's verdicts in place, with their day (docs/02, "When it is down").

The quota and the requests now come from the watch cache, not Thanos (docs/03: "Quota comes from the API, not Thanos"):
per namespace, the smallest hard of its unscoped ResourceQuotas ("the effective hard value is the minimum across them,
never the sum"), scoped quotas left out ("It is reported separately and left out of the effective value").
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from cmapi.capacity.thanos import MetricsUnavailable
from cmapi.capacity.usage import QUOTA_KEYS, NamespaceUsage, UsageSource
from cmapi.capacity.verdicts import KINDS, AnalysisSettings, Headline, Verdict, headline, judge
from cmapi.core.db.models import AnalysisSweepRow, NamespaceVerdictRow
from cmapi.core.registry import ClusterState
from cmapi.core.tiers import qty

RETENTION_DAYS = 395                    # docs/03: namespace_verdicts "kept 13 months"
STEP = "5m"                             # docs/03: analysis.sweepStep, "5 minutes by default"
NO_SAMPLE = "Thanos has no running-pod sample of this namespace in the last 14 days."


def _unscoped(q: Mapping[str, Any]) -> bool:
    spec = q.get("spec") or {}
    return not spec.get("scopes") and not spec.get("scopeSelector")


def quota_now(cache: Any) -> dict[str, tuple[dict[str, float | None], dict[str, float | None]]]:
    """Per managed namespace: (requests, quota) now, CPU in cores and memory in bytes, from the watch cache. A resource with
    no unscoped hard limit is None in both."""
    by_ns: dict[str, list[Mapping[str, Any]]] = {}
    for q in cache.all("ResourceQuota"):
        if _unscoped(q):
            by_ns.setdefault(q["metadata"]["namespace"], []).append(q)
    out: dict[str, tuple[dict[str, float | None], dict[str, float | None]]] = {}
    for ns in cache.all("Namespace"):
        name = ns["metadata"]["name"]
        if (ns["metadata"].get("labels") or {}).get("cmapi.net/managed") != "true":
            continue
        requests: dict[str, float | None] = {}
        quotas: dict[str, float | None] = {}
        for r, key in QUOTA_KEYS.items():
            hards = [qty(q["spec"]["hard"][key]) for q in by_ns.get(name, []) if key in (q.get("spec") or {}).get("hard", {})]
            used = [qty((q.get("status") or {}).get("used", {}).get(key, "0")) for q in by_ns.get(name, [])
                    if key in (q.get("spec") or {}).get("hard", {})]
            quotas[r] = float(min(hards)) if hards else None
            requests[r] = float(max(used)) if used else None
        out[name] = (requests, quotas)
    return out


@dataclass(frozen=True)
class ClusterSweep:
    cluster_id: str
    day: date
    evaluated_at: datetime
    status: str                         # complete or failed
    detail: str | None
    verdicts: dict[str, list[Verdict]]  # namespace -> its verdicts


def sweep_cluster(st: ClusterState, usage: UsageSource, analysis: AnalysisSettings, at: datetime) -> ClusterSweep | None:
    """One cluster's verdicts at the instant `at`. None when the cluster has no environment or no watch cache to name its
    namespaces: nothing is written, and its previous verdicts stay."""
    env = st.environment
    cache = st.cache                    # once: the registry clears it when the cluster drops (#402)
    if env is None or cache is None:
        return None
    t = analysis.of(env)
    namespaces = quota_now(cache)
    status, detail = "complete", None
    try:
        measured = usage.cluster(st.cluster_id, idle_days=t.idle_days, ceiling=t.quota_tight_at, at=at)
    except MetricsUnavailable as exc:
        status, detail = "failed", str(exc)[:500]
        failed = NamespaceUsage("insufficient-data", f"The usage sweep of {at:%Y-%m-%d} could not read Thanos: {detail}", None,
                                evaluated_at=at)
        measured = {ns: failed for ns in namespaces}
    verdicts = {}
    for ns, (requests, quotas) in namespaces.items():
        u = measured.get(ns) or NamespaceUsage("insufficient-data", NO_SAMPLE, None, evaluated_at=at)
        verdicts[ns] = judge(env, t, u, requests, quotas)
    return ClusterSweep(st.cluster_id, at.date(), at, status, detail, verdicts)


class VerdictRepo:
    def __init__(self, session: Session):
        self.s = session

    def store(self, sweep: ClusterSweep) -> None:
        """The day's sweep of one cluster, replacing any earlier sweep of the same day (a rerun)."""
        self.s.execute(delete(NamespaceVerdictRow).where(NamespaceVerdictRow.cluster_id == sweep.cluster_id,
                                                         NamespaceVerdictRow.day == sweep.day))
        for ns, verdicts in sweep.verdicts.items():
            for v in verdicts:
                self.s.add(NamespaceVerdictRow(cluster_id=sweep.cluster_id, namespace=ns, day=sweep.day, resource=v.resource,
                                               verdict=v.verdict, kind=v.kind, evidence={**v.evidence, "reason": v.reason}))
        self.s.merge(AnalysisSweepRow(cluster_id=sweep.cluster_id, day=sweep.day, evaluated_at=sweep.evaluated_at,
                                      status=sweep.status, step=STEP, namespaces=len(sweep.verdicts), detail=sweep.detail))
        self.s.flush()

    def prune(self, today: date) -> int:
        """Deletes the verdicts and sweeps older than 13 months."""
        cutoff = today - timedelta(days=RETENTION_DAYS)
        removed = self.s.execute(delete(NamespaceVerdictRow).where(NamespaceVerdictRow.day < cutoff)).rowcount or 0
        self.s.execute(delete(AnalysisSweepRow).where(AnalysisSweepRow.day < cutoff))
        return removed

    def latest(self) -> dict[tuple[str, str], tuple[date, list[Verdict]]]:
        """The verdicts of each cluster's latest sweep, by (cluster, namespace), with the sweep's day: one query."""
        last = (select(AnalysisSweepRow.cluster_id, func.max(AnalysisSweepRow.day).label("day"))
                .group_by(AnalysisSweepRow.cluster_id).subquery())
        rows = self.s.execute(select(NamespaceVerdictRow).join(
            last, (NamespaceVerdictRow.cluster_id == last.c.cluster_id) & (NamespaceVerdictRow.day == last.c.day))).scalars()
        out: dict[tuple[str, str], tuple[date, list[Verdict]]] = {}
        for r in rows:
            evidence = dict(r.evidence)
            reason = str(evidence.pop("reason", ""))
            kind = r.kind if r.kind in ("ok", "info", "waste", "risk") else KINDS.get(r.verdict, "info")
            out.setdefault((r.cluster_id, r.namespace), (r.day, []))[1].append(
                Verdict(r.resource, r.verdict, kind, reason, evidence))   # type: ignore[arg-type]
        return out


def run_sweep(clusters: Iterable[ClusterState], usage: UsageSource, analysis: AnalysisSettings, session: Session,
              now: datetime | None = None) -> list[ClusterSweep]:
    """One sweep of every given cluster, one at a time, each at its own single instant; then the retention."""
    done = []
    for st in clusters:
        at = now or datetime.now(timezone.utc)
        sweep = sweep_cluster(st, usage, analysis, at)
        if sweep is None:
            continue
        VerdictRepo(session).store(sweep)
        done.append(sweep)
    VerdictRepo(session).prune((now or datetime.now(timezone.utc)).date())
    return done


def row_verdict(stored: tuple[date, list[Verdict]] | None, configured: bool) -> dict[str, Any]:
    """The verdict fields of one GET /api/v1/quotas row, from its stored verdicts: the headline, the resources it holds for,
    the sentence that says why, and the sweep's day. With none stored, insufficient-data that says why."""
    if stored is None:
        from cmapi.capacity.usage import NOT_CONFIGURED
        reason = NOT_CONFIGURED if not configured else "No usage sweep has judged this namespace yet; the sweep runs once a day."
        return {"verdict": "insufficient-data", "verdictKind": "info", "verdictResources": [], "verdictReason": reason,
                "verdictDay": None}
    day, verdicts = stored
    h: Headline = headline(verdicts)
    return {"verdict": h.verdict, "verdictKind": h.kind, "verdictResources": list(h.resources), "verdictReason": h.reason,
            "verdictDay": day.isoformat()}
