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
from importlib import resources
from typing import Any, Callable, Sequence

from fastapi import APIRouter, FastAPI, Response
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic import BaseModel

from cmapi import __version__
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
    "rate-limited": (429, "Too many requests"),
    "idp-unavailable": (503, "Keycloak signing keys are unreachable and none are cached"),
    "cluster-unreachable": (503, "CRC did not answer"),
    "capacity-service-unavailable": (503, "cmapi-capacity cannot be reached"),
    "git-unavailable": (502, "The Git host answered 500"),
    "validator-unavailable": (503, "kubeconform did not start"),
    "docs-assets-missing": (503, "The Swagger UI bundle is not in /opt/app-root/static"),
}


def problem_example(code: str) -> dict[str, Any]:
    status, detail = PROBLEMS[code]
    return Problem(status, code, detail).body()


PROBLEM_SCHEMA: dict[str, str] = {"$ref": "#/components/schemas/ProblemDetail"}


def problem_responses(codes: Sequence[str]) -> dict[int | str, dict[str, Any]]:
    """One response for each status, with the one media type that cmapi answers a problem with (RFC 9457, section 3).

    The schema is written here as a reference and not passed as FastAPI's `model`: FastAPI puts a model under the media type
    of the route's response class, application/json, which no problem of cmapi has (#179).
    """
    by_status: dict[int, list[str]] = {}
    for c in codes:
        by_status.setdefault(PROBLEMS[c][0], []).append(c)
    out: dict[int | str, dict[str, Any]] = {}
    for status, names in sorted(by_status.items()):
        out[status] = {"description": ", ".join(names),
                       "content": {"application/problem+json": {
                           "schema": PROBLEM_SCHEMA, "examples": {n: {"value": problem_example(n)} for n in names}}}}
    return out


# ReDoc's navigation groups, in docs/01's order. A tag outside every group is not displayed by ReDoc at all
# (https://redocly.com/docs/api-reference-docs/specification-extensions/x-tag-groups), so a router must name one.
TAG_GROUPS: tuple[str, ...] = ("Namespaces and metadata", "Access", "Capacity and placement", "Requests and approvals",
                               "Operations", "Admin")


