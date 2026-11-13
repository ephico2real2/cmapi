# cmapi — Design and Architecture

Nov 3, 2026 · @Ola

## Summary

cmapi is one API for asking for, changing and inspecting namespaces across every OpenShift cluster, through one instance per network zone: nonprod (rnd, dev), staging (qa, uat) and prod. Every write is approved in cmapi and then becomes a bot pull request to the cluster-configs repository, and each cluster's Argo CD applies it. cmapi never writes to a cluster directly.

This document is the entry point and the current source of truth. The [v2 design](02-technical-design-v2.md) keeps the field-level detail. Where the two disagree, this document wins.

**Who uses it.**

- Application teams request namespaces, quotas, service accounts and metadata through the portal, the CLI or their pipelines.
- Platform engineers approve, operate and report.
- Automation (svc-\* clients) calls the same API with the same rules.

**Design principles.**

1. **Git is the write path.** API request → plan → approval → PR to cluster-configs → Argo CD on each cluster. Every change has a diff, an approver of record and a revert.
2. **Reads are live.** Cluster state is read through a read-only cmapi-reader ServiceAccount on each cluster, from a watch cache, never from a copy in the database.
3. **PostgreSQL holds history, not state.** It stores change requests, approvals, audit, capacity snapshots and usage verdicts. It is never replayed to rebuild a cluster.
4. **Cluster credentials are read-only.** A cluster is imported by a separate baseline process. The imported token reads; its one write is issuing ServiceAccount tokens in namespaces cmapi manages.
5. **Policy is checked once, in three places.** The same Kyverno bundle runs at plan time in cmapi, in CI on the PR, and at admission on the cluster.
6. **Optional parts stay optional.** Argo Workflows, Argo Events, Tekton, Argo CD Notifications and Kafka each improve cmapi when present. cmapi works without any of them.
7. **Capacity is measured ahead of time.** Placement reads cluster capacity snapshots stored every capacity.snapshotInterval (30 minutes by default). Namespace usage is read live from Thanos only for a quota change on an existing namespace, a scoped usage read, and the daily off-peak sweep.

## Requirements and constraints

These decisions are settled. Every section below honours them.

| Area | Decision |
| --- | --- |
| Environments | rnd, dev, qa, uat and prod, each with several clusters, served by three instances: nonprod (rnd, dev), staging (qa, uat) and prod. Which instance serves which environments is configuration (allowedEnvironments). Environment comes from clusters.yaml, never from the cluster name, and a namespace's environment must match its cluster's. |
| Domain and labels | ephico2real.com for hosts and the Keycloak realm. Every cmapi label and annotation uses the cmapi.net/ prefix. |
| User and group access | Granted by a separate process. cmapi reads Users, Groups, Identities and GroupSyncs; it never creates them or binds people. |
| ServiceAccount access | The only access cmapi grants: ServiceAccounts, their RoleBindings and SCC grants. |
| SA token guardrails | Deferred. Requirement 11 is out of scope for now. |
| Authentication | Keycloak OIDC with read-only LDAP federation. One realm, ephico2real. |
| Cluster credentials | Created on every cluster by a separate baseline process and imported automatically. Read-only, except issuing ServiceAccount tokens in managed namespaces. |
| Writes | Only through Git. The one direct call is ServiceAccount token issuance (sa-tokens). |
| Argo Workflows and Events | Optional. cmapi works with or without them, and with or without Tekton, Kafka and Argo CD Notifications. |
| Thanos on onboarding | Never queried while creating a namespace or setting its first quota. Placement uses stored snapshots. |
| Thanos on quota change | Queried live for that namespace's last 14 days when an existing namespace's quota changes, and once a day per cluster by the off-peak sweep. |
| Snapshot interval | capacity.snapshotInterval: 30 minutes by default, any value from 15 to 60 (for example 60). |
| Capacity service | cmapi-capacity is an internal microservice. It is reached only through cmapi's scoped endpoints and needs no separate user auth. |

## System architecture

Each cmapi instance runs on its zone's hub cluster as three workloads: the API, the worker and cmapi-capacity. The API calls Keycloak only for signing keys and changes cluster state only through Git. The managed clusters never hear from cmapi except as reads through each cluster's cmapi-reader ServiceAccount.

![cmapi system architecture · hub, Git, managed clusters](diagrams/architecture.png)

The only path from cmapi to a cluster's desired state is a merged PR that the cluster's own Argo CD pulls. Every arrow into a managed cluster is a read.

| Component | Where | Role | Talks to |
| --- | --- | --- | --- |
| cmapi-api | Hub, namespace cmapi | Gateway for every caller. Verifies the token, authorizes, plans, applies approval rules, records approvals, places namespaces, serves reads | Keycloak (JWKS, and the read-only admin API for directory lookups), Git host, PostgreSQL (cmapi schema), cmapi-capacity, each cluster's API (read) |
| cmapi-worker | Hub, namespace cmapi | Jobs from the jobs table: open\_pr, sync\_pr\_state, watch\_sync, notify, expire\_check, built-in operation steps | Git host, Argo CD Applications on each cluster (read), PostgreSQL |
| cmapi-capacity | Hub, namespace cmapi, ClusterIP only | All Thanos work: snapshots, live namespace usage, daily sweep, retention | Each cluster's Thanos Querier and API (read), PostgreSQL (capacity schema) |
| PostgreSQL | Hub | Two schemas: cmapi (requests, approvals, reservations, jobs, audit) and capacity (snapshots, verdicts, recommendations) | — |
| Keycloak | Hub, namespace cmapi-sso | Realm ephico2real; LDAP federation, read-only | LDAP or AD |
| cmapi-imports | Hub namespace | One import Secret per cluster, written by the baseline process | Read by cmapi-api, cmapi-worker and cmapi-capacity |
| cluster-configs | Git host | Desired state: one folder per cluster plus the Kyverno policy bundle | Argo CD on each cluster |
| Argo CD | Each managed cluster | Applies that cluster's folder; Kyverno enforces the same bundle at admission | Git host |
| cmapi-reader | Each managed cluster | Read-only ServiceAccount and ClusterRole from the baseline; cluster-monitoring-view for Thanos | — |
| Optional | Hub or external | Argo Workflows or Tekton (operations), Argo CD Notifications (sync signal), webhook or Kafka (events) | cmapi-api and worker, never in the request path |

## Deployment instances

cmapi runs as several independent instances, one per network zone, because each zone can reach only its own clusters. Every instance is the full stack (portal, API, worker, cmapi-capacity and database) from the same image and Helm chart. Which environments it serves is configuration, so a new tier needs no code.

| Instance | Serves environments | API | Portal |
| --- | --- | --- | --- |
| nonprod | rnd, dev | cmapi-nonprod.ephico2real.com | portal-nonprod.ephico2real.com |
| staging | qa, uat | cmapi-staging.ephico2real.com | portal-staging.ephico2real.com |
| prod | prod | cmapi.ephico2real.com | portal.ephico2real.com |

![deployment instances · three zones, nothing shared at runtime but Keycloak](diagrams/deployment-instances.png)

To create something in rnd or dev, a team calls the nonprod API or portal; for qa or uat, staging; for prod, prod. Calling the wrong one returns 422 environment-not-served with the URL of the instance that serves that environment.

```yaml
# config/instance.yaml: set per deployment through Helm values
instance:
  name: nonprod
  displayName: Non-production
  allowedEnvironments: [rnd, dev]
  publicUrl: https://cmapi-nonprod.ephico2real.com
  portalUrl: https://portal-nonprod.ephico2real.com
  auth:
    issuer: https://sso.ephico2real.com/realms/ephico2real
    audience: cmapi-nonprod          # a token minted for another instance is refused
  git:
    repository: caas/cluster-configs-nonprod
  directory:                         # where to send callers for other environments
    staging: {url: https://cmapi-staging.ephico2real.com, environments: [qa, uat]}
    prod:    {url: https://cmapi.ephico2real.com, environments: [prod]}
```

**What allowedEnvironments controls.**

- **Clusters.** Every clusters.yaml entry must name an environment in the list. Startup, /admin/reload and CI on the config repository refuse a file that breaks this, and the previous configuration stays in force.
- **Imports.** The baseline process writes a cluster's import Secret to the hub of the instance that serves its environment. A Secret whose registered environment is not served is refused with the finding environment-not-served.
- **Requests.** A namespace's environment must be served, and must match its cluster's. Placement only ranks this instance's clusters.
- **Policy files.** approval-rules.yaml, authz-roles.yaml, placement.yaml, capacity.yaml (overcommit and targets) and the usage thresholds are per instance. A key for an environment the instance does not serve fails validation, so prod's files hold only prod rules.
- **Portal.** The environment picker lists only served environments, and links to the other instances for the rest.

**What each instance owns.** Its own namespace, PostgreSQL (cmapi and capacity schemas), cmapi-capacity, worker, Routes, cmapi-imports namespace and Git credential. Instances share nothing at runtime and never call each other. Capacity views, usage analysis and reports cover only the instance's own clusters.

**Shared across instances.** The image, the Helm chart, the Kyverno policy bundle (pinned per instance by tag), and the Keycloak realm with one resource client per instance (cmapi-nonprod, cmapi-staging, cmapi-prod), each with its own audience and portal client. LDAP groups map to roles per client, so someone can request in nonprod without any role in prod.

**Git.** One cluster-configs repository per instance (cluster-configs-nonprod, -staging, -prod), so a nonprod credential cannot open a PR against a prod cluster's folder, and branch protection is set per tier. Each cluster's Argo CD watches its own instance's repository.

**Provenance.** Every object cmapi renders carries the annotation cmapi.net/instance with the instance name, and every request ID and event records it.

**dev.** dev is a new environment value. Until its own settings are agreed it takes rnd's: no approval for changes, 1 for creates (waived by baseline-rnd-namespace, extended to dev), CPU overcommit 2.0, memory 1.25, and rnd's usage thresholds.

## Modularity and reuse

cmapi is modular at four levels, and every level is chosen by configuration, not code: an offering is a plugin, an integration is an adapter behind a core interface, a heavy concern is a separately deployable service, and a network zone is an instance. Everything else is one shared core that every plugin, service, engine and instance reuses. A review of the whole design against this found seven gaps; they are closed below.

![modular layers · clients, plugins, shared core, adapters, per-instance config](diagrams/modular-layers.png)

Each layer only calls the one below it through a published interface: clients through the API, plugins through core, core through an extension point.

| Level | Unit | How it plugs in | Examples |
| --- | --- | --- | --- |
| Offering | A Python package with an entry point in cmapi.plugins | DocumentedRouter routes, a Planner, declared read RBAC, approval facts, typed plan sections | namespaces, quotas, sa-grants, capacity, adoption |
| Integration | An adapter behind a core interface, picked in config | integrations.yaml, instance.yaml, capacity.yaml | GitHub or GitLab; builtin, Argo Workflows or Tekton |
| Service | A component deployed on its own behind an interface | A backend with remote and embedded modes | cmapi-capacity |
| Instance | The same image and chart with different configuration | instance.yaml and the per-instance policy files | nonprod, staging, prod |

**Extension points.** Each is a Python Protocol in core with a default adapter; an alternative is a package that registers under cmapi.adapters.\<point>.

