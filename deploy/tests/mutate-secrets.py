#!/usr/bin/env python3
"""Mutants of deploy/secrets.sh against deploy/secrets-test.sh on the stub kubectl: a mutant that survives is a claim its test
cannot fail on. From the review of PR #89 (docs/reviews/2026-11-05-pr89/opus/tests/mutate-secrets.py), where 7 of 12 survived.
No cluster. Needs PyYAML in this Python. usage: mutate-secrets.py [<dir holding secrets.sh and secrets-test.sh>]
Exit 0 only when the unmutated script passes and every mutant is killed."""
import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(HERE)
GEN = '    printf \'%s\' "$lines" | apply_secret "$NS" cmapi-keycloak ;;'
IMPORT_GUARD = "    if realm_import_exists; then"
# A write ahead of one check: the case that names that check must see it.
EARLY_WRITE = '  printf \'CMAPI_REALM_ADMIN_SECRET %s\\n\' "$(b64 "$(rnd)")" | apply_secret "$REALM_NS" cmapi-realm-secrets >/dev/null\n'
KEYS_CHECK = 'if [ -n "$keys_existing" ]; then\n'
LDAP_CHECK = '  for pair in "$NS:$lb_ours" "$REALM_NS:$lb_theirs"; do\n'
APP_CHECK = 'if [ -n "$gh_existing" ]; then\n  for k in appId'
KEY_FILE_CHECK = 'elif [ -n "$KEY" ]; then\n  if [ -z "$APP_ID" ]'
MUTANTS = {
    "base (no mutation)": [],
    "A prints every generated value to the terminal": [(GEN, '    printf \'%s\' "$lines"; printf \'%s\' "$lines" | apply_secret "$NS" cmapi-keycloak ;;')],
    "B cmapi-keys rotated on every run": [('if [ -z "$keys_existing" ]; then', "if true; then")],
    "C a complete cmapi-github-app is replaced from the key file": [(
        '  [ -z "$KEY" ] || echo "note    : --github-app-key ignored, the Secret exists"',
        '  [ -z "$KEY" ] || kc delete secret cmapi-github-app -n "$NS" >/dev/null; [ -z "$KEY" ] || printf \'appId %s\\ninstallationId %s\\nprivateKey %s\\n\' "$(b64 "$APP_ID")" "$(b64 "$INST_ID")" "$(base64 <"$KEY" | tr -d \'\\n\')" | apply_secret "$NS" cmapi-github-app')],
    "D cmapi-ldap-bind is generated when missing, then the run still stops": [(
        '    [ -n "$j" ] || { echo "ERROR: Secret $n/cmapi-ldap-bind is missing',
        '    [ -n "$j" ] || printf \'bindDN %s\\npassword %s\\n\' "$(b64 x)" "$(b64 "$(rnd)")" | apply_secret "$n" cmapi-ldap-bind >/dev/null\n    [ -n "$j" ] || { echo "ERROR: Secret $n/cmapi-ldap-bind is missing')],
    "E the realm copy is minted before the import guard": [(
        IMPORT_GUARD,
        '    printf \'CMAPI_REALM_ADMIN_SECRET %s\\n\' "$(b64 "$(rnd)")" | apply_secret "$REALM_NS" cmapi-realm-secrets >/dev/null\n' + IMPORT_GUARD)],
    "F from-ours mints new realm values instead of copying ours": [(
        "a,b=p.split(\":\"); print(b,o[a])' | apply_secret \"$REALM_NS\" cmapi-realm-secrets ;;",
        "a,b=p.split(\":\"); print(b,\"bWludGVk\")' | apply_secret \"$REALM_NS\" cmapi-realm-secrets ;;")],
    "G a partial namespace copy is overwritten from the realm instead of stopping": [(
        'elif oe and om: print("partial namespace copy, missing "+",".join(om))', 'elif oe and om: print("from-realm")')],
    "H ours written before the realm's copy": [
        (GEN, "    :;;"),
        ('    while read -r a v; do [ -n "$a" ] || continue;', '    printf \'%s\' "$lines" | apply_secret "$NS" cmapi-keycloak\n    while read -r a v; do [ -n "$a" ] || continue;')],
    "I the same value for all four clients": [
        ('lines+="${p%%:*} $(b64 "$(rnd)")"$\'\\n\'; done', 'lines+="${p%%:*} $one"$\'\\n\'; done'),
        ('    lines=""; for p in $PAIRS', '    one=$(b64 "$(rnd)"); lines=""; for p in $PAIRS')],
    "J (control) a partial realm copy no longer stops": [('elif te and tm: print("partial realm copy, missing "+",".join(tm))', "elif False: pass")],
    "K (control) the key file mode is not checked": [('case "$mode" in *[1-7][0-7]|*[0-7][1-7]) echo "ERROR: $KEY is mode $mode; make it 0600" >&2; exit 2;; esac', ":")],
    "L (control) the import guard is gone": [(IMPORT_GUARD, "    if false; then")],
    "M a failed read counts as absent again (the original get)": [(
        'get() { kc get secret "$2" -n "$1" --ignore-not-found -o json; }', 'get() { kc get secret "$2" -n "$1" -o json 2>/dev/null || true; }')],
    "N a failed import read counts as no import again": [(
        '    echo "ERROR: cannot tell whether KeycloakRealmImport cmapi exists in $REALM_NS: $out" >&2; exit 1', "    return 1")],
    "O a partial cmapi-keys is kept silently again": [(
        '    keys_of "$keys_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-keys exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }',
        "    :")],
    "P an existing Secret with no data counts as absent again": [('if not oe and not te: print("generate")', 'if not o and not t: print("generate")')],
    "Q apply again instead of create: a stale read can overwrite": [(
        'kc create -f - >/dev/null; echo "wrote Secret $1/$2"; }', 'kc apply --server-side --field-manager=cmapi-secrets -f - >/dev/null; echo "wrote Secret $1/$2"; }')],
    "R a Secret written before the check of an existing cmapi-keys": [(KEYS_CHECK, KEYS_CHECK + EARLY_WRITE)],
    "S a Secret written before the cmapi-ldap-bind check": [(LDAP_CHECK, EARLY_WRITE + LDAP_CHECK)],
    "T a Secret written before the check of an existing app Secret": [(APP_CHECK, APP_CHECK.replace("then\n", "then\n" + EARLY_WRITE))],
    "U a Secret written before the key file's checks": [(KEY_FILE_CHECK, KEY_FILE_CHECK.replace("then\n", "then\n" + EARLY_WRITE))],
    "W the issuer check is not made": [('    if [ "$ISSUER_CHECK" = true ]; then\n      state=$(issuer_state)', '    if false; then\n      state=$(issuer_state)')],
    "X anything but a 200 reads as absent": [('        *) echo "ERROR: cannot tell whether the realm exists at $ISSUER: $state. Nothing is generated. Run this again when Keycloak answers." >&2; exit 1 ;;', '        *) ;;')],
    "Y any 404 reads as absent": [("""elif c=="404" and d=={"error":"Realm does not exist"}: print("absent")""", """elif c=="404": print("absent")""")],
    "Z a curl failure reads as absent": [('if [ "$rc" -ne 0 ]; then rm -f "$body"; echo "no answer (curl rc $rc)"; return; fi', 'if [ "$rc" -ne 0 ]; then rm -f "$body"; echo absent; return; fi')],
    "AD an issuer naming another realm is asked": [('if [ "$ISSUER_CHECK" = true ] && ! [[ "$ISSUER" =~ ^https://[^/?#]+/realms/cmapi$ ]]; then', 'if false; then')],
    "AE a glob on the end of the issuer": [('! [[ "$ISSUER" =~ ^https://[^/?#]+/realms/cmapi$ ]]', '! [[ "$ISSUER" =~ /realms/cmapi$ ]]')],
    "AA forgetting the flag skips the check": [('if [ "$ISSUER_CHECK" = true ] && [ -z "$ISSUER" ]; then echo "ERROR: --issuer is required (or --no-issuer-check on a cluster with no Keycloak)" >&2; exit 2; fi', 'if [ -z "$ISSUER" ]; then ISSUER_CHECK=false; fi')],
    "AB verification off": [('code=$(curl -sS -m 15 ${CA_FILE:+--cacert "$CA_FILE"} -o', 'code=$(curl -k -sS -m 15 ${CA_FILE:+--cacert "$CA_FILE"} -o')],
    "AC the issuer is asked after the first write": [
        ('    if [ "$ISSUER_CHECK" = true ]; then\n      state=$(issuer_state)', '    printf \'CMAPI_REALM_ADMIN_SECRET %s\\n\' "$(b64 "$(rnd)")" | apply_secret "$REALM_NS" cmapi-realm-secrets >/dev/null\n    if [ "$ISSUER_CHECK" = true ]; then\n      state=$(issuer_state)')],
    "AD the test users rotated on every run": [('  if [ -z "$users_existing" ]; then', '  if true; then')],
    "V the app Secret read after the writes again": [
        ('gh_existing=$(get "$NS" cmapi-github-app)\n', "gh_existing=\n"),
        ("# The GitHub App credential: validated", 'gh_existing=$(get "$NS" cmapi-github-app)\n# The GitHub App credential: validated')],
}


