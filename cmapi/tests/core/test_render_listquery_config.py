from datetime import date

import pytest
import yaml

from cmapi.core.config import ConfigError, load_instance
from cmapi.core.errors import Problem
from cmapi.core.listquery import Lister, ListQuery, Sorts
from cmapi.core.metadata import MetadataKeys
from cmapi.core.ports import (ApprovalChannel, CapacityBackend, GitProvider, Notifier, OperationsEngine,
                              Renderer, SyncSignal, Validator)
from cmapi.core.ratelimit import RateLimiter
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec, diff_files, plan_hash
from cmapi.core.tiers import TierCatalog
from conftest import ALL_ENVS, EX, INSTANCES

FOLDER = "clusters/OCP_GF15/namespaces/payments-dev/"


@pytest.fixture(scope="module")
def renderer():
    return ManifestRenderer(TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS),
                            MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.yaml"))


def example_folder():
    d = EX / "cluster-configs" / FOLDER
    return {FOLDER + p.name: p.read_text() for p in d.glob("*.yaml")}


def spec(**kw):
    base = dict(namespace="payments-dev", cluster_id="OCP_GF15", instance="nonprod", env="dev", tier="medium",
                request_id="req-20261104-2b17", requested_by_user="ola", requested_by_email="ola@ephico2real.com",
                labels={"cmapi.net/cost-center": "cc-4410", "cmapi.net/team": "payments",
                        "app.ephico2real.com/component": "api"},
                annotations={"cmapi.net/team-dl": "payments-team@ephico2real.com",
                             "ops.ephico2real.com/pager": "payments-oncall"},
                expires_at=date(2026, 12, 15), service_accounts=["payments-deployer"],
                grants=[("payments-deployer", "edit")], scc_grants=[("payments-deployer", "anyuid")])
    return NamespaceSpec(**{**base, **kw})


# ---- renderer
def test_renders_the_example_folder(renderer):
    want = example_folder()
    got = renderer.render(spec(), previous=want)
    assert set(got) == set(want)
    for path in want:
        assert list(yaml.safe_load_all(got[path])) == list(yaml.safe_load_all(want[path])), path
    ns = yaml.safe_load(got[FOLDER + "namespace.yaml"])
    assert list(ns["metadata"]["labels"])[:6] == ["cmapi.net/cluster-id", "cmapi.net/env", "cmapi.net/expiry",
                                                  "cmapi.net/managed", "cmapi.net/requested-by-user", "cmapi.net/tier"]


def test_unchanged_objects_keep_their_request_id(renderer):
    prev = renderer.render(spec(), previous=example_folder())          # the folder as cmapi wrote it
    got = renderer.render(spec(request_id="req-20261105-0001"), previous=prev)
    sa = yaml.safe_load(got[FOLDER + "serviceaccounts.yaml"])
    assert sa["metadata"]["annotations"]["cmapi.net/request-id"] == "req-20261104-3c41"
    assert diff_files(prev, got) == {p: "unchanged" for p in prev}


def test_tier_change_touches_only_tier_files(renderer):
    prev = renderer.render(spec(), previous=example_folder())
    got = renderer.render(spec(tier="large", request_id="req-20261105-0002"), previous=prev)
    changed = {p for p, s in diff_files(prev, got).items() if s == "changed"}
    assert changed == {FOLDER + "namespace.yaml", FOLDER + "resourcequota.yaml", FOLDER + "limitrange.yaml"}
    assert plan_hash(got) != plan_hash(prev)


def test_prod_expiry_refused_and_requester_kept(renderer):
    with pytest.raises(Problem) as e:
        renderer.render(spec(env="prod", expires_at=date(2026, 12, 1)))
    assert e.value.code == "expiration-not-allowed"
    got = renderer.render(spec(requested_by_user="someone-else", request_id="r2"), previous=example_folder())
    assert "requested-by-user: ola" in got[FOLDER + "namespace.yaml"]


def test_delete_removes_the_folder(renderer):
    prev = example_folder()
    out = renderer.delete("OCP_GF15", "payments-dev", prev)
    assert set(out) == set(prev) and all(v is None for v in out.values())


# ---- lists
ROWS = [{"name": n, "clusterId": c, "team": t, "env": "rnd", "used": u}
        for n, c, t, u in [("alpha-api", "OCP_GF1", "payments", 0.2), ("beta-db", "OCP_GF1", "ledger", 0.9),
                           ("billing", "OCP_GF2", "payments", 0.5), ("delta", "OCP_GF1", "data", 0.1),
                           ("payments-rnd", "OCP_GF1", "payments", 0.7), ("zeta", "OCP_GF2", "ops", 0.3)]]


def test_paging_forward_and_back():
    l = Lister(b"k", Sorts({"used": lambda r: r["used"]}))
    p1 = l.page(ROWS, ListQuery(limit=25 if False else 2))
    assert [r["name"] for r in p1["items"]] == ["alpha-api", "beta-db"] and p1["page"]["total"] == 6
    p2 = l.page(ROWS, ListQuery(limit=2, cursor=p1["page"]["nextCursor"]))
    assert [r["name"] for r in p2["items"]] == ["billing", "delta"] and p2["page"]["from"] == 3
    back = l.page(ROWS, ListQuery(limit=2, cursor=p2["page"]["prevCursor"]))
    assert [r["name"] for r in back["items"]] == ["alpha-api", "beta-db"]
    by_used = l.page(ROWS, ListQuery(sort="used", limit=2))
    assert [r["name"] for r in by_used["items"]] == ["beta-db", "payments-rnd"]


