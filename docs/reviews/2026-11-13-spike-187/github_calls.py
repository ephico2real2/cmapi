#!/usr/bin/env python3
"""Spike #187: each call of cmapi's GitHub adapter (core/git/github.py at a29e683) against GitHub's published OpenAPI description.

usage: python3 -I github_calls.py <api.github.com.json>
For each call: the path and method exist; each query parameter and each body field that the adapter sends is declared; each
required body field is sent; each status that the adapter accepts is documented; each answer field that it reads is in the schema.
"""
import json
import sys

D = json.load(open(sys.argv[1]))
R = "/repos/{owner}/{repo}"
# (name, method, documented path, query parameters, body fields, statuses the adapter handles, answer fields read [of the 2xx], line)
CALLS = [
    ("branch_head", "get", R + "/branches/{branch}", [], [], [200, 404], ["commit.sha"], 57),
    ("read_folder", "get", R + "/contents/{path}", ["ref"], [], [200, 404], [], 65),
    ("read_file", "get", R + "/contents/{path}", ["ref"], [], [200], [], 72),
    ("delete_branch", "delete", R + "/git/refs/{ref}", [], [], [204, 422], [], 81),
    ("create_branch", "post", R + "/git/refs", [], ["ref", "sha"], [201], [], 84),
    ("blob", "post", R + "/git/blobs", [], ["content", "encoding"], [201], ["sha"], 94),
    ("commit_read", "get", R + "/git/commits/{commit_sha}", [], [], [200], ["tree.sha"], 97),
    ("tree", "post", R + "/git/trees", [], ["base_tree", "tree"], [201], ["sha"], 98),
    ("commit", "post", R + "/git/commits", [], ["message", "tree", "parents", "author"], [201], ["sha"], 100),
    ("update_ref", "patch", R + "/git/refs/{ref}", [], ["sha"], [200], [], 103),
    ("open_pr", "post", R + "/pulls", [], ["head", "base", "title", "body"], [201], ["number", "html_url", "head.ref", "head.sha"], 104),
    ("compare", "get", R + "/compare/{basehead}", [], [], [200, 404], ["ahead_by", "files"], 113),
    ("find_pr", "get", R + "/pulls", ["state", "head"], [], [200], [], 131),
    ("pr_check_suites", "get", R + "/commits/{ref}/check-suites", ["per_page", "page"], [], [200], ["check_suites"], 155),
    ("pr_check_runs (suite)", "get", R + "/check-suites/{check_suite_id}/check-runs", ["per_page", "page", "filter"], [], [200], ["check_runs"], 159),
    ("pr_check_runs (commit)", "get", R + "/commits/{ref}/check-runs", ["per_page", "page", "filter"], [], [200], ["check_runs"], 162),
    ("pr_status", "get", R + "/pulls/{pull_number}", [], [], [200], ["state", "merged", "merge_commit_sha", "head.sha"], 170),
    ("pr_checks", "get", R + "/commits/{ref}/status", ["per_page", "page"], [], [200], ["statuses"], 178),
    ("set_check", "post", R + "/statuses/{sha}", [], ["context", "state", "description", "target_url"], [201], [], 190),
    ("merge", "put", R + "/pulls/{pull_number}/merge", [], ["sha", "merge_method", "commit_title"], [200], ["sha"], 195),
    ("comment", "post", R + "/issues/{issue_number}/comments", [], ["body"], [201], [], 203),
    ("close", "patch", R + "/pulls/{pull_number}", [], ["state"], [200], [], 204),
    ("log", "get", R + "/commits", ["sha", "per_page"], [], [200], [], 207),
]


def deref(node):
    while isinstance(node, dict) and "$ref" in node:
        cur = D
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur[part]
        node = cur
    return node


def props(schema, depth=0):
    """The property names that a schema permits, through allOf, oneOf and anyOf."""
    schema = deref(schema) or {}
    out = dict(schema.get("properties") or {})
    for key in ("allOf", "oneOf", "anyOf"):
        for sub in schema.get(key) or []:
            out.update(props(sub, depth + 1))
    return out


def has_field(schema, dotted):
    for name in dotted.split("."):
        p = props(schema)
        if name not in p:
            return False
        schema = p[name]
    return True


found, rows = [], []
for name, method, path, query, body, statuses, read, line in CALLS:
    op = (D["paths"].get(path) or {}).get(method)
    if op is None:
        found.append(f"{name} (github.py:{line}): {method.upper()} {path} is not in the description")
        continue
    declared = {deref(p)["name"] for p in (op.get("parameters") or []) + (D["paths"][path].get("parameters") or []) if deref(p).get("in") == "query"}
    for q in query:
        if q not in declared:
            found.append(f"{name} (github.py:{line}): query parameter {q} is not declared for {method.upper()} {path}")
    request = deref(((deref(op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {})
    allowed = props(request)
    for b in body:
        if b not in allowed:
            found.append(f"{name} (github.py:{line}): body field {b} is not in the request schema of {method.upper()} {path}")
    for req in request.get("required") or []:
        if req not in body:
            found.append(f"{name} (github.py:{line}): required body field {req} is not sent to {method.upper()} {path}")
    documented = {int(s) for s in op["responses"] if s.isdigit()}
    for s in statuses:
        if s not in documented:
            found.append(f"{name} (github.py:{line}): status {s} is handled, and {method.upper()} {path} documents {sorted(documented)}")
    ok = next((op["responses"][str(s)] for s in statuses if 200 <= s < 300 and str(s) in op["responses"]), None)
    answer = deref(((deref(ok or {}).get("content") or {}).get("application/json") or {}).get("schema") or {})
    for f in read:
        target = answer.get("items") if answer.get("type") == "array" else answer
        if not has_field(target, f):
            found.append(f"{name} (github.py:{line}): answer field {f} is not in the 2xx schema of {method.upper()} {path}")
    rows.append((name, method.upper(), path, sorted(documented - set(statuses))))

print(f"description: OpenAPI {D['openapi']}, version {D['info']['version']}, {len(D['paths'])} paths")
print(f"calls checked: {len(CALLS)}; distinct operations: {len({(m, p) for _, m, p, *_ in CALLS})}")
print("\nDocumented statuses that the adapter does not name (they reach its general error path):")
for name, method, path, rest in rows:
    print(f"  {name:24} {method:6} {path:60} {rest}")
print(f"\ndifferences: {len(found)}")
for f in found:
    print("  " + f)
