#!/usr/bin/env bash
# shellcheck disable=SC2015  # ok and bad here never fail, so A && ok || bad is if-then-else
# deploy/tests/kind-import-test.sh [<deploy dir>]: deploy/kind-import/{up,down,kyverno}.sh on stubs of kind, kubectl, helm, oc, ifconfig,
# curl and openssl's s_client, for each thing they claim they stop on, and for what they must never do: the token on an argument list or
# in the output, a delete that does not name one object, a write after a moved address, a Kyverno or bundle call that is not kind's
# (#430), a bundle applied after a failed install or a refused dry run. No cluster.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); SRC=$(cd "${1:-$HERE/..}" && pwd); W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
want() { local label=$1 rc=$2 got=$3; if [ "$got" = "$rc" ]; then ok "$label"; else bad "$label: rc $got, not $rc ($(tail -3 "$W/out" | tr '\n' ' '))"; fi; }
mkdir -p "$W/bin" "$W/repo/deploy"; cp -R "$SRC/kind-import" "$W/repo/deploy/"; D=$W/repo/deploy/kind-import
[ -d "$SRC/kyverno" ] && cp -R "$SRC/kyverno" "$W/repo/deploy/"
# A checkout of cmapi-cluster-configs with the rnd bundle committed: three files and the index, which is not a Kubernetes object.
B=$W/ccfg/policies/env/rnd; mkdir -p "$B"
for f in metadata quota limits; do printf 'apiVersion: policies.kyverno.io/v1\nkind: ValidatingPolicy\nmetadata: {name: cmapi-%s-rnd-x}\n' "$f" >"$B/cmapi-$f-rnd.yaml"; done
echo '{}' >"$B/index.json"
git -C "$W/ccfg" init -q && git -C "$W/ccfg" add -A && git -C "$W/ccfg" -c user.name=t -c user.email=t@example.invalid commit -qm bundle
CCFG=$W/ccfg; CCFG_COMMIT=$(git -C "$CCFG" rev-parse HEAD)
REAL_OPENSSL=$(command -v openssl); REAL_PYTHON3=$(command -v python3)
# A JWT shaped as kubectl create token prints it; every part of it is the secret.
IAT=1794964470; EXP=$((IAT + 604800))
b64url() { python3 -c 'import base64,sys; print(base64.urlsafe_b64encode(sys.stdin.read().encode()).decode().rstrip("="))'; }
TOKEN="$(printf '{"alg":"RS256"}' | b64url).$(printf '{"sub":"system:serviceaccount:cmapi-system:cmapi-reader","iat":%s,"exp":%s}' "$IAT" "$EXP" | b64url).stub-signature-never-to-be-seen"
cert() { "$REAL_OPENSSL" req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/$1.pem" -subj "/CN=kube-apiserver" -days 2 -addext "subjectAltName=$2" 2>/dev/null; }
cert ca "DNS:kubernetes"
cert served "DNS:cmapi-test-control-plane,DNS:host.crc.testing,DNS:localhost,IP:10.96.0.1,IP:192.168.86.110,IP:127.0.0.1"
cert other-ip "DNS:host.crc.testing,IP:192.168.86.111,IP:127.0.0.1"
cert no-crc "DNS:localhost,IP:192.168.86.110,IP:127.0.0.1"
export ARGV_LOG=$W/argv.log TOKEN STUB_CA=$W/ca.pem STUB_SERVED=$W/served.pem REAL_OPENSSL REAL_PYTHON3 KIND_IMPORT_KUBECONFIG=$W/kc
stub() { cat >"$W/bin/$1"; chmod +x "$W/bin/$1"; }
stub kind <<'S'
#!/usr/bin/env bash
printf 'kind %s\n' "$*" >>"$ARGV_LOG"
case "$*" in
  "get clusters") [ -n "${STUB_KIND_CLUSTERS:-}" ] && printf '%s\n' "$STUB_KIND_CLUSTERS"; [ -n "${STUB_KIND_CLUSTERS:-}" ] || echo "No kind clusters found." >&2; exit 0;;
  "create cluster "*|"export kubeconfig "*|"delete cluster "*) exit 0;;
