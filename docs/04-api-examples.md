# cmapi: API examples

This document shows each operation of the cmapi API that is built, with a curl sample and a real request and response. The payloads are not written by hand. A run of the service suite recorded them, and the OpenAPI document holds the same ones, so Swagger UI at `/docs` and ReDoc at `/redoc` show what this document shows.

## How to read it

- **Where the payloads come from.** `cmapi/tests/service/test_api_samples.py` walks the API in one scenario on the test instance of the service suite: PostgreSQL 16, a fake Git host and a fake cluster named `CRC` in environment `dev`, with a fake Kyverno report and a fake Node for the Policies and Capacity calls. It writes `cmapi/src/cmapi/contract/samples.json`, whose last commit is of 2026-11-17. Every operation of `cmapi/contract/openapi.json` has a recorded call, and the same test fails when one has none (`test_each_operation_has_a_sample_from_a_run`). No payload here is from CRC or from kind.
- **What differs on a real instance.** Request IDs, times, etags, cursors and hashes are those of that run. The host in each curl sample is the `publicUrl` of the test instance.
- **Tokens.** Each sample sends `Authorization: Bearer $TOKEN`. No token is in the samples. [`docs/15-keycloak-integration.md`](15-keycloak-integration.md) says how a caller gets a token, and [`docs/14-authorization.md`](14-authorization.md) says which role each permission needs.
- **Long lists.** A list in a response is cut to its first item, and a line under the block says so.

## Rules for each call

| Rule | Detail |
|---|---|
| The instance | Call the instance that serves the environment of the cluster. Another instance answers 422 `environment-not-served` |
| Writes | A write to a namespace returns 202 with a change request. The change reaches the cluster through a pull request after approval |
| `Idempotency-Key` | Necessary on each write to a namespace, at most 100 characters, and not read on a `?dryRun=true` call (`plugins/namespaces/router.py`, `_idem`). The same key and caller get the first response again, for 24 hours. Without it the answer is 400 `idempotency-key-required`. The same key with a different request is 409 `idempotency-replay`. Make a new key for each new action (`$(uuidgen)` in a shell), and send the same key again only to retry that same call. The fixed keys in the samples below are examples, not values to copy. Clients that generate the key, so that a person never types one, are #282 |
| `If-Match` | Necessary on a change, a delete, an extension, a new expiry date and the removal of the expiry (`:extend`, `:set`, `:makePermanent`). Its value is the `etag` of `GET .../namespaces/{ns}`. Without it the answer is 428, and with an old value it is 412 |
| `?dryRun=true` | On a create, a change and each of the three expiry calls, it returns 200 with the plan and writes nothing. A delete has no dry run |
| Protected namespaces | A delete of a namespace whose labels in Git match `protected.labels` of `approval-rules.yaml` is 422 `namespace-protected`. `GET .../namespaces/{ns}` shows `protected` and `protectedBy` (`core/approvals.py`, `decide`; `core/models.py`) |
| Errors | RFC 9457 problems, media type `application/problem+json`, with a `code` field. The last section lists the ones that the run met |

## To write this document again

After a change to the API, in `cmapi/`:

1. `CMAPI_WRITE_SAMPLES=1 PYTHONPATH=src:tests/service python -m pytest tests/service/test_api_samples.py -q -W ignore`
2. `CMAPI_WRITE_CONTRACT=1 PYTHONPATH=src:tests/service python -m pytest tests/service/test_api_docs.py -q -W ignore -k committed_contract`
3. `python ../scripts/api-examples-doc.py --write`

The CI job `api-contract` fails when the part below is not what `scripts/api-examples-doc.py` writes.

## Designed and not built

`docs/02` specifies more endpoints than the code has. These have no example here, because `cmapi/contract/openapi.json` has no operation for them. The list is the paths of `docs/01` and `docs/02` that the OpenAPI document lacks, compared on 2026-11-18:

- Namespaces: `GET .../namespaces/{ns}/expiration`, `.../quota` writes, `.../limitrange`, `.../usage`, `.../analysis`, `.../drift`, namespace and service-account metadata, service accounts with their grants, SCC grants and tokens, `:promote`, and adoption (`/adoption/candidates`, `/adoption/skipped`, `:adopt`, `/adoption:scan`). The built namespace calls are the list, create, read, change, delete and `:extend`, `:set` and `:makePermanent`.
- Clusters: `GET /clusters/{id}`, `GET` and `/health` on the cluster path, `/clusters/{id}:probe`, `/admin/clusters:propose`, `/sync`, the analysis routes with `/analysis/sweeps:run`, and `/analysis/summary`. Cluster import has no endpoint: it is done with Secrets (`docs/18-configuration.md`).
- Live RBAC and identity reads: `.../namespaces/{ns}/roles` and `/rolebindings`, `/clusterroles`, `/clusterrolebindings`, `/sccs`, `/users`, `/users/{name}` with its bindings, and `/groups`, `/groups/{name}` with its bindings.
- Tiers: `GET /tiers/{tier}` and `/tiers/{tier}/namespaces`. Only `GET /tiers` is built.
- Capacity: `/capacity:check`, `/capacity:place`, `/capacity/forecast`, `/capacity/history`, `/clusters/{id}/capacity`, its history and `snapshots:run`. Only `GET /capacity` is built.
- Policies: `GET /policies`. Only `GET /policies/results` and `GET /policies/rejections` are built.
- Reports (`/reports/*`), operations (`/operations`, `/operations/{id}`, `:cancel`), `/changesets`, the webhooks (`/webhooks/git`, `/webhooks/argocd`) and `POST /admin/reload`.

