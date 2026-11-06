# Adversarial review: PR #89

## Verdict

**Not safe to apply to the shared cluster.** I found two high-severity fail-closed/ownership defects and five medium/low findings. In particular, `secrets.sh` can treat a failed Secret read as absence and overwrite the existing GitHub App Secret, and `kind-test.sh` can delete a pre-existing cluster that it did not create.

I did not use `oc`, create a cluster, start a container, or write to GitHub. All reproductions used static checks or command stubs with dummy values. `head/` was treated as an archive; I did not use repository-dependent tests there.

## Findings, ranked

### High — Secret/API read failures are treated as absence, and an empty realm Secret is treated as no Secret

**Evidence:** `deploy/secrets.sh:29,37-52,58-63,101-112`.

`get()` suppresses every `kubectl get` failure (`2>/dev/null || true`). A timeout, authorization error, or unavailable API is therefore indistinguishable from NotFound. If `cmapi-github-app` exists but its read fails and the caller supplied `--github-app-key`, the script server-side-applies a replacement. The same fail-open behavior can mint realm values after failed reads. Separately, the verdict uses the truthiness of `.data`, not object existence: an existing `cmapi-realm-secrets` with `data: {}` enters `generate`, although it is a partial Secret that must stop the run. This loses the fail-closed guard called out in `CRC-BUILD-STATUS.md:72,77` and the design ruling at `docs/reviews/2026-11-05-deployment-design.md:491`.

Concrete scenarios:

1. The API returns an error for `GET app/cmapi-github-app`, then recovers before `apply`; the existing App credential is overwritten with the supplied file.
2. A retained realm exists, its import CR has since been removed, and its placeholder Secret survives as an empty object; the script generates new values that do not match the realm.

Tests actually run:

```text
$ review-tests/test-secret-read-errors.sh head
FAIL a failed Secret read was treated as absence: rc=0 applies=1
$ review-tests/test-secret-read-errors.sh review-fixed
PASS Secret read error stopped without writes: rc=7 applies=0

$ review-tests/test-empty-realm.sh head
FAIL empty realm Secret must stop without writes: rc=0 applies=3
$ review-tests/test-empty-realm.sh review-fixed
PASS empty realm Secret stopped: rc=1 applies=0
```

The exact tests are `review-tests/test-secret-read-errors.sh` and `review-tests/test-empty-realm.sh`; they use dummy base64 only and never print a credential.

Full fix:

```diff
diff --git a/deploy/secrets.sh b/deploy/secrets.sh
@@
-get() { kc get secret "$2" -n "$1" -o json 2>/dev/null || true; }
+# --ignore-not-found makes only a genuine absence empty. API, auth and transport
+# errors remain non-zero and set -e stops the script before any write.
+get() { kc get secret "$2" -n "$1" --ignore-not-found -o json; }
@@
 pairs=[p.split(":") for p in os.environ["PAIRS"].split()]
-o=(json.loads(os.environ["OURS"]) if os.environ["OURS"] else {}).get("data",{}) or {}
-t=(json.loads(os.environ["THEIRS"]) if os.environ["THEIRS"] else {}).get("data",{}) or {}
+oe,te=bool(os.environ["OURS"]),bool(os.environ["THEIRS"])
+o=(json.loads(os.environ["OURS"]) if oe else {}).get("data",{}) or {}
+t=(json.loads(os.environ["THEIRS"]) if te else {}).get("data",{}) or {}
 oa,ta=[a for a,_ in pairs],[b for _,b in pairs]
 om=[k for k in oa if not o.get(k)]; tm=[k for k in ta if not t.get(k)]
-if not o and not t: print("generate")
-elif t and tm: print("partial realm copy, missing "+",".join(tm))
-elif o and om: print("partial namespace copy, missing "+",".join(om))
-elif t and not o: print("from-realm")
-elif o and not t: print("from-ours")
+if not oe and not te: print("generate")
+elif te and tm: print("partial realm copy, missing "+",".join(tm))
+elif oe and om: print("partial namespace copy, missing "+",".join(om))
+elif te and not oe: print("from-realm")
+elif oe and not te: print("from-ours")
 else:
@@
-    if kc get keycloakrealmimport cmapi -n "$REALM_NS" >/dev/null 2>&1; then
+    # kind legitimately lacks the Keycloak CRD. Discovery distinguishes that
+    # condition from a failed read; discovery errors remain fatal under set -e.
+    realm_resources=$(kc api-resources --api-group=k8s.keycloak.org -o name)
+    if printf '%s\n' "$realm_resources" | grep -q '^keycloakrealmimports'; then
+      realm_import=$(kc get keycloakrealmimport cmapi -n "$REALM_NS" --ignore-not-found -o name)
+    else
+      realm_import=
+    fi
+    if [ -n "$realm_import" ]; then
       echo "ERROR: KeycloakRealmImport cmapi exists in $REALM_NS and both Secrets are gone. New values would not match the realm. Read the clients' secrets from the realm, or delete the realm and its import first." >&2; exit 1
     fi
```

