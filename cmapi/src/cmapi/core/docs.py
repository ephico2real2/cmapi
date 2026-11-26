"""The documentation layer (docs/01, "API documentation"): a route that is not fully described
does not start.

Routes register through DocumentedRouter.read() and .write(), which take the summary, the
permission, the problems the route can raise and the response model, and fill in the OpenAPI
pieces the code already knows: operationId from plugin and function, the "Requires" line, the
problem responses with one example each, the 202 shape for writes, the plugin's tag and version.
check_documented(app) runs at startup and refuses any /api route without a summary, a description
or a response model, any path, query or header parameter without a description and an example, any
model field without a description, and any required scalar model field without an example.

build_openapi(app, ...) adds what only the whole document can say: the tag descriptions, ReDoc's
x-tagGroups, one curl sample per operation (x-codeSamples), and the request and response examples
that a run of the service suite recorded (contract/samples.json).
"""
from __future__ import annotations

import inspect
import json
import shlex
from dataclasses import dataclass, fields
from importlib import resources
from typing import Any, Callable, Sequence

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from pydantic import BaseModel

from cmapi import __version__
from cmapi.core.errors import BASE, Problem
from cmapi.core.etag import STALE_READ
from cmapi.core.http_settings import DEFAULT_MAX_REQUEST_BODY_BYTES, too_large
from cmapi.core.models import ProblemDetail
from cmapi.core.ratelimit import rate_class

# Every problem code a route may declare, with its status and an example detail (docs/02, API contract).
PROBLEMS: dict[str, tuple[int, str]] = {
    "unauthenticated": (401, "Bearer token required"),
    "forbidden": (403, "Missing permission namespaces:create"),
    "environment-forbidden": (403, "Your roles grant namespaces:create only in ['rnd'], not dev"),
    "cluster-not-found": (404, "Unknown cluster OCP_X"),
    "object-not-found": (404, "No request req-20261105-0001"),
    "not-found": (404, "No resource of this API has this path"),
    "method-not-allowed": (405, "The path does not take this method. Allow lists the methods it takes"),
    "change-pending": (409, "req-20261105-0001 holds payments-dev"),
    "namespace-exists": (409, "payments-dev is already in Git"),
    "namespace-exists-unmanaged": (409, "payments-dev exists on the cluster and is not managed by cmapi"),
    "not-pending": (409, "req-20261105-0001 is synced"),
    "invalid-transition": (409, "cancel is not allowed in state merged"),
    "already-approved": (409, "This person already approved the request"),
    "self-approval": (409, "Requesters cannot approve their own request here"),
    "nothing-to-prune": (409, "No delete of payments-dev is awaiting a prune"),
    # The two below are returned by no operation: the daily expire_check holds the expiry delete with them, and the log line
    # expiry_delete_held names them (jobs/expire_check.py, core/pipeline.py check_prune_confirm; #263). Registered so that
    # /problems/<code> documents each code that cmapi raises.
    "prune-confirmation-missing": (409, "The live namespace payments-dev is not a cmapi namespace whose "
                                        "argocd.argoproj.io/sync-options holds Prune=confirm, so Argo CD would prune it "
                                        "without an operator: the expiry delete is held"),
    "expiry-delete-already-opened": (409, "A delete request was opened for the expiry 2026-11-01 of payments-dev"),
    "folder-holds-submodule": (409, "The folder of payments-dev holds the submodule clusters/CRC/namespaces/payments-dev/vendor"),
    "folder-not-utf8": (409, "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml, whose name is not "
                             "UTF-8: cmapi carries a folder's names and manifests as UTF-8 text. Rename it in Git, then send the "
                             "request again"),
    "folder-not-yaml": (409, "The folder of payments-dev holds clusters/CRC/namespaces/payments-dev/namespace.yaml, which is not "
                             "YAML: expected ',' or '}', but got '<stream end>' at line 4, column 1. Correct it in Git, then send "
                             "the request again"),
    "several-resource-quotas": (409, "The folder of payments-dev holds 2 ResourceQuotas, payments-dev-objects, payments-dev-quota: a "
                                     "change of the quota or the tier must name the object it changes, and a request cannot name "
                                     "one. Change only labels, annotations or the expiry, or leave one ResourceQuota in the folder "
                                     "in Git, then send the request again"),
    "idempotency-replay": (409, "Idempotency-Key was used for a different request"),
    "precondition-failed": (412, "The namespace changed in Git since you read it"),
    "content-too-large": (413, too_large(DEFAULT_MAX_REQUEST_BODY_BYTES).detail),
    "validation-failed": (422, "Request body is not valid"),
    "policy-violation": (422, "Metadata refused"),
    "capacity-exceeded": (422, "memory would exceed the cluster"),
    "environment-not-served": (422, "qa is not served by the nonprod instance"),
    "cluster-not-writable": (422, "CRC is imported but has no clusters.yaml entry"),
    "plugin-disabled": (422, "The namespaces plugin takes no writes in dev on the nonprod instance: plugins.yaml disables it there"),
    "reserved-namespace": (422, "kube-tools is reserved"),
    "invalid-namespace-name": (422, "Not a DNS-1123 label"),
    "no-change": (422, "The request changes nothing"),
    "identity-incomplete": (422, "The token has no employee_id claim"),
    "unknown-user": (422, "1009 is not an enabled user"),
    "invalid-team-dl": (422, "x@other.com is not an address in ['ephico2real.com']"),
    "expiration-not-allowed": (422, "Production namespaces never expire"),
    "expiration-limit": (422, "An extension is at most 30 days"),
    "expiration-in-past": (422, "The new date must be later than the current one"),
    "expiration-not-set": (422, "The namespace is permanent; use :set"),
    "expiration-already-set": (422, "Use :extend to move an existing date"),
    "namespace-protected": (422, "Protected namespaces cannot be deleted"),
    "unknown-serviceaccount": (422, "ci-deployer is not a ServiceAccount of payments-dev"),
    "on-behalf-of-not-allowed": (422, "A person calls as themselves"),
    "on-behalf-of-required": (422, "A service client must name the person"),
    "not-eligible": (403, "Not in an approving group still needed"),
    "precondition-required": (428, "If-Match is required on a change"),
    "idempotency-key-required": (400, "Idempotency-Key header is required on writes"),
    "invalid-cursor": (400, "The cursor is not valid"),
    "invalid-sort": (400, "Unknown sort used2"),
    "invalid-limit": (400, "limit is one of (25, 50, 100), at most 200"),
    "dry-run-not-supported": (400, "This call has no dry run, and nothing was done"),
    "bad-request": (400, "Too many fields. Maximum number of fields is 1000."),
    "rate-limited": (429, "Too many write calls by this caller; try again in 2 s"),
    "idp-unavailable": (503, "Keycloak signing keys are unreachable and this key is not cached"),
    "cluster-unreachable": (503, "CRC did not answer"),
    "capacity-service-unavailable": (503, "cmapi-capacity cannot be reached"),
    "git-unavailable": (502, "The Git host answered 500"),
    "validator-unavailable": (503, "kubeconform did not start"),
    "validator-busy": (503, "The policy check is busy: 1 running and 4 waiting in this pod; try again in 15 s"),
    "internal-error": (500, "The service failed. Give the X-Request-Id of this answer to the platform team"),
    "docs-assets-missing": (503, "The Swagger UI bundle is not in /opt/app-root/static"),
}


