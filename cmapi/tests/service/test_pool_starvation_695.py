"""The #695 review: a submit read the auto-approval switch in a second pooled session while its own transaction held a
connection and the day's advisory lock. The submits queued behind that lock each hold a connection, so with as many
submits at once as the pool has connections (5 and 5 overflow) the holder found none, waited 30 s and answered 500, and
other routes needing that pool could wait with it."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from sqlalchemy import event, text

import cmapi.worker as worker_mod
from cmapi.core.db.models import SwitchRow
from cmapi.core.db.repo import RequestRepo, SwitchRepo
from cmapi.worker import Worker

from test_flow import OLA, OPAL
from test_rate_limits_689 import NS, REQUESTER, URL, auth, limited  # noqa: F401  (limited is a fixture)
from test_review_d_delivery import run_until_merged
from test_review_e_recovery import lease_expired

POOL_LIMIT = 10     # make_engine (core/db/__init__.py): pool_size 5 and max_overflow 5


def test_a_create_holds_one_connection_at_a_time(limited):
    world, _ = limited
    client, ctx, *_, keys = world
    pool, most = ctx.db.engine.pool, []

    def checkout(*_args):
        most.append(pool.checkedout())

    event.listen(pool, "checkout", checkout)
    try:
        r = client.post(URL, json=NS, headers=auth(keys, "ola", **REQUESTER))
    finally:
        event.remove(pool, "checkout", checkout)
    assert r.status_code == 202, r.text
    assert max(most) == 1, most


def test_more_creates_at_once_than_the_pool_has_connections_all_succeed(limited):
    world, _ = limited
    client, ctx, *_, keys = world
    pool = ctx.db.engine.pool

    def create(i: int) -> int:
        body = {**NS, "namespace": f"payments-n{i}-dev"}
        return client.post(URL, json=body, headers=auth(keys, f"user{i}", **REQUESTER)).status_code

    # The first ten submits wait, each on its own checked-out connection, just before the day's lock: the pool is then at its
    # limit when the first of them takes the lock, whatever order the threads ran in. Later submits pass the opened gate.
    at_fill: list[int] = []
    filled = Event()

    def fill() -> None:
        at_fill.append(pool.checkedout())
        filled.set()

    first_wave = Barrier(POOL_LIMIT, action=fill, timeout=60)

    def before_sql(conn, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock" in statement and not filled.is_set():
            first_wave.wait()

    event.listen(ctx.db.engine, "before_cursor_execute", before_sql)
    try:
        with ThreadPoolExecutor(12) as executor:
            statuses = list(executor.map(create, range(12)))
    finally:
        event.remove(ctx.db.engine, "before_cursor_execute", before_sql)
    assert at_fill == [POOL_LIMIT], f"the pool was not full when the lock was taken: {at_fill}"
    assert statuses == [202] * 12, statuses


def test_the_revert_job_reads_the_switch_in_its_own_transaction(world, monkeypatch):
    """open_revert decides after repo.move locked the request's row: the switch is read on the job's connection, so the job
    checks out no second one while it holds that lock."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until_merged(ctx) == "watch_sync"
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": rid})
        s.execute(text("delete from jobs where kind='watch_sync'"))
    assert client.post(f"/api/v1/requests/{rid}:revert", headers=auth(keys, "opal", **OPAL)).status_code == 200
    pool, real, during = ctx.db.engine.pool, worker_mod.HANDLERS["open_revert"], []

    def checkout(*_args):
        during.append(pool.checkedout())

    def measured(c, s, job):
        event.listen(pool, "checkout", checkout)
        try:
            real(c, s, job)
        finally:
            event.remove(pool, "checkout", checkout)

    monkeypatch.setitem(worker_mod.HANDLERS, "open_revert", measured)
    w = Worker(ctx, "w")
    for _ in range(7):
        lease_expired(ctx)
        w.run_one()
    with ctx.db.session() as s:
        assert s.execute(text("select count(*) from change_requests")).scalar() == 2, "the revert opened no request"
    assert during == [], f"the revert job checked out more connections while it held the row lock: {during}"


def test_switch_read_after_lock_sees_a_committed_pause(world):
    _, ctx, *_ = world
    with ctx.db.session() as submit:
        RequestRepo(submit).next_id()
        with ctx.db.session() as admin:
            SwitchRepo(admin).set("auto-approval", {"paused": True}, "admin")
            admin.flush()
            assert ctx.auto_paused(submit) is False
        assert ctx.auto_paused(submit) is True


def test_a_switch_read_in_a_transaction_that_holds_the_row_sees_a_pause_committed_since(world):
    """The kill switch is read by a query, never from the session's identity map. Session.get returns a row the session holds
    "directly from this collection and no SQL is emitted" (SQLAlchemy 2.1), so a caller whose transaction keeps the switch row
    would miss a pause committed after it loaded it. PostgreSQL, at READ COMMITTED, answers a new query with what committed
    before that query began."""
    _, ctx, *_ = world
    with ctx.db.session() as admin:
        SwitchRepo(admin).set("auto-approval", {"paused": False}, "admin")
    with ctx.db.session() as job:
        held = job.get(SwitchRow, "auto-approval")
        assert ctx.auto_paused(job) is False
        with ctx.db.session() as admin:
            SwitchRepo(admin).set("auto-approval", {"paused": True}, "admin")
        RequestRepo(job).next_id()
        assert ctx.auto_paused(job) is True
        assert held.value == {"paused": False}, "the read changed the caller's row"
