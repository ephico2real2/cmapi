"""PostgreSQL: the engine, sessions and the ORM models (docs/01, Data model).

The database records history and decisions; it never holds a cluster's desired state. One
engine per process, sessions per request or per job.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def sqlalchemy_url(url: str) -> str:
    """CloudNativePG hands out postgresql://; SQLAlchemy wants the psycopg driver named."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


def make_engine(url: str, pool_size: int = 5) -> Engine:
    engine = create_engine(sqlalchemy_url(url), pool_size=pool_size, max_overflow=5, pool_pre_ping=True,
                           pool_recycle=1800, future=True)

    @event.listens_for(engine, "connect")
    def _set_tz(dbapi_conn, _record):            # every timestamp read and written in UTC
        with dbapi_conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")

    return engine


class Database:
    def __init__(self, url: str, pool_size: int = 5):
        self.engine = make_engine(url, pool_size)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False, future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._sessions()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def ping(self) -> str:
        try:
            with self.engine.connect() as c:
                c.exec_driver_sql("SELECT 1")
            return "ok"
        except Exception as exc:                                 # noqa: BLE001
            return type(exc).__name__

    def schema_version(self) -> str | None:
        """The Alembic revision the database is at; None when the version table does not exist yet."""
        with self.engine.connect() as c:
            try:
                return c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
            except Exception:                                    # noqa: BLE001 - UndefinedTable: never migrated
                return None

    def schema_status(self) -> str:
        """ok when the schema is at or past the revision this code needs (an unknown, newer revision from a later
        release counts as past: migrations are expand-only). An older or absent schema is not ready: the pods'
        migrate initContainer brings it forward, and readiness waits for it."""
        try:
            version = self.schema_version()
        except Exception as exc:                                 # noqa: BLE001
            return type(exc).__name__
        if version is None:
            return "not-migrated"
        try:
            return "ok" if not older_than_required(version) else f"behind: at {version}, needs {REQUIRED_REVISION}"
        except ValueError as exc:                                # garbage, or a divergent history: not ready
            return str(exc)


REQUIRED_REVISION = "0003"


FUTURE_REVISION = re.compile(r"([0-9]{4})(?:_[a-z0-9_]+)?")   # the repository's convention: four digits, counting up


def script_directory():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    here = Path(__file__).parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    return ScriptDirectory.from_config(cfg)


def known_revision(version: str) -> bool:
    # ScriptDirectory wraps the map's ResolutionError in CommandError; a partial id shorter than four characters
    # raises the same way.
    from alembic.script.revision import ResolutionError
    from alembic.util.exc import CommandError

    if not version:                                     # alembic asserts on an empty id instead of raising
        return False
    try:
        revision = script_directory().get_revision(version)
    except (ResolutionError, CommandError):
        return False
    # get_revision also resolves symbols ("head", "base", "0003@head"): a database holds the exact id of a migration.
    return revision is not None and revision.revision == version


def older_than_required(version: str) -> bool:
    """Whether the database's revision is a strict ancestor of REQUIRED_REVISION.

    False for REQUIRED_REVISION itself, for a known descendant, and for an unknown revision that follows the
    four-digit convention with a higher number (a later release migrated; migrations are expand-only, so this
    code runs on it). ValueError for anything else: a known revision on a divergent branch, or garbage, which
    must never read as ready."""
    script = script_directory()
    if known_revision(version):
        ancestors = {r.revision for r in script.iterate_revisions(REQUIRED_REVISION, "base")}
        if version in ancestors:
            return version != REQUIRED_REVISION
        if REQUIRED_REVISION in {r.revision for r in script.iterate_revisions(version, "base")}:
            return False
        raise ValueError(f"schema revision {version} is on a divergent branch")
    m = FUTURE_REVISION.fullmatch(version)
    need = int(REQUIRED_REVISION[:4])
    if m and int(m.group(1)) > need:
        return False
    raise ValueError(f"unknown schema revision {version!r}")
