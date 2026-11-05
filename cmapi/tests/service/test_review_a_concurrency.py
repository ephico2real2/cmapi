"""C3: races on real PostgreSQL. Each test asserts the correct outcome; a barrier makes the bad interleaving certain,
and test_natural_race_rate measures how often it happens with no barrier at all."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from cmapi.core.db.repo import RequestRepo
from test_flow import AMY, NS, OLA, auth, run_jobs

LEAD = lambda: dict(roles=["cmapi-approver"], groups=["/cmapi/cmapi-platform-leads"])


def pending(client, keys, ns="critical-a", seats=2, ctx=None):
    ctx.cfg.approvals.patterns[0]["required"] = seats       # critical-*: N from platform-leads
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": ns}, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    return r.json()["requestId"]


@pytest.fixture
def barrier_after_read(monkeypatch):
    """Two callers both finish reading the approvals before either writes; a blocked caller (a row lock) times out and goes on."""
    b = threading.Barrier(2)
    real = RequestRepo.ledger

    def ledger(self, row):
        out = real(self, row)
        try:
            b.wait(0.7)
        except threading.BrokenBarrierError:
            pass
        return out
    monkeypatch.setattr(RequestRepo, "ledger", ledger)


def parallel(*fns):
    with ThreadPoolExecutor(len(fns)) as ex:
        return [f.result() for f in [ex.submit(fn) for fn in fns]]


def test_two_approvers_at_once_complete_a_two_seat_request(world, barrier_after_read):
    client, ctx, git, kube, validator, keys = world
    rid = pending(client, keys, ctx=ctx)
    a, b = parallel(lambda: client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **LEAD())),
                    lambda: client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "bob", **LEAD())))
    assert (a.status_code, b.status_code) == (200, 200), (a.text, b.text)
    v = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert v["status"] == "approved", f"two approvals recorded, status {v['status']}, remaining {v['approval']['remaining']}"


def test_same_approver_twice_at_once_counts_once(world, barrier_after_read):
    client, ctx, git, kube, validator, keys = world
    rid = pending(client, keys, seats=3, ctx=ctx)
    a, b = parallel(lambda: client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **LEAD())),
                    lambda: client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **LEAD())))
    with ctx.db.session() as s:
        n = s.execute(text("select count(*) from approvals where request_id=:r"), {"r": rid}).scalar()
    assert n == 1, f"one person, {n} approval rows; responses {a.status_code} {b.status_code}"
    # ... and so a third approver must not complete a three-seat request with two people
    c = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "bob", **LEAD()))
    v = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert v["status"] == "pending_approval", f"approved by two people on three seats: {[x['username'] for x in v['approval']['approvals']]} {c.status_code}"


def test_approve_against_reject_has_one_winner(world, barrier_after_read):
    """The reject path reads through repo.get, not ledger: order the reject to commit first, approve second."""
    client, ctx, git, kube, validator, keys = world
    rid = pending(client, keys, seats=1, ctx=ctx)
    ap = client.post
    a, r = parallel(lambda: ap(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **LEAD())),
                    lambda: ap(f"/api/v1/requests/{rid}:reject", json={"comment": "no"}, headers=auth(keys, "bob", **LEAD())))
    v = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    ok = sorted([a.status_code, r.status_code])
    assert ok in ([200, 409],), f"approve {a.status_code} reject {r.status_code}, final {v['status']}, events {[e['event'] for e in v['events']]}"


def test_reject_committed_while_approve_is_mid_flight_is_not_overwritten(world, monkeypatch):
    """The reject arrives between the approve's read and its write. Base: it commits, then the approve overwrites it.
    A correct lock makes it wait for the approve and lose (409); the join's timeout lets the approve go on."""
    client, ctx, git, kube, validator, keys = world
    rid = pending(client, keys, seats=1, ctx=ctx)
    real = RequestRepo.ledger
    box = {}

    def ledger(self, row):
        out = real(self, row)
        if "t" not in box:
            def reject():
                box["r"] = client.post(f"/api/v1/requests/{rid}:reject", json={"comment": "no"}, headers=auth(keys, "bob", **LEAD()))
            box["t"] = threading.Thread(target=reject)
            box["t"].start()
            box["t"].join(1.0)
        return out
    monkeypatch.setattr(RequestRepo, "ledger", ledger)
    a = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **LEAD()))
    box["t"].join()
    monkeypatch.undo()
    v = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    run_jobs(ctx)
    assert not (box["r"].status_code == 200 and git.prs), f"rejected (200) yet a PR opened: approve {a.status_code}, final {v['status']}"
    assert (a.status_code, box["r"].status_code) == (200, 409), (a.status_code, box["r"].status_code)


