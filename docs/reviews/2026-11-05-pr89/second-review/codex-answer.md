# Adversarial review of PR #89 at `d6c063e` — reviewer 1

Six findings are proven. Each fix below is a standalone patch against `d6c063e`; all six returned `0` from `patch -p1` on separate clean copies of `repo/`. I also applied all six together to a clean copy: every patch applied, ShellCheck passed on the changed shell files, `render-test.sh` ended with `render cases failed: 0`, `doc12-test.py` ended with `doc cases failed: 0`, and the two changed manifest guards passed.

## Finding 1 — Medium — `deploy/render.sh:49-59`: a failed render destroys the last good render and leaves a marked partial tree

**The failure.** Start with a successful output directory, then add an unfillable `CMAPI_CONFIG_CHECKSUM` placeholder in a `.yml` file. `render.sh` deletes the successful output at line 49, creates `.cmapi-render`, copies and edits into that live directory, and only discovers the leftover placeholder at lines 56-57. It exits nonzero, but the previous `IMAGE` and sentinel file are gone and the partial directory has the marker that authorizes replacement. A release step which mishandles the exit status can consume or commit that partial tree.

The checksum itself covers the three current files the pods read. `repo/deploy/render-test.sh` returned `render cases failed: 0`: changes to each of `10-env`, `20-config`, and `30-trust` changed both Deployment annotations; two renders and another checkout were identical; a leftover placeholder failed; and the portal/mockup was unchanged. I found no current target-ConfigMap byte change that leaves the checksum unchanged. The defect is publication atomicity.

**Evidence.** Complete test: [`tests/test-render-atomic.sh`](tests/test-render-atomic.sh). Command and output:

```text
$ output/tests/test-render-atomic.sh repo
FAIL failed render rc=1 replaced the last good output; files: .cmapi-render
before_rc=1

$ output/tests/test-render-atomic.sh output/apply-check-render-atomic
PASS failed render rc=1 preserved the last good output
after_rc=0
```

**The full fix.** Complete exact patch, including the regression added to `render-test.sh`: [`fixes/render-atomic.patch`](fixes/render-atomic.patch). It renders into a sibling temporary directory, checks it, writes `IMAGE`, then renames it into place. The EXIT trap restores the old tree if the swap is interrupted. It also refuses a broken symlink as an output.

## Finding 2 — Medium — `deploy/secrets.sh:53-135`: late read/partial-object failures happen after three Secrets are minted

**The failure.** With both realm copies, `cmapi-keys`, and LDAP checks absent/disabled, but an existing `cmapi-github-app` with empty `data`, the script reconciles the realm first and creates:

1. `sect2/cmapi-realm-secrets`,
2. `sect1/cmapi-keycloak`, and
3. `sect1/cmapi-keys`.

Only then does line 123 read the empty App Secret and lines 124-127 stop. A failure of that late read has the same ordering. Thus an existing empty Secret does not generally “stop without a write”; the existing test only proves this for the two realm-copy Secrets, which are read first. The specific `cmapi-keycloak`-empty/no-realm-copy case is sound, but the broader claim is not. This does not reopen ruling 7's deleted-import/deleted-Secrets case.

**Evidence.** Complete test: [`tests/test-secrets-preflight.sh`](tests/test-secrets-preflight.sh). It uses only the repository stub and dummy objects.

```text
$ TEST_PYTHON=output/venv/bin/python output/tests/test-secrets-preflight.sh repo
FAIL empty late Secret stopped rc=1 only after 3 other Secrets were written
before_rc=1

$ TEST_PYTHON=output/venv/bin/python output/tests/test-secrets-preflight.sh output/apply-check-secrets-preflight
PASS empty late Secret stopped rc=1 before any write
after_rc=0
```

The existing full stub harness also passed after the fix, including its read-error, stale-read, empty realm-copy, partial-copy, LDAP, and App-key cases: `secrets cases failed: 0`.

**The full fix.** Complete exact patch: [`fixes/secrets-preflight.patch`](fixes/secrets-preflight.patch). It reads all six Secret objects before the first create, computes the realm verdict, validates every existing key set, LDAP equality, App arguments/file/mode, and only then enters the write phase. The patch includes two harness cases: empty late Secret and failed late read, each asserting that no other Secret was written.

## Finding 3 — Medium — `deploy/manifests/components/cmapi/40-networkpolicy.yaml:20-26`: the Route allow rule uses the pre-OVN ingress label

**The failure.** The API rule permits a namespace with `network.openshift.io/policy-group: ingress`. Current OpenShift 4.22 OVN-Kubernetes documentation gives the router allow selector as `policy-group.network.openshift.io/ingress: ""` and expressly says that label supports OVN-Kubernetes. On an OpenShift cluster carrying only the documented OVN label, the router namespace does not match this policy. Same-namespace pods still reach 8080, but Route traffic is blocked.

This is inferred from the manifest and upstream documentation, not measured on CRC. The first review recorded that the present CRC also had the old operator-managed label, so this may work on that one cluster today; the plain component is nevertheless wrong for the decided OVN deployment contract. Upstream source: [OpenShift 4.22 Network policy, `allow-from-router`](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/network_security/network-policy).

