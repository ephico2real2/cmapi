# cmapi — API call examples

Sample calls against the Cluster Management API (cmapi) v1. Every path is cluster-first:

```
https://cmapi.ephico2real.com/api/v1/clusters/{clusterId}/...
```

- **Reads** return live state from the target cluster.
- **Writes** (POST, PUT, PATCH, DELETE) return `202 Accepted` with a ChangeRequest; the change lands through a Git PR and the cluster's ArgoCD.
- `clusterId` must appear in both the path and the request body. A mismatch returns `422 validation-failed`.
- **Every call needs a Keycloak access token.** cmapi issues no tokens of its own.

Interactive docs on every instance: Swagger UI at `/docs`, ReDoc at `/redoc`, spec at `/openapi.json` and `/openapi.yaml`, spec changes at `/docs/changelog`.

**Pick the instance for your environment.** cmapi runs as one instance per network zone. Call the one that serves the environment you are working in; any other returns `422 environment-not-served` with the right URL.

| Environments | Instance | API base URL | Portal |
| --- | --- | --- | --- |
| rnd, dev | nonprod | `https://cmapi-nonprod.ephico2real.com/api/v1` | `https://portal-nonprod.ephico2real.com` |
| qa, uat | staging | `https://cmapi-staging.ephico2real.com/api/v1` | `https://portal-staging.ephico2real.com` |
| prod | prod | `https://cmapi.ephico2real.com/api/v1` | `https://portal.ephico2real.com` |

Tokens are minted per instance (audience `cmapi-nonprod`, `cmapi-staging` or `cmapi-prod`), so a token for one instance is refused by the others.

---

## Authentication (Keycloak)

