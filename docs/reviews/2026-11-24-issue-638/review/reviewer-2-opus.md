# Reviewer 2 (Opus 5.5, high), PR #639 (closes #638): a branch name put into a URL path unquoted

Reviewer 2 did not write the change. Reviewer 1 is Codex gpt-6.2-astra xhigh (`codex-report.md`). All work is in this export;
no repository, GitHub write or cluster was touched. The one patch is `r2-outputs/fix.diff` (against `head/`, applies with
`patch -p1 -F0` from the export root, checked on a fresh copy: all six files byte-identical to `r2/`).

**Ruling: apply `r2-outputs/fix.diff`.** It keeps the PR's five quotes, takes four of Codex's fixes (GitHub `safe=''`,
Gitea `contains`, Gitea `_blob_sha`, the three `git_bootstrap.py` interpolations), and replaces Codex's rewrite of
`protect_default_branch` with the deletion of that helper, which no production code calls. It merges the PR's test and
Codex's raw-bytes module into one file, `test_branch_name_in_url_path.py`.

## What was measured

| Evidence | File |
|---|---|
| A disposable Gitea 1.25.5, the chart's pinned digest, on `127.0.0.1:13639` (podman, removed after): raw spellings, the three trees' providers, and `git_bootstrap.main()` run twice per tree and default branch | `r2-outputs/gitea-live/probe-output.txt`, `logs/`, `probe.py`, `providers.py`, `bootstrap_runs.sh` |
| `api.github.com`, unauthenticated, read-only, generic user agent, 2026-11-24T11:11:06Z | `r2-outputs/github-probe.txt`, `github-probe-list.txt` |
| The merged test module on base, head and the fix | `r2-outputs/test-before-after.txt` |
| Eleven mutants of the final fix | `r2-outputs/mutants/mutants-output.txt`, `run_mutants.py` |
| Codex's patch and module on `r2/`: 25 passed; Codex's module on unpatched head: 7 failed, 12 passed (Codex's numbers reproduced) | this report, "Codex's patch reproduced" |
| The git-layer and related suites on the final tree | `r2-outputs/git-layer-tests.txt` |
| Fetched primary sources | `r2-outputs/sources/` |

### The live Gitea 1.25.5 (`probe-output.txt`)

Gitea accepted the branch names `team/main`, `release#2`, `rel%41` (201 each). Raw request targets:

| Request | Status |
|---|---|
| `GET branches/team/main` and `GET branches/team%2Fmain` | 200 `team/main`, both |
| `GET branches/release%232` | 200 `release#2` |
| `GET branches/rel%2541` | 200 `rel%41` |
| `GET branches/rel%41` | 200 **`relA`** (a different branch) |
| `POST branch_protections` rule `team/main`, first, then again | 201, then **403** `{"message":"Branch protection already exist"}` |
| `GET` / `PATCH branch_protections/team/main` (literal slash) | **404** `404 page not found` (no route) |
| `GET` / `PATCH branch_protections/team%2Fmain` | 200, 200 |
| `PATCH branch_protections/nosuch` | 404 `{"message":"not found"}` |
| `GET compare/team/main...<sha>`, `compare/team%2Fmain...<sha>`, `compare/release%232...<sha>` | 200, 200, 200 |

The providers of each tree against the same host (truth = the host's branch list and tree):

| Call | base | head (PR) | fix |
|---|---|---|---|
| `branch_head('team/main')` | OK | OK | OK |
| `branch_head('release#2')` | **WRONG** (read `release`) | OK | OK |
| `branch_head('rel%41')` | **WRONG** (read `relA`) | OK | OK |
| `_blob_sha('dir/m#1.yaml')` | **KeyError** | **KeyError** | OK |
| `_blob_sha('dir/m%41.yaml')` | **WRONG** (blob of `dir/mA.yaml`) | **WRONG** | OK |

`cmapi-tools git-bootstrap` (`git_bootstrap.main`), each tree in its own organisation, run twice, as the chart's
`post-install,post-upgrade` hook runs it (`deploy/helm/cmapi/templates/jobs.yaml:15`):

| Default branch | head run 1 | head run 2 | fix run 1 | fix run 2 |
|---|---|---|---|---|
| `team/main` | exit 0 | **exit 1**: `403 Forbidden` for `.../branch_protections` (a second create) | exit 0 | exit 0, "branch protection in force" |
| `release#2` | exit 0 | **exit 1**: `403 Forbidden` for `.../contents` (a second seed: `GET branches/release` found nothing) | exit 0 | exit 0, "branch protection in force" |

### GitHub (`github-probe.txt`)

`git/git` has no branch with a slash (its list: bisect, jch, maint, master, next, seen, test, todo), so the probe used
`microsoft/vscode`:

```
GET /repos/microsoft/vscode/branches/release/1.85   -> 200 name= release/1.85 sha= 8b3775030ed1
GET /repos/microsoft/vscode/branches/release%2F1.85 -> 200 name= release/1.85 sha= 8b3775030ed1
```

GitHub serves both spellings today. The documented one is `%2F`.

## Sources (each fetched and read 2026-11-24; copies in `r2-outputs/sources/`)

Every quote in Codex's report that I checked exists and says what Codex says. None is refuted.

1. GitHub, "Troubleshooting the REST API", https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api :
   "Additionally, any path parameters must be URL encoded. For example, any slashes in the parameter value must be replaced
   with `%2F`. If you don't properly encode any slashes in the parameter name, the endpoint URL will be misinterpreted."
2. RFC 3986, https://www.rfc-editor.org/rfc/rfc3986.txt . Section 3.3: "The path is terminated by the first question mark
   ("?") or number sign ("#") character, or by the end of the URI." Section 2.4: "Because the percent ("%") character
   serves as the indicator for percent-encoded octets, it must be percent-encoded as "%25" for that octet to be used as data
   within a URI. Implementations must not percent-encode or decode the same string more than once".
3. Gitea v1.25.5 router, https://raw.githubusercontent.com/go-gitea/gitea/v1.25.5/routers/api/v1/api.go : lines 1257-1271,
   `m.Group("/branches", ...)` with `m.Get("/*", repo.GetBranch)` and `m.Delete("/*", ..., repo.DeleteBranch)`, and
   `m.Group("/branch_protections", ...)` with `m.Group("/{name}", func() { m.Get("", ...); m.Patch("", ...) ...})`;
   line 1189 `m.Get("/compare/*", reqRepoReader(unit.TypeCode), repo.CompareDiff)`; lines 1430-1432 `m.Group("/contents", ...)`
   with `m.Get("/*", repo.GetContents)`.
4. Gitea v1.25.5 branch handlers, `routers/api/v1/repo/branch.go`: line 60 and 134 `branchName := ctx.PathParam("*")`;
   lines 589-594 `protectBranch, err := git_model.GetProtectedBranchRuleByName(ctx, repo.ID, ruleName)` ...
   `ctx.APIError(http.StatusForbidden, "Branch protection already exist")`; 422 is returned only for validation errors
   (lines 606-671); line 773 `bpName := ctx.PathParam("name")`, and 404 when the rule is absent (lines 779-781).
5. Gitea v1.25.5 middleware, `routers/common/middleware.go` line 87: "make sure chi uses EscapedPath(RawPath) as RoutePath,
   then "%2f" could be handled correctly", and lines 91-95 set `chiCtx.RoutePath` to `req.URL.RawPath` when present.
6. Gitea v1.25.5 `services/context/base_path.go` lines 16-18 (Codex cited the pkg.go.dev rendering; I read the source):
   `// PathParam returns the param in request path, eg: "/{var}" => "/a%2fb", then var == "a/b"` and
   `s, err := url.PathUnescape(b.PathParamRaw(name))`.
7. Gitea v1.25.5 `routers/api/v1/repo/compare.go` lines 55-58: `infoPath := ctx.PathParam("*")`,
   `infos = strings.SplitN(infoPath, "...", 2)`.
8. Gitea v1.25.5 name rules: `modules/validation/helpers.go` line 27, ``validUsernamePattern: regexp.MustCompile(`^[\da-zA-Z][-.\w]*$`)``;
   `models/repo/repo.go` line 75, ``validRepoNamePattern: regexp.MustCompile(`^[-.\w]+$`)``.
9. The Gitea cmapi installs: `deploy/helm/cmapi-git/values.yaml` lines 4-7, `tag: 1.25.5-rootless`,
   `digest: sha256:be0b89adf2fc8657df508303d919c3be33e6413605882919f702177d62960c9a` (the image the live probe ran).
10. Python, https://docs.python.org/3/library/urllib.parse.html#urllib.parse.quote : "Letters, digits, and the characters
    '_.-~' are never quoted. By default, this function is intended for quoting the path section of a URL. The optional
    safe parameter specifies additional ASCII characters that should not be quoted — its default value is '/'."
11. HTTPX 0.28.1 (the venv's version), https://raw.githubusercontent.com/encode/httpx/0.28.1/httpx/_urls.py : `raw_path`,
    "The complete URL path and query string as raw bytes. Used as the target when constructing HTTP requests."
12. Keycloak 26.6.4 (the version docs/11 names), `server-spi-private/.../utils/ReservedCharValidator.java` line 36
    ``Pattern.compile("[:/?#@!$&()*+,;=\\[\\]\\\\]")`` and `services/.../managers/RealmManager.java` line 132
    `ReservedCharValidator.validate(name);` (used only for the realm lead under "What Codex missed").

## Rulings on Codex's seven findings

| # | Codex | Location (head) | Ruling | Decided by |
|---|---|---|---|---|
| 1 | Medium | `github.py:66` | **Confirmed, narrowed to Low.** Apply `safe=''` | GitHub doc (source 1); live probe: both spellings 200; mutant M01 |
| 2 | Medium | `gitea.py:288` | **Confirmed on the wire, made moot:** delete the helper | No production caller (below); live 404 for the literal slash |
| 3 | Low | the PR's test | **Confirmed.** Replaced by one raw-bytes module | `test-before-after.txt`: the PR's decoded-path test passes on base for `team/main` |
| 4 | Medium | `gitea.py:286-288` | **Confirmed (403, not 422), made moot:** delete the helper | Source 4 and the live 403 |
| 5 | Medium | `gitea.py:229` | **Confirmed, narrowed to Low.** Apply `quote(path)` | Live: `m%41.yaml` read `mA.yaml`'s blob; not reachable with cmapi's file names |
| 6 | Low | `gitea.py:215` | **Confirmed as Low hardening.** Apply `quote(revision)` | Source 7; mutant M07 |
| 7 | High | `git_bootstrap.py:90,105,111` | **Confirmed, High.** Apply Codex's fix | Live: head's second run exits 1 for `team/main` and `release#2`; the fix's exits 0 |

### Finding 1: GitHub `branches/{branch}` and `safe=''`

- Callers. `GitHubProvider.branch_head` reaches REST only when `self.workspace is None`, the API process
  (`core/git/__init__.py:44-51`: `make_provider` gives the workspace only with `git_layer`). There, `_folder_head`
  (`base.py:190-198`) calls it with the configured default branch: `pipeline.py:205` and `214` call `read_folder(folder)`
  and `list_folder(folder, ref)`, and `pipeline.py:483` passes `base_sha`, a full object ID that `_folder_head` returns
  without a lookup. The request branches `cmapi/<cluster>/<requestId>` (`workspace.py:77-80`) are read in the worker through
  the Git layer, never through this line. So the name here is `git.defaultBranch` (`settings.py:42`, chart `defaultBranch: main`).
- With a slash in that name, the PR sends `branches/team/main`. GitHub's documentation says the parameter's slashes "must be
  replaced with `%2F`" (source 1). Measured: GitHub serves both spellings today (`github-probe.txt`), so the literal
  slash is an undocumented spelling that works, not a failure. Hence Low, not Medium.
- Ruling: apply `quote(branch, safe='')`, the documented spelling, measured 200. For `main` the bytes are unchanged.

### Finding 2 and 4: `GiteaProvider.protect_default_branch`

- Callers on `head` (grep over the whole export, outside `docs/reviews/`):
  - `cmapi/src/cmapi/core/git/gitea.py:282`, the definition;
  - `cmapi/src/cmapi/core/git/base.py:126`, a comment;
  - `cmapi/tests/service/test_git_host_redaction_424.py:117`, one entry of the redaction test's `GITEA_CALLS`.
  No production code calls it. The Gitea stand-in's protection is made by `tools/git_bootstrap.py:101-112`, its own code.
  (`tokensave_search` literal on `main` agrees: the same three places, at older line numbers; its index is 30 files stale.)
- Codex is right on both counts, measured live: the literal slash gets 404 from `branch_protections/{name}`, and a second
  create gets **403** "Branch protection already exist", so the helper's `if r.status_code == 422` update never ran on 1.25.5.
- Ruling: under the owner's rule "over-build only if it is the only solution", dead code is deleted, not grown. Codex's
  rewrite (PATCH first, then POST, then raise) is 12 lines and three tests for a function nothing calls. The fix deletes the
  helper, its redaction-test entry, and points the `base.py` comment at `tools/git_bootstrap.py`. Codex's three protection
  tests are dropped with it.

### Finding 3: the PR's test

- The PR asserts `request.url.path`, which httpx decodes. Run on base, the PR's own six cases give 4 failed and 2 passed
  (Codex's count): `team/main` passes on base for both providers, and it would also pass for `team%2Fmain`, so it pins nothing.
- Ruling: one module, `test_branch_name_in_url_path.py`, asserting `request.url.raw_path` bytes: the PR's cases plus
  Codex's `release?2` and `rel%`, the `main` control, the route-dependent slash, delete and compare, `contains`, `_blob_sha`,
  and `git_bootstrap.main()` on its first run and its re-run. Results (`test-before-after.txt`):

  | Tree | Result |
  |---|---|
  | base | 14 failed, 3 passed (the two `main` controls and Gitea's literal-slash `team/main`) |
  | head (PR) | 5 failed, 12 passed: GitHub `team/main`, `contains`, `_blob_sha`, bootstrap first run and re-run |
  | fix | 17 passed |

### Finding 5: Gitea `_blob_sha`

- Caller: `push_request_branch`, `gitea.py:144`, for an `update` operation: a path that is both in the plan (`req.files`) and
  already in the folder with other text.
- Measured live: the unquoted `contents/dir/m%41.yaml` returned the blob of `dir/mA.yaml`, and `dir/m#1.yaml` returned no
  `sha` (KeyError); the fix reads both right.
- Reach: the planned paths are `clusters/<cluster>/namespaces/<ns>/` (`render/manifests.py:61`) plus files named from a
  Kubernetes kind and object name (`render/manifests.py:69-76`), and Kubernetes names cannot hold "#", "?" or "%". So no
  path cmapi writes today reaches the defect. I did not check how a cluster ID is validated. Hence Low.
- Ruling: apply `quote(path)` with the default `safe='/'` (Gitea routes `/contents/*`, source 3). One call, the same rule as
  the PR's.

### Finding 6: Gitea `contains`

- Caller: `jobs/watch_sync.py:133`, `ctx.git.contains(r, row.merge_sha) for r in observed`, where `observed` is Argo CD's
  `status.sync.revisions` or `revision` (`core/sync.py:107-108`): data from outside cmapi. The second operand is the stored
  merge SHA.
- No revision with "#", "?" or "%" was observed; a Git source's revision is a SHA and a Helm source's a chart version.
- Ruling: apply `quote(revision)`. For a SHA or a version without "+" the bytes are unchanged; a "+" becomes `%2B`, which
  Gitea's `PathParam` unescapes back to "+" (`url.PathUnescape`, source 6). Low.

### Finding 7: `tools/git_bootstrap.py`, High

- The three interpolations are at head lines 90 (`branches/{s.git_default_branch}`), 105 and 111
  (`branch_protections/{s.git_default_branch}`). Codex's fix is right per route: `quote(...)` keeps the slash for the
  `/branches/*` wildcard, `quote(..., safe='')` makes one segment for `/branch_protections/{name}` (source 3), and the PATCH
  reuses the GET's `rule`.
- Measured live, not inferred: with head, the second run of the hook exits 1 for `team/main` (a second protection create,
  403) and for `release#2` (a second seed, 403 on `contents`). The chart runs this Job on `post-install,post-upgrade`, so with
  such a default branch every upgrade after the first fails its hook. With `main` the bytes are unchanged. High, as Codex said,
  for an operator who sets such a default branch.
- Codex's test. `main()` builds both clients as `httpx.Client(base_url=api, auth=..., timeout=30, verify=s.verify)` (lines 54
  and 70) and reads `settings()` from the module's own name (line 45). Codex's monkeypatching of `httpx.Client` and of
  `git_bootstrap.settings` therefore reaches the real code path, and its test fails on head (measured), so it is not vacuous.
  Two weaknesses: it replaces `Settings` with a `SimpleNamespace`, so the real environment parsing is not run; and its replies
  are a queue sized to the call count (9 replies for 8 calls). The merged module uses the real `Settings` through
  `CMAPI_*` variables and `settings.cache_clear()` (the pattern of `test_review_h_tools_migrate.py:114-137`), answers by
  route, and covers both the first run (404, seed and create) and the re-run (200, PATCH).

## The final code (all of it is in `r2-outputs/fix.diff`)

`cmapi/src/cmapi/core/git/github.py`, `branch_head`:

```python
    def branch_head(self, branch: str) -> str | None:
        if self.workspace is not None:
            return self.workspace.branch_head(branch)
        # One path parameter: GitHub asks for a "/" in it as %2F, and "#", "?" and "%" are escaped as data (#638).
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{quote(branch, safe='')}", ok=(200, 404))
        return r.json()["commit"]["sha"] if r.status_code == 200 else None
```

`cmapi/src/cmapi/core/git/gitea.py` (the PR's `delete_branch` and `changed_paths` lines stay as they are):

```python
    def branch_head(self, branch: str) -> str | None:
        # A name is data in the path: "#", "?" and "%" are escaped (RFC 3986, sections 2.4 and 3.3). Gitea routes branches,
        # compare and contents with a "/*" wildcard, so a "/" in a branch name or a file path stays a "/" (#638).
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{quote(branch)}", ok=(200, 404))
        return r.json()["commit"]["id"] if r.status_code == 200 else None
    ...
    def contains(self, revision: str, sha: str) -> bool:
        if revision == sha:
            return True
        r = self._call("compare", "GET", f"{self._repo()}/compare/{quote(revision)}...{sha}")
        ...
    def _blob_sha(self, path: str, ref: str) -> str:
        r = self._call("read_file", "GET", f"{self._repo()}/contents/{quote(path)}", params={"ref": ref})
        return r.json()["sha"]
```

and `protect_default_branch` (head lines 282-288) is deleted.

`cmapi/src/cmapi/core/git/base.py:126`:

```python
    # Whether the worker posts its checks as commit statuses. The Gitea stand-in protects main with them (tools/git_bootstrap.py);
```

`cmapi/src/cmapi/tools/git_bootstrap.py` (plus `from urllib.parse import quote`):

```python
    if bot.get(f"/repos/{org}/{repo}/branches/{quote(s.git_default_branch)}").status_code == 404:
    ...
    # Gitea routes a rule by one path segment ("/{name}"), so a "/" in the name is sent as %2F; a branch read takes "/*" (#638).
    rule = f"/repos/{org}/{repo}/branch_protections/{quote(s.git_default_branch, safe='')}"
    r = bot.get(rule)
    if r.status_code == 404:
        bot.post(f"/repos/{org}/{repo}/branch_protections", json=body).raise_for_status()
        print("branch protection created")
    else:
        r.raise_for_status()
        bot.patch(rule, json=body).raise_for_status()
        print("branch protection in force")
```

`cmapi/tests/service/test_git_host_redaction_424.py`: the `"protect_default_branch"` entry of `GITEA_CALLS` is removed.

`cmapi/tests/service/test_branch_name_in_url_path.py`, the whole module, replacing the PR's:

```python
"""A branch name, a revision or a file path is data in a URL path (#638). Git accepts "#" and "%" in a branch name
(git check-ref-format --branch 'release#2'), and RFC 3986, section 3.3: "The path is terminated by the first question mark
("?") or number sign ("#") character"; section 2.4: a data "%" "must be percent-encoded as "%25"". Unquoted, the branch
release#2 read the head of release, and rel%41 the head of relA (measured on Gitea 1.25.5, the review record of #639).

Each test asserts request.url.raw_path, the bytes httpx puts on the request line, not the decoded request.url.path: "rel%"
and "rel%25" decode to the same path, and "team/main" and "team%2Fmain" too.

The slash differs by route. GitHub: "any slashes in the parameter value must be replaced with %2F" (REST troubleshooting).
Gitea 1.25.5 routes /branches/*, /compare/* and /contents/* with a wildcard, so a "/" stays a "/", and /branch_protections/{name}
with one segment, so a "/" there is %2F (routers/api/v1/api.go)."""
from __future__ import annotations

from typing import Callable

import httpx
import pytest

from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.settings import settings
from cmapi.tools import git_bootstrap

API = "https://host.test"
ROOT = b"/repos/o/r/"
SHA = "a" * 40


@pytest.fixture
def host(monkeypatch):
    """Every httpx.Client made during the test answers from `reply`; `seen` holds (method, raw path and query) of each request."""
    seen: list[tuple[str, bytes]] = []
    state: dict[str, Callable[[httpx.Request], tuple[int, object]]] = {
        "reply": lambda req: (200, {"commit": {"sha": SHA, "id": SHA}, "commits": [], "sha": SHA})}
    real = httpx.Client

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.raw_path))
        status, body = state["reply"](req)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handle)}))
    return seen, state


@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
@pytest.mark.parametrize(("name", "tail"), [
    ("main", b"main"),                      # an ordinary name: the same bytes as before #638
    ("release#2", b"release%232"),
    ("release?2", b"release%3F2"),
    ("rel%41", b"rel%2541"),
    ("rel%", b"rel%25"),
    ("team/main", None),                    # by route: below
])
def test_a_branch_name_stays_one_name_in_the_path(host, provider, name, tail):
    seen, _ = host
    if tail is None:
        tail = b"team%2Fmain" if provider is GitHubProvider else b"team/main"
    assert provider(API, "o/r", "").branch_head(name) == SHA
    assert seen == [("GET", ROOT + b"branches/" + tail)]


def test_gitea_delete_and_compare_keep_the_name_whole(host):
    seen, state = host
    replies = iter([(200, {"commit": {"id": SHA}}), (204, None), (200, {"commits": []})])
    state["reply"] = lambda req: next(replies)
    git = GiteaProvider(API, "o/r", "", default_branch="team/main#2")
    assert git.delete_branch(git.default_branch, SHA)
    assert git.changed_paths(SHA) == set()
    branch = ROOT + b"branches/team/main%232"
    assert seen == [("GET", branch), ("DELETE", branch), ("GET", ROOT + b"compare/team/main%232..." + SHA.encode())]


def test_gitea_compare_escapes_an_observed_revision(host):
    """contains takes the revision Argo CD reports (core/sync.py), not a name cmapi made."""
    seen, state = host
    state["reply"] = lambda req: (404, {})
    assert GiteaProvider(API, "o/r", "").contains("v1+build%41", SHA) is False
    assert seen == [("GET", ROOT + b"compare/v1%2Bbuild%2541..." + SHA.encode())]


def test_gitea_blob_read_escapes_the_file_name_and_the_ref(host):
    seen, _ = host
    assert GiteaProvider(API, "o/r", "")._blob_sha("dir/a#b?c%41.yaml", "team/r#1") == SHA
    assert seen == [("GET", ROOT + b"contents/dir/a%23b%3Fc%2541.yaml?ref=team%2Fr%231")]


@pytest.mark.parametrize("exists", [False, True], ids=["first-run", "re-run"])
def test_git_bootstrap_names_the_default_branch_and_its_rule_whole(host, monkeypatch, tmp_path, exists):
    """The chart runs git-bootstrap on every install and upgrade. Its re-run must find the rule it made: on Gitea 1.25.5 a
    second create answers 403 "Branch protection already exist", which failed the hook (measured, the review record of #639)."""
    seen, state = host

    def gitea(req: httpx.Request) -> tuple[int, object]:
        named = b"/branches/" in req.url.raw_path or b"/branch_protections/" in req.url.raw_path
        if req.method == "GET" and named and not exists:
            return 404, {}
        return (201 if req.method == "POST" else 200), {}

    state["reply"] = gitea
    for key, value in {"CMAPI_GIT_URL": API, "CMAPI_GIT_DEFAULT_BRANCH": "team/r#2", "CMAPI_GIT_REPOSITORY": "o/r",
                       "CMAPI_GIT_ADMIN_USER": "admin", "CMAPI_GIT_ADMIN_PASSWORD": "placeholder", "CMAPI_GIT_PASSWORD": "placeholder",
                       "CMAPI_POLICIES_DIR": str(tmp_path), "CMAPI_METADATA_KEYS": str(tmp_path / "none")}.items():
        monkeypatch.setenv(key, value)
    settings.cache_clear()
    try:
        git_bootstrap.main([])
    finally:
        settings.cache_clear()
    rule = ROOT + b"branch_protections/team%2Fr%232"
    then = ("PATCH", rule) if exists else ("POST", ROOT + b"branch_protections")
    assert [s for s in seen if b"/branch" in s[1]] == [("GET", ROOT + b"branches/team/r%232"), ("GET", rule), then]
```

### Why Gitea keeps the slash and GitHub does not

One rule for every route (`safe=''` everywhere) would read simpler. It is not taken, for behaviour preservation: the
Gitea stand-in has served the request branches `cmapi/<cluster>/<requestId>` with a literal slash on CRC, and the live probe
shows Gitea's `/*` routes take the literal slash. `%2F` also worked for `GET branches/` and `compare/` in the probe, but
`DELETE` and `contents` with `%2F` were not probed, so changing the bytes of working requests is not proven safe. Mutant
M04 pins Gitea's literal slash so a later "simplification" is a decision, not an accident.

## Mutants of the final fix (`r2-outputs/mutants/mutants-output.txt`): 11 of 11 killed

| # | Mutant | Killed by |
|---|---|---|
| M01 | github: drop `safe=''` | `team/main-GitHubProvider` |
| M02 | github: drop `quote` | `release#2`, `release?2`, `rel%41`, `rel%`, `team/main` on GitHub |
| M03 | gitea `branch_head`: drop `quote` | the same five cases on Gitea |
| M04 | gitea `branch_head`: `safe=''` | `team/main-GiteaProvider`, delete-and-compare |
| M05 | gitea DELETE: drop `quote` | delete-and-compare |
| M06 | gitea `changed_paths`: drop `quote` | delete-and-compare |
| M07 | gitea `contains`: drop `quote` | observed-revision |
| M08 | gitea `_blob_sha`: drop `quote` | blob-read |
| M09 | bootstrap branch GET: drop `quote` | bootstrap first-run and re-run |
| M10 | bootstrap rule: drop `safe=''` | bootstrap first-run and re-run |
| M11 | bootstrap rule: drop `quote` | bootstrap first-run and re-run |

## What Codex missed

1. **The dead helper.** Codex wrote that it "found no production caller of this provider helper", then proposed to grow it
   to 12 lines and three tests. The right fix is deletion (above).
2. **The live behaviour.** Codex ruled from source and a socket capture; it did not run Gitea or call GitHub. The live
   probe confirms every one of its Gitea rulings, and shows that GitHub serves the literal slash too, which lowers finding 1.
3. **The reach of findings 5 and 6.** Codex rated `_blob_sha` Medium without saying that cmapi's planned file names are
   Kubernetes names, which cannot hold the characters; and `contains` Low without the observed-revision shapes.
4. **Comments at the quote sites.** The per-route slash rule was undocumented in the code; a reader would "fix" the
   asymmetry. Added at `github.py`, `gitea.py` and `git_bootstrap.py`, and pinned by M04.
5. **The other URL builders in `cmapi/src`.** Swept with `tokensave_search` (`literal: true`: `/branches/`, `/contents/`,
   `/compare/`, `branch_protections`, `f"/repos/`; the index is stale, so its hits were re-checked) and with a grep over
   `head/cmapi/src` for every `get|post|put|patch|delete|request|_call(` with an interpolated f-string:

   | Place | Value | Ruling |
   |---|---|---|
   | `git_bootstrap.py:58,67` | `/users/{bot_user}`, `/admin/users/{bot_user}` | Safe: a Gitea user name matches `^[\da-zA-Z][-.\w]*$` (source 8) |
   | `git_bootstrap.py:73,81,83` and both providers' `_repo()` | `{org}`, `{repo}`, `self.repository` | Safe on Gitea by its patterns (source 8). On GitHub the value is the operator's configuration; GitHub's name rules were not fetched |
   | `core/sync.py:99` | Argo CD namespace and Application name | Safe: Kubernetes names; the namespace is checked with `is_label` (`pipeline.py:202`) |
   | `core/clients/kube.py:223,255,277,285` | group/version, kind path, object name | Safe: Kubernetes names |
   | `tools/realm_sync.py:131-207,310` | Keycloak IDs | Safe: server-made IDs; names go through `params=` |
   | `github.py:96,105,120,247,256`, `gitea.py:42,74,159,209,250,261` | object IDs | Safe: SHAs from the host |
   | every `params=` (`github.py:139,191`, `gitea.py:229,279`) | default branch, `owner:branch`, ref | Safe: httpx encodes query values (Codex measured `ref=team%2Fr%231`; the merged blob test asserts it) |

   **A lead, not a finding (not tested):** the Keycloak realm. `core/context.py:150` and `tools/realm_sync.py:339` take the
   realm from the issuer URL, which is already in URL form. `core/identity/keycloak_admin.py:52` quotes it again
   (`quote(self.realm)`) while its token URL at line 37, and `realm_sync.py:79,90,104`, do not. Keycloak 26.6.4's
   `ReservedCharValidator` forbids `:/?#@!$&()*+,;=[]\` in a realm name but not "%" or a space (source 12), so a realm such
   as "my realm", if its issuer carries `my%20realm`, would be escaped twice at line 52 (RFC 3986 2.4 forbids that), and every
   directory lookup would answer "no such user" (`_users` returns `[]` on 404). Unverified: that Keycloak puts the realm
   in the issuer percent-encoded, and that its other layers accept such a name. Proving it needs a disposable Keycloak,
   which I did not start (a JVM, with CRC at load 11-13); the shared Keycloak must not be touched. Recommendation: the
   coordinator files it as an issue with this research mandate. It is not in `fix.diff`.

## Codex's patch reproduced

Codex's patch applied to a copy of head with `patch -p1 -F0` (clean). Its module: 19 passed with the patch, and on unpatched
head 7 failed, 12 passed, the seven Codex lists. Together with the PR's module: 25 passed.

## Git-layer and related suites on the final tree

`r2-outputs/git-layer-tests.txt`: the 20 files in `r2-outputs/git-layer-files.txt` (`test_git*`, `test_gitea*`,
`test_github*`, and every module that uses a provider or `git_bootstrap`: `test_review_h_tools_migrate.py`,
`test_third_pass_*`, `test_second_pass.py`, `test_delete_whole_folder_616.py`, ...), against PostgreSQL 16 database
`cmapi_wt605` on `127.0.0.1:55432`: **479 passed, 1 failed** in 8 min 3 s. The failure,
`test_third_pass_converged.py::test_every_shell_script_under_examples_and_deploy_is_executable`, runs `git ls-files` and the
export is not a git repository; it fails the same way on unmodified `head/` (run separately). It is environmental, not this change.

The live probe was re-run on the final tree after the last edit: the same results as above (`probe-output.txt`); the
container and its image were removed.

## What was not tested

- A real GitHub repository with a `#` or `%` in a branch name (none known to probe); GitHub's handling of `%23` and `%25`
  rests on its documentation.
- Gitea `DELETE branches/` and `contents/` with `%2F` (the fix keeps the literal slash there, which was probed for GET).
- `contains` against a live Argo CD; the revision shapes are from `core/sync.py`, not observed on a cluster.
- How a cluster ID is validated (it is part of every planned path).
- The Keycloak lead above.
- The whole service suite (the coordinator runs it), CRC and kind.
- `test_*bootstrap*` matched no file; the bootstrap tests are in `test_review_h_tools_migrate.py` and the merged module,
  both run.
