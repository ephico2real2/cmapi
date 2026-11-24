# PR #654 (#651): reviewer 1, Opus 5.5 at `high` (standing in for Codex)

Reviewed on 2026-11-24, from the export `review-654/` (`head/` is the PR head and `base/` is main `a2a55f3`). Nothing in
any git repository, on GitHub or on a cluster was changed. Every run below used PostgreSQL 16 on `127.0.0.1:55432`,
database `cmapi_wt605`, on the development Mac. No cluster was used. The outputs are in `review-654/r1-outputs/`.

## Summary

- **The upgrade does what it claims.** On the new pins, the served `/openapi.json` and `/openapi.yaml` are byte-identical
  to base's on the old pins, with the same ETags. All 52 served routes are the same in path, methods (HEAD included),
  permission, body and response models, dependencies, query parameters and status code. The CVE parse falls from 2.77 s
  to 0.00013 s. No advisory, from `gh api` or from pip-audit, names fastapi 0.162.2, starlette 1.10.0 or uvicorn 0.32.1.
- **One behaviour changes, as FastAPI 0.132.0 says it will.** A JSON body sent with no `Content-Type` was 200 and is now 422
  `validation-failed`. A body sent as `text/plain` was already 422 on base. Ruling: keep FastAPI's default and do not opt out
  (item 4).
- **Findings: 1 Medium and 3 Low**, each with its full fix and a test, all in `r1-outputs/fix.diff`:
  - **M1 (Medium).** `test_declared_permission_is_the_enforced_one_and_every_route_answers` passes when the route walk
    misses the included routers: an empty table holds nothing bad. That is exactly the regression class of this upgrade.
  - **L1 (Low).** The README's row for Starlette 1.7.0 says "None". It is refuted by mutant M5: without the `send` override,
    15 tests fail. The row also quotes half the release note, and the preflight's new `Vary` goes unrecorded.
  - **L2 (Low).** `docs/15` still cites only Starlette 0.41.3, and its `Vary` row does not cover the preflight.
  - **L3 (Low).** `examples/local/INSTALL.md` still says "fastapi 0.115.6" and "FastAPI 0.115".
- **The other open PRs.**
  - #645 conflicts in one hunk of `main.py`. With the resolution given below, its tests pass on the new pins (122 passed).
  - #652's local head `0ff4324` (wt-648) has a test that walks `app.routes`. It fails on the new pins (`assert 0 >= 10`),
    and its two-line fix is below.
  - #647 has no dependency on the framework.
  - All three have only line-number conflicts in `docs/14`, `docs/15` and `docs/citations.lock.json`, which
    `scripts/doc-citations.py --relocate` resolves.

## 1. Research: each source fetched and read on 2026-11-24

### PyPI (`https://pypi.org/pypi/<package>/<version>/json`, `r1-outputs/research/pypi-*.json`)

| Package | Version | First upload (UTC) | Age on 2026-11-24 | Requires |
|---|---|---|---|---|
| fastapi | 0.162.2 | 2026-11-07T15:41:38Z | 17 days: **older than two weeks** | `starlette>=0.46.0`, Python >= 3.10 |
| starlette | 1.10.0 | 2026-10-24T15:04:10Z | 31 days: **older than two weeks** | `anyio<5,>=4.0.0`, Python >= 3.11 |
| uvicorn | 0.32.1 | 2024-11-20T19:41:11Z | about 2 years | `click>=7.0`, `h11>=0.8` |

Every upload time and requirement in the README's version table matches PyPI. One fact has moved since the README was
written:
- 0.162.3 (2026-11-10T14:23Z) passed the two-week mark at 14:23Z today, and 0.162.4 (17:51Z) at 17:51Z.
- 0.162.3 holds no code fix. 0.162.4's only fix is "Require AnyIO 4.1.0 or newer at runtime" (FastAPI's release notes).
  0.162.2 therefore needs AnyIO >= 4.1 without declaring it, and the image, which has no lock file, takes the newest AnyIO
  (4.16.0 in the venv).
- This needs no change. It is one more case for the README's finding 4 (a hashed lock).

### GitHub advisories (`gh api /advisories -X GET -f ecosystem=pip -f affects=...`, `r1-outputs/research/adv-*.tsv`)

| Query | Result |
|---|---|
| `starlette@1.10.0`, `Starlette@1.10.0`, `fastapi@0.162.2`, `FastAPI@0.162.2`, `uvicorn@0.32.1` | 0 each |
| `starlette@0.41.3` | 6, all except GHSA-jp82-jpqv-5vv3 |
| `Starlette@0.41.3` | 1: GHSA-jp82-jpqv-5vv3 only |
| `starlette` / `Starlette` with no version | the same 13, in either spelling |

- **The README's claim holds.** The versioned filter matches the package name as the advisory spells it, case-sensitively.
- Each of the 7 IDs fetched directly (`gh api /advisories/<id>`) gives the CVE, severity, range and patched version that
  the README's table and the test's `ADVISORIES` list name.
- The only addition: GHSA-jp82-jpqv-5vv3 is CVSS 3.7, which the README gives as "low" with no score.
- The highest "patched" of the 13 is 1.3.1, which is at or below 1.10.0.

