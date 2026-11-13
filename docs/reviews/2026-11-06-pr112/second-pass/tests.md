# Operated tests

MEASURED: cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass. `/usr/local/bin/podman info --format '{{.Host.RemoteSocket.Exists}}'`: stdout `true`, exit 0. Docker unavailable: `Cannot connect to the Docker daemon at unix:///Users/olasumbo/.docker/run/docker.sock. Is the docker daemon running?` No Docker tests.
MEASURED: export has no Git metadata (`/usr/bin/git -C head status --short`: exit 128, `fatal: not a git repository (or any of the parent directories): .git`). Historical byte identity cannot be inferred from Git here.

## C1

MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/claims-ldap.sh` (cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass, PATH begins with supplied venv; CONTAINER=/usr/local/bin/podman, KUBECONFIG empty). See logs/C1.log for commands, output and statuses.

## C6

MEASURED: cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass. `PYTHONPATH=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/head/cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/C6.py`: exit 0; output `legacy decode=/cmapi/cmapi-{name}; new encode=/corp/{name}; null requirement=None`. Full test: tests/C6.py.
MEASURED: `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python -m pytest -q /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/head/cmapi/tests/service/test_flow.py -k 'a_stored_requirement_keeps_its_group_path or an_open_request_keeps_the_path_it_was_decided_under'`, same cwd and PYTHONPATH, CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_secondpass_pr112, PATH begins with supplied venv. Output: `2 passed, 17 deselected, 28 warnings in 9.76s`; exit 0. Full log: logs/C6-service.log. Isolated database created and dropped with supplied venv's psycopg; no changes to shared cmapi database.

## C7

MEASURED: cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass. `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/python /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/C7.py`: exit 0. Output: `without extra CA: new vs reverse-patch-10 bundle cmp=identical`; `with extra CA: keycloak DER matches; ingress DER matches; bundle has 3 certificates`. The test records full /usr/local/bin/openssl, /usr/bin/patch and /bin/bash invocations in tests/C7.py and removes its generated certificates and private keys. No network TLS or system keychain operation.

## C2

MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/claims-ldap.sh` (cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass, PATH begins with supplied venv; CONTAINER=/usr/local/bin/podman, KUBECONFIG empty). See logs/C2.log for commands, output and statuses.

## C3

MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/claims-ldap.sh` (cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass, PATH begins with supplied venv; CONTAINER=/usr/local/bin/podman, KUBECONFIG empty). See logs/C3.log for commands, output and statuses.

## C4

MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/claims-ldap.sh` (cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass, PATH begins with supplied venv; CONTAINER=/usr/local/bin/podman, KUBECONFIG empty). See logs/C4.log for commands, output and statuses.

## C5

MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/claims-ldap.sh` (cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass, PATH begins with supplied venv; CONTAINER=/usr/local/bin/podman, KUBECONFIG empty). See logs/C5.log for commands, output and statuses.

## C5 direct-probe correction

MEASURED: the first standalone probe in logs/C5.log returned `ldap_bind: Invalid credentials (49)` because the review harness's here-string added a newline to the password file. It does not establish access-control behaviour. The real apply-bind-user.sh control uses the unmodified Secret file and exits 0, explicitly reporting `cannot read ou=TrustedApplications (ldapsearch exit): 32`. Its injected hash-read and TrustedApplications-read cases each exit 1 and report the intended ldapsearch exit 52. No production server was contacted.

## C2 and C3 regression results

MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/verify-fixes.sh`, cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass, uses /usr/local/bin/podman and the supplied venv first on PATH, empty KUBECONFIG. Full behavioural fixture is tests/fixture.sh; all LDAP operations go through /usr/local/bin/podman exec to OpenLDAP 2.4.57.
MEASURED C2: `assert_old_removal_atomic` against exported script: script exit 66, assertion exit 1, old groups + lookalikes remaining=3, requested DNs=10. Against proposed C2 script: script exit 1, assertion exit 0, remaining=12, requested DNs=0, reason `has child entries: none deleted. Stop and report to the directory owner`. Full output logs/C2-fix.log.
MEASURED C3: `assert_cut_failure_stops` against exported script: script exit 0, assertion exit 1, LDAP changed and Secret present. Against proposed C3 script: script exit 52, assertion exit 0, LDAP unchanged and Secret absent. Full output logs/C3-fix.log.
MEASURED: `/usr/bin/patch -p1 --fuzz=0 -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/patches/<ID>.patch` in report/work/apply-<ID>, for C2, C3 and C10: each exit 0. New regression files are present in each patch and byte-equal to proposed files. Logs: logs/C2-patch.log, logs/C3-patch.log, logs/C10-patch.log.

