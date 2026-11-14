"""Fable's review of #240, F2: in audit only a violation becomes a warning. A policy that the CLI could not evaluate, or
applied no rule of, is a fault of the bundle or the image, and stays an error in each mode.

The stub kyverno prints what the real v1.20.0 CLI printed for each case (docs/reviews/2026-11-14-issue-213/, Fable's record).
"""
from __future__ import annotations

import pytest

from cmapi.core.policy import PolicySettings
from cmapi.core.validate import CliValidator
from test_policy_modes import FILES, SERVED, _stub, stubs  # noqa: F401  (the fixture)

EVAL_ERROR = 'echo "Applying 1 policy rule(s) to 1 resource(s)..."\necho "pass: 0, fail: 0, warn: 0, error: 1, skip: 0"\nexit 1\n'
COMPILE_ERROR = ('echo "Applying 1 policy rule(s) to 1 resource(s)..."\n'
                 'echo "Error: failed to compile policy err" >&2\nexit 1\n')
NO_RULES = 'echo "Applying 0 policy rule(s) to 1 resource(s)..."\necho "pass: 0, fail: 0, warn: 0, error: 0, skip: 0"\nexit 0\n'
VIOLATION = 'echo "Applying 1 policy rule(s) to 1 resource(s)..."\necho "pass: 0, fail: 1, warn: 0, error: 0, skip: 0"\nexit 1\n'


@pytest.mark.parametrize("mode", ["audit", "enforce"])
@pytest.mark.parametrize("body", [EVAL_ERROR, COMPILE_ERROR, NO_RULES], ids=["evaluation-error", "compile-error", "no-rules"])
def test_a_policy_that_gave_no_verdict_is_an_error_in_each_mode(stubs, mode, body):
    _stub(stubs / "bin", "kyverno", body)
    v = CliValidator(stubs / "policies", policy=PolicySettings(default_mode=mode), environments=SERVED)
    assert [(f.source, f.severity) for f in v.validate(FILES, "C", "dev")] == [("cmapi", "error")]


def test_a_violation_is_still_a_warning_in_audit_and_an_error_in_enforce(stubs):
    _stub(stubs / "bin", "kyverno", VIOLATION)
    audit = CliValidator(stubs / "policies", policy=PolicySettings(default_mode="audit"), environments=SERVED)
    assert [(f.source, f.severity) for f in audit.validate(FILES, "C", "dev")] == [("kyverno", "warning")]
    enforce = CliValidator(stubs / "policies", policy=PolicySettings(), environments=SERVED)
    assert [(f.source, f.severity) for f in enforce.validate(FILES, "C", "dev")] == [("kyverno", "error")]


# F3: instance.yaml and the chart's values are YAML 1.1, where an unquoted `off` is the boolean false.
import yaml  # noqa: E402


@pytest.mark.parametrize("text, modes", [
    ("mode: off", {"dev": "off", "rnd": "off"}),
    ("mode: enforce\nenvironments:\n  rnd: {mode: off}", {"dev": "enforce", "rnd": "off"}),
    ("mode: 'off'", {"dev": "off", "rnd": "off"}),
])
def test_an_unquoted_off_in_yaml_is_the_mode_off(text, modes):
    raw = yaml.safe_load(text)
    p, problems = PolicySettings.parse(raw, SERVED)
    assert problems == [] and p.modes(SERVED) == modes and (p.needs_kyverno(SERVED) is ("enforce" in modes.values()))


@pytest.mark.parametrize("text", ["mode: on", "mode: yes", "environments:\n  rnd: {mode: on}"])
def test_an_unquoted_on_is_still_refused(text):
    _, problems = PolicySettings.parse(yaml.safe_load(text), SERVED)
    assert any("must be one of" in p for p in problems), problems
