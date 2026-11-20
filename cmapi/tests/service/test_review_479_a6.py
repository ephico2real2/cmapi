from pathlib import Path
import pytest
from cmapi.main import openapi_document
from cmapi.plugins.expiration.rules import ExpirationRules
from cmapi.tools.openapi import load


@pytest.mark.parametrize("policy,dated", [({}, True), ({"enabled": False}, False), ({"allowedAtCreate": False}, False)])
def test_create_offers_a_complete_dated_example_only_when_the_target_accepts_it(policy, dated):
    path = Path(__file__).resolve().parents[3] / "examples/cluster-configs/policies/metadata-keys.yaml"
    cfg = load(path, None)
    cfg.expiration = ExpirationRules({"environments": {"dev": policy}})
    spec = openapi_document(cfg, {"CRC": "dev"})
    op = spec["paths"]["/api/v1/clusters/{cluster_id}/namespaces"]["post"]
    media = op["requestBody"]["content"]["application/json"]
    assert "example" not in media
    examples = media["examples"]
    permanent = examples["permanent"]["value"]
    assert "expiresAt" not in permanent and permanent["labels"] and permanent["annotations"]
    assert ("withExpiry" in examples) == dated
    if dated:
        day = spec["components"]["schemas"]["NamespaceCreate"]["properties"]["expiresAt"]["examples"][0]
        assert examples["withExpiry"]["value"] == {**permanent, "expiresAt": day}
