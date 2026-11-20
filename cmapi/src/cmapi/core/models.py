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
                       "synced", "failed", "sync_failed", "superseded", "cancelled", "timeout", "reverted", "applied", "merge_failed"]


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
    groups: list[str] = Field(description="Keycloak group paths in the token", examples=[["/cmapi/app-cmapi-rbac-requester"]])
    identity: IdentityRecord = Field(description="The identity cmapi records for this caller")
    access: Access = Field(description="What the roles allow, and where")
    instance: str = Field(description="The instance answering", examples=["nonprod"])
    operator: bool = Field(description="Whether the caller is an operator somewhere: it holds namespaces:protect, so it may "
                                       "set the operator-only labels and annotations of metadata-keys.yaml "
                                       "(cmapi.net/protected). The portal shows the operator's controls from it; the API "
                                       "checks each write in its environment", examples=[False])
    operator_environments: list[str] | Literal["all"] = Field(description="Where the caller is an operator: the environments "
                                                              "of namespaces:protect, or all", examples=[[]])


class DirectoryUser(Api):
    username: str = Field(description="Username", examples=["ola"])
    email: str | None = Field(description="Email", examples=["ola@ephico2real.com"])
    name: str = Field(description="Display name", examples=["Ola A Adeyemi"])
    employee_id: str | None = Field(default=None, description="Employee ID; only for an operator (namespaces:protect)", examples=["1001"])


class DirectoryUsers(Api):
    items: list[DirectoryUser] = Field(description="Up to ten matches")


# --------------------------------------------------------------------------- requests


class ApprovalSlot(Api):
    group: str = Field(description="Approving group (token path identity.groupPath, by default /cmapi/app-cmapi-rbac-<group>)", examples=["approver-platform"])
    count: int = Field(description="Approvals needed from the group", examples=[1])
    reason: str = Field(description="Why this slot exists", examples=["Critical namespace pattern"])


class ApprovalEntry(Api):
    username: str = Field(description="Who approved", examples=["amy"])
    sub: str | None = Field(default=None, description="Approver's Keycloak user ID", examples=["7d2e..."])
    comment: str = Field(default="", description="Comment given with the approval", examples=["ok"])
    relayed_by: str | None = Field(default=None, description="Channel client that relayed the decision", examples=[None])
    at: datetime | None = Field(default=None, description="When", examples=["2026-11-05T10:00:00Z"])


class ApprovalRemaining(Api):
    group: str = Field(description="Group still needed", examples=["approver-platform"])
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
    branch: str = Field(description="Bot branch", examples=["cmapi/CRC/req-20261105-0001"])
    head: str = Field(description="PR head commit", examples=["0a1b2c3d"])


class RequestEvent(Api):
    at: datetime = Field(description="When", examples=["2026-11-05T10:00:00Z"])
    event: str = Field(description="Lifecycle event or note", examples=["pr_opened"])
    status: str | None = Field(description="Status after the event", examples=["pr_open"])
    by: str = Field(description="Actor", examples=["cmapi-bot"])
    note: str = Field(default="", description="Detail", examples=["cmapi/CRC/req-20261105-0001"])


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
    beyond_tier: BeyondTier | None = Field(default=None, description="The values beyond the tier and the approvals they add; null when the request has none")
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

# kind (container, pvc) -> part (min, defaultRequest, default, max) -> resource (cpu, memory, storage) -> quantity. The catalog
# decides which keys a request can send (tiers.yaml, overridable), so the model does not fix them.
LimitRangeValues = dict[str, dict[str, dict[str, str]]]
# No pvc item: storage LimitRanges are off unless tiers.yaml turns them on (#253), so the instances refuse one.
LIMIT_RANGE_EXAMPLE = {"container": {"default": {"cpu": "1", "memory": "1Gi"}, "max": {"cpu": "4", "memory": "8Gi"}}}


class BeyondTierKey(Api):
    key: str = Field(description="The key: a quota key, or limitRange.<kind>.<part>.<resource>", examples=["limitRange.container.max.cpu"])
    tier: str | None = Field(description="The value that the tier sets, or null when the tier sets none", examples=["2"])
    requested: str = Field(description="The value that the request asks for", examples=["4"])


class BeyondTier(Api):
    keys: list[BeyondTierKey] = Field(description="Each value of this request that differs from its tier and from the value that Git holds")
    approvals: list[ApprovalSlot] = Field(description="The approvals that the beyond-tier rules of approval-rules.yaml add for them, "
                                                      "on top of the environment's rule")


class NamespaceCreate(Api):
    namespace: DnsLabel = Field(description="Namespace name: DNS-1123, not reserved", examples=["payments-dev"])
    tier: str = Field(default="small", description="A tier from the catalog, or custom", examples=["small"])
    quota: dict[str, str] | None = Field(default=None, description="Custom tier only: each sizable quota key, and any overridable quota key of GET /tiers. An overridable value that differs from the tier needs the beyond-tier approval", examples=[None])
    limit_range: LimitRangeValues | None = Field(default=None, description="Container and PVC limits that differ from the custom tier, custom tier only. A pvc value is taken only where storageLimitRange.enabled of GET /tiers is true, and is refused with storage-limits-off elsewhere. Each key is one of `overridable` of GET /tiers, without its limitRange. prefix. A key that is left out keeps the tier's value. Each value that differs from the tier needs the beyond-tier approval", examples=[LIMIT_RANGE_EXAMPLE])
    labels: dict[str, str] = Field(default_factory=dict, description="Governed and team labels", examples=[{"cmapi.net/team": "payments"}])
    annotations: dict[str, str] = Field(default_factory=dict, description="Governed and team annotations", examples=[{"cmapi.net/team-dl": "payments-team@ephico2real.com"}])
    expires_at: date | None = Field(default=None, description="Optional expiry; never in prod", examples=["2026-12-15"])
    placement_id: str | None = Field(default=None, description="Reservation from POST /capacity:place", examples=[None])
    on_behalf_of: str | None = Field(default=None, description="Username or employee ID, for services and automation", examples=[None])
    justification: str | None = Field(default=None, description="Why the namespace is needed", examples=["Payments service dev namespace"])


