[codex] Starting Codex task thread.
[codex] Thread ready (01a20a8c-5a57-79d1-a4a2-9c03d358cf7b).
[codex] Turn started (01a20a8c-5cd8-7241-a633-9644c3abc280).
[codex] Assistant message captured: I’ll inspect the exported diff, trace the timing and failure paths through the installed Alem...
[codex] Running command: /bin/zsh -lc 'cd /Users/olasumbo/gitRepos/workbench/cmapi/review-617 && cat pr.diff'
[codex] Command completed: /bin/zsh -lc 'cd /Users/olasumbo/gitRepos/workbench/cmapi/review-617 && cat pr.diff' (exit 0)
[codex] Running command: /bin/zsh -lc 'cd /Users/olasumbo/gitRepos/workbench/cmapi/review-617/head for f in cmapi/src/...
[codex] Command completed: /bin/zsh -lc 'cd /Users/olasumbo/gitRepos/workbench/cmapi/review-617/head for f in cmapi/src/... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'configure_logging|merge_context|JSONRenderer|log =|log_level|PrintLogger...
[codex] Running command: /bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workben...
[codex] Running command: /bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workben...
[codex] Command completed: /bin/zsh -lc "rg -n 'configure_logging|merge_context|JSONRenderer|log =|log_level|PrintLogger... (exit 0)
[codex] Command completed: /bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workben... (exit 0)
[codex] Command failed: /bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workben... (exit 1)
[codex] Running command: /bin/zsh -lc "nl -ba cmapi/src/cmapi/core/observability.py | sed -n '98,129p' nl -ba cmapi/sr...
[codex] Command completed: /bin/zsh -lc "nl -ba cmapi/src/cmapi/core/observability.py | sed -n '98,129p' nl -ba cmapi/sr... (exit 0)
[codex] Running command: /bin/zsh -lc 'd=../../ob1-run/venv/lib/python3.12/site-packages nl -ba "$d/alembic/runtime/mi...
[codex] Command completed: /bin/zsh -lc 'd=../../ob1-run/venv/lib/python3.12/site-packages nl -ba "$d/alembic/runtime/mi... (exit 0)
[codex] Running command: /bin/zsh -lc "rg -n 'FUTURE_REVISION|def sqlalchemy_url' cmapi/src/cmapi/core/db/__init__.py ...
[codex] Command completed: /bin/zsh -lc "rg -n 'FUTURE_REVISION|def sqlalchemy_url' cmapi/src/cmapi/core/db/__init__.py ... (exit 0)
[codex] Assistant message captured: The nine selected integration tests hit sandbox socket restrictions. The installed Alembic so...
[codex] Running command: /bin/zsh -lc "PYTHONPATH=cmapi/src:cmapi/tests/service /Users/olasumbo/gitRepos/workbench/cma...
[codex] Running command: /bin/zsh -lc "PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/...
[codex] Running command: /bin/zsh -lc "nl -ba cmapi/src/cmapi/core/db/__init__.py | head -32 nl -ba cmapi/tests/servic...
[codex] Command completed: /bin/zsh -lc "PYTHONPATH=cmapi/src:cmapi/tests/service /Users/olasumbo/gitRepos/workbench/cma... (exit 0)
[codex] Command completed: /bin/zsh -lc "nl -ba cmapi/src/cmapi/core/db/__init__.py | head -32 nl -ba cmapi/tests/servic... (exit 0)
[codex] Command completed: /bin/zsh -lc "PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/... (exit 0)
[codex] Running command: /bin/zsh -lc 'd=../../ob1-run/venv/lib/python3.12/site-packages nl -ba "$d/psycopg/connection...
[codex] Command completed: /bin/zsh -lc 'd=../../ob1-run/venv/lib/python3.12/site-packages nl -ba "$d/psycopg/connection... (exit 0)
[codex] Running command: /bin/zsh -lc "PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/...
[codex] Command completed: /bin/zsh -lc "PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/... (exit 0)
[codex] Running command: /bin/zsh -lc "PYTHONPATH=cmapi/src:cmapi/tests/service /Users/olasumbo/gitRepos/workbench/cma...
[codex] Command failed: /bin/zsh -lc "PYTHONPATH=cmapi/src:cmapi/tests/service /Users/olasumbo/gitRepos/workbench/cma... (exit 1)
[codex] Running command: /bin/zsh -lc "PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/...
[codex] Command completed: /bin/zsh -lc "PYTHONPATH=cmapi/src /Users/olasumbo/gitRepos/workbench/cmapi/ob1-run/venv/bin/... (exit 0)
[codex] Assistant message captured: **Reviewer 1 verdict — request changes on #617.** The migration transaction and session advis...
[codex] Turn completed.
**Reviewer 1 verdict — request changes on #617.** The migration transaction and session advisory lock are preserved for cmapi’s linear revision history. The main defects are operational and in the tests: a successful invocation can emit no `migrated` event, a failed invocation emits no structured failure event, and the #615 test can both fail on a correct migrator and pass on one that wrongly exits zero.

