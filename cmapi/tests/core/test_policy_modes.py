"""#213: the policy engine and its mode for each environment (core/policy.py), and the validator that follows them.

The kyverno and kubeconform binaries are stubs on PATH, so each test runs anywhere: the stub kyverno writes a JSON
report that fails every namespace (the form that `kyverno apply -p --output-format json` writes, #212) and leaves a mark. The real Kyverno 1.20 CLI's results are in docs/reviews/2026-11-14-issue-213/.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from cmapi.core.policy import PolicySettings
from cmapi.core.validate import CliValidator, PolicyEngineMissing

FILES = {"clusters/C/namespaces/abc-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: abc-dev\n"}
SERVED = {"rnd", "dev"}


def _stub(bin_dir: Path, name: str, body: str) -> None:
    f = bin_dir / name
    f.write_text("#!/bin/sh\n" + body)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def stubs(tmp_path, monkeypatch) -> Path:
    """kubeconform passes; kyverno fails each namespace and leaves a mark. PATH holds only these and the system tools."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "kubeconform", 'echo \'{"resources": [], "summary": {"valid": 1}}\'\n')
    report = json.dumps({"summary": {"fail": 1}, "results": [{"policy": "p", "result": "fail", "message": "refused",
                                                               "resources": [{"kind": "Namespace", "name": "abc-dev"}]}]})
    _stub(bin_dir, "kyverno", f'touch "{tmp_path}/kyverno-ran"\necho \'{report}\'\nexit 1\n')
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "p.yaml").write_text("apiVersion: policies.kyverno.io/v1\nkind: ValidatingPolicy\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return tmp_path


def kyverno_findings(v: CliValidator, env: str):
    return [(f.rule, f.severity) for f in v.validate(FILES, "C", env) if f.source == "kyverno"]


def test_no_policy_key_enforces_in_each_environment_as_before():
    p, problems = PolicySettings.parse(None, SERVED)
    assert problems == [] and p.engine == "kyverno" and p.modes(SERVED) == {"dev": "enforce", "rnd": "enforce"}


def test_a_mode_for_each_environment_and_engine_none():
    p, problems = PolicySettings.parse({"mode": "enforce", "environments": {"rnd": {"mode": "audit"}}}, SERVED)
    assert problems == [] and p.modes(SERVED) == {"dev": "enforce", "rnd": "audit"}
    p, problems = PolicySettings.parse({"engine": "none"}, SERVED)
    assert problems == [] and p.modes(SERVED) == {"dev": "off", "rnd": "off"} and not p.needs_kyverno(SERVED)


@pytest.mark.parametrize("raw, message", [
    ({"engine": "opa"}, "policy.engine must be one of"),
    ({"mode": "warn"}, "policy.mode must be one of"),
    ({"environments": {"prod": {"mode": "audit"}}}, "not an environment this instance serves"),
    ({"environments": {"rnd": {"mode": "loud"}}}, "policy.environments.rnd.mode must be one of"),
    ({"engine": "none", "mode": "enforce"}, "policy.engine none runs no policy"),
    ({"engine": "none", "environments": {"rnd": {"mode": "audit"}}}, "policy.engine none runs no policy"),
    ({"modes": {}}, "unknown fields"),
    ("enforce", "policy must be a mapping"),
])
def test_a_bad_policy_stops_the_start(raw, message):
    _, problems = PolicySettings.parse(raw, SERVED)
    assert any(message in p for p in problems), problems


def test_enforce_keeps_a_kyverno_finding_an_error(stubs):
    v = CliValidator(stubs / "policies", policy=PolicySettings(), environments=SERVED)
    assert kyverno_findings(v, "dev") == [("p", "error")]


def test_audit_turns_a_kyverno_finding_into_a_warning(stubs):
    v = CliValidator(stubs / "policies", policy=PolicySettings(environments={"rnd": "audit"}), environments=SERVED)
    assert kyverno_findings(v, "rnd") == [("p", "warning")]
    assert kyverno_findings(v, "dev") == [("p", "error")]


def test_off_runs_no_kyverno(stubs):
    v = CliValidator(stubs / "policies", policy=PolicySettings(default_mode="off"), environments=SERVED)
    assert v.validate(FILES, "C", "dev") == []
    assert not (stubs / "kyverno-ran").exists()


def test_with_no_binary_enforce_and_audit_stop_the_start_and_off_starts(stubs):
    os.remove(stubs / "bin" / "kyverno")
    for policy in (PolicySettings(), PolicySettings(default_mode="audit"), PolicySettings(environments={"rnd": "audit", "dev": "off"})):
        with pytest.raises(PolicyEngineMissing, match="kyverno is not installed"):
            CliValidator(stubs / "policies", policy=policy, environments=SERVED)
    for policy in (PolicySettings(default_mode="off"), PolicySettings(engine="none")):
        v = CliValidator(stubs / "policies", policy=policy, environments=SERVED)
        assert v.validate(FILES, "C", "dev") == []


def test_a_missing_binary_found_while_planning_stays_an_error_in_audit(stubs):
    v = CliValidator(stubs / "policies", policy=PolicySettings(default_mode="audit"), environments=SERVED)
    os.remove(stubs / "bin" / "kyverno")
    assert [(f.source, f.severity) for f in v.validate(FILES, "C", "dev")] == [("cmapi", "error")]
