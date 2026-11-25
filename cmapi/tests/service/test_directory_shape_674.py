"""#674 review, finding R1-1: instance.yaml `directory` is read on every environment-not-served refusal, so the start checks
its shape (docs/18, "instance.directory": each entry has `url`, `environments` and an optional `portalUrl`).

Before #671 only the write path read it; #671 sends GET /capacity, GET /tiers and Pipeline._decide through
environment_not_served too, so an entry that the start did not check turned their 422 into a 500.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from cmapi.core.config import ConfigError, load_instance

REPO = Path(__file__).resolve().parents[3]
NONPROD = REPO / "examples" / "instances" / "nonprod"
KEYS = REPO / "examples" / "cluster-configs" / "policies" / "metadata-keys.yaml"


def _with_directory(tmp_path: Path, directory) -> Path:
    shutil.copytree(NONPROD, tmp_path / "cfg")
    inst = yaml.safe_load((tmp_path / "cfg" / "instance.yaml").read_text())
    inst["instance"]["directory"] = directory
    (tmp_path / "cfg" / "instance.yaml").write_text(yaml.safe_dump(inst))
    return tmp_path / "cfg"


@pytest.mark.parametrize("directory, message", [
    (["staging"], "instance.directory must be a mapping"),
    ({"staging": "https://cmapi-staging.ephico2real.com"}, "instance.directory.staging must be a mapping"),
    ({"staging": {"url": "https://cmapi-staging.ephico2real.com", "environments": None}},
     "instance.directory.staging.environments must be a list"),
    ({"staging": {"url": "https://cmapi-staging.ephico2real.com", "environments": "qa, uat"}},
     "instance.directory.staging.environments must be a list"),
    ({"staging": {"environments": ["qa"]}}, "instance.directory.staging.url must be an absolute http(s) URL"),
    ({"staging": {"url": 443, "environments": ["qa"]}}, "instance.directory.staging.url must be an absolute http(s) URL"),
    ({"staging": {"url": "https://cmapi-staging.ephico2real.com", "environments": ["qa"], "portalUrl": "portal-staging"}},
     "instance.directory.staging.portalUrl must be an absolute http(s) URL"),
])
def test_a_directory_of_the_wrong_shape_stops_the_start(tmp_path, directory, message):
    with pytest.raises(ConfigError, match=message.replace("(", r"\(").replace(")", r"\)")):
        load_instance(_with_directory(tmp_path, directory), KEYS)


@pytest.mark.parametrize("directory", [
    None,
    {},
    {"staging": {"url": "https://cmapi-staging.ephico2real.com", "environments": ["qa", "uat"]}},
    {"staging": {"url": "https://cmapi-staging.ephico2real.com", "environments": ["qa"], "portalUrl": ""}},
    {"staging": {"url": "https://cmapi-staging.ephico2real.com", "environments": ["qa"],
                 "portalUrl": "https://portal-staging.ephico2real.com"}},
])
def test_a_directory_of_the_documented_shape_starts(tmp_path, directory):
    assert load_instance(_with_directory(tmp_path, directory), KEYS).name == "nonprod"
