# #683: the API reads at most 1 MiB of request content, and a 422 names at most 20 errors

The implementer's record: Opus 5.5 at `high`, 2026-11-25, on `fix/683-body-size-limit` from `8633794`. The reviews go beside it
when they are done. The fix is a security control (OWASP API4), so it gets two reviewers.

## What was wrong

Nothing limited the size of a request body: not uvicorn, not Starlette as FastAPI builds it, not cmapi. pydantic reports one
error for each item it refuses, and `request_validation_handler` named each one.

**Measured, 2026-11-25, service-suite world on this Mac (PostgreSQL 16, `cmapi_impl_683`), on main `8633794`**
(`outputs/measure-before.txt`, `outputs/measure-422.txt`):

| Request (dry run of a create, signed in) | Answer on main |
|---|---|
| 2,268,919 bytes: 170,000 unknown members | 422, 15,699,474 bytes, 170,000 errors, 2.05 s |
| 2,247,821 bytes: 130,000 labels that are not strings | 422, 12,369,474 bytes, 130,000 errors, 1.82 s |
| 1,158,919 bytes: 90,000 unknown members | 422, 8,269,474 bytes, 0.95 s |
| 769,136 bytes: 60,000 unknown members (7 runs) | 422, 5,509,474 bytes, median 0.612 s |

The issue's own figures (1.68 MB, 10 MB, 1.2 s) came from another machine and body; these are this run's.

**What the edge already did.** The front door, nginx, has `client_max_body_size 1m` on the instance's site
(`cmapi-portal-ui/nginx/templates/cmapi.conf.template:94`), and the NetworkPolicy lets only the front door reach the API's port
(`deploy/manifests/components/cmapi/40-networkpolicy.yaml`). So through the Route, a body over 1 MiB got nginx's 413, as an
HTML page. Bodies up to 1 MiB reached the API, and so did any body from a caller that reaches the API's port directly. The
issue's statement "The OpenShift Route and HAProxy limits are not set in `deploy/`" holds; the front door's limit was the one
in place.

## Sources

Each fetched 2026-11-25. Copies are in `sources/` of the implementer's notes, not in the repository.

