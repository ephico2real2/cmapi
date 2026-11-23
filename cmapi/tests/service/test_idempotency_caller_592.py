"""#592: an Idempotency-Key belongs to the caller that sent it, not to the person a request is for. Release 1 of 2.

Before the fix the row held the key under `requester_sub` (the person) and `_replay` looked it up under the caller's
subject. So a service's retry sent with `onBehalfOf` got 409 `idempotency-replay`, and the person could replay the
service's request with the service's key (measured: workbench/cmapi/wt-591-evidence/592-probe.txt). The owner's decisions:
option A on #592, and expand then contract on PR #601. Migration 0008 adds `change_requests.idempotency_sub` and the
caller's unique index `uq_cr_idempotency_caller`, and keeps the requester's `uq_cr_idempotency` for 0007 pods. Release 2
(0009) keeps only the caller's. draft-ietf-httpapi-idempotency-key-header-09, section 5: "a unique composite key ...
combining the idempotency key sent by the client with other client specific attributes known only to the resource".
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
IN_USE = "Idempotency-Key is in use for another request"


def _directory(ctx):
    ctx.pipeline.directory = CachedDirectory(InMemoryDirectory([
        Person(username="ola", email="ola@ephico2real.com", sub="sub-ola"),
        Person(username="amy", email="amy@ephico2real.com", sub="sub-amy")]))


def _service(keys, key):
    return {**auth(keys, SVC_USER, **SVC), "Idempotency-Key": key}


def _ola(keys, key):
    return {**auth(keys, "ola", sub="sub-ola", **OLA), "Idempotency-Key": key}


def _keys_of(db, rid):
    with db.session() as s:
        return tuple(s.execute(text("SELECT requester_sub, idempotency_sub, idempotency_key FROM change_requests "
                                    "WHERE request_id = :r"), {"r": rid}).one())


def _first_lookup_misses(monkeypatch):
    """The retry's first lookup misses, as when the winner's commit is not visible yet, so its INSERT meets an index and
    `_submit` looks again. Returns the callers that each lookup used."""
    real, calls = RequestRepo.by_idempotency, []

    def first_misses(self, caller_sub, key):
        calls.append(caller_sub)
        return None if len(calls) == 1 else real(self, caller_sub, key)

    monkeypatch.setattr(RequestRepo, "by_idempotency", first_misses)
    return calls


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


def test_a_service_retry_that_loses_the_race_gets_the_closed_winner(world, monkeypatch):
    """The winner is cancelled first, so the namespace lock cannot answer for the key: only an Idempotency-Key index can
    stop the retry's INSERT. Before: the second lookup used the caller and the row held the person, so 409."""
    client, ctx, *_rest, keys = world
    _directory(ctx)
    body = {**NS, "onBehalfOf": "ola"}
    rid = client.post(URL, json=body, headers=_service(keys, "svc-race")).json()["requestId"]
    cancel = client.post(f"/api/v1/requests/{rid}:cancel", json={}, headers=auth(keys, "ola", sub="sub-ola", **OLA))
    assert cancel.status_code == 200, cancel.text

    calls = _first_lookup_misses(monkeypatch)
    retry = client.post(URL, json=body, headers=_service(keys, "svc-race"))
    assert retry.status_code == 202 and retry.json()["requestId"] == rid, retry.text
    assert retry.json()["status"] == "cancelled"
    assert calls == [SVC_SUB, SVC_SUB]


def test_one_service_key_for_a_second_person_is_refused_by_the_caller_index(world, monkeypatch):
    """The requester's index lets one service hold a key for two persons. The caller's index (0008) does not: the second
    INSERT conflicts, and the second lookup finds the first request, whose fingerprint differs. Before (8a5b41c): 202, a
    second request under the same caller and key."""
    client, ctx, *_rest, keys = world
    _directory(ctx)
    rid = client.post(URL, json={**NS, "onBehalfOf": "ola"}, headers=_service(keys, "svc-two")).json()["requestId"]

    _first_lookup_misses(monkeypatch)
    second = client.post(URL, json={**OTHER, "onBehalfOf": "amy"}, headers=_service(keys, "svc-two"))
    assert second.status_code == 409 and second.json()["code"] == "idempotency-replay", second.text
    assert second.json()["requestId"] == rid, second.text


