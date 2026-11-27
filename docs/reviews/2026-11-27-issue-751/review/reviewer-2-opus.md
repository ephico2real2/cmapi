# Reviewer 2 (Opus 5.5, high) · PR #752 · deliverer-agnostic delivery

Reviewer 2 did not write the PR. All service results below ran on **PostgreSQL 16.15 at 127.0.0.1:55432** (databases
`cmapi_r2_752`, `cmapi_r2_752_red`, `cmapi_r2_752_bl`), never SQLite. No cluster was used; no repository, GitHub or cluster
change was made. No command was refused by the permission system.

**Verdict: request changes, with `r2-outputs/final.diff` (one patch against head `5ab75c07`).** Four of Codex's five Highs
are real in some form; with the patch, the read cannot confirm a plan whose RoleBinding, ServiceAccount or prune policy is
missing, or whose Git main moved while it waited for a prune. Codex's 47 KB patch is narrowed. The read keeps the design's
watch cache (D2), adds no identity checks or pagination loop, and does not touch the chart. Each cut is explained below.

## 1. Verdict per finding

"Red" means the test fails on head and passes with `final.diff`. The tests are in `cmapi/tests/core/test_read_plan_751.py`
(core, reference venv) and `cmapi/tests/service/test_gitops_delivery_751.py` (PostgreSQL).

