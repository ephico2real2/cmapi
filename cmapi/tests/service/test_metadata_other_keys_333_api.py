"""#333 through the API, with no Kyverno: instance.yaml `policy.engine: none`, cmapi's real CliValidator and no kyverno
binary on PATH. Each body that one of the rendered policies of #333 refuses (a key outside the allowed prefixes, more other
keys than allowOther.max, an annotation over maxValueBytes, the other annotations over maxBytesTotal) is refused by cmapi
alone, with its own error, before any request exists (tests/core/test_policygen_coverage_333.py holds the same bodies
through the CLI).
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
def without_kyverno(test_config, fresh_db, keys, monkeypatch, tmp_path):
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


@pytest.mark.parametrize("labels, annotations, errors", [
    ({"other.example/x": "1"}, {}, [{"code": "invalid_key", "key": "other.example/x", "detail": "prefix not allowed"}]),
    ({f"k{i}": "v" for i in range(51)}, {}, [{"code": "too_many_keys", "kind": "label", "detail": "at most 50 other labels"}]),
    ({}, {"big": "é" * 2049}, [{"code": "annotations_too_large"}]),
    ({}, {f"x.ephico2real.com/a{i}": "a" * 4000 for i in range(17)}, [{"code": "annotations_too_large"}]),
], ids=["prefix", "max", "max-value-bytes", "max-bytes-total"])
def test_cmapi_alone_refuses_what_each_new_policy_refuses(without_kyverno, labels, annotations, errors):
    client, ctx, git, kube, validator, keys = without_kyverno
    assert ctx.cfg.policy.engine == "none" and shutil.which("kyverno") is None
    body = {**NS, "labels": {**NS["labels"], **labels}, "annotations": {**NS["annotations"], **annotations}}
    r = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert r.json()["errors"] == errors
    assert r.json()["findings"] == []                  # no Kyverno ran: the refusal is cmapi's own
    listed = client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA))
    assert listed.status_code == 200 and listed.json()["page"]["total"] == 0, listed.text
