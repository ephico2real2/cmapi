# Reviewer 2 (Opus 5.5 high) · cmapi PR #725 (closes #62, part of story #21)

PostgreSQL 16.15 on `127.0.0.1:55432`, database `cmapi_r2_725`, macOS, 2026-11-26. No cluster was used. Trees:
`r2-head/` (plain head; review tests copied in for each run, then removed), `r2-base/` (plain base), `r2-work/` (head plus
the fix). The final patch is [`r2-outputs/fix.diff`](r2-outputs/fix.diff), complete against `head/`, `examples/` excluded.

## Sources

- docs/02 (`head/docs/02-technical-design-v2.md`, line 1628, read 2026-11-26), Placement, "Reservations": "Placement takes a
  reservation inside the same transaction as the capacity check, under a per-cluster advisory lock, so concurrent requests
  see each other. The reservation ends when the namespace's ResourceQuota appears in cmapi's watch cache of that cluster.
  Committed quota counts it from then on, so it is never counted twice. It also ends when the request is rejected,
  cancelled or times out." Its table: `released_why ... -- observed, rejected, cancelled, timeout, expired`.
- docs/01 (`head/docs/01-design-and-architecture.md`, lines 244-261 and 448-452): the lifecycle's Reservation column;
  "approved: The count is met (auto or :approve) and capacity still fits"; "An increase reserves its delta like a placement
  and is checked again when approved".
- docs/02 line 823: "PostgreSQL with SKIP LOCKED jobs and an advisory lock for discovery, so cmapi can run several replicas";
  docs/16 line 85 (head): holds are stored "since they must outlive a process and be seen by every API pod".
- docs/12 (`head/docs/12-existing-postgresql.md`, §4): "Release 1, `0008`. It adds `change_requests.idempotency_sub`, fills
  it with the caller of each live key"; "Nothing rolls a data migration back by itself." The project fills data for live
  rows inside the migration (0008, 0009), not at start-up.
