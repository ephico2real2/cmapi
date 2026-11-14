"""Fable's review of #240, F3: instance.yaml and the chart's values are YAML 1.1, where an unquoted `off` is the boolean false."""
from __future__ import annotations

import pytest
import yaml

from cmapi.core.policy import PolicySettings

SERVED = {"rnd", "dev"}


@pytest.mark.parametrize("text, modes", [
    ("mode: off", {"dev": "off", "rnd": "off"}),
    ("mode: enforce\nenvironments:\n  rnd: {mode: off}", {"dev": "enforce", "rnd": "off"}),
    ("mode: 'off'", {"dev": "off", "rnd": "off"}),
])
def test_an_unquoted_off_in_yaml_is_the_mode_off(text, modes):
    p, problems = PolicySettings.parse(yaml.safe_load(text), SERVED)
    assert problems == [] and p.modes(SERVED) == modes and (p.needs_kyverno(SERVED) is ("enforce" in modes.values()))


@pytest.mark.parametrize("text", ["mode: on", "mode: yes", "environments:\n  rnd: {mode: on}"])
def test_an_unquoted_on_is_still_refused(text):
    _, problems = PolicySettings.parse(yaml.safe_load(text), SERVED)
    assert any("must be one of" in p for p in problems), problems
