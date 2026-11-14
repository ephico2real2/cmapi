"""#215: the four metadata stanzas (requiredLabels, requiredAnnotations, extraLabels, extraAnnotations) and
adoptionLabels, on the owner's sample namespace abc-rnd (examples/cluster-configs/policies/metadata-keys.company.yaml)."""
from __future__ import annotations

import copy

import pytest
import yaml

from cmapi.core.errors import Problem
from cmapi.core.metadata import MetadataKeys
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from cmapi.core.tiers import TierCatalog
from conftest import ALL_ENVS, EX

COMPANY = EX / "cluster-configs/policies/metadata-keys.company.yaml"
SOURCES = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "OCP_GF15", "instance": "nonprod"}
# What the requester sends for the owner's sample: no derived key.
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1",
        "company.net/mnemonic-group-contact": "", "company.net/mnemonic-confluence": ""}


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(COMPANY.read_text())


@pytest.fixture(scope="module")
def keys(raw) -> MetadataKeys:
    return MetadataKeys(raw)


def codes(errs):
    return sorted((e["code"], e.get("key")) for e in errs)


def test_the_owners_sample_namespace_renders_exactly(keys):
    renderer = ManifestRenderer(TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS), keys)
    assert keys.validate(SENT, {}, operator=False, sources=SOURCES) == []
    files = renderer.render(NamespaceSpec(namespace="abc-rnd", cluster_id="OCP_GF15", instance="nonprod", env="rnd",
                                          tier="small", request_id="req-20261114-0001", requested_by_user="ola",
                                          requested_by_email="ola@company.net", labels=SENT, annotations={}))
    ns = yaml.safe_load(files["clusters/OCP_GF15/namespaces/abc-rnd/namespace.yaml"])
    company = {k: v for k, v in ns["metadata"]["labels"].items() if not k.startswith("cmapi.net/")}
    assert company == {"name": "abc-rnd", "company.net/app-environment": "rnd", "company.net/mnemonic": "abc",
                       "company.net/lob": "amgsst", "company.net/cl": "1",
                       "company.net/mnemonic-group-contact": "", "company.net/mnemonic-confluence": ""}
    assert ns["metadata"]["annotations"]["company.net/app-environment"] == "rnd"
    # cmapi's own system keys stay beside the company's: cmapi.net/env is not the company's key (#215, owner's item 1).
    assert ns["metadata"]["labels"]["cmapi.net/env"] == "rnd" and ns["metadata"]["labels"]["cmapi.net/managed"] == "true"


@pytest.mark.parametrize("change, want", [
    ({"company.net/mnemonic": None}, [("missing_required_key", "company.net/mnemonic")]),
    ({"company.net/lob": "retail"}, [("invalid_value", "company.net/lob")]),
    ({"company.net/cl": "7"}, [("invalid_value", "company.net/cl")]),
    ({"company.net/mnemonic": "abcd"}, [("invalid_value", "company.net/mnemonic")]),
    ({"company.net/mnemonic": "xyz"}, [("invalid_value", "company.net/mnemonic")]),     # abc-rnd does not start with xyz-
    ({"name": "aao-rnd"}, [("derived_key", "name")]),                                   # the owner's typo: a derived value
    ({"company.net/app-environment": "prod"}, [("derived_key", "company.net/app-environment")]),
    ({"other.example/x": "1"}, [("invalid_key", "other.example/x")]),
])
def test_each_rule_refuses_with_the_key(keys, change, want):
    sent = {k: v for k, v in {**SENT, **change}.items() if v is not None}
    assert codes(keys.validate(sent, {}, operator=False, sources=SOURCES)) == want


def test_a_derived_key_with_its_own_value_is_accepted_and_one_removed_is_refused(keys):
    assert keys.validate({**SENT, "name": "abc-rnd"}, {"company.net/app-environment": "rnd"}, operator=False, sources=SOURCES) == []
    errs = keys.validate({"name": None}, {}, operator=False, sources=SOURCES, current_labels=SENT)
    assert ("derived_key", "name") in codes(errs)


