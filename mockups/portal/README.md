# cmapi Portal mockup

Source of the portal mockup. It is a Claude Design canvas artboard (`Main.dc.html` plus
`canvas.json`). It renders in the Design canvas and, through a small runtime, as a plain HTML page.

Live version: https://claude.ai/artifact/HW3mp5RRmuapPhj8beBH1M

## Open it outside claude.ai

- **Double-click or publish:** `dist/portal.html` is one self-contained file.
- **While editing:** serve this folder (`python3 -m http.server`) and open `index.html`, which fetches
  `Main.dc.html`. A browser will not fetch from `file://`, so `index.html` needs a server.
- **Rebuild after any edit:** `node scripts/build-portal.mjs`. Add `--check` to fail if the file is out of date.

The bar above the artboard switches instance. The hash holds the instance and tab (`#staging/quotas`) and follows
the portal's own controls. The page works offline; without Google Fonts it falls back to system fonts, so its text
then wraps differently.

## How the runtime works

`runtime/dc-lite.js` is a small renderer with no dependencies. `Main.dc.html` stays the single source: the runtime
parses it, runs its `Component` class, and renders from `renderVals()`. Every `setState` re-renders, and the result
is patched into the page by position, so focus, caret and scroll survive.

It copies these details of the canvas runtime, because they decide the layout: `<sc-for>` and `<sc-if>` add no
element, a text hole renders in `<span class="sc-interp">`, and a bare newline between elements is dropped.

## What the runtime does not support

Only what `Main.dc.html` uses. It has none of: `<dc-import>`, `<x-import>`, expressions in holes (`{{ !x }}`), pseudo-class
attributes, keyframe tracks, streaming placeholders, the editor, `forceUpdate`, `componentDidUpdate`, the callback
of `setState`, or events other than `onClick`, `onChange`, `onSubmit` and `onKeyDown`. An unsupported event attribute
stops the page with a message. Light theme only, as in the source.

## Tests

In `tests/portal/`, after `npm install` and `npx playwright install chromium`:

| Command | What it checks |
|---|---|
| `node logic.test.mjs` | The logic class with no browser: scenarios, 403 and 422 endings, paging, ES2019 syntax, `dist` up to date |
| `node interactions.test.mjs` | Scripted walks with no console errors: every scenario, paging, type-ahead, forms, approvals, expiration, the hash, reflow, offline |
| `node capture.mjs <dir>` | Captures the acceptance views at 1320 px, as PNG and as canonical DOM |
| `node diff.mjs <reference-dir> <dir>` | Pixel-diffs against references named like the captures; a view passes under 0.5% |

To compare with the canvas runtime itself, put a copy of `dc-runtime.js` named `support.js` beside a copy of
`Main.dc.html` in a folder, and pass that folder: `node capture.mjs <dir> <folder>` and
`node interactions.test.mjs --source-dir <folder> --record <file>`, then `--compare <file>` on a normal run.

## What the mockup shows

What it shows, per instance (nonprod, staging, prod; switched with the `instance` tweak):

- **Workflow:** the request flow in the same lanes as `../cmapi-flow.html` (caller, Keycloak,
  cmapi-api, cmapi-capacity, cluster-configs, Argo CD), including a wrong-instance request that
  gets 422 `environment-not-served` with the right instance's URL, and (nonprod) an AI agent signed in
  as `bot-user` with the `cmapi-onboarding` role: it creates a namespace, auto-approved and recorded as
  automated, and its change and delete are refused with 403.
- **New namespace:** schema-driven form limited to the instance's allowedEnvironments. Access comes from
  Keycloak roles only: the team is free text (ownership and cost) and any DNS-1123 name that is not
  reserved may be asked for. With
  placement, an optional expiry date (hidden in prod) and plan preview.
- **Quotas:** every namespace's ResourceQuota (requests.cpu, requests.memory, pods; used
  vs hard) with its usage verdict and any recommendation, for a few hundred generated namespaces
  per instance: A to Z, 25/50/100 per page with previous/next, a letter bar, type-ahead search
  (name prefix, then contains, then team or app), env/cluster/tier filters, sort by name, % used
  or attention, attention counts as one-click filters, and CSV export. Pick one to plan a tier or custom
  change: live 14-day usage, CPU and memory checks against the cluster (zone-failure in prod),
  the approval that will apply, and the 202 or 422 that submitting returns.
- **Expiration:** non-prod namespaces by expiry state (needs action, expiring, in grace, pending delete,
  active, permanent), paged and searchable, with Extend 7/14/30 days, Make permanent and Set a date,
  the limits and the approval each one needs. On the prod instance: "production namespaces never expire".
- **Requests:** drill-down that opens the workflow at the request's current step, newest first.
- **Approvals:** requests waiting in cmapi (nothing in Git yet) with Approve and Reject (a reason is
  required), your eligibility, the approvals so far and the channels that notified approvers.
- **Policies:** Kyverno bundle per cluster against the pinned tag, results by policy, failing resources,
  and cmapi's own refusals at plan time and in CI.
- **Capacity:** CPU and memory commitment and headroom per cluster and group from stored
  snapshots, with the resource that binds each one.
- **KPIs:** System status (each component's memory, CPU, throttling and event-loop lag against
  kpi.thresholds, with the rule beside any amber meter) and the database (connections, volume,
  size by schema, pools, backups; unavailable where nothing reports), then the agreed KPIs and the
  eight dashboards (Perses in the OpenShift console).

The header links to the instance's Swagger UI (`/docs`) and ReDoc (`/redoc`).
