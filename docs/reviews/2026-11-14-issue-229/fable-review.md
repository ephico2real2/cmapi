# PR #231 review: ReDoc as a module, and the 3.1.0 pin (BUG-57, SEC-11)

Reviewer: Fable 5.2, on 2026-11-14. Head `62e3f33`, base `962d7f8`. The author is Opus 5.5; no Codex pass ran.
I worked on `git archive` exports in my scratchpad. I did not push, merge or edit the repository.

## Verdict: changes needed

One finding blocks the merge, and one is a small text error.

- **F1 (high).** The page that this PR makes work sends data to two other hosts from each reader's browser. The PR body
  and the docstring say that it does not.
- **F2 (low).** The new test's docstring names a browser test file that is in no branch.

Everything else in the brief is confirmed: see "The five checks".

## F1 (high): `/redoc` now asks two other hosts, one of them with usage telemetry

**Where.** `cmapi/src/cmapi/main.py:266-267` (the route) and `:274-298` (`_redoc_html`), at head `62e3f33`.

**What the PR claims.** The docstring at `main.py:275`: "The ReDoc page, with no request to another host". The PR body:
"The page still makes no request to another host." `docs/08-code-status.md:84`: "No page loads a file from another
server". `docs/01`, line 693, gives the reason: "a network-limited zone may not reach a public CDN".

**What I measured.** Playwright's Chromium, this Mac, 2026-11-14. The page is the PR's own `_redoc_html`, the spec is
`cmapi/contract/openapi.json`, and the bundle is `redoc.standalone.js` from the 3.1.0 tarball whose SHA-256 is the
Containerfile's. The host name is `cmapi.apps.example.test`, mapped to 127.0.0.1, because a real instance is not on
`localhost`. Each request to another host was recorded and aborted, so nothing left this Mac.

```text
$ python serve2.py <tree> x3.1.0/package/bundles/redoc.standalone.js 18931 &
$ node probe.mjs <cmapi-portal-ui> 18931 cmapi.apps.example.test /redoc

=== tree: pr (head 62e3f33)
{ "path": "/redoc", "apiContent": 1, "errors": [], "outside": [
  "GET https://cdn.redoc.ly/redoc/logo-mini-full.svg (image, body 0 bytes)",
  "POST https://otel.cloud.redocly.com/v1/traces (fetch, body 7097 bytes)",
  "POST https://otel.cloud.redocly.com/v1/traces (fetch, body 3151 bytes)" ]}
workers 4

=== main's page (get_redoc_html, classic script), same bundle
{ "path": "/redoc-main", "apiContent": 0, "errors": ["Cannot use 'import.meta' outside a module"], "outside": [] }
```

So on main the bundle does not run and nothing is sent. This PR is the change that starts the requests.

**What is sent.** I saved one aborted POST body and listed its keys. It holds a session id, `service.version
redoc@3.1.0`, and counts that describe the API: `operations_count 32`, `schemas_count 76`, `shape.tags 7`,
`shape.secured_operations 31`, `shape.scheme_types.oauth2 1`, `shape.oauth2_flows.authorization_code 1`,
`is_localhost false`. The body does not hold the host name or the spec. Not measured: the request's headers. A browser
adds `Origin` to a cross-origin POST (the Fetch standard), so the receiver would also learn the instance's origin and
the reader's address; that part is inferred, not measured.

**The primary sources**, read on 2026-11-14:

- ReDoc 3.0.0 release notes (`gh release view 'redoc@3.0.0' -R Redocly/redoc`), the same page the PR cites, under
  "Features": "Anonymous OpenTelemetry usage telemetry, on by default." It also lists the new option `disableTelemetry`.
- `package/README.md` in `redoc-3.1.0.tgz`, line 179: "Redoc collects anonymous usage and performance data to help
  prioritize work. It never sends your API definition content or personal information. Opt out with
  `disable-telemetry="true"` on the `<redoc>` tag, `disableTelemetry: true` in options."
- The bundle: the collector is `https://otel.cloud.redocly.com/v1/traces`. The logo component is
  `<img alt="redocly logo" src="https://cdn.redoc.ly/redoc/logo-mini-full.svg">`, with `onError` hiding it. I found no
  option that removes the logo.

**Why the existing test did not see it.** `test_the_pages_load_only_from_this_server` reads `src=` and `href=` in the
HTML. The requests come from the bundle at run time. The author's Chromium check counted `.api-content` and page errors,
not requests.

