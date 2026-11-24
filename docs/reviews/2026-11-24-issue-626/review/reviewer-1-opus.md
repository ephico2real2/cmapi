# PR #647 (closes #626): reviewer 1 (Opus 5.5 at high, standing in for Codex)

Reviewer 1 of PR #647. Codex hit its usage limit partway through this review, so a separate Opus 5.5 agent at `high` took the
role. That agent did not write the change. I read Codex's partial work (`codex-result.txt` and `.review-tmp/`) as leads only.
Every result below is my own: each was measured in this export or read from the cited source.

- Export: `review-647/head/` (the PR head) and `review-647/base/` (main `ff5e992`).
- Copies: my working copies are in `review-647/r1-outputs/work/`. `head/` and `base/` are unchanged.
- Tests: every test ran on macOS against PostgreSQL 16 at `127.0.0.1:55432/cmapi_wt605`, with the brief's command
  (`r1-outputs/run.sh`). No cluster was used, and no git repository or GitHub was touched.
- Output: the patch is `r1-outputs/fix.diff`. Applied to a fresh copy of `head/` with `patch -p1 -F0`, it applied cleanly and
  gave a tree identical to `work/fix` (checked with `diff -rq`).

## Summary

| # | Severity | Finding | Before the fix (head, measured) | After |
|---|---|---|---|---|
| F1 | **Medium** | `merge._merged` reads the folder at the merge sha with no `NotUtf8` handling. | When a name landed during the host's merge, the request took 5 errors and ended **`failed`** (argocd) or **`merge_failed`** (apply), although the host had merged the PR. | Merged, then `sync_failed` with the path in the note, and no errors |
| F2 | Medium | `pr_checks` reads main's folder *before* the merge check. The README claims the merge check catches it first; that claim is false for this read. | A name that landed while the PR was open gave 5 errors, then `failed`. | `superseded` with the path, and the PR closed |
| F3 | Low | The Gitea stand-in creates the branch, *then* reads the folder. `push_branch` does not catch a `NotUtf8` raised by the push itself. | The branch was left at main's commit, and git_cleanup keeps it as foreign. A `NotUtf8` from the push gave 5 errors, then `failed`. | The branch is deleted, and the request is `superseded` |
| F4 | Low | The `\xNN` escape is not one-to-one: two different byte names show the same text. | `b"a\xe9\\xff"` and `b"a\\xe9\xff"` both showed as `a\xe9\xff`; `paths` listed the same string twice. | A backslash in such a name is doubled, as Git's `core.quotePath` does |
| F5 | Low | The detail says "is not UTF-8" for a name that *is* UTF-8 but holds U+FFFD. | `…caf�.yaml, whose name is not UTF-8` | "whose name is not UTF-8 or holds U+FFFD" |
| F6 | Low (also present before this PR) | The contract examples for `folder-not-utf8` and `folder-holds-submodule` leave out `paths`. `PROBLEM_EXTRAS` exists so that examples show such members. | `KeyError: 'paths'` | Both examples show `paths`; the contract is regenerated |
| F7 | Low | `watch_sync` compares main's folder outside the `as_plan` rule. | 5 errors, then the same `sync_failed` | `sync_failed` at once, with no errors |

Run results:

- **On head:** the 11 review tests all fail (`r1-outputs/review-on-head.log`). The end states come from a scratch probe, not
  shipped: `r1-outputs/head-states-probe.txt`.
- **On the fix:** the 11 review tests and the PR's 17 all pass, 28 in total (`review-on-fix.log`).
- **Adjacent suites on the fix:** see "Regression check" at the end.

## Research: the sources, fetched 2026-11-24 13:40 UTC (`r1-outputs/sources/`, `fetched-at.txt`)

Every quote in the implementer's README was checked against these files.

