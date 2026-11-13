#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2086  # the python reads its own variables; $pair is "verb resource"
# deploy/crc-proof.sh <rendered dir>: every proof of issue #94 that a browser is not needed for, through the Routes, with TLS verified against CMAPI_CRC_CA. Prints what it measured and
# exits 1 on the first failure. Saves nothing itself: tee it into the review record. A token never reaches an argument: curl reads headers from stdin (--config -), and no value is printed.
set -euo pipefail
RENDERED=${1:?rendered dir}
CA=${CMAPI_CRC_CA:?the bundle from deploy/crc-trust.sh --mac-ca}
OC=${CMAPI_OC:-oc}
HERE=$(cd "$(dirname "$0")" && pwd)
API=${CMAPI_API_URL:-https://cmapi-api.apps-crc.testing}
MOCKUP=${CMAPI_MOCKUP_URL:-https://cmapi-mockup.apps-crc.testing}
KC=${CMAPI_KEYCLOAK_URL:-https://keycloak.apps-crc.testing}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
c() { curl -sS -m 15 --cacert "$CA" "$@"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
say() { echo "proof: $*"; }
image=$(cat "$RENDERED/IMAGE"); digest=${image#*@}

# Admission: each workload pod under restricted-v2, started after the policy existed.
pods=$(oc_ get pods -n cmapi -o json)
printf '%s' "$pods" | python3 -c '
import json,sys
want=sys.argv[1]; items=json.load(sys.stdin)["items"]; bad=[]; seen=set()
for p in items:
    if p["status"].get("phase") in ("Succeeded","Failed"): continue
    comp=p["metadata"].get("labels",{}).get("app.kubernetes.io/component") or p["metadata"].get("labels",{}).get("cnpg.io/cluster","?")
    seen.add(comp); scc=p["metadata"].get("annotations",{}).get("openshift.io/scc")
    restarts=sum(c.get("restartCount",0) for c in p["status"].get("containerStatuses",[]))
    print("  ",p["metadata"]["name"],"scc",scc,"restarts",restarts,"uid",(p["spec"]["containers"][0].get("securityContext") or {}).get("runAsUser"))
    if scc!="restricted-v2": bad.append(p["metadata"]["name"]+" scc "+str(scc))
    if restarts: bad.append(p["metadata"]["name"]+" restarted")
    if comp in ("api","worker") and not all(want in c.get("imageID","") for c in p["status"]["containerStatuses"]): bad.append(p["metadata"]["name"]+" runs another image")
missing={"api","worker","mockup"}-seen
if missing: bad.append("no pod for "+",".join(sorted(missing)))
sys.exit("; ".join(bad) if bad else 0)' "$digest" || fail "pods"
say "pods under restricted-v2, no restarts, api and worker on $digest"
np=$(oc_ get networkpolicy cmapi-metrics -n cmapi -o 'jsonpath={.metadata.creationTimestamp}')
printf '%s' "$pods" | python3 -c '
import json,sys
late=[p["metadata"]["name"] for p in json.load(sys.stdin)["items"] if p["metadata"].get("labels",{}).get("app.kubernetes.io/component") in ("api","worker") and p["status"].get("startTime","")<sys.argv[1]]
sys.exit("started before the policy existed: "+",".join(late) if late else 0)' "$np" || fail "policy order"
say "api and worker started after NetworkPolicy cmapi-metrics ($np)"

# Through the Route, so through the router and the policy.
[ "$(c -o /dev/null -w '%{http_code}' "$API/readyz")" = 200 ] || fail "/readyz"; say "/readyz 200 through the Route"
version=$(c "$API/api/v1/version"); built=$(printf '%s' "$version" | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"])')
[ "$built" = "$(git rev-parse --short=10 HEAD)" ] || fail "/api/v1/version names $built, not HEAD"; say "/api/v1/version names commit $built"
[ "$(c -o /dev/null -w '%{http_code}' "$API/metrics")" = 404 ] || fail "/metrics answers through the Route"; say "/metrics is not on the Route"
[ "$(c -o /dev/null -w '%{http_code}' "$API/api/v1/me")" = 401 ] || fail "/api/v1/me without a token is not 401"; say "/api/v1/me with no token: 401"
[ "$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "http://${API#https://}/readyz")" = 302 ] || fail "HTTP is not redirected"; say "plain HTTP redirects"
[ "$(c -o /dev/null -w '%{http_code}' "$MOCKUP/portal.html")" = 200 ] || fail "the mockup"; say "the mockup answers (static, no API behind it)"

# The policy is enforced: a Route that answers proves nothing if nothing was ever blocked.
probe_ns=cmapi-np-probe; image_probe=docker.io/nginxinc/nginx-unprivileged@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
cleanup_probe() { oc_ delete namespace "$probe_ns" --ignore-not-found --wait=false >/dev/null 2>&1 || true; }
trap cleanup_probe EXIT
oc_ create namespace "$probe_ns" >/dev/null
oc_ run np-probe -n "$probe_ns" --image="$image_probe" --restart=Never --command -- sleep 300 >/dev/null
oc_ wait pod/np-probe -n "$probe_ns" --for=condition=Ready --timeout=120s >/dev/null || fail "the probe pod did not start"
# The control first: the mockup is in the same namespace and no policy selects it, so this path must work, or "blocked" below would prove nothing.
oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 http://cmapi-mockup.cmapi.svc:8080/portal.html >/dev/null 2>&1 || fail "the probe cannot reach the unselected mockup: the check below would prove nothing"
# Failing is not being blocked: a dropped connection is this image's "download timed out", and a bad address, a refused connection or oc exec itself failing each say something else (measured, BusyBox 1.37).
if blocked=$(oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 http://cmapi-api.cmapi.svc:8080/readyz 2>&1 >/dev/null); then fail "another namespace reaches 8080: the policy is not enforced"; fi
case "$blocked" in *"wget: download timed out"*) ;; *) fail "the probe of the api failed, but not by a dropped connection, so this says nothing about the policy: ${blocked:0:200}";; esac
# A server that accepts and then hangs times out the same way (measured), so the api must answer the router right after that timeout.
[ "$(c -o /dev/null -w '%{http_code}' "$API/readyz")" = 200 ] || fail "the api does not answer the router after the probe: the timeout may be the api's, not the policy's"
say "another namespace's pod reaches the mockup and is blocked from the api (the policy is enforced on OVN-Kubernetes)"
cleanup_probe; trap - EXIT

# A sign-in with no browser: the automation client and its bot user, password and secret on stdin.
secret=$(oc_ get secret cmapi-keycloak -n cmapi -o 'jsonpath={.data.automationClientSecret}' | base64 -d)
botpw=$(oc_ get secret cmapi-test-users -n cmapi -o 'jsonpath={.data.bot-user}' | base64 -d)
token=$(printf 'grant_type=password&client_id=cmapi-automation&username=bot-user&scope=openid&client_secret=%s&password=%s' "$secret" "$botpw" | c -X POST --data @- "$KC/realms/cmapi/protocol/openid-connect/token" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])') || fail "no token for bot-user"
me=$(printf 'header = "Authorization: Bearer %s"\n' "$token" | c --config - "$API/api/v1/me")
printf '%s' "$me" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("proof: /api/v1/me:",d["username"],d["roles"]); sys.exit(0 if d["username"]=="bot-user" else 1)' || fail "/api/v1/me"

# Each LDAP test user, signed in through the federation by the same client, password on stdin: the token holds exactly what the owner's table says, and nothing the table does not.
# The table, not the realm's own groups, is what "expected" comes from: a realm that grants the wrong role must not pass by agreeing with itself.
checked=0; tok_noaccess=; tok_viewer=
while IFS=$'\t' read -r uid number groups roles <&3; do
  case "$uid" in \#*|"") continue;; esac
  pw=$(oc_ get secret cmapi-ldap-test-users -n cmapi -o "jsonpath={.data.${uid//./\\.}}" | base64 -d)
  [ -n "$pw" ] || fail "Secret cmapi-ldap-test-users holds no password for $uid"
  t=$(printf 'grant_type=password&client_id=cmapi-automation&username=%s&scope=openid&client_secret=%s&password=%s' "$uid" "$secret" "$pw" | c -X POST --data @- "$KC/realms/cmapi/protocol/openid-connect/token" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])') || fail "no token for $uid through LDAP federation"
  printf '%s' "$t" | python3 -c '
import base64,json,sys
uid,number,groups,roles=sys.argv[1:5]
p=sys.stdin.read().split(".")[1]; c=json.loads(base64.urlsafe_b64decode(p+"="*(-len(p)%4)))
want_groups=sorted("/cmapi/"+g for g in groups.split(",")) if groups!="-" else []
want_roles=sorted(roles.split(",")) if roles!="-" else []
have_groups=sorted(c.get("groups") or [])
have_roles=sorted(((c.get("resource_access") or {}).get("cmapi-nonprod") or {}).get("roles") or [])
bad=[]
if c.get("preferred_username")!=uid: bad.append("username "+str(c.get("preferred_username")))
if have_groups!=want_groups: bad.append("groups "+str(have_groups)+", wanted "+str(want_groups))
if have_roles!=want_roles: bad.append("roles "+str(have_roles)+", wanted "+str(want_roles))
if c.get("employee_id")!=number: bad.append("employee_id "+str(c.get("employee_id"))+", wanted "+number)
sys.exit(uid+": "+"; ".join(bad) if bad else 0)' "$uid" "$number" "$groups" "$roles" || fail "the token of $uid does not match the table"
  case "$uid" in cmapi.noaccess) tok_noaccess=$t;; cmapi.viewer) tok_viewer=$t;; esac
  checked=$((checked+1))
done 3<"$HERE/../examples/cmapi-sso/ldap/test-identities.tsv"
[ "$checked" = 13 ] || fail "$checked test users checked, not 13"
say "13 LDAP test users signed in through the federation; each token holds the table's groups, roles and employee_id"
# 403 means a role is missing only if the same route answers one who holds it.
[ "$(printf 'header = "Authorization: Bearer %s"\n' "$tok_viewer" | c --config - -o /dev/null -w '%{http_code}' "$API/api/v1/clusters")" = 200 ] || fail "cmapi.viewer is not 200 on /api/v1/clusters: the 403 below would prove nothing"
[ "$(printf 'header = "Authorization: Bearer %s"\n' "$tok_noaccess" | c --config - -o /dev/null -w '%{http_code}' "$API/api/v1/clusters")" = 403 ] || fail "cmapi.noaccess is not 403 on /api/v1/clusters"
say "cmapi.noaccess gets 403 on /api/v1/clusters, where cmapi.viewer gets 200"
# The worker must not write: no write right, and a request stops before Git.
for pair in "create namespaces" "patch namespaces" "create rolebindings"; do
  for sa in cmapi-api cmapi-worker; do
    [ "$(oc_ auth can-i $pair --as="system:serviceaccount:cmapi:$sa" 2>/dev/null || true)" = no ] || fail "$sa may $pair"
  done
done
say "api and worker may not create or patch namespaces or create rolebindings"
for pair in "list namespaces" "list resourcequotas"; do [ "$(oc_ auth can-i $pair --as=system:serviceaccount:cmapi-system:cmapi-reader 2>/dev/null || true)" = yes ] || fail "the reader may not $pair"; done
for pair in "get secrets" "create namespaces"; do [ "$(oc_ auth can-i $pair --all-namespaces --as=system:serviceaccount:cmapi-system:cmapi-reader 2>/dev/null || true)" = no ] || fail "the reader may $pair"; done
say "the reader lists what it needs, and reads no Secret and writes nothing"
resp=$(printf 'header = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\n' "$token" | c --config - -w '\n%{http_code}' -X POST -d '{"namespace":"wave1-proof"}' "$API/api/v1/clusters/CRC/namespaces?dryRun=true")
[ "${resp##*$'\n'}" = 422 ] || fail "a namespace plan answered ${resp##*$'\n'}, not 422"
case "$resp" in *cluster-not-writable*) ;; *) fail "the 422 is not cluster-not-writable";; esac
say "a namespace plan stops at 422 cluster-not-writable; dryRun, so nothing could be written even if it passed"

