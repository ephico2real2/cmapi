# Reviewer 2 (Opus 5.5, high) · cmapi PR #733

**Verdict: request changes, with a narrower patch than reviewer 1's.** One High finding is confirmed (the write preconditions at
delivery). The second High finding is refuted under D10, which binds this review. Of the six Medium findings, two are confirmed
and fixed (scoped quota bounds, quota keeping), one is confirmed in part and fixed in part (the tracking method). Three go to
the Backlog, because they predate the PR, are design extensions, or have no exploit beyond a writer of the same database row.
Reviewer 1 missed a PR-introduced CI failure, which is fixed here.

- Patch: [`r2-outputs/final.diff`](r2-outputs/final.diff). It changes 14 files, and is 691 lines, against reviewer 1's 17 files
  and 1,214 lines. It applies to a fresh copy of `head/` with `patch -p1 -F0`, and the result is byte-identical to `r2-work/`.
- All runs are on **PostgreSQL 16 at `127.0.0.1:55432`, database `cmapi_r2_733`**. No cluster was used, so no result comes from a
  live API server.

## The coordinator's correction, applied

D10: "Auto-approval never covers an adoption unless a rule names it." Reviewer 1 worked from the brief's stricter wording
("Auto-approval never applies") and said so in its report. The following parts of `fix.diff` rest only on that wording, and
**all of them are cut**:

| Cut from reviewer 1's patch | Why |
|---|---|
| `approvals.py`: the hard-coded floor (1 of `approver-platform`, or 2 with findings) that overrides a site's rules | D10 makes these counts the defaults of "the shipped `approval-rules.yaml`". Head ships them as two thresholds in every instance's file (`examples/instances/nonprod` and `staging/approval-rules.yaml:58-65`, `prod:52-59`, `examples/config:53-60`, `reference_instance:60-67`). A floor in code overrides a site's explicitly written rule. |
| `approvals.py` `_auto`: no auto-approval for any adoption, and the removal of `_matches`'s "unless a policy names the plugin" | This contradicts D10's "unless a rule names it" directly. |
| `routers/requests.py`: `who.kind != "user"` refused at `:approve` for an adoption | Neither the design nor docs/14 says this. docs/14 "Step 5: who can approve" lists five checks, and none is the principal's kind. docs/14 also defines `cmapi-approval-relay`, a role that "goes on a client and not on a person" for channel integrations (docs/14 line 31; docs/11 line 34). The rule would break that relay for adoptions. This is a question for the coordinator (Q1). |
| `docs/02` and `docs/18`: "every adoption requires human approval" and "Automatic approval is disabled for adoption" | These restate the cut rule. Head's text already matches D10. |
| `tests/core/test_adoption_review.py::test_platform_floor_survives_an_instance_policy`, `test_adoption_seat_requires_a_person...` | These are the tests of the cut rules. |

## Verdict on each finding

Each verdict has a test. Each failing test fails on head and passes with `final.diff`. The tests live in
`cmapi/tests/core/test_adoption_review_733.py` (7 tests) and `cmapi/tests/service/test_adoption_delivery_733.py` (6 tests, using
fakes, collected by the service suite). The before/after runs load the same test file from a neutral folder, with each tree's
`src` first on `PYTHONPATH`.

### High 1: the per-object write preconditions at delivery (UID and resourceVersion). **Confirmed. Fixed, narrowed.**

**Facts on head:**
- `jobs/apply.py:100-114` runs D16's read (`adoption_staleness`) and then `mark_apply_started` (its own DB transaction) and
  `jobs.fence()`. Only then does it send `d.apply_folder(files)`. The comment says "no gap is left for a change", but there is
  one.
- `KubeClient.apply` (`core/clients/kube.py:328-335`) sends a forced server-side apply (`force=true`). The manifests carry
  neither `uid` nor `resourceVersion`, so the write is unconditional.
