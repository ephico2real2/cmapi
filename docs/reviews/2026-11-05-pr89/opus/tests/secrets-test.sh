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
A=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind)
B=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL")
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
# A kubectl that answers a 500 on the reads named in FAIL_READS ("get secret cmapi-keys|get keycloakrealmimport") and passes the rest.
cat >"$W/kubectl-failing" <<WRAP
#!/usr/bin/env bash
for pat in \$(printf '%s' "\${FAIL_READS:-}" | tr ' ' '_' | tr '|' ' '); do
  case "\$(printf '%s' "\$*" | tr ' ' '_')" in "\$pat"_*|"\$pat") echo 'Error from server (InternalError): an error on the server' >&2; exit 1;; esac
done
exec $KUBECTL "\$@"
WRAP
chmod +x "$W/kubectl-failing"
runf() { # the reads named in $1 fail; the writes still work
  local reads=$1; shift
  FAIL_READS="$reads" "$S" --namespace sect1 --realm-namespace sect2 --kubectl "$W/kubectl-failing" --no-ldap-bind "$@" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
h() { k get secret cmapi-keycloak -n sect1 -o json 2>/dev/null | python3 -c 'import sys,json,hashlib; d=json.load(sys.stdin)["data"]; print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:12])' 2>/dev/null || echo none; }
fails=0
run() { "$S" "${A[@]}" "$@" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
runb() { "$S" "${B[@]}" >"$T" 2>&1; local rc=$?; cat "$T" >>"$ALL"; echo "rc=$rc $(tail -1 "$T" | cut -c1-140)"; }
same() { # label, expected, actual
  [ "$2" = "$3" ] || { echo "  FAIL $1: expected $2, got $3"; fails=$((fails+1)); }; }
expect() { # label, expected rc, actual line
  case "$3" in "rc=$2 "*) echo "  ok   $1: $3";; *) echo "  FAIL $1 (expected rc=$2): $3"; fails=$((fails+1));; esac; }
r=$(run); expect "1 fresh" 0 "$r"; H1=$(h); R1=$(hs sect2 cmapi-realm-secrets); K1=$(hs sect1 cmapi-keys); collect
r=$(run); expect "2 second run" 0 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2: the hash changed"; fails=$((fails+1)); }
same "2 the realm copy" "$R1" "$(hs sect2 cmapi-realm-secrets)"; same "2 cmapi-keys is written once" "$K1" "$(hs sect1 cmapi-keys)"
# The four client secrets are four values, each 48 characters.
k get secret cmapi-keycloak -n sect1 -o json | python3 -c 'import base64,json,sys; d=json.load(sys.stdin)["data"]; v=[base64.b64decode(x) for x in d.values()]; sys.exit(0 if len(set(v))==4 and all(len(x)==48 for x in v) else 1)' || { echo "  FAIL 2: the four client secrets are not four 48-character values"; fails=$((fails+1)); }
# A read that errors is not an absent Secret: each of these minted or replaced before the fix.
r=$(runf "get secret cmapi-keys"); expect "2a a failed read of cmapi-keys stops" 1 "$r"; same "2a cmapi-keys" "$K1" "$(hs sect1 cmapi-keys)"
r=$(runf "get secret cmapi-keycloak|get secret cmapi-realm-secrets|get keycloakrealmimport"); expect "2b failed reads of the realm's Secrets stop" 1 "$r"
same "2b the realm copy" "$R1" "$(hs sect2 cmapi-realm-secrets)"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2b: ours changed"; fails=$((fails+1)); }
# from-ours: the realm's copy gone, ours complete: copied back, equal.
k delete secret cmapi-realm-secrets -n sect2 >/dev/null
r=$(run); expect "2c realm copy deleted, copied from ours" 0 "$r"; same "2c the realm copy is ours" "$R1" "$(hs sect2 cmapi-realm-secrets)"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2c: ours changed"; fails=$((fails+1)); }
# A partial copy of ours stops and changes nothing.
k patch secret cmapi-keycloak -n sect1 --type=json -p '[{"op":"remove","path":"/data/directoryClientSecret"}]' >/dev/null; H2=$(h)
r=$(run); expect "2d partial namespace copy stops" 1 "$r"; same "2d ours untouched" "$H2" "$(h)"; same "2d the realm copy" "$R1" "$(hs sect2 cmapi-realm-secrets)"
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
r=$(run); expect "6 all gone, no realm import: generates" 0 "$r"; if [ "$(h)" = "$H1" ] || [ "$(h)" = none ]; then echo "  FAIL 6"; fails=$((fails+1)); fi; collect
k patch secret cmapi-keycloak -n sect1 --type=merge -p '{"data":{"automationClientSecret":"eHh4"}}' >/dev/null
r=$(run); expect "7 copies differ, stops" 1 "$r"
k delete secret cmapi-keycloak cmapi-keys -n sect1 >/dev/null; k delete secret cmapi-realm-secrets -n sect2 >/dev/null
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
rm -f "$KEYF"
# Nothing secret may have reached the output of any case: every value the cases generated, encoded and decoded, against
# everything every run printed. The count alone is printed, never a match.
[ -s "$VALUES" ] || { echo "  FAIL: the scan collected no values"; fails=$((fails+1)); }
leaked=$(grep -cFf "$VALUES" "$ALL"); [ "${leaked:-0}" = 0 ] || { echo "  FAIL: $leaked lines of output hold a Secret value"; fails=$((fails+1)); }
echo "secrets cases failed: $fails"; [ "$fails" = 0 ]
