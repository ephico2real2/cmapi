"""docs/16-data-model.md holds the schema as scripts/db-schema-doc.py reads it from the migrated test database.
A migration that changes the schema without the document fails here."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from conftest import DB_URL

ROOT = Path(__file__).resolve().parents[3]


def test_the_data_model_document_is_the_schema_of_the_migrations(database):
    spec = importlib.util.spec_from_file_location("db_schema_doc", ROOT / "scripts" / "db-schema-doc.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    doc = (ROOT / "docs" / "16-data-model.md").read_text()
    begin, end = "<!-- schema:begin -->\n", "<!-- schema:end -->"
    assert begin in doc and end in doc, "docs/16-data-model.md has lost its marker lines"
    written = doc.split(begin, 1)[1].split(end, 1)[0]
    assert written == module.render(DB_URL), \
        "the schema changed: run scripts/db-schema-doc.py and replace the text between the marker lines of docs/16-data-model.md"
