"""ORM models for the cmapi schema (docs/01, Data model; docs/02, Schemas).

The migrations make the schema. The models say the same schema, each index included, so that `alembic check`
finds no difference between them (tests/service/test_models_match_migrations.py, #185). The indexes that carry
correctness: one open request per namespace (a partial unique index on cluster_id and namespace), one idempotency
key per requester, one approval per person, and one pending job of a kind per request.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

OPEN_STATES = ("pending_approval", "approved", "pr_open", "merged", "awaiting_prune", "sync_failed")


class Base(DeclarativeBase):
    pass


class ChangeRequestRow(Base):
    __tablename__ = "change_requests"
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
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
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


# Each index of the migrations, in the same words, so that autogenerate has nothing to add and nothing to drop.
Index("uq_cr_open_namespace", ChangeRequestRow.cluster_id, ChangeRequestRow.namespace, unique=True,
      postgresql_where=text("status IN ('" + "', '".join(OPEN_STATES) + "')"))
Index("uq_cr_idempotency", ChangeRequestRow.requester_sub, ChangeRequestRow.idempotency_key, unique=True,
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
