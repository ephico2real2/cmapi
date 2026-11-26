"""Placement: which cluster a new namespace should land on (#21, #303; docs/02, "Placement"; docs/01, "Placement").

    "Placement picks the cluster a new namespace should land on and holds its capacity until the namespace is live, so two
    requests can never both take the last headroom. It decides from three sources, refuses to decide on stale or partial
    data, and explains every cluster it ranked or excluded." (docs/02)

This module is the decision, pure: each candidate's facts in, the ranked and the excluded clusters out. The facts are gathered
by plugins/capacity/placement.py from the three sources docs/02 names: the stored snapshots (freshness, zones, 14-day usage),
the API's watch (committed quota, the size's allocatable, the team's namespaces) and the cmapi database (active holds). No
Thanos call: "Placement makes no Thanos call while a request is being planned. Thanos is read only by the snapshot job."

The arithmetic is the plan's capacity check's (core/capacity_backend.py, `SimulatedCapacity.check`), so a cluster placement
ranks is one the create's check finds room on: per resource, limit = size × overcommit, and the request fits when committed +
reserved + request ≤ limit. The size is the Capacity tab's (core/capacity.py): clusters.yaml `simulatedCapacity` when set
(the owner's decision of 2026-11-18, kept until it is removed), else the allocatable of the nodes that count. CPU and memory
are checked separately (docs/01: "placement filters on both").

Hard filters, each with a named reason (docs/02): not connected, not writable, placement disabled, outside the requested region,
zones or clusterSelector, stale or partial data, no size, maxNamespaces reached, no CPU or memory headroom after reservations,
and, in the environments of `zoneFailureEnvironments` (prod by default), no zone-failure headroom: "quota headroom computed
with the largest zone removed, so a placed namespace still fits after losing a zone". The zone sizes are the newest complete
snapshot's zone rows; the largest zone's share of the allocatable is taken off the size. A cluster with fewer than two zones
loses everything with its zone, so it has no zone-failure headroom. A counted node with no zone label may sit in the largest
zone, so that share is not known: such a cluster is excluded as partial-data where zone failure is checked.

Score, 0 to 100 (docs/02; weights in placement.yaml): quota headroom after placement 40, usage headroom from the 14-day p95
25, balance 15, team affinity 10, zone spread 10; multiplied by the cluster's `placement.weight` (0 to 2) and capped at 100;
ties go to the lower clusterId. How each factor is measured, where docs/02 names it only:
- quota headroom: the smaller of CPU's and memory's headroom after placement, as a share of the limit;
- usage headroom: 1 − the larger of CPU's and memory's 14-day p95 use over allocatable; no credit when it is not measured
  (usage.source none, or no snapshot measured it): missing is never read as idle;
- balance: "Distance from the fleet's average utilisation in that environment". 0.5 at the average of the candidates that pass
  the filters, rising to 1 for a cluster 50 points below it and 0 for one 50 points above, on its fuller resource;
- team affinity: 1 when the team already has a namespace on the cluster. A negative weight spreads teams instead;
- zone spread: "How evenly the cluster's free capacity is spread across its zones": the smallest zone's allocatable over the
  largest's, on the worse resource; 0 with fewer than two zones.

Standard library and core/capacity.py only, so tests/core runs it without the service's packages (#693).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Mapping, Sequence

from cmapi.core.capacity import RESOURCES, interval_seconds, to_unit

FACTORS = ("quotaHeadroom", "usageHeadroom", "balance", "teamAffinity", "zoneSpread")
DEFAULT_WEIGHTS = {"quotaHeadroom": 40, "usageHeadroom": 25, "balance": 15, "teamAffinity": 10, "zoneSpread": 10}
DEFAULT_RESERVATION_SECONDS = 900               # docs/02: "takes a 15-minute reservation on the top one"
MAX_ACTIVE_PLACEMENTS = 3                       # docs/01: "at most 3 active placements per team and environment"
REASONS = ("not-connected", "not-writable", "placement-disabled", "outside-region", "outside-zones", "outside-selector",
           "stale-data", "partial-data", "no-size", "max-namespaces", "no-cpu-headroom", "no-memory-headroom",
           "zone-failure-headroom")


class PlacementSettings:
    """placement.yaml (docs/02, "config/placement.yaml: score weights, freshness limits, reservation TTL"), optional:
    `weights.<factor>` (numbers; teamAffinity may be negative), `reservation` (a duration, 1m to 60m, default 15m) and
    `zoneFailureEnvironments` (default [prod]). Freshness is capacity.yaml's `staleAfterIntervals`. A value of the wrong type
    stops the start, with every problem named."""

    def __init__(self, raw: Mapping[str, Any] | None):
        raw = raw or {}
        problems: list[str] = []
        unknown = sorted(set(raw) - {"weights", "reservation", "zoneFailureEnvironments"})
        if unknown:
            problems.append(f"unknown keys {unknown}")
        weights = raw.get("weights") or {}
        self.weights = dict(DEFAULT_WEIGHTS)
        if not isinstance(weights, Mapping):
            problems.append("weights: must be a mapping of factor to number")
            weights = {}
        for k, v in weights.items():
            if k not in DEFAULT_WEIGHTS:
                problems.append(f"weights.{k}: not one of {list(FACTORS)}")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or (v < 0 and k != "teamAffinity"):
                problems.append(f"weights.{k}: must be a number{'' if k == 'teamAffinity' else ', 0 or more'}, not {v!r}")
            else:
                self.weights[k] = float(v)
        self.reservation_seconds = DEFAULT_RESERVATION_SECONDS
        if "reservation" in raw:
            try:
                self.reservation_seconds = interval_seconds(raw["reservation"])
            except ValueError as exc:
                problems.append(f"reservation: {exc}")
            if not 60 <= self.reservation_seconds <= 3600:
                problems.append(f"reservation: must be 1m to 60m, not {raw['reservation']!r}")
        zf = raw.get("zoneFailureEnvironments", ["prod"])
        if not isinstance(zf, list) or not all(isinstance(e, str) for e in zf):
            problems.append("zoneFailureEnvironments: must be a list of environments")
            zf = ["prod"]
        self.zone_failure_environments = frozenset(zf)
        if problems:
            raise ValueError("placement.yaml: " + "; ".join(problems))


@dataclass(frozen=True)
class Ask:
    """What one namespace needs (cores, bytes, pods) and where it may go."""
    environment: str
    team: str | None                    # None on an instance whose metadata keys have no team label
    cpu: Decimal
    memory: Decimal
    pods: int
    region: str | None = None
    zones: tuple[str, ...] = ()
    selector: Mapping[str, str] = field(default_factory=dict)       # clusterSelector.matchLabels

    def amount(self, resource: str) -> Decimal:
        return self.cpu if resource == "cpu" else self.memory


@dataclass(frozen=True)
class Candidate:
    """One cluster of the environment, with what the three sources say of it now."""
    cluster_id: str
    region: str | None
    labels: Mapping[str, str]
    writes: bool
    not_connected: str | None                   # why it is not connected; None when it is
    enabled: bool                               # clusters.yaml placement.enabled (default true)
    max_namespaces: int | None                  # clusters.yaml placement.maxNamespaces
    weight: float                               # clusters.yaml placement.weight (default 1, 0 to 2)
    size: Mapping[str, Decimal] | None          # cores, bytes: simulatedCapacity, else the counted nodes' allocatable
    basis: str | None                           # simulated or allocatable
    overcommit: Mapping[str, Decimal]
    committed: Mapping[str, Decimal] | None     # None: the committed quota is not known (the plan's check says unknown)
    committed_detail: str | None
    namespaces: int | None                      # managed namespaces with a quota, against maxNamespaces
    reserved: Mapping[str, Decimal]             # active holds: open requests' and placements'
    snapshot_at: datetime | None                # the newest complete snapshot
    snapshot_detail: str | None                 # why the newest snapshot is incomplete, when it is
    zones: Mapping[str, Mapping[str, Decimal]]  # the newest complete snapshot's zones: zone -> resource -> allocatable
    usage_p95: Mapping[str, float] | None       # resource -> 14-day p95 of use over allocatable
    team_namespaces: int                        # the team's namespaces on the cluster
    zones_complete: bool = True                 # all counted nodes had a zone label


@dataclass
class Ranked:
    cluster_id: str
    score: int
    factors: dict[str, float]
    figures: dict[str, dict[str, Any]]          # resource -> headroom before and after, zone-failure, p95, in API units
    bound_by: str
    commitment_after: dict[str, Decimal]
    snapshot_at: datetime | None
    basis: str | None
    reserved: bool = False


@dataclass(frozen=True)
class Excluded:
    cluster_id: str
    reason: str
    detail: str


def _fmt(resource: str, value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001'), rounding=ROUND_FLOOR).normalize():f} cores" if resource == "cpu" \
        else f"{(value / 2**30).quantize(Decimal('0.01'), rounding=ROUND_FLOOR).normalize():f} Gi"


def _age(now: datetime, at: datetime) -> str:
    minutes = int((now - at).total_seconds() // 60)
    return f"{minutes} min" if minutes < 120 else f"{minutes // 60} h"


def zone_failure_limit(c: Candidate, resource: str) -> Decimal:
    """The limit with the largest zone's share of the allocatable taken off: 0 with fewer than two zones."""
    assert c.size is not None
    shares = [z.get(resource) or Decimal(0) for z in c.zones.values()]
    total = sum(shares, Decimal(0))
    if len(shares) < 2 or total <= 0:
        return Decimal(0)
    return c.size[resource] * c.overcommit[resource] * (total - max(shares)) / total


