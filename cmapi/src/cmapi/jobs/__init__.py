"""Worker jobs, one module each (docs/02, Worker jobs). HANDLERS maps a job kind to its function
(ctx, session, job); RECURRING names the kinds that re-enqueue themselves with their period.

Delivery (#286) is a chain of jobs with one external effect each (jobs/delivery.py): push_branch, open_pr, pr_checks, apply
(apply mode), merge, then watch_sync or prune as before, and git_cleanup at the end. git_reconcile runs every 15 minutes."""
from __future__ import annotations

from cmapi.jobs.apply import apply
from cmapi.jobs.approval_timeout import APPROVAL_TIMEOUT_EVERY, approval_timeout
from cmapi.jobs.channel_notify import channel_notify
from cmapi.jobs.git_cleanup import git_cleanup
from cmapi.jobs.git_reconcile import GIT_RECONCILE_EVERY, git_reconcile
from cmapi.jobs.merge import merge
from cmapi.jobs.open_pr import open_pr, open_revert
from cmapi.jobs.pr_checks import pr_checks
from cmapi.jobs.push_branch import push_branch
from cmapi.jobs.rejections_prune import REJECTIONS_PRUNE_EVERY, rejections_prune
from cmapi.jobs.watch_sync import prune, watch_sync

HANDLERS = {
    "push_branch": push_branch,
    "open_pr": open_pr,
    "open_revert": open_revert,
    "pr_checks": pr_checks,
    "apply": apply,
    "merge": merge,
    "watch_sync": watch_sync,
    "prune": prune,
    "git_cleanup": git_cleanup,
    "git_reconcile": git_reconcile,
    "approval_timeout": approval_timeout,
    "channel_notify": channel_notify,
    "rejections_prune": rejections_prune,
}

RECURRING = {"approval_timeout": APPROVAL_TIMEOUT_EVERY, "git_reconcile": GIT_RECONCILE_EVERY,
             "rejections_prune": REJECTIONS_PRUNE_EVERY}