- A resumed apply (`started`) skips D16 altogether (`if adopting is not None and not started`).
- After the merge, `jobs/watch_sync.py:95-101` checks the uid only of a Namespace that is present **and** unmanaged. A Namespace
  that is gone is created again from Git. A replacement that carries `cmapi.net/managed: "true"` is written to without a uid
  check.

**Kubernetes primary sources (release-1.31, fetched 2026-11-26):**
- `staging/src/k8s.io/apiserver/pkg/endpoints/handlers/patch.go:565-570`: an apply whose object has a uid, with no current
  object, gives `errors.NewConflict(... "uid mismatch: the provided object specified uid %s, and no existing object was found")`.
  `test/integration/apiserver/apply/apply_test.go:707-737`, `TestCreateOnApplyFailsWithUID`, asserts `IsConflict`.
- `staging/src/k8s.io/apimachinery/pkg/api/validation/objectmeta.go:254`: `ValidateImmutableField(newMeta.GetUID(),
  oldMeta.GetUID(), fldPath.Child("uid"))`. It is called from `rest/update.go` `validateCommonFields` ("Ensure some common fields,
  like UID, are validated for all resources"), and the refusal is a 422 Invalid.
- `staging/src/k8s.io/apiserver/pkg/registry/generic/registry/store.go:713-714`: `if newResourceVersion != existingResourceVersion
  { return ... apierrors.NewConflict(qualifiedResource, name, fmt.Errorf(OptimisticLockErrorMsg)) }`.
- **Inferred, not measured:** that the applied configuration's `metadata.resourceVersion` reaches `store.Update` as
  `newResourceVersion`. `structuredmerge.go` `Apply` merges the patch object over the live object, and `stripmeta.go:39-52` removes
  `metadata.uid` and `metadata.resourceVersion` only from the *managed-fields set*, not from the object. The SSA page says only
  "`resourceVersion` doesn't have to be specified" (`server-side-apply.md:393`). A live API server was not used: proving the 409
  on kind is listed as Q4.

**Tests:**
- `test_each_adopted_object_is_written_with_the_uid_and_resource_version_of_the_plan`. Head sends
  `('Namespace', None, None)`.
- `test_an_object_changed_between_the_last_read_and_the_write_is_refused_and_nothing_is_written`. The quota changes at
  `jobs.fence()`, after the read. Head writes it.
- `test_a_resumed_apply_skips_what_cmapi_wrote_and_refuses_a_replacement`.
- `test_a_resumed_apply_never_writes_over_a_change_made_by_someone_else`.
- `test_after_the_merge_a_namespace_that_is_gone_is_not_made_again`. Head applies both objects.
- `test_after_the_merge_a_managed_replacement_namespace_is_refused_too`. Head applies both objects.

The two "resumed" tests fail on head with `AttributeError`, because the helper is new. The behavior they guard is shown failing on
head by the third and fifth tests.

**What is kept from reviewer 1, simplified:**
- `delivery.adoption_writes` (40 lines). It reads the inventory again, refuses an object that the plan holds no uid or
  resourceVersion for, and stamps both on each manifest.
- On a resume, it skips an object whose cleaned live copy equals this request's manifest. The live copy has D3a's left-out
  Namespace keys removed. The object's live resourceVersion then stands for the plan's in `stale()`. Without the skip, the
  apply-mode poll loop (`_wait` → retry) and `watch_sync` after the merge would 409 on cmapi's own earlier write.
- It is used by both `apply.py` and `watch_sync.py`.
- A 409 on an adoption is reported as `adoption-plan-stale`.
- `takeover_allowed` is removed. `stale()` compares the uid of every object, and the preconditions enforce it.

**What is cut from reviewer 1's version:**
- `adoption_base`/`request_plan_hash` inside the write path (that is Medium 5, cut).
- The `file` field on key decisions and the child-object skip decisions (Medium 6, cut).
- The `stale()` additions: the `takeover_allowed` pre-check, the `deletionTimestamp` check and the "incomplete identity" check.
  A deleting Namespace already has a new resourceVersion. An empty identity is refused in `adoption_writes`.
- `Problem` added to `watch_sync`'s broad `except`. That would turn any `Problem` of a non-adoption delivery into a silent wait. A
  `Problem` from `live_objects` is converted to `ClusterUnreachable` at the one call site instead.

**Residual risk, stated:** the resume comparison is exact equality. If a real API server adds or normalises a field on write that
the read-time snapshot lacked, an apply-mode adoption fails closed (`sync_failed`, `adoption-plan-stale`). It never writes over a
change. Only a kind run shows whether this happens (Q4). Argo CD mode keeps D16's documented interval between the last read and
the sync.

### High 2: required people can be missing. **Refuted under D10.** Nothing changed.

**Facts on head:**
- `ApprovalRules.decide` (`core/approvals.py:180-217`) applies the shipped thresholds `plugin == "adoption"` (+1
  `approver-platform`) and `plugin == "adoption" and findingCount > 0` (+1).
- Any threshold that adds a slot sets `added`, and `_auto` then returns `rules-added-approvers`. The `warnings` guard also blocks
  auto-approval when the plan has findings.
- `_matches` lets a policy cover an adoption only when `match.plugin == "adoption"`. With no slot from any rule, head still adds
  one of `defaults.group`.

**Reviewer 1's three cases:**
- An environment slot of another group satisfies the adoption: this happens only when a site deletes the shipped thresholds.
- An explicit policy auto-approves a clean plan: this needs a policy that names `adoption`, which is D10's "unless a rule names
  it".
- A service principal approves: this is not a rule of the design (see the cut list, and Q1).

**Tests**, all passing on head and with the patch. They characterise D10, and do not demonstrate a defect:
- `test_d10_a_policy_that_does_not_name_adoption_never_covers_one`
- `test_d10_with_the_shipped_rules_a_policy_naming_adoption_still_needs_the_platform_approvers` (1, then 2 with findings, never
  automatic)
- `test_d10_a_site_rule_that_names_adoption_may_auto_approve_it`

Reviewer 1's `test_platform_floor_survives_an_instance_policy` fails on head (`'auto:everything' is None`, then
`{'local': 1} == {'local': 1, 'approver-platform': 2}`). Its rules (`test_adoption_26.RULES`) have no adoption threshold and a
policy that names the plugin, so the test asserts the stricter wording, not D10.

