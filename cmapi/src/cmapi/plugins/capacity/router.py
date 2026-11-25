"""The capacity plugin, read side (#302): GET /api/v1/capacity, the fleet view of the Capacity tab.

Every figure comes from what the API process already watches, never from a call at request time (docs/01, "Reads are live"):
- the committed quota from each cluster's quota ledger (core/capacity_ledger.py), behind the gates of the plan's own check
  (`read_snapshot_quotas`, core/capacity_backend.py);
- the nodes' allocatable, zones and counts from each cluster's node watch (core/clients/nodes.py);
- the size and the targets from clusters.yaml and capacity.yaml.
The arithmetic is core/capacity.py's, the one a plan is judged by.

What a caller sees (docs/02, "Scope"; docs/14): only the clusters of the environments where the caller holds capacity:read,
and the groups computed from those clusters only. A cluster with no clusters.yaml entry has no environment to scope it by and
is not returned. No namespace is named. Unknown is null with a named state, never 0. Usage and history are null and listed in
`notMeasured` until the snapshots of cmapi-capacity (#21) fill them, with no change of contract.

The answer has a strong ETag over its exact bytes and `Cache-Control: private, no-cache` (RFC 9110 8.8.3 and 13.1.2; RFC 9111
5.2.2.4 and 5.2.2.7): the bytes depend on the caller's scope, so the cache is private and the tag differs per scope. The times
are cut to the minute, since each watch event or bookmark moves the last good read and the tab shows minutes.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, Query, Request, Response

from cmapi import __version__
from cmapi.core.capacity import NOT_MEASURED, RESOURCES, bound_by, group_figures, resource_figures, worst
from cmapi.core.capacity_backend import read_snapshot_quotas
from cmapi.core.config import environment_not_served
from cmapi.core.context import AppContext
from cmapi.core.docs import CONDITIONAL_READ, DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.etag import etag_of, not_modified
from cmapi.core.identity.claims import Identity
from cmapi.core.models import CapacityPage
from cmapi.core.registry import ClusterState
from cmapi.core.tiers import qty
from cmapi.routers import ctx, require

router = DocumentedRouter("capacity", prefix="/api/v1", version=__version__, group="Capacity and placement",
                          description="Each cluster's quota commitment against its size, live from the watch of its quotas and "
                                      "nodes, and the groups of clusters by clusters.yaml: the Capacity tab.")

GROUP_KEYS = ("environment", "region")
LABEL_KEY = re.compile(r"^label:([A-Za-z0-9]([-A-Za-z0-9_./]{0,251}[A-Za-z0-9])?)$")
MAX_GROUP_KEYS = 3

GroupBy = Annotated[str, Query(alias="groupBy", examples=["region,environment"],
                               description="The keys of the groups, comma-separated, 1 to 3 of `environment`, `region` and "
                                           "`label:<key>` (a clusters.yaml label). Another value returns 422 "
                                           "`validation-failed`.")]
EnvFilter = Annotated[str | None, Query(examples=["dev"],
                                        description="Only the clusters of this environment. One the instance does not serve "
                                                    "returns 422 `environment-not-served`; one where the caller lacks "
                                                    "capacity:read returns 403 `environment-forbidden`.")]
ClusterFilter = Annotated[str | None, Query(alias="clusterId", examples=["CRC"],
                                            description="Only this cluster. One that is not in the caller's scope returns 404 "
                                                        "`cluster-not-found`, as an unknown one does.")]


def _minute(t: float | datetime | None) -> datetime | None:
    """A time cut to the minute, in UTC: what the tab shows, and what keeps the ETag still between watch events."""
    if t is None:
        return None
    at = t if isinstance(t, datetime) else datetime.fromtimestamp(t, tz=timezone.utc)
    return at.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _group_by(raw: str) -> list[str]:
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    bad = [k for k in keys if k not in GROUP_KEYS and not LABEL_KEY.fullmatch(k)]
    if not keys or len(keys) > MAX_GROUP_KEYS or bad or len(set(keys)) != len(keys):
        raise Problem.unprocessable("validation-failed", f"groupBy is 1 to {MAX_GROUP_KEYS} distinct keys of "
                                                         f"{list(GROUP_KEYS)} or label:<key>, not {raw!r}")
    return keys


def _key_value(st: ClusterState, key: str) -> str | None:
    p = st.policy
    if key == "environment":
        return p.environment if p else None
    labels = (p.labels if p else {}) or {}
    value = labels.get(key.removeprefix("label:") if key.startswith("label:") else key)
    return str(value) if value is not None else None


def cluster_view(c: AppContext, st: ClusterState, env: str) -> dict[str, Any]:
    """One cluster's figures and its named state. Each figure that is not known is null."""
    p = st.policy
    es = c.capacity.env(env)
    simulated = {r: qty(p.simulated_capacity[r]) for r in RESOURCES} if p and p.simulated_capacity else None
    view: dict[str, Any] = {"clusterId": st.cluster_id, "env": env, "region": _key_value(st, "region"),
                            "writes": bool(p and p.writes), "state": "ok", "stateDetail": None, "asOf": None, "basis": None,
                            "nodesState": "ok", "nodesDetail": None, "nodes": None, "zones": None, "managedNamespaces": None,
                            "scopedQuotas": None, "status": None, "boundBy": None, "history": None}

    # The nodes: the cluster's allocatable, zones and counts.
    nodes = st.nodes                                  # once: the registry may clear or replace it while this view is built
    snap = nodes.snapshot() if st.status == "connected" and nodes is not None else None
    if st.status != "connected":
        nodes_state, nodes_detail = st.not_connected()
        view.update(nodesState=nodes_state, nodesDetail=nodes_detail)
    elif snap is None:
        view.update(nodesState="loading", nodesDetail="the node watch has not started")
    else:
        view.update(nodesState=snap.state, nodesDetail=snap.detail)
        if snap.known:
            view.update(nodes={"total": snap.total, "counted": snap.counted, "notReady": snap.not_ready,
                               "cordoned": snap.cordoned, "tainted": snap.tainted}, zones=list(snap.zones or ()))
    allocatable = {"cpu": snap.cpu, "memory": snap.memory} if snap is not None and snap.known else None
    sized_by_nodes = bool(allocatable and snap and snap.counted and all(allocatable[r] > 0 for r in RESOURCES))
    basis = "simulated" if simulated else "allocatable" if sized_by_nodes else None

    # The committed quota, behind the plan's own gates.
    totals, as_of = None, None
    if st.status != "connected":
        (state, detail), as_of = st.not_connected(), st.status_since
    else:
        read = read_snapshot_quotas(st)
        state, detail, totals, as_of = read.state, read.detail, read.totals, read.last_good
        if state in ("ok", "stale") and basis is None:
            if view["nodesState"] == "loading":
                state, detail = "loading", "the nodes are being listed: the cluster has no simulatedCapacity"
            else:
                why = view["nodesDetail"] or "no node counts toward allocatable"
                state, detail = "no-size", f"no simulatedCapacity in clusters.yaml, and the nodes' allocatable is not known: {why}"
        elif state == "ok" and basis == "allocatable" and snap is not None and snap.state == "stale":
            state, detail = "stale", snap.detail
        if basis == "allocatable" and snap is not None and snap.as_of is not None and as_of is not None:
            as_of = min(_minute(as_of), _minute(snap.as_of))                  # the older of the two reads
    view.update(state=state, stateDetail=None if state == "ok" else detail, asOf=_minute(as_of), basis=basis)
    if totals is not None:
        view.update(managedNamespaces=totals.namespaces, scopedQuotas=totals.scoped_quotas)

    for r in RESOURCES:
        view[r] = resource_figures(r, committed=totals.committed[r] if totals else None,
                                   quota_used=totals.quota_used(r) if totals else None,
                                   used_missing=totals.used_missing[r] if totals else None,
                                   simulated=simulated[r] if simulated else None,
                                   allocatable=allocatable[r] if allocatable else None, basis=basis, env=es)
    view["status"] = worst(view[r]["status"] for r in RESOURCES)
    view["boundBy"] = bound_by(view["cpu"]["commitment"], view["memory"]["commitment"])
    return view


