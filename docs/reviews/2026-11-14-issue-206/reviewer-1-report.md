# Reviewer 1 — cmapi #206 / #216

Completed review. Three proven P2 findings; no demonstrated wildcard/regex membership bypass or unauthenticated successful write. Export HEAD: `6ec368fd7d82a50f192e56ca5c0f9951d4bad612`; base: `418e934`. `change.diff` is the review boundary. No repository operations, containers, clusters, services, or database connections are used. The service suite is not run.

TokenSave context/status/read were attempted, but this export is not an initialized project and the server has no default project. Local read-only inspection is used instead; no other project is accessed or indexed.

Isolated dependencies are installed in `.review-venv`. All proposed fixes remain in scratch copies; the exported application and service-test sources are unchanged. Full diffs and service-test additions are embedded below.

## Proven findings

### F1 [P2] Validate the URL before deriving the fallback origin (breaks C1)

`cmapi/src/cmapi/core/cors.py:35-41,53-65,81-86`: `urlsplit` is not a browser URL parser. `portalUrl: 'https://portal.example.com\@evil.example/'` grants `https://evil.example`, while the browser treats the backslash as a path separator and the portal's origin is `https://portal.example.com`. Port zero is silently removed; Unicode domains and uncompressed IPv6 are returned in a form browsers do not send. An embedded host space is even accepted as an exact origin. This can grant an unintended origin through the fallback or silently disable the intended portal. This does **not** bypass Starlette's exact membership check: all emitted ACAO values remain in the returned list.

Evidence: `review_scratch/probe.py` / `probe.out`, using the export's functions directly. Fix: reject ambiguous/non-ASCII URL text (require an ASCII/punycode host), validate host syntax, serialize IPv6 and port zero correctly, and validate the original portal URL before stripping its components. Full patch and regression tests are embedded below.

### F2 [P2] Vary the denied and originless cache variants too (breaks C2)

`cmapi/src/cmapi/main.py:88-89`, installed `starlette/middleware/cors.py:84-86,153-165,170-172`; documented incorrectly at `docs/15-keycloak-integration.md:199`: a listed simple response **does** have `Vary: Origin`. A denied-origin or originless simple response has none. A shared cache that stores such a public response can reuse the no-ACAO variant for the listed portal, causing the browser to hide a response it should be able to read. This is an availability/cache correctness defect, not evidence of reading authenticated data from another origin. Fix: add `Vary: Origin` on every HTTP response while CORS is enabled, including originless requests. Full patch and regression tests are embedded below.

### F3 [P2] Preserve cancellation and disconnect semantics across the middleware stack (breaks C5; qualifies C4)

`cmapi/src/cmapi/main.py:75-81`, `cmapi/src/cmapi/core/observability.py:73-92`; installed `starlette/middleware/base.py:144-164,185-189` and `starlette/requests.py:233-235`: the catch-all catches `ClientDisconnect` as an application failure and logs/returns an internal-error 500. In the two BaseHTTPMiddleware layers, an endpoint's `asyncio.CancelledError` can instead become `RuntimeError('No response returned.')`; the catch-all logs that as `unhandled`, and the outer layer emits Starlette's plain 500 without CORS or request ID. Cancellation is a BaseException, but checking only the catch clause misses this task-group transformation. Normal external task cancellation and a coroutine explicitly raising cancellation are tested separately below.

Evidence: deterministic in-process ASGI receive stream (`partial http.request` then `http.disconnect`) and an endpoint raising `asyncio.CancelledError`, in `review_scratch/probe.py`. No sockets or database are involved. Fix: use ASGI middleware for both layers, propagate cancellation unchanged, end a disconnected request without generating a new response, and never attempt to replace a response after it has started. Full patch and regression tests are embedded below.


## Claim verdicts against the export

