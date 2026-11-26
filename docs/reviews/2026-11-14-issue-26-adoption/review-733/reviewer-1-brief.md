# Reviewer 1 brief: cmapi PR #733 (part of story #26; closes #248, #731), the adoption of unmanaged namespaces. A write path with approvals: two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you, on PostgreSQL.
- Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-733/` (`head/`, `base/`, `pr.diff`). When you diff, exclude `examples/`, which holds symlinks.
- Read in full: `head/docs/reviews/2026-11-14-issue-26-adoption/README.md` (decisions D1 onward, and its new section 0, "built and not built"), and the owner's decisions on #26 quoted there.
- Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The claim:**
- `GET .../adoption/candidates`, `GET .../adoption/skipped` and `POST .../namespaces/{ns}:adopt`, with a dry run, all behind `adoption:write`.
- The plan reads the live objects and keeps every key as it is, under tier `custom`, with one file per object. Each difference is a finding.
- A namespace that is not a candidate gets 409 `namespace-not-adoptable`.
- Every adoption needs a person: one approver from `approver-platform`, plus one more when there are findings. Auto-approval never applies.
- **D16:** the cluster is read again after approval, at PR opening, in the PR check and just before an apply.
  - A changed object fails the request (`adoption-plan-stale`).
  - A removed opt-in label cancels the request and closes its PR.
- **#248:** the plan and the PR check use the approved plan's snapshot as the policies' base, never a file from the PR.
- An approved adoption takes over only the namespace whose uid its plan read. A failed adoption cannot be reverted (409).
- **#731:** a quota counts as cmapi's own only when it carries the tier hash.
- A portal Adopt view.

**Confirm or refute, with tests:**
1. **Never a silent takeover** (story #26 criterion 1).
   - Can any path (create, PATCH, a label change, the sync, revert or retry) take over or rewrite an unmanaged or adopted object without an approved adoption?
   - Is the uid check enforced at apply time, and is the time window between the check and the apply closed?
2. **Approvals.** Can the approval count be lowered or skipped, for example by auto-approve rules, a dry run reused as a real request, or `Idempotency-Key` replay with a changed body?
3. **D16 staleness.** Are the four re-reads real, and does each one fail closed? Does a transient read error give a clear failure, never a silent pass?
4. **#248.** Can a PR author change the policy base by editing a file in the PR?
5. **Authorization.** Is every new route behind `adoption:write` (or read) as docs/14 says, with `x-cmapi-permission` on each operation?
6. **Behaviour beyond the purpose:** the existing create, PATCH and quota-keeping (#250, #682, #685) behave as on base.
7. **The tests can fail.** Run them on base and head, plus mutants of the uid check, the approval count and the D16 comparisons.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests, from a tree's `cmapi/`:

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_733 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`.

**Severity and fixes.**
- High and Medium findings need the full fix and a test that fails before and passes after.
- Keep fixes narrow, and **separate anything that predates the PR**.
- Low findings, and anything outside the changed lines, go to Backlog.
- #732 (adding a missing derived key) is ruled and is being fixed separately: do not re-report it.

Quote the design and your primary sources. No repository, GitHub or cluster changes. End with a five-line summary.
