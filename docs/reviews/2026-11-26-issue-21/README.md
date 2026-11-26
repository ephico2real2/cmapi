# #21 capacity snapshots and safe placement, and #303 the placement API: decisions

Story #21 (OBI-32) and its sub-issue #303. Built on PR #725 (#62, the capacity holds and migration 0011), merged to main as 9ccb88f and merged into this branch. The implementer is
Opus 5.5 at `high`. The design is docs/01 ("Capacity, placement and usage", "cmapi-capacity service") and docs/02 ("Stored
capacity", "Snapshot job", "Capacity service (cmapi-capacity)", "Cluster and fleet capacity", "Placement"), built as written
except where a row below says why.

## What was built

| Criterion of #21 | Built | Proof |
|---|---|---|
| 1. Snapshots stored at configured intervals; the gateway enforces scope | The worker's `capacity_snapshot` job (`capacity/snapshots.py`, `jobs/capacity_snapshot.py`, migration 0012) every capacity.yaml `snapshotInterval` (15m to 60m, 30m by default), on the interval's boundary: one row for the cluster, one per zone, one per node role. `GET /api/v1/clusters/{clusterId}/capacity` (capacity:read in the cluster's environment, else 404) and `POST .../capacity/snapshots:run` (operations:run) | `tests/service/test_placement_21.py`, the first five tests |
| 2. Placement checks CPU and memory separately, freshness, reservations and zone-failure headroom | `POST /api/v1/capacity:place` (`core/placement.py`, `plugins/capacity/placement.py`): the hard filters of docs/02 with a named reason each, the score, and a 15-minute hold on the first cluster that still fits under its advisory lock. The create's `placementId` turns that hold into the request's own | `tests/service/test_placement_21.py` (placement and #303 tests), `tests/core/test_placement_21.py` |
| 3. Concurrent reservations cannot overbook; expired reservations are reclaimed | #62 (PR #725) for the requests' holds; here for placements too | `test_concurrent_placements_cannot_overbook`, `test_an_expired_placement_is_reclaimed_and_holds_nothing` |
| 4. Namespace creation makes no Thanos query | Placement and the create read the stored snapshots, the watch and the holds | `test_placing_and_creating_a_namespace_make_no_thanos_query` |

The portal's New namespace tab ranks with `POST /api/v1/capacity:place?dryRun=true` (the Placement preview of
`mockups/portal/Main.dc.html`), plans on the first cluster, holds it at Submit and sends `placementId`. The Cluster field is
gone (#303). The Capacity tab shows each cluster's snapshot (the mockup's Snapshot column and pill).

## Decisions

| # | Question | Decision | Why, with the source |
|---|---|---|---|
| D1 | Where does the snapshot job run? | In the worker, in the cmapi schema, as #310's sweep | docs/01: "capacity.mode: embedded runs the same package, cmapi.capacity, inside the worker for development and small installs." The separate service is not built; migration 0010's record gives the same reasons for the schema and for no monthly partitions (#705) |
| D2 | What does a snapshot hold when `usage.source` is `none` (CRC, kind, the default)? | The API's figures (nodes, zones, roles, allocatable, conditions) and the committed quota; every figure only Thanos gives is null, and the row says `source: api`. It is complete: no configured query failed | docs/02: "A failed or warned query marks the row incomplete; it is never written as zero." No query is configured, so none failed, and nothing is written as 0. Marking every such row incomplete would exclude every cluster from placement on an instance whose owner chose `usage.source: none` (#310) |
| D3 | The size placement measures headroom against | The plan's own: clusters.yaml `simulatedCapacity` when set, else the counted nodes' allocatable, × the overcommit | The owner kept `simulatedCapacity` as the size (2026-11-18, docs/reviews/2026-11-18-issue-302-capacity/). One arithmetic, so a cluster placement ranks is one the create's check finds room on |
| D4 | Zone-failure headroom with a simulated size | The size times one minus the largest zone's share of the counted allocatable, from the newest complete snapshot's zone rows. Fewer than two zones: none | docs/02: "quota headroom computed with the largest zone removed, so a placed namespace still fits after losing a zone". A cluster in one zone loses everything with it |
| D5 | Which environments check zone failure | placement.yaml `zoneFailureEnvironments`, `[prod]` by default | docs/01 and docs/02 say "in prod". The key lets a test or an instance name another without code |
| D6 | The score factors docs/02 names without a formula | Written in `core/placement.py`'s docstring: each 0 to 1, × its weight. Usage headroom gives no credit when not measured | docs/03, "Accuracy rules": "Missing is not zero"; a cluster with no usage data is not ranked as idle |
| D7 | The permission of the hold | `namespaces:create` in the environment, beside `capacity:read` | docs/02 says "namespaces:write", and also "namespaces:create asks for a new namespace; namespaces:write changes or deletes one". A placement is for a create; `cmapi-onboarding` holds namespaces:create and not namespaces:write |
| D8 | The cap of 3 active placements | Counted in the database under a per-team advisory lock; the in-memory `start_placement` of `core/ratelimit.py`, which no route used, is removed | docs/01: "at most 3 active placements per team and environment". A count in one pod's memory is per replica and never sees a placement lapse |
| D9 | A dry run of the placement | `dryRun=true` ranks and holds nothing: the portal's preview | docs/diagrams/portal-architecture/README.md: "It names no call that ranks clusters and reserves nothing." Every write of the API takes `dryRun` (docs/02, "Dry run") |
| D10 | Units | Millicores and bytes as integers, as `GET /api/v1/capacity` | The arbitration of #302 (design B: "no floats for amounts in the contract"). docs/02's example uses cores and "32Gi" |
| D11 | clusters.yaml `placement` | `enabled`, `maxNamespaces`, `weight` and `overcommit` are read and checked at the start; `overcommit` applies to the plan's check and the Capacity tab too | docs/01: "A cluster's placement block can override its environment's overcommit." Applying it to placement alone would rank a cluster the check refuses |
| D13 | A namespace's own open hold (#725's `check(..., namespace=)`, da0e36b) | Kept: the create's plan and its submit pass `namespace` beside `exclude_placement`. Placement ranks a namespace that does not exist yet, so it has no hold of its own to leave out; a placement's hold has no namespace until a create claims it, so it is always counted | The two are alternatives of one namespace, never both (da0e36b). A new namespace has no open request on it: its create is refused 409 namespace-exists or change-pending first |
| D12 | Node roles | `node-role.kubernetes.io/<role>`, with `control-plane` as `master`; a node with several roles counts in each role's row | CRC's one node is master and worker. The role rows are breakdowns, not a partition of the cluster row |

## Sources read for the queries, 2026-11-26

- kube-state-metrics, `docs/metrics/workload/pod-metrics.md`: `kube_pod_container_resource_requests` and `_limits` carry
  `resource`, `unit`, `container`, `pod`, `namespace`, `node`; `kube_pod_info` carries `node`; `kube_pod_status_phase` carries
  `phase` "Pending|Running|Succeeded|Failed|Unknown".
  <https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/pod-metrics.md>
- prometheus-operator, `pkg/prometheus/promcfg.go`, `generateServiceMonitorConfig`: "Relabel node labels with meta labels
  available with Prometheus >= v2.3", regex `Node;(.*)` over `__meta_kubernetes_endpoint_address_target_kind` and `_name`,
  target_label `node`: the source of the `node` label on the kubelet's cAdvisor metrics.
  <https://github.com/prometheus-operator/prometheus-operator/blob/main/pkg/prometheus/promcfg.go>

## Not built, by design scope

The separate cmapi-capacity service and its remote mode; snapshot history and fleet aggregates over time; node-exporter's
whole-node use and storage in the snapshot (null, `NOT_QUERIED`); the backtest; the weekly rebalance report; pinning a zone.
