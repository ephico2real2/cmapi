# Reviewer 2 (Opus 5.5 high) · cmapi PR #695 (closes #689, #694) · rate limits

Reviewed 2026-11-25 on head `d692adc`. All database runs were on PostgreSQL 16, `127.0.0.1:55432/cmapi_r2_695`, with real
connections. No SQLite was used. Trees:

| Tree | What it is |
|---|---|
| `r2-head/` | a plain copy of `head/`, with test files added only to measure |
| `r2-work/` | `head/` plus Codex's `r1-outputs/fix.diff`, applied with `patch -p1 -F0` (clean) |
| `r2-final/` | `head/` plus my final patch, `r2-outputs/fix.diff` |

**Verdict: amend.** I accept 2 of Codex's 8 findings as they are, amend 3 (with a different fix), and reject 3. Codex's patch
passes its own tests on PostgreSQL: 57 passed (`r2-outputs/codex-fix-pg.txt`). But three of its fixes add defects of their
own:

- Its bucket cap fails closed. When the table is full, every new caller is locked out.
- Its refund design fails under concurrent submits on PostgreSQL, with 500s after 30 s.
- Its fix for the rate near 0 returns a `retryAfter` with 326 digits.

I also found a defect that predates the PR: pool starvation (Medium). Its fix is a separate patch,
`r2-outputs/followup-pool-starvation.diff`, for a follow-up pull request.

My final patch is smaller than Codex's: 11 files, 614 lines, against 17 files and 883 lines. It does not touch the
#592/#603 idempotency code or its tests.

## Sources read on 2026-11-25

- **nginx `ngx_http_limit_req_module`**, `limit_req_zone`, at <https://nginx.org/en/docs/http/ngx_http_limit_req_module.html>:
  "If the zone storage is exhausted, the least recently used state is removed. If even after that a new state cannot be
  created, the request is terminated with an error."
- **Envoy local rate limit proto** (docs for envoy 1.41.0-dev), at
  <https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/local_ratelimit/v3/local_rate_limit.proto>.
  `max_dynamic_descriptors`: "Specifies the max dynamic descriptors kept in the cache for a particular wildcard descriptor"
  … "max dynamic descriptors stored in the LRU cache" … "Minimum is 1. Default is 20."
- **golang.org/x/time/rate v0.16.0**, `Reservation.CancelAt`, at <https://pkg.go.dev/golang.org/x/time/rate>: "CancelAt
  indicates that the reservation holder will not perform the reserved action and reverses the effects of this Reservation
  on the rate limit as much as possible, considering that other reservations may have already been made."
- **The design.**
  - docs/01 line 779: "**Rate limits.** Token buckets per caller and per team, separate for writes, :place, :suggest and
    :export, and at most 3 active placements per team and environment".
  - docs/02 line 2098: "Rate limits | Protect clusters and the Git host from bursts | Per caller and per team token
    buckets".
  - docs/02 line 1105: "cmapi.net/team … Any value matching the pattern is accepted from any caller".
  - The PR record: "one token for each change request opened for the team".
- **The code.** RFC 6585 and RFC 9110 are quoted in the PR record and in Codex's report. I did not re-fetch them, and
  nothing below rests on them beyond their quoted text.

## Codex's findings, one by one

### 1. Unbounded bucket store

Codex rated it High. **Amend: Medium, with a different fix.**

**Measured on head.** I made 10,001 one-call callers, each with a bucket that was not full, on a frozen clock. Head kept
10,001 buckets (`r2-outputs/capacity-probe.txt`). The core test fails on head with `assert 10001 == 10000`.

Head's sweep drops only buckets that have refilled, and then doubles its threshold. So the store is bounded only by the
number of keys that are active at once. That is not without limit:

- A caller key needs a verified token, and `sub` is required (`core/auth.py:195`).
- A team key needs a submit that succeeds. A default team bucket refills one token in 0.1 s.

So I rate it Medium, not High. Even so, the claim in the PR record, "The memory is bounded", is false for a caller who
holds many identities.

**Codex's fix adds a lockout.** At 10,000 buckets that are not full, Codex refuses every new key with 429, "All rate limit
buckets are in use". Measured on `r2-work`:

- 10,000 identities each made one read. The first call of a new caller then got 429 with `retry_after=1`.
- 10,000 identities each made one `:export`, which takes 15 s to refill. Every new caller was then refused for 15 s
  (`t=0: 429 retry_after=15`, `t=14: 429`, `t=15: admitted`). An attacker can renew this indefinitely.

