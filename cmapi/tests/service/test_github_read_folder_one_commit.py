"""GitHub REST reads a folder at one commit, also when the default branch's name has 40 characters (review of #492,
F07): the folder's etag and the Git metadata of GET .../namespaces/{ns} then come from one commit."""
from __future__ import annotations

import base64
from unittest.mock import Mock

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
