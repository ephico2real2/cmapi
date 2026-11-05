"""`cmapi-tools`: the one-time and repeatable setup steps the chart runs as Jobs.

    cmapi-tools git-bootstrap   the Git host stand-in: bot user, org, repository, seed, branch protection
    cmapi-tools realm-sync      the realm's mutable parts through the cmapi-realm-admin client

Both are idempotent: a second run changes nothing and exits 0.
"""
from __future__ import annotations

import sys

from cmapi.tools.git_bootstrap import main as git_bootstrap
from cmapi.tools.realm_sync import main as realm_sync

COMMANDS = {"git-bootstrap": git_bootstrap, "realm-sync": realm_sync}


def run(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        sys.exit(f"usage: cmapi-tools {{{'|'.join(COMMANDS)}}}")
    COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    run()
