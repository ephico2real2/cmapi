# cmapi: API examples

This document shows each operation of the cmapi API that is built, with a curl sample and a real request and response. The payloads are not written by hand. A run of the service suite recorded them, and the OpenAPI document holds the same ones, so Swagger UI at `/docs` and ReDoc at `/redoc` show what this document shows.

## How to read it

- **Where the payloads come from.** `cmapi/tests/service/test_api_samples.py` walks the API in one scenario on the test instance of the service suite: PostgreSQL 16, a fake Git host and a fake cluster named `CRC` in environment `dev`, with a fake Kyverno report and a fake Node for the Policies and Capacity calls. It writes `cmapi/src/cmapi/contract/samples.json`, whose last commit is of 2026-11-23. Every operation of `cmapi/contract/openapi.json` has a recorded call, and the same test fails when one has none (`test_each_operation_has_a_sample_from_a_run`). No payload here is from CRC or from kind.
- **What differs on a real instance.** Request IDs, times, etags, cursors and hashes are those of that run. The host in each curl sample is the `publicUrl` of the test instance.
- **Tokens.** Each sample sends `Authorization: Bearer $TOKEN`. No token is in the samples. [`docs/15-keycloak-integration.md`](15-keycloak-integration.md) says how a caller gets a token, and [`docs/14-authorization.md`](14-authorization.md) says which role each permission needs.
- **Long lists.** A list in a response is cut to its first item, and a line under the block says so.

## Rules for each call

