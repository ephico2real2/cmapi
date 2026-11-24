# PR #645 review · framework problem responses

**Request changes on #646.** The router changes in #644 work. A missing API object still gets its own problem type, every routed 405 I exercised has one complete `Allow` field, and uvicorn sends an empty HEAD body. The class handler, however, treats *every* framework 400 as malformed JSON. A disconnect during upload generated and logged a 422, and an injected read failure produced the same client-facing diagnosis. Conversely, some non-UTF-8 JSON documents reached authentication. Those outcomes contradict the new contract.

**The static 416 does not become 500.** On both exports it was an empty 416, with a plain-text media type and a malformed `Content-Range`. The range parser catches its own exception inside `FileResponse`. Registering a 416 handler in `create_app` alone cannot repair this. I found no stock cmapi route on these versions that turns a real 413, 415 or 416 into 500.

Reviewed the complete 378-line export against main `ff5e992`, read 2026-11-24. All proposed changes and regression tests appear in the appendices. The fixes were exercised in an isolated copy. File and line references below are to the original exports or the installed versions.

## Standards and dispatch evidence

All sources in this section were read on **2026-11-24**.

| Source | Short quotation | Consequence for this review |
|---|---|---|
| [RFC 9457 §3](https://www.rfc-editor.org/rfc/rfc9457.html#section-3) | “application/problem+json” | A JSON problem response has this media type. An empty or plain-text 416 cannot be decoded as that representation. |
| [RFC 9457 §3.1.2](https://www.rfc-editor.org/rfc/rfc9457.html#section-3.1.2) | “Generators MUST use the same status code in the actual HTTP response” | Compare the problem's numeric status to the outgoing HTTP status. The original exception status and an extension such as `errors[].code` are different quantities. |
| [RFC 9457 §4](https://www.rfc-editor.org/rfc/rfc9457.html#section-4) | “SHOULD resolve to HTML” | Define the type URI, title and associated HTTP status, and provide recovery guidance at the type URI. This imposes no requirement to invent an OpenAPI operation. |
| [RFC 9110 §15.5.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.1) | “malformed request syntax” | 400 fits an unparsable request. |
| [RFC 9110 §15.5.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.2) | “at least one challenge” | A 401 requires a valid authentication challenge. A process that cannot stat its own assets has nothing to challenge the caller for. |
| [RFC 9110 §15.5.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.6) | “currently supported methods” | The origin server must generate Allow for the target resource. The PR additionally promises one physical header field. |
| [RFC 9110 §15.5.21](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.21) | “the syntax of the request content is correct” | 422 describes understood media and syntactically valid instructions the service cannot process. Malformed JSON does not meet that description. |
| [RFC 8259 §8.1](https://www.rfc-editor.org/rfc/rfc8259.html#section-8.1) | “MUST be encoded using UTF-8” | Applies to JSON exchanged outside a closed ecosystem. This wire requirement does not prevent a library from accepting additional encodings. The parser may also impose nesting and number limits. [RFC 8259 §9](https://www.rfc-editor.org/rfc/rfc8259.html#section-9) |

Installed-source quotations below come from the requested venv, confirmed with `fastapi.__version__ == "0.115.6"` and `starlette.__version__ == "0.41.3"`. The installed source URL base is `file:///Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/`. The six requested URL suffixes are `starlette/_exception_handler.py`, `starlette/middleware/exceptions.py`, `starlette/routing.py`, `starlette/staticfiles.py`, `fastapi/routing.py` and `fastapi/exception_handlers.py`. Links open the local primary sources at the relevant lines.

| Installed source | Decisive code | What it does |
|---|---|---|
| [Starlette exception wrapper](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/_exception_handler.py:46) | `handler = status_handlers.get(exc.status_code)` | Only for an HTTPException. If absent, walk the exception class MRO. A response that has started cannot be replaced. |
| [Starlette exception middleware](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/middleware/exceptions.py:41) | `self._status_handlers[exc_class_or_status_code] = handler` | Integer registrations and exception classes populate different maps. The middleware makes both available in scope. |
| [Starlette routing](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/routing.py:283) | `raise HTTPException(status_code=405, headers=headers)` | The first partial match supplies only its own methods. No path match raises 404 at line 651. |
| [Starlette static files](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/staticfiles.py:119) | `raise HTTPException(status_code=401)` | This particular 401 catches PermissionError **during lookup**. Wrong method raises 405, absent or overlong path raises 404. Conditional reads return a response object. |
| [FastAPI routing](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/fastapi/routing.py:287) | `raise http_error from e` | Retains the underlying failure. JSONDecodeError has an earlier dedicated branch, and an existing HTTPException is re-raised. |
| [FastAPI exception handler](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/fastapi/exception_handlers.py:14) | `return Response(status_code=exc.status_code, headers=headers)` | Used when the status forbids a body. Otherwise the default is JSON containing `detail`, retaining exception headers. |
| [Starlette file responses](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/responses.py:354) | `except RangeNotSatisfiable as exc:` | Sends a 416 directly at lines 355–356. Malformed ranges have a separate direct 400. |
| [Starlette requests](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/requests.py:249) | `self._json = json.loads(body)` | Passes bytes to Python's decoder, enabling UTF-16/32 detection. The stream reader raises ClientDisconnect on an ASGI disconnect. |

## Findings and regression results

The identifiers here connect each finding to its **full fix in Appendix A** and **executable regression in Appendices B–C**. Severity reflects the observed impact. No High finding.

| Severity | Location and finding | Before → after; deciding test |
|---|---|---|
| **Medium · PR** | `main.py:275` labels transport, parser and service failures alike as `json_invalid`. Misleading clients also corrupt request-status telemetry. | Actual ASGI disconnect during a real body route emitted start/body and logged HTTP 422 → no response messages. Injected OSError from the reader gave 422 → sanitized 500. A synthetic independent 400 gave 422 → registered 400. See `test_disconnected_body`, `test_failed_reader`, `test_non_json_400`. |
| **Medium · new contract, inherited decoder** | `docs/02:152` promises rejection of non-UTF-8 JSON before auth, but the handler only sees decoder failures. Python accepted UTF-16 and UTF-32, with and without a BOM in the tested cases. | Four alternate encodings reached a 401 on the namespace POST → all four returned 422 with `json_invalid`. `test_json_encoding`. The fix enforces the published requirement only where FastAPI has chosen to decode JSON. |
| **Medium · inherited static range handling** | `ConditionalStaticFiles` inherits direct range responses. A 17-byte asset produced an empty 416 with `Content-Range: */17`; a malformed range produced plain-text 400. A range on HEAD incorrectly produced 416, and an unrecognized range unit produced 400. A successful multipart range put the boundary in the top-level Content-Range instead of Content-Type and used LF framing. | `test_range_problem`, `test_inapplicable_range`, `test_multipart_range`. Fixed results include registered 400/416 problems, `bytes */17`, ordinary 200 for inapplicable ranges, and a correctly framed multipart 206. Single-range 206 and conditional 304 still pass. The user's proposed “416 becomes 500” diagnosis would lead to a fix in the wrong layer. [RFC 9110 §14.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.2) · [§14.4](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.4) · [§15.3.7.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.3.7.2) |
| **Medium · inherited static read failure** | `FileResponse._handle_simple` sends 200 before opening the asset. A file can be stat-able but unreadable. In this case the permission exception never becomes Starlette's lookup-time 401 and the 200 has already escaped. | Kept real stat and injected PermissionError at the file open. Client observed 200 → 500 `internal-error`. `test_open_failure_before_first_byte`. Defer forwarding the start until the first body message. This covers failure before the first byte, without promising recovery once streaming has begun. |
| **Low · PR test gap** | `test_router_problems_644.py:77` checks a body that TestClient has already discarded. It cannot establish the HTTP wire invariant. | All 25 passed with a corrupt ASGI HEAD body. Four new wire checks failed when five bytes were deliberately appended after uvicorn serialized the headers, then passed on the unmodified transport. Appendix C is the complete test fix. No production change is needed for the measured HEAD responses. |
| **Low · inherited browser contract** | `core/cors.py:40` omits Allow from exposed headers. The new 405 page tells the caller to read that field, but a script on an explicitly allowed second origin cannot read it. | Cross-origin POST to the GET-only version endpoint got 405 with the right origin but no exposed Allow → Allow exposed. `test_cross_origin_allow`. Measured the server headers; browser visibility follows the [Fetch Standard](https://fetch.spec.whatwg.org/#cors-safelisted-response-header-name). |
| **Low · recovery documentation** | `core/problem_docs.py:22` claims the API reference lists every path. Problem pages and docs/static routes are outside the schema. The existing `docs/02:136` also promises clusterId and requestId in every problem body, inconsistent with the five-field router contract. | `test_missing_path_help_includes_registry` and `test_design_error_example`. Direct a missing-path caller to the operation reference or the separate problem registry, and show an actual router problem plus the request-correlation header. |

The range fixes address the pinned implementation's wire behavior. A dependency upgrade could replace the adapter **after** the same regressions pass on the candidate version. The review did not test a dependency upgrade.

## Disposition of the seven claims

### 1. Handler precedence and domain 404s

Confirmed, with one distinction important for future edits. An integer handler wins for a Starlette HTTPException of that status. A cmapi `Problem` inherits directly from `Exception`, so integer dispatch is never consulted. This is why the route's domain code survives. The two existing route checks passed on both trees. `GET /problems/no-such-type` executes an explicit `raise Problem(404, "object-not-found", ...)` at `main.py:317`. The authenticated capacity read of an unknown cluster returned `cluster-not-found` with the requested ID in its detail. A missing router path on head returned `not-found`, and removing the HTTPException **class** handler left these 404/405 tests green.

### 2. Every supported method and HEAD on the wire

Confirmed for the configured routes and two static mounts. I substituted a concrete parameter value into each APIRoute template, derived the expected methods independently from the matching path regexes, sent PUT, and checked HTTP 405, set equality and physical header count. The sweep covered 54 distinct concrete URLs including five injected control routes. The PR additionally tests fixed examples with independent expected sets. The namespace collection returned one `Allow: GET, HEAD, POST`, the namespace item included GET, HEAD, PATCH and DELETE, the approval action had POST alone, and each static mount advertised GET and HEAD. A 404 had no Allow. The algorithm applies to the current flat APIRoutes and the explicitly handled StaticFiles mounts; another kind of mounted application would require its own analysis.

Raw HTTP/1.1 measurements used uvicorn **0.32.1**, both its h11 and httptools protocols, and a real connected stream socket pair. Each request used `Connection: close`. I split at the first CRLF/CRLF and counted every octet to EOF, without an HTTP client interpreting HEAD.

| Head response | HTTP status | Media type | Content-Length | Allow fields | Octets after headers, GET / HEAD |
|---|---:|---|---:|---|---:|
| `/absent` | 404 | application/problem+json | 160 | 0 | 160 / **0** |
| `/api/v1/requests/req-x:approve` | 405 | application/problem+json | 218 | 1, POST | 218 / **0** |

Both backends agreed. Base GET lengths were 22 and 31 and base HEAD lengths on the wire were also zero. The nonzero Content-Length on HEAD describes the corresponding GET representation. [RFC 9110 §9.3.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.3.2)

### 3. Unreadable request content

For the PR's three byte inputs (`ff`, Latin-1 inside JSON and excessive nesting), head returned 422 `validation-failed`, with a body error `json_invalid` with and without a token. Base used FastAPI's default 400 for these. The existing `b"{"` path returned 422 on both trees, with `field="body.1"` and `message="JSON decode error"`. Only the status, problem type and error code are common. The PR's nesting input also lacks closing brackets. A separate balanced JSON array at the same depth (200,001 bytes including the scalar) also returned 422 with body/json_invalid, with and without a token. At depths the decoder accepted, the anonymous request progressed to auth and the authenticated array failed object-schema validation instead. The UTF-16/32 counterexamples establish why “not UTF-8” and “failed in the decoder” cannot be used interchangeably.

**RFC 9457 status consistency passes.** The body says 422 and the actual HTTP response is 422. RFC 9457 neither demands that the original FastAPI 400 survive nor makes the choice of 422 semantically correct under RFC 9110.

FastAPI's complete body-read control flow is in `routing.py:244–288`. There is an open-ended `except Exception`, so no finite list of Python exception classes exhausts its possible causes. The operations inside that protected region are enumerable:

| Operation or exception path | Result in the pinned framework | Appropriate disposition |
|---|---|---|
| Form route: await `request.form()` and register `body.close` for later cleanup | A multipart form parser or its stream can fail. Starlette translates its own MultiPartException to an HTTPException(400) with a specific detail. That one is re-raised unchanged by FastAPI. Other exceptions in form parsing/registration can go through the generic 400. Executing the close callback later is outside this try. | Malformed form is a client 400, independent of JSON. A missing parser or internal I/O/cleanup-registration bug is a server fault. No installed cmapi route takes Form/File and the optional multipart module is absent. The form classifications are source-derived; the independent 400 test is synthetic. |
| Read the raw bytes from the ASGI receive stream | `ClientDisconnect` is wrapped as a 400 with the generic parsing text. An already-consumed stream, a receive error or another reader exception can have the same wrapper. Cancellation that is a BaseException bypasses this catch. | Propagate disconnect to cmapi's existing disconnect handling. There is no peer to tell to repair JSON. A reader implementation fault is a 500. A completed but truncated JSON document is a different case and follows the JSON parser. |
| Inspect Content-Type, construct an email Message and select the representation | Missing header or `application/json` or `application/*+json` invokes JSON decoding. Other types leave the bytes alone. Empty bytes skip decoding. Unexpected exceptions in header access, content-type processing or result handling also fall under the generic catch. | A genuinely rejected media type can merit 415, but the pinned code does not raise 415 here. A framework fault does not establish invalid JSON. |
| Parse JSON bytes | JSONDecodeError becomes RequestValidationError with position and `json_invalid`. UnicodeDecodeError, RecursionError or another decoder exception such as ValueError from the integer digit limit can take the generic 400 instead. | Malformed syntax/encoding conventionally merits 400 under RFC 9110. A well-formed value exceeding a decoder limit can reasonably be refused as unprocessable. Keeping the established cmapi 422 family for JSON decoding is a compatibility choice. The proposed patch retains that choice, limits it to JSON, and keeps schema failures as 422. |
| An existing HTTPException, or any remaining Exception | The former retains its status and headers into exception dispatch. The latter is chained as the cause of the generic 400. Dependency solving and endpoint execution occur *after* this try. | Classify by operation and cause. Matching the shared English error message would still conflate a disconnect, a decoder error and a service fault. |

### 4. Which other statuses turn into 500?

| Source on the installed versions | Observed behavior or reachability | Judgment |
|---|---|---|
| Router 404/405 and StaticFiles 404/405 | Dedicated status handlers. Tests include path length, missing mounts, both mounted apps and wrong methods. | Retain statuses, registry types and applicable headers. |
| StaticFiles lookup PermissionError → HTTPException(401) | The real mode-000 directory test ran here, including GET, HEAD and logged original 401. Head returned 500 with no WWW-Authenticate. | Correct for an image/filesystem permission failure. A genuine authentication 401 still requires its challenge. A failed *open* after stat is accounted for separately above. |
| FileResponse malformed/unsatisfiable ranges | Measured direct 400 and 416, never class-dispatched. A successful range was 206 with `Content-Range: bytes 1-2/17`. | Preserve client statuses. Distinct registered range problems let clients fix the header or choose a range inside the asset length. |
| Conditional file response | Measured 304 with zero payload on matching If-None-Match. cmapi's static preconditions can also raise its own Problem(412). | 304 is a direct successful revalidation. It cannot enter the catch-all. |
| 413 / 415 and security refusals | No raising site for 413/415 in the pinned routing, requests or mounted static paths. OAuth uses `auto_error=False`; cmapi makes its own auth Problems. With an authorized test caller, text/plain or urlencoded data on the JSON endpoint reached model validation and yielded 422, and anonymous calls yielded 401. | No measured real 413/415→500 regression. A future body-size limit, media rejection or permission checker deserves its original client status. A status constant alone is no evidence it is emitted. An upstream proxy's responses would be outside the app. |
| Synthetic HTTPException(403/413/415/416) | 403 in the new suite; the other three in review probes. Base retained the injected status. Head returned 500 `internal-error` and discarded an injected header. | Demonstrates the broad fallback, *not* a deployed route. The new synthetic 403 expectation codifies a version assumption. Revisit that assumption before enabling a dependency that can genuinely refuse with one of these codes. |
| Errors returned directly by middleware | A denied CORS preflight still sends plain-text 400. | Intended unchanged behavior in this review. The headline “all framework answers are problems” is too broad. |

### 5. Answers preserved and changed

`grep -RnE --include='*.py' 'HTTPException' head/cmapi/src` located the import, handler signatures/decorator and commentary in `main.py`. Inspection found no production raise of Starlette's or FastAPI's HTTPException and no alias import used to raise it. The PR's narrower textual raise check passed. That check by itself would miss a future alias or an indirect raise.

A real 304 can bypass exception dispatch, so I separately installed routes raising 304 and 307 with a sentinel header. On both versions the 304 was empty with the header intact; the 307 retained it and the JSON default detail, with redirects disabled at the client.

| Request | Base → head |
|---|---|
| Listed-origin POST preflight | 200 → 200, plain-text `OK` |
| Listed-origin preflight for disallowed TRACE | 400 → 400, plain-text `Disallowed CORS method` |
| Ordinary OPTIONS on the namespace collection | 405 → 405, same single Allow. Body changed from the default JSON detail to `method-not-allowed`. |
| Ordinary OPTIONS on an absent path | 404 → 404. Body changed to `not-found`. |
| GET `/docs`, `/redoc`, bundled Swagger JS and ReDoc JS | Four 200s on each tree, each corresponding body byte-identical. |
| Missing file / bad method under a mount | Status preserved, representation changed as specified. Conditional and range behavior on successful assets compared above. |

### 6. Contract and registry

The two served `/openapi.json` files were byte-identical on the same test configuration. Both were 428,180 bytes, SHA-256 `e4983fa695af542e9a4f67e66817d04949d285484ab2c55ae496945b0bc148a4`. Both `oasdiff changelog` and `oasdiff breaking` printed **No changes detected**. Neither new code was a named example on any documented operation. Both were linked from `GET /problems`, and their pages returned 200 without a token.

This is the right split. There is no matched OpenAPI operation to declare a response for an unknown path or unsupported method. Adding the router's generic 404 to a real object's GET would falsely describe that operation. `test_problem_type_docs.py` checks index membership, exact ACTIONS/PROBLEMS key equality, status, type, example and recovery action. `test_api_standard.py` checks the examples *declared for an operation*, their registration and status, and route-specific expectations. It does not require every registry code on an operation. The all-types page test and parametrized operation-standard checks passed, **31 cases**. The actual wire contract for formerly unhandled requests did change even though OpenAPI did not.

### 7. Mutation evidence and assertion strength

| Source under test, same two new files | Passed | Failed | Deciding observation |
|---|---:|---:|---|
| Base | 3 | 22 | Domain 404 preservation, existing malformed JSON and the source grep already passed. The other 22 distinguished the change. |
| Head | 25 | 0 | The directory permission premise held, so no skipped test. |
| Remove only `@app.exception_handler(HTTPException)` | 20 | 5 | Three undecodable-body cases, static permission case, synthetic fallback. Integer handlers survive. |
| Return Problem(400, ...) from the generic 400 branch | 22 | 3 | All three decoder cases failed. The existing `b"{"` path still passed. |
| Omit headers in the 405 problem response | 15 | 10 | Router, static and HEAD/Allow checks failed. |
| Replace every outgoing ASGI HEAD body with `b"WRONG"` | 25 | 0 | TestClient's transport discards HEAD bytes before exposing its response. |
| Insert `b"WRONG"` on the actual transport after a HEAD header block | 0 | 4 | Both paths and both uvicorn protocols failed Appendix C's empty-body assertion. All four passed on the unmodified wire. |

The remaining assertions have different evidentiary value:

- The router helper checks HTTP status, media type, the exact JSON key set, type URI, title, registry status/detail, Allow membership and single-field count, and then dereferences the URI. Each checks a different observable. Wrong media on base stops the case *before* its JSON assertions. The measured failure count cannot demonstrate that every later conjunct fired. A duplicate header line can fail the field-count check; repeated method tokens **in the same field** are collapsed by the test's set, though head constructs the field from a set itself.
- The framework helper checks both HTTP and JSON statuses, code and registry entry, a type **suffix**, and nonempty title/detail. A wrong type host can pass that helper. The router helper separately checks the complete URI. A coordinated registry/example text change can pass comparisons that use the same registry as their oracle. Exact validation error lists and exact detail in the decoder cases do provide an independent oracle.
- The malformed-`{` case and the two domain 404 assertions protect existing behavior. Passing on base is expected. The two auth variants exercise error ordering before dependencies. Registry checks alone cannot establish that order.
- The static permission check asserts the status, media type, lack of challenge, registry detail, and ordered error log levels/methods/original statuses. It can skip under an identity that can traverse a mode-000 directory. A deterministic unit alternative is to inject PermissionError at `StaticFiles.lookup_path`; the separate open-failure test intentionally injects it **later**.
- The injected 403 and log-route assertions catch removal of the class handler. A 304-only status/empty-body assertion would pass even if a handler lost its headers. The 307 and 304 sentinel controls above check that separately. A syntactic grep for a literal constructor does not prove exception provenance in general.
- HEAD status, GET-equivalent representation headers and its Allow can all fail in TestClient. Its empty-body check cannot distinguish an application sending content. The ASGI contract permits a server to suppress HEAD data; demanding empty ASGI body events would incorrectly reject this working application. Appendix C places the assertion where the invariant applies. [Installed TestClient](/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/lib/python3.12/site-packages/starlette/testclient.py:362)

## Execution scope and reproduction

The direct run from `head/cmapi` used the specified interpreter, test files and database URL, with `CMAPI_MIGRATE_WAIT_SECONDS=0` to avoid the 540-second retry. **1 passed, 24 setup errors**. libpq reported `Operation not permitted` connecting to `127.0.0.1:55432`. This establishes a sandbox restriction, not whether the named database is healthy. A TCP bind also failed with EPERM. The installed sources were read outside the export only at the requested venv. The export had no initialized TokenSave index, so I inspected the sources directly.

For the comparisons I copied each tree's source, conftest and service tests under the review folder and copied the two PR tests into each copy. This matters because conftest inserts its **own** source directory at sys.path[0]. Changing PYTHONPATH alone would silently test the wrong tree. In each disposable conftest I replaced only the `fresh_db(database)` fixture with `def fresh_db(): return None` under its existing pytest decorator. This omits migration/truncation. The real app factory, app lifespan, router, exception middleware, fake Git/Kubernetes adapters, keys, test HTTP assertions and installed framework were retained. No other database was used. These results establish HTTP behavior, not a successful PostgreSQL-backed run.

The two-file command inside each copy was:

```sh
CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_wt616 \
PYTHONPATH=src:tests/service PYTHONDONTWRITEBYTECODE=1 \
/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest \
  tests/service/test_router_problems_644.py tests/service/test_framework_problems_646.py \
  -q -W ignore -p no:cacheprovider
```

The uvicorn experiment used an AF_UNIX stream socket pair handed to the real protocol through `asyncio.connect_accepted_socket`. It measured HTTP framing and payload bytes at the receiving socket, independent of TestClient, without a TCP listener, proxy or cluster. Appendices B and C are drop-in service tests. The wire helper includes the deliberate transport corruption switch so the negative control is reproducible. All tests in this report were targeted.

## Appendix A · complete proposed source and documentation patch

Apply to the **PR head**. The JSON route and 400 handler changes belong together. The file-response adapter is an independently applicable follow-up for the pinned Starlette behavior. The browser and documentation changes are small independent edits. The patch deliberately preserves cmapi's published 422 behavior for decoder errors. Rejecting previously accepted UTF-16/32 tightens input compatibility to match the PR's stated contract. The adapter uses the pinned FileResponse range hooks, which should be rechecked when upgrading Starlette.

`````diff
--- a/cmapi/src/cmapi/core/docs.py
+++ b/cmapi/src/cmapi/core/docs.py
@@ -41,4 +41,7 @@
     "cluster-not-found": (404, "Unknown cluster OCP_X"),
     "object-not-found": (404, "No request req-20261105-0001"),
+    "bad-request": (400, "The request could not be parsed"),
+    "invalid-range": (400, "The Range header could not be parsed"),
+    "range-not-satisfiable": (416, "The range cannot be served for this file"),
     "not-found": (404, "No resource of this API has this path"),
     "method-not-allowed": (405, "The path does not take this method. Allow lists the methods it takes"),
@@ -261,4 +264,31 @@
 
 
+class UnreadableJSON(ValueError):
+    """JSON decoding failed on encoding or a decoder limit."""
+
+
+class APIRequest(Request):
+    async def json(self) -> Any:
+        if not hasattr(self, "_json"):
+            raw = await self.body()
+            try:
+                self._json = json.loads(raw.decode("utf-8-sig"))
+            except json.JSONDecodeError:
+                raise
+            except (ValueError, RecursionError) as exc:
+                raise UnreadableJSON() from exc
+        return self._json
+
+
+class JSONRoute(APIRoute):
+    def get_route_handler(self):
+        handle = super().get_route_handler()
+
+        async def route(request: Request) -> Response:
+            return await handle(APIRequest(request.scope, request.receive, request._send))
+
+        return route
+
+
 class DocumentedRouter(APIRouter):
     """An APIRouter whose routes must say what they need and what they can refuse."""
@@ -270,4 +300,5 @@
         if not description.strip():
             raise RuntimeError(f"plugin {plugin}: no description")
+        kw.setdefault("route_class", JSONRoute)
         super().__init__(prefix=prefix, tags=tags or [plugin], **kw)
         self.plugin = plugin
--- a/cmapi/src/cmapi/main.py
+++ b/cmapi/src/cmapi/main.py
@@ -7,4 +7,7 @@
 import json
 import os
+from secrets import token_hex
+
+import anyio
 from contextlib import asynccontextmanager
 from pathlib import Path
@@ -21,4 +24,7 @@
 from starlette.datastructures import Headers
 from starlette.exceptions import HTTPException
+from starlette.responses import FileResponse, MalformedRangeHeader, RangeNotSatisfiable
+from starlette.staticfiles import NotModifiedResponse
+from fastapi.params import Form
 from starlette.requests import ClientDisconnect
 from starlette.routing import Match
@@ -31,5 +37,5 @@
 from cmapi.core.changelog import changelog_html
 from cmapi.core.cors import EXPOSED_HEADERS, MAX_AGE, METHODS, REQUEST_HEADERS, OriginVaryCORSMiddleware, allowed_origins
-from cmapi.core.docs import PROBLEMS, URL_VARIABLE, InstanceFacts, build_openapi, check_documented, plugin_routers
+from cmapi.core.docs import PROBLEMS, URL_VARIABLE, InstanceFacts, UnreadableJSON, build_openapi, check_documented, plugin_routers
 from cmapi.core.errors import Problem, type_base
 from cmapi.core.etag import etag_of, not_modified
@@ -44,4 +50,71 @@
 
 
+class UnsatisfiedRange(Problem):
+    def __init__(self, size: int):
+        super().__init__(416, "range-not-satisfiable", PROBLEMS["range-not-satisfiable"][1])
+        self.size = size
+
+
+class AssetFileResponse(FileResponse):
+    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
+        value = Headers(scope=scope).get("range")
+        if value is not None:
+            unit, separator, _ = value.partition("=")
+            unsupported = separator and unit.strip().lower() != "bytes"
+            if scope["method"] != "GET" or unsupported:
+                scope = dict(scope, headers=[(k, v) for k, v in scope["headers"] if k.lower() != b"range"])
+        pending = None
+
+        async def send_file(message: Message) -> None:
+            nonlocal pending
+            if message["type"] == "http.response.start":
+                pending = message
+                return
+            if pending is not None:
+                await send(pending)
+                pending = None
+            await send(message)
+
+        await super().__call__(scope, receive, send_file)
+
+    async def _handle_multiple_ranges(self, send, ranges, file_size, send_header_only):
+        boundary = token_hex(13)
+        media = self.headers["content-type"]
+        parts = [
+            (start, end, (f"--{boundary}\r\nContent-Type: {media}\r\n"
+                          f"Content-Range: bytes {start}-{end - 1}/{file_size}\r\n\r\n").encode("latin-1"))
+            for start, end in ranges
+        ]
+        close = f"--{boundary}--\r\n".encode("ascii")
+        self.headers["content-type"] = f"multipart/byteranges; boundary={boundary}"
+        self.headers["content-length"] = str(sum(len(h) + end - start + 2 for start, end, h in parts) + len(close))
+        await send({"type": "http.response.start", "status": 206, "headers": self.raw_headers})
+        if send_header_only:
+            await send({"type": "http.response.body", "body": b""})
+            return
+        async with await anyio.open_file(self.path, "rb") as file:
+            for start, end, header in parts:
+                await file.seek(start)
+                await send({"type": "http.response.body", "body": header, "more_body": True})
+                remaining = end - start
+                while remaining:
+                    chunk = await file.read(min(self.chunk_size, remaining))
+                    if not chunk:
+                        raise OSError("File changed during range transfer")
+                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
+                    remaining -= len(chunk)
+                await send({"type": "http.response.body", "body": b"\r\n", "more_body": True})
+        await send({"type": "http.response.body", "body": close})
+
+    @staticmethod
+    def _parse_range_header(http_range: str, file_size: int) -> list[tuple[int, int]]:
+        try:
+            return FileResponse._parse_range_header(http_range, file_size)
+        except MalformedRangeHeader as exc:
+            raise Problem(400, "invalid-range", PROBLEMS["invalid-range"][1]) from exc
+        except RangeNotSatisfiable as exc:
+            raise UnsatisfiedRange(file_size) from exc
+
+
 class ConditionalStaticFiles(StaticFiles):
     """The Swagger UI and ReDoc files, with the preconditions of every other read of cmapi (core/etag.py, not_modified):
@@ -53,4 +126,10 @@
     StaticFiles calls is_not_modified for an existing file only, from file_response, so a missing one stays 404 whatever
     the preconditions (section 13.2.1). The 412 that not_modified raises is the RFC 9457 problem of create_app's handler."""
+
+    def file_response(self, full_path, stat_result, scope, status_code=200):
+        response = AssetFileResponse(full_path, stat_result=stat_result, status_code=status_code)
+        if self.is_not_modified(response.headers, Headers(scope=scope)):
+            return NotModifiedResponse(response.headers)
+        return response
 
     def is_not_modified(self, response_headers: Headers, request_headers: Headers) -> bool:
@@ -213,4 +292,6 @@
     @app.exception_handler(Problem)
     async def problem_handler(_: Request, exc: Problem) -> Response:
+        if isinstance(exc, UnsatisfiedRange):
+            return problem_response(exc, {"Content-Range": f"bytes */{exc.size}"})
         return problem_response(exc, dict(unauthenticated_headers(exc)))
 
@@ -262,18 +343,19 @@
     @app.exception_handler(HTTPException)
     async def framework_refusal(request: Request, exc: HTTPException) -> Response:
-        """Every other HTTPException, which only FastAPI and Starlette raise: cmapi's own refusals are Problems (#646).
-
-        A 400 is a body that could not be read (fastapi/routing.py:285, and starlette/requests.py:271 for a form, which no
-        route of cmapi takes): not UTF-8 (RFC 8259, section 8.1), nested deeper than the decoder goes, or cut short. It is
-        the 422 validation-failed with json_invalid that FastAPI gives a body JSON cannot decode, so a client gets one
-        answer for a body that is not JSON (core/docs.py, DocumentedRouter._register). Any other status is the service's
-        fault: StaticFiles' 401 (staticfiles.py:119) is a file of the image that the process cannot read, which no
-        credential changes, and no other site is reachable. It is internal-error, with the cause in the log line. An
-        HTTPException below 400 is no refusal and keeps FastAPI's answer."""
+        """Keep JSON decoder failures distinct from transport, form and service errors."""
         if exc.status_code < 400:
             return await http_exception_handler(request, exc)
         if exc.status_code == 400:
-            return problem_response(validation_failed([{"field": "body", "message": "the body cannot be read as JSON",
-                                                        "code": "json_invalid"}]))
+            cause = exc.__cause__
+            if isinstance(cause, ClientDisconnect):
+                raise cause
+            if isinstance(cause, UnreadableJSON):
+                return problem_response(validation_failed([{"field": "body", "message": "the body cannot be read as JSON",
+                                                            "code": "json_invalid"}]))
+            field = getattr(request.scope.get("route"), "body_field", None)
+            form = isinstance(getattr(field, "field_info", None), Form)
+            if cause is None or (form and isinstance(cause, ValueError)):
+                return problem_response(Problem(400, "bad-request", PROBLEMS["bad-request"][1]), dict(exc.headers or {}))
+            raise RuntimeError("Failed to read the request body") from cause
         log.error("framework_refusal", method=request.method, status=exc.status_code, detail=str(exc.detail)[:200],
                   route=getattr(request.scope.get("route"), "path_format", "unmatched"))
--- a/cmapi/src/cmapi/core/problem_docs.py
+++ b/cmapi/src/cmapi/core/problem_docs.py
@@ -20,6 +20,9 @@
     "cluster-not-found": "Use a cluster ID from `GET /api/v1/clusters`.",
     "object-not-found": "Check the identifier. The object does not exist, or this instance does not serve it.",
-    "not-found": "Check the path against the API reference (`/docs`, `/openapi.json`), which lists each path of this instance. "
-                 "No route and no file answers this one, so the answer says nothing of an object.",
+    "bad-request": "Check the request framing and the encoding of its content.",
+    "invalid-range": "Send a valid byte range or remove the Range header.",
+    "range-not-satisfiable": "Use the size in Content-Range to select a range within the file.",
+    "not-found": "Check the path. For documented API operations, see /docs or /openapi.json. "
+                 "For problem types, see /problems.",
     "method-not-allowed": "Send the request with one of the methods that the `Allow` header of the answer lists. "
                           "The API reference lists each operation of the path.",
--- a/cmapi/src/cmapi/core/cors.py
+++ b/cmapi/src/cmapi/core/cors.py
@@ -31,5 +31,5 @@
 # ETag is the value of If-Match on a change; Retry-After and WWW-Authenticate say what to do after a 429, a 503 or a 401;
 # X-Request-Id is the line to look for in the logs.
-EXPOSED_HEADERS = ["ETag", "Location", "Retry-After", "WWW-Authenticate", "X-Request-Id"]
+EXPOSED_HEADERS = ["Allow", "ETag", "Location", "Retry-After", "WWW-Authenticate", "X-Request-Id"]
 MAX_AGE = 600           # seconds a browser keeps a preflight answer; WebKit's ceiling is 600, Chromium's is 7200
 
--- a/docs/02-technical-design-v2.md
+++ b/docs/02-technical-design-v2.md
@@ -134,15 +134,13 @@
 | Patch format | application/merge-patch+json; null removes a key |
 
-**Errors.** RFC 9457 problem details (application/problem+json), always with clusterId and requestId:
+**Errors.** cmapi problem responses use `application/problem+json`. The HTTP request correlation ID is in `X-Request-Id`. A router refusal can occur before the application knows any cluster or change request. For example, an unknown path on an instance using the default type base returns:
 
 ```json
 {
-  "type": "https://cmapi.ephico2real.com/problems/policy-violation",
-  "title": "Grant not allowed",
-  "status": 422,
-  "detail": "ClusterRole cluster-admin is not on the ServiceAccount allowlist",
-  "clusterId": "OCP_GF1",
-  "requestId": "req-20261103-7f3a",
-  "errors": [{"field": "roleRef.name", "code": "not_allowlisted"}]
+  "type": "https://cmapi.ephico2real.com/problems/not-found",
+  "title": "not found",
+  "status": 404,
+  "detail": "No resource of this API has this path",
+  "code": "not-found"
 }
 ```
@@ -150,4 +148,7 @@
 | Problem type | Status | When |
 | --- | --- | --- |
+| bad-request | 400 | The framework rejected a malformed request, for example invalid form data. |
+| invalid-range | 400 | A static asset request has a malformed byte range. |
+| range-not-satisfiable | 416 | No requested byte range can be served. Read the file size in `Content-Range`. |
 | validation-failed | 422 | Schema, name or label rules fail. A body that is not JSON is this problem with `json_invalid`, also one that is not UTF-8 or is nested deeper than the decoder goes, with or without a token (#646) |
 | policy-violation | 422 | Allowlist, subject rule, reserved prefix, limits below requests |
@@ -164,5 +165,5 @@
 | cluster-not-found | 404 | clusterId not in the registry |
 | object-not-found | 404 | Live object missing |
-| not-found | 404 | No route and no file of the instance has the path, under `/static` too: the router's own 404, before any route runs (#644) |
+| not-found | 404 | No route and no file of the instance has the path, including a lookup miss in either static mount (#644) |
 | method-not-allowed | 405 | The path does not take the method. `Allow` lists every method of the path, also on a HEAD, which has no content (#634, #644) |
 | change-pending | 409 | An open request already targets this object |
@@ -170,5 +171,5 @@
 | cluster-unreachable | 503 | Cluster API down; Retry-After set |
 | git-unavailable | 502 | Git host error; the request row is marked failed |
-| internal-error | 500 | An exception that no handler takes. The answer has no text of the exception; the log line `unhandled` has it, with the X-Request-Id of the answer. The answer has the CORS headers, so the portal shows the problem and not a network error. A refusal of FastAPI or Starlette that is the service's fault is this problem too, with the log line `framework_refusal`: a file under `/static` that the process cannot read (Starlette's 401), or any status other than 400, 404 and 405 (#646) |
+| internal-error | 500 | An exception that no handler takes. The answer has no text of the exception; the log line `unhandled` has it, with the X-Request-Id of the answer. The answer has the CORS headers, so the portal shows the problem and not a network error. A refusal of FastAPI or Starlette that is the service's fault is this problem too, with the log line `framework_refusal`: permission denied during static path lookup (Starlette's 401), or an unexpected framework HTTP exception with status 400 or above outside the dedicated handlers (#646) |
 
 **Problem type URIs.** The type of a problem is a base and the code of the problem. The base is problems.typeBase in instance.yaml, and its default is https://cmapi.ephico2real.com/problems/. An organisation uses one base for all its instances, because the type is the identifier that a client compares (RFC 9457, section 3.1.1). Each instance serves GET /problems and GET /problems/{code} as HTML, with no token: the type, the title, the status, an example and what the caller does. So the type resolves when the host of the base points at an instance. On CRC the base is the Route of the API.
`````

## Appendix B · regressions for production and documentation findings

Save as `cmapi/tests/service/test_framework_review.py`. All 16 parametrized cases failed on head and passed against the proposed changes. The initial failed-open test substitutes an actual file-open error after successful lookup. The separate original PR test exercises directory traversal permissions. The direct-400 endpoint is a classification control, independent of optional multipart support.

```python
import asyncio
import pytest
from test_api_docs import bundles
from test_framework_problems_646 import JSON, WRITE
from starlette.requests import Request
from starlette.exceptions import HTTPException

@pytest.mark.parametrize("encoding", ["utf-16", "utf-32", "utf-16-le", "utf-32-be"])
def test_json_encoding(world, encoding):
    client, *_ = world
    r = client.post(WRITE, content='{"name":"café"}'.encode(encoding), headers=JSON)
    assert r.status_code == r.json()["status"] == 422
    assert r.json()["errors"][0]["code"] == "json_invalid"

def test_disconnected_body(world):
    client, *_ = world
    sent = []
    async def receive():
        return {"type": "http.disconnect"}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "method": "POST", "path": WRITE, "headers": [(b"content-type", b"application/json")],
             "http_version": "1.1", "scheme": "http", "query_string": b""}
    asyncio.run(client.app(scope, receive, send))
    assert sent == []

def test_failed_reader(world, monkeypatch):
    client, *_ = world
    async def broken(self):
        raise OSError("reader failure")
    monkeypatch.setattr(Request, "body", broken)
    r = client.post(WRITE, content=b"{}", headers=JSON)
    assert r.status_code == r.json()["status"] == 500
    assert r.json()["code"] == "internal-error"

def test_non_json_400(world):
    client, *_ = world
    @client.app.get("/bad-request")
    def endpoint():
        raise HTTPException(400, detail="Malformed form")
    r = client.get("/bad-request")
    assert r.status_code == r.json()["status"] == 400
    assert r.json()["code"] == "bad-request"

@pytest.mark.parametrize("header,status,code", [("oops", 400, "invalid-range"), ("bytes=99-", 416, "range-not-satisfiable")])
def test_range_problem(bundles, world, header, status, code):
    client, *_ = world
    url = "/static/swagger/swagger-ui-bundle.js"
    r = client.get(url, headers={"Range": header})
    assert r.status_code == status
    if status == 416:
        assert r.headers["content-range"] == f"bytes */{len(client.get(url).content)}"
    assert r.headers["content-type"] == "application/problem+json"
    assert (r.json()["status"], r.json()["code"]) == (status, code)
    assert client.get("/problems/" + code).status_code == 200
    assert client.get(url, headers={"Range": "bytes=1-2"}).status_code == 206
    assert client.get(url, headers={"If-None-Match": client.get(url).headers["etag"]}).status_code == 304

@pytest.mark.parametrize("method,header", [("HEAD", "bytes=99-"), ("GET", "widgets=1-2")])
def test_inapplicable_range(bundles, world, method, header):
    client, *_ = world
    url = "/static/redoc/redoc.standalone.js"
    ordinary = client.request(method, url)
    ranged = client.request(method, url, headers={"Range": header})
    assert ranged.status_code == ordinary.status_code == 200
    assert ranged.content == ordinary.content
    assert ranged.headers["content-length"] == ordinary.headers["content-length"]

def test_cross_origin_allow(test_config, tmp_path, keys, monkeypatch, fresh_db):
    from conftest import build_world
    from test_cors import PORTAL, with_instance
    cfg = with_instance(test_config, tmp_path, lambda i: i.update(cors={"allowedOrigins": [PORTAL]}))
    with build_world(cfg, keys, monkeypatch) as (client, *_):
        r = client.post("/api/v1/version", headers={"Origin": PORTAL})
        assert r.status_code == 405 and r.headers["access-control-allow-origin"] == PORTAL
        assert "allow" in {h.strip().lower() for h in r.headers["access-control-expose-headers"].split(",")}

def test_missing_path_help_includes_registry(world):
    client, *_ = world
    assert "/problems" not in client.get("/openapi.json").json()["paths"]
    page = client.get("/problems/not-found").text
    import re
    action = re.search(r'<td id="action">(.*?)</td>', page, re.S)[1]
    assert "/problems" in action and "each path of this instance" not in action

def test_open_failure_before_first_byte(bundles, world, monkeypatch):
    import anyio
    from fastapi.testclient import TestClient
    client, *_ = world
    original = anyio.open_file
    async def denied(path, *args, **kwargs):
        if str(path).endswith("/swagger-ui-bundle.js"):
            raise PermissionError("no read permission")
        return await original(path, *args, **kwargs)
    monkeypatch.setattr(anyio, "open_file", denied)
    with_client = TestClient(client.app, raise_server_exceptions=False)
    r = with_client.get("/static/swagger/swagger-ui-bundle.js")
    assert r.status_code == 500
    assert r.json()["code"] == "internal-error"

def test_multipart_range(bundles, world):
    client, *_ = world
    r = client.get("/static/swagger/swagger-ui-bundle.js", headers={"Range": "bytes=0-0,5-6"})
    assert r.status_code == 206 and "content-range" not in r.headers
    assert r.headers["content-type"].startswith("multipart/byteranges; boundary=")
    assert b"Content-Range: bytes 0-0/17" in r.content
    boundary = r.headers["content-type"].split("boundary=")[1].encode()
    parts = r.content.split(b"--" + boundary)
    assert parts[1].endswith(b"\r\n\r\n/\r\n") and parts[2].endswith(b"\r\n\r\nst\r\n")
    assert parts[-1] == b"--\r\n" and len(r.content) == int(r.headers["content-length"])

def test_design_error_example(world):
    import json
    import re
    from pathlib import Path
    client, *_ = world
    design = (Path(__file__).resolve().parents[3] / "docs/02-technical-design-v2.md").read_text()
    errors = design.split("**Errors.**", 1)[1].split("| Problem type |", 1)[0]
    example = json.loads(re.search(r"```json\s*(.*?)\s*```", errors, re.S)[1])
    r = client.get("/does-not-exist")
    assert r.headers["x-request-id"]
    assert r.json() == example
```

## Appendix C · HEAD wire test and sensitivity control

Save the helper as `cmapi/tests/service/wire.py`. The ordinary test uses the installed protocols unchanged. For the failing control, set the helper's `leak` default to `True` in the disposable test copy. This injects bytes after HTTP serialization, so the error is observable on the peer socket for either backend. Restoring `False` makes all four pass. The ASGI mutant in the main table instead changed the body *before* HTTP serialization, leaving response-start headers intact.

```python
import asyncio
import socket
import uvicorn
from uvicorn.server import ServerState

async def wire(app, method, path, protocol="auto", leak=False):
    config = uvicorn.Config(app, http=protocol, lifespan="off", log_config=None, access_log=False)
    config.load()
    loop = asyncio.get_running_loop()
    server, client = socket.socketpair()
    client.setblocking(False)
    transport, handler = await loop.connect_accepted_socket(
        lambda: config.http_protocol_class(config, ServerState(), {}), server)
    # Positive control: corrupt just the outgoing bytes of a HEAD response after serialization.
    if leak and method == "HEAD":
        write = transport.write
        def corrupt(data):
            write(data + (b"WRONG" if b"\r\n\r\n" in data else b""))
        transport.write = corrupt
    try:
        await loop.sock_sendall(client, f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
        data = bytearray()
        while chunk := await asyncio.wait_for(loop.sock_recv(client, 65536), 5):
            data.extend(chunk)
        headers, body = bytes(data).split(b"\r\n\r\n", 1)
        return headers, body
    finally:
        client.close()
        transport.close()
```

Save the test as `cmapi/tests/service/test_router_head_wire.py`.

```python
import asyncio

import pytest
from wire import wire


@pytest.mark.parametrize("protocol", ["h11", "httptools"])
@pytest.mark.parametrize("path,status,allow", [
    ("/absent", 404, []),
    ("/api/v1/requests/req-x:approve", 405, [b"allow: post"]),
])
def test_head_wire(world, protocol, path, status, allow):
    client, *_ = world
    for method in ("GET", "HEAD"):
        headers, body = asyncio.run(wire(client.app, method, path, protocol))
        lines = headers.lower().split(b"\r\n")
        assert int(lines[0].split()[1]) == status
        assert [h for h in lines if h.startswith(b"allow:")] == allow
        assert b"content-type: application/problem+json" in lines
        if method == "GET":
            size = len(body)
            assert size > 0
        else:
            assert body == b""
        assert f"content-length: {size}".encode() in lines
```

## Appendix D · base/head comparison controls

Run this service test against each export, setting `REVIEW_TREE` to `base` or `head` and `REVIEW_SPEC` to a distinct output path inside the review folder. Compare those two files with `cmp` and `oasdiff changelog`. These assertions capture observations of the two **unfixed** versions, including the defective static 416 header. Appendix B contains the forward-looking expectations for the fixed version.

```python
import os
from pathlib import Path

from starlette.exceptions import HTTPException
from test_api_docs import bundles
from test_cors import PORTAL, preflight, world
from test_framework_problems_646 import JSON, WRITE
from test_flow import OLA, auth


def test_contract_controls(bundles, world):
    client, *_, keys = world
    head = os.environ["REVIEW_TREE"] == "head"
    assert preflight(client, PORTAL).status_code == 200
    assert preflight(client, PORTAL, method="TRACE").status_code == 400
    for path, status in [(WRITE, 405), ("/absent", 404)]:
        r = client.options(path)
        assert r.status_code == status
        assert r.headers["content-type"] == ("application/problem+json" if head else "application/json")
        if status == 405:
            assert r.headers.get_list("allow") == ["GET, HEAD, POST"]

    url = "/static/swagger/swagger-ui-bundle.js"
    for path in ["/docs", "/redoc", url, "/static/redoc/redoc.standalone.js"]:
        assert client.get(path).status_code == 200
    base = client.get(url)
    assert client.get(url, headers={"If-None-Match": base.headers["etag"]}).status_code == 304
    ranged = client.get(url, headers={"Range": "bytes=99-"})
    assert (ranged.status_code, ranged.headers["content-range"], ranged.content) == (416, "*/17", b"")
    assert client.get(url, headers={"Range": "oops"}).status_code == 400

    r = client.get("/openapi.json")
    assert r.status_code == 200
    Path(os.environ["REVIEW_SPEC"]).write_bytes(r.content)
    registry = client.get("/problems").text
    for code in ["not-found", "method-not-allowed"]:
        assert (f'href="/problems/{code}"' in registry) == head
        for ops in r.json()["paths"].values():
            for op in ops.values():
                for response in op["responses"].values():
                    media = response.get("content", {}).get("application/problem+json", {})
                    assert code not in media.get("examples", {})

    def route(status):
        def endpoint():
            raise HTTPException(status, headers={"X-Probe": "yes"})
        return endpoint
    for status in (307, 304, 413, 415, 416):
        path = f"/injected/{status}"
        client.app.add_api_route(path, route(status))
        r = client.get(path, follow_redirects=False)
        assert r.status_code == (500 if head and status >= 400 else status)
        if status < 400:
            assert r.headers["x-probe"] == "yes"
            if status == 304:
                assert r.content == b""
            else:
                assert r.json() == {"detail": "Temporary Redirect"}

    nested = b"[" * 100_000 + b"0" + b"]" * 100_000
    for token in ({}, auth(keys, "ola", **OLA)):
        r = client.post(WRITE, headers={**JSON, **token}, content=nested)
        assert r.status_code == (422 if head else 400)
        if head:
            assert r.json()["errors"][0]["code"] == "json_invalid"
```
