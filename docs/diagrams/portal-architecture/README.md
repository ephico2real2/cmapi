# Portal architecture: each mockup action and the call behind it

This folder holds one figure set. It shows the architecture of cmapi as the portal mockup sees it.

The source is `mockups/portal/Main.dc.html`, read in full at commit `ecc5cb3`. The list of built endpoints is `cmapi/contract/openapi.json`, which has 32 operations. `cmapi/tests/service/test_portal_map.py` holds this map to that file: a row that says built names an operation of it, a row that says not built names none, and the counts and the list of unused operations are true.

Nothing here was measured on a running system. No cmapi workload runs on a cluster yet.

**After #204 (2026-11-14).** The figures and the sentences below that say "the portal makes no API call" are from before #204. The portal build of `cmapi-portal-ui` now signs a person in and calls `GET /api/v1/me` and `GET /api/v1/requests` (rows 16 to 19, and the page frame). This is proven against a stand-in issuer and a stand-in API only. The arrows of those rows are still dashed in figures 1 and 3: #209 draws them again. The demo build is what the figures show.

## The counts

| Item | Count |
|---|---|
| Tabs in the mockup | 9, and the page frame |
| Actions in the mockup | 64 |
| Actions that make no call | 17 |
| Endpoints that the actions need | 26 |
| Endpoints built, in `openapi.json` | 13 |
| Endpoints built, not in `openapi.json` (`/docs`, `/redoc`) | 2 |
| Endpoints not built | 11 |

## How to read the figures

- A solid box is built. Its code is merged and has tests. Keycloak and LDAP are solid because they exist as shared services.
- A dashed box is not built, or not installed for cmapi.
- A solid arrow is a call that the built code makes.
- A dashed arrow is proposed. Its label says so.
- A grey box shows actions that make no call.
- Red text is a finding.

The portal is dashed in each figure. The React app `cmapi-portal-ui` runs on sample data and makes no API call. Thus each arrow from a portal action is dashed, even where the endpoint is built.

Three boxes are dashed because their state is not certain or not there. Argo CD is not installed for cmapi. No cluster is registered, because cmapi runs nowhere. No Git host is connected to cmapi. The record does not say if a `cluster-configs` repository exists, so the Git host is dashed.

## The figures

| Figure | File name | Shows |
|---|---|---|
| 1 | `1-system-overview.light.png`, `1-system-overview.dark.png` | The portal, the API, the worker, the database, and the services outside cmapi |
| 2 | `2-new-namespace-workflow.light.png`, `2-new-namespace-workflow.dark.png` | The New namespace tab and the Workflow tab |
| 3 | `3-requests-approvals.light.png`, `3-requests-approvals.dark.png` | The Requests tab, the Approvals tab and the page frame |
| 4 | `4-quotas.light.png`, `4-quotas.dark.png` | The Quotas tab |
| 5 | `5-expiration-policies-capacity-kpis.light.png`, `5-expiration-policies-capacity-kpis.dark.png` | The Expiration, Policies, Capacity and KPIs tabs |

## One row for each action

"Open the tab" is the tab button. In the Endpoint column, a row with two endpoints has one status for each, in the same order.

