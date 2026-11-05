"""Shared fixtures. Run from cmapi/:  PYTHONPATH=src:tests/core python -m pytest -q tests/core

The config files these tests read live in examples/ (config, instances, cluster-configs), found by
walking up from this file to the repository root. The tests are also reachable through the
examples/tests symlink; Path.resolve() follows it, so both entry points land here.
"""
from pathlib import Path

import pytest

from cmapi.core.identity.claims import Identity

EX = next(p / "examples" for p in Path(__file__).resolve().parents if (p / "examples" / "config").is_dir())
ALL_ENVS = {"rnd", "dev", "qa", "uat", "prod"}
INSTANCES = {"nonprod": {"rnd", "dev"}, "staging": {"qa", "uat"}, "prod": {"prod"}}


def person(username, *, roles=(), groups=(), kind="user", client="cmapi-portal", employee_id="E100", sub=None):
    return Identity(sub=sub or f"sub-{username}", username=username, kind=kind, client_id=client,
                    email=f"{username}@ephico2real.com", given_name=username.title(), family_name="Doe",
                    employee_id=employee_id, roles=frozenset(roles), groups=frozenset(groups))


@pytest.fixture
def ex() -> Path:
    return EX
