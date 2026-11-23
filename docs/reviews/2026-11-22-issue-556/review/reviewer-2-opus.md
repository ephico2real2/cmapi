# PR #559: reviewer 2's report (Opus 5.5 at high)

Head fb24158, base 5c01876. I did not write this code. I worked only in copies: `review-559/r2/` (head plus my fixes) and
`review-559/mut/` (mutant trees). I ran no git command in them, pushed nothing, and wrote nothing to CRC, LDAP or Keycloak.
The outputs are in `review-559/r2-outputs/`, and the scripts that made them are in `review-559/r2-outputs/harness/`.

## Summary

| Item | Ruling |
|---|---|
| F1, the guarded stylesheet when `docs.public` is false | **Reject.** The change is cosmetic, and only on a page that already fails on base. |
| F2, the `beyond` predicate | **Accept as updated.** A one-loop "nearest clipping ancestor" check replaces Codex's 50-line predicate. Shown on the real page with a mutant. |
| F3, timeout hygiene in `check` | **Accept as updated.** `clearTimeout`, `finally` closing the context, and a bounded wait. Codex's AbortController plumbing is not needed. |
| Comment corrections in `main.py` | **Accept as updated.** Two claims are refuted by the PR's own evidence. The 129-character line is within the file's practice (no change). One test comment is badly wrapped (fixed). |
| Codex's premise: the API sends no CSP for `/docs` | **Confirmed.** Nothing in the PR says otherwise. No change. |
| Missed 1: docs.public now governs seven paths, but `docs/08` and the `_add_docs` docstring say "five", and docs/08 names a test that does not exist | **New finding, fixed.** |
| Missed 2: the PR body repeats the refuted "the Field column keeps its x- names whole" | **New finding.** The coordinator corrects the PR body. |
| Missed 3: the `@import` chain | **Measured, no change.** It adds one round trip to the CSS. The first operation shows 57 ms later (median) at 100 ms latency. |
| Missed 4: other areas checked, no defect | Dark mode, the oauth2-redirect page, `no-cache` without a validator, CI cost of the 40-operation checks, docs/04 and docs/14, the service test, the docs/reviews record |
| Outside this PR | `docs/14:131` says every route but three has the token check, and it omits the docs and problem pages. This predates the PR. The coordinator files it. |

---

## F1: the guarded stylesheet when `docs.public` is false: reject

**Where:** `head/cmapi/src/cmapi/main.py:288-290` (`docs_css`, `dependencies=guard`).

**First, the premise: can private docs work in a browser on base?** No, not without a proxy that adds the token to every
request. On both base and head, `_add_docs` guards `/docs`, `/openapi.json`, `/openapi.yaml`, `/redoc`, `/docs/changelog` and
`/docs/redoc-start.js` with the same `guard`. Only the `/static/*` mounts are unguarded (`main.py:244-247`). `docs/08:98`
states the design: "With `docs.public: false`, a browser gets 401, because a browser sends no bearer token when it loads a page
... To show the pages to signed-in people only, put a proxy that signs in with Keycloak before the Route." So the supported
private-docs browser setup is a proxy that adds the token to every request. That proxy also covers `/docs/swagger.css`.

**Measured.** I ran cmapi's `_add_docs` from each tree (`harness/standin.py`, with a fixed-token stand-in for the bearer
dependency), `docs.public: false`, Chromium (`harness/exp-private.mjs`):

```
{"tree":"base","mode":"none","docs":401,"opblocks":0,"cssRules":0,"responses":["401 /docs"]}
{"tree":"base","mode":"document","docs":200,"opblocks":0,"cssRules":1591,"error":"Failed to load API definition. Errors Hide Fetch error Unauthorized /openapi.j","responses":["200 /docs","200 /static/swagger/swagger-ui.css","200 /static/swagger/swagger-ui-bundle.js","401 /openapi.json"]}
{"tree":"base","mode":"every","docs":200,"opblocks":40,"cssRules":1591,"responses":["200 /docs","200 /static/swagger/swagger-ui.css","200 /static/swagger/swagger-ui-bundle.js","200 /openapi.json"]}
{"tree":"head","mode":"none","docs":401,"opblocks":0,"cssRules":0,"responses":["401 /docs"]}
{"tree":"head","mode":"document","docs":200,"opblocks":0,"cssRules":0,"error":"Failed to load API definition. Errors Hide Fetch error Unauthorized /openapi.j","responses":["200 /docs","401 /docs/swagger.css","200 /static/swagger/swagger-ui-bundle.js","401 /openapi.json"]}
{"tree":"head","mode":"every","docs":200,"opblocks":40,"cssRules":1594,"responses":["200 /docs","200 /docs/swagger.css","200 /static/swagger/swagger-ui.css","200 /static/swagger/swagger-ui-bundle.js","200 /openapi.json"]}
```

