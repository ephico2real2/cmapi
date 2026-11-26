# PR #718 (#716): reviewer 2's report (Opus 5.5 high, 2026-11-26)

Every number below was measured on PostgreSQL 16 at `127.0.0.1:55432/cmapi_r2_718`, unless it says "inferred".
- **Trees:** plain head is `r2-head/`, plain base is `r2-base/`, and the patched tree is `r2-work/`.
- **Final patch:** `r2-outputs/fix.diff`, 571 lines against `head/`. It applies cleanly to a fresh copy of head, and the result matches `r2-work/` exactly, with `examples/` excluded.
- **Separate patches, for separate issues:** `r2-outputs/separate-revert-inverse-policy.diff` and `r2-outputs/separate-exposure-bound-removed.diff`. Each applies to head with `fix.diff` already applied.
- **Measurement test:** `r2-outputs/measure_test_revert_review_718.py`, run on head and on base.

## The design this is judged against (read in full, not reopened)

- **docs/01:260, the state `reverted`:** ":revert on a sync\_failed request; the revert is a new request through the same approval rules". The same row's "Released, so the revert request can take it" is in the **Lock** column, as Codex said. docs/01:258 already shows the reservation `Released` at `sync_failed`.
- **docs/01:238, step 5:** "For a quota increase, the delta is reserved the same way".
- **docs/01:240, step 7:** "When the count is met, capacity is checked again".
- **docs/02:1345, "Beyond the tier":** "A value that differs from the tier's value ... The planner sets the facts beyondTier, beyondTierKeys and networkExposure (the new quota has more services.loadbalancers or services.nodeports than Git holds; for a new namespace, more than the tier gives)".
- **docs/02:1377:** "Namespaces on custom keep their sizable values and their approved beyond-tier values; only the rest of their catalog part re-renders".
- **docs/16:218:** "the namespace-wide hard value is the smallest quantity among unscoped quotas, never their sum".
- **docs/01, "Git cannot bypass cmapi":** "The bot is the only account that can merge under clusters/".
- **Kubernetes v1.34.0,** `staging/src/k8s.io/apiserver/pkg/admission/plugin/resourcequota/controller.go`: `hardResources := quota.ResourceNames(resourceQuota.Status.Hard)` and then `requestedUsage := quota.Mask(deltaUsage, hardResources)`. Admission compares only the resources that `hard` names, so a quota without `services.nodeports` sets no limit on them. Fetched 2026-11-26 from raw.githubusercontent.com. The kubernetes.io Resource Quotas page has no explicit sentence on this.

## Findings: measured on head and on base, and decided

