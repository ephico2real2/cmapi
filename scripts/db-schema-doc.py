#!/usr/bin/env python3
"""Print the tables of the cmapi database as Markdown, read from a live database at the migrations' head.

    CMAPI_DATABASE_URL=postgresql://... python scripts/db-schema-doc.py [schema]

docs/16-data-model.md holds this output between its two marker lines, and the service suite fails when the two differ
(tests/service/test_data_model_doc.py). So the document cannot drift from the migrations. Needs psycopg, as the service does.
"""
from __future__ import annotations

import os
import sys

import psycopg

COLUMNS = """
select c.table_name, c.column_name,
       case when c.data_type = 'character varying' then 'varchar(' || c.character_maximum_length || ')'
            when c.data_type = 'timestamp with time zone' then 'timestamptz' else c.data_type end,
       c.is_nullable, coalesce(c.column_default, '')
from information_schema.columns c
where c.table_schema = %s and c.table_name <> 'alembic_version'
order by c.table_name, c.ordinal_position"""
INDEXES = """
select tablename, indexname, indexdef from pg_indexes
where schemaname = %s and tablename <> 'alembic_version' order by tablename, indexname"""
CONSTRAINTS = """
select rel.relname, con.conname, con.contype, pg_get_constraintdef(con.oid)
from pg_constraint con join pg_class rel on rel.oid = con.conrelid join pg_namespace n on n.oid = rel.relnamespace
where n.nspname = %s and rel.relname <> 'alembic_version' and con.contype in ('p', 'f', 'c', 'u')
order by rel.relname, con.contype, con.conname"""
KINDS = {"p": "Primary key", "f": "Foreign key", "c": "Check", "u": "Unique"}


def render(url: str, schema: str = "public") -> str:
    out: list[str] = []
    with psycopg.connect(url) as conn:
        columns, indexes, constraints = ({}, {}, {})
        for table, *rest in conn.execute(COLUMNS, (schema,)):
            columns.setdefault(table, []).append(rest)
        for table, name, definition in conn.execute(INDEXES, (schema,)):
            indexes.setdefault(table, []).append((name, definition))
        for table, name, kind, definition in conn.execute(CONSTRAINTS, (schema,)):
            constraints.setdefault(table, []).append((name, kind, definition))
        version = conn.execute(f'select version_num from "{schema}".alembic_version').fetchone()[0]
    out.append(f"Migration head: `{version}`. Tables: {len(columns)}.")
    for table in sorted(columns):
        out += ["", f"### `{table}`", "", "| Column | Type | Null | Default |", "|---|---|---|---|"]
        for name, kind, nullable, default in columns[table]:
            out.append(f"| `{name}` | {kind} | {'yes' if nullable == 'YES' else 'no'} | {('`' + default + '`') if default else ''} |")
        out += ["", "| Constraint or index | Kind | Definition |", "|---|---|---|"]
        named = set()
        for name, kind, definition in constraints.get(table, []):
            named.add(name)
            out.append(f"| `{name}` | {KINDS[kind]} | `{definition}` |")
        for name, definition in indexes.get(table, []):
            if name in named:
                continue                        # the index that backs a primary key or a unique constraint
            what = definition.split(" USING ", 1)[1].replace(f"{schema}.", "")
            out.append(f"| `{name}` | {'Unique index' if definition.startswith('CREATE UNIQUE') else 'Index'} | `{what}` |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    url = os.environ.get("CMAPI_DATABASE_URL")
    if not url:
        sys.exit("db-schema-doc: set CMAPI_DATABASE_URL")
    sys.stdout.write(render(url, sys.argv[1] if len(sys.argv) > 1 else "public"))
