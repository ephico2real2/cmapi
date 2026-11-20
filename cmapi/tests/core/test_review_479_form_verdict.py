from cmapi.core.metadata import MetadataKeys
from metadata_form_corpus import accepted


def test_form_oracle_accepts_an_omitted_default_and_refuses_an_omitted_wrong_suffix():
    keys = MetadataKeys({"requiredLabels": {
        "owner": {"example": "abc"}, "team": {"default": {"from": "owner"}, "example": "payments"},
        "env": {"value": {"from": "environment"}, "namespaceSuffix": True},
    }})
    from metadata_form_corpus import ENVIRONMENT
    assert accepted(keys, "label", "team", None, "abc-payments-" + ENVIRONMENT)
    assert not accepted(keys, "label", "team", "payments", "abc-payments-wrong")
