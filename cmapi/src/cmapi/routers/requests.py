"""The requests router (docs/02, routers/requests.py): list, get, events, approval-status, and the
decisions :approve, :reject, :cancel, :retry. Every decision is an audit event."""
from __future__ import annotations

from fastapi import Depends, Query

from cmapi.core.context import AppContext
from cmapi.core.db.repo import AuditRepo, JobRepo, RequestRepo
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.listquery import ListQuery
from cmapi.core.models import ApprovalStatus, ChangeRequest, DecisionBody, RequestEvents, RequestPage
from cmapi.core.observability import APPROVAL_WAIT
from cmapi.core.views import request_view
from cmapi.routers import caller, ctx, require

router = DocumentedRouter("requests", prefix="/api/v1")


def _visible_envs(c: AppContext, who: Identity) -> set[str]:
    envs = c.cfg.roles.environments(who, "requests:read")
    return set(c.cfg.allowed_environments) if envs is None else envs


@router.read("/requests", summary="List requests", permission="requests:read", response_model=RequestPage,
             problems=["invalid-cursor", "invalid-limit"])
def list_requests(
        status: str | None = Query(default=None, description="Lifecycle state, e.g. pending_approval"),
        approver: str | None = Query(default=None, description="me: only requests the caller can still approve"),
        cluster_id: str | None = Query(default=None, alias="clusterId", description="One cluster"),
        requested_by: str | None = Query(default=None, alias="requestedBy", description="Requester username"),
        q: str = Query(default="", description="Text match on request ID, namespace or cluster"),
        limit: int = Query(default=50, description="25, 50 or 100; at most 200"),
        cursor: str | None = Query(default=None, description="Keyset cursor from a previous page"),
        who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """One page of requests in the environments where the caller may read requests, newest first.
    `approver=me` keeps only requests still waiting for an approval from one of the caller's groups."""
    with c.db.session() as s:
        repo = RequestRepo(s)
        rows = repo.list(status=status, cluster_id=cluster_id, requested_by=requested_by, envs=_visible_envs(c, who))
        views = [request_view(repo, r, with_events=True) for r in rows]
    if approver == "me":
        views = [v for v in views if v["approval"] and v["status"] == "pending_approval" and
                 any(f"/cmapi/cmapi-{r['group']}" in who.groups for r in v["approval"]["remaining"])]
    if q:
        t = q.lower()
        views = [v for v in views if t in v["requestId"].lower() or t in v["namespace"].lower() or t in v["clusterId"].lower()]
    rows_for_paging = [{**v, "name": v["requestId"], "clusterId": v["clusterId"], "_created": v["createdAt"].timestamp()} for v in views]
    page = c.lister.page(rows_for_paging, ListQuery(q="", sort="newest", limit=limit, cursor=cursor,
                                                   filters={"status": status or "", "approver": approver or ""}))
    page["items"] = [{k: v for k, v in it.items() if k not in ("name", "_created")} for it in page["items"]]
    return page


@router.read("/requests/{request_id}", summary="One request", permission="requests:read", response_model=ChangeRequest,
             problems=["object-not-found"])
def get_request(request_id: str, who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """The request with its approval ledger, its PR and every event so far."""
    with c.db.session() as s:
        repo = RequestRepo(s)
        row = repo.get(request_id)
        c.cfg.roles.require(who, "requests:read", row.env)
        return request_view(repo, row)


@router.read("/requests/{request_id}/events", summary="A request's events", permission="requests:read",
             response_model=RequestEvents, problems=["object-not-found"])
def get_events(request_id: str, who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """Every state change of the request, oldest first: what the portal's WorkflowViewer draws."""
    with c.db.session() as s:
        repo = RequestRepo(s)
        row = repo.get(request_id)
        c.cfg.roles.require(who, "requests:read", row.env)
        return {"requestId": row.request_id, "status": row.status,
                "events": [{"at": e.at, "event": e.event, "status": e.status, "by": e.by, "note": e.note}
                           for e in repo.events(request_id)]}


@router.read("/requests/{request_id}/approval-status", summary="Is this request approved, and for which plan",
             permission="requests:read", response_model=ApprovalStatus, problems=["object-not-found"])
def approval_status(request_id: str, who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """What the cmapi check in CI asks: the request is approved (or further along) and the plan hash the PR must carry."""
    with c.db.session() as s:
        row = RequestRepo(s).get(request_id)
        approved = row.status in ("approved", "pr_open", "merged", "awaiting_prune", "synced")
        return {"requestId": row.request_id, "approved": approved, "status": row.status, "planHash": row.plan_hash}


@router.write("/requests/{request_id}:approve", summary="Approve a request", permission="requests:approve",
              response_model=ChangeRequest, status_code=200,
              problems=["object-not-found", "not-pending", "already-approved", "self-approval", "not-eligible", "environment-forbidden"])
def approve(request_id: str, body: DecisionBody | None = None, who: Identity = Depends(require("requests:approve")),
            c: AppContext = Depends(ctx)) -> dict:
    """Records one approval from an eligible person. When every slot is filled the request becomes approved
    and the worker opens the bot PR. The approver's own token decides: no relay, no Git review."""
    comment = (body.comment if body else "") or ""
    with c.db.session() as s:
        repo, jobs = RequestRepo(s), JobRepo(s)
        row = repo.get(request_id)
        if row.status != S.PENDING_APPROVAL.value:
            raise Problem.conflict("not-pending", f"{request_id} is {row.status}")
        ledger = repo.ledger(row)
        if ledger is None:
            raise Problem.conflict("not-pending", f"{request_id} needs no approval")
        met = ledger.approve(who, permitted=c.cfg.roles.allowed(who, "requests:approve", row.env), comment=comment)
        repo.record_approval(row, who, comment, None)
        AuditRepo(s).record(who, "request.approve", request_id, {"comment": comment})
        if met:
            repo.move(row, E.APPROVED, who.username, "approval count met")
            if row.approved_at and row.created_at and row.requirement:
                APPROVAL_WAIT.labels(row.requirement.get("rule", "")).observe((row.approved_at - row.created_at).total_seconds())
            jobs.enqueue("open_pr", request_id=request_id, cluster_id=row.cluster_id)
            jobs.enqueue("channel_notify", request_id=request_id, cluster_id=row.cluster_id, payload={"kind": "approved"})
        return request_view(repo, row)


@router.write("/requests/{request_id}:reject", summary="Reject a request", permission="requests:reject",
              response_model=ChangeRequest, status_code=200,
              problems=["object-not-found", "not-pending", "validation-failed", "environment-forbidden"])
def reject(request_id: str, body: DecisionBody, who: Identity = Depends(require("requests:reject")),
           c: AppContext = Depends(ctx)) -> dict:
    """Rejects a pending request with a comment, which the requester sees. Releases the namespace lock."""
    if not body.comment.strip():
        raise Problem.unprocessable("validation-failed", "A comment is required to reject")
    with c.db.session() as s:
        repo, jobs = RequestRepo(s), JobRepo(s)
        row = repo.get(request_id)
        c.cfg.roles.require(who, "requests:reject", row.env)
        repo.move(row, E.REJECTED, who.username, body.comment)
        AuditRepo(s).record(who, "request.reject", request_id, {"comment": body.comment})
        jobs.enqueue("channel_notify", request_id=request_id, cluster_id=row.cluster_id, payload={"kind": "rejected"})
        return request_view(repo, row)


@router.write("/requests/{request_id}:cancel", summary="Cancel a request", permission="requests:cancel",
              response_model=ChangeRequest, status_code=200, problems=["object-not-found", "invalid-transition"])
def cancel(request_id: str, who: Identity = Depends(require("requests:cancel")), c: AppContext = Depends(ctx)) -> dict:
    """The requester, or an operator, withdraws a request before its PR is open."""
    with c.db.session() as s:
        repo = RequestRepo(s)
        row = repo.get(request_id)
        repo.move(row, E.CANCEL, who.username, actor_is_requester=row.requester_username == who.username,
                  actor_is_operator=bool({"cmapi-operator", "cmapi-admin"} & who.roles))
        AuditRepo(s).record(who, "request.cancel", request_id, None)
        return request_view(repo, row)


@router.write("/requests/{request_id}:retry", summary="Retry a failed request", permission="requests:retry",
              response_model=ChangeRequest, status_code=200,
              problems=["object-not-found", "invalid-transition", "change-pending"])
def retry(request_id: str, who: Identity = Depends(require("requests:retry")), c: AppContext = Depends(ctx)) -> dict:
    """From failed: re-takes the namespace lock (409 if another request holds it) and opens the PR again.
    From sync_failed: watches the sync again."""
    with c.db.session() as s:
        repo, jobs = RequestRepo(s), JobRepo(s)
        row = repo.get(request_id)
        before = row.status
        after = repo.move(row, E.RETRY, who.username, "retry requested")
        row.attempts = 0
        AuditRepo(s).record(who, "request.retry", request_id, {"from": before})
        if after is S.APPROVED:
            jobs.enqueue("open_pr", request_id=request_id, cluster_id=row.cluster_id)
        else:
            jobs.enqueue("watch_sync", request_id=request_id, cluster_id=row.cluster_id, payload={"since": None})
        return request_view(repo, row)


@router.write("/requests/{request_id}:revert", summary="Revert a sync-failed request", permission="requests:retry",
              response_model=ChangeRequest, status_code=200,
              problems=["object-not-found", "invalid-transition", "change-pending"])
def revert(request_id: str, who: Identity = Depends(require("requests:retry")), c: AppContext = Depends(ctx)) -> dict:
    """Marks a sync_failed request reverted and opens a new request that restores the folder as it was
    before the plan, through the same approval rules. The new request's ID is in the events."""
    with c.db.session() as s:
        repo, jobs = RequestRepo(s), JobRepo(s)
        row = repo.get(request_id)
        repo.move(row, E.REVERT, who.username, "revert requested")
        AuditRepo(s).record(who, "request.revert", request_id, None)
        jobs.enqueue("open_revert", request_id=request_id, cluster_id=row.cluster_id, payload={"by": who.username})
        return request_view(repo, row)
