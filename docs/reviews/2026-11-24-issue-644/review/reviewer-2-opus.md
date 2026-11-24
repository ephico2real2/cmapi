# PR #645 · reviewer 2 (Opus 5.5, high) · rulings on reviewer 1 (Codex gpt-6.2-astra xhigh)

Read in full: `pr.diff` (378 lines), `codex-report.md` (695 lines, appendices A to D), `head/cmapi/src/cmapi/main.py`
(519 lines), and the installed Starlette 0.41.3 and FastAPI 0.115.6 sources named below. All runs are on PostgreSQL at
`127.0.0.1:55432/cmapi_wt616`, the only database named. Cluster: none (service tests with fakes). Date: 2026-11-24.

**The patch:** `review-645/r2-outputs/fix.diff`, 8 files, against `head/`. Checked on a fresh copy of `head/`: `patch -p1 -F0 -N`
exits 0, and the result is byte-identical to `review-645/r2/` (`diff -ruN` empty).

> Trap for whoever builds or applies a patch here: `examples/src/cmapi` is a symlink to `../../cmapi/src/cmapi`. A
> `diff -ruN head r2` over the whole tree follows it and writes every source hunk twice. BSD `patch` then takes the second
> copy for a reversed patch and *undoes* the first, still exiting 0. My first `fix.diff` did exactly this; the shipped one is
> built from `cmapi/` and `docs/` only.

## Summary of rulings

| # | Codex finding (severity) | Ruling | Where |
|---|---|---|---|
| 1 | Every framework 400 is labelled `json_invalid` (Medium) | **Accept, narrower fix.** Classify by `exc.__cause__`: disconnect sends nothing, decoder failure stays 422 `json_invalid`, no cause is a new registered 400 `bad-request`, any other cause is 500 `internal-error` with the cause logged. Codex's `JSONRoute`/`APIRequest`/Form-detection is not needed | In `fix.diff` |
| 2 | UTF-16/UTF-32 reach auth, contrary to docs/02 (Medium) | **Correct the sentence, do not enforce.** RFC 8259 §8.1's MUST is on the JSON text exchanged; §9 lets a parser "accept non-JSON forms". The PR's sentence and test docstring over-claimed | In `fix.diff` |
| 3 | Static range handling (Medium) | **Separate issue, raised to High:** Starlette 0.41.3 carries CVE-2025-62727, which Codex did not report. Fix: ignore Range on the static mounts (RFC 9110 §14.2 MAY), then upgrade. Codex's 70-line `AssetFileResponse` is not needed | Issue A, proven in `r2-static/` |
| 4 | Static open fails after the 200 (Medium) | **Separate issue, Low.** Not reachable in the image as built (`Containerfile:97`); the cause is file modes, fixed by an image check | Issue B |
| 5 | HEAD body not provable through TestClient (Low) | **Accept the finding, decline the wire test.** No cmapi mutant exists for it: cmapi always hands the body to ASGI on HEAD, and uvicorn drops it. Remove the vacuous assertion and rename the test to what it checks | In `fix.diff` |
| 6 | CORS does not expose `Allow` (Low) | **Accept.** One word in `EXPOSED_HEADERS`; the test kills mutant M10, which the existing CORS test cannot (it compares the header to the constant itself) | In `fix.diff` |
| 7 | Doc gaps: not-found action text; docs/02 "always with clusterId and requestId" (Low) | **Accept both doc fixes, decline both tests.** Neither test kills a code mutant: the body's field set is already pinned by `test_router_problems_644.py:55` | In `fix.diff` |

What Codex missed is in its own section below: the CVE (High), the one-line RFC route for all range findings, the
4300-digit integer case, an equivalent mutant, the vacuous test name, and the symlink trap above.

## Sources (fetched 2026-11-24 13:37 UTC with curl and quoted from the saved text, `r2-outputs/sources/`)

Every quote Codex gave was checked against the fetched text. All of them are verbatim and in the section Codex named. I
retract nothing of Codex's quotations. Where I rule against Codex, it is on what follows from a quote, stated per finding.

