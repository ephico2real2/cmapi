"""cmapi's refusals before Git, stored for the Policies tab (#302; table policy_rejections, migration 0006).

A plan that cmapi refuses never becomes a request, so before #302 it left only a metric. Three things are stored now:

- `refused`, stage `plan`: a write that cmapi refused with one of RECORDED, with no request. The router wraps each plan
  in `refusals()`; the row is written in its own transaction, and a failed write is logged and counted, never turned into
  another answer than the 422 itself. A dry run is counted in cmapi_plan_refusals_total only: the portal's forms dry-run
  as a person types, and their drafts are not refusals.
- `warned`, stage `plan`: Kyverno's findings on a plan that went on to a request (audit mode), written with the request in
  its transaction.
- `refused`, stage `ci`: the worker's checks that failed a pull request, with the request.

What a row holds of the person is the username, and whether the call was automated: never the email, the employee ID or
the justification (the owner, 2026-11-17). The same refusal again on the same UTC day adds to `count` (ON CONFLICT on the
fingerprint and the day), so a retried POST does not fill the table, and a row keeps its place in the list, which is in
the order of `first_at`.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Mapping, Sequence

from sqlalchemy import Date, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from cmapi.core.db.models import PolicyRejectionRow
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.observability import PLAN_REFUSALS, REJECTIONS_UNRECORDED, log
from cmapi.core.pipeline import CMAPI_REFUSALS

# The refusals that are a verdict on what was asked (design B, D8). Not stored: 409, 412 and 428 (concurrency), 403
# (authorization, which the audit log has), 503 (no verdict), and capacity-exceeded, which is the Capacity tab's.
RECORDED = frozenset({"policy-violation", *CMAPI_REFUSALS})
MAX_FINDINGS = 20
MESSAGE_MAX = 300
LIST_CAP = 10_000            # the newest rows that one list reads; past it the answer says `truncated`


def _finding(source: str, policy: str, rule: str | None, path: str | None, severity: str, message: str,
             kyverno_rule: str | None = None) -> dict[str, Any]:
    return {"source": source, "policy": policy, "rule": rule, "kyvernoRule": kyverno_rule, "path": path or None,
            "severity": severity, "message": (message or "")[:MESSAGE_MAX]}


def _check_rule(index: Mapping[str, Mapping[str, Any]], policy: str, kyverno_rule: str | None) -> str | None:
    """The rule to show: index.json's rule of a rendered policy (`max`, `pattern`), else Kyverno's own rule."""
    return (index.get(policy) or {}).get("rule") or kyverno_rule


def findings_of(problem: Problem, index: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The findings of a refusal: each error, then each finding beside them (Kyverno's warnings in audit mode)."""
    out: list[dict[str, Any]] = []
    for e in problem.errors:
        if "source" in e:                                   # an error of the validator (enforce mode)
            policy, kyverno_rule = str(e.get("code") or ""), e.get("kyvernoRule")
            out.append(_finding(e["source"], policy, _check_rule(index, policy, kyverno_rule), e.get("path"), "error",
                                str(e.get("detail") or ""), kyverno_rule))
        else:                                               # cmapi's own metadata check
            key, kind = e.get("key"), e.get("kind")
            path = f"{kind}s/{key}" if key and kind else key
            out.append(_finding("cmapi", "metadata-keys", str(e.get("code") or ""), path, "error",
                                str(e.get("detail") or str(e.get("code") or "").replace("_", " "))))
    if not problem.errors:
        out.append(_finding("cmapi", problem.code, None, None, "error", problem.detail))
    for f in problem.extra.get("findings") or []:
        out.append(_finding(f["source"], f["rule"], _check_rule(index, f["rule"], f.get("kyvernoRule")), f.get("path"),
                            f.get("severity") or "warning", f.get("message") or "", f.get("kyvernoRule")))
    return out[:MAX_FINDINGS]


