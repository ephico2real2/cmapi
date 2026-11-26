# #719 and #720: the revert's inverse policy, and a removed exposure bound

Both predate today's work. Codex found them in the review of PR #718 (findings 4, 5 and 2b). Reviewer 2 of #718 (Opus 5.5 high) measured them on PostgreSQL 16, and wrote the fixes and tests (`origin-reviewer-2-of-718.md`). The coordinator applied both on main `e500176`. Their one shared line takes the merged form reviewer 2 gave: `"networkExposure": bool(exposure_raised(exposure_base, hard))`.

**#719.** docs/01:260: "the revert is a new request through the same approval rules". So:
- the undo of a delete is judged as a create;
- the undo of a create is judged as any delete, so a protected namespace refuses it and the namespace's age counts;
- the facts carry the restored team, tier and cluster labels.

**Coordinator's ruling:** with the shipped rules, undoing the delete of a `small` dev namespace is auto-approved, as a forward create is. Main gave it 1 approval, by accident: it judged the revert as a change (`dev-change`, 0) and counted the restored `cmapi.net/team` as a sensitive key changed (+1 `approver-platform`). Measured by reviewer 2 of #722 on PostgreSQL 16.

**The restore judged as a create also carries a create's other inputs** (reviewer 2 of #722): the validator's findings, so the guard "when the plan has warnings" (docs/01) holds; the expiry, whose lifetime counts from the namespace's creation on the cluster (`expirationBeyondLimits`); and no `tierChange` or `quotaIncreasePct`, which a create does not have.

**#720.** Removing the last `services.nodeports` or `services.loadbalancers` bound counts as network exposure, in the forward planner and in the revert. Kubernetes limits only what a quota names (v1.34.0 resourcequota `controller.go`, `quota.Mask(deltaUsage, hardResources)`), and docs/02:1345 compares against what Git holds.

**Tests:**

| Run | Result |
|---|---|
| main (without the fixes) | the 6 new tests fail |
| fix | the 6 pass |
| revert, drift, custom tier, recovery, delivery, short names, contract and citation tests | 129 passed |
| `tests/core` in the reference venv | 843 passed, 113 skipped |

**Review:** reviewer 2 of #718 (Opus) wrote it, so it is reviewed by Codex.

## Review and the coordinator's rulings (2026-11-26)

**Reviewers.**
- **Reviewer 1:** Codex gpt-6.2-astra xhigh. Its sandbox could not reach PostgreSQL.
- **Reviewer 2:** Opus 5.5 high, on PostgreSQL 16 (`review/`).

**Correction.** Above, "Main also gave 0 approvals" was wrong, and the coordinator retracts it (see #719). Measured on base: the revert of the delete of a small dev namespace was `dev-change` with 1 approver-platform slot ("Sensitive key changed"). This PR makes it `dev-create`, auto-approved, as the forward create is (docs/01:260). That is a deliberate loosening by the design, and the owner was told.

**Measured on the PR's first head:** three cases were looser than base.
- With a validator warning: auto-approved, against 1 on base.
- With an expiry 200 days out: auto-approved, against 1 on base.
- With the cluster moved from dev to rnd: auto-approved as `dev-create`, against 1 under dev on base.

Docs/01:534 (warnings go to humans) and :544 (beyond the expiry limits, or making a namespace permanent, adds approver-platform) require approvals in those cases. **So both reviewer 2 patches land here**, and no case is looser than base:
- **`fix.diff`:**
  - the restored create is validated, and its warnings reach the plan (M1);
  - `ExpirationRules.plan_restore` counts the lifetime from the namespace's creation on its cluster, with none of the create-time refusals (M4, the create path);
  - the change-only facts are dropped on a create (M2);
  - three tests cover gaps in the PR's own tests.
- **`separate-revert-hardening.diff`:**
  - a revert is refused when the cluster's environment is no longer `row.env`, when writes are off, or when the plugin is not offered (H2);
  - warnings and expiry approvals also apply on the update path.

**Rejected:**
- **H1:** reachable only by hand-editing Git (docs/01:262).
- **M3:** consistent with base and the per-quota design; it errs on the safe side.
- **M5:** Codex's `team: None` would skip the daily allowance.

**Tests on PostgreSQL:** reviewer 2 ran 195 with `fix.diff` and 199 with both patches, catching 7 of 7 mutants; `tests/core` gave 843 passed.
