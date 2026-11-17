"""OB3's review of #368: each refusal of a value names its kind, so a client puts it on the right field when one key is a
label and an annotation, each with its own rule (the portal's errorsByField reads item.kind; #336, design B D9)."""
from __future__ import annotations

from cmapi.core.metadata import MetadataKeys

RAW = {
    "system": [], "operatorOnly": [], "reservedPrefixes": [], "adoptionLabels": {}, "sensitiveKeys": [],
    "emailDomains": ["company.net"],
    "requiredLabels": {"x.io/both": {"pattern": "^a+$", "example": "a"}},
    "requiredAnnotations": {"x.io/both": {"pattern": "^b+$", "example": "b"}},
    "extraLabels": {"keys": {"x.io/lv": {"enum": ["a"]}}, "allowOther": {"prefixes": [], "max": 0}},
    "extraAnnotations": {"keys": {"x.io/mail": {"format": "email-in-domains"}},
                         "allowOther": {"prefixes": [], "max": 0, "maxValueBytes": 10, "maxBytesTotal": 10}},
}


def test_a_value_refusal_names_the_kind_of_the_map_it_is_in():
    keys = MetadataKeys(RAW)
    assert keys.validate({"x.io/both": "a"}, {"x.io/both": "c"}, operator=False) == [
        {"code": "invalid_value", "key": "x.io/both", "kind": "annotation", "detail": "must match ^b+$"}]
    assert keys.validate({"x.io/both": "c"}, {"x.io/both": "b"}, operator=False) == [
        {"code": "invalid_value", "key": "x.io/both", "kind": "label", "detail": "must match ^a+$"}]
    errs = keys.validate({"x.io/both": "a", "x.io/lv": "a b"}, {"x.io/both": "b", "x.io/mail": "x@y.org"}, operator=False)
    assert [(e["key"], e.get("kind")) for e in errs] == [("x.io/lv", "label"), ("x.io/mail", "annotation")], errs
