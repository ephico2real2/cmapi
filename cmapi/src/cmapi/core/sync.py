"""How a merged folder reaches the cluster, and how cmapi learns it did (docs/01, Sync).

Two delivery modes, chosen in config/integrations.yaml (`delivery.mode`) or per cluster:

    argocd   The design: each cluster's Argo CD applies clusters/<id>/namespaces; the worker reads
             the root Application (SyncSignal poll) and confirms with a direct read. Deletes
             wait in awaiting_prune until an operator confirms the prune in Argo CD.
    apply    Built-in, for a cluster with no GitOps (CRC): once Git main's folder is seen to equal
             the approved plan, the worker applies that plan with server-side apply as a separate
             deliverer identity, confirms with a read, and holds deletes until an operator
             confirms through POST /admin/prune:confirm. It refuses a namespace that exists and
             is not cmapi-managed. This is the only cluster write cmapi ever makes, and it is
             documented as a deployment choice, not the design's default.

Both end the same way: a request is synced only when a read shows the namespace and its quota
as planned.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

import yaml

from cmapi.core.clients.kube import KubeClient, KubeError
from cmapi.core.ports import AppStatus
from cmapi.core.tiers import qty

DeliveryMode = Literal["argocd", "apply"]


@dataclass(frozen=True)
class DeliveryConfig:
    mode: DeliveryMode = "argocd"     # the design's mode; apply is a deployment's explicit choice
    poll_seconds: int = 30
    sync_timeout_seconds: int = 1800
    argocd_namespace: str = "openshift-gitops"
    argocd_root_application: str = "cluster-configs-{clusterId}"

    @classmethod
    def from_integrations(cls, raw: Mapping[str, Any] | None) -> "DeliveryConfig":
        raw = raw or {}
        d = raw.get("delivery") or {}
        s = raw.get("syncSignal") or {}
        return cls(mode=d.get("mode", "argocd"), poll_seconds=_seconds(s.get("pollInterval", "30s")),
                   sync_timeout_seconds=_seconds(d.get("syncTimeout", "30m")),
                   argocd_namespace=d.get("argocd", {}).get("namespace", "openshift-gitops"),
                   argocd_root_application=d.get("argocd", {}).get("rootApplication", "cluster-configs-{clusterId}"))


def _seconds(v: str | int) -> int:
    if isinstance(v, int):
        return v
    units = {"s": 1, "m": 60, "h": 3600}
    return int(v[:-1]) * units[v[-1]] if v[-1] in units else int(v)


class ApplyDelivery:
    """Server-side apply of one namespace folder with the deliverer identity."""

    def __init__(self, client: KubeClient):
        self.client = client

    def apply_folder(self, files: Mapping[str, str]) -> int:
        docs: list[dict[str, Any]] = []
        for path, text in sorted(files.items(), key=lambda kv: not kv[0].endswith("namespace.yaml")):
            docs.extend(d for d in yaml.safe_load_all(text) if d)
        for d in docs:
            self.client.apply(d)
        return len(docs)

    def prune_objects(self, namespace: str, removed_files: Mapping[str, str]) -> int:
        n = 0
        for text in removed_files.values():
            for d in yaml.safe_load_all(text):
                if d and d["kind"] != "Namespace":
                    self.client.delete(d["kind"], namespace, d["metadata"]["name"])
                    n += 1
        return n

    def delete_namespace(self, namespace: str) -> None:
        self.client.delete("Namespace", None, namespace)


class ArgoCdSignal:
    """SyncSignal poll: the root Application's sync status and the prune-pending namespaces."""

    def __init__(self, client: KubeClient, namespace: str, application: str):
        self.client, self.namespace, self.application = client, namespace, application

    def status(self, cluster_id: str) -> AppStatus:
        app = self.client.get(f"/apis/argoproj.io/v1alpha1/namespaces/{self.namespace}/applications/{self.application}")
        if app is None:
            raise KubeError(404, self.application, "root Application not found")
        st = app.get("status", {})
        sync = st.get("sync", {})
        op = st.get("operationState", {}) or {}
        prune = frozenset(r["name"] for r in st.get("resources", []) if r.get("kind") == "Namespace"
                          and r.get("requiresPruning"))
        revisions = frozenset(r for r in (sync.get("revisions") or [sync.get("revision")]) if r)
        return AppStatus(cluster_id=cluster_id, revision=sync.get("revision", ""),
                         sync=sync.get("status", "Unknown"), health=st.get("health", {}).get("status", "Unknown"),
                         phase=op.get("phase"), prune_pending=prune, revisions=revisions,
                         resources=tuple((r.get("kind", ""), r.get("namespace") or "", r.get("name", ""), r.get("status", "Unknown"))
                                         for r in st.get("resources", [])))


def not_synced(app: AppStatus, files: Mapping[str, str]) -> list[str]:
    """The planned objects Argo CD does not report Synced. The Application's own status covers every namespace in
    its folder: one neighbour waiting for Prune=confirm leaves it OutOfSync, so it says nothing about this one."""
    seen = {(k, ns, n): s for k, ns, n, s in app.resources}
    out = []
    for text in files.values():
        for d in yaml.safe_load_all(text):
            if d:
                key = (d["kind"], d["metadata"].get("namespace") or "", d["metadata"]["name"])
                if seen.get(key) != "Synced":
                    out.append(f"{key[0]}/{key[2]}: {seen.get(key, 'not in the Application')}")
    return out


def confirmed_by_read(cache_get: Any, namespace: str, files: Mapping[str, str]) -> tuple[bool, str]:
    """The read that ends a request: the namespace exists and its quota equals the planned hard values."""
    ns = cache_get("Namespace", None, namespace)
    if ns is None:
        return False, "namespace not found"
    rq_text = next((t for p, t in files.items() if p.endswith("resourcequota.yaml")), None)
    if rq_text is None:
        return True, "namespace present"
    want = yaml.safe_load(rq_text)
    live = cache_get("ResourceQuota", namespace, want["metadata"]["name"])
    if live is None:
        return False, "resourcequota not found"
    hard = live.get("spec", {}).get("hard", {})
    # The API server returns quantities canonicalised (5120Mi reads back as 5Gi): compare values, not spellings.
    missing = {k: v for k, v in want["spec"]["hard"].items() if k not in hard or qty(hard[k]) != qty(v)}
    return (not missing, "quota matches the plan" if not missing else f"quota differs: {missing}")
