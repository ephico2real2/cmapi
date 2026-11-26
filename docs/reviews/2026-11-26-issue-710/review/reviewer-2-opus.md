# Reviewer 2 (Opus 5.5 high), PR #714 (#710): summary as delivered to the coordinator, 2026-11-26

Every case ran on PostgreSQL 16.15. The raw runs were in `workbench/cmapi/review-714/r2-outputs/runs/`.

**Verdict:** the PR's change is correct. All seven Codex findings predate it: each measured the same on base, except H2a, where head's baseline is Git and base's is the catalog.

**Design lines used:**
- docs/01:42, :260;
- docs/02:1345, :1377, :1831;
- docs/16:219-220;
- the adoption record, D8 (l.256), D9 (l.272) and D16 (l.516).

| Codex | Measured | Ruling |
|---|---|---|
| H1: the revert skips quota review | A revert of large → small restores large: no capacity check, no `quotaIncreasePct`, auto-approved. Also a `KeyError: 'sensitiveKeyChanged'`. | Separate issue, Medium: **#716** |
| H2a: short names | `cpu: 1, memory: 2Gi` to medium is charged (16, 32Gi) at 100% where the rise is 1500%; `cpu: 1` beside `requests.cpu: 8` gives (0,0) | Separate issue, Medium, **landed in this PR: #715** (docs/16:219) |
| H2b, H2c: scoped to unscoped; a legacy duplicate | (0,0) | Low, Backlog **#717** |
| H3: a partial folder breaks the create | A create over a stray file is charged in full and approved as a create | **Rejected as High.** It bypasses nothing. Folder hygiene is Low (#717). |
| H4: a new key gets no peak ratio | `newOverPeak 4.0`, and no approval from it | Low, Backlog #717 |
| M1: a first quota reads live usage | 1 usage call; with Thanos down, +1 approver-platform | Low, inside the changed lines: **fixed in this PR** (`if old_hard:`) |
| M2: a quota-less custom namespace refuses a metadata change | 422 `custom-quota-required` | Low, Backlog #717 (adoption, #26) |
| M3: a move off a retired tier | 422 `tier-unknown` | Low, Backlog #717 |

**Missed by Codex:**
- the PR's tests did not catch a revived `old_hard or hard` fallback (now caught by `test_a_quota_that_git_does_not_hold_is_written_from_nothing`: 6 failures on base, 1 on the mutant);
- the revert drops the metadata facts;
- docs/16:219 requires the normalisation;
- H3 is not a bypass.

Codex's 43 KB patch was not taken; it was replaced by narrower patches.

**Results:**
- the drift file: 8 of 8;
- names: 127 passed in the regression run;
- the first quota: 107;
- all patches together: 74;
- core in the reference venv: 818 passed, 113 skipped.