| No. | Tab | Action | Endpoint | Endpoint status | Figure | Note |
|---|---|---|---|---|---|---|
| 1 | New namespace | Open the tab | `GET /api/v1/tiers`<br>`POST /api/v1/capacity:place` | built<br>not built | 2 | The tier list and the placement preview. |
| 2 | New namespace | Environment buttons | `POST /api/v1/capacity:place` | not built | 2 | The preview changes with the environment. |
| 3 | New namespace | Tier buttons | `POST /api/v1/capacity:place` | not built | 2 | The preview changes with the tier. |
| 4 | New namespace | Dry run | `POST /api/v1/clusters/{cluster_id}/namespaces` | built | 2 | With `?dryRun=true`. |
| 5 | New namespace | Submit request | `POST /api/v1/capacity:place`<br>`POST /api/v1/clusters/{cluster_id}/namespaces` | not built<br>built | 2 | The create sends the `placementId` from the placement call. |
| 6 | New namespace | Form fields: Team, Region, Namespace name, Team DL, Expires, Justification | None | No endpoint | 2 | Team, Region, Namespace name, Team DL, Expires, Justification. Dry run and Submit send the values. |
| 7 | New namespace | Links to the other portals | None | No endpoint | 2 | Each link opens the portal of a different instance. |
| 8 | Workflow | Open the tab | `GET /api/v1/requests/{request_id}`<br>`GET /api/v1/requests/{request_id}/events` | built<br>built | 2 | For one request. The design names no call for the Capacity, Pull request and Argo CD panels. |
| 9 | Workflow | Scenario buttons | None | No endpoint | 2 | They choose sample data. Mockup only. |
| 10 | Workflow | Step buttons | None | No endpoint | 2 | Playback in the browser. |
| 11 | Workflow | Reset | None | No endpoint | 2 | Playback in the browser. |
| 12 | Workflow | Back | None | No endpoint | 2 | Playback in the browser. |
| 13 | Workflow | Next step | None | No endpoint | 2 | Playback in the browser. |
| 14 | Workflow | Play or Pause | None | No endpoint | 2 | Playback in the browser. |
| 15 | Workflow | Back to current step | None | No endpoint | 2 | Playback in the browser. |
| 16 | Requests | Open the tab | `GET /api/v1/requests` | built | 3 |  |
| 17 | Requests | Search box | `GET /api/v1/requests` | built | 3 | With `?q=`. |
| 18 | Requests | Status chips (All, Open, Closed) | `GET /api/v1/requests` | built | 3 | The built `status` parameter takes one lifecycle state. It has no Open or Closed group. |
| 19 | Requests | Previous and Next | `GET /api/v1/requests` | built | 3 | With `?cursor=`. |
| 20 | Requests | Open at current step (row) | `GET /api/v1/requests/{request_id}`<br>`GET /api/v1/requests/{request_id}/events` | built<br>built | 3 | Then the Workflow tab shows the request. |
| 21 | Requests | Replay a policy rejection | None | No endpoint | 3 | On the prod instance only. It opens a sample scenario. |
| 22 | Requests | Replay a wrong-instance request | None | No endpoint | 3 | It opens a sample scenario. |
| 23 | Approvals | Open the tab | `GET /api/v1/requests` | built | 3 | With `?status=pending_approval&approver=me`. |
| 24 | Approvals | Open at current step | `GET /api/v1/requests/{request_id}`<br>`GET /api/v1/requests/{request_id}/events` | built<br>built | 3 | Then the Workflow tab shows the request. An expiry request opens the Expiration tab instead. |
| 25 | Approvals | Confirm reject | `POST /api/v1/requests/{request_id}:reject` | built | 3 | The second click on Reject. It sends the reason. |
| 26 | Approvals | Approve | `POST /api/v1/requests/{request_id}:approve` | built | 3 |  |
| 27 | Approvals | Reject (first click) | None | No endpoint | 3 | It opens the reason field. |
| 28 | Page frame, on every | Swagger link | `GET /docs` | built | 3 |  |
| 29 | Page frame, on every | ReDoc link | `GET /redoc` | built | 3 |  |
| 30 | Page frame, on every | Instance buttons | None | No endpoint | 3 | Mockup only. Each instance is a separate deployment with its own URL. |
| 31 | Quotas | Open the tab | `GET /api/v1/quotas` | built | 4 |  |
| 32 | Quotas | Needs attention chips | `GET /api/v1/quotas` | built | 4 | The design has `state=`. The built endpoint has no `state` parameter. |
| 33 | Quotas | Pick a suggestion | `GET /api/v1/quotas` | built | 4 | The list jumps to the row and selects it. The design names no parameter for this jump. |
| 34 | Quotas | Show all matches | `GET /api/v1/quotas` | built | 4 | With `?q=`. |
| 35 | Quotas | Clear the match chip | `GET /api/v1/quotas` | built | 4 |  |
| 36 | Quotas | Env, Cluster and Tier chips | `GET /api/v1/quotas` | built | 4 | With `env=`, `clusterId=` and `tier=`. |
| 37 | Quotas | Sort and Per page chips | `GET /api/v1/quotas` | built | 4 | The built `sort` takes `name` or `used`. `severity` is not built. |
| 38 | Quotas | A to Z letters | `GET /api/v1/quotas` | built | 4 | With `?startsWith=`. |
| 39 | Quotas | Previous and Next | `GET /api/v1/quotas` | built | 4 | With `?cursor=`. |
| 40 | Quotas | Back to the first page | `GET /api/v1/quotas` | built | 4 | After a 400 `invalid-cursor`. |
| 41 | Quotas | Type in the search box | `GET /api/v1/quotas:suggest` | built | 4 | After two characters. |
| 42 | Quotas | Export CSV | `GET /api/v1/quotas:export` | built | 4 |  |
| 43 | Quotas | Manage (row) | `GET /api/v1/clusters/{cluster_id}/namespaces/{ns}/quota` | not built | 4 | The built `GET …/namespaces/{ns}` also returns an ETag, but the mockup names `…/quota`. |
| 44 | Quotas | Plan change | `PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}`<br>`PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}/quota` | built<br>not built | 4 | A tier goes to the namespace PATCH with `?dryRun=true`. A custom size goes to `…/quota`. That Plan change is a dry run is inferred. |
| 45 | Quotas | Submit change | `PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}`<br>`PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}/quota` | built<br>not built | 4 | A tier goes to the namespace PATCH. A custom size goes to `…/quota`. |
| 46 | Quotas | Open at current step (namespace with an open request) | `GET /api/v1/requests/{request_id}`<br>`GET /api/v1/requests/{request_id}/events` | built<br>built | 4 | Shown when a request is open on the namespace. |
| 47 | Quotas | Close (export preview) | None | No endpoint | 4 | It hides the preview. |
| 48 | Quotas | Use this size | None | No endpoint | 4 | It fills the form from the recommendation. Recommendations come from cmapi-capacity, which is not built. |
| 49 | Quotas | New size buttons and fields | None | No endpoint | 4 | Small, medium, large, custom, the cpu and memory fields, Justification. Plan and Submit send the values. |
| 50 | Expiration | Open the tab | `GET /api/v1/expirations` | not built | 5 |  |
| 51 | Expiration | State chips | `GET /api/v1/expirations` | not built | 5 | With `state=`. |
| 52 | Expiration | Search box | `GET /api/v1/expirations` | not built | 5 | The design's parameter list for this endpoint has no search parameter. |
| 53 | Expiration | Env chips | `GET /api/v1/expirations` | not built | 5 | With `env=`. |
| 54 | Expiration | Previous and Next | `GET /api/v1/expirations` | not built | 5 | With `?cursor=`. |
| 55 | Expiration | Manage (row) | `GET /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration` | not built | 5 |  |
| 56 | Expiration | Submit: Request make permanent | `POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:makePermanent` | not built | 5 |  |
| 57 | Expiration | Submit: Set expiry | `POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:set` | not built | 5 |  |
| 58 | Expiration | Submit: Extend | `POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:extend` | built | 5 |  |
| 59 | Expiration | Action buttons and date field | None | No endpoint | 5 | Extend 7, 14 or 30 days, Make permanent, Set a date. Submit sends the choice. |
| 60 | Policies | Open the tab | `GET /api/v1/policies/results`<br>`GET /api/v1/policies/rejections`<br>`GET /api/v1/policies` | not built<br>not built<br>not built | 5 | The mockup names no call for its Clusters and Results by policy cards. `GET /api/v1/policies` is inferred from the design. |
| 61 | Policies | Cluster chips | `GET /api/v1/policies/results` | not built | 5 | A filter on the results. |
| 62 | Policies | Show failures (row) | `GET /api/v1/policies/results` | not built | 5 | A filter on the results. |
| 63 | Capacity | Open the tab | `GET /api/v1/capacity` | not built | 5 | The tab has no other action. |
| 64 | KPIs | Open the tab | `GET /api/v1/admin/kpi` | built | 5 | The tab has no other action. The built endpoint returns four database KPIs and the figures of one component. |

