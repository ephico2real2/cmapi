#!/usr/bin/env python3
"""The plan's capacity check on one set of quotas, run on a tree of cmapi: what #302 changes in `SimulatedCapacity.check()`.

    PYTHONPATH=<tree>/cmapi/src:<tree>/cmapi/tests/service python check-before-after.py

CRC as the service suite has it: simulatedCapacity 64 cores and 256Gi, dev overcommit 2.0 and 1.25 (128 cores, 320Gi). No
database and no cluster: the registry connects to the suite's FakeKube and the quotas are listed as the watch lists them.
"""
from __future__ import annotations

from cmapi.core.registry import ClusterPolicy, ClusterRegistry
from conftest import FakeKube, OneSecret

OVERCOMMIT = {"dev": {"cpu": 2.0, "memory": 1.25}}
TARGETS = {"dev": {"commitment": {"warn": 0.85, "critical": 0.95}}}


def quota(ns, name, hard, scopes=None):
    spec = {"hard": hard, **({"scopes": scopes} if scopes else {})}
    return {"kind": "ResourceQuota", "metadata": {"name": name, "namespace": ns, "labels": {"cmapi.net/managed": "true"}},
            "spec": spec, "status": {"used": {k: "0" for k in hard}}}


CASES = {
    "one namespace, quotas of 8 and 2 cores": [quota("payments-dev", "a", {"requests.cpu": "8"}),
                                                quota("payments-dev", "b", {"requests.cpu": "2"})],
    "one namespace, 8 cores and a BestEffort-scoped 120": [quota("payments-dev", "a", {"requests.cpu": "8"}),
                                                          quota("payments-dev", "c", {"requests.cpu": "120"}, ["BestEffort"])],
    "CRC's six quotas (72 cores, 144Gi), one per namespace": [
        quota(f"cmapi-live-{x}", "q", {"requests.cpu": "8", "requests.memory": "16Gi"}) for x in "abcdf"] + [
        quota("cmapi-live-e", "q", {"requests.cpu": "32", "requests.memory": "64Gi"})],
}


def capacity(registry):
    from cmapi.core.capacity_backend import SimulatedCapacity
    try:
        from cmapi.core.capacity import CapacitySettings              # after #302
        return SimulatedCapacity(registry, CapacitySettings({"overcommit": OVERCOMMIT, "targets": TARGETS}))
    except ImportError:                                               # before #302
        return SimulatedCapacity(registry, OVERCOMMIT, TARGETS)


for name, quotas in CASES.items():
    kube = FakeKube()
    for q in quotas:
        kube.objects[("ResourceQuota", q["metadata"]["namespace"], q["metadata"]["name"])] = q
    policy = ClusterPolicy("CRC", "dev", "clusters/CRC", simulated_capacity={"cpu": 64, "memory": "256Gi"})
    registry = ClusterRegistry({"CRC": policy}, OneSecret(), client_factory=lambda *a, **k: kube, start_caches=False)
    registry.refresh()
    cache = registry.cache("CRC")
    for kind in cache.kinds:
        cache._list(kind)
    cap = capacity(registry).check("CRC", "dev", 0, 0)
    print(f"{name}: {cap.status}, fresh={cap.fresh}, cpu {cap.detail.get('cpu')}, memory {cap.detail.get('memory')}")
