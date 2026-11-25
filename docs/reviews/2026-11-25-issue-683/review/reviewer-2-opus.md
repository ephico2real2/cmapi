# PR #691 (closes #683), reviewer 2: Opus 5.5 at high

Reviewed head `c3c62ed` from `review-691/head/`, with reviewer 1's `r1-outputs/fix.diff` applied in `r2-work/`
(`patch -p1 -F0`, clean). The service-suite world ran against PostgreSQL 16 on `127.0.0.1:55432`, database `cmapi_r2_691`,
on this Mac. No cluster was used, and no repository or GitHub was touched. Copies: `r2-work/` (the fix), `r2-headrun/`
(head), `r2-r1only/` (head plus reviewer 1's fix, with my tests).

## Verdict

- **F1: amend.** Reviewer 1 found a real defect, and the after-start pass-through is right. It is also incomplete: the
  same break remains when the refusing read comes from a streamed answer's own disconnect listener *before* its start goes
  out. Over TCP that is the head and the content in one write, at any limit below about 320 KiB. It was measured on both
  parsers with reviewer 1's fix in place (M1 below). Reviewer 1 also missed the second route family that reads after its start:
  `/static`, which needs no token.
- **F2: accept.** The bound is the same exact number in the Python check, the schema, docs/18, values.yaml and config.py.
- **F3: accept.**
- **Missed by reviewer 1:** M1 (Medium), the `/static` reach (folded into F1), and no visibility of the after-start drop
  (M2, Low, in reviewer 1's changed lines). There is also one Backlog item, B4.

## Sources, read 2026-11-25

- **ASGI HTTP spec**, `https://raw.githubusercontent.com/django/asgiref/main/specs/www.rst`, fetched 18:27 UTC (copy:
  `r2-outputs/sources/asgi-www.rst`):
  - `http.request`, `body`: "Body of the request. Optional; if missing defaults to `b""`. If `more_body` is set, treat as
    start of body and concatenate on further chunks."
  - `more_body`: "If `True`, the consuming application should wait until it gets a chunk with this set to `False`. If
    `False`, the request is complete and should be processed."
  - `http.disconnect` (HTTP): "Sent to the application if receive is called after a response has been sent or after the
    HTTP connection has been closed."
  - `asgi["spec_version"]`: "Optional; if missing assume "2.0"." Version 2.4: "Calling `send()` on a closed connection
    should raise an error".
- **Starlette 1.10.0**, installed source (`venv-merged/.../starlette/`):
  - `responses.py:247-251` `StreamingResponse.listen_for_disconnect`:
    `while True: message = await receive(); if message["type"] == "http.disconnect": break`.
    It drops every `http.request`.
  - `responses.py:270-285`: under `spec_version < (2, 4)`, `stream_response` runs in `start_soon`, and the listener runs in
    the host task. `wrap` cancels the group when either one ends.
  - `responses.py:396-410` `FileResponse.__call__`: the same shape, `if (await receive())["type"] == "http.disconnect"`, for
    a GET under spec < 2.4. Reviewer 1 did not cite this one.
  - `_exception_handler.py:55-56`: `if response_started: raise RuntimeError("Caught handled exception, but response already
    started.") from exc`.
  - `middleware/body_limit.py:104-113, 90-92`: Starlette's own limit raises from `receive_with_limit` whoever reads, and
    re-raises once started. It has F1 and M1 too.
- **anyio 4.16.0** `_backends/_asyncio.py:623-627` (`_deliver_cancellation`): "The task is eligible for cancellation if it
  has started". A task that has not started runs its first step, so `StreamingResponse.stream_response` sends its start
  before the cancellation reaches it. This is the premise of M1.
- **uvicorn 0.32.1**:
  - `protocols/http/flow_control.py:7`: `HIGH_WATER_LIMIT = 65536`.
  - `h11_impl.py:258` and `httptools_impl.py:302`: pause reading once the body passes it.
  - `h11_impl.py:521-535` `receive()`: it waits on `message_event` only when it is not already set, and returns
    `http.disconnect` once the response is complete.
  - CPython 3.12 `asyncio/selector_events.py:772`: `max_size = 256 * 1024`, the bytes read per `recv`.
  - So the first read can hold up to about 64 KiB + 256 KiB.

## F1: amend (Medium)

### What reviewer 1's snippet gets right, checked against the spec and the code

- **The message passed on** is `{**message, "body": b""}`, with `more_body` as the server sent it. The spec allows this
  shape: `body` "defaults to `b""`".
- **No loop.** Each `receive_counted()` awaits exactly one server `receive()` and returns one message, so the wrapper
  creates no message and cannot spin. Probe R5 (`r2-outputs/probes-r1fix.txt`): 6 server messages after the start reached
  the listener as 6, one-for-one: `[(..., 4096, True), (..., 0, True) x4, (..., 0, False)]`. After `more_body: False`,
  uvicorn's `receive()` blocks until the response completes or the client goes, then returns `http.disconnect`.
- **A truncated body seen as complete is harmless.** Only two kinds of code read after a start:
  - the two disconnect listeners above, which drop `http.request`;
  - `UnhandledToProblemMiddleware.receive_checked`, which only notes `http.disconnect`.

  FastAPI reads a body only for a route with a `body_field`, and before the handler runs (`fastapi/routing.py:450-475`).
  The grep of `src/cmapi` for `request.body`, `.stream()`, `.form()`, `is_disconnected` and `receive(` finds no other reader.
  `tokensave_search` literal `StreamingResponse(` finds one use, `plugins/quotas/__init__.py:161`. There are no
  `BackgroundTask` uses.
- **`http.disconnect` would be worse, so it is refused.** It is not faithful: the spec sends it "after a response has
  been sent or after the HTTP connection has been closed", and neither is true mid-stream. It also cuts the answer.
  Probe R3: a disconnect delivered just after the 200 start gave `starts=[200] body=b'' complete=False`. `wrap` cancels
  `stream_response` (`responses.py:279-285`).
- **"Nothing over the limit reaches the application" is true for every route.** The crossing message is emptied whole,
  so the application sees at most the bytes before it, which are at most `max_bytes`. Every read passes through the wrapper.

### M1: what the snippet misses: the refusal raised *before* the stream's start

**Mechanism.** In `StreamingResponse.__call__` the host task reads first. If the content over the limit is already
buffered, `receive_counted` raises with `started == False`.

Then anyio runs the stream task's first step during teardown, because a task that has not started is not cancelled. That
first step sends the 200 start. Starlette's wrapper then turns `ContentTooLarge` into
`RuntimeError(... already started)`, and the middleware's `except ContentTooLarge` misses it. The result is the
F1 symptom: a cut 200, `unhandled` at error level with a traceback, and uvicorn's "Exception in ASGI application".

**Measured with reviewer 1's fix in place.** Probes in `r2-outputs/probes/test_r2_probes_691.py`, outputs
`probes-r1fix.txt` and `probes-r7-r1fix-{1,2,3}.txt`:

| Case | Head | Head plus reviewer 1's fix |
|---|---|---|
| R1, ASGI, export, the over-limit message at the first read | 200, `complete=False`, `unhandled`, RuntimeError | the same |
| R2, ASGI, `/static/swagger/...` (no token), after the start | 200 cut, `unhandled` | whole 307,204 bytes |
| R2, the same, before the start | 200 cut, `unhandled` | 200 cut, `unhandled` |
| R4, TCP, LIMIT 4096, head and content in one write, h11 and httptools | 200 head only, `unhandled` | the same |
| R6, TCP, default 1 MiB, head and 1.5 MiB in one write, export and `/static`, both parsers | `ConnectionResetError` in all 4 | whole in all 4 |
| R7, TCP, 3 runs per limit and parser (export) | not run | 64 KiB: RESET and `unhandled` 6/6. 128 KiB: 3/6. 256 KiB: 3/6. 512 KiB: 0/6 |

So reviewer 1's fix holds at the default 1 MiB, because uvicorn's first read cannot exceed about 320 KiB (sources above).
It does not hold at a lowered limit. The schema takes any value from 1, and the PR's own test world uses 4096. Reviewer 1's
analysis also missed `FileResponse`: with the default 1 MiB on head, an unauthenticated `GET /static/...` with chunked
content resets the connection and logs `unhandled` (R6, 4/4). This is also why F1 is reachable with no `objects:read`.

### The fix: after a refusal, the middleware answers

`bodylimit.py`, `RequestBodyLimitMiddleware.__call__` (full code in `r2-outputs/fix.diff`):

```python
        received = 0
        started = False  # an answer's start has gone to the client
        refused = False  # the content passed the limit before any answer started: the answer is the 413

        async def receive_counted() -> Message:
            nonlocal received, refused
            message = await receive()
            if message["type"] == "http.request":
                size = len(message.get("body", b""))
                received += size
                if received > self.max_bytes:
                    if started:
                        if received - size <= self.max_bytes:
                            log.info("content_dropped", reason="content-too-large", max_bytes=self.max_bytes)
                        return {**message, "body": b""}
                    refused = True
                    raise ContentTooLarge(self.max_bytes)
            return message

        async def send_tracked(message: Message) -> None:
            nonlocal started
            if refused:
                return  # the 413 below is the answer, whatever the application sends after the refusal
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive_counted, send_tracked)
        except Exception as exc:
            # The refusal itself, or Starlette's RuntimeError("Caught handled exception, but response already started.")
            # raised from it when a streamed answer's start followed the refusal (_exception_handler.py:55-56).
            if not refused or not (isinstance(exc, ContentTooLarge) or isinstance(exc.__cause__, ContentTooLarge)):
                raise
        if refused:
            await self.problem_response(too_large(self.max_bytes))(scope, receive, send)
```

**Why this design.**
- `refused` is set only while nothing has started, so the client gets exactly one answer: the 413 if the first over-limit
  read came before any start went out, and the whole answer if it came after.
- The exception filter swallows only the refusal or Starlette's RuntimeError raised `from` it. Anything else still reaches
  `UnhandledToProblemMiddleware`.

**Rejected:**
- *Yield once before raising and re-check `started`.* It depends on scheduling, not on a rule.
- *Hold the application's messages after a refusal and replay them if it returns normally.* It buffers more for no gain.
- *Forward only a start whose status is 413.* It sniffs the status.

**Behaviour preserved.**
- In the ordinary chunked refusal, the 413 handler's answer is now dropped, and the middleware sends the same problem
  through the same outer `send`, so the bytes are the same.
  - `test_chunked_content_over_the_limit_is_refused_at_the_message_that_passes_it` still asserts the full problem, the
    `X-Request-Id` and 2 reads.
  - The handler stays: without it, `framework_refusal` would log the 413 as `internal-error` (`main.py`, its docstring).
- The Content-Length path is unchanged.
- The `main.py` comments say the new rule. They keep their line count, so docs/14's citations hold:
  `doc-citations.py --check`, "0 problems" (`r2-outputs/doc-citations.txt`). A longer first version moved 4 citations,
  so I shortened it.
- The PR's README, step 2 of "How", now describes this.

**Tests** (in `test_body_limit_683.py`). The failures were measured before the fix (`r2-outputs/new-tests-on-head.txt`,
`new-tests-on-r1fix.txt`), and every test passes after:

| Test | Head | Reviewer 1's fix | This fix |
|---|---|---|---|
| `test_a_streamed_answer_that_starts_after_its_own_read_refused_the_content_is_replaced_by_the_413` | fails | fails | passes |
| `test_a_static_file_with_content_over_the_limit_gets_one_whole_answer[after the start]` | fails | passes | passes |
| `…[before the start]` | fails | fails | passes |
| `test_on_a_real_server_a_streamed_export_with_content_over_the_limit_gets_one_whole_answer[with the head-h11/httptools]` | fails | fails | passes |
| `…[after the start-h11/httptools]` | fails | passes | passes |
| Reviewer 1's F1 test, now with two messages past the limit and one `content_dropped` | fails | fails (no log) | passes |

The real-server "after the start" case waits for the 200's head on the socket before it sends the content, so it is
deterministic. The three runs of the 10 streaming tests passed 10/10 each (`fix-tests-realserver-{1,2,3}.txt`).

## M2 (Low, in reviewer 1's changed lines): the after-start drop was silent

With reviewer 1's fix, content over the limit after a start left no trace. The `http` line says 200, and no counter moves.

The fix logs `content_dropped` once per request, at the message that crosses the limit, at info level, with
`max_bytes` and the bound `request_id`.

Its test is reviewer 1's F1 test, which now has a second over-limit message and asserts exactly one event. Two mutants
are killed: no log, and a log on every message.

## F2: accept

- **The number is the same in every place:** `bodylimit.py MAX_LIMIT = 2**53 - 1`, `values.schema.json "maximum":
  9007199254740991`, values.yaml "1 to 9007199254740991 (2^53 - 1)", docs/18 "9007199254740991 (2^53 - 1 …)", and
  config.py "1 to 2**53 - 1". `python3 -c 'print(2**53-1)'` gives 9007199254740991.
- **One more reason for the bound.** `_content_length` turns a numeral longer than 19 digits into `10**19` and calls it
  "over any limit". On head, with no upper bound, a limit of `10**19` or more made that false. With the bound
  (2^53 - 1 < 10^19) it is true.

## F3: accept

The comment is right: chunked content is read up to the limit.

## The other points of the brief

- **Middleware order.**
  - `RefuseNulMiddleware` answers a NUL path before any read. With an over-limit Content-Length as well, the answer is its
    422, and neither middleware reads the body.
  - `UnhandledToProblemMiddleware` sees a refusal only as the exception that F1 and M1 leaked. With the fix, every refusal
    ends inside the body-limit middleware, and its 413 goes out through `send_checked`, `MetricsAndRequestIdMiddleware` and
    CORS.
  - Nothing outer swallows a 413. The tests assert `X-Request-Id` on the 413.
- **Metrics and logs of a 413.**
  - Each refusal is counted in `cmapi_http_requests_total{status="413"}`, gets a duration, and is logged as `http` with
    `status: 413` (`observability.py:160-176`).
  - A Content-Length refusal is labelled `route="unmatched"` and has no `caller_sub`, because the router and the sign-in
    never ran. The status label tells it apart from a 404.
  - There is no dedicated counter. I judge the status label enough, so I make no finding.
- **`ContentTooLarge` in a background task.**
  - cmapi has no `BackgroundTask` or `BackgroundTasks` (grep).
  - Starlette runs `self.background()` after the answer and passes it no `receive` (`responses.py:287-288`). It cannot
    raise one.
- **Config surface.**
  - `http` takes one key. Unknown keys stop the start, and the schema has `additionalProperties: false`.
  - The chart writes it (`templates/config.yaml:40`, `toJson ($inst.http | default dict)`).
  - The plain manifests (`deploy/manifests/environments/{kind,crc}/20-config.yaml`) omit `http`, as they omit `problems` and
    `cors`, so they take the default. That is consistent (B4).

## Backlog (Low, no fix)

- **B4.** The plain manifests and `examples/instances/*/instance.yaml` show no commented `http` line, as they do for
  `cors`. An operator of plain YAML finds the key only in docs/18.
- **Upstream note, no cmapi change.** Starlette 1.10.0's own `RequestBodyLimitMiddleware` has F1 and M1
  (`body_limit.py:104-113, 90-92`). It could be reported upstream.

Reviewer 1's B1 to B3 stand.

## Results

- `r2-outputs/fix.diff` is complete against `head/`: 8 files, 499 lines. It applied with `patch -p1 -F0` to a fresh copy of
  head and gave a tree identical to `r2-work` (`diff -r`).
- `test_body_limit_683.py` on the fix: **35 passed** (`r2-outputs/fix-tests.txt`).
- Related suites on the fix: **309 passed** (`r2-outputs/fix-related.txt`):
  - `test_body_limit_683`, `test_value_error_648`, `test_head_605`, `test_list_filters`;
  - `test_api_standard`, `test_api_docs`, `test_framework_upgrade_651`, `test_router_problems_644`.
  - One caveat: this run used the F1 test before its last edit, the second message. The file alone was re-run after that
    edit: 35 passed.
- Mutants (`r2-outputs/mutants.sh`, `mutants.txt`). All 6 were killed:

| Mutant | Tests failed |
|---|---|
| No drop after the refusal | 8 |
| No RuntimeError cause | 4 |
| No log | 1 |
| Raise after the start (reviewer 1's fix removed) | 4 |
| No own 413 | 9 |
| Log on every message | 1 |

- `doc-citations.py --check`: 0 problems, run in a throwaway git copy in the scratchpad.

Not tested: CRC and kind; the spec-2.4 path, which no server here sends (uvicorn 0.32.1 sends 2.3).
