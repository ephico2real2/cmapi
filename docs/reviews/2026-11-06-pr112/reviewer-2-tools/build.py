#!/usr/bin/env python3
"""Reviewer 2's patch set: each entry is exact-string edits on the tree the previous one left. Writes output/final/NN-name.patch and a tree work/pN per patch."""
import os, shutil, subprocess, sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = f"{R}/work"; FINAL = f"{R}/output/final"
SCRIPT = "examples/cmapi-sso/ldap/apply-test-identities.sh"
BIND = "examples/cmapi-sso/ldap/apply-bind-user.sh"
TEST = "deploy/tests/ldap-identities-test.sh"
TRUST = "deploy/crc-trust.sh"
SCRIPTS_TEST = "deploy/tests/crc-scripts-test.sh"
DOC11 = "docs/11-existing-identity-services.md"
DOC13 = "docs/13-crc-deployment.md"
FLOW = "cmapi/tests/service/test_flow.py"
APPROVALS = "cmapi/tests/core/test_approvals.py"

PATCHES = []
def patch(name, *edits): PATCHES.append((name, edits))

# ------------------------------------------------------------------ 01: job 2, the CI failure
patch("01-stored-requirement-test-moves-to-service",
  (APPROVALS, '''def test_a_stored_requirement_keeps_its_group_path():
    """The stored requirement is what a later approve reads, so the path has to survive the database's JSON."""
    from cmapi.core.db.repo import requirement_from_json, requirement_to_json
    raw = {"environments": {"prod": {"create": 1, "group": "approver-prod"}}}
    req = ApprovalRules(raw, {"prod"}, group_path="/corp/{name}").decide(facts())
    back = requirement_from_json(requirement_to_json(req))
    assert back.token_group("approver-prod") == "/corp/approver-prod"
    old = requirement_to_json(req); old.pop("groupPath")
    assert requirement_from_json(old).token_group("approver-prod") == "/cmapi/app-cmapi-rbac-approver-prod"


''', ''),
  (FLOW, '''def test_a_token_with_no_role_gets_403(world):
''', '''def test_a_stored_requirement_keeps_its_group_path():
    """The stored requirement is what a later approve reads, so the path has to survive the database's JSON. Here and not in tests/core: cmapi.core.db needs sqlalchemy, and the reference-code job runs tests/core with examples/local/requirements.txt, which has none."""
    from cmapi.core.approvals import Requirement, Slot
    from cmapi.core.db.repo import requirement_from_json, requirement_to_json
    req = Requirement(rule="prod-create", slots=(Slot("approver-prod", 1, "r"),), self_approval=False, timeout_hours=48, reasons=("r",), group_path="/corp/{name}")
    back = requirement_from_json(requirement_to_json(req))
    assert back.token_group("approver-prod") == "/corp/approver-prod"
    old = requirement_to_json(req); old.pop("groupPath")
    assert requirement_from_json(old).token_group("approver-prod") == "/cmapi/app-cmapi-rbac-approver-prod"


def test_a_token_with_no_role_gets_403(world):
'''))

# ------------------------------------------------------------------ 02: a row from before the setting
patch("02-a-row-with-no-group-path-is-the-old-constant",
  ("cmapi/src/cmapi/core/authz.py", '''DEFAULT_GROUP_PATH = "/cmapi/app-cmapi-rbac-{name}"
''', '''DEFAULT_GROUP_PATH = "/cmapi/app-cmapi-rbac-{name}"
# A requirement stored before this setting has no path of its own, and was decided under the constant of that time. Read under
# the default, its slots would name groups nobody holds on a site that kept its names.
LEGACY_GROUP_PATH = "/cmapi/cmapi-{name}"
'''),
  ("cmapi/src/cmapi/core/db/repo.py", '''from cmapi.core.authz import DEFAULT_GROUP_PATH
''', '''from cmapi.core.authz import LEGACY_GROUP_PATH
'''),
  ("cmapi/src/cmapi/core/db/repo.py", '''group_path=d.get("groupPath", DEFAULT_GROUP_PATH))''', '''group_path=d.get("groupPath", LEGACY_GROUP_PATH))'''),
  (FLOW, '''    old = requirement_to_json(req); old.pop("groupPath")
    assert requirement_from_json(old).token_group("approver-prod") == "/cmapi/app-cmapi-rbac-approver-prod"


def test_a_token_with_no_role_gets_403(world):
''', '''    old = requirement_to_json(req); old.pop("groupPath")
    assert requirement_from_json(old).token_group("platform-leads") == "/cmapi/cmapi-platform-leads", "a row from before identity.groupPath was decided under the old constant"


def test_an_open_request_keeps_the_path_it_was_decided_under(world):
    """docs/11's claim, through the routes: the setting changes while a request is open, and the approvers do not."""
    client, ctx, git, kube, validator, keys = world
    big = {**NS, "namespace": "payments-batch", "tier": "large"}
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=big, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    ctx.cfg.approvals.group_path = "/corp/{name}"
    decided = dict(roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-platform"])
    moved = dict(roles=["cmapi-approver"], groups=["/corp/approver-platform"])
    assert client.get("/api/v1/requests?status=pending_approval&approver=me", headers=auth(keys, "sam", **moved)).json()["items"] == []
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "sam", **moved))
    assert r.status_code == 403 and r.json()["code"] == "not-eligible"
    assert [i["requestId"] for i in client.get("/api/v1/requests?status=pending_approval&approver=me", headers=auth(keys, "amy", **decided)).json()["items"]] == [rid]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **decided))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text


def test_a_token_with_no_role_gets_403(world):
'''),
  (DOC11, '''A request stores the path it was decided under with its slots, so changing the setting does not move the approvers of an open request.''',
          '''A request stores the path it was decided under with its slots, so changing the setting does not move the approvers of an open request; a row stored before this setting reads as the old `/cmapi/cmapi-{name}`, the constant it was decided under.'''))

