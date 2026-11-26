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
# A plan is the API's slowest call: the front door gives it 60 s (cmapi-portal-ui/nginx/cmapi/proxy-api.conf) and the Route 130 s
# (environments/crc/40-routes.yaml). The proof waits as long as the Route, so a slow plan gets nginx's own answer, never a client
# timeout first. On CRC a first plan answered 200 after 27.7 s while 15 s stopped the run (#275).
PLAN_SECONDS=${CMAPI_PROOF_PLAN_SECONDS:-130}
c_plan() { curl -sS -m "$PLAN_SECONDS" --cacert "$CA" "$@"; }
fail() { echo "FAIL: $*" >&2; exit 1; }
say() { echo "proof: $*"; }
# Checked before anything runs: curl takes -m 0 as no limit at all, and a word only at the plan, after the probes.
case $PLAN_SECONDS in 0*|*[!0-9]*) fail "CMAPI_PROOF_PLAN_SECONDS is a whole number of seconds above 0, not '$PLAN_SECONDS'";; esac
# The run's start (#425): docs/13's step 23 passes the time on the first line of step 2's preflight.txt, written before any step
# writes to the cluster or loads the Mac. A restart before it is reported and passes; one at or after it fails. Unset, every restart
# fails, as before. Set, it must be a UTC time as the run prints it, so a lost record stops here rather than excusing anything.
if [ -n "${CMAPI_PROOF_SINCE+set}" ]; then
  python3 -c 'import datetime,sys; datetime.datetime.strptime(sys.argv[1],"%Y-%m-%dT%H:%M:%SZ")' "$CMAPI_PROOF_SINCE" 2>/dev/null \
    || fail "CMAPI_PROOF_SINCE is the run's start as a UTC time, YYYY-MM-DDTHH:MM:SSZ, not '$CMAPI_PROOF_SINCE'"