| # | Codex | Head (PostgreSQL) | Base (PostgreSQL) | Scope | Severity | Decision |
|---|---|---|---|---|---|---|
| F1 | Capacity baseline after a failed sync | **Refused** with "cpu would exceed the cluster". Large → small merged, the cluster still holds 32 CPUs and Git holds 8. Head counts 32 + 24 = 56 of 40. The undo of a delete that was not pruned counts 0.125 where the true figure is 0.0625 (8 live + 8) | No check at all | **In scope:** head added the check | Medium. It fails closed: a spurious refusal, or a spurious `capacity == "warn"` approval | **Amend.** Fixed narrowly. Codex's projection is not taken |
| F1b | Undercount (8 live, Git 32, restore 36) | Not reachable from `sync_failed` itself: it needs the live quota to drift below both Git and the restore. The forward planner uses the same "Git delta over the live total" model | n/a | Predates: the forward model | Low | Backlog |
| F2a | A tighter sibling is removed | 0.0% for an effective 8 → 32. Measured only by editing Git out of band | KeyError: no facts | Head computes it, but it is **unreachable**: a cmapi plan never adds a second quota (`several_quotas`), and only the bot merges under clusters/ | Low | **Reject as High.** Backlog |
| F2b | Removing the last NodePort bound | `networkExposure` False | No facts | **Predates.** The forward planner uses the identical comparison: head `pipeline.py:463-464`, `qty(hard.get(k, "0")) > qty(exposure_base.get(k, "0"))` | Medium (approval gap) | **Separate:** `separate-exposure-bound-removed.diff` |
| F3 | Historical annotations | `beyondTier` False when restoring an unannotated 400Gi against today's 200Gi | No facts | **In scope:** head chose annotations, where the forward planner uses `TierCatalog.beyond` | Medium (approval gap) | **Amend.** Fixed with `TierCatalog.beyond`, as the planner uses it |
| F4a | Undo of a delete is an `update` | `dev-change` plus a **spurious** `sensitiveKeyChanged` slot (+1). That slot is head's own: `existing=True` on an empty Git folder | `dev-change`, auto-approved | The action predates. The sensitive slot is head's, but fixing it alone drops the undo to 0 approvals | Medium | **Separate:** `separate-revert-inverse-policy.diff` |
| F4b | Undo of a create: `protected=False`, age 0 | Opens the delete of a protected namespace | Same | Predates: the lines are identical on base | Medium | **Separate** (same diff) |
| F5 | Original team, no tier, no cluster labels | `tier` None, `clusterLabels` None | Same | Predates | Low. No shipped rule reads them for update or delete; they matter for the create auto-approval match after F4a | **Separate** (same diff) |
| F6a | Missing-tier sentinel 0 | `compare("small"@0 → retired)` gives `same` | The old side gives the same | Head changed the new-side line | Low, inside the changed lines | **Accept.** Fixed, with a core test |
| F6b | `beyondTier` null while `beyondTierKeys` is set | Stored `beyondTier` None while the facts list `services.nodeports` | No facts | In scope | Low, inside the changed lines | **Accept.** Fixed |
| (r1) | README misquotes the Lock column as capacity | Text | — | Inside the changed lines | Low | **Accept.** Corrected |

## The fix (`r2-outputs/fix.diff`)

**F1. Size the restore over the live quota.** `restore_facts` sizes the revert over what the cluster commits for the namespace now, not over Git.
- It reads the namespace's figure from the `CapacityLedger`, through a new `namespace_committed(ns)` that uses the ledger's own binding rule (docs/16:218).
- It computes the restored folder's figure with `totals_of(quota_facts(...))`, the same definition.
- The delta it passes is the restored figure minus the live one. It is clamped at 0, as the forward planner clamps.
- With no ledger, it falls back to Git's figure. The check then answers `unknown` anyway.
- There is no change to the `CapacityBackend` port. Codex's `check_restore` and `projected_totals` add a port method and a projection path; that is not needed for the same result.

**F3. Judge beyond-tier values against today's catalog.** For a tier the catalog offers, the restored values go through `TierCatalog.beyond(env, tier, hard, limits_of(LimitRanges))`, which is what `_plan_namespace` calls.
- `TierCatalog.limits_of` is new: the inverse of render for LimitRanges. Only cmapi's own LimitRanges count (`own_limit_range`, made public).
- A tier the catalog no longer offers keeps head's annotation record.
- **Approved values:**
  - on a custom tier, Git's values, so a value the revert keeps unchanged is never asked for again;
  - otherwise, the annotated overrides, as before.

**F6b. Show the approver the restored values.** `restore_facts` now returns the beyond-tier keys. The forward planner's view code becomes `Pipeline.beyond_view(facts, beyond)`, shared by both paths; the forward behaviour is identical. `open_revert` stores the view, so the request carries `beyondTier`.

**F6a. A missing tier ranks below every tier.** In `compare`, a missing tier ranks below every tier: `floor = min(order) - 1` on both sides, as its docstring already said. The docstring's stale `Pipeline.size_restore` is corrected to `restore_facts`.

**Tests, PR test, docs and citations.**
- **New tests:** six in `test_revert_sizing.py` and one in `tests/core/test_tiers.py`.
- **The PR's own helper** now relists the ledger (`relist_quotas`). The fake cluster sends no watch events, so the PR's tests ran with an empty ledger and never included live usage.
- **README:** the Lock-column misquote is corrected.
- **Citations:** `docs/14` and `docs/citations.lock.json` were relocated with `doc-citations.py --relocate`. The patch moves 6 cited lines of `pipeline.py`.

