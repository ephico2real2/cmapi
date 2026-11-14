"""#253 (the adoption design's D19): cmapi's own LimitRanges, one for each resource, and the storage switch.

The sync check's read by kind is in tests/service/test_storage_limits_switch.py: core/sync.py needs the service's
packages, which the reference-code job does not install. Each test fails on the code before #253: it rendered one <ns>-limits object with a Container item and a PVC item, wrote
resourcequota.yaml and limitrange.yaml, and had no storageLimitRange switch.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import index_of, render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec, object_file, objects_of
from cmapi.core.tiers import CatalogError, TierCatalog, TierError
from conftest import ALL_ENVS, EX
from test_policygen import BASE, LR_CPU, RQ, kyverno, owners_sample, validator  # noqa: F401  (fixtures)

COMBINED = EX / "config/tiers.yaml"
SIZES = {"requests.cpu": "8", "requests.memory": "16Gi", "pods": "50"}
KW = dict(namespace="abc-rnd", cluster_id="OCP_GF15", instance="nonprod", env="rnd", request_id="req-1")


def raw(storage: bool | None = None) -> dict:
    r = yaml.safe_load(COMBINED.read_text())
    if storage is not None:
        r["storageLimitRange"] = {"enabled": storage}
    return r


def names(lrs: list[dict]) -> list[str]:
    return [lr["metadata"]["name"] for lr in lrs]


# ------------------------------------------------------------------------------------------------- the rendering
def test_the_default_is_off_in_code_with_the_key_absent():
    """The owner: "turn it off by default in code and then provide an override". No shipped catalog carries the key, and
    each environment of each is off."""
    for path in [COMBINED, *sorted((EX / "instances").glob("*/tiers.yaml"))]:
        r = yaml.safe_load(path.read_text())
        assert "storageLimitRange" not in r and not any("storageLimitRange" in e for e in r["environments"].values()), path
        envs = set(r["environments"])
        c = TierCatalog(r, envs)
        assert not any(c.storage_limits(e) for e in envs), path
        assert all(lr["metadata"]["name"] != "abc-rnd-limits-storage"
                   for lr in c.render(**{**KW, "env": sorted(envs)[0]}, tier="small")[1]), path


def test_off_renders_one_limitrange_for_cpu_and_one_for_memory():
    rq, lrs = TierCatalog(raw(), ALL_ENVS).render(**KW, tier="medium")
    assert names(lrs) == ["abc-rnd-limits-cpu", "abc-rnd-limits-memory"]
    cpu, memory = lrs
    assert cpu["spec"]["limits"] == [{"type": "Container", "defaultRequest": {"cpu": "100m"}, "default": {"cpu": "500m"},
                                      "max": {"cpu": "4"}}]
    assert memory["spec"]["limits"] == [{"type": "Container", "defaultRequest": {"memory": "256Mi"},
                                         "default": {"memory": "512Mi"}, "max": {"memory": "8Gi"}}]
    # one tier hash on every object, so is_outdated reads the same value from any of them
    assert {o["metadata"]["annotations"]["cmapi.net/tier-hash"] for o in (rq, *lrs)} == {
        TierCatalog(raw(), ALL_ENVS).resolve("rnd", "medium").hash}


def test_on_renders_a_third_object_for_storage():
    _, lrs = TierCatalog(raw(storage=True), ALL_ENVS).render(**KW, tier="medium")
    assert names(lrs) == ["abc-rnd-limits-cpu", "abc-rnd-limits-memory", "abc-rnd-limits-storage"]
    assert lrs[2]["spec"]["limits"] == [{"type": "PersistentVolumeClaim", "max": {"storage": "50Gi"}}]


def test_no_two_objects_set_a_default_for_the_same_resource():
    """The reason for the split: Kubernetes does not say which default applies when two LimitRanges set one."""
    r = raw(storage=True)
    r["overridable"].append("limitRange.container.default.ephemeral-storage")
    r["custom"]["max"]["limitRange.container.default.ephemeral-storage"] = "8Gi"
    c = TierCatalog(r, ALL_ENVS)
    _, lrs = c.render(**KW, tier="custom", hard=SIZES, limits={"container": {"default": {"ephemeral-storage": "2Gi"}}})
    assert names(lrs) == ["abc-rnd-limits-cpu", "abc-rnd-limits-memory", "abc-rnd-limits-ephemeral-storage",
                          "abc-rnd-limits-storage"]
    by_resource = {}
    for lr in lrs:
        for item in lr["spec"]["limits"]:
            for part in ("default", "defaultRequest"):
                for res in item.get(part, {}):
                    by_resource.setdefault((item["type"], res), set()).add(lr["metadata"]["name"])
    assert sorted(by_resource) == [("Container", "cpu"), ("Container", "ephemeral-storage"), ("Container", "memory")]
    assert all(len(objs) == 1 for objs in by_resource.values()), by_resource


def test_an_extended_resource_gets_a_valid_object_name():
    r = raw()
    gpu = "nvidia.com/gpu"
    for part in ("defaultRequest", "default"):
        r["overridable"].append(f"limitRange.container.{part}.{gpu}")
        r["custom"]["max"][f"limitRange.container.{part}.{gpu}"] = "4"
    _, lrs = TierCatalog(r, ALL_ENVS).render(**KW, tier="custom", hard=SIZES,
                                             limits={"container": {"defaultRequest": {gpu: "1"}, "default": {gpu: "1"}}})
    assert names(lrs)[-1] == "abc-rnd-limits-nvidia.com-gpu"
    assert lrs[-1]["metadata"]["annotations"]["cmapi.net/beyond-tier"] == \
        "limitRange.container.defaultRequest.nvidia.com/gpu,limitRange.container.default.nvidia.com/gpu"


@pytest.mark.parametrize("resources", [("hugepages-2Mi", "hugepages-2mi"), ("storage",), ("x/y", "x-y")])
def test_two_resources_that_would_share_an_object_stop_the_catalog(resources):
    r = raw()
    for res in resources:
        r["overridable"].append(f"limitRange.container.max.{res}")
        r["custom"]["max"][f"limitRange.container.max.{res}"] = "4"
    with pytest.raises(CatalogError, match="would share the LimitRange"):
        TierCatalog(r, ALL_ENVS)


# ------------------------------------------------------------------------------------------------- the switch
def test_an_environment_overrides_the_switch_and_inherit_passes_it_on():
    r = raw()
    r["environments"]["rnd"]["storageLimitRange"] = {"enabled": True}          # dev inherits rnd
    c = TierCatalog(r, ALL_ENVS)
    assert {e: c.storage_limits(e) for e in sorted(ALL_ENVS)} == {"dev": True, "prod": False, "qa": False, "rnd": True,
                                                                  "uat": False}
    r = raw(storage=True)
    r["environments"]["dev"]["storageLimitRange"] = {"enabled": False}         # the child's own value wins
    c = TierCatalog(r, ALL_ENVS)
    assert c.storage_limits("rnd") and not c.storage_limits("dev")


@pytest.mark.parametrize("value", ["true", "off", 1, None])
def test_the_switch_takes_only_a_boolean(value):
    r = raw()
    r["storageLimitRange"] = {"enabled": value}
    with pytest.raises(Exception, match="enabled"):
        TierCatalog(r, ALL_ENVS)


def test_the_hash_follows_what_is_rendered():
    off, on = TierCatalog(raw(), ALL_ENVS), TierCatalog(raw(storage=True), ALL_ENVS)
    for tier in ("small", "medium", "large", "custom"):
        assert off.resolve("rnd", tier).hash != on.resolve("rnd", tier).hash, tier
    changed = raw()
    changed["defaults"]["limitRange"]["pvc"]["max"]["storage"] = "60Gi"           # not rendered while the switch is off
    assert TierCatalog(changed, ALL_ENVS).resolve("rnd", "small").hash == off.resolve("rnd", "small").hash


def test_off_refuses_a_new_storage_limit_and_names_the_key_and_the_environment():
    c = TierCatalog(raw(), ALL_ENVS)
    with pytest.raises(TierError) as e:
        c.limits_for("rnd", "custom", {"pvc": {"max": {"storage": "100Gi"}}}, SIZES)
    assert e.value.code == "storage-limits-off"
    assert e.value.data == {"keys": ["limitRange.pvc.max.storage"], "environment": "rnd"}
    assert str(e.value) == "Storage limits are off in environment rnd: limitRange.pvc.max.storage cannot be set"


def test_off_drops_a_storage_limit_that_git_holds_instead_of_refusing_the_change():
    """A namespace approved while the switch was on: a change of a label still goes through, and the plan removes the
    storage object."""
    on, off = TierCatalog(raw(storage=True), ALL_ENVS), TierCatalog(raw(), ALL_ENVS)
    rq, lrs = on.render(**KW, tier="custom", hard=SIZES, limits={"pvc": {"max": {"storage": "100Gi"}}})
    approved = {**SIZES, **on.rendered_overrides(rq, lrs)}
    assert approved["limitRange.pvc.max.storage"] == "100Gi"
    limits = {"pvc": {"max": {"storage": "100Gi"}}}                              # as the pipeline merges Git's values
    assert "pvc" not in off.limits_for("rnd", "custom", limits, SIZES, approved)
    _, after = off.render(**KW, tier="custom", hard=SIZES, limits=limits, approved=approved)
    assert names(after) == ["abc-rnd-limits-cpu", "abc-rnd-limits-memory"]
    with pytest.raises(TierError) as e:
        off.limits_for("rnd", "custom", {"pvc": {"max": {"storage": "90Gi"}}}, SIZES, approved)    # a new value
    assert e.value.code == "storage-limits-off"


def test_describe_says_whether_storage_limits_are_on():
    assert TierCatalog(raw(), ALL_ENVS).describe("rnd")["environments"]["rnd"]["storageLimitRange"] == {"enabled": False}
    assert TierCatalog(raw(storage=True), ALL_ENVS).describe("rnd")["environments"]["rnd"]["storageLimitRange"] == \
        {"enabled": True}


def test_off_has_no_storage_rule_in_the_policies_and_on_has_it():
    keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.yaml")
    rule = "cmapi-limits-rnd-limit-limitrange-pvc-max-storage-max"
    off = index_of(render_bundle(TierCatalog(raw(), ALL_ENVS), keys, PolicySettings(), {"rnd"}, "nonprod"))
    on = index_of(render_bundle(TierCatalog(raw(storage=True), ALL_ENVS), keys, PolicySettings(), {"rnd"}, "nonprod"))
    assert not any(v["key"].startswith("limitRange.pvc.") for v in off.values() if v["key"])
    assert on[rule] == {"kind": "limit", "key": "limitRange.pvc.max.storage", "rule": "max"}
    assert set(on) - set(off) == {rule}


# ------------------------------------------------------------------------------------------------- the folder
def renderer(storage: bool = False) -> ManifestRenderer:
    return ManifestRenderer(TierCatalog(raw(storage), ALL_ENVS), MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.yaml"))


def spec(**kw) -> NamespaceSpec:
    base = dict(KW, tier="custom", requested_by_user="ola", requested_by_email="ola@company.net", labels={}, annotations={})
    base = {**base, **kw}
    if base["tier"] == "custom":
        base.setdefault("quota", SIZES)
    return NamespaceSpec(**base)


def old_layout(files: dict[str, str | None]) -> dict[str, str]:
    """The folder as cmapi wrote it before #253: resourcequota.yaml, and one <ns>-limits with every item."""
    out = {p: t for p, t in files.items() if t and "/resourcequota-" not in p and "/limitrange-" not in p}
    rq = objects_of(files, "ResourceQuota")[0]
    lrs = objects_of(files, "LimitRange")
    one = copy.deepcopy(lrs[0])
    one["metadata"]["name"] = "abc-rnd-limits"
    keys = [k for lr in lrs for k in (lr["metadata"]["annotations"].get("cmapi.net/beyond-tier") or "").split(",") if k]
    one["metadata"]["annotations"].pop("cmapi.net/beyond-tier", None)
    if keys:
        one["metadata"]["annotations"]["cmapi.net/beyond-tier"] = ",".join(keys)
    container: dict = {"type": "Container"}
    for lr in lrs:
        for item in lr["spec"]["limits"]:
            if item["type"] == "Container":
                for part, vals in item.items():
                    if part != "type":
                        container.setdefault(part, {}).update(vals)
    one["spec"]["limits"] = [container]
    out[BASE + "resourcequota.yaml"] = yaml.safe_dump(rq, sort_keys=False)
    out[BASE + "limitrange.yaml"] = yaml.safe_dump(one, sort_keys=False)
    return out


