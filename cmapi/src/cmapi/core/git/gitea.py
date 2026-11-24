"""GitProvider for Gitea (API v1). Endpoints as documented for Gitea 1.25:

    GET  /repos/{o}/{r}/branches/{b}                    head sha
    GET  /repos/{o}/{r}/git/commits/{sha}               a commit: its message (the trailers) and its parents
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
from itertools import count
from pathlib import PurePosixPath
from typing import Any, Iterator, Mapping
from urllib.parse import quote

from cmapi.core.git.base import (BranchRequest, CheckState, GitUnavailable, HostGitProvider, PushResult, manifest_text,
                                 refuse_lost_names)
from cmapi.core.git.workspace import TRAILER_PLAN_HASH, TRAILER_REQUEST, BranchMoved, BranchRefused, request_branch
from cmapi.core.ports import PrRef, PrStatus


class GiteaProvider(HostGitProvider):
    name = "gitea"
    object_id_lengths = (40, 64)        # a Gitea repository is SHA-1 or SHA-256, as the Git layer's _OID reads both

    def _repo(self) -> str:
        return f"/repos/{self.repository}"

    def branch_head(self, branch: str) -> str | None:
        # A name is data in the path: "#", "?" and "%" are escaped (RFC 3986, sections 2.4 and 3.3). Gitea routes branches,
        # compare and contents with a "/*" wildcard, so a "/" in a branch name or a file path stays a "/" (#638).
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{quote(branch)}", ok=(200, 404))
        return r.json()["commit"]["id"] if r.status_code == 200 else None

    def _tree_entries(self, oid: str) -> Iterator[dict[str, Any]]:
        for page in count(1):
            r = self._call("read_folder", "GET", f"{self._repo()}/git/trees/{oid}", params={"page": page})
            if r.status_code != 200:
                raise GitUnavailable(f"read tree {oid}: HTTP {r.status_code}")
            body = r.json()
            entries = body["tree"] or []
            if body["truncated"] and (not entries or body["page"] != page):
                raise GitUnavailable(f"incomplete page {page} of tree {oid}")
            yield from entries
            if not body["truncated"]:
                return

    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        head = self._folder_head(ref)
        # Gitea Contents resolves a branch or tag before a commit. Trees and blobs accept object IDs.
        directory = PurePosixPath(path.strip("/"))
        tree = head
        for i, part in enumerate(directory.parts):
            entry = next((e for e in self._tree_entries(tree) if e["path"] == part), None)
            if entry is None:
                return {}, head
            if entry["type"] != "tree":
                if i + 1 < len(directory.parts):
                    return {}, head
                entries = [entry]       # Contents also supports a direct file path.
                directory = directory.parent
                break
            tree = entry["sha"]
        else:
            entries = self._tree_entries(tree)
        manifests = {str(directory / e["path"]): e["sha"] for e in entries
                     if e["type"] == "blob" and e["mode"] in ("100644", "100755") and e["path"].endswith(".yaml")}
        # Gitea's JSON writes a byte that is not UTF-8 as U+FFFD (json-iterator): no plan can name the file (#626).
        refuse_lost_names(manifests)
        texts: dict[str, bytes] = {}
        for path, sha in manifests.items():
            r = self._call("read_file", "GET", f"{self._repo()}/git/blobs/{sha}")
            if r.status_code != 200:
                raise GitUnavailable(f"read blob {sha}: HTTP {r.status_code}")
            texts[path] = base64.b64decode(r.json()["content"])
        return manifest_text(texts), head

    def list_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        """Every blob and submodule under path, at any depth (#616): each subtree read with _tree_entries, page by page, so no
        recursive listing that the host may cut is read as complete."""
        entries, head = self._walk(path, ref)
        refuse_lost_names(entries)               # a delete removes each path, so it must name each one (#626)
        return {p: kind for p, (kind, _) in entries.items()}, head

    def _walk(self, path: str, ref: str | None) -> tuple[dict[str, tuple[str, str]], str]:
        """list_folder with each entry's object ID: {path: (type, ID)}. The ID is what a delete sends as its sha, the tree
        entry's own, which Gitea compares it with, so no URL has to carry a name that holds "#" or "?" (#616)."""
        head = self._folder_head(ref)
        tree = head
        directory = PurePosixPath(path.strip("/"))
        for part in directory.parts:
            entry = next((e for e in self._tree_entries(tree) if e["path"] == part), None)
            if entry is None or entry["type"] != "tree":
                return {}, head
            tree = entry["sha"]
        listed: dict[str, tuple[str, str]] = {}
        pending = [(directory, tree)]
        while pending:
            where, oid = pending.pop()
            for e in self._tree_entries(oid):
                if e["type"] == "tree":
                    pending.append((where / e["path"], e["sha"]))
                else:
                    listed[str(where / e["path"])] = (e["type"], e["sha"])
        return listed, head

    def push_request_branch(self, req: BranchRequest) -> PushResult:
        """Through Gitea's REST API, not the Git layer: the chart's stand-in, whose Gitea the cluster serves over plain http, which
        the Git layer refuses. A branch that exists is handled as the Git layer handles it (the arbitration of #286, row 3;
        #450): adopted when its head is this request's commit of this plan with the plan's files; deleted and written again
        when it is this request's own stale attempt; refused, and left as it is, when it is anyone else's. An open PR proves
        nothing about the head. REST has no lease, so the delete of a stale attempt reads the head first (delete_branch)."""
        branch = request_branch(req.cluster_id, req.request_id)
        base = self.branch_head(self.default_branch)
        if base is None:
            raise GitUnavailable(f"branch {self.default_branch} does not exist")
        existing = self.branch_head(branch)
        if existing is not None:
            trailers, parents = self._commit(existing)
            planned = {p: t for p, t in req.files.items() if t is not None}
            if trailers.get(TRAILER_REQUEST) != [req.request_id]:
                raise BranchRefused(f"branch {branch} exists at {existing[:8]} and its head is not cmapi's commit for "
                                    f"{req.request_id}: it is not adopted or overwritten")
            if trailers.get(TRAILER_PLAN_HASH) == [req.plan_hash] and len(parents) == 1 and \
                    self.read_folder(req.folder, existing)[0] == planned:
                return PushResult(existing, parents[0], "adopted")
            if not self.delete_branch(branch, existing):
                raise BranchMoved(f"branch {branch} moved from {existing[:8]} before its stale attempt was replaced")
        r = self._call("create_branch", "POST", f"{self._repo()}/branches",
                       json={"new_branch_name": branch, "old_ref_name": base}, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"create branch {branch}: {r.status_code} {self.host_text(r, 200)}")
        current, _ = self.read_folder(req.folder, branch)
        # A removal is any path of the folder, not only a manifest (#616). Only a plan that removes one walks the subfolders.
        listed = self._walk(req.folder, branch)[0] if any(text is None for text in req.files.values()) else {}
        ops = []
        for path, text in req.files.items():
            if text is None:
                if path in listed:
                    ops.append({"operation": "delete", "path": path, "sha": listed[path][1]})
            elif path in current:
                if current[path] != text:
                    ops.append({"operation": "update", "path": path, "sha": self._blob_sha(path, branch), "content": _b64(text)})
            else:
                ops.append({"operation": "create", "path": path, "content": _b64(text)})
        if ops:
            r = self._call("commit", "POST", f"{self._repo()}/contents",
                           json={"branch": branch, "message": req.message, "files": ops,
                                 "author": {"name": self.BOT_NAME, "email": self.BOT_EMAIL},
                                 "committer": {"name": self.BOT_NAME, "email": self.BOT_EMAIL}}, ok=(200, 201))
            if r.status_code not in (200, 201):
                raise GitUnavailable(f"commit on {branch}: {r.status_code} {self.host_text(r)}")
        head = self.branch_head(branch)
        return PushResult(head or base, base, "created" if existing is None else "replaced")

    def _commit(self, sha: str) -> tuple[dict[str, list[str]], list[str]]:
        """A commit's cmapi trailers ({key: [values]}, from its message's last paragraph) and its parents' shas."""
        r = self._call("commit_read", "GET", f"{self._repo()}/git/commits/{sha}", ok=(200,))
        if r.status_code != 200:
            raise GitUnavailable(f"read commit {sha[:8]}: {r.status_code} {self.host_text(r, 200)}")
        body = r.json()
        paragraphs = [p for p in ((body.get("commit") or {}).get("message") or "").strip().split("\n\n") if p.strip()]
        trailers: dict[str, list[str]] = {}
        for line in (paragraphs[-1].splitlines() if paragraphs else []):
            key, sep, value = line.partition(":")
            if sep and key.strip() in (TRAILER_REQUEST, TRAILER_PLAN_HASH):
                trailers.setdefault(key.strip(), []).append(value.strip())
        return trailers, [p["sha"] for p in body.get("parents") or []]


    def recreate_branch(self, req: BranchRequest, base: str, expected: str) -> str:
        raise GitUnavailable("the Gitea stand-in is not on the Git layer: a closed PR's branch is not re-created")

    def open_pr(self, branch: str, head: str, title: str, body: str) -> PrRef:
        existing = self.find_pr(branch)
        if existing is None:
            r = self._call("open_pr", "POST", f"{self._repo()}/pulls",
                           json={"head": branch, "base": self.default_branch, "title": title, "body": body}, ok=(201,))
            if r.status_code != 201:
                raise GitUnavailable(f"open PR from {branch}: {r.status_code} {self.host_text(r)}")
            existing = self._pr_ref(r.json())
        return existing

    def comment(self, pr: PrRef, text: str) -> None:
        self._call("comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": text}, ok=(201,))

    def delete_branch(self, branch: str, expected: str) -> bool:
        """Gitea's REST delete is not conditional: the head is read first, and a race in between is the stand-in's to accept."""
        head = self.branch_head(branch)
        if head is None:
            return True
        if head != expected:
            return False
        r = self._call("delete_branch", "DELETE", f"{self._repo()}/branches/{quote(branch)}", ok=(204, 404))
        return r.status_code in (204, 404)

    def list_open(self, prefix: str) -> list[PrRef]:
        r = self._call("find_pr", "GET", f"{self._repo()}/pulls", params={"state": "open", "limit": 50})
        return [self._pr_ref(p) for p in r.json() if p["head"]["ref"].startswith(prefix)]

    def list_branches(self, prefix: str) -> dict[str, str]:
        r = self._call("branches", "GET", f"{self._repo()}/branches", params={"limit": 50})
        return {b["name"]: b["commit"]["id"] for b in r.json() if b["name"].startswith(prefix)}

    def branch_time(self, sha: str) -> int:
        from datetime import datetime

        r = self._call("commit_read", "GET", f"{self._repo()}/git/commits/{sha}")
        return int(datetime.fromisoformat(r.json()["created"].replace("Z", "+00:00")).timestamp())

    def contains(self, revision: str, sha: str) -> bool:
        if revision == sha:
            return True
        r = self._call("compare", "GET", f"{self._repo()}/compare/{quote(revision)}...{sha}")
        if r.status_code == 404:      # not this repository's: a multi-source Application's other source, or a force-pushed commit
            return False
        if r.status_code != 200:
            raise GitUnavailable(f"compare {revision[:8]}...{sha[:8]}: {r.status_code} {self.host_text(r, 200)}")
        return r.json().get("total_commits", 1) == 0

    def changed_paths(self, head: str) -> set[str]:
        r = self._call("compare", "GET", f"{self._repo()}/compare/{quote(self.default_branch)}...{head}")
        if r.status_code != 200:
            raise GitUnavailable(f"compare {head[:8]}: {r.status_code} {self.host_text(r, 200)}")
        return {f["filename"] for c in r.json().get("commits") or [] for f in c.get("files") or []}

    def _blob_sha(self, path: str, ref: str) -> str:
        r = self._call("read_file", "GET", f"{self._repo()}/contents/{quote(path)}", params={"ref": ref})
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
        return PrStatus(state=state, checks=checks, merge_sha=p.get("merge_commit_sha") if p.get("merged") else None, head_sha=head)

    def set_check(self, sha: str, context: str, state: CheckState, description: str, target_url: str | None = None) -> None:
        body = {"context": context, "state": state, "description": description[:255]}
        if target_url:
            body["target_url"] = target_url
        r = self._call("set_check", "POST", f"{self._repo()}/statuses/{sha}", json=body, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"status {context} on {sha[:8]}: {r.status_code} {self.host_text(r, 200)}")

    def merge(self, pr: PrRef, expected_head: str) -> str:
        r = self._call("merge", "POST", f"{self._repo()}/pulls/{pr.number}/merge",
                       json={"Do": "merge", "head_commit_id": expected_head, "delete_branch_after_merge": False,
                             "MergeTitleField": f"Merge {pr.branch}"}, ok=(200,))
        if r.status_code != 200:
            raise GitUnavailable(f"merge PR {pr.number}: {r.status_code} {self.host_text(r)}")
        p = self._call("pr_status", "GET", f"{self._repo()}/pulls/{pr.number}").json()
        return p.get("merge_commit_sha") or self.branch_head(self.default_branch) or ""

    def close(self, pr: PrRef, comment: str) -> None:
        self._call("comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": comment}, ok=(201,))
        self._call("close", "PATCH", f"{self._repo()}/pulls/{pr.number}", json={"state": "closed"}, ok=(201, 200))

    def log(self, n: int = 20) -> list[str]:
        r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "limit": n})
        return self.commit_lines(r.json())


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


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