def _filter(c: Candidate, ask: Ask, now: datetime, stale_after: int, zone_failure: bool) -> Excluded | None:
    """The first hard filter the cluster fails, or None."""
    def out(reason: str, detail: str) -> Excluded:
        return Excluded(c.cluster_id, reason, detail[:300])

    if c.not_connected:
        return out("not-connected", c.not_connected)
    if not c.writes:
        return out("not-writable", "clusters.yaml writes: false")
    if not c.enabled:
        return out("placement-disabled", "clusters.yaml placement.enabled: false")
    if ask.region and c.region != ask.region:
        return out("outside-region", f"region {c.region or 'not set'}, not {ask.region}")
    missing = [z for z in ask.zones if z not in c.zones]
    if missing:
        return out("outside-zones", f"no counted node in {', '.join(missing)}")
    off = [f"{k}={v}" for k, v in ask.selector.items() if c.labels.get(k) != v]
    if off:
        return out("outside-selector", f"clusterSelector {', '.join(off)} does not match")
    if c.snapshot_at is None or (now - c.snapshot_at).total_seconds() > stale_after:
        if c.snapshot_detail:
            return out("partial-data", f"newest snapshot incomplete: {c.snapshot_detail}")
        when = f"newest complete snapshot {_age(now, c.snapshot_at)} old" if c.snapshot_at else "no complete snapshot yet"
        return out("stale-data", f"{when}, limit {stale_after // 60} min")
    if c.committed is None:
        return out("partial-data", f"committed quota not known: {c.committed_detail or 'no quota read'}")
    if c.size is None or any(c.size[r] <= 0 for r in RESOURCES):
        return out("no-size", "no simulatedCapacity in clusters.yaml, and the nodes' allocatable is not known or not fresh")
    if c.max_namespaces is not None and (c.namespaces or 0) >= c.max_namespaces:
        return out("max-namespaces", f"{c.namespaces} of placement.maxNamespaces {c.max_namespaces}")
    for r in RESOURCES:
        headroom = c.size[r] * c.overcommit[r] - c.committed[r] - c.reserved[r]
        if ask.amount(r) > headroom:
            return out(f"no-{r}-headroom", f"needs {_fmt(r, ask.amount(r))}, {_fmt(r, max(headroom, Decimal(0)))} left "
                                           "after committed quota and active reservations")
    if zone_failure:
        if not c.zones_complete:
            return out("partial-data", "zone-failure headroom needs a zone for every counted node")
        for r in RESOURCES:
            left = zone_failure_limit(c, r) - c.committed[r] - c.reserved[r]
            if ask.amount(r) > left:
                largest = min(c.zones, key=lambda z: (-(c.zones[z].get(r) or 0), z)) if c.zones else None
                without = f"without zone {largest}" if len(c.zones) >= 2 else \
                    f"in its {'one zone' if c.zones else 'nodes with no zone label'}, which a zone failure takes"
                return out("zone-failure-headroom", f"needs {_fmt(r, ask.amount(r))}, {_fmt(r, max(left, Decimal(0)))} "
                                                    f"left {without}")
    return None