## Actions with no endpoint in the design

- **Placement preview.** The design has `POST /api/v1/capacity:place`, which also makes a reservation. It names no call that ranks clusters and reserves nothing. The figure maps the preview to `capacity:place`. This is inferred.
- **Pick a suggestion.** The mockup jumps to one row by its key. The design names no parameter for this jump.
- **Search box of the Expiration tab.** The design's parameter list for `GET /api/v1/expirations` has no search parameter.
- **Clusters and Results by policy cards.** The mockup names no call for these two cards. The figure uses `GET /api/v1/policies` from the design. This is inferred.
- **Capacity, Pull request and Argo CD panels of the Workflow tab.** The design names no call for them.
- **Instance buttons, scenario buttons and replay buttons.** These are mockup controls. They have no endpoint, and they need none.

## Built endpoints that no mockup action calls

The mockup has no action for these 19 operations of `openapi.json`:

- `GET /api/v1/me`, `GET /api/v1/version`, `GET /api/v1/clusters`
- `GET /api/v1/clusters/{cluster_id}/namespaces`, and `GET` and `DELETE /api/v1/clusters/{cluster_id}/namespaces/{ns}`
- `GET /api/v1/requests/{request_id}/approval-status`
- `POST /api/v1/requests/{request_id}:cancel`, `:retry` and `:revert`
- `GET /api/v1/directory/users` and `GET /api/v1/directory/users/{username}`
- `GET /api/v1/admin/auto-approval`, and `POST /api/v1/admin/auto-approval:pause` and `:resume`
- `GET /api/v1/admin/git-log`, `GET /api/v1/admin/integrations`, `POST /api/v1/admin/prune:confirm`, `GET /api/v1/admin/plugins`

