"""BUG-74: two due jobs with the same run_after were claimed in no fixed order (JobRepo.claim ordered by run_after
alone). The merge job of #286 queues watch_sync and then git_cleanup for one request; when their run_after became equal
(as lease_expired in the tests does, and as leases that expire together do), PostgreSQL returned whichever row it met
first, and seven argocd tests failed when their files ran alone. The claim now breaks a tie by job_id: first queued,
first claimed."""
from __future__ import annotations

from sqlalchemy import text

from cmapi.core.db.repo import JobRepo


def test_jobs_with_the_same_run_after_are_claimed_in_the_order_they_were_queued(fresh_db):
    with fresh_db.session() as s:
        jobs = JobRepo(s)
        first = jobs.enqueue("watch_sync", cluster_id="CRC").job_id
        second = jobs.enqueue("git_cleanup", cluster_id="CRC").job_id
    with fresh_db.session() as s:
        # The same run_after for both. The first job is updated last, so its row version is the newest on the heap: an
        # order that rests on row position alone then meets the second job first.
        s.execute(text("update jobs set run_after = now() - interval '1 second' where job_id = :j"), {"j": second})
        s.execute(text("update jobs set run_after = (select run_after from jobs where job_id = :o) where job_id = :j"),
                  {"j": first, "o": second})
    with fresh_db.session() as s:
        claimed = JobRepo(s).claim("w-test")
        assert claimed is not None and claimed.job_id == first, (claimed and claimed.kind, first, second)
