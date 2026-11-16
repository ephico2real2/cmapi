"""Adversarial C5–C8 checks; the existing DB fixture only. The check-run cases (C5, C6) went with the Checks API (#286)."""
import pytest

from cmapi.core.ports import Finding
from test_flow import NS, OLA, auth
from test_review_d_delivery import run_until, status
from cmapi.jobs.pr_checks import CONTEXT_CMAPI, CONTEXT_KUBECONFORM, CONTEXT_KYVERNO
from test_review_e_recovery import lease_expired


def poll(ctx, n=1):
    from cmapi.worker import Worker
    worker = Worker(ctx, "w")
    for _ in range(n):
        lease_expired(ctx)
        assert worker.run_one()


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
    # Since #286 the checks and the merge are two jobs: a pass leaves the PR open with the apply job queued (apply mode).
    assert status(client, keys, rid)['status'] == ('failed' if findings else 'pr_open')
    assert fake.prs[1]['state'] == ('closed' if findings else 'open')
    if not findings:
        assert run_until(ctx, 'apply') == 'apply'
