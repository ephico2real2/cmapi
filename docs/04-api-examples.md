# cmapi: API examples

This document shows each operation of the cmapi API that is built, with a curl sample and a real request and response. The payloads are not written by hand. A run of the service suite recorded them, and the OpenAPI document holds the same ones, so Swagger UI at `/docs` and ReDoc at `/redoc` show what this document shows.

## How to read it

- **Where the payloads come from.** `cmapi/tests/service/test_api_samples.py` walks the API in one scenario on the test instance of the service suite: PostgreSQL 16, a fake Git host and a fake cluster named `CRC` in environment `dev`. It writes `cmapi/src/cmapi/contract/samples.json`. Recorded on macOS on 2026-11-13. No payload here is from CRC or from kind yet.
- **What differs on a real instance.** Request IDs, times, etags, cursors and hashes are those of that run. The host in each curl sample is the `publicUrl` of the test instance.
- **Tokens.** Each sample sends `Authorization: Bearer $TOKEN`. No token is in the samples. [`docs/15-keycloak-integration.md`](15-keycloak-integration.md) says how a caller gets a token, and [`docs/14-authorization.md`](14-authorization.md) says which role each permission needs.
- **Long lists.** A list in a response is cut to its first item, and a line under the block says so.

## Rules for each call

| Rule | Detail |
|---|---|
| The instance | Call the instance that serves the environment of the cluster. Another instance answers 422 `environment-not-served` |
| Writes | A write to a namespace returns 202 with a change request. The change reaches the cluster through a pull request after approval |
| `Idempotency-Key` | Necessary on each write to a namespace. The same key and caller get the first response again, for 24 hours. Without it the answer is 400 `idempotency-key-required`. The same key with a different request is 409 `idempotency-replay`. Make a new key for each new action (`$(uuidgen)` in a shell), and send the same key again only to retry that same call. The fixed keys in the samples below are examples, not values to copy. Clients that generate the key, so that a person never types one, are #282 |
| `If-Match` | Necessary on a change, a delete and an extension. Its value is the `etag` of `GET .../namespaces/{ns}`. Without it the answer is 428, and with an old value it is 412 |
| `?dryRun=true` | On a create or a change, it returns 200 with the plan and writes nothing |
| Errors | RFC 9457 problems, media type `application/problem+json`, with a `code` field. The last section lists the ones that the run met |

## To write this document again

After a change to the API, in `cmapi/`:

1. `CMAPI_WRITE_SAMPLES=1 PYTHONPATH=src:tests/service python -m pytest tests/service/test_api_samples.py -q -W ignore`
2. `CMAPI_WRITE_CONTRACT=1 PYTHONPATH=src:tests/service python -m pytest tests/service/test_api_docs.py -q -W ignore -k committed_contract`
3. `python ../scripts/api-examples-doc.py --write`

The CI job `api-contract` fails when the part below is not what `scripts/api-examples-doc.py` writes.

## Designed and not built

`docs/01` and `docs/02` specify more endpoints than the code has. These have no example here, because no code answers them yet: expirations (`GET /expirations`, `:set`, `:makePermanent`), the tier detail, quota writes other than the namespace `PATCH`, metadata, service accounts, grants, SCC grants, tokens, policies, cluster import, capacity and placement, adoption, reports, operations and the admin reload. `docs/08-code-status.md`, section 4, is the full list.

<!-- examples:begin -->
## Namespaces and metadata

The managed namespaces of a cluster: read them, and create, change, delete or extend one. Each write returns a change request and becomes a pull request after approval.

### Managed namespaces on a cluster

`GET /api/v1/clusters/{cluster_id}/namespaces`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/clusters/CRC/namespaces`.

The answer was 200 (`application/json`):

```json
{
  "items": [
    {
      "annotations": {
        "argocd.argoproj.io/sync-options": "Prune=confirm,ServerSideApply=true",
        "cmapi.net/instance": "nonprod",
        "cmapi.net/request-id": "req-20261115-0001",
        "cmapi.net/requested-by": "ola@ephico2real.com",
        "cmapi.net/team-dl": "payments-team@ephico2real.com"
      },
      "clusterId": "CRC",
      "env": "dev",
      "etag": null,
      "expiresAt": null,
      "labels": {
        "cmapi.net/cluster-id": "CRC",
        "cmapi.net/cost-center": "cc-4410",
        "cmapi.net/env": "dev",
        "cmapi.net/managed": "true",
        "cmapi.net/requested-by-user": "ola",
        "cmapi.net/team": "payments",
        "cmapi.net/tier": "small"
      },
      "managed": true,
      "name": "payments-dev",
      "openRequest": null,
      "team": "payments",
      "tier": "small"
    }
  ]
}
```

### Create a namespace

`POST /api/v1/clusters/{cluster_id}/namespaces`

Permission: `namespaces:create`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'Content-Type: application/json' -d '{"namespace": "payments-dev", "tier": "small", "limitRange": {"container": {"default": {"cpu": "1", "memory": "1Gi"}, "max": {"cpu": "4", "memory": "8Gi"}}}, "labels": {"cmapi.net/team": "payments"}, "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, "expiresAt": "2026-12-15", "justification": "Payments service dev namespace"}'
```

The run sent `POST /api/v1/clusters/CRC/namespaces` with this body:

```json
{
  "annotations": {
    "cmapi.net/team-dl": "payments-team@ephico2real.com"
  },
  "justification": "Payments service dev namespace",
  "labels": {
    "cmapi.net/cost-center": "cc-4410",
    "cmapi.net/team": "payments"
  },
  "namespace": "payments-dev",
  "tier": "small"
}
```

The answer was 202 (`application/json`):