class NamespacePatch(Api):
    tier: str | None = Field(default=None, description="New tier", examples=["large"])
    quota: dict[str, str] | None = Field(default=None, description="Custom quota values. On a namespace that is already on the custom tier, they are merged over its values in Git, key by key", examples=[None])
    limit_range: LimitRangeValues | None = Field(default=None, description="Custom container and PVC limits, custom tier only (a pvc value only where storageLimitRange.enabled of GET /tiers is true), merged over the namespace's values in Git, key by key. Send the tier's value to remove an override", examples=[LIMIT_RANGE_EXAMPLE])
    labels: dict[str, str | None] | None = Field(default=None, description="Merge patch; null removes a key", examples=[{"cmapi.net/cost-center": "cc-4410"}])
    annotations: dict[str, str | None] | None = Field(default=None, description="Merge patch; null removes a key", examples=[None])
    on_behalf_of: str | None = Field(default=None, description="Username or employee ID, for services and automation", examples=[None])
    justification: str | None = Field(default=None, description="Why", examples=["More capacity for the batch"])


class MetadataValue(Api):
    value: str = Field(description="The value that the namespace will carry", examples=["abc"])
    source: str = Field(description="Where it came from: request (the body sent it); namespace, environment, cluster or "
                                    "instance (cmapi filled it in from the request's target, value.from of "
                                    "metadata-keys.yaml); or default:<key> (copied from that key, default.from)",
                        examples=["request"])


class PlanMetadata(Api):
    namespace: str = Field(description="The namespace name", examples=["abc-payments-dev"])
    labels: dict[str, MetadataValue] = Field(description="Each label that the request sets or that cmapi fills in, with "
                                                         "its source. cmapi's own system labels are not listed",
                                             examples=[{"cmapi.net/team": {"value": "payments", "source": "request"}}])
    annotations: dict[str, MetadataValue] = Field(description="Each annotation that the request sets or that cmapi fills "
                                                              "in, with its source",
                                                  examples=[{}])


class PlanView(Api):
    changes: dict[str, str] = Field(description="Per changed file: added, changed or removed", examples=[{"clusters/CRC/namespaces/payments-dev/namespace.yaml": "added"}])
    plan_hash: str = Field(description="SHA-256 of the planned files", examples=["9f2c..."])
    etag: str | None = Field(description="Git commit the plan was made against; send it as If-Match", examples=["0a1b2c3d"])
    requester: RequesterView = Field(description="Who the request would be for")
    capacity: CapacityView = Field(description="The capacity check")
    approval: ApprovalView = Field(description="The approval that would apply")
    files: dict[str, str] = Field(description="Rendered content of each changed file", examples=[{"clusters/CRC/namespaces/payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\n..."}])
    findings: list[dict[str, Any]] = Field(default_factory=list, description="Validator warnings", examples=[[]])
    beyond_tier: BeyondTier | None = Field(default=None, description="The values beyond the tier and the approvals they add; null when the request has none")
    metadata: PlanMetadata | None = Field(default=None, description="On a create: the final labels and annotations, each "
                                                                     "with its source (#479). Null on other writes")


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
    protected: bool | None = Field(default=None, description="Whether cmapi refuses a delete request for it (422 "
                                   "namespace-protected): its labels in Git, which a delete checks, match protected.labels of "
                                   "approval-rules.yaml. Null on the list, which reads no Git", examples=[False])
    protected_by: list[str] | None = Field(default=None, description="The entries of protected.labels that its labels in Git "
                                           "match, such as cmapi.net/protected=true. Null on the list", examples=[[]])


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


# --------------------------------------------------------------------------- expirations

ExpiryState = Literal["permanent", "active", "expiring", "grace", "pending_delete"]


class ExpirationRow(Api):
    name: str = Field(description="Namespace", examples=["sprint-dev"])
    cluster_id: str = Field(description="Cluster", examples=["CRC"])
    env: str | None = Field(description="Environment (`cmapi.net/env`)", examples=["dev"])
    team: str | None = Field(description="Team (`cmapi.net/team`)", examples=["payments"])
    app: str | None = Field(default=None, description="`cmapi.net/app`", examples=[None])
    created: date | None = Field(description="The day the namespace was created on the cluster (its creationTimestamp), UTC",
                                 examples=["2026-10-01"])
    expires_at: str | None = Field(description="`cmapi.net/expires-at` as the cluster has it; null for a permanent namespace",
                                   examples=["2026-12-15"])
    days_left: int | None = Field(description="Days from `today` of the page to the expiry date: 0 on the date, negative after it; "
                                              "null when the namespace is permanent", examples=[29])
    state: ExpiryState = Field(description="`permanent` (no date), `active` (further away than the first notice), `expiring` "
                                           "(within the first notice, before the date), `grace` (from the date for graceDays; it still "
                                           "runs and can be extended) or `pending_delete` (grace is over)", examples=["active"])
    grace_ends: date | None = Field(description="The first day after grace: from this day the namespace is `pending_delete`. "
                                                "Null when it is permanent", examples=["2026-12-22"])
    lifetime_days: int | None = Field(description="Days from `created` to the expiry date; null when either is not known",
                                      examples=[75])
    notices_sent: int = Field(description="The expiry notices recorded for this date (of 14, 7 and 1 days before), from the "
                                          "database", examples=[0])
    open_request: str | None = Field(default=None, description="The request that holds the namespace; while it is open, another "
                                                               "change is refused with 409 change-pending", examples=[None])
    actions: list[Literal["extend", "set", "makePermanent"]] = Field(
        description="The expiry writes this namespace takes (#479): `extend` and `makePermanent` with a date, `set` without one. "
                    "Where expiration is off in its environment, only `makePermanent`, for a date kept from before",
        examples=[["extend", "makePermanent"]])