### Source of the fix (complete; the tests are in fix.diff)

```diff
diff -ruN -x examples -x __pycache__ head/cmapi/src/cmapi/core/capacity_ledger.py r2-work/cmapi/src/cmapi/core/capacity_ledger.py
--- head/cmapi/src/cmapi/core/capacity_ledger.py	2026-11-26 04:52:14
+++ r2-work/cmapi/src/cmapi/core/capacity_ledger.py	2026-11-26 05:40:29
@@ -238,6 +238,13 @@
                     self._acc.add(figures, 1)
 
     # ---- reads
+    def namespace_committed(self, namespace: str) -> dict[str, Decimal]:
+        """What one namespace adds to `committed` now, per resource, in cores and bytes: 0 for a resource it does not bound."""
+        with self._lock:
+            figures = self._figures.get(namespace)
+        bounds = figures.bounds if figures else (None, None)
+        return {r: amount(b.hard) if b else Decimal(0) for r, b in zip(RESOURCES, bounds)}
+
     def totals(self) -> LedgerTotals:
         with self._lock:
             return self._acc.totals(self._scoped)
diff -ruN -x examples -x __pycache__ head/cmapi/src/cmapi/core/pipeline.py r2-work/cmapi/src/cmapi/core/pipeline.py
--- head/cmapi/src/cmapi/core/pipeline.py	2026-11-26 04:52:14
+++ r2-work/cmapi/src/cmapi/core/pipeline.py	2026-11-26 05:40:30
@@ -13,6 +13,7 @@
 import json
 from dataclasses import asdict, dataclass, field
 from datetime import date
+from decimal import Decimal
 from typing import Any, Mapping
 
 import yaml
@@ -21,7 +22,7 @@
 from cmapi.core import kube_yaml
 from cmapi.core.approvals import BEYOND_FACTS, ApprovalLedger, Requirement
 from cmapi.core.capacity_backend import SimulatedCapacity
-from cmapi.core.capacity_ledger import binding_hard
+from cmapi.core.capacity_ledger import binding_hard, quota_facts, totals_of
 from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeError
 from cmapi.core.config import InstanceConfig, environment_not_served
 from cmapi.core.db.models import ChangeRequestRow
@@ -39,8 +40,8 @@
 from cmapi.core.ports import CapacityBackend, CapacityResult, Finding, Validator
 from cmapi.core.validate import ValidatorBusy, ValidatorUnavailable
 from cmapi.core.registry import ClusterRegistry
-from cmapi.core.render.manifests import (DELETED, ManifestRenderer, NamespaceSpec, diff_files, folder, objects_of, own_quota,
-                                         plan_hash, quotas_kept)
+from cmapi.core.render.manifests import (DELETED, ManifestRenderer, NamespaceSpec, diff_files, folder, objects_of,
+                                         own_limit_range, own_quota, plan_hash, quotas_kept)
 from cmapi.core.tiers import EXPOSURE_KEYS, QuotaChange, flatten_limits, qty
 from cmapi.plugins.expiration.rules import ExpiryInfo, utc_day, utc_today
 
@@ -464,11 +465,7 @@
         raised = [k for k in sorted(EXPOSURE_KEYS) if qty(hard.get(k, "0")) > qty(exposure_base.get(k, "0"))]
         facts.update({"beyondTier": bool(beyond), "beyondTierKeys": sorted(beyond), "networkExposure": bool(raised)})
         requirement = self._decide(facts)
-        beyond_view = None
-        if beyond:
-            added = self.cfg.approvals.added_for(facts, BEYOND_FACTS)
-            beyond_view = {"keys": [{"key": k, **beyond[k]} for k in sorted(beyond)],
-                           "approvals": [{"group": s.group, "count": s.count, "reason": s.reason} for s in added]}
+        beyond_view = self.beyond_view(facts, beyond)
         return Plan(cluster_id, ns, env, action, "namespaces", spec, files, prev_files, changes, requirement, cap, facts,
                     requester, findings, base_sha, reason=reason, etag=etag, warnings=[f.message for f in findings],
                     beyond_tier=beyond_view, metadata=metadata_view, metadata_diff=metadata_diff, usage=usage_view)
@@ -644,28 +641,47 @@
         return row
 
     def restore_facts(self, cluster_id: str, env: str, ns: str, current: Mapping[str, str | None],
-                      restored: Mapping[str, str | None]) -> tuple[CapacityResult, dict[str, Any], dict[str, Any] | None]:
+                      restored: Mapping[str, str | None]
+                      ) -> tuple[CapacityResult, dict[str, Any], dict[str, Any] | None, dict[str, dict[str, str | None]]]:
         """The approval facts of a revert, which writes back the folder that Git held before a plan: "the revert is a new
         request through the same approval rules" (docs/01, the state reverted). Taken as _plan_namespace takes them for a
         change, from what Git holds now (#710) to what is restored: the capacity check, quotaIncreasePct and tierChange,
         networkExposure, beyondTier, the live usage of a quota that Git holds, and the metadata facts (sensitiveKeyChanged).
-        Raises capacity-exceeded as a plan does."""
-        (old_rq, old_lrs), (new_rq, new_lrs) = ((own_quota(objects_of(f, "ResourceQuota"), ns), objects_of(f, "LimitRange"))
+        Returns the check, the facts, the usage view and the values beyond the tier (beyond_view). Raises capacity-exceeded
+        as a plan does."""
+        (old_rq, old_lrs), (new_rq, new_lrs) = ((own_quota(objects_of(f, "ResourceQuota"), ns),
+                                                 [d for d in objects_of(f, "LimitRange") if own_limit_range(d, ns)])
                                                 for f in (current, restored))
         old_hard, hard = binding_hard(_hard(old_rq) or {}), binding_hard(_hard(new_rq) or {})
-        cpu_delta = float(qty(hard.get("requests.cpu", "0")) - qty(old_hard.get("requests.cpu", "0")))
-        mem_delta = float(qty(hard.get("requests.memory", "0")) - qty(old_hard.get("requests.memory", "0")))
-        cap = self.capacity.check(cluster_id, env, max(cpu_delta, 0), max(mem_delta, 0))
+        # The cluster's commitment holds the quota that the namespace has now. After a failed sync that is Git's, the restored
+        # one or neither, so the restore is sized over the live quota that the ledger counts: over Git's, the revert of a
+        # lowering whose sync did not finish counted the quota still live twice (#718, reviewer 1's H1).
+        committed = totals_of(f for q in objects_of(restored, "ResourceQuota") if (f := quota_facts(q)) is not None).committed
+        live = self._live_committed(cluster_id, ns, current)
+        cap = self.capacity.check(cluster_id, env, max(float(committed["cpu"] - live["cpu"]), 0),
+                                  max(float(committed["memory"] - live["memory"]), 0))
         if cap.status == "exceeded":
             raise Problem.unprocessable("capacity-exceeded", f"{cap.binding_resource} would exceed the cluster",
                                         capacity=dict(cap.detail))
         before, after = (metadata_of(namespace_doc(f)) for f in (current, restored))
         old_tier, tier = before["label"].get("cmapi.net/tier"), after["label"].get("cmapi.net/tier")
-        approved = self.cfg.tiers.rendered_overrides(old_rq, old_lrs)
-        beyond = sorted(k for k, v in self.cfg.tiers.rendered_overrides(new_rq, new_lrs).items()
-                        if k not in approved or qty(approved[k]) != qty(v))
-        facts = {**self.cfg.tiers.compare(env, old_tier, old_hard, tier, hard).facts(),
-                 "capacity": cap.status, "capacityFresh": cap.fresh, "beyondTier": bool(beyond), "beyondTierKeys": beyond,
+        # Beyond the tier as a plan judges it: each restored value that today's tier does not give (TierCatalog.beyond). An
+        # object rendered while the catalog's default was its value names no key in cmapi.net/beyond-tier, so that record
+        # alone missed it (#718, reviewer 1's H3); it is what remains of a tier that the catalog no longer offers. A value
+        # that Git holds on the custom tier now was approved, and one that Git holds unchanged is not asked for again.
+        tiers = self.cfg.tiers
+        offered = {r.name: r for r in tiers.offered(env)}
+        if tier in offered:
+            beyond = tiers.beyond(env, tier, {k: v for k, v in (_hard(new_rq) or {}).items() if k not in ("cpu", "memory")},
+                                  tiers.limits_of(new_lrs))
+        else:
+            beyond = {k: {"tier": None, "requested": v} for k, v in tiers.rendered_overrides(new_rq, new_lrs).items()}
+        custom_before = old_tier in offered and offered[old_tier].custom
+        approved = ({**(_hard(old_rq) or {}), **flatten_limits(tiers.limits_of(old_lrs))} if custom_before
+                    else tiers.rendered_overrides(old_rq, old_lrs))
+        beyond = {k: v for k, v in beyond.items() if k not in approved or qty(approved[k]) != qty(v["requested"])}
+        facts = {**tiers.compare(env, old_tier, old_hard, tier, hard).facts(),
+                 "capacity": cap.status, "capacityFresh": cap.fresh, "beyondTier": bool(beyond), "beyondTierKeys": sorted(beyond),
                  "networkExposure": any(qty(hard.get(k, "0")) > qty(old_hard.get(k, "0")) for k in EXPOSURE_KEYS),
                  **self.cfg.metadata.change_facts(before["label"], after["label"], before["annotation"], after["annotation"],
                                                   existing=True)}
@@ -673,7 +689,27 @@
         if old_hard and (old_hard.keys() != hard.keys() or any(qty(old_hard[k]) != qty(hard[k]) for k in hard)):
             usage_view, usage_facts = plan_usage(self.usage.namespace(cluster_id, ns), old_hard, hard)
             facts.update(usage_facts)
-        return cap, facts, usage_view
+        return cap, facts, usage_view, beyond
+
+    def _live_committed(self, cluster_id: str, ns: str, current: Mapping[str, str | None]) -> dict[str, Decimal]:
+        """What the namespace adds to the cluster's commitment now (CapacityLedger), or, with no ledger to read, what Git's
+        quotas bind: the capacity check then answers unknown whatever the delta."""
+        try:
+            ledger = self.registry.quota_watch(cluster_id)[1]
+        except Problem:
+            ledger = None
+        if ledger is not None:
+            return ledger.namespace_committed(ns)
+        return totals_of(f for q in objects_of(current, "ResourceQuota") if (f := quota_facts(q)) is not None).committed
+
+    def beyond_view(self, facts: Mapping[str, Any], beyond: Mapping[str, Mapping[str, str | None]]) -> dict[str, Any] | None:
+        """What an approver reads of the values beyond the tier (the request's beyondTier): each key, and the approvals that
+        the rules reading beyondTier add for these facts."""
+        if not beyond:
+            return None
+        added = self.cfg.approvals.added_for(facts, BEYOND_FACTS)
+        return {"keys": [{"key": k, **beyond[k]} for k in sorted(beyond)],
+                "approvals": [{"group": s.group, "count": s.count, "reason": s.reason} for s in added]}
 
 
 # The refusals of cmapi's own checks that are a verdict on the request (#302): its names and its expiry. A policy-violation
diff -ruN -x examples -x __pycache__ head/cmapi/src/cmapi/core/render/manifests.py r2-work/cmapi/src/cmapi/core/render/manifests.py
--- head/cmapi/src/cmapi/core/render/manifests.py	2026-11-26 04:52:14
+++ r2-work/cmapi/src/cmapi/core/render/manifests.py	2026-11-26 05:40:30
@@ -123,7 +123,7 @@
     return len(quotas) > 1 or not changes_quota
 
 
-def _own_limit_range(doc: Mapping[str, Any], namespace: str) -> bool:
+def own_limit_range(doc: Mapping[str, Any], namespace: str) -> bool:
     """A LimitRange that cmapi rendered: named <ns>-limits-<resource> (limit_object_name, #253) or the single <ns>-limits of
     before, and carrying the cmapi.net/tier-hash that every rendering of a tier writes (tiers.render; before #253 too). The
     name alone is not enough: a team's own LimitRange may be called <ns>-limits-gpu, and a change would remove it from Git and
@@ -231,7 +231,7 @@
             rendered = {(d["kind"], d["metadata"]["name"]) for d in tier_objects}
             own = own_quota(quotas, spec.namespace)
             kept = [d for d in quotas if d is not own and ("ResourceQuota", _name(d)) not in rendered]
-            kept += [d for d in prev_objects if d.get("kind") == "LimitRange" and not _own_limit_range(d, spec.namespace)
+            kept += [d for d in prev_objects if d.get("kind") == "LimitRange" and not own_limit_range(d, spec.namespace)
                      and ("LimitRange", _name(d)) not in rendered]
         for d in tier_objects:
             d["metadata"]["labels"] = self.keys.ordered(d["metadata"]["labels"])
diff -ruN -x examples -x __pycache__ head/cmapi/src/cmapi/core/tiers.py r2-work/cmapi/src/cmapi/core/tiers.py
--- head/cmapi/src/cmapi/core/tiers.py	2026-11-26 04:52:14
+++ r2-work/cmapi/src/cmapi/core/tiers.py	2026-11-26 05:40:30
@@ -654,6 +654,19 @@
                 if k in asked and not _same(asked[k], mine.get(k))}
 
     @staticmethod
+    def limits_of(limit_ranges: Iterable[Mapping[str, Any]]) -> LimitRange:
+        """The values that rendered LimitRange objects hold, as limits_for gives them: the inverse of render() for limits."""
+        kinds = {api: kind for kind, api in LIMIT_KINDS.items()}
+        out: LimitRange = {}
+        for lr in limit_ranges:
+            for item in (lr.get("spec") or {}).get("limits") or []:
+                kind = kinds.get(item.get("type"))
+                for part in LIMIT_PARTS if kind else ():
+                    for res, value in (item.get(part) or {}).items():
+                        out.setdefault(kind, {}).setdefault(part, {})[res] = str(value)
+        return out
+
+    @staticmethod
     def rendered_overrides(rq: Mapping[str, Any] | None,
                            limit_ranges: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None) -> dict[str, str]:
         """The approved beyond-tier values of a namespace, from its rendered objects: each key that the annotation
@@ -700,7 +713,7 @@
                 new_tier: str | None, new_hard: Mapping[str, str],
                 used: Mapping[str, str] | None = None) -> QuotaChange:
         """current_hard: what Git holds (#710). A tier that is None, or that the catalog no longer has, ranks below every tier,
-        and a key that a side does not hold is 0: a revert restores a folder as Git held it (Pipeline.size_restore)."""
+        and a key that a side does not hold is 0: a revert restores a folder as Git held it (Pipeline.restore_facts)."""
         pct, delta, below = {}, {}, []
         for k in self.sizable:
             old, new = qty(current_hard.get(k, "0")), qty(new_hard.get(k, "0"))
@@ -717,8 +730,10 @@
         elif cur_c:
             change = "from-custom"
         else:
-            o_old = self.file.tiers[current_tier].order if current_tier in self.file.tiers else 0
-            o_new = self.file.tiers[new_tier].order if new_tier in self.file.tiers else 0
+            # Below every tier: an order may be 0 or negative (TierDef.order is any unique int).
+            floor = min((t.order for t in self.file.tiers.values()), default=0) - 1
+            o_old = self.file.tiers[current_tier].order if current_tier in self.file.tiers else floor
+            o_new = self.file.tiers[new_tier].order if new_tier in self.file.tiers else floor
             change = "up" if o_new > o_old else "down" if o_new < o_old else "same"
         return QuotaChange(tier_change=change, increase_pct=pct, delta=delta, below_used=below)
 
diff -ruN -x examples -x __pycache__ head/cmapi/src/cmapi/jobs/open_pr.py r2-work/cmapi/src/cmapi/jobs/open_pr.py
--- head/cmapi/src/cmapi/jobs/open_pr.py	2026-11-26 04:52:14
+++ r2-work/cmapi/src/cmapi/jobs/open_pr.py	2026-11-26 05:40:30
@@ -94,11 +94,11 @@
     facts = {"plugin": "namespaces", "action": action, "environment": row.env, "namespace": row.namespace,
              "clusterId": row.cluster_id, "team": row.team, "automated": True, "reason": "revert",
              "capacity": "fits", "capacityFresh": True, "warnings": []}
-    cap, usage = CapacityResult("fits", True, None, {"source": "revert"}), None
+    cap, usage, beyond = CapacityResult("fits", True, None, {"source": "revert"}), None, {}
     if action == "update":
         # What it writes back is a change of what Git holds now, sized and reviewed as any (#710). capacity-exceeded fails the
         # job as a Git outage does: the transaction is rolled back and the request stays sync_failed.
-        cap, restore_facts, usage = ctx.pipeline.restore_facts(row.cluster_id, row.env, row.namespace, now_files, prev)
+        cap, restore_facts, usage, beyond = ctx.pipeline.restore_facts(row.cluster_id, row.env, row.namespace, now_files, prev)
         facts.update(restore_facts)
     else:
         pods, pvcs = ctx.pipeline.workload_counts(row.cluster_id, row.namespace)
@@ -111,7 +111,8 @@
                                                     client_id="cmapi-worker", employee_id="revert",
                                                     roles=frozenset({"cmapi-onboarding"})), None)
     plan = Plan(row.cluster_id, row.namespace, row.env, action, "namespaces", None, files, now_files, changes, requirement,
-                cap, facts, requester, [], base_sha, reason="revert", usage=usage)
+                cap, facts, requester, [], base_sha, reason="revert", usage=usage,
+                beyond_tier=ctx.pipeline.beyond_view(facts, beyond))
     new = ctx.pipeline.submit(who, plan, repo, jobs, idempotency_key=None, body_fingerprint="revert:" + row.request_id,
                               justification=f"Revert of {row.request_id}")
     repo.event(row, "revert_opened", "worker", new.request_id)
```

