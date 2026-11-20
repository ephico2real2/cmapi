# cmapi #244 · Publish the environment bundle through an approved request

A change to the running configuration should produce one reviewable change per affected environment. The platform approver sees the file diff and validation findings in cmapi. Approval authorizes one immutable plan.
The worker opens and merges its PR. Each cluster can resume namespace writes as soon as its own policies catch up, independently of the other clusters in that environment.

## Decisions

All source locations below are relative to cmapi `main` at `f87fd2dc44d9cb5dfbd5a3ccc0a6b5006f41599b`, read **2026-11-19** (America/Chicago), except the explicitly identified config-repo and upstream references. Names introduced below are proposals.

| Question | Options | Choice | Reason | Source |
|---|---|---|---|---|
| When to compare? | Start/reload only, polling only, or both | Wake a durable worker on start and successful reload, and every 15 minutes with jitter | Immediate on config changes, eventual repair after a hand merge, missed wakeup or outage | `docs/reviews/2026-11-14-issue-212/design-opus.md:128`, `cmapi/src/cmapi/jobs/git_reconcile.py:31` |
| Unit of work? | Per cluster, per environment, or entire instance | One request for the owning instance's repository, base branch and environment | Clusters share the same files. Independent environments can have different approvers' scopes and roll out separately | `cmapi/src/cmapi/tools/policies.py:24`, `examples/instances/nonprod/instance.yaml:8`, `docs/02-technical-design-v2.md:1965` |
| Who can write where? | Arbitrary repository path, separate Git writer, or a second typed target on the existing writer | Add an environment-policy target with generated-file ownership checks | Reuses branch leases, PR adoption and exact head verification while keeping the namespace boundary enforceable | `cmapi/src/cmapi/core/git/base.py:60`, `cmapi/src/cmapi/core/git/workspace.py:376`, `docs/02-technical-design-v2.md:2260` |
| Who authorizes it? | Git review only, automatic merge, or a ChangeRequest | Internal `policies/rerender` request, one human `approver-platform` before push | The ledger records who approved the diff. Q5 locates approval evidence in the request and head check. Tier rerender is a precedent for ordinary requests. The catalog implements drift detection | `docs/reviews/2026-11-14-issue-212/README.md:53`, `docs/02-technical-design-v2.md:1352`, `cmapi/src/cmapi/core/tiers.py:677`, `docs/14-authorization.md:23` |
| What identifies a bundle? | Git SHA, raw YAML bytes, or canonical validator inputs | An environment-specific SHA-256 over the selected policy documents, mode and rule index. Keep the existing file-plan hash | Unrelated commits and YAML serialization can change with identical inputs. The index can change a plan verdict without any change to the policy YAML | `cmapi/src/cmapi/core/policygen.py:134`, `cmapi/src/cmapi/core/validate/__init__.py:217`, `cmapi/src/cmapi/core/render/manifests.py:92` |
| What proves delivery? | Trust an annotation, compare Git SHAs, or resolve the observed revision and check installed objects | Argo clusters require a healthy, synced policies Application and the bundle at its compared revision. Without Argo, use the platform installer's revision receipt and a live read | Git records the intended contents. Readiness and complete membership detect partial installs and pending prune | `cmapi/src/cmapi/core/sync.py:98`, `cmapi/src/cmapi/core/clients/policyreports.py:114`, `examples/cluster-configs/clusters/OCP_GF15/argocd/policies-application.yaml:15`, [Argo CD SyncStatus](https://github.com/argoproj/argo-cd/blob/v3.1.0/pkg/apis/application/v1alpha1/types.go#L1690-L1699) |
| What happens on mismatch? | Warn, queue all submissions, or refuse publication and hold previously issued work | Retryable refusal before publication in audit and enforce. Hold existing approved work for transient lag. Replan changed inputs | A warning could authorize an unseen rule set. Queuing speculative new requests would also reserve namespaces while approval facts are uncertain | `docs/reviews/2026-11-14-issue-212/README.md:56`, `docs/reviews/2026-11-14-issue-212/design-codex.md:76`, `cmapi/src/cmapi/core/pipeline.py:408` |
| Second change or rejection? | Amend the PR, retry continuously, or supersede and remember decisions | Fresh request for a changed diff. Suppress the same rejected proposal until an explicit retry or material change | Approval belongs to the exact plan. One denial should survive a process restart | `cmapi/src/cmapi/jobs/pr_checks.py:73`, `cmapi/src/cmapi/routers/requests.py:147` |
| How do people see it? | New dashboard or extend Policies and Approvals | Extend the existing cluster row with revision, hashes, gate reason and request link | The tab already has expected/live counts, action drift, readiness and unknown states. Its comparison alone misses extra policies | `cmapi/src/cmapi/plugins/policies/router.py:80`, `cmapi-portal-ui/src/portal/PoliciesTab.tsx:152` |
| How to ship? | Switch everything at once, or stage read/verify/write | Land the hash, schema, observers, writer and controller separately. Activate the gate after consumers support both targets | Existing rows and running workers have namespace assumptions. Old approvals lack bundle provenance | `cmapi/src/cmapi/core/db/models.py:25`, `cmapi/src/cmapi/jobs/delivery.py:79`, `docs/16-data-model.md:68` |

