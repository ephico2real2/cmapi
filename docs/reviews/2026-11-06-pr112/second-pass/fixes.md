# Defects and proposed repairs

## C3 — a failed cut can certify measurements and permit every write

MEASURED: on the exported head, cut printed a nonempty constant then exited 52 four times, yet the script exited 0, created 13 users, 10 groups and the Secret, and reported identical zero digests. logs/C3.log.
READ FROM CODE: the echo commands at examples/cmapi-sso/ldap/apply-test-identities.sh:121,128 replace the command-substitution exit status with echo's success. The nonempty-field checks cannot detect this.
PROPOSAL NOT OPERATED: patch patches/C3.patch changes only the two cut assignments plus adds the complete regression below. Full changed production code, path examples/cmapi-sso/ldap/apply-test-identities.sh (each pair replaces the respective echo):

```sh
  others=$(cut -d" " -f1 "$w/canon-sum")
  echo "others=$others"

  gate=$(cut -d" " -f1 "$w/gate-sum")
  echo "gate=$gate"
```

PROPOSAL NOT OPERATED: complete added test, path deploy/tests/pr112-c3-regression.sh; CONTAINER=/usr/local/bin/podman, TMPDIR inside this report/work when operated here:

```bash
#!/usr/bin/env bash
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SOURCE=$ROOT/deploy/tests/ldap-identities-test.sh
# Reuse the real LDAP fixture without executing its all/failures dispatch.
# The source is trusted repository code; no result is asserted from its text.
eval "$(python3 - "$SOURCE" <<'PYCODE'
import sys
s = open(sys.argv[1]).read().split("# ---- no container needed")[0]
s = s.replace('HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd); SRC=$ROOT/examples/cmapi-sso/ldap', 'SRC=$ROOT/examples/cmapi-sso/ldap')
s = s.replace('NAME=cmapi-w1-lt-ldap; LABEL=cmapi.test=ldap-identities;', 'NAME=cmapi-pr112-review-$$; LABEL=cmapi.review=pr112-$$;')
print(s)
PYCODE
)"
start groupOfNames

in_c sh -c '
p=$(command -v cut); mv "$p" "$p.real"; echo "$p" >/tmp/lt-cut
printf "#!/bin/sh\ncase \"\$*\" in *-f1*) echo 0000000000000000000000000000000000000000000000000000000000000000; echo cut-partial-failure >&2; exit 52;; esac\nexec %s \"\$@\"\n" "$p.real" >"$p"; chmod +x "$p"' || exit 1
before=$(everything); rc=$(run); after=$(everything)
printf 'rc=%s ldap_unchanged=%s secret_absent=%s\n' "$rc" "$([ "$before" = "$after" ] && echo yes || echo no)" "$([ ! -d "$W/secrets/cmapi/cmapi-ldap-test-users" ] && echo yes || echo no)"
grep -E 'cut-partial|rest of the directory|FAIL:' "$W/out"
[ "$rc" != 0 ] && [ "$before" = "$after" ] && [ ! -d "$W/secrets/cmapi/cmapi-ldap-test-users" ]
```

MEASURED: the identical assertion and injection in tests/verify-fixes.sh return 1 before and 0 after; script exits 0 before and 52 after, LDAP changes before and stays byte-for-byte equal by the independent digest after, Secret present before and absent after. logs/C3-fix.log. Patch applies at fuzz 0 (logs/C3-patch.log).

## C2 — a nonleaf old group permits earlier irreversible deletions (additional attack)

MEASURED: with a child under the final old group, nine earlier groups are deleted before ldapdelete exits 66. The child and its group remain; the script cannot restore the other nine. logs/C2.log.
READ FROM CODE: remove_old validates each old entry's objectClass but not whether all target DNs are leaves before delete_exact sends the batch. Recursive deletion would remove unowned children and is not an acceptable repair.
PROPOSAL NOT OPERATED: patches/C2.patch adds a read-only child check for every existing old group before the batch, and a complete behavioural regression. Full replacement function, path examples/cmapi-sso/ldap/apply-test-identities.sh:

```sh
remove_old() {
  dns=$tmp/old-dns; : > "$dns"
  for cn in $old_groups; do group_dn "$cn" >> "$dns"; echo >> "$dns"; done
  in_pod "$lib"'
    while read -r dn; do
      present "$dn" || { echo "gone already: $dn"; continue; }
      search -b "$dn" -s base objectClass > "$w/e"
      grep -qix "objectClass: groupOfNames" "$w/e" || { echo "FAIL: $dn is not a groupOfNames: leaving every entry alone" >&2; exit 1; }
      search -b "$dn" -s one "(objectClass=*)" dn > "$w/children"
      if [ -s "$w/children" ]; then
        echo "FAIL: $dn has child entries: none deleted. Stop and report to the directory owner; move or remove the children only after ownership review, then rerun --remove-old-groups" >&2
        exit 1
      fi
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
```