| Interface | Default | Alternatives | Chosen in |
| --- | --- | --- | --- |
| Authenticator | OIDC against the Keycloak realm | Any OIDC issuer | instance.yaml auth |
| DirectoryProvider | Keycloak admin API (users, read-only) | Direct LDAP read, Microsoft Graph | instance.yaml identity |
| Renderer | Raw Kubernetes manifests, one folder per namespace | project-meta.yml, Kustomize overlay | plugins.yaml, per plugin |
| GitProvider | GitHub REST | GitLab REST, GitPython clone over HTTPS or SSH | instance.yaml git |
| Validator | Kyverno CLI + kubeconform | conftest (OPA) | policy-bundle.yaml |
| CapacityBackend | remote (cmapi-capacity) | embedded | capacity.yaml mode |
| MetricsSource | Each cluster's Thanos Querier | ACM Observability hub | capacity.yaml |
| SyncSignal | poll | Argo CD Notifications | integrations.yaml, per cluster |
| OperationsEngine | builtin | Argo Workflows, Tekton | integrations.yaml |
| EventPublisher | none | Signed webhook, Kafka | integrations.yaml |
| Notifier | email | Slack, Teams | integrations.yaml |
| Import source (outside cmapi) | The import Secret contract | RHACM ManagedServiceAccount, per-cluster Job, ExternalSecret | The baseline process |
| Dashboards | Perses (OpenShift console) | Grafana, or both | Chart value dashboards.provider; plugins add panels from their own package |

**Shared, reusable components.**

| Component | Package | Reused by |
| --- | --- | --- |
| Write pipeline: authorize → idempotency → lock → plan → approve → commit | cmapi-core | Every write plugin; plugins only plan |
| DocumentedRouter and the problem registry | cmapi-core | Every route; Swagger, ReDoc, SDK and CLI |
| ClusterScoped models, ClusterId, the instance-limited Environment type | cmapi-core | Every model in every plugin |
| Cluster registry, clusterSelector and read-only per-cluster clients | cmapi-core | Plugins, placement, approval rules, operations, cmapi-capacity |
| Metadata key classes and merge patch | cmapi-core | Namespaces, ServiceAccounts, any labelled object |
| Approval engine and auto-approval guards | cmapi-core | Every write plugin, through the facts its planner returns |
| Jobs queue, advisory locks, outbox | cmapi-core | Worker, cmapi-capacity, builtin operations engine, events |
| Plugin test kit: fake cluster, local Git server, contract tests | cmapi-core\[testing\] | Every plugin's CI |
| Operation step library | cmapi-ops | builtin engine, Argo Workflows, Tekton |
| Generated SDK and CLI | cmapi-sdk | Portal, CLI, pipelines, operation steps |
| Portal UI kit (React, TypeScript, Vite, PatternFly): WorkflowViewer, PlanView, SchemaForm, RequestTable, PlacementView, PagedTable (search, filters, sort, letter jump, paging, export) | cmapi-portal-ui | Every portal screen and every plugin |
| Kyverno policy bundle | cluster-configs policies, tagged | API plan, CI, admission, every instance |
| Helm chart | helm/cmapi | Every instance |

**The workflow is generic.** The request lifecycle belongs to core, so every plugin's requests go through the same stages and write the same request\_events. The portal's WorkflowViewer draws any request from GET /api/v1/requests/{id}/events, and an operation from its operation\_steps. Plugins add content only through typed plan sections (checks, diff, table, usage, placement), which PlanView renders by kind. A new plugin's requests therefore appear in Workflow, Requests and Approvals with no portal change.

**The portal is schema-driven.** Forms come from the OpenAPI request schemas, with x-cmapi-form hints for field order and widgets (a tier picker, an environment picker limited to the instance). A plugin ships a portal extension module only when a generated form cannot express the task.

**Lists page, search and export the same way.** An instance holds hundreds of namespaces and thousands of requests, so no list endpoint returns everything. cmapi-core provides one contract and cmapi-portal-ui one PagedTable, used by Quotas, Requests and Approvals and by any plugin's list:

- **Paging:** the envelope {items, page: {limit, total, from, to, nextCursor, prevCursor}, letters}. The cursor is keyset on (sort value, name, clusterId), so with the default name order, namespaces created or deleted between pages never cause a skip or a repeat. Sorting by % used or severity is best-effort across pages, because those values change while someone pages. It carries a hash of the filters and sort; reusing it after either changes returns 400 invalid-cursor. limit is 25, 50 (default) or 100, at most 200.
- **Letter jump:** with sort=name, startsWith=p starts the page at the first name from that letter. The response's letter counts disable letters with no rows.
- **Search:** :suggest returns up to 10 matches from 2 characters: names that start with the text, then names that contain it, then namespaces whose cmapi.net/team or cmapi.net/app label matches, each saying why it matched. Choosing one opens that row with its page; q= on the list applies the same match to every page. The portal debounces 250 ms and cancels the previous call on each keystroke.
- **Filters and sort:** env, clusterId, team, tier, verdict and state combine with q; sort is name (default), used (highest percentage of quota first) or severity.
- **Attention:** facets.attention counts quota-tight, near limit (80% or more of any hard limit), open recommendation, oversized, idle and open request over the current filters; each count is a one-click filter. Severity for sorting: quota-tight or 95% used 3, 80% used 2, a recommendation, oversized or idle 1, ties by name.
- **Export:** :export?format=csv streams every row matching the same filters in the same order, capped at 10,000 rows and written to the audit log.
- **Scope and source:** every row, count, letter, suggestion and export covers only the environments where the caller's roles grant objects:read (requests:read for the request list); there is no team or namespace-name scope. Rows come from the watch cache joined in memory with the latest verdicts and recommendations; nothing calls Thanos and nothing queries the database per row. A cluster that cannot be reached keeps its rows, marked stale with the time of the last good read.
- **Budgets:** a page answers in under 300 ms p95 and a suggestion in under 150 ms p95 at 5,000 namespaces per instance.

**Adding an offering**, for example a NetworkPolicy baseline:

1. cmapi plugin new netpol scaffolds the package from the template: router, models, planner, renderer fragment, tests.
2. Implement the models (described fields and examples), the planner (validate, render, diff, return facts and plan sections) and the read RBAC it needs.
3. Run the shared test kit: the contract test, the plugin's own tests against the fake cluster and local Git server.
4. Add netpol to plugins.yaml for the instances and environments that should offer it.

With no core or portal change, it then has routes in the spec, Swagger and ReDoc pages, the SDK and CLI commands, a generated portal form, workflow and request views, approval rules and auto-approval matching on its facts, metrics labelled by plugin, and its read grants in the next exported ClusterRole.

**Gaps closed by this review.**

| Gap | Was | Now |
| --- | --- | --- |
| Plugins could reach Thanos | ClusterContext handed every plugin a ThanosClient | ClusterContext carries a read-only capacity facade over CapacityBackend; only cmapi-capacity talks to Thanos |
| Portal built per offering | Each screen hand-made | SchemaForm from OpenAPI, and the generic WorkflowViewer and PlanView |
| Plugin RBAC had no consumer | required\_rbac merged into a ClusterRole cmapi no longer applies | cmapi rbac export publishes the merged cmapi-reader ClusterRole with each release, and the baseline applies it |
| Plugin enablement by environment only | plugins.yaml overrides keyed by environment | Keyed by instance, then environment, and validated against allowedEnvironments |
| Notifier named two ways | Slack in one place, Teams in another | One Notifier interface: email by default, chat adapters optional |
| No shared test harness | Each plugin built its own | cmapi-core\[testing\], required by the plugin contract |
| Validation tied to one engine | Kyverno CLI called directly | Validator interface, Kyverno CLI by default |

## Request lifecycle

Every write runs the same pipeline, whatever the plugin. **Approval happens in cmapi, before anything reaches Git.** The API answers 202 with a ChangeRequest in pending\_approval, or already approved when an auto-approval policy matches. Only an approved request is rendered into a pull request, which the cmapi bot merges once CI passes. The caller follows the request, not the PR.

![request lifecycle · 9 steps, one approval branch](diagrams/request-lifecycle.png)

1. **Authenticate.** Verify the Keycloak JWT offline against the cached JWKS: issuer, audience cmapi-\<instance>, expiry.
2. **Authorize.** The route's permission must come from a Keycloak role in the token (config/authz-roles.yaml maps roles to permissions), and a role limited to some environments must cover the request's environment. Names are checked, not owned: anyone holding namespaces:create may ask for any valid name that is not reserved and not an unmanaged namespace on the cluster.
3. **Idempotency.** The same Idempotency-Key from the same caller returns the first response.
4. **Lock.** At most one open request per namespace, covering every file in its folder (a partial unique index on cluster and namespace), so two requests can never edit the same files.
5. **Plan.** The plugin validates, renders the YAML and diffs it against the live object. The Kyverno bundle and kubeconform run on the rendered files, and the plan stores a hash of them. For a new namespace, the request carries the placementId from POST /api/v1/capacity:place and that reservation becomes the request's own. For a quota increase, the delta is reserved the same way and cmapi-capacity reads the namespace's last 14 days from Thanos.
6. **Decide.** The rules engine turns the plan's facts into an ApprovalRequirement. A matching auto-approval policy approves at once (approver auto:\<policy>); otherwise the request waits in pending\_approval and the approval channels tell the eligible approvers.
7. **Approve.** An eligible approver calls POST /api/v1/requests/{id}:approve, or :reject with a comment, with their own token: from the portal, the CLI, or a channel such as an email link or ServiceNow. When the count is met, capacity is checked again and the request becomes approved.
8. **Commit.** The worker renders the approved plan, confirms the hash still matches, and opens a bot PR. CI runs the Kyverno bundle, kubeconform and the cmapi check (request ID approved, PR head equal to the approved hash). When CI passes, the bot merges. Nobody reviews in Git.
9. **Sync.** Argo CD on the target cluster applies the folder. The worker learns the result by polling or from Argo CD Notifications and confirms it with a direct read; then the request is synced and its reservation ends. A delete stops in awaiting\_prune until an operator confirms the prune in Argo CD.

| State | Entered when | Moves to | Lock | Reservation |
| --- | --- | --- | --- | --- |
| pending\_approval | The plan passed and approvals are required | approved, rejected, cancelled, timeout | Held | Held |
| approved | The count is met (auto or :approve) and capacity still fits | pr\_open, cancelled, failed, superseded | Held | Held |
| pr\_open | The bot PR is open | merged, failed, superseded | Held | Held |
| merged | CI passed and the bot merged | synced, awaiting\_prune, sync\_failed | Held | Held |
| awaiting\_prune | A delete merged; Argo CD shows the namespace waiting for prune confirmation | synced | Held | None |
| synced | Argo CD Synced at or after the merge commit, confirmed by a read | End | Released | Released |
| rejected | The plan failed, or an approver rejected | End | Released | Released |
| cancelled | The requester, or an operator, cancelled before pr\_open | End | Released | Released |
| timeout | The approval window passed | End | Released | Released |
| failed | The PR could not be opened after 5 attempts with backoff, CI failed, or someone closed the PR | approved (:retry re-acquires the lock; 409 if another request holds it) | Released | Released |
| sync\_failed | Merged but not synced within 30 minutes, or Argo CD reports a failed sync | synced (:retry re-watches the sync), or reverted (:revert) | Held until resolved | Released |
| superseded | The namespace's files changed in Git after the plan | End; the caller re-plans | Released | Released |
| reverted | :revert on a sync\_failed request; the revert is a new request through the same approval rules | End | Released, so the revert request can take it | Released |

Reads skip steps 3 to 9. A dry run (?dryRun=true) returns 200 with the plan, the capacity check and the approval that would apply; it skips the idempotency and lock steps, reserves nothing, writes no row and opens no PR. POST /api/v1/requests/{id}:cancel lets the requester or an operator withdraw before pr\_open; :retry and :revert need requests:retry; a revert is a new request through the same approval rules.

**Git cannot bypass cmapi.** The bot is the only account that can merge under clusters/. Branch protection requires the cmapi check, which fails closed on a PR with no approved request ID or with a head that differs from the approved hash, and dismisses stale results on every push. policies/ and argocd/ are owned by approver-platform and need two of them.

