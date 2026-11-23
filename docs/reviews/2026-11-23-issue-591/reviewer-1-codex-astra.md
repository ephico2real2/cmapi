# PR #599 · reviewer 1 · head 547fea3

**Head loaded two trust anchors from a bundle that the unmodified OpenSSL file loader refused.** The registry reported `connected`. This is the production finding I would fix before merging. The replay findings affect the portal’s test stand-in. The proposed documentation has the correct write-status inventory, but its source citation and two claims about headers need correction. [CA run](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/ca.log:10) · [Replay comparisons](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/matrix-head.log) · [Contract and redirect run](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/docs-after.log)

## #591 · Certificate loading

**1. A non-ASCII line inside a legacy certificate can be silently repaired.** In `core/registry.py:317–329`, one valid `CERTIFICATE` block is enough to pass. The validator treats a sibling `X509 CERTIFICATE` block as surrounding text. In `core/clients/trust.py:104–110`, the loader deletes every non-ASCII line, including one inside that sibling. With two distinct synthetic CAs and an extra mixed ASCII/Unicode body line in the second block, base raised `TypeError`, head returned `('connected', [], 2)`, and loading the same UTF-8 file raised `SSLError`. Direct callers of `ca_data_context` can also repair an ordinary block because that function has no registry guard. The ordinary registry import correctly refused that case. [Measured cases](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/ca.log:6)

The fix checks both labels at validation and load time, preserves the physical lines, and represents non-ASCII explanatory characters in ASCII without removing base64 content. The regression checks both the import status and the direct loader. Both label cases failed on head. Applying the complete patch to a fresh scratch copy and running the regression and existing CA suites gave **23 passed**. [Full fix and tests](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/591.patch) · [Patched run](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/patched-python.log)

**Compatibility — confirmed for base-loadable input.** Base passed the original string directly at `core/clients/trust.py:98`. Head returns ASCII input unchanged at lines 102–103. The new validator guard at `core/registry.py:303–308` excludes some values base *validated*. For example, bare base64 containing NBSP passed base validation and then raised `TypeError`. With the supplied Python, every previously successful string load required ASCII, for which the validation and loader inputs are equivalent. In 3,000 generated comparisons, **143** lost validation, **0** gained validation, **0** formerly successful imports lost or changed anchors, and **472** newly loaded. Head also validated **307** inputs its loader could not load. Validation is a base64/structure check. The harness used fresh SSL contexts, counted `cert_store_stats()["x509"]`, and compared DER sets on joint successes. Command: `"$PY" reviewer1/ca.py` after `source reviewer1/env`. [Harness](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/ca.py) · [Counts](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/ca.log:25)

