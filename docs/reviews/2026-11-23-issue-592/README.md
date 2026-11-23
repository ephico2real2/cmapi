# #592: an Idempotency-Key belongs to its caller

The implementer's record: Opus 5.5 at `high`, 2026-11-23, on `fix/592-idempotency-caller` from `8a5b41c`. The reviews go
beside it when they are done.

## The defect, as measured

Reviewer 2 of PR #589 measured it, and the probe `workbench/cmapi/wt-591-evidence/592-probe.txt` repeated it. Service
`svc-payments-ci` writes `onBehalfOf: ola` with key `svc-key-1`. The first answer is 202 `req-20261123-0001`. The stored
row has `requester_sub = sub-ola` and `requester.submittedBySub = sub-service-account-svc-payments-ci`. The same retry is
409 `idempotency-replay`, "Idempotency-Key is in use for another request". `ola` sending the service's key with the same
body gets 202 and the service's request. The cause: `Pipeline.submit` stored the key under `requester_sub` (the person),
and `_replay` looked it up under `who.sub` (the caller).

## The owner's decision

Option A on #592, 2026-11-23: key on the caller, with a column. Migration 0008 adds `change_requests.idempotency_sub`,
backfills `COALESCE(requester->>'submittedBySub', requester_sub)` for the rows that hold a key, and moves the unique index
to `(idempotency_sub, idempotency_key)`. `_replay` looks up by `who.sub`.

## Sources, fetched 2026-11-23

- draft-ietf-httpapi-idempotency-key-header-09, 21 November 2026,
  <https://www.ietf.org/archive/id/draft-ietf-httpapi-idempotency-key-header-09.txt>.
  - Section 5: "On the resource, implement a unique composite key as the idempotent cache lookup key. For example, a
    composite key MAY be implemented by combining the idempotency key sent by the client with other client specific
    attributes known only to the resource." The client is the caller that sent the key, so the composite is
    `(caller's subject, key)`. Section 5 also lists "Data leaks - When an idempotency implementation allows low entropy
    keys, attackers MAY determine other keys and use them to fetch existing idempotent cache entries, belonging to other
    clients." Before the fix, a person could fetch a service's entry with the service's key.
  - Section 2.2: "An idempotency key is an opaque value. A resource MAY define what makes a key unique". cmapi defines a
    key as unique for each caller.
  - Section 2.4: "If the fingerprint does not match, the resource fails the request as described in Section 2.7 and does
    not return the result of the original request." The same caller's key with another body is still 409
    `idempotency-replay`. Section 2.7 suggests 422 for that case. cmapi answers 409, as it did before; this fix does not
    change that.
- PostgreSQL 16, CREATE INDEX, <https://www.postgresql.org/docs/16/sql-createindex.html>: "a regular CREATE INDEX command
  can be performed within a transaction block, but CREATE INDEX CONCURRENTLY cannot." And: "Other transactions can still
  read the table, but if they try to insert, update, or delete rows in the table they will block until the index build is
  finished." On NULLs: "The default is that they are distinct, so that a unique index could contain multiple null values
  in a column."
- PostgreSQL 16, ALTER TABLE, <https://www.postgresql.org/docs/16/sql-altertable.html>: "If no DEFAULT is specified, NULL
  is used. In neither case is a rewrite of the table required."
- Alembic, `autocommit_block`, <https://alembic.sqlalchemy.org/en/latest/api/runtime.html>: "the database transaction
  preceding the block is unconditionally committed."

## Choices