Every call is two steps: get an access token from Keycloak, then send it to cmapi as `Authorization: Bearer <token>`. Access tokens last **5 minutes**. Clients refresh them automatically, so people sign in far less often (see [Session lengths](#session-lengths)).

```bash
export KC=https://sso.ephico2real.com/realms/ephico2real/protocol/openid-connect
export CMAPI=https://cmapi-nonprod.ephico2real.com/api/v1   # the instance for your environment
```

| Caller | Keycloak client | Flow |
| --- | --- | --- |
| Pipelines and automation | `svc-<team>-<purpose>` (one per pipeline) | Client credentials |
| An AI agent or bot that onboards namespaces | its own `svc-` client, or the local account `bot-user` through `cmapi-automation` | Client credentials, or password grant for the local account |
| A person at a terminal | `cmapi-cli` | Device authorization (browser approval) |
| Swagger UI | `cmapi-docs` | Authorization Code + PKCE, via the **Authorize** button |
| Namespace portal | `cmapi-portal` | Authorization Code + PKCE, handled by the portal |

The password grant is disabled for people: LDAP passwords are typed only into Keycloak's own login page, never into scripts. The one exception is `cmapi-automation`, for local Keycloak accounts such as `bot-user`, which have no LDAP password.

### Pipelines and automation: client credentials

```bash
TOKEN=$(curl -s "$KC/token" \
  -d grant_type=client_credentials \
  -d client_id=svc-payments-ci \
  -d client_secret="$CMAPI_CLIENT_SECRET" | jq -r .access_token)
```

Fetch a token per job, or again when it is within 30 seconds of the `expires_in` the token response returns. Service accounts get no refresh token; they just ask again.

A new pipeline gets its client through a PR to the realm repository (`cmapi-sso/realm/ephico2real.yaml`), which also assigns its role. What a role may do is set in the instance's `config/authz-roles.yaml`; a role can be limited to some environments there (for example `cmapi-bot-rnd`, a requester in rnd only). There is no team or namespace-name scope: any role with `namespaces:create` may ask for any name that is not reserved.

### An AI agent or bot: the onboarding role

`cmapi-onboarding` lets an account create namespaces and follow its requests, and nothing else: it cannot change or delete a namespace. Give it to people (directly or through the group `/cmapi/app-cmapi-rbac-onboarding`) or to a local Keycloak account such as `bot-user` that an agent signs in as:

```bash
TOKEN=$(curl -s "$KC/token" \
  -d grant_type=password -d client_id=cmapi-automation -d client_secret="$AUTOMATION_CLIENT_SECRET" \
  -d username=bot-user -d password="$BOT_PASSWORD" | jq -r .access_token)
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/me" | jq .access
```

An account holding an automation role (`identity.automationRoles`, default `cmapi-onboarding`) needs no employee ID and is recorded as the requester, with `"automated": true`. It may send `"onBehalfOf"` to record a person instead. Its requests follow the same approval rules as anyone's; rules can tell them apart with the `automated` and `requesterClient` facts.

### A person at a terminal: device flow

The CLI does this for you:

```bash
cmapi login            # prints a URL and code; approve in the browser; stays signed in up to 90 days
TOKEN=$(cmapi token)   # a fresh access token for use with curl
cmapi logout           # revokes the stored offline token
```

The same flow by hand with curl:

```bash
# 1. Ask for a device code, then open the printed URL and sign in with your LDAP account
curl -s "$KC/auth/device" -d client_id=cmapi-cli -d scope=offline_access \
  | tee /tmp/device.json | jq -r .verification_uri_complete

# 2. After approving in the browser, exchange the code for tokens
curl -s "$KC/token" \
  -d grant_type=urn:ietf:params:oauth:grant-type:device_code \
  -d client_id=cmapi-cli \
  -d device_code="$(jq -r .device_code /tmp/device.json)" > /tmp/tokens.json
TOKEN=$(jq -r .access_token /tmp/tokens.json)

# 3. Later, swap the refresh token for a new access token (no browser).
#    Save the new refresh token each time: refresh tokens are single-use.
curl -s "$KC/token" \
  -d grant_type=refresh_token \
  -d client_id=cmapi-cli \
  -d refresh_token="$(jq -r .refresh_token /tmp/tokens.json)" > /tmp/tokens.new \
  && mv /tmp/tokens.new /tmp/tokens.json
TOKEN=$(jq -r .access_token /tmp/tokens.json)
```

`cmapi-cli` is a public client, so there is no secret. Keep the token file private (`chmod 600`); the CLI stores it in the OS keychain instead.

### Swagger UI

Open your instance's `/docs` (for rnd and dev, `https://cmapi-nonprod.ephico2real.com/docs`), click **Authorize**, sign in through Keycloak, then use **Try it out**. Swagger attaches the token to every call. `/redoc` is the same reference grouped by area, with a curl sample on every operation, and `/openapi.json` is the spec itself.

Both pages are generated from the running code, so they always match what the instance accepts: every route, field, example, required permission and error is filled in by cmapi's documentation layer, and an undocumented route cannot ship. Each instance's spec lists only the environments it serves.

### Python

```python
import time

import httpx

KC_TOKEN = "https://sso.ephico2real.com/realms/ephico2real/protocol/openid-connect/token"


class CmapiAuth(httpx.Auth):
    """Client-credentials token, cached until 30 seconds before it expires."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id, self.client_secret = client_id, client_secret
        self._token, self._expires = "", 0.0

    def auth_flow(self, request):
        if time.time() > self._expires - 30:
            r = httpx.post(KC_TOKEN, data={"grant_type": "client_credentials",
                                           "client_id": self.client_id,
                                           "client_secret": self.client_secret})
            r.raise_for_status()
            body = r.json()
            self._token, self._expires = body["access_token"], time.time() + body["expires_in"]
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


cmapi = httpx.Client(base_url="https://cmapi.ephico2real.com/api/v1",
                     auth=CmapiAuth("svc-payments-ci", "<client secret from your CI secret store>"))
print(cmapi.get("/me").json())
```

### Check who you are

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/me"
```

Returns your username, kind (user or service), client, identity and `access`: each of your roles with its permissions and the environments it covers, and your combined permissions. Check this first when a call returns 403.

### Session lengths

cmapi keeps no session; each call stands on its token. How long you stay signed in is set in Keycloak:

| Caller | Signs in again after |
| --- | --- |
| Portal | 8 hours idle or 12 hours total |
| Portal with **Remember me** | 7 days idle or 30 days total |
| CLI (`cmapi login`) | 30 days idle or 90 days total |
| Swagger UI | 1 hour idle or 8 hours total |
| Pipelines | No session; a new token per job |

Sessions survive Keycloak restarts and upgrades. A session ends early on sign-out, `cmapi logout`, an admin sign-out, or when your LDAP account is disabled. If you are removed from an LDAP group, the role disappears at your next token refresh (within about 15 minutes).

---

## Required headers

| Header | Reads | Writes | Value |
| --- | --- | --- | --- |
| `Authorization` | Yes | Yes | `Bearer <Keycloak access token>` |
| `Content-Type` | — | Yes | `application/json`, or `application/merge-patch+json` for PATCH |
| `Idempotency-Key` | — | Yes | A UUID per logical request; retries with the same key return the original ChangeRequest for 24 hours |
| `If-Match` | — | PUT, PATCH, DELETE | The `ETag` from the last GET; missing returns `428`, stale returns `412` |

---

## Generic template

### Read

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://cmapi.ephico2real.com/api/v1/clusters/{clusterId}/namespaces/{namespace}"
```

### Write

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{ ...body... }' \
  "https://cmapi.ephico2real.com/api/v1/clusters/{clusterId}/{resource}"
```

---

## Worked example: cluster `OCP_GF6` (rnd), namespace `payments-rnd`

### Set up

```bash
export KC=https://sso.ephico2real.com/realms/ephico2real/protocol/openid-connect
export CMAPI=https://cmapi-nonprod.ephico2real.com/api/v1   # rnd is served by nonprod
export CLUSTER=OCP_GF6
export NS=payments-rnd

# A person: sign in once, then take a fresh token whenever you need one
cmapi login
export TOKEN=$(cmapi token)

# Or a pipeline:
# export TOKEN=$(curl -s "$KC/token" -d grant_type=client_credentials \
#   -d client_id=svc-payments-ci -d client_secret="$CMAPI_CLIENT_SECRET" | jq -r .access_token)
```

Tokens expire after 5 minutes; run `export TOKEN=$(cmapi token)` again if a call returns 401.

### 1. Read the namespace (live from the cluster)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$CMAPI/clusters/$CLUSTER/namespaces/$NS"
```

### 2. Read its quota and usage

`GET /quotas` pages through every namespace in your scope on this instance with its ResourceQuota (hard and used for `requests.cpu`, `requests.memory` and `pods`), tier and latest usage verdict. It is what the portal's Quotas tab shows. `used` is the sum of pod requests, read from the watch cache; it is not real consumption and never calls Thanos. Pages are sorted A to Z by default, 50 at a time; follow `page.nextCursor` until it is null.

```bash
# First page, A to Z, with the attention counts and letter counts
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/quotas?env=rnd&limit=50"
# → {"items": [{"clusterId": "OCP_GF8", "namespace": "ledger-rnd", "team": "ledger", "tier": "small",
#      "hard": {"requests.cpu": "8", "requests.memory": "16Gi", "pods": "50"},
#      "used": {"requests.cpu": "7400m", "requests.memory": "13.9Gi", "pods": "41"},
#      "verdict": "quota-tight", "recommendation": "rec-ledger-rnd-0412"}, ...],
#    "page": {"limit": 50, "total": 263, "from": 1, "to": 50, "nextCursor": "eyJrIjpb...", "prevCursor": null},
#    "facets": {"attention": {"quotaTight": 13, "nearLimit": 28, "recommendation": 11, "oversized": 16, "idle": 3, "openRequest": 0},
#               "letters": {"a": 21, "b": 18, ...}}}

# Next page: pass the cursor back with the same filters (changing a filter or the sort returns 400 invalid-cursor)
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/quotas?env=rnd&limit=50&cursor=eyJrIjpb..."

# Jump to the first namespace starting with "p"
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/quotas?env=rnd&startsWith=p"

# Only what needs attention, most urgent first
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/quotas?state=quotaTight&sort=severity"

# Type-ahead: from 2 characters, up to 10 matches (name prefix, then contains, then team or app label)
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/quotas:suggest?q=pay"
# → [{"namespace": "payments-admin-rnd", "clusterId": "OCP_GF6", "environment": "rnd", "team": "payments", "match": "prefix"}, ...]

# Every matching row as CSV (same filters, not just one page; capped at 10,000 rows, audited)
curl -s -H "Authorization: Bearer $TOKEN" -o quotas-rnd.csv "$CMAPI/quotas:export?format=csv&env=rnd&q=payments"

curl -s -i -H "Authorization: Bearer $TOKEN" \
  "$CMAPI/clusters/$CLUSTER/namespaces/$NS/quota"      # -i shows the ETag header

curl -s -H "Authorization: Bearer $TOKEN" \
  "$CMAPI/clusters/$CLUSTER/namespaces/$NS/usage?window=14d"   # live, last 14 days, via cmapi-capacity
```

### 2b. Pick a cluster for a new namespace

Placement ranks the clusters you may use from stored capacity snapshots (no Thanos call) and holds the best one for 15 minutes. Put the returned `placementId` in the create body.

```bash
curl -s -X POST "$CMAPI/capacity:place" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"environment": "rnd", "team": "payments", "tier": "medium",
       "constraints": {"region": "us-central"}}'
# → {"placementId": "pl-20261103-5e17", "ranked": [{"clusterId": "OCP_GF6", "score": 78, "reserved": true}, ...], "excluded": [...]}
```

### 2a. See the tiers you can choose

`GET /tiers` returns every tier this instance offers per environment, resolved: the full ResourceQuota and LimitRange values, the tier's hash, and the bounds a `custom` quota must stay within. The portal's tier picker reads the same call; the response's `ETag` changes only when the catalog does.

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/tiers?environment=rnd"
# → {"catalogHash": "618ae03a131d6626", "sizable": ["requests.cpu", "requests.memory", "pods"],
#    "environments": {"rnd": {"tiers": [{"name": "small", "quota": {"requests.cpu": "8", ...}, ...}, ...],
#                             "custom": {"min": {...}, "max": {"requests.cpu": "32", ...}, "step": {...}}}}}
```

Pick `small`, `medium` or `large` and send no quota, or pick `custom` and send all three sizable keys, each within `min` and `max` and on `step`:

```json
"tier": "custom",
"quota": {"requests.cpu": "20", "requests.memory": "40Gi", "pods": "120"}
```

### 3. Dry run a create

Returns the Plan (validation results, rendered YAML, diff, approval requirement, capacity check). No PR, no reservation and no database row are created.

```bash
curl -s -X POST "$CMAPI/clusters/$CLUSTER/namespaces?dryRun=true" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "clusterId": "OCP_GF6",
        "namespace": "payments-rnd",
        "env": "rnd",
        "placementId": "pl-20261103-5e17",
        "tier": "medium",
        "labels": {
          "cmapi.net/team": "payments",
          "cmapi.net/cost-center": "cc-4410",
          "app.ephico2real.com/component": "api"
        },
        "annotations": {
          "cmapi.net/team-dl": "payments-team@ephico2real.com",
          "ops.ephico2real.com/runbook": "https://wiki.ephico2real.com/payments/runbook"
        },
        "expiresAt": "2026-12-15",
        "justification": "Payments service rnd namespace"
      }'
```

`cmapi.net/team` and `cmapi.net/team-dl` (your team's distribution list) are required. The team is ownership and cost metadata: any valid value, not checked against you. The namespace name is yours to pick too, as long as it is a DNS-1123 name, not reserved (`default`, `openshift-*`, `kube-*`, `cmapi-*` system names and the instance's `reservedPatterns`) and not an existing namespace cmapi does not manage. The DL only has to be an address in one of your organisation's email domains (the `emailDomains` list in `metadata-keys.yaml`; `ephico2real.com` in these examples is a placeholder), since cmapi does not look it up. Don't send who you are: cmapi reads your username and email from your token and writes them as `cmapi.net/requested-by-user` and `cmapi.net/requested-by`. A pipeline using a `svc-` client, or an automation account, may add `"onBehalfOf": "<username or employee ID>"` to name the person the request is for; cmapi looks that person up in the directory and records both. Without it, the client or account is the requester (`identity.requireOnBehalfOf: true` makes it mandatory). `expiresAt` is optional in rnd, dev, qa and uat; leave it out for a permanent namespace. In prod it is refused with `422 expiration-not-allowed`.

### 4. Submit the create

```bash
curl -s -X POST "$CMAPI/clusters/$CLUSTER/namespaces" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 7f3a2c1e-0b9d-4e2a-9a51-3c8d2f6b1a40" \
  -d @namespace-request.json
```

`namespace-request.json` holds the same body as step 3.

### 5. Change the quota

Uses the `ETag` from step 2 as `If-Match`. CPU and memory are checked separately against the cluster's quota headroom (and, in prod, its zone-failure headroom); either one alone can refuse the change with `capacity-exceeded`, and the error names the resource. To change the tier instead, PATCH the namespace with `{"tier": "large"}`.

```bash
curl -s -X PATCH "$CMAPI/clusters/$CLUSTER/namespaces/$NS/quota" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/merge-patch+json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'If-Match: "9b2e4f1c..."' \
  -d '{
        "clusterId": "OCP_GF6",
        "hard": {"requests.cpu": "16", "requests.memory": "32Gi"}
      }'
