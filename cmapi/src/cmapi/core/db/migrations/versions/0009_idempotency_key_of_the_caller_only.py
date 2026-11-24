"""An Idempotency-Key belongs to the caller that sent it: release 2 of 2, the contract step (#603).

Release 1 (0008, #592) added `change_requests.idempotency_sub` and the caller's unique index `uq_cr_idempotency_caller`,
and kept the requester's `uq_cr_idempotency (requester_sub, idempotency_key)` so that 0007 pods kept working. This
migration ships once release 1 is deployed everywhere and no 0007 pod runs (the owner's decision on PR #601). It removes
the old version, as Fowler's ParallelChange (2014) has the contract phase "remove the old version and change the interface
so that it only supports the new version". The Idempotency-Key draft (draft-ietf-httpapi-idempotency-key-header-09,
section 5) asks for "a unique composite key as the idempotent cache lookup key", combining the client's key "with other
client specific attributes known only to the resource": here, the caller's token subject.

The upgrade runs in one transaction (migrations/env.py):

1. It locks `change_requests` in ACCESS EXCLUSIVE mode, first, so that no insert comes between the checks and the updates.
   DROP INDEX takes the same lock later in this transaction, so taking it first makes the migration wait no longer.
2. It refuses, and changes nothing, while a live key (created less than 24 hours ago) cannot be given one owner:
   - a keyed row with no `idempotency_sub` (a 0007 pod wrote it in release 1's window) that is delegated
     (`requester` has `submittedBy` or `submittedByClient`) and has no `submittedBySub` to name its caller;
   - two live rows with the same key and the same caller, by release 1's `key_owner`:
     `COALESCE(idempotency_sub, requester->>'submittedBySub', requester_sub)`. A 0007 pod's insert has no
     `idempotency_sub`, and NULLs are distinct in `uq_cr_idempotency_caller`, so one service's key used for two persons
     in the window is two rows (#601 review, the risk accepted until 0009). Choosing one would end a live key early.
   No other live pair needs a refusal. The requester's index was in force over every keyed row until this migration, so
   no two rows share `(requester_sub, idempotency_key)` and dropping it changes no stored row and no retry of a stored
   request. What it changes is the answer to a new request from another caller for the same person: a person using a
   key that a service holds for them, or a service using the person's key, was 409 "Idempotency-Key is in use for another
   request", naming no request; it is now that caller's own 202. That is the fix this release ships (#603), and no caller
   could learn of another's request from the 409. The same migration succeeds once the refused rows are over 24 hours old.
3. It clears the keys older than 24 hours, as `RequestRepo.by_idempotency` would before any lookup, so that an expired
   row cannot meet a live one in the caller's index when the next step fills it.
4. It fills the caller of each keyed row that has none: `requester.submittedBySub` when a service sent the request for a
   person, otherwise `requester_sub` (0008's rule, from 0007's `Requester.record`, core/identity/checks.py).
5. It adds the check `ck_cr_idempotency_caller`: a row that holds a key names its caller. The caller's index is now the
   only one, and NULLs are distinct in it, so a keyed row with no caller would be under no unique index and invisible to
   the lookup. A 0007 image started by mistake on this schema migrates nothing (0009 is a later release's revision to it,
   core/db/migrate.py) and would write such rows; the check refuses them instead.
6. It drops `uq_cr_idempotency`.

Locks. ACCESS EXCLUSIVE on `change_requests` from the first statement until commit: reads and writes of the table wait
through the checks, the updates, the check's scan and the drop. The 30-second `lock_timeout` of migrations/env.py limits
each attempt to acquire a lock, not the work after it. CONCURRENTLY is not used: PostgreSQL 16 runs neither
CREATE INDEX CONCURRENTLY nor DROP INDEX CONCURRENTLY inside a transaction block, and the refusal relies on this migration
being all or nothing.

The downgrade restores release 1's schema, so that release 1's image can run again. It refuses, and changes nothing,
while two live rows share a requester and a key: this release lets a person and a service that writes for them hold the
same key, and the requester's index cannot hold both. It succeeds once all but one row of each such pair are over 24 hours
old. It clears the expired keys, for the same reason as the upgrade, then creates `uq_cr_idempotency` and drops the check.
Every keyed row keeps its caller, which release 1's code reads.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# IDEMPOTENCY_HOURS of core/db/repo.py on the day of this migration, and the bounds of its lookup: older than 24 hours is
# expired. A migration keeps its own copy, so that it does the same thing whenever it runs.
_LIVE = "idempotency_key IS NOT NULL AND created_at >= now() - interval '24 hours'"
_EXPIRED = "idempotency_key IS NOT NULL AND created_at < now() - interval '24 hours'"
# Release 1's key_owner (core/db/repo.py at 0008): the caller that this code wrote, else the one 0008's backfill takes.
_OWNER = "COALESCE(idempotency_sub, requester->>'submittedBySub', requester_sub)"
_DELEGATED_WITHOUT_CALLER = """(requester ? 'submittedBy' OR requester ? 'submittedByClient')
           AND (jsonb_typeof(requester->'submittedBySub') IS DISTINCT FROM 'string' OR requester->>'submittedBySub' = '')"""
_CLEAR_EXPIRED = (f"UPDATE change_requests SET idempotency_key = NULL, idempotency_fingerprint = NULL, idempotency_sub = NULL "
                  f"WHERE {_EXPIRED}")


def _lock() -> None:
    op.execute("LOCK TABLE change_requests IN ACCESS EXCLUSIVE MODE")


def _shared(group_by: str):
    """The live rows that share `group_by` and a key, as "a, b; c, d" by request id, or None."""
    return op.get_bind().execute(sa.text(f"""
        SELECT string_agg(ids, '; ' ORDER BY ids) FROM (
               SELECT string_agg(request_id, ', ' ORDER BY request_id) AS ids FROM change_requests WHERE {_LIVE}
                GROUP BY {group_by}, idempotency_key HAVING count(*) > 1) shared""")).scalar()


def _refuse_live_keys_without_one_owner() -> None:
    """Raise, so that the transaction rolls back, when a live key has no single owner. Each message names the rows."""
    ambiguous = op.get_bind().execute(sa.text(f"""
        SELECT string_agg(request_id, ', ' ORDER BY request_id) FROM change_requests
         WHERE {_LIVE} AND idempotency_sub IS NULL AND {_DELEGATED_WITHOUT_CALLER}""")).scalar()
    if ambiguous:
        raise RuntimeError(f"0009 refused, nothing changed: the live delegated requests {ambiguous} hold an Idempotency-Key "
                           "but neither idempotency_sub nor requester.submittedBySub, so their caller is not known. Run the "
                           "migration again once they are more than 24 hours old (#603).")
    collisions = _shared(_OWNER)
    if collisions:
        raise RuntimeError(f"0009 refused, nothing changed: live requests share one caller's Idempotency-Key ({collisions}). "
                           "A 0007 pod wrote them in release 1's window. The caller's unique index cannot hold them, and no "
                           "live key is ended early. Run the migration again once all but one request of each group are "
                           "more than 24 hours old (#603).")


def upgrade() -> None:
    _lock()
    _refuse_live_keys_without_one_owner()
    op.execute(_CLEAR_EXPIRED)
    op.execute("UPDATE change_requests SET idempotency_sub = COALESCE(requester->>'submittedBySub', requester_sub) "
               "WHERE idempotency_key IS NOT NULL AND idempotency_sub IS NULL")
    op.create_check_constraint("ck_cr_idempotency_caller", "change_requests",
                               "idempotency_key IS NULL OR idempotency_sub IS NOT NULL")
    op.drop_index("uq_cr_idempotency", table_name="change_requests")


def downgrade() -> None:
    _lock()
    shared = _shared("requester_sub")
    if shared:
        raise RuntimeError(f"0009 downgrade refused, nothing changed: live requests share one requester's Idempotency-Key "
                           f"({shared}), which release 1's index on (requester_sub, idempotency_key) cannot hold. Run the "
                           "downgrade again once all but one request of each group are more than 24 hours old (#603).")
    op.execute(_CLEAR_EXPIRED)
    op.create_index("uq_cr_idempotency", "change_requests", ["requester_sub", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.drop_constraint("ck_cr_idempotency_caller", "change_requests", type_="check")
