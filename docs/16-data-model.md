# The data model of the service

This document describes each table of the cmapi database. It says only what the migrations and the code do. The column tables come from a live database at the head of the migrations, so they cannot differ from the schema.

The database is PostgreSQL through CloudNativePG, or an existing PostgreSQL server (`docs/12`). The migrations are in `cmapi/src/cmapi/core/db/migrations/versions/`, and `cmapi-migrate` applies them before each API and worker process starts. The models are in `cmapi/src/cmapi/core/db/models.py`.

## What each table holds

| Table | One row is | Written by | Read by |
|---|---|---|---|
| `change_requests` | One write to a namespace: its plan, its approval rule, its requester, its pull request and its state | The API when a write is submitted (`RequestRepo.insert`, `core/db/repo.py:148`), then the API and the worker on each state change (`RequestRepo.move`, `repo.py:173`) | The request routes, the worker jobs, the KPI report |
| `request_events` | One state change or note of a request, in order | `RequestRepo.event` and `RequestRepo.move` (`repo.py:168-173`) | `GET /api/v1/requests/{request_id}/events` |
| `approvals` | One approval of one request by one person | `RequestRepo.record_approval` (`repo.py:216`) | The approval ledger (`repo.py:202`) |
| `jobs` | One unit of work for the worker, with its lease | `JobRepo.enqueue` (`repo.py:232`) | The worker: `JobRepo.claim` (`repo.py:245`) |
| `audit_events` | One recorded action: who, what and on which target | `AuditRepo.record` (`repo.py:304`) | No route reads it yet. `AuditRepo.recent` exists (`repo.py:308`) |
| `jwks_keys` | The last good signing keys of one issuer | `DbKeyStore.save` (`repo.py:339`) | `DbKeyStore.load` (`repo.py:334`), when a pod starts while Keycloak does not answer |
| `admin_switches` | One switch of the instance, for example `auto-approval`, with who set it | `SwitchRepo.set` (`repo.py:320`) | `SwitchRepo.get` (`repo.py:316`) |
| `approval_notifications` | One notice that a channel recorded for a request | The worker job `channel_notify` (`jobs/channel_notify.py:30`) | The same job, to send a notice only once |
| `expiration_notices` | One expiry notice for a namespace | No code writes it yet. The job `expire_check` is not built | No code reads it yet |

## Relations

`change_requests` is the centre. Four tables refer to it with a foreign key on `request_id`: `request_events`, `approvals`, `jobs` (optional) and `approval_notifications`. The other four tables have no foreign key.

```text
change_requests (request_id)
  |-- request_events.request_id          many events for one request
  |-- approvals.request_id               many approvals for one request, one for each person
  |-- jobs.request_id                    many jobs for one request; a job can have no request
  |-- approval_notifications.request_id  many notices for one request

audit_events, jwks_keys, admin_switches, expiration_notices: no foreign key
```

<!-- markdownlint-disable MD033 -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="diagrams/data-model/data-model.dark.png">
  <source srcset="diagrams/data-model/data-model.light.png">
  <img alt="The cmapi database has nine tables. change_requests is the centre: request_events, approvals, jobs and approval_notifications refer to it by request_id. audit_events, jwks_keys, admin_switches and expiration_notices have no foreign key." src="diagrams/data-model/data-model.light.png">
</picture>
<!-- markdownlint-enable MD033 -->

*One request has many events, many approvals, many jobs and many notices. No built code writes `expiration_notices` yet, so its box is dashed. The text block above is the twin of this figure.*

## The rules that the schema holds

These indexes and constraints carry correctness. The code relies on each of them.

