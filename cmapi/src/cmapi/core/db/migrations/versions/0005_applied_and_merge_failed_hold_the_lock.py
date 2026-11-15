"""applied and merge_failed hold the namespace's lock (#286, F1 of the design review; Fable's design, 1).

Apply before merge: a request whose change is on the cluster and whose PR is not merged must keep the lock, or the next plan
reads main, which lacks the change, and overwrites it. The lock is the partial unique index uq_cr_open_namespace, so its
WHERE list gains applied and merge_failed. No row can hold either before this revision, so the new index cannot meet a duplicate.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

BEFORE = "('pending_approval', 'approved', 'pr_open', 'merged', 'awaiting_prune', 'sync_failed')"
AFTER = "('pending_approval', 'approved', 'pr_open', 'applied', 'merge_failed', 'merged', 'awaiting_prune', 'sync_failed')"


def _index(states: str) -> None:
    op.execute("DROP INDEX uq_cr_open_namespace")
    op.execute(f"CREATE UNIQUE INDEX uq_cr_open_namespace ON change_requests (cluster_id, namespace) WHERE status IN {states}")


def upgrade() -> None:
    _index(AFTER)


def downgrade() -> None:
    # An applied or merge_failed row would then hold no lock: refuse, rather than drop the guarantee.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM change_requests WHERE status IN ('applied', 'merge_failed')) THEN "
               "RAISE EXCEPTION 'applied or merge_failed requests exist: merge them before the downgrade'; END IF; END $$")
    _index(BEFORE)
