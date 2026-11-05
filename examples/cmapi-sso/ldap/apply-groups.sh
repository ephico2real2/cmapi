#!/bin/sh
# Adds the cmapi-* groups to the existing LDAP server in namespace ldap-testing, and changes nothing else.
# Safe to run again: a group that already exists is left as it is. Uses the admin password already in the
# server's own environment, so it never leaves the pod or reaches this shell.
set -eu

here=$(dirname "$0")
ns=${LDAP_NAMESPACE:-ldap-testing}
pod=$(oc get pods -n "$ns" --no-headers | awk '/^openldap-server/ && /Running/ {print $1; exit}')
[ -n "$pod" ] || { echo "no running openldap-server pod in $ns" >&2; exit 1; }

# -c carries on past a group that exists. 68 is LDAP's "already exists", and the listing below is the real check.
oc exec -i -n "$ns" -c openldap "$pod" -- sh -c '
  ldapadd -c -x -H ldap://localhost -D "cn=admin,$LDAP_BASE_DN" -w "$LDAP_ADMIN_PASSWORD"
  rc=$?; [ "$rc" -eq 0 ] || [ "$rc" -eq 68 ]' < "$here/cmapi-groups.ldif"

oc exec -n "$ns" -c openldap "$pod" -- sh -c '
  ldapsearch -x -LLL -H ldap://localhost -D "cn=admin,$LDAP_BASE_DN" -w "$LDAP_ADMIN_PASSWORD" \
    -b "ou=Groups,$LDAP_BASE_DN" "(cn=cmapi-*)" cn member'
