"""Cluster capacity snapshots (#21; docs/02, "Stored capacity", "Snapshot job"; docs/01, "Cluster snapshots").

    "cmapi-capacity queries each cluster's Thanos Querier every capacity.snapshotInterval (30 minutes by default, 15 to 60
    allowed). One set of per-node queries gives a row for the whole cluster, one per zone and one per node role (worker,
    infra, master). [...] Committed quota comes from the API, not Thanos, because ResourceQuota status is exact. A failed or
    warned query, or a gap over 5% between Thanos allocatable and the API node sum, marks the row incomplete; it is never
    written as zero." (docs/01)

The worker runs the job (jobs/capacity_snapshot.py), in the embedded mode of docs/01 ("One interface, two modes"). Each run:

1. lists the cluster's nodes from its API, and joins each to its zone (`topology.kubernetes.io/zone`), its roles
   (`node-role.kubernetes.io/<role>`; `control-plane` is `master`) and whether its allocatable counts, by the Capacity tab's
   own rule (core/clients/nodes.py, `counts`);
2. with capacity.yaml `usage.source: thanos`, evaluates the per-node queries of docs/02 at one instant, the end of the interval,
   with partial_response=false and dedup on (capacity/thanos.py), every query within SNAPSHOT_TIMEOUT_SECONDS;
3. writes one row for the cluster, one per zone and one per role. A node with several role labels (CRC's one node is master
   and worker) counts in each of its roles' rows.

With `usage.source: none` the rows have the API's figures and the committed quota, and the figures only Thanos gives
(requested, limits, used, running pods) are null: `source` is `api`. Nothing failed, so such a row is complete. Placement then
ranks on the API's figures and gives no credit for usage headroom (core/placement.py).

The queries (docs/02, "Snapshot job"; `[iv]` is the interval). Their labels, read 2026-11-26:
- kube-state-metrics (https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/pod-metrics.md):
  kube_pod_container_resource_requests and _limits carry `resource`, `unit`, `container`, `pod`, `namespace`, `node`;
  kube_pod_info carries `node`; kube_pod_status_phase carries `phase` "Pending|Running|Succeeded|Failed|Unknown".
- cAdvisor's container metrics get their `node` label from prometheus-operator's ServiceMonitor scrape config
  (pkg/prometheus/promcfg.go: "Relabel node labels with meta labels available with Prometheus >= v2.3", regex `Node;(.*)`
  over `__meta_kubernetes_endpoint_address_target_kind` and `_name`, target_label `node`), which OpenShift's monitoring uses.
Whole-node usage (node-exporter) and storage are not queried yet: they are null and named in `NOT_QUERIED`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from cmapi.capacity.thanos import MetricsUnavailable
from cmapi.capacity.usage import PromUsage, sample
from cmapi.core.capacity_ledger import amount, nano_units
from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeError, list_items
from cmapi.core.clients.nodes import counts, reduce_node
from cmapi.core.db.models import CapacitySnapshotRow
from cmapi.core.registry import ClusterState

RETENTION_DAYS = 395                     # docs/01: snapshots "13 months"
USAGE_WINDOW_DAYS = 14                   # docs/02: "Usage headroom is allocatable − the 14-day p95 of real usage"
SNAPSHOT_TIMEOUT_SECONDS = 60.0          # every query of one cluster's snapshot
MISMATCH = Decimal("0.05")               # docs/02: "differ by more than 5% (data-mismatch)"
NODE_PAGE = 500
ROLE_PREFIX = "node-role.kubernetes.io/"
ROLES = {"worker": "worker", "infra": "infra", "master": "master", "control-plane": "master"}
NOT_QUERIED = ("nodeUsedAvg", "storage")

# docs/02, "Snapshot job", per node. A Pending pod with no node has node="" and counts toward the cluster row only.
LIVE = 'max by (namespace, pod) (kube_pod_status_phase{phase=~"Pending|Running"} == 1)'
QUERIES = {
    "requested": f'sum by (node, resource) (kube_pod_container_resource_requests{{resource=~"cpu|memory"}} '
                 f'* on (namespace, pod) group_left() {LIVE})',
    "limits": f'sum by (node, resource) (kube_pod_container_resource_limits{{resource=~"cpu|memory"}} '
              f'* on (namespace, pod) group_left() {LIVE})',
    "allocatable": 'sum by (node, resource) (kube_node_status_allocatable{resource=~"cpu|memory"})',
    "running": 'count by (node) (kube_pod_info * on (namespace, pod) group_left() (kube_pod_status_phase{phase="Running"} == 1))',
}
CPU_USE = 'sum by (node) (rate(container_cpu_usage_seconds_total{container!="", image!=""}[5m]))'
MEMORY_USE = 'sum by (node) (container_memory_working_set_bytes{container!="", image!=""})'


def queries(interval_seconds: int) -> dict[str, str]:
    """Every query of one snapshot: average and peak over the interval in 5-minute steps, so a spike between runs is kept."""
    iv = f"{interval_seconds // 60}m"
    out = dict(QUERIES)
    for res, expr in (("cpu", CPU_USE), ("memory", MEMORY_USE)):
        out[f"{res}.usedAvg"] = f"avg_over_time(({expr})[{iv}:5m])"
        out[f"{res}.usedPeak"] = f"max_over_time(({expr})[{iv}:5m])"
    return out


def floor_to_interval(at: datetime, interval_seconds: int) -> datetime:
    """docs/02: "Snapshot times are floored to the interval boundary, so history buckets line up across clusters"."""
    ts = int(at.timestamp())
    return datetime.fromtimestamp(ts - ts % interval_seconds, tz=timezone.utc)


# --------------------------------------------------------------------------- the nodes

@dataclass(frozen=True)
class NodeFacts:
    """What a snapshot keeps of one Node. Amounts in cores and bytes; None where the kubelet reports none."""
    name: str
    zone: str | None
    roles: tuple[str, ...]
    counted: bool                        # its allocatable is capacity (core/clients/nodes.py, `counts`)
    ready: bool
    memory_pressure: bool
    disk_pressure: bool
    capacity: dict[str, Decimal | None]
    allocatable: dict[str, Decimal | None]    # cpu, memory, pods


def _amount(value: Any) -> Decimal | None:
    n = nano_units(value) if value is not None else None
    return amount(n) if n is not None else None


def node_facts(obj: Mapping[str, Any], count_taints: Iterable[str]) -> NodeFacts:
    meta, status = obj.get("metadata") or {}, obj.get("status") or {}
    view = reduce_node(obj)
    labels = meta.get("labels") or {}
    roles = tuple(sorted({ROLES[k[len(ROLE_PREFIX):]] for k in labels
                          if k.startswith(ROLE_PREFIX) and k[len(ROLE_PREFIX):] in ROLES}))
    conditions = {c.get("type"): c.get("status") for c in status.get("conditions") or [] if isinstance(c, Mapping)}
    cap, alloc = status.get("capacity") or {}, status.get("allocatable") or {}
    return NodeFacts(str(meta.get("name") or ""), view.zone, roles, counts(view, tuple(count_taints)), view.ready,
                     conditions.get("MemoryPressure") == "True", conditions.get("DiskPressure") == "True",
                     {r: _amount(cap.get(r)) for r in ("cpu", "memory")},
                     {r: _amount(alloc.get(r)) for r in ("cpu", "memory", "pods")})


def list_nodes(st: ClusterState, count_taints: Iterable[str]) -> list[NodeFacts]:
    """The cluster's nodes from its API, page by page. ClusterUnreachable, KubeError or BadResponse when they cannot be read."""
    client = st.client                   # once: the registry clears it when the cluster drops (#402)
    if client is None:
        raise ClusterUnreachable(f"{st.cluster_id} is {st.status}: no client")
    out: list[NodeFacts] = []
    cont: str | None = None
    while True:
        body = client.list("Node", limit=NODE_PAGE, continue_=cont)
        out.extend(node_facts(n, count_taints) for n in list_items(body, "/api/v1/nodes", 200))
        cont = (body.get("metadata") or {}).get("continue")
        if not cont:
            return out


