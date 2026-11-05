# cmapi on CRC: build status

Branch `app-on-crc`. This file is the hand-over: another session must be able to continue from it
alone. Everything under "Measured" was seen on the cluster or run on this Mac; everything else is
inferred or planned. Updated 2026-11-05, at the stopping point before the first review.

## Where it is

| Step | State |
| --- | --- |
| Reference package moved to the service tree (`cmapi/src/cmapi`, tests in `cmapi/tests/core`; `examples/src/cmapi` and `examples/tests` are symlinks to them) | Done: 120 tests pass from both paths |
| Service (`cmapi/src/cmapi`): `core/auth.py`, `core/docs.py`, `core/db/` with the Alembic schema, `core/pipeline.py`, `core/registry.py` (six import checks, watch cache), `core/git/` (Gitea, GitHub), `core/validate/`, `core/sync.py` (delivery `argocd` or `apply`), routers (me, clusters, requests, admin), plugins (namespaces, tiers, directory, quotas), the worker and its jobs | Built. 30 service tests pass against a PostgreSQL in the podman machine with in-memory fakes for the Git host and the cluster |
| Image `cmapi/Containerfile` (UBI9 python-312-minimal, kyverno 1.16.2 and kubeconform 0.6.7 by checksum, Swagger UI and ReDoc bundled) | Built locally as `cmapi:dev`, 549 MB; tools, static files and the commit stamp verified in the container. Not pushed to CRC yet |
| Helm charts `deploy/helm/cmapi` (api, worker, portal, CNPG database, RBAC, Route or Ingress, trust bundle, ServiceMonitors, PrometheusRule, migrate Job, git-bootstrap Job, realm-sync Job, KeycloakRealmImport) and `deploy/helm/cmapi-git` (Gitea stand-in) | Written; `helm lint` passes; `helm template` renders 28 objects for CRC (`deploy/environments/crc.yaml`) and the Ingress variant for kind. Never installed yet |
| `deploy/release-crc.sh` (build, stamp check, push `sha-<commit>`, lock file by digest, `helm upgrade -f`) | Written, not run end to end |
| `cmapi-tools git-bootstrap` and `realm-sync` (the chart's Jobs) | Written, import cleanly, not run against a host |
| Deployed on CRC | Namespace `cmapi` exists and is empty. Nothing of cmapi runs on the cluster yet |
| Portal on the API | Not started; `cmapi-portal-ui` is unchanged apart from the merge of `main` (the "Use this size" fix). The portal Containerfile is not written, so `deploy/release-crc.sh` fails at the portal build until it is; `portal.enabled: false` in `deploy/environments/crc.yaml` |
| CLI and `cmapi-sdk` | Not started (in scope after the thin slice, per the coordinator) |
| `docs/10-architecture-review.md` | Written at the start of the build; the twelve-factor and observability rows marked *to measure* are still unmeasured |
| `docs/08-code-status.md` | **Not yet updated**: it still describes the pre-service state. To be updated with the first cluster-verified step |

## Measured

- `oc adm top node` before any cmapi workload: `crc 2017m 25% 15601Mi 79%` (first read), `2250m 28% 15704Mi 80%`, later `16049Mi 82%` (coordinator's read). Nothing of cmapi has been added to the cluster, so there is no "after" yet.
- `oc version`: client 4.22.18, server 4.22.14, Kubernetes v1.35.6. Host: x86_64 macOS; podman machine `podman-machine-default` (applehv, 2 GiB, 8 CPUs, rootless, amd64) was stopped at the start and started by this build; `podman login default-route-openshift-image-registry.apps-crc.testing` with the ingress CA (`--cert-dir`) succeeded. A throwaway `postgres:16-alpine` container `cmapi-test-pg` runs in that machine on port 55432 for the service tests; its clock is about one second ahead of the Mac's.
- Existing Keycloak (`docs/11`): RHBK operator, OperatorGroup `targetNamespaces: [keycloak]`, CR `keycloak`, hostname `https://keycloak.apps-crc.testing`, TLS from ClusterIssuer `enterprise-ca` (CA `CN=LDAP Enterprise Root CA`, in `keycloak-tls` as `ca.crt`); `curl` from this Mac fails verification (`ssl=20`) until given that CA; from a pod in `cmapi`, `keycloak.apps-crc.testing` resolves to 192.168.127.2 and both the Route and `keycloak-service.keycloak.svc:8443` answer 200. Existing imports `corp`, `inkcast-prod`, `inkcast-staging`, `tutorial` are `Done=True`; `corp` federates LDAP read-only with its bind password as a placeholder from Secret `keycloak-ldap-bind`.
- Existing LDAP server (`docs/11`): `ldap-testing`, people `john.doe`, `jane.smith`, `bob.wilson`, `alice.cooper`, `charlie.brown` under `ou=People` with `uidNumber` 10001 to 10005 (read from ConfigMap `ldap-structure`); the ten `cmapi-*` groups added on `main` by the main session. No write of mine touched it.
- Operators present: CloudNativePG 1.30.1 (`Database` CRD present; `inkcast-db/inkcast-pg` runs with requests 256Mi, limit 512Mi, 2Gi storage), Cluster Observability Operator 1.5.3, cert-manager; user workload monitoring on; `thanos-querier.openshift-monitoring.svc:9091` answers 401 from a pod. Absent: Argo CD, Kyverno, Gitea, Tekton, KEDA, an OpenTelemetry collector.
- Default StorageClass `crc-csi-hostpath-provisioner` (WaitForFirstConsumer). Pods in `cmapi` reach pypi.org (200); the earlier probe of raw.githubusercontent.com printed nothing, so kubeconform's online schema fetch is **unverified** from a pod.
- Tests on this Mac: `cmapi/tests/core` 120 passed; `cmapi/tests/service` 30 passed (auth rules, the documented-API contract, the write path from plan to synced, approvals, refusals, If-Match, idempotency, a PR edited after approval, a changed base, delete with prune confirmation, a Git outage with retries, the kill switch).

## Cluster objects created so far

| Kind | Name | Scope | Created by |
| --- | --- | --- | --- |
| Namespace | `cmapi` | cluster-scoped | `oc create ns` (empty) |

The chart will add, when first installed (not yet done): in `cmapi` the Deployments, Services, Secrets, ConfigMaps, Jobs, the CNPG `Cluster`, ServiceMonitors, PrometheusRule, NetworkPolicy, Routes; namespace `cmapi-imports` with Role and RoleBinding `cmapi-imports-reader`; ClusterRole and ClusterRoleBinding `cmapi-deliverer` (the worker's write identity for `apply` delivery); in namespace `keycloak` the `KeycloakRealmImport` `cmapi` and Secret `cmapi-realm-secrets` (its placeholders). Removal: `helm uninstall cmapi -n cmapi`, then the `keep` objects by name (`oc delete keycloakrealmimport cmapi secret cmapi-realm-secrets -n keycloak`, the realm itself through Keycloak's admin console as the owner decides, `oc delete clusterrole,clusterrolebinding cmapi-deliverer`, `oc delete ns cmapi cmapi-imports`).

## Decisions taken (owner to review)

1. The reference package moved to `cmapi/src/cmapi` with symlinks left at the documented paths.
2. SQLAlchemy with psycopg 3, synchronous, instead of the asyncpg named in `docs/02`: the reference modules, the Git and cluster adapters and the worker are synchronous, and FastAPI runs sync handlers in a thread pool. Not yet reflected in `docs/02`.
3. Delivery to a cluster without Argo CD: `integrations.yaml` `delivery.mode: apply` (the worker server-side applies the merged folder from Git `main` as a separate `cmapi-deliverer` identity, confirms by a read, holds deletes for the operator's `POST /admin/prune:confirm`). `argocd` is the design's mode and the `ArgoCdSignal` adapter exists; it is unproven on CRC. Recorded in `docs/10` §5; `docs/01` and `docs/02` not yet amended.
4. Two reference modules changed with tests: the kill switch reports `paused` as the auto-approval fallback; `ListQuery` gained `context` so a cursor is bound to a caller's scope without filtering rows.
5. Realm `cmapi` in the existing Keycloak through a `KeycloakRealmImport` plus one placeholder Secret in namespace `keycloak` (`cmapi-realm-secrets`, generated), the pattern the existing imports use. Mutable parts (user profile, group-to-role mappings, LDAP federation, local test users) converge through the `cmapi-realm-admin` service client in the realm sync Job. LDAP federation is configured only when Secret `cmapi-ldap-bind` (`bindDN`, `password`) exists in `cmapi`, which is the owner's pending step; until then local users `ola`, `amy`, `opal`, `bot-user` with generated passwords (Secret `cmapi-test-users`).
6. The Gitea stand-in uses basic auth for the bot (`CMAPI_GIT_USER`/`CMAPI_GIT_PASSWORD`), so no token generation step is needed; the GitHub adapter uses a token.
7. Kyverno CI checks run in the worker's `pr_checks` job and are posted as commit statuses (`ci/kubeconform`, `ci/kyverno`, `cmapi/check`) that branch protection requires; on a real GitHub the same contexts come from Actions and the cmapi check reads `GET /requests/{id}/approval-status`.

## Review this step (pre-loop work)

Commit range `72d082b..HEAD` on `app-on-crc`. What to attack: `core/auth.py` (stale-on-error and the 503 path), `core/db/repo.py` (`move()` lock re-check, `JobRepo.claim` lease), `core/pipeline.py` (If-Match, idempotency fingerprint, the `old_hard` branch), `jobs/pr_checks.py` (the cmapi check equality), `jobs/watch_sync.py` (retry vs. failure after the timeout, `attempts = 0` resets), `core/registry.py` (cert-verify classification by string match), the chart's `secrets.yaml` `lookup` pattern, and the realm template.

## Resume

```bash
cd /Users/olasumbo/gitRepos/cmapi-design-crc && git pull
python3 -m venv .venv && .venv/bin/pip install -q -e "cmapi[test]"
podman machine start; podman start cmapi-test-pg || podman run -d --name cmapi-test-pg -e POSTGRES_PASSWORD=cmapi -e POSTGRES_USER=cmapi -e POSTGRES_DB=cmapi -p 55432:5432 docker.io/library/postgres:16-alpine
(cd cmapi && PYTHONPATH=src:tests/core ../.venv/bin/python -m pytest -q tests/core && PYTHONPATH=src:tests/service ../.venv/bin/python -m pytest -q tests/service -W ignore)
helm lint deploy/helm/cmapi -f deploy/environments/crc.yaml --set cmapi.tag=x --set cmapi_portal.tag=x
```

Next step (needs its arbitrated design first, per the delivery loop): the thin slice on CRC. In order: `deploy/release-crc.sh --no-portal` (flag still to add), `helm install cmapi-git`, fill `trustedCA.certificates` in `crc.yaml` from `keycloak-tls` `ca.crt` and `default-ingress-cert`, the baseline (`cmapi-system/cmapi-reader`, `cmapi-token-issuer`, the import Secret in `cmapi-imports`), then one namespace request with a real token through approval, PR and apply, measured with `oc adm top node` before and after.