| Rule | Detail |
|---|---|
| The instance | Call the instance that serves the environment of the cluster. Another instance answers 422 `environment-not-served` |
| Writes | A write to a namespace returns 202 with a change request. The change reaches the cluster through a pull request after approval |
| `Idempotency-Key` | Necessary on each write to a namespace, at most 100 characters, and not read on a `?dryRun=true` call (`plugins/namespaces/router.py`, `_idem`). For 24 hours, the same caller retrying the same request with the same key gets the original request in its current state, with the same `requestId` (`_replay` and `core/views.py`, `request_view`), not a stored copy of the first response. The caller is the token's subject, and the key is stored and looked up under it (#592): a service that sends `onBehalfOf` holds its own key, so its retry replays, and the person it names cannot replay that request with the key. The person's own use of that key is a request of their own (#603). Without it the answer is 400 `idempotency-key-required`. The same key with a different request is 409 `idempotency-replay`. The expiry calls do not compare `justification`, so a retry that changes only it gets the original request. Make a new key for each new action (`$(uuidgen)` in a shell), and send the same key again only to retry that same call. The fixed keys in the samples below are examples, not values to copy. Clients that generate the key, so that a person never types one, are #282 |
| `If-Match` | Necessary on a change, a delete, an extension, a new expiry date and the removal of the expiry (`:extend`, `:set`, `:makePermanent`). Its value is the `etag` of `GET .../namespaces/{ns}` in double quotes, as the `ETag` header gives it. A list of tags (`If-Match: "a", "b"`) passes when one of them is the current etag (RFC 9110, section 13.1.1). Send the list in one comma-separated `If-Match` field: the front door's nginx answers 400 to a second `If-Match` line (#582). Without it, or with `If-Match: *`, the answer is 428 `precondition-required`: cmapi refuses `*` on purpose, where RFC 9110 lets it match any namespace that exists, because it proves no read (RFC 6585, section 3; #571). A weak tag (`W/"..."`) never matches, and with an old value the answer is 412 `precondition-failed`, whose `etag` is the current one. An Idempotency-Key replay still needs If-Match and refuses `*`, and returns the original request in its current state without comparing the tag |
| Conditional reads | `/openapi.json`, `/openapi.yaml`, `GET /api/v1/metadata-keys`, `GET /api/v1/capacity` and the files under `/static/swagger` and `/static/redoc` send an `ETag`, and evaluate the preconditions in the order of RFC 9110, section 13.2.2 (`core/etag.py`, `not_modified`). An `If-Match` that is not `*` and lists no strong tag equal to the `ETag` is 412 `precondition-failed`, with the current tag in `etag`, before `If-None-Match` is read. Then a matching `If-None-Match` (weak comparison, `*` matches) is 304 with no body. The static files also send `Last-Modified`: without `If-Match`, an `If-Unmodified-Since` earlier than it is 412, and without `If-None-Match`, an `If-Modified-Since` at or after it is 304. A date field that is not one valid HTTP-date, a list of dates or a second line of it is ignored (#604, #619, #620). A valid date has the day name of its date, a year from 1900, and a time to 23:59:59, or 23:59:60 on the last day of a month (a leap second) |
| `Range` | Not supported. The files under `/static/swagger` and `/static/redoc` ignore `Range` and `If-Range`: they answer 200 with the whole file, or 304, and both say `Accept-Ranges: none`. The preconditions above are unchanged (RFC 9110, sections 14.2 and 14.3; `main.py`, `ConditionalStaticFiles`; #649). No other route reads `Range` |
| `Content-Type` | Each call with a body sends `Content-Type: application/json`, as each sample does; a media type that ends in `+json`, such as `application/merge-patch+json`, is read too. A body with no `Content-Type`, or with one that is not JSON, is not read as JSON and is 422 `validation-failed`: FastAPI's strict check since 0.132.0, which cmapi keeps (#651) |
| `HEAD` | Every `GET` also answers `HEAD` (RFC 9110, sections 9.1 and 9.3.2), with the status and headers of the `GET` and no body: the same sign-in and permission, and the same `ETag`, `Cache-Control` and `Content-Length`, so `curl -I` checks a tag or a 401 without the body. A `HEAD` of `GET /api/v1/quotas:export` sends no rows, so it writes no audit event: only the `GET` is an export. The OpenAPI document lists the `GET` only (#605) |
| `?dryRun=true` | On every write to a namespace (a create, a change, a delete and each of the three expiry calls), it returns 200 with the plan and writes nothing: no request, no pull request. It makes the checks of the call it previews, so it is refused where that call would be. A delete's plan lists each file of the folder, at any depth and whatever made it, as `removed` and renders none (#602, #616); a folder that holds a submodule is 409 `folder-holds-submodule`. Every other write (`:approve`, `:reject`, `:cancel`, `:retry`, `:revert`, the admin calls, `:probe`) has no dry run and answers any `dryRun` with 400 `dry-run-not-supported`, so a preview never runs for real (`core/docs.py`, `refuse_dry_run`; #606) |
| A change of metadata | `PATCH .../namespaces/{ns}` is a JSON merge patch (RFC 7396) inside `labels` and `annotations`: a key left out keeps its value, a value sets it, and `null` removes it. The keys that the namespace name is made of (`namespacePrefix`, `namespaceSuffix`) and the keys that cmapi fills in (`value: {from: ...}`) keep their values: sending the value back is accepted, and another value is refused. `x-cmapi-edit` of each key in `GET /api/v1/metadata-keys` says how it may change, and the dry run's `metadataDiff` lists each effective change with `before`, `after` and `source` (`core/metadata.py`, `edit_rule` and `metadata_diff`; #481) |
| One request per namespace | A second submit while a request holds the namespace is 409 `change-pending`, with the holder's `requestId`. `GET .../namespaces/{ns}` shows the holder in `sync.openRequest`, and `sync.state` compares Git (`git`) with the live namespace: `pending`, `drift` (each key in `sync.driftedKeys`), `in-sync` or `unknown` (`plugins/namespaces/state.py`, `sync_state`) |
| Finding a namespace | `GET .../namespaces?q=pay&mnemonic=abc&limit=10` matches the name, the team and the app, names that start with `q` first, and returns `total` and `facets.mnemonics`. With no parameter it is every managed namespace by name |
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

The routes `/healthz`, `/readyz`, `/problems`, `/problems/{code}`, `/openapi.json`, `/openapi.yaml`, `/docs`, `/docs/oauth2-redirect`, `/docs/redoc-start.js`, `/docs/swagger.css`, `/redoc` and `/docs/changelog`, and the files under `/static/swagger` and `/static/redoc`, are built and have no example, because they are not in the OpenAPI document (`include_in_schema=False` in `cmapi/main.py` and `routers/health.py`; the static files are mounts). `docs/08-code-status.md`, section 4, lists the same gaps and may lag the code.

<!-- examples:begin -->
## Namespaces and metadata

The managed namespaces by expiry: a paged list of each namespace that can expire, with its date, the days left and its state. A date is changed with :extend, :set or :makePermanent of the namespaces plugin.

### List namespaces by expiry

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
      "actions": [
        "extend"
      ],
      "app": null,
      "clusterId": "CRC",
      "created": "2026-11-26",
      "daysLeft": 21,
      "env": "dev",
      "expiresAt": "2026-12-17",
      "graceEnds": "2026-12-24",
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
  "today": "2026-11-26"
}
```

`body.items` has 3 items in the run. The first is shown.
`body.items[0].actions` has 2 items in the run. The first is shown.
`body.rules.dev.notifyDaysBefore` has 3 items in the run. The first is shown.

The managed namespaces of a cluster: read them, and create, change, delete or extend one. Each write returns a change request and becomes a pull request after approval.

### List managed namespaces on a cluster

`GET /api/v1/clusters/{cluster_id}/namespaces`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/clusters/CRC/namespaces?q=pay&limit=10`.

The answer was 200 (`application/json`):

```json
{
  "facets": {
    "mnemonics": {}
  },
  "items": [
    {
      "annotations": {
        "argocd.argoproj.io/sync-options": "Prune=confirm,ServerSideApply=true",
        "cmapi.net/instance": "nonprod",
        "cmapi.net/request-id": "req-20261126-0001",
        "cmapi.net/requested-by": "ola@ephico2real.com",
        "cmapi.net/team-dl": "payments-team@ephico2real.com"
      },
      "clusterId": "CRC",
      "env": "dev",
      "etag": null,
      "expiresAt": null,
      "git": null,
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
      "mnemonic": null,
      "name": "payments-dev",
      "openRequest": null,
      "protected": null,
      "protectedBy": null,
      "sync": {
        "driftedKeys": [],
        "openRequest": null,
        "state": "unknown"
      },
      "team": "payments",
      "tier": "small"
    }
  ],
  "total": 1
}
```

### Create a namespace

`POST /api/v1/clusters/{cluster_id}/namespaces`

Permission: `namespaces:create`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'Content-Type: application/json' -d '{"annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com"}, "justification": "Payments service dev namespace", "labels": {"cmapi.net/team": "payments", "cmapi.net/cost-center": "cc-4410"}, "namespace": "payments-dev", "tier": "small"}'
```

With expiration (choose a future date when sending)

```json
{
  "annotations": {
    "cmapi.net/team-dl": "payments-team@ephico2real.com"
  },
  "expiresAt": "2026-12-15",
  "justification": "Payments service dev namespace",
  "labels": {
    "cmapi.net/cost-center": "cc-4410",
    "cmapi.net/team": "payments"
  },
  "namespace": "payments-dev",
  "tier": "small"
}
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
  "createdAt": "2026-11-26T18:48:14.925300Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:15.008254Z",
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
    "events": "/api/v1/requests/req-20261126-0001/events",
    "self": "/api/v1/requests/req-20261126-0001"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "05f11d47a3e765a127f8a5219e764c0f8f33cc0278c08556a9249bfdb49d3737",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261126-0001",
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
  "updatedAt": "2026-11-26T18:48:14.798832Z"
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
    "reserved": {
      "cpu": 0.0,
      "memory": 0
    },
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
  "metadataDiff": null,
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
  },
  "usage": null
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
  "baseSha": "f2384f006831a8a6663be5efae93955878f7cae8",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:32.649396Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:32.676007Z",
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
    "events": "/api/v1/requests/req-20261126-0008/events",
    "self": "/api/v1/requests/req-20261126-0008"
  },
  "mergeSha": null,
  "namespace": "search-dev",
  "planHash": "c490196334dad591c3196aa59224d119861392145360aee1d428c93109235dbe",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261126-0008",
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
  "updatedAt": "2026-11-26T18:48:32.471280Z"
}
```

The run sent `DELETE /api/v1/clusters/CRC/namespaces/search-dev?dryRun=true`.

The answer was 200 (`application/json`):

```json
{
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
  "beyondTier": null,
  "capacity": {
    "bindingResource": null,
    "fresh": true,
    "source": "delete",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/search-dev/limitrange-search-dev-limits-cpu.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/limitrange-search-dev-limits-memory.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/namespace.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/resourcequota-search-dev-quota.yaml": "removed",
    "clusters/CRC/namespaces/search-dev/token-issuer-rolebinding.yaml": "removed"
  },
  "etag": "ee065493c1da46cf",
  "files": {},
  "findings": [],
  "metadata": null,
  "metadataDiff": null,
  "planHash": "c490196334dad591c3196aa59224d119861392145360aee1d428c93109235dbe",
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
  "usage": null
}
```

### Get a namespace and its ETag

`GET /api/v1/clusters/{cluster_id}/namespaces/{ns}`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/clusters/CRC/namespaces/payments-dev`.

The answer was 200 (`application/json`, `etag: "f58b8be265a84def"`):

