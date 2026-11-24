## 1.10.0 (October 24, 2026)

#### Changed

* Compare multidicts such as `FormData` and `QueryParams` by key while keeping the order of values under a repeated key, so `FormData` with repeated uploads no longer raises `TypeError`. `QueryParams("a=1&a=2")` and `QueryParams("a=2&a=1")` are no longer equal [#3619](https://github.com/Kludex/starlette/pull/3619).
* Build URL-encoded form fields in the parser callbacks, lowering memory and CPU usage for forms with many fields [#3724](https://github.com/Kludex/starlette/pull/3724).
* Compare `Match` members by identity during routing [#3665](https://github.com/Kludex/starlette/pull/3665) and [#3722](https://github.com/Kludex/starlette/pull/3722).

#### Deprecated

* Deprecate `starlette.formparsers.FormMessage`, which is no longer used [#3724](https://github.com/Kludex/starlette/pull/3724).

#### Fixed

* Parse the last URL-encoded form field when the request stream ends without an empty chunk [#3599](https://github.com/Kludex/starlette/pull/3599).
* Keep path parameter values that look like another placeholder in `url_path_for()` [#3725](https://github.com/Kludex/starlette/pull/3725).
* Default omitted `http.response.start` headers in `BaseHTTPMiddleware`, `GZipMiddleware` and `SessionMiddleware` instead of raising `KeyError` [#3721](https://github.com/Kludex/starlette/pull/3721).
* Clear the traceback of handled exceptions, so reused exception instances no longer keep per-request objects alive [#3205](https://github.com/Kludex/starlette/pull/3205).
* Strip only one pair of matching outer quotes from `Config` env file values [#3720](https://github.com/Kludex/starlette/pull/3720).
* Strip `root_path` from `PATH_INFO` only at a path segment boundary in `WSGIMiddleware` [#3718](https://github.com/Kludex/starlette/pull/3718).
* Report NaN and infinity correctly in `FloatConvertor.to_string()` [#3716](https://github.com/Kludex/starlette/pull/3716).
* Ignore `Range` on requests other than `GET` and `HEAD` in `FileResponse` [#3679](https://github.com/Kludex/starlette/pull/3679).

## 1.9.0 (October 18, 2026)

#### Changed

* Stream `TestClient` response bodies, so `client.stream()` returns before the application finishes. Closing an unfinished streamed response now cancels the application [#3491](https://github.com/Kludex/starlette/pull/3491).

#### Fixed

* Percent-encode `?`, `#`, `\` and a leading `//` in the request path when building `request.url`, and `\` and a leading `//` in `url_path_for` [#3671](https://github.com/Kludex/starlette/pull/3671).
* Use the byte length for `Content-Length` when the response body is a typed or multidimensional `memoryview` [#3622](https://github.com/Kludex/starlette/pull/3622).
* Include `HEAD` in the `Allow` header of `HTTPEndpoint` 405 responses when `GET` is defined [#3585](https://github.com/Kludex/starlette/pull/3585).
* Match host names case-insensitively in `Host` routing and `TrustedHostMiddleware` [#3542](https://github.com/Kludex/starlette/pull/3542).
* Preserve every existing `Vary` header in `MutableHeaders.add_vary_header()`, used by `GZipMiddleware` and `SessionMiddleware` [#3675](https://github.com/Kludex/starlette/pull/3675).

## 1.8.0 (October 13, 2026)

This release drops Python 3.10 support and adds HTTP 103 Early Hints.

#### Added

* Add `Request.send_early_hints()` for HTTP 103 Early Hints through the ASGI `http.response.early_hint` extension [#3435](https://github.com/Kludex/starlette/pull/3435).

#### Changed

* Require Python 3.11 or later, dropping support for Python 3.10 [#3592](https://github.com/Kludex/starlette/pull/3592).
* Exclude native gRPC media types (`application/grpc` and `application/grpc+...`) from `GZipMiddleware` compression by default [#3565](https://github.com/Kludex/starlette/pull/3565).
* Send `http.response.start` immediately in `GZipMiddleware` for responses with an existing `Content-Encoding`, status `206`, or an excluded content type, instead of waiting for the first body chunk [#3631](https://github.com/Kludex/starlette/pull/3631).
* Resolve the multipart charset once per request instead of once per field [#3618](https://github.com/Kludex/starlette/pull/3618).

#### Fixed

* Preserve response trailers through `GZipMiddleware` [#3565](https://github.com/Kludex/starlette/pull/3565).
* Stop `FileResponse` transfers when the client disconnects [#3523](https://github.com/Kludex/starlette/pull/3523).
* Stop multipart range responses when the file ends before a range is complete, instead of looping forever [#3583](https://github.com/Kludex/starlette/pull/3583).
* Ignore `Range` when `If-Range` contains a weak ETag [#3567](https://github.com/Kludex/starlette/pull/3567).
* Include `Allow: GET, HEAD` in `StaticFiles` `405` responses [#3640](https://github.com/Kludex/starlette/pull/3640).
* Close `Request.stream()` generators deterministically, avoiding "Exception ignored" errors with stacked `BaseHTTPMiddleware` [#3628](https://github.com/Kludex/starlette/pull/3628).
* Add `Vary: Cookie` when `Session.pop()` removes an existing key [#3186](https://github.com/Kludex/starlette/pull/3186).
* Emit `Max-Age=0` on the session cookie when `SessionMiddleware` uses `max_age=0` [#3651](https://github.com/Kludex/starlette/pull/3651).
* Bracket IPv6 hostnames in `URL.replace()` [#3617](https://github.com/Kludex/starlette/pull/3617).

## 1.7.0 (September 23, 2026)

This release adds experimental OpenTelemetry tracing and requires AnyIO 4.

!!! warning "OpenTelemetryMiddleware is experimental"
    Its API and emitted telemetry may change in minor releases without a deprecation period
    [#3574](https://github.com/Kludex/starlette/pull/3574).

#### Added

* Add experimental `OpenTelemetryMiddleware` for HTTP server spans, with URL exclusions and custom tracer providers [#3438](https://github.com/Kludex/starlette/pull/3438), [#3463](https://github.com/Kludex/starlette/pull/3463), and [#3520](https://github.com/Kludex/starlette/pull/3520).
* Expose the matched route through `scope["route"]` [#3438](https://github.com/Kludex/starlette/pull/3438).
* Support the `QUERY` HTTP method in `HTTPEndpoint`, CORS, and OpenAPI 3.2 schema generation [#3489](https://github.com/Kludex/starlette/pull/3489).
* Capture HTTP response trailers in `TestClient` and expose them through `response.extensions["http.response.trailers"]` [#3563](https://github.com/Kludex/starlette/pull/3563).
* Support partitioned cookies in `SessionMiddleware` [#3510](https://github.com/Kludex/starlette/pull/3510).
* Add `partitioned` to `Response.delete_cookie()` on Python 3.14 and later [#3376](https://github.com/Kludex/starlette/pull/3376).
* Support IPv6 hosts in `TrustedHostMiddleware` and `TestClient` [#3471](https://github.com/Kludex/starlette/pull/3471).
* Support Python 3.15 [#3508](https://github.com/Kludex/starlette/pull/3508).

#### Changed

* Require `anyio>=4.0.0,<5`, dropping support for AnyIO 3 [#3512](https://github.com/Kludex/starlette/pull/3512).
* Raise `WebSocketDisconnected`, a `RuntimeError` subclass, for disconnected WebSocket operations [#2767](https://github.com/Kludex/starlette/pull/2767).
* Accept `Collection[str]` in `CORSMiddleware` configuration annotations, including sets and frozensets [#3518](https://github.com/Kludex/starlette/pull/3518).

#### Fixed

* Run background tasks only after the response is sent when using `BaseHTTPMiddleware` [#3476](https://github.com/Kludex/starlette/pull/3476).
* Return `400` for invalid multipart parser input [#3492](https://github.com/Kludex/starlette/pull/3492).
* Include `Vary: Origin` on all normal CORS responses and vary preflight responses by all request headers that affect them [#3516](https://github.com/Kludex/starlette/pull/3516) and [#3517](https://github.com/Kludex/starlette/pull/3517).
* Handle malformed `Host` headers and IPv6 authorities consistently across URL construction, host routing, and redirect middleware [#3472](https://github.com/Kludex/starlette/pull/3472).
* Ignore `Range` headers when `FileResponse` has a status other than `200`, preserving its status and full body [#3568](https://github.com/Kludex/starlette/pull/3568).
* Handle standalone `If-None-Match: *` in `StaticFiles` [#3201](https://github.com/Kludex/starlette/pull/3201).
* Reject WebSocket requests to `StaticFiles` without raising an assertion error [#3532](https://github.com/Kludex/starlette/pull/3532).
* Persist session mutations made with `popitem()` and `|=` [#3436](https://github.com/Kludex/starlette/pull/3436).
* Handle empty and absent payloads in `WebSocketEndpoint.decode()` [#3372](https://github.com/Kludex/starlette/pull/3372).
* Implement `identity` on `SimpleUser` and `UnauthenticatedUser` [#3271](https://github.com/Kludex/starlette/pull/3271).
* Allow `HTTPException` to use non-standard status codes without an explicit `detail` [#3545](https://github.com/Kludex/starlette/pull/3545).
* Avoid deprecated AnyIO imports in `TestClient` and add explicit imports in `WSGIMiddleware` for AnyIO 4.15 compatibility [#3498](https://github.com/Kludex/starlette/pull/3498) and [#3501](https://github.com/Kludex/starlette/pull/3501).
* Offload debug traceback rendering to a worker thread in `ServerErrorMiddleware` [#2858](https://github.com/Kludex/starlette/pull/2858).

## 1.6.0 (August 8, 2026)

#### Added

* Add `max_body_size` to `Starlette` and route classes [#3431](https://github.com/encode/starlette/pull/3431).
* Expose `http.response.debug` information via response extensions [#3130](https://github.com/encode/starlette/pull/3130).

## 1.5.1 (August 8, 2026)

#### Fixed

* Reject inverted single-byte ranges in `FileResponse` [#3389](https://github.com/encode/starlette/pull/3389).
* Limit `FileResponse` to 100 ranges [#3430](https://github.com/encode/starlette/pull/3430).

## 1.5.0 (August 8, 2026)

#### Added

* Add `exclude_content_types` parameter to `GZipMiddleware` [#3418](https://github.com/encode/starlette/pull/3418).

#### Changed

* Expand default excluded content types in `GZipMiddleware` [#3421](https://github.com/encode/starlette/pull/3421).

#### Fixed

* Flush GZip output for each streamed chunk [#3419](https://github.com/encode/starlette/pull/3419).
* Skip compression of partial responses in `GZipMiddleware` [#3420](https://github.com/encode/starlette/pull/3420).

## 1.4.1 (August 5, 2026)

#### Fixed

* Default `thread_minimum_size` to 128 KiB in `GZipResponder`, keeping it usable without the new keyword argument [#3415](https://github.com/encode/starlette/pull/3415).

## 1.4.0 (August 5, 2026)

#### Added

* Offload large GZip compression to a worker thread, keeping the event loop responsive. `GZipMiddleware` accepts a new `thread_minimum_size` parameter (default 128 KiB) controlling the minimum body chunk size compressed in a thread [#3410](https://github.com/encode/starlette/pull/3410).

#### Changed

* Use `zlib.compressobj` instead of `GzipFile` in `GZipMiddleware`, reducing memory usage during compression [#3411](https://github.com/encode/starlette/pull/3411).
* Lazily allocate `GZipMiddleware` compression resources, avoiding compressor allocation for responses that are never compressed [#3407](https://github.com/encode/starlette/pull/3407).

## 1.3.1 (June 12, 2026)

#### Fixed

* Enforce `max_fields` and `max_part_size` in `FormParser` [#3329](https://github.com/encode/starlette/pull/3329).
* Enforce `FormParser` limits in parser callbacks [#3331](https://github.com/encode/starlette/pull/3331).

## 1.3.0 (June 11, 2026)

#### Added

* Add `httpx2` to the `full` extra [#3323](https://github.com/encode/starlette/pull/3323).
* Annotate the `URLPath` `protocol` parameter with `Literal` [#3285](https://github.com/encode/starlette/pull/3285).

#### Fixed

* Build `request.url` from structured components [#3326](https://github.com/encode/starlette/pull/3326).
* Clamp oversized suffix ranges in `FileResponse` [#3307](https://github.com/encode/starlette/pull/3307).
* Catch `OSError` alongside `MultiPartException` when closing temp files [#3191](https://github.com/encode/starlette/pull/3191).
* Avoid collapsing exception groups raised from user code [#2830](https://github.com/encode/starlette/pull/2830).
* Use `removeprefix` to strip the weak `ETag` indicator in `is_not_modified` [#3193](https://github.com/encode/starlette/pull/3193).
* Fix `IndexError` in `URL.replace()` on a URL with no authority [#3317](https://github.com/encode/starlette/pull/3317).
* Adjust `testclient` typing and warnings [#3322](https://github.com/encode/starlette/pull/3322).

## 1.2.1 (May 31, 2026)

#### Fixed

* Use `httpx2` for type checking in the `testclient` module [#3304](https://github.com/encode/starlette/pull/3304).
* Add assert error for `requires()` when the request parameter is not a `Request` type [#3298](https://github.com/encode/starlette/pull/3298).

## 1.2.0 (May 28, 2026)

#### Added

* Support httpx2 in the test client [#3291](https://github.com/encode/starlette/pull/3291).

## 1.1.0 (May 23, 2026)

#### Added

* Use `"application/octet-stream"` as the `FileResponse` media type fallback [#3283](https://github.com/encode/starlette/pull/3283).

#### Fixed

* Only dispatch standard HTTP verbs in `HTTPEndpoint` [#3286](https://github.com/encode/starlette/pull/3286).
* Reject absolute paths in `StaticFiles.lookup_path` [#3287](https://github.com/encode/starlette/pull/3287).

## 1.0.1 (May 21, 2026)

#### Fixed

* Ignore malformed `Host` header when constructing `request.url` [#3279](https://github.com/encode/starlette/pull/3279).

## 1.0.0 (March 22, 2026)

Starlette 1.0 is here!

After nearly eight years since its creation, Starlette has reached its first stable release.
Thank you to everyone who tested the release candidate and reported issues.

You can read more on the [blog post](https://marcelotryle.com/blog/2026/03/22/starlette-10-is-here/).

#### Added

* Track session access and modification in `SessionMiddleware` [#3166](https://github.com/encode/starlette/pull/3166).

#### Fixed

* Handle websocket denial responses in `StreamingResponse` and `FileResponse` [#3189](https://github.com/encode/starlette/pull/3189).
* Use `bytearray` for field accumulation in `FormParser` [#3179](https://github.com/encode/starlette/pull/3179).
* Move `parser.finalize()` inside try/except in `MultiPartParser.parse()` [#3153](https://github.com/encode/starlette/pull/3153).

## 1.0.0rc1 (February 23, 2026)

We're ready! I'm thrilled to announce the first release candidate for Starlette 1.0.

Starlette was created in June 2018 by Tom Christie, and has been on ZeroVer for years. Today, it's downloaded
almost [10 million times a day](https://pypistats.org/packages/starlette), serves as the foundation for FastAPI,
and has inspired many other frameworks. In the age of AI, Starlette continues to play an important role as a
dependency of the Python MCP SDK.

This release focuses on removing deprecated features that were marked for removal in 1.0.0, along with some
last minute bug fixes. It's a release candidate, so we can gather feedback from the community before the final
1.0.0 release soon.

A huge thank you to all the contributors who have helped make Starlette what it is today.
In particular, I'd like to recognize:

* [Kim Christie](https://github.com/lovelydinosaur) - The original creator of Starlette, Uvicorn, and MkDocs, and the
  current maintainer of HTTPX. Kim's work helped lay the foundation for the modern async Python ecosystem.
* [Adrian Garcia Badaracco](https://github.com/adriangb) - One of the smartest people I know, whom I have the pleasure of working with at Pydantic.
* [Thomas Grainger](https://github.com/graingert) - My async teacher, always ready to help with questions.
* [Alex Grönholm](https://github.com/agronholm) - Another async mentor, always prompt to help with questions.
* [Florimond Manca](https://github.com/florimondmanca) - Always present in the early days of both Starlette and Uvicorn, and helped a lot in the ecosystem.
* [Amin Alaee](https://github.com/aminalaee) - Contributed a lot with file-related PRs.
* [Sebastián Ramírez](https://github.com/tiangolo) - Maintains FastAPI upstream, and always in contact to help with upstream issues.
* [Alex Oleshkevich](https://github.com/alex-oleshkevich) - Helped a lot on templates and many discussions.
* [abersheeran](https://github.com/abersheeran) - My go-to person when I need help on many subjects.

I'd also like to thank my sponsors for their support. A special thanks to
[@tiangolo](https://github.com/tiangolo), [@huggingface](https://github.com/huggingface),
and [@elevenlabs](https://github.com/elevenlabs) for their generous sponsorship, and to all my other sponsors:

[@roboflow](https://github.com/roboflow),
[@ogabrielluiz](https://github.com/ogabrielluiz),
[@SaboniAmine](https://github.com/SaboniAmine),
[@russbiggs](https://github.com/russbiggs),
[@BryceBeagle](https://github.com/BryceBeagle),
[@chdsbd](https://github.com/chdsbd),
[@TheR1D](https://github.com/TheR1D),
[@ddanier](https://github.com/ddanier),
[@larsyngvelundin](https://github.com/larsyngvelundin),
[@jpizquierdo](https://github.com/jpizquierdo),
[@alixlahuec](https://github.com/alixlahuec),
[@nathanchapman](https://github.com/nathanchapman),
[@devid8642](https://github.com/devid8642),
[@comet-ml](https://github.com/comet-ml),
[@Evil0ctal](https://github.com/Evil0ctal),
[@msehnout](https://github.com/msehnout),
and [@codingjoe](https://github.com/codingjoe).

#### Removed

* Remove `on_startup` and `on_shutdown` parameters from `Starlette` and `Router`.
  Use the `lifespan` parameter instead [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `on_event()` decorator from `Starlette` and `Router`.
  Use the `lifespan` parameter instead [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `add_event_handler()` method from `Starlette` and `Router`.
  Use the `lifespan` parameter instead [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `startup()` and `shutdown()` methods from `Router`
  [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `@app.route()` decorator from `Starlette` and `Router`.
  Use `Route` in the `routes` parameter instead [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `@app.websocket_route()` decorator from `Starlette` and `Router`.
  Use `WebSocketRoute` in the `routes` parameter instead [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `@app.exception_handler()` decorator from `Starlette`.
  Use `exception_handlers` parameter instead [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `@app.middleware()` decorator from `Starlette`.
  Use `middleware` parameter instead [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `iscoroutinefunction_or_partial()` from `starlette.routing` [#3117](https://github.com/encode/starlette/pull/3117).
* Remove `**env_options` parameter from `Jinja2Templates`.
  Use a preconfigured `jinja2.Environment` via the `env` parameter instead [#3118](https://github.com/encode/starlette/pull/3118).
* Remove deprecated `TemplateResponse(name, context)` signature from `Jinja2Templates`.
  Use `TemplateResponse(request, name, ...)` instead [#3118](https://github.com/encode/starlette/pull/3118).
* Remove deprecated `method` parameter from `FileResponse` [#3147](https://github.com/encode/starlette/pull/3147).

#### Added

* Add state generic to `WebSocket` [#3132](https://github.com/encode/starlette/pull/3132).

#### Fixed

* Include `bytes` unit in `Content-Range` header on 416 responses.
* Handle null bytes in `StaticFiles` path [#3139](https://github.com/encode/starlette/pull/3139).
* Use sort-based merge for `Range` header parsing [#3138](https://github.com/encode/starlette/pull/3138).
* Set `Content-Type` instead of `Content-Range` on multi-range responses [#3142](https://github.com/encode/starlette/pull/3142).
* Use CRLF line endings in multipart byterange boundaries [#3143](https://github.com/encode/starlette/pull/3143).
* Avoid mutating `FileResponse` headers on range requests [#3144](https://github.com/encode/starlette/pull/3144).
* Return explicit origin in CORS response when credentials are allowed [#3137](https://github.com/encode/starlette/pull/3137).
* Enable `autoescape` by default in `Jinja2Templates` [#3148](https://github.com/encode/starlette/pull/3148).

#### Changed

* `jinja2` must now be installed to import `Jinja2Templates`. Previously it would only
  fail when instantiating the class [#3118](https://github.com/encode/starlette/pull/3118).

## 0.52.1 (January 18, 2026)

#### Fixed

* Only use `typing_extensions` in older Python versions [#3109](https://github.com/Kludex/starlette/pull/3109).

## 0.52.0 (January 18, 2026)

In this release, `State` can be accessed using dictionary-style syntax for improved type
safety ([#3036](https://github.com/Kludex/starlette/pull/3036)).

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict

import httpx

from starlette.applications import Starlette
from starlette.requests import Request


class State(TypedDict):
    http_client: httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[State]:
    async with httpx.AsyncClient() as client:
        yield {"http_client": client}


async def homepage(request: Request[State]):
    client = request.state["http_client"]
    # If you run the below line with mypy or pyright, it will reveal the correct type.
    reveal_type(client)  # Revealed type is 'httpx.AsyncClient'
```

See [Accessing State](lifespan.md#accessing-state) for more details.

## 0.51.0 (January 10, 2026)

#### Added

* Add `allow_private_network` in `CORSMiddleware` [#3065](https://github.com/Kludex/starlette/pull/3065).

#### Changed

* Increase warning stacklevel on `DeprecationWarning` for wsgi module [#3082](https://github.com/Kludex/starlette/pull/3082).

## 0.50.0 (November 1, 2025)

#### Removed

* Drop Python 3.9 support [#3061](https://github.com/Kludex/starlette/pull/3061).

## 0.49.3 (November 1, 2025)

This is the last release that supports Python 3.9, which will be dropped in the next minor release.

#### Fixed

* Relax strictness on `Middleware` type [#3059](https://github.com/Kludex/starlette/pull/3059).

## 0.49.2 (November 1, 2025)

#### Fixed

* Ignore `if-modified-since` header if `if-none-match` is present in `StaticFiles` [#3044](https://github.com/Kludex/starlette/pull/3044).

## 0.49.1 (October 28, 2025)

This release fixes a security vulnerability in the parsing logic of the `Range` header in `FileResponse`.

You can view the full security advisory: [GHSA-7f5h-v6xp-fcq8](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8)

#### Fixed

* Optimize the HTTP ranges parsing logic [4ea6e22b489ec388d6004cfbca52dd5b147127c5](https://github.com/Kludex/starlette/commit/4ea6e22b489ec388d6004cfbca52dd5b147127c5)

## 0.49.0 (October 28, 2025)

#### Added

* Add `encoding` parameter to `Config` class [#2996](https://github.com/Kludex/starlette/pull/2996).
* Support multiple cookie headers in `Request.cookies` [#3029](https://github.com/Kludex/starlette/pull/3029).
* Use `Literal` type for `WebSocketEndpoint` encoding values [#3027](https://github.com/Kludex/starlette/pull/3027).

#### Changed

* Do not pollute exception context in `Middleware` when using `BaseHTTPMiddleware` [#2976](https://github.com/Kludex/starlette/pull/2976).

## 0.48.0 (September 13, 2025)

#### Added

* Add official Python 3.14 support [#3013](https://github.com/Kludex/starlette/pull/3013).

#### Changed

* Implement [RFC9110](https://www.rfc-editor.org/rfc/rfc9110) http status names [#2939](https://github.com/Kludex/starlette/pull/2939).

## 0.47.3 (August 24, 2025)

#### Fixed

* Use `asyncio.iscoroutinefunction` for Python 3.12 and older [#2984](https://github.com/Kludex/starlette/pull/2984).

## 0.47.2 (July 20, 2025)

#### Fixed

* Make `UploadFile` check for future rollover [#2962](https://github.com/Kludex/starlette/pull/2962).

## 0.47.1 (June 21, 2025)

#### Fixed

* Use `Self` in `TestClient.__enter__` [#2951](https://github.com/Kludex/starlette/pull/2951).
* Allow async exception handlers to type-check [#2949](https://github.com/Kludex/starlette/pull/2949).

## 0.47.0 (May 29, 2025)

#### Added

* Add support for ASGI `pathsend` extension [#2671](https://github.com/Kludex/starlette/pull/2671).
* Add `partitioned` attribute to `Response.set_cookie` [#2501](https://github.com/Kludex/starlette/pull/2501).

#### Changed

* Change `methods` parameter type from `list[str]` to `Collection[str]`
  [#2903](https://github.com/Kludex/starlette/pull/2903).
* Replace `import typing` by `from typing import ...` in the whole codebase
  [#2867](https://github.com/Kludex/starlette/pull/2867).

#### Fixed

* Mark `ExceptionMiddleware.http_exception` as async to prevent thread creation
  [#2922](https://github.com/Kludex/starlette/pull/2922).

## 0.46.2 (April 13, 2025)

#### Fixed

* Prevents reraising of exception from BaseHttpMiddleware [#2911](https://github.com/Kludex/starlette/pull/2911).
* Use correct index on backwards compatible logic in `TemplateResponse` [#2909](https://github.com/Kludex/starlette/pull/2909).

## 0.46.1 (March 8, 2025)

#### Fixed

* Allow relative directory path when `follow_symlinks=True` [#2896](https://github.com/Kludex/starlette/pull/2896).

## 0.46.0 (February 22, 2025)

#### Added

* `GZipMiddleware`: Make sure `Vary` header is always added if a response can be compressed [#2865](https://github.com/Kludex/starlette/pull/2865).

#### Fixed

* Raise exception from background task on BaseHTTPMiddleware [#2812](https://github.com/Kludex/starlette/pull/2812).
* `GZipMiddleware`: Don't compress on server sent events [#2871](https://github.com/Kludex/starlette/pull/2871).

#### Changed

* `MultiPartParser`: Rename `max_file_size` to `spool_max_size` [#2780](https://github.com/Kludex/starlette/pull/2780).

#### Deprecated

* Add deprecated warning to `TestClient(timeout=...)` [#2840](https://github.com/Kludex/starlette/pull/2840).

## 0.45.3 (January 24, 2025)

#### Fixed

* Turn directory into string on `lookup_path` on commonpath comparison [#2851](https://github.com/Kludex/starlette/pull/2851).

## 0.45.2 (January 4, 2025)

#### Fixed

* Make `create_memory_object_stream` compatible with old anyio versions once again, and bump anyio minimum version to 3.6.2 [#2833](https://github.com/Kludex/starlette/pull/2833).

## 0.45.1 (December 30, 2024)

#### Fixed

* Close `MemoryObjectReceiveStream` left unclosed upon exception in `BaseHTTPMiddleware` children [#2813](https://github.com/Kludex/starlette/pull/2813).
* Collect errors more reliably from the WebSocket logic on the `TestClient` [#2814](https://github.com/Kludex/starlette/pull/2814).

#### Refactor

* Use a pair of memory object streams instead of two queues on the `TestClient` [#2829](https://github.com/Kludex/starlette/pull/2829).

## 0.45.0 (December 29, 2024)

#### Removed

* Drop Python 3.8 support [#2823](https://github.com/Kludex/starlette/pull/2823).
* Remove `ExceptionMiddleware` import proxy from `starlette.exceptions` module [#2826](https://github.com/Kludex/starlette/pull/2826).
* Remove deprecated `WS_1004_NO_STATUS_RCVD` and `WS_1005_ABNORMAL_CLOSURE` [#2827](https://github.com/Kludex/starlette/pull/2827).

## 0.44.0 (December 28, 2024)

#### Added

* Add `client` parameter to `TestClient` [#2810](https://github.com/Kludex/starlette/pull/2810).
* Add `max_part_size` parameter to `Request.form()` [#2815](https://github.com/Kludex/starlette/pull/2815).

## 0.43.0 (December 25, 2024)

#### Removed

* Remove deprecated `allow_redirects` argument from `TestClient` [#2808](https://github.com/Kludex/starlette/pull/2808).

#### Added

* Make UUID path parameter conversion more flexible [#2806](https://github.com/Kludex/starlette/pull/2806).

## 0.42.0 (December 14, 2024)

#### Added

* Raise `ClientDisconnect` on `StreamingResponse` [#2732](https://github.com/Kludex/starlette/pull/2732).

#### Fixed

* Use ETag from headers when parsing If-Range in FileResponse [#2761](https://github.com/Kludex/starlette/pull/2761).
* Follow directory symlinks in `StaticFiles` when `follow_symlinks=True` [#2711](https://github.com/Kludex/starlette/pull/2711).
* Bump minimum `python-multipart` version to `0.0.18` [0ba8395](https://github.com/Kludex/starlette/commit/0ba83959e609bbd460966f092287df1bbd564cc6).
* Bump minimum `httpx` version to `0.27.0` [#2773](https://github.com/Kludex/starlette/pull/2773).

