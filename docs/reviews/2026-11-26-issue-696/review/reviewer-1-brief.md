# Reviewer brief: cmapi PR #700 (closes #696), pool starvation. One reviewer.

You are the reviewer, from the Codex model family, adversarial. An Opus 5.5 high agent wrote the fix while reviewing PR #695.
The change is small (2 source files, +17 −7), so it gets one reviewer.

## The export

Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-700/`:
- `head/` is `0ec93a9`;
- `base/` is main `c5f705b`;
- `pr.diff` has 153 lines.

Write `r1-report.md`, and put any fix in `r1-outputs/fix.diff` against `head/`. Edit only a copy (`r1-work/`).

## The claim

`pipeline.submit` held a pooled connection and the advisory lock, then opened a **second** session through `ctx.auto_paused` (`core/context.py`). The pool is 5 + 5 overflow, so 12 creates at once gave three 500s after 30 s, and every route waited. The fix: `auto_paused` reads through the submit's own session. The new `tests/service/test_pool_starvation_695.py` has 2 tests that fail on base and pass on head.

## Confirm or refute, with a test that decides it

1. Every caller of `auto_paused` and every other path that opens a second session while a submit, approval or worker transaction holds a connection. Search `head/cmapi/src` with grep. Is any other nested-session path left, for example in `approvals`, the revert job, the expire check, or `team_request` from #695?
2. Reading inside the submit's transaction: does it change isolation semantics? Could it now see uncommitted state, or miss a pause that another transaction committed? Is that acceptable for an auto-approval kill switch? Quote the PostgreSQL 16 documentation on READ COMMITTED.
3. Do the tests really exercise the pool limit, or a mock? Run them on base and on head.
4. Behaviour beyond the purpose.

## How to run

**Your sandbox may not reach PostgreSQL.** If `psql`, or a connection to `127.0.0.1:55432`, is refused, say so plainly at the top of your report, and limit your claims to reading the code. **Do not substitute SQLite for this review:** pool and lock behaviour is the point.

From a tree's `cmapi/`:

```
CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_700 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider
```

## Severity and fixes

- Mark each finding High, Medium or Low.
- Every High or Medium finding needs its full code fix and a test that fails before and passes after.
- Low findings go to Backlog, unless they sit in the changed lines.

Research first: quote your primary sources, with their URL and the date you read them. No repository, GitHub or cluster changes. No secrets. End with a five-line summary.
