# #710: a change of a tier-outdated namespace is sized from what Git holds, not from the catalog

- **Implementer:** Opus 5.5 high (all code, tests and this record).
- **Review:** two reviewers (reviewer 1 Codex, reviewer 2 a separate Opus 5.5 high). The defect is an approval bypass, so it
  is security, and the rule of 2026-11-25 for one reviewer does not apply.
- **Parent:** story #22. Found by reviewer 2 of PR #707. Same class as #685 (PR #682).

## What was wrong, measured on main 2992944 (PostgreSQL 16, the service suite's fakes)

`Pipeline._plan_namespace` took the old quota of a named tier from the catalog: `old_hard =
self.cfg.tiers.quota_for(env, old_tier)`. Git held what an older catalog had rendered. The capacity delta, `quotaIncreasePct`
and `tierChange` were computed against the catalog's values. So a change that rendered the tier again was sized as if
nothing had changed. A label change does render it again. Measured by the "before" run, with `cmapi/src` stashed:

1. **Label change, Git `requests.cpu: 1`, catalog 8.** The plan wrote 8. The capacity check got the delta (0, 0),
   `quotaIncreasePct` was 0, and the change was auto-approved (`approved`, no slot). Reviewer 2's probe.
2. **Tier move small to medium from Git's 1 CPU.** The capacity delta was 8 CPUs (catalog 8 to 16), not 15.
   `quotaIncreasePct` was 100, under the `> 100` threshold, where Git's 1 to 16 is 1500.
3. **Label change, Git twice the catalog on every sizable key.** `quotaIncreasePct` was 0, not -50.
4. **A Namespace that names no tier.** Git holds `<ns>-quota` at 1 CPU, and the change renders tier small. The capacity
   delta was 8 (the whole quota). The plan had no `quotaIncreasePct` at all, so it was auto-approved.
5. **Network exposure on a Namespace that names no tier.** The base was the catalog (`resolved.quota`). A catalog that now
   gives a load balancer, against Git's 0, opened no `networkExposure` approval. With a tier label the base was already
   Git's quota.

#707's usage gate already compared with Git (`previous = old_quota or {}`).

## Sources, read on 2026-11-26

- The design, docs/02, "Changing a tier": "A PR to tiers.yaml (approver-platform in CODEOWNERS) changes no namespace by
  itself; after the rollout, namespaces whose cmapi.net/tier-hash differs show as tier-outdated. [...] It opens one ordinary
  update request per outdated namespace: the plan diff shows old and new values, increases go through the capacity check and
  reserve the delta, a decrease below current use is skipped and listed in the operation report, and the approval rules apply
  as for any quota change." docs/01, "Tiers live in cmapi", says the same: "the tiers-rerender operation opens one request per
  affected namespace, in batches, through the normal approval rules."
- The adoption design, D9 (docs/reviews/2026-11-14-issue-26-adoption/README.md): "Any other request, a change of a label for
  example, leaves every object unchanged." D9 is about adopted objects (a namespace on tier `custom` whose quota cmapi did not
  render). #250's decision 3 applies it to ResourceQuotas that are not cmapi's. Neither D9 nor "Changing a tier" says that a
  change must not render cmapi's own `<ns>-quota` again. The re-render is "an ordinary update request", which the operation
  that is not built yet will open. So a change still renders the tier, as before, and this fix does not reopen that.
- Kubernetes, "Resource Quotas"
  (<https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/policy/resource-quotas.md>): "the
  quota system tracks usage to ensure it does not exceed hard resource limits defined in a ResourceQuota." The limit in force
  is the object's `spec.hard`, which is the object Git holds once it is synced. cmapi's capacity ledger counts the same
  object from the watch cache (`core/capacity_backend.py`).
