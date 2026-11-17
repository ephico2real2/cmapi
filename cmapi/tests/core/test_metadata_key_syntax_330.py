"""#330: a key with a "/" and nothing before it ("/foo") has an empty prefix, which Kubernetes refuses; it is not a key
with no prefix.

The rule is apimachinery's IsLabelKey (pkg/api/validate/content/kube.go, which IsQualifiedName now aliases): at most one
"/", and when there is one, the prefix before it is non-empty ("prefix part must be non-empty") and a DNS-1123 subdomain.
The API server checks label keys with it, and annotation keys with it after lowercasing them (pkg/api/validation/
objectmeta.go, ValidateAnnotations). The two corpora below are the success and error cases of its own test,
TestIsLabelKey in kube_test.go (kubernetes/apimachinery at 52d6a18, read 2026-11-17).
"""
from __future__ import annotations

import copy

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from conftest import EX

REFERENCE = EX / "cluster-configs/policies/metadata-keys.yaml"
# The issue's call: a body that is valid but for the one key with an empty prefix.
LABELS = {"cmapi.net/team": "payments"}
ANNOTATIONS = {"cmapi.net/team-dl": "payments-team@ephico2real.com"}

K8S_VALID = ["simple", "now-with-dashes", "1-starts-with-num", "1234", "simple/simple", "now-with-dashes/simple",
             "now-with-dashes/now-with-dashes", "now.with.dots/simple", "now-with.dashes-and.dots/simple",
             "1-num.2-num/3-num", "1234/5678", "1.2.3.4/5678", "Uppercase_Is_OK_123", "example.com/Uppercase_Is_OK_123",
             "requests.storage-foo", "a" * 63, "a" * 253 + "/" + "b" * 63]
K8S_INVALID = ["nospecialchars%^=@", "cantendwithadash-", "-cantstartwithadash-", "only/one/slash", "Example.com/abc",
               "example_com/abc", "example.com/", "/simple", "a" * 64, "a" * 254 + "/abc"]


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(REFERENCE.read_text())


@pytest.fixture(scope="module")
def keys(raw) -> MetadataKeys:
    return MetadataKeys(raw)


def test_the_reference_config_admits_unprefixed_keys(raw):
    # The premise of the cases below: "" in allowOther admits a key with no prefix, so "/foo" passed as one.
    assert "" in raw["extraLabels"]["allowOther"]["prefixes"]
    assert "" in raw["extraAnnotations"]["allowOther"]["prefixes"]


@pytest.mark.parametrize("kind", ["label", "annotation"])
@pytest.mark.parametrize("key", ["/foo", "/simple", "/"])
def test_a_key_with_an_empty_prefix_is_refused(keys, kind, key):
    labels = {**LABELS, key: "x"} if kind == "label" else LABELS
    annotations = {**ANNOTATIONS, key: "x"} if kind == "annotation" else ANNOTATIONS
    assert keys.validate(labels, annotations, operator=False) == [{"code": "invalid_key", "key": key}]


def test_a_key_with_no_prefix_is_still_admitted(keys):
    assert keys.validate({**LABELS, "foo": "x"}, {**ANNOTATIONS, "foo": "x"}, operator=False) == []


@pytest.mark.parametrize("key", K8S_VALID)
def test_each_key_that_kubernetes_accepts_has_valid_syntax(keys, key):
    assert keys._syntax(key, None, "label") is None


@pytest.mark.parametrize("key", K8S_INVALID)
def test_each_key_that_kubernetes_refuses_is_invalid(keys, key):
    assert keys._syntax(key, None, "label") == {"code": "invalid_key", "key": key}


@pytest.mark.parametrize("stanza, kind", [("extraLabels", "label"), ("extraAnnotations", "annotation")])
def test_the_loader_refuses_a_declared_key_with_an_empty_prefix(raw, stanza, kind):
    bad = copy.deepcopy(raw)
    bad[stanza]["keys"] = {**(bad[stanza].get("keys") or {}), "/foo": {}}
    with pytest.raises(ValueError, match=rf"{stanza}\./foo: not a valid {kind} key"):
        MetadataKeys(bad)


def test_the_loader_refuses_an_adoption_label_with_an_empty_prefix(raw):
    bad = copy.deepcopy(raw)
    bad["adoptionLabels"] = {"/provisioner": {"recognise": ["cluster-configs"]}}
    with pytest.raises(ValueError, match=r"adoptionLabels\./provisioner: not a valid label key"):
        MetadataKeys(bad)
