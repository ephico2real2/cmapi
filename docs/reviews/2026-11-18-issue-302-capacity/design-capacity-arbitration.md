# #302 Capacity: the arbitration

Coordinator (Opus 5.5), 2026-11-18. Inputs: `design-capacity-a.md` (Opus 5.5) and `design-capacity-b.md` (OB3, Opus 5.5),
written apart. One model family: Fable is paused, and Codex has no quota until 2026-11-18 14:09. The owner's answers are at
the end. Where this file is silent, design A holds, then design B.

## Where both agree (taken as is)

- One route, `GET /api/v1/capacity?groupBy=`, permission `capacity:read`, in the tag group "Capacity and placement". No
  paging: the rows are the registry's clusters in the caller's scope.
- A Node watch per connected cluster: a separate `WatchCache` on `("Node",)`, projected page by page (#384 F2). A Node's
  `status.images` is never kept. It is built and stopped beside `st.reports`. A 403 on Node is the node part's `forbidden` state.
- No request calls a cluster. No Thanos, no Pod watch, no metrics.k8s.io. LimitRange is not a capacity figure.
- Scope: only clusters whose `clusters.yaml` environment the caller holds `capacity:read` in. Group sums are computed after
  that filter. A cluster with no environment is not returned. No namespace name is in the answer.
- Unknown is null, never 0, and every cluster has a named state. A null meter draws no bar, says "—", and carries no
  `aria-valuenow`. Group ratios are computed from summed numerators and denominators; headroom is floored at 0 per cluster;
  `largestPlacement` is given per resource with its cluster. Totals are totals, never the length of a capped list.
- The plan and the tab share one computation, and a test asserts they agree.
- The tab follows the mockup's group cards and Clusters table. "Snapshot" becomes "As of", and the footnote comes from the
  API, never from constants.

## Rulings where they differ

| Topic | A | B | Ruling |
|---|---|---|---|
| How totals are kept | A pure `figures()`, memoised on resourceVersions | An incremental per-cluster ledger fed by the cache's `admit`/`dropped` hooks | **B.** B measured `qty()` at 28.4 ms per 1,000 quotas and 337 ms per 10,000, paid by every plan today; resourceVersions move on every event, so A's memo rarely hits. Add a property test: the ledger equals a full recount after random events and relists. A's pure `figures()` stays as the arithmetic over the ledger's totals |
| Units | CPU in cores (number), memory in bytes | Integers: millicores and bytes | **B.** Exact, with no floats in the contract. The portal shows cores and Gi (binary) |
| Names | `committed`, `quotaUsed` (status.used), `requested`/`usedAvg`/`usedPeak` null until snapshots | `committed`, `requested` = status.used, `notMeasured` list | **A's names, plus B's `notMeasured`.** `requested` is kept for all pods' requests from snapshots (#21), so it never changes meaning. `quotaUsed` is what pods use within managed quotas. `quotaUsed` is null when any quota lacks `status.used`, with `quotaUsedMissing` (A) |
| Size basis | `size {source: simulated or nodes}` | `basis`, with both `allocatable` and `simulated` kept on each resource | **B's shape, the owner's rule.** Each resource carries `allocatable` (nodes, or null) and `simulated` (clusters.yaml, or null). `basis` is `simulated` when clusters.yaml sets it, else `allocatable`. The tab shows the other beside it when both exist ("simulated 64 cores · nodes 7.8 cores") |
| Several unscoped quotas in one namespace | Sum, as today | Take the smallest (docs/16) | **B.** Kubernetes enforces every quota in a namespace, so the tightest one binds (ResourceQuota docs). The `cpu` key is read as `requests.cpu`; when both are set on one quota, the smaller binds. A behaviour change for multi-quota namespaces only; the PR says so |
| Counted nodes | Not `unschedulable`, no NoSchedule or NoExecute taint | Also Ready; `countTaints` in capacity.yaml; `{total, counted, notReady, cordoned, tainted}` | **B**, with `countTaints` defaulting to none. Infra nodes are not excluded by role by default (not asked) |
| Clusters that are not writable | Not addressed | Left out of group sums, as `not-writable` | **B**, matching the mockup's "placement off" |
| Stale | Last figures, marked, left out of groups | "—" (mockup) | **Owner: last figures, marked** "stale since HH:MM", left out of group sums with the reason |
| Group thresholds | Per environment | A mixed group takes its worst cluster's status | **B** |
| Polling | `refetchInterval` 30 s, ETag/304 | Refetch on focus, no polling | **A**: strong ETag, `private, no-cache`, 304; `asOf` cut to the minute. Refetch on focus plus 60 s |
| `status` values | ok, warn, critical | Adds `over` above 100 % | **B** |
| Per-cluster overcommit override (docs/01) | Not mentioned | Q6 | **Deferred**: `check()` ignores it today, and changing it changes plans. Filed as a follow-up |

## Defects

- **#393** (both designs, measured by B): unknown committed quota counted as 0 and reported fresh, so auto-approval can pass
  a create. It is fixed on its own branch first (`fix/393-capacity-unknown`); this slice builds on that fix.
- The CRC reader's missing `nodes` grant (A's D3) is not a separate defect: the owner granted it (below), and this slice adds
  it to the CRC, kind and chart readers.

## The owner's answers (2026-11-18)

1. **Size basis:** keep `simulatedCapacity` as what the check uses until cmapi-capacity (#21). The tab labels it "simulated"
   and shows the nodes' real allocatable beside it.
2. **Nodes grant:** yes. `nodes` get, list and watch for cmapi-reader on every managed cluster (CRC, kind, chart), matching the
   example baseline.
3. **Scope:** ship live now. Usage and history are in the schema as null and listed in `notMeasured`; #21 fills them with no
   contract change.
4. **Stale:** last figures, marked, left out of group sums.

## What CRC must show

One group, "us-central · dev", with one cluster. Basis simulated: CPU 72 of 128 cores, 56 %; memory 144 of 320 Gi, 45 %.
After the nodes grant, allocatable is 7.8 cores and 19.1 Gi beside them, and zones "—", since there is no zone label. These
are computed from inputs measured 2026-11-17; the CRC walk re-measures them with `oc`.

## Tests

Union of A §8 and B §7. Required as well: the ledger property test, the M1 regression (it lands with #393), a scale test
(50,000 quotas and 5,000 nodes: a GET under 50 ms after the lists, and projected node memory measured), and a kind proof
before and after the nodes grant.
