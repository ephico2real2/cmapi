"""Removing the last bound on services.nodeports or services.loadbalancers is network exposure (separate issue, found
reviewing PR #718).

docs/02, "Beyond the tier": networkExposure is "the new quota has more services.loadbalancers or services.nodeports than Git
holds". A quota that names no such key does not limit it: quota admission masks the requested usage to the quota's hard names
(kubernetes v1.34.0, staging/src/k8s.io/apiserver/pkg/admission/plugin/resourcequota/controller.go,
`requestedUsage := quota.Mask(deltaUsage, hardResources)`). Before the fix a missing key was read as 0, so a change or a
revert that removed services.nodeports "0" opened every NodePort with networkExposure false.
"""
from __future__ import annotations

import shutil

import pytest
import yaml
from sqlalchemy import text

from cmapi.core.db.models import ChangeRequestRow
from cmapi.worker import Worker
from conftest import build_world
from test_catalog_drift_710 import LABEL, QUOTA_FILE, created, patch
from test_flow import OPAL, auth, run_jobs


def test_a_change_that_drops_the_nodeport_bound_is_exposure(test_config, tmp_path, fresh_db, keys, monkeypatch):
    """The catalog no longer gives services.nodeports; Git holds "0". A label change renders the quota without it."""
    config = tmp_path / "config"
    shutil.copytree(test_config, config)
    tiers = yaml.safe_load((config / "tiers.yaml").read_text())
    with build_world(config, keys, monkeypatch) as world:
        created(world)
        del tiers["defaults"]["quota"]["services.nodeports"]
        (config / "tiers.yaml").write_text(yaml.safe_dump(tiers, sort_keys=False))
        client, ctx, git, kube, validator, keys = world
        from cmapi.core.tiers import TierCatalog
        ctx.cfg.tiers = ctx.pipeline.renderer.catalog = TierCatalog(tiers, set(ctx.cfg.allowed_environments))
        plan = patch(world, LABEL, dry_run=True)
        assert plan.status_code == 200, plan.text
        assert "services.nodeports" not in yaml.safe_load(plan.json()["files"][QUOTA_FILE])["spec"]["hard"]
        assert any("networkExposure" in r for r in plan.json()["approval"]["reasons"]), plan.json()["approval"]


@pytest.mark.parametrize("key", ["services.nodeports", "services.loadbalancers"])
def test_a_revert_that_removes_the_nodeport_bound_is_exposure(world, key):
    """Git's quota had no services.nodeports (an older catalog); a label change rendered "0"; its revert removes it. The same
    for services.loadbalancers."""
    client, ctx, git, kube, validator, keys = world
    created(world)
    rq = yaml.safe_load(git.branches["main"][QUOTA_FILE])
    del rq["spec"]["hard"][key]
    git.branches["main"][QUOTA_FILE] = yaml.safe_dump(rq, sort_keys=False)
    git._sha("main")
    low = patch(world, LABEL, dry_run=False).json()["requestId"]
    run_jobs(ctx)
    assert yaml.safe_load(git.branches["main"][QUOTA_FILE])["spec"]["hard"][key] == "0"
    with ctx.db.session() as s:
        s.execute(text("update change_requests set status='sync_failed' where request_id=:r"), {"r": low})
    assert client.post(f"/api/v1/requests/{low}:revert", headers=auth(keys, "opal", **OPAL)).status_code == 200
    assert Worker(ctx, "w").run_one()
    child = next(e["note"] for e in client.get(f"/api/v1/requests/{low}", headers=auth(keys, "opal", **OPAL)).json()["events"]
                 if e["event"] == "revert_opened")
    with ctx.db.session() as s:
        assert s.get(ChangeRequestRow, child).plan["facts"]["networkExposure"] is True
