"""#614: cmapi-migrate logs, in one JSON line per run, what it applied and how long it took.

Before the fix it printed `migrated to head` whether it applied no revision or several, so the log could not say which of
the two migrators (the api's and the worker's) applied 0008, or how long it held the locks that docs/12 asks a site to
measure. Alembic calls `on_version_apply` "after the respective operation has been applied but before its transaction is
finalized" (https://alembic.sqlalchemy.org/en/latest/api/runtime.html, read 2026-11-23); env.py times each step with it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import psycopg

from conftest import DB_URL
from test_review_h_tools_migrate import ROOT, empty_schema, migrate  # noqa: F401 - empty_schema is a fixture

from cmapi.core.db import REQUIRED_REVISION

ADVISORY_KEY = 727364  # migrations/env.py


def _migrated(*args, url):
    """The `migrated` event of one run, after checking that the run succeeded and that every line it wrote is a JSON event,
    as the api's and the worker's are: Alembic's own text lines must not mix in."""
    p = migrate(url, *args)
    out = p.communicate(timeout=120)[0]
    assert p.returncode == 0, out[-800:]
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    found = [e for e in events if e.get("event") == "migrated"]
    assert len(found) == 1, out[-800:]
    return found[0]


def _seconds(value):
    assert isinstance(value, float) and value >= 0, value
    return value


def test_a_run_that_applies_two_revisions_names_them_in_order_with_their_times(empty_schema):
    _migrated("0007", url=empty_schema)
    e = _migrated("0009", url=empty_schema)
    assert e["level"] == "info" and e["timestamp"]
    assert (e["direction"], e["target"], e["from_revision"], e["revision"]) == ("upgrade", "0009", "0007", "0009")
    assert [s["revision"] for s in e["applied"]] == ["0008", "0009"]
    steps = sum(_seconds(s["seconds"]) for s in e["applied"])
    lock_wait, transaction, total = (_seconds(e[k]) for k in ("lock_wait_seconds", "transaction_seconds", "total_seconds"))
    # Each step lies inside the one transaction, and the transaction and the lock wait inside the run (rounded to 1 ms).
    assert steps <= transaction + 0.002 and lock_wait + transaction <= total + 0.002, e


def test_a_run_at_head_says_it_applied_nothing(empty_schema):
    _migrated("head", url=empty_schema)
    e = _migrated("head", url=empty_schema)
    assert (e["from_revision"], e["revision"], e["applied"]) == (REQUIRED_REVISION, REQUIRED_REVISION, [])


def test_a_run_from_an_empty_database_starts_from_none(empty_schema):
    e = _migrated("head", url=empty_schema)
    assert e["from_revision"] is None and e["applied"][0]["revision"] == "0001" and e["applied"][-1]["revision"] == REQUIRED_REVISION


def test_a_downgrade_names_the_revisions_it_undid(empty_schema):
    _migrated("0009", url=empty_schema)
    e = _migrated("0007", "--downgrade", url=empty_schema)
    assert (e["direction"], e["from_revision"], e["revision"]) == ("downgrade", "0009", "0007")
    assert [s["revision"] for s in e["applied"]] == ["0009", "0008"]


def test_the_lock_wait_is_the_time_spent_behind_the_other_migrator(empty_schema):
    """The other migrator holds the advisory lock; this one waits for it, and says so."""
    held = 1.5
    other = psycopg.connect(DB_URL, autocommit=True)
    other.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_KEY,))
    p = migrate(empty_schema, "head")
    try:
        deadline = time.monotonic() + 60
        while not other.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = %s AND NOT granted "
                                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())",
                                (ADVISORY_KEY,)).fetchone()[0]:
            assert time.monotonic() < deadline and p.poll() is None, "the migrator never waited on the advisory lock"
            time.sleep(0.05)
        time.sleep(held)
    finally:
        other.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_KEY,))
        other.close()
    out = p.communicate(timeout=120)[0]
    assert p.returncode == 0, out[-800:]
    e = next(json.loads(line) for line in out.splitlines() if '"migrated"' in line)
    assert e["lock_wait_seconds"] >= held, e
    assert e["total_seconds"] >= e["lock_wait_seconds"] + e["transaction_seconds"] - 0.002, e