The routes `/healthz`, `/readyz`, `/problems`, `/problems/{code}`, `/openapi.json`, `/openapi.yaml`, `/docs`, `/docs/oauth2-redirect`, `/docs/redoc-start.js`, `/redoc` and `/docs/changelog`, and the files under `/static/swagger` and `/static/redoc`, are built and have no example, because they are not in the OpenAPI document (`include_in_schema=False` in `cmapi/main.py` and `routers/health.py`; the static files are mounts). `docs/08-code-status.md`, section 4, lists the same gaps and may lag the code.

<!-- examples:begin -->
## Namespaces and metadata

The managed namespaces by expiry: a paged list of each namespace that can expire, with its date, the days left and its state. A date is changed with :extend, :set or :makePermanent of the namespaces plugin.

### Namespaces by expiry, paged

`GET /api/v1/expirations`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/expirations -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/expirations?limit=25`.

The answer was 200 (`application/json`):

```json
{
  "facets": {
    "active": 2,
    "attention": 0,
    "expiring": 0,
    "grace": 0,
    "pending_delete": 0,
    "permanent": 1
  },
  "items": [
    {
      "app": null,
      "clusterId": "CRC",
      "created": "2026-11-20",
      "daysLeft": 21,
      "env": "dev",
      "expiresAt": "2026-12-11",
      "graceEnds": "2026-12-18",
      "lifetimeDays": 21,
      "name": "notes-dev",
      "noticesSent": 0,
      "openRequest": null,
      "state": "active",
      "team": "payments"
    }
  ],
  "letters": {
    "N": 1,
    "P": 1,
    "S": 1
  },
  "page": {
    "from": 1,
    "limit": 25,
    "nextCursor": null,
    "prevCursor": null,
    "to": 3,
    "total": 3
  },
  "rules": {
    "dev": {
      "graceDays": 7,
      "maxExtensionDays": 30,
      "maxLifetimeDays": 180,
      "notifyDaysBefore": [
        14
      ]
    }
  },
  "today": "2026-11-20"
}
```

`body.items` has 3 items in the run. The first is shown.
`body.rules.dev.notifyDaysBefore` has 3 items in the run. The first is shown.

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
        "cmapi.net/request-id": "req-20261120-0001",
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
      "protected": null,
      "protectedBy": null,
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
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'Content-Type: application/json' -d '{"annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, "justification": "Payments service dev namespace", "labels": {"cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410"}, "namespace": "payments-dev", "tier": "small"}'
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
  "createdAt": "2026-11-20T10:32:55.981438Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:32:55.981438Z",
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
    "events": "/api/v1/requests/req-20261120-0001/events",
    "self": "/api/v1/requests/req-20261120-0001"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "85687a3dac629df64bb5e1d70ed160017edc50c1d4e279932600b1699c87ce39",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261120-0001",
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
  "updatedAt": "2026-11-20T10:32:55.975881Z"
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
  "metadata": {
    "annotations": {
      "cmapi.net/team-dl": {
        "source": "request",
        "value": "payments-team@ephico2real.com"
      }
    },
    "labels": {
      "cmapi.net/cost-center": {
        "source": "request",
        "value": "cc-4410"
      },
      "cmapi.net/team": {
        "source": "request",
        "value": "payments"
      }
    },
    "namespace": "payments-dev"
  },
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
  "baseSha": "42c28d55db885b61d2f81efe3a4655f69e366bbd",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:33:06.118570Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:33:06.118570Z",
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
    "events": "/api/v1/requests/req-20261120-0008/events",
    "self": "/api/v1/requests/req-20261120-0008"
  },
  "mergeSha": null,
  "namespace": "search-dev",
  "planHash": "c490196334dad591c3196aa59224d119861392145360aee1d428c93109235dbe",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261120-0008",
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
  "updatedAt": "2026-11-20T10:33:06.063078Z"
}
```

### One namespace, with its etag