PROPOSAL NOT OPERATED: full added test, path deploy/tests/pr112-c2-regression.sh:

```bash
#!/usr/bin/env bash
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SOURCE=$ROOT/deploy/tests/ldap-identities-test.sh
# Reuse the real LDAP fixture without executing its all/failures dispatch.
# The source is trusted repository code; no result is asserted from its text.
eval "$(python3 - "$SOURCE" <<'PYCODE'
import sys
s = open(sys.argv[1]).read().split("# ---- no container needed")[0]
s = s.replace('HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd); SRC=$ROOT/examples/cmapi-sso/ldap', 'SRC=$ROOT/examples/cmapi-sso/ldap')
s = s.replace('NAME=cmapi-w1-lt-ldap; LABEL=cmapi.test=ldap-identities;', 'NAME=cmapi-pr112-review-$$; LABEL=cmapi.review=pr112-$$;')
print(s)
PYCODE
)"
start groupOfNames

rc=$(run); [ "$rc" = 0 ] || { tail -3 "$W/out"; exit 1; }
printf 'dn: cn=child,cn=cmapi-auditors,ou=Groups,%s\nobjectClass: organizationalRole\ncn: child\n\n' "$BASE" | adm ldapadd >/dev/null || exit 1
rc=$(run --remove-old-groups)
left=$(count "ou=Groups,$BASE" '(cn=cmapi-*)')
printf 'rc=%s old_groups_and_lookalikes=%s deletes_requested=%s\n' "$rc" "$left" "$(wc -l <"$LT_DELETES" | tr -d ' ')"
tail -4 "$W/out"
[ "$rc" != 0 ] && [ "$left" = 12 ] && [ ! -s "$LT_DELETES" ]
```

MEASURED: the identical assertion in tests/verify-fixes.sh fails before (assertion 1, script 66, nine deleted) and passes after (assertion 0, script 1, none deleted); logs/C2-fix.log. Patch applies at fuzz 0 (logs/C2-patch.log). The preflight does not lock the DIT; concurrent child creation remains a race and is outside this demonstrated deterministic failure.

## C10 — most important finding: rollback deletes infrastructure before a predictable LDAP refusal

MEASURED: step 9 exits 0. A directory-owned description on one newly created group makes step 10 exit 1 with zero LDAP delete requests. The unmodified rollback then issues 32 simulated Kubernetes delete calls before the same LDAP ownership check refuses; it reports `nothing deleted` from the inner script without explaining the prior infrastructure deletion. Neither refusal gives actionable ownership-review guidance. No real Kubernetes operation occurred. logs/C10.log.
READ FROM CODE: examples/cmapi-sso/ldap/apply-test-identities.sh:172-174 deliberately treats extra normal attributes as a mismatch. Keep that protection. deploy/crc-rollback.sh:29-57 reaches LDAP only after removing workloads, database objects, Secrets and roles. docs/13-crc-deployment.md:228,528 describes a rollback that takes step 9's additions away, but this state cannot be removed automatically.
PROPOSAL NOT OPERATED: patches/C10.patch adds a read-only preflight before any rollback deletion and explicit instructions to stop, report the DNs, and have the directory owner review extra attributes. It preserves mismatched entries and repeats the checks at actual LDAP removal. This is not a transaction or a directory lock. Full changed code, path examples/cmapi-sso/ldap/apply-test-identities.sh:

```sh
case "${1:-}" in
  "") ;;
  --remove-old-groups) mode=remove-old ;;
  --remove-test-identities) mode=remove-new ;;
  --check-remove-test-identities) mode=check-remove-new ;;
  *) echo "unknown argument: $1. Nothing done" >&2; exit 2 ;;
esac

check_remove_new() {
  # An entry at one of these names that is not what the first form writes is somebody's, as the first form says when it refuses to touch it. A cmapi.* stranger is not on the list, and stays.
  read_state
  if grep -q '^different ' "$tmp/state"; then
    grep '^different ' "$tmp/state" | sed 's/^/FAIL: /' >&2
    die "an entry with one of cmapi's names differs: nothing deleted. Stop and report the listed DNs to the directory owner. Review the attributes and their ownership before retrying; do not strip attributes or delete entries to force rollback"
  fi
}

remove_new() {
  check_remove_new
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
  check-remove-new)
    check_remove_new
    measure "$tmp/ours" 0 > "$tmp/removal-check"
    echo "ok   LDAP removal preflight: no entries or Secrets written or deleted"
    exit 0 ;;
esac
```

