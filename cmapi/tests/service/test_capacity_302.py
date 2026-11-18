"""#302 Capacity: GET /api/v1/capacity on the service suite's world, against fake clusters.

The world's CRC is in dev, region us-central, with simulatedCapacity 64 cores and 256Gi; dev's overcommit is 2.0 and 1.25 and
its targets 0.85 and 0.95. The quotas below are CRC's as measured on 2026-11-17 (design A, section 7): five of 8 cores and
16Gi and one of 32 cores and 64Gi, so 72 cores and 144Gi committed, against one node of 7800m and 20013044Ki allocatable."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cmapi.core.capacity_ledger import CapacityLedger
from cmapi.core.clients.kube import CacheState, WatchCache
from cmapi.core.clients.nodes import NodeCache
from cmapi.core.registry import ClusterPolicy, ClusterState
from conftest import FakeKube, build_world
from test_capacity_ledger_302 import node, quota

GI = 2**30
URL = "/api/v1/capacity"
VIEWER = dict(roles=["cmapi-viewer"], groups=["/cmapi/app-cmapi-rbac-viewer"])
BOT_RND = dict(roles=["cmapi-bot-rnd"], groups=[])                 # capacity:read in rnd only (authz-roles.yaml)
RELAY = dict(roles=["cmapi-approval-relay"], groups=[])            # no capacity:read anywhere
CRC_QUOTAS = [quota(f"cmapi-live-{x}", {"requests.cpu": "8", "requests.memory": "16Gi", "pods": "20"}) for x in "abcdf"] + [
    quota("cmapi-live-e", {"requests.cpu": "32", "requests.memory": "64Gi"})]


def get(client, keys, url=URL, who=VIEWER, user="vera", headers=None):
    return client.get(url, headers={"Authorization": f"Bearer {keys.token(user, **who)}", **(headers or {})})


def body(client, keys, url=URL, **kw) -> dict:
    r = get(client, keys, url, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def crc(ctx) -> ClusterState:
    return ctx.registry.clusters["CRC"]


def load_crc(ctx, kube, quotas=CRC_QUOTAS, nodes=(node("crc", cpu="7800m", memory="20013044Ki"),)) -> None:
    """CRC's quotas and nodes, listed as the watch lists them."""
    for q in quotas:
        kube.objects[("ResourceQuota", q["metadata"]["namespace"], q["metadata"]["name"])] = q
    for n in nodes:
        kube.objects[("Node", "", n["metadata"]["name"])] = n
    crc(ctx).cache._list("ResourceQuota")
    crc(ctx).nodes.sync()


def add_cluster(ctx, cluster_id: str, env: str, *, region: str | None = "us-central", simulated=None, writes=True,
                quotas=(), nodes=()) -> tuple[FakeKube, ClusterState]:
    """A second connected cluster beside CRC, its caches listed in this thread."""
    kube = FakeKube(cluster_id)
    for q in quotas:
        kube.objects[("ResourceQuota", q["metadata"]["namespace"], q["metadata"]["name"])] = q
    for n in nodes:
        kube.objects[("Node", "", n["metadata"]["name"])] = n
    policy = ClusterPolicy(cluster_id, env, f"clusters/{cluster_id}", writes=writes,
                           labels={"region": region} if region else {}, simulated_capacity=simulated)
    st = ClusterState(cluster_id, policy, status="connected", client=kube, checked_at=datetime.now(timezone.utc))
    st.ledger = CapacityLedger()
    st.cache = WatchCache(kube, admit=st.ledger.admit, dropped=st.ledger.dropped)
    for kind in st.cache.kinds:
        st.cache._list(kind)
    st.nodes = NodeCache(kube)
    st.nodes.sync()
    ctx.registry.clusters[cluster_id] = st
    return kube, st


# ---------------------------------------------------------------- what CRC shows (the arbitration, "What CRC must show")