- A plain browser (`none`) gets 401 on both trees.
- With a proxy that adds the token to every request (`every`), both trees render all 40 operations, styled.
- In Codex's scenario (`document`: only the page request carries the token), **both** trees fail with "Failed to load API definition"
  (401 on `/openapi.json`), with 0 operations. The only difference is that head's error page has no styles.

**Ruling.** F1 is moot as a defect. Its narrow real form is the styling of an error page that base already shows with no API.
The guard is also consistent: `/docs/redoc-start.js` holds no secret either and is guarded the same way, so `docs.public` governs
every docs path (`DOCS_PATHS`).

**The three fixes compared.**
- (a) Codex's inline `<style>`: it post-edits FastAPI's HTML string. The PR body rejects that string surgery for good reason, and
  it fixes no working setup.
- (b) An unguarded `/docs/swagger.css`: harmless, but it fixes nothing that works. It also adds a second exception to "docs.public
  governs the docs paths".
- (c) A second `<link>`: this also needs string surgery or a copied FastAPI template.

The simplest correct choice is the PR as it stands. **No code change.** I wrote no failing test because no working setup fails.
The measurement above is the evidence.

---

## F2: the `beyond` predicate: accept as updated

**Where:** `head/cmapi-portal-ui/tests/front-door.test.mjs:178` (`scrolls`) and `:183` (`beyond`).

**Is the false pass real for this page?** Yes. The PR's `scrolls(e)` excuses an element if **any** ancestor has `overflow-x:
auto|scroll`. On the real head page at 390 px, every operation open (`r2-outputs/exp-layout-head-base.txt`), Swagger UI has 40
`div.responses-inner` (auto), 252 `pre.example.microlight` (auto) and 93 `article.json-schema-2020-12` (auto). Inside them are
boxes that clip: `select.content-type`, `select.examples-select-element` and `svg`. That is the shape of Codex's case.

**A simpler sound check.** Codex's replacement is about 50 lines and recomputes scrollports. The defect only needs this:
**the nearest ancestor whose `overflow-x` is not `visible` decides.** It must be `auto` or `scroll`, and its own box must end
inside the window. With no clipping box in between, a scroll container's scrollable overflow reaches the element. This is CSS
Overflow 3: a scroll container's scrollable overflow area includes its descendants' boxes, unless a closer box clips them. Codex's
extra cases (scrollLeft offsets, left-edge overflow, nested scrollports) are not reachable by the page's right-edge filter.

**Fix**, `front-door.test.mjs`, replacing line 178 (inside the `p.evaluate`):

```javascript
          // The nearest ancestor that does not let overflow show decides: it must scroll, and it must end inside the window.
          const scrolls = (e) => {
            for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
              const o = getComputedStyle(a).overflowX;
              if (o !== "visible") return (o === "auto" || o === "scroll") && a.getBoundingClientRect().right <= page.clientWidth;
            }
            return false;
          };
```

The assertion message at line 192 becomes:

```javascript
        assert.deepEqual(seen.beyond, [], "these pass the page's right edge, and no box that ends inside the window scrolls to them");
