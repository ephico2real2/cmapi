# Reviewer 1 — adversarial review of PRs 453 and 455

Recommendation: request changes on both PRs. Four reproduced findings follow. Locations refer to the original PR heads, relative to their archive folders. No GitHub calls, pushes, merges, or cluster calls were made. TokenSave context/status rejected this directory as uninitialized; source inspection used the supplied archives and diffs instead. Production files in the archives are restored to their original heads; proposed changes and regression tests are in the two patches.

## Findings

### F1 — High — #453: URL-encoded Git credentials survive error redaction

Location: `pr453/cmapi/src/cmapi/core/git/base.py:136-139`.
A Git host/proxy returns HTTP 500 with `credential=Credential%2Fwith%2Bspecial%26characters-123`. Both adapters put this spelling in GitUnavailable. The raw/JSON form set does not contain quote_plus(token). This refutes R1 for the URL-encoded echo explicitly requested in this review. The same issue applies to encoded Basic password/header values. Fix: register raw and form-encoded credential spellings before forming both provider and oplog redaction sets. Complete code below and in `codex-fixes-453.patch`.

Regression: `test_encoded_git_echo`, two provider cases. Head: **2 failed** in `evidence/453-head.txt`; fixed: **2 passed** within `evidence/453-final-targeted.txt` (6 total). Each test asserts the actual 500 diagnostic survives, the encoded credential disappears, and the mask appears.

### F2 — High — #453: realm-sync transport exceptions escape with credentials

Location: `pr453/cmapi/src/cmapi/tools/realm_sync.py:72-73,82-83`.
`Realm._bearer` and `Realm.call` call httpx without catching HTTPError. A LocalProtocolError that includes the submitted secret/access-token bytes bypasses `answer` entirely and is printed by the uncaught-exception handler. Tests inject that HTTP library failure through MockTransport at both authenticated stages. This is a deterministic error-channel reproduction; it does not claim all transport errors contain credentials.

Fix: route both calls through `_request`, redact HTTPError text with the credentials already registered by `sends`, and terminate with a sanitized SystemExit. `from None` suppresses the original exception chain. No credential-bearing URL is included in the replacement diagnostic.

Regression: `test_realm_transport_error[token/admin]`. Head: **2 failed**, HTTPError escapes instead of sanitized SystemExit (`evidence/453-head.txt`). Fixed: **2 passed** within the 6-test targeted run. Both tests assert error type and mask remain, and neither credential appears.

### F3 — High — #453: successful Git host messages leak through the API

Locations: `pr453/cmapi/src/cmapi/core/git/github.py:87`, `pr453/cmapi/src/cmapi/core/git/gitea.py:203`; sink: `pr453/cmapi/src/cmapi/routers/admin.py:205`.
A 200 commits response containing the credential in `commit.message` bypasses `host_text`. `log()` formats the unredacted message, and the admin route returns that list directly. Thus “every response text” and the R2 coverage assertion are false even when every error-body substitution works. This requires the host/proxy to put the credential in a successful semantic field, consistent with the adversarial echo premise.

Fix: redact complete formatted log entries in both providers; also redact the workspace branch of GitHubProvider.log. Do not truncate repository content or alter commit identifiers used for operations.

Regression: `test_successful_commit_message_is_redacted`, both providers. Original head: **2 failed** (`evidence/453-success-head.txt`). Fixed: **2 passed** within `evidence/453-final-targeted.txt`. Tests require the returned entry and its ordinary message text to remain, preventing a vacuous empty return.

### F4 — Medium — #455: malformed paginated metadata terminates the watch loop

Location: `pr455/cmapi/src/cmapi/core/clients/kube.py:337`; exception filter: `:394`.
After a good list, a paginated relist with `items: []` and truthy string/list/number metadata passes list_items. `_fetch` invokes `.get("continue")` on that value before `_resource_version` validates metadata. AttributeError escapes `_loop`, whose handler accepts ValueError but not AttributeError. Node/report watches use chunking, so that kind stops refreshing permanently. The retained objects are not immediately deleted, but recovery never occurs. This refutes the broader watch-survival assertion in R3; it is adjacent malformed-list coverage, not a failure of the missing-items check itself.

