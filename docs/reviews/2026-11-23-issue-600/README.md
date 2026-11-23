# #600: check "20 Policies" waits for the filtered rows

The implementer's record: Opus 5.5 at `high`, 2026-11-23, on `fix/600-policies-flake` from `e5ac180`. The reviews go
beside it when they are done.

## The defect

CI run 45197095820 (PR #599, head `547fea3`), job `portal-ui`: `not ok - 20 Policies…`, `AssertionError … at
portal.test.mjs:3615:12`, with the unfiltered CRC rows as the actual value. After **Show failures** the check waited for
the heading `Failing, warning and erroring resources · <policy> · CRC` and read the table at once. The heading comes from
the page's filter state; the rows come from `usePolicyResults`, whose query has `placeholderData: keepPreviousData`
(`cmapi-portal-ui/src/api/hooks.ts`). Until the filtered answer arrives the table holds the last answer's rows.

## The page is right; the check read too early

The page already marks those rows. `PoliciesTab.tsx` passes `busy = result.state === "ok" && result.refreshing` to the
table, `refreshing` is the query's `isPlaceholderData` (`resultOf`, `hooks.ts`), and `DataTable` renders it as
`aria-busy` (`components/ui.tsx`; WAI-ARIA 1.2: the element is being updated). Check "407 Policies results keep both
cursors off while a cluster loads" already proves the busy marker while a held answer loads. So the fix is in the check.

Sources, fetched 2026-11-23:

- TanStack Query, "Paginated / Lagged Queries" (`docs/framework/react/guides/paginated-queries.md`, `TanStack/query`
  branch `main`): with `keepPreviousData`, "The data from the last successful fetch is available while new data is being
  requested, even though the query key has changed", and "`isPlaceholderData` is made available to know what data the
  query is currently providing you".
- TanStack Query 5.107.1, the version the portal pins, `query-core/build/modern/queryObserver.js`, `createResult`: for a
  new key with no data and `placeholderData` set, the result in the same render has `status = "success"`, the previous
  data, and `isPlaceholderData = true`. `react-query/build/modern/useBaseQuery.js` calls `observer.getOptimisticResult`
  during render. So the render that shows the new heading already marks the old rows busy, and a wait for a table that is
  not busy cannot pass on the old rows.

| Option | Why not, or why |
|---|---|
| **Wait for `table[aria-label="Failing resources"]:not([aria-busy="true"])`, then read** | Chosen. It waits for the state the page itself exposes for "the answer of these filters is in", with Playwright's auto-waiting locator, and keeps the exact comparison |
| Poll `tableRows` until it deep-equals the expected rows | Works, but waits for the answer rather than for the page's state, and a wrong answer only shows as a timeout |
| A sleep | Hides the race on a fast machine and not on a slow one |

`settledRows` (in `tests/api/portal.test.mjs`, beside `tableRows`) is used for the three reads after a change in the
check: after **Next ›**, after the CRC chip, after **Show failures**. The two `sentPol` checks now follow the settled
table, because the stand-in records a call when it arrives (`standin.mjs`, `state.seen.push` before any delay): once the
answer is in, the call was sent. Before, they ran right after the heading or the address changed, which an effect's fetch
may not have reached yet (inferred, not seen in CI).

## Proof

A delay injection (`workbench/cmapi/wt-600-outputs/inject-600.py`): a copy of the suite where the stand-in holds every
`/api/v1/policies/results` call with `policy` for 500 ms, from the Show failures click on. `CHECK="20 Policies: the
clusters"`, chromium 156, on this machine:

| Copy | Runs | Result |
|---|---|---|
| main's check (`e5ac180`) with the injection | 3 | 3 fail at the Show failures read (line 3616 in the copy, 3615 in the file), actual the unfiltered rows (`accounts-api-dev`, …): CI's failure |
| the fixed check with the injection | 3 | 3 pass |
| the fixed check, no injection | 3 | 3 pass |
| `npm test` in `cmapi-portal-ui/` | 2 | both exit 0; `portal on the API: 139 checks` |

Not changed: other checks' reads. Each other `tableRows` read in the file follows a first load, not a change of filters or
page.
