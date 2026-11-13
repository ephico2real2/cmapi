"""Approval rules engine, auto-approval and the approval ledger (config/approval-rules.yaml).

decide(facts) turns a plan's facts into a Requirement, evaluated in this order:

1. The environment's count for the action kind (create, change, delete) and its approving group.
2. Namespace patterns, first match wins: waive the action kind, or raise the count and set the group.
   Skipped for an expiry delete (reason expired).
3. Thresholds: each `when:` that is true adds approvers (its group, or defaults.group).
4. Auto-approval: when the master switch is on, the kill switch is off, a policy matches and every
   fixed guard and the policy's own guards pass, the request is approved by auto:<policy>.

A Requirement is a list of slots, one per approving group, so "2 approver-prod + 1 approver-platform"
is expressible. The ledger fills slots one approver at a time and enforces eligibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping

import yaml

from cmapi.core.authz import DEFAULT_GROUP_PATH, group_path, permissions as builtin_permissions
from cmapi.core.errors import Problem
from cmapi.core.expression import Expression
from cmapi.core.identity.claims import Identity


def action_kind(action: str) -> str:
    return {"create": "create", "delete": "delete"}.get(action, "change")


@dataclass(frozen=True)
class Slot:
    group: str
    count: int
    reason: str


@dataclass(frozen=True)
class Requirement:
    rule: str                                  # e.g. "prod-delete"
    slots: tuple[Slot, ...]
    self_approval: bool
    timeout_hours: int
    reasons: tuple[str, ...]
    auto: str | None = None                    # auto:<policy>, or "none-required"
    auto_fallback: str | None = None           # the guard that stopped a matching policy
    # The instance's identity.groupPath when this was decided. Stored with the slots it names, like every other part of
    # a requirement, so a later config change does not move an open request's approvers under it.
    group_path: str = DEFAULT_GROUP_PATH

    @property
    def total(self) -> int:
        return sum(s.count for s in self.slots)

    def token_group(self, group: str) -> str:
        """The Keycloak group path a token carries for this approving group."""
        return group_path(group, self.group_path)

    @property
    def approved_at_plan(self) -> bool:
        return self.auto is not None


FIXED_GUARDS = ("delete", "rules-added-approvers", "capacity", "warnings", "team-allowance")
CAPACITY_PLUGINS = frozenset({"namespaces", "quotas"})   # their creates and changes need "fits" on fresh data
POLICY_GUARDS = {
    "noOpenRequest": lambda f: not f.get("openRequestOnNamespace", False),
    "notProtected": lambda f: not f.get("protected", False),
    "noExtensionInLast24h": lambda f: f.get("lastExtensionHoursAgo") is None or f["lastExtensionHoursAgo"] >= 24,
    "noticesSentAtLeast2": lambda f: f.get("noticesSent", 0) >= 2,
}


class ApprovalRules:
    def __init__(self, raw: Mapping[str, Any], allowed_environments: set[str] | None = None,
                 group_path: str = DEFAULT_GROUP_PATH):
        self.group_path = group_path
        self.defaults = {"required": 0, "group": "approver-platform", "timeoutHours": 24,
                         "selfApproval": False, **(raw.get("defaults") or {})}
        self.environments = {e: {**self.defaults, **(v or {})} for e, v in (raw.get("environments") or {}).items()}
        self.patterns = list(raw.get("namespacePatterns") or [])
        self.thresholds = [(Expression(t["when"]), t) for t in raw.get("thresholds") or []]
        self.protected = list((raw.get("protected") or {}).get("labels", []))
        auto = raw.get("autoApproval") or {}
        self.auto_enabled = bool(auto.get("enabled", False))
        self.max_per_team = int(auto.get("maxPerTeamPerDay", 20))
        self.policies = list(auto.get("policies") or [])
        problems = []
        if allowed_environments is not None:
            extra = set(self.environments) - allowed_environments
            if extra:
                problems.append(f"environments not served by this instance: {sorted(extra)}")
            for p in self.policies:
                envs = set(p.get("match", {}).get("environments", [])) - {"*"}
                if envs - allowed_environments and p.get("enabled", True):
                    # a combined reference file lists every environment; a deployed one may not
                    problems.append(f"policy {p['name']}: environments not served {sorted(envs - allowed_environments)}")
        for p in self.policies:
            for g in p.get("guards", []):
                if g not in POLICY_GUARDS:
                    problems.append(f"policy {p['name']}: unknown guard {g}")
        if problems:
            raise ValueError("invalid approval-rules.yaml: " + "; ".join(problems))

    @classmethod
    def load(cls, path: str | Path, allowed_environments: set[str] | None = None) -> "ApprovalRules":
        return cls(yaml.safe_load(Path(path).read_text()), allowed_environments)

    def tier_names(self) -> set[str]:
        return {t for p in self.policies for t in p.get("match", {}).get("tiers", [])}

    def is_protected(self, labels: Mapping[str, str]) -> bool:
        return any(labels.get(k) == v for k, _, v in (p.partition("=") for p in self.protected))

    # ---- decide
    def decide(self, facts: Mapping[str, Any], *, paused: bool = False,
               team_auto_today: int = 0) -> Requirement:
        env = facts["environment"]
        if env not in self.environments:
            raise Problem.unprocessable("environment-not-served", f"No approval rules for {env}")
        rule = self.environments[env]
        kind = action_kind(facts["action"])
        if kind == "delete" and facts.get("protected"):
            raise Problem.unprocessable("namespace-protected", "Protected namespaces cannot be deleted")
        count, group = int(rule.get(kind, rule["required"])), rule["group"]
        reasons = [f"{env} {kind}: {count} from {group}"]
        added = False
        if facts.get("reason") != "expired":
            for p in self.patterns:
                if fnmatchcase(facts.get("namespace") or "", p["match"]):
                    if kind in p.get("waive", []):
                        count = 0
                        reasons.append(f"waived by pattern {p['match']}: {p.get('reason', '')}".rstrip(": "))
                    if "required" in p:              # the pattern's group replaces the environment's
                        count, group, added = max(count, p["required"]), p.get("group", group), True
                        reasons.append(f"pattern {p['match']}: {count} from {group}")
                    break
        slots = [Slot(group, count, reasons[-1])] if count else []
        for expr, t in self.thresholds:
            if expr(facts):
                g = t.get("group", self.defaults["group"])
                slots.append(Slot(g, int(t.get("add", 1)), t.get("reason") or expr.source))
                reasons.append(f"threshold {expr.source}: +{t.get('add', 1)} {g}")
                added = True
        merged: dict[str, Slot] = {}
        for s in slots:
            m = merged.get(s.group)
            merged[s.group] = Slot(s.group, s.count + (m.count if m else 0),
                                   s.reason if not m else f"{m.reason}; {s.reason}")
        req = Requirement(rule=f"{env}-{kind}", slots=tuple(merged.values()),
                          self_approval=bool(rule.get("selfApproval")), timeout_hours=int(rule["timeoutHours"]),
                          reasons=tuple(reasons), group_path=self.group_path)
        policy, fallback = self._auto(facts, kind, added, paused, team_auto_today)
        if policy:
            return Requirement(req.rule, (), req.self_approval, req.timeout_hours,
                               req.reasons + (f"auto-approved by policy {policy}",), auto=f"auto:{policy}",
                               group_path=self.group_path)
        if not req.slots:
            return Requirement(req.rule, (), req.self_approval, req.timeout_hours, req.reasons,
                               auto="none-required", auto_fallback=fallback, group_path=self.group_path)
        return Requirement(req.rule, req.slots, req.self_approval, req.timeout_hours, req.reasons,
                           auto_fallback=fallback, group_path=self.group_path)

    def _auto(self, f: Mapping[str, Any], kind: str, added: bool, paused: bool,
              team_today: int) -> tuple[str | None, str | None]:
        if not self.auto_enabled:
            return None, None
        for p in self.policies:
            if not p.get("enabled", True) or not self._matches(p, f):
                continue
            if paused:                                  # the kill switch: recorded as the guard that stopped it
                return None, "paused"
            expiry_policy = p.get("match", {}).get("reason") == "expired"
            if kind == "delete" and not expiry_policy:
                return None, "delete"
            if added:
                return None, "rules-added-approvers"
            needs_capacity = f.get("plugin") in CAPACITY_PLUGINS and kind != "delete"
            if needs_capacity and not (f.get("capacity") == "fits" and f.get("capacityFresh") is True):
                return None, "capacity"
            if not needs_capacity and f.get("capacity") not in (None, "fits"):
                return None, "capacity"
            if f.get("warnings"):
                return None, "warnings"
            if team_today >= self.max_per_team:
                return None, "team-allowance"
            for g in p.get("guards", []):
                if not POLICY_GUARDS[g](f):
                    return None, g
            return p["name"], None
        return None, None

    @staticmethod
    def _matches(p: Mapping[str, Any], f: Mapping[str, Any]) -> bool:
        m = p.get("match", {})
        def any_of(key: str, value: Any) -> bool:
            allowed = m.get(key)
            return allowed is None or "*" in allowed or value in allowed
        if m.get("plugin") and m["plugin"] != f.get("plugin"):
            return False
        if not (any_of("actions", f.get("action")) and any_of("environments", f.get("environment"))
                and any_of("tiers", f.get("tier"))):
            return False
        if "reason" in m and m["reason"] != f.get("reason"):
            return False
        if "keyClasses" in m and not set(f.get("keyClasses", [])) <= set(m["keyClasses"]):
            return False
        if "clusterRoles" in m and not set(f.get("clusterRoles", [])) <= set(m["clusterRoles"]):
            return False
        clients = (p.get("requester") or {}).get("clients")
        if clients and f.get("requesterClient") not in clients:
            return False
        want = (m.get("clusterSelector") or {}).get("matchLabels", {})
        labels = f.get("clusterLabels", {})
        return all(labels.get(k) == v for k, v in want.items())


# ---------------------------------------------------------------------------- the ledger


@dataclass
class ApprovalLedger:
    """Who has approved one request. Persisted as approvals rows.

    Slots are not claimed first come, first served: an approver in two approving groups would
    otherwise block a later approver who fits only one. Each approve re-solves the assignment of
    approvers to slots (bipartite matching), so a person counts wherever they are needed most.
    """
    requirement: Requirement
    requester_sub: str                         # the person the request is for (Requester.sub)
    operation_starter_sub: str | None = None
    client_owner_subs: frozenset[str] = frozenset()
    entries: list[dict[str, Any]] = field(default_factory=list)

    def _seats(self) -> list[str]:
        return [s.group for s in self.requirement.slots for _ in range(s.count)]

    def _assign(self, people: list[dict[str, Any]]) -> dict[int, int]:
        """seat index -> person index, maximum matching (people are few)."""
        seats, match = self._seats(), {}
        def try_person(pi: int, seen: set[int]) -> bool:
            for si, group in enumerate(seats):
                if si in seen or self.requirement.token_group(group) not in people[pi]["groups"]:
                    continue
                seen.add(si)
                if si not in match or try_person(match[si], seen):
                    match[si] = pi
                    return True
            return False
        for pi in range(len(people)):
            try_person(pi, set())
        return match

    @property
    def met(self) -> bool:
        return len(self._assign(self.entries)) == len(self._seats())

    def counted_for(self) -> dict[str, str]:
        """approver sub -> the approving group whose slot the approval fills now.

        Each approve solves the assignment again, so an earlier approval can move to another slot when a later one arrives.
        The caller stores the whole answer after each approval; the answer at the last approval is the final one."""
        seats = self._seats()
        return {self.entries[pi]["sub"]: seats[si] for si, pi in self._assign(self.entries).items()}

    def remaining(self) -> list[dict[str, Any]]:
        seats, taken = self._seats(), self._assign(self.entries)
        need: dict[str, int] = {}
        for si, g in enumerate(seats):
            if si not in taken:
                need[g] = need.get(g, 0) + 1
        return [{"group": g, "needed": n} for g, n in need.items()]

    def approve(self, approver: Identity, *, permitted: bool | None = None, relay: Identity | None = None,
                relay_permitted: bool | None = None, comment: str = "") -> bool:
        """approver is the eligible person; relay is the channel client (approvals:relay) if any.

        permitted / relay_permitted: whether the instance's role policy grants requests:approve (in
        this request's environment) and approvals:relay. None falls back to the built-in roles.
        """
        if relay is not None:
            ok = relay_permitted if relay_permitted is not None else "approvals:relay" in builtin_permissions(relay)
            if not ok:
                raise Problem.forbidden("Relay client lacks approvals:relay")
        ok = permitted if permitted is not None else "requests:approve" in builtin_permissions(approver)
        if not ok:
            raise Problem.forbidden("Missing permission requests:approve for this environment")
        if approver.sub in {e["sub"] for e in self.entries}:
            raise Problem.conflict("already-approved", "This person already approved the request")
        if approver.sub in self.client_owner_subs or approver.sub == self.operation_starter_sub:
            raise Problem.conflict("self-approval", "The operation starter or client owner cannot approve")
        if approver.sub == self.requester_sub and not self.requirement.self_approval:
            raise Problem.conflict("self-approval", "Requesters cannot approve their own request here")
        entry = {"sub": approver.sub, "username": approver.username, "groups": frozenset(approver.groups),
                 "comment": comment, "relayedBy": relay.client_id if relay else None}
        if len(self._assign(self.entries + [entry])) <= len(self._assign(self.entries)):
            raise Problem.forbidden(f"Not in an approving group still needed: "
                                    f"{[r['group'] for r in self.remaining()]}", code="not-eligible")
        self.entries.append(entry)
        return self.met

