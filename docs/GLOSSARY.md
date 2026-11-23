# Glossary of cmapi names and abbreviations

This page explains the names, abbreviations, IDs and technical terms that the cmapi code, documents, issues, pull requests and agent reports use. Each entry gives the meaning and the file that defines it or first uses it. Where one name has two meanings, the entry says so.

Keep it current. A change can add a new name, ID, status, header or technology to the code, a document, an issue or a pull request. If it does, the same change adds its row here.

Status: read from `main` at `afd1206` on 2026-11-23. Each row was read from the source in its last column. A line number or a count can move with later commits. Where a document and the code disagree, the row says what the code does.

## The product and its code

| Term | Meaning | Source |
|---|---|---|
| cmapi | The product: one API and portal to ask for, change and inspect namespaces across every OpenShift cluster. Every write becomes a pull request to a cluster-configs repository, and each cluster's Argo CD applies it. cmapi never writes to a cluster directly in `argocd` delivery mode. | [README.md](../README.md) |
| Instance | One running copy of cmapi, for one network zone. The reference design has three: `nonprod` (environments `rnd`, `dev`), `staging` (`qa`, `uat`) and `prod` (`prod`). Each has its own configuration files, token audience and Git repository. The names are the owner's choice, and cmapi reads them from the configuration. | [18-configuration.md](18-configuration.md) |
| The api | The FastAPI process that serves `/api/v1`. Its entry point is `cmapi-api` (`cmapi.main:run`). | [pyproject.toml](../cmapi/pyproject.toml) |
| The worker | The second process of an instance (`cmapi-worker`, `cmapi.worker:run`). It runs the jobs: open the pull request, push the branch, apply, merge, watch the sync, renew tokens, prune rejections. | [pyproject.toml](../cmapi/pyproject.toml), [jobs/](../cmapi/src/cmapi/jobs/) |
| `cmapi-tools` | The command line of the package (`cmapi.tools:run`). Its tools include `openapi render`, `policies render` and `policies check`, `docs-assets`, a realm sync and a Git bootstrap. | [pyproject.toml](../cmapi/pyproject.toml), [tools/](../cmapi/src/cmapi/tools/) |
| `cmapi-migrate` | The command that runs the Alembic migrations (`cmapi.core.db.migrate:run`). | [pyproject.toml](../cmapi/pyproject.toml) |
| `cmapi/core` | The code that every plugin shares: the pipeline, the lifecycle, authorization, the problem registry, the Git layer, the database. | [core/](../cmapi/src/cmapi/core/) |
| Plugin | A module that adds routes to the API. The built-in plugins are `namespaces`, `tiers`, `directory`, `quotas`, `expiration`, `policies` and `capacity`. A plugin that `plugins.yaml` does not enable has no route and no line in the API document. | [core/plugins.py](../cmapi/src/cmapi/core/plugins.py) |
| `WRITERS` | The set of plugins that have a write. Only `namespaces` is in it, so an override in `plugins.yaml` can stop only its writes. | [core/plugins.py](../cmapi/src/cmapi/core/plugins.py) |
| `plugins.yaml` | Optional file with `enabled` (the plugins to mount) and `overrides.<instance>.<env>.disabled` (stops the writes of a plugin in one environment, answer 422 `plugin-disabled`). | [18-configuration.md](18-configuration.md), [core/plugins.py](../cmapi/src/cmapi/core/plugins.py) |
| `instance.yaml` | The file with the key `instance`: name, allowed environments, token issuer and audience, Git repository, identity, CORS, problem base URL, docs and policy settings. | [18-configuration.md](18-configuration.md) |
| `tiers.yaml` | The tier catalog: the quota and limits of each tier in each environment. | [18-configuration.md](18-configuration.md) |
| `metadata-keys.yaml` | The file of the label and annotation keys: the system keys, the keys a requester sets, `operatorOnly`, `sensitiveKeys`, `liveOnlyKeys`, and `emailDomains`. | [18-configuration.md](18-configuration.md), [metadata-keys.yaml](../examples/cluster-configs/policies/metadata-keys.yaml) |
| `approval-rules.yaml` | The file that decides, from the facts of a request, how many approvals it needs and from which groups, and which auto-approval policies apply. | [18-configuration.md](18-configuration.md) |
| `authz-roles.yaml` | The file that maps each role to its permissions and, optionally, to the environments where it applies. | [core/authz.py](../cmapi/src/cmapi/core/authz.py), [18-configuration.md](18-configuration.md) |
| `clusters.yaml`, `capacity.yaml` | `clusters.yaml` lists the clusters (`environment`, `writes`, `delivery`, `clusterTokens` and more). `capacity.yaml` holds the overcommit, the warn and critical commitment targets and the KPI thresholds. | [18-configuration.md](18-configuration.md) |
| `cmapi-cluster-configs` | The Git repository that holds the desired state of each cluster's namespaces. For CRC it is `ephico2real2/cmapi-cluster-configs`. The folder of a namespace is `clusters/<clusterId>/namespaces/<namespace>/`. | [19-setup-connections-to-git.md](19-setup-connections-to-git.md), [18-configuration.md](18-configuration.md) |
| `cmapi-git-bot` | The bot account of the Git host. The worker opens pull requests and pushes branches as this account. | [19-setup-connections-to-git.md](19-setup-connections-to-git.md) |
| The portal | The web UI. The source is `cmapi-portal-ui/` (React, TypeScript, PatternFly), served from the `cmapi-portal` image. | [package.json](../cmapi-portal-ui/package.json), [CLAUDE.md](../CLAUDE.md) |
| `cmapi-portal-ui` | The directory of the portal's source and tests. Its `npm test` runs the model, contract, behaviour, parity and browser checks. | [package.json](../cmapi-portal-ui/package.json) |
| The mockup | The approved design of the portal: a Claude Design canvas (`mockups/portal/Main.dc.html` with `canvas.json`). It is the source for the portal. Read the whole file before you write from it. | [mockups/portal/README.md](../mockups/portal/README.md), [CLAUDE.md](../CLAUDE.md) |
| The front door | nginx in the `cmapi-portal` image. It serves the portal's files at `/` and sends the API's paths to the API pods. The portal and the API therefore share one origin, so CORS is off. | [01-design-and-architecture.md](01-design-and-architecture.md), [02-technical-design-v2.md](02-technical-design-v2.md) |
| `cmapi-reader` | The read-only ServiceAccount (`cmapi-system/cmapi-reader`) that cmapi uses on each managed cluster. Cluster state is read live through it, from a watch cache. | [01-design-and-architecture.md](01-design-and-architecture.md), [20-cluster-token-renewal.md](20-cluster-token-renewal.md) |
| `cmapi-imports` | The hub namespace that holds one import Secret for each cluster. The api, the worker and the capacity service read it. | [01-design-and-architecture.md](01-design-and-architecture.md) |
| `cmapi-capacity` | The third workload of an instance in the design, a capacity service. The built code has a `capacity` plugin and a simulated check; the separate service is not built. | [01-design-and-architecture.md](01-design-and-architecture.md), [08-code-status.md](08-code-status.md), [18-configuration.md](18-configuration.md) |
| `cmapi.net/…` | The prefix of the labels and annotations that cmapi writes, for example `cmapi.net/managed`, `cmapi.net/cluster-id`, `cmapi.net/request-id`, `cmapi.net/protected`, `cmapi.net/expires-at`. | [metadata-keys.yaml](../examples/cluster-configs/policies/metadata-keys.yaml) |
| Governed key | A label or annotation key that `metadata-keys.yaml` declares, with a rule for its value. Example: `cmapi.net/cost-center`. | [01-design-and-architecture.md](01-design-and-architecture.md), [18-configuration.md](18-configuration.md) |
| Operator-only key | A key that only a caller with `namespaces:protect` can set or remove (`cmapi.net/protected`, `do-not-delete`). Another caller gets 403. | [18-configuration.md](18-configuration.md), [core/authz.py](../cmapi/src/cmapi/core/authz.py) |
| Sensitive key | A key whose change adds one `approver-platform` approval (fact `sensitiveKeyChanged`). | [18-configuration.md](18-configuration.md) |
| Live-only key | A key that only the cluster or its controllers write (for example `kubernetes.io/metadata.name`, `openshift.io/*`). The comparison of Git with the cluster leaves it out. | [metadata-keys.yaml](../examples/cluster-configs/policies/metadata-keys.yaml) |
| Protected namespace | A namespace whose labels in Git match `protected.labels` of `approval-rules.yaml`. A delete of it is refused with 422 `namespace-protected`, also the delete after it expires. Only a caller with `namespaces:protect` can set the label. | [18-configuration.md](18-configuration.md), [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| Tier | A named size of a namespace: a quota and limits. The reference catalog has `small`, `medium`, `large` and `custom`. A custom tier takes values inside `custom.min`, `custom.max` and `custom.step`. | [tiers.yaml](../examples/instances/nonprod/tiers.yaml), [18-configuration.md](18-configuration.md) |
| Cost center | The governed label `cmapi.net/cost-center` of a namespace, for example `cc-4410`. | [01-design-and-architecture.md](01-design-and-architecture.md), [core/models.py](../cmapi/src/cmapi/core/models.py) |
| Reserved namespace | A name that nobody can ask for: `default`, `openshift`, `openshift-*`, `kube-*`, `cmapi-system`, `cmapi-imports`, and `instance.namespaces.reservedPatterns`. The answer is 422 `reserved-namespace`. | [18-configuration.md](18-configuration.md) |

## The API contract

| Term | Meaning | Source |
|---|---|---|
| ETag | A validator header that names one version of an answer. cmapi uses two kinds. A strong ETag of served bytes: `"` and the first 32 hex characters of the SHA-256 of the bytes, then `"` (`etag_of`). It guards `/openapi.json`, `/openapi.yaml`, `GET /api/v1/metadata-keys` and `GET /api/v1/capacity`. And the namespace ETag, below. | [core/etag.py](../cmapi/src/cmapi/core/etag.py) |
| Namespace ETag (`folder_etag`) | The version of one namespace: the first 16 hex characters of the SHA-256 of the `plan_hash` of the namespace's folder in Git, or `0` when the folder has no files. It changes when the folder changes. A client sends it back in `If-Match`. Treat it as opaque: RFC 9110 section 8.8.3 gives a client no right to read a structure from an entity tag. | [core/pipeline.py](../cmapi/src/cmapi/core/pipeline.py), [RFC 9110 section 8.8.3](https://www.rfc-editor.org/rfc/rfc9110#section-8.8.3) |
| `If-None-Match`, 304 | A read that sends the ETag it holds gets 304 with no body when that ETag is still current. The comparison is weak: `W/"x"` matches `"x"`, and `*` matches any. Used by the docs, `metadata-keys` and capacity reads. | [core/etag.py](../cmapi/src/cmapi/core/etag.py), [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| `If-Match` | The header that a change or a delete of an existing namespace must carry: the ETag from the last GET. The comparison strips the quotes. A create needs none. | [core/pipeline.py](../cmapi/src/cmapi/core/pipeline.py) |
| 428 `precondition-required` | The answer when a change has no `If-Match` (RFC 6585 section 3). It is checked after the namespace is found, so an unknown namespace answers 404 first. | [core/pipeline.py](../cmapi/src/cmapi/core/pipeline.py) |
| 412 `precondition-failed` | The answer when `If-Match` no longer equals the namespace ETag: the namespace changed in Git since the caller read it. The answer carries the current ETag in `etag`. | [core/pipeline.py](../cmapi/src/cmapi/core/pipeline.py), [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| `Idempotency-Key` | A header on writes: a new random value for each new request, at most 100 characters. The same key and caller get the first answer again for 24 hours. It is required except with `dryRun=true`. A key reused for a different request answers 409 `idempotency-replay`; a missing key answers 400 `idempotency-key-required`. | [routers/__init__.py](../cmapi/src/cmapi/routers/__init__.py), [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| `?dryRun=true` | A query parameter on a write. The answer is 200 with the plan, the capacity check and the approval that would apply. cmapi writes nothing and opens no request. | [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| Merge patch | The body form of the namespace `PATCH` for `labels` and `annotations`: JSON Merge Patch, RFC 7396. A value sets a key, and `null` removes it. | [plugins/namespaces/router.py](../cmapi/src/cmapi/plugins/namespaces/router.py), [RFC 7396](https://www.rfc-editor.org/rfc/rfc7396) |
| `metadataDiff` | The part of a plan that lists the effective label and annotation changes of a change, each with its source (#481). | [core/pipeline.py](../cmapi/src/cmapi/core/pipeline.py) |
| Problem details | The error body of every failure: `application/problem+json`, RFC 9457, with `type`, `title`, `status`, `detail` and a `code`. The base of `type` is `instance.problems.typeBase`. | [core/docs.py](../cmapi/src/cmapi/core/docs.py), [18-configuration.md](18-configuration.md) |
| Problem code | The short name of one failure, for example `change-pending` or `precondition-failed`. The registry `PROBLEMS` in `core/docs.py` maps each code to its status and a sample detail. A new error needs a registered code, with one example. | [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| `/problems`, `/problems/{code}` | The pages that a problem's `type` URI resolves to. They are public in every docs setting. | [main.py](../cmapi/src/cmapi/main.py) |
| `x-cmapi-permission` | The OpenAPI field that names the permission a route needs. The route's description ends with a "Requires" line. | [core/docs.py](../cmapi/src/cmapi/core/docs.py), [14-authorization.md](14-authorization.md) |
| `x-codeSamples` | The OpenAPI field that holds one curl sample for each operation. | [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| `x-tagGroups` | The ReDoc navigation groups: Namespaces and metadata, Access, Capacity and placement, Requests and approvals, Operations, Admin. A tag in no group is not shown by ReDoc. | [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| The contract | `cmapi/contract/openapi.json`: the OpenAPI 3.1 document that the code serves for the test instance. A test fails when it is not what the code serves. | [contract/README.md](../cmapi/contract/README.md) |
| The contract gate | `contract/gate.sh <base> <head>`, which runs `oasdiff breaking --fail-on ERR` with the list of accepted breaking changes. CI runs it against the newest released document and, on a pull request, against `openapi.json` of the base branch. | [contract/README.md](../cmapi/contract/README.md) |
| oasdiff | The tool of the gate and of the changelog, version 1.37.0. CI downloads the release archive and checks its SHA-256. | [contract/README.md](../cmapi/contract/README.md), [ci.yml](../.github/workflows/ci.yml) |
| Spectral lint | A lint of the contract with cmapi's ruleset `contract/spectral/.spectral.yaml`. It extends `spectral:oas` and adds rules with the prefix `cmapi-`. Spectral CLI is 6.17.1. | [contract/README.md](../cmapi/contract/README.md), [package.json](../cmapi/contract/spectral/package.json) |
| `accepted-breaking.txt` | The breaking changes that the gate lets through, one for each line, with the reason and the issue number above it. Use only before version 1.0 or for a new major version. | [contract/README.md](../cmapi/contract/README.md) |
| `released/<version>.json` | The document of each released version. A release adds one file. No version is released yet. | [contract/README.md](../cmapi/contract/README.md) |
| The changelog | `changelog.json`, written by `contract/changelog.py` from `released/`. `/docs/changelog` serves it. CI fails when it is not current. | [contract/README.md](../cmapi/contract/README.md) |
| The documentation standard (S1 to S10) | The ten items that every operation must have in the API document: summary and description, one tag in one group, permission, parameters with examples, request body, an Example Value, every status, one named example for each problem code, the `x-` fields visible, a curl sample. `test_api_standard.py` checks it. | [implementation_plan.md](reviews/2026-11-20-issue-479/implementation_plan.md), [test_api_standard.py](../cmapi/tests/service/test_api_standard.py) |
| `/docs` | Swagger UI of the instance. It comes from the image's own bundle, never a CDN. Without the bundle the page answers 503 `docs-assets-missing`. | [main.py](../cmapi/src/cmapi/main.py) |
| `/redoc` | ReDoc of the instance, from the image's bundle. | [main.py](../cmapi/src/cmapi/main.py) |
| `/docs/swagger.css` | The stylesheet that cmapi serves for Swagger UI. It is one of the files of the two pages, with `/docs/redoc-start.js`. | [main.py](../cmapi/src/cmapi/main.py) |
| `/openapi.json`, `/openapi.yaml` | The API document of the running instance, with a strong ETag. FastAPI's own route is off. | [main.py](../cmapi/src/cmapi/main.py) |
| `instance.docs.public`, `instance.docs.enabled` | `public: false` makes `/docs`, `/redoc`, the OpenAPI documents and `/docs/changelog` need a valid token. `enabled: false` turns the pages off. Both default to `true`. | [18-configuration.md](18-configuration.md) |
| `/healthz`, `/readyz`, `/api/v1/version` | The liveness and readiness routes, and the version route that needs no token. `/api/v1/version` answers the version, the commit and the component. | [routers/health.py](../cmapi/src/cmapi/routers/health.py), [14-authorization.md](14-authorization.md) |

## Requests and their lifecycle

| Term | Meaning | Source |
|---|---|---|
| Request, `change_requests` | One write to a namespace: its plan, approval rule, requester, pull request and state. Its ID is `req-YYYYMMDD-NNNN`. | [16-data-model.md](16-data-model.md) |
| `lifecycle.py` | The one table of (state, event) to state. The pipeline, the worker and the request routes all move a request through `transition()`. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `pending_approval` | The plan passed and approvals are required. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `approved` | The approval count is met (or the plan was auto-approved) and the capacity still fits. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `pr_open` | The worker opened the pull request. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `applied` | Apply mode only: the cluster holds the pull request's head, and `main` does not yet. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `merge_failed` | Apply mode: the apply happened and the merge did not. Lock, pull request and branch are kept until it merges. A `:retry` runs the merge again, pinned to the applied head. It is never a rollback. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `merged` | The pull request merged (cmapi merged it, or a person did and cmapi adopted it). | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `awaiting_prune` | A delete merged and Argo CD waits for the confirmation of the prune. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `synced` | Terminal. Argo CD is Synced at or after the merge, confirmed by a read. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `rejected` | Terminal. An approver rejected the request, or the plan failed (policy, capacity or validation). | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `cancelled` | Terminal. The requester or an operator cancelled it before an apply started. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `timeout` | Terminal. The approval timed out. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `failed` | The pull request failed: 5 attempts with backoff, CI failed, or the pull request was closed. No lock. A `:retry` takes the lock again and answers 409 when another request holds it. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py), [16-data-model.md](16-data-model.md) |
| `sync_failed` | Not synced within 30 minutes, or a failed sync. The pull request and branch are kept. `:retry` restarts the watch, and `:revert` hands the request over to a revert request. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `superseded` | Terminal. The namespace's files changed in Git after the plan (event `base_changed`). | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `reverted` | Terminal. A `sync_failed` request that a `:revert` request took over. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| Open request | A request in one of the eight states that hold the namespace lock: `pending_approval`, `approved`, `pr_open`, `applied`, `merge_failed`, `merged`, `awaiting_prune`, `sync_failed`. | [16-data-model.md](16-data-model.md), [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| Namespace lock | The rule that one namespace has at most one open request. The database holds it with the unique index `uq_cr_open_namespace`. A second change answers 409 `change-pending`. | [16-data-model.md](16-data-model.md), [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| Plan | What cmapi works out before it writes anything: the files to write or remove, the capacity check, the findings of the validators, the approval that applies. `dryRun=true` returns it. | [core/pipeline.py](../cmapi/src/cmapi/core/pipeline.py) |
| `plan_hash` (`planHash`) | The SHA-256 over the path and content of every file the plan writes or removes (`<deleted>` for a removed file). The pull request must match it. | [core/render/manifests.py](../cmapi/src/cmapi/core/render/manifests.py) |
| `base_sha` (`baseSha`) | The Git commit that the plan was made against. | [core/models.py](../cmapi/src/cmapi/core/models.py) |
| `request_events` | The table of one state change or note of a request, in order. `GET /api/v1/requests/{request_id}/events` reads it. Migration 0007 makes its time the insertion time. | [16-data-model.md](16-data-model.md) |
| Approval | One approval of one request by one person, in `approvals`. A person counts once (migration 0002). Requesters cannot approve their own request (409 `self-approval`). | [16-data-model.md](16-data-model.md), [core/docs.py](../cmapi/src/cmapi/core/docs.py) |
| Auto-approval | An `auto:<policy>` rule of `approval-rules.yaml` that approves a plan with no person. A Kyverno warning keeps it from applying. `approvals:pause` stops it. | [18-configuration.md](18-configuration.md), [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| `:cancel`, `:approve`, `:reject`, `:retry`, `:revert` | The verbs on `/api/v1/requests/{request_id}`, each with its permission (`requests:cancel`, `requests:approve`, `requests:reject`, `requests:retry`; `:revert` also needs `requests:retry`). | [14-authorization.md](14-authorization.md), [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py) |
| In sync, Pending, Drift, Unknown | The state of a namespace in the portal and in the API field `state`. `pending`: an open request holds the namespace, also after the merge and before the cluster has it. `drift`: no request is open and a governed, extra or operator-only key differs between Git and the cluster, or the cluster does not have the namespace. `in-sync`: they are the same. `unknown`: cmapi cannot compare. | [schema.generated.ts](../cmapi-portal-ui/src/api/schema.generated.ts), [NamespacesTab.tsx](../cmapi-portal-ui/src/portal/NamespacesTab.tsx) |
| Drift (two meanings) | 1. A namespace whose cluster state differs from Git with no open request (the row above; the alert `CmapiDriftDetected` is OutOfSync with no open request). 2. A cluster whose Kyverno bundle differs from the pinned or rendered one (`hashState` `drift`; the alert `CmapiPolicyBundleDrift`). | [01-design-and-architecture.md](01-design-and-architecture.md), [plugins/policies/router.py](../cmapi/src/cmapi/plugins/policies/router.py) |
| Delivery mode | How an approved change reaches a cluster. `argocd` (default): Argo CD on each cluster applies the folder and cmapi only reads. `apply`: the worker applies the approved folder with server-side apply, a deviation that a site must accept. Set in `integrations.yaml` (`delivery.mode`) or for one cluster in `clusters.yaml`. | [18-configuration.md](18-configuration.md) |
| Apply before merge | The `apply` mode order (#286): the worker applies the pull request's head, confirms it by a read (`applied`), then merges, so `main` records only what succeeded. | [core/lifecycle.py](../cmapi/src/cmapi/core/lifecycle.py), [01-design-and-architecture.md](01-design-and-architecture.md) |
| Git delivery, PR adapter | Git through Git itself (clone, push over HTTPS or SSH), and a thin adapter for each host's pull request API (GitHub, GitLab, Bitbucket, Gitea). The host's Contents and Checks APIs are not used. | [01-design-and-architecture.md](01-design-and-architecture.md), [core/git/](../cmapi/src/cmapi/core/git/) |
| `instance.git.hostChecks` | `true`: the worker waits for `ci/kubeconform` and `ci/kyverno` as commit statuses of the host, and posts its own. | [18-configuration.md](18-configuration.md) |
| `kubeconform` | The validator of the rendered manifests. It is baked into the api image with the Kyverno CLI. | [Containerfile](../cmapi/Containerfile), [18-configuration.md](18-configuration.md) |
| Jobs and leases | The `jobs` table holds one unit of work for the worker, with a lease. A fencing token (migration 0003) refuses the commit of a worker whose lease expired. | [16-data-model.md](16-data-model.md), [0003](../cmapi/src/cmapi/core/db/migrations/versions/0003_job_lease_generation.py) |
| `policy_rejections` | The table of cmapi's refusals before Git, and Kyverno's warnings on a plan that went on (migration 0006, #302). Pruned by the daily job `rejections_prune`. | [16-data-model.md](16-data-model.md), [18-configuration.md](18-configuration.md) |

## Policies

| Term | Meaning | Source |
|---|---|---|
| Kyverno | The policy engine. cmapi renders its policies from its own configuration. Kyverno runs in CI on the pull request, at admission on the cluster, and in the plan. cmapi's own checks refuse in every mode, and with `engine: none`. | [18-configuration.md](18-configuration.md), [13-crc-deployment.md](13-crc-deployment.md) |
| ValidatingPolicy (vpol) | The `policies.kyverno.io/v1` object kind that cmapi renders. Each carries `cmapi.net/policy-digest`. | [18-configuration.md](18-configuration.md), [13-crc-deployment.md](13-crc-deployment.md) |
| Policy mode: `audit`, `enforce`, `off` | `audit` (default): a finding is a warning, admitted and recorded; `validationActions: [Audit, Warn]`. `enforce`: a finding refuses the plan with 422 `policy-violation`; `validationActions: [Deny]`. `off`: no Kyverno run and no policy files for the environment. The owner's rule, 2026-11-17: Kyverno audits, and cmapi core refuses. | [18-configuration.md](18-configuration.md) |
| `policy.engine` | `kyverno` or `none`. | [18-configuration.md](18-configuration.md) |
| The bundle | The set of rendered policy files of an instance, in the folders `env/<env>/` of its cluster-configs repository. | [18-configuration.md](18-configuration.md) |
| Bundle hash | SHA-256 over the sorted policy names and digests of a bundle, as `{"format": 1, "policies": [...]}`. cmapi compares the hash of the render, of Git and of the cluster. | [core/policybundle.py](../cmapi/src/cmapi/core/policybundle.py) |
| `cmapi.net/policy-digest` | The annotation with the SHA-256 of one policy's canonical JSON. | [18-configuration.md](18-configuration.md) |
| `hashState` | The comparison of the bundle hashes of one cluster: `current` (live equals render), `behind` (live equals Git, which differs from the render), `drift`, `off` and `unknown`. | [plugins/policies/router.py](../cmapi/src/cmapi/plugins/policies/router.py) |
| `cmapi-tools policies render`, `policies check` | `render` writes the policy files from the configuration. `check` fails when a file in the repository differs from the render. | [18-configuration.md](18-configuration.md), [tools/policies.py](../cmapi/src/cmapi/tools/policies.py) |
| `ci/kyverno` | The commit status of the Kyverno check on a pull request of the cluster-configs repository. The api image carries the Kyverno CLI, pinned to one version. | [18-configuration.md](18-configuration.md), [Containerfile](../cmapi/Containerfile) |
| Policies tab | The portal tab and `GET /api/v1/policies/results`: the PolicyReports of each cluster, with the states `ok`, `drift`, `capped`, `engine-off`, `mode-off`. Results past `policy.reports.maxResultsPerCluster` are counted and not listed. | [18-configuration.md](18-configuration.md), [plugins/policies/router.py](../cmapi/src/cmapi/plugins/policies/router.py) |

## Identity and access

| Term | Meaning | Source |
|---|---|---|
| Keycloak | The identity provider. cmapi uses an existing Keycloak and installs none. Keycloak holds users and group membership and maps each group to a cmapi role. cmapi reads only roles and group paths from the token. | [11-existing-identity-services.md](11-existing-identity-services.md), [14-authorization.md](14-authorization.md) |
| Realm `cmapi` | The realm that cmapi adds to the shared Keycloak. The import makes it once (`KeycloakRealmImport cmapi`); a sync Job completes it. Other realms stay untouched. | [15-keycloak-integration.md](15-keycloak-integration.md), [13-crc-deployment.md](13-crc-deployment.md) |
| RHBK | The Red Hat build of Keycloak that runs on CRC. | [13-crc-deployment.md](13-crc-deployment.md) |
| `cmapi-nonprod`, `cmapi-staging`, `cmapi-prod` | The client of each instance, `cmapi-<instance>`. Its name is the token audience, and it holds the client roles. | [14-authorization.md](14-authorization.md), [15-keycloak-integration.md](15-keycloak-integration.md) |
| `cmapi-portal`, `cmapi-docs` | Public clients with Authorization Code and PKCE: the portal and Swagger UI. | [15-keycloak-integration.md](15-keycloak-integration.md) |
| `cmapi-automation`, `cmapi-directory`, `cmapi-realm-admin`, `cmapi-cli` | Clients: `cmapi-automation` (client credentials, role `cmapi-onboarding` only, for an AI agent or script); `cmapi-directory` (people search, `view-users` and `query-users`); `cmapi-realm-admin` (the sync Job); `cmapi-cli` (device flow; the CLI is not built). | [15-keycloak-integration.md](15-keycloak-integration.md) |
| Roles | The built-in client roles: `cmapi-viewer`, `cmapi-onboarding`, `cmapi-requester`, `cmapi-approver`, `cmapi-operator`, `cmapi-admin`, `cmapi-auditor`, `cmapi-approval-relay`. `authz-roles.yaml` can redefine them. | [core/authz.py](../cmapi/src/cmapi/core/authz.py) |
| Permission | A scope that a route declares and a role grants, for example `clusters:read`, `objects:read`, `capacity:read`, `requests:read`, `requests:approve`, `operations:run`. | [core/authz.py](../cmapi/src/cmapi/core/authz.py), [14-authorization.md](14-authorization.md) |
| `namespaces:create`, `namespaces:write` | `create` asks for a new namespace. `write` changes or deletes one (PATCH, DELETE, the expiration verbs). | [core/authz.py](../cmapi/src/cmapi/core/authz.py), [14-authorization.md](14-authorization.md) |
| `namespaces:protect` | The permission that makes an operator (`OPERATOR_PERMISSION`): it sets and removes operator-only keys, cancels another person's request and reads employee IDs. | [core/authz.py](../cmapi/src/cmapi/core/authz.py) |
| Groups | One LDAP group for each role, `app-cmapi-rbac-<role>`, under `/cmapi` in the token. The approving groups are `approver-platform`, `approver-prod`, `approver-qa` and `approver-uat`. `identity.groupPath` is the template, default `/cmapi/app-cmapi-rbac-{name}`. | [14-authorization.md](14-authorization.md), [core/authz.py](../cmapi/src/cmapi/core/authz.py) |
| `LEGACY_GROUP_PATH` | `/cmapi/cmapi-{name}`: the group names before the rename. A requirement stored before `identity.groupPath` existed is read under it. The ten old LDAP groups are removed in step 10 of the CRC run. | [core/authz.py](../cmapi/src/cmapi/core/authz.py), [13-crc-deployment.md](13-crc-deployment.md) |
| The group to route table | The table "Which route needs which permission", with the group to role mapping above it. | [14-authorization.md](14-authorization.md) |
| LDAP | The existing LDAP server that federates users and groups into Keycloak. cmapi adds its groups and 13 test users to it and changes nothing else. | [11-existing-identity-services.md](11-existing-identity-services.md), [14-authorization.md](14-authorization.md) |
| `employee_id` | The token claim that a person's request needs. Without it: 422 `identity-incomplete`. A role in `identity.automationRoles` needs none. | [18-configuration.md](18-configuration.md) |
| `onBehalfOf` | A service client names the person a request is for. A person calls as themselves (422 `on-behalf-of-not-allowed`); a service client with `requireOnBehalfOf` must name one (422 `on-behalf-of-required`). | [core/docs.py](../cmapi/src/cmapi/core/docs.py), [18-configuration.md](18-configuration.md) |
| `cmapi.requester` | The test user that requests namespaces on CRC. | [14-authorization.md](14-authorization.md), [HANDOVER-AND-RESUME.md](../HANDOVER-AND-RESUME.md) |

## Clusters and environments

| Term | Meaning | Source |
|---|---|---|
| CRC | OpenShift Local on the owner's Mac. It is the deployment target, and the final proof of a step runs there. | [13-crc-deployment.md](13-crc-deployment.md), [CLAUDE.md](../CLAUDE.md) |
| kind, `cmapi-test` | A local Kubernetes cluster for tests on plain Kubernetes (`KIND_EXPERIMENTAL_PROVIDER=podman`). It is not the deployment target. Say which cluster each result came from. | [CLAUDE.md](../CLAUDE.md), [13-crc-deployment.md](13-crc-deployment.md) |
| Environment | A stage that an instance serves: `rnd` and `dev` on nonprod, `qa` and `uat` on staging, `prod` on prod. A write to another environment answers 422 `environment-not-served`. Only `prod` has a meaning in code: a `prod` namespace never expires. | [18-configuration.md](18-configuration.md) |
| Cluster ID | The name of a managed cluster in `clusters.yaml`, for example `CRC`. | [18-configuration.md](18-configuration.md) |
| Cluster import | An import Secret in `cmapi-imports` that gives cmapi a cluster's address, CA and the token of `cmapi-reader`. The baseline process writes it. It supplies connection fields, not an environment. | [01-design-and-architecture.md](01-design-and-architecture.md) |
| Import token | The bearer token of `cmapi-reader` in an import Secret. Its expiry is in the annotation `cmapi.net/token-expires-at`. | [20-cluster-token-renewal.md](20-cluster-token-renewal.md) |
| TokenRequest | The Kubernetes API that issues a bounded token for a ServiceAccount. The worker's job `token_renew` uses it to renew the import token. | [20-cluster-token-renewal.md](20-cluster-token-renewal.md) |
| `clusterTokens` | The setting of the lifetime and the renewal point of import tokens: `duration` (default 7d) and `renewBefore` or `renewBeforePercentage` (default 20). A cluster's entry in `clusters.yaml` inherits the instance setting. | [18-configuration.md](18-configuration.md) |
| `:probe` | `POST /api/v1/clusters/{id}:probe`: checks again the credential that cmapi holds for a cluster and returns its diagnostics. It needs `operations:run`. | [routers/me.py](../cmapi/src/cmapi/routers/me.py) |
| Watch cache | The cache that the live reads use, filled by a watch on each cluster through `cmapi-reader`. A read is `unknown` when the watch is not fresh. | [01-design-and-architecture.md](01-design-and-architecture.md), [schema.generated.ts](../cmapi-portal-ui/src/api/schema.generated.ts) |
| `cmap-live-g-dev` | The test namespace on CRC that the proofs of the namespace stories use. Protected, cost center `cc-4410`, team `cmapi-live`. | [HANDOVER-AND-RESUME.md](../HANDOVER-AND-RESUME.md) |
| `cmapi-live-a` to `cmapi-live-f` | Earlier test namespaces on CRC. | [HANDOVER-AND-RESUME.md](../HANDOVER-AND-RESUME.md), [09-portal-ui-testing.md](09-portal-ui-testing.md) |

## Deployment

| Term | Meaning | Source |
|---|---|---|
| The CRC runbook | `docs/13`: the run of the first deployment on CRC, in 25 numbered steps. Step 5 gets the images, step 15 does the realm import, step 21 starts the workloads, step 23 runs the proofs. | [13-crc-deployment.md](13-crc-deployment.md) |
| Run 32, run 33 | A numbered CRC deployment run. In run 32 a local build restarted 58 containers in 42 namespaces, which led to CI-built images (#545). The #484 closing comment calls the run on `5c01876` run 33. | [13-crc-deployment.md](13-crc-deployment.md), [HANDOVER-AND-RESUME.md](../HANDOVER-AND-RESUME.md) |
| `crc-guard.py` | The script that guards a run: `snapshot` and `compare` of the other realms and of `keycloak-0`, `watch`, `gate`, `import-wait`. | [crc-guard.py](../deploy/crc-guard.py), [13-crc-deployment.md](13-crc-deployment.md) |
| The guard watch | `crc-guard.py watch`: polls every realm and `keycloak-0` every 5 seconds from step 12 to step 24 and writes one line to `watch.log`. | [13-crc-deployment.md](13-crc-deployment.md) |
| The stop file | The file that the watch writes on a breach (a non-200, a changed key, a changed `keycloak-0`). Every step's `gate` refuses while it exists. | [13-crc-deployment.md](13-crc-deployment.md) |
| The CI `images` job | The job of `ci.yml` that builds the `cmapi` and `cmapi-portal` images on a push to `main`, pushes each to GHCR as `sha-<commit>` (10 characters), labels it with the commit, and attests it by its digest. | [ci.yml](../.github/workflows/ci.yml), [13-crc-deployment.md](13-crc-deployment.md) |
| GHCR | GitHub Container Registry, `ghcr.io/ephico2real2/`. | [13-crc-deployment.md](13-crc-deployment.md) |
| Image digest | The `sha256:` ID of an image. CRC imports the digest, never the tag. | [13-crc-deployment.md](13-crc-deployment.md) |
| `ImageStreamImport` | The OpenShift object that `crc-image.sh` uses with `import: false` to ask GHCR for a tag's digest, through CRC's own importer. | [13-crc-deployment.md](13-crc-deployment.md) |
| Secret `cmapi-ghcr-pull` | The read-only GHCR credential in namespace `cmapi` that the image import needs. The owner makes it before step 5. | [13-crc-deployment.md](13-crc-deployment.md) |
| `crc-image.sh`, `render.sh`, `release-crc.sh` | The scripts that import an image by digest, render the manifests for an environment, and run `helm upgrade` with the environment file and the image lock. | [13-crc-deployment.md](13-crc-deployment.md), [crc.yaml](../deploy/environments/crc.yaml) |
| Plain manifests, chart | Two ways to deploy: plain YAML under `deploy/manifests/` first, and a Helm chart under `deploy/helm/cmapi` for each component later. None for Keycloak or LDAP. | [deploy/manifests/README.md](../deploy/manifests/README.md), [crc.yaml](../deploy/environments/crc.yaml) |
| CloudNativePG | The operator that runs the default database: one `Cluster` (operator 1.30.1 on CRC). A site with its own PostgreSQL provides Secret `cmapi-db-app` instead. | [12-existing-postgresql.md](12-existing-postgresql.md), [CLAUDE.md](../CLAUDE.md) |
| Migrations 0001 to 0007 | Alembic revisions. 0001 schema; 0002 one approval per person; 0003 fencing token on job leases; 0004 `counted_for` on approvals; 0005 `applied` and `merge_failed` hold the lock; 0006 `policy_rejections`; 0007 request events record the insertion time. | [versions/](../cmapi/src/cmapi/core/db/migrations/versions/) |
| Argo CD | The GitOps controller on each cluster. In `argocd` mode it applies the namespace folder. cmapi reads the Application's status to confirm `synced`. | [06-reference-architecture.md](06-reference-architecture.md), [18-configuration.md](18-configuration.md) |
| Backup (CRC) | `crc-backup.sh`: the backup that step 13 takes immediately before the import and step 25 deletes. | [13-crc-deployment.md](13-crc-deployment.md) |

## How the work is done

| Term | Meaning | Source |
|---|---|---|
| The owner | The person who decides. The standing mandate: full autonomy on cmapi; research instead of asking; file every bug and fix it in the same session. | [CLAUDE.md](../CLAUDE.md) |
| Coordinator | The main session. It writes the briefs, re-checks every verdict, arbitrates, records decisions and merges. It authors no application code (with the exceptions the owner records). | [CLAUDE.md](../CLAUDE.md) |
| Implementer | Opus 5.5 at `high`, which writes the code, tests and manifests of a step. | [CLAUDE.md](../CLAUDE.md) |
| Reviewer 1 | Codex, which designs each step independently, reviews the code and returns the full fix and test for each finding. | [CLAUDE.md](../CLAUDE.md) |
| Reviewer 2 | A separate Opus 5.5 agent at `high` that did not write the step. It checks reviewer 1's snippets and reports what reviewer 1 missed. | [CLAUDE.md](../CLAUDE.md) |
| Codex | The outside model family that reviews (and builds in houston-mayday). | [CLAUDE.md](../CLAUDE.md) |
| Opus | Opus 5.5 at `high`: writes code and arbitrates. | [CLAUDE.md](../CLAUDE.md) |
| Sonnet | Sonnet 5.5: reads as-built code and drafts documentation and agile issue updates. The coordinator verifies and posts. This page is one such draft. | [HANDOVER-AND-RESUME.md](../HANDOVER-AND-RESUME.md) |
| Fable | A model family. Paused by the owner on 2026-11-05. In houston-mayday, Fable reviews later (label `review:fable`). | [CLAUDE.md](../CLAUDE.md), [implementation_plan.md](reviews/2026-11-20-issue-479/implementation_plan.md) |
| OB1 | The long build-everything run, first pinned to Fable 5.2 for one run by the owner (2026-11-13). Its prompt is `OB1-PROMPT.md`. A run has a number (for example "OB1 run 23"). | [OB1-PROMPT.md](../OB1-PROMPT.md), [11-existing-identity-services.md](11-existing-identity-services.md) |
| houston-mayday | The mode in which Codex builds and reviews and Opus rules. Its pull requests carry the label `review:fable`. | [CLAUDE.md](../CLAUDE.md), `gh label list` |
| `/fix-defect` | The skill for every defect: issue with a research mandate, link to the parent, background agent fix, review, then validation and test by the coordinator. | [.claude/skills/fix-defect/SKILL.md](../.claude/skills/fix-defect/SKILL.md) |
| `/adversarial-review` | The skill for the review of a change by reviewers from other model families, never the author, each finding with its full fix and a failing test. | [CLAUDE.md](../CLAUDE.md) |
| `/decide` | The diagram-kit skill for an owner decision. The stories #483 to #485 were approved through it. | [CLAUDE.md](../CLAUDE.md), [HANDOVER-AND-RESUME.md](../HANDOVER-AND-RESUME.md) |
| diagram-kit | The owner's repository of skills (`app-architect`, `test-ui`, `adversarial-review`, `decide`, `mockup-to-page-react`) and the diagram renderer. | [CLAUDE.md](../CLAUDE.md) |
| The delivery loop | The seven steps of every change: one issue, one branch, one pull request; two designs arbitrated; implementation; functional test; adversarial review; docs updated from measured numbers; merge when CI is green and the review passed. | [CLAUDE.md](../CLAUDE.md) |
| Story, epic, spike, task, feature | Issue types by label: `epic` (a body of work tracked by child issues), `feature` (a capability a user sees), `story` (one slice of a feature for one role), `spike` (a time-boxed question with a measured answer), `task` (a unit of work with no user story). | `gh label list` |
| Stories #13 to #29 | The stories that a pull request delivers a part of. A story closes only after the owner approves, with a comment that cites the proof of each acceptance criterion. | [CLAUDE.md](../CLAUDE.md) |
| `Part of #N`, `Closes #N` | `Closes #N` starts the body of the pull request that fixes the issue. `Part of #N` marks a pull request that delivers part of a story or links a defect to its parent. | [CLAUDE.md](../CLAUDE.md), [fix-defect SKILL.md](../.claude/skills/fix-defect/SKILL.md) |
| `status:open`, `status:partly-fixed`, `status:fixed-on-review-branch`, `status:owner-action` | No fix yet; part fixed and the rest is a story or an owner action; fix and test merged on a branch that is not the default; waits for the owner. | `gh label list` |
| `sev:critical`, `sev:high`, `sev:medium`, `sev:low` | Severity. critical: a person with no special access can get money, data or control of a server now. high: if a condition occurs, a person can get money, data or access. medium: incorrect data, a weak control or a slow service, with no direct loss. low: a small defect, a defect no code path reaches yet, or a cleanup. | `gh label list` |
| Backlog, In-Progress, In-QA, Done | Board labels. Backlog: not started. In-Progress: started, not complete. In-QA: pull request open, in review and CI. Done: merged into the integration branch, with the proof in the comment. | `gh label list` |
| Local-Deploy, Sbx-Deploy, Go-Live | Done and walked on the local deploy with screenshots; running on the sandbox; running in production from the default branch, and the issue closes. | `gh label list` |
| Blocked | Work cannot continue. The comment names the blocker. | `gh label list` |
| `review:fable` | Done in houston-mayday, and waits for a Fable review. | `gh label list` |
| `class:INV`, `class:TDT` | INV: innovation (a new feature, design, idea or method). TDT: tech debt (works today, but costs more to change, operate or upgrade). | `gh label list` |
| `/agile` | The skill whose labels the issue register follows. | [issue-register.md](../issue-register.md) |
| Review record | A folder `docs/reviews/<date>-<subject>/` with the brief, the findings and the decision of one review. | [reviews/](reviews/) |

## Document and issue IDs

| Term | Meaning | Source |
|---|---|---|
| `docs/01` | Design and architecture. An export of a live Claude Doc: edit the live doc first when the tools are available. | [01-design-and-architecture.md](01-design-and-architecture.md), [CLAUDE.md](../CLAUDE.md) |
| `docs/02` | Technical design v2 (FastAPI). An export of a live Claude Doc, like `docs/01`. | [02-technical-design-v2.md](02-technical-design-v2.md), [CLAUDE.md](../CLAUDE.md) |
| `docs/03` | Usage analysis from Thanos: verdicts and rightsizing. | [03-usage-analysis.md](03-usage-analysis.md) |
| `docs/04` | API examples, generated from the recorded samples by `scripts/api-examples-doc.py`. | [04-api-examples.md](04-api-examples.md), [contract/README.md](../cmapi/contract/README.md) |
| `docs/05` | Consolidated requirements baseline of the OpenShift cluster management API. | [05-requirements-baseline.md](05-requirements-baseline.md) |
| `docs/06` | Reference architecture: hub and spoke. | [06-reference-architecture.md](06-reference-architecture.md) |
| `docs/07` | Review of Argo Events and Argo Workflows. | [07-argo-events-workflows-review.md](07-argo-events-workflows-review.md) |
| `docs/08` | Code status: what is built and what is not. Dated 2026-11-05. | [08-code-status.md](08-code-status.md) |
| `docs/09` | How the portal UI was tested. | [09-portal-ui-testing.md](09-portal-ui-testing.md) |
| `docs/10` | Architecture review to the `/app-architect` standard. | [10-architecture-review.md](10-architecture-review.md) |
| `docs/11` | The existing Keycloak and LDAP on CRC, and what cmapi adds. | [11-existing-identity-services.md](11-existing-identity-services.md) |
| `docs/12` | Use of an existing PostgreSQL server. | [12-existing-postgresql.md](12-existing-postgresql.md) |
| `docs/13` | The CRC deployment runbook. | [13-crc-deployment.md](13-crc-deployment.md) |
| `docs/14` | Authorization: the contract between cmapi and Keycloak. | [14-authorization.md](14-authorization.md) |
| `docs/15` | The Keycloak integration. | [15-keycloak-integration.md](15-keycloak-integration.md) |
| `docs/16` | The data model of the service. | [16-data-model.md](16-data-model.md) |
| `docs/17` | The KPIs of cmapi. | [17-kpis.md](17-kpis.md) |
| `docs/18` | The configuration of cmapi, file by file. | [18-configuration.md](18-configuration.md) |
| `docs/19` | Set up cmapi's connection to Git. | [19-setup-connections-to-git.md](19-setup-connections-to-git.md) |
| `docs/20` | Cluster import-token renewal design. | [20-cluster-token-renewal.md](20-cluster-token-renewal.md) |
| `build-tracker.md` | What is done, in progress and left, and which cluster proved each thing. | [build-tracker.md](../build-tracker.md) |
| `HANDOVER-AND-RESUME.md` | The current state and the next steps. Its top section supersedes the sections below it. | [HANDOVER-AND-RESUME.md](../HANDOVER-AND-RESUME.md) |
| `issue-register.md` | Every issue and milestone, generated from GitHub by `scripts/issue-register.sh`. Do not edit it by hand. | [issue-register.md](../issue-register.md) |
| `CRC-BUILD-STATUS.md` | The measured log of the CRC build. | [CRC-BUILD-STATUS.md](../CRC-BUILD-STATUS.md) |
| `docs/reviews/` | The records of reviews, one folder for each. | [reviews/](reviews/) |
| `docs/citations.lock.json` | For each `file:line` citation of docs 14, 15 and 16, the text of the cited lines. `scripts/doc-citations.py --check` compares it with the code. | [doc-citations.py](../scripts/doc-citations.py) |
| `#N` | An issue or pull request of `ephico2real2/cmapi`. | [issue-register.md](../issue-register.md) |
| S1 to S10 | The documentation standard of every API operation (see "The API contract"). In code comments, "S7" and "S8" cite it. | [implementation_plan.md](reviews/2026-11-20-issue-479/implementation_plan.md) |
| A1 to A11, P1 to P12 | The design points of epic #479: A for the API contract of the namespace, P for the portal's New namespace form. | [implementation_plan.md](reviews/2026-11-20-issue-479/implementation_plan.md) |
| C1 to C8 | The code rules of the plan of #479: one function one step, rules in data, no metaprogramming, and the rest. | [implementation_plan.md](reviews/2026-11-20-issue-479/implementation_plan.md) |
| Phase 1 to Phase 5 (#479) | The five phases, each one pull request: the API contract; the contract lint and the standard; Swagger UI and ReDoc settings; the portal's form; CRC configuration, the Kyverno bundle and the deploy. | [implementation_plan.md](reviews/2026-11-20-issue-479/implementation_plan.md) |
| 484-T1 to 484-T9 (T1 to T9) | The nine tests of story #484, the Namespaces tab, checked at 390, 820 and 1440 px in each theme. | [09-portal-ui-testing.md](09-portal-ui-testing.md) |
| 390, 820, 1440 px | The three widths of every portal check. | [09-portal-ui-testing.md](09-portal-ui-testing.md) |

## Technologies and libraries

| Term | Meaning | Source |
|---|---|---|
| FastAPI | The web framework of the api (0.115.6). | [pyproject.toml](../cmapi/pyproject.toml) |
| Pydantic | The models and settings (`pydantic`, `pydantic-settings`). | [pyproject.toml](../cmapi/pyproject.toml) |
| SQLAlchemy, Alembic, psycopg | The database layer, the migrations and the driver. | [pyproject.toml](../cmapi/pyproject.toml) |
| PostgreSQL 16 | The database. The service tests run against one on `127.0.0.1:55432`. | [CLAUDE.md](../CLAUDE.md), [12-existing-postgresql.md](12-existing-postgresql.md) |
| PyJWT | Verifies the token signatures. | [pyproject.toml](../cmapi/pyproject.toml) |
| structlog, prometheus-client | The structured logs and the `/metrics` figures. | [pyproject.toml](../cmapi/pyproject.toml) |
| React, PatternFly | The portal's UI library (React 19) and component set (PatternFly 6). | [package.json](../cmapi-portal-ui/package.json) |
| Vite, TypeScript | The portal's build tool and language. | [package.json](../cmapi-portal-ui/package.json) |
| TanStack Query | The portal's data fetching and cache (`@tanstack/react-query`). | [package.json](../cmapi-portal-ui/package.json) |
| `openapi-fetch`, `api:types` | The typed client of the API and the script that generates `schema.generated.ts` from the contract. | [package.json](../cmapi-portal-ui/package.json) |
| `oidc-client-ts` | The portal's sign-in library (Authorization Code with PKCE). | [package.json](../cmapi-portal-ui/package.json) |
| Playwright, axe-core | The browser tests of the portal and the accessibility scan. `PW_CHANNEL=chrome` runs them in the installed Chrome. | [package.json](../cmapi-portal-ui/package.json), [CLAUDE.md](../CLAUDE.md) |
| nginx | The front door, `nginx-unprivileged` in the `cmapi-portal` image. | [Containerfile](../cmapi-portal-ui/Containerfile) |
| Swagger UI, ReDoc | The two renderers of the API document, served from the image. | [main.py](../cmapi/src/cmapi/main.py) |
| Helm | The chart of each component under `deploy/helm/`. | [crc.yaml](../deploy/environments/crc.yaml) |
| Podman | The container engine that kind runs on here. | [CLAUDE.md](../CLAUDE.md) |
| GitHub Actions | The CI. `ci.yml` has the jobs `reference-code`, `service`, `portal-mockup`, `portal-ui`, `front-door`, `images`, `images-pr`, `api-contract` and `manifests`. | [ci.yml](../.github/workflows/ci.yml) |