```

The comment at lines 158-162 is rewrapped and says the same thing (see the comment item below). The full diff is in
`r2-outputs/front-door.test.mjs.diff`.

**Test 1: Codex's fixture, run** (`harness/f2-fixture.mjs`). A 400 px box is clipped by a 332 px `overflow:hidden` box inside
the 332 px scrolling `.responses-inner`, at 390 px. A second case puts the same box straight in the scroller.

```
FAIL old     clipped beyond=[] want=["wide"]
ok   nearest clipped beyond=["wide"] want=["wide"]
ok   old     scrolls beyond=[] want=[]
ok   nearest scrolls beyond=[] want=[]
failures: 1
```

The old predicate excuses the clipped box. The new one reports it, and it still accepts the box that a scroll does reach.

**Test 2: on the real page, through nginx, as CI runs it.** Mutant M5 adds a clip inside the scroller:
`.responses-table { display: block; overflow-x: hidden; }` (`mut/*-m5`). The page stays 390 px wide, but the Links column is
cut off and no scroll reaches it.

| Run | 390 px check |
|---|---|
| PR's test, M5 (`front-door-mut_head-m5.txt`) | `ok`. **False pass**: "front door browser checks failed: 0" |
| Reviewer 2's test, M5 (`front-door-mut_r2-m5.txt`) | `FAIL ... these pass the page's right edge, and no box that ends inside the window scrolls to them`, listing `td.response-col_links "No links"` and its rows |
| Reviewer 2's test, unmutated (`front-door-r2.txt`, `front-door-r2-final.txt`) | `ok` at 390 and 1440, "failed: 0" |

On the unmutated head page the new predicate finds 0 elements (46 elements are past the edge, and all are reached by a
scroller). On base it finds the same 564 as the old one. The predicate costs 121 ms per check.

---

## F3: timeout hygiene in `check`: accept as updated

**Where:** `head/cmapi-portal-ui/tests/front-door.test.mjs:121-130` (`check`), `:175` (`timeout: 0`), `:197` (`context.close()`
only on success).

**Is it real?** Yes, though small.
- `waitForFunction(..., { timeout: 0 })` waits forever ([Playwright: "`0` - disables timeout"](https://playwright.dev/docs/api/class-page#page-wait-for-function)).
- If one operation never shows its Extensions table, the check fails only at the outer 300 s, with the message
  "timed out after 300 s", which does not say which wait.
- The page, with 40 operations open, keeps polling through the 1440 check, because nothing closes its context.
- Every passing check leaves a 300 s timer.

Does it matter in CI? Not much. The script ends with `process.exit`, so timers cannot hold the job, and the front-door job has
no `timeout-minutes` (GitHub's default is 360 min). The cost is up to 5 minutes and an unhelpful message on a failure.

**Fix** (minimal). Codex's AbortController and `signal` threading are not needed once the wait is bounded, because the check
body then always settles and its `finally` closes the context.

After line 38:

```javascript
// The wait for every Extensions table ends a minute before the check's own limit, so its error, not the limit's, is shown.
const OPEN_DOCS_WAIT_MS = OPEN_DOCS_TIMEOUT_MS - 60_000;
```

`check`:

```javascript
  async function check(name, fn, timeoutMs = CHECK_TIMEOUT_MS) {
    let timeout;
    const timer = new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error(`timed out after ${timeoutMs / 1000} s`)), timeoutMs); });
    try {
      await Promise.race([fn(), timer]);
      console.log(`  ok   ${name}`);
    } catch (e) {
      failed++;
      console.log(`  FAIL ${name}: ${e.message}`);
    } finally {
      clearTimeout(timeout);
    }
  }
```

The check body is wrapped in `try { ... } finally { await context.close(); }`, re-indented, and the wait is changed to
`{ polling: 1000, timeout: OPEN_DOCS_WAIT_MS }`. The full block is in `r2-outputs/front-door.test.mjs.diff`.

**Test** (`harness/f3-harness.mjs`). It runs the PR's `check` and the fixed one, scaled to an outer limit of 6 s and an inner
limit of 3 s, on a page whose Extensions never all appear:

```
== old (fb24158)
  FAIL stuck: timed out after 6 s
  returned after 6.0 s; open contexts 1
  ok   quick
  after a passing check: pending timers 1
  1.5 s later: open contexts 1
== new (reviewer 2)
  FAIL stuck: page.waitForFunction: Timeout 3000ms exceeded.
  returned after 3.2 s; open contexts 0
  ok   quick
  after a passing check: pending timers 0
  1.5 s later: open contexts 0
```

---

## Comment corrections: accept as updated

**`main.py:353-354`, "Only the Value column wraps: the Field column keeps its x- names whole."** The PR's own screenshot
refutes it. `docs/reviews/2026-11-22-issue-556/screenshots/after-390-patch-extensions.png` shows "x-cmapi-/permission",
"x-/codeSamples" and "x-plugin-/version" broken at their hyphens. Field cells keep `overflow-wrap: normal`, and a hyphen is a
soft wrap opportunity.

**`main.py:358-360`, "so wider windows are unchanged."** Codex says this is refuted. That is only partly right. In its paragraph
the sentence is about the Responses rule, and for that rule it holds: I hashed the committed screenshots, and
`before-1440-capacity-responses.png` and `after-1440-capacity-responses.png` are both `566fdb26…3427`. But read as a statement
about the whole stylesheet it is false: `outputs/layout-1440-before-after.txt` shows 14 Extensions tables changing at 1440 px.
The quote was also cut before its second half. MDN (fetched 2026-11-23,
https://developer.mozilla.org/en-US/docs/Web/CSS/overflow-x): "If content fits inside the element's padding box, it looks the
same as with `visible`, but still establishes a new block-formatting context."

**Line width.** No linter sets one (`cmapi/pyproject.toml` has none, and `ci.yml` runs no Python linter). Base `main.py` already
has 11 of its 30 comment lines over 120 characters, the longest at 137. So the 129-character line, which holds a URL, follows the
file's practice, and that nit is rejected. In the test, however, line 160 is 172 characters in a comment block wrapped at about
120: a sentence was inserted without rewrapping. That one is fixed.

**Fix**, `main.py`, replacing lines 353-360:

```python
# its container; break-word would wrap the text but leave the column as wide. Only the Value cells get the rule; the
# Field cells keep Swagger UI's wrapping, which at 390 px still breaks an x- name at its hyphens. Because the Value
# column's min-content is now small, the auto layout also moves the Field/Value split at 1440 px, by 1 to 5 px
# (docs/reviews/2026-11-22-issue-556/outputs/layout-1440-before-after.txt).
# The Responses table (#558) is a table, not one long string: its Code and Links columns are held at min-width 6em by
# Swagger UI, and an operation that documents a response header nests a three-column headers table in Description, so in
# a 332 px box it needs 349 px. Breaking its words would not make it readable, so its box scrolls sideways instead, the
# usual pattern for a wide table on a phone (https://getbootstrap.com/docs/5.3/content/tables/#responsive-tables). A
# box with overflow-x auto that fits "looks the same as with visible, but still establishes a new block-formatting
# context" (https://developer.mozilla.org/en-US/docs/Web/CSS/overflow-x), and its overflow-y computes to auto; it has
# no height limit, and the 1440 px screenshots of a Responses section are byte-identical before and after.
```

**Fix**, `front-door.test.mjs:158-162`:

```javascript
  // #556: Swagger UI 5.34.1 shows each x- field of an operation in its Extensions table as one JSON string, and without
  // cmapi's stylesheet (/docs/swagger.css) the x-codeSamples value made the table wider than a 390 px page, which then
  // scrolled sideways; so did the Responses table of two operations (#558). With every operation open, the page must be
  // no wider than the window; whatever passes its right edge must be in a box that scrolls sideways, with no box between
  // that cuts it off, and that box must end inside the window; and each x- value of the contract must be on the page
  // whole, wrapped inside the page's width. Rendering 40 open operations takes Chromium a while.
```

Comments cannot have a failing test. The evidence is the PR's own screenshot and layout file, cited above.

---

## Codex's premise: the API sends no CSP for `/docs`: confirmed

`curl -s -D - http://127.0.0.1:18601/docs` against head's `_add_docs` returns no `Content-Security-Policy` and no
`Cache-Control`. FastAPI 0.115.6's `get_swagger_ui_html` returns a plain `HTMLResponse`. Only `/redoc` sets `REDOC_CSP`
(`main.py:299-305`). The CSP that allows the stylesheet and the `@import` is the front door's `$cmapi_csp_docs`
(`cmapi.conf.template:53-54`, `style-src 'self' 'unsafe-inline'`). The PR body says "its CSP" about the front door's
`location /docs/`, which is accurate. No comment or doc in the diff claims an API CSP for `/docs`. **No change.**

---

## What reviewer 1 missed

### M1. docs.public now governs seven paths; docs/08 and the docstring say "five": fixed

- `docs/08-code-status.md:91` says "the five paths need a valid bearer token ... `docs.enabled: false` removes all five". It names
  the proof as `test_docs_public_false_puts_the_five_paths_behind_a_token`, a test that does not exist; the test is
  `test_docs_public_false_puts_the_docs_paths_behind_a_token` (`test_api_docs.py:351`).
- `main.py:236-238` (`_add_docs` docstring) lists five paths and says "each of the five".
- `DOCS_PATHS` holds seven since this PR. Six were already true on base (`redoc-start.js`), so part of this predates the PR. The PR
  adds the seventh and edits the next row of docs/08 (l.85), so it is in scope now.

**Fix**, `docs/08-code-status.md:91`, first and third cells:

```markdown
| `docs.public` | With `docs.public: false` in `instance.yaml`, the seven docs paths (`/docs`, `/redoc`, `/openapi.json`, `/openapi.yaml`, `/docs/changelog`, `/docs/redoc-start.js`, `/docs/swagger.css`) need a valid bearer token. Without one they answer 401 with `WWW-Authenticate`. `docs.enabled: false` removes all seven | `test_docs_public_false_puts_the_docs_paths_behind_a_token`, `test_docs_enabled_false_serves_none_of_them` |
```

**Fix**, `main.py:236-238`:

```python
    """/docs, /redoc, /openapi.json, /openapi.yaml and /docs/changelog (docs/01, "API documentation"), with the files of the
    two pages: /docs/redoc-start.js and /docs/swagger.css.

    Public unless instance.yaml says docs.public: false; then each of the seven needs a valid bearer token and answers
```

**Test.** `test_docs_public_false_puts_the_docs_paths_behind_a_token` already iterates `DOCS_PATHS` (seven), and it passes
(below). The fix is to the docs, so the check is the test name now matching the file. The docstring adds one line to `main.py`.
Every `docs/14`, `docs/15` and `docs/16` citation into `main.py` names lines 120-192, before the shift (`citations.lock.json`),
so `test_doc_citations` is not affected. That is inferred: `scripts/doc-citations.py --check` needs `git ls-files`, and I did not
make the export a git repository.

### M2. The PR body repeats the refuted Field-column claim

The PR body ("The fix", first bullet) says: "Only the Value column wraps; the Field column keeps its `x-` names whole." The
replacement text for the coordinator:

> Only the Value cells get `overflow-wrap: anywhere`. The Field cells keep Swagger UI's wrapping, which at 390 px still breaks an
> `x-` name at its hyphens (see the after-390 screenshot).

### M3. The `@import` chain and `no-cache`: measured, no change

`harness/exp-import.mjs`, cold cache, 5 runs each, median, Chromium with CDP latency emulation:

```
base rtt=0 ms:   {"cssStart":8,"cssEnd":19,"jsEnd":29,"firstOp":1966}
head rtt=0 ms:   {"cssStart":17,"cssEnd":23,"jsEnd":32,"firstOp":1993}
base rtt=100 ms: {"cssStart":112,"cssEnd":228,"jsEnd":235,"firstOp":2265}
head rtt=100 ms: {"cssStart":226,"cssEnd":334,"jsEnd":234,"firstOp":2322}
```

- The `@import` makes the bundle CSS start one round trip later (+114 ms at 100 ms latency).
- The CSS then ends about 100 ms after the JS bundle, so it is on the critical path.
- The first operation shows 57 ms later (median; `firstOp` includes Playwright's polling, so treat it as approximate) out of about
  2.3 s.
- `/docs/swagger.css` sends `Cache-Control: no-cache` with no `ETag` or `Last-Modified` (measured), so every load refetches its
  ~200 bytes in full, as `/docs/redoc-start.js` already does.

The only fix would be option (c) above, which costs HTML surgery. Not worth it.

### M4. Other areas checked, no defect

- **Dark mode.** The 5.34.1 bundle CSS has 272 `.dark-mode` selectors and no `prefers-color-scheme`. FastAPI's page never sets
  `.dark-mode` (`grep -c dark-mode` on `/docs`: 0). The two rules set no colour. Nothing to do.
- **The oauth2-redirect page.** `get_swagger_ui_oauth2_redirect_html` links no stylesheet (`grep -c "stylesheet\|<style"`: 0), and
  it stays unguarded. It is not affected.
- **CI cost of the 40-operation checks.** CI run 45116977360: the browser step took 86 s, against 11 s on main's run 44989513636.
  The two new checks took 37.0 s each (05:21:26 to 05:22:03 to 05:22:40). The front-door job has no `timeout-minutes`, so GitHub's
  default of 360 min applies, and the job took 3 min 56 s. Locally, the time is all Swagger UI rendering after the clicks
  (85-87 s at 390, 1440 and on base). The measurement takes 0.2 s. Acceptable. Issue #556's proof asks for 1440 px too, so I
  kept that check.
- **docs/04, docs/08, docs/14.** docs/04:49 lists `/docs/swagger.css` among the routes not in the OpenAPI document. That is
  correct (`include_in_schema=False`). docs/08:85 is correct. docs/14's route table covers `/api/v1` permissions only and lists no
  docs route, so it is consistent. Its three citation relocations into `test_review_c_authz.py` (+2 lines) match the file.
- **The service test.** `test_swagger_ui_loads_the_bundles_stylesheet_through_cmapis` checks strings in the constant. The part
  that matters is the order (`@import` first, or the browser drops it) and the single `<link>`; the layout proof is the browser
  check. I tested whether a broken `@import` URL escapes the suite (mutant `*-imp`: `swagger-ui-missing.css`). It does not: the
  PR's own browser suite fails three checks (`front-door-mut_head-imp.txt`). The console shows "Refused to apply style ...
  MIME type ('application/json')", which the CSP console filter catches, and the page is 582 px wide. I had added an `@import`
  assertion, and **I retract it**: it duplicates that coverage, and on a failed import it errors with a SecurityError instead of
  a clear message. It is not in the final diff.
- **The docs/reviews record.** I checked its claims against the files.
  - "Responses screenshots at 1440 are byte-identical": true (same SHA-256), though no output file records it.
  - "Chromium took 85 s": I measured 85-87 s on this Mac.
  - "CI ... 37 s": true.
  - The PR body says `.responses-inner` "never scrolls vertically". "Never" is stronger than the evidence, which shows only that it
    has no height limit. My comment text above says only what was measured.
  - I found no other overclaim.

### Outside this PR (the coordinator files it)

`docs/14-authorization.md:131`: "Each route except `/healthz`, `/readyz` and `/api/v1/version` has the token check as a
dependency". The problem pages (`/problems`, `/problems/{code}`), `/docs/oauth2-redirect`, and with `docs.public` true every docs
path also answer without a token (`test_review_c_authz.py` `PUBLIC`). This predates the PR.

---

## What I ran

| Run | Where | Result |
|---|---|---|
| `test_api_docs.py` + `test_review_c_authz.py` on head (copy) | PostgreSQL 16, `127.0.0.1:55432` (`cmapi-test-pg`), FastAPI 0.115.6 venv | 39 passed |
| The same on r2 (all my fixes) | same | 39 passed (`r2-outputs/service-docs-authz-r2.txt`) |
| `front-door.test.mjs` on r2 | native nginx 1.30.6 (`ob1-run6/nginx`), Playwright 1.64.1 Chromium, `cmapi-tools docs-assets` bundles, r2's `npm run build` | failed: 0 (`front-door-r2.txt`; re-run on the final test: `front-door-r2-final.txt`) |
| Mutant M5 with the PR's test, and with r2's test | same | PR's: failed 0 (false pass); r2's: 390 fails on `beyond` |
| Mutant import-URL with the PR's test, and with r2's test | same | both fail 3 checks (so no new assertion is needed) |
| F2 fixture, F3 harness, private-docs, layout and `@import` experiments | stand-ins on 127.0.0.1:18601-18604 | outputs quoted above |

## What I did not run

- The full service suite. I ran only the two affected files; CI's `service` job runs the rest.
- `scripts/doc-citations.py --check` and `test_doc_citations.py`: they need a git checkout. That they still pass is inferred from
  the cited line ranges.
- `deploy/tests/front-door-test.py --nginx`. My changes do not touch nginx or the route list.
- Firefox and WebKit, CRC, kind, and the image build.
- The CI `front-door` job on r2's changes. Nothing was pushed.

## For the coordinator to apply

- `r2-outputs/front-door.test.mjs.diff`: F2, F3, and the comment rewrap.
- `r2-outputs/main.py.diff`: the comment corrections and the docstring (M1).
- `r2-outputs/docs-08.diff`: M1.
- The PR body: M2.
- File the docs/14:131 issue (outside this PR).
