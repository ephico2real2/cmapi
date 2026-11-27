# #751: deliverer-agnostic delivery, `delivery.mode: gitops`

Part of stories #18 and #19. The design below was written on 2026-11-27, before the code, by the implementer (Opus 5.5 at
`high`). One model family designed it; the pull request gets two reviewers.

The inputs, kept in this folder:

- [`coordinator-assessment.md`](coordinator-assessment.md): the owner's decision ("It shouldn't matter what apply the
  rendered yaml", "Build gitops mode now") and the three cases the design must handle.
- [`should-cmapi-apply-directly.md`](should-cmapi-apply-directly.md): the owner's question and the coordinator's answer.
  `gitops` is the normal mode, `apply` stays for clusters with no deliverer, and GitHub Actions never apply.

## 1. The primary sources, read on 2026-11-27

| Source | What it says, quoted | What it means here |
|---|---|---|
| Kubernetes, "Server-Side Apply", <https://kubernetes.io/docs/reference/using-api/server-side-apply/> | "If you remove a field from a manifest and apply that manifest, Server-Side Apply checks if there are any other field managers that also own the field. If the field is not owned by any other field managers, it is either deleted from the live object or reset to its default value, if it has one." | A key or object the plan removes is not gone just because a deliverer applied the folder: another manager can keep it. Only a read of the live object shows whether it went. |
| The same page | "When two or more appliers set a field to the same value, they share ownership of that field." | The deliverer's success says nothing about the values another manager holds. The read compares values. |
| Kubernetes source, `pkg/apis/core/v1/defaults.go`, <https://raw.githubusercontent.com/kubernetes/kubernetes/master/pkg/apis/core/v1/defaults.go>, `SetDefaults_LimitRangeItem` | "If a default limit is unspecified, but the max is specified, default the limit to the max"; "If a default limit is specified, but the default request is not, default request to limit"; "If a default request is not specified, but the min is provided, default request to the min". Only for `Type == v1.LimitTypeContainer`. | The API server adds keys to a Container LimitRange item. The read applies the same three rules to the plan before it compares, so a server-added default is never a difference. |
| The same file, `SetDefaults_Namespace` | "adds a default label for all namespaces" (`kubernetes.io/metadata.name`). There is no `SetDefaults_ResourceQuota`. | The server adds a label to every Namespace (already in `liveOnlyKeys`), and nothing to a ResourceQuota's `spec.hard` but its canonical spelling, which `qty` handles. |
| Argo CD, `pkg/apis/application/v1alpha1/types.go`, <https://raw.githubusercontent.com/argoproj/argo-cd/master/pkg/apis/application/v1alpha1/types.go> | `SyncStatusCodeSynced`: "desired and live states match". `OperationState.Message`: "any pertinent messages when attempting to perform operation (typically errors)". `ApplicationConditionSyncError`: "controller failed to automatically sync the application". | Argo CD's status is its own comparison of its own desired state, and its message carries the error when an apply fails. That makes it a useful signal, not proof of cmapi's plan. |
| Argo CD, "Diffing Customization", <https://argo-cd.readthedocs.io/en/stable/user-guide/diffing/> | "Argo CD allows ignoring differences at a specific JSON path, using RFC6902 JSON patches and JQ path expressions." | An Application can report Synced while a field cmapi approved differs. So the status alone does not prove the plan. |
| Argo CD, "Automated Sync Policy", <https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/> | "By default (and as a safety mechanism), automated sync will not delete resources when Argo CD detects the resource is no longer defined in Git." "Automatic sync will not reattempt a sync if the previous sync attempt against the same commit-SHA and parameters had failed." | Case 3 is the default for Argo CD: a removal can wait for ever without any failure. A failed apply is not retried by itself either, so the signal's error is what an operator needs to see. |
| Argo CD, "Sync Options", <https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/> | "Resources such as Namespaces are critical and should not be pruned without confirmation." "You can set the `Prune=confirm` sync option to require manual confirmation before pruning." | cmapi renders `Prune=confirm` on its objects (docs/01). Under Argo CD every removal waits for an operator. |
| Argo CD, "Resource Health", <https://argo-cd.readthedocs.io/en/stable/operator-manual/health/> | "Argo CD App health is inferred from the health of its immediate child resources". | Health is shown in the signal, never used as proof. |
| Flux, "Kustomizations", <https://fluxcd.io/flux/components/kustomize/kustomizations/> | `.spec.prune` "is a required boolean field to enable/disable garbage collection for a Kustomization." Ready True: "the source was fetched, the kustomization was built and applied on the cluster". Ready False reasons: "PruneFailed \| ArtifactFailed \| BuildFailed \| HealthCheckFailed \| DependencyNotReady \| ReconciliationFailed"; the message "will contain more information about why the reconciliation failed". `status.lastAppliedRevision`: "the last revision ... that was successfully applied"; `status.lastAttemptedRevision`: "the last revision ... that was attempted". | A Kustomization with `prune: false` never removes anything (case 3). Its Ready condition and the two revisions tell "not applied yet" from "applied and failed" (case 1), when cmapi can read them. |

