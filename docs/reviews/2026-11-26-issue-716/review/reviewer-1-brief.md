# Reviewer brief: cmapi PR #718 (closes #716), the revert's sizing. Security (an approval gap).

You are the reviewer, from the Codex model family, adversarial. Opus 5.5 high wrote it, as reviewer 2 of #714. Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-718/` (`head/`, `base/`, `pr.diff`). When you diff, exclude `examples/`, which holds symlinks. Read `head/docs/reviews/2026-11-26-issue-716/README.md`. Write `r1-report.md`, and put any fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The claim.** docs/01:260 says a revert is "a new request through the same approval rules". `Pipeline.restore_facts()` now gives `open_revert`:
- the capacity check (a refusal raises capacity-exceeded, and the request stays `sync_failed`);
- `quotaIncreasePct` and `tierChange`, `networkExposure`, `beyondTier`;
- live usage;
- the metadata facts.

`compare` copes with a missing key or tier.

**Confirm or refute, with tests:**
1. A revert can no longer restore a larger quota, a wider exposure, or a sensitive key without the approvals a forward change would need.
2. The capacity reservation is released and taken correctly, with no double charge and no leak, when the revert is refused.
3. A revert of a create or of a delete still works.
4. Behaviour beyond the purpose.
5. The tests fail on base and pass on head, plus mutants.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests, from a tree's `cmapi/`:

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_718 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`.

**Severity and fixes.** Mark each finding High, Medium or Low. High and Medium findings need the full fix and a test that fails before and passes after. Keep fixes narrow: the owner wants speed. Low findings outside the changed lines go to Backlog.

Quote your sources. No repository, GitHub or cluster changes. End with a five-line summary.