| Rule | How the schema holds it | Source |
|---|---|---|
| One open request for each namespace | The partial unique index `uq_cr_open_namespace` on `(cluster_id, namespace)`, for the six open states | Migration `0001`, line 57 |
| One request for each idempotency key of a caller | The partial unique index `uq_cr_idempotency` on `(requester_sub, idempotency_key)` | Migration `0001`, line 60 |
| One approval for each person on a request | The unique index `uq_approvals_person` on `(request_id, approver_sub)` | Migration `0002` |
| An approval says which approving group it counted for | `approvals.counted_for`. Each new approval writes the column again for each approval of the request, because the ledger can move an earlier approval to another slot. It is null for an approval from before the column | Migration `0004` |
| One pending job for each kind, request and payload kind. A job with no request counts the request as empty. A second `enqueue` with the same three values does nothing (`JobRepo.enqueue`, `repo.py:232`) | The partial unique index `uq_jobs_pending` on `(kind, coalesce(request_id, ''), coalesce(payload->>'kind', ''))`, for rows with no `done_at` | Migration `0001`, line 108 |
| A worker that lost its lease cannot commit | `jobs.lease_generation` increases at each claim, and the commit checks it | Migration `0003`, `JobRepo.assert_lease` (`repo.py:258`) |
| A requester is a person or a service | The check `ck_cr_requester_kind` | Migration `0001`, line 54 |

The states of a request are in `cmapi/src/cmapi/core/lifecycle.py`. The six open states are `pending_approval`, `approved`, `pr_open`, `merged`, `awaiting_prune` and `sync_failed` (`core/db/models.py:17`).

## The models and the migrations agree

The migrations make the schema. The models in `cmapi/src/cmapi/core/db/models.py` describe the same schema for the code. A test of the service suite holds the two together (`cmapi/tests/service/test_models_match_migrations.py`):

| Check | What it finds |
|---|---|
| `alembic check` on the migrated test database | A column, a table or an index that only the models have, or only the database has. A model change with no migration fails here |
| The definition of each index, as PostgreSQL writes it, in a schema that is made from the models alone | A different WHERE of a partial index. `alembic check` does not see that (measured with Alembic 1.20.1 on PostgreSQL 16), and three unique indexes of cmapi are partial |

Before this check, the models did not declare eight indexes of the migrations. `alembic revision --autogenerate` would then have written a migration that drops them, the lock index `uq_cr_open_namespace` among them. The models now declare each index.

A changed server default is not compared. To add a column: change the model, write the migration, and run the suite.

## What the database does not hold

- The names and the employee ID of a requester are in `change_requests.requester` only. They are never written to Git (`cmapi/src/cmapi/core/identity/claims.py:43-48`).
- No token, password or client secret is in any table. `jwks_keys` holds public keys.
- The live state of a namespace is not stored. It comes from the watch cache of each cluster, in the memory of the process.

## What each column holds

The type, the null rule and the default of each column are in "The tables" at the end of this document. This part says what a column holds, and which code writes it. A column that this part does not list is a plain copy of its name.

### `change_requests`

One row is one write to one namespace. The row is the only record of a request: Git holds the result, and this table holds the plan, the decision and the history.

