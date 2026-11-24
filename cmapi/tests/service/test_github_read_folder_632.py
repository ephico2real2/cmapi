"""#632 (found by reviewer 1 of #631, widened by reviewer 2): GitHub's read_folder in the API process read a folder through its
Contents listing and each file's Contents read, and that read differs from the worker's (workspace._folder) below the cap too.

Version 2022-11-28 of "Get repository content" (docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28, fetched
2026-11-23): "When listing the contents of a directory, submodules have their "type" specified as "file"". "If the content is a
symlink and the symlink's target is a normal file in the repository, then the API responds with the content of the file." For
a file between 1 and 100 MB, "the content field will be an empty string and the encoding field will be "none"". Measured on
api.github.com the same day: a symlink to a file is listed as "file" too, and a 1.1 MB file read with the default media type
also answers 200 with content "" and encoding "none". RFC 3986, section 3.3: "The path is terminated by the first question
mark ("?") or number sign ("#") character". The mock below answers as GitHub did.
"""
from __future__ import annotations

import base64

import httpx
import pytest

from cmapi.core.git.base import GitUnavailable
from test_delete_whole_folder_616 import BASE, FOLDER_PATH, HEAD, RestHost, _github, _oid

ONE_MB = 1024 ** 2
OBJECT = "application/vnd.github.object+json"


class GitHubContents(RestHost):
    """GitHub's Contents for the commit HEAD, version 2022-11-28, beside RestHost's trees and blobs. A listing holds at most
    1,000 rows; a submodule and a symlink to a file are listed as "file"; a symlink's own read answers its target's text; a
    file past 1 MB answers no content. status refuses the folder's read, file_status each file's (Contents or blob)."""

    def __init__(self, entries, *, data=None, links=None, status=200, file_status=200):
        super().__init__(entries)
        self.data = data or {}                 # {path: bytes}; the default is RestHost's "text of {path}\n"
        self.links = links or {}               # {symlink path: the path of its target}
        self.status, self.file_status = status, file_status

    def _bytes(self, path):
        return self.data.get(path, f"text of {path}\n".encode())

    def _row(self, directory, e):
        kind = "dir" if e["type"] == "tree" else "file"
        return {"type": kind, "name": e["path"], "path": f"{directory}/{e['path']}", "sha": e["sha"]}

    def __call__(self, request):
        path = request.url.path.removeprefix("/repos/o/r")
        if request.method == "GET" and path.startswith("/contents/"):
            self.calls.append((request.method, path, dict(request.url.params)))
            assert request.url.params["ref"] == HEAD
            target = path.removeprefix("/contents/")
            children = self._children(target)
            if children:
                if self.status != 200:
                    return httpx.Response(self.status, json={"message": "Forbidden"})
                rows = [self._row(target, e) for e in children][:1000]
                if request.headers.get("accept") == OBJECT:
                    return httpx.Response(200, json={"type": "dir", "path": target, "sha": _oid("tree", target), "entries": rows})
                return httpx.Response(200, json=rows)
            if target not in self.entries:
                return httpx.Response(404, json={"message": "Not Found"})
            if self.file_status != 200:
                return httpx.Response(self.file_status, json={"message": "Forbidden"})
            kind = self.entries[target][0]
            own = {"name": target.rsplit("/", 1)[1], "path": target, "sha": _oid(kind, target)}
            if kind == "commit":
                return httpx.Response(200, json={**own, "type": "submodule", "submodule_git_url": "https://x.invalid/m.git"})
            text = self._bytes(self.links.get(target, target))
            large = len(text) > ONE_MB
            return httpx.Response(200, json={**own, "type": "file", "encoding": "none" if large else "base64",
                                             "content": "" if large else base64.b64encode(text).decode()})
        if request.method == "GET" and path.startswith("/git/blobs/"):
            self.calls.append((request.method, path, dict(request.url.params)))
            if self.file_status != 200:
                return httpx.Response(self.file_status, json={"message": "Forbidden"})
            name = next(p for p in self.entries if _oid("blob", p) == path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(self._bytes(name)).decode()})
        return super().__call__(request)


def folder_of(names, filler=0):
    """The folder's entries: names ({name: (Git type, mode)}) and `filler` regular .txt files before them."""
    entries = {f"{BASE}{i:04}.txt": ("blob", "100644") for i in range(filler)}
    entries.update({BASE + name: entry for name, entry in names.items()})
    return entries


REGULAR = ("blob", "100644")


