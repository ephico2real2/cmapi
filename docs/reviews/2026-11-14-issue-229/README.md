# #229 BUG-57 and #230 SEC-11: ReDoc 3 on `/redoc`

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
| A module script, `<script type="module" src=...>`, on cmapi's own page (chosen) | The bundle starts itself on `<redoc spec-url>`. The page keeps no request to another host |
| Import `init` from the bundle in an inline module | Works too, but an inline script needs `'unsafe-inline'` or a hash in the Content-Security-Policy, and the page gets more code |
| Pin ReDoc 2 again | ReDoc 2 is a classic script, so FastAPI's page works, but it gives up the 3.x fixes, the security fix of #230 among them |

The pin moves to ReDoc 3.1.0. Its tarball's SHA-512 equals npm's `dist.integrity`
(`sha512-hYsN0ABpoDAPE2+A+mNvs6DDTzhPlJaIeJK2jCFgvxtiXHpWzBXqNBWWKUNq/VLBMZGnyT4qiQnODVWEX031uQ==`), and its SHA-256 is
`d6f4b0c0abb970724c112473ace8229fd1cc3c78be4ca110841de4c640de15a9`. 3.1.0 was published on 2026-11-05, nine days before
this pin. The other pins wait 14 days after a release; this one does not, because it is the fix of a security advisory.

## Proof

| Test | Before | After |
|---|---|---|
| `test_api_docs.py::test_redoc_loads_its_bundle_as_a_module` | failed | passed |
| `test_api_docs.py::test_the_redoc_pin_carries_the_dompurify_fix` | failed | passed |
| Chromium on `/redoc`, ReDoc 3.0.1 and FastAPI's page | `.api-content` 0, error `Cannot use 'import.meta' outside a module` | |
| Chromium on `/redoc`, ReDoc 3.1.0 and the module page | | `.api-content` 1, no error |

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
