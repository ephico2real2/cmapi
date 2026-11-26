# Reviewer brief: cmapi PR #735 (closes #732, part of story #26), stacked on #733. One reviewer: a small rule change, not security.

You are the only reviewer, from the Codex model family, adversarial. Opus 5.5 high wrote it.
- Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-735/` (`head/`, and `base/`, which is #733's branch, plus `pr.diff`).
- Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The ruling being built** (issue #732, the coordinator's comment, from the owner's decision 2 on #26, 2026-11-14: "Later updates go through without it; it stays a finding until someone chooses to add it"):
- A change to an existing namespace may add a missing automatic (`value.from`) key with exactly the derived value.
- It may also add a missing `namespacePrefix` key with exactly the name's start.
- Any other value is still refused.
- The remedy texts say "a request can add it".

**Confirm or refute, with tests:**
1. Only an exactly derived value or exact prefix is accepted. Try case, whitespace, Unicode look-alikes, a key present in Git with a different value (still refused, as #481 says), and a removal.
2. Creation and the other #481 rules are unchanged (behaviour beyond the purpose).
3. The tests fail on `base/` and pass on `head/`. Add mutants of the equality check.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests: from a tree's `cmapi/`, run

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_735 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`.

**Severity and fixes.** High and Medium findings need the full fix and a test that fails before and passes after. Keep fixes narrow. Anything that predates the PR goes to Backlog. No repository, GitHub or cluster changes. End with a five-line summary.
