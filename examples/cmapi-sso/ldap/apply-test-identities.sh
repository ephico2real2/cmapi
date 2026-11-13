#!/bin/sh
# shellcheck disable=SC2016  # each program here runs in the pod, on the variables of the pod
# Adds cmapi's ten app-cmapi-rbac-* groups and its 13 cmapi.<role> test users to the existing LDAP server, changes nothing else, and fails unless
# that is what happened. Safe to run again: an entry already there, exactly as it should be, is left alone. docs/11, "The test users".
#
#   apply-test-identities.sh                         the groups (cmapi-groups.ldif) and the users (test-identities.tsv), with their passwords in Secret cmapi-ldap-test-users
#   apply-test-identities.sh --remove-old-groups     deletes the ten cmapi-* groups these replace, each by its full dn, and nothing else
#   apply-test-identities.sh --remove-test-identities   deletes what the first form adds, each by its full dn, and the Secret by name (deploy/crc-rollback.sh)
#
# Every form measures the rest of the directory before and after, and fails when it moved. It fails, never warns: this is a server other projects log in through.
#
# Passwords and the server's admin password reach no command line. A generated password goes from a 0600 file to the Secret, and into the pod on stdin; slappasswd reads it from a
# 0600 file there. The admin password stays in the pod and reaches the LDAP clients by -y. Nothing prints a password or its hash. The digests printed are of names and other attributes, and never of userPassword.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
ldap_ns=${LDAP_NAMESPACE:-ldap-testing}
app_ns=${CMAPI_NAMESPACE:-cmapi}
secret=cmapi-ldap-test-users
bind_secret=cmapi-ldap-bind
table=$here/test-identities.tsv
groups_ldif=$here/cmapi-groups.ldif
# The gate of OpenShift's ldap-local identity provider (oc get oauth cluster, read on 2026-11-06), and through its bind rules of realm corp.
gate_cn=app-ssb-autobahnusers
# The groups this replaces, by name. The only cmapi-* entries --remove-old-groups can reach: a look-alike such as cn=cmapi-something stays.
old_groups="cmapi-viewers cmapi-requesters cmapi-onboarding cmapi-prod-approvers cmapi-qa-leads cmapi-uat-leads cmapi-platform-leads cmapi-platform-operators cmapi-platform-admins cmapi-auditors"

mode=apply
case "${1:-}" in
  "") ;;
  --remove-old-groups) mode=remove-old ;;
  --remove-test-identities) mode=remove-new ;;
  *) echo "unknown argument: $1. Nothing done" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "too many arguments: this takes no name, since it can only touch the names it holds. Nothing done" >&2; exit 2; }

OC=${CMAPI_OC:-oc}
# shellcheck disable=SC2086  # CMAPI_OC may carry --kubeconfig
oc_() { $OC "$@"; }
die() { echo "FAIL: $*" >&2; exit 1; }

umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'exit 1' HUP INT TERM

pod=$(oc_ get pods -n "$ldap_ns" --no-headers | awk '/^openldap-server/ && /Running/ {print $1; exit}')
[ -n "$pod" ] || die "no running openldap-server pod in $ldap_ns"
in_pod() { oc_ exec -i -n "$ldap_ns" -c openldap "$pod" -- sh -c "$@"; }

base=$(in_pod 'printf %s "$LDAP_BASE_DN"' </dev/null)
case "$base" in dc=*) ;; *) die "the server's base DN is not one: $base" ;; esac
gate_dn="cn=$gate_cn,ou=Groups,$base"

# Runs first in every program sent to the pod. The password is written by the shell's own printf, so it is on no argument list there either.
lib='
  set -eu
  umask 077
  w=$(mktemp -d)
  trap "rm -rf \"\$w\"" EXIT
  printf %s "$LDAP_ADMIN_PASSWORD" > "$w/admin"
  admin="cn=admin,$LDAP_BASE_DN"
  search() { ldapsearch -x -LLL -o ldif-wrap=no -H ldap://localhost -D "$admin" -y "$w/admin" "$@" </dev/null; }
  # The names a search finds. Through a file, so a search that fails stops here and does not read as "found nobody". LDIF gives a name that is not ASCII as "dn:: <base64>": it is shown as that, so it matches none of ours, and is refused.
  names() { search "$@" dn > "$w/raw"; sed -n "s/^dn:: */base64 /p; s/^dn: //p" "$w/raw"; }
  # 0 there, 1 absent. Anything else stops: a server that did not answer has not said the entry is absent.
  present() {
    rc=0; search -b "$1" -s base dn >/dev/null 2>"$w/err" || rc=$?
    case "$rc" in 0) return 0 ;; 32) return 1 ;; *) echo "FAIL: reading $1: rc $rc: $(cat "$w/err")" >&2; exit 1 ;; esac
  }
