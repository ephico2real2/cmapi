# #244 · The bot proposes the policy bundle, and each plan records it: arbitration

Two designs were written independently from one brief (`brief.md`) on 2026-11-19/20: [design-codex.md](design-codex.md)
(Codex `gpt-6.2-astra`, high) and [design-opus.md](design-opus.md) (Opus 5.5, high). Neither saw the other. The
coordinator (Opus 5.5) arbitrated on 2026-11-20, after checking the premises each choice rests on in the code.

**Premises checked:** reload is not built, and a config change restarts the pods by the ConfigMap hash (docs/18, item 2).
Every rendered policy carries `cmapi.net/policy-digest`, SHA-256 of its canonical JSON without the annotation
(`core/policygen.py`, `policy_digest`). The open-request lock is `uq_cr_open_namespace` on `(cluster_id, namespace)`
(migration 0005), and `change_requests.plugin` already tells request kinds apart (`core/db/models.py`).

## Rulings

| Question | Codex | Opus | Ruling and reason |
|---|---|---|---|
| Trigger | Start, a new `POST /admin/reload`, and every 15 min; a monotonic config-release generation installed in PostgreSQL fences old pods | A recurring worker job `policy_bundle` at start and every 15 min, plus `POST /api/v1/policies/bundles/{env}:propose`; newest process wins | **Opus.** Reload is a separate, unbuilt feature (docs/18). Start already covers every config change because the pods restart, and the 15-minute run covers Git changing under cmapi. A config-release generation system is a large new mechanism the issue does not need. When reload is built, it enqueues the same job |
| Duplicates across replicas | Per-target row lock plus a new open-request index | One pending job (existing index) plus the existing request lock on `(cluster_id='policies', namespace=<env>)` | **Opus.** Both guarantees are already enforced and tested in PostgreSQL |
| Request model | `target_kind` column, nullable `cluster_id` and `namespace`, a `policy_bundle_targets` table, separate `/policies/requests` routes (migration 0007) | A ChangeRequest with `plugin='policies'`, `action='render'`, `cluster_id='policies'`, `namespace=<env>`; no migration; reuse the request routes | **Opus, with Codex's wire-compatibility rule.** `plugin` is the discriminator that already exists. The reserved `cluster_id` keeps the one-open-request-per-env lock with no schema change, and `clusters.yaml` must refuse a cluster named `policies`. From Codex: every namespace-specific consumer (capacity, namespace conflict, the namespace list and portal, notifications) dispatches on `plugin`, and slice S4 proves it |
| Approval | Internal rule `policy-bundle-platform`, one human approver-platform | New optional `policyBundle` section in `approval-rules.yaml` (default 1 from `approver-platform`), thresholds and auto policies never apply | **Opus.** Same outcome, configurable per environment. `required: 0` stays legal as the owner's explicit choice ("approval is the gate") |
| Branch and commit | `cmapi-policy/<instance>/<env>/<rid>`, new trailers on namespace commits too | `cmapi/policies/<rid>`, new trailers `Cmapi-Policy-Env` and `Cmapi-Policy-Bundle` on policy commits only | **Opus.** The branch fits the existing prefix, sweeper, reconciler and the #429 recognizer unchanged. A new trailer on namespace commits would change the reproducible sha of requests in flight across the upgrade (`workspace.py`, `recreate`) |
| Files written | Only renderer-emitted direct children and owned obsolete files, full tree compare, symlink and mode checks | Only marked files and `index.json` of `policies/env/<env>/`, the same preflight as `cmapi-tools policies render`, moved into `core/policysync.py` | **Opus, with Codex's checks.** Also adopted from Codex: a failed Git read is never an empty folder; the changed-path set is verified including deletions, renames and mode changes; `_folder()` must see `index.json` |
| Bundle hash | RFC 8785 canonical JSON of the full documents plus mode and the validator index, versioned | SHA-256 of the sorted `[name, digest]` pairs of the env's generated ValidatingPolicies; null when empty | **Opus, versioned.** The per-policy digest is the one value that exists on all three sides: the render, Git and the cluster. A spec read back from the API server never equals the render (#302 D5), and the index never reaches admission. Mode is inside each document's `validationActions`, so the digest covers it. The hash input gains a format field so it can change later: `sha256(json.dumps({"format": 1, "policies": sorted([name, digest], ...)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False))` |
| What proves the cluster has it | Argo CD Synced and Healthy at a revision, the bundle rebuilt at that commit, and a fresh live compare; without Argo, a platform installer's receipt ConfigMap | Live digests decide (the worker already watches them); Argo CD's `{clusterId}-policies` Application only explains a mismatch | **Opus.** Live digests work for Argo and apply-mode clusters alike, with no new RBAC. Residual risk, from Codex: a hand edit of a live policy that keeps its annotation is invisible to the digest. Only platform administrators can write admission policies, so this is recorded, not designed around |
| Plans while hashes differ | Refuse publication in audit and enforce (409 or 503); hold work already approved | Hold only where the cluster enforces (mode enforce, or any live Deny) unless `current`, or `behind` with the plan also passing the Git bundle; audit publishes and records the state | **Opus.** In audit, admission never refuses, so a mismatch cannot fail a sync, and refusing would stop every write while a policy PR waits for approval. This matches the owner's rule that approval gates and nothing blocks a capability. The hold sits in the worker (`push_branch`, then `pr_checks` before apply or merge), bounded by `policy.bundle.holdTimeout` (24 h), then `policy-bundle-mismatch` |
| Apply mode, no Argo CD | A platform-owned installer with its own identity and a receipt | An opt-in `policy-deliverer` credential used by the apply job | **Opus, default off.** A separate credential that writes only the bundle's policy kinds, never cmapi-reader's or the namespace deliverer's. Without it a cluster stays `behind` and enforce plans hold. Turning it on for CRC is a later deployment step |
| Config repository CI | Fetch trusted release inputs and run `cmapi-tools policies check` in CI | Recompute each marked file's digest; fail a non-cmapi PR that edits a marked file | **Opus.** The config repository holds no `tiers.yaml` or `instance.yaml`, so its CI cannot run `policies check` |
| Superseding | A fresh request for a changed diff; suppression of a rejected proposal persists | Supersede open requests, including `pending_approval` (a new lifecycle edge); same rejected hash not reopened until the render changes or `:propose` | **Opus.** Suppression is derived from the latest request rows, so it survives restarts. From Codex: an explicit veto is distinguished from a transport failure |

