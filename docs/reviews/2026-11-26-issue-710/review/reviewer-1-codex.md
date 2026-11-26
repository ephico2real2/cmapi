# Reviewer 1 · cmapi PR #714

**PostgreSQL was unreachable.** The sandbox denied the connection to the designated loopback test database with `EPERM`. All seven PR service cases stopped in fixture setup on both base and head. The results below come from separate executions of the production planner, approval engine, renderer and revert handler against test doubles. No SQLite, cluster, remote Git or GitHub was used.

**Request changes.** Head fixes the reported named-tier drift on the ordinary update path. A label update from Git's 1 CPU to the catalog's 8 charges 7 CPUs and produces a 700% increase. The revert worker still assumes fresh, fitting capacity, and several valid quota layouts give the ordinary planner a different baseline from its capacity ledger. The attached patch addresses these and the findings below.

## Design evidence

All sources in this table were read on **2026-11-26** from the export. The base text establishes the requirements independently of the PR's additions.

| Source | Design text | Review consequence |
|---|---|---|
| [Base docs/02, Changing a tier](base/docs/02-technical-design-v2.md#L1377) | “increases go through the capacity check and reserve the delta” and “the approval rules apply as for any quota change” | Size the manifests the request actually changes. The same passage assigns skipping a decrease below use to the tiers-rerender operation. |
| [Base docs/02, Tiers](base/docs/02-technical-design-v2.md#L1326), [approval configuration](base/docs/02-technical-design-v2.md#L1831) | “an increase reserves only the delta” and `when: quotaIncreasePct > 100` | A reported 100% does not cross the shipped percentage threshold. CPU and memory are the capacity dimensions. |
| [Base docs/02, Beyond the tier](base/docs/02-technical-design-v2.md#L1345) | “the new quota has more services.loadbalancers or services.nodeports than Git holds; for a new namespace, more than the tier gives” | A genuine create and a rewrite of existing quota have different exposure baselines. |
| [Adoption decision D9](head/docs/reviews/2026-11-14-issue-26-adoption/README.md#L265), [no-quota case](head/docs/reviews/2026-11-14-issue-26-adoption/README.md#L516) | “Any other request, a change of a label for example, leaves every object unchanged.” For a missing quota, “A later quota request adds the object”. | Metadata alone must preserve raw adopted objects and allow a custom namespace to remain without a quota. [Docs/02's several-quota rules](head/docs/02-technical-design-v2.md#L1008) identify the object an ordinary change acts on. |
| [Docs/01, onboarding](head/docs/01-design-and-architecture.md#L42), [base docs/02, failure handling](base/docs/02-technical-design-v2.md#L1420) | “Never queried while creating a namespace or setting its first quota.” Separately, “A quota change on an existing namespace makes one live query”. | The specific first-quota exception covers an already-existing Namespace. Subsequent hard changes read usage. |
| [Docs/01, lifecycle](head/docs/01-design-and-architecture.md#L260) | “the revert is a new request through the same approval rules” | Restoring a snapshot must supply the facts those rules consume. The future temporary burst feature described in docs/02 is a different job. |
| [Docs/16, quota accounting](head/docs/16-data-model.md#L218) | “the namespace-wide hard value is the smallest quantity among unscoped quotas” and “Scoped quotas remain visible but do not enter namespace-wide numbers.” | Measure the change in the ledger's binding CPU and memory values. Its inputs include the short `cpu` and `memory` aliases. |

## Findings and fixes

All test names below refer to `cmapi/tests/service/test_quota_plan_boundaries_710.py` in the patch. Each finding has an assertion that failed on unmodified head and passed after applying the patch.

| Severity | Finding on head | Fix and deciding test |
|---|---|---|
| **High** | **Revert skips quota review.** The worker constructs `fits`, `capacityFresh=True` and an update with no quota, exposure or usage facts. Restoring a prior larger quota or restoring a deleted folder therefore misses the applicable rules. A binding sibling can also disappear while the surviving quota text stays the same. [open_pr.py](head/cmapi/src/cmapi/jobs/open_pr.py#L93) | Assess the exact Git and restoration snapshots, share quota and capacity calculations with ordinary updates, and keep the historical manifests as the delivery payload. The four `test_revert_sizes_the_snapshot_before_submission` cases cover a warning, exceeded capacity, restore after delete and removal of the binding sibling. A warning reaches the plan and approval engine. Exceeded capacity raises before submission. |
| **High** | **Raw hard values can undercharge the ledger and understate an approval threshold.** A scoped-to-unscoped rewrite can expand the namespace commitment with identical `hard` text. With both CPU aliases present, the smaller one binds. Duplicate legacy copies of one quota also make choosing the first path unsafe. [pipeline.py](head/cmapi/src/cmapi/core/pipeline.py#L417), [ledger](head/cmapi/src/cmapi/core/capacity_ledger.py#L20) | Recount the managed quota set on each side, normalize aliases, compare duplicate versions conservatively, and account for an increase of the unscoped binding limit. The scope test charges 0 extra CPU and 16 GiB of memory. The alias and duplicate tests each charge 7 CPUs and require approval at 700%. See `test_capacity_accounts_for_scope_and_the_binding_quota`, `test_cpu_alias_counts_for_usage_and_policy`, and `test_a_legacy_copy_cannot_hide_the_smaller_baseline`. |
| **High** | **A partial Git folder breaks the empty-create assumption.** Create checks for the Namespace document. A folder containing a ResourceQuota alone can reach the create renderer and its tier-relative exposure rule. The full capacity charge on create does not provide the missing update approval. [pipeline.py](head/cmapi/src/cmapi/core/pipeline.py#L282) | Refuse a create that encounters quota manifests with the existing `409 namespace-exists`. This avoids assigning update semantics to a create or silently replacing the existing quota. `test_a_create_requires_a_new_quota_folder` verifies the refusal. |
| **Medium** | **A first quota can require an unintended live-usage approval.** With no ResourceQuota in Git, head calls the usage source. An outage then adds a platform slot for onboarding. This predates #710. The 100% fact is correct. [pipeline.py](head/cmapi/src/cmapi/core/pipeline.py#L427) | Skip the live read when setting the first quota. Preserve the full capacity charge, the 100% fact and any independently applicable approval rules. `test_onboarding_never_queries_usage_for_the_first_quota` uses an unavailable source, and `test_first_quota_percentage` checks the percentage separately. |
| **Medium** | **A quota-less adopted custom namespace cannot receive a metadata-only update.** Planning attempts to render custom without the required sizable keys. D9 records a missing quota as a supported state. [pipeline.py](head/cmapi/src/cmapi/core/pipeline.py#L376), [renderer](head/cmapi/src/cmapi/core/render/manifests.py#L221) | Use the same preservation decision in planning and rendering. The custom namespace keeps its limits and absence of quota until a quota request supplies sizes. `test_custom_namespace_without_a_quota_keeps_its_limits_until_a_quota_is_requested` checks both operations. |
| **Medium** | **A move off a retired tier fails before comparison.** The prior-tier lookup requires a currently offered tier, even though the comparison explicitly handles an unknown old tier. [pipeline.py](head/cmapi/src/cmapi/core/pipeline.py#L359) | Require the destination of an ordinary move to resolve, and use the available old definition only to identify preserved custom values. `test_move_from_a_retired_tier_uses_its_git_quota` checks an upward move and 700% from Git. |
| **High** | **Adding a sizable key to an existing quota can omit the peak-based approval.** The live read succeeds and the view has a planned-to-peak ratio, but the approval fact requires an old value for that key. This is distinct from installing a first quota. [usage.py](head/cmapi/src/cmapi/capacity/usage.py#L350) | Preserve the absent prior quota as null in the view and use zero for deciding whether the planned amount rose. `test_new_key_in_an_existing_quota_is_compared_to_live_peak` checks that 8 planned CPUs over a peak of 2 produce a ratio of 4 and a slot. |

## Disposition of the requested paths

| Path | Deciding observation |
|---|---|
| Create | A clean small create checks 8 CPUs and 16 GiB and makes no usage read. Create-specific exposure uses the tier. A quota-only partial folder requires the fix above. |
| Tier move, metadata and explicit quota | Head passes the parameterized 1→8 metadata, 1→16 tier move and 1→6 custom override checks. They charge 7, 15 and 5 CPUs and report 700%, 1500% and 500%. A missing tier label also produces `same` and 700% on the default-tier re-render. |
| LimitRange | A limits-only change on custom can still re-render a quota resource. `test_limitrange_only_update_counts_drift_in_a_quota_key` checks the actual rendered NodePort value, network approval and live read. |
| Several quotas and missing own quota | With several foreign quotas, metadata leaves hard values alone and the plan sizes zero. Explicit quota, tier and limits changes receive `409 several-resource-quotas`. With an own quota plus a sibling, object-level policy and namespace-wide capacity both matter. The several-quota and scope tests exercise these branches. A separate [planner probe](r1-work/probes/test_adoption_policy.py) confirmed that a lone foreign quota retains the same parsed manifest on metadata and becomes the selected quota on an explicit move. The corresponding database-backed cases are in [test_multidoc_quota_250.py](head/cmapi/tests/service/test_multidoc_quota_250.py#L359). |
| First quota and adoption | Under the shipped dev rule, 100% alone adds zero slots. The supplemental policy probe sets the threshold to `> 50` and confirms one slot for the first quota. D9 holds foreign objects on metadata, and an explicit first quota is a full capacity charge. The outage-triggered approval and the quota-less custom metadata refusal are separate defects. |
| Decrease | Halving all sizable values yields −50%, checks (0 CPU, 0 memory), and adds no increase slot. A mixed change can still need capacity for the resource that rises. The percentage is the largest per-key percentage, so an unchanged sizable key can make it zero. The current [simulated backend](head/cmapi/src/cmapi/core/capacity_backend.py#L98) implements `reserve` as a no-op. The tests verify the check inputs and absence of a reservation call. Durable reservations belong to the future capacity component, as the [implementation status](head/docs/08-code-status.md#L61) records. |
| Usage gate | With an existing quota, a numeric change reads usage against Git. Equivalent quantities skip the read. The existing #707 pod-only drift test passed on the applied patch. The first-quota and newly added key exceptions are covered above. |
| Revert and expiry | Revert can increase a hard quota and failed the worker checks on head. The #699 timer calls `plan_expiry_delete` after grace. That planner emits only removals, and `test_expiry_delete_only_removes_files` compares its entire file map with the expected tombstones. It has no quota raise to size. [Expiry worker](head/cmapi/src/cmapi/jobs/expire_check.py#L196) |

## Test evidence

The same 22 reviewer cases ran in the requested service venv in each row. They instantiate the real planner and policies with fake Git, a registry double and a capacity spy. Worker cases replace the repositories and intercept submission, so they cover the actual worker decision without claiming to exercise the SQL transaction.

| Source under test | Passed | Failed | What distinguishes the run |
|---|---:|---:|---|
| Main `2992944` | 4 | 18 | Misses ordinary drift, no-tier facts and first-quota sizing as well as the independent findings. |
| PR head | 10 | 12 | Ordinary named-tier drift and the empty-baseline percentage are corrected. |
| Head with the named-tier catalog baseline restored | 6 | 16 | The capacity assertions for metadata, tier move and custom override fail. The decrease percentage also regresses. |
| Head with `old_hard or hard` restored only at comparison | 9 | 13 | The first quota still charges the full capacity, but the percentage falls to zero. |
| Head with catalog-relative network exposure | 8 | 14 | The no-tier load-balancer and limits-only NodePort cases both lose the exposure fact. |
| Fresh head with reviewer patch | **22** | **0** | All twelve head failures turn green and all ten controls remain green. |

Mutant counts include pre-existing head failures. The catalog mutant also masks the unrelated first-quota usage bug for a named tier. The deciding evidence is the individual assertion that changes relative to head. The PR's own seven cases all seed an existing quota, so they do not distinguish the empty-baseline fallback. The added first-quota case does.

The fresh patched copy also passed **51 service-venv cases** in one invocation covering the 22 reviewer cases, all of `test_usage_review_707.py`, and `test_usage_follows_the_change_to_the_stored_quota`. Both supplemental adoption and policy probes passed. In the reference venv, the full core suite on base, head and the freshly patched copy each finished with **816 passed, 115 skipped and one warning**. Go's default build cache was unwritable on the first run. The completed runs used a workspace-local `GOCACHE`. The full PostgreSQL API, persistence, lease and delivery paths remain unverified here.

The export has no TokenSave index. I read the supplied source directly. I generated the diff against head with `examples/` excluded, applied it with `patch -p1 -F0` to a new head copy, and compared that tree with the reviewed fix. They matched. The documentation citation check reported zero problems using the export's file list in place of a Git index.

## Backlog

The PR record already tracks the local reference app's catalog baseline as #713 and the live `quotaBelowRequested` input as #256. Neither is evidence that a DB-backed reservation or a below-current-use guard ran in this review.

## Five-line summary

1. Request changes. Head fixes ordinary catalog drift, but the revert worker still skips quota review.
2. Scoped quotas, aliases and duplicate manifests need a baseline consistent with the capacity ledger and approval rules.
3. A first quota is 100% and has no onboarding usage read. A quota-less custom namespace can retain its state on metadata changes.
4. All three mutants were distinguished. All 22 reviewer cases passed after the patch applied with zero fuzz.
5. Core passed on all three trees. PostgreSQL-backed lifecycle verification remains outstanding.