I reviewed the supplied `e47977d` export. I made no file changes, touched no git repository, and did not push. Paths below are relative to `head/` unless marked `base/`. `runtime/migration.py` refers to the supplied venv’s Alembic source; the project pins Alembic 1.20.1 at `cmapi/pyproject.toml:17`.

## 1. The migration path

**Confirmed — transaction boundaries, lock identity, and normal rollback behavior are preserved.** Compare `base/cmapi/src/cmapi/core/db/migrations/env.py:25–38` with `cmapi/src/cmapi/core/db/migrations/env.py:30–61`. Both use a `NullPool` connection, acquire the session lock with exactly `SELECT pg_advisory_lock(727364)`, execute the same `SET lock_timeout`, commit that setup transaction, and then enter one Alembic transaction. The new starting-revision read is **inside** that transaction, after both the advisory lock and the setup commit. It does not trigger an SQLAlchemy autobegin ahead of Alembic’s transaction. PostgreSQL’s Alembic implementation declares transactional DDL at `alembic/ddl/postgresql.py:79`. The outer transaction and per-migration context selection are visible at `runtime/migration.py:406–415,455–460,604–605`.

**Confirmed — the 30 seconds apply per lock acquisition after the `SET`.** The default, override, conversion, SQL, and order are unchanged at `cmapi/src/cmapi/core/db/migrations/env.py:35–41`. The migrator’s own 30-second setting does not bound its preceding advisory-lock wait or the time a revision spends working after acquiring a table lock. `docs/12-existing-postgresql.md:103–109` describes this correctly.

**Confirmed with a qualification — there is still an earlier revision read.** The existing upgrade compatibility check uses a separate connection before `command.upgrade` at `cmapi/src/cmapi/core/db/migrate.py:29–43,97–102`; compare `base/cmapi/src/cmapi/core/db/migrate.py:69–74`. The event takes `from_revision` from the later, serialized read at `migrations/env.py:57`. Thus a second migrator that waited while the first advanced the database can report the revision it actually found on acquiring the lock. A statement that *all* revision reads follow the lock would be incorrect.

**Confirmed for the supported history — the hook receives the fields it uses.** Alembic runs the revision function, updates the version table, then passes `step.info` and a set of resulting heads to the callback at `runtime/migration.py:616–630`. `up_revision_id` identifies the migration script, including the script undone on downgrade (`runtime/migration.py:829–847,875–883`). The callback reads a monotonic performance counter, sorts the head IDs, and appends to an ordinary list at `migrations/env.py:45–52`. I found no ordinary upgrade, downgrade, no-op, or downgrade-to-base input in this linear history that makes those operations raise. Empty resulting heads are handled at `migrate.py:65–71`.

The hook is **not exception-isolated**. If the callback raises, Alembic does not catch it at `runtime/migration.py:624–630`; the exception leaves the transaction context at `migrations/env.py:56–61`, whose exit delegates to SQLAlchemy at `runtime/migration.py:70–76`. This aborts the migration transaction. The extra read can also raise: Alembic’s `get_current_revision()` rejects multiple current heads at `runtime/migration.py:478–487`. cmapi’s shipped history is linear, and the upgrade precheck already used this same single-head API. An unconditional claim that instrumentation *cannot* abort any Alembic invocation would be too strong. Conversely, final event formatting and writing at `migrate.py:62–74,93–102` occur after the command returns; a failure there cannot undo a committed migration.

