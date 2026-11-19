"""The published import diagnostics and the expiry countdown, including rotation and retirement."""
from datetime import datetime, timedelta, timezone
import time

import yaml
from prometheus_client import REGISTRY

from cmapi.core.registry import DirImportSource
from conftest import build_world
from test_cluster_trust_434 import CA
from test_registry_survives_419 import good, registry, secret

ANNOTATION = "cmapi.net/token-expires-at"
METRIC = "cmapi_cluster_token_expiry_seconds"


def test_list_reports_the_import_and_last_remote_probe(test_config, keys, monkeypatch, tmp_path):
    imports = tmp_path / "imports"
    imports.mkdir()
    expiry = "2026-11-25T01:14:30Z"
    for cid, fields in (("CA", {"caData": CA(tmp_path, "issuer").pem}), ("SYSTEM", {}),
                        ("CRC", {"insecure": "true"})):
        doc = {"kind": "Secret", "metadata": {"name": cid.lower(), "labels": {"cmapi.net/cluster-id": cid},
                                               "annotations": {ANNOTATION: expiry}},
               "stringData": {"apiUrl": "https://example.test", "token": "fixture", **fields}}
        (imports / f"{cid}.yaml").write_text(yaml.safe_dump(doc))
    with build_world(test_config, keys, monkeypatch) as (client, ctx, *_):
        reg = ctx.registry
        reg.source = DirImportSource(imports)
        reg.insecure_environments = {"dev"}
        reg.refresh()
        headers = {"Authorization": "Bearer " + keys.token("reader", roles=["cmapi-viewer"])}

        def listed():
            response = client.get("/api/v1/clusters", headers=headers)
            assert response.status_code == 200
            return {item["clusterId"]: item for item in response.json()["items"]}

        rows = listed()
        for cid, mode in (("CA", "caData"), ("SYSTEM", "trusted"), ("CRC", "insecure")):
            row = rows[cid]
            assert row["trust"]["source"] == mode
            assert row["tokenExpiresAt"] == expiry
            assert row["secretName"] == cid.lower()
            assert row["lastProbeAt"] == row["checkedAt"]
            assert row["findingDetails"] == row["findings"] == []

        path = imports / "CRC.yaml"
        doc = yaml.safe_load(path.read_text())
        del doc["stringData"]["token"]
        path.write_text(yaml.safe_dump(doc))
        reg.refresh()
        invalid = listed()["CRC"]
        assert invalid["status"] == "invalid-secret"
        assert invalid["lastProbeAt"] == rows["CRC"]["lastProbeAt"]
        assert invalid["checkedAt"] != invalid["lastProbeAt"]
        assert invalid["findings"] == ["missing field token"]
        assert invalid["findingDetails"][0]["finding"] == invalid["findings"][0]
        assert "token" in invalid["findingDetails"][0]["fix"]

        path.unlink()
        reg.refresh()
        retired = listed()["CRC"]
        assert retired["secretName"] is retired["tokenExpiresAt"] is None
        assert retired["lastProbeAt"] == rows["CRC"]["lastProbeAt"]
        assert retired["findingDetails"][0]["fix"]


def test_expiry_series_counts_down_and_disappears(monkeypatch):
    cid = "EXPIRY"
    item = secret(cid)
    reg = registry({cid: good}, [item])
    now = datetime(2026, 11, 19, tzinfo=timezone.utc)
    monkeypatch.setattr(time, "time", lambda: now.timestamp())

    def remaining():
        return REGISTRY.get_sample_value(METRIC, {"cluster_id": cid})

    try:
        for value in (None, "bad timestamp", "2026-11-19T00:00:00", {"invalid": True}):
            item["annotations"] = {ANNOTATION: value}
            reg.refresh()
            assert reg.get(cid).status == "connected"
            assert remaining() is None
        item["annotations"] = {ANNOTATION: (now + timedelta(seconds=300)).isoformat()}
        reg.refresh()
        assert remaining() == 300
        now += timedelta(seconds=301)
        assert remaining() == -1
        item["annotations"] = {ANNOTATION: (now + timedelta(days=7)).isoformat()}
        reg.refresh()
        assert remaining() == 604800
        item["annotations"] = {}
        reg.refresh()
        assert remaining() is None
        item["annotations"] = {ANNOTATION: now.isoformat()}
        reg.refresh()
        assert remaining() == 0
        reg.source.secrets.clear()
        reg.refresh()
        assert remaining() is None
    finally:
        reg.stop()


def test_last_probe_is_recorded_when_local_cache_setup_fails():
    reg = registry({"ONE": good}, [secret("ONE")])

    def unavailable_nodes(st, client):
        raise OSError("node cache unavailable")

    reg.nodes_factory = unavailable_nodes
    try:
        reg.refresh()
        row = reg.get("ONE").view()
        assert row["status"] == "unreachable"
        assert row["lastProbeAt"] == row["checkedAt"] and row["lastProbeAt"] is not None
    finally:
        reg.stop()


def test_malformed_expiry_clears_view_and_series_without_normalizing_input():
    cid = "MALFORMED"
    item = secret(cid)
    reg = registry({cid: good}, [item])
    try:
        for invalid in ("2026-11-19T01:02:03+00:60", "2026-11-19X01:02:03Z", "20261119T010203Z"):
            item["annotations"][ANNOTATION] = "2026-11-19T01:02:03.456+01:30"
            reg.refresh()
            assert reg.get(cid).view()["tokenExpiresAt"] == datetime(2026, 11, 18, 23, 32, 3, 456000, timezone.utc)
            assert REGISTRY.get_sample_value(METRIC, {"cluster_id": cid}) is not None
            item["annotations"][ANNOTATION] = invalid
            reg.refresh()
            row = reg.probe(cid)
            assert row["status"] == "connected"
            assert row["tokenExpiresAt"] is None
            assert REGISTRY.get_sample_value(METRIC, {"cluster_id": cid}) is None
    finally:
        reg.stop()


def test_directory_annotation_cannot_abort_discovery_or_keep_a_stale_expiry(tmp_path):
    cid = "DIRECTORY"
    reg = registry({cid: good}, [])
    reg.source = DirImportSource(tmp_path)
    path = tmp_path / "cluster.yaml"
    document = """kind: Secret
metadata:
  name: local-import
  labels: {cmapi.net/cluster-id: DIRECTORY}
  annotations: {cmapi.net/token-expires-at: EXPIRY}
stringData: {apiUrl: https://cluster.example, token: fixture-token}
"""
    try:
        path.write_text(document.replace("EXPIRY", "2026-11-19T00:00:00Z"))
        reg.refresh()
        assert reg.get(cid).view()["tokenExpiresAt"] == datetime(2026, 11, 19, tzinfo=timezone.utc)
        assert REGISTRY.get_sample_value(METRIC, {"cluster_id": cid}) is not None
        for malformed in ("2026-02-31T00:00:00Z", "2026-11-19T00:00:00+01:60"):
            prior = reg.get(cid).checked_at
            path.write_text(document.replace("EXPIRY", malformed))
            reg.refresh()
            row = reg.get(cid).view()
            assert row["checkedAt"] > prior
            assert row["status"] == "connected" and row["tokenExpiresAt"] is None
            assert REGISTRY.get_sample_value(METRIC, {"cluster_id": cid}) is None
    finally:
        reg.stop()
