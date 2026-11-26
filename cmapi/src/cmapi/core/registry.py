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
    6. Capability: list namespaces. When the instance reads usage (capacity.yaml usage.source thanos), also the reader's own
       grants for the cluster's Thanos Querier in openshift-monitoring (#724): each one missing is a finding on a cluster that
       stays connected, and its usage is unavailable with that finding as the reason (capacity/thanos.py).

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
from copy import copy, deepcopy
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
from cmapi.core.clients.redact import order_forms, redact, secret_forms
from cmapi.core.clients.trust import Trust, file_context, require_https, trusted_context, valid_server_name
from cmapi.core.cluster_tokens import READER_IDENTITY, ReaderGrant, TokenPolicy
from cmapi.core.config import ConfigError
from cmapi.core.errors import Problem
from cmapi.core.observability import CLUSTER_STATUS, CLUSTER_TLS_INSECURE, cluster_http_call, log, set_token_expiry
from cmapi.core.tiers import qty

STATUSES = ("connected", "not-imported", "invalid-secret", "unreachable", "cert-verify-failed", "auth_failed",
            "wrong-identity", "forbidden", "bad-response")
NO_IMPORT_SECRET = "no import Secret"          # the finding of a not-imported cluster, from the start and from the relist
# The reader's reads of the cluster's Thanos Querier for usage.source thanos (#724), each with the grant of the baseline that gives
# it (examples/baseline/cmapi-reader-rbac.yaml). The Route: capacity/thanos.py's ROUTE_PATH, when clusters.yaml has no thanosUrl.
# The query: the Querier's kube-rbac-proxy allows get on prometheuses/api "k8s" in openshift-monitoring
# (cluster-monitoring-operator release-4.18 and release-4.22, assets/thanos-querier/kube-rbac-proxy-web-secret.yaml).
MONITORING_NAMESPACE = "openshift-monitoring"
ROUTE_READ = ({"verb": "get", "group": "route.openshift.io", "resource": "routes", "name": "thanos-querier"},
              "get on Route thanos-querier (Role and RoleBinding cmapi-reader-thanos-route)")
QUERY_READ = ({"verb": "get", "group": "monitoring.coreos.com", "resource": "prometheuses", "subresource": "api", "name": "k8s"},
              "get on prometheuses/api k8s (RoleBinding cmapi-reader-metrics-api of Role cluster-monitoring-metrics-api)")
GRANT_CHECK = "create localsubjectaccessreviews (Role and RoleBinding cmapi-reader-grant-check)"
# The reader's groups as a ServiceAccount, without system:authenticated: a grant to every user (on CRC, another project's
# ClusterRoleBinding of cluster-monitoring-view) is not cmapi's and must not hide a missing one of its own (#724).
READER_GROUPS = ["system:serviceaccounts", "system:serviceaccounts:cmapi-system"]
USAGE_FINDING = "usage: "                        # the start of every finding of the usage grants
USAGE_UNCHECKED = USAGE_FINDING + "the reader's grants could not be checked: "
USAGE_NO_MONITORING = USAGE_FINDING + "the cluster serves no monitoring.coreos.com/v1, so it has no OpenShift monitoring"
USAGE_FIX = ("Apply the reader's openshift-monitoring grants of examples/baseline/cmapi-reader-rbac.yaml on the cluster; until "
             "then its usage is unavailable.")
HEADER_TOKEN = re.compile(r"[\x21-\x7e]+")      # visible ASCII: what a bearer token in an Authorization header may hold
# Kubernetes date-time annotations carry a full timestamp with an explicit offset.
TOKEN_EXPIRY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?"
                          r"(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")