**What a deliverer-agnostic confirmation must compare.** Each deliverer reports on its own desired state, in its own
scope, with its own ignore rules. None of them reports on cmapi's approved plan. Server-side apply does not remove what
another manager co-owns, and the API server adds defaults. So the only proof is a read of the live objects, compared with
the plan, field by field, after the server's own defaults and the keys that only the cluster writes are taken out.

## 2. The design

### D1. Three modes; `gitops` is the normal one

| Mode | Who applies | What ends a create or change | What ends a delete |
|---|---|---|---|
| `gitops` (new) | Anything that applies `main`: Argo CD, Flux, ACM, a pipeline | The full-plan read (D2). The deliverer's status is optional signal (D4) | A read of absence (D6) |
| `argocd` (kept) | Argo CD | Argo CD has compared a revision at or after the merge, this folder's objects are Synced, and then the full-plan read | A read of absence, after the operator confirms in Argo CD |
| `apply` (kept) | cmapi's worker, as the deliverer identity, before the merge | The full-plan read, then the merge | `POST /admin/prune:confirm`, the worker's delete, then a read of absence |

- `gitops` is the mode to choose for a cluster that has a deliverer. `apply` is for a cluster with no deliverer, such as
  CRC today (`should-cmapi-apply-directly.md`). GitHub Actions never apply: they validate only.
- **The default stays `argocd`.** A configuration without `delivery.mode` keeps its behaviour, and the chart's guard that
  Argo CD's controller is contained keeps holding for it. Making `gitops` the default is one line in `core/sync.py` and in
  the chart's values, for the owner to decide.
- **`argocd` does not become `gitops` plus the signal.** The reasons:
  1. The owner's brief and #751 say `argocd` behaves as before, and the existing tests of its gate stay as they are.
  2. Its gate adds evidence that the read alone lacks: Argo CD has compared a revision that contains the merge commit. So
     the deliverer that owns the fields has taken this commit, not only reached the same values.
  3. A site that does not want the gate chooses `gitops` with `delivery.signal: argocd`. Both modes read the same
     `delivery.argocd` block, so no setting moves.
- Per cluster, `clusters.yaml` `delivery` takes the same three values. An unknown mode in either file now stops the start.
  Before, a misspelled mode silently ran as `argocd`.

### D2. The full-plan read (`core/sync.py`, `read_plan`), in every mode

It replaces `confirmed_by_read`'s check of the Namespace and its quota hard values. It also closes the comparison part of
#26's deferred B4. B4's `managedFields` comparison stays deferred.

| Object | What is compared | What is left out |
|---|---|---|
| The Namespace | It exists. Each label and annotation the plan writes has the same value live. Each label and annotation that the previous folder's Namespace held, and the plan drops, is absent live | Keys that match `liveOnlyKeys` (`metadata-keys.yaml`), and keys under a skip prefix of `adoption.yaml` (D3's `skip.keyPrefixes`). A live key that neither the plan nor the previous folder holds is not the plan's: the drift view (#481) covers it |
| Every ResourceQuota of the plan | It exists. `spec.hard` equal in both directions, by value (`qty`: `5120Mi` equals `5Gi`). `spec.scopes` and `spec.scopeSelector` equal | Labels and annotations of the quota |
| Every LimitRange of the plan | It exists. `spec.limits` item by item: the same `type`, and `max`, `min`, `default`, `defaultRequest` and `maxLimitRequestRatio` equal in both directions, by value, after the plan's Container items get the API server's three defaults (section 1) | Labels and annotations |
| Each object the plan removes | Absent. An object is removed when the previous folder holds its kind, namespace and name and the plan does not: a file rename that keeps the object is not a removal | |

- The read goes to the watch cache first, then to the reader directly, as before. A removed object counts as absent only
  when the cache does not hold it and a direct read finds nothing. A read that fails is never absence.
