"""#739: the keys a namespace lacks and a request may add (MetadataKeys.missing_keys), and the adopted folder with them.

missing_keys is what the candidates list, the adoption plan and the namespace read return, and what the portal pre-fills. Its
`value` must be one that the change rule of #732 accepts (MetadataKeys.validate with existing=True), or the form would offer
a value that the API refuses.
"""
import pytest
import yaml

from cmapi.core.adoption import AdoptionSettings, Owner, adopted_files, snapshot
from cmapi.core.metadata import MetadataKeys

TARGET = {"namespace": "abc-pay-dev", "environment": "dev", "cluster": "CRC", "instance": "nonprod"}


def keys_of(labels=None, annotations=None, extra=None):
    raw = {"requiredLabels": labels or {}, "requiredAnnotations": annotations or {}}
    if extra:
        raw["extraLabels"] = {"keys": extra}
    return MetadataKeys(raw)


def accepted(keys, kind, key, value, sources=TARGET):
    sent = {key: value}
    return keys.validate(sent if kind == "label" else {}, sent if kind == "annotation" else {}, operator=False,
                         existing=True, sources=sources) == []


@pytest.mark.parametrize("source", TARGET)
def test_a_derived_key_offers_its_source_which_a_change_accepts(source):
    keys = keys_of({"unit": {"value": {"from": source}}})
    assert keys.missing_keys({}, {}, TARGET) == [{"kind": "label", "key": "unit", "required": True, "value": TARGET[source]}]
    assert accepted(keys, "label", "unit", TARGET[source])


@pytest.mark.parametrize("instance", ["", "Not A Label", "x" * 64])
def test_a_derived_key_with_no_valid_value_is_not_offered(instance):
    keys = keys_of({"unit": {"value": {"from": "instance"}}})
    assert keys.missing_keys({}, {}, {**TARGET, "instance": instance}) == []


@pytest.mark.parametrize("namespace, rule, value", [
    ("abc-pay-dev", {"pattern": "^[a-z]{3,4}$", "example": "abc"}, "abc"),
    ("abcd-pay-dev", {"pattern": "^[a-z]{3,4}$", "example": "abc"}, "abcd"),
    ("ab-cde-dev", {"pattern": "^[a-z-]{4,8}$", "example": "ab-cde"}, "ab-cde"),   # the shortest start that keeps the rule
    ("abc-pay-dev", {"enum": ["abc-pay"], "example": "abc-pay"}, "abc-pay"),
    ("abc-pay-dev", {"example": "abc"}, "abc"),
])
def test_the_prefix_key_offers_the_shortest_start_that_keeps_its_rule(namespace, rule, value):
    keys = keys_of({"mnemonic": {"namespacePrefix": True, **rule}})
    sources = {**TARGET, "namespace": namespace}
    assert keys.missing_keys({}, {}, sources) == [{"kind": "label", "key": "mnemonic", "required": True, "value": value}]
    assert accepted(keys, "label", "mnemonic", value, sources)


@pytest.mark.parametrize("namespace", ["abcpaydev", "ab-cd-ef"])
def test_a_prefix_key_with_no_valid_start_is_not_offered(namespace):
    keys = keys_of({"mnemonic": {"namespacePrefix": True, "pattern": "^[a-z]{3,4}$", "example": "abc"}})
    assert keys.missing_keys({}, {}, {**TARGET, "namespace": namespace}) == []


def test_the_suffix_key_is_never_offered():
    keys = keys_of({"env": {"namespaceSuffix": True, "example": "dev"}})
    assert keys.missing_keys({}, {}, TARGET) == []


@pytest.mark.parametrize("held", ["legacy", ""])
def test_a_key_the_namespace_holds_is_not_offered_also_empty(held):
    keys = keys_of({"name": {"value": {"from": "namespace"}}, "team": {"pattern": "^[a-z]+$", "example": "abc"}})
    assert [m["key"] for m in keys.missing_keys({"name": held, "team": held}, {}, TARGET)] == []


def test_required_keys_come_first_then_the_optional_ones_with_no_value():
    keys = keys_of({"team": {"pattern": "^[a-z]+$", "example": "abc"}}, {"dl": {"format": "url", "example": "https://wiki.example/abc"}},
                   extra={"app": {"pattern": "^[a-z]+$"}})
    assert keys.missing_keys({}, {}, TARGET) == [
        {"kind": "label", "key": "team", "required": True, "value": None},
        {"kind": "annotation", "key": "dl", "required": True, "value": None},
        {"kind": "label", "key": "app", "required": False, "value": None}]


def test_the_adopted_namespace_gets_the_added_keys_and_its_other_objects_and_the_snapshot_do_not():
    live = {"metadata": {"name": "abc-rnd", "uid": "u", "resourceVersion": "1", "labels": {"cmapi.net/adopt": "true"},
                         "annotations": {"a": "1"}}}
    quota = {"metadata": {"name": "q", "uid": "uq", "resourceVersion": "2"}, "spec": {"hard": {"pods": "10"}}}
    snap, _ = snapshot(live, [quota], [], AdoptionSettings())
    keys = MetadataKeys({"requiredLabels": {"cmapi.net/team": {"pattern": "^[a-z]+$", "example": "abc"}}})
    owner = Owner("CRC", "nonprod", "dev", "custom", "(planned)", "ola", None)
    added = {"label": {"cmapi.net/team": "abc"}, "annotation": {"b": "2"}}
    files, replaced = adopted_files(snap, owner, keys, added)
    ns = yaml.safe_load(files["clusters/CRC/namespaces/abc-rnd/namespace.yaml"])["metadata"]
    assert ns["labels"]["cmapi.net/team"] == "abc" and ns["labels"]["cmapi.net/adopt"] == "true"
    assert ns["annotations"]["b"] == "2" and ns["annotations"]["a"] == "1"
    rq = yaml.safe_load(files["clusters/CRC/namespaces/abc-rnd/resourcequota-q.yaml"])["metadata"]
    assert "cmapi.net/team" not in rq["labels"] and "b" not in rq["annotations"]
    assert replaced == [] and "cmapi.net/team" not in snap.namespace["metadata"]["labels"]
    assert adopted_files(snap, owner, keys)[0] == adopted_files(snap, owner, keys, {"label": {}, "annotation": {}})[0]


def test_derived_environment_suffix_is_not_offered():
    keys = keys_of({"env": {"value": {"from": "environment"}, "namespaceSuffix": True}})
    assert keys.missing_keys({}, {}, TARGET) == []
