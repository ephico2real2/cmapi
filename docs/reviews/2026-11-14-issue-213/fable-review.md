# Fable review of PR #240 (#213, Kyverno optional, a mode for each environment, the CLI at v1.20.0)

Reviewer: Fable 5.2. Author of the PR: Opus 5.5 (OB1 run 6). Head `0248031157b6e6a34fb5350093d09360c6aeaed7`, base
`0c70b0e` (main). Date: 2026-11-14. No Codex pass ran on this PR, so this is its only outside review, and it is not an
outside model family.

Everything below was measured on this Mac (darwin x86_64), with no cluster and no image build. The pytest runs went
through `/Users/olasumbo/gitRepos/workbench/cmapi/ob1-run5/tools/suite.sh`, one at a time, core and service in separate
calls. The Kyverno CLI is `ob1-run5/tools/bin/kyverno`: `Version: v1.20.0`, and its tarball's SHA-256
(`2e31ed3d...376275`) equals the release's `checksums.txt` entry for `kyverno-cli_v1.20.0_darwin_x86_64.tar.gz`.
Worktrees (mine, detached, nothing pushed): `scratchpad/wt240` (the head) and `scratchpad/wt240fix` (the head plus the
fixes), under `/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/f7ded52b-75f6-4c7e-b4dc-532bcd598fb3/`.

## Verdict: changes needed

Three findings, each with its fix and a test that fails on `0248031` and passes with the fix.

| # | Severity | Finding |
|---|---|---|
| F1 | High | In audit, a request that the approvers accepted with its Kyverno warning is failed by cmapi's own PR check, and its PR is closed. Audit refuses after approval. #213 and docs/02 both say the PR check "Reports, does not fail" |
| F2 | Medium | In audit, a policy that the CLI could not compile or evaluate, and the "0 rules applied" guard, become warnings. A broken bundle then passes plans. #245 replaces this code and fixes it there, so F2 matters only for the time #240 is on main without #245 |
| F3 | Medium | `mode: off` written without quotes is refused at the start. YAML 1.1 reads `off` as the boolean false, in instance.yaml (PyYAML) and in a chart values file (Helm). `off` is the value that the issue, docs/02 and values.yaml name |

The fix for all three is one diff, `/Users/olasumbo/gitRepos/workbench/cmapi/fable-review/pr-240-files/fixes.diff`
(`git apply --check` passes on `0248031`). It touches `jobs/pr_checks.py`, `core/validate/__init__.py` and
`core/policy.py`, and no generated file: the contract and samples tests pass with it.