# What each problem status means, in one sentence: the first line of its response in Swagger UI and ReDoc (#480, S7).
# The codes of the status follow it, and each code is one named example (S8).
PROBLEM_STATUS_TEXT: dict[int, str] = {
    400: "A header or a parameter that cmapi reads first is missing or not valid.",
    401: "No token, or the token is not valid.",
    403: "The caller may not do this, or not in this environment.",
    404: "What the path names is not known.",
    409: "It conflicts with the current state of the object, of an open request or of the Idempotency-Key.",
    412: "No strong tag that If-Match lists is the object's ETag: it changed since it was read, or the value named none.",
    413: "The request content is larger than this instance reads; `maxBytes` says how many bytes it reads. Nothing was done.",
    422: "The request breaks a rule. `code` says which; a policy refusal lists each item in `errors`.",
    428: "A change needs If-Match with the ETag of the object as it was read; `*` is not one.",
    429: "Too many calls by this caller in the bucket that `x-cmapi-rate-limit` names, or too many new requests for the "
         "team. Wait for the seconds in `Retry-After`, which `retryAfter` repeats. Nothing was done.",
    500: "The service failed.",
    502: "The Git host failed.",
    503: "A service that cmapi depends on is not answering. Try again later; `retryAfter`, when present, says when.",
}

# The success answer of a write that opens a request (status 202), unless the route says otherwise.
WRITE_ACCEPTED = ("The request is created. It waits for approval unless a policy approves it at once: `status` and "
                  "`approval` say which, and `links.events` follows it.")
DRY_RUN_RETURNS = ("Dry run (`?dryRun=true`): the plan. The call opens no change request, takes no lock or reservation, "
                   "queues no job and opens no pull request.")

# A read that answers 304 to a matching If-None-Match, and 412 to a false If-Match (core/etag.py, not_modified, #590), passed
# to read() as **CONDITIONAL_READ; FastAPI merges it into the operation (openapi_extra). RFC 9110, 15.4.5: a 304 "cannot
# contain content", and it repeats the ETag of the 200. The 412's example is replaced by the recorded one
# (add_recorded_examples) when contract/samples.json has it.
ETAG_HEADER = {"ETag": {"description": "The strong ETag of this answer, to send back in If-None-Match.",
                        "schema": {"type": "string"}}}
# An ETag of a read is 32 hex characters (etag_of); the examples have that form.
READ_ETAG_EXAMPLE = "1f774baf9bf093f8d4ebc497eb0d5b96"
READ_PRECONDITION_FAILED = Problem(412, "precondition-failed", STALE_READ, extra={"etag": READ_ETAG_EXAMPLE})
CONDITIONAL_READ: dict[str, Any] = {
    "parameters": [{"name": "If-None-Match", "in": "header", "required": False,
                    "description": "The ETag of the answer the caller holds. If it is still the current one, the answer is "
                                   "304 with no body.",
                    "schema": {"type": "string", "examples": [f'"{READ_ETAG_EXAMPLE}"']}},
                   {"name": "If-Match", "in": "header", "required": False,
                    "description": "Optional on a read. The answer is sent only if one strong tag listed here is its "
                                   "current ETag, or if the value is `*`; otherwise it is 412 `precondition-failed`, with "
                                   "the current tag in `etag`. A weak tag (`W/\"...\"`) never matches. If-Match is read "
                                   "before If-None-Match (RFC 9110, section 13.2.2). Send the tags in one comma-separated "
                                   "If-Match field (`If-Match: \"a\", \"b\"`): the front door answers 400 to a second "
                                   "If-Match line.",
                    "schema": {"type": "string", "examples": [f'"{READ_ETAG_EXAMPLE}"']}}],
    "responses": {"200": {"headers": ETAG_HEADER},
                  "304": {"description": "Not modified: the ETag in If-None-Match is still the current one. Use the answer "
                                         "you hold; this one has no body.", "headers": ETAG_HEADER},
                  "412": {"description": f"{PROBLEM_STATUS_TEXT[412]}\n\nCodes: `precondition-failed`.",
                          "content": {"application/problem+json": {
                              "schema": {"$ref": "#/components/schemas/ProblemDetail"},
                              "examples": {"precondition-failed": {"value": READ_PRECONDITION_FAILED.body()}}}}}},
}


def takes_validated_input(op: dict[str, Any]) -> bool:
    """Whether FastAPI checks an input of the operation, so it can answer 422 validation-failed: a body, or a parameter.
    If-None-Match and If-Match do not count: the conditional reads take them from the raw request and compare them, never
    refuse them as input (core/etag.py, not_modified), and a write's If-Match is a plain optional string (routers/__init__.py,
    if_match) that core/pipeline.py checks."""
    params = [p for p in op.get("parameters") or () if p.get("name") not in ("If-None-Match", "If-Match")]
    return bool(params or op.get("requestBody"))


# A route's 403 examples name the route's own permission, in the words of core/authz.py's refusal (RolePolicy.require).
PERMISSION_DETAILS: dict[str, str] = {
    "forbidden": "Missing permission {permission}: no role in your token grants it (roles: ['cmapi-requester'])",
    "environment-forbidden": "Your roles grant {permission} only in ['rnd'], not dev",
}


# The fields beyond `detail` that a problem carries where cmapi raises it, so its example shows them too: each 503 says
# when to try again (core/auth.py Jwks.key, core/registry.py cache, core/pipeline.py).
PROBLEM_EXTRAS: dict[str, dict[str, Any]] = {
    "idp-unavailable": {"retryAfter": 30},
    "cluster-unreachable": {"retryAfter": 30},
    "validator-unavailable": {"retryAfter": 60},
    "validator-busy": {"retryAfter": 15},     # CMAPI_VALIDATOR_WAIT_SECONDS, here its default (core/validate, #708)
    "rate-limited": {"retryAfter": 2},
    "folder-holds-submodule": {"paths": ["clusters/CRC/namespaces/payments-dev/vendor"]},
    # instance.yaml http.maxRequestBodyBytes, here its default (core/http_settings.py, #683)
    "content-too-large": {"maxBytes": DEFAULT_MAX_REQUEST_BODY_BYTES},
    "folder-not-utf8": {"paths": ["clusters/CRC/namespaces/payments-dev/caf\\xe9.yaml"]},
    "folder-not-yaml": {"paths": ["clusters/CRC/namespaces/payments-dev/namespace.yaml"]},
    "several-resource-quotas": {"resourceQuotas": ["payments-dev-objects", "payments-dev-quota"]},
    # the instance that serves qa, from instance.yaml directory (core/config.py environment_not_served, #671)
    "environment-not-served": {"instanceUrl": "https://cmapi-staging.ephico2real.com",
                               "portalUrl": "https://portal-staging.ephico2real.com"},
}


def problem_example(code: str, permission: str | None = None) -> dict[str, Any]:
    status, detail = PROBLEMS[code]
    if permission is not None and code in PERMISSION_DETAILS:
        detail = PERMISSION_DETAILS[code].format(permission=permission)
    return Problem(status, code, detail, extra=dict(PROBLEM_EXTRAS.get(code, {}))).body()


PROBLEM_SCHEMA: dict[str, str] = {"$ref": "#/components/schemas/ProblemDetail"}


def problem_description(status: int, codes: Sequence[str]) -> str:
    """The description of a problem response: what the status means, then its codes, each a named example."""
    return f"{PROBLEM_STATUS_TEXT[status]}\n\nCodes: " + ", ".join(f"`{c}`" for c in codes) + "."


