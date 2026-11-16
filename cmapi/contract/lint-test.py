#!/usr/bin/env python3
"""Prove the Spectral ruleset on the committed document (#143): the document passes, and a document that breaks one rule fails
with that rule. A ruleset that passes everything, or a rule that never fires, fails this test.

    python contract/lint-test.py

Each case changes a copy of contract/openapi.json in one place and names the rule that must report it. A case fails when
the lint passes, or when the named rule is not among the results.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
CREATE = ("/api/v1/clusters/{cluster_id}/namespaces", "post")
EXPORT = ("/api/v1/quotas:export", "get")


def op(spec: dict, where: tuple[str, str] = CREATE) -> dict:
    return spec["paths"][where[0]][where[1]]


def problem(spec: dict, status: str = "401") -> dict:
    return op(spec)["responses"][status]["content"]["application/problem+json"]


def set_(target: dict, key: str, value: Any) -> None:
    target[key] = value


CASES: list[tuple[str, str, Callable[[dict], Any]]] = [
    # ---- 1. operationId
    ("an operation has no operationId", "operation-operationId", lambda s: op(s).pop("operationId")),
    ("two operations have one operationId", "operation-operationId-unique",
     lambda s: set_(op(s, EXPORT), "operationId", op(s)["operationId"])),
    ("an operationId is in camel case", "cmapi-operation-id-of-plugin", lambda s: set_(op(s), "operationId", "namespacesCreate")),
    ("an operationId starts with another plugin", "cmapi-operation-id-of-plugin",
     lambda s: set_(op(s), "operationId", "quotas_create_namespace")),
    # ---- 2. tags
    ("an operation has no tag", "operation-tags", lambda s: op(s).pop("tags")),
    ("an operation has two tags", "cmapi-operation-one-tag", lambda s: set_(op(s), "tags", ["namespaces", "quotas"])),
    ("an operation has the tag of another plugin", "cmapi-operation-one-tag", lambda s: set_(op(s), "tags", ["quotas"])),
    ("an operation has a tag that the document does not define", "operation-tag-defined", lambda s: set_(op(s), "tags", ["netpol"])),
    ("a tag has no description", "tag-description", lambda s: s["tags"][0].pop("description")),
    ("a tag is in no group", "cmapi-tag-in-one-group", lambda s: s["x-tagGroups"][0]["tags"].pop()),
    ("a tag is in two groups", "cmapi-tag-in-one-group", lambda s: s["x-tagGroups"][1]["tags"].append(s["x-tagGroups"][0]["tags"][0])),
    ("the document has no groups", "cmapi-tag-in-one-group", lambda s: s.pop("x-tagGroups")),
    # ---- 3. examples
    ("a parameter has no example", "cmapi-parameter-example", lambda s: op(s)["parameters"][0]["schema"].pop("examples")),
    ("a request body has no example", "cmapi-body-example", lambda s: op(s)["requestBody"]["content"]["application/json"].pop("example")),
    ("a response body has no example", "cmapi-body-example", lambda s: op(s)["responses"]["202"]["content"]["application/json"].pop("example")),
    ("the plan of a dry run has no example", "cmapi-body-example", lambda s: op(s)["responses"]["200"]["content"]["application/json"].pop("example")),
    ("an example does not fit its schema", "oas3-valid-media-example",
     lambda s: set_(op(s)["responses"]["202"]["content"]["application/json"]["example"], "requestId", 7)),
    # ---- 4. problem responses
    ("a problem response has application/json also", "cmapi-problem-media-type",
     lambda s: set_(op(s)["responses"]["401"]["content"], "application/json", {"schema": {"$ref": "#/components/schemas/ProblemDetail"}})),
    ("a problem response has no content", "cmapi-problem-media-type", lambda s: op(s)["responses"]["401"].pop("content")),
    ("a problem response has no schema", "cmapi-problem-media-type", lambda s: problem(s).pop("schema")),
    ("a problem response has another schema", "cmapi-problem-schema",
     lambda s: set_(problem(s), "schema", {"$ref": "#/components/schemas/ChangeRequest"})),
    ("a problem response has no example", "cmapi-problem-example", lambda s: problem(s).pop("examples")),
    ("a problem example has the status of another response", "cmapi-problem-example",
     lambda s: set_(problem(s)["examples"]["unauthenticated"]["value"], "status", 403)),
    ("a problem example has no code", "cmapi-problem-example", lambda s: problem(s)["examples"]["unauthenticated"]["value"].pop("code")),
    ("a problem example is under the name of another code", "cmapi-problem-example",
     lambda s: set_(problem(s)["examples"], "forbidden", problem(s)["examples"].pop("unauthenticated"))),
    ("an operation with a token declares no 401", "cmapi-secured-operation-problems", lambda s: op(s)["responses"].pop("401")),
    ("an operation with a permission declares no 403", "cmapi-secured-operation-problems", lambda s: op(s)["responses"].pop("403")),
    # ---- 5. no inline schemas
    ("a response has an inline object", "cmapi-no-inline-schema",
     lambda s: set_(op(s)["responses"]["202"]["content"]["application/json"], "schema",
                    {"type": "object", "properties": {"requestId": {"type": "string"}}})),
    ("a response has an empty schema", "cmapi-no-inline-schema", lambda s: set_(op(s)["responses"]["202"]["content"]["application/json"], "schema", {})),
    ("a response has no schema", "cmapi-no-inline-schema", lambda s: op(s)["responses"]["202"]["content"]["application/json"].pop("schema")),
    ("a request body has an inline object", "cmapi-no-inline-schema",
     lambda s: set_(op(s)["requestBody"]["content"]["application/json"], "schema", {"type": "object", "additionalProperties": True})),
    ("a list holds inline objects", "cmapi-no-inline-schema",
     lambda s: set_(op(s)["responses"]["202"]["content"]["application/json"], "schema", {"type": "array", "items": {"type": "object"}})),
    # ---- 6. cmapi.net/ keys only in label examples
    ("a cmapi.net/ key is a field of a response example", "cmapi-net-keys-only-in-labels",
     lambda s: set_(op(s)["responses"]["202"]["content"]["application/json"]["example"], "cmapi.net/team", "payments")),
    ("a cmapi.net/ key is in an example of a field that is not a metadata map", "cmapi-net-keys-only-in-labels",
     lambda s: set_(s["components"]["schemas"]["NamespaceCreate"]["properties"]["tier"], "examples", [{"cmapi.net/tier": "small"}])),
]


def lint(document: Path) -> tuple[int, list[dict]]:
    run = subprocess.run([str(HERE / "lint.sh"), str(document), "--format", "json", "--quiet"], capture_output=True, text=True)
    if run.returncode not in (0, 1):
        sys.exit(f"lint-test: the lint did not run (exit {run.returncode}): {run.stderr.strip()[:400]}")
    return run.returncode, json.loads(run.stdout or "[]")


def main() -> int:
    committed = json.loads((HERE / "openapi.json").read_text())
    failed = 0
    code, results = lint(HERE / "openapi.json")
    if code != 0 or results:
        failed += 1
        print(f"FAIL the committed document passes: exit {code}, {sorted({r['code'] for r in results})}")
    else:
        print("ok   the committed document passes")
    with tempfile.TemporaryDirectory() as tmp:
        for number, (name, rule, change) in enumerate(CASES, 1):
            spec = copy.deepcopy(committed)
            change(spec)
            if spec == committed:
                sys.exit(f"lint-test: the case '{name}' changes nothing")
            path = Path(tmp) / f"case-{number}.json"
            path.write_text(json.dumps(spec))
            code, results = lint(path)
            codes = sorted({r["code"] for r in results})
            if code == 1 and rule in codes:
                print(f"ok   refused, as it must: {name} ({rule})")
            else:
                failed += 1
                print(f"FAIL {name}: wanted {rule}, exit {code}, results {codes}")
    print(f"lint-test: {len(CASES) + 1} cases, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