| Claim | Verdict and source evidence |
|---|---|
| C1 | **Partly refuted (F1).** The validator does not ensure a canonical browser origin. **Confirmed:** there is no way through these inputs to make the configured Starlette middleware grant an ACAO value outside the returned list: `cors.py:48-51,87-93`, `main.py:88-89`, installed `cors.py:95-102,164-172`. Incorrect parsing can put the wrong origin *in* the list. See the complete input matrix below. |
| C2 | **Partly refuted (F2).** Exact list membership, no regex, no ACAC, and no wildcard ACAO are correct. `allow_origin_regex` is omitted in `main.py:88-89`; installed `cors.py:30-42,95-102`. **A listed simple response does not lack Vary**: installed `cors.py:164-172`; the existing service assertion at `test_cors.py:57` is correct. Denied and originless variants lack Vary, so a shared cache may reuse a no-ACAO response for the listed portal and make its response unreadable. A different listed origin's cached ACAO would also fail the browser's exact-origin check; this is not proof of a cross-origin data disclosure. |
| C3 | **The security conclusion is supported, but the universal Idempotency-Key premise is false.** `auth.py:189-206` obtains only the OAuth2 bearer Authorization header and passes it to `Authenticator.authenticate`; it reads no cookie, query token, body credential, or proxy identity. The verifier checks signed tokens at `auth.py:150-186`. `main.py:117-119` puts bearer authentication on all state-changing routers. A safelisted **POST `/api/v1/requests/{request_id}:cancel`**, `Content-Type: text/plain`, no Authorization, is routed and refused with **401** before the state change (`routers/requests.py:164-175`). No successful unauthenticated business-state change was found. The route has no body and no Idempotency-Key dependency, and an authenticated call can succeed without that key. Likewise `:approve`, `:retry`, and the admin auto-approval switch are not universally keyed. Namespace creation requires a key (`plugins/namespaces/router.py:41-48,137-154`), with dry-run exemption. `DocumentedRouter.write` adds no key automatically (`core/docs.py:184-190`). Thus CORS does not stop delivery of all writes: bearer authentication is the essential barrier for safelisted requests. `core/cors.py:20` also overstates Content-Type: a text/plain value alone does not require preflight. This existing route design is not a new authorization flaw introduced by this diff. |
| C4 | **Confirmed for the named ordinary application responses, not an absolute guarantee.** The three user middleware run **CORS → metrics/request ID → catch-all**, followed by ExceptionMiddleware and the router. Starlette adds **ServerErrorMiddleware outside all three** (`applications.py:80-100,132`). Problem, request validation, router 404, 429 and a pre-response RuntimeError→internal-error 500 all receive ACAO for the listed origin. Normal `/docs` and mounted StaticFiles also receive it (`main.py:164-167,198-210`); neither is an exception to wrapping. A logger failure inside the catch-all (`main.py:80`) produces the outer plain `Internal Server Error` 500 without ACAO or request ID, reproduced by making `log.exception` raise. F3 reproduces another outer plain 500 through cancellation. A streaming failure after the first byte does **not** remove CORS from the already-sent headers; it leaves a failed/truncated response and cannot send a replacement 500. |
| C5 | **Ordinary pre-response exception handling is correct; cancellation/disconnect assurance is refuted (F3).** The catch-all response uses only static registry text and internal-error (`main.py:69-81`, `core/docs.py:83`), with no exception text or class. Real configured JSON logging includes the traceback and the matching request ID (`observability.py:55-61,75-77`; `main.py:80`). The normal 500 increments `cmapi_http_requests_total{status="500"}` exactly once: inner catch-all returns a Response, outer instrumentation follows `observability.py:93` rather than `90-92`. HTTPException uses FastAPI's handler; Problem, RequestValidationError, TierError and ValueError keep their handlers (`main.py:92-112`), verified individually. This no-exception-text assertion is about the catch-all; ValueError's own handler deliberately returns its text. Late failures and cancellation details appear below. |
| C6 | **Confirmed, with an operator-documentation caveat.** Absent `allowedOrigins` (including `cors: {}` and `cors: null`) falls back; an explicit `allowedOrigins: []` does not (`cors.py:74-89`). Explicit `allowedOrigins: null` is rejected, not fallback. `main.py:87` installs no CORS middleware for an empty result, so application responses send no Access-Control-* headers. Helm renders `cors: {}` by default (`templates/config.yaml:34`, `values.yaml:25`); this enables the portal fallback once portalUrl is set, and is not an explicit off switch. CRC omits cors and now supplies the portal origin (`20-config.yaml:19-31`), so enables that origin. The empty map can surprise an operator who equates it with off. Clarify the Helm comment with the exact nested off setting; see the documentation-only recommendation below. The fallback itself matches the documented design (`docs/15:192`). |
| C7 | **Supported within this review's API/portal trust model.** `cors.py:21,24-25` exposes ETag, resource Location, retry/challenge metadata and request ID, not a bearer token, cookie or signing key. It permits explicit bearer/concurrency/idempotency headers; allowing a header does not create credentials or bypass authorization. Starlette also adds the standard safelisted request headers (`starlette/middleware/cors.py:12,58-60`). 600 seconds is at WebKit's current cap and below Chromium's; browsers can cap further or evict entries. This is not a promise of a minimum cache lifetime. See primary sources below. |

## C1 input matrix (direct execution)

All entries describe the **export**, before any proposed fix. Values below are YAML scalar/list values, not regex configuration.