def problem_responses(codes: Sequence[str], permission: str | None = None) -> dict[int | str, dict[str, Any]]:
    """One response for each status, with the one media type that cmapi answers a problem with (RFC 9457, section 3).

    The schema is written here as a reference and not passed as FastAPI's `model`: FastAPI puts a model under the media type
    of the route's response class, application/json, which no problem of cmapi has (#179).
    """
    by_status: dict[int, list[str]] = {}
    for c in codes:
        names = by_status.setdefault(PROBLEMS[c][0], [])
        if c not in names:
            names.append(c)
    out: dict[int | str, dict[str, Any]] = {}
    for status, names in sorted(by_status.items()):
        out[status] = {"description": problem_description(status, names),
                       "content": {"application/problem+json": {
                           "schema": PROBLEM_SCHEMA, "examples": {n: {"value": problem_example(n, permission)} for n in names}}}}
    return out


def add_problem(op: dict[str, Any], code: str) -> None:
    """Declare one more problem code on an operation of the document: its status's response, its named example and its
    description, after the codes that the route declared."""
    status = str(PROBLEMS[code][0])
    # Copies, level by level: FastAPI puts the route's own dicts in the document, and every app of the process shares them.
    # Each other field of the response (a header, an x- field) stays as the route declared it.
    response = dict(op["responses"].get(status) or {})
    content = dict(response.get("content") or {})
    content.pop("application/json", None)                     # FastAPI's own 422 (HTTPValidationError): main.py answers a problem
    media = dict(content.get("application/problem+json") or {"schema": PROBLEM_SCHEMA})
    examples = dict(media.get("examples") or {})
    examples.setdefault(code, {"value": problem_example(code)})
    media["examples"] = examples
    content["application/problem+json"] = media
    response["content"] = content
    response["description"] = problem_description(int(status), list(examples))
    op["responses"][status] = response
    op["responses"] = dict(sorted(op["responses"].items()))      # Swagger UI and ReDoc list them in this order


# ReDoc's navigation groups, in docs/01's order. A tag outside every group is not displayed by ReDoc at all
# (https://redocly.com/docs/api-reference-docs/specification-extensions/x-tag-groups), so a router must name one.
TAG_GROUPS: tuple[str, ...] = ("Namespaces and metadata", "Access", "Capacity and placement", "Requests and approvals",
                               "Operations", "Admin")


# The "core" plugin has two routers (routers/me.py and routers/health.py), so its metadata is here, once.
CORE: dict[str, str] = {"version": __version__, "group": "Operations",
                        "description": "The instance itself: who the caller is and what the caller can do, the clusters "
                                       "that the instance knows, the rules of a new namespace's labels and annotations, "
                                       "and the version of the running build."}


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def refuse_dry_run(request: Request) -> None:
    """The guard of a write that has no dry run (#606). FastAPI ignores a query parameter that a route does not declare, so
    without it `?dryRun=true` would do the action. Any `dryRun` is refused, whatever its value, as the Kubernetes API server
    refuses one on a call that cannot honour it (apiserver, endpoints/handlers/rest.go, ConnectResource and isDryRun)."""
    if "dryRun" in request.query_params:
        raise Problem.bad_request("dry-run-not-supported", PROBLEMS["dry-run-not-supported"][1])


def refuse_repeated_dry_run(request: Request) -> None:
    """The guard of a write that has a dry run (#607 review). FastAPI binds a scalar query parameter to one value, the last
    (Starlette's QueryParams), so `dryRun=true&dryRun=false` ran the write. More than one `dryRun` is not one Boolean, so it is
    the 422 `validation-failed` that `dryRun=maybe` gets, in the same form. Kubernetes also answers 422 Invalid to a dryRun
    value that a call does not accept (apiserver, endpoints/handlers/create.go, ValidateCreateOptions and errors.NewInvalid)."""
    if len(request.query_params.getlist("dryRun")) > 1:
        raise Problem(422, "validation-failed", "The request is not valid: query.dryRun: send it at most once",
                      [{"field": "query.dryRun", "message": "send it at most once", "code": "too_many_values"}])


class DocumentedRouter(APIRouter):
    """An APIRouter whose routes must say what they need and what they can refuse."""

    def __init__(self, plugin: str, *, version: str, description: str, group: str, prefix: str = "",
                 tags: list[str] | None = None, **kw: Any):
        if group not in TAG_GROUPS:
            raise RuntimeError(f"plugin {plugin}: group {group!r} is not one of {TAG_GROUPS}")
        if not description.strip():
            raise RuntimeError(f"plugin {plugin}: no description")
        super().__init__(prefix=prefix, tags=tags or [plugin], **kw)
        self.plugin = plugin
        self.version = version
        self.plugin_description = description
        self.group = group

    def _register(self, method: str, path: str, *, summary: str, permission: str | None, problems: Sequence[str],
                  response_model: Any, status_code: int, returns: str, extra: dict[str, Any], media_type: str | None = None,
                  dry_run_model: Any = None) -> Callable:
        unknown = [p for p in problems if p not in PROBLEMS]
        if unknown:
            raise RuntimeError(f"{self.plugin} {method} {path}: unregistered problems {unknown}")
        if not returns.strip():
            # The success response's description; FastAPI's own is "Successful Response", which says nothing (#480, S7).
            raise RuntimeError(f"{self.plugin} {method} {path}: no `returns`, the description of the {status_code} answer")
        codes = list(problems)
        if permission is not None:
            codes = ["unauthenticated", "forbidden", *codes]
        # A write without a dry run refuses one (#606), and a write with one refuses it repeated (#607 review). The router's
        # sign-in (main.py, include_router) runs first, so a call without a token is 401. The guard follows it, before the
        # endpoint's own dependencies: the permission (403), the Idempotency-Key, If-Match and the action. A body that is not
        # JSON is 422 before both, because FastAPI decodes the body before it solves any dependency.
        guarded = method in WRITE_METHODS and dry_run_model is None
        single = method in WRITE_METHODS and dry_run_model is not None
        if guarded:
            codes.append("dry-run-not-supported")
        if single and "validation-failed" not in codes:
            codes.append("validation-failed")

        def deco(fn: Callable) -> Callable:
            desc = inspect.getdoc(fn) or ""
            if not desc:
                raise RuntimeError(f"{self.plugin} {method} {path}: route {fn.__name__} has no docstring")
            if permission:
                desc += f"\n\n**Requires** `{permission}`."
            op_id = f"{self.plugin}_{fn.__name__}"
            responses = problem_responses(codes, permission)
            x: dict[str, Any] = {"x-cmapi-permission": permission, "x-cmapi-plugin": self.plugin,
                                 "x-plugin-version": self.version, **extra}
            kwargs: dict[str, Any] = dict(summary=summary, description=desc, response_model=response_model,
                                          status_code=status_code, operation_id=op_id, responses=responses,
                                          response_description=returns, openapi_extra=x)
            if guarded:
                kwargs["dependencies"] = [Depends(refuse_dry_run)]
            elif single:
                kwargs["dependencies"] = [Depends(refuse_repeated_dry_run)]
            if media_type:
                # A streamed body (CSV): declared by media type, since it has no JSON model. The response class with no media
                # type of its own stops FastAPI from adding application/json beside it (#179).
                responses[status_code] = {"description": returns, "content": {media_type: {"schema": {"type": "string"}}}}
                x["x-cmapi-media-type"] = media_type
                kwargs["response_class"] = Response
            if dry_run_model is not None:
                responses[200] = {"model": dry_run_model, "description": DRY_RUN_RETURNS}
            # A GET answers HEAD on its own route (#605), declared here where the route is made. Since FastAPI 0.137.0 each
            # app that includes this router serves this route object, so HEAD added per app reached the other apps of the
            # process (main.py, _serve_head_with_get; #654 review).
            return self.api_route(path, methods=[method, "HEAD"] if method == "GET" else [method], **kwargs)(fn)

        return deco

    def read(self, path: str, *, summary: str, permission: str | None, returns: str, problems: Sequence[str] = (),
             response_model: Any = None, method: str = "GET", media_type: str | None = None, **extra: Any) -> Callable:
        """`returns` describes the 200 answer: what the caller gets back."""
        if response_model is None and media_type is None:
            raise RuntimeError(f"{self.plugin} {method} {path}: a read needs a response_model or a media_type")
        return self._register(method, path, summary=summary, permission=permission, problems=problems,
                              response_model=response_model, status_code=200, returns=returns, extra=extra,
                              media_type=media_type)

    def write(self, path: str, *, summary: str, permission: str, problems: Sequence[str] = (),
              response_model: Any, method: str = "POST", status_code: int = 202, dry_run_model: Any = None,
              returns: str | None = None, **extra: Any) -> Callable:
        """`dry_run_model` is the model of the 200 that the route answers with `dryRun=true` (docs/01: "200 Plan for dry runs").
        `returns` describes the success answer; a write that opens a request (202) has WRITE_ACCEPTED unless it says more."""
        if returns is None:
            returns = WRITE_ACCEPTED if status_code == 202 else ""
        return self._register(method, path, summary=summary, permission=permission, problems=problems,
                              response_model=response_model, status_code=status_code, returns=returns, extra=extra,
                              dry_run_model=dry_run_model)


