#!/usr/bin/env bash
# shellcheck disable=SC2015  # ok and bad here never fail, so A && ok || bad is if-then-else
# deploy/tests/crc-scripts-test.sh [<deploy dir>]: deploy/crc-{image,trust,reader-import,backup,rollback,proof}.sh on stubs of oc, podman, skopeo, curl and tmutil, for each thing they claim
# they can stop on, and for what they must never do: a credential on an argument list, a delete that does not name one object, a dump's path or content in the output. No cluster.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); SRC=$(cd "${1:-$HERE/..}" && pwd); W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
want() { local label=$1 rc=$2 got=$3; if [ "$got" = "$rc" ]; then ok "$label"; else bad "$label: rc $got, not $rc"; fi; }
TOKEN=sha256~stub-token-value-never-to-be-seen; SECRETVAL=stub-client-secret-never-to-be-seen; DUMP_MARK=stub-dump-content-never-to-be-seen
mkdir -p "$W/bin" "$W/repo/deploy"; cp "$SRC"/crc-*.sh "$W/repo/deploy/"; cp -R "$SRC/manifests" "$W/repo/deploy/"; export ARGV_LOG=$W/argv.log TOKEN SECRETVAL DUMP_MARK
openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/ca.pem" -subj "/CN=stub CA" -days 2 2>/dev/null
openssl req -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/leaf.csr" -subj "/CN=leaf" 2>/dev/null; export STUB_CA=$W/ca.pem
cat >"$W/bin/oc" <<'OC'
#!/usr/bin/env bash
printf 'oc %s\n' "$*" >>"$ARGV_LOG"
s="$*"
case "$s" in
  "get secret keycloak-tls -n keycloak -o jsonpath={.data.ca\.crt}") base64 <"$STUB_CA"; exit 0;;
  "get cm default-ingress-cert"*) cat "$STUB_CA"; exit 0;;
  "get istag cmapi:"*"--ignore-not-found"*) printf '%s' "${STUB_ISTAG:-}"; exit 0;;
  "get istag cmapi:"*) printf '%s' "${STUB_REGISTRY_DIGEST:-sha256:aaaa}"; exit 0;;
  "get route default-route"*) printf 'registry.stub'; exit 0;;
  "get route thanos-querier"*) printf 'thanos.stub'; exit 0;;
  "whoami -t") printf '%s\n' "$TOKEN"; exit 0;;
  "get secret cmapi-reader-token"*) [ -n "${STUB_NO_TOKEN:-}" ] && { echo '{"data":{}}'; exit 0; }; printf '{"data":{"token":"%s","ca.crt":"Y2E="}}\n' "$(printf '%s' "$TOKEN" | base64)"; exit 0;;
  "apply --server-side --field-manager=cmapi-wave1 -f -") cat >"$ARGV_LOG.applied"; exit 0;;
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
  delete*|label*|"create namespace"*|"run np-probe"*|"wait pod/np-probe"*) exit 0;;
  "get pods -n cmapi -o json") python3 -c 'import json,os
img=os.environ.get("STUB_IMAGE_ID","sha256:aaaa"); scc=os.environ.get("STUB_SCC","restricted-v2"); r=int(os.environ.get("STUB_RESTARTS","0")); start=os.environ.get("STUB_START","2026-11-06T10:00:00Z")
pod=lambda n,c:{"metadata":{"name":n,"labels":{"app.kubernetes.io/component":c},"annotations":{"openshift.io/scc":scc}},"spec":{"containers":[{}]},"status":{"phase":"Running","startTime":start,"containerStatuses":[{"restartCount":r,"imageID":"x@"+img}]}}
print(json.dumps({"items":[pod("a","api"),pod("w","worker"),pod("m","mockup")]}))'; exit 0;;
  "get networkpolicy cmapi-metrics"*) printf '2026-11-06T09:00:00Z'; exit 0;;
  "exec np-probe"*"cmapi-mockup"*) exit "${STUB_CONTROL_RC:-0}";;
  "exec np-probe"*"cmapi-api"*) exit "${STUB_BLOCK_RC:-1}";;
  "get secret cmapi-test-users"*) printf '%s' "$SECRETVAL" | base64; exit 0;;
  "auth can-i"*"--all-namespaces"*) echo "${STUB_READER_WIDE:-no}"; exit 0;;
  "auth can-i"*"cmapi-reader"*) echo yes; exit 0;;
  "auth can-i"*) echo "${STUB_WRITER:-no}"; exit 0;;
  "exec cmapi-db-1"*) echo "${STUB_SSL:-3|0}"; exit 0;;