| Source | Quote | Used for |
|---|---|---|
| RFC 9457 §3, https://www.rfc-editor.org/rfc/rfc9457.txt | "When serialized in a JSON document, that format is identified with the "application/problem+json" media type." | media type of every answer |
| RFC 9457 §3.1.2 | "Generators MUST use the same status code in the actual HTTP response" | 422/400/500 bodies match their status (tests assert both) |
| RFC 9457 §4 | "A problem type URI SHOULD resolve to HTML [HTML5] documentation that explains how to resolve the problem." Also: "New problem type definitions MUST document: 1. a type URI ... 2. a title ... 3. the HTTP status code" | `bad-request` gets a registry entry and an action, so `/problems/bad-request` resolves |
| RFC 9110 §15.5.1, https://www.rfc-editor.org/rfc/rfc9110.txt | "something that is perceived to be a client error (e.g., malformed request syntax, invalid request message framing, or deceptive request routing)" | a framework 400 with no cause stays 400 |
| RFC 9110 §15.5.2 | "The server generating a 401 response MUST send a WWW-Authenticate header field ... containing at least one challenge applicable to the target resource." | StaticFiles' 401 stays internal-error (PR unchanged) |
| RFC 9110 §15.5.6 | "The origin server MUST generate an Allow header field in a 405 response containing a list of the target resource's currently supported methods." | PR's 405 handler (unchanged) |
| RFC 9110 §15.5.21 | "the syntax of the request content is correct, but it was unable to process the contained instructions" | 422 for undecodable JSON is cmapi's earlier choice (#164), kept as the brief says |
| RFC 9110 §14.2 | "A server MAY ignore the Range header field." / "A server MUST ignore a Range header field received with a request method that is unrecognized or for which range handling is not defined. For this specification, GET is the only method for which range handling is defined." / "An origin server MUST ignore a Range header field that contains a range unit it does not understand." | Issue A fix |
| RFC 9110 §14.4 | `Content-Range = range-unit SP ( range-resp / unsatisfied-range )`, `unsatisfied-range = "*/" complete-length`; example `Content-Range: bytes */1234` | Starlette's `*/17` is invalid |
| RFC 9110 §15.3.7.2 | "a Content-Type header field containing the "multipart/byteranges" media type and its required boundary parameter. ... a server MUST NOT generate a Content-Range header field in the HTTP header section of a multiple part response" | Starlette's multipart 206 is invalid |
| RFC 9110 §15.5.17 | "Because servers are free to ignore Range, many implementations will respond with the entire selected representation in a 200 (OK) response." | Issue A fix is conventional |
| RFC 8259 §8.1, https://www.rfc-editor.org/rfc/rfc8259.txt | "JSON text exchanged between systems that are not part of a closed ecosystem MUST be encoded using UTF-8 [RFC3629]." / "implementations that parse JSON texts MAY ignore the presence of a byte order mark rather than treating it as an error." | ruling 2 |
| RFC 8259 §9 | "A JSON parser MUST accept all texts that conform to the JSON grammar. A JSON parser MAY accept non-JSON forms or extensions." / "An implementation may set limits on the maximum depth of nesting. An implementation may set limits on the range and precision of numbers." | ruling 2; the depth and integer cases |
| Fetch Standard, https://fetch.spec.whatwg.org/#cors-safelisted-response-header-name | "A CORS-safelisted response-header name ... is a header name that is a byte-case-insensitive match for one of `Cache-Control` `Content-Language` `Content-Length` `Content-Type` `Expires` `Last-Modified` `Pragma`" | ruling 6: `Allow` is not on it |
| Fetch Standard, CORS-preflight fetch | "If a CORS check for request and response returns success and response's status is an ok status, then: ... Return response. Otherwise, return a network error." | no change to the preflight's plain-text 400: no page ever reads it |
| GHSA-7f5h-v6xp-fcq8 / CVE-2025-62727, https://api.github.com/advisories/GHSA-7f5h-v6xp-fcq8 | "An unauthenticated attacker can send a crafted HTTP Range header that triggers quadratic-time processing in Starlette's `FileResponse` Range parsing/merging logic." Affected `>= 0.39.0, <= 0.49.0`, patched 0.49.1, CVSS 7.5 | Issue A |
| Starlette release notes (master), https://raw.githubusercontent.com/encode/starlette/master/docs/release-notes.md | "Include `bytes` unit in `Content-Range` header on 416 responses." / "Set `Content-Type` instead of `Content-Range` on multi-range responses" / "Use CRLF line endings in multipart byterange boundaries" | upstream fixed the range defects: upgrade path |

Installed sources (`ob1-run/venv/lib/python3.12/site-packages/`, `starlette.__version__ == "0.41.3"`, `fastapi.__version__ == "0.115.6"`):

- `fastapi/routing.py:244-287`: inside one `try`, the body is read (`request.body()`), its content type parsed
  (`email.message.Message`), and `request.json()` called; `except json.JSONDecodeError` becomes the 422 `json_invalid`;
  `except HTTPException: raise`; `except Exception as e: ... raise http_error from e` with
  `HTTPException(status_code=400, detail="There was an error parsing the body")`. So every generic 400 carries its real
  failure as `__cause__`.
- `starlette/requests.py:218-250`: `stream()` raises `ClientDisconnect()` on `http.disconnect` and `RuntimeError("Stream
  consumed")`; `json()` is `json.loads(body)` on the bytes. `:269-271`: a `MultiPartException` becomes
  `HTTPException(status_code=400, detail=exc.message)` raised inside `except`, so with no `__cause__`.
- `fastapi/dependencies/utils.py:481-482`: a `Form` parameter calls `ensure_multipart_is_installed()` when the route is
  built. `python-multipart` is not installed (`import multipart` fails), so no form route can exist in cmapi.
- `starlette/_exception_handler.py:46-50`: a status handler is looked up before the class handler (confirms Codex 1).
- `starlette/responses.py:353-356`: a malformed Range is `PlainTextResponse(..., 400)`, an unsatisfiable one
  `PlainTextResponse(status_code=416, headers={"Content-Range": f"*/{exc.max_size}"})`, both sent directly, never raised.
  `:409`: `self.headers["content-range"] = f"multipart/byteranges; boundary={boundary}"`. `:367-378`: `_handle_simple`
  sends `http.response.start` before `anyio.open_file`.
- `starlette/testclient.py:362`: `if request.method != "HEAD": raw_kwargs["stream"].write(body)`: TestClient discards a
  HEAD body, so `head.content == b""` cannot fail.

Measured decoder behaviour (`python -I`, Python 3.12 of the venv): `json.loads(b"\xff")` raises `UnicodeDecodeError`
(a `ValueError`); `json.loads(b"1" * 5000)` raises `ValueError` (the 4300-digit limit); `json.loads(b"[" * 100000)` raises
`RecursionError`; UTF-16 with a BOM, UTF-32-BE without one, and UTF-8 with a BOM all decode to `{'a': 1}`. The
`email.message` content-type parse raised nothing for nine odd values, CR/LF included.

## Ruling 1 · the framework 400 (Codex Medium 1): accept, with a narrower fix

