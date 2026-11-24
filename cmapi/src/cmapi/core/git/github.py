"""GitHub: the Git layer for every branch, commit and read in the worker (core/git/workspace.py), and REST for the PR (#286).

The worker writes the request branch with git, pushes it with a lease, and deletes it with a lease. GitHub's REST API opens the
PR, reads its state, merges it pinned to a sha, comments and closes. Nothing reads the Checks API: a fine-grained token cannot
call it (BUG-69, #279). Host CI is optional and off by default (instance.git.hostChecks): when it is on, pr_status reads the
commit statuses alone. The worker posts its own checks as commit statuses only when host CI or instance.git.postStatus is on
(the arbitration, row 11).

The API process has no Git layer: the bot's SSH key is mounted in the worker alone (F2), so plan-time reads of a folder, the
branch head and the log go through the contents, branches and commits endpoints with the bot's token, as before #286 (the
arbitration, row 12: for PR-A).

The bot account's token: Contents read and write (git fetch and push over HTTPS, and the reads above), Pull requests read and
write, Metadata read; Commit statuses read and write only with host CI or postStatus. Endpoints as documented by GitHub (2026-11):

    GET  /repos/{o}/{r}/pulls?head=&state=open      POST /repos/{o}/{r}/pulls          GET /repos/{o}/{r}/pulls/{n}
    PUT  /repos/{o}/{r}/pulls/{n}/merge {sha}       PATCH /repos/{o}/{r}/pulls/{n}     POST /repos/{o}/{r}/issues/{n}/comments
    GET  /repos/{o}/{r}/commits/{sha}/status        POST /repos/{o}/{r}/statuses/{sha} GET /repos/{o}/{r}/pulls?state=open (list)
    The API process, reads only: GET /repos/{o}/{r}/branches/{b}, /contents/{path}?ref=, /commits?sha=,
    /git/trees/{sha}[?recursive=1] (the folder a delete lists, #616)
"""
from __future__ import annotations

import base64
from typing import Any, Iterable, Mapping

from cmapi.core.git.base import (BranchRequest, CheckState, GitUnavailable, HeadMoved, HostGitProvider, IncompleteList, MergeCheck,
                                 NotMergeable, PlatformRefused, PushResult)
from cmapi.core.ports import PrRef, PrStatus


def _worse(a: CheckState | None, b: CheckState) -> CheckState:
    """One context reported twice reads as the worse report: a pass from one source never hides the other's failure."""
    return max(a or b, b, key=("success", "pending", "failure").index)


# "This API has an upper limit of 1,000 files for a directory" (REST docs, Repository contents): a listing this long may be cut.
CONTENTS_DIRECTORY_LIMIT = 1000


