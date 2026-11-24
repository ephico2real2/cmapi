# PR #631 (#625, #632): reviewer 2 (Opus 5.5, high)

Reviewed head 4367c93 against base f4c7145, from the export `review-631/`. Reviewer 1: Codex gpt-6.2-astra xhigh (`codex-result.txt`).
Every test ran on the copy `review-631/r2/` (the patched one), on `review-631/r2-outputs/codex/cmapi/` (Codex's fix applied) or on
head. All ran against PostgreSQL 16 on 127.0.0.1:55432, database `cmapi_wt616`, after the gate (`r2-outputs/gate.sh`).

**The patch:** `r2-outputs/fix.diff`. It applies to 4367c93 with `patch -p1 -F0` from the repository root (`r2-outputs/fix-apply-check.txt`). The
patched files are byte-identical to `r2/`.

## The short version

- **Reviewer 1's findings 1 to 5 hold.** Finding 2 is worse than reported. On api.github.com, a file over 1 MB answers 200 with
  `content: ""`, so head reads a large manifest as an **empty string** with no error. The `KeyError` came from Codex's mock.
- **Reviewer 1 missed a sixth defect, measured live.** Version 2022-11-28 lists a **symlink to a file** as `"type": "file"`, and that
  symlink's own read returns the **target's text**. Below the cap, head and Codex's fix read a `.yaml` symlink as a manifest. The
  worker and head's past-cap path skip it. Codex's fix fails the symlink test (`codex-variant.txt`).
- **The fix is simpler than both.** Contents does not say which entry is a symlink, so no change to the per-file Contents read can
  fix this. The patch reads the folder's **tree** at every size, as `workspace._folder`, `list_folder` and Gitea already do.
  - One Contents request (object media type) gives the folder's tree sha.
  - The tree gives each entry's mode.
  - Each regular `.yaml` file is read as a blob.
  - This removes the 1,000-entry branch, `CONTENTS_DIRECTORY_LIMIT` and `_tree_manifests`. It fixes 1 to 6 and costs one more GET
    than head below the cap (M+2 against M+1). Past the cap it costs four fewer than head on a cmapi folder (M+2 against M+6).
- **Results:**

  | Run | Result | Evidence |
  |---|---|---|
  | The targeted suites | 487 passed | `after-targeted.txt` |
  | The full service suite | 2,583 passed, 2 failed | `after-full.txt` |
  | `scripts/doc-citations.py --check` | 0 problems | `doc-citations-r2.txt` |

  Both full-suite failures need `git ls-files` in a Git repository, and the export has none. Neither concerns this change.
  `test_doc_citations.py` passes in full with a `git ls-files` shim. See "Runs".
- **One defect outside this function:** an unquoted branch name in `branch_head`. Its separate patch is
  `r2-outputs/branch-name-quote.diff`, for the coordinator to file.

## Sources (fetched 2026-11-23; saved in `r2-outputs/sources/`)

- **GitHub REST, "Get repository content"**, version 2022-11-28,
  <https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28>. Saved as `contents-2022-11-28.html` and `.txt`.
  - "When listing the contents of a directory, submodules have their "type" specified as "file". Logically, the value should be
    "submodule". This behavior exists for backwards compatibility purposes. In the next major version of the API, the type will be
    returned as "submodule"." (The page for the current version, 2026-03-10, no longer has this sentence; cmapi pins 2022-11-28 at
    `github.py:54`.)
  - "If the content is a symlink and the symlink's target is a normal file in the repository, then the API responds with the
    content of the file. Otherwise, the API responds with an object describing the symlink itself."
  - "application/vnd.github.object+json: Returns the contents in a consistent object format regardless of the content type. For
    example, instead of an array of objects for a directory, the response will be an object with an entries attribute containing
    the array of objects." The "Content Tree" schema requires `sha`, `type`, `path`, `size`, `url`, `git_url`, `html_url`,
    `download_url` and `_links`.
  - "If the requested file's size is: 1 MB or smaller: All features of this endpoint are supported. Between 1-100 MB: Only the raw
    or object custom media types are supported. Both will work as normal, except that when using the object media type, the
    content field will be an empty string and the encoding field will be "none". To get the contents of these larger files, use the
    raw media type. Greater than 100 MB: This endpoint is not supported."
  - "This API has an upper limit of 1,000 files for a directory. If you need to retrieve more files, use the Git Trees API."
  - Status codes: "200 OK, 302 Found, 304 Not modified, 403 Forbidden, 404 Resource not found".
