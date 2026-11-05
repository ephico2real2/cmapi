"""PostgreSQL: the engine, sessions and the ORM models (docs/01, Data model).

The database records history and decisions; it never holds a cluster's desired state. One
engine per process, sessions per request or per job.
"""
from __future__ import annotations

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
        return "ok" if not older_than_required(version) else f"behind: at {version}, needs {REQUIRED_REVISION}"


REQUIRED_REVISION = "0003"


def older_than_required(version: str) -> bool:
    """Whether a revision is a strict ancestor of REQUIRED_REVISION in the migration history."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    here = Path(__file__).parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    ancestors = {r.revision for r in script.iterate_revisions(REQUIRED_REVISION, "base")} - {REQUIRED_REVISION}
    return version in ancestors