def test_the_person_cannot_replay_the_service_request_with_its_key(world):
    """The person the service named cannot replay its request with its key. Before (8a5b41c): her body with `onBehalfOf`
    replayed it (202), and another body was 409 naming it. After, in release 1: 422 for `onBehalfOf`, the lock, and for
    another namespace 409 from the requester's index, which still holds the pair (person, key) and names no request.
    Release 2 (0009) drops that index, and the last answer becomes 202."""
    client, ctx, *_rest, keys = world
    _directory(ctx)
    rid = client.post(URL, json={**NS, "onBehalfOf": "ola"}, headers=_service(keys, "svc-key-2")).json()["requestId"]

    same = client.post(URL, json={**NS, "onBehalfOf": "ola"}, headers=_ola(keys, "svc-key-2"))
    assert same.status_code == 422 and same.json()["code"] == "on-behalf-of-not-allowed", same.text

    # The service's request holds the namespace, and the requester's index holds (person, key): the INSERT breaks both,
    # and the answer is the conflict that PostgreSQL reports first. Neither replays the service's request.
    held = client.post(URL, json=NS, headers=_ola(keys, "svc-key-2"))
    assert held.status_code == 409 and held.json()["code"] in ("change-pending", "idempotency-replay"), held.text
    assert held.json()["code"] == "change-pending" or "requestId" not in held.json(), held.text

    other = client.post(URL, json=OTHER, headers=_ola(keys, "svc-key-2"))
    assert other.status_code == 409 and other.json()["code"] == "idempotency-replay", other.text
    assert other.json()["detail"] == IN_USE and "requestId" not in other.json(), other.text
    assert _keys_of(ctx.db, rid) == ("sub-ola", SVC_SUB, "svc-key-2")


def test_a_person_own_retry_still_replays(world):
    client, ctx, *_rest, keys = world
    first = client.post(URL, json=NS, headers=_ola(keys, "ola-key"))
    assert first.status_code == 202, first.text
    rid = first.json()["requestId"]
    retry = client.post(URL, json=NS, headers=_ola(keys, "ola-key"))
    assert retry.status_code == 202 and retry.json()["requestId"] == rid, retry.text
    assert _keys_of(ctx.db, rid) == ("sub-ola", "sub-ola", "ola-key")      # the person is the caller


def test_a_service_key_is_free_again_after_24_hours(world):
    """The expiry clears the caller with the key, so the row leaves both unique indexes and the key can be used again."""
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


def test_a_row_that_a_0007_pod_wrote_after_0008_belongs_to_its_caller(world):
    """In release 1's window a 0007 pod inserts on the 0008 schema without `idempotency_sub` (its model has no such column).
    Here such rows are made with this code, then the column is set to NULL, which is what that pod leaves. This code takes
    their caller from `requester`, as 0008's backfill does (`key_owner`). Before (628a6c5, which looked up by
    `idempotency_sub` only): the service's retry missed its request."""
    client, ctx, *_rest, keys = world
    _directory(ctx)
    by_service = client.post(URL, json={**NS, "onBehalfOf": "ola"}, headers=_service(keys, "old-pod-svc")).json()["requestId"]
    own = client.post(URL, json=OTHER, headers=_ola(keys, "old-pod-ola")).json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("UPDATE change_requests SET idempotency_sub = NULL"))

    retry = client.post(URL, json={**NS, "onBehalfOf": "ola"}, headers=_service(keys, "old-pod-svc"))
    assert retry.status_code == 202 and retry.json()["requestId"] == by_service, retry.text
    again = client.post(URL, json=OTHER, headers=_ola(keys, "old-pod-ola"))
    assert again.status_code == 202 and again.json()["requestId"] == own, again.text

    person = client.post(URL, json={**OTHER, "namespace": "audit-dev"}, headers=_ola(keys, "old-pod-svc"))
    assert person.status_code == 409 and person.json()["detail"] == IN_USE and "requestId" not in person.json(), person.text

    with ctx.db.session() as s:
        s.execute(text("UPDATE change_requests SET created_at = now() - interval '24 hours 1 minute' WHERE request_id = :r"),
                  {"r": by_service})
    reused = client.post(URL, json={**OTHER, "namespace": "audit-dev", "onBehalfOf": "ola"},
                         headers=_service(keys, "old-pod-svc"))
    assert reused.status_code == 202 and reused.json()["requestId"] not in (by_service, own), reused.text
    assert _keys_of(ctx.db, by_service) == ("sub-ola", None, None), "the expiry found the row by its owner and cleared it"


# ---- migration 0008 on real PostgreSQL, in the schema `mig`


def _run(url, *args):
    p = migrate(url, *args)
    out = p.communicate()[0]
    assert p.returncode == 0, out[-800:]


def _refused(url, *args):
    p = migrate(url, *args)
    out = p.communicate()[0]
    assert p.returncode != 0, out[-800:]
    return out


