# #199 (BUG-52): the review of the guard for a comparison that GitHub can cut

The change is in the check that lets a pull request merge, so it has a second reader.

| Who | What |
|---|---|
| OB1, Fable 5.2 | The change (commit `51d3367`), the rulings and this record |
| Codex `gpt-6.1-sol`, 2026-11-13, 89,368 tokens | Four claims on an export of that commit: `brief.md`. Its report: `codex-report.md` |

## The rulings

| Claim | Codex | Ruling |
|---|---|---|
| C1. No answer that GitHub can have cut is read as complete | PLAUSIBLE. The documented limit is 300 files for the whole comparison, `>= 300` is the right test, and a change of `per_page` cannot remove the limit. GitHub documents no other cause of a shorter list, and it gives no promise that each shorter list is complete | Stands as PLAUSIBLE. The fix covers the limit that GitHub documents. Nothing more can be proven from the documents: #61 (the first real run) can measure it |
| C2. `pr_checks` is the one caller of `changed_paths`, and `contains` does not read `files` | CONFIRMED | Stands |
| C3. A branch whose list is not complete cannot get `cmapi/check: success`, and the worker does not merge it. The text of the failure holds 8 characters of the commit and a constant, and `set_check` cuts it at 140 characters | CONFIRMED, with a test of Codex's own that needs no database: 1 passed | Stands |
| C4. Nothing changes for a comparison under 300 files, for the Gitea adapter or for the tests' `FakeGit` | CONFIRMED | Stands |

Codex found no defect, so no fix came from this review. Its extra test repeats `test_the_cmapi_check_fails_when_the_host_cannot_list_each_changed_file` with mocks in place of the database, so it is not added to the suite.

One fact from the report: a comparison of exactly 300 files that is complete is refused also. That is the cost of a limit with no "cut" flag in GitHub's answer, and a plan of cmapi has a few files.

## Not tested

No request went to GitHub (#61). The limit is from GitHub's documents, not from a measurement.
