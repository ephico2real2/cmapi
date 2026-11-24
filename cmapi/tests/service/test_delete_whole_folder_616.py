"""#616: a namespace delete removes the whole folder, every file and subfolder, and its dry run shows each path it removes.

Before the fix the delete's plan mapped to None only the files that read_folder returns, the `.yaml` files directly in the
folder (core/render/manifests.py, ManifestRenderer.delete). A README, a `.json` or `.yml` manifest, or a subfolder stayed in Git
after the merge. Argo CD's root Application syncs the namespaces folder with `directory.recurse: true` and reads `.yaml`,
`.yml` and `.json` files, so a manifest left in a subfolder stays in the Application after its Namespace is pruned.

The design decided it (docs/01, "The bot PR removes the folder"; "Removing a folder makes Argo CD prune its objects"), so the
delete lists the folder at any depth on every provider (list_folder) and removes each path, and approval is the gate: the plan
shows the approvers every path before anything reaches Git. Each provider is tested here: the FakeGit flow, the Git layer on a
real repository (GitHub's worker), GitHub's REST listing (the API process) and the Gitea stand-in.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from cmapi.core.git.base import BranchRequest, IncompleteList
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.github import GitHubProvider
from cmapi.core.git.workspace import GitWorkspace
from cmapi.core.render.manifests import folder
from gitserver import bare_repo, git
from test_flow import AMY, NS, OLA, auth, run_jobs
from test_git_layer import drive, layer  # noqa: F401  (layer is the real Git layer's fixture)

URL = "/api/v1/clusters/CRC/namespaces"
ONE = f"{URL}/payments-dev"
BASE = folder("CRC", "payments-dev")
# What a person may add to a namespace's folder by hand: a README, manifests in a subfolder, and manifests in the other
# extensions Argo CD reads (.yml, .json).
EXTRA = {f"{BASE}README.md": "# payments-dev\nOwned by the payments team.\n",
         f"{BASE}extra/configmap.yaml": "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: extra, namespace: payments-dev}\n",
         f"{BASE}extra/deeper/notes.txt": "kept by hand\n",
         f"{BASE}secret-store.yml": "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: yml, namespace: payments-dev}\n",
         f"{BASE}more.json": '{"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "json", "namespace": "payments-dev"}}\n'}


# --------------------------------------------------------------------------- the flow, on the FakeGit

def _created_with_extra_files(world) -> str:
    """payments-dev, created and synced, then a person's commit on main adds EXTRA to its folder; the etag after it."""
    client, ctx, git_, kube, validator, keys = world
    assert client.post(URL, json=NS, headers=auth(keys, "ola", **OLA)).status_code == 202
    run_jobs(ctx)
    git_.branches["main"].update(EXTRA)
    git_._sha("main")
    return client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]


def _in_folder(git_, branch: str = "main") -> list[str]:
    return sorted(p for p in git_.branches[branch] if p.startswith(BASE))


def _delete(world, etag: str) -> str:
    client, ctx, git_, kube, validator, keys = world
    r = client.delete(ONE, headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 202, r.text
    return r.json()["requestId"]


def _approve(world, rid: str) -> None:
    client, *_, keys = world
    r = client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(keys, "amy", **AMY))
    assert r.json()["status"] == "approved", r.text


def test_the_delete_dry_run_lists_every_path_of_the_folder_as_removed(world):
    client, ctx, git_, kube, validator, keys = world
    etag = _created_with_extra_files(world)
    everything = _in_folder(git_)
    assert set(EXTRA) < set(everything)

    r = client.delete(f"{ONE}?dryRun=true", headers={**auth(keys, "ola", **OLA), "If-Match": etag})

    assert r.status_code == 200, r.text
    assert r.json()["changes"] == {p: "removed" for p in everything}


def test_a_merged_delete_leaves_nothing_of_the_folder_in_git(world):
    client, ctx, git_, kube, validator, keys = world
    etag = _created_with_extra_files(world)
    outside = {p: t for p, t in git_.branches["main"].items() if not p.startswith(BASE)}
    dry = client.delete(f"{ONE}?dryRun=true", headers={**auth(keys, "ola", **OLA), "If-Match": etag}).json()["changes"]

    rid = _delete(world, etag)
    request = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    _approve(world, rid)
    run_jobs(ctx)

    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "awaiting_prune", [(e["event"], e["note"]) for e in view["events"]]
    assert _in_folder(git_) == [], "the delete left these paths of the folder in Git"
    assert {p: t for p, t in git_.branches["main"].items() if not p.startswith(BASE)} == outside, "the delete touched another path"
    assert request["files"] == dry, "the dry run shows exactly what the delete removes"