'

# What the tree should hold, with no password. A person is shaped as the directory's own people are: cn in the name, directly under ou=People, which the realm reads one level deep.
user_dn() { printf 'cn=%s,ou=People,%s' "$1" "$base"; }
group_dn() { printf 'cn=%s,ou=Groups,%s' "$1" "$base"; }
users() { awk -F'\t' '!/^#/ && NF {print $1, $2}' "$table"; }
user_count() { users | wc -l | tr -d ' '; }
user_ldif() {
  cat <<LDIF
dn: $(user_dn "$1")
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: shadowAccount
cn: $1
uid: $1
sn: ${1#cmapi.}
givenName: cmapi
displayName: $1
mail: $1@ephico2real.com
uidNumber: $2
gidNumber: 1000
homeDirectory: /home/$1
LDIF
}
groups_for_this_server() { grep -v '^#' "$groups_ldif" | sed "s/dc=ephico2real,dc=com/$base/g"; }
new_group_dns() { groups_for_this_server | sed -n 's/^dn: //p'; }
new_user_dns() { users | while read -r uid _; do user_dn "$uid"; echo; done; }

# measure <file of entries to leave out> <1 to strip>: one line each, name=value, of what must not move.
#   others  digest of the names and attributes of every entry under ou=People and ou=Groups but those left out, line by line, so an order the server chooses does not count.
#           memberOf is asked for by name, since a change to a group shows on its members there. userPassword never leaves this awk.
#   gate    digest of the gate group's members
#   idp     how many entries OpenShift's own login filter finds, and idp_cmapi how many of them are cmapi.*.
# The second argument, 1, leaves out memberOf values naming a left-out entry: removing a group takes it from its members' memberOf, which is the removal and not a change to them.
measure_prog=$lib'
  search -b "ou=People,$LDAP_BASE_DN" -s sub "(objectClass=*)" "*" memberOf > "$w/people"
  search -b "ou=Groups,$LDAP_BASE_DN" -s sub "(objectClass=*)" "*" memberOf > "$w/groups"
  cat > "$w/skip"
  awk -v strip="$1" -v OFS=" | " '"'"'
    NR == FNR { skip[$0] = 1; next }
    /^dn:/ { d = $0; left = (substr(d, 5) in skip); if (!left) print d, d; next }
    /^$/ || left { next }
    tolower($0) ~ /^userpassword:/ { next }
    strip == "1" && tolower($0) ~ /^memberof: / && (substr($0, 11) in skip) { next }
    { print d, $0 }
  '"'"' "$w/skip" "$w/people" "$w/groups" > "$w/canon"
  [ -s "$w/canon" ] || { echo "FAIL: nothing to measure under ou=People and ou=Groups: a digest of nothing would match itself" >&2; exit 1; }
  # One step a line, through files: this shell has no pipefail, so in a pipeline a sort or a sha256sum that fails would leave a digest of nothing, which matches itself.
  LC_ALL=C sort "$w/canon" > "$w/canon-sorted"
  sha256sum < "$w/canon-sorted" > "$w/canon-sum"
  echo "others=$(cut -d" " -f1 "$w/canon-sum")"
  rc=0; search -b "$2" -s base member uniqueMember > "$w/gate" || rc=$?
  [ "$rc" = 0 ] || { echo "FAIL: cannot read the gate group $2: rc $rc" >&2; exit 1; }
  grep -iE "^(member|uniqueMember):" "$w/gate" > "$w/gate-members" || true
  [ -s "$w/gate-members" ] || { echo "FAIL: the gate group $2 has no readable members: a digest of nothing would prove nothing" >&2; exit 1; }
  LC_ALL=C sort "$w/gate-members" > "$w/gate-sorted"
  sha256sum < "$w/gate-sorted" > "$w/gate-sum"
  echo "gate=$(cut -d" " -f1 "$w/gate-sum")"
  search -b "$LDAP_BASE_DN" -s sub "(&(uid=*)(memberOf=$2))" uid > "$w/idp"
  echo "idp=$(grep -c "^uid:" "$w/idp" || true)"
  echo "idp_cmapi=$(grep -c "^uid: cmapi\." "$w/idp" || true)"
'
measure() { # measure <skip file> <strip 0|1>. Each value there once and not empty, or same_rest would compare two nothings and pass.
  in_pod "$measure_prog" _ "$2" "$gate_dn" <"$1" > "$tmp/measured"
  for key in others gate idp idp_cmapi; do
    [ "$(grep -c "^$key=" "$tmp/measured" || true)" = 1 ] || die "the measurement $key is missing or repeated"
    [ -n "$(value_of "$key" "$tmp/measured")" ] || die "the measurement $key is empty"
  done
  cat "$tmp/measured"
}
value_of() { sed -n "s/^$1=//p" "$2"; }
same_rest() { # same_rest <before> <after>. Fails unless the directory outside this script's entries did not move.
  [ "$(value_of others "$1")" = "$(value_of others "$2")" ] || die "another entry under ou=People or ou=Groups changed: $(value_of others "$1" | cut -c1-12) before, $(value_of others "$2" | cut -c1-12) after"
  [ "$(value_of gate "$1")" = "$(value_of gate "$2")" ] || die "the members of $gate_cn changed"
  [ "$(value_of idp "$1")" = "$(value_of idp "$2")" ] || die "OpenShift's login filter finds $(value_of idp "$2") entries, $(value_of idp "$1") before"
  echo "ok   the rest of the directory: digest $(value_of others "$2" | cut -c1-12) before and after; $gate_cn unchanged; the login filter finds $(value_of idp "$2") before and after"
}
no_gate_for_tests() { # no_gate_for_tests <measured>. The gate must be readable and working, and a cmapi.* user outside it, or the count of none says nothing.
  [ "$(value_of idp "$1")" -gt 0 ] || die "OpenShift's login filter finds nobody here, so finding no cmapi.* user would prove nothing"
  [ "$(value_of idp_cmapi "$1")" = 0 ] || die "$(value_of idp_cmapi "$1") cmapi.* entries match OpenShift's login filter"
}

secret_data_path() { printf '{.data.%s}' "$(printf %s "$1" | sed 's/\./\\./g')"; }
read_secret_key() { # read_secret_key <uid> <file>: a value in a 0600 file, never in a variable that could reach an argument.
  oc_ get secret "$secret" -n "$app_ns" -o "jsonpath=$(secret_data_path "$1")" </dev/null | base64 -d > "$2"
  [ -s "$2" ] || die "Secret $secret has no key $1"
}

# The state of each of our entries in $tmp/state, one line each: same, different or absent. And stranger for anything else holding one of our names, since the realm would read it. $tmp/ours is their names.
read_state() {
  { new_group_dns; new_user_dns; } > "$tmp/ours"
  : > "$tmp/expected"
  users | while read -r uid number; do user_ldif "$uid" "$number"; echo; done >> "$tmp/expected"
  groups_for_this_server >> "$tmp/expected"
  in_pod "$lib"'
    cat > "$w/expected"
    awk -v w="$w" '"'"'BEGIN { RS = "" } { f = w "/e" NR; print > f; close(f) }'"'"' "$w/expected"
    : > "$w/ours"
    for f in "$w"/e[0-9]*; do
      dn=$(sed -n "s/^dn: //p" "$f"); echo "$dn" >> "$w/ours"
      if present "$dn"; then
        search -b "$dn" -s base "*" | grep -vi "^userPassword:" | grep -v "^$" | LC_ALL=C sort > "$w/have"
        grep -v "^$" "$f" | LC_ALL=C sort > "$w/want"
        if cmp -s "$w/have" "$w/want"; then echo "same $dn"; else echo "different $dn"; fi
      else
        echo "absent $dn"
      fi
    done
    names -b "$LDAP_BASE_DN" -s sub "(uid=cmapi.*)" > "$w/named"
    names -b "$LDAP_BASE_DN" -s sub "(cn=app-cmapi-rbac-*)" >> "$w/named"
    while read -r dn; do grep -qxF "$dn" "$w/ours" || echo "stranger $dn"; done < "$w/named"
  ' < "$tmp/expected" > "$tmp/state"
  # One line for each of ours, or the program did not do what it was asked, and no line would read as nothing wrong.
  [ "$(grep -cE '^(same|different|absent) ' "$tmp/state" || true)" = "$(wc -l < "$tmp/ours" | tr -d ' ')" ] || die "the state of cmapi's entries could not be read: nothing written"
}

# ---- deleting: from the fixed names above, by full dn, on stdin. No -r, no filter.
delete_exact() { # stdin: one dn a line
  in_pod "$lib"'
    ldapdelete -x -H ldap://localhost -D "$admin" -y "$w/admin"
  '
}

remove_old() {
  dns=$tmp/old-dns; : > "$dns"
  for cn in $old_groups; do group_dn "$cn" >> "$dns"; echo >> "$dns"; done
  in_pod "$lib"'
    while read -r dn; do
      present "$dn" || { echo "gone already: $dn"; continue; }
      search -b "$dn" -s base objectClass > "$w/e"
      grep -qix "objectClass: groupOfNames" "$w/e" || { echo "FAIL: $dn is not a groupOfNames: leaving every entry alone" >&2; exit 1; }
    done
  ' < "$dns"
  # The old groups stay until every new entry is what this script writes. A group at the right name with other members, or a test user missing, would leave someone with the wrong role or with none once these go.
  read_state
  if grep -qv '^same ' "$tmp/state"; then
    grep -v '^same ' "$tmp/state" | sed 's/^/FAIL: /' >&2
    die "the new groups and test users are not all in place as this script writes them: the old groups stay, none deleted"
  fi
  measure "$dns" 1 > "$tmp/before"
  # Only those still there: ldapdelete stops on one that is gone, and a rerun has to pass.
  in_pod "$lib"'
    while read -r dn; do if present "$dn"; then printf "%s\n" "$dn"; fi; done
  ' < "$dns" > "$tmp/still"
  if [ -s "$tmp/still" ]; then delete_exact < "$tmp/still"; fi
  measure "$dns" 1 > "$tmp/after"
  same_rest "$tmp/before" "$tmp/after"
  in_pod "$lib"'
    while read -r dn; do if present "$dn"; then echo "FAIL: still there: $dn" >&2; exit 1; fi; done
  ' < "$dns"
  echo "ok   the ten old groups are gone: $(wc -l < "$tmp/still" | tr -d ' ') deleted by this run, each by its full dn"
}

remove_new() {
  # An entry at one of these names that is not what the first form writes is somebody's, as the first form says when it refuses to touch it. A cmapi.* stranger is not on the list, and stays.
  read_state
  if grep -q '^different ' "$tmp/state"; then
    grep '^different ' "$tmp/state" | sed 's/^/FAIL: /' >&2
    die "an entry with one of cmapi's names is not what this script writes, so it is not this script's to delete: nothing deleted"
  fi
  measure "$tmp/ours" 0 > "$tmp/before"
  # Groups first: a person's entry should not go while a group still names it.
  in_pod "$lib"'
    while read -r dn; do if present "$dn"; then printf "%s\n" "$dn"; fi; done
  ' < "$tmp/ours" > "$tmp/still"
  if [ -s "$tmp/still" ]; then delete_exact < "$tmp/still"; fi
  measure "$tmp/ours" 0 > "$tmp/after"
  same_rest "$tmp/before" "$tmp/after"
  oc_ delete secret "$secret" -n "$app_ns" --ignore-not-found >/dev/null
  echo "ok   the test users, the new groups and Secret $secret are gone: $(wc -l < "$tmp/still" | tr -d ' ') entries deleted by this run. Nothing was restored"
}

case "$mode" in
  remove-old) remove_old; exit 0 ;;
  remove-new) remove_new; exit 0 ;;
