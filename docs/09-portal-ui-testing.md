# How the portal UI was tested

This records how the two portal UIs were tested on 2026-11-04, what was found, and what remains unproven. The method is
the `/test-ui` skill in diagram-kit (`skill/test-ui/SKILL.md`).

There are two UIs and two kinds of proof:

| UI | Must match | Proof |
|---|---|---|
| `mockups/portal/dist/portal.html` (standalone, dc-lite) | The Claude Design render of `Main.dc.html` | DOM and pixels, against the canvas runtime |
| `cmapi-portal-ui/` (React, TypeScript, Vite, PatternFly) | What the mockup says and does | Content and behaviour; PatternFly replaces the look, so never a pixel diff |

Browser: Google Chrome 156.0.8078.80 on macOS, with the windows visible, and Playwright's bundled Chromium.

**Set up first.** In each of `tests/portal/` and `cmapi-portal-ui/`, run `npm install`, then
`npx playwright install chromium`. `PW_CHANNEL=chrome PW_HEADED=1` runs a suite in the installed Chrome. The React test
reads `mockups/portal/dist/portal.html` and needs `npm run build` first.

## Standalone page

**The oracle.** The published Design artifact includes `dc-runtime.js`. Run locally beside a copy of `Main.dc.html`, it
is the real renderer. It is not stored in this repo. The copy of `Main.dc.html` in the artifact was byte-identical to the
repo's (`cmp`).

| Check | Command, in `tests/portal/` | Result |
|---|---|---|
| Logic with no browser | `node logic.test.mjs` | 8 passed |
| Scripted walks, standalone checks | `node interactions.test.mjs` | 180 steps, no console errors |
| Build guard, caret, bad hash | `node standalone.test.mjs` | Passed |
| Walks compared with the canvas runtime | `--source-dir <folder> --record <file>`, then `--compare <file>` | 180 of 180 steps match on DOM, focus and caret |
| Views compared with the canvas runtime | `node capture.mjs <dir> [<folder>]`, then `node diff.mjs` | 13 of 13 views: 0.000% different, DOM identical |

The 13 views are all nine tabs on nonprod, and Workflow and Quotas on staging and prod, at 1320 px.

The walks cover every scenario on every instance, including "AI agent onboards · rnd" (13 steps, ending in 403); paging
to the end and back; the letter jump; type-ahead, with focus and caret asserted on each key; each filter and sort; picking
a row and planning a change; a team name updating the namespace name; typing mid-field; switching tiers; approving;
rejecting with a required reason; extending and making permanent. The standalone checks cover the hash, the instance
bar, playback, no sideways scroll at 1100, 820 and 390 px on every tab, and running with Google Fonts blocked.

**Not proven: a match with claude.ai itself.** No reference screenshots of the claude.ai render were available, so
the comparison above is with the runtime run locally, not with the Design viewer around it. To finish it, save PNGs
named like the captures (`nonprod-workflow.png`) and run `node diff.mjs <reference-dir> <capture-dir>`.

The original `test-paging.js` and `test-roles.js` could not be found on this machine or in git history.
`logic.test.mjs` covers the same subjects but was written new, not ported.

## React app

| Check | Command, in `cmapi-portal-ui/` | Result |
|---|---|---|
| Generated model is current | `node scripts/extract-model.mjs --check` | Passed |
| App styles use tokens only | `node scripts/check-discipline.mjs` | Passed |
| Types and build | `tsc --noEmit`, `vite build` | Passed |
| Nothing missing from the page | `node tests/parity.test.mjs` | 98 states, 15,944 strings, 0 missing |
| Nothing invented by the page | The same test | 0 added |
| Layout at 1440, 820 and 390 px, all tabs | The same test | No sideways scroll, no leftover placeholders |
| Accessibility, axe at 1440 and 390 px | The same test | No serious or critical findings on each tab's first view |
| What text cannot show: native form limits, threshold ticks, meter values for screen readers, the open type-ahead with axe | `node tests/behaviour.test.mjs` | Passed |

The test drives the mockup and the page through the same steps and compares after each: all tabs on all instances,
every nonprod scenario to its end, then Quotas, New namespace, Approvals and Expiration actions. Each comparison checks
the strings, the count of every character, each table cell by cell, each status pill's colour, which choices are selected,
which buttons are disabled and each meter's value. A state the walk does not visit is not compared; `qPage.stale` has no
path a person can take, so it is the one template state never rendered here.

One failing mutation was not enough. A changed heading made the first version of this test fail, and I took that as proof.
An independent review then ran 16 mutants and 13 survived it: swapped columns, Fail showing Pass, every status pill the
wrong colour. After the comparison was extended, 14 of 16 are caught. The two left are a state no person can reach and a
region choice that changes nothing on screen. Four more mutants of my own were all caught: swapped columns, a wrong
count, validation turned off, and ticks removed.

**Not proven.** No API exists, so there are no contract tests, loading states or error states, and no sign-in to test.
See `cmapi-portal-ui/MOCKUP-CONTRACT.md`. Keyboard use relies on PatternFly and axe; no walk tabs through every
control. No CI runs these suites yet.

## The portal on the API: Workflow, New namespace and Approvals (#300)

Measured on 2026-11-16 on this Mac, against the built portal (`dist/`), a stand-in issuer and a stand-in API
(`cmapi-portal-ui/tests/api/standin.mjs`). Stage: built-mocked. It does not prove the deployed product.