```json
{
  "action": "create",
  "approval": {
    "approvals": [],
    "auto": "auto:baseline-rnd-namespace",
    "autoFallback": null,
    "reasons": [
      "dev create: 1 from approver-platform"
    ],
    "remaining": [],
    "rule": "dev-create",
    "selfApproval": true,
    "slots": [],
    "timeoutHours": 8
  },
  "baseSha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:43:56.484597Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:43:56.484597Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "auto:baseline-rnd-namespace",
      "status": "approved"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/token-issuer-rolebinding.yaml": "added"
  },
  "instance": "nonprod",
  "justification": "Payments service dev namespace",
  "links": {
    "events": "/api/v1/requests/req-20261115-0001/events",
    "self": "/api/v1/requests/req-20261115-0001"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "67e4aa6a94a2d2b67ec7e93ca431a95a111f7435209188e14f8d85fd6abd50f1",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261115-0001",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "approved",
  "updatedAt": "2026-11-15T07:43:56.328900Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.

The run sent `POST /api/v1/clusters/CRC/namespaces?dryRun=true` with this body:

```json
{
  "annotations": {
    "cmapi.net/team-dl": "payments-team@ephico2real.com"
  },
  "justification": "Payments service dev namespace",
  "labels": {
    "cmapi.net/cost-center": "cc-4410",
    "cmapi.net/team": "payments"
  },
  "limitRange": {
    "container": {
      "default": {
        "cpu": "1",
        "memory": "1Gi"
      },
      "max": {
        "cpu": "4",
        "memory": "8Gi"
      }
    }
  },
  "namespace": "payments-dev",
  "quota": {
    "pods": "20",
    "requests.cpu": "4",
    "requests.memory": "8Gi",
    "requests.storage": "500Gi"
  },
  "tier": "custom"
}
```

The answer was 200 (`application/json`):

```json
{
  "approval": {
    "approvals": [],
    "auto": null,
    "autoFallback": null,
    "reasons": [
      "dev create: 1 from approver-platform"
    ],
    "remaining": [
      {
        "group": "approver-platform",
        "needed": 2
      }
    ],
    "rule": "dev-create",
    "selfApproval": true,
    "slots": [
      {
        "count": 2,
        "group": "approver-platform",
        "reason": "dev create: 1 from approver-platform; Value beyond the tier"
      }
    ],
    "timeoutHours": 8
  },
  "beyondTier": {
    "approvals": [
      {
        "count": 1,
        "group": "approver-platform",
        "reason": "Value beyond the tier"
      }
    ],
    "keys": [
      {
        "key": "limitRange.container.default.cpu",
        "requested": "1",
        "tier": "500m"
      }
    ]
  },
  "capacity": {
    "bindingResource": "cpu",
    "clusterId": "CRC",
    "cpu": 0.031,
    "fresh": true,
    "memory": 0.025,
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/token-issuer-rolebinding.yaml": "added"
  },
  "etag": "0",
  "files": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: payments-dev-limits-cpu\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: custom\n  annotations:\n    cmapi.net/beyond-tier: limitRange.container.default.cpu,limitRange.container.max.cpu\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 77ae5f8f5ddd\nspec:\n  limits:\n  - type: Container\n    defaultRequest:\n      cpu: 100m\n    default:\n      cpu: '1'\n    max:\n      cpu: '4'\n",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: payments-dev-limits-memory\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: custom\n  annotations:\n    cmapi.net/beyond-tier: limitRange.container.default.memory,limitRange.container.max.memory\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 77ae5f8f5ddd\nspec:\n  limits:\n  - type: Container\n    defaultRequest:\n      memory: 256Mi\n    default:\n      memory: 1Gi\n    max:\n      memory: 8Gi\n",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: custom\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: payments-dev-quota\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: custom\n  annotations:\n    cmapi.net/beyond-tier: requests.storage\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 77ae5f8f5ddd\nspec:\n  hard:\n    requests.cpu: '4'\n    requests.memory: 8Gi\n    pods: '20'\n    persistentvolumeclaims: '20'\n    requests.storage: 500Gi\n    services.loadbalancers: '0'\n    services.nodeports: '0'\n",
    "clusters/CRC/namespaces/payments-dev/token-issuer-rolebinding.yaml": "apiVersion: rbac.authorization.k8s.io/v1\nkind: RoleBinding\nmetadata:\n  name: cmapi-token-issuer\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\nroleRef:\n  apiGroup: rbac.authorization.k8s.io\n  kind: ClusterRole\n  name: cmapi-token-issuer\nsubjects:\n- kind: ServiceAccount\n  name: cmapi-reader\n  namespace: cmapi-system\n"
  },
  "findings": [],
  "planHash": "581590b32816a9c0d6951dbf13ba41816b2bf074eeb6017bcbf8fc3557906a75",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  }
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.
`body.beyondTier.keys` has 5 items in the run. The first is shown.

### Delete a namespace

`DELETE /api/v1/clusters/{cluster_id}/namespaces/{ns}`

Permission: `namespaces:write`.

```bash
curl -X DELETE https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"'
```

The run sent `DELETE /api/v1/clusters/CRC/namespaces/search-dev`.

The answer was 202 (`application/json`):

```json
{
  "action": "delete",
  "approval": {
    "approvals": [],
    "auto": null,
    "autoFallback": null,
    "reasons": [
      "dev delete: 1 from approver-platform"
    ],
    "remaining": [
      {
        "group": "approver-platform",
        "needed": 1
      }
    ],
    "rule": "dev-delete",
    "selfApproval": true,
    "slots": [
      {
        "count": 1,
        "group": "approver-platform",
        "reason": "dev delete: 1 from approver-platform"
      }
    ],
    "timeoutHours": 8
  },
  "baseSha": "82ba150b3087ed60652a2c218ad25c6e060199f3",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:44:06.367895Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:44:06.367895Z",
      "by": "ola",
      "event": "plan_needs_approval",
      "note": "waiting for [('approver-platform', 1)]",
      "status": "pending_approval"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/search-dev/limitrange-search-dev-limits-cpu.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/limitrange-search-dev-limits-memory.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/namespace.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/resourcequota-search-dev-quota.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/token-issuer-rolebinding.yaml": "removed"
  },
  "instance": "nonprod",
  "justification": null,
  "links": {
    "events": "/api/v1/requests/req-20261115-0008/events",
    "self": "/api/v1/requests/req-20261115-0008"
  },
  "mergeSha": null,
  "namespace": "search-dev",
  "planHash": "c490196334dad591c3196aa59224d119861392145360aee1d428c93109235dbe",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261115-0008",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "pending_approval",
  "updatedAt": "2026-11-15T07:44:06.150997Z"
}
```

### One namespace, with its etag