### Medium 1: incorrect candidates. **Confirmed in part.** Tracking fixed; the rest moved to the Backlog.

- **(c) `annotation+label` treated as label tracking. Confirmed and fixed.** `AdoptionSettings.parse` set
  `label_tracking = tracking != "annotation"`. D1 step 3 says the label counts "only when the hub's Argo CD uses label tracking
  (`application.resourceTrackingMethod: label`)". Argo CD, `docs/user-guide/resource_tracking.md:8` (fetched 2026-11-26):
  "`annotation+label` - Argo CD uses the `app.kubernetes.io/instance` label but only for informational purposes. The label is
  not used for tracking purposes". The fix is one token (`== "label"`). docs/18's row now says so. Test:
  `test_annotation_plus_label_tracks_by_the_annotation_only` (head: `'skipped' == 'candidate'`).
- **(d) In label mode, cmapi's annotation can hide a foreign label. Backlog, Low.** It needs a cmapi tracking annotation on a
  namespace that cmapi does not manage, on a hub that tracks by label.
- **(a) The submit path uses `bool(prev_files)` and the list uses `list_folder`. Backlog, Low.** It is real: a folder that holds
  only a non-YAML file is "managed" in the list and a candidate at `:adopt`. The effect is that the adoption's YAML is written
  beside a README. Nothing on the cluster changes, and the fix changes the plan's `base_sha` source.
- **(b) A truncated listing. Refuted as a defect.** Head's choice is deliberate and commented ("too large to list: the label
  decides here, and the plan reads the one folder again"). `:adopt` checks the one folder again. Reviewer 1's fix makes
  `GET .../candidates` answer 502 on every large repository, which is a regression.