# RFC 7468 section 2: a certificate's encapsulation boundaries, each BEGIN line with its END; the base64 between them is the
# block's body. The caData loader, OpenSSL's PEM_read_bio_X509, also takes the older label X509 CERTIFICATE (pem_lib.c,
# check_pem: PEM_STRING_X509_OLD), so its body is checked too (#591).
PEM_BLOCKS = {f"-----BEGIN {label}-----": f"-----END {label}-----" for label in ("CERTIFICATE", "X509 CERTIFICATE")}


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
    cluster_tokens: TokenPolicy = field(default_factory=TokenPolicy)


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
    token_expires_at: datetime | None = None
    trust: Trust | None = None                    # the mode of the last check that got past the parse; None before or after
    status_since: datetime | None = None
    secret_name: str | None = None
    last_probe_at: datetime | None = None
    # The findings of the usage grants (#724), also in `findings`: while any is here, the cluster's usage is unavailable.
    usage_findings: list[str] = field(default_factory=list)

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

    def _fix(self, finding: str) -> str:
        if finding.startswith(USAGE_FINDING):
            if finding == USAGE_NO_MONITORING:
                return "No grant can fix this: the cluster has no OpenShift monitoring, so its usage stays unavailable."
            if finding.startswith(USAGE_UNCHECKED) and GRANT_CHECK not in finding:
                # The API server or one of its authorizers failed, which no grant fixes (#724): the next check asks again.
                return "Check the cluster's API server and its authorizers; the next import check, or :probe, asks again."
            return USAGE_FIX
        if self.status == "invalid-secret":
            if finding.startswith("duplicate cluster ID"):
                return "Keep exactly one import Secret labelled with this cluster ID."
            if "token" in finding:
                return "Supply the reader's token without whitespace in the import Secret."
            if "caData" in finding or "insecure" in finding:
                return "Configure one permitted TLS mode with a valid trust source."
            if "apiUrl" in finding:
                return "Set apiUrl to the cluster's HTTPS URL without embedded credentials."
            if "tlsServerName" in finding:
                return "Set tlsServerName to a DNS name or IP address on the server certificate."
            return "Correct the named field in the import Secret and let cmapi recheck it."
        return {
            "not-imported": "Create an import Secret labelled with this cluster ID.",
            "cert-verify-failed": "Check the server certificate, its name and the configured CA.",
            "auth_failed": "Check that the import token is valid and renew it if expired.",
            "wrong-identity": "Issue the token for cmapi-system:cmapi-reader.",
            "forbidden": "Grant the reader permission to list namespaces.",
            "unreachable": "Check the cluster API URL, network path and registry logs.",
            "bad-response": "Check that the API URL reaches the Kubernetes API and returns JSON.",
        }[self.status]

    def view(self) -> dict[str, Any]:
        p = self.policy
        return {"clusterId": self.cluster_id, "environment": p.environment if p else "", "gitopsPath": p.gitops_path if p else "",
                "writes": bool(p and p.writes), "status": self.status, "findings": list(self.findings),
                "findingDetails": [{"finding": f, "fix": self._fix(f)} for f in self.findings],
                "secretName": self.secret_name, "tokenExpiresAt": self.token_expires_at, "lastProbeAt": self.last_probe_at,
                "serverVersion": self.server_version, "labels": dict(p.labels) if p else {}, "checkedAt": self.checked_at,
                "statusSince": self.status_since, "trust": self.trust.view() if self.trust else None}


def _diagnostic_forms(secret: Mapping[str, Any]) -> tuple[str, ...]:
    # TLS mode and server name are public. Use #420's minimum length so short imports cannot garble fixed wording.
    forms: set[str] = set()
    for key, value in secret.get("data", {}).items():
        if isinstance(value, str) and value and key not in {"insecure", "tlsServerName"}:
            forms.update(secret_forms(value))
    return order_forms(forms)


def parse_token_expiry(value: Any) -> datetime | None:
    if isinstance(value, str):
        if not TOKEN_EXPIRY.fullmatch(value):
            return None
        try:
            value = datetime.fromisoformat(value.upper())
        except ValueError:
            return None
    return value if isinstance(value, datetime) and value.tzinfo is not None else None


def token_expiry(secret: Mapping[str, Any]) -> datetime | None:
    return parse_token_expiry(secret.get("annotations", {}).get("cmapi.net/token-expires-at"))


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


PLACEMENT_KEYS = {"enabled", "maxNamespaces", "overcommit", "weight"}


