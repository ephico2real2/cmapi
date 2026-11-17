"""#332 through the API, with no Kyverno: instance.yaml `policy.engine: none`, cmapi's real CliValidator, no kyverno binary
on PATH, and the owner's company metadata file. cmapi alone refuses a URL annotation that the rendered policy refuses,
with the key's own refusal (422 policy-violation, invalid_value). On main the first value was accepted (urlsplit strips a
leading C0 control) and the second was a 422 validation-failed from urlsplit's ValueError, not a refusal of the key.
"""
from __future__ import annotations

import shutil
import stat

import pytest
import yaml

from cmapi.core.validate import CliValidator
from conftest import EXAMPLES, build_world
from test_flow import OLA, auth

URL = "/api/v1/clusters/CRC/namespaces"
KEY = "company.net/mnemonic-confluence"
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}


@pytest.fixture
def company_no_kyverno(test_config, fresh_db, keys, monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    kubeconform = bin_dir / "kubeconform"
    kubeconform.write_text("#!/bin/sh\necho '{\"resources\": [], \"summary\": {\"valid\": 1}}'\n")
    kubeconform.chmod(kubeconform.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    shutil.copy(EXAMPLES / "cluster-configs/policies/metadata-keys.company.yaml", d / "metadata-keys.yaml")
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    inst["instance"]["policy"] = {"engine": "none"}
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    with build_world(d, keys, monkeypatch) as world:
        client, ctx, *_ = world
        ctx.pipeline.validator = CliValidator(tmp_path / "policies", policy=ctx.cfg.policy,
                                              environments=ctx.cfg.allowed_environments)
        yield world


def body(url: str) -> dict:
    return {"namespace": "abc-dev", "tier": "small", "labels": SENT, "annotations": {KEY: url},
            "justification": "The owner's sample namespace"}


def test_the_instance_runs_no_kyverno_and_plans_a_good_url(company_no_kyverno):
    client, ctx, git, kube, validator, keys = company_no_kyverno
    assert ctx.cfg.policy.engine == "none" and shutil.which("kyverno") is None
    for url in ("https://wiki.company.net/abc", "http://[2001:db8::1]:8080/abc"):
        r = client.post(URL + "?dryRun=true", json=body(url), headers=auth(keys, "ola", **OLA))
        assert r.status_code == 200 and r.json()["findings"] == [], r.text


@pytest.mark.parametrize("url", ["\x01https://wiki.company.net/abc", "http://[wiki.company.net/abc",
                                 "http://wiki\u2100company.net/abc", "http://[::1]x/abc"])
def test_a_url_that_the_policy_refuses_is_refused_by_cmapi_alone(company_no_kyverno, url):
    client, ctx, git, kube, validator, keys = company_no_kyverno
    r = client.post(URL, json=body(url), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert r.json()["errors"] == [{"code": "invalid_value", "key": KEY, "kind": "annotation", "detail": "an http or https URL"}]
    listed = client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA))
    assert listed.status_code == 200 and listed.json()["page"]["total"] == 0, listed.text
