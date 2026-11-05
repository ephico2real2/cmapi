# Architecture review: cmapi built to the `/app-architect` standard

A living document. It is written from the code and `docs/01` and `docs/02`, with the skill's rules of
evidence: every number names the command and its output, every finding its fix and its test, and a
claim with no evidence is a question. The subject is the repository at `cmapi/` (the service),
`cmapi-portal-ui/` (the portal) and `deploy/` (the chart), deployed on the CRC cluster of this Mac.
Each phase of the build updates this file; `CRC-BUILD-STATUS.md` holds the hand-over.

Written 2026-11-05 at the start of the build, before any service pod existed. Rows marked *to measure*
are hypotheses until a measurement supports them.

## 1. Inventory

**Code.** Python 3.12 service (`cmapi/src/cmapi`): FastAPI app factory (`main.py`), a worker
(`worker.py`), one image with three entry points (api, worker, capacity). Portal: React 19.3.1,
TypeScript, Vite 8.3.5, PatternFly 6.7.0 (`cmapi-portal-ui/package.json`). Inbound: HTTPS from the
portal, the CLI and pipelines, all with Keycloak bearer tokens. Outbound: Keycloak (JWKS, admin API as
`cmapi-directory`), the Git host REST API (Gitea on CRC, GitHub adapter unproven there), the cluster
API through `cmapi-reader`, Thanos Querier (capacity), PostgreSQL. Data store: one PostgreSQL. Queue: the
`jobs` table with `FOR UPDATE SKIP LOCKED` (no broker). Schedulers: recurring job rows (approval
timeout, expire check, snapshots).

**Tool stack.** Versions are the pins in `cmapi/pyproject.toml`, `cmapi-portal-ui/package.json` and
`deploy/`; licences from each project's repository; CNCF status from
[cncf.io/projects](https://www.cncf.io/projects/) read on 2026-11-05 (the page lists graduated and
incubating projects only).

| Tool | Version | Licence | Open source | CNCF | Portable alternative |
| --- | --- | --- | --- | --- | --- |
| FastAPI / Starlette / uvicorn | 0.115.6 / 0.41.3 / 0.32.1 | MIT / BSD-3 / BSD-3 | yes | none | any ASGI framework |
| Pydantic (+ settings) | 2.14.2 / 2.16.2 | MIT | yes | none | — |
| SQLAlchemy / psycopg / Alembic | 2.1.8 / 3.3.8 / 1.20.1 | MIT / LGPL-3 / MIT | yes | none | — |
| PyJWT, httpx, PyYAML, structlog, prometheus-client | 2.10.1, 0.28.1, 6.0.2, 26.1.0, 0.24.1 | MIT, BSD-3, MIT, MIT/Apache-2.0, Apache-2.0 | yes | none | — |
| PostgreSQL via CloudNativePG | operator 1.30.1 on CRC (`oc get csv -n openshift-operators`) | PostgreSQL / Apache-2.0 | yes | CloudNativePG: incubating | Crunchy, Zalando operator, a managed PostgreSQL |
| Keycloak (Red Hat build) | RHBK operator on CRC, CR `keycloak` in namespace `keycloak` | Apache-2.0 | yes | incubating | any OIDC issuer (the Authenticator extension point) |
| Gitea (Git host stand-in on CRC) | 1.25 rootless (`deploy/helm/cmapi-git`) | MIT | yes | none | GitHub, GitLab (GitProvider adapters) |
| Kyverno CLI + kubeconform | 1.16.2 + 0.6.7, baked into the image | Apache-2.0 both | yes | Kyverno: graduated | conftest (Validator extension point) |
| Prometheus (user workload monitoring on CRC) | OpenShift 4.22.14 stack | Apache-2.0 | yes | graduated | any OpenMetrics scraper |
| Perses (Cluster Observability Operator 1.5.3 on CRC) | COO 1.5.3 | Apache-2.0 | yes | not on the CNCF page read; status not verified here | Grafana (chart value `dashboards.provider`) |
| Argo CD | not installed on CRC | Apache-2.0 | yes | graduated | built-in `apply` delivery (see §5) |
| Helm | 4.x client on the Mac (`helm version`) | Apache-2.0 | yes | graduated | plain manifests from `helm template` |
| OpenTelemetry | planned (§3) | Apache-2.0 | yes | graduated | — |
| KEDA | not installed on CRC (`oc get crd scaledobjects.keda.sh`: none) | Apache-2.0 | yes | graduated | plain HPA (§7) |

**Build and deploy today.** `deploy/release-crc.sh`: podman build on the host, push to CRC's internal
registry under `sha-<commit>`, the digest recorded in `deploy/images.lock.yaml`, `helm upgrade -f
deploy/environments/crc.yaml` deploying by digest. The build refuses a dirty tree. Autoscaling: none yet
(§7).