fi
image=$(cat "$RENDERED/IMAGE"); digest=${image#*@}
portal_image=$(cat "$RENDERED/PORTAL_IMAGE"); portal_digest=${portal_image#*@}

# Admission: each workload pod under restricted-v2, Ready, started after the policy existed, and not restarted during the run.
# A container's restart is dated by its state.running.startedAt, "the time at which the container was last (re-)started" (the Pod API):
# it is there for every running container, where lastState can be empty and restartCount can go back to 0 after a node restart.
# A container that is not running is not Ready, and fails on that.
pods=$(oc_ get pods -n cmapi -o json)
printf '%s' "$pods" | python3 -c '
import datetime,json,sys
want,want_portal,since=sys.argv[1:4]; items=json.load(sys.stdin)["items"]; bad=[]; seen=set()
def at(t):
    try: return datetime.datetime.strptime(t or "","%Y-%m-%dT%H:%M:%SZ")
    except ValueError: return None
start=at(since) if since else None
for p in items:
    if p["status"].get("phase") in ("Succeeded","Failed"): continue
    name=p["metadata"]["name"]
    comp=p["metadata"].get("labels",{}).get("app.kubernetes.io/component") or p["metadata"].get("labels",{}).get("cnpg.io/cluster","?")
    seen.add(comp); scc=p["metadata"].get("annotations",{}).get("openshift.io/scc")
    statuses=p["status"].get("containerStatuses",[])
    restarts=sum(c.get("restartCount",0) for c in statuses)
    print("  ",name,"scc",scc,"restarts",restarts,"uid",(p["spec"]["containers"][0].get("securityContext") or {}).get("runAsUser"))
    if scc!="restricted-v2": bad.append(name+" scc "+str(scc))
    if not any(c.get("type")=="Ready" and c.get("status")=="True" for c in p["status"].get("conditions",[])): bad.append(name+" not Ready")
    if restarts and not since: bad.append(name+" restarted")
    # Init containers too: a migrate that failed and ran again is a restart, and the kubelet counts it there, not in containerStatuses.
    # A finished init container is dated by the start of its last attempt, terminated.startedAt; a regular one is dated only while it runs.
    # A count of 0 does not clear a container that came up since the run began in a pod from before it: that count can go back to 0.
    born=at(p["status"].get("startTime"))
    for kind,c in [("container",c) for c in statuses]+[("init container",c) for c in p["status"].get("initContainerStatuses",[])] if since else []:
        state=c.get("state") or {}; running=state.get("running") or {}; done=state.get("terminated") or {}
        last=(c.get("lastState") or {}).get("terminated") or {}
        began=at(running.get("startedAt") or (done.get("startedAt") if kind=="init container" and done.get("exitCode")==0 else None))
        if not c.get("restartCount",0) and not (began is not None and born is not None and born<start<=began): continue
        now=("running since "+running["startedAt"]) if running.get("startedAt") else ("last run started "+done["startedAt"]) if began is not None else "not running"
        said="%s %s: %s restarts, last terminated %s, %s, exit %s; %s" % (kind,c.get("name"),c.get("restartCount",0),last.get("finishedAt","unrecorded"),last.get("reason","no reason recorded"),last.get("exitCode","unrecorded"),now)
        if began is None or began>=start: bad.append(name+" restarted during the run, which began "+since+" ("+said+")")
        else: print("   ",name,"restarted before the run, which began",since,"("+said+"): reported, not failed")
    if comp in ("api","worker") and not all(want in c.get("imageID","") for c in p["status"]["containerStatuses"]): bad.append(name+" runs another image")
    if comp=="portal" and not all(want_portal in c.get("imageID","") for c in p["status"]["containerStatuses"]): bad.append(name+" runs another image than the front door'"'"'s")
missing={"api","worker","portal"}-seen
if missing: bad.append("no pod for "+",".join(sorted(missing)))
sys.exit("; ".join(bad) if bad else 0)' "$digest" "$portal_digest" "${CMAPI_PROOF_SINCE:-}" || fail "pods"
restarts_said="no restarts"; [ -z "${CMAPI_PROOF_SINCE:-}" ] || restarts_said="no restart since the run began at $CMAPI_PROOF_SINCE"
say "pods under restricted-v2 and Ready, $restarts_said, api and worker on $digest, the front door on $portal_digest"
# started_after <policy> <component...>: each pod of those components started once the policy existed; prints the policy's creation time.
# Called in an assignment, so that its failure stops the script under set -e.
started_after() {
  # Explicit: bash clears set -e inside $(...), where this runs, so a failed read would otherwise leave "" and pass every pod.
  local np; np=$(oc_ get networkpolicy "$1" -n cmapi -o 'jsonpath={.metadata.creationTimestamp}') || fail "NetworkPolicy $1 cannot be read"
  [ -n "$np" ] || fail "NetworkPolicy $1 has no creation time"; shift
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
# The api writes nothing. The worker is the one writer (delivery.mode apply, #157), and only inside the admission policy of
# environments/crc/deliverer/: RBAC cannot scope create to names that do not exist yet, so the policy is what is proven here.
for pair in "create namespaces" "patch namespaces" "create rolebindings"; do
  [ "$(oc_ auth can-i $pair --as=system:serviceaccount:cmapi:cmapi-api 2>/dev/null || true)" = no ] || fail "cmapi-api may $pair"
done
say "the api may not create or patch namespaces or create rolebindings"
# A server-side dry run as the worker: it is authorized and admitted as the real request would be, and persists nothing.
as_worker=--as=system:serviceaccount:cmapi:cmapi-worker
ns_doc() { printf 'apiVersion: v1\nkind: Namespace\nmetadata:\n  name: %s\n  labels: {cmapi.net/managed: "%s"}\n' "$1" "$2"; }
contained() {   # contained <what> <why>: refused, and by the policy's own message, not by something that says nothing about it
  case "$2" in *"cmapi-deliverer may only touch namespaces labelled cmapi.net/managed=true"*) ;; *) fail "$1 was refused, but not by cmapi-deliverer-managed-only: ${2:0:200}";; esac
}
if why=$(ns_doc cmapi-proof-unmanaged false | oc_ apply --server-side --dry-run=server --field-manager=cmapi-wave1 "$as_worker" -f - 2>&1 >/dev/null); then
  fail "the worker may create a namespace that is not labelled cmapi.net/managed=true: the policy does not contain it"
fi
contained "an unmanaged namespace" "$why"
ns_doc cmapi-proof-managed true | oc_ apply --server-side --dry-run=server --field-manager=cmapi-wave1 "$as_worker" -f - >/dev/null || fail "the worker may not create a namespace labelled cmapi.net/managed=true: no request could be delivered"
if why=$(oc_ label namespace default cmapi.net/proof=x --dry-run=server "$as_worker" 2>&1 >/dev/null); then
  fail "the worker may label namespace default: another project's namespace is not contained"
fi
contained "a label on namespace default" "$why"
say "the worker creates a namespace only with cmapi.net/managed=true, and may not touch one without it (cmapi-deliverer-managed-only, server dry runs)"
# list and watch nodes: the allocatable of the Capacity tab (#302, core/clients/nodes.py); without it the tab says "nodes not readable".
for pair in "list namespaces" "list resourcequotas" "list nodes" "watch nodes"; do [ "$(oc_ auth can-i $pair --as=system:serviceaccount:cmapi-system:cmapi-reader 2>/dev/null || true)" = yes ] || fail "the reader may not $pair"; done
for pair in "get secrets" "create namespaces"; do [ "$(oc_ auth can-i $pair --all-namespaces --as=system:serviceaccount:cmapi-system:cmapi-reader 2>/dev/null || true)" = no ] || fail "the reader may $pair"; done
say "the reader lists what it needs, and reads no Secret and writes nothing"
# The live usage (#310, usage.source thanos): the reader's two grants in openshift-monitoring, each by cmapi's own RoleBinding. A
# SubjectAccessReview names the reader's groups without system:authenticated: impersonation (--as) always adds that group, and a
# cluster may grant monitoring to it (on CRC another project's chart binds cluster-monitoring-view to system:authenticated), which
# would hide a missing grant here. Check the same named resource outside the granted namespace as a scope control.
sar() {   # sar <namespace> <group> <resource> <subresource> <name>: "<allowed> <reason>" for the reader alone
  printf '{"apiVersion":"authorization.k8s.io/v1","kind":"SubjectAccessReview","spec":{"user":"system:serviceaccount:cmapi-system:cmapi-reader","groups":["system:serviceaccounts","system:serviceaccounts:cmapi-system"],"resourceAttributes":{"verb":"get","namespace":"%s","group":"%s","resource":"%s","subresource":"%s","name":"%s"}}}' "$@" \
    | oc_ create -o 'go-template={{if .status.evaluationError}}inconclusive{{else}}{{.status.allowed}} {{.status.reason}}{{end}}' -f -
}
granted() {   # granted <binding> <sar args>: allowed, and by that RoleBinding of openshift-monitoring
  local got; got=$(sar "${@:2}") || fail "a SubjectAccessReview for the reader failed"
  case "$got" in "true "*"RoleBinding \"$1/openshift-monitoring\""*) ;; *) fail "the reader may not get ${4}/${6} in $2 by RoleBinding $1: $got";; esac
}
granted cmapi-reader-thanos-route openshift-monitoring route.openshift.io routes "" thanos-querier
granted cmapi-reader-metrics-api openshift-monitoring monitoring.coreos.com prometheuses api k8s
scope=$(sar openshift-user-workload-monitoring monitoring.coreos.com prometheuses api k8s) || fail "monitoring scope review failed"
case "$scope" in "false "*) ;; *) fail "expected get on prometheuses/api k8s to be refused outside openshift-monitoring: $scope";; esac

