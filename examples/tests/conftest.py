"""Shared fixtures. Run from examples/:  PYTHONPATH=src python -m pytest -q"""
from pathlib import Path

import pytest

from cmapi.core.identity.claims import Identity

EX = Path(__file__).resolve().parent.parent
ALL_ENVS = {"rnd", "dev", "qa", "uat", "prod"}
INSTANCES = {"nonprod": {"rnd", "dev"}, "staging": {"qa", "uat"}, "prod": {"prod"}}


def person(username, *, roles=(), groups=(), kind="user", client="cmapi-portal", employee_id="E100", sub=None):
    return Identity(sub=sub or f"sub-{username}", username=username, kind=kind, client_id=client,
                    email=f"{username}@ephico2real.com", given_name=username.title(), family_name="Doe",
                    employee_id=employee_id, roles=frozenset(roles), groups=frozenset(groups))


@pytest.fixture
def ex() -> Path:
    return EX
