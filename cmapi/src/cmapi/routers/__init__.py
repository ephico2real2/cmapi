"""Core routes: health, me, clusters, requests, admin. Plugins add theirs under cmapi.plugins."""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, Header, Request

from cmapi.core.context import AppContext
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.observability import AUTHZ_DENIED


def ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def caller(request: Request) -> Identity:
    """The verified caller; set by the auth dependency in cmapi.main."""
    who = getattr(request.state, "caller", None)
    if who is None:
        raise Problem(401, "unauthenticated", "Bearer token required")
    return who


def require(permission: str, env_from: Callable[..., str | None] | None = None) -> Callable[..., Identity]:
    """A dependency that checks one permission (the route's x-cmapi-permission)."""

    def dep(request: Request, who: Identity = Depends(caller)) -> Identity:
        c: AppContext = request.app.state.ctx
        try:
            c.cfg.roles.require(who, permission)
        except Problem:
            AUTHZ_DENIED.labels(permission).inc()
            raise
        return who

    return dep


def idempotency_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key",
                                                           description="Required on writes; the same key and caller return the first response for 24 hours")) -> str | None:
    return idempotency_key


def if_match(if_match: str | None = Header(default=None, alias="If-Match",
                                           description="The namespace's etag from GET; required on a change or delete")) -> str | None:
    return if_match
