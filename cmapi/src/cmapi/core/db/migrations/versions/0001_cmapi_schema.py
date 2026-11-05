"""The cmapi schema: change requests, events, approvals, jobs, audit, JWKS cache, switches.

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

OPEN = "('pending_approval', 'approved', 'pr_open', 'merged', 'awaiting_prune', 'sync_failed')"


def upgrade() -> None:
    op.create_table(
        "change_requests",
        sa.Column("request_id", sa.String(40), primary_key=True),
        sa.Column("instance", sa.String(40), nullable=False),
        sa.Column("cluster_id", sa.String(63), nullable=False),
        sa.Column("namespace", sa.String(63), nullable=False),
        sa.Column("env", sa.String(20), nullable=False),
        sa.Column("plugin", sa.String(40), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(80)),
        sa.Column("justification", sa.Text),
        sa.Column("team", sa.String(63)),
        sa.Column("plan", JSONB, nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("base_sha", sa.String(64)),
        sa.Column("requirement", JSONB),
        sa.Column("requester", JSONB, nullable=False),
        sa.Column("requester_sub", sa.String(100), nullable=False),
        sa.Column("requester_kind", sa.String(8), nullable=False),
        sa.Column("requester_client", sa.String(100), nullable=False),
        sa.Column("requester_username", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(100)),
        sa.Column("idempotency_fingerprint", sa.String(64)),
        sa.Column("pr", JSONB),
        sa.Column("merge_sha", sa.String(64)),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("merged_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("requester_kind IN ('user', 'service')", name="ck_cr_requester_kind"),
    )
    # The lock: at most one open request per namespace, covering every file in its folder.
    op.execute(f"CREATE UNIQUE INDEX uq_cr_open_namespace ON change_requests (cluster_id, namespace) "
               f"WHERE status IN {OPEN}")
    # Idempotency per caller: the same key from the same person returns the first response.
    op.create_index("uq_cr_idempotency", "change_requests", ["requester_sub", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.create_index("idx_cr_status", "change_requests", ["status", "created_at"])
    op.create_index("idx_cr_namespace", "change_requests", ["cluster_id", "namespace", "created_at"])

    op.create_table(
        "request_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.request_id"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20)),
        sa.Column("by", sa.String(100), nullable=False),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("detail", JSONB),
    )
    op.create_index("idx_request_events_request", "request_events", ["request_id", "id"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.request_id"), nullable=False),
        sa.Column("approver_sub", sa.String(100), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("groups", JSONB, nullable=False),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column("relayed_by", sa.String(100)),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_approvals_request", "approvals", ["request_id"])

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.request_id")),
        sa.Column("cluster_id", sa.String(63), nullable=False, server_default=""),
        sa.Column("payload", JSONB),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(100)),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_jobs_due", "jobs", ["run_after"], postgresql_where=sa.text("done_at IS NULL"))
    # One pending job of a kind per request (or one per recurring kind), so a retry never doubles work.
    op.execute("CREATE UNIQUE INDEX uq_jobs_pending ON jobs (kind, coalesce(request_id, ''), "
               "coalesce(payload->>'kind', '')) WHERE done_at IS NULL")

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_sub", sa.String(100), nullable=False),
        sa.Column("actor_username", sa.String(100), nullable=False),
        sa.Column("actor_client", sa.String(100), nullable=False, server_default=""),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("detail", JSONB),
    )
    op.create_index("idx_audit_at", "audit_events", ["at"])

    op.create_table(
        "jwks_keys",
        sa.Column("issuer", sa.String(255), primary_key=True),
        sa.Column("keys", JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "admin_switches",
        sa.Column("name", sa.String(60), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("set_by", sa.String(100), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "approval_notifications",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.request_id"), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("recipients", JSONB, nullable=False),
        sa.Column("link_id", sa.String(64)),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("detail", JSONB),
    )
    op.create_index("idx_approval_notifications_request", "approval_notifications", ["request_id"])
    op.create_table(
        "expiration_notices",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("cluster_id", sa.String(63), nullable=False),
        sa.Column("namespace", sa.String(63), nullable=False),
        sa.Column("expires_at", sa.String(10), nullable=False),
        sa.Column("threshold_days", sa.Integer, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("request_id", sa.String(40)),
        sa.Column("ok", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("idx_expiration_notices_ns", "expiration_notices",
                    ["cluster_id", "namespace", "expires_at", "threshold_days"])


def downgrade() -> None:
    for t in ("expiration_notices", "approval_notifications", "admin_switches", "jwks_keys", "audit_events",
              "jobs", "approvals", "request_events", "change_requests"):
        op.drop_table(t)