**Evidence before the fix** (`r2-outputs/01-new-tests-before-fix.txt`, head source with the new tests):
- a client that disconnects while sending the body was sent `{'status': 422, 'type': 'http.response.start', ...}` and a body;
- a body read that fails with `OSError` answered 422 `json_invalid`;
- a 400 that the framework raises itself (no cause) answered 422 `json_invalid`.
Codex's three claims are confirmed.

**The narrowest correct mapping.** FastAPI puts the real failure in `__cause__`, so cmapi reads it there, in the handler the
PR already has. No route class, no Request subclass, no form detection:

| `exc.__cause__` of a 400 | Answer | Why |
|---|---|---|
| `ClientDisconnect` | none: re-raised to `UnhandledToProblemMiddleware`, which returns (`main.py:103-104`); `MetricsAndRequestIdMiddleware` counts nothing without a status (`observability.py:167-169`) | nobody reads it; same as every other disconnect in cmapi |
| `ValueError`, `RecursionError` | 422 `validation-failed`, `json_invalid` (unchanged) | only the decoder raises these in that block (sources above), cmapi's #164 choice |
| `None` | 400 `bad-request`, the framework's `detail` and headers | the framework chose a client refusal (RFC 9110 §15.5.1) |
| anything else | 500 `internal-error`, log `framework_refusal` with `cause` | the service failed, not the body |

Codex's Appendix A instead adds `UnreadableJSON`, `APIRequest`, `JSONRoute` set as the `route_class` of every
`DocumentedRouter`, and a `fastapi.params.Form` check. The `JSONRoute` exists to enforce UTF-8 (ruling 2, declined), and the
Form check covers a route that FastAPI cannot build here. Under "over-build only if it is the only solution", the cause
check gives the same answers for every reachable input with one `if` per row.

`bad-request` is new: no registered 400 fits (the five 400 codes are each specific, `core/docs.py:79-83`). It needs the
registry entry, the action (`test_problem_type_docs.py:57` requires `set(ACTIONS) == set(PROBLEMS)`) and a docs/02 row.
Like `not-found`, no operation declares it, so `/openapi.json` does not change.

**Final code** (`cmapi/src/cmapi/main.py`, `framework_refusal`):

```python
    @app.exception_handler(HTTPException)
    async def framework_refusal(request: Request, exc: HTTPException) -> Response:
        """Every other HTTPException, which only FastAPI and Starlette raise: cmapi's own refusals are Problems (#646).

        FastAPI raises its 400 "There was an error parsing the body" from whatever reading the body raised
        (fastapi/routing.py:283-287), so the cause says what happened:
        - ClientDisconnect: the client went away while it sent the body. No answer is sent: UnhandledToProblemMiddleware
          ends the request, as for every other disconnect.
        - ValueError or RecursionError: the JSON decoder could not read the bytes (not Unicode text, nested deeper than it
          goes, an integer longer than 4300 digits). Only the decoder raises these there: a Form body needs
          python-multipart, which cmapi does not install, and FastAPI refuses such a route at startup. It is the 422
          validation-failed with json_invalid that a body JSON cannot parse gets (#164), so a client gets one answer
          for a body that is not JSON.
        A 400 with no cause is one that the framework chose (Starlette's form parser, starlette/requests.py:271): a client
        error, bad-request, with the framework's detail. Any other cause, and any other status, is the service's fault:
        StaticFiles' 401 (staticfiles.py:119) is a file of the image that the process cannot read, which no credential
        changes. It is internal-error, with the status and the cause in the log line. An HTTPException below 400 is no
        refusal and keeps FastAPI's answer."""
        if exc.status_code < 400:
            return await http_exception_handler(request, exc)
        cause = exc.__cause__
        if exc.status_code == 400:
            if isinstance(cause, ClientDisconnect):
                raise cause
            if isinstance(cause, (ValueError, RecursionError)):
                return problem_response(validation_failed([{"field": "body", "message": "the body cannot be read as JSON",
                                                            "code": "json_invalid"}]))
            if cause is None:
                return problem_response(Problem(400, "bad-request", str(exc.detail)[:300]), dict(exc.headers or {}))
        log.error("framework_refusal", method=request.method, status=exc.status_code, detail=str(exc.detail)[:200],
                  cause=type(cause).__name__ if cause else None,
                  route=getattr(request.scope.get("route"), "path_format", "unmatched"))
        return problem_response(Problem(500, "internal-error", PROBLEMS["internal-error"][1]))
```

`ClientDisconnect` is already imported (`main.py:23`). Registry (`cmapi/src/cmapi/core/docs.py`, after
`dry-run-not-supported`):

```python
    "bad-request": (400, "Too many fields. Maximum number of fields is 1000."),
```

Action (`cmapi/src/cmapi/core/problem_docs.py`, after `dry-run-not-supported`):

```python
    "bad-request": "Fix what `detail` names, and send the request again. FastAPI or Starlette refused the request "
                   "before any route of cmapi read it.",
```

**Tests** (`cmapi/tests/service/test_framework_problems_646.py`; imports `asyncio` and `from starlette.requests import
Request` added). The existing parametrized test gains `b"1" * 5_000` (`integer-too-long`) and a docstring that no longer
cites §8.1 as its reason (full text in `fix.diff`). New:

