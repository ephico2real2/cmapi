# Security review: CORS on the API, and the catch-all 500 (cmapi issues #206 and #216)

You are reviewer 1. You work in this folder only: it is an export of the commit in `EXPORT-HEAD`, not a repository. `change.diff` is the whole change against the base `418e934`. Write each finding to `REPORT.md` in this folder as you go. Do not start a container, a cluster or a network service, and open no database: `cmapi/tests/service` needs a shared PostgreSQL that another session uses, so do not run it. You can test `cmapi/src/cmapi/core/cors.py` directly, and you can build a small FastAPI/Starlette app in a scratch file with the same middleware order as `create_app` and call it with Starlette's `TestClient` (install fastapi==0.115.6, starlette==0.41.3, httpx and pytest in a venv inside this folder). Say what you ran.

## The files to read, in full
- `cmapi/src/cmapi/core/cors.py`
- `cmapi/src/cmapi/main.py`, `create_app` (the middleware order: `unhandled_to_problem`, then `instrument(app)`, then `CORSMiddleware`)
- `cmapi/src/cmapi/core/observability.py`, `instrument`
- `cmapi/src/cmapi/core/auth.py` (how a caller is authenticated: is any cookie or ambient credential read?)
- Starlette 0.41.3 `starlette/middleware/cors.py` and `starlette/applications.py:build_middleware_stack` (from the installed package)
- `cmapi/tests/service/test_cors.py`
- `docs/15-keycloak-integration.md`, section "The portal's origin and the API"
- `deploy/helm/cmapi/templates/config.yaml`, `deploy/manifests/environments/crc/20-config.yaml` (instance.yaml)

## The claims. Confirm or refute each one, with the file and the line.
- C1. `cors.py:allowed_origins` returns only exact origins of the form `scheme://host[:port]`. No input from `instance.yaml` can make the API answer `Access-Control-Allow-Origin` for an origin that is not in the returned list: try `*`, `null`, a list with `"*"` inside, a regex-like value, an origin with a trailing dot, an IDN or punycode host, upper case, a default port, userinfo, an IPv6 host, a value with whitespace or a newline, a non-string YAML value (a number, a mapping, `true`), and `portalUrl` values such as `https://portal.example.com@evil.example/`, `https://evil.example#https://portal.example.com`, `//evil.example`, `https://portal.example.com:443/x`.
- C2. Starlette's `CORSMiddleware` as configured in `main.py` compares the request's `Origin` with the list by exact string equality (no regex, no prefix or suffix match), never sends `Access-Control-Allow-Credentials`, never sends `*`, and adds `Vary: Origin` to each answer whose content depends on the origin. Say if a simple (not preflighted) response to a listed origin lacks `Vary: Origin`, and what a shared cache could then do.
- C3. With no cookie and no ambient credential read by the API (confirm in `auth.py`), a page of an origin that is not listed can make no state-changing call succeed: each write needs `Authorization` (a preflight) and `Idempotency-Key`. Name a route that changes state and that a CORS-safelisted request can reach (a `POST` with `Content-Type: text/plain` and no `Authorization`), if one exists.
- C4. The middleware order in `create_app` makes `CORSMiddleware` the outer one of the three, so each answer that the application makes has the CORS headers for a listed origin: a `Problem`, a `RequestValidationError`, a 404 of the router, a 429, and the 500 of `unhandled_to_problem`. Name an answer that still has no CORS header (for example Starlette's `ServerErrorMiddleware` when the catch-all itself fails, a streaming response that fails after the first byte, `StaticFiles`, `/docs`).
- C5. `unhandled_to_problem`: the answer never has the text or the type of the exception, the log line has the traceback and the request ID, the metric `cmapi_http_requests_total{status="500"}` counts the request exactly one time (see `observability.py`), and `HTTPException`, `Problem`, `RequestValidationError`, `TierError` and `ValueError` are still handled by their own handlers and not by the catch-all. Check `BaseHTTPMiddleware`'s behaviour for an exception raised after the response has started, for `asyncio.CancelledError` and client disconnects (they must not be logged as `unhandled` and turned into a 500), and for background tasks.
- C6. `allowed_origins` falls back to the origin of `portalUrl` only when `cors.allowedOrigins` is absent. A deployment that sets `cors: {allowedOrigins: []}` sends no CORS header at all. The Helm template renders `cors: {}` by default, which is the fallback and not "off": say if that default can surprise an operator, with the fix if so.
- C7. The exposed response headers (`ETag`, `Location`, `Retry-After`, `WWW-Authenticate`, `X-Request-Id`) and the allowed request headers leak nothing that a page of the portal's origin should not read, and `Access-Control-Max-Age: 600` is not above a browser's limit.

## For each finding
Give: the claim it breaks, the file and line, why it is wrong, the full code of the fix (a unified diff against this export), and a test that fails before the fix and passes after it: in the form of `cmapi/tests/service/test_cors.py` (it uses the `world` fixture; you cannot run it, so also give a standalone scratch test that you did run and that shows the same defect). A finding with no failing test is listed as "not proven". Also list what you checked and found correct, one line each.

## Not in this review
The redirect URIs of the realm (#205), the portal's code, Keycloak's own CORS (`webOrigins`), and the choice between CORS and one origin (docs/15 has it).