class ExpirationRulesView(Api):
    max_extension_days: int = Field(description="The most days that one extension adds, and how far out a first date can be set",
                                    examples=[30])
    max_lifetime_days: int = Field(description="Days from creation past which a date adds an approval from approver-platform",
                                   examples=[180])
    notify_days_before: list[int] = Field(description="When the notices go out, in days before the date", examples=[[14, 7, 1]])
    grace_days: int = Field(description="Days from the date during which the namespace still runs", examples=[7])


class ExpirationPage(Api):
    items: list[ExpirationRow] = Field(description="One page")
    page: PageInfo = Field(description="Paging")
    letters: dict[str, int] = Field(description="Rows per first letter", examples=[{"S": 1}])
    facets: dict[str, int] = Field(description="Rows in each state, and `attention` (expiring, grace and pending_delete), over the "
                                               "other filters", examples=[{"attention": 0, "active": 1, "permanent": 2}])
    rules: dict[str, ExpirationRulesView] = Field(description="The expiration rules of each environment in the caller's scope where "
                                                              "a namespace can expire (config/expiration.yaml). Empty on an instance "
                                                              "where none can, such as prod")
    today: date = Field(description="The day that `daysLeft` and `state` are counted from: the day the API plans an extension from",
                        examples=["2026-11-16"])


# --------------------------------------------------------------------------- policies (#302)

PolicyMode = Literal["enforce", "audit", "off"]
ReportState = Literal["ok", "loading", "not-installed", "forbidden", "not-imported", "unreachable", "stale", "capped", "drift",
                      "mode-off", "engine-off"]


class Policy(Api):
    engine: Literal["kyverno", "none"] = Field(description="The policy engine of the instance: `kyverno`, or `none`, which runs no "
                                                          "policy anywhere", examples=["kyverno"])
    kyverno_version: str | None = Field(description="The Kyverno CLI that the image pins: the least version that the clusters must "
                                                    "run. Null outside the image", examples=["v1.20.0"])
    environments: dict[str, PolicyMode] = Field(description="The mode of each served environment: `audit` (the default: admitted, "
                                                            "reported and warned), `enforce` (denied) or `off` (no policy)",
                                                examples=[{"dev": "audit", "rnd": "audit"}])


class PolicyCounts(Api):
    pass_: int = Field(alias="pass", description="Results that passed", examples=[412])
    fail: int = Field(description="Results that failed. In `audit` the resource was admitted and the failure recorded; in "
                                  "`enforce` a failure at admission was denied, and a background scan still reports one", examples=[2])
    warn: int = Field(description="Results of a policy that is not scored: Kyverno reports such a failure as warn", examples=[0])
    error: int = Field(description="Results that Kyverno could not evaluate", examples=[0])
    skip: int = Field(description="Results that did not apply", examples=[0])


class PolicyHidden(Api):
    unmanaged: int = Field(description="Results on namespaces that cmapi does not manage, and on cluster-scoped objects other than "
                                       "a Namespace: counted, never listed", examples=[1840])
    other_policies: int = Field(description="Results of policies that are not in the bundle of the cluster's environment",
                                examples=[41])
    stale: int = Field(description="Results of a bundle policy that is not on the cluster any more: Kyverno drops them at its "
                                   "next reconcile", examples=[0])


class PolicyBundleView(Api):
    expected: int = Field(description="The policies of the bundle for the cluster's environment", examples=[31])
    live: int = Field(description="Of those, the ones on the cluster", examples=[31])
    current: int = Field(description="Of those, the ones whose `cmapi.net/policy-digest` is the render's", examples=[31])
    ready: int = Field(description="Of those, the ones whose `status.conditionStatus.ready` is true", examples=[31])
    missing: list[str] = Field(description="Bundle policies that are not on the cluster (at most 20 names)", examples=[[]])
    differing: list[str] = Field(description="Bundle policies whose digest on the cluster is not the render's (at most 20)",
                                 examples=[[]])
    actions_differ: list[str] = Field(description="Rendered policies whose live `validationActions` are not those of the "
                                                  "environment's mode (at most 20)", examples=[[]])
    actions_differ_total: int = Field(description="How many rendered policies on the cluster have other `validationActions` "
                                                  "than the mode's: `actionsDiffer` names 20 at most", examples=[0])


class PolicyBundleHashes(Api):
    rendered: str | None = Field(description="Version 1 SHA-256 of the generated policies rendered for this environment. "
                                             "Null for an empty render.", examples=[None])
    live: str | None = Field(description="Version 1 SHA-256 from the generated policy digest annotations observed on this "
                                         "cluster. Null for an empty bundle or an unavailable policy list.", examples=[None])


