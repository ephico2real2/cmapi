# PR #622, reviewer 2 (Opus 5.5, high), at ed3dcf5 (#616, #623)

The harness refused the agent's own write of this file. The coordinator saved its report text here on 2026-11-24, unchanged in substance. The evidence files are in `r2-outputs/`.

Reviewer 1's blocker is confirmed, and it is now refused before the merge on every provider. All 7 findings were checked:
- 1, 2 and 6: confirmed and fixed;
- 3, 5 and 7: confirmed and narrowed;
- 4: confirmed, but it predates this PR (a separate issue and patch).

## What was run (in `r2-outputs/`)

- **The patch:** `fix.diff`, 16 files. `patch -p1 -F0` applies it to a fresh copy of `head/` with exit 0, and the result is byte-identical to `r2/`.
- **`test_delete_whole_folder_616.py`:** 19 new tests, 33 in all.
  - On the ed3dcf5 source: 13 failed and 19 passed (`before-616.txt`). The 33rd test also fails there (`before-lost-path.txt`).
  - On the patched copy: all pass (`after-616.txt`, 32 of 32, plus the 33rd in the full suite).
- **The full service suite on `r2/`:** 2508 passed and 2 failed (`after-service-suite.txt`). The 2 failures, `test_doc_citations` and the executable-scripts test, call `git ls-files`, and the export has no `.git`.
- **`doc-citations --check`:** 0 problems on head and on r2, through a `git ls-files` shim.
- **Mutants on the fix:** 15 of 15 killed (`mutants.txt`).
- **Gate:** each run waited for no other suite and a 1-minute load under 16. The load was 7.96 to 14.03.

## Sources (fetched 2026-11-23)

- **GitHub Git trees** (docs.github.com/en/rest/git/trees):
  - "If truncated is true in the response then the number of items in the tree array exceeded our maximum limit."
  - "The limit for the tree array is 100,000 entries with a maximum size of 7 MB when using the recursive parameter."
- **GitHub Contents** (docs.github.com/en/rest/repos/contents): "This API has an upper limit of 1,000 files for a directory."
- **Gitea 1.25 get-tree:** `page` and `truncated`. The adapter walks each subtree and refuses a page that was cut.
- **Gitea v1.25.5 `services/repository/files/update.go`:** a delete's `sha` is checked against the tree entry's own ID (`ErrSHADoesNotMatch`).
- **Argo CD Directory:** it "loads plain manifest files from `.yml`, `.yaml`, and `.json` files", root-only by default. It also lists `.jsonnet`. Neither changes the decision.

## Rulings

1. **P1 blocker: a file added to main before the merge is found only after it.** Confirmed, and now refused before the merge on every provider.
   - The fix:
     - `merge_check(..., *, whole_folder=False)`; `pr_checks` and the merge job pass `row.action == "delete"`;
     - on main, the full listing must equal the plan's removals, each a plain file (`blob`);
     - the merged tree, or the head's listing, must hold nothing of the folder.
   - Also taken: reviewer 1's `pr_checks` head check, so `cmapi/check` fails a head that still holds the file.
   - `_merged`, the check after the merge, stays: a host's merge takes no expected main sha.
   - Tests:
     - `test_a_file_added_to_main_after_the_push_is_refused_before_the_merge`;
     - `..._after_the_checks_is_refused_by_the_merge_job`;
     - `test_the_git_layer_refuses_the_merge_of_a_delete_when_main_gained_a_file`;
     - `test_a_branch_built_on_a_main_that_gained_a_file_fails_the_cmapi_check`;
     - unit tests that kill mutants M4 and M5.
2. **P1: a `:retry` of a failed delete says `synced` without reading Git.** Confirmed, narrowed.
   - The retry now refuses, naming the paths left on main.
   - Reviewer 1's no-merge-sha refusal was dropped: it would hold the namespace lock for ever.
3. **P1: Git object types are ignored, and the branch is built on a second read of main.** Confirmed, narrowed.
   - `push_branch` now compares types too.
   - Reviewer 1's `checked_base` plumbing was rejected as over-build: the type-aware checks already close the window before any merge.
4. **P2: GitHub Contents caps a directory at 1,000 entries in `read_folder`.** Confirmed, but it predates #622.
   - The failure is safe: a 404, or the request is superseded.
   - The separate patch is `outside-pr-github-contents-cap.diff`. Its test fails before and passes after (`outside-4-single.txt`).
5. **P2: Gitea sends names with `#` or `?` unencoded in the URL, and walks every subtree on every push.** Confirmed, fixed differently.
   - The delete's `sha` comes from the tree walk that already ran, so no URL carries the name.
   - The walk now runs only when the plan removes a path.
6. **P2: a file name with a newline is listed in the plan, then refused at the push.** Confirmed.
   - Fixed as reviewer 1 proposed: `check_path(..., removal=True)` waives the newline rule for removals only.
7. **P2: the revert of a delete restores only the manifests.** Confirmed, narrowed.
   - No 409, because approval is the gate.
   - The original request records a `revert_partial` event that names the paths and the `base_sha`. docs/16 lists the new event.

## Safety of the recursive delete

- **Nothing outside the folder:** the paths come from a listing under the folder, with the prefix's trailing `/`.
  - The renderer, the Git layer's staged-path check and `pr_checks` each refuse a path outside the plan.
  - New tests: `test_a_longer_sibling_is_not_the_requested_folder[github|gitea]` and `test_the_renderer_removes_nothing_of_a_longer_sibling`.
- **Truncation:** a truncated GitHub tree, or a Gitea page that was cut, becomes a 502. Never a partial delete.

## What reviewer 1 missed

- **A.** `FakeGit.merge` copied the branch over main, which hid the blocker. `conftest.py` now keeps what main gained.
- **B.** Reviewer 1's retry fix would strand a request that has no merge sha.
- **C.** Reviewer 1 relied on an implicit `all(text is None)` test; this patch uses an explicit `whole_folder` flag instead.
- **D.** The provider matrix: there are two code paths, the Git layer and `HostGitProvider`. The stand-in's adopt-branch path is covered by the head listing.
- **E.** The docs:
  - docs/02's #616 paragraph now says the check runs before the merge, and covers the type check, `:retry` and `:revert`;
  - docs/16 gains `revert_partial`;
  - the contract README's step 7 names `permissions.generated.ts`.
- **F. Not measured:** non-UTF-8 file names. `workspace._entries` and `_folder` decode as strict UTF-8, so such a name gives a 500 or a job error. This predates #622 for direct files, and #616 extends it to subfolders. Suggested: an issue to refuse such a folder at the plan.

## Live docs

docs/02 only: the "A delete removes the whole folder (#616)" paragraph. The exact text is in `r2-outputs/LIVE-DOC-EDITS.md`.

## Not tested

- CRC, a real GitHub or a real Gitea. Both hosts ran as mocks shaped by the quoted docs.
- A file landing during the host's own merge.
- The cost of the stand-in's two tree walks per check on a real Gitea.