## Trigger, ownership and concurrency

- Derive work only from `cfg.allowed_environments`. Bind each key to the configured host/repository identity and default branch, independent of SSH versus HTTPS URL spelling.
  A reviewed deployment inventory maps each such environment to exactly one instance and database. Validate uniqueness across instance manifests in release CI, including two instances using the same repository.
  Workers check their ownership against that inventory before opening or cleaning up a PR. Ownership transfer drains the old writer and its PR before activating the new owner.
  Removing an env from an instance revokes its authority. Explicitly turning it off while still owned authorizes pruning.
- Use one authoritative immutable **config release** for publication.
  The deployment supplies a monotonic rollout generation and a content-addressed reference to the reviewed inputs and renderer image, produced automatically on rollout. A rollback gets a newer generation.
  At first start or on a newer mounted release, validate the entire candidate, render all served envs and atomically install its generation/fingerprints and wakeups in PostgreSQL. Replicas with the same release join.
  Older generations cannot publish work or replace desired state. Equal generation with different contents is a configuration error. Each API and worker must load that generation before handling policy-sensitive work.
  This also fences an old pod during rolling updates.
- Add `POST /api/v1/admin/reload`, using existing `admin:reload` across all environments the reload can affect.
  It loads the configured release, takes no paths, credentials or policy content from the caller, and returns 202 with the accepted generation and queued environments.
  An invalid candidate gives 422, keeps the last accepted snapshot and enqueues nothing.
  Processes observe the accepted generation and atomically replace the matching configuration, validator, bundle and affected caches. Startup and reload need no Git-host availability.
  The current API and worker build separate contexts, and reload is documented as unimplemented.
  `cmapi/src/cmapi/core/config.py:66`, `cmapi/src/cmapi/core/context.py:81`, `cmapi/src/cmapi/core/context.py:97`, `cmapi/src/cmapi/worker.py:212`, `docs/14-authorization.md:387`.
- Proposed job `policy_reconcile` reads the default branch at a pinned SHA, snapshots the target folder and diffs the generated subset.
  Under a row lock per target, recheck desired generation and base, then atomically record the request, event and notification. An unchanged tree is a no-op. Signals coalesce into one pending comparison per target.
  A periodic scan also finds dirty targets without jobs. The open-request unique index is the final arbiter across replicas. Losing transactions reread the winner.
  The render digest alone is a poor idempotency key because a later rollback or a new edit of the same Git base may need a legitimate new request.
  `cmapi/src/cmapi/worker.py:60`, `cmapi/src/cmapi/core/db/repo.py:137`, `cmapi/src/cmapi/core/db/repo.py:245`.

## Request, database and API

**Migration 0007** follows `cmapi/src/cmapi/core/db/migrations/versions/0006_policy_rejections.py:18`.
Extend `change_requests` with `target_kind` (default `namespace`), `repository_key`, `base_branch` and nullable `policy_bundle_hash` (64 lowercase hex). Store the version and validation details in `plan.policyBundle`.
Relax `cluster_id` and `namespace` only for a checked `target_kind=policy_environment`, which requires both null, a real `env`, repository and branch, and `plugin=policies, action=rerender`.
Keep namespace constraints and their lock. Policy jobs use the existing empty job cluster key. Capacity, namespace conflict queries and namespace-specific notifications must dispatch on target kind.
`cmapi/src/cmapi/core/db/models.py:18`, `cmapi/src/cmapi/core/db/models.py:87`, `cmapi/src/cmapi/core/db/repo.py:105`, `cmapi/src/cmapi/jobs/channel_notify.py:22`.

