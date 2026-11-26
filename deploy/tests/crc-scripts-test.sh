#!/usr/bin/env bash
# shellcheck disable=SC2015  # ok and bad here never fail, so A && ok || bad is if-then-else
# deploy/tests/crc-scripts-test.sh [<deploy dir>]: deploy/crc-{image,trust,reader-import,backup,rollback,proof}.sh on stubs of oc, curl and tmutil, for each thing they claim
# they can stop on, and for what they must never do: a credential on an argument list, a delete that does not name one object, a dump's path or content in the output. No cluster.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); SRC=$(cd "${1:-$HERE/..}" && pwd); W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
want() { local label=$1 rc=$2 got=$3; if [ "$got" = "$rc" ]; then ok "$label"; else bad "$label: rc $got, not $rc"; fi; }
REAL_KUBECTL=$(command -v kubectl) || { echo "kubectl is needed: the stub renders the API's answers with its output templates"; exit 1; }; export REAL_KUBECTL
TOKEN=sha256~stub-token-value-never-to-be-seen; SECRETVAL=stub-client-secret-never-to-be-seen; DUMP_MARK=stub-dump-content-never-to-be-seen
mkdir -p "$W/bin" "$W/repo/deploy" "$W/repo/examples"; cp "$SRC"/crc-*.sh "$W/repo/deploy/"; cp -R "$SRC/manifests" "$W/repo/deploy/"; cp -R "$SRC/../examples/cmapi-sso" "$W/repo/examples/"; export ARGV_LOG=$W/argv.log TOKEN SECRETVAL DUMP_MARK
mkdir -p "$W/repo/cmapi/src/cmapi/core"
cp "$SRC/../cmapi/src/cmapi/core/cluster_tokens.py" "$W/repo/cmapi/src/cmapi/core/"

mkdir -p "$W/repo/deploy/kind-import"
cp "$SRC/kind-import/import-secret.py" "$SRC/kind-import/write-import.sh" "$W/repo/deploy/kind-import/"
openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/ca.pem" -subj "/CN=stub CA" -days 2 2>/dev/null
# The ingress bundle as measured on CRC: the site's certificate, then its CA.
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$W/ingress-ca.key" -out "$W/ingress-ca.pem" -subj "/CN=ingress-operator@1" -days 2 2>/dev/null
openssl req -newkey rsa:2048 -nodes -keyout "$W/leaf.key" -out "$W/leaf.csr" -subj "/CN=*.apps-crc.testing" 2>/dev/null
printf 'basicConstraints=critical,CA:FALSE\n' >"$W/leaf.ext"; openssl x509 -req -in "$W/leaf.csr" -CA "$W/ingress-ca.pem" -CAkey "$W/ingress-ca.key" -CAcreateserial -days 2 -extfile "$W/leaf.ext" -out "$W/leaf.pem" 2>/dev/null
cat "$W/leaf.pem" "$W/ingress-ca.pem" >"$W/ingress-bundle.pem"; export STUB_CA=$W/ca.pem STUB_INGRESS=$W/ingress-bundle.pem
cat >"$W/bin/oc" <<'OC'
#!/usr/bin/env bash
printf 'oc %s\n' "$*" >>"$ARGV_LOG"
s="$*"
# The object as the API returns it, printed with the caller's output template by the real client: no cluster, no kubeconfig.
render() { KUBECONFIG=/dev/null "$REAL_KUBECTL" label --local -f "$1" cmapi-stub=1 -o "$2"; }
case "$s" in
  "get secret keycloak-tls -n keycloak -o jsonpath={.data.ca\.crt}") base64 <"$STUB_CA"; exit 0;;
  "get cm default-ingress-cert"*) cat "$STUB_INGRESS"; exit 0;;
  # crc-image.sh (#545): the pull secret's type, GHCR's answer through the cluster's importer, the import, and the image stream tag. Each answer
  # is the object the API returns, rendered with the script's own output template by a real kubectl, offline, so a wrong path in the script fails here.
  "get secret cmapi-ghcr-pull -n cmapi --ignore-not-found -o jsonpath={.type}") [ -n "${STUB_NO_PULL_SECRET:-}" ] || printf '%s' "${STUB_PULL_SECRET_TYPE:-kubernetes.io/dockerconfigjson}"; exit 0;;
  # The proof's SubjectAccessReviews for the reader's Thanos grants (#310): each allowed by cmapi's own RoleBinding. The same API resource is refused
  # in another namespace. A review that names system:authenticated is allowed by a binding to everyone, as on CRC, so it proves nothing.
  "create -o go-template={{if .status.evaluationError}}inconclusive{{else}}{{.status.allowed}} {{.status.reason}}{{end}} -f -") body=$(cat); printf '%s\n' "$body" >>"$ARGV_LOG.sar"
    case "$body" in *system:authenticated*) printf 'true RBAC: allowed by ClusterRoleBinding "everyone"'; exit 0;; esac
    case "$body" in
      *'"name":"thanos-querier"'*) printf '%s' "${STUB_SAR_ROUTE-true RBAC: allowed by RoleBinding \"cmapi-reader-thanos-route/openshift-monitoring\" of Role \"cmapi-reader-thanos-route\" to ServiceAccount \"cmapi-reader/cmapi-system\"}";;
      *'"namespace":"openshift-user-workload-monitoring","group":"monitoring.coreos.com","resource":"prometheuses","subresource":"api","name":"k8s"'*) printf '%s' "${STUB_SAR_UWM-false }";;
      *'"namespace":"openshift-monitoring","group":"monitoring.coreos.com","resource":"prometheuses","subresource":"api","name":"k8s"'*) printf '%s' "${STUB_SAR_API-true RBAC: allowed by RoleBinding \"cmapi-reader-metrics-api/openshift-monitoring\" of Role \"cluster-monitoring-metrics-api\" to ServiceAccount \"cmapi-reader/cmapi-system\"}";;
      *'"resource":"localsubjectaccessreviews"'*) printf '%s' "${STUB_SAR_CHECK-true RBAC: allowed by RoleBinding \"cmapi-reader-grant-check/openshift-monitoring\" of Role \"cmapi-reader-grant-check\" to ServiceAccount \"cmapi-reader/cmapi-system\"}";;
      *) echo "stub oc: unhandled review $body" >&2; exit 3;;
    esac; exit 0;;
  "create token cmapi-reader -n cmapi-system --duration=10m") printf 'reader.%s\n' "$TOKEN"; exit 0;;
  "create -f - -o jsonpath="*|"create -f - -o go-template="*) [ -z "${STUB_CREATE_ERROR:-}" ] || { echo "$STUB_CREATE_ERROR" >&2; exit 1; }; python3 "$STUB_IMAGES_PY" isi >"$ARGV_LOG.response" || exit 1; render "$ARGV_LOG.response" "${*: -1}"; exit;;
  "import-image cmapi:sha-"*|"import-image cmapi-portal:sha-"*) [ "${STUB_IMPORT_RC:-0}" = 0 ] || { echo "error: tag failed: ${STUB_REGISTRY_ERROR:-stub}" >&2; exit "$STUB_IMPORT_RC"; }
    printf '%s\n' "$@" >"$ARGV_LOG.imported"; echo "imagestream.image.openshift.io/stub imported"; exit 0;;
  "get istag cmapi:sha-"*|"get istag cmapi-portal:sha-"*)
    if python3 "$STUB_IMAGES_PY" istag "$3" >"$ARGV_LOG.response"; then render "$ARGV_LOG.response" "${*: -1}"; exit; fi
    case "$s" in *--ignore-not-found*) exit 0;; esac; echo "Error from server (NotFound): imagestreamtags.image.openshift.io \"${3%% *}\" not found" >&2; exit 1;;
  "get route thanos-querier"*) printf 'thanos.stub'; exit 0;;
  "whoami -t") printf '%s\n' "$TOKEN"; exit 0;;
  "get secret cmapi-cluster-crc -n cmapi-imports --ignore-not-found -o jsonpath={.metadata.resourceVersion}") echo 1; exit 0;;
  "get configmap kube-root-ca.crt"*) cat "$STUB_CA"; exit 0;;
  "create token cmapi-reader -n cmapi-system --duration=168h"|"create token cmapi-reader -n cmapi-system --duration=1h")
    life=604800; [ "${*: -1}" = "--duration=1h" ] && life=3600
    [ -z "${STUB_NO_TOKEN:-}" ] || exit 1
    issued=$(date +%s)
    payload=$(printf '{"sub":"system:serviceaccount:cmapi-system:cmapi-reader","iat":%s,"exp":%s}' "$issued" "$((issued + life))" | base64 | tr -d '=\n' | tr '+/' '-_')
    printf 'stub.%s.%s\n' "$payload" "$TOKEN"; exit 0;;
  "apply --server-side --field-manager=crc-reader-import.sh --force-conflicts -f -") cat >"$ARGV_LOG.applied"; exit 0;;
  "get pod postgres-0 -n keycloak -o json") cat <<'J'
{"spec":{"containers":[{"name":"postgres","image":"registry.redhat.io/rhel9/postgresql-16:latest","resources":{"limits":{"memory":"512Mi"}},"env":[{"name":"POSTGRESQL_USER","valueFrom":{"secretKeyRef":{"name":"keycloak-db","key":"user"}}},{"name":"POSTGRESQL_PASSWORD","value":"literal-value-never-to-be-seen"}]}]}}
J
    exit 0;;
  "get pod postgres-0 -n keycloak -o jsonpath"*) printf '512Mi'; exit 0;;
  "adm top pod postgres-0"*) echo "postgres-0 5m ${STUB_DB_USED:-100Mi}"; exit 0;;
  "exec postgres-0"*"select current_setting"*) echo "${STUB_DB_SLOTS:-40}"; exit 0;;
  "exec postgres-0"*"select count(*) from realm"*) echo "${STUB_LIVE_REALMS:-6}"; exit 0;;
  "exec postgres-0"*"pg_dump"*) [ -n "${STUB_DUMP_FAIL:-}" ] && { printf 'PGDMP-part'; echo "pg_dump: error: connection lost" >&2; exit 1; }; [ -n "${STUB_DUMP_EMPTY:-}" ] && exit 0; printf 'PGDMP%s' "$DUMP_MARK"; exit 0;;
  "exec -i postgres-0"*"--list"*) cat >/dev/null; [ -n "${STUB_LIST_FAIL:-}" ] && exit 1; echo 90; exit 0;;
  "exec -i postgres-0"*"-t realm"*) cat >/dev/null; echo "${STUB_DUMP_REALMS:-6}"; exit 0;;
  "exec -i postgres-0"*"pg_restore -f /dev/null"*) cat >/dev/null; [ -n "${STUB_READ_FAIL:-}" ] && { echo "pg_restore: error: could not read from input file: end of file" >&2; exit 1; }; exit 0;;
  "get secret cmapi-keycloak -n cmapi -o jsonpath"*) printf '%s' "$SECRETVAL" | base64; exit 0;;
  "get pvc cmapi-db-1"*) printf 'pv-1'; exit 0;;
  "get pv pv-1"*) printf '%s' "${STUB_PV_WHO:-cmapi/cmapi-db-1/Released}"; exit 0;;
  # The proof's containment checks (#157): server dry runs as the worker, refused by cmapi-deliverer-managed-only unless labelled managed.
  "apply --server-side --dry-run=server --field-manager=cmapi-wave1 --as=system:serviceaccount:cmapi:cmapi-worker -f -")
    case "$(cat)" in
      *'cmapi.net/managed: "true"'*) exit "${STUB_MANAGED_RC:-0}";;
      *) echo "${STUB_UNMANAGED_ERR-The namespaces \"cmapi-proof-unmanaged\" is invalid: : ValidatingAdmissionPolicy 'cmapi-deliverer-managed-only' with binding 'cmapi-deliverer-managed-only' denied request: cmapi-deliverer may only touch namespaces labelled cmapi.net/managed=true}" >&2; exit "${STUB_UNMANAGED_RC:-1}";;
    esac;;
  "label namespace default "*"--as=system:serviceaccount:cmapi:cmapi-worker"*)
    echo "${STUB_DEFAULT_ERR-Error from server (Invalid): namespaces \"default\" is invalid: : ValidatingAdmissionPolicy 'cmapi-deliverer-managed-only' denied request: cmapi-deliverer may only touch namespaces labelled cmapi.net/managed=true}" >&2; exit "${STUB_DEFAULT_RC:-1}";;
  "get namespaces -l cmapi.net/managed=true -o name") printf '%s' "${STUB_MANAGED_LEFT:-}"; exit 0;;
  "get namespace abc-proof-plan-dev --ignore-not-found -o name") printf '%s' "${STUB_PLAN_NS:-}"; exit 0;;
  delete*|label*|"create namespace"*|"run np-probe"*|"wait pod/np-probe"*|"run cmapi-np-target -n cmapi "*|"wait pod/cmapi-np-target -n cmapi "*) exit 0;;
  "get pods -n cmapi -o json") python3 -c 'import json,os
