"""#402: a view reads each of a cluster's caches once, since the registry may clear them while the view is built.

The registry clears `reports` and `nodes` in `_stop_caches` and sets `cache` to None in `_set` and in the relist when a
cluster drops, from its own thread. A view that checks a cache and then reads it again could read None the second time: a
500 for every caller (the #400 fault on `st.nodes`, here on `st.reports`, `st.cache` and `ClusterRegistry.cache`). Each test
swaps the cluster's state for one whose cache reads as itself once and as None after, which is that clear landing between
the two reads, and the route must still answer 200.

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_cache_read_once_402.py -q -W ignore
"""
from __future__ import annotations

import dataclasses

from cmapi.core.registry import ClusterState
from test_flow import OLA, auth
from test_policies_302 import RESULTS, kyverno  # noqa: F401 - the fixture: CRC with Kyverno, its bundle and reports


def cleared(ctx, attr: str, after: int = 1, cluster_id: str = "CRC") -> list[int]:
    """Put in the registry a copy of the cluster's state whose `attr` reads as its value `after` times and as None from then
    on: the registry's clear landing between two reads of one request. Returns the list of reads, one entry each."""
    st = ctx.registry.clusters[cluster_id]
    value, reads = getattr(st, attr), []

    def read(self):
        reads.append(1)
        return value if len(reads) <= after else None

    flicker = type("Cleared", (ClusterState,), {attr: property(read, lambda self, v: None)})
    ctx.registry.clusters[cluster_id] = flicker(**{f.name: getattr(st, f.name) for f in dataclasses.fields(ClusterState)})
    return reads


def get(client, keys, path):
    return client.get(path, headers=auth(keys, "ola", **OLA))


def test_policy_results_read_the_report_cache_once(kyverno):  # noqa: F811
    client, ctx, git, kube, validator, keys = kyverno
    reads = cleared(ctx, "reports")
    r = get(client, keys, RESULTS)
    assert r.status_code == 200, r.text
    [cl] = r.json()["clusters"]
    assert cl["state"] == "ok" and cl["counts"]["fail"] >= 1, cl
    assert len(reads) == 1


def test_policy_results_read_the_namespace_cache_once(kyverno):  # noqa: F811
    """The managed namespaces come from the cache whose freshness was checked: a second read would be None (a 500), or a new
    cache with no namespace listed, which would hide every result as unmanaged."""
    client, ctx, git, kube, validator, keys = kyverno
    before = get(client, keys, RESULTS).json()["clusters"][0]
    reads = cleared(ctx, "cache")
    r = get(client, keys, RESULTS)
    assert r.status_code == 200, r.text
    [cl] = r.json()["clusters"]
    assert (cl["state"], cl["counts"], cl["hidden"]) == (before["state"], before["counts"], before["hidden"]), cl
    assert len(reads) == 1


def test_expirations_skip_a_cluster_whose_cache_was_cleared_after_it_was_listed_as_connected(world):
    """`connected()` reads the status; the relist may then clear the cache before the view reads it."""
    client, ctx, git, kube, validator, keys = world
    cleared(ctx, "cache", after=0)
    r = get(client, keys, "/api/v1/expirations")
    assert r.status_code == 200, r.text
    assert r.json()["items"] == [] and r.json()["rules"] == {}


def test_quotas_skip_a_cluster_whose_cache_was_cleared_after_it_was_listed_as_connected(world):
    client, ctx, git, kube, validator, keys = world
    cleared(ctx, "cache", after=0)
    r = get(client, keys, "/api/v1/quotas")
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


def test_the_registry_returns_the_cache_it_checked(world):
    """`ClusterRegistry.cache` checked `st.cache` and then returned a second read of it: None, on which the namespaces
    routes, the plan and the watch sync then call a method."""
    client, ctx, git, kube, validator, keys = world
    cache = ctx.registry.clusters["CRC"].cache
    reads = cleared(ctx, "cache")
    assert ctx.registry.cache("CRC") is cache and len(reads) == 1


def test_the_namespaces_list_reads_the_cache_the_registry_checked(world):
    client, ctx, git, kube, validator, keys = world
    cleared(ctx, "cache")
    r = get(client, keys, "/api/v1/clusters/CRC/namespaces")
    assert r.status_code == 200, r.text
