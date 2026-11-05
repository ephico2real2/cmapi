"""The directory plugin: GET /directory/users through the DirectoryProvider (Keycloak admin API, read-only)."""
from __future__ import annotations

from fastapi import Depends, Query

from cmapi.core.context import AppContext
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.identity.directory import DirectoryUnavailable
from cmapi.core.models import DirectoryUser, DirectoryUsers
from cmapi.routers import ctx, require

router = DocumentedRouter("directory", prefix="/api/v1")


def _operator(who: Identity) -> bool:
    return bool({"cmapi-operator", "cmapi-admin"} & who.roles)


@router.read("/directory/users", summary="Search people", permission="objects:read", response_model=DirectoryUsers,
             problems=["idp-unavailable"])
def search(q: str = Query(min_length=2, description="Two or more characters of a username, name or email"),
           who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """Up to ten people matching the text, for the portal's people picker. The employee ID is returned to
    cmapi-operator and above only."""
    if c.directory is None:
        raise Problem(503, "idp-unavailable", "No directory is configured", extra={"retryAfter": 60})
    try:
        return {"items": [p.public(_operator(who)) for p in c.directory.search(q)]}
    except DirectoryUnavailable as exc:
        raise Problem(503, "idp-unavailable", f"Directory unavailable: {exc}", extra={"retryAfter": 30}) from exc


@router.read("/directory/users/{username}", summary="One person", permission="objects:read", response_model=DirectoryUser,
             problems=["object-not-found", "idp-unavailable"])
def get_user(username: str, who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """A person by username (cached 15 minutes, served from the cache when Keycloak is unreachable)."""
    if c.directory is None:
        raise Problem(503, "idp-unavailable", "No directory is configured", extra={"retryAfter": 60})
    try:
        p = c.directory.get_user(username)
    except DirectoryUnavailable as exc:
        raise Problem(503, "idp-unavailable", f"Directory unavailable: {exc}", extra={"retryAfter": 30}) from exc
    if p is None:
        raise Problem(404, "object-not-found", f"No user {username}")
    return p.public(_operator(who))
