#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2086  # the python reads its own variables; $pair is "verb resource"
# deploy/crc-proof.sh <rendered dir>: every proof of issue #94 that a browser is not needed for, through the Routes, with TLS verified against CMAPI_CRC_CA. Prints what it measured and
# exits 1 on the first failure. Saves nothing itself: tee it into the review record. A token never reaches an argument: curl reads headers from stdin (--config -), and no value is printed.
# Since #226 every request goes through the front door: one host for the portal and the API, and the API has no Route of its own.
set -euo pipefail
RENDERED=${1:?rendered dir}
CA=${CMAPI_CRC_CA:?the bundle from deploy/crc-trust.sh --mac-ca}
OC=${CMAPI_OC:-oc}
HERE=$(cd "$(dirname "$0")" && pwd)
API=${CMAPI_API_URL:-https://cmapi.apps-crc.testing}
MOCKUP=${CMAPI_MOCKUP_URL:-https://cmapi-mockup.apps-crc.testing}
KC=${CMAPI_KEYCLOAK_URL:-https://keycloak.apps-crc.testing}
# The sign-in of a person with no browser; the scripts test puts a stand-in here, as it does for oc.
LOGIN=${CMAPI_OIDC_LOGIN:-python3 $HERE/oidc-login.py}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
c() { curl -sS -m 15 --cacert "$CA" "$@"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
say() { echo "proof: $*"; }
image=$(cat "$RENDERED/IMAGE"); digest=${image#*@}
portal_image=$(cat "$RENDERED/PORTAL_IMAGE"); portal_digest=${portal_image#*@}

# Admission: each workload pod under restricted-v2, started after the policy existed.
pods=$(oc_ get pods -n cmapi -o json)
printf '%s' "$pods" | python3 -c '
import json,sys
want,want_portal=sys.argv[1:3]; items=json.load(sys.stdin)["items"]; bad=[]; seen=set()
for p in items:
    if p["status"].get("phase") in ("Succeeded","Failed"): continue
    comp=p["metadata"].get("labels",{}).get("app.kubernetes.io/component") or p["metadata"].get("labels",{}).get("cnpg.io/cluster","?")
    seen.add(comp); scc=p["metadata"].get("annotations",{}).get("openshift.io/scc")
    restarts=sum(c.get("restartCount",0) for c in p["status"].get("containerStatuses",[]))
    print("  ",p["metadata"]["name"],"scc",scc,"restarts",restarts,"uid",(p["spec"]["containers"][0].get("securityContext") or {}).get("runAsUser"))
    if scc!="restricted-v2": bad.append(p["metadata"]["name"]+" scc "+str(scc))
    if restarts: bad.append(p["metadata"]["name"]+" restarted")
    if comp in ("api","worker") and not all(want in c.get("imageID","") for c in p["status"]["containerStatuses"]): bad.append(p["metadata"]["name"]+" runs another image")
    if comp=="portal" and not all(want_portal in c.get("imageID","") for c in p["status"]["containerStatuses"]): bad.append(p["metadata"]["name"]+" runs another image than the front door'"'"'s")
missing={"api","worker","portal"}-seen
if missing: bad.append("no pod for "+",".join(sorted(missing)))
sys.exit("; ".join(bad) if bad else 0)' "$digest" "$portal_digest" || fail "pods"
say "pods under restricted-v2, no restarts, api and worker on $digest, the front door on $portal_digest"
# started_after <policy> <component...>: each pod of those components started once the policy existed; prints the policy's creation time.
# Called in an assignment, so that its failure stops the script under set -e.
started_after() {
  local np; np=$(oc_ get networkpolicy "$1" -n cmapi -o 'jsonpath={.metadata.creationTimestamp}'); shift
  printf '%s' "$pods" | python3 -c '
import json,sys
late=[p["metadata"]["name"] for p in json.load(sys.stdin)["items"] if p["metadata"].get("labels",{}).get("app.kubernetes.io/component") in sys.argv[2:] and p["status"].get("startTime","")<sys.argv[1]]
sys.exit("started before the policy existed: "+",".join(late) if late else 0)' "$np" "$@" || fail "policy order"
  echo "$np"
}
np=$(started_after cmapi-metrics api worker); say "api and worker started after NetworkPolicy cmapi-metrics ($np)"
np=$(started_after cmapi-front-door portal); say "the front door started after NetworkPolicy cmapi-front-door ($np)"

# Through the Route, so through the router, the front door and both policies.
[ "$(c -o /dev/null -w '%{http_code}' "$API/healthz")" = 200 ] || fail "the front door's /healthz"; say "the front door answers /healthz through the Route"
version=$(c "$API/api/v1/version"); built=$(printf '%s' "$version" | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"])')
[ "$built" = "$(git rev-parse --short=10 HEAD)" ] || fail "/api/v1/version names $built, not HEAD"; say "/api/v1/version through the front door names commit $built"
# The front door passes the API's paths alone: any other path is the portal's page (deploy/tests/front-door-test.py), never the API's metrics or probe.
for path in /metrics /readyz; do
  got=$(c -o /dev/null -w '%{http_code} %{content_type}' "$API$path")
  case "$got" in "200 text/html"*) ;; *) fail "$path through the Route answers $got, not the portal's page: it reaches the API";; esac
done
say "/metrics and /readyz are not on the Route: the portal's page answers"
[ "$(c -o /dev/null -w '%{http_code}' "$API/api/v1/me")" = 401 ] || fail "/api/v1/me without a token is not 401"; say "/api/v1/me with no token: 401"
# The headers are set once, at the front door (docs/reviews/2026-11-14-issue-226): read them on the page the browser loads first.
headers=$(c -o /dev/null -D - "$API/" | tr '[:upper:]' '[:lower:]')
for h in "strict-transport-security: max-age=63072000; includesubdomains" "x-content-type-options: nosniff" "content-security-policy: default-src 'self';"; do
  case "$headers" in *"$h"*) ;; *) fail "the portal's page has no ${h%%:*} from the front door";; esac
done
say "the portal's page carries the front door's HSTS, nosniff and Content-Security-Policy"
[ "$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "http://${API#https://}/healthz")" = 302 ] || fail "HTTP is not redirected"; say "plain HTTP redirects"
[ "$(c -o /dev/null -w '%{http_code}' "$MOCKUP/portal.html")" = 200 ] || fail "the mockup"; say "the mockup answers (static, no API behind it)"

# The policies are enforced: a Route that answers proves nothing if nothing was ever blocked.
probe_ns=cmapi-np-probe; image_probe=docker.io/nginxinc/nginx-unprivileged@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6
cleanup_probe() {
  oc_ delete pod cmapi-np-target -n cmapi --ignore-not-found --wait=false >/dev/null 2>&1 || true
  oc_ delete namespace "$probe_ns" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup_probe EXIT
oc_ create namespace "$probe_ns" >/dev/null
oc_ run np-probe -n "$probe_ns" --image="$image_probe" --restart=Never --command -- sleep 300 >/dev/null
# The control: a pod in namespace cmapi that no policy selects (no component label), serving on 8080. Since #226 every pod of
# cmapi's own is under a policy, so the control is made here, and removed with the probe.
oc_ run cmapi-np-target -n cmapi --image="$image_probe" --restart=Never --labels=app.kubernetes.io/part-of=cmapi-np-probe >/dev/null
oc_ wait pod/np-probe -n "$probe_ns" --for=condition=Ready --timeout=120s >/dev/null || fail "the probe pod did not start"
oc_ wait pod/cmapi-np-target -n cmapi --for=condition=Ready --timeout=120s >/dev/null || fail "the control pod did not start"
target=$(oc_ get pod cmapi-np-target -n cmapi -o 'jsonpath={.status.podIP}')
[ -n "$target" ] || fail "the control pod has no address"
# The control first: this path must work, or "blocked" below would prove nothing.
oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 "http://$target:8080/" >/dev/null 2>&1 || fail "the probe cannot reach the unselected control pod in cmapi: the checks below would prove nothing"
# blocked <what> <url>: failing is not being blocked. A dropped connection is this image's "download timed out", and a bad address, a refused connection or oc exec itself failing
# each say something else (measured, BusyBox 1.37). A server that accepts and then hangs times out the same way (measured), so the instance must answer the router right after.
blocked() {
  local why
  if why=$(oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 "$2" 2>&1 >/dev/null); then fail "another namespace reaches $1: the policy is not enforced"; fi
  case "$why" in *"wget: download timed out"*) ;; *) fail "the probe of $1 failed, but not by a dropped connection, so this says nothing about the policy: ${why:0:200}";; esac
  [ "$(c -o /dev/null -w '%{http_code}' "$API/api/v1/version")" = 200 ] || fail "the instance does not answer the router after the probe of $1: the timeout may be the server's, not the policy's"
}
blocked "the api's 8080" http://cmapi-api.cmapi.svc:8080/readyz
blocked "the front door's 8080" http://cmapi-portal.cmapi.svc:8080/healthz
say "another namespace's pod reaches an unselected pod of cmapi and is blocked from the api and from the front door (the policies are enforced on OVN-Kubernetes)"
cleanup_probe; trap - EXIT

# The automation client signs in by its service account: the client credentials grant, the secret on stdin. No password of any account.
secret=$(oc_ get secret cmapi-keycloak -n cmapi -o 'jsonpath={.data.automationClientSecret}' | base64 -d)
token=$(printf 'grant_type=client_credentials&client_id=cmapi-automation&scope=openid&client_secret=%s' "$secret" | c -X POST --data @- "$KC/realms/cmapi/protocol/openid-connect/token" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])') || fail "no token for cmapi-automation"
me=$(printf 'header = "Authorization: Bearer %s"\n' "$token" | c --config - "$API/api/v1/me")
printf '%s' "$me" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("proof: /api/v1/me:",d["username"],d["roles"]); sys.exit(0 if d["username"]=="cmapi-automation" and d["roles"]==["cmapi-onboarding"] else 1)' || fail "/api/v1/me"
# No client takes the resource owner password grant (RFC 9700, section 2.4; #181). The one confidential client that had it must answer
# unauthorized_client, which Keycloak decides before it reads the account: so the name is of no account, and the password is not a password.
refused=$(printf 'grant_type=password&client_id=cmapi-automation&username=no-such-account&password=not-a-password&scope=openid&client_secret=%s' "$secret" | c -X POST --data @- "$KC/realms/cmapi/protocol/openid-connect/token" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("error"))') || fail "the token endpoint did not answer the password grant"
[ "$refused" = unauthorized_client ] || fail "cmapi-automation answers the password grant with $refused, not unauthorized_client: the grant is on"
say "cmapi-automation signs in with client credentials, and the password grant is refused (unauthorized_client)"

# Each LDAP test user, signed in through the federation as a browser does: the authorization code grant with PKCE through cmapi-docs, the password
# on stdin and only to Keycloak's login form (deploy/oidc-login.py). The token holds exactly what the owner's table says, and nothing the table does not.
# The table, not the realm's own groups, is what "expected" comes from: a realm that grants the wrong role must not pass by agreeing with itself.
checked=0; tok_noaccess=; tok_viewer=
while IFS=$'\t' read -r uid number groups roles <&3; do
  case "$uid" in \#*|"") continue;; esac
  pw=$(oc_ get secret cmapi-ldap-test-users -n cmapi -o "jsonpath={.data.${uid//./\\.}}" | base64 -d)
  [ -n "$pw" ] || fail "Secret cmapi-ldap-test-users holds no password for $uid"
  t=$(printf '%s\n' "$pw" | $LOGIN --issuer "$KC/realms/cmapi" --client-id cmapi-docs --redirect-uri "$API/docs/oauth2-redirect" --username "$uid" --cacert "$CA") || fail "no token for $uid through LDAP federation"
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
# The server cannot see whether a client verified it. Each container's own libpq says which sslmode its URI and environment come to.
for c in api worker; do
  mode=$(oc_ exec "deploy/cmapi-$c" -n cmapi -c "$c" -- python3 -c 'import os, psycopg; print(next(o.val.decode() for o in psycopg.connect(os.environ["CMAPI_DATABASE_URL"]).pgconn.info if o.keyword == b"sslmode"))') || fail "the $c could not connect to the database to say how it connects"
  [ "$mode" = verify-full ] || fail "the $c connects to the database with sslmode=$mode"
done
say "the api and the worker connect to the database with sslmode=verify-full"

# Prometheus, with no secret on any command line and none in the targets: Thanos Querier's Route, the session's token on stdin.
thanos=$(oc_ get route thanos-querier -n openshift-monitoring -o 'jsonpath={.spec.host}')
query() { printf 'header = "Authorization: Bearer %s"\n' "$(oc_ whoami -t)" | c --config - --get --data-urlencode "query=$1" "https://$thanos/api/v1/query" | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(len(r), sum(float(x["value"][1]) for x in r))'; }
for attempt in $(seq 1 "${CMAPI_PROOF_SCRAPE_TRIES:-20}"); do up=$(query 'up{namespace="cmapi",job=~"cmapi-api|cmapi-worker"}'); [ "$up" = "2 2.0" ] && break; sleep 15; done
[ "$up" = "2 2.0" ] || fail "up for the two targets is: $up"; say "Prometheus scrapes both targets: up = $up (try $attempt)"
# Exactly this: one series with the value 1. No series at all (a target not scraped, a label renamed) must not read as connected.
connected=$(query 'cmapi_cluster_status{namespace="cmapi",cluster_id="CRC",status="connected"}'); [ "$connected" = "1 1.0" ] || fail "the reader is not connected: $connected"; say "cmapi_cluster_status connected"
say "all passed"
