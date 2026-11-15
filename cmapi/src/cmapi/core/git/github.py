"""GitHub: the Git layer for every branch, commit and read (core/git/workspace.py), and REST for the PR alone (#286).

The worker's request branch is written with git and pushed by git; GitHub's REST API opens the PR, reads its state, merges it with an
expected head, deletes the merged branch, and comments and closes on a failure. Nothing reads the Checks API: a fine-grained
token cannot call it (BUG-69, #279). Host CI is optional and off by default (instance.git.hostChecks). When it is on, pr_status
reads the commit statuses alone, which every host has in common, and the worker waits for ci/kubeconform and ci/kyverno there.
When it is off, the worker's own validators are the gate, and it posts ci/* and cmapi/check as commit statuses, as a record.

The API process has no Git layer: the bot's SSH key is mounted in the worker alone (F2), so plan-time reads of a folder, the
branch head and the log go through the contents, branches and commits endpoints with the bot's token, as before #286.

The token's permissions: Contents read and write (git fetch and push, and the branch's deletion), Pull requests read and
write, Commit statuses read and write, Metadata read. Endpoints as documented by GitHub (2026-11):

    GET  /repos/{o}/{r}/pulls?head=&state=open      POST /repos/{o}/{r}/pulls          GET /repos/{o}/{r}/pulls/{n}
    PUT  /repos/{o}/{r}/pulls/{n}/merge {sha}       PATCH /repos/{o}/{r}/pulls/{n}     POST /repos/{o}/{r}/issues/{n}/comments
    GET  /repos/{o}/{r}/commits/{sha}/status        POST /repos/{o}/{r}/statuses/{sha} DELETE /repos/{o}/{r}/git/refs/heads/{b}
    The API process, reads only: GET /repos/{o}/{r}/branches/{b}, /contents/{path}?ref=, /commits?sha=
"""
from __future__ import annotations

import base64
from typing import Any, Iterable, Mapping

from cmapi.core.git.base import BranchRequest, CheckState, GitUnavailable, HostGitProvider
from cmapi.core.ports import PrRef, PrStatus


def _worse(a: CheckState | None, b: CheckState) -> CheckState:
    """One context reported twice reads as the worse report: a pass from one source never hides the other's failure."""
    return max(a or b, b, key=("success", "pending", "failure").index)


