"""ORM models for the cmapi schema (docs/01, Data model; docs/02, Schemas).

The migrations make the schema. The models say the same schema, each index included, so that `alembic check`
finds no difference between them (tests/service/test_models_match_migrations.py, #185). The indexes that carry
correctness: one open request per namespace (a partial unique index on cluster_id and namespace), one idempotency
key per caller (#592, #603), one approval per person, and one pending job of a kind per request.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
                        Uuid, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

OPEN_STATES = ("pending_approval", "approved", "pr_open", "applied", "merge_failed", "merged", "awaiting_prune", "sync_failed")


class Base(DeclarativeBase):
    pass


class ChangeRequestRow(Base):
    __tablename__ = "change_requests"
    # ck_cr_requester_kind is 0001's. A row that holds an Idempotency-Key names its caller (0009, #603):
    # uq_cr_idempotency_caller is the key's only unique index, and NULLs are distinct in it, so a keyed row with no caller
    # would escape it and the lookup.
    __table_args__ = (
        CheckConstraint("requester_kind IN ('user', 'service')", name="ck_cr_requester_kind"),
        CheckConstraint("idempotency_key IS NULL OR idempotency_sub IS NOT NULL", name="ck_cr_idempotency_caller"),
    )
    request_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance: Mapped[str] = mapped_column(String(40), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(63), nullable=False)
    namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    env: Mapped[str] = mapped_column(String(20), nullable=False)
    plugin: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(80))
    justification: Mapped[str | None] = mapped_column(Text)
    team: Mapped[str | None] = mapped_column(String(63))
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)        # files, prev, facts, spec
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    base_sha: Mapped[str | None] = mapped_column(String(64))
    requirement: Mapped[dict[str, Any] | None] = mapped_column(JSONB)          # the Requirement, as data
    requester: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)   # Requester.record()
    requester_sub: Mapped[str] = mapped_column(String(100), nullable=False)
    requester_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    requester_client: Mapped[str] = mapped_column(String(100), nullable=False)
    requester_username: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(64))
    # The subject of the caller that sent the key: the service, not the person, on a write sent with onBehalfOf (#592,
    # migration 0008). Never null on a row that holds a key (ck_cr_idempotency_caller, 0009). A row with no key may keep
    # one: a 0007 pod's expiry cleared the key and left it (docs/16).
    idempotency_sub: Mapped[str | None] = mapped_column(String(100))
    pr: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    merge_sha: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestEventRow(Base):
    __tablename__ = "request_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(40), ForeignKey("change_requests.request_id"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str | None] = mapped_column(String(20))
    by: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(40), ForeignKey("change_requests.request_id"), nullable=False)
    approver_sub: Mapped[str] = mapped_column(String(100), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    groups: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # The approving group of approval-rules.yaml whose slot this approval fills, from the ledger's assignment. `groups` is
    # each group of the approver, so it cannot say that. NULL: recorded before migration 0004, and not known (#171).
    counted_for: Mapped[str | None] = mapped_column(String(100))
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    relayed_by: Mapped[str | None] = mapped_column(String(100))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class JobRow(Base):
    __tablename__ = "jobs"
    job_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("change_requests.request_id"))
    cluster_id: Mapped[str] = mapped_column(String(63), nullable=False, default="")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_sub: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_username: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_client: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class JwksRow(Base):
    __tablename__ = "jwks_keys"
    issuer: Mapped[str] = mapped_column(String(255), primary_key=True)
    keys: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SwitchRow(Base):
    """Admin switches: auto-approval paused, with who and why."""
    __tablename__ = "admin_switches"
    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    set_by: Mapped[str] = mapped_column(String(100), nullable=False)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ApprovalNotificationRow(Base):
    __tablename__ = "approval_notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(40), ForeignKey("change_requests.request_id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)       # pending | decision
    recipients: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    link_id: Mapped[str | None] = mapped_column(String(64))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ExpirationNoticeRow(Base):
    __tablename__ = "expiration_notices"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cluster_id: Mapped[str] = mapped_column(String(63), nullable=False)
    namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(10), nullable=False)
    threshold_days: Mapped[int] = mapped_column(Integer, nullable=False)   # 14, 7, 1; 0 for grace, -1 for the delete
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    request_id: Mapped[str | None] = mapped_column(String(40))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PolicyRejectionRow(Base):
    """A refusal of cmapi before Git, or Kyverno's warnings on a plan that went on (#302, migration 0006).

    One row per refusal per UTC day: the same refusal again that day adds to `count` and moves `last_at`, never the row's
    place, since the list is ordered by `first_at`. Who asked is the username only: never the email, the employee ID or the
    justification (the owner, 2026-11-17). A refused plan has no request (`request_id` is NULL); a warned plan and a CI
    refusal belong to theirs."""
    __tablename__ = "policy_rejections"
    __table_args__ = (
        CheckConstraint("count >= 1", name="ck_rej_count"),
        CheckConstraint("stage IN ('plan', 'ci')", name="ck_rej_stage"),
        CheckConstraint("outcome IN ('refused', 'warned')", name="ck_rej_outcome"),
        CheckConstraint("(stage = 'plan' AND outcome = 'refused') = (request_id IS NULL)", name="ck_rej_request"),
        CheckConstraint("(stage = 'plan' AND outcome = 'refused') = (problem IS NOT NULL)", name="ck_rej_problem"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    stage: Mapped[str] = mapped_column(String(4), nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    problem: Mapped[str | None] = mapped_column(String(60))
    cluster_id: Mapped[str] = mapped_column(String(63), nullable=False)
    env: Mapped[str] = mapped_column(String(20), nullable=False)
    namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    plugin: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("change_requests.request_id"))
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    automated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class CapacityReservationRow(Base):
    """Capacity that one request holds on its cluster until its quota is live (#62, migration 0011; docs/02, Placement,
    "Reservations"). The columns are docs/02's, with three added: the namespace, and the namespace's binding quota after the
    change (`target_cpu`, `target_memory`). The capacity check stops counting a hold once the cluster's quota ledger shows
    that quota ("observed"), so it is never counted twice. `cpu` and `memory` are the increase the plan was checked for."""
    __tablename__ = "capacity_reservations"
    __table_args__ = (
        CheckConstraint("cpu >= 0 AND memory >= 0 AND pods >= 0", name="ck_resv_amounts"),
        CheckConstraint("(released_at IS NULL) = (released_why IS NULL)", name="ck_resv_released"),
    )
    reservation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    request_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("change_requests.request_id"))
    cluster_id: Mapped[str] = mapped_column(String(63), nullable=False)
    namespace: Mapped[str | None] = mapped_column(String(63))
    zone: Mapped[str | None] = mapped_column(String(63))
    cpu: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    memory: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pods: Mapped[int] = mapped_column(Integer, nullable=False)
    target_cpu: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    target_memory: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_why: Mapped[str | None] = mapped_column(String(20))


# Each index of the migrations, in the same words, so that autogenerate has nothing to add and nothing to drop.
Index("uq_cr_open_namespace", ChangeRequestRow.cluster_id, ChangeRequestRow.namespace, unique=True,
      postgresql_where=text("status IN ('" + "', '".join(OPEN_STATES) + "')"))
Index("uq_cr_idempotency_caller", ChangeRequestRow.idempotency_sub, ChangeRequestRow.idempotency_key, unique=True,
      postgresql_where=text("idempotency_key IS NOT NULL"))
Index("idx_cr_namespace", ChangeRequestRow.cluster_id, ChangeRequestRow.namespace, ChangeRequestRow.created_at)
Index("uq_approvals_person", ApprovalRow.request_id, ApprovalRow.approver_sub, unique=True)
Index("idx_jobs_due", JobRow.run_after, postgresql_where=text("done_at IS NULL"))
Index("uq_jobs_pending", JobRow.kind, text("coalesce(request_id, '')"), text("coalesce(payload->>'kind', '')"), unique=True,
      postgresql_where=text("done_at IS NULL"))
Index("idx_audit_at", AuditEventRow.at)
Index("idx_approval_notifications_request", ApprovalNotificationRow.request_id)
Index("idx_request_events_request", RequestEventRow.request_id, RequestEventRow.id)
Index("idx_approvals_request", ApprovalRow.request_id)
Index("idx_cr_status", ChangeRequestRow.status, ChangeRequestRow.created_at)
Index("idx_expiration_notices_ns", ExpirationNoticeRow.cluster_id, ExpirationNoticeRow.namespace,
      ExpirationNoticeRow.expires_at, ExpirationNoticeRow.threshold_days)
Index("uq_rej_fingerprint_day", PolicyRejectionRow.fingerprint, PolicyRejectionRow.day, unique=True)
Index("idx_rej_env_first", PolicyRejectionRow.env, PolicyRejectionRow.first_at, PolicyRejectionRow.id)
Index("idx_rej_last", PolicyRejectionRow.last_at)
Index("idx_resv_active", CapacityReservationRow.cluster_id, postgresql_where=text("released_at IS NULL"))
Index("idx_resv_request", CapacityReservationRow.request_id)


class AnalysisSweepRow(Base):
    """One usage sweep of one cluster on one UTC day (#310, migration 0010; docs/03, "Data model and API"). `evaluated_at` is
    the single instant every query of the sweep used. `failed` means no query answered cleanly: its namespaces got
    insufficient-data for the day, never a zero."""
    __tablename__ = "analysis_sweeps"
    __table_args__ = (CheckConstraint("status IN ('complete', 'partial', 'failed')", name="ck_sweep_status"),)
    cluster_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    step: Mapped[str] = mapped_column(String(5), nullable=False)
    namespaces: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)


class NamespaceVerdictRow(Base):
    """A verdict of one namespace's resource on one day, with the numbers and the threshold behind it (`evidence`, which also
    holds the sentence a person reads). Kept 13 months (capacity/sweep.py)."""
    __tablename__ = "namespace_verdicts"
    __table_args__ = (
        CheckConstraint("kind IN ('ok', 'info', 'waste', 'risk')", name="ck_verdict_kind"),
        CheckConstraint("resource IN ('cpu', 'memory', 'pods')", name="ck_verdict_resource"),
        Index("idx_verdicts_cluster_day", "cluster_id", "day"),
        Index("idx_verdicts_day", "day"),
    )
    cluster_id: Mapped[str] = mapped_column(String(63), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(63), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    resource: Mapped[str] = mapped_column(String(10), primary_key=True)
    verdict: Mapped[str] = mapped_column(String(30), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