`GET /api/v1/clusters/{cluster_id}/namespaces/{ns}`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/clusters/CRC/namespaces/payments-dev`.

The answer was 200 (`application/json`, `etag: "ba376f6abad40439"`):

```json
{
  "annotations": {
    "argocd.argoproj.io/sync-options": "Prune=confirm,ServerSideApply=true",
    "cmapi.net/instance": "nonprod",
    "cmapi.net/request-id": "req-20261115-0001",
    "cmapi.net/requested-by": "ola@ephico2real.com",
    "cmapi.net/team-dl": "payments-team@ephico2real.com"
  },
  "clusterId": "CRC",
  "env": "dev",
  "etag": "ba376f6abad40439",
  "expiresAt": null,
  "labels": {
    "cmapi.net/cluster-id": "CRC",
    "cmapi.net/cost-center": "cc-4410",
    "cmapi.net/env": "dev",
    "cmapi.net/managed": "true",
    "cmapi.net/requested-by-user": "ola",
    "cmapi.net/team": "payments",
    "cmapi.net/tier": "small"
  },
  "managed": true,
  "name": "payments-dev",
  "openRequest": null,
  "team": "payments",
  "tier": "small"
}
```

### Change a namespace

`PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}`

Permission: `namespaces:write`.

```bash
curl -X PATCH https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"' -H 'Content-Type: application/json' -d '{"tier": "large", "limitRange": {"container": {"default": {"cpu": "1", "memory": "1Gi"}, "max": {"cpu": "4", "memory": "8Gi"}}}, "labels": {"cmapi.net/cost-center": "cc-4410"}, "justification": "More capacity for the batch"}'
```

The run sent `PATCH /api/v1/clusters/CRC/namespaces/payments-dev` with this body:

```json
{
  "justification": "Load test next sprint",
  "tier": "large"
}
```

The answer was 202 (`application/json`):

```json
{
  "action": "update",
  "approval": {
    "approvals": [],
    "auto": null,
    "autoFallback": null,
    "reasons": [
      "dev change: 0 from approver-platform"
    ],
    "remaining": [
      {
        "group": "approver-platform",
        "needed": 1
      }
    ],
    "rule": "dev-change",
    "selfApproval": true,
    "slots": [
      {
        "count": 1,
        "group": "approver-platform",
        "reason": "quotaIncreasePct > 100"
      }
    ],
    "timeoutHours": 8
  },
  "baseSha": "4d7b43ccb7ce7b8511d89719e439c9fcaa81b90f",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:43:57.930101Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:43:57.930101Z",
      "by": "ola",
      "event": "plan_needs_approval",
      "note": "waiting for [('approver-platform', 1)]",
      "status": "pending_approval"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/token-issuer-rolebinding.yaml": "unchanged"
  },
  "instance": "nonprod",
  "justification": "Load test next sprint",
  "links": {
    "events": "/api/v1/requests/req-20261115-0002/events",
    "self": "/api/v1/requests/req-20261115-0002"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "0deac03847a7c4106c8ca8e8e4b076a66b667f77203be731a18c098cdbdd5bf7",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261115-0002",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "pending_approval",
  "updatedAt": "2026-11-15T07:43:57.795196Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.

The run sent `PATCH /api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true` with this body:

```json
{
  "justification": "A smaller size after the load test",
  "tier": "medium"
}
```

The answer was 200 (`application/json`):

```json
{
  "approval": {
    "approvals": [],
    "auto": "none-required",
    "autoFallback": null,
    "reasons": [
      "dev change: 0 from approver-platform"
    ],
    "remaining": [],
    "rule": "dev-change",
    "selfApproval": true,
    "slots": [],
    "timeoutHours": 8
  },
  "beyondTier": null,
  "capacity": {
    "bindingResource": "cpu",
    "clusterId": "CRC",
    "cpu": 0.125,
    "fresh": true,
    "memory": 0.1,
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "changed"
  },
  "etag": "ba376f6abad40439",
  "files": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: payments-dev-limits-cpu\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  limits:\n  - type: Container\n    defaultRequest:\n      cpu: 100m\n    default:\n      cpu: 500m\n    max:\n      cpu: '4'\n",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: payments-dev-limits-memory\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  limits:\n  - type: Container\n    defaultRequest:\n      memory: 256Mi\n    default:\n      memory: 512Mi\n    max:\n      memory: 8Gi\n",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: medium\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: payments-dev-quota\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  hard:\n    requests.cpu: '16'\n    requests.memory: 32Gi\n    pods: '100'\n    persistentvolumeclaims: '30'\n    requests.storage: 500Gi\n    services.loadbalancers: '0'\n    services.nodeports: '0'\n"
  },
  "findings": [],
  "planHash": "4af23397be8e03971c7000b0add56da998d56d67549798030c840e59f8568886",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  }
}
```

### Extend a namespace's expiry

`POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:extend`

Permission: `namespaces:write`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev/expiration:extend -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"' -H 'Content-Type: application/json' -d '{"days": 30, "until": "2026-12-15", "justification": "Another sprint"}'
```

The run sent `POST /api/v1/clusters/CRC/namespaces/sprint-dev/expiration:extend` with this body:

```json
{
  "days": 7,
  "justification": "Another sprint"
}
```

The answer was 202 (`application/json`):

```json
{
  "action": "update",
  "approval": {
    "approvals": [],
    "auto": "none-required",
    "autoFallback": null,
    "reasons": [
      "dev change: 0 from approver-platform"
    ],
    "remaining": [],
    "rule": "dev-change",
    "selfApproval": true,
    "slots": [],
    "timeoutHours": 8
  },
  "baseSha": "de59322b07e885c8087c40b679e9e6ab186890d7",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:44:00.838223Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:44:00.838223Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "none-required",
      "status": "approved"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/sprint-dev/limitrange-sprint-dev-limits-cpu.yaml": "unchanged",
    "clusters/CRC/namespaces/sprint-dev/limitrange-sprint-dev-limits-memory.yaml": "unchanged",
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "changed",
    "clusters/CRC/namespaces/sprint-dev/resourcequota-sprint-dev-quota.yaml": "unchanged",
    "clusters/CRC/namespaces/sprint-dev/token-issuer-rolebinding.yaml": "unchanged"
  },
  "instance": "nonprod",
  "justification": "Another sprint",
  "links": {
    "events": "/api/v1/requests/req-20261115-0004/events",
    "self": "/api/v1/requests/req-20261115-0004"
  },
  "mergeSha": null,
  "namespace": "sprint-dev",
  "planHash": "5dd3978000c9d35c39a369ed9ea9c739bd5893c26166c3db2953c05b4d734bbe",
  "plugin": "namespaces",
  "pr": null,
  "reason": "expiration:extend",
  "requestId": "req-20261115-0004",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "approved",
  "updatedAt": "2026-11-15T07:44:00.682820Z"
}
```

## Access

The people that Keycloak knows: a search for the people picker, and one person by username.

### Search people

`GET /api/v1/directory/users`

Permission: `objects:read`.

```bash
curl -X GET 'https://cmapi-nonprod.ephico2real.com/api/v1/directory/users?q=ada' -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/directory/users?q=ola`.

The answer was 200 (`application/json`):

```json
{
  "items": [
    {
      "email": "ola@ephico2real.com",
      "employeeId": null,
      "name": "Ola Adeyemi",
      "username": "ola"
    }
  ]
}
```

### One person

`GET /api/v1/directory/users/{username}`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/directory/users/cmapi.requester -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/directory/users/ola`.

The answer was 200 (`application/json`):

