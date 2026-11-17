"""#358 through the API, with no Kyverno: instance.yaml `policy.engine: none`, cmapi's real CliValidator, no kyverno binary
on PATH, and the owner's company metadata file. The owner, 2026-11-17: amgsst was only an example of a line of business,
which is free text, the critical level is 0 to 6, and the mnemonic is 3 or 4 lowercase letters, still the start of the
namespace name. So cmapi alone plans any line of business that is a label value, a critical level of 0 to 6 and a mnemonic
of 3 or 4 letters, refuses the rest with the key's own refusal (422 policy-violation, invalid_value), and serves the same
rules in its schema. On main a6f807e the company file listed `lob: [amgsst]`, `cl: 0 to 3` and `mnemonic: ^[a-z]{3}$`.
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
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}
LEVELS = ["0", "1", "2", "3", "4", "5", "6"]
MNEMONIC = "^[a-z]{3,4}$"


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


def body(labels: dict, namespace: str = "abc-dev") -> dict:
    return {"namespace": namespace, "tier": "small", "labels": labels, "annotations": {},
            "justification": "The owner's sample namespace"}


@pytest.mark.parametrize("lob, cl", [("retail", "6"), ("amgsst", "0"), ("Card.Services_2", "4")])
def test_any_line_of_business_and_a_critical_level_of_0_to_6_dry_run(company_no_kyverno, lob, cl):
    client, ctx, git, kube, validator, keys = company_no_kyverno
    assert ctx.cfg.policy.engine == "none" and shutil.which("kyverno") is None
    r = client.post(URL + "?dryRun=true", json=body({**SENT, "company.net/lob": lob, "company.net/cl": cl}),
                    headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and r.json()["findings"] == [], r.text
    ns = yaml.safe_load(next(t for p, t in r.json()["files"].items() if p.endswith("/namespace.yaml")))
    assert (ns["metadata"]["labels"]["company.net/lob"], ns["metadata"]["labels"]["company.net/cl"]) == (lob, cl)


@pytest.mark.parametrize("change, key, detail", [
    ({"company.net/cl": "7"}, "company.net/cl", f"one of {LEVELS}"),
    ({"company.net/lob": "retail sales"}, "company.net/lob", "not a valid label value"),
    ({"company.net/lob": "-retail"}, "company.net/lob", "not a valid label value"),
    ({"company.net/lob": "a" * 64}, "company.net/lob", "not a valid label value"),
])
def test_a_critical_level_above_6_or_a_line_of_business_that_is_not_a_label_value_is_refused(
        company_no_kyverno, change, key, detail):
    client, ctx, git, kube, validator, keys = company_no_kyverno
    r = client.post(URL + "?dryRun=true", json=body({**SENT, **change}), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert [(e["code"], e["key"], e["detail"]) for e in r.json()["errors"]] == [("invalid_value", key, detail)]


def test_the_served_schema_has_no_list_for_the_line_of_business_and_0_to_6_for_the_critical_level(company_no_kyverno):
    client, ctx, git, kube, validator, keys = company_no_kyverno
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("NamespaceCreate", "NamespacePatch"):
        labels = schemas[name]["properties"]["labels"]
        if "anyOf" in labels:                               # a patch: the object branch of anyOf with null
            labels = next(b for b in labels["anyOf"] if b.get("type") == "object")
        lob, cl = labels["properties"]["company.net/lob"], labels["properties"]["company.net/cl"]
        assert "enum" not in lob and lob["maxLength"] == 63 and lob["examples"] == ["amgsst"], (name, lob)
        assert "free text" in lob["description"], (name, lob)
        assert cl["enum"] == LEVELS, (name, cl)
        mnemonic = labels["properties"]["company.net/mnemonic"]
        assert mnemonic["pattern"] == f"^(?:{MNEMONIC})$" and mnemonic["x-cmapi-namespace-prefix"] is True, (name, mnemonic)


def test_a_4_letter_mnemonic_that_starts_the_namespace_name_dry_runs(company_no_kyverno):
    client, ctx, git, kube, validator, keys = company_no_kyverno
    r = client.post(URL + "?dryRun=true", json=body({**SENT, "company.net/mnemonic": "abcd"}, "abcd-rnd"),
                    headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and r.json()["findings"] == [], r.text
    ns = yaml.safe_load(next(t for p, t in r.json()["files"].items() if p.endswith("/namespace.yaml")))
    assert ns["metadata"]["name"] == "abcd-rnd" and ns["metadata"]["labels"]["company.net/mnemonic"] == "abcd"


@pytest.mark.parametrize("mnemonic, namespace, detail", [
    ("abcde", "abcde-rnd", f"must match {MNEMONIC}"),
    ("ab", "ab-rnd", f"must match {MNEMONIC}"),
    ("abcd", "abc-rnd", "abc-rnd does not start with abcd-"),
])
def test_a_mnemonic_of_other_than_3_or_4_letters_or_not_the_start_of_the_name_is_refused(
        company_no_kyverno, mnemonic, namespace, detail):
    client, ctx, git, kube, validator, keys = company_no_kyverno
    r = client.post(URL + "?dryRun=true", json=body({**SENT, "company.net/mnemonic": mnemonic}, namespace),
                    headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert [(e["code"], e["key"], e["detail"]) for e in r.json()["errors"]] == [
        ("invalid_value", "company.net/mnemonic", detail)]
