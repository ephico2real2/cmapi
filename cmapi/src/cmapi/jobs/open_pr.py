"""open_pr: a request became approved. Re-read the folder, refuse a changed base (superseded),
re-render from the stored plan, check the plan hash, open the bot PR, then queue pr_checks."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.errors import Problem
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import log
from cmapi.core.render.manifests import NamespaceSpec, folder, plan_hash


def _spec_from(d: dict[str, Any]) -> NamespaceSpec:
    d = dict(d)
    d["expires_at"] = date.fromisoformat(d["expires_at"]) if d.get("expires_at") else None
    d["grants"] = [tuple(x) for x in d.get("grants", [])]
    d["scc_grants"] = [tuple(x) for x in d.get("scc_grants", [])]
    return NamespaceSpec(**d)


def open_pr(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.APPROVED.value:
        log.info("open_pr_skip", request_id=row.request_id, status=row.status)
        jobs.done(job)
        return
    plan = row.plan
    base = folder(row.cluster_id, row.namespace)
    current, base_sha = ctx.git.read_folder(base)
    if current != plan["prev"]:
        repo.move(row, E.BASE_CHANGED, "worker", "folder changed in Git since the plan")
        jobs.done(job)
        return
    files = plan["files"]
    if plan.get("spec"):
        spec = _spec_from(plan["spec"])
        spec.request_id = row.request_id
        files = ctx.pipeline.renderer.render(spec, previous=plan["prev"])
    if plan_hash(files) != row.plan_hash:
        raise RuntimeError(f"plan hash mismatch: stored {row.plan_hash[:12]}, rendered {plan_hash(files)[:12]}")
    branch = f"cmapi/{row.cluster_id}/{row.namespace}/{row.request_id}"
    title = f"{row.action} {row.namespace} ({row.request_id})"
    req = row.requirement or {}
    body = (f"Request: {row.request_id}\nPlan hash: {row.plan_hash}\nApproval: {req.get('auto') or 'approved in cmapi'}\n"
            f"Requester: {row.requester_username}\nInstance: {row.instance}")
    pr = ctx.git.open_pr(branch, files, title, body, base_sha)
    try:
        repo.move(row, E.PR_OPENED, "cmapi-bot", f"{pr.branch} #{pr.number}")
    except Problem:
        # Cancelled while the Git calls ran: the state stands, and the PR it no longer owns is closed.
        ctx.git.close(pr, f"cmapi: {row.request_id} is {row.status}; this PR will not merge.")
        repo.event(row, "pr_closed", "worker", f"#{pr.number}: the request became {row.status} while the PR was opening")
        jobs.done(job)
        return
    row.pr = {"number": pr.number, "url": pr.url, "branch": pr.branch, "head": pr.head_sha}
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
