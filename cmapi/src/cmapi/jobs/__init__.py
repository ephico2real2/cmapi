"""Worker jobs, one module each (docs/02, Worker jobs). HANDLERS maps a job kind to its function
(ctx, session, job); RECURRING names the kinds that re-enqueue themselves with their period."""
from __future__ import annotations

from cmapi.jobs.approval_timeout import APPROVAL_TIMEOUT_EVERY, approval_timeout
from cmapi.jobs.channel_notify import channel_notify
from cmapi.jobs.open_pr import open_pr, open_revert
from cmapi.jobs.pr_checks import pr_checks
from cmapi.jobs.watch_sync import prune, watch_sync

HANDLERS = {
    "open_pr": open_pr,
    "open_revert": open_revert,
    "pr_checks": pr_checks,
    "watch_sync": watch_sync,
    "prune": prune,
    "approval_timeout": approval_timeout,
    "channel_notify": channel_notify,
}

RECURRING = {"approval_timeout": APPROVAL_TIMEOUT_EVERY}
