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
from cmapi.core.git.base import NotUtf8
from cmapi.core.git.workspace import BranchRefused, request_branch
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import GIT_ORPHANS
from cmapi.core.render.manifests import folder
from cmapi.jobs.delivery import adoption_staleness, branch_request, end_adoption, request_context


def push_branch(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.APPROVED.value:
        jobs.done(job)
        return
    with request_context(ctx, row, job):
        changed = None
        try:
            current, main = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
            # A delete removes each path of the folder that its plan listed, each a file: a path added or removed since then, or
            # one that became a submodule, is a changed folder too, or the merge would leave it in Git (#616).
            moved = row.action == "delete" and \
                ctx.git.list_folder(folder(row.cluster_id, row.namespace), main)[0] != dict.fromkeys(row.plan["files"], "blob")
            if current != row.plan["prev"] or moved:
                changed = f"folder changed in Git since the plan (at {main[:8]})"
        except NotUtf8 as exc:
            # The plan refuses a folder that holds such a path, so the folder changed since: superseded, never retried (#626).
            changed = f"folder changed in Git since the plan: {exc}"
        if changed:
            return _superseded(repo, jobs, job, row, changed)
        # An adoption reads the live objects again when it is approved: this job is the first step after the approval (D16).
        found = adoption_staleness(ctx, row)
        if found is not None:
            end_adoption(ctx, repo, jobs, row, found, "worker")
            jobs.done(job)
            return
        req = branch_request(ctx, row)
        jobs.fence()
        try:
            pushed = ctx.git.push_request_branch(req)
        except NotUtf8 as exc:
            # The Gitea stand-in reads the folder again as it writes: a name that landed since the read above (#626).
            return _superseded(repo, jobs, job, row, f"folder changed in Git since the plan: {exc}")
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


def _superseded(repo: RequestRepo, jobs: JobRepo, job: JobRow, row, why: str) -> None:
    """The folder on main is not the plan's base: superseded, the lock released, and git_cleanup for anything left."""
    repo.move(row, E.BASE_CHANGED, "worker", why[:240])
    jobs.done(job)
    jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
