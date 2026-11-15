"""open_pr: the request branch is on the host (push_branch); open its PR, or adopt the one that exists, then queue pr_checks.

One external effect (Fable's design, section 2): the PR. The branch's head must be the one push_branch recorded; if it is not,
push_branch runs again, and its adoption test decides. A job queued before #286, with no head, also starts at push_branch.

open_revert: a :revert on a sync_failed request whose change is on main: a new request that restores the folder as it was
before the plan."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.errors import Problem
from cmapi.core.git.workspace import request_branch
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import log
from cmapi.core.render.manifests import folder
from cmapi.jobs.delivery import body_of, request_context, title_of


def open_pr(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.APPROVED.value:
        log.info("open_pr_skip", request_id=row.request_id, status=row.status)
        jobs.done(job)
        return
    with request_context(ctx, row, job):
        _open_pr(ctx, repo, jobs, row, job)


def _open_pr(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow) -> None:
    branch = request_branch(row.cluster_id, row.request_id)
    head, base = (job.payload or {}).get("head"), (job.payload or {}).get("base")
    if not head or ctx.git.branch_head(branch) != head:
        # No recorded push, or the branch is not at it: push_branch adopts, replaces or refuses (Fable 2.2).
        jobs.done(job)
        jobs.enqueue("push_branch", request_id=row.request_id, cluster_id=row.cluster_id)
        return
    jobs.fence()
    pr = ctx.git.open_pr(branch, head, title_of(row), body_of(row))
    try:
        repo.move(row, E.PR_OPENED, "cmapi-bot", f"{pr.branch} #{pr.number}")
    except Problem:
        # Cancelled while the host call ran: the state stands, and the PR it no longer owns is closed by git_cleanup.
        repo.event(row, "pr_closed", "worker", f"#{pr.number}: the request became {row.status} while the PR was opening")
        jobs.fence()
        ctx.git.close(pr, f"cmapi: {row.request_id} is {row.status}; this PR will not merge.")
        jobs.done(job)
        jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
        return
    row.pr = {"number": pr.number, "url": pr.url, "branch": pr.branch, "head": pr.head_sha, "base": base}
    jobs.done(job)
    jobs.enqueue("pr_checks", request_id=row.request_id, cluster_id=row.cluster_id)


def open_revert(ctx: AppContext, s: Session, job: JobRow) -> None:
    """A :revert on a sync_failed request: a new request that restores the folder as it was before the plan."""
    from cmapi.core.identity.claims import Identity
    from cmapi.core.pipeline import Plan, CapacityResult

    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.SYNC_FAILED.value:
        jobs.done(job)
        return
    prev = row.plan.get("prev") or {}
    now_files, base_sha = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
    # Only after Git answered, and in the transaction that records the new request: an outage leaves the
    # request sync_failed, ready to be reverted again, never reverted with nothing behind it.
    by = job.payload.get("by", "worker") if job.payload else "worker"
    repo.move(row, E.REVERT, by, "revert requested")
    files: dict[str, str | None] = {p: t for p, t in prev.items()}
    for p in now_files:
        if p not in prev:
            files[p] = None
    changes = {p: ("removed" if t is None else "changed") for p, t in files.items() if now_files.get(p) != t}
    if not changes:
        repo.event(row, "revert_noop", "worker", "the folder already matches the state before the plan")
        jobs.done(job)
        return
    # Reverting a create removes the folder, so it is a delete: an update would drop the quota and leave the
    # namespace on the cluster with no folder and no way to prune it.
    action = "update" if prev else "delete"
    facts = {"plugin": "namespaces", "action": action, "environment": row.env, "namespace": row.namespace,
             "clusterId": row.cluster_id, "team": row.team, "automated": True, "reason": "revert",
             "capacity": "fits", "capacityFresh": True, "warnings": []}
    if action == "delete":
        pods, pvcs = ctx.pipeline.workload_counts(row.cluster_id, row.namespace)
        facts.update(pods=pods, pvcs=pvcs, namespaceAgeDays=0, protected=False)
    requirement = ctx.pipeline._decide(facts)
    who = Identity(sub=row.requester_sub, username=by, kind="user", client_id="cmapi-worker")
    requester = ctx.pipeline.requester_for(Identity(sub=row.requester_sub, username=row.requester_username, kind="user",
                                                    client_id="cmapi-worker", employee_id="revert",
                                                    roles=frozenset({"cmapi-onboarding"})), None)
    plan = Plan(row.cluster_id, row.namespace, row.env, action, "namespaces", None, files, now_files, changes, requirement,
                CapacityResult("fits", True, None, {"source": "revert"}), facts, requester, [], base_sha, reason="revert")
    new = ctx.pipeline.submit(who, plan, repo, jobs, idempotency_key=None, body_fingerprint="revert:" + row.request_id,
                              justification=f"Revert of {row.request_id}")
    repo.event(row, "revert_opened", "worker", new.request_id)
    jobs.done(job)