def _fingerprint(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class RejectionRepo:
    def __init__(self, session: Session):
        self.s = session

    def record(self, *, stage: str, outcome: str, problem: str | None, cluster_id: str, env: str, namespace: str,
               plugin: str, action: str, request_id: str | None, username: str, automated: bool,
               findings: Sequence[Mapping[str, Any]]) -> int:
        """One refusal: a new row, or `count` + 1 on the row of the same refusal this UTC day. Returns the row's id."""
        findings = [dict(f) for f in findings][:MAX_FINDINGS]
        fp = _fingerprint(username, stage, outcome, problem, cluster_id, namespace, plugin, action, request_id,
                          sorted(json.dumps(f, sort_keys=True) for f in findings))
        table = PolicyRejectionRow.__table__
        stmt = insert(table).values(
            day=cast(func.timezone("UTC", func.now()), Date), stage=stage, outcome=outcome, problem=problem,
            cluster_id=cluster_id, env=env, namespace=namespace[:63], plugin=plugin, action=action, request_id=request_id,
            username=username[:100], automated=automated, findings=findings, fingerprint=fp)
        stmt = stmt.on_conflict_do_update(index_elements=["fingerprint", "day"],
                                          set_={"count": table.c.count + 1, "last_at": func.now()}).returning(table.c.id)
        return int(self.s.execute(stmt).scalar_one())

    def since(self, envs: Sequence[str], cutoff: datetime) -> tuple[list[PolicyRejectionRow], bool]:
        """The rows of the environments seen since the cutoff, newest first, at most LIST_CAP, and whether more exist."""
        if not envs:
            return [], False
        q = (select(PolicyRejectionRow).where(PolicyRejectionRow.env.in_(list(envs)), PolicyRejectionRow.last_at >= cutoff)
             .order_by(PolicyRejectionRow.first_at.desc(), PolicyRejectionRow.id.desc()).limit(LIST_CAP + 1))
        rows = list(self.s.scalars(q))
        return rows[:LIST_CAP], len(rows) > LIST_CAP

    def prune(self, days: int) -> int:
        """Deletes the rows last seen more than `days` days ago. Returns how many."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return self.s.execute(delete(PolicyRejectionRow).where(PolicyRejectionRow.last_at < cutoff)).rowcount or 0


def is_automated(who: Identity, automation_roles: Sequence[str]) -> bool:
    """A service client, or an account with an automation role: the same rule as resolve_requester (core/identity/checks.py)."""
    return who.kind == "service" or bool(set(automation_roles) & set(who.roles))


@contextmanager
def refusals(c: Any, who: Identity, cluster_id: str, namespace: str, action: str, *, dry_run: bool,
             plugin: str = "namespaces") -> Iterator[None]:
    """Stores a refusal of RECORDED raised inside the block, then raises it unchanged. `c` is the AppContext."""
    try:
        yield
    except Problem as exc:
        if exc.status == 422 and exc.code in RECORDED:
            PLAN_REFUSALS.labels(exc.code, "true" if dry_run else "false").inc()
            if not dry_run:
                _store_refusal(c, who, cluster_id, namespace, action, plugin, exc)
        raise


def _store_refusal(c: Any, who: Identity, cluster_id: str, namespace: str, action: str, plugin: str, exc: Problem) -> None:
    try:
        env = c.registry.get(cluster_id).environment
        if env is None:                       # a cluster with no clusters.yaml entry is refused before any check of the body
            return
        automation = c.cfg.raw_instance["instance"].get("identity", {}).get("automationRoles", ["cmapi-onboarding"])
        with c.db.session() as s:
            RejectionRepo(s).record(stage="plan", outcome="refused", problem=exc.code, cluster_id=cluster_id, env=env,
                                    namespace=namespace, plugin=plugin, action=action, request_id=None,
                                    username=who.username, automated=is_automated(who, automation),
                                    findings=findings_of(exc, c.bundle.index if c.bundle else {}))
    except Exception as err:                  # noqa: BLE001 - the caller's answer is the refusal, whatever happens here
        REJECTIONS_UNRECORDED.labels("plan").inc()
        log.warning("rejection_not_recorded", cluster_id=cluster_id, namespace=namespace, code=exc.code,
                    error=f"{type(err).__name__}: {str(err)[:200]}")


def _in_savepoint(s: Session, stage: str, write: Any) -> None:
    """A write in the caller's transaction, under a savepoint: a failure is logged and counted, and the caller's
    transaction (the request's submit, the CI job) goes on as if the row had not been asked for."""
    try:
        with s.begin_nested():
            write()
    except Exception as err:                  # noqa: BLE001 - the request or the job must not depend on this row
        REJECTIONS_UNRECORDED.labels(stage).inc()
        log.warning("rejection_not_recorded", stage=stage, error=f"{type(err).__name__}: {str(err)[:200]}")


def record_warned(s: Session, c: Any, plan: Any, request_id: str) -> None:
    """Kyverno's findings on a plan that became a request, in the request's transaction (audit mode's warnings)."""
    index = c.bundle.index if c.bundle else {}
    warned = [f for f in plan.findings if f.source == "kyverno" and f.severity == "warning"]
    if not warned:
        return
    findings = [_finding(f.source, f.rule, _check_rule(index, f.rule, f.kyverno_rule), f.path, f.severity, f.message,
                         f.kyverno_rule) for f in warned]
    _in_savepoint(s, "plan", lambda: RejectionRepo(s).record(
        stage="plan", outcome="warned", problem=None, cluster_id=plan.cluster_id, env=plan.env, namespace=plan.namespace,
        plugin=plan.plugin, action=plan.reason or plan.action, request_id=request_id, username=plan.requester.username,
        automated=plan.requester.automated, findings=findings))


def record_ci(s: Session, c: Any, row: Any, errors: Sequence[Any], extra: Sequence[Mapping[str, Any]]) -> None:
    """The checks that failed a pull request, in the job's transaction: the validator's errors, then `extra` (the cmapi
    check, the host's CI contexts)."""
    index = c.bundle.index if c.bundle else {}
    findings = [_finding(f.source, f.rule, _check_rule(index, f.rule, f.kyverno_rule), f.path, "error", f.message,
                         f.kyverno_rule) for f in errors]
    findings += [dict(f) for f in extra]
    _in_savepoint(s, "ci", lambda: RejectionRepo(s).record(
        stage="ci", outcome="refused", problem=None, cluster_id=row.cluster_id, env=row.env, namespace=row.namespace,
        plugin=row.plugin, action=row.reason or row.action, request_id=row.request_id, username=row.requester_username,
        automated=bool((row.requester or {}).get("automated")), findings=findings))


__all__ = ["RECORDED", "RejectionRepo", "findings_of", "is_automated", "record_ci", "record_warned", "refusals"]