`GET /api/v1/clusters/{cluster_id}/namespaces/{ns}`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/clusters/CRC/namespaces/payments-dev`.

The answer was 200 (`application/json`, `etag: "8b67bd76ddf33c88"`):

```json
{
  "annotations": {
    "argocd.argoproj.io/sync-options": "Prune=confirm,ServerSideApply=true",
    "cmapi.net/instance": "nonprod",
    "cmapi.net/request-id": "req-20261120-0001",
    "cmapi.net/requested-by": "ola@ephico2real.com",
    "cmapi.net/team-dl": "payments-team@ephico2real.com"
  },
  "clusterId": "CRC",
  "env": "dev",
  "etag": "8b67bd76ddf33c88",
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
  "protected": false,
  "protectedBy": [],
  "team": "payments",
  "tier": "small"
}
```

### Change a namespace

`PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}`

Permission: `namespaces:write`.

```bash
curl -X PATCH https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"' -H 'Content-Type: application/json' -d '{"justification": "Load test next sprint", "tier": "large"}'
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
  "baseSha": "d059a3d1e7a668d048e58f375ea118c148edbfd4",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:32:57.274605Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:32:57.274605Z",
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
    "events": "/api/v1/requests/req-20261120-0002/events",
    "self": "/api/v1/requests/req-20261120-0002"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "1b58de9851fc4154e07788456440a964be88c7352d3c5bbe1c6d7253c520ba26",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261120-0002",
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
  "updatedAt": "2026-11-20T10:32:57.282611Z"
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
  "etag": "8b67bd76ddf33c88",
  "files": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: payments-dev-limits-cpu\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  limits:\n  - type: Container\n    defaultRequest:\n      cpu: 100m\n    default:\n      cpu: 500m\n    max:\n      cpu: '4'\n",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: payments-dev-limits-memory\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  limits:\n  - type: Container\n    defaultRequest:\n      memory: 256Mi\n    default:\n      memory: 512Mi\n    max:\n      memory: 8Gi\n",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: medium\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: payments-dev-quota\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  hard:\n    requests.cpu: '16'\n    requests.memory: 32Gi\n    pods: '100'\n    persistentvolumeclaims: '30'\n    requests.storage: 500Gi\n    services.loadbalancers: '0'\n    services.nodeports: '0'\n"
  },
  "findings": [],
  "metadata": null,
  "planHash": "291c3bf12937a5d058e63b514c2088ec74b1b6cc1c3ac45fdcebc08c68a06557",
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
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev/expiration:extend -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"' -H 'Content-Type: application/json' -d '{"days": 7, "justification": "Another sprint"}'
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
  "baseSha": "653097d85729c316d41bbf5d82a0b66c07c89fc0",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:32:59.870601Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:32:59.870601Z",
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
    "events": "/api/v1/requests/req-20261120-0004/events",
    "self": "/api/v1/requests/req-20261120-0004"
  },
  "mergeSha": null,
  "namespace": "sprint-dev",
  "planHash": "93ce8018fdde89ade0715c760f2d24a0031593713613f70526054b678d62c84d",
  "plugin": "namespaces",
  "pr": null,
  "reason": "expiration:extend",
  "requestId": "req-20261120-0004",
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
  "updatedAt": "2026-11-20T10:32:59.876010Z"
}
```

The run sent `POST /api/v1/clusters/CRC/namespaces/sprint-dev/expiration:extend?dryRun=true` with this body:

```json
{
  "days": 7
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
    "cpu": 0.062,
    "fresh": true,
    "memory": 0.05,
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "changed"
  },
  "etag": "6c68bebe0a929af0",
  "files": {
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: sprint-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/expiry: managed\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: small\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/expires-at: '2026-12-24'\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n"
  },
  "findings": [],
  "metadata": null,
  "planHash": "64c8a9b856f3bbc84bd24814367dc44b86b6377869e5f11cc7e77440775d667a",
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

### Remove a namespace's expiry

`POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:makePermanent`

Permission: `namespaces:write`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev/expiration:makePermanent -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"' -H 'Content-Type: application/json' -d '{"justification": "In production use"}'
```

The run sent `POST /api/v1/clusters/CRC/namespaces/sprint-dev/expiration:makePermanent` with this body:

```json
{
  "justification": "In production use"
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
        "reason": "Expiry beyond limits"
      }
    ],
    "timeoutHours": 8
  },
  "baseSha": "35a1bbba3dc7f0033bf2eeb5101cecbacbba181b",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:33:11.794155Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:33:11.794155Z",
      "by": "ola",
      "event": "plan_needs_approval",
      "note": "waiting for [('approver-platform', 1)]",
      "status": "pending_approval"
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
  "justification": "In production use",
  "links": {
    "events": "/api/v1/requests/req-20261120-0013/events",
    "self": "/api/v1/requests/req-20261120-0013"
  },
  "mergeSha": null,
  "namespace": "sprint-dev",
  "planHash": "0ecd3fba8488e8fb7fd5dd93120e91a014a6f51745dad9393c91dd1c696dd52e",
  "plugin": "namespaces",
  "pr": null,
  "reason": "expiration:makePermanent",
  "requestId": "req-20261120-0013",
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
  "updatedAt": "2026-11-20T10:33:11.804243Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.

The run sent `POST /api/v1/clusters/CRC/namespaces/sprint-dev/expiration:makePermanent?dryRun=true` with this body:

```json
{
  "justification": "In production use"
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
        "reason": "Expiry beyond limits"
      }
    ],
    "timeoutHours": 8
  },
  "beyondTier": null,
  "capacity": {
    "bindingResource": "cpu",
    "clusterId": "CRC",
    "cpu": 0.062,
    "fresh": true,
    "memory": 0.05,
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "changed"
  },
  "etag": "6c68bebe0a929af0",
  "files": {
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: sprint-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: small\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n"
  },
  "findings": [],
  "metadata": null,
  "planHash": "416b6be9a626aeb63e9fa5f7340f3e752583d18ae66ad0e1ede6be2a54b6c6e1",
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

### Give a permanent namespace an expiry date

`POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:set`

Permission: `namespaces:write`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev/expiration:set -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"' -H 'Content-Type: application/json' -d '{"justification": "A load test this sprint", "until": "2026-12-11"}'
```

The run sent `POST /api/v1/clusters/CRC/namespaces/notes-dev/expiration:set` with this body:

