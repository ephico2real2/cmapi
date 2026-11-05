"""C4: die at every step, then let a second worker finish. A BaseException stands in for SIGKILL: nothing in run_one catches
it, the session closes without a commit, and the lease stays. What it cannot model is a request half-applied by a real host."""
from __future__ import annotations

import os
import signal
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import text

from cmapi.core.clients.kube import ClusterUnreachable
from cmapi.core.db.repo import JobRepo, utcnow
from cmapi.core.git.base import GitUnavailable
from cmapi.worker import Worker
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs
from test_review_d_delivery import run_until, status


class Killed(BaseException):
    pass


def lease_expired(ctx):
    with ctx.db.session() as s:
        s.execute(text("update jobs set locked_until = now() - interval '1 second', run_after = now() - interval '1 second' where done_at is null"))


def drain(w, ctx, limit=30):
    for _ in range(limit):
        lease_expired(ctx)
        if not w.run_one():
            return


STEPS = [("git", m, w) for m in ("read_folder", "open_pr", "pr_status", "branch_head", "set_check", "merge") for w in ("before", "after")] + \
        [("kube", "apply", w) for w in ("before", "after")] + [("session", "commit", "before")]


@pytest.mark.parametrize("target,method,when", STEPS)
def test_kill_at_each_step_resumes_with_nothing_doubled(world, target, method, when, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    w1, w2 = Worker(ctx, "w1"), Worker(ctx, "w2")
    fired = {"n": 0}
    if target == "session":
        from sqlalchemy.orm import Session
        real = Session.commit
        marks = {"n": 0}

        def commit(self):
            # die on the commit that closes the merge transaction
            if not fired["n"] and git.prs and git.prs[1]["state"] == "merged":
                fired["n"] = 1
                raise Killed()
            return real(self)
        monkeypatch.setattr(Session, "commit", commit)
    else:
        obj = {"git": git, "kube": kube}[target]
        real = getattr(obj, method)

        def wrapped(*a, **k):
            if not fired["n"] and when == "before":
                fired["n"] = 1
                raise Killed()
            out = real(*a, **k)
            if not fired["n"] and when == "after":
                fired["n"] = 1
                raise Killed()
            return out
        monkeypatch.setattr(obj, method, wrapped)
    with pytest.raises(Killed):
        for _ in range(10):
            w1.run_one()
    drain(w2, ctx)
    v = status(client, keys, rid)
    assert v["status"] == "synced", (target, method, when, v["status"], [e["note"] for e in v["events"]][-3:])
    assert len(git.prs) == 1, f"{len(git.prs)} PRs"
    assert len(git.commits) == 2, git.commits
    assert sum(1 for e in v["events"] if e["event"] == "pr_opened") == 1
    assert sum(1 for e in v["events"] if e["event"] == "merged") == 1


def test_sigterm_mid_job_finishes_the_job_and_stops_the_loop(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    w = Worker(ctx, "w1", poll_seconds=0.01)
    old = signal.signal(signal.SIGTERM, w.stop)
    real = git.open_pr

    def open_pr(*a, **k):
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(0.05)
        return real(*a, **k)
    git.open_pr = open_pr
    try:
        w.loop()
    finally:
        signal.signal(signal.SIGTERM, old)
    v = status(client, keys, rid)
    assert v["status"] == "pr_open" and len(git.prs) == 1, v["status"]
    with ctx.db.session() as s:
        assert s.execute(text("select count(*) from jobs where locked_until > now() and done_at is null")).scalar() == 0


def test_two_workers_whole_flow_each_step_once(world):
    client, ctx, git, kube, validator, keys = world
    rids = [client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": f"pay-{i}", "labels": {"cmapi.net/team": f"team-{i}"}},
                        headers=auth(keys, "ola", **OLA)).json()["requestId"] for i in range(6)]
    # FakeGit asserts base_sha == main: serialise the host, not the claim, so the claim is what is under test
    lock = threading.Lock()
    for name in ("open_pr", "merge", "read_folder", "pr_status", "set_check", "branch_head"):
        real = getattr(git, name)
        setattr(git, name, (lambda r: (lambda *a, **k: _locked(lock, r, a, k)))(real))
    stop = threading.Event()

    def loop(i):
        w = Worker(ctx, f"w{i}")
        idle = 0
        while idle < 15:
            with ctx.db.session() as s:
                s.execute(text("update jobs set run_after = now() - interval '1 second' where done_at is null and locked_until is null and kind <> 'approval_timeout'"))
            idle = 0 if w.run_one() else idle + 1
    ts = [threading.Thread(target=loop, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    with ctx.db.session() as s:
        rows = s.execute(text("select status, count(*) from change_requests group by 1")).all()
        dup = s.execute(text("select request_id, event, count(*) from request_events where event in ('pr_opened','merged','synced') group by 1,2 having count(*)>1")).all()
        by = s.execute(text("select locked_by, count(*) from jobs where kind<>'approval_timeout' group by 1")).all()
    print("statuses", rows, "by worker", by)
    assert dup == [], dup
    assert len(git.prs) == 6, len(git.prs)


def _locked(lock, real, a, k):
    with lock:
        return real(*a, **k)


def test_a_job_outliving_its_lease_is_not_run_twice(world, monkeypatch):
    """Worst case for pr_checks is about 320 s: Git 20 s a call, kubeconform and kyverno 60 s each, the lease a fixed 300 s.
    Here the lease is 1 s and the job takes 2.5 s; a second worker polls throughout."""
    client, ctx, git, kube, validator, keys = world
    import cmapi.worker as wm
    monkeypatch.setattr(wm, "LEASE_SECONDS", 1, raising=False)
    monkeypatch.setattr(JobRepo.claim, "__defaults__", (1,))
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    with ctx.db.session() as s:
        s.execute(text("update jobs set locked_until = now() + interval '1 hour' where kind = 'approval_timeout'"))
    calls = []
    real = git.open_pr
    started = threading.Event()

    def slow(*a, **k):
        calls.append(threading.current_thread().name)
        started.set()
        time.sleep(2.5)
        return real(*a, **k)
    git.open_pr = slow
    t1 = threading.Thread(target=Worker(ctx, "w1").run_one, name="w1")
    t1.start()
    started.wait(5)
    w2 = Worker(ctx, "w2")
    deadline = time.time() + 2.2
    second = threading.current_thread().name
    while time.time() < deadline and t1.is_alive():
        try:
            w2.run_one()
        except Exception:
            pass
        time.sleep(0.1)
    t1.join()
    assert len(calls) == 1, f"open_pr entered by {calls}"


def test_pruned_confirmation_needs_a_successful_read(world):
    """_direct() turns a read failure into None: a cluster outage must not read as 'namespace removed'."""
    client, ctx, git, kube, validator, keys = world
    ctx.delivery = type(ctx.delivery)(mode="argocd")          # no delete from cmapi; the read alone decides
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    kube.apply({"kind": "Namespace", "metadata": {"name": "payments-dev", "labels": {"cmapi.net/managed": "true"}}})
    from cmapi.core.db.models import ChangeRequestRow
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='awaiting_prune', action='delete', plan = jsonb_set(plan,'{spec}','null')"))
        rid = s.execute(text("select request_id from change_requests")).scalar()
        JobRepo(s).enqueue("prune", request_id=rid, cluster_id="CRC")
        s.execute(text("delete from jobs where kind='open_pr'"))
    real = kube.get_object

    def boom(*a, **k):
        raise ClusterUnreachable("the API server is down")
    kube.get_object = boom
    w = Worker(ctx, "w")
    for _ in range(2):
        lease_expired(ctx)
        w.run_one()
    kube.get_object = real
    assert status(client, keys, rid)["status"] == "awaiting_prune", "a read failure ended the request as synced"


def test_reader_cluster_down_waits_out_the_sync_timeout(world):
    """registry.cache() raises Problem(503) when the import is not connected; watch_sync only treats kube errors as waiting."""
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    st = ctx.registry.clusters["CRC"]
    saved = st.cache
    st.cache = None
    st.status = "unreachable"
    ctx.delivery = type(ctx.delivery)(mode="apply", poll_seconds=0, sync_timeout_seconds=1800)
    w = Worker(ctx, "w")
    for _ in range(8):
        lease_expired(ctx)
        w.run_one()
    st.cache = saved
    v = status(client, keys, rid)
    assert v["status"] == "merged", f"{v['status']} after 8 polls inside a 30-minute timeout: {v['events'][-1]['note'][:100]}"


def test_retry_from_sync_failed_really_watches_again(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    ctx.delivery = type(ctx.delivery)(mode="apply", poll_seconds=0, sync_timeout_seconds=60)
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed', merged_at = now() - interval '1 hour' where request_id=:r"), {"r": rid})
        s.execute(text("delete from jobs where kind='watch_sync'"))
    assert client.post(f"/api/v1/requests/{rid}:retry", headers=auth(keys, "opal", **OPAL)).status_code == 200
    real = kube.apply
    n = {"v": 0}

    def flaky(doc, field_manager="cmapi-deliverer"):
        n["v"] += 1
        if n["v"] == 1:
            raise ClusterUnreachable("one blip")
        return real(doc, field_manager)
    kube.apply = flaky
    w = Worker(ctx, "w")
    for _ in range(6):
        lease_expired(ctx)
        w.run_one()
    assert status(client, keys, rid)["status"] == "synced", f"one blip after :retry ended the watch: applies={n['v']}"


def test_git_outage_during_open_revert_loses_nothing(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": rid})
        s.execute(text("delete from jobs where kind='watch_sync'"))
    assert client.post(f"/api/v1/requests/{rid}:revert", headers=auth(keys, "opal", **OPAL)).status_code == 200
    git.down = True
    w = Worker(ctx, "w")
    for _ in range(7):
        lease_expired(ctx)
        w.run_one()
    with ctx.db.session() as s:
        n = s.execute(text("select count(*) from change_requests")).scalar()
        pend = s.execute(text("select count(*) from jobs where kind='open_revert' and done_at is null")).scalar()
    v = status(client, keys, rid)
    assert n == 2 or v["status"] == "sync_failed", f"status {v['status']}: reverted, no new request, {pend} jobs pending"


def test_worker_survives_a_database_not_ready_at_startup(world, monkeypatch):
    """helm's post-install migrate runs after --wait: the worker can start before the tables exist."""
    client, ctx, git, kube, validator, keys = world
    w = Worker(ctx, "w", poll_seconds=0.01)
    real = JobRepo.pending
    n = {"v": 0}

    def pending(self, kind, request_id=None):
        n["v"] += 1
        if n["v"] == 1:
            from sqlalchemy.exc import ProgrammingError
            raise ProgrammingError("select", {}, Exception('relation "jobs" does not exist'))
        return real(self, kind, request_id)
    monkeypatch.setattr(JobRepo, "pending", pending)
    threading.Timer(0.3, w.stop).start()
    w.loop()
    assert n["v"] >= 2