def test_a_refused_listing_is_not_a_missing_folder():
    with pytest.raises(GitUnavailable, match="HTTP 403"):
        _github(GitHubContents(folder_of({"namespace.yaml": REGULAR}), status=403)).read_folder(BASE, HEAD)


def test_a_refused_file_read_raises_git_unavailable():
    with pytest.raises(GitUnavailable, match="HTTP 403"):
        _github(GitHubContents(folder_of({"namespace.yaml": REGULAR}), file_status=403)).read_folder(BASE, HEAD)


@pytest.mark.parametrize("filler", [0, 1000], ids=["below-cap", "past-cap"])
def test_a_manifest_past_1_mb_is_read_whole(filler):
    text = b"kind: ConfigMap\ndata: {big: '" + b"x" * (2 * ONE_MB) + b"'}\n"
    name = f"{BASE}namespace.yaml"
    host = GitHubContents(folder_of({"namespace.yaml": REGULAR}, filler), data={name: text})
    assert _github(host).read_folder(BASE, HEAD) == ({name: text.decode()}, HEAD)


ODD = {"symlink": {"link.yaml": ("blob", "120000")}, "submodule": {"vendor.yaml": ("commit", "160000")},
       "subfolder": {"dir.yaml/nested.yaml": REGULAR}, "yml": {"c.yml": REGULAR}}


@pytest.mark.parametrize("odd", list(ODD))
@pytest.mark.parametrize("filler", [0, 1000], ids=["below-cap", "past-cap"])
def test_only_regular_yaml_files_directly_in_the_folder_are_manifests(filler, odd):
    """As workspace._folder reads them: modes 100644 and 100755. Not a symlink (120000, here to b.yaml), a submodule (160000),
    a manifest in a subfolder, or another extension."""
    names = {"a.yaml": ("blob", "100755"), "b.yaml": REGULAR, **ODD[odd]}
    host = GitHubContents(folder_of(names, filler), links={f"{BASE}link.yaml": f"{BASE}b.yaml"})
    assert _github(host).read_folder(BASE, HEAD) == ({f"{BASE}a.yaml": f"text of {BASE}a.yaml\n",
                                                      f"{BASE}b.yaml": f"text of {BASE}b.yaml\n"}, HEAD)


def test_reserved_characters_in_names_stay_in_the_path():
    """"#" or "?" would end the path, and "%41" would read as "A": x%41.yaml would read its sibling xA.yaml."""
    names = {"a#b?.yaml": REGULAR, "x%41.yaml": REGULAR, "xA.yaml": REGULAR}
    files = {BASE + n: f"text of {BASE}{n}\n" for n in names}
    assert _github(GitHubContents(folder_of(names))).read_folder(BASE, HEAD) == (files, HEAD)


def test_reserved_characters_in_the_folder_stay_in_the_path():
    directory = "clusters/C#1/namespaces/a%41"
    entries = {f"{directory}/namespace.yaml": REGULAR}
    files = {f"{directory}/namespace.yaml": f"text of {directory}/namespace.yaml\n"}
    assert _github(GitHubContents(entries)).read_folder(f"{directory}/", HEAD) == (files, HEAD)


def test_a_file_path_is_not_a_folder():
    """As the worker reads it: git ls-tree of "<file>/" lists nothing."""
    host = GitHubContents(folder_of({"namespace.yaml": REGULAR}))
    assert _github(host).read_folder(f"{BASE}namespace.yaml", HEAD) == ({}, HEAD)


def test_a_missing_folder_reads_as_empty():
    assert _github(GitHubContents(folder_of({"namespace.yaml": REGULAR}))).read_folder(
        "clusters/CRC/namespaces/none-dev/", HEAD) == ({}, HEAD)


@pytest.mark.parametrize("filler", [0, 1000], ids=["below-cap", "past-cap"])
def test_a_pinned_read_costs_the_folder_its_tree_and_one_blob_per_manifest(filler):
    """Contents finds the folder's tree in one request: GitHub's rate limit counts every request, so no walk from the root."""
    host = GitHubContents(folder_of({"namespace.yaml": REGULAR, "quota.yaml": REGULAR}, filler))
    _github(host).read_folder(BASE, HEAD)
    assert [(m, p.split("/")[2] if p.startswith("/git/") else "contents") for m, p, _ in host.calls] == [
        ("GET", "contents"), ("GET", "trees"), ("GET", "blobs"), ("GET", "blobs")]
    assert host.calls[0][1] == f"/contents/{FOLDER_PATH}"