def _placement_problem(block: Any) -> str | None:
    """Why a clusters.yaml `placement` block cannot be read, or None (#21; docs/02, "config/clusters.yaml": `enabled`,
    `maxNamespaces`, `overcommit` "overrides the environment default", `weight` "0 to 2; biases the placement score")."""
    if not isinstance(block, Mapping):
        return "must be a mapping"
    unknown = sorted(set(block) - PLACEMENT_KEYS)
    if unknown:
        return f"has unknown keys {unknown}; it takes {sorted(PLACEMENT_KEYS)}"
    if "enabled" in block and not isinstance(block["enabled"], bool):
        return f"enabled must be true or false, not {block['enabled']!r}"
    m = block.get("maxNamespaces")
    if m is not None and (isinstance(m, bool) or not isinstance(m, int) or m < 1):
        return f"maxNamespaces must be a whole number, 1 or more, not {m!r}"
    over = block.get("overcommit")
    if over is not None:
        if not isinstance(over, Mapping) or not set(over) <= {"cpu", "memory"} or not over:
            return f"overcommit must be a mapping of cpu and memory, not {over!r}"
        for r, v in over.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                return f"overcommit.{r} must be a number above 0, not {v!r}"
    w = block.get("weight", 1.0)
    if isinstance(w, bool) or not isinstance(w, (int, float)) or not 0 <= w <= 2:
        return f"weight must be a number from 0 to 2, not {w!r}"
    return None


def load_policies(path: Path, allowed_environments: set[str],
                  token_defaults: TokenPolicy = TokenPolicy()) -> dict[str, ClusterPolicy]:
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
        if (why := _placement_problem(e.get("placement") or {})) is not None:
            problems.append(f"cluster {cid}: placement {why}")
            continue
        thanos_url = e.get("thanosUrl")
        if thanos_url is not None:
            # The reader's token goes to it (capacity/thanos.py): never in clear text, nor as Basic auth from a userinfo (#310).
            try:
                require_https(thanos_url if isinstance(thanos_url, str) else "", "thanosUrl")
            except ValueError as exc:
                problems.append(f"cluster {cid}: {exc}")
                continue
        try:
            tokens = token_defaults.override(e.get("clusterTokens", {}))
        except ValueError as exc:
            raise ConfigError([f"clusters.yaml: {cid}.clusterTokens: {exc}"]) from exc
        out[cid] = ClusterPolicy(cluster_id=cid, environment=env, gitops_path=e.get("gitopsPath", f"clusters/{cid}"),
                                 writes=bool(e.get("writes", True)), sync_signal=e.get("syncSignal", "poll"),
                                 delivery=e.get("delivery"), thanos_url=e.get("thanosUrl"),
                                 labels=dict(e.get("labels") or {}), metadata=dict(e.get("metadata") or {}),
                                 cluster_tokens=tokens, placement=dict(e.get("placement") or {}), simulated_capacity=e.get("simulatedCapacity"))
    if problems:
        raise ValueError("clusters.yaml: " + "; ".join(problems))
    return out


# --------------------------------------------------------------------------- import sources