def test_crc_one_group_simulated_basis_with_the_nodes_allocatable_beside_it(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube, CRC_QUOTAS + [quota("openshift-x", {"requests.cpu": "100"}, managed=False)])
    page = body(client, keys)
    assert (page["source"], page["snapshotState"], page["groupBy"], page["hiddenClusters"]) == (
        "live", "not-built", ["region", "environment"], 0)
    assert page["notMeasured"] == ["requested", "usedAvg", "usedPeak", "history"]
    assert page["targets"] == [{"env": e, "overcommit": {"cpu": 2.0, "memory": 1.25}, "overcommitDefault": False,
                                "commitment": {"warn": 0.85, "critical": 0.95}} for e in ("dev", "rnd")]
    [c] = page["clusters"]
    assert (c["clusterId"], c["env"], c["region"], c["writes"], c["state"], c["stateDetail"], c["basis"]) == (
        "CRC", "dev", "us-central", True, "ok", None, "simulated")
    assert (c["nodesState"], c["zones"], c["nodes"]) == ("ok", [], {"total": 1, "counted": 1, "notReady": 0, "cordoned": 0,
                                                                     "tainted": 0})
    assert (c["managedNamespaces"], c["scopedQuotas"], c["status"], c["boundBy"], c["history"]) == (6, 0, "ok", "cpu", None)
    assert c["cpu"] == {"unit": "millicores", "simulated": 64000, "allocatable": 7800, "overcommit": 2.0, "limit": 128000,
                        "committed": 72000, "quotaUsed": 0, "quotaUsedMissing": 0, "headroom": 56000, "commitment": 0.5625,
                        "status": "ok", "requested": None, "usedAvg": None, "usedPeak": None}
    assert c["memory"] == {"unit": "bytes", "simulated": 256 * GI, "allocatable": 20013044 * 1024, "overcommit": 1.25,
                           "limit": 320 * GI, "committed": 144 * GI, "quotaUsed": 0, "quotaUsedMissing": 0,
                           "headroom": 176 * GI, "commitment": 0.45, "status": "ok", "requested": None, "usedAvg": None,
                           "usedPeak": None}
    as_of = datetime.fromisoformat(c["asOf"].replace("Z", "+00:00"))
    assert as_of.second == 0 and as_of.microsecond == 0 and abs(time.time() - as_of.timestamp()) < 120
    [g] = page["groups"]
    assert (g["key"], g["name"], g["clusterIds"], g["matching"], g["included"], g["coverage"], g["excluded"], g["status"],
            g["boundBy"]) == ({"region": "us-central", "environment": "dev"}, "us-central · dev", ["CRC"], 1, 1, 1.0, [], "ok", "cpu")
    assert g["statusCounts"] == {"ok": 1, "warn": 0, "critical": 0, "over": 0}
    assert g["cpu"] == {"unit": "millicores", "committed": 72000, "limit": 128000, "commitment": 0.5625, "headroom": 56000,
                        "largestPlacement": {"value": 56000, "clusterId": "CRC"}}
    assert g["memory"]["commitment"] == 0.45 and g["memory"]["largestPlacement"] == {"value": 176 * GI, "clusterId": "CRC"}


def test_no_namespace_is_named_in_the_answer(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    text = get(client, keys).text
    assert "cmapi-live" not in text and "openshift" not in text


def test_the_plan_and_the_tab_agree(world):
    """One computation: the plan's capacity ratio at no change equals the tab's commitment for the same ledger."""
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    [c] = body(client, keys)["clusters"]
    cap = ctx.pipeline.capacity.check("CRC", "dev", 0, 0)
    assert (cap.detail["cpu"], cap.detail["memory"]) == (round(c["cpu"]["commitment"], 3), round(c["memory"]["commitment"], 3))
    assert cap.status == "fits" and cap.fresh is True


# ---------------------------------------------------------------- the behaviour changes of the plan's check (#302)

def test_the_check_counts_the_smallest_unscoped_quota_of_a_namespace_not_their_sum(world):
    """Before #302 the check summed every managed quota: 8 + 2 + 120 (scoped) = 130 cores, `exceeded` against 128.
    Kubernetes binds the namespace at its tightest unscoped quota, 2 cores; the scoped one bounds BestEffort pods only."""
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube, [quota("payments-dev", {"requests.cpu": "8"}, name="a"),
                         quota("payments-dev", {"requests.cpu": "2"}, name="b"),
                         quota("payments-dev", {"requests.cpu": "120"}, name="c", scopes=["BestEffort"])], ())
    cap = ctx.pipeline.capacity.check("CRC", "dev", 0, 0)
    assert cap.status == "fits" and cap.detail["cpu"] == round(2 / 128, 3), cap
    [c] = body(client, keys)["clusters"]
    assert c["cpu"]["committed"] == 2000 and c["scopedQuotas"] == 1 and c["managedNamespaces"] == 1


