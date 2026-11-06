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

Fixed in the harness (an array, `"${A[@]}"`), shellcheck clean on 0.11.0 (see "The first CI run"), and rerun on a fresh throwaway `cmapi-test` kind
cluster (same node image), the cluster up for 93 s and deleted by name: **all ten cases pass**
(`2026-11-05-plain-manifests-test-logs/secrets-test.log`, verbatim lines):

```
  ok   1 fresh: rc=0 wrote Secret sect1/cmapi-keys
  ok   2 second run: rc=0 cmapi-keys: present, kept
  ok   3 ours deleted, copied from the realm: rc=0 cmapi-keys: present, kept
  ok   4 partial realm copy stops: rc=1 ERROR: partial realm copy, missing CMAPI_DIRECTORY_SECRET. A realm keeps the values it first imported, so nothing is generated. ...
  ok   5 partial realm copy, ours gone, stops: rc=1 ERROR: partial realm copy, missing CMAPI_DIRECTORY_SECRET. ...
  ok   6 all gone, no realm import: generates: rc=0 cmapi-keys: present, kept
  ok   7 copies differ, stops: rc=1 ERROR: copies differ on automationClientSecret. ...
  ok   8 realm import exists, both copies gone: stops: rc=1 ERROR: KeycloakRealmImport cmapi exists in sect2 and both Secrets are gone. New values would not match the realm. ...
  ok   9a ldap-bind missing stops: rc=1 ERROR: Secret sect1/cmapi-ldap-bind is missing; the owner creates it (docs/11), this script never does
  ok   9b ldap-bind lacking a key stops: rc=1 ERROR: Secret sect2/cmapi-ldap-bind lacks password
  ok   9c ldap-bind copies differ stops: rc=1 ERROR: cmapi-ldap-bind differs between the namespaces on password; make them equal by hand, nothing is written
  ok   9d ldap-bind equal passes: rc=0 cmapi-ldap-bind: present in both namespaces with bindDN and password, equal
  ok   10a app secret written from a 0600 file: rc=0 wrote Secret sect1/cmapi-github-app
  ok   10b existing app secret lacking a key stops, not replaced: rc=1 ERROR: Secret sect1/cmapi-github-app exists but lacks privateKey; it is never replaced automatically: fix or delete it by hand
  ok   10c a key file that others can read is refused: rc=2 ERROR: ... is mode 644; make it 0600
secrets cases failed: 0
```

The two Python tracebacks in the raw output were the harness's hash helper reading an absent Secret in cases 5 and 8
(expected absent); its stderr is now silenced. No defect in `secrets.sh` was found by the cases.

**The shared-service guard** (the coordinator's: `keycloak-0` on CRC had restarted at 20:17:02 UTC, cause unknown,
while an earlier `cmapi-test` was up): `oc get pod keycloak-0 -n keycloak`, read-only, before and after this run:
restart count **1** both times, `startedAt 2026-11-05T20:17:08Z` both times. This 93 s cluster did not coincide with a
restart.

## The first CI run

Run 42129295237 on `66c038a`: `manifests` failed at `Shellcheck`, SC2015 on `deploy/secrets.sh:109` and
`deploy/secrets-test.sh:32`, and every later step was skipped. "Shellcheck clean" above was measured on this Mac's 0.11.0; the
job installed apt's, which is 0.9.0-1 on Ubuntu 24.04 (measured in an `ubuntu:24.04` container, where the same files give
rc 1, as does the 0.9.0 release binary here). ShellCheck's changelog for v0.11.0: "SC2015 about `A && B || C` no longer
triggers when B is a test command", and both lines' B is a test, so neither was a defect. The cause was an unpinned tool:
the job now installs shellcheck 0.11.0 by version and SHA-256, as it does kubeconform and kind. Both lines are also rewritten
as `if`, so the five scripts give rc 0 on 0.9.0 and on 0.11.0, and a person on a distribution's shellcheck sees no noise.
The rewrites change no result: compared before and after for each combination of the two ids (`secrets.sh`, stub kubectl)
and each outcome of the two tests (case 6).

