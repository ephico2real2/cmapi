"""Admin routes: prune confirmation, the auto-approval kill switch, integrations, the plugins, the Git log, KPIs."""
from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, Request
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
from cmapi.core.plugins import BUILT_IN
from cmapi.core.views import request_view
from cmapi.routers import ctx, require

router = DocumentedRouter("admin", prefix="/api/v1/admin", version=__version__, group="Admin",
                          description="What an operator of the instance uses: the auto-approval switch, the prune confirmation, "
                                      "the integration modes, the plugins, the Git log and the system KPIs.")


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
    policy: dict[str, Any] = Field(description="The policy engine (kyverno or none), the mode of each served environment "
                                               "(enforce, audit or off), and kyvernoVersion: the Kyverno CLI that the image pins, "
                                               "the least version that the clusters must run (null outside the image)",
                                   examples=[{"engine": "kyverno", "kyvernoVersion": "v1.20.0",
                                              "environments": {"dev": "enforce", "rnd": "audit"}}])


class PluginRow(Api):
    name: str = Field(description="The plugin's name: its tag in this document, and its name in `plugins.yaml`", examples=["namespaces"])
    core: bool = Field(description="True for a part of the service itself, which `plugins.yaml` cannot switch", examples=[False])
    enabled: bool = Field(description="Whether this instance mounts the plugin's routes", examples=[True])
    version: str | None = Field(description="The version of the plugin. Null for a plugin that is not enabled: its code is not loaded",
                                examples=["0.1.0"])
    disabled_environments: list[str] = Field(description="The served environments where an override of `plugins.yaml` stops the "
                                                         "plugin's writes. The reads stay", examples=[["dev"]])


class PluginList(Api):
    instance: str = Field(description="The instance that answered", examples=["nonprod"])
    configured: bool = Field(description="False when the instance has no `plugins.yaml`: each built-in plugin is then enabled",
                             examples=[True])
    items: list[PluginRow] = Field(description="The core parts, then each built-in plugin, enabled or not")


class KpiRow(Api):
    id: str = Field(description="The stable ID of the KPI, as docs/17-kpis.md names it", examples=["change-failure-rate"])
    name: str = Field(description="The name that the portal shows", examples=["Change failure rate"])
    value: float | None = Field(description="The measured value. Null means not measured, never zero", examples=[0.021])
    unit: str = Field(description="`seconds` or `ratio` (0 to 1)", examples=["ratio"])
    target: str = Field(description="The target, as text", examples=["under 5%"])
    target_status: str = Field(description="`proposed` until the owner agrees the target, then `agreed`", examples=["proposed"])
    source: str = Field(description="Where the value comes from, and its formula in words",
                        examples=["database: failed, sync_failed or reverted requests over merged requests"])


class KpiComponent(Api):
    component: str = Field(description="`api`, `worker` or `capacity`: the process that answered", examples=["api"])
    measured_at: float = Field(description="When the figures were read, in seconds since 1970", examples=[1794580977.07])
    memory_bytes: int | None = Field(description="cgroup `memory.current`. Null outside a cgroup v2 container", examples=[183500800])
    memory_limit_bytes: int | None = Field(description="cgroup `memory.max`. Null when the container has no limit", examples=[536870912])
    cpu_usage_seconds: float | None = Field(description="cgroup `cpu.stat` `usage_usec`, in seconds, since the container started", examples=[412.6])
    cpu_limit_cores: float | None = Field(description="cgroup `cpu.max` as cores. Null when the container has no limit", examples=[0.5])
    cpu_periods: int | None = Field(description="cgroup `cpu.stat` `nr_periods`", examples=[90210])
    cpu_throttled_periods: int | None = Field(description="cgroup `cpu.stat` `nr_throttled`: the saturation signal", examples=[12])
    cpu_throttled_seconds: float | None = Field(description="cgroup `cpu.stat` `throttled_usec`, in seconds", examples=[0.8])


class KpiDatabase(Api):
    pool_size: int | None = Field(description="The size of this process's connection pool", examples=[5])
    pool_in_use: int | None = Field(description="Connections of the pool that are in use now", examples=[1])
    connections: int | None = Field(description="Connections to the server, from `pg_stat_activity`", examples=[8])
    connections_max: int | None = Field(description="The server's `max_connections`", examples=[100])
    size_bytes: int | None = Field(description="`pg_database_size` of cmapi's database", examples=[10255383])
    wal_bytes: int | None = Field(description="The size of the WAL folder. Null without the `pg_monitor` role", examples=[83886080])
    oldest_transaction_seconds: float | None = Field(description="The age of the oldest open transaction", examples=[0.0])


class KpiView(Api):
    instance: str = Field(description="Instance", examples=["nonprod"])
    thresholds: dict[str, float] = Field(description="The limit of each watch rule, as a percent or as hours",
                                         examples=[{"memoryPercent": 80, "cpuPercent": 80}])
    components: list[KpiComponent] = Field(description="The process that answered, with its own cgroup figures")
    database: KpiDatabase = Field(description="Pool, connections and size. A null value means not measured")
    kpis: list[KpiRow] = Field(description="Each KPI that cmapi computes from its database: the KPIs of docs/17-kpis.md with the status live")
    unavailable: str = Field(description="How to read a null value", examples=["a null value means not measured, never zero"])


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
    """Each integration's mode (delivery, sync signal, operations engine, event publisher, policy engine) and the import
    status per cluster."""
    i = c.integrations
    return {"delivery": {"mode": c.delivery.mode, "pollSeconds": c.delivery.poll_seconds,
                         "syncTimeoutSeconds": c.delivery.sync_timeout_seconds},
            "syncSignal": i.get("syncSignal") or {"default": "poll"}, "operations": i.get("operations") or {"engine": "builtin"},
            "events": i.get("events") or {"publisher": "none"}, "clusters": c.registry.status_map(),
            "policy": {"engine": c.cfg.policy.engine, "kyvernoVersion": os.environ.get("CMAPI_KYVERNO_VERSION") or None,
                       "environments": c.cfg.policy.modes(c.cfg.allowed_environments)}}


@router.read("/plugins", summary="The plugins of this instance", permission="clusters:read", response_model=PluginList)
def plugins(request: Request, who: Identity = Depends(require("clusters:read")), c: AppContext = Depends(ctx)) -> dict:
    """Each part of the API with its version, and what `plugins.yaml` says for this instance: whether a plugin is
    enabled, and the environments where an override stops its writes. A plugin that is not enabled has no route and
    is not in this document."""
    mounted, switch = request.app.state.plugins, c.cfg.plugins
    core = [{"name": name, "core": True, "enabled": True, "version": r.version, "disabledEnvironments": []}
            for name, r in sorted(mounted.items()) if name not in BUILT_IN]
    built_in = [{"name": name, "core": False, "enabled": switch.is_enabled(name),
                 "version": mounted[name].version if name in mounted else None,
                 "disabledEnvironments": switch.disabled_environments(name)} for name in sorted(BUILT_IN)]
    return {"instance": c.cfg.name, "configured": switch.configured, "items": core + built_in}


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
