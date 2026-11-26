# #62: the capacity guard counts the capacity that open requests hold

Part of story #21 ("Concurrent reservations cannot overbook; expired reservations are reclaimed"). Built from the design as it
stands (docs/01, "Capacity, placement and usage" and the lifecycle's Reservation column; docs/02, Placement, "Reservations").
Nothing in the design was reopened.

## What #62 asked, and where main stood at 4ef7770

| What must hold (#62) | On main | This change |
|---|---|---|
| The capacity answer comes from measured data | Committed quota already came from the quota ledger, fed by the watch (#302, #393). The size is `simulatedCapacity`: the owner kept it "as what the check uses until cmapi-capacity (#21)" (2026-11-18, `docs/reviews/2026-11-18-issue-302-capacity/design-capacity-arbitration.md`). Snapshots are #21's cmapi-capacity, not built | Unchanged; proven by a guard test (more than is free: 422 `capacity-exceeded`) |
| `reserve` and `release` change the reservations; a request that does not fit is refused or routed to approval | `reserve` and `release` returned `None`; no table; every request was checked alone, so two that each fit could together pass the cluster, and both could be auto-approved | Built: below |
| `requestToPeakRatio` and `openRequestOnNamespace` set from measured data | Already: `requestToPeakRatio` from the live 14-day usage (#310, #707); `openRequestOnNamespace` from the open requests in the database (`expire_check`, #263). The design has neither on a person's delete (docs/18) | Unchanged; proven by guard tests |

## What was built

| Design line | Built |
|---|---|
| docs/01: "Quota headroom = allocatable × overcommit − committed − reserved" | `SimulatedCapacity.check` adds the active holds of the cluster (`detail.reserved` in the plan) |
| docs/02: "Placement takes a reservation inside the same transaction as the capacity check, under a per-cluster advisory lock, so concurrent requests see each other" | `Pipeline.submit`: `reserve_check` takes the cluster's `pg_advisory_xact_lock` and checks again with every hold taken since the plan; `reserve` writes the hold after the request row, in the same transaction. A request that no longer fits is 422 `capacity-exceeded`; one whose answer moved (fits to warn) is decided again |
| docs/02: "The reservation ends when the namespace's ResourceQuota appears in cmapi's watch cache of that cluster. Committed quota counts it from then on, so it is never counted twice" | Each hold keeps the namespace and its binding quota after the change (`target_cpu`, `target_memory`); the check does not count a hold that the ledger already shows (`observed`) |
| docs/02: "It also ends when the request is rejected, cancelled or times out"; docs/01's Reservation column per state | `RequestRepo.move` releases the hold when the lifecycle says the state no longer holds one (`releases_reservation`), takes it again on a `:retry` into one (`acquires_reservation`) |
| docs/01: "approved: The count is met (auto or :approve) and capacity still fits"; "An increase reserves its delta like a placement and is checked again when approved" | The last `:approve` and a `:retry` from `failed` run `SimulatedCapacity.confirm`: 422 `capacity-exceeded`, and the transaction (the approval with it) is undone |
| docs/02's table `capacity_reservations` with `expires_at` "the approval timeout once submitted"; story #21: "expired reservations are reclaimed" | Migration 0011. An expired hold stops counting at once; the next hold on the cluster marks it `expired` |

## Decisions and why

1. **Three columns beyond docs/02's table** (`namespace`, `target_cpu`, `target_memory`): the "never counted twice" rule needs to know
   when the ledger shows the change. docs/02 reaches the namespace through `request_id`; it is kept on the row so the check of every
   plan reads no join.
2. **The term moves on at each step.** docs/02 sets `expires_at` to the approval timeout at submit. A request approved near the end
   of its window would then lose its hold while its PR is open, and another request could take the room before its quota is live.
   `RequestRepo.move` sets `expires_at` to one term from now at each step that keeps the hold: the approval rule's `timeoutHours`,
   plus the hour that the hourly `approval_timeout` job may take (`hold_term`). A request that stops moving still loses it one term
   later.
3. **The lock order.** The cluster's lock is always taken last: after a request's row lock (`:approve`, `:retry`, the revert job)
   and after the day's lock of `next_id` (submit). No two writers wait on each other in opposite orders.
4. **`unknown` at approval does not refuse.** Only `exceeded` refuses the last approval or a retry. The capacity guard of
   auto-approval already stops on `unknown` (#393); a person who approves has decided.
5. **The Capacity tab does not show the holds yet.** docs/02's cluster view overlays `reserved`; that is a contract addition to
   `GET /api/v1/capacity`, filed as #723 (Low, Backlog). Until then the tab equals the plan's check only while no request holds
   capacity (`core/capacity.py`).

## Sources

- PostgreSQL 16, "Advisory Lock Functions" (<https://www.postgresql.org/docs/16/functions-admin.html>, fetched
  2026-11-26): locks taken "at transaction level (so that they are held until the current transaction ends; there is no
  provision for manual release)", and `pg_advisory_xact_lock` "Obtains an exclusive transaction-level advisory lock, waiting if
  necessary". So the check and the hold must be in the transaction that takes the lock: its commit is what lets the next writer in,
  and that writer then sees the hold.
- docs/01 and docs/02 as quoted above.

## Measured (2026-11-26, macOS, PostgreSQL 16 on 127.0.0.1:55432, no cluster)

| Run | Result |
|---|---|
| `test_capacity_reservations_62.py` on main 4ef7770's code | 11 failed, 3 passed. The 3 are the guards: more than is free refused, `openRequestOnNamespace` and `requestToPeakRatio` from measured data. The behaviour failures: the second create auto-approved (`approved`, not `pending_approval`); submit did not refuse the plan made before the first hold; 8 of 8 concurrent submits held on room for 3; the check at 0.75 with a hold (0.812 expected); the last approval 200 (422 expected). The rest fail on the missing table |
| The same file with the fix | 14 passed |
| The service files that touch capacity, approval, retry, submit or the revision (59 files, list in the PR) with the docs and models tests | 1,240 passed, 2 failed, both from this change and fixed: `test_natural_race_rate_two_approvers` held 40 small namespaces on 128 cores (each is now cancelled once measured), and the scale test's 5 ms budget now includes the read of the holds (split: 3.0 to 3.2 ms in a transaction, budget 5 ms; 7.2 to 8.0 ms with its own session, budget 20 ms). Rerun: 48 passed |
| `tests/core` (reference venv) | 843 passed, 113 skipped |
| `scripts/doc-citations.py --check`; `contract/lint.sh` | 0 problems; no warnings |

Not tested: a real cluster (CRC was restarting); the hold's `observed` path against a real watch event after an Argo CD sync (the
test feeds the request's own rendered quota through the watch's ADDED path).

## Review and the coordinator's rulings (2026-11-26)

**Reviewers.**
- **Reviewer 1:** Codex gpt-6.2-astra xhigh. Its sandbox could not reach PostgreSQL.
- **Reviewer 2:** Opus 5.5 high, on PostgreSQL 16.15 (`review/`).

| Codex finding | Ruling |
|---|---|
| H1a: a hold vanishes inside one check | **Fixed, Medium.** The holds are read first, then the totals and held namespaces under one ledger lock (`CapacityLedger.snapshot`). |
| H1b: one pod's `observed` release ends the hold for every pod | **Fixed, Medium.** `reclaim` marks only expired holds, and each reader stops counting a hold from its own watch. |
| H2: an expired hold bypasses the last approval | **Fixed, Medium**, the approval part. Every move into `approved` re-takes the last amounts. Measured on head: 200 at 132/128. The delivery part (`guard_delivery`) was cut as new design, and filed as a question for the owner, #728. |
| H3: approve/retry and submit lock in opposite orders | **Fixed, Medium.** Measured `40P01`, so a 500 on `:retry`. `move` now takes the cluster lock first, and the retry answers 409 `change-pending`. |
| H4: 0011 leaves requests in flight without holds | **Fixed, Medium.** 0011 fills their holds in the same transaction, under `LOCK TABLE change_requests IN SHARE MODE`, the project's in-migration fill pattern (docs/12 §4, as 0008 did). |
| M1: target rounding | **Fixed, Low.** Targets are rounded down, and amounts stay rounded up. The partial-visibility part is not this PR's defect (#710 sizes against Git). |
| M2: `merge_failed` renewal | **Refuted.** `merge_failed` is reachable only after `applied`, so the quota is already counted. A guard test pins it. |

**Coordinator's decisions:**
- **Accepted:** a hold stops counting per reader at observation (docs/02), and in the database at `synced` (docs/01). No code writes `released_why = observed` any more; docs/16 says so.
- **Added:** docs/12 explains the 0011 rolling-update window.
- **Cut from Codex:** unbounded NUMERIC columns (docs/02 fixes the schema), the min rule, the candidate check at submit, and the `sync_failed` fill.

**Tests on PostgreSQL (reviewer 2):**
- the review tests: 7 failed on head, 8 passed with the fix;
- the deadlock and scale tests together: 10 of 10, 5 times;
- 5 of 5 mutants caught;
- 261 related service tests and 843 core tests passed.