- PostgreSQL 16, §13.3.4 Deadlocks (<https://www.postgresql.org/docs/16/explicit-locking.html>, fetched 2026-11-26):
  "PostgreSQL automatically detects deadlock situations and resolves them by aborting one of the transactions involved";
  "The best defense against deadlocks is generally to avoid them by being certain that all applications using a database
  acquire locks on multiple objects in a consistent order." §13.3.5: transaction-level advisory lock requests "are
  automatically released at the end of the transaction, and there is no explicit unlock operation." §13.3.1: `SHARE`
  "Conflicts with the `ROW EXCLUSIVE` ... lock modes. This mode protects a table against concurrent data changes."
- PostgreSQL 16, `deadlock_timeout` (<https://www.postgresql.org/docs/16/runtime-config-locks.html>, fetched 2026-11-26):
  "The default is one second (`1s`)".
- Alembic cookbook (<https://alembic.sqlalchemy.org/en/latest/cookbook.html>): data migrations use table stubs
  (`sa.table`/`sa.column`) rather than the application's models, so later model changes do not break old migrations. The
  backfill follows that; it imports only pure parsing functions (`qty`, `binding_hard`, `objects_of`, `own_quota`), so its
  amounts are the planner's.

## Verdicts on reviewer 1's findings (each measured on PostgreSQL)

All tests are in `cmapi/tests/service/test_capacity_reservations_62_review.py` of the patch. Head: 7 failed, 1 passed
(the passing one is the Medium 2 guard). Fixed tree: 8 passed.

| # | Codex | Verdict | Severity | Measured on head | Fix kept |
|---|---|---|---|---|---|
| H1a | A hold vanishes between the two halves of one check | **Real** | Medium | A quota landing during the holds read: 0.75 (8 cores counted nowhere), 0.812 expected | Holds read first, then totals and held namespaces in one ledger lock (`CapacityLedger.snapshot`) |
| H1b | One pod's `observed` release ends the hold for every reader | **Real** | Medium | Reader behind the watch: 0.812, 0.875 expected (A's hold released by B's submit on another reader) | `reclaim` marks only expired; each reader discounts from its own watch |
| H2 | Expired holds bypass the last approval and delayed delivery | **Approval: real. Delivery: cut** | Medium | Room taken after the hold lapsed: last `:approve` 200 `approved` at 132/128; room free: approved with no hold (`reserved.cpu` 0.0) | `move` re-takes the last amounts on entering `approved` (`reacquire`), so `confirm` checks them |
| H3 | Approval/retry and submit take locks in opposite orders | **Real (retry path measured)** | Medium | `deadlock detected` (40P01): `:retry` 500 `internal-error`, "Process 378460 waits for ExclusiveLock on advisory lock ... Process 378457 waits for ShareLock on transaction 1595032" | `move` takes the cluster lock before the flush when entering `approved` |
| H4 | 0011 creates an empty table over live requests | **Real** | Medium | Seeded 0010 rows (pending create, approved update, failed, rejected, decrease) → 0 holds after upgrade | Backfill in 0011, in the transaction that creates the table, under `LOCK TABLE change_requests IN SHARE MODE` |
| M1 | Spurious 422 on forward creates (partial visibility; target rounding) | **Partial visibility: not a defect of this PR. Rounding: real** | Low (rounding) | A 1.1Gi target stored as 1181116007 never met by the ledger's exact 1181116006.4: reserved memory 16Gi + 1181116007, 16Gi expected | Targets rounded down (`_floor`); amounts stay rounded up |
| M2 | `merge_failed + RETRY` renews a hold forever | **Refuted** | — | Guard passes on head: three retries, reserved {cpu 0, memory 0}, ratio 0.812 | None |

### Severity reasoning

None is High: every defect is a narrow race or an upgrade-time gap, its effect bounded by one hold's size or one term,
and no data is corrupted. Each is Medium, because it breaks the PR's own claim ("concurrent reservations cannot overbook",
"capacity still fits") or returns a 500 under contention.

### H1: one snapshot, and observation per reader

Head's `check` read the cluster totals in `read_quotas` (one ledger lock), then queried the holds (a database round
trip), then read each held namespace (`namespace_committed`, a second lock). A quota admitted in between is in neither
read. The test injects the watch event inside `ReservationRepo.active`. The fix: holds first, then
`CapacityLedger.snapshot(namespaces)`, one lock. `confirm` now calls `check(..., 0, 0)` with the request's own hold
counted among the others in that snapshot. The second ledger read of head's confirm is gone. head's `read_quotas` guard stays
before it, so an unknown cluster still returns None rather than 404.

`_reclaim` used this pod's ledger to mark rows `observed` in the shared table. The worker and each API replica have their
own watch, so a reader whose watch is behind then counted neither the hold nor the quota. The fix removes the write: each
reader stops counting a hold from its own watch (docs/02: "appears in cmapi's watch cache"), and the row stays active until
the lifecycle releases it at `synced` (docs/01: "A reservation ends when the request is synced and a direct read shows the
namespace's quota"). **Design mapping for the coordinator:** `observed` stays a legal `released_why` (docs/02's list) that
no code writes now; docs/16 says so.

### H2: the last approval after the hold lapsed

The hold's term is `timeoutHours + 1h` from submit. `approval_timeout` runs hourly, re-enqueued 3600 s after it finishes, and
compares with `created_at`. `:approve` itself does not check the deadline. A late job therefore leaves a request pending and
approvable after its hold expired. Head's `move` then called `rearm` (no active row, no-op), and `confirm` returned None, so
the request was approved without docs/01's "capacity still fits". The fix calls `reacquire` on every move into `approved`.
`reacquire` extends an active hold, or marks a lapsed one `expired` and holds the last amounts again. `confirm` then counts it
and refuses with 422 when the room was taken.

**Cut from Codex's patch:** `guard_delivery` in apply, merge, delivery and watch_sync. The design checks capacity at the plan,
the submit and "when approved", and it ends a hold that times out. A check before each delivery step is new design. Recorded
below as a Backlog question. Merge_failed, the case Codex measured, has its quota already live (see M2).

### H3: lock order

Measured with real connections. Request X on `payments-a` failed. A submit for a new `payments-a` holds the cluster's lock,
and an operator's `:retry` of X arrives. Head's retry flushed `approved`, which takes X's entry in the partial unique index
`uq_cr_open_namespace`, and then waited for the cluster's lock in `confirm`. The submit's insert waited on that entry.
PostgreSQL aborted the retry after `deadlock_timeout`, and it answered 500 `internal-error`. With the fix, `move` takes the
cluster's lock before the flush and before any hold row is written, the order that submit uses. Now the submit commits and
the retry gets 409 `change-pending`. Order after the fix:

- submit: day lock (`next_id`), then cluster lock, then namespace index, then hold rows;
- `:approve` and `:retry`: request row lock, then cluster lock, then namespace index, then hold rows.

No writer holding the cluster lock waits for a request row lock. The approve-side variant (head's `rearm` locked the
request's own hold row before `confirm`, while a submit's `_reclaim` could update that row as `observed`) needs the hold to be
observed while pending. It is also closed by H1b, which removes that write.

### H4: requests in flight at the upgrade

docs/02 and docs/01 say nothing specific about upgrading with requests in flight. The project's pattern is a data fill of
the live rows inside the migration (docs/12 on 0008). The fix adds this fill to 0011.

- **Which requests.** Each create or update in a holding state (docs/01's Reservation column, frozen as a literal like
  0005's) holds the increase of its stored plan: the binding quota of `plan.files` over that of `plan.prev`, and over
  nothing for a create.
- **Term and rounding.** The term is `timeoutHours + 1` from the upgrade, as a lifecycle step would set it. Amounts are
  rounded up and targets down, as `reserve` stores them.
- **Failed requests.** A failed request gets a released row (`failed`), so that its `:retry` can take the amounts again and
  check them.
- **Rows skipped.** Decreases and rejected rows hold nothing. An unreadable plan logs a warning and holds nothing, as base did.
- **Measured on PostgreSQL:** 0010 → 0011 → 0010 → 0011, with the rows checked at each upgrade and the table gone after the
  downgrade.

**Cut from Codex's patch:**

- `sync_failed` rows: its `:retry` does not re-check.
- The column type changes to unbounded `NUMERIC`: docs/02 fixes `NUMERIC(12,3)` and `BIGINT`, and the rounding fix makes
  them unnecessary.
- `SHARE ROW EXCLUSIVE`: `SHARE` already blocks every writer.

**Not covered: the rolling-update window.** A 0010 pod still running after the migration commits writes and ends requests
without touching holds. A request it rejects keeps its hold for one term. This is the same kind of window that docs/12
accepts for 0008. The coordinator should add one line about it to docs/12.

For a revert request, the fill uses Git's previous and new quota. The live planner (`restore_facts`) sizes a revert against
the live quota instead. Both give the same result unless the cluster has drifted from Git.

### M1: forward creates

- **Partial visibility: not this PR's defect.** The hold's amount is the increase over Git's quota, and its target is the new
  binding quota. The ledger shows a value strictly between the two only when the live quota has drifted from Git, for
  example when someone edits it by hand. Every quota change in cmapi is a single object written in one step. Base's plan check
  already counts live committed plus the increase over Git: #710 decided to size every change "from the quota that Git holds".
  Counting the hold the same way follows that rule. Codex's test inserts a hold whose namespace already shows 4 of its 8
  cores, so it does not exercise the product flow.
- **Candidate at submit: cut.** It needs the request's own namespace to change live between plan and submit, which happens
  only out of band.
- **Rounding: real, Low, in the changed lines.** The catalog's custom bounds step by 1Gi (measured: `custom-out-of-bounds`
  for 1.1Gi, step `1Gi`), so the only way to reach it is a revert that restores a quota written by hand, through
  `restore_facts`. It is fixed in the patch because it is one line.

### M2: refuted

`merge_failed` is reachable only from `applied`, where "the PR's head is applied and confirmed by a read" (docs/01). The
quota is therefore in the ledger, and `held` does not count the hold. Measured on head: after PR_OPENED, APPLIED,
MERGE_FAILED and three RETRY moves, the ratio is 0.812 (96 + 8 committed) and reserved is 0. Renewing the expiry has no
effect on capacity, and the renewal is decision 2 of the PR. The test stays in the file as a guard. Codex's
`before != t.after` change is cut.

## What reviewer 1 missed

1. **The deadlock answers 500, not 409.** Codex did not reach PostgreSQL and inferred that "PostgreSQL can abort one
   transaction". Measured: the aborted side is the operator's `:retry`, which surfaces as an unhandled `OperationalError`
   (500 `internal-error`). It is not a 409, and the client is not told to retry.
2. **Codex's `confirm` changes behaviour for a cluster that is not in the registry.** Codex's version calls `check` straight
   away, and `check` starts with `registry.get`, which raises 404 `cluster-not-found`. Head returned None there, through
   `read_quotas`, which catches it. With Codex's patch, approving a pending request on a cluster removed from `clusters.yaml`
   would be 404 instead of approved. The patch here keeps the `read_quotas` guard.
3. **Codex's rounding fix changes docs/02's schema** (`NUMERIC(12,3)` and `BIGINT` to unbounded `NUMERIC`, and `pods` to
   `NUMERIC`). The cause was only the direction of rounding for the target. Rounding the target down fixes it and keeps the
   designed columns.
4. **Codex's migration fill over-fills and under-holds.** It writes `sync_failed` rows, which nothing reads back,
   and it sets `expires_at` from `updated_at`, which gives an already expired hold to a request that has not moved for a
   term. That is the same gap again. The fill here starts the term at the upgrade.
5. **docs/16 still documented the `observed` write and rounding up of targets.** The patch updates lines 61, 208 and 210.

## Backlog (Low, outside this change's scope; coordinator to file)

- What happens to delivery after a hold expires mid-delivery? For example, a request stuck in `pr_open` for more than a term
  loses its hold, and its merge later applies the quota unchecked. docs/02 ends the hold on time-out and checks nothing at
  delivery. This is an owner question, not a defect.
- docs/12: the rolling-update window of 0011, where 0010 pods move requests without touching holds.

## Verification

| Run | Tree | Result |
|---|---|---|
| Review file (8 tests) | r2-head | 7 failed, 1 passed (the M2 guard) |
| Review file | r2-work | 8 passed |
| PR file `test_capacity_reservations_62.py` | r2-head | 14 passed |
| 20 files: test_capacity_302, _ledger_302, _reservations_62, _reservations_62_review, _scale_302, _unknown_393, test_data_model_doc, test_flow, test_migrate_log_614, test_models_match_migrations, test_ob3_capacity_302, test_revert_hardening, _inverse_policy, _sizing, test_review_a_concurrency, test_review_h_tools_migrate, test_unprotect_approval_378, test_request_event_timestamps, test_catalog_drift_710, test_usage_verdicts_310 | r2-work | 261 passed in 686.92 s |
| `tests/core` (reference venv) | r2-work | 843 passed, 113 skipped (as the PR's record) |
| 5 mutants on r2-work, each reverting one fix (lock before flush; re-take on approved; totals before holds; target rounded up; no backfill) | copy of r2-work | 5 of 5 caught (1, 2, 1, 1 and 1 failed). The H1b mutant is head itself (failed above) |
| Deadlock test and `test_capacity_scale_302` together, 5 runs | r2-work | 10 of 10 passed; check in a transaction 3.0 to 3.8 ms (budget 5 ms; the PR recorded 3.0 to 3.2), with its own session 7.9 to 8.7 ms (budget 20 ms) |

Not tested: a real cluster, a real second replica (the test emulates a reader whose watch is behind by deleting the quota from
the one watch), and a rolling update with 0010 pods.

## Five-line summary

1. Six findings from Codex, measured on PostgreSQL 16. H1a, H1b, H2 (the approval part), H3 and H4 are real, all Medium. M1's rounding part is real and Low. M2 is refuted (merge_failed's quota is already live).
2. The deadlock was measured: :retry against submit gives 40P01, and the retry answers 500. With the fix, the cluster lock is taken in `move` before the flush, and the retry answers 409 change-pending.
3. Cut from Codex's patch: guard_delivery (new design), the unbounded NUMERIC columns, the partial-visibility rule, the candidate at submit, the `before != after` renewal rule, and the sync_failed backfill rows.
4. Kept and narrowed: the one-lock ledger snapshot, observation per reader, re-taking the hold on approved, targets rounded down, and the 0011 fill of requests in flight (the project's data-fill pattern from 0008).
5. Review file: head 7 failed and 1 passed, fix 8 passed. 20 suites: 261 passed. Core: 843 passed. 5 of 5 mutants caught. Patch in r2-outputs/fix.diff (570 lines; applies cleanly to head).
