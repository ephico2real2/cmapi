"""#496: when the request that held a namespace closes between the failed INSERT and the lookup of its holder, the 409
says so and sends no requestId, instead of "another request holds" with requestId null.

RFC 9110 section 15.5.10: a 409 carries enough to recognise the source of the conflict. Here the conflict has just
cleared, so the answer says the holder finished and the caller should read the namespace again and resend (then 412 if
Git moved, a named 409 if another request took it, or 202)."""
from __future__ import annotations

from cmapi.core.db.repo import RequestRepo
from test_flow import NS, OLA, auth


def test_a_holder_that_closes_before_it_is_named_gives_a_409_without_a_dead_request_id(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    first = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert first.status_code == 202, first.text                 # it holds payments-dev until it is synced
    # The holder closes in the gap: the INSERT already failed on the lock, and the lookup of the holder finds nothing.
    monkeypatch.setattr(RequestRepo, "open_for", lambda self, cluster_id, namespace: None)
    second = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert second.status_code == 409 and second.json()["code"] == "change-pending", second.text
    assert "requestId" not in second.json(), "no request holds the namespace now: a null requestId names nothing"
    assert "has just finished" in second.json()["detail"], second.json()["detail"]


def test_a_holder_that_is_still_open_is_named(world):
    client, ctx, git, kube, validator, keys = world
    first = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    second = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert second.status_code == 409 and second.json()["requestId"] == first.json()["requestId"], second.text