def _insert(c, rid, *, requester_sub, key, submitted_by=None, hours_ago=0, sub=None, with_sub=False, requester=None):
    """A change_requests row as the code of that revision writes it: `requester` with `submittedBySub` when a service sent
    it for a person (core/identity/checks.py, Requester.record)."""
    if requester is None:
        requester = {"requester": {"sub": requester_sub}, "automated": submitted_by is not None}
        if submitted_by:
            requester.update(submittedBy="svc", submittedBySub=submitted_by, submittedByClient="svc")
    cols = ("request_id, instance, cluster_id, namespace, env, plugin, action, status, plan, plan_hash, requester, "
            "requester_sub, requester_kind, requester_client, requester_username, idempotency_key, "
            "idempotency_fingerprint, created_at" + (", idempotency_sub" if with_sub else ""))
    values = [rid, "test", "CRC", rid, "dev", "namespaces", "create", "cancelled", "{}", "h", json.dumps(requester),
              requester_sub, "user", "c", requester_sub, key, "fp-" + rid if key else None]
    marks = ", ".join(["%s"] * len(values)) + ", now() - make_interval(hours => %s)" + (", %s" if with_sub else "")
    c.execute(f"INSERT INTO change_requests ({cols}) VALUES ({marks})", [*values, hours_ago, *([sub] if with_sub else [])])


def _state(c):
    """Each row's key, fingerprint and caller (None when there is no column), the idempotency indexes, and the revision."""
    has_sub = c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'mig' AND "
                        "table_name = 'change_requests' AND column_name = 'idempotency_sub'").fetchone()[0]
    sub = "idempotency_sub" if has_sub else "NULL"
    rows = c.execute(f"SELECT request_id, idempotency_key, idempotency_fingerprint, {sub} FROM change_requests "
                     "ORDER BY request_id").fetchall()
    indexes = dict(c.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'mig' AND "
                             "indexname LIKE 'uq_cr_idempotency%' ORDER BY indexname").fetchall())
    version = c.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    return {r[0]: r[1:] for r in rows}, indexes, version


REQUESTER_INDEX = ("CREATE UNIQUE INDEX uq_cr_idempotency ON mig.change_requests USING btree (requester_sub, idempotency_key) "
                   "WHERE (idempotency_key IS NOT NULL)")
CALLER_INDEX = ("CREATE UNIQUE INDEX uq_cr_idempotency_caller ON mig.change_requests USING btree (idempotency_sub, "
                "idempotency_key) WHERE (idempotency_key IS NOT NULL)")


def test_the_upgrade_keys_each_stored_key_on_its_caller_and_keeps_the_old_index(empty_schema):
    """Rows written at 0007: each live key gets its caller, an expired key is cleared as the lookup would clear it, and the
    requester's index stays beside the caller's. Before (628a6c5): the requester's index was replaced."""
    _run(empty_schema, "0007")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "a-person-own", requester_sub="sub-ola", key="k1")
        _insert(c, "b-service-for-ola", requester_sub="sub-ola", key="k2", submitted_by="sub-svc", hours_ago=23)
        _insert(c, "c-expired", requester_sub="sub-ola", key="k3", hours_ago=25)
        _insert(c, "d-service-own", requester_sub="sub-svc", key="k4")
        _insert(c, "h-no-key", requester_sub="sub-ola", key=None)
        _rows, indexes, _version = _state(c)
        assert indexes == {"uq_cr_idempotency": REQUESTER_INDEX}

        _run(empty_schema, "head")
        rows, indexes, version = _state(c)
        assert version == "0008" and indexes == {"uq_cr_idempotency": REQUESTER_INDEX,
                                                 "uq_cr_idempotency_caller": CALLER_INDEX}, indexes
        assert rows == {
            "a-person-own": ("k1", "fp-a-person-own", "sub-ola"),
            "b-service-for-ola": ("k2", "fp-b-service-for-ola", "sub-svc"),
            "c-expired": (None, None, None),
            "d-service-own": ("k4", "fp-d-service-own", "sub-svc"),
            "h-no-key": (None, None, None),
        }, rows