```

### 6. Add, change and remove labels and annotations

A merge patch: a string sets a key, `null` removes it, keys you leave out are untouched. Get the `ETag` from `GET .../metadata` first.

```bash
curl -s -i -H "Authorization: Bearer $TOKEN" \
  "$CMAPI/clusters/$CLUSTER/namespaces/$NS/metadata"   # every key, its class, and the ETag

curl -s -X PATCH "$CMAPI/clusters/$CLUSTER/namespaces/$NS/metadata" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/merge-patch+json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'If-Match: "3c7e91ab52d0"' \
  -d '{
        "clusterId": "OCP_GF6",
        "labels": {
          "app.ephico2real.com/component": "api",
          "app.ephico2real.com/legacy": null
        },
        "annotations": {
          "ops.ephico2real.com/pager": "payments-oncall"
        }
      }'
```

`PUT .../metadata` replaces your whole set of governed and team keys instead. The same endpoints exist for service accounts at `.../serviceaccounts/{sa}/metadata`. System keys (`cmapi.net/cluster-id`, `cmapi.net/tier`, …) and platform prefixes (`kubernetes.io/`, `openshift.io/`, …) are refused.

### 7. Track the request until it is synced

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$CMAPI/requests/req-20261103-7f3a"

curl -s -H "Authorization: Bearer $TOKEN" \
  "$CMAPI/requests/req-20261103-7f3a/events"
```

