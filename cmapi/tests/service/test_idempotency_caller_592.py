"""#592: an Idempotency-Key belongs to the caller that sent it, not to the person a request is for.

Before the fix the row held the key under `requester_sub` (the person) and `_replay` looked it up under the caller's
subject. So a service's retry sent with `onBehalfOf` got 409 `idempotency-replay`, and the person could replay the
service's request with the service's key (measured: workbench/cmapi/wt-591-evidence/592-probe.txt). Migration 0008 adds
`change_requests.idempotency_sub` and moves the unique index to `(idempotency_sub, idempotency_key)`; the owner's decision
on #592, option A, and draft-ietf-httpapi-idempotency-key-header-09, section 5 ("a unique composite key ... combining the
idempotency key sent by the client with other client specific attributes known only to the resource").
"""
from __future__ import annotations

import json

import psycopg
from sqlalchemy import text

import conftest
from cmapi.core.db.repo import RequestRepo
from cmapi.core.identity.claims import Person
from cmapi.core.identity.directory import CachedDirectory, InMemoryDirectory
from test_flow import NS, OLA, auth
from test_review_h_tools_migrate import empty_schema, migrate  # noqa: F401 - empty_schema is a fixture

URL = "/api/v1/clusters/CRC/namespaces"
SVC_USER, SVC_SUB = "service-account-svc-payments-ci", "sub-service-account-svc-payments-ci"
SVC = dict(roles=["cmapi-requester"], client="svc-payments-ci", employee_id=None)
OTHER = {**NS, "namespace": "ledger-dev"}


def _directory(ctx):
    ctx.pipeline.directory = CachedDirectory(InMemoryDirectory([
        Person(username="ola", email="ola@ephico2real.com", sub="sub-ola")]))


def _service(keys, key):
    return {**auth(keys, SVC_USER, **SVC), "Idempotency-Key": key}


def _ola(keys, key):
    return {**auth(keys, "ola", sub="sub-ola", **OLA), "Idempotency-Key": key}


def _keys_of(db, rid):
    with db.session() as s:
        return tuple(s.execute(text("SELECT requester_sub, idempotency_sub, idempotency_key FROM change_requests "
                                    "WHERE request_id = :r"), {"r": rid}).one())


def test_a_service_retry_on_behalf_of_a_person_replays_its_request(world):
    """Before: 202, then 409 `idempotency-replay` "Idempotency-Key is in use for another request". After: the same request,
    in its current state, before and after a cancel."""
    client, ctx, *_rest, keys = world
    _directory(ctx)
    body = {**NS, "onBehalfOf": "ola"}
    first = client.post(URL, json=body, headers=_service(keys, "svc-key-1"))
    assert first.status_code == 202, first.text
    rid = first.json()["requestId"]

    retry = client.post(URL, json=body, headers=_service(keys, "svc-key-1"))
    assert retry.status_code == 202 and retry.json()["requestId"] == rid, retry.text
    assert _keys_of(ctx.db, rid) == ("sub-ola", SVC_SUB, "svc-key-1")

    cancel = client.post(f"/api/v1/requests/{rid}:cancel", json={}, headers=auth(keys, "ola", sub="sub-ola", **OLA))
    assert cancel.status_code == 200, cancel.text
    after = client.post(URL, json=body, headers=_service(keys, "svc-key-1"))
    assert after.status_code == 202 and after.json()["requestId"] == rid and after.json()["status"] == "cancelled", after.text

    changed = client.post(URL, json={**OTHER, "onBehalfOf": "ola"}, headers=_service(keys, "svc-key-1"))
    assert changed.status_code == 409 and changed.json()["code"] == "idempotency-replay", changed.text
    assert changed.json()["requestId"] == rid, "the same caller's key with another body names its own request"


def test_a_service_retry_that_loses_the_race_gets_the_winner(world, monkeypatch):
    """The retry's lookup misses (the winner's commit not visible yet), its INSERT meets a unique index, and `_submit` looks
    again under the same caller. Before: that second lookup used the caller and the row held the person, so 409."""
    client, ctx, *_rest, keys = world
    _directory(ctx)
    body = {**NS, "onBehalfOf": "ola"}
    rid = client.post(URL, json=body, headers=_service(keys, "svc-race")).json()["requestId"]
    real, calls = RequestRepo.by_idempotency, []

    def first_misses(self, caller_sub, key):
        calls.append(caller_sub)
        return None if len(calls) == 1 else real(self, caller_sub, key)

    monkeypatch.setattr(RequestRepo, "by_idempotency", first_misses)
    retry = client.post(URL, json=body, headers=_service(keys, "svc-race"))
    assert retry.status_code == 202 and retry.json()["requestId"] == rid, retry.text
    assert calls == [SVC_SUB, SVC_SUB]


