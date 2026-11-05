"""An approval counts one person once, in the schema as well as in the ledger.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("uq_approvals_person", "approvals", ["request_id", "approver_sub"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_approvals_person", table_name="approvals")