```json
{
  "email": "ola@ephico2real.com",
  "employeeId": null,
  "name": "Ola Adeyemi",
  "username": "ola"
}
```

## Capacity and placement

The quota of each managed namespace on every cluster of the instance: a paged list, type-ahead matches and a CSV export.

### Every namespace's quota, paged

`GET /api/v1/quotas`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/quotas -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/quotas?limit=25`.

The answer was 200 (`application/json`):

```json
{
  "facets": {
    "near-limit": 0,
    "open-request": 0,
    "tier-outdated": 0
  },
  "items": [
    {
      "app": null,
      "clusterId": "CRC",
      "cpu": [
        "0"
      ],
      "env": "dev",
      "expiresAt": null,
      "memory": [
        "0"
      ],
      "name": "payments-dev",
      "openRequest": null,
      "pods": [
        "0"
      ],
      "team": "payments",
      "tier": "small",
      "tierHash": "f192fb6ba493",
      "tierOutdated": false,
      "used": 0.0
    }
  ],
  "letters": {
    "P": 1
  },
  "page": {
    "from": 1,
    "limit": 25,
    "nextCursor": null,
    "prevCursor": null,
    "to": 1,
    "total": 1
  }
}
```

`body.items[0].cpu` has 2 items in the run. The first is shown.
`body.items[0].memory` has 2 items in the run. The first is shown.
`body.items[0].pods` has 2 items in the run. The first is shown.

### Export the quota list as CSV

`GET /api/v1/quotas:export`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/quotas:export -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/quotas:export`.

The answer was 200 (`text/csv`, `content-disposition: attachment; filename="quotas.csv"`):

```text
name,clusterId,env,team,tier,cpuUsed,cpuHard,memoryUsed,memoryHard,podsUsed,podsHard,used,expiresAt,tierOutdated
payments-dev,CRC,dev,payments,small,0,8,0,16Gi,0,50,0.0,,False
```

### Type-ahead matches

`GET /api/v1/quotas:suggest`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/quotas:suggest -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/quotas:suggest?q=pay`.

The answer was 200 (`application/json`):

```json
{
  "items": [
    {
      "clusterId": "CRC",
      "name": "payments-dev",
      "why": "name starts with"
    }
  ]
}
```

The tier catalog: the quota and LimitRange values that each environment offers.

### The tier catalog

`GET /api/v1/tiers`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/tiers -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/tiers?environment=dev`.

The answer was 200 (`application/json`):

```json
{
  "catalogHash": "1bc749aee0645c62",
  "environments": {
    "dev": {
      "custom": {
        "max": {
          "limitRange.container.default.cpu": "16",
          "limitRange.container.default.memory": "32Gi",
          "limitRange.container.defaultRequest.cpu": "16",
          "limitRange.container.defaultRequest.memory": "32Gi",
          "limitRange.container.max.cpu": "16",
          "limitRange.container.max.memory": "32Gi",
          "limitRange.pvc.max.storage": "500Gi",
          "persistentvolumeclaims": "100",
          "pods": "300",
          "requests.cpu": "32",
          "requests.memory": "64Gi",
          "requests.storage": "2Ti",
          "services.loadbalancers": "2",
          "services.nodeports": "10"
        },
        "min": {
          "pods": "10",
          "requests.cpu": "2",
          "requests.memory": "4Gi"
        },
        "step": {
          "pods": "10",
          "requests.cpu": "1",
          "requests.memory": "1Gi"
        }
      },
      "storageLimitRange": {
        "enabled": false
      },
      "tiers": [
        {
          "custom": false,
          "description": "A team sandbox or a single service",
          "hash": "f192fb6ba493",
          "limitRange": {
            "container": {
              "default": {
                "cpu": "500m",
                "memory": "512Mi"
              },
              "defaultRequest": {
                "cpu": "100m",
                "memory": "256Mi"
              },
              "max": {
                "cpu": "2",
                "memory": "4Gi"
              }
            }
          },
          "name": "small",
          "order": 1,
          "quota": {
            "persistentvolumeclaims": "20",
            "pods": "50",
            "requests.cpu": "8",
            "requests.memory": "16Gi",
            "requests.storage": "200Gi",
            "services.loadbalancers": "0",
            "services.nodeports": "0"
          }
        }
      ]
    }
  },
  "overridable": [
    "persistentvolumeclaims"
  ],
  "sizable": [
    "requests.cpu"
  ]
}
```

`body.environments.dev.tiers` has 4 items in the run. The first is shown.
`body.overridable` has 11 items in the run. The first is shown.
`body.sizable` has 3 items in the run. The first is shown.

## Requests and approvals

The change requests: each write to a namespace is one request, with its approvals, its pull request and its events. Approve, reject, cancel, retry or revert a request here.

### List requests

`GET /api/v1/requests`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/requests -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/requests?status=pending_approval&approver=me`.

The answer was 200 (`application/json`):

```json
{
  "items": [
    {
      "action": "update",
      "approval": {
        "approvals": [],
        "auto": null,
        "autoFallback": null,
        "reasons": [
          "dev change: 0 from approver-platform"
        ],
        "remaining": [
          {
            "group": "approver-platform",
            "needed": 1
          }
        ],
        "rule": "dev-change",
        "selfApproval": true,
        "slots": [
          {
            "count": 1,
            "group": "approver-platform",
            "reason": "quotaIncreasePct > 100"
          }
        ],
        "timeoutHours": 8
      },
      "baseSha": "4d7b43ccb7ce7b8511d89719e439c9fcaa81b90f",
      "beyondTier": null,
      "clusterId": "CRC",
      "createdAt": "2026-11-15T07:43:57.930101Z",
      "env": "dev",
      "events": [
        {
          "at": "2026-11-15T07:43:57.930101Z",
          "by": "ola",
          "event": "plan_needs_approval",
          "note": "waiting for [('approver-platform', 1)]",
          "status": "pending_approval"
        }
      ],
      "files": {
        "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "changed",
        "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "changed",
        "clusters/CRC/namespaces/payments-dev/namespace.yaml": "changed",
        "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "changed",
        "clusters/CRC/namespaces/payments-dev/token-issuer-rolebinding.yaml": "unchanged"
      },
      "instance": "nonprod",
      "justification": "Load test next sprint",
      "links": {
        "events": "/api/v1/requests/req-20261115-0002/events",
        "self": "/api/v1/requests/req-20261115-0002"
      },
      "mergeSha": null,
      "namespace": "payments-dev",
      "planHash": "0deac03847a7c4106c8ca8e8e4b076a66b667f77203be731a18c098cdbdd5bf7",
      "plugin": "namespaces",
      "pr": null,
      "reason": null,
      "requestId": "req-20261115-0002",
      "requester": {
        "automated": false,
        "requester": {
          "clientId": "cmapi-portal",
          "email": "ola@ephico2real.com",
          "employeeId": "1001",
          "familyName": "Doe",
          "givenName": "Ola",
          "kind": "user",
          "middleName": null,
          "sub": "sub-ola",
          "username": "ola"
        },
        "submittedBy": null,
        "submittedByClient": null
      },
      "status": "pending_approval",
      "updatedAt": "2026-11-15T07:43:57.795196Z"
    }
  ],
  "letters": {
    "R": 1
  },
  "page": {
    "from": 1,
    "limit": 50,
    "nextCursor": null,
    "prevCursor": null,
    "to": 1,
    "total": 1
  }
}
```

`body.items[0].approval.reasons` has 2 items in the run. The first is shown.

### One request

`GET /api/v1/requests/{request_id}`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001 -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/requests/req-20261115-0001`.

