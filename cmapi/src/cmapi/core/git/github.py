"""GitProvider for GitHub's REST API (the design's default, docs/02 "Git provider in rest mode").

Files are written through the Git Data API as one commit (blobs, tree, commit, ref), because
the contents API commits one file at a time. The cmapi check is a commit status with context
cmapi/check, which branch protection requires. ci/kubeconform and ci/kyverno are check runs from the
config repository's own Actions, which the combined status does not include, so pr_status reads both.
The App's permissions: Contents, Pull requests and Commit statuses read/write, Checks read, Metadata
read. Endpoints as documented by GitHub (2026-11):

    GET  /repos/{o}/{r}/branches/{b}            GET  /repos/{o}/{r}/contents/{path}?ref=
    POST /repos/{o}/{r}/git/refs                POST /repos/{o}/{r}/git/blobs, /git/trees, /git/commits
    PATCH /repos/{o}/{r}/git/refs/heads/{b}     POST /repos/{o}/{r}/pulls   GET /repos/{o}/{r}/pulls?head=
    GET  /repos/{o}/{r}/pulls/{n}               GET  /repos/{o}/{r}/commits/{sha}/status, /check-runs
    POST /repos/{o}/{r}/statuses/{sha}          PUT  /repos/{o}/{r}/pulls/{n}/merge {sha}
    PATCH /repos/{o}/{r}/pulls/{n}              POST /repos/{o}/{r}/issues/{n}/comments

pr_status and the calls pr_checks makes are tested on a MockTransport (tests/service/test_github_check_runs.py).
Nothing here has run against GitHub itself: this Mac's cluster has no GitHub.
"""
from __future__ import annotations

import base64
from typing import Any, Mapping

from cmapi.core.git.base import CheckState, GitUnavailable, HostGitProvider
from cmapi.core.ports import PrRef, PrStatus


def _worse(a: CheckState | None, b: CheckState) -> CheckState:
    """One context reported twice reads as the worse report: a pass from one source never hides the other's failure."""
    return max(a or b, b, key=("success", "pending", "failure").index)


def _run_state(run: Mapping[str, Any]) -> CheckState:
    """What one check run says about a required check. Unfinished is pending, whatever else the run carries. Finished is a pass
    only on the conclusion success. GitHub also treats neutral and skipped as passing for a required check; here ci/* is the
    evidence that the validation ran and passed, and a skipped run validated nothing, so they fail, as does a value not known yet."""
    if run.get("status") != "completed":
        return "pending"
    return "success" if run.get("conclusion") == "success" else "failure"


