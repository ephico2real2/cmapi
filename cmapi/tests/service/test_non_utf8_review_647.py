"""PR #647 (#626), reviewers 1 and 2: the reads that #626 left on the worker's retry-then-fail path, and the shown names.

Each test fails on the PR's head and passes with the review's fix:
- F1: _merged read the folder at the merge sha, so a name that landed during the host's merge raised NotUtf8 after the merge,
  five times, and the merged request ended failed (argocd) or merge_failed (apply) with its PR merged on the host.
- F2: pr_checks reads main's folder before the merge check, so a name that landed while the PR was open was five errors and
  failed, where the merge check would have superseded it.
- F3: the Gitea stand-in created the request branch before it read the folder: a read that failed (such a name, or the host)
  left a branch at main's commit, which a retry refuses and git_cleanup keeps as foreign. The push_branch job retried a
  NotUtf8 from the push itself.
- F4: backslashreplace alone shows two different names the same: b"a\\xe9\\\\xff" and b"a\\\\xe9\\xff" are both "a\\xe9\\xff".
  Reviewer 2: so does a name with U+FFFD and a backslash, which the fix of reviewer 1 left verbatim. Every path of NotUtf8 now
  reads back as its bytes.
- F5: the detail, and the note NotUtf8 writes, said "is not UTF-8" of a name that is UTF-8 and holds U+FFFD.
- F6: the contract's examples of folder-not-utf8 and folder-holds-submodule had no `paths`, the member each one carries.
- F7: watch_sync read main's folder outside the merge check's rule: five errors before the sync_failed it ends in anyway.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import random

import httpx
import pytest

from cmapi.core.docs import problem_example
from cmapi.core.git.base import BranchRequest, GitUnavailable, NotUtf8, git_name, manifest_text
from cmapi.core.git.workspace import GitWorkspace
from cmapi.core.pipeline import folder_not_utf8
from gitserver import bare_repo
from test_delete_whole_folder_616 import FOLDER_PATH, HEAD, RestHost, _gitea, _github
from test_delivery_states_db_review import person_merges
from test_git_layer import argocd, drive, layer  # noqa: F401  (layer is the real Git layer's fixture)
from test_github_read_folder_632 import GitHubContents
from test_non_utf8_names_626 import BASE, LATIN1, LOST, MANIFEST, NAMESPACE, SHOWN, commit_bytes

BAD = BASE.encode() + LATIN1


def _notes(view) -> list[tuple[str, str]]:
    return [(e["event"], e["note"] or "") for e in view["events"]]


def _errors(view) -> list[str]:
    return [note for event, note in _notes(view) if event == "error"]


def _until(w, rid: str, status: str, limit: int = 20) -> None:
    """Run the worker one job at a time until the request reaches status."""
    for _ in range(limit):
        if w.view(rid)["status"] == status:
            return
        assert drive(w.ctx, limit=1), f"no job left before {status}: {_notes(w.view(rid))}"
    raise AssertionError(f"never reached {status}: {_notes(w.view(rid))}")


def _mode(w, mode: str) -> None:
    if mode == "argocd":
        argocd(w)
    else:
        w.ctx.delivery = replace(w.ctx.delivery, mode="apply")


# --------------------------------------------------------------------------- F1: after the merge

@pytest.mark.parametrize("mode", ["argocd", "apply"])
def test_a_name_that_lands_during_the_hosts_merge_leaves_the_request_merged_then_sync_failed(layer, mode):  # noqa: F811
    """The host merged: the request must say so. Merged, then sync_failed with the lock held for an operator (_merged's own
    rule for a folder at the merge that is not the plan's), never five errors and then pr_failed or merge_failed."""
    w = layer
    _mode(w, mode)
    rid = w.create()
    w.host.merge_hook = lambda number: commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})

    drive(w.ctx)

    v = w.view(rid)
    assert w.host.prs[1]["merged"], "the host merged the PR"
    assert v["status"] == "sync_failed", _notes(v)
    assert not _errors(v), _notes(v)
    assert any(SHOWN in note for _, note in _notes(v)), "the operator is told which path"


# --------------------------------------------------------------------------- F2: while the PR is open

def test_a_name_that_lands_on_main_while_the_pr_is_open_supersedes_it(layer):  # noqa: F811
    w = layer
    argocd(w)
    rid = w.create()
    _until(w, rid, "pr_open")
    commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})

    drive(w.ctx)

    v = w.view(rid)
    assert v["status"] == "superseded", _notes(v)
    assert not _errors(v), _notes(v)
    assert any(SHOWN in note for _, note in _notes(v))
    assert w.host.prs[1]["state"] == "closed" and not w.host.prs[1]["merged"]


