# Wave 1 adversarial review — reviewer 1

## Finding 1 — CRITICAL — watch can die without the stop file

`repo/deploy/crc-guard.py:86`

An HTTP 503 whose declared body is cut short enters the `HTTPError` handler, then `e.read()` raises `IncompleteRead`. That exception is raised inside the handler, so the later `except http.client.HTTPException` cannot catch it. `watch` exits and leaves no stop file; a later `gate` can pass during the outage.

Command and output:

```text
$ python3 output/tests/crc_guard_incomplete_error_test.py repo/deploy/crc-guard.py
watch=crashed: IncompleteRead stop_file=False
rc=1
```

Exact fix:

```python
except urllib.error.HTTPError as e:
    try:
        return e.code, e.read()
    except (http.client.HTTPException, OSError, ValueError):
        return 0, b""
```

Patch: [`fixes/guard-incomplete-http-error.patch`](fixes/guard-incomplete-http-error.patch)

Regression test: [`tests/crc_guard_incomplete_error_test.py`](tests/crc_guard_incomplete_error_test.py)

After the patch:

```text
BREACH, the run is stopped: corp=0
watch=3 stop_file=True
rc=0
```

## Finding 2 — HIGH — a 404 for another realm authorizes minting

`repo/deploy/secrets.sh:32`

`--issuer` is not constrained to realm `cmapi`. Passing `https://keycloak.test/realms/not-cmapi` and receiving Keycloak's genuine absent-realm 404 causes the script to mint and create cmapi's three Secrets, even if the real `/realms/cmapi` exists.

Command and output:

```text
$ python3 output/tests/secrets_wrong_issuer_test.py repo/deploy/secrets.sh
rc=0 creates=3
test rc=1
```

Exact fix, before any reads or generation:

```bash
if [ "$ISSUER_CHECK" = true ]; then
  case "$ISSUER" in */realms/cmapi) ;; *) echo "ERROR: --issuer must name realm cmapi exactly: <Keycloak base>/realms/cmapi" >&2; exit 2;; esac
fi
```

Patch: [`fixes/secrets-require-cmapi-issuer.patch`](fixes/secrets-require-cmapi-issuer.patch)

Regression test: [`tests/secrets_wrong_issuer_test.py`](tests/secrets_wrong_issuer_test.py)

After the patch:

```text
rc=2 creates=0
ERROR: --issuer must name realm cmapi exactly: <Keycloak base>/realms/cmapi
test rc=0
```

## Finding 3 — HIGH — broken service is accepted as NetworkPolicy enforcement

`repo/deploy/crc-proof.sh:62`

The negative probe accepts every nonzero `oc exec ... wget` as proof of blocking. The full stubbed proof passes when that command fails with `wget: bad address 'cmapi-api.cmapi.svc'`; the service is broken, not blocked. The pinned BusyBox probe reports `wget: download timed out` for the OVN drop being proved.

Command and output:

```text
$ python3 output/tests/crc_proof_broken_probe_test.py repo/deploy/crc-proof.sh
rc=0
...
proof: another namespace's pod reaches the mockup and is blocked from the api ...
proof: all passed
test rc=1
```

Exact fix:

```bash
if blocked=$(oc_ exec np-probe -n "$probe_ns" -- wget -q -O /dev/null --timeout=5 http://cmapi-api.cmapi.svc:8080/readyz 2>&1 >/dev/null); then
  fail "another namespace reaches 8080: the policy is not enforced"
fi
case "$blocked" in
  *"wget: download timed out"*) ;;
  *) fail "the api probe failed for another reason, not a policy timeout: ${blocked:0:200}";;
esac
```

Patch: [`fixes/proof-require-policy-timeout.patch`](fixes/proof-require-policy-timeout.patch)

Regression test: [`tests/crc_proof_broken_probe_test.py`](tests/crc_proof_broken_probe_test.py)

After the patch:

```text
rc=1
FAIL: the api probe failed for another reason, not a policy timeout: wget: bad address 'cmapi-api.cmapi.svc'
test rc=0
```

## Finding 4 — CRITICAL — printed stops return success and the run continues

`repo/docs/13-crc-deployment.md:78`, `:114`, `:153`, `:179`, `:235`, `:257`, `:284`, `:293`

The instructed shell omits `errexit`. Several failures end in successful `echo STOP`; the many `&&` lists also suppress `errexit` for non-final commands. The final watch line is displayed but never checked. A failed guard, issuer check, pull-secret wait, rollout, proof, or watch can therefore be followed by a later mutating step.

Command and output:

```text
$ python3 output/tests/runbook_stops_test.py repo/docs/13-crc-deployment.md
FAIL errexit enabled
FAIL no successful echo STOP branch
FAIL no successful rollout STOP branch
FAIL service-account stop exits
FAIL final watch line is asserted
FAIL every guarded AND-list exits
FAIL trust AND-list exits
FAIL image AND-list exits
rc=1
```

Exact fix pattern, applied to every run-step AND-list in the patch:

```bash
set -euo pipefail
$G gate "$STOP" && <the step> || exit $?
```

Expected nonzero issuer and explicit stop branches become:

```bash
$G issuer && rc=0 || rc=$?
[ "$rc" = 10 ] && echo "absent: go on" || { echo STOP; exit 1; }
```

The watch ending becomes:

```bash
touch "$RUN/watch.log.done"; sleep 10
last=$(tail -1 "$RUN/watch.log"); echo "$last"
case "$last" in *"watch ended rc=0") ;; *) echo "STOP: watch did not end cleanly"; exit 1;; esac
```

Patch with every affected command: [`fixes/runbook-enforce-stops.patch`](fixes/runbook-enforce-stops.patch)