def test_the_person_cannot_replay_the_service_request_with_its_key(world):
    """To the person the service named, the service's key is a key of her own that she has not used. Before: her body
    with `onBehalfOf` replayed the service's request (202), and another body was 409 `idempotency-replay` naming it.
    After: what any new request of hers gets."""
    client, ctx, *_rest, keys = world
    _directory(ctx)
    rid = client.post(URL, json={**NS, "onBehalfOf": "ola"}, headers=_service(keys, "svc-key-2")).json()["requestId"]

    same = client.post(URL, json={**NS, "onBehalfOf": "ola"}, headers=_ola(keys, "svc-key-2"))
    assert same.status_code == 422 and same.json()["code"] == "on-behalf-of-not-allowed", same.text

    held = client.post(URL, json=NS, headers=_ola(keys, "svc-key-2"))
    assert held.status_code == 409 and held.json()["code"] == "change-pending", held.text   # the service's request holds it

    own = client.post(URL, json=OTHER, headers=_ola(keys, "svc-key-2"))
    assert own.status_code == 202 and own.json()["requestId"] != rid, own.text
    assert _keys_of(ctx.db, own.json()["requestId"]) == ("sub-ola", "sub-ola", "svc-key-2")
    assert _keys_of(ctx.db, rid) == ("sub-ola", SVC_SUB, "svc-key-2"), "both hold the key, each for its own caller"


def test_a_person_own_retry_still_replays(world):
    client, ctx, *_rest, keys = world
    first = client.post(URL, json=NS, headers=_ola(keys, "ola-key"))
    assert first.status_code == 202, first.text
    rid = first.json()["requestId"]
    retry = client.post(URL, json=NS, headers=_ola(keys, "ola-key"))
    assert retry.status_code == 202 and retry.json()["requestId"] == rid, retry.text
    assert _keys_of(ctx.db, rid) == ("sub-ola", "sub-ola", "ola-key")      # the person is the caller


def test_a_service_key_is_free_again_after_24_hours(world):
    """The expiry clears the caller with the key, so the row leaves the unique index and the key can be used again."""
    client, ctx, *_rest, keys = world
    _directory(ctx)
    rid = client.post(URL, json={**NS, "onBehalfOf": "ola"}, headers=_service(keys, "svc-old")).json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("UPDATE change_requests SET created_at = now() - interval '24 hours 1 minute' WHERE request_id = :r"),
                  {"r": rid})
    fresh = client.post(URL, json={**OTHER, "onBehalfOf": "ola"}, headers=_service(keys, "svc-old"))
    assert fresh.status_code == 202 and fresh.json()["requestId"] != rid, fresh.text
    assert _keys_of(ctx.db, rid) == ("sub-ola", None, None)
    assert _keys_of(ctx.db, fresh.json()["requestId"]) == ("sub-ola", SVC_SUB, "svc-old")


# ---- migration 0008 on real PostgreSQL, in the schema `mig`


def _run(url, *args):
    p = migrate(url, *args)
    out = p.communicate()[0]
    assert p.returncode == 0, out[-800:]


def _insert(c, rid, *, requester_sub, key, submitted_by=None, hours_ago=0, sub=None, with_sub=False):
    """A change_requests row as the code of that revision writes it: `requester` with `submittedBySub` when a service sent
    it for a person (core/identity/checks.py, Requester.record)."""
    requester = {"requester": {"sub": requester_sub}, "automated": submitted_by is not None}
    if submitted_by:
        requester["submittedBySub"] = submitted_by
    cols = ("request_id, instance, cluster_id, namespace, env, plugin, action, status, plan, plan_hash, requester, "
            "requester_sub, requester_kind, requester_client, requester_username, idempotency_key, "
            "idempotency_fingerprint, created_at" + (", idempotency_sub" if with_sub else ""))
    values = [rid, "test", "CRC", rid, "dev", "namespaces", "create", "cancelled", "{}", "h", json.dumps(requester),
              requester_sub, "user", "c", requester_sub, key, "fp-" + rid if key else None]
    marks = ", ".join(["%s"] * len(values)) + ", now() - make_interval(hours => %s)" + (", %s" if with_sub else "")
    c.execute(f"INSERT INTO change_requests ({cols}) VALUES ({marks})", [*values, hours_ago, *([sub] if with_sub else [])])


def _state(c):
    has_sub = c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'mig' AND "
                        "table_name = 'change_requests' AND column_name = 'idempotency_sub'").fetchone()[0]
    sub = "idempotency_sub" if has_sub else "NULL"
    rows = c.execute(f"SELECT request_id, idempotency_key, idempotency_fingerprint, {sub} FROM change_requests "
                     "ORDER BY request_id").fetchall()
    index = c.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = 'mig' AND indexname = 'uq_cr_idempotency'"
                      ).fetchone()[0]
    return {r[0]: r[1:] for r in rows}, index