## PostgreSQL results

| Run | Base | Head | Fix |
|---|---|---|---|
| `test_revert_sizing.py`, the final version (9 tests) | 9 failed | **4 failed** (F1 failed lowering, F1 undo-delete, F3, F6b), 5 passed | **9 passed** |
| `tests/core/test_tiers.py::test_a_missing_tier_ranks_below_a_tier_of_order_zero` (reference venv) | fail | fail | pass |
| `tests/core`, whole (reference venv) | — | 842 passed, 113 skipped (PR record) | **843 passed, 113 skipped** |
| 22 related service files¹ | — | — | 603 passed, 1 failed (`test_doc_citations`) |

¹ The list is in `r2-outputs/related-files.txt` and the log in `related-work.log`. The run started before the last test and the citation relocation were added.
- **The citation test fails identically on plain head:** the snapshot has no `.git`, and `git ls-files` fails.
- **In git-initialised copies, `doc-citations.py --check`:** head has 0 problems; the fix had 6 moved citations before `--relocate` and 0 after. Both separate trees have 0.
- **After the run:** `test_revert_sizing.py` was rerun alone and passed 9.

**Mutants.** All six were killed (`r2-outputs/mutants.sh`, log in `final-runs.log`):
- **M1, size over Git:** 2 tests fail.
- **M2, annotation only:** the F3 test fails.
- **M3, no approved filter:** the guard fails.
- **M4, no view:** 2 tests fail.
- **M5, floor 0:** the core test fails.
- **M6, live ledger reads 0:** 3 tests fail.

