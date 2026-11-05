"""The public API models (docs/02, Schemas). camelCase on the wire, snake_case in Python.

Every field carries a description and an example, because core/docs.py refuses to start a route
whose models are not fully described. A model without a cluster ID cannot be declared for a
cluster-scoped resource: inherit ClusterScoped.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

ClusterId = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,62}$")]
DnsLabel = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")]

ChangeStatus = Literal["pending_approval", "approved", "pr_open", "merged", "awaiting_prune", "rejected",
                       "synced", "failed", "sync_failed", "superseded", "cancelled", "timeout", "reverted"]


class Api(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid",
                              serialize_by_alias=True)


class ClusterScoped(Api):
    cluster_id: ClusterId = Field(description="The cluster the object lives on", examples=["OCP_GF1"])


# --------------------------------------------------------------------------- problems


class ProblemDetail(BaseModel):
    """RFC 9457 problem details, the one shape of every refusal."""
    model_config = ConfigDict(extra="allow")
    type: str = Field(description="Problem type URI", examples=["https://cmapi.ephico2real.com/problems/policy-violation"])
    title: str = Field(description="Short name of the problem", examples=["policy violation"])
    status: int = Field(description="HTTP status", examples=[422])
    detail: str = Field(description="What went wrong, for a person", examples=["Metadata refused"])
    code: str = Field(description="The problem code, the last segment of type", examples=["policy-violation"])
    errors: list[dict[str, Any]] | None = Field(default=None, description="Per-item codes", examples=[[{"code": "reserved_key", "key": "cmapi.net/tier"}]])


# --------------------------------------------------------------------------- identity


class RoleAccess(Api):
    role: str = Field(description="A Keycloak client role in the token", examples=["cmapi-requester"])
    permissions: list[str] = Field(description="Permissions the role grants", examples=[["namespaces:create", "objects:read"]])
    environments: list[str] | Literal["all"] = Field(description="Environments the role covers, or all", examples=["all"])


class Access(Api):
    roles: list[RoleAccess] = Field(description="Each held role with its permissions and environments")
    permissions: list[str] = Field(description="Every permission the caller holds somewhere", examples=[["objects:read"]])


class IdentityRecord(Api):
    sub: str | None = Field(description="Keycloak user ID", examples=["6f1c2a9e-4b7d-4e21-9c3a-0d8e5b7f2a14"])
    username: str = Field(description="preferred_username, or the client ID of a service", examples=["ola"])
    email: str | None = Field(description="Email from the token", examples=["ola@ephico2real.com"])
    given_name: str | None = Field(description="First name", examples=["Ola"])
    middle_name: str | None = Field(description="Middle name, from the cmapi-identity scope", examples=["A"])
    family_name: str | None = Field(description="Last name", examples=["Adeyemi"])
    employee_id: str | None = Field(description="Employee ID, from the cmapi-identity scope", examples=["1001"])
    kind: Literal["user", "service"] = Field(description="A person or a service-account client", examples=["user"])
    client_id: str | None = Field(default=None, description="azp of the token", examples=["cmapi-portal"])


class Me(Api):
    username: str = Field(description="Who is calling", examples=["ola"])
    kind: Literal["user", "service"] = Field(description="A person or a service-account client", examples=["user"])
    client: str = Field(description="The client the token was issued to", examples=["cmapi-portal"])
    roles: list[str] = Field(description="Client roles in the token", examples=[["cmapi-requester"]])
    groups: list[str] = Field(description="Keycloak group paths in the token", examples=[["/cmapi/cmapi-requesters"]])
    identity: IdentityRecord = Field(description="The identity cmapi records for this caller")
    access: Access = Field(description="What the roles allow, and where")
    instance: str = Field(description="The instance answering", examples=["nonprod"])


class DirectoryUser(Api):
    username: str = Field(description="Username", examples=["ola"])
    email: str | None = Field(description="Email", examples=["ola@ephico2real.com"])
    name: str = Field(description="Display name", examples=["Ola A Adeyemi"])
    employee_id: str | None = Field(default=None, description="Employee ID; only for cmapi-operator and above", examples=["1001"])


class DirectoryUsers(Api):
    items: list[DirectoryUser] = Field(description="Up to ten matches")


# --------------------------------------------------------------------------- requests


class ApprovalSlot(Api):
    group: str = Field(description="Approving group (token path /cmapi/cmapi-<group>)", examples=["platform-leads"])
    count: int = Field(description="Approvals needed from the group", examples=[1])
    reason: str = Field(description="Why this slot exists", examples=["Critical namespace pattern"])


class ApprovalEntry(Api):
    username: str = Field(description="Who approved", examples=["amy"])
    sub: str | None = Field(default=None, description="Approver's Keycloak user ID", examples=["7d2e..."])
    comment: str = Field(default="", description="Comment given with the approval", examples=["ok"])
    relayed_by: str | None = Field(default=None, description="Channel client that relayed the decision", examples=[None])
    at: datetime | None = Field(default=None, description="When", examples=["2026-11-05T10:00:00Z"])


class ApprovalRemaining(Api):
    group: str = Field(description="Group still needed", examples=["platform-leads"])
    needed: int = Field(description="Approvals still needed from it", examples=[1])


class ApprovalView(Api):
    rule: str = Field(description="The rule that applied", examples=["dev-create"])
    auto: str | None = Field(description="auto:<policy> or none-required when approved at plan time", examples=["auto:baseline-rnd-namespace"])
    auto_fallback: str | None = Field(description="The guard that stopped a matching policy", examples=[None])
    self_approval: bool = Field(default=False, description="Whether the requester may approve", examples=[True])
    timeout_hours: int = Field(default=24, description="Approval window", examples=[8])
    slots: list[ApprovalSlot] = Field(description="One slot per approving group")
    remaining: list[ApprovalRemaining] = Field(description="What is still needed")
    approvals: list[ApprovalEntry] = Field(description="Approvals recorded so far")
    reasons: list[str] = Field(description="Why approvals are needed", examples=[["Critical namespace pattern"]])


class CapacityView(Api):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow", serialize_by_alias=True)
    status: Literal["fits", "warn", "exceeded", "unknown"] = Field(description="The capacity check", examples=["fits"])
    fresh: bool = Field(default=True, description="Whether the data was fresh", examples=[True])
    binding_resource: str | None = Field(default=None, description="cpu or memory, whichever binds", examples=["memory"])


class PrView(Api):
    number: int = Field(description="PR number", examples=[12])
    url: str = Field(description="PR URL", examples=["https://git.example/cmapi/cluster-configs-nonprod/pulls/12"])
    branch: str = Field(description="Bot branch", examples=["cmapi/CRC/payments-dev/req-20261105-0001"])
    head: str = Field(description="PR head commit", examples=["0a1b2c3d"])


class RequestEvent(Api):
    at: datetime = Field(description="When", examples=["2026-11-05T10:00:00Z"])
    event: str = Field(description="Lifecycle event or note", examples=["pr_opened"])
    status: str | None = Field(description="Status after the event", examples=["pr_open"])
    by: str = Field(description="Actor", examples=["cmapi-bot"])
    note: str = Field(default="", description="Detail", examples=["cmapi/CRC/payments-dev/req-20261105-0001"])


class RequesterView(Api):
    requester: IdentityRecord = Field(description="The person or client the request is for")
    automated: bool = Field(description="Whether a service or automation account submitted it", examples=[False])
    submitted_by: str | None = Field(default=None, description="The caller, when it differs from the requester", examples=[None])
    submitted_by_client: str | None = Field(default=None, description="The service client that submitted", examples=[None])


class ChangeRequest(ClusterScoped):
    request_id: str = Field(description="Request ID", examples=["req-20261105-0001"])
    instance: str = Field(description="Instance that recorded it", examples=["nonprod"])
    namespace: str = Field(description="Target namespace", examples=["payments-dev"])
    env: str = Field(description="Environment", examples=["dev"])
    plugin: str = Field(description="Plugin that planned it", examples=["namespaces"])
    action: str = Field(description="create, update or delete", examples=["create"])
    reason: str | None = Field(description="Why the request was opened, when a plugin sets one", examples=["expiration:extend"])
    justification: str | None = Field(default=None, description="The requester's justification", examples=["Payments dev namespace"])
    status: ChangeStatus = Field(description="Lifecycle state", examples=["pending_approval"])
    plan_hash: str = Field(description="SHA-256 of the planned files; the PR must match it", examples=["9f2c..."])
    base_sha: str | None = Field(default=None, description="Git commit the plan was made against", examples=["0a1b2c3d"])
    approval: ApprovalView | None = Field(description="Approval requirement and ledger")
    requester: RequesterView = Field(description="Who asked")
    pr: PrView | None = Field(description="The bot PR, once open")
    merge_sha: str | None = Field(description="Merge commit, once merged", examples=["4e5f6a7b"])
    files: dict[str, str] = Field(description="Per file: added, changed, removed or unchanged", examples=[{"clusters/CRC/namespaces/payments-dev/namespace.yaml": "added"}])
    events: list[RequestEvent] = Field(description="Every state change, oldest first")
    created_at: datetime = Field(description="When it was submitted", examples=["2026-11-05T10:00:00Z"])
    updated_at: datetime = Field(description="Last change", examples=["2026-11-05T10:00:00Z"])
    links: dict[str, str] = Field(description="self, events, pr", examples=[{"self": "/api/v1/requests/req-20261105-0001"}])


class PageInfo(Api):
    limit: int = Field(description="Page size", examples=[50])
    total: int = Field(description="Rows matching the filters", examples=[120])
    from_: int = Field(alias="from", description="1-based index of the first row", examples=[1])
    to: int = Field(description="Index of the last row", examples=[50])
    next_cursor: str | None = Field(description="Cursor for the next page", examples=["eyJ..."])
    prev_cursor: str | None = Field(description="Cursor for the previous page", examples=[None])


class RequestPage(Api):
    items: list[ChangeRequest] = Field(description="One page of requests")
    page: PageInfo = Field(description="Paging")
    letters: dict[str, int] = Field(description="Rows per first letter of the namespace", examples=[{"P": 3}])


class RequestEvents(Api):
    request_id: str = Field(description="Request ID", examples=["req-20261105-0001"])
    status: ChangeStatus = Field(description="Current state", examples=["synced"])
    events: list[RequestEvent] = Field(description="Every event, oldest first")


class ApprovalStatus(Api):
    request_id: str = Field(description="Request ID", examples=["req-20261105-0001"])
    approved: bool = Field(description="Whether the request is approved or further along", examples=[True])
    status: ChangeStatus = Field(description="Current state", examples=["pr_open"])
    plan_hash: str = Field(description="The approved plan hash", examples=["9f2c..."])


class DecisionBody(Api):
    comment: str = Field(default="", description="A comment; required for a rejection", examples=["sizing reviewed"])


# --------------------------------------------------------------------------- namespaces


class NamespaceCreate(Api):
    namespace: DnsLabel = Field(description="Namespace name: DNS-1123, not reserved", examples=["payments-dev"])
    tier: str = Field(default="small", description="A tier from the catalog, or custom", examples=["small"])
    quota: dict[str, str] | None = Field(default=None, description="Sizable quota keys, custom tier only", examples=[None])
    labels: dict[str, str] = Field(default_factory=dict, description="Governed and team labels", examples=[{"cmapi.net/team": "payments"}])
    annotations: dict[str, str] = Field(default_factory=dict, description="Governed and team annotations", examples=[{"cmapi.net/team-dl": "payments-team@ephico2real.com"}])
    expires_at: date | None = Field(default=None, description="Optional expiry; never in prod", examples=["2026-12-15"])
    placement_id: str | None = Field(default=None, description="Reservation from POST /capacity:place", examples=[None])
    on_behalf_of: str | None = Field(default=None, description="Username or employee ID, for services and automation", examples=[None])
    justification: str | None = Field(default=None, description="Why the namespace is needed", examples=["Payments service dev namespace"])


class NamespacePatch(Api):
    tier: str | None = Field(default=None, description="New tier", examples=["large"])
    quota: dict[str, str] | None = Field(default=None, description="Custom quota values", examples=[None])
    labels: dict[str, str | None] | None = Field(default=None, description="Merge patch; null removes a key", examples=[{"cmapi.net/cost-center": "cc-4410"}])
    annotations: dict[str, str | None] | None = Field(default=None, description="Merge patch; null removes a key", examples=[None])
    on_behalf_of: str | None = Field(default=None, description="Username or employee ID, for services and automation", examples=[None])
    justification: str | None = Field(default=None, description="Why", examples=["More capacity for the batch"])


class PlanView(Api):
    changes: dict[str, str] = Field(description="Per changed file: added, changed or removed", examples=[{"clusters/CRC/namespaces/payments-dev/namespace.yaml": "added"}])
    plan_hash: str = Field(description="SHA-256 of the planned files", examples=["9f2c..."])
    etag: str | None = Field(description="Git commit the plan was made against; send it as If-Match", examples=["0a1b2c3d"])
    requester: RequesterView = Field(description="Who the request would be for")
    capacity: CapacityView = Field(description="The capacity check")
    approval: ApprovalView = Field(description="The approval that would apply")
    files: dict[str, str] = Field(description="Rendered content of each changed file", examples=[{"clusters/CRC/namespaces/payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\n..."}])
    findings: list[dict[str, Any]] = Field(default_factory=list, description="Validator warnings", examples=[[]])


class NamespaceView(ClusterScoped):
    name: str = Field(description="Namespace name", examples=["payments-dev"])
    env: str | None = Field(description="Environment label", examples=["dev"])
    team: str | None = Field(description="cmapi.net/team", examples=["payments"])
    tier: str | None = Field(description="cmapi.net/tier", examples=["small"])
    labels: dict[str, str] = Field(description="Labels", examples=[{"cmapi.net/team": "payments"}])
    annotations: dict[str, str] = Field(description="Annotations", examples=[{"cmapi.net/team-dl": "payments-team@ephico2real.com"}])
    managed: bool = Field(description="Whether cmapi manages it", examples=[True])
    expires_at: str | None = Field(description="cmapi.net/expires-at", examples=[None])
    etag: str | None = Field(description="Git commit of its folder; send as If-Match on a change", examples=["0a1b2c3d"])
    open_request: str | None = Field(description="Request holding the namespace lock", examples=[None])


class NamespaceList(Api):
    items: list[NamespaceView] = Field(description="Managed namespaces on the cluster")


# --------------------------------------------------------------------------- quotas


class QuotaRow(Api):
    name: str = Field(description="Namespace", examples=["payments-dev"])
    cluster_id: str = Field(description="Cluster", examples=["CRC"])
    env: str | None = Field(description="Environment", examples=["dev"])
    team: str | None = Field(description="Team", examples=["payments"])
    app: str | None = Field(default=None, description="cmapi.net/app", examples=[None])
    tier: str | None = Field(description="Tier", examples=["small"])
    cpu: list[str | None] = Field(description="[used, hard] requests.cpu", examples=[["0", "8"]])
    memory: list[str | None] = Field(description="[used, hard] requests.memory", examples=[["0", "16Gi"]])
    pods: list[str | None] = Field(description="[used, hard] pods", examples=[["0", "50"]])
    used: float = Field(description="Highest used/hard ratio of the three", examples=[0.0])
    expires_at: str | None = Field(description="cmapi.net/expires-at", examples=[None])
    tier_hash: str | None = Field(description="Catalog hash the quota was rendered from", examples=["dec3e603bf8d"])
    tier_outdated: bool = Field(description="The catalog changed since it was rendered", examples=[False])
    open_request: str | None = Field(default=None, description="Request holding the namespace", examples=[None])


class QuotaPage(Api):
    items: list[QuotaRow] = Field(description="One page")
    page: PageInfo = Field(description="Paging")
    letters: dict[str, int] = Field(description="Rows per first letter", examples=[{"P": 3}])
    facets: dict[str, int] = Field(description="Attention counts over the filters", examples=[{"near-limit": 0}])


class Suggestion(Api):
    name: str = Field(description="Namespace", examples=["payments-dev"])
    cluster_id: str = Field(description="Cluster", examples=["CRC"])
    why: str = Field(description="Why it matched", examples=["name starts with"])


class Suggestions(Api):
    items: list[Suggestion] = Field(description="Up to ten matches")


# --------------------------------------------------------------------------- clusters, tiers, health


class ClusterView(Api):
    cluster_id: str = Field(description="Cluster ID", examples=["CRC"])
    environment: str = Field(description="Environment from clusters.yaml", examples=["dev"])
    gitops_path: str = Field(description="Folder in cluster-configs", examples=["clusters/CRC"])
    writes: bool = Field(description="Whether writes are allowed", examples=[True])
    status: str = Field(description="connected, unreachable, auth_failed, not-imported, ...", examples=["connected"])
    findings: list[str] = Field(description="Import check findings", examples=[[]])
    server_version: str | None = Field(description="Kubernetes version seen", examples=["v1.35.6"])
    labels: dict[str, str] = Field(description="Metadata labels", examples=[{"region": "us-central"}])
    checked_at: datetime | None = Field(description="Last import check", examples=["2026-11-05T10:00:00Z"])


class ClusterList(Api):
    items: list[ClusterView] = Field(description="Every cluster this instance knows")


class Health(Api):
    status: str = Field(description="ok", examples=["ok"])
    instance: str = Field(description="Instance name", examples=["nonprod"])
    version: str = Field(description="cmapi version", examples=["0.2.0"])
    issuer: str = Field(description="OIDC issuer trusted", examples=["https://keycloak.apps-crc.testing/realms/cmapi"])
    audience: str = Field(description="Token audience required", examples=["cmapi-nonprod"])
    database: str = Field(description="ok or an error class", examples=["ok"])
    git: str = Field(description="Repository the bot writes to", examples=["cmapi/cluster-configs-nonprod"])
    clusters: dict[str, str] = Field(description="Cluster ID to import status", examples=[{"CRC": "connected"}])


class Ok(Api):
    ok: bool = Field(description="Always true", examples=[True])


class TierCatalogView(BaseModel):
    """Body of GET /tiers: the catalog as core/tiers.py describes it."""
    model_config = ConfigDict(extra="allow")
    catalog_hash: str = Field(alias="catalogHash", description="Hash of the catalog", examples=["dec3e603bf8d"])
    sizable: list[str] = Field(description="Quota keys a request may size", examples=[["requests.cpu", "requests.memory", "pods"]])
    environments: dict[str, Any] = Field(description="Per environment: tiers and custom bounds", examples=[{"dev": {"tiers": [], "custom": {}}}])


class PruneConfirm(Api):
    namespace: str = Field(description="Namespace whose delete is awaiting a prune", examples=["payments-dev"])
    cluster_id: str | None = Field(default=None, description="Cluster, when the name is ambiguous", examples=["CRC"])