| Input | Observed result |
|---|---|
| `allowedOrigins: "*"` | Reject: list required (`cors.py:88-89`). |
| `allowedOrigins: ["https://portal.example", "*"]` | Reject: wildcard (`48-49,90-92`). |
| `["null"]` | Reject: opaque origin (`50-51`). |
| `["https://.*.example.com"]` / `https://*.example.com` | Reject: wildcard. |
| `["https://portal.example.com$"]` | Accepted **literally**; a probe of this value gets ACAO only for that identical string, not for `https://portal.example.com` or a suffix. No regex interpretation. Other regex-shaped text can be malformed as a URL. |
| `["https://portal.example.com."]` | Accepted and matched exactly; the trailing dot is retained by the WHATWG URL serializer and is a different origin from the spelling without it. |
| `["https://bücher.example"]` | Accepted, but a browser serializes it as `https://xn--bcher-kva.example`; the browser spelling will not match. F1. |
| `["https://xn--bcher-kva.example"]` | Accepted, exact match. |
| Uppercase host/scheme | Explicit list spelling rejected by comparison with origin_of (`63-64`); portalUrl case is normalized. |
| `["https://portal.example.com:443"]` | Rejected as noncanonical. Fallback `https://portal.example.com:443/x` correctly returns `https://portal.example.com`. |
| Userinfo in an explicit origin | Rejected (`59-60` and canonical comparison). |
| `http://[::1]:5173`, `https://[2001:db8::1]` | Accepted; brackets retained correctly. |
| `https://[2001:0db8::1]` | Accepted in list/fallback with the uncompressed zero group; browsers serialize `https://[2001:db8::1]`. F1. |
| Whitespace/newline | Explicit leading space, tab/newline stripped by urlsplit are rejected through unequal serialization. **Embedded host space** (`https://bad host.example`) is accepted, although it is not a browser host. Fallback strips some control characters before validation, e.g. newline in host; no newline is reflected in ACAO. F1 rejects ambiguous raw text. |
| Number, mapping, `true` as a list item | Rejected as not text (`46-47`). As the whole allowedOrigins value: rejected because not a list (`88-89`). |
| `portalUrl: https://portal.example.com@evil.example/` | Returns `https://evil.example`. This agrees with the browser: portal.example.com is userinfo, not the host. |
| `portalUrl: https://evil.example#https://portal.example.com` | Returns `https://evil.example`, correctly; the apparent portal URL is a fragment. |
| `portalUrl: //evil.example` | Rejected: no accepted scheme. |
| `portalUrl: https://portal.example.com:443/x` | Returns `https://portal.example.com`, correctly. |
| `portalUrl: 'https://portal.example.com\@evil.example/'` (one backslash) | Returns `https://evil.example`; WHATWG URL origin is `https://portal.example.com`. F1. |
| `portalUrl: https://portal.example.com:0/x` | Incorrectly returns `https://portal.example.com`; browser retains `:0`. Explicit `:0` is also rejected. F1. |
| Nonempty non-string portalUrl | Number, mapping and true probes are rejected after string coercion, though the error is indirect. Falsy 0/false behave as missing and return `[]` (`79-81`). No wildcard expansion results. |

Node's built-in WHATWG `URL` was used locally to cross-check the Unicode, IPv6, port-zero, userinfo, fragment, backslash and trailing-dot cases; output is in [browser_urls.out](review_scratch/browser_urls.out). This is URL serialization evidence, not a deployed-browser integration test. Browser parsing/canonicalization is defined by the [URL Standard](https://url.spec.whatwg.org/#concept-url-origin).

## C5 lifecycle checks and limits

- A normal endpoint RuntimeError before response start: one static problem 500, one unhandled log with traceback/request ID, one status=500 metric. Proven against the export.
- A `StreamingResponse` yielding `first` and then raising: `call_next` already returned when headers arrived; the catch clause in `main.py:77-81` no longer covers the body iterator (`starlette/middleware/base.py:168-183,187-188`). One 200 start with CORS/request ID, a partial body, no replacement 500, no unhandled event from this catch-all, and one 200 metric. Exception escapes to the caller/server. This is a limit on the assurance, not a request to rewrite headers already sent.
- An immediately failing BackgroundTask: same blind spot after headers, exception escapes with no unhandled event from this catch-all and status counted as 200. Tests exercise this timing, not every possible background-task scheduling interleaving. Background task results cannot change an already-sent HTTP status. F3's ASGI fix logs a late application failure and rethrows while retaining the original status; stream failures can be ExceptionGroups.
- Endpoint explicitly raising `asyncio.CancelledError`: BaseHTTPMiddleware transforms this into “No response returned”; unhandled event plus outer headerless 500. F3 fails before, passes after.
- External cancellation of the request task while endpoint waits: propagates as CancelledError, without an unhandled event or a response. This path was already correct; tested separately from endpoint-raised cancellation.
- A raw-body endpoint receives partial body then `http.disconnect`: ClientDisconnect is misclassified as unhandled and returned/counted as 500. F3 fails before, passes after.
- FastAPI's JSON body parser catches the disconnect in its own parsing path and returns 400 without unhandled logging; this path was already correct. F3 is not a claim that every disconnect in the current service causes 500. The regression route deliberately isolates the transport exception from that parser.
- Exceptions raised by the catch-all itself remain outside its protection. For example a failing log sink reaches ServerErrorMiddleware (`starlette/middleware/errors.py:155-187`) before a response starts, so its fallback 500 has no application CORS/request-ID headers. Neither original nor proposed code promises to recover from every failure of its own recovery path.

## Complete fixes and service regressions

Each F1/F2/F3 patch below is a unified diff **against this export**, including tests appended to `cmapi/tests/service/test_cors.py` using `world`. **Those service tests were written and syntax-checked, not run**: their fixtures require the prohibited shared PostgreSQL. Their standalone equivalents are the executed tests in [test_defects.py](review_scratch/test_defects.py), using [harness.py](review_scratch/harness.py). That harness AST-loads the actual nested handlers/catch-all and imports the actual instrumentation/cors/errors/tiers modules without importing `cmapi.main` or `core.context`; it starts no lifespan, metrics server, adapter, database or network listener.

F1 deliberately enforces an ASCII DNS/IP URL subset and tells operators to use punycode for an IDN. It rejects ambiguous inputs before extracting the portal host, and correctly serializes IPv6/port zero. It does not attempt an incomplete IDNA2003 translation of browser UTS46 behavior.

