"""The #695 review: a submit read the auto-approval switch in a second pooled session while its own transaction held a
connection and the day's advisory lock. The submits queued behind that lock each hold a connection, so with as many
submits at once as the pool has connections (5 and 5 overflow) the holder found none, waited 30 s and answered 500, and
every other route of the pod waited with it."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event

from test_rate_limits_689 import NS, REQUESTER, URL, auth, limited  # noqa: F401  (limited is a fixture)


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

    def create(i: int) -> int:
        body = {**NS, "namespace": f"payments-n{i}-dev"}
        return client.post(URL, json=body, headers=auth(keys, f"user{i}", **REQUESTER)).status_code

    started = time.monotonic()
    with ThreadPoolExecutor(12) as pool:
        statuses = list(pool.map(create, range(12)))
    assert statuses == [202] * 12, statuses
    assert time.monotonic() - started < 25, "a submit waited for a pooled connection"
