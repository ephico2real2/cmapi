OB3 (Opus 5.5), reviewer 2 on Codex's review of the Git delivery layer (main b8ee59e; #444-#452). 2026-11-19.
Depth: DEEP = F1/F2 (redaction forms, cut, chained cause; measured against #453's head a9f219e), F5/F6 (state machine, driven
against PostgreSQL + real Git + the GitHub stub), F7 (design question, the stand-in's cleanup path). MEDIUM = F3, F4, F9, F8
(real Git / MockTransport, one harness each). SHALLOW: none treated as shallow by source reading alone.

Every test file and patch is under /Users/olasumbo/gitRepos/workbench/cmapi/review-288b/ob3/. Logs: ob3/logs/. Drivers:
ob3/run.sh, ob3/run2.sh, ob3/chain.sh, ob3/chain2.sh (suite.sh underneath, CMAPI_TEST_REQUIRE_SSHD=1, PYTHONDONTWRITEBYTECODE=1,
--basetemp under ob3/tmp). Import proof: cmapi from ob3/<tree>/cmapi/src (python -c "import cmapi; print(cmapi.__file__)").

==================================================================== VERDICTS ON CODEX'S F1-F9

F1 #444 (High) host errors carry the credential. HOLDS on main (ob3 test file: 11 of 12 fail on main,
  logs/offline-test_git_credentials_review-on-base.log). Also a sink Codex did not name: the API returns str(exc)[:300] as the
  git-unavailable problem (core/pipeline.py:158, routers/admin.py:207). Codex's fix is INCOMPLETE: it matches whole tokens
  after the cut (base.py:142 r.text[:200]), so a token straddling the cut leaves its first characters
  ("eee...ob3-echo-t" in the message), and a JSON-escaped Basic-auth password passes (logs/offline-...-on-codex.log).
  PER THE COORDINATOR: #453 (a9f219e) already fixes those by host_text (redact before cut, all forms, password + base64):
  6 controls pass on #453 alone (logs/offline-credentials453-on-pr453.log). What #453 still leaves: base.py `from exc`
  chains the raw httpx error, and worker.py:135 logs traceback.format_exc(), which prints "Illegal header value
  b'Bearer <token>\n'" unredacted. Fix: `from None` (credentials.patch). Test fails on #453, passes with the patch.
F2 #445 (Medium). Overlap/forms: MOOT on #453 (control passes). Short secrets: REJECTED. Codex registers every non-empty
  value, contradicting core/clients/redact.py MIN_SECRET=8 (#423). Measured damage: with the fixtures' token "t", Codex's
  tree prints "Hos*** key verifica***ion failed", and tests/service/test_git_layer.py::
  test_ssh_to_a_host_whose_key_is_not_pinned_is_refused FAILS on Codex's tree only (logs/codex-patched-service.log); Codex
  also had to rewrite an existing test's expectation and classify Git stderr before redacting. Nested redaction: KEPT,
  still missing on #453 (Op.__exit__ redacts one list level; a dict inside is logged raw). Test fails on #453, passes.
F3 #446 (High) symlink escape. HOLDS on main, and wider than Codex tested: a symlinked PARENT folder (clusters/CRC -> outside)
  makes main create namespaces/demo/namespace.yaml outside the worktree (logs/offline-test_git_workspace_review-on-base.log).
  Codex's fix is WRONG IN A WAY THAT BREAKS EVERY DELIVERY: `check_path(req.folder)` on the unstripped folder, but
  core/render/manifests.py:62 returns "clusters/<c>/namespaces/<ns>/" (trailing slash) and check_path refuses the empty
  part -> ValueError at push_branch for every real request. Measured: 26 test_git_layer.py failures on Codex's tree with
  "ValueError: 'clusters/CRC/namespaces/payments-dev/' is not a repository path cmapi writes". Corrected: strip, then
  check_path; refuse a symlink at any component, and a target that resolves outside the worktree (workspace.patch).
F4 #447 (Medium; Low in practice: one container per worker pod). HOLDS on main (0755/0644 under umask 022). Codex's fix kept,
  hardened: lock created 0600 with O_NOFOLLOW (no 0644 window), and the .private-<uid> fallback refused unless it is a real
  directory owned by this UID (lstat), not only "not a symlink". Exact modes asserted: root 0700, .home 0700, .lock 0600, both
  for an owned workdir and for the emptyDir fallback (chmod refused, simulated). Not measured under a real second UID.
F5 #448 (High) hand merge between checks and apply. HOLDS on main, DB-measured: branch deleted -> failed ("the PR head moved
  from d9e76e44 to nothing"); branch kept -> superseded (base_changed) (logs/newdb2-base.log). Codex's fix right in substance
  (ruling 16; SYNC_FAILED->MERGED keeps the lock), CHANGED in shape: Codex reads the PR before every apply attempt, i.e. one
  extra host GET on every pollInterval retry while the apply waits on the cluster (control test fails only on Codex's tree);
  mine reads it only when a check refuses (head moved, merge check), which covers both hand-merge shapes. DB: 3/3 pass fixed.
F6 #449 (High) post-merge folder gate. HOLDS for deletes (main reaches awaiting_prune with the folder still on main: DB test
  fails on main, passes fixed). For creates/changes main's watch_sync guard (watch_sync.py:89-91, 121-123) already refuses a
  main that is not the plan, so the gate there adds strictness, not safety. Codex's fix KEPT (design 2.4 says gate on every
  path) with one correction: no merge sha gives an explicit reason instead of "the folder at the merge  is not ...".
F7 #450 (High) Gitea. HOLDS on main (an open PR adopts any head; no PR deletes any head). Codex's fix REJECTED in part. Design
  answer: the target is the Git layer for every host (design §2, ruling 8), but the stand-in Gitea is plain http in the cluster
  (deploy/helm/cmapi/values.yaml:120-121) and the Git layer refuses http (core/giturl.py:33-34): moving it is a chart change
  (TLS or SSH on cmapi-git, workdir and credential mounts), a separate issue. Within REST, refusing a FOREIGN head is right
  (ruling 3); refusing EVERY delete is not: git_cleanup after every merge then raises, five times, and worker.py:166-167 moves a
  request still in merged (argocd, waiting for the sync) to sync_failed [source-derived, not driven]. Codex's patch also fails
  the existing tests/service/test_second_pass.py::test_gitea_deletes_a_stale_branch_before_reopening (Codex tree log).
  Corrected: the REST adoption test (Cmapi-Request-Id and Cmapi-Plan-Hash trailers from GET /git/commits/{sha}, one parent,
  the folder = the plan) -> adopted; this request's stale attempt -> read-then-delete and re-create ("replaced"); anyone
  else's -> BranchRefused, nothing written; delete_branch kept as main has it. The /git/commits endpoint shape is the one
  branch_time already reads (gitea.py:132); not checked against Gitea's published swagger (no network).
F8 #451 (Low) duplicate comment. HOLDS on main (MockTransport, 2 stored comments). Codex's fix KEPT; the stub's GET added.
  Read-before-POST, not an idempotency key; the comments-read permission of a fine-grained token not checked (no network).
F9 #452 (Medium -> Low: render folders always start "clusters/"). HOLDS on main: git 2.55.0 "error: unknown switch `f'",
  exit 129; `--` measured to give "/-folder/" in the cone file. Codex's fix KEPT (git 2.52 of the image not measured).

==================================================================== WHAT CODEX MISSED (G1-G8), each with code and a test above

N1 High: Codex's F3 patch fails every real push_branch (trailing slash) - the 26 test_git_layer failures; workspace.patch
  test test_the_renderers_folder_with_its_trailing_slash_is_still_delivered fails on Codex's tree, passes on main and fixed.
N2 High: Codex's F7 patch breaks the stand-in's cleanup after every merge and an existing test (above).
N3 Medium: F1 incomplete (cut prefix, JSON forms, the API problem sink, the chained cause in the logged traceback). The first
  two and the sink are moot on #453; the chained cause is in credentials.patch.
N4 Medium: F2's short-secret change garbles logs and fails an SSH test (above).
N5 Low: F5's upfront read costs one host call per apply poll (control test_an_apply_that_waits_on_the_cluster_reads_no_pr).
N6 Medium (F3 coverage): a symlinked parent folder escapes on main too; covered by workspace.patch's second test.