Add `policy_bundle_targets` keyed by `(repository_key, base_branch, env)` with `owner_instance, desired_generation, config_ref, desired_hash, dirty, active_request_id, suppressed_fingerprint, last_error, observed_base_sha, updated_at`.
Store the desired managed-file map or its immutable artifact reference with the generation. Create the per-cluster observation table described below in the same migration.
Add `uq_cr_open_policy_env` on the target key for policy requests in `pending_approval, approved, pr_open`. Hold `active_request_id` through remote cleanup on supersession even after the unique index releases.
Emit request history into existing `request_events`, `approvals` and `audit_events`. Preserve the namespace index's current open states, including applied and merge_failed.
A downgrade with policy rows requires archival or a forward fix.
`cmapi/src/cmapi/core/db/migrations/versions/0005_applied_and_merge_failed_hold_the_lock.py:20`, `docs/16-data-model.md:130`, `cmapi/src/cmapi/core/db/models.py:60`.

The controller submits as the internal service identity `cmapi-policy-controller`, with automated=true, actual instance/env, config release, base SHA, old/new mode, exact file diff, validation findings and affected clusters.
It cannot approve. In `ApprovalRules.decide`, handle this typed action after the served-env check and before namespace patterns, count-zero defaults and auto policies.
Return the stored requirement `policy-bundle-platform` with one platform slot, the configured group path and environment timeout, selfApproval=false, auto=null.
Human decisions require the environment permission and eligible token group. The policy rejection uses the same group restriction. Use the existing row-locked ledger and audit. A Git review alone cannot enqueue a push.
`cmapi/src/cmapi/core/approvals.py:160`, `cmapi/src/cmapi/core/approvals.py:321`, `cmapi/src/cmapi/routers/requests.py:124`, `docs/02-technical-design-v2.md:1840`, `docs/14-authorization.md:205`.

**Wire compatibility.** Existing `ChangeRequest` requires a real cluster and namespace. Filter the default namespace list by target kind before text search, sorting or pagination. Its schema stays valid.
Add `GET /api/v1/policies/requests` with the usual paging and `approver=me`, and `GET /api/v1/policies/requests/{id}` with a typed environment target, old/new diff, findings, events, approval and PR.
Reuse decision services behind `POST /api/v1/policies/requests/{id}:approve|reject|cancel|retry`. Both route families check target type before dispatch.
Expose no public create, arbitrary path, direct merge or rollback endpoint. The portal combines pending items for an eligible approver.
Read/decision permissions are respectively `requests:read`, `requests:approve|reject`, and the existing operator cancel/retry rules, all checked against row.env.
Namespace plan/request/approval-status responses gain optional `policyBundleHash` and validation mode. `GET /api/v1/policies/results` keeps `objects:read`.
Omit request details unless the viewer also has `requests:read`.
`cmapi/src/cmapi/core/models.py:162`, `cmapi/src/cmapi/routers/requests.py:59`, `cmapi/src/cmapi/routers/requests.py:104`, `cmapi/src/cmapi/core/authz.py:21`, `cmapi/src/cmapi/plugins/policies/router.py:193`.

## Git delivery and CI

1. Derive a closed target type inside the worker. A namespace request produces its existing folder and branch. A policy request produces exactly `policies/env/<env>/` and `cmapi-policy/<instance>/<env>/<requestId>`.
   Validate each component against an unambiguous Git-ref/path segment grammar before joining it. Use a separate local worktree root for policy targets.
   The distinct top-level ref prefix cannot collide with a cluster named “policies.” Keep one single-parent commit with the existing `Cmapi-Request-Id`, `Cmapi-Plan-Hash`, `Cmapi-Approval`, `Cmapi-Requester` and `Cmapi-Instance`.
   Add `Cmapi-Policy-Environment` and `Cmapi-Policy-Bundle-Hash`. Check their single values against the row. On new namespace commits also include the pinned bundle hash.
   During delivery verify both trailers independently against the approved row. Use the same bot, credentials and approval timestamp.
   `cmapi/src/cmapi/core/git/workspace.py:45`, `cmapi/src/cmapi/core/git/workspace.py:407`, `cmapi/src/cmapi/jobs/delivery.py:55`, `docs/19-setup-connections-to-git.md:9`.
2. Extend workspace and both host adapters with a target-aware, complete tree read at a verified commit, including file modes and the reserved `index.json`. Namespace reads today select only YAML.
   A missing folder at a known commit is empty. A missing commit, permission failure, truncated listing or unsupported tree mode is an error. Enumerate all immediate entries.
   Reject symlinks/submodules on any writable path or ancestor, traversal, ambiguous separators and file/directory collisions before staging. Preserve unrelated regular files byte-for-byte.
   Compare the entire target folder before/after by Git object ID and mode, but pass **only approved changes** to the writer.
   Separate the full expected tree from the write set in `BranchRequest` and in merge/adoption checks.
   `cmapi/src/cmapi/core/git/workspace.py:299`, `cmapi/src/cmapi/core/git/github.py:66`, `cmapi/src/cmapi/core/git/gitea.py:44`, `cmapi/src/cmapi/core/git/transport.py:102`, `cmapi/src/cmapi/core/git/workspace.py:669`.