## C10

MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/verify-fixes.sh`, cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass, env in report/review_env.sh. The fixture runs /usr/local/bin/podman exec against real OpenLDAP and forwards all oc LDAP requests there; Kubernetes delete/get-pvc/label calls are intercepted and recorded. Test adds a normal directory-owned description after step 9 to model the extra server attribute, then runs step 10 and actual crc-rollback.sh --yes in that order. It does not claim to have installed a production schema or overlay.
MEASURED: output in logs/C10.log: step9 rc=0; step10 rc=1, LDAP deletes=0; unmodified rollback rc=1, simulated cluster deletes=32, LDAP deletes=0. Both remediation assertions fail (1). Proposed scripts: step10 rc=1, rollback rc=1, cluster deletes=0 and LDAP deletes=0; both assertions pass (0) and give directory-owner instructions.

## Exact added regressions, before and after

MEASURED: full regression files in patches were executed unchanged, with /bin/bash, supplied venv first on PATH, CONTAINER=/usr/local/bin/podman, TMPDIR=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/work, KUBECONFIG=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/empty-kubeconfig, cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass. Each before copy contains exported production code; each after copy contains only that claim's patch. The new tests are identical in the pair.

MEASURED C2: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/work/exact-tests/C2/before/deploy/tests/pr112-c2-regression.sh`: exit 1; full stdout/stderr logs/C2-exact-before.log.

MEASURED C2: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/work/exact-tests/C2/after/deploy/tests/pr112-c2-regression.sh`: exit 0; full stdout/stderr logs/C2-exact-after.log.

MEASURED C2: exact added behavioural test fails before (1), passes after (0). The matching fixtures own their uniquely labelled containers and remove them on exit.

MEASURED C3: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/work/exact-tests/C3/before/deploy/tests/pr112-c3-regression.sh`: exit 1; full stdout/stderr logs/C3-exact-before.log.

MEASURED C3: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/work/exact-tests/C3/after/deploy/tests/pr112-c3-regression.sh`: exit 0; full stdout/stderr logs/C3-exact-after.log.

MEASURED C3: exact added behavioural test fails before (1), passes after (0). The matching fixtures own their uniquely labelled containers and remove them on exit.

MEASURED C10: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/work/exact-tests/C10/before/deploy/tests/pr112-c10-regression.sh`: exit 1; full stdout/stderr logs/C10-exact-before.log.

MEASURED C10: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/work/exact-tests/C10/after/deploy/tests/pr112-c10-regression.sh`: exit 0; full stdout/stderr logs/C10-exact-after.log.

MEASURED C10: exact added behavioural test fails before (1), passes after (0). The matching fixtures own their uniquely labelled containers and remove them on exit.

MEASURED: `/usr/bin/patch -p1 --fuzz=0 -i /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/patches/<ID>.patch` in /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/work/combined, C2 then C3 then C10: each exit 0. `/bin/bash -n <each combined changed script and added test>`: all exit 0; full paths/output in logs/combined-patch.log.

## C9 failure-cause audit

MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/C9.sh`, cwd=/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass, env in report/review_env.sh, exit 0. This sources the named harness's functions and runs its real `the_failures` unmodified, adding output capture around run/refuses/tool_back only. Output: `ldap identity cases failed: 0, mutants survived: 0`; no mutants were run. Complete output logs/C9.log; each apply-test-identities invocation's full output and exit status are in logs/C9/run-<n>-rc-<status>.log.

| Cause named by case | MEASURED result and actual reason |
|---|---|
| sha256sum absent | run-1, exit 127: `sha256sum: not found` |
| sort failure | run-2, exit 52: `sort: failed for this case` |
| empty cut | run-3, exit 1: `cut: failed for this case`, `measurement others is empty` |
| gate-member grep failure | run-4, exit 1: `grep: failed for this case`, gate has no readable members |
| gate lacking member attribute | run-5, exit 1: gate has no readable members |
| failed hash read | run-6, exit 1: `ldapsearch: failed for this case`, could not check whether a password hash is readable |
| non-ASCII uidNumber holder | run-7, exit 1: `uidNumber 10105 is held by base64 ...` |
| non-ASCII stranger with a test UID | run-8, exit 1: `stranger base64 ...` |
| People-only bind ACL | run-9, exit 1: `No such object (32)`, bind user reads nothing under ou=Groups |
| new group with extra real member | run-11, exit 1: `different cn=app-cmapi-rbac-viewer`, old groups stay |
| missing test user | run-12, exit 1: `absent cn=cmapi.admin`, old groups stay |
| foreign person at test user's DN | run-14, exit 1: `different cn=cmapi.admin`, nothing deleted |
| real person added to new group before removal | run-16, exit 1: `different cn=app-cmapi-rbac-admin`, nothing deleted |
| failed host openssl | run-17, exit 1 with zero output bytes; separately instrumented invocation marker proves this quiet shim was reached |
| bind-user hash read | logs/C9.log: exit 1, ldapsearch exit 52 wanted 0 |
| bind-user TrustedApplications read | logs/C9.log: exit 1, ldapsearch exit 52 wanted 32 |

