# #310: live 14-day usage on a quota change, and the usage verdicts of the Quotas tab

Story #22, criterion 2: "Existing-namespace changes use live 14-day usage; insufficient data is explicit". Built from the
design as it stands (docs/01, "Capacity, placement and usage" and "Lists"; docs/02, "Capacity plugin" and "Capacity service";
docs/03, the whole tab). Nothing in the design was reopened. This record says what was built, what was left for later and
why, and the sources each choice rests on.

## What the design says, and what was built

| Design line | Built |
|---|---|
| docs/01: "The quotas planner asks cmapi-capacity for that namespace's last 14 days. The figures feed the approval facts (quotaIncreasePct, requestToPeakRatio, the namespace's current verdicts). If Thanos cannot answer within 10 seconds, the plan carries usage: unavailable and the change needs a platform approval instead of failing." | `Pipeline._plan_namespace` reads `UsageSource.namespace` for a change of an existing namespace that moves `requests.cpu` or `requests.memory`. The plan's `usage` block, the facts `usage` and `requestToPeakRatio`, and the rule `usage == "unavailable"` (approver-platform) in every approval-rules.yaml |
| docs/01, "Is this quota change on an existing namespace justified?": "That namespace's usage now, 7-day average, 14-day p95 and peak, from Thanos · Once per quota-change plan, cached 10 minutes · Stored? No" | `PromUsage.namespace`: the four figures for CPU and memory, the coverage, one evaluation instant, a 10-minute cache of answers (never of failures) |
| docs/01, "Thanos on onboarding: Never queried while creating a namespace" | A create reads no usage, nor does a change that leaves the quota (tested) |
| docs/03, "Coverage: a namespace needs at least 80% of the window's steps, or it gets insufficient-data"; "Missing is not zero ... A failed or warned query gives that cluster's namespaces insufficient-data for the day, never a zero" | `usage.py` `_judge_coverage`; `thanos.py` `parse_answer` treats `warnings` as a failure; `sample()` drops NaN and infinities |
| docs/03, "Verdicts": quota-oversized, quota-tight, requests-oversized, idle, right-sized, insufficient-data, with the per-environment table | `capacity/verdicts.py` `judge` and `headline`; the thresholds are the table's, overridable in `analysis.yaml` |
| docs/03, "Running the sweep" and "Data model and API": the daily sweep, `analysis_sweeps`, `namespace_verdicts`, 13 months | `capacity/sweep.py`, the worker job `usage_sweep` (every 24 hours), migration 0010 |
| docs/01, Lists: "facets.attention counts quota-tight, near limit, open recommendation, oversized, idle and open request ... Severity for sorting: quota-tight or 95% used 3, 80% used 2, a recommendation, oversized or idle 1"; "Rows come from the watch cache joined in memory with the latest verdicts" | `GET /api/v1/quotas`: `verdict`, `verdictKind`, `verdictResources`, `verdictReason`, `verdictDay` on each row; facets `quota-tight`, `oversized`, `idle` and `needs-attention`; `verdict=` filter; `listquery.severity` level 1; one query for the latest verdicts per request |

## What is not built, and why

- **Recommendations** ("Recommendation {id}", "Use this size"). docs/03, "Delivery": "Phase 6: recommendations, workload hints, apply and
  dismiss, the rightsizing loop and the backtest". They have their own table and endpoints (`.../recommendations/{rid}:apply`). Left
  out; the open-recommendation facet and severity's "a recommendation" come with them (#12).
- **The other verdicts** of docs/03 (no-quota, requests-undersized, cpu-throttled, memory-limit-risk, zone-skew) need queries this
  build does not make. Until they are built, `right-sized` means none of the built verdicts holds. Follow-up #703.
- **The namespace usage and analysis endpoints** (`GET .../namespaces/{ns}/usage`, `.../analysis`, `/analysis/namespaces`,
  `/analysis/summary`) and `POST .../analysis/sweeps:run`. The story's criterion is the plan and the list. Follow-up #704.
