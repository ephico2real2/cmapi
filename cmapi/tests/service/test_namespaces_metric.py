"""#172 (BUG-43): cmapi_namespaces has a sample for each state of each listed cluster, and cmapi_sync_drift_total is not
declared while no code feeds it. docs/17: "Managed coverage" and "Drift events"."""
from __future__ import annotations

import re

from prometheus_client import REGISTRY, generate_latest

import cmapi.core.observability as observability
from cmapi.core.kpi import namespace_counts
from test_flow import NS, OLA, auth, run_jobs


def samples() -> dict[tuple[str, str], float]:
    text = generate_latest(REGISTRY).decode()
    return {(m[1], m[2]): float(m[3]) for m in re.finditer(r'^cmapi_namespaces\{cluster_id="([^"]+)",state="([^"]+)"\} (\S+)$', text, re.M)}


def test_cmapi_namespaces_counts_managed_unmanaged_and_excluded_from_the_watch_cache(world):
    client, ctx, git, kube, validator, keys = world
    assert client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).status_code == 202
    run_jobs(ctx)                                             # payments-dev: synced, with the label cmapi.net/managed=true
    kube.add_unmanaged_namespace("legacy-app")               # another project's namespace
    kube.add_unmanaged_namespace("openshift-monitoring")     # a built-in reserved name
    kube.add_unmanaged_namespace("ocp-tools")                # the instance's reservedPatterns: ocp-*
    ctx.registry.cache("CRC")._list("Namespace")
    assert samples() == {("CRC", "managed"): 1.0, ("CRC", "unmanaged"): 1.0, ("CRC", "excluded"): 2.0}
    kube.add_unmanaged_namespace("second-app")
    ctx.registry.cache("CRC")._list("Namespace")
    assert samples()[("CRC", "unmanaged")] == 2.0, "the value is read at each scrape"


def test_a_cluster_whose_namespaces_are_not_listed_has_no_sample(world):
    """Not measured is absent, never 0: a 0 would read as a cluster with no namespace."""
    client, ctx, git, kube, validator, keys = world
    state = ctx.registry.cache("CRC").state["Namespace"]
    listed, state.last_good = state.last_good, None
    try:
        assert namespace_counts(ctx.registry, ()) == {} and samples() == {}
    finally:
        state.last_good = listed
    assert ("CRC", "managed") in samples()


def test_no_drift_counter_is_declared_while_no_code_feeds_it(world):
    assert not hasattr(observability, "SYNC_DRIFT") and not hasattr(observability, "NAMESPACES")
    assert "cmapi_sync_drift" not in generate_latest(REGISTRY).decode()