class PolicyCluster(Api):
    cluster_id: str = Field(description="Cluster", examples=["CRC"])
    env: str = Field(description="Its environment", examples=["dev"])
    mode: PolicyMode = Field(description="The mode that instance.yaml configures for the environment", examples=["audit"])
    live_actions: list[str] = Field(description="The `validationActions` that the cluster's copies of the bundle carry: "
                                                "`Audit` and `Warn` for audit, `Deny` for enforce. Empty when none is read",
                                    examples=[["Audit", "Warn"]])
    state: ReportState = Field(description="What can be said of the cluster's reports: `ok`; `loading` (not listed yet); "
                                           "`not-installed` (discovery does not serve wgpolicyk8s.io/v1alpha2); `forbidden` "
                                           "(cmapi-reader may not list the reports or the policies); `not-imported` (clusters.yaml "
                                           "names the cluster and no import Secret does: nothing was tried); `unreachable` (the "
                                           "cluster's import is not connected: the detail names its status of GET /clusters); "
                                           "`stale` (no good read for 30 minutes: the counts are the last ones read); `capped` "
                                           "(rows past policy.reports.maxResultsPerCluster are counted and not listed); `drift` "
                                           "(the bundle on the cluster is not the render, or its actions are not the mode's); "
                                           "`mode-off` (the environment's mode is off); `engine-off` (policy.engine is none)",
                               examples=["ok"])
    state_detail: str | None = Field(description="Why, in words; null when the state is ok", examples=[None])
    as_of: datetime | None = Field(description="The last good read of the reports. For `unreachable` and `not-imported`, "
                                               "when the registry observed the current import status, or null if never imported.",
                                   examples=["2026-11-17T18:02:11Z"])
    bundle: PolicyBundleView | None = Field(description="The bundle on the cluster against the render. Null when the policies "
                                                        "are not read", examples=[None])
    hashes: PolicyBundleHashes = Field(description="The environment's rendered hash and the cluster's observed hash.")
    hash_state: Literal["current", "behind", "drift", "unknown", "off"] = Field(
        description="Current when the live hash matches the render, drift when it differs, off for an empty bundle, "
                    "unknown when the reports or live policies cannot establish the comparison. Behind means live "
                    "matches Git while the render differs. The API has no Git hash yet, so behind cannot occur.",
        examples=["current"])
    counts: PolicyCounts | None = Field(description="Results of the bundle's policies on the managed namespaces. Null, never "
                                                    "zero, when they are not known", examples=[None])
    hidden: PolicyHidden | None = Field(description="Results that are counted and not shown. Null when the counts are null",
                                        examples=[None])
    dropped: int | None = Field(description="Rows past the cap, counted in `counts` and not listed. Null when the counts are null",
                                examples=[0])


class PolicyCheck(Api):
    kind: str = Field(description="What the rendered policy checks: label, annotation, quota or limit", examples=["label"])
    key: str | None = Field(description="The key it checks; null for a rule over the keys that no stanza declares",
                            examples=["cmapi.net/team"])
    rule: str = Field(description="The rule: required, pattern, enum, max, prefix and the others of core/policygen.py",
                      examples=["pattern"])


class PolicySummary(Api):
    name: str = Field(description="The policy's name, from the bundle", examples=["cmapi-metadata-dev-label-cmapi-net-team-pattern"])
    kind: str = Field(description="Its kind", examples=["ValidatingPolicy"])
    description: str | None = Field(description="`policies.kyverno.io/description`", examples=["The labels and annotations that "
                                                                                               "metadata-keys.yaml requires"])
    check: PolicyCheck | None = Field(description="What a rendered policy checks, from the bundle's index.json; null for a "
                                                  "hand-written policy", examples=[None])
    environments: list[str] = Field(description="The environments in scope whose bundle has it", examples=[["dev"]])
    generated: bool = Field(description="True for a policy that cmapi renders from its configuration", examples=[True])
    counts: PolicyCounts | None = Field(description="Its results over the clusters in scope that run it and have counts, "
                                                    "following `clusterId`, `env` and `namespace`. Null, never zero, when no such "
                                                    "cluster has counts: Kyverno not installed, the policy not on the cluster, "
                                                    "the reports not readable or not listed yet", examples=[None])


class PolicyResource(Api):
    api_version: str = Field(description="apiVersion", examples=["v1"])
    kind: str = Field(description="Kind", examples=["Namespace"])
    name: str = Field(description="Name", examples=["orders-dev"])


class PolicyResultRow(Api):
    cluster_id: str = Field(description="Cluster", examples=["CRC"])
    env: str = Field(description="Environment", examples=["dev"])
    mode: PolicyMode = Field(description="The environment's mode: in `audit` the resource was admitted, in `enforce` an "
                                         "admission was denied", examples=["audit"])
    namespace: str = Field(description="The managed namespace: the resource's, or the Namespace itself", examples=["orders-dev"])
    resource: PolicyResource = Field(description="The resource the result is about")
    policy: str = Field(description="The policy", examples=["cmapi-metadata-dev-label-other-keys-prefix"])
    rule: str | None = Field(description="The rule: index.json's rule of a rendered policy, else Kyverno's own rule",
                             examples=["prefix"])
    kyverno_rule: str | None = Field(description="Kyverno's own rule name from the report (`validation` for a ValidatingPolicy)",
                                     examples=["validation"])
    result: Literal["fail", "warn", "error"] = Field(description="The verdict", examples=["fail"])
    message: str = Field(description="Kyverno's message, at most 300 characters",
                         examples=["the label keys other.example/x are not declared in metadata-keys.yaml"])
    process: str | None = Field(description="`admission review` or `background scan`", examples=["background scan"])
    source: str | None = Field(description="The result's source, as Kyverno writes it", examples=["KyvernoValidatingPolicy"])
    observed_at: datetime | None = Field(description="The result's timestamp", examples=["2026-11-17T17:58:40Z"])


class PolicyResultPage(Api):
    policy: Policy = Field(description="The engine, the pinned Kyverno version and each environment's mode: the `policy` object "
                                       "of GET /api/v1/admin/integrations")
    clusters: list[PolicyCluster] = Field(description="Each cluster of an environment where the caller holds objects:read")
    policies: list[PolicySummary] = Field(description="Each policy of the bundles of those environments, with its counts")
    items: list[PolicyResultRow] = Field(description="One page of fail, warn and error results on managed namespaces")
    page: PageInfo = Field(description="Paging")
    letters: dict[str, int] = Field(description="Rows per first letter of the namespace", examples=[{"O": 1}])