esac
echo "stub oc: unhandled $s" >&2; exit 3
OC
cat >"$W/bin/podman" <<'P'
#!/usr/bin/env bash
printf 'podman %s\n' "$*" >>"$ARGV_LOG"
case "$1" in image) echo "${STUB_LABEL:-$(git -C "$REPO" rev-parse --short=10 HEAD)}";; esac; exit 0
P
cat >"$W/bin/skopeo" <<'P'
#!/usr/bin/env bash
printf 'skopeo %s\n' "$*" >>"$ARGV_LOG"
while [ $# -gt 0 ]; do case "$1" in --digestfile) printf 'sha256:aaaa' >"$2"; shift;; --dest-authfile) cp "$2" "$ARGV_LOG.auth"; stat -c '%a' "$2" 2>/dev/null >"$ARGV_LOG.mode" || stat -f '%Lp' "$2" >"$ARGV_LOG.mode"; shift;; esac; shift; done; exit "${STUB_SKOPEO_RC:-0}"
P
cat >"$W/bin/curl" <<'P'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >>"$ARGV_LOG"
if [ -n "${STUB_PROOF:-}" ]; then
  # The proof's curl: by URL. Anything on stdin is what a token must travel on, and it is swallowed here.
  url=; code=; for a in "$@"; do case "$a" in http*) url=$a;; esac; done; case "$*" in *-w*) wants=1;; *) wants=;; esac
  [ ! -p /dev/stdin ] || cat >/dev/null
  case "$url" in
    */readyz) code=${STUB_READYZ:-200}; case "$url" in http://*) code=302;; esac;;
    */api/v1/version) printf '{"commit":"%s"}' "${STUB_COMMIT:-$(git -C "$REPO" rev-parse --short=10 HEAD)}"; exit 0;;
    */metrics) code=${STUB_METRICS:-404};;
    */api/v1/me) case "$*" in *--config*) printf '{"username":"bot-user","roles":["cmapi-onboarding"]}'; exit 0;; *) code=401;; esac;;
    */portal.html) code=200;;
    */token) printf '{"access_token":"%s"}' "$TOKEN"; exit 0;;
    */namespaces*) printf '{"code":"%s"}\n%s' "${STUB_PLAN_CODE:-cluster-not-writable}" "${STUB_PLAN:-422}"; exit 0;;
    */api/v1/query*) case "$*" in *cluster_status*) printf '{"data":{"result":[%s]}}' "${STUB_CONNECTED-{\"value\":[0,\"1\"]\}}";; *) printf '{"data":{"result":[%s]}}' "${STUB_UP:-{\"value\":[0,\"1\"]\},{\"value\":[0,\"1\"]\}}";; esac; exit 0;;
  esac
  [ -z "$wants" ] || printf '%s' "$code"; exit 0
fi
cat >/dev/null 2>&1 </dev/null
exit_code=${STUB_CURL_RC:-0}; [ "$exit_code" = 0 ] || exit "$exit_code"
out=; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done; [ -z "$out" ] || : >"$out"; printf '%s' "${STUB_CURL_CODE:-200}"
P
printf '#!/bin/sh\nexit 0\n' >"$W/bin/tmutil"
chmod +x "$W/bin/"*; export PATH="$W/bin:$PATH"
cd "$W/repo" || exit 1; git init -q .; git -c user.email=t@t -c user.name=t commit -q --allow-empty -m t; export REPO=$W/repo; mkdir -p cmapi; printf 'version = "0.2.0"\n' >cmapi/pyproject.toml
D=$W/repo/deploy; TRUST=$D/manifests/environments/crc/30-trust.yaml
no_secret() { if grep -qF -e "$TOKEN" -e "$SECRETVAL" -e "$(printf '%s' "$TOKEN" | base64)" "$ARGV_LOG" "$1"; then bad "$2: a credential reached an argument or the output"; else ok "$2: no credential on an argument or in the output"; fi; }
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
want "trust --mac-ca" 0 "$(run "$D/crc-trust.sh" --mac-ca "$W/mac.pem")"; [ "$(grep -c 'BEGIN CERTIFICATE' "$W/mac.pem")" = 2 ] && ok "both CAs in the Mac's bundle" || bad "the Mac's bundle"
if grep -rqE -- '(^|[^-])(-k |--insecure|--tls-verify=false)' "$D"/crc-*.sh; then bad "TLS verification off in a script"; else ok "no script turns TLS verification off"; fi