3. Allowed changes are direct children emitted by the renderer and obsolete marked YAML or the owned index from that same base. Use the CLI's ownership/preflight logic for additions, edits and tombstones.
   Unmarked YAML at a wanted path is a conflict. An index collision with non-generated data needs review. Reject unrecognized existing index structure before deletion.
   The bot has no write path to hand policies, config inputs, another environment, AppProject/Application YAML, workflows, or the default branch.
   Verify the complete changed-path set against the approved delta, including deletions, renames and mode changes.
   `cmapi/src/cmapi/tools/policies.py:29`, `cmapi/src/cmapi/tools/policies.py:74`, `cmapi/src/cmapi/jobs/pr_checks.py:73`.
4. Reuse `push_branch → open_pr → pr_checks → merge → git_cleanup`. Before push/merge, check active request, current generation/render, approval, exact base folder and planned tree. Fence each external write.
   Adopt only a matching parent, trailers, changed paths, tree, PR base repository/branch and head. On ambiguous host timeout, look up **closed and merged** PRs too before another create.
   Existing open PR for that request and head means success. Prefer expected-ref leases for creation and deletion. Require SHA-pinned merge on both hosts.
   For REST-only Gitea, exhaust pagination, compare complete parent/head trees and use create-if-absent. Where conditional delete is unavailable, retain the ref, flag it, and use a fresh request ID for a replacement.
   A read followed by an unconditional delete is unsafe.
   `cmapi/src/cmapi/jobs/push_branch.py:29`, `cmapi/src/cmapi/jobs/open_pr.py:34`, `cmapi/src/cmapi/core/git/workspace.py:385`, `cmapi/src/cmapi/core/git/github.py:138`, `cmapi/src/cmapi/core/git/gitea.py:134`.
5. Verify the projected merge tree before merge, the pinned head at the host and the actual result at the returned merge SHA, including hand merges.
   A verified policy request finishes at `merged` (terminal **for this target**). Track rollout separately per cluster.
   A merge with an unverifiable or wrong tree records `sync_failed`, alerts and schedules re-observation/repair from actual main.
   Policy requests bypass namespace apply, capacity, prune confirmation and namespace sync/revert handlers in both delivery modes. Release repair ownership after the actual tree is known.
   A failed cluster rollout must never prevent a corrective policy PR.
   `cmapi/src/cmapi/jobs/pr_checks.py:130`, `cmapi/src/cmapi/jobs/merge.py:89`, `cmapi/src/cmapi/jobs/merge.py:134`, `cmapi/src/cmapi/core/lifecycle.py:68`.
6. Local sweep retains worktrees for either target while active. Host reconcile enumerates exact owned policy prefixes in addition to the existing cluster prefixes.
   Verify target, instance, DB row, PR number, head and trailers before destructive cleanup. An unknown policy row after DB loss, foreign head, partial list or ownership change is quarantined for inspection.
   Recover an interrupted approved push/open by looking up its branch and PR. Close verified duplicates, retain grace periods, and never touch human refs or another instance's work.
   `cmapi/src/cmapi/worker.py:80`, `cmapi/src/cmapi/jobs/git_reconcile.py:41`, `cmapi/src/cmapi/jobs/git_cleanup.py:27`.

**CI contract.** Keep the two `ci/*` contexts and the worker's independent `cmapi/check`.
Validate candidate policy manifests against the pinned Kyverno CRD schema, compile/exercise every policy against matching fixtures (including an environment with no namespaces), and evaluate the existing namespace folders in the candidate merge tree.
Use the same pinned tooling and severity in the worker when host checks are disabled. A policy file fed into the current namespace validator can exercise zero matched resources.
Show the affected audit findings in the policy plan before approval. If a changed base introduces new findings or changes their severity, supersede the plan before merging.
Existing namespace-only plans retain their checks.
`cmapi/src/cmapi/core/validate/__init__.py:150`, `cmapi/src/cmapi/jobs/pr_checks.py:66`, `examples/cluster-configs/.github/workflows/ci.yml:18`, `examples/cluster-configs/.github/scripts/kyverno_check.py:139`.

Extend #429's recognizer with the exact policy branch form and matching instance/env/request trailers. Preserve its base-repo, one-commit, one-parent, bot author/committer and email checks.
On verified request-shaped PRs audit violations warn, Deny violations fail. Other PRs, including human policy PRs, fail audit violations too. Evaluation errors fail both. These unsigned fields select severity.
The worker proves authority and exact changes. Branch protection is a separate deployment control.
`docs/reviews/2026-11-20-issue-429/README.md:3`, `docs/reviews/2026-11-20-issue-429/README.md:18`, `examples/cluster-configs/.github/scripts/kyverno_check.py:53`.