def one(item):
    name, edits = item
    t = tempfile.mkdtemp(prefix="cmapi-mut.")
    try:
        for f in ("secrets.sh", "secrets-test.sh"):
            shutil.copy(os.path.join(SRC, f), t)
        p = os.path.join(t, "secrets.sh")
        s = open(p).read()
        for old, new in edits:
            # A mutant whose text no longer matches proves nothing, so it stops the run rather than passing as killed.
            assert s.count(old) == 1, (name, old, s.count(old))
            s = s.replace(old, new)
        open(p, "w").write(s)
        state = os.path.join(t, "state")
        os.mkdir(state)
        stub = os.path.join(HERE, "secrets-stub")
        env = dict(os.environ, STUB_DIR=state, STUB_PY=sys.executable, STUB_KUBECTL=os.path.join(stub, "kubectl-stub.py"), STUB_NO_CRD="true")
        r = subprocess.run([os.path.join(t, "secrets-test.sh"), os.path.join(stub, "stub.sh")], env=env, capture_output=True, text=True)
        return name, r.returncode, [line.strip() for line in r.stdout.splitlines() if "FAIL" in line]
    finally:
        shutil.rmtree(t)


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    rows = list(pool.map(one, MUTANTS.items()))
survived = 0
for name, rc, fails in rows:
    base = not MUTANTS[name]
    print(f"{'passes' if rc == 0 else 'FAILS' if base else 'killed':9} rc={rc} {name}" if base or rc != 0 else f"SURVIVED  rc=0 {name}")
    if fails:
        print(f"            first: {fails[0][:110]}")
    if (rc != 0) == base:
        survived += 1
print(f"mutants: {len(rows) - 1}, wrong: {survived}")
sys.exit(1 if survived else 0)
