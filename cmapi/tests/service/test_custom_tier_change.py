"""A custom-tier namespace: values beyond the tier (#211), and a change of the namespace after its creation (#214).

Each test runs the API on the fakes of conftest.py: no cluster admits the rendered LimitRange or ResourceQuota here.
"""
from __future__ import annotations

import pytest
import yaml

from test_flow import AMY, NS, OLA, auth, run_jobs

SIZES = {"requests.cpu": "4", "requests.memory": "8Gi", "pods": "20"}
LIMITS = {"container": {"default": {"cpu": "1", "memory": "1Gi"}, "max": {"cpu": "4", "memory": "8Gi"}},
          "pvc": {"max": {"storage": "100Gi"}}}
LIMIT_KEYS = ["limitRange.container.default.cpu", "limitRange.container.default.memory", "limitRange.container.max.cpu",
              "limitRange.container.max.memory", "limitRange.pvc.max.storage"]
URL = "/api/v1/clusters/CRC/namespaces"
ONE = f"{URL}/{NS['namespace']}"
PLATFORM = ("amy", "pat", "pia")          # three people of approver-platform
BEYOND = {"group": "approver-platform", "count": 1, "reason": "Value beyond the tier"}
EXPOSURE = {"group": "approver-platform", "count": 1, "reason": "Network exposure"}


def custom(**extra) -> dict:
    return {**NS, "tier": "custom", "quota": SIZES, **extra}


def approve_and_sync(world, rid: str, approvals: int) -> None:
    client, ctx, git, kube, validator, keys = world
    for n, approver in enumerate(PLATFORM[:approvals], start=1):
        a = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, approver, **AMY))
        assert a.status_code == 200, a.text
        assert a.json()["status"] == ("approved" if n == approvals else "pending_approval"), a.text
    run_jobs(ctx)
    assert client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()["status"] == "synced"


def synced(world, body: dict, approvals: int) -> str:
    """Create the namespace, approve it and sync it. Returns its etag."""
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json=body, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    approve_and_sync(world, r.json()["requestId"], approvals)
    return client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]


def patch(world, etag: str, body: dict, dry_run: bool = True):
    client, ctx, git, kube, validator, keys = world
    return client.patch(ONE + ("?dryRun=true" if dry_run else ""), json=body, headers={**auth(keys, "ola", **OLA), "If-Match": etag})


def rendered(files: dict[str, str], name: str) -> dict:
    return yaml.safe_load(next(text for path, text in files.items() if path.endswith("/" + name)))


def changed(plan: dict) -> list[str]:
    return sorted(path.rsplit("/", 1)[1] for path in plan["changes"])


# ---- #211: custom container limits, with approval as the gate