```json
{
  "justification": "A load test this sprint",
  "until": "2026-12-11"
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
  "baseSha": "2c01808b40ae5b3e5dcf8f3f3e592539190fa899",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:33:10.949876Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:33:10.949876Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "none-required",
      "status": "approved"
    }
  ],
  "files": {
    "clusters/CRC/namespaces/notes-dev/limitrange-notes-dev-limits-cpu.yaml": "unchanged",
    "clusters/CRC/namespaces/notes-dev/limitrange-notes-dev-limits-memory.yaml": "unchanged",
    "clusters/CRC/namespaces/notes-dev/namespace.yaml": "changed",
    "clusters/CRC/namespaces/notes-dev/resourcequota-notes-dev-quota.yaml": "unchanged",
    "clusters/CRC/namespaces/notes-dev/token-issuer-rolebinding.yaml": "unchanged"
  },
  "instance": "nonprod",
  "justification": "A load test this sprint",
  "links": {
    "events": "/api/v1/requests/req-20261120-0012/events",
    "self": "/api/v1/requests/req-20261120-0012"
  },
  "mergeSha": null,
  "namespace": "notes-dev",
  "planHash": "171674c56b87bbc25e217f51a5695a36999c0dadb1639f08cfd3e965d97c3ffc",
  "plugin": "namespaces",
  "pr": null,
  "reason": "expiration:set",
  "requestId": "req-20261120-0012",
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
  "updatedAt": "2026-11-20T10:33:10.954889Z"
}
```

The run sent `POST /api/v1/clusters/CRC/namespaces/notes-dev/expiration:set?dryRun=true` with this body:

```json
{
  "justification": "A load test this sprint",
  "until": "2026-12-11"
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
    "cpu": 0.062,
    "fresh": true,
    "memory": 0.05,
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/notes-dev/namespace.yaml": "changed"
  },
  "etag": "79da208d3cbbec1e",
  "files": {
    "clusters/CRC/namespaces/notes-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: notes-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/expiry: managed\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: small\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/expires-at: '2026-12-11'\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n"
  },
  "findings": [],
  "metadata": null,
  "planHash": "3cf4e289d3b3517d406d3d2911113d056fb9d04505222f6a110ac78e3d418259",
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

What the Kyverno bundle decided on each cluster, read from its policy reports, and the requests that cmapi refused before Git, with Kyverno's warnings on plans that went on.

### What cmapi refused before Git, paged

`GET /api/v1/policies/rejections`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/policies/rejections -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/policies/rejections?since=7d`.

The answer was 200 (`application/json`):

```json
{
  "from": "2026-11-13T10:33:12.015603Z",
  "items": [
    {
      "action": "create",
      "automated": false,
      "clusterId": "CRC",
      "count": 1,
      "env": "dev",
      "findings": [
        {
          "kyvernoRule": null,
          "message": "kube-tools is reserved (kube-*)",
          "path": null,
          "policy": "reserved-namespace",
          "rule": null,
          "severity": "error",
          "source": "cmapi"
        }
      ],
      "firstAt": "2026-11-20T10:33:09.751026Z",
      "id": "rej-2",
      "lastAt": "2026-11-20T10:33:09.751026Z",
      "namespace": "kube-tools",
      "outcome": "refused",
      "plugin": "namespaces",
      "problem": "reserved-namespace",
      "requestId": null,
      "stage": "plan",
      "username": "ola"
    }
  ],
  "letters": {
    "K": 1,
    "S": 1
  },
  "page": {
    "from": 1,
    "limit": 50,
    "nextCursor": null,
    "prevCursor": null,
    "to": 2,
    "total": 2
  },
  "since": "7d",
  "truncated": false
}
```

`body.items` has 2 items in the run. The first is shown.

### Kyverno's results on each cluster, paged

