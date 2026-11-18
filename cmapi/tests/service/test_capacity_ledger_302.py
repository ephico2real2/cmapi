"""#302 Capacity without the app or a database: the quota ledger's rules, the ledger against a full recount after random events
and relists (the arbitration's property test), the Node projection and the node watch's states, and capacity.yaml as code
reads it."""
from __future__ import annotations

import random
import weakref
from decimal import Decimal

import pytest
import yaml

from cmapi.core.capacity import CapacitySettings, group_figures, level, resource_figures
from cmapi.core.capacity_ledger import CapacityLedger, quota_facts, recount
from cmapi.core.clients.kube import WatchCache
from cmapi.core.clients.nodes import NodeCache, reduce_node
from conftest import ROOT, FakeKube

GI = 2**30


def quota(ns: str, hard: dict, *, name: str = "q", managed: bool = True, used: dict | None = None, scopes=None,
          selector=None) -> dict:
    spec: dict = {"hard": hard}
    if scopes is not None:
        spec["scopes"] = scopes
    if selector is not None:
        spec["scopeSelector"] = selector
    return {"kind": "ResourceQuota",
            "metadata": {"name": name, "namespace": ns, "labels": {"cmapi.net/managed": "true"} if managed else {}},
            "spec": spec, "status": {"used": used if used is not None else {k: "0" for k in hard}}}


def ledger_of(*quotas: dict) -> CapacityLedger:
    led = CapacityLedger()
    for q in quotas:
        led.admit("ResourceQuota", f"{q['metadata']['namespace']}/{q['metadata']['name']}", q)
    return led


# ---------------------------------------------------------------- the rules (docs/16)

def test_several_unscoped_quotas_in_one_namespace_commit_the_smallest_not_the_sum():
    """Kubernetes enforces every quota of a namespace, so the tightest binds. Before #302 the check summed them (20 cores)."""
    t = ledger_of(quota("a", {"requests.cpu": "8", "requests.memory": "16Gi"}, name="big"),
                  quota("a", {"requests.cpu": "12", "requests.memory": "4Gi"}, name="other")).totals()
    assert t.committed == {"cpu": Decimal(8), "memory": Decimal(4 * GI)}, "per resource, each its own smallest"
    assert t.namespaces == 1


def test_a_quota_that_bounds_neither_name_does_not_make_the_namespace_commit_zero():
    t = ledger_of(quota("a", {"requests.cpu": "8"}, name="cpu-only"), quota("a", {"pods": "10"}, name="pods")).totals()
    assert t.committed["cpu"] == 8 and t.committed["memory"] == 0


def test_scoped_quotas_are_left_out_and_counted():
    t = ledger_of(quota("a", {"requests.cpu": "8"}),
                  quota("a", {"requests.cpu": "1"}, name="besteffort", scopes=["BestEffort"]),
                  quota("b", {"requests.cpu": "4"}, name="prio",
                        selector={"matchExpressions": [{"operator": "In", "scopeName": "PriorityClass", "values": ["high"]}]}),
                  quota("c", {"requests.cpu": "2"}, name="empty-selector", selector={"matchExpressions": []})).totals()
    assert t.committed["cpu"] == 10, "a's 8 (the scoped 1 bounds only BestEffort pods), b nothing, c's 2 (no expression: unscoped)"
    assert t.scoped_quotas == 2 and t.namespaces == 2


def test_cpu_and_requests_cpu_on_one_quota_count_once_at_the_smaller_and_unmanaged_quotas_not_at_all():
    t = ledger_of(quota("a", {"requests.cpu": "100", "cpu": "10", "memory": "1Gi"}),
                  quota("b", {"requests.cpu": "50"}, managed=False)).totals()
    assert t.committed == {"cpu": Decimal(10), "memory": Decimal(GI)}
    assert quota_facts(quota("b", {"requests.cpu": "50"}, managed=False)) is None


