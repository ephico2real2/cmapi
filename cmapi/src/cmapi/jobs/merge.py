"""merge: the PR's merge through the host API, pinned to a sha (#286; Fable's design 1.2, 1.3, 2.3, 2.4).

    argocd mode, and a delete in apply mode    pr_open        pinned to the head the checks passed on
    apply mode, a create or a change           applied,       pinned to the applied head (row.pr.applied_head)
                                               merge_failed

Steps: read the PR first. Merged already (a person, or an earlier attempt that stopped after the host merged): adopted, after
the post-merge check. Closed: before an apply the request is failed; after one, a new PR opens from the same branch, which
the reproducible commit re-creates bit for bit if it is gone, and the request never becomes failed. Then the merge check on a
fresh main, the merge, and the post-merge check: the folder at the merge sha must be the plan's.

A refusal after an apply is merge_failed (F1): the PR and the branch are kept, the reason goes on the PR as a comment and on
the timeline, and the alert fires. A host or network error is retried with the worker's backoff; after five attempts applied
becomes merge_failed (worker.py). From merge_failed only :retry runs this job again. Never a rollback, never a close."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.git.base import HeadMoved, NotMergeable, PlatformRefused
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.git.workspace import BranchRefused
from cmapi.core.observability import GIT_ORPHANS, LEAD_TIME, MERGE_CONFLICTS
from cmapi.core.ports import PrRef
from cmapi.core.render.manifests import folder
from cmapi.jobs.delivery import body_of, branch_request, end_pr, mode_of, planned, pr_of, request_context, title_of

AFTER_APPLY = (S.APPLIED.value, S.MERGE_FAILED.value)


def merge(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    merge_first = row.status == S.PR_OPEN.value and (mode_of(ctx, row.cluster_id) != "apply" or row.action == "delete")
    if not row.pr or not (merge_first or row.status in AFTER_APPLY):
        jobs.done(job)
        return
    with request_context(ctx, row, job):
        _merge(ctx, repo, jobs, row, job)


def merge_failed(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, why: str, detail: dict | None = None) -> None:
    """F1: the cluster holds the change and main does not. The lock, the PR and the branch stay; the reason is on the PR."""
    repo.event(row, "merge_failed", "worker", why[:300], detail or {})
    if row.status == S.APPLIED.value:
        repo.move(row, E.MERGE_FAILED, "worker", why[:240])
    jobs.fence()
    ctx.git.comment(pr_of(row), f"cmapi: {row.request_id} is applied on the cluster and its merge did not happen: {why}. "
                                "The PR stays open; :retry merges it.")


def _merge(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow) -> None:
    after_apply = row.status in AFTER_APPLY
    pinned = row.pr.get("applied_head") if after_apply else ((job.payload or {}).get("head") or row.pr["head"])
    pr = pr_of(row)
    state = ctx.git.pr_status(pr)
    if state.state == "merged":
        return _merged(ctx, repo, jobs, row, job, state.merge_sha or "", adopted=True)
    if state.state == "closed":
        if not after_apply:
            repo.move(row, E.PR_FAILED, "worker", "the PR was closed")
            jobs.done(job)
            jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
            return
        try:
            pr = _reopen(ctx, repo, jobs, row, pinned)
        except BranchRefused as exc:
            GIT_ORPHANS.labels("foreign_branch", "refused").inc()
            merge_failed(ctx, repo, jobs, row, f"the PR was closed and it cannot open again: {exc}", {"branch": row.pr["branch"]})
            jobs.done(job)
            return
    check = ctx.git.merge_check(pinned, folder(row.cluster_id, row.namespace), row.plan.get("prev") or {}, row.plan["files"])
    if not check.ok:
        MERGE_CONFLICTS.labels("merge").inc()
        why = check.reason(ctx.git.default_branch)
        detail = {"caller": "merge", "main": check.main_sha, "head": pinned, "conflict_paths": list(check.conflicts)}
        repo.event(row, "merge_check", "worker", why[:300], detail)
        if after_apply:
            merge_failed(ctx, repo, jobs, row, why, detail)
        else:
            repo.move(row, E.BASE_CHANGED, "worker", why[:240])
            end_pr(ctx, repo, jobs, row, why)
        jobs.done(job)
        return
    # The request row, locked until this job commits (Fable's design, 2): a :cancel takes the same lock, so it waits for the
    # merge and is then refused, and one that came first is seen here and nothing merges.
    before = row.status
    repo.s.refresh(row, attribute_names=["status"], with_for_update=True)
    if row.status != before:
        jobs.done(job)
        return
    jobs.fence()
    try:
        sha = ctx.git.merge(pr, pinned)
    except (HeadMoved, PlatformRefused) as exc:
        why = f"the host refused the merge: {exc}"
        if after_apply:
            merge_failed(ctx, repo, jobs, row, why, {"http_status": getattr(exc, "status", None)})
        else:
            repo.move(row, E.PR_FAILED, "worker", why[:240])
            end_pr(ctx, repo, jobs, row, why)
        jobs.done(job)
        return
    except NotMergeable as exc:
        if exc.transient:
            raise                               # the host is still computing: the worker's backoff, then merge_failed
        if after_apply:
            merge_failed(ctx, repo, jobs, row, f"the host will not merge it: {exc}")
        else:
            repo.move(row, E.PR_FAILED, "worker", f"the host will not merge it: {exc}"[:240])
            end_pr(ctx, repo, jobs, row, str(exc))
        jobs.done(job)
        return
    _merged(ctx, repo, jobs, row, job, sha, adopted=False)


def _reopen(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, pinned: str) -> PrRef:
    """A person closed the PR after the apply: a new PR from the same branch, never failed (Fable 1.3)."""
    branch = row.pr["branch"]
    jobs.fence()                                # both the push of a re-created branch and the new PR are external effects
    if ctx.git.branch_head(branch) != pinned:
        ctx.git.recreate_branch(branch_request(ctx, row), row.pr.get("base") or "", pinned)
    new = ctx.git.open_pr(branch, pinned, title_of(row), body_of(row))
    repo.event(row, "pr_reopened", "cmapi-bot", f"#{row.pr['number']} was closed; #{new.number} opened from the same branch",
               {"old": row.pr["number"], "new": new.number})
    row.pr = {**row.pr, "number": new.number, "url": new.url, "head": new.head_sha}
    return new


def _merged(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, sha: str, adopted: bool) -> None:
    """Fable 2.4, a gate on every path that records a merge (this job, a hand merge pr_checks or apply finds): the folder at
    the merge sha must be the plan's. Then merged; after an apply also synced, since the read already confirmed it; otherwise
    watch_sync. A merge whose folder is not the plan's, or with no sha to read, is merged and then sync_failed, with the lock
    held for an operator: nothing is applied from it and a delete never waits for a prune of it (#449)."""
    after_apply = row.status in AFTER_APPLY
    on_main = ctx.git.tree_files(sha, folder(row.cluster_id, row.namespace)) if sha else None
    fulfilled = on_main == planned(row)
    if fulfilled and row.action == "delete":
        # A delete's folder is empty at the merge: no file of any kind, at any depth, is left of it (#616).
        fulfilled = not ctx.git.list_folder(folder(row.cluster_id, row.namespace), sha)[0]
    row.merge_sha = sha or None
    how = "adopted: merged on the host" if adopted else "merged"
    repo.event(row, "merge_verified", "worker", f"{how} {sha[:8]}; the folder at it {'is' if fulfilled else 'is not'} the plan's",
               {"merge_sha": sha, "adopted": adopted})
    repo.move(row, E.MERGED, "cmapi-bot", f"{how} {sha[:8]}")
    if not fulfilled:
        why = f"the folder at the merge {sha[:8]} is not the approved plan" if sha else "the host gave no merge sha to check"
        repo.move(row, E.SYNC_TIMEOUT, "worker", why)
    elif after_apply:
        repo.move(row, E.SYNCED, "cmapi-deliverer", "applied and confirmed by a read before the merge")
        approval = "auto" if (row.requirement or {}).get("auto") else "human"
        LEAD_TIME.labels(row.plugin, row.action, approval).observe((datetime.now(timezone.utc) - row.created_at).total_seconds())
    else:
        jobs.enqueue("watch_sync", request_id=row.request_id, cluster_id=row.cluster_id)
    ctx.git.cleanup(row.cluster_id, row.request_id)
    jobs.done(job)
    jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
