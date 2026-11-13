MEASURED — Two defects were repaired in the exported head: completed/null check runs fail prematurely (R87-C6), and the named moved-head test misses deletion of the approved-head SHA guard (R87-C7). The existing C3 suite-window implementation and its regression file are preserved.

READ FROM CODE — R87-C6 root cause: `_run_state` treated every completed run with a conclusion other than success as failure, including null. The original parametrized test explicitly required that mistake. The worker then closes the PR instead of waiting. Snapshot: `report/original/cmapi/src/cmapi/core/git/github.py:39`.

MEASURED — Before R87-C6, `c6-before` in tests.md exited 1: `2 failed, 20 passed, 3 skipped`. The provider regression got failure instead of pending; the job regression got failed instead of pr_open. After R87-C6, `C6-C8-after` exited 0: `22 passed`. The three impossible commit-status/check-run-field combinations were removed from parametrization; both failing cases are retained.

READ FROM CODE — Full replacement function, path `head/cmapi/src/cmapi/core/git/github.py`:

```python
def _run_state(run: Mapping[str, Any]) -> CheckState:
    """What one check run says about a required check. Unfinished is pending, whatever else the run carries. Finished is a pass
    only on the conclusion success. GitHub also treats neutral and skipped as passing for a required check; here ci/* is the
    evidence that the validation ran and passed, and a skipped run validated nothing, so they fail, as does a value not known yet.
    A null conclusion has not reported an outcome, even if status already says completed, so keep waiting for that outcome."""
    conclusion = run.get("conclusion")
    if run.get("status") != "completed" or conclusion is None:
        return "pending"
    return "success" if conclusion == "success" else "failure"
```

READ FROM CODE — Full corrected existing test (including its full parameter table), path `head/cmapi/tests/service/test_github_check_runs.py`:

```python
@pytest.mark.parametrize("conclusion,expected", [
    ("failure", "failure"), ("cancelled", "failure"), ("timed_out", "failure"),
    ("action_required", "failure"), ("stale", "failure"), ("startup_failure", "failure"),
    ("neutral", "failure"), ("skipped", "failure"), (None, "pending"),
    ("a-conclusion-github-adds-later", "failure"),
])
def test_a_completed_run_that_is_not_success_is_not_green(conclusion, expected):
    """GitHub treats neutral and skipped as passing for a required check. cmapi does not: ci/* is the evidence that the validation
    ran and passed, and a run that was skipped validated nothing. A value GitHub adds later fails closed too.
    A null conclusion is still pending because no outcome has been reported."""
    assert checks(runs=[run(CONTEXT_KUBECONFORM, conclusion=conclusion)]) == {CONTEXT_KUBECONFORM: expected}
```

READ FROM CODE — Full new regression file, path `head/cmapi/tests/service/test_review_r87_c5_c8.py`. It also exercises missing/pending commit statuses and check runs, queued/in_progress/completed-null runs, the worker gate with an already-green cmapi/check, and 12 main-versus-head stand-in scenarios.

```python
"""Adversarial C5–C8 checks; mock GitHub only, existing DB fixture only."""
import pytest

from cmapi.core.ports import Finding
from test_flow import NS, OLA, auth
from test_review_d_delivery import run_until, status
from test_github_check_runs import (
    CONTEXT_CMAPI, CONTEXT_KUBECONFORM, CONTEXT_KYVERNO,
    on_github, poll, pr_checks_job, checks, run,
)


def test_completed_run_without_a_conclusion_remains_pending():
    assert checks(runs=[run(CONTEXT_KYVERNO, conclusion=None)]) == {
        CONTEXT_KYVERNO: 'pending',
    }


@pytest.mark.parametrize('source,state', [
    ('commit-status', 'missing'), ('commit-status', 'pending'), ('commit-status', 'failure'),
    ('check-run', 'missing'), ('check-run', 'pending'), ('check-run', 'queued'),
    ('check-run', 'in_progress'), ('check-run', 'completed-null'), ('check-run', 'failure'),
])
def test_only_cmapi_and_one_ci_green_cannot_merge(on_github, source, state):
    client, ctx, fake, host, validator, keys, rid = on_github
    head = fake.heads[fake.prs[1]['branch']]
    fake.set_check(head, CONTEXT_CMAPI, 'success', 'already approved')
    if source == 'commit-status':
        fake.set_check(head, CONTEXT_KUBECONFORM, 'success', 'schema ok')
        if state != 'missing':
            fake.set_check(head, CONTEXT_KYVERNO, state, 'host CI')
    else:
        host.report(CONTEXT_KUBECONFORM)
        if state == 'failure':
            host.report(CONTEXT_KYVERNO, conclusion='failure')
        elif state != 'missing':
            host.report(CONTEXT_KYVERNO, status='completed' if state == 'completed-null' else state,
                        conclusion=None)
    poll(ctx)
    assert host.merge_refused == 0, 'worker attempted a merge instead of gating it'
    assert set(host.posted) <= {CONTEXT_CMAPI}
    if state == 'failure':
        assert status(client, keys, rid)['status'] == 'failed'
        assert fake.prs[1]['state'] == 'closed'
    else:
        assert status(client, keys, rid)['status'] == 'pr_open'
        assert fake.prs[1]['state'] == 'open'
        assert host.posted == []
        still, attempts, why = pr_checks_job(ctx)
        assert still and attempts == 0 and CONTEXT_KYVERNO in why


@pytest.mark.parametrize('source', [None, 'kubeconform', 'kyverno', 'cmapi'])
@pytest.mark.parametrize('host_state', ['missing', 'pending', 'failure'])
def test_no_external_ci_preserves_main_semantics(world, monkeypatch, source, host_state):
    client, ctx, fake, kube, validator, keys = world
    rid = client.post('/api/v1/clusters/CRC/namespaces', json=NS,
                      headers=auth(keys, 'ola', **OLA)).json()['requestId']
    assert run_until(ctx, 'pr_checks') == 'pr_checks'
    head = fake.heads[fake.prs[1]['branch']]
    if host_state != 'missing':
        fake.set_check(head, CONTEXT_KYVERNO, host_state, 'old host report')
    findings = [] if source is None else [Finding(source=source, rule='r', path='p', message='refused')]
    calls = []

    def validate(tree, cluster_id, env):
        calls.append((tree, cluster_id, env))
        return findings

    monkeypatch.setattr(validator, 'validate', validate)
    assert fake.external_ci is False
    poll(ctx)
    assert len(calls) == 1
    assert fake.statuses[head] == {
        CONTEXT_KUBECONFORM: 'failure' if source in ('kubeconform', 'cmapi') else 'success',
        CONTEXT_KYVERNO: 'failure' if source == 'kyverno' else 'success',
        CONTEXT_CMAPI: 'success',
    }
    assert status(client, keys, rid)['status'] == ('failed' if findings else 'merged')
    assert fake.prs[1]['state'] == ('closed' if findings else 'merged')
```