class ImportSource:
    """Yields the import Secrets as plain dicts: {name, labels, annotations, data(decoded)}."""

    def list(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class _ImportLoader(yaml.SafeLoader):
    """Preserve date-like scalars as text in Secret documents, as the Kubernetes annotation and data fields do."""


_ImportLoader.add_constructor("tag:yaml.org,2002:timestamp", _ImportLoader.construct_scalar)


class DirImportSource(ImportSource):
    def __init__(self, directory: Path):
        self.dir = directory

    def list(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.dir.glob("*.yaml")):
            for doc in yaml.load_all(p.read_text(), Loader=_ImportLoader):
                if doc and doc.get("kind") == "Secret":
                    out.append(_secret(doc))
        return out


class HubImportSource(ImportSource):
    """Lists Secrets in the hub's cmapi-imports namespace with the pod's own ServiceAccount."""

    def __init__(self, api_url: str, token_file: Path, ca_file: Path, namespace: str):
        require_https(api_url, "CMAPI_KUBE_API_URL")       # before the token is read: never sent in clear text
        self.namespace = namespace
        self.token_file = token_file
        # The hub's own ServiceAccount CA, else the trusted mode: never httpx's verify=True (certifi or SSL_CERT_FILE, #434).
        verify = file_context(str(ca_file)) if ca_file.exists() else trusted_context()
        self.client = httpx.Client(base_url=api_url, verify=verify, timeout=10)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        # The kubelet rotates this projected credential during the worker's lifetime.
        headers["Authorization"] = f"Bearer {self.token_file.read_text().strip()}"
        try:
            with cluster_http_call():
                response = self.client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError:
            response = None
        if response is None:
            raise RuntimeError("hub Secret request failed")
        if not response.is_success:
            # A proxy can echo any part of the submitted Secret. Only the status is diagnostic.
            raise KubeError(response.status_code, path, "hub Secret request failed")
        return response

    def list(self) -> list[dict[str, Any]]:
        """Every import Secret, or an error: `refresh` then keeps the previous set (docs/02 "Discovery"). An answer that is not
        a list of Secrets (not JSON, not an object, no items) is BadResponse, never an empty list that would retire every
        cluster (#421)."""
        path = f"/api/v1/namespaces/{self.namespace}/secrets"
        r = self._request("GET", path, params={"labelSelector": "cmapi.net/secret-type=cluster"})
        return [_secret(s) for s in list_items(KubeClient._object(r, path, sensitive=True), path, r.status_code)]

    def patch_token(self, name: str, version: str, token: str, expires: str) -> None:
        path = f"/api/v1/namespaces/{self.namespace}/secrets/{name}"
        self._request("PATCH", path, headers={"Content-Type": "application/merge-patch+json"},
                      json={"metadata": {"resourceVersion": version, "annotations": {"cmapi.net/token-expires-at": expires}},
                            "data": {"token": base64.b64encode(token.encode()).decode()}})


def _valid_ca_data(ca_data: str) -> bool:
    """Each PEM block by itself: a service account's ca.crt is usually a bundle, and base64 padding may end any block, so
    the blocks joined are not base64 even when each one is. A boundary is a whole line: a BEGIN or END line of PEM_BLOCKS,
    then only SP or HTAB (RFC 7468 sections 2 and 3, whose lines end in CRLF, CR or LF). Each BEGIN line needs the END line
    of its label before the next BEGIN, and each END line an open BEGIN of its label (#585): OpenSSL refuses a block that is
    not closed. Other text before, between and after the blocks is ignored, as RFC 7468 and OpenSSL allow, even a sentence
    that quotes a boundary, and text that is not ASCII, which the client hands the loader as "?" (#591). A value with no
    boundary line is read as bare base64, as before; the client finds no certificate in it and says so (#419).
    One pass over the lines, in linear time: the regex this replaces rescanned the rest of the value from every BEGIN."""
    def decodes(lines: list[str]) -> bool:
        text = "".join(lines)
        if not text.isascii():
            return False                   # base64 is ASCII; str.split() would drop a no-break space the loader refuses (#591)
        try:
            return bool(base64.b64decode("".join(text.split()), validate=True))
        except (binascii.Error, ValueError):
            return False

    lines = re.split(r"\r\n|\r|\n", ca_data)
    body: list[str] | None = None          # the lines of the open block; None outside a block
    end: str | None = None                 # the END line the open block needs
    blocks = 0
    for line in lines:
        boundary = line.rstrip(" \t")
        if boundary in PEM_BLOCKS:
            if body is not None:
                return False               # a BEGIN inside an open block
            body, end = [], PEM_BLOCKS[boundary]
        elif boundary in PEM_BLOCKS.values():
            if body is None or boundary != end or not decodes(body):
                return False               # an END with no open BEGIN of its label, or a body that is not base64
            body, end, blocks = None, None, blocks + 1
        elif body is not None:
            body.append(line)
    if body is not None:
        return False                       # the last BEGIN is never closed
    return blocks > 0 or decodes([line for line in lines if not line.startswith("-----")])


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
            "resourceVersion": meta.get("resourceVersion"), "data": data, "undecodable": undecodable}


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
                 nodes_factory: Callable[[ClusterState, KubeClient], NodeCache | None] | None = None,
                 usage_grants: bool = False):
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
        # True when the instance reads usage from each cluster's Thanos Querier (capacity.yaml usage.source thanos, #724):
        # each check then asks whether the reader's own grants allow it.
        self.usage_grants = usage_grants
        self.clusters: dict[str, ClusterState] = {cid: ClusterState(cid, p) for cid, p in self.policies.items()}
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._stop = threading.Event()
        # Last successful discovery, private to the relist/probe lock (includes refused imports).
        self._imports: dict[str, list[dict[str, Any]]] = {}
        self._fingerprints: dict[str, str] = {}

    # ---- the six checks
    def import_trust(self, secret: Mapping[str, Any], policy: ClusterPolicy | None) -> tuple[Trust | None, list[str]]:
        """Validate the connection before either discovery or self-renewal sends a credential."""
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
        env = policy.environment if policy else None
        if insecure and env not in self.insecure_environments:
            where = env if env is not None else "<none>"
            findings.append(f"insecure is not allowed for environment {where}: "
                            f"instance.clusterTLS.environments.{where}.insecureSkipTLSVerify is false")
        if findings:
            return None, findings
        # The root dot of a fully qualified name names the same host; OpenSSL matches the name as written, so it is dropped.
        server_name = server_name.removesuffix(".") if server_name else None
        trust = (Trust("insecure", server_name=server_name) if insecure
                 else Trust("caData", ca_data=ca_data, server_name=server_name) if ca_data
                 else Trust("trusted", server_name=server_name, bundles=self.trusted_ca_file))
        return trust, []

    def _check(self, st: ClusterState, secret: Mapping[str, Any]) -> ClusterState:
        cluster_id = st.cluster_id
        trust, findings = self.import_trust(secret, st.policy)
        if trust is None:
            return self._set(st, "invalid-secret", findings, None, secret)
        d = secret["data"]
        api_url = d["apiUrl"]
        try:
            # The whole token, as a SHA-256: a rotated token that ends in the same characters still gives the caches the new
            # client. The digest stays in memory, compared and never shown.
            fp = f"{api_url}|{hashlib.sha256(d['token'].encode()).hexdigest()}|{trust.fingerprint()}"
            # The client builds the SSL context: a caData of valid base64 that is no certificate fails now, not at a call (#419),
            # and so does a bundle of CMAPI_TRUSTED_CA_FILE that does not load (TrustBundleError, which names it).
            client = self.client_factory(cluster_id, api_url, d["token"], trust, insecure=trust.source == "insecure")
        except OSError as exc:                                      # ssl.SSLError is an OSError, as a missing file is
            if trust.source == "caData" and isinstance(exc, ssl.SSLError):
                return self._set(st, "invalid-secret", [f"invalid caData: {exc}"], None, secret)
            return self._set(st, "cert-verify-failed", [f"{exc}; trust store: {trust.store_name()}"], None, secret, trust)
        adopted = False                     # the client is closed unless the caches took it, whatever ends the check
        try:
            status, found, version = self._probe(client, trust)
            if status != "connected":
                return self._set(st, status, found, version, secret, trust, probed=True)
            usage = self._usage_grants(client, st.policy) if self.usage_grants else []
            # Anything the client verifies with is in the fingerprint (G6 of #434): a rotated caData, a new server name, a
            # change of mode or a bundle that changed gives the caches the new client, not only a new token or URL.
            if st.client is None or self._fingerprints.get(cluster_id) != fp:
                self._stop_caches(st)
                ledger = CapacityLedger()
                cache = WatchCache(client, admit=ledger.admit, dropped=ledger.dropped)
                with self._lock:
                    # Together, under the lock `quota_watch` reads them under: a read never pairs one cache with another's ledger.
                    st.client, st.ledger, st.cache = client, ledger, cache
                    # Readers can query this client while its watches start. Publish its own decision with it.
                    forms = _diagnostic_forms(secret)
                    st.usage_findings = [redact(f, forms) for f in usage]
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
            # Cache setup can still fail after the probe. Publish only the completed check.
            return self._set(st, "connected", usage, version, secret, trust, probed=True, usage=usage)
        except Exception as exc:                           # the remote check ran, even if cache setup then failed
            return self._check_failed(st, secret, exc, probed=True)
        finally:
            if not adopted:
                # A cache setup failure drops the partially installed caches. Close their client here too.
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

    @staticmethod
    def _usage_grants(client: KubeClient, policy: ClusterPolicy | None) -> list[str]:
        """The findings of the reader's own grants for the cluster's Thanos Querier, [] when it holds them (#724).

        Asked of the API server by a LocalSubjectAccessReview in openshift-monitoring, for the reader with its ServiceAccount
        groups and without system:authenticated, so only a grant to the reader or its ServiceAccount groups counts, never one
        to every user. The live query does not prove that: the Querier's kube-rbac-proxy reviews the token's own user, groups
        included. The Route is read only without a clusters.yaml thanosUrl (capacity/thanos.py). A cluster that serves no
        monitoring.coreos.com/v1 has no OpenShift monitoring, and one finding says so. A check that cannot be asked is a
        finding too: an unknown grant is not taken as held."""
        try:
            if not client.served("monitoring.coreos.com/v1"):
                return [USAGE_NO_MONITORING]
        except (KubeError, ClusterUnreachable, BadResponse) as exc:
            return [USAGE_UNCHECKED + str(exc)[:200]]
        reads = [QUERY_READ] if policy and policy.thanos_url else [ROUTE_READ, QUERY_READ]
        missing: list[str] = []
        try:
            for attributes, grant in reads:
                allowed = client.access_review(MONITORING_NAMESPACE, READER_IDENTITY, READER_GROUPS, attributes)
                if allowed is None:          # the authorizer failed to decide: not a missing grant
                    return [USAGE_UNCHECKED + "the API server reported an authorization evaluation error"]
                if not allowed:
                    missing.append(f"{USAGE_FINDING}missing grant in {MONITORING_NAMESPACE}: {grant}")
        except KubeError as exc:
            cause = f"missing grant in {MONITORING_NAMESPACE}: {GRANT_CHECK}" if exc.status == 403 else str(exc)[:200]
            return [USAGE_UNCHECKED + cause]
        except (ClusterUnreachable, BadResponse) as exc:
            return [USAGE_UNCHECKED + str(exc)[:200]]
        return missing

    def _set(self, st: ClusterState, status: str, findings: list[str], version: str | None,
             secret: Mapping[str, Any], trust: Trust | None = None, *, probed: bool = False,
             usage: list[str] | None = None) -> ClusterState:
        """Records one check's outcome. `trust` is the mode the check used, None when it ended before one was chosen.
        `usage`: those of `findings` that are the usage grants' (#724)."""
        # KubeClient redacts its token before any cut (#420). This second pass covers every other way a finding is made:
        # GET /api/v1/clusters serves findings to each clusters:read caller, and the log below writes them.
        forms = _diagnostic_forms(secret)
        findings = [redact(f, forms) for f in findings]
        if version:
            version = redact(version, forms)
        with self._lock:
            previous_status = st.status
            changed = (previous_status, st.findings) != (status, findings)
            # A first import with a usage finding (#724) is logged: it is connected, not healthy.
            first_connected = (status == "connected" and not findings and st.checked_at is None
                               and previous_status == "not-imported")
            if status != "connected" and st.cache is not None:
                self._stop_caches(st)
                st.cache, st.ledger, st.client = None, None, None
            st.status, st.findings, st.server_version = status, findings, version
            st.usage_findings = [redact(f, forms) for f in usage or []]
            st.checked_at = datetime.now(timezone.utc)
            if status != previous_status:
                st.status_since = st.checked_at
            if probed:
                st.last_probe_at = st.checked_at
            st.secret_name = secret.get("name") if isinstance(secret.get("name"), str) else None
            st.token_expires_at = token_expiry(secret)
            lifetime = None
            if st.token_expires_at:
                try:
                    grant = ReaderGrant.parse(secret["data"]["token"])
                    if grant.expires == st.token_expires_at.timestamp():
                        lifetime = grant.expires - grant.issued
                except (ValueError, KeyError):
                    pass
            set_token_expiry(st.cluster_id, st.token_expires_at, lifetime)
            self.clusters[st.cluster_id] = st
            for s in STATUSES:
                CLUSTER_STATUS.labels(st.cluster_id, s).set(1 if s == status else 0)
            previous = self._set_trust(st, trust)
        self._log_mode(st.cluster_id, previous, trust)
        if changed and not first_connected:
            emit = log.info if status == "connected" and not findings else log.warning
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
        # Serialize list, checks, logs and retirement. Locking only _set lets two first checks compare separate states,
        # a delayed event follow its recovery, or an older probe restore a cluster after another pass retired it.
        # Keep _lock available to readers while a probe waits on the network.
        with self._refresh_lock:
            self._refresh()

    def _refresh(self) -> None:
        if self.source is None:
            return
        try:
            secrets = self.source.list()
        except Exception as exc:                                    # noqa: BLE001 - a failed list keeps the previous set
            log.warning("imports_list_failed", error=str(exc)[:200])
            return
        by_id: dict[str, list[dict[str, Any]]] = {}
        for s in secrets:
            cid = s["labels"].get("cmapi.net/cluster-id")
            if isinstance(cid, str) and cid:
                by_id.setdefault(cid, []).append(deepcopy(s))
        self._imports = by_id
        for cid, items in by_id.items():
            self._check_import(self.clusters.get(cid) or ClusterState(cid, None), items)
        with self._lock:
            for cid, st in self.clusters.items():
                if cid not in by_id and st.status != "not-imported":
                    previous_status = st.status
                    st.status, st.findings, st.usage_findings = "not-imported", [NO_IMPORT_SECRET], []
                    st.secret_name = st.token_expires_at = None
                    set_token_expiry(cid, None)
                    st.status_since = datetime.now(timezone.utc)
                    self._stop_caches(st)
                    st.cache, st.ledger, st.client = None, None, None
                    self._log_mode(cid, self._set_trust(st, None), None)
                    log.warning("cluster_import", cluster_id=cid, status=st.status,
                                previous=previous_status, findings=st.findings)

    def _check_import(self, st: ClusterState, items: list[dict[str, Any]]) -> None:
        if len(items) > 1:
            finding = f"duplicate cluster ID in {[i['name'] for i in items]}"
            for item in items:
                finding = redact(finding, secret_forms(item["data"].get("token")))
            self._set(st, "invalid-secret", [finding], None, {})
            return
        try:
            self._check(st, items[0])
        except Exception as exc:                                # noqa: BLE001 - one cluster never stops the rest (#419)
            self._check_failed(st, items[0], exc)

    def _check_failed(self, st: ClusterState, secret: Mapping[str, Any], exc: Exception, *, probed: bool = False) -> ClusterState:
        # Exception messages may include the import data. Never attach the live traceback to a log record.
        error_type = type(exc).__name__
        log.error("cluster_check_failed", cluster_id=st.cluster_id, error_type=error_type)
        detail = redact(str(exc), _diagnostic_forms(secret))
        finding = f"the check failed: {error_type}: {detail[:200]}"
        return self._set(st, "unreachable", [finding], None, secret, probed=probed)

    def probe(self, cluster_id: str) -> dict[str, Any]:
        """Recheck this cluster's held import and publish its normal diagnostics before releasing the relist lock."""
        with self._refresh_lock:
            st = self.get(cluster_id)
            if items := self._imports.get(cluster_id):
                self._check_import(st, items)
            return st.view()

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

    def snapshot(self, cluster_id: str) -> ClusterState:
        with self._lock:
            return copy(self.get(cluster_id))

    def snapshots(self) -> list[ClusterState]:
        """Copy the import fields and watch references together. The watches retain their own locks."""
        with self._lock:
            return [copy(st) for st in self.clusters.values()]

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