```python
def test_a_client_that_goes_away_while_it_sends_the_body_gets_no_answer(world, capfd):
    """Reading the body raises ClientDisconnect when the client goes away, and FastAPI raises its 400 from it. Nobody reads
    an answer then, so none is sent and none is counted, as for every other disconnect (UnhandledToProblemMiddleware)."""
    client, *_ = world
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": WRITE, "raw_path": WRITE.encode(), "root_path": "", "query_string": b"",
             "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
             "client": ("127.0.0.1", 50000), "server": ("testserver", 80)}
    capfd.readouterr()
    asyncio.run(client.app(scope, receive, send))
    assert sent == []
    out = capfd.readouterr().out
    assert _events(out, "http") == [] and _events(out, "unhandled") == [] and _events(out, "framework_refusal") == [], out


def test_a_body_read_that_fails_in_the_service_is_internal_error(world, monkeypatch, capfd):
    """Any other cause of FastAPI's 400 is a failure of the service, not of the body: internal-error, and the log line names
    the cause."""
    client, *_ = world

    async def broken(self) -> bytes:
        raise OSError("the reader failed")

    monkeypatch.setattr(Request, "body", broken)
    capfd.readouterr()
    _problem(client.post(WRITE, content=b"{}", headers=JSON), 500, "internal-error")
    logged = _events(capfd.readouterr().out, "framework_refusal")
    assert [(e["status"], e["cause"], e["level"]) for e in logged] == [(400, "OSError", "error")], logged


def test_a_400_that_the_framework_raises_itself_is_bad_request(world):
    """A 400 with no cause is a refusal that the framework chose itself (Starlette's form parser, requests.py:271): a client
    error (RFC 9110, section 15.5.1), with the framework's detail and its header fields."""
    client, *_ = world

    def endpoint():
        raise HTTPException(status_code=400, detail="Too many fields. Maximum number of fields is 1000.",
                            headers={"X-Probe": "yes"})

    client.app.add_api_route("/test-646/400", endpoint)
    r = client.get("/test-646/400")
    problem = _problem(r, 400, "bad-request")
    assert problem["detail"] == "Too many fields. Maximum number of fields is 1000." and r.headers["x-probe"] == "yes"
```

Before: these three fail (`01-new-tests-before-fix.txt`). After: pass (`02-after-fix.txt`). Mutants M1 to M9 below.

## Ruling 2 · UTF-16 and UTF-32 (Codex Medium 2): correct the sentence, do not enforce

**Measured:** with the fix, as on head, a UTF-16, UTF-16-LE, UTF-32 or UTF-32-BE body with no token answers 401
`unauthenticated`: the decoder read it and the request went on to sign-in (`test_a_body_in_utf_16_or_utf_32_is_read_as_json`,
4 cases, pass before and after).

**Decision.** The PR's docs/02 row said a body "that is not UTF-8" is `json_invalid`, and its test docstring took RFC
8259 §8.1 as the reason. §8.1's MUST binds "JSON text exchanged between systems", that is the sender; §9 says "A JSON
parser MAY accept non-JSON forms or extensions". Accepting UTF-16 breaks nothing: the decoded value goes through the same
schema validation, and no cmapi component inspects body bytes before the decoder. Enforcing would need Codex's custom
Request and route class on every router, for a guarantee no source requires. So the sentence is corrected, which is what
§9 supports. I retract nothing of Codex's measurement; I decline its conclusion that the documented contract must be
enforced, because the documented contract was the error.

**Final docs/02 row** (`docs/02-technical-design-v2.md`):

```markdown
| validation-failed | 422 | Schema, name or label rules fail. A body that the JSON decoder cannot read is this problem with `json_invalid`, with or without a token: one that does not parse, bytes that are not Unicode text, nesting deeper than the decoder goes, or an integer longer than 4300 digits (#646). The decoder reads UTF-16 and UTF-32 too, which RFC 8259 allows a parser (section 9); a client sends UTF-8 (section 8.1) |
| bad-request | 400 | FastAPI or Starlette refused the request itself before a route read it, for example a form with too many fields; `detail` is the framework's (#646) |
```

**Test** (pins the corrected sentence; it would kill an enforcement change such as Codex's `JSONRoute`):

```python
@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-32", "utf-32-be"])
def test_a_body_in_utf_16_or_utf_32_is_read_as_json(world, encoding):
    """Python's decoder reads UTF-16 and UTF-32, with or without a byte order mark (json.detect_encoding). RFC 8259, section
    8.1 puts its UTF-8 "MUST" on the JSON text that systems exchange, and section 9 lets a parser read more: "A JSON parser
    MAY accept non-JSON forms or extensions". So such a body is read, and the request goes on to the sign-in (401)."""
    client, *_ = world
    r = client.post(WRITE, content='{"name": "café"}'.encode(encoding), headers=JSON)
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated"), r.text
```

The live Claude Doc behind `docs/02` needs the same four edits (this row, the new row, the internal-error row, and the
Errors intro of ruling 7) before the export, per CLAUDE.md "Design comes from the file".

## Ruling 3 · static Range handling (Codex Medium 3): a separate issue, and High

Codex's measurements stand: the 416 says `*/17`, a malformed Range is plain-text 400, the multipart 206 puts its
boundary in `Content-Range`, HEAD and an unknown unit are refused. These are Starlette's direct responses
(`responses.py:353-356`), present on main before this PR. They are not exceptions, so no handler of this PR's kind reaches them.

**What Codex missed** decides the severity: the pinned Starlette 0.41.3 is inside CVE-2025-62727's range
(`>= 0.39.0, <= 0.49.0`). `/static/swagger` and `/static/redoc` need no token, and the front door proxies both to the API
(`cmapi.conf.template:152-157`) with header lines up to 16 KB (`:100`). Measured on the venv
(`r2-outputs/cve-2025-62727-timing.txt`): the advisory's payload costs 0.042 s, 0.180 s, 0.695 s and 2.955 s for 2,000,
4,000, 8,000 and 16,000 digits, which is quadratic and runs on the event loop.

**Is a fix in cmapi the only solution?** No re-implementation is needed. RFC 9110 §14.2: "A server MAY ignore the Range
header field." Dropping it in `ConditionalStaticFiles.__call__` removes the CVE's reach and every non-conforming answer in
one override. The browser fetches both bundles whole. Upstream has since fixed the 416 unit, the multipart Content-Type and
CRLF (release notes above), so the upgrade is the lasting fix. Codex's `AssetFileResponse` (about 70 lines: a buffered
send, a multipart writer and a range-parser wrapper) is declined.

