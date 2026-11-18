"""#302 Capacity at scale (the arbitration's required test): 50,000 managed quotas and 5,000 nodes on one cluster.

After the lists, a GET of /api/v1/capacity and a plan's capacity check read the ledger's and the node cache's totals: their cost
does not grow with the quotas or the nodes. Before #302 the check parsed every quota on every call (design B, M2: 337 ms per
10,000). The memory that the node cache keeps per node is measured with tracemalloc and printed with the timings."""
from __future__ import annotations

import gc
import statistics
import time
import tracemalloc

from test_capacity_302 import URL, VIEWER, crc
from test_capacity_ledger_302 import node, quota

QUOTAS, NODES, IMAGES = 50_000, 5_000, 40


def test_fifty_thousand_quotas_and_five_thousand_nodes(world, capsys):
    client, ctx, git, kube, validator, keys = world
    for i in range(QUOTAS):
        q = quota(f"ns-{i:05d}", {"requests.cpu": "500m", "requests.memory": "1Gi", "pods": "20"})
        kube.objects[("ResourceQuota", q["metadata"]["namespace"], "q")] = q
    for i in range(NODES):
        kube.objects[("Node", "", f"w{i:04d}")] = node(f"w{i:04d}", zone=f"us-central-1{'abc'[i % 3]}", images=IMAGES)
    st = crc(ctx)

    started = time.perf_counter()
    st.cache._list("ResourceQuota")
    list_quotas = time.perf_counter() - started

    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    started = time.perf_counter()
    st.nodes.sync()
    list_nodes = time.perf_counter() - started
    kept, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    for k in [k for k in kube.objects if k[0] == "Node"]:
        del kube.objects[k]                                # the fake's raw nodes are the fake's, not the cache's

    # One token, signed before the clock starts: signing an RS256 token takes about 60 ms here, and is the caller's, not the route's.
    token = {"Authorization": f"Bearer {keys.token('vera', **VIEWER)}"}
    client.get(URL, headers=token)                         # warm: imports and the first token verification
    timings = []
    for _ in range(9):
        started = time.perf_counter()
        r = client.get(URL, headers=token)
        timings.append(time.perf_counter() - started)
        assert r.status_code == 200
    gets = statistics.median(timings)
    started = time.perf_counter()
    for _ in range(100):
        cap = ctx.pipeline.capacity.check("CRC", "dev", 1, 2**30)
    check = (time.perf_counter() - started) / 100

    [c] = r.json()["clusters"]
    assert c["cpu"]["committed"] == QUOTAS * 500 and c["managedNamespaces"] == QUOTAS
    assert c["nodes"]["counted"] == NODES and c["cpu"]["allocatable"] == NODES * 4000 and c["zones"] == [
        "us-central-1a", "us-central-1b", "us-central-1c"]
    assert cap.detail["cpu"] == round((QUOTAS * 0.5 + 1) / 128, 3)
    per_node = (kept - base) / NODES
    with capsys.disabled():
        print(f"\n#302 scale: list {QUOTAS} quotas {list_quotas:.2f}s, list {NODES} nodes {list_nodes:.2f}s; "
              f"GET median {gets * 1000:.1f} ms; check {check * 1000:.3f} ms; node cache keeps {per_node:.0f} B per node "
              f"({(kept - base) / 2**20:.1f} MiB), peak during the list {(peak - base) / 2**20:.1f} MiB")
    assert gets < 0.050, f"GET took {gets * 1000:.1f} ms after the lists"
    assert check < 0.005, f"a plan's check took {check * 1000:.2f} ms"
    assert per_node < 2048, f"{per_node:.0f} B kept per node"
