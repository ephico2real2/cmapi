"""Fable's review of #240, F1: in audit, a Kyverno finding is a warning at the PR check too, so an approved request merges."""
from __future__ import annotations

from test_flow import AMY, NS, OLA, auth, run_jobs
from test_policy_modes_api import URL, world_with  # noqa: F401  (the fixture)


def test_audit_an_approved_request_with_a_kyverno_warning_merges(world_with):
    client, ctx, git, kube, validator, keys = world_with({"mode": "audit"})
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    rid = r.json()["requestId"]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={"comment": "warning read"}, headers=auth(keys, "amy", **AMY))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "synced", [(e["event"], e.get("note")) for e in view["events"]]
    statuses = next(iter(git.statuses.values()))
    assert statuses["ci/kyverno"] == "success" and statuses["cmapi/check"] == "success"
    ci = next(e for e in view["events"] if e["event"] == "ci")
    assert "kyverno: audit" in ci["note"], ci


def test_enforce_a_kyverno_finding_at_the_pr_check_still_fails_the_request(world_with):
    """The other side: a finding that appears only at the PR check (the head was changed) fails the request in enforce."""
    client, ctx, git, kube, validator, keys = world_with({"mode": "off"}, kyverno=False)
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    rid = r.json()["requestId"]
    from cmapi.core.ports import Finding

    class Refusing:
        def validate(self, files, cluster_id, environment, previous=None):
            return [Finding("kyverno", "require-team-metadata", "", "team missing")]
    ctx.pipeline.validator = Refusing()
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "failed", view["events"]


import pytest


@pytest.mark.parametrize("policy", [{"engine": "none"}, {"mode": "off"}], ids=["engine-none", "mode-off"])
def test_with_no_kyverno_binary_a_request_plans_is_approved_and_syncs(world_with, policy):
    """The owner: "the cmapi would work with or without kyverno". PATH holds a stub kubeconform and the system tools only."""
    import shutil
    client, ctx, git, kube, validator, keys = world_with(policy, kyverno=False)
    assert shutil.which("kyverno") is None
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{r.json()['requestId']}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "synced", view["events"]
    assert client.get("/api/v1/admin/integrations", headers=auth(keys, "ola", **OLA)).json()["policy"]["environments"] == \
        {"dev": "off", "rnd": "off"}
