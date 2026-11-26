**PostgreSQL was unreachable.** The sandbox denied the connection to `127.0.0.1:55432/cmapi_r1_718` with “Operation not permitted”. The three PR service tests stopped in fixture setup on base, head and the patched copy. The two existing create/delete delivery tests also stopped in setup on head. I used no SQLite. The worker and policy results below come from independent executions without a database.

# cmapi PR #718 — request changes

Head fixes the ordinary single-quota raise, numeric network-exposure increase and sensitive-label restoration. It still misses required approvals for supported folder layouts and can both accept an over-capacity restore and refuse one that already fits. The design requires “a new request through the same approval rules”. [Design, state table](head/docs/01-design-and-architecture.md#L244) · [PR author’s review record](head/docs/reviews/2026-11-26-issue-716/README.md)

## Findings

| Severity | What fails on head | Fix and regression evidence |
|---|---|---|
| **High** | **A failed sync invalidates the capacity baseline.** Head adds the Git delta to a live watch total. With 32 CPU live, 8 in Git and 32 to restore, head counts 56 against a limit of 40. In the other direction, with 8 live, 32 in Git and 36 to restore, it counts only 12 against a limit of 30. The PR’s test first waits for “synced” and then sets the row to `sync_failed`, which cannot expose this discrepancy. [Restore calculation](head/cmapi/src/cmapi/core/pipeline.py#L655) · [Live total](head/cmapi/src/cmapi/core/capacity_backend.py#L88) · [PR fixture](head/cmapi/tests/service/test_revert_sizing.py#L32) | Project the restored quota objects onto the watched namespace under the ledger lock. Preserve other live quotas and use Git for the approval comparison. The first test now returns 80% and retains the 300% approval fact. The second refuses. Separate cases cover a live sibling and scoped quota. |
| **High** | **A whole-folder restore can lift a binding limit without an approval.** Head selects `own_quota` on each side. When a tighter sibling goes away, the selected object can be identical. The test restores an effective 8 → 32 CPU and 0 → 4 NodePorts. Head reports a 0% increase. Separately, removing the last explicit NodePort cap compares a missing key with `"0"`, so removing a zero cap leaves `networkExposure` false. [Object selection](head/cmapi/src/cmapi/core/render/manifests.py#L106) · [Exposure calculation](head/cmapi/src/cmapi/core/pipeline.py#L669) · [Multiple-quota semantics](head/docs/02-technical-design-v2.md#L1787) | Compare the namespace-wide bounds as well as the selected quota. Recognize removal of the last exposure bound. The sibling test now requires two platform approvals and the last-cap test requires one. |
| **High** | **Historical annotations can omit a newly required beyond-tier approval.** A restored custom quota can contain a value that used to be the catalog default. Head reads only keys named by the old `cmapi.net/beyond-tier` annotation. With a current default of 200 Gi and an unannotated snapshot restoring 400 Gi of storage, the keys are empty and the revert needs zero approvals. The forward planner evaluates the proposed values against the current tier. [Restore](head/cmapi/src/cmapi/core/pipeline.py#L664) · [Forward planner](head/cmapi/src/cmapi/core/pipeline.py#L457) · [Catalog contract](head/docs/02-technical-design-v2.md#L1345) | Evaluate the restored quota and LimitRange values against the current custom tier, compare the object of the same name in Git and retain recorded overrides for a retired tier. The storage test now requires one platform approval. An unchanged out-of-date quota adds none. |
| **High** | **The inverse operation can select the wrong policy.** Undoing a delete into an empty folder uses `action="update"`. With create requiring two approvals and change requiring zero, head returns `dev-change` with zero. Undoing a create hard-codes `protected=False` and `namespaceAgeDays=0`. It opens a delete for a protected namespace and requires one approval where an old namespace needs two. These action and delete defaults predate #718. [Revert worker](head/cmapi/src/cmapi/jobs/open_pr.py#L93) · [Forward delete](head/cmapi/src/cmapi/core/pipeline.py#L595) · [Protection refusal](head/cmapi/src/cmapi/core/approvals.py#L173) | Classify a restored Namespace absent from current Git as a create. Use create metadata semantics and the restored tier’s exposure baseline. For deletion, use the Git protection labels, live creation date and workload counts. The three policy tests now obtain two create approvals, a protection refusal and two delete approvals respectively. |
| **High** | **Target-dependent approval rules receive the wrong inputs.** Head supplies the original request’s team and omits the destination tier. The rule `team == "payments" and tier == "large"` contributes zero slots when restoring that exact destination. The forward plan supplies both values, and submit uses the team again for the daily allowance. [Forward facts](head/cmapi/src/cmapi/core/pipeline.py#L444) · [Revert facts](head/cmapi/src/cmapi/jobs/open_pr.py#L94) · [Submit](head/cmapi/src/cmapi/core/pipeline.py#L611) | Populate team and tier from the restored Namespace and cluster labels from cluster policy. The configured-rule test now gets both required slots. The test installs the rule locally to exercise a supported configuration. |
| **Low** | A missing tier is documented as ranking “below every tier”, but the sentinel order is zero and the catalog permits zero or negative orders. A move from an order-zero tier to an absent tier reports `same`. [Comparison](head/cmapi/src/cmapi/core/tiers.py#L702) | Rank absent definitions below every integer order. The order-zero test now returns `down`. |
| **Low** | A restore can store `beyondTierKeys` and still return a null `beyondTier` in the request an approver reads. The request contract says null “when the request has none”. [Worker’s Plan construction](head/cmapi/src/cmapi/jobs/open_pr.py#L113) · [Request contract](head/cmapi/src/cmapi/core/models.py#L290) | Populate the stored key, tier value, restored value and added approvals. The stored-plan test now shows NodePorts changing from the tier’s 0 to the requested 2. |

## Reservation, refusal and retry

The review record quotes “Released, so the revert request can take it”. In the source table that phrase is in the **Lock** column. The reservation is already released on entry to `sync_failed`. The lifecycle test confirms one release at timeout, release of the parent lock at handoff, and acquisition of both ownership flags by the pending child. [Design table](head/docs/01-design-and-architecture.md#L258) · [State sets and transitions](head/cmapi/src/cmapi/core/lifecycle.py#L93)

Head raises `capacity-exceeded` before submission. In the independent test a refusal produces zero submit calls, the live ledger stays at 8 CPU, and a retry with sufficient room submits once. In production the worker runs the handler in one session, `RequestRepo.move` refreshes the parent under a row lock, and the session calls `s.rollback()` on exception. The retry error is recorded in a separate transaction. The patch extends the PostgreSQL test to assert zero revert rows after refusal and one pending child after the same queued job succeeds. **Database rollback, locking and delivery remain unverified here.** [Worker transaction](head/cmapi/src/cmapi/worker.py#L118) · [Row locking](head/cmapi/src/cmapi/core/db/repo.py#L197) · [Rollback](head/cmapi/src/cmapi/core/db/__init__.py#L44)

There is no durable capacity debit to transfer in this implementation. The deployed adapter’s `reserve` and `release` both return immediately. The project status says “placement and reservations are not built”. The patch corrects the simulated capacity projection. Durable cross-request reservations are a separate implementation project. An external capacity adapter adopting the patch needs the new `check_restore` method. [Implementation status](head/docs/08-code-status.md#L61) · [Adapter](head/cmapi/src/cmapi/core/capacity_backend.py#L98)

## Test evidence

The [24 review tests](.review/applied/cmapi/tests/service/test_restore_policy.py) run the production `open_revert`, planner, simulator, ledger and approval engine with local quota objects. Git, repository operations, requester resolution and submission are test doubles. Capacity projection uses the actual ledger. The child assertions inspect the plan passed to submit. On head an ordinary undo-create produces delete tombstones for the full folder, and an undo-delete reconstructs the files but selects the change policy. The existing delivery tests exercise pruning and reporting of unrestored paths. Their end-to-end results in the author's record are historical. [Undo-create delivery](head/cmapi/tests/service/test_review_d_delivery.py#L166) · [Undo-delete delivery](head/cmapi/tests/service/test_delete_whole_folder_616.py#L505)

| Run | Base | Head | Head with fix applied |
|---|---:|---:|---:|
| Same 24 database-independent cases | 2 passed, 22 failed | 11 passed, 13 failed | **24 passed** |
| Full reference-venv core suite | 840 passed, 115 skipped | 840 passed, 115 skipped | 840 passed, 115 skipped |
| PR’s three PostgreSQL cases | 3 setup errors | 3 setup errors | 3 setup errors |

Eight isolated head mutants each failed their designated test, which passed on unmodified head.

| Mutated behavior | Deciding assertion |
|---|---|
| Zero both capacity deltas | An exceeded restore raises before submit |
| Omit short-name normalization on the current quota | The usage view starts from 8,000 millicores |
| Force `networkExposure=False` | A standalone numeric NodePort raise requires one approval |
| Force `sensitiveKeyChanged=False` | Restoring a changed team label requires one approval |
| Force `beyondTier=False` | A marked beyond-tier NodePort raise requires two approvals |
| Drop the usage facts | A warning and unavailable usage add independent approvals |
| Index a missing restored hard key directly | Restoring a sparse quota on a retired tier completes |
| Force `capacityFresh=True` | A stale watch produces unknown capacity and false freshness |

The patched quota-ledger, citation and review-test run had 92 passes and one deselection. The stock full-document citation check requires `git ls-files`, which fails in these exported snapshots. I ran the same citation checker against the snapshot file list and it passed. The successful core runs used a workspace-local Go build cache after the default cache denied writes. TokenSave reported that the supplied head snapshot had no initialized index, so source references above come from direct reads.

## Behavior beyond sizing and backlog

- A quota change now reads live usage inside the worker’s transaction. A warning, stale capacity and unavailable usage reach the rules independently. The reference rules add a slot for unavailable usage. The tests cover absent target keys, retired tiers and the first quota after a delete. [Usage calculation](head/cmapi/src/cmapi/capacity/usage.py#L329) · [Thresholds](head/examples/instances/nonprod/approval-rules.yaml#L36)
- **Low · Backlog.** The revert still omits expiry facts such as `expirationBeyondLimits`. The #716 record explicitly assigns that work to #717. [Author’s backlog note](head/docs/reviews/2026-11-26-issue-716/README.md#L29)

The [patch against head](r1-outputs/fix.diff) passed `git apply --check` and was applied to a fresh copy. The applied files matched the tested edits with `examples/` excluded. To repeat the isolated tests, run `PYTHONPATH=src python -m pytest --noconftest -o pythonpath= -q tests/service/test_restore_policy.py` in the applied copy’s [cmapi directory](.review/applied/cmapi/) with the service virtual environment.

## Five-line summary

1. Request changes on #718. Ordinary quota, exposure and sensitive-label restores now reach approval rules.
2. Head still misses approvals for binding siblings, removed exposure limits, catalog drift and target-specific rules.
3. Undo-create can delete a protected namespace. Undo-delete can select a zero-approval change policy.
4. The simulated check can double-count or undercount live capacity. PostgreSQL transaction behavior remains unverified.
5. All 24 review cases pass on the applied patch, and the review cases detect all eight head mutants.
