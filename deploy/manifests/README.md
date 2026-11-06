# cmapi from plain YAML

Every file here is a Kubernetes object a person can read and apply with `kubectl apply --server-side -R -f` (or `oc`;
server-side because the mockup ConfigMap is larger than a client-side apply's last-applied annotation allows, measured). No Helm, no
Kustomize, no templating: there are two substitutions, both in `deploy/render.sh`, which fills them into a copy of this tree:
the image digest (placeholder `ghcr.io/ephico2real2/cmapi@sha256:DIGEST`) and the configuration checksum
(placeholder `CMAPI_CONFIG_CHECKSUM`, in the `checksum/config` annotation of the api's and the worker's pod templates). A
copy with either left in fails the render. Argo CD reads the rendered copy as a recursive directory (the deployment design, `docs/reviews/2026-11-05-deployment-design.md`);
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

What the charts did that these files do not, so a person or `environments/<env>/` must:

- **A changed `cmapi-config`, `cmapi-env` or `cmapi-trust` restarts the api and the worker only through a render.** The
  process reads its config once, at start. `deploy/render.sh` puts a SHA-256 over those three files into the pod templates
  (as the chart's `checksum/config` did), so render again and apply both the environment and the components. Applying a
  changed ConfigMap alone restarts nothing.
- **`cmapi-env` on CRC carries `CMAPI_OIDC_JWKS_URL` and `CMAPI_KEYCLOAK_ADMIN_URL`** (the Keycloak Service, as
  `deploy/environments/crc.yaml` sets them), or the pods go through the issuer's Route.
- **Namespace `cmapi-imports` must exist first** (it does not on CRC, measured 2026-11-05; the chart created it): the
  imports reader Role lives there, and `kubectl apply -R` stops short of it otherwise. `environments/crc/` carries it
  until the bootstrap set of Wave 2 does.
- **Secret `cmapi-test-users`** (the realm sync's test users, optional) is not written by `deploy/secrets.sh`.