class GitHubProvider(HostGitProvider):
    MAX_PAGES = 100      # 10,000 entries on one commit: past this a host is not answering a list, and a partial list must not read as complete

    def __init__(self, api_url: str, repository: str, token: str, *, workspace=None, host_checks: bool = False, **kw: Any):
        super().__init__(api_url, repository, token, **kw)
        self.workspace = workspace
        # Whether the repository's own CI reports ci/kubeconform and ci/kyverno, as commit statuses. Off by default (#286).
        self.external_ci = bool(host_checks)

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def _repo(self) -> str:
        return f"/repos/{self.repository}"

    def _git(self):
        if self.workspace is None:
            raise GitUnavailable("the GitHub adapter has no Git layer: core/context.py builds one from instance.git.url")
        return self.workspace

    # ---- reads and the branch: the Git layer in the worker, REST in the API process
    def branch_head(self, branch: str) -> str | None:
        if self.workspace is not None:
            return self.workspace.branch_head(branch)
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{branch}", ok=(200, 404))
        return r.json()["commit"]["sha"] if r.status_code == 200 else None

    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        if self.workspace is not None:
            return self.workspace.read_folder(path, ref)
        ref = ref or self.default_branch
        head = ref if len(ref) == 40 else self.branch_head(ref)
        if head is None:
            raise GitUnavailable(f"branch {ref} does not exist")
        r = self._call("read_folder", "GET", f"{self._repo()}/contents/{path.strip('/')}", params={"ref": head}, ok=(200, 404))
        files: dict[str, str] = {}
        if r.status_code == 200:
            entries = r.json()
            for e in (entries if isinstance(entries, list) else [entries]):
                if e.get("type") == "file" and e["name"].endswith(".yaml"):
                    f = self._call("read_file", "GET", f"{self._repo()}/contents/{e['path']}", params={"ref": head})
                    files[e["path"]] = base64.b64decode(f.json()["content"]).decode()
        return files, head

    def contains(self, revision: str, sha: str) -> bool:
        return self._git().contains(revision, sha)

    def changed_paths(self, head: str) -> set[str]:
        return self._git().changed_paths(head)

    def log(self, n: int = 20) -> list[str]:
        if self.workspace is not None:
            return self.workspace.log(n)
        r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "per_page": n})
        return [f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}" for c in r.json()]

    def merge_check(self, head: str, folder: str, base_files: Mapping[str, str]):
        return self._git().merge_check(head, folder, base_files)

    def cleanup(self, cluster_id: str, request_id: str) -> None:
        if self.workspace is not None:
            self.workspace.remove(cluster_id, request_id)

    def sweep(self, in_flight: Iterable[tuple[str, str]]):
        return self.workspace.sweep(in_flight) if self.workspace is not None else None

    def dispose(self) -> None:
        if self.workspace is not None:
            self.workspace.dispose()

    # ---- the PR: REST
    def open_pr(self, branch: str, files: Mapping[str, str | None], title: str, body: str, base_sha: str,
                request: BranchRequest | None = None) -> PrRef:
        if request is None:
            raise ValueError("the GitHub adapter writes the branch with the Git layer: open_pr needs the BranchRequest")
        head, _reused = self._git().prepare(request.cluster_id, request.request_id, request.folder, files, request.message,
                                            request.plan_hash)
        existing = self.find_pr(branch)
        if existing is not None:
            return existing
        r = self._call("pr_open", "POST", f"{self._repo()}/pulls",
                       json={"head": branch, "base": self.default_branch, "title": title, "body": body}, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"open PR from {branch}: {r.status_code} {r.text[:300]}")
        pr = self._pr_ref(r.json())
        if pr.head_sha != head:
            raise GitUnavailable(f"PR #{pr.number} opened on {pr.head_sha[:8]}, not on the pushed head {head[:8]}")
        return pr

    def _pr_ref(self, p: Mapping[str, Any]) -> PrRef:
        return PrRef(number=p["number"], url=p["html_url"], branch=p["head"]["ref"], head_sha=p["head"]["sha"])

    def find_pr(self, branch: str) -> PrRef | None:
        owner = self.repository.split("/")[0]
        r = self._call("pr_find", "GET", f"{self._repo()}/pulls", params={"state": "open", "head": f"{owner}:{branch}"}, ok=(200,))
        if r.status_code != 200:
            raise GitUnavailable(f"find the PR of {branch}: {r.status_code} {r.text[:200]}")
        prs = r.json()
        return self._pr_ref(prs[0]) if prs else None

    def _pages(self, operation: str, path: str, key: str, **params: Any) -> list[Mapping[str, Any]]:
        """Every entry of a paginated list, or GitUnavailable: an unread page could hold the failure. The Link header says only
        whether there is a next page. Its URL is not called, because this client sends the token with every request."""
        entries: list[Mapping[str, Any]] = []
        for page in range(1, self.MAX_PAGES + 1):
            r = self._call(operation, "GET", path, params={**params, "per_page": 100, "page": page}, ok=(200,))
            if r.status_code != 200:
                raise GitUnavailable(f"{operation}: GET {path} page {page}: {r.status_code} {r.text[:200]}")
            entries.extend(r.json().get(key) or [])
            if "next" not in r.links:
                return entries
        raise GitUnavailable(f"{operation}: GET {path} has more than {self.MAX_PAGES} pages")

    def pr_status(self, pr: PrRef) -> PrStatus:
        r = self._call("pr_state", "GET", f"{self._repo()}/pulls/{pr.number}", ok=(200,))
        if r.status_code != 200:
            raise GitUnavailable(f"PR {pr.number}: {r.status_code} {r.text[:200]}")
        p = r.json()
        if p["state"] != "open":      # nothing reads a finished PR's checks, and a refused read must not hold back recording its end
            merged = bool(p.get("merged"))
            return PrStatus(state="merged" if merged else "closed", checks={}, merge_sha=p.get("merge_commit_sha") if merged else None)
        checks: dict[str, CheckState] = {}
        if self.external_ci:          # host CI on: the commit statuses, never the Checks API
            for st in self._pages("status_read", f"{self._repo()}/commits/{p['head']['sha']}/status", "statuses"):
                reported: CheckState = {"success": "success", "pending": "pending"}.get(st["state"], "failure")
                checks[st["context"]] = _worse(checks.get(st["context"]), reported)
        return PrStatus(state="open", checks=checks)

    def set_check(self, sha: str, context: str, state: CheckState, description: str, target_url: str | None = None) -> None:
        body: dict[str, Any] = {"context": context, "state": state, "description": description[:140]}
        if target_url:
            body["target_url"] = target_url
        r = self._call("status_write", "POST", f"{self._repo()}/statuses/{sha}", json=body, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"status {context} on {sha[:8]}: {r.status_code} {r.text[:200]}")

    def merge(self, pr: PrRef, expected_head: str) -> str:
        r = self._call("merge", "PUT", f"{self._repo()}/pulls/{pr.number}/merge",
                       json={"sha": expected_head, "merge_method": "merge", "commit_title": f"Merge {pr.branch}"}, ok=(200,))
        if r.status_code != 200:
            raise GitUnavailable(f"merge PR {pr.number}: {r.status_code} {r.text[:300]}")
        self._call("branch_delete", "DELETE", f"{self._repo()}/git/refs/heads/{pr.branch}", ok=(204, 422))
        return r.json()["sha"]

    def close(self, pr: PrRef, comment: str) -> None:
        self._call("pr_comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": comment}, ok=(201,))
        self._call("pr_close", "PATCH", f"{self._repo()}/pulls/{pr.number}", json={"state": "closed"})