==================================================================== TEST COUNTS
Selection (18 service files: test_git_layer, test_git_trust, test_github_statuses, test_flow, test_pr40_convergence,
test_review_288_f1..f7, test_review_d_delivery, test_review_e_recovery, test_deliverer_grants..., test_second_pass,
test_third_pass_fixes, test_third_pass_converged), PostgreSQL 127.0.0.1:55432, real sshd (CMAPI_TEST_REQUIRE_SSHD=1: SSH and
HTTPS transport tests ran, none skipped):
  main b8ee59e              1 failed, 283 passed   (logs/main-baseline-service.log)
  Codex's patched tree     31 failed, 253 passed   (logs/codex-patched-service.log: 26 in test_git_layer from the F3
                                                    trailing-slash ValueError, the SSH test from F2, the Gitea test from F7)
  workspace.patch alone     1 failed, 283 passed   (logs/ob3-ws-service.log)
  delivery-states alone     1 failed, 285 passed + new DB tests 3/3 (logs/ob3-ds-service.log, logs/newdb2-ds.log; the second
                                                    failure in that log was my first draft of the delete test, corrected)
  gitea.patch alone         1 failed, 283 passed   (logs/ob3-gitea-service.log)
  credentials (main-based, superseded) alone 1 failed, 283 passed (logs/ob3-cred-service.log)
  #453 alone (a9f219e), 5 files incl. its own test: 273 passed (logs/pr453-alone-service.log)
  #453 + all four OB3 patches: 1 failed, 430 passed, incl. #453's test_git_host_redaction_424.py and the new DB tests
                                                    (logs/ob3-on453-service.log)
  The one failure everywhere, main included: test_third_pass_converged::test_every_shell_script_under_examples_and_deploy_is_
  executable runs `git ls-files`, and the review trees are archives with no .git: environmental, not a finding.
New DB tests on main: 3 failed (logs/newdb2-base.log); on delivery-states and on the combined tree: 3 passed.
Offline: Codex's test file on main 14 failed / 27 passed (with the lifecycle file), as Codex reported; on OB3's combined tree
  3 failed / 14 passed, the three by design (short secrets; Gitea refusing every delete) (logs/codex-tests-on-ob3-on453.log).
  OB3's offline files: credentials on #453 6 fail -> 12 pass; workspace main 5 fail -> 6 pass; delivery-states main 6 fail ->
  8 pass; gitea main 5 fail -> 7 pass; on Codex's tree 6/4/1/5 of them fail (logs/offline-*).

==================================================================== THE PATCHES (each -p1)

credentials.patch      #444 #445 #447   applies on #453's head a9f219e, NOT on main: #453 merges first. Moot after #453 and
                                        dropped: Codex's GitUnavailable/host_message redaction, regex redactor, short secrets,
                                        raw-stderr classification. Kept: `from None`, nested redaction, F4.
                                        (credentials-on-main.superseded.patch: the same intent written on main, kept for trace.)
workspace.patch        #446 #452        main; alone or in any order with the others (patch reports an offset only).
delivery-states.patch  #448 #449 #451   main; also applies cleanly on #453.
gitea.patch            #450             main. It does NOT apply on #453 (one hunk: #453 changed the deleted line to
                                        host_text). gitea-on-453.patch is the same fix rebased on #453, using host_text in the
                                        new commit read. Ordering: if #453 merges first, use gitea-on-453.patch.
All four (credentials on #453) composed in three orders give one tree (diff -r identical).

==================================================================== NOT ASKED / NOT CHECKED
- Moving the Gitea stand-in onto the Git layer (ruling 8 in full): needs TLS or SSH on cmapi-git; worth its own issue.
- Live hosts: GitHub's comments-list permission for a fine-grained token, Gitea's /git/commits shape; git 2.52 (the image) for
  `sparse-checkout set --cone --`; the emptyDir fallback under a real arbitrary UID; the worker.py:166 sync_failed consequence of
  Codex's F7 (source-read, not driven); token rotation (the helper reads the file per call, register_secret only at start).
- Not run: the full 99-file service suite on any tree; the image test; CRC.

==================================================================== HOUSEKEEPING
No tracked file changed; no git write. PR #453 was read with `git archive a9f219e` from /Users/olasumbo/gitRepos/cmapi-design
(read-only). All work in review-288b/ob3 copies. One stray copy to /tmp was removed at once. Deleted at the end: every tree copy
under ob3 (pristine, base, codex, cred, ws, ds, gitea, all, pr453, cred453, gitea453, on453), ob3/tmp, and the scratchpad repo
for the sparse-checkout measurement. Kept: the patches, run.sh/run2.sh/chain.sh/chain2.sh, logs/, out.txt.
cmapi-design git status --short, before and after: empty (clean).

==================================================================== credentials.patch (verbatim)
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pr453/cmapi/src/cmapi/core/git/base.py cred453/cmapi/src/cmapi/core/git/base.py
--- pr453/cmapi/src/cmapi/core/git/base.py	2026-11-18 23:26:06
+++ cred453/cmapi/src/cmapi/core/git/base.py	2026-11-19 00:05:33
@@ -159,8 +159,9 @@
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
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pr453/cmapi/src/cmapi/core/git/oplog.py cred453/cmapi/src/cmapi/core/git/oplog.py
--- pr453/cmapi/src/cmapi/core/git/oplog.py	2026-11-18 23:26:06
+++ cred453/cmapi/src/cmapi/core/git/oplog.py	2026-11-19 00:05:33
@@ -15,7 +15,7 @@
 import time
 from contextlib import contextmanager
 from contextvars import ContextVar
-from typing import Any, Iterator
+from typing import Any, Iterator, Mapping
 
 from cmapi.core.clients.redact import redact as redact_forms, secret_forms
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
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pr453/cmapi/src/cmapi/core/git/workspace.py cred453/cmapi/src/cmapi/core/git/workspace.py
--- pr453/cmapi/src/cmapi/core/git/workspace.py	2026-11-18 23:26:06
+++ cred453/cmapi/src/cmapi/core/git/workspace.py	2026-11-19 00:05:37
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
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pr453/cmapi/tests/test_git_credentials_review.py cred453/cmapi/tests/test_git_credentials_review.py
--- pr453/cmapi/tests/test_git_credentials_review.py	1969-12-31 18:00:00
+++ cred453/cmapi/tests/test_git_credentials_review.py	2026-11-19 00:06:01
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

==================================================================== workspace.patch (verbatim)
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/src/cmapi/core/git/workspace.py ws/cmapi/src/cmapi/core/git/workspace.py
--- pristine/cmapi/src/cmapi/core/git/workspace.py	2026-11-18 20:15:02
+++ ws/cmapi/src/cmapi/core/git/workspace.py	2026-11-18 23:18:26
@@ -348,6 +348,7 @@
 
     def _check_files(self, req: BranchRequest) -> str:
         folder = req.folder.strip("/")
+        check_path(folder)
         for path in req.files:
             check_path(path)
             if not path.startswith(folder + "/"):
@@ -387,7 +388,8 @@
                 path.parent.mkdir(parents=True, exist_ok=True)
                 self._m("worktree", "add", "--quiet", "--no-checkout", "-b", branch, str(path), base)
                 # Only the request's folder is checked out: a repository of thousands of namespaces costs one folder.
-                self._run("sparse-checkout", "set", "--cone", folder, cwd=path)
+                # "--": a folder that starts with "-" is a path, never an option (#452).
+                self._run("sparse-checkout", "set", "--cone", "--", folder, cwd=path)
                 self._run("checkout", "--quiet", branch, cwd=path)
             except GitFailed as exc:
                 self._failed(op, exc)
@@ -395,7 +397,7 @@
         with Op("commit", base_sha=base, plan_hash=req.plan_hash) as op:
             try:
                 for rel, text in req.files.items():
-                    target = path / rel
+                    target = _inside(path, rel)
                     if text is None:
                         target.unlink(missing_ok=True)
                     else:
@@ -635,3 +637,18 @@
     finally:
         if root:
             shutil.rmtree(root, ignore_errors=True)
+
+
+def _inside(worktree: Path, rel: str) -> Path:
+    """worktree/rel, to write or remove. The checkout materialises the repository's symlinks, and write_text or unlink would
+    follow one out of the worktree: a symlink at any component of rel is refused, and so is a target that resolves outside
+    the worktree (#446)."""
+    target = worktree
+    for part in Path(rel).parts:
+        target = target / part
+        if target.is_symlink():
+            raise GitFailed(f"the plan path {rel} goes through the repository's symlink {target.relative_to(worktree)}: "
+                            "nothing is written through a symlink")
+    if not target.resolve().is_relative_to(worktree.resolve()):
+        raise GitFailed(f"the plan path {rel} resolves outside the request's worktree")
+    return target
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/tests/test_git_workspace_review.py ws/cmapi/tests/test_git_workspace_review.py
--- pristine/cmapi/tests/test_git_workspace_review.py	1969-12-31 18:00:00
+++ ws/cmapi/tests/test_git_workspace_review.py	2026-11-18 23:13:34
@@ -0,0 +1,106 @@
+"""#446, #452 (Codex's F3, F9 of the Git delivery review, as OB3 corrected them): the Git layer never writes through a symlink
+the repository holds, and a folder that starts with "-" is a path. Real Git over file:// only."""
+from __future__ import annotations
+
+from dataclasses import replace
+from datetime import datetime, timezone
+
+import pytest
+
+from cmapi.core.git.base import BranchRequest
+from cmapi.core.git.workspace import GitFailed, GitWorkspace
+from gitserver import bare_repo, git
+
+# As the renderer makes it (core/render/manifests.folder): with the trailing slash.
+FOLDER = "clusters/CRC/namespaces/demo/"
+REL = FOLDER + "namespace.yaml"
+
+
+def req(**kw) -> BranchRequest:
+    r = BranchRequest("CRC", "req-1", FOLDER, "hash", "create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
+                      {REL: "kind: Namespace\n"}, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))
+    return replace(r, **kw)
+
+
+def person_pushes(tmp_path, bare, build) -> None:
+    """A person's commit on main, made in a clone of their own."""
+    work = tmp_path / "person"
+    git("clone", "--quiet", str(bare), str(work), cwd=tmp_path, home=tmp_path)
+    build(work)
+    git("add", "--all", cwd=work, home=tmp_path)
+    git("commit", "--quiet", "-m", "a person's commit", cwd=work, home=tmp_path)
+    git("push", "--quiet", "origin", "main", cwd=work, home=tmp_path)
+
+
+def test_a_symlinked_manifest_in_the_repository_is_never_written_through(tmp_path):
+    bare = bare_repo(tmp_path)
+    outside = tmp_path / "outside.yaml"
+    outside.write_text("must survive\n")
+
+    def build(work):
+        (work / FOLDER).mkdir(parents=True)
+        (work / REL).symlink_to(outside)
+    person_pushes(tmp_path, bare, build)
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
+    try:
+        with pytest.raises(GitFailed) as refused:
+            ws.push_branch(req())
+        assert outside.read_text() == "must survive\n"
+        assert "symlink" in str(refused.value)
+    finally:
+        ws.dispose()
+
+
+def test_a_symlinked_parent_folder_is_never_written_through(tmp_path):
+    """clusters/CRC is a symlink to a folder outside: cone mode checks out the files of every parent folder, this link too."""
+    bare = bare_repo(tmp_path)
+    outside = tmp_path / "outside-dir"
+    outside.mkdir()
+
+    def build(work):
+        (work / "clusters").mkdir()
+        (work / "clusters" / "CRC").symlink_to(outside)
+    person_pushes(tmp_path, bare, build)
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
+    try:
+        with pytest.raises(GitFailed) as refused:
+            ws.push_branch(req())
+        assert sorted(str(p.relative_to(outside)) for p in outside.rglob("*")) == [], "nothing was made outside the worktree"
+        assert "symlink" in str(refused.value)
+    finally:
+        ws.dispose()
+
+
+def test_a_leading_dash_folder_is_a_path_not_an_option(tmp_path):
+    bare = bare_repo(tmp_path)
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
+    try:
+        request = req(folder="-folder/", files={"-folder/namespace.yaml": "kind: Namespace\n"})
+        pushed = ws.push_branch(request)
+        assert ws.read_folder("-folder", pushed.head)[0] == {"-folder/namespace.yaml": "kind: Namespace\n"}
+    finally:
+        ws.dispose()
+
+
+def test_the_renderers_folder_with_its_trailing_slash_is_still_delivered(tmp_path):
+    """Control: core/render/manifests.folder ends in "/". Codex's patch ran check_path on it unstripped, which refuses an empty
+    part, so every real request failed at push_branch."""
+    bare = bare_repo(tmp_path)
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
+    try:
+        pushed = ws.push_branch(req())
+        assert pushed.result == "created"
+        assert ws.read_folder(FOLDER, pushed.head)[0] == {REL: "kind: Namespace\n"}
+    finally:
+        ws.dispose()
+
+
+@pytest.mark.parametrize("folder", ["../escape/", "clusters/../../x/"])
+def test_a_folder_that_is_not_a_repository_path_is_refused(tmp_path, folder):
+    bare = bare_repo(tmp_path)
+    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
+    try:
+        with pytest.raises(ValueError, match="not a repository path"):
+            ws.push_branch(req(folder=folder, files={}))
+    finally:
+        ws.dispose()

