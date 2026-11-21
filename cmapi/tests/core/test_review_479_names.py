"""#479, review of PR #488: the namespace name rules of validate() and the loader (findings F06, F08, F10, F11, F12,
F17, F18 and F23 of the review). Each test names one behaviour."""
from __future__ import annotations

import pytest

from cmapi.core.metadata import MetadataKeys

NAME_KEYS = {"requiredLabels": {
    "mnemonic": {"pattern": "^[a-z]{3,4}$", "namespacePrefix": True, "example": "abc"},
    "env": {"value": {"from": "environment"}, "namespaceSuffix": True},
}}


def create(keys: MetadataKeys, labels: dict, namespace: str, environment: str = "dev") -> list[tuple[str, str]]:
    errors = keys.validate(labels, {}, operator=False, create=True,
                           sources={"namespace": namespace, "environment": environment})
    return [(e["code"], e["key"]) for e in errors]


# ---- F06: the end of the name is a create's check
def test_a_patch_that_sends_back_the_environment_of_a_namespace_named_before_the_rule_is_accepted():
    keys = MetadataKeys({"requiredLabels": {"env": {"value": {"from": "environment"}, "namespaceSuffix": True}}})
    patch = dict(operator=False, existing=True, current_labels={"env": "dev"},
                 sources={"namespace": "legacy", "environment": "dev"})
    assert keys.validate({"env": "dev"}, {}, **patch) == []
    assert [e["code"] for e in keys.validate({"env": "rnd"}, {}, **patch)] == ["derived_key"]


def test_a_create_without_the_environment_suffix_is_still_refused_on_the_environment_key():
    keys = MetadataKeys({"requiredLabels": {"env": {"value": {"from": "environment"}, "namespaceSuffix": True}}})
    assert create(keys, {}, "legacy") == [("invalid_value", "env")]


# ---- F08: the two ends alone, or with a desired name between them
@pytest.mark.parametrize("namespace,environment,accepted", [
    ("abc-dev", "dev", True), ("abc--dev", "dev", False), ("abc-payments-dev", "dev", True),
    ("abc-dev", "rnd", False), ("abc-x-dev", "dev", True), ("abc-payments-api-dev", "dev", True),
    ("abc--x-rnd", "rnd", False), ("abc-x--rnd", "rnd", False), ("abc---rnd", "rnd", False),
    ("abc-x-y-rnd", "rnd", True), ("abc-x--y-rnd", "rnd", True), ("abc-1-rnd", "rnd", True),
])
def test_a_create_accepts_team_wide_and_named_namespaces(namespace, environment, accepted):
    assert create(MetadataKeys(NAME_KEYS), {"mnemonic": "abc"}, namespace, environment) == \
        ([] if accepted else [("invalid_value", "env")])


def test_dashed_ends_are_matched_whole_in_both_name_forms():
    keys = MetadataKeys({"requiredLabels": {
        "owner": {"namespacePrefix": True, "example": "ab-c"},
        "env": {"value": {"from": "environment"}, "namespaceSuffix": True}}})
    assert create(keys, {"owner": "ab-c"}, "ab-c-payments-qa-dev", "qa-dev") == []
    assert create(keys, {"owner": "ab-c"}, "ab-c-qa-dev", "qa-dev") == []
    assert create(keys, {"owner": "ab-c"}, "ab-c--qa-dev", "qa-dev") == [("invalid_value", "env")]


# ---- F11: one error for one empty required key
def test_an_empty_mnemonic_that_breaks_its_pattern_has_one_error_on_its_field():
    assert create(MetadataKeys(NAME_KEYS), {"mnemonic": ""}, "abc-payments-dev") == [("invalid_value", "mnemonic")]


def test_an_empty_mnemonic_with_no_pattern_is_a_missing_key_and_no_name_error():
    keys = MetadataKeys({"requiredLabels": {"mnemonic": {"namespacePrefix": True, "example": "abc"}}})
    assert create(keys, {"mnemonic": ""}, "abc-payments-dev") == [("missing_required_key", "mnemonic")]
    assert create(keys, {}, "abc-payments-dev") == [("missing_required_key", "mnemonic")]


