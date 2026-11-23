"""An Idempotency-Key belongs to the caller that sent it, not to the person a request is for (#592).

The row held the key under `requester_sub`, the person, and `_replay` looked it up under the caller's subject. With
`onBehalfOf` the two differ, so a service's retry missed its own request and got 409, while the person could replay the
service's request with the service's key. `idempotency_sub` holds the caller's subject, and the unique index moves to
`(idempotency_sub, idempotency_key)`. The owner's decision (option A, 2026-11-23) on #592, and the Idempotency-Key draft
(draft-ietf-httpapi-idempotency-key-header-09, section 5): "implement a unique composite key as the idempotent cache lookup
key. For example, a composite key MAY be implemented by combining the idempotency key sent by the client with other client
specific attributes known only to the resource."

The upgrade, in one transaction (migrations/env.py):

1. Adds the column, nullable and without a default, which PostgreSQL does without rewriting the table. Null is right for a
   row with no key, and an older image that does not know the column must keep inserting after a rollback (docs/12).
2. Clears the keys older than 24 hours. `RequestRepo.by_idempotency` clears such a key before it looks one up, so an
   expired key never replays; clearing it here first keeps the expired keys out of step 4.
3. Backfills the caller: `requester.submittedBySub` when a service sent the request for a person, else `requester_sub`,
   which was the caller (`Requester.record`, core/identity/checks.py). A key stored before this migration stays valid for
   the caller that sent it, for the rest of its 24 hours.
4. Keeps one key for each `(caller, key)`. The old index allowed the same key from one service for two persons, or for a
   person and for itself; the new one does not. The row the caller could already replay (its own, where `requester_sub`
   is the caller) keeps the key, else the newest. The others lose their key, as an expired key does.
5. Moves the unique index, under the same name, so the conflict that `RequestRepo.insert` maps to 409 keeps its name.

A plain CREATE UNIQUE INDEX, not CONCURRENTLY: PostgreSQL 16 does not allow CONCURRENTLY inside a transaction block, and
this migration must stay all or nothing. The table has one row for each write request, and the build blocks only writes
while it runs; the 30 s lock_timeout of migrations/env.py bounds the wait for the lock.

The downgrade does the reverse: steps 2 and 4 again for `(requester_sub, key)`, where the new index allowed a person's own
key beside a service's same key for that person, keeping the person's own row; then the old index, and the column dropped.

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
# thing whenever it runs, whatever the code says later.
_EXPIRED = "idempotency_key IS NOT NULL AND created_at < now() - interval '24 hours'"


def _clear_expired_keys(also: str = "") -> None:
    op.execute(f"UPDATE change_requests SET idempotency_key = NULL, idempotency_fingerprint = NULL{also} WHERE {_EXPIRED}")


def _keep_one_key_per(owner: str, own: str, also: str = "") -> None:
    """Clear the key of each row but one among the rows that share `(owner, idempotency_key)`. The kept row is the one
    where `own` holds, then the newest."""
    op.execute(f"""
        UPDATE change_requests SET idempotency_key = NULL, idempotency_fingerprint = NULL{also}
         WHERE request_id IN (
               SELECT request_id FROM (
                      SELECT request_id, row_number() OVER (
                             PARTITION BY {owner}, idempotency_key
                             ORDER BY ({own}) DESC, created_at DESC, request_id DESC) AS n
                        FROM change_requests WHERE idempotency_key IS NOT NULL) ranked
                WHERE n > 1)""")


def upgrade() -> None:
    op.add_column("change_requests", sa.Column("idempotency_sub", sa.String(100), nullable=True))
    _clear_expired_keys()
    op.execute("UPDATE change_requests SET idempotency_sub = COALESCE(requester->>'submittedBySub', requester_sub) "
               "WHERE idempotency_key IS NOT NULL")
    _keep_one_key_per("idempotency_sub", "requester_sub = idempotency_sub", also=", idempotency_sub = NULL")
    op.drop_index("uq_cr_idempotency", table_name="change_requests")
    op.create_index("uq_cr_idempotency", "change_requests", ["idempotency_sub", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_cr_idempotency", table_name="change_requests")
    _clear_expired_keys()
    # A row with a key and no caller came from an older image after a rollback, which keyed it by requester_sub.
    _keep_one_key_per("requester_sub", "COALESCE(idempotency_sub, requester_sub) = requester_sub")
    op.create_index("uq_cr_idempotency", "change_requests", ["requester_sub", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.drop_column("change_requests", "idempotency_sub")
