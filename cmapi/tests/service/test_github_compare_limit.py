"""#199 (BUG-52): GitHub's compare lists at most 300 changed files, so the adapter never reads such a list as complete.

GitHub, "Compare two commits": "The list of changed files is only shown on the first page of results, and it includes up to
300 changed files for the entire comparison." The port says "every path", and pr_checks uses the list to refuse a branch that
touches a path outside the plan. A plan of today has a few files, so a cut list of 300 names always holds a path outside it:
the rule matters for a plan of 300 files or more, and it holds the port to what it says.
"""
from __future__ import annotations

import httpx
import pytest

from cmapi.core.git.base import GitUnavailable, IncompleteList
from cmapi.core.git.github import GitHubProvider
from cmapi.jobs.pr_checks import CONTEXT_CMAPI
from test_flow import NS, OLA, auth
from test_github_check_runs import API, SHA, poll
from test_review_d_delivery import run_until, status


def compare_of(count: int) -> GitHubProvider:
    def handle(request):
        assert request.url.path == f"/repos/o/r/compare/main...{SHA}"
        return httpx.Response(200, json={"ahead_by": 1, "files": [{"filename": f"clusters/CRC/ns/f{i}.yaml"} for i in range(count)]})
    git = GitHubProvider(API, "o/r", "token")
    git._client = httpx.Client(base_url=API, transport=httpx.MockTransport(handle))
    return git


def test_a_comparison_under_the_limit_is_read_in_full():
    assert len(compare_of(299).changed_paths(SHA)) == 299


@pytest.mark.parametrize("count", [300, 301])
def test_a_comparison_at_the_limit_is_not_read_as_complete(count):
    """With 300 names GitHub can have cut the list: file 301 is the one that the answer cannot hold."""
    with pytest.raises(IncompleteList, match="300 files or more"):
        compare_of(count).changed_paths(SHA)
    assert issubclass(IncompleteList, GitUnavailable), "a caller that does not handle it reads the host as unavailable"


def test_the_cmapi_check_fails_when_the_host_cannot_list_each_changed_file(world):
    """pr_checks does not wait for a list that will never be complete: the check fails and the request ends."""
    client, ctx, fake, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "pr_checks") == "pr_checks"

    def cut(head):
        raise IncompleteList(f"{head[:8]} changes 300 files or more, and GitHub lists no more than that")
    fake.changed_paths = cut
    poll(ctx)
    pr = next(iter(fake.prs.values()))
    assert status(client, keys, rid)["status"] == "failed"
    assert pr["state"] == "closed" and pr["merge_sha"] is None
    assert [checks[CONTEXT_CMAPI] for checks in fake.statuses.values()] == ["failure"]