**pip-audit 2.10.1** on the new venv (`r1-outputs/research/pip-audit-new.txt`): 24 rows in 2 packages, and no framework
package among them. They are pyjwt 2.10.1 (17 unique IDs) and pytest 8.3.4 (PYSEC-2026-1845). Both match the README's
"Found while doing this".

### FastAPI release notes 0.115.7 to 0.162.2

Read in full from https://fastapi.tiangolo.com/release-notes/ (HTTP 200) and from the same file at the tag
(`docs/en/docs/release-notes.md`, lines 10 to 2731), `r1-outputs/research/fastapi-0.115.7-0.162.2.md`.

Every release with a "Breaking Changes" section:

| Release | Breaking change, in the notes' words | cmapi affected? | Handled? |
|---|---|---|---|
| 0.162.0 | "Restore default handling for omitted boolean form fields" | No: no form parameter | n/a |
| 0.160.0 | "Apply each parameter model's `extra` configuration to sibling fields" | No: no parameter model | n/a |
| 0.155.0 | "The deprecated `**extra` keyword arguments have been removed from `Path`, `Query`, `Header`, `Cookie`, `Body`, `Form`, and `File`" | No: every route builds at import (run 01) | n/a |
| 0.151.0 | "JSON request bodies now distinguish an explicit `null` from an omitted value" | Not measured to change anything: the targeted runs pass | n/a |
| 0.150.0, 0.149.0, 0.147.0 | file inputs and form fields | No: no form or file parameter | n/a |
| 0.148.0 | "Defaults for omitted `Query`, `Header`, `Cookie`, and `Form` parameters and model fields are no longer treated as user input" | Not measured to change anything: the targeted runs pass | n/a |
| 0.146.0, 0.145.0 | `root_path` deprecated; `openapi_prefix` removed | No: neither is passed | n/a |
| 0.143.0 | "Automatic OpenTelemetry exporter setup is now opt-in" | No: there is no `OTEL_` or `opentelemetry` in `cmapi/src` or `deploy` (grep) | n/a |
| 0.137.0 | "Now `router.routes` is no longer a plain list of `APIRoute` objects, it can contain these intermediate objects that can contain additional routers, forming a tree." | **Yes** | **Yes**: `api_routes`. Proved in item 1 |
| 0.132.0 | "Now FastAPI checks, by default, that JSON requests have a `Content-Type` header with a valid JSON value, like `application/json`, and rejects requests that don't." | **Yes** (item 4) | Kept on purpose; ruled in item 4 |
| 0.131.0, 0.129.0, 0.128.0, 0.127.0, 0.125.0 | ORJSON/UJSON, `pydantic.v1`, Python 3.8 and 3.9 | No | n/a |
| 0.128.4 (a refactor, not labelled breaking) | "Simplify internals, remove Pydantic v1 only logic, no longer needed" | **Yes**: `ModelField.type_` is gone. In 0.115.6 it was `self.field_info.annotation` (`fastapi/_compat.py:107-108`, read) | **Yes**: `field_info.annotation`. Run 02b shows the same body models on both |

### Starlette release notes 0.42.0 to 1.10.0

Read in full. https://www.starlette.io/release-notes/ does not resolve (`curl: (6) Could not resolve host: www.starlette.io`).
https://starlette.dev/release-notes/ answers HTTP 200. I also read the repository's `docs/release-notes.md` at tag
1.10.0, lines 1 to 556 (`r1-outputs/research/starlette-0.42-1.10.md`). The changes that touch what cmapi uses:

| Release | Change, in the notes' words | cmapi affected? | Handled? |
|---|---|---|---|
| 1.7.0 | "Include `Vary: Origin` on all normal CORS responses and vary preflight responses by all request headers that affect them" | **Yes**. Simple answers: `Vary: Origin, Origin` and `*, Origin` (run below). Preflight: its `Vary` grows | Simple answers: **yes** (`OriginVaryCORSMiddleware.send`). Preflight: kept, but **not recorded** (L1, L2) |
| 1.8.0 | "Include `Allow: GET, HEAD` in `StaticFiles` `405` responses" | Same value as cmapi's handler | n/a |
| 1.0.0rc1 | "Include `bytes` unit in `Content-Range` header on 416 responses"; "Set `Content-Type` instead of `Content-Range` on multi-range responses"; "Use CRLF line endings in multipart byterange boundaries"; "Handle null bytes in `StaticFiles` path" | Fixes three findings of #649 (item 6); a NUL static path is now 404 (`staticfiles.py:132-134`) | Tested by the new file |
| 1.0.0rc1 | removed `on_startup`, `on_event()`, `@app.route()`, `@app.exception_handler()` of `Starlette`, `@app.middleware()`, `FileResponse(method=)` | No: cmapi uses `lifespan` and FastAPI's `exception_handler` | n/a |
| 1.3.0 | "Build `request.url` from structured components" | No: `request.url` appears only in `examples/local/keycloak_setup.py`, which reads an httpx response's URL | n/a |
| 1.7.0 | "Require `anyio>=4.0.0,<5`"; "Expose the matched route through `scope["route"]`" | No: anyio 4.16.0; FastAPI already set `scope["route"]` | n/a |
| 1.7.0 | "Run background tasks only after the response is sent when using `BaseHTTPMiddleware`" | No: cmapi has no `BaseHTTPMiddleware` (`main.py:64` says so) | n/a |
| 1.8.0 | "Require Python 3.11 or later" | No: Python 3.12 | n/a |
| 1.9.0 | "Stream `TestClient` response bodies" | Not measured to change anything: the targeted runs pass | n/a |
| 1.10.0 | "Clear the traceback of handled exceptions" | No: `_exception_handler.py:65` runs after the handler returns | n/a |
| 0.43.0, 0.45.0, 0.46.0 | `allow_redirects` removed from `TestClient`; the `ExceptionMiddleware` proxy removed; `TestClient(timeout=)` deprecated | No: none is used (grep) | n/a |