==================================================================== delivery-states.patch (verbatim)
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/src/cmapi/core/git/github.py ds/cmapi/src/cmapi/core/git/github.py
--- pristine/cmapi/src/cmapi/core/git/github.py	2026-11-18 20:15:02
+++ ds/cmapi/src/cmapi/core/git/github.py	2026-11-18 23:14:27
@@ -216,6 +216,10 @@
         raise PlatformRefused(f"merge PR {pr.number}: {r.status_code} {message}", r.status_code, message)
 
     def comment(self, pr: PrRef, text: str) -> None:
+        """At most once per text: a retry after a lost answer finds the comment the host kept, and posts nothing (#451). A read
+        before the write, not a host idempotency key: two writers at the same moment could still both post."""
+        if any(c.get("body") == text for c in self._pages("pr_comments", f"{self._repo()}/issues/{pr.number}/comments", None)):
+            return
         r = self._call("pr_comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": text}, ok=(201,))
         if r.status_code != 201:
             raise PlatformRefused(f"comment on PR {pr.number}: {r.status_code}", r.status_code, r.text[:300])
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/src/cmapi/core/lifecycle.py ds/cmapi/src/cmapi/core/lifecycle.py
--- pristine/cmapi/src/cmapi/core/lifecycle.py	2026-11-18 20:15:02
+++ ds/cmapi/src/cmapi/core/lifecycle.py	2026-11-18 23:14:27
@@ -78,6 +78,7 @@
     (S.MERGE_FAILED, E.MERGED): S.MERGED,
     (S.MERGE_FAILED, E.RETRY): S.MERGE_FAILED,    # the merge job again, pinned to the applied head; never a rollback
     (S.SYNC_FAILED, E.APPLIED): S.APPLIED,        # a :retry of an apply that had not finished (merge_sha null)
+    (S.SYNC_FAILED, E.MERGED): S.MERGED,          # that :retry finds a person merged the PR: adopted (#448)
     (S.MERGED, E.SYNCED): S.SYNCED,
     (S.MERGED, E.PRUNE_PENDING): S.AWAITING_PRUNE,
     (S.MERGED, E.SYNC_TIMEOUT): S.SYNC_FAILED,
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/src/cmapi/jobs/apply.py ds/cmapi/src/cmapi/jobs/apply.py
--- pristine/cmapi/src/cmapi/jobs/apply.py	2026-11-18 20:15:02
+++ ds/cmapi/src/cmapi/jobs/apply.py	2026-11-18 23:14:27
@@ -14,6 +14,10 @@
 
 Also from sync_failed with no merge sha (a :retry of an apply that had not finished). Deletes merge first (the arbitration,
 row 4) and never come here.
+
+A person may merge the PR between the checks and this job, and delete its branch: the branch is then gone or behind main, and
+the merge check sees main already holding the plan. Each of those refusals reads the PR first, and a merged PR is adopted
+through the merge job's post-merge check, never failed (the arbitration, row 16; #448).
 """
 from __future__ import annotations
 
@@ -31,7 +35,7 @@
 from cmapi.core.observability import MERGE_CONFLICTS
 from cmapi.core.render.manifests import folder
 from cmapi.core.sync import ApplyDelivery, confirmed_by_read
-from cmapi.jobs.delivery import APPLY_STARTED, apply_started, end_pr, mark_apply_started, mode_of, planned, request_context
+from cmapi.jobs.delivery import APPLY_STARTED, apply_started, end_pr, mark_apply_started, mode_of, planned, pr_of, request_context
 
 
 def apply(ctx: AppContext, s: Session, job: JobRow) -> None:
@@ -69,11 +73,15 @@
     removed = {p: row.plan["prev"][p] for p, t in row.plan["files"].items() if t is None and p in (row.plan.get("prev") or {})}
     current = ctx.git.branch_head(row.pr["branch"])
     if current != head:
+        if _adopt_merged(ctx, repo, jobs, row, job):
+            return
         return _stop(ctx, repo, jobs, row, job, f"the PR head moved from {head[:8]} to {(current or 'nothing')[:8]}", started)
     if ctx.git.tree_files(head, where) != files:
         return _stop(ctx, repo, jobs, row, job, f"the branch's folder at {head[:8]} is not the approved plan", started)
     check = ctx.git.merge_check(head, where, row.plan.get("prev") or {}, row.plan["files"])
     if not check.ok:
+        if _adopt_merged(ctx, repo, jobs, row, job):
+            return
         MERGE_CONFLICTS.labels("apply").inc()
         why = check.reason(ctx.git.default_branch)
         repo.event(row, "merge_check", "worker", why[:300], {"caller": "apply", "main": check.main_sha, "head": head,
@@ -124,6 +132,18 @@
     row.pr = {**row.pr, "applied_head": head}
     jobs.done(job)
     jobs.enqueue("merge", request_id=row.request_id, cluster_id=row.cluster_id, payload={"head": head})
+
+
+def _adopt_merged(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow) -> bool:
+    """A person merged the PR: adopted through the merge job's post-merge check (merged, then watch_sync applies from main), and
+    True. False while the PR is open or closed unmerged, and the caller's refusal stands."""
+    state = ctx.git.pr_status(pr_of(row))
+    if state.state != "merged":
+        return False
+    from cmapi.jobs.merge import _merged
+
+    _merged(ctx, repo, jobs, row, job, state.merge_sha or "", adopted=True)
+    return True
 
 
 def _wait(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, why: str, started: bool) -> None:
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/src/cmapi/jobs/merge.py ds/cmapi/src/cmapi/jobs/merge.py
--- pristine/cmapi/src/cmapi/jobs/merge.py	2026-11-18 20:15:02
+++ ds/cmapi/src/cmapi/jobs/merge.py	2026-11-18 23:14:27
@@ -132,22 +132,25 @@
 
 
 def _merged(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, sha: str, adopted: bool) -> None:
-    """Fable 2.4: the folder at the merge sha must be the plan's. Then merged; after an apply also synced, since the read
-    already confirmed it; otherwise watch_sync."""
+    """Fable 2.4, a gate on every path that records a merge (this job, a hand merge pr_checks or apply finds): the folder at
+    the merge sha must be the plan's. Then merged; after an apply also synced, since the read already confirmed it; otherwise
+    watch_sync. A merge whose folder is not the plan's, or with no sha to read, is merged and then sync_failed, with the lock
+    held for an operator: nothing is applied from it and a delete never waits for a prune of it (#449)."""
     after_apply = row.status in AFTER_APPLY
     on_main = ctx.git.tree_files(sha, folder(row.cluster_id, row.namespace)) if sha else None
+    fulfilled = on_main == planned(row)
     row.merge_sha = sha or None
     how = "adopted: merged on the host" if adopted else "merged"
-    repo.event(row, "merge_verified", "worker", f"{how} {sha[:8]}; the folder at it {'is' if on_main == planned(row) else 'is not'} the plan's",
+    repo.event(row, "merge_verified", "worker", f"{how} {sha[:8]}; the folder at it {'is' if fulfilled else 'is not'} the plan's",
                {"merge_sha": sha, "adopted": adopted})
     repo.move(row, E.MERGED, "cmapi-bot", f"{how} {sha[:8]}")
-    if after_apply:
-        if on_main == planned(row):
-            repo.move(row, E.SYNCED, "cmapi-deliverer", "applied and confirmed by a read before the merge")
-            approval = "auto" if (row.requirement or {}).get("auto") else "human"
-            LEAD_TIME.labels(row.plugin, row.action, approval).observe((datetime.now(timezone.utc) - row.created_at).total_seconds())
-        else:
-            repo.move(row, E.SYNC_TIMEOUT, "worker", f"the folder at the merge {sha[:8]} is not the applied plan")
+    if not fulfilled:
+        why = f"the folder at the merge {sha[:8]} is not the approved plan" if sha else "the host gave no merge sha to check"
+        repo.move(row, E.SYNC_TIMEOUT, "worker", why)
+    elif after_apply:
+        repo.move(row, E.SYNCED, "cmapi-deliverer", "applied and confirmed by a read before the merge")
+        approval = "auto" if (row.requirement or {}).get("auto") else "human"
+        LEAD_TIME.labels(row.plugin, row.action, approval).observe((datetime.now(timezone.utc) - row.created_at).total_seconds())
     else:
         jobs.enqueue("watch_sync", request_id=row.request_id, cluster_id=row.cluster_id)
     ctx.git.cleanup(row.cluster_id, row.request_id)
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/src/cmapi/jobs/pr_checks.py ds/cmapi/src/cmapi/jobs/pr_checks.py
--- pristine/cmapi/src/cmapi/jobs/pr_checks.py	2026-11-18 20:15:02
+++ ds/cmapi/src/cmapi/jobs/pr_checks.py	2026-11-18 23:14:27
@@ -57,12 +57,11 @@
         jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
         return
     if status.state == "merged":
-        # A person merged it before any apply: adopted. In apply mode watch_sync then applies from main (Fable 1.1).
-        row.merge_sha = status.merge_sha
-        repo.move(row, E.MERGED, "cmapi-bot", f"merged {(status.merge_sha or '')[:8]} on the host")
-        jobs.done(job)
-        jobs.enqueue("watch_sync", request_id=row.request_id, cluster_id=row.cluster_id)
-        jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
+        # A person merged it before any apply: adopted through the merge job's post-merge check (#449). In apply mode
+        # watch_sync then applies from main (Fable 1.1).
+        from cmapi.jobs.merge import _merged
+
+        _merged(ctx, repo, jobs, row, job, status.merge_sha or "", adopted=True)
         return
     # A context nobody has reported yet is pending: the workflow may not have started.
     ci = {c: status.checks.get(c, "pending") for c in CI_CONTEXTS} if ctx.git.external_ci else {}
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/tests/core/test_lifecycle_expiration.py ds/cmapi/tests/core/test_lifecycle_expiration.py
--- pristine/cmapi/tests/core/test_lifecycle_expiration.py	2026-11-18 20:15:02
+++ ds/cmapi/tests/core/test_lifecycle_expiration.py	2026-11-18 23:14:38
@@ -45,7 +45,10 @@
     t = transition(S.MERGED, E.SYNC_TIMEOUT)
     assert t.after == S.SYNC_FAILED and holds_lock(S.SYNC_FAILED) and t.releases_reservation
     # APPLIED: a :retry of an apply that had not finished, before any merge (#286)
-    assert set(allowed_events(S.SYNC_FAILED)) == {E.RETRY, E.SYNCED, E.REVERT, E.APPLIED}
+    assert set(allowed_events(S.SYNC_FAILED)) == {E.RETRY, E.SYNCED, E.REVERT, E.APPLIED, E.MERGED}
+    # MERGED: that :retry finds a person merged the PR, and adopts it with the lock still held (#448)
+    adopted = transition(S.SYNC_FAILED, E.MERGED)
+    assert adopted.after == S.MERGED and holds_lock(S.MERGED) and not adopted.releases_lock
 
 
 def test_a_prune_that_cannot_be_confirmed_ends_in_sync_failed():
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/tests/service/gitserver.py ds/cmapi/tests/service/gitserver.py
--- pristine/cmapi/tests/service/gitserver.py	2026-11-18 20:15:02
+++ ds/cmapi/tests/service/gitserver.py	2026-11-18 23:14:38
@@ -376,6 +376,8 @@
             self._git("update-ref", "-d", f"refs/heads/{branch}")
             return httpx.Response(204)
         m = _re.fullmatch(r"/issues/(\d+)/comments", path)
+        if m and request.method == "GET":          # one page: the adapter reads before it comments (#451)
+            return httpx.Response(200, json=[{"body": text} for n, text in self.comments if n == int(m[1])])
         if m and request.method == "POST":
             self.comments.append((int(m[1]), body["body"]))
             return httpx.Response(201, json={"id": len(self.comments)})
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/tests/service/test_delivery_states_db_review.py ds/cmapi/tests/service/test_delivery_states_db_review.py
--- pristine/cmapi/tests/service/test_delivery_states_db_review.py	1969-12-31 18:00:00
+++ ds/cmapi/tests/service/test_delivery_states_db_review.py	2026-11-18 23:58:10
@@ -0,0 +1,71 @@
+"""#448, #449, #451 (Codex's F5, F6, F8 of the Git delivery review, as OB3 corrected them): a hand merge between the checks and
+the apply is adopted; the folder at a merge is a gate on every path that records one; a comment whose answer was lost is not
+posted twice. These against PostgreSQL, real Git and the GitHub stub (test_git_layer's world); the doubles are in
+tests/test_delivery_states_review.py."""
+from __future__ import annotations
+
+import json
+
+import httpx
+import pytest
+
+from gitserver import git
+from test_flow import AMY, OLA, auth
+from test_git_layer import API, drive, layer  # noqa: F401  (the fixture)
+
+REPO = "/repos/cmapi/cluster-configs-test"
+
+
+def person_merges(w, branch: str, head: str) -> None:
+    """A person merges PR #n on the host, pinned to head, as GitHub's merge button does."""
+    n = next(n for n, p in w.host.prs.items() if p["ref"] == branch and p["state"] == "open")
+    answer = w.host(httpx.Request("PUT", f"{API}{REPO}/pulls/{n}/merge", content=json.dumps({"sha": head}).encode()))
+    assert answer.status_code == 200, answer.text
+
+
+# ---------------------------------------------------------------- #448: a hand merge between pr_checks and apply
+
+@pytest.mark.parametrize("deletes_branch", [True, False])
+def test_a_hand_merge_after_the_checks_is_adopted_by_the_apply_job(layer, deletes_branch):
+    w = layer
+    rid = w.create()
+    assert drive(w.ctx, limit=3) == ["push_branch", "open_pr", "pr_checks"]          # apply is next
+    branch = f"cmapi/CRC/{rid}"
+    person_merges(w, branch, w.host.head(branch))
+    if deletes_branch:
+        git("--git-dir", str(w.bare), "update-ref", "-d", f"refs/heads/{branch}", cwd=w.bare, home=w.tmp)
+    drive(w.ctx)
+    v = w.view(rid)
+    events = w.events(rid)
+    assert v["status"] == "synced", [(e["event"], e["note"]) for e in v["events"]]
+    assert "merge_verified" in events and events.index("merged") < events.index("applied"), "watch_sync applied from main"
+    assert len(w.host.merges) == 1, "cmapi merged nothing itself"
+
+
+# ---------------------------------------------------------------- #449: the folder at the merge, on the hand-merge path of a delete
+
+def test_a_hand_merged_delete_whose_merge_keeps_the_folder_is_sync_failed_not_awaiting_prune(layer):
+    w = layer
+    h = auth(w.keys, "ola", **OLA)
+    w.create()
+    drive(w.ctx)
+    etag = w.client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
+    delete = w.client.delete("/api/v1/clusters/CRC/namespaces/payments-dev",
+                             headers={**h, "If-Match": etag}).json()["requestId"]
+    w.client.post(f"/api/v1/requests/{delete}:approve", json={}, headers=auth(w.keys, "amy", **AMY))
+    for _ in range(10):                          # the approval's notification first, then push_branch and open_pr
+        if w.view(delete)["status"] == "pr_open":
+            break
+        drive(w.ctx, limit=1)
+    assert w.view(delete)["status"] == "pr_open"
+    branch = f"cmapi/CRC/{delete}"
+    # A person pushes a commit that puts the folder back on the branch, and merges it: main keeps the namespace.
+    tree = git("--git-dir", str(w.bare), "rev-parse", "main^{tree}", cwd=w.bare, home=w.tmp)
+    restored = git("--git-dir", str(w.bare), "commit-tree", tree, "-p", w.host.head(branch), "-m", "keep it",
+                   cwd=w.bare, home=w.tmp)
+    git("--git-dir", str(w.bare), "update-ref", f"refs/heads/{branch}", restored, cwd=w.bare, home=w.tmp)
+    person_merges(w, branch, restored)
+    drive(w.ctx)
+    v = w.view(delete)
+    assert v["status"] == "sync_failed", [(e["event"], e["note"]) for e in v["events"]]
+    assert "awaiting_prune" not in [e["event"] for e in v["events"]] and "prune_pending" not in w.events(delete)
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/tests/test_delivery_states_review.py ds/cmapi/tests/test_delivery_states_review.py
--- pristine/cmapi/tests/test_delivery_states_review.py	1969-12-31 18:00:00
+++ ds/cmapi/tests/test_delivery_states_review.py	2026-11-18 23:16:28
@@ -0,0 +1,140 @@
+"""#448, #449, #451 (Codex's F5, F6, F8 of the Git delivery review, as OB3 corrected them), with doubles: the states reached
+directly, no database. The same cases against PostgreSQL, real Git and the GitHub stub are in
+tests/service/test_delivery_states_db_review.py."""
+from __future__ import annotations
+
+import importlib
+import json
+from types import SimpleNamespace as NS
+
+import httpx
+import pytest
+
+from cmapi.core.git.base import GitUnavailable
+from cmapi.core.git.github import GitHubProvider
+from cmapi.core.lifecycle import State as S, transition
+from cmapi.core.ports import PrRef, PrStatus
+
+
+# ---------------------------------------------------------------- doubles: the same gates, reached directly
+
+class Repo:
+    def __init__(self, events=()):
+        self.seen, self._events = [], list(events)
+
+    def events(self, request_id):
+        return self._events
+
+    def event(self, row, event, by, note="", detail=None):
+        self.seen.append(event)
+
+    def move(self, row, event, by, note=""):
+        row.status = transition(S(row.status), event).after.value
+        self.seen.append(event.value)
+
+
+class Jobs:
+    def __init__(self):
+        self.queued, self.finished = [], False
+
+    def fence(self):
+        pass
+
+    def done(self, job):
+        self.finished = True
+
+    def enqueue(self, kind, **kw):
+        self.queued.append(kind)
+
+
+FOLDER = "clusters/CRC/namespaces/demo/"
+REL = FOLDER + "namespace.yaml"
+HEAD, MERGE = "a" * 40, "b" * 40
+
+
+def row(status="pr_open"):
+    return NS(status=status, cluster_id="CRC", namespace="demo", request_id="req-1", action="create",
+              plan={"files": {REL: "approved"}, "prev": {}}, merge_sha=None,
+              pr={"number": 1, "url": "", "branch": "cmapi/CRC/req-1", "head": HEAD})
+
+
+@pytest.mark.parametrize("status", ["pr_open", "sync_failed"])
+def test_apply_adopts_a_hand_merge_whose_branch_is_gone(status):
+    apply_mod = importlib.import_module("cmapi.jobs.apply")
+    r = row(status)
+    repo = Repo([NS(event="apply_started", detail={"head": HEAD})] if status == "sync_failed" else [])
+    jobs = Jobs()
+    ctx = NS(git=NS(pr_status=lambda pr: PrStatus("merged", {}, MERGE, HEAD), branch_head=lambda b: None,
+                    tree_files=lambda sha, f: {REL: "approved"}, cleanup=lambda *a: None))
+    apply_mod._apply(ctx, repo, jobs, r, NS(payload={"head": HEAD}))
+    assert (r.status, r.merge_sha, jobs.queued) == ("merged", MERGE, ["watch_sync", "git_cleanup"])
+
+
+def test_an_apply_that_waits_on_the_cluster_reads_no_pr():
+    """Control for the shape of the #448 fix: the PR is read only when a check refuses. An apply that waits at pollInterval
+    (here: the cluster cannot be reached) makes no extra host call per poll. Passes on main; Codex's upfront read makes one."""
+    from datetime import datetime, timezone
+
+    from cmapi.core.clients.kube import ClusterUnreachable
+    from cmapi.core.git.base import MergeCheck
+
+    apply_mod = importlib.import_module("cmapi.jobs.apply")
+    reads, retried = [], []
+
+    def unreachable(cid):
+        raise ClusterUnreachable("CRC is down")
+    ctx = NS(git=NS(pr_status=lambda pr: reads.append(pr) or PrStatus("open", {}, None, HEAD), branch_head=lambda b: HEAD,
+                    tree_files=lambda sha, f: {REL: "approved"}, default_branch="main",
+                    merge_check=lambda *a: MergeCheck("m" * 40, HEAD)),
+             deliverer_factory=unreachable, delivery=NS(sync_timeout_seconds=600, poll_seconds=5))
+    jobs = Jobs()
+    jobs.retry = lambda job, why, delay: retried.append(why)
+    job = NS(payload={"head": HEAD}, created_at=datetime.now(timezone.utc), last_error=None, attempts=1)
+    apply_mod._apply(ctx, Repo(), jobs, row(), job)
+    assert retried and reads == []
+
+
+@pytest.mark.parametrize("status", ["pr_open", "applied"])
+def test_a_merge_whose_folder_is_not_the_plan_never_queues_delivery(status):
+    merge_mod = importlib.import_module("cmapi.jobs.merge")
+    r, repo, jobs = row(status), Repo(), Jobs()
+    ctx = NS(git=NS(tree_files=lambda sha, f: {REL: "unapproved"}, cleanup=lambda *a: None))
+    merge_mod._merged(ctx, repo, jobs, r, NS(), MERGE, adopted=True)
+    assert r.status == "sync_failed" and "watch_sync" not in jobs.queued
+
+
+def test_a_merge_with_no_sha_to_read_is_sync_failed():
+    merge_mod = importlib.import_module("cmapi.jobs.merge")
+    r, repo, jobs = row(), Repo(), Jobs()
+    ctx = NS(git=NS(tree_files=lambda sha, f: pytest.fail("nothing to read"), cleanup=lambda *a: None))
+    merge_mod._merged(ctx, repo, jobs, r, NS(), "", adopted=True)
+    assert r.status == "sync_failed" and "watch_sync" not in jobs.queued
+
+
+def test_pr_checks_sends_a_hand_merge_through_the_post_merge_check():
+    checks = importlib.import_module("cmapi.jobs.pr_checks")
+    r, repo, jobs = row(), Repo(), Jobs()
+    ctx = NS(git=NS(pr_status=lambda pr: PrStatus("merged", {}, MERGE, HEAD), tree_files=lambda sha, f: {REL: "unapproved"},
+                    cleanup=lambda *a: None))
+    checks._pr_checks(ctx, repo, jobs, r, NS())
+    assert r.status == "sync_failed" and "merge_verified" in repo.seen and "watch_sync" not in jobs.queued
+
+
+# ---------------------------------------------------------------- #451: a comment whose answer was lost
+
+def test_a_comment_whose_answer_was_lost_is_not_posted_again():
+    kept = []
+
+    def host(request):
+        if request.method == "GET":
+            return httpx.Response(200, json=[{"body": body} for body in kept])
+        kept.append(json.loads(request.content)["body"])
+        return httpx.Response(502 if len(kept) == 1 else 201)       # the host kept the first, and its answer was lost
+    provider = GitHubProvider("https://offline.invalid", "o/r", "test-token-0123456789")
+    provider._client.close()
+    provider._client = httpx.Client(base_url="https://offline.invalid", transport=httpx.MockTransport(host))
+    pr = PrRef(1, "", "cmapi/CRC/req-1", HEAD)
+    with pytest.raises(GitUnavailable):
+        provider.comment(pr, "cmapi: merge failed; :retry merges it")
+    provider.comment(pr, "cmapi: merge failed; :retry merges it")
+    assert kept == ["cmapi: merge failed; :retry merges it"]

==================================================================== gitea.patch (verbatim)
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/src/cmapi/core/git/gitea.py gitea/cmapi/src/cmapi/core/git/gitea.py
--- pristine/cmapi/src/cmapi/core/git/gitea.py	2026-11-18 20:15:02
+++ gitea/cmapi/src/cmapi/core/git/gitea.py	2026-11-18 23:17:03
@@ -1,6 +1,7 @@
 """GitProvider for Gitea (API v1). Endpoints as documented for Gitea 1.25:
 
     GET  /repos/{o}/{r}/branches/{b}                    head sha
+    GET  /repos/{o}/{r}/git/commits/{sha}               a commit: its message (the trailers) and its parents
     GET  /repos/{o}/{r}/contents/{path}?ref=            folder listing, file content (base64)
     POST /repos/{o}/{r}/branches                        {new_branch_name, old_ref_name}
     POST /repos/{o}/{r}/contents                        one commit with several files {files: [...]}
@@ -18,6 +19,7 @@
 from typing import Any, Mapping
 
 from cmapi.core.git.base import BranchRequest, CheckState, GitUnavailable, HostGitProvider, PushResult
+from cmapi.core.git.workspace import TRAILER_PLAN_HASH, TRAILER_REQUEST, BranchMoved, BranchRefused, request_branch
 from cmapi.core.ports import PrRef, PrStatus
 
 
@@ -52,21 +54,27 @@
         return files, head
 
     def push_request_branch(self, req: BranchRequest) -> PushResult:
-        """Through Gitea's REST API, not the Git layer: the chart's stand-in. A branch with no open PR is one the bot left or
-        anyone may have pushed to, so it is deleted and written again from the default branch's head."""
-        from cmapi.core.git.workspace import request_branch
-
+        """Through Gitea's REST API, not the Git layer: the chart's stand-in, whose Gitea the cluster serves over plain http, which
+        the Git layer refuses. A branch that exists is handled as the Git layer handles it (the arbitration of #286, row 3;
+        #450): adopted when its head is this request's commit of this plan with the plan's files; deleted and written again
+        when it is this request's own stale attempt; refused, and left as it is, when it is anyone else's. An open PR proves
+        nothing about the head. REST has no lease, so the delete of a stale attempt reads the head first (delete_branch)."""
         branch = request_branch(req.cluster_id, req.request_id)
         base = self.branch_head(self.default_branch)
         if base is None:
             raise GitUnavailable(f"branch {self.default_branch} does not exist")
-        if self.branch_head(branch) is not None:
-            existing = self.find_pr(branch)
-            if existing is not None:
-                return PushResult(existing.head_sha, base, "adopted")
-            r = self._call("delete_branch", "DELETE", f"{self._repo()}/branches/{branch}", ok=(204,))
-            if r.status_code != 204:
-                raise GitUnavailable(f"delete stale branch {branch}: {r.status_code} {r.text[:200]}")
+        existing = self.branch_head(branch)
+        if existing is not None:
+            trailers, parents = self._commit(existing)
+            planned = {p: t for p, t in req.files.items() if t is not None}
+            if trailers.get(TRAILER_REQUEST) != [req.request_id]:
+                raise BranchRefused(f"branch {branch} exists at {existing[:8]} and its head is not cmapi's commit for "
+                                    f"{req.request_id}: it is not adopted or overwritten")
+            if trailers.get(TRAILER_PLAN_HASH) == [req.plan_hash] and len(parents) == 1 and \
+                    self.read_folder(req.folder, existing)[0] == planned:
+                return PushResult(existing, parents[0], "adopted")
+            if not self.delete_branch(branch, existing):
+                raise BranchMoved(f"branch {branch} moved from {existing[:8]} before its stale attempt was replaced")
         r = self._call("create_branch", "POST", f"{self._repo()}/branches",
                        json={"new_branch_name": branch, "old_ref_name": base}, ok=(201,))
         if r.status_code != 201:
@@ -90,7 +98,21 @@
             if r.status_code not in (200, 201):
                 raise GitUnavailable(f"commit on {branch}: {r.status_code} {r.text[:300]}")
         head = self.branch_head(branch)
-        return PushResult(head or base, base, "created")
+        return PushResult(head or base, base, "created" if existing is None else "replaced")
+
+    def _commit(self, sha: str) -> tuple[dict[str, list[str]], list[str]]:
+        """A commit's cmapi trailers ({key: [values]}, from its message's last paragraph) and its parents' shas."""
+        r = self._call("commit_read", "GET", f"{self._repo()}/git/commits/{sha}", ok=(200,))
+        if r.status_code != 200:
+            raise GitUnavailable(f"read commit {sha[:8]}: {r.status_code} {r.text[:200]}")
+        body = r.json()
+        paragraphs = [p for p in ((body.get("commit") or {}).get("message") or "").strip().split("\n\n") if p.strip()]
+        trailers: dict[str, list[str]] = {}
+        for line in (paragraphs[-1].splitlines() if paragraphs else []):
+            key, sep, value = line.partition(":")
+            if sep and key.strip() in (TRAILER_REQUEST, TRAILER_PLAN_HASH):
+                trailers.setdefault(key.strip(), []).append(value.strip())
+        return trailers, [p["sha"] for p in body.get("parents") or []]
 
     def recreate_branch(self, req: BranchRequest, base: str, expected: str) -> str:
         raise GitUnavailable("the Gitea stand-in is not on the Git layer: a closed PR's branch is not re-created")
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/tests/service/test_second_pass.py gitea/cmapi/tests/service/test_second_pass.py
--- pristine/cmapi/tests/service/test_second_pass.py	2026-11-18 20:15:02
+++ gitea/cmapi/tests/service/test_second_pass.py	2026-11-18 23:17:41
@@ -577,6 +577,11 @@
             return httpx.Response(200, json=[])
         if req.method == "GET" and "/branches/" in p:
             return httpx.Response(200, json={"commit": {"id": "b" * 40}}) if exists["branch"] else httpx.Response(404, json={})
+        if req.method == "GET" and "/git/commits/" in p:
+            # This request's own earlier attempt, of another plan: replaced. A head that is not this request's is refused
+            # and never deleted (the arbitration of #286, row 3; tests/test_gitea_review.py).
+            return httpx.Response(200, json={"commit": {"message": "t\n\nCmapi-Request-Id: br\nCmapi-Plan-Hash: older\n"},
+                                             "parents": [{"sha": "a" * 40}]})
         if req.method == "DELETE":
             exists["branch"] = False
             return httpx.Response(204)
diff -ruN --exclude=__pycache__ --exclude=.pytest_cache pristine/cmapi/tests/test_gitea_review.py gitea/cmapi/tests/test_gitea_review.py
--- pristine/cmapi/tests/test_gitea_review.py	1969-12-31 18:00:00
+++ gitea/cmapi/tests/test_gitea_review.py	2026-11-18 23:17:30
@@ -0,0 +1,115 @@
+"""#450 (Codex's F7 of the Git delivery review, as OB3 corrected it): the Gitea REST stand-in handles a branch that exists as the
+Git layer does (the arbitration of #286, row 3). An open PR proves nothing about the head; a head that is not this request's is
+refused and never deleted; this request's own stale attempt is replaced; this request's current commit is adopted with no
+write. Its branch delete after a merge still works. Offline: httpx.MockTransport only."""
+from __future__ import annotations
+
+import json
+from datetime import datetime, timezone
+
+import httpx
+import pytest
+
+from cmapi.core.git.base import BranchRequest
+from cmapi.core.git.gitea import GiteaProvider
+from cmapi.core.git.workspace import BranchRefused
+
+FOLDER = "clusters/CRC/namespaces/demo/"
+REL = FOLDER + "namespace.yaml"
+BRANCH = "cmapi/CRC/req-1"
+MAIN, HEAD = "1" * 40, "a" * 40
+PLAN = {REL: "kind: Namespace\n"}
+
+
+def req() -> BranchRequest:
+    return BranchRequest("CRC", "req-1", FOLDER, "hash", "create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
+                         PLAN, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))
+
+
+class Host:
+    """Gitea's REST paths the stand-in calls, over one existing request branch."""
+
+    def __init__(self, message: str, files: dict[str, str], open_pr: bool):
+        import base64
+
+        self.message, self.files, self.open_pr = message, files, open_pr
+        self.branch: str | None = HEAD
+        self.calls: list[tuple[str, str]] = []
+        self.b64 = lambda text: base64.b64encode(text.encode()).decode()
+
+    def __call__(self, request: httpx.Request) -> httpx.Response:
+        path, method = request.url.path.removeprefix("/api/v1/repos/o/r"), request.method
+        self.calls.append((method, path))
+        if method == "GET" and path == "/branches/main":
+            return httpx.Response(200, json={"commit": {"id": MAIN}})
+        if method == "GET" and path == f"/branches/{BRANCH}":
+            return httpx.Response(200, json={"commit": {"id": self.branch}}) if self.branch else httpx.Response(404, json={})
+        if method == "GET" and path == f"/git/commits/{HEAD}":
+            return httpx.Response(200, json={"sha": HEAD, "commit": {"message": self.message}, "parents": [{"sha": MAIN}]})
+        if method == "GET" and path == "/pulls":
+            return httpx.Response(200, json=[{"number": 1, "head": {"ref": BRANCH, "sha": HEAD}}] if self.open_pr else [])
+        if method == "GET" and path == f"/contents/{FOLDER.rstrip('/')}":
+            return httpx.Response(200, json=[{"type": "file", "name": p.rsplit("/", 1)[1], "path": p} for p in self.files])
+        if method == "GET" and path.startswith("/contents/"):
+            return httpx.Response(200, json={"content": self.b64(self.files.get(path[len("/contents/"):], "")), "sha": "f" * 40})
+        if method == "DELETE" and path == f"/branches/{BRANCH}":
+            self.branch = None
+            return httpx.Response(204)
+        if method == "POST" and path == "/branches":
+            self.branch, self.files = "c" * 40, {}
+            return httpx.Response(201, json={})
+        if method == "POST" and path == "/contents":
+            return httpx.Response(201, json={})
+        raise AssertionError(f"unexpected {method} {path}")
+
+
+def provider(host: Host) -> GiteaProvider:
+    g = GiteaProvider("https://g.test/api/v1", "o/r", "test-token-0123456789")
+    g._client.close()
+    g._client = httpx.Client(base_url="https://g.test/api/v1", transport=httpx.MockTransport(host))
+    return g
+
+
+def writes(host: Host) -> list[tuple[str, str]]:
+    return [(m, p) for m, p in host.calls if m != "GET"]
+
+
+@pytest.mark.parametrize("open_pr", [True, False])
+def test_a_head_that_is_not_this_requests_is_refused_and_left_alone(open_pr):
+    host = Host("a person's change\n", {REL: "kind: Namespace\nmetadata: {name: other}\n"}, open_pr)
+    with pytest.raises(BranchRefused):
+        provider(host).push_request_branch(req())
+    assert writes(host) == [] and host.branch == HEAD, "neither adopted through its PR nor deleted"
+
+
+def test_this_requests_current_commit_is_adopted_with_no_write():
+    host = Host("create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n", dict(PLAN), open_pr=False)
+    pushed = provider(host).push_request_branch(req())
+    assert (pushed.head, pushed.base, pushed.result) == (HEAD, MAIN, "adopted") and writes(host) == []
+
+
+def test_this_requests_stale_attempt_is_replaced():
+    host = Host("create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: an-older-plan\n", dict(PLAN), open_pr=False)
+    pushed = provider(host).push_request_branch(req())
+    assert pushed.result == "replaced"
+    assert writes(host)[:2] == [("DELETE", f"/branches/{BRANCH}"), ("POST", "/branches")]
+
+
+def test_the_branch_of_a_merged_request_is_still_deleted():
+    """Control: git_cleanup after every merge. Codex's patch raised here, so every merged request's cleanup failed five times,
+    and one still in merged after the fifth (argocd mode, waiting for the sync) became sync_failed (worker.py)."""
+    host = Host("", {}, open_pr=False)
+    assert provider(host).delete_branch(BRANCH, HEAD) is True
+    assert ("DELETE", f"/branches/{BRANCH}") in host.calls and host.branch is None
+
+
+def test_a_branch_that_moved_is_not_deleted():
+    host = Host("", {}, open_pr=False)
+    assert provider(host).delete_branch(BRANCH, "e" * 40) is False and writes(host) == []
+
+
+def test_the_message_trailers_parse_only_from_the_last_paragraph():
+    host = Host("create\n\nCmapi-Request-Id: req-1 is quoted in the body\n\nCmapi-Request-Id: other\n", {}, open_pr=False)
+    trailers, parents = provider(host)._commit(HEAD)
+    assert trailers == {"Cmapi-Request-Id": ["other"]} and parents == [MAIN]
+    assert json.dumps(trailers)

