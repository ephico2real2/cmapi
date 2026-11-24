**Reviewer 1 decision: request changes on PR #622 (`ed3dcf5`).** The new listing fixes the original direct-YAML defect for an unchanged folder. The main blocker is the timing of verification. Both providers can approve a merge that already contains an unremoved file. The worker detects it after main changes, and a subsequent `:retry` can mark that same delete `synced` without reading Git. I confirmed the latter two behaviors with in-memory provider and worker checks.

I ran **8 of the 16 cases** in `test_delete_whole_folder_616.py`, all passing, plus **6 existing provider-read cases**, all passing. Two requested mutations were killed. Prefix matching survived the existing tests I ran. The eight outstanding test IDs are listed below. All local references are relative to the exported `head/`. I made no repository, export, or remote changes. The fixes below are proposed code, not applied patches.

## 1. P1 — A known incomplete delete can pass the last check before merge

**Evidence.** `cmapi/src/cmapi/jobs/pr_checks.py:74–87` reads `tree_files`, then treats a planned path missing from that result as removed. `core/git/base.py:204–206` defines `tree_files` through the direct-manifest `read_folder`. `core/git/workspace.py:567–569` checks the simulated merge using the same direct-manifest projection. The Gitea fallback at `core/git/base.py:243–245` unconditionally sets `result_matches=True`. `jobs/merge.py:76–98` relies on that verdict before calling the host. In an in-memory check, the actual Gitea `merge_check` returned `ok=True` with a late `late.md` in the folder.

**Failure scenario.** The branch deletes every approved path. Before the merge job runs, a person adds `extra/new.json` to main. The Git merge is clean and would preserve that file. The worker can already see the change, but both pre-merge implementations accept it. Only `jobs/merge.py:140–152` detects the leftover, after the namespace manifests have disappeared from main. The decision record explicitly describes this post-merge outcome at `docs/reviews/2026-11-23-issue-616/README.md:109–122`. That outcome is necessary for a race *during* the host merge. It needlessly permits a change visible *before* the host merge.

**Fix.** Keep the direct-manifest comparison for ordinary writes. For a whole-folder delete, check the full path/type inventory on main and emptiness of the proposed result. In `workspace.py`, replace the two assignments at lines 567–568 with:

```python
whole_delete = bool(files) and all(text is None for text in files.values())
base_ok = self._folder(main, folder) == dict(prev)
if whole_delete:
    base_ok = base_ok and self._entries(main, folder) == dict.fromkeys(files, "blob")
    result_ok = not conflicts and not self._entries(tree, folder)
else:
    result_ok = not conflicts and self._folder(tree, folder) == expected
```

In `base.py`, replace the construction of `check` at line 245 with:

```python
base_ok = on_main == dict(prev)
result_ok = True
if files and all(text is None for text in files.values()):
    listed_main, _ = self.list_folder(folder, main)
    listed_head, _ = self.list_folder(folder, head)
    base_ok = base_ok and listed_main == dict.fromkeys(files, "blob")
    result_ok = not listed_head
check = MergeCheck(main, head, (), base_ok, result_ok)
```

In `jobs/pr_checks.py`, immediately after line 87, also make the posted cmapi status reflect a leftover on the PR head:

```python
if cmapi_ok and row.action == "delete":
    listed, _ = ctx.git.list_folder(folder(row.cluster_id, row.namespace), head)
    cmapi_ok = not listed
```

Retain the post-merge check. The GitHub and Gitea merge calls pin the PR head, and neither supplies an expected main SHA (`core/git/github.py:239–244`, `core/git/gitea.py:257–259`).

**Regression test.** This tests the production Gitea fallback without a database. The equivalent workspace case should add `late.json` on main after constructing the delete branch and assert `not ws.merge_check(...).ok`.

```python
def test_merge_check_refuses_a_late_nonmanifest(monkeypatch):
    g = _gitea(RestHost())
    prev = {BASE + "namespace.yaml": "kind: Namespace\n"}
    files = dict.fromkeys(prev)
    head = "d" * 40
    monkeypatch.setattr(g, "read_folder", lambda folder: (prev, HEAD))
    trees = {
        HEAD: {**dict.fromkeys(prev, "blob"), BASE + "late.json": "blob"},
        head: {},
    }
    monkeypatch.setattr(g, "list_folder", lambda folder, ref: (trees[ref], ref))
    assert not g.merge_check(head, BASE, prev, files).ok
```