| Run (logs in `pr-240-files/`) | `0248031` | `0248031` + fixes |
|---|---|---|
| `tests/service/test_fable_review_240.py` (4 cases) | 1 failed, 3 passed (`240-f1-before.log`) | in the full suite, below |
| `tests/core/test_fable_review_240.py` (13 cases) | 8 failed, 5 passed (`240-core-before.log`) | in `tests/core`, below |
| `tests/core` | not rerun (the PR's record: 15 new tests pass) | 203 passed (`240fix-core.log`) |
| `tests/service` (the whole suite) | green on GitHub (`gh pr checks 240`: 6 of 6 pass) | 837 passed in 390 s (`240fix-service.log`) |

The cases that pass before are controls: in enforce a finding that appears at the PR check still fails the request; a
request plans, is approved and reaches `synced` with no kyverno binary, for `engine: none` and for `mode: off`; a
violation is a warning in audit and an error in enforce; a quoted `'off'` loads; `on` and `yes` are refused.

Six of the eight core failures before are F2's (three faults, each in audit and in enforce). In enforce the finding was
already an error; the test fails there only on its source (`kyverno`, where the fix gives `cmapi`). The three audit
cases are the defect: `('kyverno', 'warning')`.

## F1 (High): audit fails the approved request at the PR check

**Where.** `cmapi/src/cmapi/jobs/pr_checks.py:71-73` and `:88`. The job runs the validator on the PR head, and then:

```python
    kc = [f for f in findings if f.source in ("kubeconform", "cmapi")]
    ky = [f for f in findings if f.source == "kyverno"]
    ...
    if findings or not cmapi_ok or ci_failed:
        ...
        repo.move(row, E.PR_FAILED, "ci", "checks failed")
```

Neither line reads `severity`. In audit the validator returns the Kyverno finding as a warning (`core/validate/__init__.py:72`),
the plan goes to approval with it, an approver approves, the bot opens the PR, and this job posts `ci/kyverno: failure`,
fails the request and closes the PR. So a Kyverno finding in audit can never merge, which is what enforce does, only later
and after a person approved it.

**The yardstick.** #213's table, row `audit`, column "CI on the PR": "Reports, does not fail". `docs/02-technical-design-v2.md`
(this PR's own text): "`audit` | A Kyverno finding is a warning on the plan and the dry run. The request goes on to
approval ... | Reports, does not fail".

**Evidence.** `suite.sh wt240 240-f1-before.log tests/service/test_fable_review_240.py`:

```
E       AssertionError: [('plan_needs_approval', "waiting for [('approver-platform', 1)]"), ('approval', 'warning read'),
        ('approved', 'approv.../req-20261114-0001 #1'), ('ci', 'kubeconform: pass; kyverno: fail; cmapi check: pass'),
        ('pr_failed', 'checks failed')]
E       assert 'failed' == 'synced'
FAILED tests/service/test_fable_review_240.py::test_audit_an_approved_request_with_a_kyverno_warning_merges
1 failed, 3 passed in 6.66s
```

**Reach.** cmapi's own Python checks refuse the same values as the shipped policies, so today the warning arises for a
hand-written policy, or where Python and the policy disagree. The path is still the one that #213's acceptance names, and
the PR's own test stops at `pending_approval`, one step before it breaks.

**Not covered by the fix.** On a host with its own CI (`git.external_ci`, GitHub), `ci/kyverno` comes from the
configuration repository's workflow, which is not in this repository. If that workflow fails on an audit finding,
`ci_failed` still fails the request. `examples/cluster-configs/` has no workflow to check. That needs its own issue.

**Fix** (the `pr_checks.py` part of `fixes.diff`): only an error fails a check; a warning is reported in the check's text
and in the `ci` event (`kyverno: audit`).

```diff
diff --git a/cmapi/src/cmapi/jobs/pr_checks.py b/cmapi/src/cmapi/jobs/pr_checks.py
index 4be268f..97d34c1 100644
--- a/cmapi/src/cmapi/jobs/pr_checks.py
+++ b/cmapi/src/cmapi/jobs/pr_checks.py
@@ -69,23 +69,29 @@ def pr_checks(ctx: AppContext, s: Session, job: JobRow) -> None:
         outside = [f"a list that is not complete: {exc}"]
     cmapi_ok = not outside and head == pr.head_sha and tree == expected and plan_hash(actual) == row.plan_hash
     findings = ctx.pipeline.validator.validate(tree, row.cluster_id, row.env)
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

**Test** (`pr-240-files/service__test_fable_review_240.py`, to be `cmapi/tests/service/test_fable_review_240.py`):

```python
"""Fable's review of #240, F1: in audit, a Kyverno finding is a warning at the PR check too, so an approved request merges."""
from __future__ import annotations

from test_flow import AMY, NS, OLA, auth, run_jobs
from test_policy_modes_api import URL, world_with  # noqa: F401  (the fixture)


def test_audit_an_approved_request_with_a_kyverno_warning_merges(world_with):
    client, ctx, git, kube, validator, keys = world_with({"mode": "audit"})
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    rid = r.json()["requestId"]
    r = client.post(f"/api/v1/requests/{rid}:approve", json={"comment": "warning read"}, headers=auth(keys, "amy", **AMY))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "synced", [(e["event"], e.get("note")) for e in view["events"]]
    statuses = next(iter(git.statuses.values()))
    assert statuses["ci/kyverno"] == "success" and statuses["cmapi/check"] == "success"
    ci = next(e for e in view["events"] if e["event"] == "ci")
    assert "kyverno: audit" in ci["note"], ci


def test_enforce_a_kyverno_finding_at_the_pr_check_still_fails_the_request(world_with):
    """The other side: a finding that appears only at the PR check (the head was changed) fails the request in enforce."""
    client, ctx, git, kube, validator, keys = world_with({"mode": "off"}, kyverno=False)
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    rid = r.json()["requestId"]
    from cmapi.core.ports import Finding

    class Refusing:
        def validate(self, files, cluster_id, environment, previous=None):
            return [Finding("kyverno", "require-team-metadata", "", "team missing")]
    ctx.pipeline.validator = Refusing()
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "failed", view["events"]


import pytest


@pytest.mark.parametrize("policy", [{"engine": "none"}, {"mode": "off"}], ids=["engine-none", "mode-off"])
def test_with_no_kyverno_binary_a_request_plans_is_approved_and_syncs(world_with, policy):
    """The owner: "the cmapi would work with or without kyverno". PATH holds a stub kubeconform and the system tools only."""
    import shutil
    client, ctx, git, kube, validator, keys = world_with(policy, kyverno=False)
    assert shutil.which("kyverno") is None
    r = client.post(URL, json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{r.json()['requestId']}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "synced", view["events"]
    assert client.get("/api/v1/admin/integrations", headers=auth(keys, "ola", **OLA)).json()["policy"]["environments"] == \
        {"dev": "off", "rnd": "off"}
```

## F2 (Medium): in audit, a broken policy is a warning

**Where.** `cmapi/src/cmapi/core/validate/__init__.py:72` turns every finding of source `kyverno` into a warning, and
`:112-116` gives source `kyverno` to three things that are not violations: "0 rules applied", a non-zero exit, and output
with no `fail: 0`.

**Evidence.** The real v1.20.0 CLI, on a `policies.kyverno.io/v1` ValidatingPolicy and a Namespace
(`scratchpad/exp/`):

```
$ kyverno apply err.yaml --resource ns-bad.yaml      # quantity(object.metadata.name): cannot be evaluated
Applying 1 policy rule(s) to 1 resource(s)...
pass: 0, fail: 0, warn: 0, error: 1, skip: 0          # exit 1
$ kyverno apply compile.yaml --resource ns-bad.yaml  # an undeclared CEL function
Applying 1 policy rule(s) to 1 resource(s)...
Error: failed to compile policy err (... undeclared reference to 'nope' ...)   # exit 1
$ kyverno apply v9.yaml --resource ns-bad.yaml       # apiVersion policies.kyverno.io/v9
Applying 0 policy rule(s) to 1 resource(s)...
pass: 0, fail: 0, warn: 0, error: 0, skip: 0          # exit 0
```

With those three outputs as the stub, `suite.sh wt240 240-core-before.log tests/core/test_fable_review_240.py` gives, in
audit, `assert [('kyverno', 'warning')] == [('cmapi', 'error')]` three times. So in audit a bundle that the CLI cannot
read lets every plan through to approval, and (with F1 fixed) to the merge. The PR's own record says the opposite for the
other fault it knows: "An image that loses its binary must not pass plans in audit".

The "0 rules applied" guard itself still works in enforce: the third output above is a finding there (control case
`no-rules-enforce`, which fails before only on the source name).

**Fix** (the `validate/__init__.py` part of `fixes.diff`): the summary line decides. `fail` above 0 with no `error` is a
violation (source `kyverno`, a warning in audit). No rules, an `error` count, a non-zero exit with no failure, or no
summary line is a fault (source `cmapi`, an error in each mode). #245 makes the same split from the JSON report, so the
coordinator may drop this part if #245 merges straight after #240.

```diff
diff --git a/cmapi/src/cmapi/core/validate/__init__.py b/cmapi/src/cmapi/core/validate/__init__.py
index 0640c47..a8081ef 100644
--- a/cmapi/src/cmapi/core/validate/__init__.py
+++ b/cmapi/src/cmapi/core/validate/__init__.py
@@ -11,12 +11,13 @@ A policy under env/prod runs only for prod namespaces. A missing binary is a fin
 cannot approve anything.
 
 The mode of each environment (instance.yaml `policy`, core/policy.py; #213): off runs no Kyverno, audit turns each
-Kyverno finding into a warning, enforce keeps it an error. A finding of cmapi itself (a missing binary) stays an error
-in each mode. When a served environment needs Kyverno and the binary is missing, cmapi does not start.
+Kyverno violation into a warning, enforce keeps it an error. A finding of cmapi itself (a missing binary, a policy that
+the CLI could not evaluate or applied no rule of) stays an error in each mode. When a served environment needs Kyverno and the binary is missing, cmapi does not start.
 """
 from __future__ import annotations
 
 import json
+import re
 import shutil
 from dataclasses import replace
 import subprocess
@@ -28,6 +29,10 @@ from cmapi.core.policy import PolicySettings
 from cmapi.core.ports import Finding
 
 
+# The summary line of `kyverno apply`: "pass: 0, fail: 1, warn: 0, error: 0, skip: 0".
+_COUNT = re.compile(r"\b(fail|error): (\d+)")
+
+
 class ValidatorUnavailable(RuntimeError):
     """The check could not run (a schema download failed). Not a verdict on the files: retry, never refuse."""
 
@@ -109,9 +114,15 @@ class CliValidator:
             for rel, f in ns_files.items():
                 r = self._run([self.kyverno, "apply", str(pol), "--resource", f])
                 text = r.stdout + r.stderr
+                counts = {k: int(n) for k, n in _COUNT.findall(text)}
+                last = [ln for ln in text.strip().splitlines() if ln.strip()]
                 if "Applying 0 policy rule" in text:
-                    out.append(Finding("kyverno", pol.stem, rel, "policy not understood by the CLI (0 rules applied)"))
-                elif r.returncode != 0 or "fail: 0" not in text:
-                    last = [ln for ln in text.strip().splitlines() if ln.strip()]
+                    # Source cmapi: a fault of the bundle or the image, not a verdict, so audit keeps it an error.
+                    out.append(Finding("cmapi", pol.stem, rel, "policy not understood by the CLI (0 rules applied)"))
+                elif counts.get("fail", 0) > 0 and counts.get("error", 0) == 0:
                     out.append(Finding("kyverno", pol.stem, rel, (last[-1] if last else f"exit {r.returncode}")[:300]))
+                elif r.returncode != 0 or counts.get("error", 0) > 0 or "fail" not in counts:
+                    # No verdict: the policy did not compile, could not be evaluated, or the CLI printed no summary.
+                    out.append(Finding("cmapi", pol.stem, rel, "kyverno could not evaluate the policy: "
+                                                               f"{(last[-1] if last else f'exit {r.returncode}')[:260]}"))
         return out
```

**Test**: the first two tests of `pr-240-files/core__test_fable_review_240.py`, below.

## F3 (Medium): an unquoted `off` stops the start

**Where.** `cmapi/src/cmapi/core/policy.py:65` and `:71` compare the raw YAML value with `MODES`.

**Evidence.** instance.yaml of `examples/instances/nonprod` plus four lines, loaded with `load_instance`:

```
  policy:
    mode: enforce
    environments:
      rnd: {mode: off}
ConfigError: invalid instance configuration:
  instance.yaml: policy.environments.rnd.mode must be one of ['enforce', 'audit', 'off']
```

The chart, with a values file that holds `instance: {policy: {mode: off}}` (helm v4.3.1):

```
$ helm template cmapi deploy/helm/cmapi ... -f offvalues.yaml | grep ' policy: '
      policy: {"mode":false}
$ helm template cmapi deploy/helm/cmapi ... --set instance.policy.mode=off | grep ' policy: '
      policy: {"mode":"off"}
```

So `--set` works and a values file does not, and the message names `'off'` as allowed while refusing it. It fails closed
(cmapi does not start), so it is not a safety defect. It is the documented way to turn Kyverno off, and it does not work
as written. The PR's tests build the file with `yaml.safe_dump`, which quotes `'off'`, so they do not see it.

**Fix** (the `policy.py` part of `fixes.diff`): the boolean false is the mode off; true (`on`, `yes`) stays a problem.

```diff
diff --git a/cmapi/src/cmapi/core/policy.py b/cmapi/src/cmapi/core/policy.py
index 48d4dc9..86497cd 100644
--- a/cmapi/src/cmapi/core/policy.py
+++ b/cmapi/src/cmapi/core/policy.py
@@ -28,6 +28,12 @@ ENGINES = ("kyverno", "none")
 MODES = ("enforce", "audit", "off")
 
 
+def _mode(value: Any) -> Any:
+    """YAML 1.1 reads an unquoted `off` as the boolean false (PyYAML here, and Helm for a values file), so false is the
+    mode off. True (`on`, `yes`) is no mode and stays a problem."""
+    return "off" if value is False else value
+
+
 @dataclass(frozen=True)
 class PolicySettings:
     engine: str = "kyverno"
@@ -62,13 +68,13 @@ class PolicySettings:
         if engine not in ENGINES:
             problems.append(f"instance.yaml: policy.engine must be one of {list(ENGINES)}, not {engine!r}")
             engine = "kyverno"
-        default = raw.get("mode", "enforce")
+        default = _mode(raw.get("mode", "enforce"))
         if default not in MODES:
             problems.append(f"instance.yaml: policy.mode must be one of {list(MODES)}, not {default!r}")
             default = "enforce"
         envs: dict[str, str] = {}
         for env, spec in (raw.get("environments") or {}).items():
-            mode = (spec or {}).get("mode") if isinstance(spec, Mapping) else None
+            mode = _mode((spec or {}).get("mode")) if isinstance(spec, Mapping) else None
             if env not in allowed:
                 problems.append(f"instance.yaml: policy.environments.{env} is not an environment this instance serves")
             elif mode not in MODES:
```

**Test** (`pr-240-files/core__test_fable_review_240.py`, to be `cmapi/tests/core/test_fable_review_240.py`; F2 and F3):

```python
"""Fable's review of #240, F2: in audit only a violation becomes a warning. A policy that the CLI could not evaluate, or
applied no rule of, is a fault of the bundle or the image, and stays an error in each mode.

The stub kyverno prints what the real v1.20.0 CLI printed for each case (docs/reviews/2026-11-14-issue-213/, Fable's record).
"""
from __future__ import annotations

import pytest

from cmapi.core.policy import PolicySettings
from cmapi.core.validate import CliValidator
from test_policy_modes import FILES, SERVED, _stub, stubs  # noqa: F401  (the fixture)

EVAL_ERROR = 'echo "Applying 1 policy rule(s) to 1 resource(s)..."\necho "pass: 0, fail: 0, warn: 0, error: 1, skip: 0"\nexit 1\n'
COMPILE_ERROR = ('echo "Applying 1 policy rule(s) to 1 resource(s)..."\n'
                 'echo "Error: failed to compile policy err" >&2\nexit 1\n')
NO_RULES = 'echo "Applying 0 policy rule(s) to 1 resource(s)..."\necho "pass: 0, fail: 0, warn: 0, error: 0, skip: 0"\nexit 0\n'
VIOLATION = 'echo "Applying 1 policy rule(s) to 1 resource(s)..."\necho "pass: 0, fail: 1, warn: 0, error: 0, skip: 0"\nexit 1\n'


@pytest.mark.parametrize("mode", ["audit", "enforce"])
@pytest.mark.parametrize("body", [EVAL_ERROR, COMPILE_ERROR, NO_RULES], ids=["evaluation-error", "compile-error", "no-rules"])
def test_a_policy_that_gave_no_verdict_is_an_error_in_each_mode(stubs, mode, body):
    _stub(stubs / "bin", "kyverno", body)
    v = CliValidator(stubs / "policies", policy=PolicySettings(default_mode=mode), environments=SERVED)
    assert [(f.source, f.severity) for f in v.validate(FILES, "C", "dev")] == [("cmapi", "error")]


def test_a_violation_is_still_a_warning_in_audit_and_an_error_in_enforce(stubs):
    _stub(stubs / "bin", "kyverno", VIOLATION)
    audit = CliValidator(stubs / "policies", policy=PolicySettings(default_mode="audit"), environments=SERVED)
    assert [(f.source, f.severity) for f in audit.validate(FILES, "C", "dev")] == [("kyverno", "warning")]
    enforce = CliValidator(stubs / "policies", policy=PolicySettings(), environments=SERVED)
    assert [(f.source, f.severity) for f in enforce.validate(FILES, "C", "dev")] == [("kyverno", "error")]


# F3: instance.yaml and the chart's values are YAML 1.1, where an unquoted `off` is the boolean false.
import yaml  # noqa: E402


@pytest.mark.parametrize("text, modes", [
    ("mode: off", {"dev": "off", "rnd": "off"}),
    ("mode: enforce\nenvironments:\n  rnd: {mode: off}", {"dev": "enforce", "rnd": "off"}),
    ("mode: 'off'", {"dev": "off", "rnd": "off"}),
])
def test_an_unquoted_off_in_yaml_is_the_mode_off(text, modes):
    raw = yaml.safe_load(text)
    p, problems = PolicySettings.parse(raw, SERVED)
    assert problems == [] and p.modes(SERVED) == modes and (p.needs_kyverno(SERVED) is ("enforce" in modes.values()))


@pytest.mark.parametrize("text", ["mode: on", "mode: yes", "environments:\n  rnd: {mode: on}"])
def test_an_unquoted_on_is_still_refused(text):
    _, problems = PolicySettings.parse(yaml.safe_load(text), SERVED)
    assert any("must be one of" in p for p in problems), problems
```

## The six checks

**1. `engine: none` or `off` with no kyverno binary: confirmed.** With `PATH` holding a stub kubeconform and `/usr/bin:/bin`
only (`env -i`, `shutil.which("kyverno")` is `None`), `pr-245-files/probe4.py` on `wt240`: `engine: none`, `mode: off` and
every environment `off` construct the validator and validate with no finding; enforce, audit, and one audit environment
raise `PolicyEngineMissing` naming the environments. Through the API (my service test, 2 cases, passing before and
after): a create is planned, auto-approved by the dev rule, and reaches `synced`; `GET /admin/integrations` reports
`{"dev": "off", "rnd": "off"}`. Render is #245's (see `pr-245.md`). On main the same call gives
`[('cmapi', 'error', 'kyverno is not installed in this image')]`.

**2. Audit against enforce: refuted in part.** At plan time enforce refuses and audit warns, as claimed. Audit does
refuse later (F1), and an evaluation error does not refuse in audit (F2). "A warning stops auto-approval" is consistent
with the owner: #213's table says of audit "the request goes on to approval, and the approvers see the warnings", and
`warnings` is a fixed guard of `core/approvals.py:71`, so no policy can auto-approve over it. The rendered
`validationActions` are #245's.

**3. The pin and the policy types: confirmed.** `gh release download v1.20.0 -R kyverno/kyverno -p checksums.txt`:
`06b8f3ca7b5626473be8fb4d343ad54ab84e317142766f72420e7d44b80942e2  kyverno-cli_v1.20.0_linux_x86_64.tar.gz`, equal to
`cmapi/Containerfile`'s `KYVERNO_SHA256`. The release is not a prerelease, published 2026-11-12T09:32:42Z. The three
shipped policies (`cmapi/policies/` two, `examples/cluster-configs/policies/env/prod/` one) are
`policies.kyverno.io/v1`; `examples/local/` keeps `v1beta1` and 1.16.2, as recorded. The CLI prints
"Applying 1 policy rule(s)" for each v1 policy and fails a Namespace without the team keys (exit 1). The guard still
fails: see F2's third output. The CLI ignores `validationActions`: the same policy with `[Audit]` prints `fail: 1` and
exits 1, and the validator does not read the action, it reads its own mode, so it does not misread it.
Kyverno's ValidatingPolicy page (read 2026-11-14) shows `apiVersion: policies.kyverno.io/v1`, `validationActions` with
`Deny` and `Audit`, `variables` read as `variables.<name>`, and "If both message and messageExpression are defined, the
messageExpression takes precedence."

**4 and 5.** Generation and the ratchet are #245's: `pr-245.md`.

**6. The tests on main: they fail, at collection.** `tests/core/test_policy_modes.py` on `0c70b0e`:
`ModuleNotFoundError: No module named 'cmapi.core.policy'`. `tests/service/test_policy_modes_api.py`:
`ImportError: cannot import name 'POLICY_MODE'`. So they fail because the module is missing, which a new feature cannot
avoid, and no test shows main's behaviour. The record says so ("fails at import"). main's behaviour, measured: see check 1.

## Not measured

The image build (#157), admission on a cluster, the chart on a cluster, and the GitHub path of `pr_checks` in audit
(F1's last paragraph).
