"""#603 lock probe: while the real cmapi-migrate runs 0009 (up, then down), paused for 4 s inside its transaction after
its checks, before its first UPDATE, another session's SELECT and UPDATE on change_requests under a 100 ms lock_timeout, and
pg_locks for the migrator's lock on the table. Run from cmapi/ with PYTHONPATH=src and CMAPI_PROBE_URL set."""
import os
import subprocess
import sys
import time

import psycopg

BASE = os.environ["CMAPI_PROBE_URL"]
URL = BASE + "?options=-csearch_path%3Dlock603"
PAUSED = """
import sys, time
from sqlalchemy import event
from sqlalchemy.engine import Engine
from cmapi.core.db.migrate import run

@event.listens_for(Engine, "before_cursor_execute")
def _pause(conn, cursor, statement, *args):
    if statement.startswith(sys.argv[1]):
        print("paused", flush=True)
        time.sleep(4)

run(sys.argv[2:])
"""


def migrate(*args):
    p = subprocess.run([sys.executable, "-c", "import sys; from cmapi.core.db.migrate import run; run(sys.argv[1:])", *args],
                       env={**os.environ, "CMAPI_DATABASE_URL": URL}, capture_output=True, text=True)
    assert p.returncode == 0, (p.stdout + p.stderr)[-800:]


def probe(statement, *args):
    p = subprocess.Popen([sys.executable, "-c", PAUSED, statement, *args], env={**os.environ, "CMAPI_DATABASE_URL": URL},
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert p.stdout.readline().strip() == "paused"
    print(f"cmapi-migrate {' '.join(args)}: paused before {statement!r}")
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("SET lock_timeout = '100ms'")
        for sql in ("SELECT count(*) FROM change_requests", "UPDATE change_requests SET attempts = attempts"):
            try:
                c.execute(sql)
                print(f"  {sql}: ran (not blocked)")
            except psycopg.errors.LockNotAvailable as exc:
                print(f"  {sql}: {exc.sqlstate} {type(exc).__name__}")
        locks = c.execute("SELECT mode, granted FROM pg_locks WHERE relation = 'lock603.change_requests'::regclass "
                          "AND pid <> pg_backend_pid() ORDER BY mode").fetchall()
        print(f"  pg_locks on change_requests, other sessions: {locks}")
    out = p.communicate(timeout=60)[0]
    print(f"  migrator exit {p.returncode}: {[l for l in out.splitlines() if 'migrated' in l][0][:120]}")


with psycopg.connect(BASE, autocommit=True) as c:
    c.execute("DROP SCHEMA IF EXISTS lock603 CASCADE")
    c.execute("CREATE SCHEMA lock603")
migrate("0008")
probe("UPDATE change_requests SET idempotency_key = NULL", "head")
probe("UPDATE change_requests SET idempotency_key = NULL", "0008", "--downgrade")
with psycopg.connect(BASE, autocommit=True) as c:
    c.execute("DROP SCHEMA lock603 CASCADE")