def groups_of(clusters: list[dict[str, Any]], states: dict[str, ClusterState], keys: list[str]) -> list[dict[str, Any]]:
    """The groups, each over the clusters in scope that share its key values. A cluster whose state is not ok, or that takes no
    writes, is left out of the figures with the reason, and counted in `matching`."""
    grouped: dict[tuple[str | None, ...], list[dict[str, Any]]] = {}
    for view in clusters:
        grouped.setdefault(tuple(_key_value(states[view["clusterId"]], k) for k in keys), []).append(view)
    out = []
    for key, members in grouped.items():
        included, excluded = [], []
        for v in members:
            reason = v["state"] if v["state"] != "ok" else None if v["writes"] else "not-writable"
            if reason is None:
                included.append(v)
            else:
                excluded.append({"clusterId": v["clusterId"], "reason": reason, "asOf": v["asOf"]})
        out.append({"key": dict(zip(keys, key)), "name": " · ".join(k if k is not None else "—" for k in key),
                    "clusterIds": [v["clusterId"] for v in members], "matching": len(members), "included": len(included),
                    "coverage": round(len(included) / len(members), 4), "excluded": excluded, **group_figures(included)})
    return sorted(out, key=lambda g: g["name"])


def _targets(c: AppContext, envs: list[str]) -> list[dict[str, Any]]:
    out = []
    for env in envs:
        es = c.capacity.env(env)
        out.append({"env": env, "overcommit": {r: float(es.overcommit[r]) for r in RESOURCES},
                    "overcommitDefault": es.overcommit_default,
                    "commitment": {"warn": float(es.warn), "critical": float(es.critical)}})
    return out