## Slices

Opus's eight, in order, each one pull request through /houston-mayday with `review:fable`:

1. **S1** `core/policybundle.py`: `bundle_hash()` (versioned) and the three hashes (rendered, Git with recomputed digests, live); `hashState` on the Policies tab.
2. **S2** Plans record `policyBundle = {env, mode, rendered, git, live, state, checkedAt}`; contract additive.
3. **S3** A `DeliveryTarget` refactor with `NamespaceTarget` only, and `_folder(suffixes)`. No change of behaviour: a golden reproducible commit sha, equal before and after.
4. **S4** `PolicyBundleTarget`, the `policy_bundle` job, `decide_policy`, the new SUPERSEDED edge, the reserved cluster `policies`, the reconciler prefix, `:propose` and `GET /policies/bundles`. Also proves that every namespace-specific consumer dispatches on `plugin`.
5. **S5** Policy `watch_sync`, `delivery.argocd.policiesApplication`, and the opt-in policy deliverer for apply mode.
6. **S6** `bundle_gate` in `push_branch` and `pr_checks`, the `policyBundleState` fact, and `holdTimeout`.
7. **S7** Config-repository CI: recompute digests, and fail a non-cmapi PR that edits a marked file (template, then `cmapi-cluster-configs`).
8. **S8** Metrics, alerts, the tab's hashes and request link, and docs/02, docs/16 and docs/18.

## Not verified

From both designs:
- whether cmapi-reader may `get` a second Argo CD Application in `openshift-gitops`;
- how long old and new worker pods overlap in a rolling update;
- how the portal lists a request whose `cluster_id` is `policies` (S4 must cover it);
- the cost of S4's self-check per offered tier.