img=os.environ.get("STUB_IMAGE_ID","sha256:aaaa"); portal=os.environ.get("STUB_PORTAL_IMAGE_ID","sha256:pppp"); scc=os.environ.get("STUB_SCC","restricted-v2"); r=int(os.environ.get("STUB_RESTARTS","0")); start=os.environ.get("STUB_START","2026-11-06T10:00:00Z")
# Each container as the kubelet reports it: running since its last (re-)start, and the last termination once it has restarted. STUB_NOT_READY names a pod whose Ready is False.
def pod(n,c,i,t=start,rc=r,running=None,last=None):
    cs={"name":c,"restartCount":rc,"imageID":"x@"+i,"state":{"running":{"startedAt":running or t}} if running!="" else {"waiting":{"reason":"CrashLoopBackOff"}}}
    if last: cs["lastState"]={"terminated":{"exitCode":0,"finishedAt":last,"reason":"Completed","startedAt":t}}
    ready="False" if n==os.environ.get("STUB_NOT_READY") else "True"
    st={"phase":"Running","startTime":t,"conditions":[{"type":"Ready","status":ready}],"containerStatuses":[cs]}
    # The api and the worker run migrate first, as on CRC; STUB_MIGRATE_RESTARTS and STUB_MIGRATE_STARTED are its count and its last run.
    if c in ("api","worker"): st["initContainerStatuses"]=[{"name":"migrate","restartCount":int(os.environ.get("STUB_MIGRATE_RESTARTS","0")),"state":{"terminated":{"exitCode":0,"reason":"Completed","startedAt":os.environ.get("STUB_MIGRATE_STARTED",t),"finishedAt":os.environ.get("STUB_MIGRATE_STARTED",t)}}}]
    return {"metadata":{"name":n,"labels":{"app.kubernetes.io/component":c},"annotations":{"openshift.io/scc":scc}},"spec":{"containers":[{}]},"status":st}
# The CloudNativePG instance, labelled as on CRC (component database), which no step of docs/13 recreates (#425).
db_rc=int(os.environ.get("STUB_CMAPI_DB_RESTARTS",r))
db=pod("cmapi-db-1","database","sha256:dddd",rc=db_rc,running=os.environ.get("STUB_CMAPI_DB_RUNNING"),last=os.environ.get("STUB_CMAPI_DB_LAST","2026-11-06T09:44:56Z") if db_rc else None)
items=[pod("a","api",img),pod("w","worker",img),db]+([] if os.environ.get("STUB_NO_PORTAL") else [pod("p","portal",portal,os.environ.get("STUB_PORTAL_START",start))])
print(json.dumps({"items":items}))'; exit 0;;
  "get networkpolicy cmapi-metrics"*|"get networkpolicy cmapi-front-door"*) case "$*" in *"${STUB_NP_GONE:-none}"*) echo "Error from server (NotFound)" >&2; exit 1;; esac; printf '2026-11-06T09:00:00Z'; exit 0;;
  "get pod cmapi-np-target -n cmapi -o jsonpath"*) printf '%s' "${STUB_TARGET_IP-10.0.0.9}"; exit 0;;
  "exec np-probe"*"http://10.0.0.9:8080/"*) exit "${STUB_CONTROL_RC:-0}";;
  "exec np-probe"*"cmapi-api.cmapi.svc"*) : >"$ARGV_LOG.probed"; echo "${STUB_BLOCK_ERR-wget: download timed out}" >&2; exit "${STUB_BLOCK_RC:-1}";;
  "exec np-probe"*"cmapi-portal.cmapi.svc"*) : >"$ARGV_LOG.probed"; echo "${STUB_FRONT_BLOCK_ERR-wget: download timed out}" >&2; exit "${STUB_FRONT_BLOCK_RC:-1}";;
  "get secret cmapi-test-users"*) printf '%s' "$SECRETVAL" | base64; exit 0;;
  "get secret cmapi-ldap-test-users"*) case "$s" in *"${STUB_NO_PASSWORD:-none}"*) exit 0;; esac; printf '%s' "$SECRETVAL" | base64; exit 0;;
  "get pods -n ldap-testing --no-headers") echo "openldap-server-1 1/1 Running 0 1d"; exit 0;;
  # A measurement reads "a" until the script has deleted in LDAP, and STUB_LDAP_AFTER from then on: the directory moving while the removal runs. The rollback
  # measures three times (its check before any delete, then before and after the removal), so "the first read" no longer tells the two sides apart.
  # The identities script's programs, told apart by what they run. Its real behaviour is deploy/tests/ldap-identities-test.sh, on a real server: here, only what the rollback gives it.
  "exec -i -n ldap-testing"*'printf %s "$LDAP_BASE_DN"'*) printf 'dc=ephico2real,dc=com'; exit 0;;
  "exec -i -n ldap-testing"*"sha256sum"*) cat >/dev/null; o=a; [ ! -s "$ARGV_LOG.ldap-deleted" ] || o=${STUB_LDAP_AFTER:-a}; printf 'others=%s\ngate=g\nidp=2\nidp_cmapi=0\n' "$o"; exit 0;;
  "exec -i -n ldap-testing"*"ldapdelete"*) cat >>"$ARGV_LOG.ldap-deleted"; exit 0;;
  "exec -i -n ldap-testing"*'echo "stranger $dn"'*) sed -n 's/^dn: /same /p'; exit 0;;
  "exec -i -n ldap-testing"*) cat; exit 0;;
  "delete secret cmapi-ldap-test-users"*) exit 0;;
  # The reader's list of Kyverno's reports in every namespace (#387), before the wide checks that must answer no.
  "auth can-i list "*"policyreports.wgpolicyk8s.io --all-namespaces --as=system:serviceaccount:cmapi-system:cmapi-reader") echo "${STUB_READER_REPORTS:-yes}"; exit 0;;
  "auth can-i"*"--all-namespaces"*) echo "${STUB_READER_WIDE:-no}"; exit 0;;
  "auth can-i"*"cmapi-reader"*) echo yes; exit 0;;
  "auth can-i"*) echo "${STUB_WRITER:-no}"; exit 0;;
  # CNPG's peer map on OpenShift: the pod's arbitrary UID signs in as a mapped role, never one named after itself. The read needs
  # pg_monitor, not a superuser, so only the monitoring role answers here (#278).
  "exec cmapi-db-1"*"psql -U cnpg_metrics_exporter "*) echo "${STUB_SSL:-3|0}"; exit 0;;
  "exec cmapi-db-1"*) echo 'psql: error: FATAL:  Peer authentication failed for user "1000720000"' >&2; exit 2;;
  "exec deploy/cmapi-"*) echo "${STUB_SSLMODE:-verify-full}"; exit "${STUB_SSLMODE_RC:-0}";;
  # Discovery as the reader (#387): the served groups, CRC's as measured on 2026-11-17 by default, and the Policies tab's group.
  "get --raw /apis --as=system:serviceaccount:cmapi-system:cmapi-reader")
    [ -z "${STUB_GROUPS_RC:-}" ] || { echo "Unable to connect to the server: EOF" >&2; exit "$STUB_GROUPS_RC"; }
    g='{"name":"apps","versions":[{"groupVersion":"apps/v1","version":"v1"}]},{"name":"wgpolicyk8s.io","versions":[{"groupVersion":"wgpolicyk8s.io/v1alpha2","version":"v1alpha2"}]}'
    printf '{"kind":"APIGroupList","groups":[%s]}\n' "${STUB_GROUPS-$g}"; exit 0;;
  "get --raw /apis/wgpolicyk8s.io/v1alpha2 --as=system:serviceaccount:cmapi-system:cmapi-reader")
    r='{"name":"clusterpolicyreports","kind":"ClusterPolicyReport"},{"name":"policyreports","kind":"PolicyReport"},{"name":"policyreports/status","kind":"PolicyReport"}'
    printf '{"kind":"APIResourceList","groupVersion":"wgpolicyk8s.io/v1alpha2","resources":[%s]}\n' "${STUB_REPORTS-$r}"; exit 0;;
