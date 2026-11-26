"""PR #725 review (reviewer 2): the reservation edges that the PR's own file does not reach.

The design: docs/02, Placement, "Reservations": "Placement takes a reservation inside the same transaction as the capacity
check, under a per-cluster advisory lock, so concurrent requests see each other. The reservation ends when the namespace's
ResourceQuota appears in cmapi's watch cache of that cluster. Committed quota counts it from then on, so it is never counted
twice." docs/01, the lifecycle: "approved: The count is met (auto or :approve) and capacity still fits"; Quota changes: "An
increase reserves its delta like a placement and is checked again when approved."

The cluster of `world`: 128 cores and 320Gi after overcommit; a small namespace is 8 cores and 16Gi.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import timedelta
from decimal import Decimal

import psycopg
import pytest
import yaml
from sqlalchemy import text

from cmapi.core.capacity_backend import CapacityHold
from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.db.repo import JobRepo, RequestRepo, ReservationRepo
from cmapi.core.errors import Problem
from cmapi.core.lifecycle import Event as E
from cmapi.core.tiers import qty
from conftest import DB_URL
from test_capacity_reservations_62 import AMY, OLA, auth, body, committed, create, holds, who
from test_review_h_tools_migrate import empty_schema, migrate  # noqa: F401  (empty_schema is a fixture)

OPAL = dict(roles=["cmapi-operator", "cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-operator"])


def own_quota(ctx, rid: str) -> dict:
    """The request's rendered ResourceQuota, as the watch delivers it after the apply."""
    with ctx.db.session() as s:
        files = s.get(ChangeRequestRow, rid).plan["files"]
    return yaml.safe_load(next(t for p, t in files.items() if "/resourcequota-" in p))


def land(ctx, quota: dict, kind: str = "ADDED") -> None:
    ctx.registry.cache("CRC")._event("ResourceQuota", {"type": kind, "object": quota})


# ---- the check reads the holds and the ledger as one instant

def test_a_quota_that_lands_during_the_check_is_counted_once(world, monkeypatch):
    """96 committed and one request holding 8 (104). Its quota reaches the watch while the check reads the holds: the check
    must count those 8 cores once, as the hold or as the quota. Head read the cluster's total before the holds and each held
    namespace after them, so it counted them neither way (96, 0.75)."""
    client, ctx, *_ = world
    committed(ctx, 96)
    rid = create(world, "payments-a").json()["requestId"]
    quota, real = own_quota(ctx, rid), ReservationRepo.active

    def active(self, *args, **kw):
        rows = real(self, *args, **kw)
        land(ctx, quota)                                   # the watch event arrives between the two reads
        return rows
    monkeypatch.setattr(ReservationRepo, "active", active)
    assert ctx.pipeline.capacity.check("CRC", "dev", 0, 0).detail["cpu"] == 0.812          # (96 + 8) / 128


def test_one_reader_seeing_a_quota_does_not_end_the_hold_for_a_reader_still_behind(world):
    """The API pods and the worker each have their own watch (docs/02: cmapi runs several replicas). One reader sees request
    A's quota and takes a hold for B; a reader whose watch has not delivered A's quota yet must still count A's hold. Head
    marked A's hold released (`observed`) for every reader at B's submit, so the reader behind counted A nowhere (0.812)."""
    client, ctx, *_ = world
    committed(ctx, 96)
    a = create(world, "payments-a").json()["requestId"]
    quota = own_quota(ctx, a)
    land(ctx, quota)                                       # this reader's watch has A's quota
    assert create(world, "payments-b").status_code == 202
    land(ctx, quota, "DELETED")                            # the same database, read by a reader whose watch is behind
    assert ctx.pipeline.capacity.check("CRC", "dev", 0, 0).detail["cpu"] == 0.875          # (96 + 8 A + 8 B) / 128
    assert {h.request_id for h in holds(ctx)} >= {a}


def test_a_fractional_quota_stops_counting_once_the_ledger_shows_it(world):
    """A memory quota of 1.1Gi is 1181116006.4 bytes; the ledger keeps it exactly. The hold's amount is rounded up (never
    smaller than the increase it was checked for), but its target must not be: head stored 1181116007, which the live quota
    never reaches, so the hold was counted beside it until the request synced. The catalog's custom bounds step by 1Gi, so
    a revert of a quota written by hand is the way such a target reaches reserve (restore_facts)."""
    client, ctx, *_ = world
    a = create(world, "payments-a").json()["requestId"]                      # holds 8 cores and 16Gi, not live
    frac = qty("1.1Gi")
    with ctx.db.session() as s:
        ctx.pipeline.capacity.reserve(s, a, "CRC", CapacityHold("restored", Decimal(4), frac, 0, Decimal(4), frac),
                                      timedelta(hours=1))
    land(ctx, {"kind": "ResourceQuota", "metadata": {"name": "q", "namespace": "restored",
                                                     "labels": {"cmapi.net/managed": "true"}},
               "spec": {"hard": {"requests.cpu": "4", "requests.memory": "1.1Gi"}}})
    assert ctx.pipeline.capacity.check("CRC", "dev", 0, 0).detail["reserved"] == {"cpu": 8.0, "memory": 16 * 2**30}


