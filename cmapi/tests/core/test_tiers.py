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
    ({"requests.cpu": "8", "requests.memory": "16Gi", "pods": "50", "limits.cpu": "16"}, "quota-key-not-sizable"),
    ({"requests.cpu": "8", "requests.memory": "16Gi", "pods": "50", "requests.storage": "3Ti"}, "custom-out-of-bounds"),  # max 2Ti
    ({"requests.cpu": "8", "requests.memory": "16Gi", "pods": "50", "services.loadbalancers": "3"}, "custom-out-of-bounds"),
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


# ---- values beyond the tier on the custom tier (#211)
SIZES = {"requests.cpu": "8", "requests.memory": "16Gi", "pods": "50"}
ALL = {"rnd", "dev", "qa", "uat", "prod"}


def test_a_custom_request_can_change_an_overridable_quota_key(cat):
    hard = cat.quota_for("rnd", "custom", {**SIZES, "requests.storage": "500Gi", "services.loadbalancers": "1"})
    assert hard["requests.storage"] == "500Gi" and hard["services.loadbalancers"] == "1"
    assert hard["persistentvolumeclaims"] == "20"                 # a key that is left out keeps the tier's value


def test_custom_limits_go_over_the_tiers_values(cat):
    hard = cat.quota_for("rnd", "custom", SIZES)
    lr = cat.limits_for("rnd", "custom", {"container": {"max": {"cpu": "4", "memory": "8Gi"}}, "pvc": {"max": {"storage": "100Gi"}}}, hard)
    assert lr["container"]["max"] == {"cpu": "4", "memory": "8Gi"} and lr["pvc"]["max"] == {"storage": "100Gi"}
    assert lr["container"]["default"] == {"cpu": "500m", "memory": "512Mi"}      # the tier's value stays
    assert cat.limits_for("rnd", "custom", None, hard) == cat.resolve("rnd", "custom").limit_range


@pytest.mark.parametrize("tier,limits,code", [
    ("small", {"container": {"max": {"cpu": "1"}}}, "limits-with-named-tier"),
    ("custom", {"container": {"min": {"cpu": "10m"}}}, "limit-key-not-overridable"),
    ("custom", {"container": {"maxLimitRequestRatio": {"cpu": "2"}}}, "limit-key-not-overridable"),
    ("custom", {"pod": {"max": {"cpu": "2"}}}, "limit-key-not-overridable"),
    ("custom", {"pvc": {"max": {"storage": "600Gi"}}}, "custom-out-of-bounds"),                 # the maximum is 500Gi
    ("custom", {"container": {"default": {"cpu": "3"}}}, "limit-order-invalid"),                # above the tier's max of 2
    ("custom", {"container": {"defaultRequest": {"memory": "1Gi"}}}, "limit-order-invalid"),    # above the default of 512Mi
    ("custom", {"container": {"max": {"cpu": "12"}}}, "limit-exceeds-quota"),                   # requests.cpu is 8
    ("custom", {"container": {"max": {"memory": "24Gi"}}}, "limit-exceeds-quota"),              # requests.memory is 16Gi
])
def test_limit_refusals(cat, tier, limits, code):
    hard = cat.quota_for("rnd", tier, SIZES if tier == "custom" else None)
    with pytest.raises(TierError) as e:
        cat.limits_for("rnd", tier, limits, hard)
    assert e.value.code == code


def test_an_out_of_bounds_limit_names_the_key_and_its_bounds(cat):
    with pytest.raises(TierError) as e:
        cat.limits_for("rnd", "custom", {"pvc": {"max": {"storage": "600Gi"}}}, cat.quota_for("rnd", "custom", SIZES))
    assert e.value.data["items"] == [{"key": "limitRange.pvc.max.storage", "value": "600Gi", "min": None, "max": "500Gi", "step": None}]


def test_beyond_lists_each_value_that_differs_from_the_tier(cat):
    hard = cat.quota_for("rnd", "custom", {**SIZES, "requests.storage": "500Gi", "persistentvolumeclaims": "20"})
    lr = cat.limits_for("rnd", "custom", {"container": {"max": {"cpu": "4"}, "default": {"cpu": "0.5"}}}, hard)
    assert cat.beyond("rnd", "custom", hard, lr) == {
        "requests.storage": {"tier": "200Gi", "requested": "500Gi"},
        "limitRange.container.max.cpu": {"tier": "2", "requested": "4"}}       # 0.5 is the tier's 500m; 20 claims is the tier's value
    small = cat.quota_for("rnd", "small")
    assert cat.beyond("rnd", "small", small, cat.limits_for("rnd", "small", None, small)) == {}


