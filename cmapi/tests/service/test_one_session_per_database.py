"""#271: a second service-test session on the database this session holds is refused at once, by name.

Two sessions on one database truncate each other's request tables (conftest.fresh_db): on 2026-11-15 a concurrent
before-run deleted a request 89 ms after test_fable_review_240 created it, and the approve answered 404. This session
holds the advisory lock (conftest.pytest_sessionstart), so a second session started now must stop before any test runs.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import DB_URL

HERE = Path(__file__).resolve().parent
INNER = "CMAPI_TEST_INNER_SESSION"
REFUSED = 3  # conftest.SESSION_LOCK_EXIT, spelled out so that this test also runs against a conftest without the lock


def test_a_second_session_on_the_same_database_is_refused_before_any_test(database):
    env = {**os.environ, "CMAPI_TEST_DATABASE_URL": DB_URL, INNER: "1"}
    r = subprocess.run([sys.executable, "-m", "pytest", f"{HERE / 'test_one_session_per_database.py'}::test_inner_session_marker",
                        "-q", "-s", "-p", "no:cacheprovider"],
                       cwd=HERE.parents[1], env=env, capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == REFUSED, out
    assert "another service-test session holds the database" in out, out
    assert "INNER SESSION RAN A TEST" not in out, out
    assert "cmapi:cmapi@" not in out, "the refusal printed the credentials"


def test_inner_session_marker():
    """Run only by the second session above: if that session gets this far, it was not refused."""
    if os.environ.get(INNER):
        print("INNER SESSION RAN A TEST")
