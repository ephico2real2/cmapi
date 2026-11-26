"""POST /api/v1/capacity:place, the API side (#21, #303; docs/02, "Placement"): the facts of each candidate, and the hold.

docs/01: "Placement, the capacity check inside every plan, and applying or dismissing recommendations stay in the API, because
they write requests or reservations." The facts come from the three sources of docs/02's "Data sources" table and nothing
else, so no request waits on Thanos:

| Source | Read here |
| --- | --- |
| capacity_snapshots | each cluster's newest complete snapshot (freshness, zones) and the 14-day p95 of its use (SnapshotRepo) |
| the API's watch | the committed quota (the cluster's ledger, behind the plan's own gates), the nodes' allocatable, the team's namespaces |
| the cmapi database | the active holds, in the transaction that takes the new one |

The decision is core/placement.py's. The hold: "Placement takes a reservation inside the same transaction as the capacity
check, under a per-cluster advisory lock, so concurrent requests see each other." Each ranked cluster is tried in order, each in
a transaction of its own that takes the team's lock and then the cluster's, counts the team's placements (at most three active
per environment), ranks that cluster again with the holds read under its lock, and holds it when it still passes. A cluster
that another request filled meanwhile is skipped; one transaction per cluster, so no two cluster locks are ever held at once.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from typing import Any

from prometheus_client import Counter
from sqlalchemy.orm import Session

from cmapi.capacity.snapshots import SnapshotRepo
from cmapi.core.capacity import RESOURCES
from cmapi.core.capacity_backend import held, read_snapshot_quotas
from cmapi.core.capacity_ledger import binding_hard
from cmapi.core.context import AppContext
from cmapi.core.db.models import CapacityReservationRow
from cmapi.core.db.repo import ReservationRepo, utcnow
from cmapi.core.errors import Problem
from cmapi.core.placement import MAX_ACTIVE_PLACEMENTS, Ask, Candidate, Excluded, PlacementSettings, Ranked, rank
from cmapi.core.registry import ClusterState
from cmapi.core.tiers import qty

PLACEMENTS = Counter("cmapi_placement_requests_total", "POST /capacity:place answers", ["result"])
EXCLUDED = Counter("cmapi_placement_excluded_total", "Clusters that placement excluded, by reason", ["reason"])


def ask_of(c: AppContext, body: dict[str, Any]) -> Ask:
    """The request sized from its tier, as the create renders it: the binding `requests.cpu` and `requests.memory` of the
    tier's quota (the smaller of a short and a long name, #393) and its `pods`."""
    env = body["environment"]
    hard = binding_hard(c.cfg.tiers.quota_for(env, body.get("tier") or "small", body.get("quota")))
    cons = body.get("constraints") or {}
    return Ask(env, body.get("team"), qty(hard.get("requests.cpu", "0")), qty(hard.get("requests.memory", "0")),
               int(qty(hard.get("pods", "0"))), cons.get("region"), tuple(cons.get("zones") or ()),
               dict(((cons.get("clusterSelector") or {}).get("matchLabels")) or {}))


def _team_namespaces(st: ClusterState, team: str | None) -> int:
    cache = st.cache
    if cache is None or team is None:
        return 0
    return sum(1 for ns in cache.all("Namespace")
               if ((ns.get("metadata") or {}).get("labels") or {}).get("cmapi.net/team") == team)


def _size(st: ClusterState) -> tuple[dict[str, Decimal] | None, str | None]:
    """The Capacity tab's size (plugins/capacity/router.py, cluster_view): simulatedCapacity, else the counted nodes."""
    p = st.policy
    if p and p.simulated_capacity:
        return {r: qty(p.simulated_capacity[r]) for r in RESOURCES}, "simulated"
    nodes = st.nodes
    snap = nodes.snapshot() if nodes is not None and st.status == "connected" else None
    if snap is not None and snap.known and snap.counted and snap.cpu and snap.memory:
        return {"cpu": snap.cpu, "memory": snap.memory}, "allocatable"
    return None, None


def candidate(c: AppContext, st: ClusterState, session: Session, ask: Ask, latest: Any,
              p95: dict[str, float] | None) -> Candidate:
    """What the three sources say of one cluster now. The holds are read in `session`, so under the cluster's lock when the
    caller holds it; and in one ledger snapshot with the committed quota, as the plan's check reads them (#725 review)."""
    p = st.policy
    block = dict(p.placement) if p else {}
    es = c.capacity.for_cluster(ask.environment, block)
    size, basis = _size(st)
    rows = ReservationRepo(session).active(st.cluster_id)
    committed, detail, namespaces = None, None, None
    reserved = {r: sum((Decimal(getattr(h, r)) for h in rows), Decimal(0)) for r in RESOURCES}
    if st.status == "connected":
        read = read_snapshot_quotas(st)
        if read.state == "ok" and read.ledger is not None:
            totals, live = read.ledger.snapshot({h.namespace for h in rows if h.namespace})
            committed, namespaces = dict(totals.committed), totals.namespaces
            reserved = held(rows, live)
        else:
            detail = read.detail
    zones = {scope.removeprefix("zone:"): {r: Decimal(str((getattr(row, r) or {}).get("allocatable") or 0)) for r in RESOURCES}
             for scope, row in latest.rows.items() if scope.startswith("zone:")}
    not_connected = None if st.status == "connected" else st.not_connected()[1]
    return Candidate(st.cluster_id, (p.labels or {}).get("region") if p else None, dict(p.labels) if p else {},
                     bool(p and p.writes), not_connected, bool(block.get("enabled", True)), block.get("maxNamespaces"),
                     float(block.get("weight", 1.0)), size, basis, es.overcommit, committed, detail, namespaces, reserved,
                     latest.complete_at, latest.detail, zones, p95, _team_namespaces(st, ask.team))