READ FROM CODE — R87-C6 complete patch against the exported original head, including the new file: [patches/R87-C6.patch](patches/R87-C6.patch).

READ FROM CODE — R87-C7 root cause: the moved-head test only added an unapproved file. The file/tree guards reject that commit even if the exact approved-head comparison is removed. The test therefore did not isolate the behavior named in its docstring. The fix retains that scenario and adds a different SHA with exactly the approved tree. The sensitivity test selects the new case explicitly when that parameter is available.

MEASURED — Before R87-C7, M4 removed `and head == pr.head_sha` and all `83` original tests passed, exit 0. `C7-final-sensitivity-before` exited 1: the named test did not raise under that mutant. After R87-C7, `C7-final-sensitivity-after` exited 0: `1 passed`; the original named test now detects the mutant. The complete suite mutation rerun is recorded as `M4-after-corrected-test-fix` in tests.md: `1 failed, 83 passed`, exit 1. An earlier rerun (`M4-after-test-fix`) stopped at collection because a default argument was invalid for pytest parametrization; that result is not counted as a killed mutant. No production head-guard change is needed.

READ FROM CODE — Full replacement test, path `head/cmapi/tests/service/test_github_check_runs.py`:

```python
@pytest.mark.parametrize("same_tree", [False, True], ids=["changed-files", "same-files-new-commit"])
def test_green_ci_does_not_excuse_a_head_that_moved(on_github, same_tree):
    """Actions passing on a pushed commit is not approval of it, even when its tree is unchanged."""
    client, ctx, fake, host, validator, keys, rid = on_github
    branch = fake.prs[1]["branch"]
    if same_tree:
        # A metadata-only/empty commit: the host reports a new SHA with identical files.
        fake.heads[branch] = "d" * 40
    else:
        fake.tamper(branch, "clusters/CRC/namespaces/payments-dev/extra.yaml", "kind: ConfigMap\n")
    host.report(CONTEXT_KUBECONFORM)
    host.report(CONTEXT_KYVERNO)
    poll(ctx)
    assert status(client, keys, rid)["status"] == "failed" and host.merge_refused == 0
    assert host.posted == [CONTEXT_CMAPI]
    assert fake.statuses[fake.heads[branch]][CONTEXT_CMAPI] == "failure"
```

READ FROM CODE — Full failing-before/passing-after mutation-sensitivity test file, path `head/cmapi/tests/service/test_review_r87_c7_sensitivity.py`:

```python
"""Mutation sensitivity of the named moved-head regression test."""
import importlib
import inspect

import pytest

from cmapi.jobs import HANDLERS
from test_github_check_runs import (
    on_github,
    test_green_ci_does_not_excuse_a_head_that_moved as moved_head_check,
)


def test_named_moved_head_check_detects_removal_of_the_approved_head_guard(on_github, monkeypatch):
    module = importlib.import_module('cmapi.jobs.pr_checks')
    source = inspect.getsource(module.pr_checks)
    assert source.count('and head == pr.head_sha') == 1
    namespace = dict(vars(module))
    exec(compile(source.replace('and head == pr.head_sha', 'and True'), '<head-guard-mutant>', 'exec'), namespace)
    monkeypatch.setitem(HANDLERS, 'pr_checks', namespace['pr_checks'])
    # Also runs against the original test, which had only its one changed-file scenario.
    kwargs = {'same_tree': True} if 'same_tree' in inspect.signature(moved_head_check).parameters else {}
    with pytest.raises(AssertionError):
        moved_head_check(on_github, **kwargs)
```

READ FROM CODE — R87-C7 complete patch against the exported original head, including the new file: [patches/R87-C7.patch](patches/R87-C7.patch).

MEASURED — Final combined validation: `108 passed in 30.93s`, exit 0. Both original authorized files and both review-added files ran in one pytest process. Both repair patches also passed independent and combined dry-runs/applications with `/usr/bin/patch -p1 --fuzz=0`; combined output files exactly match the tested head. Production GitHub code outside `_run_state`, including C3, and all of pr_checks.py remain byte-identical to the supplied export.
