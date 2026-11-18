# Design B: the Capacity API and the Capacity tab (#302, slice 4)

Designer B: OB3 (Opus 5.5). Design only. Read from `origin/main` a8aab80 (an export with `git archive`, because the local
`main` is at 9ba33b2 and does not have #384). I did not read design A. Probe scripts and logs are in
`/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/f7ded52b-75f6-4c7e-b4dc-532bcd598fb3/scratchpad/probe/`.

## 1. What exists today (read or measured)

| Fact | Source |
|---|---|
| No capacity route. `capacity:read` exists, and 0 routes use it | `core/authz.py:21`; `docs/14-authorization.md:43` |
| The Capacity tab has `needs: null`, so it shows "This tab is not on the API yet." | `portal/PortalApp.tsx:49,192` |
| The only capacity code is `SimulatedCapacity`. The size comes from `clusters.yaml simulatedCapacity`. Committed is the sum of `spec.hard.requests.cpu/.memory` over cached ResourceQuotas that carry `cmapi.net/managed=true` | `core/capacity_backend.py:24-36` |
| cmapi-capacity, snapshots, Thanos, placement and reservations are not built (#21, #62). `reserve()` and `release()` do nothing | `capacity_backend.py:56-63`; `docs/08` line 60 |
| The watch cache holds Namespace, ResourceQuota and LimitRange only. `Node` is in `RESOURCES` and nothing watches it | `core/clients/kube.py:28-41,194`; `registry.py:252` |
| The CRC reader may not read nodes. The CRC manifest was cut down to what the code calls. The example baseline grants `nodes` get, list and watch | `deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml`; `examples/baseline/cmapi-reader-rbac.yaml:33` |
| CRC is configured as `simulatedCapacity {cpu: 64, memory: 256Gi}`, with dev overcommit cpu 2 and memory 1.25. The real node has 19,543 Mi allocatable, of which 15,525 Mi is requested (HANDOVER, "Environment facts") | `deploy/environments/crc.yaml:67`; `crc/20-config.yaml:54-58`; `HANDOVER-AND-RESUME.md:568` |
| The mockup shows a stale cluster's meter as a 0 % bar and rates `null` as level 0 ("ok") | `mockups/portal/Main.dc.html:1805,2607` |

**Measured defect M1: an unknown commitment counts as 0 and is reported as fresh.** I called `SimulatedCapacity.check` on
a8aab80 (`probe_simcap.py`, log `probe_simcap.log`):

```
no cache        : status='warn', fresh=True, detail cpu 0.938   # cluster not connected; 120 cores asked
rq never listed : status='warn', fresh=True                     # cache present, ResourceQuota last_good=None
unreachable 16c : status='fits', fresh=True, cpu 0.125           # what approvals.py:226 accepts for auto-approval
+ cpu synonym 40: cpu 0.75 (unchanged)                           # a quota written `cpu: 40` is not counted
```

`_committed` catches every exception and returns `(0, 0)` (line 28), and `check` hard-codes `fresh=True` (line 53). #62 covers
"simulated, so the guard always passes". It does not cover "unknown counted as zero". Under `fix-defect` this becomes its own
issue, linked to #62 and #302, because the tab must not inherit it (D2). I did not measure whether a plan can reach `check`
on an unreachable cluster. The "rq never listed" case does reach it while namespaces are listed and quotas are refused or
still listing.

**Measured cost M2: a sum on every request does not scale.** `bench_sum.log`: `qty()` on requests.cpu and requests.memory
takes 28.4 ms per 1,000 quotas, 337 ms per 10,000 and 955 ms per 50,000 (best of 3, i9-9980HK). Twenty clusters of 10,000
quotas would take about 6.7 s per GET, and every plan pays the same today.

## 2. How this tab could mislead or leak, and what holds against each

| # | Attack | What holds (decision) |
|---|---|---|
| A1 | Figures from a cluster or environment the caller may not read | Only clusters with a `clusters.yaml` environment where `roles.allowed(who, "capacity:read", env)`, as Policies does. Groups are summed **after** that filter. "N of M" counts clusters in scope only |
| A2 | A cluster with no entry (imported, no environment) folded into a group | Not returned at all: it has no environment to scope it by. Listed as a difference from the mockup's "OCP_GF9 not registered yet" |
| A3 | Unknown shown as 0 (no cache, quotas not listed yet, nodes 403, stale) | Each figure is `null` with a named `state`. The cluster is left out of its group with the reason. The meter draws no bar, says "—", and its aria-label says "not known". Never `0%` |
| A4 | Stale numbers shown as current | Freshness is judged per kind (Node, ResourceQuota). `WatchCache.stale()` (`kube.py:308-313`) takes the min over kinds that listed, so a kind that never listed reads as fresh. It is not used. Each row has `asOf` (the older kind's `last_good`). The head pill says "N clusters not current" |
| A5 | Unreachable shown as empty | `st.status != "connected"` gives state `unreachable` with "since {checked_at}", never 0 namespaces and 0 cores |
| A6 | Quota, request and use confused | Three named figures. **committed** = ResourceQuota `spec.hard` (what was promised). **requested** = quota `status.used` (what pods request; K8s: `Used`). **usage** = not measured until cmapi-capacity (#21), and the API says so in `notMeasured`. The lede and footnote define each term |
| A7 | Unmanaged namespaces counted, or their load hidden | Committed counts managed namespaces only, keyed as `check()` keys them. The pods of other namespaces (openshift-*, unmanaged apps) also use allocatable, and cmapi cannot see them without a Pod watch. So the footnote says: "Headroom counts quota of the namespaces cmapi manages; pods of other namespaces are not subtracted." No unmanaged namespace is named, and no unmanaged quota is summed |
| A8 | Units mixed (`G` vs `Gi`, `m` on memory) | The API sends integers: CPU in **millicores** and memory in **bytes**, parsed by the exact `core/tiers.qty`. The portal shows cores and Gi (binary) only, and never "G" or "GB". A `cpu`/`memory` quota key is read as `requests.cpu`/`requests.memory` (K8s: "Same as `requests.cpu`") |
| A9 | Overcommit hidden | Each resource has `allocatable`, `overcommit`, `capacity = basis × overcommit` and `commitment = committed / capacity`. The cell shows "64 % · 1.28× allocatable". Commitment over 100 % is `over`, with the bar clamped at full and the text unclamped. The footnote lists each environment's overcommit and targets, and "default 1.0 (not in capacity.yaml)" when `check()` falls back |
| A10 | Simulated size passed off as measured | `basis` is `allocatable` (Node watch) or `simulated` (clusters.yaml), never unlabelled. A simulated basis carries the pill "simulated size". When both exist and differ by more than 10 %, the row says "simulated 256 Gi, nodes 19.1 Gi" |
| A11 | Group ratio averaged; one cluster's headroom spent on another | Ratios come from summed numerators and denominators. Headroom is floored at 0 per cluster before the group sum (docs/01). `largestPlacement` is per resource **with its cluster**, so "96 cores on GF6 · 410 Gi on GF8" never reads as one placement |
| A12 | A capped list used as a total | No paging. `clusters` is the whole registry in scope, and groups are computed on the server from all of it, never from a page |
| A13 | Memory and CPU at scale | Totals are kept incrementally by the cache's `admit`/`dropped` hooks (D3). A GET is O(clusters). Nodes are projected and listed in chunks (the #384 F2 pattern) |
| A14 | The tab and the plan disagree | One ledger feeds both `SimulatedCapacity.check` and the API, so the tab's commitment at delta 0 equals the plan's `capacity.cpu` |
| A15 | Not-schedulable nodes counted (CRC single node, masters, cordoned) | A node counts when it is Ready, not `unschedulable`, and has no NoSchedule or NoExecute taint outside `capacity.yaml countTaints` (default: none). `nodes {total, counted, notReady, cordoned, tainted}` is returned, so the exclusions are visible |

## 3. Sources: only watched objects, no work per request

- **D1. Node watch.** Each connected cluster gets a second `WatchCache(client, kinds=("Node",), project=node_view, chunk=100,
  admit=…, dropped=…)`, built and stopped next to `st.reports` in `registry._check` and `_stop_caches`. `node_view` keeps the
  name, `topology.kubernetes.io/zone`, `node-role.kubernetes.io/*`, `status.allocatable` cpu and memory (parsed to int),
  `spec.unschedulable`, the taint effects and Ready. `status.images` is never kept. Watch load: the kubelet "updates the
  node's `.status` … if there has been no update for a configured interval. The default interval … is 5 minutes"
  (kubernetes.io/docs/reference/node/node-status), so 5,000 nodes come to about 17 events/s (inferred, not measured).
  Grant: `nodes` get, list and watch on cmapi-reader in the CRC and kind manifests and the Helm chart. This restores the
  example baseline. Without it, the cluster is in state `forbidden` (nodes) and falls back to `simulated` when configured.
- **D2. The ledger, `core/capacity_ledger.py`.** One per cluster. The ResourceQuota `admit` hook records each quota's
  parsed hard and used per namespace and keeps the running totals. It is the identity on the stored object, so the Quotas
  plugin still reads raw quotas. Per namespace, a resource's value is the **smallest** among unscoped quotas, never their sum
  (docs/16), and scoped quotas are left out and counted. A relist goes through `dropped` and `admit`, so a property test can
  check the totals against a full recount. `known` is false until both kinds have listed. `SimulatedCapacity.check` reads
  the ledger and returns `unknown, fresh=False` when it is not known, which fixes M1. Today's behaviour changes only for a
  namespace with several unscoped quotas, or one written with `cpu`/`memory` keys. The PR says so (D9 Q3).
- **D3. Per-request cost.** The GET reads each ledger's totals under its lock and does arithmetic over clusters. It parses
  nothing on the request path.
- **D4. No Thanos, no Pod watch, no fan-out.** Usage and the requests of unmanaged namespaces stay `null`, listed in
  `notMeasured`, until cmapi-capacity (#21) serves snapshots. The response's `source: "watch"` becomes `"snapshot"` then,
  with the same schema.

## 4. Route and schema

`GET /api/v1/capacity?groupBy=region,environment`. Permission `capacity:read`. Group "Capacity and placement". Problems:
`validation-failed` (422, a `groupBy` key that is not `environment`, `region` or a clusters.yaml label key; at most 3
keys). `GET /api/v1/clusters/{id}/capacity` (zones and roles in detail, docs/01) is the next route and is not needed by
this tab.

```
CapacityPage  { source: "watch", groupBy: [str], asOf: datetime|null,
                notMeasured: ["usage", "requests of unmanaged namespaces", "reservations"],
                settings: { <env in scope>: { overcommit: {cpu, memory}, overcommitDefault: bool,
                                              targets: {warn, critical} } },
                clusters: [ClusterCapacity], groups: [CapacityGroup] }
ClusterCapacity { clusterId, environment, labels, writes: bool, zones: [str]|null,
                state: ok|loading|unreachable|forbidden|stale|no-size, stateDetail: str|null, asOf: datetime|null,
                basis: allocatable|simulated|null, nodes: {total, counted, notReady, cordoned, tainted}|null,
                managedNamespaces: int|null, cpu: Resource, memory: Resource,
                boundBy: cpu|memory|both|null, status: ok|warn|critical|over|null }
Resource      { unit: millicores|bytes, allocatable: int|null, simulated: int|null, overcommit: number,
                capacity: int|null, committed: int|null, requested: int|null, headroom: int|null (may be < 0),
                commitment: number|null, status: ok|warn|critical|over|null }
CapacityGroup { key: {<groupBy key>: str|null}, name: "us-central · dev",
                clusters: {inScope: int, included: int}, excluded: [{clusterId, reason}],
                cpu|memory: {capacity, committed, headroom (floored sum), commitment},
                largestPlacement: {cpu: {value, clusterId}|null, memory: {value, clusterId}|null},
                boundBy, status (worst included), statusCount: {warn, critical, over} }
```

Rules: a cluster is in a group's sums only when its `state` is `ok` and it has `writes: true`. Otherwise it goes in
`excluded` with its state or `not-writable`, as the mockup's "placement off" does. `status` per resource: `over` above 1.0,
else `critical` or `warn` at the environment's targets, else `ok`. A cluster takes the worse of its two resources (docs/01).
`boundBy` is the resource with the higher commitment, or `both` when they are equal to 3 decimals. Ratios are rounded to 4
places for display only; the integers are exact. A group mixing environments has no threshold of its own: its status is
its worst cluster's.

## 5. The tab, mapped to the mockup (`Main.dc.html:916-955`)

| Mockup | Portal |
|---|---|
| Lede "from the latest complete snapshots" | "from each cluster's watch of its nodes and quotas" (a difference row); the rest kept |
| Pill "snapshot 17:00 · every 30 min" | "live · as of {oldest asOf}" or "{n} clusters not current" (warn) |
| Group card: name, status pill, meta, 4 stats, note | `name`; "{status} · {count} of {included}"; "{included} of {inScope} clusters · {id} left out: {reason}"; CPU and Memory commitment with "quota headroom {n} cores/Gi"; Largest placement per resource with its cluster; Bound by with "cpu x % vs memory y % committed"; the note gives the overcommit and the A7 sentence |
| Clusters table, 9 columns | Same columns; "Snapshot" becomes "As of". A meter with null shows no bar and "—". `over` uses the danger tone with the unclamped %. Status shows the state word for non-ok rows ("unreachable since 14:02", "nodes not readable · simulated size", "loading", "stale since …") |
| `capFoot` | Built from `settings`, plus the definitions of committed, requested and usage, and the `notMeasured` list |

States, in the contract's table: Loading "Loading capacity…"; Empty (no cluster in scope) "No cluster of the {instance}
instance is in your environments."; Forbidden "You do not have permission to see capacity."; Error "Capacity did not
load." with Try again; 401 the client's renewal. Tab gate: `needs: PERMISSION["GET /api/v1/capacity"]`. Hook:
`useCapacity()`, refetched on focus, with no polling. MOCKUP-CONTRACT gets "Where the portal's Capacity tab differs".

## 6. What CRC will show (inferred; to be measured)

There is one group, "us-central · dev", with one cluster, "CRC", and zones "—" (inferred: a single node with no zone label).
- **Before the nodes grant:** state `forbidden` (nodes) with basis `simulated` (64 cores, 256 Gi): the pill "simulated size".
  The commitment comes out small against 128 cores and 320 Gi, which is fiction for a node with 19,543 Mi allocatable. The
  tab says so instead of hiding it.
- **After the grant:** basis `allocatable`. Memory capacity = 19,543 Mi × 1.25 = 24,429 Mi. The quota committed by
  `cmapi-live-a…e` (one is large) could pass that, which shows as `over`. That is a true reading of quota against the node,
  but it changes `check()` from fits to exceeded on CRC (Q1).
- Before relying on the counted-node rule, the coordinator measures:
  `oc get nodes -o json | jq '.items[]|{labels:.metadata.labels,taints:.spec.taints,alloc:.status.allocatable}'`
  and `oc get resourcequota -A -l cmapi.net/managed=true -o json`.

## 7. Tests

- **Service, `tests/service/test_capacity_302.py`.**
  1. Scope: a viewer limited to `dev` gets no rnd cluster, and the group sums equal the dev clusters only.
  2. Unknown: no cache, ResourceQuota not listed, nodes 403 with no simulated size, and stale each give `null` figures,
     named states and exclusion from groups. Never 0.
  3. Units: `64G`, `64Gi`, `500m` CPU and `cpu: 40` give exact integers.
  4. Overcommit: 10 cores allocatable × 2 against 30 committed gives 1.5, `over` and headroom −10,000 m; the group's
     headroom is floored at 0.
  5. Group ratio by sums: 1/10 and 90/100 give 0.827, not the 0.55 average.
  6. `largestPlacement` on two different clusters.
  7. The tab equals the plan: `check(c, env, 0, 0).detail.cpu` equals `commitment`.
  8. Ledger property test: random ADDED, MODIFIED, DELETED and relist sequences equal a full recount.
  9. Nodes: NotReady, cordoned and tainted are excluded and counted.
  10. M1: `check` returns `unknown` and `fresh=False` while the ledger is unknown. It fails on a8aab80.
  11. Scale: 50,000 quotas and 5,000 nodes. GET under 50 ms after the lists, and the projected-node memory measured.
  12. `groupBy` 422.
- **Portal (`tests/api`, Chromium and Chrome, 390/820/1440, both themes).** The five states. Null meters have no bar.
  Over 100 % is clamped with its text. Gi formatting. Exclusions in the meta line. The tab is hidden without
  `capacity:read`. Parity strings from the mockup.
- **Mutants.** null→0 in the meter; the average instead of the sum ratio; headroom not floored; the environment filter
  dropped; "Gi"→"G"; memory placement taken from the CPU cluster; an excluded cluster summed; overcommit ignored;
  `fresh=True` restored in `check`.
- **kind (`deploy/kind-test.sh`).** API `allocatable` equals the sum from `kubectl get nodes`. A managed namespace's
  quota moves `committed`. `kubectl cordon` lowers `counted`. A reader without `nodes` gives `forbidden` with the
  simulated basis.

## 8. Primary sources

- ResourceQuota (kubernetes.io/docs/concepts/policy/resource-quotas): "`cpu` | Same as `requests.cpu`"; "ResourceQuotas
  are independent of the cluster capacity"; "In the case where the total capacity of the cluster is less than the sum of
  the quotas of the namespaces, there may be contention for resources"; quota on cpu or memory means pods "must specify
  either `requests` or `limits`", and "You can use a LimitRange to automatically set a default request".
- Allocatable (…/tasks/administer-cluster/reserve-compute-resources): "the amount of compute resources that are available
  for pods. The scheduler does not over-subscribe 'Allocatable'." Node status (…/reference/node/node-status): "allocatable
  … available to be consumed by normal Pods"; the 5-minute `.status` interval.
- Quantities (…/configuration/manage-resources-containers): "E, P, T, G, M, k … Ei, Pi, Ti, Gi, Mi, Ki"; "If you request
  `400m` of memory, this is a request for 0.4 bytes"; the scheduler places on requests.
- Large lists: API concepts, "Retrieving large results sets in chunks" (`limit`/`continue`), already cited in `kube.py:118`.

## 9. Measured vs inferred

Measured: M1 and M2 above (scripts and logs in the scratchpad), and every `file:line` cited, from the a8aab80 export. Read
from records, not re-measured: the CRC node figures (HANDOVER). Inferred: the CRC node labels and taints, the Node watch
event rate, the raw Node size (images), the scale timing of D3, and what CRC shows after the grant. Not run: any cluster,
the portal, or the service suite.

## 10. Questions only the owner can answer

- **Q1.** Should CRC (and other clusters) be judged against **measured** node allocatable once the reader can read nodes?
  That makes `check()` stricter (fits can become exceeded) and may change CRC auto-approvals. Or should `simulatedCapacity`
  stay authoritative until cmapi-capacity, with the measured figure shown beside it?
- **Q2.** May cmapi-reader get `nodes` get, list and watch on every managed cluster? It is in the example baseline, and
  every import's RBAC changes.
- **Q3.** Accept the docs/16 rule (the smallest unscoped quota, with the `cpu` key read as `requests.cpu`) in `check()` now,
  a small behaviour change for multi-quota namespaces?
- **Q4.** Which taints and roles count as tenant capacity (`countTaints`, an optional per-cluster node selector)? Should
  infra nodes be excluded by default?
- **Q5.** Should a stale cluster keep its last figures, marked stale (as Policies does), or show "—" (as the mockup does)?
  This design follows the mockup.
- **Q6.** Should the cluster `placement.overcommit` override of docs/01 apply now? `check()` ignores it today.