**What cmapi writes to Git.** Plain Kubernetes manifests, one folder per namespace inside the cluster's folder. No project-meta file, CRD or operator turns them into objects: what a reviewer sees in the PR diff is exactly what Argo CD applies, and Kyverno, kubeconform and the plan hash all run on those same files. The raw manifest renderer is the default; project-meta and Kustomize stay available behind the Renderer extension point.

```
cluster-configs-nonprod/
└── clusters/
    └── OCP_GF15/                          # gitopsPath from the cluster registry
        ├── argocd/root-application.yaml   # bootstrap; not written by cmapi
        └── namespaces/
            └── payments-dev/
                ├── namespace.yaml
                ├── resourcequota.yaml
                ├── limitrange.yaml
                ├── serviceaccounts.yaml            # when the namespace has SAs
                ├── rolebindings.yaml               # SA grants and SCC grants
                └── token-issuer-rolebinding.yaml   # lets cmapi issue SA tokens here
```

- **One file per kind.** Keys are sorted with system labels first, so a quota change is a small diff to one file. An SCC grant is a RoleBinding to the ClusterRole system:openshift:scc:\<name>; cmapi never creates an SCC.
- **Tiers live in cmapi.** config/tiers.yaml holds the ResourceQuota and LimitRange values per tier and environment, and the renderer writes them out, so the diff shows real numbers; a custom tier writes the approved values. Changing a tier definition changes no namespace by itself: namespaces rendered from an older definition show as tier-outdated (their cmapi.net/tier-hash differs), and the tiers-rerender operation opens one request per affected namespace, in batches, through the normal approval rules. One module, core/tiers.py, is the only reader of the catalog; its schema, validation, API (GET /api/v1/tiers) and the module itself are in the v2 design, Tiers.
- **Metadata on every object.** Labels cmapi.net/cluster-id and cmapi.net/managed; annotations cmapi.net/request-id and cmapi.net/instance. The Namespace also carries cmapi.net/env, cmapi.net/tier, cmapi.net/team, cmapi.net/requested-by-user, cmapi.net/team-dl, cmapi.net/requested-by, the optional expiry keys (never in prod) and argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true.
- **Argo CD.** Each cluster's root Application syncs clusters/\<clusterId>/namespaces with directory recurse. Removing a folder makes Argo CD prune its objects, and Prune=confirm holds the Namespace until an operator confirms. One Application per namespace from an ApplicationSet was considered and not used: when a folder disappears, the ApplicationSet deletes that Application and by default its resources with it, which bypasses Prune=confirm.
- **namespace-configuration-operator.** Its quota and LimitRange NamespaceConfigs are retired, and cmapi owns ResourceQuota and LimitRange for every namespace. Order: adopt existing namespaces first (adoption writes their live quota and LimitRange into their folders), then remove those NamespaceConfigs, after confirming whether the operator deletes the objects it stamped when a NamespaceConfig is removed.

```yaml
# clusters/OCP_GF15/namespaces/payments-dev/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: payments-dev
  labels:
    cmapi.net/cluster-id: OCP_GF15
    cmapi.net/env: dev
    cmapi.net/expiry: managed            # non-prod only, when an expiry was asked for
    cmapi.net/managed: "true"
    cmapi.net/requested-by-user: ola     # preferred_username from the token
    cmapi.net/tier: medium
    cmapi.net/cost-center: cc-4410       # governed
    cmapi.net/team: payments
    app.ephico2real.com/component: api   # team
  annotations:
    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true
    cmapi.net/expires-at: "2026-12-15"
    cmapi.net/instance: nonprod
    cmapi.net/request-id: req-20261104-2b17
    cmapi.net/requested-by: ola@ephico2real.com   # email from the token
    cmapi.net/team-dl: payments-team@ephico2real.com
```

## Identity and access

Keycloak is the only identity provider cmapi trusts. Roles in the token decide what a caller may do and, for a role limited to some environments, where; there are no team or namespace-name scopes. cmapi stores no passwords, mints no tokens and never asks a cluster about a person.

**Keycloak.** Red Hat build of Keycloak on the hub, namespace cmapi-sso, realm ephico2real, issuer https://sso.ephico2real.com/realms/ephico2real. One read-only LDAP provider. Only groups named app-cmapi-rbac-\* are imported, under /cmapi, and each carries its client-role mapping. Adding a person to an LDAP group is the whole onboarding step.

**Requester identity.** Who asked is read from the validated token, never from the request body. preferred\_username becomes the label cmapi.net/requested-by-user and email the annotation cmapi.net/requested-by; given\_name, middle\_name, family\_name and the employee\_id claim are stored with the request in the database. These are system keys: a request that sets them is refused (422 reserved\_key). Employee ID and names never reach Git or the cluster, because the repository and namespace metadata are readable by many people; the username already identifies the person, and the directory maps a username to an employee ID when a report needs one. A person's token without employee\_id is refused with 422 identity-incomplete; an automation account (a role in identity.automationRoles) needs none and is recorded as automated.

**Claims in Keycloak.** Three settings put the extra claims in the token: LDAP user-attribute mappers (read-only) for employeeNumber (employeeID in Active Directory) and the middle-name attribute; the same attributes declared under Realm settings, User Profile, since Keycloak 24 and later ignores attributes the profile does not declare; and a client scope cmapi-identity whose user-attribute mappers add employee\_id and middle\_name to the access token, assigned to every instance's client.

**Directory.** All Keycloak access is one module in cmapi-core, not a separate service: core/auth.py verifies tokens offline, and core/identity/ holds the claims mapping, the DirectoryProvider and the only admin API client. The DirectoryProvider extension point looks people up. Its first implementation, keycloak, calls the admin API with a read-only client (realm-management roles view-users and query-users), caches results for 15 minutes and keeps serving the cached copy when Keycloak is unreachable. It serves three things. Service clients and automation accounts (the ServiceNow relay, CI, bot-user) may send onBehalfOf with a username or employee ID; cmapi resolves it to an enabled person and records both the caller and the person, or answers 422 unknown-user. Without onBehalfOf the client or account is itself the requester; identity.requireOnBehalfOf: true makes onBehalfOf mandatory for them again. The portal's people picker uses GET /api/v1/directory/users?q=, which returns name, username and email, and employee ID only to cmapi-operator and above. GET /api/v1/me returns the caller's own identity.

**Team DL.** Every namespace names its team's distribution list in the required annotation cmapi.net/team-dl (an email address, so it cannot be a label). It replaces the individual owner email; cmapi.net/owner is retired. cmapi checks the format only: an address in one of the organisation's email domains (422 invalid-team-dl otherwise). The domains are configuration, one list, emailDomains in cluster-configs/policies/metadata-keys.yaml, which cmapi and the Kyverno bundle both read; ephico2real.com throughout these documents is a placeholder. It does not look the DL up or check membership: DLs are not reliably present in Keycloak, and a person can belong to many. Expiry notices, approval requests and rightsizing recommendations go to the DL.

| Client | Flow | Used by |
| --- | --- | --- |
| cmapi | None (resource server, audience); one per instance: cmapi-nonprod, cmapi-staging, cmapi-prod | Owns the six client roles |
| cmapi-portal | Authorization Code + PKCE | Namespace portal |
| cmapi-docs | Authorization Code + PKCE | Swagger UI |
| cmapi-cli | Device Authorization Grant + offline\_access | cmapi login |
| svc-{team}-{purpose} | Client Credentials | One per pipeline or automation |

**Roles.** cmapi-viewer, cmapi-onboarding, cmapi-requester, cmapi-approver, cmapi-operator, cmapi-admin and cmapi-auditor, plus cmapi-approval-relay for channel integrations such as ServiceNow (approvals:relay only; the named person must be eligible). core/authz.py maps each to permissions such as namespaces:create (ask for a new namespace), namespaces:write (change or delete one), capacity:read or operations:run (operator and admin). Approver does not include requester, and self-approval is excluded by the caller's sub unless the environment allows it (rnd, dev).

**Onboarding and automation accounts.** cmapi-onboarding is viewer plus namespaces:create and requests:cancel: it creates namespaces and follows their requests, and cannot change or delete one. cmapi-requester is onboarding plus namespaces:write, quotas:write, serviceaccounts:write and grants:write. Onboarding is assigned to people, directly or through the group /cmapi/app-cmapi-rbac-onboarding, or to a local Keycloak account such as bot-user that an AI agent or a script signs in as. Accounts holding a role in identity.automationRoles (default \[cmapi-onboarding\]) need no employee ID and may send onBehalfOf. Every request records whether it was automated, and approval rules get the facts automated and requesterClient, so agent requests can be routed differently; otherwise they follow the same rules, auto-approval included. Anyone holding namespaces:write may change or delete any managed namespace: approval rules still apply, and a delete still needs its approvals and an operator's prune confirmation.

**Namespace names.** Any caller with namespaces:create picks the name, so the name itself is checked (core/naming.py): a DNS-1123 label of 2 to 63 characters (422 invalid-namespace-name); not reserved, either built in (default, openshift, openshift-\*, kube-\*, cmapi-system, cmapi-imports) or in the instance's namespaces.reservedPatterns in instance.yaml, such as ocp-\* and kubernetes-\* (422 reserved-namespace); and at create, not a namespace that already exists on the cluster without cmapi.net/managed (409 namespace-exists-unmanaged; adoption is the way in). cmapi.net/team stays required as ownership and cost metadata; any valid value is accepted and it is not checked against the caller.

**Role policy.** config/authz-roles.yaml maps each Keycloak client role on the instance's client (cmapi-nonprod, cmapi-staging, cmapi-prod) to permissions. Keycloak decides who holds a role: a person directly or through a group the role is assigned to, a service-account client, or a local account such as bot-user. An entry may replace a role's permissions (permissions), add another role's (inherits) or limit the role to some of the instance's environments (environments), for example cmapi-bot-rnd: inherits cmapi-requester, environments \[rnd\]. Built-in roles not listed keep their built-in permissions in every environment the instance serves. A missing permission is 403 forbidden; a role limited to other environments is 403 environment-forbidden. Retired: scope bindings and config/authz-scopes.yaml (cluster, namespace-pattern and team per caller), cluster-scope-forbidden, team\_not\_bound and mustMatchBinding.

**Sessions.** cmapi keeps no session; every call stands on its own 5-minute access token. Keycloak 26 persists sessions in its database, so restarts sign nobody out.

| Caller | Signs in again after |
| --- | --- |
| Portal | 8 hours idle or 12 hours total |
| Portal with Remember me | 7 days idle or 30 days total |
| CLI | 30 days idle or 90 days total (offline token in the OS keychain) |
| Swagger UI | 1 hour idle or 8 hours total |
| Pipelines | No session; a new token per job |

Refresh tokens rotate with zero reuse. A removed LDAP membership reaches tokens within the 15-minute LDAP cache plus one refresh.

**Users and groups on clusters.** Granted by a separate process. cmapi reads Users, Identities and Groups through cmapi-reader from a watch cache with a 30-minute relist, and GroupSyncs and the OAuth CR on demand. A 403 or a missing CRD is reported as unavailable, never as an empty list. cmapi writes only ServiceAccounts, their RoleBindings and SCC grants, through Git.

## Cluster connections and metadata

cmapi never logs in to a cluster. The cluster-baseline process creates the cmapi-reader ServiceAccount and its read-only ClusterRole on every cluster, and hands the connection to the hub as one labelled Secret. cmapi finds the Secret, checks it and starts reading.

**Import contract.** One Secret per cluster in the hub namespace cmapi-imports, labelled cmapi.net/secret-type=cluster and cmapi.net/cluster-id, annotated cmapi.net/managed-by: cluster-baseline. It holds apiUrl, token, caData and insecure, nothing else. It can arrive through RHACM's ManagedServiceAccount add-on, a per-cluster Job, or an ExternalSecret from Vault.

