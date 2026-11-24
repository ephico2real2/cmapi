"""push_branch: a request became approved. Read main, refuse a folder that changed since the plan (superseded), render from the
stored plan, check the plan hash, and put the request branch on the host, then queue open_pr (#286; Fable's design, 2).

One external effect: the branch. The Git layer adopts a branch that an earlier attempt pushed (the adoption test, Fable 2.2),
replaces this request's own stale attempt with a lease, and refuses a branch whose head is not cmapi's for this request: that
fails the request, counts in cmapi_git_orphans_total{kind="foreign_branch"} for the alert, and leaves the branch alone (the
arbitration, row 3)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.git.workspace import BranchRefused, request_branch
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import GIT_ORPHANS
from cmapi.core.render.manifests import folder
from cmapi.jobs.delivery import branch_request, request_context


def push_branch(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.APPROVED.value:
        jobs.done(job)
        return
    with request_context(ctx, row, job):
        current, main = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
        # A delete removes each path of the folder that its plan listed: a path added or removed since then is a changed
        # folder too, or the merge would leave it in Git (#616).
        moved = row.action == "delete" and \
            set(ctx.git.list_folder(folder(row.cluster_id, row.namespace), main)[0]) != set(row.plan["files"])
        if current != row.plan["prev"] or moved:
            repo.move(row, E.BASE_CHANGED, "worker", f"folder changed in Git since the plan (at {main[:8]})")
            jobs.done(job)
            jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
            return
        req = branch_request(ctx, row)
        jobs.fence()
        try:
            pushed = ctx.git.push_request_branch(req)
        except BranchRefused as exc:
            GIT_ORPHANS.labels("foreign_branch", "refused").inc()
            repo.event(row, "branch_refused", "worker", str(exc)[:300], {"branch": request_branch(row.cluster_id, row.request_id)})
            repo.move(row, E.PR_FAILED, "worker", str(exc)[:240])
            jobs.done(job)
            return
        repo.event(row, "branch_pushed", "cmapi-bot", f"{request_branch(row.cluster_id, row.request_id)} at {pushed.head[:8]} "
                                                      f"on {pushed.base[:8]} ({pushed.result})",
                   {"head": pushed.head, "base": pushed.base, "adopted": pushed.result == "adopted", "result": pushed.result})
        jobs.done(job)
        jobs.enqueue("open_pr", request_id=row.request_id, cluster_id=row.cluster_id, payload={"head": pushed.head, "base": pushed.base})
