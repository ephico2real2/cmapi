# Design A: the Policies part of portal slice 4 (#302)

Designer A, Opus 5.5 (`high`), 2026-11-17. Design only. Read on origin/main `abad314` (worktree `wt20-deploy`), Kyverno source at tag
v1.20.0 (commit `f666af0`, shallow clone in the scratchpad), and CRC read-only as `kubeadmin` and `--as` cmapi-reader.

## 1. What is there today (measured)

| Fact | Evidence |
|---|---|
| No `/api/v1/policies*` route in the contract | `grep -c '"/api/v1/policies' cmapi/contract/openapi.json` = 0 |
| A plan refusal is stored nowhere: the pipeline raises a 422 and counts `cmapi_validation_failures_total{source}` | `core/pipeline.py:287-296`, `core/observability.py:30` |
| Kyverno warnings of an accepted plan live only in `change_requests.plan.findings`; a dry run keeps nothing | `core/pipeline.py:83`, `plugins/namespaces/router.py:173` |
| CI refusals are request events (`ci`, `PR_FAILED`), not policy rows | `jobs/pr_checks.py:107-118` |
| The rendered bundle: 31 policies in dev, rnd, qa, uat; 32 in prod; names hashed past 63 characters; `index.json` maps name -> `{kind,key,rule}` | `examples/cluster-configs/policies/env/*/index.json`; `core/policygen.py:436-458` |
| CRC: `GET /apis/wgpolicyk8s.io/v1alpha2`, `/apis/openreports.io/v1alpha1`, `/apis/policies.kyverno.io` answer 404, also as cmapi-reader | `oc get --as=system:serviceaccount:cmapi-system:cmapi-reader --raw /apis/wgpolicyk8s.io/v1alpha2` -> NotFound; `/apis/apps/v1` -> 200 |
| CRC: listing reports as cmapi-reader answers **403**, not 404: authorization runs before the 404 | `oc get --as=... --raw '/apis/wgpolicyk8s.io/v1alpha2/clusterpolicyreports?limit=1'` -> Forbidden |
| CRC's cmapi-reader ClusterRole has two rules (core kinds, pods/pvcs); the baseline example already lists the report and policy kinds | `oc get clusterrole cmapi-reader`; `deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml:33-38`; `examples/baseline/cmapi-reader-rbac.yaml:60-68` |
| CRC's instance has no `policy` key: engine kyverno, every environment audit, CLI pinned `v1.20.0` | `deploy/manifests/environments/crc/20-config.yaml`; `core/policy.py:33`; `cmapi/Containerfile:11` |

Kyverno v1.20.0, from its source:
- A Namespace's results go to a **ClusterPolicyReport**, a namespaced resource's to a PolicyReport, one report per resource
  (`pkg/utils/report/new.go:90-106`; `docs/reviews/2026-11-17-issue-333/evidence/kind/outside.log`). No report grows with the cluster.
- Each policy on a report is a label `<family>/<policy name>`: `vpol.kyverno.io`, `ivpol`, `mpol`, `gpol`, `dpol`, `cpol` (ClusterPolicy),
  `pol` (`pkg/utils/report/metadata.go:34-47`). The policy kind comes from the label; no list of policies is needed.
- A ValidatingPolicy result's `rule` is always `validation` (`pkg/cel/policies/vpol/engine/engine.go:270`). The meaningful rule
  is cmapi's `index.json` entry. `warn` is only for an unscored policy (`pkg/engine/api/rulestatus.go:11`): an audit-mode
  violation of cmapi's bundle is `fail`, so the reader needs each environment's mode to know warning from denial.
- `properties.process` is `admission_review` or `background_scan` (outside.log).
- The size breaker counts EphemeralReports per source and **drops** new ones past `--maxAdmissionReports` /
  `--maxBackgroundReports` (default 10000; `cmd/kyverno/main.go:396`, `cmd/reports-controller/main.go:309`,
  `pkg/breaker/breaker.go:39-52`). A drop leaves no object; only the metric `kyverno_breaker_drops{circuit_name}` records it.
