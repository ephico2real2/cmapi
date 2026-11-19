OB3 (Opus 5.5), reviewer 2 on Codex's review of #453 (head a9f219e, #424/#454) and #455 (head 7785e68, #421). 2026-11-19.
Depth: DEEP = F2 (driven on a real local socket through real httpx 0.28.1 + h11 0.16.0, not only MockTransport) and F4/G-455
(the kind thread driven with start(), a bad relist, then recovery; plus Codex's tree measured). MEDIUM = F1, F3 (MockTransport, one
harness each, plus Codex's tree measured). SHALLOW: none. Cost measured (logs/cost-453.txt). No cluster, no network, no git writes.
Trees: copies of pr453/ and pr455/ under ob3/ (head, fix, codex = Codex's patch, credfix = fixes-453 + credentials.patch), deleted
after the runs; rebuild them from the archives and the patches. Import proof: cmapi from ob3/head453/cmapi/src (printed).
Runs: ob3/run.sh, chain.sh, chain2.sh over suite.sh (one job at a time, PostgreSQL 127.0.0.1:55432, CMAPI_TEST_REQUIRE_SSHD=1,
PYTHONDONTWRITEBYTECODE=1, --basetemp under ob3/tmp). logs/chain453.txt is an aborted first run on incomplete copies (no
examples/ deploy/): ignore it.

==================================================================== VERDICTS ON CODEX'S FINDINGS

F1 #453 form-encoded credential echoed by a Git error. CONFIRMED on head (logs/head453-codex-tests.log: "credential=Credential%2F
  with%2Bspecial%26characters-123" survives). KEPT, CHANGED. Severity High -> Low: the token goes out in the Authorization header,
  never form-encoded, so only a proxy that URL-encodes what it echoes produces it, and a GitHub/Gitea token's alphabet is unchanged
  by quote_plus (measured: forms head=1 fix=1 for a ghp_ token). Codex's fix is a second quote_plus site (realm_sync.sends already
  has one) and covers only the values the provider registers: oplog.register_secret's other caller, the Git layer token
  (workspace.py:101), still has no encoded form (test_the_git_log_registry_takes_the_same_forms FAILS on Codex's tree), and it
  registers the encoded spelling of a value under MIN_SECRET=8 (realm_sync on the head too: "a/b&c+d" -> 'a%2Fb%26c%2Bd'
  registered; test_a_value_shorter_than_eight_characters... fails on head and on Codex's tree). Correction: one function
  `sent_forms` in core/clients/redact.py (secret_forms of the value and of quote_plus(value), none below MIN_SECRET), used by
  HostGitProvider._forms, oplog.register_secret and realm_sync.sends. Cost: linear in the body; +1 form for a special-character
  secret, 1.04-1.08x at 0.1-10 MB, 1.00x for a plain token (logs/cost-453.txt).
F2 #453 realm-sync transport errors escape with credentials. CONFIRMED on head, on a REAL socket: Keycloak's access_token with a
  trailing newline -> h11 "Illegal header value b'Bearer BearerSecret-0123456789\n'" printed by the uncaught traceback, exit 1
  (logs/realm-socket-head453.txt). The token stage is defensive only (the secret is in the form body, which h11 does not check).
  KEPT, Medium (needs Keycloak or a proxy to return an illegal header value). CHANGED: Codex's message drops the call
  ("GET: LocalProtocolError: ..."); mine says which ("GET /users: ...", "sign in as cmapi-realm-admin in realm cmapi: ...").
  Same exit code 1 as the uncaught error; `from None` keeps the raw error out of the printed chain (asserted on
  traceback.format_exception). On Codex's tree my two realm tests fail only on that missing call name, not on a leak.
F3 #453 commit messages of a 200 answer reach GET /api/v1/admin/git-log (reports:read). CONFIRMED on head. KEPT, Low (the token
  must already be in a commit message of the repository). CHANGED: subject redacted, sha untouched (HostGitProvider.commit_lines,
  shared by both providers); the Git-layer branch is redacted with oplog's registry, which holds the Git layer's token. Codex
  used the provider's forms there: test_the_git_layer_log_is_redacted_with_the_git_layer_token FAILS on Codex's tree. (That
  branch runs only in the worker, which serves no /git-log: defence in depth.)
F4 #455 malformed page metadata kills the watch thread. CONFIRMED on head (AttributeError 'str'/'list'/'int' object has no
  attribute 'get', kube.py:337, outside _loop's filter :394). KEPT, Medium, CHANGED: Codex's `meta.get("continue") or None`
  reads continue false / 0 / [] as the LAST page and commits a partial list: measured on Codex's tree the cache becomes ['/b']
  and drops '/a' (the #421 bug class: a partial list read as complete; the head does the same). Mine: `_continue` refuses any
  non-string token and any non-object metadata as BadResponse; absent metadata keeps the head's path (resourceVersion check).

==================================================================== WHAT CODEX MISSED

G1 #455 Medium: an item without a string metadata.name ({} , metadata "x", no name) -> KeyError/TypeError in WatchCache._key ends
  the kind's thread (head: KeyError 'metadata', KeyError 'name', AttributeError); now BadResponse. 8 cases fail on head and Codex.
G2 #455 Medium: a watch event that is not an object, or whose object/metadata is not an object, or that has no metadata.name,
  ends the thread (head: AttributeError/KeyError in _event); now BadResponse -> relist. 5 cases fail on head and Codex.
G3 #455 Medium: the projection. reduce_node (nodes.py:52) calls status.get: a Node whose status is a string raised AttributeError
  and ended the Node watch for good. Fix: a last net in WatchCache._loop (log.exception "watch_cache_failed", redacted text, the
  same backoff), as ClusterRegistry.refresh has for #419. Fails on head and Codex. The thread itself: start(), good list, bad
  relist, good relist -> recovered with rv 3 (fails on head; passes on Codex's tree for its own metadata case).
G4 #453 Low: the encoded-form and MIN_SECRET inconsistencies in F1 (above), and the Git layer token's log forms.
G5 credentials.patch (#444/#445/#447): applies to #453's head, but on #453 + fixes-453 `git apply --check` FAILS at oplog.py:15
  (context line imports secret_forms; logs/credentials-old-gitapply-on-fix453.txt). Regenerated against #453 + fixes-453, same
  +/- lines (diffed): review-288b/ob3/credentials.patch; the old one kept as credentials-on-pr453.superseded.patch. Its offline
  test file: 12 passed on #453 + fixes-453 + credentials.patch.

==================================================================== COUNTS (same selection on each tree)
#453: test_git_host_redaction_424, test_cluster_token_redaction_420, test_cluster_token_client_420, test_registry_survives_419,
  test_git_layer, test_git_trust, test_github_statuses, test_second_pass, test_review_288_f5, test_third_pass_fixes,
  test_review_r181_realm_sync_security, test_review_r184_realm_sync + Codex's test_codex_review.py + test_redaction_review_453.py
  head a9f219e          18 failed, 391 passed (6 Codex + 12 mine; logs/head453-sel.log)
  fixes-453            409 passed (logs/fix453-sel.log)
  + credentials.patch  409 passed; offline test_git_credentials_review.py 12 passed
  Codex's tree          5 failed, 158 passed (my tests + Codex's + the #424 file; logs/codex453-review.log)
  (my control test passes on head by design: a plain token gets no extra form)
#455: test_list_without_items_421 + the four common files + test_codex_review.py + test_watch_review_455.py
  head 7785e68          28 failed, 185 passed (logs/head455-sel.log); fixes-455 213 passed (logs/fix455-sel.log)
  After loosening two message asserts to the field name (behaviour, not wording): my 25 cases head 25 failed, fixed 25 passed,
  Codex's tree 17 failed 8 passed (logs/chain2.txt).
Patches: git apply --check clean on pr453/ and pr455/; the applied trees equal the tested trees (logs/patch-apply-check.txt).
Docs: docs/02 sentences for #424 and #421 updated in the patches.

==================================================================== HOUSEKEEPING
git status --short of /Users/olasumbo/gitRepos/cmapi-design: empty before and after (nothing touched there; no git writes).
pr453/, pr455/, evidence/, Codex's files: not modified. Deleted (all mine): ob3/{head,fix,codex}453, credfix453, {head,fix,codex}455,
ob3/tmp. Kept: ob3/run.sh chain.sh chain2.sh mkpatch.sh, drive/realm_socket.py drive/cost.py, tests/, logs/, the patches, out.txt.
In review-288b/ob3: credentials.patch replaced (old kept as credentials-on-pr453.superseded.patch).

==================================================================== fixes-453.patch (verbatim, -p1 against pr453/)
--- a/cmapi/src/cmapi/core/clients/redact.py
+++ b/cmapi/src/cmapi/core/clients/redact.py
@@ -13,11 +13,15 @@
   JSON string inside a JSON string;
 - the repr of its bytes, which an HTTP library's "illegal header value b'...'" error shows.
 
+A credential a client sends (`sent_forms`) has one more spelling: form-encoded (quote_plus), as httpx writes a form body or a
+query string, and as a proxy that echoes a request URL-encodes it. Each of its forms above is removed too.
+
 A text that ends in the start of a form (8 characters or more) loses that start too: a body cut by the server or a proxy.
 """
 from __future__ import annotations
 
 import json
+from urllib.parse import quote_plus
 
 MASK = "***"                    # as the Git layer's redaction writes it (core/git/oplog.py)
 MIN_SECRET = 8                  # a shorter value is no credential, and replacing it would garble every message
@@ -43,6 +47,15 @@
     return tuple(sorted((f for f in forms if len(f) >= MIN_SECRET), key=len, reverse=True))
 
 
+def sent_forms(secret: str | None) -> tuple[str, ...]:
+    """`secret_forms` of a credential and of its form-encoded spelling, longest first: the one set of forms every client that
+    sends a credential removes (the Git hosts, the realm sync, the Git layer's log; #424). A value shorter than MIN_SECRET has
+    none in any spelling, as in `secret_forms`."""
+    if not secret or len(secret) < MIN_SECRET:
+        return ()
+    return tuple(sorted({*secret_forms(secret), *secret_forms(quote_plus(secret))}, key=len, reverse=True))
+
+
 def redact(text: str, forms: tuple[str, ...]) -> str:
     """`text` without any form of the secret, nor a trailing start of one. Call it on the whole text, then cut."""
     if not forms or not text:
--- a/cmapi/src/cmapi/core/git/base.py
+++ b/cmapi/src/cmapi/core/git/base.py
@@ -21,7 +21,7 @@
 
 import httpx
 
-from cmapi.core.clients.redact import redact, redact_cut, secret_forms
+from cmapi.core.clients.redact import redact, redact_cut, sent_forms
 from cmapi.core.ports import PrRef, PrStatus
 
 CheckState = Literal["pending", "success", "failure"]
@@ -135,7 +135,7 @@
         credentials = credential_values(token, basic_auth)
         for value in credentials:
             register_secret(value)
-        self._forms = tuple(sorted({form for value in credentials for form in secret_forms(value)}, key=len, reverse=True))
+        self._forms = tuple(sorted({form for value in credentials for form in sent_forms(value)}, key=len, reverse=True))
 
     def _headers(self, token: str) -> dict[str, str]:
         return {"Authorization": f"token {token}", "Accept": "application/json"}
@@ -148,6 +148,11 @@
         """The host's answer as error text: redacted, then cut to `limit` characters (#424)."""
         return redact_cut(r.text, self._forms, limit)
 
+    def commit_lines(self, commits: Iterable[Mapping[str, Any]]) -> list[str]:
+        """`<short sha> <subject>` of each commit of the host's list. The subject is text the host returns, and GET
+        /api/v1/admin/git-log serves it to every reports:read caller, so it is redacted; the sha is left as it is (#424)."""
+        return [f"{c['sha'][:8]} {self.redact(c['commit']['message'].splitlines()[0])}" for c in commits]
+
     def _call(self, operation: str, method: str, path: str, *, ok: tuple[int, ...] = (200, 201, 204),
               log_fields: Mapping[str, Any] | None = None, **kw: Any) -> httpx.Response:
         from cmapi.core.git.oplog import Op
--- a/cmapi/src/cmapi/core/git/github.py
+++ b/cmapi/src/cmapi/core/git/github.py
@@ -82,9 +82,12 @@
 
     def log(self, n: int = 20) -> list[str]:
         if self.workspace is not None:
-            return self.workspace.log(n)
+            # The Git layer's token is in oplog's registry, not in this provider's forms (#424).
+            from cmapi.core.git.oplog import redact as redact_registered
+
+            return [redact_registered(line) for line in self.workspace.log(n)]
         r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "per_page": n})
-        return [f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}" for c in r.json()]
+        return self.commit_lines(r.json())
 
     def contains(self, revision: str, sha: str) -> bool:
         return self._git().contains(revision, sha)
--- a/cmapi/src/cmapi/core/git/gitea.py
+++ b/cmapi/src/cmapi/core/git/gitea.py
@@ -200,7 +200,7 @@
 
     def log(self, n: int = 20) -> list[str]:
         r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "limit": n})
-        return [f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}" for c in r.json()]
+        return self.commit_lines(r.json())
 
     def protect_default_branch(self, contexts: list[str]) -> None:
         """One-time setup: nobody pushes to main; merges need every context green (the cmapi check)."""
--- a/cmapi/src/cmapi/core/git/oplog.py
+++ b/cmapi/src/cmapi/core/git/oplog.py
@@ -7,7 +7,7 @@
 
 No secret reaches a log line: every value the event carries passes through redact(), which removes each secret registered
 with register_secret() (the Git token, the platform token) wherever it appears, in each form core/clients/redact.py names:
-raw, JSON-escaped once or twice, as a bytes repr, and a trailing start of one (#424).
+raw, form-encoded, JSON-escaped once or twice, as a bytes repr, and a trailing start of one (#424).
 """
 from __future__ import annotations
 
@@ -17,7 +17,7 @@
 from contextvars import ContextVar
 from typing import Any, Iterator
 
-from cmapi.core.clients.redact import redact as redact_forms, secret_forms
+from cmapi.core.clients.redact import redact as redact_forms, sent_forms
 from cmapi.core.observability import GIT_DURATION, GIT_OPS, log
 
 _CONTEXT: ContextVar[dict[str, Any]] = ContextVar("cmapi_git_context", default={})
@@ -31,7 +31,7 @@
 def register_secret(value: str | None) -> None:
     """A value that must never be logged. Short values are refused: redacting a three-letter word would garble every line."""
     global _FORMS
-    forms = secret_forms(value)
+    forms = sent_forms(value)
     if forms:
         with _SECRETS_LOCK:
             _FORMS = tuple(sorted(set(_FORMS) | set(forms), key=len, reverse=True))
--- a/cmapi/src/cmapi/tools/realm_sync.py
+++ b/cmapi/src/cmapi/tools/realm_sync.py
@@ -29,11 +29,10 @@
 import sys
 import time
 from typing import Any
-from urllib.parse import quote_plus
 
 import httpx
 
-from cmapi.core.clients.redact import redact_cut, secret_forms
+from cmapi.core.clients.redact import redact, redact_cut, sent_forms
 
 RFC9068_HEADER = "access.token.header.type.rfc9068"      # Keycloak's client attribute, OIDCConfigAttributes (26.6.4)
 _SENT: tuple[str, ...] = ()                               # every form of every credential this run sends, longest first
@@ -41,10 +40,9 @@
 
 def sends(value: str | None) -> None:
     """A credential this sync puts in a request: never in the text it prints from an answer. A secret in a form body (the
-    client secret) is sent form-encoded (httpx's urlencode, quote_plus), so that spelling is one more form an echo can show."""
+    client secret) is sent form-encoded (httpx's urlencode, quote_plus): `sent_forms` holds that spelling's forms too."""
     global _SENT
-    forms = {*secret_forms(value), *secret_forms(quote_plus(value or ""))}
-    _SENT = tuple(sorted({*_SENT, *forms}, key=len, reverse=True))
+    _SENT = tuple(sorted({*_SENT, *sent_forms(value)}, key=len, reverse=True))
 
 
 def answer(r: httpx.Response, limit: int) -> str:
@@ -65,12 +63,22 @@
         self.client_id, self.secret = client_id, secret
         self._token: tuple[str, float] | None = None
         sends(secret)
+
+    def _request(self, method: str, url: str, what: str, **kw: Any) -> httpx.Response:
+        """One request, or the Job's end with a redacted message. An HTTP library's error can show the header it refused
+        ("Illegal header value b'Bearer ...'": the access token is Keycloak's text, measured with h11). Left uncaught, its
+        traceback reached the Job log unredacted; `from None` keeps the raw error out of the printed chain (#424)."""
+        try:
+            return self.http.request(method, url, **kw)
+        except httpx.HTTPError as exc:
+            raise SystemExit(redact(f"{what}: {type(exc).__name__}: {exc}", _SENT)) from None
 
     def _bearer(self) -> str:
         if self._token and time.time() < self._token[1]:
             return self._token[0]
-        r = self.http.post(f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
-                           data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.secret})
+        r = self._request("POST", f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
+                          f"sign in as {self.client_id} in realm {self.realm}",
+                          data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.secret})
         if r.status_code != 200:
             sys.exit(f"cannot sign in as {self.client_id} in realm {self.realm}: {r.status_code} {answer(r, 200)}")
         body = r.json()
@@ -79,8 +87,8 @@
         return self._token[0]
 
     def call(self, method: str, path: str, *, ok: tuple[int, ...] = (200, 201, 204), **kw: Any) -> httpx.Response:
-        r = self.http.request(method, f"{self.base}/admin/realms/{self.realm}{path}",
-                              headers={"Authorization": f"Bearer {self._bearer()}"}, **kw)
+        r = self._request(method, f"{self.base}/admin/realms/{self.realm}{path}", f"{method} {path}",
+                          headers={"Authorization": f"Bearer {self._bearer()}"}, **kw)
         if r.status_code not in ok:
             sys.exit(f"{method} {path}: {r.status_code} {answer(r, 300)}")
         return r
--- a/docs/02-technical-design-v2.md
+++ b/docs/02-technical-design-v2.md
@@ -756,7 +756,7 @@
 **Client rules.** Every per-cluster call follows these:
 
 - An apiUrl that carries userinfo is refused, because httpx would send it as Basic auth.
-- The findings of the parse step are fixed sentences and hold no token. The findings of the connect, identity and capability steps are the error text of the call: for a `KubeError`, the status, the path and the first 300 characters of the response body. `GET /api/v1/clusters` shows them to every holder of `clusters:read`. Built (#420): the token, and its JSON-escaped forms, are redacted from every error message before it is truncated. Each `KubeClient` replaces every form of its own token with `***` in the body of an HTTP error and in the text of a transport error, before `KubeError` cuts the body to 300 characters (`core/clients/redact.py`, `KubeClient._error`, `core/clients/kube.py`). The forms are the token as sent, its JSON escapes as Python and Go write them (Go also escapes <, > and &), once and twice, and the repr of its bytes that an "illegal header value" error shows. A text that ends in the first 8 characters or more of a form, as a body the server cut, loses them too. `ClusterRegistry._set` redacts the import Secret's token from each finding again, before it is stored, served and logged as `cluster_import`, and `HubImportSource` redacts the hub's own token from its list error. This holds for the reader client of each cluster and for the deliverer client of the delivery jobs. A token shorter than 8 characters is not redacted. Built (#424): the same rule holds for the Git host. The PR adapters put the host's answer into errors, which become request events (the Requests tab), the job's error, log lines and the `git-unavailable` answer of the API. Each one takes that text through `HostGitProvider.host_text`, which removes every form of the bot's credential and only then cuts it to 200 or 300 characters (`core/git/base.py`, `github.py`, `gitea.py`). The credential is the token, or with Basic auth the password and the header's value, base64 of user:password. A transport error's text is redacted too. Every value of a Git log event passes through `oplog.redact` with the same forms and the trailing-start rule, the git process's stderr included (`core/git/oplog.py`). The git processes hold no token in a URL or an argument (`core/git/transport.py`). The realm sync Job prints Keycloak's answer when a call fails, and removes from it the client secret (also form-encoded, as it is sent), its access token, the LDAP bind password and the test users' passwords (`answer` and `sends`, `tools/realm_sync.py`). The Keycloak directory client puts only the HTTP status in its errors (`core/identity/keycloak_admin.py`).
+- The findings of the parse step are fixed sentences and hold no token. The findings of the connect, identity and capability steps are the error text of the call: for a `KubeError`, the status, the path and the first 300 characters of the response body. `GET /api/v1/clusters` shows them to every holder of `clusters:read`. Built (#420): the token, and its JSON-escaped forms, are redacted from every error message before it is truncated. Each `KubeClient` replaces every form of its own token with `***` in the body of an HTTP error and in the text of a transport error, before `KubeError` cuts the body to 300 characters (`core/clients/redact.py`, `KubeClient._error`, `core/clients/kube.py`). The forms are the token as sent, its JSON escapes as Python and Go write them (Go also escapes <, > and &), once and twice, and the repr of its bytes that an "illegal header value" error shows. A text that ends in the first 8 characters or more of a form, as a body the server cut, loses them too. `ClusterRegistry._set` redacts the import Secret's token from each finding again, before it is stored, served and logged as `cluster_import`, and `HubImportSource` redacts the hub's own token from its list error. This holds for the reader client of each cluster and for the deliverer client of the delivery jobs. A token shorter than 8 characters is not redacted. Built (#424): the same rule holds for the Git host. The PR adapters put the host's answer into errors, which become request events (the Requests tab), the job's error, log lines and the `git-unavailable` answer of the API. Each one takes that text through `HostGitProvider.host_text`, which removes every form of the bot's credential and only then cuts it to 200 or 300 characters (`core/git/base.py`, `github.py`, `gitea.py`). The credential is the token, or with Basic auth the password and the header's value, base64 of user:password. Each value's forms include its form-encoded spelling (quote_plus), which a proxy that echoes a request can show; one function gives them to every client that sends a credential (`sent_forms`, `core/clients/redact.py`), and a value shorter than 8 characters has none in any spelling. A transport error's text is redacted too. The commit subjects of `GET /api/v1/admin/git-log` are text the host returns, and are redacted the same way (`HostGitProvider.commit_lines`). Every value of a Git log event passes through `oplog.redact` with the same forms and the trailing-start rule, the git process's stderr included (`core/git/oplog.py`). The git processes hold no token in a URL or an argument (`core/git/transport.py`). The realm sync Job prints Keycloak's answer when a call fails, and removes from it the client secret (also form-encoded, as it is sent), its access token, the LDAP bind password and the test users' passwords (`answer` and `sends`, `tools/realm_sync.py`). A transport error of the sync (h11 names a header value it refuses, the access token included) ends the Job with that text redacted and without the raw error's traceback (`Realm._request`). The Keycloak directory client puts only the HTTP status in its errors (`core/identity/keycloak_admin.py`).
 - Built: outcomes are classified by who produced the error. A transport problem this process raised is `unreachable` or `cert-verify-failed`. A 401 or 403 on `GET /version`, and a failure of the identity check, are `auth_failed`. A 403 on the list of namespaces is `forbidden`, with the finding `missing grant: list namespaces`. Built (#419): an answer to `GET /version`, the identity check or the list of namespaces that is not JSON, is JSON but not an object, or lacks the field the call reads (`metadata.name` of users/\~, `status.userInfo.username` of a SelfSubjectReview) is `bad-response`, with a finding that names the path, the HTTP status and what was wrong, never the body (`BadResponse`, `core/clients/kube.py`). **Not built:** an HTTP error other than 401 and 403 is still `unreachable` on `GET /version`, `auth_failed` on the identity check and `forbidden` (`missing grant: <the error>`) on the list of namespaces, not `bad-response`.
 - **Not built (#421):** a 200 response without an items field is read as an empty list (`out.get("items", [])`, `WatchCache._fetch`, `core/clients/kube.py`, and `HubImportSource.list`, `core/registry.py`, which then retires every cluster).
 - Built for the node and policy-report caches only: they list in pages and follow continue tokens (`chunk` in `NodeCache` and `ReportCache`; `WatchCache._fetch`, `limit` and `continue_`). The cache of namespaces, ResourceQuotas and LimitRanges that the registry builds has no `chunk`, so it lists each kind in one call (`ClusterRegistry._check`).
--- /dev/null
+++ b/cmapi/tests/service/test_redaction_review_453.py
@@ -0,0 +1,156 @@
+"""Review of #453 (#424, #454): Codex's F1-F3 as OB3 corrected them. Offline: httpx.MockTransport, and one real local socket
+for the h11 error a refused header value raises. Each test fails on #453's head (a9f219e) and passes with fixes-453.patch."""
+from __future__ import annotations
+
+import json
+import threading
+import traceback
+from http.server import BaseHTTPRequestHandler, HTTPServer
+from urllib.parse import quote_plus
+
+import httpx
+import pytest
+
+import cmapi.core.git.oplog as oplog
+import cmapi.tools.realm_sync as realm_sync
+from cmapi.core.clients.redact import MASK, secret_forms
+from cmapi.core.git.base import GitUnavailable
+from cmapi.core.git.gitea import GiteaProvider
+from cmapi.core.git.github import GitHubProvider
+from cmapi.tools.realm_sync import Realm
+
+SPECIAL = "Credential/with+special&characters-123"     # a password or token with characters a form encoding changes
+PLAIN = "ghp_0123456789abcdefABCDEF0123456789abcd"      # a GitHub token's alphabet: form encoding leaves it as it is
+
+
+@pytest.fixture(autouse=True)
+def registries(monkeypatch):
+    """Each test with empty registries: oplog's and the realm sync's are process-global."""
+    monkeypatch.setattr(oplog, "_FORMS", ())
+    monkeypatch.setattr(realm_sync, "_SENT", ())
+
+
+def offline(provider, handler, **kw):
+    git = provider("https://git.test", "o/r", kw.pop("token", SPECIAL), **kw)
+    git._client.close()
+    git._client = httpx.Client(base_url="https://git.test", transport=httpx.MockTransport(handler))
+    return git
+
+
+# ---------------------------------------------------------------- F1: the form-encoded spelling, in one definition
+
+@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
+def test_a_form_encoded_echo_of_the_token_is_redacted(provider):
+    git = offline(provider, lambda r: httpx.Response(500, text="rejected credential=" + quote_plus(SPECIAL)))
+    with pytest.raises(GitUnavailable) as caught:
+        git.branch_head("main")
+    assert "the Git host answered 500: rejected credential=" + MASK in str(caught.value)
+    assert quote_plus(SPECIAL) not in str(caught.value)
+
+
+def test_a_form_encoded_echo_of_a_basic_auth_password_is_redacted():
+    git = offline(GiteaProvider, lambda r: httpx.Response(502, text="denied password=" + quote_plus(SPECIAL)),
+                  token="", basic_auth=("bot", SPECIAL))
+    with pytest.raises(GitUnavailable) as caught:
+        git.branch_head("main")
+    assert quote_plus(SPECIAL) not in str(caught.value) and "denied password=" + MASK in str(caught.value)
+
+
+def test_the_git_log_registry_takes_the_same_forms():
+    """oplog.redact covers every request event and the Git layer's stderr: the same forms as the provider's own."""
+    oplog.register_secret(SPECIAL)
+    assert oplog.redact("remote: " + quote_plus(SPECIAL)) == "remote: " + MASK
+
+
+def test_one_definition_for_the_git_hosts_the_git_log_and_the_realm_sync():
+    git = offline(GitHubProvider, lambda r: httpx.Response(200))
+    realm_sync.sends(SPECIAL)
+    both = tuple(sorted({*secret_forms(SPECIAL), *secret_forms(quote_plus(SPECIAL))}, key=len, reverse=True))
+    assert git._forms == oplog._FORMS == realm_sync._SENT == both
+
+
+def test_a_value_shorter_than_eight_characters_has_no_form_in_any_spelling():
+    """MIN_SECRET applies to the credential, not to a spelling of it: "a/b&c+d" is 7 characters, its quote_plus 13."""
+    realm_sync.sends("a/b&c+d")
+    oplog.register_secret("a/b&c+d")
+    assert realm_sync._SENT == () and oplog._FORMS == ()
+
+
+def test_control_a_token_form_encoding_leaves_unchanged_adds_no_form():
+    """A control (passes on the head too): no over-redaction and no extra cost for the usual token."""
+    git = offline(GitHubProvider, lambda r: httpx.Response(200), token=PLAIN)
+    assert git._forms == oplog._FORMS == secret_forms(PLAIN)
+
+
+# ---------------------------------------------------------------- F2: realm sync's transport errors
+
+@pytest.mark.parametrize("stage", ["token", "admin"])
+def test_a_realm_transport_error_ends_the_job_redacted(stage):
+    secret, bearer = "RealmSecret-with-special-123", "AccessToken-with-special-456"
+    rm = Realm("https://kc.test", "cmapi", "cmapi-realm-admin", secret, True)
+
+    def handle(request):
+        if request.url.path.endswith("/token") and stage == "admin":
+            return httpx.Response(200, json={"access_token": bearer})
+        raise httpx.LocalProtocolError("Illegal header value " + repr((secret if stage == "token" else bearer).encode()))
+    rm.http = httpx.Client(transport=httpx.MockTransport(handle))
+    with pytest.raises(SystemExit) as caught:
+        rm.call("GET", "/users")
+    message = str(caught.value.code)
+    assert "LocalProtocolError" in message and MASK in message
+    assert ("GET /users" if stage == "admin" else "sign in as cmapi-realm-admin") in message
+    assert secret not in message and bearer not in message
+
+
+def test_a_refused_bearer_header_on_a_real_socket_never_reaches_the_printed_traceback():
+    """h11 refuses a header value with a newline and names it: "Illegal header value b'Bearer <token>\\n'". The token is
+    Keycloak's text. Real httpx, h11 and a local socket; the printed traceback is what the Job log would hold."""
+    bearer = "BearerSecret-0123456789"
+
+    class Keycloak(BaseHTTPRequestHandler):
+        def do_POST(self):
+            self.rfile.read(int(self.headers.get("content-length", 0)))
+            body = json.dumps({"access_token": bearer + "\n", "expires_in": 300}).encode()
+            self.send_response(200)
+            self.send_header("content-type", "application/json")
+            self.send_header("content-length", str(len(body)))
+            self.end_headers()
+            self.wfile.write(body)
+
+        def log_message(self, *a):
+            pass
+
+    server = HTTPServer(("127.0.0.1", 0), Keycloak)
+    threading.Thread(target=server.serve_forever, daemon=True).start()
+    try:
+        rm = Realm(f"http://127.0.0.1:{server.server_port}", "cmapi", "cmapi-realm-admin", "client-secret-0123456789", False)
+        with pytest.raises(SystemExit) as caught:
+            rm.call("GET", "/users")
+    finally:
+        server.shutdown()
+        server.server_close()
+    printed = "".join(traceback.format_exception(caught.value))
+    assert "LocalProtocolError" in printed and bearer not in printed
+
+
+# ---------------------------------------------------------------- F3: a successful answer's commit subjects
+
+@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
+def test_a_commit_subject_that_holds_the_token_is_redacted(provider):
+    commits = [{"sha": "a" * 40, "commit": {"message": "proxy echoed " + SPECIAL + "\n\nbody"}},
+               {"sha": "b" * 40, "commit": {"message": "Merge cmapi/CRC/r1"}}]
+    git = offline(provider, lambda r: httpx.Response(200, json=commits))
+    assert git.log() == ["aaaaaaaa proxy echoed " + MASK, "bbbbbbbb Merge cmapi/CRC/r1"]
+
+
+def test_the_git_layer_log_is_redacted_with_the_git_layer_token():
+    """The worker's GitHub provider reads the log through its Git layer, whose token oplog holds (not the provider's)."""
+    layer_token = "git-layer-token-0123456789"
+    oplog.register_secret(layer_token)
+
+    class Layer:
+        def log(self, n):
+            return ["cccccccc echoed " + layer_token, "dddddddd ordinary"]
+    git = offline(GitHubProvider, lambda r: httpx.Response(200), token=PLAIN)
+    git.workspace = Layer()
+    assert git.log() == ["cccccccc echoed " + MASK, "dddddddd ordinary"]

==================================================================== fixes-455.patch (verbatim, -p1 against pr455/)
--- a/cmapi/src/cmapi/core/clients/kube.py
+++ b/cmapi/src/cmapi/core/clients/kube.py
@@ -309,8 +309,12 @@
         self._threads: list[threading.Thread] = []
 
     @staticmethod
-    def _key(obj: Mapping[str, Any]) -> str:
-        m = obj["metadata"]
+    def _key(obj: Mapping[str, Any], kind: str = "object") -> str:
+        """`<namespace>/<name>` of a listed or watched object, or BadResponse: an object without metadata.name is no object
+        of the kind, and its KeyError or TypeError would end the kind's thread (#421)."""
+        m = obj.get("metadata")
+        if not isinstance(m, Mapping) or not isinstance(m.get("name"), str):
+            raise BadResponse(kind, 200, "an object without metadata.name")
         return f"{m.get('namespace', '')}/{m['name']}"
 
     def _value(self, kind: str, obj: dict[str, Any]) -> Any:
@@ -328,18 +332,34 @@
         ValueError that `_loop` retries, never a KeyError that would end the kind's thread."""
         if not self.chunk:
             out = self.client.list(kind)
-            return [(self._key(o), self._value(kind, o)) for o in out["items"]], self._resource_version(kind, out)
+            return [(self._key(o, kind), self._value(kind, o)) for o in out["items"]], self._resource_version(kind, out)
         values: list[tuple[str, Any]] = []
         token: str | None = None
         while True:
             out = self.client.list(kind, limit=self.chunk, continue_=token)
-            values.extend((self._key(o), self._value(kind, o)) for o in out["items"])
-            token = (out.get("metadata") or {}).get("continue") or None
+            values.extend((self._key(o, kind), self._value(kind, o)) for o in out["items"])
+            token = self._continue(kind, out)
             if token is None:
                 return values, self._resource_version(kind, out)
             del out                         # the page's raw objects go before the next page arrives
 
     @staticmethod
+    def _continue(kind: str, out: Mapping[str, Any]) -> str | None:
+        """The page's continue token, None on the last page, or BadResponse: a metadata or a token of another JSON type is
+        no list page, and reading it raised AttributeError, which ended the kind's thread (#421)."""
+        meta = out.get("metadata")
+        if meta is None:
+            return None                     # the last page; `_resource_version` then refuses it for want of one
+        if not isinstance(meta, Mapping):
+            raise BadResponse(kind, 200, f"metadata is a JSON {_JSON_TYPES.get(type(meta), 'value')}, not an object")
+        token = meta.get("continue")
+        if token is None or token == "":
+            return None
+        if not isinstance(token, str):
+            raise BadResponse(kind, 200, f"metadata.continue is a JSON {_JSON_TYPES.get(type(token), 'value')}, not a string")
+        return token
+
+    @staticmethod
     def _resource_version(kind: str, out: Mapping[str, Any]) -> str:
         meta = out.get("metadata")
         rv = meta.get("resourceVersion") if isinstance(meta, Mapping) else None
@@ -362,6 +382,8 @@
     def _event(self, kind: str, ev: Mapping[str, Any]) -> None:
         """One watch event into the cache: ADDED and MODIFIED through `project` and `admit`, DELETED through `dropped`; a
         BOOKMARK only moves the resourceVersion and the last good read. ERROR raises, so the loop lists again."""
+        if not isinstance(ev, Mapping) or not isinstance(ev.get("object", {}), Mapping):
+            raise BadResponse(kind, 200, "a watch event that is not an object with an object")
         t, obj = ev.get("type"), ev.get("object", {})
         if t == "ERROR":
             # The client redacts before the cut (#420); a test's fake client, which holds no token, has no `redact`.
@@ -369,14 +391,18 @@
             raise KubeError(410, kind, (getattr(self.client, "redact", None) or str)(text)[:200])
         with self._lock:
             st = self.state[kind]
-            st.resource_version = obj.get("metadata", {}).get("resourceVersion", st.resource_version)
+            meta = obj.get("metadata", {})
+            if not isinstance(meta, Mapping):
+                raise BadResponse(kind, 200, "a watch event's object without metadata")
+            st.resource_version = meta.get("resourceVersion", st.resource_version)
             st.last_good = self.clock()
             if t in ("ADDED", "MODIFIED"):
-                key = self._key(obj)
+                key = self._key(obj, kind)
                 st.items[key] = self._admitted(kind, key, self._value(kind, obj))
             elif t == "DELETED":
-                if st.items.pop(self._key(obj), None) is not None and self.dropped:
-                    self.dropped(kind, self._key(obj))
+                key = self._key(obj, kind)
+                if st.items.pop(key, None) is not None and self.dropped:
+                    self.dropped(kind, key)
 
     def _loop(self, kind: str) -> None:
         backoff = 1.0
@@ -391,12 +417,20 @@
                         self._event(kind, ev)
                         if self._stop.is_set():
                             break
-            except (ClusterUnreachable, KubeError, ValueError) as exc:
+            except Exception as exc:                    # noqa: BLE001 - the kind's thread never ends (#421)
+                if isinstance(exc, (ClusterUnreachable, KubeError, ValueError)):
+                    text = str(exc)[:200]
+                    log.warning("watch_cache", cluster_id=self.client.cluster_id, kind=kind, error=text, retry_in=backoff)
+                else:
+                    # The last net, as ClusterRegistry.refresh has one (#419): what the checks did not foresee, such as a
+                    # projection of a malformed object. The cache keeps its last good list and goes stale as after any
+                    # failed list; the log has the trace. The client redacts before the cut (#420).
+                    text = (getattr(self.client, "redact", None) or str)(f"{type(exc).__name__}: {exc}")[:200]
+                    log.exception("watch_cache_failed", cluster_id=self.client.cluster_id, kind=kind, error=text,
+                                  retry_in=backoff)
                 with self._lock:
-                    self.state[kind].error = str(exc)[:200]
+                    self.state[kind].error = text
                     self.state[kind].error_status = exc.status if isinstance(exc, KubeError) else None
-                log.warning("watch_cache", cluster_id=self.client.cluster_id, kind=kind, error=str(exc)[:200],
-                            retry_in=backoff)
                 self._stop.wait(backoff)
                 backoff = min(backoff * 2, 60.0)
 
--- a/docs/02-technical-design-v2.md
+++ b/docs/02-technical-design-v2.md
@@ -758,7 +758,7 @@
 - An apiUrl that carries userinfo is refused, because httpx would send it as Basic auth.
 - The findings of the parse step are fixed sentences and hold no token. The findings of the connect, identity and capability steps are the error text of the call: for a `KubeError`, the status, the path and the first 300 characters of the response body. `GET /api/v1/clusters` shows them to every holder of `clusters:read`. Built (#420): the token, and its JSON-escaped forms, are redacted from every error message before it is truncated. Each `KubeClient` replaces every form of its own token with `***` in the body of an HTTP error and in the text of a transport error, before `KubeError` cuts the body to 300 characters (`core/clients/redact.py`, `KubeClient._error`, `core/clients/kube.py`). The forms are the token as sent, its JSON escapes as Python and Go write them (Go also escapes <, > and &), once and twice, and the repr of its bytes that an "illegal header value" error shows. A text that ends in the first 8 characters or more of a form, as a body the server cut, loses them too. `ClusterRegistry._set` redacts the import Secret's token from each finding again, before it is stored, served and logged as `cluster_import`, and `HubImportSource` redacts the hub's own token from its list error. This holds for the reader client of each cluster and for the deliverer client of the delivery jobs. A token shorter than 8 characters is not redacted. The Git layer redacts its secrets from logs (`core/git/oplog.py`).
 - Built: outcomes are classified by who produced the error. A transport problem this process raised is `unreachable` or `cert-verify-failed`. A 401 or 403 on `GET /version`, and a failure of the identity check, are `auth_failed`. A 403 on the list of namespaces is `forbidden`, with the finding `missing grant: list namespaces`. Built (#419): an answer to `GET /version`, the identity check or the list of namespaces that is not JSON, is JSON but not an object, or lacks the field the call reads (`metadata.name` of users/\~, `status.userInfo.username` of a SelfSubjectReview) is `bad-response`, with a finding that names the path, the HTTP status and what was wrong, never the body (`BadResponse`, `core/clients/kube.py`). **Not built:** an HTTP error other than 401 and 403 is still `unreachable` on `GET /version`, `auth_failed` on the identity check and `forbidden` (`missing grant: <the error>`) on the list of namespaces, not `bad-response`.
-- Built (#421): a 200 response without an items field is never read as an empty list. `KubeClient.list` and the hub's list of import Secrets take `items` through `list_items` (`core/clients/kube.py`): no `items` field, an `items` that is not an array, or an item that is not an object is `bad-response`, with a finding that names the path, the status and what was wrong, never the body. Every Kubernetes list type has `items`, and the API server tests that an empty list carries it (kubernetes/kubernetes#124568, #126286). `items: null` is an empty list, because Go writes a nil slice as null and the API treats null and [] alike in a list field (kubernetes/kubernetes#43422). So the list of namespaces in the capability check is `bad-response`, a watch cache's relist keeps its last good list and records the error without a new good read (`WatchCache._loop`; it goes stale after the relist window, as after any failed list), the hub's list keeps the previous set of clusters (see "Discovery"), and the live count of Pods and PVCs before a delete is 503 `cluster-unreachable`, never 0 (`Pipeline.workload_counts`). A list with no `metadata.resourceVersion` is `bad-response` in the watch cache too, which retries it: before, its KeyError ended the kind's watch thread.
+- Built (#421): a 200 response without an items field is never read as an empty list. `KubeClient.list` and the hub's list of import Secrets take `items` through `list_items` (`core/clients/kube.py`): no `items` field, an `items` that is not an array, or an item that is not an object is `bad-response`, with a finding that names the path, the status and what was wrong, never the body. Every Kubernetes list type has `items`, and the API server tests that an empty list carries it (kubernetes/kubernetes#124568, #126286). `items: null` is an empty list, because Go writes a nil slice as null and the API treats null and [] alike in a list field (kubernetes/kubernetes#43422). So the list of namespaces in the capability check is `bad-response`, a watch cache's relist keeps its last good list and records the error without a new good read (`WatchCache._loop`; it goes stale after the relist window, as after any failed list), the hub's list keeps the previous set of clusters (see "Discovery"), and the live count of Pods and PVCs before a delete is 503 `cluster-unreachable`, never 0 (`Pipeline.workload_counts`). A list with no `metadata.resourceVersion` is `bad-response` in the watch cache too, which retries it: before, its KeyError ended the kind's watch thread. So is a page whose `metadata` is not an object or whose `continue` is not a string, a listed or watched object without a string `metadata.name`, and a watch event that is not an object (`WatchCache._continue`, `_key`, `_event`). Anything else a list or an event raises, such as a projection of a malformed Node, is caught by a last net that logs `watch_cache_failed` with the trace and retries after the backoff: the kind's thread never ends, and its cache keeps the last good list (`WatchCache._loop`).
 - Built for the node and policy-report caches only: they list in pages and follow continue tokens (`chunk` in `NodeCache` and `ReportCache`; `WatchCache._fetch`, `limit` and `continue_`). The cache of namespaces, ResourceQuotas and LimitRanges that the registry builds has no `chunk`, so it lists each kind in one call (`ClusterRegistry._check`).
 - **Not built:** a task for each cluster. One thread checks the clusters in turn, each call with a 10-second timeout (`KubeClient`, `timeout=10.0`). After the connection, each cluster has its own watch threads.
 
--- /dev/null
+++ b/cmapi/tests/service/test_watch_review_455.py
@@ -0,0 +1,128 @@
+"""Review of #455 (#421): a watch cache's kind thread survives every malformed answer, and keeps its last good list.
+Codex's F4 (a page's metadata of another JSON type) as OB3 corrected it, and what Codex missed: an object without
+metadata.name, a watch event that is not an object, a projection that fails on a malformed object, and the thread itself.
+Offline: real KubeClient over httpx.MockTransport. Each test fails on #455's head (7785e68) and passes with fixes-455.patch."""
+from __future__ import annotations
+
+import time
+
+import httpx
+import pytest
+
+from cmapi.core.clients.kube import KubeClient, WatchCache
+from cmapi.core.clients.nodes import NodeCache
+
+GOOD = {"items": [{"metadata": {"name": "a"}}], "metadata": {"resourceVersion": "1"}}
+
+
+def cache_over(answers, *, chunk=None, make=None):
+    """A WatchCache (or what `make(client)` returns) whose list calls get `answers` in order and whose watch gets the next
+    answer as its lines; serving the last answer sets the stop event, so `_loop` returns after it."""
+    client = KubeClient("C", "https://kube.test", "reader-token-0123456789", insecure=True)
+    queue = list(answers)
+    made = make(client) if make else None
+    cache = made.watch if made else WatchCache(client, ("Namespace",), chunk=chunk)
+
+    def handle(request):
+        body = queue.pop(0)
+        if not queue:
+            cache._stop.set()
+        if request.url.params.get("watch"):
+            return httpx.Response(200, content=body)
+        return httpx.Response(200, json=body)
+    client._client.close()
+    client._client = httpx.Client(transport=httpx.MockTransport(handle), base_url="https://kube.test")
+    return cache
+
+
+def kept_last_good(cache, kind="Namespace"):
+    before = cache.state[kind].last_good
+    cache._loop(kind)                       # on the head, the exception leaves _loop: the kind's thread would end here
+    st = cache.state[kind]
+    return st, before
+
+
+# ---------------------------------------------------------------- Codex's F4, corrected: the page's metadata and token
+
+@pytest.mark.parametrize("metadata", ["broken", ["broken"], 42])
+def test_a_page_whose_metadata_is_not_an_object_keeps_the_watch(metadata):
+    cache = cache_over([GOOD, {"items": [], "metadata": metadata}], chunk=1)
+    cache._list("Namespace")
+    st, before = kept_last_good(cache)
+    assert list(st.items) == ["/a"] and st.last_good == before and st.resource_version == "1"
+    assert "bad response" in st.error and "metadata" in st.error
+
+
+@pytest.mark.parametrize("token", [7, ["x"], {"x": 1}, True])
+def test_a_continue_token_that_is_not_a_string_keeps_the_watch(token):
+    """Codex's fix reads `continue or None`: false, 0 and [] end the list as if it were complete."""
+    cache = cache_over([GOOD, {"items": [], "metadata": {"resourceVersion": "2", "continue": token}}], chunk=1)
+    cache._list("Namespace")
+    st, before = kept_last_good(cache)
+    assert list(st.items) == ["/a"] and st.last_good == before and "metadata.continue" in st.error
+
+
+@pytest.mark.parametrize("token", [False, 0, []])
+def test_a_falsy_continue_of_another_type_is_refused_not_read_as_the_last_page(token):
+    cache = cache_over([GOOD, {"items": [{"metadata": {"name": "b"}}], "metadata": {"resourceVersion": "2", "continue": token}}],
+                       chunk=1)
+    cache._list("Namespace")
+    st, before = kept_last_good(cache)
+    assert list(st.items) == ["/a"] and st.resource_version == "1" and "metadata.continue" in st.error
+
+
+# ---------------------------------------------------------------- missed: an object without metadata.name
+
+@pytest.mark.parametrize("chunk", [None, 1])
+@pytest.mark.parametrize("item", [{}, {"metadata": "x"}, {"metadata": {"namespace": "n"}}, {"metadata": {"name": 5}}])
+def test_a_listed_object_without_a_name_keeps_the_watch(item, chunk):
+    cache = cache_over([GOOD, {"items": [item], "metadata": {"resourceVersion": "2"}}], chunk=chunk)
+    cache._list("Namespace")
+    st, before = kept_last_good(cache)
+    assert list(st.items) == ["/a"] and st.last_good == before and "an object without metadata.name" in st.error
+
+
+# ---------------------------------------------------------------- missed: a watch event that is not an object
+
+@pytest.mark.parametrize("line", [b"[]\n", b'"x"\n', b'{"type": "ADDED", "object": "x"}\n',
+                                  b'{"type": "ADDED", "object": {"spec": {}}}\n',
+                                  b'{"type": "MODIFIED", "object": {"metadata": "x"}}\n'])
+def test_a_malformed_watch_event_keeps_the_watch(line):
+    cache = cache_over([GOOD, line, GOOD])       # list, watch (the bad event), and the relist the loop then makes
+    cache.RELIST_SECONDS = 3600
+    cache._loop("Namespace")
+    st = cache.state["Namespace"]
+    assert list(st.items) == ["/a"]
+    assert st.error is None or "bad response" in st.error
+
+
+# ---------------------------------------------------------------- missed: the projection, and the thread itself
+
+def node(name, status):
+    return {"metadata": {"name": name}, "status": status}
+
+
+def test_a_node_the_projection_cannot_read_keeps_the_node_watch():
+    """reduce_node calls status.get: a Node whose status is a string raised AttributeError, outside _loop's filter."""
+    good = {"items": [node("n1", {"allocatable": {"cpu": "4", "memory": "8Gi"},
+                                  "conditions": [{"type": "Ready", "status": "True"}]})], "metadata": {"resourceVersion": "1"}}
+    cache = cache_over([good, {"items": [node("n2", "broken")], "metadata": {"resourceVersion": "2"}}],
+                       make=lambda client: NodeCache(client, chunk=1))
+    cache._list("Node")
+    st, before = kept_last_good(cache, "Node")
+    assert list(st.items) == ["/n1"] and st.last_good == before and "AttributeError" in st.error
+
+
+def test_the_kind_thread_survives_a_malformed_relist_and_recovers():
+    """The thread itself: a good list, a page that killed the thread on the head, then a good list with a new object."""
+    recovered = {"items": [{"metadata": {"name": "a"}}, {"metadata": {"name": "b"}}], "metadata": {"resourceVersion": "3"}}
+    cache = cache_over([GOOD, {"items": [], "metadata": "broken"}, recovered], chunk=1)
+    cache.RELIST_SECONDS = 0                    # relist at once: no watch between the lists
+    cache.start()
+    thread = cache._threads[0]
+    deadline = time.monotonic() + 10
+    while time.monotonic() < deadline and cache.state["Namespace"].resource_version != "3" and thread.is_alive():
+        time.sleep(0.05)
+    thread.join(5)
+    st = cache.state["Namespace"]
+    assert st.resource_version == "3" and sorted(st.items) == ["/a", "/b"] and st.error is None

==================================================================== review-288b/ob3/credentials.patch (verbatim, -p1 against pr453/ + fixes-453.patch)
--- a/cmapi/src/cmapi/core/git/base.py
+++ b/cmapi/src/cmapi/core/git/base.py
@@ -164,8 +164,9 @@
             except httpx.HTTPError as exc:
                 PLATFORM_REQUESTS.labels(self.name, operation, "error").inc()
                 op.outcome = "retry"
-                # An HTTP library's error can show the header it refused ("illegal header value b'...'").
-                raise GitUnavailable(self.redact(f"{operation}: {type(exc).__name__}: {exc}")) from exc
+                # An HTTP library's error can show the header it refused ("illegal header value b'...'"). Not chained: the
+                # worker logs traceback.format_exc(), which prints the cause's own, unredacted text (#444).
+                raise GitUnavailable(self.redact(f"{operation}: {type(exc).__name__}: {exc}")) from None
             PLATFORM_REQUESTS.labels(self.name, operation, f"{r.status_code // 100}xx").inc()
             op.set(http_status=r.status_code, host_request_id=r.headers.get("x-github-request-id") or r.headers.get("x-request-id"))
             if r.status_code >= 500 or r.status_code == 429:
--- a/cmapi/src/cmapi/core/git/oplog.py
+++ b/cmapi/src/cmapi/core/git/oplog.py
@@ -15,7 +15,7 @@
 import time
 from contextlib import contextmanager
 from contextvars import ContextVar
-from typing import Any, Iterator
+from typing import Any, Iterator, Mapping
 
 from cmapi.core.clients.redact import redact as redact_forms, sent_forms
 from cmapi.core.observability import GIT_DURATION, GIT_OPS, log
@@ -38,8 +38,17 @@
 
 
 def redact(value: Any) -> Any:
-    """A string without any registered secret in any form; call it on the whole text, before any cut. Anything else as it is."""
-    return redact_forms(value, _FORMS) if isinstance(value, str) else value
+    """A string without any registered secret in any form; call it on the whole text, before any cut. A mapping, list or tuple
+    with every string in it redacted, at any depth (#445): an event field can hold a structure. Anything else as it is."""
+    if isinstance(value, str):
+        return redact_forms(value, _FORMS)
+    if isinstance(value, Mapping):
+        return {redact(k): redact(v) for k, v in value.items()}
+    if isinstance(value, list):
+        return [redact(v) for v in value]
+    if isinstance(value, tuple):
+        return tuple(redact(v) for v in value)
+    return value
 
 
 @contextmanager
@@ -82,7 +91,7 @@
                  "duration_ms": round(duration * 1000, 1)}
         if exc is not None:
             event["error"] = f"{type(exc).__name__}: {exc}"
-        event = {k: redact(v) if not isinstance(v, list) else [redact(x) for x in v] for k, v in event.items()}
+        event = redact(event)
         if "stderr" in event and isinstance(event["stderr"], str):
             event["stderr"] = event["stderr"][-2000:]
         (log.info if outcome in ("ok", "skipped") else log.warning)("git_op", **event)
--- a/cmapi/src/cmapi/core/git/workspace.py
+++ b/cmapi/src/cmapi/core/git/workspace.py
@@ -10,6 +10,9 @@
     <workdir>/<cluster>/<requestId>      one git worktree per request, on branch cmapi/<cluster>/<requestId>
     <workdir>/.lock                      flock: one process owns the workdir
 
+The workdir is private to the process's UID: 0700, its .home 0700 and its .lock 0600, whatever the umask (#447). An emptyDir is
+made 0777 and owned by root, so an arbitrary UID cannot chmod it: then the workdir is <workdir>/.private-<uid> inside it.
+
 A request's branch: fetch origin main; worktree add -b <branch> <dir> <origin/main's sha> (never a local main, never git pull);
 the folder's files; one commit whose dates are the approval's, so the same plan on the same main gives the same sha on any
 replica (reproducible); a push of that branch alone with a lease. Nothing here pushes to the default branch: the PR merges on
@@ -22,7 +25,9 @@
 from __future__ import annotations
 
 import fcntl
+import os
 import re
+import stat
 import shutil
 import subprocess
 import tempfile
@@ -75,6 +80,27 @@
     return f"{BRANCH_PREFIX}{cluster_id}/{request_id}"
 
 
+def _private_root(workdir: Path) -> Path:
+    """The configured workdir made 0700, or, when this UID cannot chmod it (an emptyDir: 0777 and root's), its child
+    .private-<uid>: made by this UID, 0700, and refused when it is a symlink or another UID's (#447)."""
+    workdir.mkdir(parents=True, exist_ok=True)
+    try:
+        workdir.chmod(0o700)
+        return workdir
+    except PermissionError:
+        pass
+    private = workdir / f".private-{os.getuid()}"
+    try:
+        private.mkdir(mode=0o700)
+    except FileExistsError:
+        pass
+    st = os.lstat(private)
+    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
+        raise GitConfigError(f"{private} is not a directory of this process's UID: it cannot hold the Git workdir")
+    private.chmod(0o700)
+    return private
+
+
 def _under(path: Path) -> int:
     return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())
 
@@ -104,9 +130,9 @@
         if self._ca and not Path(self._ca).is_file():
             raise GitConfigError(f"the Git CA bundle {self._ca} is not a file")
         owned = workdir is None
-        self.root = Path(tempfile.mkdtemp(prefix="cmapi-git-")) if owned else Path(workdir)
-        self.root.mkdir(parents=True, exist_ok=True)
-        self._lockfile = open(self.root / ".lock", "w")
+        self.root = Path(tempfile.mkdtemp(prefix="cmapi-git-")) if owned else _private_root(Path(workdir))
+        self._lockfile = os.fdopen(os.open(self.root / ".lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w")
+        os.fchmod(self._lockfile.fileno(), 0o600)          # a lock file an earlier run made under another umask
         try:
             fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
         except OSError as exc:
@@ -114,7 +140,8 @@
             raise GitConfigError(f"{self.root} is the Git workdir of another process: each process has its own") from exc
         self.mirror = self.root / REPO
         self._home = self.root / ".home"
-        self._home.mkdir(exist_ok=True)
+        self._home.mkdir(mode=0o700, exist_ok=True)
+        self._home.chmod(0o700)
         self._lock = threading.RLock()
         self._env = git_environment(self.remote, self._creds, self._home, self._ca, self.author)
         self._tracking = f"refs/remotes/origin/{default_branch}"
--- /dev/null
+++ b/cmapi/tests/test_git_credentials_review.py
@@ -0,0 +1,179 @@
+"""#444, #445, #447 (Codex's F1, F2, F4 of the Git delivery review, as OB3 corrected them), on top of #453 (#424).
+
+#453 already routes every host answer through HostGitProvider.host_text (core/clients/redact.py: every form of the token, the
+Basic-auth password and its base64, redacted before the cut) and gives oplog.redact the full form set. The controls below pass
+on #453 alone and show which parts of F1 and F2 it makes moot. What it leaves, and this patch adds: no raw HTTP cause chained
+to a Git error (the worker logs the traceback), redaction at any depth of an event, and a Git workdir private to its UID.
+Offline: file:// Git and httpx.MockTransport only."""
+from __future__ import annotations
+
+import json
+import os
+import stat
+import traceback
+from datetime import datetime, timezone
+from pathlib import Path
+
+import httpx
+import pytest
+
+from cmapi.core.git.base import BranchRequest, GitUnavailable
+from cmapi.core.git.gitea import GiteaProvider
+from cmapi.core.git.github import GitHubProvider
+from cmapi.core.git.oplog import Op, redact, register_secret
+from cmapi.core.git.workspace import GitWorkspace
+from cmapi.core.ports import PrRef
+from gitserver import bare_repo
+
+FOLDER = "clusters/CRC/namespaces/demo/"
+TOKEN = "ob3-echo-token-0123456789abcdef"
+
+
+@pytest.fixture
+def secrets(monkeypatch):
+    """A registry of its own (#453 keeps the forms in oplog._FORMS), so no test sees another's secrets."""
+    import cmapi.core.git.oplog as oplog
+
+    monkeypatch.setattr(oplog, "_FORMS", ())
+    return oplog
+
+
+def github(handler) -> GitHubProvider:
+    provider = GitHubProvider("https://offline.invalid", "o/r", TOKEN)
+    provider._client.close()
+    provider._client = httpx.Client(base_url="https://offline.invalid", transport=httpx.MockTransport(handler))
+    return provider
+
+
+def pr_state(provider) -> GitUnavailable:
+    with pytest.raises(GitUnavailable) as caught:
+        provider.pr_status(PrRef(1, "", "cmapi/CRC/r1", "a" * 40))
+    return caught.value
+
+
+# ---------------------------------------------------------------- #444 (F1): what #453 makes moot, then what it leaves
+
+@pytest.mark.parametrize("code", [403, 502])
+def test_moot_on_453_a_host_error_that_echoes_the_token(code):
+    error = pr_state(github(lambda request: httpx.Response(code, json={"message": "echo " + TOKEN})))
+    assert TOKEN not in str(error) and TOKEN not in getattr(error, "host_message", "")
+
+
+def test_moot_on_453_a_token_cut_by_the_message_limit():
+    error = pr_state(github(lambda request: httpx.Response(502, text="e" * 190 + TOKEN)))
+    assert TOKEN[:10] not in str(error)
+
+
+def test_moot_on_453_a_basic_auth_password_echoed_json_escaped():
+    password = 'pa"ss/w0rd\\long-secret'
+    provider = GiteaProvider("https://offline.invalid/api/v1", "o/r", "", basic_auth=("bot", password))
+    provider._client.close()
+    provider._client = httpx.Client(base_url="https://offline.invalid/api/v1", transport=httpx.MockTransport(
+        lambda request: httpx.Response(502, text=json.dumps({"message": "denied for " + password}))))
+    with pytest.raises(GitUnavailable) as caught:
+        provider.branch_head("main")
+    assert json.dumps(password)[1:-1] not in str(caught.value)
+
+
+def test_a_transport_error_is_not_chained_to_its_raw_text():
+    """#453 redacts the message but keeps `from exc`: traceback.format_exc(), which the worker logs on job_failed (worker.py),
+    then prints the h11 error with the header value in it."""
+    def fail(request):
+        raise httpx.LocalProtocolError(f"Illegal header value b'Bearer {TOKEN}\\n'")
+    error = pr_state(github(fail))
+    trace = "".join(traceback.format_exception(error))
+    assert TOKEN not in str(error)
+    assert TOKEN not in trace, "the cause's text is in the logged traceback"
+
+
+# ---------------------------------------------------------------- #445 (F2): what #453 makes moot, then what it leaves
+
+def test_moot_on_453_overlapping_secrets_are_replaced_longest_first(secrets):
+    for value in ("abcdefgh", "abcdefgh-SUFFIX"):
+        register_secret(value)
+    assert redact("x abcdefgh-SUFFIX y") == "x *** y"
+
+
+def test_kept_from_main_a_value_shorter_than_eight_characters_is_not_a_credential(secrets):
+    """core/clients/redact.py's MIN_SECRET (#423). Codex registered every non-empty value: with the fixtures' one-letter
+    token "t", "Host key verification failed" became "Hos*** key verifica***ion failed" and an SSH test failed."""
+    register_secret("t")
+    assert redact("Host key verification failed") == "Host key verification failed"
+
+
+def test_a_structure_is_redacted_at_any_depth(secrets):
+    register_secret(TOKEN)
+    assert redact({"nested": [TOKEN, {"x": TOKEN}], "t": (TOKEN,)}) == {"nested": ["***", {"x": "***"}], "t": ("***",)}
+
+
+def test_an_op_event_redacts_a_nested_field(secrets, capsys):
+    register_secret(TOKEN)
+    with Op("pr_state") as op:
+        op.set(detail={"echo": [TOKEN]}, rows=[{"body": TOKEN}])
+    assert TOKEN not in capsys.readouterr().out
+
+
+# ---------------------------------------------------------------- #447 (F4): the workdir is private, in exact modes
+
+def req() -> BranchRequest:
+    return BranchRequest("CRC", "req-1", FOLDER, "hash", "create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
+                         {FOLDER + "namespace.yaml": "kind: Namespace\n"}, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))
+
+
+def modes(ws: GitWorkspace) -> tuple[int, int, int]:
+    return (stat.S_IMODE(ws.root.stat().st_mode), stat.S_IMODE(ws._home.stat().st_mode),
+            stat.S_IMODE((ws.root / ".lock").stat().st_mode))
+
+
+def test_the_workdir_home_and_lock_are_private_under_a_permissive_umask(tmp_path):
+    bare = bare_repo(tmp_path)
+    workdir = tmp_path / "worker"
+    workdir.mkdir()
+    workdir.chmod(0o777)
+    old = os.umask(0o022)
+    try:
+        ws = GitWorkspace(bare.as_uri(), workdir=workdir)
+        try:
+            ws.push_branch(req())
+            assert modes(ws) == (0o700, 0o700, 0o600)
+        finally:
+            ws.dispose()
+    finally:
+        os.umask(old)
+
+
+def refuse_chmod_of(monkeypatch, workdir: Path) -> None:
+    """An emptyDir: 0777 and root's, so this UID's chmod of it is refused. Simulated for that one path."""
+    real = Path.chmod
+
+    def chmod(self, mode, *a, **k):
+        if self == workdir:
+            raise PermissionError(1, "Operation not permitted", str(self))
+        return real(self, mode, *a, **k)
+    monkeypatch.setattr(Path, "chmod", chmod)
+
+
+def test_a_workdir_this_uid_cannot_chmod_holds_a_private_child(tmp_path, monkeypatch):
+    bare = bare_repo(tmp_path)
+    workdir = tmp_path / "emptydir"
+    workdir.mkdir()
+    refuse_chmod_of(monkeypatch, workdir)
+    ws = GitWorkspace(bare.as_uri(), workdir=workdir)
+    try:
+        assert ws.root == workdir / f".private-{os.getuid()}"
+        assert modes(ws) == (0o700, 0o700, 0o600)
+    finally:
+        ws.dispose()
+
+
+def test_a_private_child_that_is_a_symlink_is_refused(tmp_path, monkeypatch):
+    from cmapi.core.git.transport import GitConfigError
+
+    bare = bare_repo(tmp_path)
+    workdir = tmp_path / "emptydir"
+    workdir.mkdir()
+    (tmp_path / "elsewhere").mkdir()
+    (workdir / f".private-{os.getuid()}").symlink_to(tmp_path / "elsewhere")
+    refuse_chmod_of(monkeypatch, workdir)
+    with pytest.raises(GitConfigError, match="not a directory of this process's UID"):
+        GitWorkspace(bare.as_uri(), workdir=workdir)