# ---------------------------------------------------------------- the basis: simulated, else the nodes

@pytest.fixture
def unsized(test_config: Path, fresh_db, keys, monkeypatch, tmp_path):
    """The world with no simulatedCapacity for CRC: its basis is the nodes' allocatable."""
    d = tmp_path / "config"
    d.mkdir()
    for f in test_config.iterdir():
        (d / f.name).write_text(f.read_text())
    (d / "clusters.yaml").write_text("clusters:\n  CRC:\n    environment: dev\n    gitopsPath: clusters/CRC\n"
                                     "    labels: {region: us-central}\n")
    with build_world(d, keys, monkeypatch) as w:
        yield w


def test_without_a_simulated_size_the_basis_is_allocatable_and_over_shows_its_real_figure(unsized):
    client, ctx, git, kube, validator, keys = unsized
    load_crc(ctx, kube)
    [c] = body(client, keys)["clusters"]
    assert (c["state"], c["basis"], c["cpu"]["simulated"], c["cpu"]["allocatable"], c["cpu"]["limit"]) == (
        "ok", "allocatable", None, 7800, 15600)
    assert c["cpu"]["commitment"] == round(72 / 15.6, 4) and c["cpu"]["status"] == "over" and c["cpu"]["headroom"] == -56400
    assert c["status"] == "over" and c["boundBy"] == "memory", "memory 144Gi of 23.86Gi is the higher"
    [g] = body(client, keys)["groups"]
    assert g["status"] == "over" and g["cpu"]["headroom"] == 0 and g["cpu"]["largestPlacement"]["value"] == 0
    cap = ctx.pipeline.capacity.check("CRC", "dev", 0, 0)
    assert cap.status == "unknown", "the plan keeps simulatedCapacity as its basis until cmapi-capacity (#21): the owner, 2026-11-18"


def test_without_a_simulated_size_and_with_nodes_forbidden_the_cluster_has_no_size(unsized):
    client, ctx, git, kube, validator, keys = unsized
    kube.forbidden_kinds = {"Node"}
    load_crc(ctx, kube)
    page = body(client, keys)
    [c] = page["clusters"]
    assert (c["state"], c["basis"], c["nodesState"], c["nodes"], c["zones"]) == ("no-size", None, "forbidden", None, None)
    assert "nodes" in c["stateDetail"] and c["cpu"]["committed"] == 72000, "what is committed is still known"
    assert (c["cpu"]["limit"], c["cpu"]["commitment"], c["cpu"]["headroom"], c["status"]) == (None, None, None, None)
    [g] = page["groups"]
    assert (g["included"], g["excluded"][0]["reason"], g["cpu"], g["status"], g["coverage"]) == (0, "no-size", None, None, 0.0)


def test_nodes_forbidden_with_a_simulated_size_keeps_the_commitment(world):
    client, ctx, git, kube, validator, keys = world
    kube.forbidden_kinds = {"Node"}
    load_crc(ctx, kube)
    [c] = body(client, keys)["clusters"]
    assert (c["state"], c["basis"], c["nodesState"], c["zones"], c["cpu"]["allocatable"]) == (
        "ok", "simulated", "forbidden", None, None)
    assert "get, list and watch on nodes" in c["nodesDetail"] and c["cpu"]["commitment"] == 0.5625


# ---------------------------------------------------------------- unknown is null, never 0

