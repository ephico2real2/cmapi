"""#212 through the API and the worker: each plan and each PR check gives the validator the folder that Git already
holds, so a rendered policy can keep a value that was approved before it (core/validate, D9 of the decision record)."""
from __future__ import annotations

from test_flow import NS, OLA, auth, run_jobs

FOLDER = "clusters/CRC/namespaces/payments-dev/"


def test_the_plan_and_the_pr_check_give_the_validator_the_folder_git_holds(world):
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    run_jobs(ctx)
    # A create: nothing in Git yet, at plan time and on the default branch at the PR check.
    assert validator.previous == [{}, {}]
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    r = client.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"},
                     headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    merged = {p: t for p, t in git.branches["main"].items() if p.startswith(FOLDER)}
    plan_time, pr_check = validator.previous[2], validator.previous[3]
    # The change is checked against the folder that the create merged, small tier and all.
    assert set(plan_time) == set(pr_check) and FOLDER + "resourcequota.yaml" in plan_time
    assert "tier: small" in plan_time[FOLDER + "namespace.yaml"]
    assert "tier: medium" in merged[FOLDER + "namespace.yaml"]