## Text twins

Each block gives the same points as its figure.

```text
Figure 1: the whole system
PORTAL (dashed: not on the API)
  cmapi-portal-ui, a React app on sample data, with no sign-in
  nine tabs: Workflow, New namespace, Quotas, Expiration, Requests, Approvals, Policies, Capacity, KPIs
  - - proposed - -> cmapi-api (REST calls)
  - - proposed - -> Keycloak (sign-in, Authorization Code with PKCE)
CMAPI
  cmapi-api (built): core/auth.py, routers/requests.py, plugins/namespaces, routers/admin.py, core/pipeline.py,
    plugins/quotas and tiers, core/validate, plugins/directory, core/registry.py, routers/me and health
    not built: routes for the expirations list, set and make permanent, policies, capacity, placement, metadata,
    operations, service accounts, grants, tokens, webhooks
    ------> Keycloak (JWKS, admin API)
    ------> PostgreSQL (requests, approvals, audit, jobs)
    - - proposed - -> cmapi-capacity
    - - proposed - -> managed cluster (watch)
  PostgreSQL 16 through CloudNativePG (built; proven on kind, not on CRC)
  cmapi-capacity (not built; capacity is simulated today)
  cmapi-worker (built): open_pr, pr_checks, watch_sync, prune, open_revert, approval_timeout, channel_notify,
    core/git (gitea, github), core/sync.py (apply or argocd)
    not built: expire_check, reservation_expiry, policy_report_sweep, import_clusters, reconcile, kpi_export,
    outbox_publish, operations
    ------> PostgreSQL (claims jobs with SKIP LOCKED)
    - - proposed - -> managed cluster (apply mode)
    - - proposed - -> Argo CD (read sync)
    - - proposed - -> Git host (bot PR)
OUTSIDE CMAPI
  Keycloak (exists, shared; realm cmapi is not on CRC yet)  - - proposed - -> LDAP (user federation)
  LDAP (exists, shared; the bind user cmapi-ldap-bind exists)
  Managed cluster (dashed: none registered yet)
  Argo CD (dashed: not installed for cmapi anywhere)  - - proposed - -> managed cluster (sync)
  Git host, cluster-configs (dashed: not connected to cmapi yet; the github adapter never ran against GitHub, #61)
```

```text
Figure 2: New namespace and Workflow
New namespace tab
  Open the tab, Environment buttons, Tier buttons
    - - proposed - -> GET /api/v1/tiers [built]
    - - proposed - -> POST /api/v1/capacity:place [not built]
    behind: plugins/tiers (built); Capacity plugin, cmapi-capacity (not built)
  Dry run, Submit request
    - - proposed - -> POST /api/v1/clusters/{cluster_id}/namespaces [built]
    behind: plugins/namespaces (built)
  Form fields (6), Links to the other portals
    no call: the values go with Submit; a link opens a portal
Workflow tab
  Open the tab
    - - proposed - -> GET /api/v1/requests/{request_id} [built]
    - - proposed - -> GET /api/v1/requests/{request_id}/events [built]
    behind: routers/requests.py (built)
  Scenario buttons, Step buttons, Reset, Back, Next step, Play or Pause, Back to current step
    no call: playback of data already loaded
```