@pytest.mark.parametrize("case", ["quotas-not-listed", "quotas-forbidden", "unreachable"])
def test_an_unknown_commitment_is_null_with_a_named_state_and_left_out_of_its_group(world, case):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    st = crc(ctx)
    if case == "quotas-not-listed":
        with st.cache._lock:
            st.cache.state["ResourceQuota"] = CacheState()
        want = "loading"
    elif case == "quotas-forbidden":
        with st.cache._lock:
            st.cache.state["ResourceQuota"].error_status, st.cache.state["ResourceQuota"].error = 403, "403 forbidden"
        want = "forbidden"
    else:
        st.status, st.findings = "unreachable", ["CRC: ConnectError"]
        want = "unreachable"
    page = body(client, keys)
    [c] = page["clusters"]
    assert c["state"] == want and c["stateDetail"]
    for r in ("cpu", "memory"):
        assert all(c[r][k] is None for k in ("committed", "quotaUsed", "quotaUsedMissing", "headroom", "commitment", "status"))
    assert (c["status"], c["boundBy"], c["managedNamespaces"]) == (None, None, None)
    [g] = page["groups"]
    assert (g["included"], g["excluded"][0]["reason"], g["cpu"], g["memory"], g["status"]) == (0, want, None, None, None)
    if case == "unreachable":
        assert c["asOf"] is not None and c["nodesState"] == "unreachable"


def test_a_stale_cluster_keeps_its_last_figures_marked_and_is_left_out_of_its_group(world):
    """The owner, 2026-11-18: last figures, marked "stale since HH:MM", left out of group sums."""
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    st = crc(ctx)
    with st.cache._lock:
        st.cache.state["ResourceQuota"].last_good = time.time() - WatchCache.RELIST_SECONDS - 120
    page = body(client, keys)
    [c] = page["clusters"]
    assert c["state"] == "stale" and "stale" in c["stateDetail"]
    assert c["cpu"]["committed"] == 72000 and c["cpu"]["commitment"] == 0.5625, "the last figures, kept"
    [g] = page["groups"]
    assert g["excluded"] == [{"clusterId": "CRC", "reason": "stale", "asOf": c["asOf"]}] and g["cpu"] is None
    assert ctx.pipeline.capacity.check("CRC", "dev", 0, 0).status == "unknown", "the plan does not use stale figures"


def test_quota_used_is_null_when_a_binding_quota_has_not_reported_its_use(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube, [quota("a", {"requests.cpu": "8"}, used={"requests.cpu": "1"}), quota("b", {"requests.cpu": "8"}, used={})])
    [c] = body(client, keys)["clusters"]
    assert (c["cpu"]["quotaUsed"], c["cpu"]["quotaUsedMissing"], c["cpu"]["committed"]) == (None, 1, 16000)