esac
echo "stub kind: unhandled $*" >&2; exit 3
S
stub kubectl <<'S'
#!/usr/bin/env bash
printf 'kubectl %s\n' "$*" >>"$ARGV_LOG"
s="$*"; s=${s#--kubeconfig=* }
case "$s" in
  "config current-context") echo "${STUB_CONTEXT:-kind-cmapi-test}"; exit 0;;
  "config view --raw --minify -o jsonpath={.clusters[0].cluster.certificate-authority-data}") base64 <"$STUB_CA" | tr -d '\n'; exit 0;;
  "apply --server-side --field-manager=cmapi-baseline -f "*/reader.yaml) exit 0;;
  "config view --minify -o jsonpath={.clusters[0].cluster.server}") echo "${STUB_KIND_API:-https://192.168.86.110:16443}"; exit 0;;
  "wait --for=condition=Established --timeout=60s crd/validatingpolicies.policies.kyverno.io") exit 0;;
  "apply --server-side --field-manager=cmapi-policies --dry-run=server -f "*) [ -n "${STUB_DRYRUN_FAIL:-}" ] && { echo "admission webhook denied the request" >&2; exit 1; }; exit 0;;
  "apply --server-side --field-manager=cmapi-policies -f "*) exit 0;;
  "wait --for=jsonpath={.status.conditionStatus.ready}=true --timeout=120s -f "*) [ -n "${STUB_NOT_READY:-}" ] && { echo "timed out waiting for the condition" >&2; exit 1; }; exit 0;;
  "get -f "*" -o name") for i in $(seq 31); do echo "validatingpolicy.policies.kyverno.io/p$i"; done; exit 0;;
  "create token cmapi-reader -n cmapi-system --duration=168h") [ -n "${STUB_TOKEN_FAIL:-}" ] && { echo "error: serviceaccounts not found" >&2; exit 1; }; printf '%s\n' "$TOKEN"; exit 0;;
esac
echo "stub kubectl: unhandled $s" >&2; exit 3
S
stub helm <<'S'
#!/usr/bin/env bash
printf 'helm %s\n' "$*" >>"$ARGV_LOG"
[ -n "${STUB_HELM_FAIL:-}" ] && { echo "Error: UPGRADE FAILED: context deadline exceeded" >&2; exit 1; }
case "$*" in "--kubeconfig "*" --kube-context kind-cmapi-test upgrade --install kyverno kyverno "*) exit 0;; esac
echo "stub helm: unhandled $*" >&2; exit 3
S
stub oc <<'S'
#!/usr/bin/env bash
printf 'oc %s\n' "$*" >>"$ARGV_LOG"
case "$*" in
  "whoami --show-server") echo "${STUB_SERVER:-https://api.crc.testing:6443}"; exit 0;;
  "apply --server-side --field-manager=cmapi-baseline -f -") cat >"$ARGV_LOG.applied"; exit 0;;
  "get secret cmapi-cluster-kind-cmapi-test -n cmapi-imports --ignore-not-found -o name") printf '%s' "${STUB_SECRET-secret/cmapi-cluster-kind-cmapi-test}"; exit 0;;
  "get secret cmapi-cluster-kind-cmapi-test -n cmapi-imports -o jsonpath={.metadata.labels.cmapi\.net/cluster-id}") printf '%s' "${STUB_SECRET_ID-KIND_CMAPI_TEST}"; exit 0;;
  "delete secret cmapi-cluster-kind-cmapi-test -n cmapi-imports") exit 0;;