Fix: validate page metadata before reading continue, convert malformed metadata/continuation types to BadResponse. Regression `test_chunked_bad_metadata_keeps_watch_alive` covers three truthy non-object types. Head: **3 failed**, all AttributeError at line 337 (`evidence/455-head.txt`). Fixed: **3 passed**, plus the original 30 tests (**33 passed**, `evidence/455-fixed.txt`). It drives `_loop` after a real first list and asserts the previous object, resourceVersion and last_good survive and the error is recorded. A stop event makes it deterministic without sleeps or sockets.

## R1–R4 disposition and scope

**R1: refuted** by F1–F3. The PR correctly redacts raw/JSON/Go/bytes/trailing-prefix error-body cases covered by its tests; the fix does not establish a universal sanitizer for every successful semantic field. `secret_forms` deliberately ignores raw secrets shorter than eight characters (`core/clients/redact.py:37-38`); therefore an unconditional all-credentials guarantee is outside even the documented policy. Trailing-prefix suppression is intrinsically ambiguous: an ordinary suffix identical to a credential prefix is intentionally masked (`:56-59`). No universal “nothing over-redacted” claim is made.

Cost: `redact` does a replace per form and a descending suffix-prefix scan (`redact.py:53-59`). For a fixed credential/form set its body-length cost is linear; credential-length cost is not necessarily linear because it slices/checks each possible prefix. Local benchmark, ten calls per repetition, best of three, fixed 47-character credential, nonmatching bodies: see `evidence/453-cost.txt`. 100 KB ~0.00893 s, 1 MB ~0.0891 s, 10 MB ~0.897 s. These measurements support body-linear scaling for this case, not a bound over arbitrary secret lengths or indefinitely growing oplog registrations.

**R2: refuted** by F3. Response-text inventory is saved as `evidence/453-response-scan.txt`. Host `_call` retry/refusal diagnostics and every explicit r.text error interpolation in github/gitea use host_text; GitHub.merge's remaining raw `r.text[:300]` (`github.py:218`) only selects retry classification, so that use is justified. Gitea.pr_status (`gitea.py:169`) uses status alone. Successful response data also includes branch/sha/path/content, PR links, check names and commit messages; those are semantic data, not uniformly sanitized by this PR. Repository YAML content cannot simply be replaced without changing the repository view. No universal credential-safety certification for such fields is warranted.

Realm's explicit failed-response text sinks are `_bearer`, `call`, and the LDAP sync print/exit (`realm_sync.py:75,85,293,297`), all using answer; transport failures were the uncovered channel. Response-derived clientIds are also formatted in realm progress output (`:153,174`); the patch is a fix for the reproduced findings, not a recursive sanitization policy for all server-controlled fields.

Exclusions: Keycloak admin non-200 body messages are status-only (`core/identity/keycloak_admin.py:41,60`), but its transport handling (`:48-49`) is not evidence of a general credential-safety guarantee; `_http_for_directory` (`core/context.py:74-78`) supplies the actual HTTP implementation. JWKS fetch has no credential submission and `_refresh` catches fetch/parse failures without printing the body (`core/auth.py:50-68`). git_bootstrap calls raise_for_status and prints configured names, not r.text (`tools/git_bootstrap.py:62-112`); it is explicitly outside this defect's implementation scope. Kubernetes/Argo CD are excluded by the requested #420 boundary. These exclusions do not make the broader all-path claim true.

**R3: confirmed for the specified items shapes; broader watch guarantee refuted by F4.** The source-wide items scan is `evidence/455-items-scan.txt`: Kubernetes list consumption is centralized in KubeClient.list (`core/clients/kube.py:226-234`), HubImportSource.list (`core/registry.py:207`), WatchCache._fetch (`kube.py:331,336`), and Pipeline.workload_counts (`core/pipeline.py:165-168`). The remaining items subscripts in routers/docs concern database pagination or schemas, not Kubernetes list replies. No remaining missing-items-as-empty default was found in application source. Hub refresh catches a failed source list before retirement (`registry.py:445-451`); capability checks classify BadResponse (`:388` and its exception handler); pre-delete count catches it and returns 503 (`pipeline.py:167-169`). The original 30 tests exercise these paths and CapacityLedger preservation through actual clients over MockTransport.

