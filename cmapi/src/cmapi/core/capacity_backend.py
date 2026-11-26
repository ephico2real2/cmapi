"""CapacityBackend adapters (core/ports.py).

SimulatedCapacity is the phase 1 and 2 backend: the cluster's size comes from
clusters.yaml (simulatedCapacity) and the commitment from the cluster's quota ledger
(core/capacity_ledger.py), which the watch cache keeps as each ResourceQuota arrives: per
namespace the smallest unscoped managed quota, scoped quotas left out (#302). The arithmetic is
core/capacity.py's, the one that GET /api/v1/capacity shows. It answers fresh=True only while that quota list is
current: when the cluster has no cache, its ResourceQuotas have not listed, or their watch
is stale, the commitment is not known and the answer is unknown, never a ratio over 0 (#393).
It is named so that no reader mistakes it for measured capacity. Phase 3 replaces the size with
cmapi-capacity's snapshots from Thanos (capacity/); the owner kept simulatedCapacity as the size until then (2026-11-18,
docs/reviews/2026-11-18-issue-302-capacity/design-capacity-arbitration.md).

The check also counts the capacity that open requests hold (#62; docs/01, "Quota headroom = allocatable × overcommit −
committed − reserved"): each request with an increase holds it in capacity_reservations from its submit until it leaves the
lifecycle's holding states (RequestRepo.move), and a hold stops counting once the ledger shows the namespace's new quota, so
nothing is counted twice. The hold is taken in the transaction that checks it, under the cluster's lock (`reserve`), so two
requests cannot both take the last headroom.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session

from cmapi.core.capacity import CapacitySettings, limit_of
from cmapi.core.capacity_ledger import CapacityLedger, LedgerTotals
from cmapi.core.clients.kube import WatchCache
from cmapi.core.db.models import CapacityReservationRow
from cmapi.core.db.repo import ReservationRepo, utcnow
from cmapi.core.errors import Problem
from cmapi.core.ports import CapacityResult
from cmapi.core.registry import ClusterRegistry, ClusterState
from cmapi.core.tiers import qty


@dataclass(frozen=True)
class QuotaRead:
    """What can be said of one cluster's committed quota: the plan's check and GET /api/v1/capacity read it here, so they agree
    on what is known."""
    state: str                                  # ok, loading, forbidden, stale or unreachable
    detail: str | None
    last_good: float | None                     # the ResourceQuota kind's last good read
    totals: LedgerTotals | None                 # with ok, and the last ones read with stale; None otherwise
    ledger: CapacityLedger | None = None        # with ok: what each namespace commits, to tell an observed hold


def read_quotas(registry: ClusterRegistry, cluster_id: str) -> QuotaRead:
    try:
        cache, ledger = registry.quota_watch(cluster_id)
    except Problem as exc:
        return QuotaRead("unreachable", f"no watch cache for this cluster: {exc.detail}", None, None)
    return _read_cached_quotas(cache, ledger)


def read_snapshot_quotas(st: ClusterState) -> QuotaRead:
    cache, ledger = st.cache, st.ledger
    if cache is None:
        detail = f"{st.cluster_id} is {st.status}: {'; '.join(st.findings)}"
        return QuotaRead("unreachable", f"no watch cache for this cluster: {detail}", None, None)
    return _read_cached_quotas(cache, ledger)


def _read_cached_quotas(cache: WatchCache, ledger: CapacityLedger | None) -> QuotaRead:
    stale, last = cache.kind_stale("ResourceQuota")
    status, error = cache.kind_error("ResourceQuota")
    if status in (401, 403):
        # The API server refuses the reader (a revoked grant, a rotated token): no relist can succeed, so the items held from
        # before are not current, however recent their last good read. Transient errors stay bounded by the relist window
        # instead, so a dropped watch does not flap the answer.
        return QuotaRead("forbidden", f"the API server refuses the reader's ResourceQuota reads ({status}): {error}", last, None)
    if last is None:
        return QuotaRead("loading", "the cluster's ResourceQuotas have not listed yet" + (f": {error}" if error else ""), None,
                         None)
    if ledger is None:
        return QuotaRead("loading", "the cluster's quota ledger has not started", last, None)
    if stale:
        return QuotaRead("stale", f"the ResourceQuota watch is stale: no good read for over {cache.RELIST_SECONDS}s", last,
                         ledger.totals())
    return QuotaRead("ok", None, last, ledger.totals(), ledger)


@dataclass(frozen=True)
class CapacityHold:
    """What a request holds on its cluster: the increase its plan was checked for (cores, bytes, pods) and the namespace's
    binding quota after it, which tells when the cluster's ledger shows the change (`observed`)."""
    namespace: str
    cpu: Decimal
    memory: Decimal
    pods: int
    target_cpu: Decimal | None
    target_memory: Decimal | None

    @staticmethod
    def of(namespace: str, deltas: Mapping[str, Decimal], target: Mapping[str, Decimal | None]) -> CapacityHold | None:
        """The hold of a plan, or None when it raises neither CPU nor memory: a decrease, a delete or a label change holds
        nothing. `deltas` are the ones the check was asked about, `target` the binding hard values after the change."""
        cpu, memory = max(deltas.get("cpu", Decimal(0)), Decimal(0)), max(deltas.get("memory", Decimal(0)), Decimal(0))
        if cpu <= 0 and memory <= 0:
            return None
        return CapacityHold(namespace, cpu, memory, max(int(deltas.get("pods", 0)), 0), target.get("cpu"), target.get("memory"))


