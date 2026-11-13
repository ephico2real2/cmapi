"""The list filters that the portal's tabs need and docs/02 specifies: #145 (BUG-32) on GET /quotas, #146 (BUG-33) on GET /requests."""
from __future__ import annotations

import uuid

import cmapi.plugins.quotas as quotas_mod

from test_flow import AMY, NS, OLA, auth


def row(name: str, used: float, **kw) -> dict:
    return {"name": name, "clusterId": "CRC", "env": "dev", "team": "payments", "app": None, "tier": "small",
            "cpu": ["0", "8"], "memory": ["0", "16Gi"], "pods": ["0", "50"], "used": used, "expiresAt": None, "tierHash": None,
            "tierOutdated": kw.get("outdated", False), "openRequest": kw.get("open")}


ROWS = [row("alpha-dev", 0.10), row("bravo-dev", 0.97), row("charlie-dev", 0.85, outdated=True), row("delta-dev", 0.50, open="req-1"),
        row("echo-dev", 0.99)]


def test_severity_has_the_two_levels_that_use_alone_gives():
    from cmapi.core.listquery import severity
    assert [severity(u) for u in (0.0, 0.79, 0.8, 0.949, 0.95, 1.2)] == [0, 0, 2, 2, 3, 3]


def test_quotas_filter_on_one_attention_state_and_keep_each_count(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    monkeypatch.setattr(quotas_mod, "quota_rows", lambda c, who: [dict(r) for r in ROWS])
    h = auth(keys, "ola", **OLA)
    everything = client.get("/api/v1/quotas", headers=h).json()
    assert everything["facets"] == {"near-limit": 3, "tier-outdated": 1, "open-request": 1} and everything["page"]["total"] == 5
    near = client.get("/api/v1/quotas?state=near-limit", headers=h).json()
    assert [i["name"] for i in near["items"]] == ["bravo-dev", "charlie-dev", "echo-dev"] and near["page"]["total"] == 3
    assert near["facets"] == everything["facets"], "a chosen state changed the other chips' counts"
    assert [i["name"] for i in client.get("/api/v1/quotas?state=open-request", headers=h).json()["items"]] == ["delta-dev"]
    assert [i["name"] for i in client.get("/api/v1/quotas?state=tier-outdated", headers=h).json()["items"]] == ["charlie-dev"]
    bad = client.get("/api/v1/quotas?state=idle", headers=h)
    assert bad.status_code == 422 and bad.json()["code"] == "validation-failed" and "near-limit" in bad.json()["detail"]


def test_quotas_sort_by_severity_then_name_and_the_cursor_is_bound_to_the_state(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    monkeypatch.setattr(quotas_mod, "quota_rows", lambda c, who: [dict(r) for r in ROWS])
    h = auth(keys, "ola", **OLA)
    by_severity = client.get("/api/v1/quotas?sort=severity", headers=h)
    assert by_severity.status_code == 200, by_severity.text
    assert [i["name"] for i in by_severity.json()["items"]] == ["bravo-dev", "echo-dev", "charlie-dev", "alpha-dev", "delta-dev"]
    first = client.get("/api/v1/quotas?state=near-limit&sort=severity&limit=2", headers=h).json()
    assert [i["name"] for i in first["items"]] == ["bravo-dev", "echo-dev"] and first["page"]["nextCursor"]
    cursor = first["page"]["nextCursor"]
    second = client.get(f"/api/v1/quotas?state=near-limit&sort=severity&limit=2&cursor={cursor}", headers=h).json()
    assert [i["name"] for i in second["items"]] == ["charlie-dev"]
    other = client.get(f"/api/v1/quotas?state=open-request&sort=severity&limit=2&cursor={cursor}", headers=h)
    assert other.status_code == 400 and other.json()["code"] == "invalid-cursor"
    csv = client.get("/api/v1/quotas:export?state=near-limit&sort=severity", headers=h).text.splitlines()
    assert [line.split(",")[0] for line in csv[1:]] == ["bravo-dev", "echo-dev", "charlie-dev"]


def test_requests_filter_on_open_and_closed(world):
    client, ctx, git, kube, validator, keys = world

    def create(name: str) -> str:
        r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": name, "tier": "large"},
                        headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())})
        assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
        return r.json()["requestId"]

    pending, cancelled, rejected = create("one-dev"), create("two-dev"), create("three-dev")
    assert client.post(f"/api/v1/requests/{cancelled}:cancel", headers=auth(keys, "ola", **OLA)).status_code == 200
    assert client.post(f"/api/v1/requests/{rejected}:reject", json={"comment": "no"}, headers=auth(keys, "amy", **AMY)).status_code == 200
    h = auth(keys, "ola", **OLA)

    def ids(query: str) -> set[str]:
        r = client.get(f"/api/v1/requests{query}", headers=h)
        assert r.status_code == 200, r.text
        return {i["requestId"] for i in r.json()["items"]}

    assert ids("") == {pending, cancelled, rejected}
    assert ids("?state=open") == {pending}
    assert ids("?state=closed") == {cancelled, rejected}
    assert ids("?state=closed&status=cancelled") == {cancelled}
    assert ids("?state=open&status=cancelled") == set()
    bad = client.get("/api/v1/requests?state=done", headers=h)
    assert bad.status_code == 422 and bad.json()["code"] == "validation-failed"
