"""The cluster registry: policy from clusters.yaml, connections from the cmapi-imports Secrets,
and the six checks before a cluster is read (docs/01, "Cluster connections and metadata").

    1. Discover: list the Secrets labelled cmapi.net/secret-type=cluster (a hub API watch with a
       5-minute relist; a failed list keeps the previous set). CMAPI_IMPORTS_DIR reads YAML
       files instead, for tests and local runs.
    2. Parse: apiUrl, token, caData, insecure; refused for a missing field, a duplicate cluster
       ID, insecure with caData, invalid caData, or userinfo in apiUrl.
    3. TLS mode: caData, the trusted bundle, or insecure where the environment allows it.
    4. Connect: GET /version.
    5. Identity: users/~ must be cmapi-system:cmapi-reader.
    6. Capability: list namespaces.

Each refusal is a finding on that cluster only. A connected cluster with no clusters.yaml entry
is read-only (writes get 422 cluster-not-writable). Every connected cluster gets a WatchCache.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import httpx
import yaml

from cmapi.core.clients.kube import ClusterUnreachable, KubeClient, KubeError, WatchCache
from cmapi.core.errors import Problem
from cmapi.core.observability import CLUSTER_STATUS, log

READER_IDENTITY = "system:serviceaccount:cmapi-system:cmapi-reader"
INSECURE_ALLOWED = {"rnd"}
STATUSES = ("connected", "not-imported", "invalid-secret", "unreachable", "cert-verify-failed", "auth_failed",
            "wrong-identity", "forbidden", "environment-not-served")
PEM_CERTIFICATE = re.compile(r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", re.S)


@dataclass
class ClusterPolicy:
    cluster_id: str
    environment: str
    gitops_path: str
    writes: bool = True
    sync_signal: str = "poll"
    delivery: str | None = None
    thanos_url: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    placement: dict[str, Any] = field(default_factory=dict)
    simulated_capacity: dict[str, str] | None = None


@dataclass
class ClusterState:
    cluster_id: str
    policy: ClusterPolicy | None
    status: str = "not-imported"
    findings: list[str] = field(default_factory=list)
    server_version: str | None = None
    checked_at: datetime | None = None
    client: KubeClient | None = None
    cache: WatchCache | None = None
    token_expires_at: str | None = None

    @property
    def environment(self) -> str | None:
        return self.policy.environment if self.policy else None

    def view(self) -> dict[str, Any]:
        p = self.policy
        return {"clusterId": self.cluster_id, "environment": p.environment if p else "", "gitopsPath": p.gitops_path if p else "",
                "writes": bool(p and p.writes), "status": self.status, "findings": list(self.findings),
                "serverVersion": self.server_version, "labels": dict(p.labels) if p else {}, "checkedAt": self.checked_at}


def load_policies(path: Path, allowed_environments: set[str]) -> dict[str, ClusterPolicy]:
    raw = yaml.safe_load(path.read_text()) or {}
    entries = raw.get("clusters") or {}
    items = entries.items() if isinstance(entries, dict) else ((e["clusterId"], e) for e in entries)
    out: dict[str, ClusterPolicy] = {}
    problems: list[str] = []
    for cid, e in items:
        env = e.get("environment")
        if env not in allowed_environments:
            problems.append(f"cluster {cid}: environment {env!r} is not served by this instance")
            continue
        out[cid] = ClusterPolicy(cluster_id=cid, environment=env, gitops_path=e.get("gitopsPath", f"clusters/{cid}"),
                                 writes=bool(e.get("writes", True)), sync_signal=e.get("syncSignal", "poll"),
                                 delivery=e.get("delivery"), thanos_url=e.get("thanosUrl"),
                                 labels=dict(e.get("labels") or {}), metadata=dict(e.get("metadata") or {}),
                                 placement=dict(e.get("placement") or {}), simulated_capacity=e.get("simulatedCapacity"))
    if problems:
        raise ValueError("clusters.yaml: " + "; ".join(problems))
    return out


# --------------------------------------------------------------------------- import sources


class ImportSource:
    """Yields the import Secrets as plain dicts: {name, labels, annotations, data(decoded)}."""

    def list(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class DirImportSource(ImportSource):
    def __init__(self, directory: Path):
        self.dir = directory

    def list(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.dir.glob("*.yaml")):
            for doc in yaml.safe_load_all(p.read_text()):
                if doc and doc.get("kind") == "Secret":
                    out.append(_secret(doc))
        return out


class HubImportSource(ImportSource):
    """Lists Secrets in the hub's cmapi-imports namespace with the pod's own ServiceAccount."""

    def __init__(self, api_url: str, token_file: Path, ca_file: Path, namespace: str):
        self.namespace = namespace
        self.client = httpx.Client(base_url=api_url, verify=str(ca_file) if ca_file.exists() else True, timeout=10,
                                   headers={"Authorization": f"Bearer {token_file.read_text().strip()}"})

    def list(self) -> list[dict[str, Any]]:
        r = self.client.get(f"/api/v1/namespaces/{self.namespace}/secrets",
                            params={"labelSelector": "cmapi.net/secret-type=cluster"})
        r.raise_for_status()
        return [_secret(s) for s in r.json().get("items", [])]


def _valid_ca_data(ca_data: str) -> bool:
    """Each PEM block by itself: a service account's ca.crt is usually a bundle, and base64 padding may end any block, so the blocks joined are not base64 even when each one is."""
    bodies = PEM_CERTIFICATE.findall(ca_data) or ["".join(l for l in ca_data.splitlines() if not l.startswith("-----"))]
    try:
        return all(base64.b64decode("".join(b.split()), validate=True) for b in bodies)
    except (binascii.Error, ValueError):
        return False