### Medium 2: environment authorization on replay. **Refuted as PR-introduced.** Backlog.

The adoption route checks the replay before the planner's environment check. Base's `create_namespace`
(`plugins/namespaces/router.py:276`) and the other write routes have the same order, and the `_replay` helpers are byte-identical
on base and head. What is replayed is the caller's own earlier answer, under the caller's own key. Any change belongs to all write
routes together: Backlog B-2.

### Medium 3: the approved hash omits the policy snapshot. **Not a defect with an exploit. Cut.** Backlog with a question.

D6a, step 1 says the snapshot is stored "in the request's plan, which the plan hash covers". Head's `plan_hash` covers the files
only. The snapshot is bound by `snapshotHash` in the same JSON, which `adoption_base` checks. A PR file cannot supply the base:
`pr_checks.py` passes `adoption_base(row)`. Reviewer 1's attack needs someone who rewrites `plan.adoption.snapshot` and
`snapshotHash` in the database row. That same writer can rewrite `change_requests.plan_hash` in the same row, so binding the
digest adds no guarantee.

Reviewer 1's change also alters the meaning of `plan_hash` for adoption rows in five places (`Plan.hash`, `submit`, `rendered`,
`pr_checks`, `adoption_base`) and in the commit trailer. This review rejects that cost. The design text and the code differ, so
it is Q2: amend D6a's sentence to "which `snapshotHash` covers", or bind it.

### Medium 4: skip decisions keep or drop the wrong keys. **Refuted for the Namespace.** The children part goes to the Backlog.

D3a gives its reason for leaving a key out: managers "that Argo CD's migration does not take over". Argo CD,
`docs/user-guide/sync-options.md:399-405` (fetched 2026-11-26), says the migration checks "if the specified field manager exists in
the resource's `managedFields` with `operation: Update`", transfers its fields to `argocd-controller`, and removes that one entry.
Only the migration manager is taken over. A key that any other manager owns stays on the cluster when Git leaves it out, because
server-side apply removes only fields that the applier owned. Head keeps exactly the keys of the configured migration manager, and
keeps every key when the read gave no `managedFields`.

Reviewer 1's hard-coded `server_managers` allowlist is stricter than D3a's stated reason. It would change the shipped behaviour
proven by `test_d3a_leaves_out_a_skipped_key_only_when_no_client_side_apply_wrote_it`, so it is cut.

Skip decisions on ResourceQuotas and LimitRanges are a design gap of D3, which is written for "the object". The default prefixes
are Namespace keys, and the common child case (`kubectl.kubernetes.io/last-applied-configuration` written by `kubectl apply`) is
kept on head, which is the result D3a requires. Backlog B-4.

### Medium 5: scoped quotas lose approval facts. **Confirmed. Fixed** by reviewer 1's one-line move.

- `object_findings` (`core/adoption.py:459-462`) runs `continue` for a scoped quota before `_bound`.
- D5: "Each value outside the custom tier's bounds ... is a finding `beyond-custom-bounds` ... and the request's facts carry
  `beyondTier`". D17 keeps a scoped quota out of the namespace's *figures* only.
- The design's own test plan (section 5) gives the test namespace "a scoped quota above the custom bound for `rnd`" and expects
  `beyond-custom-bounds`. The PR's service test docstring (`tests/service/test_adoption_26.py:5`) describes "a ResourceQuota with a
  scope and a value beyond the" bound, yet expects 2 approvers.
- With the fix, the shipped `beyondTier` threshold adds the third `approver-platform` seat. The service test now expects
  `count: 3`, asserts `beyond-custom-bounds`, and approves with three people (`approve_all`).
- Test: `test_a_scoped_quota_beyond_the_custom_bounds_is_a_finding_and_a_fact` (head: `KeyError: 'requests.cpu'`).

### Medium 6: a metadata-only update re-renders adopted quota objects. **Confirmed. Fixed, simplified.**

