"""GitHub's PR adapter reads commit statuses alone, and only when host CI is on (#286; the arbitration, row 11). Never the
Checks API: a fine-grained token cannot call it (BUG-69, #279). Ported from test_github_check_runs.py (#87), whose check-run
cases went with the Checks API. The provider runs on a MockTransport shaped by GitHub's REST docs (2026-11)."""
from __future__ import annotations

import httpx
import pytest

from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.github import GitHubProvider
from cmapi.core.ports import PrRef
from cmapi.jobs.pr_checks import CONTEXT_CMAPI, CONTEXT_KYVERNO

SHA = "c" * 40
API = "https://github.test"
PR = PrRef(7, "https://github.test/o/r/pull/7", "cmapi/CRC/r1", SHA)


def st(context, state="success"):
    return {"context": context, "state": state}


def paged(request, key, items):
    per_page, page = min(int(request.url.params.get("per_page", 30)), 100), int(request.url.params.get("page", 1))
    chunk = items[(page - 1) * per_page:page * per_page]
    headers = {}
    if page * per_page < len(items):
        headers["Link"] = f'<{API}{request.url.path}?per_page={per_page}&page={page + 1}>; rel="next"'
    return httpx.Response(200, json={"total_count": len(items), key: chunk}, headers=headers)


def provider(statuses=(), *, seen=None, pr=None, on_statuses=None, host_checks=True):
    def handle(request):
        if seen is not None:
            seen.append(request)
        path = request.url.path
        assert "check-runs" not in path and "check-suites" not in path, "the Checks API is never called"
        if path == "/repos/o/r/pulls/7":
            return httpx.Response(200, json=pr or {"state": "open", "merged": False, "head": {"sha": SHA, "ref": PR.branch}})
        if path == f"/repos/o/r/commits/{SHA}/status":
            return on_statuses(request) if on_statuses else paged(request, "statuses", list(statuses))
        return httpx.Response(404, json={"message": f"not routed: {path}"})
    git = GitHubProvider(API, "o/r", "token", host_checks=host_checks)
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    return git


def checks(**kw):
    return dict(provider(**kw).pr_status(PR).checks)


def test_host_ci_off_reads_nothing_and_posts_nothing():
    seen = []
    git = provider(statuses=[st(CONTEXT_KYVERNO, "failure")], seen=seen, host_checks=False)
    assert git.pr_status(PR).checks == {} and not git.external_ci and not git.post_statuses
    assert [r.url.path for r in seen] == ["/repos/o/r/pulls/7"]


@pytest.mark.parametrize("state,expected", [("success", "success"), ("pending", "pending"), ("failure", "failure"), ("error", "failure")])
def test_commit_statuses_read_as_before(state, expected):
    assert checks(statuses=[st(CONTEXT_CMAPI, state)]) == {CONTEXT_CMAPI: expected}


def test_one_context_reported_twice_reads_as_the_worse():
    assert checks(statuses=[st(CONTEXT_KYVERNO, "success"), st(CONTEXT_KYVERNO, "failure")]) == {CONTEXT_KYVERNO: "failure"}


def test_a_failure_on_a_later_page_of_statuses_counts():
    got = checks(statuses=[st(f"other-{i}") for i in range(150)] + [st(CONTEXT_KYVERNO, "failure")])
    assert len(got) == 151 and got[CONTEXT_KYVERNO] == "failure"


def test_the_next_link_is_a_signal_and_is_never_followed_to_another_host():
    """The Authorization header goes with every request on this client, so a URL from a response is never called."""
    seen = []

    def evil(request):
        if request.url.params.get("page", "1") == "1":
            return httpx.Response(200, json={"statuses": [st(CONTEXT_CMAPI)]}, headers={"Link": '<https://evil.test/steal?page=2>; rel="next"'})
        return httpx.Response(200, json={"statuses": []})
    provider(on_statuses=evil, seen=seen).pr_status(PR)
    assert {r.url.host for r in seen} == {"github.test"}


def test_a_host_that_never_stops_paging_is_an_error_not_a_partial_read():
    calls = []

    def endless(request):
        calls.append(request)
        return httpx.Response(200, json={"statuses": [st(CONTEXT_CMAPI)]}, headers={"Link": f'<{API}/x?page=9>; rel="next"'})
    with pytest.raises(GitUnavailable, match="pages"):
        provider(on_statuses=endless).pr_status(PR)
    assert len(calls) == GitHubProvider.MAX_PAGES


@pytest.mark.parametrize("code", [403, 404, 422])
def test_a_refused_read_raises_instead_of_reading_as_no_checks(code):
    with pytest.raises(GitUnavailable, match=str(code)):
        provider(on_statuses=lambda r: httpx.Response(code, json={"message": "Resource not accessible"})).pr_status(PR)


@pytest.mark.parametrize("code", [429, 502])
def test_a_5xx_or_429_is_retryable(code):
    with pytest.raises(GitUnavailable):
        provider(on_statuses=lambda r: httpx.Response(code, text="busy")).pr_status(PR)


@pytest.mark.parametrize("pr,state,merge_sha", [
    ({"state": "closed", "merged": True, "merge_commit_sha": "d" * 40, "head": {"sha": SHA}}, "merged", "d" * 40),
    ({"state": "closed", "merged": False, "merge_commit_sha": "e" * 40, "head": {"sha": SHA}}, "closed", None),
])
def test_a_finished_pr_needs_no_read_of_its_statuses(pr, state, merge_sha):
    got = provider(pr=pr, on_statuses=lambda r: httpx.Response(403, json={"message": "no"})).pr_status(PR)
    assert (got.state, got.merge_sha, dict(got.checks), got.head_sha) == (state, merge_sha, {}, SHA)
