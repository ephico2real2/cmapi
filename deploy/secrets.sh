#!/usr/bin/env bash
# deploy/secrets.sh: the Secrets plain YAML cannot generate. Idempotent. Never rotates, never prints a value, never passes
# one as an argument.
#   deploy/secrets.sh [--namespace cmapi] [--realm-namespace keycloak] [--kubectl "oc --kubeconfig=..."]
#                     [--github-app-key FILE --github-app-id N --github-installation-id N] [--no-ldap-bind]
# The realm keeps the values it first imported and an import never overwrites them, so the copy in the Keycloak namespace
# (cmapi-realm-secrets) is the authority for the four client secrets in cmapi-keycloak:
#  - both copies absent and no realm import: generate one set, write the realm's copy first, then ours;
#  - one copy complete and the other absent: copy it across;
#  - both complete and equal: nothing to do;
#  - anything else (a partial copy, two that differ, an import with both copies gone): stop and name the keys; never mint.
# cmapi-keys (cursorKey, linkKey) is written once. cmapi-ldap-bind (bindDN, password) is never written here: the owner
# creates it (docs/11); it must exist in both namespaces with both keys, equal, unless --no-ldap-bind (kind). An existing
# cmapi-github-app is validated (appId, installationId, privateKey) and never replaced; a missing one is written from the
# key file. Written as the deployment design (docs/reviews/2026-11-05-deployment-design.md, D4) decided, from Opus's
# script with Codex's two checks.
set -euo pipefail
NS=cmapi; REALM_NS=keycloak; KEY=; APP_ID=; INST_ID=; KUBECTL=oc; LDAP_BIND=true
while [ $# -gt 0 ]; do case "$1" in
  --namespace) NS=$2; shift 2;; --realm-namespace) REALM_NS=$2; shift 2;; --kubectl) KUBECTL=$2; shift 2;;
  --github-app-key) KEY=$2; shift 2;; --github-app-id) APP_ID=$2; shift 2;; --github-installation-id) INST_ID=$2; shift 2;;
  --no-ldap-bind) LDAP_BIND=false; shift;;
  *) echo "unknown argument $1" >&2; exit 2;; esac; done
# shellcheck disable=SC2086  # KUBECTL may carry --kubeconfig
kc() { $KUBECTL "$@"; }
PAIRS="realmAdminClientSecret:CMAPI_REALM_ADMIN_SECRET directoryClientSecret:CMAPI_DIRECTORY_SECRET svcPaymentsCiSecret:CMAPI_SVC_PAYMENTS_CI_SECRET automationClientSecret:CMAPI_AUTOMATION_SECRET"
rnd() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48; }
b64() { printf '%s' "$1" | base64 | tr -d '\n'; }
get() { kc get secret "$2" -n "$1" -o json 2>/dev/null || true; }
# apply_secret NS NAME: stdin is "key base64value" lines. The document goes to kubectl on stdin, so no value reaches an
# argument list or a process listing.
apply_secret() { { printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: %s, namespace: %s, labels: {app.kubernetes.io/part-of: cmapi}}\ndata:\n' "$2" "$1"
                   while read -r k v; do printf '  %s: %s\n' "$k" "$v"; done; } | kc apply --server-side --field-manager=cmapi-secrets -f - >/dev/null; echo "wrote Secret $1/$2"; }
# keys_of JSON: the data keys whose value is non-empty, one per line
keys_of() { printf '%s' "$1" | python3 -c 'import json,sys; d=sys.stdin.read(); print("\n".join(k for k,v in ((json.loads(d) if d else {}).get("data") or {}).items() if v))'; }

ours=$(get "$NS" cmapi-keycloak); theirs=$(get "$REALM_NS" cmapi-realm-secrets)
verdict=$(OURS="$ours" THEIRS="$theirs" PAIRS="$PAIRS" python3 - <<'PY'
import json,os
pairs=[p.split(":") for p in os.environ["PAIRS"].split()]
o=(json.loads(os.environ["OURS"]) if os.environ["OURS"] else {}).get("data",{}) or {}
t=(json.loads(os.environ["THEIRS"]) if os.environ["THEIRS"] else {}).get("data",{}) or {}
oa,ta=[a for a,_ in pairs],[b for _,b in pairs]
om=[k for k in oa if not o.get(k)]; tm=[k for k in ta if not t.get(k)]
if not o and not t: print("generate")
elif t and tm: print("partial realm copy, missing "+",".join(tm))
elif o and om: print("partial namespace copy, missing "+",".join(om))
elif t and not o: print("from-realm")
elif o and not t: print("from-ours")
else:
    d=[a for a,b in pairs if o[a]!=t[b]]
    print("same" if not d else "copies differ on "+",".join(d))
PY
)
case "$verdict" in
  generate)
    # No Secret anywhere, but the realm was imported: its clients hold values nobody here knows any more.
    if kc get keycloakrealmimport cmapi -n "$REALM_NS" >/dev/null 2>&1; then
      echo "ERROR: KeycloakRealmImport cmapi exists in $REALM_NS and both Secrets are gone. New values would not match the realm. Read the clients' secrets from the realm, or delete the realm and its import first." >&2; exit 1
    fi
    lines=""; for p in $PAIRS; do lines+="${p%%:*} $(b64 "$(rnd)")"$'\n'; done
    while read -r a v; do [ -n "$a" ] || continue; for p in $PAIRS; do [ "${p%%:*}" = "$a" ] && echo "${p##*:} $v"; done; done <<<"$lines" | apply_secret "$REALM_NS" cmapi-realm-secrets
    printf '%s' "$lines" | apply_secret "$NS" cmapi-keycloak ;;
  from-realm)
    THEIRS="$theirs" PAIRS="$PAIRS" python3 -c 'import json,os