- A cluster that cannot be read (`ClusterUnreachable`) is a wait, as before. Any other failed read of one object is a
  difference that names the object and the error.
- Each difference names the object, the field, the plan's value and the live value:
  `LimitRange/payments-dev-cpu spec.limits[0].max.cpu: plan '4', live '2'`.
- **Why the extra checks cannot fail on their own.** In `apply` mode cmapi writes every key the plan holds and deletes what
  it removes. Under Argo CD the read only runs once Argo CD has reported this folder Synced. A key that another manager
  co-owns and that the plan drops stays live (section 1). That is a real difference from the plan, and it is named.

### D3. `gitops`: after the merge

`watch_sync`, every `syncSignal.pollInterval`:

1. Git `main`'s folder equals the approved plan. If not, the request is refused at once, as in `argocd` mode: the
   deliverer applies `main`, so the cluster cannot reach this plan.
2. The full-plan read. Equal: `synced`, by `gitops`.
3. Not equal: a `sync_wait` event with the differences and the signal (D4), and the next poll.
4. At `delivery.syncTimeout` (one clock from the merge, or from a `:retry`):
   - When every difference is a removed object that is still there: `awaiting_prune` (case 3, D5).
   - Otherwise: `sync_failed`, and a `sync_differences` event that lists every difference in its detail. The move's note
     names the first ones and the deliverer's last signal.

### D4. Case 1: "not applied yet" against "applied and failed"

With only a read, both look the same until the timeout. So:

- `delivery.signal` (`gitops` mode only): `none` (the default), `argocd` or `flux`.
  - `argocd`: the Application of `delivery.argocd` (`namespace`, `rootApplication`): sync status, health, the operation's
    phase and message, and each `*Error` condition's message.
  - `flux`: the Kustomization of `delivery.flux` (`namespace`, default `flux-system`; `kustomization`, default
    `cluster-configs-{clusterId}`): the `Ready` condition's status, reason and message, `lastAppliedRevision` and
    `lastAttemptedRevision`.
- The signal is read with the cluster's reader. When it is not configured, not there, forbidden or unreachable, the note says
  so in one phrase and nothing else changes. It never confirms and never fails a request: it only joins the `sync_wait`
  note and the `sync_failed` note, so a person sees the deliverer's error ("admission webhook denied ...") beside the
  differences.
- The reader needs `get` on the signal's object. Argo CD Applications are in the baseline grant already. A Flux
  Kustomization needs a Role in its namespace; without it the note says "forbidden".
- Without a signal, the `sync_failed` note and its `sync_differences` event list the exact differences.

### D5. Case 3: a deliverer that does not prune

Argo CD without automated prune (its default) and Flux with `prune: false` never remove an object. Waiting for absence
would end every such request in `sync_failed`, which is wrong: everything else was delivered.

- At the timeout, when the only differences are removed objects still on the cluster, the request moves to
  `awaiting_prune` (lock held, reservation released), not `sync_failed`. The note is the operator notice: "the deliverer has
  not removed N object(s) this plan removes: <names>. Remove them, or prune in the deliverer; a read of their absence ends
  the request." It is also logged (`prune_waiting`), and `CmapiPruneStuck` fires after a day in `awaiting_prune`, as for a
  delete.
- The `prune` job then reads the full plan every poll, without a time limit, as it waits for a namespace today. When it
  matches, the request is `synced` (`prune_confirmed`). A cluster that cannot be read for `syncTimeout` moves it to
  `sync_failed` (`_cannot_read`, as for a delete).
- `:retry` of a `sync_failed` change goes back to `watch_sync`. One new transition, `sync_failed` to `awaiting_prune` on
  `prune_pending`, lets a retried change that ends with only removals left wait there too.
- `argocd` and `apply` keep their behaviour: `argocd` waits for its own confirmation, and `apply` removes the objects itself.

### D6. Deletes in `gitops`

As in `argocd` mode, with no Argo CD in it: on the merge the request moves to `awaiting_prune` with the note "waiting for
the deliverer to remove the namespace; a read of its absence ends the request", and the `prune` job reads the namespace
every poll. A successful read that finds nothing: `synced`. A namespace that is still there waits without limit
(`CmapiPruneStuck` after a day). A deliverer that does not prune is the same wait, with the same notice, and an operator
removes the namespace in the deliverer or by hand. A namespace that cmapi does not manage is refused as today.

### D7. Case 2: a newer request superseding an older one. Checked, and it cannot happen