def test_cursor_bound_to_filters_and_signed():
    l = Lister(b"k")
    c = l.page(ROWS, ListQuery(limit=2))["page"]["nextCursor"]
    for q in [ListQuery(limit=2, cursor=c, filters={"env": "rnd"}), ListQuery(limit=2, cursor=c[:-2] + "AA")]:
        with pytest.raises(Problem) as e:
            l.page(ROWS, q)
        assert e.value.code == "invalid-cursor"


def test_letter_jump_search_and_suggest():
    l = Lister(b"k")
    p = l.page(ROWS, ListQuery(starts_with="d", limit=2))
    assert p["items"][0]["name"] == "delta" and p["letters"]["Z"] == 1
    assert [r["name"] for r in l.page(ROWS, ListQuery(q="pay"))["items"]] == ["alpha-api", "billing", "payments-rnd"]
    s = l.suggest(ROWS, "pay")
    assert s[0] == {"name": "payments-rnd", "clusterId": "OCP_GF1", "why": "name starts with"}
    assert s[1]["why"] == "team payments"
    assert l.suggest(ROWS, "p") == []


def test_export_same_order():
    l = Lister(b"k")
    lines = list(l.export_csv(ROWS, ListQuery(filters={"team": "payments"}), ["clusterId", "name"]))
    assert lines[0].strip() == "clusterId,name" and lines[1].strip() == "OCP_GF1,alpha-api" and len(lines) == 4


# ---- rate limits
def test_rate_limits():
    t = [0.0]
    rl = RateLimiter(clock=lambda: t[0])
    for _ in range(2):
        rl.check("ola", "payments", "export")
    with pytest.raises(Problem) as e:
        rl.check("ola", "payments", "export")
    assert e.value.status == 429 and e.value.extra["retryAfter"] > 0
    t[0] += 60
    rl.check("ola", "payments", "export")


# ---- instance configuration and ports
@pytest.mark.parametrize("instance", INSTANCES)
def test_each_instance_config_loads(instance):
    d = EX / "instances" / instance
    cfg = load_instance(d, EX / "cluster-configs/policies/metadata-keys.yaml")
    assert cfg.allowed_environments == INSTANCES[instance]
    assert cfg.tiers.environments() == sorted(INSTANCES[instance])


def test_cross_file_check_catches_unknown_tier(tmp_path):
    src = EX / "instances" / "nonprod"
    for f in src.iterdir():
        (tmp_path / f.name).write_text(f.read_text())
    rules = yaml.safe_load((tmp_path / "approval-rules.yaml").read_text())
    rules["autoApproval"]["policies"][0]["match"]["tiers"] = ["small", "xl"]
    (tmp_path / "approval-rules.yaml").write_text(yaml.safe_dump(rules))
    with pytest.raises(ConfigError, match="tier xl"):
        load_instance(tmp_path, EX / "cluster-configs/policies/metadata-keys.yaml")


def test_renderer_satisfies_its_port(renderer):
    assert isinstance(renderer, Renderer)
    for proto in (GitProvider, Validator, CapacityBackend, SyncSignal, OperationsEngine, Notifier, ApprovalChannel):
        assert hasattr(proto, "__protocol_attrs__") or hasattr(proto, "_is_protocol")


# ---- regressions from the code review
def test_removing_the_last_grant_removes_its_file(renderer):
    prev = renderer.render(spec(), previous=example_folder())
    got = renderer.render(spec(grants=[], scc_grants=[], request_id="r3"), previous=prev)
    assert got[FOLDER + "rolebindings.yaml"] is None
    assert diff_files(prev, got)[FOLDER + "rolebindings.yaml"] == "removed"


def test_caller_cannot_override_system_labels(renderer):
    got = renderer.render(spec(env="rnd", expires_at=None, labels={"cmapi.net/env": "prod", "cmapi.net/team": "payments"}))
    assert yaml.safe_load(got[FOLDER + "namespace.yaml"])["metadata"]["labels"]["cmapi.net/env"] == "rnd"


def test_prev_page_never_overlaps():
    rows = [{"name": f"n{i:03d}", "clusterId": "C"} for i in range(60)]
    l = Lister(b"k")
    jump = l.page(rows, ListQuery(limit=25, starts_with="n010"))
    back = l.page(rows, ListQuery(limit=25, cursor=jump["page"]["prevCursor"]))
    assert [r["name"] for r in back["items"]] == [f"n{i:03d}" for i in range(10)]
    first = l.page(rows, ListQuery(limit=25))
    p2 = l.page(rows, ListQuery(limit=25, cursor=first["page"]["nextCursor"]))
    shrunk = rows[3:]                                    # three rows deleted while paging
    back = l.page(shrunk, ListQuery(limit=25, cursor=p2["page"]["prevCursor"]))
    assert back["items"][-1]["name"] == "n024"


def test_facets_count_the_filtered_rows():
    out = Lister(b"k").page(ROWS, ListQuery(limit=2), facets={"busy": lambda r: r["used"] >= 0.7})
    assert out["facets"] == {"busy": 2}


def test_tier_compare_names_the_approval_fact():
    cat = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    ch = cat.compare("prod", "large", cat.quota_for("prod", "large"), "small", cat.quota_for("prod", "small"),
                     used={"requests.cpu": "12", "requests.memory": "10Gi", "pods": "30"})
    assert ch.facts() == {"tierChange": "down", "quotaIncreasePct": -75.0, "quotaBelowRequested": True}
