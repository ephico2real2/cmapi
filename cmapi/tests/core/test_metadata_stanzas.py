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
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}
# The two optional keys are annotations, with their formats (the owner's decision on #234).
OPTIONAL = {"company.net/mnemonic-group-contact": "abc-team@company.net",
            "company.net/mnemonic-confluence": "https://wiki.company.net/abc"}


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
    assert keys.validate(SENT, OPTIONAL, operator=False, sources=SOURCES) == []
    files = renderer.render(NamespaceSpec(namespace="abc-rnd", cluster_id="OCP_GF15", instance="nonprod", env="rnd",
                                          tier="small", request_id="req-20261114-0001", requested_by_user="ola",
                                          requested_by_email="ola@company.net", labels=SENT, annotations=OPTIONAL))
    ns = yaml.safe_load(files["clusters/OCP_GF15/namespaces/abc-rnd/namespace.yaml"])
    company = {k: v for k, v in ns["metadata"]["labels"].items() if not k.startswith("cmapi.net/")}
    assert company == {"name": "abc-rnd", "company.net/app-environment": "rnd", "company.net/mnemonic": "abc",
                       "company.net/lob": "amgsst", "company.net/cl": "1"}
    assert ns["metadata"]["annotations"]["company.net/app-environment"] == "rnd"
    assert {k: ns["metadata"]["annotations"][k] for k in OPTIONAL} == OPTIONAL
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


@pytest.mark.parametrize("annotations, want", [
    ({}, []),                                                                        # optional: neither is required
    ({"company.net/mnemonic-group-contact": "abc-team@other.org"}, [("invalid_value", "company.net/mnemonic-group-contact")]),
    ({"company.net/mnemonic-group-contact": ""}, [("invalid_value", "company.net/mnemonic-group-contact")]),
    ({"company.net/mnemonic-confluence": "wiki.company.net/abc"}, [("invalid_value", "company.net/mnemonic-confluence")]),
    ({"company.net/mnemonic-confluence": "ftp://wiki.company.net/abc"}, [("invalid_value", "company.net/mnemonic-confluence")]),
])
def test_the_two_optional_keys_are_annotations_with_their_formats(keys, annotations, want):
    """The owner's decision on #234: company.net/mnemonic-group-contact is an address in emailDomains and
    company.net/mnemonic-confluence an http or https URL, each an optional annotation."""
    assert codes(keys.validate(SENT, annotations, operator=False, sources=SOURCES)) == want


@pytest.mark.parametrize("key", sorted(OPTIONAL))
def test_a_requester_cannot_send_either_optional_key_as_a_label(keys, key):
    errs = keys.validate({**SENT, key: ""}, {}, operator=False, sources=SOURCES)
    assert [(e["code"], e["key"], e["detail"]) for e in errs] == [("invalid_key", key, f"{key} is an annotation")]


# The owner's decision on #26: a required key that an existing namespace lacks is never forced, only reported. cmapi's
# own check holds it as the rendered policies do, and checks each value that a request sends.
HELD = {k: v for k, v in SENT.items() if k != "company.net/lob"}           # an adopted namespace with no line of business


def test_an_existing_namespace_that_lacks_a_required_key_takes_an_unrelated_change(keys):
    change = {"company.net/cl": "2"}
    assert keys.validate(change, {}, operator=False, sources=SOURCES, current_labels=HELD, existing=True) == []
    # A new namespace must still carry it.
    assert ("missing_required_key", "company.net/lob") in codes(keys.validate(HELD, {}, operator=False, sources=SOURCES))


def test_a_request_that_touches_the_held_key_must_give_a_valid_value(keys):
    for sent, want in (({"company.net/lob": "retail"}, ("invalid_value", "company.net/lob")),
                       ({"company.net/lob": None}, ("missing_required_key", "company.net/lob"))):
        assert want in codes(keys.validate(sent, {}, operator=False, sources=SOURCES, current_labels=HELD, existing=True))
    assert keys.validate({"company.net/lob": "amgsst"}, {}, operator=False, sources=SOURCES, current_labels=HELD,
                         existing=True) == []


def test_a_held_value_that_breaks_its_rule_is_not_checked_again(keys):
    """An adopted namespace whose mnemonic does not start its name keeps it through an unrelated change."""
    current = {**SENT, "company.net/mnemonic": "xyz"}
    assert keys.validate({"company.net/cl": "2"}, {}, operator=False, sources=SOURCES, current_labels=current,
                         existing=True) == []
    assert ("invalid_value", "company.net/mnemonic") in codes(
        keys.validate({"company.net/mnemonic": "xyz"}, {}, operator=False, sources=SOURCES, current_labels=current,
                      existing=True))
