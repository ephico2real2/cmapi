"""channel_notify: tell the approval channels about a pending request or a decision.

The portal channel is the Approvals tab and needs no message. The email channel sends a
signed, single-use link to the approving groups' mailboxes through the Notifier when SMTP is
configured (core/channels); until then every notification is recorded in approval_notifications
with channel=portal, so the Approvals tab can say how approvers were told."""
from __future__ import annotations

from sqlalchemy.orm import Session

from cmapi.core.channels import channels_for
from cmapi.core.context import AppContext
from cmapi.core.db.models import ApprovalNotificationRow, JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.views import request_view


def channel_notify(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    kind = (job.payload or {}).get("kind", "pending")
    view = request_view(repo, row, with_events=False)
    groups = [sl["group"] for sl in (row.requirement or {}).get("slots", [])]
    jobs.fence()                       # a message is an external side effect no rollback undoes: a stale worker sends none
    for ch in channels_for(ctx):
        try:
            detail = ch.notify_pending(view, groups) if kind == "pending" else ch.notify_decision(view, kind)
        except Exception as exc:                                     # noqa: BLE001 - one channel failing never stops another
            detail = {"error": str(exc)[:200]}
        s.add(ApprovalNotificationRow(request_id=row.request_id, channel=ch.name, kind=kind,
                                      recipients=list((detail or {}).get("recipients", [])), link_id=(detail or {}).get("linkId"),
                                      detail=detail))
    jobs.done(job)