The patched script also passed ShellCheck 0.11.0. The existing `secrets-test.sh` can fail—its final `[ "$fails" = 0 ]` is effective, and the supplied record shows an earlier 13-failure run—but it lacks both cases above. The other claim-1 properties are sound on successful reads: values go through stdin/environment rather than argv or output; `cmapi-ldap-bind` is only read; a successfully read existing `cmapi-github-app` is never applied; and the supplied logs contain none of the test literals `eHh4`, `MQ==`, or a private-key header. Issue #90 is not repeated here.

### High — `kind-test.sh` can delete a pre-existing cluster

**Evidence:** `deploy/kind-test.sh:19-24`.

The EXIT trap is installed before `kind create` and always deletes `cmapi-test`. If that name already belongs to another run, `kind create` fails and the trap immediately deletes the other run's cluster. This is destructive and contradicts the script's ownership claim.

Test actually run with a stub reporting an existing cluster:

```text
$ review-tests/test-kind-ownership.sh head
FAIL EXIT trap deleted a cluster this run did not create
$ review-tests/test-kind-ownership.sh review-fixed
PASS existing cluster was refused and not deleted
```

Full fix:

```diff
diff --git a/deploy/kind-test.sh b/deploy/kind-test.sh
@@
 KC=${KIND_TEST_KUBECONFIG:-$HERE/../.cmapi-test.kubeconfig}
+CLUSTER_NAME=${KIND_TEST_CLUSTER:-cmapi-test}
@@
-finish() { rc=$?; if [ "${KIND_TEST_KEEP:-false}" != true ]; then say "deleting kind cluster cmapi-test"; kind delete cluster --name cmapi-test --kubeconfig "$KC" >/dev/null 2>&1 || true; rm -f "$KC"; fi; exit $rc; }
+OWNS_CLUSTER=false
+finish() { rc=$?; if [ "$OWNS_CLUSTER" = true ] && [ "${KIND_TEST_KEEP:-false}" != true ]; then say "deleting kind cluster $CLUSTER_NAME"; kind delete cluster --name "$CLUSTER_NAME" --kubeconfig "$KC" >/dev/null 2>&1 || true; rm -f "$KC"; fi; exit $rc; }
 trap finish EXIT
 
-say "kind create cluster cmapi-test ($NODE_IMAGE)"
-kind create cluster --name cmapi-test --image "$NODE_IMAGE" --kubeconfig "$KC" --wait 120s >/dev/null
-[ "$(k config current-context)" = kind-cmapi-test ] || { echo "ERROR: the kubeconfig's context is not kind-cmapi-test" >&2; exit 1; }
+if kind get clusters | grep -Fxq "$CLUSTER_NAME"; then
+  echo "ERROR: kind cluster $CLUSTER_NAME already exists; refusing to use or delete a cluster this run did not create" >&2
+  exit 1
+fi
+say "kind create cluster $CLUSTER_NAME ($NODE_IMAGE)"
+OWNS_CLUSTER=true
+kind create cluster --name "$CLUSTER_NAME" --image "$NODE_IMAGE" --kubeconfig "$KC" --wait 120s >/dev/null
+[ "$(k config current-context)" = "kind-$CLUSTER_NAME" ] || { echo "ERROR: the kubeconfig's context is not kind-$CLUSTER_NAME" >&2; exit 1; }
@@
-kind load image-archive "$T/image.tar" --name cmapi-test
+kind load image-archive "$T/image.tar" --name "$CLUSTER_NAME"
```

