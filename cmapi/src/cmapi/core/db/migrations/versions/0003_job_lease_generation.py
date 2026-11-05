"""A fencing token on job leases: every claim increments it, and a worker's commit is refused when
the job was claimed again after its lease expired (a long pause), so the stale worker's writes roll back.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("lease_generation", sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("jobs", "lease_generation")
