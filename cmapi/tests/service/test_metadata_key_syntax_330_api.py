"""#330 through the API, with no Kyverno: instance.yaml `policy.engine: none`, cmapi's real CliValidator, and no kyverno
binary on PATH. cmapi alone must refuse a label or annotation key with an empty prefix ("/foo"), which the API server
refuses at apply (apimachinery IsLabelKey: "prefix part must be non-empty"); before the fix the create was accepted.
"""
from __future__ import annotations

import shutil
import stat

import pytest
import yaml

from cmapi.core.validate import CliValidator
from conftest import build_world
from test_flow import NS, OLA, auth

URL = "/api/v1/clusters/CRC/namespaces"


@pytest.fixture
def no_kyverno(test_config, fresh_db, keys, monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kubeconform = bin_dir / "kubeconform"
    kubeconform.write_text("#!/bin/sh\necho '{\"resources\": [], \"summary\": {\"valid\": 1}}'\n")
    kubeconform.chmod(kubeconform.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["policy"] = {"engine": "none"}
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    with build_world(d, keys, monkeypatch) as world:
        client, ctx, *_ = world
        ctx.pipeline.validator = CliValidator(tmp_path / "policies", policy=ctx.cfg.policy,
                                              environments=ctx.cfg.allowed_environments)
        yield world


def test_the_instance_runs_no_kyverno(no_kyverno):
    client, ctx, git, kube, validator, keys = no_kyverno
    assert ctx.cfg.policy.engine == "none" and shutil.which("kyverno") is None
    # The control: the same body without the bad key plans clean, so each refusal below is the key's alone.
    r = client.post(URL + "?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and r.json()["findings"] == [], r.text


@pytest.mark.parametrize("field", ["labels", "annotations"])
def test_a_create_with_an_empty_prefix_key_is_refused(no_kyverno, field):
    client, ctx, git, kube, validator, keys = no_kyverno
    body = {**NS, field: {**NS[field], "/foo": "x"}}
    r = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert r.json()["errors"] == [{"code": "invalid_key", "key": "/foo"}]
    # Refused before a request exists: nothing to approve, nothing to deliver.
    listed = client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA))
    assert listed.status_code == 200 and listed.json()["page"]["total"] == 0, listed.text
