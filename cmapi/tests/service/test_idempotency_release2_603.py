"""#603: release 2 of #592. Migration 0009 makes `uq_cr_idempotency_caller (idempotency_sub, idempotency_key)` the only
unique index of an Idempotency-Key, fills the keyed rows that 0007 pods wrote without a caller, and the lookup reads
`idempotency_sub` only.

The owner's decisions on PR #601: expand, then contract (Fowler, ParallelChange: the contract phase "remove[s] the old
version and change[s] the interface so that it only supports the new version"), and refuse, never drop. Each refusal test
compares every row, every index and constraint of the schema and the revision before and after: nothing may change.
"""
from __future__ import annotations

import psycopg
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

import conftest
from cmapi.core.db import Database, REQUIRED_REVISION, older_than_required
from cmapi.core.db.repo import RequestRepo
from test_flow import NS
from test_idempotency_caller_592 import (CALLER_INDEX, OTHER, REQUESTER_INDEX, SVC_SUB, URL, _directory, _insert, _keys_of,
                                         _ola, _refused, _run, _service, _state)
from test_review_h_tools_migrate import empty_schema  # noqa: F401 - a fixture

CHECK = "CHECK (((idempotency_key IS NULL) OR (idempotency_sub IS NOT NULL)))"


def _everything(c):
    """Every row of change_requests with every column, the schema's indexes, the table's constraints and the revision."""
    return {
        "rows": c.execute("SELECT * FROM change_requests ORDER BY request_id").fetchall(),
        "count": c.execute("SELECT count(*) FROM change_requests").fetchone()[0],
        "indexes": c.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'mig' ORDER BY indexname").fetchall(),
        "constraints": c.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                                 "WHERE conrelid = 'mig.change_requests'::regclass ORDER BY conname").fetchall(),
        "version": c.execute("SELECT version_num FROM alembic_version").fetchone()[0],
    }


def _check(c):
    return dict(c.execute("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = "
                          "'mig.change_requests'::regclass AND conname = 'ck_cr_idempotency_caller'").fetchall())


def test_the_upgrade_fills_each_keyed_row_with_its_caller_and_keeps_only_the_caller_index(empty_schema):
    """Rows at 0008: two written by 0007 pods (no caller), one by release 1's code, expired ones, and one with no key. Each
    keyed live row gets its caller by 0008's rule, an expired key is cleared before the fill (here one shares its caller
    and key with a live row, which the caller's index would refuse), and `uq_cr_idempotency_caller` is the only unique
    index. A live delegated key is not refused: it has one owner. Before (cb59e19): no 0009, so `head` changes nothing."""
    _run(empty_schema, "0008")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "a-0007-own", requester_sub="sub-ola", key="k1")
        _insert(c, "b-0007-svc-for-ola", requester_sub="sub-ola", key="k2", submitted_by="sub-svc", hours_ago=23)
        _insert(c, "c-release-1-svc-for-amy", requester_sub="sub-amy", key="k3", submitted_by="sub-svc", sub="sub-svc",
                with_sub=True)
        _insert(c, "d-0007-svc-own-expired", requester_sub="sub-svc", key="k2", hours_ago=25)
        _insert(c, "e-release-1-expired", requester_sub="sub-ola", key="k4", hours_ago=25, sub="sub-ola", with_sub=True)
        _insert(c, "f-no-key", requester_sub="sub-ola", key=None)
        _insert(c, "g-release-1-caller-only", requester_sub="sub-amy", key="k5", sub="sub-svc2", with_sub=True,
                requester={"requester": {"sub": "sub-amy"}, "automated": True, "submittedBy": "svc2"})

        _run(empty_schema, "head")
        rows, indexes, version = _state(c)
        assert version == "0009" == REQUIRED_REVISION, version
        assert indexes == {"uq_cr_idempotency_caller": CALLER_INDEX}, indexes
        assert indexes["uq_cr_idempotency_caller"].startswith("CREATE UNIQUE INDEX "), indexes
        assert _check(c) == {"ck_cr_idempotency_caller": CHECK}
        assert rows == {
            "a-0007-own": ("k1", "fp-a-0007-own", "sub-ola"),
            "b-0007-svc-for-ola": ("k2", "fp-b-0007-svc-for-ola", "sub-svc"),
            "c-release-1-svc-for-amy": ("k3", "fp-c-release-1-svc-for-amy", "sub-svc"),
            "d-0007-svc-own-expired": (None, None, None),
            "e-release-1-expired": (None, None, None),
            "f-no-key": (None, None, None),
            "g-release-1-caller-only": ("k5", "fp-g-release-1-caller-only", "sub-svc2"),
        }, rows