# ------------------------------------------------------------------ 03: reviewer 1, finding 1, amended
patch("03-measurements-fail-closed",
  (SCRIPT, '''  LC_ALL=C sort "$w/canon" | sha256sum | cut -d" " -f1 | sed "s/^/others=/"
  rc=0; search -b "$2" -s base member uniqueMember > "$w/gate" || rc=$?
  [ "$rc" = 0 ] || { echo "FAIL: cannot read the gate group $2: rc $rc" >&2; exit 1; }
  grep -iE "^(member|uniqueMember):" "$w/gate" | LC_ALL=C sort | sha256sum | cut -d" " -f1 | sed "s/^/gate=/"
''', '''  # One step a line, through files: this shell has no pipefail, so in a pipeline a sort or a sha256sum that fails would leave a digest of nothing, which matches itself.
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
'''),
  (SCRIPT, '''measure() { # measure <skip file> <strip 0|1>
  in_pod "$measure_prog" _ "$2" "$gate_dn" <"$1"
}
''', '''measure() { # measure <skip file> <strip 0|1>. Each value there once and not empty, or same_rest would compare two nothings and pass.
  in_pod "$measure_prog" _ "$2" "$gate_dn" <"$1" > "$tmp/measured"
  for key in others gate idp idp_cmapi; do
    [ "$(grep -c "^$key=" "$tmp/measured" || true)" = 1 ] || die "the measurement $key is missing or repeated"
    [ -n "$(value_of "$key" "$tmp/measured")" ] || die "the measurement $key is empty"
  done
  cat "$tmp/measured"
}
'''),
  (TEST, '''# Then every way the script says it stops, and mutants of it: a mutant that passes is a promise this test cannot fail on. The server's memberOf overlay''',
         '''# Then every way the script says it stops, real failures inside the container, and mutants of it: a mutant that passes is a promise this test cannot fail on. "ldap-identities-test.sh failures" runs the failures alone, says so, and runs no mutant. The server's memberOf overlay'''),
  (TEST, '''# Mutants of the script, each on a fresh directory state. A mutant that passes is a promise above that means nothing.
''', '''# Real failures inside the server's container: not text in the script, and no stub answering for LDAP. A tool is moved aside, or a shim in its place fails the calls a glob of its arguments matches, as a server that stopped answering does.
tool_gone() { in_c sh -c 'p=$(command -v "$1"); mv "$p" "$p.real"; echo "$p" > "/tmp/lt-$1"' _ "$1"; }
tool_fails() { # tool_fails <tool> <glob of its arguments, with no space: it goes into a case pattern unquoted>
  in_c sh -c '
    p=$(command -v "$1"); mv "$p" "$p.real"; echo "$p" > "/tmp/lt-$1"
    printf "#!/bin/sh\\ncase \\"\\$*\\" in %s) echo \\"%s: failed for this case\\" >&2; exit 52;; esac\\nexec %s \\"\\$@\\"\\n" "$2" "$1" "$p.real" > "$p"
    chmod +x "$p"
  ' _ "$1" "$2"
}
tool_back() { in_c sh -c 'p=$(cat "/tmp/lt-$1"); mv "$p.real" "$p"; rm -f "/tmp/lt-$1"' _ "$1"; }
refused_clean() { # refused_clean <label>: as refuses, and no Secret made either
  refuses "$1"
  [ ! -d "$W/secrets/cmapi/cmapi-ldap-test-users" ] && ok "  and no Secret made" || bad "$1: a Secret was made before the refusal"
}
the_gate() { # the gate as start seeds it
  printf 'dn: cn=app-ssb-autobahnusers,ou=Groups,%s\\nobjectClass: groupOfNames\\ncn: app-ssb-autobahnusers\\nmember: cn=john.doe,ou=People,%s\\nmember: cn=jane.smith,ou=People,%s\\n\\n' "$BASE" "$BASE" "$BASE" | adm ldapadd >/dev/null
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
  printf 'dn: cn=app-ssb-autobahnusers,ou=Groups,%s\\nobjectClass: posixGroup\\ncn: app-ssb-autobahnusers\\ngidNumber: 5\\nmemberUid: john.doe\\n\\n' "$BASE" | adm ldapadd >/dev/null
  local rc; rc=$(run --remove-test-identities); [ "$rc" != 0 ] && ok "refused: a gate with no member attribute, on the removal too" || bad "a gate with no member attribute passed as unchanged"
  adm ldapdelete "cn=app-ssb-autobahnusers,ou=Groups,$BASE" >/dev/null 2>&1; the_gate
}

# Mutants of the script, each on a fresh directory state. A mutant that passes is a promise above that means nothing.
'''),
  (TEST, '''the_run groupOfNames
the_run groupOfUniqueNames
the_stops
the_mutants

echo "ldap identity cases failed: $fails, mutants survived: $survived"; [ "$fails" = 0 ] && [ "$survived" = 0 ]
''', '''case "${1:-all}" in
  all) the_run groupOfNames; the_run groupOfUniqueNames; the_stops; the_failures; the_mutants ;;
  failures) start groupOfNames; the_failures; echo "the failures alone: no mutant ran, and neither did the rest of this test" ;;
  *) echo "usage: $0 [failures]" >&2; exit 2 ;;
esac

echo "ldap identity cases failed: $fails, mutants survived: $survived"; [ "$fails" = 0 ] && [ "$survived" = 0 ]
'''))

