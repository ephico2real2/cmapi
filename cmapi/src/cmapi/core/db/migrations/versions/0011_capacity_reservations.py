"""capacity_reservations: the capacity that each open request holds on its cluster (#62; docs/02, Placement, "Reservations").

The columns are docs/02's, with three added:

- `namespace`: the namespace whose quota the request changes. docs/02 reaches it through `request_id`; the capacity check reads
  it for every active hold, so it is kept on the row instead of a join on each plan.
- `target_cpu` and `target_memory`: the namespace's binding quota after the change. docs/02: "The reservation ends when the
  namespace's ResourceQuota appears in cmapi's watch cache of that cluster. Committed quota counts it from then on, so it is
  never counted twice." The check compares them with the cluster's quota ledger and stops counting a hold that the ledger
  already shows (core/capacity_backend.py).

A placement hold (POST /api/v1/capacity:place, not built) has no request and no namespace yet, so both stay nullable.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capacity_reservations",
        sa.Column("reservation_id", sa.Uuid, primary_key=True),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.request_id")),
        sa.Column("cluster_id", sa.String(63), nullable=False),
        sa.Column("namespace", sa.String(63)),
        sa.Column("zone", sa.String(63)),
        sa.Column("cpu", sa.Numeric(12, 3), nullable=False),
        sa.Column("memory", sa.BigInteger, nullable=False),
        sa.Column("pods", sa.Integer, nullable=False),
        sa.Column("target_cpu", sa.Numeric(12, 3)),
        sa.Column("target_memory", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("released_why", sa.String(20)),
        sa.CheckConstraint("cpu >= 0 AND memory >= 0 AND pods >= 0", name="ck_resv_amounts"),
        sa.CheckConstraint("(released_at IS NULL) = (released_why IS NULL)", name="ck_resv_released"),
    )
    # The check sums a cluster's active holds on every plan; a request's own hold is found by its id.
    op.create_index("idx_resv_active", "capacity_reservations", ["cluster_id"], postgresql_where=sa.text("released_at IS NULL"))
    op.create_index("idx_resv_request", "capacity_reservations", ["request_id"])


def downgrade() -> None:
    # Holds are live state of open requests: dropping the table lets them overbook until each one ends.
    op.drop_table("capacity_reservations")
