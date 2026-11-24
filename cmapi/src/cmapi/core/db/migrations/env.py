"""Alembic environment: the URL comes from CMAPI_DATABASE_URL, the metadata from the models."""
from __future__ import annotations

import os
import time

from alembic import context
from sqlalchemy import engine_from_config, pool

from cmapi.core.db import sqlalchemy_url
from cmapi.core.db.models import Base

config = context.config
url = os.environ.get("CMAPI_DATABASE_URL") or config.get_main_option("sqlalchemy.url") or ""
config.set_main_option("sqlalchemy.url", sqlalchemy_url(url).replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # What cmapi-migrate logs (#614). Config.attributes is Alembic's dictionary "to pass objects into an env.py script";
    # a plain `alembic` command gets one that nobody reads.
    run = config.attributes.setdefault("cmapi.run", {})
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # Serialises concurrent migrators; PostgreSQL's transactional DDL makes each one all or nothing.
        asked = time.perf_counter()
        connection.exec_driver_sql("SELECT pg_advisory_lock(727364)")
        run["lock_wait_seconds"] = time.perf_counter() - asked
        # DDL waiting behind an old pod's open transaction queues every later query on that table behind it. Give up
        # instead: the process exits non-zero, the lock goes with the connection, and the initContainer tries again.
        lock_timeout = os.environ.get("CMAPI_MIGRATE_LOCK_TIMEOUT", "30s")
        connection.exec_driver_sql(f"SET lock_timeout = '{int(lock_timeout.rstrip('s'))}s'")
        connection.commit()
        steps = run["steps"] = []
        last = 0.0

        def applied(*, step, heads, **_) -> None:
            # Alembic calls this after each revision's upgrade() or downgrade() and its alembic_version update, before
            # the transaction commits. So a step's time runs from the previous step's end, and the first's from the
            # read of the starting revision, to here: one revision's own work inside the shared transaction.
            nonlocal last
            now = time.perf_counter()
            steps.append({"revision": step.up_revision_id, "seconds": now - last, "heads": sorted(heads)})
            last = now

        context.configure(connection=connection, target_metadata=target_metadata, on_version_apply=applied)
        begun = time.perf_counter()
        with context.begin_transaction():
            run["from_revision"] = context.get_context().get_current_revision()
            last = time.perf_counter()
            context.run_migrations()
        # A table lock that a revision takes is held until this commit, so the transaction's time bounds how long it is held.
        run["transaction_seconds"] = time.perf_counter() - begun


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