# ------------------------------------------------------------------ 04: reviewer 1, finding 2
patch("04-a-failed-hash-read-is-not-zero-hashes",
  (SCRIPT, '''  f=$(mktemp); trap "rm -f \\"$f\\"" EXIT; cat > "$f"
  bind="$1"
''', '''  f=$(mktemp); result="$f.result"; trap "rm -f \\"$f\\" \\"$result\\"" EXIT; cat > "$f"
  bind="$1"
'''),
  (SCRIPT, '''  check "the bind user sees no password hash" "$(as_bind -b "ou=People,$LDAP_BASE_DN" "(uid=cmapi.*)" userPassword | grep -ci "^userPassword")" 0
''', '''  as_bind -b "ou=People,$LDAP_BASE_DN" "(uid=cmapi.*)" userPassword > "$result" || { echo "FAIL: the bind user could not check whether a password hash is readable" >&2; exit 1; }
  check "the bind user sees no password hash" "$(grep -ci "^userPassword" "$result" || true)" 0
'''),
  (TEST, '''  adm ldapdelete "cn=app-ssb-autobahnusers,ou=Groups,$BASE" >/dev/null 2>&1; the_gate
}
''', '''  adm ldapdelete "cn=app-ssb-autobahnusers,ou=Groups,$BASE" >/dev/null 2>&1; the_gate
  # The proof after the write: a read that fails has not shown there is no hash to read.
  tool_fails ldapsearch '*userPassword*'
  rc=$(run); [ "$rc" != 0 ] && grep -q "could not check whether a password hash is readable" "$W/out" && ok "refused: the read for a password hash fails, which is not zero hashes" || bad "a failed read for a password hash passed: rc $rc"
  tool_back ldapsearch; remove_ours
}
'''))