# The "core" plugin has two routers (routers/me.py and routers/health.py), so its metadata is here, once.
CORE: dict[str, str] = {"version": __version__, "group": "Operations",
                        "description": "The instance itself: who the caller is and what the caller can do, the clusters "
                                       "that the instance knows, and the version of the running build."}


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
                  response_model: Any, status_code: int, extra: dict[str, Any], media_type: str | None = None,
                  dry_run_model: Any = None) -> Callable:
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
            responses = problem_responses(codes)
            x: dict[str, Any] = {"x-cmapi-permission": permission, "x-cmapi-plugin": self.plugin,
                                 "x-plugin-version": self.version, **extra}
            kwargs: dict[str, Any] = dict(summary=summary, description=desc, response_model=response_model,
                                          status_code=status_code, operation_id=op_id, responses=responses,
                                          openapi_extra=x)
            if media_type:
                # A streamed body (CSV): declared by media type, since it has no JSON model. The response class with no media
                # type of its own stops FastAPI from adding application/json beside it (#179).
                responses[status_code] = {"description": f"The body as {media_type}",
                                          "content": {media_type: {"schema": {"type": "string"}}}}
                x["x-cmapi-media-type"] = media_type
                kwargs["response_class"] = Response
            if dry_run_model is not None:
                responses[200] = {"model": dry_run_model,
                                  "description": "The plan, with `dryRun=true`. cmapi writes nothing and opens no request."}
            return self.api_route(path, methods=[method], **kwargs)(fn)

        return deco

    def read(self, path: str, *, summary: str, permission: str | None, problems: Sequence[str] = (),
             response_model: Any = None, method: str = "GET", media_type: str | None = None, **extra: Any) -> Callable:
        if response_model is None and media_type is None:
            raise RuntimeError(f"{self.plugin} {method} {path}: a read needs a response_model or a media_type")
        return self._register(method, path, summary=summary, permission=permission, problems=problems,
                              response_model=response_model, status_code=200, extra=extra, media_type=media_type)

    def write(self, path: str, *, summary: str, permission: str, problems: Sequence[str] = (),
              response_model: Any, method: str = "POST", status_code: int = 202, dry_run_model: Any = None,
              **extra: Any) -> Callable:
        """`dry_run_model` is the model of the 200 that the route answers with `dryRun=true` (docs/01: "200 Plan for dry runs")."""
        return self._register(method, path, summary=summary, permission=permission, problems=problems,
                              response_model=response_model, status_code=status_code, extra=extra,
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
        if route.response_model is None and not (route.openapi_extra or {}).get("x-cmapi-media-type"):
            problems.append(f"{route.path}: no response model")
        else:
            for m in _models_in(route.response_model):
                problems.extend(_undocumented_fields(m, seen))
        if route.body_field is not None:
            for m in _models_in(route.body_field.type_):
                problems.extend(_undocumented_fields(m, seen))
        for response in route.responses.values():            # the 200 of a dry run
            for m in _models_in(response.get("model")):
                problems.extend(_undocumented_fields(m, seen))
        problems.extend(_undocumented_parameters(route))
    if problems:
        raise RuntimeError("undocumented API:\n  " + "\n  ".join(sorted(set(problems))))


def _undocumented_parameters(route: APIRoute) -> list[str]:
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
        elif p["in"] == "header" and (p.get("required") or p["name"] in ("Idempotency-Key", "If-Match")):
            headers.append((p["name"], str(example)))
        elif p["in"] == "query" and p.get("required"):
            query.append(f"{p['name']}={example}")
    body = None
    content = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
    if content:
        body = _example_of(content.get("schema") or {}, components)
        if body is None:
            body = {}
        headers.append(("Content-Type", "application/json"))
    return {"method": method.upper(), "url": base_url.rstrip("/") + url + ("?" + "&".join(query) if query else ""),
            "headers": headers, "body": body}


def curl_sample(request: dict[str, Any]) -> str:
    """The sample as one curl command. $TOKEN stays for the shell to fill, so it is the one part in double quotes."""
    parts = ["curl", "-X", request["method"], shlex.quote(request["url"])]
    for name, value in request["headers"]:
        header = f"{name}: {value}"
        parts += ["-H", f'"{header}"' if "$TOKEN" in value else shlex.quote(header)]
    if request["body"] is not None:
        parts += ["-d", shlex.quote(json.dumps(request["body"]))]
    return " ".join(parts)


def build_openapi(app: FastAPI, plugins: dict[str, DocumentedRouter], base_url: str, problem_base: str = BASE) -> dict[str, Any]:
    """The OpenAPI 3.1 document: FastAPI's, plus the tag descriptions, ReDoc's x-tagGroups, and a curl sample per operation.

    The routes declare their problem examples at import, with the default type base. `problem_base` is the base of this
    instance (instance.yaml `problems.typeBase`), so each example shows the type that this instance answers."""
    tags = [{"name": name, "description": r.plugin_description, "x-plugin-version": r.version}
            for name, r in sorted(plugins.items())]
    spec = get_openapi(title=app.title, version=app.version, openapi_version=app.openapi_version, description=app.description,
                       routes=app.routes, tags=tags, servers=app.servers)
    spec["x-tagGroups"] = [{"name": g, "tags": names} for g in TAG_GROUPS
                           if (names := [n for n, r in sorted(plugins.items()) if r.group == g])]
    components = (spec.get("components") or {}).get("schemas") or {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            op["x-codeSamples"] = [{"lang": "Shell", "label": "curl",
                                    "source": curl_sample(sample_request(method, path, op, components, base_url))}]
    _document_validation_problem(spec)
    add_recorded_examples(spec, load_samples())
    return spec if problem_base == BASE else _with_type_base(spec, problem_base)


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
    problem = PROBLEM_SCHEMA
    for ops in spec["paths"].values():
        for op in ops.values():
            if not isinstance(op, dict) or not (op.get("parameters") or op.get("requestBody")):
                continue
            declared = op["responses"].get("422") or {}
            examples = dict((declared.get("content") or {}).get("application/problem+json", {}).get("examples") or {})
            examples.setdefault("validation-failed", {"value": problem_example("validation-failed")})
            names = [n for n in (declared.get("description") or "").split(", ") if n in PROBLEMS]
            if "validation-failed" not in names:
                names.append("validation-failed")
            op["responses"]["422"] = {"description": ", ".join(names),
                                      "content": {"application/problem+json": {"schema": problem, "examples": examples}}}
    schemas = spec.get("components", {}).get("schemas", {})
    schemas.setdefault("ProblemDetail", _without_none(ProblemDetail.model_json_schema()))
    for name in ("HTTPValidationError", "ValidationError"):
        schemas.pop(name, None)


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


def add_recorded_examples(spec: dict[str, Any], samples: dict[str, Any]) -> None:
    """Put the recorded samples into the document as examples, so Swagger UI, ReDoc and docs/04 show the same payloads.

    A success goes in as the media type's `example`. A recorded problem replaces the synthesized example of its code.
    The dry run of a write is keyed `<operationId>:dryRun` and fills that operation's 200.
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
            body_content["example"] = request["body"]
        declared = op["responses"].setdefault(str(response["status"]), {"description": "Successful Response"})
        media = declared.setdefault("content", {}).setdefault(response["contentType"] or "application/json", {})
        media["example"] = response["body"]
    for code, sample in samples.get("problems", {}).items():
        op = by_id.get(sample["operationId"])
        examples = (((op or {}).get("responses", {}).get(str(sample["response"]["status"])) or {})
                    .get("content", {}).get("application/problem+json", {}).get("examples"))
        if examples is not None and code in examples:
            examples[code] = {"value": sample["response"]["body"]}
