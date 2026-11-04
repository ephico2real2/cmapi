# Cluster Management API — Technical Design v2 (FastAPI)

Nov 3, 2026 · @Ola

The API is rebuilt in Python with FastAPI as a small core plus plugins; the consolidated design (Doc) is the business requirements baseline, and this doc is how we build it.

**Read this first.** The overview, system architecture, deployment instances (nonprod, staging, prod), modularity and reuse, API documentation, request lifecycle and delivery plan now live in [cmapi — Design and Architecture](01-design-and-architecture.md). This doc stays the detailed reference for fields, schemas, queries and settings. Where the two differ, Design and Architecture wins.

## Requirements baseline

Every decision in the requirements doc still stands except the stack; v2 adds the plugin model, the contract rules, observability and the pieces the earlier designs left open.

| Requirement | Source | Status in v2 |
| --- | --- | --- |
| Cluster ID on every object, format ^\[A-Z\]\[A-Z0-9\_\]{1,62}$ | Requirements doc | Kept; enforced by the ClusterScoped base model |
| Git (cluster-configs) is desired state; each cluster's ArgoCD applies its own folder | Requirements doc | Kept |
| Reads go live to the target cluster | Requirements doc | Kept; one read-only ServiceAccount per cluster |
| Database records history, never replays | Requirements doc, n8n design | Kept; tables extended (Schemas) |
| Read all RBAC, SCCs, users, groups; write only namespace SAs and their Role, ClusterRole and SCC grants | Requirements doc | Kept; one plugin per area |
| N-of-M approvals by environment, namespace pattern, size and age | n8n design | Kept; becomes a rules engine fed by YAML |
| Quota analysis against Thanos usage | n8n design | Kept; moves into the cmapi-capacity service. namespace peaks are 14-day windows read live from Thanos when a quota change is planned; cluster capacity is stored every 30 to 60 minutes for placement |
| Expiration via Kyverno TTL; API never deletes on a schedule | Flask design | Kept |
| Label and annotation validation to Kubernetes rules | n8n design, Namespace Configurator | Kept; moves into the Kyverno policy bundle |
| Self-service forms, notifications, dry-run | n8n design | Kept as portal + dry-run plans + notifier |
| Spring Boot + Fabric8 | Resource Management App | Replaced by FastAPI, Pydantic v2 and the kubernetes Python client |
| Git file format (project-meta or raw manifests) | Open | Resolved by making the renderer a plugin point; project-meta renderer first |
| Server-side dry-run vs offline validation | Open | Offline validation; see Missing pieces |
| Idempotency, concurrency, status tracking, metrics, KPIs, plugin model | Not designed | New in v2 |

## Architecture

Plugins only plan; core authenticates, locks, applies approval rules, commits to Git and tracks status, so every offering behaves the same way.

The current architecture diagram, with Keycloak, cmapi-capacity, cluster imports and the optional integrations, is in [Design and Architecture](01-design-and-architecture.md) under System architecture.

Reads skip steps 3 to 6: core authorizes the cluster scope, and the plugin reads the live cluster through core's per-cluster clients, and capacity reads are forwarded to cmapi-capacity. Each cluster's ArgoCD then applies merged changes, and the status worker records the sync.

## Plugin architecture

A new offering is one Python package that implements the Plugin contract; core discovers it at startup, mounts its routes under /api/v1/clusters/{clusterId}, and runs its writes through the shared pipeline.

**What core owns.** Authentication, cluster-scope authorization, the cluster registry, per-cluster Kubernetes clients, idempotency, per-object locks, the approval rules engine, the Git writer, the request database, the status worker, metrics and logging. Plugins never talk to Git, the database or the auth layer directly.

**What a plugin provides.** Its routes and Pydantic models, how to read its objects live, how to plan a write (validate, render the desired YAML, diff it against live), which approval facts it contributes, and the RBAC it needs on each cluster.

```python
# cmapi/core/plugin.py
from typing import Protocol
from fastapi import APIRouter

class Plugin(Protocol):
    name: str                    # "namespaces", "capacity", ...
    version: str                 # plugin semver, shown in /admin/plugins
    kinds: tuple[str, ...]       # object kinds it owns, e.g. ("Namespace",)

    def router(self) -> APIRouter: ...
    def required_rbac(self) -> list[PolicyRule]: ...      # merged into each cluster's read ClusterRole

    # Writes only; read-only plugins (rbac, identity, capacity) return None
    def planner(self) -> "Planner | None": ...

class Planner(Protocol):
    async def plan(self, req: WriteRequest, ctx: ClusterContext) -> Plan:
        """Validate, render desired YAML, diff with live, add approval facts.
        Pure: no Git, no DB, no cluster writes. Core does the rest."""
```

```python
# what core hands every plugin call
@dataclass(frozen=True)
class ClusterContext:
    cluster: ClusterConfig       # id, environment, api_url, gitops_path
    k8s: KubeClients             # read-only clients for this cluster only
    capacity: CapacityFacade     # read-only capacity and usage; only cmapi-capacity talks to Thanos
    git: GitReader               # read-only view of the cluster's folder
    caller: Caller               # identity, permissions, cluster scope
```

**Discovery.** Plugins register a Python entry point in the cmapi.plugins group, so an offering can live in its own repo and be installed with pip. Config enables them per cluster or per environment:

```toml
# pyproject.toml of a plugin package
[project.entry-points."cmapi.plugins"]
netpol = "cmapi_netpol:plugin"
```

```yaml
# config/plugins.yaml
enabled: [namespaces, quotas, limitranges, metadata, expiration,
          serviceaccounts, sa-grants, scc-grants, sa-tokens,
          rbac-read, identity-read, capacity, adoption, sync, reports]
overrides:                       # keyed by instance, then environment; checked against allowedEnvironments
  prod:
    prod:
      disabled: [sa-tokens]      # example: no self-service tokens in prod
```

**Extension points beyond plugins.** Swappable pieces inside core, each an interface with a default adapter. The full set of eleven, the shared components and how a new offering plugs in are under Modularity and reuse in Design and Architecture; the original three:

| Extension point | Default | Alternatives |
| --- | --- | --- |
| Renderer (desired state to files) | project-meta.yml renderer | Raw manifest renderer, Kustomize overlay renderer |
| Git provider | GitHub REST (rest mode) | GitLab REST, GitPython clone with HTTPS or SSH |
| Notifier | Email | Slack, Teams |

The first plugins are core-maintained; each later offering (capacity, NetworkPolicy baselines, PVC classes) is a new package with its own version, tests and RBAC declaration.

## API contract

Reads return the live object now; writes return a ChangeRequest at once (202) and finish asynchronously through Git, and every body carries clusterId.

**Documentation.** Each instance serves /docs (Swagger UI), /redoc and /openapi.json, generated from the running code by the documentation layer (core/docs.py). Routes register through DocumentedRouter, and an undocumented route or model stops startup and fails CI. Details: API documentation in [Design and Architecture](01-design-and-architecture.md).

**Conventions.**

- **Base path.** /api/v1/clusters/{clusterId}/…; the version moves to v2 only for breaking changes, with v1 kept for 6 months.
- **Docs.** Swagger UI at /docs, ReDoc at /redoc, the spec at /openapi.json. A snapshot test fails the build when the spec changes without a version note.
- **Field names.** camelCase in JSON (Pydantic aliases), snake\_case in Python.
- **Lists.** limit (default 100, max 500) and an opaque continue token; labelSelector where the cluster supports it. Envelope: {clusterId, items, continue}.
- **Time.** RFC 3339 in UTC.

**Write semantics.**

