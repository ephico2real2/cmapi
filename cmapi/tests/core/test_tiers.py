"""Tests for cmapi.core.tiers against the example catalog files.

Run from cmapi/:  PYTHONPATH=src:tests/core python -m pytest -q tests/core/test_tiers.py
"""
import pytest
import yaml

from cmapi.core.tiers import CatalogError, TierCatalog, TierError, qty
from conftest import EX as HERE, INSTANCES

COMBINED = HERE / "config" / "tiers.yaml"


@pytest.fixture(scope="module")
def cat() -> TierCatalog:
    return TierCatalog.load(COMBINED, {"rnd", "dev", "qa", "uat", "prod"})


def raw():
    return yaml.safe_load(COMBINED.read_text())


@pytest.mark.parametrize("instance,envs", INSTANCES.items())
def test_every_instance_file_loads(instance, envs):
    c = TierCatalog.load(HERE / "instances" / instance / "tiers.yaml", envs)
    assert set(c.environments()) == envs


def test_instance_file_with_foreign_environment_is_refused():
    with pytest.raises(CatalogError, match="not served by this instance"):
        TierCatalog(raw(), {"rnd", "dev"})


def test_quantities():
    assert qty("500m") == qty("0.5")
    assert qty("32Gi") == 32 * 2**30
    with pytest.raises(ValueError):
        qty("lots")


def test_named_tiers_resolve_with_defaults(cat):
    m = cat.resolve("dev", "medium")
    assert m.quota["requests.cpu"] == "16" and m.quota["pods"] == "100"
    assert m.quota["services.loadbalancers"] == "0"          # from defaults
    assert m.limit_range["container"]["max"] == {"cpu": "4", "memory": "8Gi"}
    assert m.limit_range["container"]["default"] == {"cpu": "500m", "memory": "512Mi"}


def test_dev_inherits_rnd(cat):
    assert cat.resolve("dev", "large").hash == cat.resolve("rnd", "large").hash
    assert cat.bounds("dev").max == cat.bounds("rnd").max


def test_prod_overrides_container_max_only(cat):
    p, r = cat.resolve("prod", "medium"), cat.resolve("rnd", "medium")
    assert p.limit_range["container"]["max"] == {"cpu": "8", "memory": "16Gi"}
    assert p.quota == r.quota and p.hash != r.hash


def test_tier_hash_is_stable_and_changes_with_values():
    a = TierCatalog(raw(), {"rnd", "dev", "qa", "uat", "prod"}).resolve("qa", "small").hash
    changed = raw()
    changed["tiers"]["small"]["quota"]["pods"] = "60"
    b = TierCatalog(changed, {"rnd", "dev", "qa", "uat", "prod"}).resolve("qa", "small").hash
    assert a == TierCatalog(raw(), {"rnd", "dev", "qa", "uat", "prod"}).resolve("qa", "small").hash
    assert a != b


def test_named_tier_refuses_quota(cat):
    with pytest.raises(TierError) as e:
        cat.quota_for("rnd", "small", {"requests.cpu": "9"})
    assert e.value.code == "quota-with-named-tier"


def test_custom_within_bounds(cat):
    hard = cat.quota_for("prod", "custom", {"requests.cpu": "40", "requests.memory": "80Gi", "pods": "150"})
    assert hard["requests.cpu"] == "40" and hard["persistentvolumeclaims"] == "20"


@pytest.mark.parametrize("hard,code", [
    ({"requests.cpu": "40", "requests.memory": "80Gi", "pods": "150"}, "custom-out-of-bounds"),   # rnd max 32
    ({"requests.cpu": "7.5", "requests.memory": "16Gi", "pods": "50"}, "custom-out-of-bounds"),   # off step
    ({"requests.cpu": "8", "requests.memory": "16Gi"}, "custom-quota-required"),
    ({"requests.cpu": "8", "requests.memory": "16Gi", "pods": "50", "requests.storage": "1Ti"}, "quota-key-not-sizable"),
])
def test_custom_refusals(cat, hard, code):
    with pytest.raises(TierError) as e:
        cat.quota_for("rnd", "custom", hard)
    assert e.value.code == code


