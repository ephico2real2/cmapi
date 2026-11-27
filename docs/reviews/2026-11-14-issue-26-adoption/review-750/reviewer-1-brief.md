# Reviewer 1 brief: cmapi PR #750 (closes #746 to #749, part of story #26), adoption follow-ups. It changes the approval count: two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you, on PostgreSQL.
- Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-750/` (`head/`, `base/`, `pr.diff`).
- Read in full: the issues' text in the PR body (`pr.diff` touches the design record); `head/docs/reviews/2026-11-14-issue-26-adoption/README.md`, the new section on which findings count, plus D2, D3, D3a, D10 and D20.
- Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`, applied to a copy.

**The owner's direction, 2026-11-26:** "adopting a namespace is very easy and promote self services". **CRC run 46 measured:** with every required key supplied, 17 findings remained, so the "adoption with findings" approver always applied. 8 were server-owned `skipped-key`, 1 was `not-adopted`, and 1 was a `policy-ratcheted` finding on the opt-in label `cmapi.net/adopt`.

**The claim:**
1. **#746:**
   - only findings a person should judge drive the extra approver;
   - the full findings list is still shown;
   - the opt-in label no longer produces a policy finding.
2. **#747:** the `skipped-key` text is true.
3. **#748:** CRC's reader can `list` ServiceAccounts and RoleBindings.
4. **#749:** the Adopt button at 390 px, and the "Not adopted" sentence.

**Confirm or refute, with tests:**
1. **Approval safety.**
   - Can any real deviation now escape the extra approver? Check each finding code the split leaves out, against D3 and D10: an unknown key, a missing required key, beyond-bounds, a real policy violation, a conflict.
   - Is the exemption of `cmapi.net/adopt` exact (its key and value as `adoption.yaml` configures them), not a prefix or a pattern?
   - Do existing site rules that use `findingCount` keep their meaning, or is the change documented?
2. **The policy change (`policygen.py`).** Does exempting the opt-in label weaken any other label rule? Does the generated Kyverno policy still refuse the same other keys? The PR also prepares a cluster-configs bundle.
3. **#748 RBAC.** Is it `list` only, on exactly `serviceaccounts` and `rolebindings`? Are CRC and the baseline, and docs/21's table, consistent?
4. **Behaviour beyond the purpose:** create, PATCH and the D10 base approval behave as on base.
5. **The tests can fail.** Run them on base and head, plus mutants of the counted-findings split and the label exemption.

**How to run.** Your sandbox may not reach PostgreSQL; if so, say it at the top and do not substitute SQLite. Service tests run from a tree's `cmapi/`:

`CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_750 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider`

Core tests: `PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/venv-ref/bin/python -m pytest tests/core -q`. Shell tests: `bash deploy/tests/crc-scripts-test.sh`.

**Severity and fixes.**
- High and Medium findings need the full fix and a test that fails before and passes after.
- Keep fixes narrow, and **separate anything that predates the PR**.
- Low findings, and anything outside the changed lines, go to Backlog.

Quote the design and primary sources. No repository, GitHub or cluster changes. End with a five-line summary.