MEASURED: clean setup controls run-10, run-13 and run-15 each exit 0; bind-user control exits 0. Tool restoration completes and subsequent cases reach their distinct intended reasons. No syntax error or unhandled oc-stub call explains a refusal.
MEASURED: `/bin/bash /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/secondpass/report/tests/quiet-case-audit.sh`, same cwd/env, exit 0. Fresh uninjected creation exits 0, then cleanup; the quiet exit-1 openssl shim gains only an invocation marker. Output: `openssl_stub_invoked=yes script_output_bytes=0`, no Secret made, LDAP unchanged. Full log logs/quiet-case-audit.log. This establishes why the original openssl case has no explanatory stderr.

## C5 corrected direct probe

MEASURED: the same quiet-case-audit.sh invokes `/usr/local/bin/podman exec -i cmapi-secondpass-audit sh -c <program>` with the exact existing Secret file on stdin; the full command and program are in tests/quiet-case-audit.sh. Output `No such object (32)` and `C5 corrected direct exit=32`; host test exits 0. This corrects the earlier here-string newline error. An intermediate ad-hoc Python attempt had a SyntaxError before invoking LDAP and establishes nothing; the successful file-based probe is the evidence. Production was not contacted and remains unmeasured.

## Tool paths and cleanup

MEASURED: host executable resolution after report/review_env.sh is in logs/host-tools.log. The fixture prepends only its local oc-stub directory; Python still resolves to the supplied venv. The shell-specific C4 tests explicitly invoke /bin/dash and /bin/bash. Other host executables used by fixtures resolve to /usr/bin/awk, /usr/bin/cut, /usr/bin/mktemp, /usr/bin/grep, /usr/bin/sed, /usr/bin/sort, /usr/bin/shasum, /usr/local/bin/jq, /usr/local/bin/openssl and /usr/local/bin/podman. The real /usr/local/bin/oc was never invoked.
MEASURED: `/usr/local/bin/podman run --rm --label cmapi.review=secondpass-tools --entrypoint /bin/sh docker.io/osixia/openldap@sha256:18742e9c449c9c1afe129d3f2f3ee15fb34cc43e5f940a20f3399728f41d7c28 -c 'for tool in sh awk cut mktemp ldapsearch ldapadd ldapmodify ldapdelete ldapwhoami slappasswd sort sha256sum grep sed cat tr cmp; do command -v "$tool"; done'`: exit 0; full output logs/container-tools.log. Container tools resolve to /bin/sh, /usr/bin/awk, /usr/bin/cut, /bin/mktemp, /usr/bin/ldapsearch, /usr/bin/ldapadd, /usr/bin/ldapmodify, /usr/bin/ldapdelete, /usr/bin/ldapwhoami, /usr/sbin/slappasswd, /usr/bin/sort, /usr/bin/sha256sum, /bin/grep, /bin/sed, /bin/cat, /usr/bin/tr and /usr/bin/cmp. These are the full tool paths for the in-container commands recorded in the fixture and exact regression tests.
MEASURED: final `/usr/local/bin/podman ps -a --filter label=cmapi.review --format '{{.Names}} {{.Labels}}'`: exit 0, no output. All review-labelled containers removed. Final `/usr/bin/find report/work -maxdepth 2 -type d -name secrets -print`: exit 0, no output; fixture Secrets and password files cleaned. Isolated database was dropped (C6 log). No venv installation, real-cluster operation, commit or push. All retained files are under secondpass/report; no intentional external filesystem artifact remains.
MEASURED: total graph calls=8 (one status, two context, four failed read attempts, one search). Total shell tool calls=68 (54 exec_command launches, 14 write_stdin polls); GitHub read calls=3. Counts include this final report-write command.
