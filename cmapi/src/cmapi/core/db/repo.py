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
from cmapi.core.db.models import (ApprovalRow, AuditEventRow, CapacityReservationRow, ChangeRequestRow, JobRow, JwksRow,
                                  OPEN_STATES, RequestEventRow, SwitchRow)
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.lifecycle import Event as E, State as S, holds_reservation, transition


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


IDEMPOTENCY_HOURS = 24      # how long an Idempotency-Key returns its original request (docs/02, API contract)
# The one unique index of an Idempotency-Key: (idempotency_sub, idempotency_key), the caller's (0008, #592). Migration 0009
# dropped the requester's (#603).
IDEMPOTENCY_INDEX = "uq_cr_idempotency_caller"


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

    def open_holders(self, cluster_id: str) -> dict[str, dict[str, str]]:
        """The open request of each namespace on the cluster that one holds, by namespace, with its status: the sync
        state of a namespace says which request holds it and how far it is (#481)."""
        q = select(ChangeRequestRow.namespace, ChangeRequestRow.request_id, ChangeRequestRow.status) \
            .where(ChangeRequestRow.status.in_(OPEN_STATES), ChangeRequestRow.cluster_id == cluster_id)
        return {n: {"requestId": r, "status": status} for n, r, status in self.s.execute(q)}

    def open_namespaces(self, cluster_id: str | None = None) -> dict[tuple[str, str], str]:
        q = select(ChangeRequestRow.cluster_id, ChangeRequestRow.namespace, ChangeRequestRow.request_id) \
            .where(ChangeRequestRow.status.in_(OPEN_STATES))
        if cluster_id:
            q = q.where(ChangeRequestRow.cluster_id == cluster_id)
        return {(c, n): r for c, n, r in self.s.execute(q)}

    def by_idempotency(self, caller_sub: str, key: str) -> ChangeRequestRow | None:
        """The caller's request for this key, if the key is still held. The key belongs to the caller that sent it, the
        service on a write sent with onBehalfOf, not the person the request is for (#592). A key is held for
        IDEMPOTENCY_HOURS (docs/02) from the request's creation, by the database's clock and not a pod's.

        Past that, the caller's hold on the key is cleared here, in the caller's transaction, so that the caller's unique
        index (IDEMPOTENCY_INDEX) does not refuse the caller's next use of it. Both statements look up
        (idempotency_sub, idempotency_key), which that index serves. Another caller's expired row cannot refuse this
        caller, since 0009 dropped the requester's index, so it keeps its key until its own caller sends it again; it never
        replays, because this clearing comes before every read (#603). The index allows one row per caller and key."""
        mine = (ChangeRequestRow.idempotency_sub == caller_sub, ChangeRequestRow.idempotency_key == key)
        self.s.execute(update(ChangeRequestRow)
                       .where(*mine, ChangeRequestRow.created_at < func.now() - text(f"interval '{IDEMPOTENCY_HOURS} hours'"))
                       .values(idempotency_key=None, idempotency_fingerprint=None, idempotency_sub=None,
                               updated_at=ChangeRequestRow.updated_at))
        return self.s.scalars(select(ChangeRequestRow).where(*mine)).one_or_none()

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
            # The index that refused, from PostgreSQL's diagnostics and not its message: the message's DETAIL quotes the
            # key, which may be any text, so a key named after an index chose the wrong 409 (#601 review).
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_cr_open_namespace":
                holder = self.open_for(row.cluster_id, row.namespace)
                if holder is None:
                    # The holder closed after this INSERT failed and before the read (#496): nothing holds the
                    # namespace now, so there is no request to name. Reading it again shows what changed.
                    raise Problem.conflict("change-pending", f"the request that held {row.namespace} has just finished; "
                                           "read the namespace again and resend the change") from exc
                raise Problem.conflict("change-pending", f"{holder.request_id} holds {row.namespace}",
                                       requestId=holder.request_id) from exc
            if constraint == IDEMPOTENCY_INDEX:
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
        holds = ReservationRepo(self.s)
        if t.after is S.APPROVED:
            # The last :approve and a :retry from failed check capacity again (SimulatedCapacity.confirm) under the cluster's
            # lock. Taken here, before the namespace's unique index entry (the flush below) and any hold row is written, as
            # submit takes it before both: in the other order a submit and a :retry wait on each other (#725 review).
            holds.lock_cluster(row.cluster_id)
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
        # The capacity hold follows the lifecycle's Reservation column (docs/01), in the same transaction as the state.
        if t.releases_reservation:
            holds.release(row.request_id, t.after.value)
        elif t.acquires_reservation or t.after is S.APPROVED:
            # approved: "capacity still fits" (docs/01). A hold that lapsed while the request waited is taken again, so that
            # the caller's check counts it, and refuses the approval when another request took the room (#725 review).
            holds.reacquire(row.request_id, hold_term(row.requirement))
        elif holds_reservation(t.after):
            holds.rearm(row.request_id, hold_term(row.requirement))
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
            .order_by(JobRow.run_after, JobRow.job_id).limit(1).with_for_update(skip_locked=True)  # a tie: first queued, first claimed (BUG-74)
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

    def value(self, name: str) -> dict[str, Any] | None:
        """The switch's value, by a query in the session's transaction, never from its identity map. Session.get returns a row
        that the session still holds "directly from this collection and no SQL is emitted" (SQLAlchemy 2.1), so a caller whose
        transaction keeps the row would miss a pause committed since; the kill switch must not depend on who keeps it."""
        return self.s.execute(select(SwitchRow.value).where(SwitchRow.name == name)).scalar_one_or_none()

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


