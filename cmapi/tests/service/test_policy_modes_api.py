"""#213 through the API: a create in each policy mode, with cmapi's real validator and stub binaries on PATH.

The stub kyverno fails every namespace; the stub kubeconform passes. So enforce refuses the plan, audit sends the request
to approval with the finding as a warning, and off plans and submits with no kyverno binary at all.
"""
from __future__ import annotations

import json
import shutil
import stat

import pytest
import yaml

from cmapi.core.observability import POLICY_MODE
from cmapi.core.validate import CliValidator
from conftest import build_world
from test_flow import NS, OLA, auth

URL = "/api/v1/clusters/CRC/namespaces"


def _stub(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def world_with(test_config, fresh_db, keys, monkeypatch, tmp_path):
    """build(policy, kyverno=True): the API on an instance.yaml with that `policy` key, and cmapi's real validator."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir / "kubeconform", 'echo \'{"resources": [], "summary": {"valid": 1}}\'\n')
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "require-team-metadata.yaml").write_text("apiVersion: policies.kyverno.io/v1\nkind: ValidatingPolicy\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    worlds = []

    def build(policy, kyverno=True):
        if kyverno:
            # The JSON report of `kyverno apply -p --output-format json` (#212), failing the namespace.
            report = json.dumps({"summary": {"fail": 1}, "results": [
                {"policy": "require-team-metadata", "result": "fail", "message": "team missing",
                 "resources": [{"kind": "Namespace", "name": NS["namespace"]}]}]})
            # `kyverno version` answers as the pinned CLI does, for the start check of CMAPI_KYVERNO_VERSION.
            _stub(bin_dir / "kyverno", 'if [ "$1" = version ]; then echo "Version: v1.20.0"; exit 0; fi\n'
                                       f"echo '{report}'\nexit 1\n")
        d = tmp_path / f"config{len(worlds)}"
        shutil.copytree(test_config, d)
        inst = yaml.safe_load((d / "instance.yaml").read_text())
        inst["instance"]["policy"] = policy
        (d / "instance.yaml").write_text(yaml.safe_dump(inst))
        cm = build_world(d, keys, monkeypatch)
        world = cm.__enter__()
        worlds.append(cm)
        client, ctx, *_ = world
        ctx.pipeline.validator = CliValidator(tmp_path / "policies", policy=ctx.cfg.policy, environments=ctx.cfg.allowed_environments)
        return world

    yield build
    for cm in reversed(worlds):
        cm.__exit__(None, None, None)


def test_enforce_refuses_the_plan(world_with):
    client, ctx, git, kube, validator, keys = world_with({"mode": "enforce"})
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert r.json()["errors"][0]["source"] == "kyverno"


def test_audit_sends_the_request_to_approval_with_the_finding_as_a_warning(world_with):
    client, ctx, git, kube, validator, keys = world_with({"mode": "audit"})
    dry = client.post(URL + "?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert dry.status_code == 200, dry.text
    assert [f["severity"] for f in dry.json()["findings"]] == ["warning"]
    # The warning keeps the auto-approval rule from applying (core/approvals.py): approvers see the finding.
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text


def test_off_plans_and_submits_with_no_kyverno_binary(world_with):
    client, ctx, git, kube, validator, keys = world_with({"mode": "off"}, kyverno=False)
    assert shutil.which("kyverno") is None
    dry = client.post(URL + "?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert dry.status_code == 200 and dry.json()["findings"] == [], dry.text
    # No finding, so the instance's auto-approval rule for a dev create applies, as it does with a clean plan in enforce.
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    assert r.json()["approval"]["auto"] == "auto:baseline-rnd-namespace"


def test_the_integrations_endpoint_reports_the_engine_and_each_mode(world_with, monkeypatch):
    monkeypatch.setenv("CMAPI_KYVERNO_VERSION", "v1.20.0")
    client, ctx, git, kube, validator, keys = world_with({"mode": "enforce", "environments": {"rnd": {"mode": "audit"}}})
    r = client.get("/api/v1/admin/integrations", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    assert r.json()["policy"] == {"engine": "kyverno", "kyvernoVersion": "v1.20.0",
                                  "environments": {"dev": "enforce", "rnd": "audit"}}
    assert POLICY_MODE.labels("rnd", "audit")._value.get() == 1


def test_the_chart_passes_the_policy_to_instance_yaml(tmp_path):
    import pathlib
    import subprocess
    root = pathlib.Path(__file__).resolve().parents[3]
    if shutil.which("helm") is None:
        pytest.skip("helm")
    (tmp_path / "ca.crt").write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    r = subprocess.run(["helm", "template", "cmapi", str(root / "deploy/helm/cmapi"), "-n", "cmapi", "-f", str(root / "deploy/environments/crc.yaml"),
                        "--set", "cmapi.digest=sha256:" + "a" * 64, "--set", "portal.enabled=false",
                        "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}",
                        "--set", "instance.policy.mode=enforce", "--set", "instance.policy.environments.rnd.mode=audit"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    cm = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "ConfigMap" and d["metadata"]["name"] == "cmapi-config")
    assert yaml.safe_load(cm["data"]["instance.yaml"])["instance"]["policy"] == {"mode": "enforce", "environments": {"rnd": {"mode": "audit"}}}
