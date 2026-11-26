"""capacity_snapshot: every capacity.snapshotInterval, one snapshot of each connected cluster this instance serves (#21;
capacity/snapshots.py; docs/02, "Stored capacity").

The recurring job re-enqueues itself at the next interval boundary, so the snapshots of every cluster line up on the
boundaries (docs/02, "Snapshot times are floored to the interval boundary"). POST /api/v1/clusters/{clusterId}/capacity/
snapshots:run enqueues a one-off job of the same kind for one cluster (payload `clusterId`), which writes that cluster's current
interval again and does not re-enqueue. The committed quota comes from the worker's own watch of the cluster's ResourceQuotas
(the ledger, core/capacity_ledger.py), never from Thanos. Rows past 13 months are deleted on each recurring run."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from cmapi.capacity.snapshots import SnapshotRepo, floor_to_interval, take
from cmapi.core.capacity_backend import read_snapshot_quotas
from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo
from cmapi.core.observability import log

CAPACITY_SNAPSHOT_EVERY = 1800           # the default interval; the job re-enqueues itself with capacity.yaml's


def capacity_snapshot(ctx: AppContext, s: Session, job: JobRow) -> None:
    payload = dict(job.payload or {})
    only = payload.get("clusterId")
    interval = ctx.capacity.snapshot_seconds
    now = datetime.now(timezone.utc)
    at = floor_to_interval(now, interval)
    metrics = getattr(ctx.usage, "sweep_metrics", None) if ctx.usage.configured else None
    repo = SnapshotRepo(s)
    for st in ctx.registry.connected():
        if st.environment not in ctx.cfg.allowed_environments or (only and st.cluster_id != only):
            continue
        read = read_snapshot_quotas(st)
        rows = take(st, metrics, interval, ctx.capacity.count_taints, at, read.totals.committed if read.totals else None)
        repo.put(rows)
        log.info("capacity_snapshot", cluster_id=st.cluster_id, taken_at=at.isoformat(), rows=len(rows),
                 source=rows[0]["source"], complete=rows[0]["complete"], detail=rows[0]["detail"])
    jobs = JobRepo(s)
    jobs.done(job)
    if only is None:
        repo.prune(now)
        nxt = (at.timestamp() + interval) - now.timestamp()
        jobs.enqueue("capacity_snapshot", delay=max(nxt, 1), payload={"every": interval})