- **cmapi-capacity as a service.** docs/01, "One interface, two modes": "capacity.mode: embedded runs the same package, cmapi.capacity,
  inside the worker for development and small installs". This build is the embedded mode: the API reads a plan's usage, the worker
  runs the sweep, and the tables are in the cmapi schema.
- **Partitions of namespace_verdicts.** docs/03 has `PARTITION BY RANGE (day)`. A partition per month needs DDL at run time, and each
  one is a table that `alembic check` reports against the models. The sweep deletes rows past 395 days instead. Follow-up #705.
- **Off-peak per region.** The sweep runs every 24 hours from the worker's first start, one cluster at a time.

## Decisions

1. **The source is `none` unless an instance names `thanos`** (`capacity.yaml` `usage.source`). With `none`, every plan and every
   row says insufficient data and why, and no extra approval is added: an instance whose reader lacks `cluster-monitoring-view`,
   or a cluster with monitoring off (CRC, #489), keeps working as before. `unavailable` (Thanos named and not answering) is what
   adds the platform approval, as docs/01 says. A safe default that calls no outside service until configured, and that says so.
2. **An answer with `warnings` is a failure.** docs/03: "A failed or warned query gives ... insufficient-data".
3. **`requestToPeakRatio` counts only the resources the change raises**, as the mockup's `ratioFlag` does: a decrease is never
   "possible over-provisioning".
4. **The plan's figures are null unless the state is `ok`.** Insufficient data is said, never shown as numbers to judge by.
5. **The headline's waste order** is idle, then quota-oversized, then requests-oversized: idle holds the whole quota unused, and
   quota slack blocks placement before request slack blocks nodes (docs/03, "Gap").
6. **`evaluatedAt` is a string** (RFC 3339): the plan routes dump the view without JSON mode.

## Sources, read on 2026-11-25

- Prometheus, query functions, <https://prometheus.io/docs/prometheus/latest/querying/functions/>: `avg_over_time` "the average value of
  all float or histogram samples in the specified interval"; `max_over_time` "the maximum value of all float samples in the specified
  interval"; `quantile_over_time` "the φ-quantile (0 ≤ φ ≤ 1) of all float samples in the specified interval"; `count_over_time` "the
  count of all samples in the specified interval"; `rate` "calculates the per-second average rate of increase of the time series in
  the range vector".
- Prometheus, querying basics, <https://prometheus.io/docs/prometheus/latest/querying/basics/>: "Subquery allows you to run an instant
  query for a given range and resolution. The result of a subquery is a range vector."
- Prometheus HTTP API, <https://prometheus.io/docs/prometheus/latest/querying/api/>: "GET /api/v1/query"; `time` "Evaluation timestamp.
  Optional."; `warnings` "Only set if there were warnings while executing the request."; "Instant vectors are returned as result type
  `vector`."
- Thanos Querier, <https://thanos.io/tip/components/query.md/>: partial response "If true, then all storeAPIs that will be unavailable
  (and thus return no data) will not cause query to fail"; dedup "controls if query results should be deduplicated using the replica
  labels".
- cAdvisor, <https://github.com/google/cadvisor/blob/master/docs/storage/prometheus.md>: `container_cpu_usage_seconds_total` "Counter |
  Cumulative cpu time consumed | seconds"; `container_memory_working_set_bytes` "Gauge | Current working set | bytes".
- kube-state-metrics, <https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/policy/resourcequota-metrics.md>:
  `kube_resourcequota` with labels `resourcequota`, `namespace`, `resource`, `type`; the `type` values from
  <https://github.com/kubernetes/kube-state-metrics/blob/main/internal/store/resourcequota.go>: `LabelValues: []string{string(res), "hard"}`
  and `LabelValues: []string{string(res), "used"}`. `kube_pod_status_phase`, "The pods current phase", `phase` Pending, Running,
  Succeeded, Failed or Unknown (<https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/pod-metrics.md>).