- **No quota.** On head, a label change of an adopted namespace that has no ResourceQuota renders the custom tier and fails with
  422 `custom-quota-required` ("A custom tier needs every sizable key"), measured by the renderer test below; the pipeline
  calls `quota_for` with the same empty values on that path. D16 says "A later quota request adds the
  object"; D9 says "Any other request, a change of a label for example, leaves every object unchanged"; and section 5 says "an
  update of a label passes".
  - Fix: `quotas_kept(..., existing_custom=)` keeps none for an existing custom namespace on a change that sends no quota, tier or
    limits.
  - The pipeline passes its existing `custom_before`, moved up 30 lines. The renderer passes `old_ns is not None and tier.custom`.
  - Reviewer 1's renderer expression repeated two conditions that `quotas_kept` already checks.
  - Test: `test_a_label_change_of_an_adopted_namespace_with_no_quota_adds_none`.
- **An imported tier hash.** A namespace that cmapi once managed and then adopts again keeps the `cmapi.net/tier-hash` of its
  `<ns>-quota`, so `rendered_quota` called it cmapi's rendering.
  - Fix (reviewer 1's): an object with D4's `Prune=confirm` is not a rendering. `TierCatalog.render` writes no sync-options on its
    quota (`core/tiers.py:757-763`), so the rule cannot misclassify cmapi's own quota.
  - Test: `test_a_label_change_keeps_an_adopted_quota_that_already_carried_a_tier_hash`.

## What reviewer 1 missed (in the changed lines)

**M-1 (CI failure introduced by the PR). Fixed.**
- `jobs/pr_checks.py:92` reads `row.plugin` for every request, so `tests/service/test_delivery_states_review.py::
  test_pr_checks_uses_the_worker_contexts_validator_slots` (#708) fails on head on PostgreSQL:
  `AttributeError: 'types.SimpleNamespace' object has no attribute 'plugin'`.
- The test's fake row lacks the column that every real row has. The fix adds `plugin="namespaces"` to that file's `row()`. Code
  that a real row never reaches is not changed.
- Before: head, 1 failed and 83 passed (`r2-outputs/head-service.log`). After: see the runs.

```python
def row(status="pr_open"):
    return NS(status=status, cluster_id="CRC", namespace="demo", request_id="req-1", plugin="namespaces", action="create",
              plan={"files": {REL: "approved"}, "prev": {}}, merge_sha=None,
              pr={"number": 1, "url": "", "branch": "cmapi/CRC/req-1", "head": HEAD})
```

**M-2 (a managed replacement after the merge). Fixed by High 1's change.** It is tested by
`test_after_the_merge_a_managed_replacement_namespace_is_refused_too`. Reviewer 1 named the absent case and the managed case, but
tested only the absent one.

**M-3 (Low, Backlog).** The `:adopt` docstring, which is rendered into `contract/openapi.json`, says "no automatic approval covers
it". With the shipped rules that is true. Under D10, a site rule can cover an adoption. The wording is "no automatic approval
covers it unless a policy names the adoption plugin", and changing it means regenerating the OpenAPI document.

**A test adapted, not a finding.** `tests/service/test_review_255_apply.py::test_a_file_rename_does_not_prune_the_reapplied_quota`
runs a slice of `watch_sync.py`'s source text, cut out by `source.index("n = d.apply_folder(files)")`. The patch renames the
argument to `writes`, so the test's anchor and its `exec` namespace follow (`"writes": files`). The first run of `r2-work` caught
this (1 failed, 89 passed), and the run after the change passed.

## Backlog (separate; none of these blocks this PR)

| # | Item | Origin |
|---|---|---|
| B-1 | `plan_adoption` decides `in_git` from top-level YAML only (`_read_folder`), and the list uses `list_folder`. Use `list_folder` in the planner too, and check folder presence again in `push_branch`. Reviewer 1's code in `fix.diff`, `core/pipeline.py` and `jobs/push_branch.py` hunks, is a starting point. | PR, Low |
| B-2 | The idempotency replay is answered before the environment grant on every write route (base `create_namespace:276`, and so on). Check the grant first, for all routes together. | Predates the PR |
| B-3 | D6a's "which the plan hash covers" against `snapshotHash` (Q2). | Design text |
| B-4 | D3/D3a skip decisions on ResourceQuota and LimitRange keys, with the finding naming the child file. | Design extension |
| B-5 | `tracked_by` in label mode: the label should decide even when cmapi's annotation is present. | PR, Low |
| B-6 | The `:adopt` docstring against D10 (M-3), with the OpenAPI regeneration. | PR, Low |
| B-7 | Portal copy shows the literal `"true"` for a configured opt-in value (reviewer 1's Low). | PR, Low |
| B-8 | head's fallback approver (no slot from any rule) sets `added`, so a policy that names adoption cannot cover it in that case. This is stricter than D10's "unless a rule names it", so it is a question, not a defect. | PR, Low |

## Questions for the coordinator

1. **Q1.** Should an adoption's approval require a person's token (`who.kind == "user"`)? It is not in D10 or docs/14, and docs/14
   defines `cmapi-approval-relay` for clients that relay approvals. My recommendation is no, unless the owner rules it.
2. **Q2.** D6a step 1 says the plan hash covers the snapshot, but head binds it with `snapshotHash`. Should D6a's text be amended
   (recommended, since there is no gain against a writer of the same row), or should the snapshot be bound into `plan_hash`?
3. **Q3.** B-8: with no slot from any rule, should a policy that names `adoption` be able to cover it? This is D10's literal
   reading, and head is stricter.
4. **Q4.** Before the CRC walk, one kind run of an apply-mode adoption would measure two things: the 409 for a stale
   `resourceVersion` in an apply patch, and the resume equality after a real server-side apply. Both are inferred from the
   source here and not measured.

## Runs

| Run | Tree | Result |
|---|---|---|
| Service: `test_adoption_26`, `test_multidoc_quota_250`, `test_delivery_states_review`, `test_delivery_states_db_review`, `test_review_255_apply`, `test_watch_review_455` (PostgreSQL) | head | 1 failed (M-1), 83 passed |
| The same six files and `test_adoption_delivery_733` (PostgreSQL) | `r2-work` | first run 1 failed (the source-slice test, adapted), 89 passed; after the change see the next row |
| The same seven files (PostgreSQL) | fresh head copy + `final.diff` | **90 passed** |
| `tests/core` (`venv-ref`) | `r2-work` | 877 passed, 115 skipped |
| `tests/core` (`venv-ref`) | fresh head copy + `final.diff` | **877 passed, 115 skipped** (head: 870 passed, 115 skipped; +7 new tests) |
| `test_adoption_review_733.py` (core) | head / patched | 4 failed, 3 passed (the 3 D10 characterisations) / 7 passed |
| `test_adoption_delivery_733.py` (service fakes) | head / patched | 6 failed / 6 passed |
| Reviewer 1's `test_adoption_review.py` | head | 9 failed. 2 of them test the cut D10-stricter rules, and 3 test cut Medium parts |
| Mutants on copies of the patched source (`r2-outputs/mutants/`) | patched | 7 of 7 killed: no preconditions (3 failed), skip keeps the plan's rv (1), resume always writes (1), an imported hash counted as a rendering (1), no-quota re-renders (1), scoped skips the bound (1), annotation+label tracks (1) |
| Patch check | fresh head copy | `patch -p1 -F0 --dry-run` then apply: clean; `diff -r` against `r2-work`: identical |

The portal was not changed, so `npm test` was not run. The whole service suite was not run; CI runs it.

## Who wrote what

Reviewer 2 (Opus 5.5 high) wrote `final.diff`. It contains reviewer 1's changes for Medium 5 (`object_findings`) and Medium 6
(`rendered_quota`), applied as written. Reviewer 1's `adoption_writes` design and its `quotas_kept` parameter are rewritten
here. Everything else in `final.diff` is new in this review.
