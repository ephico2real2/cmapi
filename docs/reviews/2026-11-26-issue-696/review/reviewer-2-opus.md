# cmapi PR #700 (closes #696): reviewer 2 (Opus 5.5 high)

**PostgreSQL 16 was reachable.** Every run below used the database `cmapi_r2_700` on `127.0.0.1:55432`, the interpreter
`wt-655-outputs/venv-merged` (SQLAlchemy 2.1.8, psycopg 3.3.8), and was started from each tree's own `cmapi/`. Logs are in
`r2-outputs/logs/`. The scripts that ran them are `r2-outputs/run.sh` and `r2-outputs/run2.sh`.

## Verdict

PR #700 works for what it claims. On head, an HTTP create holds one connection, and twelve creates at once all return 202.
On base, the same creates return 500s after the 30 s pool timeout, and this reproduced in every run (6 of 6).

Codex's revert finding is **confirmed**: on head, the revert job checks out a second connection while it holds the request's
row lock. I give it **Low**, not Medium, because the worker cannot exhaust its pool (see finding 1). I still recommend landing
it in this PR, because it is the one remaining caller that breaks the PR's own rule.

Codex's saturation risk was **not observed**: the original test filled the pool and failed on base in every run. I still keep
its deterministic gate, and I add the proof that it asks for: the pool's checked-out count.

I replaced Codex's mock revert test with a real one on PostgreSQL. I add one Low hardening in the changed lines (a fresh read
of the switch) with a test that fails on head. I also tested and **retract** a regression that I suspected in Codex's patch.

`r2-outputs/fix.diff` (217 lines) is the complete patch against `head/`. On a fresh copy of head, `patch -p1 -F0` applies all
seven files with no fuzz. Each patched file matches `r2-work/` byte for byte.

## Primary sources (all read 2026-11-25)

