# cmapi on CRC: build status

Branch `app-on-crc`. This file is the hand-over: another session must be able to continue from it
alone. Everything under "Measured" was seen on the cluster; everything else is inferred or planned.

## Where it is

| Step | State |
| --- | --- |
| Reference package moved to the service tree (`cmapi/src/cmapi`, tests in `cmapi/tests/core`; `examples/src/cmapi` and `examples/tests` are symlinks to them) | Done, 120 tests pass from both paths |
| Service: auth, db, pipeline, routers, worker, Git adapter, validator, cluster reader, delivery | Not started |
| Images and Helm chart | Not started |
| Deployed on CRC | Namespace `cmapi` created, nothing in it yet |
| Portal on the API | Not started |

## Measured on the cluster

- `oc adm top node` before any cmapi workload: `crc 2017m 25% 15601Mi 79%` (first read), `2250m 28% 15704Mi 80%` (second read, ~10 min later).
- `oc version`: client 4.22.18, server 4.22.14, Kubernetes v1.35.6. Host: x86_64 macOS, podman machine `podman-machine-default` (applehv, 2 GiB, amd64) started for image builds; `podman login default-route-openshift-image-registry.apps-crc.testing` with `oc whoami -t` succeeded.
- Keycloak: RHBK operator in namespace `keycloak`, CR `keycloak`, hostname `https://keycloak.apps-crc.testing`, TLS from cert-manager ClusterIssuer `enterprise-ca` (CA subject `CN=LDAP Enterprise Root CA`, also in `keycloak-tls` as `ca.crt`). Existing realms are imported through `KeycloakRealmImport` CRs (`corp`, inkcast). From a pod in `cmapi`: `keycloak.apps-crc.testing` resolves to 192.168.127.2 and both `https://keycloak.apps-crc.testing/realms/master` and `https://keycloak-service.keycloak.svc:8443/realms/master` answer 200.
- Operators present cluster-wide: CloudNativePG 1.30.1 (`inkcast-db/inkcast-pg` is a running example), Cluster Observability Operator 1.5.3 (Perses CRDs), cert-manager. User workload monitoring is on (`enableUserWorkload: true`); `thanos-querier.openshift-monitoring.svc:9091` answers 401 from a pod (reachable, needs a token). Not present: Argo CD, Kyverno, Gitea, Tekton.
- Default StorageClass `crc-csi-hostpath-provisioner` (WaitForFirstConsumer).

## Cluster objects created so far

| Kind | Name | Scope |
| --- | --- | --- |
| Namespace | `cmapi` | cluster-scoped |

## Decisions taken (owner to review)

1. The reference package moved from `examples/src/cmapi` to `cmapi/src/cmapi` with symlinks left behind, so the documented paths still work and `examples/local` still runs.

## Resume

```bash
cd /Users/olasumbo/gitRepos/cmapi-design-crc
git pull
V=$(mktemp -d)/venv; python3 -m venv $V; $V/bin/pip install -q -r examples/local/requirements.txt
(cd cmapi && PYTHONPATH=src:tests/core $V/bin/python -m pytest -q tests/core)
```
