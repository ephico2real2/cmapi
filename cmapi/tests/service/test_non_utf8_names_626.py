"""#626: a namespace's folder that holds a name, or a manifest's text, that is not UTF-8.

Git keeps a path as bytes. Documentation/i18n.adoc (git/git master, fetched 2026-11-24): "Git at the core level treats path
names simply as sequences of non-NUL bytes, there are no path name encoding conversions (except on Mac and Windows)", and
git-ls-tree(1): "Using -z the filename is output verbatim". The Git layer decoded each name of `git ls-tree -z` as strict UTF-8,
so a name such as b"caf\\xe9.yaml" (Latin-1) raised UnicodeDecodeError, which no caller handles: a 500 where the API reads
through the Git layer, and a job error retried five times in the worker.

The hosts' REST APIs lose the byte instead. Measured on api.github.com, 2026-11-24 (a throwaway branch, deleted after the
read): git/trees, git/trees?recursive=1 and Contents all answer the name b"caf\\xe9.yaml" as "caf\\ufffd.yaml", U+FFFD in
place of the byte, with no error. Gitea 1.25 writes its JSON with json-iterator's ConfigCompatibleWithStandardLibrary, whose
writeStringSlowPathWithHTMLEscaped writes `\\ufffd` for an invalid byte (read from the source, not measured). So the API
process, which reads through REST, planned a path that does not exist in Git.

The decision (the PR, and docs/reviews/2026-11-24-issue-626/README.md): a name cmapi carries is valid UTF-8 and holds no
U+FFFD, on every provider. A folder with any other name is refused at the plan, 409 folder-not-utf8 with each path, its bytes
escaped, and nothing changes. A name that reaches the folder after the plan supersedes the request at push_branch, and the
merge check reads such a folder as not the plan's.
"""
from __future__ import annotations

import base64
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from cmapi.core.git.base import BranchRequest, NotUtf8
from cmapi.core.git.workspace import GitWorkspace
from cmapi.core.render.manifests import folder
from gitserver import GIT, _env, bare_repo, git
from test_delete_whole_folder_616 import FOLDER_PATH, HEAD, _gitea, _github, _oid
from test_flow import AMY, OLA, auth
from test_git_layer import drive, layer  # noqa: F401  (layer is the real Git layer's fixture)
from test_github_read_folder_632 import GitHubContents

BASE = folder("CRC", "payments-dev")                  # "clusters/CRC/namespaces/payments-dev/"
ONE = "/api/v1/clusters/CRC/namespaces/payments-dev"
LATIN1 = b"caf\xe9.yaml"                              # "café.yaml" in Latin-1: 0xE9 alone is not UTF-8
SHOWN = f"{BASE}caf\\xe9.yaml"                        # the name as cmapi shows it: each byte that is not UTF-8 escaped
NAMESPACE = "apiVersion: v1\nkind: Namespace\nmetadata: {name: payments-dev}\n"


def commit_bytes(bare: Path, scratch: Path, files: dict[bytes, bytes], message: str = "a person's commit") -> str:
    """A person's commit on main that adds each path as raw bytes. Through the index, not the file system: APFS refuses a name
    that is not UTF-8 (EILSEQ, measured on this Mac), and Git itself takes any non-NUL bytes."""
    work = scratch / f"bytes-{time.monotonic_ns()}"
    git("clone", "--quiet", "--no-checkout", str(bare), str(work), cwd=scratch, home=scratch)
    git("read-tree", "HEAD", cwd=work, home=scratch)
    info = b""
    for path, data in files.items():
        blob = git("hash-object", "-w", "--stdin", cwd=work, home=scratch, input=data)
        info += b"100644 " + blob.encode() + b"\t" + path + b"\0"
    git("update-index", "-z", "--index-info", cwd=work, home=scratch, input=info)
    git("commit", "--quiet", "-m", message, cwd=work, home=scratch)
    git("push", "--quiet", "origin", "HEAD:main", cwd=work, home=scratch)
    return git("rev-parse", "HEAD", cwd=work, home=scratch)


def main_sha(bare: Path) -> str:
    return git("--git-dir", str(bare), "rev-parse", "main", cwd=bare, home=bare.parent)