==================================================================== gitea-on-453.patch (verbatim)
diff -ruN --exclude=__pycache__ pr453/cmapi/src/cmapi/core/git/gitea.py gitea453/cmapi/src/cmapi/core/git/gitea.py
--- pr453/cmapi/src/cmapi/core/git/gitea.py	2026-11-18 23:26:06
+++ gitea453/cmapi/src/cmapi/core/git/gitea.py	2026-11-19 00:06:45
@@ -1,6 +1,7 @@
 """GitProvider for Gitea (API v1). Endpoints as documented for Gitea 1.25:
 
     GET  /repos/{o}/{r}/branches/{b}                    head sha
+    GET  /repos/{o}/{r}/git/commits/{sha}               a commit: its message (the trailers) and its parents
     GET  /repos/{o}/{r}/contents/{path}?ref=            folder listing, file content (base64)
     POST /repos/{o}/{r}/branches                        {new_branch_name, old_ref_name}
     POST /repos/{o}/{r}/contents                        one commit with several files {files: [...]}
@@ -18,6 +19,7 @@
 from typing import Any, Mapping
 
 from cmapi.core.git.base import BranchRequest, CheckState, GitUnavailable, HostGitProvider, PushResult
+from cmapi.core.git.workspace import TRAILER_PLAN_HASH, TRAILER_REQUEST, BranchMoved, BranchRefused, request_branch
 from cmapi.core.ports import PrRef, PrStatus
 
 
@@ -52,21 +54,27 @@
         return files, head
 
     def push_request_branch(self, req: BranchRequest) -> PushResult:
-        """Through Gitea's REST API, not the Git layer: the chart's stand-in. A branch with no open PR is one the bot left or
-        anyone may have pushed to, so it is deleted and written again from the default branch's head."""
-        from cmapi.core.git.workspace import request_branch
-
+        """Through Gitea's REST API, not the Git layer: the chart's stand-in, whose Gitea the cluster serves over plain http, which
+        the Git layer refuses. A branch that exists is handled as the Git layer handles it (the arbitration of #286, row 3;
+        #450): adopted when its head is this request's commit of this plan with the plan's files; deleted and written again
+        when it is this request's own stale attempt; refused, and left as it is, when it is anyone else's. An open PR proves
+        nothing about the head. REST has no lease, so the delete of a stale attempt reads the head first (delete_branch)."""
         branch = request_branch(req.cluster_id, req.request_id)
         base = self.branch_head(self.default_branch)
         if base is None:
             raise GitUnavailable(f"branch {self.default_branch} does not exist")
