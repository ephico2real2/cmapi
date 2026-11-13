"""Repositories: how the pipeline, the routers and the worker read and write the cmapi schema.

Every state change of a request goes through RequestRepo.move(), which applies the lifecycle
table (core/lifecycle.py) and writes the request_events row in the same transaction. The
namespace lock is the partial unique index uq_cr_open_namespace: a second open request for the
same namespace fails the INSERT, which move() turns into 409 change-pending.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from cmapi.core.approvals import ApprovalLedger, Requirement, Slot
from cmapi.core.authz import LEGACY_GROUP_PATH
from cmapi.core.db.models import (ApprovalRow, AuditEventRow, ChangeRequestRow, JobRow, JwksRow, OPEN_STATES,
                                  RequestEventRow, SwitchRow)
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.lifecycle import Event as E, State as S, transition


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def requirement_to_json(r: Requirement | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {"rule": r.rule, "slots": [asdict(s) for s in r.slots], "selfApproval": r.self_approval,
            "timeoutHours": r.timeout_hours, "reasons": list(r.reasons), "auto": r.auto,
            "autoFallback": r.auto_fallback, "groupPath": r.group_path}


def requirement_from_json(d: Mapping[str, Any] | None) -> Requirement | None:
    if d is None:
        return None
    return Requirement(rule=d["rule"], slots=tuple(Slot(**s) for s in d["slots"]), self_approval=d["selfApproval"],
                       timeout_hours=d["timeoutHours"], reasons=tuple(d["reasons"]), auto=d.get("auto"),
                       auto_fallback=d.get("autoFallback"), group_path=d.get("groupPath", LEGACY_GROUP_PATH))


IDEMPOTENCY_HOURS = 24      # how long an Idempotency-Key returns its first response (docs/02, API contract)


class LeaseLost(RuntimeError):
    """A job's lease was claimed by another worker while this one ran it: its transaction must not commit."""