Regression test: [`tests/runbook_stops_test.py`](tests/runbook_stops_test.py)

After the patch:

```text
ok errexit enabled
ok no successful echo STOP branch
ok no successful rollout STOP branch
ok service-account stop exits
ok final watch line is asserted
ok every guarded AND-list exits
ok trust AND-list exits
ok image AND-list exits
rc=0
```

## Non-finding checks

Claim 2 command:

```bash
python3 - <<'PY'
from pathlib import Path
import re
s=Path('repo/deploy/crc-rollback.sh').read_text()
deletes='\n'.join(line for line in s.splitlines() if re.search(r'(^|[ ;])(del|oc_ delete) ', line))
paths=re.findall(r'-X DELETE "\$KC([^" ]+)"', s)
print('realm_delete_paths='+repr(paths))
print('banned_names_in_deletes='+repr([x for x in ('inkcast','corp','group-sync','cmapi-ldap-bind') if x in deletes]))
print('broad_delete_flags='+repr([x for x in ('--all','--selector','--prune') if x in deletes]))
assert paths == ['/admin/realms/cmapi']
assert not any(x in deletes for x in ('inkcast','corp','group-sync','cmapi-ldap-bind','--all','--selector','--prune'))
PY
```

```text
realm_delete_paths=['/admin/realms/cmapi']
banned_names_in_deletes=[]
broad_delete_flags=[]
```

Claim 3 command, using `registry.redhat.io/rhel9/postgresql-16:latest` in container `cmapi-codex-backup`, removed by the test:

```text
$ python3 output/tests/crc_backup_image_test.py repo/deploy/crc-backup.sh
success_rc=0 dumps=1 full_path_leaked=False
partial_rc=1 leftovers=0
```

The image reported `pg_dump (PostgreSQL) 16.15` and `pg_restore (PostgreSQL) 16.15`. Test: [`tests/crc_backup_image_test.py`](tests/crc_backup_image_test.py).

Claim 5 command and output (the loader supplies only a fake `httpx` module so the named predicate can be called without installing dependencies):

```bash
python3 - <<'PY'
import importlib.util, sys, types
sys.modules['httpx'] = types.ModuleType('httpx')
spec = importlib.util.spec_from_file_location('realm_sync', 'repo/cmapi/src/cmapi/tools/realm_sync.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class R:
    def __init__(self, status, body): self.status_code=status; self.body=body
    def json(self):
        if isinstance(self.body, Exception): raise self.body
        return self.body
for status, body in [(500, {'added': 1}), (200, {'failed': 1, 'added': 1}), (200, {'failed': 0, 'added': 0, 'updated': 0}), (200, ValueError('bad'))]:
    print(status, type(body).__name__, m._sync_read_someone(R(status, body)))
PY
awk '/^  name:|^  namespace:|^    realm:|secret:/{print NR ":" $0}' repo/deploy/manifests/environments/crc/realm/10-realm-import.yaml
awk '/backoffLimit:|restartPolicy:|requireSync/{print NR ":" $0}' repo/deploy/manifests/environments/crc/realm/20-realm-sync.yaml
```

```text
500 dict False
200 dict False
200 dict False
200 ValueError False
11:  name: cmapi
12:  namespace: keycloak
28:      secret:
32:      secret:
36:      secret:
40:      secret:
44:    realm: cmapi
302:      secret: ${CMAPI_AUTOMATION_SECRET}
316:      secret: ${CMAPI_SVC_PAYMENTS_CI_SECRET}
331:      secret: ${CMAPI_DIRECTORY_SECRET}
342:      secret: ${CMAPI_REALM_ADMIN_SECRET}
4:# a Job's template is immutable. requireSync: a federation that did not sync fails the Job, not only a log line.
12:  backoffLimit: 0
19:      restartPolicy: Never
39:              value: '{"bindSecret":"cmapi-ldap-bind","connectionUrl":"ldaps://ldaps-ldap-testing.apps-crc.testing:443","employeeIdAttribute":"uidNumber","enabled":true,"groupsDn":"ou=Groups,dc=ephico2real,dc=com","groupsFilter":"(cn=cmapi-*)","requireSync":true,"usersDn":"ou=People,dc=ephico2real,dc=com"}'
```

The shipped guard suite also completed successfully:

```text
$ python3 repo/deploy/tests/crc-guard-test.py repo/deploy/crc-guard.py --no-mutants >/dev/null; echo guard_suite_rc=$?
guard_suite_rc=0
```

## Unproven worries

- None beyond the runbook's own “Not proven before the run” list.

## Seven verdicts

1. **REFUTED** — incomplete HTTP error body kills `watch` without the stop file.
2. **NOT REFUTED** — exact-name audit found no route to `inkcast`, `corp`, group-sync, or `cmapi-ldap-bind`; realm DELETE is fixed to `cmapi`.
3. **NOT REFUTED** — real Red Hat PostgreSQL 16.15 success and forced-partial-dump runs behaved as claimed.
4. **REFUTED** — another realm's genuine 404 authorizes cmapi secret minting.
5. **NOT REFUTED** — only realm `cmapi`, no literal secret, and required federation failure exits the Job.
6. **REFUTED** — a DNS-broken API service is reported as policy enforcement.
7. **REFUTED** — stop branches can return success and later steps continue.

## Not tested

No command contacted CRC or any Kubernetes server. I did not exercise real RHBK import behavior, real realm deletion, LDAP, OVN, Routes, Prometheus, Chrome, or the shared `postgres-0`; PostgreSQL testing used only the named throwaway container bound on `127.0.0.1` and removed afterward.