def _ceil(value: Decimal, places: int) -> Decimal:
    """Rounded up to the column's scale, so a stored hold is never smaller than the increase it was checked for."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_CEILING)


def _floor(value: Decimal, places: int) -> Decimal:
    """Rounded down to the column's scale, so the exact quota, once live, reaches a stored target (1.1Gi is 1181116006.4
    bytes: rounded up, the ledger's exact figure would never reach it, and the hold would be counted beside the quota)."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_FLOOR)


def held(rows: Iterable[CapacityReservationRow], live: Mapping[str, Mapping[str, Decimal]]) -> dict[str, Decimal]:
    """What the holds add to the cluster's commitment, per resource. `live`: what each held namespace commits, read in the
    same ledger snapshot as the totals (CapacityLedger.snapshot). A hold whose namespace the ledger already shows at its
    target binds there now (docs/02: "Committed quota counts it from then on, so it is never counted twice"). Each reader
    decides this from its own watch, and nothing is written: another API pod or the worker, whose watch may be behind, still
    counts the hold until the lifecycle releases it (#725 review)."""
    out = {"cpu": Decimal(0), "memory": Decimal(0)}
    for r in rows:
        shown = live.get(r.namespace) if r.namespace else None
        for res, amount, target in (("cpu", Decimal(r.cpu), r.target_cpu), ("memory", Decimal(r.memory), r.target_memory)):
            if shown is not None and target is not None and shown[res] >= Decimal(target):
                continue
            out[res] += amount
    return out


