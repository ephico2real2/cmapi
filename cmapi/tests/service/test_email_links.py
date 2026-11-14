"""The links of the email channel name the instance that sent the message (#222)."""
from __future__ import annotations

import pytest

from cmapi.core.channels import EmailChannel, channels_for

REQUEST = {"requestId": "req-20261114-0001", "action": "create", "namespace": "payments-prod", "clusterId": "OCP_P1", "env": "prod",
           "approval": {"reasons": ["prod create: 1 from approver-prod"]},
           "requester": {"requester": {"username": "ola", "email": "ola@ephico2real.com"}}}


@pytest.mark.parametrize("instance", ["prod", "staging", "nonprod", "emea-lab"])
def test_each_link_opens_the_view_of_the_instance_that_sent_it(instance, monkeypatch):
    sent = []
    channel = EmailChannel({"host": "smtp.test"}, "https://portal.example.com/", b"k", {}, instance=instance)
    monkeypatch.setattr(channel, "_send", lambda to, subject, body: sent.append(body))
    link_id = channel.notify_pending(REQUEST, ["approver-prod"])["linkId"]
    channel.notify_decision(REQUEST, "approved")
    assert f"https://portal.example.com/#{instance}/approvals?request=req-20261114-0001&link={link_id}" in sent[0]
    assert f"https://portal.example.com/#{instance}/requests?request=req-20261114-0001" in sent[1]
    assert [body.count("/#") for body in sent] == [1, 1]
    if instance != "nonprod":
        assert "#nonprod" not in "".join(sent)


def test_the_running_instance_gives_its_own_name_to_the_channel(world):
    client, ctx, git, kube, validator, keys = world
    ctx.integrations["notifier"] = {"smtp": {"host": "smtp.test"}}
    ctx.cfg.name = "prod"
    email = next(c for c in channels_for(ctx) if c.name == "email")
    assert email.instance == "prod" and "/#prod/approvals?" in email._link("req-1")[1]