def test_the_upgrade_refuses_a_live_delegated_row_without_its_caller_and_changes_nothing(empty_schema):
    """A 0007 pod's delegated row with no `submittedBySub`: its caller is not known, and 0009 does not guess the person.
    An expired key and a row with no caller beside it show that nothing was cleared or filled. Before (cb59e19): `head`
    is 0008, so nothing is refused."""
    _run(empty_schema, "0008")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "x-delegated", requester_sub="sub-ola", key="k6", hours_ago=1,
                requester={"requester": {"sub": "sub-ola"}, "automated": True, "submittedBy": "svc"})
        _insert(c, "y-0007-own", requester_sub="sub-amy", key="k7")
        _insert(c, "z-expired", requester_sub="sub-ola", key="k8", hours_ago=30, sub="sub-ola", with_sub=True)
        before = _everything(c)
        assert before["version"] == "0008" and before["count"] == 3

        out = _refused(empty_schema, "head")
        assert "0009 refused, nothing changed: the live delegated requests x-delegated hold an Idempotency-Key" in out, out[-800:]
        assert _everything(c) == before

        c.execute("UPDATE change_requests SET created_at = now() - interval '25 hours' WHERE request_id = 'x-delegated'")
        _run(empty_schema, "head")
        rows, _indexes, version = _state(c)
        assert version == "0009" and rows == {"x-delegated": (None, None, None), "y-0007-own": ("k7", "fp-y-0007-own", "sub-amy"),
                                              "z-expired": (None, None, None)}, rows


@pytest.mark.parametrize("subject", [None, 42, ""], ids=["json-null", "a-number", "empty"])
def test_the_upgrade_refuses_each_shape_of_an_unknown_caller_and_changes_nothing(empty_schema, subject):
    """0009 keeps its own copy of 0008's ambiguity rule (`_DELEGATED_WITHOUT_CALLER`). The test above has a missing
    `submittedBySub` only, and the #592 tests of the other shapes run 0008: a broken type or empty check in 0009 passed
    them all (#630 review)."""
    _run(empty_schema, "0008")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "z-invalid", requester_sub="sub-ola", key="k8", hours_ago=1,
                requester={"requester": {"sub": "sub-ola"}, "submittedBy": "svc", "submittedBySub": subject})
        before = _everything(c)
        out = _refused(empty_schema, "head")
        assert "0009 refused, nothing changed: the live delegated requests z-invalid hold an Idempotency-Key" in out, out[-800:]
        assert _everything(c) == before