**Why a separate namespace.** The baseline writer needs create and update on Secrets there. In cmapi's own namespace that grant would expose cmapi's Git and database credentials. cmapi itself has only get, list and watch on cmapi-imports.

**Read-only by design.** The imported token can read namespaces, nodes, quotas, RBAC, SCCs, users, groups, GroupSyncs, Argo CD Applications and Thanos. It changes nothing on the cluster, with one exception below. Writes reach a cluster only through a merged PR and that cluster's Argo CD, and validation runs offline with the Kyverno CLI and kubeconform. The exception is create on serviceaccounts/token for the sa-tokens plugin, granted by a cmapi-token-issuer RoleBinding that Git renders only into namespaces cmapi manages.

**Tokens.** TokenRequest tokens live 7 days and are rewritten at 80% of their life by the one writer. cmapi re-reads the token on every client build and alerts at 90% without a replacement.

**Six checks before a cluster is read.**

1. Discover: watch cmapi-imports plus a 5-minute relist. A failed list keeps the previous set.
2. Parse the Secret. Refused for a missing field, a duplicate cluster ID, insecure with caData, invalid caData, or userinfo in apiUrl.
3. Choose the TLS mode: caData, trusted bundle, or insecure where the environment allows it (rnd only by default).
4. Connect with GET /version. Fails as unreachable or cert-verify-failed, naming the trust store and the fix.
5. Check identity with GET users/\~. It must be cmapi-system:cmapi-reader, or the result is auth\_failed or wrong-identity.
6. Check capability: list namespaces and applications, reach Thanos. A 403 names the missing grant and never triggers a token change.

Each refusal is a finding on that cluster only. A connected cluster with no clusters.yaml entry is read-only; writes return 422 cluster-not-writable until the cluster-onboard operation merges its entry.

**Connection from the import, policy from Git.** clusters.yaml holds only policy and classification, so neither source can override the other.

```yaml
# config/clusters.yaml
- clusterId: OCP_GF1
  environment: prod                 # rnd | dev | qa | uat | prod
  gitopsPath: clusters/OCP_GF1
  writes: true
  syncSignal: notify                # poll | notify
  thanosUrl: null                   # optional; default is the thanos-querier Route
  metadata:
    region: us-central
    zones: [us-central-1a, us-central-1b, us-central-1c]
    datacenter: dfw-dc2
    provider: vsphere
    labels: {business-unit: commercial, gpu: "false"}
  placement:
    enabled: true
    maxNamespaces: 400
    overcommit: {cpu: 1.0, memory: 1.0}
    weight: 1.0
```

The metadata becomes a label set per cluster: region, zone, environment, provider, datacenter, clusterId and every key in labels. A clusterSelector over that set is how approval rules, auto-approval, placement, integrations, operations, reports and capacity rollups pick clusters. Declared zones are checked against node topology labels on every import check; a mismatch raises zone-mismatch and the declared value stays in force.

## Capacity, placement and usage

Cluster capacity is measured ahead of time and stored; namespace usage is read live and only when it changes a decision. Creating a namespace never waits on Thanos.

![capacity data flow · three reads of Thanos, one per question](diagrams/capacity-data-flow.png)

Placement also reads committed quota from the API watch cache and active reservations from the cmapi schema, both current to the second. The 30-minute label is the default interval; 60 minutes is the other common setting.

| Question | Data | Read when | Stored? |
| --- | --- | --- | --- |
| Which cluster should a new namespace land on? | Latest complete capacity snapshot, committed quota from the API watch cache, active reservations | Every create and every quota or tier increase | Snapshots, every capacity.snapshotInterval |
| Is this quota change on an existing namespace justified? | That namespace's usage now, 7-day average, 14-day p95 and peak, from Thanos | Once per quota-change plan, cached 10 minutes | No |
| How full is a cluster, a zone, a region or an environment? | capacity\_snapshots aggregated by clusters.yaml metadata | On read | Snapshots, 13 months |
| Which namespaces waste quota, or are at risk? | Daily fleet sweep over each cluster's last 14 days | Once a day per cluster, off-peak | Verdicts and recommendations only |

**Cluster snapshots.** cmapi-capacity queries each cluster's Thanos Querier every capacity.snapshotInterval (30 minutes by default, 15 to 60 allowed). One set of per-node queries gives a row for the whole cluster, one per zone and one per node role (worker, infra, master). Each row holds CPU and memory capacity, allocatable, requests, limits, workload average and peak, whole-node usage and committed quota, plus pods, storage and node conditions. Committed quota comes from the API, not Thanos, because ResourceQuota status is exact. A failed or warned query, or a gap over 5% between Thanos allocatable and the API node sum, marks the row incomplete; it is never written as zero.

**Cluster and fleet capacity.** GET /api/v1/clusters/{clusterId}/capacity returns one ClusterCapacity view: whole cluster, each zone, each role, and zone-failure headroom. GET /api/v1/capacity?groupBy=region,environment aggregates clusters by any metadata field.

- Counts and quantities are summed.
- Ratios (utilisation, commitment) are recomputed from summed numerators and denominators, never averaged.
- Headroom is floored at zero per cluster before summing, because capacity cannot move between clusters.
- largestPlacement is the biggest single cluster's headroom: the answer to "can one namespace of this size land here?".
- Peaks are summed as an upper bound and labelled coincidentPeakUpper.
- Stale or incomplete clusters are left out and listed with the reason; coverage shows how many were included.

**Headroom and overcommit.** Quota headroom = allocatable × overcommit − committed − reserved. Memory has tighter limits because it cannot be throttled. CPU and memory are tracked, committed and checked separately everywhere: every capacity view reports both, placement filters on both, a quota change is checked on both, and a cluster's status is the worse of the two, with boundBy naming the resource that limits it. A namespace that needs only memory is never refused for CPU, and the reverse.

| Environment | CPU overcommit | Memory overcommit | Warn when memory limits exceed |
| --- | --- | --- | --- |
| rnd | 2.0 | 1.25 | 1.5 × allocatable |
| qa | 1.5 | 1.1 | 1.5 × allocatable |
| uat | 1.25 | 1.0 | 1.5 × allocatable |
| prod | 1.0 | 1.0 | 1.2 × allocatable |

A cluster's placement block can override its environment's overcommit.

**Placement.** POST /api/v1/capacity:place ranks clusters and holds a 15-minute reservation on the winner.

- **Hard filters** exclude a cluster with a named reason: wrong environment, not connected or not writable, placement disabled, outside the requested region, zones or clusterSelector or the team's binding, stale or partial data, maxNamespaces reached, no quota headroom after reservations, and in prod no zone-failure headroom.
- **Score** (0 to 100, weights in config/placement.yaml): quota headroom after placement 40, usage headroom from the 14-day p95 25, balance 15, team affinity 10, zone spread 10. It is multiplied by the cluster's weight and capped at 100; ties go to the lower clusterId.
- **Reservations** are taken in the same transaction as the check, under a per-cluster advisory lock. A reservation ends when the request is synced and a direct read shows the namespace's quota, or when it is rejected, cancelled, timed out, failed or sync\_failed.
- A quota increase that no longer fits returns 422 capacity-exceeded with the clusters where it would fit, as advice. Moving a namespace is a migration and never automatic.

**Quota changes on existing namespaces.** The quotas planner asks cmapi-capacity for that namespace's last 14 days. The figures feed the approval facts (quotaIncreasePct, requestToPeakRatio, the namespace's current verdicts). If Thanos cannot answer within 10 seconds, the plan carries usage: unavailable and the change needs a platform approval instead of failing. An increase reserves its delta like a placement and is checked again when approved. A decrease below what pods already request is refused unless approver-platform approve, because new pods would be rejected at admission.

**Quota view.** GET /api/v1/quotas?q=&env=&clusterId=&team=&tier=&verdict=&state=&sort=&limit=&cursor=&startsWith= pages through every namespace in the caller's scope on this instance with its tier and its ResourceQuota hard and used for requests.cpu, requests.memory and pods, read from the watch cache, plus its latest verdict and any open recommendation. Used is the sum of pod requests, not what pods consume. GET /api/v1/clusters/{clusterId}/namespaces/{ns}/quota returns one namespace with the ETag a change needs. Neither read touches Thanos. The portal's Quotas tab is built on these two reads; it opens A to Z, 50 per page, with the attention counts above the list and type-ahead search, as described in Lists page, search and export the same way. Planning a change from it adds the live 14-day usage, the CPU and memory check against the cluster (and zone-failure headroom in prod), and the approval that will apply. A change is a tier (PATCH on the namespace) or custom requests.cpu and requests.memory (PATCH on its quota), and one open request per namespace still holds, so a second change waits with 409.

**Usage analysis.** A daily sweep reads each cluster's namespaces over 14 days and stores per-namespace verdicts (for example quota-oversized, requests-oversized, quota-tight, cpu-throttled, memory-limit-risk, idle) and rightsizing recommendations. Thresholds are per environment. Recommendations are applied only through a normal cmapi request. Detail: the [Usage analysis tab](02-technical-design-v2.md).

**Retention limit.** Platform Prometheus keeps 15 days, so every namespace window is 14 days. Anything longer comes from stored snapshots, or later from raised retention or ACM Observability.

## cmapi-capacity service

All Thanos work runs in cmapi-capacity, a long-lived internal microservice with its own pods and its own database schema. The API and worker never call Thanos, so a slow query, a heavy sweep or a capacity bug cannot slow a request.

| Work | When | Writes |
| --- | --- | --- |
| Cluster snapshots | Every capacity.snapshotInterval, per cluster | capacity.capacity\_snapshots |
| Daily fleet sweep | Once a day per cluster, off-peak | capacity.analysis\_sweeps, namespace\_verdicts, recommendations |
| Live namespace usage | On request from the API, cached 10 minutes | Nothing |
| Retention | Daily | Drops expired monthly partitions |

**Reached only through cmapi.** No Route, no public hostname, no user authentication of its own. Callers use cmapi's cluster-first paths; the API verifies the Keycloak token, checks the role and its environments, then forwards. Fleet calls go out with the caller's environments already resolved, so the service makes no authorization decisions.

| Public path on cmapi | Forwarded to cmapi-capacity |
| --- | --- |
| GET /api/v1/clusters/{clusterId}/capacity and /capacity/history | Latest or historical snapshot rows |
| GET /api/v1/clusters/{clusterId}/namespaces/{ns}/usage?window=14d | Live Thanos read, cached 10 minutes |
| GET /api/v1/clusters/{clusterId}/namespaces/{ns}/analysis | Latest verdicts and recommendation |
| GET /api/v1/clusters/{clusterId}/analysis/namespaces | Namespaces by verdict, within the caller's patterns |
| POST /api/v1/clusters/{clusterId}/capacity/snapshots:run and /analysis/sweeps:run | Run now (operations:run) |
| GET /api/v1/capacity and /api/v1/analysis/summary | Fleet aggregates over the caller's clusters |

Placement, the capacity check inside every plan, and applying or dismissing recommendations stay in the API, because they write requests or reservations.

**Trust with nothing to manage.**

- ClusterIP Service only; a NetworkPolicy admits the API and worker pods and the monitoring namespace.
- TLS from the OpenShift service CA, issued and rotated by annotation.
- The API presents a projected ServiceAccount token (audience cmapi-capacity, 10-minute lifetime). The service accepts only that ServiceAccount, checked by a cached TokenReview.
- X-Request-Id and the caller's username travel for logs and audit, never for authorization.

**Deployment.** Two replicas, a PodDisruptionBudget and a ServiceMonitor, from the same image as cmapi with the cmapi-capacity entrypoint. A PostgreSQL advisory lock per job keeps scheduled work from running twice. It reads the same cmapi-imports Secrets and clusters.yaml, and uses each cluster's cmapi-reader token.