# ------------------------------------------------------------------ 05: a name only base64 can carry
patch("05-a-name-in-base64-is-still-a-name",
  (SCRIPT, '''  # The names a search finds. Through a file, so a search that fails stops here and does not read as "found nobody".
  names() { search "$@" dn > "$w/raw"; sed -n "s/^dn: //p" "$w/raw"; }
''', '''  # The names a search finds. Through a file, so a search that fails stops here and does not read as "found nobody". LDIF gives a name that is not ASCII as "dn:: <base64>": it is shown as that, so it matches none of ours, and is refused.
  names() { search "$@" dn > "$w/raw"; sed -n "s/^dn:: */base64 /p; s/^dn: //p" "$w/raw"; }
'''),
  (TEST, '''  tool_back ldapsearch; remove_ours
}
''', '''  tool_back ldapsearch; remove_ours
  # Someone whose name LDIF can only give in base64 holds what a test user needs.
  local jose; jose=$(printf 'cn=Jos\\303\\251 Real,ou=People,%s' "$BASE")
  printf 'dn: %s\\nobjectClass: inetOrgPerson\\nobjectClass: posixAccount\\ncn: Jos\\303\\251 Real\\nsn: x\\nuid: jose.real\\nuidNumber: 10105\\ngidNumber: 1\\nhomeDirectory: /x\\n\\n' "$jose" | adm ldapadd >/dev/null
  refused_clean "a uidNumber held by a person whose name is not ASCII"; grep -q 'uidNumber 10105 is held by base64 ' "$W/out" || bad "no reason given: $(tail -2 "$W/out")"
  adm ldapdelete "$jose" >/dev/null 2>&1; remove_ours
  printf 'dn: %s\\nobjectClass: inetOrgPerson\\ncn: Jos\\303\\251 Real\\nsn: x\\nuid: cmapi.viewer\\n\\n' "$jose" | adm ldapadd >/dev/null
  refused_clean "a test user's uid held by a person whose name is not ASCII"; grep -q 'stranger base64 ' "$W/out" || bad "no reason given: $(tail -2 "$W/out")"
  adm ldapdelete "$jose" >/dev/null 2>&1; remove_ours
}
'''))

# ------------------------------------------------------------------ 06: a precondition measured only after the write
patch("06-the-bind-user-reads-groups-before-any-write",
  (SCRIPT, '''# Before any write: the bind user reads ou=People at all, so its check after the write can only fail on what this adds.
''', '''# Before any write: the bind user reads ou=People and ou=Groups at all, so its check after the write can only fail on what this adds. Rules that name it in one and not the other would otherwise stop the run with everything written.
'''),
  (SCRIPT, '''  [ "$n" -gt 0 ] || { echo "FAIL: the bind user reads no one under ou=People" >&2; exit 1; }
''', '''  [ "$n" -gt 0 ] || { echo "FAIL: the bind user reads no one under ou=People" >&2; exit 1; }
  n=$(as_bind -b "ou=Groups,$LDAP_BASE_DN" "(objectClass=*)" dn | grep -c "^dn:" || true)
  [ "$n" -gt 0 ] || { echo "FAIL: the bind user reads nothing under ou=Groups" >&2; exit 1; }
'''),
  (TEST, '''acls() { # acls <1: the bind user is in the rules>
  local by=""; [ "$1" = 1 ] && by="by dn=\\"$BIND_DN\\" read "
''', '''acls() { # acls <1: the bind user is in the rules; people: in the rule for ou=People alone; 0: in neither>
  local by="" by_groups=""; [ "$1" = 0 ] || by="by dn=\\"$BIND_DN\\" read "; [ "$1" != 1 ] || by_groups=$by
'''),
  (TEST, '''olcAccess: {2}to dn.subtree="ou=Groups,$BASE" by dn="cn=admin,$BASE" write ${by}by * none
''', '''olcAccess: {2}to dn.subtree="ou=Groups,$BASE" by dn="cn=admin,$BASE" write ${by_groups}by * none
'''),
  (TEST, '''  adm ldapdelete "$jose" >/dev/null 2>&1; remove_ours
}
''', '''  adm ldapdelete "$jose" >/dev/null 2>&1; remove_ours
  # A precondition: measured before the write, not found after it.
  acls people; refused_clean "a bind user the rule for ou=People names and the rule for ou=Groups does not"; grep -q 'reads nothing under ou=Groups' "$W/out" || bad "no reason given: $(tail -2 "$W/out")"
  acls 1; remove_ours
}
'''),
  (DOC13, '''**Stops when,** before anything is written: the bind user cannot read `ou=People`; the gate group''', '''**Stops when,** before anything is written: the bind user cannot read `ou=People` or `ou=Groups`; the gate group'''))

