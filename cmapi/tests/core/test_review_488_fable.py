"""#479, Fable's review of PR #488. Each test names one behaviour of validate()."""
from __future__ import annotations

from cmapi.core.metadata import MetadataKeys

KEYS = MetadataKeys({"requiredLabels": {
    "mnemonic": {"pattern": "^[a-z]{3,4}$", "namespacePrefix": True, "example": "abc"},
    "env": {"value": {"from": "environment"}, "namespaceSuffix": True},
    "team": {"pattern": "^[a-z0-9-]{2,40}$", "default": {"from": "mnemonic"}, "example": "payments"},
}})
# A namespace named before the file had namespacePrefix: Git holds mnemonic abc on a name that does not start with abc-.
LEGACY = dict(operator=False, existing=True, current_labels={"mnemonic": "abc", "env": "dev", "team": "abc"},
              sources={"namespace": "legacy-app", "environment": "dev"})


def errors(found: list[dict]) -> list[tuple[str, str]]:
    return [(e["code"], e["key"]) for e in found]


# ---- FB1: the start of the name, as its end (F06), is not checked again on a value that Git holds
def test_a_patch_that_sends_back_the_mnemonic_of_a_namespace_named_before_the_rule_is_accepted():
    assert KEYS.validate({"mnemonic": "abc"}, {}, **LEGACY) == []
    assert KEYS.validate({"mnemonic": "abc", "env": "dev", "team": "abc"}, {}, **LEGACY) == []


def test_a_patch_that_changes_the_mnemonic_is_still_checked_against_the_name():
    assert errors(KEYS.validate({"mnemonic": "abd"}, {}, **LEGACY)) == [("invalid_value", "mnemonic")]
    assert errors(KEYS.validate({"mnemonic": "ABC"}, {}, **LEGACY)) == [("invalid_value", "mnemonic")]


def test_a_create_is_still_checked_against_the_name():
    found = KEYS.validate({"mnemonic": "abc"}, {}, operator=False, create=True,
                          sources={"namespace": "legacy-app-dev", "environment": "dev"})
    assert errors(found) == [("invalid_value", "mnemonic")]


# ---- FB2: one fault, one error: a team copied from a refused mnemonic is not refused for the same value
def test_a_refused_mnemonic_is_not_reported_again_on_the_team_copied_from_it():
    sources = {"namespace": "abc-payments-dev", "environment": "dev"}
    for mnemonic in ("ABC", "a", "ab"):
        found = KEYS.validate({"mnemonic": mnemonic}, {}, operator=False, create=True, sources=sources)
        assert errors(found) == [("invalid_value", "mnemonic")], mnemonic


def test_an_empty_mnemonic_copies_nothing_so_the_team_is_still_reported_missing():
    found = KEYS.validate({"mnemonic": ""}, {}, operator=False, create=True,
                          sources={"namespace": "abc-payments-dev", "environment": "dev"})
    assert errors(found) == [("invalid_value", "mnemonic"), ("missing_required_key", "team")]


def test_a_team_that_the_request_sends_keeps_its_own_error_beside_the_mnemonic_s():
    found = KEYS.validate({"mnemonic": "ABC", "team": "P"}, {}, operator=False, create=True,
                          sources={"namespace": "abc-payments-dev", "environment": "dev"})
    assert errors(found) == [("invalid_value", "mnemonic"), ("invalid_value", "team")]


def test_a_default_that_breaks_its_own_pattern_from_an_accepted_source_is_still_refused():
    keys = MetadataKeys({"requiredLabels": {
        "mnemonic": {"pattern": "^[a-z]{3,4}$", "example": "abc"},
        "team": {"pattern": "^[a-z]{4}$", "default": {"from": "mnemonic"}, "example": "abcd"}}})
    found = keys.validate({"mnemonic": "abc"}, {}, operator=False, create=True, sources={"namespace": "abc-x-dev"})
    assert errors(found) == [("invalid_value", "team")]
