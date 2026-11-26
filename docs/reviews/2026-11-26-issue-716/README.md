# #716: a revert gets the same capacity check and approval facts

PR #718. Found as Codex's H1 in the review of PR #714 (#710). Reviewer 2 (Opus 5.5 high) measured it on PostgreSQL 16.15 and wrote the fix and its tests. The coordinator applied it on main `0c9c4d7`, with one adjustment: `restore_facts` sizes through `binding_hard`, as #715 now requires.

**Design.** docs/01:260: "the revert is a new request through the same approval rules". As a new request it is planned as step 5 plans any: "For a quota increase, the delta is reserved" (docs/01:238). The row's "Released, so the revert request can take it" is the Lock column; the reservation was released at sync\_failed (docs/01:258).

**What was wrong**, measured on main:
- a revert of large → small restored the large quota with no capacity check, no `quotaIncreasePct`, and auto-approval;
- a revert that wrote back a sensitive key raised `KeyError: 'sensitiveKeyChanged'` and was auto-approved.

**Fix.**
- `Pipeline.restore_facts()` gives the revert job:
  - its capacity check (a refusal raises capacity-exceeded, so the job fails like a Git outage and the request stays `sync_failed`);
  - `quotaIncreasePct` and `tierChange`, `networkExposure`, `beyondTier`;
  - live usage;
  - the metadata facts.
- `open_revert` uses that result.
- `compare` copes with a missing key or tier.

**Tests** (`test_revert_sizing.py`):

| Run | Result |
|---|---|
| main | 3 failed: not sized as a raise; opened with no room; no `sensitiveKeyChanged` |
| fix | 3 passed |
| revert, recovery, delivery, drift, short names, authz, contract and citation tests | 115 passed |
| `tests/core` in the reference venv | 842 passed, 113 skipped |

**Still open (Low):** the revert's expiry facts (`expirationBeyondLimits`), in #717's Backlog note.

**Review:** reviewer 2 of #714 (Opus) wrote it, so it is reviewed by Codex, the other model family.

## Review and the coordinator's rulings (2026-11-26)

**Reviewers.**
- **Reviewer 1:** Codex gpt-6.2-astra xhigh. Its sandbox could not reach PostgreSQL.
- **Reviewer 2:** Opus 5.5 high, on PostgreSQL 16 (`review/`).

| Codex finding | Ruling |
|---|---|
| 1. The capacity baseline after a failed sync double-counts | **Fixed, Medium.** The revert is sized over what the cluster commits now (`namespace_committed()`), not Git plus live. Head counted 56 of 40 where 32 is committed; an undo of an unpruned delete counted 0.125 instead of 0.0625. |
| 3. Beyond-tier read from old annotations | **Fixed, Medium.** Restored values are checked against today's tier (`TierCatalog.beyond`, as the forward planner does). |
| 6a. A missing tier ranks as order 0 | **Fixed, Low.** |
| 6b. `beyondTier` null for the approver | **Fixed, Low.** `Pipeline.beyond_view()` is shared. |
| The design note misquoted docs/01:260 | **Corrected above.** |
| 2b. Removing a NodePort or LoadBalancer bound | **Separate: #720, Medium.** It predates this PR. |
| 4 and 5. The inverse policy, and the target-dependent facts | **Separate: #719, Medium.** They predate this PR. The ruling: the undo of a delete is judged as a create, per docs/01:260. |
| 1b, 2a, and the inferred items | **Low, Backlog #721.** 2a is reachable only by hand-editing Git. |

**Tests on PostgreSQL:** `test_revert_sizing.py` (9 tests) gave 9 failed on base, 4 failed on head, and 9 passed with the fix; 6 of 6 mutants were caught. Reviewer 2's related run gave 603 passed.