It is a denial-of-service vector against callers who have done nothing wrong. Both primary sources do the opposite. nginx
removes the least recently used state first, and Envoy keeps its dynamic descriptors in an LRU cache.

**My fix.**
- The table is an `OrderedDict` in least-recently-used order, with a hard cap of `MAX_BUCKETS = 10_000`.
- `take` moves its key to the end. A new key at the cap drops the first key, in O(1). The sweep is gone.
- A dropped bucket starts full when its key comes back. That gives tokens back only to whoever used them least recently.
  To evict their own spent bucket, an attacker needs 10,000 newer keys, which means 10,000 identities. With that many,
  they already have 10,000 times the budget.
- Measured on `r2-final`: 10,000 buckets kept, and the new caller admitted.
- docs/18 and the PR record now say what the bound is.

**Tests.**
- New: `test_buckets_that_are_not_full_stay_bounded_and_a_new_caller_is_never_refused_for_room`. It fails on head and
  passes on the fix. It also fails on Codex's fix, at the 10,001st `take`, which returns a refusal.
- Rewritten: `test_ratelimit_689.py::test_the_buckets_stay_at_most_max_buckets_and_the_least_recently_used_goes_first`
  (this test was `test_full_buckets_are_dropped_once_there_are_many`).

### 2. Private docs take no token

Codex rated it Medium. **Accept: Medium, Codex's fix with the same effect.**

**Measured on head, PostgreSQL.** With `docs.public: false` and the read bucket empty, `GET /docs` answered 503
`docs-assets-missing`. That is the route itself, so no limit ran. `/openapi.json` is 876,973 bytes, served without
limit to one caller. That contradicts the PR's own rule, "Every route that takes a token".

**The fix.** In `main.py` `_add_docs`, the private guard is `[Depends(authed), Depends(rate_limit(authed))]`, which is the
same wiring as the API routers. This fits docs/01, "per caller", and changes nothing for public docs.

**Test.** `test_private_docs_take_from_the_callers_read_bucket` checks every path, with GET and HEAD, both with and without
a token. It fails on head and passes on the fix.

### 3. A team transfer charges the wrong team

Codex rated it Medium. **Reject.** Head is right. A guard test now pins head's behaviour.

The team of a change request is `plan.facts["team"]`, the label after the change (`core/pipeline.py:417`). The same value
is used in three other places:
- the row's `team` (`pipeline.py:563`);
- the team whose auto-approvals of the day it counts (`pipeline.py:553`);
- the team the KPI report counts it under.

The PR record's rule is "one token for each change request opened for the team". docs/02 says only "per team". So the team
to charge is the team that the request records.

Codex's fix charges the team in Git instead. That makes the charged team differ from the recorded one, and it adds a
field, `Plan.existing_team`, to do so.

It also gains nothing:
- docs/02:1105 lets any caller name any team, so charging the old team protects nothing.
- A transfer already needs approval. Measured on head, a PATCH that moves `payments` to `billing` got "threshold
  sensitiveKeyChanged: +1 approver-platform".