esac
echo "stub oc: unhandled $s" >&2; exit 3
OC
# Nothing may build or push an image on this Mac (#545): each tool is a stub that records its call and does nothing, so a call is seen, never run.
for tool in podman skopeo docker buildah; do
  # shellcheck disable=SC2016  # "$*" and $ARGV_LOG are the stub's own, expanded when it runs
  printf '#!/usr/bin/env bash\nprintf "%s %%s\\n" "$*" >>"$ARGV_LOG"\nexit 0\n' "$tool" >"$W/bin/$tool"
done
# The registry's side of crc-image.sh, as the API returns it. isi: the ImageStreamImport (import: false) answered with GHCR's image, or the importer's
# NotFound or Unauthorized (openshift-apiserver importer.go). istag: the image stream tag, before the import (STUB_ISTAG digest|policy|label) or
# after it (the imported digest, unless STUB_REGISTRY_DIGEST; the policy the import asked for, unless STUB_IMPORT_POLICY); absent otherwise.
cat >"$W/images.py" <<'PY'
import json, os, subprocess, sys
log = os.environ["ARGV_LOG"]; e = os.environ.get
commit = subprocess.run(["git", "-C", os.environ["REPO"], "rev-parse", "--short=10", "HEAD"], capture_output=True, text=True).stdout.strip()
def image(digest, label):
    return {"metadata": {"name": digest}, "dockerImageMetadata": {"kind": "DockerImage", "apiVersion": "image.openshift.io/1.0", "Config": {"Labels": {"org.opencontainers.image.revision": label}}}}
if sys.argv[1] == "isi":
    req = json.load(sys.stdin); json.dump(req, open(log + ".isi", "w"))
    ref = req["spec"]["images"][0]["from"]["name"]; mode = e("STUB_GHCR", "found")
    if mode == "found":
        st = {"metadata": {}, "status": "Success"}; img = image(e("STUB_GHCR_DIGEST", os.environ["IMAGE_DIGEST"]), e("STUB_GHCR_LABEL", commit))
        img["dockerImageReference"] = ref.rsplit(":", 1)[0] + "@" + img["metadata"]["name"]
    elif mode == "missing":
        st = {"metadata": {}, "status": "Failure", "reason": "NotFound", "code": 404, "message": 'dockerimage.image.openshift.io "%s" not found' % ref}; img = None
    else:
        st = {"metadata": {}, "status": "Failure", "reason": "Unauthorized", "code": 401, "message": e("STUB_REGISTRY_ERROR", 'you may not have access to the container image "%s"' % ref)}; img = None
    req["status"] = {"images": [{"tag": "", "status": st, **({"image": img} if img else {})}]}
    json.dump(req, sys.stdout); raise SystemExit
name = sys.argv[2] if len(sys.argv) > 2 else "cmapi:sha-x"
if os.path.exists(log + ".imported"):
    args = open(log + ".imported").read().split("\n"); frm = next(a for a in args if a.startswith("--from=")); pol = next(a for a in args if a.startswith("--reference-policy="))
    digest, policy, label = e("STUB_REGISTRY_DIGEST", frm.rsplit("@", 1)[1]), e("STUB_IMPORT_POLICY", pol.split("=", 1)[1].capitalize()), e("STUB_LABEL", commit)
elif e("STUB_ISTAG"):
    digest, policy, label = e("STUB_ISTAG").split("|")
else:
    raise SystemExit(1)
obj = {"apiVersion": "image.openshift.io/v1", "kind": "ImageStreamTag", "metadata": {"name": name, "namespace": "cmapi"}, "image": image(digest, label)}
if policy: obj["tag"] = {"name": name.split(":")[1], "referencePolicy": {"type": policy}}
json.dump(obj, sys.stdout)
PY
export STUB_IMAGES_PY=$W/images.py
cat >"$W/bin/curl" <<'P'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >>"$ARGV_LOG"
if [ -n "${STUB_PROOF:-}" ]; then
  # The proof's curl: by URL. Anything on stdin is what a token must travel on, and it is swallowed here.
  url=; code=; for a in "$@"; do case "$a" in http*) url=$a;; esac; done; case "$*" in *-w*) wants=1;; *) wants=;; esac
  STDIN_SEEN=; [ ! -p /dev/stdin ] || STDIN_SEEN=$(cat); export STDIN_SEEN
  case "$url" in
    # The front door: its own health, the API's paths through it, and the portal's page for any other path.
    */healthz) code=${STUB_HEALTHZ:-200}; case "$url" in http://*) code=302;; esac;;
    */api/v1/version) [ -n "$wants" ] || { printf '{"commit":"%s"}' "${STUB_COMMIT:-$(git -C "$REPO" rev-parse --short=10 HEAD)}"; exit 0; }
      code=${STUB_VERSION_CODE:-200}; [ ! -e "$ARGV_LOG.probed" ] || code=${STUB_AFTER:-$code};;
    */metrics) code=${STUB_METRICS:-200 text/html};;
    */readyz) code=${STUB_READYZ_PAGE:-200 text/html};;
    */) case "$*" in *"-D -"*) printf '%s' "${STUB_HEADERS-HTTP/1.1 200 OK
Strict-Transport-Security: max-age=63072000; includeSubDomains
X-Content-Type-Options: nosniff
Content-Security-Policy: default-src 'self'; script-src 'self'
}"; exit 0;; esac;;
    */api/v1/me) case "$*" in *--config*) printf '{"username":"%s","roles":["cmapi-onboarding"]}' "${STUB_ME:-cmapi-automation}"; exit 0;; *) code=401;; esac;;
    */portal.html) code=200;;
    */token) python3 "$STUB_TOKEN_PY"; exit 0;;
    # Without -w, the viewer's list: CRC and the kind cluster, each as cmapi's import check left it (#724).
    */api/v1/clusters) [ -n "$wants" ] || { printf '{"items":[%s]}' "${STUB_CLUSTERS-{\"clusterId\":\"CRC\",\"status\":\"connected\",\"findings\":[]\},{\"clusterId\":\"KIND_CMAPI_TEST\",\"status\":\"connected\",\"findings\":[\"usage: the cluster serves no monitoring.coreos.com/v1, so it has no OpenShift monitoring\"]\}}"; exit 0; }
      case "$STDIN_SEEN" in *cmapi.noaccess*) code=${STUB_NOACCESS:-403};; *) code=${STUB_VIEWER:-200};; esac;;
    # STUB_PLAN_SECONDS: how long the plan takes. curl's own -m decides, as the real one does: past it, curl's exit 28 (#275).
    */namespaces*) m=; prev=; for a in "$@"; do [ "$prev" = -m ] && m=$a; prev=$a; done
      if [ -n "${STUB_PLAN_SECONDS:-}" ] && [ -n "$m" ] && [ "$STUB_PLAN_SECONDS" -gt "$m" ]; then
        echo "curl: (28) Operation timed out after ${m}000 milliseconds with 0 bytes received" >&2; exit 28
      fi
      printf '%s\n%s' "${STUB_PLAN_BODY-{\"changes\":{\"clusters/CRC/namespaces/abc-proof-plan-dev/namespace.yaml\":\"+\"\}\}}" "${STUB_PLAN:-200}"; exit 0;;
    # Prometheus's answer: a series per target, each with its job label, as the ServiceMonitors make them (job is the Service's name).
    */api/v1/query*) api='{"metric":{"job":"cmapi-api"},"value":[0,"1"]}'; wrk='{"metric":{"job":"cmapi-worker"},"value":[0,"1"]}'; quotas='{"metric":{},"value":[0,"108"]}'
      case "$*" in
        *'count(kube_resourcequota)'*)
          case "$STDIN_SEEN" in *"reader.$TOKEN"*) ;; *) exit 22;; esac
          for arg in partial_response=false dedup=true timeout=10s; do
            case " $* " in *" --data-urlencode $arg "*) ;; *) exit 22;; esac
          done
          while [ "$1" != --cacert ]; do shift || exit 22; done
          cmp -s "$2" "$STUB_CA" || exit 60
          printf '{"status":"success","warnings":%s,"data":{"resultType":"vector","result":[%s]}}' "${STUB_WARNINGS-[]}" "${STUB_QUOTAS-$quotas}";;
        *cluster_token_expiry_seconds*' > bool 0'*) printf '{"data":{"result":[%s]}}' "${STUB_EXPIRY-$api,$wrk}";; *cluster_status*) printf '{"data":{"result":[%s]}}' "${STUB_CONNECTED-$api,$wrk}";; *) printf '{"data":{"result":[%s]}}' "${STUB_UP:-$api,$wrk}";; esac; exit 0;;
  esac
  [ -z "$wants" ] || printf '%s' "$code"; exit 0
fi
cat >/dev/null 2>&1 </dev/null
exit_code=${STUB_CURL_RC:-0}; [ "$exit_code" = 0 ] || exit "$exit_code"
out=; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done; [ -z "$out" ] || : >"$out"; printf '%s' "${STUB_CURL_CODE:-200}"
P
printf '#!/bin/sh\nexit 0\n' >"$W/bin/tmutil"
# The token for whoever signed in: claims from the table, and $TOKEN in the signature, so a token on an argument is found. STUB_CLAIMS changes one claim of one user: uid:claim:json.
cat >"$W/token.py" <<'TOK'
import base64, json, os, urllib.parse
form = urllib.parse.parse_qs(os.environ.get("STDIN_SEEN", "")); user = form.get("username", ["service-account-cmapi-automation"])[0]
# The token endpoint takes client credentials. It refuses the password grant, unless STUB_PASSWORD_GRANT says that the realm still has it.
if form.get("grant_type") == ["password"] and not os.environ.get("STUB_PASSWORD_GRANT"):
    print('{"error":"unauthorized_client","error_description":"Client not allowed for direct access grants"}'); raise SystemExit
if form.get("grant_type") == ["password"]:
    print('{"error":"invalid_grant","error_description":"Invalid user credentials"}'); raise SystemExit
if user == os.environ.get("STUB_NO_SIGN_IN"):
    print('{"error":"invalid_grant"}'); raise SystemExit
claims = {"preferred_username": user}
for line in open(os.environ["REPO"] + "/examples/cmapi-sso/ldap/test-identities.tsv"):
    if line.startswith("#") or not line.strip(): continue
    uid, number, groups, roles = line.rstrip("\n").split("\t")
    if uid == user:
        claims = {"preferred_username": uid, "employee_id": number}
        if groups != "-": claims["groups"] = ["/cmapi/" + g for g in groups.split(",")]
        if roles != "-": claims["resource_access"] = {"cmapi-nonprod": {"roles": roles.split(",")}}
