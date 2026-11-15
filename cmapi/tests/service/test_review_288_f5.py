"""PR #288 review, F5: host CI (instance.git.hostChecks, external_ci) still drives jobs/pr_checks.py: a failed ci/* fails the
request at once, a missing one is a wait that spends no attempts and ends at syncTimeout, and green CI excuses neither a moved
head nor the worker's own validator. b660758 removed the tests of these paths with tests/service/test_github_check_runs.py and
test_review_r87_c5_c8.py (their Checks API parts are gone; these paths are not). Ported from 77d069e onto FakeGit's statuses."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from cmapi.core.ports import Finding
from cmapi.jobs.pr_checks import CONTEXT_CMAPI, CONTEXT_KUBECONFORM, CONTEXT_KYVERNO
from cmapi.worker import Worker
from test_flow import NS, OLA, auth
from test_review_d_delivery import run_until, status
from test_review_e_recovery import lease_expired


def poll(ctx, n=1):
    worker = Worker(ctx, "w")
    for _ in range(n):
        lease_expired(ctx)
        assert worker.run_one()


def pending(ctx, kind):
    with ctx.db.session() as s:
        return s.execute(text("select attempts, last_error from jobs where kind=:k and done_at is null"), {"k": kind}).one_or_none()


@pytest.fixture
def host_ci(world):
    client, ctx, fake, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "pr_checks") == "pr_checks"
    fake.external_ci = True
    head = fake.heads[fake.prs[1]["branch"]]
    return client, ctx, fake, validator, keys, rid, head


def report(fake, head, **states):
    fake.statuses.setdefault(head, {}).update({f"ci/{k}": v for k, v in states.items()})


@pytest.mark.parametrize("failed", [CONTEXT_KUBECONFORM, CONTEXT_KYVERNO])
def test_a_failed_host_ci_context_fails_the_request_and_closes_the_pr_without_waiting(host_ci, failed):
    client, ctx, fake, validator, keys, rid, head = host_ci
    fake.statuses[head] = {failed: "failure"}            # the other context has not reported: a failure does not wait for it
    poll(ctx)
    view = status(client, keys, rid)
    assert view["status"] == "failed" and fake.prs[1]["state"] == "closed", view["events"]
    assert fake.statuses[head][failed] == "failure", "the worker never posts a ci/* context that host CI owns"
    assert any(failed in (e["note"] or "") and "failure" in (e["note"] or "") for e in view["events"]), view["events"]
    assert pending(ctx, "apply") is None and pending(ctx, "merge") is None


def test_a_host_ci_context_not_reported_yet_is_a_wait_that_spends_no_attempts_and_both_are_needed(host_ci):
    client, ctx, fake, validator, keys, rid, head = host_ci
    report(fake, head, kubeconform="success")             # one green context and the cmapi check are not enough
    poll(ctx, 3)
    view = status(client, keys, rid)
    assert view["status"] == "pr_open" and fake.prs[1]["state"] == "open"
    attempts, why = pending(ctx, "pr_checks")
    assert attempts == 0 and CONTEXT_KYVERNO in why, (attempts, why)
    assert sum(e["event"] == "ci_wait" for e in view["events"]) == 1, "one event for one reason, not one per poll"
    assert CONTEXT_CMAPI not in fake.statuses[head] and pending(ctx, "apply") is None, "nothing is posted or applied while CI runs"
    report(fake, head, kyverno="success")
    poll(ctx)
    assert status(client, keys, rid)["status"] == "pr_open" and pending(ctx, "pr_checks") is None
    assert fake.statuses[head][CONTEXT_CMAPI] == "success" and pending(ctx, "apply") is not None


def test_host_ci_that_never_reports_fails_the_request_when_the_clock_runs_out(host_ci):
    client, ctx, fake, validator, keys, rid, head = host_ci
    ctx.delivery = type(ctx.delivery)(**{**ctx.delivery.__dict__, "poll_seconds": 0, "sync_timeout_seconds": 0})
    poll(ctx)
    view = status(client, keys, rid)
    assert view["status"] == "failed" and fake.prs[1]["state"] == "closed", view["events"]
    assert any(CONTEXT_KUBECONFORM in (e["note"] or "") for e in view["events"]), view["events"]
    assert pending(ctx, "pr_checks") is None and pending(ctx, "apply") is None


@pytest.mark.parametrize("same_tree", [False, True], ids=["changed-files", "same-files-new-commit"])
def test_green_host_ci_does_not_excuse_a_head_that_moved(host_ci, same_tree):
    """Host CI passing on a pushed commit is not approval of it, even when its tree is the plan's."""
    client, ctx, fake, validator, keys, rid, head = host_ci
    branch = fake.prs[1]["branch"]
    if same_tree:
        fake.heads[branch] = "d" * 40                      # a new commit with the same files
    else:
        fake.tamper(branch, "clusters/CRC/namespaces/payments-dev/extra.yaml", "kind: ConfigMap\n")
    report(fake, fake.heads[branch], kubeconform="success", kyverno="success")
    poll(ctx)
    assert status(client, keys, rid)["status"] == "failed" and pending(ctx, "apply") is None
    assert fake.statuses[fake.heads[branch]][CONTEXT_CMAPI] == "failure"


def test_green_host_ci_does_not_excuse_the_workers_own_validator(host_ci):
    client, ctx, fake, validator, keys, rid, head = host_ci
    validator.findings = [Finding(source="kyverno", rule="r", path="p", message="refused")]
    report(fake, head, kubeconform="success", kyverno="success")
    poll(ctx)
    assert status(client, keys, rid)["status"] == "failed" and pending(ctx, "apply") is None


# The adapter cases of test_github_check_runs.py that are about the PR and the statuses, not the Checks API.
import httpx  # noqa: E402

from cmapi.core.git.base import GitUnavailable  # noqa: E402
from cmapi.core.git.github import GitHubProvider  # noqa: E402
from cmapi.core.ports import PrRef  # noqa: E402

API, SHA = "https://github.test", "c" * 40
PR = PrRef(7, "https://github.test/o/r/pull/7", "cmapi/CRC/r1", SHA)


def adapter(handle):
    git = GitHubProvider(API, "o/r", "token", host_checks=True)
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    return git


@pytest.mark.parametrize("code", [401, 403, 404])
def test_a_refused_read_of_the_pr_itself_raises(code):
    with pytest.raises(GitUnavailable, match=str(code)):
        adapter(lambda r: httpx.Response(code, json={"message": "no"})).pr_status(PR)


def test_a_refused_later_page_of_statuses_raises():
    def handle(request):
        if request.url.path == "/repos/o/r/pulls/7":
            return httpx.Response(200, json={"state": "open", "merged": False, "head": {"sha": SHA, "ref": PR.branch}})
        if request.url.params.get("page", "1") == "1":
            return httpx.Response(200, json={"statuses": [{"context": CONTEXT_CMAPI, "state": "success"}]},
                                  headers={"Link": f'<{API}{request.url.path}?page=2>; rel="next"'})
        return httpx.Response(403, json={"message": "Resource not accessible"})
    with pytest.raises(GitUnavailable, match="403"):
        adapter(handle).pr_status(PR)
