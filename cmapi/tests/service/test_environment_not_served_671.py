"""#671: every 422 environment-not-served names the instance that serves the environment.

docs/02, "Problems": "the body carries instanceUrl and portalUrl of the instance that serves it". The service suite's instance
is nonprod (rnd, dev), and its instance.yaml `directory` sends qa and uat to staging and prod to prod, with no portalUrl. A
member that the directory does not give is left out, never null (RFC 9457, section 3.2; core/config.py, environment_not_served).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cmapi.core.errors import Problem
from cmapi.core.pipeline import Pipeline

PROD = "https://cmapi.ephico2real.com"
STAGING = "https://cmapi-staging.ephico2real.com"
STAGING_PORTAL = "https://portal-staging.ephico2real.com"
VIEWER = dict(roles=["cmapi-viewer"], groups=["/cmapi/app-cmapi-rbac-viewer"])


def refusal(client, keys, url: str) -> dict:
    r = client.get(url, headers={"Authorization": f"Bearer {keys.token('vera', **VIEWER)}"})
    assert r.status_code == 422, r.text
    problem = r.json()
    assert problem["code"] == "environment-not-served", problem
    return problem


def with_staging_portal(ctx, monkeypatch) -> None:
    monkeypatch.setitem(ctx.cfg.raw_instance["instance"]["directory"]["staging"], "portalUrl", STAGING_PORTAL)


# ---------------------------------------------------------------- GET /api/v1/capacity (plugins/capacity/router.py)

def test_capacity_names_the_instance_that_serves_the_environment(world):
    client, ctx, git, kube, validator, keys = world
    problem = refusal(client, keys, "/api/v1/capacity?env=prod")
    assert problem["instanceUrl"] == PROD
    assert "portalUrl" not in problem, "the directory's prod entry has no portalUrl: the member is left out, not null"
    assert problem["detail"] == "prod is not served by the nonprod instance"


def test_capacity_carries_the_portal_url_when_the_directory_gives_one(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    with_staging_portal(ctx, monkeypatch)
    problem = refusal(client, keys, "/api/v1/capacity?env=qa")
    assert (problem["instanceUrl"], problem["portalUrl"]) == (STAGING, STAGING_PORTAL)


def test_capacity_leaves_both_out_for_an_environment_no_instance_serves(world):
    client, ctx, git, kube, validator, keys = world
    problem = refusal(client, keys, "/api/v1/capacity?env=sandbox")
    assert "instanceUrl" not in problem and "portalUrl" not in problem, problem


# ---------------------------------------------------------------- GET /api/v1/tiers (core/tiers.py TierCatalog._need_env)

def test_tiers_names_the_instance_that_serves_the_environment(world, monkeypatch):
    client, ctx, git, kube, validator, keys = world
    with_staging_portal(ctx, monkeypatch)
    problem = refusal(client, keys, "/api/v1/tiers?environment=qa")
    assert (problem["instanceUrl"], problem["portalUrl"]) == (STAGING, STAGING_PORTAL)
    assert problem["detail"] == "qa is not served by the nonprod instance"


# ---------------------------------------------------------------- approvals (core/approvals.py ApprovalRules.decide)

def test_the_approval_decision_names_the_instance_that_serves_the_environment(world, monkeypatch):
    """Pipeline._decide is the one caller of ApprovalRules.decide: the request path, the submit and the revert job
    (jobs/open_pr.py), whose row may name an environment that a later configuration no longer serves."""
    client, ctx, git, kube, validator, keys = world
    with_staging_portal(ctx, monkeypatch)
    with pytest.raises(Problem) as caught:
        ctx.pipeline._decide({"plugin": "namespaces", "action": "update", "environment": "uat", "namespace": "payments-uat"})
    assert (caught.value.status, caught.value.code) == (422, "environment-not-served")
    assert caught.value.extra == {"instanceUrl": STAGING, "portalUrl": STAGING_PORTAL}


# ---------------------------------------------------------------- the request path (core/pipeline.py check_env_served)

def test_the_request_path_leaves_out_what_the_directory_does_not_give():
    cfg = SimpleNamespace(allowed_environments={"rnd", "dev"}, name="nonprod", raw_instance={
        "instance": {"directory": {"prod": {"environments": ["prod"], "url": PROD}}}})
    pipeline = SimpleNamespace(cfg=cfg)
    with pytest.raises(Problem) as caught:
        Pipeline.check_env_served(pipeline, "prod")
    assert caught.value.extra == {"instanceUrl": PROD}
    with pytest.raises(Problem) as caught:
        Pipeline.check_env_served(pipeline, "sandbox")
    assert caught.value.extra == {}
