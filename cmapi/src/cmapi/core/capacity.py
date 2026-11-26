"""The capacity arithmetic that the plan's check and GET /api/v1/capacity share (#302), and capacity.yaml as code reads it.

One definition, so the commitment the Capacity tab shows is the one a plan is judged by (a service test holds them equal while
no request holds capacity; the plan's check also counts the holds of open requests, #62, which the tab does not show yet):
    limit      = size × overcommit                 (size: clusters.yaml simulatedCapacity, else the nodes' allocatable)
    commitment = committed ÷ limit                 (may pass 1: quota is not capacity, and Kubernetes lets it pass)
    headroom   = limit − committed                 (negative when over)
    status     = over above 1, critical or warn at the environment's targets, else ok
docs/01 "Headroom and overcommit"; docs/02 "Cluster capacity", "Aggregation rules". The figures are exact (Decimal) until the
API's integers: CPU in millicores and memory in bytes (design B: no floats for amounts in the contract).

Group rules (docs/02, "Aggregation rules"): a group's commitment is recomputed from the summed numerators and denominators,
never an average of ratios; headroom is the sum of each cluster's headroom floored at 0, since capacity cannot move between
clusters; the largest placement is the largest single cluster's headroom, per resource, with that cluster; the status is the
worst member's, with the counts per status.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Iterable, Mapping, Sequence

RESOURCES = ("cpu", "memory")
UNITS = {"cpu": "millicores", "memory": "bytes"}
STATUSES = ("ok", "warn", "critical", "over")                  # from best to worst
DEFAULT_OVERCOMMIT = Decimal("1.0")
DEFAULT_WARN, DEFAULT_CRITICAL = Decimal("0.85"), Decimal("0.95")
# What GET /api/v1/capacity leaves null for every cluster: the history of the snapshots (#21) is GET .../capacity of one cluster.
NOT_MEASURED = ("history",)
# capacity.yaml `snapshotInterval` (docs/02, "Stored capacity": "15m to 60m: the stored grain of cluster capacity", 30m by
# default) and `staleAfterIntervals` ("placement refuses a cluster whose newest complete snapshot is older", 2 by default).
SNAPSHOT_INTERVAL_DEFAULT, SNAPSHOT_INTERVAL_MIN, SNAPSHOT_INTERVAL_MAX = 1800, 900, 3600
STALE_AFTER_INTERVALS_DEFAULT = 2
DURATION = re.compile(r"^([1-9][0-9]*)(m|h)$")


def interval_seconds(value: Any) -> int:
    """A duration of capacity.yaml (`30m`, `1h`) in seconds. ValueError for anything else."""
    m = DURATION.fullmatch(str(value)) if isinstance(value, str) else None
    if m is None:
        raise ValueError(f"must be minutes or hours such as 30m or 1h, not {value!r}")
    return int(m.group(1)) * (60 if m.group(2) == "m" else 3600)


@dataclass(frozen=True)
class EnvSettings:
    overcommit: dict[str, Decimal]
    overcommit_default: bool                                    # the environment has no overcommit in capacity.yaml
    warn: Decimal
    critical: Decimal


class CapacitySettings:
    """The keys of capacity.yaml that built code reads: `overcommit.<env>.cpu|memory` (default 1.0),
    `targets.<env>.commitment.warn|critical` (default 0.85 and 0.95), `countTaints` (default none: the taint keys whose
    NoSchedule or NoExecute nodes still count as capacity), `snapshotInterval` (15m to 60m, default 30m) and
    `staleAfterIntervals` (1 or more, default 2; #21). A value of the wrong type stops the start, with every problem named."""

    def __init__(self, raw: Mapping[str, Any] | None):
        raw = raw or {}
        problems: list[str] = []
        self.overcommit: dict[str, dict[str, Decimal]] = {}
        for env, block in self._blocks(raw, "overcommit", problems):
            if not isinstance(block, Mapping):
                problems.append(f"overcommit.{env}: must be a mapping of cpu and memory")
                continue
            # Above 0: the limit is size × overcommit, and the plan's check divides by it.
            self.overcommit[str(env)] = {r: self._number(block[r], f"overcommit.{env}.{r}", problems, above_zero=True)
                                         for r in RESOURCES if r in block}
        self.targets: dict[str, dict[str, Decimal]] = {}
        for env, block in self._blocks(raw, "targets", problems):
            if not isinstance(block, Mapping):
                problems.append(f"targets.{env}: must be a mapping, such as {{commitment: {{warn: 0.85, critical: 0.95}}}}")
                continue
            commitment = block.get("commitment")
            if commitment is None:
                continue
            if not isinstance(commitment, Mapping):
                problems.append(f"targets.{env}.commitment: must be a mapping of warn and critical")
                continue
            self.targets[str(env)] = {k: self._number(commitment[k], f"targets.{env}.commitment.{k}", problems)
                                      for k in ("warn", "critical") if k in commitment}
        taints = raw.get("countTaints", [])
        if not isinstance(taints, list) or not all(isinstance(t, str) and t for t in taints):
            problems.append("countTaints: must be a list of taint keys")
            taints = []
        self.count_taints: tuple[str, ...] = tuple(taints)
        self.snapshot_seconds = SNAPSHOT_INTERVAL_DEFAULT
        if "snapshotInterval" in raw:
            try:
                self.snapshot_seconds = interval_seconds(raw["snapshotInterval"])
            except ValueError as exc:
                problems.append(f"snapshotInterval: {exc}")
            if not SNAPSHOT_INTERVAL_MIN <= self.snapshot_seconds <= SNAPSHOT_INTERVAL_MAX:
                problems.append(f"snapshotInterval: must be 15m to 60m, not {raw['snapshotInterval']!r}")
        stale = raw.get("staleAfterIntervals", STALE_AFTER_INTERVALS_DEFAULT)
        if isinstance(stale, bool) or not isinstance(stale, int) or stale < 1:
            problems.append(f"staleAfterIntervals: must be a whole number, 1 or more, not {stale!r}")
            stale = STALE_AFTER_INTERVALS_DEFAULT
        self.stale_after_intervals: int = stale
        if problems:
            raise ValueError("capacity.yaml: " + "; ".join(problems))

    @staticmethod
    def _blocks(raw: Mapping[str, Any], key: str, problems: list[str]) -> list[tuple[Any, Any]]:
        """The per-environment entries of a top-level key, or none with a problem named when the key is not a mapping."""
        value = raw.get(key) or {}
        if not isinstance(value, Mapping):
            problems.append(f"{key}: must be a mapping of environment to settings")
            return []
        return list(value.items())

    @staticmethod
    def _number(value: Any, where: str, problems: list[str], *, above_zero: bool = False) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or (above_zero and value == 0):
            problems.append(f"{where}: must be a number, {'above 0' if above_zero else '0 or more'}, not {value!r}")
            return Decimal(0)
        return Decimal(str(value))

    @property
    def stale_after_seconds(self) -> int:
        """How old a cluster's newest complete snapshot may be before placement excludes it as stale-data."""
        return self.snapshot_seconds * self.stale_after_intervals

    def for_cluster(self, environment: str, placement: Mapping[str, Any] | None) -> EnvSettings:
        """The environment's settings with the cluster's clusters.yaml `placement.overcommit` over them (docs/01: "A cluster's
        placement block can override its environment's overcommit"). The plan's check, the Capacity tab and placement all read
        a cluster's overcommit here, so they agree."""
        es = self.env(environment)
        over = (placement or {}).get("overcommit") or {}
        if not over:
            return es
        return EnvSettings({r: Decimal(str(over[r])) if r in over else es.overcommit[r] for r in RESOURCES}, False,
                           es.warn, es.critical)

    def env(self, environment: str) -> EnvSettings:
        over = self.overcommit.get(environment)
        targets = self.targets.get(environment) or {}
        return EnvSettings({r: (over or {}).get(r, DEFAULT_OVERCOMMIT) for r in RESOURCES}, over is None,
                           targets.get("warn", DEFAULT_WARN), targets.get("critical", DEFAULT_CRITICAL))


# --------------------------------------------------------------------------- one cluster

def limit_of(size: Decimal, overcommit: Decimal) -> Decimal:
    return size * overcommit


def ratio(committed: Decimal, limit: Decimal) -> Decimal | None:
    """committed ÷ limit, or None when there is no limit to divide by."""
    return committed / limit if limit > 0 else None


def level(r: Decimal | float, warn: Decimal | float, critical: Decimal | float) -> str:
    if r > 1:
        return "over"
    return "critical" if r >= critical else "warn" if r >= warn else "ok"


def worst(statuses: Iterable[str | None]) -> str | None:
    known = [s for s in statuses if s is not None]
    return max(known, key=STATUSES.index) if known else None


def bound_by(cpu: float | Decimal | None, memory: float | Decimal | None) -> str | None:
    """The resource that binds: the higher commitment, `both` when they agree to three decimals; None when either is unknown."""
    if cpu is None or memory is None:
        return None
    c, m = round(float(cpu), 3), round(float(memory), 3)
    return "both" if c == m else "cpu" if c > m else "memory"


def to_unit(resource: str, value: Decimal | None, rounding: str) -> int | None:
    """Cores to millicores, bytes to bytes, as an integer: ROUND_CEILING for what is committed or used, ROUND_FLOOR for what is
    available, so a rounding never shows more room than there is."""
    if value is None:
        return None
    scaled = value * 1000 if resource == "cpu" else value
    return int(scaled.to_integral_value(rounding=rounding))


def resource_figures(resource: str, *, committed: Decimal | None, quota_used: Decimal | None, used_missing: int | None,
                     simulated: Decimal | None, allocatable: Decimal | None, basis: str | None, env: EnvSettings) -> dict[str, Any]:
    """One resource of one cluster as the API gives it. `committed` None: the commitment is not known, and every figure that
    depends on it is null, never 0."""
    over = env.overcommit[resource]
    size = simulated if basis == "simulated" else allocatable if basis == "allocatable" else None
    limit = limit_of(size, over) if size is not None else None
    r = ratio(committed, limit) if committed is not None and limit is not None else None
    headroom = limit - committed if committed is not None and limit is not None else None
    return {"unit": UNITS[resource],
            "simulated": to_unit(resource, simulated, ROUND_FLOOR), "allocatable": to_unit(resource, allocatable, ROUND_FLOOR),
            "overcommit": float(over), "limit": to_unit(resource, limit, ROUND_FLOOR),
            "committed": to_unit(resource, committed, ROUND_CEILING),
            "quotaUsed": to_unit(resource, quota_used, ROUND_CEILING) if committed is not None else None,
            "quotaUsedMissing": used_missing if committed is not None else None,
            "headroom": to_unit(resource, headroom, ROUND_FLOOR),
            "commitment": round(float(r), 4) if r is not None else None,
            "status": level(r, env.warn, env.critical) if r is not None else None,
            "requested": None, "usedAvg": None, "usedPeak": None}


# --------------------------------------------------------------------------- a group of clusters

def group_figures(included: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The figures of a group from its included clusters (each an API cluster view whose state is ok): per resource the sums,
    the recomputed commitment, the floored headroom and the largest placement; the worst status and the counts."""
    out: dict[str, Any] = {"status": worst(c["status"] for c in included),
                           "statusCounts": {s: sum(1 for c in included if c["status"] == s) for s in STATUSES}}
    commitments: dict[str, float | None] = {}
    for r in RESOURCES:
        rows = [(c["clusterId"], c[r]) for c in included if c[r]["limit"] is not None and c[r]["committed"] is not None]
        if not rows:
            out[r], commitments[r] = None, None
            continue
        committed, limit = sum(f["committed"] for _, f in rows), sum(f["limit"] for _, f in rows)
        floored = sorted(((max(f["headroom"], 0), cid) for cid, f in rows), key=lambda hc: (-hc[0], hc[1]))
        commitment = round(committed / limit, 4) if limit > 0 else None
        commitments[r] = commitment
        out[r] = {"unit": UNITS[r], "committed": committed, "limit": limit, "commitment": commitment,
                  "headroom": sum(h for h, _ in floored),
                  "largestPlacement": {"value": floored[0][0], "clusterId": floored[0][1]}}
    out["boundBy"] = bound_by(commitments["cpu"], commitments["memory"])
    return out
