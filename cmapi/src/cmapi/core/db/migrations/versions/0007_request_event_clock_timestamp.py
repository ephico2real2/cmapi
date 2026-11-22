"""Request events record insertion time, rather than the transaction's start time (#551).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("request_events", "at", server_default=sa.func.clock_timestamp())


def downgrade() -> None:
    op.alter_column("request_events", "at", server_default=sa.func.now())
