# Reviewer 1 — export 869fc29 against 418e934

Decision record read first. Review complete; all five findings below have failing core regressions and verified fixes. No service tests, containers, clusters, database connections, or network services are used.

TokenSave cannot inspect this export: it is not an initialized project. Local source inspection is used without creating an index. System `python3` has no pytest; an isolated `.review-venv` inside this folder supplied the test dependencies. The unmodified core suite passes: **166 passed**.

All line numbers in findings and the claim table refer to the **unmodified export**. Candidate diffs are independent fixes against that export; F4/F5 share the quantity fix and F2/F5 share an in-memory test helper. Use the cumulative patch at the end to apply every change together without overlapping hunks. Reviewed application and test files are restored to their exported bytes after verification; this report is the deliverable.

| Claim | Result | Evidence in the export |
|---|---|---|
| C1 | Refuted: F5 | `tiers.py:45,78-80,499`; `pipeline.py:289-294`: precision loss can hide an actual quantity change before `decide`. |
| C2 | Confirmed for inspected request paths | `pipeline.py:238-245`: approved values come only from Git's quota/limit documents, only for an old custom tier; `metadata.py:78-80,109-111` and `metadata-keys.yaml:3-4` reject spoofed labels/annotations. |
| C3 | Policy guard confirmed; owner rule violated: F1 | `approvals.py:190-193` requires literal `True` for a beyond-tier policy, but `170-174` can still return `none-required`. |
| C4 | Confirmed | `pipeline.py:353-369` reuses `plan.facts` and stores the rendered spec/files; `open_pr.py:19-24,35-47` reconstructs them and checks the hash before opening a PR. |
| C5 | Refuted: F5 | `tiers.py:404-405` checks the same key, but `_same` can incorrectly call two different quantities equal. |
| C6 | Numeric ordering/quota checks confirmed for the reference catalog; overall claim refuted: F3 | `tiers.py:470-484` sorts every kind/resource and checks container max against requests quota; ordering alone misses the Kubernetes GPU default-equality rule. |
| C7 | Refuted: F2 | `pipeline.py:291-292`: network exposure is restricted to new beyond-tier keys, missing increases back to a tier default or inherited through a tier transition. |
| C8 | Refuted: F4 | `tiers.py:407,463,577` propagate a non-`TierError` for well-formed supported Kubernetes quantities such as `4e0`; the ordinary catalog edge cases below do not crash. |
| C9 | Confirmed for the compatibility matrix | Base `418e934` reconstructed locally by reversing `change.diff`. Thirty original-export/base plans match exact file strings, hashes, approval requirements, and legacy facts: every environment/tier create (20), plus named-tier size/metadata changes (10). Custom input quota order was reversed. |

Paths abbreviated in the table: `tiers.py`, `pipeline.py`, `approvals.py`, `metadata.py` are under `cmapi/src/cmapi/core/`; `open_pr.py` is under `cmapi/src/cmapi/jobs/`; `metadata-keys.yaml` is `examples/cluster-configs/policies/metadata-keys.yaml`.

## F1 — P1: `none-required` bypasses the beyond-tier approval gate (C3)

`cmapi/src/cmapi/core/approvals.py:170-174` returns `auto="none-required"` when an environment's action count is zero and no threshold adds a slot, even with `beyondTier=True`. `_auto`'s guard (lines 190-193) only stops `auto:<policy>`; it cannot stop this separate automatic approval path. A dev PATCH can therefore receive a new beyond-tier value without a human approval if the instance removes the threshold. This breaks the owner's rule, including the requirement for an *extra* approval on top of a nonzero environment rule. A fallback beyond-tier slot must be independent of the presence of the configured threshold, while an explicit eligible `match.beyondTier: true` policy can still authorize automatic approval.

Reproduced directly: `ApprovalRules({'environments': {'dev': {'required': 0}}}).decide({'environment': 'dev', 'action': 'update', 'beyondTier': True})` returns no slots and `auto='none-required'`.

Regression: `test_review_beyond_tier_needs_an_extra_slot_without_threshold` (four parameter cases). Each fails on the export and passes with this fix. The existing no-threshold test is updated from one approver to two to enforce an extra approval above the environment rule.

Complete candidate fix and regression against this export (existing test files only):

```diff
--- a/cmapi/src/cmapi/core/approvals.py
+++ b/cmapi/src/cmapi/core/approvals.py
@@ -121,8 +121,19 @@
 
     def added_for(self, facts: Mapping[str, Any], names: frozenset[str]) -> list[Slot]:
         """The approvers that the thresholds reading one of the named facts add for these facts, one slot for each rule."""
-        return [Slot(t.get("group", self.defaults["group"]), int(t.get("add", 1)), t.get("reason") or expr.source)
-                for expr, t in self.thresholds if expr.names() & names and expr(facts)]
+        slots = [Slot(t.get("group", self.defaults["group"]), int(t.get("add", 1)), t.get("reason") or expr.source)
+                 for expr, t in self.thresholds if expr.names() & names and expr(facts)]
+        fallback = self._beyond_fallback(facts)
+        if fallback and names & {"beyondTier", "beyondTierKeys"}:
+            slots.append(fallback)
+        return slots
+
+    def _beyond_fallback(self, facts: Mapping[str, Any]) -> Slot | None:
+        if facts.get("beyondTier") and not any(
+                expr.names() & {"beyondTier", "beyondTierKeys"} and expr(facts) and int(t.get("add", 1)) > 0
+                for expr, t in self.thresholds):
+            return Slot(self.defaults["group"], 1, "Value beyond the tier")
+        return None
 
     # ---- decide
     def decide(self, facts: Mapping[str, Any], *, paused: bool = False,
@@ -154,6 +165,11 @@
                 slots.append(Slot(g, int(t.get("add", 1)), t.get("reason") or expr.source))
                 reasons.append(f"threshold {expr.source}: +{t.get('add', 1)} {g}")
                 added = True
+        beyond_fallback = self._beyond_fallback(facts)
+        if beyond_fallback:
+            slots.append(beyond_fallback)
+            reasons.append("Value beyond the tier: +1 " + beyond_fallback.group)
+            # _auto still permits a policy explicitly covering beyondTier when no configured rule added a slot.
         merged: dict[str, Slot] = {}
         for s in slots:
             m = merged.get(s.group)
--- a/cmapi/tests/core/test_approvals.py
+++ b/cmapi/tests/core/test_approvals.py
@@ -99,7 +99,7 @@
     raw["thresholds"] = [t for t in raw["thresholds"] if t["when"] not in ("beyondTier", "networkExposure")]
     f = facts(environment="rnd", namespace="payments-rnd", tier="small", beyondTier=True, beyondTierKeys=["requests.storage"])
     r = ApprovalRules(raw, ALL_ENVS).decide(f)            # no threshold adds an approver, and still no auto-approval
-    assert r.auto is None and r.auto_fallback == "beyond-tier" and [(s.group, s.count) for s in r.slots] == [("approver-platform", 1)]
+    assert r.auto is None and r.auto_fallback == "beyond-tier" and [(s.group, s.count) for s in r.slots] == [("approver-platform", 2)]
     next(p for p in raw["autoApproval"]["policies"] if p["name"] == "baseline-rnd-namespace")["match"]["beyondTier"] = True
     assert ApprovalRules(raw, ALL_ENVS).decide(f).auto == "auto:baseline-rnd-namespace"
     # with the reference rules the threshold stops it first, and the guard that is named is the specific one
@@ -265,3 +265,19 @@
            "autoApproval": {"enabled": True, "policies": [{"name": "p", "match": {"plugin": "namespaces", "actions": ["create"], "environments": ["*"]}}]}}
     req = ApprovalRules(raw, {"prod"}, group_path="/corp/{name}").decide(facts(), paused=True)
     assert req.slots and req.auto_fallback == "paused" and req.token_group("approver-prod") == "/corp/approver-prod"
+
+
+@pytest.mark.parametrize("base", [0, 1])
+@pytest.mark.parametrize("auto", [False, True])
+def test_review_beyond_tier_needs_an_extra_slot_without_threshold(base, auto):
+    raw = {"environments": {"dev": {"change": base}},
+           "autoApproval": {"enabled": auto, "policies": [{"name": "ordinary", "match": {}}]}}
+    rules = ApprovalRules(raw)
+    f = facts(environment="dev", action="update", tier="custom", beyondTier=True)
+    req = rules.decide(f)
+    assert req.auto is None
+    assert req.total == base + 1
+    assert [(s.group, s.count) for s in rules.added_for(f, BEYOND_FACTS)] == [("approver-platform", 1)]
+    raw["autoApproval"]["policies"][0]["match"]["beyondTier"] = True
+    if auto:
+        assert ApprovalRules(raw).decide(f).auto == "auto:ordinary"
```

