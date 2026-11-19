"""#446, #452 (Codex's F3, F9 of the Git delivery review, as OB3 corrected them): the Git layer never writes through a symlink
the repository holds, and a folder that starts with "-" is a path. Real Git over file:// only."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from cmapi.core.git.base import BranchRequest
from cmapi.core.git.workspace import GitFailed, GitWorkspace
from gitserver import bare_repo, git

# As the renderer makes it (core/render/manifests.folder): with the trailing slash.
FOLDER = "clusters/CRC/namespaces/demo/"
REL = FOLDER + "namespace.yaml"


def req(**kw) -> BranchRequest:
    r = BranchRequest("CRC", "req-1", FOLDER, "hash", "create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
                      {REL: "kind: Namespace\n"}, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))
    return replace(r, **kw)


def person_pushes(tmp_path, bare, build) -> None:
    """A person's commit on main, made in a clone of their own."""
    work = tmp_path / "person"
    git("clone", "--quiet", str(bare), str(work), cwd=tmp_path, home=tmp_path)
    build(work)
    git("add", "--all", cwd=work, home=tmp_path)
    git("commit", "--quiet", "-m", "a person's commit", cwd=work, home=tmp_path)
    git("push", "--quiet", "origin", "main", cwd=work, home=tmp_path)


def test_a_symlinked_manifest_in_the_repository_is_never_written_through(tmp_path):
    bare = bare_repo(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("must survive\n")

    def build(work):
        (work / FOLDER).mkdir(parents=True)
        (work / REL).symlink_to(outside)
    person_pushes(tmp_path, bare, build)
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        with pytest.raises(GitFailed) as refused:
            ws.push_branch(req())
        assert outside.read_text() == "must survive\n"
        assert "symlink" in str(refused.value)
    finally:
        ws.dispose()


def test_a_symlinked_parent_folder_is_never_written_through(tmp_path):
    """clusters/CRC is a symlink to a folder outside: cone mode checks out the files of every parent folder, this link too."""
    bare = bare_repo(tmp_path)
    outside = tmp_path / "outside-dir"
    outside.mkdir()

    def build(work):
        (work / "clusters").mkdir()
        (work / "clusters" / "CRC").symlink_to(outside)
    person_pushes(tmp_path, bare, build)
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        with pytest.raises(GitFailed) as refused:
            ws.push_branch(req())
        assert sorted(str(p.relative_to(outside)) for p in outside.rglob("*")) == [], "nothing was made outside the worktree"
        assert "symlink" in str(refused.value)
    finally:
        ws.dispose()


def test_a_leading_dash_folder_is_a_path_not_an_option(tmp_path):
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        request = req(folder="-folder/", files={"-folder/namespace.yaml": "kind: Namespace\n"})
        pushed = ws.push_branch(request)
        assert ws.read_folder("-folder", pushed.head)[0] == {"-folder/namespace.yaml": "kind: Namespace\n"}
    finally:
        ws.dispose()


def test_the_renderers_folder_with_its_trailing_slash_is_still_delivered(tmp_path):
    """Control: core/render/manifests.folder ends in "/". Codex's patch ran check_path on it unstripped, which refuses an empty
    part, so every real request failed at push_branch."""
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        pushed = ws.push_branch(req())
        assert pushed.result == "created"
        assert ws.read_folder(FOLDER, pushed.head)[0] == {REL: "kind: Namespace\n"}
    finally:
        ws.dispose()


@pytest.mark.parametrize("folder", ["../escape/", "clusters/../../x/"])
def test_a_folder_that_is_not_a_repository_path_is_refused(tmp_path, folder):
    bare = bare_repo(tmp_path)
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        with pytest.raises(ValueError, match="not a repository path"):
            ws.push_branch(req(folder=folder, files={}))
    finally:
        ws.dispose()