**One interface, two modes.** The API calls a CapacityBackend. capacity.mode: remote is the production layout above, with timeouts (10 seconds for live usage, 3 for stored reads), one retry on GET and a circuit breaker. capacity.mode: embedded runs the same package, cmapi.capacity, inside the worker for development and small installs.

**When it is down.** The API returns 503 capacity-service-unavailable for forwarded reads. Placement keeps working from stored snapshots until a cluster's newest one is two intervals old, then excludes it as stale-data. Quota-change plans get usage: unavailable and need a platform approval. A missed sweep leaves the previous verdicts in place, dated. CmapiCapacityServiceDown and CmapiCapacitySnapshotStale alert.

## Approvals and auto-approval

Approval rules live in config/approval-rules.yaml and are evaluated at plan time; the strictest match wins, and cmapi enforces it before anything is written to Git.

| Environment | Instance | Create | Change | Delete | Approving group | Timeout |
| --- | --- | --- | --- | --- | --- | --- |
| rnd | nonprod | 1 (0 through baseline-rnd-namespace) | 0 | 1 | approver-platform (self-approval allowed) | 8 h |
| dev | nonprod | 1 (0 through baseline-rnd-namespace) | 0 | 1 | approver-platform (self-approval allowed) | 8 h |
| qa | staging | 1 | 1 | 1 | approver-qa | 24 h |
| uat | staging | 1 | 1 | 1 | approver-uat | 24 h |
| prod | prod | 1 | 1 | 2 | approver-prod | 48 h |

rnd and dev creates need 1 approval, so the baseline-rnd-namespace policy has something to waive: small and medium rnd and dev namespaces on fresh capacity data go straight to Git, and anything larger or flagged waits for a person.

Namespace patterns raise or waive (critical-\* needs 2 from approver-platform; temp-\* waives create and change). Thresholds add approvers from the plan's facts: quota increase over 100%, request-to-peak ratio over 3, capacity warn, a decrease below what pods request, a sensitive key change, an expiry beyond limits, and deletes of old or large namespaces. The engine, the auto-approval guards and the approval ledger are reference code; see the v2 design, Module catalog.

**Approval of record.** cmapi records every approval; Git reviews carry no authority, so no mapping from Git usernames to Keycloak users is needed. POST /api/v1/requests/{id}:approve and :reject (a comment is required) take the approver's own token. cmapi checks the approver role, the approving group from the token, that one of the approver's roles grants requests:approve in the request's environment, and that the approver is not the requester, not the person who started the operation, and not an owner of the svc client that asked (self-approval only where the environment allows it). GET /api/v1/requests?status=pending\_approval&approver=me lists what a person can approve. Each decision is an approvals row and an audit event.

**Approval channels.** How approvers hear about a request, and how they reach :approve, is an extension point (ApprovalChannel); a channel notifies or relays, and the decision is always the same :approve call, so a gate added later changes no plugin.

| Channel | How it works |
| --- | --- |
| portal (default) | The Approvals tab lists pending requests with the plan, the reasons and Approve / Reject |
| email | A message with a signed, single-use link that opens the request in the portal; the email itself never approves |
| argo-events / notifications | cmapi publishes request.pending\_approval; a Sensor or Argo CD Notifications fans it out to chat, paging or a workflow |
| servicenow | Opens a change task; when it is approved there, the integration calls :approve as a svc client with approvals:relay, naming the person, who must be eligible; both identities are recorded |
| slack / teams | An interactive message whose button opens the portal page, like email |

**Auto-approval.** Baseline requests the platform team decides need no human approval. It is off unless switched on, at three levels.

| Switch | Where | Effect |
| --- | --- | --- |
| Master | autoApproval.enabled | false: every request follows the normal rules |
| Per policy | policies\[\].enabled | Turns one baseline off, leaves the rest |
| Kill switch | POST /api/v1/admin/auto-approval:pause and :resume (cmapi-admin) | Immediate, no PR; recorded with who and why; overrides Git until resumed |

Example policies: baseline-rnd-namespace (create, rnd and dev, small or medium tier, optional clusterSelector), team-metadata (team-class label keys in any environment), expired-namespace (the delete that follows an expiry grace period, see Namespace expiration), baseline-sa-grants (written, not yet on). A team gets at most maxPerTeamPerDay auto-approvals (20 by default).

**Guards no policy can switch off.** A matching request still goes to humans when it is a delete (other than expired-namespace, which has its own guards), when a pattern or threshold added approvers, when placement or the capacity check is anything but fits on fresh data, when the plan has warnings, or when the team's daily allowance is used. CI must pass either way.

An auto-approved request is approved at plan time by approver auto:\<policy>, skips pending\_approval and goes straight to the bot PR; CI must still pass. Widening a policy that reaches prod needs two approver-platform.

## Namespace expiration

Expiration is optional, and prod never has it. A namespace in rnd, dev, qa or uat may be created with an expiry date or without one; a prod namespace can never carry expiration metadata.

- **Where it lives.** The renderer writes the annotation cmapi.net/expires-at (a date) and the label cmapi.net/expiry=managed onto the Namespace manifest (namespace.yaml); both are system keys nobody sets by hand. cleanup.kyverno.io/ttl is not used: a Kyverno delete would leave the folder in Git, and Argo CD would recreate the namespace.
- **Never in prod.** A prod request with any expiry field gets 422 expiration-not-allowed, the renderer never writes the keys for prod, and the Kyverno ValidatingPolicy deny-expiry-in-prod refuses them in CI and at admission, so a hand edit cannot add them either.
- **Limits.** Set per environment in config/expiration.yaml. An extension within the limits follows the environment's change rule; going past them, or making a namespace permanent, adds approver-platform.

| Setting | rnd, dev | qa, uat | prod |
| --- | --- | --- | --- |
| Expiry at create | Optional | Optional | Not allowed |
| Each extension | Up to 30 days | Up to 30 days | — |
| Total lifetime | 180 days from creation; longer needs approver-platform | Same | — |
| Approvals for an extension within limits | 0 | 1 (approver-qa, approver-uat) | — |
| Notices before expiry | 14, 7 and 1 days | Same | — |
| Grace after the date | 7 days | 7 days | — |

- **API.** GET /api/v1/clusters/{clusterId}/namespaces/{ns}/expiration; POST …/expiration:extend {days or until, justification}; POST …/expiration:set (give a permanent non-prod namespace a date); POST …/expiration:makePermanent; GET /api/v1/expirations?state=expiring|grace|pending\_delete|active|permanent&within=14d&env=&team= (paged and searched like quotas). Every write is a normal request: plan, approval, bot PR. The portal's Expiration tab is built on these calls.
- **The daily expire\_check.** The worker notifies the team DL (cmapi.net/team-dl) through the Notifier at 14, 7 and 1 days. On the date the namespace enters grace: it keeps running, can still be extended, and is flagged on the Expiration tab. After grace, cmapi opens a delete request approved by the expired-namespace policy, whose guards are no open request on the namespace, not protected, no extension in the last 24 hours, and at least two notices sent. The delete thresholds (age, pods, PVCs) and namespace patterns do not apply to an expiry delete: these guards and the operator's prune confirmation stand in for them. The bot PR removes the folder and Argo CD waits for an operator to confirm the prune (awaiting\_prune), so data and PVCs are never removed by a timer alone.
- **Deletes in general.** Namespaces are rendered with the Argo CD sync option Prune=confirm, so every namespace delete, by request or by expiry, waits for an operator. CI refuses a PR that removes more than one namespace folder, or any folder without a matching approved delete request.

## Policy reports (Kyverno)

The same Kyverno bundle runs at plan time, in CI and at admission. What it decided on each cluster is read back from the policy reports and shown on the portal's Policies tab, per instance.

