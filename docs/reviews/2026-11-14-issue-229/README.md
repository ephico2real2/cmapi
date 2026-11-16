# #229 BUG-57, #230 SEC-11 and #235 SEC-12: ReDoc 3 on `/redoc`

OB1 run 6 (Opus 5.5 at high) wrote the fix, the tests and this record. It is not a change to auth, tokens, admission,
secrets or deletion, so it has no second reader (`OB1-PROMPT.md`, "How to work").

## What was wrong

- **#229.** `/redoc` showed an empty page. FastAPI's `get_redoc_html` loads the bundle with a classic
  `<script src>`. The ReDoc 3 standalone bundle is an ES module: it ends with `export{RedocStandalone,hydrate,init};`
  and reads `import.meta.url`. Chromium stopped it with `Cannot use 'import.meta' outside a module`, and
  `.api-content` did not appear. Measured on this Mac on 2026-11-14, Playwright 1.64.1 with its Chromium, against
  cmapi's own route functions and the bundle at the Containerfile's pin.
- **#230.** ReDoc 3.0.1 bundles DOMPurify 3.4.16 (the bundle names `.version=\`3.4.16\``). GitHub advisory
  GHSA-cg2g-xh64-v4q7 (critical, 2026-10-22) covers DOMPurify `>= 3.4.4, <= 3.4.16`. ReDoc 3.1.0 bundles 3.4.17.

## The decision

| Option | Result |
|---|---|
| A module script, `<script type="module" src=...>`, on cmapi's own page (chosen) | The bundle runs. With #235's start module and the policy above, the page makes no request to another host |
| Import `init` from the bundle in an inline module | Works too, but an inline script needs `'unsafe-inline'` or a hash in the Content-Security-Policy, and the page gets more code |
| Pin ReDoc 2 again | ReDoc 2 is a classic script, so FastAPI's page works, but it gives up the 3.x fixes, the security fix of #230 among them |

The pin moves to ReDoc 3.1.0. Its tarball's SHA-512 equals npm's `dist.integrity`
(`sha512-hYsN0ABpoDAPE2+A+mNvs6DDTzhPlJaIeJK2jCFgvxtiXHpWzBXqNBWWKUNq/VLBMZGnyT4qiQnODVWEX031uQ==`), and its SHA-256 is
`d6f4b0c0abb970724c112473ace8229fd1cc3c78be4ca110841de4c640de15a9`. 3.1.0 was published on 2026-11-05, nine days before
this pin. The other pins wait 14 days after a release; this one does not, because it is the fix of a security advisory.

## #235 SEC-12: no telemetry to Redocly

Once the page runs, ReDoc 3 sends usage telemetry. Measured in Chromium against `/redoc` with ReDoc 3.1.0 and no
Content-Security-Policy, scrolling and one click: `POST https://otel.cloud.redocly.com/v1/traces` and
`GET https://cdn.redoc.ly/redoc/logo-mini-full.svg`. In the bundle, the telemetry client's collector defaults to
`https://otel.cloud.redocly.com/v1/traces`, and the client is off only with the option `disableTelemetry`
(`options?.disableTelemetry`). The bundle's own start on `<redoc spec-url>` passes no options (`init(t,{},e)`).

| Option | Result |
|---|---|
| A start module of cmapi's own, `/docs/redoc-start.js`, which imports `init` and passes `disableTelemetry: true` (chosen) | No telemetry. No inline script, so the docs' Content-Security-Policy at the front door (#226) stays as it is |
| An inline module script with the same call | Needs `'unsafe-inline'` for module scripts or a hash for each instance |
| Rely on the front door's CSP (`connect-src`) alone | The request is blocked behind the front door, but not on a direct connection to the API (a port-forward); the page should not try |

Measured after the fix, the same run: no request to `otel.cloud.redocly.com`, `.api-content` shown, no page error. The
attribution logo still loads from `cdn.redoc.ly`: no option removes it. The front door's CSP blocks it (`img-src`), and
the component hides the image when it fails to load. The bundle names two more hosts, `cdn.redocly.com/icons/...`, which
this page did not request.

## Fable's review of PR #231, and the rulings

Fable 5.2 reviewed head `62e3f33` (`fable-review.md`). The coordinator ruled; OB1 run 6 applied the accepted findings.

| Finding | Ruling | Done |
|---|---|---|
| F1 (high): the page asks two other hosts, one with telemetry | Accepted, with #235's start module kept (the 3.1.0 README names the option `disableTelemetry`) | A Content-Security-Policy on the `/redoc` response, in the app, so it holds without the front door: `default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:`. Fable's test `test_the_redoc_page_asks_no_other_host`, with its telemetry line reading the start module instead of a tag attribute. The front door's policy for `/redoc` (#226) is the same string |
| F2 (low): a docstring named a browser test that is in no branch | Accepted | The docstring says the render was done by hand (this folder) and that the front door's browser check (#226) adds one |

Measured with the policy, Playwright's Chromium, against the docs pages served by cmapi's own `_add_docs`: the page
renders, 4 search workers run, Ctrl+K opens the search and "namespace" lists the operations
(`redoc-search-under-the-csp.png`); the one violation is the refused logo (`img-src https://cdn.redoc.ly/...`), and no
request leaves for another host. With `'unsafe-eval'` removed from the policy: 0 workers and a `script-src eval`
violation, as Fable found. `/docs/redoc-start.js` follows `docs.enabled` and `docs.public` (it is in `DOCS_PATHS` of
`test_api_docs.py`), is served by the app (not a CDN) as `text/javascript`, and is public as `/redoc` is
(`test_review_c_authz.py`).

## Proof

| Test | Before | After |
|---|---|---|
| `test_api_docs.py::test_redoc_loads_its_bundle_as_a_module` | failed | passed |
| `test_api_docs.py::test_the_redoc_pin_carries_the_dompurify_fix` | failed | passed |
| Chromium on `/redoc`, ReDoc 3.0.1 and FastAPI's page | `.api-content` 0, error `Cannot use 'import.meta' outside a module` | |
| Chromium on `/redoc`, ReDoc 3.1.0 and the module page | | `.api-content` 1, no error |
| `test_api_docs.py::test_redoc_starts_with_its_telemetry_off` (#235) | failed | passed |
| `test_api_docs.py::test_the_redoc_page_asks_no_other_host` (Fable's, F1) | failed | passed |
| Chromium on `/redoc` (3.1.0), requests to other hosts | `POST https://otel.cloud.redocly.com/v1/traces`, the logo | the logo only |

`cmapi-tools docs-assets` fetched the new pin and checked its SHA-256. The service suite passed (see the pull request).
Not tested: the image build (no container on this Mac, #157); GitHub's `service` and `manifests` jobs build nothing
that holds ReDoc.

## Sources, read on 2026-11-14

- ReDoc 3.0.0 release notes (`gh release view redoc@3.0.0 -R Redocly/redoc`): "The package and the standalone bundle
  ship as ES modules. Load the bundle with `<script type="module" src="…/bundles/redoc.standalone.js">`".
- ReDoc 3.1.0 release notes: "Fixed security vulnerability `GHSA-cg2g-xh64-v4q7` in HTML sanitization".
- GitHub advisory GHSA-cg2g-xh64-v4q7 (`gh api /advisories/GHSA-cg2g-xh64-v4q7`).
- The HTML standard, "Scripting" (<https://html.spec.whatwg.org/multipage/scripting.html>): for a module script with
  no `async`, "the module script and its dependencies will be fetched in parallel to parsing" and "evaluated when the
  page has finished parsing". So the `<redoc>` element exists when the bundle runs.
