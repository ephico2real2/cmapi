"""The nodes of one cluster, watched and kept small, for the Capacity tab (#302; docs/01: "Allocatable comes from the live node
list in the watch cache").

A WatchCache of its own on `Node`, beside the cluster's main cache and its report cache:
- its own, because `project` applies to every kind of one cache, and the main cache keeps raw Namespaces and ResourceQuotas
  that other readers need; and because `wait_ready` waits on every kind, so a reader without the `nodes` grant would hold the
  start to its timeout;
- projected (`reduce_node`), page by page in chunks of CHUNK: a Node's `status.images` alone can be hundreds of KB, and only
  what capacity reads is kept, never the raw object;
- totals kept by the cache's `admit` and `dropped` hooks, so a read costs O(1) in the number of nodes.

A node counts toward allocatable when it is Ready, not cordoned (`spec.unschedulable`), and has no NoSchedule or NoExecute
taint other than those whose key capacity.yaml's `countTaints` names (docs/02: "schedulable workers without NoSchedule
taints"). "'Allocatable' on a Kubernetes node is defined as the amount of compute resources that are available for pods. The
scheduler does not over-subscribe 'Allocatable'." (kubernetes.io/docs/tasks/administer-cluster/reserve-compute-resources).

Event volume: the kubelet updates a Node's `.status` every 5 minutes when nothing changes, and its heartbeat goes to a Lease
(kubernetes.io/docs/reference/node/node-status), so the watch sees a few events per node per 5 minutes. A 403 on the list is
the node part's `forbidden` state: the cluster's commitment against a simulated size is still known.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from cmapi.core.capacity_ledger import amount, nano_units
from cmapi.core.clients.kube import ClusterUnreachable, KubeClient, KubeError, WatchCache

KIND = "Node"
CHUNK = 500
ZONE_LABEL = "topology.kubernetes.io/zone"
EXCLUDING_EFFECTS = ("NoSchedule", "NoExecute")


@dataclass(frozen=True, slots=True)
class NodeView:
    """What is kept of one Node: allocatable in nano-units, its zone, and why it might not count."""
    cpu: int | None                     # nano-cores; None when status.allocatable has no parseable cpu
    memory: int | None                  # nano-bytes
    zone: str | None
    ready: bool
    unschedulable: bool
    taints: tuple[str, ...]             # the keys of its NoSchedule and NoExecute taints


def reduce_node(obj: Mapping[str, Any]) -> NodeView:
    """A Node reduced to what capacity reads. Pure: the chunked list calls it on each page as the page arrives."""
    meta, spec, status = obj.get("metadata") or {}, obj.get("spec") or {}, obj.get("status") or {}
    alloc = status.get("allocatable") or {}
    ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions") or []
                if isinstance(c, Mapping))
    taints = tuple(sorted({str(t.get("key") or "") for t in spec.get("taints") or []
                           if isinstance(t, Mapping) and t.get("effect") in EXCLUDING_EFFECTS}))
    zone = (meta.get("labels") or {}).get(ZONE_LABEL)
    cpu = nano_units(alloc["cpu"]) if "cpu" in alloc else None
    memory = nano_units(alloc["memory"]) if "memory" in alloc else None
    return NodeView(cpu, memory, str(zone) if zone else None, ready, bool(spec.get("unschedulable")), taints)


@dataclass
class _Totals:
    total: int = 0
    counted: int = 0
    not_ready: int = 0
    cordoned: int = 0
    tainted: int = 0
    cpu: int = 0                        # nano-cores of the counted nodes
    memory: int = 0
    zones: Counter = field(default_factory=Counter)


@dataclass(frozen=True)
class NodeSnapshot:
    """What one read of the node cache sees."""
    state: str                          # ok, loading, forbidden or stale
    detail: str | None
    as_of: datetime | None              # the last good read of the nodes
    total: int | None = None
    counted: int | None = None
    not_ready: int | None = None
    cordoned: int | None = None
    tainted: int | None = None
    cpu: Any = None                     # Decimal cores of the counted nodes, or None
    memory: Any = None                  # Decimal bytes
    zones: tuple[str, ...] | None = None

    @property
    def known(self) -> bool:
        """Whether the figures are there: listed, and not refused since (a stale read keeps its last figures)."""
        return self.state in ("ok", "stale")


class NodeCache:
    """The nodes of one cluster: a projected, chunked watch and the totals of the nodes that count."""

    def __init__(self, client: KubeClient, count_taints: Iterable[str] = (), *, clock: Callable[[], float] = time.time,
                 chunk: int | None = CHUNK):
        self.client, self.count_taints, self.clock = client, frozenset(count_taints), clock
        self._lock = threading.Lock()
        self._views: dict[str, NodeView] = {}
        self._t = _Totals()
        self.watch = WatchCache(client, (KIND,), clock, project=lambda kind, obj: reduce_node(obj), admit=self._admit,
                                dropped=self._dropped, chunk=chunk)

    # ---- the rule, and the totals as each node enters or leaves
    def counts(self, v: NodeView) -> bool:
        """Whether a node's allocatable is capacity: Ready, not cordoned, no excluding taint outside countTaints, and an
        allocatable the kubelet has reported (a node without one has not finished registering)."""
        return (v.ready and not v.unschedulable and v.cpu is not None and v.memory is not None
                and all(t in self.count_taints for t in v.taints))

    def _apply(self, v: NodeView, sign: int) -> None:
        t = self._t
        t.total += sign
        t.not_ready += sign * (not v.ready)
        t.cordoned += sign * v.unschedulable
        t.tainted += sign * any(k not in self.count_taints for k in v.taints)
        if self.counts(v):
            t.counted += sign
            t.cpu += sign * (v.cpu or 0)
            t.memory += sign * (v.memory or 0)
            if v.zone:
                t.zones[v.zone] += sign
                if t.zones[v.zone] <= 0:
                    del t.zones[v.zone]

    def _admit(self, kind: str, key: str, view: NodeView) -> NodeView:
        with self._lock:
            old = self._views.get(key)
            if old is not None:
                self._apply(old, -1)
            self._views[key] = view
            self._apply(view, 1)
        return view

    def _dropped(self, kind: str, key: str) -> None:
        with self._lock:
            old = self._views.pop(key, None)
            if old is not None:
                self._apply(old, -1)

    # ---- the watch
    def start(self) -> None:
        self.watch.start()

    def stop(self) -> None:
        self.watch.stop()

    def sync(self) -> None:
        """One list in the caller's thread, recording a failure as the loop does: what the tests and a first read use."""
        try:
            self.watch._list(KIND)
        except (ClusterUnreachable, KubeError, ValueError) as exc:
            with self.watch._lock:
                self.watch.state[KIND].error = str(exc)[:200]
                self.watch.state[KIND].error_status = exc.status if isinstance(exc, KubeError) else None

    def wait_ready(self, timeout: float = 5.0) -> bool:
        """Until the first list ended or failed: either way the snapshot has its answer."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = self.watch.state[KIND]
            if st.last_good is not None or st.error is not None:
                return True
            time.sleep(0.02)
        return False

    # ---- reads
    def snapshot(self) -> NodeSnapshot:
        status, error = self.watch.kind_error(KIND)
        stale, last = self.watch.kind_stale(KIND)
        as_of = datetime.fromtimestamp(last, tz=timezone.utc) if last is not None else None
        if status in (401, 403):
            # As for the quotas (#393): a refused read cannot relist, so what was held before is not current.
            return NodeSnapshot("forbidden", f"cmapi-reader may not list nodes ({status}): its ClusterRole needs get, list and "
                                             "watch on nodes", as_of)
        if last is None:
            return NodeSnapshot("loading", "the nodes are being listed" + (f": {error}" if error else ""), None)
        with self._lock:
            t = self._t
            figures = dict(total=t.total, counted=t.counted, not_ready=t.not_ready, cordoned=t.cordoned, tainted=t.tainted,
                           cpu=amount(t.cpu), memory=amount(t.memory), zones=tuple(sorted(t.zones)))
        if stale:
            return NodeSnapshot("stale", f"no good read of the nodes for over {WatchCache.RELIST_SECONDS // 60} minutes: the "
                                         "figures are the last ones read", as_of, **figures)
        return NodeSnapshot("ok", None, as_of, **figures)
