# Reviewer 2 (Opus 5.5, high) · cmapi PR #734

**Verdict: all four of reviewer 1's findings are real defects. I lower H1 and H2 to Medium and narrow one part of Codex's
patch.** [`r2-outputs/final.diff`](r2-outputs/final.diff) applies to a fresh copy of `head/` with `patch -p1 -F0`. Applied to
`r2-work/proof2/`, it gives a tree byte-identical to `r2-work/final/` (`r2-work/proof/` holds an earlier version, which differed
only in wording). All runs below used
PostgreSQL 16 at `127.0.0.1:55432/cmapi_r2_734` where a database was needed. No cluster was touched.

## Verdict per finding

Each test below fails on head and passes on the final tree. Head's failures are in
[`r2-outputs/before-and-codex-with-r2-tests.log`](r2-outputs/before-and-codex-with-r2-tests.log): 11 failed and 19 passed. The
create-path control passed on head.

| # | Codex | Mine | Evidence |
|---|---|---|---|
| H1: cached usage ignores a fresh finding | High | **Confirmed, Medium** | Head's own docs/02 (line 834, this PR): "while any of them stands the cluster's usage is unavailable". `PromUsage.namespace` returns a cache hit before `ThanosQuerier.query` can check `usage_findings`, so a warm answer outlives the finding for up to `CACHE_SECONDS = 600`. `test_probe_finding_takes_precedence_over_cached_usage` fails on head with `'insufficient-data' == 'unavailable'`. **Why not High:** a cached answer was read while the last check found the grants held, so it is real data, not data allowed only by a grant to everyone. The check itself runs on the 300 s relist (the `ClusterRegistry` default, which `context.py` does not override), so the design already accepts a revoked grant going unseen for up to 5 minutes. The cache stretches that window to 10 minutes. It is a broken contract, not a bypass. |
| H2: client published before its grants are reviewed | High | **Confirmed, Medium** | `registry.get()` returns the state whatever its status (registry.py:754). `ThanosQuerier.query` checks only `client is None`. On a first import, a reconnect or a rotation, head publishes `st.client` under the lock, then starts the caches and only then runs discovery and the two LSARs, while `usage_findings` is still `[]`. On head, `test_new_client_is_private_until_its_grants_are_checked` sees the new client inside each review: `[<client>] == [None, None]`. **Why not High:** the window lasts as long as one discovery call and two reviews. That is milliseconds, and at most about 30 s at the client's 10 s httpx timeout (kube.py:103), against the 300 s relist window above. Within that window it is exactly what #724 forbids, a query backed by no check at all, so it is fixed. |
| M1: old `cmapi-reader-monitoring` ClusterRoleBinding survives an upgrade | Medium | **Confirmed, Medium** | cmapi shipped this object, by this exact name, in `base/examples/baseline/cmapi-reader-rbac.yaml:71` (`metadata: {name: cmapi-reader-monitoring}`, roleRef `cluster-monitoring-view`). It was also in base `docs/02:633`, and `deploy/baseline-crc.sh` applies that file. `cluster-monitoring-view` on `release-4.18` grants `get` on `prometheuses/api` `k8s` cluster-wide (fetched `assets/cluster-monitoring-operator/cluster-role-view.yaml`). So an upgraded cluster keeps the wide grant, and the query review passes through it. The deletion names one kind and one name. My stricter test asserts that the only `oc delete` the script runs is `oc delete clusterrolebinding cmapi-reader-monitoring --ignore-not-found`, and that it runs after the apply. On head the list of deletes is `[]`. `--ignore-not-found` is kubectl's flag ("Treat \"resource not found\" as a successful delete", `release-1.31` `staging/src/k8s.io/kubectl/pkg/cmd/delete/delete_flags.go:152`). `oc` wires kubectl's delete (`openshift/oc` `release-4.18` `pkg/cli/cli.go:264`, `kubectlwrappers.NewCmdDelete`). I did not check whether the live CRC still holds the object; that is a read for the coordinator. |
| M2: `evaluationError` reported as a missing grant | Medium | **Confirmed, Medium** (as a diagnosis defect) | `release-1.31` LSAR `rest.go:95-102`: `Allowed: (decision == authorizer.DecisionAllow)`, `EvaluationError = BuildEvaluationError(evaluationErr, …)`. In `union.go`, an allow returns at once, and otherwise errors are aggregated with `NoOpinion`, so `allowed:false` with an error means that some authorizer failed to decide. I verified the case the type comment names ("RBAC can be missing a role") and it does **not** come through `evaluationError`. `rbac.go` (`release-1.31`, and `openshift/kubernetes` `release-4.18` lines 124-126) puts role-resolution errors in `reason` and returns `nil` error. So a missing `cluster-monitoring-metrics-api` Role stays a "missing grant" under the fix, which is correct. Head also pointed 503, timeout and malformed answers at "Apply the grants". The four `test_inconclusive_review_preserves_reads_and_recovers` cases fail on head. The usage outcome is the same before and after; only the diagnosis and the fix change. |