def test_the_upgrade_refuses_a_live_collision_under_the_caller_and_changes_nothing(empty_schema):
    """Two pairs that release 1's window let through: one service's key for two persons, both from 0007 pods, and one from
    a 0007 pod beside one from release 1's code. The caller's index cannot hold either pair once it is filled. Before
    (cb59e19): `head` is 0008 and keeps both."""
    _run(empty_schema, "0008")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "a-0007-for-ola", requester_sub="sub-ola", key="k1", submitted_by="sub-svc", hours_ago=2)
        _insert(c, "b-0007-for-amy", requester_sub="sub-amy", key="k1", submitted_by="sub-svc", hours_ago=1)
        _insert(c, "c-0007-for-ola", requester_sub="sub-ola", key="k2", submitted_by="sub-svc", hours_ago=3)
        _insert(c, "d-release-1-for-amy", requester_sub="sub-amy", key="k2", submitted_by="sub-svc", sub="sub-svc",
                with_sub=True)
        before = _everything(c)

        out = _refused(empty_schema, "head")
        assert ("0009 refused, nothing changed: live requests share one caller's Idempotency-Key (a-0007-for-ola, "
                "b-0007-for-amy; c-0007-for-ola, d-release-1-for-amy)") in out, out[-800:]
        assert _everything(c) == before

        c.execute("UPDATE change_requests SET created_at = now() - interval '25 hours' "
                  "WHERE request_id IN ('a-0007-for-ola', 'c-0007-for-ola')")
        _run(empty_schema, "head")
        rows, indexes, version = _state(c)
        assert version == "0009" and indexes == {"uq_cr_idempotency_caller": CALLER_INDEX}, indexes
        assert rows == {
            "a-0007-for-ola": (None, None, None),
            "b-0007-for-amy": ("k1", "fp-b-0007-for-amy", "sub-svc"),
            "c-0007-for-ola": (None, None, None),
            "d-release-1-for-amy": ("k2", "fp-d-release-1-for-amy", "sub-svc"),
        }, rows


def test_the_downgrade_restores_release_1_and_keeps_every_live_key(empty_schema):
    """0009 can be downgraded: back to release 1's two unique indexes and no check, every live key and its caller kept,
    so release 1's code finds them. An expired key is cleared, as the lookup would clear it, so that it cannot block the
    requester's index. Then up again. Before (cb59e19): there is no 0009 to downgrade."""
    _run(empty_schema, "head")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "a-own", requester_sub="sub-ola", key="k1", hours_ago=2, sub="sub-ola", with_sub=True)
        _insert(c, "b-svc-for-ola", requester_sub="sub-ola", key="k2", submitted_by="sub-svc", sub="sub-svc", with_sub=True)
        _insert(c, "c-expired-svc-for-ola", requester_sub="sub-ola", key="k1", submitted_by="sub-svc", hours_ago=25,
                sub="sub-svc", with_sub=True)

        _run(empty_schema, "0008", "--downgrade")
        rows, indexes, version = _state(c)
        assert version == "0008" and indexes == {"uq_cr_idempotency": REQUESTER_INDEX,
                                                 "uq_cr_idempotency_caller": CALLER_INDEX}, indexes
        assert _check(c) == {}
        assert rows == {"a-own": ("k1", "fp-a-own", "sub-ola"), "b-svc-for-ola": ("k2", "fp-b-svc-for-ola", "sub-svc"),
                        "c-expired-svc-for-ola": (None, None, None)}, rows

        _run(empty_schema, "head")
        assert _state(c)[1:] == ({"uq_cr_idempotency_caller": CALLER_INDEX}, "0009") and _state(c)[0] == rows


def test_the_downgrade_refuses_a_live_pair_of_one_requester_and_changes_nothing(empty_schema):
    """Since 0009 the person and a service writing for her may hold the same key (the inverted window test). Release 1's
    requester index cannot hold that pair, so the downgrade refuses while both are live, and succeeds once one is over
    24 hours old. Before (cb59e19): no 0009."""
    _run(empty_schema, "head")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "a-own", requester_sub="sub-ola", key="k1", hours_ago=2, sub="sub-ola", with_sub=True)
        _insert(c, "b-svc-for-ola", requester_sub="sub-ola", key="k1", submitted_by="sub-svc", sub="sub-svc", with_sub=True)
        before = _everything(c)
        assert before["version"] == "0009"

        out = _refused(empty_schema, "0008", "--downgrade")
        assert ("0009 downgrade refused, nothing changed: live requests share one requester's Idempotency-Key "
                "(a-own, b-svc-for-ola)") in out, out[-800:]
        assert _everything(c) == before

        c.execute("UPDATE change_requests SET created_at = now() - interval '25 hours' WHERE request_id = 'a-own'")
        _run(empty_schema, "0008", "--downgrade")
        rows, _indexes, version = _state(c)
        assert version == "0008" and rows == {"a-own": (None, None, None),
                                              "b-svc-for-ola": ("k1", "fp-b-svc-for-ola", "sub-svc")}, rows


