"""The worker (docs/02, worker.py): claims jobs from the jobs table with SKIP LOCKED and a lease,
runs them, and re-enqueues the recurring ones.

- A job that raises is retried with backoff (5, 15, 45, 135, 405 s); after five attempts a
  request-bound job marks its request failed and the job is done.
- Idempotent by construction: open_pr finds an existing branch or PR, pr_checks reads the PR
  state first, watch_sync is a pure read. A lease that expires because a worker died makes
  the job claimable again.
- cmapi_worker_last_loop_timestamp_seconds is the heartbeat the CmapiWorkerNotLooping alert
  watches: a Running pod with a dead loop would otherwise look healthy.
- SIGTERM: the loop finishes the current job and exits.
- A heartbeat renews the lease while a job runs, so only a dead worker's job is claimed again.
"""
from __future__ import annotations

import os
import signal
import socket
import threading
import time
import traceback
from datetime import timedelta
from typing import Any, Callable

from prometheus_client import Gauge
from sqlalchemy import update

from cmapi.core.context import AppContext, build_context
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, LeaseLost, RequestRepo, oldest_open_ages, utcnow
from cmapi.core.kpi import register_collectors
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import JOB_FAILURES, JOBS_PENDING, OPEN_REQUEST_AGE, configure_logging, log, start_metrics
from cmapi.jobs import HANDLERS, RECURRING
from cmapi.settings import Settings, settings

LAST_LOOP = Gauge("cmapi_worker_last_loop_timestamp_seconds", "When the worker loop last ran")
BACKOFF = (5, 15, 45, 135, 405)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 300