Approval happens in cmapi before anything reaches Git. The 202 arrives at `pending_approval`, or at `approved` when an auto-approval policy matched. Only then does the worker open a bot PR, which the bot merges when CI passes. Status moves through `pending_approval` → `approved` → `pr_open` → `merged` → `synced`; a delete stops in `awaiting_prune` until an operator confirms the prune. Exits: `rejected`, `cancelled`, `timeout`, `failed` (retry with `:retry`), `sync_failed` (`:retry` or `:revert`), `superseded` (re-plan).

### 8. Approve or reject (approvers)

Approvals are recorded in cmapi, never as Git reviews. Use your own token; you cannot approve your own request, one your pipeline client made, or an operation you started (except where the environment allows self-approval).

```bash
# What can I approve?
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/requests?status=pending_approval&approver=me"

curl -s -X POST "$CMAPI/requests/req-20261103-9c02:approve" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"comment": "Load test signed off by SRE"}'
# → {"requestId": "req-20261103-9c02", "status": "pending_approval", "approval": {"requiredCount": 2, "count": 1, ...}}
#   the second eligible approval moves it to "approved" and the worker opens the bot PR

curl -s -X POST "$CMAPI/requests/req-20261103-9c02:reject" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"comment": "Use pod request tuning first; 14-day peak is 9.6 cores"}'
```