Charging **both** teams is wrong too: one request is one branch and one pull request, so it is one token (docs/02: "Protect
… the Git host from bursts").

**Test.** `test_a_team_transfer_charges_the_team_that_the_request_records`:
- billing's bucket empty: 429, "team billing";
- after a refill: 202, with `team = billing` in the row, and payments uncharged.

It passes on head and on my fix. Codex's fix fails it, because it charges payments.

### 4. A failed submit keeps its team token, and a retry gets a 429

Codex rated it Medium. **Amend: Low, with a different, simpler fix.** The defect sits inside the changed lines, so it is
fixed now.

**Measured on head, PostgreSQL.**
- A submit that fails after its INSERT leaves the team bucket short. The next create got 429.
- A lost race to the same key replays the winner but keeps the token.
- A retry whose first lookup missed the winner got 429, although its request existed.

I rate it Low:
- each failure costs one token of a burst of 200;
- the caller's write bucket (burst 30) bounds how fast anyone can cause failures;
- a 429 to a retry is a valid transient answer.

**Codex's fix is invasive.**
- It holds a new process-wide `threading.Lock` across the whole submit transaction.
- It moves `next_id`, and so the advisory lock, ahead of the in-transaction replay check.
- It changes the signature of `pipeline.submit`.
- It makes `by_idempotency` read-only and adds `release_expired_key`. That rewrites the repository contract of #592/#603.
- It edits two existing tests. One of them, `test_idempotency_release2_603`, now calls `release_expired_key` first, so
  #603's `["UPDATE", "SELECT"]` assertion no longer tests `by_idempotency`.

All of that is behaviour beyond the finding's purpose.

**It also fails on PostgreSQL under concurrency.** I ran my concurrency test, at its first size (12 creates, 8 tokens), on
Codex's tree (`r2-outputs/codex-concurrency-pg.txt`). It answered `[202, 500, 500, 503, 500, …]`: `QueuePool limit of size
5 overflow 5 reached, connection timed out, timeout 30.00`.

Codex moves `next_id`, which takes the advisory lock, ahead of the team check. So every submit, including those the team
will refuse, waits on the advisory lock while it holds a pooled connection. The holder then opens a second session
(`pipeline._decide` → `ctx.auto_paused`) and finds no connection left. Codex could not see this, because it ran on SQLite
with a stand-in for the lock. The cause predates #689; see "What Codex missed", item 1.

**My fix.**
- `RateLimiter.give_back`, which is x/time/rate's `CancelAt` (quoted above). It adds one token under the limiter's lock
  and stops at the burst.
- `routers.team_request`, a context manager that wraps the transaction. It takes the token on entry, and gives it back if
  the transaction raises, including when the commit fails. `_submit` enters it before `c.db.session()`, so it exits after
  the commit.
- `_submit` looks up the replay for a team 429 as well as for a 409: `exc.status in (409, 429)`. That is the path that
  already handles a lost race.
- No lock is held across I/O. PostgreSQL's advisory lock already makes submits serial.

**Race-free under concurrent submits, measured.**
`test_concurrent_submits_spend_exactly_the_tokens_of_the_requests_recorded` sends 8 creates for one team at once, through
TestClient threads, the app's thread pool and real PostgreSQL connections. Each odd create fails after its INSERT. The team
has 5 tokens and only 4 creates are even, so at least 1 odd create took a token. I kept it at 8 creates, under the pool's 10
connections, so that it tests the tokens and not the pool starvation below.

The check: tokens left must equal 5 minus the rows in the database, whatever the interleaving.
- Head failed it, at 8 creates and at 12. At 12: `[202, 503, 202, 429, 429, 429, …]`, 5 recorded, 0 tokens left where 3
  were due.
- The fix passed it, 5 runs out of 5 at each size (`r2-outputs/codex-and-repeat-pg.txt`,
  `r2-outputs/followup-and-tight-pg.txt`).
- The core test `test_takes_and_gives_back_from_many_threads_leave_exactly_the_tokens_not_used` (200 threads) checks the
  same invariant on the limiter alone.

**Tests.** Each fails on head and passes on the fix:
- `test_a_submit_that_fails_after_its_insert_gives_the_team_token_back` (Codex's test, kept);
- `test_a_lost_race_to_the_same_key_replays_the_winner_and_gives_the_team_token_back` (new);
- `test_a_retry_refused_by_the_team_gets_the_request_its_key_already_made` (Codex's test, kept);
- the concurrency test.

**Mutants** (`r2-outputs/mutants.txt`):
- Without `give_back`: 3 tests fail.
- Without the 429 replay: 1 test fails.

### 5. Expired-key UPDATE during the replay check

Codex rated it Low. **Reject.**

The UPDATE is #603's design. Its docstring: "the caller's hold on the key is cleared here, in the caller's transaction".
An expired key replays nothing either way. The same UPDATE already ran before #689 ahead of every refused plan (a 422).

No design text says a 429 must write nothing. The PR record says the 429 comes "before the request is recorded", and it
does. Codex's fix is the repository rewrite described in finding 4. Its test, `test_team_refusal_issues_no_sql_write…`,
fails on head only because of that by-design UPDATE.

### 6. A rate near 0 raises `OverflowError`

Codex rated it Low. **Amend.** It is inside the changed lines, so it is fixed.

**Measured on head.** With `perMinute: 5e-324`, the second take raises `OverflowError: cannot convert float infinity to
integer`. That is a 500 where a 429 was due.

Codex's `Fraction` rewrite gives `retry_after = ceil(60/Fraction("5e-324"))`, an integer with 326 digits. That is far past
2^53−1, the largest integer JSON carries exactly, which this repository uses as its bound (`MAX_SETTING`). It also
rewrites the bucket arithmetic on every call.

**My fix.** The wait stops at `MAX_SETTING`:

```python
seconds = (1 - bucket.tokens) * 60 / limit.rate_per_minute
wait = MAX_SETTING if seconds >= MAX_SETTING else max(1, math.ceil(seconds))
```

**Test.** `test_a_rate_near_zero_waits_the_largest_setting_instead_of_raising` fails on head with `OverflowError`, and
passes on the fix.

Codex's other case was `0.3` a minute. Floating point gives 201 s against an exact 200 s. That over-estimates by 1 s, so the
bucket still holds a token after the wait. It is not a defect.

### 7. The config loader and the Helm schema disagree

Codex rated it Low. **Reject as a defect of this PR. Two items go to Backlog.**

- **null.** `parse_http` (#683) treats `http: null` as the defaults (`core/http_settings.py:34`). `rateLimits: null`
  follows the same precedent. Codex's change would make the two disagree.
- **`1.0`.** `maxRequestBodyBytes: 1.0` is refused in the same way (`http_settings.py:44`). Backlog, for both fields
  together: decide whether integral floats, which JSON Schema's `integer` accepts, are allowed.
- **`1e-7`.** The Helm template line is not in this PR. It matters only for `perMinute` below 1e-6, which is less than one
  call in about 1.9 years. Backlog: Helm's `toJson` writes such a value as `1e-07`, which PyYAML reads as a string.

### 8. An empty set is left for placements

Codex rated it Low. **Accept.** The PR changed `end_placement`'s signature, so this is inside the changed lines.

The fix deletes the empty set under the lock. It is the same as Codex's.

**Test.** `test_finishing_the_last_placement_keeps_no_empty_set` fails on head and passes on the fix.

## What Codex missed

1. **Pool starvation in the submit path (Medium). The defect predates the PR; fix it in a follow-up pull request.**
   - **Where.** `pipeline.submit` holds a pooled connection and the day's advisory lock (`next_id`). It then calls `_decide`,
     which calls `ctx.auto_paused`, which opens a second session (`core/context.py:58-63`, `pipeline.py:502`, `:553`).
   - **How it fails.** The submits queued behind the lock each hold a connection. With as many submits at once as the pool
     has connections (`pool_size=5`, `max_overflow=5`, `core/db/__init__.py:27`), the holder finds none and waits 30 s.
     It then answers 500, and every route of the pod waits with it.
   - **Measured on head, PostgreSQL** (`r2-outputs/pool-probe.txt`): 12 creates at once with the default limits gave
     `[202, 500, 202, …, 500, 500, …]`, 61.4 s.
   - **Not caused by #689.** `pipeline.py` is not in the PR's source change. Codex's reordering makes it reachable even
     when the team refuses.
   - **The fix.** Read the switch in the submit's own transaction: `ctx.auto_paused(session)` and
     `Pipeline._decide(..., session=repo.s)`. Five files, including the citations that moved (`docs/14`, two pipeline
     lines, relocated).
   - **Tests** (`test_pool_starvation_695.py`):
     - `test_a_create_holds_one_connection_at_a_time`: head checked out 2 connections at once, the fix 1.
     - `test_more_creates_at_once_than_the_pool_has_connections_all_succeed`: on head, a 500; on the fix, 12 × 202.
     - Both fail on head and pass on the fix. With `test_rate_limits_689.py` and `test_flow.py`: 41 passed
       (`r2-outputs/followup-and-tight-pg.txt`).
   - **Landing.** It touches `docs/14` and `docs/citations.lock.json`, as `fix.diff` does. Land it after #695 and rerun
     `doc-citations --relocate`.
2. **Its own cap is a lockout vector (Medium).** It fails closed, so filling the table refuses every new caller. See
   finding 1 for the measurements and the fix.
3. **Its rate fix produces a `retryAfter` beyond 2^53−1 (Low).** See finding 6.
4. **Its refund fix holds a process-wide lock across database I/O, and fails on PostgreSQL.** It also rewrites the
   #592/#603 code and weakens #603's test. See finding 4.
5. **The transfer finding contradicts the request's recorded team.** It is not a defect. See finding 3.
6. **The PR's docs claimed the memory was bounded.** docs/18 and the PR record are corrected.
7. **Checked, and found to be no defect:**
   - `sub` is required in every token (`auth.py:195`);
   - a delete charges the team in Git (`pipeline.py:536`);
   - Codex's dispatch check of all 39 operations and their HEAD variants passes on PostgreSQL. I kept it in my file as a
     guard: `test_each_operation_that_takes_a_token_charges_its_caller_once_from_its_class`.

## Results

| Run | Tree | Result | Output |
|---|---|---|---|
| Codex's tests, PostgreSQL | `r2-work` | 57 passed | `r2-outputs/codex-fix-pg.txt` |
| Codex's service tests, PostgreSQL | `r2-head` | 6 failed, 1 passed (the dispatch guard) | `r2-outputs/head-codex-tests-pg.txt` |
| My service tests, PostgreSQL | `r2-head` | 5 failed, 2 passed (dispatch and transfer guards) | `r2-outputs/head-r2-tests-pg.txt` |
| My core tests | `r2-head` | 5 failed (`OverflowError`, 10001, `give_back`, placements) | run inline |
| Service: mine, plus the #689, #592, #603, api_docs and authz files | `r2-final` | 107 passed, 1 failed | `r2-outputs/final-pg.txt` |
| `test_doc_citations.py` in a `git init` copy | `r2-final` | 12 passed | `r2-outputs/final-doc-citations-git.txt` |
| `doc-citations --check` | `r2-final` | 0 problems | `r2-outputs/citations.txt` |
| Reference suite `tests/core` (venv-ref) | `r2-final` | 775 passed, 113 skipped | `r2-outputs/final-core.txt` |
| My service tests, PostgreSQL | `r2-work` (Codex's fix) | 2 failed (concurrency: 500s; transfer) | `r2-outputs/codex-and-repeat-pg.txt` |
| Follow-up pool tests | `r2-head` | 2 failed | `r2-outputs/followup-and-tight-pg.txt` |
| Follow-up, with `test_rate_limits_689.py` and `test_flow.py` | `r2-followup` | 41 passed | `r2-outputs/followup-and-tight-pg.txt` |
| Follow-up reference suite `tests/core` | `r2-followup` | 770 passed, 113 skipped | `r2-outputs/followup-core.txt` |
| Patch check | fresh copies of `head/` | both patches apply with `-F0`, byte-identical (11 files and 5 files) | `r2-outputs/patch-check.txt` |

- **The one failure** in the `r2-final` service run is `test_doc_citations.py`. It runs `git ls-files`, and the export is
  not a git repository. The same test passes in a `git init` copy.
- **The reference suite** passed 770 on head; the 5 extra tests are my new core tests.
- **My tests on Codex's tree** are in `r2-outputs/codex-and-repeat-pg.txt`.

**Not tested:** several API pods, CRC, kind, and `:place`, which is not built.

## Five-line summary

1. **Accept:** #2 private docs (Medium) and #8 empty placement set (Low).
   **Amend:** #1 the cap (High to Medium; LRU instead of fail-closed), #4 the refund (Medium to Low; `give_back` instead of a
   lock across the transaction) and #6 the rate near 0 (clamp at 2^53−1).
   **Reject:** #3 team transfer, #5 expired-key UPDATE and #7 config null and `1.0`, with the `1.0` and `1e-7` cases to
   Backlog.
2. **Codex missed:** its cap is a lockout vector; its refund fix gives 500s under concurrency on PostgreSQL; its rate fix
   sends a 326-digit `retryAfter`. Pool starvation in `pipeline.submit` predates the PR (Medium): 12 concurrent creates gave
   500s after 30 s on head.
3. **`r2-outputs/fix.diff`:** 11 files, 614 lines, complete against `head/`, applies with `-F0`. On PostgreSQL, my tests
   failed 5 of 7 on head and 0 on the fix (the 2 that pass on head are guards). Wider service run: 107 passed, 1 failed (the
   git-only citations test, which passes in a git copy). Reference suite: 775 passed.
4. **`r2-outputs/followup-pool-starvation.diff`:** the follow-up fix, which needs its own issue and pull request. 2 of 2
   tests fail on head; with the related files, 41 passed on PostgreSQL. Reference suite: 770 passed.
5. **Not tested:** several pods, CRC and kind.
