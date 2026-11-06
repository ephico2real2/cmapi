#!/usr/bin/env python3
"""Mutants of deploy/secrets.sh against deploy/secrets-test.sh on the stub kubectl. A survivor is a claim its test cannot fail on.
usage: mutate-secrets.py <dir holding secrets.sh and secrets-test.sh>"""
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1]
PY = os.path.join(HERE, "..", "work", "venv", "bin", "python")
GEN = '    printf \'%s\' "$lines" | apply_secret "$NS" cmapi-keycloak ;;'
MUTANTS = {
 "base (no mutation)": [],
 "A prints every generated value to the terminal": [(GEN, '    printf \'%s\' "$lines"; printf \'%s\' "$lines" | apply_secret "$NS" cmapi-keycloak ;;')],
 "B cmapi-keys rotated on every run": [('if [ -z "$(get "$NS" cmapi-keys)" ]; then', 'if true; then')],
 "C a complete cmapi-github-app is replaced from the key file": [('  [ -z "$KEY" ] || echo "note    : --github-app-key ignored, the Secret exists"',
     '  [ -z "$KEY" ] || kc delete secret cmapi-github-app -n "$NS" >/dev/null; [ -z "$KEY" ] || printf \'appId %s\\ninstallationId %s\\nprivateKey %s\\n\' "$(b64 "$APP_ID")" "$(b64 "$INST_ID")" "$(base64 <"$KEY" | tr -d \'\\n\')" | apply_secret "$NS" cmapi-github-app')],
 "D cmapi-ldap-bind is generated when missing, then the run still stops": [('    [ -n "$j" ] || { echo "ERROR: Secret $n/cmapi-ldap-bind is missing',
     '    [ -n "$j" ] || printf \'bindDN %s\\npassword %s\\n\' "$(b64 x)" "$(b64 "$(rnd)")" | apply_secret "$n" cmapi-ldap-bind >/dev/null\n    [ -n "$j" ] || { echo "ERROR: Secret $n/cmapi-ldap-bind is missing')],
 "E the realm copy is minted before the import guard": [('    if kc get keycloakrealmimport cmapi -n "$REALM_NS" >/dev/null 2>&1; then',
     '    printf \'CMAPI_REALM_ADMIN_SECRET %s\\n\' "$(b64 "$(rnd)")" | apply_secret "$REALM_NS" cmapi-realm-secrets >/dev/null\n    if kc get keycloakrealmimport cmapi -n "$REALM_NS" >/dev/null 2>&1; then')],
 "F from-ours mints new realm values instead of copying ours": [("a,b=p.split(\":\"); print(b,o[a])' | apply_secret \"$REALM_NS\" cmapi-realm-secrets ;;",
     "a,b=p.split(\":\"); print(b,\"bWludGVk\")' | apply_secret \"$REALM_NS\" cmapi-realm-secrets ;;")],
 "G a partial namespace copy is overwritten from the realm instead of stopping": [('elif o and om: print("partial namespace copy, missing "+",".join(om))', 'elif o and om: print("from-realm")')],
 "H ours written before the realm's copy": [(GEN, '    :;;'), ('    while read -r a v; do [ -n "$a" ] || continue;', '    printf \'%s\' "$lines" | apply_secret "$NS" cmapi-keycloak\n    while read -r a v; do [ -n "$a" ] || continue;')],
 "I the same value for all four clients": [('lines+="${p%%:*} $(b64 "$(rnd)")"$\'\\n\'; done', 'lines+="${p%%:*} $one"$\'\\n\'; done'), ('    lines=""; for p in $PAIRS', '    one=$(b64 "$(rnd)"); lines=""; for p in $PAIRS')],
 "J (control) a partial realm copy no longer stops": [('elif t and tm: print("partial realm copy, missing "+",".join(tm))', 'elif False: pass')],
 "K (control) the key file mode is not checked": [('case "$mode" in *[1-7][0-7]|*[0-7][1-7]) echo "ERROR: $KEY is mode $mode; make it 0600" >&2; exit 2;; esac', ':')],
 "L (control) the import guard is gone": [('if kc get keycloakrealmimport cmapi -n "$REALM_NS" >/dev/null 2>&1; then', 'if false; then')],
}
if len(sys.argv) > 2 and sys.argv[2] == "fixed":
    MUTANTS["B cmapi-keys rotated on every run"] = [('if [ -z "$keys_existing" ]; then', 'if true; then')]
    MUTANTS["E the realm copy is minted before the import guard"] = [('    if realm_import_exists; then', '    printf \'CMAPI_REALM_ADMIN_SECRET %s\\n\' "$(b64 "$(rnd)")" | apply_secret "$REALM_NS" cmapi-realm-secrets >/dev/null\n    if realm_import_exists; then')]
    MUTANTS["L (control) the import guard is gone"] = [('    if realm_import_exists; then', '    if false; then')]
    MUTANTS["M a failed read counts as absent again (the original get)"] = [('get() { kc get secret "$2" -n "$1" --ignore-not-found -o json; }', 'get() { kc get secret "$2" -n "$1" -o json 2>/dev/null || true; }')]
    MUTANTS["N a failed import read counts as no import again"] = [('    echo "ERROR: cannot tell whether KeycloakRealmImport cmapi exists in $REALM_NS: $out" >&2; exit 1', '    return 1')]
    MUTANTS["O a partial cmapi-keys is kept silently again"] = [('    keys_of "$keys_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-keys exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }', '    :')]
rows = []
for name, edits in MUTANTS.items():
    t = tempfile.mkdtemp(prefix="mut", dir=os.environ.get("TMPDIR"))
    for f in ("secrets.sh", "secrets-test.sh"): shutil.copy(os.path.join(SRC, f), t)
    p = os.path.join(t, "secrets.sh"); s = open(p).read()
    for old, new in edits:
        assert s.count(old) == 1, (name, old, s.count(old))
        s = s.replace(old, new)
    open(p, "w").write(s)
    state = os.path.join(t, "state"); os.mkdir(state)
    env = dict(os.environ, STUB_DIR=state, STUB_PY=PY, STUB_KUBECTL=os.path.join(HERE, "stub", "kubectl-stub.py"), STUB_NO_CRD="true")
    r = subprocess.run([os.path.join(t, "secrets-test.sh"), os.path.join(HERE, "stub", "stub.sh")], env=env, capture_output=True, text=True)
    fails = [l.strip() for l in r.stdout.splitlines() if "FAIL" in l]
    rows.append((name, r.returncode, fails))
    shutil.rmtree(t)
for name, rc, fails in rows:
    verdict = "SURVIVED" if rc == 0 else "killed"
    print(f"{verdict:9} rc={rc} {name}" + (f"\n            first: {fails[0][:110]}" if fails else ""))
