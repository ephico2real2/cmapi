"""#420: GET /api/v1/clusters serves each cluster's findings to every clusters:read caller, so no finding may hold the token.

The cluster here echoes the Authorization header in its 401 and 500 bodies, raw and JSON-escaped, the way some proxies do; the
client is the real KubeClient over an httpx MockTransport. tests/service/test_cluster_token_client_420.py proves the client
and the registry over a real socket; this proves the answer of the API.

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_cluster_token_redaction_420.py -q -W ignore
"""
from __future__ import annotations

import json

import httpx
import pytest

from cmapi.core.clients.kube import KubeClient
from conftest import OneSecret
from test_flow import OLA, auth

TOKEN = OneSecret().list()[0]["data"]["token"]


@pytest.mark.parametrize("status, body", [
    (401, lambda header: f"rejected credential {header}"),
    (500, lambda header: json.dumps({"kind": "Status", "message": f"upstream refused {header}"})),
    (500, lambda header: "x" * 280 + header),                   # the 300-character cut falls inside the token
], ids=["401-raw", "500-json", "500-split"])
def test_get_clusters_never_shows_the_token(world, status, body):
    client, ctx, git, kube, validator, keys = world

    def echo(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body(request.headers["authorization"]))

    def factory(cluster_id, api_url, token, ca_file, *, insecure=False):
        c = KubeClient(cluster_id, api_url, token, ca_file, insecure=insecure)
        c._client = httpx.Client(base_url=c.api_url, headers=c._client.headers, transport=httpx.MockTransport(echo))
        return c
    ctx.registry.client_factory = factory
    ctx.registry.refresh()
    r = client.get("/api/v1/clusters", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    crc = next(c for c in r.json()["items"] if c["clusterId"] == "CRC")
    assert crc["status"] == ("auth_failed" if status == 401 else "unreachable") and crc["findings"], crc
    assert "***" in crc["findings"][0], crc["findings"]
    assert not [TOKEN[i:i + 8] for i in range(len(TOKEN) - 7) if TOKEN[i:i + 8] in r.text], r.text
