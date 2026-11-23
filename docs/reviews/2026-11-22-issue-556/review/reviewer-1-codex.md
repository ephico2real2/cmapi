# PR #559 — adversarial review, reviewer 1

Reviewed exported head `fb24158` against base `5c01876`. No Git commands, repository changes, or pushes were made.

**Verdict:** the two CSS rules address the reported overflow mechanisms. I found a conditional private-docs styling regression and weaknesses in the browser test. I did **not** establish that ordinary Swagger response controls are clipped by this patch.

**Report could not be saved:** both filesystem creation and `apply_patch` were denied for `/Users/olasumbo/gitRepos/workbench/cmapi/review-559/`. The runtime permits writes only to the configured workspace and temporary directories, and escalation is disabled. Your export authorization does not change that runtime restriction. The full report follows.

## Claim 1: selector scope

**Confirmed for the standard Parameters, Request body, Responses, and Models/Schemas renderers, with a callback qualification.**

In Swagger UI **v5.34.1**:

- [`operation-extensions.jsx`, lines 7–26](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/components/operation-extensions.jsx#L7) renders `.opblock-section > .table-container > table > tbody`.
- [`operation-extension-row.jsx`, lines 7–10](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/components/operation-extension-row.jsx#L7) renders two cells, ending with:

  ```jsx
  <td>{ JSON.stringify(xNormalizedValue) }</td>
  ```

  Thus `td:last-child` selects Value.

- [`parameters/parameters.jsx`, lines 159–162](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/components/parameters/parameters.jsx#L159) inserts `.parameters-container` between `.opblock-section` and `.table-container`. The direct-child selector excludes its table.
- The same file, lines 202–220, puts Request body content inside `.opblock-description-wrapper`, not the required direct-child table container.
- [`responses.jsx`, lines 87–115](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/components/responses.jsx#L87) uses `.responses-wrapper > .responses-inner > table`.
- [`json-schema-5/components/models.jsx`, lines 175 onward](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/plugins/json-schema-5/components/models.jsx#L175) renders a `section.models`, containing model items rather than that operation-section hierarchy.

**Qualification:** “never Callbacks” is too absolute if it includes Extensions tables belonging to callback operations. [`oas3/components/callbacks.jsx`, lines 24–34](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/plugins/oas3/components/callbacks.jsx#L24) renders ordinary `OperationContainer` components. Their own Extensions tables can match. Their Parameters and Responses tables remain excluded.

This is appropriate structural targeting for the pinned version, not a semantic guarantee against arbitrary plugins or future markup changes.

## Claim 2: `anywhere` versus `break-word`

**Confirmed.**

[CSS Text 3 §5.4](https://www.w3.org/TR/css-text-3/#overflow-wrap-property) explicitly distinguishes their intrinsic-size behavior:

> “Soft wrap opportunities introduced by anywhere are considered when calculating min-content intrinsic sizes.”

For `break-word`, those opportunities do not contribute to min-content sizing.

That distinction matters for an automatically sized table: reducing the Value cell’s minimum intrinsic contribution permits the column and table to shrink. [`_table.scss`, lines 4–8](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/style/_table.scss#L4) gives tables `width: 100%` without selecting fixed layout. [CSS table layout §17.5.2.2](https://www.w3.org/TR/CSS22/tables.html#auto-table-layout) describes the role of minimum cell and column widths.

The comment’s explanation is correct for this case. It should not imply that `break-word` universally prevents every table from shrinking; other width constraints or layout algorithms can change the outcome.

The supplied mutation log also reports failure with `break-word`: 647 px document width at a 390 px viewport. That is author-supplied evidence, not a measurement I reproduced.

## Claim 3: `.responses-inner` cannot clip or trap anything

**The unconditional claim is refuted; a concrete ordinary-control regression is not demonstrated.**

The wrapper contains substantially more than a static response table:

| Content | v5.34.1 evidence | Consequence |
|---|---|---|
| Live “Try it out” result | [`responses.jsx` 101–114](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/components/responses.jsx#L101) | The rule also affects live-response content. |
| Documented Responses table | Same file, 115–155 | Intended horizontal scrolling applies here. |
| Examples selector | [`response.jsx` 220–239](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/components/response.jsx#L220) | It is inside the scroll container. |
| Example/schema model | Same file, 243–251 | Expanded model content participates in its overflow. |
| Response headers | Same file, 262–267 | The nested headers table is inside Description. |

[`live-response.jsx`, lines 83–143](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/components/live-response.jsx#L83) includes the request snippet, URL, server-response table, response body, headers, and duration.

However:

- **Examples dropdown:** [`examples-select.jsx`, lines 110–135](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/components/examples-select.jsx#L110) uses native `<select>` and `<option>` elements. It is not an absolutely positioned HTML dropdown menu. A generic “responsive tables clip dropdown menus” warning does not establish failure here.
- **Model expander:** [`model-collapse.jsx`, lines 78–96](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/plugins/json-schema-5/components/model-collapse.jsx#L78) inserts expanded children in normal flow. Expansion can increase the wrapper’s height.
- **Vertical scrollbar:** `overflow-y: visible` **does compute to `auto`** when `overflow-x` is `auto`. But [`_layout.scss`, lines 601–618](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/style/_layout.scss#L601) gives `.responses-inner` padding without a height or maximum-height constraint. A vertical scrollbar is possible, not inevitable.
- **Focus outlines:** ink extending outside the clipping boundary can be clipped. The existing 20 px wrapper padding provides room for ordinary outlines; no actual focus-outline failure was reproduced.
- **Live response body:** it is affected, but scrollable content is not automatically inaccessible or trapped. Its reachability and keyboard behavior require an interaction test.

[CSS Overflow 3 §3.1](https://www.w3.org/TR/css-overflow-3/#overflow-properties) establishes clipping, coupled computed values, and the new formatting context. These are real effects even when no scrollbar is visible.

**Recommendation:** retain the rule unless interaction testing demonstrates a defect. Do not claim that it cannot affect clipping or that every browser behaves identically.

## Claim 4: import resolution, CSP, and request cost

**Resolution and CSP compatibility: confirmed for public docs.**

`/static/swagger/swagger-ui.css` is root-relative. From `/docs/swagger.css`, it resolves to the same origin’s `/static/swagger/swagger-ui.css`, not `/docs/static/...`. See [CSS Values 3 §3.4.1](https://www.w3.org/TR/css-values-3/#relative-urls).

There is an important correction to the question’s premise:

- `head/cmapi/src/cmapi/main.py:278–285` returns FastAPI’s Swagger HTML without adding a CSP.
- The API explicitly adds `REDOC_CSP` only to `/redoc`, at lines 299–305.
- FastAPI 0.115.6’s [`get_swagger_ui_html`, lines 109–148](https://github.com/fastapi/fastapi/blob/0.115.6/fastapi/openapi/docs.py#L109) returns an ordinary `HTMLResponse` without a CSP header.

Therefore, **there is no API-defined `/docs` CSP in the inspected implementation**.

Through nginx, `$cmapi_csp_docs` permits same-origin styles with `style-src 'self' 'unsafe-inline'`. Both CSS URLs satisfy `'self'`. The import does not require `'unsafe-inline'`. See [CSP 3 stylesheet checks](https://www.w3.org/TR/CSP3/#directive-style-src-elem).

**Request-chain cost: real, but unmeasured here.**

The imported bundle is discovered after fetching the wrapper stylesheet:

```text
HTML → swagger.css → swagger-ui.css
```

That adds a stylesheet discovery dependency and an extra request compared with the base implementation. Cache state, revalidation, connection reuse, and latency determine its practical impact.

Precisely:

- The wrapper explicitly sends `Cache-Control: no-cache`.
- The mounted static bundle does not receive an explicit `Cache-Control` from this route code.
- `no-cache` permits storage but requires validation before reuse; it does not mean `no-store`.

**Simpler alternatives exist.**

FastAPI 0.115.6 accepts one `swagger_css_url`; it has no additional-CSS parameter. `swagger_ui_parameters` is JavaScript configuration, not a CSS injection mechanism. See its [signature, lines 24–95](https://github.com/fastapi/fastapi/blob/0.115.6/fastapi/openapi/docs.py#L24).

Either a second link after the bundle link, or an inline style block after it, avoids the import chain. An inline block is allowed by the inspected nginx docs CSP.

## Finding F1 — P2: bearer-guarded stylesheet changes private-docs asset behavior

**Location:** `head/cmapi/src/cmapi/main.py:287–289`; associated expectations in `head/cmapi/tests/service/test_api_docs.py:35–38`.

**What is wrong:** the new stylesheet requires the bearer dependency when `docs.public` is false. A browser stylesheet request does not automatically copy a bearer header supplied specifically to the document request.

**Failure scenario:** an authenticated document-only loader obtains `/docs` with a bearer header, then renders that document at the API origin. Its ordinary stylesheet fetch lacks that header and receives 401. Since the bundle CSS is now behind an import in that refused stylesheet, **all Swagger styling is lost**, not merely the two overrides.

This is conditional. A proxy, extension, or browser test context that injects authorization into **every** request can make the stylesheet load.

**Comparison with existing behavior:**

- `/static/swagger/*` is mounted without `guard` at lines 246–247.
- `/docs/redoc-start.js` already uses `guard` at lines 307–309.
- Thus the new route follows ReDoc’s existing pattern but regresses Swagger’s previously public CSS loading.
- Private `/openapi.json` also needs authentication; fixing CSS alone does not solve private-docs bootstrap generally.

### Full proposed fix

Keep the protected HTML route, load the public bundle directly, and append these non-sensitive overrides inline. This also removes the import waterfall.

Replace `docs()` and remove the `docs_css()` route:

```python
    @app.get("/docs", include_in_schema=False, dependencies=guard)
    def docs() -> Response:
        if not swagger_dir.exists():
            return missing("Swagger UI")
        page = get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=f"cmapi ({ctx.cfg.name}) - API docs",
            oauth2_redirect_url="/docs/oauth2-redirect",
            swagger_js_url="/static/swagger/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger/swagger-ui.css",
            swagger_favicon_url="/static/swagger/favicon-32x32.png",
            init_oauth=app.swagger_ui_init_oauth,
            swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
        )
        markup = page.body.decode("utf-8").replace(
            "</head>",
            f"<style>{SWAGGER_CSS_TEXT}</style>\n</head>",
            1,
        )
        return HTMLResponse(markup)
```

Replace the stylesheet constants with:

```python
# Extensions values contribute their arbitrary wrapping opportunities to
# min-content sizing. Responses retain their table layout and scroll locally.
SWAGGER_CSS_TEXT = """
.opblock-section > .table-container > table > tbody > tr > td:last-child {
  overflow-wrap: anywhere;
}

.responses-inner {
  overflow-x: auto;
}
"""
```

Remove `/docs/swagger.css` from `DOCS_PATHS` and the nginx route-check list. Replace the last service test with:

```python
def test_swagger_styles_work_with_document_only_authorization(
    bundles, test_config, tmp_path, fresh_db, keys, monkeypatch
):
    config = _config(test_config, tmp_path, {"public": False})
    with build_world(config, keys, monkeypatch) as (client, *_):
        token = {
            "Authorization": (
                f"Bearer {keys.token('ada', roles=['cmapi-viewer'])}"
            )
        }
        page = client.get("/docs", headers=token)
        assert page.status_code == 200
        assert client.get("/docs").status_code == 401

        stylesheets = re.findall(
            r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"',
            page.text,
        )
        assert stylesheets == ["/static/swagger/swagger-ui.css"]
        for url in stylesheets:
            response = client.get(url)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/css")

        assert "<style>" in page.text
        assert "overflow-wrap: anywhere;" in page.text
        assert "overflow-x: auto;" in page.text
        assert page.text.index('href="/static/swagger/swagger-ui.css"') \
            < page.text.index("<style>")
```

**Before/after:** before, the unauthenticated linked stylesheet request is 401; after, the linked bundle is 200 and the overrides arrive inside the authenticated document.

This test was not executed because FastAPI and the service dependencies are unavailable.

## Finding F2 — P2: `beyond` can excuse clipped response content

**Location:** `head/cmapi-portal-ui/tests/front-door.test.mjs:178–184`.

**What is wrong:** `scrolls(e)` treats any ancestor whose computed `overflowX` contains `auto` or `scroll` as sufficient evidence of reachability. It does not establish:

- that the ancestor actually scrolls;
- that an intervening ancestor does not clip the content;
- that the scrollport itself fits the viewport.

**Failure scenario:** inside `.responses-inner`, insert a 332 px `overflow: hidden` wrapper around a 349 px response table. The page can remain 390 px wide. Every overflowing response descendant is excused because `.responses-inner` has `overflow-x: auto`, even though the intermediate wrapper makes the right-hand content inaccessible. The Extensions-only `unseen` check does not inspect those response cells.

An oversized nested scroll container can likewise be excused. That alone does not prove inaccessible content: an outer container might scroll the whole inner container into view. The defect is that the predicate proves neither case.

**Can the original defect pass unchanged?** The root `scrollWidth` assertion should reject the reported 539 px document at a 390 px viewport. The supplied mutation logs support that it catches removal of either rule. The weakness concerns clipping-based or nested-container false fixes.

### Full proposed fix

Replace `scrolls` with this conservative reachability predicate, and change the `beyond` filter to call it:

```javascript
const reachable = (e) => {
  const viewport = document.documentElement.clientWidth;
  const rect = e.getBoundingClientRect();
  let left = rect.left;
  let right = rect.right;
  const epsilon = 1;

  for (
    let a = e.parentElement;
    a && a !== document.body;
    a = a.parentElement
  ) {
    const style = getComputedStyle(a);
    const box = a.getBoundingClientRect();
    const start = box.left + a.clientLeft;
    const end = start + a.clientWidth;
    const outside = left < start - epsilon || right > end + epsilon;

    if (/^(hidden|clip)$/.test(style.overflowX) && outside) {
      return false;
    }

    if (/^(auto|scroll)$/.test(style.overflowX) && outside) {
      if (
        box.left < -epsilon ||
        box.right > viewport + epsilon ||
        a.scrollWidth <= a.clientWidth
      ) {
        return false;
      }

      const contentStart = start - a.scrollLeft;
      const contentEnd = contentStart + a.scrollWidth;
      if (
        left < contentStart - epsilon ||
        right > contentEnd + epsilon
      ) {
        return false;
      }

      // Reachable content is viewed through this scrollport.
      left = start;
      right = end;
    }
  }

  return left >= -epsilon && right <= viewport + epsilon;
};

const beyond = [...document.querySelectorAll("#swagger-ui *")]
  .filter((e) =>
    e.getBoundingClientRect().right > page.clientWidth &&
    !reachable(e)
  )
  .map((e) =>
    `${e.tagName.toLowerCase()}.${[...e.classList].join(".")} ` +
    `"${e.textContent.slice(0, 40)}"`
  )
  .slice(0, 10);
```

Use `beyond` in the returned measurement object.

### Regression test

A small browser fixture isolates the false positive:

```javascript
await p.setViewportSize({ width: 390, height: 900 });
await p.setContent(`
  <style>
    body { margin: 0; }
    #swagger-ui { width: 390px; }
    .responses-inner { width: 332px; overflow-x: auto; }
    .clip { width: 332px; overflow: hidden; }
    .wide { width: 349px; height: 30px; }
  </style>
  <div id="swagger-ui">
    <div class="responses-inner">
      <div class="clip"><div class="wide">response content</div></div>
    </div>
  </div>
`);
```

Evaluate the production measurement logic and assert that `.wide` is reported as unreachable. The old predicate excuses it; the replacement rejects the clipping ancestor.

I executed a Node model of the existing predicate: it returned `true` for an oversized inner scrollport under an `auto` ancestor. The browser fixture itself was not executed.

## Claim 6, continued: JSON ordering

**Confirmed for this version and the present contract. No ordering finding.**

The same `JSON.stringify` function is used on both sides, and upstream preserves object order:

- [`spec/reducers.js`, lines 44–54](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/plugins/spec/reducers.js#L44) converts JSON and resolved subtrees using `fromJSOrdered`.
- [`utils/index.js`, lines 48–66](https://github.com/swagger-api/swagger-ui/blob/v5.34.1/src/core/utils/index.js#L48) recursively constructs `OrderedMap` values.
- `OperationExtRow` converts the immutable value with `toJS()` before stringifying.

The stand-in serves the committed contract used by `contractRows`. Sorting the outer row lists removes row-order differences while retaining JSON property order inside each value.

Executed contract inspection found **40 operations, 159 extension rows, zero falsy extension values**. Upstream’s normalization of falsy extension values to `null` could matter for future fixtures, but is not an introduced defect here.

## Finding F3 — P2: unbounded inner wait and uncancelled timeout work

**Location:** `head/cmapi-portal-ui/tests/front-door.test.mjs:121–129, 175, 197`.

**What is wrong:**

- `waitForFunction(..., {timeout: 0})` disables its timeout.
- The outer `Promise.race` stops awaiting the check but does not cancel its browser work.
- Successful checks leave their timeout handles scheduled.
- The browser context closes only on the successful path.

[Playwright documents `timeout: 0` as disabling the timeout](https://playwright.dev/docs/api/class-page#page-wait-for-function).

**Failure scenario:** one operation never renders its Extensions heading. After 300 seconds the helper records failure and starts the next check while the old page continues polling. Its context remains alive until later browser cleanup, increasing load and potentially causing cascading failures.

The script is **not necessarily permanently hung**: the outer timer bounds each check, and final browser closure or `process.exit` terminates remaining work. Calling this an unconditional infinite suite hang would be inaccurate.

### Full proposed fix

Replace `check` with:

```javascript
async function check(name, fn, timeoutMs = CHECK_TIMEOUT_MS) {
  const controller = new AbortController();
  let handle;

  const timer = new Promise((_, reject) => {
    handle = setTimeout(() => {
      controller.abort();
      reject(new Error(`timed out after ${timeoutMs / 1000} s`));
    }, timeoutMs);
  });

  try {
    await Promise.race([fn(controller.signal), timer]);
    console.log(`  ok   ${name}`);
  } catch (e) {
    failed++;
    console.log(`  FAIL ${name}: ${e.message}`);
  } finally {
    clearTimeout(handle);
  }
}
```

For each new Swagger layout check, accept `signal`, register context closure immediately after creating the context, and put its existing navigation, expansion, measurement, and assertions inside `try/finally`:

```javascript
const closeOnAbort = () => {
  void context.close().catch(() => {});
};
signal.addEventListener("abort", closeOnAbort, { once: true });

try {
  await p.goto(`${origin}/docs`);
  await shows(p, ".opblock", violations);
  const operations = await p.locator(".opblock").count();

  await p.evaluate(() => {
    document.querySelectorAll(".opblock-summary-control")
      .forEach((button) => button.click());
  });

  await p.waitForFunction(
    (expected) =>
      [...document.querySelectorAll(".opblock-section-header h4")]
        .filter((heading) => heading.textContent === "Extensions")
        .length >= expected,
    operations,
    { polling: 1000, timeout: OPEN_DOCS_TIMEOUT_MS - 10_000 }
  );

  // Keep the existing measurement and assertions here.
} finally {
  signal.removeEventListener("abort", closeOnAbort);
  await context.close();
}
```

The callback signature becomes `async (signal) => { ... }`. Existing unrelated callbacks can continue ignoring the argument.

### Regression test

Use a page whose expected heading never appears and a short check timeout. Assert that:

1. the check reports failure;
2. its context closes immediately;
3. a subsequent check has no leftover page;
4. a successful check leaves no scheduled timeout.

I executed the existing helper under an injected timer implementation. It left **one timer after success**, and its underlying work **continued after timeout**. The browser cancellation test remains unexecuted.

## Claim 7: comments, desktop changes, citations, and browser support

### Desktop “unchanged” claim: refuted

**Location:** `head/cmapi/src/cmapi/main.py:359–360`.

The export’s `docs/reviews/2026-11-22-issue-556/outputs/layout-1440-before-after.txt` reports:

- 14 Extensions sections with changed column allocations;
- column changes of approximately 1–5 px;
- three sections shrinking from 343 px to 325 px.

That is consistent with changing a cell’s intrinsic size contribution, which can change automatic column allocation even when the table already fits.

It is not evidence of a harmful desktop regression. It does contradict “wider windows are unchanged.”

The MDN quotation is real, but applies to fitting overflow content—not to the separate `overflow-wrap` rule. [MDN also explicitly notes that `auto` still establishes a formatting context](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/overflow-x#auto).

**Full comment replacement:**

```python
# Responses retain their table layout and scroll horizontally when needed.
# Their wrapper also becomes a formatting context, and overflow-y computes to
# auto. The Extensions wrapping rule can change column allocation at desktop
# widths because it changes the Value cells' min-content contributions.
```

**Verification:** the supplied before/after measurement already disproves the old assertion. No pixel-equality test should be added as a requirement unless unchanged desktop geometry is actually intended.

### Width and wording nits

- `main.py:359` is **129 characters**, measured.
- `front-door.test.mjs:160` also contains an unnecessarily long comment.
- “Field column keeps its x- names whole” overstates the guarantee. The new arbitrary wrapping rule excludes Field, but ordinary wrapping at existing break opportunities remains possible.

Suggested replacement:

```python
# Apply arbitrary wrapping only to Value cells. Field cells retain Swagger
# UI's normal wrapping behavior.
```

The `@import` cascade citation is correct: imported rules participate at the import location. See [MDN `@import`](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@import#description). The CSS Text citation is also correct.

These are documentation/style issues, not separate functional blockers.

### Firefox and Safari support: confirmed for supported versions

MDN’s compatibility data records `overflow-wrap: anywhere` support from:

- **Firefox 65**
- **Safari 15.4**, including iOS Safari
- Chromium 80

See [MDN compatibility data, `anywhere`](https://github.com/mdn/browser-compat-data/blob/main/css/properties/overflow-wrap.json#L92).

Current Firefox and Safari therefore support the value. Safari versions before 15.4 do not. Replacing it with `break-word` is not an equivalent intrinsic-sizing fallback.

Compatibility data does not establish that this exact table layout and all interactions have been tested across engines. The new browser test imports Chromium only.

## Executed checks and limitations

Executed without importing or modifying repository code:

- Node syntax check of `front-door.test.mjs`: passed.
- Python AST parsing of `main.py`, `test_api_docs.py`, and `front-door-test.py`: passed.
- Contract inspection: 40 operations, 159 extension rows, no falsy extension values.
- Isolated execution of `_add_docs` with mock framework objects: confirmed private guards on the CSS and ReDoc starter, CSS `no-cache`, and no explicit Swagger-page CSP.
- Node reproduction of the ancestor-predicate weakness.
- Node reproduction of pending successful-check timers and work continuing after timeout.

Not executed:

- Full service tests: FastAPI is unavailable.
- Front-door browser suite: export has no `node_modules`; nginx is unavailable.
- Firefox/WebKit interaction checks.
- Independent live-cluster or desktop pixel measurements.

Swagger source was fetched read-only from GitHub at **tag `v5.34.1`**. Supplied mutation and layout logs were inspected as author evidence, not represented as independently reproduced results.

Codex session ID: 01a206eb-bf95-7b81-85a8-22c51e0177bd
Resume in Codex: codex resume 01a206eb-bf95-7b81-85a8-22c51e0177bd