if os.environ.get("STUB_CLAIMS"):
    uid, name, value = os.environ["STUB_CLAIMS"].split(":", 2)
    if uid == user: claims[name] = json.loads(value)
enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
print(json.dumps({"access_token": ".".join([enc({"alg": "none"}), enc(claims), os.environ["TOKEN"] + "-" + user])}))
TOK
export STUB_TOKEN_PY=$W/token.py
# The stand-in for deploy/oidc-login.py: the token of --username, from the same table. The password comes on stdin and is swallowed here.
cat >"$W/bin/oidc-login-stub" <<'P'
#!/usr/bin/env bash
printf 'oidc-login %s\n' "$*" >>"$ARGV_LOG"
cat >/dev/null
user=; while [ $# -gt 0 ]; do [ "$1" = --username ] && user=$2; shift; done
STDIN_SEEN="grant_type=authorization_code&username=$user" python3 "$STUB_TOKEN_PY" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(1) if "access_token" not in d else print(d["access_token"])'
P
export CMAPI_OIDC_LOGIN=$W/bin/oidc-login-stub
chmod +x "$W/bin/"*; export PATH="$W/bin:$PATH"
cd "$W/repo" || exit 1; git init -q .; git -c user.email=t@t -c user.name=t commit -q --allow-empty -m t; export REPO=$W/repo; mkdir -p cmapi; printf 'version = "0.2.0"\n' >cmapi/pyproject.toml
D=$W/repo/deploy; TRUST=$D/manifests/environments/crc/30-trust.yaml
no_secret() { if grep -qF -f <(printf '%s\n' "$TOKEN" "$SECRETVAL"; printf '%s' "$TOKEN" | base64) "$ARGV_LOG" "$1"; then bad "$2: a credential reached an argument or the output"; else ok "$2: no credential on an argument or in the output"; fi; }
run() { : >"$ARGV_LOG"; "$@" >"$W/out" 2>&1; echo $?; }

# crc-trust.sh
# The file in Git is what --write produces: its own bundle read back through a stub oc gives the same bytes, so --check and a later rotation mean the same file.
sed -n 's/^    //p' "$TRUST" >"$W/committed.pem"; cp "$TRUST" "$W/committed.yaml"
want "the committed bundle holds one CA, and it is not kind's" 1 "$(grep -c 'BEGIN CERTIFICATE' "$W/committed.pem")"
openssl x509 -in "$W/committed.pem" -noout -subject 2>/dev/null | grep -q 'CN *= *LDAP Enterprise Root CA' && ok "the committed CA is LDAP Enterprise Root CA" || bad "the committed CA: $(openssl x509 -in "$W/committed.pem" -noout -subject 2>&1)"
want "trust --write from the committed certificate" 0 "$(STUB_CA=$W/committed.pem run "$D/crc-trust.sh" --write)"
cmp -s "$TRUST" "$W/committed.yaml" && ok "30-trust.yaml is byte for byte what --write produces" || bad "30-trust.yaml differs from what --write produces"
# Under pipefail, "openssl | grep -q" can kill openssl with SIGPIPE when grep leaves early, and a real CA would be refused. This openssl goes on writing after the match.
mkdir "$W/noisy"; cat >"$W/noisy/openssl" <<NOISY
#!/usr/bin/env bash
$(command -v openssl) "\$@"; rc=\$?
case "\$*" in *-text*) head -c 2000000 /dev/zero | tr '\\0' x; exit \$?;; esac
exit \$rc
NOISY
chmod +x "$W/noisy/openssl"
want "a CA whose openssl goes on writing is still a CA" 0 "$(PATH="$W/noisy:$PATH" run "$D/crc-trust.sh" --write)"
want "trust --write" 0 "$(run "$D/crc-trust.sh" --write)"; grep -q 'BEGIN CERTIFICATE' "$TRUST" || bad "no certificate in the file"
if grep -qE 'tls\.key|-o (yaml|json)( |$)' "$ARGV_LOG"; then bad "trust --write asked for more than ca.crt"; else ok "trust --write asks for ca.crt alone"; fi
grep -q 'name: cmapi-trust' "$TRUST" && [ "$(grep -c 'BEGIN CERTIFICATE' "$TRUST")" = 1 ] && ok "the file declares cmapi-trust" || bad "the trust file"
printf -- '-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n' >"$W/key.pem"
cp "$TRUST" "$W/keep"; want "trust --extra-ca refuses a private key" 1 "$(run "$D/crc-trust.sh" --write --extra-ca "$W/key.pem")"; cmp -s "$TRUST" "$W/keep" && ok "and the file stays" || bad "a refused --write changed the file"
want "trust --check passes" 0 "$(run "$D/crc-trust.sh" --check)"
if grep -q 'keycloak-tls' "$ARGV_LOG"; then bad "--check read the Secret"; else ok "--check reads no Secret"; fi
grep -q -- '--cacert' "$ARGV_LOG" && ok "--check verifies with the file" || bad "--check did not use --cacert"
want "trust --check: a failed handshake stops" 1 "$(STUB_CURL_RC=60 run "$D/crc-trust.sh" --check)"
want "trust --check: not 200 stops" 1 "$(STUB_CURL_CODE=503 run "$D/crc-trust.sh" --check)"
mkdir "$W/mac"; want "trust --mac-ca" 0 "$(run "$D/crc-trust.sh" --mac-ca "$W/mac/crc-ca.pem")"; cp "$W/mac/crc-ca.pem" "$W/mac.pem"; [ "$(grep -c 'BEGIN CERTIFICATE' "$W/mac.pem")" = 2 ] && ok "both CAs in the Mac's bundle" || bad "the Mac's bundle"
fp() { openssl x509 -in "$1" -noout -fingerprint -sha1; }
[ "$(fp "$W/mac/ingress-ca.pem")" = "$(fp "$W/ingress-ca.pem")" ] && ok "ingress-ca.pem is the ingress CA, though the bundle starts with the site's certificate" || bad "ingress-ca.pem: $(fp "$W/mac/ingress-ca.pem")"
[ "$(grep -c 'BEGIN CERTIFICATE' "$W/mac/keycloak-ca.pem")" = 1 ] && [ "$(grep -c 'BEGIN CERTIFICATE' "$W/mac/ingress-ca.pem")" = 1 ] && ok "one certificate in each file" || bad "a file holds more than one certificate"
if awk '/BEGIN/{c=""} {c=c $0 "\n"} /END/{printf "%s", c | "openssl x509 -noout -subject"; close("openssl x509 -noout -subject")}' "$W/mac.pem" | grep -q 'apps-crc.testing'; then bad "the site's certificate is in the Mac's bundle"; else ok "the site's certificate is nowhere in the Mac's bundle"; fi
openssl verify -CAfile "$W/mac.pem" "$W/leaf.pem" >/dev/null 2>&1 && ok "and the CA alone still verifies the site" || bad "the Mac's bundle no longer verifies the site"
mkdir "$W/mac3"; want "a CA whose openssl goes on writing is still a CA for --mac-ca" 0 "$(PATH="$W/noisy:$PATH" run "$D/crc-trust.sh" --mac-ca "$W/mac3/x.pem")"
mkdir "$W/mac2"; want "trust --mac-ca: a bundle with no CA stops" 1 "$(STUB_INGRESS=$W/leaf.pem run "$D/crc-trust.sh" --mac-ca "$W/mac2/x.pem")"; [ ! -e "$W/mac2/ingress-ca.pem" ] && ok "and writes no ingress-ca.pem" || bad "a leaf was written as the ingress CA"
cat "$W/ingress-ca.pem" "$W/ca.pem" >"$W/two-cas.pem"; want "trust --mac-ca: a bundle with two CAs stops: which to trust is not a guess" 1 "$(STUB_INGRESS=$W/two-cas.pem run "$D/crc-trust.sh" --mac-ca "$W/mac2/x.pem")"
# A trust file that also holds an external database's CA (--write --extra-ca, docs/12): --mac-ca still works, the keychain's file is Keycloak's, and the Mac's bundle keeps every CA the pods trust.
openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/db-ca.pem" -subj "/CN=external-db-ca" -days 2 2>/dev/null
cp "$TRUST" "$W/keep-trust"; want "trust --write --extra-ca" 0 "$(run "$D/crc-trust.sh" --write --extra-ca "$W/db-ca.pem")"
mkdir "$W/mac4"; want "trust --mac-ca with an extra CA in the trust file" 0 "$(run "$D/crc-trust.sh" --mac-ca "$W/mac4/crc-ca.pem")"
[ -e "$W/mac4/keycloak-ca.pem" ] && [ "$(fp "$W/mac4/keycloak-ca.pem")" = "$(fp "$W/ca.pem")" ] && ok "keycloak-ca.pem is Keycloak's CA, not the extra one" || bad "keycloak-ca.pem with an extra CA in the trust file"
[ -e "$W/mac4/crc-ca.pem" ] && [ "$(grep -c 'BEGIN CERTIFICATE' "$W/mac4/crc-ca.pem")" = 3 ] && ok "the Mac's bundle holds Keycloak's, the extra one and the ingress CA" || bad "the Mac's bundle with an extra CA in the trust file"
cp "$W/keep-trust" "$TRUST"
if grep -rqE -- '(^|[^-])(-k |--insecure|--tls-verify=false)' "$D"/crc-*.sh; then bad "TLS verification off in a script"; else ok "no script turns TLS verification off"; fi

# crc-image.sh (#545): CI's image, imported by digest; nothing built or pushed from here.
irun() { rm -f "$ARGV_LOG.imported" "$ARGV_LOG.isi"; run "$@"; }
IMAGE_DIGEST=sha256:$(printf '%064d' 1); export IMAGE_DIGEST
HEAD10=$(git rev-parse --short=10 HEAD)
built() { if grep -qE '^(podman|skopeo|docker|buildah) ' "$ARGV_LOG"; then bad "$1: an image tool ran: $(grep -E '^(podman|skopeo|docker|buildah) ' "$ARGV_LOG" | head -1)"; else ok "$1: no podman, skopeo, docker or buildah"; fi; }
imported() { if [ -e "$ARGV_LOG.imported" ]; then bad "$1: it imported"; else ok "$1: and imports nothing"; fi; }
want "image: imports CI's image and prints" 0 "$(irun "$D/crc-image.sh")"
tail -1 "$W/out" | grep -qxF "image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@$IMAGE_DIGEST" && ok "the last line is GHCR's digest, in the reference render.sh takes" || bad "the image line: $(tail -1 "$W/out")"
built "image"; no_secret "$W/out" "image"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); i=d["spec"]["images"][0]["from"]; sys.exit(0 if d["kind"]=="ImageStreamImport" and d["spec"]["import"] is False and d["metadata"]["namespace"]=="cmapi" and i=={"kind":"DockerImage","name":"ghcr.io/ephico2real2/cmapi:sha-"+sys.argv[2]} else 1)' "$ARGV_LOG.isi" "$HEAD10" \
  && ok "GHCR's sha-<commit> is resolved with import: false" || bad "the lookup: $(cat "$ARGV_LOG.isi")"
