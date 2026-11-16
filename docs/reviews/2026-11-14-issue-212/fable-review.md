# Fable review of PR #245 (#212, Kyverno policies rendered from the configuration)

Reviewer: Fable 5.2. Author of the PR: Opus 5.5 (OB1 run 6); Codex designed and reviewed it (F1 to F9, applied). Head
`584e183e7ec4f8400bbb1e691ec5bf2844214aad`, stacked on #240 and #234; its own change is `git diff f18224f..584e183`.
Date: 2026-11-14. Read `pr-240.md` first: #240's three findings are in this head too.

Everything below was measured on this Mac (darwin x86_64) with the Kyverno CLI v1.20.0 (`ob1-run5/tools/bin/kyverno`,
checksum-verified, see `pr-240.md`), with no cluster. The pytest runs went through `ob1-run5/tools/suite.sh`, one at a
time, core and service in separate calls, with `CMAPI_REQUIRE_KYVERNO=1` so no CLI test could skip. Worktrees (mine,
detached, nothing pushed): `scratchpad/wt245` (the head) and `scratchpad/wt245fix` (the head plus the fixes), under
`/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/f7ded52b-75f6-4c7e-b4dc-532bcd598fb3/`.

## Verdict: changes needed, small

The generator does what the owner asked. The three example instances render exactly the committed bundle, each bound
and each metadata rule of the configuration has its policy with the configured value in the expression and in the
message, a changed bound changes only that policy, and nothing is written by hand. The ratchet could not be abused in
the ways tried. Three findings remain, each with its fix and a test that fails on `584e183` and passes with the fix, plus
#240's F3, which this head carries unchanged.

| # | Severity | Finding |
|---|---|---|
| F1 | High | #240's F1, still here: in audit, the worker's PR check fails the approved request on its Kyverno warning. This PR's own record says "Audit turns a violation into a warning" |
| F2 | Medium | The guard against a vacuous pass lost a case that #240's head catches: a hand-written policy of a kind that the CLI does not know gives no result, and next to the rendered bundle that is silent |
| F3 | Low | The rendered validations carry a `messageExpression` and no static `message`. Kyverno's documentation says it falls back to the static message when the expression's result is empty or multi-line; an annotation value can hold a newline. Not measured at admission (no cluster) |
| #240 F3 | Medium | An unquoted `mode: off` is refused at the start (`pr-240.md`). `core/policy.py` is unchanged by this PR; the same fix and test apply |