`GET /api/v1/policies/results`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/policies/results -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/policies/results?limit=25`.

The answer was 200 (`application/json`):

```json
{
  "clusters": [
    {
      "asOf": "2026-11-20T10:33:11.902213Z",
      "bundle": {
        "actionsDiffer": [],
        "actionsDifferTotal": 0,
        "current": 31,
        "differing": [],
        "expected": 31,
        "live": 31,
        "missing": [],
        "ready": 31
      },
      "clusterId": "CRC",
      "counts": {
        "error": 0,
        "fail": 1,
        "pass": 1,
        "skip": 0,
        "warn": 0
      },
      "dropped": 0,
      "env": "dev",
      "hashState": "current",
      "hashes": {
        "live": "1d05d32730f241fc36287e6b97780dc60f1844c074b33661876bb4cc561c573f",
        "rendered": "1d05d32730f241fc36287e6b97780dc60f1844c074b33661876bb4cc561c573f"
      },
      "hidden": {
        "otherPolicies": 0,
        "stale": 0,
        "unmanaged": 0
      },
      "liveActions": [
        "Audit"
      ],
      "mode": "audit",
      "state": "ok",
      "stateDetail": null
    }
  ],
  "items": [
    {
      "clusterId": "CRC",
      "env": "dev",
      "kyvernoRule": "validation",
      "message": "the label keys other.example/x are not declared in metadata-keys.yaml, and are outside extraLabels.allowOther.prefixes",
      "mode": "audit",
      "namespace": "payments-dev",
      "observedAt": "2026-11-17T13:41:10Z",
      "policy": "cmapi-metadata-dev-label-other-keys-prefix",
      "process": "background scan",
      "resource": {
        "apiVersion": "v1",
        "kind": "Namespace",
        "name": "payments-dev"
      },
      "result": "fail",
      "rule": "prefix",
      "source": "KyvernoValidatingPolicy"
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
  },
  "policies": [
    {
      "check": {
        "key": "limitRange.container.default.cpu",
        "kind": "limit",
        "rule": "max"
      },
      "counts": {
        "error": 0,
        "fail": 0,
        "pass": 0,
        "skip": 0,
        "warn": 0
      },
      "description": "Each LimitRange value of a managed namespace at or below the dev maximum; limits never below requests.",
      "environments": [
        "dev"
      ],
      "generated": true,
      "kind": "ValidatingPolicy",
      "name": "cmapi-limits-dev-limit-limitrange-container-default-cpu-max"
    }
  ],
  "policy": {
    "engine": "kyverno",
    "environments": {
      "dev": "audit",
      "rnd": "audit"
    },
    "kyvernoVersion": null
  }
}
```

`body.clusters[0].liveActions` has 2 items in the run. The first is shown.
`body.policies` has 31 items in the run. The first is shown.

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

Each cluster's quota commitment against its size, live from the watch of its quotas and nodes, and the groups of clusters by clusters.yaml: the Capacity tab.

### Cluster capacity, grouped

`GET /api/v1/capacity`

Permission: `capacity:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/capacity -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/capacity`.

The answer was 200 (`application/json`, `etag: "854373e171f867395bd081a622112223"`):

```json
{
  "clusters": [
    {
      "asOf": "2026-11-20T10:33:00Z",
      "basis": "simulated",
      "boundBy": "cpu",
      "clusterId": "CRC",
      "cpu": {
        "allocatable": 7800,
        "commitment": 0.375,
        "committed": 48000,
        "headroom": 80000,
        "limit": 128000,
        "overcommit": 2.0,
        "quotaUsed": 0,
        "quotaUsedMissing": 0,
        "requested": null,
        "simulated": 64000,
        "status": "ok",
        "unit": "millicores",
        "usedAvg": null,
        "usedPeak": null
      },
      "env": "dev",
      "history": null,
      "managedNamespaces": 3,
      "memory": {
        "allocatable": 20493357056,
        "commitment": 0.3,
        "committed": 103079215104,
        "headroom": 240518168576,
        "limit": 343597383680,
        "overcommit": 1.25,
        "quotaUsed": 0,
        "quotaUsedMissing": 0,
        "requested": null,
        "simulated": 274877906944,
        "status": "ok",
        "unit": "bytes",
        "usedAvg": null,
        "usedPeak": null
      },
      "nodes": {
        "cordoned": 0,
        "counted": 1,
        "notReady": 0,
        "tainted": 0,
        "total": 1
      },
      "nodesDetail": null,
      "nodesState": "ok",
      "region": "us-central",
      "scopedQuotas": 0,
      "state": "ok",
      "stateDetail": null,
      "status": "ok",
      "writes": true,
      "zones": []
    }
  ],
  "groupBy": [
    "region"
  ],
  "groups": [
    {
      "boundBy": "cpu",
      "clusterIds": [
        "CRC"
      ],
      "coverage": 1.0,
      "cpu": {
        "commitment": 0.375,
        "committed": 48000,
        "headroom": 80000,
        "largestPlacement": {
          "clusterId": "CRC",
          "value": 80000
        },
        "limit": 128000,
        "unit": "millicores"
      },
      "excluded": [],
      "included": 1,
      "key": {
        "environment": "dev",
        "region": "us-central"
      },
      "matching": 1,
      "memory": {
        "commitment": 0.3,
        "committed": 103079215104,
        "headroom": 240518168576,
        "largestPlacement": {
          "clusterId": "CRC",
          "value": 240518168576
        },
        "limit": 343597383680,
        "unit": "bytes"
      },
      "name": "us-central \u00b7 dev",
      "status": "ok",
      "statusCounts": {
        "critical": 0,
        "ok": 1,
        "over": 0,
        "warn": 0
      }
    }
  ],
  "hiddenClusters": 0,
  "notMeasured": [
    "requested"
  ],
  "snapshotState": "not-built",
  "source": "live",
  "targets": [
    {
      "commitment": {
        "critical": 0.95,
        "warn": 0.85
      },
      "env": "dev",
      "overcommit": {
        "cpu": 2.0,
        "memory": 1.25
      },
      "overcommitDefault": false
    }
  ]
}
```

`body.groupBy` has 2 items in the run. The first is shown.
`body.notMeasured` has 4 items in the run. The first is shown.
`body.targets` has 2 items in the run. The first is shown.

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
      "baseSha": "d059a3d1e7a668d048e58f375ea118c148edbfd4",
      "beyondTier": null,
      "clusterId": "CRC",
      "createdAt": "2026-11-20T10:32:57.274605Z",
      "env": "dev",
      "events": [
        {
          "at": "2026-11-20T10:32:57.274605Z",
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
        "events": "/api/v1/requests/req-20261120-0002/events",
        "self": "/api/v1/requests/req-20261120-0002"
      },
      "mergeSha": null,
      "namespace": "payments-dev",
      "planHash": "1b58de9851fc4154e07788456440a964be88c7352d3c5bbe1c6d7253c520ba26",
      "plugin": "namespaces",
      "pr": null,
      "reason": null,
      "requestId": "req-20261120-0002",
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
      "updatedAt": "2026-11-20T10:32:57.282611Z"
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

The run sent `GET /api/v1/requests/req-20261120-0001`.

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
  "createdAt": "2026-11-20T10:32:55.981438Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:32:55.981438Z",
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
    "events": "/api/v1/requests/req-20261120-0001/events",
    "pr": "https://git.test/pulls/1",
    "self": "/api/v1/requests/req-20261120-0001"
  },
  "mergeSha": "d059a3d1",
  "namespace": "payments-dev",
  "planHash": "85687a3dac629df64bb5e1d70ed160017edc50c1d4e279932600b1699c87ce39",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261120-0001",
    "head": "d059a3d1",
    "number": 1,
    "url": "https://git.test/pulls/1"
  },
  "reason": null,
  "requestId": "req-20261120-0001",
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
  "updatedAt": "2026-11-20T10:32:56.250280Z"
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

The run sent `GET /api/v1/requests/req-20261120-0001/approval-status`.

The answer was 200 (`application/json`):

```json
{
  "approved": true,
  "planHash": "85687a3dac629df64bb5e1d70ed160017edc50c1d4e279932600b1699c87ce39",
  "requestId": "req-20261120-0001",
  "status": "synced"
}
```

### A request's events

`GET /api/v1/requests/{request_id}/events`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001/events -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/requests/req-20261120-0001/events`.

The answer was 200 (`application/json`):

```json
{
  "events": [
    {
      "at": "2026-11-20T10:32:55.981438Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "auto:baseline-rnd-namespace",
      "status": "approved"
    }
  ],
  "requestId": "req-20261120-0001",
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

The run sent `POST /api/v1/requests/req-20261120-0002:approve` with this body:

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
        "at": "2026-11-20T10:32:57.509239Z",
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
  "baseSha": "d059a3d1e7a668d048e58f375ea118c148edbfd4",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:32:57.274605Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:32:57.274605Z",
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
    "events": "/api/v1/requests/req-20261120-0002/events",
    "self": "/api/v1/requests/req-20261120-0002"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "1b58de9851fc4154e07788456440a964be88c7352d3c5bbe1c6d7253c520ba26",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261120-0002",
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
  "updatedAt": "2026-11-20T10:32:57.474895Z"
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

The run sent `POST /api/v1/requests/req-20261120-0005:cancel`.

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
  "baseSha": "d7b0c767b07bc0b02ea75261144529ca1cc3a5cd",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:33:01.039775Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:33:01.039775Z",
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
    "events": "/api/v1/requests/req-20261120-0005/events",
    "self": "/api/v1/requests/req-20261120-0005"
  },
  "mergeSha": null,
  "namespace": "ledger-dev",
  "planHash": "5af6c61c82738e5f32de12d201ff7f8260c2656fcdbaaaef02f71e5209046a9a",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261120-0005",
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
  "updatedAt": "2026-11-20T10:33:01.345469Z"
}
```

`body.events` has 2 items in the run. The first is shown.

### Reject a request

`POST /api/v1/requests/{request_id}:reject`

Permission: `requests:reject`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:reject -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"comment": "Use the medium tier"}'
```

The run sent `POST /api/v1/requests/req-20261120-0006:reject` with this body:

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
  "baseSha": "d7b0c767b07bc0b02ea75261144529ca1cc3a5cd",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:33:01.187695Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:33:01.187695Z",
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
    "events": "/api/v1/requests/req-20261120-0006/events",
    "self": "/api/v1/requests/req-20261120-0006"
  },
  "mergeSha": null,
  "namespace": "billing-dev",
  "planHash": "a1c89830573d18294884f45c3acea3e19c4bc59c40c4ffe3abf1f7c45d8d7c22",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261120-0006",
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
  "updatedAt": "2026-11-20T10:33:01.251710Z"
}
```

