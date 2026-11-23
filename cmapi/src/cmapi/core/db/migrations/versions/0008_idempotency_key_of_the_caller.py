"""An Idempotency-Key belongs to the caller that sent it: release 1 of 2, the expand step (#592).

The row held the key under `requester_sub`, the person, and `_replay` looked it up under the caller's subject. With
`onBehalfOf` the two differ, so a service's retry missed its own request and got 409, and the person could replay the
service's request with the service's key. The owner's decision on #592 is option A. On PR #601 it is expand, then contract
(Fowler, ParallelChange, 2014: in the expand phase "you augment the interface to support both the old and the new
versions"). The Idempotency-Key draft
(draft-ietf-httpapi-idempotency-key-header-09, section 5) asks for "a unique composite key as the idempotent cache lookup
key", combining the client's key "with other client specific attributes known only to the resource".

Release 1, this migration, adds `idempotency_sub`, fills it, and adds a second unique index on
`(idempotency_sub, idempotency_key)`. It keeps the old index on `(requester_sub, idempotency_key)`, so a 0007 pod still
works on this schema, both during a rolling update and after an image-only rollback (docs/12). Release 2 (0009) fills the
keyed rows that 0007 pods wrote without a caller, and then keeps only the caller's index (#603).

The upgrade runs in one transaction (migrations/env.py):

1. It adds the column, nullable and with no default. A row with no key has no caller, and a 0007 pod inserts without the
   column.
2. It refuses, and changes nothing, while a live key (created less than 24 hours ago) cannot be given one owner. That is
   the case for:
   - a delegated row (`requester` has `submittedBy` or `submittedByClient`) that has no `submittedBySub` to name the
     caller;
   - two live rows with the same key and the same caller, which the old index allowed: for example, one service's key used
     for two persons. The new index forbids them, and choosing one row would end a live key early.
   The same migration succeeds once those rows are more than 24 hours old.
3. It clears the keys older than 24 hours. `RequestRepo.by_idempotency` clears such a key before it looks one up, so an
   expired key never replays. Clearing them keeps expired pairs out of the new unique index.
4. It fills the caller: `requester.submittedBySub` when a service sent the request for a person, otherwise `requester_sub`
   (`Requester.record`, core/identity/checks.py). A key stored before this migration stays valid for its caller for the
   rest of its 24 hours.
5. It creates the unique index `uq_cr_idempotency_caller`.

Locks. The upgrade takes ACCESS EXCLUSIVE on `change_requests` when it adds the column, and the downgrade takes it when it
drops the index. Each holds the lock until commit, so reads and writes of this table wait through the checks, the updates
and the index build. The 30-second `lock_timeout` of migrations/env.py limits each attempt to acquire a lock. It does not
limit the work done after the lock is acquired, or the whole migration. The migrator takes its session advisory lock before
it sets that timeout. CONCURRENTLY is not used: PostgreSQL 16 does not allow it inside a transaction block, and this
migration must stay all or nothing.

The downgrade drops the new index and the column. The old index was in force the whole time, so no two rows share a
person and a key, and the downgrade clears no key.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# IDEMPOTENCY_HOURS of core/db/repo.py on the day of this migration. A migration keeps its own copy: it must do the same
# thing whenever it runs, whatever the code says later. The bounds are the lookup's: older than 24 hours is expired.
_LIVE = "idempotency_key IS NOT NULL AND created_at >= now() - interval '24 hours'"
_EXPIRED = "idempotency_key IS NOT NULL AND created_at < now() - interval '24 hours'"
# The caller of a row that 0007 wrote: the service that sent it for a person, or else the requester, who sent it.
_CALLER = "COALESCE(requester->>'submittedBySub', requester_sub)"


def _refuse_live_keys_without_one_owner() -> None:
    """Raise, so that the transaction rolls back, when a live key has no single owner. Each message names the rows."""
    bind = op.get_bind()
    ambiguous = bind.execute(sa.text(f"""
        SELECT string_agg(request_id, ', ' ORDER BY request_id) FROM change_requests
         WHERE {_LIVE} AND (requester ? 'submittedBy' OR requester ? 'submittedByClient')
           AND (jsonb_typeof(requester->'submittedBySub') IS DISTINCT FROM 'string'
                OR requester->>'submittedBySub' = '')""")).scalar()
    if ambiguous:
        raise RuntimeError(f"0008 refused, nothing changed: the live delegated requests {ambiguous} hold an Idempotency-Key "
                           "but no requester.submittedBySub, so their caller is not known. Run the migration again once "
                           "they are more than 24 hours old (#592).")
    collisions = bind.execute(sa.text(f"""
        SELECT string_agg(ids, '; ' ORDER BY ids) FROM (
               SELECT string_agg(request_id, ', ' ORDER BY request_id) AS ids FROM change_requests WHERE {_LIVE}
                GROUP BY {_CALLER}, idempotency_key HAVING count(*) > 1) shared""")).scalar()
    if collisions:
        raise RuntimeError(f"0008 refused, nothing changed: live requests share one caller's Idempotency-Key ({collisions}). "
                           "The caller's unique index cannot hold them, and no live key is ended early. Run the migration "
                           "again once all but one request of each group are more than 24 hours old (#592).")


def upgrade() -> None:
    # First, so that the checks and the updates below run under the table's lock and no insert can come between them.
    op.add_column("change_requests", sa.Column("idempotency_sub", sa.String(100), nullable=True))
    _refuse_live_keys_without_one_owner()
    op.execute(f"UPDATE change_requests SET idempotency_key = NULL, idempotency_fingerprint = NULL WHERE {_EXPIRED}")
    op.execute(f"UPDATE change_requests SET idempotency_sub = {_CALLER} WHERE idempotency_key IS NOT NULL")
    op.create_index("uq_cr_idempotency_caller", "change_requests", ["idempotency_sub", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_cr_idempotency_caller", table_name="change_requests")
    op.drop_column("change_requests", "idempotency_sub")
