#!/usr/bin/env bash
# deploy/secrets-test.sh <kubectl command>: the cases deploy/secrets.sh must get right, on a throwaway pair of namespaces
# (sect1 as cmapi, sect2 as keycloak) of the cluster the command points at. Prints "rc=N <last line>" per case and fails
# if any case's rc or hash differs from what it must be. Example: deploy/secrets-test.sh "kubectl --kubeconfig=./kc"
set -uo pipefail
KUBECTL=${1:?kubectl command with its --kubeconfig}
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC2086
k() { $KUBECTL "$@"; }
k create ns sect1 >/dev/null 2>&1 || true; k create ns sect2 >/dev/null 2>&1 || true
# The kubectl command carries its --kubeconfig, so it is one argument: an array, never a word-split string (the first
# run of this harness split it and secrets.sh refused "--kubeconfig=..." as an unknown argument).
A=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL" --no-ldap-bind)
B=(--namespace sect1 --realm-namespace sect2 --kubectl "$KUBECTL")
S="$HERE/secrets.sh"
T=$(mktemp); trap 'rm -f "$T"; k delete ns sect1 sect2 --wait=false >/dev/null 2>&1' EXIT
h() { k get secret cmapi-keycloak -n sect1 -o json 2>/dev/null | python3 -c 'import sys,json,hashlib; d=json.load(sys.stdin)["data"]; print(hashlib.sha256(json.dumps(d,sort_keys=True).encode()).hexdigest()[:12])' 2>/dev/null || echo none; }
fails=0
run() { "$S" "${A[@]}" "$@" >"$T" 2>&1; echo "rc=$? $(tail -1 "$T" | cut -c1-140)"; }
runb() { "$S" "${B[@]}" >"$T" 2>&1; echo "rc=$? $(tail -1 "$T" | cut -c1-140)"; }
expect() { # label, expected rc, actual line
  case "$3" in "rc=$2 "*) echo "  ok   $1: $3";; *) echo "  FAIL $1 (expected rc=$2): $3"; fails=$((fails+1));; esac; }
r=$(run); expect "1 fresh" 0 "$r"; H1=$(h)
r=$(run); expect "2 second run" 0 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 2: the hash changed"; fails=$((fails+1)); }
k delete secret cmapi-keycloak -n sect1 >/dev/null
r=$(run); expect "3 ours deleted, copied from the realm" 0 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 3: the hash changed"; fails=$((fails+1)); }
k patch secret cmapi-realm-secrets -n sect2 --type=json -p '[{"op":"remove","path":"/data/CMAPI_DIRECTORY_SECRET"}]' >/dev/null
r=$(run); expect "4 partial realm copy stops" 1 "$r"; [ "$(h)" = "$H1" ] || { echo "  FAIL 4: ours changed"; fails=$((fails+1)); }
k delete secret cmapi-keycloak -n sect1 >/dev/null
r=$(run); expect "5 partial realm copy, ours gone, stops" 1 "$r"; [ "$(h)" = none ] || { echo "  FAIL 5: something was written"; fails=$((fails+1)); }
k delete secret cmapi-realm-secrets -n sect2 >/dev/null
r=$(run); expect "6 all gone, no realm import: generates" 0 "$r"; [ "$(h)" != "$H1" ] && [ "$(h)" != none ] || { echo "  FAIL 6"; fails=$((fails+1)); }
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
k delete keycloakrealmimport cmapi -n sect2 >/dev/null; [ "${CRD_STAND_IN:-}" = true ] && k delete crd keycloakrealmimports.k8s.keycloak.org >/dev/null
# 9: cmapi-ldap-bind is checked, never written
r=$(runb); expect "9a ldap-bind missing stops" 1 "$r"
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
k delete secret cmapi-github-app -n sect1 >/dev/null; chmod 644 "$KEYF"
r=$(run --github-app-key "$KEYF" --github-app-id 1 --github-installation-id 2); expect "10c a key file that others can read is refused" 2 "$r"
rm -f "$KEYF"
# nothing secret may have reached the output
grep -c "eHh4\|MQ==" "$T" >/dev/null 2>&1 && { echo "  FAIL: a value reached the output"; fails=$((fails+1)); }
echo "secrets cases failed: $fails"; [ "$fails" = 0 ]