## 2. Finding — successful runs can be silent, and failures have no structured event

`cmapi/src/cmapi/core/db/migrate.py:79` now calls `configure_logging(settings().log_level)` before even checking the database URL. The setting is an unrestricted string, default `INFO`, at `cmapi/src/cmapi/settings.py:17–18,66`. `cmapi/src/cmapi/core/observability.py:114–124` uses it for both standard logging and structlog’s filtering wrapper. All three migrator events use `info` (`migrate.py:58,70,99`).

I reproduced these results using the real entry function and Alembic, with an in-memory SQLite database stamped `0008` and the two PostgreSQL-only setup statements substituted. These probes exercise command dispatch and logging, **not** PostgreSQL locking.

| Invocation | Exit | Observed output |
|---|---:|---|
| `head`, `INFO` | 0 | One parseable `migrated` line, `from_revision = revision = "0008"`, `applied = []` |
| `head`, `WARNING` | 0 | Empty stdout and stderr |
| `head`, invalid log level | 1 | `ValueError: Unknown level` before migration |
| Missing target revision, `INFO` | 1 | Empty stdout, Alembic `CommandError` on stderr |

The exported Helm API init container passes the database URL and optional CA settings; its configurable API log level belongs to the subsequent application container (`deploy/helm/cmapi/templates/api.yaml:29–39,46–55`). The silent-success case therefore matters particularly for direct invocations and deployments that set the migrator’s environment. The former unconditional success print did not depend on that setting (`base/cmapi/src/cmapi/core/db/migrate.py:56–75`).

**Failure behavior:** confirmed that an ordinary migration exception still escapes and the CLI exits nonzero. Refuted that an event is logged with the terminal error. `_wait_for_database` re-raises on the final failed attempt *before* the retry log, and both `_log_run` calls follow successful command returns (`migrate.py:55–59,93–102`). The base code also propagated failures. The PR preserves the diagnostic traceback and ordinary failure status, but its new logging configuration introduces the separate invalid-level exit above.

**Proposed fix.** Treat the short-lived CLI’s lifecycle events as an unconditional operational record. Configure its logger at INFO, keep the Alembic threshold, add a distinct failure event, and re-raise so the existing diagnostic and exit status survive. Replace `run` with these two functions in `migrate.py`. This change intentionally makes the migrator independent of the application log level.

```python
def run(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    configure_logging("INFO")
    logging.getLogger("alembic").setLevel(logging.WARNING)

    try:
        _run_migration(args)
    except (Exception, SystemExit) as exc:
        cause = getattr(exc, "orig", exc)
        log.error(
            "migrate_failed",
            error=type(cause).__name__,
            sqlstate=getattr(cause, "sqlstate", None),
        )
        raise


def _run_migration(args: list[str]) -> None:
    if not settings().database_url:
        sys.exit("CMAPI_DATABASE_URL is not set")
    url = os.environ.get("CMAPI_DATABASE_URL") or settings().database_url
    _wait_for_database(url, float(os.environ.get("CMAPI_MIGRATE_WAIT_SECONDS", "540")))

    cfg = Config(str(Path(__file__).parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    target = args[0] if args else "head"
    started = time.perf_counter()

    if args[1:] == ["--downgrade"]:
        command.downgrade(cfg, target)
        _log_run("downgrade", target, cfg.attributes["cmapi.run"], started)
        return

    ahead = _compatible_future(url)
    if ahead:
        log.info(
            "migrate_skipped",
            revision=ahead,
            reason="the database is at a later release's revision",
        )
        return

    command.upgrade(cfg, target)
    _log_run("upgrade", target, cfg.attributes["cmapi.run"], started)
```

**Regression tests.** Add these to `test_migrate_log_614.py`. The imported subprocess helper merges stderr into stdout at `cmapi/tests/service/test_review_h_tools_migrate.py:43–45`, so the failure test can check the JSON event and the original diagnostic independently.