Setting ownership before `create` deliberately cleans up a partially created cluster, while the preflight protects any pre-existing name.

### Medium — the chart's API ingress source guard was lost

**Evidence:** `deploy/manifests/components/cmapi/40-networkpolicy.yaml:14-20`, versus `deploy/helm/cmapi/templates/monitoring.yaml:21-28`.

The chart's Route path admits API port 8080 only from the OpenShift ingress namespace or same-namespace pods. The plain manifest has a rule with `ports` and no `from`, which admits port 8080 from every source. Its comment, “Only the router reaches the API port,” is false. On a shared cluster, a compromised pod in an unrelated namespace can bypass the router and reach the service ClusterIP directly.

Test actually run:

```text
$ review-tests/test-networkpolicy-api-source.sh head
FAIL API ingress is not restricted to the OpenShift router
$ review-tests/test-networkpolicy-api-source.sh review-fixed
PASS API ingress has the chart router/source guard
```

Full fix (restores the chart rule while remaining harmless on kind):

```diff
diff --git a/deploy/manifests/components/cmapi/40-networkpolicy.yaml b/deploy/manifests/components/cmapi/40-networkpolicy.yaml
@@
-    - ports:
+    - from:
+        - namespaceSelector:
+            matchLabels: {network.openshift.io/policy-group: ingress}
+        - podSelector: {}
+      ports:
         - {port: 8080, protocol: TCP}
```

I did not run a kind cluster, so the source guard is proven statically against the chart, while port-forward behavior after the fix remains to be exercised by the functional job.

### Medium — plain YAML lost the chart's configuration-rollout behavior

**Evidence:** chart annotations at `deploy/helm/cmapi/templates/api.yaml:20-21` and `worker.yaml:17-18`; absent from the pod templates at `deploy/manifests/components/cmapi/20-api.yaml:28-36` and `30-worker.yaml:24-33`. The unversioned mutable ConfigMaps are `deploy/manifests/environments/kind/10-env.yaml:5-10`, `20-config.yaml:4-10`, and `30-trust.yaml:4-10`.

The chart hashes `config.yaml` into each pod template. The plain manifests instead reference mutable ConfigMaps by stable name. Kubernetes updates projected files and `envFrom` only for newly started containers; the application has no config hot reload (`build-tracker.md:58`). A GitOps change to instance, cluster, Git, or log settings therefore leaves running API and worker processes on the old configuration indefinitely.

Test actually run:

```text
$ review-tests/test-config-rollout.sh head
FAIL unversioned ConfigMap: head/deploy/manifests/environments/kind/10-env.yaml
$ review-tests/test-config-rollout.sh review-fixed
PASS ConfigMaps are immutable and versioned in both workloads
```

Full no-template fix: make the three ConfigMaps immutable/versioned, update both Deployments, and document that every environment advances the version together. The same edits must be used when `environments/crc/` is added.