def test_a_read_only_cluster_shows_its_figures_and_is_left_out_as_not_writable(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    crc(ctx).policy.writes = False
    try:
        page = body(client, keys)
    finally:
        crc(ctx).policy.writes = True
    [c] = page["clusters"]
    [g] = page["groups"]
    assert c["state"] == "ok" and c["cpu"]["commitment"] == 0.5625 and c["writes"] is False
    assert g["excluded"][0]["reason"] == "not-writable" and g["included"] == 0


# ---------------------------------------------------------------- groups over several clusters

def test_a_group_recomputes_its_ratio_and_a_mixed_group_takes_its_worst_cluster(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)                                                          # dev: 72 of 128 cores, ok
    add_cluster(ctx, "OCP_GF6", "dev", simulated={"cpu": 10, "memory": "100Gi"},
                quotas=[quota("x", {"requests.cpu": "19", "requests.memory": "10Gi"})])  # 19 of 20 cores: 0.95, critical
    add_cluster(ctx, "OCP_GF7", "rnd", region="eu-west", simulated={"cpu": 4, "memory": "8Gi"},
                quotas=[quota("y", {"requests.cpu": "1", "requests.memory": "1Gi"})])
    page = body(client, keys)
    names = [g["name"] for g in page["groups"]]
    assert names == ["eu-west · rnd", "us-central · dev"]
    dev = page["groups"][1]
    assert dev["cpu"]["commitment"] == round(91 / 148, 4), "summed numerators and denominators, not the mean of 0.5625 and 0.95"
    assert dev["cpu"]["headroom"] == 56000 + 1000 and dev["cpu"]["largestPlacement"] == {"value": 56000, "clusterId": "CRC"}
    assert dev["status"] == "critical" and dev["statusCounts"] == {"ok": 1, "warn": 0, "critical": 1, "over": 0}

    by_region = body(client, keys, URL + "?groupBy=region")["groups"]
    assert [(g["name"], g["matching"]) for g in by_region] == [("eu-west", 1), ("us-central", 2)]
    by_label = body(client, keys, URL + "?groupBy=label:region,environment")["groups"]
    assert by_label[1]["key"] == {"label:region": "us-central", "environment": "dev"}


def test_a_cluster_without_a_region_groups_under_a_dash(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    add_cluster(ctx, "OCP_GF9", "dev", region=None, simulated={"cpu": 4, "memory": "8Gi"})
    groups = body(client, keys)["groups"]
    assert ("— · dev", {"region": None, "environment": "dev"}) in [(g["name"], g["key"]) for g in groups]


# ---------------------------------------------------------------- scope and refusals

def test_only_the_environments_where_the_caller_reads_capacity(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    add_cluster(ctx, "OCP_GF7", "rnd", simulated={"cpu": 4, "memory": "8Gi"})
    page = body(client, keys, who=BOT_RND, user="bot")
    assert [c["clusterId"] for c in page["clusters"]] == ["OCP_GF7"] and page["hiddenClusters"] == 1
    assert [t["env"] for t in page["targets"]] == ["rnd"] and [g["name"] for g in page["groups"]] == ["us-central · rnd"]
    assert "CRC" not in json.dumps(page)


@pytest.mark.parametrize("url, who, status, code", [
    (URL, RELAY, 403, "forbidden"),
    (URL + "?env=dev", BOT_RND, 403, "environment-forbidden"),
    (URL + "?env=qa", VIEWER, 422, "environment-not-served"),
    (URL + "?clusterId=OCP_NOPE", VIEWER, 404, "cluster-not-found"),
    (URL + "?clusterId=CRC", BOT_RND, 404, "cluster-not-found"),
    (URL + "?groupBy=zone", VIEWER, 422, "validation-failed"),
    (URL + "?groupBy=", VIEWER, 422, "validation-failed"),
    (URL + "?groupBy=region,region", VIEWER, 422, "validation-failed"),
    (URL + "?groupBy=region,environment,label:a,label:b", VIEWER, 422, "validation-failed"),
    (URL + "?groupBy=label:", VIEWER, 422, "validation-failed"),
])
def test_refusals(world, url, who, status, code):
    client, ctx, git, kube, validator, keys = world
    r = get(client, keys, url, who=who)
    assert (r.status_code, r.json()["code"]) == (status, code), r.text


def test_filters_by_environment_and_cluster(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    add_cluster(ctx, "OCP_GF7", "rnd", simulated={"cpu": 4, "memory": "8Gi"})
    assert [c["clusterId"] for c in body(client, keys, URL + "?env=rnd")["clusters"]] == ["OCP_GF7"]
    assert [c["clusterId"] for c in body(client, keys, URL + "?clusterId=CRC")["clusters"]] == ["CRC"]
    assert body(client, keys, URL + "?clusterId=CRC&env=rnd")["clusters"] == []


# ---------------------------------------------------------------- the strong ETag

def test_the_etag_answers_304_moves_with_a_quota_and_not_with_a_bookmark_in_the_same_minute(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    st = crc(ctx)
    minute = int(time.time()) // 60 * 60
    st.cache.clock = lambda: minute + 5
    st.cache._event("ResourceQuota", {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": "100"}}})
    first = get(client, keys)
    tag = first.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache" and tag.startswith('"') and not tag.startswith("W/")
    again = get(client, keys, headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == tag
    assert get(client, keys, headers={"If-None-Match": f"W/{tag}"}).status_code == 304, "weak comparison (RFC 9110 13.1.2)"

    st.cache.clock = lambda: minute + 50
    st.cache._event("ResourceQuota", {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": "101"}}})
    assert get(client, keys).headers["etag"] == tag, "a later read in the same minute changes no byte"

    st.cache._event("ResourceQuota", {"type": "ADDED", "object": quota("new-ns", {"requests.cpu": "1"})})
    moved = get(client, keys, headers={"If-None-Match": tag})
    assert moved.status_code == 200 and moved.headers["etag"] != tag


def test_two_scopes_get_two_tags(world):
    client, ctx, git, kube, validator, keys = world
    load_crc(ctx, kube)
    add_cluster(ctx, "OCP_GF7", "rnd", simulated={"cpu": 4, "memory": "8Gi"})
    assert get(client, keys).headers["etag"] != get(client, keys, who=BOT_RND, user="bot").headers["etag"]
