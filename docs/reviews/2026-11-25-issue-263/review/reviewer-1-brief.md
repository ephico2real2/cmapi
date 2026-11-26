# Reviewer 1 brief: cmapi PR #699 (closes #263 and #321, part of story #25), the daily expiry check. Two reviewers.

You are reviewer 1, from the Codex model family, adversarial. Opus 5.5 high wrote this change. Reviewer 2 (Opus) checks your fixes after you.

## The export

Work only in `/Users/olasumbo/gitRepos/workbench/cmapi/review-699/`:
- `head/` is `9539685`;
- `base/` is main `cf1c0f4`;
- `pr.diff` has 1663 lines. The source change is 8 files, +381 −42.

Read `head/docs/reviews/2026-11-25-issue-263/README.md` in full. Write `r1-report.md`, and put your fix in `r1-outputs/fix.diff` against `head/`. Edit only a copy (`r1-work/`).

## What it does (the implementer's claims)

`jobs/expire_check.py` is a daily worker job. It:
- counts days in UTC (`utc_today()`, #321);
- sends notices at 14, 7 and 1 days, each once, by email to the team DL when SMTP is set. Otherwise it records them in `expiration_notices` and `noticesSent`;
- records grace once;
- after grace, opens the **normal delete request** through `Pipeline.plan_expiry_delete` and `submit`, as the service identity `cmapi-expire-check`, so no role check applies;
- lets the approval rules decide: `auto:expired-namespace` for rnd and dev, or `pending_approval`. Either way the request stops at `awaiting_prune` until an operator confirms;
- skips prod;
- runs each action in its own transaction, fenced by the job lease and a per-namespace lock.

## The design it must match (do not reopen it)

docs/01 and docs/02 on expiration: 30-day steps, a 180-day maximum, notices at 14, 7 and 1 days, seven days of grace, and expiry opening the normal delete request with approvals and operator prune confirmation, **never a direct delete**. docs/08 §2.

## Confirm or refute each point, with a test that decides it

1. **No direct delete, ever.** Every path ends in a delete *request* that needs prune confirmation. Could `cmapi-expire-check`'s identity let it skip a check that a person's delete must pass: protected labels, `cmapi.net/protected`, prod, unmanaged, or a namespace with a change pending?
2. **The service identity.** Can a person or a token ever be `cmapi-expire-check`? Is "no role check" limited to this job?
3. **Exactly once.** Notices and the delete request, across restarts, two worker replicas, a lease lost mid-run, and a date moved in Git between runs. Is the per-namespace lock the project's existing pattern?
4. **#321, UTC.** Every place that computed "today" now uses `utc_today()`, including the planner, `GET /expirations`, the portal and policy generation. Does the contract change (`ExpirationPage.today`) break the portal?
5. **Email.** Is the SMTP path safe: TLS on, no secrets in logs, a timeout? Does a mail failure block or repeat the notice?
6. **Tests can fail.** Run the new file on base and on head, plus mutants: send a notice twice, a direct delete, local date instead of UTC, and no prod skip.

## How to run

**Your sandbox may not reach PostgreSQL.** If it cannot, say so plainly at the top, and limit your claims about locks and transactions to reading the code. **Do not substitute SQLite** for lock or concurrency claims.

From a tree's `cmapi/`, service tests:

```
CMAPI_TEST_DATABASE_URL=postgresql://cmapi:cmapi@127.0.0.1:55432/cmapi_r1_699 PYTHONPATH=src:tests/service /Users/olasumbo/gitRepos/workbench/cmapi/wt-655-outputs/venv-merged/bin/python -m pytest <files> -q -W ignore -p no:cacheprovider
```

The reference suite:

```
PYTHONPATH=src /Users/olasumbo/gitRepos/workbench/cmapi/wt-689-outputs/venv-ref/bin/python -m pytest tests/core -q
```

## Severity and fixes

- Mark each finding High, Medium or Low.
- Every High or Medium finding, and every Low one inside the changed lines, needs its **full code fix and a test that fails before and passes after**. Check the fix applies to a fresh `head/` copy with `patch -p1 -F0`.
- Other Low findings go to Backlog.

Research first: quote RFC 3339, RFC 5321 / 8314 (mail over TLS), and the design lines, each with its URL and the date you read it. No repository, GitHub or cluster changes. No secrets. End with a five-line summary.