class RejectionFinding(Api):
    source: str = Field(description="`cmapi` (its own checks), `kyverno`, `kubeconform`, or `ci` (the Git host's CI)",
                        examples=["cmapi"])
    policy: str = Field(description="The policy or check: a Kyverno policy, `metadata-keys`, a problem code, `cmapi-check`",
                        examples=["metadata-keys"])
    rule: str | None = Field(description="The rule: the error's code for cmapi, index.json's rule of a rendered policy",
                             examples=["invalid_value"])
    kyverno_rule: str | None = Field(description="Kyverno's own rule name, for a Kyverno finding", examples=[None])
    path: str | None = Field(description="Where: `labels/<key>`, or the file of the plan", examples=["labels/cmapi.net/team"])
    severity: Literal["error", "warning"] = Field(description="`error` refused; `warning` reported only (audit)",
                                                  examples=["error"])
    message: str = Field(description="What it said, at most 300 characters", examples=["must match ^[a-z][a-z0-9-]{1,30}$"])


class Rejection(Api):
    id: str = Field(description="`rej-<n>`; never a request ID", examples=["rej-1042"])
    first_at: datetime = Field(description="When it was first refused on its UTC day: the order of the list", examples=["2026-11-17T17:02:11Z"])
    last_at: datetime = Field(description="When it was last refused that day", examples=["2026-11-17T17:05:40Z"])
    count: int = Field(description="How many times that day", examples=[2])
    stage: Literal["plan", "ci"] = Field(description="`plan` (the API's plan) or `ci` (the worker's checks of the pull request)",
                                         examples=["plan"])
    outcome: Literal["refused", "warned"] = Field(description="`refused`, or `warned`: Kyverno's findings on a plan that went on to "
                                                              "a request", examples=["refused"])
    problem: str | None = Field(description="The problem code of the 422 of a refused plan", examples=["policy-violation"])
    cluster_id: str = Field(description="Cluster", examples=["CRC"])
    env: str = Field(description="Environment", examples=["dev"])
    namespace: str = Field(description="Namespace", examples=["checkout-dev"])
    plugin: str = Field(description="Plugin", examples=["namespaces"])
    action: str = Field(description="`create`, `update`, `delete`, `expiration:extend`, `expiration:set` or "
                                    "`expiration:makePermanent`", examples=["create"])
    request_id: str | None = Field(description="The request of a warned plan or a CI refusal; null for a refused plan, which "
                                               "never became one", examples=[None])
    username: str = Field(description="Who asked: the username only, never the email, the employee ID or the justification",
                          examples=["ola"])
    automated: bool = Field(description="A service client or an automation account", examples=[False])
    findings: list[RejectionFinding] = Field(description="Each error and warning, at most 20")


class RejectionPage(Api):
    since: str = Field(description="The window asked for, in days", examples=["7d"])
    from_: datetime = Field(alias="from", description="The start of the window", examples=["2026-11-10T18:02:11Z"])
    truncated: bool = Field(description="True when the window holds more than the 10,000 newest rows that one list reads",
                            examples=[False])
    items: list[Rejection] = Field(description="One page, newest first")
    page: PageInfo = Field(description="Paging")
    letters: dict[str, int] = Field(description="Rows per first letter of the namespace", examples=[{"C": 1}])


# --------------------------------------------------------------------------- capacity (#302)

CapacityStatus = Literal["ok", "warn", "critical", "over"]
CapacityState = Literal["ok", "loading", "not-imported", "unreachable", "forbidden", "stale", "no-size"]
NodesState = Literal["ok", "loading", "forbidden", "stale", "not-imported", "unreachable"]


class CapacityResource(Api):
    unit: Literal["millicores", "bytes"] = Field(description="The unit of every amount here: `millicores` for cpu, `bytes` for "
                                                            "memory. Integers, exact", examples=["millicores"])
    simulated: int | None = Field(description="clusters.yaml `simulatedCapacity`: a configured size, not a measurement. Null "
                                              "when the cluster has none", examples=[64000])
    allocatable: int | None = Field(description="The sum of `status.allocatable` over the nodes that count (Ready, not cordoned, "
                                                "no NoSchedule or NoExecute taint outside capacity.yaml `countTaints`). Null when "
                                                "the nodes are not known", examples=[7800])
    overcommit: float = Field(description="The environment's overcommit from capacity.yaml, 1.0 when it sets none",
                              examples=[2.0])
    limit: int | None = Field(description="The size of `basis` × `overcommit`: what the managed quotas may commit. Null with no "
                                          "basis", examples=[128000])
    committed: int | None = Field(description="What cmapi's quotas commit: per managed namespace the smallest unscoped "
                                              "ResourceQuota `requests.cpu` or `cpu` (`requests.memory` or `memory`), summed. "
                                              "Null, never 0, when the quotas are not known", examples=[72000])
    quota_used: int | None = Field(description="What the pods of those namespaces request within the quotas: the binding quota's "
                                               "`status.used`, summed. Null when the quotas are not known or when any binding "
                                               "quota has not reported its use (`quotaUsedMissing`): never a partial sum",
                                   examples=[0])
    quota_used_missing: int | None = Field(description="Namespaces whose binding quota reports no `status.used` for the resource "
                                                       "yet. Null when the quotas are not known", examples=[0])
    headroom: int | None = Field(description="`limit` − `committed`; negative when the quotas commit more than the limit",
                                 examples=[56000])
    commitment: float | None = Field(description="`committed` ÷ `limit`, to 4 places; above 1 when over", examples=[0.5625])
    status: CapacityStatus | None = Field(description="Against the environment's targets: `over` above 1, `critical` or `warn` "
                                                      "at the targets, else `ok`. Null when the commitment is not known",
                                          examples=["ok"])
    requested: int | None = Field(description="The requests of every pod, from the snapshots of cmapi-capacity (#21). Null: not "
                                              "measured yet (`notMeasured`)", examples=[None])
    used_avg: int | None = Field(description="The average use over a snapshot interval (#21). Null: not measured yet",
                                 examples=[None])
    used_peak: int | None = Field(description="The peak use over a snapshot interval (#21). Null: not measured yet",
                                  examples=[None])


