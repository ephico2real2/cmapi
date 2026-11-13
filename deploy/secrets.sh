#!/usr/bin/env bash
# deploy/secrets.sh: the Secrets plain YAML cannot generate. Idempotent. Never rotates, never prints a value, never passes
# one as an argument.
#   deploy/secrets.sh (--issuer URL [--ca-file FILE] | --no-issuer-check) [--namespace cmapi] [--realm-namespace keycloak]
#                     [--kubectl "oc --kubeconfig=..."] [--github-app-key FILE --github-app-id N --github-installation-id N]
#                     [--no-ldap-bind] [--test-users]
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
# Before anything is minted the realm itself is asked, with no credential and with TLS verified: GET <issuer>. Keycloak's own 404 is
# the only "absent". A 200 stops the run: a realm exists whose client secrets nobody here knows. Anything else (a timeout, a bad
# certificate, a router's 503 while Keycloak restarts, a 404 that is not Keycloak's) stops it too: "could not tell" is not "no realm".
# --no-issuer-check is for a cluster with no Keycloak (kind); nothing defaults to it, so CRC cannot skip this by forgetting a flag.
# --test-users writes cmapi-test-users once (ola, amy, opal), for the realm sync; it is never rotated.
set -euo pipefail
NS=cmapi; REALM_NS=keycloak; KEY=; APP_ID=; INST_ID=; KUBECTL=oc; LDAP_BIND=true; ISSUER=; CA_FILE=; ISSUER_CHECK=true; TEST_USERS=false
while [ $# -gt 0 ]; do case "$1" in
  --namespace) NS=$2; shift 2;; --realm-namespace) REALM_NS=$2; shift 2;; --kubectl) KUBECTL=$2; shift 2;;
  --github-app-key) KEY=$2; shift 2;; --github-app-id) APP_ID=$2; shift 2;; --github-installation-id) INST_ID=$2; shift 2;;
  --no-ldap-bind) LDAP_BIND=false; shift;;
  --issuer) ISSUER=$2; shift 2;; --ca-file) CA_FILE=$2; shift 2;; --no-issuer-check) ISSUER_CHECK=false; shift;;
  --test-users) TEST_USERS=true; shift;;
  *) echo "unknown argument $1" >&2; exit 2;; esac; done
