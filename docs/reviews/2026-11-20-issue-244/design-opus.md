# #244: the bot opens the policy bundle's PR, and each plan records the bundle hash (design 1 of 2, Opus 5.5 high)

Written 2026-11-19 from `main` at `f87fd2d`, before reading the other design. Design only: no code was written or run.
Every `path:line` below was read in this session. Web sources are listed at the end with the date read.

## 1. What the code does today (facts the design rests on)

| # | Fact | Where |
|---|---|---|
| F1 | The bundle is rendered once, at process start, from the loaded configuration, and held in the context for plan time and the Policies tab | `cmapi/src/cmapi/core/context.py:92-95` |
| F2 | **No reload exists.** `admin:reload` is a permission with no route. A config change restarts the pods, because each pod template carries `checksum/config` | `docs/18-configuration.md:16`; `cmapi/src/cmapi/routers/admin.py` (no reload route); `deploy/helm/cmapi/templates/worker.yaml:18`; `deploy/manifests/components/cmapi/30-worker.yaml:28-30` |
| F3 | Each rendered policy carries `cmapi.net/policy-digest`: SHA-256 of canonical JSON (sorted keys, no spaces), without the digest annotation | `cmapi/src/cmapi/core/policygen.py:131-139` |
| F4 | The worker already watches every cluster's ValidatingPolicies as `LivePolicy(name, digest, generated, actions, ready)` through cmapi-reader, and the tab computes `expected/live/current/missing/differing` and the state `drift` | `cmapi/src/cmapi/core/clients/policyreports.py:66-73,114-121`; `cmapi/src/cmapi/plugins/policies/router.py:80-95,172-177`; `cmapi/src/cmapi/core/models.py:410` |
| F5 | `cmapi-tools policies render` owns only files with the mark `# Rendered by cmapi` and `index.json` under `env/<env>/` of the instance's own environments; it refuses to overwrite a hand-written file or write through a symlink | `cmapi/src/cmapi/tools/policies.py:21,29-42,74-88` |
| F6 | The delivery chain is namespace-shaped: every job derives the folder from `folder(cluster_id, namespace)` = `clusters/<id>/namespaces/<ns>/`, and `rendered()` re-renders from the namespace spec | `cmapi/src/cmapi/core/render/manifests.py:61-62`; `cmapi/src/cmapi/jobs/delivery.py:66-82`; `cmapi/src/cmapi/jobs/push_branch.py:29`; `cmapi/src/cmapi/jobs/pr_checks.py:74,89,130` |
| F7 | The Git layer itself is folder-generic: `BranchRequest.folder`, a sparse checkout of that folder, all files must be inside it, one reproducible commit, the branch `cmapi/<cluster>/<requestId>` | `cmapi/src/cmapi/core/git/base.py:60-69`; `cmapi/src/cmapi/core/git/workspace.py:77,376-383,407-447` |
| F8 | `_folder()` returns only `*.yaml` regular files, so `index.json` is invisible to `read_folder`, `tree_files` and the adoption test | `cmapi/src/cmapi/core/git/workspace.py:299-319,385-405` |
| F9 | One open request per `(cluster_id, namespace)` is a partial unique index, so two replicas cannot insert duplicates | `cmapi/src/cmapi/core/db/migrations/versions/0005_applied_and_merge_failed_hold_the_lock.py:26-27` |
| F10 | At most one pending job per `(kind, request_id, payload->>'kind')`; recurring jobs are ensured at worker start | `0001_cmapi_schema.py:108-109`; `cmapi/src/cmapi/core/db/repo.py:232-243`; `cmapi/src/cmapi/worker.py:60-65`; `cmapi/src/cmapi/jobs/__init__.py:36-37` |
| F11 | Approval decides by environment and action kind; thresholds read namespace facts; auto-approval policies match on `plugin` | `cmapi/src/cmapi/core/approvals.py:160-205,207-239` |
| F12 | `SUPERSEDED` is reached by `BASE_CHANGED` from `approved` and `pr_open` only; `pending_approval` has no such edge | `cmapi/src/cmapi/core/lifecycle.py:55-93` |
| F13 | The worker reads Argo CD's root Application (`status.sync.revision`, `revisions`, `sync.status`, `health`, `operationState.phase`) | `cmapi/src/cmapi/core/sync.py:92-111` |
| F14 | The config repository's CI recognises a cmapi PR by branch `cmapi/[^/]+/([^/]+)`, one single-parent commit, the bot identity and one `Cmapi-Request-Id` | `examples/cluster-configs/.github/scripts/kyverno_check.py:53-69`; `docs/reviews/2026-11-20-issue-429/README.md` |
| F15 | The config repository holds `policies/metadata-keys.yaml` but not `tiers.yaml` or `instance.yaml`, so its CI **cannot** run `cmapi-tools policies check` (which needs `--config-dir`) | `examples/cluster-configs/` listing; `docs/02-technical-design-v2.md:1951-1963,1965` |
| F16 | `tiers-rerender`, named as the precedent, is specified but not built: there is no operations plugin | `docs/02-technical-design-v2.md:1333,1352`; `cmapi/src/cmapi/plugins/` listing |
| F17 | With `engine: none`, every environment's mode is `off`, so the render is empty | `cmapi/src/cmapi/core/policy.py:57-61` |
| F18 | On CRC (apply mode, no Argo CD) the bundle is applied by hand: server dry run, then SSA with field manager `cmapi-policies`; nothing prunes | `docs/13-crc-deployment.md:740-760` |