### Each quote in the implementer's README, checked against its source

- **FastAPI release notes:** 0.137.0, 0.132.0, 0.128.4, 0.155.0, 0.151.0, 0.148.0, 0.143.0 and 0.122.0 are verbatim.
- **Starlette release notes:** 1.0.0rc1, 1.7.0 ("Require `anyio>=4.0.0,<5`"), 1.8.0, 1.9.0 and 1.10.0 are verbatim.
- **FastAPI discussion #15782,** read through the GraphQL API: tiangolo, 2026-06-17T18:49:08Z, "Would this work for you
  all? https://github.com/fastapi/fastapi/pull/15785", with the `iter_route_contexts(router.routes)` example. Verbatim.
- **The "Strict Content-Type Checking" page at tag 0.162.2:** both quotes are verbatim.
- **FastAPI's CI at tag 0.162.2:**
  - `test.yml` has the matrix entry `starlette-git` and the step "Install Starlette from source".
  - Run 42387496196 is on `3adc94e…`, which is the tag's commit. Its conclusion is "success".
  - FastAPI's `uv.lock` at the tag pins starlette 1.7.0.
  - Starlette `271c277` is dated 2026-11-06T11:03:14Z and `8aa828c` ("Version 1.10.0") 2026-10-24T14:58:54Z. All verified.
- **Line citations into the installed sources,** each read:
  - Starlette 1.10.0: `cors.py:170`, `routing.py:244-247`, `_exception_handler.py:46-50` and `:65`, `staticfiles.py:120`.
  - FastAPI 0.162.2: `routing.py:476-499`, `routing.py:1316-1321`, `routing.py:1074`.
  - FastAPI 0.115.6: `_compat.py:107-108`.
  - All are correct.
- **Retracted.** The README's row for Starlette 1.7.0 says "None: `OriginVaryCORSMiddleware.vary_send` adds Origin only
  when no Vary line has it; `test_cors.py` passes". The code and the tests refute that: mutant M5, without the PR's `send`
  override, fails 15 tests of `test_read_preconditions_590_593.py`. The row also quotes only half of the 1.7.0 note, so the
  change to the preflight's `Vary` is in no record. This is finding L1.

## 2. The seven claims, each decided by a test

### 1. Included routes: confirmed

- `api_routes` (`core/docs.py`) walks `iter_route_contexts(app.routes)`. `iter_route_contexts` is FastAPI 0.162.2
  `routing.py:1893`, and it yields each included route through `_IncludedRouter.effective_route_contexts()`.
- `_serve_head_with_get` adds HEAD on the cached `_EffectiveRouteContext`, whose `methods` is a copy
  (`routing.py:1074`, `route.methods = {method.upper() for method in methods}`). It also adds HEAD on the original route,
  from which a context is rebuilt when the router's route version changes (`routing.py:1660-1683`).

**Mutant M1**: `api_routes` returns `[RouteContext(r) for r in app.routes if isinstance(r, APIRoute)]`
(`runs/04-M1.txt`): **21 failed**. Among them:

