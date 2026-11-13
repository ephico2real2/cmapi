#!/usr/bin/env bash
# deploy/crc-rollback.sh --yes [--delete-realm --owner-approved]: returns CRC to the state before Wave 1, as far as cmapi can. Every delete names one object: no --all, no selector, no --prune, no -f on a directory.
# Stays: namespace cmapi, its generated Secrets and cmapi-ldap-bind (before Wave 1), the same Secret in keycloak, every LDAP entry this run did not add, every other project's object. The old cmapi-* groups are not restored.
# Stays by design: realm cmapi and Secret keycloak/cmapi-realm-secrets, the authority for the realm's client secrets (deploy/secrets.sh) while the realm exists. Deleting the import does not delete a realm.
# --delete-realm --owner-approved removes the realm too, with the realm's own cmapi-realm-admin service client, no master credential (measured on Keycloak 26.6.4: 204, the other realms' keys unchanged, and 403 on another realm).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OC=${CMAPI_OC:-oc}
KC=${CMAPI_KEYCLOAK_URL:-https://keycloak.apps-crc.testing}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
YES=false; REALM=false; APPROVED=false
for a in "$@"; do case "$a" in --yes) YES=true;; --delete-realm) REALM=true;; --owner-approved) APPROVED=true;; *) echo "unknown argument $a" >&2; exit 2;; esac; done
[ "$YES" = true ] || { sed -n '2,5p' "$0"; echo "nothing done: pass --yes"; exit 2; }
if [ "$REALM" = true ] && [ "$APPROVED" != true ]; then echo "ERROR: --delete-realm needs --owner-approved" >&2; exit 2; fi
del() { echo "delete $*"; oc_ delete "$@" --ignore-not-found; }

if [ "$REALM" = true ]; then
  # First, while its secret exists. Only this realm's name is ever in the URL.
  CA=${CMAPI_CRC_CA:?the bundle from deploy/crc-trust.sh --mac-ca}
  secret=$(oc_ get secret cmapi-keycloak -n cmapi -o 'jsonpath={.data.realmAdminClientSecret}' | base64 -d)
  [ -n "$secret" ] || { echo "ERROR: no realmAdminClientSecret; the realm stays" >&2; exit 1; }
  token=$(printf 'grant_type=client_credentials&client_id=cmapi-realm-admin&client_secret=%s' "$secret" | curl -sS -m 15 --cacert "$CA" -X POST --data @- "$KC/realms/cmapi/protocol/openid-connect/token" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])') || { echo "ERROR: cmapi-realm-admin cannot sign in; the realm stays, and no other credential is used" >&2; exit 1; }
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$token" | curl -sS -m 30 --cacert "$CA" --config - -o /dev/null -w '%{http_code}' -X DELETE "$KC/admin/realms/cmapi")
  [ "$code" = 204 ] || { echo "ERROR: deleting realm cmapi answered $code; it stays" >&2; exit 1; }
  echo "realm cmapi deleted"
  del secret cmapi-realm-secrets -n keycloak
fi
del keycloakrealmimport cmapi -n keycloak
del job cmapi-realm-sync -n cmapi
del deployment cmapi-api -n cmapi
del deployment cmapi-worker -n cmapi
del deployment cmapi-mockup -n cmapi
# The database: read the PV's name first. The storage class is Retain, so deleting the claim leaves the PV Released, holding the data.
pv=$(oc_ get pvc cmapi-db-1 -n cmapi --ignore-not-found -o 'jsonpath={.spec.volumeName}')
del cluster.postgresql.cnpg.io cmapi-db -n cmapi
oc_ delete pvc cmapi-db-1 -n cmapi --ignore-not-found --wait=true --timeout=120s >/dev/null
if [ -n "$pv" ]; then
  # Only a PV whose claim was this one, and only once it is Released.
  who=$(oc_ get pv "$pv" -o 'jsonpath={.spec.claimRef.namespace}/{.spec.claimRef.name}/{.status.phase}')
  case "$who" in cmapi/cmapi-db-1/Released) del pv "$pv"; echo "note    : the PV's directory stays on the node's disk: the provisioner does not remove data under Retain, and cmapi does not write to the node";;
    *) echo "note    : PV $pv left alone: $who";; esac
fi
for o in "service cmapi-api" "service cmapi-worker" "service cmapi-mockup" "networkpolicy cmapi-metrics" "route.route.openshift.io cmapi-api" "route.route.openshift.io cmapi-mockup" \
         "servicemonitor.monitoring.coreos.com cmapi-api" "servicemonitor.monitoring.coreos.com cmapi-worker" "prometheusrule.monitoring.coreos.com cmapi" \
         "configmap cmapi-env" "configmap cmapi-config" "configmap cmapi-trust" "configmap cmapi-mockup" \
         "secret cmapi-keys" "secret cmapi-keycloak" "secret cmapi-test-users" "serviceaccount cmapi-api" "serviceaccount cmapi-worker" "serviceaccount cmapi-jobs" "imagestream.image.openshift.io cmapi"; do
  # shellcheck disable=SC2086  # "kind name"
  del $o -n cmapi
done
del namespace cmapi-np-probe
del namespace cmapi-imports
del namespace cmapi-system
del clusterrolebinding cmapi-reader
del clusterrole cmapi-reader
# The test users, the new groups and Secret cmapi-ldap-test-users, each by exact name. It fails if the rest of the directory moved.
"$HERE/../examples/cmapi-sso/ldap/apply-test-identities.sh" --remove-test-identities
oc_ label namespace cmapi app.kubernetes.io/part-of- >/dev/null 2>&1 || true
echo "rollback done. Left behind, each on purpose: see docs/13, Rollback"