-        if self.branch_head(branch) is not None:
-            existing = self.find_pr(branch)
-            if existing is not None:
-                return PushResult(existing.head_sha, base, "adopted")
-            r = self._call("delete_branch", "DELETE", f"{self._repo()}/branches/{branch}", ok=(204,))
-            if r.status_code != 204:
-                raise GitUnavailable(f"delete stale branch {branch}: {r.status_code} {self.host_text(r, 200)}")
+        existing = self.branch_head(branch)
+        if existing is not None:
+            trailers, parents = self._commit(existing)
+            planned = {p: t for p, t in req.files.items() if t is not None}
+            if trailers.get(TRAILER_REQUEST) != [req.request_id]:
+                raise BranchRefused(f"branch {branch} exists at {existing[:8]} and its head is not cmapi's commit for "
+                                    f"{req.request_id}: it is not adopted or overwritten")
+            if trailers.get(TRAILER_PLAN_HASH) == [req.plan_hash] and len(parents) == 1 and \
+                    self.read_folder(req.folder, existing)[0] == planned:
+                return PushResult(existing, parents[0], "adopted")
+            if not self.delete_branch(branch, existing):
+                raise BranchMoved(f"branch {branch} moved from {existing[:8]} before its stale attempt was replaced")
         r = self._call("create_branch", "POST", f"{self._repo()}/branches",
                        json={"new_branch_name": branch, "old_ref_name": base}, ok=(201,))
         if r.status_code != 201:
