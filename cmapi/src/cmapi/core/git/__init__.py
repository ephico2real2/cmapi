"""GitProvider adapters (core/ports.py): the bot's view of the cluster-configs repository.

    gitea    Gitea's REST API: the stand-in of the chart (deploy/helm/cmapi-git)
    github   GitHub's REST API, the design's default and the Git host of CRC's plain manifests (#157):
             ephico2real2/cmapi-cluster-configs. Its trust is settings.git_verify (#97)

Both open a bot branch from the planned base commit, write the files in one commit, open a PR,
report its status, set the cmapi check as a commit status, merge with an expected head, and
close. The worker is the only caller.
"""
from __future__ import annotations

import ssl

from cmapi.core.git.base import GitUnavailable, HostGitProvider
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider

PROVIDERS = {"gitea": GiteaProvider, "github": GitHubProvider}


def make_provider(kind: str, api_url: str, repository: str, token: str, *, default_branch: str = "main",
                  verify: ssl.SSLContext | str | bool = True, web_url: str | None = None,
                  basic_auth: tuple[str, str] | None = None) -> HostGitProvider:
    if kind not in PROVIDERS:
        raise ValueError(f"unknown git provider {kind}; one of {sorted(PROVIDERS)}")
    return PROVIDERS[kind](api_url, repository, token, default_branch=default_branch, verify=verify, web_url=web_url,
                           basic_auth=basic_auth)


__all__ = ["GitUnavailable", "GiteaProvider", "GitHubProvider", "HostGitProvider", "make_provider"]
