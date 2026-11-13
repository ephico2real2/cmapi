"""Admin routes: prune confirmation, the auto-approval kill switch, integrations, the Git log, KPIs."""
from __future__ import annotations

from typing import Any

from fastapi import Depends
from pydantic import Field

from cmapi import __version__
from cmapi.core.context import AppContext
from cmapi.core.db.repo import AuditRepo, JobRepo, RequestRepo, SwitchRepo
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.git.base import GitUnavailable
from cmapi.core.identity.claims import Identity
from cmapi.core.kpi import kpi_report
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.models import Api, ChangeRequest, PruneConfirm
from cmapi.core.observability import AUTO_PAUSED
from cmapi.core.views import request_view
from cmapi.routers import ctx, require

router = DocumentedRouter("admin", prefix="/api/v1/admin", version=__version__, group="Admin",
                          description="What an operator of the instance uses: the auto-approval switch, the prune confirmation, "
                                      "the integration modes, the Git log and the system KPIs.")


class SwitchBody(Api):
    reason: str = Field(description="Why the switch is being changed", examples=["incident 1234"])


class SwitchView(Api):
    paused: bool = Field(description="Whether auto-approval is paused", examples=[False])
    reason: str | None = Field(default=None, description="Why", examples=["incident 1234"])
    set_by: str | None = Field(default=None, description="Who set it", examples=["opal"])
    set_at: str | None = Field(default=None, description="When", examples=["2026-11-05T10:00:00+00:00"])


class GitLog(Api):
    log: list[str] = Field(description="Recent commits on the default branch", examples=[["0a1b2c3d create payments-dev"]])


class Integrations(Api):
    delivery: dict[str, Any] = Field(description="Delivery mode and its settings", examples=[{"mode": "apply"}])
    sync_signal: dict[str, Any] = Field(description="poll or notify, per the default", examples=[{"default": "poll"}])
    operations: dict[str, Any] = Field(description="Operations engine", examples=[{"engine": "builtin"}])
    events: dict[str, Any] = Field(description="Event publisher", examples=[{"publisher": "none"}])
    clusters: dict[str, str] = Field(description="Cluster ID to import status", examples=[{"CRC": "connected"}])


class KpiView(Api):
    model_config = {"extra": "allow"}
    instance: str = Field(description="Instance", examples=["nonprod"])
    thresholds: dict[str, Any] = Field(description="kpi.thresholds from the chart", examples=[{"memoryPercent": 80}])
    components: list[dict[str, Any]] = Field(description="Self-reported system metrics per component", examples=[[]])
    database: dict[str, Any] = Field(description="Pool, connections, size; unavailable when not measured", examples=[{}])
    kpis: list[dict[str, Any]] = Field(description="The KPI table rows cmapi can compute from its database", examples=[[]])


@router.write("/prune:confirm", summary="Confirm the prune of a deleted namespace", permission="operations:run",
              response_model=ChangeRequest, status_code=200, problems=["nothing-to-prune", "validation-failed", "environment-forbidden"])
def prune_confirm(body: PruneConfirm, who: Identity = Depends(require("operations:run")), c: AppContext = Depends(ctx)) -> dict:
    """An operator confirms that a merged delete may remove the namespace. In `argocd` delivery the
    confirmation happens in Argo CD and the worker observes it; in `apply` delivery this call is the
    confirmation and the worker's delivery job removes the namespace."""
    with c.db.session() as s:
        repo, jobs = RequestRepo(s), JobRepo(s)
        # sync_failed: a delete that failed before anyone confirmed it, still waiting for this call in apply mode.
        rows = [r for r in repo.in_states([S.AWAITING_PRUNE.value, S.SYNC_FAILED.value])
                if r.namespace == body.namespace and r.action == "delete"
                and (body.cluster_id is None or r.cluster_id == body.cluster_id)]
        if not rows:
            raise Problem.conflict("nothing-to-prune", f"No delete of {body.namespace} is awaiting a prune")
        if len(rows) > 1:
            raise Problem.unprocessable("validation-failed", f"{body.namespace} is awaiting a prune on "
                                        f"{sorted(r.cluster_id for r in rows)}; send clusterId")
        row = rows[0]
        c.cfg.roles.require(who, "operations:run", row.env)
        repo.event(row, "prune_confirm", who.username, "operator confirmed the prune")
        AuditRepo(s).record(who, "prune.confirm", f"{row.cluster_id}/{row.namespace}", {"requestId": row.request_id})
        jobs.enqueue("prune", request_id=row.request_id, cluster_id=row.cluster_id)
        return request_view(repo, row)


