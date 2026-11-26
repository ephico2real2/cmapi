"""#263 and #321: the daily expire_check, run by the worker on a real PostgreSQL with the fake Git host and cluster.

docs/01, Namespace expiration: notices to the team DL at 14, 7 and 1 days; grace from the date for graceDays; after grace,
"cmapi opens a delete request approved by the expired-namespace policy" (or by people, when a guard of the policy stops it),
the bot PR removes the folder and Argo CD waits for an operator's prune confirmation. Never a direct delete; never in prod.
#321: every day is the UTC day, whatever the host's zone.

Each test fails before the fix (no expire_check job; the local-date clock) and passes after it.
"""
from __future__ import annotations

import importlib
import os
import threading
import time
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from cmapi.core.db.models import ChangeRequestRow, ExpirationNoticeRow, JobRow
from cmapi.core.db.repo import JobRepo, utcnow
from test_expirations import created_namespace, put
from test_flow import AMY, OLA, OPAL, auth, run_jobs

NAME = "payments-dev"
DL = "payments-team@ephico2real.com"


def utc_date() -> date:
    return datetime.now(timezone.utc).date()


class FakeNotifier:
    """The Notifier port: records each message; `fail` makes the next sends raise, as an SMTP outage does."""

    def __init__(self):
        self.sent: list[tuple[list[str], str]] = []
        self.fail = False

    def send(self, to, subject, body, links=None):
        if self.fail:
            raise OSError("smtp down")
        self.sent.append((list(to), subject))


_MAIL: list[FakeNotifier] = []


@pytest.fixture
def mail():
    """SMTP is on: run_check puts this notifier in the job (imported there, so a test without the job fails, not errors)."""
    _MAIL.append(FakeNotifier())
    yield _MAIL[0]
    _MAIL.clear()


def run_check(ctx, monkeypatch, day: date, worker: str = "w1") -> list[str]:
    """The day comes: the pending expire_check is due now, and a worker drains the queue, as after a restart."""
    job_mod = importlib.import_module("cmapi.jobs.expire_check")
    from cmapi.worker import Worker
    monkeypatch.setattr(job_mod, "utc_today", lambda: day)
    if _MAIL:
        monkeypatch.setattr(job_mod, "notifier_for", lambda ctx: _MAIL[0])
    with ctx.db.session() as s:
        jobs = JobRepo(s)
        pending = jobs.pending("expire_check")
        if pending is None:
            jobs.enqueue("expire_check", payload={"every": 86_400})
        else:
            pending.run_after, pending.locked_until = utcnow(), None
    ran = []
    w = Worker(ctx, worker, poll_seconds=0)
    for _ in range(30):
        with ctx.db.session() as s:
            due = s.scalar(select(JobRow.kind).where(JobRow.done_at.is_(None), JobRow.run_after <= utcnow()).limit(1))
        if due is None or not w.run_one():
            break
        ran.append(due)
    assert "expire_check" in ran, ran
    return ran


def notices(ctx, name: str = NAME) -> list[tuple[str, int, bool]]:
    with ctx.db.session() as s:
        return [(r.expires_at, r.threshold_days, r.ok) for r in s.scalars(
            select(ExpirationNoticeRow).where(ExpirationNoticeRow.namespace == name).order_by(ExpirationNoticeRow.id))]


def expiry_deletes(ctx, name: str = NAME) -> list[ChangeRequestRow]:
    with ctx.db.session() as s:
        return list(s.scalars(select(ChangeRequestRow).where(ChangeRequestRow.namespace == name, ChangeRequestRow.reason == "expired")))


def dated(kube, ctx, expires: date, name: str = NAME, **kw) -> None:
    put(kube, name, expires=expires.isoformat(), **kw)
    obj = kube.objects[("Namespace", "", name)]
    obj["metadata"]["annotations"]["cmapi.net/team-dl"] = DL
    ctx.registry.cache("CRC")._list("Namespace")