- Argo CD, "Overview" (<https://raw.githubusercontent.com/argoproj/argo-cd/master/docs/index.md>): "Argo CD follows the
  **GitOps** pattern of using Git repositories as the source of truth for defining the desired application state", and it
  "compares the current, live state against the desired target state (as specified in the Git repo)."

## Decisions

1. **The baseline is Git.** For every change, `old_hard` is the `spec.hard` of the quota that the change acts on. That is
   `own_quota`, as Git holds it, or `{}` when Git holds none. A create has nothing in Git, so its baseline stays `{}`. The
   capacity delta, the usage read (#707), `compare` (`quotaIncreasePct`, `tierChange`) and `networkExposure` all read that
   one baseline. Rejected: keeping the catalog as the baseline and adding a "tier-outdated" approval rule. That would add a
   rule the design does not have, and it would still size the capacity delta from the catalog.
2. **A change renders the tier again, sized as a quota change.** It is not frozen at Git's values. "Changing a tier" opens
   "an ordinary update request" for an outdated namespace, so an ordinary update is the re-render. Keeping Git's quota on a
   label change would need a new request kind for the operation, which is a design change. A raise goes through the capacity
   check and `quotaIncreasePct`. A decrease reserves nothing, and its `quotaIncreasePct` is negative.
3. **No quota in Git is a write from nothing.** `compare` already gives 100% for each key with an old value of 0. The
   fallback `old_hard or hard` made such a write 0% while the capacity check reserved all of it. It is removed.
4. **A Namespace that names no tier gets the same facts.** `compare` runs for every change that is not a create. A Namespace
   with no `cmapi.net/tier` that the change does not move is rendered on `tier` (`moved` is false), so its `tierChange` is
   from `tier`. A move from no tier ranks the old tier below every tier, as `compare` already did for a tier the catalog no
   longer has.

## Tests

`cmapi/tests/service/test_catalog_drift_710.py`, 7 cases, PostgreSQL 16 at `127.0.0.1:55432`, database `cmapi_impl_710`.

- **Before** (`cmapi/src` stashed in the worktree): 5 failed, 2 passed. The two that pass are guards, and they pass on
  purpose: no drift (Git equals the catalog), and network exposure with a tier label, whose base was already Git.
- **After:** 7 passed (8 with reviewer 2's fallback case).
- **Related service suites:** 17 files, including `test_multidoc_quota_250`, `test_usage_verdicts_310`,
  `test_usage_review_707`, `test_api_contract`, `test_flow`, `test_custom_tier_change` and `test_doc_citations`. Result:
  480 passed and 1 failed. The failure was `test_doc_citations`: the run started before `--relocate` moved two docs/14
  citations of `pipeline.py` (`:529` to `:533`, `:613` to `:617`). Each target was read and still says what docs/14
  cites. Run again after `--write`, 12 passed.
- **tests/core** (the reference venv, no structlog): 818 passed, 113 skipped.

The runs are in `workbench/cmapi/wt-710-outputs/` (`before.txt`, `after.txt`, `suites-after.txt`, `core-after.txt`).

## Behaviour that changed beyond the defect

- A change of a namespace whose Git folder holds no quota, but whose Namespace names a tier, now has `quotaIncreasePct` 100
  (a write from nothing), where it was 0. The capacity delta was already the whole quota.
- A change of a namespace whose Namespace names no tier now has `quotaIncreasePct` and `tierChange`, and its capacity delta
  and `networkExposure` are from Git's quota. Before, the plan had no `quotaIncreasePct` and `tierChange`, the capacity
  delta was the whole new quota, and `networkExposure` compared with the catalog.

## Not changed, and filed

- `quotaBelowRequested` is still always false. `compare` gets no usage. That is #256, open.
- `examples/local/app.py`, the local reference app, still takes the old quota from the catalog. It has an in-memory store and
  is never deployed. Filed as #713 (Low, Backlog).

## Review and the coordinator's rulings (2026-11-26)

**Reviewers.**
- **Reviewer 1:** Codex gpt-6.2-astra xhigh (`review/reviewer-1-codex.md`). Its sandbox could not reach PostgreSQL.
- **Reviewer 2:** Opus 5.5 high, on PostgreSQL 16.15 (`review/reviewer-2-opus.md`).

**The PR's change is correct.** All seven Codex findings predate it: each measured the same on base. The rulings:

- **In this PR:**
  - reviewer 2's PostgreSQL case for a quota Git does not hold, which catches a revived `old_hard or hard` fallback that the PR's own 7 cases missed;
  - **#715 (Medium):** short names are normalised, `binding_hard`, per docs/16:219-220;
  - **Codex M1 (Low, in the changed lines):** a first quota does not read live usage (docs/01:42).
- **Separate issue, next:** **#716 (Medium):** the revert gets the same capacity check and approval facts (docs/01:260). Reviewer 2's patch is saved in `workbench/cmapi/pending-716/`.
- **Rejected:** Codex H3. A create over a stray file is sized and approved as a create, so nothing is bypassed.
- **Backlog:** #717.

**Records:** the docs/02 sentence is edited in the export only. The live Claude Doc needs the same edit, and the coordinator tracks it in `LIVE-DOCS-PENDING.md`.

**Run:**
- the drift, short-name, first-quota, #250, #707, #310, custom-tier, contract, flow and citation tests: **149 passed**;
- `tests/core` in the reference venv: **818 passed, 113 skipped**.