**Line handling — confirmed.** `trust.py:32` and `registry.py:312` recognize CRLF, CR and LF. `"$PY" reviewer1/lines.py` reported `55987 line splits agree`, including vertical tab and U+2028. A mixed explanatory line before the block loaded one anchor. A mixed ordinary body line was refused. A CR-only PEM passed both validators but loaded zero anchors on this OpenSSL build. A legacy `Proc-Type:` header inside an ordinary block was refused by both validators. RFC 7468 itself does not permit encapsulated headers. [Line check](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/lines.py) · [Loader results](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/ca.log:14) · [RFC 7468 §2](https://www.rfc-editor.org/rfc/rfc7468.html#section-2)

## #595 and #597 · Replay

**Confirmed on the covered paths.** `node head/cmapi-portal-ui/tests/api/standin.test.mjs` gave **5 passed**. Create replays the current request without If-Match. Metadata PATCH, quota PATCH and expiry replay the current state after rejection. A quota retry survives an ETag change. Changing only expiry justification reuses the request, and changing days gives 409 with the holder’s ID. For ordinary `*` and SP/HTAB-padded `*`, head returns 428 on first write and replay. Empty If-Match gives 412 on first write and permits replay. See `standin.mjs:962–969, 1170–1184, 1238–1250, 1309–1318`. [Head matrix](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/matrix-head.log) · [PR tests](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/head/cmapi-portal-ui/tests/api/standin.test.mjs:32)

`"$PY" reviewer1/router.py` exercised the real route functions, `_replay`, fingerprint and precondition code, with persistence, planning and view construction substituted. All five conditional paths tested — PATCH, DELETE, extend, set and makePermanent — accepted a stale tag on replay, returned 428 for absent or wildcard, and accepted empty. A different fingerprint won over a missing header and returned 409. A dry key and another caller missed. The simulated submit-time 409 re-read the winner for equal input and refused changed input. The real transaction race needs PostgreSQL. See `plugins/namespaces/router.py:76–115, 268–279, 317–351, 358–374, 385–424`. [Route output](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/router.log)

| Finding and head location | Measured failure | Fix and regression |
|---|---|---|
| **2. Create keys omit the cluster and model defaults. Policy runs before replay.** `standin.mjs:1071–1097, 1104` | Same key/body on another cluster returned **202** for the first cluster. Adding explicit default `tier: "small"` returned **409**. Removing the cluster fixture made an identical retry **404**. The API includes the cluster and normalized model, then looks up the key before planning at `router.py:268–276`. | Bind the normalized input and target before the fixture checks. [Full fix and regression](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/standin.patch:339) |
| **3. PATCH replay depends on a current fixture row. Quota PATCH also hashes top-level nulls.** `standin.mjs:1222, 1232, 1292–1295, 1309` | Removing the quota row after submission returned **404**. Retrying with `justification: null` returned **409**. The API replays both, while retaining null *inside* metadata merge maps at `router.py:317–328`. | Dispatch replay from the path before looking up either fixture. Normalize top-level nulls. [Full fix and regression](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/standin.patch) |
| **4. Extend fingerprints an ignored input.** `standin.mjs:1170–1175, 1188–1191` | Submit `days: 7`, then add `until` alongside the same days. Head returned **409**. The real route selected days both times and replayed. Head also requires integer days during planning, whereas the API accepts an until-only extension. See `router.py:385–397` and `expiration/rules.py:148–165`. | Use the selected route input for the fingerprint and the plan. Keep justification separate. [Full fix and regression](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/standin.patch:161) · [API result](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/router.log:35) |
| **5. First-write tag parsing and wildcard problem details differ.** `standin.mjs:969, 1182–1183, 1249–1250, 1317–1318` | With current tag `abc`, a missing closing quote got **202** and a valid list containing `"abc"` got **412**. NBSP-wrapped star got **412** on first write and **202** on quota replay. The API returned **428** on both because `pipeline.py:127` uses Python `strip()`. Base gave **412** on that replay, so the erroneous 202 is newly observable. An empty first-write field reports changed Git even when no strong tag was supplied. Ordinary star gets the missing-header detail. | Use the API’s strong-tag grammar and distinct problem details. Preserve the presence-only replay check. [Full fix and three route tests](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/standin.patch:8) · [Base](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/matrix-base.log) · [Head](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/matrix-head.log) · [API](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/router.log:38) |
| **6. Key validation, lifetime, dry-run selection and conflict titles differ.** `standin.mjs:906, 966, 1087–1097, 1165–1172` | A 101-character key got **202**. An aged key returned the original ID. A held create with `dryRun=1` returned **202**. A changed-body conflict used title `idempotency-replay`. The API caps keys at 100, releases them after 24 hours, parses a boolean query, and renders the title `idempotency replay`. See `router.py:76–83`, `core/db/repo.py:49, 124–133`, `routers/__init__.py:22`, `core/errors.py:38–43`. | Share key lookup and expiration across writes, parse the dry-run flag, and render the API’s title. [Full fix and regressions](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/standin.patch:68) · [Measured outputs](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/matrix-head.log) |
| **7. DELETE has no stand-in replay path.** `standin.mjs:1288, 1357` | DELETE of the existing quota fixture returned route **404**. The API submits the delete and supports subsequent replay even after the namespace disappears, at `router.py:334–351`. This gap also exists in base. | The scratch implementation uses the recorded delete response and common replay path. Its test submits, rejects, removes the namespace and retries with stale and wildcard tags. [Full fix and regression](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/standin.patch:205) |

The comparisons above used `node reviewer1/matrix.mjs`, the corresponding base and fixed scripts, and the expanded handler tests. The expanded suite gave **6 passed, 9 failed on head** and **15 passed** after applying the patch. The DELETE implementation models the recorded fixture’s approval path. Production approval-policy parity beyond that fixture was not verified. [Before](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/quality.log:3) · [After](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/patched-node.log)

## #594 · HTTP contract and live-doc text

**Write inventory — confirmed.** `"$PY" reviewer1/docs.py reviewer1/LIVE-DOC-EDITS.md` enumerated all **15** POST/PATCH/DELETE operations in the committed contract and found zero PUTs. Create, PATCH and the three expiry submissions declare **202 ChangeRequest / 200 PlanView**. DELETE declares **202 ChangeRequest** only. Approve, reject, cancel, retry, revert and prune-confirm declare **200 ChangeRequest**. Pause and resume declare **200 SwitchView**. Probe declares **200 ClusterView**. Revert queues a worker to open a separate request (`routers/requests.py:232–255`). Probe returns current diagnostics and can change no cluster resource (`routers/me.py:86–97`). [Complete per-operation output](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/docs-after.log)

**8. Correct the citation, scope the header claims, and qualify dry run.** `LIVE-DOC-EDITS.md:20–23, 40, 54, 60, 68` cites `views.py:15–16`. Those lines read the plan and PR. **Lines 17–18** build the self and events links, and lines 24 and 34 return status and links. No successful **write** declares response headers. Three successful GETs declare ETag. The sole literal `Location` response-header name found in service source was `core/cors.py:31`, but a real in-process POST to the namespace route **with a trailing slash returned 307 and Location**. Scope the claim to successful write responses. Explicitly exclude DELETE from dry runs and describe the probe as diagnostics. The documentation check failed on the supplied proposal and passed on the corrected text, including substitution at the two actual export lines. [Full replacement text](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/594.patch) · [Test](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/docs.py) · [Redirect and substitution results](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/docs-after.log:19)

**RFC citation — confirmed.** Section 15.3.3 advises a 202 representation to describe current status and point to or embed a status monitor. It does not require a Location header. Section 10.2.2 describes status-dependent Location semantics, including 201 and 3xx. The service’s body identifies the request to poll. The CORS exposure entry matches `docs/15-keycloak-integration.md:212`. The documentation checker’s list at `scripts/doc-citations.py:35` covers docs 14–16. Live document contents, work ownership and future route response codes are outside the evidence in this export. [RFC 9110 §15.3.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.3) · [§10.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.2)

## Test quality and coordinator runs

**9. The new tests catch the primary regressions but allow specific broken behaviors.** Running `"$PY" reviewer1/mutate.py` on scratch copies gave these results. [Mutation output](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/mutations.log)

| Mutation | Result on the PR’s tests |
|---|---|
| Restore the old CA loader | All five explanatory-text cases and the legacy-label case failed |
| Restore the old body validator | All three Unicode body cases failed |
| Normalize ASCII CRLF or omit the legacy block | The ASCII spy or distinct legacy-CA test failed, respectively |
| Drop the second ordinary certificate, or allow NBSP in bare base64 | **All 10 CA tests passed** in each mutation. The fixture at `test_ca_data_non_ascii_591.py:50–56` repeats the same CA and expects one anchor |
| Return the original stored object | The expiry, metadata PATCH, quota PATCH and create current-view tests failed |
| Restore justification to the fingerprint, or omit the holder ID | The fifth Node test failed in each run |
| Accept wildcard replays, or compare the quota replay’s ETag again | Three conditional replay tests failed, or only the quota test failed, respectively |
| Restore the old first-write checks only, or corrupt replayed `links` only | **All five Node tests passed** in each mutation. `standin.test.mjs:33–42` checks selected fields and exercises wildcard on replay |

The added tests killed both surviving CA mutants. A focused fresh-write test failed on the old first-write check and passed on head. Full-body equality killed the wrong-links mutant on all four current-view paths. The create test now uses the PR object shape from `core/models.py:140–144, 176` in place of the integer at `standin.test.mjs:95`. The full fixes include these tests. [CA tests](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/591.patch:75) · [Node tests](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/standin.patch:339) · [Focused fresh-write test](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/mutants/cmapi-portal-ui/tests/api/fresh.test.mjs) · [Mutation follow-up](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/quality.log)

**Other diff — confirmed.** `pr599.diff` contains six file changes. The package change at `cmapi-portal-ui/package.json:15` adds the Node test to the test chain. Its imports resolved, and `node head/scripts/build-portal.mjs --check` reported the portal HTML up to date. The standalone Node suite ran. The full npm/browser build was not run; the export has no `cmapi-portal-ui/node_modules`. The unmodified CA suites gave **19 passed**. [CA test output](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/ca-tests.log)

**Coordinator reruns.** PostgreSQL at `127.0.0.1:55432` returned `Operation not permitted`. **32 database-backed cases** stopped in fixture setup. The logs list every parameterized ID. With the supplied Python and `PYTHONPATH=head/cmapi/src`, rerun:

- `pytest head/cmapi/tests/service/test_{if_match_forms_571,if_match_before_replay_495}.py` — 24 passed locally, 26 setup errors. [Exact IDs](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/db-fast.log:218)
- `pytest head/cmapi/tests/service/test_expirations.py::test_one_key_on_set_and_on_extend_until_is_two_requests_not_a_replay` — one setup error. [Output](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/db-expiry.log)
- `pytest head/cmapi/tests/service/test_{flow,review_a_concurrency}.py -k 'idempotency_key_is or same_key'` — five setup errors covering retention, cluster binding, key length and concurrent submissions. [Exact IDs](/Users/olasumbo/gitRepos/workbench/cmapi/review-599/reviewer1/db-keys.log)

All fixes are review artifacts inside the export. I applied the three patches to a fresh scratch copy and reran the checks there. I used direct source inspection because the export has no initialized TokenSave graph. No Git commands or pushes were used.

## Full patch · 591

```diff
--- a/cmapi/src/cmapi/core/clients/trust.py
+++ b/cmapi/src/cmapi/core/clients/trust.py
@@ -94,20 +94,31 @@
     return ctx
 
 
-def _ascii_lines(ca_data: str) -> str:
-    """caData as Python's loader takes it: "an ASCII string of one or more PEM-encoded certificates" (the ssl docs), since a
-    bytes value is read as DER. A line that is not ASCII, such as an issuer's name above a certificate (RFC 7468 section 5.2's
-    explanatory text), raised TypeError (#591); OpenSSL and client-go skip such text, so that line is left out. The registry
-    has refused a value with one inside a CERTIFICATE block, so no certificate line is lost. An ASCII value is unchanged."""
+def ascii_certificate_bodies(ca_data: str) -> bool:
+    """Check the bodies of both certificate labels accepted by the cadata loader."""
     if ca_data.isascii():
-        return ca_data
-    return "".join(line for line in _LINE.findall(ca_data) if line.isascii())
+        return True
+    end = None
+    for match in _LINE.finditer(ca_data):
+        line = match.group().rstrip("\r\n").rstrip(" \t")
+        if line in ("-----BEGIN CERTIFICATE-----", "-----BEGIN X509 CERTIFICATE-----"):
+            end = line.replace("BEGIN", "END", 1)
+        elif line == end:
+            end = None
+        elif end and not line.isascii():
+            return False
+    return True
 
 
 def ca_data_context(ca_data: str, server_name: str | None = None) -> ssl.SSLContext:
     """The caData of an import Secret as the only anchors, in memory. ssl.SSLError when it holds no certificate."""
     ctx = _client_context(server_name)
-    ctx.load_verify_locations(cadata=_ascii_lines(ca_data))
+    if not ca_data.isascii():
+        if not ascii_certificate_bodies(ca_data):
+            raise ssl.SSLError("non-ASCII certificate body")
+        # Preserve boundaries and physical line endings. A replacement is never base64.
+        ca_data = ca_data.encode("ascii", errors="replace").decode("ascii")
+    ctx.load_verify_locations(cadata=ca_data)
     return ctx
 
 
--- a/cmapi/src/cmapi/core/registry.py
+++ b/cmapi/src/cmapi/core/registry.py
@@ -44,7 +44,7 @@
 from cmapi.core.clients.nodes import NodeCache
 from cmapi.core.clients.policyreports import ReportCache
 from cmapi.core.clients.redact import order_forms, redact, secret_forms
-from cmapi.core.clients.trust import Trust, file_context, require_https, trusted_context, valid_server_name
+from cmapi.core.clients.trust import Trust, ascii_certificate_bodies, file_context, require_https, trusted_context, valid_server_name
 from cmapi.core.cluster_tokens import READER_IDENTITY, ReaderGrant, TokenPolicy
 from cmapi.core.config import ConfigError
 from cmapi.core.errors import Problem
@@ -297,7 +297,7 @@
     or HTAB (RFC 7468 sections 2 and 3, whose lines end in CRLF, CR or LF). Each BEGIN line needs an END line before the
     next BEGIN, and each END line an open BEGIN (#585): OpenSSL refuses a block that is not closed. Other text before,
     between and after the blocks is ignored, as RFC 7468 and OpenSSL allow, even a sentence that quotes a boundary, and text
-    that is not ASCII, which the client leaves out of the loader (#591). A value with no boundary line is read as bare base64,
+    that is not ASCII, which the client represents in ASCII for the loader (#591). A value with no boundary line is read as bare base64,
     as before; the client finds no certificate in it and says so (#419).
     One pass over the lines, in linear time: the regex this replaces rescanned the rest of the value from every BEGIN."""
     def decodes(lines: list[str]) -> bool:
@@ -308,6 +308,9 @@
             return bool(base64.b64decode("".join(text.split()), validate=True))
         except (binascii.Error, ValueError):
             return False
+
+    if not ascii_certificate_bodies(ca_data):
+        return False
 
     lines = re.split(r"\r\n|\r|\n", ca_data)
     body: list[str] | None = None          # the lines of the open block; None outside a block
--- /dev/null
+++ b/cmapi/tests/service/test_review591.py
@@ -0,0 +1,19 @@
+import ssl
+import pytest
+from test_ca_data_non_ascii_591 import CA, _check_import, _second_ca
+from cmapi.core.clients.trust import ca_data_context
+from cmapi.core.registry import _valid_ca_data
+
+@pytest.mark.parametrize("label", ["CERTIFICATE", "X509 CERTIFICATE"])
+def test_internal_comment_refused(label):
+    second = _second_ca().replace(" CERTIFICATE-----", f" {label}-----")
+    bundle = CA + second.replace("\n", "\nIssuer: Zürich\n", 1)
+    assert _check_import(bundle) == ("invalid-secret", ["invalid caData"], None)
+    with pytest.raises(ssl.SSLError):
+        ca_data_context(bundle)
+
+def test_two_distinct_standard_anchors():
+    assert _check_import(CA + "Zürich\n" + _second_ca()) == ("connected", [], 2)
+
+def test_bare_base64():
+    assert not _valid_ca_data("T\xa0Q==")
```

## Full patch · standin

```diff
--- a/cmapi-portal-ui/tests/api/standin.mjs
+++ b/cmapi-portal-ui/tests/api/standin.mjs
@@ -595,6 +595,18 @@
 // The body's fingerprint, with the keys of each object in order, as the API compares two bodies of one key.
 const sorted = (v) => (Array.isArray(v) ? v.map(sorted) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v);
 const fingerprint = (value) => JSON.stringify(sorted(value));
+
+function strongTags(value) {
+  if (!value.startsWith("W/") && value !== "*" && /^[\x21\x23-\x2b\x2d-\x7e\x80-\xff]+$/.test(value)) return [value];
+  const element = /[ \t]*(?:(W\/)?"([\x21\x23-\x7e\x80-\xff]*)"[ \t]*)?(?:,|$)/y;
+  const tags = [];
+  while (element.lastIndex < value.length) {
+    const match = element.exec(value);
+    if (!match) return [];
+    if (!match[1] && match[2] !== undefined) tags.push(match[2]);
+  }
+  return tags;
+}
 
 /**
  * The create's metadata as cmapi/src/cmapi/core/metadata.py builds it (#479): steps 1 and 2 fill each key that cmapi sets
@@ -903,12 +915,12 @@
     res.writeHead(body.status, { ...cors, "content-type": "application/problem+json" });
     res.end(JSON.stringify(body));
   };
-  const refuse = (status, code, detail) => ({ type: `https://cmapi.ephico2real.com/problems/${code}`, title: code, status, code, detail });
+  const refuse = (status, code, detail) => ({ type: `https://cmapi.ephico2real.com/problems/${code}`, title: code.replaceAll("-", " "), status, code, detail });
   const handle = async (req, res) => {
     const url = new URL(req.url, "http://api");
     // The API allows the portal's origin and no other, and takes no cookie. The headers are cmapi/src/cmapi/core/cors.py's.
     const cors = { "access-control-allow-origin": portalOrigin(), "access-control-allow-headers": "authorization, content-type, idempotency-key, if-match",
-      "access-control-allow-methods": "GET, POST, PATCH", "access-control-expose-headers": "etag", vary: "origin" };
+      "access-control-allow-methods": "GET, POST, PATCH, DELETE", "access-control-expose-headers": "etag", vary: "origin" };
     if (req.method === "OPTIONS") {
       res.writeHead(204, cors);
       return res.end();
@@ -959,14 +971,54 @@
       state.items = state.items.map((x) => (x === r ? next : x));
       return next;
     };
-    // plugins/namespaces/router.py _replay: a replay answers request_view of the stored row, the request as it is now. The key
-    // map holds the first object, and a decision replaces it in state.items, so the replay looks it up there (#595).
-    const replayed = (held) => ok(find(held.request.requestId), 202);
-    // Problem.conflict("idempotency-replay", ..., requestId=row.request_id): a held key with another body names its request.
-    const replayRefused = (held) => ({ ...refuse(409, "idempotency-replay", "Idempotency-Key was used for a different request"), requestId: held.request.requestId });
-    // core/pipeline.py require_if_match: no If-Match, or `*` with only SP or HTAB around it, is 428 precondition-required, on a
-    // first write and on a replay alike (#495, #571). An empty value lists no tag, so it is a 412 on a first write.
-    const preconditionMissing = (ifMatch) => ifMatch == null || /^[ \t]*\*[ \t]*$/.test(ifMatch);
+    const inputs = Object.fromEntries(Object.entries(body ?? {}).filter(([, v]) => v !== null));
+    const keySlot = JSON.stringify([user.sub, call.key]);
+    const dryParam = url.searchParams.getAll("dryRun").at(-1)?.toLowerCase();
+    const dry = req.method !== "DELETE" && ["true", "1", "yes", "y", "t", "on"].includes(dryParam);
+    const remember = (print, request) => state.keys.set(keySlot, { fingerprint: print, request });
+    const precondition = (etag, write = "change") => {
+      const value = call.ifMatch;
+      if (value == null || /^[\x09-\x0d\x1c-\x20\x85\xa0]*\*[\x09-\x0d\x1c-\x20\x85\xa0]*$/.test(value)) {
+        const detail = value == null ? `If-Match is required on a ${write}` : `If-Match must name the namespace's etag, not *, on a ${write}`;
+        return refuse(428, "precondition-required", detail + "; GET the namespace for its etag");
+      }
+      if (etag === undefined) return null;
+      const tags = strongTags(value);
+      if (tags.includes(etag)) return null;
+      const detail = tags.length ? "The namespace changed in Git since you read it" :
+        "If-Match lists no strong entity tag: send the namespace's etag from GET in double quotes";
+      return { ...refuse(412, "precondition-failed", detail), etag };
+    };
+    // Return true once the response has been written.
+    const replay = (print, write) => {
+      if (dry) return false;
+      if (req.method !== "DELETE" && dryParam !== undefined && !["false", "0", "no", "n", "f", "off"].includes(dryParam)) {
+        const message = "Input should be a valid boolean, unable to interpret input";
+        problem(res, { ...refuse(422, "validation-failed", "The request is not valid: query.dryRun: " + message),
+          errors: [{ field: "query.dryRun", message, code: "bool_parsing" }] }, cors);
+        return true;
+      }
+      let error;
+      if (!call.key || [...call.key].length > 100) {
+        const detail = call.key ? "Idempotency-Key is at most 100 characters" : "Idempotency-Key header is required on writes";
+        error = refuse(400, "idempotency-key-required", detail);
+      } else {
+        const held = state.keys.get(keySlot);
+        if (!held) return false;
+        if (Date.parse(held.request.createdAt) < Date.now() - 86400000) {
+          state.keys.delete(keySlot);
+          return false;
+        }
+        if (held.fingerprint !== print) {
+          error = { ...refuse(409, "idempotency-replay", "Idempotency-Key was used for a different request"), requestId: held.request.requestId };
+        } else if (write) {
+          error = precondition(undefined, write);
+        }
+        if (!error) ok(find(held.request.requestId), 202);
+      }
+      if (error) problem(res, error, cors);
+      return true;
+    };
 
     if (url.pathname === "/api/v1/me") {
       const me = SAMPLES.operations.core_me.response.body;
@@ -1068,6 +1120,8 @@
       const denied = lacks("namespaces:create");
       if (denied) return problem(res, denied, cors);
       const clusterId = create[1];
+      const print = fingerprint({ tier: "small", labels: {}, annotations: {}, expiresAt: null, ...inputs, clusterId });
+      if (replay(print)) return;
       if (!state.clusters.some((c) => c.clusterId === clusterId)) return problem(res, refuse(404, "cluster-not-found", `Unknown cluster ${clusterId}`), cors);
       if (!body || typeof body.namespace !== "string" || !NAME.test(body.namespace)) return problem(res, refuse(422, "invalid-namespace-name", `${JSON.stringify(body?.namespace)} is not a DNS-1123 name`), cors);
       if (RESERVED.test(body.namespace)) return problem(res, refuse(422, "reserved-namespace", `${body.namespace} is reserved`), cors);
@@ -1084,24 +1138,20 @@
       if (late) return problem(res, refuse(...late), cors);
       const protection = protectionRefusal(body.labels, env);
       if (protection) return problem(res, protection, cors);
-      if (url.searchParams.get("dryRun") === "true") {
+      if (dry) {
         const changes = Object.fromEntries(Object.keys(state.plan.changes).map((path) => [path.replace(/namespaces\/[^/]+\//, `namespaces/${body.namespace}/`).replace(/^clusters\/[^/]+\//, `clusters/${clusterId}/`), "added"]));
         const files = Object.fromEntries(Object.entries(state.plan.files).map(([path, text]) => [path.replace(/namespaces\/[^/]+\//, `namespaces/${body.namespace}/`).replace(/^clusters\/[^/]+\//, `clusters/${clusterId}/`), text]));
         const nsFile = Object.keys(files).find((p) => p.endsWith("/namespace.yaml"));
         if (nsFile) files[nsFile] = namespaceYaml(clusterId, body.namespace, env, body.tier ?? "small", user, made.filled, body.expiresAt);
         return ok({ ...state.plan, changes, files, metadata: made.metadata, capacity: { ...state.plan.capacity, clusterId } });
       }
-      const key = call.key;
-      if (!key) return problem(res, SAMPLES.problems["idempotency-key-required"].response.body, cors);
-      const held = state.keys.get(`${user.sub} ${key}`);
-      if (held) return held.fingerprint === fingerprint(body) ? replayed(held) : problem(res, replayRefused(held), cors);
       const now = new Date().toISOString();
       const requestId = `req-${now.slice(0, 10).replaceAll("-", "")}-9${String(++state.created).padStart(3, "0")}`;
       const request = requestWith(created, { requestId, namespace: body.namespace, status: "approved", pr: null, mergeSha: null,
         events: [{ at: now, by: user.username, event: "plan_auto_approved", note: created.approval.auto, status: "approved" }] });
       request.clusterId = clusterId;
       state.items = [request, ...state.items];
-      state.keys.set(`${user.sub} ${key}`, { fingerprint: fingerprint(body), request });
+      remember(print, request);
       return ok(request, 202);
     }
 
@@ -1162,33 +1212,34 @@
       const [, clusterId, ns, route] = expiry;
       const denied = lacks("namespaces:write");
       if (denied) return problem(res, denied, cors);
-      const dry = url.searchParams.get("dryRun") === "true";
-      if (!dry && !call.key) return problem(res, SAMPLES.problems["idempotency-key-required"].response.body, cors);
-      // The API's replay comes first (_expiry_write), before the namespace is looked up: the same key and caller with the same
-      // route and body is the stored request again, if its If-Match is there and not `*`. The API's fingerprint holds the
-      // route's inputs and not the justification, which it passes to the submission apart (#597).
-      const { justification: _, ...asked } = body ?? {};
-      const print = fingerprint({ ...asked, route, clusterId, namespace: ns });
-      const held = dry ? null : state.keys.get(`${user.sub} ${call.key}`);
-      if (held) {
-        if (held.fingerprint !== print) return problem(res, replayRefused(held), cors);
-        if (preconditionMissing(call.ifMatch)) return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
-        return replayed(held);
-      }
+      const days = Number(body?.days);
+      let until = body?.until;
+      if (route === "extend" && !days) {
+        if (!until) return problem(res, refuse(422, "validation-failed", "Send days or until"), cors);
+        if (/^\d{8}$/.test(until)) until = until.replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3");
+        if (!/^\d{4}-\d{2}-\d{2}$/.test(until) || !Number.isFinite(Date.parse(until)) || isoPlus(until, 0) !== until)
+          return problem(res, refuse(422, "validation-failed", "until is a date, YYYY-MM-DD"), cors);
+      }
+      const expiryInput = route === "set" ? { expiresAt: until, route: "expiration:set" } :
+        route === "makePermanent" ? { makePermanent: true } : days ? { extendDays: days } : { extendUntil: until };
+      const print = fingerprint({ ...expiryInput, clusterId, namespace: ns });
+      if (replay(print, "change")) return;
       const row = state.expirations.find((r) => r.clusterId === clusterId && r.name === ns);
       if (!row) return problem(res, refuse(404, "object-not-found", `${ns} is not managed on ${clusterId}`), cors);
       const etag = state.etags.get(`${clusterId}/${ns}`) ?? createHash("sha256").update(`${clusterId}/${ns}`).digest("hex").slice(0, 16);
       state.etags.set(`${clusterId}/${ns}`, etag);
-      if (preconditionMissing(call.ifMatch)) return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
-      if (call.ifMatch.replace(/^"|"$/g, "") !== etag) return problem(res, { ...SAMPLES.problems["precondition-failed"].response.body, etag }, cors);
+      const error = precondition(etag);
+      if (error) return problem(res, error, cors);
       // cmapi/src/cmapi/plugins/expiration/rules.py: plan_extend, plan_set and plan_make_permanent.
       const max = EXP_RULES.dev.maxExtensionDays;
       let date = null;
       if (route === "extend") {
         if (!row.expiresAt) return problem(res, refuse(422, "expiration-not-set", "The namespace is permanent; use :set"), cors);
-        if (!Number.isInteger(body?.days) || body.days < 1) return problem(res, refuse(422, "validation-failed", "Send days or until"), cors);
-        if (body.days > max) return problem(res, refuse(422, "expiration-limit", `One extension adds at most ${max} days`), cors);
-        date = isoPlus(row.expiresAt > state.today ? row.expiresAt : state.today, body.days);
+        const base = row.expiresAt > state.today ? row.expiresAt : state.today;
+        const step = days || Math.round((Date.parse(until) - Date.parse(base)) / 864e5);
+        if (!Number.isInteger(step) || step <= 0) return problem(res, refuse(422, "expiration-in-past", "The new date must be later than the current one"), cors);
+        if (step > max) return problem(res, refuse(422, "expiration-limit", `One extension adds at most ${max} days`), cors);
+        date = isoPlus(base, step);
       } else if (route === "set") {
         if (row.expiresAt) return problem(res, SAMPLES.problems["expiration-already-set"].response.body, cors);
         if (typeof body?.until !== "string" || body.until <= state.today) return problem(res, refuse(422, "expiration-in-past", "The expiry must be after today"), cors);
@@ -1215,11 +1266,45 @@
       Object.assign(request, { clusterId, approval, reason: `expiration:${route}`, justification: body?.justification ?? null });
       state.items = [request, ...state.items];
       state.expirations = state.expirations.map((r) => (r === row ? { ...r, openRequest: requestId } : r));
-      state.keys.set(`${user.sub} ${call.key}`, { fingerprint: print, request });
+      remember(print, request);
       return ok(request, 202);
     }
     const nsPath = /^\/api\/v1\/clusters\/([^/]+)\/namespaces\/([^/:]+)$/.exec(url.pathname);
+    const print = nsPath && fingerprint({ ...(req.method === "DELETE" ? { action: "delete" } : inputs), clusterId: nsPath[1], namespace: nsPath[2] });
+    if (nsPath && ["PATCH", "DELETE"].includes(req.method)) {
+      const denied = lacks("namespaces:write");
+      if (denied) return problem(res, denied, cors);
+      if (replay(print, req.method === "DELETE" ? "delete" : "change")) return;
+    }
     const record = nsPath && state.namespaces.find((r) => r.clusterId === nsPath[1] && r.name === nsPath[2]);
+    if (nsPath && req.method === "DELETE") {
+      const [, clusterId, ns] = nsPath;
+      const row = record ?? [...state.quotas, ...state.expirations].find(r => r.clusterId === clusterId && r.name === ns);
+      if (!row) return problem(res, refuse(404, "object-not-found", `${ns} is not managed on ${clusterId}`), cors);
+      const scope = ROLE_ENVIRONMENTS[user.role];
+      if (scope && !scope.includes(row.env)) return problem(res, refuse(403, "environment-forbidden", `Your roles do not cover ${row.env}`), cors);
+      const target = `${clusterId}/${ns}`;
+      const etag = record ? recordEtag(record) : state.etags.get(target) ?? createHash("sha256").update(target).digest("hex").slice(0,16);
+      const error = precondition(etag, "delete");
+      if (error) return problem(res, error, cors);
+      if (state.protection.get(target)?.length || PROTECTION_LABELS.some(k => record?.git.labels[k] === "true"))
+        return problem(res, refuse(422, "namespace-protected", "Protected namespaces cannot be deleted"), cors);
+      if (row.openRequest) {
+        const id = row.openRequest.requestId ?? row.openRequest;
+        return problem(res, { ...refuse(409, "change-pending", `${id} holds ${ns}`), requestId: id }, cors);
+      }
+      const now = new Date().toISOString();
+      const requestId = `req-${now.slice(0,10).replaceAll("-", "")}-8${String(++state.created).padStart(3,"0")}`;
+      const status = "pending_approval";
+      const request = requestWith(SAMPLES.operations.namespaces_delete_namespace.response.body, { requestId, namespace: ns, status, pr: null, mergeSha: null,
+        events: [{ at: now, by: user.username, event: "plan_needs_approval", note: "", status }] });
+      Object.assign(request, { clusterId, env: row.env });
+      state.items = [request, ...state.items];
+      if (record) record.openRequest = { requestId, status };
+      for (const list of ["quotas", "expirations"]) state[list] = state[list].map(r => r.clusterId === clusterId && r.name === ns ? { ...r, openRequest: requestId } : r);
+      remember(print, request);
+      return ok(request, 202);
+    }
     if (record && req.method === "GET") {
       // router.py get_namespace: the live namespace, its Git and sync, and the etag, also as the ETag header.
       const denied = lacks("objects:read");
@@ -1231,23 +1316,11 @@
     }
     if (record && req.method === "PATCH") {
       // router.py update_namespace, then pipeline.py _plan_namespace, in their order.
-      const denied = lacks("namespaces:write");
-      if (denied) return problem(res, denied, cors);
-      const dry = url.searchParams.get("dryRun") === "true";
-      if (!dry && !call.key) return problem(res, SAMPLES.problems["idempotency-key-required"].response.body, cors);
-      const raw = Object.fromEntries(Object.entries(body ?? {}).filter(([, value]) => value !== null));
-      const print = fingerprint({ ...raw, clusterId: record.clusterId, namespace: record.name });
-      const held = dry ? null : state.keys.get(`${user.sub} ${call.key}`);
-      if (held) {
-        if (held.fingerprint !== print) return problem(res, replayRefused(held), cors);
-        if (preconditionMissing(call.ifMatch)) return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
-        return replayed(held);
-      }
       const scope = ROLE_ENVIRONMENTS[user.role];
       if (scope && !scope.includes(record.env)) return problem(res, refuse(403, "environment-forbidden", `Your roles do not cover ${record.env}`), cors);
       const etag = recordEtag(record);
-      if (preconditionMissing(call.ifMatch)) return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
-      if (call.ifMatch.replace(/^"|"$/g, "") !== etag) return problem(res, { ...SAMPLES.problems["precondition-failed"].response.body, etag }, cors);
+      const error = precondition(etag);
+      if (error) return problem(res, error, cors);
       const operatorKeys = MAPS.flatMap(([, map]) => Object.keys(body?.[map] ?? {})
         .filter((key) => state.metadataKeys[map].properties[key]?.["x-cmapi-operator-only"]));
       const environment = state.clusters.find((c) => c.clusterId === record.clusterId)?.environment;
@@ -1282,7 +1355,7 @@
       state.items = [request, ...state.items];
       record.openRequest = { requestId, status: request.status };
       record.pending = after;
-      state.keys.set(`${user.sub} ${call.key}`, { fingerprint: print, request });
+      remember(print, request);
       return ok(request, 202);
     }
     if (nsPath && (req.method === "GET" || req.method === "PATCH")) {
@@ -1302,20 +1375,9 @@
           expiresAt: row.expiresAt ?? null, protected: protectedBy.length > 0, protectedBy,
           labels: { ...view.labels, "cmapi.net/cluster-id": clusterId, "cmapi.net/env": row.env, "cmapi.net/team": row.team, "cmapi.net/tier": row.tier } }));
       }
-      // router.py update_namespace: the Idempotency-Key and its replay come before the plan, so a retry with its first ETag is
-      // the stored request even after Git moved; it still needs If-Match, and `*` is 428 (#495, #595).
-      const dry = url.searchParams.get("dryRun") === "true";
-      if (!dry && !call.key) return problem(res, SAMPLES.problems["idempotency-key-required"].response.body, cors);
-      const print = fingerprint({ ...body, clusterId, namespace: ns });
-      const held = dry ? null : state.keys.get(`${user.sub} ${call.key}`);
-      if (held) {
-        if (held.fingerprint !== print) return problem(res, replayRefused(held), cors);
-        if (preconditionMissing(call.ifMatch)) return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
-        return replayed(held);
-      }
       // cmapi/src/cmapi/core/pipeline.py: If-Match is required, and it must be the folder's etag now (quotes are taken off).
-      if (preconditionMissing(call.ifMatch)) return problem(res, SAMPLES.problems["precondition-required"].response.body, cors);
-      if (call.ifMatch.replace(/^"|"$/g, "") !== etag) return problem(res, { ...SAMPLES.problems["precondition-failed"].response.body, etag }, cors);
+      const error = precondition(etag);
+      if (error) return problem(res, error, cors);
       const tiers = state.tiers.environments[row.env]?.tiers ?? [];
       const named = tiers.find((t) => t.name === body?.tier);
       if (!body || (body.tier !== undefined && !named)) return problem(res, refuse(422, "validation-failed", `${JSON.stringify(body?.tier)} is not a tier of ${row.env}`), cors);
@@ -1347,7 +1409,7 @@
       Object.assign(request, { clusterId, approval, justification: body.justification ?? null });
       state.items = [request, ...state.items];
       state.quotas = state.quotas.map((r) => (r === row ? { ...r, openRequest: requestId } : r));
-      state.keys.set(`${user.sub} ${call.key}`, { fingerprint: print, request });
+      remember(print, request);
       return ok(request, 202);
     }
     if (url.pathname === "/api/v1/admin/kpi") {
--- a/cmapi-portal-ui/tests/api/standin.test.mjs
+++ b/cmapi-portal-ui/tests/api/standin.test.mjs
@@ -34,7 +34,7 @@
   const again = await send(tag);
   assert.equal(again.status, 202);
   assert.equal(again.body.status, decided.status, "the request in its current state, not the first answer");
-  assert.deepEqual(again.body.events, decided.events);
+  assert.deepEqual(again.body, decided);
   for (const value of [undefined, "*", " \t*\t "]) {
     const answer = await send(value);
     assert.equal(answer.status, 428, `If-Match ${JSON.stringify(value)} on a replay`);
@@ -92,11 +92,11 @@
   const first = await send();
   assert.equal(first.status, 202, JSON.stringify(first.body));
   // The API moves an approved request on (the bot opens its pull request); the stand-in has no bot, so the test moves it.
-  const moved = { ...first.body, status: "pr_open", pr: 42 };
+  const moved = { ...first.body, status: "pr_open", pr: { number: 42, url: "https://git.test/pulls/42", branch: "cmapi/orders-dev", head: "abcdef12" } };
   api.state.items = api.state.items.map((r) => (r.requestId === moved.requestId ? moved : r));
   const again = await send();
   assert.equal(again.status, 202);
-  assert.deepEqual([again.body.status, again.body.pr], ["pr_open", 42]);
+  assert.deepEqual(again.body, moved);
 });
 
 test("an expiry replay with another justification is the same request, as the API's fingerprint leaves it out", async () => {
@@ -116,3 +116,101 @@
   assert.equal(other.body.code, "idempotency-replay");
   assert.equal(other.body.requestId, first.body.requestId, "the 409 names the request that holds the key, as _replay's does");
 });
+
+const path = "/api/v1/clusters/CRC/namespaces";
+const q = path + "/payments-dev";
+const createBody = {namespace:"orders-dev",labels:{"cmapi.net/team":"orders"},annotations:{"cmapi.net/team-dl":"orders-team@ephico2real.com"}};
+const submit = (api, url=path, body=createBody, key="k") => api.call("POST",url,"requester",{body,key});
+function patch(api,body,ifMatch,key="k") { return api.call("PATCH",q,"requester",{body,ifMatch,key}); }
+async function tag(api) {return (await api.call("GET",q,"requester")).body.etag;}
+test("create normalizes defaults, scopes cluster and replays before planning",async()=>{
+  const a=standIn(), first=await submit(a);
+  assert.equal(first.status,202);
+  a.state.clusters=[];
+  assert.deepEqual((await submit(a,path,{...createBody,tier:"small",justification:null})).body,first.body);
+  const conflict=await submit(a,path.replace("CRC","ALT"));
+  assert.deepEqual([conflict.status,conflict.body.requestId,conflict.body.title],[409,first.body.requestId,"idempotency replay"]);
+});
+test("key length and retention",async()=>{
+  const a=standIn();
+  assert.equal((await submit(a,path,createBody,"k".repeat(101))).status,400);
+  const first=await submit(a);
+  a.state.keys.values().next().value.request.createdAt="2000-01-01T00:00:00Z";
+  assert.notEqual((await submit(a)).body.requestId,first.body.requestId);
+});
+test("PATCH replay before lookup and with normalized nulls",async()=>{
+  const a=standIn(), etag=await tag(a), first=await patch(a,{tier:"large"},etag);
+  assert.equal(first.status,202);
+  a.state.quotas=[];
+  assert.deepEqual((await patch(a,{tier:"large",justification:null},"")).body,first.body);
+  const conflict=await patch(a,{tier:"small"},undefined);
+  assert.deepEqual([conflict.status,conflict.body.requestId],[409,first.body.requestId]);
+});
+for (const target of ["quota","metadata","expiry"]) test("first-write and replay preconditions "+target,async()=>{
+  const a=standIn();
+  const rec=namespaceRecord({name:"abc-ledger-dev",prefix:"abc",team:"ledger",extraLabels:{"cmapi.net/protected":"true"}});
+  a.state.namespaces=[rec];
+  a.state.expirations=[{clusterId:"CRC",name:"notes-dev",env:"dev",expiresAt:"2027-01-01"}];
+  const url=target==="quota"?q:target==="metadata"?path+"/abc-ledger-dev":path+"/notes-dev/expiration:makePermanent";
+  a.state.etags.set("CRC/notes-dev","abc");
+  const etag=target==="expiry"?"abc":(await a.call("GET",url,"operator")).body.etag;
+  const send=v=>a.call(target==="expiry"?"POST":"PATCH",url,"operator",{body:target==="quota"?{tier:"large"}:target==="metadata"?{labels:{"cmapi.net/protected":null}}:{},ifMatch:v,key:"k"});
+  for (const [value,status] of [["*",428],[" \t*\t ",428],["",412],['"'+etag,412],["\xa0*\xa0",428]]) {
+    const r=await send(value);
+    assert.equal(r.status,status,JSON.stringify(value));
+    if (value==="") assert.match(r.body.detail,/lists no strong entity tag/);
+  }
+  assert.equal((await send('W/"a,b", "'+etag+'"')).status,202);
+  assert.equal((await send("")).status,202);
+  assert.equal((await send("\xa0*\xa0")).status,428);
+});
+test("expiry fingerprints the chosen input and replays after removal",async()=>{
+  const a=standIn();
+  a.state.expirations=[{clusterId:"CRC",name:"notes-dev",env:"dev",expiresAt:"2027-01-01"}];
+  a.state.etags.set("CRC/notes-dev","abc");
+  const send=body=>a.call("POST",path+"/notes-dev/expiration:extend","requester",{body,ifMatch:'"abc"',key:"k"});
+  const first=await send({days:7});
+  assert.equal(first.status,202);
+  a.state.expirations=[];
+  assert.deepEqual((await send({days:7,until:"2027-02-01",justification:"edit"})).body,first.body);
+  assert.equal((await send({days:8})).status,409);
+});
+test("delete replay outlives the namespace",async()=>{
+  const a=standIn(),etag=await tag(a);
+  const send=v=>a.call("DELETE",q,"requester",{ifMatch:v,key:"del"});
+  const first=await send(etag);
+  assert.equal(first.status,202);
+  const final=await reject(a,first.body.requestId);
+  a.state.quotas=[];
+  assert.deepEqual((await send('"stale"')).body,final);
+  assert.equal((await send("*")).status,428);
+});
+test("all expiry routes replay the owner before lookup and refuse another route", async()=>{
+  for (const [route,body,expiresAt] of [["set",{until:"2027-01-08"},null],["extend",{days:2},"2027-01-01"],["makePermanent",{},"2027-01-01"]]) {
+    const a=standIn(); a.state.today="2027-01-01";
+    a.state.expirations=[{clusterId:"CRC",name:"notes-dev",env:"dev",expiresAt}];
+    a.state.etags.set("CRC/notes-dev","abc");
+    const send=(route,body,user="requester",ifMatch="abc",query="")=>a.call("POST",path+"/notes-dev/expiration:"+route+query,user,{body,key:"k",ifMatch});
+    const first=await send(route,body);
+    assert.equal(first.status,202);
+    a.state.expirations=[];
+    assert.deepEqual((await send(route,{...body,justification:"edit"})).body,first.body);
+    assert.equal((await send(route,body,"operator")).status,404);
+    assert.equal((await send(route,body,"requester","abc","?dryRun=true")).status,404);
+    const other=await send(route==="extend"?"makePermanent":"extend",route==="extend"?{}:{days:2},"requester","*");
+    assert.deepEqual([other.status,other.body.requestId],[409,first.body.requestId]);
+  }
+});
+
+test("a true dryRun bypasses the held key and writes nothing", async () => {
+  const api = standIn();
+  const first = await submit(api);
+  assert.equal(first.status, 202);
+  for (const query of ["true", "1", "ON", "yes"]) {
+    const answer = await submit(api, path + "?dryRun=" + query);
+    assert.equal(answer.status, 200, query);
+    assert.ok(answer.body.files);
+  }
+  assert.equal((await submit(api, path + "?dryRun=invalid")).status, 422);
+  assert.equal(api.state.created, 1);
+});
```

## Full patch · 594

```diff
--- a/LIVE-DOC-EDITS.md
+++ b/LIVE-DOC-EDITS.md
@@ -17,14 +17,13 @@
 | `POST /admin/auto-approval:pause`, `:resume` | 200 SwitchView |
 | `POST /clusters/{id}:probe` | 200 ClusterView |
 
-No route is a PUT. No 2xx response declares a header, and no service code sets `Location`: the one reference is the CORS
-exposure list, `cmapi/src/cmapi/core/cors.py:31`. The ChangeRequest names itself: `request_view` sets
+No route is a PUT. No successful write response declares a header. The write handlers send no `Location` on these successes. Routing redirects can send one. The explicit response-header name in the service source occurs in the CORS exposure list, `cmapi/src/cmapi/core/cors.py:31`. The ChangeRequest names itself: `request_view` sets
 `links = {"self": base, "events": f"{base}/events"}` with `base = f"/api/v1/requests/{row.request_id}"`
-(`cmapi/src/cmapi/core/views.py:15-16`).
+(`cmapi/src/cmapi/core/views.py:17-18`).
 
 RFC 9110 (https://www.rfc-editor.org/rfc/rfc9110.txt, read 2026-11-23), section 15.3.3: "The representation sent with this
 response ought to describe the request's current status and point to (or embed) a status monitor". The body does both, so
-the doc is corrected to the code; no `Location` header is added. Section 10.2.2 defines `Location` for 201 and 3xx, not 202.
+the doc is corrected to the code; no `Location` header is added. Section 10.2.2 describes status-dependent uses of `Location`, including 201 and 3xx.
 
 ## 1. docs/02-technical-design-v2.md, line 128 (Write semantics, the Async row)
 
@@ -37,7 +36,7 @@
 New:
 
 ```
-| Async | A write that opens a change request returns 202 with the ChangeRequest: today the namespace create, change and delete, and the three expiry writes. Its `links.self` is `/api/v1/requests/{requestId}`, the request to follow (`request_view`, `cmapi/src/cmapi/core/views.py:15-16`); no `Location` header is sent, because the body already points to the request, as RFC 9110, section 15.3.3 asks of a 202. The other writes return 200 with what they changed: the request actions (`:approve`, `:reject`, `:cancel`, `:retry`, `:revert`), `admin/prune:confirm`, `admin/auto-approval:pause` and `:resume`, and `clusters/{id}:probe` |
+| Async | Namespace create, change, delete, and the three expiry submissions return 202 with a ChangeRequest. Its status and `links.self` at `/api/v1/requests/{requestId}` let the client follow progress (`request_view`, `cmapi/src/cmapi/core/views.py:17-18`; RFC 9110 §15.3.3). These 202 responses omit `Location`. The five request actions (`:approve`, `:reject`, `:cancel`, `:retry`, `:revert`) and `admin/prune:confirm` return 200 with the request. The auto-approval pause and resume actions return 200 with the switch, and the cluster probe returns 200 with the cluster view. |
 ```
 
 ## 2. docs/01-design-and-architecture.md, line 730 (what the OpenAPI document fills in) — the same claim
@@ -51,19 +50,18 @@
 New:
 
 ```
-| 202 + ChangeRequest, whose `links.self` names the request, for a write that opens one; 200 Plan for its dry run; 200 for the other writes | The route's response model, for every write route |
+| Namespace submissions return 202 ChangeRequest with a status link in `links.self`. A dry run, where supported, returns 200 PlanView. DELETE has no dry run. The remaining writes return 200. | Each route's documented responses |
 ```
 
 ## Left as it is
 
 - `docs/15-keycloak-integration.md:212` lists `Location` among the response headers a page can read. That is what
-  `core/cors.py:31` exposes, so the row is true of the code. Exposing a header that is never sent is harmless; dropping it
-  from the list is a change to `core/cors.py`, which another implementer holds (#593).
+  `core/cors.py:31` exposes, so the row is true of the code. The list describes which headers JavaScript may read when present.
 - The designed quota and limit-range PUTs (`docs/02:185-186`) and metadata PATCH/PUT (`docs/02:1168-1169`) are not built.
-  The new row states the rule for "a write that opens a change request", so it covers them when they are.
+  Their response codes can be documented when implemented.
 
 ## Proof after the edit
 
 `scripts/doc-citations.py` holds docs/14, 15 and 16 only (its `DOCS`), so it does not check these two rows. Check the new
-citation by hand: `sed -n 15,16p cmapi/src/cmapi/core/views.py` shows the `base` and `links` lines quoted above. Then
+citation by hand: `sed -n 17,18p cmapi/src/cmapi/core/views.py` shows the `base` and `links` lines quoted above. Then
 `grep -n "Location header" docs/01-design-and-architecture.md docs/02-technical-design-v2.md` finds nothing.
```
