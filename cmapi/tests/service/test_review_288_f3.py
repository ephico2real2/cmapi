"""PR #288 review, F3: GET /requests/{id}/approval-status answers "approved (or further along)" for the CI cmapi check. applied
and merge_failed (#286) come after pr_open and before merged, so a check that CI runs on the PR then (a PR that the merge job
opened again after a person closed it, with host CI on) must read approved, or the merge is refused while the cluster holds the
change. On b660758 the list is ("approved", "pr_open", "merged", "awaiting_prune", "synced")."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from test_flow import NS, OLA, auth, run_jobs


@pytest.mark.parametrize("state", ["applied", "merge_failed"])
def test_a_request_applied_before_its_merge_is_approved_for_the_ci_check(world, state):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    run_jobs(ctx, limit=3)
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status=:st where request_id=:r"), {"st": state, "r": rid})
    r = client.get(f"/api/v1/requests/{rid}/approval-status", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == state and r.json()["approved"] is True, r.json()