# --------------------------------------------------------------------------- F7: after the merge, waiting for the sync

def test_watch_sync_reads_a_folder_it_cannot_name_as_not_the_plans(layer):  # noqa: F811
    w = layer
    argocd(w)
    rid = w.create()
    _until(w, rid, "merged")
    commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})

    drive(w.ctx)

    v = w.view(rid)
    assert v["status"] == "sync_failed", _notes(v)
    assert not _errors(v), _notes(v)


def test_watch_sync_in_apply_mode_reads_a_folder_it_cannot_name_as_not_the_plans(layer):  # noqa: F811
    """Apply mode reaches watch_sync after a person's merge before the apply: it applies from main, so it reads main first."""
    w = layer                                  # apply mode
    rid = w.create()
    assert drive(w.ctx, limit=3) == ["push_branch", "open_pr", "pr_checks"]
    branch = f"cmapi/CRC/{rid}"
    person_merges(w, branch, w.host.head(branch))
    commit_bytes(w.bare, w.tmp, {BAD: b"kind: ConfigMap\n"})

    drive(w.ctx)

    v = w.view(rid)
    assert v["status"] == "sync_failed", _notes(v)
    assert not _errors(v), _notes(v)
    assert "applied" not in w.events(rid), "nothing applied from that main"


# --------------------------------------------------------------------------- F3: the push itself

def test_a_name_the_push_finds_supersedes_the_request(layer, monkeypatch):  # noqa: F811
    """The Gitea stand-in reads the folder as it writes the branch: a name that landed after push_branch's own read."""
    w = layer
    argocd(w)

    def found(req):
        raise NotUtf8([SHOWN], "name")

    monkeypatch.setattr(w.ctx.git, "push_request_branch", found)
    rid = w.create()

    drive(w.ctx)

    v = w.view(rid)
    assert v["status"] == "superseded", _notes(v)
    assert not _errors(v), _notes(v)
    assert any(SHOWN in note for _, note in _notes(v))


class _Branching(RestHost):
    """RestHost, where the request branch, once created, is main's commit as Gitea makes it, and can be deleted."""

    BRANCH = "/branches/cmapi/CRC/req-1"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1").removeprefix("/repos/o/r")
        if request.method == "GET" and path == self.BRANCH and self.branch_exists:
            self.calls.append(("GET", path, {}))
            return httpx.Response(200, json={"commit": {"id": HEAD}})
        if request.method == "DELETE" and path == self.BRANCH:
            self.calls.append(("DELETE", path, {}))
            self.branch_exists = False
            return httpx.Response(204)
        return super().__call__(request)


