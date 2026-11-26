"""The usage verdicts of docs/03, "Verdicts" (#310), as pure functions of a namespace's usage, requests and quota history.

    | Verdict            | Kind  | Fires when (over the window)                                                         |
    | insufficient-data  | Info  | Under 7 days of history, or under 80% hourly coverage                               |
    | quota-oversized    | Waste | requests ÷ quota (daily p95) below the environment's floor                          |
    | quota-tight        | Risk  | requests ÷ quota at or above the environment's ceiling for 10% of hours, or the     |
    |                    |       | quota was exhausted                                                                  |
    | requests-oversized | Waste | usage p95 ÷ requests below the environment's floor                                  |
    | idle               | Waste | CPU p95 under 0.05 cores and memory p95 under 128 MiB for the environment's idle    |
    |                    |       | period                                                                               |
    | right-sized        | OK    | None of the above                                                                    |

"A namespace's headline is its worst risk, or its largest waste when it has no risk." The other verdicts of docs/03 (no-quota,
requests-undersized, cpu-throttled, memory-limit-risk, zone-skew) need queries this build does not make yet (#703);
until then right-sized means none of the verdicts above.

The thresholds are docs/03's table, its "starting points", and config/analysis.yaml may set each one per environment:

    environments:
      prod: {quotaOversizedBelow: 0.5, requestsOversizedBelow: 0.4, quotaTightAt: 0.85, idleDays: 14}

dev takes rnd's column (docs/03: "dev ... uses the rnd column until its own thresholds are agreed").

Coverage is judged on the 14-day window (usage.py, MIN_COVERAGE): 80% of 14 days is more than 7 days of history, so the
"under 7 days of history" condition never fires on its own and is not checked twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

from cmapi.capacity.usage import NamespaceUsage, QuotaHistory

Kind = Literal["ok", "info", "waste", "risk"]
IDLE_CPU_CORES = 0.05
IDLE_MEMORY_BYTES = 128 * 2**20
QUOTA_TIGHT_HOURS = 0.10
RESOURCES = ("cpu", "memory")
KINDS: dict[str, Kind] = {"insufficient-data": "info", "quota-tight": "risk", "quota-oversized": "waste",
                          "requests-oversized": "waste", "idle": "waste", "right-sized": "ok"}
VERDICTS = tuple(KINDS)
# Waste with no risk: idle holds the whole quota unused; a quota above the requests blocks placement before requests above
# the usage block nodes (docs/03, "Gap"). The order breaks a tie between two wastes of one namespace.
WASTE_ORDER = ("idle", "quota-oversized", "requests-oversized")
NAMES = {"cpu": "CPU", "memory": "memory"}


@dataclass(frozen=True)
class Thresholds:
    quota_oversized_below: float
    requests_oversized_below: float
    quota_tight_at: float
    idle_days: int


DEFAULTS: dict[str, Thresholds] = {
    "rnd": Thresholds(0.30, 0.20, 0.95, 7),
    "dev": Thresholds(0.30, 0.20, 0.95, 7),
    "qa": Thresholds(0.40, 0.30, 0.90, 14),
    "uat": Thresholds(0.50, 0.40, 0.90, 14),
    "prod": Thresholds(0.50, 0.40, 0.85, 14),
}
FIELDS = {"quotaOversizedBelow": "quota_oversized_below", "requestsOversizedBelow": "requests_oversized_below",
          "quotaTightAt": "quota_tight_at", "idleDays": "idle_days"}


class AnalysisSettings:
    """config/analysis.yaml, optional: docs/03's thresholds with an override per served environment. A problem stops the start."""

    def __init__(self, raw: Mapping[str, Any] | None, allowed: set[str]):
        raw = raw or {}
        problems: list[str] = []
        self.thresholds = {env: DEFAULTS.get(env, DEFAULTS["prod"]) for env in allowed}
        unknown = set(raw) - {"environments"}
        if unknown:
            problems.append(f"analysis.yaml has unknown keys {sorted(unknown)}")
        envs = raw.get("environments") or {}
        if not isinstance(envs, Mapping):
            problems.append("analysis.yaml: environments must be a mapping of environment to thresholds")
            envs = {}
        for env, block in envs.items():
            where = f"analysis.yaml: environments.{env}"
            if env not in allowed:
                problems.append(f"{where} is not an environment this instance serves")
                continue
            if not isinstance(block, Mapping) or set(block) - set(FIELDS):
                problems.append(f"{where} takes only {sorted(FIELDS)}")
                continue
            changes: dict[str, Any] = {}
            for key, value in block.items():
                if key == "idleDays":
                    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 14:
                        problems.append(f"{where}.idleDays is a whole number of days, 1 to 14 (the window), not {value!r}")
                        continue
                elif not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value <= 1:
                    problems.append(f"{where}.{key} is a ratio above 0 and at most 1, not {value!r}")
                    continue
                changes[FIELDS[key]] = value
            self.thresholds[env] = replace(self.thresholds[env], **changes)
        if problems:
            raise ValueError("; ".join(problems))

    def of(self, env: str) -> Thresholds:
        return self.thresholds.get(env, DEFAULTS.get(env, DEFAULTS["prod"]))