## F2 — P1: raising network quota to a tier default misses the exposure approval (C7)

`cmapi/src/cmapi/core/pipeline.py:291-292` computes `raised` only from `beyond`. Returning an approved lower network quota to the tier's nonzero value removes the key from `beyond`, so a real increase produces `networkExposure=False`. A named-to-custom transition that inherits a larger network default, and a custom-to-named transition, have the same problem. With a zero-approver dev change rule this can remove the only required approval. Compare the effective new `hard` network keys directly with the ResourceQuota in Git (or the resolved tier for a create), independently of beyond-tier classification.

Three in-memory core regression cases fail before the fix: custom nodeports 0 -> tier default 1; small nodeports 0 -> custom default 1; custom nodeports 0 -> small default 1. Each produces the expected new quota but `networkExposure=False`. No service fixture or database was used.

Complete candidate fix and regression against this export (existing test files only):

```diff
--- a/cmapi/src/cmapi/core/pipeline.py
+++ b/cmapi/src/cmapi/core/pipeline.py
@@ -288,8 +288,9 @@
         # was approved before is not beyond the tier again.
         beyond = {k: v for k, v in self.cfg.tiers.beyond(env, tier, hard, limit_range).items()
                   if k not in approved or qty(approved[k]) != qty(v["requested"])}
-        raised = [k for k, v in beyond.items()
-                  if k in EXPOSURE_KEYS and qty(v["requested"]) > qty(approved.get(k) or v["tier"] or "0")]
+        exposure_baseline = (old_quota or {}) if old_tier else resolved.quota
+        raised = [k for k in EXPOSURE_KEYS
+                  if qty(hard.get(k, "0")) > qty(exposure_baseline.get(k, "0"))]
         facts.update({"beyondTier": bool(beyond), "beyondTierKeys": sorted(beyond), "networkExposure": bool(raised)})
         requirement = self._decide(facts)
         beyond_view = None
--- a/cmapi/tests/core/test_tiers.py
+++ b/cmapi/tests/core/test_tiers.py
@@ -295,3 +295,49 @@
         c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "60Gi"}}}, SIZES)          # the tier's max is 50Gi
     assert e.value.code == "limit-order-invalid" and e.value.data["kind"] == "pvc"
     assert c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "1Gi"}}}, SIZES)["pvc"] == {"max": {"storage": "50Gi"}, "min": {"storage": "1Gi"}}
+
+
+def _review_pipeline(catalog, *, tier="custom", quota=None):
+    """Only in-memory ports: no database, API server, HTTP client, or worker."""
+    from types import SimpleNamespace as NS
+    from cmapi.core.config import load_instance
+    from cmapi.core.pipeline import Pipeline
+    from cmapi.core.ports import CapacityResult
+    from cmapi.core.render.manifests import NamespaceSpec
+    from conftest import person
+    cfg = load_instance(HERE / "instances/nonprod", HERE / "cluster-configs/policies/metadata-keys.yaml")
+    cfg.tiers = catalog
+    cache = NS(namespace=lambda ns: None)
+    registry = NS(writable=lambda cid: NS(policy=NS(environment="dev", labels={})), cache=lambda cid: cache)
+    git = NS(read_folder=lambda path: (previous, "base"))
+    pipe = Pipeline(cfg, registry, git, NS(validate=lambda *a: []),
+                    NS(check=lambda *a: CapacityResult("fits", True, None, {})), None, [])
+    spec = NamespaceSpec("review-dev", "CRC", "nonprod", "dev", tier, "old", "ola", "ola@ephico2real.com",
+                         labels={"cmapi.net/team": "payments"},
+                         annotations={"cmapi.net/team-dl": "payments@ephico2real.com"},
+                         quota=(quota or SIZES) if tier == "custom" else None)
+    previous = pipe.renderer.render(spec)
+    who = person("ola", roles={"cmapi-requester"})
+    return pipe, who, previous
+
+
+
+@pytest.mark.parametrize("old_tier,old_network,new_tier,new_network", [
+    ("custom", "0", "custom", "1"),  # return from a lower approved value to a nonzero tier default
+    ("small", "0", "custom", None),  # named -> custom inherits a higher default
+    ("custom", "0", "small", None),  # custom -> named inherits a higher default
+])
+def test_review_network_exposure_uses_git_even_when_new_value_equals_tier(old_tier, old_network, new_tier, new_network):
+    from cmapi.core.pipeline import folder_etag
+    r = raw()
+    r["defaults"]["quota"]["services.nodeports"] = "1"
+    r["tiers"]["small"]["quota"]["services.nodeports"] = "0" if old_tier == "small" else "1"
+    c = TierCatalog(r, ALL)
+    pipe, who, previous = _review_pipeline(c, tier=old_tier, quota={**SIZES, "services.nodeports": old_network})
+    body = {"namespace": "review-dev", "tier": new_tier}
+    if new_tier == "custom":
+        body["quota"] = {**SIZES, **({"services.nodeports": new_network} if new_network else {})}
+    plan = pipe.plan_namespace(who, "CRC", body, action="update", if_match=folder_etag(previous))
+    assert plan.facts["networkExposure"] is True
+    assert plan.requirement.total >= 1
+
```

## F3 — P2: ordered GPU defaults can still produce an invalid LimitRange (C6)