```text
Figure 3: Requests, Approvals and the page frame
Requests tab
  Open the tab, Search box, Status chips (All, Open, Closed), Previous and Next
    - - proposed - -> GET /api/v1/requests [built]
    behind: routers/requests.py (built)
  Open at current step (row)
    - - proposed - -> GET /api/v1/requests/{request_id} [built]
    - - proposed - -> GET /api/v1/requests/{request_id}/events [built]
    behind: routers/requests.py (built)
  Replay a policy rejection, Replay a wrong-instance request
    no call: a sample scenario: mockup only
Approvals tab
  Open the tab
    - - proposed - -> GET /api/v1/requests [built]
    behind: routers/requests.py (built)
  Open at current step
    - - proposed - -> GET /api/v1/requests/{request_id} [built]
    - - proposed - -> GET /api/v1/requests/{request_id}/events [built]
    behind: routers/requests.py (built)
  Confirm reject
    - - proposed - -> POST /api/v1/requests/{request_id}:reject [built]
    behind: routers/requests.py (built)
  Approve
    - - proposed - -> POST /api/v1/requests/{request_id}:approve [built]
    behind: routers/requests.py (built)
  Reject (first click)
    no call: opens the reason field
Page frame, on every tab
  Swagger link, ReDoc link
    - - proposed - -> GET /docs [built]
    - - proposed - -> GET /redoc [built]
    behind: main.py (built)
  Instance buttons
    no call: mockup only: one portal per instance
```

```text
Figure 4: Quotas
Quotas tab
  Open the tab, Needs attention chips, Pick a suggestion, Show all matches, Clear the match chip, Env, Cluster and Tier chips, Sort and Per page chips, A to Z letters, Previous and Next, Back to the first page
    - - proposed - -> GET /api/v1/quotas [built]
    behind: plugins/quotas (built)
  Type in the search box
    - - proposed - -> GET /api/v1/quotas:suggest [built]
    behind: plugins/quotas (built)
  Export CSV
    - - proposed - -> GET /api/v1/quotas:export [built]
    behind: plugins/quotas (built)
  Manage (row)
    - - proposed - -> GET /api/v1/clusters/{cluster_id}/namespaces/{ns}/quota [not built]
    behind: Quota routes (not built)
  Plan change, Submit change
    - - proposed - -> PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}/quota [not built]
    - - proposed - -> PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} [built]
    behind: Quota routes (not built); plugins/namespaces (built)
  Open at current step (locked)
    - - proposed - -> GET /api/v1/requests/{request_id} [built]
    - - proposed - -> GET /api/v1/requests/{request_id}/events [built]
    behind: routers/requests.py (built)
  Close (export preview), Use this size, New size buttons and fields
    no call: in the browser; Plan and Submit send the values
```

```text
Figure 5: Expiration, Policies, Capacity and KPIs
Expiration tab
  Open the tab, State chips, Search box, Env chips, Previous and Next
    - - proposed - -> GET /api/v1/expirations [not built]
    behind: Expiration routes, expire_check (not built)
  Manage (row)
    - - proposed - -> GET /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration [not built]
    behind: Expiration routes, expire_check (not built)
  Submit: Request make permanent
    - - proposed - -> POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:makePermanent [not built]
    behind: Expiration routes, expire_check (not built)
  Submit: Set expiry
    - - proposed - -> POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:set [not built]
    behind: Expiration routes, expire_check (not built)
  Submit: Extend
    - - proposed - -> POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:extend [built]
    behind: plugins/namespaces (built)
  Action buttons and date field
    no call: the choice goes with Submit
Policies tab
  Open the tab, Cluster chips, Show failures (row)
    - - proposed - -> GET /api/v1/policies/results [not built]
    - - proposed - -> GET /api/v1/policies/rejections [not built]
    - - proposed - -> GET /api/v1/policies [not built]
    behind: plugins/policies (not built)
Capacity tab
  Open the tab
    - - proposed - -> GET /api/v1/capacity [not built]
    behind: Capacity gateway, cmapi-capacity (not built)
KPIs tab
  Open the tab
    - - proposed - -> GET /api/v1/admin/kpi [built]
    behind: routers/admin.py, core/kpi.py (built)
```

## Diagram sources

`source.html` is the source of the five figures. The PNG files come from it. Do not edit a PNG file.

To render the figures again, run this command from the root of the repository:

```sh
diagram-render docs/diagrams/portal-architecture/source.html docs/diagrams/portal-architecture \
  1-system-overview,2-new-namespace-workflow,3-requests-approvals,4-quotas,5-expiration-policies-capacity-kpis
```

`diagram-render` comes with diagram-kit. The command writes a light and a dark PNG for each figure. It writes nothing if a check fails.

After each render, open each PNG and look at it. The checks do not find a line that crosses a label.

Change the page, the PNG files, the table and the text twins in the same commit. When an endpoint is built, make its box solid and change its row.