- **Reports, not policy internals.** cmapi reads wgpolicyk8s.io PolicyReports and ClusterPolicyReports live through cmapi-reader (the baseline grants get, list and watch on them and on the policy kinds), as the group-sync dashboard's Kyverno module already does. The CEL policy kinds (ValidatingPolicy, MutatingPolicy, GeneratingPolicy, DeletingPolicy, ImageValidatingPolicy) are first-class; results from the deprecated ClusterPolicy family are counted separately. Kyverno not installed, and results dropped by the report size breaker, show as states, never as zero.
- **What the tab shows.** Per cluster, the bundle tag running against the tag pinned for the instance, and each policy's readiness. Per policy, pass, fail, warn and error counts and the failing resources by namespace, scoped to the caller. cmapi's own refusals at plan time and in CI sit beside the admission results, so a team sees a rule once whatever stopped them.
- **API.** GET /api/v1/policies?clusterId= (bundle and readiness), GET /api/v1/policies/results?clusterId=&policy=&namespace=&result=fail|warn|error (paged, scoped), GET /api/v1/policies/rejections?since=7d (cmapi's plan-time and CI refusals).
- **Metrics.** cmapi\_policy\_results{cluster\_id, policy, result} and cmapi\_policy\_bundle\_info{cluster\_id, tag, pinned="true"|"false"}, with no namespace or resource label. CmapiPolicyBundleDrift fires when a cluster runs a tag other than the pinned one for 30 minutes.

## Optional integrations

cmapi runs fully with none of these. Each sits behind an extension point with a built-in default in config/integrations.yaml; turning one on adds capability, and losing it never touches the request path.

| Capability | Built-in default | With the integration | If the integration fails |
| --- | --- | --- | --- |
| Sync signal | Worker polls each cluster's root Application every 30 s while it has merged requests | Argo CD Notifications push results; a 10-minute reconcile pass remains. Per cluster: syncSignal: notify | The reconcile pass catches up |
| Operations (cluster-onboard, rebuild-verify, adoption-sweep, bulk-migrate, promote) | Built-in engine runs steps in the worker, state in PostgreSQL | Argo Workflows or Tekton run the same steps as cmapi-ops pods, with UI and archive | cmapi stays ready; POST /api/v1/operations returns 503 operations-engine-unavailable |
| Outbound events | Off | Signed webhook or Kafka topic, from a transactional outbox; Argo Events can consume either | The outbox holds events until the bus recovers |
| Notifications to people | notify job (chat and email) | Unchanged | — |

**Rules for operations on any engine.** Steps change managed objects only by calling cmapi. Runs start only through cmapi and carry cmapi.net/operation-id. There are no pause nodes; a step that needs approval opens a cmapi request. Steps call cmapi as svc-cmapi-workflows and record the person who started the run.

GET /api/v1/admin/integrations reports each integration's mode and health, per cluster for the sync signal.

## Observability, KPIs and dashboards

Every instance measures itself the same way: each component exposes /metrics, ServiceMonitors hand them to the hub's user workload monitoring, a PrometheusRule raises the alerts, and one set of dashboards shows them in the OpenShift console through Perses, with Grafana as an option. The KPIs below are read from those metrics and the database, per instance.

![observability flow · per instance](diagrams/observability-flow.png)

**Metrics.** Prefix cmapi\_. Labels stay low-cardinality: cluster\_id, environment, plugin, kind, action, status, reason. Never namespace, user or request ID; per-namespace figures are served by the API. cmapi\_build\_info{instance, version} on every component says which instance and release a series came from.

| Component | Key metrics |
| --- | --- |
| cmapi-api | cmapi\_http\_requests\_total, cmapi\_http\_request\_duration\_seconds, cmapi\_change\_requests\_total, cmapi\_validation\_failures\_total, cmapi\_environment\_not\_served\_total{environment} |
| Identity | cmapi\_auth\_failures\_total{reason}, cmapi\_authz\_denied\_total{permission}, cmapi\_jwks\_refresh\_total{result}, cmapi\_idp\_unavailable\_total |
| Approvals | cmapi\_approval\_wait\_seconds{rule}, cmapi\_auto\_approvals\_total{policy, environment}, cmapi\_auto\_approval\_fallbacks\_total{guard}, cmapi\_auto\_approval\_paused |
| Placement | cmapi\_placement\_requests\_total{result}, cmapi\_placement\_excluded\_total{reason}, cmapi\_reservations\_active{cluster\_id}, cmapi\_placement\_backtest\_breaches |
| cmapi-worker | cmapi\_change\_lead\_time\_seconds{plugin, action, approval}, cmapi\_jobs\_pending{kind}, cmapi\_job\_failures\_total{kind}, cmapi\_sync\_drift\_total, cmapi\_git\_operations\_total and \_duration\_seconds, cmapi\_outbox\_pending, cmapi\_open\_change\_requests\_oldest\_age\_seconds{status, environment} (alerts on age, not on count), cmapi\_approval\_timeout\_seconds{environment}, cmapi\_config\_info{hash}, cmapi\_operation\_runs\_total{template, engine, result} |
| Cluster imports | cmapi\_cluster\_status{cluster\_id, status}, cmapi\_cluster\_token\_expiry\_seconds{cluster\_id}, cmapi\_cluster\_api\_calls\_total and \_duration\_seconds |
| cmapi-capacity | cmapi\_capacity\_snapshot\_age\_seconds{cluster\_id}, cmapi\_capacity\_snapshot\_runs\_total{result}, cmapi\_thanos\_query\_duration\_seconds{cluster\_id}, cmapi\_cluster\_commitment\_ratio and cmapi\_cluster\_quota\_headroom{cluster\_id, environment, region, resource}, cmapi\_capacity\_target\_ratio{environment, resource, level} (capacity.targets, so one alert rule serves every environment), cmapi\_analysis\_runs\_total{result}, cmapi\_analysis\_slack\_cores{environment, region, kind}, cmapi\_recommendations{state} |
| Adoption | cmapi\_namespaces{cluster\_id, state}, cmapi\_adoptions\_total{result} |

**Collection.** User workload monitoring is enabled on each instance's hub (enableUserWorkload: true). The Helm chart ships one ServiceMonitor per component, each scraping a separate metrics port that the Route never exposes; a NetworkPolicy admits only openshift-user-workload-monitoring to it.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cmapi-capacity            # also cmapi-api and cmapi-worker
  namespace: cmapi
  labels: {app.kubernetes.io/part-of: cmapi}
spec:
  selector:
    matchLabels: {app.kubernetes.io/name: cmapi-capacity}
  endpoints:
  - port: metrics                 # 9090, separate from the API port
    path: /metrics
    interval: 30s
```

Keycloak's own metrics reach the same Prometheus through a ServiceMonitor in cmapi-sso.

**System metrics, self-reported.** Each component also reports its own resource use, so the KPI board says whether cmapi itself has room, not only whether requests flow. The approach is the one already proven in the group-sync dashboard's KPI module (gsd/kpi):

- **One definition, two surfaces.** Every system KPI is one definition in cmapi-core (cmapi.core.kpi: name, kind, bounded labels, privacy class, collector). render\_prom emits it on /metrics and render\_json serves the same number to the portal's KPIs tab through GET /api/v1/admin/kpi, so the page and Prometheus read one collector and cannot drift.
- **The pod's own cgroup.** Each process reads the cgroup v2 files it can already read as non-root, with no extra RBAC: memory.current and memory.max, cpu.max and cpu.stat. The cgroup is what the kernel limits and OOM-kills on; a process RSS figure misses page cache and child processes such as the Kyverno CLI and kubeconform.
- **Throttling is the saturation signal.** nr\_throttled over nr\_periods shows a component hitting its CPU limit while utilisation still reads as headroom, so it has its own threshold.
- **Unavailable is not zero.** A value that cannot be measured (cgroup v1, a limit of max, a database that does not answer) is omitted from /metrics and shown as unavailable on the page, never as 0.
- **Bounded, public-safe labels.** component (api, worker, capacity) plus the pod Prometheus adds; never a user, team, namespace or request. /metrics is scraped without user authentication, so anything that counts people is an internal KPI, served only in the JSON behind the platform role.
- **One collector for shared figures.** Database figures are measured every 30 seconds by the worker that holds the discovery lock, so they are not multiplied by replicas; cmapi\_leader says which pod that is.
- **Thresholds are configuration.** kpi.thresholds in the chart: memoryPercent 80, cpuPercent 80, throttledPercent 1, dbConnectionsPercent 80, dbVolumePercent 80, backupMaxAgeHours 26. Each amber meter on the page states its rule ("watch: memory 84% > 80% of limit").

| Family | Labels | Source |
| --- | --- | --- |
| cmapi\_process\_memory\_bytes, cmapi\_process\_memory\_limit\_bytes | component | cgroup memory.current, memory.max; limit absent when unlimited |
| cmapi\_process\_cpu\_usage\_seconds\_total, cmapi\_process\_cpu\_limit\_cores | component | cgroup cpu.stat usage\_usec, cpu.max; rate(usage) / limit is utilisation |
| cmapi\_process\_cpu\_periods\_total, cmapi\_process\_cpu\_throttled\_periods\_total, cmapi\_process\_cpu\_throttled\_seconds\_total | component | cgroup cpu.stat; the saturation signal |
| cmapi\_event\_loop\_lag\_seconds (histogram) | component | an asyncio probe every second; a blocked loop delays every request on that pod |
| cmapi\_component\_replicas | component, state (desired, ready) | the Deployments in the cmapi namespace, through a Role with get, list, watch on deployments |
| cmapi\_db\_pool\_connections, cmapi\_db\_pool\_size | component, state (in\_use, idle, overflow, waiting) | SQLAlchemy pool events |
| cmapi\_db\_size\_bytes | schema (cmapi, capacity) | pg\_total\_relation\_size summed per schema |
| cmapi\_db\_wal\_bytes, cmapi\_db\_connections, cmapi\_db\_connections\_max, cmapi\_db\_oldest\_transaction\_seconds | none | pg\_ls\_waldir, pg\_stat\_activity and max\_connections, read with the pg\_monitor role |
| cmapi\_db\_backup\_last\_success\_timestamp\_seconds, cmapi\_db\_backup\_size\_bytes | none | the backup tool's status; omitted when nothing reports (open question) |

Two figures come from the platform rather than from cmapi, and are read by the rules and dashboards through the hub's Thanos Querier: container restarts and OOM kills (kube-state-metrics) and the database volume's fill (kubelet\_volume\_stats). prometheus\_client's own process\_\* and python\_gc\_\* series stay on as a cross-check.

**Alerts (PrometheusRule, shipped in the chart).**

| Alert | Fires when | Severity |
| --- | --- | --- |
| CmapiHighErrorRate | 5xx above 2% of requests for 10 min | critical |
| CmapiIdpUnavailable | Callers getting idp-unavailable for 5 min | critical |
| CmapiGitUnavailable | Git operation failures above 20% for 5 min | critical |
| CmapiCapacityServiceDown | No cmapi-capacity replica ready for 5 min | critical |
| CmapiClusterUnreachable | A connected cluster unreachable for 10 min | warning |
| CmapiClusterTokenExpiring | An import token past 90% of its life | warning |
| CmapiCapacitySnapshotStale | Snapshot older than two intervals on any cluster | warning |
| CmapiCapacityTargetBreached | A cluster's commitment critical, CPU or memory, for 1 h (regions are on the Capacity dashboard) | warning |
| CmapiSyncStuck | A request in sync\_failed (merged, not synced within 30 min) | warning |
| CmapiDriftDetected | OutOfSync with no open request | warning |
| CmapiWorkerBacklog | More than 100 jobs pending for 15 min | warning |
| CmapiAutoApprovalPaused | The kill switch has been on for 24 h | info |
| CmapiApprovalBacklog | A request waiting in pending\_approval for more than half of its environment's approval window | info |
| CmapiMemoryNearLimit | A component above 80% of its memory limit for 15 min | warning |
| CmapiCpuThrottled | A component throttled in more than 1% of CPU periods for 30 min | warning |
| CmapiPodRestarting | A cmapi container restarted or was OOM-killed in the last 15 min | warning |
| CmapiEventLoopBlocked | Event-loop lag p99 above 250 ms for 10 min | warning |
| CmapiDbConnectionsHigh | Database connections above 80% of max\_connections, or requests waiting on a pool, for 10 min | warning |
| CmapiDbLongTransaction | A transaction open for more than 15 min | warning |
| CmapiDbVolumeFilling | The database volume above 80%, or predicted full within 7 days | warning |
| CmapiDbBackupStale | No successful database backup for 26 h | critical |
| CmapiPolicyBundleDrift | A cluster runs a Kyverno bundle tag other than the pinned one for 30 min | warning |
| CmapiPruneAwaiting | A delete has waited for prune confirmation for more than 24 h | info |

Recording rules precompute the KPI series (for example cmapi:change\_lead\_time\_seconds:p90\_1h by approval, short windows only because user workload monitoring keeps about a day; 7- and 30-day figures come from the monthly KPI export), so dashboards and the monthly report read the same numbers.

**KPIs.** Measured per instance. [`docs/17-kpis.md`](17-kpis.md) is the one definition of each KPI: its formula, its source and labels, its target, its alert and whether code computes it today. Each target is proposed and needs agreement before launch.

| Group | KPIs |
| --- | --- |
| Delivery | Lead time, auto-approved (p90); Lead time, with approval (p90); Approval turnaround (p50 and p90); Auto-approval rate; Self-service rate; Change failure rate |
| Reliability and state | API availability (30 d); Drift events (7 d); Expired namespaces cleaned; Managed coverage; Import health |
| Capacity | Placement accuracy; Capacity freshness; Cluster headroom; Quota efficiency (median); Capacity recovered |
| System | System headroom (p95, 7 d); CPU saturation; Database headroom; Backup freshness |

The KPI review of 2026-11-13 removed four entries from this list, each with its reason in `docs/17`. **Rebuild recovery** (cluster bootstrap to Synced and Healthy, under 1 h) is removed by the owner's decision: "i don't think we should be measuring rebuilding a cluster in under 1 hour. this is not our place." A cluster rebuild is the platform team's work, not cmapi's. Docs coverage is a startup gate and not a measurement. Stability and Event-loop health are alerts (CmapiPodRestarting, CmapiEventLoopBlocked) and not KPIs.

**Dashboards.** Eight dashboards per instance, each showing only that instance's clusters:

1. **Service health:** request rate, errors and latency for api, worker and cmapi-capacity; pods; job backlog; outbox.
2. **Change flow (KPI board):** volume by plugin, environment and status; lead time and approval wait percentiles; change failure rate; drift; self-service rate.
3. **Approvals:** pending approvals and their age by rule and channel, auto-approvals by policy, fallbacks by guard, kill-switch state, namespaces by expiry state, policy failures by policy.
4. **Capacity and placement:** CPU and memory commitment and headroom by environment, region and zone; largest placement; exclusions by reason; snapshot age; reservations.
5. **Namespace efficiency:** slack cores by environment and region, verdict counts, recommendations by state, capacity recovered.
6. **Fleet dependencies:** cluster status and token expiry from imports, cluster API, Thanos and Git latency, sync signal health.
7. **Access:** auth failures by reason, top denied permissions, JWKS refreshes, Keycloak health.
8. **System resources:** memory and CPU against limits and CPU throttling per component and pod, event-loop lag, restarts and OOM kills, replicas ready, database pool and connections, size by schema, WAL, volume fill and backup age.

**Perses first, Grafana optional.** On OpenShift the dashboards appear in the console under Observe → Dashboards (Perses), from the Cluster Observability Operator (1.5 or later, OpenShift 4.15 or later) with its monitoring UIPlugin set to perses.enabled: true. The chart ships them as PersesDashboard resources in the cmapi namespace, with a PersesDatasource there pointing at the hub's Thanos Querier, so they resolve it before any global data source. Access follows Kubernetes RBAC: the platform team gets the Perses dashboard editor role in that namespace, and everyone else gets the viewer role ([Red Hat Developer](https://developers.redhat.com/index%2Ephp/articles/2026/07/07/manage-observability-red-hat-build-perses)).

Which format ships is a chart value, so dashboards are pluggable like everything else: dashboards.provider is perses (the default), grafana (GrafanaDashboard resources for the Grafana Operator) or both. There is one source: the dashboards are kept as Grafana JSON in dashboards/, and CI converts them with percli migrate into PersesDashboard YAML against a Perses container, failing the build if a panel or variable does not convert. A plugin can add panels to these dashboards from its own package; they are merged at build time.

**Cross-instance view.** Each zone's Prometheus sees only its own instance, and instances never call each other. A fleet-wide KPI view would come from each instance's monthly KPI export, the same open question as the cross-instance report.

**Logs and traces.** structlog JSON to stdout with request\_id, cluster\_id, plugin, caller and trace\_id; tokens and secret-bearing manifests are never logged. OpenTelemetry instruments FastAPI, httpx and SQLAlchemy and exports OTLP when a collector exists; it is off by default.

## API documentation: Swagger UI and ReDoc

Every instance documents itself. The OpenAPI document is generated from the running code, so Swagger UI and ReDoc can never drift from what the API accepts. A documentation layer in core refuses to start a route that is not fully described, and CI refuses a spec that breaks v1.

![self-documentation layer · code to spec to docs and checks](diagrams/self-documentation-layer.png)

| Path (per instance) | What it is | Auth |
| --- | --- | --- |
| /docs | Swagger UI with Try it out; signs in through Keycloak | Page public; calls need a token |
| /redoc | ReDoc reference, grouped by plugin, with curl samples | Public |
| /openapi.json, /openapi.yaml | The OpenAPI 3.1 document, with an ETag | Public; holds no data |
| /docs/changelog | Spec changes per release, from the contract diff | Public |

docs.enabled and docs.public in instance.yaml switch these off, or put them behind sign-in, for any instance. Swagger UI and ReDoc are bundled in the image and served from /static, because a network-limited zone may not reach a public CDN.

**The layer: core/docs.py.** Plugins never call FastAPI's decorators directly. They register routes through a documented router that fills in everything the code already knows, and refuses what it cannot fill.

| Filled in automatically | From |
| --- | --- |
| operationId (namespaces\_create, quotas\_patch, …) | Plugin name + verb + resource |
| Tag, tag description, x-plugin-version | The plugin's metadata; a disabled plugin is absent from the spec |
| Required permission and roles (x-cmapi-permission, a "Requires" line in the description) | The route's require() dependency |
| Security: OAuth2 Authorization Code + PKCE (Keycloak) and pasted bearer token | instance.yaml auth; audience cmapi-\<instance> |
| Idempotency-Key, If-Match, ?dryRun headers and parameters | Shared write dependencies |
| 202 + ChangeRequest + Location for writes; 200 Plan for dry runs | The pipeline, for every write route |
| RFC 9457 error responses with an example each | The problem types the route declares, from core/errors.py |
| Environment enum limited to allowedEnvironments; servers set to the instance URL | instance.yaml, so each instance's Swagger offers only its own environments |
| A curl sample per operation (x-codeSamples), with the instance URL and headers | Generated from the operation |
| x-tagGroups for ReDoc: Namespaces and metadata, Access, Capacity and placement, Requests and approvals, Operations, Admin | Plugin category |

```python
# cmapi/plugins/namespaces/router.py: what a plugin writes
router = DocumentedRouter(plugin="namespaces")

@router.write(
    "/clusters/{cluster_id}/namespaces",
    action="create",
    summary="Create a namespace",
    permission="namespaces:write",
    problems=[ValidationFailed, PolicyViolation, CapacityExceeded,
              EnvironmentNotServed, ClusterNotWritable, ChangePending],
)
async def create_namespace(cluster_id: ClusterId, body: NamespaceCreate) -> Plan:
    """Plans a new namespace on the cluster and submits a change request; the bot opens a pull request once it is approved.

    Send the placementId from POST /capacity:place to turn its reservation into
    this request's own. The environment must be one this instance serves.
    """
```

**What it refuses.** The app does not start, and CI fails, when any of these is missing:

- A summary and a docstring description on every route.
- A response model; no bare dict or Any in a public response.
- description and at least one example on every field of every public model (Field(description=…, examples=\[…\])).
- A declared problem list on every route that can fail, with each problem type registered in core/errors.py.
- An example request body on every write.

**CI gates on the spec.**

1. Spectral lint with cmapi's ruleset: operationId, tags, examples, problem responses, no inline schemas, cmapi.net/ keys only in label examples.
2. Contract snapshot (tests/contract/test\_openapi\_snapshot.py): any spec change shows as a diff in the PR, and the changelog entry is generated from it.
3. oasdiff against the last release tag: a breaking change to /api/v1 fails the build. Removing a field needs the deprecation path (deprecated: true and a Sunset header, 6 months).
4. The generated CLI and Python SDK are rebuilt from the spec on every release.

**One spec per instance.** The document is built at startup from the enabled plugins and instance.yaml. Nonprod's Swagger offers rnd and dev; prod's offers prod. Swagger's Authorize button uses that instance's cmapi-docs client, so a token from one instance's docs only works there. cmapi-capacity's internal API is not in the public spec; its gateway routes are.

## Operational safety

- **Keycloak outages.** The verifier keeps the last good signing keys (stale-on-error, persisted to the database) and refreshes them in the background, so an outage stops new sign-ins but not calls with valid tokens. The audience is cmapi-\<instance> everywhere, including the role-claim path resource\_access.cmapi-\<instance>.roles.
- **Rate limits.** Token buckets per caller and per team, separate for writes, :place, :suggest and :export, and at most 3 active placements per team and environment, so nobody can hold a cluster's headroom with reservations.
- **Audit.** An audit\_events table records approvals and rejections, exports, reads that span many namespaces, ServiceAccount token issuance (subject, ServiceAccount and expiry, never the token) and admin switches. sa-tokens responses are never kept in the idempotency cache.
- **Sync signal.** Each cluster's Argo CD Notifications uses its own token and sends its cluster ID; the webhook is a hint, confirmed by reading the Application. Drift is computed per resource from the Application's status, so one open request does not hide drift elsewhere on the cluster.
- **Database recovery.** Targets: at most 15 minutes of data lost, service back within 1 hour. After a restore the auto-approval kill switch starts paused, and a reconcile job rebuilds requests already in Git (pr\_open and later) from the bot's branches and PR bodies, which carry the request ID and plan hash. Requests that were pending\_approval or approved have no PR yet; point-in-time recovery from the WAL keeps them within the 15-minute limit, and anything newer is resubmitted, which the Idempotency-Key makes safe. A break-glass path (two approver-platform, audited) lets the platform team merge in cluster-configs while cmapi is down.
- **Upgrades.** Schema migrations run from a pre-upgrade Job and are expand-then-contract, so old and new replicas run together. Plugins declare the core API range they support, and a request is rendered by the version that planned it. Configuration reloads when its ConfigMap changes, and every pod reports the config hash it runs (cmapi\_config\_info).
- **Testing.** A cmapi-dev instance takes every release before nonprod. An end-to-end suite runs against a real Git host and Argo CD (approve, bot PR, merge, sync, failed sync, revert, expiry, prune confirmation), a load test covers 5,000 namespaces per instance, and failure tests cover Git down, Keycloak down, a failed sync and a database failover.
- **Placement inputs.** Allocatable comes from the live node list in the watch cache; snapshots supply usage and history.

## Deployment topology

Everything an instance runs sits on its zone's hub; the table shows one instance, and each zone repeats it. A managed cluster carries only what the baseline and its own Argo CD put there.

| Where | Namespace | Object | Notes |
| --- | --- | --- | --- |
| Hub | cmapi | Deployment cmapi-api | 2+ replicas behind the instance's Route, for example cmapi-nonprod.ephico2real.com; /metrics on a separate port |
| Hub | cmapi | Deployment cmapi-worker | 2+ replicas; jobs claimed with SKIP LOCKED, discovery under an advisory lock |
| Hub | cmapi | Deployment cmapi-capacity | 2 replicas, ClusterIP only, NetworkPolicy, service-CA TLS, PDB |
| Hub | cmapi | Secrets | Git host credentials (GitHub App or deploy key), database credentials, events HMAC |
| Hub | cmapi | ConfigMaps | clusters.yaml, approval-rules.yaml, authz-roles.yaml, placement.yaml, capacity.yaml, integrations.yaml, adoption.yaml |
| Hub | cmapi-imports | Secrets, one per cluster | Written only by the baseline; cmapi has get, list, watch |
| Hub | cmapi-sso | Keycloak (2 instances, Operator) | Route sso.ephico2real.com; external PostgreSQL; shared by all instances |
| Hub | — | PostgreSQL | Schemas cmapi and capacity; the API role reads capacity but cannot write it |
| Each cluster | cmapi-system | ServiceAccount cmapi-reader | ClusterRole cmapi-reader and cluster-monitoring-view, from the baseline |
| Each cluster | Argo CD's namespace | Root Application | Watches only clusters/\<clusterId>; policies/ pinned to a bundle tag |
| Each cluster | managed namespaces | Namespace, quota, LimitRange, SAs, RoleBindings, cmapi-token-issuer RoleBinding | Rendered by cmapi into Git, applied by Argo CD |
| Git host | — | cluster-configs | Only the cmapi bot merges under clusters/; branch protection requires CI and the cmapi check (approved request ID, plan hash) |
| Hub | cmapi | ServiceMonitors (api, worker, capacity), PrometheusRule, PersesDashboards and a PersesDatasource | Needs user workload monitoring and the Cluster Observability Operator; GrafanaDashboards instead or as well when dashboards.provider says so |

The image is UBI9 python-312 minimal with kubeconform and the Kyverno CLI baked in; api, worker and cmapi-capacity are three entrypoints of one image. Optional pieces (Argo Workflows, Tekton, Kafka) run wherever the platform already runs them.

## Data model

One PostgreSQL, two schemas, each owned by one service: cmapi (API and worker) or cmapi-capacity. The database records history and decisions; it never holds the desired state of a cluster.

| Schema | Table | Holds | Written by |
| --- | --- | --- | --- |
| cmapi | change\_requests | One row per write: plugin, plan, idempotency key, base ETag, status, Keycloak sub | API, worker |
| cmapi | request\_events | Every state change of a request | API, worker |
| cmapi | approvals | Required rule and each approval, including auto:\<policy> | API, worker |
| cmapi | jobs | Work queue (open\_pr, sync\_pr\_state, watch\_sync, notify, expire\_check, operation\_step) | API, worker |
| cmapi | capacity\_reservations | Placement holds per cluster and zone, with release reason | API |
| cmapi | operations, operation\_steps | Operation runs and step state for the built-in engine | API, worker |
| capacity | capacity\_snapshots | Cluster, zone and role rows every snapshot interval; 13 months in monthly partitions | cmapi-capacity |
| capacity | analysis\_sweeps | One row per cluster per day | cmapi-capacity |
| capacity | namespace\_verdicts | Per namespace, resource and day, with evidence; 13 months | cmapi-capacity |
| capacity | recommendations | Proposed sizes, freed capacity, state; request\_id when applied | cmapi-capacity (state changes requested through the API) |
| capacity | namespace\_usage\_daily | Optional daily summary per namespace (analysis.persistNamespaceDaily, off by default) | cmapi-capacity |
| cmapi | audit\_events | Approvals and rejections, exports, wide reads, SA token issuance (never the token), admin switches | API, worker |
| cmapi | expiration\_notices | Notices sent per namespace and threshold, grace start, the delete request opened; the date itself lives in Git | Worker |
| cmapi | approval\_notifications | What each channel sent for a pending request, and the signed links issued and used | Worker |

Indexes that carry correctness: one open request per namespace (partial unique index on cluster and namespace), idempotency per caller, and active reservations per cluster. Namespace usage samples are never stored.

change\_requests keeps the requester's identity as the token showed it at submit time: username, email, first, middle and last name, employee ID, and the service client when a service submitted on someone's behalf. These columns stay in the database and the audit trail; they are never rendered into Git.

In embedded mode the worker writes the capacity schema; the one-writer rule still holds. The outbox table exists only when an event publisher is on. Field-level schemas are in the [v2 design](02-technical-design-v2.md).

## Delivery plan

Five phases to launch and one after it. Each phase ends in something a team can use, and none starts until the previous exit check passes. This sequence replaces the one in v2.

1. **Core, identity and reads.** App factory and plugin discovery; instance configuration with allowedEnvironments, deployed first as the nonprod instance; the documentation layer (core/docs.py) with /docs, /redoc and the spec lint, snapshot and oasdiff gates in CI; Keycloak realm as code, LDAP federation with the employee ID and middle-name mappers and the cmapi-identity client scope, token verification, the directory module (DirectoryProvider, keycloak), roles mapped to permissions (authz-roles.yaml) and namespace-name checks; cluster import from cmapi-imports with the six checks; clusters.yaml policy and metadata with selectors; problem errors, metrics and logs; ServiceMonitors, the PrometheusRule and the Service health, System resources, Access and Fleet dependencies dashboards (Perses); self-reported system metrics (cmapi.core.kpi) and GET /api/v1/admin/kpi. Read plugins: namespaces, rbac-read, identity-read, sync. *Exit:* every read endpoint live on two clusters, imported with no manual step.
2. **First write path and approvals.** Pipeline, idempotency and lock; Kyverno bundle at plan, CI and admission; raw manifest renderer with config/tiers.yaml; Git provider; status worker with polling (Notifications where a cluster opts in); the request state table with :retry and :revert; approval of record (:approve, :reject) with the portal and email channels; bot PRs merged on CI with the cmapi check and the plan hash; approval rules, and auto-approval with its three switches and guards (switched on in Phase 3, once placement gives it fresh capacity data); namespaces and metadata writes; the Change flow and Approvals dashboards with the KPI recording rules. *Exit:* an rnd namespace goes from POST to synced with one approval in the portal and no manual Git step, and a PR edited after approval is refused by the cmapi check.
3. **Capacity and placement.** cmapi-capacity in remote mode with snapshots every capacity.snapshotInterval; cluster and fleet capacity endpoints through the gateway; placement with reservations and zone-failure headroom; the quotas planner (the LimitRange comes from the tier catalog); live 14-day namespace usage for quota changes; the Capacity and placement dashboard. *Exit:* a prod create is placed from stored snapshots with no Thanos call, a medium rnd namespace is auto-approved end to end, and an oversized quota increase is flagged and routed to platform approval.
4. **Service account access.** serviceaccounts, sa-grants and scc-grants with allowlists; sa-tokens. *Exit:* a team SA with a namespace edit grant and the anyuid SCC created through the API, audited end to end.
5. **Lifecycle and launch.** Adoption; optional expiration (never in prod) with extend, set, make permanent, notices, grace and expired-namespace deletes, and the Expiration tab; deletes with extra approvals, Prune=confirm and operator confirmation; the Policies tab from Kyverno policy reports; daily usage sweep and verdicts with a 30-day shadow period, and the Namespace efficiency dashboard; reports, notifier, operations engine (built-in by default) with cluster-onboard and rebuild-verify; portal integration, generated CLI, runbooks, alerts, database backups with a tested restore; the staging and prod instances stood up from the same chart. *Exit:* every KPI in the KPI table reported from its dashboard and the monthly export for one month; v1 contract frozen.
6. **After launch, first quarter.** Recommendations and the rightsizing loop for opted-in rnd and qa namespaces; weekly rebalance report; placement and recommendation backtests. *Exit:* first rightsizing PRs merged, and the placement backtest shows zero overcommit breaches over 30 days.

**Backlog.** Change sets and promote (promote now crosses instances, so it becomes an export from one instance submitted to the next), temporary quota bursts, capacity forecasting, showback, ownership attestation, outbound events, tamper-evident audit. SA token guardrails stay deferred.

## Decisions and open questions

**Decided in this design round.**

| Decision | Instead of | Because |
| --- | --- | --- |
| Keycloak OIDC with read-only LDAP federation | Hashed API tokens in cmapi | One identity source; LDAP groups become roles with no cmapi change |
| Roles in the token, scopes in Git | Roles alone | Pairing role with scope stops a prod approver gaining request rights everywhere |
| Baseline process creates and imports cluster credentials | cmapi onboarding its own ServiceAccount | cmapi never holds cluster-admin and never logs in |
| Separate cmapi-imports namespace | Imports in cmapi's namespace | The import writer cannot read cmapi's Git or database secrets |
| Read-only cluster credential; writes only through Git | Server-side dry-run with write RBAC | No cluster write path exists to misuse |
| Argo Workflows, Events, Tekton, Notifications, Kafka optional | Argo as a dependency | Built-in defaults keep cmapi complete on its own |
| Stored cluster snapshots for placement | Thanos query per create | Onboarding never waits on or fails with Thanos |
| Live 14-day namespace read only on quota change | Storing namespace usage every interval | Small, current, and enough for the decision |
| cmapi-capacity as an internal microservice behind the gateway | Capacity in the API process, or a public service | Isolation without a second auth system |
| Per-environment, per-resource overcommit | One ratio | Memory cannot be throttled |
| Auto-approval with master, per-policy and kill switches plus fixed guards | Always human approval | Baseline requests ship in minutes, and stay stoppable |
| cmapi is the record of approval; only approved requests reach Git, as bot PRs merged when CI passes | Human reviews on the PR counted by a CI check | No Git-to-Keycloak identity mapping; Git cannot bypass approvals; :approve can later be gated by email, Argo Events or ServiceNow |
| Expiry opens a delete request after a 7-day grace; Kyverno only reports | Kyverno cleanup TTL | A Kyverno delete leaves the folder in Git and Argo CD recreates the namespace |
| Expiration optional; never in prod | A TTL on every namespace | Production namespaces must not carry anything that could remove them on a date |
| Namespace deletes wait for an operator to confirm the prune | Argo CD prunes on merge | A bad commit or renderer bug cannot remove namespaces and their data |
| dev small and medium creates auto-approved, like rnd | A person approves every dev create | dev and rnd carry the same risk |
| cmapi writes plain Kubernetes manifests, one folder per namespace; tiers in config/tiers.yaml; namespace-configuration-operator's quota and LimitRange configs retired | project-meta.yml expanded on the cluster by an operator | No extra renderer or CRD to maintain; the PR diff, CI checks and plan hash cover exactly what Argo CD applies |
| Requester identity from the token; employee ID and names in the database only; required team DL, format-checked | Individual owner email in the request body; employee ID on the namespace; DL lookup in the directory | Callers cannot misstate who asked; personal data stays out of Git; DLs are not reliably in Keycloak |
| Access by Keycloak role only (authz-roles.yaml, optional per-role environments); any namespace name outside the reserved ones; cmapi-onboarding (create only) for people and local automation accounts such as bot-user | Scope bindings in authz-scopes.yaml (retired): per-team namespace prefixes, cmapi.net/team checked against the caller, and onBehalfOf required of every service | Team-prefix gating did not scale and cannot fit a bot account; Keycloak alone decides who may do what; an AI agent can onboard namespaces with least privilege |
| The portal (cmapi-portal-ui) is React with TypeScript, built with Vite, using PatternFly as the component library | Preact | PatternFly is Red Hat's design system, built on React, and the OpenShift console is made from it. Users already know its tables, filters, forms and wizards, and it brings accessibility we would otherwise build and test ourselves. It keeps open the option of turning parts of the portal into an OpenShift console plugin later. Preact's advantage is bundle size, which matters little for an internal portal; PatternFly and most of these libraries reach Preact only through its React-compatibility layer, which they do not officially support. |

**Open questions.**

- [ ] Directory: Active Directory or OpenLDAP / IdM? Both mappings are written.
- [ ] Keycloak: a dedicated realm on an existing corporate Keycloak, or a new instance on the hub?
- [ ] Baseline identity: RHACM ManagedServiceAccount, a per-cluster Job, or Vault with ExternalSecrets?
- [ ] Does the baseline also install OpenShift GitOps and each cluster's root Application?
- [ ] Operations engine if one is added: Argo Workflows or Tekton?
- [ ] Event bus if one is added: Kafka or NATS?
- [ ] Confirm capacity.targets, overcommit ratios and the usage verdict thresholds per environment.
- [ ] Should cmapi.net/app (already a governed key) be required on new namespaces, so cross-environment comparison is exact rather than inferred from names?
- [ ] Can teams opt in to automatic rnd and qa decreases with cmapi.net/rightsizing: auto?

* [ ] Is dev a permanent environment, and what are its own approvals, overcommit and thresholds? It takes rnd's until then.
* [ ] Can every zone reach sso.ephico2real.com, or does each zone need its own Keycloak on the same LDAP?
* [ ] One cluster-configs repository per instance (recommended), or one shared repository with path ownership?
* [ ] Should a read-only cross-instance report exist, built from each instance's exports rather than live calls?

- [ ] Is the Cluster Observability Operator (1.5 or later) with the Perses UI plugin on every hub, and does any site still need Grafana (dashboards.provider: both)?
- [ ] Confirm the KPI targets, and who reviews the KPI board each month.
- [ ] Which PostgreSQL runs each instance's database (CloudNativePG, Crunchy, a managed service), and what reports its backups? cmapi\_db\_backup\_\* and the Backup freshness KPI read that status; until it is chosen they show as unavailable.
- [ ] Confirm the system thresholds (memory and CPU 80% of limit, throttling 1%, database connections and volume 80%, backup 26 h) and the resource limits each component ships with.

## Related documents

| Document | Use it for |
| --- | --- |
| [cmapi Technical Design v2](02-technical-design-v2.md) | Field-level detail: plugin contract, schemas, PromQL, Keycloak realm settings, labels, adoption, observability |
| [v2, Usage analysis](03-usage-analysis.md) | Verdicts, thresholds, rightsizing rules and the analysis API |
| [Requirements baseline](05-requirements-baseline.md) | The original business requirements |
| [Argo Events and Workflows review](07-argo-events-workflows-review.md) | Why each Argo piece is optional and where it helps |
| [cmapi request flow mockup](../mockups/cmapi-flow.html) | Clickable walk through placement, auto-approval, quota change, policy reject, cluster import, expiry to delete, a wrong-instance request, and an AI agent onboarding a namespace as bot-user with the cmapi-onboarding role (create only; change and delete refused) |
| [API examples](04-api-examples.md) | Calling the API with Keycloak tokens: which instance to call, curl, device flow, Swagger and ReDoc, Python |
| [cmapi Portal mockup](../mockups/portal/README.md) | The portal per instance: Workflow (including the AI agent onboarding scenario), New namespace (any team, any name that is not reserved), Quotas (CPU, memory and pod quota per namespace, with plan and change), Requests (opening at each request's current step), Approvals (approve or reject before anything reaches Git), Expiration (extend, set, make permanent), Policies (Kyverno results), Capacity (CPU and memory) and KPIs, with Swagger and ReDoc links |
