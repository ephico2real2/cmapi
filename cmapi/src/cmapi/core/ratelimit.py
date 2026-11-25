"""Rate limits (docs/01, Operational safety): token buckets per caller and per team, separate buckets for writes, :place,
:suggest and :export, and a cap on a team's active placements in an environment. 429 rate-limited with Retry-After.
In the memory of each replica, not shared: each API pod enforces the limits on the calls that reach it, so with N pods
behind the front door a caller can reach up to N times a limit (docs/18, "Rate limits"; #689).

Standard library and core/errors.py only: core/config.py reads the limits with it, and the tools and the reference code
load the config without structlog or prometheus_client (#693). The 429 dependency, its log line and its metric are in
cmapi/routers/__init__.py.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from cmapi.core.errors import Problem

# The bucket classes. Every limited call takes one token from its caller's bucket of exactly one of the first five, so a
# burst of type-ahead does not spend the budget of reads; "team" is the bucket of the team that a new change request is for.
READ, WRITE, PLACE, SUGGEST, EXPORT, TEAM = "read", "write", "place", "suggest", "export", "team"
CALLER_CLASSES = (READ, WRITE, PLACE, SUGGEST, EXPORT)
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# The custom methods that the design names (docs/01), each with a bucket of its own.
CUSTOM_CLASSES = {":place": PLACE, ":suggest": SUGGEST, ":export": EXPORT}

# The largest value of a setting: the largest integer that JSON carries exactly (core/http_settings.py, MAX_LIMIT).
MAX_SETTING = 2**53 - 1


@dataclass(frozen=True)
class Limit:
    rate_per_minute: float      # tokens added each minute
    burst: int                  # the most tokens a bucket holds, and the tokens of a new bucket


# The defaults, per caller (team: per team) and per replica. read, team, place, suggest and export keep the values that this
# module had since docs/02; write is new with #689: one a second, 30 at once.
DEFAULTS: dict[str, Limit] = {
    READ: Limit(120, 60),       # every call that is not one of the others
    WRITE: Limit(60, 30),       # POST, PUT, PATCH and DELETE, a dry run too: it runs the validator
    PLACE: Limit(10, 5),        # POST /api/v1/capacity:place (not built yet)
    SUGGEST: Limit(240, 40),    # GET /api/v1/quotas:suggest, which the portal sends as a person types
    EXPORT: Limit(4, 2),        # GET /api/v1/quotas:export, every matching row
    TEAM: Limit(600, 200),      # each change request opened for one team, whoever sends it
}

# The active placements that a team may hold in one environment (docs/01). No route takes them yet: :place is not built.
MAX_ACTIVE_PLACEMENTS = 3
# The buckets kept before the full ones are dropped. A full bucket is the same as no bucket: a new one starts full.
SWEEP_AT = 10_000


def rate_class(method: str, path: str) -> str:
    """The caller's bucket of a route: its custom method's when the design names it, else write or read by the method.

    `path` is the route's template (`/api/v1/quotas:export`), not the URL, so a path parameter that ends in ":export"
    does not make a call an export."""
    for suffix, kind in CUSTOM_CLASSES.items():
        if path.endswith(suffix):
            return kind
    return WRITE if method.upper() in WRITE_METHODS else READ


def parse_rate_limits(raw: Any) -> tuple[dict[str, Limit], list[str]]:
    """instance.yaml `http.rateLimits`: {class: {perMinute, burst}}, each field optional, over the defaults. Returns the
    limits and the problems that stop the start."""
    limits = dict(DEFAULTS)
    if raw is None:
        return limits, []
    if not isinstance(raw, Mapping):
        return limits, ["instance.yaml: http.rateLimits must be a mapping, such as {write: {perMinute: 60, burst: 30}}"]
    problems = []
    unknown = sorted(str(k) for k in set(raw) - set(DEFAULTS))
    if unknown:
        problems.append(f"instance.yaml: http.rateLimits has unknown classes {unknown}; the classes are {sorted(DEFAULTS)}")
    for kind, given in raw.items():
        if kind not in DEFAULTS:
            continue
        where = f"instance.yaml: http.rateLimits.{kind}"
        if not isinstance(given, Mapping):
            problems.append(f"{where} must be a mapping with perMinute and burst")
            continue
        extra = sorted(str(k) for k in set(given) - {"perMinute", "burst"})
        if extra:
            problems.append(f"{where} has unknown fields {extra}")
        rate = given.get("perMinute", DEFAULTS[kind].rate_per_minute)
        burst = given.get("burst", DEFAULTS[kind].burst)
        # bool is an int in Python, and a float can be nan or inf, which fail the range
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 < rate <= MAX_SETTING:
            problems.append(f"{where}.perMinute is a number of calls a minute, more than 0 and at most {MAX_SETTING}, "
                            f"not {rate!r}")
            continue
        if isinstance(burst, bool) or not isinstance(burst, int) or not 1 <= burst <= MAX_SETTING:
            problems.append(f"{where}.burst is a whole number of calls, 1 to {MAX_SETTING}, not {burst!r}")
            continue
        limits[kind] = Limit(float(rate), burst)
    return limits, problems


@dataclass(frozen=True)
class Refusal:
    """A call that a bucket refused: its class, its key (a caller's subject, or a team), the whole seconds until the bucket
    holds a token again, and whether it is the first refusal since the bucket last gave a token (the one that is logged)."""
    kind: str
    key: str
    retry_after: int
    first: bool

    def problem(self) -> Problem:
        if self.kind == TEAM:
            detail = f"Too many new requests for team {self.key}; try again in {self.retry_after} s"
        else:
            detail = f"Too many {self.kind} calls by this caller; try again in {self.retry_after} s"
        return Problem.too_many(detail, retry_after=self.retry_after)


@dataclass
class _Bucket:
    tokens: float
    at: float
    refusing: bool = False


@dataclass
class RateLimiter:
    """The token buckets of one process. Thread-safe: the 429 dependency runs on the event loop, and the team check in the
    route's worker thread."""
    limits: dict[str, Limit] = field(default_factory=lambda: dict(DEFAULTS))
    clock: Callable[[], float] = time.monotonic
    max_active_placements: int = MAX_ACTIVE_PLACEMENTS
    _buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)
    _placements: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _sweep_at: int = SWEEP_AT

    def take(self, kind: str, key: str) -> Refusal | None:
        """Take one token from the bucket (kind, key): None when it had one, else the refusal. A refused call takes
        nothing, so a client that retries at once is refused until the bucket refills."""
        limit = self.limits[kind]
        with self._lock:
            now = self.clock()
            if len(self._buckets) >= self._sweep_at:
                self._sweep(now)
            bucket = self._buckets.get((kind, key)) or _Bucket(float(limit.burst), now)
            bucket.tokens = min(float(limit.burst), bucket.tokens + max(0.0, now - bucket.at) * limit.rate_per_minute / 60)
            bucket.at = now
            self._buckets[(kind, key)] = bucket
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                bucket.refusing = False
                return None
            first = not bucket.refusing
            bucket.refusing = True
            # Retry-After is delay-seconds, a whole number (RFC 9110, section 10.2.3); after it the bucket holds a token.
            wait = max(1, math.ceil((1 - bucket.tokens) * 60 / limit.rate_per_minute))
            return Refusal(kind, key, wait, first)

    def _sweep(self, now: float) -> None:
        """Drop the buckets that have refilled, each the same as a new one. The keys are signed-in subjects and teams, so
        this bounds the memory to the callers of the last minutes."""
        for k, b in list(self._buckets.items()):
            limit = self.limits[k[0]]
            if b.tokens + max(0.0, now - b.at) * limit.rate_per_minute / 60 >= limit.burst:
                del self._buckets[k]
        self._sweep_at = max(SWEEP_AT, 2 * len(self._buckets))

    def start_placement(self, team: str, environment: str, placement_id: str) -> None:
        with self._lock:
            active = self._placements.setdefault((team, environment), set())
            if placement_id not in active and len(active) >= self.max_active_placements:
                raise Problem.too_many(f"{team} already holds {len(active)} active placements in {environment}",
                                       retry_after=60)
            active.add(placement_id)

    def end_placement(self, team: str, environment: str, placement_id: str) -> None:
        with self._lock:
            self._placements.get((team, environment), set()).discard(placement_id)