`results/on-kind.txt` still proves the policy blocks another namespace and permits the same namespace/port-forward on kind. That probe cannot prove an OpenShift namespace label.

**Evidence.** Complete static test: [`tests/test-openshift-router-selector.py`](tests/test-openshift-router-selector.py).

```text
$ output/venv/bin/python output/tests/test-openshift-router-selector.py repo
FAIL router selector is [{'network.openshift.io/policy-group': 'ingress'}, {}]; OpenShift 4.22 OVN documents {'policy-group.network.openshift.io/ingress': ''}
before_rc=1

$ output/venv/bin/python output/tests/test-openshift-router-selector.py output/apply-check-openshift-router-selector
PASS router selector is {'policy-group.network.openshift.io/ingress': ''}
after_rc=0
```

**The full fix.** Complete exact patch, including the service regression: [`fixes/openshift-router-selector.patch`](fixes/openshift-router-selector.patch).

## Finding 4 — Medium — `deploy/kind-test.sh:27-29`: a partial `kind create` failure leaks the cluster

**The failure.** `created=true` is assigned only after `kind create` returns successfully. If kind creates the control-plane container/network and then exits nonzero, the EXIT trap sees `created=false` and does not delete the partial cluster. This refutes “finish cleans up on every exit path.” The existing-name case remains safe in the current code, but it does not cover partial creation.

**Evidence.** Complete focused stub test: [`tests/test-kind-partial-cleanup.sh`](tests/test-kind-partial-cleanup.sh).

```text
$ output/tests/test-kind-partial-cleanup.sh repo
FAIL partial create rc=9 left the cluster; calls: kind create cluster --name cmapi-test ...;
before_rc=1

$ output/tests/test-kind-partial-cleanup.sh output/apply-check-kind-partial-v2
PASS partial create rc=9 was cleaned up
after_rc=0
```

The repository's full stub suite passed after the fix, including wrong `/version`, missing image revision, worker restart, plaintext database, failed TLS probe, existing cluster ownership, failed ownership read, and the new partial-create case: `wrong: 0`.

**The full fix.** Complete exact patch: [`fixes/kind-partial-cleanup.patch`](fixes/kind-partial-cleanup.patch). It first requires a successful `kind get clusters`, refuses an existing exact name without setting ownership, then sets ownership before `kind create`, so a partial create is cleaned. The stub now distinguishes existing-name, ownership-read-failure, and partial-create failures.

## Finding 5 — Medium — `docs/12-existing-postgresql.md:103`: a failed restore can leave the external database partially changed

**The failure.** Section 5 runs `pg_restore` with neither `--exit-on-error` nor `--single-transaction`. PostgreSQL's default is to continue after SQL errors and report the error count at the end. Earlier objects/data can therefore commit even though the command ultimately returns nonzero, leaving the target as a partial mixture. That is especially dangerous in the documented cutover because the two row counts do not prove every schema object/table and a rerun then encounters duplicates.

This is inferred from the exact command and PostgreSQL's documented semantics; no real database was started here. PostgreSQL documents that `--single-transaction` makes the restore all-or-nothing and implies `--exit-on-error`: [PostgreSQL 17 `pg_restore`](https://www.postgresql.org/docs/17/app-pgrestore.html).

**Evidence.** Complete test: [`tests/test-doc12-atomic-restore.py`](tests/test-doc12-atomic-restore.py).

```text
$ output/tests/test-doc12-atomic-restore.py repo
FAIL pg_restore can continue and commit a partial restore: pg_restore -d "$TARGET" --no-owner --role=cmapi cmapi.dump
before_rc=1

$ output/tests/test-doc12-atomic-restore.py output/apply-check-doc12-atomic-restore
PASS restore is all-or-nothing: pg_restore --exit-on-error --single-transaction -d "$TARGET" --no-owner --role=cmapi cmapi.dump
after_rc=0
```

**The full fix.** Complete exact documentation and guard patch: [`fixes/doc12-atomic-restore.patch`](fixes/doc12-atomic-restore.patch). The existing `doc12-test.py` remained green with the new assertion (`doc cases failed: 0`).

## Finding 6 — High — `cmapi/tests/service/test_plain_manifests.py:100-104`, `deploy/render-test.sh:14-18`: an unreviewed workload image survives CI

**The failure.** Replace one of the four cmapi placeholders with `ghcr.io/evil/cmapi@sha256:<64 hex>`. `render-test.sh` derives its expected count from however many placeholders remain, so it happily reports “3 placeholders, 3 filled.” The service guard accepts any image containing the substring `@sha256:`, without checking registry, repository, digest length, or that every API/worker container uses the render placeholder. Kubeconform treats the image as a string. The mutant therefore survives the whole intended image guard and can put a different image in one main or migrate container.

**Evidence.** Complete mutation test: [`tests/test-image-mutant.sh`](tests/test-image-mutant.sh).