| Check | Command, in `cmapi-portal-ui/` | Result |
|---|---|---|
| Everything | `npm test` | exit 0 in Chromium 156.0.8078.4 and with `PW_CHANNEL=chrome` in Chrome 157.0.8103.51; portal suite 23 checks, config cases 10 |
| Parity both ways, per tab | `tests/api/portal.test.mjs`, check "6 the Workflow, New namespace and Approvals tabs" | 15, 33 and 11 strings of the mockup's blocks found, in 4, 4 and 3 states; nothing shown that is not listed |
| Layout at 390, 820, 1440 px, both themes | the same suite, check "7 the Workflow, New namespace and Approvals tabs" | 18 views, no sideways scroll, no placeholder |
| axe at 390 and 1440 px, both themes | the same check | 12 scans, no serious or critical finding; the Approvals scan has the reason field open |
| Mutants | `npm run test:mutants` | 65 mutants (36 before, 29 new), 65 killed |
| New tests fail on main | each new check run alone with `CHECK=` on a build of main 0a805b0 | all 10 changed or new portal checks and both new config cases fail |

**Found while testing.** Chrome sends a POST again by itself when a reused connection closes with no answer. The
stand-in's lost-answer case had to hold until the test cleared it; the retry carried the same Idempotency-Key, so the API
answered with the first request. **Not proven here:** keyboard use beyond PatternFly and axe. The sign-in and the submit on
CRC are in the next section.

### Live on CRC (#300)

Measured on 2026-11-16 by OB1 run 13, on CRC, against main 130ff6c deployed by docs/13 steps 5 and 21 (images
`cmapi@sha256:4a0b0b34…` and `cmapi-portal@sha256:669cf3d2…`, both labelled `130ff6c98e`; `/api/v1/version` answered
`130ff6c98e`). Stage: deployed. Playwright drove Chromium 156.0.8078.4, and installed Chrome 157.0.8103.51 for the read-only
walks, at 1440 px in the light theme, through `https://cmapi.apps-crc.testing` with HTTPS errors not ignored. The browser
trusts the two CRC CAs from the login keychain, whose SHA-256 fingerprints equal `ingress-ca.pem` and `keycloak-ca.pem` of
docs/13 step 1. Each person signed in on Keycloak's own login form, with the password piped from Secret
`cmapi-ldap-test-users` to the script's stdin. Screenshots: `cmapi-portal-ui/screenshots/slice-2-crc/`.

| Check | Who | Result |
|---|---|---|
| New namespace, auto-approved | `cmapi.requester` | `cmapi-live-d`, small, team platform. The dry run showed four checks, the last "Approval dev-create · 0 of 0 (auto)", and the card "Auto-approved by baseline-rnd-namespace". Submit: one create POST, 202, `req-20261116-0002`, with one `Idempotency-Key` (a UUID). The Workflow tab opened on it and, reading every 5 s, showed `approved`, `pr_open`, `applied` and `synced`; it finished at step 10 of 10, `branch_deleted`, lead time 26 s |
| New namespace that needs a person | `cmapi.requester` | `cmapi-live-e`, large. The dry run showed "! Approval dev-create · 1 of approver-platform" and the card "1 approval in cmapi from approver-platform". Submit: 202, `req-20261116-0003`, `pending_approval` |
| Approvals | `cmapi.approver-platform` | The card for `req-20261116-0003`, "0 of 1 approvals", eligibility "Role cmapi-approver" and "Not the requester". Approve: "Approved · 1 of 1". The requester's open Workflow tab then showed `approved`, `pr_open`, `applied` and `synced` (04:16:45 to 04:17:05Z) |
| Requests, and "Open at current step" | `cmapi.requester` | Both requests listed with status, last event, approval and PR. The button opened `#workflow?request=<id>` at its last step |
| Tabs by permission | `cmapi.viewer` | Workflow, Quotas, Expiration, Requests, Policies, Capacity: no New namespace, no Approvals |
| Tabs by permission | `cmapi.noaccess` | Expiration, Policies, Capacity, each "This tab is not on the API yet."; the only API call was `GET /api/v1/me` |
| The cluster and Git | `oc`, `gh` | Both namespaces exist with `cmapi.net/managed=true` and both LimitRanges (`-limits-cpu`, `-limits-memory`) and the quota of the tier. PRs #8 and #9 on `cmapi-cluster-configs` are merged, five files each, commits by `cmapi-git-bot` with the five `Cmapi-` trailers, branches deleted |
| Same origin, CSP | every walk | Every request went to `cmapi.apps-crc.testing` or `keycloak.apps-crc.testing`; no CSP violation; no page error |
| Chrome | the read-only walks | The same tabs per person, a dry run of `cmapi-live-f` (auto-approved, not submitted), and the same Requests and Workflow views |

