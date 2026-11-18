#!/usr/bin/env bash
# shellcheck disable=SC2015  # ok and bad here never fail, so A && ok || bad is if-then-else
# deploy/tests/kind-import-test.sh [<deploy dir>]: deploy/kind-import/{up,down}.sh on stubs of kind, kubectl, oc, ifconfig, curl and
# openssl's s_client, for each thing they claim they stop on, and for what they must never do: the token on an argument list or in the
# output, a delete that does not name one object, a write after a moved address. No cluster.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); SRC=$(cd "${1:-$HERE/..}" && pwd); W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fails=0; bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
want() { local label=$1 rc=$2 got=$3; if [ "$got" = "$rc" ]; then ok "$label"; else bad "$label: rc $got, not $rc ($(tail -3 "$W/out" | tr '\n' ' '))"; fi; }
mkdir -p "$W/bin" "$W/repo/deploy"; cp -R "$SRC/kind-import" "$W/repo/deploy/"; D=$W/repo/deploy/kind-import
REAL_OPENSSL=$(command -v openssl)
# A JWT shaped as kubectl create token prints it; every part of it is the secret.
IAT=1794964470; EXP=$((IAT + 604800))
b64url() { python3 -c 'import base64,sys; print(base64.urlsafe_b64encode(sys.stdin.read().encode()).decode().rstrip("="))'; }
TOKEN="$(printf '{"alg":"RS256"}' | b64url).$(printf '{"sub":"system:serviceaccount:cmapi-system:cmapi-reader","iat":%s,"exp":%s}' "$IAT" "$EXP" | b64url).stub-signature-never-to-be-seen"
cert() { "$REAL_OPENSSL" req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/$1.pem" -subj "/CN=kube-apiserver" -days 2 -addext "subjectAltName=$2" 2>/dev/null; }
cert ca "DNS:kubernetes"
cert served "DNS:cmapi-test-control-plane,DNS:host.crc.testing,DNS:localhost,IP:10.96.0.1,IP:192.168.86.110,IP:127.0.0.1"
cert other-ip "DNS:host.crc.testing,IP:192.168.86.111,IP:127.0.0.1"
cert no-crc "DNS:localhost,IP:192.168.86.110,IP:127.0.0.1"
export ARGV_LOG=$W/argv.log TOKEN STUB_CA=$W/ca.pem STUB_SERVED=$W/served.pem REAL_OPENSSL KIND_IMPORT_KUBECONFIG=$W/kc
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
  "create token cmapi-reader -n cmapi-system --duration=168h") [ -n "${STUB_TOKEN_FAIL:-}" ] && { echo "error: serviceaccounts not found" >&2; exit 1; }; printf '%s\n' "$TOKEN"; exit 0;;
esac
echo "stub kubectl: unhandled $s" >&2; exit 3
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
exec "$REAL_OPENSSL" "$@"
S
stub curl <<'S'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >>"$ARGV_LOG"
exit "${STUB_CURL_RC:-0}"
S
export PATH="$W/bin:$PATH"
run() { : >"$ARGV_LOG"; rm -f "$ARGV_LOG.applied"; "$@" >"$W/out" 2>&1; echo $?; }
no_secret() { if grep -qF -e "$TOKEN" -e "stub-signature-never-to-be-seen" "$ARGV_LOG" "$W/out"; then bad "$1: the token is on an argument list or in the output"; else ok "$1: the token is on no argument list and not in the output"; fi; }
wrote_nothing() { if grep -qE '^(oc apply|oc delete|kind create|kind delete|kubectl .*(apply|create token))' "$ARGV_LOG"; then bad "$1: it wrote first: $(grep -E '^(oc apply|oc delete|kind create|kind delete|kubectl )' "$ARGV_LOG" | head -2 | tr '\n' ' ')"; else ok "$1: and wrote nothing"; fi; }
says() { grep -qF -- "$2" "$W/out" && ok "$1: says \"$2\"" || bad "$1: the message does not say \"$2\": $(tr '\n' ' ' <"$W/out")"; }

echo "up.sh"
want "a new cluster" 0 "$(run "$D/up.sh")"; no_secret "a new cluster"
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
want "an existing cluster is reused and its token rewritten" 0 "$(STUB_KIND_CLUSTERS=$'other\ncmapi-test' run "$D/up.sh")"; no_secret "a rerun"
if grep -q '^kind create' "$ARGV_LOG"; then bad "it created again"; else ok "and not created again"; fi
[ -s "$ARGV_LOG.applied" ] && ok "and the Secret written again (the rotation)" || bad "no Secret on a rerun"
want "a moved DHCP lease stops" 1 "$(STUB_ADDR=192.168.86.57 run "$D/up.sh")"; says "a moved lease" "no longer holds 192.168.86.110"; wrote_nothing "a moved lease"
want "a served certificate for another address stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_SERVED=$W/other-ip.pem run "$D/up.sh")"; says "another address" "does not name 192.168.86.110"; wrote_nothing "another address"
want "a served certificate without host.crc.testing stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_SERVED=$W/no-crc.pem run "$D/up.sh")"; wrote_nothing "no host.crc.testing"
want "no API server answering stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_NO_SERVER=1 run "$D/up.sh")"; wrote_nothing "no API server"
want "an oc that is not CRC's stops" 1 "$(STUB_SERVER=https://api.other.example:6443 run "$D/up.sh")"; wrote_nothing "not CRC"
want "a CA that does not verify the API stops" 1 "$(STUB_KIND_CLUSTERS=cmapi-test STUB_CURL_RC=60 run "$D/up.sh")"; wrote_nothing "an unverified API"
want "a failed TokenRequest stops" 1 "$(STUB_TOKEN_FAIL=1 run "$D/up.sh")"
[ -s "$ARGV_LOG.applied" ] && bad "and a Secret was applied without a token" || ok "and no Secret is applied"
want "an argument is refused" 2 "$(run "$D/up.sh" --force)"
# Whole names: on 192.168.86.11 a certificate for 192.168.86.110 must not pass.
cp -R "$D" "$W/k11"; sed -i.bak 's/192\.168\.86\.110/192.168.86.11/g' "$W/k11/kind-cmapi-test.yaml" "$W/k11/pf-cmapi-kind.conf"
want "a certificate for a longer address does not pass" 1 "$(STUB_ADDR=192.168.86.11 STUB_KIND_CLUSTERS=cmapi-test run "$W/k11/up.sh")"; wrote_nothing "a longer address"
cp -R "$D" "$W/kpf"; sed -i.bak 's/192\.168\.86\.110/192.168.86.111/' "$W/kpf/pf-cmapi-kind.conf"
want "a pf anchor for another address stops" 1 "$(run "$W/kpf/up.sh")"; says "the pf anchor" "does not drop"; wrote_nothing "the pf anchor"
cp -R "$D" "$W/ksan"; sed -i.bak 's/certSANs: \[localhost, 127.0.0.1, 192.168.86.110, host.crc.testing\]/certSANs: [localhost, 127.0.0.1, host.crc.testing]/' "$W/ksan/kind-cmapi-test.yaml"
want "certSANs without the address stop" 1 "$(run "$W/ksan/up.sh")"; wrote_nothing "certSANs"

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

echo "kind import cases failed: $fails"; [ "$fails" = 0 ]