| Test | What it proves |
|---|---|
| `test_every_get_route_answers_head_as_its_get` | HEAD works on every GET (#605) |
| `test_405_lists_the_methods_of_the_resource` | a 405's `Allow` lists every method of the path (#634) |
| `test_a_parameter_without_a_description_or_an_example_stops_startup` | `check_documented` checks every route |
| `test_head_is_not_an_operation_of_the_document` | HEAD stays out of the document |
| `test_every_write_without_a_dry_run_refuses_one` | the dry-run guard covers every write |
| `test_the_plugins_that_the_switch_knows_are_the_routers_and_their_writes` | the plugin switch sees every router |
| both route tests of the new file | the new tests can fail |

**One test did not fail under M1:** `test_review_c_authz.py::test_declared_permission_is_the_enforced_one_and_every_route_answers`.
This is finding M1, below.

**Mutant M4** (no HEAD on the context, `runs/07-M4.txt`): `test_every_get_route_answers_head_as_its_get` fails.

**Mutant M3** (no HEAD on the original route, `runs/06-M3.txt`): `test_head_stays_on_a_route_when_its_router_changes`
and `test_head_is_not_an_operation_of_the_document` fail.

**Run 02b:** the 405s on base with the old pins and on head with the new pins are the same.

| Request | Answer on both |
|---|---|
| PUT on a namespace | 405, `Allow: DELETE, GET, HEAD, PATCH` |
| DELETE `/api/v1/version` | 405, `GET, HEAD` |
| POST on a static file | 405, `GET, HEAD` |
| PUT `/problems` | 405, `GET, HEAD` |

An anonymous HEAD and GET of every documented GET path give the same status, with 0 mismatches on either side.

**An observation, not a finding.** Adding HEAD to `original_route.methods` now changes the module-level routers, such as
`health.router`, `me.router` and `admin.router`, for every app in the process. Before 0.137.0, `include_router` copied
each route.
- A second app that includes the same router without `_serve_head_with_get` answers HEAD with 200. A direct probe with
  `app2` showed this.
- In production there is one app per process. The document is unaffected because `_WithoutHead` filters it.
- I leave it as recorded. A fix (HEAD declared when the route is made) would touch every router for no measured gain.

### 2. OpenAPI document: confirmed

- `get_openapi` reads each `RouteContext` as given (`openapi/utils.py:536-540`, `_get_api_route_for_openapi`), so
  `_WithoutHead.methods` is the value it sees.
- **Byte comparison.** `base-old-openapi.json` against `head-new-openapi.json`: `cmp` finds them identical. The same holds
  for `.yaml`. The ETags are equal (`"e4983fa695af542e9a4f67e66817d049"` for JSON). Run 02b.
- **Mutant M2** (`_WithoutHead` passes HEAD through, `runs/05-M2.txt`): `test_head_is_not_an_operation_of_the_document`
  and `test_the_committed_contract_is_the_document_this_code_serves` fail.

### 3. CORS Vary: confirmed for simple answers; preflight changed and not recorded (L1, L2)

`r1-outputs/probes/cors_probe.py` runs 25 cases. Seven Vary shapes from the application go through `OriginVaryCORSMiddleware`:
none, one line, two lines, `Origin`, `Accept, origin`, `*` and `Accept,\tOrigin`. Each runs for a listed origin, a
not-listed origin and no origin. On top of those come three preflights and one OPTIONS without
`Access-Control-Request-Method`.

**Base with the old pins against head with the new pins** (`cors-compare.txt`). Field order across different names is
ignored, because RFC 9110 section 5.3 gives it no meaning.
- **All 22 simple answers are identical.**
- **The 3 preflights differ only in `Vary`:** `Origin` (0.41.3) became
  `Origin, Access-Control-Request-Method, Access-Control-Request-Headers, Access-Control-Request-Private-Network` (1.10.0).

**Base's source on the new pins** (no `send` override) against head:
- 8 answers are wrong: `Origin, Origin`, `Accept, origin, Origin`, `*, Origin` and `Accept,\tOrigin, Origin`, each for a
  not-listed origin and for no origin.
- The override fixes all 8.

**Tests.**
- `test_cors.py` and `test_read_preconditions_590_593.py` pass on head (run 01: 329 passed in the targeted set).
- **Mutant M5** (override removed, `runs/08-M5.txt`): `test_cors.py` still passes, and 15 tests of
  `test_read_preconditions_590_593.py` fail. So the #596 cases that guard the override live in
  `test_read_preconditions_590_593`, not in `test_cors`.

### 4. Strict Content-Type: measured, and ruled "keep FastAPI's default"

**Measured** (run 02b, dry-run create, the same bytes):

| Content-Type | Base with the old pins | Head with the new pins |
|---|---|---|
| `application/json` | 200 | 200 |
| none | **200** | **422** `validation-failed`, `model_attributes_type`, "Input should be a valid dictionary or object to extract fields from" |
| `text/plain` | 422, the same problem | 422, the same problem |

**Who sends a body, and does each send the header?**

| Sender | Sends `Content-Type: application/json`? | Evidence |
|---|---|---|
| The portal | Yes, whenever there is a body | `openapi-fetch` 0.17.0, `dist/index.mjs:56-63`, fetched from unpkg: `"Content-Type": "application/json"` unless there is no body or it is FormData |
| The docs' curl samples | Yes, on each sample with a body | `docs/04-api-examples.md` |
| `docs/02` | Yes (merge-patch) | `application/merge-patch+json`, which FastAPI parses as `+json` |
| `examples/local/INSTALL.md` | Yes | `H=(-H 'content-type: application/json')` on every call with a body, the `$BOT` service client's included (line 470) |
| `examples/local/demo.py` | Yes | `httpx.request(..., json=body)` |
| `deploy/crc-proof.sh:238` | Yes | `header = "Content-Type: application/json"` |

- No other client of the API is in the repository. The "bot" that runs from it is that `$BOT` service account in
  `INSTALL.md`. cmapi's own Git bot does not call the API.

**FastAPI's option.** From "Strict Content-Type Checking" at tag 0.162.2: "If you need to support clients that don't send
a `Content-Type` header, you can disable strict checking by setting `strict_content_type=False`".

**Ruling: keep the default (strict), and do not opt out.** The reasons:
1. No client found needs the opt-out.
2. The documented request body is `application/json`.
3. The no-header case now gets the answer that a wrong header already got on base.

**Recorded for the owner, not filed.** RFC 9110 section 15.5.21 says a 422 "indicates that the server understands the content
type of the request content (hence a 415 (Unsupported Media Type) status code is inappropriate)". Section 15.5.16 makes 415
the answer for content "in a format not supported". Section 8.3 lets a server that gets no Content-Type "assume a media type
of 'application/octet-stream'". So 415 is the precise status for both `text/plain` and no header.
- This predates the PR (`text/plain` is already 422).
- cmapi's decided convention since #164 answers every body problem with 422 `validation-failed` (`core/docs.py`,
  `_register`: "A body that is not JSON is 422 before both").