def test_a_round_trip_through_0007_takes_the_caller_from_requester(empty_schema):
    """0008's downgrade drops `idempotency_sub`, so on the way up 0008 takes each live key's caller from `requester` again
    (docs/12, "Back to 0007"). Every row this code writes names its caller there too (`Requester.record` and
    `Pipeline.submit` both take it from the token's subject), which the HTTP round trip of #592 shows. A live row whose
    caller is in `idempotency_sub` alone is not lost in silence: 0008 refuses it on the way up, changing nothing, and
    succeeds once it is over 24 hours old. This pins the limit that docs/12 states (#630 review, finding 1)."""
    _run(empty_schema, "head")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        _insert(c, "g-caller-only", requester_sub="sub-amy", key="k5", sub="sub-svc2", with_sub=True,
                requester={"requester": {"sub": "sub-amy"}, "automated": True, "submittedBy": "svc2"})
        _run(empty_schema, "0007", "--downgrade")
        before = _state(c)
        assert before[0] == {"g-caller-only": ("k5", "fp-g-caller-only", None)} and before[2] == "0007", before

        out = _refused(empty_schema, "head")
        assert "0008 refused, nothing changed: the live delegated requests g-caller-only hold an Idempotency-Key" in out, \
            out[-800:]
        assert _state(c) == before

        c.execute("UPDATE change_requests SET created_at = now() - interval '25 hours'")
        _run(empty_schema, "head")
        assert _state(c)[0] == {"g-caller-only": (None, None, None)}


def test_rows_that_a_0007_pod_wrote_replay_for_their_caller_after_0009(empty_schema, test_config, keys, monkeypatch):
    """End to end, through HTTP. The app writes a service's request for ola and ola's own. Back at 0008 their caller is
    emptied, which is what a 0007 pod leaves on release 1's schema (its model has no `idempotency_sub`). 0009 fills it, and
    each caller's retry replays its request, by `idempotency_sub` alone. Ola's own use of the service's key is a new
    request of hers. Before (cb59e19): the caller stays empty, and ola gets 409 "in use"."""
    _run(empty_schema, "head")
    monkeypatch.setattr(conftest, "DB_URL", empty_schema)
    body = {**NS, "onBehalfOf": "ola"}
    with conftest.build_world(test_config, keys, monkeypatch) as (client, ctx, *_rest):
        _directory(ctx)
        by_service = client.post(URL, json=body, headers=_service(keys, "old-pod-svc")).json()["requestId"]
        own = client.post(URL, json=OTHER, headers=_ola(keys, "old-pod-ola")).json()["requestId"]
        ctx.db.engine.dispose()

    _run(empty_schema, "0008", "--downgrade")
    with psycopg.connect(empty_schema, autocommit=True) as c:
        c.execute("UPDATE change_requests SET idempotency_sub = NULL")
    _run(empty_schema, "head")

    with conftest.build_world(test_config, keys, monkeypatch) as (client, ctx, *_rest):
        _directory(ctx)
        assert _keys_of(ctx.db, by_service) == ("sub-ola", SVC_SUB, "old-pod-svc")
        assert _keys_of(ctx.db, own) == ("sub-ola", "sub-ola", "old-pod-ola")
        retry = client.post(URL, json=body, headers=_service(keys, "old-pod-svc"))
        assert retry.status_code == 202 and retry.json()["requestId"] == by_service, retry.text
        again = client.post(URL, json=OTHER, headers=_ola(keys, "old-pod-ola"))
        assert again.status_code == 202 and again.json()["requestId"] == own, again.text
        hers = client.post(URL, json={**OTHER, "namespace": "audit-dev"}, headers=_ola(keys, "old-pod-svc"))
        assert hers.status_code == 202 and hers.json()["requestId"] not in (by_service, own), hers.text
        ctx.db.engine.dispose()


