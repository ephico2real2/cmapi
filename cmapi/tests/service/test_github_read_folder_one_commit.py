"""GitHub REST reads a folder at one commit, also when the default branch's name has 40 characters (review of #492,
F07): the folder's etag and the Git metadata of GET .../namespaces/{ns} then come from one commit."""
from __future__ import annotations

import base64
from unittest.mock import Mock

import pytest

from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.core.pipeline import folder_etag


def test_github_reads_every_file_at_one_commit_when_the_default_branch_has_40_characters(monkeypatch):
    branch = "production".ljust(40, "-")
    git = GitHubProvider("https://example.invalid", "o/r", "", default_branch=branch)
    first, second = "a" * 40, "b" * 40
    current = first
    paths = ["folder/namespace.yaml", "folder/quota.yaml"]

    def answer(operation, method, path, **kw):
        nonlocal current
        if operation == "branch_head":
            return Mock(status_code=200, json=lambda: {"commit": {"sha": current}})
        ref = kw["params"]["ref"]
        revision = current if ref == branch else ref          # a branch name reads the head of that moment
        if operation == "read_folder":
            return Mock(status_code=200, json=lambda: [{"path": p, "name": p.split("/")[-1], "type": "file"} for p in paths])
        current = second                                      # the branch moves after the first file is read
        return Mock(status_code=200, json=lambda: {"content": base64.b64encode(revision.encode()).decode()})

    monkeypatch.setattr(git, "_call", answer)
    files, sha = git.read_folder("folder")
    assert files == dict.fromkeys(paths, first) and sha == first
    assert folder_etag(files) == folder_etag(dict.fromkeys(paths, first))


@pytest.mark.parametrize("provider", [GitHubProvider, GiteaProvider])
def test_default_branch_and_explicit_commit_with_the_same_spelling(provider, monkeypatch):
    configured, tip = "a" * 40, "b" * 40
    git = provider("https://example.invalid", "o/r", "", default_branch=configured)
    branch = Mock(return_value=tip if provider is GiteaProvider else None)
    monkeypatch.setattr(git, "branch_head", branch)
    path = "folder/namespace.yaml"

    trees = {configured: "c" * 40, tip: "d" * 40}
    blobs = {configured: "e" * 40, tip: "f" * 40}

    def contents(operation, method, url, *, params=None, **kw):
        oid = url.rsplit("/", 1)[1]
        if "/git/trees/" in url:
            if oid in trees:
                entries = [{"type": "tree", "path": "folder", "sha": trees[oid]}]
            else:
                revision = next(k for k, tree in trees.items() if tree == oid)
                entries = [{"type": "blob", "mode": "100644", "path": "namespace.yaml", "sha": blobs[revision]}]
            body = {"tree": entries, "truncated": False}
        elif "/git/blobs/" in url:
            revision = next(k for k, blob in blobs.items() if blob == oid)
            body = {"content": base64.b64encode(revision.encode()).decode()}
        elif operation == "read_folder":
            body = [{"path": path, "name": "namespace.yaml", "type": "file"}]
        else:
            revision = params["ref"]
            if provider is GiteaProvider and revision == configured:
                revision = tip  # Contents checks branches before interpreting a bare object ID.
            body = {"content": base64.b64encode(revision.encode()).decode()}
        return Mock(status_code=200, json=lambda: body)

    monkeypatch.setattr(git, "_call", contents)
    if provider is GitHubProvider:
        # GitHub rejects this branch name, even when that object exists.
        with pytest.raises(GitUnavailable, match="does not exist"):
            git.read_folder("folder")
    else:
        assert git.read_folder("folder") == ({path: tip}, tip)
    assert git.read_folder("folder", configured) == ({path: configured}, configured)
    branch.assert_called_once_with(configured)


def _gitea(monkeypatch, head, root_pages):
    """A Gitea whose root tree comes in these pages, and whose folder holds a file, a symbolic link and a submodule."""
    git = GiteaProvider("https://example.invalid", "o/r", "", default_branch="main")
    monkeypatch.setattr(git, "branch_head", Mock(return_value=head))
    asked = []

    def call(operation, method, url, *, params=None, **kw):
        if "/git/blobs/" in url:
            body = {"content": base64.b64encode(b"kind: Namespace\n").decode()}
        elif url.rsplit("/", 1)[1] == head:
            asked.append(params["page"])
            body = root_pages[params["page"] - 1]
        else:
            body = {"tree": [{"type": "blob", "mode": "100644", "path": "namespace.yaml", "sha": "e" * 40},
                             {"type": "blob", "mode": "120000", "path": "link.yaml", "sha": "f" * 40},
                             {"type": "commit", "mode": "160000", "path": "module.yaml", "sha": "9" * 40}],
                    "truncated": False, "page": 1}
        return Mock(status_code=200, json=lambda: body)

    monkeypatch.setattr(git, "_call", call)
    return git, asked


def test_gitea_follows_a_tree_that_the_host_cuts_into_pages_and_reads_regular_files_only(monkeypatch):
    head = "a" * 40
    pages = [{"tree": [{"type": "tree", "path": "another", "sha": "b" * 40}], "truncated": True, "page": 1},
             {"tree": [{"type": "tree", "path": "folder", "sha": "c" * 40}], "truncated": False, "page": 2}]
    git, asked = _gitea(monkeypatch, head, pages)
    assert git.read_folder("folder") == ({"folder/namespace.yaml": "kind: Namespace\n"}, head)
    assert asked == [1, 2]


def test_gitea_refuses_a_cut_page_that_it_cannot_continue(monkeypatch):
    git, _ = _gitea(monkeypatch, "a" * 40, [{"tree": None, "truncated": True, "page": 1}])
    with pytest.raises(GitUnavailable, match="incomplete page 1"):
        git.read_folder("folder")


def test_gitea_reads_a_sha256_commit_as_it_is_and_github_has_no_such_commit(monkeypatch):
    commit = "c" * 64
    gitea = GiteaProvider("https://example.invalid", "o/r", "", default_branch="main")
    branch = Mock(return_value=None)
    monkeypatch.setattr(gitea, "branch_head", branch)
    monkeypatch.setattr(gitea, "_call", lambda *a, **kw: Mock(status_code=200, json=lambda: {"tree": [], "truncated": False}))
    assert gitea.read_folder("folder", commit) == ({}, commit)
    branch.assert_not_called()
    # Only a provider that says so reads 64 hex characters as an object ID. GitHub's keeps the default, and reads a branch name.
    github = GitHubProvider("https://example.invalid", "o/r", "", default_branch="main")
    monkeypatch.setattr(github, "branch_head", Mock(return_value=None))
    with pytest.raises(GitUnavailable, match="does not exist"):
        github.read_folder("folder", commit)
