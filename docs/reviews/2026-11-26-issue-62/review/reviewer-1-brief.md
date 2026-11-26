# Reviewer 1 brief: cmapi PR #725 (closes #62, part of story #21), capacity reservations. Two reviewers: the approval guard and a migration.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you, on PostgreSQL. Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-725/` (`head/`, `base/`, `pr.diff`). When you diff, exclude `examples/`, which holds symlinks. Read `head/docs/reviews/2026-11-26-issue-62/README.md` in full. Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The claim.** On main, `reserve` and `release` did nothing, so two requests that each fitted could both be recorded and auto-approved. The PR builds docs/02's Placement "Reservations":
- migration 0011 adds `capacity_reservations`;
- the capacity check counts active holds, and a hold stops counting once the ledger shows its quota;
- submit re-checks under a per-cluster advisory lock and takes the hold in the same transaction;
- `RequestRepo.move` releases or re-takes holds by lifecycle;
- expired holds stop counting;
- the last `:approve` and a `:retry` from `failed` re-check, returning 422.

**One deliberate difference from docs/02:** a hold's expiry restarts at each step.

**Confirm or refute, with tests:**
1. **No double count and no leak.** A hold is released on every terminal state (rejected, cancelled, failed, synced, expired). It stops counting exactly when the ledger shows the quota.
2. **Race safety.** Two submits on one cluster cannot both fit when only one fits. Is the advisory lock key per cluster and released at commit?
3. **The hold expiry restarting** at each step: could a request hold capacity forever?
4. **Migration 0011:** up, down and up. Are `REQUIRED_REVISION` and the migration tests updated? (Grep `tests/service` for `'0010'`.)
5. **Behaviour beyond the purpose:** a forward request that used to pass must not now fail without cause.
6. **The tests can fail.** Run them on base and head, plus mutants.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests, from a tree's `cmapi/`:

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_725 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`.

**Severity and fixes.** High and Medium findings need the full fix and a test that fails before and passes after. Keep fixes narrow, and **separate anything that predates the PR**. Low findings outside the changed lines go to Backlog.

Quote the design (docs/02, Placement "Reservations") and your sources. No repository, GitHub or cluster changes. End with a five-line summary.
