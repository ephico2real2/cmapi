"""OB3's review of #368: an emailDomains entry is a domain name whose labels hold 1 to 63 characters (RFC 1035, 2.3.4).
The portal's <input type=email> (#336) checks HTML's "valid e-mail address", whose labels hold at most 63: with a longer
label, the browser refused every address that cmapi accepted (Chromium 156, 12 of 12 such addresses)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cmapi.core import metadata
from cmapi.core.metadata import MetadataKeys

REPO = Path(__file__).resolve().parents[3]
# HTML Living Standard, 4.10.5.1.5 (input type=email): the domain part of a valid e-mail address.
HTML_DOMAIN = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")


def raw(domains: list[str]) -> dict:
    return {"system": [], "operatorOnly": [], "reservedPrefixes": [], "adoptionLabels": {}, "sensitiveKeys": [],
            "emailDomains": domains, "requiredLabels": {}, "requiredAnnotations": {},
            "extraLabels": {"keys": {}, "allowOther": {"prefixes": [], "max": 0}},
            "extraAnnotations": {"keys": {"x.io/dl": {"format": "email-in-domains"}},
                                 "allowOther": {"prefixes": [], "max": 0, "maxValueBytes": 1, "maxBytesTotal": 1}}}


@pytest.mark.parametrize("label", ["a" * 64, "A" + "-" * 62 + "b"])
def test_a_domain_label_over_63_characters_is_refused(label):
    with pytest.raises(ValueError, match="are not domain names"):
        MetadataKeys(raw([f"{label}.example.org"]))


def test_a_63_character_label_loads_and_every_accepted_domain_is_an_html_email_domain():
    MetadataKeys(raw(["a" * 63 + ".example.org", "Sub.Example-1.Org"]))
    for n in range(1, 70):
        for label in ("a" * n, "a" + "-" * max(n - 2, 0) + "b" if n > 1 else "a"):
            domain = f"{label}.example.org"
            assert bool(metadata._DOMAIN.fullmatch(domain)) == bool(HTML_DOMAIN.fullmatch(domain)), domain


def test_the_chart_schema_says_the_same_pattern():
    schema = json.loads((REPO / "deploy/helm/cmapi/values.schema.json").read_text())
    domains = schema["properties"]["metadata"]["properties"]["emailDomains"]["items"]
    assert domains["pattern"] == metadata._DOMAIN.pattern