def _secret(doc: Mapping[str, Any]) -> dict[str, Any]:
    meta = doc.get("metadata", {})
    data = {k: base64.b64decode(v).decode() for k, v in (doc.get("data") or {}).items()}
    data.update(doc.get("stringData") or {})
    return {"name": meta.get("name"), "labels": meta.get("labels") or {}, "annotations": meta.get("annotations") or {},
            "data": data}


# --------------------------------------------------------------------------- the registry


class ClusterRegistry:
    def __init__(self, policies: Mapping[str, ClusterPolicy], source: ImportSource | None, *,
                 trusted_bundle: str | None = None, relist_seconds: int = 300,
                 client_factory: Callable[..., KubeClient] = KubeClient, start_caches: bool = True):
        self.policies = dict(policies)
        self.source, self.trusted_bundle, self.relist_seconds = source, trusted_bundle, relist_seconds
        self.client_factory, self.start_caches = client_factory, start_caches
        self.clusters: dict[str, ClusterState] = {cid: ClusterState(cid, p) for cid, p in self.policies.items()}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._ca_files: dict[str, str] = {}
        self._fingerprints: dict[str, str] = {}

    # ---- the six checks
    def _ca_file(self, cluster_id: str, ca_data: str) -> str:
        path = self._ca_files.get(cluster_id)
        if path is None or Path(path).read_text() != ca_data:
            fd, path = tempfile.mkstemp(prefix=f"cmapi-ca-{cluster_id}-", suffix=".crt")
            with os.fdopen(fd, "w") as f:
                f.write(ca_data)
            self._ca_files[cluster_id] = path
        return path

    def _check(self, cluster_id: str, secret: Mapping[str, Any]) -> ClusterState:
        st = self.clusters.get(cluster_id) or ClusterState(cluster_id, None)
        d = secret["data"]
        findings: list[str] = []
        # 2. parse
        for k in ("apiUrl", "token"):
            if not d.get(k):
                findings.append(f"missing field {k}")
        api_url = d.get("apiUrl", "")
        u = urlparse(api_url)
        if u.username or u.password:
            findings.append("userinfo in apiUrl")
        if u.scheme != "https":
            findings.append("apiUrl is not https")
        insecure = str(d.get("insecure", "false")).lower() == "true"
        ca_data = d.get("caData")
        if insecure and ca_data:
            findings.append("insecure with caData")
        if ca_data and not _valid_ca_data(ca_data):
            findings.append("invalid caData")
        # 3. TLS mode
        env = st.policy.environment if st.policy else None
        if insecure and env not in INSECURE_ALLOWED:
            findings.append(f"insecure not allowed for environment {env}")
        if findings:
            return self._set(st, "invalid-secret", findings, None, secret)
        ca_file = self._ca_file(cluster_id, ca_data) if ca_data else self.trusted_bundle
        client = self.client_factory(cluster_id, api_url, d["token"], ca_file, insecure=insecure)
        # 4. connect
        try:
            version = client.version()
        except ClusterUnreachable as exc:
            status = "cert-verify-failed" if "CERTIFICATE_VERIFY_FAILED" in str(exc) or "certificate" in str(exc).lower() \
                else "unreachable"
            hint = "; trust store: caData" if ca_data else "; trust store: the hub bundle"
            return self._set(st, status, [str(exc)[:200] + (hint if status == "cert-verify-failed" else "")], None, secret)
        except KubeError as exc:
            return self._set(st, "auth_failed" if exc.status in (401, 403) else "unreachable", [str(exc)], None, secret)
        # 5. identity
        try:
            who = client.whoami()
        except KubeError as exc:
            return self._set(st, "auth_failed", [f"identity check: {exc}"], version, secret)
        except ClusterUnreachable as exc:
            return self._set(st, "unreachable", [str(exc)[:200]], version, secret)
        if who != READER_IDENTITY:
            return self._set(st, "wrong-identity", [f"token is {who}, expected {READER_IDENTITY}"], version, secret)
        # 6. capability
        try:
            client.list("Namespace")
        except KubeError as exc:
            grant = "list namespaces" if exc.status == 403 else str(exc)
            return self._set(st, "forbidden", [f"missing grant: {grant}"], version, secret)
        except ClusterUnreachable as exc:
            return self._set(st, "unreachable", [str(exc)[:200]], version, secret)
        st = self._set(st, "connected", [], version, secret)
        fp = f"{api_url}|{d['token'][-12:]}|{bool(ca_data)}"
        if st.client is None or self._fingerprints.get(cluster_id) != fp:
            if st.cache is not None:
                st.cache.stop()
            st.client = client
            st.cache = WatchCache(client)
            if self.start_caches:
                st.cache.start()
            self._fingerprints[cluster_id] = fp
        else:
            client.close()
        return st

    def _set(self, st: ClusterState, status: str, findings: list[str], version: str | None,
             secret: Mapping[str, Any]) -> ClusterState:
        with self._lock:
            if status != "connected" and st.cache is not None:
                st.cache.stop()
                st.cache, st.client = None, None
            st.status, st.findings, st.server_version = status, findings, version
            st.checked_at = datetime.now(timezone.utc)
            st.token_expires_at = secret.get("annotations", {}).get("cmapi.net/token-expires-at")
            self.clusters[st.cluster_id] = st
            for s in STATUSES:
                CLUSTER_STATUS.labels(st.cluster_id, s).set(1 if s == status else 0)
        if status != "connected":
            log.warning("cluster_import", cluster_id=st.cluster_id, status=status, findings=findings)
        return st

    def refresh(self) -> None:
        """One discovery pass: every import Secret through the six checks."""
        if self.source is None:
            return
        try:
            secrets = self.source.list()
        except Exception as exc:                                    # noqa: BLE001 - a failed list keeps the previous set
            log.warning("imports_list_failed", error=str(exc)[:200])
            return
        seen: set[str] = set()
        by_id: dict[str, list[dict[str, Any]]] = {}
        for s in secrets:
            cid = s["labels"].get("cmapi.net/cluster-id")
            if cid:
                by_id.setdefault(cid, []).append(s)
        for cid, items in by_id.items():
            seen.add(cid)
            if len(items) > 1:
                st = self.clusters.get(cid) or ClusterState(cid, None)
                self._set(st, "invalid-secret", [f"duplicate cluster ID in {[i['name'] for i in items]}"], None, items[0])
                continue
            self._check(cid, items[0])
        with self._lock:
            for cid, st in self.clusters.items():
                if cid not in seen and st.status != "not-imported":
                    st.status, st.findings = "not-imported", ["no import Secret"]
                    if st.cache:
                        st.cache.stop()
                    st.cache, st.client = None, None

    def start(self) -> None:
        self.refresh()
        threading.Thread(target=self._loop, name="imports", daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.wait(self.relist_seconds):
            self.refresh()

    def stop(self) -> None:
        self._stop.set()
        for st in self.clusters.values():
            if st.cache:
                st.cache.stop()

    # ---- questions the API asks
    def get(self, cluster_id: str) -> ClusterState:
        st = self.clusters.get(cluster_id)
        if st is None:
            raise Problem(404, "cluster-not-found", f"Unknown cluster {cluster_id}")
        return st

    def writable(self, cluster_id: str) -> ClusterState:
        st = self.get(cluster_id)
        if st.policy is None:
            raise Problem.unprocessable("cluster-not-writable", f"{cluster_id} is imported but has no clusters.yaml entry")
        if not st.policy.writes:
            raise Problem.unprocessable("cluster-not-writable", f"writes are off for {cluster_id} in clusters.yaml")
        return st

    def cache(self, cluster_id: str) -> WatchCache:
        st = self.get(cluster_id)
        if st.cache is None:
            raise Problem(503, "cluster-unreachable", f"{cluster_id} is {st.status}: {'; '.join(st.findings)}",
                          extra={"retryAfter": 30})
        return st.cache

    def connected(self) -> list[ClusterState]:
        return [st for st in self.clusters.values() if st.status == "connected"]

    def status_map(self) -> dict[str, str]:
        return {cid: st.status for cid, st in self.clusters.items()}


def wait_for_caches(registry: ClusterRegistry, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    for st in registry.connected():
        if st.cache is not None:
            st.cache.wait_ready(max(0.1, deadline - time.time()))