```json
{
  "annotations": {
    "argocd.argoproj.io/sync-options": "Prune=confirm,ServerSideApply=true",
    "cmapi.net/instance": "nonprod",
    "cmapi.net/request-id": "req-20261126-0001",
    "cmapi.net/requested-by": "ola@ephico2real.com",
    "cmapi.net/team-dl": "payments-team@ephico2real.com"
  },
  "clusterId": "CRC",
  "env": "dev",
  "etag": "f58b8be265a84def",
  "expiresAt": null,
  "git": {
    "annotations": {
      "argocd.argoproj.io/sync-options": "Prune=confirm,ServerSideApply=true",
      "cmapi.net/instance": "nonprod",
      "cmapi.net/request-id": "req-20261126-0001",
      "cmapi.net/requested-by": "ola@ephico2real.com",
      "cmapi.net/team-dl": "payments-team@ephico2real.com"
    },
    "edits": {
      "annotations": {
        "argocd.argoproj.io/sync-options": {
          "mode": "fixed",
          "reason": "Reserved for the platform.",
          "removable": false,
          "sensitive": false
        },
        "cmapi.net/instance": {
          "mode": "fixed",
          "reason": "Managed by cmapi.",
          "removable": false,
          "sensitive": false
        },
        "cmapi.net/request-id": {
          "mode": "fixed",
          "reason": "Managed by cmapi.",
          "removable": false,
          "sensitive": false
        },
        "cmapi.net/requested-by": {
          "mode": "fixed",
          "reason": "Managed by cmapi.",
          "removable": false,
          "sensitive": false
        }
      },
      "labels": {
        "cmapi.net/cluster-id": {
          "mode": "fixed",
          "reason": "Managed by cmapi.",
          "removable": false,
          "sensitive": false
        },
        "cmapi.net/env": {
          "mode": "fixed",
          "reason": "Managed by cmapi.",
          "removable": false,
          "sensitive": false
        },
        "cmapi.net/managed": {
          "mode": "fixed",
          "reason": "Managed by cmapi.",
          "removable": false,
          "sensitive": false
        },
        "cmapi.net/requested-by-user": {
          "mode": "fixed",
          "reason": "Managed by cmapi.",
          "removable": false,
          "sensitive": false
        },
        "cmapi.net/tier": {
          "mode": "fixed",
          "reason": "Managed by cmapi.",
          "removable": false,
          "sensitive": false
        }
      }
    },
    "labels": {
      "cmapi.net/cluster-id": "CRC",
      "cmapi.net/cost-center": "cc-4410",
      "cmapi.net/env": "dev",
      "cmapi.net/managed": "true",
      "cmapi.net/requested-by-user": "ola",
      "cmapi.net/team": "payments",
      "cmapi.net/tier": "small"
    }
  },
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
  "mnemonic": null,
  "name": "payments-dev",
  "openRequest": null,
  "protected": false,
  "protectedBy": [],
  "sync": {
    "driftedKeys": [],
    "openRequest": null,
    "state": "in-sync"
  },
  "team": "payments",
  "tier": "small"
}
```

### Change a namespace

`PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns}`

Permission: `namespaces:write`.

```bash
curl -X PATCH https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"' -H 'Content-Type: application/json' -d '{"annotations": {"runbook.ephico2real.com/url": "https://wiki.ephico2real.com/payments/runbook"}, "justification": "A smaller size after the load test, with the metadata tidied", "labels": {"cmapi.net/cost-center": null}, "tier": "medium"}'
```

Change labels and annotations: a value sets a key, null removes it (add dryRun=true to check)

```json
{
  "annotations": {
    "runbook.ephico2real.com/url": "https://wiki.ephico2real.com/payments/runbook"
  },
  "justification": "A smaller size after the load test, with the metadata tidied",
  "labels": {
    "cmapi.net/cost-center": null
  },
  "tier": "medium"
}
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
  "baseSha": "cb5c898bb9e87c673d2f8ea2db640d276b35b5a0",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:17.431998Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:17.539455Z",
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
    "events": "/api/v1/requests/req-20261126-0002/events",
    "self": "/api/v1/requests/req-20261126-0002"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "11b771c07365e3c8936ddb4a02620ba79697364721fcd5cb36905404aabe4311",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261126-0002",
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
  "updatedAt": "2026-11-26T18:48:17.335060Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.

The run sent `PATCH /api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true` with this body:

```json
{
  "annotations": {
    "runbook.ephico2real.com/url": "https://wiki.ephico2real.com/payments/runbook"
  },
  "justification": "A smaller size after the load test, with the metadata tidied",
  "labels": {
    "cmapi.net/cost-center": null
  },
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
    "reserved": {
      "cpu": 0.0,
      "memory": 0
    },
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "changed",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "changed"
  },
  "etag": "f58b8be265a84def",
  "files": {
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-cpu.yaml": "apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: payments-dev-limits-cpu\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  limits:\n  - type: Container\n    defaultRequest:\n      cpu: 100m\n    default:\n      cpu: 500m\n    max:\n      cpu: '4'\n",
    "clusters/CRC/namespaces/payments-dev/limitrange-payments-dev-limits-memory.yaml": "apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: payments-dev-limits-memory\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  limits:\n  - type: Container\n    defaultRequest:\n      memory: 256Mi\n    default:\n      memory: 512Mi\n    max:\n      memory: 8Gi\n",
    "clusters/CRC/namespaces/payments-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: medium\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n    runbook.ephico2real.com/url: https://wiki.ephico2real.com/payments/runbook\n",
    "clusters/CRC/namespaces/payments-dev/resourcequota-payments-dev-quota.yaml": "apiVersion: v1\nkind: ResourceQuota\nmetadata:\n  name: payments-dev-quota\n  namespace: payments-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/managed: 'true'\n    cmapi.net/tier: medium\n  annotations:\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/tier-hash: 44fd85f2d7cb\nspec:\n  hard:\n    requests.cpu: '16'\n    requests.memory: 32Gi\n    pods: '100'\n    persistentvolumeclaims: '30'\n    requests.storage: 500Gi\n    services.loadbalancers: '0'\n    services.nodeports: '0'\n"
  },
  "findings": [],
  "metadata": null,
  "metadataDiff": {
    "annotations": {
      "runbook.ephico2real.com/url": {
        "after": "https://wiki.ephico2real.com/payments/runbook",
        "before": null,
        "source": "request"
      }
    },
    "labels": {
      "cmapi.net/cost-center": {
        "after": null,
        "before": "cc-4410",
        "source": "request"
      }
    }
  },
  "planHash": "9a8898212a1e12a01c9565806230827decfb1e77a481c739c2671eb1e1235613",
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
  "usage": {
    "coverage": null,
    "cpu": {
      "avg7d": null,
      "newOverPeak": null,
      "newQuota": 16000,
      "now": null,
      "p95": null,
      "peak": null,
      "quota": 8000
    },
    "evaluatedAt": null,
    "memory": {
      "avg7d": null,
      "newOverPeak": null,
      "newQuota": 34359738368,
      "now": null,
      "p95": null,
      "peak": null,
      "quota": 17179869184
    },
    "reason": "No usage source is configured on this instance (capacity.yaml usage.source is none), so there is no 14-day usage.",
    "state": "insufficient-data",
    "units": {
      "cpu": "millicores",
      "memory": "bytes"
    },
    "window": "14d"
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
  "baseSha": "22a35f4793b3c001e8c8f0e6264753ea45b75be6",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:21.906964Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:22.039160Z",
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
    "events": "/api/v1/requests/req-20261126-0004/events",
    "self": "/api/v1/requests/req-20261126-0004"
  },
  "mergeSha": null,
  "namespace": "sprint-dev",
  "planHash": "9df90ce6833b4f3b8a7c4f47ca4aaac03c732687e99f0a767e00ba284651b9ab",
  "plugin": "namespaces",
  "pr": null,
  "reason": "expiration:extend",
  "requestId": "req-20261126-0004",
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
  "updatedAt": "2026-11-26T18:48:21.835319Z"
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
    "cpu": 0.25,
    "fresh": true,
    "memory": 0.2,
    "reserved": {
      "cpu": 24.0,
      "memory": 51539607552
    },
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "changed"
  },
  "etag": "2fb3790866b00ef5",
  "files": {
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: sprint-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/expiry: managed\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: small\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/expires-at: '2026-12-30'\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n"
  },
  "findings": [],
  "metadata": null,
  "metadataDiff": {
    "annotations": {},
    "labels": {}
  },
  "planHash": "bd37b8a2a01b507d9292bd3ad9b7cb5ae1526a72cf715293dd5fe40ad6d4b48d",
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
  "usage": null
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
  "baseSha": "a40cef6e6fff67dfaba8587d441c897bd3af523d",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:42.317931Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:42.430565Z",
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
    "events": "/api/v1/requests/req-20261126-0013/events",
    "self": "/api/v1/requests/req-20261126-0013"
  },
  "mergeSha": null,
  "namespace": "sprint-dev",
  "planHash": "6b73413a9b855c456f7c20454c9022db1ce2a0e4f0a4af5f3b262297054c0bb1",
  "plugin": "namespaces",
  "pr": null,
  "reason": "expiration:makePermanent",
  "requestId": "req-20261126-0013",
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
  "updatedAt": "2026-11-26T18:48:42.228002Z"
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
    "cpu": 0.25,
    "fresh": true,
    "memory": 0.2,
    "reserved": {
      "cpu": 24.0,
      "memory": 51539607552
    },
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "changed"
  },
  "etag": "2fb3790866b00ef5",
  "files": {
    "clusters/CRC/namespaces/sprint-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: sprint-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: small\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n"
  },
  "findings": [],
  "metadata": null,
  "metadataDiff": {
    "annotations": {},
    "labels": {}
  },
  "planHash": "003772433362b49df8ccca8091573a5709c23e384fda55d53e2e3c04619cf998",
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
  "usage": null
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.

