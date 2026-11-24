## (a) GitHub’s API contract

**Confirmed: PR #631 fixes the reported omission.** The supplied regression failed against `base` and passed against `head`. Its folder contains 1,000 `.txt` files followed by `namespace.yaml`. The Contents response omits the manifest, but the tree contains it. The test checks both the full repository path and the returned commit. `test_github_read_folder_contents_cap_625.py:12–26`, `github.py:74–80`.

All external sources below were fetched on **2026-11-23**. Source and test line numbers refer to the export’s `head/cmapi/` unless marked `base`.

| Question | Verified contract |
|---|---|
| Contents directory cap | **Confirmed.** “This API has an upper limit of 1,000 files for a directory.” A response of exactly 1,000 therefore needs the fallback even though the directory might be complete. [GitHub, Get repository content](https://docs.github.com/en/rest/repos/contents#get-repository-content) |
| Tree truncation | **Confirmed.** GitHub sets `truncated` when it cuts the result. “The limit for the `tree` array is 100,000 entries with a maximum size of 7 MB when using the `recursive` parameter.” I retract the unqualified interpretation that those numbers also specify the limit of each non-recursive request in `_tree_manifests`. [GitHub, Get a tree](https://docs.github.com/en/rest/git/trees#get-a-tree) |
| Blob encoding and size | **Confirmed.** “The `content` in the response will always be Base64 encoded.” “This endpoint supports blobs up to 100 megabytes in size.” cmapi requests JSON at `github.py:52–54`. Base64 describes the transport encoding and gives no guarantee that the decoded bytes are UTF-8. [GitHub, Get a blob](https://docs.github.com/en/rest/git/blobs#get-a-blob) |
| Large files through Contents | **Confirmed.** “To get the contents of these larger files, use the `raw` media type.” For the 1–100 MB range, the documented alternative, `object`, returns empty `content` and encoding `none`. cmapi’s existing small-directory path requests the default JSON representation. `github.py:52–54,83–84`. [GitHub, Get repository content](https://docs.github.com/en/rest/repos/contents#get-repository-content) |

## (b) Equivalence at the boundary

**Confirmed for ordinary regular manifests, including a complete directory of exactly 1,000 entries. Refuted as a general claim.**

- **Keys, bytes, and commit — confirmed.** I ran both algorithms against the **same complete 1,000-entry mock folder**, forcing the Contents branch for one read. Output was `same complete 1000-entry folder, both algorithms equal: True`. Both returned repository-relative `clusters/CRC/namespaces/payments-dev/a.yaml` and `…/b.yaml`, the text `café\n`, and the pinned commit. A separate root-tree read returned `{'run.yaml': 'text of run.yaml\n'}`. `github.py:74–84,91–108`, `base.py:190–202`.
- **Manifest selection in the tree — confirmed.** The fallback reads direct children, accepts blob modes `100644` and `100755`, and checks the case-sensitive suffix `.yaml`. The mixed-entry run included an executable, a `120000` symlink ending in `.yaml`, an uppercase suffix, and a nested manifest. Only the two direct regular manifests appeared. This agrees with the worker’s filter at `workspace.py:299–309`. `github.py:96–105`.
- **Exactly 1,000 versus more than 1,000 — confirmed separately.** The complete-folder run above exercised exactly 1,000 actual children. The PR regression exercised 1,001 actual children and recovered the omitted manifest. The original test alone establishes only the second case. `test_github_read_folder_contents_cap_625.py:16–26`.
- **Regular files only below the cap — refuted.** I retract the claim in `workspace.py:306` that the Contents listing’s `file` type identifies regular files. The provider pins `2022-11-28` at `github.py:54`. That version says, “When listing the contents of a directory, submodules have their "type" specified as "file".” A `vendor.yaml` submodule produced `KeyError 'content'` at 999 entries and was correctly excluded at 1,000. [GitHub, Contents for API version 2022-11-28](https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28#get-repository-content)
- **Symlinks — confirmed for a listing row typed `symlink`.** The small path skips that row at `github.py:82`, so it never requests the target. The fallback skips mode `120000` at `github.py:104`. GitHub’s separate rule that an individual symlink request can return its target’s content does not establish how every parent directory row is typed. The mock verified the explicit `symlink` case. I could not independently verify a live listing in this environment. [GitHub, Get repository content](https://docs.github.com/en/rest/repos/contents#get-repository-content)
- **Other differences — reproduced.** A regular 2 MiB manifest and a regular manifest named `a#b?.yaml` each failed on the Contents path and succeeded on the tree path. `github.py:83–84,105–108`. Findings 2 and 4 give the reproductions and fixes.

## (c) Robustness

| Case | Result on PR head |
|---|---|
| Truncated ancestor or final directory | **Confirmed, refused.** Injecting `truncated: true` at the root raised `IncompleteList the tree eeeeeeee is truncated`; injecting it at the destination raised `IncompleteList the tree 8fa6b6ef is truncated`. `_tree` checks the flag before returning any entries. `github.py:97,103,115–121`. |
| Missing folder | **Confirmed, same caller semantics.** A Contents 404 returned `({}, HEAD)`. A missing path component in the tree helper returned `{}`, which `read_folder` pairs with `head`. The caller probe returned `namespace_doc({}) is None` and `folder_etag({}) == "0"`. Update and delete turn that absence into `404 object-not-found`. A create can proceed past the existence check. `github.py:75–85,96–100`, `pipeline.py:107–108,261–267,476–479,558–561`. A refused listing also masquerades as absence on head, addressed in finding 1. |
| Non-UTF-8 manifest | **Confirmed, strict rejection in both paths.** A blob containing `0xff` raised the same `UnicodeDecodeError` at 999 and 1,000 entries. Neither path returned partial text. The worker also uses strict decoding. The API registers a `ValueError` handler returning `validation-failed`; I ran the provider probe, not an HTTP request through that handler. `github.py:84,108`, `workspace.py:315–318`, `main.py:223–225`. |
| Large or refused blob | **Confirmed within the mocked cases.** The fallback returned the complete 2 MiB payload, byte-for-byte after decoding. A mocked blob HTTP 403 raised `GitUnavailable read blob 93d4dfda: HTTP 403`. The documented blob ceiling is 100 MB. I did not verify a particular live status code above that ceiling. `github.py:105–108`. [GitHub, Get a blob](https://docs.github.com/en/rest/git/blobs#get-a-blob) |
| Request cost | **Confirmed.** With a pinned commit, directory depth `D`, and `M` matching entries, the fallback makes `D + M + 3` GETs: Contents, commit, `D` ancestor trees, destination tree, and `M` blob reads. An unpinned branch adds one branch lookup. The four-component namespace folder with 1,001 manifests produced **1,008 GETs, including 1,001 blob GETs**. The complete 1,000-entry folder with just two manifests took nine GETs. GitHub says, “All of these requests count towards your personal rate limit of 5,000 requests per hour.” That figure applies to the personal-token case, and the source lists other authentication limits. `github.py:65–80,92–105`, `base.py:190–198`. [GitHub, REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#primary-rate-limit-for-authenticated-users) |

## (d) Other callers and delete

- **`tree_files` — confirmed covered by this fix.** It delegates to `read_folder(folder, ref)`. My run returned `tree_files: 1001 manifests, 1008 GETs, 1001 blob GETs`. There is no second Contents listing in that method. `base.py:204–206`.
- **`list_folder` — confirmed independent of the Contents cap.** It walks Git trees and requests the destination tree recursively. Its own limit is checked through `_tree`. My run returned 1,001 entries. The existing GitHub tests for recursive listing, missing folders, submodules, and truncated trees also passed. `github.py:115–141`, `test_delete_whole_folder_616.py:331–349`.
- **Delete — confirmed for the exported call paths.** Planning first needs the namespace manifest, so it benefits from #631. It then calls `removable_folder` at the returned SHA. That invokes `list_folder`, includes nested entries and non-YAML files, and refuses submodules. The worker checks the whole listing before push and checks the merged tree for remaining entries. The post-merge and prune checks also use `list_folder`. `pipeline.py:209–222,476–483`, `jobs/push_branch.py:29–33`, `workspace.py:571–574`, `jobs/merge.py:141–145`, `jobs/watch_sync.py:230`.
- **Other GitHub Contents directory reads — none found in the exported production source.** The source search found the directory call at `github.py:75` and the individual file call at `github.py:83`. GitHub’s worker dispatches to the local Git workspace at `github.py:72–73,127–128`.

## (e) Mutation results

I ran the PR’s new test against each independently modified method in memory. The unmodified selected pytest run reported **`12 passed, 28 deselected`**. The supplied regression failed against the exported base implementation.

| Mutant | Supplied test | Evidence |
|---|---|---|
| Change `>= 1000` to `> 1000` | **Killed** | Assertion failed. The listing contains exactly 1,000 `.txt` rows and omits `namespace.yaml`. `github.py:79`, test `:16–26`. |
| Remove the mode filter | **Survived** | The assertion still passed. Every blob in the supplied fixture has mode `100644`. `github.py:104`, test `:22–25`. |
| Remove the `.yaml` suffix test | **Killed** | Assertion failed. The result included `.txt` files. `github.py:104`, test `:22–26`. |
| Drop the directory prefix from the result key | **Killed** | Assertion failed. The expected key includes `BASE`. `github.py:101,108`, test `:23–26`. |

The added mixed-mode test below **killed the surviving mode mutant** at exactly 1,000 entries. The regression does not require changing the production mode filter.

## Findings, ordered by severity

Findings 1–4 are inherited from `base/cmapi/src/cmapi/core/git/github.py:71–79`. The PR fixes the capped path and makes the differences observable across the threshold. Finding 5 concerns the new test. The complete production fix and regression tests follow the list. I verified the code in memory using the supplied Python. No repository or export file was changed, no issue was posted, and nothing was pushed.

1. **High — a refused folder read is reported as a missing namespace.** `github.py:75–85`, `base.py:177–184`. A listing HTTP 403 falls through to `return files, head` with an empty map. Update and delete can consequently report that a managed namespace is missing, and create passes its existence check. An individual file 403 instead raises `KeyError 'content'`. The mocked run produced `DID NOT RAISE GitUnavailable` and `KeyError 'content'`, respectively. **Fix:** return empty only for the initial 404, and check every file response before decoding. **Tests:** `test_refused_folder` and `test_refused_file` below both passed after the fix. GitHub documents separate `403 Forbidden` and `404 Resource not found` responses. [GitHub, Contents status codes](https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28#http-response-status-codes-for-get-repository-content)
2. **Medium — the same large manifest is readable only at the directory cap.** `github.py:52–54,83–84,105–108`. A 2 MiB regular `.yaml` file at 999 entries raised `KeyError 'content'` when the mock refused the unsupported representation. At 1,000 entries the blob read returned the entire file. The exact refusal status was a mock choice. The underlying API restriction is documented. **Fix:** request the supported Contents object representation and, when it reports `encoding: none`, read the immutable blob SHA. **Test:** `test_large` failed at 999 on head and passed at both sizes after the fix. [GitHub, Contents media types and size limits](https://docs.github.com/en/rest/repos/contents#get-repository-content)
3. **Medium — a `.yaml`-named submodule breaks a below-cap read.** `github.py:54,82–84,104`. A version-2022 directory row for `vendor.yaml` can say `file`. The subsequent request returns submodule metadata without `content`. The 999-entry probe raised `KeyError 'content'`; the complete 1,000-entry tree correctly excluded the gitlink. During a delete, the exception can preempt the intended `folder-holds-submodule` response at `pipeline.py:217–221,476–483`. **Fix:** recognize the individual submodule response before decoding. **Test:** `test_types(999)` failed before and passed after. GitHub’s published individual-response example contains `"type": "submodule"` and `submodule_git_url`. [Versioned Contents contract](https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28#get-repository-content) · [GitHub’s submodule response example](https://developer.github.com/changes/29/)
4. **Medium — URI delimiters in a manifest name change the requested path.** `github.py:75,83`. With `a#b?.yaml`, the below-cap HTTP client requested a different path and the read raised `KeyError 'content'`. At 1,000 entries the SHA-based read returned the correct key and text. RFC 3986 says, “The path is terminated by the first question mark ("?") or number sign ("#") character, or by the end of the URI.” **Fix:** percent-encode repository path data while preserving directory separators. **Test:** `test_reserved_filename` failed before and passed after. [RFC 3986 §3.3, January 2005](https://www.rfc-editor.org/rfc/rfc3986#section-3.3)
5. **Low — the cap regression permits reading symlink blobs as manifests.** `test_github_read_folder_contents_cap_625.py:22–26`. Removing the production mode condition left the supplied test green. If that condition is removed, a `.yaml` symlink qualifies as a blob and its stored link target can enter the manifest map. **Fix and test:** add `test_types(1000)` below with a `120000` link, a `100755` regular file, a gitlink and a nested manifest. It failed against the mutant and passed against head. The production filter at `github.py:104` is correct. [GitHub, Git tree modes](https://docs.github.com/en/rest/git/trees#create-a-tree)

### Full production fix for findings 1–4

In `cmapi/src/cmapi/core/git/github.py`, add the import and replace `read_folder` with the following methods.

```python
from urllib.parse import quote
```

```python
    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        if self.workspace is not None:
            return self.workspace.read_folder(path, ref)

        head = self._folder_head(ref)
        url = f"{self._repo()}/contents/{quote(path.strip('/'))}"
        r = self._call("read_folder", "GET", url, params={"ref": head}, ok=(200, 404))
        if r.status_code == 404:
            return {}, head
        if r.status_code != 200:
            raise GitUnavailable(f"read folder: HTTP {r.status_code}")

        entries = r.json()
        if isinstance(entries, list) and len(entries) >= CONTENTS_DIRECTORY_LIMIT:
            return self._tree_manifests(path, head), head

        files = {}
        for e in entries if isinstance(entries, list) else [entries]:
            if e.get("type") != "file" or not e["name"].endswith(".yaml"):
                continue
            url = f"{self._repo()}/contents/{quote(e['path'])}"
            f = self._call(
                "read_file", "GET", url, params={"ref": head},
                headers={"Accept": "application/vnd.github.object+json"},
            )
            if f.status_code != 200:
                raise GitUnavailable(f"read file {e['path']}: HTTP {f.status_code}")
            body = f.json()
            if body.get("type") == "submodule" or "submodule_git_url" in body:
                continue
            if body.get("encoding") == "none":
                files[e["path"]] = self._blob_text(body["sha"])
            else:
                files[e["path"]] = base64.b64decode(body["content"]).decode()
        return files, head

    def _blob_text(self, sha: str) -> str:
        b = self._call("read_file", "GET", f"{self._repo()}/git/blobs/{sha}")
        if b.status_code != 200:
            raise GitUnavailable(f"read blob {sha[:8]}: HTTP {b.status_code}")
        return base64.b64decode(b.json()["content"]).decode()
```

Replace the body of the existing matching-entry condition at `github.py:105–108` with this single line so both paths use the checked blob reader.

```python
                files[prefix + e["path"]] = self._blob_text(e["sha"])
```

### Full regression tests for findings 1–5

These tests use the exported `RestHost` for commit and tree responses. The new mock derives its Contents listing from the same children as the tree, so the exactly-1,000 case represents a genuinely complete directory. The seven parameterized cases all passed with the fix. The existing cap and one-commit test modules also passed with it, **`7 passed`**.

```python
import base64

import httpx
import pytest

from cmapi.core.git.base import GitUnavailable
from test_delete_whole_folder_616 import (
    BASE, FOLDER_PATH, HEAD, RestHost, _github, _oid,
)


class Directory(RestHost):
    def __init__(self, entries, data=b"ok\n", *, listing_status=200, file_status=200):
        super().__init__(entries)
        self.data = data
        self.listing_status = listing_status
        self.file_status = file_status

    def __call__(self, request):
        path = request.url.path.removeprefix("/repos/o/r")
        if path == f"/contents/{FOLDER_PATH}":
            assert request.url.params["ref"] == HEAD
            if self.listing_status != 200:
                return httpx.Response(self.listing_status, json={})
            rows = []
            for e in self._children(FOLDER_PATH)[:1000]:
                kind = {"120000": "symlink", "040000": "dir"}.get(e["mode"], "file")
                rows.append({
                    "type": kind,
                    "name": e["path"],
                    "sha": e["sha"],
                    "path": BASE + e["path"],
                })
            return httpx.Response(200, json=rows)

        if path.startswith("/contents/"):
            assert request.url.params["ref"] == HEAD
            name = path.removeprefix("/contents/")
            if name not in self.entries:
                return httpx.Response(404, json={})
            if self.file_status != 200:
                return httpx.Response(self.file_status, json={})
            if self.entries[name][0] == "commit":
                return httpx.Response(200, json={
                    "type": "submodule", "submodule_git_url": "../lib",
                })
            if len(self.data) > 1024**2:
                if request.headers["accept"] == "application/vnd.github.object+json":
                    return httpx.Response(200, json={
                        "type": "file", "content": "", "encoding": "none",
                        "sha": _oid("blob", name),
                    })
                return httpx.Response(403, json={"message": "file too large"})
        elif not path.startswith("/git/blobs/"):
            return super().__call__(request)

        if self.file_status != 200:
            return httpx.Response(self.file_status, json={})
        return httpx.Response(200, json={
            "encoding": "base64",
            "content": base64.b64encode(self.data).decode(),
        })


def entries(n, names):
    files = {BASE + name: entry for name, entry in names.items()}
    files.update({
        f"{BASE}{i:04}.txt": ("blob", "100644")
        for i in range(n - len(names))
    })
    return files


def test_refused_folder():
    host = Directory({}, listing_status=403)
    with pytest.raises(GitUnavailable, match="403"):
        _github(host).read_folder(BASE, HEAD)


def test_refused_file():
    host = Directory(entries(1, {"a.yaml": ("blob", "100644")}), file_status=403)
    with pytest.raises(GitUnavailable, match="403"):
        _github(host).read_folder(BASE, HEAD)


@pytest.mark.parametrize("n", [999, 1000])
def test_large(n):
    data = b"#" + b"x" * (2 * 1024**2) + b"\n"
    host = Directory(entries(n, {"a.yaml": ("blob", "100644")}), data)
    assert _github(host).read_folder(BASE, HEAD) == (
        {BASE + "a.yaml": data.decode()}, HEAD,
    )


@pytest.mark.parametrize("n", [999, 1000])
def test_types(n):
    names = {
        "a.yaml": ("blob", "100755"),
        "link.yaml": ("blob", "120000"),
        "vendor.yaml": ("commit", "160000"),
        "dir.yaml/nested.yaml": ("blob", "100644"),
        "ignored.yml": ("blob", "100644"),
    }
    host = Directory(entries(n, names))
    assert _github(host).read_folder(BASE, HEAD) == (
        {BASE + "a.yaml": "ok\n"}, HEAD,
    )


def test_reserved_filename():
    name = "a#b?.yaml"
    host = Directory(entries(1, {name: ("blob", "100644")}))
    assert _github(host).read_folder(BASE, HEAD) == (
        {BASE + name: "ok\n"}, HEAD,
    )
```

## Tests I could not run

- **Live GitHub symlink-listing and blob-limit checks.** The public API request failed with `curl: (6) Could not resolve host: api.github.com`. Live behavior at or above 100 MB remains untested. The documentation fetches, 2 MiB mock, and refused-blob mock succeeded.
- **Real-Git delete integration tests.** The fixtures clone, commit to, and push to test repositories, outside the review’s no-repository constraint. `test_delete_whole_folder_616.py:159–172,180–231`. The mocked GitHub delete-listing and truncation tests ran. The database-backed end-to-end delete flows were outside the selected run.
- **All four requested mutants and the supplied PR regression ran.**

Codex session ID: 01a20be4-1db6-7283-80a6-ef0f2e04f426
Resume in Codex: codex resume 01a20be4-1db6-7283-80a6-ef0f2e04f426