# How long a hold lasts past a request's last step: its approval timeout (docs/02: "the approval timeout once submitted"), plus
# the hour that jobs/approval_timeout.py may take to see a request past it, so a pending request never outlives its hold.
HOLD_GRACE = timedelta(hours=1)


def hold_term(requirement: Mapping[str, Any] | None) -> timedelta:
    return timedelta(hours=(requirement or {}).get("timeoutHours", 24)) + HOLD_GRACE


class ReservationRepo:
    """capacity_reservations (migration 0011; docs/02, Placement, "Reservations"). A hold is active while it is not released and
    its `expires_at` is ahead. The lifecycle decides when a request holds one (holds_reservation, core/lifecycle.py):
    RequestRepo.move releases it as the request leaves those states, takes it again when a :retry re-enters them, and moves
    its expiry on at each step in between. The capacity check that reads the holds is core/capacity_backend.py's."""

    def __init__(self, session: Session):
        self.s = session

    def lock_cluster(self, cluster_id: str) -> None:
        """Serialize every check-and-hold on one cluster until this transaction ends. docs/02: "Placement takes a reservation
        inside the same transaction as the capacity check, under a per-cluster advisory lock, so concurrent requests see each
        other." Taken after any request row lock and the day's lock (next_id), never before them, so no two writers wait on
        each other in opposite orders."""
        digest = hashlib.sha256(f"cmapi-capacity:{cluster_id}".encode()).digest()
        self.s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int.from_bytes(digest[:8], "big", signed=True)})

    @staticmethod
    def _active(now: datetime) -> Any:
        return and_(CapacityReservationRow.released_at.is_(None), CapacityReservationRow.expires_at > now)

    def active(self, cluster_id: str, *, exclude: str | None = None,
               exclude_placement: str | None = None) -> list[CapacityReservationRow]:
        """The cluster's active holds; `exclude`: leave out this request's own, to check it again on its own terms;
        `exclude_placement`: leave out the placement that a create claims, whose amount the create's own check counts (#21)."""
        q = select(CapacityReservationRow).where(CapacityReservationRow.cluster_id == cluster_id, self._active(utcnow()))
        if exclude is not None:
            q = q.where(or_(CapacityReservationRow.request_id.is_(None), CapacityReservationRow.request_id != exclude))
        if exclude_placement is not None:
            q = q.where(or_(CapacityReservationRow.placement_id.is_(None),
                            CapacityReservationRow.placement_id != exclude_placement))
        return list(self.s.scalars(q))

    def placement(self, placement_id: str) -> CapacityReservationRow | None:
        """The placement's hold while it is active and no request has claimed it (#21), else None."""
        return self.s.scalars(select(CapacityReservationRow).where(
            CapacityReservationRow.placement_id == placement_id, CapacityReservationRow.request_id.is_(None),
            self._active(utcnow()))).first()

    def lock_team_placements(self, team: str, env: str) -> None:
        """Serialize the placements of one team in one environment until this transaction ends, so two at once cannot both
        pass the count of `active_placements`."""
        digest = hashlib.sha256(f"cmapi-placements:{env}:{team}".encode()).digest()
        self.s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int.from_bytes(digest[:8], "big", signed=True)})

    def active_placements(self, team: str, env: str) -> int:
        """The team's placements in the environment that are active and not claimed by a create (docs/01: "at most 3 active
        placements per team and environment, so nobody can hold a cluster's headroom with reservations")."""
        return self.s.scalar(select(func.count()).select_from(CapacityReservationRow).where(
            CapacityReservationRow.placement_id.is_not(None), CapacityReservationRow.request_id.is_(None),
            CapacityReservationRow.team == team, CapacityReservationRow.env == env, self._active(utcnow()))) or 0

    def claim(self, placement_id: str, row: CapacityReservationRow) -> bool:
        """docs/02: "The create request then carries the placementId, which turns that reservation into the request's own."
        The placement's hold takes the request, its namespace, the amounts its plan was checked for and the request's term.
        False when the hold lapsed or was claimed since the plan: the caller then takes a hold of its own, already checked."""
        return self.s.execute(update(CapacityReservationRow).where(
            CapacityReservationRow.placement_id == placement_id, CapacityReservationRow.request_id.is_(None),
            self._active(utcnow())).values(
            request_id=row.request_id, namespace=row.namespace, cpu=row.cpu, memory=row.memory, pods=row.pods,
            target_cpu=row.target_cpu, target_memory=row.target_memory, expires_at=row.expires_at)).rowcount == 1

    def of(self, request_id: str) -> CapacityReservationRow | None:
        """The request's active hold, or None: it has none (no increase, a delete), or it ended."""
        return self.s.scalars(select(CapacityReservationRow).where(
            CapacityReservationRow.request_id == request_id, self._active(utcnow()))).first()

    def hold(self, row: CapacityReservationRow) -> CapacityReservationRow:
        self.s.add(row)
        self.s.flush()
        return row

    def release(self, request_id: str, why: str) -> int:
        """End the request's holds, naming why: the state it moved to (synced, rejected, cancelled, timeout, ...)."""
        return self.s.execute(update(CapacityReservationRow).where(
            CapacityReservationRow.request_id == request_id, CapacityReservationRow.released_at.is_(None)
        ).values(released_at=utcnow(), released_why=why)).rowcount

    def rearm(self, request_id: str, term: timedelta) -> None:
        """Move the expiry of the request's active hold to one term from now: a request that keeps moving keeps its hold, and
        one that stops (a lost worker, a crash) lets it go one term after its last step. Without this, a request approved
        near the end of its approval window lost its hold while its PR was still open."""
        now = utcnow()
        self.s.execute(update(CapacityReservationRow).where(
            CapacityReservationRow.request_id == request_id, self._active(now)).values(expires_at=now + term))

    def reacquire(self, request_id: str, term: timedelta) -> CapacityReservationRow | None:
        """A :retry that re-enters a holding state (failed to approved) holds the request's last amounts again, for a new
        term. The caller checks that they still fit (SimulatedCapacity.confirm)."""
        last = self.s.scalars(select(CapacityReservationRow).where(CapacityReservationRow.request_id == request_id)
                              .order_by(CapacityReservationRow.created_at.desc())).first()
        if last is None:
            return None
        now = utcnow()
        if last.released_at is None and last.expires_at > now:
            last.expires_at = now + term
            return last
        if last.released_at is None:
            last.released_at, last.released_why = now, "expired"      # lapsed: one active hold per request
        return self.hold(CapacityReservationRow(
            request_id=request_id, cluster_id=last.cluster_id, namespace=last.namespace, zone=last.zone, cpu=last.cpu,
            memory=last.memory, pods=last.pods, target_cpu=last.target_cpu, target_memory=last.target_memory,
            created_at=now, expires_at=now + term))

    def reclaim(self, cluster_id: str) -> None:
        """docs/02's "expired reservations are reclaimed": mark the cluster's expired holds released. A hold that one reader's
        ledger shows is not released here: each reader stops counting it from its own watch (capacity_backend.held)."""
        now = utcnow()
        self.s.execute(update(CapacityReservationRow).where(
            CapacityReservationRow.cluster_id == cluster_id, CapacityReservationRow.released_at.is_(None),
            CapacityReservationRow.expires_at <= now).values(released_at=now, released_why="expired"))