Add render agreement to `ci/kyverno`.
Fetch the owning instance's immutable reviewed release inputs with read-only access from the trusted deployment source, then run the pinned `cmapi-tools policies check` on the proposed tree.
Supply an additive `--environment` filter so each changed generated environment can be repaired independently. Check every impacted env for a shared input change.
Keep the complete-instance check on main for overall drift. Configure that source during bootstrap and fail the check if it cannot be verified.
This avoids trusting configuration or executable code provided by the proposed policy commit. The current template invokes only its namespace-folder script.
`cmapi/src/cmapi/tools/policies.py:55`, `cmapi/tests/core/test_policygen.py:146`, `docs/02-technical-design-v2.md:1965`, `examples/cluster-configs/.github/workflows/ci.yml:51`.

## Hash and publication gate

**Bundle identity.** Build one immutable per-environment snapshot and give that same object to the validator, planner and observer.
Start with the files actually selected by `policies_for(env)`, including local hand-written policies outside `env/` and inside this environment. The render wins on a path clash as today.
Use the part of the validator index referenced by selected policies. Read hand-written files once per snapshot. Track the CLI version, release and provenance separately for audit.
`cmapi/src/cmapi/core/policybundle.py:22`, `cmapi/src/cmapi/core/validate/__init__.py:75`, `cmapi/src/cmapi/core/validate/__init__.py:146`, `cmapi/src/cmapi/core/policygen.py:468`.