class GitHubProvider(HostGitProvider):
    name = "github"
    MAX_PAGES = 100      # 10,000 entries: past this a host is not answering a list, and a partial list must not read as complete

    def __init__(self, api_url: str, repository: str, token: str, *, workspace=None, host_checks: bool = False,
                 post_status: bool = False, **kw: Any):
        super().__init__(api_url, repository, token, **kw)
        self.workspace = workspace
        self.external_ci = bool(host_checks)
        self.post_statuses = bool(host_checks or post_status)

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def _repo(self) -> str:
        return f"/repos/{self.repository}"

    def _git(self):
        if self.workspace is None:
            raise GitUnavailable("this process has no Git layer: only the worker writes branches (core/context.py)")
        return self.workspace

    # ---- the Git side: the Git layer in the worker; REST reads in the API process
    def branch_head(self, branch: str) -> str | None:
        if self.workspace is not None:
            return self.workspace.branch_head(branch)
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{branch}", ok=(200, 404))
        return r.json()["commit"]["sha"] if r.status_code == 200 else None

    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        if self.workspace is not None:
            return self.workspace.read_folder(path, ref)
        head = self._folder_head(ref)
        r = self._call("read_folder", "GET", f"{self._repo()}/contents/{path.strip('/')}", params={"ref": head}, ok=(200, 404))
        files: dict[str, str] = {}
        if r.status_code == 200:
            entries = r.json()
            if isinstance(entries, list) and len(entries) >= CONTENTS_DIRECTORY_LIMIT:
                return self._tree_manifests(path, head), head
            for e in (entries if isinstance(entries, list) else [entries]):
                if e.get("type") == "file" and e["name"].endswith(".yaml"):
                    f = self._call("read_file", "GET", f"{self._repo()}/contents/{e['path']}", params={"ref": head})
                    files[e["path"]] = base64.b64decode(f.json()["content"]).decode()
        return files, head

    def _tree_manifests(self, path: str, head: str) -> dict[str, str]:
        """read_folder past the Contents cap: the folder's own tree, its regular .yaml blobs, as workspace._folder reads them.
        "This API has an upper limit of 1,000 files for a directory. If you need to retrieve more files, use the Git Trees API"
        (REST docs, Repository contents, 2026-11)."""
        directory = path.strip("/")
        c = self._call("read_folder", "GET", f"{self._repo()}/git/commits/{head}")
        if c.status_code != 200:
            raise GitUnavailable(f"read commit {head[:8]}: HTTP {c.status_code}")
        tree = c.json()["tree"]["sha"]
        for part in filter(None, directory.split("/")):
            entry = next((e for e in self._tree(tree) if e["path"] == part), None)
            if entry is None or entry["type"] != "tree":
                return {}
            tree = entry["sha"]
        prefix = f"{directory}/" if directory else ""
        files: dict[str, str] = {}
        for e in self._tree(tree):
            if e["type"] == "blob" and e["mode"] in ("100644", "100755") and e["path"].endswith(".yaml"):
                b = self._call("read_file", "GET", f"{self._repo()}/git/blobs/{e['sha']}")
                if b.status_code != 200:
                    raise GitUnavailable(f"read blob {e['sha'][:8]}: HTTP {b.status_code}")
                files[prefix + e["path"]] = base64.b64decode(b.json()["content"]).decode()
        return files

    def _tree(self, oid: str, *, recursive: bool = False) -> list[dict[str, Any]]:
        """GET git/trees/{oid}: the entries of one tree, or of every tree under it. "If truncated is true in the response then
        the number of items in the tree array exceeded our maximum limit" (100,000 entries or 7 MB recursive; REST docs,
        2026-11): IncompleteList, never a short list read as complete."""
        r = self._call("list_folder", "GET", f"{self._repo()}/git/trees/{oid}", params={"recursive": "1"} if recursive else None)
        if r.status_code != 200:
            raise GitUnavailable(f"read tree {oid[:8]}: HTTP {r.status_code}")
        body = r.json()
        if body.get("truncated"):
            raise IncompleteList(f"the tree {oid[:8]} is truncated: past GitHub's limit for a tree")
        return body["tree"]

    def list_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        """The Git Trees API, not Contents: a tree gives each entry's Git type and mode, and Contents stops at 1,000 entries.
        From the commit's root tree (GET git/commits/{sha}), the walk to the folder reads one tree per part, then the folder's
        tree with recursive=1."""
        if self.workspace is not None:
            return self.workspace.list_folder(path, ref)
        head = self._folder_head(ref)
        c = self._call("list_folder", "GET", f"{self._repo()}/git/commits/{head}")
        if c.status_code != 200:
            raise GitUnavailable(f"read commit {head[:8]}: HTTP {c.status_code}")
        directory = path.strip("/")
        tree = c.json()["tree"]["sha"]
        for part in filter(None, directory.split("/")):
            entry = next((e for e in self._tree(tree) if e["path"] == part), None)
            if entry is None or entry["type"] != "tree":
                return {}, head
            tree = entry["sha"]
        prefix = f"{directory}/" if directory else ""
        return {prefix + e["path"]: e["type"] for e in self._tree(tree, recursive=True) if e["type"] in ("blob", "commit")}, head

    def log(self, n: int = 20) -> list[str]:
        if self.workspace is not None:
            # The Git layer's token is in oplog's registry, not in this provider's forms (#424).
            from cmapi.core.git.oplog import redact as redact_registered

            return [redact_registered(line) for line in self.workspace.log(n)]
        r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "per_page": n})
        return self.commit_lines(r.json())

    def contains(self, revision: str, sha: str) -> bool:
        return self._git().contains(revision, sha)

    def changed_paths(self, head: str) -> set[str]:
        return self._git().changed_paths(head)

    def push_request_branch(self, req: BranchRequest) -> PushResult:
        return self._git().push_branch(req)

    def recreate_branch(self, req: BranchRequest, base: str, expected: str) -> str:
        return self._git().recreate(req, base, expected)

    def merge_check(self, head: str, folder: str, prev: Mapping[str, str], files: Mapping[str, str | None], *,
                    whole_folder: bool = False) -> MergeCheck:
        return self._git().merge_check(head, folder, prev, files, whole_folder=whole_folder)

    def delete_branch(self, branch: str, expected: str) -> bool:
        return self._git().delete_branch(branch, expected)

    def list_branches(self, prefix: str) -> dict[str, str]:
        return self._git().ls_remote(f"{prefix}*")

    def branch_time(self, sha: str) -> int:
        return self._git().commit_time(sha)

    def request_of(self, sha: str) -> str | None:
        ws = self._git()
        with ws._lock:
            ws._need(sha)
            ids = ws.trailers(sha)["Cmapi-Request-Id"]
        return ids[0] if len(ids) == 1 else None

    def cleanup(self, cluster_id: str, request_id: str) -> None:
        if self.workspace is not None:
            self.workspace.remove(cluster_id, request_id)

    def sweep(self, open_requests: Iterable[tuple[str, str]]):
        return self.workspace.sweep(open_requests) if self.workspace is not None else None

    def dispose(self) -> None:
        if self.workspace is not None:
            self.workspace.dispose()

    # ---- the PR: REST
    def _pr_ref(self, p: Mapping[str, Any]) -> PrRef:
        return PrRef(number=p["number"], url=p["html_url"], branch=p["head"]["ref"], head_sha=p["head"]["sha"])

    def find_pr(self, branch: str) -> PrRef | None:
        owner = self.repository.split("/")[0]
        r = self._call("pr_find", "GET", f"{self._repo()}/pulls", params={"state": "open", "head": f"{owner}:{branch}"}, ok=(200,))
        if r.status_code != 200:
            text = self.host_text(r)
            raise PlatformRefused(f"find the PR of {branch}: {r.status_code} {text[:200]}", r.status_code, text)
        prs = r.json()
        if len(prs) > 1:
            raise PlatformRefused(f"{len(prs)} open PRs from {branch}: one is expected")
        return self._pr_ref(prs[0]) if prs else None

    def open_pr(self, branch: str, head: str, title: str, body: str) -> PrRef:
        existing = self.find_pr(branch)
        if existing is None:
            r = self._call("pr_open", "POST", f"{self._repo()}/pulls",
                           json={"head": branch, "base": self.default_branch, "title": title, "body": body}, ok=(201,))
            if r.status_code != 201:
                existing = self.find_pr(branch) if r.status_code == 422 else None      # "A pull request already exists"
                if existing is None:
                    text = self.host_text(r)
                    raise PlatformRefused(f"open PR from {branch}: {r.status_code} {text}", r.status_code, text)
            else:
                existing = self._pr_ref(r.json())
        if existing.head_sha != head:
            raise HeadMoved(f"PR #{existing.number} is on {existing.head_sha[:8]}, not on the pushed head {head[:8]}")
        return existing

    def _pages(self, operation: str, path: str, key: str | None, **params: Any) -> list[Mapping[str, Any]]:
        """Every entry of a paginated list, or GitUnavailable: an unread page could hold the answer. The Link header says only
        whether there is a next page. Its URL is not called, because this client sends the token with every request."""
        entries: list[Mapping[str, Any]] = []
        for page in range(1, self.MAX_PAGES + 1):
            r = self._call(operation, "GET", path, params={**params, "per_page": 100, "page": page}, ok=(200,))
            if r.status_code != 200:
                raise GitUnavailable(f"{operation}: GET {path} page {page}: {r.status_code} {self.host_text(r, 200)}")
            body = r.json()
            entries.extend((body.get(key) or []) if key else body)
            if "next" not in r.links:
                return entries
        raise GitUnavailable(f"{operation}: GET {path} has more than {self.MAX_PAGES} pages")

    def list_open(self, prefix: str) -> list[PrRef]:
        return [self._pr_ref(p) for p in self._pages("pr_list", f"{self._repo()}/pulls", None, state="open")
                if p["head"]["ref"].startswith(prefix)]

    def pr_status(self, pr: PrRef) -> PrStatus:
        r = self._call("pr_state", "GET", f"{self._repo()}/pulls/{pr.number}", ok=(200,))
        if r.status_code != 200:
            text = self.host_text(r)
            raise PlatformRefused(f"PR {pr.number}: {r.status_code} {text[:200]}", r.status_code, text)
        p = r.json()
        head = (p.get("head") or {}).get("sha")
        if p["state"] != "open":      # nothing reads a finished PR's checks, and a refused read must not hold back recording its end
            merged = bool(p.get("merged"))
            return PrStatus(state="merged" if merged else "closed", checks={}, merge_sha=p.get("merge_commit_sha") if merged else None,
                            head_sha=head)
        checks: dict[str, CheckState] = {}
        if self.external_ci:          # host CI on: the commit statuses, never the Checks API
            for st in self._pages("status_read", f"{self._repo()}/commits/{head}/status", "statuses"):
                reported: CheckState = {"success": "success", "pending": "pending"}.get(st["state"], "failure")
                checks[st["context"]] = _worse(checks.get(st["context"]), reported)
        return PrStatus(state="open", checks=checks, head_sha=head)

    def set_check(self, sha: str, context: str, state: CheckState, description: str, target_url: str | None = None) -> None:
        body: dict[str, Any] = {"context": context, "state": state, "description": description[:140]}
        if target_url:
            body["target_url"] = target_url
        r = self._call("status_write", "POST", f"{self._repo()}/statuses/{sha}", json=body, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"status {context} on {sha[:8]}: {r.status_code} {self.host_text(r, 200)}")

    def merge(self, pr: PrRef, expected_head: str) -> str:
        """PUT .../merge with sha: GitHub merges only if the head is that sha. 409 is HeadMoved, 405 NotMergeable. The branch is
        not deleted here: git_cleanup deletes it with a lease."""
        r = self._call("merge", "PUT", f"{self._repo()}/pulls/{pr.number}/merge", ok=(200,), log_fields={"pinned_sha": expected_head,
                       "pr_number": pr.number, "merge_method": "merge"},
                       json={"sha": expected_head, "merge_method": "merge", "commit_title": f"Merge {pr.branch}"})
        if r.status_code == 200:
            return r.json()["sha"]
        message = self.host_text(r)
        if r.status_code == 409:
            raise HeadMoved(f"merge PR {pr.number}: the head is not {expected_head[:8]}: {message}", 409, message)
        if r.status_code == 405:
            said = r.text[:300].lower()            # the decision reads the host's own words; only the message is redacted
            raise NotMergeable(f"merge PR {pr.number}: {message}", transient="pending" in said or "expected" in said)
        raise PlatformRefused(f"merge PR {pr.number}: {r.status_code} {message}", r.status_code, message)

    def comment(self, pr: PrRef, text: str) -> None:
        """At most once per text: a retry after a lost answer finds the comment the host kept, and posts nothing (#451). A read
        before the write, not a host idempotency key: two writers at the same moment could still both post."""
        if any(c.get("body") == text for c in self._pages("pr_comments", f"{self._repo()}/issues/{pr.number}/comments", None)):
            return
        r = self._call("pr_comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": text}, ok=(201,))
        if r.status_code != 201:
            raise PlatformRefused(f"comment on PR {pr.number}: {r.status_code}", r.status_code, self.host_text(r))

    def close(self, pr: PrRef, comment: str) -> None:
        self.comment(pr, comment)
        r = self._call("pr_close", "PATCH", f"{self._repo()}/pulls/{pr.number}", json={"state": "closed"}, ok=(200,))
        if r.status_code != 200:
            raise PlatformRefused(f"close PR {pr.number}: {r.status_code}", r.status_code, self.host_text(r))