class GitHubProvider(HostGitProvider):
    external_ci = True
    MAX_PAGES = 100      # 10,000 entries on one commit: past this a host is not answering a list, and a partial list must not read as complete

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def _repo(self) -> str:
        return f"/repos/{self.repository}"

    def branch_head(self, branch: str) -> str | None:
        r = self._call("branch_head", "GET", f"{self._repo()}/branches/{branch}", ok=(200, 404))
        return r.json()["commit"]["sha"] if r.status_code == 200 else None

    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        ref = ref or self.default_branch
        head = ref if len(ref) == 40 else self.branch_head(ref)
        if head is None:
            raise GitUnavailable(f"branch {ref} does not exist")
        r = self._call("read_folder", "GET", f"{self._repo()}/contents/{path.strip('/')}", params={"ref": head},
                       ok=(200, 404))
        files: dict[str, str] = {}
        if r.status_code == 200:
            entries = r.json()
            for e in (entries if isinstance(entries, list) else [entries]):
                if e.get("type") == "file" and e["name"].endswith(".yaml"):
                    f = self._call("read_file", "GET", f"{self._repo()}/contents/{e['path']}", params={"ref": head})
                    files[e["path"]] = base64.b64decode(f.json()["content"]).decode()
        return files, head

    def open_pr(self, branch: str, files: Mapping[str, str | None], title: str, body: str, base_sha: str) -> PrRef:
        existing = self.find_pr(branch)
        if existing is not None:
            return existing
        if self.branch_head(branch) is not None:      # see GiteaProvider.open_pr: never adopt a head the bot did not write
            self._call("delete_branch", "DELETE", f"{self._repo()}/git/refs/heads/{branch}", ok=(204,))
        head = self.branch_head(branch)
        if head is None:
            r = self._call("create_branch", "POST", f"{self._repo()}/git/refs",
                           json={"ref": f"refs/heads/{branch}", "sha": base_sha}, ok=(201,))
            if r.status_code != 201:
                raise GitUnavailable(f"create branch {branch}: {r.status_code} {r.text[:200]}")
            head = base_sha
        tree_entries = []
        for path, text in files.items():
            if text is None:
                tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            else:
                b = self._call("blob", "POST", f"{self._repo()}/git/blobs", json={"content": text, "encoding": "utf-8"},
                               ok=(201,)).json()
                tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": b["sha"]})
        base_commit = self._call("commit_read", "GET", f"{self._repo()}/git/commits/{head}").json()
        tree = self._call("tree", "POST", f"{self._repo()}/git/trees",
                          json={"base_tree": base_commit["tree"]["sha"], "tree": tree_entries}, ok=(201,)).json()
        commit = self._call("commit", "POST", f"{self._repo()}/git/commits",
                            json={"message": f"{title}\n\n{body}", "tree": tree["sha"], "parents": [head],
                                  "author": {"name": self.BOT_NAME, "email": self.BOT_EMAIL}}, ok=(201,)).json()
        self._call("update_ref", "PATCH", f"{self._repo()}/git/refs/heads/{branch}", json={"sha": commit["sha"]})
        r = self._call("open_pr", "POST", f"{self._repo()}/pulls",
                       json={"head": branch, "base": self.default_branch, "title": title, "body": body}, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"open PR from {branch}: {r.status_code} {r.text[:300]}")
        return self._pr_ref(r.json())

    def contains(self, revision: str, sha: str) -> bool:
        if revision == sha:
            return True
        r = self._call("compare", "GET", f"{self._repo()}/compare/{revision}...{sha}")
        if r.status_code == 404:      # not this repository's: a multi-source Application's other source, or a force-pushed commit
            return False
        if r.status_code != 200:
            raise GitUnavailable(f"compare {revision[:8]}...{sha[:8]}: {r.status_code} {r.text[:200]}")
        return r.json().get("ahead_by", 1) == 0

    def changed_paths(self, head: str) -> set[str]:
        r = self._call("compare", "GET", f"{self._repo()}/compare/{self.default_branch}...{head}")
        if r.status_code != 200:
            raise GitUnavailable(f"compare {head[:8]}: {r.status_code} {r.text[:200]}")
        return {f["filename"] for f in r.json().get("files") or []}

    def _pr_ref(self, p: Mapping[str, Any]) -> PrRef:
        return PrRef(number=p["number"], url=p["html_url"], branch=p["head"]["ref"], head_sha=p["head"]["sha"])

    def find_pr(self, branch: str) -> PrRef | None:
        owner = self.repository.split("/")[0]
        r = self._call("find_pr", "GET", f"{self._repo()}/pulls", params={"state": "open", "head": f"{owner}:{branch}"})
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

    def _check_runs(self, head: str) -> list[Mapping[str, Any]]:
        """The check runs of a commit, one per check. filter=latest asks for the latest attempts; within one check suite of one App
        a later id replaces an earlier one of the same name, in case a re-run's attempts still come back together. Two suites or two
        Apps reporting one name are two checks, and both count."""
        latest: dict[tuple[Any, Any, Any], Mapping[str, Any]] = {}
        for run in self._pages("pr_check_runs", f"{self._repo()}/commits/{head}/check-runs", "check_runs", filter="latest"):
            key = (run["name"], (run.get("app") or {}).get("id"), (run.get("check_suite") or {}).get("id"))
            if key not in latest or run["id"] > latest[key]["id"]:
                latest[key] = run
        return list(latest.values())

    def pr_status(self, pr: PrRef) -> PrStatus:
        r = self._call("pr_status", "GET", f"{self._repo()}/pulls/{pr.number}", ok=(200,))
        if r.status_code != 200:
            raise GitUnavailable(f"PR {pr.number}: {r.status_code} {r.text[:200]}")
        p = r.json()
        if p["state"] != "open":      # nothing reads a finished PR's checks, and a refused read must not hold back recording its end
            merged = bool(p.get("merged"))
            return PrStatus(state="merged" if merged else "closed", checks={}, merge_sha=p.get("merge_commit_sha") if merged else None)
        head = p["head"]["sha"]
        checks: dict[str, CheckState] = {}
        for st in self._pages("pr_checks", f"{self._repo()}/commits/{head}/status", "statuses"):
            reported: CheckState = {"success": "success", "pending": "pending"}.get(st["state"], "failure")
            checks[st["context"]] = _worse(checks.get(st["context"]), reported)
        for run in self._check_runs(head):
            checks[run["name"]] = _worse(checks.get(run["name"]), _run_state(run))
        return PrStatus(state="open", checks=checks)

    def set_check(self, sha: str, context: str, state: CheckState, description: str, target_url: str | None = None) -> None:
        body: dict[str, Any] = {"context": context, "state": state, "description": description[:140]}
        if target_url:
            body["target_url"] = target_url
        r = self._call("set_check", "POST", f"{self._repo()}/statuses/{sha}", json=body, ok=(201,))
        if r.status_code != 201:
            raise GitUnavailable(f"status {context} on {sha[:8]}: {r.status_code} {r.text[:200]}")

    def merge(self, pr: PrRef, expected_head: str) -> str:
        r = self._call("merge", "PUT", f"{self._repo()}/pulls/{pr.number}/merge",
                       json={"sha": expected_head, "merge_method": "merge", "commit_title": f"Merge {pr.branch}"}, ok=(200,))
        if r.status_code != 200:
            raise GitUnavailable(f"merge PR {pr.number}: {r.status_code} {r.text[:300]}")
        self._call("delete_branch", "DELETE", f"{self._repo()}/git/refs/heads/{pr.branch}", ok=(204, 422))
        return r.json()["sha"]

    def close(self, pr: PrRef, comment: str) -> None:
        self._call("comment", "POST", f"{self._repo()}/issues/{pr.number}/comments", json={"body": comment}, ok=(201,))
        self._call("close", "PATCH", f"{self._repo()}/pulls/{pr.number}", json={"state": "closed"})

    def log(self, n: int = 20) -> list[str]:
        r = self._call("log", "GET", f"{self._repo()}/commits", params={"sha": self.default_branch, "per_page": n})
        return [f"{c['sha'][:8]} {c['commit']['message'].splitlines()[0]}" for c in r.json()]