def raw_names(bare: Path, prefix: str) -> list[bytes]:
    out = subprocess.run([GIT, "--git-dir", str(bare), "ls-tree", "-r", "-z", "--name-only", "main", "--", prefix],
                         capture_output=True, check=True, env=_env(bare.parent)).stdout
    return sorted(filter(None, out.split(b"\0")))


@pytest.fixture
def repo(tmp_path):
    bare = bare_repo(tmp_path, {f"{BASE}namespace.yaml": NAMESPACE})
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    yield bare, ws, tmp_path
    ws.dispose()


# --------------------------------------------------------------------------- the Git layer, on a real repository

def test_the_git_layer_refuses_a_manifest_whose_name_is_not_utf8(repo):
    bare, ws, tmp = repo
    commit_bytes(bare, tmp, {BASE.encode() + LATIN1: b"kind: ConfigMap\n"})

    for read in (ws.read_folder, ws.list_folder):
        with pytest.raises(NotUtf8) as caught:
            read(BASE)
        assert (caught.value.paths, caught.value.part) == ([SHOWN], "name"), read.__name__


def test_the_delete_listing_names_each_path_it_cannot_carry_at_any_depth(repo):
    """list_folder is what a delete removes (#616): every name under the folder counts. read_folder reads the .yaml files
    directly in it, so a README or a subfolder's file it never reads does not refuse it."""
    bare, ws, tmp = repo
    commit_bytes(bare, tmp, {BASE.encode() + b"READ\xe9.md": b"notes\n", BASE.encode() + b"sub/caf\xe9.txt": b"x\n"})

    files, _ = ws.read_folder(BASE)
    assert files == {f"{BASE}namespace.yaml": NAMESPACE}
    with pytest.raises(NotUtf8) as caught:
        ws.list_folder(BASE)
    assert caught.value.paths == [f"{BASE}READ\\xe9.md", f"{BASE}sub/caf\\xe9.txt"]


def test_a_manifest_whose_text_is_not_utf8_is_refused_by_its_path(repo):
    bare, ws, tmp = repo
    commit_bytes(bare, tmp, {f"{BASE}configmap.yaml".encode(): b"data: {city: Montr\xe9al}\n"})

    with pytest.raises(NotUtf8) as caught:
        ws.read_folder(BASE)
    assert (caught.value.paths, caught.value.part) == ([f"{BASE}configmap.yaml"], "text")


def test_a_name_that_holds_u_fffd_is_refused_as_the_rest_reads_refuse_it(repo):
    """A REST host answers a byte that is not UTF-8 as U+FFFD, so U+FFFD cannot be told from a lost byte there. One rule on
    every provider: the API process and the worker agree on which folders cmapi can carry."""
    bare, ws, tmp = repo
    commit_bytes(bare, tmp, {f"{BASE}caf�.yaml".encode(): b"kind: ConfigMap\n"})

    with pytest.raises(NotUtf8) as caught:
        ws.read_folder(BASE)
    assert caught.value.paths == [f"{BASE}caf�.yaml"]


def test_the_merge_check_reads_a_folder_it_cannot_name_as_not_the_plans(repo):
    """The merge gate: a plan never holds such a name, so main's folder that holds one is not the plan's base, and the merge
    check refuses it instead of raising."""
    bare, ws, tmp = repo
    req = BranchRequest("CRC", "req-1", BASE, "hash", "change\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
                        {f"{BASE}namespace.yaml": NAMESPACE + "# changed\n"}, {f"{BASE}namespace.yaml": NAMESPACE},
                        datetime(2026, 1, 1, tzinfo=timezone.utc))
    head = ws.push_branch(req).head
    commit_bytes(bare, tmp, {BASE.encode() + LATIN1: b"kind: ConfigMap\n"})

    check = ws.merge_check(head, BASE, req.prev, req.files)
    assert not check.ok and not check.base_matches
    deleted = ws.merge_check(head, BASE, req.prev, dict.fromkeys(req.files), whole_folder=True)
    assert not deleted.ok and not deleted.base_matches


