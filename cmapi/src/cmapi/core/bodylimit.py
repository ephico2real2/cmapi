"""The most bytes of request content that the API reads (#683): instance.yaml `http.maxRequestBodyBytes`.

Without a limit a caller made the API spend memory and CPU in proportion to what it sent: a 2.3 MB body of unknown members
was answered with a 15.7 MB 422 in 2.1 s on the event loop (docs/reviews/2026-11-25-issue-683). OWASP API Security Top 10
2023, API4, "How To Prevent": "Define and enforce a maximum size of data on all incoming parameters and payloads".

RFC 9110, section 15.5.14: 413 "indicates that the server is refusing to process a request because the request content is
larger than the server is willing or able to process". The answer is the problem content-too-large, as every refusal is.

Why a middleware of cmapi's own, and not Starlette's: Starlette 1.10.0 has `Starlette(max_body_size=...)` and
RequestBodyLimitMiddleware, but FastAPI 0.162.2 builds its own middleware stack (applications.py,
build_middleware_stack) and never reads `max_body_size`, and Starlette's answer is text/plain "Content Too Large".
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cmapi.core.errors import Problem
from cmapi.core.observability import log

# The default limit, 1 MiB. The largest create that the reference metadata-keys.yaml takes, at its maximums (50 team labels
# and 50 team annotations with the longest keys, 64 KiB of annotation values), is 430,701 bytes when each value byte is a
# control character that json.dumps writes as a six-byte \uXXXX escape, and 102,581 bytes in ASCII (measured, the review
# record). So 1 MiB is 2.4 times the worst encoding, as Kubernetes allows twice its largest object (3 MiB for etcd's
# 1.5 MiB, k8s.io/apiserver pkg/server/config.go). It is also the front door's limit (client_max_body_size 1m).
DEFAULT_MAX_REQUEST_BODY_BYTES = 1024 * 1024

# Content-Length is "a decimal non-negative integer number of octets", and "a recipient MUST anticipate potentially large
# decimal numerals and prevent parsing errors due to integer conversion overflows" (RFC 9110, section 8.6). Python's int()
# refuses more than 4300 digits, so a longer numeral is not converted: it is over any limit.
_LONGEST_LENGTH = 19

# The largest limit: the largest integer that JSON carries exactly, 2**53 - 1 (RFC 7493, section 2.2: a receiver cannot be
# expected to treat a larger integer "as an exact value"). The chart passes the value through JSON (toJson), which writes
# 1e21 or more as "1e+21", a string to PyYAML, and rounds a value above it (review 691, F2).
MAX_LIMIT = 2**53 - 1


def parse_http(raw: Any) -> tuple[int, list[str]]:
    """instance.yaml `http`: the limit, and the problems that stop the start."""
    if raw is None:
        return DEFAULT_MAX_REQUEST_BODY_BYTES, []
    if not isinstance(raw, Mapping):
        return DEFAULT_MAX_REQUEST_BODY_BYTES, ["instance.yaml: http must be a mapping, such as {maxRequestBodyBytes: 1048576}"]
    problems = []
    unknown = set(raw) - {"maxRequestBodyBytes"}
    if unknown:
        problems.append(f"instance.yaml: http has unknown fields {sorted(unknown)}")
    value = raw.get("maxRequestBodyBytes", DEFAULT_MAX_REQUEST_BODY_BYTES)
    # bool is an int in Python; "maxRequestBodyBytes: yes" is not a limit
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIMIT:
        problems.append(f"instance.yaml: http.maxRequestBodyBytes is a whole number of bytes, 1 to {MAX_LIMIT}, not {value!r}")
        value = DEFAULT_MAX_REQUEST_BODY_BYTES
    return value, problems


def too_large(max_bytes: int) -> Problem:
    """The problem of a request whose content is over the limit."""
    return Problem(413, "content-too-large", f"The request content is larger than {max_bytes} bytes, the most that this "
                                             "instance reads", extra={"maxBytes": max_bytes})


class ContentTooLarge(HTTPException):
    """Raised from receive() when the content read so far passes the limit.

    An HTTPException, because FastAPI 0.162.2 re-raises one from the body's read as it is (routing.py:492-494), and turns any
    other exception there into its 400 "There was an error parsing the body". RequestBodyLimitMiddleware sends the 413 that
    reaches the client; create_app's handler for the status 413 keeps the exception from framework_refusal, which would log
    it as internal-error."""

    def __init__(self, max_bytes: int):
        super().__init__(413, too_large(max_bytes).detail)


class RequestBodyLimitMiddleware:
    """Refuses request content over `max_bytes` with 413 content-too-large, for every route.

    - A Content-Length over the limit is refused before the application runs: no route, no sign-in, no byte of the content
      read. uvicorn sends no 100 Continue then, since it sends one only when the application first reads.
    - Content with no Content-Length (chunked, RFC 9112 section 7.1) is counted as it arrives, and refused at the first
      message that passes the limit. So is content longer than its Content-Length says, whatever the server lets through.
    - A request that the application never reads, a GET for one, is not counted.
    - A refusal is answered by this middleware: once the 413 is decided, nothing the application sends goes out. A streamed
      answer, Starlette 1.10.0's StreamingResponse and FileResponse under ASGI spec 2.3 (which uvicorn 0.32.1 reports), reads
      receive() for a disconnect while it streams, and its start can follow a refusal that its own read caused
      (review 691); the client still gets one answer, the 413.
    - Content that passes the limit after an answer has started is passed on empty, with its more_body unchanged: a 413 can
      no longer be sent, and the content cannot change an answer already sent. The readers after a start are those
      disconnect listeners, which drop http.request messages. It is logged once, as `content_dropped`.

    The rest of a refused body is left to the server: uvicorn reads and drops it, and keeps the connection (RFC 9112,
    section 9.6, explains why closing at once can lose the answer).
    """

    def __init__(self, app: ASGIApp, problem_response: Callable[[Problem], Response], max_bytes: int):
        self.app = app
        self.problem_response = problem_response
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > self.max_bytes:
            await self.problem_response(too_large(self.max_bytes))(scope, receive, send)
            return
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


def _content_length(scope: Scope) -> int | None:
    """The request's Content-Length, or None when it has none, or one that is not a number (uvicorn's parsers refuse such a
    request with 400 before the application sees it)."""
    value = Headers(scope=scope).get("content-length")
    if value is None or not value.isascii() or not value.isdigit():
        return None
    return int(value) if len(value) <= _LONGEST_LENGTH else 10 ** _LONGEST_LENGTH
