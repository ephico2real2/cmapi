"""Shared fixtures. Run from cmapi/:  PYTHONPATH=src:tests/core python -m pytest -q tests/core

The config files these tests read live in examples/ (config, instances, cluster-configs), found by
walking up from this file to the repository root. The tests are also reachable through the
examples/tests symlink; Path.resolve() follows it, so both entry points land here.
"""
from pathlib import Path

import pytest
import yaml

from cmapi.core.identity.claims import Identity

EX = next(p / "examples" for p in Path(__file__).resolve().parents if (p / "examples" / "config").is_dir())
ALL_ENVS = {"rnd", "dev", "qa", "uat", "prod"}
INSTANCES = {"nonprod": {"rnd", "dev"}, "staging": {"qa", "uat"}, "prod": {"prod"}}
CRC_CONFIG = EX.parent / "deploy/manifests/environments/crc/20-config.yaml"


def crc_config_dir(dest: Path) -> Path:
    """CRC's instance files in dest: each key of the ConfigMap cmapi-config in CRC_CONFIG, as the pod mounts it. The split the
    operator makes before `cmapi-tools policies render` for CRC (docs/13, "cmapi's policy bundle on CRC")."""
    data = next(yaml.safe_load_all(CRC_CONFIG.read_text()))["data"]
    for name, text in data.items():
        (dest / name).write_text(text)
    return dest


def person(username, *, roles=(), groups=(), kind="user", client="cmapi-portal", employee_id="E100", sub=None):
    return Identity(sub=sub or f"sub-{username}", username=username, kind=kind, client_id=client,
                    email=f"{username}@ephico2real.com", given_name=username.title(), family_name="Doe",
                    employee_id=employee_id, roles=frozenset(roles), groups=frozenset(groups))


@pytest.fixture
def ex() -> Path:
    return EX