| Column | What it holds | Written by |
|---|---|---|
| `request_id` | `req-YYYYMMDD-NNNN`: the day and a number for that day. The number comes from the highest id of the day, under a transaction lock for the day (`RequestRepo.next_id`) | `Pipeline.submit` (`core/pipeline.py`) |
| `instance`, `cluster_id`, `namespace`, `env` | The instance name from `instance.yaml`, the cluster, the namespace, and the environment of that cluster | `Pipeline.submit` |
| `plugin`, `action` | The plugin that planned the write (`namespaces` today), and the action: `create`, `update` (a PATCH, or an expiry extension) or `delete` | `Pipeline.submit` |
| `status` | One of 13 states. See "The states" below | `RequestRepo.insert` and `RequestRepo.move`, from the table in `core/lifecycle.py` |
| `reason` | A short code for the cause of a request: `expiration:extend` for an expiry extension, `revert` for a revert request, `expired` for the delete that the expiry job opens (a rule of `approval-rules.yaml` reads it). Null for a plain write | `Pipeline.submit` |
| `justification` | The text that the requester wrote | `Pipeline.submit` |
| `team` | The value of the label `cmapi.net/team` at plan time. The daily allowance of auto-approvals counts requests for this value (`RequestRepo.auto_approvals_today`) | `Pipeline.submit` |
| `plan` | The stored plan, as JSON. See "The JSON columns" below | `Plan.stored` (`core/pipeline.py`) |
| `plan_hash` | SHA-256 of the rendered files. The worker checks that the files of the pull request still have this hash before it merges | `Pipeline.submit` |
| `base_sha` | The Git commit that the plan read. A change of the namespace folder in Git after this commit moves the request to `superseded` | `Pipeline.submit` |
| `requirement` | The approval requirement that the rules decided, as JSON (`requirement_to_json`, `repo.py`) | `Pipeline.submit` |
| `requester` | The record of the person and of the caller, as JSON. See "The JSON columns" below | `Requester.record` (`core/identity/checks.py`) |
| `requester_sub`, `requester_kind`, `requester_client`, `requester_username` | The person's token subject, `user` or `service`, the client that got the token, and the person's username. The ledger refuses `requester_sub` as an approver unless the rule has `selfApproval` | `Pipeline.submit` |
| `idempotency_key`, `idempotency_fingerprint` | The `Idempotency-Key` header and a hash of the body. The same key with the same body returns the first response. The same key with another body is `idempotency-replay` | `Pipeline.submit`; `RequestRepo.by_idempotency` clears both after 24 hours |
| `pr` | The pull request: `number`, `url`, `branch` and `head` (the head commit). Null until `open_pr` runs | `open_pr` (`jobs/open_pr.py`) |
| `merge_sha` | The merge commit of the pull request | `pr_checks` (`jobs/pr_checks.py`) |
| `attempts` | A counter that starts at 0. `:retry` sets it to 0 again (`cmapi/src/cmapi/routers/requests.py`). No built code adds to it | `:retry` |
| `created_at`, `updated_at` | The insert time, and the time of the last event. Each event of the request moves `updated_at` (`RequestRepo.event`) | Database default, `RequestRepo.event` |
| `approved_at` | The time of the last move to `approved` | `RequestRepo.insert` for an auto-approval, and `RequestRepo.move` |
| `merged_at` | The time of the move to `merged` | `RequestRepo.move` |
| `finished_at` | The time of the last move to `synced`, `rejected`, `cancelled`, `timeout`, `failed`, `superseded`, `reverted` or `sync_failed` | `RequestRepo.move` |

#### The states

The table `_T` in `cmapi/src/cmapi/core/lifecycle.py` holds each allowed move. No other code changes `status`.

| Group | States |
|---|---|
| Open: the request holds the lock of its namespace (the six states of `uq_cr_open_namespace`) | `pending_approval`, `approved`, `pr_open`, `merged`, `awaiting_prune`, `sync_failed` |
| Closed for good (`TERMINAL`) | `synced`, `rejected`, `cancelled`, `timeout`, `superseded`, `reverted` |
| Closed, and `:retry` can open it again | `failed` (the move `retry` goes to `approved`) |

`approved_at` and the other time columns follow the table above. A request in `failed` has no lock, so another request can take the namespace. `:retry` of a `failed` request then answers 409 `change-pending` (`RequestRepo.move`).

#### The JSON columns

| Column | Keys | Source |
|---|---|---|
| `plan` | `files` (the rendered files of the folder, path to text, null for a file that the plan removes), `prev` (the folder as Git held it), `changes` (path to `added`, `changed` or `removed`), `facts` (what the approval rules read, for example `beyondTier`, `beyondTierKeys`, `networkExposure`, `tierChange`, `quotaIncreasePct`, `keyClasses`), `capacity`, `spec` (the namespace spec that the renderer used), `findings` (each finding of the validator, with its severity and source) and `beyondTier` (the keys of a custom tier that differ from the tier, and the approvals that they add; null when none) | `Plan.stored` |
| `requirement` | `rule` (for example `rnd-create`), `slots` (each `group`, `count` and `reason`), `selfApproval`, `timeoutHours`, `reasons`, `auto` (`auto:<policy>`, `none-required`, or null), `autoFallback` (the guard that stopped a matching auto-approval policy) and `groupPath` (the `identity.groupPath` of the instance when the rule was decided) | `requirement_to_json` |
| `requester` | `requester` (the person: `sub`, `username`, `email`, `givenName`, `middleName`, `familyName`, `employeeId`, `kind`, and `clientId` when the person is an `Identity`), `automated`, and, when a service sent the request for a person: `submittedBy`, `submittedBySub` and `submittedByClient` | `Requester.record` |
| `pr` | `number`, `url`, `branch`, `head` | `open_pr` |

