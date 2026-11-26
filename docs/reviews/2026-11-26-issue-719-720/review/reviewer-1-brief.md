# Reviewer brief: cmapi PR #722 (closes #719 and #720). Security (approval rules).

You are the reviewer, from the Codex model family, adversarial. Opus 5.5 high wrote it, as reviewer 2 of #718. Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-722/` (`head/`, `base/`, `pr.diff`). When you diff, exclude `examples/`, which holds symlinks. Read `head/docs/reviews/2026-11-26-issue-719-720/README.md`. Write `r1-report.md`, and put any fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The claims.**
- **#719:** a revert's inverse is judged by its own policy (the undo of a delete as a create; the undo of a create as any delete, so a protected namespace refuses it and its age counts), with the restored team, tier and cluster labels.
- **#720:** removing the last NodePort or LoadBalancer bound is network exposure, in the forward planner and in the revert.

**Confirm or refute, with tests:**
1. No revert can now dodge a rule its forward equivalent meets.
2. No forward request changed its approvals beyond #720's exposure rule.
3. The undo of a delete of a small dev namespace is auto-approved by the shipped rules, as a forward create is. The coordinator accepted that per docs/01:260; refute it only from the design.
4. The tests fail on base and pass on head, plus mutants.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests, from a tree's `cmapi/`:

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_722 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`.

**Severity and fixes.** High and Medium findings need the full fix and a test that fails before and passes after. Keep fixes narrow. **Separate anything that predates this PR**, and say so. Low findings outside the changed lines go to Backlog.

Quote your sources. No repository, GitHub or cluster changes. End with a five-line summary.
