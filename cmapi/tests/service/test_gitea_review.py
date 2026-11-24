"""#450 (Codex's F7 of the Git delivery review, as OB3 corrected it): the Gitea REST stand-in handles a branch that exists as the
Git layer does (the arbitration of #286, row 3). An open PR proves nothing about the head; a head that is not this request's is
refused and never deleted; this request's own stale attempt is replaced; this request's current commit is adopted with no
write. Its branch delete after a merge still works. Offline: httpx.MockTransport only."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from cmapi.core.git.base import BranchRequest
from cmapi.core.git.gitea import GiteaProvider
from cmapi.core.git.workspace import BranchRefused

FOLDER = "clusters/CRC/namespaces/demo/"
REL = FOLDER + "namespace.yaml"
BRANCH = "cmapi/CRC/req-1"
MAIN, HEAD = "1" * 40, "a" * 40
PLAN = {REL: "kind: Namespace\n"}


def req() -> BranchRequest:
    return BranchRequest("CRC", "req-1", FOLDER, "hash", "create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n",
                         PLAN, {}, datetime(2026, 1, 1, tzinfo=timezone.utc))


class Host:
    """Gitea's REST paths the stand-in calls, over one existing request branch."""

    def __init__(self, message: str, files: dict[str, str], open_pr: bool):
        import base64

        self.message, self.files, self.open_pr = message, files, open_pr
        self.branch: str | None = HEAD
        self.calls: list[tuple[str, str]] = []
        self.b64 = lambda text: base64.b64encode(text.encode()).decode()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.removeprefix("/api/v1/repos/o/r"), request.method
        self.calls.append((method, path))
        if method == "GET" and path == "/branches/main":
            return httpx.Response(200, json={"commit": {"id": MAIN}})
        if method == "GET" and path == f"/branches/{BRANCH}":
            return httpx.Response(200, json={"commit": {"id": self.branch}}) if self.branch else httpx.Response(404, json={})
        if method == "GET" and path == f"/git/commits/{HEAD}":
            return httpx.Response(200, json={"sha": HEAD, "commit": {"message": self.message}, "parents": [{"sha": MAIN}]})
        if method == "GET" and path == "/pulls":
            return httpx.Response(200, json=[{"number": 1, "head": {"ref": BRANCH, "sha": HEAD}}] if self.open_pr else [])
        if method == "GET" and path == f"/git/trees/{MAIN}":
            return httpx.Response(200, json={"tree": [], "truncated": False})   # main's commit: the folder is not there yet
        if method == "GET" and path.startswith("/git/trees/"):
            parts = FOLDER.strip("/").split("/")
            trees = [self.branch, *(str(i) * 40 for i in range(2, 2 + len(parts)))]   # never MAIN's "1" * 40
            depth = trees.index(path.rsplit("/", 1)[1])
            if depth < len(parts):
                entries = [{"type": "tree", "path": parts[depth], "sha": trees[depth + 1]}]
            else:
                entries = [{"type": "blob", "mode": "100644", "path": p.rsplit("/", 1)[1], "sha": "f" * 40}
                           for p in self.files]
            return httpx.Response(200, json={"tree": entries, "truncated": False})
        if method == "GET" and path == "/git/blobs/" + "f" * 40:
            return httpx.Response(200, json={"content": self.b64(self.files[REL])})
        if method == "GET" and path.startswith("/contents/"):
            return httpx.Response(200, json={"content": self.b64(self.files.get(path[len("/contents/"):], "")), "sha": "f" * 40})
        if method == "DELETE" and path == f"/branches/{BRANCH}":
            self.branch = None
            return httpx.Response(204)
        if method == "POST" and path == "/branches":
            self.branch, self.files = "c" * 40, {}
            return httpx.Response(201, json={})
        if method == "POST" and path == "/contents":
            return httpx.Response(201, json={})
        raise AssertionError(f"unexpected {method} {path}")


def provider(host: Host) -> GiteaProvider:
    g = GiteaProvider("https://g.test/api/v1", "o/r", "test-token-0123456789")
    g._client.close()
    g._client = httpx.Client(base_url="https://g.test/api/v1", transport=httpx.MockTransport(host))
    return g


def writes(host: Host) -> list[tuple[str, str]]:
    return [(m, p) for m, p in host.calls if m != "GET"]


@pytest.mark.parametrize("open_pr", [True, False])
def test_a_head_that_is_not_this_requests_is_refused_and_left_alone(open_pr):
    host = Host("a person's change\n", {REL: "kind: Namespace\nmetadata: {name: other}\n"}, open_pr)
    with pytest.raises(BranchRefused):
        provider(host).push_request_branch(req())
    assert writes(host) == [] and host.branch == HEAD, "neither adopted through its PR nor deleted"


def test_this_requests_current_commit_is_adopted_with_no_write():
    host = Host("create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: hash\n", dict(PLAN), open_pr=False)
    pushed = provider(host).push_request_branch(req())
    assert (pushed.head, pushed.base, pushed.result) == (HEAD, MAIN, "adopted") and writes(host) == []


def test_this_requests_stale_attempt_is_replaced():
    host = Host("create\n\nCmapi-Request-Id: req-1\nCmapi-Plan-Hash: an-older-plan\n", dict(PLAN), open_pr=False)
    pushed = provider(host).push_request_branch(req())
    assert pushed.result == "replaced"
    assert writes(host)[:2] == [("DELETE", f"/branches/{BRANCH}"), ("POST", "/branches")]


def test_the_branch_of_a_merged_request_is_still_deleted():
    """Control: git_cleanup after every merge. Codex's patch raised here, so every merged request's cleanup failed five times,
    and one still in merged after the fifth (argocd mode, waiting for the sync) became sync_failed (worker.py)."""
    host = Host("", {}, open_pr=False)
    assert provider(host).delete_branch(BRANCH, HEAD) is True
    assert ("DELETE", f"/branches/{BRANCH}") in host.calls and host.branch is None


def test_a_branch_that_moved_is_not_deleted():
    host = Host("", {}, open_pr=False)
    assert provider(host).delete_branch(BRANCH, "e" * 40) is False and writes(host) == []


def test_the_message_trailers_parse_only_from_the_last_paragraph():
    host = Host("create\n\nCmapi-Request-Id: req-1 is quoted in the body\n\nCmapi-Request-Id: other\n", {}, open_pr=False)
    trailers, parents = provider(host)._commit(HEAD)
    assert trailers == {"Cmapi-Request-Id": ["other"]} and parents == [MAIN]
    assert json.dumps(trailers)
