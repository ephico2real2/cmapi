"""What the Gitea and GitHub adapters share: one httpx client, metrics, and the error contract.

A Git host failure is GitUnavailable; the worker turns it into a retry with backoff and, after
five attempts, a failed request (502 git-unavailable on the API side).
"""
from __future__ import annotations

import time
from typing import Any, Literal, Mapping

import httpx

from cmapi.core.observability import GIT_DURATION, GIT_OPS
from cmapi.core.ports import PrRef, PrStatus

CheckState = Literal["pending", "success", "failure"]


class GitUnavailable(RuntimeError):
    pass


class HostGitProvider:
    """The contract. Subclasses fill in the host's endpoints."""

    BOT_NAME = "cmapi-bot"
    BOT_EMAIL = "cmapi-bot@ephico2real.com"

    def __init__(self, api_url: str, repository: str, token: str, *, default_branch: str = "main",
                 verify: str | bool = True, web_url: str | None = None, timeout: float = 20.0):
        self.api_url, self.repository, self.default_branch = api_url.rstrip("/"), repository, default_branch
        self.web_url = (web_url or self.api_url).rstrip("/")
        self._client = httpx.Client(base_url=self.api_url, verify=verify, timeout=timeout, headers=self._headers(token))

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"token {token}", "Accept": "application/json"}

    def _call(self, operation: str, method: str, path: str, *, ok: tuple[int, ...] = (200, 201, 204),
              **kw: Any) -> httpx.Response:
        started = time.perf_counter()
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            GIT_OPS.labels(operation, "failure").inc()
            raise GitUnavailable(f"{operation}: {type(exc).__name__}: {exc}") from exc
        finally:
            GIT_DURATION.labels(operation).observe(time.perf_counter() - started)
        if r.status_code >= 500:
            GIT_OPS.labels(operation, "failure").inc()
            raise GitUnavailable(f"{operation}: the Git host answered {r.status_code}: {r.text[:200]}")
        GIT_OPS.labels(operation, "ok" if r.status_code in ok else "refused").inc()
        return r

    # ---- the GitProvider protocol, plus what the cmapi check needs
    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        """Files under path at ref (default branch head), keyed by repository path, and the commit sha."""
        raise NotImplementedError

    def open_pr(self, branch: str, files: Mapping[str, str | None], title: str, body: str, base_sha: str) -> PrRef:
        raise NotImplementedError

    def pr_status(self, pr: PrRef) -> PrStatus:
        raise NotImplementedError

    def set_check(self, sha: str, context: str, state: CheckState, description: str, target_url: str | None = None) -> None:
        raise NotImplementedError

    def merge(self, pr: PrRef, expected_head: str) -> str:
        raise NotImplementedError

    def close(self, pr: PrRef, comment: str) -> None:
        raise NotImplementedError

    def branch_head(self, branch: str) -> str | None:
        raise NotImplementedError

    def find_pr(self, branch: str) -> PrRef | None:
        """An open PR from the branch, so a retried open_pr never opens a second one."""
        raise NotImplementedError

    def tree_files(self, ref: str, folder: str) -> dict[str, str]:
        files, _ = self.read_folder(folder, ref)
        return files

    def log(self, n: int = 20) -> list[str]:
        raise NotImplementedError
