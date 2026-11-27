"""How a merged folder reaches the cluster, and how cmapi learns it did (docs/01, Sync).

Three delivery modes, chosen in config/integrations.yaml (`delivery.mode`) or per cluster (#751):

    gitops   For a cluster with a deliverer: whatever applies Git main (Argo CD, Flux, ACM, a pipeline)
             applies the folder, and cmapi confirms by a read of the full approved plan (read_plan),
             whoever applied it. The deliverer's own status, when configured and readable, is signal
             for people (deliverer_signal), never proof. Deletes wait in awaiting_prune for a read of
             absence.
    argocd   Each cluster's Argo CD applies clusters/<id>/namespaces; the worker reads the root
             Application (SyncSignal poll) and then confirms with the same read. Deletes wait in
             awaiting_prune until an operator confirms the prune in Argo CD.
    apply    For a cluster with no deliverer (CRC): once Git main's folder is seen to equal the
             approved plan, the worker applies that plan with server-side apply as a separate
             deliverer identity, confirms with the read, and holds deletes until an operator
             confirms through POST /admin/prune:confirm. It refuses a namespace that exists and
             is not cmapi-managed. This is the only cluster write cmapi ever makes, and it is
             documented as a deployment choice, not the design's default.

All three end the same way: a request is synced only when a read shows the cluster as the plan says
(docs/reviews/2026-11-27-issue-751/README.md, D2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from cmapi.core import kube_yaml
from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeClient, KubeError
from cmapi.core.plan_read import Difference, Getter, PlanRead, Unreadable, defaulted_limit, read_plan  # noqa: F401 (the API)
from cmapi.core.ports import AppStatus

DeliveryMode = Literal["argocd", "gitops", "apply"]
MODES: tuple[str, ...] = ("argocd", "gitops", "apply")
# Whose status joins a gitops request's notes (#751, D4). Never proof: see read_plan.
SIGNALS: tuple[str, ...] = ("none", "argocd", "flux")


@dataclass(frozen=True)
class DeliveryConfig:
    mode: DeliveryMode = "argocd"     # unchanged for a file that names none; gitops is the mode to choose (#751, D1)
    poll_seconds: int = 30
    sync_timeout_seconds: int = 1800
    argocd_namespace: str = "openshift-gitops"
    argocd_root_application: str = "cluster-configs-{clusterId}"
    signal: str = "none"
    flux_namespace: str = "flux-system"
    flux_kustomization: str = "cluster-configs-{clusterId}"

    def __post_init__(self) -> None:
        # Before #751 a misspelt mode ran as argocd: the watch's else branch took it. Now it stops the start.
        if self.mode not in MODES:
            raise ValueError(f"integrations.yaml: delivery.mode must be one of {', '.join(MODES)}, not {self.mode!r}")
        if self.signal not in SIGNALS:
            raise ValueError(f"integrations.yaml: delivery.signal must be one of {', '.join(SIGNALS)}, not {self.signal!r}")

    @classmethod
    def from_integrations(cls, raw: Mapping[str, Any] | None) -> "DeliveryConfig":
        raw = raw or {}
        d = raw.get("delivery") or {}
        s = raw.get("syncSignal") or {}
        argocd, flux = d.get("argocd") or {}, d.get("flux") or {}
        return cls(mode=d.get("mode", "argocd"), poll_seconds=_seconds(s.get("pollInterval", "30s")),
                   sync_timeout_seconds=_seconds(d.get("syncTimeout", "30m")),
                   argocd_namespace=argocd.get("namespace", "openshift-gitops"),
                   argocd_root_application=argocd.get("rootApplication", "cluster-configs-{clusterId}"),
                   signal=d.get("signal", "none"), flux_namespace=flux.get("namespace", "flux-system"),
                   flux_kustomization=flux.get("kustomization", "cluster-configs-{clusterId}"))


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
            docs.extend(kube_yaml.load_all(text))
        for d in docs:
            self.client.apply(d)
        return len(docs)

    def prune_objects(self, namespace: str, removed_files: Mapping[str, str]) -> int:
        n = 0
        for text in removed_files.values():
            for d in kube_yaml.load_all(text):
                if d["kind"] != "Namespace":
                    self.client.delete(d["kind"], namespace, d["metadata"]["name"])
                    n += 1
        return n

    def delete_namespace(self, namespace: str) -> None:
        self.client.delete("Namespace", None, namespace)


def application_name(template: str, cluster_id: str, namespace: str) -> str:
    """The Application to read. Kubernetes refuses an upper-case object name (measured on 1.35.6) and a cluster id is
    upper-case (CRC), so {clusterId} takes the spelling deploy/baseline-crc.sh gives the cluster's import Secret."""
    return template.format(clusterId=cluster_id.lower().replace("_", "-"), namespace=namespace)


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


