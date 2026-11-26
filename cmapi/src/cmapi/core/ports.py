"""Every extension point and outside dependency of cmapi-core, as typed Protocols.

Core and plugins depend only on these; adapters implement them and register under
cmapi.adapters.<point> (docs/01, Modularity). An adapter is chosen per instance in instance.yaml,
integrations.yaml, capacity.yaml or plugins.yaml. Each Protocol below says which module owns the
default adapter. The pure-logic modules (tiers, metadata, approvals, lifecycle, expiration,
listquery, render, identity checks) need none of these and are tested without them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

from cmapi.core.identity.claims import Identity
from cmapi.core.identity.directory import DirectoryProvider  # noqa: F401  (re-exported)

# --------------------------------------------------------------------------- shared value types


@dataclass(frozen=True)
class Finding:
    source: Literal["kyverno", "kubeconform", "cmapi"]
    rule: str                                     # the policy's name for Kyverno, the check's name for cmapi, `schema`
    path: str
    message: str
    severity: Literal["error", "warning"] = "error"
    # Kyverno's own rule name from its report (#302): `validation` for a ValidatingPolicy, the rule of a hand-written
    # ClusterPolicy. None for every other source.
    kyverno_rule: str | None = None

    def view(self) -> dict[str, Any]:
        """The JSON form of a finding in a plan, a 422 and a stored refusal: camelCase, as the rest of the API."""
        return {"source": self.source, "rule": self.rule, "path": self.path, "message": self.message,
                "severity": self.severity, "kyvernoRule": self.kyverno_rule}


@dataclass(frozen=True)
class CapacityResult:
    status: Literal["fits", "warn", "exceeded", "unknown"]
    fresh: bool
    binding_resource: str | None = None          # cpu or memory, whichever binds
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PrRef:
    number: int
    url: str
    branch: str
    head_sha: str


@dataclass(frozen=True)
class PrStatus:
    state: Literal["open", "merged", "closed"]
    checks: Mapping[str, Literal["pending", "success", "failure"]]
    merge_sha: str | None = None
    head_sha: str | None = None                   # the PR's head as the host reports it (#286: merge pins it)


@dataclass(frozen=True)
class AppStatus:
    cluster_id: str
    revision: str
    sync: Literal["Synced", "OutOfSync", "Unknown"]
    health: str
    phase: str | None
    revisions: frozenset[str] = frozenset()       # status.sync.revisions (multi-source) or {status.sync.revision}
    resources: tuple[tuple[str, str, str, str], ...] = ()   # (kind, namespace, name, status) from status.resources
    prune_pending: frozenset[str] = frozenset()   # namespaces waiting on Prune=confirm


@dataclass(frozen=True)
class PolicyResult:
    cluster_id: str
    policy: str
    rule: str
    result: Literal["pass", "fail", "warn", "error", "skip"]
    resource: str
    namespace: str | None
    message: str


@dataclass(frozen=True)
class CloudEvent:
    id: str
    type: str                                     # cmapi.request.synced, cmapi.namespace.expiring, ...
    subject: str                                  # <clusterId>/<namespace>
    time: datetime
    data: Mapping[str, Any]


# --------------------------------------------------------------------------- extension points


@runtime_checkable
class Authenticator(Protocol):
    """core/auth.py (OIDC against the Keycloak realm, offline JWKS)."""
    def authenticate(self, bearer: str) -> Identity: ...


@runtime_checkable
class Renderer(Protocol):
    """core/render/manifests.py (raw manifests); project_meta.py and Kustomize are alternatives."""
    def render(self, spec: Any, previous: Mapping[str, str] | None = None) -> dict[str, str | None]: ...
    def delete(self, cluster_id: str, namespace: str, previous: Mapping[str, str]) -> dict[str, None]: ...


@runtime_checkable
class GitProvider(Protocol):
    """core/git/ (#286): a Git layer for branches, commits and reads (workspace.py) and a thin platform adapter per host for the
    PR (github.py; gitea.py is REST alone). The full contract is core/git/base.py HostGitProvider. Every change is a request
    branch and a PR; nothing pushes to the default branch."""
    external_ci: bool
    post_statuses: bool
    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]: ...  # files, commit sha
    def list_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]: ...  # {path: blob|commit}, sha
    def push_request_branch(self, req: Any) -> Any: ...                  # BranchRequest -> PushResult
    def open_pr(self, branch: str, head: str, title: str, body: str) -> PrRef: ...
    def pr_status(self, pr: PrRef) -> PrStatus: ...
    def merge_check(self, head: str, folder: str, prev: Mapping[str, str], files: Mapping[str, str | None], *,
                    whole_folder: bool = False) -> Any: ...
    def merge(self, pr: PrRef, expected_head: str) -> str: ...          # merge sha, pinned to expected_head
    def comment(self, pr: PrRef, text: str) -> None: ...
    def close(self, pr: PrRef, comment: str) -> None: ...
    def delete_branch(self, branch: str, expected: str) -> bool: ...


@runtime_checkable
class Validator(Protocol):
    """core/validate/: the Kyverno CLI bundle plus kubeconform on the rendered files."""
    def validate(self, files: Mapping[str, str], cluster_id: str, environment: str,
                 previous: Mapping[str, str | None] | None = None, held: list[Finding] | None = None) -> list[Finding]: ...


@runtime_checkable
class CapacityBackend(Protocol):
    """remote (cmapi-capacity over HTTP, default) or embedded (the worker runs the jobs).

    The holds of open requests live in the cmapi schema, so `reserve_check`, `reserve`, `confirm` and `release` take the
    caller's transaction: "Placement, the capacity check inside every plan [...] stay in the API, because they write requests
    or reservations" (docs/01). The hold is core/capacity_backend.py's CapacityHold."""
    def check(self, cluster_id: str, environment: str, cpu_delta: float, memory_delta: float, *, session: Any = None,
              exclude: str | None = None, namespace: str | None = None) -> CapacityResult: ...
    def place(self, environment: str, team: str, tier: str, constraints: Mapping[str, Any]) -> dict[str, Any]: ...
    def reserve_check(self, session: Any, cluster_id: str, environment: str, hold: Any) -> CapacityResult: ...
    def reserve(self, session: Any, request_id: str, cluster_id: str, hold: Any, term: timedelta) -> None: ...
    def confirm(self, session: Any, request_id: str, cluster_id: str, environment: str) -> CapacityResult | None: ...
    def release(self, session: Any, request_id: str, why: str) -> int: ...


@runtime_checkable
class MetricsSource(Protocol):
    """Each cluster's Thanos Querier (default) or an ACM Observability hub. Used by cmapi-capacity only."""
    def query(self, cluster_id: str, promql: str, at: datetime | None = None) -> list[dict[str, Any]]: ...


@runtime_checkable
class SyncSignal(Protocol):
    """poll (default) or notify (Argo CD Notifications webhook, then confirmed by a read)."""
    def status(self, cluster_id: str) -> AppStatus: ...


@runtime_checkable
class OperationsEngine(Protocol):
    """builtin (worker steps, default), Argo Workflows or Tekton."""
    def start(self, template: str, parameters: Mapping[str, Any], started_by: Identity) -> str: ...
    def status(self, operation_id: str) -> Mapping[str, Any]: ...
    def cancel(self, operation_id: str) -> None: ...


@runtime_checkable
class EventPublisher(Protocol):
    """none (default), signed webhook, Kafka. Fed from the outbox table, so delivery is at least once."""
    def publish(self, event: CloudEvent) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    """email (default), Slack, Teams. Expiry notices and approval prompts go to the team DL."""
    def send(self, to: list[str], subject: str, body: str, links: Mapping[str, str] | None = None) -> None: ...


@runtime_checkable
class ApprovalChannel(Protocol):
    """portal (default), email link, argo-events, servicenow, slack/teams. A channel notifies or
    relays; the decision is always POST /requests/{id}:approve with an eligible person's identity."""
    name: str
    def notify_pending(self, request: Mapping[str, Any], groups: list[str]) -> None: ...
    def notify_decision(self, request: Mapping[str, Any], decision: str) -> None: ...


# --------------------------------------------------------------------------- readers


@runtime_checkable
class KubeReader(Protocol):
    """core/clients/kube.py: watch cache per cluster through the read-only cmapi-reader."""
    def namespaces(self, cluster_id: str) -> list[Mapping[str, Any]]: ...
    def get(self, cluster_id: str, kind: str, namespace: str | None, name: str) -> Mapping[str, Any] | None: ...
    def quota(self, cluster_id: str, namespace: str) -> Mapping[str, Any] | None: ...


@runtime_checkable
class PolicyReportReader(Protocol):
    """plugins/policies: PolicyReport and ClusterPolicyReport (wgpolicyk8s.io), CEL policy kinds."""
    def results(self, cluster_id: str) -> list[PolicyResult]: ...
    def bundle_tag(self, cluster_id: str) -> str | None: ...


@runtime_checkable
class AuditLog(Protocol):
    """core/audit.py: audit_events rows; never token values."""
    def record(self, actor: Identity, action: str, target: str, detail: Mapping[str, Any]) -> None: ...


@runtime_checkable
class Plugin(Protocol):
    """Every plugin: name, a router, models, a planner and its read RBAC (docs/01, Adding an offering)."""
    name: str
    def routes(self) -> Any: ...
    def plan(self, request: Mapping[str, Any], caller: Identity) -> Mapping[str, Any]: ...
