"""`cmapi-migrate`: run the Alembic migrations to head. The chart runs it as an initContainer on the api and the
worker (expand then contract, so old and new replicas run together; serialised by the lock in migrations/env.py).

A database already past this code's history is not an error: migrations are expand-only, /readyz treats it as past,
and a rollback of the image must be able to start.

Each run writes one JSON event `migrated`, as the api's and the worker's are written (#614): the revision it started from,
each revision it applied in order with its seconds, the seconds it waited for the other migrator's advisory lock, the
seconds of the one transaction (the table locks are held until its commit), and the run's total. docs/12, section 4."""
from __future__ import annotations

import logging
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
from cmapi.core.observability import configure_logging, log
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
            log.info("waiting_for_database", error=type(exc.orig).__name__)
            time.sleep(min(5.0, seconds))


def _log_run(direction: str, target: str, measured: dict, started: float) -> None:
    """The run's one `migrated` event, from what migrations/env.py measured. Seconds are rounded to the millisecond, and
    the total runs from after the wait for the database to the end of the command."""
    steps = measured["steps"]
    revision = measured["from_revision"]
    if steps:
        heads = steps[-1]["heads"]                  # one head: the history is linear; none after a downgrade to base
        revision = heads[0] if heads else None
    log.info("migrated", direction=direction, target=target, from_revision=measured["from_revision"], revision=revision,
             applied=[{"revision": s["revision"], "seconds": round(s["seconds"], 3)} for s in steps],
             lock_wait_seconds=round(measured["lock_wait_seconds"], 3),
             transaction_seconds=round(measured["transaction_seconds"], 3),
             total_seconds=round(time.perf_counter() - started, 3))


def run(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    configure_logging(settings().log_level)
    # The `migrated` event carries what Alembic's INFO lines say ("Running upgrade 0007 -> 0008"), with the times; its
    # plain-text lines would break the JSON log that every other cmapi component writes.
    logging.getLogger("alembic").setLevel(logging.WARNING)
    if not settings().database_url:
        sys.exit("CMAPI_DATABASE_URL is not set")
    url = os.environ.get("CMAPI_DATABASE_URL") or settings().database_url
    # Under helm --wait --timeout 10m: the database may take minutes on a loaded node, and an exit here would put the
    # initContainer into kubelet's crash backoff (up to five minutes), which can outlast the install timeout.
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
        log.info("migrate_skipped", revision=ahead, reason="the database is at a later release's revision")
        return
    command.upgrade(cfg, target)
    _log_run("upgrade", target, cfg.attributes["cmapi.run"], started)


if __name__ == "__main__":
    run()
