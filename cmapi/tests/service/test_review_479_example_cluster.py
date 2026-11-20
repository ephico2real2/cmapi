from pathlib import Path
from cmapi.core.metadata import MetadataKeys
from cmapi.main import openapi_document
from cmapi.tools.openapi import load


def test_create_curl_and_derived_values_target_a_configured_cluster_when_crc_is_absent():
    path = Path(__file__).resolve().parents[3] / "examples/cluster-configs/policies/metadata-keys.yaml"
    cfg = load(path, None)
    cfg.metadata = MetadataKeys({"requiredLabels": {"target": {"value": {"from": "cluster"}},
                               "env": {"value": {"from": "environment"}, "namespaceSuffix": True}}})
    op = openapi_document(cfg, {"NEWS_DEV": "dev"})["paths"]["/api/v1/clusters/{cluster_id}/namespaces"]["post"]
    example = op["requestBody"]["content"]["application/json"]["examples"]["permanent"]["value"]
    assert example["labels"] == {"target": "NEWS_DEV", "env": "dev"}
    assert example["namespace"].endswith("-dev")
    assert "/clusters/NEWS_DEV/namespaces" in op["x-codeSamples"][0]["source"]
