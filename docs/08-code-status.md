# Code status: what is built, and what is not

Updated 2026-11-05 with PR #40 (branch `app-on-crc`). The short answer: **the production service exists
as code and tests, and nothing of it runs on a cluster yet.** What exists:

- the complete design;
- the core business logic, tested (section 1);
- the production service built on it: PostgreSQL store, the write pipeline, Git host adapters, the
  validator, the cluster registry, the worker, an image and Helm charts (section 2);
- the local application `examples/local` with its stand-ins (section 3).

Not built: the portal on the API (the React app still runs the mockup's sample logic), the CLI and
SDK, cmapi-capacity, and every plugin after the namespaces one. No cluster has run the service:
`CRC-BUILD-STATUS.md` records what has been measured and what has not.

The Module catalog in [02-technical-design-v2.md](02-technical-design-v2.md#module-catalog) is the
authoritative list of modules, phases and the three statuses (Reference code, Protocol, Specified).
This page summarises what the code tree holds today.

## 1. Core logic (`cmapi/src/cmapi/core`, reference modules; 120 tests in `cmapi/tests/core`)

`examples/src/cmapi` and `examples/tests` are symlinks to these, so the documented paths still work.

| Module | What it does |
| --- | --- |
| `core/tiers.py` | Tier catalog: resolve, custom bounds, normalise, match, compare, render, tier hash |
| `core/approvals.py` | Approval rules, auto-approval guards (the kill switch now reports `paused` as its fallback), the ledger |
| `core/expression.py` | The `when:` language of approval-rules.yaml |
| `core/lifecycle.py` | Request state machine, lock and reservation ownership |
| `core/metadata.py` | Label and annotation classes, validation, merge patch, change facts, render order |
| `core/identity/claims.py`, `checks.py`, `directory.py`, `keycloak_admin.py` | Identity from the token, onBehalfOf, automation accounts, the DirectoryProvider with its cache, the Keycloak admin client |
| `core/authz.py` | Keycloak roles to permissions (`authz-roles.yaml`) |
| `core/naming.py` | Namespace names: DNS-1123, reserved, never an unmanaged namespace |
| `core/render/manifests.py` | The plain-manifest renderer, plan hash, file diff |
| `core/listquery.py` | Paging, search, cursor (now bound to the caller's scope through `context`), facets, CSV |
| `core/ratelimit.py` | Token buckets; **no route uses it yet** |
| `core/config.py` | Instance config loading and cross-file checks (no hot reload) |
| `core/errors.py`, `core/ports.py` | RFC 9457 problems; the Protocols of every extension point |
| `plugins/expiration/rules.py` | Expiration limits, grace and notices |

## 2. The service (`cmapi/`, tested in `cmapi/tests/service` against PostgreSQL with in-memory fakes for the Git host and the cluster)

| Piece | Where | Status |
| --- | --- | --- |
| App factory, documented routers, `/docs`, `/redoc`, `/openapi.json` and `.yaml`; an undocumented route stops startup | `main.py`, `core/docs.py` | Built; contract test in `tests/service/test_api_contract.py` |
| Token verification: RS256, iss and aud pinned, JWKS cached with single-flight refresh, stale-on-error with a persisted key set, `typ` other than `Bearer` refused | `core/auth.py` | Built and tested |
| PostgreSQL store: change requests (one open request per namespace by a partial unique index), events, approvals (one per person per request), a `SKIP LOCKED` jobs queue with leases and a fencing generation, audit, JWKS cache, admin switches | `core/db/`, migrations `0001` to `0003` | Built; migrations run as an initContainer on every pod, serialised by an advisory lock |
| The write pipeline: authorize, idempotency (key plus body fingerprint), lock, plan, decide; If-Match on changes | `core/pipeline.py`, `plugins/namespaces/router.py` | Built and tested |
| Requests: list (paged), get, events, approval-status, `:approve`, `:reject`, `:cancel`, `:retry`, `:revert`; decisions serialised by a row lock | `routers/requests.py` | Built and tested |
| Admin: `prune:confirm`, the auto-approval kill switch, integrations, Git log, KPIs | `routers/admin.py`, `core/kpi.py` | Built; KPIs read the database and the pod's cgroup |
| Tiers, directory, quotas (list, suggest, CSV export) | `plugins/tiers`, `plugins/directory`, `plugins/quotas` | Built |
| Cluster registry: the six import checks, a list-then-watch cache per cluster | `core/registry.py`, `core/clients/kube.py` | Built; the watch proven against a real kube-apiserver in the review, not on CRC |
| Git host: Gitea (the stand-in on CRC, **being replaced by GitHub, GitHub Actions and GHCR**, #85) and GitHub | `core/git/` | Gitea proven against a real Gitea in the reviews; the provider contract (`contains()`, `changed_paths`, statuses, merge) holds on both adapters by mock, and so do GitHub's check runs (conclusions, pagination, re-runs: `tests/service/test_github_check_runs.py`, #87); **GitHub never exercised against GitHub** (#61) |
| Validator: Kyverno CLI and kubeconform, schemas baked into the image | `core/validate/` | Built |
| Delivery: `argocd` (the design, the default, and what CRC's values select, #63) or `apply` (a deviation a site must acknowledge) | `core/sync.py`, `jobs/watch_sync.py` | Both built and tested with fakes; **nothing has run on a real Argo CD**, and its objects (install, Application, AppProject, repository credential) do not exist on CRC. `apply` is implemented and fake-tested; argocd status parsing exists (`revision`, `revisions`, per-object `resources`, `contains()` on the Git adapter), its convergence and prune observation are tested with fakes only |
| Worker: `open_pr`, `pr_checks` (the cmapi check as a commit status; on GitHub it reads `ci/*` from Actions' check runs, on the Gitea stand-in it posts them), `watch_sync`, `prune` (bounded: a cluster that cannot be read, unreachable or its reader never connecting, waits for `delivery.syncTimeout` on one clock then ends in `sync_failed`; a refusal, a removed cluster or a bug ends there after five attempts; a namespace seen present waits for the operator and `CmapiPruneStuck` alerts), `approval_timeout`, `channel_notify`, `open_revert`; lease heartbeat and `JobRepo.fence()` before every external write (Git, cluster, commit statuses, notifications) | `worker.py`, `jobs/` | Built and tested with fakes; the fence's row lock and the blocked heartbeat measured by Codex with three workers against a real Gitea, not under kubelet |
| Approval channels: portal, email (signed link) | `core/channels.py` | Built; email never sent in a test |
| Capacity | `core/capacity_backend.py` | **Simulated** from `clusters.yaml`; cmapi-capacity, placement and reservations are not built, and the `cmapi-capacity` entry point was removed until the component exists |
| Image | `cmapi/Containerfile` | Built locally; not pushed to a cluster |
| Plain manifests | `deploy/manifests/` (`components/database-cnpg`, `components/cmapi`, `components/portal` for the mockup, `environments/kind`), `deploy/render.sh`, `deploy/secrets.sh`, `deploy/kind-test.sh`, `deploy/tests/`, `docs/12-existing-postgresql.md` | The deployment path (#88): `deploy/kind-test.sh` exits 0 on a `cmapi-test` kind cluster against CNPG 1.30.1: api and worker Ready, the migrate environment over TLS, `/readyz` 200, `/api/v1/version` naming the built commit, a changed `cmapi-env` restarting both, the secrets cases green. On podman kind the NetworkPolicy is deleted first by the DNS failure, and the job's `np-reach-test.sh` measures it (`docs/reviews/2026-11-05-plain-manifests-test.md`). Not on CRC yet; `environments/crc/`, the bootstrap set and Argo CD are later pull requests |
| Helm charts | `deploy/helm/cmapi`, `deploy/helm/cmapi-git` | Lint and render; never installed. **Not the deployment path**: the owner decided (2026-11-05) to deploy with plain YAML first (`deploy/manifests/<component>/`, `oc apply`) and to write charts later, one per independently running component under `helm/`, none for Keycloak or LDAP; these charts and their tests stay until the YAML replaces them |
| Release script (`--atomic --cleanup-on-fail` unless `RELEASE_ATOMIC=false`), setup tools (`cmapi-tools git-bootstrap`, `realm-sync`) | `deploy/release-crc.sh`, `cmapi/src/cmapi/tools` | Setup tools run by the reviews against real Gitea and Keycloak in containers; the release script only with stubs; neither on a cluster |

## 3. Built for the local run only (`examples/local`, about 1,300 lines)

Unchanged: one process, state in memory, stand-ins for Git, CI, Argo CD and capacity. It still runs
against the symlinked reference modules; section 2 is what replaces each stand-in.

## 4. Not built yet

**Service:** config hot reload; `core/kpi/` beyond the system figures and four database KPIs; the metadata
plugin; `:probe`, `/admin/reload`, `/tiers/{tier}`, the webhooks; OpenTelemetry (none in the code);
rate limits on routes.

**Adapters:** OpenShift reader beyond the kinds the namespaces plugin needs; policy report reader; LDAP
directory provider; Argo CD mode proven against a real Argo CD (none has run).

**Endpoints not yet wired:** expiration `:set`, `:makePermanent`, `GET /expirations`; `/tiers/{tier}`,
`/tiers/{tier}/namespaces`; quota writes other than the namespace PATCH; metadata; service accounts,
grants, SCC grants, SA tokens; policies; cluster import endpoint; capacity and placement; adoption,
reports, operations; admin reload.

**Worker jobs:** `expire_check`, `reservation_expiry`, `policy_report_sweep`, `import_clusters` (the
registry relists instead), `reconcile`, `kpi_export`, `outbox_publish`, `operations`.

**cmapi-capacity:** all of it.

**Portal:** `cmapi-portal-ui/` still runs the mockup's sample logic with no sign-in and no API call; it
must not be deployed as the portal (`MOCKUP-CONTRACT.md`). The chart's `portal.enabled` is off.

**CLI and SDK:** not started.

**Delivery:** CI runs the reference, service and portal suites (`.github/workflows/ci.yml`); no image
build or chart lint in CI yet; the Kyverno bundle release.

## 5. Order to finish it

Unchanged from the delivery plan: the thin slice on CRC first (phases 1 and 2 verified end to end), then
phase 3 (cmapi-capacity, quotas), 4 (service accounts), 5 (lifecycle, policies, operations, launch), 6.
The portal follows the API: New namespace, Requests and Approvals first.