def test_the_upgrade_keys_each_stored_key_on_its_caller(empty_schema):
    """Rows written at 0007, the old way: each key that is still held moves to its caller. An expired key is cleared, as
    the lookup would clear it. Where the old index allowed one caller the same key twice, the row the caller could
    already replay keeps it, else the newest."""
    _run(empty_schema, "0007")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "a-person-own", requester_sub="sub-ola", key="k1")
        _insert(c, "b-service-for-ola", requester_sub="sub-ola", key="k2", submitted_by="sub-svc")
        _insert(c, "c-expired", requester_sub="sub-ola", key="k3", hours_ago=25)
        _insert(c, "d-service-own", requester_sub="sub-svc", key="k4", hours_ago=2)
        _insert(c, "e-service-for-ola", requester_sub="sub-ola", key="k4", submitted_by="sub-svc", hours_ago=1)
        _insert(c, "f-service-for-ola", requester_sub="sub-ola", key="k5", submitted_by="sub-svc", hours_ago=2)
        _insert(c, "g-service-for-amy", requester_sub="sub-amy", key="k5", submitted_by="sub-svc", hours_ago=1)
        _insert(c, "h-no-key", requester_sub="sub-ola", key=None)
        rows, index = _state(c)
        assert "(requester_sub, idempotency_key)" in index, index

        _run(empty_schema, "head")
        rows, index = _state(c)
        assert "(idempotency_sub, idempotency_key) WHERE (idempotency_key IS NOT NULL)" in index, index
        assert rows == {
            "a-person-own": ("k1", "fp-a-person-own", "sub-ola"),
            "b-service-for-ola": ("k2", "fp-b-service-for-ola", "sub-svc"),
            "c-expired": (None, None, None),
            "d-service-own": ("k4", "fp-d-service-own", "sub-svc"),     # its own: the service could replay it before
            "e-service-for-ola": (None, None, None),
            "f-service-for-ola": (None, None, None),
            "g-service-for-amy": ("k5", "fp-g-service-for-amy", "sub-svc"),   # the newer one
            "h-no-key": (None, None, None),
        }, rows


def test_the_downgrade_keys_each_stored_key_on_its_requester_again(empty_schema):
    """At 0008 a person's own key and a service's same key for that person can both be held. The downgrade keeps the
    person's own, which 0007 could replay, then puts the old index back and drops the column."""
    _run(empty_schema, "head")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "a-person-own", requester_sub="sub-ola", key="k1", hours_ago=2, sub="sub-ola", with_sub=True)
        _insert(c, "b-service-for-ola", requester_sub="sub-ola", key="k1", hours_ago=1, sub="sub-svc", with_sub=True)
        _insert(c, "c-older-image", requester_sub="sub-amy", key="k2", hours_ago=2, sub=None, with_sub=True)
        _insert(c, "d-service-for-amy", requester_sub="sub-amy", key="k2", hours_ago=1, sub="sub-svc", with_sub=True)
        _insert(c, "e-expired", requester_sub="sub-ola", key="k3", hours_ago=25, sub="sub-ola", with_sub=True)

        _run(empty_schema, "0007", "--downgrade")
        rows, index = _state(c)
        assert "(requester_sub, idempotency_key) WHERE (idempotency_key IS NOT NULL)" in index, index
        assert rows == {
            "a-person-own": ("k1", "fp-a-person-own", None),
            "b-service-for-ola": (None, None, None),
            "c-older-image": ("k2", "fp-c-older-image", None),     # written by 0007's code after a rollback: its own
            "d-service-for-amy": (None, None, None),
            "e-expired": (None, None, None),
        }, rows


def test_a_key_stored_before_the_upgrade_replays_after_it(empty_schema, test_config, keys, monkeypatch):
    """The real app, on the schema `mig`: a service's request for a person and a person's own, then down to 0007, which
    leaves each row as 0007's code wrote it (that code wrote every column but idempotency_sub), then up to 0008. The same
    retries replay, through HTTP."""
    _run(empty_schema, "head")
    monkeypatch.setattr(conftest, "DB_URL", empty_schema)
    body = {**NS, "onBehalfOf": "ola"}
    with conftest.build_world(test_config, keys, monkeypatch) as (client, ctx, *_rest):
        _directory(ctx)
        by_service = client.post(URL, json=body, headers=_service(keys, "svc-before"))
        own = client.post(URL, json=OTHER, headers=_ola(keys, "ola-before"))
        assert by_service.status_code == 202 and own.status_code == 202, (by_service.text, own.text)
        ctx.db.engine.dispose()

    _run(empty_schema, "0007", "--downgrade")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        rows, _index = _state(c)
    assert rows[by_service.json()["requestId"]][0] == "svc-before" and rows[own.json()["requestId"]][0] == "ola-before"

    _run(empty_schema, "head")
    with conftest.build_world(test_config, keys, monkeypatch) as (client, ctx, *_rest):
        _directory(ctx)
        assert _keys_of(ctx.db, by_service.json()["requestId"]) == ("sub-ola", SVC_SUB, "svc-before")
        retry = client.post(URL, json=body, headers=_service(keys, "svc-before"))
        assert retry.status_code == 202 and retry.json()["requestId"] == by_service.json()["requestId"], retry.text
        again = client.post(URL, json=OTHER, headers=_ola(keys, "ola-before"))
        assert again.status_code == 202 and again.json()["requestId"] == own.json()["requestId"], again.text
        ctx.db.engine.dispose()