def test_render_names_the_beyond_tier_keys_on_each_object(cat):
    kw = dict(namespace="payments-dev", cluster_id="OCP_GF15", instance="nonprod", env="dev", tier="custom", request_id="req-1")
    rq, lr = cat.render(**kw, hard={**SIZES, "requests.storage": "500Gi"},
                        limits={"container": {"max": {"cpu": "4", "memory": "8Gi"}}})
    assert rq["metadata"]["annotations"]["cmapi.net/beyond-tier"] == "requests.storage"
    assert lr["metadata"]["annotations"]["cmapi.net/beyond-tier"] == "limitRange.container.max.cpu,limitRange.container.max.memory"
    assert lr["spec"]["limits"][0]["max"] == {"cpu": "4", "memory": "8Gi"} and rq["spec"]["hard"]["requests.storage"] == "500Gi"
    assert cat.rendered_overrides(rq, lr) == {"requests.storage": "500Gi", "limitRange.container.max.cpu": "4",
                                              "limitRange.container.max.memory": "8Gi"}
    plain_rq, plain_lr = cat.render(**kw, hard=SIZES)
    assert "cmapi.net/beyond-tier" not in plain_rq["metadata"]["annotations"]
    assert "cmapi.net/beyond-tier" not in plain_lr["metadata"]["annotations"]
    assert cat.rendered_overrides(plain_rq, plain_lr) == {} and cat.rendered_overrides(None, None) == {}


def test_a_value_that_git_holds_is_not_checked_against_the_bounds_again():
    r = raw()
    r["custom"]["max"]["requests.storage"] = "300Gi"            # the bound went down after 500Gi was approved
    r["custom"]["max"]["limitRange.pvc.max.storage"] = "80Gi"
    c = TierCatalog(r, ALL)
    quota, limits = {**SIZES, "requests.storage": "500Gi"}, {"pvc": {"max": {"storage": "100Gi"}}}
    approved = {"requests.storage": "500Gi", "limitRange.pvc.max.storage": "100Gi"}
    hard = c.quota_for("rnd", "custom", quota, approved)
    assert c.limits_for("rnd", "custom", limits, hard, approved)["pvc"]["max"] == {"storage": "100Gi"}
    with pytest.raises(TierError) as e:
        c.quota_for("rnd", "custom", {**quota, "requests.storage": "400Gi"}, approved)       # a new value is checked
    assert e.value.code == "custom-out-of-bounds"
    with pytest.raises(TierError):
        c.limits_for("rnd", "custom", limits, hard)                                             # and so is a value with no approval


@pytest.mark.parametrize("mutate,problem", [
    (lambda r: r["overridable"].append("pods"), "pods is already sizable"),
    (lambda r: r["overridable"].append("limitRange.container.maximum.cpu"), "is not limitRange"),
    (lambda r: r["overridable"].append("requests.storage"), "listed more than once"),
    (lambda r: r["overridable"].append("count/secrets"), "custom.max.count/secrets missing"),
    (lambda r: r["custom"]["max"].update({"limits.cpu": "4"}), "not a sizable or overridable key"),
    (lambda r: r["custom"]["max"].update({"requests.storage": "100Gi"}), "the tier's own requests.storage"),
    (lambda r: r["custom"]["max"].update({"limitRange.pvc.max.storage": "lots"}), "not a Kubernetes quantity"),
])
def test_bad_overridable_keys_are_refused(mutate, problem):
    r = raw()
    mutate(r)
    with pytest.raises(CatalogError, match=problem):
        TierCatalog(r, ALL)


def test_describe_names_the_overridable_keys_and_their_bounds(cat):
    body = cat.describe("prod")
    assert "limitRange.container.max.cpu" in body["overridable"] and "services.nodeports" in body["overridable"]
    assert body["environments"]["prod"]["custom"]["max"]["services.loadbalancers"] == "2"


def test_an_approved_value_stays_valid_when_the_catalog_no_longer_names_its_key():
    r = raw()
    for key in ("requests.storage", "limitRange.pvc.max.storage"):
        r["overridable"].remove(key)
        del r["custom"]["max"][key]
    c = TierCatalog(r, ALL)
    quota, limits = {**SIZES, "requests.storage": "500Gi"}, {"pvc": {"max": {"storage": "100Gi"}}}
    approved = {"requests.storage": "500Gi", "limitRange.pvc.max.storage": "100Gi"}
    kw = dict(namespace="payments-dev", cluster_id="OCP_GF15", instance="nonprod", env="dev", tier="custom", request_id="req-1")
    rq, lr = c.render(**kw, hard=quota, limits=limits, approved=approved)
    assert rq["spec"]["hard"]["requests.storage"] == "500Gi" and lr["spec"]["limits"][1]["max"] == {"storage": "100Gi"}
    assert c.rendered_overrides(rq, lr) == approved            # the objects still name them, so the next change keeps them too
    for call, code in ((lambda: c.quota_for("dev", "custom", {**quota, "requests.storage": "400Gi"}, approved), "quota-key-not-sizable"),
                       (lambda: c.quota_for("dev", "custom", quota), "quota-key-not-sizable"),
                       (lambda: c.limits_for("dev", "custom", {"pvc": {"max": {"storage": "90Gi"}}}, SIZES, approved), "limit-key-not-overridable"),
                       (lambda: c.limits_for("dev", "custom", limits, SIZES), "limit-key-not-overridable")):
        with pytest.raises(TierError) as e:
            call()
        assert e.value.code == code