def test_changed_paths_shows_a_name_it_cannot_decode_escaped(repo):
    """pr_checks compares the branch's changed paths with the plan's: a name that is not UTF-8 is a path outside the plan,
    shown escaped, never an error."""
    bare, ws, tmp = repo
    before = main_sha(bare)
    head = commit_bytes(bare, tmp, {BASE.encode() + LATIN1: b"kind: ConfigMap\n"})
    git("--git-dir", str(bare), "update-ref", "refs/heads/main", before, cwd=bare, home=tmp)
    git("--git-dir", str(bare), "update-ref", "refs/heads/person", head, cwd=bare, home=tmp)

    assert ws.changed_paths(head) == {SHOWN}


# --------------------------------------------------------------------------- the API and the worker, on the real Git layer

def _etag(w) -> str:
    return w.client.get(ONE, headers=auth(w.keys, "ola", **OLA)).json()["etag"]


def test_a_change_and_a_delete_of_a_folder_with_such_a_name_are_refused_and_nothing_changes(layer):  # noqa: F811
    w = layer
    w.create()
    drive(w.ctx)
    etag = _etag(w)
    commit_bytes(w.bare, w.tmp, {BASE.encode() + LATIN1: b"kind: ConfigMap\n"})
    head = main_sha(w.bare)

    read = w.client.get(ONE, headers=auth(w.keys, "ola", **OLA))
    change = w.client.patch(ONE, json={"tier": "medium"}, headers={**auth(w.keys, "ola", **OLA), "If-Match": etag})
    dry = w.client.delete(f"{ONE}?dryRun=true", headers={**auth(w.keys, "ola", **OLA), "If-Match": etag})
    delete = w.client.delete(ONE, headers={**auth(w.keys, "ola", **OLA), "If-Match": etag})

    for r in (read, change, dry, delete):
        assert (r.status_code, r.json()["code"]) == (409, "folder-not-utf8"), r.text
        assert r.json()["paths"] == [SHOWN] and SHOWN in r.json()["detail"]
        assert r.headers["content-type"] == "application/problem+json"
    assert main_sha(w.bare) == head, "nothing reached Git"
    assert drive(w.ctx) == [], "no request and no job"


def test_a_change_is_not_refused_for_a_name_it_never_reads(layer):  # noqa: F811
    """A change reads the .yaml files directly in the folder: a subfolder's name that is not UTF-8 does not concern it. Only the
    delete, which removes every path, refuses it."""
    w = layer
    w.create()
    drive(w.ctx)
    etag = _etag(w)
    commit_bytes(w.bare, w.tmp, {BASE.encode() + b"sub/caf\xe9.txt": b"x\n"})

    change = w.client.patch(f"{ONE}?dryRun=true", json={"tier": "medium"}, headers={**auth(w.keys, "ola", **OLA), "If-Match": etag})
    delete = w.client.delete(f"{ONE}?dryRun=true", headers={**auth(w.keys, "ola", **OLA), "If-Match": etag})
    assert change.status_code == 200, change.text
    assert (delete.status_code, delete.json()["code"], delete.json()["paths"]) == \
        (409, "folder-not-utf8", [f"{BASE}sub/caf\\xe9.txt"]), delete.text


@pytest.mark.parametrize("action, name", [("change", LATIN1), ("delete", b"sub/caf\xe9.txt")])
def test_a_name_that_reaches_the_folder_after_the_plan_supersedes_the_request(layer, action, name):  # noqa: F811
    """push_branch reads the folder on main again: a name that cannot be read means the folder changed since the plan, so the
    request ends superseded, with the path in its note, and no branch is pushed. Before the fix: UnicodeDecodeError five times,
    then pr_failed."""
    w = layer
    w.create()
    drive(w.ctx)
    etag = _etag(w)
    h = {**auth(w.keys, "ola", **OLA), "If-Match": etag}
    r = w.client.patch(ONE, json={"tier": "medium"}, headers=h) if action == "change" else w.client.delete(ONE, headers=h)
    assert r.status_code == 202, r.text
    rid = r.json()["requestId"]
    commit_bytes(w.bare, w.tmp, {BASE.encode() + name: b"kind: ConfigMap\n"})
    head = main_sha(w.bare)
    if w.view(rid)["status"] == "pending_approval":
        w.client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(w.keys, "amy", **AMY))

    drive(w.ctx)

    view = w.view(rid)
    assert view["status"] == "superseded", [(e["event"], e["note"]) for e in view["events"]]
    note = next(e["note"] for e in view["events"] if e["event"] == "base_changed" or "changed in Git" in (e["note"] or ""))
    assert BASE + name.decode("utf-8", "backslashreplace") in note
    assert main_sha(w.bare) == head and BASE.encode() + name in raw_names(w.bare, BASE)
    assert not [b for b in git("--git-dir", str(w.bare), "branch", "--list", "cmapi/*", cwd=w.bare, home=w.tmp).split() if b]


