# PR #617, reviewer 2 (Opus 5.5, high)

PR #617 closes #614 and #615. I reviewed e47977d (`review-617/head/`) and did not write this code. Reviewer 1 is Codex
gpt-6.2-astra xhigh (`review-617/codex-result.txt`).

- **Working copy:** `review-617/r2/`.
- **Patch:** `r2-outputs/fix.diff`, against e47977d. It changes five files: `cmapi/src/cmapi/core/db/migrate.py`,
  `cmapi/tests/service/test_migrate_log_614.py`, `cmapi/tests/service/test_second_pass.py`,
  `docs/12-existing-postgresql.md` and `docs/18-configuration.md`. It applies with `patch -p1 -F0` from the repo root. I
  applied it to a fresh copy of head's five files, and each result is byte-identical to `r2/`. env.py does not change.
- **Database:** every run is on the local PostgreSQL 16 at `127.0.0.1:55432`, in database `cmapi_r2_617`, which I made and
  dropped. All runs were on 2026-11-23.
- **Machine:** the 1-minute load was 5.6 to 11.5, mostly from the CRC VM (`ps`: one Virtualization process at 730 % CPU).
  Two other agents' full service suites (wt-616, wt-604) ran during the review. My gate (`r2-outputs/gate.sh`) held each
  of my pytest runs until they had ended and the load was under 8.
- **Not touched:** no cluster, no git repository, no GitHub.

## Sources I read (2026-11-23)