def _object_keys(files: Mapping[str, str]) -> list[tuple[str, str, str]]:
    """(kind, namespace, name) of each object. A plan's previous folder is whatever Git held, so a document with no name
    (a kustomization.yaml, say) is not an object Argo CD would report."""
    keys = []
    for text in files.values():
        for d in kube_yaml.load_all(text):
            meta = d.get("metadata") or {}
            if meta.get("name") and d.get("kind"):
                keys.append((d["kind"], meta.get("namespace") or "", meta["name"]))
    return keys


def not_synced(app: AppStatus, files: Mapping[str, str], previous: Mapping[str, str] | None = None) -> list[str]:
    """The planned objects Argo CD does not report Synced, and the objects this plan removed that it still reports (a
    removal is delivered when the object has left the Application: until then it is live, OutOfSync, requiresPruning).
    The Application's own status covers every namespace in its folder: one neighbour waiting for Prune=confirm leaves
    it OutOfSync, so it says nothing about this one."""
    seen = {(k, ns, n): s for k, ns, n, s in app.resources}
    planned = _object_keys(files)
    out = [f"{k[0]}/{k[2]}: {seen.get(k, 'not in the Application')}" for k in planned if seen.get(k) != "Synced"]
    out += [f"{k[0]}/{k[2]}: removed by this plan, still in the Application ({seen[k]})"
            for k in _object_keys(previous or {}) if k not in planned and k in seen]
    return out


# --------------------------------------------------------------------------- the read that ends a request (#751, D2)

def confirmed_by_read(get: Getter, namespace: str, files: Mapping[str, str | None],
                      previous: Mapping[str, str | None] | None = None, **rules: Any) -> tuple[bool, str]:
    """read_plan (core/plan_read.py) as (confirmed, why): the argocd and apply jobs' form of it."""
    found = read_plan(get, namespace, files, previous, **rules)
    return found.ok, found.summary()


# --------------------------------------------------------------------------- the deliverer's status, as signal (#751, D4)

def _argocd_phrase(name: str, app: Mapping[str, Any]) -> str:
    st = app.get("status") or {}
    op = st.get("operationState") or {}
    sync, health = (st.get("sync") or {}).get("status", "Unknown"), (st.get("health") or {}).get("status", "Unknown")
    words = f"Argo CD {name}: {sync}, {health}"
    if op.get("phase"):
        words += f", last operation {op['phase']}"
        if op.get("message"):
            words += f": {op['message']}"
    errors = [c.get("message", "") for c in st.get("conditions") or [] if str(c.get("type", "")).endswith("Error")]
    if errors:
        words += f"; {'; '.join(errors)}"
    return words


def _flux_phrase(name: str, ks: Mapping[str, Any]) -> str:
    st = ks.get("status") or {}
    ready = next((c for c in st.get("conditions") or [] if c.get("type") == "Ready"), None)
    words = f"Flux {name}: " + (f"Ready {ready.get('status')} ({ready.get('reason', '')}): {ready.get('message', '')}"
                                if ready else "no Ready condition yet")
    return f"{words}; applied {st.get('lastAppliedRevision') or 'nothing'}, attempted {st.get('lastAttemptedRevision') or 'nothing'}"


def deliverer_signal(client: Any, config: DeliveryConfig, cluster_id: str, namespace: str) -> str | None:
    """One phrase on what the deliverer reports, for a person reading the request, or None when no signal is set.

    It never raises and never decides: a request is confirmed or failed by read_plan alone. A deliverer that is not there,
    a read the reader may not make, or a cluster that does not answer is said in a phrase, and nothing else changes."""
    if config.signal == "none":
        return None
    if config.signal == "argocd":
        name = application_name(config.argocd_root_application, cluster_id, namespace)
        label, path = f"Argo CD {name}", f"/apis/argoproj.io/v1alpha1/namespaces/{config.argocd_namespace}/applications/{name}"
    else:
        name = application_name(config.flux_kustomization, cluster_id, namespace)
        label = f"Flux {name}"
        path = f"/apis/kustomize.toolkit.fluxcd.io/v1/namespaces/{config.flux_namespace}/kustomizations/{name}"
    try:
        if client is None:
            raise ClusterUnreachable("no reader")
        found = client.get(path)
    except KubeError as exc:
        return f"{label}: {'forbidden to the reader' if exc.status == 403 else f'unreadable ({exc.status})'}"
    except (ClusterUnreachable, BadResponse) as exc:
        return f"{label}: unreadable ({type(exc).__name__})"
    if found is None:
        return f"{label}: not found"
    try:
        phrase = _argocd_phrase(name, found) if config.signal == "argocd" else _flux_phrase(name, found)
    except (AttributeError, TypeError):           # a status of another shape: still only a phrase, never a failed job
        return f"{label}: a status cmapi cannot read"
    return phrase[:300]
