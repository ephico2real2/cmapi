"""git_cleanup: a request reached a final state, or merged. Close its PR if one is still open, and delete its branch on the
host with a lease, only when the branch is at a head that is cmapi's for this request (#286; Fable's design 5.2, 3.2). A
missing PR or branch is success. Never in applied, merge_failed, sync_failed or awaiting_prune, where the PR and the branch are
what an operator or :retry needs (F1). The worktree on this pod goes too; the sweeper removes it on the other pods."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.git.workspace import request_branch
from cmapi.core.lifecycle import State as S
from cmapi.core.observability import GIT_ORPHANS
from cmapi.jobs.delivery import request_context

KEEP = (S.APPROVED.value, S.PR_OPEN.value, S.APPLIED.value, S.MERGE_FAILED.value, S.SYNC_FAILED.value, S.AWAITING_PRUNE.value,
        S.PENDING_APPROVAL.value)


def git_cleanup(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status in KEEP:
        jobs.done(job)
        return
    with request_context(ctx, row, job):
        branch = request_branch(row.cluster_id, row.request_id)
        if row.pr and row.pr.get("number") and row.status != S.MERGED.value and row.status != S.SYNCED.value:
            open_pr = ctx.git.find_pr(branch)
            if open_pr is not None:
                jobs.fence()
                ctx.git.close(open_pr, f"cmapi: {row.request_id} is {row.status}; this PR will not merge.")
                repo.event(row, "pr_closed", "worker", f"#{open_pr.number}: the request is {row.status}", {"number": open_pr.number})
        head = ctx.git.branch_head(branch)
        if head is not None:
            ours = {(row.pr or {}).get("head"), (row.pr or {}).get("applied_head")} - {None}
            if head in ours or ctx.git.request_of(head) == row.request_id:
                jobs.fence()
                if ctx.git.delete_branch(branch, head):
                    repo.event(row, "branch_deleted", "worker", f"{branch} at {head[:8]}", {"head": head})
            else:
                GIT_ORPHANS.labels("foreign_branch", "kept").inc()
                repo.event(row, "branch_kept", "worker", f"{branch} is at {head[:8]}, which is not cmapi's for {row.request_id}: "
                                                         "left alone", {"head": head})
        ctx.git.cleanup(row.cluster_id, row.request_id)
    jobs.done(job)
