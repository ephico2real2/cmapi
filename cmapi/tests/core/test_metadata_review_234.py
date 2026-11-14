"""The Fable review of #234 (#215): a format a label cannot hold, an adoption label under an allowed prefix,
and limits that are not numbers. Each case fails on c830276."""
from __future__ import annotations

import copy

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from conftest import EX

COMPANY = EX / "cluster-configs/policies/metadata-keys.company.yaml"
SOURCES = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "OCP_GF15", "instance": "nonprod"}
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}


@pytest.fixture
def raw() -> dict:
    return copy.deepcopy(yaml.safe_load(COMPANY.read_text()))


def codes(errs):
    return sorted((e["code"], e.get("key")) for e in errs)


def test_the_loader_refuses_an_email_format_on_a_label(raw):
    # #215's example: extraLabels.keys.company.net/mnemonic-group-contact: {format: email-in-domains}. A label value
    # cannot hold "@", so the key would refuse every address, and the empty value of the owner's sample too.
    raw["extraLabels"]["keys"]["company.net/mnemonic-group-contact"] = {"format": "email-in-domains"}
    with pytest.raises(ValueError, match="format email-in-domains is for annotations only"):
        MetadataKeys(raw)


def test_an_email_format_on_an_annotation_still_loads_and_checks(raw):
    raw["extraAnnotations"]["keys"]["company.net/mnemonic-group-contact"] = {"format": "email-in-domains"}
    keys = MetadataKeys(raw)
    assert keys.validate(SENT, {"company.net/mnemonic-group-contact": "abc-team@company.net"}, operator=False, sources=SOURCES) == []
    assert codes(keys.validate(SENT, {"company.net/mnemonic-group-contact": "abc-team@other.org"}, operator=False,
                               sources=SOURCES)) == [("invalid_value", "company.net/mnemonic-group-contact")]


def test_a_requester_cannot_set_an_adoption_label_when_allow_other_admits_its_prefix(raw):
    raw["extraLabels"]["allowOther"]["prefixes"] = ["", "company.net/"]
    keys = MetadataKeys(raw)
    assert keys.classify("company.net/provisioner", "label") == "reserved"
    assert codes(keys.validate({**SENT, "company.net/provisioner": "cluster-configs"}, {}, operator=False,
                               sources=SOURCES)) == [("reserved_key", "company.net/provisioner")]
    # another key of the same prefix is still a team key
    assert keys.validate({**SENT, "company.net/owner": "ola"}, {}, operator=False, sources=SOURCES) == []


@pytest.mark.parametrize("key, spec, message", [
    ("cmapi.net/managed", {"recognise": ["true"]}, "a system or operator-only key is not an adoption label"),
    ("not a key", {"recognise": ["x"]}, "not a valid label key and values"),
    ("company.net/provisioner", {"recognise": ["cluster configs"]}, "not a valid label key and values"),
])
def test_the_loader_refuses_a_bad_adoption_label(raw, key, spec, message):
    raw["adoptionLabels"] = {key: spec}
    with pytest.raises(ValueError, match=message):
        MetadataKeys(raw)


@pytest.mark.parametrize("stanza, field, value", [
    ("extraLabels", "max", -1),               # c830276: loads, and then every other key is "too many"
    ("extraLabels", "max", True),             # c830276: loads as 1
    ("extraAnnotations", "maxValueBytes", None),   # c830276: loads, and then every annotation is "too large"
    ("extraAnnotations", "maxBytesTotal", "64k"),  # c830276: loads, and the first annotation raises TypeError
])
def test_the_loader_refuses_a_limit_that_is_not_a_whole_number(raw, stanza, field, value):
    raw[stanza]["allowOther"][field] = value
    with pytest.raises(ValueError, match=rf"{stanza}\.allowOther\.{field} must be a whole number"):
        MetadataKeys(raw)


def test_the_shipped_copies_still_load():
    for path in ("cluster-configs/policies/metadata-keys.yaml", "cluster-configs/policies/metadata-keys.company.yaml",
                 "local/config/metadata-keys.yaml"):
        MetadataKeys.load(EX / path)


def test_a_key_of_the_other_kind_is_refused_when_allow_other_admits_its_prefix(raw):
    # 527eedb: accepted as a team label, so the address lands where the owner decided it does not go.
    raw["extraLabels"]["allowOther"]["prefixes"] = ["", "company.net/"]
    keys = MetadataKeys(raw)
    errs = keys.validate({**SENT, "company.net/mnemonic-confluence": "abc"}, {}, operator=False, sources=SOURCES)
    assert [(e["code"], e["key"], e["detail"]) for e in errs] == [
        ("invalid_key", "company.net/mnemonic-confluence", "company.net/mnemonic-confluence is an annotation")]