def test_the_order_check_covers_each_kind_of_limit():
    r = raw()
    r["overridable"].append("limitRange.pvc.min.storage")
    r["custom"]["max"]["limitRange.pvc.min.storage"] = "500Gi"
    c = TierCatalog(r, ALL)
    with pytest.raises(TierError) as e:
        c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "60Gi"}}}, SIZES)          # the tier's max is 50Gi
    assert e.value.code == "limit-order-invalid" and e.value.data["kind"] == "pvc"
    assert c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "1Gi"}}}, SIZES)["pvc"] == {"max": {"storage": "50Gi"}, "min": {"storage": "1Gi"}}


# ---- from the review of #211 (Codex, findings F3 to F5)
@pytest.mark.parametrize("amount", ["4e0", "4E+0", "4.", "+4", "4.0", "4000m"])
def test_each_spelling_of_a_quantity_that_kubernetes_takes_is_read_as_its_amount(cat, amount):
    limits = {"container": {"max": {"cpu": amount}}}
    rq, lr = cat.render(namespace="review-dev", cluster_id="CRC", instance="nonprod", env="dev", tier="custom", request_id="r",
                        hard=SIZES, limits=limits)
    assert lr["spec"]["limits"][0]["max"]["cpu"] == amount
    assert cat.beyond("dev", "custom", rq["spec"]["hard"], cat.limits_for("dev", "custom", limits, SIZES)) == {
        "limitRange.container.max.cpu": {"tier": "2", "requested": amount}}


def test_a_quantity_keeps_each_digit_and_rounds_up_to_the_nano_unit_as_kubernetes_does(cat):
    assert qty("2.0000000000000000000000000001") > qty("2") and qty("2.0000000000000000000000000001") == qty("2000000001n")
    assert qty("500.00000000000000000000000001Gi") > qty("500Gi") and qty("1Ei") == 2 ** 60 and qty("1E") == 10 ** 18
    assert qty("1e3") == qty("1k") and qty(".5") == qty("500m") and qty("1E3") == 1000
    hard = cat.quota_for("dev", "custom", SIZES)
    tiny = cat.limits_for("dev", "custom", {"container": {"max": {"cpu": "2.0000000000000000000000000001"}}}, hard)
    assert list(cat.beyond("dev", "custom", hard, tiny)) == ["limitRange.container.max.cpu"]      # a new value, not the tier's 2


def test_rounding_cannot_reuse_an_approval_for_a_larger_value():
    r = raw()
    r["custom"]["max"]["requests.storage"] = "300Gi"
    with pytest.raises(TierError) as e:
        TierCatalog(r, ALL).quota_for("dev", "custom", {**SIZES, "requests.storage": "500.00000000000000000000000001Gi"},
                                      {"requests.storage": "500Gi"})
    assert e.value.code == "custom-out-of-bounds"


def test_a_resource_that_cannot_overcommit_needs_equal_defaults():
    r, gpu = raw(), "nvidia.com/gpu"
    for part in ("defaultRequest", "default"):
        r["overridable"].append(f"limitRange.container.{part}.{gpu}")
        r["custom"]["max"][f"limitRange.container.{part}.{gpu}"] = "4"
    c = TierCatalog(r, ALL)
    with pytest.raises(TierError) as e:
        c.limits_for("dev", "custom", {"container": {"defaultRequest": {gpu: "1"}, "default": {gpu: "2"}}}, SIZES)
    assert e.value.code == "limit-order-invalid" and e.value.data["resources"] == [gpu]
    assert c.limits_for("dev", "custom", {"container": {"defaultRequest": {gpu: "1"}, "default": {gpu: "1"}}}, SIZES)
    bad = raw()
    bad["defaults"]["limitRange"]["container"]["default"][gpu] = "2"
    bad["defaults"]["limitRange"]["container"]["defaultRequest"][gpu] = "1"
    with pytest.raises(CatalogError, match="cannot overcommit"):
        TierCatalog(bad, ALL)
