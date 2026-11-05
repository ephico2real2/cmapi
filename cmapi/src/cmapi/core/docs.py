"""The documentation layer (docs/01, "API documentation"): a route that is not fully described
does not start.

Routes register through DocumentedRouter.read() and .write(), which take the summary, the
permission, the problems the route can raise and the response model, and fill in the OpenAPI
pieces the code already knows: operationId from plugin and function, the "Requires" line, the
problem responses with one example each, the 202 shape for writes. check_documented(app) runs at
startup and refuses any /api route without a summary, a description, a response model, or a model
field without a description and an example.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Sequence

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from cmapi.core.errors import BASE, Problem
from cmapi.core.models import ProblemDetail

# Every problem code a route may declare, with its status and an example detail (docs/02, API contract).
PROBLEMS: dict[str, tuple[int, str]] = {
    "unauthenticated": (401, "Bearer token required"),
    "forbidden": (403, "Missing permission namespaces:create"),
    "environment-forbidden": (403, "Your roles grant namespaces:create only in ['rnd'], not dev"),
    "cluster-not-found": (404, "Unknown cluster OCP_X"),
    "object-not-found": (404, "No request req-20261105-0001"),
    "change-pending": (409, "req-20261105-0001 holds payments-dev"),
    "namespace-exists": (409, "payments-dev is already in Git"),
    "namespace-exists-unmanaged": (409, "payments-dev exists on the cluster and is not managed by cmapi"),
    "not-pending": (409, "req-20261105-0001 is synced"),
    "invalid-transition": (409, "cancel is not allowed in state merged"),
    "already-approved": (409, "This person already approved the request"),
    "self-approval": (409, "Requesters cannot approve their own request here"),
    "nothing-to-prune": (409, "No delete of payments-dev is awaiting a prune"),
    "idempotency-replay": (409, "Idempotency-Key was used for a different request"),
    "precondition-failed": (412, "The namespace changed in Git since you read it"),
    "validation-failed": (422, "Request body is not valid"),
    "policy-violation": (422, "Metadata refused"),
    "capacity-exceeded": (422, "memory would exceed the cluster"),
    "environment-not-served": (422, "qa is served by the staging instance"),
    "cluster-not-writable": (422, "CRC is imported but has no clusters.yaml entry"),
    "reserved-namespace": (422, "kube-tools is reserved"),
    "invalid-namespace-name": (422, "Not a DNS-1123 label"),
    "no-change": (422, "The request changes nothing"),
    "identity-incomplete": (422, "The token has no employee_id claim"),
    "unknown-user": (422, "1009 is not an enabled user"),
    "invalid-team-dl": (422, "x@other.com is not an address in ['ephico2real.com']"),
    "expiration-not-allowed": (422, "Production namespaces never expire"),
    "expiration-limit": (422, "An extension is at most 30 days"),
    "on-behalf-of-not-allowed": (422, "A person calls as themselves"),
    "on-behalf-of-required": (422, "A service client must name the person"),
    "not-eligible": (403, "Not in an approving group still needed"),
    "precondition-required": (428, "If-Match is required on a change"),
    "idempotency-key-required": (400, "Idempotency-Key header is required on writes"),
    "invalid-cursor": (400, "The cursor is not valid"),
    "invalid-sort": (400, "Unknown sort used2"),
    "invalid-limit": (400, "limit is one of (25, 50, 100), at most 200"),
    "rate-limited": (429, "Too many requests"),
    "idp-unavailable": (503, "Keycloak signing keys are unreachable and none are cached"),
    "cluster-unreachable": (503, "CRC did not answer"),
    "capacity-service-unavailable": (503, "cmapi-capacity cannot be reached"),
    "git-unavailable": (502, "The Git host answered 500"),
}


def problem_example(code: str) -> dict[str, Any]:
    status, detail = PROBLEMS[code]
    return Problem(status, code, detail).body()


def problem_responses(codes: Sequence[str]) -> dict[int | str, dict[str, Any]]:
    by_status: dict[int, list[str]] = {}
    for c in codes:
        by_status.setdefault(PROBLEMS[c][0], []).append(c)
    out: dict[int | str, dict[str, Any]] = {}
    for status, names in sorted(by_status.items()):
        out[status] = {"model": ProblemDetail, "description": ", ".join(names),
                       "content": {"application/problem+json": {
                           "examples": {n: {"value": problem_example(n)} for n in names}}}}
    return out


class DocumentedRouter(APIRouter):
    """An APIRouter whose routes must say what they need and what they can refuse."""

    def __init__(self, plugin: str, *, prefix: str = "", tags: list[str] | None = None, **kw: Any):
        super().__init__(prefix=prefix, tags=tags or [plugin], **kw)
        self.plugin = plugin

    def _register(self, method: str, path: str, *, summary: str, permission: str | None, problems: Sequence[str],
                  response_model: Any, status_code: int, extra: dict[str, Any]) -> Callable:
        unknown = [p for p in problems if p not in PROBLEMS]
        if unknown:
            raise RuntimeError(f"{self.plugin} {method} {path}: unregistered problems {unknown}")
        codes = list(problems)
        if permission is not None:
            codes = ["unauthenticated", "forbidden", *codes]

        def deco(fn: Callable) -> Callable:
            desc = inspect.getdoc(fn) or ""
            if not desc:
                raise RuntimeError(f"{self.plugin} {method} {path}: route {fn.__name__} has no docstring")
            if permission:
                desc += f"\n\n**Requires** `{permission}`."
            op_id = f"{self.plugin}_{fn.__name__}"
            kwargs: dict[str, Any] = dict(summary=summary, description=desc, response_model=response_model,
                                          status_code=status_code, operation_id=op_id,
                                          responses=problem_responses(codes),
                                          openapi_extra={"x-cmapi-permission": permission, "x-cmapi-plugin": self.plugin,
                                                         **extra})
            return self.api_route(path, methods=[method], **kwargs)(fn)

        return deco

    def read(self, path: str, *, summary: str, permission: str | None, problems: Sequence[str] = (),
             response_model: Any, method: str = "GET", **extra: Any) -> Callable:
        return self._register(method, path, summary=summary, permission=permission, problems=problems,
                              response_model=response_model, status_code=200, extra=extra)

    def write(self, path: str, *, summary: str, permission: str, problems: Sequence[str] = (),
              response_model: Any, method: str = "POST", status_code: int = 202, **extra: Any) -> Callable:
        return self._register(method, path, summary=summary, permission=permission, problems=problems,
                              response_model=response_model, status_code=status_code, extra=extra)


def _undocumented_fields(model: type[BaseModel], seen: set[type]) -> list[str]:
    if model in seen:
        return []
    seen.add(model)
    out: list[str] = []
    for name, f in model.model_fields.items():
        if not f.description:
            out.append(f"{model.__name__}.{name}: no description")
        if f.examples is None and f.default is None and not f.is_required() and f.default_factory is None:
            pass
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


def check_documented(app: FastAPI) -> None:
    """Refuse to start when any /api route or its models is not fully described."""
    problems: list[str] = []
    seen: set[type] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if not route.summary:
            problems.append(f"{route.path}: no summary")
        if not route.description:
            problems.append(f"{route.path}: no description")
        if route.response_model is None:
            problems.append(f"{route.path}: no response model")
        else:
            for m in _models_in(route.response_model):
                problems.extend(_undocumented_fields(m, seen))
        if route.body_field is not None:
            for m in _models_in(route.body_field.type_):
                problems.extend(_undocumented_fields(m, seen))
    if problems:
        raise RuntimeError("undocumented API:\n  " + "\n  ".join(sorted(set(problems))))


def problem_type(code: str) -> str:
    return BASE + code