`submittedBySub` stays in the database. The API leaves it out of each view (`cmapi/src/cmapi/core/views.py`). A request keeps its own `groupPath`, so a later change of `identity.groupPath` cannot move the approvers of an open request. A row from before that key was written is read with the older template `/cmapi/cmapi-{name}` (`LEGACY_GROUP_PATH`, `core/authz.py`).

### `request_events`

One row is one event of one request. `idx_request_events_request` serves the read in order.

| Column | What it holds |
|---|---|
| `event` | The name of the event: a lifecycle event (`plan_needs_approval`, `plan_auto_approved`, `approved`, `rejected`, `cancel`, `approval_timeout`, `pr_opened`, `pr_failed`, `base_changed`, `merged`, `synced`, `prune_pending`, `prune_confirmed`, `sync_timeout`, `retry`, `revert`) or a note that a handler wrote: `approval`, `error`, `prune_confirm`, `revert_requested`, `revert_opened`, `revert_noop`, `pr_closed`, `ci`, `ci_wait`, `head_moved`, `sync_wait`, `argocd`, `applied`, `refused`, `prune_waiting`, `pruned` |
| `status` | The status of the request after the event |
| `by` | A username, or `worker`, `ci`, `argocd` or `cmapi-deliverer` |
| `note`, `detail` | A text, and optional JSON |

Sources: `core/lifecycle.py` for the lifecycle names, and each `repo.event(` call in `cmapi/src/cmapi/jobs/` and `cmapi/src/cmapi/routers/`.

### `approvals`

One row is one approval. A person can approve one time (`uq_approvals_person`).

| Column | What it holds |
|---|---|
| `approver_sub`, `username` | The approver's token subject and username |
| `groups` | The approver's groups from the token, as full paths, sorted. An approving group of the rule counts when its path (`identity.groupPath` applied to the short name) is in this list |
| `counted_for` | The short name of the approving group whose slot this approval fills (`approver-platform`, for example). `RequestRepo.record_approval` writes it for each approval of the request after each new approval, because the matching of approvers to slots can move an earlier approval. Null for an approval from before migration `0004`. The self-service rate reads it (`docs/17`) |
| `comment` | The approver's comment, an empty text when none |
| `relayed_by` | The client that relayed the approval, when a channel relayed it. No route accepts a relayed approval yet (`docs/14`) |
| `at` | The time of the approval |

### `jobs`

One row is one unit of work. The worker claims a due row with `FOR UPDATE SKIP LOCKED` (`JobRepo.claim`).

| Column | What it holds |
|---|---|
| `kind` | One of `open_pr`, `open_revert`, `pr_checks`, `watch_sync`, `prune`, `approval_timeout`, `channel_notify` (`HANDLERS`, `cmapi/src/cmapi/jobs/__init__.py`) |
| `request_id`, `cluster_id` | The request, and its cluster. `approval_timeout` has no request and no cluster. It runs again every hour and queues itself (`RECURRING`) |
| `payload` | Optional JSON. `channel_notify` has `kind`: `pending`, `approved`, `rejected` or `timeout`. `watch_sync` has `since`. `open_revert` has `by`. `approval_timeout` has `every` |
| `run_after` | The earliest time that a worker can claim the job. A retry moves it |
| `attempts` | Added 1 at each claim. At 5 attempts (`MAX_ATTEMPTS`), a failed job closes. If its request is `approved` or `pr_open`, the request moves to `failed`. If its request is `merged` or `awaiting_prune`, the request moves to `sync_failed` (`Worker._record_failure`, `cmapi/src/cmapi/worker.py`) |
| `last_error`, `locked_until`, `locked_by`, `lease_generation` | The last error (cut to 2000 characters), the end of the lease (300 seconds from the claim), the worker that holds it, and the fencing token |
| `done_at` | Set when the job ends. A row with `done_at` is out of `uq_jobs_pending` and `idx_jobs_due` |

### `audit_events`

One row is one action by one caller: `action` is for example `namespace.create`, `request.approve`, `request.reject`, `request.cancel`, `request.retry`, `request.revert`, `prune.confirm`, `auto-approval.pause`, `auto-approval.resume` or `quotas.export`. `target` is the object (`<cluster>/<namespace>`, a request ID, or `instance`). Each write route calls `AuditRepo.record`. No route reads the rows yet.

