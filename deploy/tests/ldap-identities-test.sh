#!/usr/bin/env bash
# shellcheck disable=SC2015,SC2016  # ok and bad never fail, so A && ok || bad is if-then-else; the programs in single quotes run in the container
# deploy/tests/ldap-identities-test.sh: examples/cmapi-sso/ldap/apply-test-identities.sh, against a real OpenLDAP of the image the server runs (osixia/openldap 1.5.0), with a stub oc that forwards
# exec to it and keeps Secrets as files. Rules shaped as the server's (ConfigMap ldap-acls, read on 2026-11-06), a gate group and an identity-provider filter as OpenShift's, and the ten old groups with their real members.
# Then every way the script says it stops, real failures inside the container, and mutants of it: a mutant that passes is a promise this test cannot fail on. "ldap-identities-test.sh failures" runs the failures alone, says so, and runs no mutant. The server's memberOf overlay is not known from outside the pod, so the run is repeated on the image's default (groupOfUniqueNames)
# and on groupOfNames, where a group's change reaches its members' entries. One container cmapi-w1-lt-*, labelled, with no port published; only what this run labelled is removed. Test values only. CONTAINER=podman on a Mac, docker in CI. Exit 1 on any failure.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd); SRC=$ROOT/examples/cmapi-sso/ldap
C=${CONTAINER:-docker}; LDAP=docker.io/osixia/openldap@sha256:18742e9c449c9c1afe129d3f2f3ee15fb34cc43e5f940a20f3399728f41d7c28  # 1.5.0
NAME=cmapi-w1-lt-ldap; LABEL=cmapi.test=ldap-identities; BASE=dc=ephico2real,dc=com; ADMIN=lt-admin
W=$(mktemp -d); fails=0; survived=0
bad() { echo "  FAIL $*"; fails=$((fails+1)); }; ok() { echo "  ok   $*"; }
cleanup() { for i in $("$C" ps -a -q --filter "label=$LABEL"); do "$C" rm -f "$i" >/dev/null 2>&1; done; rm -rf "$W"; }
trap cleanup EXIT

