#!/usr/bin/env python3
"""An in-memory-on-disk kubectl for deploy/secrets.sh and deploy/secrets-test.sh. Implements only the verbs they use, the
way kubectl behaves: a named get of an absent object is rc 1; --ignore-not-found makes that rc 0 with empty output.
STUB_DIR holds state.json and argv.log. STUB_FAIL is a comma list of 'verb:kind:name' (use * as a wildcard); a match prints
a Forbidden-style error and exits 1, standing for an API error that is not NotFound. STUB_NO_CRD=true: no KeycloakRealmImport
type on this server unless a CRD was applied."""
import base64, json, os, sys, fnmatch

try:
    import yaml
except ImportError:
    sys.exit("run with a python that has pyyaml")

d = os.environ["STUB_DIR"]; sp = os.path.join(d, "state.json")
state = json.load(open(sp)) if os.path.exists(sp) else {"secret": {}, "ns": [], "crd": [], "kri": {}}
argv = sys.argv[1:]
open(os.path.join(d, "argv.log"), "a").write(" ".join(argv) + "\n")
def save(): json.dump(state, open(sp, "w"))
def die(msg, rc=1): print(msg, file=sys.stderr); sys.exit(rc)
def opt(name, default=None):
    for i, a in enumerate(argv):
        if a == name: return argv[i + 1]
        if a.startswith(name + "="): return a.split("=", 1)[1]
    return default
FLAGS_WITH_VALUE = {"-n", "-o", "-p", "-f", "--type", "--namespace", "--field-manager"}
pos = []
i = 0
while i < len(argv):
    a = argv[i]
    if a in FLAGS_WITH_VALUE: i += 2; continue
    if a.startswith("-"): i += 1; continue
    pos.append(a); i += 1
ns = opt("-n") or opt("--namespace")
verb = pos[0]
kind = pos[1] if len(pos) > 1 else ""
name = pos[2] if len(pos) > 2 else ""
for rule in filter(None, os.environ.get("STUB_FAIL", "").split(",")):
    v, k, nm = rule.split(":")
    if fnmatch.fnmatch(verb, v) and fnmatch.fnmatch(kind, k) and fnmatch.fnmatch(name, nm):
        die(f'Error from server (Forbidden): {kind} "{name}" is forbidden')
ignore = "--ignore-not-found" in argv or "--ignore-not-found=true" in argv
def sk(n, nm): return f"{n}/{nm}"
def emit_secret(s):
    o = opt("-o")
    if o == "json": print(json.dumps(s))
    elif o and o.startswith("jsonpath="):
        key = o.split(".data.")[1].rstrip("}")
        print(s.get("data", {}).get(key, ""), end="")
if verb == "config":
    print(os.environ.get("STUB_CONTEXT", "kind-stub")); sys.exit(0)
if verb == "create" and kind in ("ns", "namespace"):
    state["ns"].append(name); save(); sys.exit(0)
if verb == "get" and kind == "secret" and name:
    s = state["secret"].get(sk(ns, name))
    if s is None:
        if ignore: sys.exit(0)
        die(f'Error from server (NotFound): secrets "{name}" not found')
    emit_secret(s); sys.exit(0)
if verb == "get" and kind == "crd":
    if name in state["crd"]: sys.exit(0)
    die("NotFound")
if verb == "get" and kind == "keycloakrealmimport":
    if os.environ.get("STUB_NO_CRD") == "true" and not state["crd"]:
        die('error: the server doesn\'t have a resource type "keycloakrealmimport"')
    if sk(ns, name) in state["kri"]: 
        print(f"keycloakrealmimport.k8s.keycloak.org/{name}") if opt("-o") == "name" else None
        sys.exit(0)
    if ignore: sys.exit(0)
    die("NotFound")
if verb == "create" and not kind:
    for doc in yaml.safe_load_all(sys.stdin.read()):
        if not doc: continue
        assert doc["kind"] == "Secret"
        k = sk(doc["metadata"]["namespace"], doc["metadata"]["name"])
        if k in state["secret"]: die(f'Error from server (AlreadyExists): secrets "{doc["metadata"]["name"]}" already exists')
        state["secret"][k] = {"metadata": doc["metadata"], "data": dict(doc.get("data") or {})}
    save(); sys.exit(0)
if verb == "get" and kind == "secret" and not name:
    print(json.dumps({"items": [v for k, v in state["secret"].items() if k.startswith(ns + "/")]})); sys.exit(0)
if verb == "apply":
    # the document arrives on stdin; a Secret value must not be in argv (argv.log proves it)
    for doc in yaml.safe_load_all(sys.stdin.read()):
        if not doc: continue
        if doc["kind"] == "Secret":
            k = sk(doc["metadata"]["namespace"], doc["metadata"]["name"])
            cur = state["secret"].get(k, {"metadata": doc["metadata"], "data": {}})
            cur["data"].update(doc.get("data") or {})
            for kk, vv in (doc.get("stringData") or {}).items():
                cur["data"][kk] = base64.b64encode(vv.encode()).decode()
            state["secret"][k] = cur
        elif doc["kind"] == "CustomResourceDefinition":
            state["crd"].append(doc["metadata"]["name"])
        elif doc["kind"] == "KeycloakRealmImport":
            state["kri"][sk(doc["metadata"]["namespace"], doc["metadata"]["name"])] = 1
    save(); sys.exit(0)
if verb == "create" and kind == "secret":
    # create secret generic NAME --from-literal=...
    nm = pos[3]
    k = sk(ns, nm)
    if k in state["secret"]: die("AlreadyExists")
    data = {}
    for a in argv:
        if a.startswith("--from-literal="):
            kk, vv = a[len("--from-literal="):].split("=", 1)
            data[kk] = base64.b64encode(vv.encode()).decode()
    state["secret"][k] = {"metadata": {"name": nm, "namespace": ns}, "data": data}; save(); sys.exit(0)
if verb == "patch" and kind == "secret":
    s = state["secret"].get(sk(ns, name))
    if s is None: die("NotFound")
    p = json.loads(opt("-p"))
    if opt("--type") == "json":
        for op in p:
            assert op["op"] == "remove"; s["data"].pop(op["path"].split("/")[-1])
    else:
        s["data"].update(p["data"])
    save(); sys.exit(0)
if verb == "delete":
    if kind in ("ns", "namespace"): sys.exit(0)
    if kind == "secret":
        for nm in pos[2:]:
            if state["secret"].pop(sk(ns, nm), None) is None: die("NotFound")
        save(); sys.exit(0)
    if kind == "keycloakrealmimport":
        state["kri"].pop(sk(ns, name), None); save(); sys.exit(0)
    if kind == "crd":
        state["crd"].remove(name); save(); sys.exit(0)
die(f"stub: unhandled {argv}", 3)