## 2. Twelve-factor scorecard

| Factor | Today | Gap | Fix | Phase |
| --- | --- | --- | --- | --- |
| I Codebase | One repo, branch `app-on-crc` | — | — | — |
| II Dependencies | Pinned in `pyproject.toml` and `package-lock.json`; CLI binaries pinned by version and SHA-256 in the Containerfile | — | — | 1 |
| III Config | Instance files from ConfigMaps, secrets from Secrets, the rest `CMAPI_*` env (`cmapi/src/cmapi/settings.py`) | — | — | 1 |
| IV Backing services | PostgreSQL, Keycloak, Git host and clusters reached by URL and credential; adapters behind `core/ports.py` | — | — | 1 |
| V Build, release, run | Image by commit, release = chart + values + lock file | — | — | 1 |
| VI Processes | API stateless; worker state in PostgreSQL; JWKS cache in memory with a persisted copy | watch cache is per pod (by design, a read cache) | — | 1 |
| VII Port binding | uvicorn on 8080, metrics on 9090 | — | — | 1 |
| VIII Concurrency | Worker claims jobs with `SKIP LOCKED`; API replicas share nothing | **not proven**: no test has scaled out yet | run two worker replicas on kind, submit N requests, assert each job ran once (`jobs.attempts`, `locked_by`) | 2 |
| IX Disposability | SIGTERM handled by uvicorn; the worker finishes the current job then exits; a job lease expires if a worker dies | *to measure* on the cluster: kill a worker mid-job and watch the lease expire | — | 2 |
| X Dev/prod parity | kind and CRC from one chart; local run `examples/local` differs by design (stand-ins) | — | — | 2 |
| XI Logs | structlog JSON on stdout | — | — | 1 |
| XII Admin processes | `cmapi-migrate` as a pre-upgrade Job; `/admin/*` routes gated by roles | — | — | 1 |

## 3. Observability against the layered standard

OpenTelemetry is the only pipeline: the SDK in the process, OTLP out when a collector exists
(`CMAPI_OTEL_EXPORTER_OTLP_ENDPOINT`), off by default as `docs/01` says. Metrics stay in the Prometheus
format on `/metrics` because the hub's user workload monitoring scrapes it; traces and logs go over
OTLP. No collector is installed on CRC (`oc get crd opentelemetrycollectors.opentelemetry.io`: none), and
the hard limits forbid a cluster-wide operator for it, so on CRC the exporter stays off and the
instrumentation is proven by the in-process span export to stdout in the integration test.