- So I record the RFC reading for the owner and do not reopen the convention here.

### 5. The other open PRs

PR states read from GitHub (read-only):

| PR | State | GitHub head | Worktree head |
|---|---|---|---|
| #645 | OPEN, not merged | `9de8199` | wt-644, the same |
| #652 | open | `3e87b63` | wt-648 has a newer, unpushed `0ff4324` |
| #647 | open | `190e4069` | wt-626 is `ab6b36a`, a merge of `a2a55f3` |

The conflicts come from a three-way `git merge-file`: ours = the PR #654 head, base = `a2a55f3`, theirs = each PR
(`r1-outputs/merge/`). Each merged tree was then run on the new pins.

**#645 (`fix/644-router-problems`, `9de8199`)**

**Conflicts:**
- `main.py`: one hunk, the docstring and first lines of `method_not_allowed`.
- `docs/14`: 3 hunks; `docs/citations.lock.json`: 4. All are line numbers.
- `cors.py` and `docs.py` merge cleanly.

**Its code after the upgrade.** The merge takes #654's `api_routes` line, because #645 left that line unchanged. The
`methods = {…}` line is therefore right, and `APIRoute` is not referenced (checked in the merged file). The resolved
handler is below; the whole file is `r1-outputs/merge/pr645-main.resolved.py`:

```python
    @app.exception_handler(405)
    async def method_not_allowed(request: Request, exc: HTTPException) -> Response:
        """RFC 9110, section 15.5.6: a 405's Allow lists "the target resource's currently supported methods". The router
        names the methods of the first route that matches the path only (Starlette 0.41.3, routing.py:737 and :281;
        FastAPI 0.162.2, routing.py:1316-1321), and cmapi gives each method of a path its own route, so PUT on a namespace
        said "GET, HEAD" without PATCH and DELETE. StaticFiles serves GET and HEAD (Starlette 0.41.3 sent no Allow,
        staticfiles.py:113; 1.10.0 sends "GET, HEAD", staticfiles.py:120)."""
        headers = dict(exc.headers or {})
        allow = None
        if isinstance(request.scope.get("endpoint"), StaticFiles):
            allow = "GET, HEAD"
        else:
            methods = {m for r in api_routes(app) if r.matches(request.scope)[0] == Match.PARTIAL for m in r.methods}
            if methods:
                allow = ", ".join(sorted(methods))
        if allow:   # one Allow field: Starlette's, whatever its case, gives way to the whole list
            headers = {k: v for k, v in headers.items() if k.lower() != "allow"} | {"Allow": allow}
        return problem_response(Problem(405, "method-not-allowed", PROBLEMS["method-not-allowed"][1]), headers)
```

**Its assumptions about Starlette 0.41.3 and FastAPI 0.115.6, each checked in the 1.10.0 and 0.162.2 sources:**
- **They hold.**
  - The status handler is looked up before the class handler (`_exception_handler.py:46-50`).
  - FastAPI raises its body 400 `from e` (`routing.py:494-499`).
  - The router raises HTTPException 404 and 405 (`routing.py:639`, `:284`; FastAPI `routing.py:1316-1321` for an included
    route).
  - StaticFiles raises 401 (`staticfiles.py:125`) and 404 (`:129`, `:134`, `:158`).
  - The form parser raises 400 (`requests.py:297`, `:311`).
- **Only the line numbers in its comments are stale.** These should become 1.10.0 and 0.162.2 lines after the merge:

| Place in #645 | Line now cited | Line after the upgrade |
|---|---|---|
| comment above `not_found`, Starlette's router | `routing.py:651` (no route matches) and `:283` (another method) | 1.10.0 `routing.py:639` and `:284`, plus FastAPI 0.162.2 `routing.py:1316-1321` for an included route |
| comment above `not_found`, StaticFiles | `staticfiles.py:114, :123, :149` | `staticfiles.py:120`, `:129`, `:134`, `:158` |
| `framework_refusal` docstring, FastAPI's body 400 | `fastapi/routing.py:283-287` | `fastapi/routing.py:494-499` |
| `framework_refusal` docstring, the form parser | `starlette/requests.py:271` | `starlette/requests.py:297` and `:311` |
| `framework_refusal` docstring, StaticFiles' 401 | `staticfiles.py:119` | `staticfiles.py:125` |

- **Run 11:** `test_router_problems_644`, `test_framework_problems_646`, `test_head_605`, `test_cors` and
  `test_framework_upgrade_651` on the merged tree, new pins: **122 passed**.

**#652 (`fix/648-value-error`, local `0ff4324`)**

**Conflicts:** `main.py` merges cleanly. Line-number conflicts only: `docs/14` 2, `docs/15` 1, citations lock 5.

