#!/usr/bin/env bash
# deploy/secrets-test.sh <kubectl command>: the cases deploy/secrets.sh must get right, on a throwaway pair of namespaces
# (sect1 as cmapi, sect2 as keycloak) of the cluster the command points at. Prints "rc=N <last line>" per case and fails
# if any case's rc or hash differs from what it must be. Example: deploy/secrets-test.sh "kubectl --kubeconfig=./kc"
set -uo pipefail
KUBECTL=${1:?kubectl command with its --kubeconfig}
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC2086
k() { $KUBECTL "$@"; }
# The cases create and delete namespaces and may add a CRD: never on a shared cluster, whichever context the command carries.
case "$(k config current-context 2>/dev/null)" in kind-*) ;; *) echo "ERROR: $KUBECTL does not point at a kind cluster; these cases only run on a throwaway one" >&2; exit 2;; esac
k create ns sect1 >/dev/null 2>&1 || true; k create ns sect2 >/dev/null 2>&1 || true
# The kubectl command carries its --kubeconfig, so it is one argument: an array, never a word-split string (the first
# run of this harness split it and secrets.sh refused "--kubeconfig=..." as an unknown argument).
A=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind --no-issuer-check)
B=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-issuer-check)
S="$HERE/secrets.sh"
T=$(mktemp); ALL=$(mktemp); VALUES=$(mktemp); W=$(mktemp -d)
trap 'rm -rf "$T" "$ALL" "$VALUES" "$W"; k delete ns sect1 sect2 --wait=false >/dev/null 2>&1' EXIT
# hs NS NAME: a short hash of a Secret's data, "none" when absent.
hs() { k get secret "$2" -n "$1" -o json 2>/dev/null | python3 -c 'import sys,json,hashlib; d=json.load(sys.stdin)["data"]; print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:12])' 2>/dev/null || echo none; }
# collect: every value in the Secrets of the two namespaces, encoded and decoded, kept (never printed) for the scan at the end.
collect() { for n in sect1 sect2; do k get secret -n "$n" -o json 2>/dev/null; done | python3 -c '
import base64,json,sys
dec=json.JSONDecoder(); s=sys.stdin.read(); i=0
while i<len(s):
    if s[i].isspace(): i+=1; continue
    o,i=dec.raw_decode(s,i)
    for it in o.get("items",[]):
        if it["metadata"]["name"].startswith("cmapi-") and it["metadata"]["name"]!="cmapi-ldap-bind":
            for v in (it.get("data") or {}).values():
                print(v); print(base64.b64decode(v).decode("utf-8","replace").split("\n")[0])
' | awk 'length($0)>=12' >>"$VALUES"; }
# A kubectl that answers a 500 on the reads named in FAIL_READS ("get secret cmapi-keys|get keycloakrealmimport") and on the
# write of the Secret named in FAIL_WRITE, answers "absent" on the reads in STALE_READS, and passes the rest.
cat >"$W/kubectl-failing" <<WRAP
#!/usr/bin/env bash
for pat in \$(printf '%s' "\${FAIL_READS:-}" | tr ' ' '_' | tr '|' ' '); do
  case "\$(printf '%s' "\$*" | tr ' ' '_')" in "\$pat"_*|"\$pat") echo 'Error from server (InternalError): an error on the server' >&2; exit 1;; esac
done
for pat in \$(printf '%s' "\${STALE_READS:-}" | tr ' ' '_' | tr '|' ' '); do
  case "\$(printf '%s' "\$*" | tr ' ' '_')" in "\$pat"_*|"\$pat") exit 0;; esac
done
if [ -n "\${FAIL_WRITE:-}" ] && [ "\$1" = create ] && [ "\$2" = -f ]; then
  doc=\$(cat)
  case "\$doc" in *"name: \$FAIL_WRITE,"*) echo 'Error from server (InternalError): the write failed' >&2; exit 1;; esac
  printf '%s\n' "\$doc" | $KUBECTL "\$@"; exit \$?