esac
echo "stub oc: unhandled $*" >&2; exit 3
S
stub ifconfig <<'S'
#!/usr/bin/env bash
printf 'lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\nen8: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n\tinet %s netmask 0xffffff00 broadcast 192.168.86.255\n' "${STUB_ADDR:-192.168.86.110}"
S
stub openssl <<'S'
#!/usr/bin/env bash
if [ "${1:-}" = s_client ]; then printf 'openssl %s\n' "$*" >>"$ARGV_LOG"; [ -n "${STUB_NO_SERVER:-}" ] && exit 1; cat "$STUB_SERVED"; exit 0; fi
# STUB_LIBRESSL: macOS's own /usr/bin/openssl, LibreSSL 3.3.6, whose x509 has no -ext (measured: "unknown option -ext", rc 1).
if [ -n "${STUB_LIBRESSL:-}" ]; then for a in "$@"; do [ "$a" = -ext ] && { echo "unknown option -ext" >&2; exit 1; }; done; fi
exec "$REAL_OPENSSL" "$@"
S
# python3 too: a token on import-secret.py's argument list is as visible in ps as one on oc's.
stub python3 <<'S'
#!/usr/bin/env bash
printf 'python3 %s\n' "$*" >>"$ARGV_LOG"
exec "$REAL_PYTHON3" "$@"
S
stub curl <<'S'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >>"$ARGV_LOG"
exit "${STUB_CURL_RC:-0}"
S
export PATH="$W/bin:$PATH"
run() { : >"$ARGV_LOG"; rm -f "$ARGV_LOG.applied"; "$@" >"$W/out" 2>&1; echo $?; }
no_secret() { if grep -qF -e "$TOKEN" -e "stub-signature-never-to-be-seen" "$ARGV_LOG" "$W/out"; then bad "$1: the token is on an argument list or in the output"; else ok "$1: the token is on no argument list and not in the output"; fi; }
wrote_nothing() { if grep -qE '^(oc apply|oc delete|kind create|kind delete|kubectl .*(apply|create token)|helm )' "$ARGV_LOG"; then bad "$1: it wrote first: $(grep -E '^(oc apply|oc delete|kind create|kind delete|kubectl .*(apply|create token)|helm )' "$ARGV_LOG" | head -2 | tr '\n' ' ')"; else ok "$1: and wrote nothing"; fi; }
no_bundle() { if grep -qE -- '--field-manager=cmapi-policies( -f |$)' "$ARGV_LOG"; then bad "$1: the bundle was applied"; else ok "$1: and no policy applied"; fi; }
no_import() { [ -s "$ARGV_LOG.applied" ] && bad "$1: the import Secret was written" || ok "$1: and no import Secret written"; }
says() { grep -qF -- "$2" "$W/out" && ok "$1: says \"$2\"" || bad "$1: the message does not say \"$2\": $(tr '\n' ' ' <"$W/out")"; }