# ------------------------------------------------------------------ 07: the old groups go only for a new set that is proven
patch("07-old-groups-stay-until-the-new-set-is-proven",
  (SCRIPT, '''# ---- deleting: from the fixed names above, by full dn, on stdin. No -r, no filter.
''', '''# The state of each of our entries in $tmp/state, one line each: same, different or absent. And stranger for anything else holding one of our names, since the realm would read it. $tmp/ours is their names.
read_state() {
  { new_group_dns; new_user_dns; } > "$tmp/ours"
  : > "$tmp/expected"
  users | while read -r uid number; do user_ldif "$uid" "$number"; echo; done >> "$tmp/expected"
  groups_for_this_server >> "$tmp/expected"
  in_pod "$lib"\'
    cat > "$w/expected"
    awk -v w="$w" \'"\'"\'BEGIN { RS = "" } { f = w "/e" NR; print > f; close(f) }\'"\'"\' "$w/expected"
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
  \' < "$tmp/expected" > "$tmp/state"
  # One line for each of ours, or the program did not do what it was asked, and no line would read as nothing wrong.
  [ "$(grep -cE \'^(same|different|absent) \' "$tmp/state" || true)" = "$(wc -l < "$tmp/ours" | tr -d \' \')" ] || die "the state of cmapi\'s entries could not be read: nothing written"
}

# ---- deleting: from the fixed names above, by full dn, on stdin. No -r, no filter.
'''),
  (SCRIPT, '''  new_group_dns | in_pod "$lib"\'
    while read -r dn; do present "$dn" || { echo "FAIL: $dn is not there yet: the old groups stay until the new ones are in place" >&2; exit 1; }; done
  \'
  measure "$dns" 1 > "$tmp/before"
''', '''  # The old groups stay until every new entry is what this script writes. A group at the right name with other members, or a test user missing, would leave someone with the wrong role or with none once these go.
  read_state
  if grep -qv \'^same \' "$tmp/state"; then
    grep -v \'^same \' "$tmp/state" | sed \'s/^/FAIL: /\' >&2
    die "the new groups and test users are not all in place as this script writes them: the old groups stay, none deleted"
  fi
  measure "$dns" 1 > "$tmp/before"
'''),
  (SCRIPT, '''# ---- before any write: every read that can stop this.
{ new_group_dns; new_user_dns; } > "$tmp/ours"
: > "$tmp/expected"
users | while read -r uid number; do user_ldif "$uid" "$number"; echo; done >> "$tmp/expected"
groups_for_this_server >> "$tmp/expected"

# The state of each of our entries, one line each. "different" stops the run: it is not ours to change. And nothing else may hold our names, or the realm would read it.
in_pod "$lib"\'
  cat > "$w/expected"
  awk -v w="$w" \'"\'"\'BEGIN { RS = "" } { f = w "/e" NR; print > f; close(f) }\'"\'"\' "$w/expected"
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
\' < "$tmp/expected" > "$tmp/state"

if grep -qE \'^(different|stranger) \' "$tmp/state"; then
''', '''# ---- before any write: every read that can stop this.
# "different" stops the run: it is not ours to change. And nothing else may hold our names, or the realm would read it.
read_state
if grep -qE \'^(different|stranger) \' "$tmp/state"; then
'''),
  (TEST, '''  acls 1; remove_ours
}
''', '''  acls 1; remove_ours
  # The old groups go only for a new set that is what the script writes.
  [ "$(run)" = 0 ] || bad "the run before the unproven set: $(tail -3 "$W/out")"
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=app-cmapi-rbac-viewer,ou=Groups,$BASE
changetype: modify
add: member
member: cn=john.doe,ou=People,$BASE
LDIF
  rc=$(run --remove-old-groups); [ "$rc" != 0 ] && [ ! -s "$LT_DELETES" ] && ok "refused: removing the old groups while a new group holds someone else" || bad "the old groups went with a new group not as written: rc $rc"
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=app-cmapi-rbac-viewer,ou=Groups,$BASE
changetype: modify
delete: member
member: cn=john.doe,ou=People,$BASE
LDIF
  reseed_removal
  adm ldapdelete "cn=cmapi.admin,ou=People,$BASE" >/dev/null 2>&1
  rc=$(run --remove-old-groups); [ "$rc" != 0 ] && [ ! -s "$LT_DELETES" ] && ok "refused: removing the old groups while a test user is missing" || bad "the old groups went with a test user missing: rc $rc"
  reseed_removal; remove_ours
}
'''),
  (DOC11, '''It takes no name from outside, refuses an old name that is not a `groupOfNames`, and refuses to start until the new groups are there.''', '''It takes no name from outside, refuses an old name that is not a `groupOfNames`, and refuses to start until every new group and test user is exactly what the first form writes.'''),
  (DOC13, '''**Stops when** a new group is not there yet; an old name holds''', '''**Stops when** a new group or test user is not there, or is not what step 9 writes; an old name holds'''))

