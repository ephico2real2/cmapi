"""The requests router (docs/02, routers/requests.py): list, get, events, approval-status, and the
decisions :approve, :reject, :cancel, :retry. Every decision is an audit event."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Query

from cmapi import __version__
from cmapi.core.context import AppContext
from cmapi.core.db.repo import AuditRepo, JobRepo, RequestRepo, utcnow
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.lifecycle import Event as E, State as S, transition
from cmapi.core.listquery import ListQuery
from cmapi.core.models import ApprovalStatus, ChangeRequest, DecisionBody, RequestEvents, RequestPage
from cmapi.core.observability import APPROVAL_WAIT
from cmapi.core.views import request_view
from cmapi.routers import Cursor, Limit, RequestId, caller, ctx, require

router = DocumentedRouter("requests", prefix="/api/v1", version=__version__, group="Requests and approvals",
                          description="The change requests: each write to a namespace is one request, with its approvals, "
                                      "its pull request and its events. Approve, reject, cancel, retry or revert a request here.")


def _visible_envs(c: AppContext, who: Identity) -> set[str]:
    envs = c.cfg.roles.environments(who, "requests:read")
    return set(c.cfg.allowed_environments) if envs is None else envs


@router.read("/requests", summary="List requests", permission="requests:read", response_model=RequestPage,
             problems=["invalid-cursor", "invalid-limit", "validation-failed"])
def list_requests(
        status: str | None = Query(default=None, examples=["pending_approval"],
                                   description="Only the requests in this lifecycle state."),
        state: str | None = Query(default=None, examples=["open"],
                                  description="`open` gives the requests that are not finished: pending_approval, approved, "
                                              "pr_open, merged, awaiting_prune and sync_failed. `closed` gives all the others. "
                                              "Another value returns 422 `validation-failed`."),
        approver: str | None = Query(default=None, examples=["me"],
                                     description="With `me`, only the pending requests that still need an approval from one of "
                                                 "the caller's groups. Any other value has no effect."),
        cluster_id: str | None = Query(default=None, alias="clusterId", examples=["CRC"],
                                       description="Only the requests for this cluster."),
        requested_by: str | None = Query(default=None, alias="requestedBy", examples=["cmapi.requester"],
                                         description="Only the requests that this username opened."),
        q: str = Query(default="", examples=["payments"],
                       description="Text that the request ID, the namespace or the cluster ID contains. Case does not matter."),
        limit: Limit = 50,
        cursor: Cursor = None,
        who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """One page of requests in the environments where the caller may read requests, newest first.
    `approver=me` keeps only requests still waiting for an approval from one of the caller's groups."""
    if state not in (None, "open", "closed"):
        raise Problem.unprocessable("validation-failed", f"state is open or closed, not {state}")
    with c.db.session() as s:
        repo = RequestRepo(s)
        rows = repo.list(status=status, cluster_id=cluster_id, requested_by=requested_by, envs=_visible_envs(c, who),
                         open_=None if state is None else state == "open")
        if approver == "me":
            rows = [r for r in rows if r.status == S.PENDING_APPROVAL.value and _can_still_approve(repo, r, who)]
        if q:
            t = q.lower()
            rows = [r for r in rows if t in r.request_id.lower() or t in r.namespace.lower() or t in r.cluster_id.lower()]
        # Views cost two queries each: page over the bare rows, then build a view for the page only.
        paging = [{"name": r.request_id, "clusterId": r.cluster_id, "_created": r.created_at.timestamp(), "_row": r} for r in rows]
        page = c.lister.page(paging, ListQuery(q="", sort="newest", limit=limit, cursor=cursor,
                                               context={"status": status or "", "state": state or "", "approver": approver or "", "q": q,
                                                        "clusterId": cluster_id or "", "requestedBy": requested_by or ""}))
        page["items"] = [request_view(repo, it["_row"], with_events=True) for it in page["items"]]
    return page


def _can_still_approve(repo: RequestRepo, row: Any, who: Identity) -> bool:
    ledger = repo.ledger(row)
    return bool(ledger) and any(ledger.requirement.token_group(r["group"]) in who.groups for r in ledger.remaining())


@router.read("/requests/{request_id}", summary="One request", permission="requests:read", response_model=ChangeRequest,
             problems=["object-not-found"])