mkdir -p "$W/bin" "$W/secrets/cmapi"; export LT_C=$C LT_NAME=$NAME LT_ARGV=$W/argv.log LT_SECRETS=$W/secrets LT_DELETES=$W/deletes
# Every call's arguments are logged, so a password on one can be found, and every name given to ldapdelete, so a broad delete can. exec reaches the container; a Secret is a directory of files.
cat >"$W/bin/oc" <<'OC'
#!/usr/bin/env bash
printf 'oc %s\n' "$*" >>"$LT_ARGV"
case "$*" in
  "get pods -n ldap-testing --no-headers") echo "openldap-server-1 1/1 Running 0 1d"; exit 0;;
  "exec -i -n ldap-testing -c openldap "*)
    case "$*" in *ldapdelete*) tee -a "$LT_DELETES" | { shift 8; "$LT_C" exec -i "$LT_NAME" "$@"; }; exit $?;; esac
    shift 8; exec "$LT_C" exec -i "$LT_NAME" "$@";;
  "get secret "*"--ignore-not-found -o name") [ ! -d "$LT_SECRETS/$5/$3" ] || echo "secret/$3"; exit 0;;
  "get secret "*" -n "*" -o jsonpath={.data."*)
    d=$LT_SECRETS/$5/$3; k=${7#jsonpath=\{.data.}; k=${k%\}}; k=${k//\\/}; [ -f "$d/$k" ] && base64 <"$d/$k"; exit 0;;
  "get secret "*" -n "*" -o go-template="*) ls "$LT_SECRETS/$5/$3"; exit 0;;
  "create secret generic "*)
    d=$LT_SECRETS/$6/$4; [ ! -e "$d" ] || { echo "already exists" >&2; exit 1; }; mkdir -p "$d"; cp "${7#--from-file=}"/* "$d/"; exit 0;;
  "delete secret "*) rm -rf "${LT_SECRETS:?}/$5/$3"; exit 0;;
esac
echo "stub oc: unhandled $*" >&2; exit 3
OC
chmod +x "$W/bin/oc"; export PATH="$W/bin:$PATH"
in_c() { "$C" exec -i "$NAME" "$@"; }
adm() { in_c "$1" -x -H ldap://localhost -D "cn=admin,$BASE" -w "$ADMIN" "${@:2}"; }

# Rules as the server's: every identity not named is refused. What differs between the server and the stand-in is only who the third-party accounts are.
BIND_DN="cn=cmapi-ldap-bind,ou=TrustedApplications,$BASE"; BIND_PW=lt-bind-password
acls() { # acls <1: the bind user is in the rules>
  local by=""; [ "$1" = 1 ] && by="by dn=\"$BIND_DN\" read "
  in_c ldapmodify -Y EXTERNAL -H ldapi:/// >/dev/null 2>&1 <<LDIF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcAccess
olcAccess: {0}to attrs=userPassword by self write by dn="cn=admin,$BASE" write by anonymous auth by * none
olcAccess: {1}to dn.subtree="ou=People,$BASE" by self read by dn="cn=admin,$BASE" write ${by}by * none
olcAccess: {2}to dn.subtree="ou=Groups,$BASE" by dn="cn=admin,$BASE" write ${by}by * none
olcAccess: {3}to * by dn="cn=admin,$BASE" write by * none
LDIF
}
OLD="cmapi-viewers cmapi-requesters cmapi-onboarding cmapi-prod-approvers cmapi-qa-leads cmapi-uat-leads cmapi-platform-leads cmapi-platform-operators cmapi-platform-admins cmapi-auditors"
person() { printf 'dn: cn=%s,ou=People,%s\nobjectClass: inetOrgPerson\nobjectClass: posixAccount\nobjectClass: shadowAccount\ncn: %s\nsn: x\nuid: %s\nmail: %s@ephico2real.com\nuidNumber: %s\ngidNumber: %s\nhomeDirectory: /home/%s\nuserPassword: lt-%s\n\n' "$1" "$BASE" "$1" "$1" "$1" "$2" "$2" "$1" "$1"; }
seed() { # the directory as this run finds it on the server: people, other groups, the old groups with real members, the gate
  local gate_oc=$1
  { printf 'dn: ou=People,%s\nobjectClass: organizationalUnit\nou: People\n\n' "$BASE"
    printf 'dn: ou=Groups,%s\nobjectClass: organizationalUnit\nou: Groups\n\n' "$BASE"
    printf 'dn: ou=TrustedApplications,%s\nobjectClass: organizationalUnit\nou: TrustedApplications\n\n' "$BASE"
    printf 'dn: %s\nobjectClass: simpleSecurityObject\nobjectClass: organizationalRole\ncn: cmapi-ldap-bind\nuserPassword: %s\n\n' "$BIND_DN" "$BIND_PW"
    person john.doe 10001; person jane.smith 10002; person bob.wilson 10003; person alice.cooper 10004; person charlie.brown 10005
    printf 'dn: cn=app-ssb-autobahnusers,ou=Groups,%s\n' "$BASE"
    if [ "$gate_oc" = groupOfNames ]; then printf 'objectClass: groupOfNames\ncn: app-ssb-autobahnusers\nmember: cn=john.doe,ou=People,%s\nmember: cn=jane.smith,ou=People,%s\n\n' "$BASE" "$BASE"
    else printf 'objectClass: groupOfUniqueNames\ncn: app-ssb-autobahnusers\nuniqueMember: cn=john.doe,ou=People,%s\nuniqueMember: cn=jane.smith,ou=People,%s\n\n' "$BASE" "$BASE"; fi
    printf 'dn: cn=app-ocp-rbac-other,ou=Groups,%s\nobjectClass: groupOfNames\ncn: app-ocp-rbac-other\nmember: cn=john.doe,ou=People,%s\n\n' "$BASE" "$BASE"
    # Look-alikes: a filter on cmapi-* would take them, and exact names must not.
    printf 'dn: cn=cmapi-keepme,ou=Groups,%s\nobjectClass: groupOfNames\ncn: cmapi-keepme\nmember: cn=bob.wilson,ou=People,%s\n\n' "$BASE" "$BASE"
    printf 'dn: cn=cmapi-viewers-extra,ou=Groups,%s\nobjectClass: groupOfNames\ncn: cmapi-viewers-extra\nmember: cn=bob.wilson,ou=People,%s\n\n' "$BASE" "$BASE"
    for g in $OLD; do printf 'dn: cn=%s,ou=Groups,%s\nobjectClass: groupOfNames\ncn: %s\nmember: cn=charlie.brown,ou=People,%s\nmember: cn=jane.smith,ou=People,%s\n\n' "$g" "$BASE" "$g" "$BASE" "$BASE"; done
  } | adm ldapadd >/dev/null || { echo "the stand-in was not seeded"; exit 1; }
}
start() { # start <groupOfNames|groupOfUniqueNames>
  for i in $("$C" ps -a -q --filter "label=$LABEL"); do "$C" rm -f "$i" >/dev/null 2>&1; done
  "$C" run -d --name "$NAME" --label "$LABEL" -e "LDAP_BASE_DN=$BASE" -e LDAP_DOMAIN=ephico2real.com -e LDAP_ORGANISATION=e -e "LDAP_ADMIN_PASSWORD=$ADMIN" -e LDAP_TLS=false "$LDAP" >/dev/null || { echo "the container did not start"; exit 1; }
  # The image bootstraps with a temporary slapd on the same address, then starts the real one: a change made to the first is lost (measured).
  for _ in $(seq 1 90); do "$C" logs "$NAME" 2>&1 | grep -q 'Running /container/run/process/slapd/run' && in_c ldapwhoami -x -H ldap://localhost -D "cn=admin,$BASE" -w "$ADMIN" >/dev/null 2>&1 && break; sleep 1; done
  if [ "$1" = groupOfNames ]; then
    in_c ldapmodify -Y EXTERNAL -H ldapi:/// >/dev/null 2>&1 <<'LDIF'
dn: olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcMemberOfGroupOC
olcMemberOfGroupOC: groupOfNames
-
replace: olcMemberOfMemberAD
olcMemberOfMemberAD: member
LDIF
  fi
  seed "$1"; acls 1
  mkdir -p "$W/secrets/cmapi/cmapi-ldap-bind"; printf %s "$BIND_PW" >"$W/secrets/cmapi/cmapi-ldap-bind/password"; printf %s "$BIND_DN" >"$W/secrets/cmapi/cmapi-ldap-bind/bindDN"
  rm -rf "$W/secrets/cmapi/cmapi-ldap-test-users"
}
# Measured by this test, not by the script: the whole tree but the script's own entries, every attribute a change would show, with no userPassword read at all. A digest of it.
OURS='^(cn=(cmapi\.[a-z0-9-]+),ou=People|cn=app-cmapi-rbac-[a-z-]+,ou=Groups),'
tree() { # tree [regex of dn to leave out, on top of ours]
  adm ldapsearch -LLL -o ldif-wrap=no -b "$BASE" -s sub "(objectClass=*)" "*" memberOf entryCSN 2>/dev/null | awk -v ours="$OURS" -v more="${1:-^$}" '
    /^dn: /{ d=substr($0,5); left=(d ~ ours || d ~ more); if(!left) print d; next } /^$/||left{next} /^userPassword/{next} { print d" | "$0 }' | LC_ALL=C sort | shasum -a 256 | cut -c1-16
}
everything() { adm ldapsearch -LLL -o ldif-wrap=no -b "$BASE" -s sub "(objectClass=*)" "*" memberOf entryCSN 2>/dev/null | LC_ALL=C sort | shasum -a 256 | cut -c1-16; }
count() { adm ldapsearch -LLL -b "$1" -s sub "$2" dn 2>/dev/null | grep -c '^dn:'; }
remove_ours() { # what the script added, by the test's own hand, for the next case
  { adm ldapsearch -LLL -b "ou=Groups,$BASE" "(cn=app-cmapi-rbac-*)" dn 2>/dev/null; adm ldapsearch -LLL -b "ou=People,$BASE" "(uid=cmapi.*)" dn 2>/dev/null; } | sed -n 's/^dn: //p' | adm ldapdelete >/dev/null 2>&1 || true
  rm -rf "$W/secrets/cmapi/cmapi-ldap-test-users"
}
S=$SRC/apply-test-identities.sh
run() { : >"$LT_ARGV"; : >"$LT_DELETES"; "${SCRIPT:-$S}" "$@" >"$W/out" 2>&1; echo $?; }
# Exactly these full names reached ldapdelete in the last run, and no other. A delete that also removes something else cannot pass this, whatever the tree shows afterwards.
deleted_exactly() { [ "$(LC_ALL=C sort "$LT_DELETES")" = "$(LC_ALL=C sort)" ]; }
old_dns() { for g in $OLD; do echo "cn=$g,ou=Groups,$BASE"; done; }
new_dns() { grep '^dn: ' "$SRC/cmapi-groups.ldif" | cut -c5-; awk -F'\t' -v b="$BASE" '!/^#/ && NF {print "cn=" $1 ",ou=People," b}' "$SRC/test-identities.tsv"; }
# Every attribute of every entry but those named, without memberOf and entryCSN: what a person's entry says, whichever group left it.
tree_of_people() {
  adm ldapsearch -LLL -o ldif-wrap=no -b "$BASE" -s sub "(objectClass=*)" "*" 2>/dev/null | awk -v ours="$OURS" -v old='^cn=cmapi-(viewers|requesters|onboarding|prod-approvers|qa-leads|uat-leads|platform-leads|platform-operators|platform-admins|auditors),' '
    /^dn: /{ d=substr($0,5); left=(d ~ ours || d ~ old); if(!left) print d; next } /^$/||left{next} /^userPassword/{next} { print d" | "$0 }' | LC_ALL=C sort | shasum -a 256 | cut -c1-16
}
leaked() { local f; for f in "$W/secrets/cmapi/cmapi-ldap-test-users"/*; do [ -f "$f" ] || continue; grep -qF "$(cat "$f")" "$W/out" "$LT_ARGV" && return 0; done; return 1; }
no_leak() { # every password, and any hash, nowhere in the output or on an argument
  local f; for f in "$W/secrets/cmapi/cmapi-ldap-test-users"/* "$W/secrets/cmapi/cmapi-ldap-bind/password"; do [ -f "$f" ] || continue
    if grep -qF "$(cat "$f")" "$W/out" "$LT_ARGV"; then bad "$1: the password in $(basename "$f") reached the output or an argument"; return; fi; done
  if grep -qE '\{SSHA\}|userPassword:' "$W/out"; then bad "$1: a password hash in the output"; return; fi
  if grep -qF "$ADMIN" "$W/out" "$LT_ARGV"; then bad "$1: the admin password reached the output or an argument"; return; fi
  ok "$1: no password or hash in the output or on an argument"
}
refuses() { # refuses <label>: this run must fail and write nothing
  local label=$1 before after rc; before=$(everything); rc=$(run); after=$(everything)
  [ "$rc" != 0 ] && ok "refused: $label" || bad "not refused: $label"
  [ "$before" = "$after" ] && ok "  and nothing written to LDAP" || bad "$label: LDAP changed before the refusal"
}

the_run() { # the_run <overlay>
  local overlay=$1 base_tree="" rc t1
  start "$overlay"
  echo "-- memberOf on $overlay"
  if [ "$(count "$BASE" "(&(uid=*)(memberOf=cn=app-ssb-autobahnusers,ou=Groups,$BASE))")" = 2 ]; then ok "the control: the login filter finds the gate's two members"; else bad "the stand-in's login filter does not find the gate's members"; fi
  base_tree=$(tree)

  # The first run, and what it made.
  rc=$(run); [ "$rc" = 0 ] && ok "first run: rc 0" || { bad "first run: rc $rc: $(tail -5 "$W/out")"; }
  no_leak "first run"
  [ "$(tree)" = "$base_tree" ] && ok "no other entry moved, every attribute and entryCSN, by this test's own measure" || bad "another entry moved on the first run"
  [ "$(count "ou=People,$BASE" "(uid=cmapi.*)")" = 13 ] && ok "13 test users" || bad "$(count "ou=People,$BASE" "(uid=cmapi.*)") test users"
  [ "$(count "ou=Groups,$BASE" "(cn=app-cmapi-rbac-*)")" = 10 ] && ok "10 groups" || bad "$(count "ou=Groups,$BASE" "(cn=app-cmapi-rbac-*)") groups"
  [ "$(count "$BASE" "(&(uid=cmapi.*)(memberOf=cn=app-ssb-autobahnusers,ou=Groups,$BASE))")" = 0 ] && ok "no test user behind the gate" || bad "a test user behind the gate"
  # Against the table, from the tree itself: each user's entry and memberships, as the script was asked for them.
  local members; members=$(adm ldapsearch -LLL -o ldif-wrap=no -b "ou=Groups,$BASE" "(cn=app-cmapi-rbac-*)" member 2>/dev/null | grep '^member:' | grep -vc "cn=cmapi\.")
  [ "$members" = 0 ] && ok "no real person in a cmapi group" || bad "$members members of cmapi groups are not test users"
  # In one exec: a wrong password must fail too, or the sign-in check would mean nothing.
  local wanted; wanted=$(awk -F'\t' -v d="$W/secrets/cmapi/cmapi-ldap-test-users" '!/^#/ && NF { f = d "/" $1; getline p < f; close(f); print $1, $2, $3, p }' "$SRC/test-identities.tsv")
  in_c sh -c '
    b=$1; a=$2; bad=0
    say() { echo "$1"; bad=1; }
    while read -r uid number groups password; do
      e=$(ldapsearch -x -LLL -o ldif-wrap=no -H ldap://localhost -D "cn=admin,$b" -w "$a" -b "cn=$uid,ou=People,$b" -s base "*" </dev/null)
      for want in "objectClass: inetOrgPerson" "objectClass: posixAccount" "objectClass: shadowAccount" "uid: $uid" "mail: $uid@ephico2real.com" "gidNumber: 1000" "homeDirectory: /home/$uid" "uidNumber: $number"; do
        printf "%s\n" "$e" | grep -qxF "$want" || say "$uid has no $want"
      done
      have=$(ldapsearch -x -LLL -H ldap://localhost -D "cn=admin,$b" -w "$a" -b "ou=Groups,$b" "(&(cn=app-cmapi-rbac-*)(member=cn=$uid,ou=People,$b))" cn </dev/null | sed -n "s/^cn: //p" | LC_ALL=C sort | paste -sd, -)
      [ "$groups" != - ] || groups=
      [ "$have" = "$groups" ] || say "$uid is in [$have], not [$groups]"
      ldapwhoami -x -H ldap://localhost -D "cn=$uid,ou=People,$b" -w "$password" >/dev/null 2>&1 </dev/null || say "$uid does not sign in with the password in the Secret"
      ! ldapwhoami -x -H ldap://localhost -D "cn=$uid,ou=People,$b" -w wrong >/dev/null 2>&1 </dev/null || say "$uid signs in with a wrong password"
    done
    exit "$bad"
  ' _ "$BASE" "$ADMIN" <<<"$wanted" >"$W/table.out" 2>&1 || bad "against the table: $(cat "$W/table.out")"
  ok "each user against the table: entry, groups, and its password from the Secret"
  [ "$(find "$W/secrets/cmapi/cmapi-ldap-test-users" -type f | wc -l | tr -d ' ')" = 13 ] && ok "Secret cmapi-ldap-test-users: 13 keys" || bad "the Secret's keys"
  grep -qE '^[0-9a-f]{48}$' "$W/secrets/cmapi/cmapi-ldap-test-users/cmapi.requester" && ok "a password is openssl rand -hex 24" || bad "the password's shape"

  # Run again: nothing changes, down to entryCSN.
  t1=$(everything); local keep; keep=$(cat "$W/secrets/cmapi/cmapi-ldap-test-users/cmapi.viewer")
  rc=$(run); [ "$rc" = 0 ] && ok "second run: rc 0" || bad "second run: rc $rc: $(tail -3 "$W/out")"
  [ "$(everything)" = "$t1" ] && ok "second run: nothing in LDAP changed" || bad "the second run changed LDAP"
  [ "$(cat "$W/secrets/cmapi/cmapi-ldap-test-users/cmapi.viewer")" = "$keep" ] && ok "second run: the passwords stay" || bad "the second run changed a password"
  no_leak "second run"

  # --remove-old-groups: the ten, and only the ten.
  local keep_tree; keep_tree=$(tree_of_people)
  rc=$(run --remove-old-groups cn=cmapi-keepme,ou=Groups,$BASE); [ "$rc" = 2 ] && ok "--remove-old-groups refuses a name: only its own ten" || bad "--remove-old-groups took a name: rc $rc"
  rc=$(run --remove-everything); [ "$rc" = 2 ] && ok "an unknown flag is refused" || bad "an unknown flag: rc $rc"
  [ "$(count "ou=Groups,$BASE" "(cn=cmapi-*)")" = 12 ] && ok "and those two refusals deleted nothing" || bad "a refused call deleted something"
  # An entry at an old name that is not a group is somebody else's.
  adm ldapdelete "cn=cmapi-auditors,ou=Groups,$BASE" >/dev/null 2>&1
  printf 'dn: cn=cmapi-auditors,ou=Groups,%s\nobjectClass: organizationalRole\ncn: cmapi-auditors\n\n' "$BASE" | adm ldapadd >/dev/null
  rc=$(run --remove-old-groups); [ "$rc" != 0 ] && ok "an old name that is not a groupOfNames stops it" || bad "it deleted an old name that is not a group"
  [ "$(count "ou=Groups,$BASE" "(cn=cmapi-*)")" = 12 ] && [ ! -s "$LT_DELETES" ] && ok "and it deleted none of them" || bad "it deleted some before it stopped"
  adm ldapdelete "cn=cmapi-auditors,ou=Groups,$BASE" >/dev/null 2>&1
  printf 'dn: cn=cmapi-auditors,ou=Groups,%s\nobjectClass: groupOfNames\ncn: cmapi-auditors\nmember: cn=charlie.brown,ou=People,%s\n\n' "$BASE" "$BASE" | adm ldapadd >/dev/null
  local groups_before; groups_before=$(count "ou=Groups,$BASE" "(objectClass=*)")
  rc=$(run --remove-old-groups); [ "$rc" = 0 ] && ok "--remove-old-groups: rc 0" || bad "--remove-old-groups: rc $rc: $(tail -3 "$W/out")"
  old_dns | deleted_exactly && ok "ldapdelete was given exactly the ten full names" || bad "ldapdelete was given: $(cat "$LT_DELETES")"
  [ "$(count "ou=Groups,$BASE" "(objectClass=*)")" = "$((groups_before - 10))" ] && ok "exactly ten fewer entries under ou=Groups" || bad "$(count "ou=Groups,$BASE" "(objectClass=*)") under ou=Groups, was $groups_before"
  for g in $OLD; do [ "$(count "ou=Groups,$BASE" "(cn=$g)")" = 0 ] || bad "$g is still there"; done
  [ "$(count "ou=Groups,$BASE" "(|(cn=cmapi-keepme)(cn=cmapi-viewers-extra))")" = 2 ] && ok "the look-alikes stay" || bad "a look-alike was deleted"
  # On groupOfNames its members lose memberOf for those groups, which is the removal itself. Nothing else about them moves.
  local tree_after; tree_after=$(adm ldapsearch -LLL -o ldif-wrap=no -b "cn=jane.smith,ou=People,$BASE" -s base memberOf 2>/dev/null | grep -c 'memberOf: cn=cmapi-')
  [ "$tree_after" = 0 ] && ok "no member's memberOf names a removed group" || bad "$tree_after memberOf lines still name a removed group"
  [ "$(tree_of_people)" = "$keep_tree" ] && ok "every other entry says what it said, by this test's own measure" || bad "another entry moved on --remove-old-groups"
  rc=$(run --remove-old-groups); [ "$rc" = 0 ] && ok "--remove-old-groups a second time: rc 0, nothing left to do" || bad "--remove-old-groups a second time: rc $rc: $(tail -3 "$W/out")"
  no_leak "--remove-old-groups"

  # --remove-test-identities: what the first form added, and no more. The old groups do not come back.
  local t2; t2=$(tree)
  rc=$(run --remove-test-identities); [ "$rc" = 0 ] && ok "--remove-test-identities: rc 0" || bad "--remove-test-identities: rc $rc: $(tail -3 "$W/out")"
  new_dns | deleted_exactly && ok "ldapdelete was given exactly the ten groups and 13 users, by full name" || bad "ldapdelete was given: $(cat "$LT_DELETES")"
  [ "$(count "$BASE" "(|(uid=cmapi.*)(cn=app-cmapi-rbac-*))")" = 0 ] && ok "no test user and no new group left" || bad "something of ours is left"
  [ "$(tree)" = "$t2" ] && ok "nothing else moved, and the old groups were not restored" || bad "another entry moved on removal"
  [ ! -d "$W/secrets/cmapi/cmapi-ldap-test-users" ] && ok "Secret cmapi-ldap-test-users is gone" || bad "the Secret is still there"
  [ -d "$W/secrets/cmapi/cmapi-ldap-bind" ] && ok "Secret cmapi-ldap-bind stays" || bad "the bind Secret was deleted"
  rc=$(run --remove-test-identities); [ "$rc" = 0 ] && ok "and a second time: rc 0" || bad "--remove-test-identities a second time: rc $rc"
  no_leak "--remove-test-identities"
}

# Each stop, on a directory that has just had the run's own entries taken away again.
the_stops() {
  echo "-- what stops it"
  start groupOfNames
  printf 'dn: cn=has.a.number,ou=People,%s\nobjectClass: inetOrgPerson\nobjectClass: posixAccount\ncn: has.a.number\nsn: x\nuid: has.a.number\nuidNumber: 10105\ngidNumber: 1\nhomeDirectory: /x\n\n' "$BASE" | adm ldapadd >/dev/null
  refuses "a uidNumber another entry holds"; grep -q 'uidNumber 10105 is held by' "$W/out" || bad "no reason given: $(tail -2 "$W/out")"
  [ ! -d "$W/secrets/cmapi/cmapi-ldap-test-users" ] && ok "  and no Secret made" || bad "a Secret was made before the refusal"
  adm ldapdelete "cn=has.a.number,ou=People,$BASE" >/dev/null 2>&1

  printf 'dn: cn=cmapi.stranger,ou=People,%s\nobjectClass: inetOrgPerson\ncn: cmapi.stranger\nsn: x\nuid: cmapi.stranger\n\n' "$BASE" | adm ldapadd >/dev/null
  refuses "a cmapi.* user that is not in the table: the realm would read it"
  adm ldapdelete "cn=cmapi.stranger,ou=People,$BASE" >/dev/null 2>&1

  printf 'dn: cn=app-cmapi-rbac-stranger,ou=Groups,%s\nobjectClass: groupOfNames\ncn: app-cmapi-rbac-stranger\nmember: cn=john.doe,ou=People,%s\n\n' "$BASE" "$BASE" | adm ldapadd >/dev/null
  refuses "an app-cmapi-rbac-* group that is not in the file: the realm would read it"
  adm ldapdelete "cn=app-cmapi-rbac-stranger,ou=Groups,$BASE" >/dev/null 2>&1

  # One of our names, with something else in it: a real person in a new group, and a user who differs.
  printf 'dn: cn=app-cmapi-rbac-viewer,ou=Groups,%s\nobjectClass: groupOfNames\ncn: app-cmapi-rbac-viewer\ndescription: Role cmapi-viewer\nmember: cn=cmapi.viewer,ou=People,%s\nmember: cn=john.doe,ou=People,%s\n\n' "$BASE" "$BASE" "$BASE" | adm ldapadd >/dev/null
  refuses "a real person in one of the new groups"
  adm ldapdelete "cn=app-cmapi-rbac-viewer,ou=Groups,$BASE" >/dev/null 2>&1
  printf 'dn: cn=cmapi.viewer,ou=People,%s\nobjectClass: inetOrgPerson\ncn: cmapi.viewer\nsn: someone\nuid: cmapi.viewer\n\n' "$BASE" | adm ldapadd >/dev/null
  refuses "a person at a test user's name who is not the test user"
  adm ldapdelete "cn=cmapi.viewer,ou=People,$BASE" >/dev/null 2>&1

  # The gate: unreadable, or a filter that finds nobody, says nothing; a test user behind it is the thing to stop.
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=app-ssb-autobahnusers,ou=Groups,$BASE
changetype: modrdn
newrdn: cn=app-ssb-autobahnusers-moved
deleteoldrdn: 1
LDIF
  refuses "no gate group to measure"
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=app-ssb-autobahnusers-moved,ou=Groups,$BASE
changetype: modrdn
newrdn: cn=app-ssb-autobahnusers
deleteoldrdn: 1
LDIF
  # A first run, a test user put behind the gate, then the second run must see it.
  [ "$(run)" = 0 ] || bad "the first run for the gate's case: $(tail -3 "$W/out")"
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=app-ssb-autobahnusers,ou=Groups,$BASE
changetype: modify
add: member
member: cn=cmapi.viewer,ou=People,$BASE
LDIF
  refuses "a cmapi.* user behind the gate"; grep -q "match OpenShift's login filter" "$W/out" || bad "no reason given: $(tail -2 "$W/out")"
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=app-ssb-autobahnusers,ou=Groups,$BASE
changetype: modify
delete: member
member: cn=cmapi.viewer,ou=People,$BASE
LDIF

  # Secrets that do not fit what is there.
  rm -rf "$W/secrets/cmapi/cmapi-ldap-test-users"
  refuses "test users there with no Secret: nobody has their passwords"
  [ ! -d "$W/secrets/cmapi/cmapi-ldap-test-users" ] && ok "  and no Secret made" || bad "a Secret was made for users whose passwords it does not hold"
  remove_ours
  [ "$(run)" = 0 ] || bad "a clean run: $(tail -3 "$W/out")"
  rm -f "$W/secrets/cmapi/cmapi-ldap-test-users/cmapi.admin"
  refuses "a Secret with a key missing"
  remove_ours; [ "$(run)" = 0 ] || bad "a clean run: $(tail -3 "$W/out")"
  printf %s wrong-password >"$W/secrets/cmapi/cmapi-ldap-test-users/cmapi.admin"
  local rc; rc=$(run); [ "$rc" != 0 ] && grep -q "does not sign in" "$W/out" && ok "refused: a password in the Secret that LDAP does not accept" || bad "not refused: a password in the Secret that LDAP does not accept"

  # The bind user.
  remove_ours; acls 0
  refuses "a bind user the rules do not name"; acls 1
  printf %s wrong-password >"$W/secrets/cmapi/cmapi-ldap-bind/password"
  refuses "a bind Secret whose password fails"; printf %s "$BIND_PW" >"$W/secrets/cmapi/cmapi-ldap-bind/password"
  rm -rf "$W/secrets/cmapi/cmapi-ldap-bind"
  refuses "no bind Secret"; mkdir -p "$W/secrets/cmapi/cmapi-ldap-bind"; printf %s "$BIND_PW" >"$W/secrets/cmapi/cmapi-ldap-bind/password"; printf %s "$BIND_DN" >"$W/secrets/cmapi/cmapi-ldap-bind/bindDN"

  # The old groups go only once the new are there.
  rc=$(run --remove-old-groups); [ "$rc" != 0 ] && ok "refused: removing the old groups before the new are there" || bad "the old groups went with no new ones there"
  [ "$(count "ou=Groups,$BASE" "(cn=cmapi-*)")" = 12 ] && ok "  and none was deleted" || bad "some were deleted"
}

# Real failures inside the server's container: not text in the script, and no stub answering for LDAP. A tool is moved aside, or a shim in its place fails the calls a glob of its arguments matches, as a server that stopped answering does.
tool_gone() { in_c sh -c 'p=$(command -v "$1"); mv "$p" "$p.real"; echo "$p" > "/tmp/lt-$1"' _ "$1"; }
tool_fails() { # tool_fails <tool> <glob of its arguments, with no space: it goes into a case pattern unquoted>
  in_c sh -c '
    p=$(command -v "$1"); mv "$p" "$p.real"; echo "$p" > "/tmp/lt-$1"
    printf "#!/bin/sh\ncase \"\$*\" in %s) echo \"%s: failed for this case\" >&2; exit 52;; esac\nexec %s \"\$@\"\n" "$2" "$1" "$p.real" > "$p"
    chmod +x "$p"
  ' _ "$1" "$2"
}
tool_back() { in_c sh -c 'p=$(cat "/tmp/lt-$1"); mv "$p.real" "$p"; rm -f "/tmp/lt-$1"' _ "$1"; }
refused_clean() { # refused_clean <label>: as refuses, and no Secret made either
  refuses "$1"
  [ ! -d "$W/secrets/cmapi/cmapi-ldap-test-users" ] && ok "  and no Secret made" || bad "$1: a Secret was made before the refusal"
}
the_gate() { # the gate as start seeds it
  printf 'dn: cn=app-ssb-autobahnusers,ou=Groups,%s\nobjectClass: groupOfNames\ncn: app-ssb-autobahnusers\nmember: cn=john.doe,ou=People,%s\nmember: cn=jane.smith,ou=People,%s\n\n' "$BASE" "$BASE" "$BASE" | adm ldapadd >/dev/null
}
# A failure must stop the run, and not pass as a measurement or a proof. Each case starts on a directory holding none of ours, with the bind user in the rules.
the_failures() {
  echo "-- real failures"
  tool_gone sha256sum; refused_clean "sha256sum gone: no digest to compare"; tool_back sha256sum; remove_ours
  tool_fails sort '*canon*'; refused_clean "sort fails on what the digest covers: a digest of nothing matches itself"; tool_back sort; remove_ours
  tool_fails cut '*-f1*'; refused_clean "the digest comes back empty"; tool_back cut; remove_ours
  tool_fails grep '*uniqueMember*'; refused_clean "the gate's members cannot be taken from what was read: a digest of nothing matches itself"; tool_back grep; remove_ours
  # A gate that answers with no member at all, in the form that does not also look for the login filter's people.
  adm ldapdelete "cn=app-ssb-autobahnusers,ou=Groups,$BASE" >/dev/null 2>&1
  printf 'dn: cn=app-ssb-autobahnusers,ou=Groups,%s\nobjectClass: posixGroup\ncn: app-ssb-autobahnusers\ngidNumber: 5\nmemberUid: john.doe\n\n' "$BASE" | adm ldapadd >/dev/null
  local rc; rc=$(run --remove-test-identities); [ "$rc" != 0 ] && ok "refused: a gate with no member attribute, on the removal too" || bad "a gate with no member attribute passed as unchanged"
  adm ldapdelete "cn=app-ssb-autobahnusers,ou=Groups,$BASE" >/dev/null 2>&1; the_gate
}

# Mutants of the script, each on a fresh directory state. A mutant that passes is a promise above that means nothing.
mutant() { # mutant <label> <python: s = s.replace(...)> <what proves it, a shell test run after, with $rc set>
  local label=$1 edit=$2 proof=$3 rc
  mkdir -p "$W/m"; cp "$SRC/test-identities.tsv" "$SRC/cmapi-groups.ldif" "$W/m/"
  python3 - "$S" "$W/m/apply-test-identities.sh" "$edit" <<'PY' || { bad "mutant $label: not applied"; return; }
import sys
s = orig = open(sys.argv[1]).read()
scope = {"s": s}; exec(sys.argv[3], scope); s = scope["s"]
assert s != orig, "the edit changed nothing"
open(sys.argv[2], "w").write(s)
PY
  chmod +x "$W/m/apply-test-identities.sh"
  export SCRIPT=$W/m/apply-test-identities.sh
  # shellcheck disable=SC2034  # read by the proof
  if eval "$proof"; then echo "  killed   $label"; else echo "  SURVIVED $label"; survived=$((survived+1)); fi
  unset SCRIPT
}
the_mutants() {
  echo "-- mutants"
  start groupOfNames
  # What the script promises to notice: each mutant does the forbidden thing partway through a run, and the run must fail.
  local poke_person='s = s.replace("# ---- after. Each of these fails the script.\n", "printf \"dn: cn=john.doe,ou=People,%s\\nchangetype: modify\\nreplace: sn\\nsn: changed\\n\" \"$base\" | in_pod \"$lib\"\x27 ldapmodify -x -H ldap://localhost -D \"$admin\" -y \"$w/admin\" \x27\n")'
  mutant "a person changed during the run goes unnoticed: the mutant changes one, the run must fail" "$poke_person" \
    'rc=$(run); [ "$rc" != 0 ] && grep -q "another entry" "$W/out"'
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=john.doe,ou=People,$BASE
changetype: modify
replace: sn
sn: x
LDIF
  remove_ours
  local poke_gate='s = s.replace("# ---- after. Each of these fails the script.\n", "printf \"dn: cn=app-ssb-autobahnusers,ou=Groups,%s\\nchangetype: modify\\nadd: member\\nmember: cn=bob.wilson,ou=People,%s\\n\" \"$base\" \"$base\" | in_pod \"$lib\"\x27 ldapmodify -x -H ldap://localhost -D \"$admin\" -y \"$w/admin\" \x27\n")'
  mutant "the gate's members changed during the run: the run must fail" "$poke_gate" \
    'rc=$(run); [ "$rc" != 0 ]'
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=app-ssb-autobahnusers,ou=Groups,$BASE
changetype: modify
delete: member
member: cn=bob.wilson,ou=People,$BASE
LDIF
  remove_ours
  # What the removal must not reach, measured by the test against the tree.
  [ "$(run)" = 0 ] || bad "the run before the removal mutants: $(tail -3 "$W/out")"
  local broad='s = s.replace("for cn in $old_groups; do group_dn \"$cn\" >> \"$dns\"; echo >> \"$dns\"; done", "in_pod \"$lib\"\x27 search -b \"ou=Groups,$LDAP_BASE_DN\" \"(cn=cmapi-*)\" dn | sed -n \"s/^dn: //p\" \x27 </dev/null > \"$dns\"")'
  mutant "the old groups found by a filter on cmapi-*: a broad delete" "$broad" \
    'rc=$(run --remove-old-groups); ! old_dns | deleted_exactly'
  reseed_removal
  mutant "an eleventh name in the list" 's = s.replace("cmapi-auditors\"\n", "cmapi-auditors cmapi-keepme\"\n", 1)' \
    'rc=$(run --remove-old-groups); ! old_dns | deleted_exactly'
  reseed_removal
  mutant "the subtree instead of the names" 's = s.replace("for cn in $old_groups; do group_dn \"$cn\" >> \"$dns\"; echo >> \"$dns\"; done", "printf \"ou=Groups,%s\\n\" \"$base\" > \"$dns\"")' \
    'rc=$(run --remove-old-groups); ! old_dns | deleted_exactly'
  reseed_removal
  mutant "ldapdelete -r" 's = s.replace("ldapdelete -x -H", "ldapdelete -r -x -H")' '! static_deletes_ok "$SCRIPT"'
  mutant "the admin password on an argument in the pod" 's = s.replace("ldapdelete -x -H ldap://localhost -D \"$admin\" -y \"$w/admin\"", "ldapdelete -x -H ldap://localhost -D \"$admin\" -w \"$LDAP_ADMIN_PASSWORD\"")' '! static_deletes_ok "$SCRIPT"'
  remove_ours
  mutant "a hash printed" 's = s.replace("printf \"userPassword: %s\\n\" \"$hash\"; }", "printf \"userPassword: %s\\n\" \"$hash\"; echo \"userPassword: $hash\" >\x262; }")' \
    'rc=$(run); grep -qE "\{SSHA\}|userPassword:" "$W/out"'
  remove_ours
  mutant "the digest's awk failing: a digest of nothing would match itself" 's = s.replace("awk -v strip=", "no-such-awk -v strip=")' 'rc=$(run); [ "$rc" != 0 ]'
  mutant "a search for strangers that fails reads as finding none" 's = s.replace("names -b \"$LDAP_BASE_DN\" -s sub \"(uid=cmapi.*)\"", "names -b \"ou=NoSuch,$LDAP_BASE_DN\" -s sub \"(uid=cmapi.*)\"")' 'rc=$(run); [ "$rc" != 0 ]'
  remove_ours
  mutant "a password on an argument" 's = s.replace("--from-file=\"$pw\"", "--from-file=\"$pw\" --from-literal=x=$(cat \"$pw/cmapi.viewer\")")' \
    'rc=$(run); leaked'
}
reseed_removal() { # the look-alikes and the ten back, for the next mutant
  for g in $OLD cmapi-keepme cmapi-viewers-extra; do
    [ "$(count "ou=Groups,$BASE" "(cn=$g)")" = 1 ] || printf 'dn: cn=%s,ou=Groups,%s\nobjectClass: groupOfNames\ncn: %s\nmember: cn=charlie.brown,ou=People,%s\n\n' "$g" "$BASE" "$g" "$BASE" | adm ldapadd >/dev/null 2>&1
  done
}
# The rule on the text: every delete is ldapdelete with no -r and no -w, from stdin; every admin client by -y.
static_deletes_ok() {
  local f=$1
  if grep -nE 'ldapdelete[^|]*( -r| -w )|ldap[a-z]+ [^|]*-w "\$' "$f"; then return 1; fi
  if grep -nE 'slappasswd[^|]* -s |--from-literal=[a-z.]*=\$' "$f"; then return 1; fi
  return 0
}

# ---- no container needed
static_deletes_ok "$S" >/dev/null && ok "no -r, no -w, no slappasswd -s and no --from-literal in the script" || bad "the script's own text breaks the rule"
python3 - "$SRC" <<'PY' && ok "cmapi-groups.ldif names exactly the table's memberships, ten groups, none empty" || bad "cmapi-groups.ldif and test-identities.tsv disagree"
import re, sys
src = sys.argv[1]; table = {}
for line in open(f"{src}/test-identities.tsv"):
    if line.startswith("#") or not line.strip(): continue
    uid, number, groups, roles = line.rstrip("\n").split("\t")
    for g in ([] if groups == "-" else groups.split(",")):
        table.setdefault(g, set()).add(uid)
ldif = {}
for block in open(f"{src}/cmapi-groups.ldif").read().split("\n\n"):
    m = re.search(r"^cn: (.+)$", block, re.M)
    if m: ldif[m[1]] = set(re.findall(r"^member: cn=([^,]+),ou=People,", block, re.M))
sys.exit(0 if ldif == table and len(ldif) == 10 and all(ldif.values()) else 1)
PY

case "${1:-all}" in
  all) the_run groupOfNames; the_run groupOfUniqueNames; the_stops; the_failures; the_mutants ;;
  failures) start groupOfNames; the_failures; echo "the failures alone: no mutant ran, and neither did the rest of this test" ;;
  *) echo "usage: $0 [failures]" >&2; exit 2 ;;
esac

echo "ldap identity cases failed: $fails, mutants survived: $survived"; [ "$fails" = 0 ] && [ "$survived" = 0 ]