# ------------------------------------------------------------------ 08: a removal does not reach what it did not write
patch("08-removal-leaves-what-it-did-not-write",
  (SCRIPT, '''remove_new() {
  { new_group_dns; new_user_dns; } > "$tmp/ours"
  measure "$tmp/ours" 0 > "$tmp/before"
''', '''remove_new() {
  # An entry at one of these names that is not what the first form writes is somebody's, as the first form says when it refuses to touch it. A cmapi.* stranger is not on the list, and stays.
  read_state
  if grep -q \'^different \' "$tmp/state"; then
    grep \'^different \' "$tmp/state" | sed \'s/^/FAIL: /\' >&2
    die "an entry with one of cmapi\'s names is not what this script writes, so it is not this script\'s to delete: nothing deleted"
  fi
  measure "$tmp/ours" 0 > "$tmp/before"
'''),
  (TEST, '''  reseed_removal; remove_ours
}
''', '''  reseed_removal; remove_ours
  # The removal, on an entry at one of its names that it did not write: a real person there, or a real person added to a group.
  [ "$(run)" = 0 ] || bad "the run before the removal: $(tail -3 "$W/out")"
  adm ldapdelete "cn=cmapi.admin,ou=People,$BASE" >/dev/null 2>&1
  printf 'dn: cn=cmapi.admin,ou=People,%s\\nobjectClass: inetOrgPerson\\ncn: cmapi.admin\\nsn: A Real Person\\nuid: cmapi.admin\\n\\n' "$BASE" | adm ldapadd >/dev/null
  rc=$(run --remove-test-identities); [ "$rc" != 0 ] && [ ! -s "$LT_DELETES" ] && [ "$(count "ou=People,$BASE" "(sn=A Real Person)")" = 1 ] && ok "refused: removing an entry at a test user's name that is someone else" || bad "the removal reached a person it did not write: rc $rc, it asked for $(wc -l <"$LT_DELETES") deletes"
  adm ldapdelete "cn=cmapi.admin,ou=People,$BASE" >/dev/null 2>&1; remove_ours
  [ "$(run)" = 0 ] || bad "the run before the removal: $(tail -3 "$W/out")"
  adm ldapmodify >/dev/null 2>&1 <<LDIF
dn: cn=app-cmapi-rbac-admin,ou=Groups,$BASE
changetype: modify
add: member
member: cn=john.doe,ou=People,$BASE
LDIF
  rc=$(run --remove-test-identities); [ "$rc" != 0 ] && [ ! -s "$LT_DELETES" ] && ok "refused: removing a new group with a real person added" || bad "the removal reached a group holding a real person: rc $rc, it asked for $(wc -l <"$LT_DELETES") deletes"
  remove_ours
}
'''),
  (SCRIPTS_TEST, '''  "exec -i -n ldap-testing"*"ldapdelete"*) cat >>"$ARGV_LOG.ldap-deleted"; exit 0;;
''', '''  "exec -i -n ldap-testing"*"ldapdelete"*) cat >>"$ARGV_LOG.ldap-deleted"; exit 0;;
  "exec -i -n ldap-testing"*'echo "stranger $dn"'*) sed -n 's/^dn: /same /p'; exit 0;;
'''),
  (DOC11, '''`--remove-test-identities` deletes the 10 groups and 13 users each by its full `dn`, then the Secret by name. `deploy/crc-rollback.sh` calls it. It restores nothing.''', '''`--remove-test-identities` deletes the 10 groups and 13 users each by its full `dn`, then the Secret by name, and refuses, deleting none, if an entry at one of those names is not what the first form writes. `deploy/crc-rollback.sh` calls it. It restores nothing.'''),
  (DOC13, '''then Secret `cmapi-ldap-test-users` by name. It fails if anything else under `ou=People` or `ou=Groups` moved.''', '''then Secret `cmapi-ldap-test-users` by name. It refuses, deleting none, if an entry at one of those names is not what step 9 writes, and it fails if anything else under `ou=People` or `ou=Groups` moved.'''))

# ------------------------------------------------------------------ 09: a password of nothing
patch("09-a-failed-openssl-makes-no-secret",
  (SCRIPT, '''  users | while read -r uid _; do openssl rand -hex 24 | tr -d '\\n' > "$pw/$uid"; done
''', '''  # Not in a pipeline: its status would be tr's, and an openssl that failed would put empty passwords in the Secret.
  users | while read -r uid _; do
    openssl rand -hex 24 > "$tmp/generated"
    tr -d '\\n' < "$tmp/generated" > "$pw/$uid"
    [ -s "$pw/$uid" ] || die "openssl gave no password for $uid: nothing written"
  done
  rm -f "$tmp/generated"
'''),
  (TEST, '''  remove_ours
}

# Mutants of the script''', '''  remove_ours
  # openssl on the machine running the script.
  mkdir -p "$W/no-openssl"; printf '#!/bin/sh\\nexit 1\\n' >"$W/no-openssl/openssl"; chmod +x "$W/no-openssl/openssl"
  local path=$PATH; PATH="$W/no-openssl:$PATH"; refused_clean "openssl fails: a Secret of empty passwords"; PATH=$path; remove_ours
}

# Mutants of the script'''))

