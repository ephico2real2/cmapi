# Adversarial review of PR #89 (reviewer A, Opus 5.5)

Reviewed the export `head/` (verified equal to PR head `d21599a` for `deploy/secrets.sh` and `build-tracker.md` through `gh api`). Paths below are relative to this `pr89-a/` folder unless they name a file in the PR. Every number here came from a run whose log is under `work/`, unless it is marked read or inferred.

**Which cluster:** `cmapi-pr89-a` is my kind cluster (`KIND_EXPERIMENTAL_PROVIDER=podman`, node `v1.35.8`, CNPG 1.30.1 from the SHA-256-verified file). It was deleted by name. "Stub" means `tests/stub/kubectl-stub.py` or `tests/kindtest/bin/`. CRC was read only with `oc get`, `oc describe` and `oc api-resources`. `keycloak-0` read restart count 1, started `2026-11-05T20:17:08Z`, before and after.

## Verdict for the shared cluster

**Do not apply as it stands.** Two defects reach CRC directly. H1 opens the API port to every pod on the cluster. H2 can rotate Secrets behind the realm after an API error. Patches 01 and 02 fix both. Merging by itself writes nothing to a cluster. Wave 1 also cannot start from this tree without M5 and M7: `render.sh` refuses the internal-registry digest, and `cmapi-imports` does not exist on CRC.

## Findings, ranked

| # | Severity | What | Patch | Test |
|---|---|---|---|---|
| H1 | High | The reviewed NetworkPolicy guard was lost: port 8080 is open to every namespace | `patches/01` | `fixed/cmapi/tests/service/test_plain_manifests.py`, `tests/np-reach-test.sh` |
| H2 | High | `secrets.sh` treats any read error as "absent", so it rotates and replaces | `patches/02` | `fixed/deploy/secrets-test.sh` cases 2a, 2b, 8a, 10e |
| M1 | Medium | `secrets-test.sh` cannot fail on several claims, including the no-value scan | `patches/02` | `tests/mutate-secrets.py` |
| M2 | Medium | docs/12 section 5: the dump fails and the Secret cannot be replaced as written | `patches/03` | `tests/doc12/doc-test.py`, `tests/doc12/cnpg-move-test.sh` |
| M3 | Medium | `kind-test.sh` cannot fail on `/version` or on a crashing worker, deletes a cluster it did not create, and more | `patches/04` | `tests/kindtest/run.sh` |
| M4 | Medium | The migrate initContainer silently falls back to plaintext on the default CNPG path | `patches/09` (optional, needs a ruling) | `tests/doc12/external-pg-test.sh`, pytest |
| M5 | Medium | `render.sh` refuses Wave 1's digest, deletes any directory, misreads arguments, and allows `--allow-tag` everywhere | `patches/05` | `fixed/deploy/render-test.sh` |
| M6 | Medium | CI: floating schemas and kubectl; the render step cannot detect a wrong image | `patches/06` | `tests/ci-guard.py` |
| M7 | Medium | What the charts did and nothing now says: restart on config change, Keycloak URLs, `cmapi-imports` | `patches/07`, `patches/08` | Unproven by a run, see below |
| L1 | Low | docs/12 smaller defects: empty password, lost password, floating digest, a false table row, connection limit | `patches/03` | `tests/doc12/doc-test.py` |
| L2 | Low | A partial `cmapi-keys` is reported as "present, kept" | `patches/02` | case 2f |
| L3 | Low | `secrets-test.sh` runs on whatever context it is given | `patches/02` | Run shown below |
| L4 | Low | Tracker facts | `patches/08` | Read and `gh`, no test |

### H1. The API port is open to every pod on the shared cluster

