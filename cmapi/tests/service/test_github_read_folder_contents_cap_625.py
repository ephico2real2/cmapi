"""#625 (found by reviewer 2 of #622, from reviewer 1's finding 4): GitHub's Contents API "has an upper limit of 1,000 files for a
directory. If you need to retrieve more files, use the Git Trees API" (docs.github.com/en/rest/repos/contents, fetched
2026-11-23). read_folder in the API process read one Contents listing as the whole folder."""
from __future__ import annotations

import httpx

from test_delete_whole_folder_616 import BASE, FOLDER_PATH, HEAD, RestHost, _github, _oid


class CappedContents(RestHost):
    """The Contents listing of the folder stops at 1,000 entries and leaves namespace.yaml out, in its array form and in its
    object form, which also carries the folder's tree sha (application/vnd.github.object+json)."""

    def __call__(self, request):
        path = request.url.path.removeprefix("/repos/o/r")
        if request.method == "GET" and path == f"/contents/{FOLDER_PATH}":
            rows = [{"type": "file", "name": f"{i:04}.txt", "path": f"{BASE}{i:04}.txt"} for i in range(1000)]
            if request.headers.get("accept") == "application/vnd.github.object+json":
                return httpx.Response(200, json={"type": "dir", "path": FOLDER_PATH, "sha": _oid("tree", FOLDER_PATH),
                                                 "entries": rows})
            return httpx.Response(200, json=rows)
        return super().__call__(request)


def test_github_reads_a_folder_past_the_contents_cap_from_its_tree():
    entries = {f"{BASE}{i:04}.txt": ("blob", "100644") for i in range(1000)}
    name = f"{BASE}namespace.yaml"
    entries[name] = ("blob", "100644")
    assert _github(CappedContents(entries)).read_folder(BASE, HEAD) == ({name: f"text of {name}\n"}, HEAD)
