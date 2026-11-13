#!/bin/sh
# Creates cmapi's read-only bind user, cmapi-ldap-bind, on the existing LDAP server, and fails unless it can read
# ou=People and ou=Groups and nothing more. Safe to run again.
#
# The server's rules are exhaustive: any identity they do not name is refused, and looks like missing data. So this also
# adds the user to the rules for those two subtrees. It changes those two rules only, in one atomic modify, because a
# replace of the whole list that leaves a rule out stops every login on the server.
#
# The password is generated here, kept only in Secrets, and passed on stdin, so it never reaches a command line or a log.
set -eu

ldap_ns=${LDAP_NAMESPACE:-ldap-testing}
app_ns=${CMAPI_NAMESPACE:-cmapi}
keycloak_ns=${KEYCLOAK_NAMESPACE:-keycloak}
secret=cmapi-ldap-bind

pod=$(oc get pods -n "$ldap_ns" --no-headers | awk '/^openldap-server/ && /Running/ {print $1; exit}')
[ -n "$pod" ] || { echo "no running openldap-server pod in $ldap_ns" >&2; exit 1; }
in_pod() { oc exec -i -n "$ldap_ns" -c openldap "$pod" -- sh -c "$@"; }

base=$(in_pod 'printf %s "$LDAP_BASE_DN"' </dev/null)
bind_dn="cn=cmapi-ldap-bind,ou=TrustedApplications,$base"

umask 077
password_file=$(mktemp)
trap 'rm -f "$password_file"' EXIT

# The Secret in the cmapi namespace is the source, and the realm import's placeholder reads the copy in Keycloak's.
if oc get secret "$secret" -n "$app_ns" >/dev/null 2>&1; then
  oc get secret "$secret" -n "$app_ns" -o jsonpath='{.data.password}' | base64 -d > "$password_file"
else
  openssl rand -hex 24 | tr -d '\n' > "$password_file"
  oc create secret generic "$secret" -n "$app_ns" \
    --from-file=password="$password_file" --from-literal=bindDN="$bind_dn" >/dev/null
fi
if ! oc get secret "$secret" -n "$keycloak_ns" >/dev/null 2>&1; then
  oc create secret generic "$secret" -n "$keycloak_ns" \
    --from-file=password="$password_file" --from-literal=bindDN="$bind_dn" >/dev/null
fi

# The entry, in the same shape as the other bind accounts in ou=TrustedApplications. The stored value is a salted hash.
# shellcheck disable=SC2016
in_pod '
  set -eu
  admin="cn=admin,$LDAP_BASE_DN"
  dn="$1"
  if ldapsearch -x -LLL -H ldap://localhost -D "$admin" -w "$LDAP_ADMIN_PASSWORD" -b "$dn" -s base dn 2>/dev/null | grep -q "^dn:"; then
    cat >/dev/null
    echo "entry exists: $dn"
    exit 0
  fi
  f=$(mktemp); cat > "$f"; hash=$(slappasswd -T "$f"); rm -f "$f"
  ldapadd -x -H ldap://localhost -D "$admin" -w "$LDAP_ADMIN_PASSWORD" <<LDIF
dn: $dn
objectClass: simpleSecurityObject
objectClass: organizationalRole
cn: cmapi-ldap-bind
description: Read-only bind account for cmapi Keycloak LDAP user federation - reads ou=People and ou=Groups
userPassword: $hash
LDIF
' _ "$bind_dn" < "$password_file"

# Rules {1} People and {2} Groups only. {0} keeps userPassword from this user, and {3} keeps ou=TrustedApplications from it.
# shellcheck disable=SC2016
in_pod '
  set -eu
  dn="$1"
  db="olcDatabase={1}mdb,cn=config"
  rules=$(ldapsearch -LLL -Y EXTERNAL -H ldapi:/// -o ldif-wrap=no -b "$db" -s base olcAccess 2>/dev/null | grep "^olcAccess: ")
  changes=""
  for n in 1 2; do
    old=$(printf "%s\n" "$rules" | grep "^olcAccess: {$n}to ")
    case "$old" in
      *"$dn"*) continue ;;
      *" by * none") ;;
      *) echo "rule {$n} does not end in by * none: leaving the rules alone" >&2; exit 1 ;;
    esac
    new=$(printf "%s\n" "$old" | sed "s|by \* none\$|by dn=\"$dn\" read by * none|")
    changes="$changes
delete: olcAccess
$old
-
add: olcAccess
$new
-"
  done
  [ -n "$changes" ] || { echo "rules already name $dn"; exit 0; }
  printf "dn: %s\nchangetype: modify%s\n" "$db" "$changes" | ldapmodify -Y EXTERNAL -H ldapi:/// 2>/dev/null
' _ "$bind_dn" </dev/null

# The ConfigMap holds the whole rule list for a hand reapply, which replaces every rule, so it has to name this user too.
oc get cm ldap-acls -n "$ldap_ns" -o json | jq --arg dn "$bind_dn" '
  .data["configure-acls.ldif"] |= (split("\n") | map(
    if (test("^olcAccess: \\{[12]\\}to ") and (contains($dn) | not))
    then sub("by \\* none$"; "by dn=\"" + $dn + "\" read by * none")
    else . end) | join("\n"))
  | del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .metadata.managedFields)
' | oc replace -f - >/dev/null

# Proof, as the new user. 32 is what the server answers for a subtree a user may not see.
# shellcheck disable=SC2016
in_pod '
  set -u
  dn="$1"
  f=$(mktemp); cat > "$f"
  as_user() { ldapsearch -x -LLL -H ldap://localhost -D "$dn" -y "$f" "$@" 2>&1; }
  fail=0
  check() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2, wanted $3"; fail=1; fi; }
  people=$(as_user -b "ou=People,$LDAP_BASE_DN" "(objectClass=inetOrgPerson)" dn | grep -c "^dn:")
  [ "$people" -gt 0 ] && check "reads ou=People" yes yes || check "reads ou=People" no yes
  # Any group here: apply-test-identities.sh makes the cmapi groups, needs this user first, and checks them as this user.
  groups=$(as_user -b "ou=Groups,$LDAP_BASE_DN" "(objectClass=groupOfNames)" dn | grep -c "^dn:")
  [ "$groups" -gt 0 ] && check "reads ou=Groups" yes yes || check "reads ou=Groups" no yes
  # Exit first: a read that failed for another reason has shown nothing, and its count of nothing would pass.
  as_user -b "ou=People,$LDAP_BASE_DN" "(objectClass=inetOrgPerson)" userPassword > "$f.out"
  check "the read for a password hash answers (ldapsearch exit)" "$?" 0
  check "sees no password hash" "$(grep -c "^userPassword" "$f.out")" 0
  as_user -b "ou=TrustedApplications,$LDAP_BASE_DN" "(objectClass=*)" dn > "$f.out"
  check "cannot read ou=TrustedApplications (ldapsearch exit)" "$?" 32
  printf "dn: cn=cmapi-write-probe,ou=Groups,%s\nobjectClass: groupOfNames\ncn: cmapi-write-probe\nmember: %s\n" "$LDAP_BASE_DN" "$dn" |
    ldapadd -x -H ldap://localhost -D "$dn" -y "$f" >/dev/null 2>&1
  check "cannot write (ldapadd exit)" "$?" 50
  rm -f "$f" "$f.out"
  exit "$fail"
' _ "$bind_dn" < "$password_file"
