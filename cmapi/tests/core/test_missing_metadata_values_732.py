"""Exact additions on PATCH, and the Git and create rules on either side of that exception."""
import pytest

from cmapi.core.metadata import MetadataKeys


TARGET = {"namespace": "abc-pay-dev", "environment": "dev", "cluster": "CRC", "instance": "nonprod"}


def check(kind, rule, value, *, current=None, sources=TARGET, create=False):
    key = "unit"
    keys = MetadataKeys({"required" + kind.title() + "s": {key: {"example": "abc", **rule}}})
    sent = {key: value}
    return keys.validate(sent if kind == "label" else {}, sent if kind == "annotation" else {},
                         operator=False, create=create, existing=not create, sources=sources,
                         **{"current_" + kind + "s": current or {}})


@pytest.mark.parametrize("source", TARGET)
@pytest.mark.parametrize("kind", ["label", "annotation"])
def test_missing_automatic_accepts_exact_source(kind, source):
    assert check(kind, {"value": {"from": source}}, TARGET[source]) == []


@pytest.mark.parametrize("value", ["DEV", " dev", "dev ", "deｖ", "dеv", "de", "dev-x", "", None])
def test_missing_automatic_rejects_changed_text(value):
    errors = check("annotation", {"value": {"from": "environment"}}, value)
    assert [(e["code"], e["key"]) for e in errors] == [("derived_key", "unit")]


@pytest.mark.parametrize("kind", ["label", "annotation"])
@pytest.mark.parametrize("value,accepted", [("abc", True), ("abc-pay", True), ("ABC", False), ("abc ", False),
                                           ("ａｂｃ", False), ("аbc", False), ("ab", False), ("bc", False),
                                           ("pay", False), ("abc-pay-dev", False), ("", False)])
def test_missing_prefix_needs_a_complete_delimited_start(kind, value, accepted):
    errors = check(kind, {"namespacePrefix": True}, value)
    assert [e["code"] for e in errors] == ([] if accepted else ["invalid_value"])


def test_a_delimited_start_must_also_pass_its_rule():
    errors = check("label", {"namespacePrefix": True, "enum": ["abc"]}, "abc-pay")
    assert [e["code"] for e in errors] == ["invalid_value"]


@pytest.mark.parametrize("held", ["legacy", ""])
@pytest.mark.parametrize("rule,value,refused,removed", [
    ({"value": {"from": "namespace"}}, "abc-pay-dev", "derived_key", "derived_key"),
    ({"namespacePrefix": True}, "abc", "invalid_value", "missing_required_key"),
])
def test_present_key_cannot_be_repaired_or_removed(held, rule, value, refused, removed):
    current = {"unit": held}
    assert [e["code"] for e in check("label", rule, value, current=current)] == [refused]
    assert [e["code"] for e in check("label", rule, None, current=current)] == [removed]


def test_suffix_alone_stays_fixed_when_missing():
    assert [e["code"] for e in check("label", {"namespaceSuffix": True}, "dev")] == ["invalid_value"]


def test_unknown_source_refuses_an_addition():
    assert [e["code"] for e in check("annotation", {"value": {"from": "instance"}}, "", sources={})] == ["derived_key"]


@pytest.mark.parametrize("source", ["west coast", "a" * 64])
def test_a_new_exact_derived_label_must_still_be_a_valid_label(source):
    rule = {"value": {"from": "instance"}}
    for create in (True, False):
        errors = check("label", rule, source, create=create, sources={"instance": source})
        assert [e["code"] for e in errors] == ["invalid_value"]
    assert check("annotation", rule, source, sources={"instance": source}) == []


def test_an_empty_source_fills_no_value_to_add():
    rule = {"value": {"from": "instance"}}
    sources = {"instance": ""}
    keys = MetadataKeys({"requiredAnnotations": {"unit": rule}})
    assert "unit" not in keys.filled({}, {}, sources)["annotation"]
    assert [e["code"] for e in check("annotation", rule, "", sources=sources)] == ["derived_key"]


@pytest.mark.parametrize("source", ["", "west coast"])
def test_the_remedy_never_offers_an_addition_that_a_change_refuses(source):
    keys = MetadataKeys({"requiredLabels": {"unit": {"value": {"from": "instance"}}}})
    assert keys.remedy("label", "unit", {"instance": source}) == "a change cannot add it: the instance gives no valid value"
    assert keys.remedy("label", "unit", {"instance": "nonprod"}) == \
        "a request can add it with the value cmapi derives from the instance (nonprod)"