def _clamp(v: float) -> float:
    return min(max(v, 0.0), 1.0)


def rank(ask: Ask, candidates: Sequence[Candidate], settings: PlacementSettings, *, now: datetime,
         stale_after: int) -> tuple[list[Ranked], list[Excluded]]:
    """Every candidate either ranked, best first, or excluded with its reason. Deterministic: the same facts, the same order."""
    zone_failure = ask.environment in settings.zone_failure_environments
    passing: list[Candidate] = []
    excluded: list[Excluded] = []
    for c in sorted(candidates, key=lambda c: c.cluster_id):
        why = _filter(c, ask, now, stale_after, zone_failure)
        if why is None:
            passing.append(c)
        else:
            excluded.append(why)
    # The environment's average commitment over the clusters that pass, per resource: summed, never an average of ratios.
    avg: dict[str, float] = {}
    for r in RESOURCES:
        limit = sum((c.size[r] * c.overcommit[r] for c in passing), Decimal(0))          # type: ignore[index]
        used = sum((c.committed[r] + c.reserved[r] for c in passing), Decimal(0))        # type: ignore[index]
        avg[r] = float(used / limit) if limit > 0 else 0.0
    w = settings.weights
    ranked: list[Ranked] = []
    for c in passing:
        assert c.size is not None and c.committed is not None
        limit = {r: c.size[r] * c.overcommit[r] for r in RESOURCES}
        before = {r: limit[r] - c.committed[r] - c.reserved[r] for r in RESOURCES}
        after = {r: before[r] - ask.amount(r) for r in RESOURCES}
        commitment = {r: (c.committed[r] + c.reserved[r] + ask.amount(r)) / limit[r] for r in RESOURCES}
        factors = {"quotaHeadroom": min(_clamp(float(after[r] / limit[r])) for r in RESOURCES),
                   "usageHeadroom": _clamp(1 - max(c.usage_p95[r] for r in RESOURCES))
                   if c.usage_p95 and all(r in c.usage_p95 for r in RESOURCES) else 0.0,
                   "balance": _clamp(0.5 - max(float(commitment[r]) - avg[r] for r in RESOURCES)),
                   "teamAffinity": 1.0 if c.team_namespaces > 0 else 0.0,
                   "zoneSpread": 0.0}
        if len(c.zones) >= 2:
            factors["zoneSpread"] = min(
                float(min(z.get(r) or 0 for z in c.zones.values()) / max(z.get(r) or 0 for z in c.zones.values()))
                if max(z.get(r) or 0 for z in c.zones.values()) > 0 else 0.0 for r in RESOURCES)
        raw = sum(w[f] * factors[f] for f in FACTORS)
        score = int(min(max(raw * c.weight, 0.0), 100.0) + 0.5)
        figures: dict[str, dict[str, Any]] = {}
        for r in RESOURCES:
            zf = zone_failure_limit(c, r) - c.committed[r] - c.reserved[r] - ask.amount(r) if zone_failure else None
            figures[r] = {"quotaHeadroomBefore": to_unit(r, before[r], ROUND_FLOOR),
                          "quotaHeadroomAfter": to_unit(r, after[r], ROUND_FLOOR),
                          "zoneFailureHeadroomAfter": to_unit(r, zf, ROUND_FLOOR) if zf is not None else None,
                          "usageP95": (c.usage_p95 or {}).get(r)}
        bound = "both" if round(commitment["cpu"], 3) == round(commitment["memory"], 3) else \
            "cpu" if commitment["cpu"] > commitment["memory"] else "memory"
        ranked.append(Ranked(c.cluster_id, score, {f: round(factors[f], 4) for f in FACTORS}, figures, bound, commitment,
                             c.snapshot_at, c.basis))
    ranked.sort(key=lambda x: (-x.score, x.cluster_id))
    return ranked, excluded