class CapacityNodes(Api):
    total: int = Field(description="Nodes of the cluster", examples=[1])
    counted: int = Field(description="Of those, the ones whose allocatable counts", examples=[1])
    not_ready: int = Field(description="Nodes whose Ready condition is not True", examples=[0])
    cordoned: int = Field(description="Nodes with `spec.unschedulable`", examples=[0])
    tainted: int = Field(description="Nodes with a NoSchedule or NoExecute taint outside capacity.yaml `countTaints`",
                         examples=[0])


class CapacityCluster(Api):
    cluster_id: str = Field(description="Cluster", examples=["CRC"])
    env: str = Field(description="Its environment in clusters.yaml", examples=["dev"])
    region: str | None = Field(description="Its clusters.yaml label `region`", examples=["us-central"])
    writes: bool = Field(description="clusters.yaml `writes`: a read-only cluster takes no placement and is left out of its "
                                     "group", examples=[True])
    state: CapacityState = Field(description="What can be said of its figures: `ok`; `loading` (the quotas, or the nodes of a "
                                             "cluster sized by them, are being listed); `not-imported` (clusters.yaml names the "
                                             "cluster and no import Secret does: nothing was tried); `unreachable` (the import is "
                                             "not connected: the detail names its status of GET /clusters); `forbidden` "
                                             "(cmapi-reader may not list ResourceQuotas); `stale` (no good read for 30 minutes: "
                                             "the figures are the last ones read); `no-size` (no `simulatedCapacity`, and the "
                                             "nodes' allocatable is not known)", examples=["ok"])
    state_detail: str | None = Field(description="Why, in words; null when the state is ok", examples=[None])
    as_of: datetime | None = Field(description="The last good read of the figures, to the minute. For `unreachable` and "
                                               "`not-imported`, the minute the registry observed the current import status, "
                                               "or null if never imported.",
                                   examples=["2026-11-18T09:14:00Z"])
    basis: Literal["simulated", "allocatable"] | None = Field(
        description="The size the commitment is measured against: `simulated` when clusters.yaml sets `simulatedCapacity` (what "
                    "the plan's capacity check uses until cmapi-capacity, #21), else `allocatable` from the nodes. Null when "
                    "neither is known", examples=["simulated"])
    nodes_state: NodesState = Field(description="What can be said of the nodes: `ok`; `loading`; `forbidden` (cmapi-reader may not "
                                                "list nodes); `stale`; `not-imported` and `unreachable`, as `state`",
                                    examples=["ok"])
    nodes_detail: str | None = Field(description="Why, in words; null when the nodes' state is ok", examples=[None])
    nodes: CapacityNodes | None = Field(description="The node counts. Null when the nodes are not known", examples=[None])
    zones: list[str] | None = Field(description="The distinct `topology.kubernetes.io/zone` of the nodes that count. Empty when "
                                                "they carry no zone label; null when the nodes are not known", examples=[[]])
    managed_namespaces: int | None = Field(description="Namespaces with an unscoped managed quota, which the commitment sums. "
                                                       "Null when the quotas are not known", examples=[6])
    scoped_quotas: int | None = Field(description="Managed quotas left out because they are scoped (`scopes` or "
                                                  "`scopeSelector`). Null when the quotas are not known", examples=[0])
    status: CapacityStatus | None = Field(description="The worse status of cpu and memory. Null when neither is known",
                                          examples=["ok"])
    bound_by: Literal["cpu", "memory", "both"] | None = Field(description="The resource with the higher commitment; `both` when "
                                                                          "they agree to 3 places", examples=["cpu"])
    cpu: CapacityResource = Field(description="CPU, in millicores")
    memory: CapacityResource = Field(description="Memory, in bytes")
    history: list[dict[str, Any]] | None = Field(description="The cluster's figures over time, from the snapshots of "
                                                             "cmapi-capacity (#21). Null: not measured yet", examples=[None])


class CapacityPlacement(Api):
    value: int = Field(description="The largest headroom of one included cluster, floored at 0", examples=[56000])
    cluster_id: str = Field(description="That cluster", examples=["CRC"])


class CapacityGroupResource(Api):
    unit: Literal["millicores", "bytes"] = Field(description="The unit of the amounts", examples=["millicores"])
    committed: int = Field(description="The sum over the included clusters", examples=[72000])
    limit: int = Field(description="The sum over the included clusters", examples=[128000])
    commitment: float | None = Field(description="The summed `committed` ÷ the summed `limit`, to 4 places: recomputed, never an "
                                                 "average of the clusters' ratios", examples=[0.5625])
    headroom: int = Field(description="The sum of each included cluster's headroom floored at 0: capacity does not move between "
                                      "clusters", examples=[56000])
    largest_placement: CapacityPlacement = Field(description="What one new namespace can get on one cluster of the group")