### `jwks_keys`, `admin_switches`

| Table | Rows |
|---|---|
| `jwks_keys` | One row for each issuer. `keys` is the list of signing keys as JSON. The row is replaced at each good fetch |
| `admin_switches` | One row for each switch. The one switch today is `auto-approval`, with `value` as `{"paused": true or false, "reason": text}`. `set_by` and `set_at` say who and when |

### `approval_notifications`

One row is one notice of one channel for one request. `channel` is `portal` or `email`. `kind` is the kind of the `channel_notify` job: `pending`, `approved`, `rejected` or `timeout`. The comment in `models.py` says `pending | decision`, and the code stores the four values. `recipients` is the list that the channel reports. `link_id` is the signed link of an email, and `used_at` is for the single use of that link. No code sets `used_at` yet. A channel that fails records `detail.error` and stops no other channel (`cmapi/src/cmapi/jobs/channel_notify.py`).

### `expiration_notices`

No code writes this table. The design is in `docs/01`, "Namespace expiration". `expires_at` is a date as text. `threshold_days` is 14, 7 or 1 for a notice before the date, 0 for the grace, and -1 for the delete (`models.py`).

## Caches, and why cmapi has no Redis or Valkey

The owner's rule, 2026-11-13: "we can use postgress for cache as well if needed so we don't have to use redis or vakkey". cmapi has no Redis and no Valkey, and adds none. The state that more than one replica must share is already in PostgreSQL:

| Shared state | Where it is | Expiry |
|---|---|---|
| The copy of the signing keys | `jwks_keys`, one row for each issuer, replaced at each good fetch | None. A newer fetch replaces the row |
| The idempotency records | `change_requests.idempotency_key` and `idempotency_fingerprint` | 24 hours from the creation of the request, by the database's `now()`. The lookup clears an older key (`RequestRepo.by_idempotency`, `core/db/repo.py:117`, #142) |
| The lock of a namespace | The index `uq_cr_open_namespace` | The request leaves the open states |
| The work queue | `jobs`, claimed with a lease | `locked_until` |

These caches are in the memory of each process, and are not shared: the signing keys for ten minutes (`cmapi/src/cmapi/core/auth.py:37`), the watch cache of each cluster, the directory lookups, and the rate limits (`cmapi/src/cmapi/core/ratelimit.py:1-4`).

**Decision, 2026-11-13: no new cache table and no cache library.** Nothing in the built code needs a general key-value cache that replicas share. When a feature needs one, the reference is the owner's `github.com/inkcasthq/kvpg` at commit `f654a121820f`: its contract v1 (rules S1 to S14), a logged table, expiry by the database's `now()`, and cleanup in batches. The choice between a small store of cmapi's own and a public Python library is open until then, with the checks in `OB1-PROMPT.md`. OB1 did not read kvpg for this decision, because the decision adds nothing.

## Diagram sources

The figure is `docs/diagrams/data-model/source.html`, drawn to diagram-kit's `/visual` standard. Render it again with `diagram-render docs/diagrams/data-model/source.html docs/diagrams/data-model data-model`. The picture, its text twin and the page change together.

## The tables

Written by `scripts/db-schema-doc.py` from the test database of the service suite (PostgreSQL 16 on `127.0.0.1:55432`, macOS, 2026-11-13). The test `tests/service/test_data_model_doc.py` fails when this part differs from the database. To write it again: `CMAPI_DATABASE_URL=... python scripts/db-schema-doc.py`, and replace the text between the two marker lines.

<!-- schema:begin -->
Migration head: `0004`. Tables: 9.

### `admin_switches`

| Column | Type | Null | Default |
|---|---|---|---|
| `name` | varchar(60) | no |  |
| `value` | jsonb | no |  |
| `set_by` | varchar(100) | no |  |
| `set_at` | timestamptz | no | `now()` |

| Constraint or index | Kind | Definition |
|---|---|---|
| `admin_switches_pkey` | Primary key | `PRIMARY KEY (name)` |

### `approval_notifications`