Email, chat and ServiceNow approvals all end in the same `:approve` call (email links open this request in the portal).

### 9. Retry or revert (operators)

```bash
curl -s -X POST "$CMAPI/requests/req-20261103-7f3a:retry"  -H "Authorization: Bearer $TOKEN"   # failed or sync_failed
curl -s -X POST "$CMAPI/requests/req-20261103-7f3a:revert" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"justification": "Sync failed on OCP_GF6; roll back"}'   # a new request, same approval rules
```

### 10. Expiration (non-prod only)

```bash
# Expiry of one namespace
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/clusters/OCP_GF6/namespaces/payments-rnd/expiration"
# → {"expiresAt": "2026-12-15", "state": "active", "daysLeft": 42, "lifetimeDaysUsed": 42, "maxLifetimeDays": 180,
#    "maxExtensionDays": 30, "notices": ["14d", "7d", "1d"], "graceDays": 7}

# Extend by up to 30 days (rnd and dev: no approval; qa and uat: 1)
curl -s -X POST "$CMAPI/clusters/OCP_GF6/namespaces/payments-rnd/expiration:extend" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -H "Idempotency-Key: $(uuidgen)" \
  -d '{"days": 30, "justification": "Integration tests run through January"}'

# Make permanent, or give a permanent non-prod namespace a date (beyond the limits: approver-platform approve)
curl -s -X POST "$CMAPI/clusters/OCP_GF6/namespaces/payments-rnd/expiration:makePermanent" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"justification": "Now the shared payments sandbox"}'
curl -s -X POST "$CMAPI/clusters/OCP_GF6/namespaces/ledger-rnd/expiration:set" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"until": "2027-01-31", "justification": "Project ends in January"}'

# Everything expiring in the next 14 days, or in grace (paged like /quotas)
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/expirations?state=expiring&within=14d"
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/expirations?state=grace"
```

