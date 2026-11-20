from datetime import date

import pytest
from cmapi.core.docs import InstanceFacts, _document_expiry
from cmapi.core.errors import Problem
from cmapi.plugins.expiration.rules import ExpirationRules


def test_create_documentation_uses_allowed_at_create_in_addition_to_enabled():
    rules = ExpirationRules({"environments": {"dev": {"enabled": True, "allowedAtCreate": False}}})
    prop = {}
    spec = {"components": {"schemas": {"NamespaceCreate": {"properties": {"expiresAt": prop}}}}}
    _document_expiry(spec, InstanceFacts("np", "CRC", "dev", ("dev",), rules))
    assert "Refused with expiration-not-allowed at create in dev" in prop["description"]
    assert "Taken in dev" not in prop["description"]
    with pytest.raises(Problem) as exc:
        rules.plan_create("dev", date(2027, 1, 2), date(2027, 1, 1))
    assert exc.value.code == "expiration-not-allowed"