- **git-ls-tree(1)** (<https://raw.githubusercontent.com/git/git/master/Documentation/git-ls-tree.adoc>):
  - `-z`: "\0 line termination on output and do not quote filenames."
  - Output format: "Without the `-z` option, pathnames with "unusual" characters are quoted as explained for the configuration
    variable `core.quotePath` (see linkgit:git-config[1]). Using `-z` the filename is output verbatim and the line is terminated
    by a NUL byte."
  - **The README's quote matches.**
- **core.quotePath** (<https://raw.githubusercontent.com/git/git/master/Documentation/config/core.adoc>, line 159): "…escaping
  those characters with backslashes in the same way C escapes control characters (e.g. `\t` for TAB, `\n` for LF, `\\` for
  backslash) or bytes with values larger than 0x80 (e.g. octal `\302\265` for "micro" in UTF-8)… **Double-quotes, backslash
  and control characters are always escaped regardless of the setting of this variable.** … Many commands can output pathnames
  completely verbatim using the `-z` option. The default value is true."
  - The README's quote matches, but it leaves out the bolded sentence. That sentence is Git's own rule for keeping an escape
    unambiguous, and F4 rests on it.
- **Documentation/i18n.adoc** (<https://raw.githubusercontent.com/git/git/master/Documentation/i18n.adoc>):
  - "Path names are encoded in UTF-8 normalization form C."
  - "Note that Git at the core level treats path names simply as sequences of non-NUL bytes, there are no path name encoding
    conversions (except on Mac and Windows)…"
  - "many Git-based tools simply assume path names to be UTF-8 and will fail to display other encodings correctly."
  - **Matches.**
- **Python `codecs`** (<https://docs.python.org/3/library/codecs.html>, the "Python 3.15.2 documentation" page):
  - `'backslashreplace'`: "Replace with backslashed escape sequences. … On decoding, use hexadecimal form of byte value with
    format \xhh."
  - `'surrogateescape'`: "On decoding, replace byte with individual surrogate code ranging from U+DC80 to U+DCFF. This code
    will then be turned back into the same byte when the 'surrogateescape' error handler is used when encoding the data."
  - `'replace'`: "On decoding, use � (U+FFFD, the official REPLACEMENT CHARACTER)."
  - **Matches.** Note that `backslashreplace` leaves a backslash that is already in the input as it is, so the result is not
    one-to-one. F4 measures this.
- **PEP 383** (<https://peps.python.org/pep-0383/>, Status: Final): "this interface has the limitation that chosen
  representation only "works" if the data get converted back to bytes with the surrogateescape error handler also. Encoding
  the data with the locale's encoding and the (default) strict error handler will raise an exception…"
  - **Matches.** The README uses straight quotes where the PEP has curly ones.
- **RFC 9457** (<https://www.rfc-editor.org/rfc/rfc9457.txt>):
  - §3.1.4: "The "detail" string, if present, ought to focus on helping the client correct the problem, rather than giving
    debugging information. Consumers SHOULD NOT parse the "detail" member for information; extensions are more suitable and
    less error-prone ways to obtain such information."
  - §3.2: "Problem type definitions MAY extend the problem details object with additional members that are specific to that
    problem type."
  - §5: "avoid making implementation details such as a stack dump available through the HTTP interface".
  - **Matches.**
- **RFC 9110** (<https://www.rfc-editor.org/rfc/rfc9110.txt>):
  - §15.5.10: "The 409 (Conflict) status code indicates that the request could not be completed due to a conflict with the
    current state of the target resource. This code is used in situations where the user might be able to resolve the
    conflict and resubmit the request. The server SHOULD generate content that includes enough information for a user to
    recognize the source of the conflict."
  - §15.5.21 (422): "the server understands the content type of the request content … and the syntax of the request content
    is correct, but it was unable to process the contained instructions."
  - **The 409 quote matches.**
- **Gitea and json-iterator**, the README's claim, which it read from source:
  - <https://raw.githubusercontent.com/go-gitea/gitea/v1.25.0/modules/json/json.go> line 36: `DefaultJSONHandler Interface =
    JSONiter{jsoniter.ConfigCompatibleWithStandardLibrary}`. The same holds at v1.25.2 and on `release/v1.25`, whose `go.mod`
    pins `github.com/json-iterator/go v1.1.12`.
  - <https://raw.githubusercontent.com/json-iterator/go/v1.1.12/config.go> line 55: `ConfigCompatibleWithStandardLibrary =
    Config{EscapeHTML: true, …}`.
  - `stream_str.go` line 276: `if c == utf8.RuneError && size == 1 {`, then at line 280: `` stream.WriteRaw(`�`) ``.
  - **Matches. The README is right that this was read from source and not measured.**

## The claims

### 1. The retraction: confirmed

Both halves were measured on `base/`'s source.

- **422 on main, not 500.** On main, `main.py:227-229` maps every `ValueError` to 422 `validation-failed`
  (`@app.exception_handler(ValueError) … Problem.unprocessable("validation-failed", str(exc)[:300])`). Python's
  `UnicodeDecodeError.__mro__` is `(UnicodeDecodeError, UnicodeError, ValueError, …)`. Running the PR's test file against base
  (`r1-outputs/base-626.log`: 16 failed, 1 passed) recorded at `:174` the answer
  `{"…validation-failed","status":422,"detail":"'utf-8' codec can't decode byte 0xe9 in position 93: invalid continuation byte"}`.
- **GitHub's REST answer holds U+FFFD.** All four saved answers in `github-probe/` carry the bytes `EF BF BD` and no byte
  `0xE9`. I also recomputed the Git tree object IDs from the saved JSON:
  - Tree `6774dc96…`: hashing the entries with the name byte `0xE9` gives exactly `6774dc96…` (True). Hashing them with
    `EF BF BD` gives `36ff8043…` (False).
  - Tree `8ed23cd7…`: the same result.
  - So the object GitHub stored holds the Latin-1 byte, and the JSON it answered lost that byte. This rests on GitHub's own
    object IDs, not on the implementer's word.
  - Script and output: `r1-outputs/tree_hash_check.py` and `tree_hash_check.txt`.

### 2. 409 or 422: 409 is right

- The request content is valid. What blocks it is the state of the target resource, the namespace's folder in Git. A person
  can fix that state and send the request again. That is exactly what RFC 9110 §15.5.10 describes.
- 422 (§15.5.21) is about the request content being "unable to process the contained instructions". Nothing in the request is
  wrong.
- This matches how cmapi already uses 409 in `core/docs.py:43-55`: `namespace-exists` ("payments-dev is already in Git") and
  `folder-holds-submodule` (#616) are both conflicts with what is in Git, and the caller fixes them in Git. `paths` plays the
  same part as `folder-holds-submodule`'s `paths`.
- One note on GET: 409 on a GET of the namespace is unusual, but §15.5.10 does not restrict it to writes. The read cannot
  build the namespace's view while the folder is in that state, and the person can fix it.
- Ruling: **409 is right.** (F6: the contract's example should show the `paths` member.)

### 3. A delete never skips a file it cannot name: confirmed

A delete refuses at every depth on the Git layer (`_entries` uses `ls-tree -r`), on GitHub REST (`refuse_lost_names` over the
recursive tree), and on Gitea (`refuse_lost_names` over `_walk`). The mutants decide it (see claim 8):

| Mutant | Tests that fail |
|---|---|
| `depth-git` | 3 |
| `depth-github` | 1 |
| `depth-gitea` | 1 |

**A U+FFFD typed on purpose** (`"caf�.yaml"` as real UTF-8): the Git layer refuses it
(`test_a_name_that_holds_u_fffd_is_refused_as_the_rest_reads_refuse_it` passes, and the `fffd-git` mutant fails it).

Ruling: **acceptable.**

- The API process plans through REST. GitHub answers a lost byte as U+FFFD, and the probe's tree object IDs prove the byte
  is gone from the answer. So from the REST answer alone the two cases cannot be told apart.
- If the Git layer accepted a literal U+FFFD that REST must refuse, the worker and the API would disagree about which folders
  can be carried. That is the split #626 exists to remove.
- The Python docs name U+FFFD "the official REPLACEMENT CHARACTER", a stand-in for data that could not be decoded. A
  manifest file name that holds it on purpose is not a legitimate name worth an exception.
- The refusal is narrow. It applies only to `.yaml` names directly in the folder for a change, and to every path for a delete.
  It changes nothing in Git, and its detail tells the person to rename the file.
- What was wrong is the detail's wording, which calls such a name "not UTF-8" (F5).

### 4. Superseding is safe

| Question | Answer | Evidence |
|---|---|---|
| Status and events | `superseded` (from `approved` or `pr_open` on `BASE_CHANGED`, `lifecycle.py:67,70`). `superseded` is in `TERMINAL` and not in `_LOCK` (`:93-94`), so the lock is released. The `base_changed` event's note names the path, for example `folder changed in Git since the plan: the name of …/caf\xe9.yaml is not UTF-8`. | The PR's `test_a_name_that_reaches_the_folder_after_the_plan_supersedes_the_request` passes, and the `retry` mutant fails both of its cases. |
| Can it leave a branch or a PR? | **Git layer and GitHub: no.** The check runs before `push_request_branch`, and the PR's test asserts that no `cmapi/*` branch exists. **Gitea: yes, in a race (F3).** `push_request_branch` creates the branch from main and then reads the folder (`gitea.py:137` then `:141`). If that read raises, the branch stays at main's commit. The retry supersedes, and `git_cleanup` (`git_cleanup.py:37-45`) finds a head that is neither `ours` nor this request's, so it records `branch_kept` and counts `cmapi_git_orphans_total{kind="foreign_branch"}`. The same gap applies to a `GitUnavailable` on those reads (present before this PR). | `test_the_gitea_stand_in_leaves_no_branch_when_it_cannot_read_the_folder` fails on head and passes with the fix. |
| Is the operator told why? | Yes, in the note, with the path; it is cut at 240 characters (three paths, then "and more"). The note does not say what to do; a new request's 409 says that. Acceptable. | |
| What the PR missed | A `NotUtf8` raised by `push_request_branch` (Gitea reads the folder again) is not caught: 5 errors, then `failed` (measured: `status=failed errors=5`). | `test_a_name_the_push_finds_supersedes_the_request` |

### 5. A change ignores names it never reads: consistent

The rule is "the `.yaml` files directly in the folder" everywhere it applies:

- a change's plan (`read_folder`, which reads that set on every provider);
- `push_branch`'s comparison;
- the merge check for a change (`_folder`, which reads the same set);
- watch_sync.

A delete instead uses the whole listing for its plan, for `push_branch` and for the merge check (`whole_folder`). So a
subfolder's or a README's name that is not UTF-8 is allowed for a change and refused for a delete, at every step. The PR's
`test_a_change_is_not_refused_for_a_name_it_never_reads` shows this, and the `depth-git` mutant fails it.

**Is there a path where a change is planned and then fails at merge forever?** Not for a name the change never reads: no
later step reads it either.

For a direct `.yaml` name that lands **after an apply** (apply mode), the merge check refuses with each `:retry`, and the
request stays `merge_failed` until Git is fixed. That is the designed state after an apply (the cluster is ahead of main),
not a defect. Its reason, "the folder on main at X is no longer the plan's base", does not name the path, because `as_plan`
drops the `NotUtf8`. I record this as an observation, not a finding: the operator sees the same folder in Git, where
`git ls-tree` shows the quoted name.

The real "fails forever" path was F1: after the host's merge, the merged request read as `merge_failed`, and every `:retry`
went `merge` → `pr_status` "merged" → `_merged` → `NotUtf8` again.

### 6. The five reads on the retry-then-fail path

The worker gives each job 5 attempts with backoff `(5, 15, 45, 135, 405)` seconds (`worker.py:43-44,149-171`), then it
finishes the job and moves the request by its status. None of these reads is in a recurring job: `git_reconcile` and
`git_cleanup` read no folder. Nothing loops without bound, and the logs get at most 5 `job_failed` lines per job.

| Read | Head, measured | Ruling |
|---|---|---|
| `merge._merged` (`merge.py:141,145`) | Reached **after the host merged**. 5 errors, then `failed` (argocd) or `merge_failed` (apply), with `host.prs[1].merged == True`. The request says the change failed while main holds it, and Argo CD syncs it. In apply mode, every `:retry` repeats the failure. | **F1, Medium. Fix now.** |
| `pr_checks`' base read (`pr_checks.py:93`) | It runs **before** `merge_check` (`:134`). 5 errors, then `failed`, where the merge check would have given `superseded`. The README says "the usual path is superseded or `merge_failed` before these reads"; that is false for this read. | **F2. Fix now.** |
| A delete's head check (`pr_checks.py:91`), `pr_checks`' head tree (`:74`), and `apply`'s head tree (`apply.py:79`) | These read the bot's own branch, which holds such a name only if a person pushed one to it. 5 errors, then `failed` (or `sync_failed` once an apply started): the same end state a failed check gives. | Leave as is, and say so (the README is updated). |
| `watch_sync` (`watch_sync.py:89,121`) | 5 errors, then the same `sync_failed` that `_refuse` gives at once. | F7, Low: `as_plan`, the merge check's own rule. |
| `open_revert` (`open_pr.py:70,73`) and `prune`'s retry (`watch_sync.py:230`) | On a `sync_failed` request, the worker has no transition for that status. 5 error events, the request stays `sync_failed`, and `:revert` and `:retry` are still offered. | Leave as is. Bounded, and the request stays recoverable. |

### 7. The escape: ambiguous, measured (F4)

Python's `backslashreplace` escapes only the bytes it cannot decode. A backslash that is already in the name stays as it is.
So `b"a\xe9\\xff"` and `b"a\\xe9\xff"` both show as `a\xe9\xff`. Measured on the real Git layer: a folder holding both
names gives `NotUtf8.paths == ['…/a\\xe9\\xff.txt', '…/a\\xe9\\xff.txt']`, the same string twice, so a client cannot tell
which file to rename.

Git's own quoting avoids this by always escaping the backslash (core.quotePath, quoted above). The fix does the same, but only
for names that are not UTF-8: `shown()` doubles each backslash, then applies `backslashreplace`. That mapping is one-to-one,
and a name with no backslash shows exactly as before, so the PR's `SHOWN` and its contract example are unchanged.

**Collisions with a valid plan path.** In `changed_paths` and `_adoptable`, an escaped name could equal a literal, valid name
that a plan holds, such as a delete of a file literally named `a\xe9`. I checked whether that changes any decision:

- `pr_checks` also requires `head == pr.head_sha`, and that fails whenever a person pushed.
- `_adoptable` needs this request's trailers, and is followed by `merge_check(whole_folder)`, which reads strictly.

So the collision changes no outcome; I rate it display only. Both now go through `path_text`, so every place shows a name the
same way.

### 8. The tests

**The PR's file** passes 17/17 on head (`head-626.log`). On base's source plus a stub `NotUtf8`, 16 fail and 1 passes
(`base-626.log`), which reproduces the implementer's `test-before.txt`. The one test that passes on base,
`test_the_gitea_merge_check…`, is explained by the README: on main, Gitea's lossy read happened to refuse that merge. That
explanation is right.

**Mutants** (`r1-outputs/mutants/make.py`, one exact substitution each; logs in `mut-*.log`):

| Mutant | Change | Result |
|---|---|---|
| `fffd-git` | `git_name` returns `name, True` | killed, 1 failed |
| `fffd-rest` | `refuse_lost_names` refuses nothing | killed, 4 failed |
| `retry` | `push_branch` re-raises `NotUtf8` | killed, 2 failed |
| `depth-git` | `_entries` refuses only names directly in the folder | killed, 3 failed |
| `depth-github` | GitHub `list_folder` refuses only names directly in the folder | killed, 1 failed |
| `depth-gitea` | Gitea `list_folder` refuses only names directly in the folder | killed, 1 failed |
| `replace` | `errors="replace"` in `git_name` and `changed_paths` | killed, 7 failed |

**Can each assertion fail?** Each one is tied to a mutant or to the base run above, with these exceptions:

- `r.headers["content-type"] == "application/problem+json"` also holds on base's 422. Only the status assertion decides that
  test.
- The supersede test's "no `cmapi/*` branch" assertion cannot fail on the Git layer, because the check runs before any push.
  It guards against a future reorder.

**What the file does not cover:** F1, F2, F3 (both parts), F4 and F7. The review's file covers them.

## The findings, each with its full fix and its test

Every hunk below is copied from `r1-outputs/fix.diff`. Every test is in
`cmapi/tests/service/test_non_utf8_review_647.py` (full text in the appendix). Each test fails on head and passes with the fix
(`review-on-head.log`, `review-on-fix.log`).

### F1 (Medium): `_merged` fails a request whose PR the host already merged

**What, where.** `jobs/merge.py:141-145`. `_merged` runs after the host merged, both after cmapi's own merge and when
`pr_checks`, `merge` or `apply` finds a person's merge. It reads the folder at the merge sha with `tree_files` (for a delete,
also `list_folder`). A name or text that is not UTF-8 there raises `NotUtf8` before `MERGED` is recorded.

**How it happens.** A person's commit lands on main between the merge check and the host's merge, or someone merges a PR by
hand onto such a main.

**Measured on head** (`head-states-probe.txt`). The host merged (`prs[1].merged == True`), and then:
- argocd mode: 5 errors, and the request ends **`failed`**, its lock released, with no `merge_sha`. It says the change failed
  while main holds it, and Argo CD syncs it.
- apply mode: 5 errors, and the request ends **`merge_failed`**. Each `:retry` runs `merge` → `pr_status` "merged" →
  `_merged` → `NotUtf8` again.

**Fix.** Read `NotUtf8` as "not the plan's", which is `_merged`'s own documented outcome for such a folder ("merged and then
sync_failed, with the lock held for an operator", #449). Put the path in the note, so the operator is told why.

```diff
--- a/cmapi/src/cmapi/jobs/merge.py
+++ b/cmapi/src/cmapi/jobs/merge.py
@@ -21,7 +21,7 @@
 from cmapi.core.context import AppContext
 from cmapi.core.db.models import JobRow
 from cmapi.core.db.repo import JobRepo, RequestRepo
-from cmapi.core.git.base import HeadMoved, NotMergeable, PlatformRefused
+from cmapi.core.git.base import HeadMoved, NotMergeable, NotUtf8, PlatformRefused
 from cmapi.core.lifecycle import Event as E, State as S
 from cmapi.core.git.workspace import BranchRefused
 from cmapi.core.observability import GIT_ORPHANS, LEAD_TIME, MERGE_CONFLICTS
@@ -138,11 +138,15 @@
     watch_sync. A merge whose folder is not the plan's, or with no sha to read, is merged and then sync_failed, with the lock
     held for an operator: nothing is applied from it and a delete never waits for a prune of it (#449)."""
     after_apply = row.status in AFTER_APPLY
-    on_main = ctx.git.tree_files(sha, folder(row.cluster_id, row.namespace)) if sha else None
-    fulfilled = on_main == planned(row)
-    if fulfilled and row.action == "delete":
-        # A delete's folder is empty at the merge: no file of any kind, at any depth, is left of it (#616).
-        fulfilled = not ctx.git.list_folder(folder(row.cluster_id, row.namespace), sha)[0]
+    unreadable: NotUtf8 | None = None
+    try:
+        fulfilled = bool(sha) and ctx.git.tree_files(sha, folder(row.cluster_id, row.namespace)) == planned(row)
+        if fulfilled and row.action == "delete":
+            # A delete's folder is empty at the merge: no file of any kind, at any depth, is left of it (#616).
+            fulfilled = not ctx.git.list_folder(folder(row.cluster_id, row.namespace), sha)[0]
+    except NotUtf8 as exc:
+        # The merge happened: a folder no plan can hold (#626) is not the plan's, recorded, never retried into pr_failed.
+        fulfilled, unreadable = False, exc
     row.merge_sha = sha or None
     how = "adopted: merged on the host" if adopted else "merged"
     repo.event(row, "merge_verified", "worker", f"{how} {sha[:8]}; the folder at it {'is' if fulfilled else 'is not'} the plan's",
@@ -150,7 +154,7 @@
     repo.move(row, E.MERGED, "cmapi-bot", f"{how} {sha[:8]}")
     if not fulfilled:
         why = f"the folder at the merge {sha[:8]} is not the approved plan" if sha else "the host gave no merge sha to check"
-        repo.move(row, E.SYNC_TIMEOUT, "worker", why)
+        repo.move(row, E.SYNC_TIMEOUT, "worker", f"{why}: {unreadable}"[:240] if unreadable else why)
     elif after_apply:
         repo.move(row, E.SYNCED, "cmapi-deliverer", "applied and confirmed by a read before the merge")
         approval = "auto" if (row.requirement or {}).get("auto") else "human"
```

**Test.** `test_a_name_that_lands_during_the_hosts_merge_leaves_the_request_merged_then_sync_failed[argocd|apply]`. `merge_hook` commits `caf\xe9.yaml` to main inside the host's merge. The test asserts the PR merged, status `sync_failed`, no `error` events, and the path in a note.

### F2 (Medium): `pr_checks` reads main's folder before its merge check

**What, where.** `jobs/pr_checks.py:93` reads main's folder (`base`, for the validators) before `merge_check` at `:134`. The
README says "The merge check, which runs before every merge in `pr_checks` and `merge`, reads such a folder as not the plan's,
so the usual path is superseded or `merge_failed` before these reads". **That is false for this read; I retract it from the
record.**

**Measured on head.** A `caf\xe9.yaml` committed to main while the PR is open gives 5 errors, then **`failed`**
(`head-states-probe.txt`).

**Fix.** The same refusal the merge check would make: `BASE_CHANGED` (legal from `pr_open`, `lifecycle.py:70`, and already
used by this job at `:141`), with the path in the note, and the PR closed through `end_pr`.

```diff
--- a/cmapi/src/cmapi/jobs/pr_checks.py
+++ b/cmapi/src/cmapi/jobs/pr_checks.py
@@ -23,7 +23,7 @@
 from cmapi.core.context import AppContext
 from cmapi.core.db.models import JobRow
 from cmapi.core.db.repo import JobRepo, RequestRepo, utcnow
-from cmapi.core.git.base import IncompleteList
+from cmapi.core.git.base import IncompleteList, NotUtf8
 from cmapi.core.observability import MERGE_CONFLICTS
 from cmapi.core.lifecycle import Event as E, State as S
 from cmapi.core.ports import PrRef
@@ -90,7 +90,15 @@
         # pass a head that keeps a path, which a person could then merge by hand (#616).
         cmapi_ok = not ctx.git.list_folder(folder(row.cluster_id, row.namespace), head)[0]
     # The default branch's folder is what this merge changes: a value that it already holds is not refused (#212).
-    base, _ = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
+    try:
+        base, _ = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
+    except NotUtf8 as exc:
+        # Main's folder holds a name or text no plan holds (#626): not the plan's base, as the merge check below would read it.
+        why = f"the folder on {ctx.git.default_branch} is no longer the plan's base: {exc}"
+        repo.move(row, E.BASE_CHANGED, "worker", why[:240])
+        end_pr(ctx, repo, jobs, row, why)
+        jobs.done(job)
+        return
     findings = ctx.pipeline.validator.validate(tree, row.cluster_id, row.env, previous=base)
     # Only an error fails a check. In audit a Kyverno finding is a warning (core/validate, #213): the plan showed it and the
     # approvers accepted it, so the PR check reports it and does not fail, as the cluster's Audit action does.
```

**Test.** `test_a_name_that_lands_on_main_while_the_pr_is_open_supersedes_it`: status `superseded`, no errors, the path in a note, and the PR closed and not merged.

### F3 (Low): the Gitea stand-in leaves a branch behind; `push_branch` retries a `NotUtf8` from the push

**What, where.** `core/git/gitea.py:137-141`: `create_branch` comes first, then `read_folder(req.folder, branch)`. If the
read raises (a name that landed since the job's own read, or a `GitUnavailable`, which predates this PR), the branch is left at
main's commit:
- The retry supersedes.
- `git_cleanup` keeps the branch as foreign (`branch_kept`, `cmapi_git_orphans_total{kind="foreign_branch"}`).
- A plain retry would instead get `BranchRefused`.

`jobs/push_branch.py:49-50` does not catch the `NotUtf8` that this read raises.

**Measured on head:**
- `host.branch_exists` stays `True` after the `NotUtf8`.
- A `NotUtf8` from `push_request_branch` gives `status=failed errors=5`.

**Fix:**
- Gitea deletes the branch it just made, conditionally on main's commit, before it re-raises.
- `push_branch` supersedes on a `NotUtf8` from the push. The supersede is factored into `_superseded`, so it is written once.

Reading the folder at `base` before creating the branch would close the window as well. I did not choose it: it breaks the
existing Gitea stand-in tests, whose stub serves a tree only at the branch head (`test_gitea_review.Host`; Codex's run of that
change failed `test_this_requests_current_commit_is_adopted_with_no_write`).

```diff
--- a/cmapi/src/cmapi/core/git/gitea.py
+++ b/cmapi/src/cmapi/core/git/gitea.py
@@ -138,9 +138,18 @@
                        json={"new_branch_name": branch, "old_ref_name": base}, ok=(201,))
         if r.status_code != 201:
             raise GitUnavailable(f"create branch {branch}: {r.status_code} {self.host_text(r, 200)}")
-        current, _ = self.read_folder(req.folder, branch)
-        # A removal is any path of the folder, not only a manifest (#616). Only a plan that removes one walks the subfolders.
-        listed = self._walk(req.folder, branch)[0] if any(text is None for text in req.files.values()) else {}
+        try:
+            current, _ = self.read_folder(req.folder, branch)
+            # A removal is any path of the folder, not only a manifest (#616). Only a plan that removes one walks the subfolders.
+            listed = self._walk(req.folder, branch)[0] if any(text is None for text in req.files.values()) else {}
+        except Exception:
+            # The branch is main's commit and holds nothing of cmapi's yet. Left there, a retry would find a head that is not this
+            # request's and refuse it, and git_cleanup would keep it as foreign (#626: a name that landed since the job's read).
+            try:
+                self.delete_branch(branch, base)
+            except GitUnavailable:
+                pass                             # the read's own error is the one to report; git_reconcile sweeps the branch
+            raise
         ops = []
         for path, text in req.files.items():
             if text is None:
```
```diff
--- a/cmapi/src/cmapi/jobs/push_branch.py
+++ b/cmapi/src/cmapi/jobs/push_branch.py
@@ -40,14 +40,14 @@
             # The plan refuses a folder that holds such a path, so the folder changed since: superseded, never retried (#626).
             changed = f"folder changed in Git since the plan: {exc}"
         if changed:
-            repo.move(row, E.BASE_CHANGED, "worker", changed[:240])
-            jobs.done(job)
-            jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
-            return
+            return _superseded(repo, jobs, job, row, changed)
         req = branch_request(ctx, row)
         jobs.fence()
         try:
             pushed = ctx.git.push_request_branch(req)
+        except NotUtf8 as exc:
+            # The Gitea stand-in reads the folder again as it writes: a name that landed since the read above (#626).
+            return _superseded(repo, jobs, job, row, f"folder changed in Git since the plan: {exc}")
         except BranchRefused as exc:
             GIT_ORPHANS.labels("foreign_branch", "refused").inc()
             repo.event(row, "branch_refused", "worker", str(exc)[:300], {"branch": request_branch(row.cluster_id, row.request_id)})
@@ -59,3 +59,10 @@
                    {"head": pushed.head, "base": pushed.base, "adopted": pushed.result == "adopted", "result": pushed.result})
         jobs.done(job)
         jobs.enqueue("open_pr", request_id=row.request_id, cluster_id=row.cluster_id, payload={"head": pushed.head, "base": pushed.base})
+
+
+def _superseded(repo: RequestRepo, jobs: JobRepo, job: JobRow, row, why: str) -> None:
+    """The folder on main is not the plan's base: superseded, the lock released, and git_cleanup for anything left."""
+    repo.move(row, E.BASE_CHANGED, "worker", why[:240])
+    jobs.done(job)
+    jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
```

**Test.** `test_the_gitea_stand_in_leaves_no_branch_when_it_cannot_read_the_folder` (on `RestHost`: the branch is created, then gone) and `test_a_name_the_push_finds_supersedes_the_request` (on the layer: `superseded`, no errors, the path in a note).

### F4 (Low): the escape in `paths` is not one-to-one

**What, where.** `core/git/base.py` `git_name`, and `workspace.py` `changed_paths` and `_adoptable`. `backslashreplace` keeps
a literal backslash as it is. Measured: `git_name(b"a\xe9\\xff.yaml")` and `git_name(b"a\\xe9\xff.yaml")` both give
`'a\xe9\xff.yaml'`, and a folder holding both lists the same path twice in `paths`.

**Fix.** Double the backslash of a name that is not UTF-8, as Git's quoting always escapes a backslash (core.quotePath), then
apply `backslashreplace`. A name with no backslash, such as the PR's `caf\xe9.yaml`, shows as before. `changed_paths` and
`_adoptable` show names the same way, through `path_text`.

```diff
--- a/cmapi/src/cmapi/core/git/base.py
+++ b/cmapi/src/cmapi/core/git/base.py
@@ -74,13 +74,28 @@
         super().__init__(f"the {part} of {', '.join(self.paths[:3])}{' and more' if len(self.paths) > 3 else ''} is not UTF-8")
 
 
-def git_name(raw: bytes) -> tuple[str, bool]:
-    """A name as `git ls-tree -z` gives it ("the filename is output verbatim", git-ls-tree(1)), as text, and whether cmapi can
-    carry it: valid UTF-8 with no U+FFFD. A name it cannot carry comes back with each byte that is not UTF-8 as \\xNN, to show."""
+def shown(raw: bytes) -> str:
+    """A name that is not UTF-8, to show: each byte that is not UTF-8 as \\xNN (codecs, 'backslashreplace'), and each
+    backslash doubled, as Git's own quoting escapes it (core.quotePath), so no two names show the same (#626)."""
+    return raw.replace(b"\\", b"\\\\").decode(errors="backslashreplace")
+
+
+def path_text(raw: bytes) -> str:
+    """A path Git gave as bytes, as text: verbatim when it is UTF-8, else as shown() shows it."""
     try:
-        name = raw.decode()
+        return raw.decode()
     except UnicodeDecodeError:
-        return raw.decode(errors="backslashreplace"), False
+        return shown(raw)
+
+
+def git_name(raw: bytes) -> tuple[str, bool]:
+    """A name as `git ls-tree -z` gives it ("the filename is output verbatim", git-ls-tree(1)), as text, and whether cmapi can
+    carry it: valid UTF-8 with no U+FFFD. A name it cannot carry comes back as shown() shows it."""
+    name = path_text(raw)
+    try:
+        raw.decode()
+    except UnicodeDecodeError:
+        return name, False
     return name, REPLACEMENT not in name
 
 
```
```diff
--- a/cmapi/src/cmapi/core/git/workspace.py
+++ b/cmapi/src/cmapi/core/git/workspace.py
@@ -37,7 +37,8 @@
 from pathlib import Path
 from typing import Iterable, Iterator, Literal, Mapping
 
-from cmapi.core.git.base import BranchRequest, GitUnavailable, MergeCheck, NotUtf8, PushResult, as_plan, git_name, manifest_text
+from cmapi.core.git.base import (BranchRequest, GitUnavailable, MergeCheck, NotUtf8, PushResult, as_plan, git_name, manifest_text,
+                                 path_text)
 from cmapi.core.git.oplog import Op, redact, register_secret
 from cmapi.core.git.transport import Credentials, GitConfigError, Remote, check_path, git_environment, load_credentials, parse_remote
 from cmapi.core.observability import GIT_WORKDIR_BYTES, GIT_WORKTREES, SWEEPER_RUNS, log
@@ -384,8 +385,8 @@
             main = self.fetch_main()
             self._need(head)
             out = self._m("diff", "--name-only", "--no-renames", "-z", f"{main}...{head}").stdout
-        # Compared with the plan's paths and shown, never written: a name that is not UTF-8 shows its bytes as \xNN (#626).
-        return {p for p in out.decode(errors="backslashreplace").split("\0") if p}
+        # Compared with the plan's paths and shown, never written: a name that is not UTF-8 is shown as path_text shows it (#626).
+        return {path_text(p) for p in out.split(b"\0") if p}
 
     def log(self, n: int = 20) -> list[str]:
         with self._lock:
@@ -433,8 +434,8 @@
         t = self.trailers(head)
         if t[TRAILER_REQUEST] != [req.request_id] or t[TRAILER_PLAN_HASH] != [req.plan_hash]:
             return "its trailers are not this request's and plan's"
-        diff = self._m("diff", "--name-only", "--no-renames", "-z", parent, head).stdout.decode(errors="backslashreplace")
-        changed = {p for p in diff.split("\0") if p}
+        diff = self._m("diff", "--name-only", "--no-renames", "-z", parent, head).stdout
+        changed = {path_text(p) for p in diff.split(b"\0") if p}
         if not changed <= set(req.files):
             return f"it changes {sorted(changed - set(req.files))[:3]}, outside the plan"
         if not as_plan(lambda: self._folder(head, folder) == {p: t for p, t in req.files.items() if t is not None}):
```

**Test.** `test_two_names_that_are_not_utf8_never_show_the_same` (unit) and `test_the_delete_listing_names_two_such_names_apart` (a real repository: `len(set(paths)) == 2`).

### F5 (Low): the detail calls a name with U+FFFD "not UTF-8"

**What, where.** `core/pipeline.py` `folder_not_utf8`. Measured on head: `The folder of payments-dev holds …/caf�.yaml, whose
name is not UTF-8`. U+FFFD is valid UTF-8, so the detail states the rule wrongly for that name. RFC 9457 §3.1.4 says the
detail "ought to focus on helping the client correct the problem".

**Fix.** Say "is not UTF-8 or holds U+FFFD" when a path holds one. The problem page names both cases, and its entry keeps its
five lines, so `problem_docs.py:61-62`, which docs/14 cites, does not move.

```diff
--- a/cmapi/src/cmapi/core/pipeline.py
+++ b/cmapi/src/cmapi/core/pipeline.py
@@ -25,7 +25,7 @@
 from cmapi.core.db.repo import JobRepo, RequestRepo, fingerprint, requirement_to_json
 from cmapi.core.errors import Problem
 from cmapi.core.etag import if_match_tags
-from cmapi.core.git.base import GitUnavailable, HostGitProvider, NotUtf8
+from cmapi.core.git.base import REPLACEMENT, GitUnavailable, HostGitProvider, NotUtf8
 from cmapi.core.identity.checks import Requester, resolve_requester
 from cmapi.core.identity.claims import Identity, label_value_of
 from cmapi.core.identity.directory import CachedDirectory
@@ -554,7 +554,9 @@
     resolve in Git and then send again (RFC 9110, section 15.5.10), as folder-holds-submodule is. Nothing is planned."""
     shown = ", ".join(exc.paths[:3]) + (f" and {len(exc.paths) - 3} more" if len(exc.paths) > 3 else "")
     action = "Rename it" if exc.part == "name" else "Write it again as UTF-8"
-    return Problem.conflict("folder-not-utf8", f"The folder of {ns} holds {shown}, whose {exc.part} is not UTF-8: cmapi carries a "
+    # U+FFFD is valid UTF-8: a REST host's stand-in for a lost byte, or typed on purpose. Either way no plan can carry it.
+    rule = "is not UTF-8 or holds U+FFFD" if any(REPLACEMENT in p for p in exc.paths) else "is not UTF-8"
+    return Problem.conflict("folder-not-utf8", f"The folder of {ns} holds {shown}, whose {exc.part} {rule}: cmapi carries a "
                                                f"folder's names and manifests as UTF-8 text. {action} in Git, then send the request "
                                                "again", paths=exc.paths)
 
```
```diff
--- a/cmapi/src/cmapi/core/problem_docs.py
+++ b/cmapi/src/cmapi/core/problem_docs.py
@@ -32,9 +32,9 @@
                               "outside the folder.",
     "folder-not-utf8": "Rename each file that `paths` lists to a name in UTF-8, or write its text again as UTF-8, in the namespace's "
                        "folder in Git, then send the request again. Git keeps a file name as bytes, and cmapi carries names and "
-                       "manifests as UTF-8 text. `paths` shows each byte that is not UTF-8 as `\\xNN`, as in `caf\\xe9.yaml`; "
-                       "a name with U+FFFD is the one a Git host's API gave for such a byte. `git ls-tree` shows the same "
-                       "name quoted, with each byte in octal (`caf\\351.yaml`).",
+                       "manifests as UTF-8 text. `paths` shows each byte that is not UTF-8 as `\\xNN` (`caf\\xe9.yaml`), and in such "
+                       "a name a backslash as `\\\\`. A name with U+FFFD, which a Git host's API gives for such a byte, is refused too. "
+                       "`git ls-tree` shows the same name quoted, with each byte in octal (`caf\\351.yaml`).",
     "idempotency-replay": "Send a new `Idempotency-Key` for a new request. A key belongs to one request body.",
     "precondition-failed": "For a read, send it again without `If-Match` or `If-Unmodified-Since`. For a change, read the object again, and send the change with the new `ETag` in `If-Match`.",
     "validation-failed": "Correct the fields that `errors` names, and send the request again.",
```

**Test.** `test_the_detail_names_the_rule_a_name_with_u_fffd_breaks`.

### F6 (Low; also present before this PR for `folder-holds-submodule`): the examples leave out `paths`

**What, where.** `core/docs.py` `PROBLEM_EXTRAS`, documented as "The fields beyond `detail` that a problem carries where cmapi
raises it, so its example shows them too". Both folder refusals carry `paths` (`pipeline.py`), and neither example showed it.
Measured on head: `problem_example("folder-not-utf8")["paths"]` raises `KeyError`.

**Fix.** Add both entries, then regenerate the contract with `cmapi-tools openapi render --metadata-keys
examples/cluster-configs/policies/metadata-keys.yaml --out cmapi/contract/openapi.json`. First I checked that rendering head
reproduces head's committed contract byte for byte (`cmp`: identical). The regenerated contract adds `paths` to 8 examples
(+24 lines).
- The portal's `schema.generated.ts` holds descriptions, not examples (checked: no example detail text appears in it), so it
  does not change.
- `docs.py` gains two lines above the "Requires" block that docs/14 cites, so the citation moves from 306-311 to 308-313, in
  `docs/14-authorization.md` and `docs/citations.lock.json`.

```diff
--- a/cmapi/src/cmapi/core/docs.py
+++ b/cmapi/src/cmapi/core/docs.py
@@ -170,6 +170,8 @@
     "idp-unavailable": {"retryAfter": 30},
     "cluster-unreachable": {"retryAfter": 30},
     "validator-unavailable": {"retryAfter": 60},
+    "folder-holds-submodule": {"paths": ["clusters/CRC/namespaces/payments-dev/vendor"]},
+    "folder-not-utf8": {"paths": ["clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"]},
 }
 
 
```
```diff
--- a/cmapi/contract/openapi.json
+++ b/cmapi/contract/openapi.json
@@ -10251,6 +10251,9 @@
                     "value": {
                       "code": "folder-not-utf8",
                       "detail": "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml, whose name is not UTF-8: cmapi carries a folder's names and manifests as UTF-8 text. Rename it in Git, then send the request again",
+                      "paths": [
+                        "clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"
+                      ],
                       "status": 409,
                       "title": "folder not utf8",
                       "type": "https://cmapi.ephico2real.com/problems/folder-not-utf8"
@@ -10904,6 +10907,9 @@
                     "value": {
                       "code": "folder-holds-submodule",
                       "detail": "The folder of payments-dev holds the submodule clusters/CRC/namespaces/payments-dev/vendor",
+                      "paths": [
+                        "clusters/CRC/namespaces/payments-dev/vendor"
+                      ],
                       "status": 409,
                       "title": "folder holds submodule",
                       "type": "https://cmapi.ephico2real.com/problems/folder-holds-submodule"
@@ -10913,6 +10919,9 @@
                     "value": {
                       "code": "folder-not-utf8",
                       "detail": "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml, whose name is not UTF-8: cmapi carries a folder's names and manifests as UTF-8 text. Rename it in Git, then send the request again",
+                      "paths": [
+                        "clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"
+                      ],
                       "status": 409,
                       "title": "folder not utf8",
                       "type": "https://cmapi.ephico2real.com/problems/folder-not-utf8"
@@ -11383,6 +11392,9 @@
                     "value": {
                       "code": "folder-not-utf8",
                       "detail": "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml, whose name is not UTF-8: cmapi carries a folder's names and manifests as UTF-8 text. Rename it in Git, then send the request again",
+                      "paths": [
+                        "clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"
+                      ],
                       "status": 409,
                       "title": "folder not utf8",
                       "type": "https://cmapi.ephico2real.com/problems/folder-not-utf8"
@@ -11890,6 +11902,9 @@
                     "value": {
                       "code": "folder-not-utf8",
                       "detail": "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml, whose name is not UTF-8: cmapi carries a folder's names and manifests as UTF-8 text. Rename it in Git, then send the request again",
+                      "paths": [
+                        "clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"
+                      ],
                       "status": 409,
                       "title": "folder not utf8",
                       "type": "https://cmapi.ephico2real.com/problems/folder-not-utf8"
@@ -12553,6 +12568,9 @@
                     "value": {
                       "code": "folder-not-utf8",
                       "detail": "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml, whose name is not UTF-8: cmapi carries a folder's names and manifests as UTF-8 text. Rename it in Git, then send the request again",
+                      "paths": [
+                        "clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"
+                      ],
                       "status": 409,
                       "title": "folder not utf8",
                       "type": "https://cmapi.ephico2real.com/problems/folder-not-utf8"
@@ -13215,6 +13233,9 @@
                     "value": {
                       "code": "folder-not-utf8",
                       "detail": "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml, whose name is not UTF-8: cmapi carries a folder's names and manifests as UTF-8 text. Rename it in Git, then send the request again",
+                      "paths": [
+                        "clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"
+                      ],
                       "status": 409,
                       "title": "folder not utf8",
                       "type": "https://cmapi.ephico2real.com/problems/folder-not-utf8"
@@ -13836,6 +13857,9 @@
                     "value": {
                       "code": "folder-not-utf8",
                       "detail": "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml, whose name is not UTF-8: cmapi carries a folder's names and manifests as UTF-8 text. Rename it in Git, then send the request again",
+                      "paths": [
+                        "clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"
+                      ],
                       "status": 409,
                       "title": "folder not utf8",
                       "type": "https://cmapi.ephico2real.com/problems/folder-not-utf8"
```
```diff
--- a/docs/14-authorization.md
+++ b/docs/14-authorization.md
@@ -81,7 +81,7 @@
 
 ### Which route needs which permission
 
-Each route declares one permission. The OpenAPI document shows it as `x-cmapi-permission`, and the description of the route ends with a "Requires" line (`cmapi/src/cmapi/core/docs.py:306-311`). A `HEAD` is answered by the route of its `GET`, so it needs the same permission and gets the same 401 or 403 (#605).
+Each route declares one permission. The OpenAPI document shows it as `x-cmapi-permission`, and the description of the route ends with a "Requires" line (`cmapi/src/cmapi/core/docs.py:308-313`). A `HEAD` is answered by the route of its `GET`, so it needs the same permission and gets the same 401 or 403 (#605).
 
 | Permission | Routes |
 |---|---|
```
```diff
--- a/docs/citations.lock.json
+++ b/docs/citations.lock.json
@@ -338,7 +338,7 @@
   "        return None",
   "    return Requirement(rule=d[\"rule\"], slots=tuple(Slot(**s) for s in d[\"slots\"]), self_approval=d[\"selfApproval\"],"
  ],
- "docs/14-authorization.md|cmapi/src/cmapi/core/docs.py|306-311": [
+ "docs/14-authorization.md|cmapi/src/cmapi/core/docs.py|308-313": [
   "            if permission:",
   "                desc += f\"\\n\\n**Requires** `{permission}`.\"",
   "            op_id = f\"{self.plugin}_{fn.__name__}\"",
```

**Test.** `test_the_example_of_a_folder_refusal_shows_its_paths[folder-not-utf8|folder-holds-submodule]`, plus the contract and citation suites (`test_api_contract`, `test_doc_citations`).

### F7 (Low): `watch_sync` compares main's folder outside the `as_plan` rule

**What, where.** `jobs/watch_sync.py:89,121`. A name on main after the merge gives 5 errors, then the same `sync_failed`
that `_refuse` gives at once. The outcome is right, but the path to it is noisy.

**Fix.** Use `as_plan`, the merge check's rule.

```diff
--- a/cmapi/src/cmapi/jobs/watch_sync.py
+++ b/cmapi/src/cmapi/jobs/watch_sync.py
@@ -13,7 +13,7 @@
 from cmapi.core.db.models import JobRow
 from cmapi.core.db.repo import JobRepo, RequestRepo
 from cmapi.core.errors import Problem
-from cmapi.core.git.base import GitUnavailable
+from cmapi.core.git.base import GitUnavailable, as_plan
 from cmapi.core.lifecycle import Event as E, State as S
 from cmapi.core.observability import LEAD_TIME, log
 from cmapi.core.render.manifests import folder
@@ -86,8 +86,8 @@
         return
     try:
         if mode == "apply":
-            on_main, _ = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
-            if on_main != files:
+            # A folder that holds a name or text that is not UTF-8 is never the plan's: as_plan reads it as False (#626).
+            if not as_plan(lambda: ctx.git.read_folder(folder(row.cluster_id, row.namespace))[0] == files):
                 return _refuse(repo, jobs, row, job, "Git main's folder differs from the approved plan; nothing applied")
             d = ApplyDelivery(_deliverer(ctx, row.cluster_id))
             live = d.client.get_object("Namespace", None, row.namespace)
@@ -118,8 +118,7 @@
             # change to the folder is a new request, not this one), Argo CD has compared a revision at or after the
             # merge (status.sync.revision is the head of main, so a later merge moves it), and this folder's own objects
             # are Synced (the Application's status covers every namespace, so a neighbour's pending prune says nothing).
-            on_main, _ = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
-            if on_main != files:
+            if not as_plan(lambda: ctx.git.read_folder(folder(row.cluster_id, row.namespace))[0] == files):
                 return _refuse(repo, jobs, row, job, "Git main's folder differs from the approved plan")
             st = ctx.registry.get(row.cluster_id)
             reader = st.client                  # once: `_set` or the relist may clear it between a check and a use (#402)
```

**Test.** `test_watch_sync_reads_a_folder_it_cannot_name_as_not_the_plans`: `sync_failed`, no errors.

### The records

The README's section "What is not handled specially" was false for `pr_checks` and `_merged`. It is rewritten to name what
the review changed and what stays on the retry path, and why. docs/02 gains one sentence.

```diff
--- a/docs/reviews/2026-11-24-issue-626/README.md
+++ b/docs/reviews/2026-11-24-issue-626/README.md
@@ -143,10 +143,19 @@
 bytes that are not UTF-8. Git shows the same name as `"caf\351.yaml"` with its default `core.quotePath`; the problem page
 says so, so a person can match the two.
 
-## What is not handled specially
+## The reads after the plan (reviewer 1's findings F1, F2, F3, F7)
 
-These jobs read the folder after a merge or for a sync: `pr_checks` (the base it validates against, and a delete's empty
-head), `merge`'s `_merged`, `watch_sync` and `open_revert`. Where the folder holds such a name, they raise `NotUtf8`. The worker
-then retries and fails the request, as it does for any error, with the message `NotUtf8: the name of <path> is not UTF-8`
-instead of a codec error. The merge check, which runs before every merge in `pr_checks` and `merge`, reads such a folder as
-not the plan's, so the usual path is superseded or `merge_failed` before these reads.
+- `pr_checks` reads main's folder for the validators before it runs the merge check, so such a name there supersedes the
+  request, as the merge check would (F2).
+- `merge`'s `_merged` reads the folder at the merge sha after the host merged: such a folder is not the plan's, so the request
+  is merged and then `sync_failed`, with the path in the note (F1). Before, it was five errors and then `pr_failed`, with the PR
+  merged on the host.
+- `watch_sync` compares main's folder with the plan through `as_plan`, as the merge check does (F7).
+- The Gitea stand-in deletes the branch it just made when its read of the folder fails, and `push_branch` supersedes on a
+  `NotUtf8` from the push itself (F3).
+
+Still the worker's retry, then failure, as for any error, with `NotUtf8: the name of <path> is not UTF-8` in the note: the
+reads of a PR head that a person pushed to (`pr_checks`' tree and a delete's head, `apply`'s tree; the request ends
+`pr_failed`, or `sync_failed` once an apply started, as a failed check would), the retry of a `sync_failed` delete
+(`prune`), and `open_revert`. Each is bounded by the five attempts, and none leaves a lock held without a state that offers
+`:retry` or `:revert`.
```
```diff
--- a/docs/02-technical-design-v2.md
+++ b/docs/02-technical-design-v2.md
@@ -998,7 +998,7 @@
 
 **A delete removes the whole folder (#616).** The plan lists every file of the namespace's folder at any depth, whatever made it: cmapi's manifests, a README, a `.yml` or `.json` manifest, a subfolder (`GitProvider.list_folder`: `git ls-tree -r` in the Git layer, the Git Trees API on GitHub, each subtree on Gitea). Each path is shown as removed in the plan and the dry run, so the approvers see it before anything reaches Git, and the branch removes each one. The root Application syncs the namespaces folder with `directory.recurse: true` and reads `.yaml`, `.yml` and `.json` files, so a manifest left in a subfolder would stay in its desired state after the Namespace is pruned. A path that the folder gains or loses after the plan, or a file that becomes a submodule, supersedes the delete at push_branch, and again at the merge check before the merge: main's full listing must be the plan's removals, and the merged result must hold nothing of the folder. The check after the merge, an empty folder at the merge sha, is for a path that lands during the host's own merge; it leaves the delete sync_failed, and its :retry reads the folder on main before the cluster, so it confirms only an empty folder. The revert of a delete restores cmapi's manifests and names each other path it does not restore, with the commit that holds it (`revert_partial`). A submodule is refused with 409 folder-holds-submodule: its removal also changes `.gitmodules`, outside the folder. The other reads of a folder (the ETag, the plan's base, the renderer's previous files) stay the `.yaml` files directly in it (#578). The decision record is docs/reviews/2026-11-23-issue-616/README.md.
 
-**A name or a manifest that is not UTF-8 (#626).** Git keeps a file name as bytes, and a plan, the API's JSON and the database hold text, so cmapi carries a folder's names and manifests only as UTF-8. A REST host loses such a byte: GitHub's git/trees and Contents answered `caf\xe9.yaml` as `caf\ufffd.yaml`, U+FFFD in its place (measured 2026-11-24), and Gitea's JSON encoder writes the same, so a name that holds U+FFFD is treated as one that is not UTF-8 on every provider. A write or a read of the namespace whose folder holds such a manifest, a delete whose folder holds such a path at any depth, or a manifest whose text is not UTF-8, is 409 folder-not-utf8 with each path in `paths`, each byte that is not UTF-8 shown as `\xNN`, and nothing is planned. A name a change never reads (a subfolder's, a README's) does not refuse it. Such a path that reaches the folder after the plan supersedes the request at push_branch, and the merge check reads such a folder as not the plan's. The decision record is docs/reviews/2026-11-24-issue-626/README.md.
+**A name or a manifest that is not UTF-8 (#626).** Git keeps a file name as bytes, and a plan, the API's JSON and the database hold text, so cmapi carries a folder's names and manifests only as UTF-8. A REST host loses such a byte: GitHub's git/trees and Contents answered `caf\xe9.yaml` as `caf\ufffd.yaml`, U+FFFD in its place (measured 2026-11-24), and Gitea's JSON encoder writes the same, so a name that holds U+FFFD is treated as one that is not UTF-8 on every provider. A write or a read of the namespace whose folder holds such a manifest, a delete whose folder holds such a path at any depth, or a manifest whose text is not UTF-8, is 409 folder-not-utf8 with each path in `paths`, each byte that is not UTF-8 shown as `\xNN`, and nothing is planned. A name a change never reads (a subfolder's, a README's) does not refuse it. Such a path that reaches the folder after the plan supersedes the request at push_branch or at pr_checks, the merge check reads such a folder as not the plan's, and a merge whose folder holds one is merged and then sync_failed. In `paths` a backslash of such a name is doubled, so no two names show the same. The decision record is docs/reviews/2026-11-24-issue-626/README.md.
 
 If your cluster-configs repo keeps the existing segment/mnemonic/clusterEnv layout, the renderer maps clusterId to that path instead; the registry's gitopsPath is the only place the mapping lives.
 
```

**Test.** Documentation only, so no test. `test_doc_citations` still passes.

## Regression check (adjacent suites on the fix)

I ran 13 files on `work/fix` (`r1-outputs/adjacent-on-fix.log`): `test_gitea_review`, `test_delete_whole_folder_616`,
`test_git_layer`, `test_api_contract`, `test_api_standard`, `test_api_samples`, `test_api_docs`, `test_doc_citations`,
`test_github_read_folder_632`, `test_review_288_f7`, `test_delivery_states_review`, `test_delivery_states_db_review` and
`test_git_workspace_review`. Result: **380 passed, 1 failed.**

The one failure, `test_doc_citations::test_each_citation_of_the_documents_is_the_text_that_was_recorded_for_it`, comes from
the export, not from the fix:
- The script runs `git ls-files`, and the export has no `.git`.
- The same test fails on unchanged head (`citations-on-head.log`, run with `--noconftest`, because by then another session
  held the test database's advisory lock).
- Run with a file-system listing in place of `git ls-files` (`r1-outputs/citations_check.py`), the citation check gives
  **0 problems on head and 0 on the fix**. So the moved `docs.py:308-313` citation is right.
- **CI, which has `.git`, is the check that decides this test.**

The PR's own 17 tests and the review's 11 pass together on the fix: 28 passed (`review-on-fix.log`).

## Appendix: the review's test file

```diff
--- a/cmapi/tests/service/test_non_utf8_review_647.py
+++ b/cmapi/tests/service/test_non_utf8_review_647.py
@@ -0,0 +1,197 @@
+"""PR #647 (#626), reviewer 1: the reads that #626 left on the worker's retry-then-fail path, and the shown names.
+
+Each test fails on the PR's head and passes with the review's fix:
+- F1: _merged read the folder at the merge sha, so a name that landed during the host's merge raised NotUtf8 after the merge,
+  five times, and the merged request ended pr_failed (argocd) or merge_failed (apply) with its PR merged on the host.
+- F2: pr_checks reads main's folder before the merge check, so a name that landed while the PR was open was five errors and
+  pr_failed, where the merge check would have superseded it.
+- F3: the Gitea stand-in creates the request branch before it reads the folder: a failed read left a branch at main's commit,
+  which git_cleanup keeps as foreign. The push_branch job retried a NotUtf8 from the push itself.
+- F4: backslashreplace alone shows two different names the same: b"a\\xe9\\\\xff" and b"a\\\\xe9\\xff" are both "a\\xe9\\xff".
+- F5: the detail said "is not UTF-8" of a name that is UTF-8 and holds U+FFFD.
+- F6: the contract's examples of folder-not-utf8 and folder-holds-submodule had no `paths`, the member each one carries.
+- F7: watch_sync read main's folder outside the merge check's rule: five errors before the sync_failed it ends in anyway.
+"""
+from __future__ import annotations
+
+from dataclasses import replace
+from datetime import datetime, timezone
+
+import httpx
+import pytest
+
+from cmapi.core.docs import problem_example
+from cmapi.core.git.base import BranchRequest, NotUtf8, git_name
+from cmapi.core.git.workspace import GitWorkspace
+from cmapi.core.pipeline import folder_not_utf8
+from gitserver import bare_repo
+from test_delete_whole_folder_616 import HEAD, RestHost, _gitea
+from test_git_layer import argocd, drive, layer  # noqa: F401  (layer is the real Git layer's fixture)
+from test_non_utf8_names_626 import BASE, LATIN1, LOST, MANIFEST, NAMESPACE, SHOWN, commit_bytes
+
+BAD = BASE.encode() + LATIN1
+
+
+def _notes(view) -> list[tuple[str, str]]:
+    return [(e["event"], e["note"] or "") for e in view["events"]]
+
+
+def _errors(view) -> list[str]:
+    return [note for event, note in _notes(view) if event == "error"]
+
+
+def _until(w, rid: str, status: str, limit: int = 20) -> None:
+    """Run the worker one job at a time until the request reaches status."""
+    for _ in range(limit):
+        if w.view(rid)["status"] == status:
+            return
+        assert drive(w.ctx, limit=1), f"no job left before {status}: {_notes(w.view(rid))}"
+    raise AssertionError(f"never reached {status}: {_notes(w.view(rid))}")
+
+
+def _mode(w, mode: str) -> None:
+    if mode == "argocd":
+        argocd(w)
+    else:
+        w.ctx.delivery = replace(w.ctx.delivery, mode="apply")
+
+
+# --------------------------------------------------------------------------- F1: after the merge
+
+@pytest.mark.parametrize("mode", ["argocd", "apply"])
+def test_a_name_that_lands_during_the_hosts_merge_leaves_the_request_merged_then_sync_failed(layer, mode):  # noqa: F811
+    """The host merged: the request must say so. Merged, then sync_failed with the lock held for an operator (_merged's own
+    rule for a folder at the merge that is not the plan's), never five errors and then pr_failed or merge_failed."""
+    w = layer
+    _mode(w, mode)
+    rid = w.create()
+    w.host.merge_hook = lambda number: commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})
+
+    drive(w.ctx)
+
+    v = w.view(rid)
+    assert w.host.prs[1]["merged"], "the host merged the PR"
+    assert v["status"] == "sync_failed", _notes(v)
+    assert not _errors(v), _notes(v)
+    assert any(SHOWN in note for _, note in _notes(v)), "the operator is told which path"
+
+
+# --------------------------------------------------------------------------- F2: while the PR is open
+
+def test_a_name_that_lands_on_main_while_the_pr_is_open_supersedes_it(layer):  # noqa: F811
+    w = layer
+    argocd(w)
+    rid = w.create()
+    _until(w, rid, "pr_open")
+    commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})
+
+    drive(w.ctx)
+
+    v = w.view(rid)
+    assert v["status"] == "superseded", _notes(v)
+    assert not _errors(v), _notes(v)
+    assert any(SHOWN in note for _, note in _notes(v))
+    assert w.host.prs[1]["state"] == "closed" and not w.host.prs[1]["merged"]
+
+
+# --------------------------------------------------------------------------- F7: after the merge, waiting for the sync
+
+def test_watch_sync_reads_a_folder_it_cannot_name_as_not_the_plans(layer):  # noqa: F811
+    w = layer
+    argocd(w)
+    rid = w.create()
+    _until(w, rid, "merged")
+    commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})
+
+    drive(w.ctx)
+
+    v = w.view(rid)
+    assert v["status"] == "sync_failed", _notes(v)
+    assert not _errors(v), _notes(v)
+
+
+# --------------------------------------------------------------------------- F3: the push itself
+
+def test_a_name_the_push_finds_supersedes_the_request(layer, monkeypatch):  # noqa: F811
+    """The Gitea stand-in reads the folder as it writes the branch: a name that landed after push_branch's own read."""
+    w = layer
+    argocd(w)
+
+    def found(req):
+        raise NotUtf8([SHOWN], "name")
+
+    monkeypatch.setattr(w.ctx.git, "push_request_branch", found)
+    rid = w.create()
+
+    drive(w.ctx)
+
+    v = w.view(rid)
+    assert v["status"] == "superseded", _notes(v)
+    assert not _errors(v), _notes(v)
+    assert any(SHOWN in note for _, note in _notes(v))
+
+
+class _Branching(RestHost):
+    """RestHost, where the request branch, once created, is main's commit as Gitea makes it, and can be deleted."""
+
+    BRANCH = "/branches/cmapi/CRC/req-1"
+
+    def __call__(self, request: httpx.Request) -> httpx.Response:
+        path = request.url.path.removeprefix("/api/v1").removeprefix("/repos/o/r")
+        if request.method == "GET" and path == self.BRANCH and self.branch_exists:
+            self.calls.append(("GET", path, {}))
+            return httpx.Response(200, json={"commit": {"id": HEAD}})
+        if request.method == "DELETE" and path == self.BRANCH:
+            self.calls.append(("DELETE", path, {}))
+            self.branch_exists = False
+            return httpx.Response(204)
+        return super().__call__(request)
+
+
+def test_the_gitea_stand_in_leaves_no_branch_when_it_cannot_read_the_folder():
+    host = _Branching({**MANIFEST, LOST: ("blob", "100644")})
+    path = next(iter(MANIFEST))
+    req = BranchRequest("CRC", "req-1", BASE, "hash", "update\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
+                        {path: "changed\n"}, {path: f"text of {path}\n"}, datetime(2026, 1, 1, tzinfo=timezone.utc))
+
+    with pytest.raises(NotUtf8):
+        _gitea(host).push_request_branch(req)
+
+    assert ("POST", "/branches", {}) in host.calls
+    assert not host.branch_exists, "the branch made for this push is gone"
+
+
+# --------------------------------------------------------------------------- F4: what `paths` shows
+
+def test_two_names_that_are_not_utf8_never_show_the_same():
+    one, two = b"a\xe9\\xff.yaml", b"a\\xe9\xff.yaml"
+    assert git_name(one) == ("a\\xe9\\\\xff.yaml", False)
+    assert git_name(two) == ("a\\\\xe9\\xff.yaml", False)
+    assert git_name(b"caf\xe9.yaml") == ("caf\\xe9.yaml", False), "a name with no backslash shows as before"
+
+
+def test_the_delete_listing_names_two_such_names_apart(tmp_path):
+    bare = bare_repo(tmp_path, {f"{BASE}namespace.yaml": NAMESPACE})
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
+    try:
+        commit_bytes(bare, tmp_path, {BASE.encode() + b"a\xe9\\xff.txt": b"1\n", BASE.encode() + b"a\\xe9\xff.txt": b"2\n"})
+        with pytest.raises(NotUtf8) as caught:
+            ws.list_folder(BASE)
+        assert len(set(caught.value.paths)) == 2, caught.value.paths
+    finally:
+        ws.dispose()
+
+
+# --------------------------------------------------------------------------- F5, F6: the problem
+
+def test_the_detail_names_the_rule_a_name_with_u_fffd_breaks():
+    lost = folder_not_utf8("payments-dev", NotUtf8([LOST], "name")).body()
+    plain = folder_not_utf8("payments-dev", NotUtf8([SHOWN], "name")).body()
+    assert "is not UTF-8 or holds U+FFFD" in lost["detail"], lost["detail"]
+    assert "U+FFFD" not in plain["detail"] and "is not UTF-8" in plain["detail"]
+
+
+@pytest.mark.parametrize("code", ["folder-not-utf8", "folder-holds-submodule"])
+def test_the_example_of_a_folder_refusal_shows_its_paths(code):
+    example = problem_example(code)
+    assert example["paths"] and all(p in example["detail"] for p in example["paths"]), example
```

## What was measured, what was inferred, what was not tested

- **Measured:**
  - every test result;
  - every mutant;
  - the end states on head (`head-states-probe.txt`, a scratch probe not shipped);
  - the escape collision;
  - the tree object IDs of the GitHub probe;
  - the base run;
  - the deterministic contract render;
  - that the patch applies with `-F0` to a fresh copy of head.
- **Read from source, not measured:**
  - Gitea's U+FFFD (json-iterator);
  - that only a person's push can put such a name on the bot's branch (F7's "leave as is" rows);
  - that no outcome depends on the collision between an escaped name and a valid plan path (claim 7).
- **Not tested:**
  - a running Gitea;
  - GitHub after this fix (the API process path is covered by the REST stand-ins);
  - CRC or any cluster;
  - the whole service suite (not run, per the brief);
  - the portal build (`schema.generated.ts` does not change).
- **Codex's leads** that I checked and kept: F3, F4, F5, F6, and the `_merged` and `pr_checks` paths behind F1 and F2. Every
  one was re-derived and re-measured here.
- **Codex's leads I did not take:**
  - its `diff_names` change, which would make `changed_paths` raise. It is not needed, because no outcome depends on the
    collision (claim 7).
  - its Gitea reorder, which breaks `test_gitea_review`.
  - its "gate reports the snapshot it read" timing point in `HostGitProvider.merge_check`. When `read_folder` raises, the check
    reads `_folder_head(None)` again, so the `main_sha` it reports can be newer than the read that failed. That sha only goes
    into the refusal's note, and the refusal is right either way, so it changes no outcome. I did not file it.
