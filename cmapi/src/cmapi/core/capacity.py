"""The capacity arithmetic that the plan's check and GET /api/v1/capacity share (#302), and capacity.yaml as code reads it.

One definition, so the commitment the Capacity tab shows is the one a plan is judged by (a service test holds them equal):
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

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Iterable, Mapping, Sequence

RESOURCES = ("cpu", "memory")
UNITS = {"cpu": "millicores", "memory": "bytes"}
STATUSES = ("ok", "warn", "critical", "over")                  # from best to worst
DEFAULT_OVERCOMMIT = Decimal("1.0")
DEFAULT_WARN, DEFAULT_CRITICAL = Decimal("0.85"), Decimal("0.95")
# What only the snapshots of cmapi-capacity (#21) can give: in the contract as null, so #21 fills them with no change.
NOT_MEASURED = ("requested", "usedAvg", "usedPeak", "history")


@dataclass(frozen=True)
class EnvSettings:
    overcommit: dict[str, Decimal]
    overcommit_default: bool                                    # the environment has no overcommit in capacity.yaml
    warn: Decimal
    critical: Decimal


class CapacitySettings:
    """The keys of capacity.yaml that built code reads: `overcommit.<env>.cpu|memory` (default 1.0),
    `targets.<env>.commitment.warn|critical` (default 0.85 and 0.95) and `countTaints` (default none: the taint keys whose
    NoSchedule or NoExecute nodes still count as capacity). A value of the wrong type stops the start, with every problem named."""

    def __init__(self, raw: Mapping[str, Any] | None):
        raw = raw or {}
        problems: list[str] = []
        self.overcommit: dict[str, dict[str, Decimal]] = {}
        for env, block in (raw.get("overcommit") or {}).items():
            if not isinstance(block, Mapping):
                problems.append(f"overcommit.{env}: must be a mapping of cpu and memory")
                continue
            self.overcommit[str(env)] = {r: self._number(block[r], f"overcommit.{env}.{r}", problems)
                                         for r in RESOURCES if r in block}
        self.targets: dict[str, dict[str, Decimal]] = {}
        for env, block in (raw.get("targets") or {}).items():
            commitment = (block or {}).get("commitment") if isinstance(block, Mapping) else None
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
        if problems:
            raise ValueError("capacity.yaml: " + "; ".join(problems))

    @staticmethod
    def _number(value: Any, where: str, problems: list[str]) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            problems.append(f"{where}: must be a number, 0 or more, not {value!r}")
            return Decimal(0)
        return Decimal(str(value))

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