# --------------------------------------------------------------------------- the measures

@dataclass
class Measured:
    """The per-node answers of one snapshot: measure -> node -> value. `failed` names why they cannot be trusted."""
    values: dict[str, dict[str, float]] = field(default_factory=dict)
    failed: str | None = None


def measure(metrics: Any, cluster_id: str, interval_seconds: int, at: datetime) -> Measured:
    """Every query at the instant `at`; any failure, warning or timeout fails the whole set (docs/02: "A failed or warned
    query marks the row incomplete")."""
    try:
        answers = PromUsage._run(metrics, cluster_id, queries(interval_seconds), at, SNAPSHOT_TIMEOUT_SECONDS)
    except MetricsUnavailable as exc:
        return Measured(failed=f"Thanos did not answer: {exc}"[:300])
    out: dict[str, dict[str, float]] = {}
    for name, series in answers.items():
        for s in series:
            v = sample(s)
            if v is None:
                continue
            m = s.get("metric") or {}
            key = f"{m['resource']}.{name}" if "resource" in m else name
            node = str(m.get("node") or "")
            out.setdefault(key, {})[node] = out.get(key, {}).get(node, 0.0) + v
    return Measured(out)


# --------------------------------------------------------------------------- the rows

def _sum(values: Iterable[Decimal | None]) -> Decimal | None:
    """The sum, or None when any part is unknown: never a partial sum shown as the whole."""
    total = Decimal(0)
    for v in values:
        if v is None:
            return None
        total += v
    return total


