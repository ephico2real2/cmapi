"""A branch name is data in a URL path. Git accepts "#" and "%" in a branch name (git check-ref-format --branch 'release#2'),
and RFC 3986, section 3.3: "The path is terminated by the first question mark ("?") or number sign ("#") character". Unquoted,
the default branch release#2 read the head of the branch release."""
from __future__ import annotations

import httpx
import pytest

from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider


@pytest.mark.parametrize("branch", ["release#2", "rel%41", "team/main"])
@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
def test_a_branch_name_stays_in_the_path(provider, branch):
    asked = []

    def host(request):
        asked.append(request.url.path)
        return httpx.Response(200, json={"commit": {"sha": "a" * 40, "id": "a" * 40}})

    git = provider("https://h.test", "o/r", "", default_branch=branch)
    git._client = httpx.Client(base_url="https://h.test", transport=httpx.MockTransport(host))
    assert git.branch_head(branch) == "a" * 40
    assert asked == [f"/repos/o/r/branches/{branch}"]
