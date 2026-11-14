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

    def validate(tree, cluster_id, env, previous=None):     # previous: the default branch's folder (#212)
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
