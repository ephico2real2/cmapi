"""approval_timeout: hourly. A request pending past its rule's timeoutHours becomes timeout."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.lifecycle import Event as E, State as S

APPROVAL_TIMEOUT_EVERY = 3600


def approval_timeout(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    now = datetime.now(timezone.utc)
    for row in repo.in_states([S.PENDING_APPROVAL.value]):
        hours = (row.requirement or {}).get("timeoutHours", 24)
        if now - row.created_at > timedelta(hours=hours):
            repo.move(row, E.APPROVAL_TIMEOUT, "worker", f"no decision within {hours} h")
            jobs.enqueue("channel_notify", request_id=row.request_id, cluster_id=row.cluster_id, payload={"kind": "timeout"})
    jobs.done(job)
    jobs.enqueue("approval_timeout", delay=APPROVAL_TIMEOUT_EVERY, payload={"every": APPROVAL_TIMEOUT_EVERY})
