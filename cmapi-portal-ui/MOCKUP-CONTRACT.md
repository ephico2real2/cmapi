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
- **Data.** `src/api/schema.generated.ts` holds the types of `cmapi/contract/openapi.json` (`npm run api:types`). `src/api/client.ts` is the one client. `src/api/hooks.ts` has one TanStack Query hook for each endpoint: `useMe`, `useRequests`, `useRequest`, `useEvents`, `useTiers`, `useClusters`, `usePlan` (the dry run), `useSubmitNamespace`, `useApprove` and `useReject`; for the Quotas and KPIs tabs (#301) `useQuotas`, `useSuggest`, `useExport`, `useNamespace`, `useCatalog`, `usePatchPlan` (the dry run of a change), `useSubmitPatch` and `useKpi`; for the Expiration tab (#318) `useExpirations`, `useExpiryPlan` (the dry run of an expiry change) and `useSubmitExpiry`; for the New namespace form's labels and annotations (#336) `useMetadataKeys`, read through `src/portal/metadataForm.ts`; for the Policies tab (#302) `usePolicyResults` and `usePolicyRejections`; for the Capacity tab (#302) `useCapacity`, read again on focus and every 60 s, which the browser's own cache sends with `If-None-Match` so an unchanged answer is a 304 with no body. A refusal keeps its problem's `errors` (`src/api/problem.ts`), so the form puts each one on its field.
- **Permissions.** A tab shows only when `GET /api/v1/me` gives its permission in `access.permissions`. The permission of each call comes from the OpenAPI document (`src/api/permissions.generated.ts`). The browser reads no role from the token.
- **Writes.** The create sends an `Idempotency-Key` that the portal makes with `crypto.randomUUID()`: one for each request that the New namespace form sends (#282, docs/04 "Rules for each call"). The same form sent again, after a refusal or a lost answer, carries the same key, so it cannot make a second request. A form changed since its last submit is another request and gets a new key: the API answers an old key with another body with 409 `idempotency-replay`. Leaving the tab ends the form, and the next one starts with no key. Approve and reject take no key: they are not writes to a namespace. Each of the three sends one call at a time: a second click while the first is in flight sends nothing.
- **The quota change (#301)** is `PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}`, with `tier`, or `tier: custom` and `quota`. Its dry run (`?dryRun=true`) and its submit each send `If-Match`: the `etag` of `GET .../namespaces/{ns}`, quoted (RFC 9110, section 8.8.3). Submit sends the plan on the page, with the etag that it was planned at: a form with no plan, or changed since its plan, is planned first. A 412 `precondition-failed` or 428 `precondition-required`, of the dry run or of the submit, reads the namespace again and plans the same change on its new etag (docs/04, If-Match); the stale etag is never sent again, and the next Submit sends the new plan with the same `Idempotency-Key`. Its `Idempotency-Key` belongs to the change (cluster, namespace and body): the same change sent again keeps it, a changed one gets a new one. One submit at a time, as above. The export (`GET /api/v1/quotas:export`) is audited by the API, so it is sent once for each click and not cached.
- **The expiry change (#318)** is `POST .../namespaces/{ns}/expiration:extend` with `days`, `:set` with `until` (a namespace with no date) or `:makePermanent`. It follows the quota change: a dry run (`?dryRun=true`) and a submit, each with `If-Match`, Submit sends the plan on the page and plans first when there is none, a 412 or 428 reads the namespace again and plans the same change on its new etag, the `Idempotency-Key` belongs to the change (cluster, namespace, route and body), and one submit at a time. The page computes no date or approval of its own for the write: the plan shows the date that it writes (`cmapi.net/expires-at` in its `namespace.yaml`) and the API's approval.
- **On the API today (#204, #300, #301, #318, #302):** the page frame and every tab of the mockup: Workflow, New namespace, Quotas, Expiration, Requests, Approvals, Policies, Capacity and KPIs. A tab shows only to a person who holds the permission of its first call.

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
| New namespace | "Loading the form…" | none: the form | "You do not have permission to request a namespace." (a 403 of the clusters, the tiers or the rules) | "The form did not load." (also when `GET /api/v1/metadata-keys` answers another shape: "The metadata rules of this instance are not in the form this portal reads: …", never a form with fields missing) |
| Approvals | "Loading approvals…" | The mockup's "Nothing waiting for you" card | "You do not have permission to see approvals." | "The approvals did not load." |
| Quotas | "Loading quotas…" | The mockup's "No namespace on the {instance} instance matches these filters." | "You do not have permission to see quotas." | "The quotas did not load."; a 400 `invalid-cursor` is the mockup's "This page link is out of date" callout instead |
| KPIs | "Loading the KPIs…" | none: the API always answers with its figures | "You do not have permission to see the KPIs." | "The KPIs did not load." |
| Expiration | "Loading expirations…" | The mockup's "No namespace matches this state and search." | "You do not have permission to see expirations." | "The expirations did not load."; a 400 `invalid-cursor` is the "This page link is out of date" callout |
| Policies, results | "Loading the policy results…" | The mockup's "Nothing failing for this selection." | "You do not have permission to see policy results." | "The policy results did not load."; a 400 `invalid-cursor` is the "This page link is out of date" callout |
| Policies, refusals (a panel of its own: it loads and fails apart from the results) | "Loading the refusals…" | "Nothing refused in the last 7 days." | "You do not have permission to see the refusals.", in that panel only | "The refusals did not load." |
| Capacity | "Loading capacity…" | "No cluster of your environments is known to this instance." | "You do not have permission to see capacity." | "Capacity did not load." |

A refusal of a write is the API's decision, not an error: it shows as the mockup's "Refused: {code}" callout with the
problem's `detail` (a refused dry run, a 409 `self-approval`), or "Not submitted" for the create. A refused quota change
shows the mockup's "{status} {code} · nothing written" with "No request was stored and nothing was written to Git." and the
`detail` (a 412 `precondition-failed`, a 409 `change-pending`). A 5xx of a write says "Not submitted" and that the same
submit can be sent again.

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
| The labels and annotations are the instance's own keys, from `GET /api/v1/metadata-keys` (#336): a "Labels" and an "Annotations" section, each with its required keys as inputs, the keys that cmapi sets as read-only inputs with the value it will write, and its optional keys in a collapsed "Optional labels (n)" or "Optional annotations (n)" group. Operator-only keys and other allowed keys are not offered as fields (#365); an operator's protection is the box below (#366) | The mockup hard-codes the CRC keys; an instance with other required keys could not send a valid request. The rules are cmapi's (`metadata-keys.yaml`), served with the same schema as the API document |
| A field's label is the rule's `title`, else its key, then "(required)" or "(optional)": the reference file titles `cmapi.net/team` "Team" and `cmapi.net/team-dl` "Team DL", so the CRC form says "Team (required)" and "Team DL (required)" | The mockup's "Team" has no mark, and its "Team DL (required)" does. WCAG 2.2, 3.3.2: required or optional in words on each field |
| A field's hint is its key (in code, when a title is shown) and the API's words: the config's description and the rule in words. The reference file's descriptions are the mockup's hints, so the CRC form shows "Who owns it, for cost and notices: …" and "Your team's distribution list, …; format only.", each followed by its rule ("Must match ^[a-z0-9-]{2,40}$.", "An address in ['ephico2real.com'].") | One source for the words: the instance's file. The rule in words is what a refusal says |
| "Requested by {user} ({email}), from your sign-in." is its own hint, under the annotations, not part of the Team DL hint | It is about the request's system key `requested-by`, which every instance writes, not about the DL key, which another instance may not have |
| Each field starts empty; its first example is its placeholder. A select (an `enum` key) starts on "—" | An example is a sample, not a default (JSON Schema 2020-12, Validation 9.5); the mockup's values are its sample |
| A value is checked in the browser by the API's own rules, in the validator's order and words: "Required: {rule}", "Not a valid label value", "Not valid: {rule}", "{name} does not start with {value}-". Each pattern runs in a Web Worker with a 200 ms limit; a check that runs out shows nothing, and the dry run decides. An empty required field shows "Required" only after the first Dry run or Submit (WAI-ARIA 1.2, `aria-invalid`) | cmapi decides; the form never refuses what cmapi accepts (a differential test over the #328 corpus). A configured pattern can backtrack in the browser's engine for minutes (docs/18, "Patterns") |
| A refused dry run or submit puts each error that names a shown key under its field, and lists every error in the "Refused" callout, which takes the focus; each listed error of a field is a link to it. An error that names a key the form does not show reads the rules again | WCAG 2.2, 3.3.1 and 3.3.3. The mockup has no field errors |
| When the rules change while the form is open (read again when the window has the focus, and at each opening of the tab), the fields follow them, a removed key's value is not sent, and a warning says "The label and annotation rules of this instance changed. Check the fields below." | A config change restarts the pods; a form open across it would send the old keys |
| The suggested name is `{value}-{environment}` of the key that starts the name (`namespacePrefix`), else of the first required label: `payments-dev` on CRC, `abc-dev` on the company file | The mockup's name is `team-env`. A recorded default of #336 that the owner may change |
| The layout: Environment; Region and Cluster; Labels; Annotations; Namespace name; Tier; Expires; Justification. Dry run checks the form first, as Submit does | The keys come before the name, which follows them. Nothing is planned that the browser already knows cmapi refuses |
| The default environment is the first one with a cluster that takes writes | So that the form can be sent as it opens |
| An operator has a "Deletion protection" group with a "Protect from deletion" checkbox: checked, the body's labels carry `cmapi.net/protected: "true"`; unchecked, no key. Shown when `GET /api/v1/me` says `operator` in the environment (`operatorEnvironments`) and the instance's rules mark `cmapi.net/protected` operator-only (#366) | The mockup has no protection. docs/02: the portal shows only the actions that a person can take; a requester's body with the label gets 403. A checkbox, not a switch: PatternFly's switch saves at once, and a form field is sent by Submit |
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

### Where the portal's Quotas tab differs from the mockup

The API has no usage analysis yet (#310): no verdict, no recommendation and no live usage. Those parts are left out.

| Difference | Why |
|---|---|
| No Verdict column, no "Usage verdict", no "Recommendation" with "Use this size" | `QuotaRow` has no verdict and no recommendation (#310) |
| The attention chips are All, "Near limit ≥ 80%", "Open request" and "Tier outdated": the API's `facets` and `state`. No "Quota tight", "Recommendation", "Oversized" or "Idle" | Those four need the usage analysis (#310). "Tier outdated" is the API's third facet, which the mockup does not have |
| An "Attention" column instead of Verdict: the facets that hold for the row (`near-limit` at a use of 80% or more, `open-request`, `tier-outdated`), in the API's words | The row's state the API has. The tests are the API's `FACETS` (`cmapi/src/cmapi/plugins/quotas`) |
| The heading says "{N} namespaces in scope · {M} near the limit" | "Need attention" counts the severity of the mockup, whose level 1 needs the usage analysis (#310); the API counts near-limit |
| The lede ends at "not what they consume."; the footnote has no "verdicts from the 02:00 usage sweep" | No Thanos read and no sweep is built (#310) |
| No "Live usage · last 14 days" in a planned change | `PlanView` has no usage (#310) |
| The plan's checks are Environment served, If-Match matches the current ETag, Capacity on {cluster} and Approval, as in the New namespace tab | `PlanView` has no Kyverno result and no headroom before and after; the capacity check gives its status, its share of CPU and memory and the binding resource |
| The size hint says that custom sizes go "in the same PATCH", and the detail's footnote names `GET /api/v1/clusters/{c}/namespaces/{ns}` | `.../namespaces/{ns}/quota` is not built (docs/04, "Designed and not built"); the namespace PATCH takes `quota` with `tier: custom` |
| The sizes are the catalog's tiers of the namespace's environment (`GET /api/v1/tiers`), the Tier filter the catalog's tier names, and the custom fields take the catalog's `custom` min, max and step | The mockup's sizes and bounds are its sample. The browser refuses a value outside them, and so does the API |
| The Cluster filter lists `GET /api/v1/clusters` | The mockup lists the clusters of its sample rows |
| A suggestion shows its cluster and why it matched | `Suggestion` has the name, the cluster and why; no environment, team or tier |
| The lock says "{request} holds this namespace in cmapi" and "409 change-pending" | The row has the request's ID only, and the API's code for a held namespace is `change-pending` (`cmapi/src/cmapi/core/db/repo.py`) |
| The 202 shows the request's ID, status, cluster, namespace, approval rule and remaining approvals, and links | The answer of the API, not the mockup's sample body |
| The export has a Download button: the file of the API's CSV | A person needs the file. The callout and the first rows are the mockup's |
| A page size change keeps the first namespace in view only when sorted by name; another sort starts at the first page | The API places a page by name only (`startsWith`) |
| An address that names a namespace (`#quotas?ns={cluster}/{name}`) opens on the page that starts with it | So that a shared link shows the namespace |
| The change form is shown only to a person with `namespaces:write` | docs/02: the portal shows only the actions that a person can take |
| The detail shows a "Protected" label (a lock) and "cmapi refuses a delete request for this namespace (422 namespace-protected): {protectedBy}." to everyone, from the API's `protected` and `protectedBy` of `GET .../namespaces/{ns}`; with an expiry, "Its expiry will not delete it: the delete after its grace is held while it is protected." (#366) | The mockup has no protection and no delete. The API decides which labels protect (approval-rules.yaml), from Git, the input of a delete. "A delete request": no Kyverno rule reads the label, so a delete outside cmapi is not stopped |
| An operator in the namespace's environment who may change it has "Protect from deletion", or "Remove protection" (warning), which opens a dialog: what the request does, a Justification, the plan's If-Match check and approval, then "Submit request". The body is `{"labels": {"cmapi.net/protected": "true"}}` or `null` to remove, with the justification, If-Match and one Idempotency-Key; a 412 reads the namespace again and plans again. Removing names what still protects (`do-not-delete=true`). The 202 is a status message with "Open at current step" (#366) | A button and a confirmation, not a switch: the change is a request that may wait for an approval (removing adds one approver-platform approval, `sensitiveKeys`). The body names the label only, so the control cannot carry another change |
| "Searching…" in the type-ahead while the matches load, and "The matches did not load." for a failed one | The mockup's model cannot wait and cannot fail |

### Where the portal's KPIs tab differs from the mockup

`GET /api/v1/admin/kpi` gives the figures of the process that answered, the database and the live KPIs of
`docs/17-kpis.md`. #147 and #311 list what it does not give yet.

| Difference | Why |
|---|---|
| One component card, the process that answered (`cmapi-api`), not three | `components` has one entry (#147) |
| CPU, Event-loop lag p99, Volume, Volume trend and Last backup read "unavailable" | The API gives CPU time since the start, not a rate, and no lag, volume or backup (#311). "unavailable" is the mockup's word for a figure that nothing reports |
| A component's line is its CPU time since the container started, its CPU limit and when it was measured, not replicas, restarts and OOM kills | The API has no replica, restart or OOM figure (#311) |
| Throttling is the share of periods since the container started | `cpuThrottledPeriods` and `cpuPeriods` count from the start (#311) |
| The KPI cards are the API's live KPIs, in its order, with "target proposed" (or "agreed") for the status | `KpiRow` has no result against the target, and the page does not parse the target text (#311) |
| No "30 days ·" in the heading, and the lede says the KPIs come from cmapi's database | The KPIs have no window (#311) |
| The database's size is one figure, "Size", with the WAL; "Pools" is the answering process's pool | `sizeBytes` is the whole database, and the pool is the process's own |
| The database footnote says the figures are measured when the page asks | The API reads them on each call; no worker measures them every 30 s |
| No Dashboards card | No PersesDashboard ships in `deploy/` yet, and docs/17 says the dashboards are not proven on a cluster |
| The API's `unavailable` sentence is under the cards | It is how to read a null value |

### Where the portal's Expiration tab differs from the mockup

The list is `GET /api/v1/expirations` (#318). It reads `cmapi.net/expires-at` from the watch cache; the writes plan from Git
under `If-Match`. The PR of #318 records why the two agree.

| Difference | Why |
|---|---|
| The numbers of the lede (30, 180, 14, 7 and 1, 7) and the actions' limits come from the API's `rules`; the lede says "approver-platform approves" and ends at "an operator confirms" | `rules` is per environment (config/expiration.yaml). The approving group of the API is approver-platform, and the mockup's "platform-leads" is its sample. The prune confirmation is in Argo CD only in argocd mode |
| "Make permanent" says "adds approver-platform"; "Set a date" says "at most 30 days from today", and its date field takes tomorrow to 30 days out | The API's rules: `:set` takes a date at most maxExtensionDays away (`rules.py`, plan_set), not "within 180 days of creation" |
| "Today" is the API's `today`, not the browser's clock | The days left, the states and the plan are counted from the day the API plans from |
| A row past grace reads "-9 (grace over)" | The mockup's formula gives a negative count of grace days left |
| No "Extensions" row in the detail | The API does not count extensions yet |
| "Notices sent" is what the database records; no `expire_check` job sends notices yet, so it reads "none yet" | The job is not built (docs/08) |
| The detail's footnote names `GET /api/v1/clusters/{c}/namespaces/{ns}` and its ETag, and says the list reads the date from the watch cache | `GET .../namespaces/{ns}/expiration` is not built; the namespace read gives the etag of If-Match |
| "Plan change" beside the Submit button, and the plan's checks "If-Match matches the current ETag" and "The plan writes cmapi.net/expires-at: {date}" (or "no cmapi.net/expires-at"), with the API's approval | As the Quotas tab: the person sees the plan of the API before anything is written. The mockup computes the approval in the browser |
| The lock is "Open request: {id}", "{id} holds this namespace in cmapi. One open request per namespace, so another change waits until it closes.", with "Open at current step" | The row has the request's ID only |
| The 202 shows the call, the request's ID and status, the date that the plan writes and the approval's rule and remaining approvals | The answer of the API, not the mockup's sample body |
| The footnote shows the call that the page sent, with its `limit` and `q`, and "today is" the API's day | The mockup's footnote is its sample |
| An address that names a namespace shows it when it is on the page; the search narrows the list to it | The list is sorted by urgency, and the API places a page by its cursor only |
| The change form is shown only to a person with `namespaces:write` | docs/02: the portal shows only the actions that a person can take |
| On an instance where no namespace can expire (the API's `rules` is empty), the mockup's prod callout, with "{instance} · never expires" and no sample rows | The mockup's prod rows name its sample policies and clusters |

### Where the portal's Policies tab differs from the mockup

The tab is `GET /api/v1/policies/results` and `GET /api/v1/policies/rejections?since=7d` (#302). The designs and their
arbitration are in `docs/reviews/2026-11-17-issue-302-policies/`.

| Difference | Why |
|---|---|
| "Pinned for this instance:" names the Kyverno CLI that the image pins and each environment's mode ("Kyverno v1.20.0; audit in dev, rnd"), from the API's `policy` object | The owner, #302: the tab shows the engine, each environment's mode and the pinned version. cmapi renders the bundle from its configuration and has no bundle tag |
| A Mode column (the configured mode; "audit (cluster: Deny)" when the cluster's copies carry other actions) | The owner, #302: a reader must know whether a Kyverno result was a warning (audit) or a denial (enforce). The mode is never guessed from fail or warn: Kyverno reports the fail of an unscored policy as warn |
| "Bundle running" is "current", or what is off ("1 missing, 3 differ", "N with other actions"), by `cmapi.net/policy-digest`; the head's pill says "off the bundle" | No bundle tag exists (design B, M8); a digest per rendered policy says whether the cluster runs what cmapi renders |
| Each cluster's state: ok, Kyverno not installed, no access to the reports, unreachable since, stale since, N rows not listed, off the bundle, loading, mode off, Kyverno off; the API's `stateDetail` under the table | The API's states (design A and B). The mockup's "breaker: 140 results dropped" needs Kyverno's breaker metric from Thanos, which cmapi does not read yet (deferred by the arbitration) |
| The clusters' footnote says what the states are, and that a cluster off the bundle is one whose policies differ from the render; it does not name CmapiPolicyBundleDrift | That alert is not built, and there is no tag to compare |
| "What it checks" is index.json's rule ("label cmapi.net/team: pattern"), or a hand-written policy's description | The bundle names what each rendered policy checks; the mockup's sentences describe its sample policies |
| The footnote of the policies is the hidden counts: results on namespaces that cmapi does not manage, of other policies, and of policies no longer on the cluster | Design B: what the caller does not see is counted, never named. The mockup's line on legacy ClusterPolicies is one case of "other policies" |
| A row's Policy cell has its rule ("rule prefix") | The owner, #302: Kyverno's findings with policy, rule and message |
| The rows page by cursor ("1–25 of 30 · by namespace", Previous and Next) | The list contract; the mockup shows its six sample rows |
| The refusals have a By column: the username only | The owner, 2026-11-17: a stored refusal shows the username, never the email, the employee ID or the justification, to anyone who can read that environment |
| A refusal's Detail lists each further finding as a line ("warning: <policy> <rule>: <message>"), and "(N times that day)" | Design B: Kyverno's findings beside cmapi's errors; one row per refusal per day |
| The stages are "plan (422)", "plan, warned" and "CI" | The API stores Kyverno's warnings on a plan that went on to a request as `warned` (design B, D7) |
| With `policy.engine: none`, an info callout "Kyverno is off on this instance" and the refusals only | The owner, #302 |
| No "Replay a policy rejection" | It opens a sample scenario of the mockup |

### Where the portal's Capacity tab differs from the mockup

The tab is `GET /api/v1/capacity` (#302), live from each cluster's watch of its quotas and nodes. No capacity snapshot exists
yet (cmapi-capacity, #21), so the API gives usage and history as null and lists them in `notMeasured`. The designs and their
arbitration are in `docs/reviews/2026-11-18-issue-302-capacity/`; the owner's decisions of 2026-11-18 are in the arbitration.

| Difference | Why |
|---|---|
| The lede says the figures come from "each cluster's watch of its quotas and nodes", and that CPU and memory are "committed and checked separately", not "measured" | No snapshot exists, and nothing measures usage yet. The rest of the lede is the mockup's |
| The head's pill is "live from the watch · no snapshots yet", not "snapshot 17:00 · every 30 min" | The same: there is no snapshot interval to show |
| The Snapshot column is **As of**: the minute of the cluster's last good read | The API's `asOf`, cut to the minute |
| Each meter has its size under it: the basis first, then the other ("simulated 64 cores · nodes 7.8 cores") | The owner, 2026-11-18: the check keeps `simulatedCapacity` until #21; the tab labels it "simulated" and shows the nodes' real allocatable beside it |
| A commitment over 100 % fills the bar in the danger tone and says its figure ("462%"); a negative headroom says "over by 694.2 cores"; the status is "over · cpu" | The API's `over` status (design B). The mockup has no cluster over 100 % |
| An unknown commitment draws no bar and says "—", with no `aria-valuenow` | The mockup draws a 0 % bar for its stale cluster, which a screen reader reads as 0. Unknown is never 0 (#393) |
| A stale cluster keeps its last figures, marked "stale since HH:MM", and is left out of its group | The owner, 2026-11-18. The mockup shows "—" for it |
| The other states are words: loading, unreachable since HH:MM, no access to the quotas, no size; the API's `stateDetail` and `nodesDetail` are lines under the table | The API's named states (designs A and B) |
| A cluster whose clusters.yaml has `writes: false` keeps its figures, says so under the table, and is "placement off" in its group's meta line | The mockup's OCP_GF14 "placement off": a read-only cluster takes no placement (design B) |
| The group's meta line always gives the coverage, then each cluster left out with its reason | docs/02 "Freshness and alignment": coverage and the excluded clusters with their reason |
| Largest placement names each resource's cluster when they differ ("cpu on CRC · memory on OCP_GF15") | Design A: one figure per resource, with its cluster, so two clusters are never read as one placement |
| A group's note gives each of its environments' overcommit, and names the clusters sized by `simulatedCapacity` | The mockup's notes are prose about its samples; these are what the API knows |
| The footnote is built from the API's `targets`, says "(not in capacity.yaml)" for an environment that falls back to 1.0, and a second line defines what is committed and lists `notMeasured` | The mockup's footnote reads its OVERCOMMIT and TARGETS constants |
| No cluster that is not in clusters.yaml, and no "OCP_GF9 not registered yet" | A cluster with no clusters.yaml entry has no environment to scope it by, so the API does not return it (designs A and B) |
| "N clusters of environments where your roles do not read capacity are not shown." | The API's `hiddenClusters`: a count, never a name (docs/14) |

### On CRC

Deployed on CRC from main 130ff6c on 2026-11-16 (OB1 run 13) and walked through `https://cmapi.apps-crc.testing` with TLS
verified, signed in through Keycloak's own form. Screenshots: `screenshots/slice-2-crc/`; measured results:
`docs/09-portal-ui-testing.md`, "Live on CRC".

| Tab | What ran on CRC | Result |
|---|---|---|
| New namespace | Two creates as `cmapi.requester`: `cmapi-live-d` (small) and `cmapi-live-e` (large) | Each dry run showed the plan's checks and the approval that applies (auto by baseline-rnd-namespace; 1 from approver-platform). Each Submit sent one create with one Idempotency-Key, got 202 and opened the Workflow tab |
| Approvals | `cmapi.approver-platform` approved `req-20261116-0003` | "Approved · 1 of 1"; the request went on to `synced` |
| Workflow | Followed both requests with the 5 s re-read | `applied` (info) then `synced`, finished at the last event |
| Requests | Both requests listed; "Open at current step" | Opened the Workflow tab on the request |
| Permissions | `cmapi.viewer`, `cmapi.noaccess` | No New namespace or Approvals for the viewer; no data tab for noaccess |

Open from that walk: #306 (`ProgressStep` with no `id`) and #307 (the scenario button's stale status).

The Quotas and KPIs tabs were deployed on CRC from main 525ca27 on 2026-11-16 (OB1 run 15) and walked the same way, in
Chromium 156 and Chrome 157. Screenshots: `screenshots/slice-3-crc/`; measured results: `docs/09-portal-ui-testing.md`,
"Quotas and KPIs live on CRC".

| Tab | What ran on CRC | Result |
|---|---|---|
| Quotas | The list as `cmapi.requester`: filters, sort, A–Z, paging, type-ahead, export | The 5 namespaces `cmapi-live-a` to `cmapi-live-e`; each control sent its API parameter (`tier`, `env`, `q`, `sort`, `startsWith`, `limit`, `cursor`) and showed the API's rows. The type-ahead called `:suggest` and picked by keyboard. The CSV downloaded with 5 rows, the list's total |
| Quotas, the change | `cmapi-live-e` large to medium (Chromium), then medium to large (Chrome) | The plan and the Submit each sent `If-Match` with the namespace's ETag; "No approval needed" (`dev-change`); 202, then `synced`. The cluster's ResourceQuota changed each time (`requests.cpu` 32 to 16 and back) |
| KPIs | As `cmapi.operator`; the tabs of `cmapi.requester` | The API's figures, and "unavailable" for its one null (`walBytes`) and for the figures it does not give. The requester has no KPIs tab, and the API answers it 403 |

Open from that walk: the 202 callout's "Argo CD re-stamps the quota" on an `apply` instance, added to #309.

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
| New namespace | `env`, `tier`, `team`, `region`, `name`, `nsExp`, `dry` | `place`, `appr`: `POST ...?dryRun=true`; `GET /api/v1/tiers`; the labels and annotations: `GET /api/v1/metadata-keys` | Dry run, Submit |
| Quotas | `qq`, `qsugOpen`, `qsugIdx`, `qapplied`, `qenv`, `qcluster`, `qtier`, `qstate`, `qsort`, `qlimit`, `qcursor`, `qstarts`, `qat`, `qexport`, `qns`, `qsize`, `qcpu`, `qmem`, `qcpuRaw`, `qmemRaw`, `qplan`, `qsent` | `quotas`: `GET /api/v1/quotas` | Filter, sort, page, letter jump, type-ahead, export, plan, submit |
| Expiration | `xstate`, `xenv`, `xq`, `xcursor`, `xsel`, `xact`, `xuntil`, `xsent` | `exp`: `GET /api/v1/expirations` | Extend, set a date, make permanent |
| Requests | `filter`, `rq`, `rcursor` | `requests`: `GET /api/v1/requests` | Open at current step, replay |
| Approvals | `apvDone`, `apvRejecting`, `apvComment` | `apv`: approvals on `/api/v1/requests` | Approve, reject with a reason, open |
| Policies | `pcluster`, `ppolicy` | `pol`: `GET /api/v1/policies/results`, `/rejections` | Choose cluster, choose policy |
| Capacity | none | `groups`, `clusters`: `GET /api/v1/capacity` (live from the watch; the snapshots of #21 fill usage and history later) | None |
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
source 215 ways, one at a time, and each must fail the suite or the checks named with it.
