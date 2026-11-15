"""git_sweep: the Git layer's cleanup, every GIT_SWEEP_EVERY seconds (#286). The worker runs one job at a time, so while this
runs no other Git job of this process does; the workspace's own lock also refuses to sweep under a running Git operation.
It prunes worktrees, removes the folder and local branch of every request that is not in flight (approved or pr_open), and
runs git gc --auto. Each pass is one logged and counted cleanup event (core/git/oplog.py)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import ChangeRequestRow, JobRow
from cmapi.core.db.repo import JobRepo
from cmapi.core.lifecycle import State as S

GIT_SWEEP_EVERY = 600
IN_FLIGHT = (S.APPROVED.value, S.PR_OPEN.value)


def git_sweep(ctx: AppContext, s: Session, job: JobRow) -> None:
    jobs = JobRepo(s)
    rows = s.execute(select(ChangeRequestRow.cluster_id, ChangeRequestRow.request_id)
                     .where(ChangeRequestRow.status.in_(IN_FLIGHT))).all()
    ctx.git.sweep({(c, r) for c, r in rows})
    jobs.done(job)
    jobs.enqueue("git_sweep", delay=GIT_SWEEP_EVERY, payload={"every": GIT_SWEEP_EVERY})
