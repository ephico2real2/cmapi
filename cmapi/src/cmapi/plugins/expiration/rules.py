"""Expiration rules (config/expiration.yaml) and the daily expire_check decisions.

Optional, and never in prod: an environment with no entry in expiration.yaml, or with enabled: false,
refuses every expiry field with 422 expiration-not-allowed, except :makePermanent of a namespace that has a date: a date
given while expiration was on stays as it is on every other change, until :makePermanent removes it (#479). prod may
have an entry only with enabled: false (the owner's #222 decision: production never expires). Within limits an
extension follows the environment's change rule; past maxLifetimeDays from creation, or :makePermanent, adds
approver-platform. A single extension longer than maxExtensionDays is refused (expiration-limit).

States (GET /api/v1/expirations?state=):
    permanent       no expiry
    active          expiry further away than the first notice
    expiring        within the first notice (14 days), before the date
    grace           from the date for graceDays (7: the date and the 6 days after); still running
                    and extendable
    pending_delete  grace is over; the expired-namespace delete is due or open

Notices: on each run the nearest threshold at or above the days left is sent if it has not been,
so a short expiry still gets its 1-day notice and a missed run never sends a stale 14-day one.

Days are UTC days (#321). `cmapi.net/expires-at` is a date with no zone, and every date it is compared with is a UTC date:
today is `utc_today()`, and a namespace's creation day is the UTC date of its `creationTimestamp`, which Kubernetes writes
in UTC (metav1.Time marshals `t.UTC()` as RFC 3339). RFC 3339, section 4.1: "true interoperability is best achieved by
using Coordinated Universal Time (UTC)". The host's local date (`date.today()`) is never used: on a host east or west of UTC
it is another day for part of each day, and the plan, the list and the daily check would disagree.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from cmapi.core.errors import Problem


def utc_today() -> date:
    """Today's UTC date: the one day that the planner, GET /expirations and expire_check count from (#321)."""
    return datetime.now(timezone.utc).date()


def utc_day(stamp: Any) -> date | None:
    """The UTC date of an RFC 3339 timestamp such as `creationTimestamp`, or None when it is missing or not one. A stamp with
    no offset is read as UTC, as Kubernetes writes every stamp."""
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date()
    except (ValueError, OverflowError):                 # OverflowError: an offset that moves the day past year 1 or 9999
        return None


@dataclass(frozen=True)
class EnvRules:
    enabled: bool = True                # false: the environment takes no expiry, as one with no entry (#479)
    allowed_at_create: bool = True
    max_extension_days: int = 30
    max_lifetime_days: int = 180
    notify_days_before: tuple[int, ...] = (14, 7, 1)
    grace_days: int = 7
    delete_after_grace: bool = True
    min_notices_before_delete: int = 2


@dataclass(frozen=True)
class ExpiryInfo:
    """What the plugin reads from the Namespace (Git and live) and the request history."""
    namespace: str
    environment: str
    created: date
    expires_at: date | None
    notices_sent: frozenset[int] = frozenset()     # which notifyDaysBefore went out for this date
    last_extension: date | None = None
    open_request: bool = False
    protected: bool = False


@dataclass(frozen=True)
class ExpiryPlan:
    action: str                                    # set | extend | makePermanent | create
    new_date: date | None
    extra_approvals: tuple[str, ...] = ()          # groups added beyond the environment's change rule
    reasons: tuple[str, ...] = ()

    def facts(self) -> dict[str, Any]:
        return {"expirationAction": self.action, "expirationBeyondLimits": bool(self.extra_approvals)}


@dataclass
class CheckResult:
    notify: list[tuple[str, int]] = field(default_factory=list)       # (namespace, days before)
    entered_grace: list[str] = field(default_factory=list)
    open_delete: list[dict[str, Any]] = field(default_factory=list)   # facts for the delete request
    held: list[tuple[str, str]] = field(default_factory=list)         # (namespace, guard that held it)


