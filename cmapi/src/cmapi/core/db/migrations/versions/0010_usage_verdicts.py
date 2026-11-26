"""analysis_sweeps and namespace_verdicts: the daily usage sweep and the verdicts it stores (#310; docs/03, "Data model and API").

The columns are docs/03's. Two differences, both of storage only:

- namespace_verdicts is not partitioned by month. docs/03 has `PARTITION BY RANGE (day)` and a retention job that "drops
  expired monthly partitions". A partitioned table needs each month's partition made before its first row, so runtime DDL in
  the sweep, and `alembic check` (tests/service/test_models_match_migrations.py) sees each partition as a table the models do
  not have. The sweep deletes the rows past 13 months instead (capacity/sweep.py, RETENTION_DAYS). At 5,000 namespaces, two
  resources and 395 days that is about 4 million rows; partitioning is #705.
- They live in the cmapi schema, beside the other tables. docs/01 has a capacity schema written by cmapi-capacity alone; that
  service is not built, and the embedded mode (docs/01, "One interface, two modes") runs the sweep in the worker.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_sweeps",
        sa.Column("cluster_id", sa.String(63), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("step", sa.String(5), nullable=False),
        sa.Column("namespaces", sa.Integer),
        sa.Column("detail", sa.Text),
        sa.CheckConstraint("status IN ('complete', 'partial', 'failed')", name="ck_sweep_status"),
    )
    op.create_table(
        "namespace_verdicts",
        sa.Column("cluster_id", sa.String(63), primary_key=True),
        sa.Column("namespace", sa.String(63), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("resource", sa.String(10), primary_key=True),
        sa.Column("verdict", sa.String(30), primary_key=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("evidence", JSONB, nullable=False),
        sa.CheckConstraint("kind IN ('ok', 'info', 'waste', 'risk')", name="ck_verdict_kind"),
        sa.CheckConstraint("resource IN ('cpu', 'memory', 'pods')", name="ck_verdict_resource"),
    )
    # GET /api/v1/quotas reads one day of a cluster's verdicts, and the retention deletes by day.
    op.create_index("idx_verdicts_cluster_day", "namespace_verdicts", ["cluster_id", "day"])
    op.create_index("idx_verdicts_day", "namespace_verdicts", ["day"])


def downgrade() -> None:
    # Only the sweep writes these tables and nothing refers to them: dropping them loses the stored verdicts only.
    op.drop_table("namespace_verdicts")
    op.drop_table("analysis_sweeps")
