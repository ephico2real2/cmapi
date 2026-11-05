"""`cmapi-migrate`: run the Alembic migrations to head. The chart runs it as an initContainer on the api and the
worker (expand then contract, so old and new replicas run together; serialised by the lock in migrations/env.py).

A database already past this code's history is not an error: migrations are expand-only, /readyz treats it as past,
and a rollback of the image must be able to start."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, pool
from sqlalchemy.exc import OperationalError

from cmapi.core.db import sqlalchemy_url
from cmapi.settings import settings


def _compatible_future(url: str) -> str | None:
    """The database's revision when it is a later release's, by the four-digit convention, else None. A revision
    this code does not know and cannot place (garbage, a divergent branch) exits non-zero: the pod must not start."""
    from cmapi.core.db import known_revision, older_than_required

    engine = create_engine(sqlalchemy_url(url), poolclass=pool.NullPool)
    with engine.connect() as c:
        current = MigrationContext.configure(c).get_current_revision()
    if current is None or known_revision(current):
        return None
    try:
        older_than_required(current)
    except ValueError as exc:
        sys.exit(f"refusing to migrate: {exc}")
    return current


def _wait_for_database(url: str, seconds: float) -> None:
    """A database not up yet is what a first install looks like. Waiting here keeps the initContainer running; exiting
    would put it in kubelet's crash backoff, which can outlast helm's --wait timeout after the database has come up."""
    engine = create_engine(sqlalchemy_url(url), poolclass=pool.NullPool)
    deadline = time.monotonic() + seconds
    while True:
        try:
            with engine.connect():
                return
        except OperationalError as exc:
            if time.monotonic() >= deadline:
                raise
            print(f"waiting for the database: {type(exc.orig).__name__}", flush=True)
            time.sleep(min(5.0, seconds))


def run(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not settings().database_url:
        sys.exit("CMAPI_DATABASE_URL is not set")
    url = os.environ.get("CMAPI_DATABASE_URL") or settings().database_url
    # Under helm --wait --timeout 10m: the database may take minutes on a loaded node, and an exit here would put the
    # initContainer into kubelet's crash backoff (up to five minutes), which can outlast the install timeout.
    _wait_for_database(url, float(os.environ.get("CMAPI_MIGRATE_WAIT_SECONDS", "540")))
    cfg = Config(str(Path(__file__).parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    target = args[0] if args else "head"
    if args[1:] == ["--downgrade"]:
        command.downgrade(cfg, target)
    else:
        ahead = _compatible_future(url)
        if ahead:
            print(f"the database is at {ahead}, a later release's revision: nothing to do")
            return
        command.upgrade(cfg, target)
    print(f"migrated to {target}")


if __name__ == "__main__":
    run()
