# Review brief: cmapi issue #199 (BUG-52), a comparison that GitHub can cut

You are the second reader of one small change to a guard. Work only in this folder. `head/` is an export of the commit (not a git repository). `change.diff` is the diff of this change alone (it also deletes a stray file `test_github_check_runs.py.orig`: ignore that part). Do not start a container. Do NOT connect to the PostgreSQL on 127.0.0.1:55432. You may use the network to read primary sources only: GitHub's REST documentation for "Compare two commits" and "List pull requests files", and github/rest-api-description. A test with no database can run with `PYTHONPATH=head/cmapi/src:head/cmapi/tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest -p no:cacheprovider <file>::<test>` (the first three tests of `head/cmapi/tests/service/test_github_compare_limit.py` need no database).

Write your report to the ABSOLUTE path `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run3/review-199/report/report.md` as you go, one section per claim: verdict CONFIRMED, REFUTED or PLAUSIBLE, the evidence as `file:line` with the quoted lines or the quoted source with its URL, and for each REFUTED claim the full code of a fix and the full code of a test that fails before the fix and passes after it. A finding with no failing test does not count. New files go in the report folder, never in `head/`. Keep it short: this is a narrow review.

## The change
`GitHubProvider.changed_paths` (`head/cmapi/src/cmapi/core/git/github.py`, lines 122 to 130) read `files` of `GET /repos/{owner}/{repo}/compare/{base}...{head}` as the full list. GitHub: "The list of changed files is only shown on the first page of results, and it includes up to 300 changed files for the entire comparison." After: at 300 files or more it raises `IncompleteList` (a subclass of `GitUnavailable`, `head/cmapi/src/cmapi/core/git/base.py`), and `pr_checks` (`head/cmapi/src/cmapi/jobs/pr_checks.py`, lines 64 to 70) reads that as a path outside the plan, so the check `cmapi/check` fails and the request ends as failed.

## Claims to confirm or refute, exactly

C1. With the change, no answer of the compare operation that GitHub can have cut is read as complete: the limit is 300 for the whole comparison, the adapter sends no `per_page` or `page`, and `len(files) >= 300` is the right test. Say whether GitHub can cut the list below 300 for another documented reason (for example a diff that is too large, or a timeout), and quote the source.

C2. `changed_paths` has one more reader: `contains` does not read `files`, and no other caller of `changed_paths` or of the compare answer exists in `head/cmapi/src`. Each caller of `changed_paths` either handles `IncompleteList` or treats `GitUnavailable` safely (the job is tried again and nothing merges). List each caller with its file and line.

C3. In `pr_checks`, a branch whose list is not complete cannot get `cmapi/check: success` and cannot be merged by the worker: read lines 56 to 95 of `head/cmapi/src/cmapi/jobs/pr_checks.py`. Say whether the string put in `outside` can leak anything, and whether it can break `set_check` (GitHub limits a status description to 140 characters; `set_check` cuts at 140).

C4. The change does not alter behaviour for a comparison under 300 files, for the Gitea adapter, or for `FakeGit` of the tests.

Also report anything else in `change.diff` that is wrong, with the same standard of proof.