F2 preserves existing Vary entries and avoids duplicate Origin or `Vary: *` entries. It runs only when the factory enables CORS.

F3 replaces both BaseHTTPMiddleware task boundaries with ASGI wrappers; changing only `except Exception` would not fix cancellation transformed by the outer instrumentation. It propagates cancellation, ends ClientDisconnect without fabricating a response, converts closed-send OSError to disconnect, and avoids sending a second response after start. Late failures are logged with the request context and rethrown. Counters record one actual response status; requests cancelled/disconnected before headers produce no fabricated 500 metric.

The files overlap; apply the merged [combined.patch](review_scratch/combined.patch) to take all three fixes. It passed `patch --dry-run -p1` against the export. Separate patches are alternatives for reviewing each finding, not sequential patches to apply blindly.

### F1 — full fix and service test diff

```diff
--- a/cmapi/src/cmapi/core/cors.py
+++ b/cmapi/src/cmapi/core/cors.py
@@ -12,6 +12,9 @@
 - Only the request headers that the API reads, and only the response headers that a client needs.
 """
 from __future__ import annotations
+
+import ipaddress
+import re
 
 from typing import Any, Mapping
 from urllib.parse import urlsplit
@@ -32,13 +35,32 @@
 
 def origin_of(url: str) -> str:
     """scheme://host[:port] of a URL, as a browser writes the Origin header (lower case, no default port, no path)."""
-    parts = urlsplit(url)
-    host = (parts.hostname or "").lower()
-    if ":" in host:
-        host = f"[{host}]"
-    default = {"https": 443, "http": 80}.get(parts.scheme)
-    port = f":{parts.port}" if parts.port and parts.port != default else ""
+    # Accept an unambiguous subset of browser URLs. Operators must spell IDNs as punycode.
+    if not isinstance(url, str) or not url or not url.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
+        raise CorsConfigError("URL must be ASCII text without whitespace or backslashes; use a punycode host")
+    try:
+        parts = urlsplit(url)
+        port_number = parts.port
+        host = (parts.hostname or "").lower()
+        if parts.scheme not in ("http", "https") or not host:
+            raise ValueError("must be an absolute http(s) URL")
+        if ":" in host:
+            if "%" in host:
+                raise ValueError("IPv6 zone identifiers are not browser origins")
+            host = f"[{ipaddress.IPv6Address(host).compressed}]"
+        else:
+            labels = host.removesuffix(".").split(".")
+            if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
+                raise ValueError("invalid DNS host")
+            # Browsers interpret a numeric final label as an IPv4 address. Only accept canonical IPv4.
+            if re.fullmatch(r"[0-9]+|0x[0-9a-f]*", labels[-1]):
+                host = str(ipaddress.IPv4Address(host))
+    except ValueError as exc:
+        raise CorsConfigError(f"is not a URL ({exc})") from exc
+    default = {"https": 443, "http": 80}[parts.scheme]
+    port = f":{port_number}" if port_number is not None and port_number != default else ""
     return f"{parts.scheme}://{host}{port}"
+
 
 
 def _problem(value: Any) -> str | None:
@@ -60,8 +82,12 @@
         return "must be scheme://host[:port] only: no path, no query, no fragment, no user"
     if parts.scheme == "http" and parts.hostname.lower() not in {h.strip("[]") for h in LOCAL_HOSTS}:
         return "must be https: http is for localhost only"
-    if value != origin_of(value):
-        return f"must be written as the browser sends it: {origin_of(value)}"
+    try:
+        origin = origin_of(value)
+    except CorsConfigError as exc:
+        return str(exc)
+    if value != origin:
+        return f"must be written as the browser sends it: {origin}"
     return None
 
 
@@ -78,7 +104,10 @@
         portal = instance.get("portalUrl")
         if not portal:
             return []
-        origin = origin_of(str(portal))
+        try:
+            origin = origin_of(portal)
+        except CorsConfigError as exc:
+            raise CorsConfigError(f"instance.yaml portalUrl {portal!r}: {exc}") from exc
         problem = _problem(origin)
         if problem:
             raise CorsConfigError(f"instance.yaml portalUrl {portal!r} gives the origin {origin!r}, which {problem}. "
--- a/cmapi/tests/service/test_cors.py
+++ b/cmapi/tests/service/test_cors.py
@@ -188,3 +188,25 @@
     before = counter._value.get()
     assert client.get("/api/v1/tiers", headers=auth(keys, "ola", **OLA)).status_code == 500
     assert counter._value.get() == before + 1
+
+
+# Reviewer 1 / F1: add to cmapi/tests/service/test_cors.py.
+@pytest.mark.parametrize("value", ["https://bad host.example", "https://bücher.example",
+                                    "https://portal.example.com\\@evil.example/"])
+def test_review_rejects_ambiguous_portal_url(world, value):
+    with pytest.raises(CorsConfigError):
+        allowed_origins({"portalUrl": value})
+
+
+@pytest.mark.parametrize("value", ["https://bad host.example", "https://bücher.example", "https://portal|evil.example"])
+def test_review_rejects_non_origin_allowlist_values(world, value):
+    with pytest.raises(CorsConfigError):
+        allowed_origins({"cors": {"allowedOrigins": [value]}})
+
+
+def test_review_port_zero_and_ipv6_are_browser_serialized(world):
+    assert allowed_origins({"portalUrl": "https://portal.example.com:0/x"}) == ["https://portal.example.com:0"]
+    assert allowed_origins({"cors": {"allowedOrigins": ["https://portal.example.com:0"]}}) == ["https://portal.example.com:0"]
+    assert allowed_origins({"portalUrl": "https://[2001:0db8::1]/x"}) == ["https://[2001:db8::1]"]
+    with pytest.raises(CorsConfigError):
+        allowed_origins({"cors": {"allowedOrigins": ["https://[2001:0db8::1]"]}})
```

