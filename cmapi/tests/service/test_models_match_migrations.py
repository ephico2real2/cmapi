"""The SQLAlchemy models and the Alembic migrations describe one schema (#185).

`alembic check` fails when autogenerate would write an operation: a model with no migration, or a migration that the
models do not say. The first test is that command on the migrated test database. The others show that the comparison
can fail: a column, an index and a uniqueness that only the models have, and an index that only the database has.

What `alembic check` does not see, measured with Alembic 1.20.1 on PostgreSQL 16: the WHERE of a partial index. A changed
or a removed predicate gives no difference, and the columns and the expressions of an index do. Three unique indexes of
cmapi are partial, and their predicate is the rule (one OPEN request per namespace). So the last test makes the models'
schema beside the migrated one and compares the definition of each index as PostgreSQL writes it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.util import CommandError
from sqlalchemy import Column, Index, MetaData, String, text

from cmapi.core.db.models import Base

INI = Path(__file__).resolve().parents[2] / "src/cmapi/core/db/alembic.ini"


def differences(database, metadata: MetaData) -> list[str]:
    """Each operation that autogenerate would write, as `operation name`."""
    with database.engine.connect() as connection:
        found = compare_metadata(MigrationContext.configure(connection), metadata)
    out = []
    for item in found:
        for op in (item if isinstance(item, list) else [item]):
            subject = op[-1] if op[0].endswith("column") else op[1]
            out.append(f"{op[0]} {getattr(subject, 'name', subject)}")
    return sorted(out)


def copy_of_the_models() -> MetaData:
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    return metadata


def test_alembic_check_finds_no_difference_between_the_models_and_the_migrations(database):
    try:
        command.check(Config(str(INI)))
    except CommandError as exc:
        pytest.fail("the models and the migrations differ. A model change needs a migration, and each index of a migration is "
                    f"declared in core/db/models.py. alembic check: {exc}")
    assert differences(database, Base.metadata) == []


def test_a_column_that_only_the_models_have_is_found(database):
    metadata = copy_of_the_models()
    metadata.tables["approvals"].append_column(Column("only_in_the_models", String(200)))
    assert differences(database, metadata) == ["add_column only_in_the_models"]


def test_an_index_that_only_the_models_have_is_found(database):
    metadata = copy_of_the_models()
    Index("idx_cr_team", metadata.tables["change_requests"].c.team)
    assert differences(database, metadata) == ["add_index idx_cr_team"]


@pytest.mark.parametrize("name", ["uq_cr_open_namespace", "uq_cr_idempotency", "uq_approvals_person", "uq_jobs_pending", "idx_jobs_due"])
def test_an_index_of_the_migrations_that_the_models_do_not_declare_is_found(database, name):
    """The state before #185: autogenerate would have written a migration that drops the index."""
    metadata = copy_of_the_models()
    table = next(t for t in metadata.tables.values() if any(i.name == name for i in t.indexes))
    table.indexes.remove(next(i for i in table.indexes if i.name == name))
    assert differences(database, metadata) == [f"remove_index {name}"]


def test_an_index_that_is_unique_only_in_the_database_is_found(database):
    metadata = copy_of_the_models()
    table = metadata.tables["approvals"]
    table.indexes.remove(next(i for i in table.indexes if i.name == "uq_approvals_person"))
    Index("uq_approvals_person", table.c.request_id, table.c.approver_sub)
    assert differences(database, metadata) == ["add_index uq_approvals_person", "remove_index uq_approvals_person"]


def index_definitions(connection, schema: str) -> dict[str, str]:
    rows = connection.execute(text("select indexname, indexdef from pg_indexes where schemaname = :s"), {"s": schema})
    return {name: definition.replace(f" ON {schema}.", " ON ") for name, definition in rows}


def models_schema_indexes(database, metadata: MetaData) -> tuple[dict[str, str], dict[str, str]]:
    """The index definitions of the migrated schema, and of a schema that is made from the models alone and then dropped."""
    scratch = "cmapi_models_check"
    with database.engine.connect() as connection:
        connection.execute(text(f"drop schema if exists {scratch} cascade"))
        connection.execute(text(f"create schema {scratch}"))
        try:
            metadata.create_all(connection.execution_options(schema_translate_map={None: scratch}))
            return index_definitions(connection, "public"), index_definitions(connection, scratch)
        finally:
            connection.execute(text(f"drop schema {scratch} cascade"))
            connection.commit()


def test_each_index_of_the_models_is_the_index_of_the_migrations_predicate_included(database):
    migrated, modelled = models_schema_indexes(database, Base.metadata)
    migrated.pop("alembic_version_pkc", None)
    assert modelled == migrated


def test_a_changed_predicate_of_a_partial_index_is_found_where_alembic_check_is_blind(database):
    metadata = copy_of_the_models()
    table = metadata.tables["jobs"]
    table.indexes.remove(next(i for i in table.indexes if i.name == "idx_jobs_due"))
    Index("idx_jobs_due", table.c.run_after)                       # the predicate `done_at IS NULL` is gone
    assert differences(database, metadata) == [], "alembic check sees it now: this test and the note above are out of date"
    migrated, modelled = models_schema_indexes(database, metadata)
    assert modelled["idx_jobs_due"] != migrated["idx_jobs_due"] and "WHERE" not in modelled["idx_jobs_due"]
