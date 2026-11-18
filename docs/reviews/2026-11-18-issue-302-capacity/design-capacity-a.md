# #302 Capacity: design A

Designer A: Opus 5.5 at high. Written apart from design B, on origin/main a8aab80 (exported with `git archive`; the local
checkout was at 9ba33b2, before #384). Design only: no code in any repository.

## 1. What the owner asked, and what exists

- #302: "**Capacity:** the capacity snapshots", API first (OpenAPI, samples, docs/04, the contract gate), then the tab, proven
  with `/test-ui` at 390/820/1440 px in both themes. No comment on #302 adds a Capacity requirement (read 2026-11-17, 4 comments).
- **No snapshot exists.** There is no `capacity_snapshots` or `capacity_reservations` table, no cmapi-capacity service and no
  Thanos client (searched `cmapi/src`). Snapshots are #21 (draft); #62 says capacity is simulated; #303 is placement.
- `core/capacity_backend.py` `SimulatedCapacity.check()` sizes a cluster from clusters.yaml `simulatedCapacity` × the
  environment's overcommit, and commits the `requests.cpu`/`requests.memory` hard of ResourceQuotas labelled
  `cmapi.net/managed=true` from the watch cache. Its one caller is `Pipeline` (`core/pipeline.py:286`); `context.py:116` builds it.
- docs/02 ("Cluster capacity", "Placement") already designs `GET /api/v1/capacity?groupBy=` and the aggregation rules, and
  docs/01:783 says "Allocatable comes from the live node list in the watch cache; snapshots supply usage and history."
- `capacity:read` is in every built-in reading role and no route uses it (docs/14, permission table: "Routes today 0").

**Decision: build the live half of the designed fleet view now, in the designed shape.** Every figure that only a snapshot can
give (pod requests, usage average and peak, utilisation) is in the schema and `null` with a named reason, so #21 fills it
without a contract change. The tab says plainly that no snapshot exists. Nothing is called a snapshot that is not one.

## 2. What Capacity measures, and where each number comes from

| Figure (per cluster, per resource cpu and memory) | Source | Primary source for the meaning |
|---|---|---|
| `committed`: sum of managed ResourceQuotas' `spec.hard` `requests.cpu` / `requests.memory` | Watch cache (`ResourceQuota`, already watched) | K8s ResourceQuota: `cpu` is "Same as `requests.cpu`"; quota is not capacity: "In the case where the total capacity of the cluster is less than the sum of the quotas of the namespaces, there may be contention for resources. This is handled on a first-come-first-served basis." (kubernetes.io/docs/concepts/policy/resource-quotas) |
| `quotaUsed`: sum of `status.used` of the same keys | Same objects | Same page: "the quota system tracks usage to ensure it does not exceed hard resource limits" |
| `allocatable`: sum over **schedulable** nodes: not `spec.unschedulable`, no `NoSchedule`/`NoExecute` taint (docs/02: "schedulable workers without NoSchedule taints") | **New** NodeCache (list-then-watch, projected) | "'Allocatable' on a Kubernetes node is defined as the amount of compute resources that are available for pods. The scheduler does not over-subscribe 'Allocatable'." (kubernetes.io/docs/tasks/administer-cluster/reserve-compute-resources) |
| `size`: what the commitment is measured against: `simulatedCapacity` when clusters.yaml sets it (source `simulated`), else `allocatable` (source `nodes`) | clusters.yaml, NodeCache | `capacity_backend.py` docstring: simulated is "named so that no reader mistakes it for measured capacity" |
| `overcommit`, `limit = size × overcommit`, `headroom = limit − committed` (negative allowed), `commitment = committed ÷ limit` (may exceed 1) | capacity.yaml `overcommit` | docs/01 "Headroom and overcommit"; `reserved` is absent: no reservation exists until #303 |
| `status` ok/warn/critical per resource against capacity.yaml `targets.<env>.commitment`; the cluster takes the worse, `boundBy` names it (`both` on a tie) | capacity.yaml | docs/02 "Targets" |
| `zones`: distinct `topology.kubernetes.io/zone` of schedulable nodes; `nodes`: total, schedulable, notReady, memoryPressure, diskPressure | NodeCache | kubernetes.io/docs/reference/labels-annotations-taints |
| `requested`, `usedAvg`, `usedPeak`, `utilisation` | **null**, `"snapshotState": "not-built"` | docs/02: requests and usage come from the snapshot job's Thanos queries |

Not used, and why:
- **LimitRange** sets per-container defaults and bounds, not a namespace's or cluster's total
  (kubernetes.io/docs/concepts/policy/limit-range); it is not a capacity figure.
- **metrics.k8s.io** (metrics-server): "only offers the minimum CPU and memory metrics to enable automatic scaling using HPA
  and / or VPA" (kubernetes.io/docs/tasks/debug/debug-cluster/resource-metrics-pipeline). Point-in-time, no history: usage is
  the snapshot job's (Thanos), as docs/02 designs.
- **Pod watch for live requests**: every pod of every namespace in memory per cluster, against docs/02 which takes requests from
  Thanos. Left to #21.
- **Unmanaged namespaces' load** (`openshift-*`, unquota'd pods) is not in `committed`, exactly as `check()` today. The tab
  footnote says "managed quota only; system and unmanaged workloads arrive with snapshots". docs/02 counts "the live requests of
  namespaces that have no quota", which needs pod requests: #21.