The answer was 200 (`application/json`):

```json
{
  "action": "create",
  "approval": {
    "approvals": [],
    "auto": "auto:baseline-rnd-namespace",
    "autoFallback": null,
    "reasons": [
      "dev create: 1 from approver-platform"
    ],
    "remaining": [],
    "rule": "dev-create",
    "selfApproval": true,
    "slots": [],
    "timeoutHours": 8
  },
  "baseSha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:43:56.484597Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:43:56.484597Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "auto:baseline-rnd-namespace",
      "status": "approved"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "added",
    "clusters/CRC/namespaces/payments-dev/token-issuer-rolebinding.yaml": "added"
  },
  "instance": "nonprod",
  "justification": "Payments service dev namespace",
  "links": {
    "events": "/api/v1/requests/req-20261115-0001/events",
    "pr": "https://git.test/pulls/1",
    "self": "/api/v1/requests/req-20261115-0001"
  },
  "mergeSha": "4d7b43cc",
  "namespace": "payments-dev",
  "planHash": "67e4aa6a94a2d2b67ec7e93ca431a95a111f7435209188e14f8d85fd6abd50f1",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261115-0001",
    "head": "4d7b43cc",
    "number": 1,
    "url": "https://git.test/pulls/1"
  },
  "reason": null,
  "requestId": "req-20261115-0001",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "synced",
  "updatedAt": "2026-11-15T07:43:56.664542Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.
`body.events` has 9 items in the run. The first is shown.

### Is this request approved, and for which plan

`GET /api/v1/requests/{request_id}/approval-status`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001/approval-status -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/requests/req-20261115-0001/approval-status`.

The answer was 200 (`application/json`):

```json
{
  "approved": true,
  "planHash": "67e4aa6a94a2d2b67ec7e93ca431a95a111f7435209188e14f8d85fd6abd50f1",
  "requestId": "req-20261115-0001",
  "status": "synced"
}
```

### A request's events

`GET /api/v1/requests/{request_id}/events`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001/events -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/requests/req-20261115-0001/events`.

The answer was 200 (`application/json`):

```json
{
  "events": [
    {
      "at": "2026-11-15T07:43:56.484597Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "auto:baseline-rnd-namespace",
      "status": "approved"
    }
  ],
  "requestId": "req-20261115-0001",
  "status": "synced"
}
```

`body.events` has 9 items in the run. The first is shown.

### Approve a request

`POST /api/v1/requests/{request_id}:approve`

Permission: `requests:approve`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:approve -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"comment": "sizing reviewed"}'
```

The run sent `POST /api/v1/requests/req-20261115-0002:approve` with this body:

```json
{
  "comment": "sizing reviewed"
}
```

The answer was 200 (`application/json`):

```json
{
  "action": "update",
  "approval": {
    "approvals": [
      {
        "at": "2026-11-15T07:43:58.221073Z",
        "comment": "sizing reviewed",
        "relayedBy": null,
        "sub": "sub-amy",
        "username": "amy"
      }
    ],
    "auto": null,
    "autoFallback": null,
    "reasons": [
      "dev change: 0 from approver-platform"
    ],
    "remaining": [],
    "rule": "dev-change",
    "selfApproval": true,
    "slots": [
      {
        "count": 1,
        "group": "approver-platform",
        "reason": "quotaIncreasePct > 100"
      }
    ],
    "timeoutHours": 8
  },
  "baseSha": "4d7b43ccb7ce7b8511d89719e439c9fcaa81b90f",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:43:57.930101Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:43:57.930101Z",
      "by": "ola",
      "event": "plan_needs_approval",
      "note": "waiting for [('approver-platform', 1)]",
      "status": "pending_approval"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/token-issuer-rolebinding.yaml": "unchanged"
  },
  "instance": "nonprod",
  "justification": "Load test next sprint",
  "links": {
    "events": "/api/v1/requests/req-20261115-0002/events",
    "self": "/api/v1/requests/req-20261115-0002"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "0deac03847a7c4106c8ca8e8e4b076a66b667f77203be731a18c098cdbdd5bf7",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261115-0002",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "approved",
  "updatedAt": "2026-11-15T07:43:58.031900Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.
`body.events` has 3 items in the run. The first is shown.

### Cancel a request

`POST /api/v1/requests/{request_id}:cancel`

Permission: `requests:cancel`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:cancel -H "Authorization: Bearer $TOKEN"
```

The run sent `POST /api/v1/requests/req-20261115-0005:cancel`.

The answer was 200 (`application/json`):

```json
{
  "action": "create",
  "approval": {
    "approvals": [],
    "auto": null,
    "autoFallback": null,
    "reasons": [
      "dev create: 1 from approver-platform"
    ],
    "remaining": [
      {
        "group": "approver-platform",
        "needed": 1
      }
    ],
    "rule": "dev-create",
    "selfApproval": true,
    "slots": [
      {
        "count": 1,
        "group": "approver-platform",
        "reason": "dev create: 1 from approver-platform"
      }
    ],
    "timeoutHours": 8
  },
  "baseSha": "9280f9d38e683a4ed1869001f61fffc5d9767bf8",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:44:02.092672Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:44:02.092672Z",
      "by": "ola",
      "event": "plan_needs_approval",
      "note": "waiting for [('approver-platform', 1)]",
      "status": "pending_approval"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/ledger-dev/limitrange-ledger-dev-limits-cpu.yaml": "added",
    "clusters/CRC/namespaces/ledger-dev/limitrange-ledger-dev-limits-memory.yaml": "added",
    "clusters/CRC/namespaces/ledger-dev/namespace.yaml": "added",
    "clusters/CRC/namespaces/ledger-dev/resourcequota-ledger-dev-quota.yaml": "added",
    "clusters/CRC/namespaces/ledger-dev/token-issuer-rolebinding.yaml": "added"
  },
  "instance": "nonprod",
  "justification": "Payments service dev namespace",
  "links": {
    "events": "/api/v1/requests/req-20261115-0005/events",
    "self": "/api/v1/requests/req-20261115-0005"
  },
  "mergeSha": null,
  "namespace": "ledger-dev",
  "planHash": "becab0c50021fc12d7098414e6e5b167185733eac37ba6d1ce141129cde5e527",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261115-0005",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "cancelled",
  "updatedAt": "2026-11-15T07:44:02.207988Z"
}
```