def test_a_file_added_to_the_folder_after_the_plan_supersedes_the_delete(world):
    """The plan lists the paths it removes. A path added before the branch is pushed would stay in Git after the merge, so the
    delete ends superseded, as a change of a manifest already ends it (push_branch), and a person plans it again."""
    client, ctx, git_, kube, validator, keys = world
    etag = _created_with_extra_files(world)
    rid = _delete(world, etag)
    git_.branches["main"][f"{BASE}extra/late.txt"] = "added after the plan\n"
    git_._sha("main")
    _approve(world, rid)
    run_jobs(ctx)

    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "superseded", [(e["event"], e["note"]) for e in view["events"]]
    assert f"{BASE}namespace.yaml" in git_.branches["main"], "nothing was removed"


def test_a_folder_that_holds_a_submodule_is_refused_with_its_paths(world):
    client, ctx, git_, kube, validator, keys = world
    etag = _created_with_extra_files(world)
    git_.branches["main"][f"{BASE}vendor"] = "a submodule"
    git_.submodules.add(f"{BASE}vendor")
    git_._sha("main")
    etag = client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]

    for suffix in ("?dryRun=true", ""):
        r = client.delete(f"{ONE}{suffix}", headers={**auth(keys, "ola", **OLA), "If-Match": etag})
        assert (r.status_code, r.json()["code"]) == (409, "folder-holds-submodule"), r.text
        assert r.json()["paths"] == [f"{BASE}vendor"]


def test_the_merge_check_holds_a_delete_whose_folder_is_not_empty_at_the_merge(world):
    """Fable 2.4: the folder at the merge sha must be the plan's. For a delete that is an empty folder, so a path that reached
    main between the push and the merge holds the request for an operator, and nothing waits for a prune of it."""
    client, ctx, git_, kube, validator, keys = world
    etag = _created_with_extra_files(world)
    rid = _delete(world, etag)
    _approve(world, rid)
    merge = git_.merge

    def merge_with_a_late_file(pr, expected_head):
        sha = merge(pr, expected_head)
        git_.branches["main"][f"{BASE}late.md"] = "pushed by a person while the delete merged\n"
        git_.heads["main"] = sha                         # the merge sha now holds the late file
        return sha
    git_.merge = merge_with_a_late_file
    run_jobs(ctx)

    view = client.get(f"/api/v1/requests/{rid}", headers=auth(keys, "ola", **OLA)).json()
    assert view["status"] == "sync_failed", [(e["event"], e["note"]) for e in view["events"]]
    assert any(e["event"] == "merge_verified" and "is not the plan's" in e["note"] for e in view["events"]), view["events"]


# --------------------------------------------------------------------------- the Git layer on a real repository

def _person_commit_with_links(bare: Path, scratch: Path, files: dict[str, str], links: dict[str, str], executables: set[str]) -> None:
    work = scratch / "person-616"
    git("clone", "--quiet", str(bare), str(work), cwd=scratch, home=scratch)
    for path, text in files.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(text)
    for path in executables:
        os.chmod(work / path, 0o755)
    for path, target in links.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).symlink_to(target)
    git("add", "--all", cwd=work, home=scratch)
    git("commit", "--quiet", "-m", "a person's files", cwd=work, home=scratch)
    git("push", "--quiet", "origin", "main", cwd=work, home=scratch)


def _tree(bare: Path, prefix: str) -> list[str]:
    out = git("--git-dir", str(bare), "ls-tree", "-r", "--name-only", "main", "--", prefix, cwd=bare, home=bare.parent)
    return sorted(filter(None, out.splitlines()))


def test_the_git_layer_removes_every_file_symlink_and_subfolder_of_the_folder(layer):  # noqa: F811
    w = layer
    w.create()
    drive(w.ctx)
    outside = w.tmp / "outside.txt"
    outside.write_text("must survive\n")
    _person_commit_with_links(w.bare, w.tmp, {**EXTRA, f"{BASE}hooks/run.sh": "#!/bin/sh\n"},
                              {f"{BASE}link-out": str(outside), f"{BASE}extra/link-in": "configmap.yaml"}, {f"{BASE}hooks/run.sh"})
    everything = _tree(w.bare, BASE)
    assert {f"{BASE}link-out", f"{BASE}hooks/run.sh", *EXTRA} < set(everything)
    other = _tree(w.bare, "clusters") + _tree(w.bare, "README.md")
    h = auth(w.keys, "ola", **OLA)
    etag = w.client.get(ONE, headers=h).json()["etag"]

    dry = w.client.delete(f"{ONE}?dryRun=true", headers={**h, "If-Match": etag})
    assert dry.status_code == 200 and dry.json()["changes"] == {p: "removed" for p in everything}, dry.text
    rid = w.client.delete(ONE, headers={**auth(w.keys, "ola", **OLA), "If-Match": etag}).json()["requestId"]
    w.client.post(f"/api/v1/requests/{rid}:approve", json={}, headers=auth(w.keys, "amy", **AMY))
    drive(w.ctx)

    assert w.view(rid)["status"] == "awaiting_prune", w.events(rid)
    assert _tree(w.bare, BASE) == [], "the delete left these paths in Git"
    assert _tree(w.bare, "clusters") + _tree(w.bare, "README.md") == [p for p in other if not p.startswith(BASE)]
    assert outside.read_text() == "must survive\n", "a symlink is removed, never what it points to"