| Call or dependency | Layer | Evidence | Gap |
| --- | --- | --- | --- |
| Inbound HTTP | L1 (FastAPI instrumentation) + RED metrics `cmapi_http_*` (`core/observability.py`) | `/metrics` scraped on CRC | — |
| Keycloak JWKS, admin API | L1 (httpx instrumentation); `cmapi_jwks_refresh_total`, `cmapi_auth_failures_total` | — | *to measure* |
| PostgreSQL | L1 (SQLAlchemy instrumentation); pool gauges | — | *to measure* |
| Git host | L1 httpx + `cmapi_git_operations_total{operation,result}` | — | — |
| Cluster API | L1 httpx + `cmapi_cluster_api_calls_total` | — | — |
| Worker job loop | L3: one span per job with `job.kind` and `request_id`; `cmapi_worker_last_loop_timestamp_seconds` (the "healthy but dead loop" lesson from group-sync-dashboard's `GroupSyncDashboardNotPolling`) | alert `CmapiWorkerNotLooping` | — |
| Business operations: plan, submit, approve, merge, sync | L3 spans and `cmapi_change_requests_total`, `cmapi_change_lead_time_seconds` | — | — |
| Context through the queue | W3C `traceparent` stored in `jobs.payload` and restored when the job runs | *to measure* | — |
| Baggage | `cmapi.instance`, `cmapi.cluster_id`, `cmapi.plugin` set at the front door and copied by an allow-listed span processor; never a user or a token | — | — |
| CI guard | `cmapi/tests/core/test_api_contract.py`: every `/api` route documented (startup check `core/docs.py`), every outbound client instrumented | — | — |

Personal data (names, employee ID) and tokens never go in telemetry: structlog logs `sub`, `username`,
`client`, never a token; spans carry no label values from the request body.

## 4. Security, adversarially (STRIDE per trust boundary)

| Boundary | Threats considered | Control in code | Test |
| --- | --- | --- | --- |
| Internet → Route → cmapi-api | Spoofing (forged JWT), tampering (alg=none, HS256 key confusion), DoS | `core/auth.py`: RS256 only, `kid` required, `iss` and `aud` pinned per instance, `exp`/`nbf` with 30 s leeway, JWKS refetched once on an unknown `kid`, stale-on-error with a persisted copy; 503 `idp-unavailable` never 401 when no key is cached; rate limits (`core/ratelimit.py`) | `tests/core/test_auth.py`: wrong issuer, wrong audience, expired, `alg=none`, unknown kid with Keycloak down |
| cmapi → Keycloak admin API | Elevation (the directory credential) | `cmapi-directory` holds `view-users` and `query-users` only; secret from a Kubernetes Secret, never in the realm CR | realm import reviewed; `GET /admin/realms/cmapi/users` with the credential returns 200, `POST` returns 403 (*to measure*) |
| cmapi → Git host | Tampering (a PR edited after approval), repudiation | Plan hash stored at submit, re-checked before the PR opens and before the merge (`jobs/pr_checks.py`); the bot token is the only identity that merges under `clusters/`; branch protection requires the `cmapi/check` status | integration: edit the bot branch after approval → `failed`, cmapi check `failure` |
| cmapi → cluster (read) | Elevation | `cmapi-reader` ClusterRole from `examples/baseline/cmapi-reader-rbac.yaml`: get/list/watch only; the import check refuses a token whose identity is not `cmapi-system:cmapi-reader` | `oc auth can-i create namespaces --as=system:serviceaccount:cmapi-system:cmapi-reader` → no |
| worker → cluster (apply delivery on CRC) | Elevation, tampering | A separate `cmapi-deliverer` identity used only by the worker's delivery job, applying only what Git `main` holds; never held by the API pods | the API SA cannot create namespaces (`oc auth can-i`) |
| Portal (browser) → Keycloak | Spoofing, CSRF | Authorization Code + PKCE through the public `cmapi-portal` client, redirect URIs pinned to the portal Route; tokens in memory, not local storage | Playwright walk: a token from `cmapi-cli` cannot be used by the portal client (different `azp`, same audience: allowed by design; recorded) |
| Secrets | Information disclosure | Nothing secret in git, logs or the report; generated Secrets; the Git token and DB URL only as env from Secrets; the idempotency cache never keeps token-issuing responses | `git grep` of the tree for `password:`/`token:` with values is part of `deploy/check.sh` |
| Supply chain | Tampering | Base images by digest, CLI tarballs by SHA-256, Python pins, npm lock | the Containerfile fails on a checksum mismatch |

Input handling: every body is a Pydantic model with `extra="forbid"`; namespace names, labels and
annotations go through `core/naming.py` and `core/metadata.py` (DNS-1123, reserved prefixes, size caps).

## 5. Architecture and modernization

cmapi is already the modular monolith `docs/01` describes: one image, three entry points, plugins
behind one pipeline, adapters behind `core/ports.py`. No further split is recommended; cmapi-capacity is
the one separately deployable service the design names (isolation of Thanos work), and it runs
embedded (`capacity.mode: embedded`) on CRC to save memory.

**Delivery without Argo CD on CRC.** `docs/01` has every write applied by each cluster's Argo CD. CRC
has no Argo CD, and installing OpenShift GitOps is a cluster-wide operator the hard limits refuse while a
namespace-scoped way exists. The build adds a `delivery` setting to `config/integrations.yaml`:
`argocd` (the design: the worker only reads Applications) or `apply` (the worker applies the merged
folder from Git `main` with a separate deliverer credential, confirmed by a read, and holds deletes for
an operator exactly as `Prune=confirm` does). `apply` is the built-in default for a cluster with no
GitOps; it is recorded in `docs/01` and `docs/02` as a design change. An Argo CD installed from its Helm
chart into `cmapi-argocd` (namespace-scoped, CRDs cluster-scoped) is the widening step once memory
allows; the `argocd` SyncSignal adapter exists either way and is proven on kind.

**Lifecycle and recovery** (to prove on the running system, phase 2): a worker killed mid-job leaves a
lease that expires and the job runs again idempotently (open_pr checks for an existing branch; merge
checks the PR state first); a Git host outage marks jobs failed with backoff, never a terminal request
state until five attempts; a PostgreSQL failover reconnects through `pool_pre_ping`.

## 6. Portability and platform

| Concern | Open standard | Default open-source implementation | OpenShift | AWS | Azure | Google Cloud |
| --- | --- | --- | --- | --- | --- | --- |
| Identity | OIDC, OAuth 2 device grant, PKCE | Keycloak | RHBK | Cognito (OIDC) | Entra ID (OIDC) | Identity Platform (OIDC) |
| Relational store | SQL, PostgreSQL wire protocol | PostgreSQL via CloudNativePG | same | RDS / Aurora PostgreSQL | Azure Database for PostgreSQL | Cloud SQL for PostgreSQL |
| Delivery | GitOps (Argo CD Application CRD) | Argo CD | OpenShift GitOps | [Amazon EKS capability for Argo CD](https://aws.amazon.com/blogs/containers/deep-dive-streamlining-gitops-with-amazon-eks-capability-for-argo-cd) (verified 2026-11-05: a managed control plane outside the cluster) | AKS GitOps extension runs Flux v2, not Argo CD (verified 2026-11-05 through [Qovery's comparison](https://www.qovery.com/blog/argo-cd-alternatives-managed-gitops-control-plane); Argo CD itself must be self-run) | not verified: no result named a managed Argo CD on GKE; Config Sync is Google's own GitOps |
| Metrics | OpenMetrics / Prometheus format | Prometheus | user workload monitoring | Amazon Managed Service for Prometheus | Azure Monitor managed Prometheus | Managed Service for Prometheus |
| Traces and logs | OTLP, W3C trace context | OpenTelemetry Collector | OpenTelemetry (Red Hat build) | X-Ray via ADOT | Azure Monitor OTLP | Cloud Trace / Logging OTLP |
| Event-driven autoscaling | KEDA ScaledObject | KEDA | KEDA (Custom Metrics Autoscaler operator) | **not verified**: no managed KEDA add-on found for EKS on 2026-11-05 ([AWS guidance](https://aws.amazon.com/solutions/guidance/event-driven-application-autoscaling-with-keda-on-amazon-eks) runs it self-managed) | [AKS KEDA add-on](https://learn.microsoft.com/is-is/azure/aks/keda-about), verified 2026-11-05 | **not verified**: none found |
| Ingress | Ingress / Gateway API | Ingress (chart value `exposure: Ingress`) | Route (`exposure: Route`, `spec.subdomain`) | ALB controller | Application Gateway | GKE Ingress |
| Secrets | Kubernetes Secret, External Secrets Operator interface | generated Secrets | same | Secrets Manager via ESO | Key Vault via ESO | Secret Manager via ESO |
| Feature flags | OpenFeature | not used (no flag today) | — | — | — | — |

Images: built outside the cluster, pushed under `sha-<commit>`, deployed by digest from
`deploy/images.lock.yaml`; the running pod serves the commit at `GET /api/v1/version`. On kind a local
registry container (`kind-registry`) stands in for CRC's internal registry; `kind load` is not used.

## 7. Scaling and elasticity

| Workload | Signal | Why | Readiness checks |
| --- | --- | --- | --- |
| cmapi-api | request rate and p95 latency from `cmapi_http_request_duration_seconds` (KEDA Prometheus scaler, or a plain HPA on CPU where KEDA is absent) | stateless, request-driven | readiness = DB ping + config loaded; SIGTERM drains uvicorn |
| cmapi-worker | `cmapi_jobs_pending` (KEDA PostgreSQL scaler: `SELECT count(*) FROM jobs WHERE done_at IS NULL AND run_after <= now()`), min 1 | backlog-driven; jobs are idempotent and claimed with leases | the recurring jobs are singletons by the `uq_jobs_pending` index, not by a leader |
| cmapi-capacity | cron (snapshot interval) | scheduled load | advisory lock per job |

KEDA is not on CRC and will not be installed here (hard limit); the ScaledObjects ship in the chart off
by default (`autoscaling.keda.enabled`), with the PostgreSQL scaler's identity a separate read-only
role and its TLS from the CNPG server CA, never `unsafeSsl`. Proof planned on kind, phase 3.

## 8. CI/CD

GitHub Actions is the project's CI (none exists yet on this branch): unit tests, the API contract test,
the portal suites, image build with SBOM and a scan, chart lint and `helm template` against the kind
values. Argo CD deploys from `deploy/environments/*.yaml`. Added in phase 2.

## 9. Product capabilities that make the app operable

The portal's KPIs tab (`GET /api/v1/admin/kpi`) is the admin view of the app's own health. Business
logic is explicit in `core/approvals.py` and `core/lifecycle.py` and instrumented per request.
Fraud analytics from the skill's list do not apply: cmapi has no payments or external users; recorded
here, not built.

## 10. Roadmap, mapped to `docs/08` section 4

| Step | Proof (runnable) |
| --- | --- |
| Now: phase 1 and 2 thin slice on CRC | `deploy/e2e/walk.sh`: one namespace request from the portal through approval and a PR to a namespace on CRC |
| Next: phase 2 widening (retry, revert, events, email channel, superseded), phase 3 (capacity from Thanos, quotas, placement) | the walk extended; `tests/integration` on kind |
| Later: phases 4 to 6 | per-phase sections appended here with their evidence |
