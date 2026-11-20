from pathlib import Path
from cmapi.core.metadata import MetadataKeys
from cmapi.main import openapi_document
from cmapi.tools.openapi import load


def test_plan_model_annotation_example_uses_only_configured_fields_and_domain():
    path = Path(__file__).resolve().parents[3] / "examples/cluster-configs/policies/metadata-keys.yaml"
    cfg = load(path, None)
    cfg.metadata = MetadataKeys({"requiredAnnotations": {"cnn.com/contact": {
        "format": "email-in-domains", "example": "payments@cnn.com"}}, "emailDomains": ["cnn.com"]})
    schemas = openapi_document(cfg)["components"]["schemas"]
    props = schemas["PlanMetadata"]["properties"]
    assert props["annotations"]["examples"] == [{"cnn.com/contact": {"value": "payments@cnn.com", "source": "request"}}]


def test_plan_model_examples_show_each_source_on_the_designs_file():
    import copy

    from test_namespace_contract_479 import DESIGN
    path = Path(__file__).resolve().parents[3] / "examples/cluster-configs/policies/metadata-keys.yaml"
    cfg = load(path, None)
    cfg.metadata = MetadataKeys(copy.deepcopy(DESIGN))
    props = openapi_document(cfg, {"CRC": "dev"})["components"]["schemas"]["PlanMetadata"]["properties"]
    labels = props["labels"]["examples"][0]
    assert props["namespace"]["examples"] == ["abc-payments-dev"]
    assert labels["name"] == {"value": "abc-payments-dev", "source": "namespace"}
    assert labels["company.net/app-environment"] == {"value": "dev", "source": "environment"}
    assert labels["cmapi.net/team"] == {"value": "abc", "source": "default:company.net/mnemonic"}
    assert labels["company.net/mnemonic"] == {"value": "abc", "source": "request"}