- **12-factor, Logs** (https://12factor.net/logs): "each running process writes its event stream, unbuffered, to
  `stdout`", and "A twelve-factor app never concerns itself with routing or storage of its output stream." The page says
  nothing about log levels.
- **PostgreSQL 16, `lock_timeout`** (https://www.postgresql.org/docs/16/runtime-config-client.html): "The time limit
  applies separately to each lock acquisition attempt", and "A value of zero (the default) disables the timeout."
- **PostgreSQL 16, `pg_blocking_pids`** (https://www.postgresql.org/docs/16/functions-info.html): "One server process
  blocks another if it either holds a lock that conflicts with the blocked process's lock request (hard block), or is
  waiting for a lock that would conflict ... and is ahead of it in the wait queue (soft block)."
- **structlog** (https://www.structlog.org/en/stable/api.html): `make_filtering_bound_logger` "Create a new
  FilteringBoundLogger that only logs *min_level* or higher." The installed `structlog/_output.py:107-113` (26.1.0)
  writes `print(message, file=f, flush=True)`.
- **Alembic 1.20.1, installed `alembic/runtime/migration.py:594-630`.** `get_current_heads()` runs, then
  `_ensure_version_table()` on an empty database, then `self._migrations_fn(heads, self)`, then per step
  `step.migration_fn(**kw)`, `head_maintainer.update_to_step(step)` and the `on_version_apply` callbacks.
  `alembic/command.py:467-487`: `upgrade` builds `script._upgrade_revs(...)` inside `run_env()`, so the revision map loads
  inside the first step's interval.
- **SQLAlchemy 2.1.8, installed `sqlalchemy/engine/events.py:538-540`:** "Intercept commit() events, as initiated by a
  Transaction". `engine/base.py:1188-1190` dispatches it in `_commit_impl`, before the driver's commit.

## Finding 1: the success event depends on `CMAPI_LOG_LEVEL`. CONFIRMED; reviewer 1's fix ACCEPTED, NARROWED

**Measured on head** (`r2-outputs/f1-probe-head.txt`; the real `cmapi-migrate` in a schema of `cmapi_r2_617`):

| Invocation | Exit | Output |
|---|---:|---|
| `head`, level unset (INFO) | 0 | one `migrated` line |
| `head`, `CMAPI_LOG_LEVEL=WARNING` | 0 | nothing on stdout or stderr |
| `0007 --downgrade`, `WARNING` | 0 | nothing |
| `head`, `CMAPI_LOG_LEVEL=not-a-level` | 1 | `ValueError: Unknown level: 'NOT-A-LEVEL'`, before it migrates |
| `missing-revision` | 1 | stdout empty; stderr `CommandError: Can't locate revision ...` |
| no `CMAPI_DATABASE_URL` | 1 | stderr `CMAPI_DATABASE_URL is not set` |

**What the api and the worker do.** Both call `configure_logging(s.log_level)` (`main.py:153`, `worker.py:210`). In both
the Helm chart and the plain manifests, the initContainer `migrate` gets no `CMAPI_LOG_LEVEL`
(`deploy/helm/cmapi/templates/api.yaml:29-39`; `deploy/manifests/components/cmapi/20-api.yaml:62-71`). The api container
does get it (`api.yaml:54-55`, `api.logLevel`). So the silent run happens when someone runs the command in the api
container, for example docs/12's `cmapi-migrate 0007 --downgrade`. docs/12 does not say where to run that command, so this
part is inferred.

**Ruling: the migrator always logs at INFO.** There are three reasons:

- **Behaviour preservation.** Base never read the level: it printed `migrated to <target>` at every level. The PR changed
  this, and a change beyond the PR's purpose is a new bug. The PR also brought in the exit 1 on an invalid level.
- **What the logs are for.** The migrator's own events are its result and why it waits. Twelve-factor says a process
  writes its event stream to stdout and the environment routes it. A level that removes the only event a run makes
  takes away what that stream is for.
- **The simplest form.** A clamp (follow DEBUG, never go above INFO) would be more code, and DEBUG gives the migrator
  nothing. Alembic is held at WARNING in any case.

**The failure event: accepted, narrowed.** `migrate_failed` carries only `error` (the class of `exc.orig`, or else of the
exception) and `sqlstate`. It never carries the message: the code cannot vet an error's text. The traceback and the exit
code stay as they were. I narrowed reviewer 1's comment, which says that a message "can contain the URL". In the cases I
measured, the message does not contain it: a refused connection, a wrong password and a malformed port all left the
sentinel password out of stdout and stderr, on head and after the patch. So the comment now says why the text is left
out, without that claim. conftest.py:66 says libpq messages can quote a URL; I did not reproduce that.

**Tests.**
- `SystemExit` keeps its message: `test_a_failed_run_says_so_in_one_event_and_still_exits_with_its_diagnostic` checks
  that stderr's last line is exactly `CMAPI_DATABASE_URL is not set` and that the exit code is 1.
- `test_the_failure_event_never_carries_the_url_or_its_password` uses a sentinel password with a refused port and with a
  malformed port. It checks the event's key set exactly.

**Mutants** (`r2-outputs/mutants.txt`):
- `app-log-level`, which restores `configure_logging(settings().log_level)`: `test_the_result_is_written_whatever_the_log_level` fails.
- `no-failure-event`: killed (`test_migrate_log_614.py:157` fails; `mutants.txt`).
- `failure-event-leaks-text`, which adds `message=str(exc)`: killed (`test_migrate_log_614.py:172` fails on the extra `message` key).

docs/18's `CMAPI_LOG_LEVEL` row now says that `cmapi-migrate` does not read the level.

Final code (`migrate.py`; the rest of the old `run` body moves unchanged into `_migrate`):

```python
def run(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    # INFO, not CMAPI_LOG_LEVEL: a run's result is its one line, and it printed whatever the level before #614. The level
    # set for the api's container, where an operator may run cmapi-migrate by hand, must not hide it.
    configure_logging("INFO")
    # The `migrated` event carries what Alembic's INFO lines say ("Running upgrade 0007 -> 0008"), with the times; its
    # plain-text lines would break the JSON log that every other cmapi component writes.
    logging.getLogger("alembic").setLevel(logging.WARNING)
    try:
        _migrate(args)
    except (Exception, SystemExit) as exc:
        cause = getattr(exc, "orig", exc)           # SQLAlchemy's DBAPIError wraps the driver's error, which has the SQLSTATE
        # The class and the SQLSTATE only, never the error's text, which this code does not control. The traceback follows.
        log.error("migrate_failed", error=type(cause).__name__, sqlstate=getattr(cause, "sqlstate", None))
        raise


def _migrate(args: list[str]) -> None:
    if not settings().database_url:
        sys.exit("CMAPI_DATABASE_URL is not set")
    ...  # unchanged from e47977d's run(), from `url = ...` to the final _log_run
```

The full tests are in `fix.diff` (`test_migrate_log_614.py`, the last four tests and `_failed`).

## Finding 2: the docs/12 wording. CONFIRMED; reviewer 1's text REPLACED with a shorter one

I checked each of reviewer 1's statements against the code:

- **Rounding:** `round(x, 3)` (`migrate.py:70-73`). Confirmed.
- **The first step's start:** `last` is set after env.py's own `get_current_revision()` (`env.py:57-58`). So the first
  step excludes env.py's read. It includes Alembic's `get_current_heads()`, `_ensure_version_table()` on an empty
  database, and the revision-map load (sources above). Confirmed.
- **`lock_wait_seconds`** wraps the whole `pg_advisory_lock` statement (`env.py:34-36`). It measured 0.004 s with no
  other migrator (`f1-probe-head.txt`). Confirmed.
- **`migrate_skipped`** is written in place of `migrated`, and a failure writes no `migrated`. Confirmed.
- **Half-millisecond undershoot from rounding:** true, but a site measuring a lock in seconds does not need it. I left it out.

Reviewer 1's paragraph is long and dense. The replacement keeps each fact the code supports, in short sentences, and adds
`migrate_failed` with its `55P03` example. Final text (docs/12, section 4):

```markdown
- **Reading a migration's times (#614).** Each run of the migrator writes one result event to its log
  (`oc logs <pod> -c migrate`), at any `CMAPI_LOG_LEVEL`, after any `waiting_for_database` events. Times are in seconds,
  rounded to the millisecond.
  - `migrated`, when the run succeeds. `from_revision` is the revision found after the advisory lock, and `revision` is
    the revision at the end. `applied` lists each revision that ran, in order, with its `seconds`. The first revision's
    seconds also include Alembic's setup: it reads `alembic_version` (and creates it in an empty database) and loads the
    revision files. `transaction_seconds` runs from before the transaction begins to after it commits. So it is the
    longest time that a table lock of the run, such as `0008`'s ACCESS EXCLUSIVE, can be held. `lock_wait_seconds` is
    the `pg_advisory_lock` call: the wait for another migrator, plus a few milliseconds for the query. `total_seconds`
    starts after the wait for the server. A migrator that found the database at its target has `applied: []`.
  - `migrate_skipped`, when the database is at a later release's revision. Nothing ran.
  - `migrate_failed`, when the run fails: the error's class and its `sqlstate`, such as `55P03` for a lock timeout. The
    traceback follows, and the migrator exits non-zero.
```

The patched docs pass both checks:
- `deploy/tests/doc12-test.py`: 32 ok, 0 FAIL, exit 0 (`r2-outputs/doc12-test-r2.txt`).
- `scripts/doc-citations.py --check`: 0 problems, on head and on r2 (`r2-outputs/citations-*.txt`). The export has no
  `.git`, so `r2-outputs/citations_check.py` lists the files in place of `git ls-files`.

## Finding 3: weak timing assertions. CONFIRMED; reviewer 1's mock test REPLACED with a simpler real-database test

**Head's tests let three of six mutants through** (`r2-outputs/mutants.txt`, "-head" rows). Head's five #614 tests pass
with zeroed steps, swapped steps and stop-before-commit. They catch only `cumulative-steps`, where `last` is never
advanced, through its `steps <= transaction` check.

**Reviewer 1's controlled-clock test** (`r2-outputs/r1-tests/test_r1_timing.py`, verbatim) passes on head and on r2.

**My replacement** runs the real `cmapi-migrate` on PostgreSQL with known delays, set by two SQLAlchemy events in the
subprocess:
- 0.5 s before 0007's `ALTER TABLE request_events ALTER COLUMN at SET DEFAULT`;
- 1.0 s before 0008's `CREATE UNIQUE INDEX uq_cr_idempotency_caller`;
- 0.4 s on every commit.

It then checks:

```
0.5 <= 0007 < 1.0 <= 0008 < 1.5
transaction >= 0007 + 0008 + 0.4
lock_wait < 0.4
total >= lock_wait + transaction + 0.4
```

Each mutant was run against both tests (`r2-outputs/mutants.txt`):

| Mutant (env.py) | Head's tests | Reviewer 1's mock | Mine |
|---|---|---|---|
| zeroed steps (`"seconds": 0.0`) | pass (missed) | killed | killed |
| swapped durations | pass (missed) | killed | killed |
| cumulative (`last` never advanced) | killed | killed | killed |
| early start (`last` before the start read) | not run | killed | passes |
| stop before the commit | pass (missed) | killed | killed |
| lock wait measured after the setup commit | not run | **passes (missed)** | killed |

**Ruling: mine replaces reviewer 1's.**
- Reviewer 1's test patches `alembic.context`, `sqlalchemy.engine_from_config` and `time.perf_counter`, and runs env.py
  with `runpy`. It encodes env.py's exact call order: the lock SQL string, `get_context().get_current_revision()`, and
  `configure(on_version_apply=...)`. Any refactor of env.py breaks it.
- Its mock has no real commit, so it lets the lock-wait-after-commit mutant through.
- Mine uses the real Alembic, env.py and PostgreSQL. It depends only on two statements of fixed revisions (history does
  not change), and it is about 25 lines.

**The one mutant mine lets through is early start, and it is not a guarantee.** It moves env.py's own read of
`alembic_version` into the first step. That read is one indexed SELECT on a table that only a migrator holding the
advisory lock writes, so it cannot wait on a lock. The docs/12 text above does not say that the first step excludes it.
Owner's rule: over-build only if it is the only solution. No guarantee is lost here.

Final code: `fix.diff`, `test_migrate_log_614.py`, `SLOW` and
`test_each_time_holds_its_own_work_and_the_transaction_ends_after_its_commit`.

## Finding 4: the #615 test. CONFIRMED in part; NARROWED, and reviewer 1's replacement not taken

Reviewer 1's claims against head, measured (`r2-outputs/repeat615.txt`, `r2-outputs/mutants.txt`):

- **Any exit code is accepted.** Confirmed. Mutant `exit-0-on-lock-timeout-head` (`command.upgrade` wrapped in
  `except OperationalError: return`): it **passes** on head (`mutants.txt`: `exit-0-on-lock-timeout-head`, 1 passed), so head misses it.
- **The reader connects after the wait is seen.** Confirmed, and measured:
  - The migrator gives up 2 s after it queues. A reader sent at time t after the queue is cancelled by its 1 s
    `statement_timeout` only when t < 1 s.
  - Head opens the reader's connection and sets the timeout inside that 1 s. Connect plus `SET` took median 0.0228 s, p90 0.0242 s, max 0.0297 s over 50 runs (`repeat615.txt`, load 8.0 to 9.0).
  - Head passed 5 of 5 (`repeat615.txt`).
  - So it is a real margin, but a wide one.
- **Cleanup is skipped on an early assert.** Confirmed by reading `test_second_pass.py:337-341`. If the loop asserts, `old`
  keeps its ACCESS SHARE on `sp.jobs`, and the fixture's `DROP SCHEMA sp CASCADE` then waits on it with no timeout. I did
  not force that hang.
- **The pipe is not drained.** Confirmed by reading: `p.wait(8)` with `stdout=PIPE`. The migrator writes about 1 KB, far
  under a pipe buffer, so it cannot deadlock today. `communicate` is still the documented way to read a piped child.
- **New, missed by reviewer 1:** the `pg_locks` probe did not filter by database. `relation` is an OID, unique only within
  one database, and other agents' suites run their own databases on the same server.

**Reviewer 1's replacement** (`r2-outputs/r1-tests/test_r1_615.py`, verbatim):
- It is deterministic. Its first migrator has `lock_timeout` `0s`, which disables the timeout, and is cancelled once
  `pg_blocking_pids` shows the reader behind it. A second migrator then checks `55P03`.
- It passed 5 of 5 (`repeat615.txt`), and it kills the exit-0 mutant: killed (1 failed).
- But it runs the migrator twice and needs a thread pool, a `pg_stat_activity` join, `PGAPPNAME` and two context
  managers.

**Mine keeps one run.** It narrows each defect:
- the reader connects and sets its timeout before the migrator starts, so only one query send falls in the 1 s window;
- the probe is filtered to the current database;
- the whole wait sits in `try/finally`, which kills and reaps the child and closes both connections before the fixture's
  DROP;
- it uses `communicate(timeout=8)`;
- it asserts a non-zero exit, and exactly one `migrate_failed` with `sqlstate` `55P03`.

Results:
- It passed 5 of 5 (`repeat615.txt`).
- It kills the exit-0 mutant: killed (1 failed).
- Over-building rule: the only guarantee that reviewer 1's version adds is to remove the remaining scheduling margin
  (about 0.9 s for one send), at twice the run time and code. That margin did not fail in 15 (5 each of head, reviewer 2 and reviewer 1) runs.

The test file's other advisory-lock check
(`test_a_migration_that_fails_leaves_the_last_good_revision_and_the_lock_free`) got the same database filter.

Final code: `fix.diff`, `test_second_pass.py`.

## Reviewer 1's confirmed claims in sections 1 and 5

I re-checked each against the code. The tests are the run evidence.

- **Transaction boundaries.** Base `env.py:25-38` and head `env.py:30-61` both take a NullPool connection, run
  `pg_advisory_lock(727364)`, set `lock_timeout` and commit, then open one Alembic transaction. The start read is inside
  that transaction. Confirmed.
- **All or nothing still holds.** `test_a_migration_that_fails_leaves_the_last_good_revision_and_the_lock_free` passes on
  head and on r2: the version stays at 0002 and no advisory lock is left.
- **The advisory lock is unchanged.** `test_two_migrators_at_once_both_succeed` passes (60 passed).
- **No secrets in the event.** Confirmed. The sentinel probes and the new test found the password in neither the event
  nor the stream. `target` is the CLI argument as given. That is right, since the operator supplies it.
- **Reviewer 1's caveats are correct.**
  - The `on_version_apply` callback is not isolated: an exception in it aborts the transaction. It cannot raise on this
    linear history.
  - `get_current_revision()` raises on more than one head.
  - Alembic's per-step "Running ..." INFO line is gone. So during a hang the log does not say which step is running; the
    `migrated` event comes only at the end. I record this as a known limit and do not fix it. Restoring the line in JSON
    would mean logging inside the hook *before* each step, which Alembic does not offer.

## Test runs

| Run | Head | r2 (patched) |
|---|---|---|
| `test_migrate_log_614.py` + `test_second_pass.py` | 34 passed (`before-head-614-secondpass.txt`) | 38 passed (`after-r2-614-secondpass.txt`) |
| Other migrator tests: `test_review_h_tools_migrate.py`, `test_second_pass_converged.py`, `test_idempotency_caller_592.py` | in the implementer's full suite | 60 passed (`after-r2-migrate-related.txt`) |
| `doc12-test.py`, `doc-citations --check` | 0 problems | 32 ok, 0 problems |

Not run: the full service suite on r2 (the other agents' suites held the database server for most of the review), and
anything on kind or CRC.

## What reviewer 1 missed

Each is fixed in `fix.diff`.

1. **Their timing test misses a mutant:** a lock wait measured after the setup commit. The mock has no real commit cost.
   My real-database test kills it.
2. **The `pg_locks` probes were not filtered by database,** in three places: the #615 probe, the lock-wait test's probe,
   and the failing-migration test's check that no advisory lock is held. Advisory locks and relation OIDs are per
   database, and other suites run on the same server in their own databases, for example `cmapi_ob614` and
   wt-604/wt-616. Without the filter, a concurrent migrator in another database can satisfy the lock-wait probe early
   or fail the "lock is free" check.
3. **docs/18 said `CMAPI_LOG_LEVEL` is "The log level"** for every process. After finding 1 the migrator ignores it. The
   row now says so.
4. **Reviewer 1's comment claims more than was measured** ("an exception message can contain the URL"). It is not true in
   the cases I measured, so the comment now gives the real reason: the text is not ours to vet.

No new defect outside this PR's scope was found.


_The coordinator filled the measured blanks on 2026-11-24 from `r2-outputs/` after taking over the queued runs (`queue-coordinator.sh`; the idle gate's load limit raised from 8 to 16)._
