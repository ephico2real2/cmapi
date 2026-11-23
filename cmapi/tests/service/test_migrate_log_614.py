"""#614: cmapi-migrate logs, in one JSON line per run, what it applied and how long it took.

Before the fix it printed `migrated to head` whether it applied no revision or several, so the log could not say which of
the two migrators (the api's and the worker's) applied 0008, or how long it held the locks that docs/12 asks a site to
measure. Alembic calls `on_version_apply` "after the respective operation has been applied but before its transaction is
finalized" (https://alembic.sqlalchemy.org/en/latest/api/runtime.html, read 2026-11-23); env.py times each step with it.
"""
from __future__ import annotations

import json
import time

import psycopg

from conftest import DB_URL
from test_review_h_tools_migrate import empty_schema, migrate  # noqa: F401 - empty_schema is a fixture

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
    _migrated("0006", url=empty_schema)
    e = _migrated("head", url=empty_schema)
    assert e["level"] == "info" and e["timestamp"]
    assert (e["direction"], e["target"], e["from_revision"], e["revision"]) == ("upgrade", "head", "0006", REQUIRED_REVISION)
    assert [s["revision"] for s in e["applied"]] == ["0007", "0008"]
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
    _migrated("head", url=empty_schema)
    e = _migrated("0006", "--downgrade", url=empty_schema)
    assert (e["direction"], e["from_revision"], e["revision"]) == ("downgrade", REQUIRED_REVISION, "0006")
    assert [s["revision"] for s in e["applied"]] == ["0008", "0007"]


def test_the_lock_wait_is_the_time_spent_behind_the_other_migrator(empty_schema):
    """The other migrator holds the advisory lock; this one waits for it, and says so."""
    held = 1.5
    other = psycopg.connect(DB_URL, autocommit=True)
    other.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_KEY,))
    p = migrate(empty_schema, "head")
    try:
        deadline = time.monotonic() + 60
        while not other.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = %s AND NOT granted",
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