# Run the real cmapi-migrate with known delays: 0008's index build and 0009's DROP INDEX, inside their steps and the transaction,
# and every commit. The last commit ends the transaction; the setup commit before it falls in the total only. SQLAlchemy
# 2.1's "commit" event runs before the driver's commit: "Intercept commit() events, as initiated by a Transaction"
# (sqlalchemy/engine/events.py).
SLOW = """
import sys, time
from sqlalchemy import event
from sqlalchemy.engine import Engine
from cmapi.core.db.migrate import run

@event.listens_for(Engine, "before_cursor_execute")
def _slow_steps(conn, cursor, statement, *args):
    if statement.startswith("CREATE UNIQUE INDEX uq_cr_idempotency_caller"):              # 0008
        time.sleep(float(sys.argv[1]))
    if statement.lstrip().startswith("DROP INDEX uq_cr_idempotency"):                     # 0009, after a newline
        time.sleep(float(sys.argv[2]))

@event.listens_for(Engine, "commit")
def _slow_commit(conn):
    time.sleep(float(sys.argv[3]))

run(sys.argv[4:])
"""


def test_each_time_holds_its_own_work_and_the_transaction_ends_after_its_commit(empty_schema):
    """A step's seconds are its own revision's (not zero, not its neighbour's), and the transaction's include its commit:
    the table locks are held until then, which is what docs/12 reads the number for."""
    first, second, commit = 0.5, 1.0, 0.4
    _migrated("0007", url=empty_schema)
    env = {**os.environ, "CMAPI_DATABASE_URL": empty_schema, "PYTHONPATH": str(ROOT / "cmapi/src"), "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, "-c", SLOW, str(first), str(second), str(commit), "0009"], env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, (p.stdout + p.stderr)[-800:]
    e = json.loads(p.stdout)
    steps = {s["revision"]: s["seconds"] for s in e["applied"]}
    assert list(steps) == ["0008", "0009"], e
    assert first <= steps["0008"] < second <= steps["0009"] < second + first, e
    assert e["transaction_seconds"] >= steps["0008"] + steps["0009"] + commit, e
    assert e["lock_wait_seconds"] < commit, e
    assert e["total_seconds"] >= e["lock_wait_seconds"] + e["transaction_seconds"] + commit, e


def test_the_result_is_written_whatever_the_log_level(empty_schema, monkeypatch):
    """The api's CMAPI_LOG_LEVEL must not hide the migrator's one result, nor stop it before it migrates (#617 review)."""
    for level in ("WARNING", "not-a-level"):
        monkeypatch.setenv("CMAPI_LOG_LEVEL", level)
        assert _migrated("head", url=empty_schema)["revision"] == REQUIRED_REVISION
    monkeypatch.setenv("CMAPI_LOG_LEVEL", "WARNING")
    assert _migrated("0006", "--downgrade", url=empty_schema)["revision"] == "0006"


def _failed(*args, url, **env):
    p = subprocess.run([sys.executable, "-c", "import sys; from cmapi.core.db.migrate import run; run(sys.argv[1:])", *args],
                       capture_output=True, text=True, timeout=120,
                       env={**{k: v for k, v in os.environ.items() if k != "CMAPI_DATABASE_URL"}, **env,
                            "PYTHONPATH": str(ROOT / "cmapi/src"), "PYTHONDONTWRITEBYTECODE": "1",
                            **({"CMAPI_DATABASE_URL": url} if url else {})})
    assert p.returncode == 1, p.stdout + p.stderr[-800:]
    events = [json.loads(line) for line in p.stdout.splitlines()]
    assert [e["event"] for e in events] == ["migrate_failed"] and events[0]["level"] == "error", p.stdout
    return events[0], p.stderr


def test_a_failed_run_says_so_in_one_event_and_still_exits_with_its_diagnostic(empty_schema):
    e, err = _failed("missing-revision", url=empty_schema)
    assert (e["error"], e["sqlstate"]) == ("CommandError", None) and "Can't locate revision" in err
    e, err = _failed("head", url="")
    assert e["error"] == "SystemExit" and err.strip().splitlines()[-1] == "CMAPI_DATABASE_URL is not set"


def test_the_failure_event_never_carries_the_url_or_its_password():
    sentinel = "Sentinel-pw-617"
    for url in (f"postgresql://cmapi:{sentinel}@127.0.0.1:1/x", f"postgresql://cmapi:{sentinel}@127.0.0.1:notaport/x"):
        e, _ = _failed("head", url=url, CMAPI_MIGRATE_WAIT_SECONDS="0")
        assert set(e) == {"event", "error", "sqlstate", "level", "timestamp"} and sentinel not in json.dumps(e), e