def _undocumented_fields(model: type[BaseModel], seen: set[type]) -> list[str]:
    if model in seen:
        return []
    seen.add(model)
    out: list[str] = []
    for name, f in model.model_fields.items():
        if not f.description:
            out.append(f"{model.__name__}.{name}: no description")
        if f.examples is None and f.is_required():
            # nested models carry their own examples per field; a plain required scalar needs one
            if not (inspect.isclass(f.annotation) and issubclass(f.annotation, BaseModel)) and \
                    not _is_model_list(f.annotation):
                out.append(f"{model.__name__}.{name}: no example")
        for sub in _models_in(f.annotation):
            out.extend(_undocumented_fields(sub, seen))
    return out


def _is_model_list(annotation: Any) -> bool:
    return bool(_models_in(annotation))


def _models_in(annotation: Any) -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        found.append(annotation)
    for arg in getattr(annotation, "__args__", ()) or ():
        found.extend(_models_in(arg))
    return found


def api_routes(app: FastAPI) -> list[RouteContext]:
    """Every APIRoute that the app serves, as FastAPI's RouteContext: the path, methods, dependencies and handler that it
    is served with, including the prefix and dependencies of the router that includes it.

    FastAPI 0.137.0 stopped copying an included router's routes into app.routes: "Now `router.routes` is no longer a plain
    list of `APIRoute` objects, it can contain these intermediate objects that can contain additional routers, forming a
    tree" (https://fastapi.tiangolo.com/release-notes/, 0.137.0, read 2026-11-24). A walk of app.routes for APIRoute saw
    the app's own routes only. iter_route_contexts (0.137.2) is the walk that FastAPI's author gave for it
    (https://github.com/fastapi/fastapi/discussions/15782, 2026-06-17), and the one that FastAPI's get_openapi uses."""
    return [r for r in iter_route_contexts(app.routes) if isinstance(r.original_route, APIRoute)]


def check_documented(app: FastAPI) -> None:
    """Refuse to start when any /api route or its models is not fully described."""
    problems: list[str] = []
    seen: set[type] = set()
    for route in api_routes(app):
        if not route.path.startswith("/api/"):
            continue
        if not route.summary:
            problems.append(f"{route.path}: no summary")
        if not route.description:
            problems.append(f"{route.path}: no description")
        if route.response_model is None and not (route.openapi_extra or {}).get("x-cmapi-media-type"):
            problems.append(f"{route.path}: no response model")
        else:
            for m in _models_in(route.response_model):
                problems.extend(_undocumented_fields(m, seen))
        if route.body_field is not None:
            for m in _models_in(route.body_field.field_info.annotation):
                problems.extend(_undocumented_fields(m, seen))
        for response in route.responses.values():            # the 200 of a dry run
            for m in _models_in(response.get("model")):
                problems.extend(_undocumented_fields(m, seen))
        problems.extend(_undocumented_parameters(route))
    if problems:
        raise RuntimeError("undocumented API:\n  " + "\n  ".join(sorted(set(problems))))


def _undocumented_parameters(route: RouteContext) -> list[str]:
    """Each path, query and header parameter of the route, its sub-dependencies included, without a description or an example."""
    out: list[str] = []
    stack, seen = [route.dependant], set()
    while stack:
        dep = stack.pop()
        if id(dep) in seen:
            continue
        seen.add(id(dep))
        stack.extend(dep.dependencies)
        for place, params in (("path", dep.path_params), ("query", dep.query_params), ("header", dep.header_params)):
            for p in params:
                info = p.field_info
                if not info.description:
                    out.append(f"{route.path}: {place} parameter {p.alias}: no description")
                if not info.examples:
                    out.append(f"{route.path}: {place} parameter {p.alias}: no example")
    return out


def problem_type(code: str) -> str:
    return BASE + code


def plugin_routers(routers: Sequence[APIRouter]) -> dict[str, DocumentedRouter]:
    """One entry per plugin among the routers the app includes: a plugin that is not included is not in the spec."""
    out: dict[str, DocumentedRouter] = {}
    for r in routers:
        if not isinstance(r, DocumentedRouter):
            continue
        first = out.setdefault(r.plugin, r)
        if (first.version, first.plugin_description, first.group) != (r.version, r.plugin_description, r.group):
            raise RuntimeError(f"plugin {r.plugin}: two routers disagree on its version, description or group")
    return out


def _example_of(schema: dict[str, Any], components: dict[str, Any], depth: int = 0) -> Any:
    """A sample value for a schema, from the examples the models carry. None when the schema gives nothing to go on."""
    if "$ref" in schema:
        schema = components[schema["$ref"].rsplit("/", 1)[1]]
    if schema.get("examples"):
        return schema["examples"][0]
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key) or ():
            if sub.get("type") != "null":
                value = _example_of(sub, components, depth)
                if value is not None:
                    return value
    if schema.get("type") == "object" or "properties" in schema:
        if depth > 4:
            return None
        out = {}
        for name, sub in (schema.get("properties") or {}).items():
            value = _example_of(sub, components, depth + 1)
            if value is not None:
                out[name] = value
        return out or None
    if schema.get("type") == "array" and "items" in schema:
        value = _example_of(schema["items"], components, depth + 1)
        return [value] if value is not None else None
    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    return None


def sample_request(method: str, path: str, op: dict[str, Any], components: dict[str, Any], base_url: str) -> dict[str, Any]:
    """The request a curl sample makes: method, url, headers and body, with each parameter at its documented example."""
    url, query, headers = path, [], []
    if op.get("security"):
        headers.append(("Authorization", "Bearer $TOKEN"))
    for p in op.get("parameters") or ():
        example = p["example"] if "example" in p else _example_of(p.get("schema") or {}, components)
        if p["in"] == "path":
            url = url.replace("{" + p["name"] + "}", str(example))
        elif p["in"] == "header" and (p.get("required") or (method != "get" and p["name"] in ("Idempotency-Key", "If-Match"))):
            # A write is refused without these two. A read's If-Match is an optional condition (CONDITIONAL_READ): not sent.
            headers.append((p["name"], str(example)))
        elif p["in"] == "query" and p.get("required"):
            query.append(f"{p['name']}={example}")
    body = None
    content = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
    if content:
        # The media type's example is a whole body (OpenAPI 3.1, Media Type Object: it "SHALL override the example provided
        # by the schema"): the recorded request, with this instance's labels and annotations (#334), which "Try it out"
        # sends too. A body put together from each property's first example can pair fields that refuse each other, as
        # limitRange with a named tier (#349), so it is only for an operation that no run recorded.
        if "example" in content:
            body = content["example"]
        elif content.get("examples"):
            body = next(iter(content["examples"].values()))["value"]      # the first named example (create, #479)
        else:
            body = _example_of(content.get("schema") or {}, components)
        if body is None:
            body = {}
        headers.append(("Content-Type", "application/json"))
    return {"method": method.upper(), "url": base_url.rstrip("/") + url + ("?" + "&".join(query) if query else ""),
            "headers": headers, "body": body}