def test_the_folder_has_one_file_for_each_object():
    files = renderer().render(spec(tier="small"))
    assert sorted(p.removeprefix(BASE) for p in files) == [
        "limitrange-abc-rnd-limits-cpu.yaml", "limitrange-abc-rnd-limits-memory.yaml", "namespace.yaml",
        "resourcequota-abc-rnd-quota.yaml", "token-issuer-rolebinding.yaml"]
    for p, text in files.items():
        if "/resourcequota-" in p or "/limitrange-" in p:
            (doc,) = list(yaml.safe_load_all(text))
            assert p.endswith(object_file(doc["kind"], doc["metadata"]["name"]))


def test_a_name_too_long_for_a_file_is_written_under_its_hash():
    name = "a" * 250
    f = object_file("LimitRange", name)
    assert f.startswith("limitrange-") and f.endswith(".yaml") and len(f.encode()) <= 255 and name not in f
    assert f == object_file("LimitRange", name) != object_file("LimitRange", "b" * 250)


def test_an_old_folder_moves_to_the_named_files_in_one_change_and_keeps_its_approvals():
    r = renderer()
    first = r.render(spec(limit_range={"container": {"max": {"cpu": "4"}}}))
    old = old_layout(first)
    assert TierCatalog(raw(), ALL_ENVS).rendered_overrides(objects_of(old, "ResourceQuota")[0],
                                                           objects_of(old, "LimitRange")) == \
        {"limitRange.container.max.cpu": "4"}
    again = r.render(spec(request_id="req-2", limit_range={"container": {"max": {"cpu": "4"}}},
                          approved={**SIZES, "limitRange.container.max.cpu": "4"}), previous=old)
    assert again[BASE + "resourcequota.yaml"] is None and again[BASE + "limitrange.yaml"] is None
    assert names(objects_of(again, "LimitRange")) == ["abc-rnd-limits-cpu", "abc-rnd-limits-memory"]
    # the quota object kept its name and its content, so it keeps the request ID that Git holds
    (rq,) = objects_of(again, "ResourceQuota")
    assert rq["metadata"]["annotations"]["cmapi.net/request-id"] == "req-1"


