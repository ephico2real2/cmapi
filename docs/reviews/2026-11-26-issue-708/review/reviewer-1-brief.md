# Reviewer 1 brief: cmapi PR #709 (closes #708), the validator slots. Security and availability, two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote it. Reviewer 2 (Opus) checks your fixes after you.

## The export

Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-709/`:
- `head/` is `b8e7971`;
- `base/` is main `cab292f`;
- `pr.diff` has 1348 lines. The source change is 8 files under `cmapi/src` (+104 −9).

Read `head/docs/reviews/2026-11-26-issue-708/README.md` in full: the Kyverno memory measurements and the sources. Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`. Edit only a copy (`r1-work/`).

## The defect and the claim

On CRC, 12 concurrent create dry runs OOM-killed the API (512Mi), with 12 `kyverno` CLI processes at once. Each plan ran `subprocess.run` of kubeconform and kyverno with no bound. AnyIO runs sync routes in a 40-thread pool.

The fix is `ValidatorSlots` in `core/validate/__init__.py`, two `BoundedSemaphore`s per process:
- One slot covers both CLIs of a plan. The default is 1 running plus 4 waiting, up to 15 s.
- A plan past the queue is refused at once and holds no thread.
- A refusal is 503 `validator-busy` with `Retry-After`, through the #694 path.
- It is configured by `CMAPI_VALIDATOR_CONCURRENCY`, `_QUEUE` and `_WAIT_SECONDS` (out of range stops the start), with chart values `api.validator.*`.
- Metrics: `cmapi_validator_busy_total{reason}` and `cmapi_validator_wait_seconds`.
- Measured: one `kyverno apply` peaks at about 151–158 MiB RSS. One slot plus the app comes to about 310 MiB of 512.

## Confirm or refute each point, with a test that decides it

1. **Every path that runs the CLIs goes through the slots:** plans, the worker, policy reports, `pr_checks`, and anything that calls `validate`. Search with grep in `head/cmapi/src`. A path that bypasses the slots is the same OOM.
2. **Semaphore correctness:**
   - each slot is released on every path: exception, timeout, a subprocess that hangs, a client that disconnects;
   - the queue counter cannot leak or go negative;
   - a refusal holds no thread.

   Prove each with a test that fails if the release is removed.
3. **The worker:** does it share the API's slots? It is a separate process, with its own limit. Can a worker job and an API plan together exceed the container's memory? They are in separate containers or pods: check the manifests.
4. **The timeout:** does a hung kyverno process ever get killed? `subprocess.run` with a timeout, and its process group. Otherwise a slot is held forever, which is a permanent outage.
5. **Is 503 `validator-busy` with `Retry-After` right?** Quote RFC 9110 §15.6.4. The answer must not leak internals.
6. **Config bounds** in the Python check and the Helm schema agree, with lab-safe defaults. The production values to raise are documented in docs/18. The owner allows raising pods in the lab when needed, but prefers using less.
7. **Tests can fail.** Run on base and head, plus mutants: no release in `finally`, a queue that is unbounded, and a bypass path.

## How to run

**Your sandbox may not reach PostgreSQL.** If so, say it at the top. Do not substitute SQLite.

From a tree's `cmapi/`, service tests:

```
CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_709 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider
```

Core tests: `PYTHONPATH=src`, `tests/core`.

## Severity and fixes

- Mark each finding High, Medium or Low.
- Every High or Medium finding, and every Low one inside the changed lines, needs its **full code fix and a test that fails before and passes after**. Check it applies to a fresh `head/` copy with `patch -p1 -F0`.
- Other Low findings go to Backlog.

Research first: quote your primary sources, with their URL and the date you read them. No repository, GitHub or cluster changes. No secrets. End with a five-line summary.
