#!/usr/bin/env python3
"""Spike #187: each call of cmapi's cluster adapter (core/clients/kube.py at a29e683) against the Kubernetes API description.

usage: python3 -I kube_calls.py <swagger.json of kubernetes/kubernetes api/openapi-spec>
For each call: the path and method exist, each query parameter is declared, the content type of the apply is accepted, and each
status that the adapter names is documented. OpenShift's /apis/user.openshift.io/v1/users/~ is not in this description.
"""
import json
import sys

D = json.load(open(sys.argv[1]))
RESOURCES = {
    "Namespace": ("/api/v1/namespaces", False), "ResourceQuota": ("/api/v1/resourcequotas", True),
    "LimitRange": ("/api/v1/limitranges", True), "ServiceAccount": ("/api/v1/serviceaccounts", True),
    "RoleBinding": ("/apis/rbac.authorization.k8s.io/v1/rolebindings", True), "Node": ("/api/v1/nodes", False),
    "Pod": ("/api/v1/pods", True), "PersistentVolumeClaim": ("/api/v1/persistentvolumeclaims", True),
}
calls = [("version", "get", "/version/", [], None, [200])]
calls.append(("whoami (Kubernetes)", "post", "/apis/authentication.k8s.io/v1/selfsubjectreviews", [], None, [200, 201]))
for kind, (path, namespaced) in RESOURCES.items():
    one = path.replace("/v1/", "/v1/namespaces/{namespace}/", 1) if namespaced else path
    calls.append((f"list {kind} (all namespaces)", "get", path, ["labelSelector", "resourceVersion"], None, [200]))
    calls.append((f"watch {kind}", "get", path, ["watch", "resourceVersion", "timeoutSeconds", "allowWatchBookmarks"], None, [200]))
    if namespaced:
        calls.append((f"list {kind} (one namespace)", "get", one, ["labelSelector", "resourceVersion"], None, [200]))
    calls.append((f"get {kind}", "get", one + "/{name}", [], None, [200]))
    calls.append((f"apply {kind}", "patch", one + "/{name}", ["fieldManager", "force"], "application/apply-patch+yaml", [200]))
    calls.append((f"delete {kind}", "delete", one + "/{name}", [], None, [200, 202]))


def deref(p):
    return D["parameters"][p["$ref"].split("/")[-1]] if "$ref" in p else p


found = []
for name, method, path, query, content, statuses in calls:
    item = D["paths"].get(path)
    op = (item or {}).get(method)
    if op is None:
        found.append(f"{name}: {method.upper()} {path} is not in the description")
        continue
    declared = {deref(p)["name"] for p in (op.get("parameters") or []) + (item.get("parameters") or []) if deref(p).get("in") == "query"}
    for q in query:
        if q not in declared:
            found.append(f"{name}: query parameter {q} is not declared for {method.upper()} {path}")
    if content and content not in (op.get("consumes") or []):
        found.append(f"{name}: {content} is not accepted by {method.upper()} {path}: {op.get('consumes')}")
    documented = {int(s) for s in op["responses"] if s.isdigit()}
    for s in statuses:
        if s not in documented:
            found.append(f"{name}: status {s} is named, and {method.upper()} {path} documents {sorted(documented)}")
print(f"description: swagger {D['swagger']}, {len(D['paths'])} paths")
print(f"calls checked: {len(calls)}; distinct operations: {len({(m, p) for _, m, p, *_ in calls})}")
print(f"differences: {len(found)}")
for f in found:
    print("  " + f)