| # | Codex finding | Verdict | What the evidence shows | In `final.diff` |
|---|---|---|---|---|
| H1 | The read ignores the RoleBinding and ServiceAccount the renderer emits | **Confirmed, High, kept** | `core/render/manifests.py` writes `token-issuer-rolebinding.yaml` on every plan, plus `serviceaccounts.yaml` and `rolebindings.yaml` when requested. Head's `_ORDER` has three kinds and skips the rest. In gitops mode nothing else checks them; argocd checks them through `not_synced`, and apply mode writes them itself. Red, service: `test_gitops_a_missing_rolebinding_is_not_synced`. Head reports **synced** with the binding deleted. Red, core: `test_a_missing_rolebinding_or_serviceaccount_is_named_and_a_binding_must_grant_what_the_plan_grants` | ServiceAccount: present. RoleBinding: `roleRef` and `subjects`, the subjects in any order. Codex's "plan must hold the request's Namespace" check is cut: the renderer always writes `namespace.yaml`, so no plan reaches the read without it |
| H2a | A positive cache hit is taken as evidence when a direct read says the object is gone | **Refuted as a PR defect, Backlog B4** | D2 states "The read goes to the watch cache first, then to the reader directly, as before". Base did the same (`cache.get(...) or _direct(...)`). `WatchCache` drops an object on its DELETED event and on every relist; a stale hit needs a broken watch. Codex's fix removes the cache from every mode, so it changes argocd and apply behaviour and adds a GET per object per poll. That is the owner's design choice to reopen, not a narrow fix | No |
| H2b | A response of another kind, name or namespace could confirm | **Refuted** | A named GET of `/api/v1/namespaces/<ns>/resourcequotas/<name>` returns that object or 404, and the cache is keyed by kind, namespace and name. No Kubernetes path returns another object, so the check guards against nothing | No |
| H2c | A planned object being deleted is accepted | **Confirmed, kept (one branch)** | "the Kubernetes API marks the object for deletion by populating `.metadata.deletionTimestamp` … The target object remains in a terminating state" (Kubernetes, Finalizers, <https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/>, read 2026-11-27). Red, core: `test_a_planned_object_marked_for_deletion_is_not_the_plans` | Yes |
| H3a | The `argocd.argoproj.io/*` wildcard hides cmapi's own `Prune=confirm` annotation | **Confirmed, High, kept** | `metadata-keys.yaml` `liveOnlyKeys` holds `argocd.argoproj.io/*`, and the renderer writes `argocd.argoproj.io/sync-options` on the Namespace. Red, core: `test_the_prune_policy_is_compared_though_argo_cds_tracking_keys_are_left_out` | That one key is exempt from the skip rules |
| H3b | An adoption skip prefix covering `cmapi.net/` hides a management label | **Refuted for this PR, Backlog B3** | It needs an operator to configure a skip prefix over cmapi's own keys, which would also break adoption. That is a missing check in the configuration, which predates the PR. Codex's `classify` hook is cut | No |
| H4 | Chart: per-cluster override, a string `"no"` acknowledgement, an invalid identity | **Measured; predates the PR, Backlog B2** | On head, `--set argocd.acknowledgeUncontainedController=no` also renders (exit 0), and the gitops regex is a copy of the argocd one. The same per-cluster gap exists for argocd and apply overrides. The hub's ValidatingAdmissionPolicy cannot contain a *remote* cluster's deliverer, so Codex's "bind the gitops writer on the hub whenever any cluster selects gitops" needs an owner decision. A string acknowledgement still prints the NOTES warning | No (B2 has the fix) |
| H5 | `awaiting_prune` stops re-checking Git main and has no deadline | **Confirmed, High, kept, with a correction to Codex's patch** | Red, service: `test_gitops_main_changed_while_waiting_for_a_prune_is_never_synced`. On head, with `main` changed and the leftover removed, the request is **synced**: a false synced. Red, service: `test_gitops_a_difference_other_than_a_removal_ends_a_prune_wait_at_sync_timeout`. On head, drift in `awaiting_prune` waits for ever, and that state has no `:retry` or `:revert` | `_prune_change` reads Git main first. A changed folder moves the request to `sync_failed`. A difference other than a removal is bounded by `syncTimeout`, through `_cannot_read`, then `sync_failed`. Codex instead failed at once on any such difference, which would turn one 429 or 500 read into `sync_failed` (§3) |
| M1 | Removals use `get` where CRC's reader has only `list` | **Confirmed, raised to High-impact Medium, kept** | `deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml` and `deploy/kind-import/reader.yaml` grant `list` only on serviceaccounts and rolebindings ("list only, as the code never gets or watches them"). Head's removal read is a GET, so on CRC **apply mode** too, any change that removes a ServiceAccount or RoleBinding ends `sync_failed`. The PR's `FakeKube` allowed the GET. Made honest, it turns red on head: `test_gitops_a_leftover_removed_object_waits_in_awaiting_prune_then_synced_when_gone` and `test_gitops_a_retried_change_with_only_removals_left_waits_in_awaiting_prune` | `_live` lists the namespace for those two kinds, with one unpaged list and no continuation loop. `FakeKube.get_object` refuses SA and RB, as the reader does |
| M2a | LimitRange defaulting is applied to the response | **Refuted** | "static defaults also apply when an object is read from storage (i.e. GET operations)" (API conventions, Defaulting, <https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md>). A live Container item without its defaults cannot be served, so defaulting both sides is a no-op on real data. Codex's version also needed a `FakeKube` change | No |
| M2b | Sub-milli rounding | **Confirmed, kept** | `SetDefaults_ResourceList`: "We round up resource values to milli scale … `val.RoundUp(milliScale)`" (kubernetes v1.31.0 `pkg/apis/core/v1/defaults.go`, fetched 2026-11-27). `SetObjectDefaults_LimitRange` applies it to all five maps, and `SetObjectDefaults_ResourceQuota` to `spec.hard`. `tiers._QTY` accepts `100u`, so such a plan never confirmed. The quota half predates the PR; the same line fixes both. Red, core: `test_a_sub_milli_amount_matches_the_api_servers_rounding_and_no_other[QUOTA, CPU]`, with `2m` as the negative control | `_stored()` quantizes both sides to 0.001 with ROUND_UP |
| M3 | Quota `scopeSelector` with an empty `values` | **Confirmed, kept** | The `values` field of a scope requirement is `omitempty` (kubernetes/api v0.31.0 `core/v1/types.go`). Red, core: `test_a_scope_selector_matches_the_form_the_api_server_returns_and_no_other`, with the operator change as the negative control | Compares the requirements |
| M4 | The operator notice is truncated | **Confirmed, kept** | Red, service: `test_gitops_the_prune_notice_keeps_every_name_and_the_operators_action`. On head, 30 names cut the note before "Remove them". `request_events.note` is `Text` | The `[:500]` cut is dropped |
| M5 | An invalid Flux name template raises | **Confirmed, kept, fixed at start** | `deliverer_signal` is called inside `watch_sync`'s `try`, but `str.format`'s KeyError is not among the caught types, so the job errors, its attempts are spent and the request never reaches its timeout. Codex caught it at run time. `final.diff` refuses the template at start, as an unknown mode is refused, for both templates. Red, service: `test_an_unfillable_deliverer_name_template_stops_the_start` | `DeliveryConfig.__post_init__` |
| — | Codex's change of `waited > timeout` to `>=` | **Cut** | It changes every mode's timeout boundary, and no finding needs it | No |

**Case 2 lock, on PostgreSQL (Codex could not reach the database).** `test_gitops_a_second_request_waits_for_the_first_to_be_confirmed`
(409 `change-pending` while `merged` and while `sync_failed`) passed on head and on the fix. The new
`test_gitops_a_change_waiting_for_a_prune_still_holds_the_namespace` passed on head too, as a verification. It checks a
409 `change-pending` naming the request while it is `awaiting_prune`, and that `pg_indexes.indexdef` of
`uq_cr_open_namespace` lists `'merged'`, `'awaiting_prune'` and `'sync_failed'`. The retraction of case 2 stands.

