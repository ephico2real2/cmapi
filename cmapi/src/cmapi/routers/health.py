"""Health, readiness and version: no token needed, nothing sensitive in the body."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Response

from cmapi import __version__
from cmapi.core.context import AppContext
from cmapi.core.db.repo import JobRepo
from cmapi.core.docs import CORE, DocumentedRouter
from cmapi.core.models import Api, Health
from cmapi.routers import ctx
from pydantic import Field

router = APIRouter(tags=["health"])
version_router = DocumentedRouter("core", prefix="/api/v1", **CORE)


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
    """Ready when the database answers and its schema is at or past the revision this code needs; a cluster
    being down does not make the API unready. During a rolling upgrade an older pod stays ready on a newer schema."""
    db = c.db.ping()
    schema = c.db.schema_status() if db == "ok" else "unavailable"
    ready = db == "ok" and schema == "ok"
    if not ready:
        response.status_code = 503
    return {"status": "ok" if ready else "degraded", "database": db, "schema": schema}


# async, with no I/O: the liveness probe, so a saturated thread pool or database never restarts the pod
@version_router.read("/version", summary="Version and commit of the running build", permission=None, response_model=Version)
async def version() -> dict:
    """The commit the image was built from, so a deployment can be checked against its source."""
    return {"version": __version__, "commit": os.environ.get("CMAPI_GIT_COMMIT", "unknown"),
            "component": os.environ.get("CMAPI_COMPONENT", "api")}


def _health(c: AppContext) -> dict:
    db = c.db.ping()
    due = None
    if db == "ok":
        with c.db.session() as s:
            due = JobRepo(s).oldest_due_seconds()
    return {"status": "ok" if db == "ok" else "degraded", "instance": c.cfg.name, "version": __version__, "issuer": c.issuer,
            "audience": c.audience, "database": db, "git": c.git.repository, "clusters": c.registry.status_map(),
            "oldestDueJobSeconds": due}
