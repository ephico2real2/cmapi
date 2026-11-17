# #302 Policies: the arbitration of two designs

- **Design A** (`design-policies-a.md`): a general-purpose Opus 5.5 agent.
- **Design B** (`design-policies-b.md`): OB3, a separate Opus 5.5 agent.

One model family (Codex out of quota until 2026-11-18 14:09; Fable paused). Written apart, both on origin/main abad314.

## The owner's decisions

- From #302 (2026-11-17): Kyverno in audit by default; the tab shows the clusters' PolicyReport results, Kyverno's plan-time
  warnings beside cmapi's refusals, the engine, each environment's mode and the pinned Kyverno version; with engine none
  the tab says Kyverno is off; no hard-coded policy list.
- 2026-11-17: a stored refusal shows **the username only** — never the email, the employee ID or the justification —
  to anyone who can read that environment, as the Requests tab shows who asked.

## Where the designs agree (adopted)

| Point | Both |
|---|---|
| Source | `wgpolicyk8s.io/v1alpha2` PolicyReports, watched per cluster beside the existing cache, kept slimmed; no live call to a cluster per request |
| Never a zero for missing data | Each cluster has a named state (not installed, forbidden, unreachable, stale, engine off, capped); its counts are `null` then, never 0 |
| No policy list in the portal | A policy's kind, key and rule come from the report and the rendered `index.json` |
| Refusals stored | Nothing stores plan-time refusals today (the mockup itself says "metric only, no row"). A new table `policy_rejections`, migration 0006. A failed write never changes the 422 |
| Drift | A digest annotation on each rendered policy (there is no bundle tag today) |
| RBAC | The cluster reader gains read on PolicyReports (CRC has none today) |
| CRC | Kyverno is not installed there: the tab must say so; the CRC proof checks that |

## Rulings where they differ

| Point | A | B | Ruling |
|---|---|---|---|
| "Not installed" | From API discovery: measured on CRC, discovery answers 404 while a list answers 403 | Counts null | **A's detection, B's null counts.** Reading the list error would show CRC as "forbidden" |
| What a caller sees | — | Only environments where the caller holds `objects:read`, namespaces cmapi manages, policies in the bundle and live; everything else as hidden counts | **B** |
| Audit or enforce | The mode from the integrations endpoint | The configured mode beside each policy's live `validationActions`; a mismatch is a `drift` state; never inferred from fail or warn (Kyverno turns an unscored fail into warn) | **B.** B also found that the contract has no `Policy` schema despite the #302 comment: add it |
| Rejection rows | One row per finding, 90 days | One row per refusal per day, ordered by first seen (stable pages); request id null for a plan refusal, a foreign key otherwise; Kyverno plan-time warnings as `warned` rows with the request id; dry runs only in a metric; no justification, email or employee ID | **B**, plus the owner's username column |
| Retention | Constant or config | — | **A config key** with 90 days as the default (one place to change it per instance) |
| Digest annotation name | `cmapi.net/policy-digest` | `cmapi.net/bundle-digest` | **`cmapi.net/policy-digest`**: it is per policy |
| Kyverno's `rule` | — | Dropped today (`core/validate/__init__.py:210`) | **Keep it**, with a test |
| cmapi's refusal metric | — | Refusals raised before the only `cmapi_validation_failures_total` increment (`pipeline.py:285-292`), so not counted | **Fix** with a test |

## Deferred (each its own issue)

- Reading `openreports.io` reports (the newer API group).
- The breaker's dropped count from Thanos (shown as "not measured" until then).
