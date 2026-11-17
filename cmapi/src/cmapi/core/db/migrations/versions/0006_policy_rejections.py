"""policy_rejections: cmapi's refusals before Git, and Kyverno's warnings on a plan that went on (#302).

Nothing stored a plan-time refusal before this revision: the pipeline answered 422 and counted a metric. The Policies tab
lists them for the environments a caller may read (GET /api/v1/policies/rejections). One row per refusal per UTC day
(`fingerprint`, `day`), so a retried refusal adds to `count` instead of a row. Who asked is the username only. The rows
are pruned after policy.rejections.retentionDays (90 by default) by the worker's daily rejections_prune.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_rejections",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("stage", sa.String(4), nullable=False),
        sa.Column("outcome", sa.String(8), nullable=False),
        sa.Column("problem", sa.String(60)),
        sa.Column("cluster_id", sa.String(63), nullable=False),
        sa.Column("env", sa.String(20), nullable=False),
        sa.Column("namespace", sa.String(63), nullable=False),
        sa.Column("plugin", sa.String(40), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.request_id")),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("automated", sa.Boolean, nullable=False),
        sa.Column("findings", JSONB, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("count >= 1", name="ck_rej_count"),
        sa.CheckConstraint("stage IN ('plan', 'ci')", name="ck_rej_stage"),
        sa.CheckConstraint("outcome IN ('refused', 'warned')", name="ck_rej_outcome"),
        # A refused plan never became a request; a warned plan and a CI refusal always belong to one.
        sa.CheckConstraint("(stage = 'plan' AND outcome = 'refused') = (request_id IS NULL)", name="ck_rej_request"),
        sa.CheckConstraint("(stage = 'plan' AND outcome = 'refused') = (problem IS NOT NULL)", name="ck_rej_problem"),
    )
    op.create_index("uq_rej_fingerprint_day", "policy_rejections", ["fingerprint", "day"], unique=True)
    op.create_index("idx_rej_env_first", "policy_rejections", ["env", "first_at", "id"])
    op.create_index("idx_rej_last", "policy_rejections", ["last_at"])


def downgrade() -> None:
    # Only this table refers to its rows: dropping it loses the stored refusals and nothing else.
    op.drop_table("policy_rejections")