def test_the_refusal_is_one_problem_that_names_each_key_and_its_rule(keys):
    with pytest.raises(Problem) as e:
        keys.check({"company.net/lob": "retail"}, {}, operator=False, sources=SOURCES)
    errors = e.value.body("https://x/")["errors"]
    by_key = {err["key"]: err for err in errors}
    assert set(by_key) == {"company.net/lob", "company.net/mnemonic", "company.net/cl"}
    assert by_key["company.net/lob"]["detail"] == "one of ['amgsst']"
    assert by_key["company.net/mnemonic"]["code"] == "missing_required_key"
    assert "the start of the namespace name" in by_key["company.net/mnemonic"]["detail"]


def test_other_keys_are_limited_by_kind(keys):
    many = {**SENT, **{f"k{i}": "v" for i in range(51)}}
    assert ("too_many_keys", None) in codes(keys.validate(many, {}, operator=False, sources=SOURCES))
    assert keys.validate({**SENT, **{f"k{i}": "v" for i in range(50)}}, {}, operator=False, sources=SOURCES) == []


def test_a_key_can_be_a_label_and_an_annotation_with_one_rule_each(keys):
    assert keys.rules["label"]["company.net/app-environment"].derived == "environment"
    assert keys.rules["annotation"]["company.net/app-environment"].derived == "environment"
    assert keys.derived(SOURCES) == ({"name": "abc-rnd", "company.net/app-environment": "rnd"},
                                     {"company.net/app-environment": "rnd"})


def test_adoption_labels_are_read_and_a_requester_cannot_set_them(keys):
    assert keys.adoption_labels == {"company.net/provisioner": ("cluster-configs",)}
    assert codes(keys.validate({**SENT, "company.net/provisioner": "cluster-configs"}, {}, operator=False,
                               sources=SOURCES)) == [("reserved_key", "company.net/provisioner")]


def test_the_old_stanzas_stop_the_start_with_the_new_names():
    old = {"governed": {"cmapi.net/team": {"kind": "label", "required": True}}, "team": {"allowedPrefixes": [""]}}
    with pytest.raises(ValueError, match=r"requiredLabels, requiredAnnotations, extraLabels and extraAnnotations"):
        MetadataKeys(old)


@pytest.mark.parametrize("edit, message", [
    (lambda r: r["extraLabels"]["keys"].__setitem__("company.net/wiki", {"format": "url"}), "format url is for annotations only"),
    (lambda r: r["requiredLabels"]["name"].__setitem__("pattern", "^x$"), "takes no pattern"),
    (lambda r: r["requiredLabels"]["company.net/lob"].__setitem__("required", True), "unknown fields"),
    (lambda r: r["requiredLabels"].__setitem__("cmapi.net/tier", {}), "system, operator-only or reserved"),
    (lambda r: r["requiredLabels"].__setitem__("app.kubernetes.io/name", {}), "system, operator-only or reserved"),
    (lambda r: r["requiredLabels"]["company.net/lob"].__setitem__("pattern", "^a"), "give one of pattern, enum and format"),
    (lambda r: r["requiredLabels"]["name"].__setitem__("value", {"from": "team"}), "value.from must be one of"),
    (lambda r: r["requiredLabels"]["company.net/cl"].__setitem__("enum", ["a b"]), "not valid label values"),
    (lambda r: r["adoptionLabels"].__setitem__("company.net/lob", {"recognise": ["x"]}), "not an adoption label"),
    (lambda r: r["requiredLabels"]["company.net/mnemonic"].__setitem__("pattern", "(["), "does not compile"),
])
def test_the_loader_refuses_a_bad_configuration(raw, edit, message):
    bad = copy.deepcopy(raw)
    edit(bad)
    with pytest.raises(ValueError, match=message):
        MetadataKeys(bad)


def test_the_shipped_configuration_keeps_its_keys_and_classes():
    keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.yaml")
    assert [k for k, r in keys.rules["label"].items() if r.required] == ["cmapi.net/team"]
    assert [k for k, r in keys.rules["annotation"].items() if r.required] == ["cmapi.net/team-dl"]
    assert keys.classify("cmapi.net/cost-center") == "governed" and keys.classify("owner") == "team"
    assert keys.derived(SOURCES) == ({}, {})