`cmapi/src/cmapi/core/tiers.py:470-475` only compares the numeric order of the four parts. A valid catalog can list `limitRange.container.defaultRequest.nvidia.com/gpu` and `limitRange.container.default.nvidia.com/gpu` as overridable, both bounded at 4. A request for defaultRequest=1 and default=2 passes the order check and renders an invalid LimitRange. Kubernetes requires matching defaults for resources that cannot be overcommitted; see [ValidateLimitRange](https://github.com/kubernetes/kubernetes/blob/master/pkg/apis/core/validation/validation.go) and its `IsOvercommitAllowed` check. The API server rejects this object after the approval and Git workflow. The core regression expecting `TierError` fails with `DID NOT RAISE`.

The fix enforces equality for non-overcommittable container resources in both request-time validation and catalog validation, while preserving the permitted CPU/memory ordering. The reference catalog has no GPU keys; this finding concerns the explicitly catalog-driven extension mechanism.

Regression tests: `test_review_non_overcommittable_limit_defaults_must_match` and `test_review_catalog_rejects_unequal_non_overcommittable_defaults`. Both fail on the export and pass with this fix.

Complete candidate fix and regression against this export (existing test files only):

```diff
--- a/cmapi/src/cmapi/core/tiers.py
+++ b/cmapi/src/cmapi/core/tiers.py
@@ -78,6 +78,14 @@
 def _same(a: str | None, b: str | None) -> bool:
     """Two quantities are the same amount: "1" and "1000m" are, a missing value and a value are not."""
     return (a is None and b is None) or (a is not None and b is not None and qty(a) == qty(b))
+
+
+def _unequal_non_overcommittable_defaults(parts: Mapping[str, Mapping[str, str]]) -> list[str]:
+    """Match Kubernetes IsOvercommitAllowed: native resources except hugepages can overcommit."""
+    defaults, requests = parts.get("default", {}), parts.get("defaultRequest", {})
+    return sorted(res for res in defaults.keys() & requests.keys()
+                  if (res.startswith("hugepages-") or ("/" in res and "kubernetes.io/" not in res))
+                  and not _same(defaults[res], requests[res]))
 
 
 # --------------------------------------------------------------------------- errors
@@ -315,6 +323,9 @@
                                 p.append(f"{where}: limitRange.{kind}.{part}.{k}: {exc}")
                 if len(p) > before:
                     continue
+                for kind, parts in lr.items():
+                    for res in _unequal_non_overcommittable_defaults(parts):
+                        p.append(f"{where}: {kind} {res} defaultRequest must equal default: resource cannot overcommit")
                 if t.custom:
                     if sizable & set(quota):
                         p.append(f"{where}: a custom tier cannot fix sizable keys {sorted(sizable & set(quota))}")
@@ -468,6 +479,10 @@
             kind, part, res = limit_key_parts(key)        # type: ignore[misc]  # overridable keys were checked at load
             out.setdefault(kind, {}).setdefault(part, {})[res] = value
         for kind in sorted(out):
+            unequal = _unequal_non_overcommittable_defaults(out[kind])
+            if unequal:
+                raise TierError("limit-order-invalid", "Non-overcommittable resources require defaultRequest == default",
+                                kind=kind, resources=unequal)
             for res in sorted({res for vals in out[kind].values() for res in vals}):
                 chain = {part: out[kind][part][res] for part in LIMIT_PARTS if res in out[kind].get(part, {})}
                 if [qty(v) for v in chain.values()] != sorted(qty(v) for v in chain.values()):
--- a/cmapi/tests/core/test_tiers.py
+++ b/cmapi/tests/core/test_tiers.py
@@ -295,3 +295,29 @@
         c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "60Gi"}}}, SIZES)          # the tier's max is 50Gi
     assert e.value.code == "limit-order-invalid" and e.value.data["kind"] == "pvc"
     assert c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "1Gi"}}}, SIZES)["pvc"] == {"max": {"storage": "50Gi"}, "min": {"storage": "1Gi"}}
+
+
+def test_review_non_overcommittable_limit_defaults_must_match():
+    r = raw()
+    resource = "nvidia.com/gpu"
+    for part in ("defaultRequest", "default"):
+        key = f"limitRange.container.{part}.{resource}"
+        r["overridable"].append(key)
+        r["custom"]["max"][key] = "4"
+    c = TierCatalog(r, ALL)
+    with pytest.raises(TierError) as exc:
+        c.limits_for("dev", "custom", {"container": {"defaultRequest": {resource: "1"},
+                                                      "default": {resource: "2"}}}, SIZES)
+    assert exc.value.code == "limit-order-invalid"
+    assert c.limits_for("dev", "custom", {"container": {"defaultRequest": {resource: "1"},
+                                                        "default": {resource: "1"}}}, SIZES)
+
+
+
+def test_review_catalog_rejects_unequal_non_overcommittable_defaults():
+    r = raw()
+    r["defaults"]["limitRange"]["container"]["default"]["nvidia.com/gpu"] = "2"
+    r["defaults"]["limitRange"]["container"]["defaultRequest"]["nvidia.com/gpu"] = "1"
+    with pytest.raises(CatalogError, match="cannot overcommit"):
+        TierCatalog(r, ALL)
+
```

## F4 — P2: valid Kubernetes quantity spellings escape the tier error boundary (C8; C1 quantity probe)

`cmapi/src/cmapi/core/tiers.py:407`, reached by the newly added `limits_for` at line 463 and `render` at line 577, calls the restricted `qty` parser (lines 36-45). With the unchanged, valid reference catalog, a container CPU max of `"4e0"`, `"4E+0"`, or `"4."` raises plain `ValueError`, despite each spelling being a valid quantity of four CPUs, within bounds and quota. These are valid requests that should enter the beyond-tier approval path. They instead receive the generic validation-failed handling rather than tier policy validation. The parser restriction predates this change for quota inputs; the new limit override path exposes it as well. This is not a newly introduced quota-parser regression.

The [Kubernetes Quantity grammar](https://github.com/kubernetes/apimachinery/blob/master/pkg/api/resource/quantity.go) explicitly supports decimal exponent suffixes and a trailing decimal point. Three added core render regressions fail before the fix with `ValueError: not a Kubernetes quantity`. No missing approval fact is exploitable through this input: it is refused before deciding. The fix accepts the valid spellings and continues to compare their numeric quantities, so they cannot suppress beyond-tier detection.

The quantity fix below is shared by F4 and F5; it preserves both the accepted grammar and Kubernetes rounding.

Complete candidate fix and regression against this export (existing test files only):

```diff
--- a/cmapi/src/cmapi/core/tiers.py
+++ b/cmapi/src/cmapi/core/tiers.py
@@ -18,7 +18,7 @@
 import json
 import re
 from dataclasses import dataclass, field
-from decimal import Decimal
+from decimal import Decimal, ROUND_CEILING, localcontext
 from pathlib import Path
 from typing import Any, Literal, Mapping
 
@@ -34,7 +34,7 @@
     "Ki": Decimal(2) ** 10, "Mi": Decimal(2) ** 20, "Gi": Decimal(2) ** 30,
     "Ti": Decimal(2) ** 40, "Pi": Decimal(2) ** 50, "Ei": Decimal(2) ** 60,
 }
-_QTY = re.compile(r"^\+?([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E)?$")
+_QTY = re.compile(r"^\+?([0-9]+(?:\.[0-9]*)?|\.[0-9]+)(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E|[eE][+-]?[0-9]+)?$")
 
 
 def qty(value: str | int | float) -> Decimal:
@@ -42,7 +42,19 @@
     m = _QTY.fullmatch(str(value).strip())
     if not m:
         raise ValueError(f"not a Kubernetes quantity: {value!r}")
-    return Decimal(m.group(1)) * _SUFFIX[m.group(2) or ""]
+    suffix = m.group(2) or ""
+    if len(suffix) > 1 and suffix[0] in "eE" and suffix[1] != "i":
+        amount = Decimal(m.group(1) + suffix)
+    else:
+        number, factor = Decimal(m.group(1)), _SUFFIX[suffix]
+        with localcontext() as context:
+            context.prec = max(28, len(number.as_tuple().digits) + len(factor.as_tuple().digits))
+            amount = number * factor
+    if amount.as_tuple().exponent >= -9:
+        return amount
+    with localcontext() as context:
+        context.prec = max(28, len(amount.as_tuple().digits), amount.adjusted() + 10)
+        return amount.quantize(Decimal("1e-9"), rounding=ROUND_CEILING)
 
 
 # --------------------------------------------------------------------------- limit keys
--- a/cmapi/tests/core/test_tiers.py
+++ b/cmapi/tests/core/test_tiers.py
@@ -295,3 +295,14 @@
         c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "60Gi"}}}, SIZES)          # the tier's max is 50Gi
     assert e.value.code == "limit-order-invalid" and e.value.data["kind"] == "pvc"
     assert c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "1Gi"}}}, SIZES)["pvc"] == {"max": {"storage": "50Gi"}, "min": {"storage": "1Gi"}}
+
+
+@pytest.mark.parametrize("amount", ["4e0", "4E+0", "4.", "+4", "4.0", "4000m"])
+def test_review_valid_kubernetes_quantity_spellings_render(cat, amount):
+    rq, lr = cat.render(namespace="review-dev", cluster_id="CRC", instance="nonprod", env="dev", tier="custom",
+                        request_id="r", hard=SIZES, limits={"container": {"max": {"cpu": amount}}})
+    assert lr["spec"]["limits"][0]["max"]["cpu"] == amount
+    assert cat.beyond("dev", "custom", rq["spec"]["hard"],
+                      cat.limits_for("dev", "custom", {"container": {"max": {"cpu": amount}}}, SIZES)) == {
+        "limitRange.container.max.cpu": {"tier": "2", "requested": amount}}
+
```

## F5 — P1: Decimal rounding hides a new value and reuses approval for a larger amount (C1, C5)

`cmapi/src/cmapi/core/tiers.py:45` multiplies the parsed Decimal by the suffix under Python's default 28-digit precision, rounding distinct amounts together. The new `_same` at lines 78-80 uses that result for both beyond-tier comparisons (line 499) and the approved bounds exemption (lines 404-405). `pipeline.py:289-290` uses it again to remove previously approved values from the approval facts.

Concrete PATCH: on an ordinary custom namespace with the tier's CPU max `"2"`, send `limitRange.container.max.cpu="2.0000000000000000000000000001"`. cmapi accepts and renders the new string but computes `beyondTier=False`, no beyond-tier annotation, and `none-required` for a dev change. The value is not in Git. Kubernetes parses it as `2000000001n`, strictly greater than two, so this is a direct C1 bypass. The increase is tiny, but it contradicts the asserted gate and can also bypass the numerical bounds boundary.

For C5, lower the storage bound to 300Gi after Git approved 500Gi, and request `"500.00000000000000000000000001Gi"`. The comparison rounds back to 500Gi and incorrectly exempts the new, larger amount. The regression expecting `custom-out-of-bounds` fails. Both failures occur with valid quantity strings and a catalog that loads.

Verified using Kubernetes' actual `k8s.io/apimachinery v0.32.0` quantity parser in a local Go program, without starting a service: `2 -> 2`; `2.0000000000000000000000000001 -> 2000000001n`. Its [ParseQuantity implementation](https://github.com/kubernetes/apimachinery/blob/v0.32.0/pkg/api/resource/quantity.go#L330-L355) rounds positive fractions upward to nanounits, whereas cmapi rounds this value downward. The fix must multiply without losing digits and normalize to Kubernetes nanounits before comparisons. Merely switching string equality to Decimal equality is insufficient.

The quantity fix below is shared by F4 and F5; it preserves both the accepted grammar and Kubernetes rounding.

Complete candidate fix and regression against this export (existing test files only):

```diff
--- a/cmapi/src/cmapi/core/tiers.py
+++ b/cmapi/src/cmapi/core/tiers.py
@@ -18,7 +18,7 @@
 import json
 import re
 from dataclasses import dataclass, field
-from decimal import Decimal
+from decimal import Decimal, ROUND_CEILING, localcontext
 from pathlib import Path
 from typing import Any, Literal, Mapping
 
@@ -34,7 +34,7 @@
     "Ki": Decimal(2) ** 10, "Mi": Decimal(2) ** 20, "Gi": Decimal(2) ** 30,
     "Ti": Decimal(2) ** 40, "Pi": Decimal(2) ** 50, "Ei": Decimal(2) ** 60,
 }
-_QTY = re.compile(r"^\+?([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E)?$")
+_QTY = re.compile(r"^\+?([0-9]+(?:\.[0-9]*)?|\.[0-9]+)(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E|[eE][+-]?[0-9]+)?$")
 
 
 def qty(value: str | int | float) -> Decimal:
@@ -42,7 +42,19 @@
     m = _QTY.fullmatch(str(value).strip())
     if not m:
         raise ValueError(f"not a Kubernetes quantity: {value!r}")
-    return Decimal(m.group(1)) * _SUFFIX[m.group(2) or ""]
+    suffix = m.group(2) or ""
+    if len(suffix) > 1 and suffix[0] in "eE" and suffix[1] != "i":
+        amount = Decimal(m.group(1) + suffix)
+    else:
+        number, factor = Decimal(m.group(1)), _SUFFIX[suffix]
+        with localcontext() as context:
+            context.prec = max(28, len(number.as_tuple().digits) + len(factor.as_tuple().digits))
+            amount = number * factor
+    if amount.as_tuple().exponent >= -9:
+        return amount
+    with localcontext() as context:
+        context.prec = max(28, len(amount.as_tuple().digits), amount.adjusted() + 10)
+        return amount.quantize(Decimal("1e-9"), rounding=ROUND_CEILING)
 
 
 # --------------------------------------------------------------------------- limit keys
--- a/cmapi/tests/core/test_tiers.py
+++ b/cmapi/tests/core/test_tiers.py
@@ -295,3 +295,51 @@
         c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "60Gi"}}}, SIZES)          # the tier's max is 50Gi
     assert e.value.code == "limit-order-invalid" and e.value.data["kind"] == "pvc"
     assert c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "1Gi"}}}, SIZES)["pvc"] == {"max": {"storage": "50Gi"}, "min": {"storage": "1Gi"}}
+
+
+def _review_pipeline(catalog, *, tier="custom", quota=None):
+    """Only in-memory ports: no database, API server, HTTP client, or worker."""
+    from types import SimpleNamespace as NS
+    from cmapi.core.config import load_instance
+    from cmapi.core.pipeline import Pipeline
+    from cmapi.core.ports import CapacityResult
+    from cmapi.core.render.manifests import NamespaceSpec
+    from conftest import person
+    cfg = load_instance(HERE / "instances/nonprod", HERE / "cluster-configs/policies/metadata-keys.yaml")
+    cfg.tiers = catalog
+    cache = NS(namespace=lambda ns: None)
+    registry = NS(writable=lambda cid: NS(policy=NS(environment="dev", labels={})), cache=lambda cid: cache)
+    git = NS(read_folder=lambda path: (previous, "base"))
+    pipe = Pipeline(cfg, registry, git, NS(validate=lambda *a: []),
+                    NS(check=lambda *a: CapacityResult("fits", True, None, {})), None, [])
+    spec = NamespaceSpec("review-dev", "CRC", "nonprod", "dev", tier, "old", "ola", "ola@ephico2real.com",
+                         labels={"cmapi.net/team": "payments"},
+                         annotations={"cmapi.net/team-dl": "payments@ephico2real.com"},
+                         quota=(quota or SIZES) if tier == "custom" else None)
+    previous = pipe.renderer.render(spec)
+    who = person("ola", roles={"cmapi-requester"})
+    return pipe, who, previous
+
+
+
+def test_review_decimal_rounding_cannot_hide_a_new_limit(cat):
+    from cmapi.core.pipeline import folder_etag
+    pipe, who, prev = _review_pipeline(cat)
+    amount = "2.0000000000000000000000000001"
+    plan = pipe.plan_namespace(who, "CRC", {"namespace": "review-dev", "limitRange": {"container": {"max": {"cpu": amount}}}},
+                               action="update", if_match=folder_etag(prev))
+    assert plan.facts["beyondTier"] is True
+    assert plan.facts["beyondTierKeys"] == ["limitRange.container.max.cpu"]
+    assert plan.requirement.total == 1
+
+
+
+def test_review_decimal_rounding_cannot_reuse_approval_for_a_larger_value(cat):
+    r = raw()
+    r["custom"]["max"]["requests.storage"] = "300Gi"
+    c = TierCatalog(r, ALL)
+    with pytest.raises(TierError) as exc:
+        c.quota_for("dev", "custom", {**SIZES, "requests.storage": "500.00000000000000000000000001Gi"},
+                    {"requests.storage": "500Gi"})
+    assert exc.value.code == "custom-out-of-bounds"
+
```

## Checks found correct

- C1: `+4`, `4.0`, and `4000m` compare as the same amount; ordinary quantity aliases do not hide a new override (`tiers.py:78-80,487-499`). F5 covers the precision exception.
- C1: a zero-valued override remains present and is marked beyond-tier when it differs from the tier; an empty string fails before deciding (`tiers.py:40-45,400-410`).
- C1: numeric quota/limit values and a caller-supplied `approved` field are rejected by the request models (`models.py:22-24,241-260`).
- C1: unknown/case-changed quota keys and invalid limit kind/part spellings are refused; `limits_for` reconstructs validated flattened keys into the rendered nested structure (`tiers.py:427-432,458-469`).
- C1: a PATCH with a newly overridable quota key sets `beyondTier` both from an old custom tier and from a named tier (`pipeline.py:243-247,289-294`).
- C1: `expiration:extend` follows `plan_namespace`, retains Git's approved overrides, and does not erase facts for a newly calculated difference (`plugins/namespaces/router.py:217`; `pipeline.py:234-294`).
- C2: `cmapi.net/beyond-tier` is system-owned in the example, local, and Helm metadata catalogs; both labels and annotations are refused even for an operator (`metadata.py:109-111`).
- C2: caller metadata is rendered on the Namespace; quota/limit override annotations are computed separately from effective catalog values (`render/manifests.py:112-128`; `tiers.py:596-598`).
- C2: an old named tier never supplies `approved`, and changing custom back to a named tier discards quota/limit overrides (`pipeline.py:235-252`; `tiers.py:420-425,452-456`).
- C3: `_auto` uses `is not True`, so a truthy string or integer cannot authorize beyond-tier auto-approval (`approvals.py:190`).
- C4: under `team_auto_today=21`, submit retains the original `beyondTier` facts and persists the same quota, limits, and approved map; a stored-spec render reproduces the submitted files (`pipeline.py:79-92,353-369`; `render/manifests.py:125-128`).
- C4: an actual in-memory call to `open_pr` with a wider catalog raises `plan hash mismatch` before any Git mutation (`jobs/open_pr.py:42-54`). No worker loop or database is started.
- C5: matching equivalent storage units remain exempt after a bound is lowered; a different key or a larger ordinary value is refused (`tiers.py:404-410`). F5 covers the precision exception.
- C6: the reference catalog enforces min/defaultRequest/default/max ordering for custom CPU, memory and PVC resources, and container max fits requests quota (`tiers.py:470-484`; existing refusal tests).
- C7: raising an already-approved network value from 1 to 2 sets both facts and adds both default thresholds (`pipeline.py:289-294`).
- C8: non-quantity bounds are collected as catalog errors before comparisons; a zero step is treated as no step and does not divide by zero (`tiers.py:271-288,408-409`).
- C8: an overridable limit kind missing from the tier is created with `setdefault`; a malformed flattened key cannot reach tuple unpacking under a catalog that passed validation (`tiers.py:233-237,458-469`).
- C9: quota hard-key order is already sorted by `_quota_order` in the base, and unchanged requests acquire no beyond-tier annotation (`tiers.py:585,596-598`; matching reversed-order custom plans).

## Execution and reproducibility

All five independent candidate diffs above were applied with `patch -p1` to fresh local copies of the exported files and their **entire core suites** passed:

| Candidate | Core result |
|---|---:|
| F1 | 170 passed |
| F2 | 169 passed |
| F3 | 168 passed |
| F4 | 172 passed |
| F5 | 168 passed |

The cumulative patch below adds all regressions and the additional confirmation tests described above. On original source it yields **15 failed, 186 passed**: 14 new regression cases plus the existing approval test whose expected count must increase under the corrected rule. With the cumulative source fixes it yields **201 passed**. The unmodified source/tests yielded **166 passed**.

The system Python lacked pytest. Tests used an isolated environment with Python 3.14, PyYAML 6.0.3, Pydantic 2.14.3 and pytest 9.2.0; these are installed test-environment versions, not a claim that project-pinned dependencies were tested. The in-memory pipeline/worker confirmation tests additionally import the application's HTTP, SQLAlchemy, logging and settings libraries, but never construct a database, connect to PostgreSQL, or start a server.

Save the final diff block as a patch and apply it with `patch -p1` from this folder. Recreate an isolated environment here and run:

```sh
python3 -m venv .review-venv
.review-venv/bin/python -m pip install pyyaml pydantic pytest httpx sqlalchemy prometheus-client structlog pyjwt fastapi pydantic-settings
cd cmapi/tests/core
PYTHONPATH=../../src ../../../.review-venv/bin/python -m pytest . -q
```

The C9 comparison removed only the new `overridable` declaration/extra bounds and the two new threshold expressions when loading the old schemas; existing tier values and approval rules were preserved. It compared strings and `plan_hash`, not just parsed YAML. This matters because the existing example-folder test alone compares dictionaries.

No `tests/service` collection or execution occurred. No portal or Kyverno policy review was performed. There are no findings without a failing test.

## Cumulative patch against the export

This is the exact combined application/test change used for the 201-test green run. It includes all source fixes and all added core tests; it creates no new source or test files.

```diff
--- a/cmapi/src/cmapi/core/approvals.py
+++ b/cmapi/src/cmapi/core/approvals.py
@@ -121,8 +121,19 @@
 
     def added_for(self, facts: Mapping[str, Any], names: frozenset[str]) -> list[Slot]:
         """The approvers that the thresholds reading one of the named facts add for these facts, one slot for each rule."""
-        return [Slot(t.get("group", self.defaults["group"]), int(t.get("add", 1)), t.get("reason") or expr.source)
-                for expr, t in self.thresholds if expr.names() & names and expr(facts)]
+        slots = [Slot(t.get("group", self.defaults["group"]), int(t.get("add", 1)), t.get("reason") or expr.source)
+                 for expr, t in self.thresholds if expr.names() & names and expr(facts)]
+        fallback = self._beyond_fallback(facts)
+        if fallback and names & {"beyondTier", "beyondTierKeys"}:
+            slots.append(fallback)
+        return slots
+
+    def _beyond_fallback(self, facts: Mapping[str, Any]) -> Slot | None:
+        if facts.get("beyondTier") and not any(
+                expr.names() & {"beyondTier", "beyondTierKeys"} and expr(facts) and int(t.get("add", 1)) > 0
+                for expr, t in self.thresholds):
+            return Slot(self.defaults["group"], 1, "Value beyond the tier")
+        return None
 
     # ---- decide
     def decide(self, facts: Mapping[str, Any], *, paused: bool = False,
@@ -154,6 +165,11 @@
                 slots.append(Slot(g, int(t.get("add", 1)), t.get("reason") or expr.source))
                 reasons.append(f"threshold {expr.source}: +{t.get('add', 1)} {g}")
                 added = True
+        beyond_fallback = self._beyond_fallback(facts)
+        if beyond_fallback:
+            slots.append(beyond_fallback)
+            reasons.append("Value beyond the tier: +1 " + beyond_fallback.group)
+            # _auto still permits a policy explicitly covering beyondTier when no configured rule added a slot.
         merged: dict[str, Slot] = {}
         for s in slots:
             m = merged.get(s.group)
--- a/cmapi/src/cmapi/core/pipeline.py
+++ b/cmapi/src/cmapi/core/pipeline.py
@@ -288,8 +288,9 @@
         # was approved before is not beyond the tier again.
         beyond = {k: v for k, v in self.cfg.tiers.beyond(env, tier, hard, limit_range).items()
                   if k not in approved or qty(approved[k]) != qty(v["requested"])}
-        raised = [k for k, v in beyond.items()
-                  if k in EXPOSURE_KEYS and qty(v["requested"]) > qty(approved.get(k) or v["tier"] or "0")]
+        exposure_baseline = (old_quota or {}) if old_tier else resolved.quota
+        raised = [k for k in EXPOSURE_KEYS
+                  if qty(hard.get(k, "0")) > qty(exposure_baseline.get(k, "0"))]
         facts.update({"beyondTier": bool(beyond), "beyondTierKeys": sorted(beyond), "networkExposure": bool(raised)})
         requirement = self._decide(facts)
         beyond_view = None
--- a/cmapi/src/cmapi/core/tiers.py
+++ b/cmapi/src/cmapi/core/tiers.py
@@ -18,7 +18,7 @@
 import json
 import re
 from dataclasses import dataclass, field
-from decimal import Decimal
+from decimal import Decimal, ROUND_CEILING, localcontext
 from pathlib import Path
 from typing import Any, Literal, Mapping
 
@@ -34,7 +34,7 @@
     "Ki": Decimal(2) ** 10, "Mi": Decimal(2) ** 20, "Gi": Decimal(2) ** 30,
     "Ti": Decimal(2) ** 40, "Pi": Decimal(2) ** 50, "Ei": Decimal(2) ** 60,
 }
-_QTY = re.compile(r"^\+?([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E)?$")
+_QTY = re.compile(r"^\+?([0-9]+(?:\.[0-9]*)?|\.[0-9]+)(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E|[eE][+-]?[0-9]+)?$")
 
 
 def qty(value: str | int | float) -> Decimal:
@@ -42,7 +42,19 @@
     m = _QTY.fullmatch(str(value).strip())
     if not m:
         raise ValueError(f"not a Kubernetes quantity: {value!r}")
-    return Decimal(m.group(1)) * _SUFFIX[m.group(2) or ""]
+    suffix = m.group(2) or ""
+    if len(suffix) > 1 and suffix[0] in "eE" and suffix[1] != "i":
+        amount = Decimal(m.group(1) + suffix)
+    else:
+        number, factor = Decimal(m.group(1)), _SUFFIX[suffix]
+        with localcontext() as context:
+            context.prec = max(28, len(number.as_tuple().digits) + len(factor.as_tuple().digits))
+            amount = number * factor
+    if amount.as_tuple().exponent >= -9:
+        return amount
+    with localcontext() as context:
+        context.prec = max(28, len(amount.as_tuple().digits), amount.adjusted() + 10)
+        return amount.quantize(Decimal("1e-9"), rounding=ROUND_CEILING)
 
 
 # --------------------------------------------------------------------------- limit keys
@@ -78,6 +90,14 @@
 def _same(a: str | None, b: str | None) -> bool:
     """Two quantities are the same amount: "1" and "1000m" are, a missing value and a value are not."""
     return (a is None and b is None) or (a is not None and b is not None and qty(a) == qty(b))
+
+
+def _unequal_non_overcommittable_defaults(parts: Mapping[str, Mapping[str, str]]) -> list[str]:
+    """Match Kubernetes IsOvercommitAllowed: native resources except hugepages can overcommit."""
+    defaults, requests = parts.get("default", {}), parts.get("defaultRequest", {})
+    return sorted(res for res in defaults.keys() & requests.keys()
+                  if (res.startswith("hugepages-") or ("/" in res and "kubernetes.io/" not in res))
+                  and not _same(defaults[res], requests[res]))
 
 
 # --------------------------------------------------------------------------- errors
@@ -315,6 +335,9 @@
                                 p.append(f"{where}: limitRange.{kind}.{part}.{k}: {exc}")
                 if len(p) > before:
                     continue
+                for kind, parts in lr.items():
+                    for res in _unequal_non_overcommittable_defaults(parts):
+                        p.append(f"{where}: {kind} {res} defaultRequest must equal default: resource cannot overcommit")
                 if t.custom:
                     if sizable & set(quota):
                         p.append(f"{where}: a custom tier cannot fix sizable keys {sorted(sizable & set(quota))}")
@@ -468,6 +491,10 @@
             kind, part, res = limit_key_parts(key)        # type: ignore[misc]  # overridable keys were checked at load
             out.setdefault(kind, {}).setdefault(part, {})[res] = value
         for kind in sorted(out):
+            unequal = _unequal_non_overcommittable_defaults(out[kind])
+            if unequal:
+                raise TierError("limit-order-invalid", "Non-overcommittable resources require defaultRequest == default",
+                                kind=kind, resources=unequal)
             for res in sorted({res for vals in out[kind].values() for res in vals}):
                 chain = {part: out[kind][part][res] for part in LIMIT_PARTS if res in out[kind].get(part, {})}
                 if [qty(v) for v in chain.values()] != sorted(qty(v) for v in chain.values()):
--- a/cmapi/tests/core/test_approvals.py
+++ b/cmapi/tests/core/test_approvals.py
@@ -99,7 +99,7 @@
     raw["thresholds"] = [t for t in raw["thresholds"] if t["when"] not in ("beyondTier", "networkExposure")]
     f = facts(environment="rnd", namespace="payments-rnd", tier="small", beyondTier=True, beyondTierKeys=["requests.storage"])
     r = ApprovalRules(raw, ALL_ENVS).decide(f)            # no threshold adds an approver, and still no auto-approval
-    assert r.auto is None and r.auto_fallback == "beyond-tier" and [(s.group, s.count) for s in r.slots] == [("approver-platform", 1)]
+    assert r.auto is None and r.auto_fallback == "beyond-tier" and [(s.group, s.count) for s in r.slots] == [("approver-platform", 2)]
     next(p for p in raw["autoApproval"]["policies"] if p["name"] == "baseline-rnd-namespace")["match"]["beyondTier"] = True
     assert ApprovalRules(raw, ALL_ENVS).decide(f).auto == "auto:baseline-rnd-namespace"
     # with the reference rules the threshold stops it first, and the guard that is named is the specific one
@@ -265,3 +265,19 @@
            "autoApproval": {"enabled": True, "policies": [{"name": "p", "match": {"plugin": "namespaces", "actions": ["create"], "environments": ["*"]}}]}}
     req = ApprovalRules(raw, {"prod"}, group_path="/corp/{name}").decide(facts(), paused=True)
     assert req.slots and req.auto_fallback == "paused" and req.token_group("approver-prod") == "/corp/approver-prod"
+
+
+@pytest.mark.parametrize("base", [0, 1])
+@pytest.mark.parametrize("auto", [False, True])
+def test_review_beyond_tier_needs_an_extra_slot_without_threshold(base, auto):
+    raw = {"environments": {"dev": {"change": base}},
+           "autoApproval": {"enabled": auto, "policies": [{"name": "ordinary", "match": {}}]}}
+    rules = ApprovalRules(raw)
+    f = facts(environment="dev", action="update", tier="custom", beyondTier=True)
+    req = rules.decide(f)
+    assert req.auto is None
+    assert req.total == base + 1
+    assert [(s.group, s.count) for s in rules.added_for(f, BEYOND_FACTS)] == [("approver-platform", 1)]
+    raw["autoApproval"]["policies"][0]["match"]["beyondTier"] = True
+    if auto:
+        assert ApprovalRules(raw).decide(f).auto == "auto:ordinary"
--- a/cmapi/tests/core/test_tiers.py
+++ b/cmapi/tests/core/test_tiers.py
@@ -295,3 +295,232 @@
         c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "60Gi"}}}, SIZES)          # the tier's max is 50Gi
     assert e.value.code == "limit-order-invalid" and e.value.data["kind"] == "pvc"
     assert c.limits_for("rnd", "custom", {"pvc": {"min": {"storage": "1Gi"}}}, SIZES)["pvc"] == {"max": {"storage": "50Gi"}, "min": {"storage": "1Gi"}}
+
+
+def _review_pipeline(catalog, *, tier="custom", quota=None):
+    """Only in-memory ports: no database, API server, HTTP client, or worker."""
+    from types import SimpleNamespace as NS
+    from cmapi.core.config import load_instance
+    from cmapi.core.pipeline import Pipeline
+    from cmapi.core.ports import CapacityResult
+    from cmapi.core.render.manifests import NamespaceSpec
+    from conftest import person
+    cfg = load_instance(HERE / "instances/nonprod", HERE / "cluster-configs/policies/metadata-keys.yaml")
+    cfg.tiers = catalog
+    cache = NS(namespace=lambda ns: None)
+    registry = NS(writable=lambda cid: NS(policy=NS(environment="dev", labels={})), cache=lambda cid: cache)
+    git = NS(read_folder=lambda path: (previous, "base"))
+    pipe = Pipeline(cfg, registry, git, NS(validate=lambda *a: []),
+                    NS(check=lambda *a: CapacityResult("fits", True, None, {})), None, [])
+    spec = NamespaceSpec("review-dev", "CRC", "nonprod", "dev", tier, "old", "ola", "ola@ephico2real.com",
+                         labels={"cmapi.net/team": "payments"},
+                         annotations={"cmapi.net/team-dl": "payments@ephico2real.com"},
+                         quota=(quota or SIZES) if tier == "custom" else None)
+    previous = pipe.renderer.render(spec)
+    who = person("ola", roles={"cmapi-requester"})
+    return pipe, who, previous
+
+
+@pytest.mark.parametrize("old_tier,old_network,new_tier,new_network", [
+    ("custom", "0", "custom", "1"),  # return from a lower approved value to a nonzero tier default
+    ("small", "0", "custom", None),  # named -> custom inherits a higher default
+    ("custom", "0", "small", None),  # custom -> named inherits a higher default
+])
+def test_review_network_exposure_uses_git_even_when_new_value_equals_tier(old_tier, old_network, new_tier, new_network):
+    from cmapi.core.pipeline import folder_etag
+    r = raw()
+    r["defaults"]["quota"]["services.nodeports"] = "1"
+    r["tiers"]["small"]["quota"]["services.nodeports"] = "0" if old_tier == "small" else "1"
+    c = TierCatalog(r, ALL)
+    pipe, who, previous = _review_pipeline(c, tier=old_tier, quota={**SIZES, "services.nodeports": old_network})
+    body = {"namespace": "review-dev", "tier": new_tier}
+    if new_tier == "custom":
+        body["quota"] = {**SIZES, **({"services.nodeports": new_network} if new_network else {})}
+    plan = pipe.plan_namespace(who, "CRC", body, action="update", if_match=folder_etag(previous))
+    assert plan.facts["networkExposure"] is True
+    assert plan.requirement.total >= 1
+
+
+def test_review_non_overcommittable_limit_defaults_must_match():
+    r = raw()
+    resource = "nvidia.com/gpu"
+    for part in ("defaultRequest", "default"):
+        key = f"limitRange.container.{part}.{resource}"
+        r["overridable"].append(key)
+        r["custom"]["max"][key] = "4"
+    c = TierCatalog(r, ALL)
+    with pytest.raises(TierError) as exc:
+        c.limits_for("dev", "custom", {"container": {"defaultRequest": {resource: "1"},
+                                                      "default": {resource: "2"}}}, SIZES)
+    assert exc.value.code == "limit-order-invalid"
+    assert c.limits_for("dev", "custom", {"container": {"defaultRequest": {resource: "1"},
+                                                        "default": {resource: "1"}}}, SIZES)
+
+
+def test_review_catalog_rejects_unequal_non_overcommittable_defaults():
+    r = raw()
+    r["defaults"]["limitRange"]["container"]["default"]["nvidia.com/gpu"] = "2"
+    r["defaults"]["limitRange"]["container"]["defaultRequest"]["nvidia.com/gpu"] = "1"
+    with pytest.raises(CatalogError, match="cannot overcommit"):
+        TierCatalog(r, ALL)
+
+
+@pytest.mark.parametrize("amount", ["4e0", "4E+0", "4.", "+4", "4.0", "4000m"])
+def test_review_valid_kubernetes_quantity_spellings_render(cat, amount):
+    rq, lr = cat.render(namespace="review-dev", cluster_id="CRC", instance="nonprod", env="dev", tier="custom",
+                        request_id="r", hard=SIZES, limits={"container": {"max": {"cpu": amount}}})
+    assert lr["spec"]["limits"][0]["max"]["cpu"] == amount
+    assert cat.beyond("dev", "custom", rq["spec"]["hard"],
+                      cat.limits_for("dev", "custom", {"container": {"max": {"cpu": amount}}}, SIZES)) == {
+        "limitRange.container.max.cpu": {"tier": "2", "requested": amount}}
+
+
+@pytest.mark.parametrize("kind", ["labels", "annotations"])
+@pytest.mark.parametrize("operator", [False, True])
+def test_review_override_annotation_cannot_be_supplied_as_metadata(kind, operator):
+    from cmapi.core.metadata import MetadataKeys
+    keys = MetadataKeys.load(HERE / "cluster-configs/policies/metadata-keys.yaml")
+    args = {"labels": {}, "annotations": {}, kind: {"cmapi.net/beyond-tier": "requests.storage"}}
+    assert keys.validate(**args, operator=operator, require_governed=False) == [
+        {"code": "reserved_key", "key": "cmapi.net/beyond-tier"}]
+
+
+@pytest.mark.parametrize("key,value", [("requests.storage", "500Gi"), ("requests.storage", "0"),
+                                       ("services.nodeports", "1")])
+@pytest.mark.parametrize("tier", ["small", "custom"])
+def test_review_quota_patch_marks_each_new_override(tier, key, value, cat):
+    from cmapi.core.pipeline import folder_etag
+    pipe, who, prev = _review_pipeline(cat, tier=tier)
+    quota = {key: value} if tier == "custom" else {**SIZES, key: value}
+    plan = pipe.plan_namespace(who, "CRC", {"namespace": "review-dev", "tier": "custom", "quota": quota},
+                               action="update", if_match=folder_etag(prev))
+    assert plan.facts["beyondTier"] is True
+    assert plan.facts["beyondTierKeys"] == [key]
+    assert plan.spec.approved.get(key) is None
+
+
+def test_review_approved_exemption_is_same_key_and_quantity(cat):
+    r = raw()
+    r["custom"]["max"]["requests.storage"] = "300Gi"
+    c = TierCatalog(r, ALL)
+    approved = {"requests.storage": "500Gi"}
+    assert c.quota_for("dev", "custom", {**SIZES, "requests.storage": "512000Mi"}, approved)
+    with pytest.raises(TierError):
+        c.quota_for("dev", "custom", {**SIZES, "requests.storage": "501Gi"}, approved)
+    with pytest.raises(TierError):
+        c.quota_for("dev", "custom", {**SIZES, "requests.storage": "500Gi"}, {"other": "500Gi"})
+
+
+def test_review_bad_key_spellings_do_not_bypass_checks(cat):
+    with pytest.raises(TierError):
+        cat.quota_for("dev", "custom", {**SIZES, "Requests.storage": "500Gi"})
+    for limits in ({"Container": {"max": {"cpu": "4"}}},
+                   {"container.max": {"cpu": {"": "4"}}},
+                   {"container": {"Max": {"cpu": "4"}}}):
+        with pytest.raises(TierError):
+            cat.limits_for("dev", "custom", limits, SIZES)
+
+
+def test_review_zero_step_and_new_limit_kind_do_not_crash():
+    r = raw()
+    r["custom"]["step"]["requests.cpu"] = "0"
+    del r["defaults"]["limitRange"]["pvc"]
+    c = TierCatalog(r, ALL)
+    rq, lr = c.render(namespace="review-dev", cluster_id="CRC", instance="nonprod", env="dev", tier="custom",
+                      request_id="r", hard=SIZES, limits={"pvc": {"max": {"storage": "100Gi"}}})
+    assert lr["spec"]["limits"][1] == {"type": "PersistentVolumeClaim", "max": {"storage": "100Gi"}}
+    assert c.beyond("dev", "custom", rq["spec"]["hard"], {"pvc": {"max": {"storage": "100Gi"}}})
+
+
+def test_review_submit_retains_facts_and_stored_render_matches_plan(cat):
+    from types import SimpleNamespace as NS
+    from cmapi.core.pipeline import folder_etag
+    from cmapi.jobs.open_pr import _spec_from
+    pipe, who, prev = _review_pipeline(cat)
+    plan = pipe.plan_namespace(who, "CRC", {"namespace": "review-dev", "limitRange": {"pvc": {"max": {"storage": "100Gi"}}}},
+                               action="update", if_match=folder_etag(prev))
+    before = dict(plan.facts)
+    repo = NS(next_id=lambda: "review-r", auto_approvals_today=lambda team: 21, insert=lambda *a: None)
+    row = pipe.submit(who, plan, repo, NS(enqueue=lambda *a, **kw: None), idempotency_key=None,
+                      body_fingerprint="f", justification=None)
+    assert row.plan["facts"] == before and before["beyondTier"] is True
+    assert pipe.renderer.render(_spec_from(row.plan["spec"]), previous=prev) == row.plan["files"]
+    assert row.requirement["auto"] is None
+
+
+def test_review_worker_hash_check_rejects_catalog_widening(cat, monkeypatch):
+    from importlib import import_module
+    from types import SimpleNamespace as NS
+    from cmapi.core.pipeline import folder_etag
+    worker = import_module("cmapi.jobs.open_pr")
+    pipe, who, prev = _review_pipeline(cat)
+    plan = pipe.plan_namespace(who, "CRC", {"namespace": "review-dev", "labels": {"cmapi.net/cost-center": "cc-9000"}},
+                               action="update", if_match=folder_etag(prev))
+    repo = NS(next_id=lambda: "review-r", auto_approvals_today=lambda team: 0, insert=lambda *a: None)
+    row = pipe.submit(who, plan, repo, NS(enqueue=lambda *a, **kw: None), idempotency_key=None,
+                      body_fingerprint="f", justification=None)
+    row.status = "approved"
+    r = raw()
+    r["defaults"]["limitRange"]["pvc"]["max"]["storage"] = "75Gi"
+    pipe.renderer.catalog = TierCatalog(r, ALL)
+    repo.get = lambda rid: row
+    monkeypatch.setattr(worker, "RequestRepo", lambda session: repo)
+    monkeypatch.setattr(worker, "JobRepo", lambda session: NS())
+    with pytest.raises(RuntimeError, match="plan hash mismatch"):
+        worker.open_pr(NS(git=pipe.git, pipeline=pipe), None, NS(request_id=row.request_id))
+
+
+def test_review_raising_an_approved_network_override_marks_exposure(cat):
+    from cmapi.core.pipeline import folder_etag
+    pipe, who, prev = _review_pipeline(cat, quota={**SIZES, "services.nodeports": "1"})
+    plan = pipe.plan_namespace(who, "CRC", {"namespace": "review-dev", "quota": {"services.nodeports": "2"}},
+                               action="update", if_match=folder_etag(prev))
+    assert plan.facts["beyondTier"] and plan.facts["networkExposure"]
+    assert plan.spec.approved["services.nodeports"] == "1"
+    assert plan.requirement.total == 2
+
+
+def test_review_models_reject_numeric_quantities_and_caller_approved():
+    from pydantic import ValidationError
+    from cmapi.core.models import NamespacePatch
+    for body in ({"quota": {"services.nodeports": 1}},
+                 {"limitRange": {"container": {"max": {"cpu": 4}}}},
+                 {"approved": {"requests.storage": "500Gi"}}):
+        with pytest.raises(ValidationError):
+            NamespacePatch.model_validate(body)
+
+
+def test_review_expiration_extension_keeps_git_overrides(cat):
+    from datetime import date, timedelta
+    from cmapi.core.pipeline import folder_etag
+    pipe, who, prev = _review_pipeline(cat, quota={**SIZES, "requests.storage": "500Gi"})
+    ns_path = next(path for path in prev if path.endswith("/namespace.yaml"))
+    namespace = yaml.safe_load(prev[ns_path])
+    namespace["metadata"]["annotations"]["cmapi.net/expires-at"] = (date.today() + timedelta(days=1)).isoformat()
+    prev[ns_path] = yaml.safe_dump(namespace)
+    plan = pipe.plan_namespace(who, "CRC", {"namespace": "review-dev", "extendDays": 1},
+                               action="update", if_match=folder_etag(prev), reason="expiration:extend")
+    assert plan.spec.quota["requests.storage"] == "500Gi"
+    assert plan.spec.approved["requests.storage"] == "500Gi"
+    assert plan.facts["beyondTier"] is False
+
+
+def test_review_decimal_rounding_cannot_hide_a_new_limit(cat):
+    from cmapi.core.pipeline import folder_etag
+    pipe, who, prev = _review_pipeline(cat)
+    amount = "2.0000000000000000000000000001"
+    plan = pipe.plan_namespace(who, "CRC", {"namespace": "review-dev", "limitRange": {"container": {"max": {"cpu": amount}}}},
+                               action="update", if_match=folder_etag(prev))
+    assert plan.facts["beyondTier"] is True
+    assert plan.facts["beyondTierKeys"] == ["limitRange.container.max.cpu"]
+    assert plan.requirement.total == 1
+
+
+def test_review_decimal_rounding_cannot_reuse_approval_for_a_larger_value(cat):
+    r = raw()
+    r["custom"]["max"]["requests.storage"] = "300Gi"
+    c = TierCatalog(r, ALL)
+    with pytest.raises(TierError) as exc:
+        c.quota_for("dev", "custom", {**SIZES, "requests.storage": "500.00000000000000000000000001Gi"},
+                    {"requests.storage": "500Gi"})
+    assert exc.value.code == "custom-out-of-bounds"
```
