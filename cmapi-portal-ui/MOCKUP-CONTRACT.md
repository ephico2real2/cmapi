# cmapi-portal-ui: what it takes from the mockup

The contract between `mockups/portal/Main.dc.html` and this app. The mockup does not follow `/build-mockup` (no
`$target`, hex colours in markup, no section types), so `/mockup-to-page-react` requires this inventory.

**The mockup file is the source.** Copy, labels and fields come from it. `npm run model` extracts its logic class,
and `tests/parity.test.mjs` fails if a string it shows is missing here.

## Two builds from one source

| Build | Command | What it is |
|---|---|---|
| The portal | `vite build`, to `dist/` | The portal on the API. It reads `config.json`, signs the person in through Keycloak, and calls the API. It holds no sample data |
| The demo | `vite build --mode demo`, to `dist-demo/` | The mockup's stand-in. It runs the mockup's logic class (`src/model/logic.generated.js`) with no sign-in and no API call. It must not be deployed as the portal |

`tests/api/bundle.test.mjs` reads the names of the mockup's sample data from the mockup. It fails if one of them is in `dist/`.

## The portal on the API (issue #204)

- **Settings.** `config.json` lies beside `index.html`. It gives `apiUrl`, `issuer`, `clientId`, `instance`, `displayName`, `environments` and `otherInstances` (the portals of the other instances, each an https URL). `config.example.json` is a sample. With no valid `config.json`, the portal shows "The portal is not configured." and starts nothing.
- **Sign-in.** Authorization Code with PKCE (`S256`) through `oidc-client-ts` and `react-oidc-context` (`src/portal/auth.ts`). The tokens stay in the memory of the page. `docs/15-keycloak-integration.md` gives the flow and the sources.
- **Data.** `src/api/schema.generated.ts` holds the types of `cmapi/contract/openapi.json` (`npm run api:types`). `src/api/client.ts` is the one client. `src/api/hooks.ts` has one TanStack Query hook for each endpoint: `useMe`, `useRequests`, `useRequest`, `useEvents`, `useTiers`, `useClusters`, `usePlan` (the dry run), `useSubmitNamespace`, `useApprove` and `useReject`.
- **Permissions.** A tab shows only when `GET /api/v1/me` gives its permission in `access.permissions`. The permission of each call comes from the OpenAPI document (`src/api/permissions.generated.ts`). The browser reads no role from the token.
- **Writes.** The create sends an `Idempotency-Key` that the portal makes with `crypto.randomUUID()`: one for each request that the New namespace form sends (#282, docs/04 "Rules for each call"). The same form sent again, after a refusal or a lost answer, carries the same key, so it cannot make a second request. A form changed since its last submit is another request and gets a new key: the API answers an old key with another body with 409 `idempotency-replay`. Leaving the tab ends the form, and the next one starts with no key. Approve and reject take no key: they are not writes to a namespace. Each of the three sends one call at a time: a second click while the first is in flight sends nothing.
- **On the API today (#204, #300):** the page frame and the Workflow, New namespace, Requests and Approvals tabs. Each other tab says "This tab is not on the API yet."

The states of the Requests tab:

| State | Cause | The page shows |
|---|---|---|
| Loading | No answer yet | "Loading requests…" as a status line, and a skeleton |
| Empty | 200 with no rows | The mockup's sentence |
| Forbidden | 403 | "You do not have permission to see requests." and the problem's `detail`. No action |
| Error | 5xx, or no answer from the network | "The requests did not load." with the problem's `detail`, and "Try again" |
| 401 | The token ended | Nothing: one renewal with the refresh token, then the same call. If Keycloak refuses, or the API answers 401 again, "Sign-in did not complete." with "Sign in again" |

The states of the Workflow, New namespace and Approvals tabs (#300) follow the same rules: a status line and a skeleton
while loading, `EmptyState` with `LockIcon` and the problem's `detail` for a 403, a danger `Alert` with the `detail` and
"Try again" for a 5xx or no answer, and the client's renewal for a 401.

| Tab | Loading | Empty | Forbidden | Error |
|---|---|---|---|---|
| Workflow | "Loading the request…" | "No requests on the {instance} instance yet." with no request in the address; "No events yet." (the mockup's) for a request with none | "You do not have permission to see this request." | "The request did not load." (a 404 too: its detail names the request) |
| New namespace | "Loading the form…" | none: the form | "You do not have permission to request a namespace." | "The form did not load." |
| Approvals | "Loading approvals…" | The mockup's "Nothing waiting for you" card | "You do not have permission to see approvals." | "The approvals did not load." |

A refusal of a write is the API's decision, not an error: it shows as the mockup's "Refused: {code}" callout with the
problem's `detail` (a refused dry run, a 409 `self-approval`), or "Not submitted" for the create. A 5xx of a write says
"Not submitted" and that the same submit can be sent again.

### Where the portal's Requests tab differs from the mockup

| Difference | Why |
|---|---|
| "Where it is" shows the last event of the request and who made it | The mockup's step number comes from its sample scenarios. The API has events, and no step count |
| "Open at current step" opens the Workflow tab on that request (`#workflow?request=<id>`) | The mockup opens a sample scenario at its step |
| No "Replay a policy rejection" and no "Replay a wrong-instance request" | They open sample scenarios of the mockup |
| No instance buttons | The mockup says "Mockup only": each instance is its own deployment |
| "Sign out" in the page frame | A signed-in person needs it. The mockup has no session |
| The name and the roles in the page frame come from `GET /api/v1/me` | The mockup shows its sample person |
| A tab that the person has no permission for is not shown | `docs/02`: the portal shows only the actions that a person can take |
| Words for loading, forbidden and error | The mockup's model cannot wait and cannot fail, so it has no words for them |
| The address is `#requests?q=...&state=...` | One portal serves one instance, so the address has no instance |

### Where the portal's Workflow tab differs from the mockup

| Difference | Why |
|---|---|
| A step is one event of `GET /api/v1/requests/{id}/events`: its name, its actor as the lane, its note, its status and its time | The mockup's steps are scripted scenarios. The API records events, the same for every plugin (docs/01, "The workflow is generic") |
| The current position is always the last event, and no step comes after it | The API knows what happened, not what will happen next |
| The scenario buttons are the five newest requests, and the one in the address | The mockup's scenarios are samples |
| No "Systems involved" strip, no "Capacity · cmapi-capacity" panel and no "Argo CD" panel | The API has no per-system state and no capacity or Argo CD data for a request. `docs/diagrams/portal-architecture/README.md`, row 8: "The design names no call for the Capacity, Pull request and Argo CD panels" |
| The Pull request panel shows the PR number as a link, its branch and each file with added or changed, and no check list or reviewers | `PrView` has the number, URL, branch and head. The files come from the request |
| "No pull request. Nothing was written to Git." for a finished request with no PR | The mockup's sentence says "rejected at plan time", which is true of its sample only |
| An open request is read again every 5 seconds until it ends | So that the tab follows a request to `synced` or `merge_failed` (#286) |
| "No requests on the {instance} instance yet." | The mockup always has a scenario |

### Where the portal's New namespace tab differs from the mockup

| Difference | Why |
|---|---|
| A Cluster field: the clusters of the environment and region that take writes, from `GET /api/v1/clusters` | No call ranks clusters or reserves one (#303). The create needs the cluster in its path |
| The Placement preview shows the chosen cluster and, after the dry run, its capacity check (status, cpu and memory, the binding resource) | The same: nothing is ranked or reserved until #303 |
| The approval card says "Not planned yet" until the dry run, then shows the plan's rule, reasons and self-approval rule | The approval belongs to the API (docs/02). The mockup computes it in the browser |
| The dry run's checks are Environment served, Capacity, Expiry and Approval | `PlanView` has no Kyverno bundle or kubeconform result. The mockup's lines for them are samples |
| The tiers come from `GET /api/v1/tiers` for the environment, and the custom tier is not offered | The form has no fields for custom sizes |
| Team, Team DL and Justification start empty; Team DL and the name are required | The mockup's values are its sample. `NamespaceCreate` requires the team DL |
| The default environment is the first one with a cluster that takes writes | So that the form can be sent as it opens |
| The links to the other portals come from `otherInstances` of config.json, named "{instance} portal" | The mockup's links are samples |
| The expiry date's limits are tomorrow and 180 days from today, UTC | The mockup's limits are fixed to its sample day |
| Submit opens the Workflow tab on the new request | As the mockup's Submit opens its workflow |
| Submit sends the body of the dry run on the page. A form with no plan, or changed since its dry run, is planned first, and the next Submit sends it | The mockup's Submit sends without a plan. The person sees the approval that will apply before anything is written |

### Where the portal's Approvals tab differs from the mockup

| Difference | Why |
|---|---|
| The list is `GET /api/v1/requests?status=pending_approval&approver=me` | docs/diagrams/portal-architecture/README.md, row 23 |
| No "Live usage" table and no "How approvers were told" | The API has neither |
| No "Recently decided" card | The API has no filter for it (#304) |
| "Your eligibility" shows the person's roles that grant `requests:approve`, and whether they opened the request | Group membership is decided by the API: `approver=me` lists only what the person's groups can approve |
| Approve stays on for the person's own request, and the API's refusal shows ("Refused: self-approval") | The API decides who may approve (docs/14). The page does not compute a permission |
| A decision stays on its card, with the mockup's callout, until the tab is left | The mockup's behaviour. The list is read again when the tab opens next |
| "Approved by you · N of M" says "Your approval is recorded: N of M. Nothing is in Git yet." | The mockup's sentence names its sample groups |

The demo build has none of these differences. The sections below describe it.

## The demo build: the mockup's logic stands in for the API

The API is built for a part of the mockup. `docs/diagrams/portal-architecture/README.md` maps each action of the mockup to its endpoint. Until each tab calls the API, the demo build keeps the mockup's logic class as the stand-in, and the parity and behaviour suites compare it with the mockup. Components take view-model props from `renderVals()`.

Consequences in the demo build:

- Sample data ships in its bundle.
- There are no loading or error states, because the model is synchronous and cannot fail. Each list has its empty state.
- There is no sign-in. The user shown is the mockup's.
- Paging, filters and search run in the browser inside the model, not as server parameters.
- `src/model/types.ts` infers types from the JavaScript, with gaps typed `any`.

## Tabs

| Tab | State in the model | Datasets, and the API behind each | Actions |
|---|---|---|---|
| Workflow | `tab`, `inst`, `scn`, `i`, `pos`, `playing` | `wf`: `GET /api/v1/requests/{id}/events` | Scenario, step, Back, Next, Reset, Play |
| New namespace | `env`, `tier`, `team`, `region`, `name`, `nsExp`, `dry` | `place`, `appr`: `POST ...?dryRun=true`; `GET /api/v1/tiers` | Dry run, Submit |
| Quotas | `qq`, `qsugOpen`, `qsugIdx`, `qapplied`, `qenv`, `qcluster`, `qtier`, `qstate`, `qsort`, `qlimit`, `qcursor`, `qstarts`, `qat`, `qexport`, `qns`, `qsize`, `qcpu`, `qmem`, `qcpuRaw`, `qmemRaw`, `qplan`, `qsent` | `quotas`: `GET /api/v1/quotas` | Filter, sort, page, letter jump, type-ahead, export, plan, submit |
| Expiration | `xstate`, `xenv`, `xq`, `xcursor`, `xsel`, `xact`, `xuntil`, `xsent` | `exp`: `GET /api/v1/expirations` | Extend, set a date, make permanent |
| Requests | `filter`, `rq`, `rcursor` | `requests`: `GET /api/v1/requests` | Open at current step, replay |
| Approvals | `apvDone`, `apvRejecting`, `apvComment` | `apv`: approvals on `/api/v1/requests` | Approve, reject with a reason, open |
| Policies | `pcluster`, `ppolicy` | `pol`: `GET /api/v1/policies/results`, `/rejections` | Choose cluster, choose policy |
| Capacity | none | `groups`, `clusters`: the capacity snapshots | None |
| KPIs | none | `sys`, `db`, `kpis`, `dashboards`: `GET /api/v1/admin/kpi` | None |

## Where the page differs from the mockup, and why

| Difference | Why |
|---|---|
| Look: colours, spacing, type, control shapes | PatternFly replaces them by design |
| Paging is `Button`s, not `Pagination` | These lists page by cursor; `Pagination` expects to jump to any page |
| Dates are `TextInput type="date"`, not `DatePicker` | Keeps the mockup's `min` and `max` as native limits. PatternFly's `Form` sets `noValidate`, so each form here turns it off |
| The reject reason stays inline, not in a `Modal` | Keeps the mockup's flow, with the reason beside the request |
| Lane colours are PatternFly label colours | No hex in the page; each lane keeps one colour |
| Team DL can be edited | In the mockup it is a controlled field with no handler, so typing does nothing, which looks like a slip |
| The selected type-ahead suggestion shows a check mark | `MenuItem` draws it with `isSelected`, which also gives the option its `aria-selected` |
| The brand mark and avatar letter are gone | Both are decorative (`aria-hidden`) in the mockup |
| Light theme only, with no switch | As the mockup specifies |

## Run it

`npm install`. `npm run dev:demo` runs the demo. `npm run dev` runs the portal: copy `config.example.json` to
`public/config.json` first, and name a real issuer and API in it.

`npm test` checks that `mockups/portal/dist/portal.html`, the generated model and the generated API types are current.
Then it runs the extractor and contract tests, the style check, the type check, the two builds, the portal's suites
(`tests/api`), the behaviour test and the parity test. The browser tests need `npx playwright install chromium`. The type
check of the API needs `npm ci --ignore-scripts` in `tools/openapi-types`. `npm run test:mutants` breaks the portal's
source 65 ways, one at a time, and each must fail the suite or the checks named with it.
