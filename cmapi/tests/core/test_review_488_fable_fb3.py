"""#479, Fable's review of PR #488, FB3: no name error is built on a mnemonic that step 5 refuses."""
from __future__ import annotations

from cmapi.core.metadata import MetadataKeys

KEYS = MetadataKeys({"requiredLabels": {
    "mnemonic": {"pattern": "^[a-z]{3,4}$", "namespacePrefix": True, "example": "abc"},
    "env": {"value": {"from": "environment"}, "namespaceSuffix": True},
}})


def create(labels: dict, namespace: str) -> list[tuple[str, str]]:
    found = KEYS.validate(labels, {}, operator=False, create=True, sources={"namespace": namespace, "environment": "dev"})
    return [(e["code"], e["key"]) for e in found]


def test_a_refused_mnemonic_gets_no_desired_name_error_on_the_environment_key():
    assert create({"mnemonic": "ab"}, "ab-dev") == [("invalid_value", "mnemonic")]
    assert create({"mnemonic": "abcde"}, "abcde--dev") == [("invalid_value", "mnemonic")]


def test_an_accepted_mnemonic_still_needs_a_desired_name():
    assert create({"mnemonic": "abc"}, "abc-dev") == [("invalid_value", "env")]
    assert create({"mnemonic": "abc"}, "abc-x-dev") == []
