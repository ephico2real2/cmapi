"""The API documentation standard (#480; docs/reviews/2026-11-20-issue-479/implementation_plan.md, section 3): every
operation of the document meets S1 to S10, so Swagger UI and ReDoc show each one in the same format.

The documents are the ones that the reference instance serves (`cmapi-tools openapi render`, no database): on the
reference metadata-keys.yaml, which test_the_committed_contract_is_the_document_this_code_serves holds equal to
cmapi/contract/openapi.json, and on the company keys of the namespace design. Each check is one
row of CHECKS: a function that returns one failure line per gap, such as "POST /api/v1/x: 409 has no example named
idempotency-replay". The second test breaks the create operation once per check and holds the check to its failure, so a
check that can never fail is caught too.

S9 is also the renderers' settings; test_api_docs.py checks that /docs and /redoc are served with them.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable

import pytest

from cmapi.core.docs import PROBLEM_STATUS_TEXT, PROBLEMS, WRITE_ACCEPTED, DocumentedRouter, problem_description
from cmapi.core.models import Health
from cmapi.main import openapi_document
from cmapi.tools.openapi import cluster_environments, load

# The reference file of the committed contract, and the company keys of the namespace design (#479, section 3.1).
POLICIES = Path(__file__).resolve().parents[3] / "examples/cluster-configs/policies"
CREATE = ("post", "/api/v1/clusters/{cluster_id}/namespaces")
FASTAPI_DEFAULT = "Successful Response"
MEDIA_TYPES = ("application/json", "text/csv")
SCALARS = ("string", "integer", "number", "boolean")
Op = dict[str, Any]


@pytest.fixture(scope="module", params=["metadata-keys.yaml", "metadata-keys.company.yaml"])
def spec(request) -> dict[str, Any]:
    cfg = load(POLICIES / request.param, None)
    return openapi_document(cfg, cluster_environments(cfg, None))


def operations(spec: dict[str, Any]):
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            yield method, path, op


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
    """S6: one complete Example Value for the request body (recorded or generated, so it is an object)."""
    media = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
    if media is None:
        return []
    values = [media["example"]] if "example" in media else [e.get("value") for e in (media.get("examples") or {}).values()]
    if not values or not all(isinstance(v, dict) and v for v in values):
        return ["request body has no complete example"]
    return []


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
        elif list(content) != ["application/problem+json"]:
            out.append(f"{status} is not application/problem+json alone: {list(content)}")
        elif not description.startswith(PROBLEM_STATUS_TEXT.get(int(status), "\0")):
            out.append(f"{status} does not start with what the status means")
    if (op.get("parameters") or op.get("requestBody")) and "422" not in responses:
        out.append("takes input and has no 422 validation-failed")
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
    missing = [f for f in ("type", "title", "status", "detail", "code") if f not in value]
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


def check_curl_sample(method: str, path: str, op: Op, spec: dict) -> list[str]:
    """S10: one curl sample of this method, with every path parameter filled and the token where one is needed."""
    samples = op.get("x-codeSamples") or []
    if len(samples) != 1 or (samples[0].get("lang"), samples[0].get("label")) != ("Shell", "curl"):
        return [f"has not one Shell curl sample: {samples}"]
    source = samples[0].get("source", "")
    out = []
    if not source.startswith(f"curl -X {method.upper()} ") or "{" in source.split()[3]:
        out.append(f"curl sample is not a {method.upper()} with its path filled: {source[:120]}")
    if ('"Authorization: Bearer $TOKEN"' in source) != bool(op.get("security")):
        out.append("curl sample's token does not match the security scheme")
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


# ---------------------------------------------------------------- each check can fail

def _create(spec: dict) -> Op:
    return spec["paths"][CREATE[1]][CREATE[0]]


def _problem(spec: dict, status: str) -> dict[str, Any]:
    return _create(spec)["responses"][status]["content"]["application/problem+json"]


BREAKS: list[tuple[str, str, Callable[[dict], Any]]] = [
    ("S1 summary and description", "final stop", lambda s: _create(s).update(summary="Create a namespace.")),
    ("S2 one tag in one group", "not the one tag", lambda s: _create(s).update(tags=["namespaces", "quotas"])),
    ("S3 permission and security", "no 503 idp-unavailable", lambda s: _create(s)["responses"].pop("503")),
    ("S3 permission and security", "**Requires**", lambda s: _create(s).update(description="Plans a new namespace on the cluster.")),
    ("S4 parameters", "has no example", lambda s: _create(s)["parameters"][0]["schema"].pop("examples")),
    ("S5 request body", "has no description",
     lambda s: s["components"]["schemas"]["NamespaceCreate"]["properties"]["namespace"].pop("description")),
    ("S6 request example", "no complete example",
     lambda s: _create(s)["requestBody"]["content"]["application/json"].update(examples={})),
    ("S7 every status described", "says nothing", lambda s: _create(s)["responses"]["202"].update(description=FASTAPI_DEFAULT)),
    ("S7 every status described", "what the status means", lambda s: _create(s)["responses"]["409"].update(description="409")),
    ("S8 one named example per problem code", "does not list its codes",
     lambda s: _problem(s, "409")["examples"].pop("idempotency-replay")),
    ("S8 one named example per problem code", "not a registered code",
     lambda s: _problem(s, "409")["examples"].update({"forbidden": _problem(s, "409")["examples"]["change-pending"]})),
    ("S9 extensions", "has no x-plugin-version", lambda s: _create(s).pop("x-plugin-version")),
    ("S10 curl sample", "not one Shell curl sample", lambda s: _create(s).pop("x-codeSamples")),
]


@pytest.mark.parametrize("name,expected,brk", BREAKS, ids=[f"{n}: {e}" for n, e, _ in BREAKS])
def test_each_check_fails_on_a_document_that_breaks_it(spec, name, expected, brk):
    broken = copy.deepcopy(spec)
    brk(broken)
    found = [line for line in gaps(CHECKS[name], broken) if line.startswith(f"{CREATE[0].upper()} {CREATE[1]}:")]
    assert any(expected in line for line in found), f"{name} did not report {expected!r}: {json.dumps(found)[:600]}"
