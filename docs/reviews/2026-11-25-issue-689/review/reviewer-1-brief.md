# Reviewer 1 brief: cmapi PR #695 (closes #689 and #694), rate limits. Security, two reviewers.

You are reviewer 1, from the Codex model family, adversarial. You did not write this change. Opus 5.5 high wrote it.
After you, reviewer 2 (Opus) checks your fixes.

## The export

Work only in this folder, `/Users/olasumbo/gitRepos/workbench/cmapi/review-695/`:
- `head/` is the PR head `d692adc`;
- `base/` is main `cf1c0f4`;
- `pr.diff` is 6032 lines, mostly the regenerated contract.

The source change is 9 files under `cmapi/src` (+272 −57):
- `cmapi/src/cmapi/core/ratelimit.py`;
- `cmapi/src/cmapi/routers/__init__.py` (`rate_limit`, the dependency);
- `_submit` in the pipeline (the team bucket);
- the config check;
- `problem_response` (#694: `Retry-After` on 503s that carry `retryAfter`);
- `main.py` wiring.

Read `head/docs/reviews/2026-11-25-issue-689/README.md` in full: the design, its choices and its sources.

Write your report to `r1-report.md`. Put your fix, as one `fix.diff` against `head/` built from the repository root, and your runs in `r1-outputs/`. Make your own copy for edits (`r1-work/`). Never edit `head/` or `base/`.

## The design it must match (do not reopen it)

docs/01 "Operational safety": "Token buckets per caller and per team, separate for writes, :place, :suggest and :export". docs/02 has the row "Rate limits". The answer is 429 `rate-limited` with `Retry-After`.

## Confirm or refute each point, with a test that decides it

1. **Coverage.** Every route that takes a token is limited, exactly once per request, from exactly one caller bucket. Check the route-template-to-class mapping for every operation in `head/cmapi/contract/openapi.json`: none missed, none double-charged, including `HEAD` (answered by the `GET` route) and the `:action` routes. Unauthenticated routes are not limited.
2. **Order.** The 429 comes after authentication and before body validation. Does FastAPI 0.162.2 decode JSON before dependencies (the README says yes, with a measured 0.030 s)? Is a 401 still a 401, not a 429, for a bad token? Can an unauthenticated flood still cost CPU, and is that #683's limit's job?
3. **Team bucket.** In `_submit`, after the plan:
   - Is the team taken from a trusted place, or can the caller choose it in the body to drain another team's bucket, or to escape their own?
   - What happens to a token taken when the request later fails, or is an idempotent replay?
   - Is the 429 raised before any write to the database or Git?
4. **Concurrency and memory.**
   - Is the bucket update safe under asyncio, and under threads if any handler runs in a threadpool?
   - Is the number of buckets bounded? An attacker with many `sub`s or many teams must not grow memory without limit. Look for eviction.
5. **Clock.** Monotonic or wall clock? Refill maths, `Retry-After` rounding (RFC 9110 §10.2.3 needs a non-negative integer of seconds), and `retryAfter` equal to it.
6. **Config.** The `http.rateLimits` validation at start and the Helm schema agree, with bounds like #683's (2^53−1). Safe defaults. And `core/config.py` must still import without structlog or prometheus_client: run `head/cmapi/tests/core/test_config_import_693.py`.
7. **#694.** `Retry-After` on a 503 that carries `retryAfter`. Is it right for every problem that carries `retryAfter`, and never sent without one?
8. **Tests can fail.** Run the new test files on base (stash `cmapi/src` in a copy) and on head, plus mutants:
   - no team bucket;
   - wrong class for `:export`;
   - a limit check after body validation;
   - a `Retry-After` of 0.

## How to run

`tests/service/conftest.py` puts the checkout's own `src` first on `sys.path`, so run each tree from its own `cmapi/` folder. `PYTHONPATH` alone does not switch trees.

Service tests, from a tree's `cmapi/`:

```
CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_695 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider
```

The reference suite, as CI runs it:

```
PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/wt-689-outputs/venv-ref/bin/python -m pytest tests/core -q
```

That database is yours. Do not run the whole service suite.

## Research first; never assume

Fetch and quote these, each with its URL and date:
- RFC 6585 §4;
- RFC 9110 §10.2.3;
- draft-ietf-httpapi-ratelimit-headers, its current status;
- OWASP API4:2023;
- the FastAPI 0.162.2 and Starlette 1.10.0 source on dependency and body order.

## Severity and fixes

- Mark each finding High, Medium or Low.
- Every High or Medium finding, and every Low one inside the changed lines, needs its **full code fix and a test that fails before and passes after**, in `r1-outputs/fix.diff`. Check that it applies to a fresh copy of `head/` with `patch -p1 -F0`.
- Other Low findings go to Backlog: describe them, with no fix.

Touch no repository, no GitHub and no cluster. No secrets.

End `r1-report.md` with a five-line summary.
