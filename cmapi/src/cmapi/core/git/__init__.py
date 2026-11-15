"""GitProvider adapters (core/ports.py): the bot's view of the cluster-configs repository.

Two layers since #286, as Renovate has them: a Git layer (workspace.py, transport.py) that writes and reads with the Git
protocol alone, the same for every host, and a thin platform adapter per host for the PR alone.

    github   The Git layer, plus GitHub's REST API for the PR: open, state, merge with an expected head, comment, close
    gitea    Gitea's REST API for everything: the stand-in of the chart (deploy/helm/cmapi-git). Not on the Git layer yet

The worker is the only writer, and nothing ever pushes to the default branch: every change is a request branch and a PR.
"""
from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

from cmapi.core.git.base import BranchRequest, GitUnavailable, HostGitProvider
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.core.git.transport import GitConfigError
from cmapi.core.git.workspace import GitWorkspace, request_branch

PROVIDERS: dict[str, Any] = {"gitea": GiteaProvider, "github": GitHubProvider}
ON_GIT_LAYER = {"github"}


def clone_url(kind: str, repository: str, web_url: str | None, url: str | None) -> str:
    """instance.git.url, else the host's usual HTTPS clone URL: <webUrl>/<owner>/<repo>.git."""
    if url:
        return url
    return f"{(web_url or 'https://github.com').rstrip('/')}/{repository}.git"


def make_provider(kind: str, api_url: str, repository: str, token: str, *, default_branch: str = "main",
                  verify: ssl.SSLContext | str | bool = True, web_url: str | None = None,
                  basic_auth: tuple[str, str] | None = None, git_layer: bool = False, git_url: str | None = None,
                  workdir: Path | str | None = None, credentials_dir: Path | str = "/etc/cmapi/git-bot",
                  ssh_dir: Path | str | None = None, known_hosts_dir: Path | str | None = None,
                  ca_bundle: Path | str | None = None, username: str | None = None, commit_email: str | None = None,
                  host_checks: bool = False) -> HostGitProvider:
    """git_layer: the worker writes through the Git layer; the API process reads through the host API alone (F2)."""
    if kind not in PROVIDERS:
        raise ValueError(f"unknown git provider {kind}; one of {sorted(PROVIDERS)}")
    if kind in ON_GIT_LAYER:
        workspace = None
        if git_layer:
            workspace = GitWorkspace(clone_url(kind, repository, web_url, git_url), default_branch=default_branch, workdir=workdir,
                                     credentials_dir=credentials_dir, ssh_dir=ssh_dir, known_hosts_dir=known_hosts_dir,
                                     ca_bundle=ca_bundle, username=username, commit_email=commit_email)
        return PROVIDERS[kind](api_url, repository, token, default_branch=default_branch, verify=verify, web_url=web_url,
                               basic_auth=basic_auth, workspace=workspace, host_checks=host_checks)
    return PROVIDERS[kind](api_url, repository, token, default_branch=default_branch, verify=verify, web_url=web_url,
                           basic_auth=basic_auth)


__all__ = ["BranchRequest", "GitConfigError", "GitUnavailable", "GitWorkspace", "GiteaProvider", "GitHubProvider",
           "HostGitProvider", "clone_url", "make_provider", "request_branch"]
