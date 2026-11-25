"""The API documentation standard (#480; docs/reviews/2026-11-20-issue-479/implementation_plan.md, section 3): every
operation of the document meets S1 to S10, so Swagger UI and ReDoc show each one in the same format.

The documents are the ones that the reference instance serves (`cmapi-tools openapi render`, no database): on the
reference metadata-keys.yaml, which test_the_committed_contract_is_the_document_this_code_serves holds equal to
cmapi/contract/openapi.json, on the company keys of the namespace design, and on the design's own keys. Each check is
one row of CHECKS: a function that returns one failure line per gap, such as "GET /api/v1/kpi: 200 says nothing of what
it returns ('Successful Response')". The second test breaks the create operation once per check and holds the check to its failure, so a check
that can never fail is caught too.

Two more tests hold the document to sources outside it: what each route declares (FastAPI's document before
build_openapi adds to it), and the create operation's answers in the design's section 5.4. The last section holds what
each operation can answer to the code that answers it (the review of #503).

S9 is also the renderers' settings; test_api_docs.py checks that /docs and /redoc are served with them.
"""
from __future__ import annotations

import copy
import json
import re
import shlex
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml
from fastapi import FastAPI
from metadata_corpus import SchemaReader
from test_namespace_contract_479 import DESIGN

from cmapi.core.docs import (IF_MATCH_OPERATIONS, PROBLEM_STATUS_TEXT, PROBLEMS, WRITE_ACCEPTED, DocumentedRouter,
                             problem_description, takes_validated_input)
from cmapi.core.models import Health
from cmapi.main import api_app, openapi_document
from cmapi.tools.openapi import cluster_environments, load

# The reference file of the committed contract, the company keys of the namespace design (#479, section 3.1), and the
# design's own keys, the one of the three with a namespace suffix and a default (x-cmapi-suffix-from, x-cmapi-default-from).
POLICIES = Path(__file__).resolve().parents[3] / "examples/cluster-configs/policies"
CREATE = ("post", "/api/v1/clusters/{cluster_id}/namespaces")
FASTAPI_DEFAULT = "Successful Response"
MEDIA_TYPES = ("application/json", "text/csv")
SCALARS = ("string", "integer", "number", "boolean")
# S1: a summary starts with what the caller does. A new kind of operation adds its verb here.
VERBS = {"Approve", "Cancel", "Change", "Confirm", "Create", "Delete", "Export", "Extend", "Get", "Give", "List", "Pause",
         "Probe", "Reject", "Remove", "Resume", "Retry", "Revert", "Search"}
# S3: the operations that need a token and no permission (GET /me is how a caller finds out what it may do).
TOKEN_ONLY = {("get", "/api/v1/me")}
# S7: the reads that answer 304 to a matching If-None-Match (routers/me.py, plugins/capacity/router.py).
CONDITIONAL_READS = {("get", "/api/v1/metadata-keys"), ("get", "/api/v1/capacity")}
# S10: the headers that a write is refused without, so a sample that "runs as written" carries them even where the
# document cannot mark them required: 400 idempotency-key-required (optional only on a dry run), 428 precondition-required.
# A conditional read's If-Match is optional (#590), so a read's sample does not send it.
REFUSED_WITHOUT = ("Idempotency-Key", "If-Match")
Op = dict[str, Any]


@pytest.fixture(scope="module", params=["metadata-keys.yaml", "metadata-keys.company.yaml", "design"])
def cfg(request, tmp_path_factory) -> Any:
    path = POLICIES / request.param
    if request.param == "design":
        path = tmp_path_factory.mktemp("design") / "metadata-keys.yaml"
        path.write_text(yaml.safe_dump(DESIGN))
    return load(path, None)


@pytest.fixture(scope="module")
def spec(cfg) -> dict[str, Any]:
    return openapi_document(cfg, cluster_environments(cfg, None))


@pytest.fixture(scope="module")
def declared(cfg) -> dict[str, Any]:
    """The document as FastAPI writes it from the routes alone, before build_openapi adds to it: what each route declares."""
    app, _ = api_app(cfg, cfg.raw_instance["instance"]["auth"]["issuer"], cluster_environments=cluster_environments(cfg, None))
    return FastAPI.openapi(app)


def operations(spec: dict[str, Any]):
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            yield method, path, op


def problem_codes(response: dict[str, Any]) -> dict[str, Any]:
    """The named examples of a problem response: one for each code."""
    return ((response.get("content") or {}).get("application/problem+json") or {}).get("examples") or {}