esac

# ---- before any write: every read that can stop this.
# "different" stops the run: it is not ours to change. And nothing else may hold our names, or the realm would read it.
read_state
if grep -qE '^(different|stranger) ' "$tmp/state"; then
  grep -E '^(different|stranger) ' "$tmp/state" | sed 's/^/FAIL: /' >&2
  die "an entry with one of cmapi's names is not what this script would write: nothing written"
fi

# A uidNumber another entry holds is refused, wherever in the tree it is. The range is free today (10007 is the highest, measured 2026-11-06); this says so at the run.
users | while read -r uid number; do echo "$number $(user_dn "$uid")"; done | in_pod "$lib"'
  while read -r number dn; do
    names -b "$LDAP_BASE_DN" -s sub "(uidNumber=$number)" > "$w/holders"
    while read -r holder; do
      [ "$holder" = "$dn" ] || { echo "FAIL: uidNumber $number is held by $holder, and $dn needs it: nothing written" >&2; exit 1; }
    done < "$w/holders"
  done
'

[ -n "$(oc_ get secret "$bind_secret" -n "$app_ns" --ignore-not-found -o name)" ] || die "no Secret $bind_secret in $app_ns: the bind user comes first (apply-bind-user.sh)"
oc_ get secret "$bind_secret" -n "$app_ns" -o 'jsonpath={.data.password}' | base64 -d > "$tmp/bind-password"
bind_dn=$(oc_ get secret "$bind_secret" -n "$app_ns" -o 'jsonpath={.data.bindDN}' | base64 -d)
if [ ! -s "$tmp/bind-password" ] || [ -z "$bind_dn" ]; then die "Secret $bind_secret has no password or bindDN"; fi