@dataclass(frozen=True)
class Verdict:
    resource: str                   # cpu or memory
    verdict: str
    kind: Kind
    reason: str                     # the sentence a person reads, with the numbers and the threshold
    evidence: Mapping[str, Any] = field(default_factory=dict)


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _amount(resource: str, value: float) -> str:
    return f"{value:.2f} cores" if resource == "cpu" else f"{value / 2**30:.1f} GiB"


def judge(env: str, t: Thresholds, usage: NamespaceUsage, requests: Mapping[str, float | None],
          quotas: Mapping[str, float | None]) -> list[Verdict]:
    """The verdicts of one namespace, one or more per resource. `requests` and `quotas` are the ResourceQuota's used and
    hard now, from the API (docs/03: "Quota comes from the API, not Thanos"): CPU in cores, memory in bytes."""
    base = {"environment": env, "window": "14d", "coverage": usage.coverage}
    if usage.state != "ok":
        return [Verdict(r, "insufficient-data", "info", usage.reason or "Not enough usage data.", base) for r in RESOURCES]
    figs = {r: usage.figures(r) for r in RESOURCES}
    out: list[Verdict] = []
    idle = (figs["cpu"].idle_p95 is not None and figs["memory"].idle_p95 is not None
            and figs["cpu"].idle_p95 < IDLE_CPU_CORES and figs["memory"].idle_p95 < IDLE_MEMORY_BYTES)
    for r in RESOURCES:
        f = figs[r]
        req, quota = requests.get(r), quotas.get(r)
        history = usage.quota.get(r) or QuotaHistory(None, None, None)
        ev = {**base, "p95": f.p95, "peak": f.peak, "mean": f.avg7d, "requested": req, "quota": quota}
        if quota is not None and (history.p95 is None or history.hours_at_ceiling is None or history.peak is None):
            # Missing is not zero (docs/03): the namespace has a quota and Thanos has no history of it.
            out.append(Verdict(r, "insufficient-data", "info",
                               f"Thanos has no kube_resourcequota history of {QUOTA_KEYS_TEXT[r]} for this namespace.", ev))
            continue
        found = False
        if quota is not None and (history.hours_at_ceiling >= QUOTA_TIGHT_HOURS or history.peak >= 1):
            why = (f"the {NAMES[r]} quota was exhausted" if history.peak >= 1 else
                   f"requests were at {_pct(t.quota_tight_at)} or more of the {NAMES[r]} quota in "
                   f"{_pct(history.hours_at_ceiling)} of hours")
            out.append(Verdict(r, "quota-tight", "risk",
                               f"Over 14 days {why}; {env}'s ceiling is {_pct(t.quota_tight_at)} for {_pct(QUOTA_TIGHT_HOURS)} of hours.",
                               {**ev, "hoursAtCeiling": history.hours_at_ceiling, "ratioPeak": history.peak,
                                "threshold": t.quota_tight_at}))
            found = True
        if quota is not None and history.p95 < t.quota_oversized_below:
            out.append(Verdict(r, "quota-oversized", "waste",
                               f"Requests use {_pct(history.p95)} of the {NAMES[r]} quota at their p95 over 14 days, below "
                               f"{env}'s floor of {_pct(t.quota_oversized_below)}.",
                               {**ev, "ratioP95": history.p95, "threshold": t.quota_oversized_below}))
            found = True
        if req and f.p95 is not None and f.p95 / req < t.requests_oversized_below:
            out.append(Verdict(r, "requests-oversized", "waste",
                               f"Pods request {_amount(r, req)} of {NAMES[r]} and use {_amount(r, f.p95)} at p95 over 14 days: "
                               f"{_pct(f.p95 / req)}, below {env}'s floor of {_pct(t.requests_oversized_below)}.",
                               {**ev, "efficiency": f.p95 / req, "threshold": t.requests_oversized_below}))
            found = True
        if idle:
            out.append(Verdict(r, "idle", "waste",
                               f"CPU p95 {figs['cpu'].idle_p95:.3f} cores and memory p95 {figs['memory'].idle_p95 / 2**20:.0f} MiB "
                               f"over {env}'s idle period of {t.idle_days} days, under 0.05 cores and 128 MiB.",
                               {**ev, "idleP95": f.idle_p95, "idleDays": t.idle_days}))
            found = True
        if not found:
            out.append(Verdict(r, "right-sized", "ok", f"Quota, requests and real usage agree within the {env} thresholds.", ev))
    return out


QUOTA_KEYS_TEXT = {"cpu": "requests.cpu", "memory": "requests.memory"}


@dataclass(frozen=True)
class Headline:
    verdict: str
    kind: Kind
    resources: tuple[str, ...]      # the resources it holds for, cpu before memory
    reason: str


def headline(verdicts: list[Verdict]) -> Headline:
    """docs/03: "A namespace's headline is its worst risk, or its largest waste when it has no risk." With no risk and no
    waste, right-sized when every resource is, else insufficient-data."""
    def of(name: str) -> Headline | None:
        hits = [v for v in verdicts if v.verdict == name]
        if not hits:
            return None
        return Headline(name, hits[0].kind, tuple(r for r in RESOURCES if any(v.resource == r for v in hits)),
                        " ".join(dict.fromkeys(v.reason for v in hits)))

    for name in ("quota-tight", *WASTE_ORDER, "insufficient-data", "right-sized"):
        h = of(name)
        if h:
            return h
    return Headline("insufficient-data", "info", (), "No verdict was made for this namespace.")