- **PostgreSQL 16, §13.2.1, Read Committed**
  (https://www.postgresql.org/docs/16/transaction-iso.html): "a `SELECT` query (without a `FOR UPDATE/SHARE` clause) sees only
  data committed before the query began; it never sees either uncommitted data or changes committed by concurrent
  transactions during the query's execution … `SELECT` does see the effects of previous updates executed within its own
  transaction … two successive `SELECT` commands can see different data, even though they are within a single transaction".
- **SQLAlchemy 2.1.8, `Session.get` docstring** (installed source,
  `venv-merged/lib/python3.12/site-packages/sqlalchemy/orm/session.py`): "If the given primary key identifier is present in
  the local identity map, the object is returned directly from this collection and no SQL is emitted, unless the object has
  been marked fully expired."
- **SQLAlchemy 2.0, "Session Referencing Behavior"**
  (https://docs.sqlalchemy.org/en/20/orm/session_state_management.html): "Objects within the session are weakly referenced";
  they "fall out of scope from within the Session as well and are subject to garbage collection by the Python interpreter".
  The exceptions are pending, deleted, and "persistent objects which have pending changes on them".
- **SQLAlchemy 2.0, pooling** (https://docs.sqlalchemy.org/en/20/core/pooling.html), QueuePool `timeout`: "The number of
  seconds to wait before giving up on returning a connection. Defaults to 30.0." cmapi sets `pool_size=5, max_overflow=5`
  in `core/db/__init__.py:27-28`. The 500s on base logged the same limit: "QueuePool limit of size 5 overflow 5 reached,
  connection timed out, timeout 30.00".
- **Code**, read in `head/`:
  - `RequestRepo.move` locks the request row: `self.s.refresh(row, attribute_names=["status"], with_for_update=True)`
    (`core/db/repo.py:202`).
  - `next_id` takes `pg_advisory_xact_lock` (`repo.py:156`).
  - The worker is its own Deployment: `deploy/kind-test.sh:106` waits on `deploy/cmapi-worker`. It runs one `Worker` per
    process (`worker.py:208-216`), and that worker runs one handler at a time (`run_one`, `worker.py:102-130`).

## Reviewer 1's findings, measured on a plain copy of head

### R1-1: the revert job decides on a second session while it holds the row lock. Confirmed. Low (Codex: Medium). Land now.

What I measured: `test_the_revert_job_reads_the_switch_in_its_own_transaction` records `pool.checkedout()` at every checkout
during the real `open_revert` handler.
- On head it records `[2]`: the handler's connection, plus one more for `AppContext.auto_paused(None)`. The handler holds the
  `FOR UPDATE` lock from `repo.move` the whole time (`final-on-head.log`).
- With the fix it records `[]`: no checkout at all.

Why Low:
- The worker pod runs one handler at a time. Its peak is the handler, this nested read and the lease heartbeat: 3 of 10
  connections. The pool cannot starve.
- What remains is a needless dependency on a spare connection during recovery, with a row lock held.

Why land it now:
- It is the other caller of the `_decide(..., session=)` API that this PR adds.
- The PR's rule, read the switch in the caller's transaction, is not true until this caller follows it too.

Codex's one-line fix is right. I kept it and added a comment and the `_decide` docstring update.

### R1-2: the concurrent test "can pass on base without reaching the pool limit". Not observed. Low, in the changed lines: landed.

I ran the PR's original test unchanged, with a checkout probe (`r2-outputs/probes/test_zz_probe_r2.py`, not shipped). Every run
reached the pool limit:

| Tree | Runs | Peak `checkedout()` | 500s in each run |
|---|---|---|---|
| base | 5, plus the plain PR run | 10 in every run | 2, 2, 3, 3, 3; and 2 in the plain run |
| head | 5 | 10 in every run | 0 (all 202, about 1.6 s each) |

So the risk is only theoretical on this machine. Codex's barrier still makes it deterministic, so I kept it. The brief asked for
proof by the pool's own count, so the barrier action now records `pool.checkedout()`, and the test asserts
`at_fill == [POOL_LIMIT]` (10) before it looks at the statuses.

- On base this test fails with `at_fill == [10]` and a 500 caused by the QueuePool timeout (`r2tests-on-base.log`).
- On head it passes.

### R1-3: "every route waited" is broader than the evidence. Confirmed. Low, docstring only: landed.

- `/api/v1/version` is `async` with no I/O (`routers/health.py:47-53`), so it does not wait for the pool.
- `/readyz` calls `c.db.ping()`, which runs `engine.connect()` (`health.py:38`, `core/db/__init__.py:57`). So readiness can
  stall during a burst. That is a "route that needs the pool", as Codex's wording says.

### R1-4: READ COMMITTED visibility of the kill switch. Confirmed.

Codex's `test_switch_read_after_lock_sees_a_committed_pause` passes on head, on Codex's patch and on the final patch. On base
it fails with a `TypeError`, because base's `auto_paused` takes no session.

This holds because the PostgreSQL 16 sentence above is per query. A switch read that runs after the advisory-lock wait sees
any pause committed before that read began. It never sees an uncommitted one.

### R1's mock revert test: replaced

Codex's `Mock(spec=Session)` test asserted only the shape of the call, `_decide(facts, session=session)`. My replacement runs
the real flow on PostgreSQL: create, merge, `sync_failed`, `:revert`, then the real `Worker.run_one`. It measures what matters,
the pool count while the row lock is held, and it checks that the revert opened its request (2 rows).
- It fails on head with `[2]` and on base with `[2]`.
- It passes on Codex's patch and on the final patch.

## What reviewer 1 missed

### R2-1 (Low, in the changed lines of `core/context.py`): the switch read depended on the identity map. Hardened.

`auto_paused(session)` read the switch with `SwitchRepo.get`, which is `Session.get`. Per the docstring quoted above,
`Session.get` returns a row that the session still holds without SQL.

Today the read is fresh only because nothing keeps a strong reference to the `SwitchRow`. SQLAlchemy's identity map is weak,
so the row drops out once `SwitchRepo.get` returns its dict. A caller that keeps the row would see a stale switch inside its
transaction, even after a pause committed.

`test_a_switch_read_in_a_transaction_that_holds_the_row_sees_a_pause_committed_since` holds the row, commits a pause from
another session, takes the day's lock, and reads again. It **fails on head and on Codex's patch** (`assert False is True`,
`final-on-head.log`, `final-on-codex.log`) and passes with the fix.

The fix is `SwitchRepo.value(name)`: one `select(SwitchRow.value)` column query. It runs in the caller's transaction, so
READ COMMITTED applies to every read, and it never touches the identity map. `auto_paused` uses it on both branches.
`SwitchRepo.get`, used by the admin view, is unchanged. docs/16 and `docs/citations.lock.json` move with the lines.
`scripts/doc-citations.py --check` reports "0 problems", run on a scratch git copy because the export has no `.git`.

No current path holds the row. If the coordinator prefers the smaller diff, this hunk can be dropped:
`context.py`, `repo.py`, the two docs files and that one test. Its premise stays true only for as long as no caller keeps the
row.

### Retraction

I suspected that Codex's patch makes the revert's second switch read (submit, after the lock) come from the identity map and
miss a pause committed while the revert waits for the lock. **I retract this. The data refutes it.**

The probe `r2-outputs/probes/test_zz_probe_revert_r2.py` (not shipped) reverts a delete. That revert is an update, so it
decides twice. The probe commits a pause just before the revert's `next_id`, and it records each switch answer as
`(read in the caller's session, paused)`:

| Tree | The two switch answers |
|---|---|
| head | `[(False, False), (True, True)]` |
| Codex's patch | `[(True, False), (True, True)]` |
| final patch | `[(True, False), (True, True)]` |

In every tree, the second read saw the pause. The weak identity map had already dropped the row. R2-1 is the latent form of
this suspicion, and it stays Low.

### R2-2: the rest of the nested-session audit. No other path in head. One note for PR #699.

I searched with `grep -rn -e "db.session()" -e "engine.connect" -e "_decide(" -e "auto_paused" …` over `head/cmapi/src` and
traced each hit. This agrees with Codex's table:
- **Approvals.** `approve`, `reject`, `cancel`, `retry` and `revert` (`routers/requests.py:146-268`) each use one session.
  `repo.ledger` and `request_view` work in memory or on the same session.
- **HTTP submit.** `record_warned` writes under a savepoint of the same session (`rejections.py:170`).
- **`team_request`** (#695) takes an in-memory token, opens no session, and gives the token back on error. `_replay` runs
  after the submit session has closed.
- **Planning.** `plan_namespace` and `plan_delete` call `_decide(facts)` before `_submit` opens its session. Their own session
  is not nested.
- **`DbKeyStore`** runs during authentication, before the route's session.
- **`kpi`** runs its two connections one after the other.
- **Expiry on main.** `ExpirationRules.expire_check` is pure (`plugins/expiration/rules.py:214`), and no job is wired
  (`jobs/__init__.py`).
- **Apply and heartbeat.** The apply marker (`delivery.py:114-124`) and the heartbeat (`worker.py:88-100`) are intentional,
  as Codex says. `mark_apply_started` locks the row in its own transaction while the handler holds no lock on it.

Note for PR #699 (not merged, read in `review-699/head`): `jobs/expire_check.py:190` calls
`ctx.pipeline.plan_expiry_delete(...)` → `_decide(facts)` with no session. At that point the worker's handler session `s`
already holds a connection (`run_one` loaded the job row), but no row or advisory lock. Each later action opens its own
session (`:100`, `:146`, `:171`, `:190`). That makes three checkouts at most, in a worker that runs one handler at a time: no
starvation, and no lock held across a checkout. It needs no change in #700. #699's reviewers should know that its
`_open_delete` submit is the delete path: it keeps the planning decision and does not decide again under the lock.

## Final patch: `r2-outputs/fix.diff`

| File | Change | Who |
|---|---|---|
| `cmapi/src/cmapi/jobs/open_pr.py` | `_decide(facts, session=s)`, plus a two-line comment | Codex; comment by R2 |
| `cmapi/src/cmapi/core/pipeline.py` | `_decide` docstring names the revert job | R2 |
| `cmapi/src/cmapi/core/db/repo.py` | `SwitchRepo.value`: a column query, never the identity map | R2 (R2-1) |
| `cmapi/src/cmapi/core/context.py` | `auto_paused` reads with `SwitchRepo.value` | R2 (R2-1) |
| `docs/16-data-model.md`, `docs/citations.lock.json` | `repo.py` citations move by 6 lines; the decision's reader is named | R2 |
| `cmapi/tests/service/test_pool_starvation_695.py` | See the test table below | Codex and R2 |

The tests, before and after (`final-on-*.log`, `fresh-patched-adjacent.log`):

| Test | base | head | Codex's patch | Final patch |
|---|---|---|---|---|
| `test_a_create_holds_one_connection_at_a_time` (PR) | FAIL `[1,1,1,2]` | pass | pass | pass |
| `test_more_creates_at_once_…` (PR, Codex's barrier and R2's `at_fill == [10]`) | FAIL: 500, QueuePool timeout | pass | pass | pass |
| `test_the_revert_job_reads_the_switch_in_its_own_transaction` (R2, replaces Codex's mock) | FAIL `[2]` | FAIL `[2]` | pass | pass |
| `test_switch_read_after_lock_sees_a_committed_pause` (Codex) | FAIL `TypeError` | pass | pass | pass |
| `test_a_switch_read_in_a_transaction_that_holds_the_row_…` (R2-1) | FAIL `TypeError` | FAIL | FAIL | pass |

On the fresh copy with the patch applied, 42 tests passed in 79 s:
- the five tests above;
- `test_flow.py::test_auto_approval_kill_switch`;
- `test_review_e_recovery.py::test_git_outage_during_open_revert_loses_nothing`;
- `test_delete_whole_folder_616.py::test_the_revert_of_a_delete_names_the_paths_it_does_not_restore`;
- `test_dry_run_refused_606.py` and `test_client_input_653.py`, which exercise the admin switch.

I did not run the whole service suite, as the brief asked.

## What was measured, inferred and not tested

**Measured:** every pass and fail, pool count and status above, on PostgreSQL 16, on one Mac.

**Inferred:**
- That production cannot starve the worker's pool. This rests on the process model read in the code (one handler at a time,
  pool of 10), not on a load test.
- That the identity-map row is dropped at once. This holds under CPython reference counting, and the revert probe confirms it
  here. Another interpreter might keep the row longer.

**Not tested:** CRC or kind, and a multi-pod burst.

## Five-line summary

- PR #700 is confirmed on PG16: base gave 500s from the QueuePool timeout in 6 of 6 bursts that filled the pool (peak 10).
  Head: all 202, one connection for each create.
- Codex's revert nested session is confirmed (`[2]` checkouts under the row lock). It is Low, since the worker cannot starve,
  but land it: it is the last caller that breaks the PR's rule.
- Codex's saturation doubt was not observed (base failed 6 of 6). Its barrier is kept, with `at_fill == [10]` from
  `pool.checkedout()` as proof. Its mock test is replaced by a real worker-flow test.
- R2-1 (Low, in the changed lines): the switch read relied on the weak identity map. `SwitchRepo.value` makes it a query. Its
  test fails on head and on Codex's patch, and passes after. The hunk is optional.
- I retract my suspicion that Codex's patch stales the revert's second read: the probe saw the pause. `r2-outputs/fix.diff`
  applies with `-F0`, and 42 tests pass on the patched fresh copy.
