"""#253: storage LimitRanges through the API, with tiers.yaml's switch off (the default, in code) and turned on later or off
later. The world's tiers.yaml is the nonprod instance's, which carries no storageLimitRange key.

Before #253 the first two tests fail: the custom pvc value was taken and rendered into the single <ns>-limits object.
"""
from __future__ import annotations

import yaml

from test_custom_tier_change import (LR, NS, ONE, OLA, RQ, URL, approve_and_sync, auth, catalog_with, changed,
                                     custom, patch, rendered)
from test_flow import run_jobs


def test_with_the_switch_off_a_custom_storage_limit_is_refused_and_nothing_is_recorded(world):
    client, ctx, git, kube, validator, keys = world
    body = custom(limitRange={"pvc": {"max": {"storage": "100Gi"}}})
    for dry in ("?dryRun=true", ""):
        r = client.post(URL + dry, json=body, headers=auth(keys, "ola", **OLA))
        assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
        assert r.json()["errors"] == [{"code": "storage-limits-off", "keys": ["limitRange.pvc.max.storage"],
                                       "environment": "dev"}], r.text
        assert "Storage limits are off in environment dev" in r.json()["detail"]
    assert client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"] == 0


def test_with_the_switch_off_the_namespace_gets_two_limitranges_and_reaches_the_cluster(world):
    client, ctx, git, kube, validator, keys = world
    dry = client.post(URL + "?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA)).json()
    assert changed(dry) == sorted([LR("cpu"), LR("memory"), "namespace.yaml", RQ, "token-issuer-rolebinding.yaml"])
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    ns = NS["namespace"]
    on_cluster = sorted(name for kind, n, name in kube.objects if kind == "LimitRange" and n == ns)
    assert on_cluster == [f"{ns}-limits-cpu", f"{ns}-limits-memory"]
    assert kube.objects[("LimitRange", ns, f"{ns}-limits-cpu")]["spec"]["limits"] == [
        {"type": "Container", "defaultRequest": {"cpu": "100m"}, "default": {"cpu": "500m"}, "max": {"cpu": "2"}}]


def test_the_catalog_view_says_whether_storage_limits_are_on(world):
    client, ctx, git, kube, validator, keys = world
    view = lambda: client.get("/api/v1/tiers?environment=dev", headers=auth(keys, "ola", **OLA)).json()
    assert view()["environments"]["dev"]["storageLimitRange"] == {"enabled": False}
    catalog_with(world)                                                 # the operator sets the override to true
    assert view()["environments"]["dev"]["storageLimitRange"] == {"enabled": True}


def test_a_namespace_approved_with_a_storage_limit_still_changes_after_the_switch_goes_off(world):
    """The switch goes off after a storage limit was approved: a label change is not refused, and its plan removes
    <ns>-limits-storage. A new storage value is refused."""
    client, ctx, git, kube, validator, keys = world
    catalog_with(world)
    r = client.post(URL, json=custom(limitRange={"pvc": {"max": {"storage": "100Gi"}}}), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    approve_and_sync(world, r.json()["requestId"], approvals=2)
    etag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    from pathlib import Path
    from cmapi.core.tiers import TierCatalog
    off = yaml.safe_load((Path(ctx.settings.config_dir) / "tiers.yaml").read_text())
    ctx.cfg.tiers = ctx.pipeline.renderer.catalog = TierCatalog(off, set(ctx.cfg.allowed_environments))
    plan = patch(world, etag, {"labels": {"cmapi.net/cost-center": "cc-9000"}})
    assert plan.status_code == 200, plan.text
    removed = [p.rsplit("/", 1)[1] for p, s in plan.json()["changes"].items() if s == "removed"]
    assert removed == [LR("storage")] and plan.json()["beyondTier"] is None
    assert all(not p.endswith(LR("storage")) for p, t in plan.json()["files"].items() if t)
    refused = patch(world, etag, {"limitRange": {"pvc": {"max": {"storage": "90Gi"}}}})
    assert refused.status_code == 422 and refused.json()["errors"][0]["code"] == "storage-limits-off", refused.text


def test_quota_and_limits_keep_their_values_when_only_the_cpu_limit_changes(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json=custom(), headers=auth(keys, "ola", **OLA))
    approve_and_sync(world, r.json()["requestId"], approvals=1)
    etag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]
    plan = patch(world, etag, {"limitRange": {"container": {"max": {"cpu": "3"}}}}).json()
    assert changed(plan) == [LR("cpu")]                       # the quota and the memory object are not touched
    assert rendered(plan["files"], LR("cpu"))["spec"]["limits"][0]["max"] == {"cpu": "3"}
    assert not any(p.endswith((LR("memory"), RQ)) for p in plan["files"])