if [ "$ISSUER_CHECK" = true ] && [ -z "$ISSUER" ]; then echo "ERROR: --issuer is required (or --no-issuer-check on a cluster with no Keycloak)" >&2; exit 2; fi
# The whole URL, and realm cmapi: a 404 for any other realm is also Keycloak's own, and would read as "cmapi is absent" and mint. A glob on the end would pass ?x=/realms/cmapi.
if [ "$ISSUER_CHECK" = true ] && ! [[ "$ISSUER" =~ ^https://[^/?#]+/realms/cmapi$ ]]; then echo "ERROR: --issuer must be https://<Keycloak host>/realms/cmapi, not $ISSUER" >&2; exit 2; fi
if [ -n "$CA_FILE" ] && [ ! -r "$CA_FILE" ]; then echo "ERROR: cannot read the CA file $CA_FILE" >&2; exit 2; fi
# shellcheck disable=SC2086  # KUBECTL may carry --kubeconfig
kc() { $KUBECTL "$@"; }
PAIRS="realmAdminClientSecret:CMAPI_REALM_ADMIN_SECRET directoryClientSecret:CMAPI_DIRECTORY_SECRET svcPaymentsCiSecret:CMAPI_SVC_PAYMENTS_CI_SECRET automationClientSecret:CMAPI_AUTOMATION_SECRET"
rnd() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48; }
b64() { printf '%s' "$1" | base64 | tr -d '\n'; }
# get NS NAME: the object's JSON, empty only when the API says it does not exist. Any other failure (a timeout, a 500, a
# Forbidden) stops the run: "could not read" is not "absent", and treating it so mints new values behind a kept realm.
get() { kc get secret "$2" -n "$1" --ignore-not-found -o json; }
# True when the realm import exists. No such type on this server (no Keycloak operator, kind) is "no import"; any other
# failure stops the run for the same reason as get.
realm_import_exists() {
  local out rc=0
  out=$(kc get keycloakrealmimport cmapi -n "$REALM_NS" --ignore-not-found -o name 2>&1) || rc=$?
  if [ "$rc" -ne 0 ]; then
    case "$out" in *"doesn't have a resource type"*) return 1;; esac
    echo "ERROR: cannot tell whether KeycloakRealmImport cmapi exists in $REALM_NS: $out" >&2; exit 1
  fi
  [ -n "$out" ]
}
# issuer_state: "present", "absent", or a reason it cannot tell, for the realm at $ISSUER. --cacert only adds what is verified against; TLS is never off.
issuer_state() {
  local body code rc=0
  body=$(mktemp)
  code=$(curl -sS -m 15 ${CA_FILE:+--cacert "$CA_FILE"} -o "$body" -w '%{http_code}' "$ISSUER" 2>/dev/null) || rc=$?
  if [ "$rc" -ne 0 ]; then rm -f "$body"; echo "no answer (curl rc $rc)"; return; fi
  BODY="$body" CODE="$code" REALM="${ISSUER##*/}" python3 -c 'import json,os
try: d=json.load(open(os.environ["BODY"]))
except ValueError: d=None
c=os.environ["CODE"]
if c=="200" and isinstance(d,dict) and d.get("realm")==os.environ["REALM"]: print("present")
elif c=="404" and d=={"error":"Realm does not exist"}: print("absent")
else: print("HTTP "+c+" that is neither a realm document nor Keycloak'"'"'s own 404")'
  rm -f "$body"
}
# apply_secret NS NAME: stdin is "key base64value" lines. The document goes to kubectl on stdin, so no value reaches an
# argument list or a process listing. Create, never apply: every write here fills an absent Secret, so a Secret that
# appeared since the read (a second run, a person) stops the run instead of being overwritten.
apply_secret() { { printf 'apiVersion: v1\nkind: Secret\ntype: Opaque\nmetadata: {name: %s, namespace: %s, labels: {app.kubernetes.io/part-of: cmapi}}\ndata:\n' "$2" "$1"
                   while read -r k v; do printf '  %s: %s\n' "$k" "$v"; done; } | kc create -f - >/dev/null; echo "wrote Secret $1/$2"; }
# keys_of JSON: the data keys whose value is non-empty, one per line
keys_of() { printf '%s' "$1" | python3 -c 'import json,sys; d=sys.stdin.read(); print("\n".join(k for k,v in ((json.loads(d) if d else {}).get("data") or {}).items() if v))'; }

# Read and validate every existing object before the first create. A late read error or partial Secret must not leave an
# otherwise unrelated Secret created by this run.
ours=$(get "$NS" cmapi-keycloak); theirs=$(get "$REALM_NS" cmapi-realm-secrets)
keys_existing=$(get "$NS" cmapi-keys)
users_existing=$(get "$NS" cmapi-test-users)
if [ "$LDAP_BIND" = true ]; then
  lb_ours=$(get "$NS" cmapi-ldap-bind); lb_theirs=$(get "$REALM_NS" cmapi-ldap-bind)
fi
gh_existing=$(get "$NS" cmapi-github-app)
verdict=$(OURS="$ours" THEIRS="$theirs" PAIRS="$PAIRS" python3 - <<'PY'
import json,os
pairs=[p.split(":") for p in os.environ["PAIRS"].split()]
# Whether the object exists, not whether its data is truthy: an existing Secret with no data is a partial copy, never absent.
oe,te=bool(os.environ["OURS"]),bool(os.environ["THEIRS"])
o=(json.loads(os.environ["OURS"]) if oe else {}).get("data",{}) or {}
t=(json.loads(os.environ["THEIRS"]) if te else {}).get("data",{}) or {}
oa,ta=[a for a,_ in pairs],[b for _,b in pairs]
om=[k for k in oa if not o.get(k)]; tm=[k for k in ta if not t.get(k)]
if not oe and not te: print("generate")
elif te and tm: print("partial realm copy, missing "+",".join(tm))
elif oe and om: print("partial namespace copy, missing "+",".join(om))
elif te and not oe: print("from-realm")
elif oe and not te: print("from-ours")
else:
    d=[a for a,b in pairs if o[a]!=t[b]]
    print("same" if not d else "copies differ on "+",".join(d))
PY
)
case "$verdict" in
  generate|from-realm|from-ours|same) ;;
  *) echo "ERROR: $verdict. A realm keeps the values it first imported, so nothing is generated. Fix it by hand from the realm's own client secrets." >&2; exit 1 ;;
esac
if [ -n "$keys_existing" ]; then
  for k in cursorKey linkKey; do
    keys_of "$keys_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-keys exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }
  done
