"""GitProvider for Gitea (API v1). Endpoints as documented for Gitea 1.25:

    GET  /repos/{o}/{r}/branches/{b}                    head sha
    GET  /repos/{o}/{r}/contents/{path}?ref=            folder listing, file content (base64)
    POST /repos/{o}/{r}/branches                        {new_branch_name, old_ref_name}
    POST /repos/{o}/{r}/contents                        one commit with several files {files: [...]}
    POST /repos/{o}/{r}/pulls                           {head, base, title, body}
    GET  /repos/{o}/{r}/pulls/{n}                       state, merged, head.sha, merge_commit_sha
    GET  /repos/{o}/{r}/pulls?state=open&head=          open PR from a branch
    POST /repos/{o}/{r}/statuses/{sha}                  commit status {state, context, description}
    GET  /repos/{o}/{r}/commits/{sha}/status            combined status
    POST /repos/{o}/{r}/pulls/{n}/merge                 {Do: merge, head_commit_id, delete_branch_after_merge}
    PATCH /repos/{o}/{r}/pulls/{n}                      {state: closed}
"""
from __future__ import annotations

import base64
from typing import Any, Mapping

from cmapi.core.git.base import CheckState, GitUnavailable, HostGitProvider
from cmapi.core.ports import PrRef, PrStatus