def test_the_git_layer_lists_a_submodule_as_a_commit(tmp_path):
    bare = bare_repo(tmp_path, {f"{BASE}namespace.yaml": "kind: Namespace\n"})
    work = tmp_path / "person"
    git("clone", "--quiet", str(bare), str(work), cwd=tmp_path, home=tmp_path)
    git("update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},{BASE}vendor", cwd=work, home=tmp_path)
    git("commit", "--quiet", "-m", "a gitlink", cwd=work, home=tmp_path)
    git("push", "--quiet", "origin", "main", cwd=work, home=tmp_path)
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        listed, head = ws.list_folder(BASE)
        assert listed == {f"{BASE}namespace.yaml": "blob", f"{BASE}vendor": "commit"} and len(head) == 40
    finally:
        ws.dispose()


def test_a_removal_named_like_a_pathspec_glob_removes_only_that_file(tmp_path):
    """git rm reads literal pathspecs: a file named "*.yaml" is that file, never every .yaml of the folder."""
    bare = bare_repo(tmp_path, {f"{BASE}namespace.yaml": "kind: Namespace\n", f"{BASE}*.yaml": "a name with a star\n"})
    ws = GitWorkspace(bare.as_uri(), workdir=tmp_path / "worker")
    try:
        req = BranchRequest("CRC", "req-1", BASE, "hash", "delete\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
                            {f"{BASE}*.yaml": None}, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))
        pushed = ws.push_branch(req)
        assert ws.list_folder(BASE, pushed.head)[0] == {f"{BASE}namespace.yaml": "blob"}
    finally:
        ws.dispose()


# --------------------------------------------------------------------------- REST: GitHub's API process and the Gitea stand-in

HEAD, ROOT = "c" * 40, "e" * 40          # a commit and its root tree
FOLDER_PATH = BASE.rstrip("/")
# Every entry under the folder, as Git types it: a symlink is a blob, a submodule a commit.
ENTRIES = {f"{FOLDER_PATH}/namespace.yaml": ("blob", "100644"), f"{FOLDER_PATH}/README.md": ("blob", "100644"),
           f"{FOLDER_PATH}/link": ("blob", "120000"), f"{FOLDER_PATH}/extra/configmap.yaml": ("blob", "100644"),
           f"{FOLDER_PATH}/extra/deeper/notes.txt": ("blob", "100755")}
SIBLING = "clusters/CRC/namespaces/other-dev/namespace.yaml"


def _oid(kind: str, path: str) -> str:
    return hashlib.sha1(f"{kind}:{path}".encode()).hexdigest()