- **RFC 9110, section 15.5.14** (<https://www.rfc-editor.org/rfc/rfc9110.txt>): "The 413 (Content Too Large) status code
  indicates that the server is refusing to process a request because the request content is larger than the server is willing
  or able to process. The server MAY terminate the request, if the protocol version in use allows it; otherwise, the server MAY
  close the connection."
- **RFC 9110, section 8.6**: Content-Length "indicates the associated representation's data length as a decimal non-negative
  integer number of octets", and "a recipient MUST anticipate potentially large decimal numerals and prevent parsing errors due
  to integer conversion overflows or precision loss due to integer conversion (Section 17.5)". So `_content_length` converts at
  most 19 digits; a longer numeral is over any limit (Python's `int()` refuses more than 4300 digits).
- **RFC 9112, section 7.1** (<https://www.rfc-editor.org/rfc/rfc9112.txt>): "Chunked enables content streams of unknown size to
  be transferred as a sequence of length-delimited buffers". Section 6.3, item 6: "If a valid Content-Length header field is
  present without Transfer-Encoding, its decimal value defines the expected message body length in octets." Section 9.6: "If a
  server performs an immediate close of a TCP connection, there is a significant risk that the client will not be able to read
  the last HTTP response."
- **OWASP API Security Top 10 2023, API4, Unrestricted Resource Consumption**
  (<https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption>, source
  <https://raw.githubusercontent.com/OWASP/API-Security/master/editions/2023/en/0xa4-unrestricted-resource-consumption.md>): "An
  API is vulnerable if at least one of the following limits is missing or set inappropriately", among them "Maximum upload file
  size"; How To Prevent: "Define and enforce a maximum size of data on all incoming parameters and payloads, such as maximum
  length for strings, maximum number of elements in arrays, and maximum upload file size".
- **Starlette 1.10.0** (the lock, `cmapi/requirements.txt`), installed source. `applications.py:31` and `:52-53`:
  `max_body_size: int | None = None`, "Non-negative maximum total size in bytes of an HTTP request body. The default, `None`,
  does not limit request body size." `middleware/body_limit.py` is `RequestBodyLimitMiddleware`: it checks Content-Length when
  the application first reads (`receive_with_limit`, line 105) or starts its answer (`send_with_limit`, line 118), counts each
  message (line 110), and answers `PlainTextResponse("Content Too Large", status_code=413)` (lines 93 and 119).
- **FastAPI 0.162.2**, installed source. `applications.py:1032-1080`, `build_middleware_stack`: "Duplicate/override from
  Starlette", which never reads `self.max_body_size`. `routing.py:492-499`: an HTTPException raised while the body is read is
  raised again ("If a middleware raises an HTTPException, it should be raised again"); any other exception becomes
  `HTTPException(status_code=400, detail="There was an error parsing the body")`.
- **uvicorn 0.32.1**, installed source. No option limits a body: its limits are `limit_max_requests` (requests per process)
  and `h11_max_incomplete_event_size` (the head of a message). It sends `100 Continue` from `receive()`, the application's first
  read (`protocols/http/h11_impl.py:521-527`, `protocols/http/httptools_impl.py:556-559`). `server.py:315-319`: "Signals can only be listened to from the
  main thread", so the test runs it in a thread.
- **OpenShift Route annotations**, `openshift/openshift-docs` branch `enterprise-4.20` at `97663f0`,
  `modules/nw-route-specific-annotations.adoc` (the source of the "Route-specific annotations" page; docs.redhat.com answered
  403 to the fetch): "An individual route can override some of these defaults by providing specific configurations in its
  annotations." Its table has 14 rows: `balance`, `disable_cookies`, `cookie_name`, `pod-concurrent-connections`, the four
  `rate-limit-connections` keys, `haproxy.health.check.interval`, `ip_allowlist`, `hsts_header`, `rewrite-target`,
  `cookie-same-site` and `set-forwarded-headers`; none is for the size of a request body. The router's template
  (`openshift/router` at `735b2f0`, `images/router/haproxy/conf/haproxy-config.template`) reads those and four more
  (`timeout`, `timeout-tunnel`, `h1-adjust-case`, `ip_whitelist`), and no body size; its only size is
  `tune.bufsize {{ env "ROUTER_BUF_SIZE" "32768" }}` (line 81), HAProxy's buffer.
  The IngressController's `tuningOptions` (`openshift/api` at `49a0300`, `operator/v1/types_ingresscontroller.go:2078-2348`)
  has header buffers, timeouts, `maxConnections` and `reloadInterval`, and no body size.
- **nginx, `client_max_body_size`** (<https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size>):
  "Sets the maximum allowed size of the client request body. If the size in a request exceeds the configured value, the 413
  (Request Entity Too Large) error is returned to the client." Default `1m`.
- **Kubernetes, prior art for the size** (`kubernetes/kubernetes` at `3596eb6`,
  `staging/src/k8s.io/apiserver/pkg/server/config.go:260-262` and `:490-499`): `MaxRequestBodyBytes`, "The limit on the request
  size that would be accepted and decoded in a write request", default `3 * 1024 * 1024`, because "1.5MB is the recommended
  client request size in byte the etcd server should accept" and "we allow 2x as the largest request".

**Retracted.** The brief and the issue say neither uvicorn nor Starlette limits a body. Starlette 1.10.0 does have one,
`max_body_size`. It is off by default, and FastAPI 0.162.2 drops it: setting it on a FastAPI app does nothing. The issue's
statement holds for this app; the reason is FastAPI, not Starlette.

## The decision

**Where.** In both places. The front door keeps its 1 MiB. The API gets its own limit, because it is the one place every
request passes, whatever is in front of it (a kind or plain Kubernetes install, a caller inside the cluster, a NetworkPolicy
that a site changes), and its answer is the problem every client reads. OpenShift's router has no body limit to set, so no
Route changes.

**How.** `RequestBodyLimitMiddleware` (`cmapi/src/cmapi/core/bodylimit.py`), a plain ASGI middleware, the innermost of
cmapi's: nothing reads the body before it counts, an over-limit read that escaped the 413 handler would reach it before
`UnhandledToProblemMiddleware` could call it a failure, and its answer still passes the request-ID and CORS middleware:

1. A `Content-Length` over the limit: 413 at once. No route runs, no sign-in, no byte read. uvicorn sends `100 Continue` only
   when the application reads, so a client that waits for it gets the 413 instead.
2. No `Content-Length` (chunked): each `http.request` message is counted, and the one that passes the limit raises
   `ContentTooLarge`, an `HTTPException(413)`. FastAPI raises it again from the body's read (above). The middleware sends the
   problem itself and drops anything the application sends after the refusal, so the client gets one answer, the 413, even
   when a streamed answer's start follows its own refused read (review 691). `create_app`'s handler for the status 413 keeps
   the exception from `framework_refusal`. Content that passes the limit after an answer has started is passed on empty
   (a 413 can no longer be sent) and logged once as `content_dropped`; only a streamed answer's disconnect listener reads
   then (Starlette 1.10.0 `StreamingResponse` and `FileResponse`, ASGI spec 2.3).
3. Content longer than its `Content-Length`: what is read counts, not what is declared. uvicorn itself never passes more than the
   declared bytes (measured below).
4. The rest of a refused body is uvicorn's to drop: it reads it, discards it and keeps the connection (measured below with both
   parsers). Sending `Connection: close` would make uvicorn close at once, which section 9.6 warns can lose the answer.

The answer is the problem `content-too-large` (RFC 9110's name for 413), with `maxBytes`, the limit, as an extension member.
The document declares it on each of the 10 operations that take a body.

Rejected:
- **Starlette's `max_body_size`.** FastAPI 0.162.2 does not wire it, its answer is text/plain, and it waits for the application
  to read before it checks `Content-Length`, so the route is already chosen.
- **Starlette's `RequestBodyLimitMiddleware` added by hand, with a 413 handler.** The plain-text answers of its own except and
  `send_with_limit` paths remain, outside the problem style, and it still lets the application start before it checks a
  declared length.
- **A limit at the OpenShift router only.** There is none to set (above).

**The size.** `instance.yaml` `http.maxRequestBodyBytes`, default 1,048,576 (1 MiB). The largest create of the reference
`metadata-keys.yaml` at its maximums (`outputs/measure-before.txt`, the same on the fix) was planned (200 dry run) at:

| Annotation values (64 KiB, `json.dumps` default) | Body |
|---|---|
| ASCII | 102,581 bytes |
| U+4E2D (3 bytes in UTF-8, 6 as `\uXXXX`) | 168,085 bytes |
| U+00E9 (2 bytes, 6 as `\uXXXX`) | 233,653 bytes |
| U+0001 (1 byte, 6 as `\uXXXX`), indented | 430,701 bytes |

with 50 team labels and 50 team annotations with keys of 317 characters, labels of 63 characters, and a justification of
1,000 characters (`justification` has no maximum; see #688 below). 1 MiB is 2.4 times the worst encoding, the Kubernetes
reasoning of twice the largest object, and equals the front door's limit. A site that raises `allowOther.maxBytesTotal` raises
this with it (docs/18, "The request body limit"). The value is checked at start like every other key: a whole number, 1 or
more, and no other key under `http`. The chart writes it from `instance.http`, and its schema refuses the same values.

**The 422.** Under the limit, a body can still hold some 80,000 items that pydantic refuses one by one. `request_validation_handler`
now names the first 20 (`MAX_VALIDATION_ERRORS`, the number #681 chose for the places of one surrogate refusal), in pydantic's
order. Measured on 769,136 bytes of 60,000 unknown members, 7 runs each (`outputs/measure-422.txt`): main 5,509,474 bytes, median
0.612 s; the fix 2,354 bytes, median 0.365 s.

**Retracted.** `outputs/measure-after.txt` shows 1.499 s for that body on the fix. It was the first request of its test to
reach a route; the 7-run medians above replace it.

**Not changed: the work under the limit.** The remaining 0.365 s is pydantic refusing 60,000 members on the event loop, before
the route runs. Filed as #690. A signed-in caller can repeat it without limit: `core/ratelimit.py` holds a limiter that no
route calls (docs/08 says so; filed as #689, Medium, security).

## Proof

`cmapi/tests/service/test_body_limit_683.py`, 24 tests. The cases a test client cannot send (chunked content in several
messages, content longer than its length) go to the application as ASGI messages; `test_on_a_real_server` runs uvicorn 0.32.1
on 127.0.0.1 with h11 and with httptools and speaks HTTP/1.1 on a socket.

- Before, `cmapi/src` stashed, the file run with two stand-ins for the module main does not have (`outputs/before.txt`):
  20 failed, 2 passed. The two that pass are guards: a GET without content, and the largest real create under 1 MiB. Two tests
  came after that run: the chart test, and the middleware answering an over-limit read with no 413 handler.
- After (`outputs/after.txt`): 24 passed.
- On the wire, both parsers: a `Content-Length` over the limit is answered with no content sent; chunked content over it is
  413, and the same connection then answers `GET /api/v1/version` with 200; a `Content-Length` shorter than the content gets the
  declared bytes only: h11 answers the create (200), httptools answers its own 400 "Invalid HTTP request received." to the bytes
  after it. Neither passes them to the application.
- The related suites, 19 files (the contract, standard, samples and problem-docs suites, the #644, #646, #648, #653 and #353
  problem suites, CORS, auth, the authz review, `test_flow.py`, the plain manifests and the chart tests,
  `test_directory_shape_674.py`, the contract report): 623 passed, 3 failed (`outputs/related-suites.txt`), and the core tests
  750 passed, 113 skipped. The 3 were `test_the_create_operation_answers_what_the_design_lists`: the create now declares 413,
  so `CREATE_ANSWERS` in `test_api_standard.py` gains `"413": ["content-too-large"]`, with its reason beside it. After that,
  and after the middleware moved to the innermost place (below), 11 files rerun: 416 passed (`outputs/after-rerun.txt`).
- The probes that measured are in `probes/`: copy one into `cmapi/tests/service/` to run it.
- The contract: `contract/openapi.json` gains a 413 on 10 operations. oasdiff 1.37.0 against main: "No breaking changes to
  report"; its changelog, 10 changes, each `response-non-success-status-added` (info). `changelog.py --check`, `lint.sh`
  (Spectral), `lint-test.py` (37 cases), `gate-test.sh`, `api-examples-doc.py --check` and `doc-citations.py --check` pass
  (`outputs/contract-checks.txt`). `samples.json` is unchanged: a new recording differed only in ETags and dates, so it was
  put back. The portal's `schema.generated.ts` is written again (130 lines added).
- `doc-citations.py --relocate` moved 12 citations in docs/14 and docs/15 that the new lines of `main.py`, `docs.py` and
  `problem_docs.py` shifted; each target was read and holds what its sentence says.

Not tested: CRC and kind (no cluster was used), and the front door's own 413 (nginx; #687).

## Filed

- #687 (Low, Backlog): the front door answers its own 413, 502 and 504 as nginx HTML, not as problems, and its 1 MiB is fixed
  in the image, not taken from `instance.http`.
- #688 (Low, Backlog): string fields of the request bodies (`justification`, `comment`, `onBehalfOf`) have no maximum length;
  since #683 the body limit bounds them.
- #689 (Medium, security): rate limits are designed (docs/01, docs/02) but no route applies them; `core/ratelimit.py` is never
  called and no operation can answer 429. Out of this change's scope: it needs its own design and pull request.
- #690 (Low, Backlog): pydantic refuses a body's items on the event loop: 0.365 s for 60,000 unknown members under the limit.
