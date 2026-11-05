"""Rate limits (docs/01, Operational safety): token buckets per caller and per team, separate
buckets for the expensive calls (:place, :suggest, :export), and a cap on a team's active
placements. 429 rate-limited with Retry-After. In-process per replica; the limits are set per
replica count so the instance-wide rate stays near the configured one."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable

from cmapi.core.errors import Problem


@dataclass(frozen=True)
class Limit:
    rate_per_minute: float
    burst: int


DEFAULTS = {
    "default": Limit(120, 60),        # per caller, every route
    "team": Limit(600, 200),          # per team, writes
    "place": Limit(10, 5),            # POST /capacity:place per caller
    "suggest": Limit(240, 40),        # :suggest per caller (debounced by the portal)
    "export": Limit(4, 2),            # :export per caller
}


@dataclass
class _Bucket:
    tokens: float
    at: float


@dataclass
class RateLimiter:
    limits: dict[str, Limit] = field(default_factory=lambda: dict(DEFAULTS))
    max_active_placements_per_team: int = 10
    clock: Callable[[], float] = time.monotonic
    _buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)
    _placements: dict[str, set[str]] = field(default_factory=dict)

    def take(self, kind: str, key: str) -> None:
        lim = self.limits[kind]
        now = self.clock()
        b = self._buckets.get((kind, key)) or _Bucket(lim.burst, now)
        b.tokens = min(lim.burst, b.tokens + (now - b.at) * lim.rate_per_minute / 60)
        b.at = now
        if b.tokens < 1:
            wait = math.ceil((1 - b.tokens) * 60 / lim.rate_per_minute)
            self._buckets[(kind, key)] = b
            raise Problem.too_many(f"Too many {kind} calls; retry in {wait} s", retry_after=wait)
        b.tokens -= 1
        self._buckets[(kind, key)] = b

    def check(self, caller: str, team: str | None, route_kind: str = "default", write: bool = False) -> None:
        self.take("default", caller)
        if route_kind != "default":
            self.take(route_kind, caller)
        if write and team:
            self.take("team", team)

    def start_placement(self, team: str, placement_id: str) -> None:
        active = self._placements.setdefault(team, set())
        if len(active) >= self.max_active_placements_per_team:
            raise Problem.too_many(f"{team} already holds {len(active)} active placements", retry_after=60)
        active.add(placement_id)

    def end_placement(self, team: str, placement_id: str) -> None:
        self._placements.get(team, set()).discard(placement_id)