# The database: every client connection of the application, from the server's side, and the migrate container's environment from kind-test.sh's pod.
db=$(oc_ exec cmapi-db-1 -n cmapi -c postgres -- psql -d cmapi -Atc "select count(*) filter (where s.ssl), count(*) filter (where not s.ssl) from pg_stat_ssl s join pg_stat_activity a using (pid) where a.usename='cmapi'")
case "$db" in *"|0") [ "${db%%|*}" -gt 0 ] || fail "no application connections"; say "pg_stat_ssl: application connections on TLS|not: $db";; *) fail "pg_stat_ssl: $db";; esac

# Prometheus, with no secret on any command line and none in the targets: Thanos Querier's Route, the session's token on stdin.
thanos=$(oc_ get route thanos-querier -n openshift-monitoring -o 'jsonpath={.spec.host}')
query() { printf 'header = "Authorization: Bearer %s"\n' "$(oc_ whoami -t)" | c --config - --get --data-urlencode "query=$1" "https://$thanos/api/v1/query" | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(len(r), sum(float(x["value"][1]) for x in r))'; }
for attempt in $(seq 1 "${CMAPI_PROOF_SCRAPE_TRIES:-20}"); do up=$(query 'up{namespace="cmapi",job=~"cmapi-api|cmapi-worker"}'); [ "$up" = "2 2.0" ] && break; sleep 15; done
[ "$up" = "2 2.0" ] || fail "up for the two targets is: $up"; say "Prometheus scrapes both targets: up = $up (try $attempt)"
# Exactly this: one series with the value 1. No series at all (a target not scraped, a label renamed) must not read as connected.
connected=$(query 'cmapi_cluster_status{namespace="cmapi",cluster_id="CRC",status="connected"}'); [ "$connected" = "1 1.0" ] || fail "the reader is not connected: $connected"; say "cmapi_cluster_status connected"
say "all passed"