- **Where:** `deploy/manifests/components/cmapi/40-networkpolicy.yaml:20-21`. Line 1 still says "Only the router reaches the API port".
- **What happened:** the chart's template (`templates/monitoring.yaml:21-27`) adds `from` only when `exposure` is `Route`, and CRC sets `Route`. The manifest copied the branch without `from`, which is the non-Route shape. This is also the kind leak that claim 5 asks about. The guard had a test: `test_review_g_chart.py:69-72`, "a rule with no from: any pod on the shared cluster reaches 8080". That test reads helm's output, so nothing reads this file.
- **Scenario:** a pod in `inkcast` calls `http://<api pod ip>:8080` and bypasses the router, including anything a Route would enforce.
- **Measured on `cmapi-pr89-a`** (`work/np-reach.log`, `tests/np-reach-test.sh`):
  ```
  head's policy : other ns reached; same ns reached; port-forward 200
  fixed policy  : other ns blocked; same ns reached; port-forward 200
  ```
- **On CRC (read):** `oc get ns -l network.openshift.io/policy-group=ingress` lists `openshift-host-network` and `openshift-ingress`, so the chart's selector matches the router.
- **Fix:** `patches/01-networkpolicy-from-and-plain-yaml-guards.patch` restores the chart's rule. Kind's port-forward still works, as measured above.
- **Test:** `test_api_port_is_not_open_to_every_namespace`. Before: `1 failed, 9 passed`. After: `10 passed`.
- **Not run:** kubelet probes under this rule on a Docker-backed kind. On podman kind `kind-test.sh` removes the policy anyway. On OVN-Kubernetes I did not measure it.

### H2. A read error counts as an absent Secret, so values are rotated