def test_the_upgrade_refuses_a_live_collision_and_succeeds_once_it_expires(empty_schema):
    """One service's key, for itself and for a person, and for two persons: the requester's index allowed both pairs, the
    caller's cannot. The upgrade refuses, names them and changes nothing, and succeeds when all but one of each pair are
    over 24 hours old. Before (628a6c5): the losers' live keys were cleared."""
    _run(empty_schema, "0007")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "d-service-own", requester_sub="sub-svc", key="k4", hours_ago=23)
        _insert(c, "e-service-for-ola", requester_sub="sub-ola", key="k4", submitted_by="sub-svc", hours_ago=2)
        _insert(c, "f-service-for-ola", requester_sub="sub-ola", key="k5", submitted_by="sub-svc", hours_ago=3)
        _insert(c, "g-service-for-amy", requester_sub="sub-amy", key="k5", submitted_by="sub-svc", hours_ago=1)
        before = _state(c)

        out = _refused(empty_schema, "head")
        assert ("live requests share one caller's Idempotency-Key (d-service-own, e-service-for-ola; f-service-for-ola, "
                "g-service-for-amy)") in out, out[-800:]
        assert _state(c) == before and before[2] == "0007"

        c.execute("UPDATE change_requests SET created_at = now() - interval '25 hours' "
                  "WHERE request_id IN ('d-service-own', 'f-service-for-ola')")
        _run(empty_schema, "head")
        rows, _indexes, version = _state(c)
        assert version == "0008" and rows == {
            "d-service-own": (None, None, None),
            "e-service-for-ola": ("k4", "fp-e-service-for-ola", "sub-svc"),
            "f-service-for-ola": (None, None, None),
            "g-service-for-amy": ("k5", "fp-g-service-for-amy", "sub-svc"),
        }, rows


def test_the_upgrade_refuses_a_live_delegated_row_without_its_caller(empty_schema):
    """A delegated row that does not name its caller: the upgrade will not guess the person. Before (628a6c5): its key was
    given to the person."""
    _run(empty_schema, "0007")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "x-delegated", requester_sub="sub-ola", key="k6", hours_ago=1,
                requester={"requester": {"sub": "sub-ola"}, "automated": True, "submittedBy": "svc"})
        _insert(c, "y-null-caller", requester_sub="sub-ola", key="k7", hours_ago=1,
                requester={"requester": {"sub": "sub-ola"}, "submittedByClient": "svc", "submittedBySub": None})
        before = _state(c)

        out = _refused(empty_schema, "head")
        assert "the live delegated requests x-delegated, y-null-caller hold an Idempotency-Key" in out, out[-800:]
        assert _state(c) == before

        c.execute("UPDATE change_requests SET created_at = now() - interval '25 hours'")
        _run(empty_schema, "head")
        rows, _indexes, _version = _state(c)
        assert rows == {"x-delegated": (None, None, None), "y-null-caller": (None, None, None)}, rows


def test_the_downgrade_keeps_every_key_and_the_old_index(empty_schema):
    """At 0008 the requester's index was in force, so no two rows share a person and a key: the downgrade only drops the
    caller's index and the column. Rows from this code and from a 0007 pod in the window (no caller) keep their keys.
    Before (628a6c5): the downgrade cleared keys and rebuilt the requester's index."""
    _run(empty_schema, "head")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "a-person-own", requester_sub="sub-ola", key="k1", hours_ago=2, sub="sub-ola", with_sub=True)
        _insert(c, "b-service-for-ola", requester_sub="sub-ola", key="k2", submitted_by="sub-svc", hours_ago=1,
                sub="sub-svc", with_sub=True)
        _insert(c, "c-0007-pod", requester_sub="sub-amy", key="k1", hours_ago=1, sub=None, with_sub=True)
        _insert(c, "d-expired", requester_sub="sub-ola", key="k3", hours_ago=25, sub="sub-ola", with_sub=True)

        _run(empty_schema, "0007", "--downgrade")
        rows, indexes, version = _state(c)
        assert version == "0007" and indexes == {"uq_cr_idempotency": REQUESTER_INDEX}, indexes
        assert rows == {
            "a-person-own": ("k1", "fp-a-person-own", None),
            "b-service-for-ola": ("k2", "fp-b-service-for-ola", None),
            "c-0007-pod": ("k1", "fp-c-0007-pod", None),
            "d-expired": ("k3", "fp-d-expired", None),
        }, rows


def test_keys_written_by_this_code_replay_after_a_schema_round_trip(empty_schema, test_config, keys, monkeypatch):
    """A data round trip with this code at both ends: the app writes a service's request for a person and a person's own,
    the schema goes down to 0007 (the rows then hold what 0007's code writes: every column but idempotency_sub) and up to
    0008, and the same retries replay through HTTP. It does not run 0007's code; the mixed-version window is measured by a
    separate probe (docs/reviews/2026-11-23-issue-592)."""
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
        rows, _indexes, _version = _state(c)
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