def fingerprint(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class RequestRepo:
    def __init__(self, session: Session):
        self.s = session

    # ---- reads
    def get(self, request_id: str) -> ChangeRequestRow:
        row = self.s.get(ChangeRequestRow, request_id)
        if row is None:
            raise Problem(404, "object-not-found", f"No request {request_id}")
        return row

    def get_for_update(self, request_id: str) -> ChangeRequestRow:
        """The row, locked until this transaction ends: what a decision reads before it counts anything."""
        row = self.s.get(ChangeRequestRow, request_id, with_for_update=True, populate_existing=True)
        if row is None:
            raise Problem(404, "object-not-found", f"No request {request_id}")
        return row

    def events(self, request_id: str) -> list[RequestEventRow]:
        return list(self.s.scalars(select(RequestEventRow).where(RequestEventRow.request_id == request_id)
                                   .order_by(RequestEventRow.id)))

    def approvals(self, request_id: str) -> list[ApprovalRow]:
        return list(self.s.scalars(select(ApprovalRow).where(ApprovalRow.request_id == request_id)
                                   .order_by(ApprovalRow.id)))

    def list(self, *, status: str | None = None, cluster_id: str | None = None, namespace: str | None = None,
             requested_by: str | None = None, envs: Iterable[str] | None = None, open_: bool | None = None,
             limit: int = 5000) -> list[ChangeRequestRow]:
        q = select(ChangeRequestRow)
        if open_ is not None:           # open: a state that still holds the namespace's lock (OPEN_STATES); closed: every other state
            q = q.where(ChangeRequestRow.status.in_(OPEN_STATES) if open_ else ChangeRequestRow.status.not_in(OPEN_STATES))
        if status:
            q = q.where(ChangeRequestRow.status == status)
        if cluster_id:
            q = q.where(ChangeRequestRow.cluster_id == cluster_id)
        if namespace:
            q = q.where(ChangeRequestRow.namespace == namespace)
        if requested_by:
            q = q.where(ChangeRequestRow.requester_username == requested_by)
        if envs is not None:
            q = q.where(ChangeRequestRow.env.in_(list(envs)))
        # the plan holds every rendered file: load it only for the rows a page actually shows
        return list(self.s.scalars(q.options(defer(ChangeRequestRow.plan)).order_by(ChangeRequestRow.created_at.desc()).limit(limit)))

    def open_for(self, cluster_id: str, namespace: str) -> ChangeRequestRow | None:
        return self.s.scalars(select(ChangeRequestRow).where(ChangeRequestRow.cluster_id == cluster_id,
                                                            ChangeRequestRow.namespace == namespace,
                                                            ChangeRequestRow.status.in_(OPEN_STATES))).first()

    def open_namespaces(self, cluster_id: str | None = None) -> dict[tuple[str, str], str]:
        q = select(ChangeRequestRow.cluster_id, ChangeRequestRow.namespace, ChangeRequestRow.request_id) \
            .where(ChangeRequestRow.status.in_(OPEN_STATES))
        if cluster_id:
            q = q.where(ChangeRequestRow.cluster_id == cluster_id)
        return {(c, n): r for c, n, r in self.s.execute(q)}

    def by_idempotency(self, requester_sub: str, key: str) -> ChangeRequestRow | None:
        """The caller's request for this key, if the key is still held. A key is held for IDEMPOTENCY_HOURS (docs/02) from
        the request's creation, by the database's clock and not a pod's. Past that the key and its fingerprint are cleared
        here, in the caller's transaction, so the unique index on (requester_sub, idempotency_key) lets the key be used again."""
        self.s.execute(update(ChangeRequestRow)
                       .where(ChangeRequestRow.requester_sub == requester_sub, ChangeRequestRow.idempotency_key == key,
                              ChangeRequestRow.created_at < func.now() - text(f"interval '{IDEMPOTENCY_HOURS} hours'"))
                       .values(idempotency_key=None, idempotency_fingerprint=None, updated_at=ChangeRequestRow.updated_at))
        return self.s.scalars(select(ChangeRequestRow).where(ChangeRequestRow.requester_sub == requester_sub,
                                                            ChangeRequestRow.idempotency_key == key)).first()

    def auto_approvals_today(self, team: str) -> int:
        start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.s.scalar(select(func.count()).select_from(ChangeRequestRow).where(
            ChangeRequestRow.team == team, ChangeRequestRow.created_at >= start,
            ChangeRequestRow.requirement["auto"].astext.like("auto:%"))) or 0

    def in_states(self, states: Iterable[str]) -> list[ChangeRequestRow]:
        return list(self.s.scalars(select(ChangeRequestRow).where(ChangeRequestRow.status.in_(list(states)))))

    def next_id(self, today: datetime | None = None) -> str:
        """req-YYYYMMDD-NNNN, the next number for the day (under the day's advisory lock)."""
        day = (today or utcnow()).strftime("%Y%m%d")
        self.s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int(day)})
        prefix = f"req-{day}-"
        last = self.s.scalar(select(func.max(ChangeRequestRow.request_id)).where(
            ChangeRequestRow.request_id.like(prefix + "%")))
        n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
        return f"{prefix}{n:04d}"

    # ---- writes
    def insert(self, row: ChangeRequestRow, first_event: E, by: str, note: str = "") -> ChangeRequestRow:
        t = transition(None, first_event)
        row.status = t.after.value
        if t.after is S.APPROVED:
            row.approved_at = utcnow()
        self.s.add(row)
        try:
            self.s.flush()
        except IntegrityError as exc:
            self.s.rollback()
            if "uq_cr_open_namespace" in str(exc.orig):
                holder = self.open_for(row.cluster_id, row.namespace)
                raise Problem.conflict("change-pending", f"{holder.request_id if holder else 'another request'} holds "
                                       f"{row.namespace}", requestId=holder.request_id if holder else None) from exc
            if "uq_cr_idempotency" in str(exc.orig):
                raise Problem.conflict("idempotency-replay", "Idempotency-Key is in use for another request") from exc
            raise
        self.event(row, first_event.value, by, note)
        return row

    def event(self, row: ChangeRequestRow, event: str, by: str, note: str = "", detail: Mapping[str, Any] | None = None) -> None:
        self.s.add(RequestEventRow(request_id=row.request_id, event=event, status=row.status, by=by, note=note,
                                   detail=dict(detail) if detail else None))
        row.updated_at = utcnow()

    def move(self, row: ChangeRequestRow, event: E, by: str, note: str = "", **kw: Any) -> S:
        """Apply one lifecycle event; the lock is the unique index, re-checked when the state re-acquires it.

        The state is re-read under a row lock first. Without it two writers each move from the state they
        read earlier and the last commit wins: a rejected request becomes approved, a cancelled one pr_open."""
        self.s.refresh(row, attribute_names=["status"], with_for_update=True)
        before = S(row.status)
        t = transition(before, event, **kw)
        if t.acquires_lock:
            holder = self.open_for(row.cluster_id, row.namespace)
            if holder is not None and holder.request_id != row.request_id:
                raise Problem.conflict("change-pending", f"{holder.request_id} holds {row.namespace}",
                                       requestId=holder.request_id)
        row.status = t.after.value
        now = utcnow()
        if t.after is S.APPROVED:
            row.approved_at = now
        if t.after is S.MERGED:
            row.merged_at = now
        if t.after in (S.SYNCED, S.REJECTED, S.CANCELLED, S.TIMEOUT, S.FAILED, S.SUPERSEDED, S.REVERTED, S.SYNC_FAILED):
            row.finished_at = now
        try:
            self.s.flush()
        except IntegrityError as exc:
            self.s.rollback()
            raise Problem.conflict("change-pending", f"another request holds {row.namespace}") from exc
        self.event(row, event.value, by, note)
        return t.after

    def ledger(self, row: ChangeRequestRow) -> ApprovalLedger | None:
        req = requirement_from_json(row.requirement)
        if req is None or not req.slots:
            return None
        # Who filed it for someone else is a second identity on the request: under a no-self-approval
        # rule that identity may not approve it either.
        submitter = (row.requester or {}).get("submittedBySub")
        ledger = ApprovalLedger(req, requester_sub=row.requester_sub,
                                operation_starter_sub=None if req.self_approval else submitter)
        for a in self.approvals(row.request_id):
            ledger.entries.append({"sub": a.approver_sub, "username": a.username, "groups": frozenset(a.groups),
                                   "comment": a.comment, "relayedBy": a.relayed_by, "at": a.at})
        return ledger

    def record_approval(self, row: ChangeRequestRow, who: Identity, comment: str, relayed_by: str | None,
                        counted_for: Mapping[str, str]) -> None:
        """`counted_for` is ApprovalLedger.counted_for() after this approval: each approval of the request gets its slot's
        group, because a new approval can move an earlier one to another slot."""
        self.s.add(ApprovalRow(request_id=row.request_id, approver_sub=who.sub, username=who.username,
                               groups=sorted(who.groups), comment=comment, relayed_by=relayed_by))
        self.s.flush()
        for a in self.approvals(row.request_id):
            a.counted_for = counted_for.get(a.approver_sub)
        self.event(row, "approval", who.username, comment)