def schema_of(schema: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """A schema with its $ref followed."""
    ref = schema.get("$ref")
    return spec["components"]["schemas"][ref.rsplit("/", 1)[1]] if ref else schema


def has_type(schema: dict[str, Any]) -> bool:
    if "type" in schema or "$ref" in schema or "const" in schema:
        return True
    return any(has_type(sub) for key in ("anyOf", "oneOf", "allOf") for sub in schema.get(key) or ())


# ---------------------------------------------------------------- the checks, one per item of the standard

def check_summary(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S1: a summary, a short phrase with no final stop, and a description that says what the operation does."""
    out = []
    summary = op.get("summary") or ""
    if not summary or len(summary) > 60 or summary.endswith("."):
        out.append(f"summary {summary!r} is not a phrase of at most 60 characters with no final stop")
    if summary.partition(" ")[0] not in VERBS:
        out.append(f"summary {summary!r} does not start with a verb of VERBS")
    if len(op.get("description") or "") < 40:
        out.append("description says too little (under 40 characters)")
    return out


def check_tag(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S2: one tag, the plugin's, in exactly one x-tagGroups group."""
    tags = op.get("tags") or []
    if len(tags) != 1 or tags[0] != op.get("x-cmapi-plugin"):
        return [f"tags {tags} are not the one tag of its plugin {op.get('x-cmapi-plugin')}"]
    groups = [g["name"] for g in spec.get("x-tagGroups", []) if tags[0] in g["tags"]]
    return [] if len(groups) == 1 else [f"tag {tags[0]} is in the groups {groups}, not in exactly one"]


def check_permission(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S3: the permission in x-cmapi-permission and in the description; a token-only route says 401 and 503."""
    out = []
    permission, secured = op.get("x-cmapi-permission"), bool(op.get("security"))
    schemes = (spec.get("components") or {}).get("securitySchemes") or {}
    for requirement in op.get("security") or ():
        out.extend(f"names the security scheme {name}, which the document does not define"
                   for name in requirement if name not in schemes)
    if secured and permission is None and (method, path) not in TOKEN_ONLY:
        out.append("takes a token and names no x-cmapi-permission")
    codes = {s: set(((r.get("content") or {}).get("application/problem+json") or {}).get("examples") or ())
             for s, r in op["responses"].items()}
    if permission is not None:
        if not secured:
            out.append(f"needs {permission} and has no security scheme")
        if not (op.get("description") or "").endswith(f"**Requires** `{permission}`."):
            out.append(f"description does not end with **Requires** `{permission}`.")
        if "forbidden" not in codes.get("403", set()):
            out.append("needs a permission and has no 403 forbidden")
    if secured:
        for status, code in (("401", "unauthenticated"), ("503", "idp-unavailable")):
            if code not in codes.get(status, set()):
                out.append(f"takes a token and has no {status} {code}, which the token check answers")
    elif "401" in op["responses"]:
        out.append("takes no token and declares 401")
    return out


def check_parameters(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S4: each parameter with a description, its location, a required flag, a type and an example."""
    out = []
    for p in op.get("parameters") or ():
        name, schema = f"{p.get('in')} parameter {p.get('name')}", p.get("schema") or {}
        if not p.get("description"):
            out.append(f"{name} has no description")
        if p.get("in") not in ("path", "query", "header") or not isinstance(p.get("required"), bool):
            out.append(f"{name} has no location or no required flag")
        if p.get("in") == "path" and p.get("required") is not True:
            out.append(f"{name} is a path parameter that is not required")
        if not has_type(schema):
            out.append(f"{name} has no type")
        if not (schema.get("examples") or p.get("examples") or "example" in p):
            out.append(f"{name} has no example")
        # S4 asks for the rule and an example: an example that the rule refuses documents a call that answers 422.
        shown = [*(schema.get("examples") or ()), *([p["example"]] if "example" in p else ()),
                 *(e.get("value") for e in (p.get("examples") or {}).values())]
        validator = SchemaReader().validator({**schema, "components": spec["components"]})
        out.extend(f"{name} has the example {value!r}, which its own rule refuses: {e.message[:120]}"
                   for value in shown for e in validator.iter_errors(value))
    return out


def check_request_body(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S5: a request body by reference, each field with a description and a type, each required scalar with an example."""
    content = (op.get("requestBody") or {}).get("content") or {}
    if not content:
        return []
    schema = (content.get("application/json") or {}).get("schema") or {}
    # An optional body (`DecisionBody | None`) is anyOf its model and null.
    refs = [sub for sub in [schema, *(schema.get("anyOf") or ())] if "$ref" in sub]
    if list(content) != ["application/json"] or len(refs) != 1:
        return [f"request body is not one application/json schema by reference: {list(content)}"]
    out = []
    optional = any(sub.get("type") == "null" for sub in schema.get("anyOf") or ())
    if not optional and op["requestBody"].get("required") is not True:
        out.append("request body is not marked required")
    model = schema_of(refs[0], spec)
    for field, prop in (model.get("properties") or {}).items():
        if not prop.get("description"):
            out.append(f"request field {field} has no description")
        if not has_type(prop):
            out.append(f"request field {field} has no type")
        if field in model.get("required", []) and prop.get("type") in SCALARS and not prop.get("examples"):
            out.append(f"request field {field} is required and has no example")
    return out


def check_request_example(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S6: one complete Example Value for the request body (recorded or generated, so it is an object) that its own schema
    accepts, so "Try it out" sends a body that passes validation."""
    media = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
    if media is None:
        return []
    values = [media["example"]] if "example" in media else [e.get("value") for e in (media.get("examples") or {}).values()]
    if not values or not all(isinstance(v, dict) and v for v in values):
        return ["request body has no complete example"]
    validator = SchemaReader().validator({**media["schema"], "components": spec["components"]})
    return [f"request example breaks its schema: {e.message[:200]}" for v in values for e in validator.iter_errors(v)]


def check_responses(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S7: every status described, a success in its one media type, a problem in application/problem+json."""
    out, responses = [], op["responses"]
    if not any(s.startswith("2") for s in responses):
        out.append("has no success response")
    for status, r in responses.items():
        description, content = r.get("description") or "", r.get("content") or {}
        if not description or description == FASTAPI_DEFAULT:
            out.append(f"{status} says nothing of what it returns ({description!r})")
        if status.startswith("2"):
            if len(content) != 1 or list(content)[0] not in MEDIA_TYPES:
                out.append(f"{status} is not one of {MEDIA_TYPES}: {list(content)}")
            elif not any(k in media for media in content.values() for k in ("example", "examples")):
                out.append(f"{status} has no example")
        elif status == "304":
            # RFC 9110, 15.4.5: a 304 "cannot contain content", and it repeats the ETag of the 200.
            if content or "ETag" not in (r.get("headers") or {}):
                out.append("304 has a body or no ETag header")
        elif list(content) != ["application/problem+json"]:
            out.append(f"{status} is not application/problem+json alone: {list(content)}")
        elif not description.startswith(PROBLEM_STATUS_TEXT.get(int(status), "\0")):
            out.append(f"{status} does not start with what the status means")
    if takes_validated_input(op) and "422" not in responses:
        out.append("takes input and has no 422 validation-failed")
    conditional = any(p.get("name") == "If-None-Match" for p in op.get("parameters") or ())
    if ((method, path) in CONDITIONAL_READS) != ("304" in responses) or ("304" in responses) != conditional:
        out.append("answers 304 to If-None-Match and does not document both, or documents them and does not")
    # RFC 9110, 13.2.2: a conditional read evaluates If-Match first and answers 412 when it is false (#590).
    names = {p.get("name") for p in op.get("parameters") or ()}
    if (method, path) in CONDITIONAL_READS and ("If-Match" not in names or "412" not in responses):
        out.append("a conditional read does not document If-Match and its 412")
    return out


def check_problem_examples(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S8: one named example per problem code, named by the code, a full RFC 9457 body, all listed in the description."""
    out = []
    for status, r in op["responses"].items():
        media = (r.get("content") or {}).get("application/problem+json")
        if media is None:
            continue
        examples = media.get("examples") or {}
        if not examples:
            out.append(f"{status} has no named example")
        for name, example in examples.items():
            out.extend(_problem_example_gaps(status, name, example.get("value") or {}))
        # The committed document sorts its keys, so the examples' order is not the description's: the set must match.
        listed = re.findall(r"`([a-z0-9-]+)`", (r.get("description") or "").rpartition("Codes: ")[2])
        if examples and (set(listed) != set(examples) or r.get("description") != problem_description(int(status), listed)):
            out.append(f"{status} does not list its codes {sorted(examples)}")
    return out


def _problem_example_gaps(status: str, name: str, value: dict[str, Any]) -> list[str]:
    out = []
    if name not in PROBLEMS or str(PROBLEMS[name][0]) != status:
        out.append(f"{status} has the example {name}, which is not a registered code of that status")
    missing = [f for f in ("type", "title", "status", "detail", "code") if not value.get(f)]
    if missing:
        out.append(f"{status} example {name} has no {', '.join(missing)}")
    if value.get("code") != name or str(value.get("status")) != status:
        out.append(f"{status} example {name} has the code {value.get('code')} and the status {value.get('status')}")
    if not str(value.get("type", "")).endswith(f"/problems/{name}"):
        out.append(f"{status} example {name} has a type that is not /problems/{name}")
    return out


def check_extensions(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S9: the x- fields that Swagger UI and ReDoc show in Extensions: the plugin, its version and the permission."""
    out = [f"has no {x}" for x in ("x-cmapi-plugin", "x-plugin-version") if not isinstance(op.get(x), str) or not op[x]]
    if "x-cmapi-permission" in op and not isinstance(op["x-cmapi-permission"], str):
        out.append(f"x-cmapi-permission is {op['x-cmapi-permission']!r}, not a permission")
    return out


def _after(words: list[str], flag: str) -> list[str]:
    """The words of a curl command that follow one flag: each header after -H, the body after -d."""
    return [word for before, word in zip(words, words[1:]) if before == flag]


def check_curl_sample(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S10: one curl sample of this method that runs as written: every path parameter filled, the token where one is
    needed, each header that the call is refused without, and the request's Example Value (S6) as its JSON body."""
    samples = op.get("x-codeSamples") or []
    if len(samples) != 1 or (samples[0].get("lang"), samples[0].get("label")) != ("Shell", "curl"):
        return [f"has not one Shell curl sample: {samples}"]
    source = samples[0].get("source", "")
    out = []
    # The path that the sample calls: the operation's, each path parameter at its documented example.
    expected = path
    for p in op.get("parameters") or ():
        if p.get("in") == "path":
            expected = expected.replace("{" + p["name"] + "}", str(((p.get("schema") or {}).get("examples") or ["?"])[0]))
    words = shlex.split(source)
    url = words[3] if len(words) > 3 else ""
    if words[:3] != ["curl", "-X", method.upper()] or not url.split("?")[0].endswith(expected):
        out.append(f"curl sample is not a {method.upper()} of {expected}: {source[:120]}")
    if ('"Authorization: Bearer $TOKEN"' in source) != bool(op.get("security")):
        out.append("curl sample's token does not match the security scheme")
    headers = {header.partition(":")[0] for header in _after(words, "-H")}
    for p in op.get("parameters") or ():
        refused_without = p.get("required") or (method != "get" and p["name"] in REFUSED_WITHOUT)
        if p.get("in") == "header" and refused_without and p["name"] not in headers:
            out.append(f"curl sample has no {p['name']} header, which the call is refused without")
    media = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
    bodies = _after(words, "-d")
    if media is None:
        if bodies:
            out.append("curl sample sends a body and the operation takes none")
        return out
    examples = [media["example"]] if "example" in media else [e.get("value") for e in (media.get("examples") or {}).values()]
    try:
        sent = [json.loads(body) for body in bodies]
    except ValueError:
        sent = []
    if "Content-Type" not in headers or len(sent) != 1 or sent[0] not in examples:
        out.append("curl sample does not send the request's Example Value as application/json")
    return out


CHECKS: dict[str, Callable[[str, str, Op, dict], list[str]]] = {
    "S1 summary and description": check_summary,
    "S2 one tag in one group": check_tag,
    "S3 permission and security": check_permission,
    "S4 parameters": check_parameters,
    "S5 request body": check_request_body,
    "S6 request example": check_request_example,
    "S7 every status described": check_responses,
    "S8 one named example per problem code": check_problem_examples,
    "S9 extensions": check_extensions,
    "S10 curl sample": check_curl_sample,
}


def gaps(check: Callable[[str, str, Op, dict], list[str]], spec: dict[str, Any]) -> list[str]:
    out = []
    for method, path, op in operations(spec):
        out.extend(f"{method.upper()} {path}: {line}" for line in check(method, path, op, spec))
    return out


@pytest.mark.parametrize("name", list(CHECKS))
def test_every_operation_meets_the_standard(spec, name):
    found = gaps(CHECKS[name], spec)
    assert found == [], f"{name}: {len(found)} gaps\n  " + "\n  ".join(found)


def test_the_standard_covers_every_operation(spec):
    """The 40 operations of the reference instance, in the 10 tags of the six groups (#480)."""
    ops = list(operations(spec))
    assert len(ops) >= 40 and len({t for _, _, op in ops for t in op["tags"]}) >= 10


def test_a_route_that_says_nothing_of_its_answer_does_not_register():
    """S7 at the source: a read, or a write that answers 200, names its success answer in `returns`; a write that opens a
    request (202) has WRITE_ACCEPTED unless it says more."""
    r = DocumentedRouter("x", prefix="/api/v1", version="1", description="What the x plugin does.", group="Admin")
    with pytest.raises(RuntimeError, match="no `returns`"):
        r.read("/x", summary="Read x", permission=None, returns=" ", response_model=Health)
    with pytest.raises(RuntimeError, match="no `returns`"):
        r.write("/x:act", summary="Act on x", permission="x:write", response_model=Health, status_code=200)

    @r.write("/x", summary="Change x", permission="x:write", response_model=Health)
    def change():
        """Changes it."""

    assert r.routes[-1].response_description == WRITE_ACCEPTED


def test_the_document_keeps_what_each_route_declares(declared, spec):
    """build_openapi adds to the routes' own document and takes nothing away: the security, the permission, each
    parameter's rules and required flag, the body's required flag and each field's rules, each status and each code."""
    out = []
    for method, path, route in operations(declared):
        if method == "head":            # a GET's HEAD, which the document leaves out (core/docs.py, _without_head; #605)
            continue
        op, label = spec["paths"][path][method], f"{method.upper()} {path}"
        for key in ("security", "x-cmapi-permission"):
            if op.get(key) != route.get(key):
                out.append(f"{label}: {key} is {op.get(key)}, the route declares {route.get(key)}")
        published = {(p["name"], p["in"]): p for p in op.get("parameters") or ()}
        for p in route.get("parameters") or ():
            mine = published.get((p["name"], p["in"]), {})
            rules = {k: v for k, v in p["schema"].items() if k not in ("examples", "description", "title")}
            if (p["name"], p["in"]) == ("If-Match", "header") and op.get("operationId") in IF_MATCH_OPERATIONS:
                # The one parameter that the document tightens (#586): the route keeps it optional so that 404 comes before
                # 428, and the document marks it required and drops only the null of `str | None`. Every rule of the string
                # stays, and nothing is added (_document_if_match_required).
                string = next(v for v in rules.pop("anyOf") if v != {"type": "null"})
                shown = {k: v for k, v in (mine.get("schema") or {}).items() if k not in ("examples", "description", "title")}
                if p.get("required") or mine.get("required") is not True or shown != {**rules, **string}:
                    out.append(f"{label}: If-Match is not the route's string, required in the document only: {shown}")
                continue
            kept = {k: v for k, v in (mine.get("schema") or {}).items() if k in rules}
            if kept != rules or mine.get("required") != p.get("required"):
                out.append(f"{label}: parameter {p['name']} lost a rule or its required flag")
        if (op.get("requestBody") or {}).get("required") != (route.get("requestBody") or {}).get("required"):
            out.append(f"{label}: the body's required flag changed")
        for status, response in route["responses"].items():
            codes, shown = problem_codes(response), problem_codes(op["responses"].get(status) or {})
            if status not in op["responses"] or not set(codes) <= set(shown):
                out.append(f"{label}: {status} or one of its codes {sorted(codes)} is missing")
    models = declared["components"]["schemas"]
    for name, model in models.items():
        if name in ("HTTPValidationError", "ValidationError"):
            continue            # FastAPI's 422, which the problem validation-failed replaces (_document_validation_problem)
        for field, prop in (model.get("properties") or {}).items():
            if name in ("NamespaceCreate", "NamespacePatch") and field in ("labels", "annotations"):
                continue        # the instance's metadata-keys.yaml writes these two (the next test)
            mine = spec["components"]["schemas"].get(name, {}).get("properties", {}).get(field, {})
            lost = [k for k, v in prop.items() if k not in ("examples", "description", "title") and mine.get(k) != v]
            if lost:
                out.append(f"{name}.{field} lost {lost}")
    assert out == [], "\n  ".join(out)


def test_the_namespace_fields_carry_the_rules_of_metadata_keys(cfg, spec):
    """S5 and S9 for the configured fields: labels and annotations are the instance's JSON Schemas, with their x-cmapi-*
    markers, and the namespace name says which keys start and end it (#479, design section 5.5)."""
    fields = spec["components"]["schemas"]["NamespaceCreate"]["properties"]
    for field, kind in (("labels", "label"), ("annotations", "annotation")):
        for key, value in cfg.metadata.json_schema(kind, "create").items():
            assert fields[field].get(key) == value, f"NamespaceCreate.{field}: {key}"
    for marker, target in (("x-cmapi-prefix-from", cfg.metadata.prefix_key()),
                           ("x-cmapi-suffix-from", cfg.metadata.suffix_key())):
        assert fields["namespace"].get(marker) == (target[1] if target else None), marker


# The answers of the create operation, as the design's section 5.4 lists them, with two changes that the code decides: the
# token check's 503 idp-unavailable (#504), and no top-level invalid-team-dl or no-change. A bad team-dl is an item of a
# policy-violation (core/metadata.py), and a create always changes Git: namespace-exists refuses a folder that holds one.
# folder-not-utf8 (#626): the create reads the folder too, and a name or a manifest in it that is not UTF-8 is refused there.
# folder-not-yaml (#680): the same read refuses a manifest of the folder that does not parse as YAML.
CREATE_ANSWERS = {
    "200": [], "202": [],
    "400": ["idempotency-key-required"],
    "401": ["unauthenticated"],
    "403": ["forbidden", "environment-forbidden"],
    "404": ["cluster-not-found"],
    "409": ["change-pending", "idempotency-replay", "namespace-exists", "namespace-exists-unmanaged", "folder-not-utf8",
            "folder-not-yaml"],
    "422": ["cluster-not-writable", "environment-not-served", "plugin-disabled", "validation-failed", "policy-violation",
            "capacity-exceeded", "identity-incomplete", "unknown-user", "unknown-serviceaccount", "reserved-namespace",
            "invalid-namespace-name", "expiration-not-allowed", "expiration-in-past", "on-behalf-of-not-allowed",
            "on-behalf-of-required"],
    "502": ["git-unavailable"],
    "503": ["cluster-unreachable", "validator-unavailable", "idp-unavailable"],
}


def test_the_create_operation_answers_what_the_design_lists(spec):
    responses = _create(spec)["responses"]
    assert sorted(responses) == sorted(CREATE_ANSWERS)
    for status, codes in CREATE_ANSWERS.items():
        assert sorted(problem_codes(responses[status])) == sorted(codes), status


# ---------------------------------------------------------------- what each operation can answer (#503 review)

def _codes(spec: dict, operation_id: str, status: str) -> set[str]:
    op = next(op for _, _, op in operations(spec) if op["operationId"] == operation_id)
    return set(problem_codes(op["responses"].get(status) or {}))


@pytest.mark.parametrize("operation_id", ["requests_get_request", "requests_get_events", "requests_approval_status",
                                          "requests_cancel", "requests_retry", "requests_revert",
                                          "namespaces_list_namespaces", "namespaces_get_namespace"])
def test_a_route_that_checks_the_permission_in_an_environment_shows_environment_forbidden(spec, operation_id):
    """Each of these calls roles.require with the request's or the cluster's environment (core/authz.py)."""
    assert "environment-forbidden" in _codes(spec, operation_id, "403")


def test_revert_takes_no_namespace_lock_so_it_has_no_change_pending(spec):
    """:revert only queues open_revert (routers/requests.py); the new request takes the lock in the worker."""
    assert _codes(spec, "requests_revert", "409") == {"invalid-transition"}


def test_a_delete_renders_nothing_and_names_no_requester(spec):
    """plan_delete runs no validator, no capacity check and no render of a namespace, and sends no onBehalfOf."""
    codes = _codes(spec, "namespaces_delete_namespace", "422") | _codes(spec, "namespaces_delete_namespace", "503")
    assert codes.isdisjoint({"policy-violation", "capacity-exceeded", "unknown-serviceaccount", "no-change",
                             "validator-unavailable", "unknown-user", "on-behalf-of-not-allowed"})
    assert "on-behalf-of-required" in codes


@pytest.mark.parametrize("operation_id,has", [
    ("namespaces_create_namespace", {"unknown-user", "on-behalf-of-not-allowed", "on-behalf-of-required", "expiration-in-past"}),
    ("namespaces_update_namespace", {"unknown-user", "on-behalf-of-not-allowed", "on-behalf-of-required", "no-change"}),
    ("namespaces_extend", {"on-behalf-of-required", "expiration-not-set", "expiration-in-past", "expiration-limit"}),
    ("namespaces_set_expiry", {"on-behalf-of-required", "expiration-already-set", "expiration-in-past", "expiration-limit"}),
    ("namespaces_make_permanent", {"on-behalf-of-required", "expiration-not-set"}),
])
def test_each_namespace_write_shows_the_refusals_of_its_own_steps(spec, operation_id, has):
    """No top-level invalid-team-dl (a policy-violation item), and only the date checks that each expiry route runs
    (plugins/expiration/rules.py): :makePermanent takes no date, :set refuses a date that exists."""
    codes = _codes(spec, operation_id, "422")
    assert has <= codes and "invalid-team-dl" not in codes
    every = {"unknown-user", "on-behalf-of-not-allowed", "no-change", "expiration-not-set", "expiration-already-set",
             "expiration-in-past", "expiration-limit"}
    assert not (codes & every) - has, sorted((codes & every) - has)


def test_an_environment_that_the_instance_does_not_serve_is_environment_not_served_on_tiers(spec):
    """GET /tiers?environment=x refuses an unserved environment before the catalog, with 422 environment-not-served and the
    serving instance's URLs (#671; it was a TierError, answered as policy-violation), so the document lists that code."""
    codes = _codes(spec, "tiers_tiers", "422")
    assert "environment-not-served" in codes and "policy-violation" not in codes, sorted(codes)


def test_each_403_example_names_the_permission_of_its_route(spec):
    for _, path, op in operations(spec):
        permission = op.get("x-cmapi-permission")
        for code in ("forbidden", "environment-forbidden"):
            example = problem_codes(op["responses"].get("403") or {}).get(code)
            if permission and example:
                assert permission in example["value"]["detail"], (path, code)


def test_the_token_checks_503_example_is_the_answer_of_the_token_check(spec):
    """core/auth.py, Jwks.key: an unknown key while Keycloak cannot be read is 503 idp-unavailable with retryAfter."""
    from cmapi.core.auth import Jwks
    from cmapi.core.errors import Problem

    def unreachable(url):
        raise OSError("Keycloak is down")

    with pytest.raises(Problem) as refusal:
        Jwks("issuer", "https://keycloak.test/certs", fetch=unreachable).key("a-key-it-never-saw")
    for _, path, op in operations(spec):
        if op.get("security"):
            assert op["responses"]["503"]["content"]["application/problem+json"]["examples"]["idp-unavailable"]["value"] == \
                refusal.value.body(), path


def test_a_sample_without_a_public_url_lets_the_shell_fill_cmapi_url(tmp_path):
    """instance.yaml without publicUrl: the samples start with $CMAPI_URL, which single quotes would keep from the shell."""
    import os
    import subprocess

    from cmapi.core.docs import curl_sample

    command = curl_sample({"method": "GET", "url": "$CMAPI_URL/api/v1/version", "headers": [], "body": None})
    shown = subprocess.run(["sh", "-c", "curl() { printf '%s\\n' \"$@\"; }; " + command], check=True, text=True,
                           capture_output=True, env={**os.environ, "CMAPI_URL": "https://cmapi.test"}).stdout.splitlines()
    assert shown == ["-X", "GET", "https://cmapi.test/api/v1/version"]


def test_the_directory_and_the_retry_say_what_the_caller_gets(spec):
    """GET /directory/users/{username} gives the employee ID to an operator only (Person.public), and :retry queues the
    next step for the worker (routers/requests.py): it opens no pull request itself."""
    person = spec["paths"]["/api/v1/directory/users/{username}"]["get"]["responses"]["200"]["description"]
    retry = spec["paths"]["/api/v1/requests/{request_id}:retry"]["post"]["responses"]["200"]["description"]
    assert "operator only" in person and "queued" in retry


def test_the_delete_key_is_described_as_the_delete_checks_it(spec):
    """DELETE checks its Idempotency-Key as the other writes do (_idem): 400 without one, or past 100, and none is read
    with dryRun=true (#602). Its description leaves out what the delete does not take: onBehalfOf and justification."""
    from cmapi.plugins.namespaces.router import _idem

    for key in (None, "", "k" * 101):
        with pytest.raises(Exception, match="Idempotency-Key"):
            _idem(key, False)
    assert _idem(None, True) is None
    ops = spec["paths"]["/api/v1/clusters/{cluster_id}/namespaces/{ns}"]
    delete = next(p for p in ops["delete"]["parameters"] if p["name"] == "Idempotency-Key")["description"]
    patch = next(p for p in ops["patch"]["parameters"] if p["name"] == "Idempotency-Key")["description"]
    assert "except with `dryRun=true`" in delete and "100 characters" in delete
    assert "onBehalfOf" not in delete and "justification" not in delete
    assert "dryRun" in patch and "100 characters" in patch


def test_adding_a_problem_keeps_what_the_response_declared_and_the_order_of_the_statuses():
    """add_problem (core/docs.py) adds a code to a copy of the response: its headers stay, the route's dict is not changed,
    and the statuses stay in order, as Swagger UI and ReDoc list them."""
    from cmapi.core.docs import add_problem, problem_responses

    declared = problem_responses(["cluster-unreachable"])[503]
    declared["headers"] = {"Retry-After": {"schema": {"type": "integer"}}}
    before = copy.deepcopy(declared)
    op = {"responses": {"200": {"description": "ok"}, "503": declared}}
    add_problem(op, "validation-failed")
    add_problem(op, "idp-unavailable")
    assert declared == before        # the route's own dict, which FastAPI shares between the apps of a process
    assert list(op["responses"]) == ["200", "422", "503"]
    assert op["responses"]["503"]["headers"] == {"Retry-After": {"schema": {"type": "integer"}}}
    assert set(op["responses"]["503"]["content"]["application/problem+json"]["examples"]) == {"cluster-unreachable",
                                                                                            "idp-unavailable"}


# ---------------------------------------------------------------- each check can fail

def _create(spec: dict) -> Op:
    return spec["paths"][CREATE[1]][CREATE[0]]


def _problem(spec: dict, status: str) -> dict[str, Any]:
    return _create(spec)["responses"][status]["content"]["application/problem+json"]


BREAKS: list[tuple[str, str, Callable[[dict], Any]]] = [
    ("S1 summary and description", "final stop", lambda s: _create(s).update(summary="Create a namespace.")),
    ("S1 summary and description", "verb", lambda s: _create(s).update(summary="Namespace creation")),
    ("S2 one tag in one group", "not the one tag", lambda s: _create(s).update(tags=["namespaces", "quotas"])),
    ("S3 permission and security", "no 503 idp-unavailable", lambda s: _create(s)["responses"].pop("503")),
    ("S3 permission and security", "**Requires**", lambda s: _create(s).update(description="Plans a new namespace on the cluster.")),
    ("S3 permission and security", "no x-cmapi-permission", lambda s: _create(s).pop("x-cmapi-permission")),
    ("S3 permission and security", "does not define", lambda s: _create(s).update(security=[{"missing": []}])),
    ("S4 parameters", "has no example", lambda s: _create(s)["parameters"][0]["schema"].pop("examples")),
    ("S5 request body", "has no description",
     lambda s: s["components"]["schemas"]["NamespaceCreate"]["properties"]["namespace"].pop("description")),
    ("S5 request body", "not marked required", lambda s: _create(s)["requestBody"].pop("required")),
    ("S6 request example", "no complete example",
     lambda s: _create(s)["requestBody"]["content"]["application/json"].update(examples={})),
    ("S6 request example", "breaks its schema",
     lambda s: _create(s)["requestBody"]["content"]["application/json"]["examples"]["permanent"].update(value={"namespace": "x"})),
    ("S7 every status described", "says nothing", lambda s: _create(s)["responses"]["202"].update(description=FASTAPI_DEFAULT)),
    ("S7 every status described", "what the status means", lambda s: _create(s)["responses"]["409"].update(description="409")),
    ("S7 every status described", "202 has no example",
     lambda s: _create(s)["responses"]["202"]["content"]["application/json"].pop("example")),
    ("S8 one named example per problem code", "does not list its codes",
     lambda s: _problem(s, "409")["examples"].pop("idempotency-replay")),
    ("S8 one named example per problem code", "not a registered code",
     lambda s: _problem(s, "409")["examples"].update({"forbidden": _problem(s, "409")["examples"]["change-pending"]})),
    ("S9 extensions", "has no x-plugin-version", lambda s: _create(s).pop("x-plugin-version")),
    ("S10 curl sample", "not one Shell curl sample", lambda s: _create(s).pop("x-codeSamples")),
    ("S10 curl sample", "is not a POST of",
     lambda s: _create(s)["x-codeSamples"][0].update(source=_create(s)["x-codeSamples"][0]["source"].replace("/namespaces ", "/x "))),
    ("S4 parameters", "its own rule refuses",
     lambda s: next(p for p in _create(s)["parameters"] if p["in"] == "query")["schema"].update(examples=["maybe"])),
    ("S8 one named example per problem code", "example change-pending has no detail",
     lambda s: _problem(s, "409")["examples"]["change-pending"]["value"].update(detail="")),
    ("S10 curl sample", "has no Idempotency-Key header",
     lambda s: _create(s)["x-codeSamples"][0].update(
         source=_create(s)["x-codeSamples"][0]["source"].replace("Idempotency-Key: ", "X-Other: "))),
    ("S10 curl sample", "does not send the request's Example Value",
     lambda s: _create(s)["x-codeSamples"][0].update(
         source=_create(s)["x-codeSamples"][0]["source"].partition(" -d ")[0] + " -d '{\"namespace\": \"x\"}'")),
]


@pytest.mark.parametrize("name,expected,brk", BREAKS, ids=[f"{n}: {e}" for n, e, _ in BREAKS])
def test_each_check_fails_on_a_document_that_breaks_it(spec, name, expected, brk):
    broken = copy.deepcopy(spec)
    brk(broken)
    found = [line for line in gaps(CHECKS[name], broken) if line.startswith(f"{CREATE[0].upper()} {CREATE[1]}:")]
    assert any(expected in line for line in found), f"{name} did not report {expected!r}: {json.dumps(found)[:600]}"