**Equivalent mutant.** Forcing `custom_before=False` is equivalent in every reachable case: approved values are annotated there.

## Separate issues: full code and tests in `r2-outputs/`

1. **`separate-revert-inverse-policy.diff` (F4a, F4b, F5).**
   - **Changes:**
     - Restoring into a folder Git no longer holds is a `create`.
     - `restore_facts` uses `existing = namespace_doc(current) is not None` and the tier's exposure baseline for a create, as the planner does.
     - The undo of a create reads Git's protection labels and the live creation date, as `_plan_delete` does (pipeline.py:585-601).
     - The facts carry the target's `team`, its `tier` (when the action is not a delete) and `clusterLabels`.
   - **Tests:** `test_revert_inverse_policy.py`. 4 fail on fix+head; 13 pass on its tree, with the sizing tests.
   - **Owner decision it implies:** under the shipped rules, the undo of a delete of a `small` dev namespace becomes **auto-approved** by `baseline-rnd-namespace`. That is exactly what a forward create gets. Head requires 1 (the spurious sensitive-key slot); base requires 0.
2. **`separate-exposure-bound-removed.diff` (F2b).**
   - **Change:** `exposure_raised(old, new)` counts the removal of a bound as exposure, in the forward planner and in the revert. A key missing on both sides stays 0, as before.
   - **Tests:** `test_exposure_bound_removed.py` covers a forward re-render and a revert. 2 fail on fix+head; on its tree they pass, 37 with the drift and custom-tier files and 11 with the sizing file.

