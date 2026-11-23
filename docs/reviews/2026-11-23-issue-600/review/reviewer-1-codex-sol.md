## PR #608 — source assessment supports the fix; runtime verification incomplete

Paths below are relative to `review-608/head/`.

| Question | Verdict and evidence |
|---|---|
| Is `aria-busy` the right condition? | **Confirmed for the placeholder-data case.** `src/api/hooks.ts:540` includes filters/cursor in the query key; line 547 uses `keepPreviousData`; line 90 maps `isPlaceholderData` to `refreshing`. `PoliciesTab.tsx:103` derives `busy`, and lines 199–203 pass both that marker and the displayed items to `DataTable`. `src/components/ui.tsx:304` renders `aria-busy={busy \|\| undefined}`. This matches [TanStack’s v5 pagination semantics](https://tanstack.com/query/latest/docs/framework/react/guides/paginated-queries). |
| Correct at every current helper call? | **Confirmed by source inspection.** All three calls target **Failing resources**: `tests/api/portal.test.mjs:3611`, `3617`, `3622`. That table receives `busy`. The helper would not provide this guarantee for **Clusters** or **Results by policy**, whose tables omit `busy` (`PoliciesTab.tsx:162`, `222`). |
| Can busy be absent before fetching starts? | **Refuted for the proposed query-render/fetch-start gap.** TanStack computes the optimistic result during render, before the effect that applies observer options; placeholder data already carries `isPlaceholderData=true`. See [`useBaseQuery`](https://raw.githubusercontent.com/TanStack/query/main/packages/react-query/src/useBaseQuery.ts), lines 97–102, and [`QueryObserver`](https://raw.githubusercontent.com/TanStack/query/main/packages/query-core/src/queryObserver.ts), lines 601–637. The updated policy heading and busy table therefore render together. The chip updates route state directly, without a fetch-start effect (`src/portal/route.ts:36–41`; `PoliciesTab.tsx:88–97`). **Qualification:** this is source reasoning, not a browser reproduction; the exact pinned 5.107.1 sources were unavailable at the attempted versioned URLs. |
| Does it time out clearly? | **Confirmed bounded; diagnostic wording unverified.** `fresh()` sets an 8,000 ms default timeout (`portal.test.mjs:48`); `settledRows` calls locator `waitFor()` at line 3551. Its selector names the table and excludes busy state. There is also a named 90-second check deadline at lines 147–171. I could not observe the actual Playwright timeout message. |
| Any other one-shot reads? | **Confirmed.** The Capacity focus/304 case reads `tableRows` once at `portal.test.mjs:4358`. Lines 4352–4357 establish server-side activity, not browser query completion. Because the expected rows remain identical, that assertion can pass before the browser processes the 304. Other one-shot helpers also exist: Requests at line 63, Quotas at 2144, Expiration at 2850. Their existence alone does not establish the same filter-change flake. |
| Are moving `sentPol` assertions justified? | **Confirmed.** They now follow settlement at lines 3617–3618 and 3622–3623. The stand-in records the request before delaying or holding its answer (`tests/api/standin.mjs:923–925`). |

No demonstrated defect in the changed helper warrants a fix.

**Verification limits:** Node dependency resolution returned:

```text
ERR_MODULE_NOT_FOUND playwright
ERR_MODULE_NOT_FOUND @tanstack/react-query
ERR_MODULE_NOT_FOUND @axe-core/playwright
```

I could not run the portal suite, reproduce the flake, or verify timeout diagnostics. I also did not finish reading all 5,146 lines of `portal.test.mjs` and all 1,396 lines of `standin.mjs`; therefore this is **not a completed full-file/exhaustive suite review** under your grounding requirement. The conclusions above are limited to the inspected code and cited evidence.

