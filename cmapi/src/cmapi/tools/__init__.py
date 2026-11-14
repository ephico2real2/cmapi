"""`cmapi-tools`: the one-time and repeatable setup steps the chart runs as Jobs.

    cmapi-tools git-bootstrap   the Git host stand-in: bot user, org, repository, seed, branch protection
    cmapi-tools realm-sync      the realm's mutable parts through the cmapi-realm-admin client
    cmapi-tools docs-assets     Swagger UI and ReDoc for a source checkout, at the Containerfile's versions and hashes
    cmapi-tools policies        the Kyverno bundle rendered from an instance's configuration, and its check (#212)

Each is idempotent: a second run changes nothing and exits 0.
"""
from __future__ import annotations

import importlib
import sys

# Each command's module is imported only when it runs: git-bootstrap needs the database layer, policies needs none, and
# a command must not fail on another's dependencies.
COMMANDS = {"git-bootstrap": "cmapi.tools.git_bootstrap", "realm-sync": "cmapi.tools.realm_sync",
            "docs-assets": "cmapi.tools.docs_assets", "policies": "cmapi.tools.policies"}


def run(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in COMMANDS:
        sys.exit(f"usage: cmapi-tools {{{'|'.join(COMMANDS)}}}")
    importlib.import_module(COMMANDS[args[0]]).main(args[1:])


if __name__ == "__main__":
    run()