grep -qxF -e "--from=ghcr.io/ephico2real2/cmapi@$IMAGE_DIGEST" "$ARGV_LOG.imported" && grep -qxF -e '--reference-policy=local' "$ARGV_LOG.imported" && grep -qxF "cmapi:sha-$HEAD10" "$ARGV_LOG.imported" \
  && ok "the import is of that digest, never the tag, with referencePolicy local" || bad "the import: $(tr '\n' ' ' <"$ARGV_LOG.imported")"
if grep -qE '^oc (whoami -t|get route default-route|get cm default-ingress-cert)' "$ARGV_LOG"; then bad "image: it read a token or the registry's route"; else ok "image: no session token and no registry route"; fi
grep -q '^oc get secret cmapi-ghcr-pull -n cmapi --ignore-not-found -o jsonpath={.type}$' "$ARGV_LOG" && ! grep -E '^oc get secret' "$ARGV_LOG" | grep -qv 'jsonpath={.type}$' \
  && ok "image: the pull secret's type is read, never a value" || bad "image: the secret reads: $(grep '^oc get secret' "$ARGV_LOG")"
want "image cmapi-portal: imports and prints" 0 "$(irun "$D/crc-image.sh" cmapi-portal)"
tail -1 "$W/out" | grep -qxF "image-registry.openshift-image-registry.svc:5000/cmapi/cmapi-portal@$IMAGE_DIGEST" && ok "the last line is the front door's reference" || bad "the portal image line: $(tail -1 "$W/out")"
grep -qxF -e "--from=ghcr.io/ephico2real2/cmapi-portal@$IMAGE_DIGEST" "$ARGV_LOG.imported" && grep -qxF "cmapi-portal:sha-$HEAD10" "$ARGV_LOG.imported" && ok "into its own image stream, from its own package" || bad "the portal import: $(tr '\n' ' ' <"$ARGV_LOG.imported")"
built "image cmapi-portal"
want "image: an unknown name stops" 2 "$(irun "$D/crc-image.sh" cmapi-other)"; if grep -q . "$ARGV_LOG"; then bad "an unknown name called $(head -1 "$ARGV_LOG")"; else ok "and calls nothing"; fi
want "image: no image for this commit in GHCR stops" 1 "$(STUB_GHCR=missing irun "$D/crc-image.sh")"; imported "no image"; built "no image"
grep -q "GHCR has no ghcr.io/ephico2real2/cmapi:sha-$HEAD10" "$W/out" && ok "and says that CI has not pushed it" || bad "the no-image message: $(cat "$W/out")"
want "image: GHCR refusing the pull secret stops" 1 "$(STUB_GHCR=denied irun "$D/crc-image.sh")"; imported "refused"
grep -q "Secret cmapi-ghcr-pull cannot read the package" "$W/out" && ok "and names the secret" || bad "the refused message: $(cat "$W/out")"
want "image: no pull secret stops" 1 "$(STUB_NO_PULL_SECRET=1 irun "$D/crc-image.sh")"; imported "no pull secret"
grep -q 'Secret cmapi-ghcr-pull is not in namespace cmapi' "$W/out" && ok "and says the owner creates it" || bad "the no-secret message: $(cat "$W/out")"
if grep -q '^oc create' "$ARGV_LOG"; then bad "no pull secret: it asked GHCR anyway"; else ok "no pull secret: and asks GHCR nothing"; fi
want "image: a pull secret of another type stops" 1 "$(STUB_PULL_SECRET_TYPE=Opaque irun "$D/crc-image.sh")"; imported "an Opaque secret"
for invalid in sha256: sha256:abcd "${IMAGE_DIGEST}0" "${IMAGE_DIGEST%?}z"; do
  want "image: malformed GHCR digest $invalid stops" 1 "$(STUB_GHCR_DIGEST="$invalid" irun "$D/crc-image.sh")"
  imported "malformed digest"
done
want "image: an image stream digest that is not GHCR's stops" 1 "$(STUB_REGISTRY_DIGEST=sha256:bbbb irun "$D/crc-image.sh")"
grep -qF "holds sha256:bbbb, GHCR's is $IMAGE_DIGEST" "$W/out" && ok "and names both digests" || bad "the digest message: $(cat "$W/out")"
want "image: an image stream revision label that is not this commit stops" 1 "$(STUB_LABEL=other irun "$D/crc-image.sh")"
want "image: GHCR's image labelled with another commit stops before the import" 1 "$(STUB_GHCR_LABEL=other irun "$D/crc-image.sh")"; imported "GHCR's label"
wrong_label="$HEAD10"$'\nextra'
want "image: the whole GHCR label must match" 1 "$(STUB_GHCR_LABEL="$wrong_label" irun "$D/crc-image.sh")"; imported "multiline GHCR label"
want "image: the whole stream label must match" 1 "$(STUB_LABEL="$wrong_label" irun "$D/crc-image.sh")"
want "image: a failed lookup stops" 1 "$(STUB_CREATE_ERROR="error: You must be logged in to the server (Unauthorized)" irun "$D/crc-image.sh")"; imported "failed lookup"
grep -qF "You must be logged in to the server" "$W/out" && ok "and shows oc's own reason" || bad "the failed-lookup message: $(cat "$W/out")"
want "image: a registry error is safe to log" 1 "$(STUB_GHCR=denied STUB_REGISTRY_ERROR="$SECRETVAL" irun "$D/crc-image.sh")"
no_secret "$W/out" "registry error"
want "image: an imported tag whose reference policy is not Local stops" 1 "$(STUB_IMPORT_POLICY=Source irun "$D/crc-image.sh")"
want "image: a failed import stops" 7 "$(STUB_IMPORT_RC=7 STUB_REGISTRY_ERROR="$SECRETVAL" irun "$D/crc-image.sh")"
no_secret "$W/out" "failed import"
want "image: an existing tag holding GHCR's digest is reused" 0 "$(STUB_ISTAG="$IMAGE_DIGEST|Local|$HEAD10" irun "$D/crc-image.sh")"; imported "reused"
tail -1 "$W/out" | grep -qxF "image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@$IMAGE_DIGEST" && ok "and printed" || bad "the reused line: $(tail -1 "$W/out")"
want "image: an existing tag of this commit built elsewhere stops" 1 "$(STUB_ISTAG="sha256:cccc||$HEAD10" irun "$D/crc-image.sh")"; imported "built elsewhere"
grep -q 'oc delete istag cmapi:sha-' "$W/out" && ok "and says how to clear it" || bad "the stale-tag message: $(cat "$W/out")"
printf 'broken index' >"$W/invalid-index"
want "image: git status failing stops" 128 "$(GIT_INDEX_FILE="$W/invalid-index" irun "$D/crc-image.sh")"
if [ -s "$ARGV_LOG" ]; then bad "failed status: contacted the cluster"; else ok "failed status: no cluster call"; fi
printf x >>cmapi/pyproject.toml; git add -A >/dev/null; want "image: a dirty tree stops" 1 "$(irun "$D/crc-image.sh")"; git -c user.email=t@t -c user.name=t commit -q -m t2

# crc-reader-import.sh
want "reader import" 0 "$(run "$D/crc-reader-import.sh")"; no_secret "$W/out" "reader import"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); m=d["metadata"]; sys.exit(0 if m["namespace"]=="cmapi-imports" and m["labels"]["cmapi.net/cluster-id"]=="CRC" and m["labels"]["cmapi.net/secret-type"]=="cluster" and set(d["data"])=={"apiUrl","token","caData","insecure"} else 1)' "$ARGV_LOG.applied" && ok "the import Secret is what the registry reads" || bad "the import Secret"
python3 "$HERE/token-renewal-test.py" "$STUB_CA" && ok "worker and script renewal deadlines agree" || bad "worker and script renewal deadlines differ"
want "CRC short-duration fallback" 0 "$(CMAPI_TOKEN_DURATION=1h run "$D/crc-reader-import.sh")"
grep -q -- '--duration=1h' "$ARGV_LOG" && ok "CRC requested one hour" || bad "wrong CRC duration"
want "reader import: a refused TokenRequest stops" 1 "$(STUB_NO_TOKEN=1 run "$D/crc-reader-import.sh")"