def get_request(request_id: RequestId, who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """The request with its approval ledger, its PR and every event so far."""
    with c.db.session() as s:
        repo = RequestRepo(s)
        row = repo.get(request_id)
        c.cfg.roles.require(who, "requests:read", row.env)
        return request_view(repo, row)


@router.read("/requests/{request_id}/events", summary="A request's events", permission="requests:read",
             response_model=RequestEvents, problems=["object-not-found"])
def get_events(request_id: RequestId, who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
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
def approval_status(request_id: RequestId, who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """What the cmapi check in CI asks: the request is approved (or further along) and the plan hash the PR must carry."""
    with c.db.session() as s:
        row = RequestRepo(s).get(request_id)
        c.cfg.roles.require(who, "requests:read", row.env)
        approved = row.status in ("approved", "pr_open", "merged", "awaiting_prune", "synced")
        return {"requestId": row.request_id, "approved": approved, "status": row.status, "planHash": row.plan_hash}


@router.write("/requests/{request_id}:approve", summary="Approve a request", permission="requests:approve",
              response_model=ChangeRequest, status_code=200,
              problems=["object-not-found", "not-pending", "already-approved", "self-approval", "not-eligible", "environment-forbidden"])
def approve(request_id: RequestId, body: DecisionBody | None = None, who: Identity = Depends(require("requests:approve")),
            c: AppContext = Depends(ctx)) -> dict:
    """Records one approval from an eligible person. When every slot is filled the request becomes approved
    and the worker opens the bot PR. The approver's own token decides: no relay, no Git review."""
    comment = (body.comment if body else "") or ""
    with c.db.session() as s:
        repo, jobs = RequestRepo(s), JobRepo(s)
        # Locked for the whole decision: two approvers count each other, and a person counts once.
        row = repo.get_for_update(request_id)
        # As in reject: a role that does not cover this environment gets environment-forbidden, with where it does apply (#141).
        c.cfg.roles.require(who, "requests:approve", row.env)
        if row.status != S.PENDING_APPROVAL.value:
            raise Problem.conflict("not-pending", f"{request_id} is {row.status}")
        ledger = repo.ledger(row)
        if ledger is None:
            raise Problem.conflict("not-pending", f"{request_id} needs no approval")
        met = ledger.approve(who, permitted=c.cfg.roles.allowed(who, "requests:approve", row.env), comment=comment)
        repo.record_approval(row, who, comment, None, ledger.counted_for())
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
def reject(request_id: RequestId, body: DecisionBody, who: Identity = Depends(require("requests:reject")),
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
def cancel(request_id: RequestId, who: Identity = Depends(require("requests:cancel")), c: AppContext = Depends(ctx)) -> dict:
    """The requester, or an operator, withdraws a request before its PR is open."""
    with c.db.session() as s:
        repo = RequestRepo(s)
        row = repo.get(request_id)
        c.cfg.roles.require(who, "requests:cancel", row.env)
        repo.move(row, E.CANCEL, who.username, actor_is_requester=row.requester_username == who.username,
                  actor_is_operator=bool({"cmapi-operator", "cmapi-admin"} & who.roles))
        AuditRepo(s).record(who, "request.cancel", request_id, None)
        return request_view(repo, row)


@router.write("/requests/{request_id}:retry", summary="Retry a failed request", permission="requests:retry",
              response_model=ChangeRequest, status_code=200,
              problems=["object-not-found", "invalid-transition", "change-pending"])
def retry(request_id: RequestId, who: Identity = Depends(require("requests:retry")), c: AppContext = Depends(ctx)) -> dict:
    """From failed: re-takes the namespace lock (409 if another request holds it) and opens the PR again.
    From sync_failed: watches the sync again, or for a delete, looks for the pruned namespace again."""
    with c.db.session() as s:
        repo, jobs = RequestRepo(s), JobRepo(s)
        row = repo.get(request_id)
        c.cfg.roles.require(who, "requests:retry", row.env)
        before = row.status
        after = repo.move(row, E.RETRY, who.username, "retry requested")
        row.attempts = 0
        AuditRepo(s).record(who, "request.retry", request_id, {"from": before})
        if after is S.APPROVED:
            jobs.enqueue("open_pr", request_id=request_id, cluster_id=row.cluster_id)
        elif row.action == "delete":                       # sync_failed after a prune that could not be confirmed
            jobs.enqueue("prune", request_id=request_id, cluster_id=row.cluster_id)
        else:
            jobs.enqueue("watch_sync", request_id=request_id, cluster_id=row.cluster_id, payload={"since": utcnow().isoformat()})
        return request_view(repo, row)


@router.write("/requests/{request_id}:revert", summary="Revert a sync-failed request", permission="requests:retry",
              response_model=ChangeRequest, status_code=200,
              problems=["object-not-found", "invalid-transition", "change-pending"])
def revert(request_id: RequestId, who: Identity = Depends(require("requests:retry")), c: AppContext = Depends(ctx)) -> dict:
    """Queues the revert of a sync_failed request: the worker marks it reverted and opens a new request that
    restores the folder as it was before the plan, through the same approval rules, in one transaction. The new
    request's ID is in the events."""
    with c.db.session() as s:
        repo, jobs = RequestRepo(s), JobRepo(s)
        row = repo.get(request_id)
        c.cfg.roles.require(who, "requests:retry", row.env)
        transition(S(row.status), E.REVERT)                    # 409 invalid-transition unless sync_failed
        repo.event(row, "revert_requested", who.username, "")
        AuditRepo(s).record(who, "request.revert", request_id, None)
        jobs.enqueue("open_revert", request_id=request_id, cluster_id=row.cluster_id, payload={"by": who.username})
        return request_view(repo, row)
