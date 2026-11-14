"""The API: app factory (docs/02, main.py). Loads the instance, builds the adapters, mounts the
documented routers, refuses to start with an undocumented route, serves /docs, /redoc and the spec."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cmapi import __version__
from cmapi.core.auth import caller_dependency, oauth2_scheme, unauthenticated_headers
from cmapi.core.context import AppContext, build_context
from cmapi.core.changelog import changelog_html
from cmapi.core.cors import EXPOSED_HEADERS, MAX_AGE, METHODS, REQUEST_HEADERS, OriginVaryCORSMiddleware, allowed_origins
from cmapi.core.docs import PROBLEMS, build_openapi, check_documented, plugin_routers
from cmapi.core.errors import Problem, type_base
from cmapi.core.kpi import register_collectors
from cmapi.core.problem_docs import problem_html, problems_index_html
from cmapi.core.observability import configure_logging, instrument, log, start_metrics
from cmapi.core.tiers import TierError
from cmapi.routers import admin, health, me, requests
from cmapi.settings import Settings, settings

STATIC = Path(os.environ.get("CMAPI_STATIC_DIR", "/opt/app-root/static"))


class UnhandledToProblemMiddleware:
    """An exception that no handler takes becomes the problem internal-error (#216).

    Starlette's own 500 is sent outside each middleware, so it has no CORS header and no X-Request-Id. The answer here has no
    text of the exception; the log line `unhandled` has it, with the request ID that the answer carries. A plain ASGI
    middleware, not BaseHTTPMiddleware: that one runs the application in a task group, where a cancelled request or a client
    that went away turns into RuntimeError("No response returned.") and would be logged as a failure of the service (review
    finding F3). A cancellation goes on unchanged, a client that went away gets no answer, and an answer that has started
    is never replaced.
    """

    def __init__(self, app: ASGIApp, problem_response: Any):
        self.app = app
        self.problem_response = problem_response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False
        disconnected = False

        async def receive_checked() -> Message:
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
            return message

        async def send_checked(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            try:
                await send(message)
            except OSError as exc:
                # ASGI servers signal a closed connection through send() this way.
                raise ClientDisconnect() from exc

        try:
            await self.app(scope, receive_checked, send_checked)
        except asyncio.CancelledError:
            raise
        except ClientDisconnect:
            return
        except Exception:
            if disconnected:
                return
            request = Request(scope)
            log.exception("unhandled", method=request.method, route=getattr(scope.get("route"), "path", "unmatched"))
            if started:
                raise  # A stream/background failure cannot replace a status already sent.
            response = self.problem_response(Problem(500, "internal-error", PROBLEMS["internal-error"][1]))
            await response(scope, receive, send)


def create_app(s: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
    s = s or settings()
    configure_logging(s.log_level)
    ctx = ctx or build_context(s)
    issuer = ctx.issuer
    scheme = oauth2_scheme(issuer)
    authed = caller_dependency(scheme)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        register_collectors(ctx.registry, ctx.pipeline.reserved)
        if s.metrics_port:
            start_metrics(s.metrics_port, ctx.cfg.name, s.component)
        log.info("startup", instance=ctx.cfg.name, issuer=issuer, audience=ctx.audience, version=__version__,
                 commit=os.environ.get("CMAPI_GIT_COMMIT", "unknown"), clusters=ctx.registry.status_map(),
                 plugins=list(ctx.cfg.plugins.enabled), plugins_file=ctx.cfg.plugins.configured)
        yield
        ctx.shutdown()

    docs_cfg = (ctx.cfg.raw_instance["instance"].get("docs") or {})
    docs_enabled = docs_cfg.get("enabled", True)
    # FastAPI's own /openapi.json is off: the route below serves the document with an ETag, and behind sign-in when docs.public is false.
    app = FastAPI(title=f"cmapi ({ctx.cfg.name})", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None,
                  description=f"The {ctx.cfg.name} instance serves {sorted(ctx.cfg.allowed_environments)}. "
                              "Every write is approved in cmapi, then becomes a bot pull request to cluster-configs.",
                  swagger_ui_init_oauth={"clientId": "cmapi-docs", "usePkceWithAuthorizationCodeGrant": True,
                                         "scopes": "openid"})
    app.state.ctx = ctx
    app.state.auth = ctx.auth
    problem_base = type_base(ctx.cfg.raw_instance["instance"])

    def problem_response(p: Problem, headers: dict[str, str] | None = None) -> Response:
        return JSONResponse(p.body(problem_base), status_code=p.status, media_type="application/problem+json", headers=headers)

    app.add_middleware(UnhandledToProblemMiddleware, problem_response=problem_response)

    instrument(app)
    # CORS is added after the request middleware, so it is the outer one: each answer that the application makes has the
    # headers, a problem and a rate limit refusal too. Without them a browser hides the status and the body from the portal.
    origins = allowed_origins(ctx.cfg.raw_instance["instance"])
    if origins:
        app.add_middleware(OriginVaryCORSMiddleware, allow_origins=origins, allow_methods=METHODS, allow_headers=REQUEST_HEADERS,
                           expose_headers=EXPOSED_HEADERS, allow_credentials=False, max_age=MAX_AGE)
    app.state.cors_origins = origins

    @app.exception_handler(Problem)
    async def problem_handler(_: Request, exc: Problem) -> Response:
        return problem_response(exc, dict(unauthenticated_headers(exc)))

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_: Request, exc: RequestValidationError) -> Response:
        # FastAPI's own refusal of a parameter or a body, as the same RFC 9457 problem as every other refusal. The input value is
        # left out: it can hold what the caller did not mean to send back, and the field names it.
        errors = [{"field": ".".join(str(part) for part in e.get("loc", ())), "message": e.get("msg", ""), "code": e.get("type", "")}
                  for e in exc.errors()]
        p = Problem(422, "validation-failed", "The request is not valid: " + "; ".join(f"{e['field']}: {e['message']}" for e in errors)[:400],
                    errors)
        return problem_response(p)

    @app.exception_handler(TierError)
    async def tier_error_handler(_: Request, exc: TierError) -> Response:
        return problem_response(Problem.policy_violation(exc.detail, [{"code": exc.code, **exc.data}]))

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> Response:
        return problem_response(Problem.unprocessable("validation-failed", str(exc)[:300]))

    app.include_router(health.router)
    app.include_router(health.version_router)
    # The core routers always, then the router of each plugin that plugins.yaml enables (core/plugins.py).
    authed_routers = (me.router, requests.router, admin.router, *ctx.cfg.plugins.routers())
    for r in authed_routers:
        app.include_router(r, dependencies=[Depends(authed)])
    check_documented(app)
    _add_servers(app, ctx)
    plugins = plugin_routers((health.version_router, *authed_routers))
    app.state.plugins = plugins
    public_url = ctx.cfg.raw_instance["instance"].get("publicUrl") or "$CMAPI_URL"

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = build_openapi(app, plugins, public_url, problem_base, ctx.cfg.metadata)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    _add_problem_pages(app, ctx, problem_base)
    if docs_enabled:
        _add_docs(app, ctx, docs_cfg, authed, problem_response)
    return app


def _add_problem_pages(app: FastAPI, ctx: AppContext, problem_base: str) -> None:
    """/problems and /problems/{code}: what the `type` of a problem resolves to (RFC 9457, section 4; #182).

    Public always, also with docs.public false or docs.enabled false: a caller with no token gets the problem unauthenticated,
    and its type must resolve for that caller. The pages hold the registry of core/docs.py and nothing of the instance's data.
    """
    @app.get("/problems", include_in_schema=False)
    def problems_index() -> Response:
        return HTMLResponse(problems_index_html(problem_base, ctx.cfg.name))

    @app.get("/problems/{code}", include_in_schema=False)
    def problem_page(code: str) -> Response:
        if code not in PROBLEMS:
            raise Problem(404, "object-not-found", "No such problem type. /problems lists each one")
        return HTMLResponse(problem_html(code, problem_base, ctx.cfg.name))


def _add_docs(app: FastAPI, ctx: AppContext, docs_cfg: dict[str, Any], authed: Any, problem_response: Any) -> None:
    """/docs, /redoc, /openapi.json, /openapi.yaml and /docs/changelog (docs/01, "API documentation").

    Public unless instance.yaml says docs.public: false; then each of the five needs a valid bearer token and answers
    401 with WWW-Authenticate without one. Swagger UI and ReDoc come from the image's bundles only, never a CDN: without
    the bundles the two pages answer 503 and name the command that fetches them (cmapi-tools docs-assets).
    """
    guard = [] if docs_cfg.get("public", True) else [Depends(authed)]
    swagger_dir, redoc_dir = STATIC / "swagger-ui", STATIC / "redoc"
    if swagger_dir.exists():
        app.mount("/static/swagger", StaticFiles(directory=str(swagger_dir)), name="swagger")
    if redoc_dir.exists():
        app.mount("/static/redoc", StaticFiles(directory=str(redoc_dir)), name="redoc")
    documents: dict[str, tuple[bytes, str]] = {}

    def document(kind: str) -> tuple[bytes, str]:
        """The document's bytes and its strong ETag (RFC 9110, 8.8.3): a hash of exactly the bytes served."""
        if kind not in documents:
            spec = app.openapi()
            body = (json.dumps(spec, separators=(",", ":")) if kind == "json" else yaml.safe_dump(spec, sort_keys=False)).encode()
            documents[kind] = (body, '"' + hashlib.sha256(body).hexdigest()[:32] + '"')
        return documents[kind]

    def serve(kind: str, media_type: str, request: Request) -> Response:
        body, etag = document(kind)
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return Response(body, media_type=media_type, headers=headers)

    @app.get("/openapi.json", include_in_schema=False, dependencies=guard)
    def openapi_json(request: Request) -> Response:
        return serve("json", "application/json", request)

    @app.get("/openapi.yaml", include_in_schema=False, dependencies=guard)
    def openapi_yaml(request: Request) -> Response:
        return serve("yaml", "application/yaml", request)

    def missing(what: str) -> Response:
        p = Problem(503, "docs-assets-missing", f"The {what} bundle is not in {STATIC}. The image holds it; in a source checkout, "
                                                 "run `cmapi-tools docs-assets` once, which fetches the versions the Containerfile pins.")
        return problem_response(p)

    @app.get("/docs", include_in_schema=False, dependencies=guard)
    def docs() -> Response:
        if not swagger_dir.exists():
            return missing("Swagger UI")
        return get_swagger_ui_html(
            openapi_url="/openapi.json", title=f"cmapi ({ctx.cfg.name}) - API docs", oauth2_redirect_url="/docs/oauth2-redirect",
            swagger_js_url="/static/swagger/swagger-ui-bundle.js", swagger_css_url="/static/swagger/swagger-ui.css",
            swagger_favicon_url="/static/swagger/favicon-32x32.png",
            init_oauth=app.swagger_ui_init_oauth, swagger_ui_parameters={"persistAuthorization": True})

    @app.get("/docs/oauth2-redirect", include_in_schema=False)
    def docs_redirect() -> Response:
        return get_swagger_ui_oauth2_redirect_html()

    @app.get("/redoc", include_in_schema=False, dependencies=guard)
    def redoc() -> Response:
        if not redoc_dir.exists():
            return missing("ReDoc")
        # FastAPI's page with its two outside requests removed: the Google Fonts stylesheet and FastAPI's own favicon.
        return get_redoc_html(openapi_url="/openapi.json", title=f"cmapi ({ctx.cfg.name}) - reference",
                              redoc_js_url="/static/redoc/redoc.standalone.js", with_google_fonts=False,
                              redoc_favicon_url="/static/swagger/favicon-32x32.png")

    @app.get("/docs/changelog", include_in_schema=False, dependencies=guard)
    def changelog() -> Response:
        return HTMLResponse(changelog_html(f"cmapi ({ctx.cfg.name})", __version__))


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    """If-None-Match against the document's tag, by the weak comparison RFC 9110 13.1.2 asks for."""
    if not if_none_match:
        return False
    candidates = [c.strip() for c in if_none_match.split(",")]
    return "*" in candidates or etag in [c.removeprefix("W/") for c in candidates]


def _add_servers(app: FastAPI, ctx: AppContext) -> None:
    public = ctx.cfg.raw_instance["instance"].get("publicUrl")
    if public:
        app.servers = [{"url": public, "description": f"the {ctx.cfg.name} instance"}]


def run() -> None:
    import uvicorn
    s = settings()
    uvicorn.run("cmapi.main:create_app", factory=True, host="0.0.0.0", port=s.bind_port, log_level=s.log_level.lower(),
                proxy_headers=True, forwarded_allow_ips="*", timeout_graceful_shutdown=20)


if __name__ == "__main__":
    run()