class JobRepo:
    def __init__(self, session: Session):
        self.s = session

    def enqueue(self, kind: str, *, request_id: str | None = None, cluster_id: str = "", delay: float = 0,
                payload: Mapping[str, Any] | None = None) -> JobRow | None:
        """At most one pending job per (kind, request): a duplicate is a no-op, not an error."""
        job = JobRow(kind=kind, request_id=request_id, cluster_id=cluster_id, payload=dict(payload) if payload else None,
                     run_after=utcnow() + timedelta(seconds=delay))
        try:
            with self.s.begin_nested():
                self.s.add(job)
                self.s.flush()
        except IntegrityError:
            return None
        return job

    def claim(self, worker_id: str, lease_seconds: int = 300) -> JobRow | None:
        now = utcnow()
        due = select(JobRow.job_id).where(JobRow.done_at.is_(None), JobRow.run_after <= now,
                                          or_(JobRow.locked_until.is_(None), JobRow.locked_until < now)) \
            .order_by(JobRow.run_after).limit(1).with_for_update(skip_locked=True)
        job_id = self.s.scalar(due)
        if job_id is None:
            return None
        self.s.execute(update(JobRow).where(JobRow.job_id == job_id).values(
            locked_until=now + timedelta(seconds=lease_seconds), locked_by=worker_id, attempts=JobRow.attempts + 1,
            lease_generation=JobRow.lease_generation + 1))
        return self.s.get(JobRow, job_id, populate_existing=True)

    def assert_lease(self, job_id: int, worker_id: str, generation: int) -> None:
        """The fencing check a worker runs in its job transaction before committing: the row, locked, must still
        carry this worker's claim. A later claim (after a lease expired under a paused worker) has a higher
        generation, and the stale worker's whole transaction is rolled back by raising."""
        row = self.s.execute(text("SELECT locked_by, lease_generation FROM jobs WHERE job_id = :id FOR UPDATE"),
                             {"id": job_id}).one_or_none()
        if row is None or row[0] != worker_id or row[1] != generation:
            raise LeaseLost(f"job {job_id}: lease generation {generation} of {worker_id} was superseded by "
                            f"{row[1] if row else 'none'} ({row[0] if row else 'no row'})")

    def fence(self) -> None:
        """Call before a side effect a rollback cannot undo (a merge, a close, a delete). Refuses a stale worker, and
        keeps the job's row locked until this transaction ends, so nobody can claim it while the side effect runs."""
        lease = self.s.info.get("lease")
        if lease:
            self.assert_lease(*lease)

    def done(self, job: JobRow) -> None:
        job.done_at = utcnow()
        job.locked_until = None

    def retry(self, job: JobRow, error: str, delay: float) -> None:
        job.last_error = error[:2000]
        job.run_after = utcnow() + timedelta(seconds=delay)
        job.locked_until = None

    def oldest_due_seconds(self) -> float:
        """Age of the oldest job a live worker would already have claimed; 0 when there is none."""
        now = utcnow()
        oldest = self.s.scalar(select(func.min(JobRow.run_after)).where(
            JobRow.done_at.is_(None), JobRow.run_after <= now, or_(JobRow.locked_until.is_(None), JobRow.locked_until < now)))
        return (now - oldest).total_seconds() if oldest else 0.0

    def pending_counts(self) -> dict[str, int]:
        q = select(JobRow.kind, func.count()).where(JobRow.done_at.is_(None)).group_by(JobRow.kind)
        return {k: n for k, n in self.s.execute(q)}

    def pending(self, kind: str, request_id: str | None = None) -> JobRow | None:
        return self.s.scalars(select(JobRow).where(JobRow.kind == kind, JobRow.done_at.is_(None),
                                                   JobRow.request_id == request_id)).first()


