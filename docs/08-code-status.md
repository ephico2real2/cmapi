# Code status: what is built, and what is not

The short answer: **no, this is not the full cmapi code yet.** What exists:

- the complete design;
- working, tested code for the core business logic;
- a local application that runs that logic end to end against real Keycloak, Git and
  Kubernetes, with stand-ins for Argo CD, capacity and the database.

The production service is not built yet:

- its PostgreSQL store;
- the GitHub/GitLab, Argo CD and OpenShift adapters;
- the capacity service;
- the portal;
- packaging.

The Module catalog in [02-technical-design-v2.md](02-technical-design-v2.md#module-catalog) is the
authoritative list. It names every module with its phase and one of three statuses:

| Status | Meaning |
| --- | --- |
| Reference code | Exists and is tested |
| Protocol | The interface is fixed in `core/ports.py`; no adapter yet |
| Specified | Designed only |

This page summarises it.

## 1. Built and tested: the core logic (`examples/src/cmapi`, about 2,700 lines, 120 tests)

| Module | What it does |
| --- | --- |
| `core/tiers.py` | Tier catalog: resolve, custom bounds, normalise, match, compare, render, tier hash |
| `core/approvals.py` | Approval rules (environment, patterns, thresholds), auto-approval guards, approval ledger with matching |
| `core/expression.py` | The `when:` language of approval-rules.yaml |
| `core/lifecycle.py` | Request state machine, lock and reservation ownership |
| `core/metadata.py` | Label and annotation classes, validation, merge patch, change facts, render order |
| `core/identity/claims.py`, `checks.py`, `directory.py`, `keycloak_admin.py` | Identity from the token; automation accounts (bot-user) and bots requesting in their own name or onBehalfOf; team DL and email domains; DirectoryProvider with cache; Keycloak admin client |
| `core/authz.py` | Keycloak roles to permissions (`authz-roles.yaml`): the built-in roles including `cmapi-onboarding` (create only); optional per-role environments; no team or namespace-name scoping |
| `core/naming.py` | Namespace names: DNS-1123, reserved names, never take over an unmanaged namespace |
| `core/render/manifests.py` | The plain-manifest renderer, plan hash, file diff |
| `core/listquery.py` | Paging, search, cursor, facets, CSV export |
| `core/ratelimit.py` | Token buckets |
| `core/config.py` | Instance config loading and cross-file checks (no hot reload yet) |
| `core/errors.py` | RFC 9457 problems |
| `core/ports.py` | Protocols for every extension point |
| `plugins/expiration/rules.py` | Expiration limits, grace and notices |

## 2. Built for the local run only (`examples/local`, about 1,300 lines)

This code makes the logic above run end to end. It is demo-grade: one process, state in memory.

| Piece | Local version | Production module it stands in for |
| --- | --- | --- |
| Token verification (JWKS, audience, issuer) and role checks | `caller()` and `CFG.roles` in `app.py` | `core/auth.py` |
| Plan and submit | `plan_namespace()`, `submit()` in `app.py` | `core/pipeline.py` |
| Endpoints | `/me`, `/tiers`, `/directory/users`; namespace create, patch, delete; `expiration:extend`; `/requests` list and get, `:approve`, `:reject`, `:cancel`; `/admin/prune:confirm`; `/quotas`; `/healthz`; `/admin/git-log` | `routers/*`, `plugins/*` (partly) |
| Git | `LocalGit`: a bare repository; a PR is a branch | `core/git/` GitHub and GitLab REST adapters |
| CI checks | `LocalValidator`: kubeconform and the Kyverno CLI, run in-process | `core/validate/` plus the Git host's CI and the cmapi check |
| Cluster reads and sync | `KubeCluster`: kubectl against k3s, kind or any cluster; applies the merged folder in place of Argo CD | `core/clients/` (kube watch cache, argocd), `core/sync.py`, and Argo CD itself |
| Capacity | `SimulatedCapacity`: a fixed cluster size | cmapi-capacity |
| Worker | A thread: open PR, checks, merge, apply, prune hold | `worker.py` and `jobs/` |
| Store | Python dicts | `core/db/` with PostgreSQL |
| Realm setup | `keycloak_setup.py` | `examples/cmapi-sso/realm/ephico2real.yaml` and LDAP federation |

## 3. Not built yet

**Service foundation**

- The production service layout: routers per plugin, startup checks that every route is
  documented, and `/openapi.yaml`.
- `core/db/`: SQLAlchemy models, Alembic migrations, `audit_events`.
- `core/kpi/` and `/metrics`.
- Config hot reload.

**Adapters**

- GitHub and GitLab `GitProvider`: PRs, branch protection, the cmapi check as a check run.
- Argo CD client and the sync webhook.
- OpenShift `KubeReader` with a watch cache.
- Policy report reader.
- Optional LDAP directory.

**Endpoints not yet wired:**

| Area | Endpoints |
| --- | --- |
| Requests | `:retry`, `:revert`, `/events` |
| Expiration | `:set`, `:makePermanent`, `GET /expirations` |
| Tiers | `/tiers/{tier}`, `/tiers/{tier}/namespaces` |
| Quotas | `:suggest`, `:export` |
| Metadata | metadata endpoints |
| Service accounts | service accounts, grants, SCC grants, SA token issuance |
| Policies | policies |
| Clusters | cluster import (the six checks) |
| Capacity | capacity and placement |
| Other plugins | adoption, reports |
| Operations | operations |
| Admin | admin KPI, reload, auto-approval pause/resume |

**Worker jobs:** `approval_timeout`, `channel_notify`, `expire_check`, `reservation_expiry`,
`policy_report_sweep`, `import_clusters`, `reconcile`, `kpi_export`, `outbox_publish`, `operations`.

**Approval channels and notifications:** email links, ServiceNow, Argo Events, chat; `Notifier`.

**cmapi-capacity:** Thanos source, snapshots, placement, reservations, usage sweep.

**Portal:** only the clickable mockups exist (`mockups/`). The portal app (React with TypeScript, built with Vite, using PatternFly) is not built.

**Packaging and delivery:**

- container images (Dockerfiles);
- the Helm chart (only `examples/helm/values-kpi.yaml` exists);
- CI pipelines for cmapi's own repository;
- the Kyverno bundle release;
- `cmapi-sdk` and a CLI.

## 4. Suggested order to finish it

This follows the delivery plan's phases:

| Phase | Work |
| --- | --- |
| 1 | Service skeleton, `core/auth.py`, `core/db/` with migrations, `/me`, directory, OpenShift reader, cluster import |
| 2 | The namespaces plugin on the real pipeline, GitHub adapter and cmapi check, Argo CD sync, requests router, worker jobs, email approval channel, Helm chart and images. Phase 2 is the first deployable cmapi |
| 3 | cmapi-capacity and the quotas plugin |
| 4 | Service accounts, grants, SA tokens |
| 5 | Expiration plugin and `expire_check`, policies, adoption, operations, reconcile |
| 6 | Usage analysis |

The portal follows the API: Quotas, Requests and Approvals first.