## 2. Decisions

| Q | Options | Choice | Reason | Source |
|---|---|---|---|---|
| 1. Trigger | (a) start; (b) `POST /admin/reload`; (c) periodic; (d) combination | **(d): a recurring worker job `policy_bundle`, run at worker start and every `policy.bundle.checkInterval` (default 15 min, like `git_reconcile`), plus `POST /api/v1/policies/bundles/{env}:propose`. `/admin/reload`, when it is built, enqueues the same job** | Start covers every config change today (F2). Only a periodic run also sees Git changing under cmapi: a hand edit of a rendered file, a PR closed on the host, Git down at start. The worker alone runs it: API pods never write Git | F2, F10; Argo CD reconciles every 120 s + 60 s jitter (auto_sync doc), so 15 min is not the latency floor of delivery |
| 1a. Replicas and instances | leader election; DB lock; per-env advisory lock | **The DB, twice:** one pending `policy_bundle` job (F10), and the request lock `uq_cr_open_namespace` on `(cluster_id='policies', namespace=<env>)` (F9). A racing insert gets `IntegrityError` and becomes a no-op. Each instance acts only on `allowedEnvironments` (F5's ownership rule) | No new mechanism; both guarantees are already tested in Postgres | F9, F10 |
| 1b. Rolling update (old and new pods both run the job) | ignore; config-hash ordering; process start time | **Newest process wins.** A process does not open or supersede a policy request when the latest policy request of that env was created or merged after this process started and carries another hash; it logs `policy_bundle_check{outcome=stale_config}` | Config hashes are not ordered; process start is (a changed config starts new pods, F2). Without the rule an old pod reverts the new bundle |
| 1c. Idempotency | — | Same render hash as the open request: nothing. Same as `main`: nothing. Same as the latest request that ended `rejected`, `timeout`, or `failed` because a person closed its PR: nothing until the render changes or someone calls `:propose` | Prevents a reopen loop after an approver says no |
| 2. Git path | a second Git writer; generalise the namespace jobs; a target abstraction | **A `DeliveryTarget` chosen by `row.plugin`:** `NamespaceTarget` (today's behaviour, moved, unchanged) and `PolicyBundleTarget` (folder `policies/env/<env>/`). The Git layer is already folder-generic (F7); only the jobs are namespace-shaped (F6) | One delivery chain, one state machine, one reconciler. A second writer would duplicate the adoption test, leases and reproducible commits |
| 2a. Branch | `cmapi/policies/<env>/<rid>`; `cmapi/policies/<rid>` | **`cmapi/policies/<requestId>`**, via `request_branch('policies', rid)`. `clusters.yaml` refuses a cluster named `policies` (case-insensitive) | Matches #429's regex (F14), `worktree_path`'s name rule, the sweeper's `cluster/rid` split and the reconciler's prefix scheme with no change to their parsing |
| 2b. Commit | — | Subject `policies render <env> (<rid>)`; trailers `Cmapi-Request-Id`, `Cmapi-Plan-Hash` (as today), plus `Cmapi-Policy-Env: <env>` and `Cmapi-Policy-Bundle: <bundle hash>`. Author and committer `cmapi-git-bot`. **Namespace commits get no new trailer** | A new trailer on namespace commits would change the reproducible sha of a request in flight across the upgrade, and `recreate()` refuses a sha that differs (`workspace.py:494-497`) |
| 2c. Files | — | Only marked files and `index.json` of `env/<env>/`, plus deletions of marked files the render no longer gives. The same preflight as `render` (F5), moved into `core/policysync.py` and used by both | A hand-written policy in `policies/env/<env>/` (the README allows reviewed ones) is never touched |
| 2d. Forbidden | — | The policy target refuses any path outside `policies/env/<env>/` of an environment the instance serves; it never writes `clusters/`, `policies/metadata-keys*.yaml`, `.github/`, or another instance's env | Least privilege on a shared repo |
| 2e. Reconcile, sweeper, cleanup | — | `git_reconcile` adds the prefix `cmapi/policies/` to its cluster loop; `git_cleanup` and the sweeper need no change (they key on `cluster/rid`). `_folder()` gains a `suffixes` argument, default `(".yaml",)`; the policy target passes `(".yaml", ".json")` | F8: without it the adoption test and the PR check never see `index.json` |
| 3. Request model | a ChangeRequest; a separate table | **A ChangeRequest**: `plugin='policies'`, `action='render'`, `cluster_id='policies'`, `namespace=<env>`, `env=<env>`, requester `cmapi-policy-bot` (kind `service`, client `cmapi-worker`, sub `cmapi:policy-bundle`). Plan, approval, events, audit, PR checks, list and approve endpoints are the existing ones | Audit and approval come for free; the lock gives "one open policy request per env" (F9) |
| 3a. Approval rule | reuse env `change` (0 in rnd/dev); a fixed rule; a new section | **New optional section** in `approval-rules.yaml`: `policyBundle: {required: 1, group: approver-platform, timeoutHours: 72}`, overridable per env as `environments.<env>.policyBundle`. Default when absent: 1 from `defaults.group`. Thresholds and auto-approval policies never apply (`ApprovalRules.decide_policy(env)`) | Using `change` would auto-merge policy changes in rnd/dev (`change: 0`). The owner's rule is that approval rules gate (memory "approval is the gate"), so `required: 0` stays legal and is the owner's explicit choice |
| 3b. Migration | new columns; none | **None.** The plan JSONB carries the new fields; the lock is the existing index | Smallest change; nothing new to back-fill |
| 3c. API (additive) | — | `POST /api/v1/policies/bundles/{env}:propose` (`operations:run`, 202, job kind `policy_bundle` with payload `kind: propose:<env>`); `GET /api/v1/policies/bundles` (`requests:read`): per env `renderedHash`, `gitHash`, `openRequest`, per cluster `liveHash`, `hashState`. New optional fields: `policyBundle` on the plan view and the request view; `hashes` on `PolicyBundleView` | Contract additive only; approve and reject stay `POST /requests/{id}:approve|:reject` (`requests:approve` in the env, docs/14:96,199) |
| 4. Bundle hash | file text; Argo revision; per-policy digests | **`bundle_hash = sha256(json.dumps(sorted([name, digest] for each generated ValidatingPolicy of the env), separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()`; `null` when the set is empty** | The digest is the only per-policy value that exists on all three sides: render, Git and the cluster (F3, F4); a spec read back from the API server never equals the render (#302 D5). `index.json` does not reach admission, so it is out. Sorting makes key and file order irrelevant; values are strings, so no float formatting differs between platforms |
| 4a. Three hashes | — | `rendered` (from the in-memory render, F1); `git` (from `main`'s marked files, with each digest **recomputed** from the parsed doc, so a hand edit of a spec that kept its annotation is `tampered`); `live` (from `LivePolicy.generated == true`, F4) | A cluster that also runs another env's generated policy hashes differently: correctly not `current` |
| 4b. "The policies Application reports another hash" | Argo `status.sync.revision`; hash annotation; live policies | **Live digests decide; Argo CD explains.** The state per cluster: `current` (live = rendered), `behind` (live = git ≠ rendered: a policy PR pending), `drift` (live ∉ {rendered, git}), `unknown` (report cache not `ok`/`drift`, or stale), `off` (rendered = live = null). For Argo CD clusters the worker also reads `{clusterId}-policies` (`delivery.argocd.policiesApplication`, template as `application_name`, `sync.py:86-90`) for `sync.status`, `sync.revision` and `operationState.phase` | Argo CD reports a Git revision, not a bundle ("Revision contains information about the revision the comparison has been performed to"); apply-mode clusters have no Application (F18). Digests work for both and need no new RBAC |
| 4c. Each plan records | — | `plan.policyBundle = {env, mode, rendered, git, live, state, checkedAt}` in `change_requests.plan` and the plan view | Audit: which bundle the plan was validated against, and what the cluster ran |
| 4d. Plans and auto-approval while they differ | refuse; warn; hold | **By what the cluster enforces.** `enforce` mode, or any live generated policy with `Deny` (`liveEnforces`): **hold** at publish unless `current`, or `behind` and the plan also passes the git bundle. `audit` and nothing live Denying: **publish**, record the state, no warning. `off`: no gate. Auto-approval still decides at plan time; a new fact `policyBundleState` lets an instance add approvers by a threshold | In audit admission never refuses, so a mismatch cannot fail a sync; making it a warning would trip the warnings guard (docs/02 "The warning guard") and stop every auto-approval while a policy PR waits. In enforce a stricter live bundle would deny the sync, so cmapi does not publish what it cannot predict. Validating `behind` plans against the git bundle as well keeps delivery moving while the policy PR waits |
| 4e. Where the hold sits | plan time; push_branch; merge | **`bundle_gate(ctx, row)` in `push_branch` before the push, and again in `pr_checks` before `apply`/`merge`.** A hold is a wait, like `_wait_for_ci` (`pr_checks.py:145-159`): one `bundle_wait` event per reason, attempts reset, bounded by `policy.bundle.holdTimeout` (default 24 h), then `PR_FAILED` with problem `policy-bundle-mismatch`; `:retry` re-enters | Nothing reaches the host or the cluster while held. If the rendered hash moved since the plan (a restart with new config), the gate re-validates the plan with the current bundle; an error fails the request in enforce, and is an event in audit |
| 4f. Apply mode, no Argo CD | never deliver policies; deliver opt-in | **Opt-in policy delivery**: a cluster with `/etc/cmapi/policy-deliverer/<clusterId>` (token, apiUrl, ca.crt) gets the bundle applied by the `apply` job before the merge: server dry run, SSA with field manager `cmapi-policies`, then delete of generated policies of the env that the bundle no longer names. Without it the cluster is `manual`: its state stays `behind` and enforce plans hold | Keeps "no manual policy work" for CRC, as docs/13 does by hand (F18). It is a separate credential because writing admission policies is a different privilege, and RBAC cannot narrow `create` by name ("You cannot restrict deletecollection or top-level create requests by resource name") |

## 3. The policy request, end to end

1. `policy_bundle` (worker) for each served env whose mode is not off, or that has marked files on `main`: read
   `policies/env/<env>/` at `main` (with `index.json`), diff with the render (`core/policysync.diff`, F5's rule), compute the
   three hashes, refresh the state gauges.
2. No diff: done. Diff: apply rules 1b and 1c; supersede an open request in `pending_approval`, `approved` or `pr_open` with a
   new event edge `(PENDING_APPROVAL, BASE_CHANGED) -> SUPERSEDED` (F12: the other two exist) and `end_pr`; leave one in
   `applied`/`merge_failed`/`sync_failed` alone (the lock holds; the next run retries).
3. Plan: `files` (texts and `None` deletions), `prev` (the folder at `main`), `facts {plugin, action, environment, modeBefore,
   modeAfter, policiesAdded, policiesRemoved, policiesChanged}`, `bundle {hash, env, configHashes (cfg.hashes), processStart}`,
   and a self-check: each offered tier of the env is rendered through `ManifestRenderer` and validated with the **new** bundle,
   and must give no finding (an end-to-end form of `_check_offered`, `policygen.py:378-389`). `plan_hash` is `plan_hash(files)`
   (`manifests.py:92-97`). Insert with `decide_policy(env)`; `channel_notify` tells approver-platform.
4. Approved: `push_branch` -> `open_pr` (the host returns an existing PR for the branch, `base.py:247-249`) -> `pr_checks`.
   The cmapi check is today's: head = PR head, the folder (with `index.json`) = the plan, `changed_paths ⊆ plan files`
   (`pr_checks.py:84-87`). The local Kyverno step runs the step-3 self-check on the head. Host CI per slice 7.
5. Apply mode: the `apply` job delivers to each apply-mode cluster with a policy deliverer (4f); then `merge`.
6. `watch_sync` for the policy target: for each cluster of the env, `live == bundle.hash` (and, for Argo CD,
   `sync.status == Synced`, `phase == Succeeded`, `contains(sync.revision, merge_sha)`, `workspace.py:333`) -> event
   `bundle_synced{cluster}`. All confirmed, or `delivery.syncTimeout` reached -> `SYNCED`, the second with
   `bundle_unconfirmed{clusters}`. **A policy request never enters `sync_failed`**: main is already right, the gate protects the
   lagging cluster, and a `sync_failed` row would hold the env's lock against the next config change.

## 4. Failure and edge cases

| Case | Behaviour |
|---|---|
| The render changes again while a PR is open | Superseded (step 2); its PR closed with "superseded by <rid>"; one new request. Approvals do not carry over: the content changed |
| Approver rejects, or the approval times out | Final; not reopened for the same hash (1c). A new config, or `:propose`, opens again. Gauge `behind` stays visible, enforce plans hold |
| A person closes the PR on the host | `pr_checks` sees `closed` -> `failed` (`pr_checks.py:54-58`); treated as a rejection for that hash |
| A person merges the bot PR on the host | Adopted, as today (`pr_checks.py:59-65`) |
| Git or the host is down | The job raises `GitUnavailable`, backs off (worker `BACKOFF`), and the next period retries; `outcome=git_unavailable`. Plans still record `git: null`, and the gate uses only rendered vs live |
| A hand edit of a rendered file on `main` | Next run: diff -> a bot PR that restores the render; `git` hash `tampered` when only the spec changed |
| A hand-written policy in `policies/env/<env>/` | Not in any hash (no digest, `generated` false); never touched; collision with a rendered path refuses the plan, as `render` does (`tools/policies.py:87-88`) |
| The main folder moves under an open policy PR | `merge_check` -> `BASE_CHANGED` -> superseded (`pr_checks.py:130-139`); the next run re-plans on the new main (retryable, not 1c) |
| An env set to `off` (or `engine: none`, F17) | Render empty: one PR deleting the env's marked files; Argo CD prunes (`prune: true` in `policies-application.yaml`); live becomes null; state `off`. While live still Denies, `liveEnforces` keeps the gate on |
| A cluster unreachable or Kyverno not installed | `unknown`: enforce plans for it hold (fail closed); audit plans publish |
| Two instances share one repository | Each owns only its envs (F5); disjoint branches by request id; no cross-instance lock is needed |

## 5. Observability

- **Request events:** `bundle_planned`, `bundle_superseded`, `bundle_synced`, `bundle_unconfirmed` (policy requests);
  `bundle_wait`, `bundle_revalidated` (namespace requests). Logs: `policy_bundle_check{env, rendered, git, outcome}`.
- **Metrics:** `cmapi_policy_bundle_checks_total{environment, outcome}` (in_sync, opened, open, superseded, skipped_rejected,
  stale_config, git_unavailable); `cmapi_policy_bundle_state{cluster, environment, state}` (1 per current state);
  `cmapi_policy_bundle_behind_seconds{environment}` (since rendered ≠ git was first seen); `cmapi_policy_bundle_holds{environment}`.
- **Alerts:** `CmapiPolicyBundleBehind` (> `holdTimeout`), `CmapiPolicyBundleDrift` (state drift for 30 min).
- **Policies tab (#384):** keep `expected/live/current`; add the three short hashes, `hashState`, the Argo CD revision and
  phase, and a link to the open policy request ("dev: render ahead of Git; PR #N waits for approver-platform").

## 6. Slices (each mergeable alone, each with the test that fails before and passes after)

| # | Slice | Proof |
|---|---|---|
| S1 | `bundle_hash()` and `BundleHashes` in `core/policybundle.py`: rendered, git (recomputed digests), live; `hashState` on the tab | Unit: equal under shuffled dict and file order; changes with one digest; render vs live from the same digests equal; a spec edit with its old annotation is `tampered`; the example bundle's hash pinned. Service: `test_policies_302.py` extended for `hashState` |
| S2 | Plans record `policyBundle` (stored and view); OpenAPI additive | Service: a plan row holds the rendered hash and state; contract test: no field removed or retyped |
| S3 | `DeliveryTarget` refactor, `NamespaceTarget` only; `_folder(suffixes)` | The full service suite unchanged; a golden reproducible commit sha for a fixed namespace plan, equal before and after |
| S4 | `PolicyBundleTarget`, the `policy_bundle` job, `decide_policy`, the new SUPERSEDED edge, reserved cluster `policies`, reconciler prefix, `:propose`, `GET /policies/bundles` | Bare-repo service tests: a changed tier gives one request and one branch touching only marked files; two workers race -> one row; same hash -> no-op; new render -> superseded; rejected -> not reopened, `:propose` reopens; mode off -> deletions; hand-written policy untouched; extra path on the head fails the cmapi check; rnd's `change: 0` does not auto-approve |
| S5 | Policy `watch_sync`; `policiesApplication`; opt-in policy deliverer for apply mode | Fake kube: synced on live hash, waits on OutOfSync, timeout -> synced + `bundle_unconfirmed`; dry-run refusal -> failed with nothing written; prune deletes only generated policies of the env. kind: Kyverno v1.20.0 + Argo CD |
| S6 | `bundle_gate` in `push_branch` and `pr_checks`; `policyBundleState` fact; `holdTimeout` | enforce+drift holds (no branch pushed, one `bundle_wait`); enforce+behind passing git bundle publishes; audit+drift publishes; unknown holds in enforce; timeout -> `policy-bundle-mismatch`; rendered hash moved -> revalidated |
| S7 | Config repo CI (`examples/cluster-configs`, then `cmapi-cluster-configs`): recompute each marked file's digest; fail a non-cmapi PR that edits a marked file; on a cmapi policy-only PR, a Deny finding on an unchanged namespace folder is a warning | Script tests with fixtures; an agreement test that the script's digest equals `policy_digest` for the example bundle |
| S8 | Metrics, alerts, the tab's hashes and request link, docs/02 (the "Not built here" line 1971 and 1965), docs/16 (plan JSONB), docs/18 (`policy.bundle.*`, `policyBundle` rule) | Metric names test; portal unit and Playwright at 390/1440 px; the CRC walk: change a tier bound, see the PR, approve, see `current` |

## 7. What I could not verify

- Whether cmapi-reader (or the identity of `ArgoCdSignal`) may `get` a second Application in `openshift-gitops`; not read.
- That YAML round-trip of a rendered file gives the same dict, hence the same digest, in the CI script (S7 tests it).
- The worker Deployment's update strategy, which bounds how long old and new pods overlap (rule 1b assumes overlap is short).
- How the portal lists requests whose `cluster_id` is `policies`; the list and detail views were not read.
- Cost of the step-3 self-check per offered tier with the CLI; not measured.
- Kyverno's ValidatingPolicy page does not document `status.conditionStatus.ready`; cmapi reads it already (F4), unverified here.

## Sources (read 2026-11-19)

- Argo CD `pkg/apis/application/v1alpha1/types.go` (master): `SyncStatus.Revision` "contains information about the revision the
  comparison has been performed to"; `ReconciledAt` "when the application state was reconciled using the latest git version";
  `SyncOperationResult.Revision` "the revision this sync operation was performed to".
- Argo CD automated sync, <https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/>: `timeout.reconciliation` "defaults to
  120s with added jitter of 60s"; "only attempt one synchronization per unique combination of commit SHA1 and application parameters".
- Argo CD sync windows, <https://argo-cd.readthedocs.io/en/stable/user-guide/sync_windows/>: a deny window blocks syncs, so live may lag main.
- Kyverno ValidatingPolicy, <https://kyverno.io/docs/policy-types/validating-policy/>: `evaluation` "can be used to enable, or
  disable, admission request processing and background processing".
- Kubernetes RBAC, <https://kubernetes.io/docs/reference/access-authn-authz/rbac/>: "You cannot restrict deletecollection or
  top-level create requests by resource name."
- GitHub REST pulls, <https://docs.github.com/en/rest/pulls/pulls>: `head` "Filter pulls by head user or head organization and branch name".
