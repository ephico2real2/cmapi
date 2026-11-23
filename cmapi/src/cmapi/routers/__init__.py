"""Core routes: health, me, clusters, requests, admin. Plugins add theirs under cmapi.plugins."""
from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, Header, Path, Query, Request

from cmapi.core.context import AppContext
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.observability import AUTHZ_DENIED


# The parameters that more than one route takes, each described once. check_documented refuses a parameter with no description or example.
# The cluster that every example names; the create example takes its environment where clusters.yaml has it (#479).
EXAMPLE_CLUSTER = "CRC"
ClusterId = Annotated[str, Path(description="The cluster's ID, as `GET /api/v1/clusters` returns it.",
                                examples=[EXAMPLE_CLUSTER])]
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
                                                           description="A new random value for each new request, such as a UUID, of at most 100 "
                                                                       "characters. Required, except with `dryRun=true`. The same key and caller get "
                                                                       "the first answer again for 24 hours.")) -> str | None:
    return idempotency_key


def delete_idempotency_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key",
                                                                  examples=["0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10"],
                                                                  description="A new random value for each new request, such as a UUID, of at most "
                                                                              "100 characters. Required: a delete has no dry run. The same key and "
                                                                              "caller get the first answer again for 24 hours.")) -> str | None:
    """The delete's key: the same header, described without the dry run that a delete does not take (_idem(key, False))."""
    return idempotency_key


def if_match(request: Request,
             if_match: str | None = Header(default=None, alias="If-Match", examples=['"3f9a1c0b7e2d4a68"'],
                                           description="The namespace's etag from `GET .../namespaces/{ns}`, in double quotes as "
                                                       "its `ETag` header gives it. Required on a change or a delete. A list "
                                                       "of tags passes when one of them is the current etag (RFC 9110, section "
                                                       "13.1.1). `*` is 428 `precondition-required`: If-Match must name the "
                                                       "etag that was read. A weak tag (`W/\"...\"`) never matches. An "
                                                       "Idempotency-Key replay returns the request that its key opened without "
                                                       "comparing the tag.")) -> str | None:
    """If-Match as one list: a field sent on several lines is the same list joined with commas (RFC 9110, section 5.3),
    and FastAPI's Header gives only the first line. The Header parameter stays, so the document describes the field."""
    lines = request.headers.getlist("If-Match")
    return ", ".join(lines) if lines else if_match
