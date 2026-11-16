"""Review of PR #272 (#271): the one-session-per-database lock, for the URL shapes and invocations its own test leaves out.

Each test starts a second service-test session while this one holds the database (conftest takes the lock at session
start), and reads what that second session printed and returned. Copy into cmapi/tests/service/ and run from cmapi/.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

import conftest
from conftest import DB_URL

HERE = Path(__file__).resolve().parent
CMAPI = HERE.parents[1]
MARKER = "test_one_session_per_database.py::test_inner_session_marker"
PARTS = conninfo_to_dict(DB_URL)
HOST, PORT, DB, USER, PASSWORD = (PARTS.get(k, "") for k in ("host", "port", "dbname", "user", "password"))


def second_session(url: str, *args: str) -> tuple[int, str]:
    env = {**os.environ, "CMAPI_TEST_DATABASE_URL": url, "CMAPI_TEST_INNER_SESSION": "1"}
    r = subprocess.run([sys.executable, "-m", "pytest", *args, "-q", "-s", "-p", "no:cacheprovider"],
                       cwd=CMAPI, env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("url", [
    f"postgresql://{USER}@{HOST}:{PORT}/{DB}?password={PASSWORD}",
    f"postgresql:///{DB}?host={HOST}&port={PORT}&user={USER}&password={PASSWORD}",
], ids=["password-in-query", "no-at-sign"])
def test_the_refusal_never_prints_a_password_given_in_the_query(database, url):
    rc, out = second_session(url, str(HERE / MARKER))
    assert rc == conftest.SESSION_LOCK_EXIT, out
    assert "another service-test session holds the database" in out, out
    assert f"password={PASSWORD}" not in out, "the refusal printed the password"


def test_a_sqlalchemy_style_url_is_refused_by_name_not_an_internal_error(database):
    rc, out = second_session(f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB}", str(HERE / MARKER))
    assert "INTERNALERROR" not in out, out
    assert f"{USER}:{PASSWORD}@" not in out, "the session start printed the credentials"
    assert rc == conftest.SESSION_LOCK_EXIT, out
    assert "INNER SESSION RAN A TEST" not in out, out


def test_the_refusal_exit_code_is_not_one_of_pytests_own():
    assert conftest.SESSION_LOCK_EXIT not in {int(c) for c in pytest.ExitCode}, \
        "a refusal must not read as pytest's internal error, usage error or interruption"


def test_a_session_started_on_the_tests_folder_is_refused_too(database):
    """`pytest tests` from cmapi/ loads tests/service/conftest.py during collection, after pytest_sessionstart has run."""
    rc, out = second_session(DB_URL, "tests", "--ignore=tests/core", "-k", "test_inner_session_marker")
    assert "INNER SESSION RAN A TEST" not in out, out
    assert rc == conftest.SESSION_LOCK_EXIT, out
    assert "another service-test session holds the database" in out, out
