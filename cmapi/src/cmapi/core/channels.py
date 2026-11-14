"""ApprovalChannel adapters (core/ports.py): portal (default) and email.

The email channel sends a message with a signed, single-use link that opens the request in the
portal; the email itself never approves. SMTP comes from integrations.yaml (notifier.smtp) with
the credentials from the environment; without SMTP only the portal channel is active.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import smtplib
import time
from email.message import EmailMessage
from typing import Any, Mapping

from cmapi.core.authz import DEFAULT_GROUP_PATH, group_path
from cmapi.core.observability import log


class PortalChannel:
    name = "portal"

    def __init__(self, group_path_template: str = DEFAULT_GROUP_PATH):
        self.group_path_template = group_path_template

    def notify_pending(self, request: Mapping[str, Any], groups: list[str]) -> dict[str, Any]:
        return {"recipients": [group_path(g, self.group_path_template) for g in groups], "where": "the Approvals tab"}

    def notify_decision(self, request: Mapping[str, Any], decision: str) -> dict[str, Any]:
        return {"recipients": [request["requester"]["requester"]["username"]], "where": "the Requests tab", "decision": decision}


class EmailChannel:
    name = "email"

    def __init__(self, smtp: Mapping[str, Any], portal_url: str, link_key: bytes, group_mail: Mapping[str, str], instance: str):
        self.smtp, self.portal_url, self.key, self.group_mail = smtp, portal_url.rstrip("/"), link_key, group_mail
        # The portal's address has the instance first (#<instance>/<tab>). It is this instance's own name, never a literal:
        # an instance and its environments have the names that the owner gives them (#222).
        self.instance = instance

    def _link(self, request_id: str) -> tuple[str, str]:
        issued = str(int(time.time()))
        mac = hmac.new(self.key, f"{request_id}:{issued}".encode(), hashlib.sha256).hexdigest()[:24]
        link_id = f"{issued}.{mac}"
        return link_id, f"{self.portal_url}/#{self.instance}/approvals?request={request_id}&link={link_id}"

    def _send(self, to: list[str], subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.smtp.get("from", "cmapi@ephico2real.com")
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content(body)
        host, port = self.smtp.get("host", "localhost"), int(self.smtp.get("port", 25))
        with smtplib.SMTP(host, port, timeout=10) as conn:
            if self.smtp.get("starttls"):
                conn.starttls()
            user, password = os.environ.get("CMAPI_SMTP_USER"), os.environ.get("CMAPI_SMTP_PASSWORD")
            if user and password:
                conn.login(user, password)
            conn.send_message(msg)

    def notify_pending(self, request: Mapping[str, Any], groups: list[str]) -> dict[str, Any]:
        to = [self.group_mail.get(g, f"cmapi-{g}@{self.smtp.get('domain', 'ephico2real.com')}") for g in groups]
        link_id, url = self._link(request["requestId"])
        self._send(to, f"[cmapi] {request['action']} {request['namespace']} on {request['clusterId']} needs your approval",
                   f"Request {request['requestId']} ({request['action']} {request['namespace']}, {request['env']}) is waiting.\n"
                   f"Reasons: {', '.join(request['approval']['reasons']) if request.get('approval') else '-'}\n\n"
                   f"Open it in the portal: {url}\n\nThis link opens the request; approving happens in the portal with your own sign-in.")
        log.info("email_sent", request_id=request["requestId"], recipient_count=len(to), kind="pending")
        return {"recipients": to, "linkId": link_id}

    def notify_decision(self, request: Mapping[str, Any], decision: str) -> dict[str, Any]:
        email = request["requester"]["requester"].get("email")
        if not email:
            return {"recipients": [], "skipped": "requester has no email"}
        self._send([email], f"[cmapi] {request['requestId']} {decision}",
                   f"Your request {request['requestId']} ({request['action']} {request['namespace']}) is {decision}.\n"
                   f"Follow it: {self.portal_url}/#{self.instance}/requests?request={request['requestId']}")
        return {"recipients": [email], "decision": decision}


def channels_for(ctx: Any) -> list[Any]:
    out: list[Any] = [PortalChannel(ctx.cfg.approvals.group_path)]
    notifier = (ctx.integrations.get("notifier") or {})
    smtp = notifier.get("smtp")
    if smtp and smtp.get("host"):
        out.append(EmailChannel(smtp, ctx.cfg.raw_instance["instance"].get("portalUrl", ""),
                                (ctx.settings.link_key or "unset-link-key").encode(), notifier.get("groupMail") or {},
                                instance=ctx.cfg.name))
    return out
