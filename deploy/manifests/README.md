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
| `environments/crc/` | What differs on CRC: the namespaces, `cmapi-env`, `cmapi-config`, `cmapi-trust` (Keycloak's CA, written by `deploy/crc-trust.sh`), the Routes, the monitoring objects. `reader/` holds the reader baseline, and `realm/` the realm import and the realm-sync Job | a person, by [`docs/13-crc-deployment.md`](../../docs/13-crc-deployment.md) |

Secrets are not here: `deploy/secrets.sh` writes `cmapi-keys`, `cmapi-keycloak` (with its copy `cmapi-realm-secrets` in
the Keycloak namespace), `cmapi-test-users` with `--test-users`, and `cmapi-github-app`, and checks `cmapi-ldap-bind`; CNPG
writes `cmapi-db-app` and `cmapi-db-ca`. `secrets.sh` requires `--issuer` or `--no-issuer-check`, so that CRC cannot skip asking the
realm by forgetting a flag. Monitoring objects (ServiceMonitors, PrometheusRule) and the realm-sync Job need CRDs and services kind
does not have, so they live in `environments/crc/`, not in `components/`.

Every environment connects to CNPG the same way, so it is in `components/cmapi/`, not in `environments/<env>/`: the api, the worker and
both migrate containers set `PGSSLMODE=verify-full` and read `ca.crt` of `cmapi-db-ca` through the `trust` volume. A `ca.crt` that CNPG
renews reaches running pods through that volume, with no restart; `checksum/config` does not read it.

Measured on a `cmapi-test` kind cluster on Podman (CloudNativePG 1.30.1), 2026-11-13, by `deploy/kind-test.sh`:

| Manifests | Each of the four containers, as deployed | The same container with a CA that does not cover the server |
|---|---|---|
| Before #91 | `connected True TLSv1.3 prefer`: TLS, and nothing verified | `connected False None prefer`: libpq fell back to plaintext without a word |
| With #91 | `connected True TLSv1.3 verify-full` | `refused ... SSL error: certificate verify failed` |

The four containers are the api, the worker and the migrate container of each. On the fixed manifests `pg_stat_ssl` showed 1 TLS and 0 plaintext connection for the api pod and for the worker pod. `deploy/tests/external-db-test.sh` then ran `docs/12`'s route on the same cluster: 0 of its 13 cases failed. The NetworkPolicy was deleted for these runs, as `kind-test.sh` does on Podman kind, so they say nothing about the policy. Not measured on CRC yet: `deploy/crc-proof.sh` reads each container's `sslmode` there.

`environments/crc/`: `oc apply --server-side --field-manager=cmapi-wave1 -f environment/` applies its top-level files. Never
`-R`: `reader/` and `realm/` are applied by name, in the steps of `docs/13-crc-deployment.md`. Their files are outside what
`render.sh`'s checksum reads, and only `realm/20-realm-sync.yaml` carries an image placeholder of the environment's own.

Order for a person: namespaces, the CNPG operator (1.30.1, a prerequisite, not here), `environments/<env>/`,
`deploy/secrets.sh`, then `components/` through `deploy/render.sh`'s output. `deploy/kind-test.sh` does exactly that on a
`cmapi-test` kind cluster and is the functional test.

What the charts did that these files do not, so a person or `environments/<env>/` must:

- **A changed `cmapi-config`, `cmapi-env` or `cmapi-trust` restarts the api and the worker only through a render.** The
  process reads its config once, at start. `deploy/render.sh` puts a SHA-256 over those three files into the pod templates
  (as the chart's `checksum/config` did), so render again and apply the environment, then the components, in that order:
  pods restarted by the components before the ConfigMap changes read the old values, carry the new checksum, and nothing
  restarts them again. Applying a changed ConfigMap alone restarts nothing.
- **`cmapi-env` on CRC carries `CMAPI_OIDC_JWKS_URL` and `CMAPI_KEYCLOAK_ADMIN_URL`** (the Keycloak Service, as
  `deploy/environments/crc.yaml` sets them), or the pods go through the issuer's Route.
- **Namespace `cmapi-imports` must exist first** (it does not on CRC, measured 2026-11-05; the chart created it): the
  imports reader Role lives there, and `kubectl apply -R` stops short of it otherwise. `environments/crc/` carries it
  until the bootstrap set of Wave 2 does.
- **Secret `cmapi-test-users`** (the realm sync's test users) is written by `deploy/secrets.sh` only with `--test-users`, once, and never rotated.