### Give a permanent namespace an expiry date

`POST /api/v1/clusters/{cluster_id}/namespaces/{ns}/expiration:set`

Permission: `namespaces:write`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/namespaces/payments-dev/expiration:set -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: 0d5f3c1e-7a44-4f0b-9b55-3f1a2c8e6d10' -H 'If-Match: "3f9a1c0b7e2d4a68"' -H 'Content-Type: application/json' -d '{"justification": "A load test this sprint", "until": "2026-12-17"}'
```

The run sent `POST /api/v1/clusters/CRC/namespaces/notes-dev/expiration:set` with this body:

```json
{
  "justification": "A load test this sprint",
  "until": "2026-12-17"
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
  "baseSha": "f13f28fcafc43bb4f6cbc2d6a90c4972cc5d64c5",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:40.914170Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:41.019012Z",
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
    "events": "/api/v1/requests/req-20261126-0012/events",
    "self": "/api/v1/requests/req-20261126-0012"
  },
  "mergeSha": null,
  "namespace": "notes-dev",
  "planHash": "003c86c680c76087dc054ff674759766b1a47df8384510b92d785f80c1c8d389",
  "plugin": "namespaces",
  "pr": null,
  "reason": "expiration:set",
  "requestId": "req-20261126-0012",
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
  "updatedAt": "2026-11-26T18:48:40.818144Z"
}
```

The run sent `POST /api/v1/clusters/CRC/namespaces/notes-dev/expiration:set?dryRun=true` with this body:

```json
{
  "justification": "A load test this sprint",
  "until": "2026-12-17"
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
    "cpu": 0.25,
    "fresh": true,
    "memory": 0.2,
    "reserved": {
      "cpu": 24.0,
      "memory": 51539607552
    },
    "source": "simulated",
    "status": "fits"
  },
  "changes": {
    "clusters/CRC/namespaces/notes-dev/namespace.yaml": "changed"
  },
  "etag": "cea2a7394431421b",
  "files": {
    "clusters/CRC/namespaces/notes-dev/namespace.yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: notes-dev\n  labels:\n    cmapi.net/cluster-id: CRC\n    cmapi.net/env: dev\n    cmapi.net/expiry: managed\n    cmapi.net/managed: 'true'\n    cmapi.net/requested-by-user: ola\n    cmapi.net/tier: small\n    cmapi.net/cost-center: cc-4410\n    cmapi.net/team: payments\n  annotations:\n    argocd.argoproj.io/sync-options: Prune=confirm,ServerSideApply=true\n    cmapi.net/expires-at: '2026-12-17'\n    cmapi.net/instance: nonprod\n    cmapi.net/request-id: (planned)\n    cmapi.net/requested-by: ola@ephico2real.com\n    cmapi.net/team-dl: payments-team@ephico2real.com\n"
  },
  "findings": [],
  "metadata": null,
  "metadataDiff": {
    "annotations": {},
    "labels": {}
  },
  "planHash": "88c813d1902c603949465a37278a6d2dfb7a0bf231a805be2a987d625492591f",
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
  "usage": null
}
```

What the Kyverno bundle decided on each cluster, read from its policy reports, and the requests that cmapi refused before Git, with Kyverno's warnings on plans that went on.

### List policy rejections before Git

`GET /api/v1/policies/rejections`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/policies/rejections -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/policies/rejections?since=7d`.

The answer was 200 (`application/json`):