### The fix

Two parts. The tag's attribute turns the telemetry off at its source. A Content-Security-Policy on the page's own
response makes the browser refuse each other host, which covers the logo and whatever a later bundle adds.

I first tried `script-src 'self'` alone. It stopped the search workers without a page error (0 workers, violation
`script-src eval`), so the policy below has `'unsafe-eval'`. The app has no policy at all today, so this is stricter
than now. The policy is on `/redoc` only; `/docs` and every other route are unchanged.

`cmapi/src/cmapi/main.py`, against head `62e3f33`:

```diff
@@ -264,16 +264,29 @@
         if not redoc_dir.exists():
             return missing("ReDoc")
         return HTMLResponse(_redoc_html(f"cmapi ({ctx.cfg.name}) - reference", "/openapi.json",
-                                        "/static/redoc/redoc.standalone.js", "/static/swagger/favicon-32x32.png"))
+                                        "/static/redoc/redoc.standalone.js", "/static/swagger/favicon-32x32.png"),
+                            headers={"Content-Security-Policy": REDOC_CSP})
 
     @app.get("/docs/changelog", include_in_schema=False, dependencies=guard)
     def changelog() -> Response:
         return HTMLResponse(changelog_html(f"cmapi ({ctx.cfg.name})", __version__))
 
 
+# The ReDoc page fetches from this server only (docs/01: the bundles come from the image, never a CDN). ReDoc 3.1.0 asks two
+# other hosts by itself: usage telemetry to otel.cloud.redocly.com, which the tag's disable-telemetry turns off, and the
+# "API docs by Redocly" logo from cdn.redoc.ly, which has no option. The policy stops both in the browser, and whatever a
+# later bundle adds. 'unsafe-eval' and blob: workers are for the bundle's search index (FlexSearch); 'unsafe-inline'
+# styles are for styled-components. Without them the search workers do not start (measured, #231 review).
+REDOC_CSP = ("default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
+             "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:")
+
+
 def _redoc_html(title: str, spec_url: str, bundle_url: str, favicon_url: str) -> str:
-    """The ReDoc page, with no request to another host (no Google Fonts, no outside favicon).
+    """The ReDoc page. With REDOC_CSP on its response it makes no request to another host.
 
+    ReDoc 3 sends anonymous usage telemetry by default (its 3.0.0 release notes: "Anonymous OpenTelemetry usage
+    telemetry, on by default"). Its README gives the opt-out: disable-telemetry="true" on the <redoc> tag.
+
     ReDoc 3's standalone bundle is an ES module: its 3.0.0 release notes say "Load the bundle with
     <script type="module" src=".../bundles/redoc.standalone.js">", and the bundle reads import.meta.url. A classic
     script stops at the first import.meta with a SyntaxError, which is what FastAPI's get_redoc_html gave (#229). As a
@@ -291,7 +304,7 @@
 </head>
 <body>
 <noscript>ReDoc needs JavaScript to show the reference.</noscript>
-<redoc spec-url="{html.escape(spec_url)}"></redoc>
+<redoc spec-url="{html.escape(spec_url)}" disable-telemetry="true"></redoc>
 <script type="module" src="{html.escape(bundle_url)}"></script>
 </body>
 </html>
```

The new lines are after line 266, so the citations of `main.py:122-123`, `142-144` and `169` do not move.

### The test

`cmapi/tests/service/test_api_docs.py`, against head `62e3f33`. One assertion of the PR's test changes, and one test is
new:

