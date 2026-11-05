"""The API: app factory (docs/02, main.py). Loads the instance, builds the adapters, mounts the
documented routers, refuses to start with an undocumented route, serves /docs, /redoc and the spec."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from cmapi import __version__
from cmapi.core.auth import caller_dependency, oauth2_scheme, unauthenticated_headers
from cmapi.core.context import AppContext, build_context
from cmapi.core.docs import check_documented
from cmapi.core.errors import Problem
from cmapi.core.kpi import register_collectors
from cmapi.core.observability import configure_logging, instrument, log, start_metrics
from cmapi.core.tiers import TierError
from cmapi.plugins.directory import router as directory_router
from cmapi.plugins.namespaces.router import router as namespaces_router
from cmapi.plugins.quotas import router as quotas_router
from cmapi.plugins.tiers import router as tiers_router
from cmapi.routers import admin, health, me, requests
from cmapi.settings import Settings, settings

STATIC = Path(os.environ.get("CMAPI_STATIC_DIR", "/opt/app-root/static"))


def create_app(s: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
    s = s or settings()
    configure_logging(s.log_level)
    ctx = ctx or build_context(s)
    issuer = ctx.issuer
    scheme = oauth2_scheme(issuer)
    authed = caller_dependency(scheme)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        register_collectors()
        if s.metrics_port:
            start_metrics(s.metrics_port, ctx.cfg.name, s.component)
        log.info("startup", instance=ctx.cfg.name, issuer=issuer, audience=ctx.audience, version=__version__,
                 commit=os.environ.get("CMAPI_GIT_COMMIT", "unknown"), clusters=ctx.registry.status_map())
        yield
        ctx.shutdown()

    docs_cfg = (ctx.cfg.raw_instance["instance"].get("docs") or {})
    app = FastAPI(title=f"cmapi ({ctx.cfg.name})", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/openapi.json" if docs_cfg.get("enabled", True) else None,
                  description=f"The {ctx.cfg.name} instance serves {sorted(ctx.cfg.allowed_environments)}. "
                              "Every write is approved in cmapi, then becomes a bot pull request to cluster-configs.",
                  swagger_ui_init_oauth={"clientId": "cmapi-docs", "usePkceWithAuthorizationCodeGrant": True,
                                         "scopes": "openid"})
    app.state.ctx = ctx
    app.state.auth = ctx.auth
    instrument(app)

    @app.exception_handler(Problem)
    async def problem_handler(_: Request, exc: Problem) -> Response:
        return JSONResponse(exc.body(), status_code=exc.status, media_type="application/problem+json",
                            headers=dict(unauthenticated_headers(exc)))

    @app.exception_handler(TierError)
    async def tier_error_handler(_: Request, exc: TierError) -> Response:
        p = Problem.policy_violation(exc.detail, [{"code": exc.code, **exc.data}])
        return JSONResponse(p.body(), status_code=p.status, media_type="application/problem+json")

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> Response:
        p = Problem.unprocessable("validation-failed", str(exc)[:300])
        return JSONResponse(p.body(), status_code=p.status, media_type="application/problem+json")

    app.include_router(health.router)
    app.include_router(health.version_router)
    for r in (me.router, requests.router, admin.router, namespaces_router, tiers_router, directory_router, quotas_router):
        app.include_router(r, dependencies=[Depends(authed)])
    check_documented(app)

    if docs_cfg.get("enabled", True):
        swagger_dir = STATIC / "swagger-ui"
        redoc_dir = STATIC / "redoc"
        if swagger_dir.exists():
            app.mount("/static/swagger", StaticFiles(directory=str(swagger_dir)), name="swagger")
        if redoc_dir.exists():
            app.mount("/static/redoc", StaticFiles(directory=str(redoc_dir)), name="redoc")

        @app.get("/docs", include_in_schema=False)
        def docs() -> Response:
            # Bundled Swagger UI: a network-limited zone may not reach a CDN (docs/01).
            local = swagger_dir.exists()
            return get_swagger_ui_html(
                openapi_url="/openapi.json", title=f"cmapi ({ctx.cfg.name}) - API docs",
                oauth2_redirect_url="/docs/oauth2-redirect",
                swagger_js_url="/static/swagger/swagger-ui-bundle.js" if local else "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
                swagger_css_url="/static/swagger/swagger-ui.css" if local else "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
                swagger_favicon_url="/static/swagger/favicon-32x32.png" if local else "https://fastapi.tiangolo.com/img/favicon.png",
                init_oauth=app.swagger_ui_init_oauth, swagger_ui_parameters={"persistAuthorization": True})

        @app.get("/docs/oauth2-redirect", include_in_schema=False)
        def docs_redirect() -> Response:
            from fastapi.openapi.docs import get_swagger_ui_oauth2_redirect_html
            return get_swagger_ui_oauth2_redirect_html()

        @app.get("/redoc", include_in_schema=False)
        def redoc() -> Response:
            local = redoc_dir.exists()
            return get_redoc_html(openapi_url="/openapi.json", title=f"cmapi ({ctx.cfg.name}) - reference",
                                  redoc_js_url="/static/redoc/redoc.standalone.js" if local
                                  else "https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js")

        @app.get("/openapi.yaml", include_in_schema=False)
        def openapi_yaml() -> Response:
            return Response(yaml.safe_dump(app.openapi(), sort_keys=False), media_type="application/yaml")

    _add_servers(app, ctx)
    return app


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