Null policy: the local PR cites [kubernetes#124568](https://github.com/kubernetes/kubernetes/issues/124568), [kubernetes#126286](https://github.com/kubernetes/kubernetes/pull/126286), and [kubernetes#43422](https://github.com/kubernetes/kubernetes/issues/43422) in `pr455/docs/02-technical-design-v2.md:761` and `core/clients/kube.py:78-84`. Its stated rationale is nil Go slices and null/[] equivalence. The code explicitly normalizes null to [] and preserves metadata; the regression proves this behavior. **External citation contents were not independently verified**, because GitHub network access was forbidden. The null policy is compatible with that cited rationale; independent confirmation of those upstream discussions remains for the coordinator.

**R4: negative controls demonstrated for runnable PR regressions, not an exhaustive proof of every adapter branch.** Main was reconstructed locally by reversing each supplied diff in a copy; no remote main was fetched. #453: 138 selected original tests fail on reconstructed main on leaked credential assertions, and 138 pass on PR head. #455: 29 fail/1 passes on main, and 30 pass on head. The one main pass is `test_a_hub_list_that_is_empty_still_retires_the_cluster[items-empty]`: explicit empty-array retirement already worked (see PASSES in `evidence/455-main.txt`). Main examples: #453 raw 403 reaches the leak assertion (`evidence/453-main.txt`); #455 Status object retires the existing cluster and fails connected-state assertion (`evidence/455-main.txt`). There are no collection/import failures in these negative controls. The #453 broad adapter test catches arbitrary exceptions, so its coverage should not be read as proof that every method reached its intended refusal branch; it does assert nonempty requests, errors, logs and masks. The new regressions use specific exception/return assertions.

## Runs and coordinator handoff

Every pytest command used this interpreter and flags, from the applicable archive's cmapi directory:

```sh
PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest <files> -q -p no:cacheprovider
```

- Original #455: `tests/service/test_list_without_items_421.py`: 30 passed (head); reconstructed main: 29 failed, 1 passed (`evidence/455-main.txt`).
- Original #453: `tests/service/test_git_host_redaction_424.py -k 'not request_event and not transport_error_that'`: 138 passed, 6 deselected (`evidence/453-original-head.txt`); reconstructed main: 138 failed, 6 deselected (`evidence/453-main.txt`).
- New #453 original head: `tests/service/test_codex_review.py`: first four cases 4 failed (`evidence/453-head.txt`); successful-log cases added afterward: `-k successful`, 2 failed (`evidence/453-success-head.txt`).
- Fixed #453 combined original/new selection: 144 passed, 6 deselected (`evidence/453-fixed.txt`). After extending oplog registration to encoded spellings: new tests rerun, 6 passed (`evidence/453-final-targeted.txt`).
- New #455 original head: `tests/service/test_codex_review.py`: 3 failed (`evidence/455-head.txt`). Fixed combined original/new suites: 33 passed (`evidence/455-fixed.txt`).
- Patch syntax/application checked with reverse dry runs on the tested fixed trees, then forward dry runs on restored heads (evidence patch-check files).

Coordinator: run #453 `test_a_transport_error_that_shows_the_header_holds_no_token` (local socket) and the five `test_no_request_event_api_answer_or_log_line_holds_the_token` cases (world/PostgreSQL fixtures). An initial unfiltered attempt had 126 passes, socket-bind PermissionError, and was interrupted in database migration after 87.29 seconds (`evidence/453-unfiltered-summary.txt`); it does not establish their behavior. They were excluded from the completed reproducible runs above. No escalation requested. Broader suites and live Kubernetes tests were not run.

Apply proposed patches from their respective archive roots with `patch -p1 < ../codex-fixes-453.patch` / `patch -p1 < ../codex-fixes-455.patch`. New tests are included in the patches; copies also live in evidence. No patch is represented as fixing every possible semantic-data echo.

## Full fix code and tests

The following patches contain all imports, replacement code, and regression tests without omitted additions.

### PR 453

```diff
--- a/cmapi/src/cmapi/core/git/base.py
+++ b/cmapi/src/cmapi/core/git/base.py
@@ -15,6 +15,7 @@
 
 import base64
 import ssl
+from urllib.parse import quote_plus
 from dataclasses import dataclass
 from datetime import datetime
 from typing import Any, Iterable, Literal, Mapping
@@ -132,7 +133,8 @@
                                     auth=basic_auth)
         from cmapi.core.git.oplog import register_secret
 
-        credentials = credential_values(token, basic_auth)
+        credentials = tuple({spelling for value in credential_values(token, basic_auth)
+                             for spelling in (value, quote_plus(value))})
         for value in credentials:
             register_secret(value)
         self._forms = tuple(sorted({form for value in credentials for form in secret_forms(value)}, key=len, reverse=True))
--- a/cmapi/src/cmapi/core/git/github.py
+++ b/cmapi/src/cmapi/core/git/github.py
@@ -82,9 +82,9 @@
 
     def log(self, n: int = 20) -> list[str]:
         if self.workspace is not None:
-            return self.workspace.log(n)
+            return [self.redact(line) for line in self.workspace.log(n)]
         r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "per_page": n})
-        return [f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}" for c in r.json()]
+        return [self.redact(f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}") for c in r.json()]
 
     def contains(self, revision: str, sha: str) -> bool:
         return self._git().contains(revision, sha)
--- a/cmapi/src/cmapi/core/git/gitea.py
+++ b/cmapi/src/cmapi/core/git/gitea.py
@@ -200,7 +200,7 @@
 
     def log(self, n: int = 20) -> list[str]:
         r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "limit": n})
-        return [f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}" for c in r.json()]
+        return [self.redact(f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}") for c in r.json()]
 
     def protect_default_branch(self, contexts: list[str]) -> None:
         """One-time setup: nobody pushes to main; merges need every context green (the cmapi check)."""
--- a/cmapi/src/cmapi/tools/realm_sync.py
+++ b/cmapi/src/cmapi/tools/realm_sync.py
@@ -33,7 +33,7 @@
 
 import httpx
 
-from cmapi.core.clients.redact import redact_cut, secret_forms
+from cmapi.core.clients.redact import redact, redact_cut, secret_forms
 
 RFC9068_HEADER = "access.token.header.type.rfc9068"      # Keycloak's client attribute, OIDCConfigAttributes (26.6.4)
 _SENT: tuple[str, ...] = ()                               # every form of every credential this run sends, longest first
@@ -66,10 +66,17 @@
         self._token: tuple[str, float] | None = None
         sends(secret)
 
+    def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
+        try:
+            return self.http.request(method, url, **kw)
+        except httpx.HTTPError as exc:
+            # Suppress the original exception: its header text must not reach the Job log.
+            raise SystemExit(redact(f"{method}: {type(exc).__name__}: {exc}", _SENT)) from None
+
     def _bearer(self) -> str:
         if self._token and time.time() < self._token[1]:
             return self._token[0]
-        r = self.http.post(f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
+        r = self._request("POST", f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
                            data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.secret})
         if r.status_code != 200:
             sys.exit(f"cannot sign in as {self.client_id} in realm {self.realm}: {r.status_code} {answer(r, 200)}")
@@ -79,7 +86,7 @@
         return self._token[0]
 
     def call(self, method: str, path: str, *, ok: tuple[int, ...] = (200, 201, 204), **kw: Any) -> httpx.Response:
-        r = self.http.request(method, f"{self.base}/admin/realms/{self.realm}{path}",
+        r = self._request(method, f"{self.base}/admin/realms/{self.realm}{path}",
                               headers={"Authorization": f"Bearer {self._bearer()}"}, **kw)
         if r.status_code not in ok:
             sys.exit(f"{method} {path}: {r.status_code} {answer(r, 300)}")
--- /dev/null
+++ b/cmapi/tests/service/test_codex_review.py
@@ -0,0 +1,47 @@
+from urllib.parse import quote_plus
+import httpx
+import pytest
+from cmapi.core.git.github import GitHubProvider
+from cmapi.core.git.gitea import GiteaProvider
+from cmapi.core.git.base import GitUnavailable
+from cmapi.tools.realm_sync import Realm
+
+@pytest.mark.parametrize('provider', [GitHubProvider, GiteaProvider])
+def test_encoded_git_echo(provider):
+    secret = 'Credential/with+special&characters-123'
+    encoded = quote_plus(secret)
+    git = provider('https://git.test', 'o/r', secret)
+    git._client = httpx.Client(base_url='https://git.test', transport=httpx.MockTransport(
+        lambda r: httpx.Response(500, text='rejected credential=' + encoded)))
+    with pytest.raises(GitUnavailable) as caught:
+        git.branch_head('main')
+    assert 'the Git host answered 500' in str(caught.value)
+    assert encoded not in str(caught.value)
+    assert '***' in str(caught.value)
+
+@pytest.mark.parametrize('stage', ['token', 'admin'])
+def test_realm_transport_error(stage):
+    secret = 'RealmSecret-with-special-123'
+    bearer = 'AccessToken-with-special-456'
+    rm = Realm('https://kc.test', 'cmapi', 'admin', secret, True)
+    def handle(request):
+        if request.url.path.endswith('/token') and stage == 'admin':
+            return httpx.Response(200, json={'access_token': bearer})
+        value = secret if stage == 'token' else bearer
+        raise httpx.LocalProtocolError('Illegal header value ' + repr(value.encode()))
+    rm.http = httpx.Client(transport=httpx.MockTransport(handle))
+    with pytest.raises(SystemExit) as caught:
+        rm.call('GET', '/users')
+    message = str(caught.value)
+    assert 'LocalProtocolError' in message and '***' in message
+    assert secret not in message and bearer not in message
+
+@pytest.mark.parametrize('provider', [GitHubProvider, GiteaProvider])
+def test_successful_commit_message_is_redacted(provider):
+    secret = 'Credential-with-special-123'
+    git = provider('https://git.test', 'o/r', secret)
+    git._client = httpx.Client(base_url='https://git.test', transport=httpx.MockTransport(
+        lambda r: httpx.Response(200, json=[{'sha': 'a' * 40, 'commit': {'message': 'proxy echoed ' + secret}}])))
+    answer = git.log()
+    assert len(answer) == 1 and 'proxy echoed' in answer[0]
+    assert secret not in answer[0] and '***' in answer[0]
```

### PR 455

```diff
--- a/cmapi/src/cmapi/core/clients/kube.py
+++ b/cmapi/src/cmapi/core/clients/kube.py
@@ -334,7 +334,12 @@
         while True:
             out = self.client.list(kind, limit=self.chunk, continue_=token)
             values.extend((self._key(o), self._value(kind, o)) for o in out["items"])
-            token = (out.get("metadata") or {}).get("continue") or None
+            meta = out.get("metadata")
+            if not isinstance(meta, Mapping):
+                raise BadResponse(kind, 200, "metadata is not an object")
+            token = meta.get("continue") or None
+            if token is not None and not isinstance(token, str):
+                raise BadResponse(kind, 200, "metadata.continue is not a string")
             if token is None:
                 return values, self._resource_version(kind, out)
             del out                         # the page's raw objects go before the next page arrives
--- /dev/null
+++ b/cmapi/tests/service/test_codex_review.py
@@ -0,0 +1,25 @@
+import httpx
+import pytest
+from cmapi.core.clients.kube import KubeClient, WatchCache
+
+@pytest.mark.parametrize('metadata', ['broken', ['broken'], 42])
+def test_chunked_bad_metadata_keeps_watch_alive(metadata):
+    client = KubeClient('C', 'https://kube.test', 'reader-token-123', insecure=True)
+    bodies = iter([
+        {'items': [{'metadata': {'name': 'a'}}], 'metadata': {'resourceVersion': '1'}},
+        {'items': [], 'metadata': metadata},
+    ])
+    cache = WatchCache(client, ('Namespace',), chunk=1)
+    def handle(request):
+        body = next(bodies)
+        if body['metadata'] == metadata:
+            cache._stop.set()
+        return httpx.Response(200, json=body)
+    client._client = httpx.Client(transport=httpx.MockTransport(handle), base_url='https://kube.test')
+    cache._list('Namespace')
+    before = cache.state['Namespace'].last_good
+    cache._loop('Namespace')
+    state = cache.state['Namespace']
+    assert list(state.items) == ['/a']
+    assert state.last_good == before and state.resource_version == '1'
+    assert 'metadata' in state.error
```
