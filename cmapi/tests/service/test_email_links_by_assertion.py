"""The same claim as test_email_links.py, through channels_for alone, so that the old code fails on the link's text (#222)."""
from __future__ import annotations

import pytest

from cmapi.core.channels import channels_for

REQUEST = {"requestId": "req-20261114-0001", "action": "create", "namespace": "payments-prod", "clusterId": "OCP_P1", "env": "prod",
           "approval": {"reasons": ["prod create: 1 from approver-prod"]},
           "requester": {"requester": {"username": "ola", "email": "ola@ephico2real.com"}}}


@pytest.mark.parametrize("instance", ["prod", "staging", "emea-lab"])
def test_the_running_instance_names_both_links(world, monkeypatch, instance):
    client, ctx, git, kube, validator, keys = world
    monkeypatch.setitem(ctx.integrations, "notifier", {"smtp": {"host": "smtp.test"}})
    monkeypatch.setattr(ctx.cfg, "name", instance)
    monkeypatch.setitem(ctx.cfg.raw_instance["instance"], "portalUrl", "https://portal.example.com/")
    email = next(c for c in channels_for(ctx) if c.name == "email")
    sent = []
    monkeypatch.setattr(email, "_send", lambda to, subject, body: sent.append(body))
    link_id = email.notify_pending(REQUEST, ["approver-prod"])["linkId"]
    email.notify_decision(REQUEST, "approved")
    assert f"https://portal.example.com/#{instance}/approvals?request=req-20261114-0001&link={link_id}" in sent[0]
    assert f"https://portal.example.com/#{instance}/requests?request=req-20261114-0001" in sent[1]
    assert "#nonprod" not in "".join(sent)
