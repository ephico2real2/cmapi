"""Response bodies built from rows: the ChangeRequest view every request route returns."""
from __future__ import annotations

from typing import Any

from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.db.repo import RequestRepo, requirement_from_json
from cmapi.core.pipeline import approval_view
from cmapi.core.render.manifests import diff_files


def request_view(repo: RequestRepo, row: ChangeRequestRow, *, with_events: bool = True) -> dict[str, Any]:
    req = requirement_from_json(row.requirement)
    ledger = repo.ledger(row)
    plan = row.plan or {}
    pr = row.pr or None
    base = f"/api/v1/requests/{row.request_id}"
    links = {"self": base, "events": f"{base}/events"}
    if pr:
        links["pr"] = pr["url"]
    return {
        "requestId": row.request_id, "instance": row.instance, "clusterId": row.cluster_id, "namespace": row.namespace,
        "env": row.env, "plugin": row.plugin, "action": row.action, "reason": row.reason,
        "justification": row.justification, "status": row.status, "planHash": row.plan_hash, "baseSha": row.base_sha,
        # submittedBySub is a stable identifier the ledger needs (self-approval through onBehalfOf); it is not
        # part of the public contract, so it stays in the row and out of the response.
        "approval": approval_view(req, ledger), "requester": {k: v for k, v in row.requester.items() if k != "submittedBySub"},
        "pr": None if not pr else {"number": pr["number"], "url": pr["url"], "branch": pr["branch"], "head": pr["head"][:8]},
        "mergeSha": row.merge_sha and row.merge_sha[:8],
        "files": diff_files(plan.get("prev", {}), plan.get("files", {})),
        "events": [{"at": e.at, "event": e.event, "status": e.status, "by": e.by, "note": e.note}
                   for e in repo.events(row.request_id)] if with_events else [],
        "createdAt": row.created_at, "updatedAt": row.updated_at, "links": links,
    }