**A Starlette-0.41.3 dependency that breaks.** `test_client_input_653.py::test_every_request_body_is_a_request_body`
walks `client.app.routes` for `APIRoute`.
- On the new pins it finds no included route: `AssertionError: {} … assert 0 >= 10` (run 12: 1 failed, 75 passed).
- This file is new in `0ff4324`, after the `3e87b63` that the implementer measured.

The exact code it needs (`r1-outputs/merge/pr652-after-651.diff`):

```diff
 import pytest
-from fastapi.routing import APIRoute
-
+from cmapi.core.docs import api_routes
 from conftest import build_world
@@
-    for route in client.app.routes:
-        if isinstance(route, APIRoute) and route.body_field is not None:
+    for route in api_routes(client.app):
+        if route.body_field is not None:
```

With it, the test passes on the merged tree (run 14: 1 passed).

**Comments that are now untrue on 1.10.0:**
- **`UnhandledToProblemMiddleware`.** Its comment says a StreamingResponse failure "comes wrapped in a one-member
  ExceptionGroup (starlette/responses.py:252 …) … as Starlette's own collapse_excgroups unwraps it (_utils.py:79-80)".
  - In 1.10.0, StreamingResponse uses `create_collapsing_task_group` (`responses.py:278`, `_utils.py:101-111`), which
    re-raises the single member itself.
  - `collapse_excgroups` no longer exists.
  - The loop stays as a guard for groups raised by user code. Comment to use:
    `# Starlette 0.41.3 wrapped a StreamingResponse failure in a one-member ExceptionGroup (responses.py:252); 1.10.0
    # collapses it itself (_utils.py:101-111, create_collapsing_task_group). A group that user code raises is still unwrapped here.`
- **`RefuseNulMiddleware`.** Its docstring says "os.stat refuses one in the path of a static file, so before this a NUL in …
  a static path answered 500". That holds on 0.41.3 only: 1.10.0 answers 404 (`staticfiles.py:132-134`, `except ValueError`
  → 404).
  - The middleware still answers first with 422, so the behaviour is unchanged.
  - Wording to use: `…and on Starlette 0.41.3 os.stat refused one in the path of a static file (500); 1.10.0 answers 404
    (staticfiles.py:132-134)`.

**The rest holds:**
- `RequestBody` is a pydantic `model_validator`, so it does not depend on the framework version.
- `TierError` keeps its handler through the MRO lookup.
- The `ValueError` handler is removed as before.

**#647 (`fix/626-non-utf8-names`, `ab6b36a`)**

- **Conflicts:** `docs/14` 1, citations lock 1, both line numbers. `core/docs.py` merges cleanly.
- **Framework dependency:** none. Its source diff touches no Starlette or FastAPI API.
- **Run 13:** `test_non_utf8_names_626` and `test_non_utf8_review_647` on the merged tree, new pins. **36 passed**.

### 6. The CVE: confirmed; #649's two answers now conform; one #649 item remains

`r1-outputs/probes/range_probe.py` (`range-probe.txt`), best of three, `FileResponse._parse_range_header("bytes=" + "0"*n + "a-", 1_000_000)`:

| n | 0.41.3 | 1.10.0 |
|---|---|---|
| 2000 | 0.0415 s | 0.000026 s |
| 4000 | 0.167 s | 0.000038 s |
| 8000 | 0.689 s | 0.000069 s |
| 16000 | 2.768 s | 0.000131 s |

- **The growth.** On 0.41.3, doubling `n` quadruples the time. On 1.10.0 it doubles it.
- **Through StaticFiles** with the 16 kB header: 400 in 2.99 s on 0.41.3, and in 0.034 s on 1.10.0.
- **The 416 now conforms.** It sends `Content-Range: bytes */17`, where 0.41.3 sent `*/17`. RFC 9110 section 14.4 gives
  `unsatisfied-range = "*/" complete-length` after the range unit.
- **The multipart 206 now conforms.**
  - `Content-Type: multipart/byteranges; boundary=…` and no `Content-Range` in the header section. 0.41.3 put the multipart
    type in `Content-Range`.
  - The parts are framed with CRLF; 0.41.3 used LF.
- **Still nonconforming, and #649's own step:** `Range: widgets=1-2` is 400 "Only support bytes range" on both versions.
  RFC 9110 section 14.2 says "An origin server MUST ignore a Range header field that contains a range unit it does not
  understand". The README leaves this to #649 step 1, which is correct.

### 7. The new test file: every assertion can fail

| Test | Fails under |
|---|---|
| `test_the_installed_package_is_patched` ×7 | the old pins: each names its advisory (run 03) |
| `test_pyproject_pins_a_patched_starlette` | base's pyproject, "does not pin starlette" (run 03); M6 `starlette==1.3.0` (run 09); M7 `starlette>=1.10.0` (run 10) |
| `test_the_range_parse_of_the_cve_is_not_quadratic` | the old pins (run 03) |
| `test_a_static_file_answers_the_cve_range_at_once` | the old pins (run 03) |
| `test_the_range_answers_that_starlette_1_fixed` | the old pins (run 03) |
| `test_a_route_of_an_included_router_is_one_of_api_routes` | M1 (run 04); the old base (ImportError) |
| `test_head_stays_on_a_route_when_its_router_changes` | M3 (run 06); M1 (run 04) |