### F2 — full fix and service test diff

```diff
--- a/cmapi/src/cmapi/core/cors.py
+++ b/cmapi/src/cmapi/core/cors.py
@@ -15,6 +15,10 @@
 
 from typing import Any, Mapping
 from urllib.parse import urlsplit
+
+from starlette.datastructures import MutableHeaders
+from starlette.middleware.cors import CORSMiddleware
+from starlette.types import Message, Receive, Scope, Send
 
 METHODS = ["GET", "POST", "PATCH", "DELETE"]
 # Each makes the request one that needs a preflight, so no page of an origin that is not listed can send it at all.
@@ -91,3 +95,22 @@
     if problems:
         raise CorsConfigError("instance.yaml cors.allowedOrigins: " + "; ".join(problems))
     return list(dict.fromkeys(listed))
+
+
+class OriginVaryCORSMiddleware(CORSMiddleware):
+    """Keep allowed, denied, and originless responses in separate cache variants."""
+
+    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
+        if scope["type"] != "http":
+            await self.app(scope, receive, send)
+            return
+
+        async def vary_send(message: Message) -> None:
+            if message["type"] == "http.response.start":
+                headers = MutableHeaders(scope=message)
+                varied = {v.strip().lower() for v in headers.get("vary", "").split(",")}
+                if "origin" not in varied and "*" not in varied:
+                    headers.add_vary_header("Origin")
+            await send(message)
+
+        await super().__call__(scope, receive, vary_send)
--- a/cmapi/src/cmapi/main.py
+++ b/cmapi/src/cmapi/main.py
@@ -12,7 +12,6 @@
 import yaml
 from fastapi import Depends, FastAPI, Request
 from fastapi.exceptions import RequestValidationError
-from fastapi.middleware.cors import CORSMiddleware
 from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
 from fastapi.responses import HTMLResponse, JSONResponse, Response
 from fastapi.staticfiles import StaticFiles
@@ -21,6 +20,7 @@
 from cmapi.core.auth import caller_dependency, oauth2_scheme, unauthenticated_headers
 from cmapi.core.context import AppContext, build_context
 from cmapi.core.changelog import changelog_html
+from cmapi.core.cors import OriginVaryCORSMiddleware as CORSMiddleware
 from cmapi.core.cors import EXPOSED_HEADERS, MAX_AGE, METHODS, REQUEST_HEADERS, allowed_origins
 from cmapi.core.docs import PROBLEMS, build_openapi, check_documented, plugin_routers
 from cmapi.core.errors import Problem, type_base
--- a/cmapi/tests/service/test_cors.py
+++ b/cmapi/tests/service/test_cors.py
@@ -188,3 +188,15 @@
     before = counter._value.get()
     assert client.get("/api/v1/tiers", headers=auth(keys, "ola", **OLA)).status_code == 500
     assert counter._value.get() == before + 1
+
+
+# Reviewer 1 / F2: add to cmapi/tests/service/test_cors.py.
+@pytest.mark.parametrize("origin", [None, OTHER])
+def test_review_public_responses_always_vary_on_origin(world, origin):
+    client, *_ = world
+    first = client.get("/problems", headers={"Origin": origin} if origin else {})
+    assert first.status_code == 200
+    assert "origin" in {v.strip().lower() for v in first.headers.get("vary", "").split(",")}
+    assert ACAO not in first.headers
+    portal = client.get("/problems", headers={"Origin": PORTAL})
+    assert portal.headers[ACAO] == PORTAL
```

### F3 — full fix and service test diff