**Found on CRC.** PatternFly warns once per Workflow step on every render because `ProgressStep` has no `id` (#306). The
Workflow tab's scenario button keeps the status it was first read with while the page follows the request to `synced`
(#307). Bundled Chromium 156 warns on the `web-share` feature of the portal's `Permissions-Policy` header; Chrome 157 does
not. The Approvals callout says "Argo CD applies it", the mockup's sentence; CRC applies with the worker (delivery mode
`apply`, docs/13).

**Not proven on CRC.** Reject, a refused write, the 401 renewal, the 390 and 820 px widths, the dark theme and axe: these
ran built-mocked only (above). The first screenshots of `cmapi-live-d` stopped at the viewport, because the page frame
scrolls an inner element; the New namespace pictures in the folder are a dry run of the same large-tier form
(`cmapi-live-g`, never submitted), and the auto-approved plan is the Chrome dry run of `cmapi-live-f`, never submitted.

## The portal on the API: Quotas and KPIs (#301)

Measured on 2026-11-15 on this Mac, against the built portal (`dist/`), the stand-in issuer and the stand-in API
(`cmapi-portal-ui/tests/api/standin.mjs`). The stand-in now serves `GET /api/v1/quotas` (with the list engine of
`cmapi/src/cmapi/core/listquery.py`: filters, sorts, a keyset cursor bound to the filters, `startsWith`, letters and the
attention counts), `:suggest`, `:export`, `GET` and `PATCH .../namespaces/{ns}` (If-Match, Idempotency-Key, `change-pending`)
and `GET /api/v1/admin/kpi`, and a `cmapi.operator` user. Stage: built-mocked. It does not prove the deployed product.

| Check | Command, in `cmapi-portal-ui/` | Result |
|---|---|---|
| Everything | `npm test` | exit 0 in Chromium 156.0.8078.4; portal suite 39 checks (12 new, 1 changed) |
| The installed Chrome | `PW_CHANNEL=chrome npm test`, then the portal suite again | Chrome 157.0.8103.51: the first run failed one slice 2 check on a colour transition (#312); the portal suite run again passed 39 of 39, and the behaviour and parity suites passed |
| Parity both ways | check "6 the Quotas and KPIs tabs" | Quotas: 49 strings of the mockup's block found over 13 states (list, type-ahead with and without a match, applied search, export, the same size, custom, a plan, the 202, a lock, a stale cursor, empty); KPIs: 5 strings; nothing shown that is not listed |
| Layout at 390, 820, 1440 px, both themes | check "7 the Quotas and KPIs tabs" | 24 views (a planned change, the open type-ahead, the export, the KPIs), no sideways scroll, no placeholder |
| axe at 390 and 1440 px, both themes | the same check | 16 scans, no serious or critical finding |
| One write at a time | check "R6" | a double click and two submits in one task each sent 1 PATCH |
| Mutants | `npm run test:mutants` | 119 mutants (69 before, 50 new), 119 killed. The first run had 2 survivors: both were weak checks, fixed (below) |
| New tests fail on main | each new check run alone with `CHECK=` on a build of main 01a23fe with this branch's `portal.test.mjs` and `standin.mjs` | all 12 new checks fail (the Quotas and KPIs tabs say "This tab is not on the API yet."); the changed check 5 (an operator sees KPIs) passes on main, because main already gated the tab by `reports:read` |

**Found while testing.** The first parity check of the Quotas tab could not fail on an invented sentence: the letters of the
A–Z bar were "known" strings, and taking each letter out of a text left nothing. A mutant showed it; the letters are now
matched whole. A double click did not prove the hook's one-at-a-time guard either, because the page's own "sending" state
had already reached React; two submits in one task do. **Not proven here:** keyboard use beyond PatternFly and axe, and
the custom-size PATCH against the real service (the stand-in follows `cmapi/tests/service/test_custom_tier_change.py`). The
Quotas and KPIs tabs on CRC are in the next section.

### Quotas and KPIs live on CRC (#301)

Measured on 2026-11-16 by OB1 run 15, on CRC, against main 525ca27 deployed by docs/13 steps 5 and 21 (images
`cmapi@sha256:7f48c24b…` and `cmapi-portal@sha256:18c12140…`; `/api/v1/version` answered `525ca27725`). Stage: deployed.
docs/13 step 23 (`deploy/crc-proof.sh`, unmodified) printed "proof: all passed", and step 24 ended the watch with `rc=0`
(217 lines, no breach); keycloak-0 had 0 restarts before and after every step. The method is slice 2's (above): Playwright
at 1440 px in the light theme, through `https://cmapi.apps-crc.testing` with HTTPS errors not ignored, the two CRC CAs
trusted from the login keychain (fingerprints equal to docs/13 step 1's), each person signed in on Keycloak's own form with
the password piped from Secret `cmapi-ldap-test-users` to stdin. Every walk ran in bundled Chromium 156.0.8078.4 and in the
installed Chrome 157.0.8103.51. Screenshots: `cmapi-portal-ui/screenshots/slice-3-crc/`.

| Check | Who | Result |
|---|---|---|
| The list | `cmapi.requester` | `GET /api/v1/quotas?limit=50`: 5 rows, `cmapi-live-a` to `cmapi-live-e`, in the API's order; the pill "5 namespaces in scope · 0 near the limit" |
| Filters | `cmapi.requester` | Tier large: `?tier=large`, 1 row (`cmapi-live-e`), "1–1 of 1 (filtered from 5)". Tier small: 4 rows. Env dev: `?env=dev`, 5. "Show all matches" for `live-d`: `?q=live-d`, 1 row |
| Sort | `cmapi.requester` | "% used": `?sort=used`, "most used first"; "Needs attention": `?sort=severity`, "most urgent first"; the rows in the API's order each time |
| A–Z jump | `cmapi.requester` | One letter enabled, "C: 5 namespaces"; the other 25 are disabled. C sent `?startsWith=c` |
| Paging | `cmapi.requester` | Per page 25: `?limit=25`, Previous and Next disabled (the API gave no cursor). After a pick opened the page at `cmapi-live-e` ("5–5 of 5"), Previous sent the API's cursor and showed 1–4 of 5; Next came back to 5–5 of 5 |
| Type-ahead | `cmapi.requester` | One `GET /api/v1/quotas:suggest?q=live-e` for the typed text, none for fewer than 2 characters; the list showed "cmapi-live-e · CRC name contains". ArrowDown set `aria-activedescendant` to `q-opt-0`; Enter opened `#quotas?ns=CRC%2Fcmapi-live-e` with `?startsWith=cmapi-live-e` |
| Export | `cmapi.requester` | `GET /api/v1/quotas:export`: 200, `text/csv; charset=utf-8`. The callout "quotas-nonprod-2026-11-16.csv · 5 rows"; Download saved the file, 5 rows under the header, the same 5 names as the list (total 5), in both browsers |
| A quota change | `cmapi.requester` (`namespaces:write`) | `cmapi-live-e`, large to medium. The plan: `PATCH ...?dryRun=true` with `If-Match: "9e2464b935262b48"`, the ETag of `GET .../namespaces/cmapi-live-e`; 200, four checks, "No approval needed" (rule `dev-change`: 0 approvals for a change in dev). Submit: `PATCH` with the same `If-Match` and an `Idempotency-Key`, 202, `req-20261116-0004`. It reached `synced`, finished at step 10 of 10, `branch_deleted`; the row then read medium, 16 cores, 32 Gi, 100 pods |
| The same in Chrome | `cmapi.requester` | `cmapi-live-e`, medium back to large, `If-Match: "66941dd71597b020"`: 202 `req-20261116-0005`, `approved`, then `pr_open`, `applied` and `synced` on the page's 5 s reads (07:56:12 to 07:56:32Z); the row then read large |
| The cluster and Git | `oc`, `gh` | After `req-20261116-0004`, `oc get resourcequota -n cmapi-live-e`: `requests.cpu 0/16`, `requests.memory 0/32Gi`, `pods 0/100` (from 32, 64Gi and 200), field manager `cmapi-deliverer`; LimitRange max cpu 4, memory 8Gi; PR #10 on `cmapi-cluster-configs` merged, four files. After `req-20261116-0005`: 32, 64Gi, 200 again; PR #11 merged |
| If-Match | the browser, the API | The browser's PATCH requests carried it (above). The API's access log names the two PATCHes (200 and 202 Accepted) but logs no header, and the request's events do not record it |
| KPIs | `cmapi.operator` | `GET /api/v1/admin/kpi`: 200. One component, `cmapi-api`: "Memory 28% · 141 MiB of 512 MiB" (147677184 of 536870912 bytes), "Throttled 3.1% of periods (limit 1%)" (36 of 1167), so "watch". Database "Connections 10 of 60", "Pools 0 in use of 5", "Oldest transaction 0 s", "Size 8 MiB". Seven KPI cards with the API's values (for example "4.4 h", "83.3%", "16.7%") |
| "unavailable" | `cmapi.operator` | The API's only null was `database.walBytes`; the page read "WAL unavailable". CPU, Event-loop lag p99, Volume, Volume trend and Last backup read "unavailable", as the contract lists, because the API has no such figure |
| No KPIs tab | `cmapi.requester` | Tabs: Workflow, New namespace, Quotas, Expiration, Requests, Policies, Capacity; no call to `/api/v1/admin/kpi`. The API answers the requester 403 `forbidden`, "Missing permission reports:read" |
| Same origin, CSP | every walk | Every request went to `cmapi.apps-crc.testing` or `keycloak.apps-crc.testing`; no CSP violation; no page error |

**Found on CRC.** The 202 callout of a quota change says "Argo CD re-stamps the quota on CRC", the mockup's sentence; CRC
applies with the worker before the merge (delivery mode `apply`), as the request's events say. It is the same defect as the
Approvals and Workflow text, so it was added to #309. The Workflow tab still warns once per `ProgressStep` on each render
(#306: 42 warnings while one request was followed). The events of a request are stamped with the transaction's start, so
`applied` reads before `apply_started` (#294; it was so in run 13 too). Chromium 156 warns on `web-share` in the
`Permissions-Policy` header, as before.

**Not proven on CRC.** A change that needs a person (every change in dev needs 0 approvals), a custom size, a 409
`change-pending` lock on a row, a 412 or 428 on a stale ETag, the stale-cursor callout, Next on a list of more than one
page from the first page (5 namespaces fit one page at the smallest size, 25), the 390 and 820 px widths, the dark theme and
axe: these ran built-mocked only (above). The first Chromium change run stopped at the 202 callout on a script locator,
after the PATCH was sent; the request was followed in a second run, and its 202 picture is the Chrome one.

## The portal on the API: Expiration (#318)

Measured on 2026-11-16 on this Mac, against the built portal (`dist/`), the stand-in issuer and the stand-in API. The
stand-in now serves `GET /api/v1/expirations` (the states, filters, `urgency` sort, counts and keyset cursor of
`cmapi/src/cmapi/plugins/expiration/router.py`, counted from the recorded `today`) and `POST .../expiration:extend`, `:set`
and `:makePermanent` with their dry runs (If-Match, Idempotency-Key, `change-pending`, and the refusals of `rules.py`). The
fleet is 40 namespaces in dev and rnd over every state. Stage: built-mocked. It does not prove the deployed product.

| Check | Command, in `cmapi-portal-ui/` | Result |
|---|---|---|
| Everything | `npm test` | exit 0 in Chromium 156.0.8078.4; portal suite 49 checks (9 new: the review of #322 added check 17) |
| The installed Chrome | `PW_CHANNEL=chrome npm test` | Chrome 157.0.8103.79: the first run, beside the 17-minute service suite on the same Mac, timed out the existing check "7 the Quotas and KPIs tabs" at its 90 s limit; run again with the machine idle, exit 0, 48 of 48, and the behaviour and parity suites passed |
| Parity both ways | check "6 the Expiration tab" | 19 strings of the mockup's block found over 6 states (the list, make permanent planned and sent, a date set, empty, an instance where nothing expires); nothing shown that is not listed |
| Layout at 390, 820, 1440 px, both themes | check "7 the Expiration tab" | 18 views (a planned make permanent, the date field, the list), no sideways scroll, no placeholder |
| axe at 390 and 1440 px, both themes | the same check | 12 scans, no serious or critical finding |
| One write at a time | check "R7" | two submits in one task sent 1 POST |
| Mutants | `npm run test:mutants` | 140 mutants (119 before, 21 new), 140 killed, 0 survived. Of the first 20 new, 9 fail a direct assertion and 11 fail on a check's 8 s wait for text that the mutant removes. The review of #322 added the 21st (a role of another environment sees the expiry form), killed by check 17 |
| New tests fail on main | each new check run alone with `CHECK=` on a build of main b7149d2 with this branch's `portal.test.mjs`, `standin.mjs` and samples | all 8 new checks fail (the tab says "This tab is not on the API yet.") |

**Not proven here:** the tab against the real service and Keycloak (the live walk on CRC, extending `cmapi-live-a`, comes
after the review), and keyboard use beyond PatternFly and axe. The live walk is in the next section.

### Expiration live on CRC (#318)

Measured on 2026-11-17 by OB1 run 17, on CRC, against main 9ba33b2 deployed by docs/13 steps 5 and 21 (images
`cmapi@sha256:345c39a6…` and `cmapi-portal@sha256:45bd4d32…`; `/api/v1/version` answered `9ba33b2064`, where it answered
`525ca27725` before). Stage: deployed. Step 6 was not run: `oc diff` of `environment/` was empty. No migration: the
migrations folder did not change since 525ca27, and `alembic_version` read `0005`, the head, before and after. docs/13
step 23 (`deploy/crc-proof.sh`, unmodified) printed "proof: all passed", and step 24 ended the watch with `rc=0`.
keycloak-0 had 0 restarts before and after every step, and the api, worker, portal and db pods 0 restarts after the walk.
The method is slice 3's (above): Playwright through `https://cmapi.apps-crc.testing`, HTTPS errors not ignored,
`cmapi.requester` signed in on Keycloak's own form with the password piped from Secret `cmapi-ldap-test-users`, light theme.
The change ran in bundled Chromium 156.0.8078.4; the list ran in it and in the installed Chrome 157.0.8103.79.
Screenshots and the API's answers: `cmapi-portal-ui/screenshots/expiration-crc/`.

| Check | Who | Result |
|---|---|---|
| The API | `cmapi.requester`, curl with the token on stdin | `GET /api/v1/expirations?limit=50`: 200, 5 rows `cmapi-live-a` to `cmapi-live-e`, all dev, all `permanent`; `today` 2026-11-17; rules for dev 30 / 180 / [14, 7, 1] / 7 (`api-expirations-before.json`) |
| `:extend` on a permanent namespace | the same | `POST .../cmapi-live-a/expiration:extend?dryRun=true` `{"days":30}` with If-Match: 422 `expiration-not-set`, "The namespace is permanent; use :set" (`api-extend-live-a-422.json`). So the walk first used Set a date, the only action the tab offers a permanent namespace, then extended the date it set |
| The list | `cmapi.requester` | The tab opens on Needs action (`?limit=25&state=attention`, 0 rows); All shows the API's 5 rows in its order, "1–5 of 5 · most urgent first", Expires "never", State "Permanent 5". The same after the change in both browsers, with `cmapi-live-a` first. At 390 px the rows become cards and the page does not scroll sideways |
| The plan | `cmapi.requester` (`namespaces:write`) | Set a date, the default 2026-12-17 (today + 30). `POST .../expiration:set?dryRun=true` with `If-Match: "a191fbec7278f89c"`, the ETag of `GET .../namespaces/cmapi-live-a`: 200. The checks "Lifetime within 180 days · 32 days from creation (Nov 15)", "The plan writes cmapi.net/expires-at: 2026-12-17", and "No approval needed" (rule `dev-change`, 0 approvals) |
| Submit | `cmapi.requester` | `POST .../expiration:set` with the same If-Match and an Idempotency-Key: 202 `req-20261117-0001`, `approved` at once ("Approved at once; the bot PR updates cmapi.net/expires-at when CI passes"). No approval by a person: a change in dev needs none |
| To synced | the Workflow tab | On the page's reads: `approved` 04:55:43, `pr_open` 04:55:58, `applied` 04:56:03, `synced` 04:56:13Z; "finished at step 10 of 10: branch_deleted". The request's events: created 04:55:42.15, `pr_opened` #12 04:55:52, CI pass 04:55:54, `applied` 04:56:01, `merged` 2ec73449 and `synced` 04:56:02.83, `branch_deleted` 04:56:08Z |
| The row after | `cmapi.requester` | Dec 17, 30 days left, "32 of 180 d", Active; the API: `expiresAt` 2026-12-17, `graceEnds` 2026-12-24, facets active 1, permanent 4 (`api-expirations-after.json`). The form now offers Extend 7, 14 and 30 days and Make permanent |
| The cluster and Git | `oc`, `gh` | `oc get ns cmapi-live-a -o jsonpath='{.metadata.annotations.cmapi\.net/expires-at}'`: `2026-12-17` (it had none before), field manager `cmapi-deliverer`. PR #12 on `cmapi-cluster-configs` merged at 04:56:06Z: `namespace.yaml` +3 −1 (`cmapi.net/expiry: managed`, `cmapi.net/expires-at: '2026-12-17'`, the request id) |
| Extend from the tab | `cmapi.requester` | With the date set, the form offered Extend 7, 14 and 30 days and Make permanent. Extend 30 days: `POST .../expiration:extend?dryRun=true` with `If-Match: "4520db45a0c5d2f6"`: 200, "Extension within 30 days · +30 days, to Jan 16", "Lifetime within 180 days · 62 days from creation", "The plan writes cmapi.net/expires-at: 2027-01-16", "No approval needed". Submit: 202 `req-20261117-0002`, `approved`; on the page's reads `pr_open` 05:00:30, `applied` 05:00:35, `synced` 05:00:46Z. Events: created 05:00:20.37, `pr_opened` #13 05:00:25, CI pass 05:00:27, `merged` d752bcc2 and `synced` 05:00:35.84Z |
| Extend: the row, the cluster, Git | the tab, `oc`, `gh` | The row: Jan 16, 60 days left, "62 of 180 d", Active (`api-expirations-after-extend.json`: `expiresAt` 2027-01-16, `graceEnds` 2027-01-23). `oc get ns cmapi-live-a` annotation `cmapi.net/expires-at`: `2027-01-16`. PR #13 merged at 05:00:39Z: `expires-at` `'2026-12-17'` to `'2027-01-16'` and the request id |
| Same origin, CSP | every walk | Every request went to `cmapi.apps-crc.testing` or `keycloak.apps-crc.testing`; no CSP violation; no page error |

**Found on CRC.** At 390 px the State chips break their words ("Need s actio n 0"), and so does the Quotas New size
choice in the built-mocked pictures ("mediu m"): the shared `Choices` component shrinks its items instead of scrolling
them. The layout check cannot see it, as nothing scrolls sideways (#324). The Workflow tab warned 44 times on
`ProgressStep` while one request was followed (#306). Chromium 156 warns on `web-share`, as before. The events are
stamped with the transaction's start, so `applied` (04:56:01.13) reads before `apply_started` (04:56:02.70) (#294). After each
change, the picture taken after `synced` and after the page read the namespace again still shows the ETag from before the
change: `a191fbec7278f89c` after the set (the API served `4520db45a0c5d2f6` later), `4520db45a0c5d2f6` after the extend
(the API served `28feaca300c6d77a` at 05:01:09Z). This run does not show whether the API's Git read or the page's cache
held the old value (#325). The form reads the namespace again on a 412, which this run did not test.

**Not proven on CRC.** Make permanent and its approver-platform approval, a refusal shown on the page, the grace
and pending-delete states, the 820 px width, the dark theme and axe: these ran built-mocked only (above).

## The New namespace form from the instance's metadata config (#336)

Measured on 2026-11-17 on this Mac, against the built portal (`dist/`), the stand-in issuer and the stand-in API, which now
serves `GET /api/v1/metadata-keys` (the recorded answer of the reference file, or the company file's answer in
`tests/api/metadata-keys.company.json`) with a strong ETag, `private, no-cache` and `304`, and refuses a create that leaves
out a required key of the served rules in the shape of the recorded `policy-violation`. Stage: built-mocked. It does not
prove the deployed product. The local runs were filtered with `CHECK=` to the New namespace checks; CI runs the whole suite.

| Check | Command, in `cmapi-portal-ui/` | Result |
|---|---|---|
| The form never refuses what cmapi accepts | `node tests/api/direct.test.mjs` (M1) on `tests/api/metadata-corpus.json` | reference: 1,315 cases, 96 accepted by `validate()`, 0 refused by the form, 3 let through (an empty optional key, which the form does not send); company: 1,654 cases, 170 accepted, 0 refused by the form, 2 let through (the same) |
| Each keyword of the answer is read or listed as ignored | `node tests/contract.test.mjs` | passes on both answers; fails with `x-cmapi-format` taken out of the list (mutant) |
| The company form | check "18 New namespace on a company instance" | the mnemonic, lob and cl inputs (cl a select of 0 to 6), `name` and `company.net/app-environment` read-only, no `cmapi.net/protected`; `ABC`, `amg sst` and `xyz-dev` refused in the validator's words with nothing sent; the dry-run body is the requester's three labels and the URL that `type=url` would refuse |
| The reference form | check "18 New namespace on the reference instance" | "Team (required)" and "Team DL (required)" with the mockup's hints from the file; "Optional labels (3)" collapsed; the second opening sends `If-None-Match` with the tag (Chromium 156 revalidates; the stand-in answers 304) |
| A refusal on its fields | check "18 New namespace: a refused dry run's errors" | the team error under its field with `aria-invalid`; the three errors in the callout, which takes the focus; its link focuses the field; a missing key the form does not show reads the rules again |
| A pattern that backtracks | check "18 New namespace: a configured pattern that backtracks" | `^(?:[a-z0-9]+-?)*[a-z0-9]$` on 41 characters: the page answers in under 1 s and a field takes keys; no error shown; the dry run's refusal is under the field |
| Rules that change while the form is open | check "18 New namespace: rules that change" | after a window focus: the warning, Team DL gone, a new required key empty and required, Team keeps its value, the body has no removed key |
| States | check "18 New namespace states with the rules" | a 403 of the rules: the forbidden state; a 5xx: "The form did not load." and Try again; `labels: []`: the error state with "not in the form this portal reads", no form; a role limited to rnd gets the form |
| Existing New namespace checks | checks 6 (parity), 9, R1, R2, R3 | pass; check 6 lists the API's words and the two sections, and splits the mockup's Team DL hint (MOCKUP-CONTRACT.md) |
| Layout at 390, 820, 1440 px, both themes, and axe | check "7 the Workflow, New namespace and Approvals tabs" with a fourth view, the company form with an error shown | 4 tabs, 24 views, no sideways scroll; 16 axe scans, no serious or critical finding |
| The placeholder's contrast, which axe does not measure | `docs/reviews/2026-11-17-issue-336/evidence/screens.mjs` | light `rgb(77, 77, 77)` on white, 8.45:1; dark `rgb(199, 199, 199)` on `rgb(56, 56, 56)`, 6.94:1 (`placeholder.log`) |
| Mutants | `node tests/api/mutants.mjs "#336"` | 26 new mutants (a field dropped, a pattern, the label syntax, the prefix, an enum, UTF-16 lengths, patterns on the page's thread, no time limit, the errors dropped or not on their fields, no re-read, the summary's focus and link, a derived key sent or editable, an empty optional key sent, an operator-only key offered, `type=url`, the example as the value, the titles, the warning, no re-read on focus, the 403 state, another shape read, a keyword not listed): 26 killed, 0 survived (`mutants-336.log`) |
| New tests fail on main | each new check with `CHECK=`, and the direct and contract tests, on a build of main c7ab6c4 with this branch's tests, stand-in and samples | the 6 new checks and checks 6 and 9 fail; direct M1 to M6 and the contract test fail (no `metadataForm.ts`) (`before-portal.log`) |

Screenshots of the whole form for both files, at 390, 820 and 1440 px in each theme:
`docs/reviews/2026-11-17-issue-336/screenshots/`.

**Not proven here:** the form against the real service and Keycloak (the route itself is proven by the service tests, on
the reference and company files, with `policy.engine: none`), the installed Chrome, and the company file on CRC (CRC runs
the reference file and is shared). Whether a browser other than Chromium 156 revalidates the answer is not measured; the
form does not depend on it.

## Protection from deletion (#366)

Measured on 2026-11-17 on this Mac, against the built portal (`dist/`), the stand-in issuer and the stand-in API. The stand-in
now answers `operator` and `operatorEnvironments` on `GET /api/v1/me` (an operator holds `namespaces:protect`; a new user,
`rnd.operator`, holds it in rnd only), `protected` and `protectedBy` on `GET .../namespaces/{ns}`, refuses a protection label
from a caller who is not an operator (403) and a value other than `"true"` (422 `invalid_value`), and plans a removal with
the approval that the service measured (`threshold sensitiveKeyChanged: +1 approver-platform`). Stage: built-mocked. It
does not prove the deployed product.

| Check | Command, in `cmapi-portal-ui/` | Result |
|---|---|---|
| The badge and its sentence, to everyone; the control to an operator only | check "19 Protection: everyone" | viewer, requester and operator see "Protected" and "cmapi refuses a delete request for this namespace (422 namespace-protected): cmapi.net/protected=true, do-not-delete=true."; only the operator has "Remove protection"; an unprotected namespace has no badge and "Protect from deletion" |
| The protect dialog | check "19 Protection: the operator's dialog" | the dry run's body is `{"labels":{"cmapi.net/protected":"true"}}` with If-Match and no key; a lost answer, then Submit again: the same key, one request made; the 202 is a status message; "Open at current step" opens the Workflow tab |
| An operator in rnd only | check "19 Protection: an operator limited to rnd" | no control on a dev namespace, the control on an rnd one; no create box in dev, the box in rnd |
| The remove dialog | check "19 Protection: removing it" | the body is `null`, never `"false"`; "1 approval in cmapi from approver-platform"; "Still protected by do-not-delete=true"; Cancel writes nothing and the focus returns to the button |
| A 412 and a 403 | check "19 Protection: a 412" | the stale ETag once, then the namespace's new one, with no 412 callout; a 403 shows "403 forbidden · nothing written" and reads `/me` again |
| The create box | check "19 New namespace" | absent for a requester; for an operator, unchecked sends no protection key, checked sends `"cmapi.net/protected": "true"` in the dry run and in the submit |
| Layout and axe | check "19 Protection at 390 and 1440 px" | the detail, the open dialog and the create box at 390 and 1440 px in each theme: no sideways scroll; axe on the page and on the dialog, no serious or critical finding. Screenshots: `docs/reviews/2026-11-17-issue-366/screenshots/` |
| The installed Chrome | `CHECK=19 PW_CHANNEL=chrome node tests/api/portal.test.mjs` | 7 checks pass in Chrome 157.0.8103.79 (`evidence/portal-19-chrome.log`) |
| The whole portal suite | `npm test` | 62 checks pass in Chromium 156, then the behaviour and parity tests: 98 states, 0 with a missing string (the run before the last three checks were added) |
| New checks fail on main | each check with `CHECK=`, on a build of main 7ba5d78 with this branch's tests and stand-in | the six checks that existed then each fail (`evidence/portal-19-before.log`) |
| Mutants | `node tests/api/mutants.mjs "<name>"` for each new one | 11 new mutants (the control or the box for everyone, an operator somewhere counted everywhere, the badge from the labels, `"false"` for a removal, a second key in the body, no key kept across a retry, no re-read on a 412 or a 403, no note of what still protects, the box sending the label unchecked) and the four whose text moved: 15 killed. The first run had one survivor, "an operator somewhere is an operator everywhere": the detail also needs `namespaces:write` in the environment, so the check now tests the create box in dev and rnd (`evidence/portal-mutants-366.log`) |

**Not proven here:** the controls against the real service and Keycloak (the service suite proves the API side with
`policy.engine: none`, `tests/service/test_protected_366.py`), and the walk on CRC.

## The portal on the API: Policies (#302)

Measured on 2026-11-17 on this Mac, against the built portal (`dist/`), the stand-in issuer and the stand-in API. The
stand-in now serves `GET /api/v1/policies/results` (the recorded answer, and a fleet built from it: CRC with 30 fail, warn
and error rows, and one cluster in each other state: off the bundle, unreachable, Kyverno not installed, no access, capped,
stale with mode enforce; the keyset cursor bound to `clusterId`, `policy` and `result`; the counts of `policies` following
`clusterId`) and `GET /api/v1/policies/rejections` (a plan refusal with Kyverno's warning, a warned plan, a CI refusal;
`since` from 1d to 90d). Stage: built-mocked. It does not prove the deployed product.

| Check | Command, in `cmapi-portal-ui/` | Result |
|---|---|---|
| Everything | `npm test` | exit 0 in Chromium 156.0.8078.4: the portal suite 68 checks (5 new), then the behaviour and parity suites: 98 states, 0 with a missing string |
| The installed Chrome | `CHECK=<name> PW_CHANNEL=chrome node tests/api/portal.test.mjs` for each Policies check | the 5 Policies checks pass in Chrome 157.0.8103.79 (`docs/reviews/2026-11-17-issue-302-policies/evidence/portal-chrome.log`) |
| The clusters, the policies and the rows, cell by cell | check "20 Policies: the clusters" | each cluster's 10 cells, `—` (never 0) for the 3 clusters whose counts are unknown, each state's tone; the lede's pinned version and modes; the head's pill; 31 policies from the API with what each checks; 25 rows then 5, by namespace, Previous back to 25; a chip sends `clusterId`, Show failures sends `policy`, each in the address |
| The refusals | check "20 Policies: the refusals" | the stage ("plan (422)", "plan, warned", "CI"), the policy or check and its rule, Kyverno's warning beside cmapi's error, "(2 times that day)", the username; no `@`, employee ID or justification in the panel |
| States | check "21 Policies states" | loading, empty, a 403 with no action, a 5xx and Try again, a stale cursor and "Back to the first page", the refusals' 403 in their panel only (the results stay), and `policy.engine: none` (the callout and the refusals only) |
| Parity both ways | check "6 the Policies tab" | 31 strings of the mockup's block found over 3 states; nothing shown that is not listed (MOCKUP-CONTRACT.md); the mockup's clusters footnote is the one string listed as mockup only |
| Layout at 390, 820, 1440 px, both themes | check "7 the Policies tab" | 12 views (the tab, and a cluster and a policy chosen), no sideways scroll, no placeholder. Screenshots: `docs/reviews/2026-11-17-issue-302-policies/screenshots/` |
| axe at 390 and 1440 px, both themes | the same check | 8 scans, no serious or critical finding |
| Mutants | `node tests/api/mutants.mjs "<name>"` for each new one | 16 new mutants, 16 killed (`docs/reviews/2026-11-17-issue-302-policies/evidence/mutants.log`). The first run had two survivors: "the hidden counts are dropped" changed nothing (`Small` takes no `hidden`), replaced by "the hidden counts are not summed"; "a changed Policies heading" survived the string comparison, which finds "Policies" in other text, so check 6 now reads the `h1` by role |
| New checks fail on main | each Policies check with `CHECK=`, on a build of main abad314 with this branch's tests, stand-in and samples | all 5 fail: the tab says "This tab is not on the API yet.", so no Clusters table and no loading line appear within the 8 s wait (`evidence/portal-before.log`) |

**Not proven here:** the tab against the real service and Keycloak, and the walk on CRC (the coordinator deploys). The
service side ran against a real cluster: `docs/reviews/2026-11-17-issue-302-policies/evidence/kind/` (kind, Kyverno
v1.20.0 in audit, the reader of `deploy/manifests/environments/crc/reader/`).

## What testing found

| Found by | Problem | Fix |
|---|---|---|
| Identical DOM with different pixels | The artboard sat at y = 32.1875 because the bar's height was fractional, moving up to 1.4% of pixels | A whole-pixel bar height |
| Step-by-step comparison | React mirrors a textarea's value into its text child | The runtime does too |
| Reading the source in full | An invented Workflow intro, a "Share" column and placement headings | Replaced with the file's content |
| Reverse content check, added after that | A check for missing strings cannot see invented ones | The test now fails on both |
| Layout run at 820 px | PatternFly's overflow mode folded a tab into a menu | Scrolling tabs |
| Axe | A long token made a KPI card a scrollable region no keyboard could reach | Text wraps inside cards |
| Installed Chrome | `/favicon.ico` 404 reported as a console error; a dev server hid it | An inline icon |
| Independent review | 17 defects the suites had passed, including forms submitting what the mockup refuses and a footnote about a tick that did not exist | See `docs/reviews/2026-11-05-portal-ui.md` |

Mockup behaviour worth a decision, left unchanged in `Main.dc.html`: the Team DL field has a value and no handler, so typing
in it does nothing. The React app makes it editable.

"Use this size" on a custom recommendation was fixed in `Main.dc.html` on 2026-11-05 (`tests/portal/recommendation.test.mjs`).
