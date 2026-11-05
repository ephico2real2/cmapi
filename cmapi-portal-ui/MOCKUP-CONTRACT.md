# cmapi-portal-ui: what it takes from the mockup

The contract between `mockups/portal/Main.dc.html` and this app. The mockup does not follow `/build-mockup` (no
`$target`, hex colours in markup, no section types), so `/mockup-to-page-react` requires this inventory.

**The mockup file is the source.** Copy, labels and fields come from it. `npm run model` extracts its logic class,
and `tests/parity.test.mjs` fails if a string it shows is missing here.

## Data: no API yet

The API is not built, so the mockup's logic class is this app's stand-in for it (`src/model/logic.generated.js`).
Components take view-model props from `renderVals()`. When the API exists, typed TanStack Query hooks replace
`usePortal` without changing how components read their data; that is phase 2, with the libraries `docs/02` names.

Consequences until then:

- Sample data ships in the bundle. This app is a demo and must not be deployed as the portal.
- There are no loading or error states, because the model is synchronous and cannot fail. Each list has its empty state.
- There is no sign-in. The user shown is the mockup's.
- Paging, filters and search run in the browser inside the model, not as server parameters.
- `src/model/types.ts` infers types from the JavaScript, with gaps typed `any`. OpenAPI types replace it.

## Tabs

| Tab | State in the model | Datasets, and the API behind each | Actions |
|---|---|---|---|
| Workflow | `scn`, `i`, `pos`, `playing` | `wf`: `GET /api/v1/requests/{id}/events` | Scenario, step, Back, Next, Reset, Play |
| New namespace | `env`, `tier`, `team`, `region`, `name`, `nsExp`, `dry` | `place`, `appr`: `POST ...?dryRun=true`; `GET /api/v1/tiers` | Dry run, Submit |
| Quotas | `qq`, `qenv`, `qcluster`, `qtier`, `qsort`, `qlimit`, `qcursor`, `qns`, `qsize` | `quotas`: `GET /api/v1/quotas` | Filter, sort, page, letter jump, type-ahead, export, plan, submit |
| Expiration | `xstate`, `xq`, `xcursor`, `xsent` | `exp`: `GET /api/v1/expirations` | Extend, set a date, make permanent |
| Requests | `filter`, `rq`, `rcursor` | `requests`: `GET /api/v1/requests` | Open at current step, replay |
| Approvals | `apvDone`, `apvRejecting`, `apvComment` | `apv`: approvals on `/api/v1/requests` | Approve, reject with a reason, open |
| Policies | `pcluster`, `ppolicy` | `pol`: `GET /api/v1/policies/results`, `/rejections` | Choose cluster, choose policy |
| Capacity | none | `groups`, `clusters`: the capacity snapshots | None |
| KPIs | none | `sys`, `db`, `kpis`: `GET /api/v1/admin/kpi` | None |

## Where the page differs from the mockup, and why

| Difference | Why |
|---|---|
| Look: colours, spacing, type, control shapes | PatternFly replaces them by design |
| Paging is `Button`s, not `Pagination` | These lists page by cursor; `Pagination` expects to jump to any page |
| Dates are `TextInput type="date"`, not `DatePicker` | Keeps the mockup's `min` and `max` as native limits |
| The reject reason stays inline, not in a `Modal` | Keeps the mockup's flow, with the reason beside the request |
| Meters have no threshold mark | `Progress` has no such mark; the rule text beside each meter says the same |
| Lane colours are PatternFly label colours | No hex in the page; each lane keeps one colour |
| Team DL can be edited | In the mockup it is a controlled field with no handler, so typing does nothing, which looks like a slip |
| The brand mark and avatar letter are gone | Both are decorative (`aria-hidden`) in the mockup |
| Light theme only, with no switch | As the mockup specifies |

## Run it

`npm install`, then `npm run dev`. `npm test` runs the model check, the style check, the type check, the build and the
parity test. The parity test needs `mockups/portal/dist/portal.html` and `npx playwright install chromium`.