- `openreports.enabled: false` by default (`charts/kyverno/values.yaml:188-190`): reports stay in `wgpolicyk8s.io/v1alpha2`.

## 2. Decisions

| # | Decision | Rejected, and why |
|---|---|---|
| D1 | **Results come from a watch per cluster**, held by a new `PolicyReportCache` beside each connected cluster's `WatchCache`, in each API pod. The request path never calls a cluster (docs/01 "Reads are live", the WatchCache contract) | A live fan-out per request: N clusters x list per page, latency of the slowest cluster, API-server load per portal view. Storing reports in PostgreSQL from the worker: a second copy and a sync lag for data the watch already keeps current |
| D2 | **"Not installed" is decided by discovery**, `GET /apis/wgpolicyk8s.io/v1alpha2`: 404 -> `kyverno-not-installed`. Discovery is open to every authenticated user (`system:discovery`), so the answer is true even when the reader lacks the grant. Re-probed every 300 s; no watch thread and no log line per retry while absent | Reading the list's 404: on CRC the list answers 403 (measured), which would show "forbidden" for a cluster with no Kyverno. Treating any error as not installed: hides a missing grant |
| D3 | States per cluster, never a zero: `ok`, `syncing` (first list not done), `kyverno-not-installed`, `forbidden` (discovery 200, list 403: names the missing grant), `unreachable` (registry status not `connected`; `since` = `checked_at`), `stale` (no good read for 30 min, rows kept), `reports-in-openreports` (wgpolicy absent, `openreports.io/v1alpha1` served: not read in v1), `engine-off` (`policy.engine: none`: no cache is started, no cluster call). Counts are `null` unless `ok` or `stale` | A boolean "available": cannot say why, and the mockup's footnote requires the reason |
| D4 | **Memory bound**: the cache keeps a projection, not the object: per report its scope and, per result, `policy, family, rule, result, process, at`; the message only for `fail`, `warn`, `error` (cut to 500 characters); `pass` and `skip` only as counts per policy. Past 20,000 kept non-pass results per cluster the rest are counted, not kept, and the cluster says `truncated: true` | Whole objects (`managedFields`, pass messages "success" x every policy x every resource) |
| D5 | **Bundle drift is by digest, not tag.** No tag exists today: cmapi renders the bundle from its own configuration (#212, docs/02 line 1944). `policygen` adds `cmapi.net/policy-digest` (SHA-256 of the canonical JSON of the policy without its annotations) to each rendered policy. The cache lists `validatingpolicies` every 300 s; for the cluster's environment, `bundle.state` is `current` (same names, same digests), `drift` (`missing`, `extra`, `changed` names), `absent` (mode not off and no `cmapi.net/generated` policy) or `not-rendered` (mode off) | Comparing the cluster's spec with the render: the API server adds CRD defaults, so equal policies would differ. Names only: a tightened bound keeps its name. A bundle tag: does not exist; #244 is the bundle-hash follow-up and can reuse the digest |
| D6 | `policiesReady` = objects with `status.conditionStatus.ready: true` over all five `policies.kyverno.io` kinds the baseline grants (CRD v1.20.0 printer column `.status.conditionStatus.ready`). Legacy `kyverno.io` ClusterPolicy/Policy results (label families `cpol`, `pol`) are counted in `legacy` and left out of `items` and `policies`, as the mockup's footnote says | Showing legacy rows: the family is deprecated (docs/01) |
| D7 | **Breaker**: `breakerDropped` is `null` (not measured) in this slice. cmapi has no Thanos client; the Capacity part of #302 (#325) brings one, and then the value is `increase(kyverno_breaker_drops_total{circuit_name=~".*reports.*"}[24h])` per cluster (metric name with `_total` to verify on kind) | Counting EphemeralReports through the API: with a label selector `remainingItemCount` is unset (Kubernetes API reference, ListMeta `remainingItemCount`: "If the list request contained label or field selectors, then the number of remaining items is unknown"), so a per-source count means paging up to 10k objects every pass. Showing 0: forbidden by the mockup ("never as zero") |
| D8 | **One endpoint for the clusters, the per-policy counts and the rows**: `GET /policies/results` returns `clusters`, `policies` and a paged `items` from one cache snapshot, so the counts and the rows agree. docs/01's `GET /api/v1/policies` is folded in and its line updated | A separate `/policies`: two reads can straddle a watch event; a third contract surface |
| D9 | **Rejections are a new table `policy_rejections`** (migration 0006), one row per finding, written for every **non-dry-run** plan that cmapi refuses with a rule code, for the Kyverno and kubeconform warnings of a refused or accepted plan, and for a CI refusal (`pr_checks`). A refusal is written in its own session; a failed write is logged (`rejection_record_failed`) and counted, and the 422 is unchanged | Reading `audit_events`: a refusal is not audited today, and actions there are free text. Recording dry runs: the portal's forms dry-run on input (`hooks.ts:526-535`), which would flood the table with drafts; the 422 is shown in the form at once. Turning a failed record into a 500: the caller's refusal must not depend on the log |
| D10 | Rule codes recorded: `policy-violation` (one row per `errors[]` item: `policy` = its `code`, `key`, `source`, `path`, `detail`; plus one row per `findings[]` warning), `expiration-not-allowed`, `expiration-limit`, `expiration-in-past`, `reserved-namespace`, `invalid-namespace-name`, `capacity-exceeded`. Not recorded: `no-change`, routing codes (`environment-not-served`, `plugin-disabled`, `cluster-not-writable`), 400/409/412/428. `check` = the `index.json` entry of the policy at write time, so a later render does not rewrite history | Every 4xx: a stale etag is not a policy |
| D11 | Permissions per environment, as `/quotas` and `/expirations`: `/results` needs `objects:read` and shows only clusters whose environment the caller holds it in (cluster objects). `/rejections` needs `requests:read` and shows only those environments (an attempted request and who sent it, as `/requests` shows). Neither refuses: rows of other environments are left out (docs/14 step 4) | One new permission `policies:read`: every role that would get it has these two already (docs/14 table) |
| D12 | Partial answers are 200: one unreachable cluster is a state in the body, not a 503 (RFC 9110 §15.6.4: 503 means the server cannot handle the request; here it can, and says per cluster what it knows) | 503 when any cluster is down: hides the clusters that answered |
| D13 | Retention 90 days, purged by a daily recurring job `rejections_purge`; `since` accepts `1h`..`90d` (default `7d`, as the mockup) | No purge: unbounded table |
| D14 | `policies` is a **built-in plugin** (`plugins/policies`), as docs/02 line 2203 specifies, with the port `PolicyReportReader` (docs/02 line 2159) and `core/clients/policyreports.py` (line 2179). Recording rejections is core (pipeline side), so it runs with the plugin off | A core router: docs/02 already names the plugin |

## 3. GET /api/v1/policies/results

Query: `clusterId`, `env`, `namespace`, `policy` (exact), `result` (comma list of `fail`, `warn`, `error`; default all three; another
value 422 `validation-failed`), `q` (namespace or resource name contains), `sort` (`result`, default: fail, error, warn, then newest;
`name`: namespace, kind, resource, policy; `newest`), `limit`, `cursor`. The cursor binds the filters, `result` and `sort`
(`ListQuery.context`, as `/expirations` binds `state`). The Lister's row key is internal: `name` =
`<namespace>/<Kind>/<name>/<policy>/<rule>`, unique per result, so the keyset never skips a tie (`listquery.py:127-133`); it is
mapped to the item shape after paging. `policies` and `clusters[].counts` follow `clusterId`, `env` and `namespace`, not `result`
or `policy` (each row keeps its numbers, like `/expirations` facets).

CRC today (Kyverno not installed):

```json
{"clusters": [{"clusterId": "CRC", "env": "dev", "state": "kyverno-not-installed",
   "detail": "wgpolicyk8s.io/v1alpha2 is not served on CRC", "since": "2026-11-17T18:02:11Z",
   "bundle": null, "policiesReady": null, "counts": null, "legacy": null, "breakerDropped": null, "truncated": false}],
 "policies": [], "items": [],
 "page": {"limit": 50, "total": 0, "from": 0, "to": 0, "nextCursor": null, "prevCursor": null}, "letters": {}}
```

kind with Kyverno v1.20.0 and the dev bundle (the #333 case):

```json
{"clusters": [{"clusterId": "KIND", "env": "dev", "state": "ok", "detail": null, "since": "2026-11-17T14:21:10Z",
   "bundle": {"state": "current", "expected": 31, "onCluster": 31, "missing": [], "extra": [], "changed": []},
   "policiesReady": {"ready": 31, "total": 31}, "counts": {"pass": 412, "fail": 1, "warn": 0, "error": 0, "skip": 0},
   "legacy": {"policies": 0, "results": 0}, "breakerDropped": null, "truncated": false}],
 "policies": [{"name": "cmapi-metadata-dev-label-other-keys-prefix", "kind": "ValidatingPolicy",
   "description": "The labels and annotations that metadata-keys.yaml requires of a managed namespace in dev.",
   "check": {"kind": "label", "key": null, "rule": "prefix"}, "clusters": ["KIND"],
   "counts": {"pass": 2, "fail": 1, "warn": 0, "error": 0, "skip": 0}}],
 "items": [{"clusterId": "KIND", "env": "dev", "namespace": "orders-dev",
   "resource": {"apiVersion": "v1", "kind": "Namespace", "name": "orders-dev"},
   "policy": "cmapi-metadata-dev-label-other-keys-prefix", "policyKind": "ValidatingPolicy", "rule": "validation",
   "check": {"kind": "label", "key": null, "rule": "prefix"}, "result": "fail", "process": "background_scan",
   "message": "the label keys other.example/x are not declared in metadata-keys.yaml, and are outside extraLabels.allowOther.prefixes [\"\", \"*.ephico2real.com/\"]",
   "at": "2026-11-17T14:21:10Z"}],
 "page": {"limit": 50, "total": 1, "from": 1, "to": 1, "nextCursor": null, "prevCursor": null}, "letters": {"O": 1}}
```

`description` comes from the policy's `policies.kyverno.io/description` annotation, `check` from the bundle's `index.json`
(`CliValidator.index`); both are `null` for a policy cmapi did not render. `kind` comes from the report label family.

## 4. GET /api/v1/policies/rejections

Query: `since` (default `7d`), `clusterId`, `env`, `namespace`, `stage` (`plan`, `ci`), `severity` (`error`, `warning`), `source`
(`cmapi`, `kyverno`, `kubeconform`), `policy`, `sort` (`newest` default, `name`), `limit`, `cursor`. SQL selects `at >= since` and
the caller's environments, newest first, at most 10,000 rows (`truncated: true` past that); the Lister pages them with row key
`<namespace>/<id>`. `facets` count over every filter but `severity` and `stage`.

```json
{"items": [
  {"id": 412, "eventId": "0f3c2a9e-6a1d-4f0b-9b51-2d7e8c1a4b10", "at": "2026-11-17T18:05:02Z", "stage": "plan", "outcome": "refused",
   "severity": "error", "clusterId": "CRC", "env": "dev", "namespace": "payments-dev", "plugin": "namespaces", "action": "create",
   "problem": "policy-violation", "source": "cmapi", "policy": "invalid_value", "check": null, "key": "cmapi.net/team",
   "path": null, "message": "must match ^[a-z][a-z0-9-]{1,30}$", "requestId": null, "by": "ola"},
  {"id": 413, "eventId": "0f3c2a9e-6a1d-4f0b-9b51-2d7e8c1a4b10", "at": "2026-11-17T18:05:02Z", "stage": "plan", "outcome": "refused",
   "severity": "warning", "clusterId": "CRC", "env": "dev", "namespace": "payments-dev", "plugin": "namespaces", "action": "create",
   "problem": "policy-violation", "source": "kyverno", "policy": "cmapi-metadata-dev-label-cmapi-net-team-pattern",
   "check": {"kind": "label", "key": "cmapi.net/team", "rule": "pattern"}, "key": "cmapi.net/team",
   "path": "clusters/CRC/namespaces/payments-dev/namespace.yaml", "message": "the label cmapi.net/team is \"Pay_Ments\"; it must be: must match ^[a-z][a-z0-9-]{1,30}$",
   "requestId": null, "by": "ola"}],
 "page": {"limit": 50, "total": 2, "from": 1, "to": 2, "nextCursor": null, "prevCursor": null}, "letters": {"P": 2},
 "facets": {"error": 1, "warning": 1, "plan": 2, "ci": 0}, "since": "2026-11-10T18:05:30Z", "truncated": false}
```

The two messages are illustrative of the shape; the CRC proof records the real ones. A CI row has `stage: "ci"`, `requestId`, `by: "ci"`,
and `policy: "cmapi-check"` for a head that differs from the approved plan.

## 5. Table `policy_rejections` (migration `0006_policy_rejections.py`)

`id bigserial pk; event_id varchar(36) not null; at timestamptz not null default now(); stage varchar(8) not null check in
('plan','ci'); outcome varchar(10) not null check in ('refused','accepted'); severity varchar(8) not null check in
('error','warning'); cluster_id varchar(63) not null; env varchar(20) not null; namespace varchar(63) not null; plugin varchar(40)
not null; action varchar(20) not null; problem varchar(60); source varchar(12) not null; policy varchar(255) not null; check_ref
jsonb; key varchar(317); path varchar(255); message text not null (cut to 500); request_id varchar(40); actor_sub varchar(100) not
null; actor_username varchar(100) not null`. Indexes `(at)`, `(env, at)`. No foreign key to `change_requests` (a plan refusal has
no request). Text from the body is cut to the column width before insert, so a long name never turns the 422 into a 500.

## 6. The tab (mockup `Main.dc.html:863-913`, `policiesView` 2505-2536)

Data: `GET /admin/integrations` (`policy`: engine, environments, kyvernoVersion; the owner's comment), `GET /policies/results`,
`GET /policies/rejections?since=7d`. URL state `pcluster`, `ppolicy`, results cursor (MOCKUP-CONTRACT row `pcluster`, `ppolicy`).
- Head: the mockup's lede, "Pinned for this instance: Kyverno {kyvernoVersion}" (`not pinned outside the image` when null), and a
  pill `{fail} failing · {drift} clusters off the bundle`. Engine `none`: an info Alert "Kyverno is off for this instance
  (policy.engine: none). cmapi's own checks still refuse; no cluster report is read." and only the rejections panel.
- Clusters: the mockup's columns plus **Mode** (from `policy.environments[env]`: audit means a Kyverno fail was admitted and
  recorded, enforce means denied); Bundle shows `current`, `drift: N`, `absent` or `—`; Reports shows the state text and tone of D3.
  Every count is `—` when `counts` is null.
- Results by policy: chips `All clusters` + each `ok` cluster; rows from `policies` (no list in the portal); "Show failures"
  sets `policy`. Footnote from `legacy`.
- Failing, warning and erroring resources: `items`, paged with next and previous; empty "Nothing failing for this selection.".
- "Refused by cmapi before Git · last 7 days": When, Where (`cluster · namespace`), Stage (`plan (422)`, `plan (warning)`, `CI`),
  Policy or check (with `check.key` when set), Detail. A 403 on rejections shows the forbidden state in that panel only.
- States: loading, 401, 403 (tab hidden by `/me` without `objects:read`), error with retry, empty, and each cluster state.
Deviations to record in MOCKUP-CONTRACT.md: the Mode column, Bundle by digest instead of tag, "breaker: not measured" until #325.

## 7. File by file

| File | Change |
|---|---|
| `core/clients/kube.py` | `RESOURCES` += `PolicyReport`, `ClusterPolicyReport` (`/apis/wgpolicyk8s.io/v1alpha2/...`), the five `policies.kyverno.io` kinds; `KubeClient.served(group_version) -> bool` (404 False, other 4xx `KubeError`); `WatchCache(..., project=None)` applies a projection per kind on list and on each event |
| `core/clients/policyreports.py` (new) | `PolicyReportCache`: discovery probe, a `WatchCache` of the two report kinds with `compact()`, the 300 s poll of policy kinds (ready, digests, descriptions), the state of D3, `snapshot()` for the router |
| `core/ports.py` | `PolicyReportReader` Protocol |
| `core/registry.py` | `ClusterState.reports`; started and stopped with `cache` through an injected factory; none when engine is `none` |
| `core/context.py` | builds the factory from `cfg.policy` |
| `core/policygen.py`, `examples/cluster-configs/policies/env/*` | `cmapi.net/policy-digest`; re-render with `cmapi-tools policies render` |
| `core/db/models.py`, `core/db/migrations/versions/0006_policy_rejections.py` | the table of §5 |
| `core/rejections.py` (new) | `RULE_CODES`, `RejectionRepo` (`refused`, `accepted_warnings`, `ci`, `page`, `purge`), `recording(c, who, cluster_id, ns, plugin, action, dry_run)` context manager |
| `plugins/namespaces/router.py` | one `_plan()` helper used by the five write routes, wrapping the plan in `recording(...)`; `_submit` writes accepted warnings in the request's session |
| `jobs/pr_checks.py`; `jobs/rejections_purge.py`, `jobs/__init__.py` (`RECURRING`) | CI rows on a failed check; the daily purge |
| `plugins/policies/__init__.py`, `router.py`; `core/plugins.py`; `examples/instances/*/plugins.yaml` | the two routes; `BUILT_IN["policies"]` |
| `core/models.py` | `PolicyResultsPage`, `PolicyCluster`, `PolicySummary`, `PolicyResult`, `RejectionPage`, `Rejection` |
| `core/observability.py` | `cmapi_policy_results{cluster_id,policy,result}`, `cmapi_policy_reports_state{cluster_id,state}`, `cmapi_policy_bundle_drift{cluster_id}`, `cmapi_policy_rejections_total{stage,severity,source}`, `cmapi_policy_rejections_unrecorded_total` |
| `deploy/manifests/environments/{crc,kind}/reader/*`, `deploy/rendered/crc/...`, the chart's reader if present | the report and policy-kind rules from the baseline example (this slice's "own rule", as the file's header asks) |
| `contract/openapi.json`, `contract/samples.json`, `docs/04`, `docs/14`, `docs/01` (API line, drift by digest), `docs/16`, `docs/08` | contract and docs from measured output |
| `tests/service/conftest.py` | `FakeKube.served_groups`, report kinds; `fresh_db` truncates `policy_rejections` |
| Portal: `src/api/hooks.ts` (`useIntegrations`, `usePolicyResults`, `usePolicyRejections`), `src/portal/PoliciesTab.tsx`, `PortalApp.tsx` (`needs: PERMISSION["GET /api/v1/policies/results"]`), generated schema and permissions, `MOCKUP-CONTRACT.md`, `tests/api/standin.mjs`, `portal.test.mjs`, `mutants.mjs`, `docs/09` | the tab |

## 8. Tests, each failing before

Service (`tests/service/test_policies_302.py`, `test_rejections_302.py`); before the change every route test fails with 404.
1. Discovery 404 -> `kyverno-not-installed`, `counts: null`, no list call on report kinds (FakeKube counts calls).
2. Discovery 200, list 403 -> `forbidden` naming `list clusterpolicyreports`; fails if the list's error is read as not installed.
3. A ClusterPolicyReport (Namespace) and a PolicyReport (ResourceQuota) with pass, fail, warn, error and a `cpol` result: items hold
   fail, warn, error only; counts per cluster and per policy; `policyKind` from the label; `check` from `index.json`; legacy apart.
4. Paging: 120 results, three pages forward and back, no row twice or missing with equal timestamps; a cursor reused with another
   `result` -> 400 `invalid-cursor`.
5. Scoping: `cmapi-bot-rnd` sees no CRC row and no CRC cluster; no `objects:read` -> 403.
6. Unreachable (`kube.unreachable`, `registry.refresh()`): state `unreachable`, `since` = `checked_at`, `counts: null`.
7. `policy.engine: none`: state `engine-off` and zero cluster calls for report kinds.
8. Drift: a policy with another `cmapi.net/policy-digest` -> `changed: [name]`; one missing -> `missing`; equal -> `current`.
9. `compact()` keeps no pass message and cuts a 10 kB message to 500 characters (unit, fails on identity projection).
10. A refused create (bad `cmapi.net/team`) writes an error row and the Kyverno warning row with one `eventId`; a dry run writes none.
11. An accepted plan with a warning finding writes `outcome: accepted` rows with `requestId`, in the request's transaction.
12. `pr_checks` with a moved head writes a `ci` row `cmapi-check`.
13. The repo raising on insert leaves the 422 body byte-identical and logs `rejection_record_failed`.
14. `since=8h` and `since=91d` (422); environment scoping on rejections; no `requests:read` -> 403.
15. `rejections_purge` deletes rows older than 90 days only. `test_models_match_migrations` covers 0006.
Core: the digest is stable across renders, changes when a CEL literal changes, and excludes its own annotation;
`cmapi-tools policies check` passes on the re-rendered examples.
Portal (standin, Chromium and Chrome, 390/820/1440, both themes): each D3 state renders its text and `—`, never `0`; Mode from
integrations; chips and "Show failures" change the request's `clusterId` and `policy`; paging; engine none shows the Alert and only
rejections; rejections 403 in its panel only; 401 signs in again; a policy name present only in standin data is shown. Mutants: null
counts rendered as 0; Mode hard-coded; chip not sent; engine ignored; a constant policy list; the rejections Stage column dropped.
kind (`cmapi-test`, Kyverno v1.20.0 install.yaml as in #333): a label outside the allowed prefixes -> a `fail` row with that message;
an edited policy -> `drift`; the report rules removed from the reader -> `forbidden`; process RSS with 1,000 namespaces' reports
recorded (the memory claim of D4 is measured there, not assumed).
CRC proof (no Kyverno): the tab through the Route shows CRC `dev · audit`, "Kyverno not installed", every count `—`; a refused
create appears under "Refused by cmapi" with its Kyverno warning; screenshots at three widths, both themes; the JSON saved.

## 9. Open questions for the owner

1. Breaker: `null` ("not measured") until #325 brings the Thanos reader (D7). Acceptable, or block this slice on it?
2. Retention of 90 days as a constant, or a key in `instance.yaml` `policy`?
3. `by` (the refused caller) is in the API for `requests:read`; the mockup has no column. Show it in the tab?
4. `openreports.io` is a state, not read (D3). Read it when a cluster enables it, or keep `wgpolicyk8s.io` only?
5. The digest annotation changes every rendered policy once (one Argo CD sync per cluster). Ship it here or under #244?