@@ -90,7 +98,22 @@
             if r.status_code not in (200, 201):
                 raise GitUnavailable(f"commit on {branch}: {r.status_code} {self.host_text(r)}")
         head = self.branch_head(branch)
-        return PushResult(head or base, base, "created")
+        return PushResult(head or base, base, "created" if existing is None else "replaced")
+
+    def _commit(self, sha: str) -> tuple[dict[str, list[str]], list[str]]:
+        """A commit's cmapi trailers ({key: [values]}, from its message's last paragraph) and its parents' shas."""
+        r = self._call("commit_read", "GET", f"{self._repo()}/git/commits/{sha}", ok=(200,))
+        if r.status_code != 200:
+            raise GitUnavailable(f"read commit {sha[:8]}: {r.status_code} {self.host_text(r, 200)}")
+        body = r.json()
+        paragraphs = [p for p in ((body.get("commit") or {}).get("message") or "").strip().split("\n\n") if p.strip()]
+        trailers: dict[str, list[str]] = {}
+        for line in (paragraphs[-1].splitlines() if paragraphs else []):
+            key, sep, value = line.partition(":")
+            if sep and key.strip() in (TRAILER_REQUEST, TRAILER_PLAN_HASH):
+                trailers.setdefault(key.strip(), []).append(value.strip())
+        return trailers, [p["sha"] for p in body.get("parents") or []]
+
 
     def recreate_branch(self, req: BranchRequest, base: str, expected: str) -> str:
         raise GitUnavailable("the Gitea stand-in is not on the Git layer: a closed PR's branch is not re-created")
