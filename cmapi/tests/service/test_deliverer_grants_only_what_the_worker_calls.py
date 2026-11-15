"""F1: ClusterRole cmapi-deliverer grants only what the worker's deliverer identity calls.

The deliverer client (jobs/watch_sync.py, _deliverer) is used for one Namespace read (watch_sync: the live check before the apply),
server-side apply (core/sync.py ApplyDelivery.apply_folder: PATCH application/apply-patch+yaml, which is RBAC patch, and create
when the object is new) and delete (ApplyDelivery.prune_objects, prune's namespace delete). The watch cache and every confirming
read go through the reader import (registry.cache), never the deliverer. So list and watch, granted cluster-wide on
serviceaccounts and rolebindings among others, read every project's ServiceAccounts and RoleBindings on a shared cluster for no
caller. Each call the full flow makes is recorded as the RBAC verb the API server checks, and the ClusterRole (the plain file and
the chart, held equal by test_crc_deliverer_is_the_charts) must grant exactly the verbs that some call needs.

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_deliverer_grants_only_what_the_worker_calls.py -q -W ignore
"""
from __future__ import annotations

from pathlib import Path

import yaml

from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs

ROOT = Path(__file__).resolve().parents[3]
PLAIN = ROOT / "deploy/manifests/environments/crc/deliverer/00-cmapi-deliverer.yaml"
RESOURCE = {"Namespace": "namespaces", "ResourceQuota": "resourcequotas", "LimitRange": "limitranges",
            "ServiceAccount": "serviceaccounts", "RoleBinding": "rolebindings"}


class RecordingDeliverer:
    """The deliverer's KubeClient surface over the world's cluster, recording (verb, resource) as RBAC authorizes each call."""

    def __init__(self, kube):
        self.kube, self.calls = kube, set()

    def get_object(self, kind, namespace, name):
        self.calls.add(("get", RESOURCE[kind]))
        return self.kube.get_object(kind, namespace, name)

    def list(self, kind, *a, **k):
        self.calls.add(("list", RESOURCE[kind]))
        return self.kube.list(kind, *a, **k)

    def watch(self, kind, *a, **k):
        self.calls.add(("watch", RESOURCE[kind]))
        return self.kube.watch(kind, *a, **k)

    def apply(self, doc, field_manager="cmapi-deliverer"):
        m = doc["metadata"]
        exists = self.kube.get_object(doc["kind"], m.get("namespace"), m["name"]) is not None
        self.calls.add(("patch", RESOURCE[doc["kind"]]))
        if not exists:              # server-side apply that creates: create as well as patch
            self.calls.add(("create", RESOURCE[doc["kind"]]))
        return self.kube.apply(doc, field_manager)

    def delete(self, kind, namespace, name):
        self.calls.add(("delete", RESOURCE[kind]))
        return self.kube.delete(kind, namespace, name)


def granted_verbs() -> set[tuple[str, str]]:
    role = next(d for d in yaml.safe_load_all(PLAIN.read_text()) if d and d["kind"] == "ClusterRole")
    return {(v, r) for rule in role["rules"] if "resourceNames" not in rule for r in rule["resources"] for v in rule["verbs"]}


def test_the_deliverer_role_grants_the_verbs_the_worker_calls_and_no_other(world):
    client, ctx, git, kube, validator, keys = world
    rec = RecordingDeliverer(kube)
    ctx.deliverer_factory = lambda cid: rec
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    run_jobs(ctx)
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    rid = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    assert client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx)
    assert client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}, headers=auth(keys, "opal", **OPAL)).status_code == 200
    run_jobs(ctx)
    assert kube.get_object("Namespace", None, "payments-dev") is None, "the flow did not reach the prune"

    granted = granted_verbs()
    assert rec.calls <= granted, f"called but not granted: {sorted(rec.calls - granted)}"
    # What the flow above cannot reach is still a call site: prune_objects deletes every rendered kind, and apply creates and patches each.
    needed = rec.calls | {(v, r) for r in RESOURCE.values() for v in ("create", "patch", "delete")}
    assert granted <= needed, f"granted but no caller: {sorted(granted - needed)}"
