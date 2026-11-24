# Adversarial review · cmapi PR #639 / issue #638

**Request changes.** The PR fixes the branch lookups for `release#2` and `rel%41` on both REST providers. Two of its five URL builders still send a literal slash where the documented route takes one parameter. The Gitea protection helper also misses the existing-rule response from the version the chart installs. Gitea branch GET, branch DELETE, and compare can keep the default `safe='/'`.

I read all 92 lines of `pr.diff` and inspected the exported source directly. The export has no TokenSave index. Line numbers below refer to `head/`. The comparison is against the supplied `base/` at `baa932b`. All primary sources linked below were opened and read on **2026-11-24**. The Gitea version comes from `deploy/helm/cmapi-git/values.yaml:4–7`.

## Findings

| Severity | Location | Failure and disposition |
|---|---|---|
| **Medium** | `cmapi/src/cmapi/core/git/github.py:66` | A REST read for `team/main` emits two segments. GitHub documents an encoded slash in a path parameter. Use `quote(branch, safe='')`. This is a pre-existing issue at a changed line. Host rejection for this particular name was not measured. The worker's workspace branch read bypasses this line. |
| **Medium** | `cmapi/src/cmapi/core/git/gitea.py:288` | The protection update emits `branch_protections/team/main`. Gitea's named rule route cannot match the extra segment. Use `quote(self.default_branch, safe='')` here. The initial create sends the name in JSON and has no slash-routing problem. This defect exists in both snapshots. |
| **Low** | `cmapi/tests/service/test_branch_name_in_url_path.py:13–25` | The decoded-path assertion detects the two reported truncation/substitution examples, but cannot specify slash encoding or catch an unescaped lone percent. Three Gitea changes are outside this test. Assert literal request-target bytes, including the compare suffix, both requests in the delete flow, and the actual protection update. |
| **Medium** | `cmapi/src/cmapi/core/git/gitea.py:286–288` | Pre-existing. Posting an existing rule returns **403** on Gitea 1.25.5. The helper returns normally without applying new check contexts. A 422 is a validation error, and the helper also ignores an unsuccessful PATCH. Update the named rule, create on a missing rule, and report other failures. This is distinct from escaping the slash. I found no production caller of this provider helper in the export. |
| **Medium** | `cmapi/src/cmapi/core/git/gitea.py:229` | Pre-existing. The update path at line 144 asks `_blob_sha` for the current blob. A filename such as `dir/m#1.yaml` requests `contents/dir/m`. It can receive a different SHA or a missing-file response, preventing the planned update. Quote the repository path, keep its directory separators, and retain `params=` for the ref. |
| **Low** | `cmapi/src/cmapi/core/git/gitea.py:215` | Pre-existing. The first operand of `contains` is an observed Argo revision. It is passed through from `core/sync.py:107` via `jobs/watch_sync.py:130–133`, including other sources in a multi-source application. No hexadecimal-ID check occurs. URI syntax in that operand changes the comparison sent. Quote the revision and preserve the existing handling of absent revisions and host errors. The second operand is the stored merge SHA. No affected deployment was observed. |
| **High** | `cmapi/src/cmapi/tools/git_bootstrap.py:90,105,111` | Pre-existing, outside `core/git/`. The actual bootstrap job constructs its own seed-branch GET and protection GET/PATCH. For `team/r#2` all three lose the suffix. For a slash-only name the protection lookup also misses the single-segment route, so rerunning bootstrap can attempt a duplicate create. For `release#2`, if `release` and its rule exist, bootstrap can skip the intended seed and address the other rule. The incorrect requests were measured. The resulting repository state is inferred. Fix all three interpolations in the bootstrap entry point. |

## What was on the wire