# crc-backup.sh
B=$W/backup; export CMAPI_BACKUP_DIR=$B
want "backup --inspect" 0 "$(run "$D/crc-backup.sh" --inspect)"; if grep -q 'literal-value' "$W/out"; then bad "--inspect printed a value"; else ok "--inspect prints names, never a value"; fi
grep -q 'POSTGRESQL_USER' "$W/out" && ok "--inspect names the variables" || bad "--inspect names nothing"
want "backup" 0 "$(run "$D/crc-backup.sh")"
f=$(find "$B" -type f -name 'keycloak-*.dump'); [ -n "$f" ] && ok "a dump in the directory" || bad "no dump"
# The GNU form first: GNU's -f writes the file system's details on stdout before it fails, while BSD's stat refuses -c with nothing on stdout (#90).
m() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }; [ "$(m "$B")" = 700 ] && [ "$(m "$f")" = 600 ] && ok "directory 0700, file 0600" || bad "modes $(m "$B") $(m "$f")"
if grep -qF -e "$DUMP_MARK" -e "$f" "$W/out" "$ARGV_LOG"; then bad "the dump's content or path reached the output"; else ok "no content and no path in the output"; fi
if grep -qE 'pg_dump.*(> *[/a-z]|-f )' "$ARGV_LOG"; then bad "the dump is written inside the pod"; else ok "the dump goes to stdout"; fi
if grep -qE 'exec (-[a-z]+ )*-t' "$ARGV_LOG"; then bad "a TTY would corrupt the stream"; else ok "no TTY on the stream"; fi
rm -rf "$B"
stop() { local label=$1; shift; local got; got=$(env "$@" "$D/crc-backup.sh" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "backup stops: $label" || bad "backup did not stop: $label"; if find "$B" -type f 2>/dev/null | grep -q .; then bad "$label: left a file"; fi; rm -rf "$B"; }
stop "a dump that fails partway" STUB_DUMP_FAIL=1
stop "an empty dump" STUB_DUMP_EMPTY=1
stop "a list that fails" STUB_LIST_FAIL=1
stop "an archive that does not read to its end" STUB_READ_FAIL=1
stop "realm counts that differ" STUB_DUMP_REALMS=5
stop "too little room under the limit" STUB_DB_USED=450Mi
stop "too few free connections" STUB_DB_SLOTS=2
ln -s "$W" "$B"; got=$("$D/crc-backup.sh" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "backup stops: a symbolic link for the directory" || bad "the link was followed"; rm -f "$B"
"$D/crc-backup.sh" >/dev/null 2>&1; want "backup --delete" 0 "$(run "$D/crc-backup.sh" --delete)"; [ ! -e "$B" ] && ok "the backup is gone" || bad "the backup is still there"

# crc-proof.sh
export STUB_PROOF=1 CMAPI_PROOF_SCRAPE_TRIES=1 CMAPI_CRC_CA=$W/mac.pem; P=$W/rendered; mkdir -p "$P"; printf 'image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:aaaa\n' >"$P/IMAGE"; printf 'image-registry.openshift-image-registry.svc:5000/cmapi/cmapi-portal@sha256:pppp\n' >"$P/PORTAL_IMAGE"
: >"$ARGV_LOG.sar"; want "proof passes when all is right" 0 "$(run "$D/crc-proof.sh" "$P")"; [ "$(tail -1 "$W/out")" = "proof: all passed" ] || bad "the proof's last line: $(tail -1 "$W/out")"
# The reader's Thanos grants (#310) and the import check's review of them (#724): each review for the reader and its own
# groups alone, its own token's query, and cmapi's own check of CRC with no usage finding.
grep -qxF "proof: cmapi's import check finds the reader's own usage grants on CRC: no usage finding" "$W/out" \
  && ok "the proof records cmapi's import check of the usage grants" || bad "the import check's record: $(grep -i 'usage' "$W/out" | head -1)"
grep -qxF 'proof: the reader has the two cmapi Thanos grants in openshift-monitoring: count(kube_resourcequota) = 108' "$W/out" \
  && ok "the proof records the reader's Thanos grants and its query" || bad "the reader's Thanos record: $(grep -i thanos "$W/out" | head -1)"
[ "$(grep -c '"user":"system:serviceaccount:cmapi-system:cmapi-reader","groups":\["system:serviceaccounts","system:serviceaccounts:cmapi-system"\]' "$ARGV_LOG.sar")" = 4 ] \
  && ! grep -q 'system:authenticated' "$ARGV_LOG.sar" && ok "each review names the reader's groups without system:authenticated" || bad "the reviews: $(cat "$ARGV_LOG.sar")"
# The Policies tab's premise, recorded as the reader's discovery serves it (#387): the request the API's own probe makes.
grep -qxF 'proof: discovery, as cmapi-reader, serves wgpolicyk8s.io/v1alpha2 with clusterpolicyreports policyreports, the reports of the Policies tab; openreports.io: not served' "$W/out" \
  && grep -qxF 'oc get --raw /apis/wgpolicyk8s.io/v1alpha2 --as=system:serviceaccount:cmapi-system:cmapi-reader' "$ARGV_LOG" \
  && ok "the proof records the report groups that discovery serves to the reader" || bad "the report groups' record: $(grep -i 'discovery' "$W/out" | head -1)"
for kind in clusterpolicyreports policyreports; do
  grep -qxF "oc auth can-i list $kind.wgpolicyk8s.io --all-namespaces --as=system:serviceaccount:cmapi-system:cmapi-reader" "$ARGV_LOG" \
    && ok "the proof asks whether the reader may list $kind in every namespace" || bad "no can-i list $kind as the reader in every namespace"
done
want "proof passes with openreports.io served beside wgpolicyk8s.io" 0 "$(STUB_GROUPS='{"name":"wgpolicyk8s.io","versions":[{"groupVersion":"wgpolicyk8s.io/v1alpha2","version":"v1alpha2"}]},{"name":"openreports.io","versions":[{"groupVersion":"openreports.io/v1alpha1","version":"v1alpha1"}]}' run "$D/crc-proof.sh" "$P")"
grep -q '; openreports.io: v1alpha1$' "$W/out" && ok "and records openreports.io's version" || bad "openreports.io's record: $(grep -i 'discovery' "$W/out" | head -1)"
# The plan, the slowest call, may take as long as the front door gives it: CRC's first answered 200 after 27.7 s (#275).
want "proof passes when the plan takes 28 s" 0 "$(: >"$ARGV_LOG"; STUB_PLAN_SECONDS=28 "$D/crc-proof.sh" "$P" >"$W/out" 2>&1; echo $?)"
# Each call's own bound, read from what curl was given: the plan the Route's timeout, every other call 15 s. A grep for one
# call that some other line also matches (crc-proof.sh's plain-HTTP curl names /healthz with -m 15 too) could not fail.
route_s=$(sed -n 's/^ *haproxy.router.openshift.io\/timeout: \([0-9][0-9]*\)s$/\1/p' "$D/manifests/environments/crc/40-routes.yaml")
plan_m=$(grep -- '/namespaces?dryRun=true' "$ARGV_LOG" | sed -n 's/^curl -sS -m \([^ ]*\) .*/\1/p')
[ -n "$route_s" ] && [ "$plan_m" = "$route_s" ] && ok "the plan waits as long as the Route: -m $plan_m" || bad "the plan's bound is -m ${plan_m:-none}, the Route's timeout ${route_s:-unread} s"
others=$(grep '^curl ' "$ARGV_LOG" | grep -v -- '/namespaces?dryRun=true')
[ "$(printf '%s\n' "$others" | grep -c .)" -ge 10 ] && ! printf '%s\n' "$others" | grep -qv '^curl -sS -m 15 ' && ok "every other call keeps its 15 s bound" || bad "a call other than the plan lost its 15 s bound: $(printf '%s\n' "$others" | grep -v '^curl -sS -m 15 ' | head -1 | cut -c1-120)"
no_secret "$W/out" "proof"
pstop() { local label=$1; shift; local got; rm -f "$ARGV_LOG.probed"; got=$(: >"$ARGV_LOG"; env "$@" "$D/crc-proof.sh" "$P" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "proof fails: $label" || bad "proof did not fail: $label"; }
pstop "a pod under another SCC" STUB_SCC=anyuid
pstop "a restart" STUB_RESTARTS=1
pstop "another image running" STUB_IMAGE_ID=sha256:bbbb
pstop "a pod started before the policy" STUB_START=2026-11-06T08:00:00Z
pstop "the front door on another image" STUB_PORTAL_IMAGE_ID=sha256:bbbb
pstop "no front door pod" STUB_NO_PORTAL=1
pstop "the front door started before its policy" STUB_PORTAL_START=2026-11-06T08:00:00Z
pstop "the front door's /healthz not 200" STUB_HEALTHZ=503
pstop "NetworkPolicy cmapi-metrics not there" STUB_NP_GONE=cmapi-metrics
grep -qxF "FAIL: NetworkPolicy cmapi-metrics cannot be read" "$W/out" && ok "and it says which policy" || bad "the missing policy is not named: $(tail -1 "$W/out")"
pstop "NetworkPolicy cmapi-front-door not there" STUB_NP_GONE=cmapi-front-door
pstop "another commit" STUB_COMMIT=other
pstop "/metrics reaching the API through the Route" 'STUB_METRICS=200 text/plain; version=0.0.4'
pstop "/readyz reaching the API through the Route" 'STUB_READYZ_PAGE=200 application/json'
pstop "the portal's page without HSTS" 'STUB_HEADERS=HTTP/1.1 200 OK
X-Content-Type-Options: nosniff
Content-Security-Policy: default-src '"'self'"'
'
pstop "the portal's page without a Content-Security-Policy" 'STUB_HEADERS=HTTP/1.1 200 OK
Strict-Transport-Security: max-age=63072000; includeSubDomains
X-Content-Type-Options: nosniff
'
pstop "the probe reaching the api: the policy not enforced" STUB_BLOCK_RC=0
pstop "the probe reaching the front door: its policy not enforced" STUB_FRONT_BLOCK_RC=0
pstop "the front door refusing the probe: broken, not blocked" "STUB_FRONT_BLOCK_ERR=wget: can't connect to remote host (10.0.0.2): Connection refused"
pstop "the control failing: the block would prove nothing" STUB_CONTROL_RC=1
pstop "the control pod with no address" STUB_TARGET_IP=
pstop "the api's name not resolving: broken, not blocked" "STUB_BLOCK_ERR=wget: bad address 'cmapi-api.cmapi.svc:8080'"
pstop "a refused connection: broken, not blocked" "STUB_BLOCK_ERR=wget: can't connect to remote host (10.0.0.1): Connection refused"
pstop "the api answering 503: not blocked" "STUB_BLOCK_ERR=wget: server returned error: HTTP/1.0 503 down"
pstop "oc exec failing: nothing was probed" "STUB_BLOCK_ERR=Error from server: error dialing backend: EOF"
pstop "no reason at all" STUB_BLOCK_ERR=
pstop "a timeout from an instance that then does not answer the router" STUB_AFTER=503
pstop "an api that may write" STUB_WRITER=yes
pstop "the worker creating an unmanaged namespace: not contained" STUB_UNMANAGED_RC=0
pstop "the worker refused, but not by the policy" "STUB_UNMANAGED_ERR=Error from server (Forbidden): namespaces is forbidden: User cannot create"
pstop "the worker refused a managed namespace: nothing could be delivered" STUB_MANAGED_RC=1
pstop "the worker labelling namespace default: not contained" STUB_DEFAULT_RC=0
pstop "namespace default refused, but not by the policy" "STUB_DEFAULT_ERR=error: unable to connect"
pstop "a reader reading Secrets" STUB_READER_WIDE=yes
# Each stopped by the discovery check itself, not by something after it that the stub does not answer.
says() { grep -qxF "$1" "$W/out" && ok "and it says why" || bad "the proof stopped without saying '$1': $(tail -1 "$W/out")"; }
pstop "wgpolicyk8s.io not served: the Policies tab reads Kyverno not installed" 'STUB_GROUPS={"name":"apps","versions":[{"groupVersion":"apps/v1","version":"v1"}]}'
says 'FAIL: discovery as cmapi-reader does not serve wgpolicyk8s.io/v1alpha2 (wgpolicyk8s.io: not served; openreports.io: not served): the Policies tab reads "Kyverno not installed" (#382)'
pstop "only openreports.io served (#382)" 'STUB_GROUPS={"name":"openreports.io","versions":[{"groupVersion":"openreports.io/v1alpha1","version":"v1alpha1"}]}'
says 'FAIL: discovery as cmapi-reader does not serve wgpolicyk8s.io/v1alpha2 (wgpolicyk8s.io: not served; openreports.io: v1alpha1): the Policies tab reads "Kyverno not installed" (#382)'
pstop "wgpolicyk8s.io served at another version alone" 'STUB_GROUPS={"name":"wgpolicyk8s.io","versions":[{"groupVersion":"wgpolicyk8s.io/v1beta1","version":"v1beta1"}]}'
says 'FAIL: discovery as cmapi-reader does not serve wgpolicyk8s.io/v1alpha2 (wgpolicyk8s.io: v1beta1; openreports.io: not served): the Policies tab reads "Kyverno not installed" (#382)'
pstop "wgpolicyk8s.io/v1alpha2 without clusterpolicyreports" 'STUB_REPORTS={"name":"policyreports","kind":"PolicyReport"}'
says "FAIL: wgpolicyk8s.io/v1alpha2 serves 'policyreports', without clusterpolicyreports"
pstop "discovery failing: nothing was read" STUB_GROUPS_RC=1
says 'FAIL: discovery as cmapi-reader gave no list of the served groups'
pstop "a reader that may not list the reports in every namespace" STUB_READER_REPORTS=no
says 'FAIL: cmapi-reader may not list clusterpolicyreports.wgpolicyk8s.io in every namespace: the Policies tab reads "no access to the reports"'
pstop "a plan refused" STUB_PLAN=422
pstop "a plan that names no file" STUB_PLAN_BODY='{"changes":{}}'
pstop "a dry run that left the namespace" STUB_PLAN_NS=namespace/abc-proof-plan-dev
pstop "a plan that outlasts the Route" STUB_PLAN_SECONDS=200
# Stopped by the proof, which names the step, not by set -e on curl's exit with only curl's own line.
grep -q '^FAIL: the dry-run namespace plan got no answer: curl exit 28' "$W/out" && ok "a plan with no answer says which step stopped" || bad "a plan with no answer stopped without naming the step: $(tail -1 "$W/out")"
for v in abc 0 -5 1.5; do pstop "a plan bound of '$v'" CMAPI_PROOF_PLAN_SECONDS=$v
  ! grep -q '^oc ' "$ARGV_LOG" && grep -q '^FAIL: CMAPI_PROOF_PLAN_SECONDS' "$W/out" && ok "a plan bound of '$v' stops before the cluster is touched" || bad "a plan bound of '$v' was not refused first: $(tail -1 "$W/out")"; done
pstop "a connection without TLS" "STUB_SSL=3|1"
pstop "no connection at all" "STUB_SSL=0|0"
pstop "a connection that does not verify the server" STUB_SSLMODE=prefer
pstop "a container that cannot say how it connects" STUB_SSLMODE_RC=1
# The reader's Thanos grants (#310), each by cmapi's own RoleBinding, proven without system:authenticated, and its own token's query.
pstop "the reader without its Route grant" 'STUB_SAR_ROUTE=false '
pstop "Thanos allowed to the reader only through a binding to everyone" 'STUB_SAR_API=true RBAC: allowed by ClusterRoleBinding "openshift-coo-cluster-monitoring-view" of ClusterRole "cluster-monitoring-view" to Group "system:authenticated"'
# The import check's own grant and its outcome (#724), each stopped by its own line, not by an earlier step.
pstop "the reader without the import check's review" 'STUB_SAR_CHECK=false '
grep -q '^FAIL: the reader may not create localsubjectaccessreviews/ in openshift-monitoring by RoleBinding cmapi-reader-grant-check' "$W/out" && ok "the missing review grant is named" || bad "the missing review grant was not named: $(tail -1 "$W/out")"
pstop "a usage finding of cmapi's import check on CRC" 'STUB_CLUSTERS={"clusterId":"CRC","status":"connected","findings":["usage: missing grant in openshift-monitoring: x"]}'
grep -q "^FAIL: cmapi's import check of CRC is not connected without usage findings: connected usage: missing grant" "$W/out" && ok "a usage finding on CRC is named" || bad "a usage finding on CRC was not named: $(tail -1 "$W/out")"
pstop "CRC not connected" 'STUB_CLUSTERS={"clusterId":"CRC","status":"forbidden","findings":[]}'
pstop "the named monitoring API grant extends to another namespace" 'STUB_SAR_UWM=true RBAC: allowed by ClusterRoleBinding "x" of ClusterRole "cluster-monitoring-view" to ServiceAccount "cmapi-reader/cmapi-system"'
pstop "a positive count with a Thanos store warning" 'STUB_WARNINGS=["store unavailable"]'
pstop "an inconclusive scope review" 'STUB_SAR_UWM=inconclusive'
pstop "no kube_resourcequota series as the reader" STUB_QUOTAS=
pstop "kube_resourcequota counted 0 as the reader" 'STUB_QUOTAS={"metric":{},"value":[0,"0"]}'
pstop "a target Prometheus does not scrape" 'STUB_UP={"value":[0,"1"]}'
pstop "two api targets up and no worker" 'STUB_UP={"metric":{"job":"cmapi-api"},"value":[0,"1"]},{"metric":{"job":"cmapi-api"},"value":[0,"1"]}'
pstop "worker has not observed the bounded import" 'STUB_EXPIRY={"metric":{"job":"cmapi-api"},"value":[0,"1"]}'
pstop "no cmapi_cluster_status series at all" STUB_CONNECTED=
pstop "cmapi_cluster_status connected at 0" 'STUB_CONNECTED={"value":[0,"0"]},{"value":[0,"0"]}'
pstop "one target's series missing" 'STUB_CONNECTED={"value":[0,"1"]}'
pstop "one of the two targets not connected" 'STUB_CONNECTED={"value":[0,"1"]},{"value":[0,"0"]}'
pstop "two api series and no worker's" 'STUB_CONNECTED={"metric":{"job":"cmapi-api"},"value":[0,"1"]},{"metric":{"job":"cmapi-api"},"value":[0,"1"]}'
pstop "a test user who cannot sign in" STUB_NO_SIGN_IN=cmapi.auditor
pstop "a realm where cmapi-automation still takes the password grant" STUB_PASSWORD_GRANT=1
pstop "the automation token is of another caller" STUB_ME=bot-user
pstop "a test user with no password in the Secret" 'STUB_NO_PASSWORD=cmapi\.auditor'
pstop "a token with a group the table does not give" 'STUB_CLAIMS=cmapi.viewer:groups:["/cmapi/app-cmapi-rbac-viewer","/cmapi/app-cmapi-rbac-admin"]'
pstop "a token missing its group" 'STUB_CLAIMS=cmapi.requester:groups:[]'
pstop "an approver with the wrong role" 'STUB_CLAIMS=cmapi.approver-qa:resource_access:{"cmapi-nonprod":{"roles":["cmapi-admin"]}}'
pstop "the operator without its second role" 'STUB_CLAIMS=cmapi.operator:resource_access:{"cmapi-nonprod":{"roles":["cmapi-operator"]}}'
pstop "cmapi.noaccess holding a role" 'STUB_CLAIMS=cmapi.noaccess:resource_access:{"cmapi-nonprod":{"roles":["cmapi-viewer"]}}'
pstop "cmapi.noaccess in a group" 'STUB_CLAIMS=cmapi.noaccess:groups:["/cmapi/app-cmapi-rbac-viewer"]'
pstop "the wrong employee_id" 'STUB_CLAIMS=cmapi.admin:employee_id:"1"'
pstop "cmapi.noaccess answered 200" STUB_NOACCESS=200
pstop "the control: cmapi.viewer not answered 200" STUB_VIEWER=403
# A restart is the run's only from the run's start on (#425): CMAPI_PROOF_SINCE, step 2's first time in docs/13's step 23.
# Here the run began at 10:30; each pod started at 10:00, after the policies (09:00).
since=2026-11-06T10:30:00Z
want "proof passes with the database restarted before the run" 0 "$(CMAPI_PROOF_SINCE=$since STUB_CMAPI_DB_RESTARTS=1 STUB_CMAPI_DB_RUNNING=2026-11-06T09:45:24Z run "$D/crc-proof.sh" "$P")"
grep -qxF '    cmapi-db-1 restarted before the run, which began 2026-11-06T10:30:00Z (container database: 1 restarts, last terminated 2026-11-06T09:44:56Z, Completed, exit 0; running since 2026-11-06T09:45:24Z): reported, not failed' "$W/out" \
  && ok "and reports the pod, its count, its last termination's time and reason" || bad "the restart before the run is not reported: $(grep -i 'cmapi-db-1' "$W/out" | head -2)"
grep -qxF "proof: pods under restricted-v2 and Ready, no restart since the run began at $since, api and worker on sha256:aaaa, the front door on sha256:pppp" "$W/out" \
  && [ "$(tail -1 "$W/out")" = "proof: all passed" ] && ok "and every later proof ran" || bad "the proof after the pods: $(tail -1 "$W/out")"
pstop "the database restarted during the run" CMAPI_PROOF_SINCE=$since STUB_CMAPI_DB_RESTARTS=1 STUB_CMAPI_DB_RUNNING=2026-11-06T10:41:07Z STUB_CMAPI_DB_LAST=2026-11-06T10:41:00Z
says "FAIL: pods"; grep -q '^cmapi-db-1 restarted during the run, which began 2026-11-06T10:30:00Z (container database: 1 restarts, last terminated 2026-11-06T10:41:00Z, Completed, exit 0; running since 2026-11-06T10:41:07Z)$' "$W/out" \
  && ok "and names the pod, its termination and its start" || bad "the restart during the run is not named: $(head -1 "$W/out")"
pstop "a container back at the run's very second" CMAPI_PROOF_SINCE=$since STUB_CMAPI_DB_RESTARTS=1 STUB_CMAPI_DB_RUNNING=$since
pstop "a container down since before the run, not running" CMAPI_PROOF_SINCE=$since STUB_CMAPI_DB_RESTARTS=1 STUB_CMAPI_DB_RUNNING=
pstop "the api, worker and front door restarted after their rollout" CMAPI_PROOF_SINCE=$since STUB_START=2026-11-06T10:45:00Z STUB_RESTARTS=1 STUB_CMAPI_DB_RESTARTS=0
pstop "the database not Ready" STUB_NOT_READY=cmapi-db-1
says "FAIL: pods"; grep -q '^cmapi-db-1 not Ready$' "$W/out" && ok "and says which pod is not Ready" || bad "the pod not Ready is not named: $(head -1 "$W/out")"
pstop "the database restarted before the run and not Ready" CMAPI_PROOF_SINCE=$since STUB_CMAPI_DB_RESTARTS=1 STUB_CMAPI_DB_RUNNING=2026-11-06T09:45:24Z STUB_NOT_READY=cmapi-db-1
pstop "the front door not Ready" STUB_NOT_READY=p
pstop "a restart before the run with no run start given" STUB_CMAPI_DB_RESTARTS=1 STUB_CMAPI_DB_RUNNING=2026-11-06T09:45:24Z
pstop "migrate run again during the run" CMAPI_PROOF_SINCE=$since STUB_START=2026-11-06T10:45:00Z STUB_MIGRATE_RESTARTS=1 STUB_MIGRATE_STARTED=2026-11-06T10:46:10Z
says "FAIL: pods"; grep -q '^a restarted during the run, which began 2026-11-06T10:30:00Z (init container migrate: 1 restarts, last terminated unrecorded, no reason recorded, exit unrecorded; last run started 2026-11-06T10:46:10Z)' "$W/out" \
  && ok "and names the init container" || bad "the init container's restart is not named: $(head -1 "$W/out")"
want "proof passes with migrate run again before the run" 0 "$(CMAPI_PROOF_SINCE=$since STUB_MIGRATE_RESTARTS=2 STUB_MIGRATE_STARTED=2026-11-06T10:00:30Z run "$D/crc-proof.sh" "$P")"
pstop "the database back since the run began with its count at 0" CMAPI_PROOF_SINCE=$since STUB_CMAPI_DB_RESTARTS=0 STUB_CMAPI_DB_RUNNING=2026-11-06T10:41:07Z
want "proof passes with pods the run rolled, each at 0" 0 "$(CMAPI_PROOF_SINCE=$since STUB_START=2026-11-06T10:45:00Z run "$D/crc-proof.sh" "$P")"
for v in "" 2026-11-06 "2026-11-06 10:30:00" 2026-11-06T10:30:00+00:00 2026-13-06T10:30:00Z; do pstop "a run start of '$v'" "CMAPI_PROOF_SINCE=$v"
  ! grep -q '^oc ' "$ARGV_LOG" && grep -q '^FAIL: CMAPI_PROOF_SINCE' "$W/out" && ok "a run start of '$v' stops before the cluster is touched" || bad "a run start of '$v' was not refused first: $(tail -1 "$W/out")"; done
unset STUB_PROOF

# crc-rollback.sh: every delete names one object, from a fixed list.
want "rollback needs --yes" 2 "$(run "$D/crc-rollback.sh")"; [ ! -s "$ARGV_LOG" ] && ok "and does nothing without it" || bad "it ran without --yes"
: >"$ARGV_LOG.ldap-deleted"; want "rollback" 0 "$(run "$D/crc-rollback.sh" --yes)"
check_deletes() { python3 - "$ARGV_LOG" <<'PY'
import re,sys
ok={"secret cmapi-ldap-test-users -n cmapi","keycloakrealmimport cmapi -n keycloak","job cmapi-realm-sync -n cmapi","cluster.postgresql.cnpg.io cmapi-db -n cmapi","pvc cmapi-db-1 -n cmapi","pv pv-1","namespace cmapi-np-probe","namespace cmapi-imports","namespace cmapi-system","clusterrolebinding cmapi-reader","clusterrole cmapi-reader","secret cmapi-realm-secrets -n keycloak",
    "rolebinding cmapi-reader-metrics-api -n openshift-monitoring","rolebinding cmapi-reader-thanos-route -n openshift-monitoring","role cmapi-reader-thanos-route -n openshift-monitoring",
    "rolebinding cmapi-reader-grant-check -n openshift-monitoring","role cmapi-reader-grant-check -n openshift-monitoring",
    "clusterrolebinding cmapi-deliverer","clusterrole cmapi-deliverer","validatingadmissionpolicybinding cmapi-deliverer-managed-only","validatingadmissionpolicy cmapi-deliverer-managed-only"}
ok|={f"{k} {n} -n cmapi" for k,n in [("deployment","cmapi-api"),("deployment","cmapi-worker"),("deployment","cmapi-portal"),("pod","cmapi-np-target"),("service","cmapi-api"),("service","cmapi-api-pods"),("service","cmapi-worker"),("service","cmapi-portal"),("networkpolicy","cmapi-metrics"),("networkpolicy","cmapi-front-door"),("route.route.openshift.io","cmapi"),("route.route.openshift.io","cmapi-mockup"),("servicemonitor.monitoring.coreos.com","cmapi-api"),("servicemonitor.monitoring.coreos.com","cmapi-worker"),("prometheusrule.monitoring.coreos.com","cmapi"),("configmap","cmapi-env"),("configmap","cmapi-config"),("configmap","cmapi-trust"),("configmap","cmapi-trusted-ca"),("configmap","cmapi-portal-config"),("secret","cmapi-keys"),("secret","cmapi-keycloak"),("secret","cmapi-test-users"),("secret","cmapi-git"),("secret","cmapi-git-bot"),("secret","cmapi-git-bot-ssh"),("configmap","cmapi-git-bot-known-hosts"),("serviceaccount","cmapi-api"),("serviceaccount","cmapi-worker"),("serviceaccount","cmapi-jobs"),("imagestream.image.openshift.io","cmapi"),("imagestream.image.openshift.io","cmapi-portal")]}
bad=[]
for line in open(sys.argv[1]):
    if not line.startswith("oc delete "): continue
    words=[w for w in line[len("oc delete "):].split() if not w.startswith(("--ignore-not-found","--wait","--timeout"))]
    if " ".join(words) not in ok: bad.append(line.strip())
print("\n".join(bad)); sys.exit(1 if bad else 0)
PY
}
if out=$(check_deletes); then ok "rollback deletes only named objects from its list"; else bad "rollback deleted: $out"; fi
# LDAP: only the 23 full names of what the run added, and no other.
sed -n 's/^dn: //p' "$W/repo/examples/cmapi-sso/ldap/cmapi-groups.ldif" >"$W/ldap-want"; awk -F'\t' '!/^#/ && NF {print "cn=" $1 ",ou=People,dc=ephico2real,dc=com"}' "$W/repo/examples/cmapi-sso/ldap/test-identities.tsv" >>"$W/ldap-want"
[ "$(LC_ALL=C sort "$ARGV_LOG.ldap-deleted")" = "$(LC_ALL=C sort "$W/ldap-want")" ] && [ "$(wc -l <"$W/ldap-want" | tr -d ' ')" = 23 ] && ok "rollback gives ldapdelete exactly the 10 new groups and 13 test users, by full dn" || bad "rollback's LDAP deletes: $(cat "$ARGV_LOG.ldap-deleted")"
if grep -qE 'cmapi-(viewers|requesters|onboarding|prod-approvers)|john\.doe' "$ARGV_LOG.ldap-deleted"; then bad "rollback reached an entry the run did not add"; else ok "rollback reaches no other LDAP entry"; fi
if grep -qE 'delete .*(namespace cmapi( |$)|cmapi-ldap-bind|realm-secrets)' "$ARGV_LOG"; then bad "rollback touched namespace cmapi, the bind Secret or the realm's Secret"; else ok "namespace cmapi, cmapi-ldap-bind and the realm's Secret stay"; fi
if grep -qF 'admin/realms' "$ARGV_LOG"; then bad "rollback touched the realm without being asked"; else ok "the realm stays unless asked"; fi
: >"$ARGV_LOG"; [ "$(STUB_MANAGED_LEFT=namespace/team-a run "$D/crc-rollback.sh" --yes)" != 0 ] && ok "rollback stops while a namespace cmapi delivered is there" || bad "rollback went on with a delivered namespace there"
if grep -q '^oc delete ' "$ARGV_LOG"; then bad "and it deleted before stopping"; else ok "and deleted nothing"; fi
want "rollback: --delete-realm alone is refused" 2 "$(run "$D/crc-rollback.sh" --yes --delete-realm)"
if grep -qE 'delete ' "$ARGV_LOG"; then bad "it deleted something first"; fi
: >"$ARGV_LOG"; STUB_PV_WHO=inkcast/other/Bound "$D/crc-rollback.sh" --yes >"$W/out" 2>&1; if grep -q 'oc delete pv ' "$ARGV_LOG"; then bad "a PV another claim holds was deleted"; else ok "a PV that is not ours stays"; fi
cp "$ARGV_LOG" "$W/rollback-argv"; : >"$ARGV_LOG.ldap-deleted"; [ "$(STUB_LDAP_AFTER=b run "$D/crc-rollback.sh" --yes)" != 0 ] && ok "rollback fails when the rest of the directory moved" || bad "rollback passed with the rest of the directory moved"
# The static rule, on every script: no broad delete, no prune, ever. It must be able to fail: a copy with --all has to be caught.
broad() { cat "$@" | grep -vE '^[[:space:]]*#' | grep -nE '(oc_|oc|kc) delete .*( --all| -l | --selector| -f | -R)|(^|[[:space:]])del .*( --all| -l | --selector| -f | -R)|--prune'; }
if broad "$D"/crc-*.sh; then bad "a broad delete in a script"; else ok "no broad delete in any script"; fi
# The CRC import has its own field manager. All other scripts use the wave manager.
unmanaged() {
  local f manager
  for f in "$@"; do
    manager=cmapi-wave1
    [ "${f##*/}" != crc-reader-import.sh ] || manager=crc-reader-import.sh
    grep -vE '^[[:space:]]*#' "$f" | grep -E '(oc_|oc|kc) apply' | grep -vE -- "apply --server-side( --dry-run=server)? --field-manager=$manager " && return 0
  done
  return 1
}
if unmanaged "$D"/crc-*.sh; then bad "an apply without its field manager"; else ok "every apply is server-side with its field manager"; fi
printf 'oc_ apply --server-side -f -\n' >"$W/mut.sh"; if unmanaged "$W/mut.sh" >/dev/null; then ok "and that rule can fail"; else bad "the field-manager rule caught nothing"; fi
printf 'oc_ delete keycloakrealmimport --all -n keycloak\n' >"$W/mut.sh"; if broad "$W/mut.sh" >/dev/null; then ok "and that rule can fail"; else bad "the broad-delete rule caught nothing"; fi

echo "crc script cases failed: $fails"; [ "$fails" = 0 ]