# ------------------------------------------------------------------ 10: --mac-ca and --extra-ca
patch("10-mac-ca-keeps-working-with-an-extra-ca",
  (TRUST, '''#   --mac-ca OUT               writes the bundle this Mac's checks use: that CA (Keycloak's Route is passthrough) and the ingress CA (edge Routes). Beside it, keycloak-ca.pem and ingress-ca.pem,
#                              one CA each, for the keychain step in docs/13. Only CA:TRUE certificates: default-ingress-cert's bundle also holds the *.apps-crc.testing site certificate (#109).
''', '''#   --mac-ca OUT               writes the bundle this Mac's checks use: every CA of the trust file (Keycloak's Route is passthrough) and the ingress CA (edge Routes). Beside it, keycloak-ca.pem and ingress-ca.pem,
#                              one CA each, for the keychain step in docs/13: Keycloak's is the file's first, as --write puts it. Only CA:TRUE certificates: default-ingress-cert's bundle also holds the *.apps-crc.testing site certificate (#109).
'''),
  (TRUST, '''mac_ca() {
  local out=$1 dir; dir=$(dirname "$out")
  ( umask 077
    bundle_of "$OUT" | the_one_ca "$OUT" "$dir/keycloak-ca.pem"
    oc_ get cm default-ingress-cert -n openshift-config-managed -o 'jsonpath={.data.ca-bundle\\.crt}' | the_one_ca "ConfigMap default-ingress-cert" "$dir/ingress-ca.pem"
    cat "$dir/keycloak-ca.pem" "$dir/ingress-ca.pem" >"$out" )
''', '''# first_cert: stdin's first PEM certificate. awk reads to the end, or under pipefail what feeds it could die of SIGPIPE (see require_certs).
first_cert() { awk '/BEGIN CERTIFICATE/ { n++ } n == 1 { print }'; }
mac_ca() {
  local out=$1 dir; dir=$(dirname "$out")
  ( umask 077
    bundle_of "$OUT" | first_cert | the_one_ca "$OUT" "$dir/keycloak-ca.pem"
    oc_ get cm default-ingress-cert -n openshift-config-managed -o 'jsonpath={.data.ca-bundle\\.crt}' | the_one_ca "ConfigMap default-ingress-cert" "$dir/ingress-ca.pem"
    { bundle_of "$OUT"; cat "$dir/ingress-ca.pem"; } >"$out" )
'''),
  (SCRIPTS_TEST, '''if grep -rqE -- '(^|[^-])(-k |--insecure|--tls-verify=false)' "$D"/crc-*.sh; then''', '''# A trust file that also holds an external database's CA (--write --extra-ca, docs/12): --mac-ca still works, the keychain's file is Keycloak's, and the Mac's bundle keeps every CA the pods trust.
openssl req -x509 -newkey rsa:2048 -nodes -keyout /dev/null -out "$W/db-ca.pem" -subj "/CN=external-db-ca" -days 2 2>/dev/null
cp "$TRUST" "$W/keep-trust"; want "trust --write --extra-ca" 0 "$(run "$D/crc-trust.sh" --write --extra-ca "$W/db-ca.pem")"
mkdir "$W/mac4"; want "trust --mac-ca with an extra CA in the trust file" 0 "$(run "$D/crc-trust.sh" --mac-ca "$W/mac4/crc-ca.pem")"
[ -e "$W/mac4/keycloak-ca.pem" ] && [ "$(fp "$W/mac4/keycloak-ca.pem")" = "$(fp "$W/ca.pem")" ] && ok "keycloak-ca.pem is Keycloak's CA, not the extra one" || bad "keycloak-ca.pem with an extra CA in the trust file"
[ -e "$W/mac4/crc-ca.pem" ] && [ "$(grep -c 'BEGIN CERTIFICATE' "$W/mac4/crc-ca.pem")" = 3 ] && ok "the Mac's bundle holds Keycloak's, the extra one and the ingress CA" || bad "the Mac's bundle with an extra CA in the trust file"
cp "$W/keep-trust" "$TRUST"
if grep -rqE -- '(^|[^-])(-k |--insecure|--tls-verify=false)' "$D"/crc-*.sh; then'''))

