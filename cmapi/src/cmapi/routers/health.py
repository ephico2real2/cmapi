"""Health, readiness and version: no token needed, nothing sensitive in the body."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Response

from cmapi import __version__
from cmapi.core.context import AppContext
from cmapi.core.models import Api, Health
from cmapi.routers import ctx
from pydantic import Field

router = APIRouter(tags=["health"])


class Version(Api):
    version: str = Field(description="cmapi version", examples=["0.2.0"])
    commit: str = Field(description="Git commit the image was built from", examples=["72d082b4c1"])
    component: str = Field(description="api, worker or capacity", examples=["api"])


@router.get("/healthz", summary="Liveness", response_model=Health, include_in_schema=False)
def healthz(c: AppContext = Depends(ctx)) -> dict:
    """Which issuer, audience, repository and clusters this instance is wired to."""
    return _health(c)


@router.get("/readyz", summary="Readiness", include_in_schema=False)
def readyz(response: Response, c: AppContext = Depends(ctx)) -> dict:
    """Ready when the database answers; a cluster being down does not make the API unready."""
    db = c.db.ping()
    if db != "ok":
        response.status_code = 503
    return {"status": "ok" if db == "ok" else "degraded", "database": db}


@router.get("/api/v1/version", summary="Version and commit of the running build", response_model=Version,
            operation_id="core_version", description="The commit the image was built from, so a deployment can be checked against its source.")
def version() -> dict:
    """The commit the image was built from, so a deployment can be checked against its source."""
    return {"version": __version__, "commit": os.environ.get("CMAPI_GIT_COMMIT", "unknown"),
            "component": os.environ.get("CMAPI_COMPONENT", "api")}


def _health(c: AppContext) -> dict:
    return {"status": "ok", "instance": c.cfg.name, "version": __version__, "issuer": c.issuer, "audience": c.audience,
            "database": c.db.ping(), "git": c.git.repository, "clusters": c.registry.status_map()}