class CapacityExcluded(Api):
    cluster_id: str = Field(description="A cluster of the group left out of its figures", examples=["OCP_GF7"])
    reason: str = Field(description="Its state (`stale`, `not-imported`, `unreachable`, `loading`, `forbidden`, `no-size`), or "
                                    "`not-writable`",
                        examples=["stale"])
    as_of: datetime | None = Field(description="The excluded cluster's Capacity asOf value, to the minute",
                                   examples=["2026-11-18T08:30:00Z"])


class CapacityStatusCounts(Api):
    ok: int = Field(description="Included clusters with status ok", examples=[1])
    warn: int = Field(description="Included clusters with status warn", examples=[0])
    critical: int = Field(description="Included clusters with status critical", examples=[0])
    over: int = Field(description="Included clusters with status over", examples=[0])


class CapacityGroup(Api):
    key: dict[str, str | None] = Field(description="The value of each `groupBy` key; null when a cluster has no such label",
                                       examples=[{"region": "us-central", "environment": "dev"}])
    name: str = Field(description="The values joined with ` · `", examples=["us-central · dev"])
    cluster_ids: list[str] = Field(description="The clusters of the group in the caller's scope, by cluster ID: those of "
                                               "`clusters` that it is made of", examples=[["CRC"]])
    matching: int = Field(description="The clusters of the group in the caller's scope", examples=[1])
    included: int = Field(description="Of those, the ones in the figures: state ok and writable", examples=[1])
    coverage: float | None = Field(description="`included` ÷ `matching`", examples=[1.0])
    excluded: list[CapacityExcluded] = Field(description="Every cluster left out, with the reason")
    status: CapacityStatus | None = Field(description="The worst status of the included clusters, each against its own "
                                                      "environment's targets. Null when none is included", examples=["ok"])
    status_counts: CapacityStatusCounts = Field(description="The included clusters per status")
    bound_by: Literal["cpu", "memory", "both"] | None = Field(description="The resource with the higher group commitment",
                                                              examples=["cpu"])
    cpu: CapacityGroupResource | None = Field(description="CPU, in millicores. Null when no cluster is included",
                                              examples=[None])
    memory: CapacityGroupResource | None = Field(description="Memory, in bytes. Null when no cluster is included",
                                                 examples=[None])


class CapacityOvercommit(Api):
    cpu: float = Field(description="CPU overcommit", examples=[2.0])
    memory: float = Field(description="Memory overcommit", examples=[1.25])


class CapacityThresholds(Api):
    warn: float = Field(description="The commitment at which a cluster is `warn`", examples=[0.85])
    critical: float = Field(description="The commitment at which a cluster is `critical`", examples=[0.95])


class CapacityTarget(Api):
    env: str = Field(description="An environment where the caller holds capacity:read", examples=["dev"])
    overcommit: CapacityOvercommit = Field(description="capacity.yaml `overcommit.<env>`")
    overcommit_default: bool = Field(description="True when capacity.yaml sets no overcommit for the environment: 1.0 applies",
                                     examples=[False])
    commitment: CapacityThresholds = Field(description="capacity.yaml `targets.<env>.commitment`, 0.85 and 0.95 by default")


class CapacityPage(Api):
    source: Literal["live"] = Field(description="Where the figures come from: `live`, each cluster's watch of its quotas and "
                                                "nodes. No request calls a cluster", examples=["live"])
    snapshot_state: Literal["not-built"] = Field(description="The snapshots of cmapi-capacity (#21): `not-built` until it "
                                                             "serves them", examples=["not-built"])
    not_measured: list[str] = Field(description="The fields that are null for every cluster because only the snapshots can give "
                                                "them", examples=[["requested", "usedAvg", "usedPeak", "history"]])
    group_by: list[str] = Field(description="The keys the groups are made of", examples=[["region", "environment"]])
    hidden_clusters: int = Field(description="Clusters of environments where the caller lacks capacity:read: counted, not "
                                             "shown", examples=[0])
    targets: list[CapacityTarget] = Field(description="The overcommit and the targets of each environment in the caller's scope")
    groups: list[CapacityGroup] = Field(description="One group per combination of `groupBy` values, computed from every cluster "
                                                    "in scope")
    clusters: list[CapacityCluster] = Field(description="Every cluster in scope, by cluster ID")


class Suggestion(Api):
    name: str = Field(description="Namespace", examples=["payments-dev"])
    cluster_id: str = Field(description="Cluster", examples=["CRC"])
    why: str = Field(description="Why it matched", examples=["name starts with"])


class Suggestions(Api):
    items: list[Suggestion] = Field(description="Up to ten matches")


# --------------------------------------------------------------------------- clusters, tiers, health


class ClusterTrust(Api):
    """How cmapi verified the cluster's API server in its last check (docs/02, "TLS: one mode per cluster", #434)."""
    source: Literal["caData", "trusted", "insecure"] = Field(
        description="caData: the import Secret's CA alone. trusted: the image's system store and the bundles of "
                    "CMAPI_TRUSTED_CA_FILE (the injected bundle and an operator's). insecure: no verification, allowed by "
                    "instance.clusterTLS for the cluster's environment", examples=["trusted"])
    downgrade: bool = Field(description="True when verification is off (source insecure): a deliberate downgrade",
                            examples=[False])
    server_name: str | None = Field(description="The import Secret's tlsServerName: the name sent in SNI and checked against the "
                                                "certificate, when it is not the host of apiUrl", examples=[None])


class ClusterFinding(Api):
    finding: str = Field(description="Redacted import finding", examples=["missing field token"])
    fix: str = Field(description="Suggested corrective action", examples=["Supply the reader's token in the import Secret."])


