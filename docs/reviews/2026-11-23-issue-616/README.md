# #616: a namespace delete removes the whole folder

The implementer's record. Opus 5.5 at `high` wrote it on 2026-11-23, on `fix/616-delete-folder` from `78ec33e`. The reviews will go beside it.

## The defect, as measured

`cmapi/tests/service/test_delete_whole_folder_616.py`, run on `78ec33e` (main's `src`, the new test and FakeGit's listing):

- **The folder.** A person's commit put five files into `payments-dev`'s folder, next to cmapi's five manifests:
  - `README.md`
  - `extra/configmap.yaml`
  - `extra/deeper/notes.txt`
  - `secret-store.yml`
  - `more.json`
- **The dry run** (`DELETE ...?dryRun=true`) listed only the five manifests as `removed`.
- **After the delete merged**, all five extra paths were still in the folder in Git.
- **All 14 tests of the file fail** on `78ec33e` and pass on the fix (`test-before.txt`, `test-after.txt`). Main has no
  `list_folder`, so the three listing tests and the pathspec test fail there for that reason; the pathspec test guards the
  new `git rm`, which main did not use.

The cause, read on `78ec33e`:

- `ManifestRenderer.delete` (`core/render/manifests.py`) maps to `None` only the paths it is given.
- `plan_delete` gave it the paths that `read_folder` returns: the `.yaml` files directly in the folder. Each provider reads them so:
  - `github.py`: `read_folder`, one Contents listing, entries of type `file`.
  - `gitea.py`: one tree, blobs of mode 100644 or 100755.
  - `workspace.py`: `_folder`, `git ls-tree` without `-r`.
- The checks after the push read the same way, so none of them saw the leftovers:
  - `tree_files` in `pr_checks` and in `_merged`;
  - `merge_check`.
- The Gitea stand-in deletes a path only when `read_folder` has it (`push_request_branch`).

## Sources, fetched 2026-11-23

