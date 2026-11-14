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

- **Settings.** `config.json` lies beside `index.html`. It gives `apiUrl`, `issuer`, `clientId`, `instance`, `displayName` and `environments`. `config.example.json` is a sample. With no valid `config.json`, the portal shows "The portal is not configured." and starts nothing.
- **Sign-in.** Authorization Code with PKCE (`S256`) through `oidc-client-ts` and `react-oidc-context` (`src/portal/auth.ts`). The tokens stay in the memory of the page. `docs/15-keycloak-integration.md` gives the flow and the sources.
- **Data.** `src/api/schema.generated.ts` holds the types of `cmapi/contract/openapi.json` (`npm run api:types`). `src/api/client.ts` is the one client. `src/api/hooks.ts` has one TanStack Query hook for each endpoint: `useMe` and `useRequests`.
- **Permissions.** A tab shows only when `GET /api/v1/me` gives its permission in `access.permissions`. The permission of each call comes from the OpenAPI document (`src/api/permissions.generated.ts`). The browser reads no role from the token.
- **On the API today:** the page frame and the Requests tab. Each other tab says "This tab is not on the API yet."

The states of the Requests tab:

| State | Cause | The page shows |
|---|---|---|
| Loading | No answer yet | "Loading requests…" as a status line, and a skeleton |
| Empty | 200 with no rows | The mockup's sentence |
| Forbidden | 403 | "You do not have permission to see requests." and the problem's `detail`. No action |
| Error | 5xx, or no answer from the network | "The requests did not load." with the problem's `detail`, and "Try again" |
| 401 | The token ended | Nothing: one renewal with the refresh token, then the same call. If Keycloak refuses, sign-in again |

### Where the portal's Requests tab differs from the mockup

| Difference | Why |
|---|---|
| "Where it is" shows the last event of the request and who made it | The mockup's step number comes from its sample scenarios. The API has events, and no step count |
| "Open at current step" is off, with one line that says why | The Workflow tab is not on the API yet |
| No "Replay a policy rejection" and no "Replay a wrong-instance request" | They open sample scenarios of the mockup |
| No instance buttons | The mockup says "Mockup only": each instance is its own deployment |
| "Sign out" in the page frame | A signed-in person needs it. The mockup has no session |
| The name and the roles in the page frame come from `GET /api/v1/me` | The mockup shows its sample person |
| A tab that the person has no permission for is not shown | `docs/02`: the portal shows only the actions that a person can take |
| Words for loading, forbidden and error | The mockup's model cannot wait and cannot fail, so it has no words for them |
| The address is `#requests?q=...&state=...` | One portal serves one instance, so the address has no instance |

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
source 28 ways, one at a time, and each must fail the suite.