```diff
@@ -388,7 +388,7 @@
     with build_world(test_config, keys, monkeypatch) as (client, *_):
         page = client.get("/redoc").text
     assert re.findall(r"<script\b[^>]*>", page) == ['<script type="module" src="/static/redoc/redoc.standalone.js">']
-    assert '<redoc spec-url="/openapi.json"></redoc>' in page
+    assert '<redoc spec-url="/openapi.json" disable-telemetry="true"></redoc>' in page
     assert "<title>cmapi (" in page and ") - reference</title>" in page
 
 
@@ -398,3 +398,18 @@
     version, sha = pinned(CMAPI / "Containerfile")["REDOC"]
     assert tuple(int(p) for p in version.split(".")) >= (3, 1, 0), f"ReDoc {version} bundles a DOMPurify with GHSA-cg2g-xh64-v4q7"
     assert re.fullmatch(r"[0-9a-f]{64}", sha)
+
+
+def test_the_redoc_page_asks_no_other_host(bundles, test_config, fresh_db, keys, monkeypatch):
+    """ReDoc 3 sends usage telemetry to otel.cloud.redocly.com by default and loads its logo from cdn.redoc.ly (measured
+    in Chromium on the 3.1.0 bundle). docs/01: a network-limited zone may not reach another host. The tag turns the
+    telemetry off, and the page's policy lets the browser fetch from this server only."""
+    with build_world(test_config, keys, monkeypatch) as (client, *_):
+        r = client.get("/redoc")
+    assert re.search(r'<redoc\b[^>]*\bdisable-telemetry="true"', r.text), "ReDoc's telemetry is on"
+    policy = {d.split()[0]: d.split()[1:] for d in r.headers.get("content-security-policy", "").split(";") if d.strip()}
+    assert policy.get("default-src") == ["'none'"], policy
+    assert policy.get("connect-src") == ["'self'"], "the page may send data to another host"
+    assert policy.get("script-src") == ["'self'", "'unsafe-eval'"] and policy.get("worker-src") == ["'self'", "blob:"]
+    for directive, sources in policy.items():
+        assert not [s for s in sources if "//" in s or s in ("*", "https:", "http:")], f"{directive} lets in another host"
```

**Before and after**, under `suite.sh`, on the test database:

```text
== before (head 62e3f33 code + these tests): tests/service/test_api_docs.py
FAILED tests/service/test_api_docs.py::test_redoc_loads_its_bundle_as_a_module
FAILED tests/service/test_api_docs.py::test_the_redoc_page_asks_no_other_host
E       AssertionError: ReDoc's telemetry is on
2 failed, 19 passed in 9.98s

== after (the fix): test_api_docs.py, test_review_c_authz.py, test_portal_map.py
40 passed in 24.15s
```