t=json.loads(os.environ["THEIRS"])["data"]
for p in os.environ["PAIRS"].split():
    a,b=p.split(":"); print(a,t[b])' | apply_secret "$NS" cmapi-keycloak ;;
  from-ours)
    OURS="$ours" PAIRS="$PAIRS" python3 -c 'import json,os
o=json.loads(os.environ["OURS"])["data"]
for p in os.environ["PAIRS"].split():
    a,b=p.split(":"); print(b,o[a])' | apply_secret "$REALM_NS" cmapi-realm-secrets ;;
  same) echo "realm secrets: both copies present and equal, nothing to do" ;;
  *) echo "ERROR: $verdict. A realm keeps the values it first imported, so nothing is generated. Fix it by hand from the realm's own client secrets." >&2; exit 1 ;;
esac

if [ -z "$(get "$NS" cmapi-keys)" ]; then
  printf 'linkKey %s\ncursorKey %s\n' "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" | apply_secret "$NS" cmapi-keys
else
  echo "cmapi-keys: present, kept"
fi

# The LDAP bind user is the owner's (docs/11, #34): checked, never generated. Both copies must exist, carry bindDN and
# password, and be equal, or Keycloak's federation and the realm sync would disagree.
if [ "$LDAP_BIND" = true ]; then
  lb_ours=$(get "$NS" cmapi-ldap-bind); lb_theirs=$(get "$REALM_NS" cmapi-ldap-bind)
  for pair in "$NS:$lb_ours" "$REALM_NS:$lb_theirs"; do
    n=${pair%%:*}; j=${pair#*:}
    [ -n "$j" ] || { echo "ERROR: Secret $n/cmapi-ldap-bind is missing; the owner creates it (docs/11), this script never does" >&2; exit 1; }
    for k in bindDN password; do keys_of "$j" | grep -qx "$k" || { echo "ERROR: Secret $n/cmapi-ldap-bind lacks $k" >&2; exit 1; }; done
  done
  OURS="$lb_ours" THEIRS="$lb_theirs" python3 -c 'import json,os
o=json.loads(os.environ["OURS"])["data"]; t=json.loads(os.environ["THEIRS"])["data"]
d=[k for k in ("bindDN","password") if o[k]!=t[k]]
raise SystemExit("ERROR: cmapi-ldap-bind differs between the namespaces on "+",".join(d)+"; make them equal by hand, nothing is written" if d else 0)' || exit 1
  echo "cmapi-ldap-bind: present in both namespaces with bindDN and password, equal"
fi

# The GitHub App credential: validated when present (never replaced), written only when absent and a key file is given.
gh_existing=$(get "$NS" cmapi-github-app)
if [ -n "$gh_existing" ]; then
  for k in appId installationId privateKey; do
    keys_of "$gh_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-github-app exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }
  done
  echo "cmapi-github-app: present with appId, installationId and privateKey, kept"
  [ -z "$KEY" ] || echo "note    : --github-app-key ignored, the Secret exists"
elif [ -n "$KEY" ]; then
  [ -n "$APP_ID" ] && [ -n "$INST_ID" ] || { echo "ERROR: --github-app-key needs --github-app-id and --github-installation-id" >&2; exit 2; }
  [ -r "$KEY" ] || { echo "ERROR: cannot read $KEY" >&2; exit 2; }
  mode=$(stat -f '%Lp' "$KEY" 2>/dev/null || stat -c '%a' "$KEY"); case "$mode" in *[1-7][0-7]|*[0-7][1-7]) echo "ERROR: $KEY is mode $mode; make it 0600" >&2; exit 2;; esac
  printf 'appId %s\ninstallationId %s\nprivateKey %s\n' "$(b64 "$APP_ID")" "$(b64 "$INST_ID")" "$(base64 <"$KEY" | tr -d '\n')" | apply_secret "$NS" cmapi-github-app
fi