**Applying both:** A and B conflict on one line of `restore_facts` when both are applied. The merged line is `"networkExposure": bool(exposure_raised(exposure_base, hard)),`.

## What Codex missed

1. **The undo of a delete is the common double count.** A delete's `sync_failed` leaves the namespace live, because prune waits for an operator. Head counted it 0.125 against a true 0.0625. Codex's H1 measured only the update path.
2. **Head itself added a sensitive-key approval to every undo of a delete:** `existing=True` over an empty folder adds "Sensitive key changed" +1, where base had none. Codex's patch changes this without saying that head introduced it. Fixing it alone would make the undo a 0-approval change, which is weaker than head, so it belongs with F4a.
3. **The PR's tests ran with an empty capacity ledger:** the fake cluster sends no watch events. Their capacity numbers never included live usage. The patch relists explicitly.
4. **The beyond-tier view's approvals also list "Network exposure":** `BEYOND_FACTS` includes `networkExposure` (approvals.py:70). Codex's view test checked only the keys.
5. **Citation drift:** any patch to `pipeline.py` moves 6 citations in docs/14. Codex could not run the check. It was run here in git-initialised copies and relocated.
6. **Backlog, inferred from code and not measured:**
   - A revert that **lowers** a quota on a cluster already over 100% is refused, because the delta is clamped at 0. The forward planner refuses a decrease the same way.
   - The revert's 10-second Thanos read (`usage.py:53`) now runs inside the worker transaction that holds the parent's row lock. It is bounded, and the forward planner reads it outside any transaction.