On the old pins all 13 tests fail, each for its own reason (`runs/03-…`).

## 3. Findings, each with its fix and its test (all in `r1-outputs/fix.diff`)

### M1 (Medium): the permission-table test passes when the route walk misses every included route

**Where:** `cmapi/tests/service/test_review_c_authz.py`, `test_declared_permission_is_the_enforced_one_and_every_route_answers`.
It is the test that compares each route's declared permission with the one it enforces, and checks that an anonymous
caller gets 401 and the viewer and onboarding roles get 403 (`docs/14`, which cites it).

**What is wrong:** under mutant M1, the table holds only the app's own routes and no `/api` route. `assert not bad, bad`
is then true for an empty set, and the test passed (run 04). That is the failure this upgrade causes, and the guard did
not exist.

**Fix:**

```python
    with capsys.disabled():
        print("\n" + "\n".join(rows))
    # The walk saw every operation of the document: a walk that misses the included routers (app.routes after FastAPI
    # 0.137.0, #651) leaves the table empty, and an empty table has nothing bad in it.
    spec = c.get("/openapi.json").json()
    documented = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    assert len(documented) > 30 and documented <= set(answers), sorted(documented - set(answers))
    assert not bad, bad
```

The test (the fixed test is its own test): it fails under M1 (run 16) and passes on head (run 15). The fix also moves two
`docs/14` citations by five lines (`test_review_c_authz.py:119-182` → `124-187`, `197-207` → `202-212`), with
`docs/citations.lock.json`, using `scripts/doc-citations.py --relocate`. After it, `--check` reports 0 problems, run in a
throwaway git copy.

### L1 (Low): the README's row for Starlette 1.7.0 says "None", and the code and tests refute it

**Where:** `docs/reviews/2026-11-24-issue-651/README.md`, the Starlette table.

**What is wrong:**
- The row says "None". The PR added the `send` override because of 1.7.0, and without it 15 tests fail (M5, run 08).
- The row quotes half of the release note. The preflight's new `Vary` (measured in `cors-compare.txt`) is in no record.

**Fix:** the row, replaced:

```
| 1.7.0 | "Include `Vary: Origin` on all normal CORS responses and vary preflight responses by all request headers that affect them" | **Changed.** `CORSMiddleware.send` now appends Origin to the Vary of every answer for no origin or an origin not listed, and joins the lines into one, also when a line holds Origin or `*` (`cors.py:170`): `Vary: Origin, Origin`, `*, Origin`. `OriginVaryCORSMiddleware.send` puts the application's lines back before `vary_send` adds Origin once; without it `test_read_preconditions_590_593` fails. A preflight now answers `Vary: Origin, Access-Control-Request-Method, Access-Control-Request-Headers, Access-Control-Request-Private-Network` where 0.41.3 answered `Vary: Origin`: kept, and pinned by `test_cors.py`, `test_a_preflight_varies_on_each_request_header_that_decides_it` (reviewer 1) |
```

**Test** (`test_cors.py`, added after `test_each_answer_varies_on_origin_so_a_cache_keeps_the_copies_apart`):

```python
@pytest.mark.parametrize("origin", [PORTAL, OTHER])
def test_a_preflight_varies_on_each_request_header_that_decides_it(world, origin):
    """Starlette 1.7.0 (https://starlette.dev/release-notes/, read 2026-11-24): "vary preflight responses by all request
    headers that affect them". The answer to a preflight depends on Origin and on the method and headers that it asks
    for, so a shared cache must not give one preflight's answer to another (#651 review)."""
    client, *_ = world
    r = preflight(client, origin)
    varied = {v.strip(" \t").lower() for line in r.headers.get_list("vary") for v in line.split(",")}
    assert {"origin", "access-control-request-method", "access-control-request-headers"} <= varied, r.headers.get_list("vary")
```

It fails on base with the old pins (run 18) and passes on head with the new pins (run 17).

### L2 (Low): `docs/15` names only Starlette 0.41.3, and its `Vary` row leaves out the preflight

**Where:** `docs/15-keycloak-integration.md`: the `Vary: Origin` row of the CORS table, the "Measured" line and "Sources".

