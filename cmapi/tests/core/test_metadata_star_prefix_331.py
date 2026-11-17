"""#331: an allowOther prefix pattern names a prefix, so it never admits a key with no prefix; only "" does.

docs/18 (allowOther) and docs/02 ("Labels and annotations"): "`""` allows a key with no prefix. A `*` matches, as in
`*.company.net/`". Kubernetes' own words for the two kinds of key (concepts/overview/working-with-objects/labels): "If the
prefix is omitted, the label Key is presumed to be private to the user", and a prefix is "a DNS subdomain" followed by
"/". fnmatchcase("", "*") is true, so before the fix a pattern that matches the empty string admitted unprefixed keys too.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from conftest import EX

REFERENCE = EX / "cluster-configs/policies/metadata-keys.yaml"
LABELS = {"cmapi.net/team": "payments"}
ANNOTATIONS = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(REFERENCE.read_text())


def with_prefixes(raw: dict, prefixes: list[str]) -> MetadataKeys:
    out = copy.deepcopy(raw)
    for stanza in ("extraLabels", "extraAnnotations"):
        out[stanza]["allowOther"]["prefixes"] = prefixes
    return MetadataKeys(out)


@pytest.mark.parametrize("pattern", ["*", "**", "*/"])
@pytest.mark.parametrize("kind", ["label", "annotation"])
def test_a_pattern_does_not_admit_a_key_with_no_prefix(raw, pattern, kind):
    keys = with_prefixes(raw, [pattern])
    labels = {**LABELS, "foo": "x"} if kind == "label" else LABELS
    annotations = {**ANNOTATIONS, "foo": "x"} if kind == "annotation" else ANNOTATIONS
    assert keys.classify("foo", kind) == "disallowed"
    assert keys.validate(labels, annotations, operator=False) == [
        {"code": "invalid_key", "key": "foo", "detail": "prefix not allowed"}]


@pytest.mark.parametrize("kind", ["label", "annotation"])
def test_star_still_admits_each_prefixed_key_that_is_not_reserved(raw, kind):
    keys = with_prefixes(raw, ["*"])
    assert keys.classify("team.example/foo", kind) == "team"
    assert keys.classify("kubernetes.io/foo", kind) == "reserved"
    assert keys.classify("cmapi.net/tier", kind) == "system"


@pytest.mark.parametrize("kind", ["label", "annotation"])
def test_the_empty_prefix_entry_admits_a_key_with_no_prefix(raw, kind):
    for prefixes in ([""], ["", "*"], ["/"]):
        assert with_prefixes(raw, prefixes).classify("foo", kind) == "team", prefixes


def test_the_reference_config_is_unchanged(raw):
    # The shipped lists, ["", "*.ephico2real.com/"]: unprefixed keys and the company's subdomains, nothing else.
    keys = MetadataKeys(raw)
    assert [keys.classify(k, "label") for k in ("foo", "team.ephico2real.com/x", "ephico2real.com/x", "other.io/x")] == [
        "team", "team", "disallowed", "disallowed"]