```python
def test_success_event_survives_application_log_level(empty_schema, monkeypatch):
    for level in ("WARNING", "not-a-level"):
        monkeypatch.setenv("CMAPI_LOG_LEVEL", level)
        assert _migrated("head", url=empty_schema)["revision"] == REQUIRED_REVISION


def test_failure_has_one_error_event_and_preserves_cli_failure(empty_schema):
    p = migrate(empty_schema, "missing-revision")
    out = p.communicate(timeout=120)[0]
    assert p.returncode != 0
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    assert [e["event"] for e in events] == ["migrate_failed"]
    assert events[0]["error"] == "CommandError"
    assert "Can't locate revision" in out
```

## 3. Finding — the timing fields are useful, but the runbook overstates their precision and scope

| Field | What the code measures |
|---|---|
| `applied[i].seconds` | **Confirmed** elapsed interval ending at that revision’s post-version-update callback. The first interval **excludes** the explicit starting-revision read because `last` is set afterward (`migrations/env.py:55–59`). It **includes** Alembic’s second current-head/version-table lookup, possible version-table creation, planning, revision work and version update (`runtime/migration.py:524–531,594–605,616–630`). Subsequent intervals start at the preceding callback’s clock sample (`migrations/env.py:49–52`). These are not isolated DDL execution times. |
| `transaction_seconds` | **Confirmed** client wall time from just before entering the migration transaction until after successful context exit (`migrations/env.py:55–61`). The unrounded interval bounds how long `0008` holds its `change_requests` table lock during that transaction: it adds the column before the checks, updates, and index build (`0008_idempotency_key_of_the_caller.py:88–95`). The published number is rounded to the nearest millisecond (`migrate.py:73`), so it can undershoot the unrounded interval by up to half a millisecond. It does not bound locks in the earlier compatibility-check transaction. |
| `lock_wait_seconds` | **Confirmed** elapsed client time around the entire `SELECT pg_advisory_lock(727364)` call (`migrations/env.py:34–36`). It includes executing the query and its round trip even when there is no competing pod. The code does not identify which session held the lock. |
| `total_seconds` | **Confirmed** it excludes database readiness waiting. It also excludes subsequent config construction before `started`, and event output after the final clock sample. On upgrade it includes the compatibility check, command, and connection teardown (`migrate.py:70–74,88–102`). |
| Event count | A successful command, including a no-op, reaches one `_log_run`. The future-schema branch emits `migrate_skipped`; a failure emits no `migrated` (`migrate.py:93–102`). Both pods can legitimately report `applied: []` when the database was already at target. |

**Failure scenario.** An operator following `docs/12-existing-postgresql.md:110–116` could attribute a small nonzero lock time to another pod, treat a rounded number as an exact lock-hold bound, or search for a missing second `migrated` event on a future-schema rollback. The “one with a non-empty `applied`” description also assumes that at least one revision was pending.

**Full documentation replacement** for lines 110–116, assuming finding 2 is fixed:

