"""An approval records the approving group that it counted for, so the self-service rate can be computed (#171).

The column is nullable: the approvals of before have no value, because the ledger decided their slots in memory and
did not store them. A request with such an approval is in neither part of the rate.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("counted_for", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "counted_for")