**Fix:**
- The row says that a preflight's answer also varies on `Access-Control-Request-Method`,
  `Access-Control-Request-Headers` and `Access-Control-Request-Private-Network` (Starlette 1.7.0, #651).
- "Measured" says 57 tests, from `--collect-only`: 55 before, 57 with the two new cases.
- "Sources" adds Starlette 1.10.0's `cors.py`, read on 2026-11-24.

**Test:** the L1 test pins the behaviour that the row states.

### L3 (Low): the local guide still names FastAPI 0.115

**Where:** `examples/local/INSTALL.md:51` ("FastAPI 0.115") and `:144` ("`requirements.txt` pins fastapi 0.115.6, …").
The PR moved the pin to 0.162.2 and added starlette 1.10.0. The list at line 144 already lacked google-re2 and jsonschema.

**Fix:** the guide names no version, and says `requirements.txt` pins each package:

```
| Python | 3.11 or newer (3.13 tested) | The cmapi reference modules and the API (FastAPI, Starlette, uvicorn, PyJWT, httpx; `requirements.txt` pins each) |
```
```
`requirements.txt` pins each package to one version, FastAPI and Starlette among them (#651); the file is the
list, so this page names no version. The cmapi modules themselves are not installed. They are imported
from `../src` with `PYTHONPATH=../src:.`
```

**Test:** new, `cmapi/tests/core/test_local_pins_doc_651.py`. It runs in both the service job's `tests/core` and the
reference-code job, through the `examples/tests` symlink. It fails on the PR head ("INSTALL.md:51: FastAPI 0.115, pinned
0.162.2", and line 144) and passes with the fix (`runs/20-pins-doc-before-after.txt`):

```python
"""#651 review: the local run's guide names no version of a pinned package other than its pin.

examples/local/requirements.txt is the list that run.sh installs. INSTALL.md and README.md beside it said "fastapi 0.115.6"
and "FastAPI 0.115" after the pin moved to 0.162.2, so a reader followed a version the file no longer installs."""
from __future__ import annotations

import re
from pathlib import Path

LOCAL = Path(__file__).resolve().parents[3] / "examples" / "local"


def pins() -> dict[str, str]:
    out = {}
    for line in (LOCAL / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            out[re.sub(r"\[.*\]", "", name).strip().lower()] = version.strip()
    return out


def test_the_local_guides_name_only_the_pinned_versions():
    pinned = pins()
    assert {"fastapi", "starlette", "uvicorn"} <= set(pinned), pinned
    names = "|".join(re.escape(n) for n in sorted(pinned, key=len, reverse=True))
    # "fastapi 0.115.6", "FastAPI 0.115", "fastapi==0.115.6", "pyjwt[crypto] 2.10.1": a pinned name, then a version.
    mention = re.compile(rf"\b({names})(?:\[[^\]]*\])?\s*(?:==|\s)\s*v?(\d+(?:\.\d+)+)", re.IGNORECASE)
    wrong = []
    for doc in ("INSTALL.md", "README.md"):
        for n, line in enumerate((LOCAL / doc).read_text().splitlines(), 1):
            for name, version in mention.findall(line):
                pin = pinned[name.lower()]
                if not (pin == version or pin.startswith(version + ".")):
                    wrong.append(f"{doc}:{n}: {name} {version}, pinned {pin}")
    assert wrong == []
```

## 4. The patch

`review-654/r1-outputs/fix.diff` covers 8 files under `cmapi/`, `docs/` and `examples/local` only, with no bytecode. It was
built from a copy of the export head against the fixed copy. Applied with `patch -p1 -F0` to a fresh copy of
`head/{cmapi,docs,examples/local}`, it applies cleanly and reproduces the fixed tree (`diff -rq` finds no difference).

## 5. Runs

All are in `r1-outputs/runs/`.
- **Database:** every pytest run used `cmapi_wt605`, after the gate `until ! pgrep -f "[p]ytest tests/service -q"`.
- **Cluster:** none.
- **Venvs:** the implementer's `venv` (new pins) and `venv-old` (old pins), unchanged.

| Run | Tree, pins | Result |
|---|---|---|
| 00 | head, `examples/` reference code (`venv-examples`, new pins) | 748 passed, 113 skipped |
| 01 | head, new: `test_framework_upgrade_651`, `test_head_605`, `test_cors`, `test_read_preconditions_590_593`, `test_api_docs`, `test_review_c_authz`, `test_plugins_switch`, `test_dry_run_refused_606`, `test_static_preconditions_604`, the probe | 329 passed |
| 02, 02b | base, old: the probe; base-old against head-new | documents byte-identical; 52 routes identical; only the no-Content-Type answer differs |
| 03 | base, old, with the new test file | 13 failed, each for its own reason |
| 04 | M1 `api_routes` = `app.routes` | 21 failed, 72 passed: the authz table test passed (M1 finding) |
| 05 | M2 `_WithoutHead` no-op | 2 failed |
| 06 | M3 no HEAD on the original route | 2 failed |
| 07 | M4 no HEAD on the context | 1 failed |
| 08 | M5 no `send` override | 15 failed (`test_read_preconditions_590_593`), 148 passed (`test_cors` passes) |
| 09, 10 | M6 `starlette==1.3.0`, M7 `starlette>=1.10.0` | 1 failed each |
| 11 | #645 `9de8199` merged, with the resolution above | 122 passed |
| 12 | #652 `0ff4324` merged | 1 failed (`test_every_request_body_is_a_request_body`), 75 passed |
| 13 | #647 `ab6b36a` merged | 36 passed |
| 14 | #652 merged, with the fix above | 1 passed |
| 15, 16 | M1 finding's test on head / under M1 | 1 passed / 1 failed: the 40 documented operations are missing from the table |
| 17, 18 | L1 test on head with new pins / base with old pins | 2 passed / 2 failed (`Vary: Origin` only) |
| 20 | L3 test on head / with the fix | 1 failed / 1 passed |

## 6. Not done

- The whole service suite: not run, as the brief says.
- The image build, CI, CRC and kind: not run.
- The portal suites: not run; the document is byte-identical, so its generated types are unchanged.
- **The first chain of runs did not run.** Its outputs had relative paths after a `cd`. It was found and rerun with
  absolute paths, and every result above comes from the rerun.