class GiteaProvider(HostGitProvider):
    def _repo(self) -> str:
        return f"/repos/{self.repository}"

    def branch_head(self, branch: str) -> str | None:
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{branch}", ok=(200, 404))
        return r.json()["commit"]["id"] if r.status_code == 200 else None

    def _entries(self, path: str, ref: str) -> list[dict[str, Any]]:
        r = self._call("read_folder", "GET", f"{self._repo()}/contents/{path.strip('/')}", params={"ref": ref},
                       ok=(200, 404))
        if r.status_code == 404:
            return []
        body = r.json()
        return body if isinstance(body, list) else [body]

    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        ref = ref or self.default_branch
        head = self.branch_head(ref) if not _is_sha(ref) else ref
        if head is None:
            raise GitUnavailable(f"branch {ref} does not exist")
        files: dict[str, str] = {}
        for e in self._entries(path, head):
            if e.get("type") == "file" and e["name"].endswith(".yaml"):
                r = self._call("read_file", "GET", f"{self._repo()}/contents/{e['path']}", params={"ref": head})
                files[e["path"]] = base64.b64decode(r.json()["content"]).decode()
        return files, head

    def open_pr(self, branch: str, files: Mapping[str, str | None], title: str, body: str, base_sha: str) -> PrRef:
        existing = self.find_pr(branch)
        if existing is not None:
            return existing
        if self.branch_head(branch) is not None:
            # No open PR, yet the branch exists: a closed PR, or a crash before the PR. Anyone may have pushed to it,
            # and a new PR would adopt that head as the bot's own. Start again from the base.
            r = self._call("delete_branch", "DELETE", f"{self._repo()}/branches/{branch}", ok=(204,))
            if r.status_code != 204:
                raise GitUnavailable(f"delete stale branch {branch}: {r.status_code} {r.text[:200]}")
        if self.branch_head(branch) is None:
            r = self._call("create_branch", "POST", f"{self._repo()}/branches",
                           json={"new_branch_name": branch, "old_ref_name": base_sha}, ok=(201,))
            if r.status_code != 201:
                raise GitUnavailable(f"create branch {branch}: {r.status_code} {r.text[:200]}")
        current, _ = self.read_folder(_common_folder(files), branch)
        ops = []
        for path, text in files.items():
            if text is None:
                if path in current:
                    ops.append({"operation": "delete", "path": path, "sha": self._blob_sha(path, branch)})
            elif path in current:
                if current[path] != text:
                    ops.append({"operation": "update", "path": path, "sha": self._blob_sha(path, branch),
                                "content": _b64(text)})
            else:
                ops.append({"operation": "create", "path": path, "content": _b64(text)})
        if ops:
            r = self._call("commit", "POST", f"{self._repo()}/contents",
                           json={"branch": branch, "message": f"{title}\n\n{body}", "files": ops,
                                 "author": {"name": self.BOT_NAME, "email": self.BOT_EMAIL},
                                 "committer": {"name": self.BOT_NAME, "email": self.BOT_EMAIL}}, ok=(200, 201))
            if r.status_code not in (200, 201):
                raise GitUnavailable(f"commit on {branch}: {r.status_code} {r.text[:300]}")
        r = self._call("open_pr", "POST", f"{self._repo()}/pulls",
                       json={"head": branch, "base": self.default_branch, "title": title, "body": body}, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"open PR from {branch}: {r.status_code} {r.text[:300]}")
        return self._pr_ref(r.json())

    def changed_paths(self, head: str) -> set[str]:
        r = self._call("compare", "GET", f"{self._repo()}/compare/{self.default_branch}...{head}")
        if r.status_code != 200:
            raise GitUnavailable(f"compare {head[:8]}: {r.status_code} {r.text[:200]}")
        return {f["filename"] for c in r.json().get("commits") or [] for f in c.get("files") or []}

    def _blob_sha(self, path: str, ref: str) -> str:
        r = self._call("read_file", "GET", f"{self._repo()}/contents/{path}", params={"ref": ref})
        return r.json()["sha"]

    def _pr_ref(self, p: Mapping[str, Any]) -> PrRef:
        return PrRef(number=p["number"], url=p.get("html_url") or f"{self.web_url}/{self.repository}/pulls/{p['number']}",
                     branch=p["head"]["ref"], head_sha=p["head"]["sha"])

    def find_pr(self, branch: str) -> PrRef | None:
        r = self._call("find_pr", "GET", f"{self._repo()}/pulls", params={"state": "open", "limit": 50})
        for p in r.json():
            if p["head"]["ref"] == branch:
                return self._pr_ref(p)
        return None

    def pr_status(self, pr: PrRef) -> PrStatus:
        r = self._call("pr_status", "GET", f"{self._repo()}/pulls/{pr.number}")
        if r.status_code != 200:
            raise GitUnavailable(f"PR {pr.number}: {r.status_code}")
        p = r.json()
        head = p["head"]["sha"]
        checks: dict[str, CheckState] = {}
        s = self._call("pr_checks", "GET", f"{self._repo()}/commits/{head}/status", ok=(200, 404))
        if s.status_code == 200:
            for st in s.json().get("statuses") or []:
                checks[st["context"]] = {"success": "success", "pending": "pending"}.get(st["status"], "failure")
        state = "merged" if p.get("merged") else ("open" if p["state"] == "open" else "closed")
        return PrStatus(state=state, checks=checks, merge_sha=p.get("merge_commit_sha") if p.get("merged") else None)

    def set_check(self, sha: str, context: str, state: CheckState, description: str, target_url: str | None = None) -> None:
        body = {"context": context, "state": state, "description": description[:255]}
        if target_url:
            body["target_url"] = target_url
        r = self._call("set_check", "POST", f"{self._repo()}/statuses/{sha}", json=body, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"status {context} on {sha[:8]}: {r.status_code} {r.text[:200]}")

    def merge(self, pr: PrRef, expected_head: str) -> str:
        r = self._call("merge", "POST", f"{self._repo()}/pulls/{pr.number}/merge",
                       json={"Do": "merge", "head_commit_id": expected_head, "delete_branch_after_merge": True,
                             "MergeTitleField": f"Merge {pr.branch}"}, ok=(200,))
        if r.status_code != 200:
            raise GitUnavailable(f"merge PR {pr.number}: {r.status_code} {r.text[:300]}")
        p = self._call("pr_status", "GET", f"{self._repo()}/pulls/{pr.number}").json()
        return p.get("merge_commit_sha") or self.branch_head(self.default_branch) or ""

    def close(self, pr: PrRef, comment: str) -> None:
        self._call("comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": comment}, ok=(201,))
        self._call("close", "PATCH", f"{self._repo()}/pulls/{pr.number}", json={"state": "closed"}, ok=(201, 200))

    def log(self, n: int = 20) -> list[str]:
        r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "limit": n})
        return [f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}" for c in r.json()]

    def protect_default_branch(self, contexts: list[str]) -> None:
        """One-time setup: nobody pushes to main; merges need every context green (the cmapi check)."""
        body = {"branch_name": self.default_branch, "enable_push": False, "enable_status_check": True,
                "status_check_contexts": contexts, "block_on_rejected_reviews": True, "enable_merge_whitelist": False}
        r = self._call("protect", "POST", f"{self._repo()}/branch_protections", json=body, ok=(201, 403, 422))
        if r.status_code == 422:                               # already protected: update it
            self._call("protect", "PATCH", f"{self._repo()}/branch_protections/{self.default_branch}", json=body)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _is_sha(ref: str) -> bool:
    return len(ref) == 40 and all(c in "0123456789abcdef" for c in ref)


def _common_folder(files: Mapping[str, Any]) -> str:
    paths = list(files)
    if not paths:
        return ""
    parts = paths[0].split("/")[:-1]
    for p in paths[1:]:
        q = p.split("/")[:-1]
        while parts and parts != q[:len(parts)]:
            parts = parts[:-1]
    return "/".join(parts)
