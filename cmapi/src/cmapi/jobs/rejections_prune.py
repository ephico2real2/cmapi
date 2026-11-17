"""rejections_prune: daily. Deletes the stored refusals last seen more than policy.rejections.retentionDays ago (#302).

A stored refusal holds a username: it is kept as long as the Policies tab can show it, and no longer (90 days by default,
one key per instance in instance.yaml)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo
from cmapi.core.observability import log
from cmapi.core.rejections import RejectionRepo

REJECTIONS_PRUNE_EVERY = 86_400


def rejections_prune(ctx: AppContext, s: Session, job: JobRow) -> None:
    days = ctx.cfg.policy.rejection_retention_days
    removed = RejectionRepo(s).prune(days)
    log.info("rejections_pruned", removed=removed, retention_days=days)
    jobs = JobRepo(s)
    jobs.done(job)
    jobs.enqueue("rejections_prune", delay=REJECTIONS_PRUNE_EVERY, payload={"every": REJECTIONS_PRUNE_EVERY})