fi
if [ "$LDAP_BIND" = true ]; then
  for pair in "$NS:$lb_ours" "$REALM_NS:$lb_theirs"; do
    n=${pair%%:*}; j=${pair#*:}
    [ -n "$j" ] || { echo "ERROR: Secret $n/cmapi-ldap-bind is missing; the owner creates it (docs/11), this script never does" >&2; exit 1; }
    for k in bindDN password; do keys_of "$j" | grep -qx "$k" || { echo "ERROR: Secret $n/cmapi-ldap-bind lacks $k" >&2; exit 1; }; done
  done
  OURS="$lb_ours" THEIRS="$lb_theirs" python3 -c 'import json,os
o=json.loads(os.environ["OURS"])["data"]; t=json.loads(os.environ["THEIRS"])["data"]
d=[k for k in ("bindDN","password") if o[k]!=t[k]]
raise SystemExit("ERROR: cmapi-ldap-bind differs between the namespaces on "+",".join(d)+"; make them equal by hand, nothing is written" if d else 0)' || exit 1
fi
if [ -n "$gh_existing" ]; then
  for k in appId installationId privateKey; do
    keys_of "$gh_existing" | grep -qx "$k" || { echo "ERROR: Secret $NS/cmapi-github-app exists but lacks $k; it is never replaced automatically: fix or delete it by hand" >&2; exit 1; }
  done
elif [ -n "$KEY" ]; then
  if [ -z "$APP_ID" ] || [ -z "$INST_ID" ]; then echo "ERROR: --github-app-key needs --github-app-id and --github-installation-id" >&2; exit 2; fi
  [ -r "$KEY" ] || { echo "ERROR: cannot read $KEY" >&2; exit 2; }
  # The GNU form first: GNU's -f reports the file system on stdout before failing on %Lp, while BSD's stat refuses -c with nothing on stdout (#90).
  mode=$(stat -c '%a' "$KEY" 2>/dev/null || stat -f '%Lp' "$KEY"); case "$mode" in *[1-7][0-7]|*[0-7][1-7]) echo "ERROR: $KEY is mode $mode; make it 0600" >&2; exit 2;; esac
fi
case "$verdict" in
  generate)
    # No Secret anywhere, but the realm was imported: its clients hold values nobody here knows any more.
    if realm_import_exists; then
      echo "ERROR: KeycloakRealmImport cmapi exists in $REALM_NS and both Secrets are gone. New values would not match the realm. Read the clients' secrets from the realm, or delete the realm and its import first." >&2; exit 1
    fi
    if [ "$ISSUER_CHECK" = true ]; then
      state=$(issuer_state)
      case "$state" in
        absent) ;;
        present) echo "ERROR: realm ${ISSUER##*/} exists at $ISSUER and both Secrets are gone. New values would not match the realm. Read the clients' secrets from the realm, or delete the realm first." >&2; exit 1 ;;
        *) echo "ERROR: cannot tell whether the realm exists at $ISSUER: $state. Nothing is generated. Run this again when Keycloak answers." >&2; exit 1 ;;
      esac
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
esac

if [ -z "$keys_existing" ]; then
  printf 'linkKey %s\ncursorKey %s\n' "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" | apply_secret "$NS" cmapi-keys
else
  echo "cmapi-keys: present, kept"
fi

# Local test users for the realm sync. Generated once: the sync sets these passwords on every run, so they must not change.
if [ "$TEST_USERS" = true ]; then
  if [ -z "$users_existing" ]; then
    printf 'ola %s\namy %s\nopal %s\n' "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" "$(b64 "$(rnd)")" | apply_secret "$NS" cmapi-test-users
  else
    echo "cmapi-test-users: present, kept"
  fi
fi

# The LDAP bind user is the owner's (docs/11, #34): checked, never generated. Both copies must exist, carry bindDN and
# password, and be equal, or Keycloak's federation and the realm sync would disagree.
if [ "$LDAP_BIND" = true ]; then
  echo "cmapi-ldap-bind: present in both namespaces with bindDN and password, equal"
fi

# The GitHub App credential: validated when present (never replaced), written only when absent and a key file is given.
if [ -n "$gh_existing" ]; then
  echo "cmapi-github-app: present with appId, installationId and privateKey, kept"
  [ -z "$KEY" ] || echo "note    : --github-app-key ignored, the Secret exists"
elif [ -n "$KEY" ]; then
  printf 'appId %s\ninstallationId %s\nprivateKey %s\n' "$(b64 "$APP_ID")" "$(b64 "$INST_ID")" "$(base64 <"$KEY" | tr -d '\n')" | apply_secret "$NS" cmapi-github-app
fi
