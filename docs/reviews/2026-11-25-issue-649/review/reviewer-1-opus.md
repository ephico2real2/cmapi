# PR #665 (#649): reviewer 1's report

Reviewer 1: Opus 5.5 at `high`, in Codex's place (Codex was at its usage limit). I did not write this change. Run on
2026-11-25 (UTC) on the development Mac. I used the export only, PostgreSQL 16 on `127.0.0.1:55432`, database
`cmapi_r1_665`, and the new-pins venv (FastAPI 0.162.2, Starlette 1.10.0). No cluster was used.

Outputs are in `r1-outputs/`. The sources I fetched are in `r1-outputs/sources/`.

## Findings

| # | Severity | What | Test that decides it | Before (head) | After (fix.diff) |
|---|---|---|---|---|---|
| F1 | Low | The 304 of `/static` has no `Accept-Ranges` field, so a cache keeps the `Accept-Ranges: bytes` that it stored from the image before #649 | `test_a_304_says_accept_ranges_none` (2 paths × GET, HEAD × If-None-Match, If-Modified-Since) | 2 failed | passed |
| F2 | Low | Test gap: nothing fails if the scope is changed in place instead of copied | `test_the_request_keeps_its_range_header` | passes on head; fails on mutant M4 | passed |
| F3 | Low | Docs gap: no user-facing doc says that `/static` ignores Range or sends `Accept-Ranges: none` | none possible (prose); `doc-citations.py --check` gives 0 problems after the patch | — | rows added to docs/04 and docs/08 |

Everything else I checked holds (see "Confirmations").

### F1 (Low): the 304 keeps a stale `Accept-Ranges: bytes` in caches

**Facts.**
- On head, a 304 from `/static` carries only `etag` and `x-request-id`. This was measured in `r1-outputs/run-head.txt`:
  `Headers({'etag': '"71276735…"', 'x-request-id': '…'})`.
- The reason is Starlette 1.10.0. `NotModifiedResponse` (staticfiles.py:23-37) keeps only `cache-control`,
  `content-location`, `date`, `etag`, `expires` and `vary`. The PR sets `accept-ranges` only `if isinstance(response,
  FileResponse)`.