def test_quota_used_is_the_binding_quotas_and_never_a_partial_sum():
    led = ledger_of(quota("a", {"requests.cpu": "8"}, used={"requests.cpu": "2500m"}),
                    quota("b", {"requests.cpu": "4"}, used={}))
    t = led.totals()
    assert t.used_missing["cpu"] == 1 and t.quota_used("cpu") is None, "b has not reported: the sum would be partial"
    led.admit("ResourceQuota", "b/q", quota("b", {"requests.cpu": "4"}, used={"requests.cpu": "1"}))
    assert led.totals().quota_used("cpu") == Decimal("3.5")


def test_equal_bounds_take_the_same_use_whatever_order_the_quotas_arrived_in():
    """Found by the property test below (seed 0, step 80): two quotas bounding memory at 1Gi with uses 0 and 100m; the use
    taken depended on a set's iteration order. Now the larger reported use, in either order."""
    one = quota("b", {"memory": "1Gi"}, name="q2", used={"memory": "0"})
    two = quota("b", {"memory": "1Gi"}, name="q3", used={"memory": "100m"})
    assert ledger_of(one, two).totals() == ledger_of(two, one).totals()
    assert ledger_of(one, two).totals().quota_used("memory") == Decimal("0.1")


def test_a_relist_that_no_longer_holds_a_quota_drops_it_and_a_modified_one_replaces_its_share():
    kube = FakeKube()
    led = CapacityLedger()
    cache = WatchCache(kube, ("ResourceQuota",), admit=led.admit, dropped=led.dropped)
    for ns in ("a", "b"):
        kube.objects[("ResourceQuota", ns, "q")] = quota(ns, {"requests.cpu": "8"})
    cache._list("ResourceQuota")
    assert led.totals().committed["cpu"] == 16
    del kube.objects[("ResourceQuota", "b", "q")]
    kube.objects[("ResourceQuota", "a", "q")] = quota("a", {"requests.cpu": "3"})
    cache._list("ResourceQuota")
    assert led.totals().committed["cpu"] == 3 and led.totals().namespaces == 1


# ---------------------------------------------------------------- the property test: the ledger equals a full recount

def _random_quota(rng: random.Random) -> dict:
    ns, name = rng.choice("abcdef"), rng.choice(("q1", "q2", "q3"))
    hard: dict = {}
    for names, units in ((("requests.cpu", "cpu"), ("500m", "1", "2", "8", "40")), (("requests.memory", "memory"), ("1Gi", "2G", "3Gi", "64Gi"))):
        for n in names:
            if rng.random() < 0.55:
                hard[n] = rng.choice(units)
    if rng.random() < 0.2:
        hard["pods"] = "10"
    used = {k: rng.choice(("0", "100m", "1", "512Mi")) for k in hard if rng.random() < 0.8}
    return quota(ns, hard, name=name, managed=rng.random() < 0.8, used=used,
                 scopes=["BestEffort"] if rng.random() < 0.15 else None)


