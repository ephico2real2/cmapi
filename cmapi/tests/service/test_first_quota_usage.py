"""The first quota of a namespace reads no live usage (separate issue, found reviewing PR #714).

docs/01, "Thanos on onboarding": "Never queried while creating a namespace or setting its first quota." A change of a
namespace whose folder holds no ResourceQuota (an adopted one, D16: "A later quota request adds the object", or a hand edit)
sets its first quota. Before the fix it read the live usage, and with Thanos down the plan carried usage: unavailable,
which adds approver-platform.
"""
from __future__ import annotations

from unittest.mock import Mock

from cmapi.capacity.usage import NamespaceUsage
from test_catalog_drift_710 import LABEL, NAME, OWN, QUOTA_FILE, created, patch, rendered_by_an_older_catalog

DOWN = NamespaceUsage("unavailable", "Thanos did not answer", None)


def thanos_down(world, monkeypatch) -> Mock:
    client, ctx, git, kube, validator, keys = world
    usage = Mock()
    usage.namespace.return_value = DOWN
    monkeypatch.setattr(ctx.pipeline, "usage", usage)
    return usage


def test_the_first_quota_reads_no_live_usage(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    created(world)
    del git.branches["main"][QUOTA_FILE]
    git._sha("main")
    kube.delete("ResourceQuota", NAME, OWN)
    usage = thanos_down(world, monkeypatch)
    plan = patch(world, LABEL, dry_run=True)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["changes"][QUOTA_FILE] == "added", body["changes"]
    assert usage.namespace.call_count == 0
    assert body["usage"] is None and body["approval"]["slots"] == [], body["approval"]


def test_a_change_of_a_quota_that_git_holds_still_reads_it(world, monkeypatch):
    """The other side: Git holds 1 CPU and the change renders 8, so the live read runs, and Thanos down adds approver-platform."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    rendered_by_an_older_catalog(world, {"requests.cpu": "1"})
    usage = thanos_down(world, monkeypatch)
    plan = patch(world, LABEL, dry_run=True)
    assert plan.status_code == 200, plan.text
    assert usage.namespace.call_count == 1
    assert any("usage" in reason for reason in plan.json()["approval"]["reasons"]), plan.json()["approval"]
