# Review of #384: OB3 (Opus 5.5), and the coordinator's rulings

OB3 reviewed head da7cfbb on an export (`git archive`, byte-identical). Opus wrote and designed the change, so the review
is from the same model family. OB3's fixes were applied unchanged as one patch.

## Claims

| Claim | Verdict | Evidence |
|---|---|---|
| C1: no leaks; rejections hold the username only | Confirmed | Scoped by `objects:read`, managed namespaces and bundle policies (`plugins/policies/router.py`); `env IN (allowed)` in SQL (`core/rejections.py`); no email, employee ID or justification column; log events and metric labels carry no username |
| C2: no unknown count shown as 0 | **Refuted: F1** | Per-policy counts came back 0 with nothing known; the tab said "0 failing" |
| C3: audit vs enforce from the configuration and the live spec, drift flagged | Confirmed (code read) | |
| C4: one row per refusal per day, paging, retention, migration 0006 | Confirmed | 16 concurrent `record()` calls gave one row with count 16; migrations up, down, up passed |
| C5: a bundle change is detected | Confirmed | A changed `cmapi.net/policy-digest` shows as drift. Not detectable: results Kyverno has not yet re-evaluated after a delivery |
| C6: bounded memory, 410 handled, no per-request fan-out | **Refuted on memory: F2**; the rest confirmed | |
| C7: what CRC shows now Kyverno is installed | Plausible; one premise checked by the coordinator | CRC serves `wgpolicyk8s.io/v1alpha2` `policyreports` and `clusterpolicyreports` (`oc api-resources`, 2026-11-17). With no cmapi policy delivered, the tab shows drift, "31 missing" (after F3), and null counts (after F1). docs/13 updated |

## Findings, all accepted

| # | Severity | Finding | Fix |
|---|---|---|---|
| F1 | Medium | Unknown per-policy counts returned and shown as 0, against "never a zero" | `PolicySummary.counts` nullable; counted only where the policy is live and its cluster known; the tab shows "—" |
| F2 | Medium | A chunked list held every raw report until the last page: peak 275.78 MiB vs 55.4 MiB retained at 8,000 reports | Each page reduced before the next; the cap moved to an `admit` hook. Peak 70.54 MiB |
| F3 | Low-Medium | Drift text counted name lists capped at 20 ("20 missing" for 31) | Totals, and `actionsDifferTotal` |
| F4 | Low | `cmapi_policy_reports_state` declared, never set | Removed |

## The coordinator's check

Arbiter run on 2026-11-17: OB3's test files placed on the head code, then the patched copy, through `suite.sh`.

- Head: 6 failed (the 6 new tests), each on its assertion, for example `'20 missing, …' == '31 missing, …'` and 31 policies
  of zeros where `{}` was expected.
- Fix: `test_policies_302.py` and `test_policy_reports_unit_302.py`, 40 passed.
- The portal checks and mutants run in CI (`portal-ui`).

## Not checked

The full service suite and `npm test` locally (CI runs both); CRC itself (the PR is not deployed); whether Kyverno labels a
report with the policy version it used; CPU per request at scale.

#385 (a migration test that called 0004 "a later release") stays fixed in this PR, since CI cannot pass without it.
