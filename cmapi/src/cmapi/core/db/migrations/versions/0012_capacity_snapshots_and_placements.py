"""capacity_snapshots, and the placement holds of POST /api/v1/capacity:place (#21; docs/02, "Stored capacity", "Placement").

capacity_snapshots has docs/02's columns, with two added:

- `source`: what measured the row. `thanos` when capacity.yaml `usage.source` is thanos: the requests, limits and use come from
  the cluster's Thanos Querier, per node. `api` when it is none: the row has what the cluster's API gives (nodes, zones, roles,
  allocatable, conditions) and the committed quota, and its measured figures are null, never 0.
- `detail`: why the row is incomplete, in words; null when it is complete. Placement names it when it excludes the cluster.

Two differences, both of storage only, as 0010's: the table is not partitioned by month (the job deletes the rows past 13
months, capacity/snapshots.py; partitioning is #705), and it lives in the cmapi schema, since cmapi-capacity is not built and
the worker runs the snapshot job (docs/01, "One interface, two modes": embedded).

capacity_reservations gains what a placement hold needs before any request exists (docs/02: "request_id ... null while only
placed"): `placement_id`, the id that POST /capacity:place returns and the create sends, unique; and `env` and `team`, which
the create must match ("must match the path cluster, team and env", NamespaceCreate.placement_id) and which count a team's
active placements (docs/01: "at most 3 active placements per team and environment").

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capacity_snapshots",
        sa.Column("cluster_id", sa.String(63), primary_key=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("scope", sa.String(80), primary_key=True),
        sa.Column("interval_seconds", sa.Integer, nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("cpu", JSONB, nullable=False),
        sa.Column("memory", JSONB, nullable=False),
        sa.Column("pods", JSONB, nullable=False),
        sa.Column("storage", JSONB),
        sa.Column("nodes", JSONB, nullable=False),
        sa.Column("complete", sa.Boolean, nullable=False),
        sa.Column("detail", sa.Text),
        sa.CheckConstraint("source IN ('thanos', 'api')", name="ck_snapshot_source"),
        sa.CheckConstraint("complete = (detail IS NULL)", name="ck_snapshot_detail"),
    )
    # Placement and the Capacity tab read each cluster's newest rows; the retention deletes by time.
    op.create_index("idx_snapshots_cluster_taken", "capacity_snapshots", ["cluster_id", "taken_at"])
    op.create_index("idx_snapshots_taken", "capacity_snapshots", ["taken_at"])
    op.add_column("capacity_reservations", sa.Column("placement_id", sa.String(40)))
    op.add_column("capacity_reservations", sa.Column("env", sa.String(20)))
    op.add_column("capacity_reservations", sa.Column("team", sa.String(63)))
    op.create_index("uq_resv_placement", "capacity_reservations", ["placement_id"], unique=True,
                    postgresql_where=sa.text("placement_id IS NOT NULL"))


def downgrade() -> None:
    # A placement hold that no request has claimed yet is lost with its id: it would have lapsed within its 15 minutes.
    op.drop_index("uq_resv_placement", "capacity_reservations")
    op.execute("DELETE FROM capacity_reservations WHERE request_id IS NULL")
    for column in ("team", "env", "placement_id"):
        op.drop_column("capacity_reservations", column)
    op.drop_table("capacity_snapshots")