At the date the namespace enters a 7-day grace: it keeps running and can still be extended. After grace, cmapi opens a delete request (auto-approved by the `expired-namespace` policy), and Argo CD waits for an operator to confirm the prune.

### 11. Kyverno policy results

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/policies?clusterId=OCP_GF6"                        # bundle tag running vs pinned, readiness
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/policies/results?clusterId=OCP_GF6&result=fail"    # failing resources in your scope (paged)
curl -s -H "Authorization: Bearer $TOKEN" "$CMAPI/policies/rejections?since=7d"                      # cmapi's own plan-time and CI refusals
```

---

## Responses

### Write accepted (`202`)

```json
{
  "requestId": "req-20261103-7f3a",
  "clusterId": "OCP_GF6",
  "plugin": "namespaces",
  "kind": "Namespace",
  "action": "create",
  "namespace": "payments-rnd",
  "status": "approved",
  "prUrl": null,
  "approval": {"rule": "rnd-create", "requiredCount": 0, "autoApproved": true, "autoPolicy": "baseline-rnd-namespace"},
  "links": {"self": "/api/v1/requests/req-20261103-7f3a"}
}
```

### Error (`application/problem+json`, RFC 9457)

```json
{
  "type": "https://cmapi.ephico2real.com/problems/policy-violation",
  "title": "Grant not allowed",
  "status": 422,
  "detail": "ClusterRole cluster-admin is not on the ServiceAccount allowlist",
  "clusterId": "OCP_GF6",
  "requestId": "req-20261103-7f3a",
  "errors": [{"field": "roleRef.name", "code": "not_allowlisted"}]
}
```

| Status | Problem type | Meaning | What to do |
| --- | --- | --- | --- |
| 401 | `unauthenticated` | Missing, expired or invalid token, or a token issued for another app | Get a new token from your cmapi client |
| 403 | `forbidden` | None of your Keycloak roles grants this action (for example `cmapi-onboarding` changing a namespace) | Ask to join the right `app-cmapi-rbac-*` LDAP group, or for the role on your account |
| 403 | `environment-forbidden` | Your role grants this action, but only in other environments | Use a role that covers the environment (`authz-roles.yaml`) |
| 404 | `cluster-not-found` / `object-not-found` | Unknown cluster or missing live object | |
| 409 | `change-pending` | An open request already targets this namespace | Wait for it, or cancel it with `POST /requests/{id}:cancel` |
| 409 | `namespace-exists-unmanaged` | At create: the namespace already exists on the cluster and cmapi does not manage it | Ask for adoption instead |
| 409 | `not-pending` / `self-approval` | `:approve` on a request not waiting for approval, or by someone who may not approve it | Check `GET /requests/{id}`; ask another eligible approver |
| 422 | `expiration-not-allowed` / `expiration-limit` | Expiry asked for in prod, or a single extension over 30 days (past 180 days in total is not refused: it is routed to approver-platform) | Leave it out in prod; extend in steps of 30 days or less |
| 412 / 428 | `precondition-failed` / `precondition-required` | Stale or missing `If-Match` | GET again for the current ETag |
| 422 | `validation-failed` / `policy-violation` / `capacity-exceeded` | Request rejected at plan time | Read `errors[].code`, e.g. `reserved_key`, `invalid-team-dl` |
| 422 | `invalid-namespace-name` / `reserved-namespace` | The name is not a DNS-1123 label of 2 to 63 characters, or is reserved | Pick another name |
| 429 | `rate-limited` | Too many calls, or too many active placements for your team | Honour `Retry-After` |
| 422 | `environment-not-served` | This instance does not serve that environment | Use the instance URL in the response's `instanceUrl` |
| 422 | `identity-incomplete` / `unknown-user` / `invalid-team-dl` | A person's token has no employee ID claim (automation accounts need none); `onBehalfOf` names nobody (or a disabled user); the team DL is not in one of the configured email domains | Sign in again or ask the platform team to check your directory entry; fix `onBehalfOf`; fix the DL |
| 422 | `tier-unknown` / `tier-not-offered` / `quota-with-named-tier` / `quota-key-not-sizable` / `custom-quota-required` / `custom-out-of-bounds` | The tier does not exist or is not offered in that environment; a quota sent with a named tier; a quota key other than requests.cpu, requests.memory or pods; a custom quota missing a key, or outside the bounds or off the step (each offending key is listed with its min, max and step) | Check `GET /tiers?environment=` and resend |
| 422 | `cluster-not-writable` | The cluster is imported but has no clusters.yaml entry yet | Wait for its cluster-onboard PR to merge |
| 503 | `cluster-unreachable` / `idp-unavailable` | Cluster API or Keycloak keys unreachable | Honour `Retry-After` |
| 503 | `capacity-service-unavailable` | cmapi-capacity is down; capacity and usage reads cannot be served | Honour `Retry-After`; creates still place from stored snapshots |
| 503 | `operations-engine-unavailable` | The configured operations engine is unreachable | Retry later; requests are unaffected |

A 401 also carries `WWW-Authenticate: Bearer error="invalid_token"`.
