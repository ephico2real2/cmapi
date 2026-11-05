"""Expiration rules (config/expiration.yaml) and the daily expire_check decisions.

Optional, and never in prod: an environment with no entry in expiration.yaml refuses every expiry
field with 422 expiration-not-allowed. Within limits an extension follows the environment's change
rule; past maxLifetimeDays from creation, or :makePermanent, adds platform-leads. A single
extension longer than maxExtensionDays is refused (expiration-limit).

States (GET /api/v1/expirations?state=):
    permanent       no expiry
    active          expiry further away than the first notice
    expiring        within the first notice (14 days), before the date
    grace           from the date for graceDays (7: the date and the 6 days after); still running
                    and extendable
    pending_delete  grace is over; the expired-namespace delete is due or open

Notices: on each run the nearest threshold at or above the days left is sent if it has not been,
so a short expiry still gets its 1-day notice and a missed run never sends a stale 14-day one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

import yaml

from cmapi.core.errors import Problem


@dataclass(frozen=True)
class EnvRules:
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
        def mk(over: Mapping[str, Any]) -> EnvRules:
            v = {**d, **(over or {})}
            return EnvRules(allowed_at_create=v.get("allowedAtCreate", True),
                            max_extension_days=v.get("maxExtensionDays", 30),
                            max_lifetime_days=v.get("maxLifetimeDays", 180),
                            notify_days_before=tuple(sorted(v.get("notifyDaysBefore", [14, 7, 1]), reverse=True)),
                            grace_days=v.get("graceDays", 7),
                            delete_after_grace=v.get("deleteAfterGrace", True),
                            min_notices_before_delete=v.get("minNoticesBeforeDelete", 2))
        envs = raw.get("environments") or {}
        if "prod" in envs:
            raise ValueError("expiration.yaml: prod cannot have an entry; production namespaces never expire")
        if allowed_environments is not None and set(envs) - allowed_environments:
            raise ValueError(f"expiration.yaml: environments not served: {sorted(set(envs) - allowed_environments)}")
        self.envs = {e: mk(v) for e, v in envs.items()}

    @classmethod
    def load(cls, path: str | Path, allowed_environments: set[str] | None = None) -> "ExpirationRules":
        return cls(yaml.safe_load(Path(path).read_text()), allowed_environments)

    def rules(self, env: str) -> EnvRules:
        r = self.envs.get(env)
        if r is None:
            raise Problem.unprocessable("expiration-not-allowed",
                                        f"Namespaces in {env} cannot carry expiration metadata")
        return r

    def allows(self, env: str) -> bool:
        return env in self.envs

    # ---- requests
    def _lifetime(self, r: EnvRules, created: date, new_date: date, reasons: list[str]) -> tuple[str, ...]:
        if new_date > created + timedelta(days=r.max_lifetime_days):
            reasons.append(f"past {r.max_lifetime_days} days from creation")
            return ("platform-leads",)
        return ()

    def plan_create(self, env: str, expires_at: date | None, today: date) -> ExpiryPlan | None:
        if expires_at is None:
            return None                                   # permanent: the default
        r = self.rules(env)
        if not r.allowed_at_create:
            raise Problem.unprocessable("expiration-not-allowed", f"{env} does not take an expiry at create")
        if expires_at <= today:
            raise Problem.unprocessable("expiration-in-past", "The expiry must be after today")
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
        new = base + timedelta(days=days) if days is not None else until
        step = (new - base).days
        if step <= 0:
            raise Problem.unprocessable("expiration-in-past", "The new date must be later than the current one")
        if step > r.max_extension_days:
            raise Problem.unprocessable("expiration-limit",
                                        f"One extension adds at most {r.max_extension_days} days",
                                        maxExtensionDays=r.max_extension_days)
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
        reasons: list[str] = []
        return ExpiryPlan("set", until, self._lifetime(r, ns.created, until, reasons), tuple(reasons))

    def plan_make_permanent(self, ns: ExpiryInfo) -> ExpiryPlan:
        self.rules(ns.environment)
        if ns.expires_at is None:
            raise Problem.unprocessable("expiration-not-set", "The namespace is already permanent")
        return ExpiryPlan("makePermanent", None, ("platform-leads",), ("make permanent",))

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