def test_unknown_and_not_offered(cat):
    with pytest.raises(TierError) as e:
        cat.resolve("rnd", "xl")
    assert e.value.code == "tier-unknown"
    with pytest.raises(TierError) as e:
        cat.resolve("staging", "small")
    assert e.value.code == "environment-not-served"


def test_patch_quota_normalises_to_named_tier_or_custom(cat):
    assert cat.normalise("qa", {"requests.cpu": "16", "requests.memory": "32Gi", "pods": "100"})[0] == "medium"
    tier, hard = cat.normalise("qa", {"requests.cpu": "20", "requests.memory": "40Gi", "pods": "120"})
    assert tier == "custom" and hard["requests.cpu"] == "20"


def test_rightsizing_snaps_within_ten_percent(cat):
    near = {"requests.cpu": "15", "requests.memory": "30Gi", "pods": "95"}
    assert cat.match("uat", near) is None
    assert cat.match("uat", near, tolerance=0.10) == "medium"


def test_compare_gives_approval_facts(cat):
    small, large = cat.quota_for("prod", "small"), cat.quota_for("prod", "large")
    up = cat.compare("prod", "small", small, "large", large)
    assert up.tier_change == "up" and up.quota_increase_pct == 300.0
    down = cat.compare("prod", "large", large, "small", small,
                       used={"requests.cpu": "12", "requests.memory": "10Gi", "pods": "30"})
    assert down.tier_change == "down" and down.below_used == ["requests.cpu"]


def test_render_matches_the_example_namespace_folder(cat):
    rq, lr = cat.render(namespace="payments-dev", cluster_id="OCP_GF15", instance="nonprod", env="dev",
                        tier="medium", request_id="req-20261104-2b17")
    folder = HERE / "cluster-configs/clusters/OCP_GF15/namespaces/payments-dev"
    assert rq == yaml.safe_load((folder / "resourcequota.yaml").read_text())
    assert lr == yaml.safe_load((folder / "limitrange.yaml").read_text())
    assert list(rq["spec"]["hard"])[:3] == ["requests.cpu", "requests.memory", "pods"]


def test_outdated_detection(cat):
    h = cat.resolve("dev", "medium").hash
    assert not cat.is_outdated("dev", "medium", h)
    assert cat.is_outdated("dev", "medium", "000000000000")


@pytest.mark.parametrize("mutate,problem", [
    (lambda r: r["tiers"]["medium"]["quota"].update({"requests.cpu": "8"}), "not above small"),
    (lambda r: r["tiers"]["large"]["limitRange"]["container"]["max"].update({"cpu": "40"}), "would not fit"),
    (lambda r: r["environments"]["rnd"].update({"offered": ["small", "xl"]}), "unknown tier xl"),
    (lambda r: r["environments"]["dev"].update({"inherit": "dev"}), "inherit loop"),
    (lambda r: r["custom"]["min"].update({"requests.cpu": "1"}), "would not fit"),
    (lambda r: r["tiers"]["custom"].update({"quota": {"pods": "10"}}), "cannot fix sizable"),
])
def test_bad_catalogs_are_refused(mutate, problem):
    r = raw()
    mutate(r)
    with pytest.raises(CatalogError, match=problem):
        TierCatalog(r, {"rnd", "dev", "qa", "uat", "prod"})


def test_describe_is_the_api_body(cat):
    body = cat.describe("prod")
    assert body["catalogHash"] == cat.catalog_hash
    names = [t["name"] for t in body["environments"]["prod"]["tiers"]]
    assert names == ["small", "medium", "large", "custom"]
    assert body["environments"]["prod"]["custom"]["max"]["requests.cpu"] == "128"
