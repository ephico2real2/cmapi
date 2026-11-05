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
"""
from __future__ import annotations

import os
import signal
import socket
import threading
import time
import traceback
from typing import Any, Callable

from prometheus_client import Gauge

from cmapi.core.context import AppContext, build_context
from cmapi.core.db.repo import JobRepo, RequestRepo, oldest_open_ages
from cmapi.core.kpi import register_collectors
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import JOB_FAILURES, JOBS_PENDING, OPEN_REQUEST_AGE, configure_logging, log, start_metrics
from cmapi.jobs import HANDLERS, RECURRING
from cmapi.settings import Settings, settings

LAST_LOOP = Gauge("cmapi_worker_last_loop_timestamp_seconds", "When the worker loop last ran")
BACKOFF = (5, 15, 45, 135, 405)
MAX_ATTEMPTS = 5


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
            for kind in set(HANDLERS) | set(counts):
                JOBS_PENDING.labels(kind).set(counts.get(kind, 0))
            for status, env, age in oldest_open_ages(s):
                OPEN_REQUEST_AGE.labels(status, env).set(age)

    def run_one(self) -> bool:
        """Claim and run one job; True when one was run."""
        with self.ctx.db.session() as s:
            job = JobRepo(s).claim(self.worker_id)
            if job is None:
                return False
            job_id, kind, request_id, payload, attempts = job.job_id, job.kind, job.request_id, dict(job.payload or {}), job.attempts
        handler: Callable[..., Any] | None = HANDLERS.get(kind)
        log.info("job_start", job=job_id, kind=kind, request_id=request_id, attempt=attempts, worker=self.worker_id)
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
        except Exception as exc:                                      # noqa: BLE001 - every failure is recorded
            JOB_FAILURES.labels(kind).inc()
            err = f"{type(exc).__name__}: {exc}"
            log.error("job_failed", job=job_id, kind=kind, request_id=request_id, attempt=attempts, error=err[:300],
                      trace=traceback.format_exc()[-1500:])
            with self.ctx.db.session() as s:
                jobs, repo = JobRepo(s), RequestRepo(s)
                job = s.get(type(job), job_id)
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
        return True

    def loop(self) -> None:
        self.ensure_recurring()
        last_gauges = 0.0
        while not self._stop.is_set():
            LAST_LOOP.set_to_current_time()
            try:
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
