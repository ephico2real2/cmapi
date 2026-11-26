"""Core routes: health, me, clusters, requests, admin. Plugins add theirs under cmapi.plugins."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated, Any, Callable, Iterator

from fastapi import Depends, Header, Path, Query, Request

from cmapi.core.context import AppContext
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.observability import AUTHZ_DENIED, RATE_LIMITED, log
from cmapi.core.ratelimit import TEAM, Refusal, rate_class


# The parameters that more than one route takes, each described once. check_documented refuses a parameter with no description or example.
# The cluster that every example names; the create example takes its environment where clusters.yaml has it (#479).
EXAMPLE_CLUSTER = "CRC"
ClusterId = Annotated[str, Path(description="The cluster's ID, as `GET /api/v1/clusters` returns it.",
                                examples=[EXAMPLE_CLUSTER])]
NamespaceName = Annotated[str, Path(description="The name of the namespace on that cluster.", examples=["payments-dev"])]
RequestId = Annotated[str, Path(description="The request's ID, as the write that opened the request returned it.",
                                examples=["req-20261105-0001"])]
DryRun = Annotated[bool, Query(alias="dryRun", examples=[True],
                               description="With `true`, the call returns the plan with status 200 and needs no Idempotency-Key. "
                                           "It opens no change request, takes no lock or reservation and opens no pull "
                                           "request. Send it at most once: a repeated `dryRun` is 422 `validation-failed`.")]
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


def rate_limit(authed: Callable[..., Identity]) -> Callable[..., Any]:
    """The 429 of the caller's bucket (core/ratelimit.py, #689), a dependency of each router that takes a token (main.py,
    api_app), after the sign-in that it names.

    FastAPI reads and decodes the body before it solves any dependency, then solves the dependencies in order, then checks
    the path, query, header and body against the route (FastAPI 0.162.2, routing.py:450-499 and :511,
    dependencies/utils.py:676-768). So a caller over the limit is refused before the route checks the body, the permission
    or any parameter, and before any work of the route; the JSON decode of a body under the body limit is the cost left.
    The sign-in comes first because the bucket is the caller's: a call with no valid token is 401 and takes no token.
    `authed` is the same dependency as the router's, so FastAPI verifies the token once (its dependency cache)."""

    async def limited(request: Request, who: Identity = Depends(authed)) -> None:
        # The template of the APIRoute that matched, as the document writes it (`{request_id}`, without its convertor)
        template = request.scope["route"].path_format
        refusal = request.app.state.ctx.limiter.take(rate_class(request.method, template), who.sub)
        if refusal is not None:
            raise refused(refusal, who)

    return limited


def refused(refusal: Refusal, who: Identity) -> Problem:
    """Count a rate limit refusal and answer it: 429 rate-limited with retryAfter, which main.py's problem_response also
    sends as Retry-After. The log line `rate_limited` is written once for each run of refusals of a bucket, not for each
    refusal, so a client that keeps retrying does not flood the log; the access log line `http` has every 429."""
    RATE_LIMITED.labels(refusal.kind).inc()
    if refusal.first:
        log.warning("rate_limited", limit=refusal.kind, caller_sub=who.sub, client=who.client_id,
                    team=refusal.key if refusal.kind == TEAM else None, retry_after=refusal.retry_after)
    return refusal.problem()


@contextmanager
def team_request(c: AppContext, who: Identity, team: str | None) -> Iterator[None]:
    """The team's bucket: one token for each change request that a write opens for the team (the namespace's
    cmapi.net/team, as the request records it), whoever sends it. Entered once the plan knows the team and before the
    request is recorded, around the transaction that records it; a dry run, a replay of an Idempotency-Key and a refused
    plan open no request and take no token. A transaction that ends in an error records no request, so its token is given
    back (#695 review)."""
    if not team:
        yield
        return
    refusal = c.limiter.take(TEAM, team)
    if refusal is not None:
        raise refused(refusal, who)
    try:
        yield
    except BaseException:
        c.limiter.give_back(TEAM, team)
        raise


def idempotency_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key",
                                                           examples=["0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10"],
                                                           description="A new random value for each new request, such as a UUID, of at most 100 "
                                                                       "characters. Required, except with `dryRun=true`. For 24 hours, the same "
                                                                       "caller retrying the same request with the same key gets the original "
                                                                       "request in its current state. The caller is the token's subject: a "
                                                                       "service that sends `onBehalfOf` holds its key, and the person cannot "
                                                                       "replay it: the person's own use of that key is a request of their own. "
                                                                       "The same key with another "
                                                                       "request is 409 `idempotency-replay`. The expiry writes do not compare "
                                                                       "`justification`: a retry that changes only it gets the original "
                                                                       "request.")) -> str | None:
    """The key of a create, a change and the expiry writes. The row holds it under the caller's subject (core/pipeline.py,
    submit), and `_replay` (plugins/namespaces/router.py) looks it up under the same subject (#592). The caller's unique
    index is the key's only one since migration 0009, so a person may use a key that a service holds for them (#603).
    Each route chooses what its fingerprint holds; the expiry writes leave out `justification`. The Idempotency-Key draft
    (draft-ietf-httpapi-idempotency-key-header-09, section 2.4): "If the fingerprint covers only part of the payload,
    requests that differ only outside that part are treated as the same request", and a resource that computes one
    "SHOULD document it". So the description says so."""
    return idempotency_key


def delete_idempotency_key(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key",
                                                                  examples=["0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10"],
                                                                  description="A new random value for each new request, such as a UUID, of at most "
                                                                              "100 characters. Required, except with `dryRun=true`. For 24 hours, the "
                                                                              "same caller retrying the same request with the same key gets the "
                                                                              "original request in its current state.")) -> str | None:
    """The delete's key: the same header, described without what the delete does not take (onBehalfOf, justification)."""
    return idempotency_key


def if_match(request: Request,
             if_match: str | None = Header(default=None, alias="If-Match", examples=['"3f9a1c0b7e2d4a68"'],
                                           description="The namespace's etag from `GET .../namespaces/{ns}`, in double quotes as "
                                                       "its `ETag` header gives it. Required on a change or a delete. A list "
                                                       "of tags passes when one of them is the current etag (RFC 9110, section "
                                                       "13.1.1). Send the tags in one comma-separated If-Match field "
                                                       "(`If-Match: \"a\", \"b\"`): the front door answers 400 to a second "
                                                       "If-Match line. `*` is 428 `precondition-required`: If-Match must name "
                                                       "the etag that was read. A weak tag (`W/\"...\"`) never matches. An "
                                                       "Idempotency-Key replay returns the original request in its current "
                                                       "state without comparing the tag.")) -> str | None:
    """If-Match as one list: a field sent on several lines is the same list joined with commas (RFC 9110, section 5.3),
    and FastAPI's Header gives only the first line. The Header parameter stays, so the document describes the field.

    The join serves a caller that reaches the API directly. Through the front door the tags must come in one field:
    nginx registers If-Match with ngx_http_process_unique_header_line, which answers 400 to a second line (nginx
    1.30.6, src/http/ngx_http_request.c, #582). The document marks the field required although the default is None
    (core/docs.py, _document_if_match_required): the plan answers 404 for a namespace missing from Git before 428."""
    lines = request.headers.getlist("If-Match")
    return ", ".join(lines) if lines else if_match
