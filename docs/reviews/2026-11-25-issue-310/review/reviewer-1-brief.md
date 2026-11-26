# Reviewer 1 brief: cmapi PR #707 (closes #310, part of story #22), usage verdicts and live usage. Two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you.

## The export

Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-707/`:
- `head/` is `8ceea45`;
- `base/` is main `3bd6581`;
- `pr.diff` has 10,367 lines, mostly the contract, samples and portal types.

The source change is 18 files under `cmapi/src` (+1426 −334), plus 2 portal files and migration 0010. Read `head/docs/reviews/2026-11-25-issue-310/README.md` in full. Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`. Edit only a copy (`r1-work/`).

## What it claims

The usage source is an interface:
- `PromUsage` runs docs/03's PromQL against Thanos, from `capacity/thanos.py`;
- `NoUsage` is the default (`capacity.yaml usage.source: none`).

With a source:
- the dry run of a quota change gets `usage`: now, 7-day average, p95, peak, and new quota over peak. It is cached 10 minutes;
- if Thanos does not answer, the change needs one more approval from approver-platform (docs/01). That rule was **added to every approval-rules.yaml**.

A daily job, `usage_sweep` (migration 0010), stores the verdicts `quota-tight`, `idle`, `quota-oversized`, `requests-oversized`, `right-sized` and `insufficient-data`. `GET /api/v1/quotas` adds the verdicts, the attention counts, a `verdict=` filter and severity level 1. Insufficient data is explicit: no source, under 80% of samples, NaN, or warnings.

On the portal's Quotas tab: the Verdict column, the chips, "{N} need attention", and the live-usage block.

## Do not reopen the design

docs/01, docs/02 and docs/03 on usage, verdicts, approvals and capacity. Recommendations are docs/03 phase 6, left out on purpose (#12, #703, #704, #705).

## Confirm or refute each point, with a test that decides it

1. **Security of the Thanos call:**
   - TLS is verified with the project's `trusted_context()`. It must never be off, and never `ssl.create_default_context()`: in the pods, `SSL_CERT_FILE` holds only Keycloak's CA.
   - The token used, and where it comes from. Is it least privilege, and is it never logged?
   - The PromQL is built with label values from user input (namespace or cluster). Can a caller inject PromQL? Prove it with a malicious namespace name or filter value.
   - Timeouts, and the response size bound.
2. **The approval rule.** "Thanos does not answer, so one more approval":
   - Is it added consistently, and can a caller make Thanos fail on purpose to change the outcome, in either direction?
   - Does a stale cache hide a failure?
   - Does it ever *remove* an approval that base required?
3. **The verdict rules,** at their boundaries, by docs/03. Check the 80% sample rule, NaN, and the "warnings count as failure" rule.
4. **Migration 0010:** up and down, from empty and from 0009 with data. The sweep's retention delete must be bounded and indexed. Is the job's locking the project's pattern, and safe with two workers?
5. **The `GET /api/v1/quotas` change:** one query, no N+1; the `verdict=` filter and the sort; the contract and oasdiff.
6. **The portal:** the states, including insufficient data, are rendered faithfully with no invented figures. Check the `MOCKUP-CONTRACT.md` differences.
7. **Tests can fail.** Run the new files on base and head, plus mutants: drop the 80% rule, treat NaN as 0, skip the extra approval, and inject PromQL.

## How to run

**Your sandbox may not reach PostgreSQL.** If so, say it at the top and limit database claims to reading. Do not substitute SQLite for migration or locking claims.

From a tree's `cmapi/`, service tests:

```
CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_707 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider
```

Core tests: `PYTHONPATH=src` with the same venv, `tests/core`. Portal: `cd cmapi-portal-ui && npm test`, if node is available.

## Severity and fixes

- Mark each finding High, Medium or Low.
- Every High or Medium finding, and every Low one inside the changed lines, needs its **full code fix and a test that fails before and passes after**. Check it applies to a fresh `head/` copy with `patch -p1 -F0`.
- Other Low findings go to Backlog.

Research first: quote the Prometheus HTTP API documentation (query and query_range, warnings), the Thanos querier documentation, and the design lines, each with its URL and the date you read it. No repository, GitHub or cluster changes. No secrets. End with a five-line summary.