class RestHost:
    """GitHub's trees paths, and Gitea's branches, trees, blobs, contents and commit paths, over one commit whose files are
    ENTRIES and a sibling folder. Trees are built from the paths. truncated cuts the folder's recursive tree; walk_truncated
    cuts each tree on the way to it."""

    def __init__(self, entries=None, *, truncated: bool = False, walk_truncated: bool = False):
        self.entries = dict(ENTRIES if entries is None else entries)
        self.entries[SIBLING] = ("blob", "100644")
        self.truncated, self.walk_truncated = truncated, walk_truncated
        self.calls: list[tuple[str, str, dict]] = []
        self.commit_ops: list[dict] = []
        self.branch_exists = False

    def _children(self, directory: str) -> list[dict]:
        out: dict[str, dict] = {}
        prefix = f"{directory}/" if directory else ""
        for path, (kind, mode) in self.entries.items():
            if not path.startswith(prefix):
                continue
            name, _, rest = path[len(prefix):].partition("/")
            full = prefix + name
            out[name] = ({"path": name, "type": "tree", "mode": "040000", "sha": _oid("tree", full)} if rest else
                         {"path": name, "type": kind, "mode": mode, "sha": _oid(kind, full)})
        return sorted(out.values(), key=lambda e: e["path"])

    def _dir_of(self, oid: str) -> str:
        if oid in (HEAD, ROOT, "d" * 40):
            return ""
        return next(p for p in {"/".join(k.split("/")[:i]) for k in self.entries for i in range(1, k.count("/") + 1)}
                    if _oid("tree", p) == oid)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.removeprefix("/api/v1").removeprefix("/repos/o/r"), request.method
        params = dict(request.url.params)
        self.calls.append((method, path, params))
        if method == "GET" and path == f"/git/commits/{HEAD}":           # GitHub: the commit's root tree
            return httpx.Response(200, json={"sha": HEAD, "tree": {"sha": ROOT}})
        if method == "GET" and path == "/branches/main":
            return httpx.Response(200, json={"commit": {"id": HEAD, "sha": HEAD}})
        if method == "GET" and path == "/branches/cmapi/CRC/req-1":
            return httpx.Response(200, json={"commit": {"id": "d" * 40}}) if self.branch_exists else httpx.Response(404, json={})
        if method == "POST" and path == "/branches":
            self.branch_exists = True
            return httpx.Response(201, json={})
        if method == "GET" and path.startswith("/contents/"):           # Gitea's read of one file's sha
            target = path[len("/contents/"):]
            assert target in self.entries, target
            return httpx.Response(200, json={"type": "file", "path": target, "sha": _oid("blob", target)})
        if method == "GET" and path.startswith("/git/trees/"):
            directory = self._dir_of(path.rsplit("/", 1)[1])
            if "recursive" in params:                                  # GitHub's recursive tree
                prefix = f"{directory}/"
                tree = [{"path": p[len(prefix):], "type": k, "mode": m, "sha": _oid(k, p)}
                        for p, (k, m) in self.entries.items() if p.startswith(prefix)]
                return httpx.Response(200, json={"sha": "t", "tree": tree, "truncated": self.truncated})
            return httpx.Response(200, json={"tree": self._children(directory), "truncated": self.walk_truncated, "page": 1})
        if method == "GET" and path.startswith("/git/blobs/"):
            name = next(p for p in self.entries if _oid("blob", p) == path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"content": base64.b64encode(f"text of {name}\n".encode()).decode()})
        if method == "POST" and path == "/contents":
            self.commit_ops = json.loads(request.read())["files"]
            return httpx.Response(201, json={})
        raise AssertionError(f"unexpected {method} {path}")


def _github(host: RestHost) -> GitHubProvider:
    g = GitHubProvider("https://api.github.test", "o/r", "test-token-0123456789")
    g._client.close()
    g._client = httpx.Client(base_url="https://api.github.test", transport=httpx.MockTransport(host))
    return g


def _gitea(host: RestHost) -> GiteaProvider:
    g = GiteaProvider("https://g.test/api/v1", "o/r", "test-token-0123456789")
    g._client.close()
    g._client = httpx.Client(base_url="https://g.test/api/v1", transport=httpx.MockTransport(host))
    return g


WANT = {p: k for p, (k, _) in ENTRIES.items()}


@pytest.mark.parametrize("make", [_github, _gitea], ids=["github", "gitea"])
def test_rest_lists_every_entry_of_the_folder_at_any_depth_and_nothing_beside_it(make):
    host = RestHost()
    listed, head = make(host).list_folder(BASE)
    assert (listed, head) == (WANT, HEAD)
    assert make(RestHost()).list_folder(FOLDER_PATH)[0] == WANT, "with or without the trailing slash"


@pytest.mark.parametrize("make", [_github, _gitea], ids=["github", "gitea"])
def test_rest_lists_a_submodule_as_a_commit_and_a_missing_folder_as_empty(make):
    host = RestHost({**ENTRIES, f"{FOLDER_PATH}/vendor": ("commit", "160000")})
    assert make(host).list_folder(BASE)[0][f"{FOLDER_PATH}/vendor"] == "commit"
    assert make(RestHost()).list_folder("clusters/CRC/namespaces/not-there/") == ({}, HEAD)


@pytest.mark.parametrize("cut", ["truncated", "walk_truncated"])
def test_github_refuses_a_tree_that_its_limits_have_cut(cut):
    with pytest.raises(IncompleteList, match="truncated"):
        _github(RestHost(**{cut: True})).list_folder(BASE)


def test_gitea_refuses_a_cut_page_of_a_tree():
    """_tree_entries: a page marked truncated with no entries, or another page number, is not read as the end."""
    host = RestHost(walk_truncated=True)
    with pytest.raises(Exception, match="incomplete page"):
        _gitea(host).list_folder(BASE)


def test_the_gitea_stand_in_deletes_every_path_the_plan_removes():
    host = RestHost()
    req = BranchRequest("CRC", "req-1", BASE, "hash", "delete\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
                        dict.fromkeys(WANT), {f"{FOLDER_PATH}/namespace.yaml": f"text of {FOLDER_PATH}/namespace.yaml\n"},
                        datetime(2026, 1, 1, tzinfo=timezone.utc))
    _gitea(host).push_request_branch(req)
    assert sorted((op["operation"], op["path"]) for op in host.commit_ops) == sorted(("delete", p) for p in WANT)
    assert all(op["sha"] == _oid("blob", op["path"]) for op in host.commit_ops)
