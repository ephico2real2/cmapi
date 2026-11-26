# #696: a submit holds one pooled connection at a time

PR #700.
- **Fix:** written by reviewer 2 of #695 (Opus 5.5 high), from its PostgreSQL measurement. Applied by the coordinator.
- **Reviewer 1:** Codex gpt-6.2-astra xhigh. Its sandbox could not reach PostgreSQL, so it reviewed by reading the code.
- **Reviewer 2:** Opus 5.5 high, on PostgreSQL 16.

## The measurement

- **Main:** twelve creates at once filled the pool (5 + 5, peak 10), and some answered 500 with "QueuePool limit … timeout 30.00", in 6 of 6 runs.
- **With the fix:** one connection per create, and all twelve answered 202.

## Rulings

| Finding | Ruling |
|---|---|
| Codex: the revert job opens a second session under the row lock | **Fixed (Low).** Measured: 2 checkouts while the row is locked. The worker can't starve, since it runs one handler at a time with a pool of 10. It is the last caller that broke the rule "read the switch in the caller's transaction", so the one-line fix lands here, with a real PostgreSQL worker test. |
| Codex: the concurrent test may not fill the pool | **Not observed** (6 of 6 base failures). Codex's barrier is kept, and the test now asserts `pool.checkedout()` reached 10. |
| Codex: "every route waited" is too broad | **Accepted.** `/version` makes no database call; `/readyz` does. The docstring is corrected. |
| Codex: kill-switch visibility under READ COMMITTED | **Confirmed.** PostgreSQL 16 §13.2.1. The test is kept. |
| Reviewer 2, R2-1: `Session.get` may return a cached switch row | **Fixed (Low).** `SwitchRepo.value` always queries. Its test fails on head and passes with the fix. |

No other path opens a second session while holding a lock. Reviewer 2 searched approvals, `team_request`, replay, planning, JWKS, KPIs and expiry.

**The coordinator's run (2026-11-26).** Pool starvation, rate limits, flow, dry-run and client-input tests: **78 passed**. CI is the full-suite gate.