## Codex's patch, line by line: what I kept, narrowed and changed

- **Kept, H2 (registry.py).** `_usage_grants` moves ahead of the publish, and `usage_findings` is set under the same lock as
  `client, ledger, cache`. `ThanosQuerier.query` reads `registry.snapshot()`, a copy under the lock, so the client and its
  findings always come from one check. The cost is that on a new client the watches start after discovery and the two reviews,
  not before. A read in that interval gets the existing 503 for a cluster with no cache.
- **Narrowed, H1 (thanos.py, usage.py).** Codex's cache guard was `checked_cluster`, which also raised when `client is None`.
  So a cluster that drops returned `unavailable` from a warm cache, where head served the cached answer. That changes behaviour
  beyond the finding, as [`dropped-client-cache.log`](r2-outputs/dropped-client-cache.log) shows: head and final serve the cache,
  and Codex returns `unavailable | … is unreachable: no client`. I replaced it with `ThanosQuerier.check_grants`, which refuses
  only on `usage_findings`, and a module helper `_refuse_findings` that `query` shares. `query` keeps its original order. New
  test: `test_a_cached_answer_is_hidden_by_a_finding_and_not_by_a_dropped_client`.
- **Kept and tidied, M2 (kube.py, registry.py).** `access_review` returns `None` for "no, with `evaluationError`". The
  docstring now quotes the API type. A `USAGE_UNCHECKED` finding without `GRANT_CHECK` gets the fix "Check the cluster's API
  server and its authorizers; the next import check, or :probe, asks again." The 403 on the review keeps the baseline fix.
  `GRANT_CHECK not in finding` replaces Codex's double `startswith`. I also reflowed a 139-character line.
- **Declared and tested, a change Codex made without listing it.** Codex also changed the fix for
  `usage: the cluster serves no monitoring.coreos.com/v1 …`. Head told the operator of a kind cluster to "Apply the reader's
  openshift-monitoring grants", but kind has no `openshift-monitoring` to hold them. That is a Low defect introduced by this PR.
  I kept the change, named the finding `USAGE_NO_MONITORING` with one shared definition, and worded the fix "No grant can fix
  this: the cluster has no OpenShift monitoring, so its usage stays unavailable." A test asserts it, and it fails on head.
- **Kept, M1.** `deploy/baseline-crc.sh` deletes after the apply, so the reader is never left without a grant. The comments in
  the manifest and `examples/README.md` give the same step for externally run baselines.
- **Replaced** Codex's `test_usage_finding_allows_namespace_read_and_create_plan`. It stubbed the open-request lookup, the pause
  flag and the capacity check. The replacement runs the real write path on PostgreSQL (below).
- **README** (review record): Codex's least-privilege paragraph is accurate. An LSAR holder learns any subject's decision in
  that namespace, including from authorizers other than RBAC, and a binding to `system:serviceaccounts` would also satisfy the
  check. I reflowed it and aligned the "Not a refusal" paragraph with the three fix texts.

The design holds: a namespace create never queries Thanos, and a missing grant keeps the cluster connected. Both are proven
below.

## What Codex missed, in the changed lines

1. **The cache guard's side effect** (narrowed above, with its test). Codex's own run could not catch it: none of its tests had
   a dropped client with a warm cache.
2. **The no-monitoring fix text** was changed without being reported (declared above, with its test).
3. **The real create path was unverified.** Codex says so itself. `test_a_namespace_is_created_and_its_quota_changed_without_the_grants`
   runs it with `usage.source: thanos` and both grants missing, on PostgreSQL. CRC stays `connected` with 2 usage findings. A
   `POST /namespaces` is auto-approved, and `run_jobs` reaches `synced` with `Namespace//payments-dev` applied. The namespace
   GET answers 200. A quota-change dry run carries `usage.state == "unavailable"` with the finding in the reason. The real PATCH
   is `pending_approval` with the slot `{"group": "approver-platform", "count": 1, "reason": "Live usage unavailable"}`. Across
   all of it, there is no `monitoring_get` and no Route `get`. This passes on head as well, so the PR's design claim stands.
   The test now guards it.