I used the specified interpreter, httpx 0.28.1 and httpcore 1.0.9. I invoked the real provider methods with an HTTP client and captured the first line at the peer end of a local socket pair. Only httpcore's connection factory was replaced. HTTPX, httpcore's HTTP/1.1 transport and h11 serialized the requests. The peer supplied canned responses. This measures the bytes a host would receive without contacting a repository, running a Git host, or exercising a proxy. The pytest regressions below check `request.url.raw_path` in MockTransport separately. HTTPX defines that property as “The complete URL path and query string as raw bytes.” [HTTPX 0.28.1 URL implementation](https://raw.githubusercontent.com/encode/httpx/0.28.1/httpx/_urls.py)

Both providers emitted the following request lines, abbreviated by removing the identical `GET /repos/o/r/branches/` prefix and ` HTTP/1.1` suffix. The last column is the decoded path suffix on **base**.

| Input | Base request target suffix | Head request target suffix | Base decoded path / effect on the PR assertion |
|---|---|---|---|
| `main` | `main` | `main` | `main`, control |
| `release#2` | `release` | `release%232` | `release`, fails |
| `release?2` | `release?2` | `release%3F2` | `release`, query bytes `2`. Would fail if included |
| `rel%41` | `rel%41` | `rel%2541` | `relA`, fails |
| `rel%` | `rel%` | `rel%25` | `rel%`, would pass on either spelling |
| `team/main` | `team/main` | `team/main` | `team/main`, passes both versions and would also pass for `team%2Fmain` |
| `team/main#2` | `team/main` | `team/main%232` | `team/main`, two segments |
| `v1+hotfix` | `v1+hotfix` | `v1%2Bhotfix` | `v1+hotfix`, equal after one path decode |

**Ruling on claim 1.** For names with no slash, all three special characters reach the request target as data within one segment on head. For names that also contain a slash the general one-segment claim is false. A literal `%41` in the name must survive one decoding step as the three characters `%41`. The PR's `rel%41` case really does fail on base. The slash example alone passes vacuously in the submitted parameter set. A lone percent exposes a second blind spot. A question mark is a useful URL serialization case for this string-taking API, although Git disallows it in a branch name. The RFC says, “The path is terminated by the first question mark (“?”) or number sign (“#”) character, or by the end of the URI.” Section 2.4 specifies escaping a data percent as `%25`. Git says, “They cannot have question-mark ?, asterisk *, or open bracket [ anywhere.” [RFC 3986 §§2.4, 3.3](https://www.rfc-editor.org/rfc/rfc3986#section-3.3) · [Git ref format](https://git-scm.com/docs/git-check-ref-format)

**Ruling on claim 4.** With `main`, all five changed request targets matched byte-for-byte across snapshots, including `compare/main...` followed by the same 40-character SHA and the PATCH target after a simulated 422. The diff changes five string interpolations, one import, and one test file. Methods, JSON, response handling and workspace dispatch are untouched by this PR. Byte preservation does not extend to every valid name. For example, the measured plus becomes `%2B`, the same data after one path decode. Python documents the control case: “Letters, digits, and the characters '_.-~' are never quoted.” The full endpoint-equivalence conclusion for other names depends on host routing and decoding. [Python URL quoting](https://docs.python.org/3/library/urllib.parse.html#urllib.parse.quote)

## Which routes accept a slash?

| Endpoint | Evidence and ruling |
|---|---|
| GitHub GET branch | The branches reference gives `GET /repos/{owner}/{repo}/branches/{branch}` and describes the path parameter as “The name of the branch.” The REST troubleshooting guide explicitly says, “For example, any slashes in the parameter value must be replaced with `%2F`.” Use `team%2Fmain`. The documentation establishes the supported spelling. Whether GitHub happens to accept a literal slash for a particular name remains unverified. [Get a branch](https://docs.github.com/en/rest/branches/branches#get-a-branch) · [GitHub REST path-parameter guidance](https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api#404-not-found-for-an-existing-resource) |
| Gitea GET and DELETE branch | The API describes GET as “Retrieve a specific branch from a repository, including its effective branch protection” and DELETE as “Delete a specific branch from a repository”. In the `/branches` group, the registrations include `m.Get("/*", repo.GetBranch)` and `m.Delete("/*",` with `repo.DeleteBranch`. Both handlers read `ctx.PathParam("*")`. Thus literal `team/main` routes to one wildcard **value** spanning two URI segments. Keep the slash on both the pre-delete GET and DELETE. [Get branch](https://docs.gitea.com/api/1.25/operations/repo-get-branch/) · [Delete branch](https://docs.gitea.com/api/1.25/operations/repo-delete-branch/) · [Pinned route declarations](https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/api/v1/api.go) · [Pinned branch handlers](https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/api/v1/repo/branch.go) |
| Gitea GET compare | The API calls this “Get commit comparison information”. The router registers `"/compare/*"`. The handler takes `ctx.PathParam("*")` and executes `infos = strings.SplitN(infoPath, "...", 2)`. A slash inside the base or head is part of the capture. Keep the default safe slash and construct the three-dot delimiter separately. I measured `/repos/o/r/compare/team/main%232...aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` on head. [Compare API](https://docs.gitea.com/api/1.25/operations/repo-compare-diff/) · [Pinned router](https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/api/v1/api.go) · [Pinned compare parser](https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/api/v1/repo/compare.go) |
| Gitea PATCH protection | The API describes `name` as “Name of protected branch”. Under `/branch_protections` the router uses `m.Group("/{name}", func() {` for GET, PATCH and DELETE. The handler reads `bpName := ctx.PathParam("name")`. A literal slash prevents a match. The middleware explains the ordering: “make sure chi uses EscapedPath(RawPath) as RoutePath, then "%2f" could be handled correctly”. Thus `team%2Fmain` matches one segment first and supplies the rule name `team/main` after decoding. Gitea's published PathParam example explicitly gives `"/a%2fb"` → `"a/b"`. This is a source-based ruling for a request reaching Gitea with the escape intact. [Edit protection](https://docs.gitea.com/api/1.25/operations/repo-edit-branch-protection/) · [Pinned routes](https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/api/v1/api.go) · [Pinned routing middleware](https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/common/middleware.go) · [Gitea PathParam documentation](https://pkg.go.dev/code.gitea.io/gitea/services/context#Base.PathParam) |
| Gitea protection upsert | The pinned create handler looks up the rule name and returns `ctx.APIError(http.StatusForbidden, "Branch protection already exist")` when found. The edit handler returns 404 for an absent rule and HTTP 200 for an updated one. A synthetic POST 422 can exercise the old PATCH line, but it does not model an existing 1.25.5 rule. The proposed fix tries PATCH first. A simultaneous creator can cause a reported create refusal; retrying reaches the existing rule. [Pinned create and edit handlers](https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/api/v1/repo/branch.go) |

## Inventory of URL construction

Paths in this table are under `head/cmapi/src/cmapi/core/git/`. “SHA” denotes provenance in current production callers. Most URL builders accept a Python string and do not themselves validate the object ID.

| File and line | Value in path or query | Ruling |
|---|---|---|
| `github.py:66` | Branch parameter | Quoted, needs `safe=''` for slash. |
| `github.py:80` | Contents directory, `ref=head` | Directory already quoted with slash preserved. Ref goes through `params=`. `base.py:190–198` resolves a name to its head or accepts an explicit full object ID. |
| `github.py:96,105,120` | Blob SHA, tree SHA, commit SHA respectively | Safe object IDs, supplied by a tree/contents response or the resolved folder head. The recursive-tree switch is a separate query parameter. |
| `github.py:139,191` | Commit log's default branch and PR filter `owner:branch` | Both use `params=`. Preserve the unescaped application values. |
| `github.py:247,256` | Combined status for the PR head and status write for a commit | PR response SHA and checked head SHA. Safe. Pagination at line 221 adds ordinary query parameters. |
| `gitea.py:37,195` | Branch read and delete | Both quoted, wildcard routes. The generated request branch at `workspace.py:77–80` and `gitea.py:114` follows the same encoding path. No special case for the cmapi prefix is necessary. |
| `gitea.py:42,74` | Tree OID and blob SHA | Safe. Folder components are matched locally in trees. The page number is a query parameter. |
| `gitea.py:159,209` | Read commit and commit time | Commit SHAs from branch reads/listings. Safe. |
| `gitea.py:215` | `revision...sha` | Unquoted revision requires quoting. Merge SHA is safe. The equality shortcut sends no URL. |
| `gitea.py:223` | `default_branch...head` | Default branch quoted; head is a SHA in `jobs/pr_checks.py:73,84`, from the branch lookup or stored PR head. Safe for this caller. |
| `gitea.py:229` | Contents path and ref query | File path needs `quote(path)`; the Contents GET is registered as `m.Get("/*", repo.GetContents)`. The query already uses `params=`. [Pinned contents route](https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/api/v1/api.go) |
| `gitea.py:250,261` | Combined status for the PR head and status write | PR response SHA and checked commit SHA. Safe. |
| `gitea.py:279,288` | Log's default branch, protection rule name | Log uses `params=`; rule name requires one encoded segment. |

`base.py:168` forwards keyword arguments to `self._client.request`. With the synthetic value `team/a#b?c%41&x+y`, the peer received `sha=team%2Fa%23b%3Fc%2541%26x%2By` for both logs, `head=o%3Ateam%2Fa%23b%3Fc%2541%26x%2By` for GitHub PR lookup, and `ref=team%2Fa%23b%3Fc%2541%26x%2By` for Gitea Contents. This verifies that passing a value through `params=` is sufficient, even when the path in the same request is wrong. [HTTPX query parameters](https://www.python-httpx.org/quickstart/#passing-parameters-in-urls)

For completeness, `github.py:203,265` and `gitea.py:130,148,178,266,284` put branch names, refs or file paths in JSON. Gitea filters prefix/branch locally at lines 199–204 and 237–240; GitHub does so at 230–232. Both providers' `_repo()` methods build the configured owner/repository namespace. PR/issue numbers and returned PR web links do not interpolate a Git ref. The workspace and transport modules pass a configured remote URL and separate Git arguments; `oplog.py`, `__init__.py`, and the base class add no further branch/path URL interpolation.

## Full fixes and regression tests

The following is the complete production delta against the PR head. The protection change addresses both its segment boundary and its existing-rule/error handling. The bootstrap fix preserves its existing create/update flow and JSON names.

```diff
--- a/cmapi/src/cmapi/core/git/github.py
+++ b/cmapi/src/cmapi/core/git/github.py
@@ -63,7 +63,7 @@
     def branch_head(self, branch: str) -> str | None:
         if self.workspace is not None:
             return self.workspace.branch_head(branch)
-        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{quote(branch)}", ok=(200, 404))
+        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{quote(branch, safe='')}", ok=(200, 404))
         return r.json()["commit"]["sha"] if r.status_code == 200 else None
 
     def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
--- a/cmapi/src/cmapi/core/git/gitea.py
+++ b/cmapi/src/cmapi/core/git/gitea.py
@@ -212,7 +212,7 @@
     def contains(self, revision: str, sha: str) -> bool:
         if revision == sha:
             return True
-        r = self._call("compare", "GET", f"{self._repo()}/compare/{revision}...{sha}")
+        r = self._call("compare", "GET", f"{self._repo()}/compare/{quote(revision)}...{sha}")
         if r.status_code == 404:      # not this repository's: a multi-source Application's other source, or a force-pushed commit
             return False
         if r.status_code != 200:
@@ -226,7 +226,7 @@
         return {f["filename"] for c in r.json().get("commits") or [] for f in c.get("files") or []}
 
     def _blob_sha(self, path: str, ref: str) -> str:
-        r = self._call("read_file", "GET", f"{self._repo()}/contents/{path}", params={"ref": ref})
+        r = self._call("read_file", "GET", f"{self._repo()}/contents/{quote(path)}", params={"ref": ref})
         return r.json()["sha"]
 
     def _pr_ref(self, p: Mapping[str, Any]) -> PrRef:
@@ -283,9 +283,16 @@
         """One-time setup: nobody pushes to main; merges need every context green (the cmapi check)."""
         body = {"branch_name": self.default_branch, "enable_push": False, "enable_status_check": True,
                 "status_check_contexts": contexts, "block_on_rejected_reviews": True, "enable_merge_whitelist": False}
-        r = self._call("protect", "POST", f"{self._repo()}/branch_protections", json=body, ok=(201, 403, 422))
-        if r.status_code == 422:                               # already protected: update it
-            self._call("protect", "PATCH", f"{self._repo()}/branch_protections/{quote(self.default_branch)}", json=body)
+        rules = f"{self._repo()}/branch_protections"
+        rule = f"{rules}/{quote(self.default_branch, safe='')}"
+        r = self._call("protect", "PATCH", rule, json=body, ok=(200, 404))
+        if r.status_code == 200:
+            return
+        if r.status_code == 404:
+            r = self._call("protect", "POST", rules, json=body, ok=(201,))
+            if r.status_code == 201:
+                return
+        raise GitUnavailable(f"protect default branch: HTTP {r.status_code} {self.host_text(r, 200)}")
 
 
 def _b64(text: str) -> str:
--- a/cmapi/src/cmapi/tools/git_bootstrap.py
+++ b/cmapi/src/cmapi/tools/git_bootstrap.py
@@ -14,6 +14,7 @@
 import sys
 import time
 from typing import Any
+from urllib.parse import quote
 
 import httpx
 
@@ -87,7 +88,7 @@
         r.raise_for_status()
         print(f"repository {org}/{repo} present")
     # Decided by the branch, not the repository: a run killed before the seed commit must seed on the next run.
-    if bot.get(f"/repos/{org}/{repo}/branches/{s.git_default_branch}").status_code == 404:
+    if bot.get(f"/repos/{org}/{repo}/branches/{quote(s.git_default_branch)}").status_code == 404:
         files: dict[str, str] = {"README.md": SEED_README}
         for cid in cluster_ids:
             files[f"clusters/{cid}/namespaces/.keep"] = ""
@@ -102,13 +103,14 @@
     body = {"branch_name": s.git_default_branch, "rule_name": s.git_default_branch, "enable_push": False,
             "enable_status_check": True, "status_check_contexts": list(REQUIRED_CONTEXTS),
             "block_on_outdated_branch": False, "enable_merge_whitelist": True, "merge_whitelist_usernames": [bot_user]}
-    r = bot.get(f"/repos/{org}/{repo}/branch_protections/{s.git_default_branch}")
+    rule = f"/repos/{org}/{repo}/branch_protections/{quote(s.git_default_branch, safe='')}"
+    r = bot.get(rule)
     if r.status_code == 404:
         bot.post(f"/repos/{org}/{repo}/branch_protections", json=body).raise_for_status()
         print("branch protection created")
     else:
         r.raise_for_status()
-        bot.patch(f"/repos/{org}/{repo}/branch_protections/{s.git_default_branch}", json=body).raise_for_status()
+        bot.patch(rule, json=body).raise_for_status()
         print("branch protection in force")
 
 
```

Save the following complete module as `cmapi/tests/service/test_review639_urls.py`. The branch-target matrix can replace the PR's decoded-path test. Expected bytes are literals independent of the quoting implementation. The wildcard test exercises the PR fixes to delete and compare, and the rule test models the pinned server's duplicate-create response.

```python
from types import SimpleNamespace

import httpx
import pytest

from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.tools import git_bootstrap

API = "https://host.test"
ROOT = b"/repos/o/r/"
SHA = "a" * 40
COMMIT = {"commit": {"sha": SHA, "id": SHA}}


@pytest.fixture
def host(monkeypatch):
    seen = []
    replies = []
    client_type = httpx.Client

    def handle(req):
        seen.append((req.method, req.url.raw_path))
        reply = replies.pop(0)
        status, body = reply(req) if callable(reply) else reply
        return httpx.Response(status, json=body)

    def client(*args, **kwargs):
        return client_type(*args, **kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(httpx, "Client", client)
    return seen, replies


@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
@pytest.mark.parametrize(("name", "tail"), [
    ("main", b"main"), ("release#2", b"release%232"), ("release?2", b"release%3F2"),
    ("rel%41", b"rel%2541"), ("rel%", b"rel%25"), ("team/main", b"team/main"),
])
def test_branch_target(host, provider, name, tail):
    seen, replies = host
    replies.append((200, COMMIT))
    if name == "team/main" and provider is GitHubProvider:
        tail = b"team%2Fmain"
    git = provider(API, "o/r", "")
    assert git.branch_head(name) == SHA
    assert seen == [("GET", ROOT + b"branches/" + tail)]


def test_gitea_wildcards(host):
    seen, replies = host
    replies.extend([(200, COMMIT), (204, None), (200, {"commits": []})])
    git = GiteaProvider(API, "o/r", "", default_branch="team/main#2")
    assert git.delete_branch(git.default_branch, SHA)
    assert git.changed_paths(SHA) == set()
    branch = ROOT + b"branches/team/main%232"
    assert seen == [("GET", branch), ("DELETE", branch),
                    ("GET", ROOT + b"compare/team/main%232..." + SHA.encode())]


def test_update_existing_protection(host):
    seen, replies = host
    rule = ROOT + b"branch_protections/team%2Fmain%232"

    def existing(req):
        if req.method == "POST":
            return 403, {"message": "Branch protection already exist"}
        if req.method == "PATCH" and req.url.raw_path == rule:
            return 200, {}
        return 404, {}

    replies.extend([existing, existing])
    GiteaProvider(API, "o/r", "", default_branch="team/main#2").protect_default_branch([])
    assert ("PATCH", rule) in seen


def test_create_missing_protection(host):
    seen, replies = host
    replies.extend([(404, {}), (201, {})])
    GiteaProvider(API, "o/r", "").protect_default_branch([])
    assert seen == [("PATCH", ROOT + b"branch_protections/main"), ("POST", ROOT + b"branch_protections")]


def test_protection_refusal_is_visible(host):
    _, replies = host
    replies.append((403, {}))
    with pytest.raises(GitUnavailable):
        GiteaProvider(API, "o/r", "").protect_default_branch([])


def test_blob_name_and_ref(host):
    seen, replies = host
    replies.append((200, {"sha": SHA}))
    git = GiteaProvider(API, "o/r", "")
    assert git._blob_sha("dir/a#b?c%41.yaml", "team/r#1") == SHA
    assert seen == [("GET", ROOT + b"contents/dir/a%23b%3Fc%2541.yaml?ref=team%2Fr%231")]


def test_observed_revision(host):
    seen, replies = host
    replies.append((404, {}))
    assert not GiteaProvider(API, "o/r", "").contains("v1+build%41", SHA)
    assert seen == [("GET", ROOT + b"compare/v1%2Bbuild%2541..." + SHA.encode())]


def test_bootstrap_existing_branch_and_rule(host, monkeypatch):
    seen, replies = host
    for key in ("GIT_ADMIN_USER", "GIT_ADMIN_PASSWORD", "GIT_PASSWORD"):
        monkeypatch.setenv("CMAPI_" + key, "test")
    monkeypatch.setenv("CMAPI_GIT_REPOSITORY", "o/r")
    settings = SimpleNamespace(git_url=API, verify=True, git_default_branch="team/r#2")
    monkeypatch.setattr(git_bootstrap, "settings", lambda: settings)
    replies.extend([(200, {})] * 9)
    git_bootstrap.main([])
    assert seen[-3:] == [
        ("GET", ROOT + b"branches/team/r%232"),
        ("GET", ROOT + b"branch_protections/team%2Fr%232"),
        ("PATCH", ROOT + b"branch_protections/team%2Fr%232"),
    ]
```

## Verification

| Tests | Base at baa932b | PR head | Head with proposed fixes |
|---|---:|---:|---:|
| Submitted test, 6 cases | 4 failed, 2 passed | 6 passed | 6 passed |
| Review module above, 19 cases | 16 failed, 3 passed | 7 failed, 12 passed | 19 passed |

The seven head failures were the GitHub slash case, three protection cases (update, create after missing rule, visible refusal), the Contents filename, the observed revision and bootstrap. The base-only failures additionally expose the escaping repaired by this PR. In particular, the bare-percent byte assertion fails on base even though the decoded path equals the input. The test host does not simulate GitHub's private router. The socket capture establishes the client's behavior, and the dated host documentation and source establish the routing conclusions.

Commands used from `head/cmapi`, with the same interpreter and module layout for the isolated before/after copies:

```sh
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_branch_name_in_url_path.py -q -W ignore
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest tests/service/test_review639_urls.py -q -W ignore
```

All fixes were exercised on a disposable copy of the export. The report contains the patch and tests for local filing.
