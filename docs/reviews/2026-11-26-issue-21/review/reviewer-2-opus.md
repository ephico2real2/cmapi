# Reviewer 2 (Opus 5.5, high): feat/21-placement, capacity snapshots and safe placement

Reviewer 2 reviewed reviewer 1's (Codex gpt-6.2-astra xhigh) report, its 50 KB patch line by line, and the head on **PostgreSQL 16.15**
(`127.0.0.1:55432`, databases `cmapi_r2_21` and `cmapi_r2_21b`; Codex could not reach it). Work tree:
`review-21/r2-work/` (`head/`, Codex's `fixed/`, `headt/` and `headr2/` = head code with the review tests, `final/`, `verify/`).
Logs: `r2-outputs/logs/`. The deliverable is [`r2-outputs/final.diff`](r2-outputs/final.diff), against `head/`.

**Verdict: request changes, then mergeable with `final.diff`.** Four Codex findings are confirmed as defects that this branch introduces and
are kept (F1, F3 narrowed, F4, F6), and three Low ones are kept because their fixes are one or a few lines (F5, F7, F9). F2 (bind a
placement to its caller) is refuted against the design, and F8 (one-statement snapshot read) goes to the Backlog. Of the 50 KB, the
subject binding, the zero-amount hold, the `sized` delta change, the pods bound, the `latest()` rewrite, the `placed_by` column change
and five redundant tests are cut.

## The design the verdicts rest on

- docs/02, `NamespaceCreate`: `placement_id: str | None = None      # from POST /capacity:place; must match the path cluster, team and env`.
- docs/01, "Rate limits": "at most 3 active placements per team and environment, so nobody can hold a cluster's headroom with reservations."
- docs/14, line 396: "A scope by team or by namespace name | Not designed."
- D3: "The plan's own: clusters.yaml `simulatedCapacity` when set, else the counted nodes' allocatable, × the overcommit ... One arithmetic,
  so a cluster placement ranks is one the create's check finds room on." The owner, 2026-11-18 (design-capacity-arbitration.md):
  "keep `simulatedCapacity` as what the check uses until cmapi-capacity (#21)." docs/01: "Placement inputs. Allocatable comes from the
  live node list in the watch cache."
- docs/02, Placement: "Zone-failure headroom (prod only) is quota headroom computed with the largest zone removed, so a placed namespace still
  fits after losing a zone." "Placement ... refuses to decide on stale or partial data."
- docs/02, Reservations: "Placement takes a reservation inside the same transaction as the capacity check, under a per-cluster advisory lock".
- docs/02, Snapshot job: "A failed or warned query marks the row incomplete; it is never written as zero."

Primary sources fetched 2026-11-26:
- PostgreSQL 16, 9.27.10 (<https://www.postgresql.org/docs/16/functions-admin.html>): `pg_advisory_xact_lock` "Obtains an exclusive
  transaction-level advisory lock, waiting if necessary", and locks "at transaction level (so that they are held until the current
  transaction ends; there is no provision for manual release)". Both writers call `ReservationRepo.lock_cluster` (same key) inside the
  transaction that checks and holds, so the hold is visible to the next locker when it gets the lock.
- PostgreSQL 16, 13.2.1 (<https://www.postgresql.org/docs/16/transaction-iso.html>): Read Committed "a `SELECT` query ... sees only data
  committed before the query began", and "two successive `SELECT` commands can see different data, even though they are within a single
  transaction". This confirms F8's premise.
- Kubernetes, well-known labels (<https://kubernetes.io/docs/reference/labels-annotations-taints/>), `topology.kubernetes.io/zone` on
  Node: "The `kubelet` or the external `cloud-controller-manager` populates this with the information from the cloud provider. This will
  be set only if you are using a cloud provider." So a cluster with some unlabelled nodes is a real case (F4).

## Verdict on each Codex finding

| # | Codex finding | Verdict | What the final patch does | Test: head, then final (PostgreSQL) |
|---|---|---|---|---|
| F1 | High: placement sizes a cluster with no `simulatedCapacity` by its nodes, the plan's check does not | **Confirmed, High, branch-introduced.** Head's `SimulatedCapacity.check` reads `simulated_capacity` only and answers `unknown` (so the create is recorded, goes to a person, and `confirm` never says `exceeded`), while placement ranks and holds on node allocatable. D3's claim "one arithmetic" is false in head's code | Kept: `cluster_size` in `core/capacity_backend.py`, used by the check and placement; the node basis only on a fresh (`ok`) node read, as the Capacity tab marks a stale one | `test_a_direct_create_on_a_node_sized_cluster_counts_a_placement_s_hold` (world, no simulatedCapacity, 16 cores / 20Gi limit): head 202, final 422 `capacity-exceeded` with `source: allocatable`. `test_capacity_302` asserts `exceeded` now (head: `unknown`) |
| F2 | High: a hold has no caller check; another caller on the team can claim it | **Refuted as a defect.** The design binds a placement to "the path cluster, team and env", counts the cap "per team and environment", and has no team scope at all (docs/14). Binding to the subject is a design extension. "Two subjects can share a display name": `username` is the token's username, `String(100)` in every table (`requester_username`, `actor_username`), not a display name | Cut: `who.sub`, the `Text` column, the docs/16 change, the subject tests. To the Backlog as an owner question (B1) | none |
| F3 | High: conversion can enlarge the reservation | **Confirmed, Medium, branch-introduced.** A small placement claimed by a medium create passes: the plan's check counts the full 16 cores against ordinary headroom, so the cluster is not overbooked, but the zone-failure headroom that placement checked for 8 is never checked for 16. Medium, not High: a direct create with no `placementId` skips zone-failure headroom on head as well | Narrowed: `_placement` refuses `placement-mismatch` when the create's binding `requests.cpu` or `requests.memory` exceeds the hold. Cut: the `sized` delta change (it changed the check's delta for placement creates only; not needed, the bound reads `target`), the pods bound (placement does not check pods), and the zero-amount hold (Backlog B4) | `test_a_create_with_a_placement_of_another_target_is_refused[change2-placement-mismatch]` (`tier: medium` on a small placement): head 200, final 422 |
| F4 | High: unlabelled capacity inflates zone-failure headroom | **Confirmed, Medium, branch-introduced.** Head scales the size by the labelled zones' shares only; an unlabelled counted node may be in the largest zone. Also a zone row with only uncounted nodes counted as a zone | Kept: `zones_complete` (zoned schedulable nodes equal the cluster row's), `partial-data` where zone failure is checked, and zones with no counted node left out | `test_zone_failure_headroom_needs_a_zone_for_every_counted_node` (world, a third worker with no zone, zoneFailureEnvironments [dev]): head ranks CRC, final excludes it `partial-data` |
| F5 | Medium: the locked re-check uses the time before the lock wait | **Confirmed, Low** (the wait is one short transaction; the limit is two intervals). Kept: its fix is one line, and the cluster lost under the lock is now named in `excluded` and left out of `ranked` (docs/02: "explains every cluster it ranked or excluded") | Kept as Codex wrote it, with a comment | `test_the_locked_recheck_reads_freshness_when_it_holds_the_lock[3601]`: head holds the stale cluster, final excludes it `stale-data`; `[0]` passes on both |
| F6 | Medium: rounding changes admission | **Confirmed, Low.** (a) `1 - 2/3` at 28 digits gives 0.999...9 cores where 1 fits; (b) ranks 0.5001 cores, holds 0.501 | Kept: the zone limit multiplies before it divides; `ask_of` rounds to the hold's columns; the hold row then stores `ask.cpu`, `int(ask.memory)` (Codex rounded twice) | core `test_equal_fit_after_zone_loss_is_admitted_exactly`: head 1 failed, final passed. `test_the_ranking_checks_the_amount_the_hold_stores`: head fails, final passes |
| F7 | Medium: a NaN sample becomes 0 | **Confirmed, Low.** `capacity/usage.py::sample` says "a sample that is not a number is missing, never zero", and `measure` skipped it, so `_measured` summed 0. It affects the stored figures and the usage-headroom score, not admission | Kept (one line, commented) | `test_an_invalid_sample_marks_the_snapshot_incomplete_never_zero`: head fails, final passes |
| F8 | Medium: three reads of `latest()` can see different revisions | **Premise confirmed** (PostgreSQL quote above), **effect Low and transient**: it needs a `:run` to commit between two statements of one request, and the mixed result is conservative for placement (fewer zones: prod excluded). Codex's one-statement rewrite is harder to read than the risk warrants | Cut, to the Backlog (B2) | none |
| F9 | Medium: collection time delays the next snapshot | **Confirmed, Low.** It does not accumulate: the next run floors to its own boundary, so only that run starts late by the collection time | Kept (one line, commented) | `test_the_next_snapshot_is_due_on_the_next_boundary_after_a_slow_collection`: head 900 s, final 720 s |

## The checks Codex left (all on PostgreSQL)

| Check | Test | Result |
|---|---|---|
| Concurrent placements on one cluster, under #725's lock | `test_concurrent_placements_cannot_overbook` (8 threads, room for 1) | head and final: one `placed`, seven `no-placement`, 16 cores held |
| A placement and a direct create on one cluster | `test_a_placement_and_a_direct_create_compete_for_the_last_headroom` (Codex's, kept) | head and final: one wins, the other refused, one hold of 16 |
| Rollback of a failed create after its claim | `test_a_create_that_fails_after_claiming_its_placement_leaves_the_placement_as_it_was` | head and final: the placement unclaimed again with its own 15 minutes |
| Replay and release of a claimed placement | `test_a_claimed_placement_replays_with_its_key_and_ends_with_its_request` | head and final: same request on replay, 409 `idempotency-replay` on a changed body, hold released `failed` |
| Expiry | `test_an_expired_placement_is_reclaimed_and_holds_nothing` | head and final: a lapsed hold stops counting, reclaimed `expired` |
| Migration 0012 up, down, up, populated | `test_0012_roundtrip_keeps_request_holds_and_drops_unclaimed_placements` (Codex's, kept); `test_migrations_from_an_empty_database_up_down_up` | head and final pass: the request's hold survives, the unclaimed placement is deleted, `capacity_snapshots` is dropped and recreated |
| `REQUIRED_REVISION` | `src/cmapi/core/db/__init__.py:87` is `"0012"`; the only `"0011"` literal left in `tests/service` is the 0010↔0011 round trip | confirmed; 0012 is not on main, so editing it in place is right (the final patch does not edit it) |
| Thanos calls on create | `test_placing_and_creating_a_namespace_make_no_thanos_query` | head and final: **0** calls after the snapshot, through the preview, the hold, the create's dry run, the create and its jobs |

## What Codex missed (in the changed lines)

| # | What | Fix (in `final.diff`) | Test |
|---|---|---|---|
| M1 | F1 makes the contract's `basis` description false: "`simulated` ... (what the plan's capacity check uses until cmapi-capacity, #21)" (`core/models.py`, and so `contract/openapi.json` and the portal's `schema.generated.ts`) | The description now says the check and placement use the same size and that a stale node read is unknown to them; contract regenerated per `cmapi/contract/README.md` steps 3 and 6; step 5 `api-examples-doc.py --check` exits 0 | `test_api_docs.py::...committed_contract` (keeps the document current); the portal-ui CI job checks the types |
| M2 | Codex's rewrite of `capacity_backend.py`'s module docstring dropped the #302 ledger rule, the #393 unknown rule and the owner's 2026-11-18 decision | Restored and updated for D3 | docstring |
| M4 | F3's new refusal is `placement-mismatch`, whose remedy (`core/problem_docs.py`) named only cluster, environment and team | Remedy: "... and no more CPU or memory than it holds, or place again for this target." | `test_problem_type_docs.py` 16 passed, `test_api_docs.py` + `test_api_standard.py` 203 passed, docs/04 check exit 0 |
| M3 | With F1, a stale node read now excludes a cluster as `no-size`, whose detail said "allocatable is not known" | Detail: "... is not known or not fresh"; `cluster_size`'s docstring says why the check needs a fresh read and the tab does not | wording only, no behaviour |

I found no further defect in the changed lines. Re-checked and cleared: the lock order (team, then cluster; submit: day, then cluster; nothing
takes them the other way), `exclude_placement` (only while unclaimed), the claim's `rowcount == 1` guard, the plan-time ownership
read (the row's cluster, env and team never change), the downgrade's `DELETE ... WHERE request_id IS NULL`, and Codex's zone code on a
zone whose `allocatable` is null (impossible: `counts()` needs cpu and memory allocatable, so a zone with a counted node has both).

## Backlog (not in this pull request)

| # | Item | Why not now |
|---|---|---|
| B1 | Owner question: should a placement be claimable only by its caller, rather than by anyone who sends its id and the same team label? The team is caller-declared (docs/14: no team scope), so the team check binds nothing; the id (32 random bits) is the only secret. The same gap lets a caller fill another team's 3-placement cap by naming it | Design extension (F2); docs/02 says "team" |
| B2 | `SnapshotRepo.latest` reads in three statements; a `:run` committing between them can mix revisions (F8). A related, separate point: a manual `:run` during a Thanos or node-list failure replaces the interval's complete rows with an incomplete row | Low, transient, conservative for placement |
| B3 | `maxNamespaces` counts the ledger's namespaces only, not active placements or open creates, so concurrent placements can pass it; direct creates do not check it at all | Needs a design rule for what counts as pending; Codex noted it without a severity |
| B4 | A create with a `placementId` and no CPU or memory increase does not claim the placement (no hold), which then lapses after 15 minutes | Harmless to capacity; Codex's synthesized zero hold cut |
| B5 | `placed_by[:100]`: a username over 100 characters would be stored cut and counted uncut for a teamless caller's cap | Every username column in cmapi is `String(100)`, so such a username already fails elsewhere; pre-existing bound |
| B6 | Portal: a hold left on a different cluster when the ranking changes between Check and Submit; preview text says 15 minutes whatever placement.yaml sets (Codex's Low) | Low, portal |
| B7 | The class is still named `SimulatedCapacity` although it now measures node allocatable too | Rename only |

## Runs (PostgreSQL 16.15 at 127.0.0.1:55432; core with venv-ref)

| Run | Tree | Files | Result | Log |
|---|---|---|---|---|
| Codex's tests on head code | `headt/` | test_placement_21, Codex's test_placement_review_21, test_capacity_reservations_62_review, test_capacity_302 | **10 failed, 67 passed**: exactly Codex's 10 regression tests; its live tests (contention, rollback, replay, 0012 round trip) and the branch's 21 placement tests pass | `headt-svc.log` |
| Codex's patch | `fixed/` | the same | **77 passed** | `fixed-svc.log` |
| The final tests on head code | `headr2/` | test_placement_review_21 (final), test_placement_21 (+ tier case), test_capacity_302, test_capacity_reservations_62_review | **8 failed, 62 passed**: the 6 regression tests of the review file, the tier case, and test_capacity_302's `exceeded`; each fails on its assertion (202, 200, `unknown`, ranked, 0.5001, no raise, 900 s, `complete`) | `headr2-svc.log` |
| The final tree | `final/` | the above plus test_capacity_reservations_62, test_capacity_unknown_393, test_ob3_capacity_302, test_revert_sizing, test_models_match_migrations, test_usage_verdicts_310, test_api_docs, test_api_standard, test_api_samples | **349 passed, 0 failed** | `final-svc.log` |
| Migrations on head code | `headr2/` | test_review_h_tools_migrate::test_migrations_from_an_empty_database_up_down_up, test_capacity_reservations_62_review (0011 and 0012 round trips) | **10 passed** | `headr2-migrate.log` |
| `final.diff` on a fresh copy of head | `verify/` (`patch -p1 -F0`, then `diff -rq` with `final/`: identical) | test_placement_review_21, test_placement_21, test_capacity_302, test_capacity_reservations_62_review, the up-down-up migration test, test_api_docs | **97 passed**. After M4 (one string in `problem_docs.py`), `final.diff` was written again and applied to a second fresh copy (`verify2/`): identical to `final/`, and the docs tests above pass on it | `verify-svc.log` |
| Core, final | `final/` | `tests/core` (venv-ref) | **856 passed, 113 skipped** | `final-core.log` |
| Core, head code | `headt/` | `tests/core/test_placement_21.py` with the exact-fit test | **1 failed, 14 passed** | `headt-core-placement.log` |
| Contract | `final/` | `CMAPI_WRITE_CONTRACT=1 ... -k committed_contract`, `npm run api:types`, `api-examples-doc.py --check` | written; only the `basis` description changed in `openapi.json` and `schema.generated.ts`; docs/04 current (exit 0) | |
| Portal | `verify/` | `npm ci --ignore-scripts` (and in `tools/openapi-types`), `npm test` | **199 ok, 0 not ok, exit 0** (a first run was killed by an external signal mid-browser test and rerun) | `verify-portal.log` |

The whole service suite was not run (CI does). One verify run was cut by an external signal (exit 144) and rerun; its orphaned pytest
was mine and was stopped.

## Who wrote what

The branch: Opus 5.5 high. The reviewed patch: Codex gpt-6.2-astra xhigh. `final.diff`: Codex's hunks for F1, F4, F5, F6, F7, F9, its
core exact-fit test, its `test_capacity_302` change and its 0012 round trip, unchanged; narrowed and rewritten by reviewer 2 (Opus 5.5 high):
F3's bound, the hold amounts, the docstrings, M1 to M4, the new world tests for F1, F3 and F4, and `test_placement_review_21.py` trimmed
from 16 tests to 10 (Codex's three live PostgreSQL tests kept).