## 2. What `final.diff` changes (38 KB with context; about 21 KB of changed lines, half of them tests)

- `core/plan_read.py`:
  - all five rendered kinds are read, with `_grant()` for a RoleBinding;
  - a `deletionTimestamp` branch;
  - the sync-options exemption in `skipped()`;
  - `_stored()` for milli rounding;
  - `_scope_requirements()`;
  - the summary adds ", as do N ServiceAccount(s) and N RoleBinding(s)" only when there are any, so existing note
    assertions hold.
- `core/sync.py`: name templates are checked at start.
- `jobs/watch_sync.py`:
  - `_live` lists ServiceAccounts and RoleBindings;
  - the notice is kept whole;
  - `_prune_change` reads main and bounds a difference other than a removal;
  - `_cannot_read` gains a `failing=` wording parameter, and its default text is unchanged.
- Tests:
  - `conftest.py`: `FakeKube` refuses a GET of ServiceAccounts and RoleBindings, as the reader does;
  - 6 core tests and 6 service tests;
  - two of the PR's expectations are updated: the summary string, and the RoleBinding in "nothing applied".
- Docs: docs/01 §Sync, docs/02 "What the read compares" (it said "ServiceAccounts and RoleBindings … are not compared"),
  docs/18 (template check), and the design record's D2 and D5, with the sources quoted.
- Not changed: the contract (no model change), the chart, `examples/` (a symlink to `cmapi/src`).

Who wrote what: reviewer 2 (Opus 5.5) wrote `final.diff` and every test in it. It reuses three ideas from Codex's patch:
the sync-options exemption, the main recheck and ROUND_UP at milli scale. The comparison of scope requirements is also
Codex's design.

## 3. What Codex missed

1. **A defect in its own patch: a passing error fails a prune wait at once.** `fix.diff`'s `_prune_change` moves to
   `sync_failed` on any difference that is not a removal. An `Unreadable` from a 429, a 500 or a `BadResponse` is such a
   difference, so a request that waited correctly fails on one bad poll. `final.diff` bounds it by `syncTimeout`. The test is
   `test_gitops_a_difference_other_than_a_removal_ends_a_prune_wait_at_sync_timeout`. Its first half asserts the request is
   still `awaiting_prune` after the drift poll. Run on a copy of Codex's tested tree (`r1-outputs/fixed`), on PostgreSQL,
   it fails: `'sync_failed' == 'awaiting_prune'` after the first poll (`r2-outputs/logs/codex-patch-drift.log`).
2. **The test double hid the RBAC failure.** `FakeKube.get_object` answered for every kind. With the reader's real grant,
   two of the PR's own tests are red on head. Codex found the `get` problem with mocks but left `FakeKube` lenient, so the
   PostgreSQL suite would not catch a regression. Fixed in `conftest.py`.
3. **M1 is wider than gitops.** The removal read is shared by every mode. On CRC, the deployment target, `apply` mode also
   ends `sync_failed` for a change that removes a ServiceAccount or RoleBinding. Codex rated it Medium; it breaks the CRC
   flow.
4. **Codex's cache removal changes argocd and apply.** It is outside a narrow fix, and against D2 as written. Moved to the
   Backlog for the owner (B4).
5. **Codex's chart fix binds a remote cluster's deliverer into the hub's policy.** That policy can only contain writes to the
   hub's API server. B2 records it as an owner decision instead of a fix.
6. **Codex's "Namespace must be in the plan" and identity checks have no reachable input** (H1, H2b). They are cut as
   over-build.

## 4. Backlog (predates the PR or needs an owner decision)

`r2-outputs/backlog/backlog.diff` applies with `patch -p1 -F0` over head plus `final.diff`; it was checked on the fresh
export. Each item has its test, red on head plus `final.diff` and green with the backlog patch:

| # | Item | Severity | Fix and test |
|---|---|---|---|
| B1 | **CRC `apply` sibling-file prune.** Both apply paths prune only from the paths a plan removes. One ServiceAccount dropped from a `serviceaccounts.yaml` that stays is never deleted. Base reported a **false synced**; with #751's read the request ends `sync_failed` | Medium, recommend next | `jobs/watch_sync.py` and `jobs/apply.py` iterate the whole previous folder (`before = row.plan.get("prev")`). The existing `retained` set keeps what the plan still holds, and a document without `metadata.name` (a kustomization.yaml) is skipped. `test_review_255_apply.py` exec globals renamed. Test `test_backlog_apply_sibling_prune.py::test_apply_prunes_an_object_dropped_from_a_file_that_stays` (red: `delete` never called) |
| B2 | **Chart containment guards.** (a) An acknowledgement given as a string ("no") passes, for both `argocd.acknowledgeUncontainedController` and `delivery.gitops.acknowledgeUncontainedDeliverer`. (b) The identity regex accepts `invalid..name`. (c) A `clusters.<id>.delivery` override is not guarded | Low/Medium; (c) needs the owner: which cluster is the hub | `values.schema.json` declares both acknowledgements boolean and the modes as enums. The DNS-subdomain regex is applied to both identities. Codex's per-cluster guard is the candidate for (c). Tests in `test_backlog_chart_containment.py` (2, red on head plus final). `deploy/render-test.sh`: 0 failed |
| B3 | An adoption skip prefix may cover `cmapi.net/` | Low | `AdoptionSettings.parse` refuses such a prefix. Test `tests/core/test_backlog_skip_prefix_752.py` (3 red cases and 1 control) |
| B4 | **The confirming read trusts a stale watch-cache hit** (D2 is cache-first, so the owner decides) | Medium | In `_live`, drop the two cache lines, so every confirming read goes to the reader (`ServiceAccount` and `RoleBinding` keep their list). Test, with mocks as in Codex's `test_stale_cache_hit_cannot_supply_the_deciding_read`: `cache.get` returns the Namespace, `client.get_object` returns None, and `watch_sync` must not move to `synced` |
| B5 | A removed object of a kind with no reader path (for example a hand-added NetworkPolicy file, which the renderer removes) is `Unreadable` for ever | Low | It fails closed (`sync_failed`, never a false synced). Fix: say so in the difference ("cmapi cannot read <kind>") and document that the folder holds only rendered kinds |
| B6 | Codex's: the client maps any 404 to absence without reading the Status reason, and `qty` has no BinarySI int64 cap | Low | As in `r1-report.md` |

## 5. Runs (cluster: none; database: PostgreSQL 16.15)

| Run | Tree | Result | Log |
|---|---|---|---|
| Touched service files: `test_gitops_delivery_751`, `test_storage_limits_switch`, `test_second_pass`, `test_watch_sync_client_once_402`, `test_review_d_delivery`, `test_review_h_tools_migrate`, `test_review_255_apply`, `test_flow` | head | **134 passed** | `r2-outputs/logs/head-service.log` |
| The same 8 files | head + final | **140 passed** | `fixed-service.log` |
| New service tests on head, head's `FakeKube` | head | **6 failed**, 18 passed. Each claim fails for its own reason, including head reporting **synced** with the RoleBinding missing and with main changed; the lock test passes | `red-service-headfake.log` |
| The same, honest `FakeKube` | head | 9 failed, 15 passed (adds M1's two leftover tests) | `red-service.log` |
| `tests/core` (reference venv, GOCACHE in scratch) | head | 990 passed, 117 skipped | `head-core.log` |
| `tests/core` | head + final | **996 passed, 117 skipped** | `fixed-core.log` |
| New core tests on head | head | 7 failed (6 new, plus the summary string), 10 passed | `red-core.log` |
| `bash deploy/render-test.sh` | head + final | render cases failed: 0 (96 ok) | `fixed-render.log` |
| `bash deploy/tests/crc-scripts-test.sh` | head + final | crc script cases failed: 0 (291 ok) | `fixed-crc-scripts.log` |
| `final.diff` on a fresh `rsync` of head, `patch -p1 -F0` | verify | 10 files patched, no fuzz or rejects; `diff -rq` against the tested tree shows no difference; `test_read_plan_751` 17 passed; 4 service files 32 passed | `verify-*.log` |
| Backlog patch | head + final + backlog | 4 service passed, 21 core passed, render 0 failed; red without it: 3 failed (+3 core) | `backlog-*.log` |

No full service suite was run (rule of 2026-11-27); CI gates the rest.

## 6. Five-line summary

Request changes: head confirms **synced** with the token-issuer RoleBinding missing, and with Git main changed during a prune wait (both reproduced on PostgreSQL).
`final.diff` reads all five rendered kinds (SA/RB by list, the reader's real grant), compares cmapi's Prune=confirm, refuses Terminating objects, rounds to milli as the API server does, and bounds and rechecks `awaiting_prune`.
Cut from Codex: cache removal, identity checks, response-side defaulting, `>=`, the chart rewrite. Codex's prune patch would fail a request on one transient read error.
Case 2 lock holds on PostgreSQL in merged, awaiting_prune and sync_failed; core 996/117, service 140/140, render 0 and CRC scripts 0 failed; the patch applies cleanly to a fresh export and passes there.
Backlog with fixes and tests: CRC apply sibling prune (recommend next), chart guards (owner: hub identity), skip-prefix check, stale-cache read (owner: D2).