class _Down(_Branching):
    """_Branching, whose tree reads answer 503, as a Git host in an outage does."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if "/git/trees/" in request.url.path:
            return httpx.Response(503, json={"message": "unavailable"})
        return super().__call__(request)


@pytest.mark.parametrize("host, error", [(_Branching({**MANIFEST, LOST: ("blob", "100644")}), NotUtf8),
                                         (_Down(MANIFEST), GitUnavailable)], ids=["lost-name", "host-down"])
def test_the_gitea_stand_in_leaves_no_branch_when_it_cannot_read_the_folder(host, error):
    """A branch left at main's commit is not cmapi's: a retry refuses it (BranchRefused) and git_cleanup keeps it as foreign."""
    path = next(iter(MANIFEST))
    req = BranchRequest("CRC", "req-1", BASE, "hash", "update\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
                        {path: "changed\n"}, {path: f"text of {path}\n"}, datetime(2026, 1, 1, tzinfo=timezone.utc))

    with pytest.raises(error):
        _gitea(host).push_request_branch(req)

    assert not host.branch_exists, [call[:2] for call in host.calls]


# --------------------------------------------------------------------------- F4: what `paths` shows

def test_two_names_that_are_not_utf8_never_show_the_same():
    one, two = b"a\xe9\\xff.yaml", b"a\\xe9\xff.yaml"
    assert git_name(one) == ("a\\xe9\\\\xff.yaml", False)
    assert git_name(two) == ("a\\\\xe9\\xff.yaml", False)
    assert git_name(b"caf\xe9.yaml") == ("caf\\xe9.yaml", False), "a name with no backslash shows as before"


def test_a_name_with_u_fffd_and_a_backslash_never_shows_as_one_that_is_not_utf8():
    typed, lost = "a\\xe9\ufffd.yaml".encode(), b"a\xe9\xef\xbf\xbd.yaml"
    assert git_name(typed) == ("a\\\\xe9\ufffd.yaml", False)
    assert git_name(lost) == ("a\\xe9\ufffd.yaml", False)


def _unshown(text: str) -> bytes:
    """The bytes of a path of NotUtf8, read back as the problem page says: \\\\ is a backslash, \\xNN a byte."""
    out, i = b"", 0
    while i < len(text):
        if text.startswith("\\\\", i):
            out, i = out + b"\\", i + 2
        elif text.startswith("\\x", i):
            out, i = out + bytes([int(text[i + 2:i + 4], 16)]), i + 4
        else:
            out, i = out + text[i].encode(), i + 1
    return out


def test_each_name_cmapi_cannot_carry_reads_back_as_its_bytes():
    """Unambiguous both ways: 5,000 names of backslashes, "x", hex digits, U+FFFD and bytes that are not UTF-8."""
    rng = random.Random(626)
    pool = [b"\\", b"x", b"e", b"9", b"a", b"\xe9", b"\xff", b"\x80", b"\xc3", b"\xa9", "\ufffd".encode()]
    for _ in range(5000):
        raw = b"".join(rng.choice(pool) for _ in range(rng.randint(1, 8)))
        name, carried = git_name(raw)
        if carried:
            assert name == raw.decode(), raw
        else:
            assert _unshown(name) == raw, (raw, name)


@pytest.mark.parametrize("one, two", [(b"a\xe9\\xff.txt", b"a\\xe9\xff.txt"),
                                      (b"b\xe9\xef\xbf\xbd.txt", "b\\xe9\ufffd.txt".encode())], ids=["backslash", "u-fffd"])
def test_the_delete_listing_names_two_such_names_apart(tmp_path, one, two):
    bare = bare_repo(tmp_path, {f"{BASE}namespace.yaml": NAMESPACE})
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        commit_bytes(bare, tmp_path, {BASE.encode() + one: b"1\n", BASE.encode() + two: b"2\n"})
        with pytest.raises(NotUtf8) as caught:
            ws.list_folder(BASE)
        assert len(set(caught.value.paths)) == 2, caught.value.paths
    finally:
        ws.dispose()


@pytest.mark.parametrize("make", [_github, _gitea], ids=["github", "gitea"])
def test_rest_shows_a_lost_name_as_the_git_layer_shows_it(make):
    lost = f"{FOLDER_PATH}/a\\x\ufffd.yaml"
    host = GitHubContents({**MANIFEST, lost: ("blob", "100644")})
    with pytest.raises(NotUtf8) as caught:
        make(host).read_folder(BASE)
    assert caught.value.paths == [git_name(lost.encode())[0]] == [f"{FOLDER_PATH}/a\\\\x\ufffd.yaml"]


def test_a_manifest_whose_text_is_not_utf8_is_shown_as_a_name_is():
    with pytest.raises(NotUtf8) as caught:
        manifest_text({"ns/a\\b.yaml": b"x: \xe9\n"})
    assert (caught.value.paths, caught.value.part) == (["ns/a\\\\b.yaml"], "text")


# --------------------------------------------------------------------------- F5, F6: the problem

def test_the_detail_names_the_rule_a_name_with_u_fffd_breaks():
    lost = folder_not_utf8("payments-dev", NotUtf8([LOST], "name")).body()
    plain = folder_not_utf8("payments-dev", NotUtf8([SHOWN], "name")).body()
    assert "is not UTF-8 or holds U+FFFD" in lost["detail"], lost["detail"]
    assert "U+FFFD" not in plain["detail"] and "is not UTF-8" in plain["detail"]
    assert str(NotUtf8([LOST], "name")).endswith(" is not UTF-8 or holds U+FFFD"), "the note on the request's timeline"
    assert str(NotUtf8([SHOWN], "name")).endswith(f"{SHOWN} is not UTF-8")


@pytest.mark.parametrize("code", ["folder-not-utf8", "folder-holds-submodule"])
def test_the_example_of_a_folder_refusal_shows_its_paths(code):
    example = problem_example(code)
    assert example["paths"] and all(p in example["detail"] for p in example["paths"]), example