`body.events` has 2 items in the run. The first is shown.

### Retry a failed request

`POST /api/v1/requests/{request_id}:retry`

Permission: `requests:retry`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:retry -H "Authorization: Bearer $TOKEN"
```

The run sent `POST /api/v1/requests/req-20261120-0007:retry`.

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
  "baseSha": "d7b0c767b07bc0b02ea75261144529ca1cc3a5cd",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:33:03.084776Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:33:03.084776Z",
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
    "events": "/api/v1/requests/req-20261120-0007/events",
    "pr": "https://git.test/pulls/5",
    "self": "/api/v1/requests/req-20261120-0007"
  },
  "mergeSha": null,
  "namespace": "search-dev",
  "planHash": "c8abcc5ed1db573a09247d14130f6cd6d53230d1639a97c21f3ba78d8bd3094c",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261120-0007",
    "head": "42c28d55",
    "number": 5,
    "url": "https://git.test/pulls/5"
  },
  "reason": null,
  "requestId": "req-20261120-0007",
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
  "updatedAt": "2026-11-20T10:33:04.814334Z"
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

The run sent `POST /api/v1/requests/req-20261120-0009:revert`.

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
  "baseSha": "d7b0c767b07bc0b02ea75261144529ca1cc3a5cd",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:33:08.464466Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:33:08.464466Z",
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
    "events": "/api/v1/requests/req-20261120-0009/events",
    "pr": "https://git.test/pulls/8",
    "self": "/api/v1/requests/req-20261120-0009"
  },
  "mergeSha": "bca2877b",
  "namespace": "orders-dev",
  "planHash": "b43c182bd4253f22eee2c22186139f6ad682363dd831e1e9192c0586a741fcfb",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261120-0009",
    "head": "bca2877b",
    "number": 8,
    "url": "https://git.test/pulls/8"
  },
  "reason": null,
  "requestId": "req-20261120-0009",
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
  "updatedAt": "2026-11-20T10:33:08.891663Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.
`body.events` has 8 items in the run. The first is shown.

## Operations

The instance itself: who the caller is and what the caller can do, the clusters that the instance knows, the rules of a new namespace's labels and annotations, and the version of the running build.

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
      "checkedAt": "2026-11-20T10:32:54.849857Z",
      "clusterId": "CRC",
      "environment": "dev",
      "findingDetails": [],
      "findings": [],
      "gitopsPath": "clusters/CRC",
      "labels": {
        "region": "us-central"
      },
      "lastProbeAt": "2026-11-20T10:32:54.849857Z",
      "secretName": "cmapi-cluster-crc",
      "serverVersion": "v1.35.6-fake",
      "status": "connected",
      "statusSince": "2026-11-20T10:32:54.849857Z",
      "tokenExpiresAt": null,
      "trust": {
        "downgrade": false,
        "serverName": null,
        "source": "trusted"
      },
      "writes": true
    }
  ]
}
```