## 2. P1 — Retrying a failed merge verification can falsely report success

**Evidence.** `jobs/merge.py:149–152` records an incomplete merged delete as `sync_failed`. `routers/requests.py:219–225` sends every such delete retry to `prune`. `jobs/watch_sync.py:219–228,254–259` checks whether the live Namespace exists and can transition straight to `synced`. I invoked the production `prune` function with a failed delete, an absent live Namespace, and a Git provider reporting a leftover. It emitted **`synced`, with zero calls to `list_folder`**.

**Failure scenario.** The merge leaves `extra/configmap.yaml`. An operator retries after the Namespace has disappeared. The request releases its failure state while the manifest that caused the failure remains in Git. The existing test stops at the first `sync_failed` response (`tests/service/test_delete_whole_folder_616.py:135–154`).

**Fix.** At `jobs/watch_sync.py:225`, before consulting the live cluster, recheck the current desired state on retry. This also allows recovery when an operator has repaired main.

```python
if retrying:
    if not row.merge_sha:
        return _refuse(repo, jobs, row, job, "the delete has no verified merge SHA")
    where = folder(row.cluster_id, row.namespace)
    remaining, main = ctx.git.list_folder(where)
    if remaining:
        return _refuse(
            repo, jobs, row, job,
            f"the namespace folder on main at {main[:8]} still contains "
            f"{sorted(remaining)[0]!r}",
        )
```

`_refuse` records the reason and leaves a `sync_failed` request held (`jobs/watch_sync.py:158–164`). A Git read error must propagate through the worker’s error path.

**Regression test.** Append this to the existing late-merge-file test, after its first `sync_failed` assertion:

```python
from test_flow import OPAL

kube.objects.pop(("Namespace", "", "payments-dev"), None)
response = client.post(
    f"/api/v1/requests/{rid}:retry",
    headers=auth(keys, "opal", **OPAL),
)
assert response.status_code == 200
run_jobs(ctx)
view = client.get(
    f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)
).json()
assert BASE + "late.md" in git_.branches["main"]
assert view["status"] == "sync_failed"
```

## 3. P1 — The worker discards Git object types and builds on a different read of main

**Evidence.** The planner refuses a `commit` entry at `core/pipeline.py:213–222`. The push job compares only key sets at `jobs/push_branch.py:29–34`. The `BranchRequest` has no checked base SHA (`core/git/base.py:59–69`). Workspace fetches main again at `core/git/workspace.py:495–499` and Gitea resolves it again at `core/git/gitea.py:107–110`. Gitea checks only `path in listed` when emitting a delete (`core/git/gitea.py:127–134`).