```diff
--- a/cmapi/src/cmapi/main.py
+++ b/cmapi/src/cmapi/main.py
@@ -2,6 +2,7 @@
 documented routers, refuses to start with an undocumented route, serves /docs, /redoc and the spec."""
 from __future__ import annotations
 
+import asyncio
 import hashlib
 import json
 import os
@@ -16,6 +17,8 @@
 from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
 from fastapi.responses import HTMLResponse, JSONResponse, Response
 from fastapi.staticfiles import StaticFiles
+from starlette.requests import ClientDisconnect
+from starlette.types import ASGIApp, Message, Receive, Scope, Send
 
 from cmapi import __version__
 from cmapi.core.auth import caller_dependency, oauth2_scheme, unauthenticated_headers
@@ -34,6 +37,54 @@
 STATIC = Path(os.environ.get("CMAPI_STATIC_DIR", "/opt/app-root/static"))
 
 
+class UnhandledToProblemMiddleware:
+    """Catch application failures without BaseHTTPMiddleware's task boundary."""
+
+    def __init__(self, app: ASGIApp, problem_response: Any):
+        self.app = app
+        self.problem_response = problem_response
+
+    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
+        if scope["type"] != "http":
+            await self.app(scope, receive, send)
+            return
+        started = False
+        disconnected = False
+
+        async def receive_checked() -> Message:
+            nonlocal disconnected
+            message = await receive()
+            if message["type"] == "http.disconnect":
+                disconnected = True
+            return message
+
+        async def send_checked(message: Message) -> None:
+            nonlocal started
+            if message["type"] == "http.response.start":
+                started = True
+            try:
+                await send(message)
+            except OSError as exc:
+                # ASGI servers signal a closed connection through send() this way.
+                raise ClientDisconnect() from exc
+
+        try:
+            await self.app(scope, receive_checked, send_checked)
+        except asyncio.CancelledError:
+            raise
+        except ClientDisconnect:
+            return
+        except Exception:
+            if disconnected:
+                return
+            request = Request(scope)
+            log.exception("unhandled", method=request.method, route=getattr(scope.get("route"), "path", "unmatched"))
+            if started:
+                raise  # A stream/background failure cannot replace a status already sent.
+            response = self.problem_response(Problem(500, "internal-error", PROBLEMS["internal-error"][1]))
+            await response(scope, receive, send)
+
+
 def create_app(s: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
     s = s or settings()
     configure_logging(s.log_level)
@@ -69,16 +120,7 @@
     def problem_response(p: Problem, headers: dict[str, str] | None = None) -> Response:
         return JSONResponse(p.body(problem_base), status_code=p.status, media_type="application/problem+json", headers=headers)
 
-    # The inner middleware: an exception that no handler takes becomes the problem internal-error here (#216). Starlette's own
-    # 500 is sent outside each middleware, so it has no CORS header and no X-Request-Id, and a browser on another origin shows a
-    # network error. The answer has no text of the exception; the log line has it, with the request ID that the answer carries.
-    @app.middleware("http")
-    async def unhandled_to_problem(request: Request, call_next: Any) -> Response:
-        try:
-            return await call_next(request)
-        except Exception:
-            log.exception("unhandled", method=request.method, route=getattr(request.scope.get("route"), "path", "unmatched"))
-            return problem_response(Problem(500, "internal-error", PROBLEMS["internal-error"][1]))
+    app.add_middleware(UnhandledToProblemMiddleware, problem_response=problem_response)
 
     instrument(app)
     # CORS is added after the request middleware, so it is the outer one: each answer that the application makes has the
--- a/cmapi/src/cmapi/core/observability.py
+++ b/cmapi/src/cmapi/core/observability.py
@@ -15,6 +15,10 @@
 import structlog
 from fastapi import FastAPI, Request
 from prometheus_client import Counter, Gauge, Histogram, start_http_server
+
+from starlette.datastructures import Headers, MutableHeaders
+from starlette.requests import ClientDisconnect
+from starlette.types import ASGIApp, Message, Receive, Scope, Send
 
 from cmapi import __version__
 
@@ -69,31 +73,50 @@
     start_http_server(port)
 
 
-def instrument(app: FastAPI) -> None:
-    @app.middleware("http")
-    async def metrics_and_request_id(request: Request, call_next: Any):
-        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
+class MetricsAndRequestIdMiddleware:
+    def __init__(self, app: ASGIApp):
+        self.app = app
+
+    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
+        if scope["type"] != "http":
+            await self.app(scope, receive, send)
+            return
+        request = Request(scope)
+        rid = Headers(scope=scope).get("x-request-id") or uuid.uuid4().hex[:16]
         structlog.contextvars.clear_contextvars()
         structlog.contextvars.bind_contextvars(request_id=rid)
         started = time.perf_counter()
         method = request.method if request.method in _METHODS else "OTHER"
+        status: int | None = None
 
-        def observe(status: int) -> str:
-            # Only declared routes become label values: a scanner's paths must not mint series.
-            route = getattr(request.scope.get("route"), "path", "unmatched")
-            HTTP_REQUESTS.labels(method, route, str(status)).inc()
-            HTTP_DURATION.labels(method, route).observe(time.perf_counter() - started)
-            return route
+        async def send_with_id(message: Message) -> None:
+            nonlocal status
+            if message["type"] == "http.response.start":
+                status = message["status"]
+                MutableHeaders(scope=message)["X-Request-Id"] = rid
+            await send(message)
 
         try:
-            response = await call_next(request)
+            await self.app(scope, receive, send_with_id)
+        except ClientDisconnect:
+            raise
         except Exception:
-            observe(500)                  # raised past this middleware: the error-rate alert must still count it
+            if status is None:
+                status = 500
             raise
-        route = observe(response.status_code)
-        response.headers["X-Request-Id"] = rid
-        caller = getattr(request.state, "caller", None)
-        log.info("http", method=request.method, route=route, status=response.status_code,
-                 caller_sub=getattr(caller, "sub", None), client=getattr(caller, "client_id", None),
-                 ms=round((time.perf_counter() - started) * 1000, 1))
-        return response
+        finally:
+            # Cancellation/disconnect before headers has no HTTP status to count.
+            # For a stream/background failure after headers, count the status actually sent.
+            if status is not None:
+                route = getattr(scope.get("route"), "path", "unmatched")
+                HTTP_REQUESTS.labels(method, route, str(status)).inc()
+                HTTP_DURATION.labels(method, route).observe(time.perf_counter() - started)
+                caller = getattr(request.state, "caller", None)
+                log.info("http", method=request.method, route=route, status=status,
+                         caller_sub=getattr(caller, "sub", None), client=getattr(caller, "client_id", None),
+                         ms=round((time.perf_counter() - started) * 1000, 1))
+            structlog.contextvars.clear_contextvars()
+
+
+def instrument(app: FastAPI) -> None:
+    app.add_middleware(MetricsAndRequestIdMiddleware)
--- a/cmapi/tests/service/test_cors.py
+++ b/cmapi/tests/service/test_cors.py
@@ -188,3 +188,71 @@
     before = counter._value.get()
     assert client.get("/api/v1/tiers", headers=auth(keys, "ola", **OLA)).status_code == 500
     assert counter._value.get() == before + 1
+
+
+# Reviewer 1 / F3: add to cmapi/tests/service/test_cors.py.
+async def _review_asgi_call(app, path, method="GET", incoming=None):
+    import asyncio
+    messages = iter(incoming or [{"type": "http.request", "body": b"", "more_body": False}])
+    sent = []
+
+    async def receive():
+        try:
+            return next(messages)
+        except StopIteration:
+            await asyncio.Event().wait()
+
+    async def send(message):
+        sent.append(message)
+
+    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
+             "method": method, "scheme": "https", "path": path, "raw_path": path.encode(),
+             "query_string": b"", "root_path": "", "headers": [(b"origin", PORTAL.encode())],
+             "server": ("api.example", 443), "client": ("127.0.0.1", 1234)}
+    await asyncio.wait_for(app(scope, receive, send), timeout=3)
+    return sent
+
+
+def test_review_disconnect_is_not_an_unhandled_500(world, monkeypatch):
+    import asyncio
+    from types import SimpleNamespace
+    from fastapi import Request
+    import cmapi.main as main
+    from cmapi.core.observability import HTTP_REQUESTS
+    client, *_ = world
+    events = []
+    monkeypatch.setattr(main, "log", SimpleNamespace(exception=lambda *a, **kw: events.append((a, kw))))
+
+    @client.app.post("/_review/upload", include_in_schema=False)
+    async def upload(request: Request):
+        await request.body()
+        return {"ok": True}
+
+    counter = HTTP_REQUESTS.labels("POST", "/_review/upload", "500")
+    before = counter._value.get()
+    sent = asyncio.run(_review_asgi_call(client.app, "/_review/upload", "POST", [
+        {"type": "http.request", "body": b"partial", "more_body": True}, {"type": "http.disconnect"}]))
+    assert not events
+    assert not any(m["type"] == "http.response.start" and m["status"] == 500 for m in sent)
+    assert counter._value.get() == before
+
+
+def test_review_cancellation_propagates_without_a_500(world, monkeypatch):
+    import asyncio
+    from types import SimpleNamespace
+    import cmapi.main as main
+    from cmapi.core.observability import HTTP_REQUESTS
+    client, *_ = world
+    events = []
+    monkeypatch.setattr(main, "log", SimpleNamespace(exception=lambda *a, **kw: events.append((a, kw))))
+
+    @client.app.get("/_review/cancel", include_in_schema=False)
+    async def cancel():
+        raise asyncio.CancelledError()
+
+    counter = HTTP_REQUESTS.labels("GET", "/_review/cancel", "500")
+    before = counter._value.get()
+    with pytest.raises(asyncio.CancelledError):
+        asyncio.run(_review_asgi_call(client.app, "/_review/cancel"))
+    assert not events
+    assert counter._value.get() == before
```


