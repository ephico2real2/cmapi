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

- **Cluster probe (#397).** `POST /api/v1/clusters/{id}:probe` is built, but `mockups/portal/Main.dc.html` has no probe action and the portal does not call it. It is listed among the operations no mockup action calls in `docs/diagrams/portal-architecture/README.md`.
- **Settings.** `config.json` lies beside `index.html`. It gives `apiUrl`, `issuer`, `clientId`, `instance`, `displayName`, `environments` and `otherInstances` (the portals of the other instances, each an https URL). `config.example.json` is a sample. With no valid `config.json`, the portal shows "The portal is not configured." and starts nothing.
- **Sign-in.** Authorization Code with PKCE (`S256`) through `oidc-client-ts` and `react-oidc-context` (`src/portal/auth.ts`). The tokens stay in the memory of the page. `docs/15-keycloak-integration.md` gives the flow and the sources.
- **Data.** `src/api/schema.generated.ts` holds the types of `cmapi/contract/openapi.json` (`npm run api:types`). `src/api/client.ts` is the one client. `src/api/hooks.ts` has one TanStack Query hook for each endpoint: `useMe`, `useRequests`, `useRequest`, `useEvents`, `useTiers`, `useClusters`, `usePlan` (the dry run), `useSubmitNamespace`, `useApprove` and `useReject`; for the Quotas and KPIs tabs (#301) `useQuotas`, `useSuggest`, `useExport`, `useNamespace`, `useCatalog`, `usePatchPlan` (the dry run of a change), `useSubmitPatch` and `useKpi`; for the Expiration tab (#318) `useExpirations`, `useExpiryPlan` (the dry run of an expiry change) and `useSubmitExpiry`; for the New namespace form's labels and annotations (#336) and, since #479, its name's two ends, the team's default, the rules of additional keys and each environment's expiry rules, `useMetadataKeys`, read through `src/portal/metadataForm.ts`; for the Policies tab (#302) `usePolicyResults` and `usePolicyRejections`; for the Capacity tab (#302) `useCapacity`, read again on focus and every 60 s, which the browser's own cache sends with `If-None-Match` so an unchanged answer is a 304 with no body. A refusal keeps its problem's `errors` (`src/api/problem.ts`), so the form puts each one on its field.
- **Permissions.** A tab shows only when `GET /api/v1/me` gives its permission in `access.permissions`. The permission of each call comes from the OpenAPI document (`src/api/permissions.generated.ts`). The browser reads no role from the token.
- **Writes.** The create sends an `Idempotency-Key` that the portal makes with `crypto.randomUUID()`: one for each request that the New namespace form sends (#282, docs/04 "Rules for each call"). The same form sent again, after a refusal or a lost answer, carries the same key, so it cannot make a second request. A form changed since its last submit is another request and gets a new key: the API answers an old key with another body with 409 `idempotency-replay`. Leaving the tab ends the form, and the next one starts with no key. Approve and reject take no key: they are not writes to a namespace. Each of the three sends one call at a time: a second click while the first is in flight sends nothing.
- **The quota change (#301)** is `PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}`, with `tier`, or `tier: custom` and `quota`. Its dry run (`?dryRun=true`) and its submit each send `If-Match`: the `etag` of `GET .../namespaces/{ns}`, quoted (RFC 9110, section 8.8.3). Submit sends the plan on the page, with the etag that it was planned at: a form with no plan, or changed since its plan, is planned first. A 412 `precondition-failed` or 428 `precondition-required`, of the dry run or of the submit, reads the namespace again and plans the same change on its new etag (docs/04, If-Match); the stale etag is never sent again, and the next Submit sends the new plan with the same `Idempotency-Key`. Its `Idempotency-Key` belongs to the change (cluster, namespace and body): the same change sent again keeps it, a changed one gets a new one. One submit at a time, as above. The export (`GET /api/v1/quotas:export`) is audited by the API, so it is sent once for each click and not cached.
- **The expiry change (#318)** is `POST .../namespaces/{ns}/expiration:extend` with `days`, `:set` with `until` (a namespace with no date) or `:makePermanent`. It follows the quota change: a dry run (`?dryRun=true`) and a submit, each with `If-Match`, Submit sends the plan on the page and plans first when there is none, a 412 or 428 reads the namespace again and plans the same change on its new etag, the `Idempotency-Key` belongs to the change (cluster, namespace, route and body), and one submit at a time. The page computes no date or approval of its own for the write: the plan shows the date that it writes (`cmapi.net/expires-at` in its `namespace.yaml`) and the API's approval.
- **On the API today (#204, #300, #301, #318, #302):** the page frame and every tab of the mockup: Workflow, New namespace, Quotas, Expiration, Requests, Approvals, Policies, Capacity and KPIs. The New namespace form reads its labels and annotations from `GET /api/v1/metadata-keys` (#336, #368), and an operator protects or unprotects a namespace in the Quotas detail (#366, #378). The portal calls none of the four endpoints of the map that are not built: `POST /api/v1/capacity:place`, `GET` and `PATCH .../namespaces/{ns}/quota`, and `GET .../namespaces/{ns}/expiration` (`docs/diagrams/portal-architecture/README.md`; no call of them is in `src/`).
- **The permission of each tab** is `needs` in `TABS` of `src/portal/PortalApp.tsx`, taken from `src/api/permissions.generated.ts`. A tab shows only to a person whose `access.permissions` holds it:

| Tab | Permission | Of the call |
|---|---|---|
| Workflow | `requests:read` | `GET /api/v1/requests/{request_id}/events` |
| New namespace | `namespaces:create` | `POST /api/v1/clusters/{cluster_id}/namespaces` |
| Quotas | `objects:read` | `GET /api/v1/quotas` |
| Expiration | `objects:read` | `GET /api/v1/expirations` |
| Requests | `requests:read` | `GET /api/v1/requests` |
| Approvals | `requests:approve` | `POST /api/v1/requests/{request_id}:approve` (the list itself is `GET /api/v1/requests`, `requests:read`) |
| Policies | `objects:read` | `GET /api/v1/policies/results` |
| Capacity | `capacity:read` | `GET /api/v1/capacity` |
| KPIs | `reports:read` | `GET /api/v1/admin/kpi` |

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

Since #479 (Phase 4) the New namespace tab follows its own mockup, `mockups/portal/new-namespace-479.html` (the owner's
approved artifact of design section 10), not the `isNew` block of `Main.dc.html`. The design is
`docs/reviews/2026-11-20-issue-479/namespace_metadata.md`, section 7 (P1 to P12). The form keeps the mockup's sections and
order (Where, Name, Labels, Annotations, Expiration, Why, Additional labels and annotations), its words, its live preview
and its Check (dry run) before Submit; PatternFly gives the look. `tests/api/portal.test.mjs` check 6 compares the page with
the mockup's strings in both directions on an instance with the configuration of design section 3.1
(`tests/api/metadata-keys.company-479.json`, the service's answer for `examples/cluster-configs/policies/metadata-keys.company-479.yaml`).

| Difference | Why |
|---|---|
| Where: the Environment buttons, then Region and Cluster, then the Tier buttons with their sizes. A cluster reads "CRC (dev)", as the mockup's | The mockup's three clusters and tiers are samples; the portal's are the API's (`GET /api/v1/clusters`, `GET /api/v1/tiers`). No call ranks clusters or reserves one (#303), so the person chooses the cluster |
| The labels and annotations are the instance's own keys, from `GET /api/v1/metadata-keys` (#336): their titles, descriptions, rules, examples (placeholders) and order. Operator-only keys are not offered as fields; an operator's protection is the "Deletion protection" box (#366) | P1: nothing about a company is in the portal's code. A test fails on a company's domain or sample value in `src/portal` (direct test 479-P1) |
| Name: the key with `x-cmapi-namespace-prefix` first (Mnemonic), then the Namespace field, a PatternFly `InputGroup` with the start (`<mnemonic>-`) and the end (`-<cluster env>`, the key with `x-cmapi-namespace-suffix`) as locked `InputGroupText` with a lock icon. With both values present, the hint uses them to say “Leave empty for a team-wide namespace: abc-dev.” Under it: "Will be created as <name> (N of 63 characters)" | P2. An instance whose keys make neither end keeps one input for the whole name, prefilled with the suggestion of #336; one end alone locks that end |
| The name is checked as typed: with both ends set, typing `payments` gives `abc-payments-dev` and leaving the middle empty gives `abc-dev`. “Will be created as”, the YAML preview and the request body use the same name. The whole name is a DNS-1123 label of 2 to 63 characters. The API refuses `abc--dev` and accepts `abc--x-dev` | C7: the form never refuses what the API accepts |
| The keys that cmapi sets (`x-cmapi-derived-from`) are read-only inputs with the value it will write and an "automatic" label; their hint is the API's words, not the mockup's "A copy of the namespace name." | P3. The words are the instance's (`metadata-keys.yaml`) |
| A key with `x-cmapi-default-from` (Team) copies its source until the person edits it, marked "from Mnemonic" meanwhile; its hint ends "Filled from Mnemonic; you can change it." An unedited default is not sent: cmapi fills it in, and the dry run says `default from company.net/mnemonic` | P4 and plan R5: once edited, never written over. Not sending it lets the dry run show where the value comes from (A7) |
| The optional declared keys are fields in their section, as the mockup shows them, not in a collapsed "Optional labels (n)" group | The mockup of #479. The collapsed group of #336 is gone |
| A field's label is its title, then "(required)" or "(optional)"; the mockup marks required fields with "*" only. An empty optional select is "—", the mockup's "(none)" | WCAG 2.2, 3.3.2: required or optional in words |
| Each field, the name and each additional row are checked as typed, with the API's rules and words; an empty required field shows its error only after the first Check (WAI-ARIA 1.2, `aria-invalid`) | P5. The patterns run in a Web Worker with a 200 ms limit (#336) |
| The preview: Namespace, Cluster, Expires, Quota ("medium: 16 cores · 32Gi · 100 pods"), Approval, and a `CodeBlock` with the Namespace as the form describes it, each value with where it comes from ("automatic", "from Mnemonic", "additional", "from Expires", "required, not set yet"). After a passing check it shows the plan's own `namespace.yaml` ("From the dry run: <path>") and "Lands in Git" | P6 and P7: the API's answer replaces the preview. The mockup's quota and approval ("1 from approver-platform") are computed in its browser; the approval is the API's (docs/02), so it reads "Check (dry run) asks cmapi which approval applies." until a check. The preview is sticky beside the form at PatternFly's `md` width (48rem, 768 px) and above; below 48rem it stacks under the form |
| Check (dry run) first checks the form; with a problem it sends nothing and lists each problem as a link to its control ("The check did not run. Fix these:"); the mockup says "The check failed (422)" for its own checks | The portal's own checks are not a 422 of the API. An API refusal reads "The check failed: <code>", with its errors on their fields and in a list that takes the focus (WCAG 2.2, 3.3.1) |
| A passing check: "The check passed (dry run, 200). Nothing is written yet.", the plan's checks (Environment served, Capacity, Expiry, Approval), the capacity line, "cmapi will set:" with each value and its source from the plan's `metadata` (A7), the approval in words and "Plan hash xxxx…" | The mockup lists three keys; the API gives every key with its source |
| Submit request is `isAriaDisabled` (focusable, described by the status) until a check passes, and again after any change, which says "Changed since the last check. Press Check (dry run) again." | P7 and plan R1. PatternFly's accessibility guidance for a disabled action that keeps its focus |
| Expiration: a PatternFly `DatePicker`, empty by default (permanent), whose calendar offers no day up to today; "No expiry" clears it. Under it: "Expires on <date>, in N days." and, past `maxLifetimeDays`, "More than 180 days: needs one more approval." as a warning; the check runs and cmapi decides. The rules are the environment's entry of `x-cmapi-expiration` | P12, D15: the limit never sets a date. The mockup's date is 25 days out as a sample. Its warning names approver-platform; the answer does not name a group |
| The hint is "Notices to the team DL 14, 7 and 1 days before. It keeps running 7 days after the date.", from `notifyDaysBefore` and `graceDays`. The mockup's "then a delete request is opened" is not said | `x-cmapi-expiration` does not carry `deleteAfterGrace` |
| Where the environment's entry is `enabled: false` or missing, there is no date field: "Expiration is turned off for this environment (expiration.yaml: enabled: false). The namespace is permanent." Where it is enabled with `allowedAtCreate: false`, the note says the date is set later from the Expiration tab | P12. The flag decides, never the environment's name |
| Days are counted from today's UTC date, as the rest of the portal counts them | Plan R7 asks for the server's `today`; `GET /api/v1/metadata-keys` does not carry one. cmapi checks the date again (`expiration-in-past`), so a browser on the wrong day can only be refused, never let through |
| Additional labels and annotations: a PatternFly `ExpandableSection`, closed and empty by default, its toggle counting the rows ("none", "1 label, 0 annotations"); inside, two compact `Table`s (Key, Value, a remove button), "+ Add label", "+ Add annotation", the counters "N of 50" and "N of 50 · B of 65536 bytes", and the allowed prefixes. A new row has placeholder text only ("e.g. example.company.net/key", "e.g. value") | P9 to P11. The answer has no example of an extra key, so the placeholder is built from the first allowed prefix. The mockup names reserved prefixes in its hint; the answer lists them only where an allowed prefix meets one |
| Each row is checked against the answer's `propertyNames` (key syntax; a declared key: "This key has its own field above."; an operator-only key; the allowed prefixes; the keys cmapi refuses there), its value against `additionalProperties` (a label value) or the bytes of `x-cmapi-other-keys`, and a duplicate in its table. The bytes are UTF-8, of the values, as cmapi counts them | P10, C7: `propertyNames` is sound, so the form refuses nothing that cmapi accepts. The mockup counts keys and values; cmapi counts values |
| Closing the section keeps its rows: they are sent in the same `labels` and `annotations` maps and shown in the preview. A Check with a problem in a closed section opens it | P11 |
| The Justification is optional | The API takes a create without one; the mockup marks it required |
| An operator has a "Deletion protection" group with a "Protect from deletion" checkbox (#366) | The mockup has no protection |
| The links to the other portals come from `otherInstances` of config.json, named "{instance} portal" | The mockup's links are samples |
| Submit opens the Workflow tab on the new request; the mockup shows "Request … submitted (mock)" | The Workflow tab follows the request |
| When the rules change while the form is open, the fields follow them, a removed key's value is not sent, and a warning says "The label and annotation rules of this instance changed. Check the fields below." | A config change restarts the pods; a form open across it would send the old keys |

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
| Each cluster's state: ok, Kyverno not installed, no access to the reports, not imported, unreachable since, stale since, N rows not listed, off the bundle, loading, mode off, Kyverno off; the API's `stateDetail` under the table | The API's states (design A and B). The mockup's "breaker: 140 results dropped" needs Kyverno's breaker metric from Thanos, which cmapi does not read yet (deferred by the arbitration) |
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
| The other states are words: loading, not imported, unreachable since HH:MM, no access to the quotas, no size; the API's `stateDetail` and `nodesDetail` are lines under the table, and a cluster that is not connected has its one detail once | The API's named states (designs A and B); `not-imported` for a cluster that clusters.yaml names and no import Secret does (#404) |
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

The Expiration tab was walked on CRC on 2026-11-17 (OB1 run 17, main 9ba33b2; `docs/09-portal-ui-testing.md`, "Expiration live on CRC"). The Policies and Capacity tabs and the protection control are recorded in `docs/09-portal-ui-testing.md` at the stage built-mocked, against the built portal, the stand-in issuer and the stand-in API: no walk of them on CRC is recorded there. `HANDOVER-AND-RESUME.md` records them on CRC: the protection requests in OB1 run 20 (row #366, #374), the Policies tab at 1440 and 390 px in run 21 (row #302 (Policies)), and the Capacity tab in run 23 ("Where it stands", row "Portal").

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
| New namespace | `env`, `tier`, `team`, `region`, `name`, `nsExp`, `dry` | `place`, `appr`: `POST ...?dryRun=true`; `GET /api/v1/tiers`; the clusters: `GET /api/v1/clusters`; the labels and annotations: `GET /api/v1/metadata-keys` | Dry run, Submit |
| Quotas | `qq`, `qsugOpen`, `qsugIdx`, `qapplied`, `qenv`, `qcluster`, `qtier`, `qstate`, `qsort`, `qlimit`, `qcursor`, `qstarts`, `qat`, `qexport`, `qns`, `qsize`, `qcpu`, `qmem`, `qcpuRaw`, `qmemRaw`, `qplan`, `qsent` | `quotas`: `GET /api/v1/quotas`, `:suggest`, `:export`; the detail: `GET .../namespaces/{ns}`; the change: `PATCH .../namespaces/{ns}` | Filter, sort, page, letter jump, type-ahead, export, plan, submit, protect, remove protection |
| Expiration | `xstate`, `xenv`, `xq`, `xcursor`, `xsel`, `xact`, `xuntil`, `xsent` | `exp`: `GET /api/v1/expirations`; the change: `POST .../expiration:extend`, `:set`, `:makePermanent` | Extend, set a date, make permanent |
| Requests | `filter`, `rq`, `rcursor` | `requests`: `GET /api/v1/requests` (with `state=`, `q=` and `cursor=`) | Open at current step, replay |
| Approvals | `apvDone`, `apvRejecting`, `apvComment` | `apv`: approvals on `/api/v1/requests` | Approve, reject with a reason, open |
| Policies | `pcluster`, `ppolicy` | `pol`: `GET /api/v1/policies/results`, `GET /api/v1/policies/rejections?since=7d` | Choose cluster, choose policy |
| Capacity | none | `groups`, `clusters`: `GET /api/v1/capacity` (live from the watch; the snapshots of #21 fill usage and history later) | None |
| KPIs | none | `sys`, `db`, `kpis`, `dashboards`: `GET /api/v1/admin/kpi` | None |

## Where the page differs from the mockup, and why

| Difference | Why |
|---|---|
| Look: colours, spacing, type, control shapes | PatternFly replaces them by design |
| Paging is `Button`s, not `Pagination` | These lists page by cursor; `Pagination` expects to jump to any page |
| Dates are `TextInput type="date"`, not `DatePicker`, except the New namespace form's Expires, which is PatternFly's `DatePicker` (#479 P12) | Keeps the mockup's `min` and `max` as native limits. PatternFly's `Form` sets `noValidate`, so each form here turns it off |
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
source 220 ways, one at a time, and each must fail the suite or the checks named with it.
