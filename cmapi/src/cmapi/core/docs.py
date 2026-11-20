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
from dataclasses import dataclass
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
    "internal-error": (500, "The service failed. Give the X-Request-Id of this answer to the platform team"),
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
                                       "that the instance knows, the rules of a new namespace's labels and annotations, "
                                       "and the version of the running build."}


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


def curl_sample(request: dict[str, Any]) -> str:
    """The sample as one curl command. $TOKEN stays for the shell to fill, so it is the one part in double quotes."""
    parts = ["curl", "-X", request["method"], shlex.quote(request["url"])]
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
                       routes=app.routes, tags=tags, servers=app.servers)
    spec["x-tagGroups"] = [{"name": g, "tags": names} for g in TAG_GROUPS
                           if (names := [n for n, r in sorted(plugins.items()) if r.group == g])]
    if metadata is not None:
        # Before the curl samples, which take the body from the examples that this sets (#334).
        _document_metadata(spec, metadata, instance)
    if instance is not None:
        _document_expiry(spec, instance)
    _document_validation_problem(spec)
    # Before the curl samples, which send the recorded body of each write (#349).
    add_recorded_examples(spec, load_samples(), metadata, instance)
    _document_create_examples(spec, instance)
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
    return (f"The name is `{shape}`, at most 63 characters: it {' and '.join(rules)}. cmapi refuses another name with "
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
    for code, sample in samples.get("problems", {}).items():
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