def _cpu(v: Decimal | float | None) -> float | None:
    return None if v is None else round(float(v), 3)


def _bytes(v: Decimal | float | None) -> int | None:
    return None if v is None else int(round(float(v)))


def _measured(measured: Measured | None, key: str, names: set[str]) -> float | None:
    """A measure summed over the scope's nodes. A node that a successful query does not return contributes 0 (no pod there
    requests, runs or uses anything); a failed or unconfigured source gives None."""
    if measured is None or measured.failed is not None:
        return None
    by_node = measured.values.get(key, {})
    return sum(v for n, v in by_node.items() if n in names)


def _scope_row(nodes: list[NodeFacts], measured: Measured | None, names: set[str],
               committed: Mapping[str, Decimal] | None) -> dict[str, Any]:
    counted = [n for n in nodes if n.counted]
    out: dict[str, Any] = {}
    for res, fmt in (("cpu", _cpu), ("memory", _bytes)):
        out[res] = {"capacity": fmt(_sum(n.capacity[res] for n in nodes)),
                    "allocatable": fmt(_sum(n.allocatable[res] for n in counted)),
                    **{k: fmt(_measured(measured, f"{res}.{k}", names)) for k in ("requested", "limits", "usedAvg", "usedPeak")},
                    "nodeUsedAvg": None,
                    "quotaCommitted": fmt(committed[res]) if committed is not None else None}
    pods = _sum(n.allocatable["pods"] for n in counted)
    running = _measured(measured, "running", names)
    out["pods"] = {"allocatable": int(pods) if pods is not None else None, "running": int(running) if running is not None else None}
    out["nodes"] = {"total": len(nodes), "schedulable": len(counted), "notReady": sum(not n.ready for n in nodes),
                    "memoryPressure": sum(n.memory_pressure for n in nodes), "diskPressure": sum(n.disk_pressure for n in nodes)}
    return out


def mismatch(nodes: list[NodeFacts], measured: Measured | None) -> str | None:
    """docs/02: "if Thanos allocatable and the API node sum differ by more than 5%, the row is marked incomplete
    (data-mismatch). This catches a scrape gap or a node that just joined." Compared over every node of the cluster."""
    if measured is None or measured.failed is not None:
        return None
    for res, unit in (("cpu", "cores"), ("memory", "bytes")):
        api = _sum(n.allocatable[res] for n in nodes)
        thanos = sum(measured.values.get(f"{res}.allocatable", {}).values())
        if api is None or api <= 0:
            continue
        gap = abs(Decimal(str(thanos)) - api) / api
        if gap > MISMATCH:
            return (f"data-mismatch: Thanos allocatable {res} {float(thanos):g} {unit} and the API's {float(api):g} differ by "
                    f"{float(gap):.1%}, over 5%")
    return None


