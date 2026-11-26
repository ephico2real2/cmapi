"""The revert's inverse, hardened where it predates PR #722 (reviewer 2 of #722; Codex's findings H2, M1 and M4 on the
change path). docs/01, the state reverted: "the revert is a new request through the same approval rules".

- The cluster as a plan reads it: a cluster moved to another environment, or with writes off, is refused; the :revert was
  authorized for the request's environment (routers/requests.py, requests:retry on row.env).
- A restore that changes the expiry is judged as the request that would change it: a restored permanent Namespace over a
  dated one is a :makePermanent, which adds approver-platform (docs/01, Namespace expiration).
- A restored change carries the validator's findings to the approvers, as a planned change does.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from cmapi.core.pipeline import utc_today
from cmapi.core.ports import Finding
from test_catalog_drift_710 import BASE, LABEL, ONE, created, patch
from test_expirations import write
from test_flow import OLA, auth, run_jobs
from test_revert_inverse_policy import deleted, facts_of, revert_once, view


@pytest.mark.parametrize("change", [{"environment": "rnd"}, {"writes": False}])
def test_a_revert_on_a_cluster_that_moved_is_refused(world, change):
    client, ctx, git, kube, validator, keys = world
    gone = deleted(world)
    st = ctx.registry.get("CRC")
    st.policy = replace(st.policy, **change)
    assert revert_once(world, gone) is None
    after = view(world, gone)
    assert after["status"] == "sync_failed"
    assert any(e["event"] == "error" and ("rnd now" in e["note"] or "writes are off" in e["note"]) for e in after["events"])


def test_the_revert_of_a_set_is_a_make_permanent(world):
    """Forward :makePermanent of the dated namespace needs 1 approver-platform; the revert of its :set writes the same
    permanent Namespace back, and needs it too."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    tag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    r = write(client, keys, "set", {"until": (utc_today() + timedelta(days=10)).isoformat()}, tag.strip('"'))
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    tag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    forward = write(client, keys, "makePermanent", {}, tag.strip('"'), dry=True).json()["approval"]
    child = revert_once(world, r.json()["requestId"])
    v = view(world, child)
    assert v["approval"]["slots"] == forward["slots"] and v["approval"]["auto"] is None, v["approval"]
    facts = facts_of(world, child)
    assert (facts["expirationAction"], facts["expirationBeyondLimits"]) == ("makePermanent", True), facts


def test_the_revert_of_a_change_carries_the_findings(world):
    client, ctx, git, kube, validator, keys = world
    created(world)
    low = patch(world, LABEL, dry_run=False).json()["requestId"]
    run_jobs(ctx)
    validator.findings = [Finding("kyverno", "audit-rule", BASE + "namespace.yaml", "audit finding", "warning")]
    assert facts_of(world, revert_once(world, low))["warnings"] == ["audit finding"]
