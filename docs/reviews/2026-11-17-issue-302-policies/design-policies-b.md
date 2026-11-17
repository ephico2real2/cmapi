# #302 Policies: design B (OB3, Opus 5.5)

Design only, from origin/main `abad314` (exported read-only to a scratch dir). Designer A's file was not read. "M" rows are
measured here; everything else is a decision with its source. Kyverno source: tag v1.20.0 clone at
`workbench/cmapi/ob-333/src/kyverno-v1.20.0` (the one #333 used).

## 1. What origin/main has today (measured)

| # | Fact | Artefact |
|---|---|---|
| M1 | No list endpoint: only `/api/v1/admin/integrations` matches `polic`/`integr` in the contract; no schema named `Policy` | `openapi.json` paths and `components.schemas` (python scan: `[]`, `null`) |
| M2 | `Integrations.policy` is `dict[str, Any]` with engine, kyvernoVersion, environments; route needs `clusters:read` | `routers/admin.py:50-55,177-187` |
| M3 | Plan-time refusals are not stored: no table (9 tables in `core/db/models.py`), the mockup itself says "metric only, no row" | `models.py` `__tablename__` list; `Main.dc.html:1410` |
| M4 | cmapi's own refusals (metadata, tiers, expiry) are raised before the metric: `cmapi_validation_failures_total` counts validator errors only | `core/pipeline.py:285,288` raise; `:292` the only `.inc()` |
| M5 | A Kyverno `Finding.rule` holds the policy name; Kyverno's own `rule` is dropped | `core/validate/__init__.py:210` |
| M6 | The watch cache lists without `limit` (one response per kind) and watches 3 kinds | `core/clients/kube.py:89-104,162` |
| M7 | Example bundle: 156 policies, 31-32 per env, 14 names hashed by #356; rules `max 75, order 20, pattern 20, required 10, prefix 10, …` | `examples/cluster-configs/policies/env/*/index.json` |
| M8 | Rendered policies carry no version, tag or digest: only `policies.kyverno.io/description` and `cmapi.net/generated` | `core/policygen.py:120-122` |
| M9 | CRC's reader ClusterRole grants no `wgpolicyk8s.io` or `policies.kyverno.io`; the baseline example does | `deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml:34-38`; `examples/baseline/cmapi-reader-rbac.yaml:60-68` |
| M10 | Kyverno v1.20 writes `wgpolicyk8s.io/v1alpha2` by default; openreports.io only with `--openreportsEnabled` | `charts/kyverno/values.yaml:188-190`; `cmd/internal/flag.go:191` |
| M11 | Result fields: policy, rule, result∈{pass,fail,warn,error,skip}, message, scored, severity, category, source, timestamp, resources, properties; report: scope, summary | `config/crds/policyreport/wgpolicyk8s.io_policyreports.yaml:66-352` |
| M12 | `fail` becomes `warn` when the policy is not scored: `warn` is not "audit" | `pkg/utils/report/results.go` (`if result.Result == "fail" && !result.Scored`) |
| M13 | The permanent report drops results of deleted policies only when it is reconciled; it carries no per-policy labels (only ephemeral reports do) | `aggregate/utils.go:56-99`; `background/controller.go:665-672` |
| M14 | The breaker drops *ephemeral reports* silently when their count exceeds `--maxBackgroundReports`/`--maxAdmissionReports` (10000); only `kyverno_breaker_drops` counts them | `pkg/breaker/breaker.go`; `cmd/reports-controller/main.go:309,429`; `pkg/metrics/breaker.go:35` |
| M15 | Policy readiness is `status.conditionStatus.ready` with `conditions[].observedGeneration` | CRD `policies.kyverno.io_validatingpolicies.yaml:4676-4742` |
| M16 | `remainingItemCount` is set on a chunked list without selectors and is "*estimating*" only | apimachinery v0.34.2 `meta/v1/types.go:84-92` |
| M17 | 20,000 stored result rows (slots dataclass, 160-char messages) take 9.4 MiB in CPython 3.14 | tracemalloc run in the scratch dir |

## 2. Where the tab can mislead or leak, and the decision for each

| Risk | Decision |
|---|---|
| Rows from clusters the caller may not read | Each cluster is kept only when the caller holds `objects:read` in its environment (as `expiration_rows`); other clusters are absent from `clusters`, `policies` counts and `items`, not zeroed |
| A report for a namespace cmapi does not manage | A row shows only when its namespace (or, for a ClusterPolicyReport, the Namespace itself) is `cmapi.net/managed=true` in the watch cache; the rest is a count, `hidden.unmanaged`, with no names |
| Policies that are not cmapi's | Only names in the bundle of the cluster's environment (`CliValidator.policies_for(env)`, rendered + `policies_dir`) are listed: no hard-coded list (#333 widens it, the tab follows). Others: `hidden.otherPolicies` count |
| Stale results after a bundle change (#356 renames) | A result counts only when its policy is both in the bundle and live on the cluster. A name live in the report but in neither: `hidden.stale` (M13: Kyverno drops them only at its next reconcile) |
| A result older than the policy's current version | `predatesPolicy`: the result's `timestamp` is before the latest non-status `managedFields[].time` of the live policy. Shown as a note, still counted (#333: background-off policies keep their admission verdict by design) |
| Audit vs enforce shown wrongly | Per cluster: `mode` from instance.yaml and `liveActions` read from the live cmapi policies' `spec.validationActions`. Mismatch is state `drift`. The tab never infers the mode from `fail`/`warn` (M12) |
| Huge reports | Chunked list (`limit=500`, `continue`; 410 restarts the list); reports are reduced on ingest; non-pass rows are capped per cluster (`policies.maxResultsPerCluster`, default 20,000 ≈ 9.4 MiB, M17); pass/skip are counters. Over the cap: state `truncated`, `dropped` count, counts stay exact |
| Kyverno's own breaker (M14) | Ephemeral-report count from one `limit=1` list's `remainingItemCount` (M16) against `policies.kyvernoMaxReports` (default 10000): state `breaker-open`, "results are being dropped". The dropped number needs Kyverno's metric (open question 2) |
| Kyverno uninstalled shown as "0 failures" | Discovery `GET /apis/wgpolicyk8s.io/v1alpha2` and `/apis/policies.kyverno.io/v1`: 404 → `not-installed`; list 403 → `no-access`; no list yet → `loading`. In each, counts are `null`, never 0 |
| Rejections holding a justification or identity | Stored: username, `automated`, the findings (each message ≤300 chars, ≤20 findings). Never: justification, body, email, employee ID, token claims. Readable with `requests:read` in the row's environment, the same audience as `GET /requests`' `requester` |
| A refusal stored for a request that never existed | `request_id` is NULL for a plan refusal and required otherwise (CHECK), with a foreign key to `change_requests`. The id shown is `rej-<n>`, never a request id |
| Paging while reports change | Keyset on identity only (namespace/kind/name/policy, cluster), never on verdict or time: a row whose verdict changes keeps its place; a new row may appear on a later page; none repeats (Lister's `kk > k`) |
| Rejection flood (a retried refused POST) | One row per fingerprint per UTC day, `count` and `lastAt` updated; sorted by the immutable `firstAt`, so an increment never moves a row across a cursor |
| Kyverno off (`engine: none`) | No report watch is started (zero calls to report kinds), results answer `engine: "none"` with no clusters or items; the tab says Kyverno is off and shows cmapi's refusals only. An environment in `off` mode: state `mode-off`, counts null |

## 3. Decisions and the options rejected

| D | Chosen | Rejected, and why |
|---|---|---|
| D1 Source | `wgpolicyk8s.io/v1alpha2` PolicyReport + ClusterPolicyReport, read live through cmapi-reader (docs/01 "Policy reports"; M10) | openreports.io now: not Kyverno's default, field `description` not `message`; a cluster with only openreports CRDs gets state `unsupported-reports` (open q. 1) |
| D2 Where read | The API's watch cache, a reduced projection per cluster (docs/01 "Reads are live", as quotas and expirations) | A worker snapshot table: a second source of truth, write churn on every report event; kept as the scale-out path (open q. 6). An on-request list: one huge cluster call per page view |
| D3 Summary | `clusters` and `policies` come back with the page, from the same snapshot | A separate `GET /policies` (docs/01): two reads can disagree mid-change. docs/01 is updated to fold it in |
| D4 Bundle running | A `cmapi.net/bundle-digest` annotation (SHA-256 of the canonical rendered document without that annotation) on each rendered policy; per cluster `bundle: {expected, live, current, missing, differing, ready}` and an env digest of 8 hex | Comparing live `spec` to the render: API-server and Kyverno defaulting make it differ always. A tag: cmapi renders from config and has none (M8). Hand-written policies: name match only (`present`, not `current`) |
| D5 Rule shown | Rendered policy: `rule` = index.json's rule (`max`, `pattern`, …) with `check: {kind, key}`; hand-written: Kyverno's `rule`. `Finding` gains `kyvernoRule` so plan findings carry it (M5) | Kyverno's `rule` for every row: for a ValidatingPolicy it says `validation` (#212 record M3), which tells an operator nothing |
| D6 Store refusals | New table `policy_rejections` (§5), written at one hook around each plan call, in its own transaction; a failed write logs `rejection_not_recorded` and never changes the 422 | Reading `request_events`: refused plans have no request. Storing dry runs: the portal's Dry run is exploration (mockup policy scenario: "no row"); dry runs are counted in `cmapi_plan_refusals_total{code,dry_run}` only |
| D7 Kyverno plan-time warnings (owner, #302 comment 2) | The same table, `outcome: "warned"`, written in `_submit` in the request's transaction, with its `requestId`, when the plan has Kyverno warnings; CI failures as `stage: "ci"` from `pr_checks` | Reading `change_requests.plan.findings` at query time: a second paging source joined in memory; CI findings there are messages only |
| D8 Which refusals | 422 `policy-violation`, `expiration-not-allowed`, `expiration-limit`, `expiration-in-past`, `reserved-namespace`, `invalid-namespace-name` | 409/412/428 (concurrency), 403 (authorization, already audited), 503 (not a verdict), `capacity-exceeded` (the Capacity tab's) |
| D9 Permissions | results: `objects:read` per environment; rejections: `requests:read` per environment; the tab shows when the caller has `objects:read` | One new permission `policies:read`: every built-in role that reads objects would get it; nothing to separate today |
| D10 `since` | `1d`…`30d`, default `7d`; retention 30 days by a recurring worker job `rejections_prune` (daily) | Unbounded history: identities kept for no reader |
| D11 Status codes | House contract: 422 `validation-failed` for a bad query value, 400 `invalid-cursor`/`invalid-limit` (RFC 9110 §15.5.1, §15.5.21 both allow it; the contract already chose) | |

## 4. The report cache

`core/clients/policyreports.py` (the file docs/02 names). `ReportCache` per connected cluster, started by the registry only when
`policy.engine == "kyverno"` and the cluster's environment mode is not `off`. It reuses `WatchCache._loop` with two hooks
added there: `list_chunked` (`limit=500`, `continue`, a 410 restarts the list) and a per-kind `reduce(obj) -> value`. Kinds:
PolicyReport, ClusterPolicyReport, ValidatingPolicy (and each other CEL kind the bundle holds), EphemeralReport count every 60 s.
`KubeClient.RESOURCES` gains their `/apis/...` paths. Discovery runs first; 404/403 set `missing`/`forbidden` on the kind state.

`reduce(report)` keeps: `scope` (apiVersion, kind, namespace, name), and per result whose policy is in the bundle of the
cluster's environment: pass/skip as counters, others as a `Row(policy, rule, result, message[:300], ts, source, process,
severity, category)` up to the cap. Results of other policies add to `hidden.otherPolicies`. Managed-ness is applied at read
(a namespace can become managed later). `cmapi_policy_results{cluster_id,policy,result}` and
`cmapi_policy_bundle_drift{cluster_id}` (missing + differing; the alert CmapiPolicyBundleDrift reads it) come from the same cache.

Cluster `state` (one, by precedence) and `stateDetail`: `unreachable` (since) > `no-access` > `not-installed` > `unsupported-reports`
> `loading` > `mode-off` > `bundle-missing` > `breaker-open` > `truncated` > `drift` > `ok`. Counts are `null` for the first seven
and `bundle-missing`; `countsComplete: false` for `breaker-open` and `truncated`.

## 5. Storage: migration `0006_policy_rejections` (number to confirm against Capacity's design, open q. 4)

```sql
CREATE TABLE policy_rejections (
  id bigserial PRIMARY KEY,
  day date NOT NULL,                                   -- UTC day of first_at: the dedupe window
  first_at timestamptz NOT NULL DEFAULT now(),
  last_at timestamptz NOT NULL DEFAULT now(),
  count integer NOT NULL DEFAULT 1 CHECK (count >= 1),
  stage varchar(4) NOT NULL CHECK (stage IN ('plan', 'ci')),
  outcome varchar(8) NOT NULL CHECK (outcome IN ('refused', 'warned')),
  problem varchar(60),                                 -- the 422 code; NULL when warned
  cluster_id varchar(63) NOT NULL, env varchar(63) NOT NULL, namespace varchar(63) NOT NULL,
  plugin varchar(40) NOT NULL, action varchar(40) NOT NULL,
  request_id varchar(40) REFERENCES change_requests (request_id),
  requester_sub varchar(100) NOT NULL, requester_username varchar(100) NOT NULL, automated boolean NOT NULL,
  findings jsonb NOT NULL,                             -- [{source, policy, rule, path, severity, message<=300}], <=20
  fingerprint char(64) NOT NULL,                       -- sha256(sub, stage, outcome, cluster, ns, action, sorted findings)
  CONSTRAINT ck_rej_request CHECK ((stage = 'plan' AND outcome = 'refused') = (request_id IS NULL)),
  CONSTRAINT ck_rej_problem CHECK ((outcome = 'refused') = (problem IS NOT NULL OR stage = 'ci'))
);
CREATE UNIQUE INDEX uq_rej_fingerprint_day ON policy_rejections (fingerprint, day);
CREATE INDEX ix_rej_env_first ON policy_rejections (env, first_at DESC, id DESC);
```
Insert: `INSERT … ON CONFLICT (fingerprint, day) DO UPDATE SET count = policy_rejections.count + 1, last_at = now()`.
Downgrade drops the table (it holds no state that another table depends on).

## 6. Responses

`GET /api/v1/policies/results?clusterId=&policy=&namespace=&result=fail,warn,error&q=&limit=50&cursor=` (`objects:read`).
`result` takes fail, warn, error only (pass and skip are counted, never listed: 422). Cursor context binds every filter.

```json
{"engine": "kyverno", "kyvernoVersion": "v1.20.0",
 "clusters": [
  {"clusterId": "CRC", "env": "dev", "mode": "audit", "liveActions": ["Audit", "Warn"], "state": "ok", "stateDetail": null,
   "asOf": "2026-11-17T18:02:11Z", "countsComplete": true,
   "bundle": {"digest": "3f9c2e1a", "expectedDigest": "3f9c2e1a", "expected": 31, "live": 31, "current": 31,
              "missing": [], "differing": [], "ready": 31},
   "counts": {"pass": 412, "fail": 2, "warn": 1, "error": 0, "skip": 0},
   "hidden": {"unmanaged": 1840, "otherPolicies": 41, "stale": 0}, "dropped": 0},
  {"clusterId": "OCP_GF9", "env": "rnd", "mode": "audit", "liveActions": [], "state": "not-installed",
   "stateDetail": "wgpolicyk8s.io/v1alpha2 is not served", "asOf": null, "countsComplete": false,
   "bundle": null, "counts": null, "hidden": null, "dropped": null}],
 "policies": [
  {"name": "cmapi-metadata-dev-label-other-keys-prefix", "kind": "ValidatingPolicy",
   "description": "The labels and annotations that metadata-keys.yaml requires of a managed namespace in dev.",
   "check": {"kind": "label", "key": null, "rule": "prefix"}, "environments": ["dev"], "generated": true,
   "counts": {"pass": 37, "fail": 1, "warn": 0, "error": 0, "skip": 0}}],
 "items": [
  {"clusterId": "CRC", "env": "dev", "mode": "audit", "namespace": "orders-dev",
   "resource": {"apiVersion": "v1", "kind": "Namespace", "name": "orders-dev"},
   "policy": "cmapi-metadata-dev-label-other-keys-prefix", "rule": "prefix", "result": "fail",
   "message": "the label keys other.example/x are not declared in metadata-keys.yaml, and are outside extraLabels.allowOther.prefixes [\"\", \"*.ephico2real.com/\"]",
   "severity": null, "category": null, "source": "KyvernoValidatingPolicy", "process": "background scan",
   "observedAt": "2026-11-17T17:58:40Z", "predatesPolicy": false}],
 "page": {"limit": 50, "total": 3, "from": 1, "to": 3, "nextCursor": null, "prevCursor": null}, "letters": {"O": 3}}
```
`policies[].counts` follow `clusterId` (the mockup's cluster chips). With `engine: "none"`: `clusters: []`, `policies: []`,
`items: []`, `page.total: 0`.

`GET /api/v1/policies/rejections?since=7d&clusterId=&stage=&outcome=&policy=&limit=50&cursor=` (`requests:read`):

```json
{"since": "7d", "from": "2026-11-10T18:02:11Z",
 "items": [
  {"id": "rej-1042", "firstAt": "2026-11-17T17:02:11Z", "lastAt": "2026-11-17T17:05:40Z", "count": 2,
   "stage": "plan", "outcome": "refused", "problem": "policy-violation",
   "clusterId": "CRC", "env": "dev", "namespace": "checkout-dev", "plugin": "namespaces", "action": "create",
   "requestId": null, "requester": "cmapi.requester", "automated": false,
   "findings": [
    {"source": "cmapi", "policy": "metadata-keys", "rule": "reserved_key", "path": "labels/kubernetes.io/team",
     "severity": "error", "message": "kubernetes.io/team is reserved; use cmapi.net/team"},
    {"source": "kyverno", "policy": "cmapi-metadata-dev-label-other-keys-prefix", "rule": "prefix",
     "path": "CRC/checkout-dev/namespace.yaml", "severity": "warning", "message": "the label keys kubernetes.io/team are …"}]},
  {"id": "rej-1039", "firstAt": "2026-11-17T09:15:00Z", "lastAt": "2026-11-17T09:15:00Z", "count": 1,
   "stage": "plan", "outcome": "warned", "problem": null, "clusterId": "CRC", "env": "dev", "namespace": "ledger-dev",
   "plugin": "namespaces", "action": "update", "requestId": "req-20261117-0004", "requester": "cmapi.requester",
   "automated": false, "findings": [{"source": "kyverno", "policy": "…", "rule": "max", "path": "…", "severity": "warning", "message": "…"}]}],
 "page": {"limit": 50, "total": 2, "from": 1, "to": 2, "nextCursor": null, "prevCursor": null}}
```
Sort: `firstAt` newest first, then `id`. `since` outside `1d`…`30d`: 422 `validation-failed`. Integrations: `policy` becomes a
named schema `Policy {engine, kyvernoVersion, environments}`, same JSON (open q. 9).

## 7. The tab (mockup `Main.dc.html:863-912`, `policiesView` 2505-2536)

Calls: `GET /admin/integrations` (`policy`: engine, modes, `kyvernoVersion`; owner's comment 3), `/policies/results`,
`/policies/rejections?since=7d`. `needs: PERMISSION["GET /api/v1/policies/results"]` in `PortalApp.tsx:47`.
- **Head**: lede with "Kyverno {kyvernoVersion} · audit in dev, rnd · enforce in prod"; pill "{fail} failing · {drift}
  clusters off the bundle". With engine none: "Kyverno is off on this instance: cmapi's own checks refuse; there are no
  cluster reports." and only the Refused panel.
- **Clusters**: Cluster, Env, Mode (configured, with live actions on drift), Bundle (digest; "3 differ" warn), Policies
  ready, Pass, Fail, Warn, Error, Reports (state pill). Null shows "—" with the state, never 0 (mockup foot kept).
- **Results by policy**: chips from `clusters` with a non-null `counts` (mockup filters `live`); rows from `policies` (no
  list in the page); "Show failures" sets `policy`. Foot: hidden counts ("1840 results on namespaces cmapi does not manage
  and 41 of other policies are not shown").
- **Failing resources**: `items` paged with Previous/Next (Expiration's pattern); pill tones fail=danger, warn=warning,
  error=info (mockup's `bad/warn/info`); "before the current policy" note when `predatesPolicy`.
- **Refused by cmapi before Git · last 7 days**: When, Where, Stage ("plan (422)", "plan, warned", "CI"), Policy or check,
  Detail; each Kyverno finding of a refused row shown beside cmapi's as a warning line.
- **States**: loading, empty ("Nothing failing for this selection."), 401 (sign in again), 403 (forbidden words), error
  with retry, each per panel (results and rejections fail independently), and per-cluster states as pills.
MOCKUP-CONTRACT rows to add: digest for tag; Mode column; hidden counts replace the legacy line; warned rows; no
"Replay a policy rejection".

## 8. Files

| File | Change |
|---|---|
| `cmapi/src/cmapi/plugins/policies/{__init__,router}.py` (new) | The two routes, built like `plugins/expiration/router.py`; registered as a core plugin |
| `cmapi/src/cmapi/core/clients/policyreports.py` (new) | `ReportCache`, `reduce`, discovery, state precedence |
| `cmapi/src/cmapi/core/clients/kube.py` | `RESOURCES` for report and policy kinds; `list_chunked`; `reduce` hook and `missing`/`forbidden` in `CacheState` |
| `cmapi/src/cmapi/core/registry.py` | Start/stop a `ReportCache` beside `WatchCache` per §4 |
| `cmapi/src/cmapi/core/rejections.py` (new) | `RECORDED` codes, `refusals(...)` context manager, `record_warned`, `record_ci`, fingerprint |
| `cmapi/src/cmapi/plugins/namespaces/router.py` | Wrap the four plan calls (create, update, `_expiry_write`, delete) in `refusals(..., dry_run=)`; `record_warned` in `_submit` |
| `cmapi/src/cmapi/jobs/pr_checks.py`, `jobs/__init__.py` | `record_ci` on the failure branch (`:114`); `rejections_prune` in `RECURRING` |
| `cmapi/src/cmapi/core/ports.py`, `core/validate/__init__.py` | `Finding.kyverno_rule`; `PolicyReportReader` as implemented |
| `cmapi/src/cmapi/core/policygen.py` | `cmapi.net/bundle-digest`; re-render `examples/cluster-configs/policies` |
| `cmapi/src/cmapi/core/db/{models.py,migrations/versions/0006_policy_rejections.py}` | §5 |
| `cmapi/src/cmapi/core/models.py`, `routers/admin.py`, `core/observability.py` | `PolicyResultPage`, `RejectionPage`, `Policy`; metrics of §4 and D6 |
| `cmapi/contract/openapi.json`, `samples.json`, `docs/04` | Generated; samples from the service tests |
| `deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml`, `deploy/helm/cmapi/templates/rbac.yaml` | get/list/watch on wgpolicyk8s.io reports, `policies.kyverno.io` kinds; list on `reports.kyverno.io` ephemeralreports |
| `cmapi-portal-ui/src/portal/PoliciesTab.tsx` (new), `api/hooks.ts`, `PortalApp.tsx`, `MOCKUP-CONTRACT.md` | §7; `usePolicyResults`, `usePolicyRejections` with `keepPreviousData` |
| `docs/01`, `docs/02`, `docs/09`, `docs/14`, `docs/18` | Policy reports section, routes table, testing record, permission rows, `policies.*` settings |

## 9. Tests

Service (`tests/service/test_policies_302.py`, `FakeKube` gains report kinds, `missing`/`forbidden` kinds, `limit/continue`,
and a call log). Each named test fails on origin/main (404 route) and passes after:
1. `engine: none`: results answer `engine none`, empty; the call log holds no report kind; a refused create is still listed.
2. Not installed (404) → `not-installed`, `counts: null`; 403 → `no-access`; unreachable → `unreachable` with `asOf`.
3. Scoping: `BOT_RND` (objects:read in rnd) sees no CRC cluster, no rows, policy counts without CRC; `namespace=` of another
   environment → 200, empty.
4. Unmanaged namespace and a non-bundle policy → hidden counts, not rows; a renamed policy's old result → `hidden.stale`.
5. Mode: instance.yaml enforce with live `[Audit, Warn]` → `drift`; `warn` from an unscored policy stays `warn` with mode audit.
6. Cap: `maxResultsPerCluster=3` with 5 fails → `truncated`, `dropped: 2`, `counts.fail: 5`.
7. Paging: between page 1 and 2 add a row before the cursor and flip one row fail→warn: no row repeats, no unchanged row is
   skipped; a changed filter → 400 `invalid-cursor`; `result=pass` → 422.
8. Rejections: a reserved-label create → one row, `requestId` null, columns hold no justification, email or employee ID
   (assert on the row and the JSON); the same POST again → `count: 2`, same id, same page position; a dry run → no row,
   `cmapi_plan_refusals_total{dry_run="true"}` +1; an audit warning (FakeValidator) → `warned` with the request id; a CI
   failure → `stage ci`; `since=31d` → 422; a DB failure in `record` → the 422 is unchanged.
9. Migration 0006 up, down, up on the PostgreSQL 16 of `127.0.0.1:55432`; the CHECK refuses a `refused` plan row with a request id.

Core: `reduce` on PolicyReports captured from Kyverno v1.20.0 on kind (fixtures), state precedence table-driven, the digest
is stable and excludes itself. Portal: standin routes `/policies/results` and `/rejections` from `samples.json`, every state
of §7 at 390/820/1440 in both themes, Chromium and installed Chrome. Mutants (each must be killed): a null count shown as
0; enforce shown as audit; the `result` chip kept in the browser; Next goes nowhere; engine none still shows the results
panels; error tone mapped to danger; the hidden-count foot dropped. kind (`cmapi-test`, Kyverno v1.20.0 install.yaml):
an other-key label → `fail` in `items`; delete the CRDs → `not-installed`; `--maxBackgroundReports=1` → `breaker-open`;
rename one policy → `stale`. CRC (Kyverno not installed, M9): `clusters[0].state == "not-installed"`, the tab's pill reads
"Kyverno not installed", and a refused create appears under Refused with a screenshot through the Route.

## 10. Open questions

1. Read openreports.io `Report`/`ClusterReport` too (same shape, `description` for `message`)? Not until a cluster uses it.
2. "140 results dropped" needs `kyverno_breaker_drops` from Thanos (exported name with `_total` not measured); without a
   metrics source the tab says "breaker open", no number.
3. The digest annotation changes all 156 rendered documents once: one re-sync of each policies Application. Owner to confirm.
4. Migration number: Capacity's design may also take 0006.
5. Show `requester` to every `requests:read` holder (as Requests does) or to operators only?
6. Per-replica watch memory (9.4 MiB per 20k rows per cluster, M17) at fleet scale vs a worker snapshot table (D2).
7. Results of `policies_dir` policies on Pods etc. in managed namespaces are listed; confirm that is wanted beside the Namespace kinds.
8. Is `GET /policies` (docs/01) dropped in favour of D3?
9. Typing `Integrations.policy` as `Policy`: confirm the contract gate calls it non-breaking.
