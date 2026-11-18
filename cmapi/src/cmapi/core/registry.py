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

Each refusal is a finding on that cluster only, and nothing one cluster sends or holds stops the others, the start or the
relist (#419): an answer the client cannot read is `bad-response`. A connected cluster with no clusters.yaml entry
is read-only (writes get 422 cluster-not-writable). Every connected cluster gets a WatchCache with the CapacityLedger that its
ResourceQuotas feed (core/capacity_ledger.py, #302); when the instance runs Kyverno in its environment, a ReportCache of its
policy reports (core/clients/policyreports.py, #302) from `reports_factory`; and a NodeCache of its nodes for capacity
(core/clients/nodes.py, #302) from `nodes_factory`.
"""
from __future__ import annotations

import base64
import binascii
import os
import re
import ssl
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

from cmapi.core.capacity_ledger import CapacityLedger
from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeClient, KubeError, WatchCache
from cmapi.core.clients.nodes import NodeCache
from cmapi.core.clients.policyreports import ReportCache
from cmapi.core.errors import Problem
from cmapi.core.observability import CLUSTER_STATUS, log
from cmapi.core.tiers import qty

READER_IDENTITY = "system:serviceaccount:cmapi-system:cmapi-reader"
INSECURE_ALLOWED = {"rnd"}
STATUSES = ("connected", "not-imported", "invalid-secret", "unreachable", "cert-verify-failed", "auth_failed",
            "wrong-identity", "forbidden", "bad-response", "environment-not-served")
NO_IMPORT_SECRET = "no import Secret"          # the finding of a not-imported cluster, from the start and from the relist
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
    # The finding of the default status: a cluster that clusters.yaml names and no import Secret does reads the same after a
    # start as after its Secret is deleted (#404).
    findings: list[str] = field(default_factory=lambda: [NO_IMPORT_SECRET])
    server_version: str | None = None
    checked_at: datetime | None = None
    client: KubeClient | None = None
    cache: WatchCache | None = None
    ledger: CapacityLedger | None = None          # fed by `cache`'s hooks: set and cleared with it
    reports: ReportCache | None = None
    nodes: NodeCache | None = None
    token_expires_at: str | None = None

    @property
    def environment(self) -> str | None:
        return self.policy.environment if self.policy else None

    def not_connected(self) -> tuple[str, str]:
        """The named state and its detail for a view of this cluster's data while it is not connected (Capacity, Policies):
        `not-imported` when no import Secret names it, so nothing was tried; else `unreachable`, with the import status of
        GET /api/v1/clusters and its findings (#404)."""
        state = "not-imported" if self.status == "not-imported" else "unreachable"
        detail = f"the cluster is {self.status}"
        if self.findings:
            detail += f": {'; '.join(self.findings)}"
        return state, detail[:300]

    def view(self) -> dict[str, Any]:
        p = self.policy
        return {"clusterId": self.cluster_id, "environment": p.environment if p else "", "gitopsPath": p.gitops_path if p else "",
                "writes": bool(p and p.writes), "status": self.status, "findings": list(self.findings),
                "serverVersion": self.server_version, "labels": dict(p.labels) if p else {}, "checkedAt": self.checked_at}


def _size_problem(size: Any) -> str | None:
    """Why a clusters.yaml `simulatedCapacity` cannot size a cluster, or None. The plan's check and GET /api/v1/capacity divide
    by it and read both resources, so a missing resource, a value that is not a quantity, or 0 would fail each of them on every
    call instead of once at the start (#302)."""
    if not isinstance(size, Mapping):
        return "must be a mapping of cpu and memory"
    for r in ("cpu", "memory"):
        if r not in size:
            return f"has no {r}"
        try:
            value = qty(size[r])
        except (TypeError, ValueError, ArithmeticError):
            return f"{r} is not a Kubernetes quantity: {size[r]!r}"
        if not value.is_finite() or value <= 0:
            return f"{r} must be above 0, not {size[r]!r}"
    return None


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
        size = e.get("simulatedCapacity")
        if size is not None and (why := _size_problem(size)):
            problems.append(f"cluster {cid}: simulatedCapacity {why}")
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
    """A Secret as the checks read it. A value that is not base64 of UTF-8 text (a binary file put in a Secret) is named in
    `undecodable` for the parse step to refuse, so one Secret never fails the list of all of them (#419)."""
    meta = doc.get("metadata") or {}
    data: dict[str, str] = {}
    undecodable: list[str] = []
    for k, v in (doc.get("data") or {}).items():
        try:
            data[k] = base64.b64decode(v).decode()
        except (binascii.Error, ValueError, TypeError):              # UnicodeDecodeError is a ValueError
            undecodable.append(k)
    data.update(doc.get("stringData") or {})
    return {"name": meta.get("name"), "labels": meta.get("labels") or {}, "annotations": meta.get("annotations") or {},
            "data": data, "undecodable": undecodable}


# --------------------------------------------------------------------------- the registry


class ClusterRegistry:
    def __init__(self, policies: Mapping[str, ClusterPolicy], source: ImportSource | None, *,
                 trusted_bundle: str | None = None, relist_seconds: int = 300,
                 client_factory: Callable[..., KubeClient] = KubeClient, start_caches: bool = True,
                 reports_factory: Callable[[ClusterState, KubeClient], ReportCache | None] | None = None,
                 nodes_factory: Callable[[ClusterState, KubeClient], NodeCache | None] | None = None):
        self.policies = dict(policies)
        self.source, self.trusted_bundle, self.relist_seconds = source, trusted_bundle, relist_seconds
        self.client_factory, self.start_caches = client_factory, start_caches
        # None, or None from the factory: no report cache for that cluster (engine none, or its environment's mode off).
        self.reports_factory = reports_factory
        # None, or None from the factory: no node cache for that cluster, so its allocatable is not known.
        self.nodes_factory = nodes_factory
        self.clusters: dict[str, ClusterState] = {cid: ClusterState(cid, p) for cid, p in self.policies.items()}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._ca_files: dict[str, str] = {}
        self._fingerprints: dict[str, str] = {}

    # ---- the six checks
    def _ca_file(self, cluster_id: str, ca_data: str) -> str:
        path = self._ca_files.get(cluster_id)
        try:
            current = Path(path).read_text() if path else None
        except OSError:                     # removed under us (a cleaner of the temporary folder): write it again
            current = None
        if current != ca_data:
            fd, path = tempfile.mkstemp(prefix=f"cmapi-ca-{cluster_id}-", suffix=".crt")
            with os.fdopen(fd, "w") as f:
                f.write(ca_data)
            self._ca_files[cluster_id] = path
        return path

    def _check(self, cluster_id: str, secret: Mapping[str, Any]) -> ClusterState:
        st = self.clusters.get(cluster_id) or ClusterState(cluster_id, None)
        d = secret["data"]
        undecodable = secret.get("undecodable") or []
        findings: list[str] = [f"field {k} is not base64 of UTF-8 text" for k in undecodable]
        # 2. parse
        for k in ("apiUrl", "token"):
            if not d.get(k) and k not in undecodable:
                findings.append(f"missing field {k}")
        api_url = d.get("apiUrl", "")
        try:
            u = urlparse(api_url)
            userinfo = bool(u.username or u.password)
        except ValueError:                  # urlparse raises on a malformed IPv6 host, such as https://[::1:6443
            findings.append("apiUrl is not a URL")
        else:
            if userinfo:
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
        try:
            # httpx loads the trust store here: a caData of valid base64 that is no certificate fails now, not at a call.
            client = self.client_factory(cluster_id, api_url, d["token"], ca_file, insecure=insecure)
        except OSError as exc:                                      # ssl.SSLError is an OSError, as a missing file is
            if ca_data and isinstance(exc, ssl.SSLError):
                return self._set(st, "invalid-secret", [f"invalid caData: {exc}"], None, secret)
            store = "caData" if ca_data else "the hub bundle"
            return self._set(st, "cert-verify-failed", [f"{exc}; trust store: {store}"], None, secret)
        try:
            status, found, version = self._probe(client, bool(ca_data))
        except BaseException:
            client.close()
            raise
        if status != "connected":
            client.close()
            return self._set(st, status, found, version, secret)
        st = self._set(st, "connected", [], version, secret)
        fp = f"{api_url}|{d['token'][-12:]}|{bool(ca_data)}"
        if st.client is None or self._fingerprints.get(cluster_id) != fp:
            self._stop_caches(st)
            ledger = CapacityLedger()
            cache = WatchCache(client, admit=ledger.admit, dropped=ledger.dropped)
            with self._lock:
                # Together, under the lock `quota_watch` reads them under: a read never pairs one cache with another's ledger.
                st.client, st.ledger, st.cache = client, ledger, cache
            st.reports = self.reports_factory(st, client) if self.reports_factory else None
            st.nodes = self.nodes_factory(st, client) if self.nodes_factory else None
            if self.start_caches:
                st.cache.start()
                if st.reports is not None:
                    st.reports.start()
                if st.nodes is not None:
                    st.nodes.start()
            self._fingerprints[cluster_id] = fp
        else:
            client.close()
        return st

    @staticmethod
    def _probe(client: KubeClient, has_ca_data: bool) -> tuple[str, list[str], str | None]:
        """Checks 4 to 6 on one client: (status, findings, server version). Each way a call can fail is a status here, so
        nothing the cluster answers escapes the check (#419). Who produced the error decides it (docs/02 "Client rules"):
        a transport failure of this process is unreachable or cert-verify-failed, an answer that cannot be read is
        bad-response, and a refusal is auth_failed or forbidden."""
        # 4. connect
        try:
            version = client.version()
        except ClusterUnreachable as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc) or "certificate" in str(exc).lower():
                hint = "; trust store: caData" if has_ca_data else "; trust store: the hub bundle"
                return "cert-verify-failed", [str(exc)[:200] + hint], None
            return "unreachable", [str(exc)[:200]], None
        except KubeError as exc:
            return "auth_failed" if exc.status in (401, 403) else "unreachable", [str(exc)], None
        except BadResponse as exc:
            return "bad-response", [str(exc)], None
        # 5. identity
        try:
            who = client.whoami()
        except KubeError as exc:
            return "auth_failed", [f"identity check: {exc}"], version
        except ClusterUnreachable as exc:
            return "unreachable", [str(exc)[:200]], version
        except BadResponse as exc:
            return "bad-response", [f"identity check: {exc}"], version
        if who != READER_IDENTITY:
            return "wrong-identity", [f"token is {who}, expected {READER_IDENTITY}"], version
        # 6. capability
        try:
            client.list("Namespace")
        except KubeError as exc:
            grant = "list namespaces" if exc.status == 403 else str(exc)
            return "forbidden", [f"missing grant: {grant}"], version
        except ClusterUnreachable as exc:
            return "unreachable", [str(exc)[:200]], version
        except BadResponse as exc:
            return "bad-response", [str(exc)], version
        return "connected", [], version

    def _set(self, st: ClusterState, status: str, findings: list[str], version: str | None,
             secret: Mapping[str, Any]) -> ClusterState:
        with self._lock:
            if status != "connected" and st.cache is not None:
                self._stop_caches(st)
                st.cache, st.ledger, st.client = None, None, None
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
            try:
                self._check(cid, items[0])
            except Exception as exc:                                # noqa: BLE001 - one cluster never stops the rest (#419)
                # `_check` makes each answer of the cluster a status; this is what it did not foresee (a full disk for the
                # caData file, a fault of a cache factory). The log has the trace; the finding names the error.
                log.exception("cluster_check_failed", cluster_id=cid)
                st = self.clusters.get(cid) or ClusterState(cid, None)
                self._set(st, "unreachable", [f"the check failed: {type(exc).__name__}: {str(exc)[:200]}"], None, items[0])
        with self._lock:
            for cid, st in self.clusters.items():
                if cid not in seen and st.status != "not-imported":
                    st.status, st.findings = "not-imported", [NO_IMPORT_SECRET]
                    self._stop_caches(st)
                    st.cache, st.ledger, st.client = None, None, None

    def start(self) -> None:
        self.refresh()
        threading.Thread(target=self._loop, name="imports", daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.wait(self.relist_seconds):
            try:
                self.refresh()
            except Exception:                                       # noqa: BLE001 - the relist outlives any one pass (#419)
                log.exception("imports_relist_failed")

    def stop(self) -> None:
        self._stop.set()
        for st in self.clusters.values():
            self._stop_caches(st)

    @staticmethod
    def _stop_caches(st: ClusterState) -> None:
        if st.cache is not None:
            st.cache.stop()
        if st.reports is not None:
            st.reports.stop()
            st.reports = None
        if st.nodes is not None:
            st.nodes.stop()
            st.nodes = None

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
        cache = st.cache                    # once: `_set` or the relist may clear it between a check and a return (#402)
        if cache is None:
            raise Problem(503, "cluster-unreachable", f"{cluster_id} is {st.status}: {'; '.join(st.findings)}",
                          extra={"retryAfter": 30})
        return cache

    def quota_watch(self, cluster_id: str) -> tuple[WatchCache, CapacityLedger | None]:
        """The cluster's watch cache and the ledger its ResourceQuotas feed, read together under the lock that `_connect` and
        `_set` replace them under. Read one at a time, a read could check the freshness of the old cache and then sum the new,
        empty ledger: 0 committed on fresh data, the #393 fault."""
        with self._lock:
            return self.cache(cluster_id), self.get(cluster_id).ledger

    def connected(self) -> list[ClusterState]:
        return [st for st in self.clusters.values() if st.status == "connected"]

    def status_map(self) -> dict[str, str]:
        return {cid: st.status for cid, st in self.clusters.items()}


def wait_for_caches(registry: ClusterRegistry, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    for st in registry.connected():
        cache = st.cache                    # once: the relist thread may clear it meanwhile (#402)
        if cache is not None:
            cache.wait_ready(max(0.1, deadline - time.time()))