# ------------------------------------------------------------------ 11: the sibling of reviewer 1's finding 2
patch("11-apply-bind-user-a-failed-read-is-not-a-pass",
  (BIND, '''  check "sees no password hash" "$(as_user -b "ou=People,$LDAP_BASE_DN" "(objectClass=inetOrgPerson)" userPassword | grep -c "^userPassword")" 0
  check "cannot read ou=TrustedApplications" "$(as_user -b "ou=TrustedApplications,$LDAP_BASE_DN" "(objectClass=*)" dn | grep -c "^dn:")" 0
''', '''  # Exit first: a read that failed for another reason has shown nothing, and its count of nothing would pass.
  as_user -b "ou=People,$LDAP_BASE_DN" "(objectClass=inetOrgPerson)" userPassword > "$f.out"
  check "the read for a password hash answers (ldapsearch exit)" "$?" 0
  check "sees no password hash" "$(grep -c "^userPassword" "$f.out")" 0
  as_user -b "ou=TrustedApplications,$LDAP_BASE_DN" "(objectClass=*)" dn > "$f.out"
  check "cannot read ou=TrustedApplications (ldapsearch exit)" "$?" 32
'''),
  (BIND, '''  rm -f "$f"
  exit "$fail"
''', '''  rm -f "$f" "$f.out"
  exit "$fail"
'''),
  (TEST, '''  "get secret "*" -n "*" -o go-template="*) ls "$LT_SECRETS/$5/$3"; exit 0;;
''', '''  "get secret "*" -n "*" -o go-template="*) ls "$LT_SECRETS/$5/$3"; exit 0;;
  "get secret "*" -n "*) [ -d "$LT_SECRETS/$5/$3" ]; exit $?;;
  "get cm ldap-acls -n ldap-testing -o json") printf '{"metadata":{"name":"ldap-acls"},"data":{"configure-acls.ldif":""}}\\n'; exit 0;;
  "replace -f -") cat >/dev/null; exit 0;;
'''),
  (TEST, '''  local path=$PATH; PATH="$W/no-openssl:$PATH"; refused_clean "openssl fails: a Secret of empty passwords"; PATH=$path; remove_ours
}
''', '''  local path=$PATH; PATH="$W/no-openssl:$PATH"; refused_clean "openssl fails: a Secret of empty passwords"; PATH=$path; remove_ours
  # apply-bind-user.sh's proof, on the same server: the control, then each read that fails.
  mkdir -p "$W/secrets/keycloak/cmapi-ldap-bind"
  "$SRC/apply-bind-user.sh" >"$W/out" 2>&1; rc=$?; [ "$rc" = 0 ] && ok "apply-bind-user.sh passes on this server: the control" || bad "apply-bind-user.sh, the control: rc $rc: $(tail -3 "$W/out")"
  tool_fails ldapsearch '*userPassword*'
  "$SRC/apply-bind-user.sh" >"$W/out" 2>&1; rc=$?; [ "$rc" != 0 ] && ok "apply-bind-user.sh: a read for a password hash that fails is not zero hashes" || bad "apply-bind-user.sh passed a failed read for a password hash"
  tool_back ldapsearch
  tool_fails ldapsearch '*-b?ou=TrustedApplications*'
  "$SRC/apply-bind-user.sh" >"$W/out" 2>&1; rc=$?; [ "$rc" != 0 ] && ok "apply-bind-user.sh: a read of ou=TrustedApplications that fails otherwise than 32 is not proof it is hidden" || bad "apply-bind-user.sh passed a failed read of ou=TrustedApplications"
  tool_back ldapsearch
}
'''))

def apply_edits(tree, edits):
    for path, old, new in edits:
        p = f"{tree}/{path}"; s = open(p, newline="").read()
        n = s.count(old)
        assert n == 1, f"{path}: {n} matches for {old[:90]!r}"
        open(p, "w", newline="").write(s.replace(old, new))

def main():
    only = int(sys.argv[1]) if len(sys.argv) > 1 else len(PATCHES)
    os.makedirs(FINAL, exist_ok=True)
    for f in os.listdir(FINAL):
        if f.endswith(".patch"): os.remove(f"{FINAL}/{f}")
    prev = f"{WORK}/p0"
    for i, (name, edits) in enumerate(PATCHES[:only], 1):
        cur = f"{WORK}/p{i}"
        shutil.rmtree(cur, ignore_errors=True)
        subprocess.run(["cp", "-a", prev, cur], check=True)
        apply_edits(cur, edits)
        files = sorted({e[0] for e in edits})
        out = []
        for path in files:
            r = subprocess.run(["diff", "-u", "--label", f"a/{path}", "--label", f"b/{path}", f"{prev}/{path}", f"{cur}/{path}"], capture_output=True)
            assert r.returncode == 1, (path, r.returncode, r.stderr)
            out.append(r.stdout)
        open(f"{FINAL}/{name}.patch", "wb").write(b"".join(out))
        print(f"{name}.patch: {len(files)} files, {sum(o.count(b'\n') for o in out)} lines")
        prev = cur

main()