- **Tiers**: no section of the mockup shows a tier breakdown, and "how many more `large` fit" is placement (#303). Not in this
  slice (owner question 3).

**One definition for the plan and the tab.** A pure `core/capacity.py` `figures(cluster) -> ClusterFigures` is the only code
that sums quotas and divides; `SimulatedCapacity.check()` and the route both call it, so the tab's commitment is the plan's.
A service test asserts the plan's `capacity.detail` ratios equal the route's `commitment` for the same cache.

**Behaviour preserved.** `check()` keeps `simulatedCapacity` as its size and keeps answering `unknown` without it. Switching the
plan to node allocatable changes which requests get 422 (on CRC it would refuse every create, §6), so it is not in this slice
(owner question 1, issue #62). Two deliberate changes to `check()`, each with its test: an unknown commitment answers
`unknown` instead of `fits` (D1, §9), and a quota that uses the `cpu`/`memory` keys (the same as `requests.*` in Kubernetes)
is counted; cmapi renders only `requests.*`, so no CRC plan changes (6 of 6 managed quotas use `requests.*`, §7).

## 3. The NodeCache (no fan-out, bounded memory)

`core/clients/nodes.py`, modelled on `ReportCache`: its own `WatchCache(client, ("Node",), project=reduce_node, chunk=500)`,
started by a `nodes_factory` in the registry beside `reports_factory`, stopped with the cluster's other caches.
- **Separate from the main cache** because `WatchCache`'s `project` applies to every kind of one cache, and the main cache
  keeps raw Namespace and ResourceQuota objects that other readers need; and `wait_ready()` waits on every kind, so a reader
  without the nodes grant would hold startup to its timeout. A 403 on the Node list is the cluster's `forbidden` node state.
- **Projected** (`reduce_node`, pure): name-free tuple of allocatable cpu (cores, Decimal) and memory (bytes),
  schedulable flag, zone, Ready / MemoryPressure / DiskPressure. A Node's `status.images` alone can be hundreds of KB; the raw
  object never stays. Chunked pages are projected page by page (the F2 fix of #384 applies as is).
- **Event volume**: "The default interval for `.status` updates to Nodes is 5 minutes" and heartbeats go to Leases "every 10
  seconds" (kubernetes.io/docs/reference/node/node-status), so watching Nodes, not Leases, costs a few events per node per 5 min.
- The route reads caches under their locks; no request calls a cluster. `figures()` is memoised per cluster on the pair of
  `resource_version`s (ResourceQuota, Node), so a poll with no change costs a dictionary lookup.
- RBAC: add `nodes: [get, list, watch]` to `deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml` and the plain/helm
  reader. `examples/baseline/cmapi-reader-rbac.yaml:33` already grants it; the CRC role does not (`oc auth can-i list nodes
  --as=system:serviceaccount:cmapi-system:cmapi-reader` answered `no`, 2026-11-17). It is cmapi's own ClusterRole: no shared object changes.

## 4. Unknown is never 0

Each cluster has a `state` and `stateDetail`; a figure that is not known is `null`, and the tab shows "—".

| State | When | Figures |
|---|---|---|
| `ok` | Quotas listed, size known | all live figures |
| `loading` | ResourceQuota (or, with source `nodes`, Node) list not ended | null |
| `unreachable` | registry status ≠ connected (detail: status and findings, `asOf` = `checked_at`) | null |
| `no-size` | no `simulatedCapacity`, and nodes not known or zero schedulable | `committed` known, the ratios null |
| `stale` | no good read for 30 min (`WatchCache.RELIST_SECONDS`) | last figures, marked; **excluded from groups** |
| `forbidden` (node part only) | Node list answered 403 | `nodes`, `zones`, `allocatable` null; with a simulated size the commitment is still known, so the cluster `state` stays `ok` and `nodesState: "forbidden"` says why `zones` is "—" |

- `quotaUsed` is null when **any** managed quota lacks `status.used` for the key, with `quotaUsedMissing: n`: a partial sum is
  never shown as a total (OB3 F3 of #384).
- A group with no included cluster has null figures and `status: null`; `coverage = included ÷ matching`, `excluded` lists each
  left-out cluster with its reason (the state) and `asOf`. Group ratios are recomputed from summed numerators and denominators,
  headroom is summed with each cluster floored at 0, `largestPlacement` is per resource: `{value, clusterId}` (docs/02,
  "Aggregation rules"). The total counts are totals, not lengths of a capped list.

## 5. The route

`GET /api/v1/capacity`, plugin `capacity` (`plugins/capacity/router.py`), permission `capacity:read`, in the existing
group "Capacity and placement" (`core/docs.py:115` `TAG_GROUPS`, so the six groups stay six). Problems: `validation-failed`, `environment-forbidden`.

| Parameter | Values |
|---|---|
| `groupBy` | comma-separated, 1 to 3 of `environment`, `region`, `label:<key>` (clusters.yaml `labels`); default `region,environment`; another value 422 |
| `env` | one environment; not served: 422; served but the caller lacks `capacity:read` there: 403 `environment-forbidden` (docs/14) |
| `clusterId` | one cluster; unknown or outside the caller's environments: 404 `cluster-not-found` (no difference shown, so no existence leak) |

No paging, no cursor: the rows are the registry's clusters (clusters.yaml plus import Secrets), as unpaged as `GET /clusters`
(`ClusterList`). Namespaces never appear, so no list grows with them.

```
CapacityPage    {source: "live", snapshotState: "not-built", groupBy: [str], hiddenClusters: int,
                 targets: [{env, overcommit: {cpu, memory}, commitment: {warn, critical}}],
                 groups: [CapacityGroup], clusters: [CapacityCluster]}
CapacityCluster {clusterId, env, region: str|null, state, stateDetail: str|null, asOf: datetime|null,
                 nodesState: "ok"|"loading"|"forbidden"|"unreachable", zones: [str]|null,
                 nodes: {total, schedulable, notReady, memoryPressure, diskPressure}|null,
                 size: {source: "simulated"|"nodes", cpu: number, memory: int}|null,
                 allocatable: {cpu: number, memory: int}|null,
                 managedNamespaces: int|null, status: "ok"|"warn"|"critical"|null, boundBy: "cpu"|"memory"|"both"|null,
                 cpu: Resource|null, memory: Resource|null}
Resource        {committed, quotaUsed|null, quotaUsedMissing: int, overcommit, limit|null, headroom|null, commitment|null,
                 requested: null, usedAvg: null, usedPeak: null}      # cpu in cores (number), memory in bytes (integer)
CapacityGroup   {key: {<groupBy>: str|null}, name, matching: int, included: int, coverage: number|null,
                 excluded: [{clusterId, reason, asOf}], status|null, statusCounts: {ok, warn, critical},
                 boundBy|null, cpu: GroupResource|null, memory: GroupResource|null}
GroupResource   {committed, limit, commitment, headroom, largestPlacement: {value, clusterId}}
```

- **Scope** (docs/02 "Scope"; docs/14): only clusters whose environment the caller holds `capacity:read` in; the rest is
  `hiddenClusters`, a count. An imported cluster with no clusters.yaml entry has no environment and is omitted, as in Policies.
  Only managed quotas are summed; no namespace name, team or quota of one namespace is in the answer.
- **Caching** (RFC 9110 8.8.3, 13.1.2; RFC 9111 3.5, 5.2.2.4, 5.2.2.7): a strong ETag from `core/etag.py etag_of` over the
  exact bytes; `Cache-Control: private, no-cache`; `If-None-Match` match answers 304 with the same headers. The body is
  deterministic (clusters and groups sorted, keys stable) and `asOf` is truncated to the minute, because a watch event moves
  `last_good` (`kube.py`, `_loop`) and the tab shows minutes; without it the tag would change with every event. The body
  carries no per-request time. The answer depends on the caller's scope, so the same URL gives different bytes per caller:
  `private` keeps it out of shared caches and the tag differs per scope, so a 304 cannot cross callers.
- OpenAPI with examples, `contract/samples.json`, docs/04 example, docs/14 count (`capacity:read`: 1 route), docs/16 note
  (no table), MOCKUP-CONTRACT row, the contract gate.

## 6. The tab, mapped to the mockup (`Main.dc.html` 916–954, data 1763–1806, view 2599–2611)

| Mockup | Portal (`src/portal/CapacityTab.tsx`, hook `useCapacity`) |
|---|---|
| Head, lede, pill "snapshot 17:00 · every 30 min" | Same title and lede, minus "from the latest complete snapshots" (recorded in MOCKUP-CONTRACT); pill "live from the watch · no snapshots yet" |
| Group cards (`capgrid`): name, status pill "warn · 2 of 3", meta "2 of 4 clusters · OCP_GF7 left out: stale-data", CPU / memory commitment + "quota headroom", Largest placement, Bound by, note | From `groups`: `name`, worst status + `statusCounts`, `included of matching` + each `excluded`; `largestPlacement` per resource ("56 cores · 176 Gi on CRC", or two clusters named when they differ); note: the size source ("simulated size from clusters.yaml" when any member is simulated) |
| Clusters table: Cluster, Env, Zones, CPU meter, Memory meter, Quota headroom, Bound by, Snapshot, Status | Same columns; "Snapshot" becomes **"As of"** (the minute); Status pill from `status` or the state; `stateDetail` lines under the table, as Policies does |
| `capFoot` from the constants OVERCOMMIT and TARGETS | From the API's `targets`, nothing hard-coded |
| Unknown: `cpuPct "0%"`, bar `none`, text "—" | No bar fill, "—", and the meter has `aria-valuetext="not known"` and **no** `aria-valuenow` (a 0 there would be the unknown-as-0 error in the accessibility tree) |

Over 100%: the bar fills to 100% with the critical tone and the label shows the real figure ("461%"); a negative headroom reads
"over by 56 cores". Tab visibility: `PortalApp.tsx:49` `needs: null` becomes `capacity:read` through `grantsIn`.

States (MOCKUP-CONTRACT state table): loading "Loading capacity…" + skeletons; empty "No cluster of your environments is known to
this instance."; 403 EmptyState "You do not have permission to see capacity."; 5xx/network Alert "Capacity did not load." with
Try again; 401 the frame's sign-in, as every tab; a cluster unreachable, loading, stale, without size or with nodes forbidden
shows its pill and detail, never a zero; a 304 keeps the cached data (TanStack `refetchInterval` 30 s, the client sends
`If-None-Match`).

## 7. What CRC will show (inputs measured 2026-11-17 with `oc` as kubeadmin, read-only; the outputs are computed, not run)

- Node `crc`: capacity 8 cpu, **allocatable 7800m and 20013044Ki (19.09 GiB)**, roles control-plane, master, worker, no taints,
  not cordoned, **no `topology.kubernetes.io/zone` label**. OpenShift 4.22.14, Kubernetes v1.35.6.
- Managed quotas (`-l cmapi.net/managed=true`): `cmapi-live-a..d,f` 8 cpu / 16Gi each, `cmapi-live-e` 32 / 64Gi:
  **committed 72 cores, 144 GiB**; every `status.used` 0. One more ResourceQuota on the cluster is unmanaged (7 in all).
- 20-config.yaml: CRC in `dev`, `region: us-central`, `simulatedCapacity {cpu: 64, memory: 256Gi}`; dev overcommit cpu 2, memory 1.25; targets warn 0.85, critical 0.95.

So, with the simulated size the plan uses: one group "us-central · dev", 1 of 1, CPU **56%** (72 of 128), memory **45%** (144
of 320 Gi), headroom 56 cores · 176 Gi, status ok, bound by cpu, zones "—" (nodes `forbidden` until the reader gains the grant,
then `[]`: "no zone label"). Against the node's real allocatable the same quotas are **461% cpu, 604% memory** (limit 15.6 cores,
23.86 GiB). The cluster row says "simulated 64 cores · 256 Gi; the nodes have 7.8 cores · 19.1 Gi allocatable", so no reader
takes 56% for a measured figure. This gap is #62's, and is why §2 keeps `check()` on the simulated size.

## 8. Tests

**Service** (`tests/service/test_capacity_302.py`, `test_node_cache_302.py`), each written to fail first:
1. `figures()`: managed quotas only; an unmanaged quota changes nothing; `cpu` alias read when `requests.cpu` is absent.
2. Unknown is null: ResourceQuota list not ended, cluster not connected, Node 403, no size: every figure null, never 0.
3. `quotaUsed` null with one quota lacking `status.used`; `quotaUsedMissing` counts it.
4. Nodes: cordoned and `NoSchedule`/`NoExecute`-tainted nodes are out of `allocatable`; zones distinct and sorted; a Node with
   2,000 images projects to under 1 KB; a chunked list holds one page of raw objects (peak measured with tracemalloc, as #384 F2).
5. Groups: ratios recomputed (a 10-node and a 200-node cluster: the sum ratio, not the mean), headroom floored per cluster,
   largest per resource, stale excluded with reason, coverage, totals not capped lengths.
6. Scope: dev-only caller sees no rnd cluster and `hiddenClusters` = 1; no namespace name anywhere in the body; no
   `capacity:read` → 403; `env` not granted → 403 `environment-forbidden`; foreign `clusterId` → 404.
7. ETag: 304 on match, `W/` matches, the tag changes when a quota changes and not when only a bookmark moves within the minute;
   two callers with different scope get different tags.
8. Plan and tab agree: `Pipeline` plan's `capacity.detail` cpu/memory equal the route's `commitment`.
9. Memo: no recompute while both `resource_version`s hold (call count).

**Portal** (`tests/behaviour.test.mjs`, parity, contract): every state above; meter for null has no `aria-valuenow`; 461% label
and full bar; footnote from `targets`; "As of" from the API; tab hidden without `capacity:read`; 390/820/1440 px both themes,
Chromium and installed Chrome. **Mutants** to kill: null rendered as 0; mean of ratios instead of recomputed; headroom not floored;
`largestPlacement` from the sum; status best instead of worst; simulated badge dropped; `aria-valuenow` 0 for null; ETag over a body
with a request time.

**kind** (`cmapi-test`, `KIND_EXPERIMENTAL_PROVIDER=podman`): 3 nodes, one cordoned, one tainted `NoSchedule`, zones labelled on
two; first without the nodes grant (`nodesState: forbidden`, commitment from a simulated size), then with it and no
`simulatedCapacity` (source `nodes`): the route's `allocatable` equals the sum from `kubectl get nodes -o json` of the one
schedulable node, and `committed` equals the summed managed quotas. Output saved with the commands.

**CRC**: deploy, apply the reader grant, walk the tab through the Route in Chrome as `cmapi.viewer` and `cmapi.noaccess`;
compare every figure with the `oc` commands of §7 re-run that day; screenshots in the PR.

## 9. Defects found while designing (each to file through `fix-defect`, parent #62, found under #302)

- **D1, unknown committed read as 0** (`core/capacity_backend.py:24-36`, measured by reading): `_committed` returns `(0, 0)` when
  the cluster has no cache and when the ResourceQuota list has not ended (`cache.all` is `[]`), and `check()` then answers
  `fits` with `fresh=True` (`:47-56`). The test: a cache whose `ResourceQuota` `last_good` is None; `check()` must answer
  `unknown`, `fresh` False. Fixed by `figures()` in this slice, so the issue closes from this PR or a PR before it.
- **D2**: `fresh` is `True` on every answer, also when the watch is stale (`:56`). Same test file.
- **D3**: the CRC reader ClusterRole lacks `nodes`, unlike `examples/baseline/cmapi-reader-rbac.yaml:33` (measured with `oc auth can-i`).

## 10. Measured, inferred, not tested

- **Measured**: CRC node, quotas and reader grant (§7); the code read on a8aab80; the K8s and RFC quotations (fetched 2026-11-17).
- **Inferred**: the CRC percentages (arithmetic on measured inputs); ETag churn per watch event (from `kube.py _loop`, bookmark
  frequency not measured); node projection size and request cost at 5,000 quotas (tests 4 and 9 measure them).
- **Not tested**: anything in §8; Thanos; a multi-node or zoned OpenShift cluster.

## 11. Questions only the owner can answer

1. Should the plan's capacity check move from `simulatedCapacity` to node allocatable where a cluster has no simulated size
   (and should CRC drop its 64-core size)? On CRC's real node every create would be refused (461% cpu). (#62)
2. Is "live from the watch, no snapshots yet" acceptable as the Capacity part of #302, with snapshots (#21) its own story,
   or must #302 wait for cmapi-capacity?
3. Do you want a tier breakdown (committed per tier, or how many more of each tier fit)? The mockup has no place for it.
4. Should `committed` count unmanaged namespaces' quotas too (system namespaces), or stay "managed quota only" as the plan does?