class ClusterView(Api):
    cluster_id: str = Field(description="Cluster ID", examples=["CRC"])
    environment: str = Field(description="Environment from clusters.yaml", examples=["dev"])
    gitops_path: str = Field(description="Folder in cluster-configs", examples=["clusters/CRC"])
    writes: bool = Field(description="Whether writes are allowed", examples=[True])
    status: str = Field(description="connected, unreachable, auth_failed, not-imported, ...", examples=["connected"])
    findings: list[str] = Field(description="Import check findings", examples=[[]])
    finding_details: list[ClusterFinding] = Field(default_factory=list, description="Findings in order with a suggested fix for each")
    secret_name: str | None = Field(default=None, description="Name of the import Secret, null without a unique source")
    token_expires_at: datetime | None = Field(default=None, description="Expiry from cmapi.net/token-expires-at, when known")
    last_probe_at: datetime | None = Field(default=None, description="Last completed remote probe result, including a failed probe")
    server_version: str | None = Field(description="Kubernetes version seen", examples=["v1.35.6"])
    labels: dict[str, str] = Field(description="Metadata labels", examples=[{"region": "us-central"}])
    checked_at: datetime | None = Field(description="Last import check", examples=["2026-11-05T10:00:00Z"])
    status_since: datetime | None = Field(default=None, description="When this registry first observed the current import status. "
                                          "Null for a cluster that has never been imported.", examples=["2026-11-05T09:55:00Z"])
    trust: ClusterTrust | None = Field(default=None, description="The TLS mode of the last check; null when the import Secret was "
                                                               "refused before one was chosen, or there is none",
                                       examples=[{"source": "caData", "downgrade": False, "serverName": None}])


class ClusterList(Api):
    items: list[ClusterView] = Field(description="Every cluster this instance knows")


class Health(Api):
    status: str = Field(description="ok, or degraded when the database does not answer", examples=["ok"])
    instance: str = Field(description="Instance name", examples=["nonprod"])
    version: str = Field(description="cmapi version", examples=["0.2.0"])
    issuer: str = Field(description="OIDC issuer trusted", examples=["https://keycloak.apps-crc.testing/realms/cmapi"])
    audience: str = Field(description="Token audience required", examples=["cmapi-nonprod"])
    database: str = Field(description="ok or an error class", examples=["ok"])
    git: str = Field(description="Repository the bot writes to", examples=["cmapi/cluster-configs-nonprod"])
    clusters: dict[str, str] = Field(description="Cluster ID to import status", examples=[{"CRC": "connected"}])
    oldest_due_job_seconds: float | None = Field(default=None, description="Age of the oldest job no worker has claimed; it grows when the worker is dead. Null when the database cannot say", examples=[0.0])


class Ok(Api):
    ok: bool = Field(description="Always true", examples=[True])


class TierCatalogView(BaseModel):
    """Body of GET /tiers: the catalog as core/tiers.py describes it."""
    model_config = ConfigDict(extra="allow")
    catalog_hash: str = Field(alias="catalogHash", description="Hash of the catalog", examples=["dec3e603bf8d"])
    sizable: list[str] = Field(description="Quota keys a request may size", examples=[["requests.cpu", "requests.memory", "pods"]])
    overridable: list[str] = Field(default_factory=list, description="More keys that a custom-tier request can change: a quota key, or limitRange.<kind>.<part>.<resource>. A value that differs from the tier needs the beyond-tier approval", examples=[["requests.storage", "limitRange.container.max.cpu"]])
    environments: dict[str, Any] = Field(description="Per environment: tiers, custom bounds, and storageLimitRange.enabled: whether cmapi renders the storage LimitRange <ns>-limits-storage and takes limitRange.pvc.* values (off unless tiers.yaml turns it on)", examples=[{"dev": {"tiers": [], "custom": {}, "storageLimitRange": {"enabled": False}}}])


class MetadataKeysView(Api):
    """Body of GET /api/v1/metadata-keys (#336): this instance's metadata-keys.yaml as the JSON Schema 2020-12 of a new
    namespace's labels and annotations. Each object is the one that the API document holds at NamespaceCreate.labels and
    .annotations, without the title, description and examples that the document puts around it."""
    labels: dict[str, Any] = Field(
        description="The JSON Schema of NamespaceCreate.labels on this instance: each declared key with its rule, which keys "
                    "are required, which cmapi fills in (x-cmapi-derived-from) and which only an operator may set "
                    "(x-cmapi-operator-only)",
        examples=[{"type": "object", "properties": {"cmapi.net/team": {"type": "string", "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
                                                                       "title": "Team", "x-cmapi-rule": "must match ^[a-z0-9-]{2,40}$"}},
                   "required": ["cmapi.net/team"]}])
    annotations: dict[str, Any] = Field(
        description="The JSON Schema of NamespaceCreate.annotations on this instance, in the same form",
        examples=[{"type": "object", "properties": {"cmapi.net/team-dl": {"type": "string", "title": "Team DL",
                                                                          "x-cmapi-format": "email-in-domains"}},
                   "required": ["cmapi.net/team-dl"]}])
    expiration: dict[str, Any] = Field(
        alias="x-cmapi-expiration",
        description="NamespaceCreate.expiresAt's x-cmapi-expiration (#479): the expiration rules of each environment that "
                    "this instance serves, from expiration.yaml; {\"enabled\": false} alone where it takes no expiry",
        examples=[{"environments": {"dev": {"enabled": True, "allowedAtCreate": True, "maxLifetimeDays": 180,
                                            "notifyDaysBefore": [14, 7, 1], "graceDays": 7}, "prod": {"enabled": False}}}])


class PruneConfirm(Api):
    namespace: str = Field(description="Namespace whose delete is awaiting a prune", examples=["payments-dev"])
    cluster_id: str | None = Field(default=None, description="Cluster, when the name is ambiguous", examples=["CRC"])