```text
$ output/tests/test-image-mutant.sh repo
FAIL one cmapi container was pinned to an unreviewed image and the test suite passed
before_rc=1

$ output/tests/test-image-mutant.sh output/apply-check-image-guard
  FAIL the source must hold the four cmapi image placeholders, got 3
PASS the unreviewed-image mutant was killed
after_rc=0
```

**The full fix.** Complete exact patch: [`fixes/image-guard.patch`](fixes/image-guard.patch). `render-test.sh` requires exactly four cmapi placeholders. The service test requires the exact placeholder in every API/worker container and a full `repository@sha256:<64 lowercase hex>` match for other Deployment images.

## Eight verdicts

1. **Ruling 3 / render: refuted.** `bash repo/deploy/render-test.sh` confirms checksum changes, stable renders/checkouts, placeholder failure, and untouched mockup. [`test-render-atomic.sh`](tests/test-render-atomic.sh) refutes safe output publication: a failure replaces the last good tree with a partial marked tree.
2. **H2 / secrets: refuted.** Lines 53, 96, 109, and 123 show reads interleaved with write phases. The focused stub run wrote three Secrets before detecting an existing empty App Secret. The empty `cmapi-keycloak`/missing realm-copy case itself does stop before writing. Ruling 7's deleted-import case was not reported.
3. **H1 / NetworkPolicy: refuted.** `results/on-kind.txt` confirms cross-namespace blocking on kind, and `results/np-probes.txt` confirms already-running pods stayed ready for 180 seconds. No pod started under the policy, as the record says. The deletion path is inside a script that exports `KIND_EXPERIMENTAL_PROVIDER=podman` at line 17 and creates its own fixed cluster. However, lines 24-25 use the wrong selector for the upstream OpenShift 4.22 OVN router label, so a Route is not generally admitted.
4. **`kind-test.sh`: refuted.** `deploy/tests/kind-test-stubbed.sh` and lines 119-129 confirm wrong commit, missing label, and worker restart are fatal; lines 102-105 make plaintext/non-TLS fatal; the existing-name case does not delete. A partial create failure is not cleaned because ownership is set after `kind create` returns.
5. **Patch 09 / TLS: confirmed.** `20-api.yaml:45-54` and `30-worker.yaml:42-51` have no `PGSSLROOTCERT`; `results/tls-measure.txt` records `pg_stat_ssl True TLSv1.3` with the shipped env and `False None` with the removed variable restored. Every external URI in docs/12 either contains `sslmode=verify-full&sslrootcert=...` (section 3) or uses `sslmode=verify-full` with `PGSSLROOTCERT` (section 5). I found no documented URI that silently connects without verification. CNPG server verification remains excluded as #91.
6. **docs/12 commands: refuted.** `output/venv/bin/python repo/deploy/tests/doc12-test.py repo/docs/12-existing-postgresql.md` passed the existing guards, and the recorded real measurements support the dump/user/CA/order corrections. But line 103 can leave a partial target on restore error; the existing guard did not check transaction/error behavior.
7. **tests and `manifests` job: refuted.** The exact-image mutant survives both positive guards, as shown above. The other local suites I ran were effective on their covered cases (`render cases failed: 0`, `secrets cases failed: 0`, the changed kind stub suite `wrong: 0`, and `doc cases failed: 0`). Static inspection found the hosted job pinned to Ubuntu 24.04, kubectl/kind/download hashes, and the Docker-default kind create. Docker itself was unavailable here, so its `np-reach-test.sh` path remains unmeasured.
8. **test record: confirmed.** `docs/reviews/2026-11-05-plain-manifests-test.md:95-135` matches `results/kind-test-16fa0fedcb.log`, `on-kind.txt`, `np-probes.txt`, `tls-measure.txt`, and `keycloak-0.txt`, including the explicit statements that the successful full run deleted the policy before pods started and that the hosted `manifests` job was not done in that record. `docs/08-code-status.md:60` makes the same bounded plain-manifest claims and says CRC/Argo CD remain later work.

## Not proven / not tested

- Docker was installed but its daemon was unreachable: `docker info` returned `Cannot connect to the Docker daemon`. I did not run `np-reach-test.sh` on Docker-backed kind.
- I did not use `oc`, CRC, its Keycloak/LDAP, a home-directory kubeconfig, or container `cmapi-test-pg`.
- I did not create any kind cluster. The NetworkPolicy Route result is inferred from the manifest plus upstream OpenShift 4.22 documentation, not measured on OpenShift.
- I did not run a real PostgreSQL restore. Finding 5 uses PostgreSQL's primary documentation and the exact runbook command.
- I did not rerun the whole service suite or kubeconform. I ran the focused manifest functions directly with PyYAML because importing the service suite's `conftest.py` requires the full application dependency set.
- I did not find a current change to the bytes of the three referenced ConfigMaps that leaves the configuration checksum unchanged. I did not test exotic duplicate Kubernetes objects in the environment directory.

No resources outside this workspace were written, and no cluster cleanup was required.