class SimulatedCapacity:
    def __init__(self, registry: ClusterRegistry, settings: CapacitySettings, db: Any = None):
        # db: the cmapi database whose capacity_reservations the check counts. None only in a test that builds the backend
        # alone; such a backend counts no holds and cannot reserve.
        self.registry, self.settings, self.db = registry, settings, db

    def check(self, cluster_id: str, environment: str, cpu_delta: float, memory_delta: float, *,
              session: Session | None = None, exclude: str | None = None,
              namespace: str | None = None) -> CapacityResult:
        """Whether `cpu_delta` cores and `memory_delta` bytes more fit the cluster, after its committed quota and the active
        holds of open requests. `session`: read the holds in the caller's transaction (submit, a job that holds a row
        lock), never a second pooled session there (#695, #696). `exclude`: leave out this request's own hold.

        `namespace`: the namespace that the deltas change; a hold on it is not counted. Only the open request on that
        namespace can hold there (the Reservation states lie within the namespace lock's, core/lifecycle.py), and its hold
        and these deltas are both sized from the quota that Git holds (#710): two alternative increases of one namespace,
        never both. A submit for the namespace is refused 409 change-pending until that request ends, and its hold with it.
        Counted together, a plan of payments-dev to medium beside its open change to large weighed 40 cores where either
        outcome is 32 or 16 (#725, CI's recorded plan)."""
        st = self.registry.get(cluster_id)
        size = st.policy.simulated_capacity if st.policy else None
        if not size:
            return CapacityResult("unknown", False, None, {"reason": "no simulatedCapacity for this cluster"})
        read = read_quotas(self.registry, cluster_id)
        if read.state != "ok" or read.totals is None or read.ledger is None:
            return CapacityResult("unknown", False, None, {"reason": read.detail, "source": "simulated",
                                                           "clusterId": cluster_id})
        # The holds first, then the totals and the held namespaces in one ledger snapshot: a quota that lands meanwhile is
        # then either committed or held, never neither (#725 review).
        rows = [r for r in self._holds(cluster_id, session, exclude) if namespace is None or r.namespace != namespace]
        totals, live = read.ledger.snapshot({r.namespace for r in rows if r.namespace})
        reserved = held(rows, live)
        env = self.settings.env(environment)
        deltas = {"cpu": Decimal(str(cpu_delta)), "memory": Decimal(str(memory_delta))}
        ratios = {r: (totals.committed[r] + reserved[r] + deltas[r]) / limit_of(qty(size[r]), env.overcommit[r])
                  for r in deltas}
        worst = max(ratios, key=ratios.get)
        r = float(ratios[worst])                                   # compared as before #302, in floats
        status = "exceeded" if r > 1 else "warn" if r >= float(env.warn) else "fits"
        return CapacityResult(status, True, worst, {k: round(float(v), 3) for k, v in ratios.items()} |
                              {"reserved": {"cpu": float(reserved["cpu"]), "memory": int(reserved["memory"])},
                               "source": "simulated", "clusterId": cluster_id})

    def _holds(self, cluster_id: str, session: Session | None, exclude: str | None) -> list[CapacityReservationRow]:
        if session is not None:
            return ReservationRepo(session).active(cluster_id, exclude=exclude)
        if self.db is None:
            return []
        with self.db.session() as s:
            rows = ReservationRepo(s).active(cluster_id, exclude=exclude)
            s.expunge_all()                                        # read after the session closes
            return rows

    def place(self, environment: str, team: str, tier: str, constraints: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("placement arrives with cmapi-capacity (phase 3)")

    def reserve_check(self, session: Session, cluster_id: str, environment: str, hold: CapacityHold) -> CapacityResult:
        """The check of a hold against the cluster as it is now, under the cluster's lock in the caller's transaction, which
        then takes the hold (`reserve`) before it commits: so a concurrent submit waits, and then counts it (docs/02,
        Placement, "Reservations"). Raises 422 capacity-exceeded when it no longer fits. Returns the check, which the plan
        takes as its own: other holds may have been taken since the plan."""
        ReservationRepo(session).lock_cluster(cluster_id)
        cap = self.check(cluster_id, environment, float(hold.cpu), float(hold.memory), session=session,
                         namespace=hold.namespace)
        if cap.status == "exceeded":
            raise capacity_exceeded(cap)
        return cap

    def reserve(self, session: Session, request_id: str, cluster_id: str, hold: CapacityHold, term: timedelta) -> None:
        """Take the hold of a recorded request, after `reserve_check` in the same transaction. The hold's amounts are rounded up
        to the columns' scale (millicores, bytes), never down; its targets down, so that the live quota reaches them."""
        repo = ReservationRepo(session)
        repo.reclaim(cluster_id)
        now = utcnow()
        repo.hold(CapacityReservationRow(
            request_id=request_id, cluster_id=cluster_id, namespace=hold.namespace, cpu=_ceil(hold.cpu, 3),
            memory=int(_ceil(hold.memory, 0)), pods=hold.pods,
            target_cpu=None if hold.target_cpu is None else _floor(hold.target_cpu, 3),
            target_memory=None if hold.target_memory is None else int(_floor(hold.target_memory, 0)),
            created_at=now, expires_at=now + term))

    def confirm(self, session: Session, request_id: str, cluster_id: str, environment: str) -> CapacityResult | None:
        """The check again for a request that enters approved ("The count is met (auto or :approve) and capacity still
        fits", docs/01; "checked again when approved", docs/01, Quota changes): its own hold against the cluster as it is
        now. Raises 422 capacity-exceeded, and the caller's transaction, the approval or the :retry with it, is undone. None
        when the request holds nothing."""
        repo = ReservationRepo(session)
        own = repo.of(request_id)
        if own is None:
            return None
        repo.lock_cluster(cluster_id)
        if read_quotas(self.registry, cluster_id).ledger is None:
            return None                       # not known: a person approved, and only auto-approval waits on a known answer
        # Its own hold is active (RequestRepo.move took it again if it had lapsed): counted with every other hold, in the
        # check's one snapshot, and not counted a second time as a delta.
        cap = self.check(cluster_id, environment, 0, 0, session=session)
        if cap.status == "exceeded":
            raise capacity_exceeded(cap)
        return cap

    def release(self, session: Session, request_id: str, why: str) -> int:
        return ReservationRepo(session).release(request_id, why)


def capacity_exceeded(cap: CapacityResult) -> Problem:
    return Problem.unprocessable("capacity-exceeded", f"{cap.binding_resource} would exceed the cluster",
                                 capacity=dict(cap.detail))
