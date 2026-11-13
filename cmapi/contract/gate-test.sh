#!/usr/bin/env bash
# Proves the contract gate on the committed document: a change that breaks a client must fail, and a change that adds must pass.
# A gate that passes everything, or fails everything, fails this test.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fail() { echo "gate-test: $*" >&2; exit 1; }

mutate() { # <out> <python statements that change spec>
  python3 - "$HERE/openapi.json" "$1" "$2" <<'PY'
import json, sys
src, out, code = sys.argv[1:]
spec = json.load(open(src))
schemas = spec["components"]["schemas"]
paths = spec["paths"]
exec(code)
json.dump(spec, open(out, "w"))
PY
}

# The same document: no change, so the gate passes.
"$HERE/gate.sh" "$HERE/openapi.json" "$HERE/openapi.json" >"$T/same.txt" 2>&1 || { cat "$T/same.txt" >&2; fail "the gate refused an unchanged document"; }

# Breaking: a response loses a required field, an endpoint goes, a request gains a required field.
n=0
while IFS='|' read -r name code; do
  n=$((n + 1))
  mutate "$T/breaking-$n.json" "$code"
  cmp -s "$HERE/openapi.json" "$T/breaking-$n.json" && fail "the mutation '$name' changed nothing"
  if "$HERE/gate.sh" "$HERE/openapi.json" "$T/breaking-$n.json" >"$T/breaking-$n.txt" 2>&1; then
    cat "$T/breaking-$n.txt" >&2; fail "the gate passed a breaking change: $name"
  fi
  echo "gate-test: refused, as it must: $name"
done <<'CASES'
a response loses the required field version|schemas["Version"]["required"].remove("version"); del schemas["Version"]["properties"]["version"]
an endpoint is removed|del paths["/api/v1/me"]
a request body gains a required field|schemas["SwitchBody"].setdefault("required", []).append("ticket"); schemas["SwitchBody"]["properties"]["ticket"] = {"type": "string"}
CASES
[ "$n" = 3 ] || fail "$n breaking cases ran, not 3"

# Additive: a new endpoint and a new optional response field.
mutate "$T/additive.json" 'paths["/api/v1/added"] = {"get": {"operationId": "added", "summary": "Added", "responses": {"200": {"description": "ok"}}}}; schemas["Version"]["properties"]["builtAt"] = {"type": "string"}'
"$HERE/gate.sh" "$HERE/openapi.json" "$T/additive.json" >"$T/additive.txt" 2>&1 || { cat "$T/additive.txt" >&2; fail "the gate refused an additive change"; }
echo "gate-test: passed, as it must: a new endpoint and a new optional response field"

# The changelog writer, on two released documents: the removed endpoint and the added one are both in the second release.
mkdir -p "$T/released" "$T/out"
cp "$HERE/openapi.json" "$T/released/1.0.0.json"
mutate "$T/released/1.1.0.json" 'del paths["/api/v1/me"]; paths["/api/v1/added"] = {"get": {"operationId": "added", "summary": "Added", "responses": {"200": {"description": "ok"}}}}'
python3 "$HERE/changelog.py" --released "$T/released" --out "$T/out/changelog.json"
python3 - "$T/out/changelog.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
r = d["releases"]
assert [x["version"] for x in r] == ["1.0.0", "1.1.0"], r
assert r[0]["previous"] is None and r[0]["changes"] == [], r[0]
assert r[1]["previous"] == "1.0.0"
paths = {(c["path"], c["level"]) for c in r[1]["changes"]}
assert ("/api/v1/me", 3) in paths, paths          # a removed endpoint is breaking
assert any(p == "/api/v1/added" and lvl == 1 for p, lvl in paths), paths
assert all(c["text"] for c in r[1]["changes"])
print("gate-test: the changelog of two released documents has the removed and the added endpoint")
PY