def candidates(c: AppContext, session: Session, ask: Ask, now: datetime) -> list[Candidate]:
    """Every cluster of the environment on this instance (docs/01: "Placement only ranks this instance's clusters")."""
    states = sorted((st for st in c.registry.snapshots() if st.environment == ask.environment), key=lambda s: s.cluster_id)
    snaps = SnapshotRepo(session)
    latest = snaps.latest(st.cluster_id for st in states)
    p95 = snaps.usage_p95((st.cluster_id for st in states), now)
    return [candidate(c, st, session, ask, latest[st.cluster_id], p95.get(st.cluster_id)) for st in states]


def place(c: AppContext, ask: Ask, settings: PlacementSettings, *, reserve: bool, placed_by: str = ""
          ) -> tuple[list[Ranked], list[Excluded], CapacityReservationRow | None, datetime]:
    """Rank, and with `reserve` hold the first cluster that still passes under its lock. Raises 429 rate-limited when the team
    already holds MAX_ACTIVE_PLACEMENTS in the environment, and 422 no-placement when no cluster can be held."""
    now = datetime.now(timezone.utc)
    stale_after = c.capacity.stale_after_seconds
    with c.db.session() as s:
        found = candidates(c, s, ask, now)
    ranked, excluded = rank(ask, found, settings, now=now, stale_after=stale_after)
    for x in excluded:
        EXCLUDED.labels(x.reason).inc()
    if not reserve:
        PLACEMENTS.labels("dry-run").inc()
        return ranked, excluded, None, now
    by_id = {x.cluster_id: x for x in found}
    for r in ranked:
        with c.db.session() as s:
            repo = ReservationRepo(s)
            repo.lock_team_placements(ask.team, ask.environment, placed_by)
            active = repo.active_placements(ask.team, ask.environment, placed_by)
            if active >= MAX_ACTIVE_PLACEMENTS:
                PLACEMENTS.labels("rate-limited").inc()
                raise Problem.too_many(f"{ask.team or placed_by} already holds {active} active placements in "
                                       f"{ask.environment}; a placement lasts until a create claims it or it lapses",
                                       retry_after=60)
            repo.lock_cluster(r.cluster_id)
            repo.reclaim(r.cluster_id)
            st = c.registry.get(r.cluster_id)
            latest = SnapshotRepo(s).latest([r.cluster_id])[r.cluster_id]
            fresh = candidate(c, st, s, ask, latest, by_id[r.cluster_id].usage_p95)
            again, _ = rank(ask, [fresh], settings, now=now, stale_after=stale_after)
            if not again:
                continue                     # filled since the ranking: the next one
            when = utcnow()
            row = repo.hold(CapacityReservationRow(
                placement_id=f"pl-{when:%Y%m%d}-{secrets.token_hex(4)}", cluster_id=r.cluster_id, env=ask.environment,
                # Rounded up to the columns' scale, as a request's hold (capacity_backend.reserve): never less than was checked.
                team=ask.team, placed_by=placed_by[:100], cpu=ask.cpu.quantize(Decimal("0.001"), rounding=ROUND_CEILING),
                memory=int(ask.memory.to_integral_value(rounding=ROUND_CEILING)), pods=ask.pods,
                created_at=when, expires_at=when + timedelta(seconds=settings.reservation_seconds)))
            s.expunge(row)
        r.reserved = True
        PLACEMENTS.labels("placed").inc()
        return ranked, excluded, row, now
    PLACEMENTS.labels("no-placement").inc()
    raise Problem.unprocessable(
        "no-placement", f"No {ask.environment} cluster can take {ask.cpu.normalize():f} cores and "
                        f"{(ask.memory / 2**30).normalize():f}Gi" + (": every candidate was excluded" if not ranked else
                                                                     ": every ranked cluster filled meanwhile"),
        excluded=[{"clusterId": x.cluster_id, "reason": x.reason, "detail": x.detail} for x in excluded])


def view(ask: Ask, body: dict[str, Any], ranked: list[Ranked], excluded: list[Excluded], row: CapacityReservationRow | None,
         now: datetime) -> dict[str, Any]:
    return {"placementId": row.placement_id if row else None, "expiresAt": row.expires_at if row else None,
            "clusterId": row.cluster_id if row else None, "asOf": now.replace(microsecond=0),
            "request": {"environment": ask.environment, "team": ask.team, "tier": body.get("tier") or "small",
                        "cpu": int(ask.cpu * 1000), "memory": int(ask.memory), "pods": ask.pods,
                        "constraints": body.get("constraints") or {}},
            "ranked": [{"clusterId": r.cluster_id, "score": r.score, "reserved": r.reserved, "basis": r.basis,
                        "snapshotAt": r.snapshot_at, "boundBy": r.bound_by, "factors": r.factors,
                        **{res: {"unit": "millicores" if res == "cpu" else "bytes", **r.figures[res]} for res in RESOURCES}}
                       for r in ranked],
            "excluded": [{"clusterId": x.cluster_id, "reason": x.reason, "detail": x.detail} for x in excluded]}
