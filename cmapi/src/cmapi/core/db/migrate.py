"""`cmapi-migrate`: run the Alembic migrations to head. The chart runs it as a pre-upgrade Job
(expand then contract, so old and new replicas run together)."""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from cmapi.settings import settings


def run(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not settings().database_url:
        sys.exit("CMAPI_DATABASE_URL is not set")
    cfg = Config(str(Path(__file__).parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    target = args[0] if args else "head"
    if args[1:] == ["--downgrade"]:
        command.downgrade(cfg, target)
    else:
        command.upgrade(cfg, target)
    print(f"migrated to {target}")


if __name__ == "__main__":
    run()
