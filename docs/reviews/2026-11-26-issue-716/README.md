# #716: a revert gets the same capacity check and approval facts

PR #717 follows. Found as Codex's H1 in the review of PR #714 (#710). Reviewer 2 (Opus 5.5 high) measured it on PostgreSQL 16.15 and wrote the fix and its tests. The coordinator applied it on main `0c9c4d7`, with one adjustment: `restore_facts` sizes through `binding_hard`, as #715 now requires.

**Design.** docs/01:260: "the revert is a new request through the same approval rules". The capacity is "Released, so the revert request can take it".

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