`body.events` has 2 items in the run. The first is shown.

### Reject a request

`POST /api/v1/requests/{request_id}:reject`

Permission: `requests:reject`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:reject -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"comment": "sizing reviewed"}'
```

The run sent `POST /api/v1/requests/req-20261115-0006:reject` with this body:

```json
{
  "comment": "Use the medium tier"
}
```

The answer was 200 (`application/json`):

```json
{
  "action": "create",
  "approval": {
    "approvals": [],
    "auto": null,
    "autoFallback": null,
    "reasons": [
      "dev create: 1 from approver-platform"
    ],
    "remaining": [
      {
        "group": "approver-platform",
        "needed": 1
      }
    ],
    "rule": "dev-create",
    "selfApproval": true,
    "slots": [
      {
        "count": 1,
        "group": "approver-platform",
        "reason": "dev create: 1 from approver-platform"
      }
    ],
    "timeoutHours": 8
  },
  "baseSha": "9280f9d38e683a4ed1869001f61fffc5d9767bf8",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:44:02.227417Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:44:02.227417Z",
      "by": "ola",
      "event": "plan_needs_approval",
      "note": "waiting for [('approver-platform', 1)]",
      "status": "pending_approval"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/billing-dev/limitrange-billing-dev-limits-cpu.yaml": "added",
    "clusters/CRC/namespaces/billing-dev/limitrange-billing-dev-limits-memory.yaml": "added",
    "clusters/CRC/namespaces/billing-dev/namespace.yaml": "added",
    "clusters/CRC/namespaces/billing-dev/resourcequota-billing-dev-quota.yaml": "added",
    "clusters/CRC/namespaces/billing-dev/token-issuer-rolebinding.yaml": "added"
  },
  "instance": "nonprod",
  "justification": "Payments service dev namespace",
  "links": {
    "events": "/api/v1/requests/req-20261115-0006/events",
    "self": "/api/v1/requests/req-20261115-0006"
  },
  "mergeSha": null,
  "namespace": "billing-dev",
  "planHash": "09182149e0f335653ad133729c867cd09964ea3a026b2a137ae7edbd691d6902",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261115-0006",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "rejected",
  "updatedAt": "2026-11-15T07:44:02.118886Z"
}
```

`body.events` has 2 items in the run. The first is shown.

### Retry a failed request

`POST /api/v1/requests/{request_id}:retry`

Permission: `requests:retry`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:retry -H "Authorization: Bearer $TOKEN"
```

The run sent `POST /api/v1/requests/req-20261115-0007:retry`.

The answer was 200 (`application/json`):

```json
{
  "action": "create",
  "approval": {
    "approvals": [],
    "auto": "auto:baseline-rnd-namespace",
    "autoFallback": null,
    "reasons": [
      "dev create: 1 from approver-platform"
    ],
    "remaining": [],
    "rule": "dev-create",
    "selfApproval": true,
    "slots": [],
    "timeoutHours": 8
  },
  "baseSha": "9280f9d38e683a4ed1869001f61fffc5d9767bf8",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:44:03.745995Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:44:03.745995Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "auto:baseline-rnd-namespace",
      "status": "approved"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/search-dev/limitrange-search-dev-limits-cpu.yaml": "added",
    "clusters/CRC/namespaces/search-dev/limitrange-search-dev-limits-memory.yaml": "added",
    "clusters/CRC/namespaces/search-dev/namespace.yaml": "added",
    "clusters/CRC/namespaces/search-dev/resourcequota-search-dev-quota.yaml": "added",
    "clusters/CRC/namespaces/search-dev/token-issuer-rolebinding.yaml": "added"
  },
  "instance": "nonprod",
  "justification": "Payments service dev namespace",
  "links": {
    "events": "/api/v1/requests/req-20261115-0007/events",
    "pr": "https://git.test/pulls/5",
    "self": "/api/v1/requests/req-20261115-0007"
  },
  "mergeSha": null,
  "namespace": "search-dev",
  "planHash": "2b15c23057ac2c54a40d308d3d0688aaf45f10a12b9c90d2c33beeaf9f16a0d0",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261115-0007",
    "head": "82ba150b",
    "number": 5,
    "url": "https://git.test/pulls/5"
  },
  "reason": null,
  "requestId": "req-20261115-0007",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "approved",
  "updatedAt": "2026-11-15T07:44:04.956717Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.
`body.events` has 9 items in the run. The first is shown.

### Revert a sync-failed request

`POST /api/v1/requests/{request_id}:revert`

Permission: `requests:retry`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:revert -H "Authorization: Bearer $TOKEN"
```

The run sent `POST /api/v1/requests/req-20261115-0009:revert`.

The answer was 200 (`application/json`):

```json
{
  "action": "create",
  "approval": {
    "approvals": [],
    "auto": "auto:baseline-rnd-namespace",
    "autoFallback": null,
    "reasons": [
      "dev create: 1 from approver-platform"
    ],
    "remaining": [],
    "rule": "dev-create",
    "selfApproval": true,
    "slots": [],
    "timeoutHours": 8
  },
  "baseSha": "9280f9d38e683a4ed1869001f61fffc5d9767bf8",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:44:08.599042Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:44:08.599042Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "auto:baseline-rnd-namespace",
      "status": "approved"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/orders-dev/limitrange-orders-dev-limits-cpu.yaml": "added",
    "clusters/CRC/namespaces/orders-dev/limitrange-orders-dev-limits-memory.yaml": "added",
    "clusters/CRC/namespaces/orders-dev/namespace.yaml": "added",
    "clusters/CRC/namespaces/orders-dev/resourcequota-orders-dev-quota.yaml": "added",
    "clusters/CRC/namespaces/orders-dev/token-issuer-rolebinding.yaml": "added"
  },
  "instance": "nonprod",
  "justification": "Payments service dev namespace",
  "links": {
    "events": "/api/v1/requests/req-20261115-0009/events",
    "pr": "https://git.test/pulls/8",
    "self": "/api/v1/requests/req-20261115-0009"
  },
  "mergeSha": "ee61a06d",
  "namespace": "orders-dev",
  "planHash": "b779a35afff12cc2186de72ecd26185e8a0b4d9cf2a7ec6f8f35505d74068322",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261115-0009",
    "head": "ee61a06d",
    "number": 8,
    "url": "https://git.test/pulls/8"
  },
  "reason": null,
  "requestId": "req-20261115-0009",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "sync_failed",
  "updatedAt": "2026-11-15T07:44:08.896620Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.
`body.events` has 8 items in the run. The first is shown.

## Operations

The instance itself: who the caller is and what the caller can do, the clusters that the instance knows, and the version of the running build.

### Clusters this instance knows

`GET /api/v1/clusters`

Permission: `clusters:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/clusters -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/clusters`.

The answer was 200 (`application/json`):

```json
{
  "items": [
    {
      "checkedAt": "2026-11-15T07:43:55.411398Z",
      "clusterId": "CRC",
      "environment": "dev",
      "findings": [],
      "gitopsPath": "clusters/CRC",
      "labels": {
        "region": "us-central"
      },
      "serverVersion": "v1.35.6-fake",
      "status": "connected",
      "writes": true
    }
  ]
}
```

### Who am I

`GET /api/v1/me`

Permission: none. A valid token is necessary.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/me -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/me`.