> **Reading a migration’s times (#614).** Inspect the init container with `oc logs <pod> -c migrate`. A successful upgrade or downgrade emits one `migrated` JSON line. `from_revision` is the revision read under the advisory lock; `revision` is the resulting revision. `applied` lists the scripts run, in order, and is empty for a no-op. Per-script seconds span successive Alembic completion callbacks, including version-table updates. The first interval starts after the explicit starting-revision read and includes Alembic’s own version lookup and setup. `transaction_seconds` spans entry to and successful exit from the migration transaction. Its unrounded duration bounds the time a revision in that transaction holds a table lock. `lock_wait_seconds` measures the entire advisory-lock query, including any wait. `total_seconds` starts after database readiness and command configuration and includes the upgrade compatibility check when applicable. All durations are client elapsed times rounded to milliseconds. A newer compatible schema emits `migrate_skipped`. A failed invocation emits `migrate_failed`; inspect its diagnostic and exit status.

**Test quality and mutants.** `cmapi/tests/service/test_migrate_log_614.py:35–49` checks nonnegative floats and upper-bound inequalities. I ran the actual two-revision test’s assertions against the real `_log_run`, with synthetic measured steps of distinct durations. Zeroing all step times survived. Reversing the two durations while leaving revision IDs in order survived. Zeroing both transaction and step times survived. Zeroing only transaction time was caught for those inputs. These were in-memory mutants of the measurement-to-event path, not claims that the PostgreSQL suite ran.

**Full regression test for the timing boundaries.** This uses the actual exported `env.py` with a controlled clock. The distinguishing values let it catch zeroed intervals, swapped attribution, inclusion of the explicit starting read, and exclusion of commit. In my probe the head produced `(2, [5, 7], 19)`; the zero-step, early-start, and pre-commit-stop mutants produced `(2, [0, 0], 19)`, `(2, [8, 7], 19)`, and `(2, [5, 7], 15)` respectively. Checking the emitted event in the same test also covers the `_log_run` mutants.

```python
def test_migration_timing_boundaries(monkeypatch):
    import runpy
    from contextlib import contextmanager, nullcontext
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import Mock

    import alembic
    import sqlalchemy
    from cmapi.core.db import migrate as cli

    clock = [0.0]

    def advance(seconds):
        clock[0] += seconds

    ctx = Mock()
    ctx.config = cli.Config()
    ctx.config.set_main_option("sqlalchemy.url", "postgresql://localhost/db")
    ctx.is_offline_mode.return_value = False
    conn = Mock()
    engine = Mock()
    engine.connect.return_value = nullcontext(conn)

    def sql(query):
        if query == "SELECT pg_advisory_lock(727364)":
            advance(2)

    @contextmanager
    def transaction():
        yield
        advance(4)  # commit

    def read_start():
        advance(3)
        return "0006"

    def run_steps():
        callback = ctx.configure.call_args.kwargs["on_version_apply"]
        for revision, seconds in (("0007", 5), ("0008", 7)):
            advance(seconds)
            callback(step=SimpleNamespace(up_revision_id=revision), heads={revision})

    conn.exec_driver_sql.side_effect = sql
    ctx.begin_transaction = transaction
    ctx.get_context.return_value.get_current_revision.side_effect = read_start
    ctx.run_migrations = run_steps
    monkeypatch.setattr(alembic, "context", ctx)
    monkeypatch.setattr(sqlalchemy, "engine_from_config", lambda *a, **kw: engine)
    monkeypatch.setattr(time, "perf_counter", lambda: clock[0])
    output = Mock()
    monkeypatch.setattr(cli, "log", output)

    runpy.run_path(str(Path(cli.__file__).with_name("migrations") / "env.py"))
    cli._log_run("upgrade", "head", ctx.config.attributes["cmapi.run"], 0.0)
    fields = output.info.call_args.kwargs
    assert fields["applied"] == [
        {"revision": "0007", "seconds": 5.0},
        {"revision": "0008", "seconds": 7.0},
    ]
    assert fields["lock_wait_seconds"] == 2.0
    assert fields["transaction_seconds"] == 19.0
    assert fields["total_seconds"] == 21.0
```

## 4. Finding — #615 still has a scheduling race and accepts the wrong exit status

**Confirmed** that the new poll checks an *awaited* `AccessExclusiveLock` on `'sp.jobs'::regclass` at `cmapi/tests/service/test_second_pass.py:337–341`. That is the table held by the old reader at line 331 and altered by `0003_job_lease_generation.py:20`. The loop checks the child and a 60-second monotonic deadline. This fixes the former assumption that the migrator would start within 1.5 seconds.

**Refuted** that the whole test is deterministic or fully bounded:

- The migrator has only two seconds from queuing to lock timeout. **After** observing its wait, the test opens a new reader connection, executes `SET`, and requires a one-second query timeout (`test_second_pass.py:332–347`). If connection establishment or scheduling takes more than the remaining margin, the reader succeeds and the test fails on correct code. The lock query also identifies neither the database nor the waiting backend explicitly.
- `p.wait(8); exited = True` accepts **any** return code (`test_second_pass.py:349–356`). I ran the actual test function with a simulated canceled reader and a child returning **0**; it passed. A migrator that swallowed the DDL lock-timeout exception would satisfy these assertions while allowing the init container to report success.
- The deadline is checked between SQL calls. It does not bound the connection at line 342 or the polling SQL itself. The child writes to a pipe that `wait()` does not drain. An early assertion skips explicit child/connection cleanup, and the timeout arm kills without reaping (`test_second_pass.py:331–353`). The schema fixture subsequently runs `DROP SCHEMA ... CASCADE` at lines 299–304. A retained blocking connection can therefore stall cleanup. These are possible failure paths, not observed PostgreSQL hangs.

**Full replacement test.** Exercise queue ordering and expiry in two separate attempts. In the first, keep the DDL queued until PostgreSQL itself identifies the reader behind that specific backend. In the second, retain the original blocking transaction and require the real two-second timeout and a failing exit. This uses the structured SQLSTATE from finding 2. The outer deadlines are test failure bounds, not assumptions about a particular interleaving.

```python
def test_migrate_gives_up_behind_a_long_transaction_instead_of_stalling_every_reader(schema):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from uuid import uuid4

    assert migrate(schema, "0002").returncode == 0
    app = f"cmapi-615-{uuid4().hex}"

    @contextmanager
    def child(lock_timeout):
        env = {
            **os.environ,
            "CMAPI_DATABASE_URL": schema,
            "PYTHONPATH": str(ROOT / "cmapi/src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CMAPI_MIGRATE_LOCK_TIMEOUT": lock_timeout,
            "PGAPPNAME": app,
        }
        p = subprocess.Popen(
            [sys.executable, "-c", "from cmapi.core.db.migrate import run; run(['head'])"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            yield p
        finally:
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=10)

    def observe(conn, p, query, params):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            row = conn.execute(query, params).fetchone()
            if row:
                return row[0]
            assert p.poll() is None, "migrator exited before the queue was observed"
            time.sleep(0.05)
        raise AssertionError("lock queue did not reach the expected state")

    options = {"connect_timeout": 5}
    with (
        psycopg.connect(schema, **options) as old,
        psycopg.connect(schema, autocommit=True, **options) as observer,
        psycopg.connect(schema, autocommit=True, **options) as reader,
    ):
        observer.execute("SET statement_timeout = '5s'")
        reader.execute("SET statement_timeout = '75s'")
        old.execute("SELECT 1 FROM jobs LIMIT 1")

        with child("0s") as p:
            waiter = observe(observer, p, """
                SELECT l.pid
                  FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
                 WHERE a.application_name = %s
                   AND l.database = (SELECT oid FROM pg_database
                                      WHERE datname = current_database())
                   AND l.relation = 'sp.jobs'::regclass
                   AND l.mode = 'AccessExclusiveLock' AND NOT l.granted
                   AND %s = ANY(pg_blocking_pids(l.pid))
            """, (app, old.info.backend_pid))
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(reader.execute, "SELECT count(*) FROM jobs")
                try:
                    observe(observer, p, """
                        SELECT 1 WHERE %s = ANY(pg_blocking_pids(%s))
                    """, (waiter, reader.info.backend_pid))
                finally:
                    observer.execute("SELECT pg_cancel_backend(%s)", (waiter,))
                pending.result(timeout=10)
            p.communicate(timeout=10)
            assert p.returncode != 0

        with child("2s") as p:
            out = p.communicate(timeout=60)[0]
            assert p.returncode != 0, out
            events = [json.loads(s) for s in out.splitlines() if s.startswith("{")]
            errors = [e for e in events if e["event"] == "migrate_failed"]
            assert [e["sqlstate"] for e in errors] == ["55P03"], out
            assert observer.execute(
                "SELECT version_num FROM sp.alembic_version"
            ).fetchone() == ("0002",)
```

This replacement is the regression test: the swallowed-error mutant fails its return-code check, an unrelated crash fails its SQLSTATE check, and a delayed reader no longer has to beat the two-second DDL timeout. It still needs the coordinator’s PostgreSQL run.

## 5. Secrets, Alembic diagnostics, and log ingestion

**Confirmed — the new structured fields do not copy the DSN, password, or environment in the shipped CLI path.** `migrate.py:58` logs only the underlying retry exception’s class name. At lines 65–74, `direction` is selected by code, `target` is the supplied CLI revision argument, `from_revision` and `revision` are version IDs, `applied` contains only revision IDs and rounded durations, and the three scalar timing fields are numbers. The skip event contains a checked revision and a constant reason (`migrate.py:29–43,97–99`; `cmapi/src/cmapi/core/db/__init__.py:90,135–140`). The URL is used for connections and Alembic configuration (`migrate.py:34,49,85–89`; `migrations/env.py:13–16`).

This is a field-provenance result, **not a redaction guarantee**. `target` is passed through as supplied. Structlog merges bound context variables, adds level and timestamp, processes explicitly supplied stack/exception information and renders JSON; it installs no general secret scrubber (`observability.py:114–127`). The fresh migrator entry point does not bind settings or request context. My CLI probes used a sentinel DSN password and unrelated environment secret; neither appeared. Unhandled exceptions still print their own diagnostic text, and `0008` intentionally names affected request IDs on refusal (`0008_idempotency_key_of_the_caller.py:66–85`). That stderr diagnostic is distinct from the fields of `migrated`.

**Confirmed — Alembic WARNING and ERROR survive; INFO progress is lost.** The threshold at `migrate.py:79–82` suppresses Alembic’s implementation/transaction-mode messages and the **pre-step** `Running …` message (`runtime/migration.py:205–215,611–616`). The success summary recovers completed revision IDs but cannot tell an operator which step a currently stuck or subsequently failed command had just started. This is useful information the suppression removes **where INFO had previously been enabled**. The base INI declares an INFO Alembic logger, but the base `env.py` does not call `fileConfig`; the INI declaration alone is not evidence that every base CLI invocation printed those lines (`cmapi/src/cmapi/core/db/alembic.ini:16–28`; `base/cmapi/src/cmapi/core/db/migrations/env.py:13–44`). In an injected-logger probe, INFO disappeared, WARNING and ERROR remained plain text, and an uncaught exception still printed its traceback and exited 1.

**Confirmed — the success event itself is one JSON line on stdout and the container selector is correct.** `observability.py:119–124` selects `JSONRenderer` and `PrintLoggerFactory(sys.stdout)`; the installed renderer defaults to `json.dumps` at `structlog/processors.py:339`, and `PrintLogger` writes one flushed line at `structlog/_output.py:113`. Both Helm workloads name the init container `migrate` and invoke `cmapi-migrate head` (`deploy/helm/cmapi/templates/api.yaml:29–35`; `deploy/helm/cmapi/templates/worker.yaml:27–33`). The rendered-chart test `test_second_pass.py::test_both_workloads_migrate_before_they_start` **passed**. The process probe also produced a single parseable success line. Thus `oc logs <pod> -c migrate` selects the intended container. A stream containing a standard-library warning or traceback can contain additional non-JSON lines.

**Collector compatibility is unverified.** `docs/12-existing-postgresql.md:110–116` names `oc logs`; it names no log stack, parser, field mapping, or collector configuration. There is evidence for newline-delimited JSON at the producer. There is no basis in that section to certify ingestion by a particular stack, and I did not run a cluster ingestion test.

## Coordinator rerun

Eight selected tests could not enter their PostgreSQL scenarios because connecting to `127.0.0.1:55432` returned `Operation not permitted`. The ninth was refused at its local listener `bind()` at `test_second_pass.py:494`. These results are environment blocks, not passing tests or evidence of a migration defect. Exact node IDs:

```text
cmapi/tests/service/test_migrate_log_614.py::test_a_run_that_applies_two_revisions_names_them_in_order_with_their_times
cmapi/tests/service/test_migrate_log_614.py::test_a_run_at_head_says_it_applied_nothing
cmapi/tests/service/test_migrate_log_614.py::test_a_run_from_an_empty_database_starts_from_none
cmapi/tests/service/test_migrate_log_614.py::test_a_downgrade_names_the_revisions_it_undid
cmapi/tests/service/test_migrate_log_614.py::test_the_lock_wait_is_the_time_spent_behind_the_other_migrator
cmapi/tests/service/test_second_pass.py::test_migrate_gives_up_behind_a_long_transaction_instead_of_stalling_every_reader
cmapi/tests/service/test_second_pass.py::test_a_migration_that_fails_leaves_the_last_good_revision_and_the_lock_free
cmapi/tests/service/test_second_pass.py::test_migrate_twice_is_a_no_op
cmapi/tests/service/test_second_pass.py::test_migrate_waits_for_a_database_that_is_not_up_yet
```

[exited with code 0]