def test_a_value_that_git_held_before_the_split_stays_held(kyverno, tmp_path):
    """The ratchet of #212 across the split: an approved cpu max above today's bound, held in the old <ns>-limits, is not
    refused on the new <ns>-limits-cpu. A changed value is."""
    keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.company.yaml")
    cat = TierCatalog(raw(), ALL_ENVS)
    files = owners_sample(cat, keys)
    cpu = yaml.safe_load(files[LR_CPU])
    cpu["spec"]["limits"][0]["max"]["cpu"] = "20"                 # the rnd maximum is 16
    files[LR_CPU] = yaml.safe_dump(cpu)
    now = {BASE + n: t for n, t in files.items() if n.endswith(".yaml") and n != "token-issuer-rolebinding.yaml"}
    previous = old_layout(now)
    assert "max" in yaml.safe_load(previous[BASE + "limitrange.yaml"])["spec"]["limits"][0]
    v = validator(cat, keys, tmp_path)
    assert [f.rule for f in v.validate(now, "OCP_GF15", "rnd", previous=previous) if f.source == "kyverno"] == []
    assert [f.rule for f in v.validate(now, "OCP_GF15", "rnd") if f.source == "kyverno"] == \
        ["cmapi-limits-rnd-limit-limitrange-container-max-cpu-max"]
    cpu["spec"]["limits"][0]["max"]["cpu"] = "21"
    now[BASE + LR_CPU] = yaml.safe_dump(cpu)
    assert [f.rule for f in v.validate(now, "OCP_GF15", "rnd", previous=previous) if f.source == "kyverno"] == \
        ["cmapi-limits-rnd-limit-limitrange-container-max-cpu-max"]