```json
{
  "from": "2026-11-19T18:48:42.567274Z",
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
      "firstAt": "2026-11-26T18:48:38.807646Z",
      "id": "rej-2",
      "lastAt": "2026-11-26T18:48:38.807646Z",
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

### List Kyverno results by cluster

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
      "asOf": "2026-11-26T18:48:42.398264Z",
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
        "live": "cb135714e86c14914098c9113b95f7dabf65bef09d4e0586db890143a319e861",
        "rendered": "cb135714e86c14914098c9113b95f7dabf65bef09d4e0586db890143a319e861"
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

### Get a directory user

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

Each cluster's quota commitment against its size, live from the watch of its quotas and nodes, and the groups of clusters by clusters.yaml: the Capacity tab. Each cluster's stored capacity snapshots, and placement: the clusters ranked for a new namespace, and a 15-minute hold on the first.

### Get cluster capacity by group

`GET /api/v1/capacity`

Permission: `capacity:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/capacity -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/capacity`.

The answer was 200 (`application/json`, `etag: "4bb363d068369cc6e99c950defea614c"`):

```json
{
  "clusters": [
    {
      "asOf": "2026-11-26T18:48:00Z",
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
      "snapshot": {
        "detail": "no snapshot yet",
        "source": null,
        "state": "none",
        "takenAt": null
      },
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
  "snapshotIntervalSeconds": 1800,
  "snapshotState": "stored",
  "source": "live",
  "staleAfterSeconds": 3600,
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

### Place a new namespace: rank the clusters and hold the first

`POST /api/v1/capacity:place`

Permission: `capacity:read`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/capacity:place -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"constraints": {"region": "us-central"}, "environment": "dev", "team": "billing", "tier": "small"}'
```

The run sent `POST /api/v1/capacity:place` with this body:

```json
{
  "constraints": {
    "region": "us-central"
  },
  "environment": "dev",
  "team": "billing",
  "tier": "small"
}
```

The answer was 201 (`application/json`):

```json
{
  "asOf": "2026-11-26T18:48:43Z",
  "clusterId": "CRC",
  "excluded": [],
  "expiresAt": "2026-11-26T19:03:43.455985Z",
  "placementId": "pl-20261126-38a98ad4",
  "ranked": [
    {
      "basis": "simulated",
      "boundBy": "cpu",
      "clusterId": "CRC",
      "cpu": {
        "quotaHeadroomAfter": 72000,
        "quotaHeadroomBefore": 80000,
        "unit": "millicores",
        "usageP95": null,
        "zoneFailureHeadroomAfter": null
      },
      "factors": {
        "balance": 0.4375,
        "quotaHeadroom": 0.5625,
        "teamAffinity": 0.0,
        "usageHeadroom": 0.0,
        "zoneSpread": 0.0
      },
      "memory": {
        "quotaHeadroomAfter": 223338299392,
        "quotaHeadroomBefore": 240518168576,
        "unit": "bytes",
        "usageP95": null,
        "zoneFailureHeadroomAfter": null
      },
      "reserved": true,
      "score": 29,
      "snapshotAt": "2026-11-26T18:30:00Z"
    }
  ],
  "request": {
    "constraints": {
      "clusterSelector": null,
      "region": "us-central",
      "zones": []
    },
    "cpu": 8000,
    "environment": "dev",
    "memory": 17179869184,
    "pods": 50,
    "team": "billing",
    "tier": "small"
  }
}
```

The run sent `POST /api/v1/capacity:place?dryRun=true` with this body:

```json
{
  "constraints": {
    "region": "us-central"
  },
  "environment": "dev",
  "team": "payments",
  "tier": "small"
}
```

The answer was 200 (`application/json`):

```json
{
  "asOf": "2026-11-26T18:48:43Z",
  "clusterId": null,
  "excluded": [],
  "expiresAt": null,
  "placementId": null,
  "ranked": [
    {
      "basis": "simulated",
      "boundBy": "cpu",
      "clusterId": "CRC",
      "cpu": {
        "quotaHeadroomAfter": 72000,
        "quotaHeadroomBefore": 80000,
        "unit": "millicores",
        "usageP95": null,
        "zoneFailureHeadroomAfter": null
      },
      "factors": {
        "balance": 0.4375,
        "quotaHeadroom": 0.5625,
        "teamAffinity": 1.0,
        "usageHeadroom": 0.0,
        "zoneSpread": 0.0
      },
      "memory": {
        "quotaHeadroomAfter": 223338299392,
        "quotaHeadroomBefore": 240518168576,
        "unit": "bytes",
        "usageP95": null,
        "zoneFailureHeadroomAfter": null
      },
      "reserved": false,
      "score": 39,
      "snapshotAt": "2026-11-26T18:30:00Z"
    }
  ],
  "request": {
    "constraints": {
      "clusterSelector": null,
      "region": "us-central",
      "zones": []
    },
    "cpu": 8000,
    "environment": "dev",
    "memory": 17179869184,
    "pods": 50,
    "team": "payments",
    "tier": "small"
  }
}
```

### Get a cluster's capacity snapshot

`GET /api/v1/clusters/{cluster_id}/capacity`

Permission: `capacity:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/capacity -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/clusters/CRC/capacity`.

The answer was 200 (`application/json`):

```json
{
  "clusterId": "CRC",
  "env": "dev",
  "intervalSeconds": 1800,
  "scopes": [
    {
      "cpu": {
        "allocatable": 7800,
        "capacity": 7800,
        "limits": null,
        "quotaCommitted": 48000,
        "requested": null,
        "unit": "millicores",
        "usedAvg": null,
        "usedPeak": null
      },
      "memory": {
        "allocatable": 20493357056,
        "capacity": 20493357056,
        "limits": null,
        "quotaCommitted": 103079215104,
        "requested": null,
        "unit": "bytes",
        "usedAvg": null,
        "usedPeak": null
      },
      "nodes": {
        "diskPressure": 0,
        "memoryPressure": 0,
        "notReady": 0,
        "schedulable": 1,
        "total": 1
      },
      "pods": {
        "allocatable": 250,
        "running": null
      },
      "scope": "cluster"
    }
  ],
  "snapshot": {
    "detail": null,
    "source": "api",
    "state": "ok",
    "takenAt": "2026-11-26T18:30:00Z"
  },
  "staleAfterSeconds": 3600
}
```

### Run a cluster's capacity snapshot now

`POST /api/v1/clusters/{cluster_id}/capacity/snapshots:run`

Permission: `operations:run`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/clusters/CRC/capacity/snapshots:run -H "Authorization: Bearer $TOKEN"
```

The run sent `POST /api/v1/clusters/CRC/capacity/snapshots:run`.

The answer was 202 (`application/json`):

```json
{
  "clusterId": "CRC",
  "queued": true
}
```

The quota of each managed namespace on every cluster of the instance: a paged list, type-ahead matches and a CSV export.

### List namespace quotas

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
    "idle": 0,
    "near-limit": 0,
    "needs-attention": 0,
    "open-request": 0,
    "oversized": 0,
    "quota-tight": 0,
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
      "used": 0.0,
      "verdict": "insufficient-data",
      "verdictDay": null,
      "verdictKind": "info",
      "verdictReason": "No usage source is configured on this instance (capacity.yaml usage.source is none), so there is no 14-day usage.",
      "verdictResources": []
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
name,clusterId,env,team,tier,cpuUsed,cpuHard,memoryUsed,memoryHard,podsUsed,podsHard,used,expiresAt,tierOutdated,verdict
payments-dev,CRC,dev,payments,small,0,8,0,16Gi,0,50,0.0,,False,insufficient-data
```

### List quota search suggestions

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

### Get the tier catalog

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
      "baseSha": "cb5c898bb9e87c673d2f8ea2db640d276b35b5a0",
      "beyondTier": null,
      "clusterId": "CRC",
      "createdAt": "2026-11-26T18:48:17.431998Z",
      "env": "dev",
      "events": [
        {
          "at": "2026-11-26T18:48:17.539455Z",
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
        "events": "/api/v1/requests/req-20261126-0002/events",
        "self": "/api/v1/requests/req-20261126-0002"
      },
      "mergeSha": null,
      "namespace": "payments-dev",
      "planHash": "11b771c07365e3c8936ddb4a02620ba79697364721fcd5cb36905404aabe4311",
      "plugin": "namespaces",
      "pr": null,
      "reason": null,
      "requestId": "req-20261126-0002",
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
      "updatedAt": "2026-11-26T18:48:17.335060Z"
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

### Get a request

`GET /api/v1/requests/{request_id}`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001 -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/requests/req-20261126-0001`.

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
  "createdAt": "2026-11-26T18:48:14.925300Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:15.008254Z",
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
    "events": "/api/v1/requests/req-20261126-0001/events",
    "pr": "https://git.test/pulls/1",
    "self": "/api/v1/requests/req-20261126-0001"
  },
  "mergeSha": "cb5c898b",
  "namespace": "payments-dev",
  "planHash": "05f11d47a3e765a127f8a5219e764c0f8f33cc0278c08556a9249bfdb49d3737",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261126-0001",
    "head": "cb5c898b",
    "number": 1,
    "url": "https://git.test/pulls/1"
  },
  "reason": null,
  "requestId": "req-20261126-0001",
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
  "updatedAt": "2026-11-26T18:48:15.594172Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.