| Column | Type | Null | Default |
|---|---|---|---|
| `id` | bigint | no | `nextval('approval_notifications_id_seq'::regclass)` |
| `request_id` | varchar(40) | no |  |
| `channel` | varchar(40) | no |  |
| `kind` | varchar(20) | no |  |
| `recipients` | jsonb | no |  |
| `link_id` | varchar(64) | yes |  |
| `used_at` | timestamptz | yes |  |
| `sent_at` | timestamptz | no | `now()` |
| `detail` | jsonb | yes |  |

| Constraint or index | Kind | Definition |
|---|---|---|
| `approval_notifications_request_id_fkey` | Foreign key | `FOREIGN KEY (request_id) REFERENCES change_requests(request_id)` |
| `approval_notifications_pkey` | Primary key | `PRIMARY KEY (id)` |
| `idx_approval_notifications_request` | Index | `btree (request_id)` |

### `approvals`

| Column | Type | Null | Default |
|---|---|---|---|
| `id` | bigint | no | `nextval('approvals_id_seq'::regclass)` |
| `request_id` | varchar(40) | no |  |
| `approver_sub` | varchar(100) | no |  |
| `username` | varchar(100) | no |  |
| `groups` | jsonb | no |  |
| `comment` | text | no | `''::text` |
| `relayed_by` | varchar(100) | yes |  |
| `at` | timestamptz | no | `now()` |
| `counted_for` | varchar(100) | yes |  |

| Constraint or index | Kind | Definition |
|---|---|---|
| `approvals_request_id_fkey` | Foreign key | `FOREIGN KEY (request_id) REFERENCES change_requests(request_id)` |
| `approvals_pkey` | Primary key | `PRIMARY KEY (id)` |
| `idx_approvals_request` | Index | `btree (request_id)` |
| `uq_approvals_person` | Unique index | `btree (request_id, approver_sub)` |

### `audit_events`

| Column | Type | Null | Default |
|---|---|---|---|
| `id` | bigint | no | `nextval('audit_events_id_seq'::regclass)` |
| `at` | timestamptz | no | `now()` |
| `actor_sub` | varchar(100) | no |  |
| `actor_username` | varchar(100) | no |  |
| `actor_client` | varchar(100) | no | `''::character varying` |
| `action` | varchar(60) | no |  |
| `target` | varchar(255) | no |  |
| `detail` | jsonb | yes |  |

| Constraint or index | Kind | Definition |
|---|---|---|
| `audit_events_pkey` | Primary key | `PRIMARY KEY (id)` |
| `idx_audit_at` | Index | `btree (at)` |

### `change_requests`

| Column | Type | Null | Default |
|---|---|---|---|
| `request_id` | varchar(40) | no |  |
| `instance` | varchar(40) | no |  |
| `cluster_id` | varchar(63) | no |  |
| `namespace` | varchar(63) | no |  |
| `env` | varchar(20) | no |  |
| `plugin` | varchar(40) | no |  |
| `action` | varchar(20) | no |  |
| `status` | varchar(20) | no |  |
| `reason` | varchar(80) | yes |  |
| `justification` | text | yes |  |
| `team` | varchar(63) | yes |  |
| `plan` | jsonb | no |  |
| `plan_hash` | varchar(64) | no |  |
| `base_sha` | varchar(64) | yes |  |
| `requirement` | jsonb | yes |  |
| `requester` | jsonb | no |  |
| `requester_sub` | varchar(100) | no |  |
| `requester_kind` | varchar(8) | no |  |
| `requester_client` | varchar(100) | no |  |
| `requester_username` | varchar(100) | no |  |
| `idempotency_key` | varchar(100) | yes |  |
| `idempotency_fingerprint` | varchar(64) | yes |  |
| `pr` | jsonb | yes |  |
| `merge_sha` | varchar(64) | yes |  |
| `attempts` | integer | no | `0` |
| `created_at` | timestamptz | no | `now()` |
| `updated_at` | timestamptz | no | `now()` |
| `approved_at` | timestamptz | yes |  |
| `merged_at` | timestamptz | yes |  |
| `finished_at` | timestamptz | yes |  |

