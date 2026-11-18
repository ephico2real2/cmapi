"""OB3's tests for #400 (Capacity), DB-free: a read that pairs an old watch cache with a new ledger (the #393 fault), and the
capacity.yaml and clusters.yaml values that the plan's check and GET /api/v1/capacity divide by or read."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cmapi.core.capacity import CapacitySettings
from cmapi.core.capacity_backend import SimulatedCapacity, read_quotas
from cmapi.core.capacity_ledger import CapacityLedger
from cmapi.core.clients.kube import WatchCache
from cmapi.core.registry import ClusterPolicy, ClusterRegistry, load_policies
from conftest import FakeKube
from test_capacity_ledger_302 import quota

ROOT = Path(__file__).resolve().parents[3]


def connected():
    """One connected cluster "C" in dev, sized 16 cores and 64Gi, its one quota of 16 cores and 32Gi listed, as the registry's
    `_connect` leaves it."""
    kube = FakeKube("C")
    kube.objects[("ResourceQuota", "a", "q")] = quota("a", {"requests.cpu": "16", "requests.memory": "32Gi"})
    policy = ClusterPolicy("C", "dev", "clusters/C", simulated_capacity={"cpu": "16", "memory": "64Gi"})
    reg = ClusterRegistry({"C": policy}, None, start_caches=False)
    st = reg.clusters["C"]
    st.status, st.client = "connected", kube
    st.ledger = CapacityLedger()
    st.cache = WatchCache(kube, admit=st.ledger.admit, dropped=st.ledger.dropped)
    st.cache._list("ResourceQuota")
    return reg, st, kube


def rebuilt_during_the_read(st, kube) -> None:
    """The registry rebuilds the cluster's cache and ledger (its import changed: a token rotation) while a read is between
    checking the cache's freshness and summing the ledger: `_connect`'s stores land at that point."""
    old = st.cache
    real = old.kind_error

    def kind_error(kind):
        st.ledger = CapacityLedger()
        st.cache = WatchCache(kube, admit=st.ledger.admit, dropped=st.ledger.dropped)
        return real(kind)

    old.kind_error = kind_error


def test_a_read_never_pairs_the_cache_it_checked_with_the_ledger_of_a_cache_built_since():
    reg, st, kube = connected()
    rebuilt_during_the_read(st, kube)
    read = read_quotas(reg, "C")
    assert read.state != "ok" or read.totals.committed["cpu"] == 16, (read.state, read.totals)


def test_a_plan_that_exceeds_the_cluster_never_fits_while_its_caches_are_rebuilt():
    """16 of 16 cores committed, a plan for one more: `exceeded`, or `unknown`; never `fits` on fresh data (#393)."""
    reg, st, kube = connected()
    rebuilt_during_the_read(st, kube)
    cap = SimulatedCapacity(reg, CapacitySettings({})).check("C", "dev", 1.0, 0.0)
    assert cap.status in ("exceeded", "unknown"), cap


def test_an_overcommit_of_zero_stops_the_start_instead_of_failing_each_plan():
    """The plan's check divides by size × overcommit: with 0 every plan in the environment raised DivisionByZero."""
    with pytest.raises(ValueError) as e:
        CapacitySettings({"overcommit": {"dev": {"cpu": 0, "memory": 1.0}}})
    assert "overcommit.dev.cpu" in str(e.value) and "above 0" in str(e.value)


@pytest.mark.parametrize("raw, where", [
    ({"targets": {"dev": 0.85}}, "targets.dev"),
    ({"overcommit": [{"cpu": 2}]}, "overcommit:"),
])
def test_a_capacity_block_that_is_not_a_mapping_is_named_not_ignored_or_a_traceback(raw, where):
    with pytest.raises(ValueError) as e:
        CapacitySettings(raw)
    assert where in str(e.value)


def test_the_example_and_deployed_capacity_and_clusters_files_still_load(tmp_path):
    """Behaviour kept: every capacity.yaml and clusters.yaml this repository ships still loads."""
    CapacitySettings(yaml.safe_load((ROOT / "examples/config/capacity.yaml").read_text()))
    for env in ("kind", "crc"):
        cm = yaml.safe_load((ROOT / f"deploy/manifests/environments/{env}/20-config.yaml").read_text())
        CapacitySettings(yaml.safe_load(cm["data"]["capacity.yaml"]))
        f = tmp_path / f"{env}-clusters.yaml"
        f.write_text(cm["data"]["clusters.yaml"])
        assert load_policies(f, {"dev", "rnd"})
    assert load_policies(ROOT / "examples/local/config/clusters.yaml", {"dev", "rnd"})


@pytest.mark.parametrize("size, why", [
    ({"cpu": "64"}, "has no memory"),
    ({"cpu": "abc", "memory": "1Gi"}, "cpu is not a Kubernetes quantity"),
    ({"cpu": "0", "memory": "1Gi"}, "cpu must be above 0"),
    ("64 cores", "must be a mapping"),
])
def test_a_simulated_capacity_that_cannot_size_a_cluster_stops_the_start(size, why, tmp_path):
    """Before: loaded, then GET /api/v1/capacity raised for every caller of the environment (KeyError, ValueError) and each plan
    on the cluster raised (KeyError, ValueError, DivisionByZero)."""
    f = tmp_path / "clusters.yaml"
    f.write_text(yaml.safe_dump({"clusters": {"C": {"environment": "dev", "simulatedCapacity": size}}}))
    with pytest.raises(ValueError) as e:
        load_policies(f, {"dev"})
    assert "cluster C: simulatedCapacity" in str(e.value) and why in str(e.value)


def test_a_cluster_view_reads_the_node_cache_once_while_the_registry_may_clear_it():
    """`_stop_caches` sets `st.nodes = None` when the registry rebuilds or drops a cluster's caches. The view read `st.nodes`
    twice (is it None? then .snapshot()), so a clear between the two raised AttributeError: a 500 for the whole fleet view."""
    from types import SimpleNamespace

    from cmapi.core.clients.nodes import NodeCache
    from cmapi.core.registry import ClusterState
    from cmapi.plugins.capacity.router import cluster_view
    from test_capacity_ledger_302 import node

    reg, st, kube = connected()
    kube.objects[("Node", "", "n")] = node("n")
    nodes = NodeCache(kube)
    nodes.sync()

    class ClearedAfterFirstRead(ClusterState):
        reads = 0

        @property
        def nodes(self):
            ClearedAfterFirstRead.reads += 1
            return nodes if ClearedAfterFirstRead.reads == 1 else None

        @nodes.setter
        def nodes(self, value):
            pass

    flick = ClearedAfterFirstRead(st.cluster_id, st.policy, status="connected", client=kube, cache=st.cache, ledger=st.ledger)
    reg.clusters["C"] = flick
    view = cluster_view(SimpleNamespace(capacity=CapacitySettings({}), registry=reg), flick, "dev")
    assert view["nodesState"] == "ok" and view["cpu"]["allocatable"] == 4000 and view["cpu"]["committed"] == 16000