## Helm clarification (not proven as a runtime defect)

The fallback default matches C6 and is intentional. The values comment can be read as saying `instance.cors: []` is off, but an empty value is fed through Helm's `default dict`, so operators should use the exact nested setting. I did not run Helm or claim a failing runtime regression for this documentation-only recommendation. Make the behavior and off switch explicit:

```diff
--- a/deploy/helm/cmapi/values.yaml
+++ b/deploy/helm/cmapi/values.yaml
@@ -25 +25,3 @@
-  cors: {}                   # {allowedOrigins: [https://portal.example.com]} names the origins yourself; [] sends no CORS header
+  # {} uses the origin of portalUrl; it does not explicitly disable CORS.
+  # To disable CORS set instance.cors: {allowedOrigins: []}.
+  cors: {}                   # Or set {allowedOrigins: [https://portal.example.com]} explicitly.
```

## What was checked and found correct

- Wildcard and opaque-null origins are refused, including a wildcard inside an otherwise valid list (`core/cors.py:48-51,90-92`).
- Exact origin membership has no regex/prefix/suffix matching (`main.py:88-89`; Starlette `cors.py:95-102`).
- Listed simple responses and both successful/denied-origin preflight responses receive `Vary: Origin` (`cors.py:49,170-172` in Starlette).
- No configured response permits credentialed browser reads or wildcard ACAO (`main.py:88-89`; Starlette `cors.py:34-42,61-62`).
- Authentication uses explicit bearer Authorization and no cookie or ambient identity (`core/auth.py:189-206`).
- All state-changing routers receive the bearer dependency (`main.py:117-119`); no successful safelisted unauthenticated write was found.
- Explicit empty allowedOrigins disables the factory's CORS middleware (`core/cors.py:87-93`; `main.py:87`).
- Ordinary Problem/validation/HTTP/TierError/ValueError/router-404/429 responses remain handled and receive listed-origin CORS headers (`main.py:92-119`).
- Ordinary unhandled 500 bodies contain neither exception text nor class; configured logs contain the traceback and matching request ID (`main.py:69-81`; `observability.py:55-61,75-77`).
- A normal caught 500 increments the status=500 request counter once, not twice (`observability.py:88-94`).
- Normal docs and mounted static responses pass through CORS (`main.py:164-167,198-210`).
- External task cancellation already propagates without an unhandled event or replacement response; post-start failures cannot replace sent headers/status.
- Exposed metadata headers and explicit request-header permission do not grant new application authorization (`core/cors.py:21-25`).

