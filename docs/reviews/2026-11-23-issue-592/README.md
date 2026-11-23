# #592: an Idempotency-Key belongs to its caller (release 1 of 2)

This is the implementer's record, written by Opus 5.5 at `high` on 2026-11-23, on `fix/592-idempotency-caller` from
`8a5b41c`. The first head, `628a6c5`, moved the unique index in one step. Codex astra reviewed it
(`workbench/cmapi/review-601/codex-result.txt`), and the owner then decided on expand and contract (#592, the last comment).
This record describes the reworked head.

## The defect, as measured

Reviewer 2 of PR #589 measured it, and the probe `workbench/cmapi/wt-591-evidence/592-probe.txt` repeated it.

- The service `svc-payments-ci` writes `onBehalfOf: ola` with the key `svc-key-1`, and the answer is 202.
- Its retry is 409 `idempotency-replay`, "Idempotency-Key is in use for another request".
- `ola`, sending the service's key with the same body, gets 202 and the service's request.

The cause: `Pipeline.submit` stored the key under `requester_sub`, the person, and `_replay` looked it up under `who.sub`,
the caller.

## The owner's decisions

1. On #592, option A: the key belongs to the caller, held in a column `idempotency_sub`, and filled from
   `COALESCE(requester->>'submittedBySub', requester_sub)`.
2. On PR #601, expand and then contract. Release 1, migration 0008, adds and fills the column, and keeps the old index so
   that 0007 pods work through the rollout and after an image-only rollback. Release 2, migration 0009 (#603), comes once
   no 0007 pod runs. The migrations refuse until rows expire: a live collision, or a live delegated row with no caller,
   stops the migration, which changes nothing and succeeds once those rows are more than 24 hours old.

The CRC data, read-only (#592): 19 rows, 0 live keys, 0 collisions, 0 ambiguous rows. The API runs 1 replica, with
`maxSurge: 1` and `maxUnavailable: 0`.

## Sources, fetched 2026-11-23

- **draft-ietf-httpapi-idempotency-key-header-09**, 21 November 2026,
  <https://www.ietf.org/archive/id/draft-ietf-httpapi-idempotency-key-header-09.txt>.
  - Section 5: "On the resource, implement a unique composite key as the idempotent cache lookup key. For example, a
    composite key MAY be implemented by combining the idempotency key sent by the client with other client specific
    attributes known only to the resource."
  - Section 2.2: "A resource MAY define what makes a key unique".
  - Section 2.4: "If the fingerprint does not match, the resource fails the request ... and does not return the result of
    the original request."
  - Section 2.7 suggests 422 for a reused key with another payload. cmapi answers 409, as docs/02 decides. This PR leaves
    that unchanged; the coordinator was told of the divergence.
- **Fowler, ParallelChange**, 13 May 2014, <https://martinfowler.com/bliki/ParallelChange.html>. Expand: "you augment the
  interface to support both the old and the new versions". Contract: "remove the old version and change the interface so
  that it only supports the new version."
- **PostgreSQL 16, Explicit Locking**, <https://www.postgresql.org/docs/16/explicit-locking.html>. ACCESS EXCLUSIVE "guarantees
  that the holder is the only transaction accessing the table in any way", and "Once acquired, a lock is normally held until
  the end of the transaction."
- **PostgreSQL 16, CREATE INDEX**, <https://www.postgresql.org/docs/16/sql-createindex.html>: "a regular CREATE INDEX command
  can be performed within a transaction block, but CREATE INDEX CONCURRENTLY cannot." On a unique index: "The default is
  that they are distinct, so that a unique index could contain multiple null values in a column."
- **PostgreSQL 16, ALTER TABLE**, <https://www.postgresql.org/docs/16/sql-altertable.html>: "An ACCESS EXCLUSIVE lock is
  acquired unless explicitly noted", and "If no DEFAULT is specified, NULL is used. In neither case is a rewrite of the table
  required."

## Decisions in release 1

| Decision | Evidence |
|---|---|
| Keep `uq_cr_idempotency (requester_sub, key)` | 0007 pods look up, and map their 409, by it. The mixed-version probe, which ran 0007's own code (`8a5b41c`) on the 0008 schema, shows them working: `outputs/mixed-version-probe.txt`, step 2 |
| Add a second unique index, `uq_cr_idempotency_caller (idempotency_sub, key) WHERE idempotency_key IS NOT NULL` | Without it, one service can hold one key for two persons. Mutant 2 makes only this index non-unique, and the second person's request then gets 202 (a second request) where 409 is expected: `outputs/mutants-unique-indexes.txt`. NULLs are distinct, so a 0007 pod's inserts with no `idempotency_sub` still succeed (probe, step 2) |
| The 409 for both indexes | `RequestRepo.insert` maps either index (`IDEMPOTENCY_INDEXES`) to 409 `idempotency-replay`, and `_submit` then looks the key up again under the caller. If the caller holds the key, the answer is its request. If only the requester's index refused, for example a person using a key that a service holds for them, the second lookup misses and the answer stays 409, "Idempotency-Key is in use for another request", naming no request. This is measured: `test_the_person_cannot_replay_the_service_request_with_its_key`, and probe step 3. Release 2 drops that index (#603). When the namespace lock and an idempotency index both refuse, the answer is the conflict that PostgreSQL reports first. The test accepts either 409 and requires that neither names the service's request |
| A new pod reads a keyed row with no `idempotency_sub` (written by a 0007 pod in the window) | `key_owner()` = `COALESCE(idempotency_sub, requester->>'submittedBySub', requester_sub)`, the same rule as 0008's backfill. 0007's `Requester.record` writes `submittedBySub` exactly when a service sent for a person, so the rule names the true caller. `by_idempotency` looks up and expires by it, oldest row first. Measured: `test_a_row_that_a_0007_pod_wrote_after_0008_belongs_to_its_caller`, and probe step 3, which replays 0007-written `req-20261123-0002` for the service and `req-20261123-0003` for ola |
| Refuse, never drop | Before any update, the upgrade checks under the table's ACCESS EXCLUSIVE lock. It raises, naming the rows, on a live delegated row with no string `submittedBySub`, and on one caller's key held by two live rows. The transaction rolls back, so the revision stays 0007 and no row changes. It succeeds once the rows are over 24 hours old. Tests: `test_the_upgrade_refuses_a_live_collision_and_succeeds_once_it_expires` and `test_the_upgrade_refuses_a_live_delegated_row_without_its_caller` |
| Keep clearing expired keys | Still needed. Without it, expired rows that share a caller and a key would be backfilled into the new unique index, and its build would fail on rows that can never replay anyway. `by_idempotency` already clears an expired key before it looks one up, so clearing them changes nothing that a caller can observe |
| The downgrade only drops the caller's index and the column | The requester's index was in force the whole time, so no two rows share a person and a key, and the downgrade has nothing to refuse and no key to clear. `test_the_downgrade_keeps_every_key_and_the_old_index` |
| Nullable, no default, one transaction, no CONCURRENTLY | A row with no key has no caller. CONCURRENTLY cannot run inside a transaction block, and the refusal relies on the migration being all or nothing |
| `REQUIRED_REVISION` is `0008` | This code writes `idempotency_sub`. `/readyz` on 0007 is 503 (`test_second_pass_converged.py`) |

**Locks** (Codex finding 3, adapted). The upgrade acquires ACCESS EXCLUSIVE on `change_requests` when it adds the column, and
the downgrade acquires it when it drops the index. Reads and writes of this table wait through the checks, the updates and
the index build, until commit. The 30-second `lock_timeout` limits each attempt to acquire a lock. It does not limit the
work done after acquisition, or the total migration time. The migrator takes its session advisory lock before it sets this
timeout. Measured on PostgreSQL 16 (`outputs/lock-probe.txt`): while another session holds each statement uncommitted, a
SELECT and an UPDATE on the table get `55P03` under a 100 ms `lock_timeout`, and `pg_locks` shows `AccessExclusiveLock`.

## What each pod version does in the window (measured, `outputs/mixed-version-probe.txt`)

| Step | Pod | Call | Answer |
|---|---|---|---|
| 1 | new | Service, `onBehalfOf: ola`, key `new-svc` | 202 `req-20261123-0001`, `idempotency_sub` = the service |
| 2 | 0007 | `ola` sends `new-svc` with that body | 202 `req-20261123-0001`: 0007's defect, live while any 0007 pod serves |
| 2 | 0007 | The service retries `new-svc` | 409 `idempotency-replay`, 0007's defect |
| 2 | 0007 | Service `old-svc`, then its retry | 202 `req-20261123-0002`, then 409, 0007's defect; the row has `idempotency_sub` NULL |
| 2 | 0007 | `ola` own key `old-ola`, then retry | 202 `req-20261123-0003`, then 202 replay, its old caller |
| 3 | new | The service retries `old-svc` | 202 `req-20261123-0002`, by `key_owner` |
| 3 | new | `ola` retries `old-ola` | 202 `req-20261123-0003` |
| 3 | new | `ola` sends `old-svc` with her own body | 409 "in use for another request", naming no request |
| 3 | new | `ola` sends `new-svc` with its body | 422 `on-behalf-of-not-allowed` |

## Tests

The tests are in `cmapi/tests/service/test_idempotency_caller_592.py`. The before outputs are in `outputs/`.

| Test | 8a5b41c | 628a6c5 | This head |
|---|---|---|---|
| `test_a_service_retry_on_behalf_of_a_person_replays_its_request` | fail (409) | pass | pass |
| `test_a_service_retry_that_loses_the_race_gets_the_closed_winner` | fail (409) | pass | pass; fails when the indexes are non-unique (mutant 1) |
| `test_one_service_key_for_a_second_person_is_refused_by_the_caller_index` | fail (202) | pass | pass; fails without the caller's unique index (mutant 2) |
| `test_the_person_cannot_replay_the_service_request_with_its_key` | fail (202 replay) | fail (202, the release-2 answer) | pass |
| `test_a_person_own_retry_still_replays` | fail (no column) | pass | pass |
| `test_a_service_key_is_free_again_after_24_hours` | fail (409) | pass | pass |
| `test_a_row_that_a_0007_pod_wrote_after_0008_belongs_to_its_caller` | fail | fail (409 change-pending, no replay) | pass |
| `test_the_upgrade_keys_each_stored_key_on_its_caller_and_keeps_the_old_index` | fail | fail (old index replaced) | pass |
| `test_the_upgrade_refuses_a_live_collision_and_succeeds_once_it_expires` | fail | fail (migrated, keys dropped) | pass |
| `test_the_upgrade_refuses_a_live_delegated_row_without_its_caller` | fail | fail (migrated) | pass |
| `test_the_downgrade_keeps_every_key_and_the_old_index` | fail | fail (expired key cleared) | pass |
| `test_keys_written_by_this_code_replay_after_a_schema_round_trip` | fail | pass | pass. This code at both ends; it does not run 0007's code (the probe does) |

## Measured, inferred, not tested

- **Measured** on PostgreSQL 16.15 at `127.0.0.1:55432`, on macOS: the tests above, on three code versions; the two
  mutants; the mixed-version probe with 0007's own code; the lock probe; and the full service suite on this head (in the
  PR).
- **Inferred from the code:**
  - The backfill and `key_owner` name each 0007 row's true caller (`Requester.record`, core/identity/checks.py).
  - `key_owner` is an expression lookup that neither unique index serves. That costs one scan of `change_requests` for
    each keyed write until #603 removes it. The cost is not measured; CRC has 19 rows.
- **Not tested:**
  - The migration on CRC's data. It runs in a later deploy run, and the read-only count on #592 shows nothing it would
    refuse.
  - A real rolling update on a cluster.
  - Concurrent races between a 0007 pod and a new pod. The `.first()` ordering covers them but was not exercised.