def test_the_dry_run_names_the_keys_beyond_the_tier_and_the_approval_they_add(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL + "?dryRun=true", json=custom(limitRange=LIMITS), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    plan = r.json()
    assert [k["key"] for k in plan["beyondTier"]["keys"]] == LIMIT_KEYS
    assert plan["beyondTier"]["keys"][2] == {"key": "limitRange.container.max.cpu", "tier": "2", "requested": "4"}
    assert plan["beyondTier"]["approvals"] == [BEYOND]
    assert plan["approval"]["slots"][0]["group"] == "approver-platform" and plan["approval"]["slots"][0]["count"] == 2
    assert plan["approval"]["auto"] is None
    lr = rendered(plan["files"], "limitrange.yaml")
    assert lr["spec"]["limits"] == [
        {"type": "Container", "defaultRequest": {"cpu": "100m", "memory": "256Mi"}, "default": {"cpu": "1", "memory": "1Gi"},
         "max": {"cpu": "4", "memory": "8Gi"}},
        {"type": "PersistentVolumeClaim", "max": {"storage": "100Gi"}}]
    assert lr["metadata"]["annotations"]["cmapi.net/beyond-tier"] == ",".join(LIMIT_KEYS)
    assert "cmapi.net/beyond-tier" not in rendered(plan["files"], "resourcequota.yaml")["metadata"]["annotations"]


def test_a_custom_request_with_no_value_beyond_the_tier_has_no_extra_approval(world):
    client, ctx, git, kube, validator, keys = world
    plan = client.post(URL + "?dryRun=true", json=custom(), headers=auth(keys, "ola", **OLA)).json()
    assert plan["beyondTier"] is None
    assert [(s["group"], s["count"]) for s in plan["approval"]["slots"]] == [("approver-platform", 1)]
    # the tier's own values, sent in full, are not beyond the tier
    same = {"container": {"max": {"cpu": "2000m", "memory": "4096Mi"}}, "pvc": {"max": {"storage": "50Gi"}}}
    plan = client.post(URL + "?dryRun=true", json=custom(limitRange=same), headers=auth(keys, "ola", **OLA)).json()
    assert plan["beyondTier"] is None and plan["approval"]["slots"][0]["count"] == 1


def test_custom_limits_wait_for_the_extra_approval_and_then_reach_the_cluster(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json=custom(limitRange=LIMITS), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    req = r.json()
    assert req["approval"]["remaining"] == [{"group": "approver-platform", "needed": 2}]
    assert [k["key"] for k in req["beyondTier"]["keys"]] == LIMIT_KEYS and req["beyondTier"]["approvals"] == [BEYOND]
    approve_and_sync(world, req["requestId"], approvals=2)
    limits = kube.objects[("LimitRange", NS["namespace"], f"{NS['namespace']}-limits")]
    assert limits["spec"]["limits"][0]["max"] == {"cpu": "4", "memory": "8Gi"}
    assert limits["metadata"]["annotations"]["cmapi.net/request-id"] == req["requestId"]
    view = client.get(f"/api/v1/requests/{req['requestId']}", headers=auth(keys, "amy", **AMY)).json()
    assert [k["key"] for k in view["beyondTier"]["keys"]] == LIMIT_KEYS       # the approver's view names them too


@pytest.mark.parametrize("body,code", [
    ({**NS, "tier": "small", "limitRange": LIMITS}, "limits-with-named-tier"),
    (custom(limitRange={"container": {"min": {"cpu": "10m"}}}), "limit-key-not-overridable"),
    (custom(limitRange={"pvc": {"max": {"storage": "600Gi"}}}), "custom-out-of-bounds"),
    (custom(limitRange={"container": {"default": {"cpu": "3"}}}), "limit-order-invalid"),
    (custom(limitRange={"container": {"defaultRequest": {"cpu": "750m"}}}), "limit-order-invalid"),
    (custom(limitRange={"container": {"max": {"cpu": "6"}}}), "limit-exceeds-quota"),
    (custom(quota={**SIZES, "limits.cpu": "8"}), "quota-key-not-sizable"),
    (custom(quota={**SIZES, "services.nodeports": "11"}), "custom-out-of-bounds"),
])
def test_a_value_that_is_not_valid_is_refused_and_nothing_is_recorded(world, body, code):
    client, ctx, git, kube, validator, keys = world
    for dry in ("?dryRun=true", ""):
        r = client.post(URL + dry, json=body, headers=auth(keys, "ola", **OLA))
        assert r.status_code == 422 and r.json()["code"] == "policy-violation", r.text
        assert [e["code"] for e in r.json()["errors"]] == [code]
    assert client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"] == 0


def test_a_limit_that_is_not_a_quantity_is_refused(world):
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL + "?dryRun=true", json=custom(limitRange={"container": {"max": {"cpu": "lots"}}}), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 422 and r.json()["code"] == "validation-failed", r.text
    assert "not a Kubernetes quantity: 'lots'" in r.json()["detail"], r.text


def test_storage_beyond_the_tier_is_on_the_quota_object(world):
    client, ctx, git, kube, validator, keys = world
    quota = {**SIZES, "requests.storage": "500Gi", "persistentvolumeclaims": "40"}
    plan = client.post(URL + "?dryRun=true", json=custom(quota=quota), headers=auth(keys, "ola", **OLA)).json()
    assert plan["beyondTier"]["keys"] == [{"key": "persistentvolumeclaims", "tier": "20", "requested": "40"},
                                          {"key": "requests.storage", "tier": "200Gi", "requested": "500Gi"}]
    assert plan["beyondTier"]["approvals"] == [BEYOND]
    rq = rendered(plan["files"], "resourcequota.yaml")
    assert rq["spec"]["hard"]["requests.storage"] == "500Gi" and rq["spec"]["hard"]["services.nodeports"] == "0"
    assert rq["metadata"]["annotations"]["cmapi.net/beyond-tier"] == "persistentvolumeclaims,requests.storage"


def test_a_load_balancer_needs_the_exposure_approval_too(world):
    client, ctx, git, kube, validator, keys = world
    quota = {**SIZES, "services.loadbalancers": "1", "services.nodeports": "2"}
    r = client.post(URL, json=custom(quota=quota), headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202, r.text
    req = r.json()
    assert req["beyondTier"]["approvals"] == [BEYOND, EXPOSURE]
    assert req["approval"]["remaining"] == [{"group": "approver-platform", "needed": 3}]
    assert any("networkExposure" in reason for reason in req["approval"]["reasons"])
    approve_and_sync(world, req["requestId"], approvals=3)
    hard = kube.objects[("ResourceQuota", NS["namespace"], f"{NS['namespace']}-quota")]["spec"]["hard"]
    assert hard["services.loadbalancers"] == "1" and hard["services.nodeports"] == "2"


def test_the_catalog_view_names_what_a_custom_request_can_change(world):
    client, ctx, git, kube, validator, keys = world
    body = client.get("/api/v1/tiers?environment=dev", headers=auth(keys, "ola", **OLA)).json()
    assert "limitRange.container.max.cpu" in body["overridable"] and "requests.storage" in body["overridable"]
    assert body["environments"]["dev"]["custom"]["max"]["limitRange.container.max.cpu"] == "16"


# ---- a change of a custom namespace (#214), and the overrides it keeps

def test_a_label_change_on_a_custom_namespace_keeps_its_quota(world):
    etag = synced(world, custom(), approvals=1)
    r = patch(world, etag, {"labels": {"cmapi.net/cost-center": "cc-9000"}})
    assert r.status_code == 200, r.text
    assert changed(r.json()) == ["namespace.yaml"]


def test_a_quota_change_on_a_custom_namespace_is_planned(world):
    etag = synced(world, custom(), approvals=1)
    r = patch(world, etag, {"quota": {"requests.cpu": "6"}})          # one key: merged over the values in Git
    assert r.status_code == 200, r.text
    assert changed(r.json()) == ["resourcequota.yaml"]
    hard = rendered(r.json()["files"], "resourcequota.yaml")["spec"]["hard"]
    assert hard["requests.cpu"] == "6" and hard["requests.memory"] == "8Gi" and hard["pods"] == "20"


def test_a_label_change_keeps_approved_overrides_and_asks_for_no_approval_again(world):
    etag = synced(world, custom(limitRange=LIMITS, quota={**SIZES, "requests.storage": "500Gi"}), approvals=2)
    r = patch(world, etag, {"labels": {"cmapi.net/cost-center": "cc-9000"}})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert changed(plan) == ["namespace.yaml"]                         # the two sized objects do not change
    assert plan["beyondTier"] is None and plan["approval"]["auto"] == "none-required"


def test_a_new_value_on_an_approved_namespace_is_beyond_the_tier_again(world):
    etag = synced(world, custom(limitRange=LIMITS), approvals=2)
    r = patch(world, etag, {"limitRange": {"container": {"max": {"cpu": "3"}}}})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["beyondTier"]["keys"] == [{"key": "limitRange.container.max.cpu", "tier": "2", "requested": "3"}]
    assert [(s["group"], s["count"]) for s in plan["approval"]["slots"]] == [("approver-platform", 1)]    # dev change is 0; this is the extra one
    lr = rendered(plan["files"], "limitrange.yaml")
    assert lr["spec"]["limits"][0]["max"] == {"cpu": "3", "memory": "8Gi"}          # the other approved values stay
    assert lr["metadata"]["annotations"]["cmapi.net/beyond-tier"] == ",".join(LIMIT_KEYS)


def test_the_tiers_value_removes_an_override(world):
    etag = synced(world, custom(limitRange={"pvc": {"max": {"storage": "100Gi"}}}), approvals=2)
    r = patch(world, etag, {"limitRange": {"pvc": {"max": {"storage": "50Gi"}}}})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["beyondTier"] is None
    lr = rendered(plan["files"], "limitrange.yaml")
    assert lr["spec"]["limits"][1] == {"type": "PersistentVolumeClaim", "max": {"storage": "50Gi"}}
    assert "cmapi.net/beyond-tier" not in lr["metadata"]["annotations"]


def test_a_change_to_a_named_tier_drops_each_override(world):
    etag = synced(world, custom(limitRange=LIMITS, quota={**SIZES, "requests.storage": "500Gi"}), approvals=2)
    r = patch(world, etag, {"tier": "small"})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["beyondTier"] is None
    lr, rq = rendered(plan["files"], "limitrange.yaml"), rendered(plan["files"], "resourcequota.yaml")
    assert lr["spec"]["limits"][0]["max"] == {"cpu": "2", "memory": "4Gi"} and rq["spec"]["hard"]["requests.storage"] == "200Gi"
    assert "cmapi.net/beyond-tier" not in lr["metadata"]["annotations"] and "cmapi.net/beyond-tier" not in rq["metadata"]["annotations"]


def test_a_lower_bound_later_does_not_refuse_a_change_of_a_label(world):
    client, ctx, git, kube, validator, keys = world
    etag = synced(world, custom(limitRange={"pvc": {"max": {"storage": "100Gi"}}}), approvals=2)
    ctx.cfg.tiers._bounds["dev"].max["limitRange.pvc.max.storage"] = "80Gi"        # the platform lowers the bound
    assert patch(world, etag, {"labels": {"cmapi.net/cost-center": "cc-9000"}}).status_code == 200
    r = patch(world, etag, {"limitRange": {"pvc": {"max": {"storage": "90Gi"}}}})   # a new value meets the new bound
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "custom-out-of-bounds", r.text


def test_an_approved_change_of_limits_opens_a_pull_request_with_the_planned_files(world):
    client, ctx, git, kube, validator, keys = world
    etag = synced(world, custom(), approvals=1)
    r = patch(world, etag, {"limitRange": {"container": {"max": {"cpu": "4", "memory": "8Gi"}}}}, dry_run=False)
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    approve_and_sync(world, r.json()["requestId"], approvals=1)
    limits = kube.objects[("LimitRange", NS["namespace"], f"{NS['namespace']}-limits")]
    assert limits["spec"]["limits"][0]["max"] == {"cpu": "4", "memory": "8Gi"}
    assert limits["metadata"]["annotations"]["cmapi.net/beyond-tier"] == "limitRange.container.max.cpu,limitRange.container.max.memory"
