# #603: migration 0009, the caller's index is the only one (release 2 of #592)

This is the implementer's record, written by Opus 5.5 at `high` on 2026-11-23, on `fix/603-idempotency-release-2` from
`cb59e19`. It follows the owner's decisions on PR #601 (expand, then contract; refuse, never drop), which are decided and
are not reopened here.

**The precondition.** Release 1 (0008) is deployed: CRC has run it since run 36, and run 37 runs `365b4b9`. No 0007 pod
runs (the coordinator's brief).

## Sources, fetched 2026-11-23

- **draft-ietf-httpapi-idempotency-key-header-09**, 21 November 2026, the newest version (the datatracker's API gives
  `rev` 09, `time` 2026-11-21T10:57:55Z),
  <https://www.ietf.org/archive/id/draft-ietf-httpapi-idempotency-key-header-09.txt>.
  - Section 5: "On the resource, implement a unique composite key as the idempotent cache lookup key. For example, a
    composite key MAY be implemented by combining the idempotency key sent by the client with other client specific
    attributes known only to the resource." The composite here is `(idempotency_sub, idempotency_key)`, and after 0009 it
    is the only one.
  - Section 2.2: "A resource MAY define what makes a key unique, and clients sending requests to that resource need to
    generate keys accordingly."
- **Fowler, ParallelChange**, 13 May 2014, <https://martinfowler.com/bliki/ParallelChange.html>.
  - "Once all usages have been migrated to the new version, you perform the contract phase to remove the old version and
    change the interface so that it only supports the new version."
  - "If the contract phase is not executed you might end up in a worse state than you started."
  - "Most database refactorings follow the parallel change pattern, where the migrate phase is the transition period
    between the original and the new schema, until all database access code has been updated to work with the new
    schema."
- **PostgreSQL 16, DROP INDEX**, <https://www.postgresql.org/docs/16/sql-dropindex.html>: "A normal DROP INDEX acquires
  an ACCESS EXCLUSIVE lock on the table, blocking other accesses until the index drop can be completed." And "regular
  DROP INDEX commands can be performed within a transaction block, but DROP INDEX CONCURRENTLY cannot."
- **PostgreSQL 16, CREATE INDEX**, <https://www.postgresql.org/docs/16/sql-createindex.html>: "a standard index build
  locks out writes (but not reads) on the table until it's done", and "a regular CREATE INDEX command can be performed
  within a transaction block, but CREATE INDEX CONCURRENTLY cannot." On a unique index: "The default is that they are
  distinct, so that a unique index could contain multiple null values in a column."
- **PostgreSQL 16, ALTER TABLE**, <https://www.postgresql.org/docs/16/sql-altertable.html>: ADD table_constraint
  "Normally, this form will cause a scan of the table to verify that all existing rows in the table satisfy the new
  constraint", and "most forms of ADD table_constraint require an ACCESS EXCLUSIVE lock".
- **PostgreSQL 16, Explicit Locking**, <https://www.postgresql.org/docs/16/explicit-locking.html>: ACCESS EXCLUSIVE "guarantees
  that the holder is the only transaction accessing the table in any way", and "Once acquired, a lock is normally held
  until the end of the transaction."
- **PostgreSQL 16, LOCK**, <https://www.postgresql.org/docs/16/sql-lock.html>: "LOCK TABLE is useless outside a
  transaction block: the lock would remain held only to the completion of the statement."
- **PostgreSQL 16, Constraints**, <https://www.postgresql.org/docs/16/ddl-constraints.html>: "a check constraint is
  satisfied if the check expression evaluates to true or the null value." `idempotency_key IS NULL OR idempotency_sub IS
  NOT NULL` is never null.

## Decisions

| Decision | Evidence |
|---|---|
| One transaction, no CONCURRENTLY | The migrator runs one transaction (migrations/env.py, docs/12 section 4), and PostgreSQL 16 runs neither `CREATE INDEX CONCURRENTLY` nor `DROP INDEX CONCURRENTLY` in one. The refusals rely on a rollback that undoes everything. A plain DROP INDEX takes ACCESS EXCLUSIVE, which the migration holds anyway |
| `LOCK TABLE change_requests IN ACCESS EXCLUSIVE MODE` first, both ways | 0008 took the lock with its first statement (ADD COLUMN) so that no insert came between its checks and its updates. 0009 has no such statement before its checks, so it says so explicitly. DROP INDEX needs the same lock later in the transaction. Taking it first closes the race before the refusal scans and avoids a lock upgrade mid-transaction (PostgreSQL 16, LOCK: "transactions should always acquire the most restrictive mode first"). Reads and writes of the table queue from this first statement until commit, through the checks and the updates too (#630 review). Measured: `outputs/lock-probe.txt` |
| Refuse a live keyed row with no `idempotency_sub` that is delegated and has no string `submittedBySub` | 0008's ambiguity rule, narrowed to the rows that 0009 fills. A row that already names its caller is not refused (`g-release-1-caller-only` in the fill test) |
| Refuse two live rows of one caller's key, by release 1's `key_owner` | The issue's acceptance criterion and the risk accepted in release 1 (#601 review, reviewer 2's mixed probe). The group is `COALESCE(idempotency_sub, requester->>'submittedBySub', requester_sub)`, so it covers two 0007 rows and a 0007 row beside a release-1 row. Two release-1 rows cannot collide: the caller's index held them |
| **Which pairs the drop of the requester's index changes** (the coordinator's addition) | Until 0009, `uq_cr_idempotency (requester_sub, idempotency_key)` held over every keyed row, since `requester_sub` is never null. So no two stored rows share a requester and a key, and the drop changes no stored row and no retry of a stored request. Its only effect is on a new request whose caller differs from a live row's caller and whose person is that row's requester: the person using a key that a service holds for them, or a service using the person's key for her. Release 1 answered 409 "Idempotency-Key is in use for another request", which named no request but told the caller the key was held; release 2 makes it that caller's own new request, under the same checks as any other, the namespace lock included (a held namespace is still 409 `change-pending`). That change is the fix (#603's first test, inverted). Refusing while such keys are live would block 0009 on every live delegated key, which a busy system always has, and would refuse the very answer the issue asks for. So no third refusal is added, and the two above are complete for what the caller's index cannot hold |
| Clear the expired keys before the fill | The caller's index already exists. An expired row with no caller would, once filled, meet a live row with its caller and key and break the index mid-update (`d-0007-svc-own-expired` in the fill test). The lookup clears an expired key before any read, so clearing it is not observable |
| Add `ck_cr_idempotency_caller CHECK (idempotency_key IS NULL OR idempotency_sub IS NOT NULL)` | Before 0009, every keyed row was under a unique index, the requester's. After the drop, a keyed row with no caller is under none (NULLs are distinct) and invisible to the lookup. Release 1's and this code always write the caller with the key, and clear them together. A 0007 image is the one writer that does not: its migrator exits 0 on 0009 (a later four-digit revision, core/db/migrate.py `_compatible_future`) and its `/readyz` is ready, so a mistaken rollback to it would silently lose idempotency. The check turns that into a refused insert. Test: `test_the_database_refuses_a_keyed_row_with_no_caller` |
| Lookup by `(idempotency_sub, idempotency_key)`, and expire only the caller's own row | The fallback of `key_owner` served rows with no caller, which the check now forbids. Clearing every caller's expired row was for the requester's index (#611), which is gone: only the caller's own row can refuse the caller now. Both statements name both columns of the caller's index. Measured plans: `outputs/size-probe.txt`. Another caller's expired row keeps its key until its own caller sends it again; it never replays (the #611 tests show it) |
| The 409 branch: `diag.constraint_name == IDEMPOTENCY_INDEX` | #612 kept. One index name now. `test_a_key_named_after_an_index_is_an_opaque_key` now meets the caller's index (a race), since the requester's is gone |
| `REQUIRED_REVISION = "0009"` | This code relies on the check and on the fill. `/readyz` at 0008 is 503 (`test_a_database_at_release_1_is_behind_this_code`) |
| Release 1's image runs on 0009's schema | It writes the caller with the key, its lookup reads `idempotency_sub` first, and its 409 list holds the caller's index. So an image-only rollback to release 1 is safe, and the rolling update from release 1 to release 2 mixes two versions that both work |

## The downgrade

0009 can be downgraded, to 0008. The downgrade locks the table, refuses (changing nothing) while two live rows share a
requester and a key, clears the expired keys, creates `uq_cr_idempotency` again, and drops the check. Every live key keeps
its caller, which release 1's code reads. The refusal is needed: after 0009 a person and a service writing for her may hold
the same key, which the requester's index cannot hold. It succeeds once all but one row of each pair are over 24 hours old.
Tests: `test_the_downgrade_restores_release_1_and_keeps_every_live_key`,
`test_the_downgrade_refuses_a_live_pair_of_one_requester_and_changes_nothing`,
`test_rows_that_a_0007_pod_wrote_replay_for_their_caller_after_0009` (down to 0008 and up again with real requests), and
the #592 round trip down to 0007.

## Tests

Each test ran on `cb59e19` (main, the tests copied into an export: `outputs/tests-before-cb59e19.txt`) and on this
branch (`outputs/targeted-after-1.txt`, `outputs/targeted-after-2.txt`), on PostgreSQL 16.15 at `127.0.0.1:55432`, each in
its own database.

| Test | cb59e19 | This branch |
|---|---|---|
| `test_the_person_cannot_replay_the_service_request_with_its_key` (the window test, inverted) | fail: the requester's index answers 409 `idempotency-replay` | pass: the lock answers `change-pending`; her own key is 202 and replays; the service's retry replays its own |
| `test_a_0007_insert_in_the_window_no_longer_escapes_the_caller_index` (inverted) | fail: `head` is 0008, nothing refused | pass: refused, unchanged; then filled; then the insert is refused by the check |
| `test_the_upgrade_fills_each_keyed_row_with_its_caller_and_keeps_only_the_caller_index` | fail: revision 0008 | pass |
| `test_the_upgrade_refuses_a_live_delegated_row_without_its_caller_and_changes_nothing` | fail: the migration exits 0 | pass: rows, count, indexes, constraints and revision are equal before and after |
| `test_the_upgrade_refuses_a_live_collision_under_the_caller_and_changes_nothing` | fail: the migration exits 0 | pass, the same comparison |
| `test_the_downgrade_restores_release_1_and_keeps_every_live_key` | fail: unique violation on `uq_cr_idempotency` (no 0009) | pass |
| `test_the_downgrade_refuses_a_live_pair_of_one_requester_and_changes_nothing` | fail: no 0009 to downgrade | pass, the same comparison |
| `test_rows_that_a_0007_pod_wrote_replay_for_their_caller_after_0009` | fail: the caller stays NULL | pass |
| `test_the_lookup_and_its_expiry_find_the_key_by_its_caller_through_the_caller_index` | fail: the index condition is the key alone | pass |
| `test_a_database_at_release_1_is_behind_this_code` | fail: `REQUIRED_REVISION` is 0008 | pass |
| `test_the_database_refuses_a_keyed_row_with_no_caller` | fail: the row is written | pass |
| `test_the_person_can_use_a_key_that_a_service_held_for_them_once_it_expires`, `test_a_service_can_use_a_key_that_the_person_held_once_it_expires` (#611, now for one index) | fail: the other caller's expired row was cleared | pass |
| `test_a_key_named_after_an_index_is_an_opaque_key` (#612, now meets the caller's index in a race) | pass | pass. It no longer fails before; the substring bug it guards is in `2c663b8`, and the DETAIL of the caller's index quotes the key too |
| 0008's migration tests | pass (with `head`) | pass, naming `0008`: `head` is 0009 |
| `test_migrate_log_614.py` (start at 0007; the slow step is 0009's DROP INDEX) | not run before | pass, 9 |

The test removed: `test_a_row_that_a_0007_pod_wrote_after_0008_belongs_to_its_caller`. It made 0007 rows at `head` by
setting `idempotency_sub` to NULL, which the check now refuses; `test_rows_that_a_0007_pod_wrote_replay_for_their_caller_after_0009`
covers the same rows through 0009.

**The full service suite** on this branch (`4354598`..`a527367`, the same code), in its own database `cmapi_603`, from
2026-11-24T03:55:49Z to 04:27:04Z, after the gate (no other suite, 1-minute load 8.19): **2494 passed in 1871.40 s**,
rc 0. Also `test_api_standard.py`, `test_api_docs.py` and `test_api_samples.py`: 206 passed. The contract lint, the
portal types check, `changelog.py --check`, `api-examples-doc.py --check`, `deploy/tests/doc12-test.py` (0 failed) and
`doc-citations.py --check` (0 problems) pass.

## Measured, inferred, not tested

- **Measured** on PostgreSQL 16.15 at `127.0.0.1:55432`, macOS:
  - the tests above on both heads, and the full service suite on this branch (in the pull request);
  - the lock probe (`outputs/lock-probe.txt`): the real migrator paused inside 0009's transaction, after its checks, up
    and down. Another session's SELECT and UPDATE get `55P03`, and `pg_locks` shows `AccessExclusiveLock` granted;
  - the size probe (`outputs/size-probe.txt`) on 200,000 synthetic rows (152,000 keyed, 32,000 with no caller, 30,000
    expired), while another agent's suite ran (load about 11). Release 1's SELECT and UPDATE: an index scan of
    `uq_cr_idempotency` on its trailing column, 771 buffers, 17.7 ms and 18.9 ms. This code's: an index scan of
    `uq_cr_idempotency_caller` on both columns, 4 buffers, 0.16 ms and 0.72 ms. 0009 took `transaction_seconds` 12.5 (its
    step 6.7), and its downgrade 3.3. After 0009, no keyed row had no caller.
  - release 1's code on 0009's schema, the image-only rollback (`outputs/release-1-code-on-0009.txt`): the tests of
    `cb59e19` (`test_flow.py` and the HTTP tests of `test_idempotency_caller_592.py`) against a database that this branch
    migrated to 0009. Release 1's migrator skipped it as a later release's revision. 27 passed. The 3 that failed are
    release 1's window answers that 0009 changes on purpose: the person's own use of a service's key is 202 (was 409);
    setting `idempotency_sub` to NULL on a keyed row is refused by the check; and the key named after an index is 202
    for the person (the requester's index that refused it is gone).
- **Not tested:**
  - 0009 on CRC. It runs in a later deploy run. The read-only count on #592 (19 rows, 0 live keys) has nothing it would
    refuse; it was not repeated for this change.
  - A real rolling update from release 1 to release 2 on a cluster.
  - A 0007 image against 0009: the check's refusal is tested with a 0007-shaped INSERT, not with 0007's code.

## Review

- **Reviewer 1:** Codex `gpt-6.2-astra` at xhigh, on head `08ef716` (`review/reviewer-1-codex-astra.md`). Four findings.
- **Reviewer 2:** a separate Opus 5.5 agent at high (`review/reviewer-2-opus.md`, mutants in
  `review/reviewer-2-mutants.txt`). All four hold; finding 1 is narrowed.
- **The coordinator's rulings** (Opus 5.5, main session). All are accepted as reviewer 2 narrowed them.
  1. **The round trip to 0007 and back.** It becomes a sentence in `docs/12` and a test, with no guard on 0008.
     - Every row cmapi writes rebuilds to the same caller: `Pipeline.submit` stores `who.sub`, and `Requester.record()`
       stores `submittedBySub` for a delegated write.
     - The only bad shape is hand-written SQL, and it fails loudly: 0008 refuses and changes nothing.
     - A guard would edit a shipped migration for rows nobody writes. Over-build only if it is the only solution.
  2. **The #612 opaque-key test.** It now records the error that `RequestRepo.insert` raises. The substring mutant fails
     it (`409 change-pending`).
  3. **The models and the migrations.** Every constraint of every table is now compared, through `pg_get_constraintdef`,
     because Alembic's autogenerate does not compare CHECK constraints. The model declares `ck_cr_requester_kind`
     (0001's). Three parametrized probes prove that a missing CHECK is found.
  4. **The `docs/12` rollout wording.** A contract step waits only for pods older than its expand step. The 409 did tell
     the caller that the key was held. The other caller's request goes through the usual checks, so a held namespace is
     still 409 `change-pending`.
  - **The two gaps reviewer 1 predicted** (0009's `_LIVE` with `>`, and a weakened ambiguity check) survived head's
    tests, and are now caught.
  - **All eight mutants are killed.**
- **The coordinator's run.** Reviewer 2's patch was applied with `patch -p1 -F0` and merged with `main` (`ea17cd1`).
  - **The full service suite** in database `cmapi_603`, 2026-11-24T08:53:41Z to 09:28:01Z, after the gate (no other
    suite, 1-minute load 8.18): **2594 passed in 2055.46 s**.
  - `doc-citations.py --check`: 0 problems.