# Use the CA source of crc-reader-import.sh and the query options of ThanosQuerier.
thanos=$(oc_ get route thanos-querier -n openshift-monitoring -o 'jsonpath={.spec.host}' --as=system:serviceaccount:cmapi-system:cmapi-reader)
[ -n "$thanos" ] || fail "the reader could not discover the Thanos Route host"
reader_query() (
  local ca_file reader_token
  ca_file=$(mktemp) || return 1
  trap 'rm -f "$ca_file"' EXIT
  oc_ get configmap kube-root-ca.crt -n cmapi-system -o 'jsonpath={.data.ca\.crt}' >"$ca_file" || return 1
  reader_token=$(oc_ create token cmapi-reader -n cmapi-system --duration=10m) || return 1
  printf 'header = "Authorization: Bearer %s"\n' "$reader_token" | curl -sS -m 15 --fail --cacert "$ca_file" --config - --get \
    --data-urlencode 'query=count(kube_resourcequota)' --data-urlencode partial_response=false --data-urlencode dedup=true --data-urlencode timeout=10s \
    "https://$thanos/api/v1/query"
)
quotas=$(reader_query | python3 -c '
import json, sys
body = json.load(sys.stdin)
if body.get("status") != "success" or body.get("warnings"):
    sys.exit("Thanos returned an error or warning")
data = body["data"]
if data.get("resultType") != "vector" or len(data["result"]) != 1:
    sys.exit("expected one count series")
series = data["result"][0]
if series.get("metric") != {} or len(series["value"]) != 2:
    sys.exit("invalid count series")
count = series["value"][1]
if not isinstance(count, str) or not count.isascii() or not count.isdecimal() or int(count) < 1:
    sys.exit("expected a positive quota count")
print(count)') || fail "the Thanos Querier did not return a clean positive quota count for the reader"
say "the reader has the two cmapi Thanos grants in openshift-monitoring: count(kube_resourcequota) = $quotas"
# The Policies tab's premise (#302, #387): the API reads Kyverno's reports in wgpolicyk8s.io/v1alpha2 and finds the group by discovery
# (core/clients/policyreports.py), so without it the tab reads "Kyverno not installed". Read as the reader, as the API reads: the
# served groups, then the request of the API's own probe. openreports.io, where a later Kyverno writes its reports (#382), is recorded.
as_reader=--as=system:serviceaccount:cmapi-system:cmapi-reader
served=$(oc_ get --raw /apis "$as_reader" | python3 -c '
import json,sys
g={x["name"]:[v["version"] for v in x["versions"]] for x in json.load(sys.stdin)["groups"]}
print(",".join(g.get("wgpolicyk8s.io",[])) or "not served", ",".join(g.get("openreports.io",[])) or "not served", sep="\t")') \
  || fail "discovery as cmapi-reader gave no list of the served groups"
wgpolicy=${served%%$'\t'*}; openreports=${served#*$'\t'}
case ",$wgpolicy," in *,v1alpha2,*) ;; *) fail "discovery as cmapi-reader does not serve wgpolicyk8s.io/v1alpha2 (wgpolicyk8s.io: $wgpolicy; openreports.io: $openreports): the Policies tab reads \"Kyverno not installed\" (#382)";; esac
reports=$(oc_ get --raw /apis/wgpolicyk8s.io/v1alpha2 "$as_reader" | python3 -c 'import json,sys; print(" ".join(sorted(r["name"] for r in json.load(sys.stdin)["resources"] if "/" not in r["name"])))') \
  || fail "GET /apis/wgpolicyk8s.io/v1alpha2 as cmapi-reader gave no list of its resources"
# The RBAC half (#387): the API lists and watches each kind in every namespace, and a 403 reads "no access to the reports".
for kind in clusterpolicyreports policyreports; do
  case " $reports " in *" $kind "*) ;; *) fail "wgpolicyk8s.io/v1alpha2 serves '$reports', without $kind";; esac
  [ "$(oc_ auth can-i list "$kind.wgpolicyk8s.io" --all-namespaces "$as_reader" 2>/dev/null || true)" = yes ] \
    || fail "cmapi-reader may not list $kind.wgpolicyk8s.io in every namespace: the Policies tab reads \"no access to the reports\""
