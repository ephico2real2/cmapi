"""Core routes: health, me, clusters, requests, admin. Plugins add theirs under cmapi.plugins."""
from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, Header, Path, Query, Request

from cmapi.core.context import AppContext
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.observability import AUTHZ_DENIED


# The parameters that more than one route takes, each described once. check_documented refuses a parameter with no description or example.
ClusterId = Annotated[str, Path(description="The cluster's ID, as `GET /api/v1/clusters` returns it.", examples=["CRC"])]
NamespaceName = Annotated[str, Path(description="The name of the namespace on that cluster.", examples=["payments-dev"])]
RequestId = Annotated[str, Path(description="The request's ID, as the write that opened the request returned it.",
                                examples=["req-20261105-0001"])]
DryRun = Annotated[bool, Query(alias="dryRun", examples=[True],
                               description="With `true`, the call returns the plan with status 200, writes nothing and needs no "
                                           "Idempotency-Key.")]
Limit = Annotated[int, Query(examples=[50],
                             description="The number of rows in one page: 25, 50 or 100, and never more than 200. A larger "
                                         "result is not cut: `page.nextCursor` gives the next page.")]
Cursor = Annotated[str | None, Query(examples=["eyJrIjpbInBheW1lbnRzLWRldiIsIkNSQyJdLCJkIjoibmV4dCJ9.2f1c"],
                                     description="`page.nextCursor` or `page.prevCursor` of an earlier page of the same "
                                                 "filters and sort. A cursor of other filters returns 400 `invalid-cursor`.")]


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
                                                           examples=["0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10"],
                                                           description="Required on writes; the same key and caller return the first response for 24 hours")) -> str | None:
    return idempotency_key


def if_match(if_match: str | None = Header(default=None, alias="If-Match", examples=['"3f9a1c0b7e2d4a68"'],
                                           description="The namespace's etag from GET; required on a change or delete")) -> str | None:
    return if_match
