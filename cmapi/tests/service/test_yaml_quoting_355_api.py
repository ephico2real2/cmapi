"""#355 through the API: with `policy.engine: none`, a create whose team label is y and team annotation is n dry-runs 200,
and the namespace.yaml it plans reads back with the strings y and n in the readers of Kubernetes tooling
(tests/core/kube_readers.py: sigs.k8s.io/yaml for kubectl, Argo CD and Kyverno, and go-yaml v3). Before the fix the
file held them plain, and sigs.k8s.io/yaml read them as true and false.
"""
from __future__ import annotations

import shutil
import stat

import pytest
import yaml

from cmapi.core.validate import CliValidator
from conftest import build_world
from kube_readers import READERS, read
from kube_readers import binary as build_reader
from test_flow import NS, OLA, auth

URL = "/api/v1/clusters/CRC/namespaces"


@pytest.fixture
def without_kyverno(test_config, fresh_db, keys, monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kubeconform = bin_dir / "kubeconform"
    kubeconform.write_text("#!/bin/sh\necho '{\"resources\": [], \"summary\": {\"valid\": 1}}'\n")
    kubeconform.chmod(kubeconform.stat().st_mode | stat.S_IEXEC)
    build_reader()                               # the Go reader, built while PATH still has go
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


def test_a_label_y_and_an_annotation_n_reach_the_planned_file_as_strings(without_kyverno):
    client, ctx, git, kube, validator, keys = without_kyverno
    assert ctx.cfg.policy.engine == "none" and shutil.which("kyverno") is None
    body = {**NS, "labels": {**NS["labels"], "x.ephico2real.com/flag": "y"},
            "annotations": {**NS["annotations"], "x.ephico2real.com/note": "n"}}
    r = client.post(URL + "?dryRun=true", json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    text = next(t for p, t in r.json()["files"].items() if p.endswith("/namespace.yaml"))
    got = read(text)
    for reader in READERS:
        meta = got[reader]["metadata"]
        assert meta["labels"]["x.ephico2real.com/flag"] == "y", (reader, meta["labels"])
        assert meta["annotations"]["x.ephico2real.com/note"] == "n", (reader, meta["annotations"])