# --------------------------------------------------------------------------- REST: GitHub's API process and the Gitea stand-in

LOST = f"{FOLDER_PATH}/caf�.yaml"               # how GitHub answered b"caf\xe9.yaml" (measured, 2026-11-24)
MANIFEST = {f"{FOLDER_PATH}/namespace.yaml": ("blob", "100644")}


@pytest.mark.parametrize("make", [_github, _gitea], ids=["github", "gitea"])
def test_rest_refuses_a_name_that_the_host_gave_as_u_fffd(make):
    host = GitHubContents({**MANIFEST, LOST: ("blob", "100644")})
    for read in ("read_folder", "list_folder"):
        with pytest.raises(NotUtf8) as caught:
            getattr(make(host), read)(BASE)
        assert (caught.value.paths, caught.value.part) == ([LOST], "name"), read


@pytest.mark.parametrize("make", [_github, _gitea], ids=["github", "gitea"])
def test_rest_lists_a_subfolder_name_with_u_fffd_only_for_a_delete(make):
    lost = f"{FOLDER_PATH}/sub/caf�.txt"
    host = GitHubContents({**MANIFEST, lost: ("blob", "100644")})
    assert make(host).read_folder(BASE)[0] == {f"{FOLDER_PATH}/namespace.yaml": f"text of {FOLDER_PATH}/namespace.yaml\n"}
    with pytest.raises(NotUtf8) as caught:
        make(host).list_folder(BASE)
    assert caught.value.paths == [lost]


@pytest.mark.parametrize("make", [_github, _gitea], ids=["github", "gitea"])
def test_rest_refuses_a_manifest_whose_text_is_not_utf8(make):
    path = f"{FOLDER_PATH}/configmap.yaml"
    host = GitHubContents({**MANIFEST, path: ("blob", "100644")}, data={path: b"data: {city: Montr\xe9al}\n"})
    with pytest.raises(NotUtf8) as caught:
        make(_Blobs(host)).read_folder(BASE)
    assert (caught.value.paths, caught.value.part) == ([path], "text")


def test_the_gitea_merge_check_reads_a_folder_it_cannot_name_as_not_the_plans():
    """HostGitProvider.merge_check, the Gitea stand-in's: main's folder that holds a lost name is not the plan's base, for a
    change and for a delete, and the check names main's head instead of raising."""
    host = GitHubContents({**MANIFEST, LOST: ("blob", "100644")})
    prev = {f"{FOLDER_PATH}/namespace.yaml": f"text of {FOLDER_PATH}/namespace.yaml\n"}
    change = _gitea(host).merge_check(HEAD, BASE, prev, {f"{FOLDER_PATH}/namespace.yaml": "changed\n"})
    delete = _gitea(host).merge_check(HEAD, BASE, prev, dict.fromkeys(MANIFEST), whole_folder=True)
    for check in (change, delete):
        assert (check.ok, check.base_matches, check.main_sha) == (False, False, HEAD)
    assert not delete.result_matches


class _Blobs:
    """Each blob with the bytes the host holds for its path, on Gitea's /api/v1 paths too, which GitHubContents leaves to
    RestHost's "text of" answer."""

    def __init__(self, host: GitHubContents):
        self.host = host

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1").removeprefix("/repos/o/r")
        if request.method == "GET" and path.startswith("/git/blobs/"):
            name = next(p for p in self.host.entries if _oid("blob", p) == path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"content": base64.b64encode(self.host._bytes(name)).decode()})
        return self.host(request)

