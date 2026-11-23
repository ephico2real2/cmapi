"""#578: the test FakeGit reads a namespace's folder as the real Git readers do: only the `.yaml` files directly in it.

core/git/github.py (read_folder: one Contents listing, entries of type "file"), core/git/gitea.py (one tree, blobs of mode
100644 or 100755) and core/git/workspace.py (_folder: `git ls-tree` of the folder, not -r) each list one folder and keep its
regular `.yaml` files. A FakeGit that also read subfolders would let a service test pass on a behaviour that no real backend
has, such as a namespace etag that covers a nested file.
"""
from __future__ import annotations

from cmapi.core.render.manifests import folder

from test_if_match_forms_571 import URL, _created
from test_flow import OLA, auth


def test_fake_git_reads_only_the_folders_own_yaml_files(world):
    client, ctx, git, kube, validator, keys = world
    tag = _created(client, ctx, keys)
    path = folder("CRC", "payments-dev")
    git.branches["main"][f"{path}nested/extra.yaml"] = "kind: ConfigMap\n"
    files, _ = git.read_folder(path)
    assert files and all("/" not in p[len(path):] for p in files), sorted(files)
    assert git.read_folder(path.rstrip("/"))[0] == files, "the real readers strip the slash, so the path may come without it"
    assert client.get(URL, headers=auth(keys, "ola", **OLA)).json()["etag"] == tag