| Constraint or index | Kind | Definition |
|---|---|---|
| `ck_cr_requester_kind` | Check | `CHECK (((requester_kind)::text = ANY ((ARRAY['user'::character varying, 'service'::character varying])::text[])))` |
| `change_requests_pkey` | Primary key | `PRIMARY KEY (request_id)` |
| `idx_cr_namespace` | Index | `btree (cluster_id, namespace, created_at)` |
| `idx_cr_status` | Index | `btree (status, created_at)` |
| `uq_cr_idempotency` | Unique index | `btree (requester_sub, idempotency_key) WHERE (idempotency_key IS NOT NULL)` |
| `uq_cr_open_namespace` | Unique index | `btree (cluster_id, namespace) WHERE ((status)::text = ANY ((ARRAY['pending_approval'::character varying, 'approved'::character varying, 'pr_open'::character varying, 'merged'::character varying, 'awaiting_prune'::character varying, 'sync_failed'::character varying])::text[]))` |

### `expiration_notices`

| Column | Type | Null | Default |
|---|---|---|---|
| `id` | bigint | no | `nextval('expiration_notices_id_seq'::regclass)` |
| `cluster_id` | varchar(63) | no |  |
| `namespace` | varchar(63) | no |  |
| `expires_at` | varchar(10) | no |  |
| `threshold_days` | integer | no |  |
| `sent_at` | timestamptz | no | `now()` |
| `request_id` | varchar(40) | yes |  |
| `ok` | boolean | no | `true` |
| `detail` | text | no | `''::text` |

| Constraint or index | Kind | Definition |
|---|---|---|
| `expiration_notices_pkey` | Primary key | `PRIMARY KEY (id)` |
| `idx_expiration_notices_ns` | Index | `btree (cluster_id, namespace, expires_at, threshold_days)` |

### `jobs`

| Column | Type | Null | Default |
|---|---|---|---|
| `job_id` | bigint | no | `nextval('jobs_job_id_seq'::regclass)` |
| `kind` | varchar(40) | no |  |
| `request_id` | varchar(40) | yes |  |
| `cluster_id` | varchar(63) | no | `''::character varying` |
| `payload` | jsonb | yes |  |
| `run_after` | timestamptz | no | `now()` |
| `attempts` | integer | no | `0` |
| `last_error` | text | yes |  |
| `locked_until` | timestamptz | yes |  |
| `locked_by` | varchar(100) | yes |  |
| `done_at` | timestamptz | yes |  |
| `created_at` | timestamptz | no | `now()` |
| `lease_generation` | integer | no | `0` |

| Constraint or index | Kind | Definition |
|---|---|---|
| `jobs_request_id_fkey` | Foreign key | `FOREIGN KEY (request_id) REFERENCES change_requests(request_id)` |
| `jobs_pkey` | Primary key | `PRIMARY KEY (job_id)` |
| `idx_jobs_due` | Index | `btree (run_after) WHERE (done_at IS NULL)` |
| `uq_jobs_pending` | Unique index | `btree (kind, COALESCE(request_id, ''::character varying), COALESCE((payload ->> 'kind'::text), ''::text)) WHERE (done_at IS NULL)` |

### `jwks_keys`

| Column | Type | Null | Default |
|---|---|---|---|
| `issuer` | varchar(255) | no |  |
| `keys` | jsonb | no |  |
| `fetched_at` | timestamptz | no | `now()` |

| Constraint or index | Kind | Definition |
|---|---|---|
| `jwks_keys_pkey` | Primary key | `PRIMARY KEY (issuer)` |

### `request_events`

| Column | Type | Null | Default |
|---|---|---|---|
| `id` | bigint | no | `nextval('request_events_id_seq'::regclass)` |
| `request_id` | varchar(40) | no |  |
| `at` | timestamptz | no | `now()` |
| `event` | varchar(40) | no |  |
| `status` | varchar(20) | yes |  |
| `by` | varchar(100) | no |  |
| `note` | text | no | `''::text` |
| `detail` | jsonb | yes |  |

| Constraint or index | Kind | Definition |
|---|---|---|
| `request_events_request_id_fkey` | Foreign key | `FOREIGN KEY (request_id) REFERENCES change_requests(request_id)` |
| `request_events_pkey` | Primary key | `PRIMARY KEY (id)` |
| `idx_request_events_request` | Index | `btree (request_id, id)` |
<!-- schema:end -->