# crc-image.sh
want "image: pushes and prints" 0 "$(run "$D/crc-image.sh")"; tail -1 "$W/out" | grep -qE '^image-registry\.openshift-image-registry\.svc:5000/cmapi/cmapi@sha256:' && ok "the last line is the reference render.sh takes" || bad "the image line: $(tail -1 "$W/out")"
no_secret "$W/out" "image"; [ "$(cat "$ARGV_LOG.mode")" = 600 ] && ok "the auth file is 0600" || bad "the auth file's mode"
grep -qF "$(printf 'unused:%s' "$TOKEN" | base64)" "$ARGV_LOG.auth" && ok "the auth file holds the session's token" || bad "the auth file's content"
grep -q -- '--dest-cert-dir' "$ARGV_LOG" && ok "skopeo verifies against the ingress CA" || bad "no --dest-cert-dir"
want "image: a pushed digest the image stream does not know stops" 1 "$(STUB_REGISTRY_DIGEST=sha256:bbbb run "$D/crc-image.sh")"
want "image: a wrong label stops" 1 "$(STUB_LABEL=other run "$D/crc-image.sh")"
want "image: a failed push stops" 1 "$(STUB_SKOPEO_RC=1 run "$D/crc-image.sh")"
want "image: an existing tag of this commit is reused" 0 "$(STUB_ISTAG="sha256:cccc $(git rev-parse --short=10 HEAD)" run "$D/crc-image.sh")"; if grep -q '^skopeo' "$ARGV_LOG"; then bad "it pushed again"; else ok "and not pushed again"; fi
want "image: an existing tag of another commit stops" 1 "$(STUB_ISTAG="sha256:cccc other" run "$D/crc-image.sh")"
printf x >>cmapi/pyproject.toml; git add -A >/dev/null; want "image: a dirty tree stops" 1 "$(run "$D/crc-image.sh")"; git -c user.email=t@t -c user.name=t commit -q -m t2

# crc-reader-import.sh
want "reader import" 0 "$(run "$D/crc-reader-import.sh")"; no_secret "$W/out" "reader import"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); m=d["metadata"]; sys.exit(0 if m["namespace"]=="cmapi-imports" and m["labels"]["cmapi.net/cluster-id"]=="CRC" and m["labels"]["cmapi.net/secret-type"]=="cluster" and set(d["data"])=={"apiUrl","token","caData"} else 1)' "$ARGV_LOG.applied" && ok "the import Secret is what the registry reads" || bad "the import Secret"
want "reader import: an unfilled token stops" 1 "$(CMAPI_READER_POLL=0 STUB_NO_TOKEN=1 run "$D/crc-reader-import.sh")"

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
export STUB_PROOF=1 CMAPI_PROOF_SCRAPE_TRIES=1 CMAPI_CRC_CA=$W/mac.pem; P=$W/rendered; mkdir -p "$P"; printf 'image-registry.openshift-image-registry.svc:5000/cmapi/cmapi@sha256:aaaa\n' >"$P/IMAGE"
want "proof passes when all is right" 0 "$(run "$D/crc-proof.sh" "$P")"; [ "$(tail -1 "$W/out")" = "proof: all passed" ] || bad "the proof's last line: $(tail -1 "$W/out")"
no_secret "$W/out" "proof"
pstop() { local label=$1; shift; local got; got=$(: >"$ARGV_LOG"; env "$@" "$D/crc-proof.sh" "$P" >"$W/out" 2>&1; echo $?); [ "$got" != 0 ] && ok "proof fails: $label" || bad "proof did not fail: $label"; }
pstop "a pod under another SCC" STUB_SCC=anyuid
pstop "a restart" STUB_RESTARTS=1
pstop "another image running" STUB_IMAGE_ID=sha256:bbbb
pstop "a pod started before the policy" STUB_START=2026-11-06T08:00:00Z
pstop "/readyz not 200" STUB_READYZ=503
pstop "another commit" STUB_COMMIT=other
pstop "/metrics on the Route" STUB_METRICS=200
pstop "the probe reaching the api: the policy not enforced" STUB_BLOCK_RC=0
pstop "the control failing: the block would prove nothing" STUB_CONTROL_RC=1
pstop "a worker that may write" STUB_WRITER=yes
pstop "a reader reading Secrets" STUB_READER_WIDE=yes
pstop "a plan that passes" STUB_PLAN=200
pstop "a 422 of another kind" STUB_PLAN_CODE=validation-failed
pstop "a connection without TLS" "STUB_SSL=3|1"
pstop "no connection at all" "STUB_SSL=0|0"
pstop "a target Prometheus does not scrape" 'STUB_UP={"value":[0,"1"]}'
pstop "no cmapi_cluster_status series at all" STUB_CONNECTED=
pstop "cmapi_cluster_status connected at 0" 'STUB_CONNECTED={"value":[0,"0"]}'
unset STUB_PROOF

