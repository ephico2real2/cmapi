"""The raw manifest renderer: one namespace's desired state in, one folder of plain YAML out.

    clusters/<clusterId>/namespaces/<ns>/
        namespace.yaml  resourcequota.yaml  limitrange.yaml
        serviceaccounts.yaml  rolebindings.yaml  token-issuer-rolebinding.yaml

Nothing on the cluster expands these files, so the plan diff, Kyverno, kubeconform and the plan
hash all cover exactly what Argo CD applies. Rules:

- Keys are ordered system first (metadata.ordered), so diffs stay small and stable.
- cmapi.net/request-id on an object is the last request that changed it: an object whose content
  is unchanged keeps the request ID it already had in Git.
- cmapi.net/requested-by(-user) are written at create from the token and kept on later changes.
- Expiry keys are never written for prod (422 expiration-not-allowed).
- An SCC grant is a RoleBinding to system:openshift:scc:<name>; cmapi never creates an SCC.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

import yaml

from cmapi.core.errors import Problem
from cmapi.core.metadata import MetadataKeys
from cmapi.core.tiers import TierCatalog

SYNC_OPTIONS = "Prune=confirm,ServerSideApply=true"
TOKEN_ISSUER = {"role": "cmapi-token-issuer", "sa": "cmapi-reader", "sa_namespace": "cmapi-system"}


@dataclass
class NamespaceSpec:
    namespace: str
    cluster_id: str
    instance: str
    env: str
    tier: str
    request_id: str
    requested_by_user: str               # from the token (Identity.label_value), used at create
    requested_by_email: str | None
    labels: dict[str, str] = field(default_factory=dict)        # governed and team keys only
    annotations: dict[str, str] = field(default_factory=dict)   # governed (team-dl) and team keys
    quota: dict[str, str] | None = None                         # sizable keys, custom tier only
    expires_at: date | None = None
    service_accounts: list[str] = field(default_factory=list)
    grants: list[tuple[str, str]] = field(default_factory=list)        # (sa, ClusterRole)
    scc_grants: list[tuple[str, str]] = field(default_factory=list)    # (sa, scc)


def folder(cluster_id: str, namespace: str) -> str:
    return f"clusters/{cluster_id}/namespaces/{namespace}/"


def plan_hash(files: Mapping[str, str | None]) -> str:
    """sha256 over path and content of every file the plan writes or removes (None = removed)."""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode() + b"\0" + (files[path] or "<deleted>").encode() + b"\0")
    return h.hexdigest()


def _dump(docs: list[dict[str, Any]]) -> str:
    return "---\n".join(yaml.safe_dump(d, sort_keys=False, default_flow_style=False) for d in docs)


def _load(text: str | None) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(text)] if text else []


def _identity(doc: Mapping[str, Any]) -> tuple[str, str]:
    return doc["kind"], doc["metadata"]["name"]


def _without_request_id(doc: Mapping[str, Any]) -> dict[str, Any]:
    d = yaml.safe_load(yaml.safe_dump(doc))
    d.get("metadata", {}).get("annotations", {}).pop("cmapi.net/request-id", None)
    return d


class ManifestRenderer:
    def __init__(self, catalog: TierCatalog, keys: MetadataKeys):
        self.catalog, self.keys = catalog, keys

    def render(self, spec: NamespaceSpec, previous: Mapping[str, str] | None = None) -> dict[str, str | None]:
        """Files for the namespace's folder, keyed by path; None means the file is removed.
        previous: the folder as it is in Git."""
        if spec.expires_at and spec.env == "prod":
            raise Problem.unprocessable("expiration-not-allowed", "Production namespaces never expire")
        base = folder(spec.cluster_id, spec.namespace)
        prev = {p.removeprefix(base): _load(t) for p, t in (previous or {}).items()}
        common_labels = {"cmapi.net/cluster-id": spec.cluster_id, "cmapi.net/managed": "true"}

        def meta(name: str, ns: str | None, labels: dict[str, str], ann: dict[str, str]) -> dict[str, Any]:
            m: dict[str, Any] = {"name": name}
            if ns:
                m["namespace"] = ns
            m["labels"] = self.keys.ordered(labels)
            m["annotations"] = self.keys.ordered({**ann, "cmapi.net/instance": spec.instance,
                                                  "cmapi.net/request-id": spec.request_id})
            return m

        # namespace.yaml
        old_ns = next(iter(prev.get("namespace.yaml", [])), None)
        old_ann = (old_ns or {}).get("metadata", {}).get("annotations", {})
        old_lab = (old_ns or {}).get("metadata", {}).get("labels", {})
        # caller keys first, system keys last: a caller can never override what the renderer owns
        labels = {**spec.labels, **common_labels, "cmapi.net/env": spec.env, "cmapi.net/tier": spec.tier,
                  "cmapi.net/requested-by-user": old_lab.get("cmapi.net/requested-by-user", spec.requested_by_user)}
        ann = {**spec.annotations, "argocd.argoproj.io/sync-options": SYNC_OPTIONS}
        requested_by = old_ann.get("cmapi.net/requested-by", spec.requested_by_email)
        if requested_by:
            ann["cmapi.net/requested-by"] = requested_by
        if spec.expires_at:
            labels["cmapi.net/expiry"] = "managed"
            ann["cmapi.net/expires-at"] = spec.expires_at.isoformat()
        namespace_doc = {"apiVersion": "v1", "kind": "Namespace",
                         "metadata": meta(spec.namespace, None, labels, ann)}

        # resourcequota.yaml and limitrange.yaml from the tier catalog
        rq, lr = self.catalog.render(namespace=spec.namespace, cluster_id=spec.cluster_id,
                                     instance=spec.instance, env=spec.env, tier=spec.tier,
                                     request_id=spec.request_id, hard=spec.quota)
        for d in (rq, lr):
            d["metadata"]["labels"] = self.keys.ordered(d["metadata"]["labels"])
            d["metadata"]["annotations"] = self.keys.ordered(d["metadata"]["annotations"])

        files: dict[str, list[dict[str, Any]]] = {
            "namespace.yaml": [namespace_doc], "resourcequota.yaml": [rq], "limitrange.yaml": [lr]}

        if spec.service_accounts:
            files["serviceaccounts.yaml"] = [
                {"apiVersion": "v1", "kind": "ServiceAccount",
                 "metadata": meta(sa, spec.namespace, dict(common_labels), {})}
                for sa in sorted(spec.service_accounts)]
        bindings = []
        for sa, role in sorted(spec.grants):
            bindings.append(self._binding(f"{sa}-{role}", spec, sa, role, meta, common_labels))
        for sa, scc in sorted(spec.scc_grants):
            bindings.append(self._binding(f"{sa}-scc-{scc}", spec, sa, f"system:openshift:scc:{scc}",
                                          meta, common_labels))
        known = set(spec.service_accounts)
        for sa, _ in [*spec.grants, *spec.scc_grants]:
            if sa not in known:
                raise Problem.unprocessable("unknown-serviceaccount", f"{sa} is not a ServiceAccount of {spec.namespace}")
        if bindings:
            files["rolebindings.yaml"] = bindings
        files["token-issuer-rolebinding.yaml"] = [{
            "apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
            "metadata": meta(TOKEN_ISSUER["role"], spec.namespace, dict(common_labels), {}),
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": TOKEN_ISSUER["role"]},
            "subjects": [{"kind": "ServiceAccount", "name": TOKEN_ISSUER["sa"], "namespace": TOKEN_ISSUER["sa_namespace"]}]}]

        # keep the request ID of every object whose content did not change
        for name, docs in files.items():
            old = {_identity(d): d for d in prev.get(name, [])}
            for d in docs:
                o = old.get(_identity(d))
                if o and _without_request_id(o) == _without_request_id(d):
                    d["metadata"]["annotations"]["cmapi.net/request-id"] = \
                        o["metadata"]["annotations"]["cmapi.net/request-id"]
        out: dict[str, str | None] = {base + name: _dump(docs) for name, docs in files.items()}
        for name in prev:                     # the last SA or grant removed: the file goes (revocation)
            if name not in files:
                out[base + name] = None
        return out

    @staticmethod
    def _binding(name, spec, sa, role, meta, common_labels) -> dict[str, Any]:
        return {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
                "metadata": meta(name, spec.namespace, dict(common_labels), {}),
                "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": role},
                "subjects": [{"kind": "ServiceAccount", "name": sa, "namespace": spec.namespace}]}

    def delete(self, cluster_id: str, namespace: str, previous: Mapping[str, str]) -> dict[str, None]:
        """A delete removes the whole folder: every file maps to None."""
        base = folder(cluster_id, namespace)
        return {p: None for p in previous if p.startswith(base)}


def diff_files(before: Mapping[str, str], after: Mapping[str, str | None]) -> dict[str, str]:
    """added | changed | removed | unchanged per path, for the plan and the PR body."""
    out = {}
    for p in sorted(set(before) | set(after)):
        b, a = before.get(p), after.get(p, before.get(p))
        out[p] = ("added" if b is None and a is not None else "removed" if a is None
                  else "unchanged" if a == b else "changed")
    return out