@pytest.mark.parametrize("seed", range(40))
def test_the_ledger_equals_a_full_recount_after_random_events_and_relists(seed):
    rng = random.Random(seed)
    kube = FakeKube()
    led = CapacityLedger()
    cache = WatchCache(kube, ("ResourceQuota",), admit=led.admit, dropped=led.dropped)
    cache._list("ResourceQuota")
    for step in range(150):
        roll = rng.random()
        if roll < 0.55:                                            # ADDED or MODIFIED, seen by the watch
            q = _random_quota(rng)
            key = ("ResourceQuota", q["metadata"]["namespace"], q["metadata"]["name"])
            kind = "MODIFIED" if key in kube.objects else "ADDED"
            kube.objects[key] = q
            cache._event("ResourceQuota", {"type": kind, "object": q})
        elif roll < 0.8 and kube.objects:                          # DELETED, seen by the watch
            key = rng.choice(sorted(kube.objects))
            q = kube.objects.pop(key)
            cache._event("ResourceQuota", {"type": "DELETED", "object": q})
        elif roll < 0.9:                                           # changes the watch missed, then a relist
            for _ in range(rng.randint(1, 4)):
                if kube.objects and rng.random() < 0.5:
                    kube.objects.pop(rng.choice(sorted(kube.objects)))
                else:
                    q = _random_quota(rng)
                    kube.objects[("ResourceQuota", q["metadata"]["namespace"], q["metadata"]["name"])] = q
            cache._list("ResourceQuota")
        else:                                                      # a DELETED for a quota the cache never held
            cache._event("ResourceQuota", {"type": "DELETED", "object": quota("zz", {"requests.cpu": "1"}, name="ghost")})
            cache._event("ResourceQuota", {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": str(step)}}})
        if roll >= 0.8 and roll < 0.9:
            assert led.totals() == recount(kube.objects.values()), f"seed {seed} step {step}: after a relist"
        assert led.totals() == recount(cache.all("ResourceQuota")), f"seed {seed} step {step}"


# ---------------------------------------------------------------- nodes

def node(name: str, *, cpu="4", memory="16Gi", ready=True, unschedulable=False, taints=(), zone=None, images=0) -> dict:
    labels = {"kubernetes.io/hostname": name, **({"topology.kubernetes.io/zone": zone} if zone else {})}
    return {"kind": "Node", "metadata": {"name": name, "labels": labels, "annotations": {"a": "b" * 200}},
            "spec": {"unschedulable": unschedulable, "taints": [{"key": k, "effect": e} for k, e in taints]},
            "status": {"allocatable": {"cpu": cpu, "memory": memory, "pods": "250"},
                       "capacity": {"cpu": cpu, "memory": memory},
                       "conditions": [{"type": "MemoryPressure", "status": "False"},
                                      {"type": "Ready", "status": "True" if ready else "False"}],
                       "images": [{"names": [f"quay.io/x/image-{i}@sha256:{'a' * 64}"], "sizeBytes": 10**8} for i in range(images)]}}


def test_cordoned_not_ready_and_tainted_nodes_are_out_of_allocatable_and_counted():
    kube = FakeKube()
    for n in (node("w1", zone="us-central-1a"), node("w2", cpu="7800m", memory="20013044Ki", zone="us-central-1b"),
              node("cordoned", unschedulable=True, zone="us-central-1c"), node("down", ready=False),
              node("master", taints=[("node-role.kubernetes.io/master", "NoSchedule")]),
              node("evicting", taints=[("x", "NoExecute")]), node("prefer", taints=[("y", "PreferNoSchedule")])):
        kube.objects[("Node", "", n["metadata"]["name"])] = n
    cache = NodeCache(kube)
    cache.sync()
    snap = cache.snapshot()
    assert (snap.state, snap.total, snap.counted, snap.not_ready, snap.cordoned, snap.tainted) == ("ok", 7, 3, 1, 1, 2)
    assert snap.cpu == Decimal("15.8") and snap.memory == 2 * 16 * GI + 20013044 * 1024
    assert snap.zones == ("us-central-1a", "us-central-1b"), "the zones of the counted nodes, sorted"

    counting = NodeCache(kube, count_taints=["node-role.kubernetes.io/master"])
    counting.sync()
    assert counting.snapshot().counted == 4, "capacity.yaml countTaints lets a tainted node count"


def test_node_totals_follow_events_and_relists():
    kube = FakeKube()
    kube.objects[("Node", "", "w1")] = node("w1")
    cache = NodeCache(kube)
    cache.sync()
    cache.watch._event("Node", {"type": "MODIFIED", "object": node("w1", unschedulable=True)})
    cache.watch._event("Node", {"type": "ADDED", "object": node("w2", cpu="2", zone="z")})
    s = cache.snapshot()
    assert (s.total, s.counted, s.cordoned, s.cpu, s.zones) == (2, 1, 1, Decimal(2), ("z",))
    cache.watch._event("Node", {"type": "DELETED", "object": node("w2")})
    kube.objects = {("Node", "", "w3"): node("w3", cpu="1")}
    cache.sync()
    s = cache.snapshot()
    assert (s.total, s.counted, s.cpu, s.zones) == (1, 1, Decimal(1), ())


def test_a_node_projects_to_what_capacity_reads_without_its_images():
    import sys
    v = reduce_node(node("w1", images=2000, zone="us-central-1a"))
    size = sys.getsizeof(v) + sum(sys.getsizeof(x) for x in (v.cpu, v.memory, v.zone, v.taints))
    assert size < 1024, size
    assert not hasattr(v, "images") and v.ready and v.zone == "us-central-1a"


def test_a_chunked_node_list_holds_the_raw_nodes_of_one_page_at_most():
    """As #384 F2 for the reports: each page is projected before the next is asked for."""
    class Raw(dict):
        pass

    alive: list[weakref.ref] = []
    held_at_call: list[int] = []

    class Client(FakeKube):
        def list(self, kind, namespace=None, label_selector=None, resource_version=None, *, limit=None, continue_=None):
            held_at_call.append(sum(1 for r in alive if r() is not None))
            start = int(continue_ or 0)
            end = min(7, start + limit)
            items = [Raw(node(f"n{i}", images=50)) for i in range(start, end)]
            alive.extend(weakref.ref(o) for o in items)
            return {"metadata": {"resourceVersion": "9", **({"continue": str(end)} if end < 7 else {})}, "items": items}

    cache = NodeCache(Client(), chunk=2)
    cache.sync()
    assert cache.snapshot().total == 7 and len(held_at_call) == 4
    assert max(held_at_call) == 0, f"raw nodes still held when the next page was asked for: {held_at_call}"


def test_the_node_watch_states_never_give_figures_it_does_not_have():
    kube = FakeKube()
    cache = NodeCache(kube)
    assert cache.snapshot().state == "loading" and cache.snapshot().cpu is None
    kube.forbidden_kinds = {"Node"}
    cache.sync()
    s = cache.snapshot()
    assert s.state == "forbidden" and s.total is None and s.cpu is None and "nodes" in s.detail

    kube.forbidden_kinds = set()
    kube.objects[("Node", "", "w1")] = node("w1")
    cache.sync()
    assert cache.snapshot().state == "ok"
    with cache.watch._lock:                      # the grant revoked after the list: what was held is not current
        cache.watch.state["Node"].error_status, cache.watch.state["Node"].error = 403, "403 forbidden"
    assert cache.snapshot().state == "forbidden" and cache.snapshot().cpu is None
    with cache.watch._lock:
        cache.watch.state["Node"].error_status = None
        cache.watch.state["Node"].last_good -= WatchCache.RELIST_SECONDS + 5
    s = cache.snapshot()
    assert s.state == "stale" and s.cpu == 4, "stale keeps the last figures, marked"


def test_the_reader_role_grants_nodes_get_list_and_watch():
    role_file = ROOT.parent / "deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml"
    role = next(d for d in yaml.safe_load_all(role_file.read_text()) if d and d["kind"] == "ClusterRole")
    granted = {(g, r, v) for rule in role["rules"] for g in rule["apiGroups"] for r in rule["resources"] for v in rule["verbs"]}
    assert {("", "nodes", v) for v in ("get", "list", "watch")} <= granted


# ---------------------------------------------------------------- capacity.yaml and the arithmetic

def test_capacity_settings_defaults_and_refusals():
    s = CapacitySettings({"overcommit": {"dev": {"cpu": 2.0, "memory": 1.25}},
                          "targets": {"dev": {"commitment": {"warn": 0.8, "critical": 0.9}, "utilisation": {"warn": 0.7}}}})
    dev, rnd = s.env("dev"), s.env("rnd")
    assert (dev.overcommit, dev.overcommit_default, dev.warn, dev.critical) == (
        {"cpu": Decimal("2.0"), "memory": Decimal("1.25")}, False, Decimal("0.8"), Decimal("0.9"))
    assert (rnd.overcommit, rnd.overcommit_default, rnd.warn, rnd.critical) == (
        {"cpu": Decimal("1.0"), "memory": Decimal("1.0")}, True, Decimal("0.85"), Decimal("0.95"))
    assert s.count_taints == ()
    with pytest.raises(ValueError) as e:
        CapacitySettings({"countTaints": "node-role.kubernetes.io/infra", "overcommit": {"dev": {"cpu": "two"}}})
    assert "countTaints" in str(e.value) and "overcommit.dev.cpu" in str(e.value)


def test_levels_and_the_over_status():
    assert [level(Decimal(x), Decimal("0.85"), Decimal("0.95")) for x in ("0.5", "0.85", "0.95", "1", "1.01")] == [
        "ok", "warn", "critical", "critical", "over"]


def test_a_group_recomputes_its_ratio_floors_headroom_and_names_the_largest_placement():
    """docs/02's rules on two clusters: 1 of 10 and 90 of 100 committed is 0.8273, not the 0.55 average; one over-committed
    cluster's negative headroom does not offset the other's room."""
    env = CapacitySettings({}).env("dev")

    def cluster(cid, committed, size, mem_committed, mem_size):
        return {"clusterId": cid, "status": "ok",
                "cpu": resource_figures("cpu", committed=Decimal(committed), quota_used=None, used_missing=0,
                                        simulated=Decimal(size), allocatable=None, basis="simulated", env=env),
                "memory": resource_figures("memory", committed=Decimal(mem_committed), quota_used=None, used_missing=0,
                                           simulated=Decimal(mem_size), allocatable=None, basis="simulated", env=env)}

    g = group_figures([cluster("A", 1, 10, 30 * GI, 20 * GI), cluster("B", 90, 100, 10 * GI, 100 * GI)])
    assert g["cpu"]["commitment"] == round(91 / 110, 4) == 0.8273
    assert g["cpu"]["headroom"] == 19000 and g["cpu"]["largestPlacement"] == {"value": 10000, "clusterId": "B"}
    assert g["memory"]["headroom"] == 90 * GI, "A is 10 Gi over: floored at 0, not subtracted from B's 90 Gi"
    assert g["memory"]["largestPlacement"] == {"value": 90 * GI, "clusterId": "B"}
    assert g["memory"]["commitment"] == round(40 / 120, 4) and g["boundBy"] == "cpu"


def test_the_chart_passes_count_taints_into_capacity_yaml_only_when_set(tmp_path):
    """docs/18: `capacity.countTaints` in the values; the default renders capacity.yaml as before #302."""
    import subprocess

    from test_review_g_chart import CHART, CRC, PEM

    (tmp_path / "ca.crt").write_text(PEM)

    def capacity_yaml(*extra: str) -> dict:
        r = subprocess.run(["helm", "template", "cmapi", str(CHART), "-n", "cmapi", "-f", str(CRC),
                            "--set", "cmapi.digest=sha256:" + "a" * 64, "--set", "cmapi_portal.digest=sha256:" + "b" * 64,
                            "--set-file", f"trustedCA.certificates={tmp_path / 'ca.crt'}", *extra], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cm = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "ConfigMap" and "capacity.yaml" in d.get("data", {}))
        return yaml.safe_load(cm["data"]["capacity.yaml"])

    assert "countTaints" not in capacity_yaml()
    raw = capacity_yaml("--set", "capacity.countTaints={node-role.kubernetes.io/infra}")
    assert CapacitySettings(raw).count_taints == ("node-role.kubernetes.io/infra",)