- **Argo CD, "Directory"** (<https://argo-cd.readthedocs.io/en/stable/user-guide/directory/>):
  - A directory application "loads plain manifest files from `.yml`, `.yaml`, and `.json` files".
  - "By default, directory applications will only include the files from the root of the configured repository/path", and
    `directory.recurse: true` turns on "recursive resource detection".
  - "Non-manifest files (those without `apiVersion`, `kind`, and `metadata`) are still ignored."
- **Argo CD, "Automated Sync Policy"** (<https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/>):
  - "automated sync will not delete resources when Argo CD detects the resource is no longer defined in Git".
  - "Pruning can also be enabled to happen automatically as part of the automated sync".
- **Argo CD, "Sync Options"** (<https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/>): with `Prune=confirm`, "the
  sync operation will remain in a Syncing state until pruning is confirmed".
- **OpenGitOps Principles v1.0.0** (<https://opengitops.dev/>):
  - "A system managed by GitOps must have its desired state expressed declaratively."
  - "Software agents continuously observe actual system state and attempt to apply the desired state."
- **GitHub REST, "Repository contents"** (<https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28>): "This API
  has an upper limit of 1,000 files for a directory. If you need to retrieve more files, use the Git Trees API."
- **GitHub REST, "Git trees"** (<https://docs.github.com/en/rest/git/trees?apiVersion=2022-11-28>):
  - "The limit for the tree array is 100,000 entries with a maximum size of 7 MB when using the recursive parameter."
  - "If truncated is true in the response then the number of items in the tree array exceeded our maximum limit."
- **GitHub REST, "Git commits"** (<https://docs.github.com/en/rest/git/commits?apiVersion=2022-11-28>): the commit object's
  schema has a required `tree` with a required `sha`.
- **GitHub, "Permissions required for fine-grained personal access tokens"**
  (<https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens?apiVersion=2022-11-28>),
  under "Contents": "`GET /repos/{owner}/{repo}/git/commits/{commit_sha}` | read" and
  "`GET /repos/{owner}/{repo}/git/trees/{tree_sha}` | read". The bot's token already has Contents read.
- **RFC 9110, section 15.5.10** (<https://www.rfc-editor.org/rfc/rfc9110.txt>): "The 409 (Conflict) status code indicates
  that the request could not be completed due to a conflict with the current state of the target resource. This code is
  used in situations where the user might be able to resolve the conflict and resubmit the request."
- **git-rm(1)** (<https://git-scm.com/docs/git-rm>):
  - It removes "from the working tree and the index".
  - `--pathspec-file-nul`: "all other characters are taken literally".
  - On a submodule, "the `submodule.<name>` section in the gitmodules file will also be removed and that file will be staged".
- **The design.**
  - docs/01, "Argo CD": "Each cluster's root Application syncs clusters/\<clusterId>/namespaces with directory recurse.
    Removing a folder makes Argo CD prune its objects".
  - docs/01, expiry: "The bot PR removes the folder".
  - The renderer's own docstring: "A delete removes the whole folder: every file maps to None."
  - The example root Application: `examples/cluster-configs/clusters/OCP_GF15/argocd/root-application.yaml` has
    `directory.recurse: true` and `automated.prune: true`.

## The decision: (a), the delete removes every file of the folder

The design already decides this: the delete removes the folder. So this fix builds what the design says, and does not
reopen it.

The sources show why the other options are wrong:

- **(c), keep the extra files: refuted.** With `directory.recurse: true`, a `.yaml`, `.yml` or `.json` manifest left in a
  subfolder stays desired state in the cluster's Application. Its Namespace is pruned, and the Application goes on
  reconciling objects whose namespace is gone. A README left alone keeps a folder for a namespace that no longer exists.
  Neither is what a GitOps repository's desired state should say.
  - Measured: the files stay, in the before test.
  - Inferred, not tested on a cluster: what Argo CD then does with the leftover manifests.
- **(b), refuse a folder that holds files cmapi does not manage: rejected.** The owner's rule is "approval is the gate":
  refuse only what is not valid. A README beside the manifests is valid. The plan now lists every path as `removed`, in the
  dry run and on the request, so the approvers see each one before anything reaches Git.

There is one refusal, and it is not a policy: a submodule. `git rm` of a submodule also stages `.gitmodules` at the
repository's root. That is outside the folder, so cmapi's branch check (`staged <= set(req.files)`) and the PR's cmapi check
("paths outside the plan") refuse it after approval. So the delete refuses it at the plan instead, with 409
`folder-holds-submodule` and the paths, and the caller removes the submodule in Git first. 409 is right because the state
of the folder conflicts with the request, and the caller can resolve it and send it again (RFC 9110, section 15.5.10).

## What changed

- **`GitProvider.list_folder(path, ref)`**: every entry under the folder at any depth, `{path: "blob" | "commit"}`. It is
  the same on every provider, and each one says so when its list can be cut:
  - **The Git layer**: `git ls-tree -r`. A partial clone needs no blob for it, and Git never descends through a symlink.
  - **GitHub REST, in the API process**: the Git Trees API, not Contents. Contents stops at 1,000 entries and its
    directory listing does not document a type for a symlink or a submodule; a tree gives each entry's Git type. From the
    commit's root tree (`git/commits/{sha}`), one tree for each part of the path, then the folder's tree with
    `recursive=1`. A `truncated` tree is `IncompleteList`, so a partial delete is never planned.
  - **Gitea**: each subtree through `_tree_entries`, page by page.
  - **FakeGit**: every path under the folder.
- **`plan_delete`** lists the folder at the commit it read and removes each path. It refuses a submodule.
- **`push_branch`** supersedes a delete whose folder gained or lost a path since the plan. Without that, the merge would
  leave the new path, or the plan would not match.
- **`_merged`** needs an empty folder at the merge sha for a delete. This is Fable 2.4: the folder at the merge must be the
  plan's. A path that reached main between the push and the merge holds the request in `sync_failed`.
- **The revert of a create** is a delete, so it lists the whole folder too.
- **The Git layer** removes each path with `git rm` (literal pathspecs, NUL-separated) and stages each written file with
  `git add`. Before, it used `unlink` and `git add --all -- <folder>`.
  - `git rm` removes a symlink itself, never what it points to.
  - It matches nothing beyond a symlink. Measured on git 2.55.0: `a/link/f`, where `a/link` is a symlink, removed nothing.
  - Writes still go through `_inside` (#446).
- **The Gitea stand-in** deletes every planned path that the listing has.

Unchanged, by design (#578): the ETag, the plan's `prev`, the renderer's previous files and the PR's folder comparison
still read the `.yaml` files directly in the folder.

## Not tested

- On CRC, a cluster or a real GitHub or Gitea. The REST listings are tested against MockTransport hosts, shaped by the docs
  quoted above.
- What Argo CD does with leftover manifests. The reasoning against (c) rests on the documentation.
- A submodule through Gitea's or GitHub's REST commit paths: the plan refuses it before a push.