The render step's `! grep` could not fail: `bash -e` does not stop on a negated command (measured). It is an `if` now.

## The whole script to exit 0, after the review of PR #89

The runs above are the first ones. Until this one `kind-test.sh` had never exited 0 on record: it stopped at the harness bug,
and the ten cases passed in a separate cluster. Run at `16fa0fedcb`, with the review's fixes and the coordinator's rulings
(`2026-11-05-pr89/README.md`), on a fresh **`cmapi-test` kind cluster** (podman, kind v0.33.0, node v1.35.8), with an image built
from that commit. Log: `2026-11-05-pr89/results/kind-test-16fa0fedcb.log`. Exit code 0 in 417 s; the script deleted the cluster.

```
[187s] cmapi-db: Cluster in healthy state
[268s] MEASURED: the migrate container ... cannot resolve cmapi-db-rw while the mockup pod (not selected) can ... Deleting the policy for this test only
[341s] ready: cmapi-api-5f67b85bc6-2pqmg true 0; cmapi-db-1 true 0; cmapi-mockup-864587966-r8wzw true 0; cmapi-worker-f4c8ddc9b-hq29f true 0;
[346s] measured, with the migrate container's env: pg_stat_ssl True TLSv1.3
readyz: 200 {"status":"ok","database":"ok","schema":"ok"}
version: {"version":"0.2.0","commit":"16fa0fedcb","component":"api"}
mockup: 200
[382s] replaced: pod/cmapi-api-5f67b85bc6-2pqmg pod/cmapi-worker-f4c8ddc9b-hq29f ; the new pods read CMAPI_LOG_LEVEL=DEBUG
secrets cases failed: 0
[417s] done; NetworkPolicy deleted for DNS: true
```

`keycloak-0` on CRC, read with `oc get pod keycloak-0 -n keycloak` before and after: restart count **1** both times.

**The podman-kind DNS failure still happens, so on this run the NetworkPolicy was deleted before the pods started**, as above.
What that leaves unproven, and what was measured instead, on a kept `cmapi-test` cluster at `b4a60eb24a`
(`2026-11-05-pr89/results/`):

| Question | Measured |
|---|---|
| Is the restored `from` rule what stops another namespace? (`on-kind.txt`) | With no policy another namespace, this namespace and a port-forward all reach port 8080. With the policy another namespace is blocked and the other two still reach it |
| Do the kubelet's probes pass under that rule? (`np-probes.txt`) | Applied to running pods for 180 s: api and worker stayed Ready, 0 restarts. No pod was started under it here, because of the DNS failure. That needs the hosted runner or CRC |
| Is the migrate container's connection to CNPG encrypted? (`tls-measure.txt`) | With its env as it ships: `pg_stat_ssl True TLSv1.3`. With `PGSSLROOTCERT` added, as before patch 09: `False None`, so it did fall back to plaintext on CNPG. With `hostnossl all all all reject` in CNPG's `pg_hba`, the real migrate container of a restarted api exited 0, and the old env was refused (`no encryption`) |

The connection is encrypted and **does not verify the server**: CNPG's `uri` has no `sslmode`, so libpq uses `prefer`.

Each new test was also run against the code from before its fix (`2026-11-05-pr89/results/before-after/`). `deploy/tests/` holds
what CI can run without a cluster, and `np-reach-test.sh` on the job's. Not on real clusters: the 15 s settle catching a real
crash (stubs only), and docs/12 section 5's corrected sequence as one piece.

## Not done

- The `manifests` CI job: its result is cited in the pull request from the run whose `headSha` is the branch head.
- `environments/crc/`, the bootstrap set, Argo CD and anything on CRC: later pull requests, by the deployment design.
