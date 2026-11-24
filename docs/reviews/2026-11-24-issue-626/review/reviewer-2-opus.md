# PR #647 (closes #626): reviewer 2 (Opus 5.5 at high)

Reviewer 2 of PR #647. I did not write the change or reviewer 1's review. Reviewer 1 was a separate Opus 5.5 agent standing in
for Codex, which hit its usage limit (`codex-result.txt`). With Codex out, the PR had no reviewer from another model family:
both reviewers are Opus.

- **Export.** `review-647/head/` is the PR head; `r2/` is head with reviewer 1's `fix.diff` applied (`patch -p1 -F0`: clean).
  `r2-outputs/work/final/` is my final tree.
- **Patch.** `r2-outputs/fix.diff` is one patch against `head/`, built from `cmapi/` and `docs/` only (16 files, 719 lines). On
  a fresh copy of `head/` (without the portal), `patch -p1 -F0` applied it with no offset or fuzz. The result was identical
  to `work/final` (`diff -rq` on `cmapi/` and `docs/`).
- **Tests.** Each ran on macOS against PostgreSQL 16 at `127.0.0.1:55432/cmapi_wt605`, with the brief's command
  (`r2-outputs/run.sh`, wrapped by `queue.sh`, which waits while another session holds the advisory lock). No cluster, Git
  repository or GitHub was touched. The whole service suite was not run.

## Summary

| # | Reviewer 1 | My ruling | What changed from reviewer 1's patch |
|---|---|---|---|
| F1 | Medium: `_merged` fails a merged request | **Upheld.** Merged, then `sync_failed` with the path, is #449's documented outcome. Argo CD acts on such a main. | Narrowed: the original two lines are kept inside the `try`. The comment names the real end states (`failed`, `merge_failed`). |
| F2 | Medium: `pr_checks`' base read | **Upheld.** Superseding is the merge check's own outcome. | None. |
| F3 | Low: Gitea leaves a branch; push retries `NotUtf8` | **Upheld; R1's Gitea fix replaced.** Its delete cannot remove a commit main lacks, except in the GET-then-DELETE race Gitea already accepts. Its comment "git_reconcile sweeps the branch" is false. | Gitea reads the folder at main's commit **before** it creates the branch. No try, no delete, no swallowed error. `push_branch` kept as R1 wrote it. |
| F4 | Low: the `\xNN` escape is not one-to-one | **Upheld, but R1's fix is incomplete.** It is not unambiguous both ways. A name with U+FFFD, and a text-failure path, were still shown verbatim. Measured: two files in one real repository showed as one path. | `shown()` for every path of `NotUtf8` (the Git layer, REST, manifest text). `path_text` and the `changed_paths`/`_adoptable` hunks dropped. |
| F5 | Low: "is not UTF-8" for a U+FFFD name | **Upheld, and widened to the note.** `NotUtf8`'s own message, written in the request's events, had the same error. | The rule lives once, on `NotUtf8.rule`, and `pipeline.py` uses it. Net one line changed in `pipeline.py`. |
| F6 | Low: the examples lack `paths` | **Upheld.** The contract renders byte-exact. The only change is 8 `paths` members. oasdiff: no breaking change. | None. |
| F7 | Low: `watch_sync` outside `as_plan` | **Upheld.** | A test for the apply-mode line, which R1 changed but no test covered. |

Measured on the final tree:
- **Before** (head with the final tests, `before-final-tests.log`): all 19 review tests fail.
- **After** (`after-final-tests.log`): 438 passed, 0 failed, across 16 files: the review file, the PR's file, and 14
  adjacent suites.
- **Mutants:** 13 of 13 killed (`mutants/summary.txt`).

## Research: the sources

Each source reviewer 1 relied on was checked against a copy I fetched myself on 2026-11-24 at 14:08 UTC
(`r2-outputs/sources/fetched-at.txt`). `core.adoc`, `rfc9110.txt` and `rfc9457.txt` are **byte-identical** to reviewer 1's
saved copies (`cmp`).