The assessment's case is two requests for the same namespace merged close together, so that the older request's read sees
the newer values and never matches. **Within one instance, cmapi's lock makes that impossible.** The evidence:

- The lock is the partial unique index `uq_cr_open_namespace` on `(cluster_id, namespace)` over `OPEN_STATES`
  (`core/db/models.py`, migration `0005`).
- `OPEN_STATES` holds `merged`, `awaiting_prune` and `sync_failed`. So a request holds the namespace from its approval until
  it is `synced`, `reverted` or another final state. A second request for that namespace is refused with 409 at its
  submission (docs/01, step 4: "At most one open request per namespace").
- Each instance has its own repository (docs/01, "Git"), so no other instance writes the folder.

So the older request is always confirmed, failed or handed to a revert before a newer one can exist. What is left is a
change of `main`'s folder that no cmapi request made: a direct commit. D3 step 1 refuses that at once, naming it, as
`argocd` mode does. A new state "superseded after the merge" would be code that no path reaches, so it is not built
(the owner's rule: build more only when it is the only solution). The test
`test_gitops_a_second_request_waits_for_the_first_to_be_confirmed` proves the premise, and
`test_gitops_main_changed_after_the_merge_is_refused_with_the_reason` proves the refusal.

### D8. Configuration (`integrations.yaml`, `clusters.yaml`, the chart)

```yaml
delivery:
  mode: gitops                 # argocd (default) | gitops | apply
  syncTimeout: 30m
  signal: flux                 # gitops only: none (default) | argocd | flux
  argocd: {namespace: openshift-gitops, rootApplication: "cluster-configs-{clusterId}"}
  flux: {namespace: flux-system, kustomization: "cluster-configs-{clusterId}"}
```

- An unknown `mode` or `signal` stops the start, naming the value.
- The chart writes `signal` and `flux` from `delivery.signal` and `delivery.flux`. In `gitops` mode the hub's containment
  policy binds `delivery.gitops.delivererServiceAccount`, the outside deliverer's identity on the hub, as `argocd` mode binds
  Argo CD's controller. An empty value fails the render unless `delivery.gitops.acknowledgeUncontainedDeliverer` is true, as
  for Argo CD.

## 3. The tests (each fails before the change and passes after)

`cmapi/tests/service/test_gitops_delivery_751.py`, on PostgreSQL:

| Test | Proves |
|---|---|
| `test_gitops_an_outside_deliverer_applies_the_folder_and_cmapi_confirms_synced` | The test plays the deliverer: it applies `main`'s folder. cmapi confirms `synced` with no Argo CD |
| `test_gitops_nothing_applied_waits_then_fails_naming_the_namespace` | Case 1 without a signal: `sync_failed`, the differences named |
| `test_gitops_a_missing_label_stays_unconfirmed_then_fails_naming_it` | A label the plan writes, missing live |
| `test_gitops_a_differing_limitrange_stays_unconfirmed_then_fails_naming_it` | A LimitRange value that differs |
| `test_gitops_a_server_defaulted_limitrange_still_confirms` | The API server's defaults are not differences |
| `test_gitops_a_leftover_removed_object_waits_in_awaiting_prune_then_synced_when_gone` | Case 3, and its end by a read of absence |
| `test_gitops_a_leftover_beside_another_difference_is_sync_failed` | A removal beside a real difference is a failure, not a prune wait |
| `test_gitops_a_delete_is_confirmed_by_absence` | D6 |
| `test_gitops_signal_shows_the_deliverers_error_and_never_gates` | Case 1 with Argo CD and with Flux: the error is in the note; an unreadable signal changes nothing |
| `test_gitops_a_second_request_waits_for_the_first_to_be_confirmed` | Case 2's premise (D7) |
| `test_gitops_main_changed_after_the_merge_is_refused_with_the_reason` | D3 step 1 |
| `test_apply_mode_now_reads_the_full_plan` | `apply` refuses to confirm a label the cluster did not take |
| `test_an_unknown_delivery_mode_stops_the_start` | D1 |

`cmapi/tests/core/test_read_plan_751.py`: the comparison itself (server-only keys, skip prefixes, quantities, defaults,
renames, a failed read is never absence).

`argocd` and `apply` keep their existing tests unchanged: `test_second_pass.py`, `test_watch_sync_client_once_402.py`,
`test_review_d_delivery.py`, `test_review_h_tools_migrate.py`, `test_review_255_apply.py`, `test_flow.py`.
