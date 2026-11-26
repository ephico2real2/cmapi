"""usage_sweep: daily. Judges every managed namespace of each connected cluster from its last 14 days in Thanos, and stores
the day's verdicts (#310; capacity/sweep.py; docs/03, "Running the sweep").

With capacity.yaml `usage.source: none` it reads nothing and writes nothing: GET /api/v1/quotas then says, on each row, that
no usage source is configured. docs/03 runs the sweep "off-peak in each cluster's region"; this job runs every 24 hours from
the worker's first start, one cluster at a time."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cmapi.capacity.sweep import run_sweep
from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo
from cmapi.core.observability import log

USAGE_SWEEP_EVERY = 86_400


def usage_sweep(ctx: AppContext, s: Session, job: JobRow) -> None:
    if ctx.usage.configured:
        served = [st for st in ctx.registry.connected() if st.environment in ctx.cfg.allowed_environments]
        for sweep in run_sweep(served, ctx.usage, ctx.analysis, s):
            log.info("usage_sweep", cluster_id=sweep.cluster_id, status=sweep.status, namespaces=len(sweep.verdicts),
                     detail=sweep.detail)
    jobs = JobRepo(s)
    jobs.done(job)
    jobs.enqueue("usage_sweep", delay=USAGE_SWEEP_EVERY, payload={"every": USAGE_SWEEP_EVERY})