# The base URL of the samples when instance.yaml has no publicUrl (main.py): a shell variable, like $TOKEN.
URL_VARIABLE = "$CMAPI_URL"


def curl_sample(request: dict[str, Any]) -> str:
    """The sample as one curl command. $CMAPI_URL and $TOKEN stay for the shell to fill, so they are the parts in double
    quotes; everything else is quoted as it is."""
    url = request["url"]
    if url.startswith(URL_VARIABLE + "/"):
        target = f'"{URL_VARIABLE}"' + shlex.quote(url[len(URL_VARIABLE):])
    else:
        target = shlex.quote(url)
    parts = ["curl", "-X", request["method"], target]
    for name, value in request["headers"]:
        header = f"{name}: {value}"
        parts += ["-H", f'"{header}"' if "$TOKEN" in value else shlex.quote(header)]
    if request["body"] is not None:
        parts += ["-d", shlex.quote(json.dumps(request["body"]))]
    return " ".join(parts)


@dataclass(frozen=True)
class InstanceFacts:
    """What the namespace contract reads from the instance beyond metadata-keys.yaml (#479): the target of the create
    example, and the expiration rules of each served environment."""
    name: str                       # instance.yaml name: the value of a value.from instance key
    cluster: str                    # the cluster_id path parameter's example
    environment: str                # that cluster's environment, or the first served one (main.py, example_environment)
    environments: tuple[str, ...]   # served, in instance.yaml's order
    expiration: Any                 # plugins/expiration/rules.py ExpirationRules


class _WithoutHead(RouteContext):
    """The route as the document shows it: a GET's HEAD (main.py, _serve_head_with_get, #605) is not an operation of its own.
    RFC 9110 section 9.3.2 defines HEAD as GET without content, and FastAPI's author on the same question: "it should
    handle HEAD requests automatically for GET requests, without adding them to the OpenAPI schema"
    (https://github.com/fastapi/fastapi/issues/1773, 2020-08-11). FastAPI's get_openapi writes one operation per method
    of a route (openapi/utils.py, get_openapi_path), so the document gets a view of the route without HEAD; the served
    route keeps it. get_openapi takes a RouteContext as it is (routing.py, iter_route_contexts), and this one differs from
    the served one in its methods only."""

    @property
    def methods(self) -> set[str] | None:
        methods = super().methods
        return methods - {"HEAD"} if methods and {"GET", "HEAD"} <= methods else methods


def _without_head(route: RouteContext) -> RouteContext:
    return _WithoutHead(*(getattr(route, f.name) for f in fields(route)))


