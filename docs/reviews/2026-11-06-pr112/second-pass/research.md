# Source evidence

MEASURED: tokensave_status reports fallback main, last_sync_at=1794013348. No index was refreshed.
MEASURED: four tokensave_read calls for the two named exported scripts failed with the exact error: `Mcp error: -32602: invalid selected graph arguments: selected tokensave_read path '/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/head/examples/cmapi-sso/ldap/apply-test-identities.sh' resolves outside selected graph root '/Users/olasumbo/gitRepos/cmapi-design-crc'; choose a file inside that root` (the other path was deploy/tests/ldap-identities-test.sh). Exported source inspection falls back to shell.
READ FROM CODE: docs/reviews/2026-11-06-pr112/README.md:51-62 reports earlier proof results and explicitly calls the production exit-32 behaviour inferred. These are historical reports, not this run's measurements.

## C1

READ FROM CODE: head/examples/cmapi-sso/ldap/apply-test-identities.sh:159-184 builds expected user/group records and counts each state. Lines 227-229: `if grep -q '^different '` refuses before deletion; absent records do not refuse. Lines 231-239 measure before/after and delete the Secret last. Passwords are deliberately excluded from structural comparison at line 172.

## C2

READ FROM CODE: head/examples/cmapi-sso/ldap/apply-test-identities.sh:205-209 refuses any new state except `same`. Lines 187-190: `No -r, no filter` and `ldapdelete -x` directly contradict recursive deletion in the brief. Old-entry preflight checks objectClass, not whether entries have children (197-203).

## C3

READ FROM CODE: head/examples/cmapi-sso/ldap/apply-test-identities.sh:116,119-121 invokes awk, sort and sha256sum as simple commands under `set -eu`; however line 121 `echo "others=$(cut ...)"` and line 128's gate equivalent discard the cut exit status. Lines 136-137 validate nonempty measurement fields, which covers empty-output cut failure only.

## C4

READ FROM CODE: head/examples/cmapi-sso/ldap/apply-test-identities.sh:300-306 keeps openssl in a simple command inside the last process of a pipeline; the piped while's failure propagates to the parent under `set -e`, before Secret creation. LDAP additions begin at 310.

## C5

READ FROM CODE: head/examples/cmapi-sso/ldap/apply-bind-user.sh:115-119 checks ldapsearch exits 0 and 32 separately from hash counts. docs/reviews/2026-11-06-pr112/README.md:61 calls production's 32 inferred, not measured.

## C6

READ FROM CODE: head/cmapi/src/cmapi/core/authz.py:47-50 defines distinct DEFAULT_GROUP_PATH and LEGACY_GROUP_PATH. head/cmapi/src/cmapi/core/db/repo.py:33-46 writes `"groupPath": r.group_path` for every non-null serialized Requirement and uses `d.get("groupPath", LEGACY_GROUP_PATH)` when decoding. `None` serializes as SQL/JSON absence, not a requirement. RequestRepo.insert at 135-140 accepts a supplied row without checking or normalizing its requirement; this is a scoped bypass path if a caller supplies an old-shaped dict. No claim about uninspected external callers is made.
MEASURED: GitHub fetch_file for ephico2real2/cmapi, ref main, cmapi/src/cmapi/core/authz.py:40-55 returns GROUP_PATH = "/cmapi/cmapi-{name}" (blob 8bf72901115bd698b2507d39f2aa2c69cef9b007). This equals exported LEGACY_GROUP_PATH.

## C7

READ FROM CODE: head/deploy/crc-trust.sh:33-38 writes Keycloak's CA before extra CA; lines 80-86 selects the first certificate for keycloak-ca.pem and retains the entire trust bundle in output. Supplied patch 10 contains the exact old mac_ca implementation for reverse-patch comparison.

## C9

READ FROM CODE: head/deploy/tests/ldap-identities-test.sh:127-130 (`refuses`) only requires nonzero status and equal directory digests; 306-308 adds no Secret. 314-385 (`the_failures`) injects real container failures, restores tools and cleans directory state. Some cases also match reasons (327,332,335,338), while other cases accept any failure. `tool_fails` at 298-303 generates shell shims; its case patterns contain no literal unquoted spaces. Current measurements retain every run's reason in logs/C9/, and direct bind-user reasons in logs/C9.log.

## C10

READ FROM CODE: head/docs/13-crc-deployment.md:222 invokes creation in step 9, 235 invokes old-group removal in step 10, and 523 invokes crc-rollback.sh --yes. 228 promises removal after a stop; 528 promises it refuses mismatched entries. `apply-test-identities.sh:172-174` compares every non-password normal attribute with its expected LDIF, so a directory-owned description on a new group makes it different. Lines 206-209 and 227-229 refuse migration and LDAP removal but give no recovery or ownership-review instructions.
READ FROM CODE: head/deploy/crc-rollback.sh:29-55 deletes workloads, storage and other named objects before line 57 checks whether LDAP removal is allowed. This ordering makes a known LDAP refusal occur after unrelated rollback deletions.
PROPOSAL NOT OPERATED: preserve differing attributes; add a read-only LDAP ownership/measurement preflight before any rollback deletes, repeat checks at actual removal, and give explicit owner-review instructions. A preflight is not a lock and cannot guarantee atomicity under a concurrent directory edit.

MEASURED C9: every nonzero result was examined, rather than relying on the harness's final exit status. The openssl shim intentionally emits no reason; a separate marker proves its invocation on clean state. See tests.md's per-case table.
READ FROM CODE: source requirement issue #110 (https://github.com/ephico2real2/cmapi/issues/110) requires ten role groups, 13 isolated test users and unchanged other LDAP entries. Issue #109 (https://github.com/ephico2real2/cmapi/issues/109) requires trusting only CA certificates and clearing trust settings on removal. GitHub fetch_issue returned both bodies; these are requirements, not runtime proof.
