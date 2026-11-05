# Functional test record: the plain manifests (#88)

Run by Fable on 2026-11-05 with `deploy/kind-test.sh localhost/cmapi:dev` on a **`cmapi-test` kind cluster** on this
Mac (`KIND_EXPERIMENTAL_PROVIDER=podman`, kind v0.33.0, node image `kindest/node:v1.35.8@sha256:07b2536e…`, CloudNativePG
operator 1.30.1 applied from `cnpg-1.30.1.yaml`, SHA-256 verified, image built locally from `main` 1f30ab1 with
`podman build`). Nothing on CRC. The log is `2026-11-05-plain-manifests-test-logs/kind-test.log` (no secret values in
it: the script prints only which Secrets it wrote). The cluster was deleted by name at the end (`kind get clusters`
empty, no `cmapi-test-control-plane` container).

## What passed (measured, verbatim from the log)

```
[259s] components applied (server-side)
[367s] cmapi-db: Cluster in healthy state
[449s] MEASURED: the migrate container (selected by the ingress-only NetworkPolicy cmapi-metrics) cannot resolve cmapi-db-rw while the mockup pod (not selected) can: the podman-kind DNS failure under a NetworkPolicy. Deleting the policy for this test only; it ships, and the hosted runner and CRC decide
deployment "cmapi-api" successfully rolled out
deployment "cmapi-worker" successfully rolled out
deployment "cmapi-mockup" successfully rolled out
[461s] ready: cmapi-api-678c6fdb7c-gmr9t true 0; cmapi-db-1 true 0; cmapi-mockup-864587966-2txdj true 0; cmapi-worker-5d44d697c9-25cp9 true 0
readyz: 200 {"status":"ok","database":"ok","schema":"ok"}
version: {"version":"0.2.0","commit":"1f30ab1ac4","component":"api"}
mockup: 200
```

- `kubectl apply --server-side -R` of the rendered `components/` after `environments/kind/`, `deploy/secrets.sh`
  (`wrote Secret cmapi-imports/cmapi-realm-secrets`, `cmapi/cmapi-keycloak`, `cmapi/cmapi-keys`) and
  `deploy/render.sh kind localhost/cmapi:dev --allow-tag`.
- The CNPG `Cluster` healthy 108 s after apply; the migrate initContainers ran `cmapi-migrate head`; api, worker and
  the mockup Ready with 0 restarts; `/readyz` 200 with `schema: ok`; `/api/v1/version` names `1f30ab1ac4`, the commit
  the image was built from (the tree's head is later, which the script notes); the mockup serves `portal.html`.
- Two facts measured on the way, both now in the scripts and the README: a client-side apply of the mockup ConfigMap
  (300 KB) fails with `metadata.annotations: Too long: may not be more than 262144 bytes`, so the components are applied
  server-side (Argo CD applies server-side too); and under the ingress-only `cmapi-metrics` NetworkPolicy the migrate
  container could not resolve `cmapi-db-rw` (`psycopg.OperationalError: failed to resolve host 'cmapi-db-rw.cmapi':
  Name or service not known`, `Init:CrashLoopBackOff` after the 540 s wait) while the mockup pod, which the policy does
  not select, resolved it. That is the podman-kind failure the deployment design recorded for Argo CD's policies
  (ruling 8: cause unknown, podman kind only). **The policy ships unchanged**; the test deletes it on podman kind only
  after proving that pair, and says so in its output. The hosted runner (Docker) and CRC (OVN-Kubernetes) decide.

## What did not pass: the secrets cases, on a harness bug

The deployment above exercised `deploy/secrets.sh` on its first-install path (three Secrets written, the api and the
worker read them). `deploy/secrets-test.sh`, which runs the ten cases, reported `secrets cases failed: 13` with every
case failing from the start. **Cause, verified at the argument layer, not inferred:** the harness built its common
arguments as a word-split string, so `--kubectl "kubectl --kubeconfig=…"` arrived as `--kubectl kubectl
--kubeconfig=…` and `secrets.sh` refused `--kubeconfig=…` as an unknown argument (reproduced:
`deploy/secrets.sh … --kubectl kubectl --kubeconfig=/nonexistent …` → `unknown argument --kubeconfig=/nonexistent`,
rc 2; the quoted form reaches kubectl). `kind-test.sh` passes it quoted, which is why the deployment half worked.

Fixed in the harness (an array, `"${A[@]}"`), shellcheck clean, and the parsing re-checked without a cluster (the first
case now fails on the missing kubeconfig, not on an argument). **The ten cases have not been rerun on a cluster**: the
owner stopped work after the run above. They are the next step before this pull request is opened.

## Not done

- The secrets cases on a cluster (above).
- The `manifests` CI job has not run (no pull request yet).
- `environments/crc/`, the bootstrap set, Argo CD and anything on CRC: later pull requests, by the deployment design.
