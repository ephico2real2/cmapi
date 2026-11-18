"""The quota that cmapi's ResourceQuotas commit on one cluster, kept as the watch admits each quota (#302, design B, D2).

The watch cache of a cluster calls `admit` for each ResourceQuota that enters it (a list, an ADDED or MODIFIED event) and
`dropped` for each one that leaves (a DELETED event, or a relist that no longer holds it). The ledger keeps what each managed
quota bounds and the running totals, so the capacity check of a plan and GET /api/v1/capacity read the totals in constant time
instead of parsing every quota of the cluster on each call: `qty()` took 337 ms per 10,000 quotas (design B, M2). `admit`
returns the quota unchanged, so the Quotas plugin still reads the raw objects.

The rules (docs/16, "For each resource, the namespace-wide hard value is the smallest quantity among unscoped quotas"):
- Only quotas labelled `cmapi.net/managed=true` count, as the capacity check always did.
- A quota's `cpu` and `memory` are the same resources as `requests.cpu` and `requests.memory`; one that sets both lets its
  namespace commit the smaller (#393).
- Kubernetes enforces every quota of a namespace, so the tightest unscoped quota binds: a namespace commits the smallest
  bound among its unscoped quotas, never their sum. Its use (`status.used`) is the binding quota's.
- A scoped quota (`spec.scopes` or `spec.scopeSelector`) bounds only the pods its scope selects, not the namespace: it is left
  out of the totals and counted in `scoped_quotas`.

`recount` computes the same totals from the quotas in one pass; the ledger's property test holds the incremental totals to it.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from decimal import Context, Decimal
from typing import Any, Iterable, Mapping

from cmapi.core.tiers import qty

RESOURCES = ("cpu", "memory")
# A quota's `cpu` and `memory` are the same resources as `requests.cpu` and `requests.memory`
# (https://kubernetes.io/docs/concepts/policy/resource-quotas/): the pod evaluator charges a pod's requests to both names,
# and quota admission refuses a pod that exceeds either hard value (kubernetes v1.34.0, pkg/quota/v1/evaluator/core/pods.go,
# podComputeUsageHelper; staging/src/k8s.io/apiserver/pkg/quota/v1/resources.go, LessThanOrEqual). So a quota with both
# lets the namespace commit the smaller of the two, and that is what is counted, once.
REQUEST_KEYS = {"cpu": ("requests.cpu", "cpu"), "memory": ("requests.memory", "memory")}
MANAGED = "cmapi.net/managed"


NANO = 9                                    # qty() is exact to 1e-9 of the unit, so nano-units are exact integers


def nano_units(value: Any) -> int | None:
    """A quantity in nano-units (nano-cores, nano-bytes), or None for a value that is not one (the API server validates `hard`,
    so only a malformed fake has one). Integers keep every sum exact: a Decimal sum is rounded past 28 digits."""
    try:
        return int(qty(value).scaleb(NANO))
    except (TypeError, ValueError):
        return None


def amount(nano: int) -> Decimal:
    """Nano-units back to the unit (cores, bytes), exactly: the context holds every digit of the integer."""
    return Decimal(nano).scaleb(-NANO, context=Context(prec=max(28, len(str(abs(nano))))))


@dataclass(frozen=True, slots=True)
class Bound:
    """What one quota bounds of one resource: the smallest hard value of its names, and the use it reports for that name, in
    nano-units."""
    hard: int
    used: int | None                         # None: the quota's status has no `used` for the name yet


@dataclass(frozen=True, slots=True)
class QuotaFacts:
    """What the ledger keeps of one managed quota."""
    namespace: str
    scoped: bool
    bounds: tuple[Bound | None, Bound | None]     # cpu, memory; None when the quota bounds neither name of the resource


def is_scoped(spec: Mapping[str, Any]) -> bool:
    """Whether a quota bounds only the pods of a scope: `scopes`, or `scopeSelector` with an expression (docs/16: "Empty scopes
    and no selector expressions mean unscoped")."""
    return bool(spec.get("scopes")) or bool((spec.get("scopeSelector") or {}).get("matchExpressions"))


def _bound(hard: Mapping[str, Any], used: Mapping[str, Any], resource: str) -> Bound | None:
    named = [(b, k) for k in REQUEST_KEYS[resource] if k in hard and (b := nano_units(hard[k])) is not None]
    if not named:
        return None
    value, key = min(named, key=lambda bk: bk[0])
    # The binding name's use; the other name reports the same sum of pod requests, so it stands in while the first is absent.
    for k in (key, *REQUEST_KEYS[resource]):
        if k in used and (u := nano_units(used[k])) is not None:
            return Bound(value, u)
    return Bound(value, None)


def quota_facts(obj: Mapping[str, Any]) -> QuotaFacts | None:
    """The facts of a quota that cmapi manages, or None for any other quota."""
    meta = obj.get("metadata") or {}
    if (meta.get("labels") or {}).get(MANAGED) != "true":
        return None
    spec = obj.get("spec") or {}
    hard, used = spec.get("hard") or {}, (obj.get("status") or {}).get("used") or {}
    return QuotaFacts(str(meta.get("namespace") or ""), is_scoped(spec), tuple(_bound(hard, used, r) for r in RESOURCES))


@dataclass(frozen=True, slots=True)
class NamespaceFigures:
    """One namespace's share of the totals: per resource, the binding (smallest) unscoped bound."""
    bounds: tuple[Bound | None, Bound | None]


def namespace_figures(quotas: Iterable[QuotaFacts]) -> NamespaceFigures | None:
    """The namespace's committed quota and its use, or None when it has no unscoped managed quota (it then commits nothing)."""
    unscoped = [q for q in quotas if not q.scoped]
    if not unscoped:
        return None
    out: list[Bound | None] = []
    for i in range(len(RESOURCES)):
        bounds = [q.bounds[i] for q in unscoped if q.bounds[i] is not None]
        # The smallest hard binds. Among equal ones: one that reports its use, so a quota whose status lags does not hide it,
        # then the larger use. Every unscoped quota charges the same pods, so their uses differ only while a status lags; the
        # larger is the conservative one, and the choice never depends on the order the quotas arrived in.
        out.append(min(bounds, key=lambda b: (b.hard, b.used is None, -(b.used or 0)), default=None))
    return NamespaceFigures((out[0], out[1]))


@dataclass(frozen=True)
class LedgerTotals:
    """The totals of a cluster at one moment, in cores and bytes, exact."""
    committed: dict[str, Decimal]                 # resource -> the sum of each namespace's binding bound
    used: dict[str, Decimal]                      # resource -> the sum of the binding quotas' `status.used`, where reported
    used_missing: dict[str, int]                  # resource -> namespaces whose binding quota reports no use: `used` is partial
    namespaces: int                               # namespaces with an unscoped managed quota
    scoped_quotas: int                            # managed quotas left out because they are scoped

    def quota_used(self, resource: str) -> Decimal | None:
        """The use within the managed quotas, or None when any binding quota has not reported its use: never a partial sum."""
        return None if self.used_missing[resource] else self.used[resource]


def totals_of(facts: Iterable[QuotaFacts]) -> LedgerTotals:
    """The totals of a set of quota facts in one pass: the definition that the ledger keeps incrementally."""
    by_ns: dict[str, list[QuotaFacts]] = {}
    scoped = 0
    for f in facts:
        by_ns.setdefault(f.namespace, []).append(f)
        scoped += f.scoped
    acc = _Acc()
    for quotas in by_ns.values():
        acc.add(namespace_figures(quotas), 1)
    return acc.totals(scoped)


def recount(quotas: Iterable[Mapping[str, Any]]) -> LedgerTotals:
    """The totals from the raw quotas of a cluster, recounted from scratch."""
    return totals_of(f for q in quotas if (f := quota_facts(q)) is not None)


@dataclass
class _Acc:
    committed: list[int] = field(default_factory=lambda: [0, 0])              # nano-units
    used: list[int] = field(default_factory=lambda: [0, 0])
    missing: list[int] = field(default_factory=lambda: [0, 0])
    namespaces: int = 0

    def add(self, figures: NamespaceFigures | None, sign: int) -> None:
        if figures is None:
            return
        self.namespaces += sign
        for i, b in enumerate(figures.bounds):
            if b is None:
                continue
            self.committed[i] += sign * b.hard
            if b.used is None:
                self.missing[i] += sign
            else:
                self.used[i] += sign * b.used

    def totals(self, scoped: int) -> LedgerTotals:
        return LedgerTotals({r: amount(n) for r, n in zip(RESOURCES, self.committed)},
                            {r: amount(n) for r, n in zip(RESOURCES, self.used)},
                            dict(zip(RESOURCES, self.missing)), self.namespaces, scoped)


class CapacityLedger:
    """The running totals of one cluster's managed quotas, fed by its WatchCache's `admit` and `dropped` hooks.

    Both hooks run on the watch thread under the cache's lock; the ledger has its own lock, so a read never waits on a list.
    Each change recounts only the namespace of the quota (a handful of quotas), so an event costs O(1) in the cluster's size."""

    KIND = "ResourceQuota"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._quotas: dict[str, QuotaFacts] = {}                  # cache key -> facts, managed quotas only
        self._keys: dict[str, set[str]] = {}                      # namespace -> its managed quotas' keys
        self._figures: dict[str, NamespaceFigures] = {}           # namespace -> its share of the totals
        self._acc = _Acc()
        self._scoped = 0

    # ---- the cache's hooks
    def admit(self, kind: str, key: str, value: Any) -> Any:
        if kind == self.KIND:
            self._put(key, quota_facts(value))
        return value

    def dropped(self, kind: str, key: str) -> None:
        if kind == self.KIND:
            self._put(key, None)

    def _put(self, key: str, facts: QuotaFacts | None) -> None:
        with self._lock:
            old = self._quotas.pop(key, None)
            touched: set[str] = set()
            if old is not None:
                self._keys[old.namespace].discard(key)
                self._scoped -= old.scoped
                touched.add(old.namespace)
            if facts is not None:
                self._quotas[key] = facts
                self._keys.setdefault(facts.namespace, set()).add(key)
                self._scoped += facts.scoped
                touched.add(facts.namespace)
            for ns in touched:
                self._acc.add(self._figures.pop(ns, None), -1)
                keys = self._keys.get(ns)
                if not keys:
                    self._keys.pop(ns, None)
                    continue
                figures = namespace_figures(self._quotas[k] for k in keys)
                if figures is not None:
                    self._figures[ns] = figures
                    self._acc.add(figures, 1)

    # ---- reads
    def totals(self) -> LedgerTotals:
        with self._lock:
            return self._acc.totals(self._scoped)