done
say "discovery, as cmapi-reader, serves wgpolicyk8s.io/v1alpha2 with $reports, the reports of the Policies tab; openreports.io: $openreports"
# A plan reads the Git folder through the GitHub adapter and the token in Secret cmapi-git-bot, and dryRun writes nothing: no request,
# no branch, no namespace. The namespace's required keys are CRC's metadata-keys.yaml's.
resp=$(printf 'header = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\n' "$token" | c_plan --config - -w '\n%{http_code}' -X POST -d '{"namespace":"abc-proof-plan-dev","tier":"small","labels":{"company.net/mnemonic":"abc","company.net/lob":"amgsst","company.net/cl":"1","cmapi.net/team":"platform"},"annotations":{"cmapi.net/team-dl":"platform@ephico2real.com"},"justification":"crc-proof dry run"}' "$API/api/v1/clusters/CRC/namespaces?dryRun=true") \
  || fail "the dry-run namespace plan got no answer: curl exit $? (28 is no answer within CMAPI_PROOF_PLAN_SECONDS, $PLAN_SECONDS s)"
[ "${resp##*$'\n'}" = 200 ] || fail "a dry-run namespace plan answered ${resp##*$'\n'}, not 200: ${resp:0:300}"
printf '%s' "${resp%$'\n'*}" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("changes") else 1)' || fail "the dry-run plan names no file it would write"
[ -z "$(oc_ get namespace abc-proof-plan-dev --ignore-not-found -o name)" ] || fail "a dry run left namespace abc-proof-plan-dev on the cluster"
say "a dry-run namespace plan reads Git and answers 200 with its files, and writes nothing to the cluster"