PROPOSAL NOT OPERATED: full replacement remove_old (same path; the guidance change is included):

```sh
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
    die "the new groups and test users are not all in place as this script writes them: the old groups stay, none deleted. Stop and report the listed DNs to the directory owner. Review any extra attributes and their ownership; do not strip attributes or delete entries to force migration"
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
```

PROPOSAL NOT OPERATED: full replacement path deploy/crc-rollback.sh:

```bash
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

# Check LDAP ownership and measurements before deleting workloads, storage, or a realm.
# The actual removal below repeats the checks; this is a preflight, not a lock.
"$HERE/../examples/cmapi-sso/ldap/apply-test-identities.sh" --check-remove-test-identities

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
```

PROPOSAL NOT OPERATED: documentation replacements are supplied in full in patches/C10.patch, path docs/13-crc-deployment.md (step 10 and Rollback). Full added behavioural test, path deploy/tests/pr112-c10-regression.sh:

```bash
#!/usr/bin/env bash
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SOURCE=$ROOT/deploy/tests/ldap-identities-test.sh
# Reuse the real LDAP fixture without executing its all/failures dispatch.
# The source is trusted repository code; no result is asserted from its text.
eval "$(python3 - "$SOURCE" <<'PYCODE'
import sys
s = open(sys.argv[1]).read().split("# ---- no container needed")[0]
s = s.replace('HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd); SRC=$ROOT/examples/cmapi-sso/ldap', 'SRC=$ROOT/examples/cmapi-sso/ldap')
s = s.replace('NAME=cmapi-w1-lt-ldap; LABEL=cmapi.test=ldap-identities;', 'NAME=cmapi-pr112-review-$$; LABEL=cmapi.review=pr112-$$;')
print(s)
PYCODE
)"
start groupOfNames

rc=$(run); [ "$rc" = 0 ] || { tail -3 "$W/out"; exit 1; }
adm ldapmodify >/dev/null <<LDIF
dn: cn=app-cmapi-rbac-viewer,ou=Groups,$BASE
changetype: modify
add: description
description: set by directory policy
LDIF
rc=$(run --remove-old-groups)
step_ok=0
[ "$rc" != 0 ] && [ ! -s "$LT_DELETES" ] && grep -q 'Stop and report' "$W/out" && step_ok=1
printf 'step10 rc=%s no_deletes_and_guidance=%s\n' "$rc" "$step_ok"
tail -3 "$W/out"
export LT_CLUSTER_DELETES="$W/cluster-deletes" LT_LDAP_OC="$W/bin/ldap-oc"
mv "$W/bin/oc" "$LT_LDAP_OC"
cat >"$W/bin/oc" <<'OC'
#!/bin/bash
case "$*" in
 'delete '*) printf '%s\n' "$*" >>"$LT_CLUSTER_DELETES"; exit 0;;
 'get pvc '*) exit 0;;
 'label namespace '*) exit 0;;
esac
exec "$LT_LDAP_OC" "$@"
OC
chmod +x "$W/bin/oc"
: >"$LT_CLUSTER_DELETES"; : >"$LT_DELETES"
"$ROOT/deploy/crc-rollback.sh" --yes >"$W/out" 2>&1; rc=$?
printf 'rollback rc=%s cluster_deletes=%s ldap_deletes=%s\n' "$rc" "$(wc -l <"$LT_CLUSTER_DELETES" | tr -d ' ')" "$(wc -l <"$LT_DELETES" | tr -d ' ')"
tail -3 "$W/out"
[ "$step_ok" = 1 ] && [ "$rc" != 0 ] && [ ! -s "$LT_CLUSTER_DELETES" ] && [ ! -s "$LT_DELETES" ] && grep -q 'Stop and report' "$W/out"
```

MEASURED: the identical assertions in tests/verify-fixes.sh fail before (step-10 assertion 1; rollback assertion 1; 32 simulated Kubernetes deletes, zero LDAP deletes) and pass after (both assertions 0; zero Kubernetes and LDAP deletes; owner-review guidance present). logs/C10.log. Patch applies at fuzz 0 and contains its new test (logs/C10-patch.log).

MEASURED: the exact added tests printed in this file and shipped in the patches have now each been run unchanged against the exported production code and against their own repair. C2: exit 1 before / 0 after. C3: exit 1 before / 0 after. C10: exit 1 before / 0 after. Full commands are in tests.md and outputs in logs/*-exact-{before,after}.log. All patches also apply together with --fuzz=0; combined scripts and test files pass /bin/bash -n. No repair was applied to the exported head.