# ---- the last approval checks capacity even when the hold lapsed

@pytest.mark.parametrize("room_taken", [True, False])
def test_the_last_approval_after_the_hold_lapsed_checks_again(world, room_taken):
    """116 committed, request A pending (124). A's hold lapses (the hourly approval_timeout job runs late), and B takes the
    room. The last approval of A must check that capacity still fits (docs/01) and refuse it at 132. Head found no active
    hold, skipped the check and approved A. When the room is still free, the approval re-takes A's hold."""
    client, ctx, *_, keys = world
    committed(ctx, 116)
    rid = create(world, "payments-a").json()["requestId"]
    url = f"/api/v1/requests/{rid}:approve"
    assert client.post(url, json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    with ctx.db.session() as s:
        s.execute(text("UPDATE capacity_reservations SET expires_at = now() - interval '1 minute'"))
    if room_taken:
        assert create(world, "payments-b").status_code == 202
    r = client.post(url, json={}, headers=auth(keys, "ben", **AMY))
    if room_taken:
        assert r.status_code == 422 and r.json()["code"] == "capacity-exceeded", r.text
        assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] == "pending_approval"
    else:
        assert r.status_code == 200 and r.json()["status"] == "approved", r.text
        assert [h.request_id for h in holds(ctx)] == [rid]
        assert ctx.pipeline.capacity.check("CRC", "dev", 0, 0).detail["reserved"]["cpu"] == 8.0


# ---- lock order: :retry and submit take the cluster's lock and the namespace's lock in one order

def _waiting_on_an_advisory_lock(timeout: float = 10) -> bool:
    with psycopg.connect(DB_URL, autocommit=True) as c:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if c.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted").fetchone()[0]:
                return True
            time.sleep(0.05)
    return False


def test_a_retry_and_a_submit_on_one_namespace_do_not_deadlock(world):
    """Request X on payments-a failed (it released the namespace and its hold). A submit of a new create of payments-a holds
    the cluster's lock (reserve_check) when an operator's :retry of X arrives. Head's retry took the namespace (the unique
    index entry) before it asked for the cluster's lock, and the submit then waited on that entry: PostgreSQL broke the
    deadlock by aborting one of them (40P01). Taking the cluster's lock first, the submit wins and the retry is 409."""
    client, ctx, *_, keys = world
    committed(ctx, 96)
    x = create(world, "payments-a").json()["requestId"]
    with ctx.db.session() as s:
        repo = RequestRepo(s)
        repo.move(repo.get(x), E.PR_FAILED, "worker", "test")
    plan = ctx.pipeline.plan_namespace(who(), "CRC", body("payments-a"), action="create")
    locked, go, out = threading.Event(), threading.Event(), {}

    def submit():
        try:
            with ctx.db.session() as s:
                ReservationRepo(s).lock_cluster("CRC")      # where reserve_check has it
                locked.set()
                go.wait(15)
                ctx.pipeline.submit(who(), plan, RequestRepo(s), JobRepo(s), idempotency_key=None, body_fingerprint="z",
                                    justification=None)
            out["submit"] = "held"
        except Problem as exc:
            out["submit"] = exc.code
        except Exception as exc:                            # noqa: BLE001  (a deadlock is a DBAPIError, not a Problem)
            out["submit"] = getattr(getattr(exc, "orig", None), "sqlstate", type(exc).__name__)

    def retry():
        r = client.post(f"/api/v1/requests/{x}:retry", headers=auth(keys, "opal", **OPAL))
        out["retry"] = (r.status_code, r.json().get("code"))

    t1 = threading.Thread(target=submit)
    t1.start()
    assert locked.wait(15)
    t2 = threading.Thread(target=retry)
    t2.start()
    assert _waiting_on_an_advisory_lock(), "the retry waits on the cluster's lock"
    go.set()
    t1.join(30)
    t2.join(30)
    assert out == {"submit": "held", "retry": (409, "change-pending")}, out


