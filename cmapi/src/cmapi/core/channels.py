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
from cmapi.core.clients.trust import trusted_context
from cmapi.core.observability import log

SMTP_TLS = ("starttls", "implicit")      # notifier.smtp.tls; there is no cleartext mode


class PortalChannel:
    name = "portal"

    def __init__(self, group_path_template: str = DEFAULT_GROUP_PATH):
        self.group_path_template = group_path_template

    def notify_pending(self, request: Mapping[str, Any], groups: list[str]) -> dict[str, Any]:
        return {"recipients": [group_path(g, self.group_path_template) for g in groups], "where": "the Approvals tab"}

    def notify_decision(self, request: Mapping[str, Any], decision: str) -> dict[str, Any]:
        return {"recipients": [request["requester"]["requester"]["username"]], "where": "the Requests tab", "decision": decision}


class EmailNotifier:
    """The Notifier port (core/ports.py) over SMTP: one message to a list of addresses. The approval email channel sends
    through it, and so do expire_check's notices to a team DL. The login comes from the environment, never the file.

    Every connection is TLS with a verified certificate, before the login and the message: RFC 8314, section 5.3, "MUAs MUST
    validate TLS server certificates". `notifier.smtp.tls` is `starttls` (the default) or `implicit` (TLS from the first
    byte, port 465, which RFC 8314 section 3 recommends); a relay without STARTTLS is refused, never used in clear text. The
    trust is the project's `trusted_context()` (core/clients/trust.py): PROTOCOL_TLS_CLIENT, so CERT_REQUIRED and the host
    name checked, over the image's system store and CMAPI_TRUSTED_CA_FILE. Not `ssl.create_default_context()`: the pods set
    SSL_CERT_FILE to Keycloak's CA alone, which it would trust instead (#434). And never smtplib's own default: `starttls()`
    with no context wraps the socket with `ssl._create_stdlib_context()`, which verifies nothing (CPython 3.12 smtplib)."""

    def __init__(self, smtp: Mapping[str, Any]):
        tls = smtp.get("tls", "starttls")
        if tls not in SMTP_TLS or smtp.get("starttls") is False:
            raise ValueError(f"notifier.smtp: tls must be one of {', '.join(SMTP_TLS)} and starttls cannot be false; "
                             "cmapi sends mail only over TLS with a verified certificate (RFC 8314)")
        self.smtp, self.tls = smtp, tls

    def _connect(self, host: str, port: int) -> smtplib.SMTP:
        context = trusted_context()
        if self.tls == "implicit":
            return smtplib.SMTP_SSL(host, port, timeout=10, context=context)
        conn = smtplib.SMTP(host, port, timeout=10)
        try:
            conn.starttls(context=context)      # SMTPNotSupportedError when the relay offers none: no message in clear
        except BaseException:
            conn.close()
            raise
        return conn

    def send(self, to: list[str], subject: str, body: str, links: Mapping[str, str] | None = None) -> None:
        msg = EmailMessage()
        msg["From"] = self.smtp.get("from", "cmapi@ephico2real.com")
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content(body + "".join(f"\n{name}: {url}" for name, url in (links or {}).items()))
        host = self.smtp.get("host", "localhost")
        port = int(self.smtp.get("port", 465 if self.tls == "implicit" else 25))
        conn = self._connect(host, port)
        try:
            user, password = os.environ.get("CMAPI_SMTP_USER"), os.environ.get("CMAPI_SMTP_PASSWORD")
            if user and password:
                conn.login(user, password)
            conn.send_message(msg)
            try:
                conn.quit()
            except (smtplib.SMTPException, OSError):
                # The relay took the message with its reply to DATA (RFC 5321, section 6.1): a QUIT that fails does not
                # undo that, and reporting it as a failure would send the message again.
                pass
        finally:
            conn.close()


def notifier_for(ctx: Any) -> EmailNotifier | None:
    """The Notifier for a message to a team DL, such as an expiry notice: email when integrations.yaml sets
    notifier.smtp.host. None without it: the notice is then recorded and shown on the portal's Expiration tab only."""
    smtp = (ctx.integrations.get("notifier") or {}).get("smtp")
    return EmailNotifier(smtp) if smtp and smtp.get("host") else None


class EmailChannel:
    name = "email"

    def __init__(self, smtp: Mapping[str, Any], portal_url: str, link_key: bytes, group_mail: Mapping[str, str], instance: str):
        self.smtp, self.portal_url, self.key, self.group_mail = smtp, portal_url.rstrip("/"), link_key, group_mail
        # The links name this instance, never a literal: an instance has the name that the owner gives it (#222). The
        # address #<instance>/<tab> is the demo build's (cmapi-portal-ui/src/model/usePortal.ts). The shipped portal reads
        # #<tab>?query (src/portal/route.ts), so these links open its first tab until #236 settles the address.
        self.instance = instance

    def _link(self, request_id: str) -> tuple[str, str]:
        issued = str(int(time.time()))
        mac = hmac.new(self.key, f"{request_id}:{issued}".encode(), hashlib.sha256).hexdigest()[:24]
        link_id = f"{issued}.{mac}"
        return link_id, f"{self.portal_url}/#{self.instance}/approvals?request={request_id}&link={link_id}"

    def _send(self, to: list[str], subject: str, body: str) -> None:
        EmailNotifier(self.smtp).send(to, subject, body)

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
