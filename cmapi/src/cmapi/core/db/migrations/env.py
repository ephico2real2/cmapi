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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
