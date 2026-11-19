"""The cluster registry: policy from clusters.yaml, connections from the cmapi-imports Secrets,
and the six checks before a cluster is read (docs/01, "Cluster connections and metadata").

    1. Discover: list the Secrets labelled cmapi.net/secret-type=cluster (a hub API watch with a
       5-minute relist; a failed list keeps the previous set). CMAPI_IMPORTS_DIR reads YAML
       files instead, for tests and local runs.
    2. Parse: apiUrl, token, caData, insecure, tlsServerName; refused for a missing field, a duplicate cluster ID, insecure
       with caData, invalid caData, an insecure that is not "true" or "false", a tlsServerName that is no host name, or
       userinfo in apiUrl.
    3. TLS mode (core/clients/trust.py, #434): insecure where instance.clusterTLS allows the cluster's environment, else
       caData alone, else trusted: the image's system store and the bundles of CMAPI_TRUSTED_CA_FILE.
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
import hashlib
import re
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

import httpx
import yaml

from cmapi.core.capacity_ledger import CapacityLedger
from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeClient, KubeError, WatchCache, list_items
from cmapi.core.clients.nodes import NodeCache
from cmapi.core.clients.policyreports import ReportCache
from cmapi.core.clients.redact import redact, secret_forms
from cmapi.core.clients.trust import Trust, file_context, require_https, trusted_context, valid_server_name
from cmapi.core.errors import Problem
from cmapi.core.observability import CLUSTER_STATUS, CLUSTER_TLS_INSECURE, log
from cmapi.core.tiers import qty

READER_IDENTITY = "system:serviceaccount:cmapi-system:cmapi-reader"
STATUSES = ("connected", "not-imported", "invalid-secret", "unreachable", "cert-verify-failed", "auth_failed",
            "wrong-identity", "forbidden", "bad-response", "environment-not-served")
NO_IMPORT_SECRET = "no import Secret"          # the finding of a not-imported cluster, from the start and from the relist
HEADER_TOKEN = re.compile(r"[\x21-\x7e]+")      # visible ASCII: what a bearer token in an Authorization header may hold
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
    trust: Trust | None = None                    # the mode of the last check that got past the parse; None before or after

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
                "serverVersion": self.server_version, "labels": dict(p.labels) if p else {}, "checkedAt": self.checked_at,
                "trust": self.trust.view() if self.trust else None}


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
        require_https(api_url, "CMAPI_KUBE_API_URL")       # before the token is read: never sent in clear text
        self.namespace = namespace
        token = token_file.read_text().strip()
        self._forms = secret_forms(token)
        # The hub's own ServiceAccount CA, else the trusted mode: never httpx's verify=True (certifi or SSL_CERT_FILE, #434).
        verify = file_context(str(ca_file)) if ca_file.exists() else trusted_context()
        self.client = httpx.Client(base_url=api_url, verify=verify, timeout=10,
                                   headers={"Authorization": f"Bearer {token}"})

    def list(self) -> list[dict[str, Any]]:
        """Every import Secret, or an error: `refresh` then keeps the previous set (docs/02 "Discovery"). An answer that is not
        a list of Secrets (not JSON, not an object, no items) is BadResponse, never an empty list that would retire every
        cluster (#421)."""
        path = f"/api/v1/namespaces/{self.namespace}/secrets"
        try:
            r = self.client.get(path, params={"labelSelector": "cmapi.net/secret-type=cluster"})
            r.raise_for_status()
        except httpx.HTTPError as exc:
            # The hub's own token never reaches the log `imports_list_failed`, whatever the error text holds (#420).
            raise RuntimeError(redact(f"{type(exc).__name__}: {exc}", self._forms)) from exc
        return [_secret(s) for s in list_items(KubeClient._object(r, path), path, r.status_code)]


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
    meta = _mapping(doc.get("metadata"))
    data: dict[str, str] = {}
    undecodable: list[str] = []
    for k, v in _mapping(doc.get("data")).items():
        try:
            data[k] = base64.b64decode(v).decode()
        except (binascii.Error, ValueError, TypeError):              # UnicodeDecodeError is a ValueError
            undecodable.append(k)
    data.update(_mapping(doc.get("stringData")))
    return {"name": meta.get("name"), "labels": _mapping(meta.get("labels")), "annotations": _mapping(meta.get("annotations")),
            "data": data, "undecodable": undecodable}


def _mapping(value: Any) -> dict[str, Any]:
    """A field of a Secret that must be a mapping, or {}: CMAPI_IMPORTS_DIR reads YAML no API server validated, and a text
    or a list there must not raise out of `refresh`, outside the net of each cluster (#419)."""
    return dict(value) if isinstance(value, Mapping) else {}


# --------------------------------------------------------------------------- the registry


class ClusterRegistry:
    def __init__(self, policies: Mapping[str, ClusterPolicy], source: ImportSource | None, *,
                 trusted_ca_file: str | None = None, insecure_environments: Iterable[str] = (), relist_seconds: int = 300,
                 client_factory: Callable[..., KubeClient] = KubeClient, start_caches: bool = True,
                 reports_factory: Callable[[ClusterState, KubeClient], ReportCache | None] | None = None,
                 nodes_factory: Callable[[ClusterState, KubeClient], NodeCache | None] | None = None):
        self.policies = dict(policies)
        self.source, self.relist_seconds = source, relist_seconds
        # CMAPI_TRUSTED_CA_FILE's value for the trusted mode (None reads the variable at each check), and the environments
        # whose instance.clusterTLS.environments.<env>.insecureSkipTLSVerify is true: none by default (#434).
        self.trusted_ca_file, self.insecure_environments = trusted_ca_file, frozenset(insecure_environments)
        self.client_factory, self.start_caches = client_factory, start_caches
        # None, or None from the factory: no report cache for that cluster (engine none, or its environment's mode off).
        self.reports_factory = reports_factory
        # None, or None from the factory: no node cache for that cluster, so its allocatable is not known.
        self.nodes_factory = nodes_factory
        self.clusters: dict[str, ClusterState] = {cid: ClusterState(cid, p) for cid, p in self.policies.items()}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._fingerprints: dict[str, str] = {}

    # ---- the six checks
    def _check(self, cluster_id: str, secret: Mapping[str, Any]) -> ClusterState:
        st = self.clusters.get(cluster_id) or ClusterState(cluster_id, None)
        d = secret["data"]
        undecodable = secret.get("undecodable") or []
        findings: list[str] = [f"field {k} is not base64 of UTF-8 text" for k in undecodable]
        # 2. parse
        for k in ("apiUrl", "token"):
            if not d.get(k) and k not in undecodable:
                findings.append(f"missing field {k}")
        token = d.get("token")
        if token and not HEADER_TOKEN.fullmatch(token):
            # `kubectl create token` ends its output with a newline that `--from-file` keeps: h11 refuses the header at the
            # first call (`unreachable`), and a non-ASCII token raises in the client's constructor. The Secret is at fault.
            findings.append("token has whitespace or a character an HTTP header cannot carry")
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
        # str(): a YAML boolean of CMAPI_IMPORTS_DIR reads as its text, as before; a Secret from the API is always text.
        insecure_text = str(d.get("insecure", "false")).lower()
        if insecure_text not in ("true", "false"):
            findings.append('insecure is "true" or "false"')
        insecure = insecure_text == "true"
        ca_data = d.get("caData")
        if insecure and ca_data:
            findings.append("insecure with caData")              # client-go refuses the same: a CA and no verification
        if ca_data and not _valid_ca_data(ca_data):
            findings.append("invalid caData")
        server_name = d.get("tlsServerName") or None
        if server_name is not None and not (isinstance(server_name, str) and valid_server_name(server_name)):
            findings.append("tlsServerName is not a DNS name or an IP address")
        # 3. TLS mode. The environment's permission is checked before any client exists, so a token never leaves this process
        # over unverified TLS where the instance does not allow it.
        env = st.policy.environment if st.policy else None
        if insecure and env not in self.insecure_environments:
            where = env if env is not None else "<none>"
            findings.append(f"insecure is not allowed for environment {where}: "
                            f"instance.clusterTLS.environments.{where}.insecureSkipTLSVerify is false")
        if findings:
            return self._set(st, "invalid-secret", findings, None, secret)
        # The root dot of a fully qualified name names the same host; OpenSSL matches the name as written, so it is dropped.
        server_name = server_name.removesuffix(".") if server_name else None
        trust = (Trust("insecure", server_name=server_name) if insecure
                 else Trust("caData", ca_data=ca_data, server_name=server_name) if ca_data
                 else Trust("trusted", server_name=server_name, bundles=self.trusted_ca_file))
        try:
            # The whole token, as a SHA-256: a rotated token that ends in the same characters still gives the caches the new
            # client. The digest stays in memory, compared and never shown.
            fp = f"{api_url}|{hashlib.sha256(d['token'].encode()).hexdigest()}|{trust.fingerprint()}"
            # The client builds the SSL context: a caData of valid base64 that is no certificate fails now, not at a call (#419),
            # and so does a bundle of CMAPI_TRUSTED_CA_FILE that does not load (TrustBundleError, which names it).
            client = self.client_factory(cluster_id, api_url, d["token"], trust, insecure=insecure)
        except OSError as exc:                                      # ssl.SSLError is an OSError, as a missing file is
            if ca_data and isinstance(exc, ssl.SSLError):
                return self._set(st, "invalid-secret", [f"invalid caData: {exc}"], None, secret)
            return self._set(st, "cert-verify-failed", [f"{exc}; trust store: {trust.store_name()}"], None, secret, trust)
        adopted = False                     # the client is closed unless the caches took it, whatever ends the check
        try:
            status, found, version = self._probe(client, trust)
            if status != "connected":
                return self._set(st, status, found, version, secret, trust)
            st = self._set(st, "connected", [], version, secret, trust)
            # Anything the client verifies with is in the fingerprint (G6 of #434): a rotated caData, a new server name, a
            # change of mode or a bundle that changed gives the caches the new client, not only a new token or URL.
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
                adopted = True
            return st
        finally:
            if not adopted:
                # A fault after the caches took it (a factory that raises) reaches the net in `refresh`, whose `_set`
                # stops those caches and drops the client: it is closed here, not left to the garbage collector.
                client.close()

    @staticmethod
    def _probe(client: KubeClient, trust: Trust) -> tuple[str, list[str], str | None]:
        """Checks 4 to 6 on one client: (status, findings, server version). Each way a call can fail is a status here, so
        nothing the cluster answers escapes the check (#419). Who produced the error decides it (docs/02 "Client rules"):
        a transport failure of this process is unreachable or cert-verify-failed, an answer that cannot be read is
        bad-response, and a refusal is auth_failed or forbidden."""
        # 4. connect
        try:
            version = client.version()
        except ClusterUnreachable as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc) or "certificate" in str(exc).lower():
                return "cert-verify-failed", [f"{str(exc)[:200]}; trust store: {trust.store_name()}"], None
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
             secret: Mapping[str, Any], trust: Trust | None = None) -> ClusterState:
        """Records one check's outcome. `trust` is the mode the check used, None when it ended before one was chosen."""
        # KubeClient redacts its token before any cut (#420). This second pass covers every other way a finding is made:
        # GET /api/v1/clusters serves findings to each clusters:read caller, and the log below writes them.
        forms = secret_forms((secret.get("data") or {}).get("token"))
        findings = [redact(f, forms) for f in findings]
        with self._lock:
            previous_status = st.status
            changed = (previous_status, st.findings) != (status, findings)
            if status != "connected" and st.cache is not None:
                self._stop_caches(st)
                st.cache, st.ledger, st.client = None, None, None
            st.status, st.findings, st.server_version = status, findings, version
            st.checked_at = datetime.now(timezone.utc)
            st.token_expires_at = secret.get("annotations", {}).get("cmapi.net/token-expires-at")
            self.clusters[st.cluster_id] = st
            for s in STATUSES:
                CLUSTER_STATUS.labels(st.cluster_id, s).set(1 if s == status else 0)
            previous = self._set_trust(st, trust)
        self._log_mode(st.cluster_id, previous, trust)
        if changed:
            emit = log.info if status == "connected" else log.warning
            emit("cluster_import", cluster_id=st.cluster_id, status=status, previous=previous_status, findings=findings)
        return st

    @staticmethod
    def _set_trust(st: ClusterState, trust: Trust | None) -> Trust | None:
        """The cluster's mode and the metric cmapi_cluster_tls_insecure; returns the mode it replaces. Under the lock."""
        previous, st.trust = st.trust, trust
        CLUSTER_TLS_INSECURE.labels(st.cluster_id).set(1 if trust and trust.source == "insecure" else 0)
        return previous

    @staticmethod
    def _log_mode(cluster_id: str, previous: Trust | None, trust: Trust | None) -> None:
        """One line when the mode changes, not one at each relist: a warning when insecure takes effect, so that the downgrade
        is in the log when it starts and when it ends. A check that ends before a mode is chosen changes nothing here, except
        that an insecure mode that no Secret holds any more is logged as cleared."""
        old = previous.source if previous else None
        new = trust.source if trust else None
        if old == new or (new is None and old != "insecure"):
            return
        emit = log.warning if new == "insecure" else log.info
        emit("cluster_tls_mode", cluster_id=cluster_id, mode=new, previous=old,
             server_name=trust.server_name if trust else None)

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
            if isinstance(cid, str) and cid:
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
                    self._log_mode(cid, self._set_trust(st, None), None)

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
