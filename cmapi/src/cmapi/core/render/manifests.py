"""The raw manifest renderer: one namespace's desired state in, one folder of plain YAML out.

    clusters/<clusterId>/namespaces/<ns>/
        namespace.yaml  resourcequota-<ns>-quota.yaml
        limitrange-<ns>-limits-cpu.yaml  limitrange-<ns>-limits-memory.yaml  [limitrange-<ns>-limits-storage.yaml]
        serviceaccounts.yaml  rolebindings.yaml  token-issuer-rolebinding.yaml

One file for each ResourceQuota and each LimitRange, named after the object (the adoption design's D8, #253), so no
reader takes several documents of those kinds. A folder written before that layout (resourcequota.yaml, limitrange.yaml)
is read as it is, and its next change removes those files and writes the named ones in the same commit.

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

from cmapi.core import kube_yaml
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
    labels: dict[str, str] = field(default_factory=dict)        # required, extra and other keys of the requester
    annotations: dict[str, str] = field(default_factory=dict)   # the same, for annotations; derived keys are added at render
    quota: dict[str, str] | None = None                         # sizable and overridable quota keys, custom tier only
    limit_range: dict[str, dict[str, dict[str, str]]] | None = None   # overridable LimitRange values, custom tier only
    approved: dict[str, str] = field(default_factory=dict)      # the custom values Git holds: not checked against the bounds again
    expires_at: date | None = None
    service_accounts: list[str] = field(default_factory=list)
    grants: list[tuple[str, str]] = field(default_factory=list)        # (sa, ClusterRole)
    scc_grants: list[tuple[str, str]] = field(default_factory=list)    # (sa, scc)


def folder(cluster_id: str, namespace: str) -> str:
    return f"clusters/{cluster_id}/namespaces/{namespace}/"


OBJECT_FILE_STEM = {"ResourceQuota": "resourcequota", "LimitRange": "limitrange"}
_NAME_MAX = 255                                  # bytes in a file name on the file systems that a Git checkout uses


def object_file(kind: str, name: str) -> str:
    """The file of one ResourceQuota or LimitRange: <kind>-<name>.yaml, or <kind>--<sha256 of the name>.yaml when that is
    longer than a file name can be. Readers find the objects by kind (objects_of), never by this name."""
    stem = OBJECT_FILE_STEM[kind]
    file = f"{stem}-{name}.yaml"
    if len(file.encode()) <= _NAME_MAX:
        return file
    # Ordinary names start with an alphanumeric character. The extra '-' keeps the hash
    # namespace disjoint from their paths, without needing a cryptographic collision.
    return f"{stem}--{hashlib.sha256(name.encode()).hexdigest()}.yaml"


def objects_of(files: Mapping[str, str | None], kind: str) -> list[dict[str, Any]]:
    """Every object of one kind in a folder's files, from any file and any document of it, in path order."""
    out = []
    for path in sorted(files):
        text = files[path]
        if not text or not path.endswith(".yaml"):
            continue
        out.extend(d for d in yaml.safe_load_all(text) if isinstance(d, Mapping) and d.get("kind") == kind)
    return out


# What plan_hash writes for a removed file, and for an empty one. Persisted plan hashes depend on it (jobs/delivery.py,
# jobs/pr_checks.py), so it stays; folder_etag (core/pipeline.py) tells the two apart another way (#584).
DELETED = "<deleted>"


def plan_hash(files: Mapping[str, str | None]) -> str:
    """sha256 over path and content of every file the plan writes or removes (None = removed)."""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode() + b"\0" + (files[path] or DELETED).encode() + b"\0")
    return h.hexdigest()


def _dump(docs: list[dict[str, Any]]) -> str:
    # kube_yaml quotes each string that kubectl, Argo CD or Kyverno would read as a bool, number or null (#355)
    return "---\n".join(kube_yaml.dump(d, sort_keys=False, default_flow_style=False) for d in docs)


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
        # caller keys first, then the keys that cmapi derives (value.from of metadata-keys.yaml), system keys last:
        # a caller can never override what the renderer owns
        derived_labels, derived_ann = self.keys.derived({"namespace": spec.namespace, "environment": spec.env,
                                                         "cluster": spec.cluster_id, "instance": spec.instance})
        if old_ns is not None:
            # A change keeps each automatic key as Git holds it, and keeps it absent where Git lacks it: its target
            # (environment, instance) may have moved since the create (#481, design section 3, row 5).
            derived_labels = {key: old_lab[key] for key in derived_labels if key in old_lab}
            derived_ann = {key: old_ann[key] for key in derived_ann if key in old_ann}
        labels = {**spec.labels, **derived_labels, **common_labels, "cmapi.net/env": spec.env, "cmapi.net/tier": spec.tier,
                  "cmapi.net/requested-by-user": old_lab.get("cmapi.net/requested-by-user", spec.requested_by_user)}
        ann = {**spec.annotations, **derived_ann, "argocd.argoproj.io/sync-options": SYNC_OPTIONS}
        requested_by = old_ann.get("cmapi.net/requested-by", spec.requested_by_email)
        if requested_by:
            ann["cmapi.net/requested-by"] = requested_by
        if spec.expires_at:
            labels["cmapi.net/expiry"] = "managed"
            ann["cmapi.net/expires-at"] = spec.expires_at.isoformat()
        namespace_doc = {"apiVersion": "v1", "kind": "Namespace",
                         "metadata": meta(spec.namespace, None, labels, ann)}

        # the ResourceQuota and the LimitRanges from the tier catalog, one file each
        rq, lrs = self.catalog.render(namespace=spec.namespace, cluster_id=spec.cluster_id,
                                     instance=spec.instance, env=spec.env, tier=spec.tier,
                                     request_id=spec.request_id, hard=spec.quota, limits=spec.limit_range,
                                     approved=spec.approved)
        files: dict[str, list[dict[str, Any]]] = {"namespace.yaml": [namespace_doc]}
        for d in (rq, *lrs):
            d["metadata"]["labels"] = self.keys.ordered(d["metadata"]["labels"])
            d["metadata"]["annotations"] = self.keys.ordered(d["metadata"]["annotations"])
            files[object_file(d["kind"], d["metadata"]["name"])] = [d]

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

        # keep the request ID of every object whose content did not change, wherever the previous folder held it
        old = {_identity(d): d for docs in prev.values() for d in docs if isinstance(d, Mapping) and d.get("metadata")}
        for docs in files.values():
            for d in docs:
                o = old.get(_identity(d))
                if o and _without_request_id(o) == _without_request_id(d):
                    d["metadata"]["annotations"]["cmapi.net/request-id"] = \
                        o["metadata"]["annotations"]["cmapi.net/request-id"]
        out: dict[str, str | None] = {base + name: _dump(docs) for name, docs in files.items()}
        for name in prev:                     # the last SA or grant removed, or a file of the old layout: the file goes
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
        """A delete removes the whole folder: every path of previous inside it maps to None. previous is the folder's full
        listing (GitProvider.list_folder), every file at any depth, not only the manifests read_folder reads (#616)."""
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