def build_rows(cluster_id: str, at: datetime, interval_seconds: int, nodes: list[NodeFacts], measured: Measured | None,
               committed: Mapping[str, Decimal] | None, *, nodes_failed: str | None = None) -> list[dict[str, Any]]:
    """The rows of one snapshot: the cluster, each zone, each role. `measured` None: no metrics source is configured."""
    source = "api" if measured is None else "thanos"
    detail = nodes_failed or (measured.failed if measured is not None else None) or mismatch(nodes, measured)
    base = {"cluster_id": cluster_id, "taken_at": at, "interval_seconds": interval_seconds, "source": source, "storage": None,
            "complete": detail is None, "detail": detail}
    if nodes_failed:
        empty = {"capacity": None, "allocatable": None, "requested": None, "limits": None, "usedAvg": None, "usedPeak": None,
                 "nodeUsedAvg": None}
        return [{**base, "scope": "cluster", "cpu": dict(empty), "memory": dict(empty),
                 "pods": {"allocatable": None, "running": None},
                 "nodes": {"total": None, "schedulable": None, "notReady": None, "memoryPressure": None, "diskPressure": None}}]
    # The cluster row also counts the Pending pods that no node has yet (node="").
    rows = [{**base, "scope": "cluster", **_scope_row(nodes, measured, {n.name for n in nodes} | {""}, committed)}]
    for zone in sorted({n.zone for n in nodes if n.zone}):
        members = [n for n in nodes if n.zone == zone]
        rows.append({**base, "scope": f"zone:{zone}", **_scope_row(members, measured, {n.name for n in members}, None)})
    for role in sorted({r for n in nodes for r in n.roles}):
        members = [n for n in nodes if role in n.roles]
        rows.append({**base, "scope": f"role:{role}", **_scope_row(members, measured, {n.name for n in members}, None)})
    return rows


def take(st: ClusterState, metrics: Any, interval_seconds: int, count_taints: Iterable[str], at: datetime,
         committed: Mapping[str, Decimal] | None) -> list[dict[str, Any]]:
    """One cluster's snapshot at `at`, the end of its interval. Never raises for the cluster: a failure is an incomplete row."""
    try:
        nodes = list_nodes(st, count_taints)
    except (ClusterUnreachable, KubeError, BadResponse) as exc:
        # KubeClient redacts its token from each of these before it is raised (#420).
        return build_rows(st.cluster_id, at, interval_seconds, [], None, None,
                          nodes_failed=f"the nodes could not be listed: {str(exc)[:200]}")
    measured = measure(metrics, st.cluster_id, interval_seconds, at) if metrics is not None else None
    return build_rows(st.cluster_id, at, interval_seconds, nodes, measured, committed)


# --------------------------------------------------------------------------- the stored rows

@dataclass(frozen=True)
class Latest:
    """What placement and the Capacity tab read of one cluster's snapshots."""
    taken_at: datetime | None            # the newest snapshot, complete or not
    complete_at: datetime | None         # the newest complete one
    detail: str | None                   # why the newest one is incomplete
    interval_seconds: int | None
    source: str | None
    rows: dict[str, CapacitySnapshotRow]  # the newest complete snapshot's rows, by scope