**The browser, after the fix** (the fixed tree's own `_redoc_html` and `REDOC_CSP`):

```text
=== tree: fix
{ "path": "/redoc", "apiContent": 1, "errors": [
  "console: Loading the image 'https://cdn.redoc.ly/redoc/logo-mini-full.svg' violates the following Content Security
   Policy directive: \"img-src 'self' data:\". The action has been blocked." ], "outside": [] }
workers 4
```

The page renders, the four search workers start as they do without the policy, and no request goes to another host. The
one console line is the browser refusing the logo; the bundle then hides the image.

**Not tested in the fix:** the full service suite on the fixed tree (I ran the three files above), typing in ReDoc's
search box, the image build, and any browser other than Playwright's Chromium. The pytest holds the header and the
attribute; it cannot see what the bundle does. The repository has no browser test of `/redoc` (see F2), so the render
above is the only proof of the run-time behaviour. Reviewer 2 or the coordinator should repeat it.

**Also update** in the same PR: the "Decision" and "Proof" parts of `docs/reviews/2026-11-14-issue-229/README.md` (the
row "The page keeps no request to another host" is true only after this fix), and the PR body.

## F2 (low): the test's docstring names a browser test that does not exist

**Where.** `cmapi/tests/service/test_api_docs.py:385-387`: "The browser check
cmapi-portal-ui/tests/front-door.test.mjs renders the page; this test holds the one tag that decides it."

**Evidence.**

```text
$ gh api "repos/ephico2real2/cmapi/git/trees/62e3f33ee8772dac6b705f6c47fe5e57e4b68609?recursive=1" \
    --jq '.tree[].path' | grep -c "front-door"
0
$ git ls-tree -r --name-only origin/main | grep -i front-door        # no output
$ ls cmapi-portal-ui/tests/
api  behaviour.test.mjs  contract.test.mjs  extract-model.test.mjs  parity.test.mjs
```

No test in the repository renders `/redoc`. A reader of the docstring would think that one does.

**Fix** (docstring only):

```diff
 def test_redoc_loads_its_bundle_as_a_module(bundles, test_config, fresh_db, keys, monkeypatch):
     """ReDoc 3's standalone bundle is an ES module (its 3.0.0 release notes). Loaded by a classic <script src>, it stops
-    at import.meta and the page stays empty (#229). The browser check cmapi-portal-ui/tests/front-door.test.mjs renders
-    the page; this test holds the one tag that decides it."""
+    at import.meta and the page stays empty (#229). No test in this repository renders the page in a browser: the render
+    was done by hand and is in docs/reviews/2026-11-14-issue-229/. This test holds the one tag that decides it."""
```

**Check, fails before and passes after:**

```bash
# from the repository root: each tests/*.mjs path that test_api_docs.py names is a file
for f in $(grep -o 'cmapi-portal-ui/tests/[a-z-]*\.test\.mjs' cmapi/tests/service/test_api_docs.py); do test -f "$f" || { echo "missing: $f"; exit 1; }; done
```

Before: `missing: cmapi-portal-ui/tests/front-door.test.mjs`, exit 1 (measured on the PR export). After: exit 0, by
construction; I did not run it on a fixed tree. If a front-door browser test is planned under #226, an issue for a
`/redoc` render in it would close the real gap.

## The five checks

### 1. The new page: correct and safe?

Correct as a module page; not safe to merge until F1 is fixed.

| Item | Result |
|---|---|
| Module script | Confirmed. `<script type="module" src="/static/redoc/redoc.standalone.js">`. The bundle ends `export{RedocStandalone,hydrate,init};` and starts itself on `<redoc spec-url>`: `.api-content` 1, no page error |
| Spec URL | `/openapi.json`, same as before |
| `docs.enabled`, `docs.public` | Unchanged. `_add_docs` is still called only `if docs_enabled` (`main.py:183-184`), and the route keeps `dependencies=guard`. `test_docs_public_false_puts_the_five_paths_behind_a_token` and `test_docs_enabled_false_serves_none_of_them` passed on the head |
| Headers | `content-type: text/html; charset=utf-8`, same as `get_redoc_html`. No other header before or after |
| CSP | None, before or after. `grep -rn Content-Security-Policy cmapi/src` has no result. `docs/15`, line 174: the policy "comes with the portal's image and its Route, which are not built". F1's fix adds one for this page |
| Favicon | `/static/swagger/favicon-32x32.png`, same file. It is served only when the Swagger bundle is present, as before |
| No CDN in the HTML | Confirmed for the HTML. Refuted for the page at run time: F1 |
| Sibling files of the bundle | None needed. The Containerfile extracts only `redoc.standalone.js`, and my server held only that file; the page rendered |

Each difference from `get_redoc_html` (FastAPI 0.115.6, printed from the suite's venv):

1. `<script type="module" ...>` replaces `<script src=...> </script>`. A module script is deferred, is fetched in CORS
   mode, and the browser refuses it unless its MIME type is a JavaScript type. Starlette's `StaticFiles` gives
   `text/javascript` on this Mac (Python 3.12.14). Not tested in the image, which was not built.
2. The title is now escaped with `html.escape`. FastAPI puts it in raw. An instance name with `<` or `&` now shows
   correctly.
3. `<html lang="en">` replaces `<html>`.
4. `<link rel="icon">` replaces `<link rel="shortcut icon">`.
5. The `<noscript>` text differs, and FastAPI's two HTML comments are gone.
6. `<meta charset>` and `<meta viewport>` now come before `<title>`.

None of these changes authentication or the routes.

### 2. The ReDoc 3.0.0 release note

Read on 2026-11-14 with `gh release view 'redoc@3.0.0' -R Redocly/redoc --json tagName,publishedAt,body`. Published
2026-10-14T11:15:43Z. Under "Features":

> **ES module build.** The package and the standalone bundle ship as ES modules.
> Load the bundle with `<script type="module" src="…/bundles/redoc.standalone.js">` and import `init` (and `hydrate` for server-rendered markup) from it.

Under "Breaking Changes": "The UMD bundle and the global `Redoc` object are removed."

The PR's quotation is correct but stops before "and import `init` ... from it". The page does not import `init`; it
relies on the bundle starting itself on the `<redoc>` tag. The release note does not say that it does, but the README
shows the tag form, and my render confirms it for 3.1.0.

### 3. The advisory, the bundle and the pin

All confirmed.

```text
$ gh api /advisories/GHSA-cg2g-xh64-v4q7
severity critical, published 2026-10-22T16:25:31Z, not withdrawn, no CVE id
"DOMPurify SAFE_FOR_TEMPLATES bypass: split template expressions survive in attached shadow root content on DOM output modes"
npm dompurify, vulnerable ">= 3.4.4, <= 3.4.16", first patched "3.4.17"

$ grep -o 'version=`3\.4\.[0-9]*`' package/bundles/redoc.standalone.js
3.0.1: version=`3.4.16`        3.1.0: version=`3.4.17`

$ shasum -a 256 redoc-3.1.0.tgz
d6f4b0c0abb970724c112473ace8229fd1cc3c78be4ca110841de4c640de15a9      # equals REDOC_SHA256 in the Containerfile
$ echo "sha512-$(openssl dgst -sha512 -binary redoc-3.1.0.tgz | base64)"
sha512-hYsN0ABpoDAPE2+A+mNvs6DDTzhPlJaIeJK2jCFgvxtiXHpWzBXqNBWWKUNq/VLBMZGnyT4qiQnODVWEX031uQ==   # equals npm dist.integrity
$ shasum -a 1 redoc-3.1.0.tgz
a710b0408f8793dada47ae8485103e2487526425                                # equals npm dist.shasum
```

The old pin also checks: `redoc-3.0.1.tgz` has SHA-256 `d9666cd5...dac189`, the value on main.

DOMPurify is bundled, not a dependency: `dependencies.dompurify` is absent from the 3.0.0, 3.0.1 and 3.1.0 package
metadata, so the version string in the bundle is the evidence. `gh api "/advisories?ecosystem=npm&affects=dompurify@3.4.17"`
returned nothing.

**A newer release?** No. npm `dist-tags.latest` is `3.1.0` (published 2026-11-05T11:15:41Z), and GitHub's latest
release is `redoc@3.1.0`. The record's exception to the 14-day wait is stated and reasoned.

### 4. The tests on main's code

Confirmed: both fail for the right reason. Main's tree with the PR's `test_api_docs.py`, then the PR head:

```text
== before (main 962d7f8 code + PR tests): tests/service/test_api_docs.py
FAILED test_redoc_loads_its_bundle_as_a_module
E   At index 0 diff: '<script src="/static/redoc/redoc.standalone.js">' != '<script type="module" src="/static/redoc/redoc.standalone.js">'
FAILED test_the_redoc_pin_carries_the_dompurify_fix
E   AssertionError: ReDoc 3.0.1 bundles a DOMPurify with GHSA-cg2g-xh64-v4q7
2 failed, 18 passed in 10.00s

== after (head 62e3f33): tests/service/test_api_docs.py
20 passed in 9.64s

== after (head 62e3f33): the full service suite
2 failed, 820 passed in 397.39s (0:06:37)
```

The two failures of the full run are `test_doc_citations` and `test_third_pass_converged`. Both call `git ls-files`,
and my tree is a `git archive` export with no repository (`returned non-zero exit status 128`). They are a result of my
export, not of the PR. So I confirm 820 of the PR's 822, and GitHub's `service` check is green for the other two.

The Chromium result is also confirmed: `.api-content` 0 with `Cannot use 'import.meta' outside a module` on main's
page, and 1 with no error on the PR's page.

A limit of the pin test: it asserts the version is at least 3.1.0 and that the hash has 64 hexadecimal characters. It
does not tie the hash to the version. The existing docs-assets test checks the hash at fetch time, so I do not raise it.

Each pytest run went through `suite.sh`, one at a time. The lock directory was held by another session when I started
and again when I finished; my runs waited for it and released it.

### 5. Anything else that changes behaviour?

No. The diff of `main.py` touches the `redoc()` route, adds `_redoc_html` and `import html`, and drops the
`get_redoc_html` import. `/docs`, `/docs/oauth2-redirect`, `/openapi.json`, `/openapi.yaml`, the ETag code and
`/docs/changelog` are not in the diff, and their tests passed on the head. `cmapi/contract/openapi.json` is unchanged,
and `/redoc` stays out of the document (`include_in_schema=False`). The three doc files change line numbers only, and
`docs/citations.lock.json` matches them.

## Evidence files

All in `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/f7ded52b-75f6-4c7e-b4dc-532bcd598fb3/scratchpad/`.
It is a session scratchpad, so copy what should be kept.

- `h/serve.py`, `h/serve2.py`, `h/probe.mjs`, `h/dbg.mjs`: the browser harness.
- `h/fix-main.diff`, `h/fix-test.diff`: the fix and the test, as applied in `fix/`.
- `h/telemetry.json`: one telemetry body, aborted before it was sent.
- `logs/before.log`, `logs/after-docs.log`, `logs/after-full.log`, `logs/f1-before.log`, `logs/f1-after.log`.
- `dl/redoc-3.0.1.tgz`, `dl/redoc-3.1.0.tgz`: the two tarballs from registry.npmjs.org.