`body.events` has 9 items in the run. The first is shown.

### Get a request's approval status

`GET /api/v1/requests/{request_id}/approval-status`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001/approval-status -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/requests/req-20261126-0001/approval-status`.

The answer was 200 (`application/json`):

```json
{
  "approved": true,
  "planHash": "05f11d47a3e765a127f8a5219e764c0f8f33cc0278c08556a9249bfdb49d3737",
  "requestId": "req-20261126-0001",
  "status": "synced"
}
```

### List a request's events

`GET /api/v1/requests/{request_id}/events`

Permission: `requests:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001/events -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/requests/req-20261126-0001/events`.

The answer was 200 (`application/json`):

```json
{
  "events": [
    {
      "at": "2026-11-26T18:48:15.008254Z",
      "by": "ola",
      "event": "plan_auto_approved",
      "note": "auto:baseline-rnd-namespace",
      "status": "approved"
    }
  ],
  "requestId": "req-20261126-0001",
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

The run sent `POST /api/v1/requests/req-20261126-0002:approve` with this body:

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
        "at": "2026-11-26T18:48:17.776975Z",
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
  "baseSha": "cb5c898bb9e87c673d2f8ea2db640d276b35b5a0",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:17.431998Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:17.539455Z",
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
    "events": "/api/v1/requests/req-20261126-0002/events",
    "self": "/api/v1/requests/req-20261126-0002"
  },
  "mergeSha": null,
  "namespace": "payments-dev",
  "planHash": "11b771c07365e3c8936ddb4a02620ba79697364721fcd5cb36905404aabe4311",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261126-0002",
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
  "updatedAt": "2026-11-26T18:48:17.632898Z"
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

The run sent `POST /api/v1/requests/req-20261126-0005:cancel`.

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
  "baseSha": "89561eb2e7666c1c6bed1799a90032085b13f57b",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:24.449033Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:24.522333Z",
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
    "events": "/api/v1/requests/req-20261126-0005/events",
    "self": "/api/v1/requests/req-20261126-0005"
  },
  "mergeSha": null,
  "namespace": "ledger-dev",
  "planHash": "ce23c0cd48b7098de4a91804d23c91cd0e63dcdfdb7cc60f129d6ca6ab1e591c",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261126-0005",
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
  "updatedAt": "2026-11-26T18:48:24.994011Z"
}
```

`body.events` has 2 items in the run. The first is shown.

### Reject a request

`POST /api/v1/requests/{request_id}:reject`

Permission: `requests:reject`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:reject -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"comment": "Use the medium tier"}'
```

The run sent `POST /api/v1/requests/req-20261126-0006:reject` with this body:

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
  "baseSha": "89561eb2e7666c1c6bed1799a90032085b13f57b",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:24.759713Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:24.828693Z",
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
    "events": "/api/v1/requests/req-20261126-0006/events",
    "self": "/api/v1/requests/req-20261126-0006"
  },
  "mergeSha": null,
  "namespace": "billing-dev",
  "planHash": "b77ec5289eb0b4282343645ac4440ee6fcdd533d0e1cbe3b2aed7e8509c4713a",
  "plugin": "namespaces",
  "pr": null,
  "reason": null,
  "requestId": "req-20261126-0006",
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
  "updatedAt": "2026-11-26T18:48:24.783312Z"
}
```

`body.events` has 2 items in the run. The first is shown.

### Retry a failed request

`POST /api/v1/requests/{request_id}:retry`

Permission: `requests:retry`.

```bash
curl -X POST https://cmapi-nonprod.ephico2real.com/api/v1/requests/req-20261105-0001:retry -H "Authorization: Bearer $TOKEN"
```

The run sent `POST /api/v1/requests/req-20261126-0007:retry`.

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
  "baseSha": "89561eb2e7666c1c6bed1799a90032085b13f57b",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:27.402070Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:27.451579Z",
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
    "events": "/api/v1/requests/req-20261126-0007/events",
    "pr": "https://git.test/pulls/5",
    "self": "/api/v1/requests/req-20261126-0007"
  },
  "mergeSha": null,
  "namespace": "search-dev",
  "planHash": "fecc27fbe1a49f538841aaebbe834a08ceabc498b2909ad001ff6da71c5adcd6",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261126-0007",
    "head": "f2384f00",
    "number": 5,
    "url": "https://git.test/pulls/5"
  },
  "reason": null,
  "requestId": "req-20261126-0007",
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
  "updatedAt": "2026-11-26T18:48:29.816462Z"
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

The run sent `POST /api/v1/requests/req-20261126-0009:revert`.

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
  "baseSha": "89561eb2e7666c1c6bed1799a90032085b13f57b",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:36.769750Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:36.817797Z",
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
    "events": "/api/v1/requests/req-20261126-0009/events",
    "pr": "https://git.test/pulls/8",
    "self": "/api/v1/requests/req-20261126-0009"
  },
  "mergeSha": "88a27e68",
  "namespace": "orders-dev",
  "planHash": "03fd76c8f693465e06c256e948056f08e1e7d1d3cfdec5f4ce4d3c5cd081c85d",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261126-0009",
    "head": "88a27e68",
    "number": 8,
    "url": "https://git.test/pulls/8"
  },
  "reason": null,
  "requestId": "req-20261126-0009",
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
  "updatedAt": "2026-11-26T18:48:37.307126Z"
}
```

`body.approval.reasons` has 2 items in the run. The first is shown.
`body.events` has 8 items in the run. The first is shown.

## Operations

The instance itself: who the caller is and what the caller can do, the clusters that the instance knows, the rules of a new namespace's labels and annotations, and the version of the running build.