- **GitHub REST, "Get a blob"**, <https://docs.github.com/en/rest/git/blobs?apiVersion=2022-11-28> (`blobs.html`, `.txt`):
  - "The content in the response will always be Base64 encoded."
  - "This endpoint supports blobs up to 100 megabytes in size."
  - The fine-grained token needs "Contents" read, the permission docs/19 already gives the API pod.
  - Status codes: 200, 403, 404, 409, 422.
- **GitHub REST, rate limits** (`ratelimits.html`, `.txt`): "If you exceed your primary rate limit, you will receive a 403 or 429
  response". So a 403 can be transient, which is why the patch raises `GitUnavailable` (retryable), not `PlatformRefused`.
- **RFC 3986, §3.3** (January 2005, <https://www.rfc-editor.org/rfc/rfc3986.txt>, `rfc3986.txt`): "The path is terminated by the
  first question mark ("?") or number sign ("#") character, or by the end of the URI."
- **A correction to my own fetch.** WebFetch's summary said "Directory listings type submodules with `type` set to "submodule"". The
  raw page refutes this for 2022-11-28, and so does the live probe below. I relied only on the raw page and the probe.

### Live probes on api.github.com (unauthenticated, public repositories, header `X-GitHub-Api-Version: 2022-11-28`)

| What | Request | Answer | File |
|---|---|---|---|
| A submodule in a listing | `GET /repos/git/git/contents/?ref=master` | `sha1collisiondetection`: `"type": "file"`, `size: 0`, `download_url: null` | `gitgit-root.json` |
| A submodule's own read | `GET /repos/git/git/contents/sha1collisiondetection?ref=master`, object and default media | `"type": "submodule"`, `submodule_git_url`, no `content` | `gitgit-submodule-*.json` |
| A 1.1 MB file, default media | `GET /repos/torvalds/linux/contents/drivers/gpu/drm/amd/include/asic_reg/nbio/nbio_7_11_5_offset.h` | **200**, `"encoding": "none"`, `"content": ""`, size 1,172,912 | `large-json.json` |
| The same file, object media | the same request | 200, `encoding: none`, `content: ""`, `sha` 759ab11d | `large-object.json` |
| A symlink to a file, in a listing | `GET /repos/torvalds/linux/contents/tools/testing/selftests/powerpc/copyloops` | `copyuser_64.S`: `"type": "file"`, size 45 (the link text), sha f1c418a2 | `symlink-listing.json` |
| The same entry in the tree | `GET .../git/trees/master:tools/testing/selftests/powerpc/copyloops` | mode `120000`, the same sha f1c418a2 | `symlink-tree.json` |
| The symlink's own read, object media | `GET .../contents/tools/testing/selftests/powerpc/copyloops/copyuser_64.S` | `"type": "file"`, `target: null`, **size 11,192**, content = the target's text (`/* SPDX-License-Identifier ...`), sha = the link's own sha f1c418a2 | `symlink-object.json` |
| A symlink to a directory, in a listing | `GET .../contents/scripts/dtc/include-prefixes` | `"type": "symlink"` | `symlink-dir-listing.json` |
| A folder, object media | `GET .../contents/tools/testing/selftests/powerpc/copyloops?ref=master` | `"type": "dir"`, `sha` dd715c11 = the folder's tree sha in its parent tree | `dir-object.json` |
| A folder past the cap, object media | `GET .../contents/include/linux?ref=master` | `"type": "dir"`, sha 9089cf25, **1,000** entries | `big-object.json` |
| The same folder's tree | `GET .../git/trees/9089cf25...` | **1,615** entries, `truncated: false` | `big-tree.json` |
| The repository root, object media | `GET /repos/git/git/contents/?ref=master` | `"type": "dir"`, `sha` 7dc68783 | `root-object.json` |

The cap probe proves the design end to end on the real host. Contents returned 1,000 entries and the folder's tree sha. That tree
returned all 1,615 entries, untruncated.

## Ruling on each finding

`_call` (base.py:161-184) takes `ok=` and passes `**kw` to `httpx.Client.request`. So `headers=` works per request, and httpx
merges it over the client's headers: Authorization and `X-GitHub-Api-Version` are still sent. A status outside `ok` is returned,
logged as `outcome=refused` with the redacted host text, and not raised. 429 and 5xx raise `GitUnavailable`. Checked in code, not
assumed.

Each "before" is a test run on unpatched head 4367c93 (`r2-outputs/before-head.txt`: 10 failed, 15 passed). Each "after" is a run on
`r2/` (`after-targeted.txt`: all pass).

| # | Reviewer 1 | Ruling | Test (in `test_github_read_folder_632.py`) | Before (head) | After |
|---|---|---|---|---|---|
| 1 | High: a refused listing (403) reads as a missing namespace; a file 403 raises `KeyError` | **Confirmed.** Head's `ok=(200, 404)` lets a 403 fall through to `return {}, head` (github.py:75-85). The per-file call has the default `ok`, so a 403 body has no `content`. | `test_a_refused_listing_is_not_a_missing_folder`, `test_a_refused_file_read_raises_git_unavailable` | `DID NOT RAISE`; `KeyError: 'content'` | pass |
| 2 | Medium: a large manifest is readable only at the cap | **Confirmed and widened: High.** Live, a file over 1 MB answers 200 with `content: ""` with either media type. So head returns `""` for it: **a silent empty manifest**, not a `KeyError` (that came from Codex's mock answering 403). An empty `namespace.yaml` makes `namespace_doc` return None (pipeline.py:558-561): the namespace reads as absent, and the etag changes. | `test_a_manifest_past_1_mb_is_read_whole[below-cap]`, `[past-cap]` | `{'.../namespace.yaml': ''}` | pass |
| 3 | Medium: a `.yaml`-named submodule breaks a read below the cap | **Confirmed live** (git/git's `sha1collisiondetection`). | `test_only_regular_..._manifests[below-cap-submodule]`, `[past-cap-submodule]` | `KeyError: 'content'` | pass |
| 4 | Medium: `#` or `?` in a name is not encoded in the URL | **Confirmed and widened.** `%` also breaks the read, and silently: httpx keeps a valid escape. `x%41.yaml` is requested as `xA.yaml`, which reads a **sibling's** text when one exists (probe output below). A folder name with these characters is cut too. | `test_reserved_characters_in_names_stay_in_the_path` (`a#b?.yaml`, `x%41.yaml` beside `xA.yaml`), `test_reserved_characters_in_the_folder_stay_in_the_path` | `KeyError: 'content'`; `({}, …)` | pass |
| 5 | Low: the cap test lets a mutant without the mode filter survive | **Confirmed.** The symlink cases kill it at both sizes (mutant `no-mode-filter`: 2 failed). | `test_only_regular_..._manifests[*-symlink]` | (see 6) | pass |

The httpx probe behind finding 4 (httpx 0.28.1, `r.url.raw_path` against `r.url.path`):

```
/contents/d/a#b?.yaml unquoted  -> raw /repos/o/r/contents/d/a?ref=H                (the path ends at "#")
/contents/d/x%41.yaml unquoted  -> raw .../d/x%41.yaml, decoded path .../d/xA.yaml  (the sibling)
quote(...)                      -> raw .../d/a%23b%3F.yaml, .../d/x%2541.yaml       (each name kept)
```

### Codex's full fix, run

Codex's fix and its 7 tests were applied verbatim to `r2-outputs/codex/cmapi/` and run with my tests (`codex-variant.txt`: 4
failed, 28 passed):

- **Codex's own 7 tests pass**, and so do the head 625 and one-commit tests.
- **It fails `[below-cap-symlink]`.** The read returns `link.yaml` with b.yaml's text: finding 6.
- It also fails two tests that check the design difference, not a defect in Codex's fix:
  - `test_a_file_path_is_not_a_folder`: Codex keeps head's file-path read.
  - `test_a_pinned_read_costs_...`: a Contents call per file.
- Codex's mock does not model the object form of a folder. So its tests cannot drive the patched code as written; the cases they
  cover are in `test_github_read_folder_632.py`.
- Codex's mock also answered a file over 1 MB with 403 and typed a file symlink `"symlink"`. **Real GitHub does neither** (the probes
  above). That is how its run missed finding 6 and understated finding 2.

## What reviewer 1 missed

**6. High: below the cap, a `.yaml` symlink to a file is read as a manifest with its target's text.**

- **Where:** head `github.py:81-84`, and Codex's fix in the same place.
- **What GitHub does (measured live, above):**
  - The 2022-11-28 listing types a symlink to a file `"file"`.
  - Its read returns the target's content and the link's own sha.
  - No field says it is a symlink: `target` is null.
- **What the others do:**
  - The worker skips mode 120000 (`workspace.py:299-309`).
  - Head's past-cap path skips it (`github.py:104`).
- **The effect:** the API process (plan, etag, `GET .../namespaces/{ns}`) and the worker (`push_branch`, `merge_check`) see
  different folders. A `.yaml` symlink can point at another namespace's manifest, for example `../other-dev/namespace.yaml`. Its
  text then enters this namespace's plan.
- **Why no Contents-based fix works:** Contents gives no documented field to tell the link apart. Only the sizes differ (45 in the
  listing, 11,192 in the read), and that is undocumented.
- **The fix:** read entries from the tree, where the mode says it.
- **Test:** `test_only_regular_yaml_files_directly_in_the_folder_are_manifests[below-cap-symlink]`. Before, on head and on Codex's
  fix: `link.yaml` read with `text of .../b.yaml`. After: passes.

**7. Low: the worker's comment rests on a refuted premise.** `workspace.py:306` reads "Regular files only, as GitHub's contents API
types them "file"". GitHub types both a submodule and a file symlink `"file"`. The patch corrects the comment only; the code is
unchanged.

**8. A changed contract, kept deliberately: a file path.**
- Head's `read_folder` given a file path returned that one file.
- The worker returns `{}`: `git ls-tree <ref> -- <file>/` lists nothing.
- The patch returns `{}` for any non-directory, which matches the worker.
- No caller passes a file path: each passes `folder(cluster_id, ns)` (manifests.py:61-62), which ends in `/`.
- Test: `test_a_file_path_is_not_a_folder`.

## The final code (`cmapi/src/cmapi/core/git/github.py`, from `fix.diff`)

```python
from urllib.parse import quote
```

```python
    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        """The regular .yaml files directly in path at ref, read from the folder's tree as workspace._folder reads them (#625,
        #632). Not from the Contents listing: version 2022-11-28 lists a submodule and a symlink to a file as "file", reads
        that symlink as its target's text, lists at most 1,000 entries, and gives no content for a file past 1 MB. A tree
        types each entry by its mode, and a blob read holds up to 100 MB. Contents still finds the folder in one request: its
        object form carries the folder's tree sha (REST docs, Repository contents and Git blobs, fetched 2026-11-23)."""
        if self.workspace is not None:
            return self.workspace.read_folder(path, ref)
        head = self._folder_head(ref)
        directory = path.strip("/")
        # A path is data in the URL: "#" or "?" would end it (RFC 3986, section 3.3), and "%41" would read as "A".
        r = self._call("read_folder", "GET", f"{self._repo()}/contents/{quote(directory)}", params={"ref": head},
                       headers={"Accept": "application/vnd.github.object+json"}, ok=(200, 404))
        if r.status_code == 404:
            return {}, head
        if r.status_code != 200:                 # 403 is a refusal or a rate limit (REST docs), never a missing folder
            raise GitUnavailable(f"read folder {directory} at {head[:8]}: HTTP {r.status_code}")
        found = r.json()
        if found["type"] != "dir":               # a file, symlink or submodule: git ls-tree of "<path>/" lists nothing either
            return {}, head
        prefix = f"{directory}/" if directory else ""
        return {prefix + e["path"]: self._blob_text(e["sha"]) for e in self._tree(found["sha"])
                if e["type"] == "blob" and e["mode"] in ("100644", "100755") and e["path"].endswith(".yaml")}, head

    def _blob_text(self, sha: str) -> str:
        """GET git/blobs/{sha}: "The content in the response will always be Base64 encoded", for blobs up to 100 MB (REST docs,
        Git blobs, fetched 2026-11-23). Strict UTF-8, as the worker decodes a manifest."""
        b = self._call("read_file", "GET", f"{self._repo()}/git/blobs/{sha}")
        if b.status_code != 200:
            raise GitUnavailable(f"read blob {sha[:8]}: HTTP {b.status_code}")
        return base64.b64decode(b.json()["content"]).decode()
```

`CONTENTS_DIRECTORY_LIMIT` and `_tree_manifests` are removed; nothing else referenced them. The module docstring's endpoint list
adds `/git/commits/{sha}`, which `list_folder` already used but the list left out, and `/git/blobs/{sha}`. `_tree` is unchanged.

The other changes in the patch:
- **workspace.py:306:** the corrected comment (finding 7).
- **test_github_read_folder_contents_cap_625.py:** `CappedContents` also answers the object form, with the folder's tree sha and the
  same 1,000 rows. It still fails on base and passes after.
- **test_github_read_folder_one_commit.py:** the GitHub mocks answer Contents in object form, with trees and blobs by sha. Every
  assertion is unchanged. The unreachable `else` branch, a per-file Contents read that no provider makes any more, now fails the
  test instead of answering.
- **test_github_read_folder_632.py (new):** a GitHub Contents mock built from the live probes, and 18 tests.

### Design choice, recorded

| Option | GETs, pinned ref, M manifests, depth-4 cmapi folder | Fixes 1-4 | Fixes 6 (symlink) | Code |
|---|---|---|---|---|
| Head (PR #631) | below cap M+1; past cap M+6 | no | no (below cap) | 2 paths |
| Codex's fix | M+1, plus 1 per file over 1 MB; past cap M+6 | yes | **no** | 2 paths and a submodule check |
| Tree only, walked from the commit (like `list_folder` and Gitea) | M+6 | yes | yes | 1 path |
| **Contents object form, then that folder's tree (this patch)** | **M+2** | yes | yes | 1 path |

- **Why it costs M+2:** `test_a_pinned_read_costs_the_folder_its_tree_and_one_blob_per_manifest` asserts exactly contents, trees,
  blob, blob for M=2, at both sizes.
- **Why the cost matters:** `GET /namespaces/{ns}` reads the folder on every call (router.py:233), and every GitHub request counts
  against the token's rate limit. That rules out the plain walk (M+6).
- **Over-build check:** the patch is shorter than head. It removes one code path and adds no new branch.

## Behaviour preservation

| Caller | Path | Effect of the patch |
|---|---|---|
| `pipeline._read_folder` (pipeline.py:201-207), so create, update, delete and `GET /namespaces/{ns}` | GitHub, API process (no workspace), `ref=None` | Same keys (repository paths) and text for regular `.yaml` files. Changes are the defect fixes only: 403 is now 502 git-unavailable (was "not found"); a file over 1 MB is read whole; a submodule or symlink is not a manifest; reserved characters are read correctly. 404 still gives `({}, head)`. |
| `HostGitProvider.tree_files` (base.py:204-206) | delegates to `read_folder` | Same as above. Its callers (merge.py:141, apply.py:79, pr_checks.py:74) run in the worker, which has a workspace. |
| `HostGitProvider.merge_check` (base.py:249) | GitHub overrides it with the workspace (github.py:164-166) | Not reached for GitHub. |
| Worker: `push_branch`, `open_pr`, `watch_sync`, `pr_checks` | `self.workspace.read_folder` (github.py:72-73) | **Unchanged**; only the comment at workspace.py:306. |
| `list_folder`, `_tree` | not edited | Unchanged; the #616 delete tests pass (`after-targeted.txt`). |
| `_call` | not edited | Unchanged. |
| Gitea | not edited | Unchanged; its two tests in the one-commit module pass. |
| Error contract | `IncompleteList` from `_tree` and `GitUnavailable` from a blob read: both subclasses `pipeline._read_folder` already maps to 502 | No new exception types. A non-UTF-8 manifest still raises `UnicodeDecodeError`, as head and the worker do. |
| Redaction (#424) | `test_git_host_redaction_424.py` | Passes. The new error text holds no host text; `_call` logs the redacted host message on a refusal. |
| Metrics label | the tree read is labelled `op="list_folder"` by `_tree` | Same as head's past-cap path. Not changed, to keep `_tree` untouched. |

## Mutants (on a separate copy, `r2-outputs/mutants/`; `mutants.txt`, `mutant-*.txt`)

Each mutant was run against the 632, 625 and one-commit tests (25 tests). Every one was killed:

| Mutant | Result |
|---|---|
| no-mode-filter | 2 failed |
| no-quote | 1 failed |
| 403-as-missing | 1 failed |
| no-object-accept | 16 failed |
| no-dir-check | 1 failed |
| no-yaml-suffix | 8 failed |
| no-prefix | 15 failed |

## Runs

| Run | Copy | Result | File |
|---|---|---|---|
| Before, 632 + 625 + one-commit | head | 10 failed, 15 passed | `before-head.txt` |
| Codex's fix + its 7 tests + mine | `codex/cmapi` | 4 failed, 28 passed | `codex-variant.txt` |
| After, targeted (below) | `r2` | **487 passed** | `after-targeted.txt` |
| After, whole service suite, once | `r2` | **2,583 passed, 2 failed**, 32 min 20 s | `after-full.txt` |
| `test_doc_citations.py` again, with a `git -C <root> ls-files` shim (`r2-outputs/shim/git`; every other git command goes to the real git) | `r2` | **12 passed** | `after-doc-citations-test.txt` |
| `scripts/doc-citations.py --check` with the shim | `r2` | 0 problems, exit 0 (head too) | `doc-citations-r2.txt`, `doc-citations-head.txt` |

The targeted run covered the 632, 625 and one-commit tests, `test_delete_whole_folder_616.py`, `test_git_layer.py`,
`test_github_statuses.py`, `test_git_credentials_review.py`, `test_git_host_redaction_424.py` and `test_api_standard.py`.

The two full-suite failures are environmental: the export has no `.git`.
- `test_doc_citations.py::test_each_citation_...` runs `git -C <root> ls-files`. It passes with the shim: the module's 12 tests pass.
- `test_third_pass_converged.py::test_every_shell_script_...` runs `git ls-files -s examples deploy`, which reads index modes that a
  shim cannot fake. The patch touches no file under examples/ or deploy/, and `find examples deploy -name '*.sh' ! -perm -u+x` lists
  none.

No `docs/01` or `docs/02` text changes, so there is no `LIVE-DOC-EDITS.md`. docs/19:39 already lists "Contents: Read" for the API
pod's reads, and the Trees and Blobs endpoints need that same permission.

## Outside this function: the branch name in `branch_head` (for the coordinator to file)

**Defect.** `GitHubProvider.branch_head` and `GiteaProvider.branch_head` put the branch name into the URL path unquoted (github.py:68,
gitea.py:36). Git accepts `#` and `%` in a branch name (`git check-ref-format --branch 'release#2'` exits 0; `'a?b'` exits 128).
A configured default branch `release#2` requests `/branches/release` (RFC 3986 §3.3), which is **another branch's head**. Probe on
head: `GitHubProvider ... /repos/o/r/branches/release`. `settings.git_default_branch` (settings.py:42) is not validated. Gitea
shows the same pattern at `delete_branch` (gitea.py:194), `changed_paths` (gitea.py:222) and `protect_default_branch`
(gitea.py:287).

**Fix.** `r2-outputs/branch-name-quote.diff` applies with `patch -p1 -F0` **after** `fix.diff`, checked:

```python
# github.py
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{quote(branch)}", ok=(200, 404))
# gitea.py (with: from urllib.parse import quote)
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{quote(branch)}", ok=(200, 404))
        r = self._call("delete_branch", "DELETE", f"{self._repo()}/branches/{quote(branch)}", ok=(204, 404))
        r = self._call("compare", "GET", f"{self._repo()}/compare/{quote(self.default_branch)}...{head}")
            self._call("protect", "PATCH", f"{self._repo()}/branch_protections/{quote(self.default_branch)}", json=body)
```

**Test** (`cmapi/tests/service/test_branch_name_in_url_path.py`):

```python
"""A branch name is data in a URL path. Git accepts "#" and "%" in a branch name (git check-ref-format --branch 'release#2'),
and RFC 3986, section 3.3: "The path is terminated by the first question mark ("?") or number sign ("#") character". Unquoted,
the default branch release#2 read the head of the branch release."""
from __future__ import annotations

import httpx
import pytest

from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider


@pytest.mark.parametrize("branch", ["release#2", "rel%41", "team/main"])
@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
def test_a_branch_name_stays_in_the_path(provider, branch):
    asked = []

    def host(request):
        asked.append(request.url.path)
        return httpx.Response(200, json={"commit": {"sha": "a" * 40, "id": "a" * 40}})

    git = provider("https://h.test", "o/r", "", default_branch=branch)
    git._client = httpx.Client(base_url="https://h.test", transport=httpx.MockTransport(host))
    assert git.branch_head(branch) == "a" * 40
    assert asked == [f"/repos/o/r/branches/{branch}"]
```

| Run | Result | File |
|---|---|---|
| Before (head's `branch_head`) | 4 failed (`release#2` and `rel%41` on both providers), 2 passed (`team/main`) | `branchhead-before.txt` |
| After, with the one-commit and #424 redaction tests | 156 passed | `branchhead-after.txt` |

## Not tested

- **A live GitHub read of a name holding `#`, `?` or `%`.** No public file was at hand. That part rests on RFC 3986 and the httpx
  probe.
- **A live 403**, for a refused token or a rate limit. That part rests on the documented status codes.
- **A file over 100 MB.** The blob endpoint documents 100 MB as its limit, and over it the patch raises `GitUnavailable` on the
  non-200.

## Housekeeping

A Python probe I ran with `PYTHONPATH=src` from `head/cmapi` wrote `__pycache__` under `head/cmapi/src` at 23:07:47. I removed those
5 folders (17 `.pyc` files); `head/` now holds no `.pyc`. No source in `head/` or `base/` was changed, and no Git repository,
worktree or GitHub was touched.