**Not in this PR:** it is a security fix with its own record, and it changes `/static` behaviour, not the problem shape.
Issue A below is to be filed and fixed at once, under the in-session mandate. Its code and test are proven in
`review-645/r2-static/`; the patch is `r2-outputs/issue-a-static-range-fix.diff` (applies to `head/` with `-p1 -F0`):

```python
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Each file is sent whole: the Range header is dropped before Starlette reads it. RFC 9110, section 14.2: "A server
        MAY ignore the Range header field." Starlette 0.41.3's range code parses the header in quadratic time on the event
        loop (CVE-2025-62727, fixed in 0.49.1), and its 416 and multipart 206 break RFC 9110, sections 14.4 and 15.3.7.2.
        The bundles are fetched whole by the browser, so nothing needs a part of one."""
        scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k.lower() != b"range"]}
        await super().__call__(scope, receive, send)
```

(a method of `ConditionalStaticFiles` in `main.py`, before `is_not_modified`), with `cmapi/tests/service/test_static_range.py`:

```python
"""The files under /static are sent whole, whatever the Range header says (main.py, ConditionalStaticFiles.__call__).

RFC 9110 (https://www.rfc-editor.org/rfc/rfc9110.txt, read 2026-11-24), section 14.2: "A server MAY ignore the Range header
field." Starlette 0.41.3 parses it in quadratic time (CVE-2025-62727, GHSA-7f5h-v6xp-fcq8, fixed in 0.49.1), answers a 416
with "Content-Range: */17" where section 14.4 requires "bytes */17", puts a multipart boundary in Content-Range where section
15.3.7.2 requires Content-Type, and answers plain-text 400 to a unit that section 14.2 says an origin "MUST ignore".
"""
from __future__ import annotations

import pytest
from starlette.responses import FileResponse

from conftest import build_world
from test_api_docs import bundles  # noqa: F401  (the fixture: Swagger UI's and ReDoc's files, so /static is mounted)

URL = "/static/swagger/swagger-ui-bundle.js"
RANGES = ["bytes=1-2", "bytes=99-", "oops", "widgets=1-2", "bytes=0-0,5-6", "bytes=" + "0" * 16_000 + "a-"]


@pytest.mark.parametrize("value", RANGES, ids=["one-range", "unsatisfiable", "malformed", "other-unit", "two-ranges", "cve"])
def test_a_static_file_is_sent_whole_whatever_its_range(bundles, test_config, fresh_db, keys, monkeypatch,  # noqa: F811
                                                        value):
    def never(*args, **kwargs):
        raise AssertionError("the Range header reached Starlette's parser")

    monkeypatch.setattr(FileResponse, "_parse_range_header", staticmethod(never))
    with build_world(test_config, keys, monkeypatch) as (client, *_):
        whole = client.get(URL)
        for method in ("GET", "HEAD"):
            r = client.request(method, URL, headers={"Range": value})
            assert (r.status_code, r.headers.get("content-range")) == (200, None), (method, r.status_code, r.text[:200])
            assert r.headers["content-length"] == whole.headers["content-length"] and r.headers["etag"] == whole.headers["etag"]
        assert client.get(URL, headers={"Range": value}).content == whole.content
        revalidated = client.get(URL, headers={"Range": value, "If-None-Match": whole.headers["etag"]})
        assert revalidated.status_code == 304
```

**Measured.** On head with only this test added (`r2-outputs/04-static-range-before.txt`): 6 failed in 8.95 s. Each
case answered 500 because the tripwire on `FileResponse._parse_range_header` fired: the Range header reached Starlette's
parser. With the override (`r2-static/`, `05-static-range-after.txt`): `test_static_range.py`,
`test_static_preconditions_604.py`, `test_api_docs.py`, `test_router_problems_644.py` and `test_framework_problems_646.py`
gave 104 passed in 128.66 s, so the #604/#619/#620 preconditions, the 304 and the PR's static cases are unchanged.

## Ruling 4 · open fails after the 200 (Codex Medium 4): a separate issue, Low

Confirmed in source: `_handle_simple` sends the start before `anyio.open_file` (`responses.py:367-378`), and Starlette
master keeps that order. But the shipped image sets `chown -R 1001:0 /opt/app-root && chmod -R g=u /opt/app-root`
(`cmapi/Containerfile:97`), so the arbitrary UID in group 0 reads every bundle. The failure needs an image whose modes
are broken. The cause is in the image, so the fix is an image check, not a buffered `send` in cmapi (Codex's
`send_file` wrapper). See Issue B. Not in this PR.

## Ruling 5 · HEAD on the wire (Codex Low 1): accept the finding, decline the test

Confirmed: `testclient.py:362` drops a HEAD body, so the PR's `assert head.content == b""` can never fail. Codex's own
table shows why its wire test kills no cmapi mutant: "Replace every outgoing ASGI HEAD body with `b"WRONG"`: 25 passed".
That mutant is not a defect, because cmapi already hands the problem body to ASGI on HEAD (`JSONResponse` does not know the
method) and uvicorn drops it, as `_serve_head_with_get` documents. Codex's failing control injects bytes after uvicorn
serialises them, so it is a uvicorn mutant. A wire test here tests uvicorn 0.32.1, so it is declined. Fix: delete the vacuous
assertion and make the name and docstring say what is checked:

```python
def _assert_head_answers_as_get(client, path: str) -> None:
    """RFC 9110, section 9.3.2: HEAD is GET without content, with GET's status and header fields. The content is uvicorn's
    to drop (main.py, _serve_head_with_get), and TestClient drops it too before a test sees it (starlette/testclient.py:362),
    so this checks the status and the header fields."""
    get, head = client.get(path), client.head(path)
    assert head.status_code == get.status_code, (path, get.status_code, head.status_code)
    for field in ("content-type", "content-length", "allow"):
        assert head.headers.get(field) == get.headers.get(field), (path, field)
```

and `test_head_of_each_case_has_no_content` becomes `test_head_of_each_case_has_the_status_and_header_fields_of_get`, its
docstring without "with no content" (full text in `fix.diff`).

## Ruling 6 · CORS exposes Allow (Codex Low 2): accept

The PR's own recovery text says to read `Allow`, and `Allow` is not CORS-safelisted (Fetch quote above). The existing
`test_cors.py:66-67` asserts `exposed == EXPOSED_HEADERS`, comparing the header to the constant, so it cannot catch a missing
entry. The new test kills M10.

```python
# ETag is the value of If-Match on a change; Allow, Retry-After and WWW-Authenticate say what to do after a 405, a 429, a
# 503 or a 401; X-Request-Id is the line to look for in the logs. None of them is CORS-safelisted
# (https://fetch.spec.whatwg.org/#cors-safelisted-response-header-name), so another origin reads only those listed here.
EXPOSED_HEADERS = ["Allow", "ETag", "Location", "Retry-After", "WWW-Authenticate", "X-Request-Id"]
```

```python
def test_a_405_lets_the_portal_read_allow(world):
    """The problem method-not-allowed says to send one of the methods that Allow lists (#644). Allow is not a CORS-safelisted
    response header (https://fetch.spec.whatwg.org/#cors-safelisted-response-header-name, read 2026-11-24), so a page of
    another origin reads it only when the answer exposes it."""
    client, *_ = world
    r = client.delete("/api/v1/version", headers={"Origin": PORTAL})
    assert (r.status_code, r.headers[ACAO], r.headers["allow"]) == (405, PORTAL, "GET, HEAD"), r.text
    assert "Allow" in r.headers["access-control-expose-headers"].split(", ")
```

(`cmapi/src/cmapi/core/cors.py:31-33`; the test goes in `cmapi/tests/service/test_cors.py`, whose `world` lists the portal
origin.) Codex's other CORS observation, that a denied preflight is plain-text 400, gets no change: per Fetch a failed
preflight is a network error to the page.

## Ruling 7 · doc gaps (Codex Low 3): accept the text, decline the tests

- `not-found` action said the API reference "lists each path of this instance". It does not: `/problems`, `/docs`,
  `/redoc` and `/static` are `include_in_schema=False` or mounts. Final:

  ```python
      "not-found": "Check the path. The API reference (`/docs`, `/openapi.json`) lists each operation of the API, and `/problems` "
                   "each problem type. No route and no file answers this path, so the answer says nothing of an object.",
  ```
- docs/02 "Errors." said problems are "always with clusterId and requestId". No problem carries either (`grep` of
  `cmapi/src` finds them only in non-problem payloads); `Problem.body` (`core/errors.py:38-43`) builds `type, title,
  status, detail, code` plus `errors` and extras. The PR's router problems make the false claim visible. Final:

  ````markdown
  **Errors.** RFC 9457 problem details (application/problem+json): `type`, `title`, `status`, `detail` and `code`, with `errors` and the fields of the problem type where it has them (`cmapi/src/cmapi/core/errors.py`, `Problem.body`). The ID of the request is the `X-Request-Id` header of the answer. A refusal of the router comes before cmapi knows a cluster or a change request; an unknown path on an instance with the default type base answers:

  ```json
  {
    "type": "https://cmapi.ephico2real.com/problems/not-found",
    "title": "not found",
    "status": 404,
    "detail": "No resource of this API has this path",
    "code": "not-found"
  }
  ```
  ````
  The example is the measured body: `test_router_problems_644.py:55-57` asserts exactly these five fields and their values.
- The internal-error row gains "which names the status and the cause", "a body that could not be read for a reason other
  than its JSON", and "A client that goes away while it sends the body gets no answer".

Codex's `test_missing_path_help_includes_registry` and `test_design_error_example` are declined: they compare prose, and
the body shape they would protect is already pinned by `set(body) == FIELDS`.

## Mutants of the final fix

`r2-outputs/mutants.py` copies `r2/`, replaces one exact text (asserting it occurs once), and runs
`test_framework_problems_646.py` plus `test_cors.py::test_a_405_lets_the_portal_read_allow` (16 tests). One at a time, on
`cmapi_wt616`. Output: `r2-outputs/03-mutants.txt`.