echo "up.sh"
want "a new cluster" 0 "$(run "$D/up.sh" "$CCFG")"; no_secret "a new cluster"
grep -qxF "kind create cluster --config $D/kind-cmapi-test.yaml --kubeconfig $W/kc --wait 180s" "$ARGV_LOG" && ok "created from kind-cmapi-test.yaml" || bad "the create: $(grep '^kind create' "$ARGV_LOG")"
python3 - "$ARGV_LOG.applied" "$TOKEN" "$STUB_CA" "$EXP" <<'PY' && ok "the import Secret is docs/02's contract" || bad "the import Secret"
import base64, datetime, json, sys
d = json.load(open(sys.argv[1])); m = d["metadata"]; v = {k: base64.b64decode(x).decode() for k, x in d["data"].items()}
exp = datetime.datetime.fromtimestamp(int(sys.argv[4]), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
assert (m["name"], m["namespace"]) == ("cmapi-cluster-kind-cmapi-test", "cmapi-imports"), m
assert m["labels"]["cmapi.net/secret-type"] == "cluster" and m["labels"]["cmapi.net/cluster-id"] == "KIND_CMAPI_TEST", m
assert m["annotations"] == {"cmapi.net/managed-by": "cluster-baseline", "cmapi.net/token-expires-at": exp}, m
assert v == {"apiUrl": "https://192.168.86.110:16443", "token": sys.argv[2], "caData": open(sys.argv[3]).read(), "insecure": "false"}, v
PY
grep -qE '^curl .*--cacert .* https://192\.168\.86\.110:16443/version$' "$ARGV_LOG" && ok "kind's CA verifies the API before the import" || bad "no verified /version"
want "an existing cluster is reused and its token rewritten" 0 "$(STUB_KIND_CLUSTERS=$'other\ncmapi-test' run "$D/up.sh" "$CCFG")"; no_secret "a rerun"
if grep -q '^kind create' "$ARGV_LOG"; then bad "it created again"; else ok "and not created again"; fi
[ -s "$ARGV_LOG.applied" ] && ok "and the Secret written again (the rotation)" || bad "no Secret on a rerun"
want "a moved DHCP lease stops" 1 "$(STUB_ADDR=192.168.86.57 run "$D/up.sh" "$CCFG")"; says "a moved lease" "no longer holds 192.168.86.110"; wrote_nothing "a moved lease"
want "a served certificate for another address stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_SERVED=$W/other-ip.pem run "$D/up.sh" "$CCFG")"; says "another address" "does not name 192.168.86.110"; wrote_nothing "another address"
want "a served certificate without host.crc.testing stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_SERVED=$W/no-crc.pem run "$D/up.sh" "$CCFG")"; wrote_nothing "no host.crc.testing"
want "no API server answering stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_NO_SERVER=1 run "$D/up.sh" "$CCFG")"; wrote_nothing "no API server"
want "an oc that is not CRC's stops" 1 "$(STUB_SERVER=https://api.other.example:6443 run "$D/up.sh" "$CCFG")"; wrote_nothing "not CRC"
want "a CA that does not verify the API stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_CURL_RC=60 run "$D/up.sh" "$CCFG")"; wrote_nothing "an unverified API"
want "a failed TokenRequest stops" 1 "$(STUB_TOKEN_FAIL=1 run "$D/up.sh" "$CCFG")"
[ -s "$ARGV_LOG.applied" ] && bad "and a Secret was applied without a token" || ok "and no Secret is applied"
want "an argument is refused" 2 "$(run "$D/up.sh" --force)"
want "macOS's LibreSSL openssl (no -ext) still reads the served names" 0 "$(STUB_LIBRESSL=1 STUB_KIND_CLUSTERS=cmapi-test run "$D/up.sh" "$CCFG")"
want "and still stops on a certificate for another address" 1 "$(STUB_LIBRESSL=1 STUB_KIND_CLUSTERS=cmapi-test STUB_SERVED=$W/other-ip.pem run "$D/up.sh" "$CCFG")"; says "LibreSSL, another address" "does not name 192.168.86.110"
# Whole names: on 192.168.86.11 a certificate for 192.168.86.110 must not pass.
cp -R "$D" "$W/k11"; sed -i.bak 's/192\.168\.86\.110/192.168.86.11/g' "$W/k11/kind-cmapi-test.yaml" "$W/k11/pf-cmapi-kind.conf"
want "a certificate for a longer address does not pass" 1 "$(STUB_ADDR=192.168.86.11 STUB_KIND_CLUSTERS=cmapi-test run "$W/k11/up.sh" "$CCFG")"; wrote_nothing "a longer address"
cp -R "$D" "$W/kpf"; sed -i.bak 's/192\.168\.86\.110/192.168.86.111/' "$W/kpf/pf-cmapi-kind.conf"
want "a pf anchor for another address stops" 1 "$(run "$W/kpf/up.sh" "$CCFG")"; says "the pf anchor" "does not drop"; wrote_nothing "the pf anchor"
cp -R "$D" "$W/ksan"; sed -i.bak 's/certSANs: \[localhost, 127.0.0.1, 192.168.86.110, host.crc.testing\]/certSANs: [localhost, 127.0.0.1, host.crc.testing]/' "$W/ksan/kind-cmapi-test.yaml"
want "certSANs without the address stop" 1 "$(run "$W/ksan/up.sh" "$CCFG")"; wrote_nothing "certSANs"

echo "Kyverno and the rnd bundle on kind (#430)"
want "up.sh with the bundle" 0 "$(run "$D/up.sh" "$CCFG")"; no_secret "with the bundle"
k=$(grep -c '^kubectl ' "$ARGV_LOG"); notkind=$(grep '^kubectl ' "$ARGV_LOG" | grep -vF "kubectl --kubeconfig=$W/kc ")
[ "$k" -gt 0 ] && [ -z "$notkind" ] && ok "each of its $k kubectl calls names kind's kubeconfig" || bad "a kubectl call without kind's kubeconfig: $notkind"
want_helm="helm --kubeconfig $W/kc --kube-context kind-cmapi-test upgrade --install kyverno kyverno --repo https://kyverno.github.io/kyverno/ --version 3.10.0 -n kyverno --create-namespace -f $D/../kyverno/kind-values.yaml --wait --timeout 8m"
[ "$(grep '^helm ' "$ARGV_LOG")" = "$want_helm" ] && ok "one helm call: chart 3.10.0 with kind-values.yaml, kind's kubeconfig and context" || bad "the helm calls: $(grep '^helm ' "$ARGV_LOG")"
[ -f "$D/../kyverno/kind-values.yaml" ] && ok "and deploy/kyverno/kind-values.yaml is there" || bad "no deploy/kyverno/kind-values.yaml"
files="-f $B/cmapi-metadata-rnd.yaml -f $B/cmapi-quota-rnd.yaml -f $B/cmapi-limits-rnd.yaml"
grep -qxF "kubectl --kubeconfig=$W/kc apply --server-side --field-manager=cmapi-policies --dry-run=server $files" "$ARGV_LOG" && ok "the server dry run names the three files" || bad "the dry run: $(grep -- '--dry-run=server' "$ARGV_LOG")"
grep -qxF "kubectl --kubeconfig=$W/kc apply --server-side --field-manager=cmapi-policies $files" "$ARGV_LOG" && ok "the apply names the three files, not index.json or the folder" || bad "the apply: $(grep -- '--field-manager=cmapi-policies -f' "$ARGV_LOG")"
# The order: the reader, Kyverno, the dry run, the apply, the readiness, then the import's token.
order=$(awk -v kc="kubectl --kubeconfig=$W/kc " '
  index($0, kc "apply --server-side --field-manager=cmapi-baseline") == 1 { print "reader" }
  /^helm / { print "helm" }
  index($0, kc "apply --server-side --field-manager=cmapi-policies --dry-run=server") == 1 { print "dryrun"; next }
  index($0, kc "apply --server-side --field-manager=cmapi-policies -f") == 1 { print "apply" }
  index($0, kc "wait --for=jsonpath=") == 1 { print "ready" }
  index($0, kc "create token") == 1 { print "token" }' "$ARGV_LOG" | tr '\n' ' ')
[ "$order" = "reader helm dryrun apply ready token " ] && ok "in order: reader, helm, dry run, apply, ready, token" || bad "the order: $order"
says "the commit" "at commit $CCFG_COMMIT"; says "the count" "31 policies of rnd applied and ready"
want "a failed Kyverno install stops" 1 "$(STUB_HELM_FAIL=1 run "$D/up.sh" "$CCFG")"; says "a failed install" "the Kyverno install failed"; no_bundle "a failed install"; no_import "a failed install"
if grep -q -- '--dry-run=server' "$ARGV_LOG"; then bad "a failed install: the dry run ran"; else ok "a failed install: and no dry run"; fi
want "a refused server dry run stops" 1 "$(STUB_DRYRUN_FAIL=1 run "$D/up.sh" "$CCFG")"; says "a refused dry run" "nothing was applied"; no_bundle "a refused dry run"; no_import "a refused dry run"
want "a policy not ready stops" 1 "$(STUB_NOT_READY=1 run "$D/up.sh" "$CCFG")"; says "not ready" "is not ready"; no_import "not ready"
want "a kubeconfig that talks to CRC stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_KIND_API=https://api.crc.testing:6443 run "$D/up.sh" "$CCFG")"; says "CRC's server" "not kind's https://192.168.86.110:16443"; wrote_nothing "CRC's server"
want "a kubeconfig of another context stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_CONTEXT=crc-admin run "$D/up.sh" "$CCFG")"; wrote_nothing "another context"
want "no checkout is refused" 2 "$(run "$D/up.sh")"; wrote_nothing "no checkout"
want "two arguments are refused" 2 "$(run "$D/up.sh" "$CCFG" "$CCFG")"; wrote_nothing "two arguments"
mkdir -p "$W/empty"; git -C "$W/empty" init -q; git -C "$W/empty" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m none
want "a checkout without the rnd files stops" 1 "$(run "$D/up.sh" "$W/empty")"; says "no rnd files" "no cmapi-metadata-rnd.yaml"; wrote_nothing "no rnd files"
mkdir -p "$W/plain/policies/env/rnd"; cp "$B"/*.yaml "$W/plain/policies/env/rnd/"
want "files that are no commit stop" 1 "$(run "$D/up.sh" "$W/plain")"; says "no commit" "is not a git checkout"; wrote_nothing "no commit"
cp -R "$CCFG" "$W/dirty"; echo '# local edit' >>"$W/dirty/policies/env/rnd/cmapi-quota-rnd.yaml"
want "a changed policies/env/rnd stops" 1 "$(run "$D/up.sh" "$W/dirty")"; says "a working copy" "apply a commit, not a working copy"; wrote_nothing "a working copy"
want "kyverno.sh alone, after a bundle change" 0 "$(STUB_KIND_CLUSTERS=cmapi-test run "$D/kyverno.sh" "$CCFG")"
if grep -q '^oc ' "$ARGV_LOG"; then bad "kyverno.sh called oc: $(grep '^oc ' "$ARGV_LOG" | head -2 | tr '\n' ' ')"; else ok "and nothing of it goes to CRC (no oc call)"; fi
want "kyverno.sh with no checkout is refused" 2 "$(run "$D/kyverno.sh")"; wrote_nothing "kyverno.sh, no checkout"
want "kyverno.sh on CRC's kubeconfig stops" 1 "$(STUB_KIND_API=https://api.crc.testing:6443 run "$D/kyverno.sh" "$CCFG")"; wrote_nothing "kyverno.sh on CRC's"
# The bundle is the environment of KIND_CMAPI_TEST in the registry: rnd on both sides, or the tab reads it off its bundle.
reg=$(awk '/^  KIND_CMAPI_TEST:/ { f = 1; next } f && /^  [^ ]/ { exit } f && $1 == "environment:" { print $2; exit }' "$SRC/environments/crc.yaml")
env=$(awk -F= '$1 == "ENVIRONMENT" { print $2 }' "$D/common.sh")
[ -n "$reg" ] && [ "$reg" = "$env" ] && ok "kind's bundle is its registry environment ($env)" || bad "deploy/environments/crc.yaml has KIND_CMAPI_TEST in '$reg', common.sh applies '$env'"

echo "down.sh"
want "deletes the Secret, then the cluster" 0 "$(STUB_KIND_CLUSTERS=$'other\ncmapi-test' run "$D/down.sh")"
deletes=$(grep -E '^(oc|kind|kubectl) .*delete' "$ARGV_LOG")
[ "$deletes" = "oc delete secret cmapi-cluster-kind-cmapi-test -n cmapi-imports
kind delete cluster --name cmapi-test --kubeconfig $W/kc" ] && ok "each by name, the Secret first, nothing else" || bad "the deletes: $deletes"
want "a moved DHCP lease stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_ADDR=192.168.86.57 run "$D/down.sh")"; says "down, a moved lease" "--stale"; wrote_nothing "down, a moved lease"
want "--stale deletes both after a move" 0 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_ADDR=192.168.86.57 STUB_NO_SERVER=1 run "$D/down.sh" --stale)"
[ "$(grep -cE '^(oc delete secret cmapi-cluster-kind-cmapi-test -n cmapi-imports|kind delete cluster --name cmapi-test )' "$ARGV_LOG")" = 2 ] && ok "and deletes both by name" || bad "--stale: $(grep delete "$ARGV_LOG")"
want "a served certificate for another address stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_SERVED=$W/other-ip.pem run "$D/down.sh")"; wrote_nothing "down, another address"
want "a Secret of another cluster is left" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_SECRET_ID=CRC run "$D/down.sh")"; wrote_nothing "another cluster's Secret"
want "an oc that is not CRC's stops" 1 "$(STUB_SERVER=https://api.other.example:6443 run "$D/down.sh")"; wrote_nothing "down, not CRC"
want "nothing there: nothing deleted" 0 "$(STUB_SECRET='' run "$D/down.sh")"; wrote_nothing "nothing there"
want "an unknown argument is refused" 2 "$(run "$D/down.sh" --all)"; wrote_nothing "--all"

echo "the scripts, read"
# No broad delete, ever, and every kind delete names the cluster. Both rules must be able to fail: a mutant has to be caught.
# shellcheck disable=SC2016  # the one allowed form, as written in down.sh, not expanded
named='kind delete cluster --name "$NAME" --kubeconfig "$KC"'
broad() { cat "$@" | grep -vE '^[[:space:]]*#' | grep -nE '(oc_|oc|kc|kubectl) delete .*( --all| -l | --selector| -f | -R)|--prune|kind delete' | grep -vF "$named"; }
if broad "$D"/*.sh; then bad "a broad delete in a script"; else ok "no broad delete in deploy/kind-import"; fi
printf 'kind delete clusters --all\n' >"$W/mut.sh"; if broad "$W/mut.sh" >/dev/null; then ok "and that rule can fail (kind delete clusters --all)"; else bad "the broad-delete rule caught nothing"; fi
printf 'kind delete cluster\n' >"$W/mut.sh"; if broad "$W/mut.sh" >/dev/null; then ok "and a kind delete without --name is caught"; else bad "a kind delete without --name passed"; fi
printf 'oc_ delete secret -n cmapi-imports -l cmapi.net/secret-type=cluster\n' >"$W/mut.sh"; if broad "$W/mut.sh" >/dev/null; then ok "and a label-selector delete is caught"; else bad "a selector delete passed"; fi

# The pf rule is this lab Mac's, never cmapi's: cmapi consumes a hub-to-cluster path and manages no firewall (docs/13).
doc=$SRC/../docs/13-crc-deployment.md
grep -qF "it is not part of cmapi" "$doc" && grep -qF "never opens, closes or manages a firewall" "$doc" && ok "docs/13: the pf rule is lab only, not cmapi's" || bad "docs/13 does not say the pf rule is lab only and not part of cmapi"
grep -qF "Lab only: this Mac's firewall, not part of cmapi" "$D/pf-cmapi-kind.conf" && ok "pf-cmapi-kind.conf says it is lab only" || bad "pf-cmapi-kind.conf does not say it is lab only and not part of cmapi"

echo "kind import cases failed: $fails"; [ "$fails" = 0 ]