class ExpirationRules:
    def __init__(self, raw: Mapping[str, Any], allowed_environments: set[str] | None = None):
        d = raw.get("defaults") or {}
        def check_enabled(entry: Mapping[str, Any]) -> None:
            if not isinstance(entry.get("enabled", True), bool):
                raise ValueError(f"expiration.yaml: enabled is true or false, not {entry['enabled']!r}")

        check_enabled(d)            # a wrong default stops the start even when no environment inherits it
        def mk(over: Mapping[str, Any]) -> EnvRules:
            v = {**d, **(over or {})}
            check_enabled(v)
            return EnvRules(enabled=v.get("enabled", True), allowed_at_create=v.get("allowedAtCreate", True),
                            max_extension_days=v.get("maxExtensionDays", 30),
                            max_lifetime_days=v.get("maxLifetimeDays", 180),
                            notify_days_before=tuple(sorted(v.get("notifyDaysBefore", [14, 7, 1]), reverse=True)),
                            grace_days=v.get("graceDays", 7),
                            delete_after_grace=v.get("deleteAfterGrace", True),
                            min_notices_before_delete=v.get("minNoticesBeforeDelete", 2))
        envs = raw.get("environments") or {}
        if allowed_environments is not None and set(envs) - allowed_environments:
            raise ValueError(f"expiration.yaml: environments not served: {sorted(set(envs) - allowed_environments)}")
        self.envs = {e: mk(v) for e, v in envs.items()}
        if "prod" in self.envs and self.envs["prod"].enabled:
            raise ValueError("expiration.yaml: prod takes only enabled: false; production namespaces never expire")

    @classmethod
    def load(cls, path: str | Path, allowed_environments: set[str] | None = None) -> "ExpirationRules":
        return cls(yaml.safe_load(Path(path).read_text()), allowed_environments)

    def rules(self, env: str) -> EnvRules:
        r = self.envs.get(env)
        if r is None or not r.enabled:
            raise Problem.unprocessable("expiration-not-allowed",
                                        f"Namespaces in {env} cannot carry expiration metadata")
        return r

    def allows(self, env: str) -> bool:
        return env in self.envs and self.envs[env].enabled

    def contract_view(self, environments: list[str]) -> dict[str, Any]:
        """x-cmapi-expiration of NamespaceCreate.expiresAt (#479, A11): each served environment's limits, so a client such
        as the portal reads them from the contract. An environment that takes no expiry is {"enabled": false} only."""
        out: dict[str, Any] = {}
        for env in environments:
            if not self.allows(env):
                out[env] = {"enabled": False}
                continue
            r = self.envs[env]
            out[env] = {"enabled": True, "allowedAtCreate": r.allowed_at_create, "maxLifetimeDays": r.max_lifetime_days,
                        "notifyDaysBefore": list(r.notify_days_before), "graceDays": r.grace_days}
        return {"environments": out}

    # ---- requests
    @staticmethod
    def _last_date(r: EnvRules) -> date:
        """The latest expiry date: its grace period must end by 9999-12-31, the last day a date holds, or GET /expirations
        cannot show graceEnds and answers 500 to everyone (#653)."""
        return date.max - timedelta(days=r.grace_days)

    def _lifetime(self, r: EnvRules, created: date, new_date: date, reasons: list[str]) -> tuple[str, ...]:
        if new_date > created + timedelta(days=r.max_lifetime_days):
            reasons.append(f"past {r.max_lifetime_days} days from creation")
            return ("approver-platform",)
        return ()

    def plan_create(self, env: str, expires_at: date | None, today: date) -> ExpiryPlan | None:
        if expires_at is None:
            return None                                   # permanent: the default
        r = self.rules(env)
        if not r.allowed_at_create:
            raise Problem.unprocessable("expiration-not-allowed", f"{env} does not take an expiry at create")
        if expires_at <= today:
            raise Problem.unprocessable("expiration-in-past", "The expiry must be after today")
        if expires_at > self._last_date(r):
            raise Problem.unprocessable("validation-failed", f"The expiry must be on or before {self._last_date(r)}")
        reasons: list[str] = []
        extra = self._lifetime(r, today, expires_at, reasons)
        return ExpiryPlan("create", expires_at, extra, tuple(reasons))

    def plan_extend(self, ns: ExpiryInfo, today: date, *, days: int | None = None,
                    until: date | None = None) -> ExpiryPlan:
        r = self.rules(ns.environment)
        if ns.expires_at is None:
            raise Problem.unprocessable("expiration-not-set", "The namespace is permanent; use :set")
        if (days is None) == (until is None):
            raise Problem.bad_request("validation-failed", "Send days or until, not both")
        base = max(ns.expires_at, today)
        # The step is checked before the date is moved: a count of days past date's range (timedelta holds 999999999 days,
        # date ends in 9999) is an OverflowError there, a 500 for the caller's number (#653).
        step = days if days is not None else (until - base).days
        if step <= 0:
            raise Problem.unprocessable("expiration-in-past", "The new date must be later than the current one")
        if step > r.max_extension_days:
            raise Problem.unprocessable("expiration-limit",
                                        f"One extension adds at most {r.max_extension_days} days",
                                        maxExtensionDays=r.max_extension_days)
        if step > (self._last_date(r) - base).days:
            raise Problem.unprocessable("validation-failed", f"The new date must be on or before {self._last_date(r)}")
        new = base + timedelta(days=step)
        reasons = [f"+{step} days"]
        return ExpiryPlan("extend", new, self._lifetime(r, ns.created, new, reasons), tuple(reasons))

    def plan_set(self, ns: ExpiryInfo, until: date, today: date) -> ExpiryPlan:
        r = self.rules(ns.environment)
        if ns.expires_at is not None:
            raise Problem.unprocessable("expiration-already-set", "Use :extend to move an existing date")
        if until <= today:
            raise Problem.unprocessable("expiration-in-past", "The expiry must be after today")
        if (until - today).days > r.max_extension_days:
            raise Problem.unprocessable("expiration-limit",
                                        f"A new date is at most {r.max_extension_days} days out")
        if until > self._last_date(r):
            raise Problem.unprocessable("validation-failed", f"The expiry must be on or before {self._last_date(r)}")
        reasons: list[str] = []
        return ExpiryPlan("set", until, self._lifetime(r, ns.created, until, reasons), tuple(reasons))

    def plan_make_permanent(self, ns: ExpiryInfo) -> ExpiryPlan:
        # Taken where expiration is off too (#479): it is how a date given while expiration was on is removed.
        if ns.expires_at is None:
            self.rules(ns.environment)                    # an environment that takes no expiry says so first, as before
            raise Problem.unprocessable("expiration-not-set", "The namespace is already permanent")
        return ExpiryPlan("makePermanent", None, ("approver-platform",), ("make permanent",))

    # ---- reads and the daily check
    def state(self, ns: ExpiryInfo, today: date) -> str:
        if ns.expires_at is None or not self.allows(ns.environment):
            return "permanent"
        r = self.rules(ns.environment)
        left = (ns.expires_at - today).days
        if left > max(r.notify_days_before, default=0):
            return "active"
        if left > 0:
            return "expiring"
        if -left < r.grace_days:
            return "grace"
        return "pending_delete"

    def expire_check(self, namespaces: list[ExpiryInfo], today: date) -> CheckResult:
        out = CheckResult()
        for ns in namespaces:
            st = self.state(ns, today)
            if st == "permanent":
                continue
            r = self.rules(ns.environment)
            left = (ns.expires_at - today).days        # type: ignore[operator]
            due = [d for d in r.notify_days_before if left <= d]
            if left > 0 and due and min(due) not in ns.notices_sent:
                out.notify.append((ns.namespace, min(due)))    # the nearest threshold only
            if left == 0:
                out.entered_grace.append(ns.namespace)
            if st == "pending_delete" and r.delete_after_grace:
                guard = self._delete_guard(ns, r, today)
                if guard:
                    out.held.append((ns.namespace, guard))
                else:
                    out.open_delete.append({
                        "plugin": "namespaces", "action": "delete", "reason": "expired",
                        "environment": ns.environment, "namespace": ns.namespace,
                        "openRequestOnNamespace": ns.open_request, "protected": ns.protected,
                        "noticesSent": len(ns.notices_sent),
                        "lastExtensionHoursAgo": None if ns.last_extension is None
                        else (today - ns.last_extension).days * 24})
        return out

    @staticmethod
    def _delete_guard(ns: ExpiryInfo, r: EnvRules, today: date) -> str | None:
        if ns.open_request:
            return "noOpenRequest"
        if ns.protected:
            return "notProtected"
        if ns.last_extension and (today - ns.last_extension).days < 1:
            return "noExtensionInLast24h"
        if len(ns.notices_sent) < r.min_notices_before_delete:
            return "noticesSentAtLeast2"
        return None
