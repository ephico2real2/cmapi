"""#331 through the API, with no Kyverno: instance.yaml `policy.engine: none`, cmapi's real CliValidator, no kyverno binary
on PATH, and metadata-keys.yaml whose allowOther prefixes are ["*"] with no "". cmapi alone must refuse a key with no
prefix; before the fix the create was accepted, because fnmatchcase("", "*") is true.
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
def star_only(test_config, fresh_db, keys, monkeypatch, tmp_path):
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
    meta = yaml.safe_load((d / "metadata-keys.yaml").read_text())
    for stanza in ("extraLabels", "extraAnnotations"):
        meta[stanza]["allowOther"]["prefixes"] = ["*"]
    (d / "metadata-keys.yaml").write_text(yaml.safe_dump(meta))
    with build_world(d, keys, monkeypatch) as world:
        client, ctx, *_ = world
        ctx.pipeline.validator = CliValidator(tmp_path / "policies", policy=ctx.cfg.policy,
                                              environments=ctx.cfg.allowed_environments)
        yield world


def test_the_instance_runs_no_kyverno_and_star_admits_a_prefixed_key(star_only):
    client, ctx, git, kube, validator, keys = star_only
    assert ctx.cfg.policy.engine == "none" and shutil.which("kyverno") is None
    assert ctx.cfg.metadata.allow_other["label"].prefixes == ("*",)
    # The control: "*" still admits a key under any prefix that is not reserved.
    body = {**NS, "labels": {**NS["labels"], "team.example/foo": "x"}}
    r = client.post(URL + "?dryRun=true", json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and r.json()["findings"] == [], r.text


@pytest.mark.parametrize("field", ["labels", "annotations"])
def test_a_create_with_an_unprefixed_key_is_refused(star_only, field):
    client, ctx, git, kube, validator, keys = star_only
    body = {**NS, field: {**NS[field], "foo": "x"}}
    r = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert r.json()["errors"] == [{"code": "invalid_key", "key": "foo", "detail": "prefix not allowed"}]
    # Refused before a request exists: nothing to approve, nothing to deliver.
    listed = client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA))
    assert listed.status_code == 200 and listed.json()["page"]["total"] == 0, listed.text