# The database: every client connection of the application, from the server's side, and the migrate container's environment from kind-test.sh's pod.
# As role cnpg_metrics_exporter, which holds pg_monitor and nothing else: enough to read pg_stat_ssl and pg_stat_activity for every
# session, and no superuser. CNPG (1.28.3 and later) maps the instance's OS user, the namespace's arbitrary UID on OpenShift, to it
# ("cnpg_metrics_exporter <uid> cnpg_metrics_exporter") as it does to postgres. With no -U, psql asks for a role named after the UID (#278).
db=$(oc_ exec cmapi-db-1 -n cmapi -c postgres -- psql -U cnpg_metrics_exporter -d cmapi -Atc "select count(*) filter (where s.ssl), count(*) filter (where not s.ssl) from pg_stat_ssl s join pg_stat_activity a using (pid) where a.usename='cmapi'")
case "$db" in *"|0") [ "${db%%|*}" -gt 0 ] || fail "no application connections"; say "pg_stat_ssl: application connections on TLS|not: $db";; *) fail "pg_stat_ssl: $db";; esac
# The server cannot see whether a client verified it. Each container's own libpq says which sslmode its URI and environment come to.
for c in api worker; do
  mode=$(oc_ exec "deploy/cmapi-$c" -n cmapi -c "$c" -- python3 -c 'import os, psycopg; print(next(o.val.decode() for o in psycopg.connect(os.environ["CMAPI_DATABASE_URL"]).pgconn.info if o.keyword == b"sslmode"))') || fail "the $c could not connect to the database to say how it connects"
  [ "$mode" = verify-full ] || fail "the $c connects to the database with sslmode=$mode"
done
say "the api and the worker connect to the database with sslmode=verify-full"

# Prometheus, with no secret on any command line and none in the targets: Thanos Querier's Route, the session's token on stdin.
prom() { printf 'header = "Authorization: Bearer %s"\n' "$(oc_ whoami -t)" | c --config - --get --data-urlencode "query=$1" "https://$thanos/api/v1/query"; }
# Each series as job=value, sorted: one series per target, named. A count and a sum alone would read two api series and no
# worker as both targets (#280 review).
by_job() { prom "$1" | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(" ".join(sorted(x["metric"].get("job","no-job")+"="+x["value"][1] for x in r)))'; }
for attempt in $(seq 1 "${CMAPI_PROOF_SCRAPE_TRIES:-20}"); do up=$(by_job 'up{namespace="cmapi",job=~"cmapi-api|cmapi-worker"}'); [ "$up" = "cmapi-api=1 cmapi-worker=1" ] && break; sleep 15; done
[ "$up" = "cmapi-api=1 cmapi-worker=1" ] || fail "up for the two targets is: $up"; say "Prometheus scrapes both targets: up = $up (try $attempt)"
# Exactly this: one series with the value 1 for each of the two targets, since the api and the worker each run a registry and
# export the gauge (#280). A missing series (a target not scraped, a label renamed) or one target not connected must not pass.
connected=$(by_job 'cmapi_cluster_status{namespace="cmapi",cluster_id="CRC",status="connected",job=~"cmapi-api|cmapi-worker"}'); [ "$connected" = "cmapi-api=1 cmapi-worker=1" ] || fail "the reader is not connected on both targets: $connected"; say "cmapi_cluster_status connected on the api and the worker"
# On a legacy-to-bounded migration the old client can still report connected.
# Its unannotated import has no expiry series. Check each registry before cleanup.
bounded=$(by_job 'cmapi_cluster_token_expiry_seconds{namespace="cmapi",cluster_id="CRC",job=~"cmapi-api|cmapi-worker"} > bool 0')
[ "$bounded" = "cmapi-api=1 cmapi-worker=1" ] || fail "the bounded CRC import is not current on both targets: $bounded"
say "the api and the worker have observed a current bounded CRC import"
say "all passed"
