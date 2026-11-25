# PR #691 (closes #683), reviewer 1: Opus 5.5 at high, standing in for Codex

Reviewed: head `c3c62ed` against main `8633794`, both from the export in `review-691/`. Every run used the service-suite
world against PostgreSQL 16 on `127.0.0.1:55432`, database `cmapi_r1_691`, on this Mac. No cluster was used. Edits went into
copies under `r1-outputs/work/` only. Running the PR's tests in `head/cmapi` also left `__pycache__` files in the export.

## Verdict

The control does what the README says. All 24 of the PR's tests pass on head and 22 fail on base. All five mutants are caught.
The middleware order is right, and the contract and the Route claim hold.

I found one regression, which the PR introduced (F1, Medium): content that arrives while a streamed answer is being sent ends
that answer early and is logged as `unhandled`. There is one Low inside the changed lines: the chart's schema and the Python
check disagree on very large values (F2). There is also one inaccurate comment (F3).

`r1-outputs/fix.diff` fixes all three, with tests. It applies to a copy of `head/` with `patch -p1 -F0`, and the result is
byte-identical to my fix copy. Results with the fix:
- `test_body_limit_683.py` on head plus the fix: 28 passed.
- The same file, plus `test_value_error_648.py`, `test_head_605.py`, `test_list_filters.py` and `test_api_standard.py`: 243 passed (`r1-outputs/fix-related.txt`).

## Sources, fetched 2026-11-25 (copies in `r1-outputs/sources/`)