- RFC 9111 §3.2 (https://www.rfc-editor.org/rfc/rfc9111.txt, fetched 2026-11-25 01:34Z): "When doing so, the cache MUST
  add each header field in the provided response to the stored response, replacing field values that are already
  present". §4.3.4: "the cache MUST update its header fields with the header fields provided in the 304 (Not Modified)
  response, as per Section 3.2." A field that the 304 omits therefore keeps its stored value.
- The stored 200 matches the new 304 across images. `cmapi/Containerfile:55-56` extracts the bundles with `tar xzf` from
  the npm tarballs. The npm tarball fixes each file's mtime: `tar tvzf swagger-ui-dist-5.34.1.tgz
  package/swagger-ui-bundle.js` gives `1685697 Oct 26 1985`. Starlette's ETag is the md5 of `mtime-size`
  (responses.py, `set_stat_headers`), so the ETag is identical in every image built from one Swagger UI or ReDoc version.
  A browser that stored the bundle before #649 revalidates with `If-None-Match`, gets the 304, and keeps
  `Accept-Ranges: bytes`.
- Sending the field on a 304 is allowed. RFC 9110 §15.4.5 says a sender "SHOULD NOT generate representation metadata
  other than the above listed fields unless said metadata exists for the purpose of guiding cache updates". §8.2 defines
  representation metadata as the representation header fields. Accept-Ranges is a range field of §14.3, not
  representation metadata, and here it exists to update caches.

**Impact.** Advisory only. §14.3: "A client MAY generate range requests regardless of having received an Accept-Ranges
field", and the server sends 200 whatever the client asks. It is Low, but it contradicts the PR's own claim that every
answer says `none`.

**Fix** (`cmapi/src/cmapi/main.py`; the line count is unchanged, so none of the 9 citations moves):

```python
    def file_response(self, full_path: PathLike, stat_result: os.stat_result, scope: Scope,
                      status_code: int = 200) -> Response:
        """FileResponse says `Accept-Ranges: bytes`. Section 14.3: "A server that does not support any kind of range request
        for the target resource MAY send Accept-Ranges: none to advise the client not to attempt a range request". The 304
        says it too: a cache updates a stored 200 with each field of the 304 (RFC 9111, section 3.2), and a bundle keeps its
        ETag from image to image (the npm tarball fixes its mtime), so a 200 stored before #649 said `bytes`."""
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["accept-ranges"] = "none"
        return response
```

The fix also removes the now-unused `from starlette.responses import FileResponse`. `super().file_response` returns
either a `FileResponse` or a `NotModifiedResponse`, or raises the 412 `Problem`, so no other response type reaches this
line.

**Test** (appended to `test_static_range_649.py`):

```python
@pytest.mark.parametrize("path", PATHS)
def test_a_304_says_accept_ranges_none(bundles, world, path):
    """RFC 9111 (https://www.rfc-editor.org/rfc/rfc9111.txt, read 2026-11-25), section 3.2: ... (full text in fix.diff)"""
    client, *_ = world
    whole = client.get(path)
    for method in ("GET", "HEAD"):
        for validator in ({"If-None-Match": whole.headers["etag"]}, {"If-Modified-Since": whole.headers["last-modified"]}):
            r = client.request(method, path, headers=validator)
            assert (r.status_code, r.headers.get("accept-ranges")) == (304, "none"), (method, validator, r.headers)
```

Results: head 2 failed (`r1-outputs/proof-head-run.txt`); fixed 21/21 passed (`proof-fixed.txt`). On the fixed tree
`test_static_preconditions_604.py` and `test_head_605.py` also pass, 100 passed in all (`run-fixed.txt`).

### F2 (Low): no test guards the copy of the scope

The ASGI spec, "Middleware" (https://github.com/django/asgiref/blob/main/specs/asgi.rst, fetched 2026-11-25), says:
"When middleware is modifying the ``scope``, it should make a copy of the ``scope`` object before mutating it and passing
it to the inner application, as changes may leak upstream otherwise."

The code does copy. However, mutant M4 (`r1-outputs/m4-in-place.diff`: `scope["headers"] = [...]` in place) passes all
18 of the PR's tests (`run-m4-in-place.txt`: the PR's 18 pass, and only my scope test fails). The fix is the test only:
`test_the_request_keeps_its_range_header`, in `fix.diff`. It calls `ConditionalStaticFiles` at the ASGI level and asserts
that the caller's scope still holds `range` after the call.

| Tree | Result |
|---|---|
| head | passes |
| M4 | fails (`proof-m4-in-place.txt`) |
| fixed | passes |

### F3 (Low): the docs do not say that `/static` ignores Range

`/static`'s conditional behaviour is documented in `docs/04-api-examples.md` (the "Conditional reads" rule),
`docs/08-code-status.md` (the "ETag" row) and `docs/GLOSSARY.md`. None of them mentions Range or `Accept-Ranges` after
this PR. The only mention is `HANDOVER-AND-RESUME.md:40`.

`fix.diff` adds:
- a `Range` row to docs/04's rules table, in the hand-written part above `<!-- examples:begin -->`;
- a "`Range` on `/static`" row to docs/08's API documentation table, naming `test_static_range_649.py`.

The docs/04 row says "No other route reads `Range`". `grep -rn -i "FileResponse|\"range\"|StaticFiles(" cmapi/src`
finds only `ConditionalStaticFiles`, and `test_r1_no_route_outside_static_sends_accept_ranges` passes on head.

## Confirmations (each decided by a test)

### 1. Dropping `range` from the scope copy stops every range path in Starlette 1.10.0

Read from the source:
- `FileResponse.__call__` reads `headers = Headers(scope=scope); http_range = headers.get("range")` from the scope that
  it is called with.
- `StaticFiles.__call__` passes its scope to `get_response`, then to `file_response` (staticfiles.py:104, :138), and
  calls `await response(scope, receive, send)` (:105).
- With `http_range is None`, the `if` takes `_handle_simple`. `_parse_range_header`, `_handle_single_range` and
  `_handle_multiple_ranges` are only reached in the `else` branch.

Measured:

| Tree | Result |
|---|---|
| M1 (no copy) | 16 failed: GET 500, because the parser was called |
| M3 (GET only) | 16 failed: HEAD 500 |
| head | 18/18 |

**If-Range without Range.** If-Range is read only inside the condition, as `(http_if_range is not None and not
self._should_use_range(...))`. With `http_range is None` the earlier `or` term already selects the simple path, so
If-Range changes nothing. RFC 9110 §13.1.5: "A server MUST ignore an If-Range header field received in a request that
does not contain a Range header field."

`test_r1_if_range_alone_changes_nothing` sends a matching ETag, a non-matching ETag, a weak ETag, the Last-Modified date
and a past date, with GET and HEAD. It passes on base and on head: 200, the whole file, no Content-Range.

### 2. Behaviour unchanged where it should be

On head, 146 tests: 144 passed, and the 2 failures are F1 (`run-head.txt`). They cover:
- `test_static_range_649`, `test_r1_665`, `test_framework_upgrade_651`;
- `test_static_preconditions_604`: ETag, Last-Modified, 304, and the 412 of #604, #619 and #620;
- `test_head_605`: HEAD with no content;
- `test_framework_problems_646` and `test_router_problems_644`: the 404 and 405 problems.

My own checks:

| Check | Base | Head |
|---|---|---|
| 412 for a stale If-Match, and for If-Unmodified-Since in 1994, both beside a Range; RFC 9457 `precondition-failed`, no Accept-Ranges | holds | holds |
| 304 for If-Modified-Since beside a Range | holds | holds |
| 404 `not-found` and 405 `method-not-allowed` (Allow `GET, HEAD`) under a Range; problem JSON, no Accept-Ranges | — | holds |
| CORS: `Origin` of the listed portal plus Range | 206 with ACAO | 200 with ACAO and `Accept-Ranges: none`; the 304 has ACAO |

Base fails my 412 test only at its last step, `If-Match` that holds plus Range, which gives 206 on base
(`run-base.txt`, line 55 of the test). The 412 steps before it pass on base.

The 405 handler reads `request.scope["endpoint"]`. The router sets that key in place (routing.py:202, `scope.update`)
before the copy, so the copy does not affect it.

### 3. `Accept-Ranges: none` on every `/static` answer, and nowhere else

GET and HEAD 200s carry it: the PR's tests pass on head, and mutant M2 fails 16. The 304 does not carry it: that is F1.

No 412, 404 or 405 carries it. Neither do the following, with GET and HEAD and a Range header, each without a 206:
- `/healthz`, `/api/v1/version`;
- `/docs`, `/redoc`, `/openapi.json`, `/openapi.yaml`, `/docs/changelog`, `/docs/redoc-start.js`, `/docs/swagger.css`,
  `/docs/oauth2-redirect`;
- `/problems`, `/problems/not-found`, an unknown path;
- an authenticated `GET /api/v1/tiers`.

The test is `test_r1_no_route_outside_static_sends_accept_ranges`, which passes on head.

### 4. The 9 relocated citations

Read in `head/cmapi/src/cmapi/main.py`. Each one points at the code its sentence describes.

| Citation | Lines say | Sentence |
|---|---|---|
| docs/14 197-199 | `authed_routers = (...)`, `include_router(r, dependencies=[Depends(authed)])` | core and plugin routers have the token check ✓ |
| docs/14 194-195 | `include_router(health.router)`, `(health.version_router)` | health routers, no dependency ✓ |
| docs/14 382-396 | `_add_problem_pages`, both `/problems` routes, no guard | always public ✓ |
| docs/14 457-459 | `@app.get("/docs/oauth2-redirect")`, no `dependencies` | no guard ✓ |
| docs/14 407 | `guard = [] if docs_cfg.get("public", True) else [Depends(authed)]` | public unless docs.public false ✓ |
| docs/14 355-356 | `if docs_enabled: _add_docs(...)` | exist unless docs.enabled false ✓ |
| docs/14 232-233 | `if s.metrics_port: start_metrics(...)` | /metrics on its own port ✓ |
| docs/14 267-269 | `problem_handler` with `unauthenticated_headers(exc)` | the WWW-Authenticate of each 401 ✓ |
| docs/15 192-193 | `swagger_ui_init_oauth={"clientId": "cmapi-docs", "usePkceWithAuthorizationCodeGrant": True, ...` | Swagger UI, PKCE, `cmapi-docs` ✓ |

Every range moved by +23, the 23 lines that the PR adds above them. `scripts/doc-citations.py --check` gives "0
problems", both on a throwaway `git init` copy of head and on the patched tree. `fix.diff` keeps `main.py`'s line count
(597), so no citation moves.

### 5. The rewritten `test_the_range_answers_that_starlette_1_fixed`

It now mounts Starlette's own `StaticFiles` over the same bundle. I ran its body, copied line for line
(`r1-outputs/probes/rewrite_651_body.py`), under both Starlettes (`run-651-rewrite-0.41.3-vs-1.10.0.txt`):

| Starlette | Result |
|---|---|
| 0.41.3 | 4 of 5 assertions fail: 416 `*/17` without the unit, multipart Content-Type missing, Content-Range present, LF framing |
| 1.10.0 | all pass |

So it still proves what #651 proved: the installed Starlette's range code has the three fixes. That is the evidence that
removing the override would be safe. The whole test file cannot run on 0.41.3, because `cmapi.core.docs` needs FastAPI
≥0.137's `RouteContext` (`run-651-rewrite-on-starlette-0.41.3.txt`), so I ran the body standalone.

What it no longer proves is cmapi's served answer to a Range, which by design is now 200. Two other tests keep the CVE
covered:
- `test_the_range_parse_of_the_cve_is_not_quadratic` still exercises the parser directly;
- `test_a_static_file_answers_the_cve_range_at_once` is now a timing guard through the app that never reaches the parser.

### 6. Can each assertion fail?

The PR's `test_static_range_649.py`, measured:

| Tree | Result | Cause |
|---|---|---|
| base | 16 failed, 2 passed | the 2 are the 304 guard, as the implementer said |
| M1 (no copy) | 16 failed | 500, parser called |
| M2 (no `Accept-Ranges`) | 16 failed | `accept-ranges` is `bytes` |
| M3 (GET only) | 16 failed | HEAD 500 |
| M4 (in place) | 0 failed | F2 |
| head | 18 passed | |

The two revalidation tests cannot fail on any of M1 to M4. They are a guard of behaviour that already held, as the record
says.

## Quotes verified (fetched 2026-11-25, 01:34Z)

**RFC 9110** (https://www.rfc-editor.org/rfc/rfc9110.txt). Every quote in the implementer's record matches the text:
- §14.2: "A server MAY ignore the Range header field"; "ought to support byte ranges when possible"; the HEAD sentence
  ("…GET is the only method for which range handling is defined."); "An origin server MUST ignore a Range header field
  that contains a range unit it does not understand"; "Range is ignored when a conditional GET would result in a 304".
- §14.3: `Accept-Ranges: none`; "A client MAY generate range requests regardless…".
- §14.4: the ABNF, and "only the 206 (Partial Content) and 416 (Range Not Satisfiable) status codes describe a meaning
  for Content-Range".
- §15.5.17's note.
- §17.15: "ignore, coalesce, or reject egregious range requests".
- §13.1.5.

**Errata** (https://www.rfc-editor.org/errata/rfc9110): 14 errata. None is on §14.2. Errata ID 7306 is on §14.1.1, OWS in
`ranges-specifier`, Verified.

**ASGI.**
- www.rst, Version 2.5 (2024-06-05): "Header names should be lowercased, but it is not required" ✓.
- asgi.rst, Middleware: quoted under F2 ✓. Middleware may change the scope if it copies it first, which the PR does.

**Starlette 1.10.0** (the venv's source):
- the `_parse_range_header` message "Only support bytes range" ✓;
- `scope["method"].upper() not in ("GET", "HEAD")` ✓;
- `accept-ranges` `setdefault` ✓;
- the six-field `NotModifiedResponse` ✓;
- the `file_response(full_path, stat_result, scope, status_code=200)` signature ✓;
- the release note "Ignore `Range` on requests other than `GET` and `HEAD` in `FileResponse`" (#3679, 1.10.0) ✓.

**Cloudflare** (https://developers.cloudflare.com/cache/reference/range-requests/): the HEAD sentence ✓.

**nginx** `proxy_force_ranges` (default `off`): "Enables byte-range support for both cached and uncached responses from
the proxied server regardless of the “Accept-Ranges” field in these responses." ✓

## What I did not test

- The front door (nginx) in front of `/static`.
- A browser loading `/docs` and `/redoc`.
- The whole service suite.
- CRC or kind.

## Deliverable

`r1-outputs/fix.diff`: 94 lines, against `head/`. It touches:
- `cmapi/src/cmapi/main.py`;
- `cmapi/tests/service/test_static_range_649.py`;
- `docs/04-api-examples.md`;
- `docs/08-code-status.md`.

`patch -p1 -F0` applies cleanly on a fresh copy of head, and each file is then byte-identical to my fixed tree. On the
patched tree, `py_compile` passes and `doc-citations.py --check` gives 0 problems.

My extra checks are in `r1-outputs/test_r1_665.py`, 13 tests. They are evidence, not part of the patch.