**Failure scenario.** A planned non-YAML blob becomes a gitlink at the same path. The set of names and the direct YAML contents are unchanged. The push job accepts it. Gitea builds a delete operation for the current object. Its pinned implementation checks the supplied object ID and removes the index entry. That can leave the submodule registration in the root `.gitmodules`. On the workspace path, `git rm` can stage the root file, although the staged-path guard should then prevent the commit (`core/git/workspace.py:449–463`). Merely changing the key-set comparison leaves a second window between checking main and selecting the branch base. [Gitea 1.25.5 deletion implementation](https://github.com/go-gitea/gitea/blob/v1.25.5/services/repository/files/update.go#L241-L265) · [Git submodule removal semantics](https://git-scm.com/docs/git-rm#_submodules)

**Fix.** Carry the SHA the job actually checked into the provider. These are the complete changes needed to select the fresh branch base and check types, in addition to the pre-merge checks in finding 1:

```python
# core/git/base.py — add at the end of BranchRequest
checked_base: str | None = None
```

```python
# jobs/push_branch.py — import
from dataclasses import replace

# Replace the moved assignment.
moved = False
if row.action == "delete":
    listed, _ = ctx.git.list_folder(folder(row.cluster_id, row.namespace), main)
    moved = listed != dict.fromkeys(row.plan["files"], "blob")

# Replace the req assignment, after the existing superseded branch.
req = branch_request(ctx, row)
if row.action == "delete":
    req = replace(req, checked_base=main)
```

```python
# core/git/workspace.py — replace main = self.fetch_main() in push_branch.
main = self.fetch_main()
if req.checked_base is not None:
    self._need(req.checked_base)
    main = req.checked_base
```

```python
# core/git/gitea.py — replace the base assignment in push_request_branch.
base = req.checked_base or self.branch_head(self.default_branch)

# Replace the reads immediately after creating the branch from base.
current, _ = self.read_folder(req.folder, base)
listed, _ = self.list_folder(req.folder, base)
```

For Gitea, use tree-derived object IDs at that base for the delete operations, or use the encoded lookup in finding 5 against the freshly created request branch. The latter retains the existing per-file SHA check. Keep the full-head check from finding 1 for branch adoption.

**Regression test.** The following extends the existing same-provider flow to cover type changes at an approved name:

```python
def test_blob_replaced_by_gitlink_supersedes_delete(world):
    client, ctx, git_, kube, validator, keys = world
    rid = _delete(world, _created_with_extra_files(world))
    path = BASE + "README.md"
    git_.branches["main"][path] = "submodule commit"
    git_.submodules.add(path)
    git_._sha("main")
    _approve(world, rid)
    run_jobs(ctx)
    result = client.get(
        f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)
    ).json()
    assert result["status"] == "superseded"
    assert path in git_.branches["main"]
```

For the separate base-selection window, assert in the Gitea transport fixture that `POST /branches` receives the checked SHA even when `GET /branches/main` now returns a newer one.

## 4. P2 — GitHub’s 1,000-entry Contents limit still affects delete planning

**Evidence.** The recursive inventory uses Trees correctly. However, `plan_delete` first calls `read_folder`, requires `namespace.yaml`, and builds the ETag and `prev` from that read (`core/pipeline.py:476–483,558–562`). In the API process, `core/git/github.py:70–79` issues one Contents request and accepts the returned array as complete. GitHub says, “This API has an upper limit of 1,000 files for a directory.” It directs larger reads to Trees. Contents directory pagination is not a documented solution. [GitHub repository Contents](https://docs.github.com/en/rest/repos/contents#get-repository-content)

**Failure scenario.** If the capped response omits `namespace.yaml`, a managed namespace gets a 404 before recursive listing runs. If it omits another direct manifest, the plan can have a complete removal inventory and incomplete `prev`. The workspace worker can then supersede an unchanged plan at `jobs/push_branch.py:34`. I found no evidence that a `truncated:true` GitHub Trees response itself results in partial deletion.

**Fix.** Preserve the common Contents read and its existing direct-file behavior. When its directory response reaches the limit, resolve that directory on the pinned commit and read only direct regular `.yaml` blobs. Insert this immediately after `entries = r.json()` at `core/git/github.py:74`:

```python
if isinstance(entries, list) and len(entries) >= 1000:
    directory = path.strip("/")
    commit = self._call("read_folder", "GET", f"{self._repo()}/git/commits/{head}")
    if commit.status_code != 200:
        raise GitUnavailable(f"read commit {head[:8]}: HTTP {commit.status_code}")
    oid = commit.json()["tree"]["sha"]
    for part in filter(None, directory.split("/")):
        entry = next((e for e in self._tree(oid) if e["path"] == part), None)
        if entry is None or entry["type"] != "tree":
            raise GitUnavailable(f"cannot resolve directory {directory!r} at {head[:8]}")
        oid = entry["sha"]

    prefix = directory + "/" if directory else ""
    for entry in self._tree(oid):
        if (entry["type"] != "blob" or entry["mode"] not in ("100644", "100755")
                or not entry["path"].endswith(".yaml")):
            continue
        blob = self._call("read_file", "GET", f"{self._repo()}/git/blobs/{entry['sha']}")
        if blob.status_code != 200:
            raise GitUnavailable(f"read blob {entry['sha']}: HTTP {blob.status_code}")
        files[prefix + entry["path"]] = base64.b64decode(blob.json()["content"]).decode()
    return files, head
```

**Regression test.** This fixture deliberately puts the managed manifest beyond the Contents response:

```python
def test_github_capped_contents_still_reads_the_namespace():
    class CappedContents(RestHost):
        def __call__(self, request):
            if request.url.path.endswith("/contents/" + FOLDER_PATH):
                return httpx.Response(200, json=[
                    {"type": "file", "name": f"{i:04}.txt", "path": BASE + f"{i:04}.txt"}
                    for i in range(1000)
                ])
            return super().__call__(request)

    entries = {BASE + f"{i:04}.txt": ("blob", "100644") for i in range(1000)}
    name = BASE + "namespace.yaml"
    entries[name] = ("blob", "100644")
    files, sha = _github(CappedContents(entries)).read_folder(BASE, HEAD)
    assert (files, sha) == ({name: f"text of {name}\n"}, HEAD)
```

## 5. P2 — Gitea misaddresses valid filenames and recursively scans ordinary writes

**Evidence.** `core/git/gitea.py:220–222` interpolates the raw repository path into a URL. Using the exported adapter and its HTTP transport, `notes#1.md` reached the host as `notes`, `q?.md` as `q`, and `percent%23.md` as `percent#.md`. The commit operation still uses the original name at `core/git/gitea.py:133`. A missing or mismatched SHA prevents the delete. Since the request branch is created first, retry can also encounter an unmarked base commit and refuse it as foreign (`core/git/gitea.py:111–126`).

Separately, line 128 scans every subtree for **every** request, including a patch or expiry extension with no removals. An unrelated subtree read failure can now prevent an ordinary manifest update. It also adds one Contents request per removed path even though the tree response already contains each object ID (`core/git/gitea.py:94–98,130–136`). These are observable changes to the Gitea write path.

**Fix.** A small patch is sufficient for URL correctness: import `quote`, encode the repository-relative path, and check the response. For the unnecessary traversal, direct managed removals are already covered by `current`. Only removals outside that projection require listing.

```python
from urllib.parse import quote

def _blob_sha(self, path: str, ref: str) -> str:
    encoded = quote(path, safe="/")
    r = self._call("read_file", "GET", f"{self._repo()}/contents/{encoded}",
                   params={"ref": ref}, ok=(200,))
    if r.status_code != 200:
        raise GitUnavailable(f"read file {path!r}: HTTP {r.status_code}")
    return r.json()["sha"]
```

```python
# Replace the unconditional list_folder call at line 128.
needs_inventory = any(
    text is None and path not in current for path, text in req.files.items()
)
listed = self.list_folder(req.folder, base)[0] if needs_inventory else current
```

A tree-entry implementation that carries the already-returned SHA into `ops` also avoids the per-deletion GET. I verified the encoded lookup against the mock transport with a filename containing `#`, `?`, and `%`.

**Regression tests.**

```python
def test_gitea_reads_the_sha_of_the_literal_name():
    path = BASE + "notes#1?%.md"
    git = _gitea(RestHost({path: ("blob", "100644")}))
    assert git._blob_sha(path, HEAD) == _oid("blob", path)


def test_gitea_plain_update_never_needs_recursive_inventory(monkeypatch):
    git = _gitea(RestHost())
    monkeypatch.setattr(git, "list_folder",
                        lambda *args: pytest.fail("unnecessary recursive read"))
    path = BASE + "namespace.yaml"
    req = BranchRequest(
        "CRC", "req-1", BASE, "hash", "update",
        {path: "new text\n"}, {path: f"text of {path}\n"},
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    git.push_request_branch(req)
```

## 6. P2 — Workspace approves a filename that its push validator rejects

**Evidence.** `core/git/workspace.py:327–336` parses NUL-delimited Git names, so a filename containing a newline enters the removal inventory intact. `core/git/transport.py:102–106` rejects newlines for every path. `core/git/workspace.py:393–399` applies that check to deletes, before the NUL-delimited literal `git rm` at lines 446–451. I confirmed `_check_files` raises `ValueError` for an in-folder multiline name. Git documents that with `--pathspec-file-nul`, “all other characters are taken literally (including newlines and quotes).” [Git `rm`](https://git-scm.com/docs/git-rm#Documentation/git-rm.txt---pathspec-file-nul)

**Failure scenario.** A namespace containing a multiline notes filename has a successful dry run listing that path, but the worker cannot build the approved branch.

**Fix.** Keep traversal checks for every operation and permit newlines only for removal operands:

```python
# core/git/transport.py
def check_path(path: str, *, removal: bool = False) -> None:
    parts = path.split("/")
    if (not path or path.startswith("/") or "\0" in path
            or ("\n" in path and not removal)
            or any(p in ("", ".", "..") or p.lower() == ".git" for p in parts)):
        raise ValueError(f"{path!r} is not a repository path cmapi writes")
```

```python
# core/git/workspace.py — replace _check_files
def _check_files(self, req: BranchRequest) -> str:
    folder = req.folder.strip("/")
    check_path(folder)
    for path, value in req.files.items():
        check_path(path, removal=value is None)
        if not path.startswith(folder + "/"):
            raise ValueError(f"{path} is outside the request's folder {folder}")
    return folder
```

**Regression test.**

```python
def test_multiline_git_name_is_a_valid_removal():
    from types import SimpleNamespace

    req = SimpleNamespace(folder=BASE, files={BASE + "notes\n2026.txt": None})
    assert GitWorkspace._check_files(None, req) == BASE.rstrip("/")
    req.files = {BASE + "../notes\n2026.txt": None}
    with pytest.raises(ValueError):
        GitWorkspace._check_files(None, req)
```

There is a distinct representation limit: `_entries` decodes the entire listing as strict UTF-8 (`core/git/workspace.py:331`). An arbitrary non-UTF-8 Git name therefore raises before a plan can be represented. I did not test a non-UTF-8 repository or establish a lossless public JSON representation for such names.

## 7. P2 — Revert can claim to restore a folder after restoring only its direct manifests

**Evidence.** The public revert contract promises to restore the folder as it was before the plan (`routers/requests.py:232–241`). A recursive delete persists all removal *names* but only direct-manifest *contents* (`core/pipeline.py:476–483,502–505`). The revert reconstructs writes solely from `row.plan["prev"]` and records the original request as reverted (`jobs/open_pr.py:69–86,93–109`).

**Failure scenario.** A merged delete removed `extra/configmap.yaml`, a binary, and a symlink. Prune confirmation subsequently fails. The operator requests a revert. The new request can restore `namespace.yaml` while omitting all three other entries. Neither the original bytes nor the symlink mode is in `prev`.

**Fix.** A lossless automatic revert needs a Git-tree restore from the recorded pre-delete revision, including modes and blob IDs. The present `BranchRequest.files` accepts only text or `None` (`core/git/base.py:59–69`). A small safe fix for this PR is to refuse the specifically unrepresentable revert before recording or queuing it, leaving the original request available for operator recovery. Insert after the `merge_sha` guard at `routers/requests.py:247–251`:

```python
if row.action == "delete":
    restore_missing = sorted(set(row.plan["files"]) - set(row.plan.get("prev") or {}))
    if restore_missing:
        raise Problem.conflict(
            "invalid-transition",
            f"{request_id} removed Git entries that this revert cannot restore. "
            f"Restore the namespace folder from the recorded Git base {row.base_sha}.",
            paths=restore_missing,
        )
```

This is a refusal fix for the demonstrated partial revert. It does not implement automatic restoration of binary files or modes.

**Regression test.** Append this to the existing failed-merge test at `tests/service/test_delete_whole_folder_616.py:154`, whose original plan contains `EXTRA`:

```python
from test_flow import OPAL

response = client.post(
    f"/api/v1/requests/{rid}:revert", headers=auth(keys, "opal", **OPAL)
)
assert response.status_code == 409
assert set(EXTRA) <= set(response.json()["paths"])
view = client.get(
    f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)
).json()
assert view["status"] == "sync_failed"
```

## Confirmed behavior and provider limits

| Review point | Evidence and conclusion |
|---|---|
| Namespace containment | **Confirmed for valid Git tree responses.** `core/pipeline.py:470–476` selects a registered writable cluster. `core/pipeline.py:201–205` and `core/naming.py:22,30–32` require a full lowercase ASCII label. I checked slash, `..`, uppercase, and accented inputs. All four failed validation. `core/render/manifests.py:61–62,226–230` includes the final `/` in the renderer boundary. GitHub and Gitea walk exact path components and descend only into trees (`core/git/github.py:103–111`, `core/git/gitea.py:84–98`). A client does not supply the removal list. I found no namespace-input route that selects `payments-dev2`, a root file, or a symlink target. |
| Case and Unicode | **Confirmed at the tree and plan level.** The comparisons above use exact strings without case folding or Unicode normalization. Workspace also compares staged Git names with the approved names before commit (`core/git/workspace.py:459–466`). I did not run a checkout on a volume containing case- or normalization-colliding filenames, so I cannot certify checkout availability there. |
| GitHub truncation | **Confirmed fail-closed for `truncated:true`.** “The limit for the `tree` array is 100,000 entries with a maximum size of 7 MB when using the `recursive` parameter.” The code checks truncation on every ancestor response and on the recursive namespace tree (`core/git/github.py:85–91,103–111`). `IncompleteList` is a `GitUnavailable`, which the planner maps to 502 (`core/git/base.py:30–36`, `core/pipeline.py:213–216`). Both truncation tests passed. [GitHub Git Trees](https://docs.github.com/en/rest/git/trees#get-a-tree) |
| Gitea pagination | **Confirmed for the documented protocol.** The chart pins 1.25.5 (`deploy/helm/cmapi-git/values.yaml:4–7`). The API says the flag “will be true if there are still more items after this page, false if the last page”. `page` and `per_page` are separate parameters. The adapter requests successive pages and leaves page size to the server (`core/git/gitea.py:39–50`). The pinned server applies its configured default and computes truncation from the end index. The existing successful two-page case also passed (`tests/service/test_github_read_folder_one_commit.py:106–113`). The adapter checks page identity only when `truncated` is true, so this conclusion assumes a conforming server on the final page. [Gitea Trees API](https://docs.gitea.com/api/1.25/operations/get-tree/) · [Gitea 1.25.5 implementation](https://github.com/go-gitea/gitea/blob/v1.25.5/services/repository/files/tree.go#L76-L97) |
| One commit and request size | **Confirmed by code.** Workspace feeds paths over stdin and creates one commit (`core/git/workspace.py:446–466`). GitHub delegates its write to workspace (`core/git/github.py:128–129`) and enforces a **2 GB push limit**. Gitea sends one `files` array in one POST (`core/git/gitea.py:129–145`), and the pinned server writes one tree and one commit. The Gitea request model marks `files` required and declares `MaxSize(500)` on each `path`. I found no published aggregate operation-count or body-byte maximum for this endpoint. A deployment’s accepted HTTP body size was not measured. An unsuccessful POST is surfaced as an error, though the separately created branch can remain. [GitHub repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits#activity) · [Gitea multiple-file operation](https://docs.gitea.com/api/1.25/operations/repo-change-files/) · [Gitea request model](https://github.com/go-gitea/gitea/blob/v1.25.5/modules/structs/repo_file.go#L63-L85) · [Gitea commit implementation](https://github.com/go-gitea/gitea/blob/v1.25.5/services/repository/files/update.go#L240-L284) |
| Gitlinks, symlinks, executables | **Confirmed at planning time.** Mode `160000` is a commit entry. Modes `120000` and `100755` are blobs. The planner returns 409 and names the gitlinks (`core/pipeline.py:217–222`). RFC 9110 says, “This code is used in situations where the user might be able to resolve the conflict and resubmit the request.” Removing the gitlink in Git is such a resolution. Deleting a symlink as a Git entry is correct. Workspace passes its literal path to `git rm` (`core/git/workspace.py:443–451`). Root `.gitmodules` is absent from the planned paths. Git’s rule about staging `.gitmodules` is conditional on the corresponding section existing. The object-type race in finding 3 qualifies any stronger assurance. [RFC 9110 §15.5.10](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.10) · [GitHub tree entry modes](https://docs.github.com/en/rest/git/trees#create-a-tree) · [Git `rm` submodules](https://git-scm.com/docs/git-rm#_submodules) |
| Dry run and approval | **Confirmed for a single snapshot.** `core/pipeline.py:483,502–505` lists at the SHA used to read `prev` and labels each removal. `core/pipeline.py:75–86,520–523` exposes the changes and stores the plan, base SHA, and hash. `core/views.py:30` and `core/render/manifests.py:233–239` show the removals on the change request. `jobs/delivery.py:66–82` uses the stored delete map and verifies the hash. Approval identifies removal **paths**. An intervening content-only edit to a non-manifest at the same name does not change that map or the direct-manifest ETag (`core/pipeline.py:100–113`, `jobs/push_branch.py:29–34`). A dry run and a later submission are independent planning calls and can observe different inventories. |
| Other callers | **Confirmed for the read contract.** Workspace and Gitea still return direct regular `.yaml` manifests (`core/git/workspace.py:299–319`, `core/git/gitea.py:52–77`), and GitHub retains its previous Contents filter (`core/git/github.py:67–79`). Create, patch, and expiry planning continue to use this projection (`core/pipeline.py:261–269`, `plugins/namespaces/router.py:330,382`). The Gitea push-path regression in finding 5 prevents a blanket claim of unchanged behavior. |
| Issue #623 | **Confirmed that the missing regeneration step is named.** `cmapi/contract/README.md:25–29` gives the dependency install and `npm run api:types`. The script exists at `cmapi-portal-ui/package.json:8`. One documentation detail remains: the generator writes **both** `schema.generated.ts` and `permissions.generated.ts` (`cmapi-portal-ui/scripts/api-types.mjs:51–60`). Step 7 should say “Commit the changed generated files in `../cmapi-portal-ui/src/api/`, including `permissions.generated.ts` when permissions change.” This PR does not change a permission. |

## Mutation results

All mutations were in memory. Counts below refer only to the tests actually run.

| Mutation | Observed result |
|---|---|
| GitHub namespace tree requested non-recursively, `core/git/github.py:111` | **Killed.** 2 failed, 6 passed. Exact recursive inventory failed at `tests/service/test_delete_whole_folder_616.py:335`. The recursive truncation case also failed at line 348. |
| Ignore GitHub `truncated`, `core/git/github.py:89` | **Killed.** 2 failed, 6 passed. Both `truncated` and `walk_truncated` failed to raise at `tests/service/test_delete_whole_folder_616.py:348`. |
| GitHub exact component comparison changed to unbounded prefix matching, `core/git/github.py:106` | **Survived** all 8 REST cases. The fixture’s sibling is `other-dev` at `tests/service/test_delete_whole_folder_616.py:242`. A new assertion with only `payments-dev2` present passed on head and failed on the mutant. |
| Renderer drops the trailing `/` in its prefix comparison, `core/render/manifests.py:230` | **Survived** the existing renderer test at `tests/core/test_render_listquery_config.py:80–83`. A new assertion supplying entries from both `payments-dev` and `payments-dev2` passed on head and failed on the mutant. |

The two measured boundary tests can be added directly:

```python
@pytest.mark.parametrize("make", [_github, _gitea], ids=["github", "gitea"])
def test_longer_sibling_is_not_the_requested_directory(make):
    host = RestHost({FOLDER_PATH + "2/note.md": ("blob", "100644")})
    assert make(host).list_folder(BASE) == ({}, HEAD)


def test_renderer_excludes_longer_sibling(renderer):
    inside = BASE + "ok"
    sibling = FOLDER_PATH + "2/notes"
    entries = {inside: "blob", sibling: "blob"}
    assert renderer.delete("CRC", "payments-dev", entries) == {inside: None}
```

## Coordinator rerun list

All eight IDs below have the prefix `cmapi/tests/service/test_delete_whole_folder_616.py::`. The database connection probe returned **`Operation not permitted`** for `127.0.0.1:55432`. The `world` fixture requires that database (`tests/service/conftest.py:436–445,482`). The `layer` fixture requires it and creates a Git repository (`tests/service/test_git_layer.py:85`). The two remaining standalone tests initialize and push to disposable repositories (`tests/service/gitserver.py:40–54`, `tests/service/test_delete_whole_folder_616.py:206–230`), so I left those to the coordinator under the no-repository/no-push instruction.

```text
test_the_delete_dry_run_lists_every_path_of_the_folder_as_removed
test_a_merged_delete_leaves_nothing_of_the_folder_in_git
test_a_file_added_to_the_folder_after_the_plan_supersedes_the_delete
test_a_folder_that_holds_a_submodule_is_refused_with_its_paths
test_the_merge_check_holds_a_delete_whose_folder_is_not_empty_at_the_merge
test_the_git_layer_removes_every_file_symlink_and_subfolder_of_the_folder
test_the_git_layer_lists_a_submodule_as_a_commit
test_a_removal_named_like_a_pathspec_glob_removes_only_that_file
```

The implementer’s record says “14 tests” at `docs/reviews/2026-11-23-issue-616/README.md:17`. Its own transcript reports **16** at `docs/reviews/2026-11-23-issue-616/test-after.txt:17`, consistent with my pytest selection of 8 passed and 8 deselected. The transcript is the implementer’s run. My results cover the REST mocks, the additional provider-read tests, the reported mutations, and the explicitly identified in-memory checks.

Codex session ID: 01a20b04-bfea-7c70-bd50-7a37b15c4aa8
Resume in Codex: codex resume 01a20b04-bfea-7c70-bd50-7a37b15c4aa8