```diff
diff --git a/deploy/manifests/environments/kind/10-env.yaml b/deploy/manifests/environments/kind/10-env.yaml
@@
-  name: cmapi-env
+  name: cmapi-env-v1
@@
   labels: {app.kubernetes.io/part-of: cmapi}
+immutable: true
diff --git a/deploy/manifests/environments/kind/20-config.yaml b/deploy/manifests/environments/kind/20-config.yaml
@@
-  name: cmapi-config
+  name: cmapi-config-v1
@@
     app.kubernetes.io/part-of: cmapi
+immutable: true
diff --git a/deploy/manifests/environments/kind/30-trust.yaml b/deploy/manifests/environments/kind/30-trust.yaml
@@
-  name: cmapi-trust
+  name: cmapi-trust-v1
@@
   labels: {app.kubernetes.io/part-of: cmapi}
+immutable: true
diff --git a/deploy/manifests/components/cmapi/20-api.yaml b/deploy/manifests/components/cmapi/20-api.yaml
@@
-            - configMapRef: {name: cmapi-env}
+            - configMapRef: {name: cmapi-env-v1}
@@
-          configMap: {name: cmapi-config}
+          configMap: {name: cmapi-config-v1}
@@
-                  name: cmapi-trust
+                  name: cmapi-trust-v1
diff --git a/deploy/manifests/components/cmapi/30-worker.yaml b/deploy/manifests/components/cmapi/30-worker.yaml
@@
-            - configMapRef: {name: cmapi-env}
+            - configMapRef: {name: cmapi-env-v1}
@@
-          configMap: {name: cmapi-config}
+          configMap: {name: cmapi-config-v1}
@@
-                  name: cmapi-trust
+                  name: cmapi-trust-v1
diff --git a/deploy/manifests/README.md b/deploy/manifests/README.md
@@
-| `environments/kind/` | What differs on kind: the namespaces, `cmapi-env`, `cmapi-config`, `cmapi-trust` (a stand-in CA) | a person |
+| `environments/kind/` | What differs on kind: the namespaces and the versioned `cmapi-env-v1`, `cmapi-config-v1`, `cmapi-trust-v1` (a stand-in CA) | a person |
+
+The environment ConfigMaps are immutable and versioned. To change `cmapi-env`, `cmapi-config`, or `cmapi-trust`, create
+the next `-vN` name in every environment and update both component Deployments to that name. Changing the pod-template
+reference is what rolls the api and worker; the application does not hot-reload configuration.
diff --git a/docs/12-existing-postgresql.md b/docs/12-existing-postgresql.md
@@
-| TLS | `sslmode=verify-full` against the server's CA, which the pods read from `/etc/cmapi/ca/ca-bundle.crt` (ConfigMap `cmapi-trust`) | `PGSSLROOTCERT` and `SSL_CERT_FILE` on the initContainer and the main containers |
+| TLS | `sslmode=verify-full` against the server's CA, which the pods read from `/etc/cmapi/ca/ca-bundle.crt` (versioned ConfigMap `cmapi-trust-v1`) | the Secret URI supplies `sslrootcert`; migrate initContainers also set `PGSSLROOTCERT` and `SSL_CERT_FILE` |
@@
-2. Put the server's CA in `cmapi-trust` (`environments/<env>/*trust*.yaml`), appended to the other certificates the pods
+2. Put the server's CA in `cmapi-trust-v1` (`environments/<env>/*trust*.yaml`), appended to the other certificates the pods
```

I parsed every patched YAML file with `yq`, rendered it with a digest, and confirmed that no image placeholder remained.

### Medium — the functional test cannot fail on a wrong `/version` commit

**Evidence:** `deploy/kind-test.sh:73-83`, especially line 82.

The script claims to check that `/api/v1/version` names the built commit, but a mismatch only prints `note` and returns success. A stale or incorrectly stamped image therefore passes the stated proof. Comparing against the archive's Git head would also be wrong; the authoritative expected value is the image's OCI revision label.

Test actually run:

```text
$ review-tests/test-kind-version-guard.sh head
FAIL expected commit is not read from the tested image
$ review-tests/test-kind-version-guard.sh review-fixed
PASS /version is compared fatally with the tested image stamp
```

Full fix (place the inspect after the pre-existing-cluster check from the prior finding, before creating the cluster):

```diff
diff --git a/deploy/kind-test.sh b/deploy/kind-test.sh
@@
+EXPECTED_COMMIT=$(podman image inspect "$IMAGE" --format '{{ index .Labels "org.opencontainers.image.revision" }}')
+[ -n "$EXPECTED_COMMIT" ] && [ "$EXPECTED_COMMIT" != unknown ] || { echo "ERROR: $IMAGE has no usable org.opencontainers.image.revision label" >&2; exit 1; }
@@
-EXPECT=$(git -C "$HERE/.." rev-parse --short=10 HEAD 2>/dev/null || echo unknown)
-echo "$VERSION" | grep -q "\"commit\":\"${EXPECT:0:7}" || echo "note    : /version commit does not start with the tree's HEAD ${EXPECT}; the image was built from another commit"
+VERSION_COMMIT=$(printf '%s' "$VERSION" | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"])')
+[ "$VERSION_COMMIT" = "$EXPECTED_COMMIT" ] || { echo "ERROR: /version commit $VERSION_COMMIT does not equal the tested image stamp $EXPECTED_COMMIT" >&2; exit 1; }
```

The NetworkPolicy deletion itself is narrower than this finding: it occurs only after API rollout failure, a selected migrate container's DNS failure, and successful resolution from an unselected mockup pod; this script forces the podman provider and reports both the deletion and final boolean. Rollout, HTTP status, mockup, CNPG health, and secrets failures are fatal. The commit check was the exception.

### Low — the manifests CI job still floats its runner and schema inputs

**Evidence:** `.github/workflows/ci.yml:94,116-119,121-128` and the already-recorded risk at `build-tracker.md:78`.

The job uses `ubuntu-latest`; both kubeconform schema locations use mutable branches (`master` and `main`). An upstream branch move can change validation—or break the job—without a PR change. The executable downloads are otherwise versioned and SHA-256 checked, Actions use full commit SHAs, the kind node uses a digest, permissions are `contents: read`, and checkout has `persist-credentials: false`.

Test actually run:

```text
$ review-tests/test-ci-schema-pins.sh head
FAIL manifests runner floats on ubuntu-latest
# An earlier run of the same branch check reported:
FAIL kubeconform schema URLs float on a branch
$ review-tests/test-ci-schema-pins.sh review-fixed
PASS the manifests runner and kubeconform schema URLs are pinned
```

I resolved both branch heads during this review and confirmed representative Kubernetes 1.35 and CNPG schema URLs return HTTP 200.

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
@@
   manifests:
-    runs-on: ubuntu-latest
+    runs-on: ubuntu-24.04
@@
-          SCHEMAS: https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/{{.NormalizedKubernetesVersion}}-standalone-strict/{{.ResourceKind}}{{.KindSuffix}}.json
-          CRDS: https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json
+          SCHEMAS: https://raw.githubusercontent.com/yannh/kubernetes-json-schema/102361970337d65537d40141dc29b991b8e95786/{{.NormalizedKubernetesVersion}}-standalone-strict/{{.ResourceKind}}{{.KindSuffix}}.json
+          CRDS: https://raw.githubusercontent.com/datreeio/CRDs-catalog/c86448cbf1a840ca62d119259864863897c8748a/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json
@@
-          SCHEMAS: https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/{{.NormalizedKubernetesVersion}}-standalone-strict/{{.ResourceKind}}{{.KindSuffix}}.json
-          CRDS: https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json
+          SCHEMAS: https://raw.githubusercontent.com/yannh/kubernetes-json-schema/102361970337d65537d40141dc29b991b8e95786/{{.NormalizedKubernetesVersion}}-standalone-strict/{{.ResourceKind}}{{.KindSuffix}}.json
+          CRDS: https://raw.githubusercontent.com/datreeio/CRDs-catalog/c86448cbf1a840ca62d119259864863897c8748a/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json
```

The schema bodies are not separately SHA-256 checked; pinning immutable Git objects removes the identified floating-input defect. Vendoring/checksumming them would be stronger supply-chain hardening.

### Low — the external-PostgreSQL probe contradicts its TLS/image claims

**Evidence:** `docs/12-existing-postgresql.md:17,62-64`.

The guide says `PGSSLROOTCERT` is on main containers, but only migrate initContainers set it; main processes rely on the Secret URI's explicit `sslrootcert`, which is valid but different. The probe sets `PGSSLROOTCERT=/tmp/ca.crt` while mounting the CA at `/etc/cmapi/ca`. Its JSON override also replaces the digest-pinned `--image` with floating `postgresql:17`. The URI currently masks the wrong environment path, but the command does not prove the mechanism it claims and silently discards its image pin.

Test actually run:

```text
$ review-tests/test-postgres-guide.sh head
FAIL PGSSLROOTCERT names an unmounted file
$ review-tests/test-postgres-guide.sh review-fixed
PASS the connectivity probe uses the mounted CA and only the pinned image
```

Full fix (if the versioned-ConfigMap fix above is applied, change the last `cmapi-trust` to `cmapi-trust-v1`):

```diff
diff --git a/docs/12-existing-postgresql.md b/docs/12-existing-postgresql.md
@@
-| TLS | `sslmode=verify-full` against the server's CA, which the pods read from `/etc/cmapi/ca/ca-bundle.crt` (ConfigMap `cmapi-trust`) | `PGSSLROOTCERT` and `SSL_CERT_FILE` on the initContainer and the main containers |
+| TLS | `sslmode=verify-full` against the server's CA, which the pods read from `/etc/cmapi/ca/ca-bundle.crt` (ConfigMap `cmapi-trust`) | the Secret URI supplies `sslrootcert`; migrate initContainers also set `PGSSLROOTCERT` and `SSL_CERT_FILE` |
@@
-     --env="PGSSLROOTCERT=/tmp/ca.crt" --overrides='{"spec":{"containers":[{"name":"pg-check","image":"ghcr.io/cloudnative-pg/postgresql:17","command":["sh","-c","psql \"$(cat /run/db/uri)\" -c \"select version(), current_user, ssl.ssl from pg_stat_ssl ssl where pid = pg_backend_pid()\""],"volumeMounts":[{"name":"db","mountPath":"/run/db"},{"name":"ca","mountPath":"/etc/cmapi/ca"}]}],"volumes":[{"name":"db","secret":{"secretName":"cmapi-db-app"}},{"name":"ca","configMap":{"name":"cmapi-trust"}}]}}'
+     --env="PGSSLROOTCERT=/etc/cmapi/ca/ca-bundle.crt" --overrides='{"spec":{"containers":[{"name":"pg-check","image":"ghcr.io/cloudnative-pg/postgresql:17@sha256:70664ebcfa1100361b5bdc28bbf06fdbe08db2dc4ad7bd14de33c5e05fe8ea8e","command":["sh","-c","psql \"$(cat /run/db/uri)\" -c \"select version(), current_user, ssl.ssl from pg_stat_ssl ssl where pid = pg_backend_pid()\""],"volumeMounts":[{"name":"db","mountPath":"/run/db"},{"name":"ca","mountPath":"/etc/cmapi/ca"}]}],"volumes":[{"name":"db","secret":{"secretName":"cmapi-db-app"}},{"name":"ca","configMap":{"name":"cmapi-trust"}}]}}'
```

The remaining guide claims match code/manifests: default pool size 5 with 5 overflow (`settings.py:25`, `core/db/__init__.py:26-28`), advisory lock 727364 and default 30-second `lock_timeout` (`migrations/env.py:30-34`), `cmapi-db-app` key `uri`, and `verify-full` plus `sslrootcert` in the documented Secret.

## Claim-by-claim results and sound checks

1. **Refuted in part.** The fail-open reads and empty-Secret case above violate the rotation/partial/existing-App claims. Successful-read paths, LDAP non-generation, stdin handling, and ordinary idempotence are sound. The supplied harness really can fail, but misses the two adversarial cases.
2. **Confirmed.** `render.sh` accepts only the exact GHCR digest regex unless `--allow-tag`, removes the output tree before copying, replaces all four workload image occurrences, recursively checks for `sha256:DIGEST`, and writes `IMAGE` only after success. Measured: valid render had five image strings including `IMAGE`, zero placeholders; an unallowed tag returned 1; allowed tag passed; a stale output containing a placeholder was replaced and ended with zero placeholders. ShellCheck passed.
3. **Refuted only for the NetworkPolicy guard and config rollout.** API/worker migrate initContainers, commands, DB Secret source, init/main trust mounts, probes, resources, termination periods, pod non-root/seccomp, container privilege/capability settings, and service accounts match the chart's current effective values. Chart-only `readOnlyRootFilesystem: false` is omitted but Kubernetes defaults it to false. Plain YAML intentionally uses `envFrom` for the four environment values; explicit `env` wins on collisions. The fixed `cmapi-db-app/uri` name is the documented plain-YAML contract for either CNPG or external PostgreSQL. Neither path sets `CMAPI_DATABASE_POOL_SIZE`, so code defaults to 5+5. `/readyz` is the same application handler and requires DB ping plus schema status `ok`. Extra Helm management labels and plain sync-wave annotations are non-functional differences. Trust is conditional in Helm but mandatory in plain YAML. The chart's config checksum and API source restriction are the material lost behaviors.
4. **Confirmed.** `cluster.yaml:13` uses the documented comma-separated resource sync options: `Prune=false` prevents Git removal from pruning the Cluster, and `Delete=false` prevents Application deletion from deleting it ([Argo CD sync-options documentation](https://argo-cd.readthedocs.io/en/latest/user-guide/sync-options/)). The PostgreSQL image is a 64-hex digest reference. `spec.storage` contains only `size`; no manifest names a StorageClass.
5. **Confirmed literally.** Kind namespaces, stand-in URLs/config, and stand-in CA are under `environments/kind/`; no kind-only object/value is in `components/`. Components are byte-identical inputs for every render. The OpenShift ingress selector restored above is platform-specific but harmless when absent and does not make the component tree vary.
6. **Refuted for cluster ownership and version checking.** The DNS-policy deletion condition and reporting are sound as noted above; the ownership trap and non-fatal commit comparison are not.
7. **Refuted for floating inputs.** Least permissions, credential persistence, action pins, binary checksums, kind/node pins, and failure propagation are sound. The runner and schemas float as described above.
8. **Refuted narrowly.** The deployment itself supports TLS verification and the factual code values are otherwise correct, but the only documented probe has the path/image defects above. No external-server run exists, as the guide correctly admits.
9. **Confirmed against the export.** `build-tracker.md` and `HANDOVER-AND-RESUME.md` agree on base `1f30ab1`, PR #89, no cmapi workload on CRC, the next Wave 1, ownership, decisions, risks, and later waves. They link the rules, design, status, and test record needed to continue. The export contains every referenced local document/log I checked. I could not independently verify the external claims that CI run `42130344182` is green at `e8afca9`, that this archive equals that SHA, or the stated live CRC inventory because the export has no Git metadata and I did not query GitHub or the cluster.

## Verification performed

- Read the exact diff and all three required documents in full.
- Rendered the Helm API/worker at this head and compared it with both plain Deployments and the NetworkPolicy.
- Ran all eight focused before/after tests shown above.
- Ran ShellCheck on all original deployment scripts and on patched `secrets.sh`/`kind-test.sh`.
- Parsed every patched manifest with `yq` and reran `render.sh` with a digest.
- Checked the supplied kind/secrets logs for the asserted milestones and test credential literals.
- Checked the PostgreSQL guide against `settings.py`, `core/db`, migration environment, health handler, and both Deployments.
- Verified the Argo CD retention semantics against official documentation and checked the two proposed schema commit URLs.

## Not checked

- No live kind, OpenShift, CNPG, Keycloak, LDAP, external PostgreSQL, OVN NetworkPolicy, SCC, or Route test was run.
- No GitHub run/head SHA was queried.
- I did not rerun `secrets-test.sh` on a cluster; I relied on its supplied successful log and used narrower executable stubs for the missing cases.
- I could not run kubeconform locally because it is not installed in this export environment; the original CI result is external evidence only.

The high findings must be fixed before merge. The NetworkPolicy and non-fatal version proof should also block applying this commit to the shared cluster; the remaining findings should be fixed in the same PR because they affect first-run reproducibility and the only external-database runbook.