- **git `core.quotePath`** (<https://raw.githubusercontent.com/git/git/master/Documentation/config/core.adoc>, lines 159-172):
  "…escaping those characters with backslashes in the same way C escapes control characters (e.g. `\t` for TAB, `\n` for
  LF, `\\` for backslash) or bytes with values larger than 0x80 (e.g. octal `\302\265` for "micro" in UTF-8). If this
  variable is set to false, bytes higher than 0x80 are not considered "unusual" any more. **Double-quotes, backslash and
  control characters are always escaped regardless of the setting of this variable.**" Confirmed in the code as well:
  `quote.c` (<https://raw.githubusercontent.com/git/git/master/quote.c>), `cq_lookup[256]`, row `0x58`: `-1, -1, -1,
  -1,'\\', -1, -1, -1`. Byte 0x5C is always quoted as `\\`.
- **RFC 9110 §15.5.10** (<https://www.rfc-editor.org/rfc/rfc9110.txt>, line 7650): "The 409 (Conflict) status code indicates
  that the request could not be completed due to a conflict with the current state of the target resource. This code is
  used in situations where the user might be able to resolve the conflict and resubmit the request. The server SHOULD
  generate content that includes enough information for a user to recognize the source of the conflict." Matches reviewer
  1's quote word for word.
- **RFC 9457 §3** (<https://www.rfc-editor.org/rfc/rfc9457.txt>):
  - §3.1.4: "The "detail" string, if present, ought to focus on helping the client correct the problem, rather than giving
    debugging information. Consumers SHOULD NOT parse the "detail" member for information; extensions are more suitable and
    less error-prone ways to obtain such information."
  - §3.2: "Problem type definitions MAY extend the problem details object with additional members that are specific to that
    problem type."
  - Both match. They are why `paths` must decode without ambiguity: it is the member a client is told to read instead of
    `detail`.
- **Python `codecs`** (<https://raw.githubusercontent.com/python/cpython/main/Doc/library/codecs.rst>, line 375):
  `'backslashreplace'`: "Replace with backslashed escape sequences. … On decoding, use hexadecimal form of byte value with
  format `\xhh`." It escapes only the undecodable bytes. A backslash already in the input is left as it is, which is the
  root of F4.
- **Argo CD, directory applications** (<https://raw.githubusercontent.com/argoproj/argo-cd/master/docs/user-guide/directory.md>):
  "A directory-type application loads plain manifest files from `.yml`, `.yaml`, and `.json` files." cmapi's root
  Application (`examples/cluster-configs/clusters/OCP_GF15/argocd/root-application.yaml`) has `directory.recurse: true` and
  automated sync with `prune: true` and `selfHeal: true`.
- **Argo CD, how a manifest is read** (<https://raw.githubusercontent.com/argoproj/argo-cd/master/reposerver/repository/repository.go>,
  `getObjsFromYAMLOrJSON`): `reader, err := utfutil.OpenFile(manifestPath, utfutil.UTF8)`. utfutil
  (<https://raw.githubusercontent.com/TomOnTime/utfutil/master/utfutil.go>, line 181) then uses
  `decoder = unicode.UTF8.NewDecoder()`. golang.org/x/text
  (<https://raw.githubusercontent.com/golang/text/master/encoding/unicode/unicode.go>, `utf8Decoder.Transform`,
  `handleInvalid`) says: "// Append RuneError to the destination." So Argo CD reads a manifest's text that is not UTF-8
  with U+FFFD in place of each bad byte, and does not fail. **Read from source, not measured on a running Argo CD.**

**Retracted, in so many words:**
1. **Reviewer 1, F3:** "Reading the folder at `base` before creating the branch … breaks the existing Gitea stand-in tests".
   I retract this; the measurement refutes it. With that reorder, `test_gitea_review.py` passed 7 of 7 on the **unchanged**
   stub. It passed by a coincidence of the stub: `MAIN = "1" * 40` is also the ID the stub gives its `namespaces` subtree.
   With the stub corrected so that cannot happen, it passed 7 of 7 again. The failure reviewer 1 cited was Codex's run of a
   different change, and reviewer 1 did not re-measure it.
2. **Reviewer 1's patch comment** "git_reconcile sweeps the branch" (`gitea.py`) is false. `git_reconcile.py` deletes a
   branch only when `head in ours or ctx.git.request_of(head) == rid`. Gitea does not override `request_of`, and the base
   returns `None`. So a branch left at main's commit is kept as `foreign_branch` on every pass.
3. **Reviewer 1, F4:** "That mapping is one-to-one" is true only of the names its `shown()` was applied to. U+FFFD names and
   text-failure paths, which share the same `paths`, were left verbatim (see F4).
4. **Reviewer 1's README text** "five errors and then `pr_failed`": `pr_failed` is the event, and the status measured was
   `failed` (argocd) or `merge_failed` (apply). Corrected in the README, the test docstring and the code comment.

## The baseline

| Run | Result | Log |
|---|---|---|
| Reviewer 1's 11 tests + the PR's 17, on head | 11 failed, 17 passed | `head-r1tests.log` |
| The same, on head + reviewer 1's patch (`r2/`) | 28 passed | `r1fix-r1tests.log` |
| My final review file + the PR's + `test_gitea_review`, on head | the 19 review tests all fail; see the note below | `before-final-tests.log` |
| The non-database review tests on head + reviewer 1's patch (`work/r1-t`) | 6 fail: my F4 additions | shown under F4 |
| 16 files on the final tree | **438 passed** | `after-final-tests.log` |

Each head failure is on the assertion its finding names, not on an import or a fixture. For F1, the "host merged" assertion
passed and the status assertion then failed with `'failed' == 'sync_failed'` (argocd) and `'merge_failed' == 'sync_failed'`
(apply).

**Note on the head run.** In `before-final-tests.log`, two of the PR's own tests also failed on head:
`test_a_change_and_a_delete_…` and `test_a_change_is_not_refused_…`. Each failed at `_etag`, before the folder held
any such name: `KeyError: 'etag'`, with `GET /requests/{id}` answering 404 straight after the create. Run alone on the
same head tree, the PR's file passed 17 of 17 (`before-rerun-626.log`). In the same order on the final tree, all
passed. These were not failures of the #626 code. Their exact cause in the combined head run was **not determined**.
The 404 is the symptom the conftest names for rows truncated by another session, and other sessions were using this
database at the time.

## Rulings

### F1 (Medium): `_merged` after the host merged: upheld, narrowed

**The question.** Once the host has merged, cmapi must not record `failed` or `merge_failed`. Is "merged, then `sync_failed`
with the path" right?

**Evidence:**
- **`jobs/merge.py` `_merged` docstring (#449):** "A merge whose folder is not the plan's, or with no sha to read, is merged
  and then sync_failed, with the lock held for an operator: nothing is applied from it and a delete never waits for a prune
  of it." A folder holding a name or text that no plan holds is not the plan's. So this is the documented outcome, the same
  one an extra file with a valid name would get. `lifecycle.py` already has both transitions: `(PR_OPEN|APPLIED|MERGE_FAILED,
  MERGED) → merged`, then `SYNC_TIMEOUT → sync_failed`.
- **Measured on head:** the host merged (`prs[1].merged` passed). The request then ended `failed` in argocd mode, with the
  lock released and no `merge_sha`. In apply mode it ended `merge_failed`, and every `:retry` repeats `_merged` and fails
  again.
- **What Argo CD does with that main** (sources above, read not measured): it loads every `.yaml` of the folder whatever the
  bytes of its name, and syncs it, with `prune` and `selfHeal`. It reads a text that is not UTF-8 with U+FFFD in place of
  each bad byte. Either way the cluster gets an object or a value the plan never held. So `failed` is false, because main
  holds the change and Argo CD applies it. `synced` is false too. `sync_failed` with the lock held, for an operator, is the
  only true state.

**Narrowed.** Reviewer 1 rewrote the two original lines as `fulfilled = bool(sha) and … == planned(row)`. That is equivalent,
but it needlessly changes their form. The final code keeps the original lines inside the `try`.

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
@@ -138,11 +138,16 @@
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
+        on_main = ctx.git.tree_files(sha, folder(row.cluster_id, row.namespace)) if sha else None
+        fulfilled = on_main == planned(row)
+        if fulfilled and row.action == "delete":
+            # A delete's folder is empty at the merge: no file of any kind, at any depth, is left of it (#616).
+            fulfilled = not ctx.git.list_folder(folder(row.cluster_id, row.namespace), sha)[0]
+    except NotUtf8 as exc:
+        # The merge happened: a folder no plan can hold (#626) is not the plan's. Never retried into failed or merge_failed.
+        fulfilled, unreadable = False, exc
     row.merge_sha = sha or None
     how = "adopted: merged on the host" if adopted else "merged"
     repo.event(row, "merge_verified", "worker", f"{how} {sha[:8]}; the folder at it {'is' if fulfilled else 'is not'} the plan's",
@@ -150,7 +155,7 @@
     repo.move(row, E.MERGED, "cmapi-bot", f"{how} {sha[:8]}")
     if not fulfilled:
         why = f"the folder at the merge {sha[:8]} is not the approved plan" if sha else "the host gave no merge sha to check"
-        repo.move(row, E.SYNC_TIMEOUT, "worker", why)
+        repo.move(row, E.SYNC_TIMEOUT, "worker", f"{why}: {unreadable}"[:240] if unreadable else why)
     elif after_apply:
         repo.move(row, E.SYNCED, "cmapi-deliverer", "applied and confirmed by a read before the merge")
         approval = "auto" if (row.requirement or {}).get("auto") else "human"
```

**Test:** `test_a_name_that_lands_during_the_hosts_merge_leaves_the_request_merged_then_sync_failed[argocd|apply]`
(reviewer 1's, unchanged). It fails on head and passes on the final tree. Mutant `f1-merged-raises`: killed, 2 failed.

### F2 (Medium): `pr_checks`' base read: upheld

**Is superseding right?** Yes.
- The merge check, 50 lines later in the same job, reads the same main through `as_plan`. It answers `BASE_CHANGED` →
  `superseded`, with `end_pr`, and reason "the folder on main at X is no longer the plan's base" (`MergeCheck.reason`).
- Reviewer 1's handler gives the same transition and the same words, plus the path. It is legal from `pr_open`
  (`lifecycle.py:70`).
- `push_branch` (the PR) supersedes on the same condition.
- A `pr_failed` alternative would offer `:retry`, which re-pushes. `push_branch` then reads main, finds the name and
  supersedes anyway.
- One order difference, which I accept: when the PR head's checks would also fail, this supersede comes first, where a base
  that merely changed would give `pr_failed` first. Both end the request, and the retry path ends superseded.

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

**Test:** `test_a_name_that_lands_on_main_while_the_pr_is_open_supersedes_it` (reviewer 1's): `superseded`, no errors, the
path in a note, and the PR closed unmerged. Mutant `f2-pr-checks-raises`: killed.

### F3 (Low): the Gitea branch: upheld; reviewer 1's Gitea fix replaced

**Can reviewer 1's conditional delete remove anything that is not cmapi's?**
- It deletes `cmapi/<cluster>/<request>` only when its head equals `base`, the main commit cmapi just created the branch from.
  The create went through only on a 201, since `ok=(201,)` and anything else raises.
- A branch at main's commit holds no commit that main lacks, so no one's work is lost.
- One exception: the window between `delete_branch`'s GET and its DELETE. Gitea's REST delete is not conditional, and
  `delete_branch`'s docstring already accepts that race for every delete. A person who pushes to that cmapi-named branch
  inside the window loses the push.
- So it is safe within the existing contract. But it has three faults. It catches every `Exception`. It swallows a failed
  delete with a false comment (see Retracted, 2). And a failed delete still leaves the branch, which a retry refuses
  (`BranchRefused` → `failed`) and `git_reconcile` keeps for ever as `foreign_branch`.

**The simpler fix.** Read the folder at `base`, main's commit, **before** creating the branch.
- The branch is created from `base` (`old_ref_name: base`), so the read is of the same tree. `_folder_head` returns a commit
  ID as it is.
- A read that fails, from a lost name (#626) or from the host (a gap that predates the PR), leaves nothing behind. No delete
  and no try are needed.
- The only call removed is one GET of the branch's head.
- `push_branch`'s `except NotUtf8` around the push stays as reviewer 1 wrote it. Main can still gain such a name between
  `push_branch`'s own read and this one.

```diff
--- a/cmapi/src/cmapi/core/git/gitea.py
+++ b/cmapi/src/cmapi/core/git/gitea.py
@@ -134,13 +134,15 @@
                 return PushResult(existing, parents[0], "adopted")
             if not self.delete_branch(branch, existing):
                 raise BranchMoved(f"branch {branch} moved from {existing[:8]} before its stale attempt was replaced")
+        # The folder at main's commit, which the new branch starts from, read before the branch exists: a read that fails (a name
+        # that is not UTF-8, #626, or the host) leaves no branch at main's commit, which a retry would refuse as not cmapi's.
+        current, _ = self.read_folder(req.folder, base)
+        # A removal is any path of the folder, not only a manifest (#616). Only a plan that removes one walks the subfolders.
+        listed = self._walk(req.folder, base)[0] if any(text is None for text in req.files.values()) else {}
         r = self._call("create_branch", "POST", f"{self._repo()}/branches",
                        json={"new_branch_name": branch, "old_ref_name": base}, ok=(201,))
         if r.status_code != 201:
             raise GitUnavailable(f"create branch {branch}: {r.status_code} {self.host_text(r, 200)}")
-        current, _ = self.read_folder(req.folder, branch)
-        # A removal is any path of the folder, not only a manifest (#616). Only a plan that removes one walks the subfolders.
-        listed = self._walk(req.folder, branch)[0] if any(text is None for text in req.files.values()) else {}
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

The stub in `test_gitea_review.py` now serves main's commit explicitly, and its subtree IDs can no longer collide with `MAIN`:

```diff
--- a/cmapi/tests/service/test_gitea_review.py
+++ b/cmapi/tests/service/test_gitea_review.py
@@ -48,9 +48,11 @@
             return httpx.Response(200, json={"sha": HEAD, "commit": {"message": self.message}, "parents": [{"sha": MAIN}]})
         if method == "GET" and path == "/pulls":
             return httpx.Response(200, json=[{"number": 1, "head": {"ref": BRANCH, "sha": HEAD}}] if self.open_pr else [])
+        if method == "GET" and path == f"/git/trees/{MAIN}":
+            return httpx.Response(200, json={"tree": [], "truncated": False})   # main's commit: the folder is not there yet
         if method == "GET" and path.startswith("/git/trees/"):
             parts = FOLDER.strip("/").split("/")
-            trees = [self.branch, *(str(i) * 40 for i in range(len(parts)))]
+            trees = [self.branch, *(str(i) * 40 for i in range(2, 2 + len(parts)))]   # never MAIN's "1" * 40
             depth = trees.index(path.rsplit("/", 1)[1])
             if depth < len(parts):
                 entries = [{"type": "tree", "path": parts[depth], "sha": trees[depth + 1]}]
```

**Tests:**
- `test_the_gitea_stand_in_leaves_no_branch_when_it_cannot_read_the_folder[lost-name|host-down]`. Reviewer 1's, widened to
  the host outage. It asserts only that no branch is left, so it does not depend on the design: it fails on head and passes
  on reviewer 1's fix and on mine.
- `test_a_name_the_push_finds_supersedes_the_request` (reviewer 1's).
- Mutants: `f3-gitea-creates-first` (head's order restored) killed, 2 failed; `f3-push-raises` killed.

### F4 (Low): the escape: upheld, reviewer 1's fix incomplete

**Is it unambiguous both ways?** With reviewer 1's patch, no.
- Its `shown()` doubled the backslashes of a name that is not UTF-8. But `git_name` returned a name with U+FFFD verbatim,
  and so did `refuse_lost_names` (REST) and `manifest_text` (text-failure paths). All of them go into the same `paths`.
- So `"a\xe9�.yaml"` typed as UTF-8 (a backslash, `x`, `e`, `9`, then U+FFFD) and the bytes `b"a\xe9\xef\xbf\xbd.yaml"`
  both show as `a\xe9�.yaml`.
- Measured on reviewer 1's patch, on a real repository: a delete of a folder holding both gave
  `paths == ['…/b\\xe9�.txt', '…/b\\xe9�.txt']`, one path for two files.
- The Git layer and REST also disagreed for a U+FFFD name with a backslash.
- The problem page tells a client to read `\\` as a backslash and `\xNN` as a byte (RFC 9457 §3.1.4: read the extension, not
  `detail`). That reading was wrong for those paths.

**Final fix.** Every path of `NotUtf8` goes through `shown()`. Every backslash is doubled, as git's `cq_lookup` always quotes
0x5C, and every undecodable byte becomes `\xNN`. In the result, a `\` is always followed by `\` or by `x` and two hex digits.
So the text reads back to exactly one byte string. The test proves this on 5,000 names drawn from backslashes, `x`, hex
digits, U+FFFD and bad bytes.

**Narrowed.** Reviewer 1's `path_text`, and its `changed_paths` and `_adoptable` hunks, are dropped:
- They are not `paths`, they change no decision, and they did not make the escaping one-to-one.
- `changed_paths` output is compared with plan paths and shown in a check's note.
- A collision there with a literal plan path is caught by the strict `_folder` or `_entries` read that follows. Reviewer 1's
  claim 7 says the same.

```diff
--- a/cmapi/src/cmapi/core/git/base.py
+++ b/cmapi/src/cmapi/core/git/base.py
@@ -65,28 +65,35 @@
 class NotUtf8(Exception):
     """Paths under a folder whose name, or a manifest whose text (part), is not UTF-8, so cmapi cannot carry them (#626).
 
-    Git keeps a name as bytes, and a plan, the API's JSON and the database hold text. Each path is shown with each byte that is
-    not UTF-8 escaped as \\xNN, or with the U+FFFD a REST host gave. Not GitUnavailable: Git answered, and a retry reads the
-    same folder."""
+    Git keeps a name as bytes, and a plan, the API's JSON and the database hold text. Each path is as shown() shows it. Not
+    GitUnavailable: Git answered, and a retry reads the same folder."""
 
     def __init__(self, paths: Iterable[str], part: Literal["name", "text"]):
         self.paths, self.part = sorted(paths), part
-        super().__init__(f"the {part} of {', '.join(self.paths[:3])}{' and more' if len(self.paths) > 3 else ''} is not UTF-8")
+        # U+FFFD is valid UTF-8: a REST host's stand-in for a lost byte, or typed on purpose. Either way no plan can carry it.
+        self.rule = "is not UTF-8 or holds U+FFFD" if any(REPLACEMENT in p for p in self.paths) else "is not UTF-8"
+        super().__init__(f"the {part} of {', '.join(self.paths[:3])}{' and more' if len(self.paths) > 3 else ''} {self.rule}")
 
 
+def shown(raw: bytes) -> str:
+    """A path of NotUtf8, to show: each backslash doubled, as Git's own quoting always escapes one (core.quotePath), and each
+    byte that is not UTF-8 as \\xNN (codecs, 'backslashreplace'). So each shown path stands for one name only (#626)."""
+    return raw.replace(b"\\", b"\\\\").decode(errors="backslashreplace")
+
+
 def git_name(raw: bytes) -> tuple[str, bool]:
     """A name as `git ls-tree -z` gives it ("the filename is output verbatim", git-ls-tree(1)), as text, and whether cmapi can
-    carry it: valid UTF-8 with no U+FFFD. A name it cannot carry comes back with each byte that is not UTF-8 as \\xNN, to show."""
+    carry it: valid UTF-8 with no U+FFFD. A name it cannot carry comes back as shown() shows it."""
     try:
         name = raw.decode()
     except UnicodeDecodeError:
-        return raw.decode(errors="backslashreplace"), False
-    return name, REPLACEMENT not in name
+        return shown(raw), False
+    return (name, True) if REPLACEMENT not in name else (shown(raw), False)
 
 
 def refuse_lost_names(paths: Iterable[str]) -> None:
     """NotUtf8 for each name a REST host gave with U+FFFD: the byte it stands for is lost, so no plan can name the path."""
-    lost = [p for p in paths if REPLACEMENT in p]
+    lost = [shown(p.encode()) for p in paths if REPLACEMENT in p]
     if lost:
         raise NotUtf8(lost, "name")
 
@@ -98,7 +105,7 @@
         try:
             files[path] = data.decode()
         except UnicodeDecodeError:
-            bad.append(path)
+            bad.append(shown(path.encode()))
     if bad:
         raise NotUtf8(bad, "text")
     return files
```

The problem page (five lines kept, so the citations of `problem_docs.py:61-62` in docs/14 do not move):

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
+                       "manifests as UTF-8 text. `paths` shows each byte that is not UTF-8 as `\\xNN` (`caf\\xe9.yaml`), and each "
+                       "backslash as `\\\\`. A name with U+FFFD, which a Git host's API gives for such a byte, is refused too. "
+                       "`git ls-tree` shows the same name quoted, with each byte in octal (`caf\\351.yaml`).",
     "idempotency-replay": "Send a new `Idempotency-Key` for a new request. A key belongs to one request body.",
     "precondition-failed": "For a read, send it again without `If-Match` or `If-Unmodified-Since`. For a change, read the object again, and send the change with the new `ETag` in `If-Match`.",
     "validation-failed": "Correct the fields that `errors` names, and send the request again.",
```

**Tests** (each fails on head; every one but the first, and only the `[u-fffd]` case of the fourth, also fails on reviewer 1's
patch, with an assertion error: `r1-t` run above, 6 failed):
- `test_two_names_that_are_not_utf8_never_show_the_same` (reviewer 1's).
- `test_a_name_with_u_fffd_and_a_backslash_never_shows_as_one_that_is_not_utf8`. On reviewer 1's patch:
  `('a\\xe9�.yaml', False) != ('a\\\\xe9�.yaml', False)`.
- `test_each_name_cmapi_cannot_carry_reads_back_as_its_bytes`. On reviewer 1's patch: `b'ee\\ae…' != b'ee\\\\ae…'`.
- `test_the_delete_listing_names_two_such_names_apart[backslash|u-fffd]`, a real repository. On reviewer 1's patch:
  `[u-fffd]` gives `assert 1 == 2`.
- `test_rest_shows_a_lost_name_as_the_git_layer_shows_it[github|gitea]`.
- `test_a_manifest_whose_text_is_not_utf8_is_shown_as_a_name_is`.

Mutants, all killed:
- `f4-no-doubling`: 8 failed.
- `f4-fffd-verbatim`: 5 failed.
- `f4-rest-verbatim`: 2 failed.
- `f4-text-verbatim`: 1 failed.

### F5 (Low): the wording: upheld, widened to the note, single source

U+FFFD is valid UTF-8, so "whose name is not UTF-8" is false for a name that holds one. Reviewer 1 fixed the 409's `detail`.
But `NotUtf8`'s own message is written into the request's events and shown on its timeline:
- the `base_changed` note of the PR's supersede;
- reviewer 1's F1 and F2 notes.

That message said the same false thing. The rule now lives once, as `NotUtf8.rule`:
- both texts use it;
- `pipeline.py` drops its copy and its `REPLACEMENT` import, so it differs from head by one line.

For `part == "text"` the condition cannot be met: a text-failure path is a name that passed `git_name` or
`refuse_lost_names`, so it holds no U+FFFD.

```diff
--- a/cmapi/src/cmapi/core/pipeline.py
+++ b/cmapi/src/cmapi/core/pipeline.py
@@ -554,7 +554,7 @@
     resolve in Git and then send again (RFC 9110, section 15.5.10), as folder-holds-submodule is. Nothing is planned."""
     shown = ", ".join(exc.paths[:3]) + (f" and {len(exc.paths) - 3} more" if len(exc.paths) > 3 else "")
     action = "Rename it" if exc.part == "name" else "Write it again as UTF-8"
-    return Problem.conflict("folder-not-utf8", f"The folder of {ns} holds {shown}, whose {exc.part} is not UTF-8: cmapi carries a "
+    return Problem.conflict("folder-not-utf8", f"The folder of {ns} holds {shown}, whose {exc.part} {exc.rule}: cmapi carries a "
                                                f"folder's names and manifests as UTF-8 text. {action} in Git, then send the request "
                                                "again", paths=exc.paths)
 
```

(`NotUtf8.rule` is in the `base.py` hunk under F4.)

**Test:** `test_the_detail_names_the_rule_a_name_with_u_fffd_breaks`, which now also checks `str(NotUtf8(...))`. Mutant
`f5-rule-always-plain`: killed.

### F6 (Low): the examples: upheld

- **Byte-exact.** Rendering the contract with `cmapi-tools openapi render --metadata-keys
  examples/cluster-configs/policies/metadata-keys.yaml` gives the committed `openapi.json`, `cmp`-identical, on head
  (`render-head.json`), on reviewer 1's patch (`render-r2.json`) and on the final tree (`render-final.json`).
- **The intended change only.** `diff head final` on the contract holds only 8 added `paths` arrays: 7 for `folder-not-utf8`
  and 1 for `folder-holds-submodule`.
- **oasdiff.** `head/cmapi/contract/gate.sh` ran in the export, with oasdiff 1.37.0, the version CI pins
  (`api-contract-report.yml`). base → final and head → final both gave "No breaking changes to report", rc 0
  (`gate-final.log`).
- **The portal.** `schema.generated.ts` holds no example values (0 matches), so it does not change.
- **Citations.** docs.py's two new lines move docs/14's citation from 306-311 to 308-313. Checked with reviewer 1's
  `citations_check.py`, because the export has no `.git` for `git ls-files`: 0 problems on head, on `r2/` and on the final
  tree (`citations-check.log`). CI, which has `.git`, runs `test_doc_citations` itself.

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

The contract and doc-citation hunks are in `fix.diff`, unchanged from reviewer 1's.

**Test:** `test_the_example_of_a_folder_refusal_shows_its_paths[folder-not-utf8|folder-holds-submodule]`. Mutants
`f6-no-paths-example` and `f6-no-submodule-paths`: each killed.

### F7 (Low): `watch_sync`: upheld, apply-mode line now tested

Reviewer 1 changed both comparisons, the apply-mode one and the argocd one. Its test runs argocd mode only, so a mutant of the
apply-mode line would have survived.

The new `test_watch_sync_in_apply_mode_reads_a_folder_it_cannot_name_as_not_the_plans` takes the one path that reaches
`watch_sync` in apply mode:
1. a person merges after `pr_checks` (`test_delivery_states_db_review.person_merges`);
2. such a name lands on main;
3. the apply job adopts the merge, and `watch_sync` must refuse with `sync_failed`, no errors and nothing applied.

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

Mutants `f7-argocd-raw-compare` and `f7-apply-raw-compare`: each killed.

## What reviewer 1 missed

1. **F4 was not one-to-one.** U+FFFD names, REST names and text-failure paths were shown verbatim beside escaped ones in the
   same `paths`. Measured collision on a real repository; fixed above.
2. **F3's comment is false, and a simpler fix exists.** `git_reconcile` keeps the branch. The reorder that reviewer 1 rejected
   does not break the tests. The stub had a coincidence that hid main's read, now corrected.
3. **F5 left the same error in `NotUtf8`'s message,** which reaches the request's timeline.
4. **F7's apply-mode line had no test.** Added.
5. **The records** called the end state `pr_failed`, which is an event; the statuses are `failed` and `merge_failed`.
6. **A pre-existing defect, fixed by F3 in this PR:** on Gitea, a host error during the read after `create_branch` left a
   branch at main's commit. The retry then refused it (`BranchRefused` → `failed`), and the alert counted a foreign branch.
   The `host-down` case of the F3 test fails on head and passes on the final tree.

## The records

The README and docs/02 hunks below replace reviewer 1's text where I changed the design, and correct `pr_failed`:

```diff
--- a/docs/reviews/2026-11-24-issue-626/README.md
+++ b/docs/reviews/2026-11-24-issue-626/README.md
@@ -139,14 +139,29 @@
 resolves it in Git and sends the request again, as RFC 9110 describes 409 and as `folder-holds-submodule` (#616) already
 does. `paths` is an extension member, so a client reads the paths without parsing `detail` (RFC 9457, 3.1.4 and 3.2).
 
-Why `\xNN` and not git's octal quoting: the escaping is Python's documented `backslashreplace`, and it changes only the
-bytes that are not UTF-8. Git shows the same name as `"caf\351.yaml"` with its default `core.quotePath`; the problem page
-says so, so a person can match the two.
+Why `\xNN` and not git's octal quoting: the escaping is Python's documented `backslashreplace`. Each backslash of a path in
+`paths` is doubled first, as Git's own quoting always escapes one (`core.quotePath`: "Double-quotes, backslash and control
+characters are always escaped"; `quote.c`, `cq_lookup`), so each shown path stands for one name only (reviewer 1's F4,
+widened by reviewer 2 to every path of `paths`). Git shows the same name as `"caf\351.yaml"` with its default
+`core.quotePath`; the problem page says so, so a person can match the two.
 
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
+  is merged and then `sync_failed`, with the path in the note (F1). Before, it was five errors and then `failed` (argocd) or
+  `merge_failed` (apply), with the PR merged on the host. Argo CD syncs such a main all the same: a directory application
+  loads every `.yaml` file of the folder whatever the bytes of its name, and reads a text that is not UTF-8 with U+FFFD in
+  place of each bad byte (argo-cd `reposerver/repository/repository.go`, `utfutil.OpenFile(manifestPath, utfutil.UTF8)`;
+  golang.org/x/text `encoding/unicode`, "Append RuneError to the destination"; read from source, not measured).
+- `watch_sync` compares main's folder with the plan through `as_plan`, as the merge check does (F7).
+- The Gitea stand-in reads the folder at main's commit before it creates the branch, so a read that fails (such a name, or
+  the host) leaves no branch at main's commit, which a retry would refuse as not cmapi's. `push_branch` supersedes on a
+  `NotUtf8` from the push itself (F3).
+
+Still the worker's retry, then failure, as for any error, with `NotUtf8: the name of <path> is not UTF-8` in the note: the
+reads of a PR head that a person pushed to (`pr_checks`' tree and a delete's head, `apply`'s tree; the request ends
+`failed`, or `sync_failed` once an apply started, as a failed check would), the retry of a `sync_failed` delete
+(`prune`), and `open_revert`. Each is bounded by the five attempts, and none leaves a lock held without a state that offers
+`:retry` or `:revert`.
```

```diff
--- a/docs/02-technical-design-v2.md
+++ b/docs/02-technical-design-v2.md
@@ -998,7 +998,7 @@
 
 **A delete removes the whole folder (#616).** The plan lists every file of the namespace's folder at any depth, whatever made it: cmapi's manifests, a README, a `.yml` or `.json` manifest, a subfolder (`GitProvider.list_folder`: `git ls-tree -r` in the Git layer, the Git Trees API on GitHub, each subtree on Gitea). Each path is shown as removed in the plan and the dry run, so the approvers see it before anything reaches Git, and the branch removes each one. The root Application syncs the namespaces folder with `directory.recurse: true` and reads `.yaml`, `.yml` and `.json` files, so a manifest left in a subfolder would stay in its desired state after the Namespace is pruned. A path that the folder gains or loses after the plan, or a file that becomes a submodule, supersedes the delete at push_branch, and again at the merge check before the merge: main's full listing must be the plan's removals, and the merged result must hold nothing of the folder. The check after the merge, an empty folder at the merge sha, is for a path that lands during the host's own merge; it leaves the delete sync_failed, and its :retry reads the folder on main before the cluster, so it confirms only an empty folder. The revert of a delete restores cmapi's manifests and names each other path it does not restore, with the commit that holds it (`revert_partial`). A submodule is refused with 409 folder-holds-submodule: its removal also changes `.gitmodules`, outside the folder. The other reads of a folder (the ETag, the plan's base, the renderer's previous files) stay the `.yaml` files directly in it (#578). The decision record is docs/reviews/2026-11-23-issue-616/README.md.
 
-**A name or a manifest that is not UTF-8 (#626).** Git keeps a file name as bytes, and a plan, the API's JSON and the database hold text, so cmapi carries a folder's names and manifests only as UTF-8. A REST host loses such a byte: GitHub's git/trees and Contents answered `caf\xe9.yaml` as `caf\ufffd.yaml`, U+FFFD in its place (measured 2026-11-24), and Gitea's JSON encoder writes the same, so a name that holds U+FFFD is treated as one that is not UTF-8 on every provider. A write or a read of the namespace whose folder holds such a manifest, a delete whose folder holds such a path at any depth, or a manifest whose text is not UTF-8, is 409 folder-not-utf8 with each path in `paths`, each byte that is not UTF-8 shown as `\xNN`, and nothing is planned. A name a change never reads (a subfolder's, a README's) does not refuse it. Such a path that reaches the folder after the plan supersedes the request at push_branch, and the merge check reads such a folder as not the plan's. The decision record is docs/reviews/2026-11-24-issue-626/README.md.
+**A name or a manifest that is not UTF-8 (#626).** Git keeps a file name as bytes, and a plan, the API's JSON and the database hold text, so cmapi carries a folder's names and manifests only as UTF-8. A REST host loses such a byte: GitHub's git/trees and Contents answered `caf\xe9.yaml` as `caf\ufffd.yaml`, U+FFFD in its place (measured 2026-11-24), and Gitea's JSON encoder writes the same, so a name that holds U+FFFD is treated as one that is not UTF-8 on every provider. A write or a read of the namespace whose folder holds such a manifest, a delete whose folder holds such a path at any depth, or a manifest whose text is not UTF-8, is 409 folder-not-utf8 with each path in `paths`, each byte that is not UTF-8 shown as `\xNN`, and nothing is planned. A name a change never reads (a subfolder's, a README's) does not refuse it. Such a path that reaches the folder after the plan supersedes the request at push_branch or at pr_checks, the merge check reads such a folder as not the plan's, and a merge whose folder holds one is merged and then sync_failed. In `paths` each backslash is doubled, so each shown path stands for one name only. The decision record is docs/reviews/2026-11-24-issue-626/README.md.
 
 If your cluster-configs repo keeps the existing segment/mnemonic/clusterEnv layout, the renderer maps clusterId to that path instead; the registry's gitopsPath is the only place the mapping lives.
 
```

## Mutants of the final fix

Each mutant is one exact substitution on a fresh copy of the final tree, asserted to occur exactly once
(`r2-outputs/mutants/mutants.py`). Only the tests that decide it are run. Logs are in `r2-outputs/mutants/<name>.log`.

```
# Mutants of reviewer 2's final fix (r2-outputs/fix.diff), each on a fresh copy of the final tree; 2026-11-24. KILLED = its tests failed.
f3-gitea-creates-first   KILLED  2 failed, 17 deselected in 4.31s
f4-no-doubling           KILLED  8 failed, 1 passed, 10 deselected in 10.80s
f4-fffd-verbatim         KILLED  5 failed, 4 passed, 10 deselected in 10.91s
f4-rest-verbatim         KILLED  2 failed, 17 deselected in 4.05s
f4-text-verbatim         KILLED  1 failed, 18 deselected in 3.47s
f5-rule-always-plain     KILLED  1 failed, 18 deselected in 3.24s
f6-no-paths-example      KILLED  1 failed, 1 passed, 17 deselected in 3.57s
f6-no-submodule-paths    KILLED  1 failed, 1 passed, 17 deselected in 3.50s
f1-merged-raises         KILLED  2 failed, 17 deselected in 30.17s
f2-pr-checks-raises      KILLED  1 failed, 18 deselected in 7.75s
f3-push-raises           KILLED  1 failed, 18 deselected in 7.25s
f7-argocd-raw-compare    KILLED  1 failed, 18 deselected in 9.87s
f7-apply-raw-compare     KILLED  1 failed, 18 deselected in 7.85s
```

## What I did not test

- A running Gitea, GitHub after this fix, Argo CD (its behaviour is read from source), CRC or any cluster.
- The whole service suite (per the brief). The after-run covered 16 files, listed in `after-final-tests.log`.
- `test_doc_citations` itself: it needs `.git`. The same check ran through `citations_check.py`.
- `open_revert` and the `sync_failed` prune retry, which reviewer 1 left on the retry path. I read its reasoning (bounded by
  5 attempts, and the request stays recoverable) and agree. I did not re-measure those states.
- The portal build (no change to `schema.generated.ts`).

## Who wrote what

- Reviewer 1 (Opus 5.5, standing in for Codex) wrote these parts, which I kept:
  - F1's `except NotUtf8` and its note;
  - F2;
  - `push_branch`'s `_superseded` and `except NotUtf8`;
  - F5's detail rule;
  - F6;
  - F7's code;
  - their tests and most of the records.
- Reviewer 2 (this agent, Opus 5.5) wrote:
  - the F1 narrowing;
  - the Gitea reorder and the stub correction;
  - the F4 escaping for every path, with its five new tests;
  - `NotUtf8.rule`;
  - the apply-mode F7 test;
  - the record corrections;
  - `mutants.py`.

## Appendix: the review's test file, final

```python
"""PR #647 (#626), reviewers 1 and 2: the reads that #626 left on the worker's retry-then-fail path, and the shown names.

Each test fails on the PR's head and passes with the review's fix:
- F1: _merged read the folder at the merge sha, so a name that landed during the host's merge raised NotUtf8 after the merge,
  five times, and the merged request ended failed (argocd) or merge_failed (apply) with its PR merged on the host.
- F2: pr_checks reads main's folder before the merge check, so a name that landed while the PR was open was five errors and
  failed, where the merge check would have superseded it.
- F3: the Gitea stand-in created the request branch before it read the folder: a read that failed (such a name, or the host)
  left a branch at main's commit, which a retry refuses and git_cleanup keeps as foreign. The push_branch job retried a
  NotUtf8 from the push itself.
- F4: backslashreplace alone shows two different names the same: b"a\\xe9\\\\xff" and b"a\\\\xe9\\xff" are both "a\\xe9\\xff".
  Reviewer 2: so does a name with U+FFFD and a backslash, which the fix of reviewer 1 left verbatim. Every path of NotUtf8 now
  reads back as its bytes.
- F5: the detail, and the note NotUtf8 writes, said "is not UTF-8" of a name that is UTF-8 and holds U+FFFD.
- F6: the contract's examples of folder-not-utf8 and folder-holds-submodule had no `paths`, the member each one carries.
- F7: watch_sync read main's folder outside the merge check's rule: five errors before the sync_failed it ends in anyway.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import random

import httpx
import pytest

from cmapi.core.docs import problem_example
from cmapi.core.git.base import BranchRequest, GitUnavailable, NotUtf8, git_name, manifest_text
from cmapi.core.git.workspace import GitWorkspace
from cmapi.core.pipeline import folder_not_utf8
from gitserver import bare_repo
from test_delete_whole_folder_616 import FOLDER_PATH, HEAD, RestHost, _gitea, _github
from test_delivery_states_db_review import person_merges
from test_git_layer import argocd, drive, layer  # noqa: F401  (layer is the real Git layer's fixture)
from test_github_read_folder_632 import GitHubContents
from test_non_utf8_names_626 import BASE, LATIN1, LOST, MANIFEST, NAMESPACE, SHOWN, commit_bytes

BAD = BASE.encode() + LATIN1


def _notes(view) -> list[tuple[str, str]]:
    return [(e["event"], e["note"] or "") for e in view["events"]]


def _errors(view) -> list[str]:
    return [note for event, note in _notes(view) if event == "error"]


def _until(w, rid: str, status: str, limit: int = 20) -> None:
    """Run the worker one job at a time until the request reaches status."""
    for _ in range(limit):
        if w.view(rid)["status"] == status:
            return
        assert drive(w.ctx, limit=1), f"no job left before {status}: {_notes(w.view(rid))}"
    raise AssertionError(f"never reached {status}: {_notes(w.view(rid))}")


def _mode(w, mode: str) -> None:
    if mode == "argocd":
        argocd(w)
    else:
        w.ctx.delivery = replace(w.ctx.delivery, mode="apply")


# --------------------------------------------------------------------------- F1: after the merge

@pytest.mark.parametrize("mode", ["argocd", "apply"])
def test_a_name_that_lands_during_the_hosts_merge_leaves_the_request_merged_then_sync_failed(layer, mode):  # noqa: F811
    """The host merged: the request must say so. Merged, then sync_failed with the lock held for an operator (_merged's own
    rule for a folder at the merge that is not the plan's), never five errors and then pr_failed or merge_failed."""
    w = layer
    _mode(w, mode)
    rid = w.create()
    w.host.merge_hook = lambda number: commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})

    drive(w.ctx)

    v = w.view(rid)
    assert w.host.prs[1]["merged"], "the host merged the PR"
    assert v["status"] == "sync_failed", _notes(v)
    assert not _errors(v), _notes(v)
    assert any(SHOWN in note for _, note in _notes(v)), "the operator is told which path"


# --------------------------------------------------------------------------- F2: while the PR is open

def test_a_name_that_lands_on_main_while_the_pr_is_open_supersedes_it(layer):  # noqa: F811
    w = layer
    argocd(w)
    rid = w.create()
    _until(w, rid, "pr_open")
    commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})

    drive(w.ctx)

    v = w.view(rid)
    assert v["status"] == "superseded", _notes(v)
    assert not _errors(v), _notes(v)
    assert any(SHOWN in note for _, note in _notes(v))
    assert w.host.prs[1]["state"] == "closed" and not w.host.prs[1]["merged"]


# --------------------------------------------------------------------------- F7: after the merge, waiting for the sync

def test_watch_sync_reads_a_folder_it_cannot_name_as_not_the_plans(layer):  # noqa: F811
    w = layer
    argocd(w)
    rid = w.create()
    _until(w, rid, "merged")
    commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})

    drive(w.ctx)

    v = w.view(rid)
    assert v["status"] == "sync_failed", _notes(v)
    assert not _errors(v), _notes(v)


def test_watch_sync_in_apply_mode_reads_a_folder_it_cannot_name_as_not_the_plans(layer):  # noqa: F811
    """Apply mode reaches watch_sync after a person's merge before the apply: it applies from main, so it reads main first."""
    w = layer                                  # apply mode
    rid = w.create()
    assert drive(w.ctx, limit=3) == ["push_branch", "open_pr", "pr_checks"]
    branch = f"cmapi/CRC/{rid}"
    person_merges(w, branch, w.host.head(branch))
    commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})

    drive(w.ctx)

    v = w.view(rid)
    assert v["status"] == "sync_failed", _notes(v)
    assert not _errors(v), _notes(v)
    assert "applied" not in w.events(rid), "nothing applied from that main"


# --------------------------------------------------------------------------- F3: the push itself

def test_a_name_the_push_finds_supersedes_the_request(layer, monkeypatch):  # noqa: F811
    """The Gitea stand-in reads the folder as it writes the branch: a name that landed after push_branch's own read."""
    w = layer
    argocd(w)

    def found(req):
        raise NotUtf8([SHOWN], "name")

    monkeypatch.setattr(w.ctx.git, "push_request_branch", found)
    rid = w.create()

    drive(w.ctx)

    v = w.view(rid)
    assert v["status"] == "superseded", _notes(v)
    assert not _errors(v), _notes(v)
    assert any(SHOWN in note for _, note in _notes(v))


class _Branching(RestHost):
    """RestHost, where the request branch, once created, is main's commit as Gitea makes it, and can be deleted."""

    BRANCH = "/branches/cmapi/CRC/req-1"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1").removeprefix("/repos/o/r")
        if request.method == "GET" and path == self.BRANCH and self.branch_exists:
            self.calls.append(("GET", path, {}))
            return httpx.Response(200, json={"commit": {"id": HEAD}})
        if request.method == "DELETE" and path == self.BRANCH:
            self.calls.append(("DELETE", path, {}))
            self.branch_exists = False
            return httpx.Response(204)
        return super().__call__(request)


class _Down(_Branching):
    """_Branching, whose tree reads answer 503, as a Git host in an outage does."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if "/git/trees/" in request.url.path:
            return httpx.Response(503, json={"message": "unavailable"})
        return super().__call__(request)


@pytest.mark.parametrize("host, error", [(_Branching({**MANIFEST, LOST: ("blob", "100644")}), NotUtf8),
                                         (_Down(MANIFEST), GitUnavailable)], ids=["lost-name", "host-down"])
def test_the_gitea_stand_in_leaves_no_branch_when_it_cannot_read_the_folder(host, error):
    """A branch left at main's commit is not cmapi's: a retry refuses it (BranchRefused) and git_cleanup keeps it as foreign."""
    path = next(iter(MANIFEST))
    req = BranchRequest("CRC", "req-1", BASE, "hash", "update\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
                        {path: "changed\n"}, {path: f"text of {path}\n"}, datetime(2026, 1, 1, tzinfo=timezone.utc))

    with pytest.raises(error):
        _gitea(host).push_request_branch(req)

    assert not host.branch_exists, [call[:2] for call in host.calls]


# --------------------------------------------------------------------------- F4: what `paths` shows

def test_two_names_that_are_not_utf8_never_show_the_same():
    one, two = b"a\xe9\\xff.yaml", b"a\\xe9\xff.yaml"
    assert git_name(one) == ("a\\xe9\\\\xff.yaml", False)
    assert git_name(two) == ("a\\\\xe9\\xff.yaml", False)
    assert git_name(b"caf\xe9.yaml") == ("caf\\xe9.yaml", False), "a name with no backslash shows as before"


def test_a_name_with_u_fffd_and_a_backslash_never_shows_as_one_that_is_not_utf8():
    typed, lost = "a\\xe9\ufffd.yaml".encode(), b"a\xe9\xef\xbf\xbd.yaml"
    assert git_name(typed) == ("a\\\\xe9\ufffd.yaml", False)
    assert git_name(lost) == ("a\\xe9\ufffd.yaml", False)


def _unshown(text: str) -> bytes:
    """The bytes of a path of NotUtf8, read back as the problem page says: \\\\ is a backslash, \\xNN a byte."""
    out, i = b"", 0
    while i < len(text):
        if text.startswith("\\\\", i):
            out, i = out + b"\\", i + 2
        elif text.startswith("\\x", i):
            out, i = out + bytes([int(text[i + 2:i + 4], 16)]), i + 4
        else:
            out, i = out + text[i].encode(), i + 1
    return out


def test_each_name_cmapi_cannot_carry_reads_back_as_its_bytes():
    """Unambiguous both ways: 5,000 names of backslashes, "x", hex digits, U+FFFD and bytes that are not UTF-8."""
    rng = random.Random(626)
    pool = [b"\\", b"x", b"e", b"9", b"a", b"\xe9", b"\xff", b"\x80", b"\xc3", b"\xa9", "\ufffd".encode()]
    for _ in range(5000):
        raw = b"".join(rng.choice(pool) for _ in range(rng.randint(1, 8)))
        name, carried = git_name(raw)
        if carried:
            assert name == raw.decode(), raw
        else:
            assert _unshown(name) == raw, (raw, name)


@pytest.mark.parametrize("one, two", [(b"a\xe9\\xff.txt", b"a\\xe9\xff.txt"),
                                      (b"b\xe9\xef\xbf\xbd.txt", "b\\xe9\ufffd.txt".encode())], ids=["backslash", "u-fffd"])
def test_the_delete_listing_names_two_such_names_apart(tmp_path, one, two):
    bare = bare_repo(tmp_path, {f"{BASE}namespace.yaml": NAMESPACE})
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        commit_bytes(bare, tmp_path, {BASE.encode() + one: b"1\n", BASE.encode() + two: b"2\n"})
        with pytest.raises(NotUtf8) as caught:
            ws.list_folder(BASE)
        assert len(set(caught.value.paths)) == 2, caught.value.paths
    finally:
        ws.dispose()


@pytest.mark.parametrize("make", [_github, _gitea], ids=["github", "gitea"])
def test_rest_shows_a_lost_name_as_the_git_layer_shows_it(make):
    lost = f"{FOLDER_PATH}/a\\x\ufffd.yaml"
    host = GitHubContents({**MANIFEST, lost: ("blob", "100644")})
    with pytest.raises(NotUtf8) as caught:
        make(host).read_folder(BASE)
    assert caught.value.paths == [git_name(lost.encode())[0]] == [f"{FOLDER_PATH}/a\\\\x\ufffd.yaml"]


def test_a_manifest_whose_text_is_not_utf8_is_shown_as_a_name_is():
    with pytest.raises(NotUtf8) as caught:
        manifest_text({"ns/a\\b.yaml": b"x: \xe9\n"})
    assert (caught.value.paths, caught.value.part) == (["ns/a\\\\b.yaml"], "text")


# --------------------------------------------------------------------------- F5, F6: the problem

def test_the_detail_names_the_rule_a_name_with_u_fffd_breaks():
    lost = folder_not_utf8("payments-dev", NotUtf8([LOST], "name")).body()
    plain = folder_not_utf8("payments-dev", NotUtf8([SHOWN], "name")).body()
    assert "is not UTF-8 or holds U+FFFD" in lost["detail"], lost["detail"]
    assert "U+FFFD" not in plain["detail"] and "is not UTF-8" in plain["detail"]
    assert str(NotUtf8([LOST], "name")).endswith(" is not UTF-8 or holds U+FFFD"), "the note on the request's timeline"
    assert str(NotUtf8([SHOWN], "name")).endswith(f"{SHOWN} is not UTF-8")


@pytest.mark.parametrize("code", ["folder-not-utf8", "folder-holds-submodule"])
def test_the_example_of_a_folder_refusal_shows_its_paths(code):
    example = problem_example(code)
    assert example["paths"] and all(p in example["detail"] for p in example["paths"]), example
```