- Define `policyBundleHash` as lowercase SHA-256 of the UTF-8 encoding of a versioned JSON object with `format=1, environment, mode, policies, index`.
  Each policy record contains its full parsed desired document with the self-referential digest annotation removed.
  Sort documents by (apiVersion, kind, namespace-or-empty, name), preserving array order **inside** each document. Reject duplicate identities, duplicate mapping keys, unsupported scalar types and non-finite numbers.
  Convert Kubernetes YAML to JSON using the validator’s scalar interpretation, then encode the record with RFC 8785 canonical JSON. Reject values that would lose precision rather than silently rounding them.
  Normalize file line endings before parsing. Preserve scalar strings, including Unicode and embedded newlines. A changed CEL expression, validation action or index entry changes the digest.
  Comments, YAML key order, file enumeration order and OS paths do not. The off snapshot has empty policies/index and explicit mode.
  `cmapi/src/cmapi/core/policygen.py:124`, `cmapi/src/cmapi/core/policygen.py:408`, `cmapi/src/cmapi/core/kube_yaml.py:3`, [RFC 8785 §3](https://www.rfc-editor.org/rfc/rfc8785.html#section-3).
- Separately, preserve byte agreement with the generated files in Git and the existing `planHash` over file paths/content/tombstones.
  A formatting-only edit may need a repair PR without holding a semantically identical namespace plan. The request binds both hashes to the immutable plan record.
  A policy request stores its proposed destination bundle hash and records that its validation evaluated the candidate. Namespace dry runs and stored plans include the hash, mode and `evaluated` flag.
  Deletes with no applicable manifests still pin the active snapshot and record `evaluated=false`.
  `cmapi/src/cmapi/core/pipeline.py:65`, `cmapi/src/cmapi/core/pipeline.py:365`, `cmapi/src/cmapi/core/render/manifests.py:92`, `cmapi/src/cmapi/core/validate/__init__.py:104`.

**Argo evidence.** Configure `delivery.argocd.policiesApplication` with default `{clusterId}-policies` and optional per-cluster override. Resolve it in the configured Argo namespace with cmapi-reader.
Verify this Application's repo, branch, environment directory, plain YAML selection and destination against the registered cluster.
Require the compared source to match its current spec, fresh reconciliation, `status.sync.status=Synced`, `status.health.status=Healthy`, and no failed/running sync, comparison error or pending prune.
Require a single supported Git source. Resolve the full `status.sync.revision` in that repository and reconstruct the manifest set and index **at that commit**.
Derive observed mode from the committed generated validationActions and confirmed installed actions (Deny for enforce, Audit/Warn for audit, empty generated set for off). Mixed or ambiguous evidence holds the gate.
Use the observed index and verified documents to compute the same versioned hash. Leave the observed hash null when evidence is missing. Cache immutable reads by repo/SHA/env.
A later namespace-only commit can give the same bundle hash. An ancestor check alone would also accept a later policy rollback.
`cmapi/src/cmapi/core/sync.py:34`, `cmapi/src/cmapi/core/sync.py:86`, `examples/cluster-configs/clusters/OCP_GF15/argocd/policies-application.yaml:11`, [Argo CD ApplicationStatus](https://github.com/argoproj/argo-cd/blob/v3.1.0/pkg/apis/application/v1alpha1/types.go#L1052-L1067).

Compare that source inventory with a fresh complete read of the cluster's cmapi policies.
Require every expected identity, readiness for its current generation where exposed, expected actions and authored content, and absence of obsolete cmapi-owned identities (including prior inventories).
Exclude unrelated platform policies. The existing annotation helps identify a generation, but can survive a manual spec edit.
Compare the effective spec using the installed, supported CRD's schema defaults on the desired object, excluding status and server-assigned metadata on both sides. Compare authored metadata and all spec fields.
An unexplained default, unsupported kind or unreadable policy yields `unknown`.
For hand-written inputs independently installed outside the Application's directory, join by identity and verify the same authored content live.
A hand YAML in the Application that the API never loaded is likewise a mismatch. Do not inject local files into the bot write set to manufacture agreement.
Distinguish genuine unrelated admission controls from policies declared as part of this bundle.
`cmapi/src/cmapi/core/policygen.py:128`, `cmapi/src/cmapi/core/clients/policyreports.py:114`, `cmapi/src/cmapi/plugins/policies/router.py:80`, `examples/baseline/cmapi-reader-rbac.yaml:49`.

**Apply without Argo.** Keep namespace delivery and policy installation independent. For an enabled environment, a platform-owned installer watches the merged environment tree.
On no-Argo baselines automate the existing install procedure after merge and on restart, with a separate identity limited to the declared policy kinds and its inventory.
It verifies the approved source, dry-runs, server-side applies, prunes only previously owned identities with UID preconditions, waits for readiness and finally records the applied repository/revision/env and owned identities in `ConfigMap/cmapi-policy-installation` in the baseline namespace.
Serialize installs per cluster, retry partial work and issue the receipt only for the generation actually installed. Give cmapi-reader get on this one ConfigMap.
A platform installer for hand-maintained policies remains their owner. The worker verifies that revision's index and policies and does the same fresh live comparison as the Argo path.
A Git merge, a receipt alone, or a PolicyReport count cannot release a plan. If an approved repair races a hand edit, refetch main and restart on the new committed inventory.
With no installer/evidence, report `installation-unknown` and hold enabled clusters. No extra policy-write verbs reach the API, cmapi-reader or namespace deliverer.
`deploy/kind-import/kyverno.sh:26`, `deploy/manifests/environments/crc/deliverer/00-cmapi-deliverer.yaml:21`, `cmapi/src/cmapi/core/sync.py:59`.

**Enforcement and recovery.**

| Boundary | Behaviour |
|---|---|
| Preview and submit | After local validation, compare the plan's immutable snapshot with current accepted desired state and cluster evidence. On known mismatch return 409 `policy-bundle-out-of-sync`. On unavailable/stale evidence return 503 `policy-bundle-unavailable` with Retry-After. Include expected/observed hash (null if unknown), reason and scoped status link. Publish neither a successful dry run nor a request, approval, reservation or branch. A replay of a previously accepted idempotency key may return that existing request. |
| Already submitted | Recheck at human approval and just before committing any auto/none-required decision, then at push, PR checks and immediately before merge or the first namespace apply. Read cluster-specific evidence with a bounded age (proposed 60 s), independently of report freshness. Refresh on demand, invalidate on failed reads/source changes, and use a fresh direct check before irreversible effects. Require a recent Argo comparison as well (proposed 5 min, configurable for a site's reconciliation interval). Serialize decisions against the accepted generation with the target row lock. Poll held jobs without consuming their failure budget. The latest observation is a point-in-time guarantee. Admission remains authoritative after the read. |
| Desired inputs changed | Before an external apply, mark the old plan superseded, revoke delivery eligibility, close its PR and require a newly validated request/approval. Preserve old decisions. If solely the observed cluster lags while the desired hash and plan still agree, resume the same request after convergence. A partial namespace apply keeps its lock and pinned head. Hold further object writes for parity. An already confirmed apply can finish its pinned merge to restore Git consistency. Record that recovery distinctly. |
| Scope | Cover namespace creation/update/delete, expiration, operator retries, scheduled submissions, reverts and alternative submit paths. Centralize the gate at plan publication and worker effect boundaries. Candidate policy requests must proceed through their own approval during drift, or the system would deadlock. Audit-mode warnings retain the existing human-review fallback even after parity succeeds. |
| Legacy plans | Return null hash for pre-0007 history. Never backfill from today's render. Before enabling enforcement, drain already-started apply/merge recovery under the old contract. Supersede unpublished/open legacy plans without a proven snapshot and permit resubmission. Prevent old workers from claiming policy jobs during rollout. |

These boundaries correspond to `cmapi/src/cmapi/plugins/namespaces/router.py:175`, `cmapi/src/cmapi/core/pipeline.py:419`, `cmapi/src/cmapi/jobs/open_pr.py:98`, `cmapi/src/cmapi/jobs/delivery.py:114`, `cmapi/src/cmapi/core/lifecycle.py:72`, and `docs/02-technical-design-v2.md:1969`.

## Failure and operator behaviour

| Condition | Outcome |
|---|---|
| Render changes while review/PR is open | Under the target lock compare the approved diff and effective validation inputs. If unchanged, retain the request and record equivalence to the new generation under the same lock. Recheck that equivalence at delivery. Otherwise supersede even a pending approval, stop further delivery, close the verified old PR and confirm closure before allowing a replacement PR. Old and new request IDs cross-link. If a merge won the race, recompute from the actual merge. Never transfer approvals. |
| Rejection, timeout, cancellation, or human closes PR | Keep the decision, actor/comment or host disposition. Persist suppression of the desired proposal plus relevant base-tree fingerprint (independent of unrelated main commits). Avoid reopening on every tick. New material diff or an operator's scoped `:retry` submits a fresh request requiring platform approval. Distinguish an explicit veto from transient transport failure. |
| Git/host outage or lost job acknowledgement | Preserve desired state, active ID, branch and pending actions. Use existing backoff, jittered rescheduling and a capped interval for infrastructure failures after normal attempts are exhausted. Read back the actual remote state before retrying a mutation. A failed comparison is never an empty tree. Keep read endpoints available with age/error. `cmapi/src/cmapi/worker.py:4`, `cmapi/src/cmapi/core/git/base.py:197`. |
| Reviewed hand change | Permit reviewed policy PRs under the #429 strict path. Unmarked hand files and shared inputs remain platform-owned. A changed generated file triggers a proposed repair against its new base. A file losing its generated marker at a wanted name raises `ownership-conflict`. A hand edit during review invalidates any affected base/diff/findings. Reconcile after a direct or human merge even if no request exists. [Config repo README, lines 8–12 and 29–53](https://github.com/ephico2real2/cmapi-cluster-configs/blob/3e4bad30202f273b5ad452247e0d0db82f0916f6/README.md#L8-L53). |
| Mode becomes off or engine becomes none | Desired generated set is empty. Approve a deletion PR for owned YAML and index. Record its canonical off hash. Keep a platform-owned non-manifest `.gitkeep` in each bootstrapped Argo source directory and enable `automated.allowEmpty: true` with prune, so the final deletion leaves a valid source. Previously enabled clusters stay held until old owned objects are gone. A fresh, never-enrolled off cluster with no policy installation requires neither Argo nor Kyverno. Persist enrollment/last installed inventory through restarts, including off transitions. Seed enrollment and previous owned identities before activating the gate, including clusters known to have run enforce. At transition to off, continue the dedicated observer until it proves absence. Successful API discovery that the policy kind is absent can establish removal. A denied read cannot. Unmanaged hand policies remain under platform review. Off skips their local evaluation. `cmapi/src/cmapi/core/policygen.py:430`, `cmapi/src/cmapi/core/context.py:97`, `examples/cluster-configs/clusters/OCP_GF15/argocd/policies-application.yaml:24`, [Argo CD automatic prune with an empty target](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/#automatic-pruning-with-allow-empty-v18). |

## Observability

Add `policy_bundle_clusters(instance, cluster_id, env, enrolled, installed_inventory, source_revision, observed_hash, observed_at, gate_state, reason)` for shared observations and restart-safe prune bookkeeping.
Evidence expires. A failed observation clears eligibility immediately and retains the last success as history. The portal and worker consume the same observer.
Avoid inferring freshness from the last successful list of a different resource kind. `cmapi/src/cmapi/core/clients/policyreports.py:244`, `cmapi/src/cmapi/plugins/policies/router.py:165`.

- Extend each Policies cluster row with `publication.{expectedHash,observedHash,source,revision,asOf,state,reason,requestId,prUrl}`.
  Show “waiting for platform approval”, “merged, waiting for cluster”, “current”, “pruning”, “blocked”, or “unknown” with the observed time. Keep expected/live/current/ready counts and missing/differing names.
  Show a copyable full digest, short visible digest and the affected environment. Limit links/events by the viewer's environment and permissions.
  Include a pending env-level change even if there are zero registered clusters.
- On transitions emit `policy_bundle_drift`, `policy_bundle_superseded`, `policy_bundle_suppressed`, `policy_bundle_held`, and `policy_bundle_current` with env, cluster when applicable, old/new hashes, revision, request ID and reason.
  Reuse standard approval/PR/merge events and fenced job logs. For refusal before any request exists, emit a structured gate event and counter without creating a fictitious request.
  Audit accepted/rejected reloads and explicit retry. `docs/16-data-model.md:143`, `cmapi/src/cmapi/core/db/models.py:104`.
- Add `cmapi_policy_bundle_reconciliations_total{environment,outcome}`, `cmapi_policy_plan_gate_total{environment,stage,result}`, and `cmapi_policy_bundle_cluster_state{cluster,environment,state}` (one active state per cluster).
  Alert on sustained unknown/mismatch, repeated host errors, or a suppressed desired change. Keep hashes, SHAs, paths and request IDs out of metric labels.
  `cmapi/src/cmapi/core/observability.py:55`, `docs/02-technical-design-v2.md:1936`.

## Independently mergeable slices

| Slice | Deliverable and acceptance test |
|---|---|
| 1 · Identity only | Add snapshot and canonical hash in `core/policybundle.py`, expose on dry run, keep decisions unchanged. Golden tests permute document/key order, CRLF, Unicode and file enumeration. Change a bound, a hand policy or the index and expect a new hash. Reorder CEL validations and expect a new hash. Confirm off/env isolation and duplicate-key rejection. |
| 2 · Storage and review | Migrate 0006→0007, add the typed target, ledger rule and read/decision API. Feature stays dormant until a producer is enabled. On PostgreSQL race two creates and approvals, prove one active request/one human vote, deny cross-env/non-platform approval and wildcard auto/waive, and prove namespace listing, lock, OpenAPI and old rows retain their contract. |
| 3 · Scoped Git delivery | Implement tree snapshots, generated-file diff, typed branches, worker dispatch, sweep and reconcile. Use a bare remote plus adapter contract fixtures for GitHub/Gitea. Round-trip the JSON index and a deletion beside hand files. Reject symlink, foreign head, out-of-folder path and changed mode. Kill after push/PR/merge but before DB commit and prove adoption of exactly one PR. Verify policy merge enqueues no namespace apply. |
| 4 · Review and CI parity | Ship the configuration repository's workflow/script and trusted release inputs before enabling the writer. Test approved bot audit vs human audit, Deny/evaluation errors in both, forged or duplicate trailers and outside-plan changes. Include zero namespaces, stale index and two dirty envs repaired separately. Compare actual fixture results with the worker's local mode. |
| 5 · Desired-state controller | Add start/reload/timer, ownership validation, fencing and suppression. With two API and worker replicas and two disjoint instances sharing a Git remote, simulate simultaneous starts, reload during review, old pod restart, hand merge, Git outage and rejected PR. Assert one PR per changed env at any time, zero on equal trees, fresh approval on changed content and autonomous retry after recovery. |
| 6 · Observe rollout | Add the Argo source/revision reader, no-Argo baseline installer/receipt and observation fields, initially diagnostic. On kind with Argo, run a real policy merge, unrelated later commit, rollback, missing path, final empty prune and config-only index change. Without Argo interrupt an install, leave an obsolete policy, edit a live spec keeping its digest, then recover. Only complete, ready and current evidence passes. Verify reader and namespace writer cannot install policies. |
| 7 · Enforce and surface | Wire publication/approval/effect guards and Policies/Approvals UI after upgrading all replicas and establishing initial inventory. Simulate a two-cluster rollout with one delayed and test manual and auto paths, dry run, expiry, retry and a previously approved plan. Assert zero publication/effects on mismatch, release only the current cluster, correct applied-head recovery, scoped links and exactly one transition event. |

## Verification limits

The supplied checkout has no TokenSave index, so source locations were checked directly on the requested commit. The example directory has no README of its own.
I read `examples/README.md:25` and the actual config repository's README at the #429 evidence commit via a local config-repo checkout. The supplied template and arbitration establish CI behaviour.
Production branch protection, credentials, authoritative rollout artifacts and the live clusters' exact Argo/Kyverno versions and CRD defaults were not verified.
This design assumes deployment automation can publish release inputs for independent CI verification. The release feed, no-Argo receipt and automatic post-merge installer are new work.
Existing kind tooling applies one pinned bundle and waits for readiness. Empty-source prune, partial installs, schema normalization and race recovery need the integration proofs above.
`docs/reviews/2026-11-14-issue-212/README.md:102`, `docs/reviews/2026-11-20-issue-429/README.md:28`, `deploy/kind-import/kyverno.sh:30`.