| Mutant | Result | Killed by |
|---|---|---|
| M1 remove the `ClientDisconnect` branch | KILLED (1 failed) | `test_a_client_that_goes_away_while_it_sends_the_body_gets_no_answer` |
| M2 `raise cause` becomes `return None` | SURVIVED: equivalent | see below |
| M3 decoder branch is `(UnicodeDecodeError, RecursionError)` | KILLED (1 failed) | `test_a_body_that_cannot_be_read_is_validation_failed[integer-too-long]` (the case this review added) |
| M4 decoder branch without `RecursionError` | KILLED (1 failed) | `...[nested-too-deep]` |
| M5 remove the no-cause branch (so 500) | KILLED (1 failed) | `test_a_400_that_the_framework_raises_itself_is_bad_request` |
| M6 `bad-request` without the exception's headers | KILLED (1 failed) | same |
| M7 `bad-request` with the registry detail | KILLED (1 failed) | same |
| M8 log line without `cause` | KILLED (1 failed) | `test_a_body_read_that_fails_in_the_service_is_internal_error` |
| M9 every caused 400 is `json_invalid` (the PR head's mapping) | KILLED (2 failed) | the service-failure and `bad-request` tests |
| M10 `Allow` removed from `EXPOSED_HEADERS` | KILLED (1 failed) | `test_cors.py::test_a_405_lets_the_portal_read_allow` |

9 killed, 1 equivalent (M2), 0 surviving non-equivalent.

**M2 is equivalent, by source.** A handler that returns `None` sends nothing (`_exception_handler.py`: `if response is not
None: await response(...)`). uvicorn 0.32.1 then logs "ASGI callable returned without starting response." only
`elif not self.response_started and not self.disconnected` (`h11_impl.py:418`, `httptools_impl.py:424`), and its
`receive` yields `http.disconnect` only `if self.disconnected or self.response_complete` (`h11_impl.py:534`). A
`ClientDisconnect` from the body read therefore means `disconnected` is true, and both forms send and log nothing. `raise
cause` is kept because it takes cmapi's one documented disconnect path (`UnhandledToProblemMiddleware`, `main.py:103-104`)
instead of relying on Starlette skipping a `None` response.

## Runs

| Run | Tree | Result | Output |
|---|---|---|---|
| PR's two files | head copy | 25 passed in 29.58 s | `r2-outputs/00-head-baseline.txt` |
| 646 file + new CORS test, new tests in place | head source | 4 failed, 12 passed: disconnect (422 sent), service read failure (422), framework 400 (422), CORS Allow | `01-new-tests-before-fix.txt` |
| 644, 646, `test_cors`, `test_problem_type_docs`, `test_api_standard` | r2 (the fix) | 282 passed in 92.60 s | `02-after-fix.txt` |
| 10 mutants | r2 copies | 9 killed, M2 equivalent | `03-mutants.txt`, `mutants.py` |
| static Range test (Issue A) | head + test only / r2-static | 6 failed / 104 passed (5 suites) | `04-…`, `05-…` |

## What Codex missed

1. **CVE-2025-62727 (High)** on the pinned Starlette, reachable with no token through the front door; measured quadratic
   (Ruling 3, Issue A). Codex read `responses.py:354` but did not check the pinned version against advisories. GitHub's
   advisory list for Starlette (`r2-outputs/sources/gh-advisories-starlette.json`) has five more whose ranges cover
   0.41.3: CVE-2026-48710 (Host header poisons `request.url.path`, `<= 1.0.0`), CVE-2026-48817 (`HTTPEndpoint`, `< 1.1.0`),
   CVE-2026-54283 (`>= 0.4.1, < 1.3.1`) and CVE-2025-54121 (`< 0.47.2`), both form parsing, and CVE-2026-48818
   (StaticFiles on Windows only, `< 1.1.0`). A sixth, CVE-2026-54282 (`request.url.hostname`), lists no affected range.
   `grep` finds no `request.url`, `HTTPEndpoint` or `.form()` in `cmapi/src`, and the image is Linux. So none of them
   is reached by cmapi's code as it stands. I checked this by grep only, with no test. The upgrade in Issue A step 2
   clears them all.
2. **RFC 9110 §14.2's "MAY ignore"**, which turns three range findings into one override instead of a re-implementation,
   and the upstream fixes that make the upgrade the lasting fix.
3. **The 4300-digit integer**: Codex named it in its table, but no test of its covered it. Without that case, mutant M3
   (narrowing the decoder branch to `UnicodeDecodeError`) survives.
4. **The test name** `test_head_of_each_case_has_no_content` still claimed what its assertion could not check. Renamed.
5. **The symlink trap** for patches over this tree (top of this report).
6. **An equivalent mutant** of the disconnect branch (M2): see the table. It is recorded, not hidden.

## What was not tested

- No cluster (CRC or kind) and no uvicorn socket run; all results are TestClient or direct ASGI calls on PostgreSQL.
- The full service suite was not run (brief). `test_api_docs.py` and `test_static_preconditions_604.py` ran only on the
  Issue A tree.
- A real form route: none can exist without `python-multipart`; the no-cause 400 is proven with a synthetic route.
- The disconnect path through uvicorn's real receive: the test drives the ASGI app with an `http.disconnect` message.
- The CVE was timed on `_parse_range_header` directly, not end to end through nginx.
- The upgrade to a fixed Starlette/FastAPI was not attempted.
- The live Claude Doc behind docs/02 was not edited (reviewer works on the export only).

## Issue texts to file separately

### Issue A (High, security): /static answers Range with Starlette 0.41.3's vulnerable and non-conforming range code

**Parent:** #646 (found in review of PR #645). Labels: bug, security.

**What is wrong.**
1. cmapi pins `fastapi==0.115.6` (`cmapi/pyproject.toml:11`), which installs Starlette 0.41.3. Starlette 0.39.0 to 0.49.0
   carry CVE-2025-62727 / GHSA-7f5h-v6xp-fcq8 (CVSS 7.5, `AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H`): "An unauthenticated
   attacker can send a crafted HTTP Range header that triggers quadratic-time processing in Starlette's `FileResponse`
   Range parsing/merging logic" (https://github.com/advisories/GHSA-7f5h-v6xp-fcq8, read 2026-11-24; fixed in 0.49.1).
   cmapi serves `/static/swagger` and `/static/redoc` with `ConditionalStaticFiles(StaticFiles)` (`main.py:46`, `:331-334`),
   with no token whatever `docs.public` says. The front door proxies both paths to the API unchanged
   (`cmapi-portal-ui/nginx/templates/cmapi.conf.template:152-157`, `proxy-docs.conf`) and accepts header lines up to 16 KB
   (`large_client_header_buffers 4 16k`, same file line 100).
2. The same code breaks RFC 9110 where it answers (Starlette 0.41.3 `responses.py:353-356`, `:409`, `:427`, `:501-511`):
   - a 416 says `Content-Range: */17`; section 14.4 requires `unsatisfied-range = "*/" complete-length` after
     `range-unit SP`, so `bytes */17`;
   - a multipart 206 puts `multipart/byteranges; boundary=...` in `Content-Range`; section 15.3.7.2: the server "MUST
     generate ... a Content-Type header field containing the "multipart/byteranges" media type" and "MUST NOT generate a
     Content-Range header field in the HTTP header section of a multiple part response"; its parts use LF, not CRLF;
   - `Range: widgets=1-2` answers plain-text 400; section 14.2: "An origin server MUST ignore a Range header field that
     contains a range unit it does not understand";
   - a malformed Range answers plain-text 400 and an unsatisfiable one an empty 416: neither is an RFC 9457 problem.

**Measured** (2026-11-24, Starlette 0.41.3 in `ob1-run/venv`; `review-645/r2-outputs/cve-2025-62727-timing.txt`):
`FileResponse._parse_range_header("bytes=" + "0"*n + "a-", 1_000_000)` took 0.042 s, 0.180 s, 0.695 s and 2.955 s for
n = 2000, 4000, 8000 and 16000: quadratic, and on the event loop. A 16 KB header passes the front door.

**How to fix.** Two steps, in this order:
1. Now: `ConditionalStaticFiles` drops the Range header before Starlette reads it, so each file is sent whole with 200.
   RFC 9110, section 14.2: "A server MAY ignore the Range header field." Section 15.5.17's note: "many implementations
   will respond with the entire selected representation in a 200 (OK) response". The two bundles are fetched whole by
   the browser; nothing uses a part of one. This removes the CVE's reach and every non-conforming answer above, with no
   re-implementation of range handling. Proven code and test: `review-645/r2-static/` (see the review report).
2. Next: upgrade FastAPI to a release whose Starlette is at least 0.49.1, in its own issue (it also clears
   CVE-2026-48710, Host-header path poisoning, `<= 1.0.0`). Starlette's later releases also fixed the 416 unit, the
   multipart Content-Type and the CRLF framing (release notes, "Fixed": "Include `bytes` unit in `Content-Range` header on
   416 responses", "Set `Content-Type` instead of `Content-Range` on multi-range responses", "Use CRLF line endings in
   multipart byterange boundaries"). Keep step 1 after the upgrade unless a measured need for ranges appears.

**How to prove it.** `cmapi/tests/service/test_static_range.py`: for six Range values (one range, unsatisfiable,
malformed, another unit, two ranges, the CVE payload), GET and HEAD of `/static/swagger/swagger-ui-bundle.js` answer 200
with the whole file's length and ETag and no Content-Range, the GET body equals the file, `If-None-Match` still answers
304, and `FileResponse._parse_range_header` is replaced by a function that fails the test if called. Measured: 6 failed on head (the parser tripwire fired), and with the fix the five static and
problem suites gave 104 passed.

### Issue B (Low): a static file that can be stat-ed but not opened answers 200, then breaks the connection

**Parent:** #646. Labels: bug.

**What is wrong.** Starlette's `FileResponse._handle_simple` sends `http.response.start` with 200 and only then opens the
file (Starlette 0.41.3 `responses.py:367-378`; the same order in Starlette master, `_handle_simple`, read 2026-11-24).
`StaticFiles` turns a PermissionError of the *lookup* into its 401 (`staticfiles.py:117-119`), which #646 maps to
internal-error, but a file in a readable directory with no read permission passes `os.stat` and fails at the open. Then
`UnhandledToProblemMiddleware` logs `unhandled` and re-raises, because the answer has started (`main.py:110-111`), and
the client gets a 200 with a cut body.

**Where it can happen.** Not in the image as built: the Containerfile runs `chown -R 1001:0 /opt/app-root && chmod -R
g=u /opt/app-root` (`cmapi/Containerfile:97`), so OpenShift's arbitrary UID in group 0 reads every file under
`/opt/app-root/static`. It needs an image whose build changes those modes, or a volume mounted over the directory.

**How to fix.** The cause is the file modes, which the image sets; the fix belongs there, not in a re-implementation of
FileResponse in cmapi. Add an image check to CI: `find /opt/app-root/static -type f ! -perm -g=r` prints nothing, run in
the built image (or in the build stage after `chmod`). Report the start-before-open order to Starlette upstream with the
reproduction below, and take their fix through the upgrade of Issue A step 2.

**How to prove it.** In the built image: `podman run --rm --entrypoint sh <image> -c 'find /opt/app-root/static -type f !
-perm -g=r | wc -l'` prints 0; the CI check fails on an image built with `chmod 0600` on one bundle. The upstream
reproduction: a StaticFiles directory with a file of mode 000 (as a non-root user), `GET` of it through uvicorn, and the
raw socket shows `HTTP/1.1 200` then a closed connection with fewer bytes than `content-length`.

## Working copies

`review-645/r2/` (head plus `fix.diff`), `review-645/r2-static/` (head plus the Issue A fix) and
`review-645/r2-static-before/` (head plus the Issue A test only) are the trees the runs used. Every other output is in
`review-645/r2-outputs/`. No git repository, GitHub, cluster or database other than `cmapi_wt616` was touched.