The answer was 200 (`application/json`):

```json
{
  "access": {
    "permissions": [
      "capacity:read"
    ],
    "roles": [
      {
        "environments": "all",
        "permissions": [
          "capacity:read"
        ],
        "role": "cmapi-requester"
      }
    ]
  },
  "client": "cmapi-portal",
  "groups": [
    "/cmapi/app-cmapi-rbac-requester"
  ],
  "identity": {
    "clientId": "cmapi-portal",
    "email": "ola@ephico2real.com",
    "employeeId": "1001",
    "familyName": "Doe",
    "givenName": "Ola",
    "kind": "user",
    "middleName": null,
    "sub": "sub-ola",
    "username": "ola"
  },
  "instance": "nonprod",
  "kind": "user",
  "roles": [
    "cmapi-requester"
  ],
  "username": "ola"
}
```

`body.access.permissions` has 10 items in the run. The first is shown.
`body.access.roles[0].permissions` has 10 items in the run. The first is shown.

### Version and commit of the running build

`GET /api/v1/version`

Permission: none, and no token.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/version
```

The run sent `GET /api/v1/version`.

The answer was 200 (`application/json`):

```json
{
  "commit": "unknown",
  "component": "api",
  "version": "0.2.0"
}
```

## Admin

What an operator of the instance uses: the auto-approval switch, the prune confirmation, the integration modes, the plugins, the Git log and the system KPIs.

### Auto-approval switch state

`GET /api/v1/admin/auto-approval`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/admin/auto-approval -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/admin/auto-approval`.

The answer was 200 (`application/json`):

```json
{
  "paused": false,
  "reason": null,
  "setAt": null,
  "setBy": null
}
```

### Pause auto-approval

`POST /api/v1/admin/auto-approval:pause`

Permission: `approvals:pause`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/admin/auto-approval:pause -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"reason": "incident 1234"}'
```

The run sent `POST /api/v1/admin/auto-approval:pause` with this body:

```json
{
  "reason": "incident 1234"
}
```

The answer was 200 (`application/json`):

```json
{
  "paused": true,
  "reason": "incident 1234",
  "setAt": "2026-11-15T07:44:02.514933+00:00",
  "setBy": "ada"
}
```

### Resume auto-approval

`POST /api/v1/admin/auto-approval:resume`

Permission: `approvals:pause`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/admin/auto-approval:resume -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"reason": "incident 1234"}'
```

The run sent `POST /api/v1/admin/auto-approval:resume` with this body:

```json
{
  "reason": "incident 1234 closed"
}
```

The answer was 200 (`application/json`):

```json
{
  "paused": false,
  "reason": "incident 1234 closed",
  "setAt": "2026-11-15T07:44:02.374003+00:00",
  "setBy": "ada"
}
```

### Recent commits in cluster-configs

`GET /api/v1/admin/git-log`

Permission: `reports:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/admin/git-log -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/admin/git-log`.

The answer was 200 (`application/json`):

```json
{
  "log": [
    "4d7b43cc Merge cmapi/CRC/req-20261115-0001"
  ]
}
```

`body.log` has 2 items in the run. The first is shown.

### Integration modes and health

`GET /api/v1/admin/integrations`

Permission: `clusters:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/admin/integrations -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/admin/integrations`.

The answer was 200 (`application/json`):

```json
{
  "clusters": {
    "CRC": "connected"
  },
  "delivery": {
    "mode": "apply",
    "pollSeconds": 1,
    "syncTimeoutSeconds": 30
  },
  "events": {
    "publisher": "none"
  },
  "operations": {
    "engine": "builtin"
  },
  "policy": {
    "engine": "kyverno",
    "environments": {
      "dev": "enforce",
      "rnd": "enforce"
    },
    "kyvernoVersion": null
  },
  "syncSignal": {
    "default": "poll",
    "pollInterval": "1s"
  }
}
```

### System KPIs

`GET /api/v1/admin/kpi`

Permission: `reports:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/admin/kpi -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/admin/kpi`.

The answer was 200 (`application/json`):

```json
{
  "components": [
    {
      "component": "api",
      "cpuLimitCores": null,
      "cpuPeriods": null,
      "cpuThrottledPeriods": null,
      "cpuThrottledSeconds": null,
      "cpuUsageSeconds": null,
      "measuredAt": 1794728637.4616761,
      "memoryBytes": null,
      "memoryLimitBytes": null
    }
  ],
  "database": {
    "connections": 9,
    "connectionsMax": 100,
    "oldestTransactionSeconds": 0.0,
    "poolInUse": 0,
    "poolSize": 5,
    "sizeBytes": 10304535,
    "walBytes": 83886080
  },
  "instance": "nonprod",
  "kpis": [
    {
      "id": "lead-time-auto-p90",
      "name": "Lead time, auto-approved (p90)",
      "source": "database: submit to synced, requests that a policy approved",
      "target": "under 10 min",
      "targetStatus": "proposed",
      "unit": "seconds",
      "value": 0.176743
    }
  ],
  "thresholds": {
    "backupMaxAgeHours": 26.0,
    "cpuPercent": 80.0,
    "dbConnectionsPercent": 80.0,
    "dbVolumePercent": 80.0,
    "memoryPercent": 80.0,
    "throttledPercent": 1.0
  },
  "unavailable": "a null value means not measured, never zero"
}
```

`body.kpis` has 7 items in the run. The first is shown.

### The plugins of this instance

`GET /api/v1/admin/plugins`