# crc-rollback.sh: every delete names one object, from a fixed list.
want "rollback needs --yes" 2 "$(run "$D/crc-rollback.sh")"; [ ! -s "$ARGV_LOG" ] && ok "and does nothing without it" || bad "it ran without --yes"
want "rollback" 0 "$(run "$D/crc-rollback.sh" --yes)"
check_deletes() { python3 - "$ARGV_LOG" <<'PY'
import re,sys
ok={"keycloakrealmimport cmapi -n keycloak","job cmapi-realm-sync -n cmapi","cluster.postgresql.cnpg.io cmapi-db -n cmapi","pvc cmapi-db-1 -n cmapi","pv pv-1","namespace cmapi-np-probe","namespace cmapi-imports","namespace cmapi-system","clusterrolebinding cmapi-reader","clusterrole cmapi-reader","secret cmapi-realm-secrets -n keycloak"}
ok|={f"{k} {n} -n cmapi" for k,n in [("deployment","cmapi-api"),("deployment","cmapi-worker"),("deployment","cmapi-mockup"),("service","cmapi-api"),("service","cmapi-worker"),("service","cmapi-mockup"),("networkpolicy","cmapi-metrics"),("route.route.openshift.io","cmapi-api"),("route.route.openshift.io","cmapi-mockup"),("servicemonitor.monitoring.coreos.com","cmapi-api"),("servicemonitor.monitoring.coreos.com","cmapi-worker"),("prometheusrule.monitoring.coreos.com","cmapi"),("configmap","cmapi-env"),("configmap","cmapi-config"),("configmap","cmapi-trust"),("configmap","cmapi-mockup"),("secret","cmapi-keys"),("secret","cmapi-keycloak"),("secret","cmapi-test-users"),("serviceaccount","cmapi-api"),("serviceaccount","cmapi-worker"),("serviceaccount","cmapi-jobs"),("imagestream.image.openshift.io","cmapi")]}
bad=[]
for line in open(sys.argv[1]):
    if not line.startswith("oc delete "): continue
    words=[w for w in line[len("oc delete "):].split() if not w.startswith(("--ignore-not-found","--wait","--timeout"))]
    if " ".join(words) not in ok: bad.append(line.strip())
print("\n".join(bad)); sys.exit(1 if bad else 0)
PY
}
if out=$(check_deletes); then ok "rollback deletes only named objects from its list"; else bad "rollback deleted: $out"; fi
if grep -qE 'delete .*(namespace cmapi( |$)|cmapi-ldap-bind|realm-secrets)' "$ARGV_LOG"; then bad "rollback touched namespace cmapi, the bind Secret or the realm's Secret"; else ok "namespace cmapi, cmapi-ldap-bind and the realm's Secret stay"; fi
if grep -qF 'admin/realms' "$ARGV_LOG"; then bad "rollback touched the realm without being asked"; else ok "the realm stays unless asked"; fi
want "rollback: --delete-realm alone is refused" 2 "$(run "$D/crc-rollback.sh" --yes --delete-realm)"
if grep -qE 'delete ' "$ARGV_LOG"; then bad "it deleted something first"; fi
: >"$ARGV_LOG"; STUB_PV_WHO=inkcast/other/Bound "$D/crc-rollback.sh" --yes >"$W/out" 2>&1; if grep -q 'oc delete pv ' "$ARGV_LOG"; then bad "a PV another claim holds was deleted"; else ok "a PV that is not ours stays"; fi
# The static rule, on every script: no broad delete, no prune, ever. It must be able to fail: a copy with --all has to be caught.
broad() { cat "$@" | grep -vE '^[[:space:]]*#' | grep -nE '(oc_|oc|kc) delete .*( --all| -l | --selector| -f | -R)|(^|[[:space:]])del .*( --all| -l | --selector| -f | -R)|--prune'; }
if broad "$D"/crc-*.sh; then bad "a broad delete in a script"; else ok "no broad delete in any script"; fi
# Every apply server-side, under the one field manager, so a later reader can see which fields this wave owns. Also able to fail.
unmanaged() { cat "$@" | grep -vE '^[[:space:]]*#' | grep -E '(oc_|oc|kc) apply' | grep -vE -- 'apply --server-side( --dry-run=server)? --field-manager=cmapi-wave1 '; }
if unmanaged "$D"/crc-*.sh; then bad "an apply without --field-manager=cmapi-wave1"; else ok "every apply in the scripts is --server-side --field-manager=cmapi-wave1"; fi
printf 'oc_ apply --server-side -f -\n' >"$W/mut.sh"; if unmanaged "$W/mut.sh" >/dev/null; then ok "and that rule can fail"; else bad "the field-manager rule caught nothing"; fi
printf 'oc_ delete keycloakrealmimport --all -n keycloak\n' >"$W/mut.sh"; if broad "$W/mut.sh" >/dev/null; then ok "and that rule can fail"; else bad "the broad-delete rule caught nothing"; fi

echo "crc script cases failed: $fails"; [ "$fails" = 0 ]