def _plans(statements, url):
    """Each captured statement's plan, with sequential scans off so that the planner shows the index it can use."""
    found = []
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("SET enable_seqscan = off")
        for statement, params in statements:
            plan = c.execute("EXPLAIN (FORMAT JSON) " + statement, params).fetchone()[0][0]["Plan"]
            nodes, stack = [], [plan]
            while stack:
                node = stack.pop()
                nodes.append(node)
                stack.extend(node.get("Plans", []))
            found.append([(n.get("Index Name"), n.get("Index Cond", "")) for n in nodes if n.get("Index Name")])
    return found


def test_the_lookup_and_its_expiry_find_the_key_by_its_caller_through_the_caller_index(world):
    """Release 1 looked up by `key_owner()`, a COALESCE that no index serves, and expired every row of the key, by the key
    alone (#592 record: a 57 ms sequential scan on 200,000 rows). Since 0009 both statements name `idempotency_sub` and the
    key, the two columns of the caller's index. Before (cb59e19): neither plan's index condition names `idempotency_sub`."""
    _client, ctx, *_rest = world
    statements = []

    def capture(conn, cursor, statement, params, context, executemany):
        if "change_requests" in statement:
            statements.append((statement, params))

    event.listen(ctx.db.engine, "before_cursor_execute", capture)
    try:
        with ctx.db.session() as s:
            assert RequestRepo(s).by_idempotency(SVC_SUB, "plan-key") is None
    finally:
        event.remove(ctx.db.engine, "before_cursor_execute", capture)
    assert [s.split()[0] for s, _p in statements] == ["UPDATE", "SELECT"], statements
    url = conftest.DB_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    for plan in _plans(statements, url):
        assert any(name == "uq_cr_idempotency_caller" and "idempotency_sub" in cond and "idempotency_key" in cond
                   for name, cond in plan), plan


def test_a_database_at_release_1_is_behind_this_code(monkeypatch):
    """This code drops the requester's index and reads `idempotency_sub` alone, so release 1's schema is not ready for it:
    /readyz is 503 until the migrate initContainer has run 0009. Before (cb59e19): REQUIRED_REVISION was 0008."""
    assert REQUIRED_REVISION == "0009"
    assert older_than_required("0008") and not older_than_required("0009")
    db = Database(conftest.DB_URL)
    monkeypatch.setattr(db, "schema_version", lambda: "0008")
    try:
        assert db.schema_status() == "behind: at 0008, needs 0009"
    finally:
        db.engine.dispose()


def test_the_database_refuses_a_keyed_row_with_no_caller(world):
    """A 0007 image started by mistake on 0009's schema would write such rows: 0009 is a later release's revision to its
    migrator, so it migrates nothing and its /readyz is ok. The caller's index cannot see them, NULLs being distinct, so
    the database refuses them. A row with no key needs no caller. Before (cb59e19): both rows are written."""
    _client, ctx, *_rest = world
    insert = ("INSERT INTO change_requests (request_id, instance, cluster_id, namespace, env, plugin, action, status, plan, "
              "plan_hash, requester, requester_sub, requester_kind, requester_client, requester_username, idempotency_key, "
              "idempotency_fingerprint) VALUES (:r, 'test', 'CRC', :r, 'dev', 'namespaces', 'create', 'cancelled', '{}', "
              "'h', '{}', 'sub-ola', 'user', 'c', 'ola', :key, :fp)")
    with ctx.db.session() as s:
        s.execute(text(insert), {"r": "no-key", "key": None, "fp": None})
    with pytest.raises(IntegrityError) as caught, ctx.db.session() as s:
        s.execute(text(insert), {"r": "a-key", "key": "k", "fp": "fp"})
    assert isinstance(caught.value.orig, psycopg.errors.CheckViolation), caught.value
    assert caught.value.orig.diag.constraint_name == "ck_cr_idempotency_caller"
    with ctx.db.session() as s:
        assert s.execute(text("SELECT request_id FROM change_requests")).scalars().all() == ["no-key"]