class Worker:
    def __init__(self, ctx: AppContext, worker_id: str, poll_seconds: float = 2.0):
        self.ctx, self.worker_id, self.poll = ctx, worker_id, poll_seconds
        self._stop = threading.Event()

    def stop(self, *_: Any) -> None:
        log.info("worker_stopping", worker=self.worker_id)
        self._stop.set()

    def ensure_recurring(self) -> None:
        with self.ctx.db.session() as s:
            jobs = JobRepo(s)
            for kind, every in RECURRING.items():
                if jobs.pending(kind) is None:
                    jobs.enqueue(kind, delay=0, payload={"every": every})

    def gauges(self) -> None:
        with self.ctx.db.session() as s:
            counts = JobRepo(s).pending_counts()
            OPEN_REQUEST_AGE.clear()      # a state with no open request must leave the gauge, or its alert never clears
            for kind in set(HANDLERS) | set(counts):
                JOBS_PENDING.labels(kind).set(counts.get(kind, 0))
            for status, env, age in oldest_open_ages(s):
                OPEN_REQUEST_AGE.labels(status, env).set(age)

    def _heartbeat(self, job_id: int, finished: threading.Event) -> None:
        while not finished.wait(LEASE_SECONDS / 3):
            try:
                with self.ctx.db.session() as s:
                    s.execute(update(JobRow).where(JobRow.job_id == job_id, JobRow.locked_by == self.worker_id,
                                                   JobRow.done_at.is_(None), JobRow.locked_until.is_not(None))
                              .values(locked_until=utcnow() + timedelta(seconds=LEASE_SECONDS)))
            except Exception as exc:                                  # noqa: BLE001 - the job's own commit reports a dead database
                log.warning("lease_renewal_failed", job=job_id, error=str(exc)[:200])

    def run_one(self) -> bool:
        """Claim and run one job; True when one was run."""
        with self.ctx.db.session() as s:
            job = JobRepo(s).claim(self.worker_id, LEASE_SECONDS)
            if job is None:
                return False
            job_id, kind, request_id, payload, attempts = job.job_id, job.kind, job.request_id, dict(job.payload or {}), job.attempts
            generation = job.lease_generation
        handler: Callable[..., Any] | None = HANDLERS.get(kind)
        log.info("job_start", job=job_id, kind=kind, request_id=request_id, attempt=attempts, worker=self.worker_id)
        finished = threading.Event()
        threading.Thread(target=self._heartbeat, args=(job_id, finished), name=f"lease-{job_id}", daemon=True).start()
        try:
            if handler is None:
                raise RuntimeError(f"no handler for job kind {kind}")
            with self.ctx.db.session() as s:
                job = s.get(type(job), job_id)
                handler(self.ctx, s, job)
                # Every handler ends with jobs.done() or jobs.retry(); claim() set the lease, retry() cleared
                # it, so a lease still held after the handler means the job finished without saying so.
                if job.done_at is None and job.locked_until is not None:
                    JobRepo(s).done(job)
                # The fencing token: if the lease expired while this ran and another worker claimed the job, this
                # transaction (the request's events and state included) is rolled back, not committed on top.
                JobRepo(s).assert_lease(job_id, self.worker_id, generation)
        except LeaseLost as exc:
            log.warning("lease_lost", job=job_id, kind=kind, request_id=request_id, worker=self.worker_id, detail=str(exc)[:200])
        except Exception as exc:                                      # noqa: BLE001 - every failure is recorded
            JOB_FAILURES.labels(kind).inc()
            err = f"{type(exc).__name__}: {exc}"
            log.error("job_failed", job=job_id, kind=kind, request_id=request_id, attempt=attempts, error=err[:300],
                      trace=traceback.format_exc()[-1500:])
            with self.ctx.db.session() as s:
                jobs, repo = JobRepo(s), RequestRepo(s)
                job = s.get(type(job), job_id)
                JobRepo(s).assert_lease(job_id, self.worker_id, generation)     # a stale worker records no failure either
                if attempts >= MAX_ATTEMPTS or kind in RECURRING:
                    jobs.done(job)
                    if request_id and kind not in RECURRING:
                        row = repo.get(request_id)
                        repo.event(row, "error", "worker", err[:300])
                        if row.status in (S.APPROVED.value, S.PR_OPEN.value):
                            repo.move(row, E.PR_FAILED, "worker", f"{kind} failed after {attempts} attempts: {err[:120]}")
                        elif row.status == S.MERGED.value:
                            repo.move(row, E.SYNC_TIMEOUT, "worker", f"{kind} failed after {attempts} attempts: {err[:120]}")
                    if kind in RECURRING:
                        jobs.enqueue(kind, delay=RECURRING[kind], payload={"every": RECURRING[kind]})
                else:
                    jobs.retry(job, err, BACKOFF[min(attempts, len(BACKOFF)) - 1])
                    if request_id:
                        repo.event(repo.get(request_id), "error", "worker", f"{kind}: {err[:200]}; retrying")
        finally:
            finished.set()
        return True

    def loop(self) -> None:
        last_gauges = 0.0
        recurring_ready = False
        while not self._stop.is_set():
            LAST_LOOP.set_to_current_time()
            try:
                # In the loop, not before it: on first install the migrate hook runs after helm --wait, and helm
                # waits for this pod. A worker that died here would hold the migration back forever.
                if not recurring_ready:
                    self.ensure_recurring()
                    recurring_ready = True
                ran = self.run_one()
            except Exception as exc:                                  # noqa: BLE001 - the loop itself must not die
                log.error("worker_loop_error", error=str(exc)[:300], trace=traceback.format_exc()[-1500:])
                ran = False
            if time.time() - last_gauges > 15:
                try:
                    self.gauges()
                except Exception as exc:                              # noqa: BLE001
                    log.warning("gauges_failed", error=str(exc)[:200])
                last_gauges = time.time()
            if not ran:
                self._stop.wait(self.poll)
        log.info("worker_stopped", worker=self.worker_id)


def run(s: Settings | None = None) -> None:
    s = s or settings()
    configure_logging(s.log_level)
    os.environ.setdefault("CMAPI_COMPONENT", "worker")
    ctx = build_context(s)
    register_collectors()
    if s.metrics_port:
        start_metrics(s.metrics_port, ctx.cfg.name, "worker")
    worker = Worker(ctx, s.worker_id or socket.gethostname(), s.worker_poll_seconds)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    log.info("worker_start", instance=ctx.cfg.name, delivery=ctx.delivery.mode, clusters=ctx.registry.status_map())
    worker.loop()
    ctx.shutdown()


if __name__ == "__main__":
    run()
