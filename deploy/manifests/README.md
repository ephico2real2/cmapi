# cmapi from plain YAML

Every file here is a Kubernetes object a person can read and apply with `kubectl apply --server-side -R -f` (or `oc`;
server-side because the mockup ConfigMap is larger than a client-side apply's last-applied annotation allows, measured). No Helm, no
Kustomize, no templating: the one substitution is the image digest, which `deploy/render.sh` fills into a copy of this
tree (`ghcr.io/ephico2real2/cmapi@sha256:DIGEST` is the placeholder; a copy with it left in fails the render). Argo CD
reads the rendered copy as a recursive directory (the deployment design, `docs/reviews/2026-11-05-deployment-design.md`);
the `argocd.argoproj.io/sync-wave` annotations order it there and mean nothing to `kubectl`.

| Folder | What | Applied by |
|---|---|---|
| `components/database-cnpg/` | CloudNativePG `Cluster` `cmapi-db` (omit it for an existing PostgreSQL: `docs/12-existing-postgresql.md`) | Argo CD, or a person on kind |
| `components/cmapi/` | ServiceAccounts, the imports reader Role, the api and the worker (migrations as initContainers), the metrics NetworkPolicy | same |
| `components/portal/` | The standalone mockup behind nginx, until the portal runs on the API | same |
| `environments/kind/` | What differs on kind: the namespaces, `cmapi-env`, `cmapi-config`, `cmapi-trust` (a stand-in CA) | a person |

Secrets are not here: `deploy/secrets.sh` writes `cmapi-keys`, `cmapi-keycloak` (with its copy `cmapi-realm-secrets` in
the Keycloak namespace) and `cmapi-github-app`, and checks `cmapi-ldap-bind`; CNPG writes `cmapi-db-app`. Monitoring
objects (ServiceMonitors, PrometheusRule) and the realm-sync Job need CRDs and services kind does not have, so they
arrive with `environments/crc/` in the CRC pull request, not in `components/`.

Order for a person: namespaces, the CNPG operator (1.30.1, a prerequisite, not here), `environments/<env>/`,
`deploy/secrets.sh`, then `components/` through `deploy/render.sh`'s output. `deploy/kind-test.sh` does exactly that on a
`cmapi-test` kind cluster and is the functional test.