### List known clusters

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
      "checkedAt": "2026-11-26T18:48:12.448398Z",
      "clusterId": "CRC",
      "environment": "dev",
      "findingDetails": [],
      "findings": [],
      "gitopsPath": "clusters/CRC",
      "labels": {
        "region": "us-central"
      },
      "lastProbeAt": "2026-11-26T18:48:12.448398Z",
      "secretName": "cmapi-cluster-crc",
      "serverVersion": "v1.35.6-fake",
      "status": "connected",
      "statusSince": "2026-11-26T18:48:12.448398Z",
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
  "checkedAt": "2026-11-26T18:48:13.221441Z",
  "clusterId": "CRC",
  "environment": "dev",
  "findingDetails": [],
  "findings": [],
  "gitopsPath": "clusters/CRC",
  "labels": {
    "region": "us-central"
  },
  "lastProbeAt": "2026-11-26T18:48:13.221441Z",
  "secretName": "cmapi-cluster-crc",
  "serverVersion": "v1.35.6-fake",
  "status": "connected",
  "statusSince": "2026-11-26T18:48:12.448398Z",
  "tokenExpiresAt": null,
  "trust": {
    "downgrade": false,
    "serverName": null,
    "source": "trusted"
  },
  "writes": true
}
```

### Get the caller's identity and permissions

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

### Get namespace label and annotation rules

`GET /api/v1/metadata-keys`

Permission: `objects:read`.

```bash
curl -X GET https://cmapi-nonprod.ephico2real.com/api/v1/metadata-keys -H "Authorization: Bearer $TOKEN"
```

The run sent `GET /api/v1/metadata-keys`.

The answer was 200 (`application/json`, `etag: "1f774baf9bf093f8d4ebc497eb0d5b96"`):

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
        "x-cmapi-edit": {
          "mode": "optional",
          "reason": "Needs namespaces:protect in the namespace's environment. Changing this key needs one more approval.",
          "sensitive": true
        },
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
        "x-cmapi-edit": {
          "mode": "required",
          "reason": "Required on every namespace.",
          "sensitive": false
        },
        "x-cmapi-format": "email-in-domains",
        "x-cmapi-rule": "an address in ['ephico2real.com']"
      },
      "do-not-delete": {
        "description": "An operator only (namespaces:protect): another caller gets 403 forbidden.",
        "type": "string",
        "x-cmapi-edit": {
          "mode": "optional",
          "reason": "Needs namespaces:protect in the namespace's environment. Changing this key needs one more approval.",
          "sensitive": true
        },
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
      ],
      "sensitiveKeys": [
        "network.ephico2real.com/zone"
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
        "x-cmapi-edit": {
          "mode": "optional",
          "reason": null,
          "sensitive": false
        },
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
        "x-cmapi-edit": {
          "mode": "optional",
          "reason": null,
          "sensitive": false
        },
        "x-cmapi-rule": "must match ^cc-[0-9]{4}$"
      },
      "cmapi.net/protected": {
        "description": "An operator only (namespaces:protect): another caller gets 403 forbidden.",
        "maxLength": 63,
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "type": "string",
        "x-cmapi-edit": {
          "mode": "optional",
          "reason": "Needs namespaces:protect in the namespace's environment. Changing this key needs one more approval.",
          "sensitive": true
        },
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
        "x-cmapi-edit": {
          "mode": "optional",
          "reason": null,
          "sensitive": false
        },
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
        "x-cmapi-edit": {
          "mode": "required",
          "reason": "Required on every namespace. Changing this key needs one more approval.",
          "sensitive": true
        },
        "x-cmapi-rule": "must match ^[a-z0-9-]{2,40}$"
      },
      "do-not-delete": {
        "description": "An operator only (namespaces:protect): another caller gets 403 forbidden.",
        "maxLength": 63,
        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?)?$",
        "type": "string",
        "x-cmapi-edit": {
          "mode": "optional",
          "reason": "Needs namespaces:protect in the namespace's environment. Changing this key needs one more approval.",
          "sensitive": true
        },
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
      ],
      "sensitiveKeys": [
        "network.ephico2real.com/zone"
      ]
    }
  },
  "x-cmapi-expiration": {
    "environments": {
      "dev": {
        "allowedAtCreate": true,
        "enabled": true,
        "graceDays": 7,
        "maxLifetimeDays": 180,
        "notifyDaysBefore": [
          14
        ]
      },
      "rnd": {
        "allowedAtCreate": true,
        "enabled": true,
        "graceDays": 7,
        "maxLifetimeDays": 180,
        "notifyDaysBefore": [
          14
        ]
      }
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
`body.x-cmapi-expiration.environments.dev.notifyDaysBefore` has 3 items in the run. The first is shown.
`body.x-cmapi-expiration.environments.rnd.notifyDaysBefore` has 3 items in the run. The first is shown.

### Get the running build's version and commit

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

### Get the auto-approval switch state

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
  "setAt": "2026-11-26T18:48:25.333297+00:00",
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
  "setAt": "2026-11-26T18:48:25.279852+00:00",
  "setBy": "ada"
}
```

### List recent commits in cluster-configs

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
    "cb5c898b Merge cmapi/CRC/req-20261126-0001"
  ]
}
```

`body.log` has 2 items in the run. The first is shown.

### Get integration modes and health

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

### Get system KPIs

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
      "measuredAt": 1795718896.8385012,
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
    "sizeBytes": 9952279,
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
      "value": 0.657985
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

### List this instance's plugins

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
        "at": "2026-11-26T18:48:32.812729Z",
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
  "baseSha": "f2384f006831a8a6663be5efae93955878f7cae8",
  "beyondTier": null,
  "clusterId": "CRC",
  "createdAt": "2026-11-26T18:48:32.649396Z",
  "env": "dev",
  "events": [
    {
      "at": "2026-11-26T18:48:32.676007Z",
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
    "events": "/api/v1/requests/req-20261126-0008/events",
    "pr": "https://git.test/pulls/7",
    "self": "/api/v1/requests/req-20261126-0008"
  },
  "mergeSha": "89561eb2",
  "namespace": "search-dev",
  "planHash": "c490196334dad591c3196aa59224d119861392145360aee1d428c93109235dbe",
  "plugin": "namespaces",
  "pr": {
    "branch": "cmapi/CRC/req-20261126-0008",
    "head": "89561eb2",
    "number": 7,
    "url": "https://git.test/pulls/7"
  },
  "reason": null,
  "requestId": "req-20261126-0008",
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
  "updatedAt": "2026-11-26T18:48:34.524666Z"
}
```

`body.events` has 10 items in the run. The first is shown.

## Problems

Each refusal is an RFC 9457 problem with the media type `application/problem+json`. These are the ones that the run met.

### 409 `change-pending`

`PATCH /api/v1/clusters/CRC/namespaces/audit-dev`, with a body:

```json
{
  "code": "change-pending",
  "detail": "req-20261126-0015 holds audit-dev",
  "requestId": "req-20261126-0015",
  "status": 409,
  "title": "change pending",
  "type": "https://cmapi.ephico2real.com/problems/change-pending"
}
```

### 404 `cluster-not-found`

`GET /api/v1/clusters/NOPE/capacity`:

```json
{
  "code": "cluster-not-found",
  "detail": "Unknown cluster NOPE",
  "status": 404,
  "title": "cluster not found",
  "type": "https://cmapi.ephico2real.com/problems/cluster-not-found"
}
```

### 400 `dry-run-not-supported`

`POST /api/v1/admin/auto-approval:pause?dryRun=true`, with a body:

```json
{
  "code": "dry-run-not-supported",
  "detail": "This call has no dry run, and nothing was done",
  "status": 400,
  "title": "dry run not supported",
  "type": "https://cmapi.ephico2real.com/problems/dry-run-not-supported"
}
```

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

### 409 `idempotency-replay`

`PATCH /api/v1/clusters/CRC/namespaces/audit-dev`, with a body:

```json
{
  "code": "idempotency-replay",
  "detail": "Idempotency-Key was used for a different request",
  "requestId": "req-20261126-0015",
  "status": 409,
  "title": "idempotency replay",
  "type": "https://cmapi.ephico2real.com/problems/idempotency-replay"
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

`POST /api/v1/requests/req-20261126-0007:revert`:

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

### 422 `no-change`

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true`, with a body:

```json
{
  "code": "no-change",
  "detail": "The request changes nothing",
  "status": 422,
  "title": "no change",
  "type": "https://cmapi.ephico2real.com/problems/no-change"
}
```

### 422 `no-placement`

`POST /api/v1/capacity:place`, with a body:

```json
{
  "code": "no-placement",
  "detail": "No dev cluster can take 8 cores and 16Gi: every candidate was excluded",
  "excluded": [
    {
      "clusterId": "CRC",
      "detail": "region us-central, not eu-west",
      "reason": "outside-region"
    }
  ],
  "status": 422,
  "title": "no placement",
  "type": "https://cmapi.ephico2real.com/problems/no-placement"
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

### 422 `placement-mismatch`

`POST /api/v1/clusters/CRC/namespaces?dryRun=true`, with a body:

```json
{
  "code": "placement-mismatch",
  "detail": "Placement pl-20261126-38a98ad4 was made for another target: the placement's team is 'billing', the create's 'payments'",
  "status": 422,
  "title": "placement mismatch",
  "type": "https://cmapi.ephico2real.com/problems/placement-mismatch"
}
```

### 422 `placement-not-found`

`POST /api/v1/clusters/CRC/namespaces?dryRun=true`, with a body:

```json
{
  "code": "placement-not-found",
  "detail": "No active placement pl-20260101-00000000: it expired, was used by another create, or never existed. Place again.",
  "status": 422,
  "title": "placement not found",
  "type": "https://cmapi.ephico2real.com/problems/placement-not-found"
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
  "etag": "f58b8be265a84def",
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

### 422 `validation-failed`

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true`, with a body:

```json
{
  "code": "validation-failed",
  "detail": "The request is not valid: body.labels: Input should be a valid dictionary",
  "errors": [
    {
      "code": "dict_type",
      "field": "body.labels",
      "message": "Input should be a valid dictionary"
    }
  ],
  "status": 422,
  "title": "validation failed",
  "type": "https://cmapi.ephico2real.com/problems/validation-failed"
}
```

### 412 `precondition-failed` (Get cluster capacity by group)

`GET /api/v1/capacity`:

```json
{
  "code": "precondition-failed",
  "detail": "If-Match does not list the current ETag of this answer: read it again",
  "etag": "4adeb7dd5ddbc10342ec59a4bcdde36b",
  "status": 412,
  "title": "precondition failed",
  "type": "https://cmapi.ephico2real.com/problems/precondition-failed"
}
```

### 412 `precondition-failed` (Get namespace label and annotation rules)

`GET /api/v1/metadata-keys`:

```json
{
  "code": "precondition-failed",
  "detail": "If-Match does not list the current ETag of this answer: read it again",
  "etag": "1f774baf9bf093f8d4ebc497eb0d5b96",
  "status": 412,
  "title": "precondition failed",
  "type": "https://cmapi.ephico2real.com/problems/precondition-failed"
}
```

### 404 `cluster-not-found` (Get a namespace and its ETag)

`GET /api/v1/clusters/NOPE/namespaces/payments-dev`:

```json
{
  "code": "cluster-not-found",
  "detail": "Unknown cluster NOPE",
  "status": 404,
  "title": "cluster not found",
  "type": "https://cmapi.ephico2real.com/problems/cluster-not-found"
}
```

### 404 `object-not-found` (Get a namespace and its ETag)

`GET /api/v1/clusters/CRC/namespaces/not-there-dev`:

```json
{
  "code": "object-not-found",
  "detail": "not-there-dev is not on CRC and not in Git",
  "status": 404,
  "title": "object not found",
  "type": "https://cmapi.ephico2real.com/problems/object-not-found"
}
```

### 404 `cluster-not-found` (List managed namespaces on a cluster)

`GET /api/v1/clusters/NOPE/namespaces?q=pay`:

```json
{
  "code": "cluster-not-found",
  "detail": "Unknown cluster NOPE",
  "status": 404,
  "title": "cluster not found",
  "type": "https://cmapi.ephico2real.com/problems/cluster-not-found"
}
```

### 422 `validation-failed` (List managed namespaces on a cluster)

`GET /api/v1/clusters/CRC/namespaces?limit=0`:

```json
{
  "code": "validation-failed",
  "detail": "The request is not valid: query.limit: Input should be greater than or equal to 1",
  "errors": [
    {
      "code": "greater_than_equal",
      "field": "query.limit",
      "message": "Input should be greater than or equal to 1"
    }
  ],
  "status": 422,
  "title": "validation failed",
  "type": "https://cmapi.ephico2real.com/problems/validation-failed"
}
```

### 404 `cluster-not-found` (Change a namespace)

`PATCH /api/v1/clusters/NOPE/namespaces/payments-dev?dryRun=true`, with a body:

```json
{
  "code": "cluster-not-found",
  "detail": "Unknown cluster NOPE",
  "status": 404,
  "title": "cluster not found",
  "type": "https://cmapi.ephico2real.com/problems/cluster-not-found"
}
```

### 403 `forbidden` (Change a namespace)

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true`, with a body:

```json
{
  "code": "forbidden",
  "detail": "Missing permission namespaces:write: no role in your token grants it (roles: ['cmapi-approver'])",
  "status": 403,
  "title": "forbidden",
  "type": "https://cmapi.ephico2real.com/problems/forbidden"
}
```

### 400 `idempotency-key-required` (Change a namespace)

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev`, with a body:

```json
{
  "code": "idempotency-key-required",
  "detail": "Idempotency-Key header is required on writes",
  "status": 400,
  "title": "idempotency key required",
  "type": "https://cmapi.ephico2real.com/problems/idempotency-key-required"
}
```

### 404 `object-not-found` (Change a namespace)

`PATCH /api/v1/clusters/CRC/namespaces/not-there-dev?dryRun=true`, with a body:

```json
{
  "code": "object-not-found",
  "detail": "not-there-dev is not managed on CRC",
  "status": 404,
  "title": "object not found",
  "type": "https://cmapi.ephico2real.com/problems/object-not-found"
}
```

### 422 `policy-violation` (Change a namespace)

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true`, with a body:

```json
{
  "code": "policy-violation",
  "detail": "Metadata refused",
  "errors": [
    {
      "code": "reserved_key",
      "key": "cmapi.net/tier"
    },
    {
      "code": "invalid_key",
      "detail": "prefix not allowed",
      "key": "other.example/x"
    },
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

### 401 `unauthenticated` (Change a namespace)

`PATCH /api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true`, with a body, with no token:

```json
{
  "code": "unauthenticated",
  "detail": "Bearer token required",
  "status": 401,
  "title": "unauthenticated",
  "type": "https://cmapi.ephico2real.com/problems/unauthenticated"
}
```

### 400 `invalid-sort` (Export the quota list as CSV)

`GET /api/v1/quotas:export?sort=nope`:

```json
{
  "code": "invalid-sort",
  "detail": "Unknown sort nope",
  "status": 400,
  "title": "invalid sort",
  "type": "https://cmapi.ephico2real.com/problems/invalid-sort"
}
```
<!-- examples:end -->
