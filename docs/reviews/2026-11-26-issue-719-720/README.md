# #719 and #720: the revert's inverse policy, and a removed exposure bound

Both predate today's work. Codex found them in the review of PR #718 (findings 4, 5 and 2b). Reviewer 2 of #718 (Opus 5.5 high) measured them on PostgreSQL 16, and wrote the fixes and tests (`origin-reviewer-2-of-718.md`). The coordinator applied both on main `e500176`. Their one shared line takes the merged form reviewer 2 gave: `"networkExposure": bool(exposure_raised(exposure_base, hard))`.

**#719.** docs/01:260: "the revert is a new request through the same approval rules". So:
- the undo of a delete is judged as a create;
- the undo of a create is judged as any delete, so a protected namespace refuses it and the namespace's age counts;
- the facts carry the restored team, tier and cluster labels.

**Coordinator's ruling:** with the shipped rules, undoing the delete of a `small` dev namespace is auto-approved, as a forward create is. Main also gave 0 approvals.

**#720.** Removing the last `services.nodeports` or `services.loadbalancers` bound counts as network exposure, in the forward planner and in the revert. Kubernetes limits only what a quota names (v1.34.0 resourcequota `controller.go`, `quota.Mask(deltaUsage, hardResources)`), and docs/02:1345 compares against what Git holds.

**Tests:**

| Run | Result |
|---|---|
| main (without the fixes) | the 6 new tests fail |
| fix | the 6 pass |
| revert, drift, custom tier, recovery, delivery, short names, contract and citation tests | 129 passed |
| `tests/core` in the reference venv | 843 passed, 113 skipped |

**Review:** reviewer 2 of #718 (Opus) wrote it, so it is reviewed by Codex.
