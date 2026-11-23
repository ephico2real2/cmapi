# PR #579, reviewer 2 (Opus 5.5, high), 2026-11-23

Head 925c879, worked in `review-579/r2/` (a plain copy of `head/`, not a repository). The patch is
`r2-outputs/fix.diff`. It applies to head with `patch -p1` from the repository root: checked on a fresh copy of `head/`,
and the result is byte-identical to `r2/`. It changes two files:

- `cmapi/src/cmapi/core/etag.py`
- `cmapi/tests/service/test_if_match_forms_571.py`

`examples/src/cmapi` is a symlink to `cmapi/src/cmapi`, so the fix covers it too.

## 1. Codex's P2: the quadratic If-Match parser. Accepted, with my test in place of the subprocess

**What I measured on head.** The pattern is `head/cmapi/src/cmapi/core/etag.py:16`, and the loop is `:46-53`. With
`time.process_time()`, the input `'"x",' + ws*N + 'x'` gives:

| N | Space, head | Space, fix | Tab, head | Tab, fix |
|---|---|---|---|---|
| 4,000 | 0.231 s | 0.0005 s | 0.249 s | 0.0005 s |
| 8,000 | 0.928 s | 0.0009 s | 0.992 s | 0.0009 s |
| 16,000 | 3.677 s | 0.0017 s | 3.997 s | 0.0018 s |

- **The GIL is held.** A thread that ticks every 10 ms got no tick at all during a 2.08 s parse on head. Python's `re` does
  not release the GIL. So one such request stalls every request on that API replica, not only its own worker thread.
- **Who can reach it.** `check_if_match` runs inside the plan, after the role check and the 404. The caller needs
  `namespaces:write` and an existing namespace. It is an authenticated denial of service.