class AuditRepo:
    def __init__(self, session: Session):
        self.s = session

    def record(self, actor: Identity, action: str, target: str, detail: Mapping[str, Any] | None = None) -> None:
        self.s.add(AuditEventRow(actor_sub=actor.sub, actor_username=actor.username, actor_client=actor.client_id,
                                 action=action, target=target, detail=dict(detail) if detail else None))

    def recent(self, limit: int = 200) -> list[AuditEventRow]:
        return list(self.s.scalars(select(AuditEventRow).order_by(AuditEventRow.id.desc()).limit(limit)))


class SwitchRepo:
    def __init__(self, session: Session):
        self.s = session

    def get(self, name: str) -> dict[str, Any] | None:
        row = self.s.get(SwitchRow, name)
        return None if row is None else {**row.value, "setBy": row.set_by, "setAt": row.set_at.isoformat()}

    def set(self, name: str, value: Mapping[str, Any], by: str) -> None:
        row = self.s.get(SwitchRow, name)
        if row is None:
            self.s.add(SwitchRow(name=name, value=dict(value), set_by=by))
        else:
            row.value, row.set_by, row.set_at = dict(value), by, utcnow()


class DbKeyStore:
    """KeyStore for core/auth.py: the last good JWKS, per issuer."""

    def __init__(self, db: Any):
        self.db = db

    def load(self, issuer: str) -> list[dict[str, Any]] | None:
        with self.db.session() as s:
            row = s.get(JwksRow, issuer)
            return None if row is None else list(row.keys)

    def save(self, issuer: str, keys: list[dict[str, Any]]) -> None:
        with self.db.session() as s:
            row = s.get(JwksRow, issuer)
            if row is None:
                s.add(JwksRow(issuer=issuer, keys=keys))
            else:
                row.keys, row.fetched_at = keys, utcnow()


def oldest_open_ages(session: Session) -> list[tuple[str, str, float]]:
    """(status, env, age seconds) of the oldest open request per status and environment, for the gauge."""
    q = select(ChangeRequestRow.status, ChangeRequestRow.env, func.min(ChangeRequestRow.created_at)) \
        .where(ChangeRequestRow.status.in_(OPEN_STATES)).group_by(ChangeRequestRow.status, ChangeRequestRow.env)
    now = utcnow()
    return [(st, env, (now - created).total_seconds()) for st, env, created in session.execute(q)]
