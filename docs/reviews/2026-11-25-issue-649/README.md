# #649: every file under `/static` is sent whole, whatever the Range header says

The implementer's record, written by Opus 5.5 at `high` on 2026-11-25, on `fix/649-static-ignores-range` from `0a85b4d`.
Part of #481.

#649 had two steps. Step 2, the upgrade to a Starlette without CVE-2025-62727, was done by #651 (PR #654: FastAPI 0.162.2,
Starlette 1.10.0). This change is step 1: `ConditionalStaticFiles` ignores Range, so each file of `/static/swagger` and
`/static/redoc` is sent whole with 200 (or 304), and says `Accept-Ranges: none`.

## What Starlette 1.10.0 still answers

`probes/static_range_probe.py` mounts cmapi's own `ConditionalStaticFiles` over a 17-byte file, as the service tests'
`bundles` fixture does. On `0a85b4d` (`outputs/static-range-probe-before.txt`):

| Range | GET | HEAD |
|---|---|---|
| `bytes=1-2`, `bytes=-5` | 206, `Content-Range: bytes 1-2/17`, `bytes 12-16/17` | 206, the same headers |
| `bytes=99-` (past the end) | 416, `Content-Range: bytes */17`, empty `text/plain` | 416 |
| `oops`, `bytes=5-1` | 400 `text/plain`, "Malformed range header." / "Range header: start must be less than end" | 400 |
| `widgets=1-2` | 400 `text/plain`, "Only support bytes range" | 400 |
| `bytes=0-0,5-6` | 206 `multipart/byteranges`, CRLF framing | 206 |
| the CVE payload, 16 000 digits | 400 `text/plain`; the parse takes 0.00013 s (#651's measure) | 400 |
| none | 200, `Accept-Ranges: bytes` | 200 |

The 416 unit, the multipart `Content-Type` and the CRLF framing are fixed, as #651 measured, and the parse is linear. Three
things are not:

1. **Another unit is refused.** RFC 9110, section 14.2: "An origin server MUST ignore a Range header field that contains a
   range unit it does not understand." Starlette answers 400 (`responses.py`, `FileResponse._parse_range_header`:
   `if units != "bytes": raise MalformedRangeHeader("Only support bytes range")`).