- **How long the value can be.**
  - The API's server sets no limit of its own. uvicorn 0.32.1 runs with `http="auto"`, which is httptools here, because
    `uvicorn[standard]` installs it. Through cmapi's own `if_match` dependency, a 200,000-byte `If-Match` got 200 on
    httptools and on h11 (`r2-outputs/`, probe below).
  - The only cap is the front door. Its config is `cmapi-portal-ui/nginx/templates/cmapi.conf.template:100`,
    `large_client_header_buffers 4 16k`. The nginx documentation
    (https://nginx.org/en/docs/http/ngx_http_core_module.html, fetched 2026-11-23) says: "A request header field cannot
    exceed the size of one buffer as well, or the 400 (Bad Request) error is returned to the client."
  - `deploy/manifests/components/cmapi/40-networkpolicy.yaml` lets only the front door reach port 8080.
  - So one line of up to about 16 KiB reaches the parser, which costs about 3.7-4.6 s of CPU on head.
  - Several field lines are joined with `", "`. The comma ends the element, so one run of whitespace never spans two
    lines.

**Checking the fix against the RFC.**

- RFC 9110 §5.6.1.2 (https://www.rfc-editor.org/rfc/rfc9110.txt, fetched 2026-11-23) says a recipient "MUST accept lists
  that satisfy the following syntax: `#element => [ element ] *( OWS "," OWS [ element ] )`". The same section says to
  ignore empty elements, "but not so much that they could be used as a denial-of-service mechanism".
- §8.8.3 gives `entity-tag = [ weak ] opaque-tag`, `weak = %s"W/"`, `opaque-tag = DQUOTE *etagc DQUOTE` and
  `etagc = %x21 / %x23-7E / obs-text`.
- The fixed pattern is `[ \t]*(?:(W/)?"(etagc*)"[ \t]*)?(?:,|\Z)`. It reads OWS, then an optional tag followed by its
  OWS, then a comma or the end. That is the same language as head's pattern: with no tag, `[ \t]*[ \t]*` and `[ \t]*`
  accept the same strings. The capture groups are unchanged.
- **Proof of equivalence** (`r2-outputs/regex-equivalence.py`, output in `regex-equivalence.txt`): over all 299,593
  strings of length 0 to 6 over `' a",W/\t\x80'`, head and the fix give the same `if_match_tags`. They also give the same
  match span and groups at every start position. There are 0 differences.
- **Why it is linear.** `match` is anchored at `pos`. In the fix, only the leading `[ \t]*` can hold a run of
  whitespace. Every backtrack step then fails on its first character, because a space is neither `W`, `"`, `,` nor the
  end. So one element costs time linear in its length. Each loop step consumes at least one character, so the whole
  value is linear too.

**Other patterns in the diff, the same check.**

- `_UNQUOTED_TAG` (`etag.py:18`): it is used with `fullmatch` on one character class with `+`, so it cannot backtrack. It
  is linear.
- `etag_matches` (If-None-Match, `etag.py:26-31`) is not changed by this PR. It uses `split(",")`, `strip` and list
  membership, with no regex, so it is linear.
- `require_if_match` uses `.strip() == "*"`, which is linear.
- No other regex is added.

**The regression test.** I did not use Codex's `subprocess` with `timeout=2`.

- It measures wall time, and that time includes starting the interpreter and importing `cmapi`. A loaded runner inflates
  both, so the test could fail on a correct parser.
- Its 100,000-character input is about 6 times longer than any line that can reach the API.
- My test runs in-process and parses a value as long as the longest line the front door passes:
  `LONGEST_LINE = 16 * 1024 - len("If-Match: \r\n")`.
- It measures `time.process_time()`, the CPU time of this process. Other processes on a busy runner do not inflate it.
- The bound is 0.25 s. The fix takes 1.7-1.8 ms, so it has a margin of over 140 times. Head takes 4.0-4.6 s in pytest,
  which is 16 times over the bound.
- On head the test costs about 4 s per case and cannot hang, because the input size is fixed.
- I rejected a structural check, such as asserting the pattern's text. It would test how the code is written, not how it
  behaves, and a different quadratic pattern would pass it.
- Proof: with head's code and the new tests (`r2-outputs/head-with-new-tests.txt`), both cases fail:
  `assert (35.081646 - 31.044774) < 0.25` and `assert (39.843681 - 35.265043) < 0.25`, so 2 failed and 41 passed. On the
  fix, both pass.

**Process note.** This defect was found in review and is in scope, so the fix belongs in this PR. Under `fix-defect`,
the coordinator files its issue. The comment in `etag.py` and the test's docstring cite "PR #579 review". Replace that
with the issue number once it is filed.

## 2. The test gaps Codex listed

**The wildcard-replay test cannot catch a replay that compares.** Closed. It was cheap and the gap was real.

- In head, `test_a_replay_with_star_is_428` (`test_if_match_forms_571.py:97-110`) never moves Git, so a replay that
  compared tags would still pass it.
- The #495 test of a replay after Git moved exists for PATCH only
  (`test_if_match_before_replay_495.py:46-56`). DELETE (`router.py:345-348`) and the expiry path (`_expiry_write`,
  `router.py:366-369`) are separate replay branches, and they have only "without If-Match is 428" tests (`:59-77`).
- **The fix.** The test now edits the folder in Git between the first request and the retries, using the idiom of
  `test_namespace_etag_doc_565.py:134-135`. It asserts that the etag moved. It is parametrized over `patch`, `delete` and
  `expiration:set`.
- **Mutation proof** (`r2-outputs/mutant-replay-compares.txt`). In the mutant, the DELETE and expiry replay branches call
  `check_if_match` against the current `folder_etag`.
  - The new test fails for `delete` and `expiration:set`: 412 "The namespace changed in Git since you read it" instead
    of 202.
  - Head's original test (2 cases) and the whole #495 file (7 tests) pass on the mutant. That proves the gap was real.

**The expiry test covers only `:set`.** No change.

- `:extend`, `:set` and `:makePermanent` all go through `_expiry_write` (`router.py:358-374`), then
  `plan_namespace(..., if_match=etag)`, then `check_if_match`. That is one code path.
- `test_the_document_says_how_each_form_is_read` already requires that all 5 operations carry the shared `If-Match`
  parameter, whose description comes from the one `if_match` dependency.
- A test for each route would add nothing that the one path does not already cover. The owner's rule is to over-build
  only when it is the only solution.

**The parser has no long-whitespace case.** Closed by the test in section 1.

**The doc test only matches strings.** No change. Its job is to pin the promised wording. The behaviour is tested by
`FORMS` and the replay tests.

## 3. Gitea's direct-file path, which FakeGit's filter does not support. No change

Every production caller of `read_folder` passes a folder path:

- `pipeline.py:189`, `jobs/open_pr.py:70`, `jobs/push_branch.py:29`, `jobs/pr_checks.py:74,89,130`,
  `jobs/watch_sync.py:89,121`, `jobs/merge.py:76,140` and `jobs/apply.py:71,79,81` all pass
  `folder(cluster_id, ns)`. Some go through `tree_files` or `merge_check`.
- `folder()` returns `clusters/{c}/namespaces/{ns}/` (`render/manifests.py:61-62`).
- `gitea.py:97,105` passes `req.folder`, which `jobs/delivery.py:81` builds from `folder()`.
- No caller passes a file path. FakeGit's filter (`conftest.py:176-179`) matches every way the code calls it.

## 4. What Codex missed

**F1. docs/02 still contradicts the decision in two places, and the PR body's proposed citation goes stale with my
patch.** docs/02 is an export of a live doc, so this goes to the live doc first, then the export.

- `docs/02-…md:131` says "The plan compares the value with its surrounding double quotes removed", and cites
  `pipeline.py:98-100` and `:218`. The PR body has replacement text for this line.
  - With my patch, `if_match_tags` moves from `etag.py:34-54` to **`etag.py:36-56`**, so the citation in that proposal
    must change to match.
  - `check_if_match` stays at `pipeline.py:120-130`, and `folder_etag` at `99-101`.
- `docs/02-…md:166`: the problem table says `precondition-required / failed | 428 / 412 | Missing or stale If-Match`.
  The PR body's proposal does not touch this line. Since #571, 428 also covers `*`, and 412 also covers a value that
  lists no strong tag. Proposed cell: `Missing If-Match, or If-Match: * (428); no strong tag it lists is the current
  ETag (412)`.

**F2. The owner's point 4 and the PR's replay behaviour, set side by side for the coordinator.** I am not re-arguing the
decision.

- The decision says: "An Idempotency-Key replay is unchanged: it returns the stored answer".
- The PR changes a replay with `*` from 202 on main (the stored answer, as the PR body's table measured) to 428. The
  PR body's decision 1 gives the reason.
- The fact that settles it:
  - An Idempotency-Key is recorded only at submit, and a first request with `*` is 428 before that point.
  - So a replay with `*` is always a retry that swapped a real tag for `*`. Refusing it loses no retry of an identical
    request.
  - The comparison is still not repeated on any replay. My mutation run shows the tests now prove that on all three
    replay branches.
- I read point 4 as being about the comparison, and points 2 and 4 as consistent. The coordinator should confirm that
  reading on #571.

**F3. Repeated field lines through the real server.** The PR lists this under "Not tested". I tested it.

- Through uvicorn 0.32.1 with httptools and with h11, using cmapi's own `if_match` dependency, two lines `"0"` and
  `"abc"` arrive as `"0", "abc"`, and `*` arrives as `*`.
- The probe is `r2-outputs/uvicorn-field-lines.py`, and its output is `uvicorn-field-lines.txt`.
- nginx itself was not run.

**F4. Nit, not changed.** `router.py:310` is a new 164-character line in the `update_namespace` docstring. That docstring
is the OpenAPI description, which `contract/openapi.json` and `schema.generated.ts` snapshot. Reflowing it would mean
regenerating both files for no change in meaning, so I left it.

**Checked, no finding.**

- `docs/04` line 19, `docs/GLOSSARY.md` (the `If-Match`, 428 and 412 rows), the `If-Match` parameter description, the
  `NamespaceView.etag` and `PlanView.etag` descriptions, the `PROBLEM_STATUS_TEXT` 412 and 428 entries, and the
  `require_if_match` and `check_if_match` docstrings all agree with the code and with the owner's points 1-4.
- The 412 sample in `contract/samples.json` (`"stale"`) still gives the same detail.
- In the docs/14 citation lock, the six entries changed only their line keys. Their text is the same, and the checker
  reports 0 problems.

## 5. The patch (`r2-outputs/fix.diff`)

```diff
--- a/cmapi/src/cmapi/core/etag.py
+++ b/cmapi/src/cmapi/core/etag.py
@@ -13,7 +13,9 @@
 # RFC 9110 section 8.8.3: entity-tag = [ weak ] opaque-tag, opaque-tag = DQUOTE *etagc DQUOTE, and etagc is any visible
 # character but DQUOTE, or obs-text. A list element (section 5.6.1.2) is OWS, an entity-tag or nothing, OWS, then a comma
 # or the end. A tag may hold a comma, so a list is read element by element, never split on ",".
-_LIST_ELEMENT = re.compile(r'[ \t]*(?:(W/)?"([\x21\x23-\x7e\x80-\xff]*)")?[ \t]*(?:,|\Z)')
+# The OWS after a tag sits inside the tag's group, so only one [ \t]* can take a run of whitespace. Two in a row would share
+# it, and a run that does not end its element would be retried at every split: a quadratic parse (PR #579 review).
+_LIST_ELEMENT = re.compile(r'[ \t]*(?:(W/)?"([\x21\x23-\x7e\x80-\xff]*)"[ \t]*)?(?:,|\Z)')
 # One strong tag sent without its quotes: etagc characters, no comma.
 _UNQUOTED_TAG = re.compile(r'[\x21\x23-\x2b\x2d-\x7e\x80-\xff]+')
 
--- a/cmapi/tests/service/test_if_match_forms_571.py
+++ b/cmapi/tests/service/test_if_match_forms_571.py
@@ -11,6 +11,7 @@
 """
 from __future__ import annotations
 
+import time
 import uuid
 from datetime import date, timedelta
 
@@ -94,19 +95,31 @@
     assert r.status_code == 200, r.text
 
 
-@pytest.mark.parametrize("method", ["patch", "delete"])
+def _send(client, method: str, headers: dict):
+    """One write of each replay path: PATCH and DELETE in their routes, and the three expiry writes in _expiry_write."""
+    if method == "patch":
+        return client.patch(URL, json={"tier": "medium"}, headers=headers)
+    if method == "delete":
+        return client.delete(URL, headers=headers)
+    until = (date.today() + timedelta(days=20)).isoformat()
+    return client.post(f"{URL}/{method}", json={"until": until, "justification": "One sprint"}, headers=headers)
+
+
+@pytest.mark.parametrize("method", ["patch", "delete", "expiration:set"])
 def test_a_replay_with_star_is_428(world, method):
-    """The replay path checks If-Match as the first request would (#495), so * is refused there as everywhere."""
+    """The replay path checks If-Match as the first request would (#495), so * is refused there as everywhere. It does not
+    compare the tags: Git moves before the retries, so a replay that compared would answer 412 to the listed value."""
     client, ctx, git, kube, validator, keys = world
     tag = _created(client, ctx, keys)
     key = str(uuid.uuid4())
-    send = (lambda h: client.patch(URL, json={"tier": "medium"}, headers=h)) if method == "patch" else \
-        (lambda h: client.delete(URL, headers=h))
-    first = send({**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"{tag}"'})
+    first = _send(client, method, {**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"{tag}"'})
     assert first.status_code == 202, first.text
-    replay = send({**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": "*"})
+    git.branches["main"]["clusters/CRC/namespaces/payments-dev/namespace.yaml"] += "# edited in Git\n"
+    git._sha("main")
+    assert client.get(URL, headers=auth(keys, "ola", **OLA)).json()["etag"] != tag, "Git moved: the tag is stale"
+    replay = _send(client, method, {**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": "*"})
     assert replay.status_code == 428 and replay.json()["code"] == "precondition-required", replay.text
-    listed = send({**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"0", "{tag}"'})
+    listed = _send(client, method, {**auth(keys, "ola", **OLA), "Idempotency-Key": key, "If-Match": f'"0", "{tag}"'})
     assert listed.status_code == 202 and listed.json()["requestId"] == first.json()["requestId"], listed.text
 
 
@@ -120,6 +133,24 @@
     from cmapi.core.etag import if_match_tags      # imported here, so the service tests above also run on main
     assert if_match_tags(value) == tags
 
+
+# The longest If-Match line that reaches the API: the front door reads a header line into one buffer of 16k
+# (large_client_header_buffers 4 16k, cmapi-portal-ui/nginx/templates/cmapi.conf.template), and the API's server, uvicorn
+# with httptools, sets no limit of its own. "If-Match: " and the CRLF take the rest of the line.
+LONGEST_LINE = 16 * 1024 - len("If-Match: \r\n")
+
+
+@pytest.mark.parametrize("ws", [" ", "\t"], ids=["space", "tab"])
+def test_the_parser_reads_a_long_run_of_whitespace_in_linear_time(ws):
+    """PR #579 review: two adjacent [ \\t]* in the element pattern shared one run of whitespace, and a run that does not end
+    its element was retried at every split. One such line took 3.7 s of CPU, with the GIL held, against 2 ms once linear.
+    CPU time of this process, not wall time, so a busy runner does not inflate it; the bound leaves the linear parse a
+    margin of over 100 times and is under a tenth of the quadratic one."""
+    from cmapi.core.etag import if_match_tags
+    value = '"x",' + ws * (LONGEST_LINE - len('"x",x')) + "x"
+    start = time.process_time()
+    assert if_match_tags(value) == []
+    assert time.process_time() - start < 0.25, "the parse is no longer linear in the length of the value"
 
 
 def test_the_document_says_how_each_form_is_read(world):
```

The patch also removes the third blank line before `test_the_document_says_how_each_form_is_read`, which was
`head :122-124`.

No generated file changes. No description, docstring or OpenAPI text is touched, so `contract/openapi.json`,
`schema.generated.ts` and `docs/04` stay current. `api-examples-doc.py --check` exits 0 on the fixed copy.

## 6. Test outputs (all in `r2-outputs/`)

| Run | Tree | Result |
|---|---|---|
| The 6 named files (`before-tests.txt`) | head | 91 passed, 1 failed. The failure is `test_doc_citations`, because the export is not a Git repository and `git ls-files` exits 128. It is not a code failure; see the next row |
| `test_doc_citations.py` (`before-doc-citations-test.txt`) | head, in a throwaway `git init` + `git add -A` copy in my scratchpad | 12 passed |
| `scripts/doc-citations.py --check` (`before-citations.txt`) | same copy of head | `doc-citations: 0 problems`, exit 0 |
| The 5 service files: 571, 578, 495, 565 and api_docs (`after-tests.txt`) | r2 (fixed) | **83 passed** (80 before, plus 2 timing cases and the `expiration:set` replay case), exit 0 |
| `test_doc_citations.py` (`after-doc-citations-test.txt`) | r2, in a throwaway git-indexed copy | 12 passed |
| `scripts/doc-citations.py --check` (`after-citations.txt`) | same copy of r2 | `doc-citations: 0 problems`, exit 0 |
| `scripts/api-examples-doc.py --check` (`after-api-examples-doc.txt`) | r2 | exit 0 |
| The new tests on head's code (`head-with-new-tests.txt`) | head plus the new test file | 2 failed (timing: 4.04 s and 4.58 s CPU, bound 0.25 s), 41 passed |
| Replay tests on a mutant whose replay compares (`mutant-replay-compares.txt`) | r2 plus the mutant | The new test fails on `delete` and `expiration:set`. Head's original test and all of #495 pass. That proves the gap |
| Regex equivalence (`regex-equivalence.txt`) | head and r2 | 299,593 strings, 0 differences |
| Field lines through uvicorn (`uvicorn-field-lines.txt`) | r2 | httptools and h11: `"0", "abc"`, and `*` |

PostgreSQL 16 on 127.0.0.1:55432 (`cmapi-test-pg`). I created my own databases, `cmapi_r2_579`, `cmapi_r2_579b` and
`cmapi_r2_579c`, through `CMAPI_TEST_DATABASE_URL`, and dropped all three at the end.

## 7. What I ran and did not run

- **Ran:** everything in the table above, the timing probes, the GIL probe, and the uvicorn header-size probe (200,000
  bytes accepted by httptools and h11).
- **Did not run:**
  - The full service suite. The PR body reports 2,243 passed on head.
  - The Spectral lint, the gate and the portal checks. My patch changes no document or description.
  - nginx itself.
  - CRC and kind.
- **Fetched on 2026-11-23:** RFC 9110 (§5.6.1.2 and §8.8.3) from rfc-editor.org, and the nginx `ngx_http_core_module`
  documentation.
- **Nothing was written** to CRC, LDAP, Keycloak or any Git repository. The `git init` copies are throwaway directories in
  my session scratchpad.
- **Working trees in `review-579/`:**
  - `r2/` is the fix.
  - `r2-head-run/` is head plus the new test file.
  - `r2-mutant/` is the mutant.
  - `pt/` holds the patch-building copies.
  - All four can be deleted.

## 8. New defects outside this PR

None. For the coordinator to file and fix in this session:

- The quadratic parse (section 1). It is in this PR, and it needs its own issue under `fix-defect`.
- The two docs/02 places (F1). They go to the live doc, then the export.