| Choice | Why |
|---|---|
| `idempotency_sub` is nullable, with no default and no CHECK | A row with no key has no caller of a key, and the revert job submits with no key (`jobs/open_pr.py`). docs/12 says an older image must keep running on a later schema. 0007's code inserts without the column, so NOT NULL or a CHECK tying it to the key would break its inserts after a rollback. Adding it with no default does not rewrite the table (ALTER TABLE, above) |
| The insert sets `idempotency_sub = who.sub` only when there is a key; the 24-hour expiry clears it with the key | One rule: the column is null exactly when the key is. That covers every row this code writes |
| A plain `CREATE UNIQUE INDEX` inside the migration's transaction, not CONCURRENTLY | CONCURRENTLY cannot run in a transaction block. Alembic's `autocommit_block` would commit the earlier steps, and `migrations/env.py` relies on transactional DDL to make each migration all or nothing. The table has one row for each write request. The build blocks writes, not reads, while it runs, and the 30 s `lock_timeout` in env.py bounds the wait for the lock |
| The new index keeps the name `uq_cr_idempotency` | `RequestRepo.insert` maps a violation of that name to 409. 0007's code maps it the same way, so it keeps working after a rollback |
| The upgrade first clears the keys older than 24 hours | `by_idempotency` clears such a key before it looks one up, so an expired key never replays. Clearing them first keeps them out of the next step. `updated_at` does not move, as with the lookup's own clear |
| One key is kept for each `(caller, key)` | The old index on `(requester_sub, key)` allowed one service the same key for two persons, or for a person and for itself. The new index does not, and creating it would fail on such rows. The row the caller could already replay keeps the key (`requester_sub` equal to the caller). If no row is the caller's own, the newest keeps it. The others lose their key, fingerprint and caller, like an expired key |
| The downgrade does the same for `(requester_sub, key)`, then restores the old index and drops the column | At 0008, a person's own key and a service's same key for that person can both be held. The person's own row keeps the key, because 0007 could replay it. A row with a key and no caller was written by 0007's code after a rollback, which keyed it on `requester_sub`, so it also counts as the person's own |
| `REQUIRED_REVISION` becomes `0008` | This code writes `idempotency_sub`, so `/readyz` must not pass on 0007 (`test_second_pass_converged.py` now says so) |

A person who sends a service's key gets what a new key of their own gets. The same body with `onBehalfOf` is 422
`on-behalf-of-not-allowed`. A body for a namespace that the service's request holds is 409 `change-pending`. A body for
another namespace is 202 with a new request.

## Tests: before (`8a5b41c`) and after (this branch)

`cmapi/tests/service/test_idempotency_caller_592.py`. The output from before is in
[`outputs/tests-before-8a5b41c.txt`](outputs/tests-before-8a5b41c.txt).

| Test | Before | After |
|---|---|---|
| `test_a_service_retry_on_behalf_of_a_person_replays_its_request` | 409 `idempotency-replay` on the retry | 202, same `requestId`, also after a cancel (`cancelled`). Another body is 409 naming its own request |
| `test_a_service_retry_that_loses_the_race_gets_the_winner` | 409 | 202, the winner's `requestId`; both lookups use the service's subject |
| `test_the_person_cannot_replay_the_service_request_with_its_key` | 202, the service's request (expected 422) | 422 `on-behalf-of-not-allowed`, then 409 `change-pending`, then 202 with a new request |
| `test_a_person_own_retry_still_replays` | The replay passes; the column check fails (no column) | Passes |
| `test_a_service_key_is_free_again_after_24_hours` | 409: the expired key, held under the person, blocked the service | 202, a new request; the old row's key, fingerprint and caller are cleared |
| `test_the_upgrade_keys_each_stored_key_on_its_caller` | The index is still `(requester_sub, idempotency_key)` | Each row as the table above says |
| `test_the_downgrade_keys_each_stored_key_on_its_requester_again` | No column to insert | The person's own key is kept, the old index is back, and the column is dropped |
| `test_a_key_stored_before_the_upgrade_replays_after_it` | No column | Through HTTP: rows written by the app, taken down to 0007 and up to 0008, and both retries replay |

## Measured, inferred, not tested

- **Measured** on PostgreSQL 16.15 (`127.0.0.1:55432`, macOS): each test above, before and after, and the full service
  suite on this branch. Also the contract lint, the oasdiff gate against `main` (no breaking change), the changelog and
  docs/04 checks, the portal types check, and `doc-citations.py --check`.
- **Inferred from the code, not tested.** For each row 0007 wrote, `COALESCE(requester->>'submittedBySub', requester_sub)`
  is the caller: `Requester.record` writes `submittedBySub = caller.sub` exactly when the person is not the caller
  (`core/identity/checks.py`). Also inferred: 0007's image on the 0008 schema inserts with a null `idempotency_sub`, and
  those keys do not replay after the next upgrade (docs/12).
- **Not tested:** the migration on CRC's data. It runs in a later deploy run. How many rows the dedupe step clears there
  is not known until then.