def test_natural_race_rate_two_approvers(world, capsys):
    """No barrier: how often does a plain simultaneous approve leave a two-seat request stuck?"""
    client, ctx, git, kube, validator, keys = world
    stuck = 0
    N = 40
    for i in range(N):
        rid = pending(client, keys, ns=f"critical-n{i}", ctx=ctx)
        go = threading.Barrier(2)

        def call(u):
            go.wait()
            return client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, u, **LEAD()))
        parallel(lambda: call("amy"), lambda: call("bob"))
        if client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] != "approved":
            stuck += 1
    with capsys.disabled():
        print(f"\n[measure] natural race, no barrier: {stuck}/{N} two-seat requests stuck pending after two approvals")
    assert stuck == 0


def test_sequential_two_approvers_is_the_control(world):
    """The neighbour of the race: the same two approvals one after the other complete the request."""
    client, ctx, git, kube, validator, keys = world
    rid = pending(client, keys, ns="critical-seq", ctx=ctx)
    assert client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **LEAD())).status_code == 200
    assert client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "bob", **LEAD())).json()["status"] == "approved"


def test_two_creates_of_one_namespace(world):
    client, ctx, git, kube, validator, keys = world
    rs = parallel(*[lambda: client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": "race-ns", "tier": "large"},
                                        headers=auth(keys, "ola", **OLA)) for _ in range(6)])
    codes = sorted(r.status_code for r in rs)
    assert codes == [202] + [409] * 5, [r.text[:120] for r in rs]
    assert {r.json()["code"] for r in rs if r.status_code == 409} == {"change-pending"}
    with ctx.db.session() as s:
        assert s.execute(text("select count(*) from change_requests")).scalar() == 1


def test_same_key_same_body_in_parallel_returns_the_first_response(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    body = {**NS, "namespace": "idem-ns", "tier": "large"}
    rs = parallel(*[lambda: client.post("/api/v1/clusters/CRC/namespaces", json=body, headers=h) for _ in range(4)])
    assert [r.status_code for r in rs] == [202] * 4, [(r.status_code, r.json().get("code")) for r in rs]
    assert len({r.json()["requestId"] for r in rs}) == 1


def test_same_key_different_bodies_in_parallel_one_wins(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    rs = parallel(*[lambda i=i: client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": f"idem-{i}", "tier": "large"}, headers=h)
                    for i in range(4)])
    assert sorted(r.status_code for r in rs) == [202, 409, 409, 409], [(r.status_code, r.text[:100]) for r in rs]
    assert {r.json()["code"] for r in rs if r.status_code == 409} == {"idempotency-replay"}
    with ctx.db.session() as s:
        assert s.execute(text("select count(*) from change_requests")).scalar() == 1


def test_idempotency_key_is_bound_to_the_cluster(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    assert client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h).status_code == 202
    r = client.post("/api/v1/clusters/NOPE/namespaces", json=NS, headers=h)
    assert r.status_code != 202, f"same key, another cluster: replayed {r.json().get('requestId')} on CRC"


def test_long_idempotency_key_is_a_4xx_not_a_500(world):
    client, ctx, git, kube, validator, keys = world
    from fastapi.testclient import TestClient
    c = TestClient(client.app, raise_server_exceptions=False)
    h = {**auth(keys, "ola", **OLA), "Idempotency-Key": "k" * 101}
    r = c.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    assert 400 <= r.status_code < 500, r.status_code


def test_daily_allowance_holds_under_parallel_submits(world):
    client, ctx, git, kube, validator, keys = world
    ctx.cfg.approvals.max_per_team = 1
    rs = parallel(*[lambda i=i: client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": f"allow-{i}"}, headers=auth(keys, "ola", **OLA))
                    for i in range(6)])
    autos = [r.json()["approval"]["auto"] for r in rs if r.status_code == 202]
    ctx.cfg.approvals.max_per_team = 20
    assert sum(1 for x in autos if x and x.startswith("auto:")) == 1, autos


def test_two_workers_claim_each_job_once(world):
    client, ctx, git, kube, validator, keys = world
    from cmapi.core.db.repo import JobRepo
    with ctx.db.session() as s:
        jobs = JobRepo(s)
        for i in range(200):
            jobs.enqueue("noop", payload={"kind": str(i)})
    got: list[list[int]] = [[], [], [], []]

    def worker(i):
        while True:
            with ctx.db.session() as s:
                j = JobRepo(s).claim(f"w{i}")
                if j is None:
                    return
                got[i].append(j.job_id)
    parallel(*[lambda i=i: worker(i) for i in range(4)])
    flat = [x for g in got for x in g]
    assert len(flat) == 200 and len(set(flat)) == 200, (len(flat), len(set(flat)))