7. **Codex's patch shape:**
   - It adds a `CapacityBackend` protocol method and a projection path through `read_quotas`.
   - It takes `max(quotaIncreasePct)` across two baselines, which changes the fact's meaning.
   - It bundles the predating F4 and F5.
   - Its 24 tests are Mock-based, with no PostgreSQL.
   - Its H1 fix is not wrong. The narrower ledger read reaches the same result, with tests on PostgreSQL.

## Five-line summary
1. F1 amended (Medium; live-ledger delta, not Codex's port change); F3 amended (Medium; `TierCatalog.beyond`); F6a, F6b and the README Lock-column quote accepted (Low).
2. F2a rejected as High: unreachable through cmapi, Low and Backlog. F2b, F4 and F5 predate head: separate diffs with tests; F4's diff auto-approves an undone delete of a small dev namespace, an owner call.
3. Codex missed: the undo-delete double count; head's spurious sensitive-key approval; the PR tests' empty ledger; exposure in the beyond view; the 6 citation moves.
4. Final patch `r2-outputs/fix.diff` (571 lines) applies cleanly to head and reproduces the tested tree.
5. PostgreSQL: `test_revert_sizing` base 9 failed, head 4 failed and 5 passed, fix 9 passed; core 843 passed; 22 related files 603 passed (the 1 failure fails on head too, as the snapshot has no `.git`); 6 of 6 mutants killed.
