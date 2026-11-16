# Review: issue #199 (BUG-52)

Paths below are relative to this review folder. No proven defect in `change.diff` (ignoring the `.orig` deletion); no REFUTED claim requiring a fix. `head/` is unchanged. No container or database was used. TokenSave has no index for this export; evidence comes from direct source inspection.

## C1 — PLAUSIBLE (the documented cap is handled; the universal guarantee is stronger)

`head/cmapi/src/cmapi/core/git/github.py:123` calls `self._call("compare", "GET", f"{self._repo()}/compare/{self.default_branch}...{head}")`, without pagination arguments. Lines 126–129 read `files`, raise on `len(files) >= self.COMPARE_FILES_LIMIT`, then return filenames; line 48 sets the limit to `300`. This conservatively rejects an exactly-full list, including an actually complete 300-file comparison.

GitHub's [Compare two commits](https://docs.github.com/en/rest/commits/commits#compare-two-commits) says it “includes up to 300 changed files for the entire comparison”. The same section limits **commits**, not filenames, to 250 without pagination; changed files appear only on the first page. Thus `>= 300`, not `> 300`, handles the documented file cap; changing `per_page` cannot remove it. The [REST description](https://github.com/github/rest-api-description/blob/main/descriptions/api.github.com/api.github.com.json), operation `repos/compare-commits`, repeats this rule. Its `commit-comparison` schema has no file-total or truncation flag, and does not require `files`.

**No other reason for a successful JSON file list being cut below 300 is documented in the permitted sources.** They provide no explicit converse guarantee that every shorter list is complete, either; therefore the absolute “no answer” assertion remains PLAUSIBLE, not a demonstrated bug. The compare documentation lists “500 Internal Error” and “503 Service unavailable”, not silent partial-success behavior for excessive diff size or timeouts. HTTP 5xx and client timeouts cannot become an empty/partial successful read: `head/cmapi/src/cmapi/core/git/base.py:54–61` uses `except httpx.HTTPError as exc:` and `if r.status_code >= 500:` to raise `GitUnavailable`; `github.py:124–125` rejects every other non-200. There is no primary-source-backed sub-300 counterexample to turn into a failing test.

Do not substitute the other endpoint's cap: [List pull requests files](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files) says “Responses include a maximum of 3000 files.” That endpoint defaults to 30 entries per page and is not called here.

## C2 — CONFIRMED

The sole production caller of **`changed_paths`** is `head/cmapi/src/cmapi/jobs/pr_checks.py:67`: `outside = sorted(ctx.git.changed_paths(head) - set(row.plan["files"]))`. Lines 68–69 catch `IncompleteList` and make `outside` nonempty. There is no second caller of that method in `head/cmapi/src`.

The additional **compare-response reader** is `GitHubProvider.contains`, `head/cmapi/src/cmapi/core/git/github.py:115–120`: it calls `/compare/{revision}...{sha}` and reads only `return r.json().get("ahead_by", 1) == 0`, never `files`. Gitea's separate compare readers are `head/cmapi/src/cmapi/core/git/gitea.py:95–106`: `contains` reads `total_commits`; `changed_paths` reads `commits[*].files`. A full source search finds no other compare consumers.

`head/cmapi/src/cmapi/core/git/base.py:23`: `class IncompleteList(GitUnavailable):`. For an uncaught host failure, `head/cmapi/src/cmapi/worker.py:111–117` catches `Exception` and invokes `_record_failure`; lines 129–143 either mark the request failed after five attempts or call `jobs.retry(job, err, BACKOFF[min(attempts, len(BACKOFF)) - 1])`. No merge follows a raised exception. Here the only changed-path caller handles this exception explicitly, so incompleteness fails the request rather than spending retries.

## C3 — CONFIRMED

`head/cmapi/src/cmapi/jobs/pr_checks.py:69–70`: `outside = [f"a list that is not complete: {exc}"]` followed by `cmapi_ok = not outside and head == pr.head_sha and tree == expected and plan_hash(actual) == row.plan_hash`. Thus `cmapi_ok` is false. Line 81 posts `"success" if cmapi_ok else "failure"`; lines 88–95 enter `if findings or not cmapi_ok or ci_failed:`, fail the request, close the PR, and return. The worker's merge at line 97 is unreachable on this path. If validation or a host write raises first, the worker retries; it still cannot reach that merge.

The current exception producer (`head/cmapi/src/cmapi/core/git/github.py:128`) interpolates only `head[:8]` and the constant limit into fixed text. This discloses a short commit identifier already associated with the PR, not credentials, file contents, paths, or an upstream error body. This is a property of this producer, not a sanitization guarantee for arbitrary future exception messages.

The resulting description can exceed 140 characters, but `head/cmapi/src/cmapi/core/git/github.py:192` sends `{"context": context, "state": state, "description": description[:140]}`. The reason may be shortened; its length cannot break the status call, and the independently supplied state stays `failure`.

Database-free execution proof: `report/test_review_no_db.py:15` runs the real adapter and job with matching approved/tree contents, green CI, and 300 visible approved filenames (so an omitted 301st filename could be outside). It asserts a 140-character `cmapi/check: failure` POST, failure transition, PR close, job completion, and no merge. **1 passed.** Database repositories are replaced by mocks; the HTTP client uses `MockTransport`.

## C4 — CONFIRMED

For fewer than 300 entries, `head/cmapi/src/cmapi/core/git/github.py:126–129` still returns `{f["filename"] for f in files}`, equivalent to the old expression; the HTTP/error paths are unchanged. The new exception handler has no effect when no exception is raised.

Neither alternative implementation changes in `change.diff`: `head/cmapi/src/cmapi/core/git/gitea.py:106` still returns `{f["filename"] for c in r.json().get("commits") or [] for f in c.get("files") or []}`; `head/cmapi/tests/service/conftest.py:133–137` still computes FakeGit's set from its before/after dictionaries. Neither uses the GitHub limit or raises `IncompleteList`.

The supplied database-free cases at `head/cmapi/tests/service/test_github_compare_limit.py:29–38` passed: 299 accepted, 300 and 301 rejected (**3 passed**). The fourth, database-dependent job test was not run; the independent job test above covers this path without PostgreSQL. All tests used `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, the supplied Python interpreter, and `PYTHONPATH=head/cmapi/src:head/cmapi/tests/service`.