- **Where:** `deploy/secrets.sh:29` (`2>/dev/null || true`), `:58`, `:78`, `:87`, `:101`. `:33` then overwrites with server-side apply.
- **Scenarios, measured on the stub with reads answering an error and writes working** (`work/fixed-harness-on-head-secrets.txt`, head's `secrets.sh`, the new cases):
  ```
  FAIL 2a a failed read of cmapi-keys stops (expected rc=1): rc=0 wrote Secret sect1/cmapi-keys
  FAIL 2b failed reads of the realm's Secrets stop (expected rc=1): rc=0 ...
  FAIL 2b the realm copy: expected 304494115f7a, got df4dc37c144e
  FAIL 8a a failed read of the import stops, it is not 'no import' (expected rc=1): rc=0 ...
  FAIL 10e a failed read of the app secret stops (expected rc=1): rc=0 wrote Secret sect1/cmapi-github-app
  ```
  - **2b is the case the script exists to prevent:** both copies are replaced with new values while the realm keeps the old ones, so every client's sign-in fails.
  - **8a:** a Forbidden on `keycloakrealmimport` alone passes the guard. A person with Secret rights but no right on that CR gets a mint with the realm still present.
  - **10e:** refutes "an existing `cmapi-github-app` is never replaced".
  - **How likely (inferred, not measured):** it needs an API error followed by a working write, or read denied with write allowed. On a single-node CRC at 79% of memory requests a transient error is plausible, and `keycloak-0` has already restarted once today with the cause unknown.
- **Fix:** `patches/02-secrets-read-errors-and-real-cases.patch`.
  - `get` uses `--ignore-not-found` with no `|| true`, so empty output now only means NotFound. I confirmed the semantics on real kubectl 1.37.1 and `oc` 4.22.18 (`oc get secret nosuch-pr89 -n cmapi --ignore-not-found -o json`: empty, rc 0).
  - `realm_import_exists` treats only "doesn't have a resource type" as no import. That text is confirmed on `oc`.
  - `apply_secret` uses `kubectl create`, because every write fills an absent Secret. So a stale read cannot overwrite either.
- **Test:** after the patch, all cases pass on the stub and on the real API of `cmapi-pr89-a` (`work/fixed-on-kind.log`, `secrets cases failed: 0`).
- **Caveat:** that kind run predates two later edits, the context guard (L3) and a header comment in `secrets.sh`. Both were run only on the stub.

### M1. `secrets-test.sh` cannot fail on several claims

Mutants of head's `secrets.sh`, run against head's `secrets-test.sh` on the stub (`tests/mutate-secrets.py`, `work/mutants-before.txt`). The base run passes, so the stub is faithful to these cases:

| Mutant | Result |
|---|---|
| A: prints every generated value to the terminal | **Survived** |
| B: `cmapi-keys` rotated on every run | **Survived** |
| C: a complete `cmapi-github-app` replaced from the key file | **Survived** |
| F: `from-ours` mints new realm values instead of copying | **Survived** |
| G: a partial namespace copy overwritten instead of stopping | **Survived** |
| H: ours written before the realm's copy | **Survived** |
| I: the same value for all four clients | **Survived** |
| D, E, J, K, L | Killed |

- **A has a clear cause:** `secrets-test.sh:78` greps only `$T`, which each `run` overwrites, so it reads only the last case's output, and only for the fixed strings `eHh4` and `MQ==`. The generated values are never looked for.
- **10b's check is weak too:** line 73 checks `appId` is still `MQ==`, but the run passes the same id, so a replacement looks identical.
- **Fix:** `patches/02`. All output is accumulated and scanned for the real values read from the cluster, printing only a count. Cases added: `cmapi-keys` hash, realm hash, `from-ours`, partial ours, complete app Secret with other arguments, `ldap-bind` absent after 9a, realm copy absent after 8, four distinct 48-character values.
- **After** (`work/mutants-after.txt`): A, B, C, D, E, F, I, J, K, L, N, O killed. Three survive, each with a reason:
  - **G and M** are stopped by the second defence: with `create`, a stale "absent" hits AlreadyExists.
  - **H** (write order) changes no outcome, since a failed second write is healed by the next run either way.

### M2. docs/12 section 5 does not work as written

Measured on real CNPG 1.30.1 on `cmapi-pr89-a` (`work/doc12-cnpg.log`, `work/doc12-cnpg-replace.log`):

- **Line 90 fails.** `pg_dump -U cmapi` gives `FATAL: Peer authentication failed for user "cmapi"`, rc 1, 0 bytes. The workloads are already at 0 by then. `-U postgres` gives rc 0.
- **"Then replace `cmapi-db-app`" cannot be done while the Cluster exists:**
  - Section 3's apply fails: `Apply failed with 1 conflict: conflict with "manager" using v1: .type`.
  - With `--force-conflicts`: `type: Invalid value: "Opaque": field is immutable`. CNPG's type is `kubernetes.io/basic-auth`, ownerRef Cluster.
  - After deleting the Secret, the operator had already written its own back before the apply ran, so the apply conflicted again.
- **"Delete it by hand when the move is proven":** deleting the Cluster garbage-collects `cmapi-db-app` and left 0 PVCs in namespace `cmapi` (`kubectl get pvc` on kind). So the order has to change.
- **Line 91:** `verify-full` with no root certificate fails: `Either provide the file, use the system's trusted roots with sslrootcert=system...` (`work/doc12-restore.log`).
- **A CNPG 17 dump with a PostgreSQL 16 `pg_restore`:** `unsupported version (1.16) in file header`, using a dump really taken from CNPG. Section 1 accepts 16.

**Fix:** `patches/03-docs12.patch`: dump as `postgres`, `PGSSLROOTCERT` for the restore, counts compared, then remove the file, delete the Cluster, create the Secret. `tests/doc12/doc-test.py`: head `doc cases failed: 10`, fixed `0`. It caught a bug in my own first fix: `set -e` is ignored in a subshell that is part of an `&&` list.

**Not run:** the corrected section 5 sequence as one piece. Measured parts: the dump as `postgres`, the Secret gone after the Cluster's deletion, and the restore flags on PostgreSQL 16 (`restore rc=0`, 10 tables, owner `cmapi2`, revision `0003`).

### M3. `kind-test.sh` cannot fail on what it claims, and deletes what it did not create

`tests/kindtest/run.sh` on head (`work/kindtest-before.txt`, `wrong: 7`):

```
WRONG rc=0 /api/v1/version answers an error, not the commit
WRONG rc=0 /api/v1/version is empty
WRONG rc=0 /api/v1/version names another commit than built
WRONG rc=0 the worker has crash-looped since its rollout
WRONG somebody else's cluster is not deleted: expected no, got yes
WRONG the policy stays: the container resolves the Service now: expected no, got yes
WRONG: the kill misses the port-forward    (8 left behind)
```

- **`:82`:** the `/version` check only ever echoes a note, though the header promises "naming the built commit".
- **`:69`:** `rollout status` passes at the first start, and the worker has no readiness probe.
- **`:19`:** the trap deletes `cmapi-test` even when `kind create` failed because the name was already taken.
- **`:57-58`:** an old `--previous` log alone triggers the NetworkPolicy deletion even when the live probe just resolved, and the output still prints "MEASURED: cannot resolve".
- **`:74`, `:78`:** `k` is a function, so `$!` is a subshell and `kill` leaves kubectl holding the port. A later run's curl can then read the old cluster.

**What held on claim 6:** `/readyz`, the mockup, the secrets cases and a rollout failure all fail the script. The policy is deleted on the proven pair and not when the mockup also fails. The deletion is reported in the `MEASURED` line and the last line. Lines 16 and 62: the script always runs on podman, so "only on podman" holds by construction, not by a check.

**Fix:** `patches/04-kind-test.patch`. The commit is compared with the image's own `org.opencontainers.image.revision` label, which on `localhost/cmapi:dev` reads `1f30ab1ac4`, the same value as the recorded `/version`.

**Test:** `wrong: 0` on `fixed/deploy` (`work/kindtest-after.txt`). The patched script ran on stubs only, never on a real kind cluster.

### M4. The migrate initContainer falls back to plaintext on the default CNPG path

- **Where:** `deploy/manifests/components/cmapi/20-api.yaml:49`, `30-worker.yaml:46`. The chart has the same env, so this is not a lost guard.
- **Measured** with the real image against PostgreSQL 16 with TLS, whose `pg_hba` allowed both (`work/doc12-external.log`):
  ```
  no sslmode, no PGSSLROOTCERT (main container)                  -> ('cmapi', True,  'TLSv1.3')
  no sslmode, PGSSLROOTCERT = bundle without the server's CA     -> ('cmapi', False, None)
  ```
- **For CNPG, inferred:** CNPG's `uri` has no query (measured: `cmapi-db-rw.cmapi 5432 /cmapi <no query>`). The PR's own kind log shows migration succeeding with a stand-in CA in the bundle, which cannot verify CNPG's certificate. I did not read `pg_stat_ssl` on CNPG itself.
- **Scenario:** migrations run in plaintext inside the cluster with no signal. If a site makes CNPG TLS-only, the same setting makes migrate fail instead.
- **Fix:** `patches/09-optional-migrate-no-plaintext-fallback.patch` removes `PGSSLROOTCERT`, because the guide's URI already carries `sslrootcert` (measured: `verify-full` passes and a wrong CA is refused with the variable unset).
- **Why optional:** it reverses a review-earned chart guard (`test_the_migrate_init_container_trusts_what_the_main_container_trusts`), so the coordinator should rule. Pytest: before 2 failed, after 10 passed. The migrate container keeps the trust mount.

### M5. `render.sh`

`fixed/deploy/render-test.sh` on head's script (`work/render-before.txt`, `render cases failed: 5`):

```
FAIL --allow-tag was accepted for crc
FAIL the internal registry's digest needs --allow-tag
FAIL --allow-tag before the out dir: the out dir was ignored
FAIL render.sh replaced a directory it did not write
FAIL deploy/ as the out dir deleted the manifests
```

- **`:16`:** Wave 1 deploys from CRC's internal registry by digest (tracker), but this regex refuses it. The only way through is `--allow-tag`, whose own message says "never a deployment".
- **`:24`:** `rm -rf "$OUT"` removes any directory it is given.
- **`:10`:** the flag becomes an empty positional argument, so `kind IMG --allow-tag OUT` silently ignores `OUT`.

**Claim 2's core holds:** 4 placeholders and 4 filled, only image lines change, the mockup image is untouched, a tag is refused and the last render stays, a partly written directory is replaced with its leftovers gone, and a placeholder in a `.yml` fails.

**Fix:** `patches/05-render.patch`, then `render cases failed: 0`, also with macOS's bash 3.2 first on `PATH`. A note for the patch: an out dir rendered before the patch has no marker, so it is refused once.

### M6. CI job `manifests`

- **`ci.yml:117-118,122-123`:** schemas float on `master` and `main`. The tracker already lists this as "To pin". Patch 06 pins `yannh/kubernetes-json-schema@10236197...` and `datreeio/CRDs-catalog@c86448cb...`, and I confirmed both URLs answer 200.
- **kubectl** comes from the runner image, so it floats with `ubuntu-latest`. The secrets cases depend on its semantics. Patch 06 pins v1.35.8 by SHA-256 (from `dl.k8s.io`).
- **The render step cannot catch a wrong image.** A mutant that fills `ghcr.io/evil/x:latest` gives render rc 0 and an empty `grep` for the placeholder, and the step would pass. `kubeconform` passing on it is inferred, since an image is only a string. Patch 06 adds `deploy/render-test.sh`, which fails that mutant: `FAIL 4 placeholders, 0 filled with the image`.

**Test:** `tests/ci-guard.py`: head `ci cases failed: 3`, fixed `0`.

**Sound (measured by hashing the downloads):** kubeconform, shellcheck, kind and CNPG all match their pinned SHA-256. Also sound: `contents: read` with no widening, `persist-credentials: false`, actions by full SHA, the `if` form of the placeholder check, and `mockup-configmap.sh --check` (rc 0, then rc 1 on a changed source). Left as is: `runs-on: ubuntu-latest`, like the other jobs.

### M7. What the charts did and nothing now says (unproven by a failing behaviour test)

- **`checksum/config` is gone.** A changed `cmapi-config`, `cmapi-env` or `cmapi-trust` restarts nothing. Read: `core/context.py:71-110` loads config at build, and the tracker says hot reload is not built. Not run.
- **`CMAPI_OIDC_JWKS_URL` and `CMAPI_KEYCLOAK_ADMIN_URL`** are in the chart's CRC render but not in the manifests, and the comment at `20-api.yaml:98` and `30-worker.yaml:95` lists four per-environment keys without them. What happens without them on CRC was not measured.
- **`cmapi-imports` does not exist on CRC** (measured). `00-namespaces.yaml` says it comes from the bootstrap set, which is Wave 2, after Wave 1. The first `oc apply -R` would fail on the Role there (inferred).
- **`cmapi-test-users`** is not written by `secrets.sh`. It is optional in the chart (`jobs.yaml:97`).

**Fix:** `patches/07` (README and comments), `patches/08` (the tracker's Wave 1 row). These are text only, so there is no failing test to show.

### L1. docs/12's smaller defects (`patches/03`, `tests/doc12/doc-test.py`)

- **Lines 51-55:** with no `pw.txt`, `oc` receives a Secret with an empty password. With a failing `oc`, `rm -f pw.txt` still deletes the only copy. Both failed before and pass after.
- **Line 63:** `--overrides` replaces the containers list. A `kubectl run --dry-run=client` on `cmapi-pr89-a` printed `image: ghcr.io/cloudnative-pg/postgresql:17` and `env: None`, so the pinned digest and the env are both dropped.
- **Line 17:** says `PGSSLROOTCERT` is on the main containers. It is on the initContainer only. Measured consequence: with `verify-full` and no `sslrootcert`, the same URI connects with the variable set and fails without it (`root certificate file ".../root.crt" does no[t exist]`), so it would migrate and then fail in the main container.
- **Line 26, `CONNECTION LIMIT 30`:** both Deployments surging gives 4 × 10 + 2 = 42 at full pools. This is arithmetic from the manifests, not measured.

### L2. Partial `cmapi-keys`

`secrets.sh:78-82` prints "present, kept" for a Secret missing a key. Fixed in patch 02. Case 2f fails before (`rc=0 cmapi-keys: present, kept`) and passes after.

### L3. The harness has no context check

`secrets-test.sh` creates and deletes namespaces on any cluster. On the stub with CRC's context name, head ran all its cases (`secrets cases failed: 0`), while the patched script gives rc 2. Fixed in patch 02.

### L4. Tracker facts

- **"Core reference modules, CI: 121 tests, `cmapi/tests/core`":** the 121 are `examples/tests` in job `reference-code` (run 42130344182 log: `121 passed`). No CI job runs `cmapi/tests/core` (`ci.yml:27,56`), and `docs/08` says 120. I did not run that folder.
- **The tracker cites kind's "ten secrets cases pass":** true for a separate run. `kind-test.sh` as a whole never exited 0 on record: its log ends with `secrets cases failed: 13`. The test record says so; the tracker does not.

Fixed in patch 08.

## A limit, not fixed

If `KeycloakRealmImport cmapi` and both Secrets are deleted while the realm stays, the script sees a first install and mints values (stub: `wrote Secret b/cmapi-realm-secrets`). Nothing in the cluster's objects can tell these apart without asking Keycloak. Patch 02 records it in the script's header. A real guard would need a realm URL argument, which I did not write.

## Claims: confirmed or refuted

1. **`secrets.sh`, refuted in part.**
   - Refuted: "nothing rotated" and "never replaced" (H2), and "its tests can actually fail" (M1).
   - Confirmed: a partial realm Secret stops the run. No value reached an argument list (stub: `values 10 in argv.log: 0`). A scan of the PR's two logs for strings of 44 or more base64 characters matched only two temp paths and the node image's digest. `cmapi-ldap-bind` is never written by the code. A failed apply stops the run without printing "wrote".
   - Observation: values pass through `OURS=` and `THEIRS=` into short-lived Python environments, which the same uid can read. They are not on an argument list, so the claim stands.
2. **`render.sh`, core confirmed, edges refuted** (M5).
3. **Manifests against the chart:** full per-object diff in `work/cmp.py`, rendered from `deploy/helm/cmapi` with `crc.yaml`.
   - Lost guard: the 8080 `from` (H1).
   - Same: migrate initContainers, trust mounts on both, env including `CMAPI_DATABASE_URL` from `cmapi-db-app/uri`, probes, `/readyz` (code unchanged, `cmapi/src` has no diff from main), pod and container security contexts, resources, pool (default `5+5`, no env set on either side).
   - Differences that do not matter: `readOnlyRootFilesystem: false` dropped (same as unset), labels, sync-wave annotations, image, `envFrom cmapi-env` replacing inline Git env.
   - Differences that matter: `checksum/config` and the two Keycloak URLs (M7).
   - By design: `storageClass` dropped; `monitoring.enablePodMonitor` dropped (the chart's PrometheusRule uses no `cnpg_` metric, read).
   - The lost-guard check is now a test: `test_plain_manifests.py`.
4. **`cluster.yaml`, confirmed.**
   - Read in Argo CD v3.5.6 source: `isPruningDisabled` on the live object (`sync_context.go:335-342`, "ignored (no prune)"), `shouldBeDeleted` (`appcontroller.go:1333-1342`), and the comma-separated options parser (`annotations.go`). **Never run on Argo CD with this file.**
   - One limit on the comment's "no Git change": a commit that first removes the annotation, then one that removes the file, would prune it (inferred from the source reading the live object). `test_plain_manifests.py` now guards the annotation.
   - Digest (measured from GHCR): `70664ebc...` is the current `17` tag, an index with linux/amd64 and arm64. It ran Healthy on `cmapi-pr89-a`.
   - No StorageClass in the file. The name is only in a comment, and on CRC `crc-csi-hostpath-provisioner` is the default (read).
5. **kind leakage, refuted once:** the NetworkPolicy (H1). Otherwise clean: no other kind-only content in `components/`, and `environments/kind/` differs from the chart's config only in the expected fields (`work/cfg.py`).
6. **`kind-test.sh`, refuted in part** (M3). The NetworkPolicy deletion is reported, and it requires the mockup pair, but an old log can trigger it.
7. **CI, confirmed except floats and the render step** (M6).
8. **docs/12:**
   - Sections 2 and 3 confirmed end to end with the real migrator: PostgreSQL 16 with TLS, a password holding `@%/:#&?` and a space, `migrated to head`, revision `0003`, owner `cmapi`, `pg_stat_ssl` true on TLSv1.3, wrong CA and wrong name both refused, a second run a no-op, step 4's SQL correct.
   - Code claims confirmed: `pool_size=5, max_overflow=5` (`core/db/__init__.py:27`), `pg_advisory_lock(727364)` and `lock_timeout` 30 s (`migrations/env.py:30-34`), 540 s (`migrate.py:63`), Secret `cmapi-db-app` key `uri`, `/readyz` semantics (`routers/health.py:33-39`).
   - Refuted: the `PGSSLROOTCERT` row (L1), section 5 (M2).
9. **Tracker and handover: a new session could continue**, apart from the Wave 1 gaps (M7) and L4.
   - Confirmed: merge commit `1f30ab1`; run 42130344182 success on `e8afca9`; run 42129295237 failed on `66c038a`; 291, 121 and 8 tests; required checks; issue states; OpenShift 4.22.14 and Kubernetes 1.35.6; 15525Mi (79%); 277 kinds; `cmapi-test-pg` on 55432; 32 GiB; podman at 8 GiB; `sweep-stale.py` exists; `oc get all -n cmapi` empty; CNPG 1.30.1 CSV on CRC.
   - Small: the tracker cites `e8afca9` while the head is `d21599a` (the tracker's own commit, rollup green). Namespace `cmapi` also holds OpenShift's dockercfg Secrets, not "only" `cmapi-ldap-bind`.
   - Not checked: the RHBK version 26.6.7, the LDAP namespace and base, the registry route, the Codex model name, and "Docker off".

## What I could not check, and why

- **`kubeconform`, not run by me.** The auto-mode classifier refused the command that downloaded and ran the binary ("Code from External"). I did not route around it: I hashed the downloads and did not execute them. The relevant part of the refused command (it also downloaded other files and made registry reads, which I then ran separately):
  `curl -fsSL -O https://github.com/yannh/kubeconform/releases/download/v0.6.7/kubeconform-darwin-amd64.tar.gz; tar xzf kubeconform-darwin-amd64.tar.gz kubeconform && ./kubeconform -v; ../work/dl/kubeconform -strict -summary -kubernetes-version 1.35.0 -schema-location "$S" -schema-location "$C" deploy/manifests/components deploy/manifests/environments`.
  So patch 06's pinned schemas and the patched manifests have not been through kubeconform; CI will do that. CI's result on head is from `gh`: job `manifests` success.
- **A blanket `rm -rf work/renderB/*` was refused** by the safety check. I used fresh directories instead, so nothing needed removing.
- **Real CRC behaviour:** SCC admission, OVN-Kubernetes policy, Routes, the realm import. Nothing was written there.
- **Real Argo CD:** source read only.
- **The full `deploy/kind-test.sh`** end to end, patched or not: it would have used the name `cmapi-test`, outside my brief.
- **Patched `kind-test.sh`'s 15 s settle time** catching a real crash: stub only.
- **Docker-backed kind** with the restored NetworkPolicy.

## Patches and tests

Patches apply in order to a fresh copy with `patch -p1` (all rc 0). On that copy: shellcheck 0.11.0 rc 0 on all six scripts, `render cases failed: 0`, `10 passed`, `doc cases failed: 0`, `ci cases failed: 0`, `secrets cases failed: 0`, and `tests/kindtest/run.sh` `wrong: 0`. Patch 09 goes on top, if accepted.

## Cleanup

Kind cluster `cmapi-pr89-a` deleted (`No kind clusters found`). No `pr89a-` container or network left. `cmapi-test-pg` untouched. One stray temp directory I wrote under `/tmp` by mistake (`/tmp/pr89a-mut-7221`) was removed.