### Probe one cluster's held credential

`POST /api/v1/clusters/{id}:probe`

Permission: `operations:run`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC:probe -H "Authorization: Bearer $TOKEN"
```

The run sent `POST /api/v1/clusters/CRC:probe`.

The answer was 200 (`application/json`):

```json
{
  "checkedAt": "2026-11-20T10:32:55.226025Z",
  "clusterId": "CRC",
  "environment": "dev",
  "findingDetails": [],
  "findings": [],
  "gitopsPath": "clusters/CRC",
  "labels": {
    "region": "us-central"
  },
  "lastProbeAt": "2026-11-20T10:32:55.226025Z",
  "secretName": "cmapi-cluster-crc",
  "serverVersion": "v1.35.6-fake",
  "status": "connected",
  "statusSince": "2026-11-20T10:32:54.849857Z",
  "tokenExpiresAt": null,
  "trust": {
    "downgrade": false,
    "serverName": null,
    "source": "trusted"
  },
  "writes": true
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
  "operator": false,
  "operatorEnvironments": [],
  "roles": [
    "cmapi-requester"
  ],
  "username": "ola"
}
```

`body.access.permissions` has 10 items in the run. The first is shown.
`body.access.roles[0].permissions` has 10 items in the run. The first is shown.

### The rules of a new namespace's labels and annotations

`GET /api/v1/metadata-keys`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/metadata-keys -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/metadata-keys`.

The answer was 200 (`application/json`, `etag: "9415b425a9b08bf3e7076447b5af8156"`):

```json
{
  "annotations": {
    "additionalProperties": {
      "maxLength": 4096,
      "type": "string"
    },
    "properties": {
      "cmapi.net/protected": {
        "description": "An operator only (namespaces:protect): another caller gets 403 forbidden.",
        "type": "string",
        "x-cmapi-operator-only": true
      },
      "cmapi.net/team-dl": {
        "description": "Your team's distribution list, in one of the organisation's email domains (emailDomains); format only. An address in ['ephico2real.com'].",
        "examples": [
          "payments-team@ephico2real.com"
        ],
        "minLength": 1,
        "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[eE][pP][hH][iI][cC][oO]2[rR][eE][aA][lL]\\.[cC][oO][mM])$",
        "title": "Team DL",
        "type": "string",
        "x-cmapi-format": "email-in-domains",
        "x-cmapi-rule": "an address in ['ephico2real.com']"
      },
      "do-not-delete": {
        "description": "An operator only (namespaces:protect): another caller gets 403 forbidden.",
        "type": "string",
        "x-cmapi-operator-only": true
      }
    },
    "propertyNames": {
      "anyOf": [
        {
          "enum": [
            "cmapi.net/team-dl"
          ]
        }
      ],
      "maxLength": 317,
      "not": {
        "pattern": "^[^/]{254}"
      },
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$"
    },
    "required": [
      "cmapi.net/team-dl"
    ],
    "type": "object",
    "x-cmapi-other-keys": {
      "max": 50,
      "maxBytesTotal": 65536,
      "maxValueBytes": 4096,
      "prefixes": [
        ""
      ]
    }
  },
  "labels": {
    "additionalProperties": {
      "maxLength": 63,
      "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
      "type": "string"
    },
    "properties": {
      "cmapi.net/app": {
        "allOf": [
          {
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
            "type": "string"
          }
        ],
        "description": "Links an app's environments. Must match ^[a-z0-9-]{2,40}$.",
        "maxLength": 63,
        "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
        "type": "string",
        "x-cmapi-rule": "must match ^[a-z0-9-]{2,40}$"
      },
      "cmapi.net/cost-center": {
        "allOf": [
          {
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
            "type": "string"
          }
        ],
        "description": "Must match ^cc-[0-9]{4}$.",
        "examples": [
          "cc-4410"
        ],
        "maxLength": 63,
        "pattern": "^(?:^cc-[0-9]{4}$)$",
        "type": "string",
        "x-cmapi-rule": "must match ^cc-[0-9]{4}$"
      },
      "cmapi.net/protected": {
        "description": "An operator only (namespaces:protect): another caller gets 403 forbidden.",
        "maxLength": 63,
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "type": "string",
        "x-cmapi-operator-only": true
      },
      "cmapi.net/rightsizing": {
        "allOf": [
          {
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
            "type": "string"
          }
        ],
        "description": "Opt-in to automatic rnd and qa decreases. Must match ^(auto|manual)$.",
        "maxLength": 63,
        "pattern": "^(?:^(auto|manual)$)$",
        "type": "string",
        "x-cmapi-rule": "must match ^(auto|manual)$"
      },
      "cmapi.net/team": {
        "allOf": [
          {
            "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
            "type": "string"
          }
        ],
        "description": "Who owns it, for cost and notices: any team name. Not checked against who you are; your Keycloak roles decide what you may do. Must match ^[a-z0-9-]{2,40}$.",
        "examples": [
          "payments"
        ],
        "maxLength": 63,
        "minLength": 1,
        "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
        "title": "Team",
        "type": "string",
        "x-cmapi-rule": "must match ^[a-z0-9-]{2,40}$"
      },
      "do-not-delete": {
        "description": "An operator only (namespaces:protect): another caller gets 403 forbidden.",
        "maxLength": 63,
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "type": "string",
        "x-cmapi-operator-only": true
      }
    },
    "propertyNames": {
      "anyOf": [
        {
          "enum": [
            "cmapi.net/team"
          ]
        }
      ],
      "maxLength": 317,
      "not": {
        "pattern": "^[^/]{254}"
      },
      "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$"
    },
    "required": [
      "cmapi.net/team"
    ],
    "type": "object",
    "x-cmapi-other-keys": {
      "max": 50,
      "prefixes": [
        ""
      ]
    }
  }
}
```