@router.read("/capacity", summary="Get cluster capacity by group",
             returns="The capacity of each cluster in the caller's environments, grouped as asked, with each cluster's"
                     " targets and snapshot state.",
             permission="capacity:read", response_model=CapacityPage,
             problems=["validation-failed", "environment-not-served", "environment-forbidden", "cluster-not-found"],
             **CONDITIONAL_READ)
def capacity(request: Request, group_by: GroupBy = "region,environment", env: EnvFilter = None,
             cluster_id: ClusterFilter = None, who: Identity = Depends(require("capacity:read")),
             c: AppContext = Depends(ctx)) -> Response:
    """Each cluster of the environments where the caller holds capacity:read: what cmapi's ResourceQuotas commit against the
    cluster's size times the environment's overcommit, with the size's basis (`simulated` from clusters.yaml, or the nodes'
    `allocatable`), the nodes, the zones and a named state. Then the groups by `groupBy`, whose figures are recomputed from the
    included clusters: summed commitments, headroom floored at 0 per cluster, and the largest single placement.

    Read from each cluster's watch, never from the cluster at request time. A figure that is not known is null, never 0. The
    answer carries a strong ETag; If-None-Match answers 304, and an If-Match that does not list it answers 412."""
    keys = _group_by(group_by)
    if env is not None:
        if env not in c.cfg.allowed_environments:
            raise environment_not_served(c.cfg, env)
        c.cfg.roles.require(who, "capacity:read", env)
    envs = sorted(e for e in c.cfg.allowed_environments if c.cfg.roles.allowed(who, "capacity:read", e))
    if cluster_id is not None:
        known = c.registry.clusters.get(cluster_id)
        if known is None or known.environment not in envs:
            # The same answer for a cluster that does not exist and one outside the caller's scope: no existence leak.
            raise Problem(404, "cluster-not-found", f"Unknown cluster {cluster_id}")
    in_scope: dict[str, ClusterState] = {}
    hidden = 0
    for st in sorted(c.registry.snapshots(), key=lambda s: s.cluster_id):
        cenv = st.environment
        if cenv is None:
            continue                                     # no clusters.yaml entry: no environment to scope it by
        if cenv not in envs:
            hidden += 1
            continue
        if (env or cenv) == cenv and (cluster_id or st.cluster_id) == st.cluster_id:
            in_scope[st.cluster_id] = st
    clusters = [cluster_view(c, st, st.environment or "") for st in in_scope.values()]
    body = {"source": "live", "snapshotState": "not-built", "notMeasured": list(NOT_MEASURED), "groupBy": keys,
            "hiddenClusters": hidden, "targets": _targets(c, envs), "groups": groups_of(clusters, in_scope, keys),
            "clusters": clusters}
    data = CapacityPage.model_validate(body).model_dump_json().encode()
    etag = etag_of(data)
    # private: the bytes depend on the caller's scope (RFC 9111, 5.2.2.7); no-cache: revalidated before each reuse (5.2.2.4).
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if not_modified(request.headers, etag):
        return Response(status_code=304, headers=headers)
    return Response(data, media_type="application/json", headers=headers)