4. **docs/02 needs one sentence after this patch** (it is a live-doc export, so the coordinator edits the live doc first). Line
   834 says the findings' `findingDetails` "give the fix 'Apply the reader's openshift-monitoring grants …'". With the patch,
   that is true for missing grants and for the 403 on the review. An inconclusive review instead says "Check the cluster's API
   server and its authorizers; the next import check, or :probe, asks again", and the no-monitoring finding says "No grant can
   fix this …". After "without a query (…)", add: "A warm usage cache is not served while a finding stands
   (`ThanosQuerier.check_grants`)." The README's `## Tests` table also needs the seven new tests from the record.

## Runs

| Run | Tree | Result | Log |
|---|---|---|---|
| Codex's new tests and `test_the_baseline_an_owner_needs_is_a_command`, on head code, PostgreSQL | `r2-work/before` | 9 failed, 20 passed. One failure is the fake's `get`→`snapshot` rename, not behaviour | `before-codex-tests.log` |
| 12 changed and related service files, Codex's patch, PostgreSQL | `r2-work/codex` | **343 passed** | `codex-service.log` |
| My tests on head code / on Codex's patch | `before` / `codexplus` | 11 failed, 19 passed / 2 failed (my rename and wording only), 28 passed | `before-and-codex-with-r2-tests.log` |
| Cached answer on a dropped client | head / codex / final | served / `unavailable` / served | `dropped-client-cache.log` |
| 14 changed and related service files (the 12 above plus `test_cluster_import_log_456.py` and `test_flow.py`), PostgreSQL, `final.diff` applied to a fresh `head/` copy | `r2-work/proof2` | **367 passed in 201.92s (0:03:21)** (the earlier version of the patch on `proof/`: 367 passed) | `proof2-service.log`, `proof-service.log` |
| `tests/core`, `venv-ref` python, workspace `GOCACHE` | `r2-work/final` | **843 passed, 113 skipped**, 1 warning (Codex had 841 and 115 skipped in its own sandbox) | `final-core.log` |
| `bash deploy/tests/crc-scripts-test.sh` | `r2-work/final` | **287 ok, 0 failed** | `final-crc-scripts.log` |
| `bash deploy/render-test.sh` | `r2-work/final` | **96 ok, 0 failed** | `final-render-test.log` |

## Backlog (predates this PR)

- `deploy/crc-rollback.sh` never deleted `cmapi-reader-monitoring` on base, and does not on head. It matters only on a CRC that
  was once baselined with `baseline-crc.sh`.
- `KubeClient.served` takes any non-404 answer below 400 as served (reviewer 1's Low; I confirmed it in the code).
- Low, in changed behaviour but in a pre-existing string: `PromUsage` prefixes every `MetricsUnavailable` with "Thanos did not
  answer: ", so a usage finding reads "Thanos did not answer: CRC: usage: missing grant …" although nothing was asked.

## Sources (fetched 2026-11-26)

- kubernetes `release-1.31`: `plugin/pkg/auth/authorizer/rbac/rbac.go` (`reason = fmt.Sprintf("RBAC: %v", …)`,
  `return authorizer.DecisionNoOpinion, reason, nil`); `pkg/registry/authorization/localsubjectaccessreview/rest.go`;
  `staging/src/k8s.io/apiserver/pkg/authorization/union/union.go`; `staging/src/k8s.io/api/authorization/v1/types.go`
  ("EvaluationError is an indication that some error occurred during the authorization check");
  `pkg/registry/authorization/util/helpers.go` (`BuildEvaluationError`);
  `staging/src/k8s.io/kubectl/pkg/cmd/delete/delete_flags.go`.
- openshift/kubernetes `release-4.18`: the same `rbac.go` and LSAR `rest.go` lines.
- openshift/cluster-monitoring-operator `release-4.18`: `assets/cluster-monitoring-operator/cluster-role-view.yaml`.
- openshift/oc `release-4.18`: `pkg/cli/cli.go`.