as_bind_prog='
  set -u
  umask 077
  f=$(mktemp); result="$f.result"; trap "rm -f \"$f\" \"$result\"" EXIT; cat > "$f"
  bind="$1"
  as_bind() { ldapsearch -x -LLL -o ldif-wrap=no -H ldap://localhost -D "$bind" -y "$f" "$@"; }
'
# Before any write: the bind user reads ou=People and ou=Groups at all, so its check after the write can only fail on what this adds. Rules that name it in one and not the other would otherwise stop the run with everything written.
in_pod "$as_bind_prog"'
  n=$(as_bind -b "ou=People,$LDAP_BASE_DN" "(objectClass=inetOrgPerson)" dn | grep -c "^dn:" || true)
  [ "$n" -gt 0 ] || { echo "FAIL: the bind user reads no one under ou=People" >&2; exit 1; }
  n=$(as_bind -b "ou=Groups,$LDAP_BASE_DN" "(objectClass=*)" dn | grep -c "^dn:" || true)
  [ "$n" -gt 0 ] || { echo "FAIL: the bind user reads nothing under ou=Groups" >&2; exit 1; }
' _ "$bind_dn" < "$tmp/bind-password"

measure "$tmp/ours" 0 > "$tmp/before"
no_gate_for_tests "$tmp/before"

# ---- the Secret, then the users. In that order: a stop between them leaves a password nobody has used, and a user whose password nobody has would be a stop on every later run.
pw=$tmp/passwords; mkdir "$pw"
if [ -n "$(oc_ get secret "$secret" -n "$app_ns" --ignore-not-found -o name)" ]; then
  keys=$(oc_ get secret "$secret" -n "$app_ns" -o 'go-template={{range $k, $v := .data}}{{$k}}{{"\n"}}{{end}}' | LC_ALL=C sort)
  want=$(users | while read -r uid _; do echo "$uid"; done | LC_ALL=C sort)
  [ "$keys" = "$want" ] || die "Secret $secret does not hold exactly one key per test user: nothing written"
  users | while read -r uid _; do read_secret_key "$uid" "$pw/$uid"; done
  echo "ok   Secret $secret: there, $(user_count) keys"
else
  if grep -q '^same .*ou=People' "$tmp/state"; then die "test users exist with no Secret $secret, so nobody has their passwords. Remove them first (--remove-test-identities): nothing written"; fi
  # Not in a pipeline: its status would be tr's, and an openssl that failed would put empty passwords in the Secret.
  users | while read -r uid _; do
    openssl rand -hex 24 > "$tmp/generated"
    tr -d '\n' < "$tmp/generated" > "$pw/$uid"
    [ -s "$pw/$uid" ] || die "openssl gave no password for $uid: nothing written"
  done
  rm -f "$tmp/generated"
  oc_ create secret generic "$secret" -n "$app_ns" --from-file="$pw" >/dev/null
  echo "ok   Secret $secret: created, $(user_count) keys"
fi

users | while read -r uid number; do
  dn=$(user_dn "$uid")
  if grep -qxF "same $dn" "$tmp/state"; then echo "there: $dn"; continue; fi
  { cat "$pw/$uid"; echo; user_ldif "$uid" "$number"; } | in_pod "$lib"'
    IFS= read -r password
    printf %s "$password" > "$w/p"
    unset password
    hash=$(slappasswd -T "$w/p")
    rm -f "$w/p"
    { cat; printf "userPassword: %s\n" "$hash"; } | ldapadd -x -H ldap://localhost -D "$admin" -y "$w/admin"
  '
done

# ---- the groups. One at a time, with no -c: a failure here is a stop, not a line to scroll past.
groups_for_this_server | awk -v d="$tmp/g" 'BEGIN { RS = "" } { f = d NR; print > f; close(f) }'
for f in "$tmp"/g[0-9]*; do
  dn=$(sed -n 's/^dn: //p' "$f")
  if grep -qxF "same $dn" "$tmp/state"; then echo "there: $dn"; continue; fi
  in_pod "$lib"'
    ldapadd -x -H ldap://localhost -D "$admin" -y "$w/admin"
  ' < "$f"
done

# ---- after. Each of these fails the script.
measure "$tmp/ours" 0 > "$tmp/after"
same_rest "$tmp/before" "$tmp/after"
no_gate_for_tests "$tmp/after"
echo "ok   no cmapi.* user matches OpenShift's login filter, which finds $(value_of idp "$tmp/after")"

# What the realm reads, as the realm's own bind user: the filters are the realm's. And no hash.
in_pod "$as_bind_prog"'
  fail=0
  check() { if [ "$2" = "$3" ]; then echo "ok   $1: $2"; else echo "FAIL $1: $2, wanted $3" >&2; fail=1; fi; }
  check "the bind user reads the new groups" "$(as_bind -b "ou=Groups,$LDAP_BASE_DN" "(&(objectClass=groupOfNames)(cn=app-cmapi-rbac-*))" dn | grep -c "^dn:")" "$2"
  check "the bind user reads their members" "$(as_bind -b "ou=Groups,$LDAP_BASE_DN" "(cn=app-cmapi-rbac-*)" member | grep -c "^member:")" "$3"
  check "the bind user reads the test users, one level under ou=People" "$(as_bind -b "ou=People,$LDAP_BASE_DN" -s one "(&(objectClass=inetOrgPerson)(uid=cmapi.*))" dn | grep -c "^dn:")" "$4"
  as_bind -b "ou=People,$LDAP_BASE_DN" "(uid=cmapi.*)" userPassword > "$result" || { echo "FAIL: the bind user could not check whether a password hash is readable" >&2; exit 1; }
  check "the bind user sees no password hash" "$(grep -ci "^userPassword" "$result" || true)" 0
  exit "$fail"
' _ "$bind_dn" "$(new_group_dns | wc -l | tr -d ' ')" "$(grep -c '^member:' "$groups_ldif")" "$(user_count)" < "$tmp/bind-password"

# Each user's password is the one in the Secret: Keycloak checks it by binding as the user, so this is the same check. Each line reaches the shell's own read and printf in the pod, never an argument.
users | while read -r uid _; do printf '%s %s\n' "$(user_dn "$uid")" "$(cat "$pw/$uid")"; done | in_pod '
  set -eu
  umask 077
  f=$(mktemp); trap "rm -f \"$f\"" EXIT
  while read -r dn password; do
    printf %s "$password" > "$f"
    ldapwhoami -x -H ldap://localhost -D "$dn" -y "$f" >/dev/null </dev/null || { echo "FAIL: $dn does not sign in to LDAP with the password in the Secret" >&2; exit 1; }
  done
'
echo "ok   all $(user_count) sign in to LDAP with the passwords in Secret $secret"
