"""#495: a write that needs If-Match answers 428 without it, even when its Idempotency-Key was used before.

RFC 6585 section 3: 428 means the server requires the request to be conditional, a property of the request itself, so
a replay without If-Match is refused as the first request would be. The ETag *comparison* is not repeated on a replay,
so a retry that carries the ETag it was first sent with still gets the original request after Git moved (a lost response,
retried). Other paths keep their order: 404 for an unknown namespace comes before 428 (RFC 9110 section 13.2.1)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from cmapi.core.errors import Problem
from cmapi.core.pipeline import Pipeline
from cmapi.plugins.expiration.rules import utc_today

from test_expirations import created_namespace, write
from test_flow import NS, OLA, auth, run_jobs

URL = "/api/v1/clusters/CRC/namespaces/payments-dev"


def _with(keys, key: str, etag: str | None) -> dict:
    headers = {**auth(keys, "ola", **OLA), "Idempotency-Key": key}
    if etag is not None:
        headers["If-Match"] = f'"{etag}"'
    return headers


def _etag(client, keys) -> str:
    return client.get(URL, headers=auth(keys, "ola", **OLA)).json()["etag"]


def test_a_patch_replay_without_if_match_is_428(world):
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    run_jobs(ctx)
    etag, key = _etag(client, keys), str(uuid.uuid4())
    first = client.patch(URL, json={"tier": "medium"}, headers=_with(keys, key, etag))
    assert first.status_code == 202, first.text
    replay = client.patch(URL, json={"tier": "medium"}, headers=_with(keys, key, None))
    assert replay.status_code == 428 and replay.json()["code"] == "precondition-required", replay.text


def test_a_patch_retry_with_its_first_etag_is_still_replayed_after_git_moved(world):
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    run_jobs(ctx)
    etag, key = _etag(client, keys), str(uuid.uuid4())
    first = client.patch(URL, json={"tier": "medium"}, headers=_with(keys, key, etag))
    assert first.status_code == 202, first.text
    run_jobs(ctx)                                   # the change merges: the folder's etag moves
    assert _etag(client, keys) != etag
    retry = client.patch(URL, json={"tier": "medium"}, headers=_with(keys, key, etag))
    assert retry.status_code == 202 and retry.json()["requestId"] == first.json()["requestId"], retry.text


def test_a_delete_replay_without_if_match_is_428(world):
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    run_jobs(ctx)
    etag, key = _etag(client, keys), str(uuid.uuid4())
    first = client.delete(URL, headers=_with(keys, key, etag))
    assert first.status_code == 202, first.text
    replay = client.delete(URL, headers=_with(keys, key, None))
    assert replay.status_code == 428 and replay.json()["code"] == "precondition-required", replay.text


def test_an_expiry_replay_without_if_match_is_428(world):
    client, ctx, git, kube, validator, keys = world
    etag = created_namespace(client, ctx, keys, expiresAt=(utc_today() + timedelta(days=10)).isoformat())
    key = str(uuid.uuid4())
    first = write(client, keys, "extend", {"days": 7}, etag, key=key)
    assert first.status_code == 202, first.text
    replay = write(client, keys, "extend", {"days": 7}, None, key=key)
    assert replay.status_code == 428 and replay.json()["code"] == "precondition-required", replay.text


def test_an_unknown_namespace_without_if_match_is_still_404(world):
    client, ctx, git, kube, validator, keys = world
    r = client.patch("/api/v1/clusters/CRC/namespaces/nope-dev", json={"tier": "medium"}, headers=_with(keys, str(uuid.uuid4()), None))
    assert r.status_code == 404 and r.json()["code"] == "object-not-found", r.text


@pytest.mark.parametrize("etag", [None, '"stale"'])
def test_delete_with_only_a_quota_left_in_git_finds_no_namespace(etag):
    pipeline = Mock(spec=Pipeline)
    pipeline.registry, pipeline.cfg = Mock(), Mock()
    pipeline._read_folder.return_value = ({"folder/quota.yaml": "kind: ResourceQuota\n"}, "a" * 40)
    # plan_delete authorizes, then plans in _plan_delete, which expire_check's delete shares (#263): both run for real here.
    pipeline._plan_delete = lambda *a, **kw: Pipeline._plan_delete(pipeline, *a, **kw)
    with pytest.raises(Problem) as problem:
        Pipeline.plan_delete(pipeline, Mock(), "CRC", "payments-dev", if_match=etag)
    assert (problem.value.status, problem.value.code) == (404, "object-not-found")