@router.write("/auto-approval:pause", summary="Pause auto-approval", permission="approvals:pause",
              response_model=SwitchView, status_code=200)
def pause(body: SwitchBody, who: Identity = Depends(require("approvals:pause")), c: AppContext = Depends(ctx)) -> dict:
    """The kill switch: every request follows the normal rules until resumed. Immediate, no PR; recorded with who and why."""
    with c.db.session() as s:
        SwitchRepo(s).set("auto-approval", {"paused": True, "reason": body.reason}, who.username)
        AuditRepo(s).record(who, "auto-approval.pause", "instance", {"reason": body.reason})
    AUTO_PAUSED.set(1)
    return _switch(c)


@router.write("/auto-approval:resume", summary="Resume auto-approval", permission="approvals:pause",
              response_model=SwitchView, status_code=200)
def resume(body: SwitchBody, who: Identity = Depends(require("approvals:pause")), c: AppContext = Depends(ctx)) -> dict:
    """Turns the kill switch off again."""
    with c.db.session() as s:
        SwitchRepo(s).set("auto-approval", {"paused": False, "reason": body.reason}, who.username)
        AuditRepo(s).record(who, "auto-approval.resume", "instance", {"reason": body.reason})
    AUTO_PAUSED.set(0)
    return _switch(c)


@router.read("/auto-approval", summary="Auto-approval switch state", permission="requests:read", response_model=SwitchView)
def switch_state(who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """Whether the kill switch is on, who set it and why."""
    return _switch(c)


def _switch(c: AppContext) -> dict:
    with c.db.session() as s:
        v = SwitchRepo(s).get("auto-approval") or {}
    return {"paused": bool(v.get("paused")), "reason": v.get("reason"), "setBy": v.get("setBy"), "setAt": v.get("setAt")}


@router.read("/integrations", summary="Integration modes and health", permission="clusters:read", response_model=Integrations)
def integrations(who: Identity = Depends(require("clusters:read")), c: AppContext = Depends(ctx)) -> dict:
    """Each integration's mode (delivery, sync signal, operations engine, event publisher) and the import status per cluster."""
    i = c.integrations
    return {"delivery": {"mode": c.delivery.mode, "pollSeconds": c.delivery.poll_seconds,
                         "syncTimeoutSeconds": c.delivery.sync_timeout_seconds},
            "syncSignal": i.get("syncSignal") or {"default": "poll"}, "operations": i.get("operations") or {"engine": "builtin"},
            "events": i.get("events") or {"publisher": "none"}, "clusters": c.registry.status_map()}


@router.read("/git-log", summary="Recent commits in cluster-configs", permission="reports:read", response_model=GitLog,
             problems=["git-unavailable"])
def git_log(who: Identity = Depends(require("reports:read")), c: AppContext = Depends(ctx)) -> dict:
    """The last commits on the repository's default branch: the bot's merges."""
    try:
        return {"log": c.git.log()}
    except GitUnavailable as exc:
        raise Problem(502, "git-unavailable", str(exc)[:300]) from exc


@router.read("/kpi", summary="System KPIs", permission="reports:read", response_model=KpiView)
def kpi(who: Identity = Depends(require("reports:read")), c: AppContext = Depends(ctx)) -> dict:
    """The KPIs tab's data: each component's cgroup memory and CPU against its limit, the database figures,
    and the KPI rows cmapi computes from its own tables. A figure that cannot be measured reads unavailable, never 0."""
    return kpi_report(c)