## What I ran

Working directory throughout: this export. Python is **3.14**; requested framework versions are **FastAPI 0.115.6 and Starlette 0.41.3**. Exact installed dependencies are saved in [requirements.txt](review_scratch/requirements.txt); this is an isolated minimal review environment, not the full application dependency set.

```sh
python3 -m venv .review-venv
.review-venv/bin/pip install fastapi==0.115.6 starlette==0.41.3 httpx pytest prometheus-client structlog pyyaml
.review-venv/bin/pip install 'PyJWT[crypto]==2.10.1'
.review-venv/bin/pip install --no-deps PyJWT==2.10.1
.review-venv/bin/python review_scratch/probe.py > review_scratch/probe.out
.review-venv/bin/python review_scratch/make_fixes.py
.review-venv/bin/python review_scratch/add_service_patches.py
.review-venv/bin/pytest -q review_scratch/test_defects.py
REVIEW_FIXED=1 .review-venv/bin/pytest -q review_scratch/test_defects.py
.review-venv/bin/pytest -q review_scratch/test_controls.py
REVIEW_FIXED=1 .review-venv/bin/pytest -q review_scratch/test_controls.py
patch --dry-run -p1 -i review_scratch/combined.patch
.review-venv/bin/pip freeze > review_scratch/requirements.txt
```

The no-deps PyJWT command installed the small JWT package while the optional crypto wheel built. Both completed. In addition, I ran local Node WHATWG URL probes, an exact-membership probe using a regex-like literal, and Python `ast.parse` on all proposed Python files. Shell reads inspected the requested sources, installed Starlette CORS/application/base/error/exception handling code, relevant route definitions, fixtures, export marker and change.diff. No service test was collected or executed.

| Run | Result | Saved output |
|---|---|---|
| Defect regressions against export | **12 failed**, all on assertions showing F1/F2/F3 | [before.txt](review_scratch/before.txt) |
| Same defect regressions with proposed merged sources | **12 passed** | [after.txt](review_scratch/after.txt) |
| Control checks against export | **47 passed** | [controls_before.txt](review_scratch/controls_before.txt) |
| Same controls with proposed merged sources | **47 passed** | [controls_after.txt](review_scratch/controls_after.txt) |
| Combined diff applicability | Clean dry run, all four target files | terminal output |
| Proposed Python files/service additions | Syntax parsed successfully; not imported/collected as service tests | terminal output |

The warnings are framework/AnyIO/Python deprecations in the pinned old framework running on Python 3.14. Standalone checks do not establish database-backed end-to-end behavior or deployed-browser behavior. No finding is based solely on a passing “shows current behavior” test: the 12 defect regressions assert the corrected behavior and demonstrably fail on the export. The scratch authentication check uses the actual OAuth2/caller dependency on a miniature bodyless decision route; it does not execute the database-backed cancel handler. The three proven findings all have both a service regression in their diff and an executed standalone counterpart. The Helm documentation recommendation is separately marked not proven as a runtime defect.

## Primary references used for browser behavior

- The [Fetch standard's CORS/HTTP-cache discussion](https://fetch.spec.whatwg.org/#cors-protocol-and-http-caches) supports varying dynamic-origin responses; its [preflight algorithm](https://fetch.spec.whatwg.org/#cors-preflight-fetch) permits user-agent max-age clamping.
- The [URL standard](https://url.spec.whatwg.org/#concept-url-origin) defines origin/host serialization; Node's local WHATWG implementation independently reproduced the specific parsing discrepancies in F1.
- [WebKit preflight cache source](https://raw.githubusercontent.com/WebKit/WebKit/main/Source/WebCore/loader/CrossOriginPreflightResultCache.cpp) sets the maximum to 600 seconds; [Chromium preflight result source](https://raw.githubusercontent.com/chromium/chromium/main/services/network/cors/preflight_result.cc) sets it to two hours. Thus 600 is not above either cap. The code's Firefox cap comment was not needed to reach that conclusion; the protocol imposes no universal browser ceiling.

Excluded as requested: realm redirect URIs (#205), portal implementation, Keycloak webOrigins, and revisiting the architectural CORS-versus-one-origin decision. No container, cluster, network service or database was started/opened.