# ---- notices: 14, 7 and 1 days, each once, by email to the team DL, across restarts
def test_notices_at_14_7_and_1_days_once_each_across_restarts(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    d = date(2027, 3, 20)
    dated(kube, ctx, d)
    for n, worker in [(20, "w1"), (14, "w1"), (14, "w2"), (10, "w3"), (7, "w1"), (7, "w2"), (3, "w1"), (1, "w2"), (1, "w3")]:
        run_check(ctx, monkeypatch, d - timedelta(days=n), worker)
    assert [t for _, t, _ in notices(ctx)] == [14, 7, 1], notices(ctx)
    assert {at for at, _, _ in notices(ctx)} == {d.isoformat()} and all(ok for *_, ok in notices(ctx))
    assert [to for to, _ in mail.sent] == [[DL]] * 3, mail.sent
    assert "expires on 2027-03-20, in 7 days" in mail.sent[1][1]
    assert expiry_deletes(ctx) == []


def test_a_short_expiry_gets_the_one_day_notice_and_a_missed_run_never_sends_a_stale_one(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    d = date(2027, 3, 20)
    dated(kube, ctx, d)
    run_check(ctx, monkeypatch, d - timedelta(days=5))          # no run at 14: the 7-day notice, the nearest, goes once
    run_check(ctx, monkeypatch, d - timedelta(days=1))
    assert [t for _, t, _ in notices(ctx)] == [7, 1]


def test_a_failed_email_is_not_counted_and_is_sent_on_the_next_run(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    d = date(2027, 3, 20)
    dated(kube, ctx, d)
    mail.fail = True
    run_check(ctx, monkeypatch, d - timedelta(days=7))
    assert notices(ctx) == [(d.isoformat(), 7, False)]
    with ctx.db.session() as s:                                   # the next run comes soon, not in a day
        nxt = JobRepo(s).pending("expire_check")
        assert nxt.run_after - utcnow() < timedelta(hours=1)
    mail.fail = False
    run_check(ctx, monkeypatch, d - timedelta(days=7))
    assert notices(ctx) == [(d.isoformat(), 7, False), (d.isoformat(), 7, True)] and len(mail.sent) == 1


def test_without_smtp_the_notice_is_recorded_for_the_expiration_tab_and_counted(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    import cmapi.plugins.expiration.router as expiration_mod
    d = date(2027, 3, 20)
    dated(kube, ctx, d)
    run_check(ctx, monkeypatch, d - timedelta(days=14))
    run_check(ctx, monkeypatch, d - timedelta(days=7))
    with ctx.db.session() as s:
        details = [r.detail for r in s.scalars(select(ExpirationNoticeRow))]
    assert all(x.startswith("portal: the Expiration tab; no email (no SMTP host") for x in details), details
    monkeypatch.setattr(expiration_mod, "today", lambda: d - timedelta(days=7))
    row = next(i for i in client.get("/api/v1/expirations", headers=auth(keys, "ola", **OLA)).json()["items"] if i["name"] == NAME)
    assert row["noticesSent"] == 2 and row["state"] == "expiring"


# ---- grace: from the date for 7 days; recorded once; nothing opened, nothing deleted
def test_grace_runs_from_the_date_for_seven_days_and_opens_nothing(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    d = date(2027, 3, 20)
    dated(kube, ctx, d)
    for n in (14, 7, 1):
        run_check(ctx, monkeypatch, d - timedelta(days=n))
    for n in range(0, 7):                                       # the date and the 6 days after it
        run_check(ctx, monkeypatch, d + timedelta(days=n))
    assert [t for _, t, _ in notices(ctx)] == [14, 7, 1, 0], "one grace row, on the date"
    assert expiry_deletes(ctx) == [] and kube.get_object("Namespace", None, NAME) is not None
    with ctx.db.session() as s:
        assert s.scalar(select(ExpirationNoticeRow.detail).where(ExpirationNoticeRow.threshold_days == 0)) == "grace ends on 2027-03-27"


def test_a_run_missed_on_the_date_still_records_the_grace(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    d = date(2027, 3, 20)
    dated(kube, ctx, d)
    run_check(ctx, monkeypatch, d + timedelta(days=2))
    assert [t for _, t, _ in notices(ctx)] == [0]


# ---- after grace: the normal delete request, never a direct delete
def _expiring_namespace(world, monkeypatch) -> date:
    """A namespace created through the API with an expiry 20 days out (Git and the cluster hold the date); 2 notices sent."""
    client, ctx, git, kube, validator, keys = world
    d = utc_date() + timedelta(days=20)
    created_namespace(client, ctx, keys, expiresAt=d.isoformat())
    assert kube.get_object("Namespace", None, NAME)["metadata"]["annotations"]["cmapi.net/expires-at"] == d.isoformat()
    run_check(ctx, monkeypatch, d - timedelta(days=14))
    run_check(ctx, monkeypatch, d - timedelta(days=7))
    return d


def test_after_grace_a_delete_request_waits_for_people_and_then_for_the_prune(world, monkeypatch, mail):
    """With auto-approval paused the expired-namespace policy cannot approve, so dev's delete rule asks one approver."""
    client, ctx, git, kube, validator, keys = world
    d = _expiring_namespace(world, monkeypatch)
    admin = dict(roles=["cmapi-admin"], groups=["/cmapi/app-cmapi-rbac-admin"])
    assert client.post("/api/v1/admin/auto-approval:pause", json={"reason": "test"}, headers=auth(keys, "root", **admin)).status_code == 200
    run_check(ctx, monkeypatch, d + timedelta(days=6))           # the last day of grace: nothing yet
    assert expiry_deletes(ctx) == []
    run_check(ctx, monkeypatch, d + timedelta(days=7))           # grace is over
    [row] = expiry_deletes(ctx)
    assert row.status == "pending_approval" and row.action == "delete" and row.plugin == "namespaces"
    assert row.requester_username == "cmapi-expire-check" and row.requester_kind == "service"
    assert [s["group"] for s in row.requirement["slots"]] == ["approver-platform"], row.requirement
    assert f"clusters/CRC/namespaces/{NAME}/namespace.yaml" in row.plan["files"] and row.reason == "expired"
    assert f"clusters/CRC/namespaces/{NAME}/namespace.yaml" in git.branches["main"], "nothing leaves Git before approval"
    assert kube.get_object("Namespace", None, NAME) is not None
    assert (d.isoformat(), -1, True) in notices(ctx)
    run_check(ctx, monkeypatch, d + timedelta(days=8))           # the request holds the namespace: no second delete
    assert len(expiry_deletes(ctx)) == 1
    h = auth(keys, "ola", **OLA)
    assert client.post(f"/api/v1/requests/{row.request_id}:approve", json={}, headers=auth(keys, "amy", **AMY)).json()["status"] == "approved"
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{row.request_id}", headers=h).json()
    assert view["status"] == "awaiting_prune", view["events"]
    assert kube.get_object("Namespace", None, NAME) is not None, "Argo CD waits for an operator: the namespace stays"
    assert client.post("/api/v1/admin/prune:confirm", json={"namespace": NAME}, headers=auth(keys, "opal", **OPAL)).status_code == 200
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{row.request_id}", headers=h).json()["status"] == "synced"
    assert kube.get_object("Namespace", None, NAME) is None


def test_the_expired_namespace_policy_approves_and_the_prune_still_waits_for_an_operator(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    d = _expiring_namespace(world, monkeypatch)
    run_check(ctx, monkeypatch, d + timedelta(days=7))
    [row] = expiry_deletes(ctx)
    assert row.requirement["auto"] == "auto:expired-namespace", row.requirement
    view = client.get(f"/api/v1/requests/{row.request_id}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "awaiting_prune", [(e["event"], e["note"]) for e in view["events"]]
    assert kube.get_object("Namespace", None, NAME) is not None, "no timer removes a namespace: the prune waits"


def test_a_guard_holds_the_delete_and_opens_nothing(world, monkeypatch):
    """One notice only (noticesSentAtLeast2): held, listed in the log, tried the next day."""
    client, ctx, git, kube, validator, keys = world
    d = utc_date() + timedelta(days=20)
    created_namespace(client, ctx, keys, expiresAt=d.isoformat())
    run_check(ctx, monkeypatch, d - timedelta(days=1))
    run_check(ctx, monkeypatch, d + timedelta(days=7))
    assert expiry_deletes(ctx) == [] and kube.get_object("Namespace", None, NAME) is not None
    run_check(ctx, monkeypatch, d - timedelta(days=7))           # a run that sends the 7-day notice: two notices now
    run_check(ctx, monkeypatch, d + timedelta(days=8))
    assert [r.status for r in expiry_deletes(ctx)] == ["awaiting_prune"]


def test_a_date_that_moved_in_git_holds_the_delete(world, monkeypatch, mail):
    """The cluster still shows an old date that Git no longer holds: the delete is planned against Git and held (412)."""
    client, ctx, git, kube, validator, keys = world
    d = _expiring_namespace(world, monkeypatch)
    old = d - timedelta(days=20)
    kube.objects[("Namespace", "", NAME)]["metadata"]["annotations"]["cmapi.net/expires-at"] = old.isoformat()
    ctx.registry.cache("CRC")._list("Namespace")
    for n in (-14, -7, 7):
        run_check(ctx, monkeypatch, old + timedelta(days=n))
    assert expiry_deletes(ctx) == [] and kube.get_object("Namespace", None, NAME) is not None


# ---- prod never expires
def test_prod_never_expires(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    st = ctx.registry.clusters["CRC"]
    monkeypatch.setattr(st, "policy", replace(st.policy, environment="prod"))
    monkeypatch.setattr(ctx.cfg, "allowed_environments", {*ctx.cfg.allowed_environments, "prod"})
    assert not ctx.cfg.expiration.allows("prod")
    d = date(2027, 3, 20)
    dated(kube, ctx, d, env="prod")                              # a hand-edited date on a prod namespace
    for n in (-14, -7, -1, 0, 7, 30):
        run_check(ctx, monkeypatch, d + timedelta(days=n))
    assert notices(ctx) == [] and expiry_deletes(ctx) == [] and mail.sent == []


# ---- #321: the UTC day, whatever the host's zone
@pytest.fixture
def zone_off_utc():
    """A zone whose local date is not the UTC date right now: UTC+14 after 12:00 UTC, UTC-12 before (POSIX signs invert)."""
    old = os.environ.get("TZ")
    zone = "Etc/GMT-14" if datetime.now(timezone.utc).hour >= 12 else "Etc/GMT+12"
    os.environ["TZ"] = zone
    time.tzset()
    try:
        assert date.today() != utc_date(), (zone, date.today(), utc_date())
        yield zone
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_the_list_the_planner_and_the_check_count_utc_days(world, monkeypatch, mail, zone_off_utc):
    client, ctx, git, kube, validator, keys = world
    from test_expirations import write
    today = utc_date()
    h = auth(keys, "ola", **OLA)
    assert client.get("/api/v1/expirations", headers=h).json()["today"] == today.isoformat()
    etag = created_namespace(client, ctx, keys)                  # permanent
    for until in (today + timedelta(days=1), today + timedelta(days=30)):   # the two edges of :set, counted from the UTC day
        r = write(client, keys, "set", {"until": until.isoformat(), "justification": "edge"}, etag, dry=True)
        assert r.status_code == 200, (zone_off_utc, until, r.text)
    job_mod = importlib.import_module("cmapi.jobs.expire_check")
    from cmapi.worker import Worker
    dated(kube, ctx, today + timedelta(days=7), name="sprint-dev")
    with ctx.db.session() as s:
        JobRepo(s).enqueue("expire_check", payload={"every": 86_400})
    while Worker(ctx, "w1", poll_seconds=0).run_one():
        pass
    assert job_mod.utc_today() == today
    assert [t for _, t, _ in notices(ctx, "sprint-dev")] == [7], "7 UTC days left: the 7-day notice"


def test_a_creation_timestamp_is_read_as_its_utc_date():
    from cmapi.plugins.expiration.rules import utc_day
    assert utc_day("2026-11-17T01:00:00Z") == date(2026, 11, 17)
    assert utc_day("2026-11-17T01:00:00+05:00") == date(2026, 11, 16)
    assert utc_day("2026-11-17T23:30:00-02:00") == date(2026, 11, 18)
    assert utc_day("not a time") is None and utc_day(None) is None


# ---- several workers
def test_two_workers_at_once_give_one_result(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    job_mod = importlib.import_module("cmapi.jobs.expire_check")
    from cmapi.worker import Worker
    d = _expiring_namespace(world, monkeypatch)
    dated(kube, ctx, d + timedelta(days=8), name="other-dev")    # on the run's day, 1 day left: its 1-day notice
    day = d + timedelta(days=7)
    monkeypatch.setattr(job_mod, "utc_today", lambda: day)
    sent_before = len(mail.sent)
    with ctx.db.session() as s:
        pending = JobRepo(s).pending("expire_check")
        pending.run_after, pending.locked_until = utcnow(), None
    gate = threading.Barrier(2)
    ran: dict[str, bool] = {}

    def go(worker_id: str) -> None:
        w = Worker(ctx, worker_id, poll_seconds=0)
        gate.wait()
        ran[worker_id] = w.run_one()

    threads = [threading.Thread(target=go, args=(f"w{i}",)) for i in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert len(expiry_deletes(ctx)) == 1
    assert [t for _, t, _ in notices(ctx, "other-dev")] == [1] and len(mail.sent) == sent_before + 1
    # Two runs of the check itself at once, outside the queue: still one notice and one delete.
    dated(kube, ctx, day + timedelta(days=7), name="third-dev")
    errors: list[BaseException] = []

    def check_once() -> None:
        try:
            gate.wait()
            job_mod.check(ctx, day)
        except BaseException as exc:                              # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=check_once) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert [t for _, t, _ in notices(ctx, "third-dev")] == [7] and len(expiry_deletes(ctx)) == 1


# ---- PR #699 review (reviewer 2): each fails on 9539685 and passes with the fix
ADMIN = dict(roles=["cmapi-admin"], groups=["/cmapi/app-cmapi-rbac-admin"])


def _pause_auto_approval(client, keys) -> None:
    assert client.post("/api/v1/admin/auto-approval:pause", json={"reason": "test"},
                       headers=auth(keys, "root", **ADMIN)).status_code == 200


def test_a_live_namespace_without_prune_confirm_holds_the_expiry_delete(world, monkeypatch, mail):
    """Argo CD reads Prune=confirm from the live object when it prunes (gitops-engine sync_context.go, task.liveObj). Without
    it, the auto-approved expiry delete would be pruned at merge with no operator: removed by a timer alone."""
    client, ctx, git, kube, validator, keys = world
    d = _expiring_namespace(world, monkeypatch)
    annotations = kube.objects[("Namespace", "", NAME)]["metadata"]["annotations"]
    kept = annotations.pop("argocd.argoproj.io/sync-options")
    assert "Prune=confirm" in kept
    ctx.registry.cache("CRC")._list("Namespace")
    run_check(ctx, monkeypatch, d + timedelta(days=7))
    assert expiry_deletes(ctx) == []
    annotations["argocd.argoproj.io/sync-options"] = kept           # the drift is repaired: the next run opens it
    ctx.registry.cache("CRC")._list("Namespace")
    run_check(ctx, monkeypatch, d + timedelta(days=8))
    assert [(r.status, r.requirement["auto"]) for r in expiry_deletes(ctx)] == [("awaiting_prune", "auto:expired-namespace")]


def test_an_extension_asked_before_utc_midnight_holds_the_delete_for_24_hours(world, monkeypatch, mail):
    """docs/01: "no extension in the last 24 hours". An extension asked at 23:30 UTC and cancelled: at 00:30 the reference
    check (whole days) passes it, and head opened a delete for people to approve."""
    from test_expirations import write
    client, ctx, git, kube, validator, keys = world
    d = _expiring_namespace(world, monkeypatch)
    etag = client.get(f"/api/v1/clusters/CRC/namespaces/{NAME}", headers=auth(keys, "ola", **OLA)).json()["etag"]
    r = write(client, keys, "extend", {"days": 1, "justification": "keep"}, etag)
    assert r.status_code == 202, r.text
    rid = r.json()["requestId"]
    assert client.post(f"/api/v1/requests/{rid}:cancel", json={}, headers=auth(keys, "ola", **OLA)).status_code == 200
    run_day = d + timedelta(days=7)
    now = datetime.combine(run_day, datetime.min.time(), timezone.utc) + timedelta(minutes=30)
    with ctx.db.session() as s:
        s.get(ChangeRequestRow, rid).created_at = now - timedelta(hours=1)
    job_mod = importlib.import_module("cmapi.jobs.expire_check")
    monkeypatch.setattr(job_mod, "utcnow", lambda: now)
    run_check(ctx, monkeypatch, run_day)
    assert expiry_deletes(ctx) == []
    monkeypatch.setattr(job_mod, "utcnow", lambda: now + timedelta(hours=24))
    run_check(ctx, monkeypatch, run_day + timedelta(days=1))
    assert len(expiry_deletes(ctx)) == 1


def test_a_rejected_expiry_delete_is_not_opened_again_for_its_date(world, monkeypatch, mail):
    client, ctx, git, kube, validator, keys = world
    d = _expiring_namespace(world, monkeypatch)
    _pause_auto_approval(client, keys)
    run_check(ctx, monkeypatch, d + timedelta(days=7))
    [row] = expiry_deletes(ctx)
    r = client.post(f"/api/v1/requests/{row.request_id}:reject", json={"comment": "keep it"}, headers=auth(keys, "amy", **AMY))
    assert r.json()["status"] == "rejected"
    for n in (8, 9):
        run_check(ctx, monkeypatch, d + timedelta(days=n), f"w{n}")
    assert [r.request_id for r in expiry_deletes(ctx)] == [row.request_id]
    assert [t for _, t, _ in notices(ctx)].count(-1) == 1


@pytest.mark.parametrize("username,sub", [("service-account-cmapi-expire-check", None), ("cmapi-expire-check", None),
                                          ("CMAPI-Expire-Check", None), ("someone", "cmapi-expire-check")])
def test_no_token_can_be_the_expiry_worker(world, monkeypatch, mail, username, sub):
    """Head let a client or person of that name cancel the worker's delete as its requester (routers/requests.py compares
    usernames), recorded in the audit trail under the worker's name."""
    client, ctx, git, kube, validator, keys = world
    d = _expiring_namespace(world, monkeypatch)
    _pause_auto_approval(client, keys)
    run_check(ctx, monkeypatch, d + timedelta(days=7))
    [row] = expiry_deletes(ctx)
    look_alike = auth(keys, username, sub=sub, roles=["cmapi-onboarding"], employee_id=None, client="cmapi-expire-check")
    r = client.post(f"/api/v1/requests/{row.request_id}:cancel", json={}, headers=look_alike)
    assert r.status_code == 401, r.text
    assert expiry_deletes(ctx)[0].status == "pending_approval"


def test_a_notice_is_delivered_at_least_once(world, monkeypatch):
    """The documented guarantee: a worker lost after the relay accepted the message sends it again, and it is recorded once."""
    client, ctx, git, kube, validator, keys = world
    job_mod = importlib.import_module("cmapi.jobs.expire_check")
    d = date(2027, 3, 20)
    dated(kube, ctx, d)

    class WorkerLost(BaseException):
        pass

    accepted: list[str] = []

    class Relay:
        lose = True

        def send(self, to, subject, body, links=None):
            accepted.append(subject)
            if Relay.lose:
                Relay.lose = False
                raise WorkerLost()

    monkeypatch.setattr(job_mod, "notifier_for", lambda ctx: Relay())
    with pytest.raises(WorkerLost):
        job_mod.check(ctx, d - timedelta(days=7))
    assert job_mod.check(ctx, d - timedelta(days=7))
    assert len(accepted) == 2 and notices(ctx) == [(d.isoformat(), 7, True)]


def test_a_lease_taken_over_stops_the_run_at_once(world, monkeypatch, mail):
    """LeaseLost is not one namespace's error: the run stops, and the counter of errors is not raised for each namespace."""
    _, ctx, _, kube, _, _ = world
    from cmapi.core.db.repo import LeaseLost
    from cmapi.core.observability import EXPIRY_ACTIONS
    job_mod = importlib.import_module("cmapi.jobs.expire_check")
    d = date(2027, 3, 20)
    for name in ("first-dev", "second-dev"):
        dated(kube, ctx, d, name=name)
    with ctx.db.session() as s:
        repo = JobRepo(s)
        repo.enqueue("expire_check")
        row = repo.claim("old")
        lease = (row.job_id, "old", row.lease_generation)
    original = job_mod._notice

    def notice(*args):
        result = original(*args)
        with ctx.db.session() as s:                              # another worker claims the job after the first notice
            s.get(JobRow, lease[0]).locked_until = utcnow() - timedelta(seconds=1)
        with ctx.db.session() as s:
            assert JobRepo(s).claim("new").job_id == lease[0]
        return result

    errors = EXPIRY_ACTIONS.labels("error", "dev")._value.get()
    monkeypatch.setattr(job_mod, "notifier_for", lambda ctx: mail)
    monkeypatch.setattr(job_mod, "_notice", notice)
    with pytest.raises(LeaseLost):
        job_mod.check(ctx, d - timedelta(days=7), lease=lease)
    assert len(mail.sent) == 1 and EXPIRY_ACTIONS.labels("error", "dev")._value.get() == errors