class SnapshotRepo:
    def __init__(self, session: Session):
        self.s = session

    def put(self, rows: list[dict[str, Any]]) -> None:
        """Each row, replacing one of the same cluster, instant and scope: a run asked for within an interval (:run) writes
        the interval again instead of failing."""
        if not rows:
            return
        stmt = insert(CapacitySnapshotRow).values(rows)
        cols = {c: stmt.excluded[c] for c in ("interval_seconds", "source", "cpu", "memory", "pods", "storage", "nodes",
                                              "complete", "detail")}
        self.s.execute(stmt.on_conflict_do_update(index_elements=["cluster_id", "taken_at", "scope"], set_=cols))
        # Rows of scopes that this run no longer has (a zone emptied) are not left beside the new ones.
        self.s.execute(delete(CapacitySnapshotRow).where(
            CapacitySnapshotRow.cluster_id == rows[0]["cluster_id"], CapacitySnapshotRow.taken_at == rows[0]["taken_at"],
            CapacitySnapshotRow.scope.not_in([r["scope"] for r in rows])))

    def latest(self, cluster_ids: Iterable[str]) -> dict[str, Latest]:
        ids = sorted(set(cluster_ids))
        if not ids:
            return {}
        newest = {cid: (t, ok, d, iv, src) for cid, t, ok, d, iv, src in self.s.execute(
            select(CapacitySnapshotRow.cluster_id, CapacitySnapshotRow.taken_at, CapacitySnapshotRow.complete,
                   CapacitySnapshotRow.detail, CapacitySnapshotRow.interval_seconds, CapacitySnapshotRow.source)
            .where(CapacitySnapshotRow.cluster_id.in_(ids), CapacitySnapshotRow.scope == "cluster")
            .distinct(CapacitySnapshotRow.cluster_id)
            .order_by(CapacitySnapshotRow.cluster_id, CapacitySnapshotRow.taken_at.desc()))}
        complete = dict(self.s.execute(
            select(CapacitySnapshotRow.cluster_id, func.max(CapacitySnapshotRow.taken_at))
            .where(CapacitySnapshotRow.cluster_id.in_(ids), CapacitySnapshotRow.scope == "cluster",
                   CapacitySnapshotRow.complete.is_(True))
            .group_by(CapacitySnapshotRow.cluster_id)).all())
        rows: dict[str, dict[str, CapacitySnapshotRow]] = {}
        if complete:
            newest_complete = or_(*(and_(CapacitySnapshotRow.cluster_id == cid, CapacitySnapshotRow.taken_at == t)
                                    for cid, t in complete.items()))
            for r in self.s.scalars(select(CapacitySnapshotRow).where(newest_complete)):
                rows.setdefault(r.cluster_id, {})[r.scope] = r
        out = {}
        for cid in ids:
            t, _, detail, iv, src = newest.get(cid, (None, None, None, None, None))
            out[cid] = Latest(t, complete.get(cid), detail, iv, src, rows.get(cid, {}))
        return out

    def usage_p95(self, cluster_ids: Iterable[str], now: datetime) -> dict[str, dict[str, float]]:
        """Per cluster and resource, the 95th percentile over the last 14 days of the cluster row's average use over its
        allocatable, from complete rows that measured it. A cluster or resource with no such row is left out."""
        ids = sorted(set(cluster_ids))
        if not ids:
            return {}
        out: dict[str, dict[str, float]] = {}
        for res in ("cpu", "memory"):
            col = getattr(CapacitySnapshotRow, res)
            ratio = col["usedAvg"].as_float() / func.nullif(col["allocatable"].as_float(), 0)
            q = (select(CapacitySnapshotRow.cluster_id, func.percentile_cont(0.95).within_group(ratio))
                 .where(CapacitySnapshotRow.cluster_id.in_(ids), CapacitySnapshotRow.scope == "cluster",
                        CapacitySnapshotRow.complete.is_(True), CapacitySnapshotRow.taken_at > now - timedelta(days=USAGE_WINDOW_DAYS),
                        and_(col["usedAvg"].as_float().is_not(None), col["allocatable"].as_float() > 0))
                 .group_by(CapacitySnapshotRow.cluster_id))
            for cid, p95 in self.s.execute(q):
                if p95 is not None:
                    out.setdefault(cid, {})[res] = round(float(p95), 4)
        return out

    def history(self, cluster_id: str, scope: str, since: datetime, until: datetime) -> list[CapacitySnapshotRow]:
        return list(self.s.scalars(select(CapacitySnapshotRow).where(
            CapacitySnapshotRow.cluster_id == cluster_id, CapacitySnapshotRow.scope == scope,
            CapacitySnapshotRow.taken_at >= since, CapacitySnapshotRow.taken_at <= until)
            .order_by(CapacitySnapshotRow.taken_at)))

    def prune(self, now: datetime) -> int:
        return self.s.execute(delete(CapacitySnapshotRow).where(
            CapacitySnapshotRow.taken_at < now - timedelta(days=RETENTION_DAYS))).rowcount