Permission: `clusters:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/admin/plugins -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/admin/plugins`.

The answer was 200 (`application/json`):

```json
{
  "configured": false,
  "instance": "nonprod",
  "items": [
    {
      "core": true,
      "disabledEnvironments": [],
      "enabled": true,
      "name": "admin",
      "version": "0.2.0"
    }
  ]
}
```

`body.items` has 7 items in the run. The first is shown.

### Confirm the prune of a deleted namespace

`POST /api/v1/admin/prune:confirm`

Permission: `operations:run`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/admin/prune:confirm -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"namespace": "payments-dev", "clusterId": "CRC"}'
```

The run sent `POST /api/v1/admin/prune:confirm` with this body:

```json
{
  "clusterId": "CRC",
  "namespace": "search-dev"
}
```

The answer was 200 (`application/json`):

```json
{
  "action": "delete",
  "approval": {
    "approvals": [
      {
        "at": "2026-11-15T07:44:06.456781Z",
        "comment": "",
        "relayedBy": null,
        "sub": "sub-amy",
        "username": "amy"
      }
    ],
    "auto": null,
    "autoFallback": null,
    "reasons": [
      "dev delete: 1 from approver-platform"
    ],
    "remaining": [],
    "rule": "dev-delete",
    "selfApproval": true,
    "slots": [
      {
        "count": 1,
        "group": "approver-platform",
        "reason": "dev delete: 1 from approver-platform"
      }
    ],
    "timeoutHours": 8
  },
  "baseSha": "82ba150b3087ed60652a2c218ad25c6e060199f3",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-15T07:44:06.367895Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-15T07:44:06.367895Z",
      "by": "ola",
      "event": "plan_needs_approval",
      "note": "waiting for [('approver-platform', 1)]",
      "status": "pending_approval"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/search-dev/limitrange-search-dev-limits-cpu.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/limitrange-search-dev-limits-memory.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/namespace.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/resourcequota-search-dev-quota.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/token-issuer-rolebinding.yaml": "removed"
  },
  "instance": "nonprod",
  "justification": null,
  "links": {
    "events": "/api/v1/requests/req-20261115-0008/events",
    "pr": "https://git.test/pulls/7",
    "self": "/api/v1/requests/req-20261115-0008"
  },
  "mergeSha": "9280f9d3",
  "namespace": "search-dev",
  "planHash": "c490196334dad591c3196aa59224d119861392145360aee1d428c93109235dbe",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261115-0008",
    "head": "9280f9d3",
    "number": 7,
    "url": "https://git.test/pulls/7"
  },
  "reason": null,
  "requestId": "req-20261115-0008",
  "requester": {
    "automated": false,
    "requester": {
      "clientId": "cmapi-portal",
      "email": "ola@ephico2real.com",
      "employeeId": "1001",
      "familyName": "Doe",
      "givenName": "Ola",
      "kind": "user",
      "middleName": null,
      "sub": "sub-ola",
      "username": "ola"
    },
    "submittedBy": null,
    "submittedByClient": null
  },
  "status": "awaiting_prune",
  "updatedAt": "2026-11-15T07:44:07.256613Z"
}
```

`body.events` has 10 items in the run. The first is shown.

## Problems

Each refusal is an RFC 9457 problem with the media type `application/problem+json`. These are the ones that the run met.

### 403 `forbidden`

`POST /api/v1/admin/auto-approval:pause`, with a body:

```json
{
  "code": "forbidden",
  "detail": "Missing permission approvals:pause: no role in your token grants it (roles: ['cmapi-requester'])",
  "status": 403,
  "title": "forbidden",
  "type": "https://cmapi.ephico2real.com/problems/forbidden"
}
```

### 400 `idempotency-key-required`

`POST /api/v1/clusters/CRC/namespaces`, with a body:

```json
{
  "code": "idempotency-key-required",
  "detail": "Idempotency-Key header is required on writes",
  "status": 400,
  "title": "idempotency key required",
  "type": "https://cmapi.ephico2real.com/problems/idempotency-key-required"
}
```

### 400 `invalid-sort`

`GET /api/v1/quotas?sort=nope`:

```json
{
  "code": "invalid-sort",
  "detail": "Unknown sort nope",
  "status": 400,
  "title": "invalid sort",
  "type": "https://cmapi.ephico2real.com/problems/invalid-sort"
}
```

### 409 `invalid-transition`

`POST /api/v1/requests/req-20261115-0007:revert`:

```json
{
  "code": "invalid-transition",
  "detail": "revert is not allowed in state synced",
  "state": "synced",
  "status": 409,
  "title": "invalid transition",
  "type": "https://cmapi.ephico2real.com/problems/invalid-transition"
}
```

### 409 `namespace-exists`

`POST /api/v1/clusters/CRC/namespaces`, with a body:

```json
{
  "code": "namespace-exists",
  "detail": "payments-dev is already in Git",
  "status": 409,
  "title": "namespace exists",
  "type": "https://cmapi.ephico2real.com/problems/namespace-exists"
}
```

### 404 `object-not-found`

`GET /api/v1/requests/req-00000000-0000`:

```json
{
  "code": "object-not-found",
  "detail": "No request req-00000000-0000",
  "status": 404,
  "title": "object not found",
  "type": "https://cmapi.ephico2real.com/problems/object-not-found"
}
```

### 412 `precondition-failed`

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev`, with a body:

```json
{
  "code": "precondition-failed",
  "detail": "The namespace changed in Git since you read it",
  "etag": "ba376f6abad40439",
  "status": 412,
  "title": "precondition failed",
  "type": "https://cmapi.ephico2real.com/problems/precondition-failed"
}
```

### 428 `precondition-required`

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev`, with a body:

```json
{
  "code": "precondition-required",
  "detail": "If-Match is required on a change; GET the namespace for its etag",
  "status": 428,
  "title": "precondition required",
  "type": "https://cmapi.ephico2real.com/problems/precondition-required"
}
```

### 422 `reserved-namespace`

`POST /api/v1/clusters/CRC/namespaces`, with a body:

```json
{
  "code": "reserved-namespace",
  "detail": "kube-tools is reserved (kube-*)",
  "pattern": "kube-*",
  "status": 422,
  "title": "reserved namespace",
  "type": "https://cmapi.ephico2real.com/problems/reserved-namespace"
}
```

### 401 `unauthenticated`

`GET /api/v1/me`, with no token:

```json
{
  "code": "unauthenticated",
  "detail": "Bearer token required",
  "status": 401,
  "title": "unauthenticated",
  "type": "https://cmapi.ephico2real.com/problems/unauthenticated"
}
```
<!-- examples:end -->