# ---- F12: one key starts or ends the name, not both
def test_a_key_that_both_starts_and_ends_the_name_is_refused_at_load():
    with pytest.raises(ValueError, match="starts the namespace name or ends it, not both"):
        MetadataKeys({"requiredLabels": {"token": {"example": "abc", "namespacePrefix": True,
                                                   "namespaceSuffix": True}}})


# ---- F18: the words of the name rules hold for dashed values
def test_the_rule_words_of_the_two_ends_hold_for_values_that_contain_a_dash():
    keys = MetadataKeys({"requiredLabels": {
        "owner": {"namespacePrefix": True, "example": "ab-c"},
        "env": {"value": {"from": "environment"}, "namespaceSuffix": True}}})
    fields = keys.keys_view()["labels"]["properties"]
    assert fields["owner"]["x-cmapi-rule"] == "the namespace name starts with this value and '-'"
    assert fields["env"]["x-cmapi-rule"].endswith("; the namespace name ends with '-' and this value")


# ---- F10: a default may copy a filled-in key
def test_a_default_from_a_filled_in_key_loads_and_copies_its_filled_value():
    keys = MetadataKeys({"requiredLabels": {
        "name": {"value": {"from": "namespace"}},
        "team": {"default": {"from": "name"}, "example": "payments"}}})
    sources = {"namespace": "abc-payments-dev"}
    assert keys.filled({}, {}, sources)["label"]["team"] == "abc-payments-dev"
    assert keys.filled({"team": "payments"}, {}, sources)["label"]["team"] == "payments"


def test_a_chain_of_defaults_is_still_refused_at_load():
    with pytest.raises(ValueError, match="has a default itself"):
        MetadataKeys({"extraLabels": {"keys": {"a": {}, "b": {"default": {"from": "a"}},
                                               "c": {"default": {"from": "b"}}}}})


def test_an_empty_mnemonic_fills_no_team_so_the_team_is_reported_missing_not_wrong():
    keys = MetadataKeys({"requiredLabels": {
        "mnemonic": {"pattern": "^[a-z]{3,4}$", "example": "abc"},
        "team": {"pattern": "^[a-z0-9-]{2,40}$", "default": {"from": "mnemonic"}, "example": "payments"}}})
    assert create(keys, {"mnemonic": ""}, "abc-payments-dev") == [("invalid_value", "mnemonic"),
                                                                  ("missing_required_key", "team")]


# ---- F17: a PATCH never fills a default, so its schema does not offer one
def test_a_patch_schema_does_not_advertise_the_create_only_default():
    keys = MetadataKeys({"requiredLabels": {"owner": {"example": "abc"},
                                            "team": {"example": "payments", "default": {"from": "owner"}}}})
    create_team = keys.json_schema("label", "create")["properties"]["team"]
    patch_team = keys.json_schema("label", "patch")["properties"]["team"]
    assert create_team["x-cmapi-default-from"] == "owner"
    assert "x-cmapi-default-from" not in patch_team
    assert "default: the value" not in patch_team["description"].lower()


# ---- F23: allowOther.example is a map, or absent
@pytest.mark.parametrize("value", [False, 0, "", []])
def test_an_allow_other_example_that_is_not_a_map_is_refused_at_load(value):
    with pytest.raises(ValueError, match="extraLabels.allowOther.example must be a mapping"):
        MetadataKeys({"extraLabels": {"allowOther": {"example": value}}})


def test_a_null_allow_other_example_is_an_absent_one_as_for_every_stanza():
    assert MetadataKeys({"extraLabels": {"allowOther": {"example": None}}}).allow_other["label"].example == {}


# ---- F09 (rejected): a name is checked against its own cluster's environment only
def test_a_name_that_ends_with_another_configured_environment_is_valid_on_its_own_cluster():
    keys = MetadataKeys(NAME_KEYS)
    assert create(keys, {"mnemonic": "abc"}, "abc-payments-qa-dev", "dev") == []        # desired name payments-qa
    assert create(keys, {"mnemonic": "abc"}, "abc-payments-qa-dev", "qa-dev") == []     # desired name payments
    assert create(keys, {"mnemonic": "abc"}, "abc-payments-rnd", "dev") == [("invalid_value", "env")]


def test_a_mnemonic_that_breaks_its_pattern_gets_no_desired_name_error_too():
    assert create(MetadataKeys(NAME_KEYS), {"mnemonic": "ABC"}, "abc-dev") == [("invalid_value", "mnemonic")]
