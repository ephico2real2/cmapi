"""#215 through the API: an instance with the owner's company stanzas plans abc-dev on CRC (environment dev).

The API takes the derived values from the request's target (the namespace and the cluster's environment), not from
the body, and refuses a body that sends another value. Runs on the fakes of conftest.py.
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from conftest import EXAMPLES, build_world
from test_flow import OLA, auth

URL = "/api/v1/clusters/CRC/namespaces"
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}
# The two optional keys are annotations, with their formats (the owner's decision on #234).
OPTIONAL = {"company.net/mnemonic-group-contact": "abc-team@company.net",
            "company.net/mnemonic-confluence": "https://wiki.company.net/abc"}


@pytest.fixture
def company(test_config, fresh_db, keys, monkeypatch, tmp_path):
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    shutil.copy(EXAMPLES / "cluster-configs/policies/metadata-keys.company.yaml", d / "metadata-keys.yaml")
    with build_world(d, keys, monkeypatch) as world:
        yield world


def body(**over) -> dict:
    return {"namespace": "abc-dev", "tier": "small", "labels": SENT, "annotations": OPTIONAL,
            "justification": "The owner's sample namespace", **over}


def namespace_yaml(plan: dict) -> dict:
    return yaml.safe_load(next(t for p, t in plan["files"].items() if p.endswith("/namespace.yaml")))


def test_the_plan_fills_the_derived_keys_from_the_target(company):
    client, ctx, git, kube, validator, keys = company
    r = client.post(URL + "?dryRun=true", json=body(), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    meta = namespace_yaml(r.json())["metadata"]
    assert {k: v for k, v in meta["labels"].items() if not k.startswith("cmapi.net/")} == {
        "name": "abc-dev", "company.net/app-environment": "dev", "company.net/mnemonic": "abc",
        "company.net/lob": "amgsst", "company.net/cl": "1"}
    assert meta["annotations"]["company.net/app-environment"] == "dev"
    assert {k: meta["annotations"][k] for k in OPTIONAL} == OPTIONAL


def test_a_body_with_another_derived_value_or_a_wrong_prefix_is_refused_with_each_key(company):
    client, ctx, git, kube, validator, keys = company
    labels = {**SENT, "name": "aao-dev", "company.net/mnemonic": "xyz"}
    r = client.post(URL + "?dryRun=true", json=body(labels=labels), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
    assert sorted((e["code"], e["key"]) for e in r.json()["errors"]) == [
        ("derived_key", "name"), ("invalid_value", "company.net/mnemonic")]


def test_the_api_document_names_the_configured_keys(company):
    client, ctx, git, kube, validator, keys = company
    props = client.get("/openapi.json").json()["components"]["schemas"]["NamespaceCreate"]["properties"]
    assert "`company.net/lob` (one of ['amgsst'])" in props["labels"]["description"]
    assert "Set by cmapi, not by the requester: `name` (set by cmapi from the namespace)" in props["labels"]["description"]
    assert "`company.net/app-environment` (set by cmapi from the environment)" in props["annotations"]["description"]