2. **HEAD gets ranges.** Section 14.2: "A server MUST ignore a Range header field received with a request method that is
   unrecognized or for which range handling is not defined. For this specification, GET is the only method for which range
   handling is defined." Starlette 1.10.0 serves Range for GET and HEAD (`FileResponse.__call__`:
   `scope["method"].upper() not in ("GET", "HEAD")`; its 1.10.0 note is "Ignore `Range` on requests other than `GET` and
   `HEAD`"). Practice differs: Cloudflare's documentation says "A `HEAD` request containing `Range` can return `200 OK`,
   `206 Partial Content`, `304 Not Modified`" or "`416 Range Not Satisfiable`"
   (https://developers.cloudflare.com/cache/reference/range-requests/, read 2026-11-25). None of the 14 errata of RFC 9110
   names section 14.2 (https://errata.rfc-editor.org/rfc9110, read 2026-11-25 01:20Z); the one on section 14 is 14.1.1
   (Errata ID 7306, whitespace in `ranges-specifier`).
3. **Its refusals are plain text.** The 400 and the 416 are `text/plain`, not the RFC 9457 problem that every other refusal
   of cmapi is (docs/02, "Problem type URIs"; #644, #646). StaticFiles returns them as responses, not as `HTTPException`, so
   `create_app`'s handlers never see them.

## The choice

**Ignore Range on `/static`, as the issue's step 1 said.** The question the brief asked: now that Starlette 1.10.0
conforms better, is ignoring Range still the best practice, or does only the unknown unit need a fix?

The sources, read 2026-11-25 (`https://www.rfc-editor.org/rfc/rfc9110.txt`, fetched 01:17Z, saved under the notes of the
implementer):

- Section 14.2: "A server MAY ignore the Range header field. However, origin servers and intermediate caches ought to
  support byte ranges when possible, since they support efficient recovery from partially failed transfers and partial
  retrieval of large representations."
- Section 14.2: "An origin server MUST ignore a Range header field that contains a range unit it does not understand."
- Section 14.3: "A server that does not support any kind of range request for the target resource MAY send
  `Accept-Ranges: none` to advise the client not to attempt a range request on the same request path." And: "A client MAY
  generate range requests regardless of having received an Accept-Ranges field."
- Section 14.4: `Content-Range = range-unit SP ( range-resp / unsatisfied-range )`, `unsatisfied-range = "*/"
  complete-length`; "only the 206 (Partial Content) and 416 (Range Not Satisfiable) status codes describe a meaning for
  Content-Range."
- Section 15.5.17's note: "Because servers are free to ignore Range, many implementations will respond with the entire
  selected representation in a 200 (OK) response. That is partly because most clients are prepared to receive a 200 (OK)
  to complete the task (albeit less efficiently) and partly because clients might not stop making an invalid range request
  until they have received a complete representation."
- Section 17.15: "Servers ought to ignore, coalesce, or reject egregious range requests".

The options:

| Option | What it takes | Decision |
|---|---|---|
| Ignore Range on `/static` | Drop the header from the scope before StaticFiles reads it; say `Accept-Ranges: none` | **Chosen** |
| Fix only the unknown unit | Drop Range when its unit is not `bytes`; keep 206 for bytes | Rejected: leaves HEAD's ranges against section 14.2, and the plain-text 400 and 416; making those RFC 9457 problems means re-implementing Starlette's range answers in cmapi |
| Keep Starlette's answers | Nothing | Rejected: the MUST of section 14.2 |

Why ignoring is right here, from the facts:

- **Nothing uses a range of these files.** They are the Swagger UI and ReDoc bundles that `/docs` and `/redoc` load with a
  `<script src>` (Swagger UI), an ES module `import` (`/docs/redoc-start.js`) and a stylesheet `@import`
  (`/docs/swagger.css`), all in `main.py`; a browser fetches each whole. Section 14.2's "ought to
  support" is for "recovery from partially failed transfers and partial retrieval of large representations"; neither is a
  use of `/static`. If a measured need appears, the override goes and Starlette's own answers come back
  (`test_framework_upgrade_651.py`, `test_the_range_answers_that_starlette_1_fixed`, keeps them proven on Starlette's own
  StaticFiles).
- **It fixes the cause.** The cause is Starlette's range code on a path that needs no token and no range. Ignoring Range
  removes every answer above, and any later defect of that code (CVE-2025-62727 was one), with no range code in cmapi.
  Fixing the unit alone treats one symptom.
- **The front door adds no range of its own.** `cmapi-portal-ui/nginx/templates/cmapi.conf.template` proxies
  `/static/swagger/` and `/static/redoc/` with `proxy-docs.conf`, with no `proxy_cache` and no `proxy_force_ranges`. nginx's
  documentation: `proxy_force_ranges` (default `off`) "Enables byte-range support for both cached and uncached responses
  from the proxied server regardless of the "Accept-Ranges" field in these responses"
  (https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_force_ranges, read 2026-11-25 01:18Z).
  Not tested through the front door.
- **`Accept-Ranges: none`, not `bytes`.** FileResponse sets `accept-ranges: bytes` on every answer (`setdefault`). Sending
  it while ignoring Range would advise clients to try what is never served; section 14.3 names `none` for this case.

## The code

`cmapi/src/cmapi/main.py`, `ConditionalStaticFiles`:

- `__call__` copies the scope without its `range` headers and calls StaticFiles. Starlette's `FileResponse.__call__` reads
  Range from the scope it is given (`Headers(scope=scope).get("range")`), and StaticFiles passes its own scope to
  `file_response` and to the response, so the copy reaches both. The copy leaves the request's own scope as received.
  The name is compared lowercased: the ASGI spec says "Header names should be lowercased, but it is not required"
  (https://github.com/django/asgiref/blob/main/specs/www.rst, "HTTP Connection Scope", version 2.5, read 2026-11-25).
- `file_response` sets `accept-ranges: none` on the FileResponse. The 304 is StaticFiles' `NotModifiedResponse`, which
  keeps only `cache-control`, `content-location`, `date`, `etag`, `expires` and `vary`, so it is left as it is.

Checked against Starlette 1.10.0's `staticfiles.py` and `responses.py` in the new-pins venv: `file_response(full_path,
stat_result, scope, status_code=200)` keeps its signature, and `If-Range` without `Range` is ignored by FileResponse
(`http_range is None` takes the simple path). Section 13.1.5: "A server MUST ignore an If-Range header field received in
a request that does not contain a Range header field."

## Tests

`cmapi/tests/service/test_static_range_649.py`, 18 tests:

- `test_a_static_file_is_sent_whole_whatever_its_range`, for eight Range values (one range, a suffix range, unsatisfiable,
  malformed, reversed, another unit, two ranges, and the CVE-2025-62727 payload at 16 000 digits) and both mounts
  (`/static/swagger/swagger-ui-bundle.js`, `/static/redoc/redoc.standalone.js`): GET and HEAD, with and without a matching
  `If-Range`, answer 200 with no Content-Range, `Accept-Ranges: none`, and the Content-Length, Content-Type, ETag and
  Last-Modified of the whole file; the GET body is the whole file and the HEAD body is empty. A plain GET says
  `Accept-Ranges: none` too. `FileResponse._parse_range_header` is replaced by a function that fails the test if called.
- `test_a_range_does_not_stop_a_revalidation`, both mounts: GET and HEAD with each Range value and the current ETag in
  `If-None-Match` answer 304, with the ETag and no body. This one guards a behaviour that already held, so it passes
  before the fix too.

`test_framework_upgrade_651.py`, `test_the_range_answers_that_starlette_1_fixed`, asserted Starlette 1.10.0's 416 and
multipart 206 through cmapi's `/static`, which now answers 200. It now mounts Starlette's own StaticFiles over the same
bundle, with the same assertions, so the upgrade's evidence stays.

Every run: `CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_impl_649` (PostgreSQL 16 on the
development Mac; no cluster), `PYTHONPATH=src:tests/service`, the new-pins venv (FastAPI 0.162.2, Starlette 1.10.0), from
`cmapi/`.

| Run | Result | Output |
|---|---|---|
| `test_static_range_649.py` on `0a85b4d` | 16 failed, 2 passed (the 304 guard): each failed at `Accept-Ranges: bytes` | `outputs/test-649-before-fix.txt` |
| mutant A: the fix without `__call__` (Range reaches Starlette) | 16 failed, 2 passed: 500, the parser was called | `outputs/test-649-mutant-a.txt` |
| mutant B: the fix without `Accept-Ranges: none` | 16 failed, 2 passed: `Accept-Ranges: bytes` | `outputs/test-649-mutant-b.txt` |
| this branch: `test_static_range_649`, `test_framework_upgrade_651`, `test_static_preconditions_604`, `test_read_preconditions_590_593`, `test_head_605`, `test_framework_problems_646`, `test_api_docs` | 249 passed in 357.95 s | `outputs/targeted-after-fix.txt` |
| the probe, before and after | the table above, then 200 with `Accept-Ranges: none` and the whole 17 bytes for every Range, GET and HEAD; 304 with `If-None-Match` | `outputs/static-range-probe-before.txt`, `outputs/static-range-probe-after.txt` |
| `scripts/doc-citations.py --check` | 9 citations of `main.py` moved 23 lines down by the new code; `--relocate` moved them, then 0 problems | |

The mutants ran on exports of the worktree with one change each to `cmapi/src/cmapi/main.py`.

**Not tested:** the whole service suite; the front door (nginx) in front of `/static`; a browser loading `/docs` and
`/redoc` after the change; CRC or kind. The suites ran on the development Mac only.