- **RFC 9110 §15.5.14** (https://www.rfc-editor.org/rfc/rfc9110.txt): "The 413 (Content Too Large) status code indicates that the
  server is refusing to process a request because the request content is larger than the server is willing or able to process.
  The server MAY terminate the request, if the protocol version in use allows it; otherwise, the server MAY close the connection."
- **RFC 9110 §8.6**: Content-Length is "a decimal non-negative integer number of octets"; "a recipient MUST anticipate potentially
  large decimal numerals and prevent parsing errors due to integer conversion overflows or precision loss due to integer
  conversion (Section 17.5)".
- **RFC 9110 §10.1.1**: "A server that responds with a final status code before reading the entire request content SHOULD indicate
  whether it intends to close the connection (e.g., see Section 9.6 of [HTTP/1.1]) or continue reading the request content."
  - In HTTP/1.1 a connection persists by default. The 413 carries no `Connection: close`, so it says the server keeps reading.
  - P3 measured that uvicorn does keep reading (below).
- **RFC 9112** (https://www.rfc-editor.org/rfc/rfc9112.txt):
  - §6.1: "A server MAY reject a request that contains both Content-Length and Transfer-Encoding ... the server MUST close the
    connection after responding to such a request".
  - §6.3, item 3: "the Transfer-Encoding overrides the Content-Length. Such a message might indicate an attempt to perform request
    smuggling".
  - §6.3, item 5: a Content-Length with differing values or an invalid value: "the server MUST respond with a 400 (Bad Request)".
  - §6.3, item 6: "its decimal value defines the expected message body length in octets."
  - §9.6: "there is a significant risk that the client will not be able to read the last HTTP response."
- **ASGI HTTP spec** (https://raw.githubusercontent.com/django/asgiref/main/specs/www.rst):
  - `more_body`: "If True, the consuming application should wait until it gets a chunk with this set to False."
  - `http.disconnect`: "Sent to the application if receive is called after a response has been sent or after the HTTP connection
    has been closed."
  - `spec_version`: "Optional; if missing assume "2.0"". Spec 2.4 adds the `OSError` from `send()`.
- **Starlette 1.10.0**, installed source:
  - `applications.py` takes `max_body_size: int | None = None`, "The default, `None`, does not limit request body size".
  - `middleware/body_limit.py` answers `PlainTextResponse("Content Too Large", status_code=413)`.
  - It checks Content-Length only in `receive_with_limit` and `send_with_limit`, so the application has already run.
  - FastAPI 0.162.2's `applications.py` never mentions `max_body_size` (grep), and its `build_middleware_stack` (lines 1033-1080)
    builds `ServerErrorMiddleware` + `user_middleware` + `ExceptionMiddleware` itself.
  - The README's reasons for rejecting Starlette's limit hold.
  - Starlette's own middleware has the same re-raise-once-started branch as F1.
- **Starlette 1.10.0, `responses.py:247-285`**, the premise of F1. `StreamingResponse.__call__` with `spec_version < (2, 4)` runs
  `listen_for_disconnect`, which loops on `receive()`, alongside `stream_response` in one task group.
- **uvicorn 0.32.1**, installed source:
  - `h11_impl.py:203` and `httptools_impl.py:225` both send `"spec_version": "2.3"`.
  - `cmapi/main.py:615` runs `uvicorn.run(...)` with the default `http="auto"`, and `uvicorn[standard]` installs httptools, so
    production parses with httptools.
  - A body that arrives after the response is complete is dropped: `h11_impl.py:254-256` (`if self.conn.our_state is h11.DONE:
    continue`) and `httptools_impl.py:298-300`.
  - It sends `100 Continue` only from `receive()` (`h11_impl.py:521-527`, `httptools_impl.py:556-559`).
- **OpenShift**: `openshift/openshift-docs` branch `enterprise-4.20`, `modules/nw-route-specific-annotations.adoc`.
  - The annotations it lists are `balance`, `disable_cookies`, `hsts_header`, `ip_allowlist`, `pod-concurrent-connections`, the
    four `rate-limit-connections` keys, `rewrite-target`, `set-forwarded-headers`, `cookie_name`, `cookie-same-site` and
    `haproxy.health.check.interval`. None of them sets a body size.
  - `openshift/router` master, `haproxy-config.template:81`: `tune.bufsize {{ env "ROUTER_BUF_SIZE" "32768" }}` is its only size.
  - The README's claim holds.
- **nginx front door**: `cmapi-portal-ui/nginx/templates/cmapi.conf.template:94` is `client_max_body_size 1m;` (read).
- **RFC 7493 §2.2** (https://www.rfc-editor.org/rfc/rfc7493.txt), for F2: "An I-JSON sender cannot expect a receiver to treat an
  integer whose absolute value is greater than 9007199254740991 (i.e., that is outside the range [-(2**53)+1, (2**53)-1]) as an
  exact value."

## The points of the brief

### 1. Order: confirmed

- Starlette's `add_middleware` does `user_middleware.insert(0, ...)` (`starlette/applications.py:107`), so the last one added is the outermost.
- The stack, from the outside in:
  1. `ServerErrorMiddleware`
  2. `OriginVaryCORSMiddleware`, when origins are set
  3. `MetricsAndRequestIdMiddleware` (`instrument`)
  4. `RefuseNulMiddleware`
  5. `UnhandledToProblemMiddleware`
  6. `RequestBodyLimitMiddleware`
  7. `ExceptionMiddleware`
  8. the router
- No middleware or route calls `request.body()`, `.json()`, `.stream()` or `.form()`, and none reads `receive` other than to pass
  it through (grep of `src/cmapi`). `UnhandledToProblemMiddleware.receive_checked` only notes `http.disconnect`.
- FastAPI reads the body (`fastapi/routing.py:458-471`, `request.body()` and `request.json()`) before `solve_dependencies`
  (`:511`), where the sign-in runs. So:
  - A declared length over the limit is refused before the sign-in.
  - Chunked content is read up to the limit before the sign-in. That is FastAPI's order, which predates this PR, and the limit now bounds it.
  - P6: GET, HEAD, OPTIONS and DELETE with `Content-Length: LIMIT+1` all get 413 with 0 reads.
- One reader outside the wrapper's assumptions does exist: Starlette's `StreamingResponse` disconnect listener. That is F1.

### 2. Streaming

- After a 413 mid-stream the application stops reading. The `ContentTooLarge` ends FastAPI's body loop.
- One `http.response.start` is sent:
  - The 413 handler runs only when the response has not started (`starlette/_exception_handler.py:55-56`).
  - The middleware's own fallback uses the raw `send` only when `started` is false.
- Connection (P3, both parsers):
  - `Content-Length` 4×LIMIT with the full content sent gets a 413 with no `Connection` header, then a GET on the same socket gets 200.
  - uvicorn drops the rest of the content (sources above).
- **When the answer has already started, it is a defect: F1.**

### 3. Edge cases (P4, P5, P6 in `r1-outputs/probes-head.txt`)

| Case | h11 | httptools (production) |
|---|---|---|
| `Content-Length` `-1`, `abc`, `+99999` | 400, close | 400, close |
| Two different `Content-Length` | 400, close | 400, close |
| `Content-Length: 99999, 99999` | h11 folds it to one value: 413 `content-too-large` | 400, close |
| CL 10 + `Transfer-Encoding: chunked`, 6144 bytes chunked | 413 `content-too-large` (streaming count), connection kept | 400, close |
| CL LIMIT+1 + TE chunked, 5 bytes | 413 (CL check) | 400, close |

- In the code, `_content_length` returns `None` for a value that is not ASCII digits, and the streaming count still applies. That is safe.
- Exactly at the limit is read, and one byte more is refused. The PR's test covers this, and both off-by-one mutants are caught.
- A limit of 1: 1 byte is read, and 2 bytes are refused both declared (0 reads) and chunked. Empty `http.request` messages count 0 (P5).
- Lifespan and websocket scopes reach the application with the original `receive` (P5).

### 4. Config

- The Python check refuses 0, -1, True, "1m", 1.5 and None, and the chart's schema refuses 0 and "1m". On small values they agree.
- They disagree on very large values. That is F2.
- I did not add an upper bound for safety: a large limit is an operator's choice. The bound in F2 is the largest value that JSON
  carries exactly, not a policy.

### 5. The 20-error cap

- `MAX_VALIDATION_ERRORS = 20` equals `core/models.py:93 MAX_PLACES = 20`.
- The loop keeps pydantic's order and stops at 20, so a surrogate refusal of 20 places plus others is cut to the first 20. The PR's
  test pins `body.x0`…`body.x19` in order, and the no-cap mutant is caught.
- The answer is now bounded by the size of the request, not by 20 × a constant. P7 measured it:
  - Request: 20 unknown members with 52,000-character keys, 1,040,446 bytes, under 1 MiB.
  - Answer: 422 with 20 errors and 1,042,364 bytes, because each `field` echoes its key in full.
  - Before the PR, the amplification was 7× (README). With the PR it is about 1×. Backlog B1.

### 6. Contract and docs

- **The contract:**
  - The 10 operations with `requestBody` in `contract/openapi.json` are exactly the 10 with a 413 (script over the document).
  - oasdiff 1.37.0 `breaking`: "No breaking changes to report".
  - `changelog`: "10 changes: 0 error, 0 warning, 10 info", each `response-non-success-status-added` (`r1-outputs/oasdiff-changelog.txt`).
- **The docs:**
  - docs/02, docs/18 and the README match the code, apart from the F1 sentence in the docstring and the values.yaml comment (F3).
  - The README's Starlette, FastAPI, uvicorn and OpenShift quotes match the sources.

### 7. The tests can fail

- On base (`r1-outputs/base-run.txt`): 22 failed, 2 passed. I used a stand-in `bodylimit.py` with only `DEFAULT_MAX_REQUEST_BODY_BYTES` and `parse_http`.
  The two that pass are the GET guard and the largest-create guard, as the README says.
- On head: 24 passed (`r1-outputs/head-run.txt`).
- Mutants (`r1-outputs/mutants.txt`, script `probes/mutants.sh`). Each was killed:

| Mutant | Failed |
|---|---|
| No Content-Length check | 3: the reads==0 test and the real-server test with both parsers |
| No streaming count | 5 |
| Streaming `>=` | 2 |
| Content-Length `>=` | 1: the exact-limit test |
| No 422 cap | 1 |

- Only one test kills the Content-Length off-by-one mutant. It is enough, but it is the only guard there.

## Findings

### F1 (Medium, in the changed lines): content over the limit that arrives while a streamed answer is sent breaks that answer

**Where.** `cmapi/src/cmapi/core/bodylimit.py`, `receive_counted` (head lines 102-109) and the docstring line 80, "A request that
the application never reads, a GET for one, is not counted."

**What is wrong.**
- uvicorn 0.32.1 sends ASGI `spec_version` "2.3". So Starlette 1.10.0's `StreamingResponse` runs `listen_for_disconnect`, which
  reads `receive()` while it streams.
- `GET /api/v1/quotas:export` (`plugins/quotas/__init__.py:161`) answers that way.
- If a caller with `objects:read` sends that GET with chunked content, and the content passes the limit after the 200 has started:
  1. `receive_counted` raises `ContentTooLarge` inside the stream's task group.
  2. Starlette's handler wrapper turns it into `RuntimeError("Caught handled exception, but response already started.")`.
  3. The middleware's `except ContentTooLarge` does not match a `RuntimeError`.
  4. `UnhandledToProblemMiddleware` logs `unhandled` at error level with a traceback.
  5. uvicorn logs "Exception in ASGI application" and closes the connection on a truncated 200.
- On base the listener drops the content and the export completes.
- The caller can repeat this at will, and every repeat writes a false `unhandled` error.

**Measured** (`r1-outputs/probes-head.txt`):
- P1, ASGI:
  - `status=200 body=b'' complete=False raised=RuntimeError`, with cause `ContentTooLarge(413)`.
  - `unhandled=[('/api/v1/quotas:export', 'RuntimeError')]`.
- P2, over TCP:
  - h11: `rest=b'5\r\nname\n\r\n' complete=False unhandled=['RuntimeError'] server_error=True`.
  - httptools: `complete=False unhandled=['RuntimeError'] server_error=True`.
  - Neither sends the final chunk.
- The regression test fails on head and passes on base (`r1-outputs/fix-tests.txt`), so the defect comes from this PR.

**Fix (in `fix.diff`).**
- Once `http.response.start` has gone, a message that passes the limit is passed on with its `body` emptied instead of raising:
  `if started: return {**message, "body": b""}`.
- Why this is safe:
  - A 413 can no longer be sent.
  - The content cannot change an answer that is already sent.
  - Nothing over the limit reaches the application, so memory stays bounded for any reader after the start.
- Before the start, the behaviour is unchanged: the listener's read raises, and the 413 handler answers with the problem.
  The CL check already answers 413 to any method.
- The docstring now says this.

**Test.** `test_content_over_the_limit_after_a_streamed_answer_started_leaves_the_answer_whole`. It is deterministic: a `receive`
that waits for `http.response.start`, `spec_version` "2.3", and a two-line CSV with a 0.2 s gap. It asserts:
- one start, status 200;
- the body `name\nrow\n` and a closing `more_body: False`;
- no `unhandled` line.

Results: it fails on head (RuntimeError), passes on head plus the fix, and passes on base.

### F2 (Low, in the changed lines): the chart accepts limits that the loader refuses or receives rounded

**Where.** `deploy/helm/cmapi/values.schema.json` (`"minimum": 1` and no maximum) and `core/bodylimit.py parse_http`.

**Measured** with Helm v4.3.1, `helm template ... --set-json instance.http=...`:

| Value given | Schema | Rendered |
|---|---|---|
| `1e21`, by `--set-json` and by a values file | Accepts | `http: {"maxRequestBodyBytes":1e+21}`. PyYAML 6.0.2 loads `1e+21` as the string `'1e+21'` (measured), so cmapi refuses to start on a value that the chart validated |
| `9007199254740993` | Accepts | `9007199254740992`, silently rounded |
| `2097152.0` | Accepts | `2097152`, fine |

**Fix.**
- `MAX_LIMIT = 2**53 - 1` (RFC 7493 §2.2) in `parse_http`, and `"maximum": 9007199254740991` in the schema. The two now agree, and
  every value the schema takes renders as the same integer.
- The message, docs/18 and the `config.py` docstring say "1 to 9007199254740991".

**Test.**
- `test_a_limit_that_is_not_one_stops_the_start` gains `2**53` and `'1e+21'`.
- `test_the_limit_comes_from_instance_yaml` gains `2**53 - 1`.
- The chart test renders `9007199254740991` and checks the loader takes it, and the schema refuses `1e21` and `9007199254740993`.

On head, the `2**53` case and the chart test fail on what they check. The other parametrized cases fail on head only because the
message wording changed. All pass with the fix.

### F3 (Low, in the changed lines, comment only): the values.yaml comment says every refused body is refused "before it is read"

That is true only when `Content-Length` declares the size. Chunked content is read up to the limit. `fix.diff` corrects the
comment and adds the range. There is no test, because it is a comment.

## Backlog (Low, no fix)

- **B1.** A 422 echoes each `field` in full, so its size is about the request's: 1,042,364 bytes for 1,040,446 (P7). It is
  bounded by the limit now. Cutting each `field` to a fixed length would make the 422 small whatever the keys are.
- **B2.** This predates the PR and is upstream. Under uvicorn's h11 parser, a request with both `Content-Length` and
  `Transfer-Encoding` is processed and the connection is kept (P4, `close=False`). RFC 9112 §6.1 says the server "MUST close the
  connection after responding to such a request". Production uses httptools (`http="auto"`), which answers 400 and closes, and
  nginx is in front. This is for h11 or uvicorn upstream, not cmapi.
- **B3.** With `Transfer-Encoding: chunked`, an over-limit `Content-Length` is still refused by the CL check (h11 only), although
  TE overrides CL (RFC 9112 §6.3, item 3). Refusing it is allowed ("MAY reject"), and httptools answers 400 first. No action.

## Observations, not defects

- The 413 handler reports `ctx.cfg.max_request_body_bytes`, while the middleware holds the `max_bytes` it was built with. They are
  equal today, because cmapi has no config reload (grep finds none). If a reload is ever added, both should read one value.
- The OpenAPI example of `content-too-large` always shows `maxBytes` 1048576, whatever the instance sets. It is an example.
- `MAX_VALIDATION_ERRORS = 20` repeats `MAX_PLACES` as a literal. The comment cites #353; the brief said #681.

## Files

- `r1-outputs/fix.diff`: the fixes for F1, F2 and F3, with their tests. Built from the repository root.
- Runs:
  - `r1-outputs/head-run.txt`, `base-run.txt`, `mutants.txt`
  - `fix-tests.txt`, `fix-related.txt`
  - `probes-head.txt`, `oasdiff-changelog.txt`, `oasdiff-diff.txt`
- `r1-outputs/probes/test_r1_probes_691.py` (P1-P7), `mutants.sh`, `run-fix-tests.sh`. To run the probes, copy them into
  `cmapi/tests/service/` of a head copy.
- `r1-outputs/sources/`: RFC 9110, RFC 9112, RFC 7493, the ASGI spec, the OpenShift annotations page and the router template.
