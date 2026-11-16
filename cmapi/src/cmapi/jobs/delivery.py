"""What the delivery jobs share (#286): the request's branch request, its PR, the job's log context, the apply marker, and the
end of a PR. The jobs, one external effect each (Fable's design, section 2; the arbitration, row 2):

    push_branch   approved        the request branch on the host                          jobs/push_branch.py
    open_pr       approved        the PR                                                   jobs/open_pr.py
    pr_checks     pr_open         the checks, then apply (apply mode) or merge             jobs/pr_checks.py
    apply         pr_open         apply mode: the branch's folder on the cluster, read     jobs/apply.py
    merge         pr_open,        the merge, pinned to a sha                               jobs/merge.py
                  applied, merge_failed
    git_cleanup   a final state   close a PR, delete the branch with a lease               jobs/git_cleanup.py
    git_reconcile periodic        PRs and branches a crashed worker left                   jobs/git_reconcile.py
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.git.base import BranchRequest
from cmapi.core.git.oplog import git_context
from cmapi.core.git.workspace import TRAILER_PLAN_HASH, TRAILER_REQUEST, request_branch
from cmapi.core.lifecycle import State as S
from cmapi.core.ports import PrRef
from cmapi.core.render.manifests import NamespaceSpec, folder, plan_hash

APPLY_STARTED = "apply_started"


def spec_from(d: dict[str, Any]) -> NamespaceSpec:
    d = dict(d)
    d["expires_at"] = date.fromisoformat(d["expires_at"]) if d.get("expires_at") else None
    d["grants"] = [tuple(x) for x in d.get("grants", [])]
    d["scc_grants"] = [tuple(x) for x in d.get("scc_grants", [])]
    return NamespaceSpec(**d)


def _line(value: Any) -> str:
    """A trailer value: one line, whatever a field holds."""
    return " ".join(str(value).split())


def title_of(row: Any) -> str:
    return f"{row.action} {row.namespace} ({row.request_id})"


def body_of(row: Any) -> str:
    req = row.requirement or {}
    return (f"Request: {row.request_id}\nPlan hash: {row.plan_hash}\nApproval: {req.get('auto') or 'approved in cmapi'}\n"
            f"Requester: {row.requester_username}\nInstance: {row.instance}")


def commit_message(row: Any) -> str:
    """The subject, the body, and the trailers that a retry, the reconciler and the history read back (Fable 2.1)."""
    req = row.requirement or {}
    return (f"{title_of(row)}\n\ncmapi request {row.request_id} on cluster {row.cluster_id}.\n\n"
            f"{TRAILER_REQUEST}: {_line(row.request_id)}\n"
            f"{TRAILER_PLAN_HASH}: {_line(row.plan_hash)}\n"
            f"Cmapi-Approval: {_line(req.get('auto') or 'approved in cmapi')}\n"
            f"Cmapi-Requester: {_line(row.requester_username)}\n"
            f"Cmapi-Instance: {_line(row.instance)}\n")


def rendered(ctx: AppContext, row: Any) -> dict[str, str | None]:
    """The plan's files, rendered again from the stored spec, and the plan hash checked (as open_pr always did)."""
    plan = row.plan
    files = plan["files"]
    if plan.get("spec"):
        spec = spec_from(plan["spec"])
        spec.request_id = row.request_id
        files = ctx.pipeline.renderer.render(spec, previous=plan["prev"])
    if plan_hash(files) != row.plan_hash:
        raise RuntimeError(f"plan hash mismatch: stored {row.plan_hash[:12]}, rendered {plan_hash(files)[:12]}")
    return files


def branch_request(ctx: AppContext, row: Any) -> BranchRequest:
    approved = row.approved_at or row.created_at or datetime.now(timezone.utc)
    return BranchRequest(row.cluster_id, row.request_id, folder(row.cluster_id, row.namespace), row.plan_hash, commit_message(row),
                         rendered(ctx, row), dict(row.plan.get("prev") or {}), approved)


def planned(row: Any) -> dict[str, str]:
    return {p: t for p, t in row.plan["files"].items() if t is not None}


def pr_of(row: Any) -> PrRef:
    return PrRef(number=row.pr["number"], url=row.pr["url"], branch=row.pr["branch"], head_sha=row.pr["head"])


def mode_of(ctx: AppContext, cluster_id: str) -> str:
    st = ctx.registry.get(cluster_id)
    return st.policy.delivery if st.policy and st.policy.delivery else ctx.delivery.mode


@contextmanager
def request_context(ctx: AppContext, row: Any, job: JobRow) -> Iterator[None]:
    """The fields of every git_op event a job logs for its request (Fable 6.1)."""
    pr = row.pr or {}
    with git_context(request_id=row.request_id, cluster=row.cluster_id, namespace=row.namespace,
                     branch=request_branch(row.cluster_id, row.request_id), attempt=job.attempts, pr_number=pr.get("number"),
                     platform=getattr(ctx.git, "name", None)):
        yield


def apply_started(repo: RequestRepo, row: Any) -> str | None:
    """The head of the last apply_started event: an apply has begun, so the cluster may be ahead of main."""
    heads = [(e.detail or {}).get("head") for e in repo.events(row.request_id) if e.event == APPLY_STARTED]
    return heads[-1] if heads else None


def mark_apply_started(ctx: AppContext, request_id: str, head: str) -> bool:
    """apply_started, in its own transaction, under the request's row lock (Fable 1.4): committed before the first write, so a
    crash after it still finds it, and a :cancel that takes the same lock either waits for it and then refuses, or wins first
    and this returns False. The job's own session holds no lock on the row yet, so the two cannot deadlock."""
    with ctx.db.session() as s:
        repo = RequestRepo(s)
        row = repo.get_for_update(request_id)
        if row.status not in (S.PR_OPEN.value, S.SYNC_FAILED.value):
            return False
        repo.event(row, APPLY_STARTED, "cmapi-deliverer", f"applying {head[:8]} before the merge", {"head": head})
    return True


def end_pr(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row: Any, why: str) -> None:
    """A PR that will not merge, with nothing applied: comment, close, and leave the branch to git_cleanup."""
    if row.pr and row.pr.get("number"):
        jobs.fence()
        ctx.git.close(pr_of(row), f"cmapi: {row.request_id} is {row.status}: {why}. This PR will not merge.")
        repo.event(row, "pr_closed", "worker", f"#{row.pr['number']}: {why}"[:300], {"number": row.pr["number"]})
    jobs.enqueue("git_cleanup", request_id=row.request_id, cluster_id=row.cluster_id)
