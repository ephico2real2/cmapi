"""Request events record insertion time, including an apply job's older transaction (#551)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.db.repo import RequestRepo
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.jobs.delivery import mark_apply_started


@pytest.fixture
def request_id(fresh_db):
    rid = "req-20261121-0001"
    with fresh_db.session() as s:
        s.add(ChangeRequestRow(request_id=rid, instance="test", cluster_id="CRC", namespace="events-dev",
                               env="dev", plugin="namespace", action="create", status=S.PR_OPEN.value,
                               plan={}, plan_hash="a" * 64, requester={}, requester_sub="test",
                               requester_kind="user", requester_client="test", requester_username="test"))
    return rid


def test_event_time_advances_within_one_transaction(fresh_db, request_id):
    with fresh_db.session() as s:
        repo = RequestRepo(s)
        row = repo.get(request_id)
        repo.event(row, "apply_started", "cmapi-deliverer")
        s.flush()  # Insert now, rather than buffering both events until the commit.
        s.execute(text("SELECT pg_sleep(0.02)"))
        repo.move(row, E.APPLIED, "cmapi-deliverer")

    with fresh_db.session() as s:
        events = RequestRepo(s).events(request_id)  # id order, as returned by the API
        assert [e.event for e in events] == ["apply_started", "applied"]
        assert all(a.at <= b.at for a, b in zip(events, events[1:]))
        # Non-decreasing alone also accepts now(): both rows get the transaction's start time.
        assert events[0].at < events[1].at


def test_apply_event_time_does_not_precede_its_separately_committed_start(fresh_db, request_id):
    with fresh_db.session() as s:
        repo = RequestRepo(s)
        row = repo.get(request_id)  # Start the job's transaction before mark_apply_started's transaction.
        s.execute(text("SELECT pg_sleep(0.02)"))
        assert mark_apply_started(SimpleNamespace(db=fresh_db), request_id, "a" * 40)
        s.execute(text("SELECT pg_sleep(0.02)"))
        repo.move(row, E.APPLIED, "cmapi-deliverer")

    with fresh_db.session() as s:
        events = RequestRepo(s).events(request_id)
        assert [e.event for e in events] == ["apply_started", "applied"]
        assert all(a.at <= b.at for a, b in zip(events, events[1:])), [(e.id, e.event, e.at) for e in events]
        assert [e.id for e in sorted(events, key=lambda e: (e.at, e.id))] == [e.id for e in events]