# ---- migration 0011 over requests in flight

ROW = """INSERT INTO change_requests (request_id, instance, cluster_id, namespace, env, plugin, action, status, plan, plan_hash,
         requester, requester_sub, requester_kind, requester_client, requester_username, requirement)
         VALUES (%s, 'i', 'CRC', %s, 'dev', 'namespaces', %s, %s, %s, 'h', '{}', 's', 'user', 'c', 'u', %s)"""


def _quota_file(ns: str, cpu: str, memory: str) -> dict[str, str]:
    q = {"apiVersion": "v1", "kind": "ResourceQuota",
         "metadata": {"name": f"{ns}-quota", "namespace": ns, "labels": {"cmapi.net/managed": "true"}},
         "spec": {"hard": {"requests.cpu": cpu, "requests.memory": memory, "pods": "50"}}}
    return {f"clusters/CRC/namespaces/{ns}/resourcequota-{ns}-quota.yaml": yaml.safe_dump(q)}


def test_0011_holds_the_increases_of_requests_in_flight_up_down_up(empty_schema):  # noqa: F811
    """Requests recorded by 0010's code hold the increase of their plan from the upgrade on (docs/01's Reservation column):
    a pending create (8 cores, 16Gi) and an approved update (8 to 16 cores) hold; a failed one keeps its amounts released,
    for its :retry to take again and check; a rejected one and a decrease hold nothing. Head created an empty table."""
    def run(*args):
        p = migrate(empty_schema, *args)
        output = p.communicate()[0]
        assert p.returncode == 0, output[-1500:]
    run("0010")
    small, medium = _quota_file("n-create", "8", "16Gi"), _quota_file("n-update", "16", "16Gi")
    rows = [("r-create", "n-create", "create", "pending_approval", {"files": small, "prev": {}}),
            ("r-update", "n-update", "update", "approved",
             {"files": medium, "prev": _quota_file("n-update", "8", "16Gi")}),
            ("r-failed", "n-failed", "create", "failed", {"files": _quota_file("n-failed", "8", "16Gi"), "prev": {}}),
            ("r-rejected", "n-rejected", "create", "rejected", {"files": _quota_file("n-rejected", "8", "16Gi"), "prev": {}}),
            ("r-lower", "n-lower", "update", "pending_approval",
             {"files": _quota_file("n-lower", "4", "8Gi"), "prev": _quota_file("n-lower", "8", "16Gi")})]
    with psycopg.connect(empty_schema, autocommit=True) as c:
        for rid, ns, action, status, plan in rows:
            c.execute(ROW, (rid, ns, action, status, json.dumps(plan), json.dumps({"timeoutHours": 4})))
        for step in range(2):
            run("0011")
            got = c.execute("""SELECT request_id, cpu, memory, target_cpu, target_memory, released_why,
                                      expires_at > now() + interval '4 hours 59 minutes'
                                 FROM capacity_reservations ORDER BY request_id""").fetchall()
            assert [(r, float(cpu), m, float(tc), tm, why, live) for r, cpu, m, tc, tm, why, live in got] == [
                ("r-create", 8.0, 16 * 2**30, 8.0, 16 * 2**30, None, True),
                ("r-failed", 8.0, 16 * 2**30, 8.0, 16 * 2**30, "failed", True),
                ("r-update", 8.0, 0, 16.0, 16 * 2**30, None, True)], got
            if step == 0:
                run("0010", "--downgrade")
                assert c.execute("SELECT to_regclass('capacity_reservations')").fetchone() == (None,)


# ---- Medium 2 of reviewer 1: a merge_failed retry cannot keep capacity from anyone

def test_a_merge_failed_request_holds_nothing_the_ledger_does_not_already_count(world):
    """merge_failed is reached only from applied: the quota is on the cluster, confirmed by a read (docs/01). However often
    it is retried, its hold adds nothing to the check, because the ledger already counts the quota. Guard: true on head."""
    client, ctx, *_ = world
    committed(ctx, 96)
    rid = create(world, "payments-a").json()["requestId"]
    land(ctx, own_quota(ctx, rid))
    with ctx.db.session() as s:
        repo = RequestRepo(s)
        for event in (E.PR_OPENED, E.APPLIED, E.MERGE_FAILED, E.RETRY, E.RETRY, E.RETRY):
            repo.move(repo.get(rid), event, "worker", "test")
    cap = ctx.pipeline.capacity.check("CRC", "dev", 0, 0)
    assert (cap.detail["cpu"], cap.detail["reserved"]) == (0.812, {"cpu": 0.0, "memory": 0})
