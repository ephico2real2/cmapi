# #651: FastAPI 0.162.2 and Starlette 1.10.0, out of the published advisories

The implementer's record, written by Opus 5.5 at `high` on 2026-11-24, on `fix/651-fastapi-starlette-upgrade` from
`a2a55f3`. Part of #481. It also clears the advisory of #649 (GHSA-7f5h-v6xp-fcq8) that reaches `/static` without a token;
#649's own step 1 (`/static` ignores Range) is not in this change.

## The advisories, before and after

`gh api /advisories -X GET -f ecosystem=pip -f affects=<package>@<version>`, read 2026-11-24
(`outputs/advisories-before-after.txt`), and pip-audit 2.10.1 on the whole installed set, which reads OSV
(`outputs/pip-audit-old-pins.txt`, `outputs/pip-audit-new-pins.txt`).

| Advisory | CVE | Severity (CVSS 3.1) | Affected | Patched | Reaches cmapi? |
|---|---|---|---|---|---|
| GHSA-7f5h-v6xp-fcq8 | CVE-2025-62727 | high (7.5) | starlette >= 0.39.0, <= 0.49.0 | 0.49.1 | Yes: `/static`, no token (#649). Measured below |
| GHSA-82w8-qh3p-5jfq | CVE-2026-54283 | high (7.5) | starlette >= 0.4.1, < 1.3.1 | 1.3.1 | No: cmapi reads no form (`grep request.form` finds none) |
| GHSA-wqp7-x3pw-xc5r | CVE-2026-48818 | high (7.5) | starlette < 1.1.0 | 1.1.0 | No: Windows UNC paths; the image is Linux |
| GHSA-86qp-5c8j-p5mr | CVE-2026-48710 | medium (6.5) | starlette <= 1.0.0 | 1.0.1 | No: cmapi reads no `request.url` |
| GHSA-x746-7m8f-x49c | CVE-2026-48817 | medium (5.3) | starlette < 1.1.0 | 1.1.0 | No: cmapi has no `HTTPEndpoint` |
| GHSA-2c2j-9gv5-cj73 | CVE-2025-54121 | medium (5.3) | starlette < 0.47.2 | 0.47.2 | No: no multipart |
| GHSA-jp82-jpqv-5vv3 | CVE-2026-54282 | low | Starlette < 1.3.0 | 1.3.0 | No: cmapi reads no `request.url` |

**A seventh advisory.** GHSA-jp82-jpqv-5vv3 names the package `Starlette`, with a capital S, and the query
`affects=starlette@0.41.3` does not return it; `affects=starlette` and pip-audit do. #651 listed six. The same holds for
PyJWT (below): the `affects=` filter matches the package name as the advisory spells it.

**After.** FastAPI 0.162.2, Starlette 1.10.0 and uvicorn 0.32.1: no advisory from `gh api` for any of the three, and none
from pip-audit for any framework package. pip-audit still reports PyJWT 2.10.1 and pytest 8.3.4, which this change does not
touch (see "Found while doing this").

## The choice of versions, and the ones rejected

PyPI's JSON (`https://pypi.org/pypi/<package>/<version>/json`, read 2026-11-24) gives each release's upload time and its
`requires_dist`:

| Package | Version | Uploaded | Requires | Decision |
|---|---|---|---|---|
| fastapi | 0.115.6 | 2024-12-03 | `starlette<0.42.0,>=0.40.0` | the old pin |
| fastapi | **0.162.2** | 2026-11-07 15:41Z | `starlette>=0.46.0`, `pydantic>=2.9.0`, `annotated-doc>=0.0.2`, `opentelemetry-api>=1.44.0` | **chosen**: the newest release older than two weeks on 2026-11-24 13:56Z |
| fastapi | 0.162.3, 0.162.4 | 2026-11-10 14:23Z, 17:51Z | as 0.162.2 (0.162.4 adds `anyio>=4.1.0`) | rejected: inside the two weeks by 27 minutes and by 4 hours |
| fastapi | 0.162.5 to 0.165.0 | 2026-11-11 to 2026-11-18 | 0.164.0 on: `starlette>=1.6.0`; 0.162.6 on: Python >= 3.11 | rejected: inside the two weeks |
| starlette | 0.41.3 | 2024-11-18 | | the old version, through FastAPI |
| starlette | 1.7.0 | 2026-09-23 | `anyio<5,>=4.0.0` | the version in FastAPI 0.162.2's `uv.lock`; rejected for 1.10.0, below |
| starlette | **1.10.0** | 2026-10-24 | `anyio<5,>=4.0.0`, `typing-extensions>=4.10.0` (Python < 3.13) | **chosen**: the newest release, no advisory, a month old |
| uvicorn | **0.32.1** | 2024-11-20 | `h11>=0.8`, `click>=7.0` | **kept**: no advisory, and it does not depend on Starlette |
| uvicorn | 0.54.0 | 2026-09-25 | | not needed: no advisory against 0.32.1, and the brief upgrades it only if needed |

**Why Starlette 1.10.0 and not 1.7.0.** FastAPI 0.162.2 was tested on Starlette's main branch as well as on its lock.
Its test workflow at the tag (`.github/workflows/test.yml`, lines 59-61 and 130-132) has a `starlette-git` matrix entry,
"Install Starlette from source", `uv pip install "git+https://github.com/Kludex/starlette@main"`, and the run on the
release commit `3adc94e` passed every `starlette-git` job (Actions run 42387496196, read 2026-11-24). Starlette's main on
2026-11-06 (`271c277`) is after the 1.10.0 tag (`8aa828c`). 1.10.0 also holds fixes that cmapi's `/static` uses: 1.8.0
"Include `Allow: GET, HEAD` in `StaticFiles` `405` responses" and "Ignore `Range` when `If-Range` contains a weak ETag",
1.10.0 "Ignore `Range` on requests other than `GET` and `HEAD` in `FileResponse`".

**Starlette is pinned on its own** in `cmapi/pyproject.toml` and `examples/local/requirements.txt`. The image runs
`pip install .` with no lock file (`cmapi/Containerfile`), so without the pin the resolver takes whatever Starlette satisfies
`starlette>=0.46.0` on the day of the build.

## Sources

- FastAPI's release notes, https://fastapi.tiangolo.com/release-notes/, fetched 2026-11-24, and the same file at
  `docs/en/docs/release-notes.md` of the repository; every release from 0.115.7 to 0.162.2 was read. The releases with a
  "Breaking Changes" section are in `sources/fastapi-breaking-blocks.md`.
- Starlette's release notes. https://www.starlette.io/release-notes/ does not resolve on 2026-11-24 ("Could not resolve
  host"); the project serves them at https://starlette.dev/release-notes/ (HTTP 200), read with the repository's
  `docs/release-notes.md`. Every release from 0.42.0 to 1.10.0 is in `sources/starlette-notes-0.42-1.10.md`.
- The FastAPI discussion that names the walk of an app's routes after 0.137.0,
  https://github.com/fastapi/fastapi/discussions/15782: tiangolo, 2026-06-17, "Would this work for you all?", with
  `for route_context in iter_route_contexts(router.routes): print(route_context.path)`, merged as PR #15785 (0.137.2).
- FastAPI's "Strict Content-Type Checking" page (`docs/en/docs/advanced/strict-content-type.md` at the tag 0.162.2):
  "JSON requests **must** include a valid `Content-Type` header (e.g. `application/json`) in order for the body to be parsed
  as JSON", and "This default behavior provides protection against a class of **Cross-Site Request Forgery (CSRF)**
  attacks".
- The installed sources of FastAPI 0.162.2 and Starlette 1.10.0, read for each assumption below, with file and line.

## The breaking changes, and what each one needs here

### FastAPI 0.115.7 to 0.162.2

| Release | Breaking change, in the notes' words | cmapi |
|---|---|---|
| 0.137.0 | "Now `router.routes` is no longer a plain list of `APIRoute` objects, it can contain these intermediate objects that can contain additional routers, forming a tree." | **Changed.** Four walks of `app.routes` saw only the app's own routes (`outputs/routes-probe-before-after.txt`): HEAD went on none of the included routes (#605 undone), a 405's `Allow` lost the methods of included routes, `check_documented` checked no `/api` route, and the document's HEAD filter passed included routes through. `core/docs.py` has `api_routes(app)`, which walks `iter_route_contexts(app.routes)`: the 405's `Allow` and `check_documented` use it, the document walks `iter_route_contexts` itself, and five tests that walked `app.routes` use it too. An included router's GET declares HEAD where it is made (`DocumentedRouter._register`, `routers/health.py`), because each app of a process serves the same included route objects; `_serve_head_with_get` adds HEAD to the app's own routes only (reviewer 2: HEAD added per app reached each later app, and a mutant without HEAD on the served route passed the whole of `test_head_605.py`) |
| 0.140.0 (not marked breaking) | "Reduce memory usage in dependencies" (PR #16049; 0.140.1, PR #16062: "Update the lru_cache limit for dependencies to account for large apps") | **Changed** (reviewer 2). A process-wide `lru_cache` (4096 entries, `fastapi/dependencies/models.py`, `_CallIdentity`) keeps each dependency's callable, and through them an app's `AppContext` and its connection pool outlive the lifespan. One app per process in production: no effect. The service suite builds an app per test in one process: 99 open connections at the peak and "sorry, too many clients already", against 15 on the old pins (`r2-outputs/runs/31-*`). `AppContext.shutdown` disposes the engine (SQLAlchemy, "Engine Disposal"); `test_an_app_that_ends_closes_its_database_connections` |
| 0.128.4 (a refactor) | "Simplify internals, remove Pydantic v1 only logic, no longer needed" | **Changed.** FastAPI's `ModelField` has no `type_` any more (0.115.6 `_compat.py:107-108` defined it as `self.field_info.annotation`). `check_documented` read `route.body_field.type_`; it reads `route.body_field.field_info.annotation`, the same value. Seen only once `check_documented` walked the included routes again: every app start failed with `AttributeError: 'ModelField' object has no attribute 'type_'` |
| 0.132.0 | "Now FastAPI checks, by default, that JSON requests have a `Content-Type` header with a valid JSON value" | **Kept, FastAPI's default.** A body sent with no Content-Type is no longer read as JSON and gets 422 validation-failed. The portal's client (openapi-fetch 0.17.0, `dist/index.mjs:56-63`) and the documented curl samples (`core/docs.py`, `sample_request`) send `Content-Type: application/json`. The page cited above gives the reason: the check closes a CSRF path that needs no preflight |
| 0.162.0, 0.160.0, 0.153.0, 0.150.0, 0.149.0, 0.147.0 | form fields and file inputs | None: cmapi has no form or file parameter |
| 0.155.0 | "The deprecated `**extra` keyword arguments have been removed from `Path`, `Query`, `Header`, `Cookie`, `Body`, `Form`, and `File`" | None: the suite builds every route at import, and none failed |
| 0.151.0 | "JSON request bodies now distinguish an explicit `null` from an omitted value" | None measured: the targeted suites pass |
| 0.148.0 | "Defaults for omitted `Query`, `Header`, `Cookie`, and `Form` parameters and model fields are no longer treated as user input" | None measured: the suites pass |
| 0.146.0, 0.145.0 | `root_path` deprecated; `openapi_prefix` removed | None: cmapi passes neither |
| 0.143.0 | "Automatic OpenTelemetry exporter setup is now opt-in" | None: cmapi sets no `OTEL_*`; FastAPI now installs `opentelemetry-api`, which is a no-op without a provider |
| 0.131.0, 0.128.0, 0.127.0, 0.129.0, 0.125.0 | ORJSON and UJSON responses deprecated, `pydantic.v1` dropped, Python 3.8 and 3.9 dropped | None: cmapi uses none, and runs Python 3.12 |
| 0.122.0 (a fix) | "Use `401` status code in security classes when credentials are missing" | None: `oauth2_scheme` has `auto_error=False` (`core/auth.py`) |
| 0.118.0 (a fix) | the exit code of a dependency with `yield` runs after the response is sent | None: cmapi has no dependency with `yield` |

### Starlette 0.42.0 to 1.10.0

| Release | Change | cmapi |
|---|---|---|
| 1.0.0rc1 | removed `on_startup`, `on_event()`, `add_event_handler()`, `@app.route()`, `@app.exception_handler()` of `Starlette`, `@app.middleware()`, the `method` of `FileResponse` | None: cmapi uses `lifespan`, and FastAPI's own `exception_handler` |
| 1.0.0rc1 | Range: "Include `bytes` unit in `Content-Range` header on 416", "Set `Content-Type` instead of `Content-Range` on multi-range responses", "Use CRLF line endings in multipart byterange boundaries" | Fixes three findings of #649; tested |
| 1.7.0 | "Require `anyio>=4.0.0,<5`" | None: anyio 4.16.0 installs |
| 1.7.0 | "Include `Vary: Origin` on all normal CORS responses and vary preflight responses by all request headers that affect them" | **Changed.** `CORSMiddleware.send` now appends Origin to the Vary of every answer for no origin or an origin not listed, and joins the lines into one, also when a line holds Origin or `*` (`cors.py:170`): `Vary: Origin, Origin`, `*, Origin`. `OriginVaryCORSMiddleware.send` puts the application's lines back before `vary_send` adds Origin once; without it 15 tests of `test_read_preconditions_590_593` fail (reviewer 1, mutant M5). A preflight now answers `Vary: Origin, Access-Control-Request-Method, Access-Control-Request-Headers, Access-Control-Request-Private-Network` where 0.41.3 answered `Vary: Origin`. Kept, with no test of its own: an answer to OPTIONS is not cacheable (RFC 9110, section 9.3.7), so this Vary changes no cache (reviewer 2) |
| 1.8.0 | "Require Python 3.11 or later" | None: Python 3.12 |
| 1.8.0 | `StaticFiles` 405 sends `Allow: GET, HEAD` | None: `method_not_allowed` sets the same value |
| 1.9.0 | "Stream `TestClient` response bodies" | None: the suites pass |
| 1.2.0 on | the TestClient prefers `httpx2`; with `httpx` it warns `StarletteDeprecationWarning` (a `UserWarning`) | A warning only. cmapi's runtime uses `httpx` for its own clients |
| 1.10.0 | "Clear the traceback of handled exceptions" | None: a handler that raises, as PR #645's `raise cause`, returns before that line (`_exception_handler.py:65`) |

## The assumptions of the open pull requests, on the new versions

Checked in the installed sources and by running each branch's own tests on an export of the branch with this change
applied, on FastAPI 0.162.2 and Starlette 1.10.0 (results under "Tests").

- **The status handler before the class handler** (PR #645, #644): holds. Starlette 1.10.0
  `_exception_handler.py:46-50`: `if isinstance(exc, HTTPException): handler = status_handlers.get(exc.status_code)`, then
  `_lookup_exception_handler` by the class's MRO.
- **`HTTPException.__cause__` for the body parse** (PR #645, #646): holds. FastAPI 0.162.2 `routing.py:476-499`: a
  `json.JSONDecodeError` is a `RequestValidationError` (`json_invalid`), any other exception from reading the body is
  `raise http_error from e` with status 400. New: with no Content-Type the body is not decoded at all (0.132.0), so it
  never reaches that 400.
- **The routing 405 and `Allow`** (PR #645, #644; main's `method_not_allowed`): holds once the route walk uses
  `api_routes`. FastAPI 0.162.2 raises the 405 of an included route with `Allow` of that one route
  (`routing.py:1316-1321`), as Starlette 0.41.3 did; `method_not_allowed` replaces it with the union.
- **`StaticFiles` 401, 404 and 405** (PR #645, #646): hold. Starlette 1.10.0 `staticfiles.py:119-134`: 405 for a method
  other than GET and HEAD (now with `Allow: GET, HEAD`), 401 for `PermissionError` with no cause, 404 for a missing file,
  a name too long, or (new) a null byte. `is_not_modified(response_headers, request_headers)` and
  `file_response(full_path, stat_result, scope, status_code)` keep their signatures, so `ConditionalStaticFiles` holds.
- **PR #645's main.py** conflicts textually with this change in `method_not_allowed`: its line
  `methods = {m for r in app.routes if isinstance(r, APIRoute) and ...}` must become
  `methods = {m for r in api_routes(app) if r.matches(request.scope)[0] == Match.PARTIAL for m in r.methods}`, or `Allow`
  loses the included routes on the new FastAPI.
- **PR #648** (`fix/648-value-error`, local commit `3e87b63`): removes the `ValueError` handler. `TierError` keeps its
  handler by the MRO lookup above, and an unhandled `ValueError` still reaches `UnhandledToProblemMiddleware`.
- **PR #647** (`fix/626-non-utf8-names`): no assumption about the framework. It changes `contract/openapi.json`, which this
  change does not touch.

## Tests

Every service run uses `CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_wt605` (PostgreSQL 16 on
the development Mac; no cluster), `PYTHONPATH=src:tests/service`, and one of two virtualenvs built from `cmapi[test]`:
the old pins (`outputs/freeze-old-pins.txt`) and the new ones (`outputs/freeze-new-pins.txt`). "Main" is an export of
`a2a55f3` with `test_framework_upgrade_651.py` copied in. The targeted set is `test_api_standard`, `test_api_docs`
(with `test_the_committed_contract_is_the_document_this_code_serves`), `test_api_samples`, `test_head_605`,
`test_cors`, `test_review_c_authz`, `test_static_preconditions_604`, `test_read_preconditions_590_593`,
`test_git_layer`, `test_problem_type_docs`, `test_plugins_switch`, `test_dry_run_refused_606` and
`test_framework_upgrade_651`.

| Run | Result | Output |
|---|---|---|
| main, old pins | 13 failed, 591 passed: the 13 tests of `test_framework_upgrade_651.py` only (7 advisories, the pin, the CVE parse 3.5 s, the CVE through `/static`, the 416 and multipart answers, `api_routes` missing) | `outputs/targeted-old-pins-main.txt` |
| main, new pins, no code change | 39 failed, 565 passed: `test_head_605` (HEAD 405 on every included route, `Allow` without the included routes), `test_read_preconditions_590_593` (Starlette's own Vary), `test_api_docs` (`check_documented` saw no `/api` route), `test_plugins_switch`, `test_dry_run_refused_606` (the walks of `app.routes` found no route), the 3 router and pin tests of this issue | `outputs/targeted-new-pins-main.txt` |
| this branch, new pins | 598 passed, 6 failed; the 6 were 500s from `psycopg.OperationalError: ... FATAL: sorry, too many clients already` (12 lines of it in the output) and pass when run again: 6 passed. In reviewer 2's runs the same error came from the test process itself, which kept each app's pool open (FastAPI 0.140.0 row above): 99 of the server's 100 connections were its database's | `outputs/targeted-new-pins-fixed.txt`, `outputs/rerun-new-pins-fixed.txt` |
| the 5 files that failed, after the CORS and `ModelField` changes | 201 passed | `outputs/subset-fixed-after-cors-and-modelfield.txt` |
| reference code (`examples/`, `pytest tests`), old pins / new pins on main / this branch | 748 passed, 113 skipped each | `outputs/examples-*.txt` |
| `scripts/doc-citations.py --check` | 13 citations moved by the line changes in `main.py`, `core/docs.py` and `test_review_c_authz.py`; `--relocate` moved them, then 0 problems | |

The committed contract test passes on this branch, so the served OpenAPI document is unchanged: no regeneration of
`contract/openapi.json`, and nothing for the oasdiff gate to compare.

**The open pull requests, on the new pins with this change applied to an export of each branch** (PR #645 at the local
head `ee33a49` of `fix/644-router-problems`, PR #647 at `origin/fix/626-non-utf8-names`, #648 at `3e87b63`):

| Branch | First run | Run again (the connection failures) | Output |
|---|---|---|---|
| PR #645 + its `test_router_problems_644`, `test_framework_problems_646` | 625 passed, 13 failed | 12 passed; the 13th is `test_pyproject_pins_a_patched_starlette`, which fails because the export keeps the branch's own pyproject.toml | `outputs/targeted-pr645-new-pins.txt`, `outputs/rerun-pr645-new-pins.txt` |
| PR #647 + its `test_non_utf8_names_626` | 612 passed, 9 failed | 8 passed; the 9th is the pin test | `outputs/targeted-pr647-new-pins.txt`, `outputs/rerun-pr647-new-pins.txt` |
| #648 + its `test_value_error_648` | 602 passed, 9 failed | 8 passed; the 9th is the pin test | `outputs/targeted-pr648-new-pins.txt`, `outputs/rerun-pr648-new-pins.txt` |

**The measurements of #649's CVE** (`outputs/range-probe-before-after.txt`, `probes/range_probe.py`, best of three):
`FileResponse._parse_range_header("bytes=" + "0" * n + "a-", 1_000_000)` took 0.052, 0.224, 0.773 and 3.570 s on
Starlette 0.41.3 for n = 2000, 4000, 8000 and 16000, and 0.000025, 0.000038, 0.000068 and 0.000131 s on 1.10.0. A GET of
a 17-byte file through `StaticFiles` with the 16 kB header took 3.42 s and 0.0067 s. Still on 1.10.0, and left to #649's
step 1: `Range: widgets=1-2` answers 400 "Only support bytes range" where RFC 9110 section 14.2 says "MUST ignore", and a
malformed or unsatisfiable Range answers plain text, not an RFC 9457 problem.

## Found while doing this

Each is for the coordinator to file (`fix-defect`); none is fixed here, because none is in #651's scope.

1. **PyJWT 2.10.1 is in published advisories, one critical** (`cmapi/pyproject.toml:20`). `gh api /advisories -X GET -f
   ecosystem=pip -f affects=pyjwt` lists 16 whose range holds 2.10.1, among them GHSA-ffc3-869f-jxw9 (critical,
   "Asymmetric-PEM detection bypass", <= 2.13.0, patched 2.14.0), GHSA-x33g-cr3x-6449 and GHSA-42vr-xj54-vc7v (<= 2.14.0,
   patched 2.15.0) (`outputs/advisories-pyjwt.txt`); pip-audit reports 17 IDs (PYSEC and GHSA) (`outputs/pip-audit-new-pins.txt`). cmapi
   verifies every token with it (`core/auth.py:165`, RS256 only, keys from `jwt.PyJWK`), so its reach needs the same
   per-advisory reading as the table above. Proof: `pip-audit -r <freeze> --no-deps --disable-pip` names pyjwt.
2. **`gh api /advisories -f affects=<name>@<version>` misses advisories** that spell the package with capitals:
   `affects=starlette@0.41.3` returns 6 and misses GHSA-jp82-jpqv-5vv3 (`Starlette`); `affects=pyjwt@2.10.1` returns 8 of
   the 16 above, and not the critical one (`PyJWT`). #651's table came from that query. pip-audit (OSV) reports Starlette's
   1.3.0 fix (PYSEC-2026-248) and 17 PyJWT IDs. CI runs no dependency audit at all (`.github/workflows/ci.yml`).
3. **pytest 8.3.4** is in GHSA-6w46-j5rx-g56g, "pytest has vulnerable tmpdir handling", patched 9.0.3 (test-only).
4. **The image has no lock file.** `cmapi/Containerfile` runs `pip install .`, so every transitive package (anyio, h11,
   httptools, opentelemetry-api, ...) is whatever the index holds on the day of the build. This change pins Starlette
   because an advisory makes it matter; a hashed lock (`pip-compile --generate-hashes` or `uv pip compile`) would make it
   hold for every package.

Two notes, not defects: Starlette 1.2.0 on prefers `httpx2` in its TestClient and warns `StarletteDeprecationWarning` (a
`UserWarning`) with `httpx`; and FastAPI 0.162.5 and 0.162.7 (11 and 13 November) fix "synchronous dependency cleanup on
cancellation" and "async yield dependency cleanup on cancellation". cmapi has no dependency with `yield`, and the next bump
can take them once they are two weeks old.

## What was not tested

- The whole service suite: the coordinator runs it. Only the targeted set above ran here.
- The image build (`cmapi/Containerfile`) and CI: not run here. The image installs the same pins from pyproject.toml.
- CRC or kind: nothing was deployed. `/readyz`, the docs, HEAD and 405 through the front door are not measured on a
  cluster.
- The portal (`cmapi-portal-ui`) suites: not run; the served document is unchanged, so its generated types are too.
- uvicorn with Starlette 1.10.0 outside the TestClient: not measured. uvicorn 0.32.1 does not import Starlette.
- The Spectral lint and the oasdiff gate: not run, because the document is unchanged (the committed-contract test).
