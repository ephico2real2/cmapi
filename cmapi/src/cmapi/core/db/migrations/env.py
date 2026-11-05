"""Alembic environment: the URL comes from CMAPI_DATABASE_URL, the metadata from the models."""
from __future__ import annotations

import os

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
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # Serialises concurrent migrators; PostgreSQL's transactional DDL makes each one all or nothing.
        connection.exec_driver_sql("SELECT pg_advisory_lock(727364)")
        # DDL waiting behind an old pod's open transaction queues every later query on that table behind it. Give up
        # instead: the process exits non-zero, the lock goes with the connection, and the initContainer tries again.
        lock_timeout = os.environ.get("CMAPI_MIGRATE_LOCK_TIMEOUT", "30s")
        connection.exec_driver_sql(f"SET lock_timeout = '{int(lock_timeout.rstrip('s'))}s'")
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