fi
exec $KUBECTL "\$@"
WRAP
chmod +x "$W/kubectl-failing"
runf() { # the reads named in $1 fail; the writes still work
  local reads=$1; shift
  FAIL_READS="$reads" "$S" --namespace sect1 --realm-namespace sect2 --kubectl "$W/kubectl-failing" --no-ldap-bind --no-issuer-check "$@" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
h() { k get secret cmapi-keycloak -n sect1 -o json 2>/dev/null | python3 -c 'import sys,json,hashlib; d=json.load(sys.stdin)["data"]; print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:12])' 2>/dev/null || echo none; }
fails=0
run() { "$S" "${A[@]}" "$@" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
runb() { "$S" "${B[@]}" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
same() { # label, expected, actual
  [ "$2" = "$3" ] || { echo "  FAIL $1: expected $2, got $3"; fails=$((fails+1)); }; }
said() { # label, text the last run must have printed. The rc alone cannot tell which guard stopped it.
  grep -qF -- "$2" "$T" || { echo "  FAIL $1: the output does not say: $2"; fails=$((fails+1)); }; }
expect() { # label, expected rc, actual line
  case "$3" in "rc=$2 "*) echo "  ok   $1: $3";; *) echo "  FAIL $1 (expected rc=$2): $3"; fails=$((fails+1));; esac; }
# 0: every check that can stop a run comes before the first write, so a stop leaves nothing half done: the existing Secrets of a
# late check, a late read, the bind user and the key file, each on an otherwise fresh install.
none_written() { same "$1 no realm Secret was written" none "$(hs sect2 cmapi-realm-secrets)"; same "$1 no client Secret was written" none "$(h)"; same "$1 no keys Secret was written" none "$(hs sect1 cmapi-keys)"; }
k create secret generic cmapi-github-app -n sect1 >/dev/null
r=$(run); expect "0a an empty app Secret stops" 1 "$r"; none_written 0a
k delete secret cmapi-github-app -n sect1 >/dev/null
r=$(runf "get secret cmapi-github-app"); expect "0b a failed late read stops" 1 "$r"; none_written 0b; said "0b it stops at the read" "an error on the server"
k create secret generic cmapi-keys -n sect1 >/dev/null
r=$(run); expect "0c an empty cmapi-keys stops" 1 "$r"; same "0c no realm Secret was written" none "$(hs sect2 cmapi-realm-secrets)"; same "0c no client Secret was written" none "$(h)"
k delete secret cmapi-keys -n sect1 >/dev/null
r=$(runb); expect "0d a missing cmapi-ldap-bind stops" 1 "$r"; none_written 0d
printf 'not a key\n' >"$W/key0"; chmod 644 "$W/key0"
r=$(run --github-app-key "$W/key0" --github-app-id 1 --github-installation-id 2); expect "0e a key file others can read stops" 2 "$r"; none_written 0e
chmod 600 "$W/key0"
r=$(run --github-app-key "$W/key0"); expect "0f a key file with no ids stops" 2 "$r"; none_written 0f
r=$(run); expect "1 fresh" 0 "$r"; H1=$(h); R1=$(hs sect2 cmapi-realm-secrets); K1=$(hs sect1 cmapi-keys); collect
r=$(run); expect "2 second run" 0 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2: the hash changed"; fails=$((fails+1)); }
same "2 the realm copy" "$R1" "$(hs sect2 cmapi-realm-secrets)"; same "2 cmapi-keys is written once" "$K1" "$(hs sect1 cmapi-keys)"
# The four client secrets are four values, each 48 characters.
k get secret cmapi-keycloak -n sect1 -o json | python3 -c 'import base64,json,sys; d=json.load(sys.stdin)["data"]; v=[base64.b64decode(x) for x in d.values()]; sys.exit(0 if len(set(v))==4 and all(len(x)==48 for x in v) else 1)' || { echo "  FAIL 2: the four client secrets are not four 48-character values"; fails=$((fails+1)); }
# A read that errors is not an absent Secret: each of these minted or replaced before the fix.
r=$(runf "get secret cmapi-keys"); expect "2a a failed read of cmapi-keys stops" 1 "$r"; same "2a cmapi-keys" "$K1" "$(hs sect1 cmapi-keys)"
said "2a it stops at the read, not at the write" "an error on the server"
# A Secret that appeared after the read (a second run, a person) stops the write: it is created, never applied over.
r=$(STALE_READS="get secret cmapi-keys" runf ""); expect "2g a read that is already stale stops at the write" 1 "$r"; same "2g cmapi-keys is not overwritten" "$K1" "$(hs sect1 cmapi-keys)"
r=$(runf "get secret cmapi-keycloak|get secret cmapi-realm-secrets|get keycloakrealmimport"); expect "2b failed reads of the realm's Secrets stop" 1 "$r"
same "2b the realm copy" "$R1" "$(hs sect2 cmapi-realm-secrets)"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2b: ours changed"; fails=$((fails+1)); }
# from-ours: the realm's copy gone, ours complete: copied back, equal.
k delete secret cmapi-realm-secrets -n sect2 >/dev/null
r=$(run); expect "2c realm copy deleted, copied from ours" 0 "$r"; same "2c the realm copy is ours" "$R1" "$(hs sect2 cmapi-realm-secrets)"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2c: ours changed"; fails=$((fails+1)); }
# A partial copy of ours stops and changes nothing.
k patch secret cmapi-keycloak -n sect1 --type=json -p '[{"op":"remove","path":"/data/directoryClientSecret"}]' >/dev/null; H2=$(h)
r=$(run); expect "2d partial namespace copy stops" 1 "$r"; same "2d ours untouched" "$H2" "$(h)"; same "2d the realm copy" "$R1" "$(hs sect2 cmapi-realm-secrets)"
said "2d it names the partial copy" "ERROR: partial namespace copy, missing directoryClientSecret"
k delete secret cmapi-keycloak -n sect1 >/dev/null; r=$(run); expect "2e ours restored from the realm" 0 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2e: the hash changed"; fails=$((fails+1)); }
# A partial cmapi-keys stops; it is never filled in or replaced.
k patch secret cmapi-keys -n sect1 --type=json -p '[{"op":"remove","path":"/data/cursorKey"}]' >/dev/null; K2=$(hs sect1 cmapi-keys)
r=$(run); expect "2f partial cmapi-keys stops" 1 "$r"; same "2f not filled in" "$K2" "$(hs sect1 cmapi-keys)"; k delete secret cmapi-keys -n sect1 >/dev/null
k delete secret cmapi-keycloak -n sect1 >/dev/null
r=$(run); expect "3 ours deleted, copied from the realm" 0 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 3: the hash changed"; fails=$((fails+1)); }
k patch secret cmapi-realm-secrets -n sect2 --type=json -p '[{"op":"remove","path":"/data/CMAPI_DIRECTORY_SECRET"}]' >/dev/null
r=$(run); expect "4 partial realm copy stops" 1 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 4: ours changed"; fails=$((fails+1)); }
k delete secret cmapi-keycloak -n sect1 >/dev/null
r=$(run); expect "5 partial realm copy, ours gone, stops" 1 "$r"; [ "$(h)" = none ] || { echo "  FAIL 5: something was written"; fails=$((fails+1)); }
k delete secret cmapi-realm-secrets -n sect2 >/dev/null
# The realm's copy is written first: a failure between the two writes leaves the authority, and the next run heals ours from it.
r=$(FAIL_WRITE=cmapi-keycloak runf ""); expect "5a the second write fails" 1 "$r"; same "5a ours is not written" none "$(h)"; R5=$(hs sect2 cmapi-realm-secrets)
[ "$R5" != none ] || { echo "  FAIL 5a: the realm's copy was not written first"; fails=$((fails+1)); }
r=$(run); expect "5b the next run copies the realm's" 0 "$r"; same "5b the realm copy is kept" "$R5" "$(hs sect2 cmapi-realm-secrets)"; [ "$(h)" != none ] || { echo "  FAIL 5b: ours was not written"; fails=$((fails+1)); }; collect
k delete secret cmapi-keycloak -n sect1 >/dev/null; k delete secret cmapi-realm-secrets -n sect2 >/dev/null
r=$(run); expect "6 all gone, no realm import: generates" 0 "$r"; if [ "$(h)" = "$H1" ] || [ "$(h)" = none ]; then echo "  FAIL 6"; fails=$((fails+1)); fi; collect
k patch secret cmapi-keycloak -n sect1 --type=merge -p '{"data":{"automationClientSecret":"eHh4"}}' >/dev/null
r=$(run); expect "7 copies differ, stops" 1 "$r"
k delete secret cmapi-keycloak cmapi-keys -n sect1 >/dev/null; k delete secret cmapi-realm-secrets -n sect2 >/dev/null
# 7a, 7b: a Secret that exists with no data is a partial copy, not an absent one. The realm's empty copy once meant "generate".
k create secret generic cmapi-realm-secrets -n sect2 >/dev/null
r=$(run); expect "7a an empty realm copy stops" 1 "$r"; said "7a it names the partial copy" "ERROR: partial realm copy"; same "7a ours is not written" none "$(h)"; same "7a cmapi-keys is not written" none "$(hs sect1 cmapi-keys)"
k delete secret cmapi-realm-secrets -n sect2 >/dev/null; k create secret generic cmapi-keycloak -n sect1 >/dev/null
r=$(run); expect "7b an empty namespace copy stops" 1 "$r"; said "7b it names the partial copy" "ERROR: partial namespace copy"; same "7b the realm's copy is not written" none "$(hs sect2 cmapi-realm-secrets)"; same "7b cmapi-keys is not written" none "$(hs sect1 cmapi-keys)"
k delete secret cmapi-keycloak -n sect1 >/dev/null
# 8: a realm import exists and both copies are gone. The CRD may be absent on this cluster: a stand-in CRD stands for it.
if ! k get crd keycloakrealmimports.k8s.keycloak.org >/dev/null 2>&1; then
  k apply -f - >/dev/null <<'CRD'
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: {name: keycloakrealmimports.k8s.keycloak.org, labels: {cmapi.net/test-stand-in: "true"}}
spec:
  group: k8s.keycloak.org
  names: {kind: KeycloakRealmImport, plural: keycloakrealmimports, singular: keycloakrealmimport}
  scope: Namespaced
  versions: [{name: v2beta1, served: true, storage: true, schema: {openAPIV3Schema: {type: object, x-kubernetes-preserve-unknown-fields: true}}}]
CRD
  sleep 3; CRD_STAND_IN=true
fi
k apply -f - >/dev/null <<'CR'
apiVersion: k8s.keycloak.org/v2beta1
kind: KeycloakRealmImport
metadata: {name: cmapi, namespace: sect2}
spec: {keycloakCRName: keycloak, realm: {realm: cmapi}}
CR
r=$(run); expect "8 realm import exists, both copies gone: stops" 1 "$r"; [ "$(h)" = none ] || { echo "  FAIL 8: something was written"; fails=$((fails+1)); }
same "8 the realm's copy was not written" none "$(hs sect2 cmapi-realm-secrets)"
r=$(runf "get keycloakrealmimport"); expect "8a a failed read of the import stops, it is not 'no import'" 1 "$r"; [ "$(h)" = none ] || { echo "  FAIL 8a: something was written"; fails=$((fails+1)); }
same "8a the realm's copy was not written" none "$(hs sect2 cmapi-realm-secrets)"
k delete keycloakrealmimport cmapi -n sect2 >/dev/null; [ "${CRD_STAND_IN:-}" = true ] && k delete crd keycloakrealmimports.k8s.keycloak.org >/dev/null
# 9: cmapi-ldap-bind is checked, never written
r=$(runb); expect "9a ldap-bind missing stops" 1 "$r"
same "9a never generated, ours" none "$(hs sect1 cmapi-ldap-bind)"; same "9a never generated, the realm's" none "$(hs sect2 cmapi-ldap-bind)"
k create secret generic cmapi-ldap-bind -n sect1 --from-literal=bindDN=cn=x --from-literal=password=p >/dev/null
k create secret generic cmapi-ldap-bind -n sect2 --from-literal=bindDN=cn=x >/dev/null
r=$(runb); expect "9b ldap-bind lacking a key stops" 1 "$r"
k delete secret cmapi-ldap-bind -n sect2 >/dev/null; k create secret generic cmapi-ldap-bind -n sect2 --from-literal=bindDN=cn=x --from-literal=password=other >/dev/null
r=$(runb); expect "9c ldap-bind copies differ stops" 1 "$r"
k delete secret cmapi-ldap-bind -n sect2 >/dev/null; k create secret generic cmapi-ldap-bind -n sect2 --from-literal=bindDN=cn=x --from-literal=password=p >/dev/null
r=$(runb); expect "9d ldap-bind equal passes" 0 "$r"
# 10: the GitHub App Secret is validated and never replaced
KEYF=$(mktemp); printf -- '-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----\n' >"$KEYF"; chmod 600 "$KEYF"
r=$(run --github-app-key "$KEYF" --github-app-id 1 --github-installation-id 2); expect "10a app secret written from a 0600 file" 0 "$r"
k get secret cmapi-github-app -n sect1 -o jsonpath='{.data.appId}' | grep -q MQ== || { echo "  FAIL 10a: appId not written"; fails=$((fails+1)); }
k patch secret cmapi-github-app -n sect1 --type=json -p '[{"op":"remove","path":"/data/privateKey"}]' >/dev/null
r=$(run --github-app-key "$KEYF" --github-app-id 1 --github-installation-id 2); expect "10b existing app secret lacking a key stops, not replaced" 1 "$r"
k get secret cmapi-github-app -n sect1 -o jsonpath='{.data.appId}' | grep -q MQ== || { echo "  FAIL 10b: the Secret was replaced"; fails=$((fails+1)); }
k delete secret cmapi-github-app -n sect1 >/dev/null
r=$(run --github-app-key "$KEYF" --github-app-id 1 --github-installation-id 2); G1=$(hs sect1 cmapi-github-app); collect
r=$(run --github-app-key "$KEYF" --github-app-id 777 --github-installation-id 888); expect "10d a complete app secret with other arguments is kept" 0 "$r"; same "10d not replaced" "$G1" "$(hs sect1 cmapi-github-app)"
r=$(runf "get secret cmapi-github-app" --github-app-key "$KEYF" --github-app-id 777 --github-installation-id 888); expect "10e a failed read of the app secret stops" 1 "$r"; same "10e not replaced" "$G1" "$(hs sect1 cmapi-github-app)"
k delete secret cmapi-github-app -n sect1 >/dev/null; chmod 644 "$KEYF"
r=$(run --github-app-key "$KEYF" --github-app-id 1 --github-installation-id 2); expect "10c a key file that others can read is refused" 2 "$r"
# One line naming the mode: GNU stat -f once put the file system's details in the message (#90), and the rc alone cannot see it.
grep -qxF "ERROR: $KEYF is mode 644; make it 0600" "$T" || { echo "  FAIL 10c: the ERROR line is not the mode alone"; fails=$((fails+1)); }
rm -f "$KEYF"
# 11: ruling 7, the realm asked before anything is minted. A curl stub answers what ISSUER_CODE and ISSUER_BODY say; ISSUER_RC is curl's own failure.
mkdir -p "$W/bin"; cat >"$W/bin/curl" <<'CURL'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$CURL_LOG"
[ "${ISSUER_RC:-0}" = 0 ] || exit "$ISSUER_RC"
out=; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
printf '%s' "$ISSUER_BODY" >"$out"; printf '%s' "$ISSUER_CODE"
CURL
chmod +x "$W/bin/curl"; export CURL_LOG="$W/curl.log"; : >"$CURL_LOG"
printf 'not a real CA\n' >"$W/ca.pem"
I=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind --issuer https://kc.test/realms/cmapi --ca-file "$W/ca.pem")
runi() { PATH="$W/bin:$PATH" ISSUER_CODE=$1 ISSUER_BODY=$2 ISSUER_RC=${3:-0} "$S" "${I[@]}" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
k delete secret cmapi-keycloak cmapi-keys -n sect1 >/dev/null 2>&1; k delete secret cmapi-realm-secrets -n sect2 >/dev/null 2>&1
r=$("$S" --namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind >"$T" 2>&1; echo "rc=$? $(tail -1 "$T")"); expect "11a neither --issuer nor --no-issuer-check stops" 2 "$r"; none_written 11a
r=$(runi 200 '{"realm":"cmapi","public_key":"x"}'); expect "11b the realm exists, both Secrets gone: stops" 1 "$r"; said "11b it says so" "exists at"; none_written 11b
r=$(runi 503 '<html>Application is not available</html>'); expect "11c a router's 503 during a restart is not absent" 1 "$r"; said "11c it cannot tell" "cannot tell"; none_written 11c
r=$(runi 404 '<html>not found</html>'); expect "11d a 404 that is not Keycloak's is not absent" 1 "$r"; said "11d it cannot tell" "cannot tell"; none_written 11d
r=$(runi 200 '{"realm":"corp"}'); expect "11e a 200 for another realm is not this realm, and not absent" 1 "$r"; none_written 11e
r=$(runi 000 '' 28); expect "11f a timeout is not absent" 1 "$r"; said "11f it cannot tell" "cannot tell"; none_written 11f
r=$(runi 000 '' 60); expect "11g a certificate failure is not absent" 1 "$r"; none_written 11g
grep -q -- '--cacert' "$CURL_LOG" || { echo "  FAIL 11: the CA file was not used"; fails=$((fails+1)); }
if grep -qE -- '(^| )(-k|--insecure)( |$)' "$CURL_LOG"; then echo "  FAIL 11: TLS verification was turned off"; fails=$((fails+1)); fi
# Keycloak's own 404 is what a request for any other realm gets too, so the URL itself has to name this realm. The curl stub would say "absent" to each.
for bad in https://kc.test/realms/not-cmapi https://kc.test/realms/cmapi/ 'https://kc.test/realms/not-cmapi?x=/realms/cmapi' 'https://kc.test/realms/not-cmapi#/realms/cmapi' http://kc.test/realms/cmapi https://kc.test/x/realms/cmapi; do
  : >"$CURL_LOG"; r=$(PATH="$W/bin:$PATH" ISSUER_CODE=404 ISSUER_BODY='{"error":"Realm does not exist"}' "$S" --namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind --issuer "$bad" --ca-file "$W/ca.pem" >"$T" 2>&1; echo "rc=$? $(tail -1 "$T" | cut -c1-140)")
  expect "11j --issuer $bad stops" 2 "$r"; none_written "11j $bad"; [ ! -s "$CURL_LOG" ] || { echo "  FAIL 11j: it asked $bad"; fails=$((fails+1)); }
done
r=$(runi 404 '{"error":"Realm does not exist"}'); expect "11h Keycloak's own 404: generates" 0 "$r"; [ "$(h)" != none ] || { echo "  FAIL 11h: nothing written"; fails=$((fails+1)); }
: >"$CURL_LOG"; r=$(runi 503 'down'); expect "11i Secrets present: nothing to mint, Keycloak not needed" 0 "$r"; [ ! -s "$CURL_LOG" ] || { echo "  FAIL 11i: asked the issuer when nothing was to be minted"; fails=$((fails+1)); }
collect
# 12: the test users are written once and kept.
r=$(run --test-users); expect "12a test users written" 0 "$r"; U1=$(hs sect1 cmapi-test-users); [ "$U1" != none ] || { echo "  FAIL 12a"; fails=$((fails+1)); }; collect
r=$(run --test-users); expect "12b test users kept" 0 "$r"; same "12b not rotated" "$U1" "$(hs sect1 cmapi-test-users)"
k delete secret cmapi-keycloak cmapi-keys cmapi-test-users -n sect1 >/dev/null 2>&1; k delete secret cmapi-realm-secrets -n sect2 >/dev/null 2>&1
# Nothing secret may have reached the output of any case: every value the cases generated, encoded and decoded, against
# everything every run printed. The count alone is printed, never a match.
[ -s "$VALUES" ] || { echo "  FAIL: the scan collected no values"; fails=$((fails+1)); }
leaked=$(grep -cFf "$VALUES" "$ALL"); [ "${leaked:-0}" = 0 ] || { echo "  FAIL: $leaked lines of output hold a Secret value"; fails=$((fails+1)); }
echo "secrets cases failed: $fails"; [ "$fails" = 0 ]