`body.annotations.propertyNames.anyOf` has 2 items in the run. The first is shown.
`body.annotations.propertyNames.anyOf[0].enum` has 3 items in the run. The first is shown.
`body.annotations.x-cmapi-other-keys.prefixes` has 2 items in the run. The first is shown.
`body.labels.propertyNames.anyOf` has 2 items in the run. The first is shown.
`body.labels.propertyNames.anyOf[0].enum` has 6 items in the run. The first is shown.
`body.labels.x-cmapi-other-keys.prefixes` has 2 items in the run. The first is shown.

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
  "setAt": "2026-11-20T10:33:01.492933+00:00",
  "setBy": "ada"
}
```

### Resume auto-approval

`POST /api/v1/admin/auto-approval:resume`

Permission: `approvals:pause`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/admin/auto-approval:resume -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"reason": "incident 1234 closed"}'
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
  "setAt": "2026-11-20T10:33:01.511793+00:00",
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
    "d059a3d1 Merge cmapi/CRC/req-20261120-0001"
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
      "dev": "audit",
      "rnd": "audit"
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
      "measuredAt": 1795170776.945011,
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
    "sizeBytes": 10451991,
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
      "value": 0.266329
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

`body.items` has 10 items in the run. The first is shown.

### Confirm the prune of a deleted namespace

`POST /api/v1/admin/prune:confirm`

Permission: `operations:run`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/admin/prune:confirm -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"clusterId": "CRC", "namespace": "search-dev"}'
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
        "at": "2026-11-20T10:33:06.205884Z",
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
  "baseSha": "42c28d55db885b61d2f81efe3a4655f69e366bbd",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-20T10:33:06.118570Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-20T10:33:06.118570Z",
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
    "events": "/api/v1/requests/req-20261120-0008/events",
    "pr": "https://git.test/pulls/7",
    "self": "/api/v1/requests/req-20261120-0008"
  },
  "mergeSha": "d7b0c767",
  "namespace": "search-dev",
  "planHash": "c490196334dad591c3196aa59224d119861392145360aee1d428c93109235dbe",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261120-0008",
    "head": "d7b0c767",
    "number": 7,
    "url": "https://git.test/pulls/7"
  },
  "reason": null,
  "requestId": "req-20261120-0008",
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
  "updatedAt": "2026-11-20T10:33:07.207643Z"
}
```

`body.events` has 10 items in the run. The first is shown.

## Problems

Each refusal is an RFC 9457 problem with the media type `application/problem+json`. These are the ones that the run met.

### 422 `expiration-already-set`

`POST /api/v1/clusters/CRC/namespaces/sprint-dev/expiration:set`, with a body:

```json
{
  "code": "expiration-already-set",
  "detail": "Use :extend to move an existing date",
  "status": 422,
  "title": "expiration already set",
  "type": "https://cmapi.ephico2real.com/problems/expiration-already-set"
}
```

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

`POST /api/v1/requests/req-20261120-0007:revert`:

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

### 422 `policy-violation`

`POST /api/v1/clusters/CRC/namespaces?dryRun=true`, with a body:

```json
{
  "code": "policy-violation",
  "detail": "Metadata refused",
  "errors": [
    {
      "code": "invalid_value",
      "detail": "must match ^[a-z0-9-]{2,40}$",
      "key": "cmapi.net/team",
      "kind": "label"
    },
    {
      "code": "missing_required_key",
      "detail": "an address in ['ephico2real.com']",
      "key": "cmapi.net/team-dl",
      "kind": "annotation"
    }
  ],
  "findings": [],
  "status": 422,
  "title": "policy violation",
  "type": "https://cmapi.ephico2real.com/problems/policy-violation"
}
```

### 412 `precondition-failed`

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev`, with a body:

```json
{
  "code": "precondition-failed",
  "detail": "The namespace changed in Git since you read it",
  "etag": "8b67bd76ddf33c88",
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