def build_openapi(app: FastAPI, plugins: dict[str, DocumentedRouter], base_url: str, problem_base: str = BASE,
                  metadata: Any = None, instance: InstanceFacts | None = None) -> dict[str, Any]:
    """The OpenAPI 3.1 document: FastAPI's, plus the tag descriptions, ReDoc's x-tagGroups, and a curl sample per operation.

    The routes declare their problem examples at import, with the default type base. `problem_base` is the base of this
    instance (instance.yaml `problems.typeBase`), so each example shows the type that this instance answers. `metadata`
    (core/metadata.py) is this instance's metadata-keys.yaml: the labels and annotations of a namespace say its keys.
    `instance` names the create example's target and gives expiresAt its rules (#479)."""
    tags = [{"name": name, "description": r.plugin_description, "x-plugin-version": r.version}
            for name, r in sorted(plugins.items())]
    spec = get_openapi(title=app.title, version=app.version, openapi_version=app.openapi_version, description=app.description,
                       routes=[_without_head(r) for r in iter_route_contexts(app.routes)], tags=tags,
                       servers=app.servers)
    spec["x-tagGroups"] = [{"name": g, "tags": names} for g in TAG_GROUPS
                           if (names := [n for n, r in sorted(plugins.items()) if r.group == g])]
    if metadata is not None:
        # Before the curl samples, which take the body from the examples that this sets (#334).
        _document_metadata(spec, metadata, instance)
    if instance is not None:
        _document_expiry(spec, instance)
    _document_validation_problem(spec)
    _document_body_limit_problem(spec)
    _document_token_problems(spec)
    _document_rate_limit_problem(spec)
    _document_retry_after(spec)
    _document_if_match_required(spec)
    # Before the curl samples, which send the recorded body of each write (#349).
    samples = load_samples()
    add_recorded_examples(spec, samples, metadata, instance)
    _document_create_examples(spec, instance)
    _document_patch_examples(spec, samples, metadata)
    if metadata is not None:
        # After the recorded examples: the sample was recorded on the reference file, and this instance's own rules are the
        # answer that it gives (the defect of #334, for GET /api/v1/metadata-keys; #336).
        _document_metadata_keys_example(spec, metadata, instance)
    components = (spec.get("components") or {}).get("schemas") or {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            op["x-codeSamples"] = [{"lang": "Shell", "label": "curl",
                                    "source": curl_sample(sample_request(method, path, op, components, base_url))}]
    return spec if problem_base == BASE else _with_type_base(spec, problem_base)


def metadata_description(keys: Any, kind: str) -> str:
    """The keys of one kind, from metadata-keys.yaml (#215): the same rules that the plan checks."""
    rules = keys.rules[kind]
    def listed(items):
        return "; ".join(f"`{k}` ({r.text(keys.email_domains)})" for k, r in items) or "none"
    required = [(k, r) for k, r in rules.items() if r.required and not r.derived]
    extra = [(k, r) for k, r in rules.items() if not r.required]
    derived = [(k, r) for k, r in rules.items() if r.derived]
    other = keys.allow_other[kind]
    prefixes = ", ".join(f"`{p}/`" if p else "no prefix" for p in other.prefixes) or "none"
    # What JSON Schema cannot say (a count of keys, a size in bytes) is said here, beside the schema (#328).
    sizes = (f", each value at most {other.max_value_bytes} bytes and all of them at most {other.max_bytes_total} bytes "
             "in UTF-8") if kind == "annotation" else ""
    parts = [f"Required: {listed(required)}.", f"Optional: {listed(extra)}.",
             f"Any other key with {prefixes}, at most {other.max}{sizes}."]
    if derived:
        parts.append(f"Required, and filled in by cmapi when a request leaves them out: {listed(derived)}. A request may "
                     "send the same value, never another.")
    return " ".join(parts)


def metadata_example(keys: Any, kind: str, sources: dict[str, str] | None = None) -> dict[str, str]:
    """What a create sends for one kind (#479, A6): each required key at its example, each filled-in key at its value
    for `sources` (the example's target), each optional key that has an example, then allowOther.example, so the
    example shows that extra keys go in the same map. A key with no value to show is left out."""
    sources = sources or {}
    out: dict[str, str] = {}
    for key, rule in keys.rules[kind].items():
        if rule.derived:
            if sources.get(rule.derived):
                out[key] = sources[rule.derived]
        elif rule.example is not None:
            out[key] = str(rule.example)
    out.update(keys.allow_other[kind].example)
    return out


def metadata_patch_example(keys: Any, kind: str) -> dict[str, str] | None:
    """What a patch of one kind sends in the document: the first optional key with an example, or nothing (#334). A
    key whose value is the start of the namespace name is passed over: the example would depend on the namespace."""
    for key, rule in keys.rules[kind].items():
        if not rule.required and not rule.derived and not rule.namespace_prefix and rule.example is not None:
            return {key: str(rule.example)}
    return None


def metadata_merge_patch(keys: Any) -> dict[str, dict[str, str | None]]:
    """The labels and annotations of a merge patch that this instance accepts (#485): the first key with an example is
    removed (null), and the next key of the other kind, or another of the same, is set. The keys are the instance's own:
    an optional key with an example, then each allowOther.example key. Empty when the instance gives no example to build
    from."""
    found: list[tuple[str, str, str]] = []
    for kind in ("label", "annotation"):
        example = metadata_patch_example(keys, kind)
        found += [(kind, key, value) for key, value in (example or {}).items()]
    for kind in ("label", "annotation"):
        found += [(kind, key, value) for key, value in keys.allow_other[kind].example.items()]
    if not found:
        return {}
    maps: dict[str, dict[str, str | None]] = {"labels": {}, "annotations": {}}
    field = {"label": "labels", "annotation": "annotations"}
    kind, key, _ = found[0]
    maps[field[kind]][key] = None
    for kind, key, value in found[1:]:
        if key not in maps[field[kind]]:
            maps[field[kind]][key] = value
            break
    return {name: sent for name, sent in maps.items() if sent}


def _accepted_patch(keys: Any, body: dict[str, Any]) -> bool:
    """Check a patch for an existing namespace: absent required keys may stay absent, but a patch cannot remove one."""
    return not keys.validate(body.get("labels") or {}, body.get("annotations") or {}, operator=False,
                             existing=True)


def example_namespace(keys: Any, default: str, environment: str | None = None) -> str:
    """The namespace of the create example, `<prefix>-<desired name>-<environment>` (#479, A3): the default's last
    "-" part is the environment when a key ends the name (namespaceSuffix), and the namespacePrefix key's example and
    "-" start it, so the example body is one that this instance accepts (#334)."""
    name = default
    if keys.suffix_key() is not None and environment:
        name = f"{default.rsplit('-', 1)[0]}-{environment}"
    found = keys.prefix_key()
    if found is not None and keys.rules[found[0]][found[1]].example is not None:
        name = f"{keys.rules[found[0]][found[1]].example}-{name}"
    return name


def example_sources(namespace: str, instance: InstanceFacts | None) -> dict[str, str]:
    """The target of the create example, from which its filled-in keys take their values."""
    if instance is None:
        return {"namespace": namespace}
    return {"namespace": namespace, "environment": instance.environment, "cluster": instance.cluster,
            "instance": instance.name}


def namespace_description(keys: Any) -> str | None:
    """The rule of the namespace name in words, when keys start or end it (#479, A3), or None."""
    prefix, suffix = keys.prefix_key(), keys.suffix_key()
    if prefix is None and suffix is None:
        return None
    shape, rules = "<desired name>", []
    if prefix is not None:
        shape = f"<{prefix[1]}>-{shape}"
        rules.append(f'starts with the value of {prefix[1]} and "-"')
    if suffix is not None:
        shape = f"{shape}-<{suffix[1]}>"
        rules.append(f'ends with "-" and the value of {suffix[1]}')
    forms = f"`{shape}`"
    if prefix is not None and suffix is not None:
        forms += f" or `<{prefix[1]}>-<{suffix[1]}>` for a team-wide namespace"
    return (f"The name is {forms}, at most 63 characters: it {' and '.join(rules)}. cmapi refuses another name with "
            "invalid_value on that key.")


def _document_metadata(spec: dict[str, Any], keys: Any, instance: InstanceFacts | None = None) -> None:
    """The labels and annotations of NamespaceCreate and NamespacePatch are this instance's keys and rules, as schema
    (MetadataKeys.json_schema, #328) and in words beside it, with examples that this instance accepts (#334)."""
    schemas = spec.get("components", {}).get("schemas", {})
    create = schemas.get("NamespaceCreate") or {}
    names = (create.get("properties") or {}).get("namespace", {}).get("examples") or ["payments-dev"]
    environment = instance.environment if instance else None
    sources = example_sources(example_namespace(keys, names[0], environment), instance)
    _document_plan_metadata(schemas, keys, sources)
    for name, op, prefix in (("NamespaceCreate", "create", ""), ("NamespacePatch", "patch", "Merge patch; null removes a key. ")):
        model = schemas.get(name) or {}
        props = model.get("properties") or {}
        for field, kind in (("labels", "label"), ("annotations", "annotation")):
            if field not in props:
                continue
            schema = keys.json_schema(kind, op)
            words = {"title": props[field].get("title", field.capitalize()),
                     "description": prefix + metadata_description(keys, kind)}
            if op == "create":
                props[field] = {**schema, **words, "examples": [metadata_example(keys, kind, sources)]}
                if schema.get("required") and field not in model.setdefault("required", []):
                    # A map that is left out is an empty one, which the plan refuses for its required keys.
                    model["required"].append(field)
            else:
                props[field] = {"anyOf": [schema, {"type": "null"}], **words,
                                "examples": [metadata_patch_example(keys, kind)]}
        if op == "create" and "namespace" in props:
            _document_namespace(props["namespace"], keys, environment)


def _document_plan_metadata(schemas: dict[str, Any], keys: Any, sources: dict[str, str]) -> None:
    """PlanMetadata's examples (#479, A7): the dry run of the create example sent without the keys that cmapi fills in
    (value.from, default.from), so they show each source with this instance's own keys and values (D10)."""
    props = (schemas.get("PlanMetadata") or {}).get("properties")
    if not props:
        return
    sent = {}
    for kind in ("label", "annotation"):
        rules = keys.rules[kind]
        sent[kind] = {k: v for k, v in metadata_example(keys, kind, sources).items()
                      if k not in rules or not (rules[k].derived or rules[k].default_from)}
    values = keys.value_sources(sent["label"], sent["annotation"], keys.filled(sent["label"], sent["annotation"], sources))
    props["namespace"]["examples"] = [sources["namespace"]]
    props["labels"]["examples"] = [values["label"]]
    props["annotations"]["examples"] = [values["annotation"]]


def _document_namespace(prop: dict[str, Any], keys: Any, environment: str | None) -> None:
    """NamespaceCreate.namespace: the keys that start and end it, as x-cmapi-prefix-from and x-cmapi-suffix-from, its
    rule in words, and an example made of the keys' examples and the example's environment (#479, A3)."""
    prop["examples"] = [example_namespace(keys, ex, environment) for ex in prop.get("examples") or []]
    words = namespace_description(keys)
    if words is None:
        return
    prop["description"] = f"{prop.get('description', '').rstrip('.')}. {words}"
    if keys.prefix_key() is not None:
        prop["x-cmapi-prefix-from"] = keys.prefix_key()[1]
    if keys.suffix_key() is not None:
        prop["x-cmapi-suffix-from"] = keys.suffix_key()[1]


def _document_expiry(spec: dict[str, Any], instance: InstanceFacts) -> None:
    """NamespaceCreate.expiresAt (#479, A11): its rules in words and, per served environment, as x-cmapi-expiration,
    from this instance's expiration.yaml, so the portal's calendar reads its limits from the contract."""
    prop = ((spec.get("components", {}).get("schemas", {}).get("NamespaceCreate") or {}).get("properties") or {}).get("expiresAt")
    if prop is None:
        return
    view = instance.expiration.contract_view(list(instance.environments))
    on = [env for env, rules in view["environments"].items() if rules.get("allowedAtCreate")]
    later = [env for env, rules in view["environments"].items() if rules["enabled"] and not rules["allowedAtCreate"]]
    off = [env for env, rules in view["environments"].items() if not rules["enabled"]]
    words = ["Optional: the day the namespace expires, after today. Left out, the namespace is permanent."]
    if on:
        words.append(f"Taken in {', '.join(on)}: past maxLifetimeDays from creation (x-cmapi-expiration) it needs one "
                     "more approver-platform approval.")
    if later:
        words.append(f"Refused with expiration-not-allowed at create in {', '.join(later)}.")
    if off:
        words.append(f"Refused with expiration-not-allowed in {', '.join(off)}, where expiration is off.")
    words.append("Never in prod.")
    prop["description"] = " ".join(words)
    prop["x-cmapi-expiration"] = view


def _document_create_examples(spec: dict[str, Any], instance: InstanceFacts | None) -> None:
    """The create's example target and body (#479, A6, §5.2). Its cluster_id is the example's cluster, one that this
    instance writes to. Its body is two named examples: "permanent" first, which "Try it out" and the curl sample send,
    and "withExpiry" with expiresAt where the example's environment takes a date at create. That date is fixed, so the
    document stays the same from day to day; its summary says to choose a future date."""
    op = spec["paths"].get("/api/v1/clusters/{cluster_id}/namespaces", {}).get("post")
    if not op or not instance:
        return
    for parameter in op.get("parameters", []):
        if parameter["in"] == "path" and parameter["name"] == "cluster_id":
            parameter["schema"]["examples"] = [instance.cluster]
    media = op["requestBody"]["content"]["application/json"]
    if "example" not in media:
        return
    permanent = dict(media.pop("example"))
    permanent.pop("expiresAt", None)
    examples = {"permanent": {"summary": "Permanent namespace", "value": permanent}}
    env = instance.environment
    if instance.expiration.allows(env) and instance.expiration.rules(env).allowed_at_create:
        dates = spec["components"]["schemas"]["NamespaceCreate"]["properties"]["expiresAt"]["examples"]
        examples["withExpiry"] = {"summary": "With expiration (choose a future date when sending)",
                                  "value": {**permanent, "expiresAt": dates[0]}}
    media["examples"] = examples


PATCH_OPERATION = "namespaces_update_namespace"


def _document_patch_examples(spec: dict[str, Any], samples: dict[str, Any], keys: Any) -> None:
    """The change's body as two named examples (#485): "mergePatch" first, which "Try it out" and the curl sample send, is
    the recorded dry run, a merge patch that sets a key and removes one with null, with this instance's own keys when it
    refuses the recorded ones; "tier" is the recorded change that opens a request. Both are bodies that a run sent."""
    op = next((op for ops in spec["paths"].values() for op in ops.values()
               if isinstance(op, dict) and op.get("operationId") == PATCH_OPERATION), None)
    checked = samples.get("operations", {}).get(f"{PATCH_OPERATION}:dryRun")
    media = ((op or {}).get("requestBody") or {}).get("content", {}).get("application/json")
    if media is None or checked is None or "example" not in media:
        return
    patch = dict(checked["request"]["body"])
    if keys is not None and not _accepted_patch(keys, patch):
        built = metadata_merge_patch(keys)
        patch = {**{k: v for k, v in patch.items() if k not in ("labels", "annotations")}, **built}
        if not built or not _accepted_patch(keys, patch):
            return
    media["examples"] = {
        "mergePatch": {"summary": "Change labels and annotations: a value sets a key, null removes it (add dryRun=true to "
                                  "check)", "value": patch},
        "tier": {"summary": "Change the tier", "value": media.pop("example")}}


def metadata_keys_view(keys: Any, expiration: Any, environments: Sequence[str]) -> dict[str, Any]:
    """The body of GET /api/v1/metadata-keys: the schemas of NamespaceCreate's labels and annotations (#336), and the
    x-cmapi-expiration of its expiresAt (#479, D15), so a form reads every rule it shows from one answer and one ETag."""
    return {**keys.keys_view(), "x-cmapi-expiration": expiration.contract_view(list(environments))}


def _document_metadata_keys_example(spec: dict[str, Any], keys: Any, instance: InstanceFacts | None = None) -> None:
    """The 200 example of GET /api/v1/metadata-keys is this instance's answer, not the recorded one of the reference file."""
    for ops in spec["paths"].values():
        for op in ops.values():
            if isinstance(op, dict) and op.get("operationId") == "core_metadata_keys":
                media = op["responses"]["200"].setdefault("content", {}).setdefault("application/json", {})
                media["example"] = (metadata_keys_view(keys, instance.expiration, instance.environments) if instance
                                    else keys.keys_view())


def _with_type_base(node: Any, problem_base: str) -> Any:
    """A copy of the document with each problem type URI on `problem_base`."""
    if isinstance(node, dict):
        return {k: _with_type_base(v, problem_base) for k, v in node.items()}
    if isinstance(node, list):
        return [_with_type_base(v, problem_base) for v in node]
    if isinstance(node, str) and node.startswith(BASE):
        return problem_base + node[len(BASE):]
    return node


def _document_validation_problem(spec: dict[str, Any]) -> None:
    """Each operation with a parameter or a body can answer 422 validation-failed (main.py turns FastAPI's own refusal into the
    problem). So FastAPI's HTTPValidationError leaves the document, and the 422 of each such operation names validation-failed."""
    for ops in spec["paths"].values():
        for op in ops.values():
            if isinstance(op, dict) and takes_validated_input(op):
                add_problem(op, "validation-failed")
    schemas = spec.get("components", {}).get("schemas", {})
    schemas.setdefault("ProblemDetail", _without_none(ProblemDetail.model_json_schema()))
    for name in ("HTTPValidationError", "ValidationError"):
        schemas.pop(name, None)


def _document_body_limit_problem(spec: dict[str, Any]) -> None:
    """Each operation with a request body can answer 413 content-too-large (main.py, RequestBodyLimitMiddleware, #683). Any
    request whose content passes the limit gets it, but only an operation that takes a body has content to send."""
    for ops in spec["paths"].values():
        for op in ops.values():
            if isinstance(op, dict) and op.get("requestBody"):
                add_problem(op, "content-too-large")


def _document_token_problems(spec: dict[str, Any]) -> None:
    """Each operation that takes a token can answer what the token check answers (core/auth.py, #480): 401
    unauthenticated, and 503 idp-unavailable when Keycloak's signing keys cannot be read and the token's key is not cached.
    The check is a dependency of the whole router (main.py, api_app), so the document's `security` says which operations."""
    for ops in spec["paths"].values():
        for op in ops.values():
            if isinstance(op, dict) and op.get("security"):
                add_problem(op, "unauthenticated")
                add_problem(op, "idp-unavailable")


def _document_rate_limit_problem(spec: dict[str, Any]) -> None:
    """Each operation that takes a token can answer 429 rate-limited (routers/__init__.py, rate_limit, #689): the rate
    limit is a dependency of the same routers as the token check (main.py, api_app), so `security` says which operations.
    `x-cmapi-rate-limit` names the caller's bucket that the operation takes from (core/ratelimit.py, rate_class)."""
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if isinstance(op, dict) and op.get("security"):
                add_problem(op, "rate-limited")
                op["x-cmapi-rate-limit"] = rate_class(method, path)


# The problem codes that carry retryAfter, which main.py's problem_response sends as Retry-After too (#689).
RETRY_AFTER_CODES = frozenset(code for code, extra in PROBLEM_EXTRAS.items() if "retryAfter" in extra)


def _document_retry_after(spec: dict[str, Any]) -> None:
    """The Retry-After header of each problem response with a code that carries retryAfter (RFC 9110, section 10.2.3):
    required when each code of the response carries it, as on a 429, else sent with the codes that do."""
    for ops in spec["paths"].values():
        for op in ops.values():
            if not isinstance(op, dict):
                continue
            for status, response in list(op.get("responses", {}).items()):
                examples = (response.get("content") or {}).get("application/problem+json", {}).get("examples") or {}
                carrying = [c for c in examples if c in RETRY_AFTER_CODES]
                if not carrying:
                    continue
                every = len(carrying) == len(examples)
                when = "" if every else " Sent with " + ", ".join(f"`{c}`" for c in carrying) + "."
                header = {"description": f"The seconds to wait before the next call: the same number as `retryAfter`.{when}",
                          "required": every, "schema": {"type": "integer", "minimum": 1}}
                op["responses"][status] = {**response, "headers": {**(response.get("headers") or {}), "Retry-After": header}}


# The five writes whose route requires If-Match (plugins/namespaces/router.py): the change, the delete and the three
# expiry writes. A create takes none.
IF_MATCH_OPERATIONS = frozenset({"namespaces_update_namespace", "namespaces_delete_namespace", "namespaces_extend",
                                 "namespaces_set_expiry", "namespaces_make_permanent"})


def _document_if_match_required(spec: dict[str, Any]) -> None:
    """If-Match is required on the five writes of IF_MATCH_OPERATIONS (#586). The runtime parameter keeps
    `Header(default=None)` (routers/__init__.py, if_match), so that a namespace missing from Git answers 404 before 428, as
    RFC 9110 section 13.2.1 orders a precondition after the resource; FastAPI's own check of a required header would answer
    422 before the route runs. So only the document says what the route enforces, and a generated client cannot leave it
    out. Another operation's If-Match keeps what its route declares.

    OpenAPI 3.1.0, Parameter Object: `required` "Determines whether this parameter is mandatory" (default false). A
    header that is sent has a string value, never null, so the schema drops the null of `str | None` and keeps the string
    with each of its rules (a maxLength or a pattern, when the route declares one)."""
    for ops in spec["paths"].values():
        for op in ops.values():
            if not isinstance(op, dict) or op.get("operationId") not in IF_MATCH_OPERATIONS:
                continue
            for param in op.get("parameters") or ():
                if param.get("in") != "header" or param.get("name") != "If-Match":
                    continue
                schema = param["schema"]
                variants = schema.pop("anyOf", None)
                if variants is not None:
                    strings = [v for v in variants if v != {"type": "null"}]
                    if len(variants) != 2 or len(strings) != 1:
                        raise RuntimeError(f"{op['operationId']}: If-Match is not declared as `str | None`: {variants}")
                    schema.update(strings[0])
                if schema.get("type") != "string":
                    raise RuntimeError(f"{op['operationId']}: If-Match is not a string: {schema}")
                param["required"] = True


def _without_none(value: Any) -> Any:
    """A schema as FastAPI writes each model of the document: it leaves out a key whose value is None (`default: null`).
    No route passes ProblemDetail to FastAPI as a model (problem_responses), so this function gives it the same form."""
    if isinstance(value, dict):
        return {k: _without_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_without_none(v) for v in value]
    return value


def load_samples() -> dict[str, Any]:
    """The request and the response of each operation from a run of the service suite (tests/service/test_api_samples.py)."""
    return json.loads(resources.files("cmapi.contract").joinpath("samples.json").read_text())


def add_recorded_examples(spec: dict[str, Any], samples: dict[str, Any], metadata: Any = None,
                          instance: InstanceFacts | None = None) -> None:
    """Put the recorded samples into the document as examples, so Swagger UI, ReDoc and docs/04 show the same payloads.

    A success goes in as the media type's `example`. A recorded problem replaces the synthesized example of its code.
    The dry run of a write is keyed `<operationId>:dryRun` and fills that operation's 200.

    The service suite records on the reference metadata-keys.yaml. `metadata` is this instance's: the create body's
    namespace, labels and annotations are this instance's examples (#479, A6), and a recorded patch body whose labels
    or annotations it refuses gets this instance's example instead, so the body that Swagger UI's "Try it out" sends is
    one that this instance accepts (#334).
    """
    by_id = {op["operationId"]: op for ops in spec["paths"].values() for op in ops.values()
             if isinstance(op, dict) and "operationId" in op}
    for key, sample in samples.get("operations", {}).items():
        op = by_id.get(key.split(":")[0])
        if op is None:
            continue
        request, response = sample["request"], sample["response"]
        body_content = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
        if body_content is not None and "body" in request and ":" not in key:    # the body of the write, not of its dry run
            body = request["body"]
            if metadata is not None and isinstance(body, dict):
                body = _with_instance_metadata(body, (body_content.get("schema") or {}).get("$ref", ""), metadata, instance)
            body_content["example"] = body
        declared = op["responses"].setdefault(str(response["status"]), {"description": "Successful Response"})
        media = declared.setdefault("content", {}).setdefault(response["contentType"] or "application/json", {})
        media["example"] = response["body"]
    # A problem that more than one operation answers is recorded once for each (operationProblems), so the operation shows
    # its own answer: the 422 of a change names the keys of a change, not those of a create.
    for sample in [*samples.get("problems", {}).values(), *samples.get("operationProblems", {}).values()]:
        code = sample["response"]["body"]["code"]
        op = by_id.get(sample["operationId"])
        examples = (((op or {}).get("responses", {}).get(str(sample["response"]["status"])) or {})
                    .get("content", {}).get("application/problem+json", {}).get("examples"))
        if examples is not None and code in examples:
            examples[code] = {"value": sample["response"]["body"]}


def _with_instance_metadata(body: dict[str, Any], schema_ref: str, keys: Any,
                            instance: InstanceFacts | None = None) -> dict[str, Any]:
    """A recorded namespace body with this instance's metadata. A create always takes the instance's examples (#479,
    A6); a patch is checked only for what it sends, since the namespace's required keys are in Git, and takes the
    instance's example only when its own is refused."""
    name = schema_ref.rsplit("/", 1)[-1]
    if name == "NamespaceCreate":
        return _create_example(body, keys, instance)
    if name != "NamespacePatch" or not ({"labels", "annotations"} & set(body)):
        return body
    if not keys.validate(body.get("labels") or {}, body.get("annotations") or {}, operator=False, require_governed=False):
        return body
    out = dict(body)
    for field, kind in (("labels", "label"), ("annotations", "annotation")):
        example = metadata_patch_example(keys, kind)
        if example is None:
            out.pop(field, None)
        else:
            out[field] = example
    return out


def _create_example(body: dict[str, Any], keys: Any, instance: InstanceFacts | None) -> dict[str, Any]:
    """The recorded create body with the namespace, labels and annotations made from this instance's configuration
    (#479, A3, A6). expiresAt is left out: the suite and "Try it out" send this body, and a fixed date stops being one
    that cmapi takes once it has passed."""
    out = dict(body)
    namespace = example_namespace(keys, body.get("namespace") or "payments-dev", instance.environment if instance else None)
    sources = example_sources(namespace, instance)
    out["namespace"] = namespace
    out["labels"] = metadata_example(keys, "label", sources)
    out["annotations"] = metadata_example(keys, "annotation", sources)
    return out