diff -ruN --exclude=__pycache__ pr453/cmapi/tests/service/test_second_pass.py gitea453/cmapi/tests/service/test_second_pass.py
--- pr453/cmapi/tests/service/test_second_pass.py	2026-11-18 23:26:06
+++ gitea453/cmapi/tests/service/test_second_pass.py	2026-11-19 00:06:45
@@ -577,6 +577,11 @@
             return httpx.Response(200, json=[])
         if req.method == "GET" and "/branches/" in p:
             return httpx.Response(200, json={"commit": {"id": "b" * 40}}) if exists["branch"] else httpx.Response(404, json={})
+        if req.method == "GET" and "/git/commits/" in p:
+            # This request's own earlier attempt, of another plan: replaced. A head that is not this request's is refused
+            # and never deleted (the arbitration of #286, row 3; tests/test_gitea_review.py).
+            return httpx.Response(200, json={"commit": {"message": "t\n\nCmapi-Request-Id: br\nCmapi-Plan-Hash: older\n"},
+                                             "parents": [{"sha": "a" * 40}]})
         if req.method == "DELETE":
             exists["branch"] = False
             return httpx.Response(204)
diff -ruN --exclude=__pycache__ pr453/cmapi/tests/test_gitea_review.py gitea453/cmapi/tests/test_gitea_review.py
--- pr453/cmapi/tests/test_gitea_review.py	1969-12-31 18:00:00
+++ gitea453/cmapi/tests/test_gitea_review.py	2026-11-19 00:06:45
@@ -0,0 +1,115 @@
+"""#450 (Codex's F7 of the Git delivery review, as OB3 corrected it): the Gitea REST stand-in handles a branch that exists as the
+Git layer does (the arbitration of #286, row 3). An open PR proves nothing about the head; a head that is not this request's is
+refused and never deleted; this request's own stale attempt is replaced; this request's current commit is adopted with no
+write. Its branch delete after a merge still works. Offline: httpx.MockTransport only."""
+from __future__ import annotations
+
+import json
+from datetime import datetime, timezone
+
+import httpx
+import pytest
+
+from cmapi.core.git.base import BranchRequest
+from cmapi.core.git.gitea import GiteaProvider
+from cmapi.core.git.workspace import BranchRefused
+
+FOLDER = "clusters/CRC/namespaces/demo/"
+REL = FOLDER + "namespace.yaml"
+BRANCH = "cmapi/CRC/req-1"
+MAIN, HEAD = "1" * 40, "a" * 40
+PLAN = {REL: "kind: Namespace\n"}
+
+
+def req() -> BranchRequest:
+    return BranchRequest("CRC", "req-1", FOLDER, "hash", "create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
+                         PLAN, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))
+
+
+class Host:
+    """Gitea's REST paths the stand-in calls, over one existing request branch."""
+
+    def __init__(self, message: str, files: dict[str, str], open_pr: bool):
+        import base64
+
+        self.message, self.files, self.open_pr = message, files, open_pr
+        self.branch: str | None = HEAD
+        self.calls: list[tuple[str, str]] = []
+        self.b64 = lambda text: base64.b64encode(text.encode()).decode()
+
+    def __call__(self, request: httpx.Request) -> httpx.Response:
+        path, method = request.url.path.removeprefix("/api/v1/repos/o/r"), request.method
+        self.calls.append((method, path))
+        if method == "GET" and path == "/branches/main":
+            return httpx.Response(200, json={"commit": {"id": MAIN}})
+        if method == "GET" and path == f"/branches/{BRANCH}":
+            return httpx.Response(200, json={"commit": {"id": self.branch}}) if self.branch else httpx.Response(404, json={})
+        if method == "GET" and path == f"/git/commits/{HEAD}":
+            return httpx.Response(200, json={"sha": HEAD, "commit": {"message": self.message}, "parents": [{"sha": MAIN}]})
+        if method == "GET" and path == "/pulls":
+            return httpx.Response(200, json=[{"number": 1, "head": {"ref": BRANCH, "sha": HEAD}}] if self.open_pr else [])
+        if method == "GET" and path == f"/contents/{FOLDER.rstrip('/')}":
+            return httpx.Response(200, json=[{"type": "file", "name": p.rsplit("/", 1)[1], "path": p} for p in self.files])
+        if method == "GET" and path.startswith("/contents/"):
+            return httpx.Response(200, json={"content": self.b64(self.files.get(path[len("/contents/"):], "")), "sha": "f" * 40})
+        if method == "DELETE" and path == f"/branches/{BRANCH}":
+            self.branch = None
+            return httpx.Response(204)
+        if method == "POST" and path == "/branches":
+            self.branch, self.files = "c" * 40, {}
+            return httpx.Response(201, json={})
+        if method == "POST" and path == "/contents":
+            return httpx.Response(201, json={})
+        raise AssertionError(f"unexpected {method} {path}")
+
+
+def provider(host: Host) -> GiteaProvider:
+    g = GiteaProvider("https://g.test/api/v1", "o/r", "test-token-0123456789")
+    g._client.close()
+    g._client = httpx.Client(base_url="https://g.test/api/v1", transport=httpx.MockTransport(host))
+    return g
+
+
+def writes(host: Host) -> list[tuple[str, str]]:
+    return [(m, p) for m, p in host.calls if m != "GET"]
+
+
+@pytest.mark.parametrize("open_pr", [True, False])
+def test_a_head_that_is_not_this_requests_is_refused_and_left_alone(open_pr):
+    host = Host("a person's change\n", {REL: "kind: Namespace\nmetadata: {name: other}\n"}, open_pr)
+    with pytest.raises(BranchRefused):
+        provider(host).push_request_branch(req())
+    assert writes(host) == [] and host.branch == HEAD, "neither adopted through its PR nor deleted"
+
+
+def test_this_requests_current_commit_is_adopted_with_no_write():
+    host = Host("create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n", dict(PLAN), open_pr=False)
+    pushed = provider(host).push_request_branch(req())
+    assert (pushed.head, pushed.base, pushed.result) == (HEAD, MAIN, "adopted") and writes(host) == []
+
+
+def test_this_requests_stale_attempt_is_replaced():
+    host = Host("create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: an-older-plan\n", dict(PLAN), open_pr=False)
+    pushed = provider(host).push_request_branch(req())
+    assert pushed.result == "replaced"
+    assert writes(host)[:2] == [("DELETE", f"/branches/{BRANCH}"), ("POST", "/branches")]
+
+
+def test_the_branch_of_a_merged_request_is_still_deleted():
+    """Control: git_cleanup after every merge. Codex's patch raised here, so every merged request's cleanup failed five times,
+    and one still in merged after the fifth (argocd mode, waiting for the sync) became sync_failed (worker.py)."""
+    host = Host("", {}, open_pr=False)
+    assert provider(host).delete_branch(BRANCH, HEAD) is True
+    assert ("DELETE", f"/branches/{BRANCH}") in host.calls and host.branch is None
+
+
+def test_a_branch_that_moved_is_not_deleted():
+    host = Host("", {}, open_pr=False)
+    assert provider(host).delete_branch(BRANCH, "e" * 40) is False and writes(host) == []
+
+
+def test_the_message_trailers_parse_only_from_the_last_paragraph():
+    host = Host("create\n\nCmapi-Request-Id: req-1 is quoted in the body\n\nCmapi-Request-Id: other\n", {}, open_pr=False)
+    trailers, parents = provider(host)._commit(HEAD)
+    assert trailers == {"Cmapi-Request-Id": ["other"]} and parents == [MAIN]
+    assert json.dumps(trailers)