| Rule | Behaviour |
| --- | --- |
| Async | POST, PUT, PATCH and DELETE return 202 with a ChangeRequest and a Location header for GET /requests/{requestId} |
| Dry run | ?dryRun=true returns 200 with the Plan (validations, rendered YAML, diff, approval requirement, capacity check); no PR, no row |
| Idempotency | Idempotency-Key header required on writes; the same key and caller return the original ChangeRequest for 24 hours |
| Optimistic concurrency | GET returns an ETag (the Git blob SHA of the object's file); PUT, PATCH and DELETE need If-Match, else 428; a stale ETag returns 412 |
| One open change per object | A second write to an object with an open request returns 409 with a link to it |
| Patch format | application/merge-patch+json; null removes a key |

**Errors.** RFC 9457 problem details (application/problem+json), always with clusterId and requestId:

```json
{
  "type": "https://cmapi.ephico2real.com/problems/policy-violation",
  "title": "Grant not allowed",
  "status": 422,
  "detail": "ClusterRole cluster-admin is not on the ServiceAccount allowlist",
  "clusterId": "OCP_GF1",
  "requestId": "req-20261103-7f3a",
  "errors": [{"field": "roleRef.name", "code": "not_allowlisted"}]
}
```

| Problem type | Status | When |
| --- | --- | --- |
| validation-failed | 422 | Schema, name or label rules fail |
| policy-violation | 422 | Allowlist, subject rule, reserved prefix, limits below requests |
| capacity-exceeded | 422 | Requested quota does not fit the cluster's headroom (capacity check in the plan) |
| unauthenticated | 401 | No or invalid token |
| cluster-scope-forbidden | 403 | Role grants the permission, but no scope binding covers this cluster, environment or namespace |
| forbidden | 403 | No Keycloak role the caller holds grants the route's permission |
| idp-unavailable | 503 | Keycloak signing keys unreachable and no cached key matches; Retry-After set |
| operations-engine-unavailable | 503 | The configured operations engine (Argo Workflows or Tekton) is unreachable; the request path is unaffected |
| cluster-not-writable | 422 | The cluster is imported but has no clusters.yaml policy entry yet; reads work |
| environment-not-served | 422 | The environment is not in this instance's allowedEnvironments; the body carries instanceUrl and portalUrl of the instance that serves it |
| capacity-service-unavailable | 503 | cmapi-capacity cannot be reached or its circuit is open; Retry-After set. Placement and creates are unaffected |
| cluster-not-found | 404 | clusterId not in the registry |
| object-not-found | 404 | Live object missing |
| change-pending | 409 | An open request already targets this object |
| precondition-required / failed | 428 / 412 | Missing or stale If-Match |
| cluster-unreachable | 503 | Cluster API down; Retry-After set |
| git-unavailable | 502 | Git host error; the request row is marked failed |

**Endpoint catalog.** Paths are relative to /api/v1/clusters/{clusterId} unless they start with /api/v1.

| Plugin | Endpoints | Mode |
| --- | --- | --- |
| core | GET /api/v1/clusters, POST /api/v1/clusters/{id}:probe, GET /, GET /health | Read |
| core | GET /api/v1/requests/{id}, /events, GET /api/v1/requests?clusterId&status&requestedBy, POST /api/v1/requests/{id}:cancel | Database |
| core | GET /api/v1/me; GET /api/v1/admin/plugins; POST /api/v1/admin/reload; POST /api/v1/admin/clusters:propose; POST /api/v1/webhooks/git; POST /api/v1/webhooks/argocd; POST, GET /api/v1/operations, GET /api/v1/operations/{id}, POST /api/v1/operations/{id}:cancel; GET /api/v1/admin/integrations | API |
| namespaces | GET /namespaces, GET, POST, PATCH, DELETE /namespaces/{ns} | Read live; write Git |
| metadata | GET, PATCH, PUT /namespaces/{ns}/metadata; GET, PATCH, PUT /namespaces/{ns}/serviceaccounts/{sa}/metadata | Write Git |
| quotas | GET, PUT, PATCH /namespaces/{ns}/quota | Read live; write Git |
| limitranges | GET, PUT, PATCH /namespaces/{ns}/limitrange | Read live; write Git |
| expiration | GET /namespaces/{ns}/expiration, POST .../expiration:extend, POST .../expiration:makePermanent, GET /namespaces?expiring=7d or ?expired=true | Read live; write Git |
| serviceaccounts | GET, POST /namespaces/{ns}/serviceaccounts, GET, DELETE .../{sa} | Read live; write Git |
| sa-grants | GET, POST /namespaces/{ns}/serviceaccounts/{sa}/grants, DELETE .../grants/{grant} | Read live; write Git |
| scc-grants | GET, POST /namespaces/{ns}/serviceaccounts/{sa}/scc, DELETE .../scc/{scc} | Read live; write Git |
| sa-tokens | POST /namespaces/{ns}/serviceaccounts/{sa}/tokens | Direct (TokenRequest) |
| rbac-read | GET /namespaces/{ns}/roles, /rolebindings; GET /clusterroles, /clusterrolebindings; GET /sccs | Read live |
| identity-read | GET /users, /users/{name}, /users/{name}/bindings; GET /groups, /groups/{name}, /groups/{name}/bindings | Read live |
| capacity | GET /capacity, /capacity/history, /namespaces/{ns}/usage, /namespaces/{ns}/analysis, /analysis/namespaces; POST /capacity/snapshots:run, /analysis/sweeps:run (gateway to cmapi-capacity); POST /capacity:check and /api/v1/capacity:place stay in the API | Read Thanos |
| sync | GET /sync (ArgoCD Application), GET /namespaces/{ns}/drift (Git vs live) | Read live + Git |
| reports | GET /api/v1/reports/namespaces?createdSince=30d, /api/v1/reports/quota-efficiency | Database + capacity schema |

The adoption plugin adds GET /adoption/candidates, GET /adoption/skipped, POST /namespaces/{ns}:adopt and POST /adoption:scan under the cluster path, and GET /api/v1/reports/unmanaged-namespaces; details are in Adoption plugin.

## Authentication and authorization

Keycloak is the only identity provider cmapi trusts. LDAP users and groups federate into one Keycloak realm, every caller (portal, CLI, Swagger UI, pipelines) presents a Keycloak-signed JWT, and cmapi verifies it locally against the realm's published keys.

Authorization has two halves. Keycloak client roles decide what a caller may do; a scope file in Git decides where (clusters, environments, namespaces). cmapi stores no passwords and mints no tokens: the hashed automation tokens and the /admin/tokens endpoints from the earlier design are replaced by Keycloak service-account clients.

![cmapi authentication · LDAP, Keycloak, callers, four checks](diagrams/v2-authentication.png)

Every caller gets its token from Keycloak and sends it on each call; cmapi verifies it offline, checks the role, then checks a Git-managed binding before the write pipeline runs.

**How it works at runtime.** A person signs in once per session; after that every call carries a short-lived token that cmapi checks without contacting Keycloak.

1. **Sign-in.** The portal redirects to Keycloak (Authorization Code + PKCE). Keycloak checks the password by binding to LDAP as that user, imports the user on first login, and reads their cmapi-\* group memberships from LDAP.
2. **Token.** Keycloak returns a 5-minute access token and a refresh token. The access token carries the user's ID, username, email, cmapi groups and effective cmapi roles, composite roles already expanded.
3. **Call.** The portal sends the token as Authorization: Bearer. cmapi verifies the signature with its cached copy of the realm keys, builds the Principal, checks the route's permission, and checks the binding in pipeline step 2.
4. **Refresh.** About every 5 minutes the portal swaps the refresh token for a new access token. Keycloak rebuilds it from current memberships, so a person removed from an LDAP group loses the role at the next refresh, and a disabled account cannot refresh at all.
5. **Pipelines and the CLI.** Pipelines run the client-credentials flow on each job, with no LDAP involved. cmapi login runs the device flow: it prints a code, the person approves it in a browser, and the CLI keeps an offline refresh token in the OS keychain, good for 30 days idle and 90 days total.

How fast a removal takes effect depends on Keycloak's user cache as well as the token lifetime. Set the LDAP provider's cache policy to MAX\_LIFESPAN with 15 minutes, so a removed membership reaches tokens within 15 minutes plus one refresh.

A decoded access token for a person who requests for payments and approves prod:

```json
{
  "iss": "https://sso.ephico2real.com/realms/ephico2real",
  "aud": "cmapi",
  "azp": "cmapi-portal",
  "sub": "6f1c2a9e-4b7d-4e21-9c3a-0d8e5b7f2a14",
  "preferred_username": "ola",
  "email": "ola@ephico2real.com",
  "groups": ["/cmapi/cmapi-payments-requesters", "/cmapi/cmapi-prod-approvers"],
  "resource_access": {"cmapi": {"roles": ["cmapi-requester", "cmapi-approver", "cmapi-viewer"]}},
  "iat": 1793725500,
  "exp": 1793725800
}
```

With these bindings, Ola can create payments-\* namespaces on OCP\_GF1 and OCP\_GF2 and approve prod requests anywhere, but cannot create a prod namespace outside payments-\*. The requester role is only bound to payments.

![Keycloak at runtime · sign-in, call, refresh](diagrams/v2-keycloak-runtime.png)

Keycloak and LDAP are involved only at sign-in and refresh; the call itself (steps 5 to 7) never leaves cmapi.

**Sessions and token lifetimes.** cmapi keeps no session: every call stands alone on its token. What people feel as a session is how long a client can keep getting fresh 5-minute tokens without signing in again, and Keycloak controls that. Sessions are long; access tokens stay short. Every refresh rebuilds the roles from current LDAP groups, so long sessions do not slow down revocation.

| Caller | Signs in again after | Mechanism |
| --- | --- | --- |
| Portal | 8 hours idle or 12 hours total (one working day) | SSO session; silent refresh every \~5 minutes |
| Portal with Remember me ticked | 7 days idle or 30 days total | Remember-me SSO session, opt-in on the login page |
| CLI (cmapi login) | 30 days idle or 90 days total | Offline token (scope offline\_access) kept in the OS keychain; every use resets the idle clock |
| Swagger UI | 1 hour idle or 8 hours total | Client session override on cmapi-docs |
| Pipelines | No session | New client-credentials token per job |

Access tokens stay at 5 minutes for every caller. That bounds how long a removed or disabled user keeps access, because cmapi verifies tokens offline and cannot revoke one mid-flight.

**Persistence.** Keycloak 26 stores user sessions in its database by default, so sessions survive Keycloak restarts and upgrades; offline sessions were always stored there ([Keycloak blog](https://www.keycloak.org/2024/12/storing-sessions-in-kc26)). A Keycloak or cmapi rollout does not sign anyone out.

**Refresh-token rotation.** Revoke Refresh Token is on with zero reuse: each refresh returns a new refresh token and invalidates the old one, so a stolen refresh token stops working after one use by either party. The portal refreshes from one place shared by all its tabs, and the CLI saves the new refresh token after every refresh.

**What ends a session early.** Signing out of the portal; cmapi logout, which revokes the offline token; an admin signing the user out in Keycloak; or the LDAP account being disabled or removed, which makes the next refresh fail.

```yaml
# cmapi-sso/realm/ephico2real.yaml (keycloak-config-cli), session settings
realm: ephico2real
accessTokenLifespan: 300                     # 5 minutes, every client
ssoSessionIdleTimeout: 28800                 # 8 hours
ssoSessionMaxLifespan: 43200                 # 12 hours
rememberMe: true
ssoSessionIdleTimeoutRememberMe: 604800      # 7 days
ssoSessionMaxLifespanRememberMe: 2592000     # 30 days
offlineSessionIdleTimeout: 2592000           # 30 days
offlineSessionMaxLifespanEnabled: true
offlineSessionMaxLifespan: 7776000           # 90 days
revokeRefreshToken: true
refreshTokenMaxReuse: 0
clients:
  - clientId: cmapi-docs
    attributes:
      client.session.idle.timeout: "3600"    # 1 hour
      client.session.max.lifespan: "28800"   # 8 hours
  - clientId: cmapi-cli
    optionalClientScopes: [offline_access]
    attributes:
      oauth2.device.authorization.grant.enabled: "true"
```

To lengthen sessions later, change these numbers; nothing in cmapi changes. Do not lengthen the access token instead: that would delay revocation by the same amount.

**Keycloak deployment.** Red Hat build of Keycloak, installed by the Keycloak Operator on the hub cluster in namespace cmapi-sso: 2 instances, an external PostgreSQL, Route sso.ephico2real.com. Realm ephico2real; issuer https://sso.ephico2real.com/realms/ephico2real. If a corporate Keycloak or RH SSO already runs, use a dedicated realm there instead of a new instance.

**LDAP user federation.** One LDAP provider in read-only mode. Keycloak never writes to the directory and stores no password hashes; logins bind against LDAP.

| Setting | OpenLDAP / IdM value | Active Directory value | Why |
| --- | --- | --- | --- |
| Connection URL | ldaps://ldap.ephico2real.com:636 | ldaps://ad.ephico2real.com:636 | LDAPS only; the directory CA goes in the Keycloak truststore |
| Bind DN | cn=svc-keycloak,ou=service-accounts,dc=ephico2real,dc=com | CN=svc-keycloak,OU=Service Accounts,DC=ephico2real,DC=com | Read-only directory account; password in a Secret |
| Users DN | ou=people,dc=ephico2real,dc=com | OU=People,DC=ephico2real,DC=com |  |
| Edit mode | READ\_ONLY | READ\_ONLY | The directory stays the source of truth |
| Username and RDN attribute | uid | sAMAccountName (username), cn (RDN) | Becomes preferred\_username in the token |
| UUID attribute | entryUUID | objectGUID | Keeps the Keycloak user linked to the same entry across renames |
| User object classes | inetOrgPerson, organizationalPerson | person, organizationalPerson, user |  |
| Import users | On | On | Needed for group and role mappings |
| Sync periods | changed users 900 s, full 86400 s | changed users 900 s, full 86400 s | With cache policy MAX\_LIFESPAN at 15 minutes, a removed membership reaches tokens within 15 minutes plus one refresh |
| Connection pooling | On | On |  |

**Group import.** A group-ldap-mapper imports only groups whose name starts with cmapi- (LDAP filter (cn=cmapi-\*)), read-only, membership attribute member (DN), under the Keycloak group path /cmapi. Importing only these keeps tokens small and keeps unrelated directory groups out of authorization. Each Keycloak group carries a client-role mapping, so adding a person to an LDAP group is the whole onboarding step.

**Clients.** One client per kind of caller, so each has only the flow it needs and its own redirect URIs.

| Client | Type | Flow | Used by |
| --- | --- | --- | --- |
| cmapi | Confidential, all login flows off | None (resource server) | Owns the client roles; the audience every token must carry |
| cmapi-portal | Public | Authorization Code + PKCE | Namespace portal; redirect https://portal.ephico2real.com/\* |
| cmapi-docs | Public | Authorization Code + PKCE | Swagger UI; redirect https://cmapi.ephico2real.com/docs/oauth2-redirect |
| cmapi-cli | Public | Device Authorization Grant | Generated CLI: cmapi login |
| svc-{team}-{purpose} | Confidential, service account on, standard flow off | Client Credentials | One per pipeline or automation |

A client scope cmapi-audience holds an Audience mapper (aud: cmapi-\<instance>; each instance, nonprod, staging and prod, has its own resource, portal and docs clients, so a token for one is refused by the others), a Group Membership mapper (claim groups, full path) and the default client-roles mapper (resource\_access.cmapi.roles). It is a default scope only on the clients above, so a token minted for another app in the realm is refused by cmapi. Access tokens live 5 minutes; session lengths per caller are under Sessions and token lifetimes below. Service accounts get no refresh token and simply request a new access token.

**Roles and permissions.** Keycloak holds six client roles on cmapi. cmapi maps each role to fine-grained permissions in core/authz.py, and every route declares the one permission it needs.

| Role | Adds these permissions | Includes | Typical LDAP group |
| --- | --- | --- | --- |
| cmapi-viewer | clusters:read, objects:read, capacity:read, requests:read | — | cmapi-{team}-viewers |
| cmapi-requester | namespaces:write, quotas:write, serviceaccounts:write, grants:write, requests:cancel (own requests) | viewer | cmapi-{team}-requesters |
| cmapi-approver | requests:approve | viewer | cmapi-prod-approvers, cmapi-platform-leads |
| cmapi-operator | requests:retry, requests:cancel (any request), adoption:write, reports:read | requester | cmapi-platform-operators |
| cmapi-admin | config:write, clusters:onboard, admin:reload | operator | cmapi-platform-admins |
| cmapi-auditor | events:read, audit:export | viewer | cmapi-auditors |

Approver deliberately does not include requester. One person can hold both through two groups, and the self-approval rule still excludes them on their own requests.

**Scope bindings.** A binding pairs one role with one scope, like a Kubernetes RoleBinding. A request passes only when some binding matches the caller, the caller still holds that binding's role in the token, the role grants the permission, and the target falls inside that binding's scope. Pairing role with scope matters: with a flat union, someone who requests for payments and approves prod would gain request rights on every prod namespace.

Bindings live in config/authz-scopes.yaml, versioned in Git and mounted from a ConfigMap like adoption.yaml, so a scope change is a reviewed PR. A subject is a Keycloak group path or a service-account client ID. Patterns use shell-style wildcards; environment is the one the planner resolves for the target (the namespace's env, else the cluster's registry environment).

```yaml
# config/authz-scopes.yaml
bindings:
  - group: /cmapi/cmapi-payments-requesters
    role: cmapi-requester
    team: payments                 # value allowed in cmapi.net/team
    clusters: [OCP_GF1, OCP_GF2]
    environments: [rnd, dev, prod]
    namespaces: ["payments-*"]
  - group: /cmapi/cmapi-payments-viewers
    role: cmapi-viewer
    clusters: [OCP_GF1, OCP_GF2]
    environments: ["*"]
    namespaces: ["payments-*"]
  - group: /cmapi/cmapi-prod-approvers
    role: cmapi-approver
    clusters: ["*"]
    environments: [prod]
    namespaces: ["*"]
  - group: /cmapi/cmapi-platform-operators
    role: cmapi-operator
    clusters: ["*"]
    environments: ["*"]
    namespaces: ["*"]
  - client: svc-payments-ci
    role: cmapi-requester
    clusters: [OCP_GF1]
    environments: [rnd, dev]
    namespaces: ["payments-*"]
```

Cluster-scoped reads (ClusterRoles, ClusterRoleBindings, SCCs, users, groups) need a binding whose namespaces is "\*". List endpoints return only the items inside the caller's scope rather than failing.

**Token verification.** core/auth.py checks every bearer token locally, with no call to Keycloak per request. It checks the RS256 signature against the realm JWKS (cached 10 minutes, refetched once on an unknown kid, so key rotation needs no restart), plus iss, aud = cmapi, and exp/nbf with 30 s leeway. The algorithm list is pinned, so none and HS256 tokens are refused. The 5-minute token lifetime bounds how long a disabled user keeps access.

```python
# cmapi/core/auth.py  (PyJWT >= 2.8, pydantic-settings)
from functools import lru_cache
from typing import Literal

import jwt
from fastapi import Depends
from fastapi.security import OAuth2AuthorizationCodeBearer
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from cmapi.core.errors import Problem


class OIDCSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CMAPI_OIDC_")
    issuer: str = "https://sso.ephico2real.com/realms/ephico2real"
    audience: str = "cmapi"
    leeway_seconds: int = 30


@lru_cache
def settings() -> OIDCSettings:
    return OIDCSettings()


@lru_cache
def jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{settings().issuer}/protocol/openid-connect/certs",
                           cache_keys=True, lifespan=600, timeout=5)


# Reads the Authorization: Bearer header for every caller; also drives Swagger's Authorize button
oauth2 = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{settings().issuer}/protocol/openid-connect/auth",
    tokenUrl=f"{settings().issuer}/protocol/openid-connect/token",
    auto_error=False,
)


class Principal(BaseModel):
    sub: str                      # Keycloak user ID, stable across LDAP renames
    username: str                 # preferred_username, or the client ID for a service account
    email: str | None
    kind: Literal["user", "service"]
    client_id: str                # azp: cmapi-portal, cmapi-cli, svc-...
    roles: frozenset[str]
    groups: frozenset[str]


def authenticate(token: str | None = Depends(oauth2)) -> Principal:
    if not token:
        raise Problem.unauthenticated("Bearer token required")
    s = settings()
    try:
        key = jwks().get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"],
                            audience=s.audience, issuer=s.issuer, leeway=s.leeway_seconds,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWKClientConnectionError as exc:
        raise Problem.idp_unavailable("Cannot fetch Keycloak signing keys") from exc
    except jwt.PyJWTError as exc:
        raise Problem.unauthenticated("Invalid or expired token") from exc

    username = claims.get("preferred_username", claims["sub"])
    service = username.startswith("service-account-")
    return Principal(
        sub=claims["sub"],
        username=username.removeprefix("service-account-"),
        email=claims.get("email"),
        kind="service" if service else "user",
        client_id=claims.get("azp", ""),
        roles=frozenset(claims.get("resource_access", {}).get(s.audience, {}).get("roles", [])),
        groups=frozenset(claims.get("groups", [])),
    )
```

**Authorization.** require() guards the route by role; authorize\_target() runs as pipeline step 2, once the planner has resolved the target's environment.

```python
# cmapi/core/authz.py
from fnmatch import fnmatchcase

from fastapi import Depends
from pydantic import BaseModel

from cmapi.core.auth import Principal, authenticate
from cmapi.core.errors import Problem

_VIEW = {"clusters:read", "objects:read", "capacity:read", "requests:read"}
_REQUEST = _VIEW | {"namespaces:write", "quotas:write", "serviceaccounts:write",
                    "grants:write", "requests:cancel"}
_OPERATE = _REQUEST | {"requests:retry", "adoption:write", "reports:read"}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "cmapi-viewer": frozenset(_VIEW),
    "cmapi-requester": frozenset(_REQUEST),
    "cmapi-approver": frozenset(_VIEW | {"requests:approve"}),
    "cmapi-operator": frozenset(_OPERATE),
    "cmapi-admin": frozenset(_OPERATE | {"config:write", "clusters:onboard", "admin:reload"}),
    "cmapi-auditor": frozenset(_VIEW | {"events:read", "audit:export"}),
}


class Binding(BaseModel):
    group: str | None = None       # Keycloak group path
    client: str | None = None      # service-account client ID
    team: str | None = None        # team slug this binding may set in cmapi.net/team
    role: str
    clusters: list[str]
    environments: list[str]
    namespaces: list[str]

    def applies_to(self, p: Principal) -> bool:
        if self.role not in p.roles:
            return False
        return self.group in p.groups or (p.kind == "service" and self.client == p.client_id)

    def covers(self, cluster_id: str, env: str, namespace: str | None) -> bool:
        def hit(value: str, patterns: list[str]) -> bool:
            return any(fnmatchcase(value, pattern) for pattern in patterns)
        ns_ok = "*" in self.namespaces if namespace is None else hit(namespace, self.namespaces)
        return hit(cluster_id, self.clusters) and hit(env, self.environments) and ns_ok


def permissions(p: Principal) -> frozenset[str]:
    return frozenset().union(*(ROLE_PERMISSIONS.get(r, frozenset()) for r in p.roles))


def require(permission: str):
    """Route dependency: some role the caller holds grants this permission."""
    def check(p: Principal = Depends(authenticate)) -> Principal:
        if permission not in permissions(p):
            raise Problem.forbidden(f"Missing permission {permission}")
        return p
    return check


def authorize_target(p: Principal, permission: str, bindings: list[Binding],
                     cluster_id: str, env: str, namespace: str | None) -> None:
    """Pipeline step 2: one binding pairs a held role, this permission and this target."""
    for b in bindings:
        if (b.applies_to(p) and permission in ROLE_PERMISSIONS.get(b.role, frozenset())
                and b.covers(cluster_id, env, namespace)):
            return
    raise Problem.cluster_scope_forbidden(cluster_id)
```

A route then reads: `caller: Principal = Depends(require("namespaces:write"))`. Swagger UI logs in through Keycloak with `FastAPI(swagger_ui_init_oauth={"clientId": "cmapi-docs", "usePkceWithAuthorizationCodeGrant": True, "scopes": "openid"})`.

**GET /api/v1/me.** Returns the caller's username, kind, client, roles, expanded permissions and the bindings that apply to them. The portal uses it to show only the actions a person can take, and it is the first thing to check when someone reports a 403.

**Errors.** 401 unauthenticated now carries `WWW-Authenticate: Bearer error="invalid_token"`. Two problem types are new: forbidden (403, no held role grants the permission) and idp-unavailable (503, JWKS unreachable and no cached key matches). cluster-scope-forbidden (403) now means the role is right but no binding covers the target.

**What gets recorded.** Requests and approvals are keyed to the Keycloak sub, not to a username or email that can change.

```sql
ALTER TABLE change_requests
  ADD COLUMN requester_sub     UUID         NOT NULL,  -- Keycloak user ID
  ADD COLUMN requester_kind    VARCHAR(8)   NOT NULL CHECK (requester_kind IN ('user', 'service')),
  ADD COLUMN requester_client  VARCHAR(100) NOT NULL;  -- azp of the token
ALTER TABLE approvals ADD COLUMN approver_sub UUID;

DROP INDEX uq_cr_idempotency;
CREATE UNIQUE INDEX uq_cr_idempotency ON change_requests (requester_sub, idempotency_key);
```

The cmapi.net/requested-by annotation keeps the email (the client ID for a service account), and the cmapi.net/requested-by-user label keeps preferred\_username or the client ID. Tokens are never logged; structlog records sub, username, client and kind.

**Approvals and Git identity.** The approving groups in approval-rules.yaml become Keycloak group paths (/cmapi/cmapi-prod-approvers, /cmapi/cmapi-platform-leads). The approval-count CI check stops reading group lists itself. It calls GET /api/v1/requests/{id}/approval-status as the service account svc-cmapi-ci. cmapi maps each PR reviewer's Git username to a Keycloak user, then checks group, approver role, binding scope and self-approval by sub. That mapping only works if the Git host signs in through the same realm (or the same LDAP), so Git usernames equal preferred\_username. A reviewer with no Keycloak match does not count.

**Automation clients.** Each pipeline gets its own confidential client svc-{team}-{purpose} with the service account on and every browser flow off. Its role is assigned to the service account directly, and a client: binding sets its scope. Client authentication is a signed JWT where the CI system can sign one, otherwise a client secret rotated every 90 days from the CI secret store. New clients are added through the realm repository below, not self-service.

```bash
TOKEN=$(curl -s https://sso.ephico2real.com/realms/ephico2real/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=svc-payments-ci \
  -d client_secret="$CMAPI_CLIENT_SECRET" | jq -r .access_token)
```

People use `cmapi login`, which runs the device flow and caches the refresh token for the SSO session.

**Realm as code.** The realm, clients, client scopes, roles, group-to-role mappings and the LDAP provider live in cmapi-sso/realm/ephico2real.yaml. keycloak-config-cli applies them as an ArgoCD PostSync Job, so a rebuilt Keycloak converges from Git the same way the clusters do. The operator's KeycloakRealmImport is not used for this: it only creates a realm that does not exist yet and ignores later changes. The LDAP bind password and client secrets stay in Secrets, never in the realm file.

**Metrics and alerts.**

| Metric | Labels | Alert |
| --- | --- | --- |
| cmapi\_auth\_failures\_total | reason: missing, expired, signature, audience, issuer | Over 20 a minute for 10 minutes: a misconfigured client or token abuse |
| cmapi\_authz\_denied\_total | permission, kind: role, scope | None; the Access dashboard shows top denied permissions to catch wrong group mappings |
| cmapi\_jwks\_refresh\_total | result: ok, error | Errors for 5 minutes: warning, cached keys still verify until Keycloak rotates |
| cmapi\_idp\_unavailable\_total | — | Any increase for 5 minutes: critical, callers are getting 503 |

Keycloak's own metrics (metrics-enabled) and LDAP sync errors go to the same Prometheus through a ServiceMonitor in cmapi-sso.

**Open decisions.**

- Directory type: Active Directory or OpenLDAP/IdM. It picks a column in the LDAP table above.
- Reuse an existing Keycloak or RH SSO, or run a new instance on the hub.
- Whether the Git host already signs in through this Keycloak or LDAP. PR approvals only count if it does.
- Whether OpenShift OAuth on each cluster should use the same realm, so console users and cmapi users share one identity.

## Cluster connections and auto-import

cmapi never logs in to a cluster and never creates its own access there. A separate cluster-baseline process, the one that lays down every cluster's day-one configuration, creates cmapi's ServiceAccount and bindings on each cluster and hands the connection to the hub as one labelled Secret. cmapi discovers those Secrets, checks each one, and starts reading the cluster with no manual step. Keycloak covers people and pipelines calling cmapi; this section covers cmapi calling clusters.

**What the baseline creates on every cluster.** The baseline owns these objects; cmapi only uses them.

```yaml
# Applied to every cluster by the cluster-baseline process, not by cmapi
apiVersion: v1
kind: ServiceAccount
metadata: {name: cmapi-reader, namespace: cmapi-system}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: cmapi-reader}
rules:
  - apiGroups: [""]
    resources: [namespaces, nodes, resourcequotas, limitranges, serviceaccounts]
    verbs: [get, list, watch]
  - apiGroups: [rbac.authorization.k8s.io]
    resources: [roles, rolebindings, clusterroles, clusterrolebindings]
    verbs: [get, list, watch]
  - apiGroups: [security.openshift.io]
    resources: [securitycontextconstraints]
    verbs: [get, list, watch]
  - apiGroups: [user.openshift.io]
    resources: [users, groups, identities]
    verbs: [get, list, watch]
  - apiGroups: [quota.openshift.io]
    resources: [clusterresourcequotas]
    verbs: [get, list, watch]
  - apiGroups: [redhatcop.redhat.io]
    resources: [groupsyncs, namespaceconfigs, groupconfigs]
    verbs: [get, list]
  - apiGroups: [config.openshift.io]
    resources: [oauths]
    resourceNames: [cluster]
    verbs: [get]
  - apiGroups: [argoproj.io]
    resources: [applications]
    verbs: [get, list, watch]
  - apiGroups: [route.openshift.io]
    resources: [routes]
    resourceNames: [thanos-querier]
    verbs: [get]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: cmapi-reader}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: cmapi-reader}
subjects: [{kind: ServiceAccount, name: cmapi-reader, namespace: cmapi-system}]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: cmapi-reader-monitoring}     # Thanos Querier for the capacity plugin
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: cluster-monitoring-view}
subjects: [{kind: ServiceAccount, name: cmapi-reader, namespace: cmapi-system}]
```

The ServiceAccount can read and nothing else, because every change goes through Git and ArgoCD. The one exception is the sa-tokens plugin, which issues tokens directly. Its grant (create on serviceaccounts/token) is never cluster-wide, since that would let cmapi mint a token for any ServiceAccount, including system ones. cmapi renders a RoleBinding named cmapi-token-issuer into each managed namespace's folder, so the grant exists only where cmapi manages the namespace.

**How the connection reaches the hub.** The contract is the Secret below; how it arrives is the baseline's choice:

- RHACM's ManagedServiceAccount add-on, if RHACM runs the fleet. It creates the ServiceAccount on each managed cluster and keeps a rotating token in a hub Secret named after it ([Open Cluster Management docs](https://main--open-cluster-management.netlify.app/docs/getting-started/integration/managed-serviceaccount)). A small hub-side mapping copies it into the contract shape.
- A Job on each cluster that writes the Secret through a hub ServiceAccount allowed only to create and update Secrets in cmapi-imports.
- An ExternalSecret on the hub that pulls each cluster's entry from Vault, where the cluster wrote it.

```yaml
# The import contract: one Secret per cluster, in the hub namespace cmapi-imports
apiVersion: v1
kind: Secret
metadata:
  name: cmapi-cluster-ocp-gf3              # cmapi-cluster-<clusterId lower-cased, _ as ->
  namespace: cmapi-imports
  labels:
    cmapi.net/secret-type: cluster
    cmapi.net/cluster-id: OCP_GF3
  annotations:
    cmapi.net/managed-by: cluster-baseline  # the one writer; cmapi never writes here
    cmapi.net/token-expires-at: "2026-11-10T20:05:00Z"
type: Opaque
stringData:
  apiUrl: https://api.ocp-gf3.ephico2real.com:6443
  token: <TokenRequest token for cmapi-system/cmapi-reader>
  caData: |                                # optional; omit to use the hub's trusted bundle
    -----BEGIN CERTIFICATE-----
    ...
  insecure: "false"                        # "true" is refused unless the cluster's environment allows it
```

**Tokens are bounded and rotated by the writer.** The baseline issues TokenRequest tokens with a 7-day lifetime and rewrites the Secret at 80% of that, before expiry and never as a reaction to a failure. cmapi reads the token from its informer cache every time it builds a client, so a rotation takes effect without a restart. cmapi publishes cmapi\_cluster\_token\_expiry\_seconds per cluster and alerts when a token passes 90% of its life without being replaced.

One writer per Secret is the rule: cmapi has get, list and watch on Secrets in cmapi-imports and nothing more on the hub. A cluster whose token expires shows credential-expired until the baseline writes a fresh one; cmapi has no way to log in itself.

Each instance imports only its own clusters. The baseline writes a cluster's Secret to the hub of the instance whose allowedEnvironments include that cluster's environment, and an instance refuses an entry outside its list (environment-not-served). **Connection comes from the import; policy comes from Git.** The import Secret carries only connection fields: apiUrl, token, caData and insecure. The cluster's entry in clusters.yaml carries only policy fields: environment, gitopsPath, syncSignal, writes and an optional thanosUrl override. Because the two sources hold different fields, neither can override the other.

An imported cluster with no clusters.yaml entry is read-only: reads work, and writes return 422 cluster-not-writable. The cluster-onboard operation adds that entry through a PR. The Thanos URL is read from the thanos-querier Route unless the entry overrides it.

**Cluster metadata.** Each clusters.yaml entry can classify its cluster with a region, its availability zones, a few standard fields and free-form labels. cmapi turns these into a label set per cluster. Selectors over that set let approval rules, auto-approval, scope bindings, placement, integrations and operations pick clusters by what they are instead of listing IDs.

```yaml
# config/clusters.yaml: policy and classification per cluster; connections come from imports
- clusterId: OCP_GF1
  environment: prod
  gitopsPath: clusters/OCP_GF1
  writes: true
  syncSignal: notify
  metadata:
    region: us-central
    zones: [us-central-1a, us-central-1b, us-central-1c]
    datacenter: dfw-dc2
    provider: vsphere
    labels:                          # free-form, same key and value rules as namespace labels
      business-unit: commercial
      data-classification: internal
      gpu: "false"
  placement:
    enabled: true                    # false: never chosen (draining, maintenance, full)
    maxNamespaces: 400
    overcommit: {cpu: 1.0, memory: 1.0}   # overrides the environment default
    weight: 1.0                      # 0 to 2; biases the placement score
```

**Validation.** region, datacenter and provider are DNS labels. zones is a non-empty list of unique DNS labels. labels keys and values follow the Kubernetes rules in core/metadata.py. The keys region, zone, environment, provider and datacenter are refused inside labels, so the standard fields cannot be shadowed. A bad entry fails /admin/reload and CI on the config repository, and the previous configuration stays in force.

**Checked against the cluster.** On every import check cmapi lists the cluster's nodes and reads topology.kubernetes.io/region and topology.kubernetes.io/zone. A declared zone with no schedulable worker, or a worker in an undeclared zone, raises the finding zone-mismatch on that cluster. The declared value stays in force, so a typo cannot silently move placement.

**Selectors.** A clusterSelector is a Kubernetes label selector over the cluster's label set: region, zone, environment, provider, datacenter, clusterId and every key in labels. zone holds several values, so zone In \[us-central-1a\] matches any cluster that has that zone.

```yaml
clusterSelector:
  matchLabels: {region: us-central, business-unit: commercial}
  matchExpressions:
    - {key: zone, operator: In, values: [us-central-1a, us-central-1b]}
    - {key: gpu, operator: NotIn, values: ["true"]}
```

| Used by | How |
| --- | --- |
| Scope bindings (authz-scopes.yaml) | clusterSelector in place of, or as well as, a clusters list |
| Approval rules and auto-approval | match.clusterSelector |
| Placement | Hard constraints from the request (region, zones, labels) and from the team's binding |
| Integrations | Per-selector overrides, for example syncSignal: notify for a whole region |
| Operations | Fan out by selector, for example bulk-migrate over region us-central |
| Reads and reports | GET /api/v1/clusters?labelSelector=region=us-central; region on per-cluster metrics |

The region and zones also go into capacity\_snapshots, so capacity can be reported per region and per zone.

**Discovery.** cmapi watches cmapi-imports for Secrets labelled cmapi.net/secret-type=cluster and also relists every 5 minutes, so a new or rotated Secret is picked up in seconds even if a watch event is missed. Each Secret goes through the checks in the diagram below. A Secret that fails becomes a finding on that cluster; it never stops the rest.

- A failed LIST keeps the previous set of clusters. Nothing is retired on a read error.
- Two Secrets claiming one clusterId are both refused (duplicate-cluster-id).
- A Secret that disappears retires the cluster: reads stop, and its history and requests stay.

**TLS: one mode per cluster.**

| Mode | When | On a verification failure |
| --- | --- | --- |
| caData | The Secret carries caData | Replace caData in that cluster's import Secret |
| trusted-bundle | No caData | Add the CA to the hub's injected bundle (config.openshift.io/inject-trusted-cabundle), fleet-wide |
| insecure | insecure: "true" and the environment allows it (rnd only by default) | Not applicable; shown on the cluster card and in GET /api/v1/clusters as a deliberate downgrade |

caData together with insecure: "true" is refused (insecure-with-ca), as is a caData that does not decode to a loadable PEM bundle (ca-data-invalid). A failure message always names the trust store in use and the fix for that mode.

**Client rules.** Every per-cluster call follows these:

- An apiUrl that carries userinfo is refused, because httpx would send it as Basic auth.
- The token, and its JSON-escaped forms, are redacted from every error message before it is truncated.
- Outcomes are classified by who produced the error. Transport problems this process raised are unreachable or cert-verify-failed. Anything the cluster answered is auth\_failed (401), forbidden (403) or bad-response.
- A 200 response without an items field is never read as an empty list.
- Lists always follow continue tokens.
- Each cluster has its own task and timeouts, so a cluster that drops traffic cannot stall the others.

**Diagnostics.** GET /api/v1/clusters shows, for each cluster: the source Secret, the TLS mode, when the token expires, the last probe, the status and any findings with their fix. Status is one of connected, auth\_failed, forbidden, unreachable, cert-verify-failed, credential-expired or refused.

POST /api/v1/clusters/{id}:probe (cmapi-operator) tests the credential cmapi already holds, using GET /version and then GET /apis/user.openshift.io/v1/users/\~. It changes nothing. Each finding is logged once when it appears and once when it clears, with phase, outcome, action and detail fields, so the log, the API and the cluster card use the same words.

**Onboarding becomes shorter.** The bootstrap and store-credential steps leave cluster-onboard; the baseline does that work. What remains:

1. wait-import: the import Secret appears and the cluster connects.
2. preflight: the Thanos Route answers, retention is at least 15 days, and the root Application exists and is Synced.
3. propose-registry: the clusters.yaml PR with the cluster's policy entry.
4. wait-request: the PR is approved and merged.
5. smoke-test: an rnd namespace is created, synced and deleted.

![Cluster import path · six checks, each with its refusal](diagrams/v2-cluster-import.png)

Each refusal is a finding on that cluster only; the other clusters keep being read.

**Lessons from group-sync-dashboard.** Reviewed at commit d6827c5 ([repository](https://github.com/ephico2real2/group-sync-dashboard)): its cluster-connection design docs, its credential and session docs, and gsd/kube.py, config.py, fleetlogin.py, fleetlookup.py, leader.py and api.py. The dashboard proved most of the rules above on a live lab. Its biggest cost came from logging in to remote clusters with a shared LDAP account, which cmapi avoids entirely.

| What the dashboard found | What cmapi does |
| --- | --- |
| Joining a cluster by logging in to it as one shared LDAP fleet account meant a wrong retry could lock that account, and every cluster with it. It needed a process-wide credential gate, a Lease per account, a terminal stop once the password was on the wire (a locked directory answers 500, not 401), and a daily ping. | No password logins to clusters at all. The baseline creates cmapi's ServiceAccount; cmapi only reads the imported token. |
| Polling tokens had no expiry, chosen so nothing ever had to re-authenticate with the shared account; rotation was a manual Rejoin. | Bounded TokenRequest tokens (7 days), rewritten at 80% of their life by the baseline or RHACM, with the expiry visible as a metric and an alert. |
| Every login left an OAuthAccessToken object on the remote, which needed careful revocation, and a list-and-delete sweep once removed people's own oc sessions. | Nothing to clean up: ServiceAccount tokens create no OAuthAccessToken objects. |
| Connections came from both chart values and Secrets, so precedence rules and a secret-shadows-values finding were needed. | Disjoint fields: the import Secret holds the connection, clusters.yaml holds policy. |
| Generated Secrets were only safe to delete with an exact managed-by value plus UID and resourceVersion preconditions, the way ArgoCD prunes only what it tracks. | One writer per import Secret (managed-by: cluster-baseline); cmapi is read-only on the hub. |
| Three TLS modes; naming two at once is refused; a failure names the trust store in use and the fix for that mode. | Adopted as-is (the TLS table above). |
| A remote API or proxy echoed the request, putting the bearer token into error messages that were stored and served. Truncating before redacting left half a token behind. | Redact the token and its JSON-escaped forms first, then truncate. |
| One HTTP 200 without an items field was read as "no groups", deleting 60 groups and writing 120 false removal events. | Require items on every list; otherwise the outcome is bad-response. |
| An apiUrl with userinfo made httpx replace the bearer token with Basic auth. | Refuse userinfo in apiUrl. |
| Outcomes are classified by who wrote the error, and a 403 never triggers rotation: the token is valid, the RBAC is not. | Same classification; forbidden names the missing grant. |
| The proxy's skip-auth list drifted from the app's list for six days, so a forged X-Forwarded-User on a static path was recorded as a real person. | cmapi verifies the Keycloak JWT itself and never trusts an identity header. Only /healthz, /readyz and /metrics are unauthenticated, and /metrics is on a separate port. |
| `oc auth can-i` said yes to deleting the user's own OAuth token, but the live call returned 403, because a SubjectAccessReview never sees a token's scope. Unit tests passed because they mocked the API. | Integration tests run against a real cluster and a mock OpenShift API, never only mocks. |
| Asking each remote cluster to authorize every reader (remote-sar) added a failure mode for every call it made, all failing closed to a narrowed view. | One authorization source: Keycloak roles plus scope bindings. cmapi never asks a cluster about a person. |
| Patching labels onto RBAC objects was refused by Kubernetes' privilege-escalation check (175 extra rule sets demanded to label one view binding). | cmapi never writes RBAC directly; ArgoCD applies it from Git. |
| A Secret written with oc took up to one discovery interval (300 seconds) to be noticed; one written through the app took seconds. | Watch the import namespace, with a 5-minute relist as the backstop. |
| Each finding is logged once when it appears and once when it clears, with phase, outcome, action and detail fields shared by the log, API and UI. | Adopted. |
| A leader Lease was required because the store was SQLite on a ReadWriteOnce volume. | PostgreSQL with SKIP LOCKED jobs and an advisory lock for discovery, so cmapi can run several replicas. |
| The TLS modes were proven with a three-certificate mock rig, re-runnable whenever the trust logic changes. | The same rig shape in CI: trusted, private-CA and self-signed mock API servers. |

**Reading users, groups and RBAC.** The identity-read and rbac-read plugins read OpenShift's own objects. Each cluster gets a watch-based cache with a full relist every 30 minutes; the first list is paged at 500 with continue tokens. Reads are served from the cache with asOf and cacheAge, instead of listing every binding in every namespace per call; group-sync-dashboard measured that at about 154 paged requests and had to drop to an hourly cadence. The field rules below are what group-sync-dashboard learned on a live cluster.

| Object | API | Fields read | What to get right |
| --- | --- | --- | --- |
| User | user.openshift.io/v1 users | name, fullName, identities\[\], creationTimestamp | Created at first login. An empty identities\[\] means the User was made by hand and nobody has logged in as it. Names are case-sensitive, so two Users differing only in case are two people. |
| Identity | user.openshift.io/v1 identities | providerName, providerUserName, user.name, creationTimestamp | The earliest Identity is the first login, except for mappingMethod: lookup providers, where an admin created it beforehand. An LDAP providerUserName is a base64url-encoded DN. Identities outlive removed providers, so match them against the providers the OAuth CR still configures. |
| Group | user.openshift.io/v1 groups | users (top level, not spec), the sync-provider label, the sync-time and openshift.io/ldap.uid annotations | users is null when the group is empty and can repeat a name, so de-duplicate and sort it. Match members byte-exact. Attribute a group to its GroupSync by the exact label value \<groupsync>\_\<provider>, never by prefix, which is ambiguous. |
| GroupSync | redhatcop.redhat.io/v1alpha1 groupsyncs | spec.providers\[\].name, schedule, status.lastSyncSuccessTime, conditions | The CRD may be absent, which is a normal state reported as unavailable, not as zero. ReconcileError and ReconcileSuccess both stay True forever; the current state is the newer lastTransitionTime at the current observedGeneration. |
| NamespaceConfig, GroupConfig | redhatcop.redhat.io/v1alpha1 | conditions | The same sticky conditions and the same absent-CRD rule |
| OAuth | config.openshift.io/v1 oauths/cluster | identityProviders\[\].name, ldap.url | The login-gate group sits in the LDAP URL's filter as memberOf or isMemberOf, depending on the directory; match both, case-insensitively |
| RoleBinding, ClusterRoleBinding | rbac.authorization.k8s.io/v1 | roleRef, subjects\[\], labels, annotations | Flatten to one row per subject. A ServiceAccount subject without a namespace takes the RoleBinding's own, as the authorizer does. A subject named twice (OLM does this) is one row. A User subject is a direct grant, reported as a finding because it survives offboarding. |
| SecurityContextConstraints | security.openshift.io/v1 | users, groups, priority | Access to an SCC comes through its own users and groups fields or through RBAC use on it; report both paths |
| ClusterResourceQuota | quota.openshift.io/v1 | selector, status.total | Team-level quota across namespaces; feeds usage analysis |

**Rules for every read.**

- A 403 on an optional read is reported as unavailable, distinct from an empty list, and named in the response's coverage block. It is never shown as "no users" or "no groups".
- A missing CRD is detected only from a 404 on that CRD's own path, checked at the start of the message. A 500 whose body happens to mention 404 must not read as "operator absent".
- Provenance: a binding carrying cmapi.net/managed was made through cmapi; one carrying the namespace-configuration-operator's labels was made by its templates; anything else is unmanaged. An exception is acknowledged by an annotation on the object itself (cmapi.net/unmanaged-exception), never by an allowlist inside cmapi. system: groups are left out of unmanaged findings.
- Effective access: GET /users/{name}/bindings returns direct grants, grants through each of the user's groups, and SCC access, each marked with its path. For "who can do this here" questions, cmapi can ask OpenShift's own localresourceaccessreviews rather than re-implementing RBAC. That is a query that stores nothing, and it needs an extra create grant on the review resource only. A SubjectAccessReview, if one is ever used, must carry spec.groups: it does not resolve group membership on its own.

## Schemas

Three schemas must agree: the Pydantic models that define the contract, the database that records history, and the Git layout that holds desired state; all three key on clusterId.

**Pydantic models (contract).** Every model inherits ClusterScoped, so a model without a cluster ID cannot be declared.

```python
# cmapi/core/models.py
from datetime import date, datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

ClusterId = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,62}$")]
DnsLabel  = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")]

class Api(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

class ClusterScoped(Api):
    cluster_id: ClusterId

ChangeStatus = Literal["validated", "pr_open", "approved", "rejected", "merged",
                       "synced", "failed", "cancelled", "timeout"]

class ApprovalRequirement(Api):
    rule: str                     # e.g. "prod-delete"
    required_count: int
    eligible_group: str           # Keycloak group path that may approve
    reasons: list[str]

class Plan(ClusterScoped):
    plugin: str
    kind: str
    action: Literal["create", "update", "patch", "delete"]
    namespace: DnsLabel | None
    name: str
    desired: dict | None          # rendered object; None for delete
    live: dict | None
    diff: str                     # unified diff of the Git file
    approval: ApprovalRequirement | None
    capacity: "CapacityCheck | None" = None
    warnings: list[str] = []

class ChangeRequest(ClusterScoped):
    request_id: str
    plugin: str
    kind: str
    action: str
    namespace: DnsLabel | None
    name: str
    status: ChangeStatus
    requested_by: str
    pr_url: str | None
    approval: ApprovalRequirement | None
    created_at: datetime
    links: dict[str, str]         # self, events, pr

class NamespaceCreate(ClusterScoped):
    namespace: DnsLabel
    env: DnsLabel
    tier: Literal["small", "medium", "large", "custom"] = "small"
    quota: "QuotaSpec | None" = None
    labels: dict[str, str] = {}
    annotations: dict[str, str] = {}
    ttl: date | None = None
    justification: Annotated[str, StringConstraints(min_length=10)]
```

**Database (record).** The seven tables in the requirements doc stay; v2 adds these columns and one table:

```sql
ALTER TABLE change_requests
  ADD COLUMN plugin           VARCHAR(40)  NOT NULL,
  ADD COLUMN idempotency_key  VARCHAR(100) NOT NULL,
  ADD COLUMN base_etag        CHAR(40),           -- Git blob SHA the change was planned against
  ADD COLUMN plan             JSONB        NOT NULL;  -- the Plan returned at submit time

CREATE UNIQUE INDEX uq_cr_idempotency ON change_requests (requested_by, idempotency_key);

-- At most one open request per object: the per-object lock
CREATE UNIQUE INDEX uq_cr_open_object ON change_requests (cluster_id, kind, (coalesce(namespace, '')), name)
  WHERE status IN ('validated', 'pr_open', 'approved', 'merged');

-- Work queue for the status worker (Postgres SKIP LOCKED, no extra broker)
CREATE TABLE jobs (
  job_id      BIGSERIAL   PRIMARY KEY,
  kind        VARCHAR(40) NOT NULL,   -- open_pr, sync_pr_state, watch_sync, notify, expire_check, operation_step (capacity jobs here only in embedded mode)
  request_id  VARCHAR(40) REFERENCES change_requests (request_id),
  cluster_id  VARCHAR(63) NOT NULL,
  run_after   TIMESTAMPTZ NOT NULL DEFAULT now(),
  attempts    INT         NOT NULL DEFAULT 0,
  last_error  TEXT,
  done_at     TIMESTAMPTZ
);
CREATE INDEX idx_jobs_due ON jobs (run_after) WHERE done_at IS NULL;
```

**Stored capacity.** cmapi-capacity stores cluster capacity only. Its snapshot job runs every capacity.snapshotInterval per cluster (30 minutes by default, 15 to 60 allowed). Each run writes one row for the whole cluster, one per zone and one per node role. Namespace usage is never stored per interval. When a quota change on an existing namespace is planned, that namespace's last 14 days are read live from Thanos; the daily fleet sweep is in the Usage analysis tab.

```yaml
# config/capacity.yaml
snapshotInterval: 30m        # 15m to 60m: the stored grain of cluster capacity
stepWithinInterval: 5m       # the interval's average and peak are taken over these steps
retentionMonths: 13
perZone: true                # one row per zone; zones come from the API
perRole: true                # worker, infra and master rows
storage: true                # PVC requested and used, where the CSI driver reports it
staleAfterIntervals: 2       # placement refuses a cluster whose newest complete snapshot is older
```

```sql
CREATE TABLE capacity_snapshots (
  cluster_id        VARCHAR(63) NOT NULL,
  taken_at          TIMESTAMPTZ NOT NULL,      -- end of the interval
  interval_seconds  INT         NOT NULL,      -- from capacity.yaml, e.g. 1800 or 3600
  scope             VARCHAR(80) NOT NULL,      -- cluster | zone:<name> | role:worker | role:infra | role:master
  cpu      JSONB NOT NULL,   -- capacity, allocatable, requested, limits, used_avg, used_peak,
                             -- node_used_avg, quota_committed (cores)
  memory   JSONB NOT NULL,   -- the same, in bytes
  pods     JSONB NOT NULL,   -- allocatable, running
  storage  JSONB,            -- requested, used (bytes), where reported
  nodes    JSONB NOT NULL,   -- total, schedulable, not_ready, memory_pressure, disk_pressure
  complete BOOLEAN     NOT NULL,               -- false when any query failed or warned
  PRIMARY KEY (cluster_id, taken_at, scope)
) PARTITION BY RANGE (taken_at);               -- monthly partitions, kept 13 months
```

**Git layout (desired state).** One folder per cluster; each cluster's ArgoCD root Application watches only its own folder. The project-meta renderer writes:

```
cluster-configs/
└── clusters/
    └── OCP_GF1/                                   # = gitopsPath in the registry
        ├── argocd/root-application.yaml           # bootstrap: points at this folder
        └── namespaces/
            └── payments-dev/
                ├── payments-dev-dev-project-meta.yml  # namespace, tier, quota, labels, TTL
                ├── serviceaccounts.yaml               # namespace ServiceAccounts
                └── rolebindings.yaml                  # SA grants and SCC grants
```

If your cluster-configs repo keeps the existing segment/mnemonic/clusterEnv layout, the renderer maps clusterId to that path instead; the registry's gitopsPath is the only place the mapping lives.

**Label and annotation conventions.** Every key the API writes or reads lives under cmapi.net/; only the Kyverno TTL label keeps Kyverno's own key.

| Key | Kind | Value | Set by | Used for |
| --- | --- | --- | --- | --- |
| cmapi.net/cluster-id | Label | Cluster ID, e.g. OCP\_GF1 | Renderer, on every object | Joins capacity, usage and audit data; the cluster-ID rule |
| cmapi.net/managed | Label | "true" | Renderer | Marks objects owned through Git; adoption skips them |
| cmapi.net/adopt | Label | "true" | Namespace owner or platform | Opt-in for adoption; removed when adoption completes |
| cmapi.net/protected | Label | "true" | Platform | Blocks delete through the API |
| cmapi.net/tier | Label | small, medium, large, custom | Renderer | NamespaceConfig selector for quota and limit templates |
| cmapi.net/requested-by | Annotation | Requester's email | Renderer | Reports; an email cannot be a label value |
| cmapi.net/requested-by-user | Label | Username part only, e.g. ola | Renderer | Label-selector queries by requester |
| cmapi.net/request-id | Annotation | Last change request ID | Renderer | Links a live object to its history |
| cleanup.kyverno.io/ttl | Label | Date, e.g. 2026-12-15 | Renderer, from the TTL field | Kyverno cleanup; no colons in the value |
| cmapi.net/team | Label | Team slug, e.g. payments | Caller (governed, required); must match a binding's team | Ownership, showback, label-selector queries by team |
| cmapi.net/cost-center | Label | e.g. cc-4410 | Caller (governed, optional) | Showback |
| cmapi.net/owner | Annotation | Owner's email | Caller (governed, required) | Who to contact; ownership attestation |

Label values must be 63 characters or fewer and use only letters, digits, dots, dashes and underscores, which is why the email goes in an annotation.

## Labels and annotations

Callers can set any number of labels and annotations on namespaces and service accounts, within limits, as long as they don't touch keys that cmapi, Kubernetes, OpenShift or platform controllers own. Every key belongs to exactly one ownership class, and the class decides who may set it.

| Class | Keys | Set by | Through the API |
| --- | --- | --- | --- |
| System | cmapi.net/cluster-id, managed, request-id, requested-by, requested-by-user, tier; cleanup.kyverno.io/ttl | The renderer | Refused (422 reserved\_key). Tier and TTL change through their own fields. |
| Operator only | cmapi.net/protected | cmapi-operator and above | Refused for requesters (403 forbidden) |
| Platform reserved | kubernetes.io/, \*.kubernetes.io/, k8s.io/, openshift.io/, \*.openshift.io/, argocd.argoproj.io/, \*.kyverno.io/, redhatcop.redhat.io/ | Kubernetes, OpenShift and platform controllers | Refused (422 reserved\_key) |
| Governed | cmapi.net/team (label, required), cmapi.net/cost-center (label), cmapi.net/owner (annotation, required) | The caller | Allowed; the value is checked against a pattern, and team must be one the caller is bound to |
| Team | Everything else, limited to the allowed prefixes | The caller | Allowed within the limits below |

**Key classes live in one file.** cluster-configs/policies/metadata-keys.yaml feeds the Kyverno bundle's metadata-keys policy, so the same rules run at plan time, in CI and at admission. cmapi reads the same file to label each key's class in GET responses.

```yaml
# cluster-configs/policies/metadata-keys.yaml
system: [cmapi.net/cluster-id, cmapi.net/managed, cmapi.net/request-id, cmapi.net/requested-by,
         cmapi.net/requested-by-user, cmapi.net/tier, cleanup.kyverno.io/ttl]
operatorOnly: [cmapi.net/protected]
reservedPrefixes: [kubernetes.io/, "*.kubernetes.io/", k8s.io/, openshift.io/, "*.openshift.io/",
                   argocd.argoproj.io/, "*.kyverno.io/", redhatcop.redhat.io/]
governed:
  cmapi.net/team:        {kind: label,      required: true,  pattern: "^[a-z0-9-]{2,40}$", mustMatchBinding: true}
  cmapi.net/cost-center: {kind: label,      required: false, pattern: "^cc-[0-9]{4}$"}
  cmapi.net/app:         {kind: label,      required: false, pattern: "^[a-z0-9-]{2,40}$"}   # links an app's environments
  cmapi.net/rightsizing: {kind: label,      required: false, pattern: "^(auto|manual)$"}    # opt-in to automatic rnd/qa decreases
  cmapi.net/owner:       {kind: annotation, required: true,  pattern: "^[^@\\s]+@ephico2real\\.com$"}
team:
  allowedPrefixes: ["", "*.ephico2real.com/"]   # "" allows unprefixed keys
  maxLabels: 50
  maxAnnotations: 50
  maxAnnotationValueBytes: 4096
  maxAnnotationBytesTotal: 65536
sensitiveKeys: [cmapi.net/team, network.ephico2real.com/zone]   # a change adds one platform-leads approval
```

Bindings in authz-scopes.yaml gain an optional team field, which is what mustMatchBinding checks: a payments requester can set cmapi.net/team: payments and nothing else. Operators are exempt.

**Syntax.** Pydantic checks Kubernetes syntax before policy runs. A key is an optional DNS subdomain prefix of up to 253 characters, a slash, and a name of up to 63 characters that starts and ends with a letter or digit. Label values follow the same name rule or are empty. Annotation values can be any string. cmapi's byte caps sit well under Kubernetes' 256 KiB total because every value lands in Git and in PR diffs. A secret scanner runs in CI on every PR, since annotations are readable by anyone with Git access.

```python
# cmapi/core/metadata.py
import re
from typing import Annotated, Literal

from pydantic import AfterValidator

from cmapi.core.models import Api, ClusterScoped, DnsLabel

_NAME = r"[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?"
_PREFIX = r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*"
_KEY = re.compile(rf"^(?:(?P<prefix>{_PREFIX})/)?{_NAME}$")
_LABEL_VALUE = re.compile(rf"^(?:{_NAME})?$")


def _key(k: str) -> str:
    m = _KEY.match(k)
    if not m or len(m.group("prefix") or "") > 253:
        raise ValueError(f"invalid key {k!r}")
    return k


def _label_value(v: str) -> str:
    if not _LABEL_VALUE.match(v):
        raise ValueError(f"invalid label value {v!r}")
    return v


MetaKey = Annotated[str, AfterValidator(_key)]
LabelValue = Annotated[str, AfterValidator(_label_value)]


class MetadataPatch(ClusterScoped):
    """JSON merge patch (RFC 7386): a string sets a key, null removes it, absent keys stay."""
    labels: dict[MetaKey, LabelValue | None] = {}
    annotations: dict[MetaKey, str | None] = {}


class MetadataPut(ClusterScoped):
    """Replaces every governed and team key; system keys are untouched."""
    labels: dict[MetaKey, LabelValue]
    annotations: dict[MetaKey, str]


class KeyState(Api):
    value: str
    owner: Literal["system", "operator", "governed", "team", "unmanaged"]


class MetadataView(ClusterScoped):
    namespace: DnsLabel
    etag: str
    labels: dict[str, KeyState]
    annotations: dict[str, KeyState]
```

NamespaceCreate and the service account create body type their labels and annotations fields with the same MetaKey and LabelValue.

**Endpoints.** The same four verbs exist for namespaces (/namespaces/{ns}/metadata) and service accounts (/namespaces/{ns}/serviceaccounts/{sa}/metadata).

| Call | Effect | Notes |
| --- | --- | --- |
| POST create (namespace or service account) | Sets the initial labels and annotations | Governed required keys must be present |
| GET .../metadata | Every live key with its value and class; keys on the cluster but not in Git show as unmanaged | Returns the ETag of the Git file |
| PATCH .../metadata | Merge patch: set, change or remove (null) individual keys | application/merge-patch+json; If-Match required |
| PUT .../metadata | Replaces the whole governed and team set; keys left out are removed | If-Match required |

One request changes one object. The same change across many namespaces is a bulk-migrate operation or a change set, so each object still gets its own plan, PR and audit record.

```bash
curl -s -X PATCH "$CMAPI/clusters/OCP_GF1/namespaces/payments-dev/metadata" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/merge-patch+json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'If-Match: "3c7e91ab52d0"' \
  -d '{
        "clusterId": "OCP_GF1",
        "labels": {
          "cmapi.net/cost-center": "cc-4410",
          "app.ephico2real.com/component": "api",
          "app.ephico2real.com/legacy": null
        },
        "annotations": {
          "ops.ephico2real.com/runbook": "https://wiki.ephico2real.com/payments/runbook",
          "ops.ephico2real.com/pager": "payments-oncall"
        }
      }'
```

**Plan and PR.** The Plan lists added, changed and removed keys per class. The PR body shows that table, and the approval engine receives it as facts. A change to a sensitive key adds one platform-leads approval on top of the environment rule.

**Rendering.** The renderer writes labels and annotations as sorted maps in the project-meta file, system keys first, so diffs stay stable and reviewers see only the keys that changed.

```yaml
# clusters/OCP_GF1/namespaces/payments-dev/payments-dev-dev-project-meta.yml
namespace: payments-dev
env: dev
labels:
  cmapi.net/cluster-id: OCP_GF1        # system
  cmapi.net/managed: "true"
  cmapi.net/requested-by-user: ola
  cmapi.net/tier: medium
  cleanup.kyverno.io/ttl: "2026-12-15"
  cmapi.net/cost-center: cc-4410       # governed
  cmapi.net/team: payments
  app.ephico2real.com/component: api   # team
annotations:
  cmapi.net/request-id: req-20261103-91c4
  cmapi.net/requested-by: ola@ephico2real.com
  cmapi.net/owner: ola@ephico2real.com
  ops.ephico2real.com/pager: payments-oncall
  ops.ephico2real.com/runbook: https://wiki.ephico2real.com/payments/runbook
```

**On the cluster.** ArgoCD compares only the keys in Git. Keys that controllers add later, such as OpenShift's openshift.io/sa.scc.\* annotations or the pod-security sync labels, never show as drift. Removing a key from Git removes it from the cluster. Namespace Applications use the ServerSideApply=true sync option, so field ownership is explicit when ArgoCD and a controller write to the same object. A key someone changes by hand with oc label is reverted by self-heal if it is in Git. A new key added by hand stays, and shows as unmanaged in GET and in the drift report until a request adopts it into Git.

**Adoption.** Adopting a namespace copies its existing governed and team keys into Git. Reserved and system keys stay on the cluster but out of the file. A missing required governed key blocks adoption and is listed in the unmanaged-namespaces report.

**New error codes,** all returned as policy-violation (422) with errors\[\].code set: reserved\_key, invalid\_key, invalid\_value, missing\_required\_key, team\_not\_bound, too\_many\_keys, annotations\_too\_large. operator\_only\_key returns 403 forbidden.

## Capacity plugin (API side)

The capacity plugin is the API-side gateway to cmapi-capacity and makes no Thanos call itself. It forwards scoped capacity and usage reads to the service, runs the capacity check inside every plan from stored snapshots plus the live watch cache and reservations, and owns placement. Its endpoints are listed under Capacity service and Cluster and fleet capacity below. cmapi-capacity reaches each cluster's Thanos Querier at the thanos-querier Route in openshift-monitoring, or at the optional thanosUrl override in clusters.yaml, with the cmapi-reader token bound to cluster-monitoring-view.

**Retention limit.** Platform Prometheus keeps 15 days by default, and the in-cluster Thanos Querier has no long-term store behind it, so any window over 14 days silently returns less data. The design therefore uses 7- and 14-day windows from Thanos, and builds anything longer from the stored cluster capacity snapshots. Namespace history is not stored: a quota change reads that namespace's last 14 days live from Thanos. Two alternatives, if needed later:

- **Raise retention** in cluster-monitoring-config (prometheusK8s.retention: 30d) with enough PV size on every cluster.
- **ACM Observability**, if adopted: one hub Thanos endpoint with long retention and a cluster label mapped to clusterId; the ThanosClient switches endpoint and adds the label filter, and no plugin changes.

**Snapshot job.** Each run evaluates every query at the end of the interval, with partial\_response=false and deduplication on. It queries per node, so a single set of queries gives the cluster, zone and role rows: cmapi joins each node to its zone, role and schedulable flag from the API. Average and peak are taken over the interval in 5-minute steps, so a spike between runs is kept. Committed quota comes from the API watch cache, not Thanos, because ResourceQuota status is exact. A failed or warned query marks the row incomplete; it is never written as zero.

| Measure (per node) | Query (\[iv\] is capacity.snapshotInterval) |
| --- | --- |
| Capacity and allocatable | kube\_node\_status\_capacity and kube\_node\_status\_allocatable{resource=\~"cpu\|memory\|pods"} |
| Requests and limits of live pods | sum by (node, resource) (kube\_pod\_container\_resource\_requests (or …\_limits){resource=~~"cpu\|memory"} \* on (namespace, pod) group\_left() max by (namespace, pod) (kube\_pod\_status\_phase{phase=~~"Pending\|Running"} == 1)); pending pods with no node count toward the cluster row only |
| Workload CPU, average and peak | avg\_over\_time / max\_over\_time of (sum by (node) (rate(container\_cpu\_usage\_seconds\_total{container!="", image!=""}\[5m\])))\[iv:5m\] |
| Workload memory, average and peak | avg\_over\_time / max\_over\_time of (sum by (node) (container\_memory\_working\_set\_bytes{container!="", image!=""}))\[iv:5m\] |
| Whole-node usage, including system | node-exporter: rate(node\_cpu\_seconds\_total{mode!="idle"}\[5m\]) and node\_memory\_MemTotal\_bytes − node\_memory\_MemAvailable\_bytes, averaged over \[iv:5m\] |
| Running pods | count by (node) (kube\_pod\_info \* on (namespace, pod) group\_left() (kube\_pod\_status\_phase{phase="Running"} == 1)) |
| Storage | sum(kube\_persistentvolumeclaim\_resource\_requests\_storage\_bytes) and sum(kubelet\_volume\_stats\_used\_bytes) |

Node conditions (Ready, MemoryPressure, DiskPressure) come from the API. The queries use raw metrics, not OpenShift's recording rules (cluster:capacity\_cpu\_cores:sum and the like). Recording-rule names change between releases, and cluster:capacity\_cpu\_cores:sum counts every node's raw capacity rather than schedulable worker allocatable.

**Which data answers which question.**

| Question | Data | Read when |
| --- | --- | --- |
| Can this cluster take a new namespace, or a bigger quota? | Latest complete capacity snapshot, committed quota from the API watch cache, active reservations | Every create and quota change; no Thanos call |
| Is this quota change on an existing namespace justified? | That namespace's usage now, its 7-day average, and its 14-day peak and p95 from Thanos | Once per quota-change plan, cached 10 minutes |
| How has cluster capacity trended, per zone and role? | capacity\_snapshots, 13 months | Reports, forecasting, placement backtest |
| Which namespaces waste quota across the fleet? | Daily fleet sweep, which stores verdicts only | Usage analysis tab |

**Headroom rules.**

- **Request headroom** = allocatable − requested; it shows what pods can still schedule.
- **Quota headroom** = allocatable × overcommit limit − quota committed; it decides whether a new or larger quota fits.
- **Overcommit limit** is set per environment and per resource in config. Proposed for CPU: rnd 2.0, qa 1.5, uat 1.25, prod 1.0. Memory cannot be throttled, and running out of it kills pods, so its limits are tighter: rnd 1.25, qa 1.1, uat 1.0, prod 1.0. The capacity check also returns warn when a cluster's committed memory limits exceed 1.5 × allocatable (1.2 in prod), because limits beyond what the nodes have are what turn memory pressure into OOM kills.
- **Check result.** fits when the increase is within quota headroom; warn when it leaves under 20% headroom (adds an approval reason); exceeds returns 422 capacity-exceeded, or a platform approval if the environment allows it.

**Behaviour under failure.** Namespace creation and placement never call Thanos, so a Thanos outage does not stop them. Placement only refuses a cluster whose newest complete snapshot is older than two intervals (stale-data). A quota change on an existing namespace makes one live query, with a 10-second timeout. If Thanos cannot answer, the plan carries usage: unavailable and the change needs a platform approval rather than failing.

The quota and namespace planners call capacity.check() through core, so capacity can be turned off per environment without touching them; their plans then carry capacity: null and a warning.

## Capacity service (cmapi-capacity)

All Thanos work runs in one long-lived service, cmapi-capacity, deployed as its own pods and writing its own database schema. The cmapi API and worker never call Thanos. A Thanos problem, a heavy sweep or a capacity bug stays in that pod and cannot slow requests.

**What it owns.**

| Work | When | Writes |
| --- | --- | --- |
| Cluster snapshot job | Every capacity.snapshotInterval, per cluster | capacity.capacity\_snapshots |
| Daily fleet sweep | Once a day per cluster, off-peak | capacity.analysis\_sweeps, capacity.namespace\_verdicts, capacity.recommendations |
| Live namespace usage for quota-change plans | On request from the cmapi API, cached 10 minutes | Nothing |
| Retention | Daily | Drops expired monthly partitions |

**Deployment.** Its own Deployment (2 replicas), ServiceAccount, PodDisruptionBudget, resource limits and ServiceMonitor, from the same image as cmapi with a different entrypoint (cmapi-capacity). Both replicas serve the internal read API. Scheduled jobs run on whichever replica holds a PostgreSQL advisory lock per job, so a job never runs twice. The service needs no extra cluster access: it reads the same cmapi-imports Secrets (get, list and watch) and the clusters.yaml ConfigMap, and uses each cluster's read-only cmapi-reader token for Thanos and the API.

**Database: one PostgreSQL, two schemas.** cmapi-capacity owns the capacity schema and is its only writer. The cmapi API's database role can only read it. Requests, approvals and reservations stay in the cmapi schema. Placement runs in the API, reading capacity snapshots and taking its reservation in one transaction under the cluster's advisory lock, so there is no transaction spanning two services. If the schemas ever move to separate databases, placement switches to the read API below and the one cross-schema foreign key (recommendations.request\_id) is dropped.

**Reached only through cmapi.** cmapi-capacity is an internal microservice. It has no Route, no public hostname and no authentication of its own to manage. Callers use cmapi's cluster-first paths. The cmapi API acts as the gateway: it verifies the Keycloak token, checks the role and the scope binding for that cluster and namespace, then forwards the call to the service. cmapi-capacity trusts nothing but the gateway, and makes no authorization decisions of its own.

| Public path (cmapi API) | Permission and scope check | Forwarded to cmapi-capacity |
| --- | --- | --- |
| GET /api/v1/clusters/{clusterId}/capacity | capacity:read on that cluster | GET /v1/clusters/{clusterId}/capacity: latest snapshot rows for the cluster, its zones and roles |
| GET /api/v1/clusters/{clusterId}/capacity/history?from=&to=&scope= | capacity:read on that cluster | GET /v1/clusters/{clusterId}/capacity/history |
| GET /api/v1/clusters/{clusterId}/namespaces/{ns}/usage?window=14d | capacity:read on that cluster and namespace | GET /v1/clusters/{clusterId}/namespaces/{ns}/usage: live from Thanos, cached 10 minutes |
| GET /api/v1/clusters/{clusterId}/namespaces/{ns}/analysis | capacity:read on that cluster and namespace | GET /v1/clusters/{clusterId}/namespaces/{ns}/analysis: latest verdicts and recommendation |
| GET /api/v1/clusters/{clusterId}/analysis/namespaces?verdict=&kind=&team= | capacity:read on that cluster; results filtered to the caller's namespace patterns | GET /v1/clusters/{clusterId}/analysis/namespaces with the allowed patterns as parameters |
| POST /api/v1/clusters/{clusterId}/capacity/snapshots:run and /analysis/sweeps:run | operations:run on that cluster | POST /v1/clusters/{clusterId}/snapshots:run and /sweeps:run |
| GET /api/v1/capacity and /api/v1/analysis/summary?groupBy=&clusterSelector= | capacity:read; the gateway resolves the caller's scope to explicit cluster IDs and namespace patterns | GET /v1/capacity and /v1/analysis/summary with those IDs and patterns as parameters |

What stays in the cmapi API, because it writes requests or reservations: POST /api/v1/capacity:place, the capacity check inside every plan, and recommendation apply and dismiss.

The quotas planner calls the same namespace usage operation directly, through the backend described below, with the request ID attached.

**Trust between the two, with nothing to manage.**

- **Network:** a ClusterIP Service only. A NetworkPolicy admits the cmapi API and worker pods and the monitoring namespace, and nothing else.
- **Encryption:** TLS from OpenShift's service CA. The service.beta.openshift.io/serving-cert-secret-name annotation issues and rotates the certificate, and the API trusts the injected service CA bundle.
- **Caller identity, with no secret:** the API presents its own projected ServiceAccount token, with audience cmapi-capacity and a 10-minute lifetime, rotated by the kubelet. cmapi-capacity accepts only that ServiceAccount, checked with a cached TokenReview, so a pod that slipped past the NetworkPolicy still gets 401.
- **Context, never authority:** the gateway forwards X-Request-Id and the caller's username and client for logs and audit. cmapi-capacity logs them but never authorizes from them; scope is already applied in the parameters it receives.

**One backend interface, two modes.** The API's capacity plugin calls a CapacityBackend. In remote mode the backend is an HTTP client with timeouts (10 seconds for live usage, 3 for stored reads), one retry on GET, and a circuit breaker. In embedded mode the same interface calls the package in-process. Route handlers never know which mode is running.

```python
# cmapi/plugins/capacity/router.py: the gateway route for live namespace usage
@router.get("/clusters/{cluster_id}/namespaces/{namespace}/usage")
async def namespace_usage(
    cluster_id: ClusterId,
    namespace: DnsLabel,
    window: Literal["1d", "7d", "14d"] = "14d",
    caller: Principal = Depends(require("capacity:read")),
    capacity: CapacityBackend = Depends(capacity_backend),     # remote HTTP or in-process
) -> NamespaceUsage:
    env = await resolve_environment(cluster_id, namespace)     # namespace env, else the cluster's
    authorize_target(caller, "capacity:read", bindings(), cluster_id, env, namespace)
    return await capacity.namespace_usage(cluster_id, namespace, window)
```

Errors from the service pass through unchanged as problem+json. If the service cannot be reached, or the circuit is open, the gateway returns 503 capacity-service-unavailable with Retry-After.

**Embedded or remote.** capacity.mode: remote is the production layout above. capacity.mode: embedded runs the same jobs inside the cmapi worker and the usage query in-process, for development and small installs, like the other optional integrations. The code is the same package, cmapi.capacity, in both modes.

**When it is down.**

- Placement keeps working from stored snapshots until a cluster's newest one is two intervals old; then that cluster is excluded (stale-data).
- A quota-change plan gets usage: unavailable and needs a platform approval.
- A missed daily sweep leaves the previous day's verdicts in place, marked with their date.
- CmapiCapacityServiceDown fires when no replica is ready for 5 minutes, and CmapiCapacitySnapshotStale when snapshots age past two intervals.

## Cluster and fleet capacity

Cluster capacity is a first-class resource alongside namespace usage. A cluster's view comes from its latest complete snapshot. A fleet view aggregates those views by any clusters.yaml field (environment, region, zone, datacenter, provider or label), with rules that keep the totals honest: ratios are recomputed, never averaged, and headroom never crosses cluster boundaries.

**The cluster capacity resource.** One view per cluster with three breakdowns: the whole cluster, each zone, and each node role. The cmapi gateway overlays two live figures from its own state: quota committed from the watch cache and capacity reserved by pending requests. The view is therefore current even between snapshots.

```python
# cmapi/capacity/models.py
class ResourceCapacity(Api):                 # one per resource: cpu (cores), memory (bytes), pods
    capacity: float
    allocatable: float                       # schedulable workers only, in the worker role and cluster rows
    requested: float                         # live pods' requests
    limits: float
    used_avg: float                          # over the snapshot interval
    used_peak: float
    node_used_avg: float                     # whole-node usage, including system
    quota_committed: float                   # live, from the watch cache
    reserved: float                          # live, pending requests
    overcommit: float                        # cluster override, else the environment default
    quota_headroom: float                    # allocatable × overcommit − committed − reserved
    request_headroom: float                  # allocatable − requested
    usage_headroom: float                    # allocatable − used_peak
    utilisation: float                       # used_avg ÷ allocatable
    commitment: float                        # (committed + reserved) ÷ (allocatable × overcommit)

class CapacityBlock(Api):
    cpu: ResourceCapacity
    memory: ResourceCapacity
    pods: ResourceCapacity
    storage: dict[str, float] | None = None  # requested, used, where reported
    nodes: dict[str, int]                    # total, schedulable, not_ready, memory_pressure, disk_pressure

class ClusterCapacity(ClusterScoped):
    environment: str
    region: str | None
    zones: list[str]
    labels: dict[str, str]                   # from clusters.yaml metadata
    as_of: datetime                          # end of the snapshot interval
    interval_seconds: int
    complete: bool
    stale: bool                              # older than staleAfterIntervals
    placement_enabled: bool
    cluster: CapacityBlock
    zones_capacity: dict[str, CapacityBlock] # keyed by zone
    roles: dict[str, CapacityBlock]          # worker, infra, master
    zone_failure_headroom: dict[str, float]  # cpu, memory quota headroom with the largest zone removed
    status: Literal["ok", "warn", "critical"]  # against capacity.targets for its environment
```

**Endpoints.** All are on the cmapi API, scoped like everything else, and served by cmapi-capacity behind the gateway.

| Path | Returns |
| --- | --- |
| GET /api/v1/clusters/{clusterId}/capacity | The ClusterCapacity view above |
| GET /api/v1/clusters/{clusterId}/capacity/history?from=&to=&scope=cluster\|zone:\<z>\|role:\<r>&resolution=interval\|1h\|1d | Time series of the same fields |
| GET /api/v1/capacity?groupBy=&clusterSelector=&role=worker | Fleet aggregates for the latest snapshots, one group per combination of groupBy values |
| GET /api/v1/capacity/history?groupBy=&clusterSelector=&from=&to=&resolution=1h\|1d | Fleet aggregates over time |
| GET /api/v1/capacity/forecast?groupBy=&clusterSelector= | Days until each group's commitment crosses its target, from a 90-day trend (roadmap) |

groupBy takes one or more of environment, region, zone, datacenter, provider, cluster and label:\<key>, comma-separated, for example groupBy=region,environment. role defaults to worker, the capacity workloads can actually use.

**Aggregation rules.**

| Field | Rule | Why |
| --- | --- | --- |
| capacity, allocatable, requested, limits, quota\_committed, reserved, used\_avg, node counts | Sum over the group's clusters | Additive |
| utilisation, commitment, request ratio | Recomputed from the summed numerator and denominator | An average of ratios weights a 10-node cluster the same as a 200-node one |
| quota\_headroom, usage\_headroom | Sum of each cluster's headroom, each floored at zero | Capacity cannot move between clusters, so one full cluster must not be offset by another's spare |
| largest\_placement | The largest single cluster's quota headroom in the group | What one new namespace can actually get; the sum overstates it |
| used\_peak | Upper bound: in each time bucket, the sum of cluster peaks; reported as coincident\_peak\_upper | Peaks on different clusters are rarely simultaneous, and the label says so |
| zone\_failure\_headroom | Sum of each cluster's own figure | Each cluster loses its own largest zone |
| status | The worst member status, plus counts per status | One critical cluster must stay visible inside a healthy region |

**Zones across clusters.** A zone key is region/zone, from clusters.yaml metadata, checked against node labels. Two clusters that declare the same region and zone are treated as sharing that failure domain. A groupBy=zone view therefore answers: if us-central-1a fails, which clusters lose capacity, and how much, summed across all of them.

**Freshness and alignment.**

- Every aggregate uses each cluster's latest complete snapshot. Clusters whose snapshot is stale or incomplete are left out and listed under excluded, with the reason and their asOf.
- coverage reports included clusters over matching clusters, so a partial region is never silently reported as smaller.
- Snapshot times are floored to the interval boundary, so history buckets line up across clusters. If the interval changes, history is resampled to the coarser of the two.

**Targets.** capacity.targets in capacity.yaml sets warn and critical levels per environment, for example prod: {commitment: {warn: 0.80, critical: 0.90}, utilisation: {warn: 0.70, critical: 0.85}}. Groups and clusters get a status against them. CmapiCapacityTargetBreached fires per cluster and per region when critical holds for an hour.

**Scope.** Cluster and fleet capacity need capacity:read on the cluster through any binding: the totals reveal nothing about another team's namespaces. A fleet query only aggregates clusters inside the caller's bindings, and the response says how many matching clusters were left out for scope.

```json
{
  "groupBy": ["region", "environment"], "role": "worker", "asOf": "2026-11-03T23:30:00Z",
  "groups": [
    {"region": "us-central", "environment": "prod", "clusters": 4, "coverage": 1.0, "status": "warn",
     "statusCounts": {"ok": 3, "warn": 1},
     "cpu": {"allocatable": 2304, "requested": 1480, "usedAvg": 920, "coincidentPeakUpper": 1410,
             "quotaCommitted": 1890, "reserved": 32, "commitment": 0.83, "utilisation": 0.40,
             "quotaHeadroom": 382, "largestPlacement": 148, "zoneFailureHeadroom": 96},
     "memory": {"allocatable": "9.0Ti", "commitment": 0.78, "utilisation": 0.52, "quotaHeadroom": "1.9Ti",
                "largestPlacement": "640Gi"}},
    {"region": "us-central", "environment": "rnd", "clusters": 2, "coverage": 0.5, "status": "ok",
     "excluded": [{"clusterId": "OCP_GF7", "reason": "stale-data", "asOf": "2026-11-03T21:30:00Z"}],
     "cpu": {"allocatable": 512, "commitment": 0.61, "quotaHeadroom": 410, "largestPlacement": 410}}
  ]
}
```

In the example, us-central prod has 382 cores of quota headroom in total, but no single cluster can take more than 148. That second number is the one that answers "can we place a 200-core namespace in this region?"; the answer is no without adding capacity. Aggregates are computed on read from capacity\_snapshots, with an index on (taken\_at, cluster\_id, scope). A materialised hourly rollup is an optional speed-up if fleet history queries become slow.

## Placement

Placement picks the cluster a new namespace should land on and holds its capacity until the namespace is live, so two requests can never both take the last headroom. It decides from three sources, refuses to decide on stale or partial data, and explains every cluster it ranked or excluded.

**Data sources.**

| Source | What it gives | Read when |
| --- | --- | --- |
| capacity\_snapshots | Allocatable, requests, limits, and usage average and peak, per cluster, zone and role | Written every snapshot interval; placement reads the stored rows |
| Kubernetes API watch cache (cmapi-reader) | Committed quota from ResourceQuotas; nodes, zones and schedulable flags | Kept current by watch; read at request time |
| cmapi database | Active reservations | At request time, under the cluster's lock |

Placement makes no Thanos call while a request is being planned. Thanos is read only by the snapshot job.

**Capacity model,** per cluster, per zone and per resource (cpu, memory, pods). Allocatable counts only schedulable workers without NoSchedule taints, from the API node list joined to kube\_node\_status\_allocatable.

- **Committed** is the sum of requests.\* hard quotas, plus the live requests of namespaces that have no quota.
- **Reserved** is the sum of active reservations, below.
- **Quota headroom** is allocatable × overcommit − committed − reserved, where overcommit comes from the cluster's placement block or the environment default.
- **Usage headroom** is allocatable − the 14-day p95 of real usage.
- **Zone-failure headroom** (prod only) is quota headroom computed with the largest zone removed, so a placed namespace still fits after losing a zone.

**Accuracy controls.** Each one either excludes the cluster with a named reason or makes the answer more exact.

- At snapshot time: one evaluation instant per run; partial\_response=false and deduplication on; a warned or failed query marks the row incomplete, never zero.
- At snapshot time: if Thanos allocatable and the API node sum differ by more than 5%, the row is marked incomplete (data-mismatch). This catches a scrape gap or a node that just joined.
- At request time: the newest complete snapshot must be no older than two intervals, or the cluster is excluded (stale-data).
- At request time: committed quota comes from the watch cache, so a quota merged since the last snapshot already counts.
- Quotas are parsed with Kubernetes quantity rules. Several ResourceQuotas in one namespace count at the smallest hard value, and a quota cmapi cannot parse counts at the namespace's live requests, with a warning.

**Reservations.** Placement takes a reservation inside the same transaction as the capacity check, under a per-cluster advisory lock, so concurrent requests see each other. The reservation ends when the namespace's ResourceQuota appears in cmapi's watch cache of that cluster. Committed quota counts it from then on, so it is never counted twice. It also ends when the request is rejected, cancelled or times out.

```sql
CREATE TABLE capacity_reservations (
  reservation_id  UUID          PRIMARY KEY,
  request_id      VARCHAR(40)   REFERENCES change_requests (request_id),  -- null while only placed
  cluster_id      VARCHAR(63)   NOT NULL,
  zone            VARCHAR(63),                       -- set when the request pins a zone
  cpu             NUMERIC(12,3) NOT NULL,            -- cores
  memory          BIGINT        NOT NULL,            -- bytes
  pods            INT           NOT NULL,
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
  expires_at      TIMESTAMPTZ   NOT NULL,            -- 15 minutes while placed; the approval timeout once submitted
  released_at     TIMESTAMPTZ,
  released_why    VARCHAR(20)                        -- observed, rejected, cancelled, timeout, expired
);
CREATE INDEX idx_resv_active ON capacity_reservations (cluster_id) WHERE released_at IS NULL;
```

**Hard filters.** A cluster that fails any of these is excluded, and the reason is returned:

- environment does not match
- not connected or not writable
- placement.enabled is false
- outside the requested region, zones or clusterSelector, or outside the team's scope binding
- stale or partial data
- maxNamespaces reached
- does not fit within quota headroom after reservations
- in prod, does not fit within zone-failure headroom

**Score,** 0 to 100 for clusters that pass, with weights in config/placement.yaml:

| Factor | Default weight | Measures |
| --- | --- | --- |
| Quota headroom after placement | 40 | Room left on committed capacity |
| Usage headroom (14-day p95) | 25 | Real pressure, which quota alone hides |
| Balance | 15 | Distance from the fleet's average utilisation in that environment |
| Team affinity | 10 | The team already has namespaces there; can be set negative to spread teams instead |
| Zone spread | 10 | How evenly the cluster's free capacity is spread across its zones |

The total is multiplied by the cluster's placement.weight and capped at 100. Ties go to the lower clusterId, so the same inputs always give the same answer.

**API.** POST /api/v1/capacity:place ranks the candidates and takes a 15-minute reservation on the top one. The create request then carries the placementId, which turns that reservation into the request's own. Reads need capacity:read; creating the reservation needs namespaces:write in the chosen cluster's scope.

```json
{
  "placementId": "pl-20261103-2c81",
  "asOf": "2026-11-03T23:40:00Z",
  "request": {"environment": "prod", "team": "payments", "tier": "medium",
              "cpu": 16, "memory": "32Gi", "pods": 100, "constraints": {"region": "us-central"}},
  "ranked": [
    {"clusterId": "OCP_GF1", "score": 82, "reserved": true,
     "cpu": {"quotaHeadroomBefore": 64, "quotaHeadroomAfter": 48, "zoneFailureHeadroomAfter": 21,
             "usageP95": 0.41}},
    {"clusterId": "OCP_GF2", "score": 67, "reserved": false,
     "cpu": {"quotaHeadroomBefore": 40, "quotaHeadroomAfter": 24, "zoneFailureHeadroomAfter": 3,
             "usageP95": 0.58}}
  ],
  "excluded": [
    {"clusterId": "OCP_GF4", "reason": "stale-data", "detail": "newest kube-state-metrics sample 11m old"},
    {"clusterId": "OCP_GF5", "reason": "zone-failure-headroom", "detail": "needs 16 cores, 9 left without zone c"}
  ]
}
```

**Across the namespace's life.**

| Stage | What placement does |
| --- | --- |
| Create | Place, reserve, open the PR; the reservation ends when the quota appears in the API |
| Quota or tier increase | Checks the current cluster, counting reservations. If it does not fit, it returns 422 capacity-exceeded with the clusters where it would fit, as advice; moving a namespace between clusters is a migration and is never automatic. |
| Approaching expiry | Namespaces expiring within 7 days are reported as soon-free capacity but never counted as free until deleted |
| Delete | Committed quota drops as soon as the API shows the namespace gone; usage drops in the next snapshot |
| Weekly rebalance report | Clusters above their target utilisation, with candidate namespaces to move and where |

**Measuring that it is right.** A backtest job replays 30 days of snapshots. For each placement it checks whether the chosen cluster would ever have exceeded its overcommit limit, and whether a better-scored cluster existed with the data available at the time. The target is zero overcommit breaches. CI runs placement against recorded Thanos responses (golden files) covering stale, partial and mismatched data.

**Metrics:** cmapi\_placement\_requests\_total{result}, cmapi\_placement\_excluded\_total{reason}, cmapi\_capacity\_data\_age\_seconds{cluster}, cmapi\_reservations\_active{cluster} and cmapi\_placement\_backtest\_breaches.

**Usage analysis.** Whether each namespace's quota, requests and real usage agree, the waste between them, and the rightsizing that follows are designed in their own tab: Usage analysis.

## Adoption plugin

Adoption brings existing namespaces under the API by rendering their live state into Git; it is opt-in per namespace with the label cmapi.net/adopt: "true", and exclusions from a ConfigMap always win over the label.

**Selection order.** A namespace is a candidate only if every step passes:

1. **Built-in exclusions** (code, cannot be removed): default, openshift, openshift-*, kube-*.
2. **Configured exclusions** from the ConfigMap: exact names, glob patterns and label selectors, global or per cluster and environment.
3. **Already managed:** carries cmapi.net/managed: "true" or already has a folder in Git; skipped.
4. **Opt-in label:** cmapi.net/adopt="true", found with a labelSelector on the namespace list.

Label values are strings, so the label must be quoted ("true"); an unquoted true in YAML is a boolean and the API server rejects it. A labelled namespace that matches an exclusion is reported as skipped with the rule that matched, never adopted.

**Configuration.** A ConfigMap in the API's namespace (cmapi) on the hub, mounted as a file and re-read on POST /admin/reload:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmapi-adoption
  namespace: cmapi
data:
  adoption.yaml: |
    selector:
      label: cmapi.net/adopt
      value: "true"
    exclude:                              # added to the built-in exclusions
      names: [default, openshift]
      patterns: ["openshift-*", "kube-*", "ocp-*", "kubernetes-*"]   # shell globs, lowercase
      labelSelectors:
        - openshift.io/run-level          # key present
        - openshift.io/cluster-monitoring=true
    environments:
      prod:
        patterns: ["vendor-*"]
    clusters:
      OCP_GF1:
        names: [legacy-batch]
    skip:                                 # objects inside an adopted namespace never adopted
      serviceAccounts: [default, builder, deployer, pipeline]
      roleBindings: ["system:image-pullers", "system:image-builders", "system:deployers"]
      annotationPrefixes: ["openshift.io/sa.scc.", "kubectl.kubernetes.io/"]
```

Patterns are matched with fnmatch on the full name; exclusions from global, environment and cluster scopes are combined, never subtracted, so a cluster entry can only exclude more.

**What gets adopted.**

| Object | Adopted | Notes |
| --- | --- | --- |
| Namespace | Labels and annotations, minus skip prefixes and server-set fields | Renderer adds cmapi.net/managed and cmapi.net/cluster-id; drops cmapi.net/adopt |
| ResourceQuota, LimitRange | Yes | Mapped to the nearest tier, or custom if none matches |
| ServiceAccounts | Yes, except the skip list and operator-owned ones | Owner references mark operator-owned |
| RoleBindings with a ServiceAccount subject | Yes, if the role is allowlisted | A non-allowlisted grant stays unmanaged and is listed as a finding |
| SCC grants to ServiceAccounts | Yes, if the SCC is allowlisted | Same rule |
| RoleBindings with User or Group subjects | No | Owned by the separate access process; ArgoCD does not prune objects it never tracked |

Server-set fields (uid, resourceVersion, creationTimestamp, managedFields, status) are always stripped. The openshift.io/sa.scc.\* annotations are skipped by default; keep them only if you need a rebuilt cluster to reuse the same UID ranges for existing PV data.

**Flow.**

1. **Request.** A caller asks to adopt one namespace or scans a cluster. The caller must be admin of each namespace, checked with a SubjectAccessReview on that cluster, or be a platform admin.
2. **Plan.** The plugin reads live objects, applies the skip rules and policies, and renders the files. The diff between rendered and live must be empty apart from the managed labels; anything else is a finding.
3. **PR.** One PR per namespace, labelled adoption, with the findings in the body. Approval: one namespace admin in rnd and qa, plus platform-leads in prod.
4. **Sync.** On merge, the cluster's ArgoCD takes ownership. The first sync is a no-op except for the managed labels and the removal of cmapi.net/adopt, which marks adoption done.
5. **Verify.** The worker confirms Synced and Healthy with no other changes; any unexpected diff fails the request and leaves the namespace as it was.

**Endpoints.**

- **GET /adoption/candidates.** Labelled, not excluded, not managed.
- **GET /adoption/skipped.** Labelled but excluded, with the matching rule.
- **POST /namespaces/{ns}:adopt.** Adopt one namespace; supports ?dryRun=true.
- **POST /adoption:scan.** Plan every candidate on the cluster; dryRun=true by default, so a scan never opens PRs unless asked.
- **GET /api/v1/reports/unmanaged-namespaces.** Per cluster: managed, candidates, unlabelled unmanaged, excluded. Unlabelled namespaces are reported, never adopted.

**RBAC.** The adoption plugin adds create on subjectaccessreviews (authorization.k8s.io) to each cluster's read ClusterRole, for the namespace-admin check.

## Approval rules engine

The n8n approval logic becomes one YAML file evaluated at plan time; the strictest matching rule wins, and the result rides into the PR where the Git host enforces it.

```yaml
# config/approval-rules.yaml
defaults: {required: 0, group: platform-leads, timeoutHours: 24, selfApproval: false}

environments:
  rnd:  {create: 1, change: 0, delete: 1, selfApproval: true,  timeoutHours: 8}   # create waived by baseline-rnd-namespace
  dev:  {create: 1, change: 0, delete: 1, selfApproval: true,  timeoutHours: 8}   # rnd's settings until dev's are agreed
  # each instance's file holds only its allowedEnvironments: nonprod rnd, dev; staging qa, uat; prod prod
  qa:   {create: 1, change: 1, delete: 1, group: qa-leads,     timeoutHours: 24}
  uat:  {create: 1, change: 1, delete: 1, group: uat-leads,    timeoutHours: 24}
  prod: {create: 1, change: 1, delete: 2, group: prod-approvers, timeoutHours: 48}

namespacePatterns:              # first match wins; can raise or waive
  - match: "critical-*"
    required: 2
    group: platform-leads
    reason: Critical namespace pattern
  - match: "temp-*"
    waive: [create, change]
    reason: Temporary namespace

thresholds:                     # facts come from the planner and the capacity plugin
  - when: quotaIncreasePct > 100
    add: 1
    group: platform-leads
  - when: requestToPeakRatio > 3   # namespace peak over 14 days, read live when the change is planned
    add: 1
    reason: Possible over-provisioning
  - when: capacity == "warn"
    add: 1
  - when: action == "delete" and (namespaceAgeDays > 90 or pods > 20 or pvcs > 10)
    add: 1

protected:                      # never deletable through the API
  labels: ["cmapi.net/protected=true", "do-not-delete=true"]
```

**How it runs.**

1. The planner returns facts (action, environment, namespace age, quota increase, usage ratios, capacity result).
2. The engine applies environment, then pattern, then thresholds, then any auto-approval policy and its guards, and returns an ApprovalRequirement: rule name, required count, approving group and every reason.
3. Core writes it into the PR body and a label (approval/prod-delete-3), and stores it in the approvals table.
4. A CI check reads the label and asks cmapi which PR reviewers count (Keycloak group, approver role and binding scope; the requester excluded by sub when self-approval is off), and stays red until the count is met; branch protection requires that check.
5. A timeout job marks the request timeout and closes the PR after timeoutHours.

Rule changes are PRs to this file and are versioned with the API; every ChangeRequest records the rules version it was evaluated against.

**Auto-approval.** Baseline requests that the platform team has decided need no human, such as a small rnd namespace or a team label change, can approve and merge themselves. It is off unless switched on, and it can be switched off at three levels.

| Switch | Where | Effect |
| --- | --- | --- |
| Master | autoApproval.enabled in approval-rules.yaml | false: every request follows the normal rules |
| Per policy | policies\[\].enabled | Turns one baseline off and leaves the rest |
| Kill switch | POST /api/v1/admin/auto-approval:pause and :resume (cmapi-admin) | Takes effect immediately, without a PR, and overrides Git until resumed. Stored in the database with who paused it and why; shown on GET /api/v1/admin/integrations and in every affected PR. For incidents and audits. |

```yaml
# config/approval-rules.yaml (continued)
autoApproval:
  enabled: true
  maxPerTeamPerDay: 20                 # beyond this, the team's requests go to human approval
  policies:
    - name: baseline-rnd-namespace
      enabled: true
      match:
        plugin: namespaces
        actions: [create]
        environments: [rnd]
        tiers: [small, medium]
        clusterSelector: {matchLabels: {region: us-central}}   # optional
    - name: team-metadata
      enabled: true
      match:
        plugin: metadata
        actions: [patch, update]
        environments: ["*"]
        keyClasses: [team]             # only team keys; a governed or sensitive key falls back
    - name: baseline-sa-grants
      enabled: false                   # written, not yet switched on
      match:
        plugin: sa-grants
        actions: [create]
        environments: [rnd, qa]
        clusterRoles: [view, edit]
      requester:
        clients: [svc-payments-ci]      # optional: only these callers qualify
```

**Guards that no policy can switch off.** A request matching a policy still goes to humans when any of these holds:

- The action is a delete. Deletes are never auto-approved.
- A namespace pattern or threshold added approvals: capacity warn, request-to-peak ratio, quota increase over 100%, a sensitive label key, or a critical-\* namespace.
- Placement or the capacity check is anything other than fits on fresh data.
- The Plan has warnings.
- The team has used its daily allowance.

CI must still pass: auto-approval replaces the human review, not the checks.

**How it runs.** The engine returns ApprovalRequirement with requiredCount 0, autoApproved true and the policy name. Core then:

- labels the PR approval/auto-\<policy>;
- turns on the Git host's auto-merge, so the PR merges the moment the checks pass;
- has the approval-count check pass with the reason auto-approved by policy \<name>;
- records an approvals row with approver auto:\<policy> and an auto\_approved event.

Branch protection requires the approval-count check rather than a human review, so no bot account has to approve a PR. The cmapi bot is the CODEOWNER of clusters/\*\*/namespaces, so its own PRs can merge. A dry run shows whether the request would be auto-approved and, if not, which guard stopped it.

**Changing the policies.** approval-rules.yaml is owned by platform-leads in CODEOWNERS. A PR that adds or widens a policy reaching prod needs two of them. cmapi\_auto\_approvals\_total{policy, environment} and cmapi\_auto\_approval\_fallbacks\_total{guard} show how often each baseline is used, and which guard sends requests back to humans.

## Policy in one place

Every object rule is written once as a Kyverno policy and checked at three points: the API at plan time, CI on the PR, and admission on the cluster. Python validators keep only what Kyverno cannot see.

| Checkpoint | How it runs | What it stops |
| --- | --- | --- |
| API plan | kyverno apply on the rendered manifests, from the CLI baked into the image | Bad requests, before any PR exists |
| CI on the PR | Same command, same bundle version | Hand edits to cluster-configs that bypass the API |
| Cluster admission | Policies synced to each cluster by its ArgoCD, in Enforce mode | Changes that bypass Git entirely |

**What moves into the bundle.** DNS-1123 names and reserved prefixes; label and annotation key and value rules; the ServiceAccount subject rule; the ClusterRole and SCC allowlists; limits never below requests; required labels (cmapi.net/cluster-id, cmapi.net/tier, and later owner, team and cost-center); the protected-namespace delete block.

**What stays in Python.** Checks that need more than one object or outside data: the namespace already exists, an open change request on the object, capacity headroom, approval facts, and the caller's namespace-admin check.

**Keeping it offline.** Allowlists live inside the policies as lists, not as ConfigMap lookups, so the CLI evaluates them with no cluster access and gives the same answer the cluster will.

```
cluster-configs/
└── policies/                         # one bundle, versioned with tags
    ├── naming.yaml
    ├── labels.yaml
    ├── rbac-subjects.yaml            # SA subjects only, same namespace
    ├── rbac-allowlist.yaml           # grantable ClusterRoles
    ├── scc-allowlist.yaml
    ├── quota-limits.yaml             # limits >= requests
    ├── protected-namespaces.yaml
    └── tests/                        # kyverno test cases, run in CI on every policy change
```

Each cluster's root Application includes policies/ pinned to a bundle tag, and the API reports the tag it validated against in every Plan. A Kyverno failure maps to the policy-violation problem type, with the policy and rule names in errors.

## Observability

The API exposes /metrics for OpenShift user workload monitoring, ships dashboards (Perses in the OpenShift console by default, Grafana optional) and a PrometheusRule; the current set of seven dashboards, alerts and KPIs is under Observability, KPIs and dashboards in Design and Architecture, and this section keeps the detail, and logs JSON with clusterId and requestId on every line.

**Metrics.** prometheus-fastapi-instrumentator covers HTTP; prometheus\_client covers the rest. Prefix cmapi\_. Labels stay low-cardinality: cluster\_id, plugin, kind, action, status; never namespace, user or request ID.

| Metric | Type | Labels | Answers |
| --- | --- | --- | --- |
| cmapi\_http\_requests\_total | counter | route, method, status | Traffic and error rate |
| cmapi\_http\_request\_duration\_seconds | histogram | route, method | API latency |
| cmapi\_change\_requests\_total | counter | cluster\_id, plugin, kind, action, status | Volume and outcomes |
| cmapi\_change\_lead\_time\_seconds | histogram | cluster\_id, plugin, action | Submit to synced |
| cmapi\_approval\_wait\_seconds | histogram | cluster\_id, rule | Time waiting on reviewers |
| cmapi\_open\_change\_requests | gauge | cluster\_id, status | Backlog |
| cmapi\_validation\_failures\_total | counter | plugin, code | Which rules users hit |
| cmapi\_git\_operations\_total / \_duration\_seconds | counter / histogram | provider, op, result | Git host health |
| cmapi\_cluster\_api\_calls\_total / \_duration\_seconds | counter / histogram | cluster\_id, verb, result | Cluster API health |
| cmapi\_cluster\_reachable | gauge (0/1) | cluster\_id | Per-cluster reachability |
| cmapi\_thanos\_query\_duration\_seconds | histogram | cluster\_id, result | Thanos health (exported by cmapi-capacity) |
| cmapi\_sync\_drift\_total | counter | cluster\_id | OutOfSync with no open request |
| cmapi\_token\_issuances\_total | counter | cluster\_id, result | SA token use |
| cmapi\_jobs\_pending / cmapi\_job\_failures\_total | gauge / counter | kind | Worker health |
| cmapi\_plugin\_info | gauge (1) | plugin, version | What is deployed |

**Collection.** Enable user workload monitoring on the hub (enableUserWorkload: true in cluster-monitoring-config) and ship a ServiceMonitor in the Helm chart:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cmapi
  namespace: cmapi
spec:
  selector:
    matchLabels: {app: cmapi}
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```

**Alerts (PrometheusRule).**

| Alert | Condition | Severity |
| --- | --- | --- |
| CmapiHighErrorRate | 5xx over 2% of requests for 10 min | critical |
| CmapiClusterUnreachable | cmapi\_cluster\_reachable == 0 for 10 min | warning |
| CmapiGitUnavailable | Git operation failures over 20% for 5 min | critical |
| CmapiSyncStuck | Request merged but not synced after 30 min | warning |
| CmapiDriftDetected | Any increase in cmapi\_sync\_drift\_total | warning |
| CmapiApprovalBacklog | Open requests waiting on approval over 24 h | info |
| CmapiWorkerBacklog | cmapi\_jobs\_pending above 100 for 15 min | warning |

Capacity adds one gauge and one alert: cmapi\_capacity\_snapshot\_age\_seconds{cluster\_id}, and CmapiCapacitySnapshotStale when it exceeds two snapshot intervals for any cluster (warning).

Adoption adds cmapi\_namespaces{cluster\_id, state} (state = managed, candidate, unmanaged, excluded) and cmapi\_adoptions\_total{cluster\_id, result}; the Change flow dashboard gets a managed-coverage panel per cluster.

**Dashboards** (kept as Grafana JSON in the Helm chart and converted by percli into PersesDashboards for the OpenShift console; dashboards.provider picks perses, grafana or both; the data source is each instance hub's Thanos Querier). The first three of the seven:

1. **Service health.** Request rate, error rate, p50/p95/p99 latency, pods, worker backlog.
2. **Change flow.** Requests by cluster, plugin and status; lead time and approval wait percentiles; failures and rejections by reason.
3. **Fleet dependencies.** Cluster reachability heatmap, cluster API and Thanos latency per cluster, Git host latency, drift events.

**Logs and traces.** structlog JSON to stdout with request\_id, cluster\_id, plugin, caller and trace\_id; tokens and manifests with secrets are never logged. OpenTelemetry instruments FastAPI, httpx and SQLAlchemy and exports OTLP if a collector exists; it is off by default.

## KPIs

The current KPI table, extended with auto-approval rate, placement accuracy, capacity freshness, import health and docs coverage and measured per instance, is in Design and Architecture. Success means teams get namespaces and access faster, with fewer failures and less wasted quota; targets are proposed and need agreement before launch.

| KPI | Definition | Source | Proposed target |
| --- | --- | --- | --- |
| Lead time, no approval | Submit to synced, rnd requests | cmapi\_change\_lead\_time\_seconds p90 | Under 10 min |
| Lead time, with approval | Submit to synced, approved requests | Same, rule label set | Under 1 business day p90 |
| Approval turnaround | PR opened to required approvals met | cmapi\_approval\_wait\_seconds p50 / p90 | 4 h / 24 h |
| Self-service rate | Requests completed with no platform-team touch | change\_requests without a platform-leads approval or manual edit | Over 80% |
| Change failure rate | Failed, sync-failed or reverted requests / merged requests | change\_requests, request\_events | Under 5% |
| Validation reject rate | Rejected at plan / submitted | cmapi\_validation\_failures\_total | Tracked, not targeted; rising means unclear rules or forms |
| Drift events | OutOfSync without an open request | cmapi\_sync\_drift\_total | 0 per week |
| Quota efficiency | Used CPU and memory / quota, per namespace, 14-day peak, read live from Thanos | Thanos (live), quota\_analyses, namespace\_verdicts | Over 40% median |
| Cluster headroom | Quota headroom per cluster | capacity\_snapshots (cmapi-capacity) | Above 20% on every cluster |
| API availability | Successful requests / all requests, excluding 4xx | cmapi\_http\_requests\_total | 99.5% monthly |
| Expired namespaces cleaned | Namespaces past TTL still present after 24 h | Expiration reports | 0 |
| Rebuild recovery | Cluster bootstrap to Synced and Healthy | cluster\_sync\_state | Under 1 h |

The Change flow dashboard carries the first six; a monthly report from the database covers the rest by cluster and team.

Adoption adds one KPI: managed coverage, managed namespaces / (all namespaces − excluded) per cluster, from cmapi\_namespaces; proposed target 90% within two quarters of launch.

## Missing pieces needed for success

None of the earlier designs covered these; each is small, but launching without them breaks the async model or trust in it.

| Piece | Why it is needed | Approach |
| --- | --- | --- |
| Status worker | Requests must move from pr\_open to synced without a user polling Git | Async worker on the jobs table (SELECT … FOR UPDATE SKIP LOCKED); runs in the same image with a different command |
| Git webhook receiver | Polling alone is slow and rate-limited | POST /api/v1/webhooks/git with signature check; enqueues sync\_pr\_state |
| ArgoCD status watcher | Merged is not done; synced is | Poll the cluster's root Application every 30 s while a request is merged |
| Idempotency and per-object lock | Retries and double clicks must not open two PRs | Idempotency-Key + the partial unique index in Schemas |
| Drift detection | Someone edits a cluster by hand | GET /namespaces/{ns}/drift plus a drift\_detected event when the Application is OutOfSync with no open request |
| Offline validation toolchain | Server-side dry-run would need write RBAC | Bake kubeconform, the Kyverno CLI and per-cluster OpenAPI schemas into the image; refresh schemas nightly |
| Per-cluster bootstrap bundle | A new or rebuilt cluster must be ready for the API and ArgoCD | The cluster-baseline process creates cmapi-reader and its bindings; cmapi's Git folder template adds the ArgoCD root Application and Kyverno cleanup RBAC |
| Cluster onboarding endpoint | Adding a cluster should be a reviewed change, not a hand edit | The cluster-onboard operation opens the clusters.yaml PR once the baseline's import Secret connects |
| Credential rotation | Per-cluster tokens and the Git key expire or leak | The cluster baseline (or RHACM) rotates cluster tokens and cmapi alerts before expiry; GitHub App tokens minted hourly |
| Notifier | Requesters and approvers need to know without watching Git | Slack and email on pr\_open, approval needed, synced, failed, timeout (the n8n messages) |
| Rate limits | Protect clusters and the Git host from bursts | Per caller and per cluster token buckets; 429 with Retry-After |
| Generated CLI and SDK | Automation should not hand-write HTTP calls | openapi-python-client from /openapi.json, published with each release |
| Portal integration | The Namespace Configurator becomes a client, not a file generator | Portal calls POST ?dryRun=true for live validation, then POST |
| Contract and integration tests | Plugins must not break the contract or each other | Spec snapshot test; per-plugin tests against a kind cluster and a local Git server |
| Runbooks | On-call needs steps, not architecture | Cluster unreachable, Git down, sync stuck, drift, token rotation, rebuild verification |
| Deprecation policy | Plugins and fields will change | Sunset header and 6 months' notice for removed fields or endpoints |

Two capacity-specific checks belong in cluster onboarding: confirm the Thanos Route answers with the API token, and confirm platform Prometheus retention is at least 15 days (or note the shorter window in the registry), so 14-day queries never return silently short data.

## Application layout

One repo for core and the first plugins, one image with two entry points (api and worker); later plugins can live in their own repos and install through the entry-point group.

```
cmapi/
├── pyproject.toml                    # FastAPI, Pydantic v2, SQLAlchemy 2 + asyncpg, Alembic,
│                                     # kubernetes, httpx, prometheus-client, structlog
├── Containerfile                     # UBI9 python-312 minimal; kubeconform + kyverno CLI baked in
├── helm/cmapi/                       # api, worker and capacity Deployments, Route, ServiceMonitor,
│                                     # PrometheusRule, Perses and Grafana dashboards, Secret mounts, PDB
├── config/
│   ├── clusters.yaml                 # registry: environment, gitopsPath, writes, syncSignal, thanosUrl override, metadata, placement (policy only; connections are imported)
│   ├── plugins.yaml
│   ├── approval-rules.yaml
│   ├── authz-scopes.yaml             # role + scope bindings for Keycloak groups and clients
│   ├── integrations.yaml             # sync signal, operations engine, event publisher (all optional)
│   ├── placement.yaml                # score weights, freshness limits, reservation TTL
│   ├── capacity.yaml                 # snapshot interval, zone and role rows, retention
│   ├── operations/                   # operation templates: cluster-onboard.yaml, rebuild-verify.yaml, ...
│   ├── policy-bundle.yaml            # tag of the Kyverno bundle in cluster-configs/policies
│   └── adoption.yaml                 # mounted from the cmapi-adoption ConfigMap
├── src/cmapi/
│   ├── main.py                       # app factory: loads registry, discovers plugins, mounts routers
│   ├── worker.py                     # job loop: open_pr, sync_pr_state, watch_sync, notify, expire_check (capacity jobs only when capacity.mode is embedded)
│   ├── core/
│   │   ├── plugin.py                 # Plugin and Planner protocols, discovery
│   │   ├── models.py                 # ClusterScoped, Plan, ChangeRequest, Problem
│   │   ├── pipeline.py               # authorize -> idempotency -> lock -> plan -> approve -> commit
│   │   ├── registry.py               # imports clusters from cmapi-imports Secrets, merges clusters.yaml policy
│   │   ├── auth.py                   # Keycloak JWT verification (JWKS cache), Principal
│   │   ├── authz.py                  # role permissions, scope bindings, require()
│   │   ├── metadata.py               # label and annotation keys, classes, merge patch
│   │   ├── operations.py             # OperationsEngine protocol; builtin, Argo Workflows and Tekton adapters
│   │   ├── clients/                  # kube.py, argocd.py (per-cluster, read-only)
│   │   ├── git/                      # provider.py (GitHub, GitLab REST), clone.py (GitPython https/ssh)
│   │   ├── render/                   # renderer interface; project_meta.py, manifests.py
│   │   ├── validate/                 # runs the Kyverno bundle and kubeconform; Python only for cross-object checks
│   │   ├── approvals.py              # rules engine
│   │   ├── db/                       # SQLAlchemy models, repositories, Alembic migrations
│   │   ├── errors.py                 # RFC 9457 problem types
│   │   └── observability.py          # metrics, structlog, OpenTelemetry
│   ├── ops/                          # operation step library; runs in the worker or as the cmapi-ops image
│   ├── capacity/                     # cmapi-capacity service (own entrypoint): thanos.py client, snapshots, sweep, usage API
│   └── plugins/
│       ├── namespaces/  metadata/  quotas/  limitranges/  expiration/
│       ├── serviceaccounts/  sa_grants/  scc_grants/  sa_tokens/
│       ├── rbac_read/  identity_read/  adoption/  sync/  reports/
│       └── capacity/                 # each: __init__.py (plugin), router.py, models.py, planner.py, tests/
└── tests/
    ├── contract/test_openapi_snapshot.py
    ├── core/                         # pipeline, approvals, idempotency, lock
    └── integration/                  # kind cluster + local Git server
```

Each plugin folder has the same five files, so adding an offering is copying one folder, renaming it and registering its entry point.

## Optional integrations: sync signal, operations, events

cmapi runs fully with no Argo Workflows, no Argo Events and no Argo CD Notifications. Each sits behind an extension point with a built-in default. Turning one on adds capability; turning it off, or losing it, never touches the request path. The reasoning behind each choice is in cmapi — Argo Events and Workflows Technical Review.

| Capability | Built-in default (no Argo) | With the optional integration |
| --- | --- | --- |
| Sync status | The worker polls each cluster's root Application every 30 seconds, only for clusters with requests in merged | Argo CD Notifications push results; polling drops to a 10-minute reconcile pass |
| Operations: cluster-onboard, rebuild-verify, adoption-sweep, bulk-migrate, promote | The built-in engine runs the steps inside the cmapi worker, with state in PostgreSQL | Argo Workflows (or Tekton) runs the same steps as pods, with its UI, archive and S3 reports |
| Fan-out limits | Per-cluster cap enforced through the jobs table | Workflow semaphores |
| Outbound events | Off, or a signed webhook or Kafka topic that any consumer can read | Argo Events Sensors are one such consumer; cmapi does not know they exist |
| Teams and email updates | notify job | Unchanged |

Argo CD Notifications ships with OpenShift GitOps, so it is the cheapest to switch on, but it is still switched on per cluster.

**Configuration.** One file, read at startup and on /admin/reload. A cluster's entry in clusters.yaml can override the sync signal, so notifications roll out one cluster at a time.

```yaml
# config/integrations.yaml
syncSignal:
  default: poll              # poll | notify
  pollInterval: 30s          # used where notify is off
  reconcileInterval: 10m     # used where notify is on
operations:
  engine: builtin            # builtin | argo-workflows | tekton
  builtin:
    maxConcurrentSteps: 4    # separate from request jobs, so operations never starve them
  argoWorkflows:
    namespace: cmapi-workflows
    image: registry.ephico2real.com/caas/cmapi-ops:1.0.0
  tekton:
    namespace: cmapi-pipelines
    image: registry.ephico2real.com/caas/cmapi-ops:1.0.0
events:
  publisher: none            # none | webhook | kafka
  webhook:
    url: https://events.ephico2real.com/cmapi
    hmacSecretRef: cmapi-events-hmac
  kafka:
    bootstrap: kafka.ephico2real.com:9093
    topic: cmapi.events

# config/clusters.yaml, per cluster
- clusterId: OCP_GF1
  syncSignal: notify         # this cluster has Argo CD Notifications configured
```

**One step library, any engine.** An operation template is data in config/operations/. Its steps are Python functions in cmapi.ops, shipped both in the worker image and as the cmapi-ops container. The built-in engine calls the functions in-process. The Argo adapter renders the same template into a Workflow with one cmapi-ops container per step, and the Tekton adapter renders a PipelineRun. A template changes in one place and behaves the same on every engine.

```yaml
# config/operations/cluster-onboard.yaml
name: cluster-onboard
parameters: [cluster-id]
retry: {limit: 3, backoff: 30s, factor: 2}
steps:
  - {name: wait-import}                    # the baseline's import Secret appears and connects
  - {name: preflight,        after: [wait-import]}
  - {name: propose-registry, after: [preflight], outputs: [request-id]}
  - {name: wait-request,     after: [propose-registry],
     inputs: {request-id: "{{steps.propose-registry.outputs.request-id}}"}}
  - {name: smoke-test,       after: [wait-request]}
onExit: cleanup
```

```python
# cmapi/core/operations.py
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal, Protocol

from cmapi.core.models import Api


class RunStatus(Api):
    operation_id: str
    run_name: str
    phase: Literal["Pending", "Running", "Succeeded", "Failed", "Error", "Stopped"]
    finished_at: datetime | None = None
    report: dict | None = None                  # built-in engine keeps the report here
    report_url: str | None = None               # Argo and Tekton put it in S3


class OperationsEngine(Protocol):
    name: Literal["builtin", "argo-workflows", "tekton"]

    async def available(self) -> bool: ...                       # CRDs present, API reachable
    async def submit(self, operation_id: str, template: "OperationTemplate",
                     parameters: dict[str, str]) -> str: ...      # returns the run name
    async def cancel(self, run_name: str) -> None: ...             # stop; onExit still runs
    def watch(self) -> AsyncIterator[RunStatus]: ...               # phase changes for cmapi's runs
```

**Built-in engine.** Each step is a job of kind operation\_step in the existing jobs table, and its state lives in operation\_steps, so a worker restart resumes where it stopped. Retries follow the template's retry block. A fan-out step gets one row per item, capped per cluster. Without Argo you lose its UI, the workflow archive and pod-level isolation; reports go into the operations row as JSON instead of S3. Cluster bootstrap is the baseline's job, so no step needs cluster-admin.

```sql
CREATE TABLE operation_steps (
  operation_id  VARCHAR(40)  NOT NULL REFERENCES operations (operation_id),
  step          VARCHAR(80)  NOT NULL,
  item          VARCHAR(253) NOT NULL DEFAULT '',   -- fan-out item; '' for a single step
  phase         VARCHAR(20)  NOT NULL DEFAULT 'Pending',
  attempts      INT          NOT NULL DEFAULT 0,
  outputs       JSONB,
  last_error    TEXT,
  PRIMARY KEY (operation_id, step, item)
);
```

**Operations API, the same on every engine.** POST /api/v1/operations starts a template; GET /api/v1/operations/{id} is the status of record; POST /api/v1/operations/{id}:cancel stops it. Starting one needs operations:run, held by cmapi-operator and cmapi-admin. Four rules apply whichever engine runs the steps:

- Steps change managed objects only by calling cmapi. The only exception is read-only checks.
- Runs start only through cmapi, which records an operations row and labels Argo or Tekton runs cmapi.net/operation-id.
- No pause nodes: a step that needs approval opens a cmapi request and polls it, and people approve in the PR.
- Steps call cmapi as svc-cmapi-workflows, and every request they open records both that client and the person who started the operation.

**Events.** The EventPublisher has three adapters: none (the default), webhook (an HMAC-signed POST with the signature in X-Cmapi-Signature) and kafka. The outbox is written only when a publisher is on, in the same transaction as request\_events, and a publish job drains it. Argo Events reads the webhook or the Kafka topic like any other consumer.

**Failure isolation.** No optional integration sits in the request path.

- If the configured engine is unreachable at startup, cmapi starts anyway and stays ready. POST /api/v1/operations returns 503 operations-engine-unavailable until the engine comes back.
- If notifications stop arriving, the reconcile pass catches up.
- If the event bus is down, the outbox holds events until it recovers.

GET /api/v1/admin/integrations reports each integration's mode and health, per cluster for the sync signal.

**Testing.** CI runs every operation template on the built-in engine against a kind cluster. The integration environment runs the same templates on Argo Workflows, with the same expected results.

## Roadmap plugins

Each roadmap item is a plugin or a core extension point, so none of them changes the contract for existing endpoints. Placement and rightsizing come first after launch; the rest are backlog. SA token guardrails (lifetime caps, active-token limits, issuance alerts) are deferred and not designed here.

| Item | Shape | What it adds | Timing |
| --- | --- | --- | --- |
| Placement | Capacity plugin endpoint | POST /api/v1/capacity:place | Phase 3, before launch |
| Rightsizing loop | New plugin, rightsizing | Weekly recommendations and PRs | First quarter after launch |
| Change sets and promote | Core extension | Linked requests across clusters | Backlog |
| Temporary quota bursts | Quotas plugin extension | Quota with an expiry and automatic revert | Backlog |
| Capacity forecasting | Capacity plugin endpoint | Days until each cluster runs short | Backlog |
| Showback | New plugin, showback | Cost per team, cluster and month | Backlog |
| Ownership attestation | New plugin, ownership | Owner and team labels, 90-day confirmation | Backlog |
| Outbound events | Core extension point | CloudEvents to subscribers | Backlog |
| Tamper-evident audit | Core database change | Hash-chained request\_events | Backlog |

**Placement.** Now designed in full in the Placement section, with reservations, zone-failure headroom and accuracy checks, and delivered in Phase 3.

**Rightsizing loop.** Designed in the Usage analysis tab. A daily fleet sweep reads each cluster's last 14 days from Thanos and stores verdicts and recommendations. The weekly loop applies the rnd and qa decreases teams have opted in to.

**Change sets and promote.** POST /api/v1/changesets takes a list of writes across clusters and returns one changeset with a linked ChangeRequest per item. Each item gets its own PR and approval rule, and the changeset status rolls up from its members. POST /clusters/{id}/namespaces/{ns}:promote {targetClusterId} copies the namespace's settings to the target cluster's environment and applies that environment's approvals. Adds a changesets table and a changeset\_id column on change\_requests.

**Temporary quota bursts.** PUT or PATCH on the quota accepts expiresAt. The planner records the current quota as the revert target, and a burst\_revert job opens the revert PR at expiry. That PR needs no approval because it restores an approved value. Maximum burst length is set per environment (proposed: 14 days).

**Capacity forecasting.** GET /capacity/forecast fits a linear trend to 90 days of capacity\_snapshots for quota committed and requested, and returns days until quota headroom falls below 20%. It exports cmapi\_capacity\_days\_to\_threshold{cluster\_id, resource} and alerts at 30 days. It returns insufficient-history until 30 days of snapshots exist.

**Showback.** Rates per environment in config (cost per core-hour and per GiB-hour of requests). GET /api/v1/reports/showback?month=2026-11 groups by cluster, cost-center and team. It needs the cmapi.net/cost-center label, which the policy bundle then requires on new namespaces.

**Ownership attestation.** The policy bundle requires cmapi.net/owner and cmapi.net/team labels. Every 90 days the notifier asks the owner to confirm the namespace is still needed; confirming records cmapi.net/attested-at. No answer within 14 days opens a PR setting a TTL 30 days out. A daily check flags namespaces whose owner no longer appears in the LDAP-synced groups.

**Outbound events.** An EventPublisher extension point emits CloudEvents 1.0 over HTTPS webhooks: net.cmapi.changerequest.created, .approved, .merged, .synced, .failed and .timeout, each with clusterId and requestId. Subscriptions live in an event\_subscriptions table with a signing secret per subscriber. A ServiceNow subscriber can open a change ticket for prod requests.

**Tamper-evident audit.** request\_events gains prev\_hash and row\_hash, where row\_hash = SHA-256(prev\_hash + the canonical row). The application's database role gets INSERT and SELECT only on that table, with no UPDATE or DELETE. A daily job verifies the chain and alerts on a break.

These items add three labels to the conventions table: cmapi.net/owner, cmapi.net/team and cmapi.net/cost-center, plus the cmapi.net/attested-at annotation.

## Delivery plan

Superseded by the resequenced plan in Design and Architecture; kept here for reference. Five phases to launch, each ending in something a team can use, then one post-launch phase and a backlog; no phase starts until the previous one's exit check passes. Adoption and the single policy bundle are both in before launch.

1. **Core and reads.** App factory, plugin discovery, cluster import (cmapi-imports Secrets plus clusters.yaml policy), Keycloak auth (realm as code, LDAP federation, token verification, roles and scope bindings), problem errors, metrics and logs; read plugins: namespaces (read), rbac-read, identity-read, sync. Exit: every read endpoint live on two clusters, Service health dashboard populated.
2. **First write path.** Pipeline, idempotency and lock, the Kyverno policy bundle (API plan, CI and admission on every cluster), project-meta renderer, Git provider in rest mode, status worker, webhook receivers (Git; Argo CD Notifications where a cluster opts in, polling elsewhere), approvals engine; namespaces and metadata writes. Exit: an rnd namespace goes from POST to synced with no manual step.
3. **Quota and capacity.** cmapi-capacity in remote mode, with the cluster-monitoring-view binding from the cluster baseline and snapshots every capacity.snapshotInterval, and the capacity plugin as its gateway; quotas and limitranges planners with capacity checks, quota analyses, cluster metadata and selectors in clusters.yaml, placement with reservations (POST /capacity:place), Change flow dashboard. Exit: an oversized quota request is flagged and routed to platform approval.
4. **Access.** serviceaccounts, sa-grants and scc-grants with allowlists, sa-tokens. Exit: a team SA with a namespace edit grant and the anyuid SCC created through the API, audited end to end.
5. **Lifecycle and launch.** adoption of labelled namespaces with the exclusion ConfigMap and the unmanaged-namespaces report, expiration, delete with extra approvals and Prune=confirm, reports, notifier, operations engine (built-in by default; Argo Workflows and Tekton adapters optional) with cluster-onboard and rebuild-verify, portal integration, generated CLI, runbooks, alerts. Exit: KPIs reported for one month; v1 contract frozen.

**After launch.**

- **Phase 6, first quarter after launch.** The rightsizing loop and the weekly rebalance report. Exit: the first rightsizing PRs are merged, and the placement backtest shows zero overcommit breaches over 30 days.
- **Backlog, in any order.** Change sets and promote, temporary quota bursts, capacity forecasting, showback, ownership attestation, outbound events, tamper-evident audit. SA token guardrails are deferred.