The fixes are `/Users/olasumbo/gitRepos/workbench/cmapi/fable-review/pr-245-files/fixes.diff` (source: `jobs/pr_checks.py`,
`core/validate/__init__.py`, `core/policygen.py`, `core/policy.py`) and `examples-rendered-again.diff` (the example bundle,
rendered again by `cmapi-tools policies render` after F3's change, 16 files; not hand-edited). `git apply --check` passes
for both on `584e183`. If #240 takes its F1 and F3 fixes first, drop the `pr_checks.py` and `policy.py` parts here.

| Run (logs in `pr-245-files/`) | `584e183` | `584e183` + fixes |
|---|---|---|
| `tests/core`, the PR's own 299 with the real CLI | 299 passed (inside `245-core-before.log`: 304 passed, 6 failed, the 11 others are mine) | passed, inside the next row |
| `tests/core/test_fable_review_245.py` and `test_fable_review_240_f3.py` (11 cases) | 5 failed, 6 passed (`245-core-before-2.log`) | passed, inside `tests/core`: 310 passed, the PR's 299 and these 11 (`245fix-core-2.log`) |
| `tests/service/test_fable_review_240.py` (4 cases) | 1 failed, 3 passed (`245-service-f1-before.log`) | passed, inside the next row |
| `tests/service` (the whole suite) | green on GitHub (`gh pr checks 245`: 6 of 6 pass) | 843 passed in 457 s (`245fix-service.log`) |

`245-core-before.log` and `245fix-core.log` are the first runs, with two errors in my own test file (a folder made twice, and
the retracted case of F2). The corrected file gave the `-2` logs, which the table uses. The PR's own 299 tests passed in each
of the three runs of `tests/core`.

## F1 (High): audit fails the approved request at the PR check

Same defect, same fix and same test as `pr-240.md` F1. Here: `cmapi/src/cmapi/jobs/pr_checks.py:74-75` and `:90`.

**Evidence.** `suite.sh wt245 245-service-f1-before.log tests/service/test_fable_review_240.py`:

```
E       AssertionError: [('plan_needs_approval', "waiting for [('approver-platform', 1)]"), ('approval', 'warning read'),
        ('approved', ...), ('ci', 'kubeconform: pass; kyverno: fail; cmapi check: pass'), ('pr_failed', 'checks failed')]
E       assert 'failed' == 'synced'
1 failed, 3 passed in 7.01s
```

docs/02 line 1886 (this head): "`audit` | A Kyverno finding is a warning on the plan and the dry run. The request goes
on to approval ... | Reports, does not fail".

**Fix** (the `pr_checks.py` part of `fixes.diff`):

```diff
diff --git a/cmapi/src/cmapi/jobs/pr_checks.py b/cmapi/src/cmapi/jobs/pr_checks.py
index 1f8361d..7a1dc29 100644
--- a/cmapi/src/cmapi/jobs/pr_checks.py
+++ b/cmapi/src/cmapi/jobs/pr_checks.py
@@ -71,23 +71,29 @@ def pr_checks(ctx: AppContext, s: Session, job: JobRow) -> None:
     # The default branch's folder is what this merge changes: a value that it already holds is not refused (#212).
     base = ctx.git.tree_files(ctx.git.default_branch, folder(row.cluster_id, row.namespace))
     findings = ctx.pipeline.validator.validate(tree, row.cluster_id, row.env, previous=base)
-    kc = [f for f in findings if f.source in ("kubeconform", "cmapi")]
-    ky = [f for f in findings if f.source == "kyverno"]
+    # Only an error fails a check. In audit a Kyverno finding is a warning (core/validate, #213): the plan showed it and the
+    # approvers accepted it, so the PR check reports it and does not fail, as the cluster's Audit action does.
+    errors = [f for f in findings if f.severity == "error"]
+    audited = [f for f in findings if f.severity != "error"]
+    kc = [f for f in errors if f.source in ("kubeconform", "cmapi")]
+    ky = [f for f in errors if f.source == "kyverno"]
+    ky_text = "; ".join(f"{f.rule}: {f.message}" for f in ky) or \
+        ("audit, not refused: " + "; ".join(f"{f.rule}: {f.message}" for f in audited) if audited else "policies ok")
     link = f"{ctx.cfg.raw_instance['instance'].get('publicUrl', '')}/api/v1/requests/{row.request_id}"
     jobs.fence()                       # the statuses are external writes: a worker whose lease was claimed posts none
     if not ctx.git.external_ci:
         ctx.git.set_check(head, CONTEXT_KUBECONFORM, "failure" if kc else "success",
                           "; ".join(f.message for f in kc)[:200] or "schema ok", link)
         ctx.git.set_check(head, CONTEXT_KYVERNO, "failure" if ky else "success",
-                          "; ".join(f"{f.rule}: {f.message}" for f in ky)[:200] or "policies ok", link)
+                          ky_text[:200], link)
     ctx.git.set_check(head, CONTEXT_CMAPI, "success" if cmapi_ok else "failure",
                       f"request {row.request_id} approved, head == plan {row.plan_hash[:12]}" if cmapi_ok
                       else f"head differs from the approved plan {row.plan_hash[:12]}, moved after it was opened, or touches {outside[:3]}", link)
     host_ci = "".join(f"; {c}: {state}" for c, state in ci.items())
-    repo.event(row, "ci", "ci", f"kubeconform: {'pass' if not kc else 'fail'}; kyverno: {'pass' if not ky else 'fail'}; "
+    repo.event(row, "ci", "ci", f"kubeconform: {'pass' if not kc else 'fail'}; kyverno: {'fail' if ky else 'audit' if audited else 'pass'}; "
                                 f"cmapi check: {'pass' if cmapi_ok else 'fail'}{host_ci}",
                {"findings": [f.message for f in findings], "head": head})
-    if findings or not cmapi_ok or ci_failed:
+    if errors or not cmapi_ok or ci_failed:
         if head != pr.head_sha:
             repo.event(row, "head_moved", "ci", f"PR head moved from {pr.head_sha[:8]} to {head[:8]} after approval")
         repo.move(row, E.PR_FAILED, "ci", "checks failed")
```

**Test**: `pr-245-files/service__test_fable_review_240.py` (the same file as #240's; it is in `pr-240.md`).

## F2 (Medium): a hand-written policy of an unknown kind passes silently

**Where.** `cmapi/src/cmapi/core/validate/__init__.py:201-204` (the guard) and `:252-267` (`_matched_kinds`, which reads
only documents of kind `ValidatingPolicy`). `settings.policies_dir` still loads hand-written policies next to the bundle.

**Evidence.** The CLI in text mode, as #240's validator calls it, on a policy whose kind has a typing error:

```
$ kyverno apply typo.yaml --resource ns-bad.yaml     # kind: ValidatingPolicyy, expression "false"
Applying 0 policy rule(s) to 1 resource(s)...
pass: 0, fail: 0, warn: 0, error: 0, skip: 0
```

On #240's head that line is a finding ("policy not understood by the CLI (0 rules applied)"). On this head
(`pr-245-files/probe5.py`, the real CLI through `CliValidator`, a namespace that the rendered bundle passes):

```
v1 ValidatingPolicy   namespaces bundle -> [('kyverno', 'hand-written', 'the hand-written policy refuses every namespace')]
v9 ValidatingPolicy   namespaces bundle -> [('cmapi', 'hand-written', 'policy not understood by the CLI (no result for this file)')]
v1 ValidatingPolicyy  namespaces bundle -> NO FINDING
v1 ValidatingPolicyy  namespaces alone  -> [('cmapi', 'validator', 'kyverno exited 0 with no report: ')]
v1 NamespacedValidatingPolicy namespaces bundle -> [('kyverno', 'hand-written', ...)]
v1 ValidatingPolicy   Namespace  bundle -> NO FINDING
```

Row 3 is the regression: a policy that should refuse every namespace refuses none, and nothing says so. Row 4 shows it is
caught only when no other policy runs. Row 6 (a ValidatingPolicy whose `resources` holds a kind name, not a plural) is
also silent, but #240's head is silent there too ("Applying 1 policy rule(s)", `fail: 0`), so it is not counted and the
fix leaves it alone.

I retract one case I first expected to be silent: `apiVersion: kyverno.io/v9`, `kind: ClusterPolicy`. The head already
refuses it (`('cmapi', 'validator', 'error')`: the CLI stops with no report), so it is not in the test.

**Fix** (the `validate/__init__.py` part of `fixes.diff`): a document of another kind must give one result at least.
A kind that the CLI runs (`NamespacedValidatingPolicy`) does, so it is unaffected.

```diff
diff --git a/cmapi/src/cmapi/core/validate/__init__.py b/cmapi/src/cmapi/core/validate/__init__.py
index 0741bf1..9ac5e36 100644
--- a/cmapi/src/cmapi/core/validate/__init__.py
+++ b/cmapi/src/cmapi/core/validate/__init__.py
@@ -202,6 +202,11 @@ class CliValidator:
             for rel, doc in docs.items():
                 if doc.get("kind") in kinds and (name, rel) not in seen:
                     out.append(Finding("cmapi", name, rel, "policy not understood by the CLI (no result for this file)"))
+        # A document of another kind (a hand-written policy): the kinds it matches are not read here, so it must give
+        # one result at least. The CLI gives none for a kind or an apiVersion it does not know (M11), and says nothing.
+        reported = {res.get("policy") for res in results}
+        for name in sorted(_other_documents(policies) - reported):
+            out.append(Finding("cmapi", name, "", "policy not understood by the CLI (no result for any file)"))
         return out
 
 
@@ -249,6 +254,16 @@ def _limit(doc: Mapping[str, Any], kind: str, part: str, res: str) -> str | None
     return None
 
 
+def _other_documents(policies: Mapping[str, str]) -> set[str]:
+    """The names of the bundle's documents that are not a ValidatingPolicy, which _matched_kinds does not cover."""
+    out: set[str] = set()
+    for text in policies.values():
+        for doc in yaml.safe_load_all(text):
+            if isinstance(doc, Mapping) and doc.get("kind") != "ValidatingPolicy":
+                out.add(str((doc.get("metadata") or {}).get("name") or doc.get("kind") or "a document with no kind"))
+    return out
+
+
 def _matched_kinds(policies: Mapping[str, str]) -> dict[str, set[str]]:
     """Policy name -> the kinds its resourceRules match, for each ValidatingPolicy of the bundle."""
     out: dict[str, set[str]] = {}
```

## F3 (Low): no static message behind the messageExpression

**Where.** `cmapi/src/cmapi/core/policygen.py:85`:
`spec["validations"] = [{"expression": c.expression, "messageExpression": c.message} for c in checks]`.

**Evidence.** Kyverno, "ValidatingPolicy", <https://kyverno.io/docs/policy-types/validating-policy/>, read 2026-11-14:
"If the expression fails or produces an invalid string (empty, whitespace-only, or multi-line), Kyverno falls back to the
static message." Each metadata message quotes the offending value, and an annotation value may hold a newline. The
rendered bundle has 131 policies and no `message` (`grep -c '^    message:' ` over `examples/cluster-configs/policies/env`
gives 0). So for such a value the refusal at admission would not carry the key or the configured value, which the owner
asked every message to carry.

Measured offline only: the v1.20.0 CLI does not fall back. `pr-245-files/probe3.py` with `cmapi.net/team-dl` set to
`"first line\nsecond@evil.com"` reports the full two-line message. So plan time is fine, and the claim about admission
rests on the documentation alone. That is why this is Low.

**Fix** (the `policygen.py` part of `fixes.diff`, and the example bundle rendered again): each `Check` carries a static
sentence with the key and the configured value, without the offending value. With the fix the CLI still reports the
expression's message (second test below), as the documentation says ("the messageExpression takes precedence").

```diff
diff --git a/cmapi/src/cmapi/core/policygen.py b/cmapi/src/cmapi/core/policygen.py
index fddfbc6..2d9abe3 100644
--- a/cmapi/src/cmapi/core/policygen.py
+++ b/cmapi/src/cmapi/core/policygen.py
@@ -67,6 +67,10 @@ class Check:
     rule: str                 # required | pattern | enum | format | namespacePrefix | derived | max | min | step | order | absent
     expression: str
     message: str
+    # The static message, with the key and the configured value and without the offending one. Kyverno falls back to it
+    # at admission when the messageExpression fails or gives an empty or multi-line string (an annotation value may hold
+    # a newline): "Kyverno falls back to the static message" (kyverno.io, ValidatingPolicy, read 2026-11-14).
+    fallback: str
 
 
 def _policy(name: str, resource: str, actions: list[str], checks: list[Check], description: str,
@@ -82,7 +86,7 @@ def _policy(name: str, resource: str, actions: list[str], checks: list[Check], d
         # The CLI evaluates as CREATE with an empty oldObject (measured, M8), so offline every key is checked.
         {"name": "update", "expression": "request.operation == 'UPDATE' && has(oldObject.metadata)"},
     ]
-    spec["validations"] = [{"expression": c.expression, "messageExpression": c.message} for c in checks]
+    spec["validations"] = [{"expression": c.expression, "message": c.fallback, "messageExpression": c.message} for c in checks]
     return {"apiVersion": "policies.kyverno.io/v1", "kind": "ValidatingPolicy",
             "metadata": {"name": name, "annotations": {"policies.kyverno.io/description": description,
                                                        "cmapi.net/generated": "true"}},
@@ -131,11 +135,13 @@ def _metadata_checks(keys: MetadataKeys, env: str, instance: str) -> list[Check]
     for kind, key in SYSTEM_REQUIRED:
         k, m = cel(key), _meta(kind)
         checks.append(Check(kind, key, "required", f"{_same(kind, key)} || ({k} in {m} && {m}[{k}] != '')",
-                            cel(f"the {kind} {key} is missing: cmapi writes it on each namespace it manages")))
+                            cel(f"the {kind} {key} is missing: cmapi writes it on each namespace it manages"),
+                            f"the {kind} {key} is missing: cmapi writes it on each namespace it manages"))
     k, m = cel(ENV_LABEL), _meta("label")
     checks.append(Check("label", ENV_LABEL, "derived", f"{_same('label', ENV_LABEL)} || ({k} in {m} && {m}[{k}] == {cel(env)})",
                         f"{cel(f'the label {ENV_LABEL} is ')} + ({k} in {m} ? {m}[{k}] : 'missing') + "
-                        + cel(f"; it must be {env}, the environment of this policy")))
+                        + cel(f"; it must be {env}, the environment of this policy"),
+                        f"the label {ENV_LABEL} must be {env}, the environment of this policy"))
     constants = {"environment": env, "instance": instance}
     for kind in KINDS:
         for key, rule in keys.rules[kind].items():
@@ -154,7 +160,8 @@ def _metadata_checks(keys: MetadataKeys, env: str, instance: str) -> list[Check]
                 present = f"{k} in {m}"
                 good = f"{present} && {value} == {want}" if rule.required else f"!({present}) || {value} == {want}"
                 checks.append(Check(kind, key, "derived", f"{_same(kind, key)} || ({good})",
-                                    f"{cel(where + ' is ')} + {shown} + {cel('; cmapi sets it to ' + said)}"))
+                                    f"{cel(where + ' is ')} + {shown} + {cel('; cmapi sets it to ' + said)}",
+                                    f"{where} is not what cmapi sets it to: {said}"))
                 continue
             vr = _value_rule(rule, value, keys.email_domains)
             parts = []
@@ -178,7 +185,8 @@ def _metadata_checks(keys: MetadataKeys, env: str, instance: str) -> list[Check]
             name = "required" if rule.required and not vr and not rule.namespace_prefix else \
                 (vr[0] if vr else "namespacePrefix")
             checks.append(Check(kind, key, name, f"{_same(kind, key)} || ({' && '.join(parts)})",
-                                f"{cel(where + ' is ')} + {shown} + {cel('; it must be: ' + words)}"))
+                                f"{cel(where + ' is ')} + {shown} + {cel('; it must be: ' + words)}",
+                                f"{where} must be: {words}"))
     return checks
 
 
@@ -193,7 +201,8 @@ def _quota_checks(catalog: TierCatalog, env: str) -> list[Check]:
         good = f"!(has(object.spec.hard) && {k} in {hard}) || quantity({hard}[{k}]).compareTo(quantity({mx})) <= 0"
         checks.append(Check("quota", key, "max", f"{same} || {good}",
                             f"{cel(key + ' ')} + (has(object.spec.hard) && {k} in {hard} ? string({hard}[{k}]) : 'missing') + "
-                            + cel(f" is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift")))
+                            + cel(f" is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift"),
+                            f"{key} is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift"))
     return checks
 
 
@@ -216,7 +225,8 @@ def _limits_checks(catalog: TierCatalog, env: str) -> list[Check]:
         same = f"({v} != '' && {was} != '' && quantity({v}).compareTo(quantity({was})) == 0)"
         checks.append(Check("limit", key, "max", f"{v} == '' || {same} || quantity({v}).compareTo(quantity({mx})) <= 0",
                             f"{cel(key + ' ')} + {v} + "
-                            + cel(f" is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift")))
+                            + cel(f" is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift"),
+                            f"{key} is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift"))
     # Limits never below requests: default not below defaultRequest, max not below default, for each container resource.
     # Structure, not a bound: never kept for a value that the object already held.
     for res in ("cpu", "memory"):
@@ -225,7 +235,8 @@ def _limits_checks(catalog: TierCatalog, env: str) -> list[Check]:
             key = f"limitRange.container.{high}.{res}"
             checks.append(Check("limit", key, "order",
                                 f"{lo} == '' || {hi} == '' || quantity({hi}).compareTo(quantity({lo})) >= 0",
-                                f"{cel(f'container {high} {res} ')} + {hi} + {cel(f' is below its {low} ')} + {lo}"))
+                                f"{cel(f'container {high} {res} ')} + {hi} + {cel(f' is below its {low} ')} + {lo}",
+                                f"container {high} {res} is below its {low}"))
     return checks
 
 
@@ -234,7 +245,9 @@ def _expiry_checks() -> list[Check]:
     for kind, key in EXPIRY_KEYS:
         out.append(Check(kind, key, "absent", f"!({cel(key)} in {_meta(kind)})",
                          "'Production namespaces never expire: remove cmapi.net/expires-at, cmapi.net/expiry "
-                         "and cleanup.kyverno.io/ttl.'"))
+                         "and cleanup.kyverno.io/ttl.'",
+                         "Production namespaces never expire: remove cmapi.net/expires-at, cmapi.net/expiry "
+                         "and cleanup.kyverno.io/ttl."))
     return out
 
 
```

**Test for F2 and F3** (`pr-245-files/core__test_fable_review_245.py`, to be `cmapi/tests/core/test_fable_review_245.py`):

```python
"""Fable's review of #245, F2: each rendered validation carries a static `message` next to its messageExpression.

Kyverno's ValidatingPolicy page (read 2026-11-14): "If the expression fails or produces an invalid string (empty,
whitespace-only, or multi-line), Kyverno falls back to the static message." An annotation value may hold a newline, so
without a static message the refusal at admission names neither the key nor the configured value.
"""
from __future__ import annotations

import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from cmapi.core.tiers import TierCatalog
from conftest import ALL_ENVS, EX
from test_policygen import apply, kyverno, resources, write  # noqa: F401  (the fixture)

KEYS = EX / "cluster-configs/policies/metadata-keys.yaml"


def _bundle():
    catalog = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    return catalog, render_bundle(catalog, MetadataKeys.load(KEYS), PolicySettings(), ALL_ENVS, "nonprod")


def test_each_rendered_validation_has_a_static_message_with_its_key_and_configured_value():
    catalog, bundle = _bundle()
    seen = 0
    for rel, text in bundle.items():
        if not rel.endswith(".yaml"):
            continue
        for doc in yaml.safe_load_all(text):
            for v in doc["spec"]["validations"]:
                seen += 1
                message = v.get("message", "")
                assert message.strip() and "\n" not in message, (doc["metadata"]["name"], message)
                assert v.get("messageExpression"), doc["metadata"]["name"]
    assert seen > 100
    quota = next(d for d in yaml.safe_load_all(bundle["env/rnd/cmapi-quota-rnd.yaml"])
                 if d["metadata"]["name"] == "cmapi-quota-rnd-quota-requests-cpu-max")
    bound = catalog.bounds("rnd").max["requests.cpu"]
    assert quota["spec"]["validations"][0]["message"] == \
        f"requests.cpu is above the rnd maximum of {bound}; a bound of tiers.yaml, which approval does not lift"
    meta = next(d for d in yaml.safe_load_all(bundle["env/rnd/cmapi-metadata-rnd.yaml"])
                if d["metadata"]["name"] == "cmapi-metadata-rnd-annotation-cmapi-net-team-dl-format")
    assert meta["spec"]["validations"][0]["message"] == \
        "the annotation cmapi.net/team-dl must be: required; an address in ephico2real.com"


def test_the_message_expression_still_wins_in_the_cli(kyverno, tmp_path):
    """The static message is a fallback only: the CLI's report still carries the offending value."""
    catalog, bundle = _bundle()
    policies = write(tmp_path / "p", {k: v for k, v in bundle.items() if k.startswith("env/rnd/") and k.endswith(".yaml")})
    rq = {"apiVersion": "v1", "kind": "ResourceQuota",
          "metadata": {"name": "q", "namespace": "abc-rnd", "labels": {"cmapi.net/managed": "true"}},
          "spec": {"hard": {"requests.cpu": "4000"}}}
    got = apply(kyverno, policies, resources(tmp_path, {"rq.yaml": rq}))
    bound = catalog.bounds("rnd").max["requests.cpu"]
    assert ("cmapi-quota-rnd-quota-requests-cpu-max",
            f"requests.cpu 4000 is above the rnd maximum of {bound}; a bound of tiers.yaml, which approval does not lift") in got["fail"]


# F3: the guard against a vacuous pass covers a hand-written policy of a kind that the CLI does not know.
from cmapi.core.validate import CliValidator  # noqa: E402
from test_policygen import owners_sample  # noqa: E402

HAND = """apiVersion: {api}
kind: {kind}
metadata: {{name: hand-written}}
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - {{apiGroups: [""], apiVersions: [v1], operations: [CREATE, UPDATE], resources: [namespaces]}}
  validations:
    - expression: "{expression}"
      message: the hand-written policy refuses every namespace
"""


def _validate(tmp_path, hand: str):
    catalog = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.company.yaml")
    d = tmp_path / f"hand{len(list(tmp_path.iterdir()))}"
    d.mkdir()
    (d / "hand.yaml").write_text(hand)
    v = CliValidator(d, policy=PolicySettings(), environments={"rnd"},
                     bundle=render_bundle(catalog, keys, PolicySettings(), {"rnd"}, "nonprod"))
    files = {"clusters/OCP_GF15/namespaces/abc-rnd/" + k: t for k, t in owners_sample(catalog, keys).items()}
    return [(f.source, f.rule, f.severity) for f in v.validate(files, "OCP_GF15", "rnd") if f.source != "kubeconform"]


import pytest  # noqa: E402


@pytest.mark.parametrize("api, kind", [("policies.kyverno.io/v1", "ValidatingPolicyy"), ("kyverno.io/v1", "ValidatingPolcy")])
def test_a_hand_written_policy_of_a_kind_the_cli_does_not_know_is_a_finding(kyverno, tmp_path, monkeypatch, api, kind):
    """On #240's head the CLI printed "Applying 0 policy rule(s)" for it, which was a finding. Next to the rendered
    bundle the JSON report just has no result for it."""
    monkeypatch.setattr("cmapi.core.validate.CliValidator._kubeconform", lambda self, paths: [])
    assert _validate(tmp_path, HAND.format(api=api, kind=kind, expression="false")) == [("cmapi", "hand-written", "error")]


def test_a_hand_written_policy_of_another_kind_that_the_cli_runs_is_no_finding(kyverno, tmp_path, monkeypatch):
    monkeypatch.setattr("cmapi.core.validate.CliValidator._kubeconform", lambda self, paths: [])
    hand = HAND.format(api="policies.kyverno.io/v1", kind="NamespacedValidatingPolicy", expression="true")
    assert _validate(tmp_path, hand) == []
    hand = HAND.format(api="policies.kyverno.io/v1", kind="NamespacedValidatingPolicy", expression="false")
    assert _validate(tmp_path, hand) == [("kyverno", "hand-written", "error")]
```

**#240's F3 here** (`pr-245-files/core__test_fable_review_240_f3.py`; the fix is the `policy.py` part of `fixes.diff`,
identical to #240's):

```python
"""Fable's review of #240, F3: instance.yaml and the chart's values are YAML 1.1, where an unquoted `off` is the boolean false."""
from __future__ import annotations

import pytest
import yaml

from cmapi.core.policy import PolicySettings

SERVED = {"rnd", "dev"}


@pytest.mark.parametrize("text, modes", [
    ("mode: off", {"dev": "off", "rnd": "off"}),
    ("mode: enforce\nenvironments:\n  rnd: {mode: off}", {"dev": "enforce", "rnd": "off"}),
    ("mode: 'off'", {"dev": "off", "rnd": "off"}),
])
def test_an_unquoted_off_in_yaml_is_the_mode_off(text, modes):
    p, problems = PolicySettings.parse(yaml.safe_load(text), SERVED)
    assert problems == [] and p.modes(SERVED) == modes and (p.needs_kyverno(SERVED) is ("enforce" in modes.values()))


@pytest.mark.parametrize("text", ["mode: on", "mode: yes", "environments:\n  rnd: {mode: on}"])
def test_an_unquoted_on_is_still_refused(text):
    _, problems = PolicySettings.parse(yaml.safe_load(text), SERVED)
    assert any("must be one of" in p for p in problems), problems
```

## The six checks

**1. No kyverno binary: confirmed.** `env -i PATH=<stub kubeconform>:/usr/bin:/bin`, `shutil.which("kyverno")` is `None`
(`probe4.py` on `wt245`): `render_bundle` gives 0 files for `engine: none` and for `mode: off`; the validator starts and
validates with no finding for `engine: none`, `mode: off` and every environment `off`; enforce and audit raise
`PolicyEngineMissing`. `cmapi-tools policies render` and `check` for the three instances ran with the same stripped PATH.
Through the API (service test, both cases pass on the head): a create is planned, auto-approved and reaches `synced`.

**2. Audit against enforce: confirmed at plan time, refuted at the PR check (F1).** `probe1.py`, the real CLI, nonprod,
dev, a quota of `requests.cpu: 4000` and no team label:

```
-- enforce bad 2   error   kyverno cmapi-metadata-dev-label-cmapi-net-team-pattern | the label cmapi.net/team is missing; it must be: required; must match ^[a-z0-9-]{2,40}$
                   error   kyverno cmapi-quota-dev-quota-requests-cpu-max | requests.cpu 4000 is above the dev maximum of 32; a bound of tiers.yaml, which approval does not lift
-- audit bad 2     warning kyverno ... (the same two)
-- audit eval error  error cmapi cmapi-quota-dev-quota-requests-cpu-max | kyverno could not evaluate the policy: error: quantities must match the regular expression ...
```

So in audit a violation never refuses the plan, and an evaluation error still does (source `cmapi`). Rendered actions
(`probe2.py`): `{'mode': 'audit'}` gives `('Audit', 'Warn')` for dev and rnd, 8 files; `rnd: off` gives 4 files, dev only,
`('Deny',)`; `engine: none` gives 0 files. "A warning stops auto-approval" matches the owner: see `pr-240.md`, check 2.

**3. v1.20.0 and the v1 types: confirmed.** The pin is in `pr-240.md`. Every rendered policy is
`policies.kyverno.io/v1` `ValidatingPolicy`. CEL `variables` (`variables.update`) and `messageExpression` work offline:
the messages above are the expanded expressions. The CLI ignores `validationActions`: the `[Audit, Warn]` bundle still
reports `fail` in the JSON report, and the validator turns it into a warning from its own mode, not from the action; a
result of `warn`, an unknown result, or a missing one is a `cmapi` error (Codex's F7, 47 tests pass here). The guard
against 0 rules is now "no result for a file that the policy matches"; it works for a ValidatingPolicy (row 2 of F2's
table) and has the hole of F2.

**4. Generation: confirmed.** `cmapi-tools policies render` for nonprod, staging and prod into an empty folder, then
`diff -r` against `examples/cluster-configs/policies/env`: identical (8, 8 and 5 files; `check` exits 0 for each).
`probe2.py`, for each of rnd, dev, qa, uat and prod: 14 maximum keys in `tiers.yaml`, 14 `max` policies, none missing, and
for each the literal in the expression and the "`<env>` maximum of `<value>`" in the message equal
`catalog.bounds(env).max[key]`; no declared metadata key without a policy; `deny-expiry-in-prod` for prod only; four
`order` policies for each. Changing rnd's `custom.max.pods` from 300 to 250 changes two files (rnd, and dev, which
inherits rnd), two lines each, the expression and the message. The minimum and the step are not rendered: recorded (Q4).

**5. The ratchet: confirmed, with one gap that is already written down.** `probe1.py`: the two violations above with the
same files as `previous` give 0 findings; with a good `previous` (the value changed) both are refused; an evaluation error
is never held. `_held` compares the one key that the policy checks, between the new file and Git's, and no rendered check
that can be held reads a second field that a requester sets (`order` is never held; a key derived from the namespace
name cannot change). So a requester cannot bring a bad value in through a field that Git holds: the value must be equal
to Git's, or it is checked. The PR check takes the default branch's folder as the base, and the namespace's lock keeps
that folder from moving under an open request. A CREATE has no oldObject: `variables.update` is false and every check
runs (Codex's `test_rendered_ratchet_with_bound_old_object`, 11 cases, pass here with the real CLI). Those cases put the
old object into the CEL as a literal, because the CLI has none (M8), so the ratchet at admission itself is not measured,
as the record says.

An adoption PR has no base in Git, so nothing is held: in enforce, an adopted namespace that breaks a rule is refused at
plan time and at the PR check (the "enforce bad" output above is that case). #239's D6 says a missing required key does
not block adoption. `design-opus.md:171-174` names this ("an adoption PR has no base version of the file, so the adoption
plan's approved findings must be the base. That is a point for the adoption design"), but `docs/02:1902` says the ratchet
"also lets an adopted namespace keep its values through its first sync (#26)", which holds at admission only, and no
issue tracks it. Not a defect of this PR (the adoption plugin is not built); it needs an issue linked to #26 and #239:
the adoption plan gives the live snapshot as `previous`, and `pr_checks` uses the plan's snapshot when the default branch
has no folder.

Removing `cmapi.net/managed` from a ResourceQuota or LimitRange in one UPDATE (allowed: the values are unchanged) and
changing a value in a second one is outside the policies, as a delete and a CREATE without the label is. The record
arbitrates this (Q4, Q5, #242): who can write those objects can write a PolicyException too. Not re-opened.

**6. The tests on main: they fail at collection.** `core/policygen.py` does not exist at `f18224f`
(`git cat-file -e f18224f:cmapi/src/cmapi/core/policygen.py` exits 128), so `test_policygen.py` and `test_review_212.py`
cannot be imported there. As with #240, that is the only way a new module's tests can fail, and it shows nothing of the
old behaviour. Codex's 47 tests are the stronger evidence: the record says 26 failed on `c67a8f4`, before its fixes. I
did not rerun them on `c67a8f4`.

## Not measured

Admission on a cluster: the ratchet with a real oldObject, `[Audit, Warn]`, the message fallback of F3, and Argo CD's
prune of the policies Application. The image build (#157). One `kyverno apply` for a plan took 2.5 s here (26 policies,
3 files); the validator's timeout is 60 s, and a `subprocess.TimeoutExpired` is not caught (so it was before this PR).
