"""What the platform adapters share (#286): one httpx client, one structured event per host call, and the error contract.

The platform layer is thin: open a PR from the request branch, read its state, merge it pinned to a sha, comment, close. A
provider with a Git layer (GitHub) writes branches and reads trees through it; one without (the Gitea stand-in) through REST.

A Git host failure is GitUnavailable; the worker turns it into a retry with backoff. HeadMoved and NotMergeable say why a
merge did not happen; PlatformRefused is a refusal that a retry cannot fix. Each call logs its op, outcome, HTTP status and,
on a refusal, the host's message (core/git/oplog.py), and counts in cmapi_git_platform_requests_total{platform,op,code}.

The host's message is text the host chose: a host or a proxy in front of it may echo the request, the Authorization header
included. So every text taken from an answer passes through host_text, which removes each form of the bot's credential and
only then cuts (docs/02 "Client rules", #424); every error, request event, log line and API answer built from it is clean.
"""
from __future__ import annotations

import base64
import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Literal, Mapping

import httpx

from cmapi.core.clients.redact import order_forms, redact, redact_cut, sent_forms
from cmapi.core.ports import PrRef, PrStatus

CheckState = Literal["pending", "success", "failure"]


class GitUnavailable(RuntimeError):
    pass


class IncompleteList(GitUnavailable):
    """The host gave a list that it can have cut, so nothing may read it as complete. A caller that does not handle it
    treats the host as unavailable, which is the safe reading."""


class PlatformRefused(GitUnavailable):
    """401, 403, 404, 422 and the like: the host said no, and saying it again will not change that."""

    def __init__(self, message: str, status: int | None = None, host_message: str = ""):
        super().__init__(message)
        self.status, self.host_message = status, host_message


class HeadMoved(PlatformRefused):
    """The PR's head is not the pinned sha: nothing was merged."""


class NotMergeable(GitUnavailable):
    """The host will not merge now. transient: it is still computing, or a required check is pending."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class BranchRequest:
    """What a provider needs to write a request's branch."""
    cluster_id: str
    request_id: str
    folder: str
    plan_hash: str
    message: str
    files: Mapping[str, str | None]              # the plan's files: text, or None for a path the plan removes
    prev: Mapping[str, str]                      # the folder before the plan (plan.prev)
    approved_at: datetime                        # both commit dates: the reproducible commit


@dataclass(frozen=True)
class PushResult:
    head: str
    base: str
    result: Literal["created", "adopted", "replaced"]


@dataclass(frozen=True)
class MergeCheck:
    """git merge-tree --write-tree <main> <head>, and the folder's two comparisons (Fable 2.3)."""
    main_sha: str
    head_sha: str
    conflicts: tuple[str, ...] = ()
    base_matches: bool = True                    # the folder on main is the plan's prev
    result_matches: bool = True                  # the folder in the merged tree is the plan's files
    tree: str | None = None

    @property
    def ok(self) -> bool:
        return not self.conflicts and self.base_matches and self.result_matches

    def reason(self, branch: str = "main") -> str:
        if self.conflicts:
            return f"conflicts with {branch} at {self.main_sha[:8]} in {', '.join(self.conflicts)}"
        if not self.base_matches:
            return f"the folder on {branch} at {self.main_sha[:8]} is no longer the plan's base"
        if not self.result_matches:
            return f"the merge of {self.head_sha[:8]} into {branch} at {self.main_sha[:8]} would not leave the folder as planned"
        return "clean"


def is_commit_id(ref: str, lengths: tuple[int, ...] = (40,)) -> bool:
    """Whether an explicit ref has the spelling of a full lowercase object ID of one of these lengths (SHA-1 has 40)."""
    return len(ref) in lengths and all(c in "0123456789abcdef" for c in ref)


def credential_values(token: str | None, basic_auth: tuple[str, str] | None) -> tuple[str, ...]:
    """Each value of the bot's credential that a host could echo: the token, and with Basic auth the password and the header's
    value as httpx sends it, base64 of user:password in UTF-8 (RFC 7617)."""
    values = [token or ""]
    if basic_auth:
        user, password = basic_auth
        values += [password, base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")]
    return tuple(v for v in values if v)


class HostGitProvider:
    """The contract. Subclasses fill in the host's endpoints."""

    name = "host"
    BOT_NAME = "cmapi-git-bot"
    BOT_EMAIL = "cmapi-git-bot@noreply.invalid"
    # Whether the host's own CI reports ci/kubeconform and ci/kyverno, as commit statuses. The worker then waits for them there.
    external_ci = False
    # Whether the worker posts its checks as commit statuses. The Gitea stand-in protects main with them (protect_default_branch);
    # GitHub posts nothing unless host CI or git.postStatus is on (the arbitration of #286, row 11).
    post_statuses = True

    def __init__(self, api_url: str, repository: str, token: str, *, default_branch: str = "main",
                 verify: ssl.SSLContext | str | bool = True, web_url: str | None = None, timeout: float = 20.0,
                 basic_auth: tuple[str, str] | None = None):
        self.api_url, self.repository, self.default_branch = api_url.rstrip("/"), repository, default_branch
        self.web_url = (web_url or self.api_url).rstrip("/")
        self._client = httpx.Client(base_url=self.api_url, verify=verify, timeout=timeout,
                                    headers=self._headers(token) if token else {"Accept": "application/json"},
                                    auth=basic_auth)
        from cmapi.core.git.oplog import register_secret

        credentials = credential_values(token, basic_auth)
        for value in credentials:
            register_secret(value)
        self._forms = order_forms({form for value in credentials for form in sent_forms(value)})

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"token {token}", "Accept": "application/json"}

    def redact(self, text: str) -> str:
        """`text` without the bot's credential in any form (core/clients/redact.py): the whole text, before any cut."""
        return redact(text, self._forms)

    def host_text(self, r: httpx.Response, limit: int = 300) -> str:
        """The host's answer as error text: redacted, then cut to `limit` characters (#424)."""
        return redact_cut(r.text, self._forms, limit)

    def commit_lines(self, commits: Iterable[Mapping[str, Any]]) -> list[str]:
        """`<short sha> <subject>` of each commit of the host's list. The subject is text the host returns, and GET
        /api/v1/admin/git-log serves it to every reports:read caller, so it is redacted; the sha is left as it is (#424)."""
        return [f"{c['sha'][:8]} {self.redact(c['commit']['message'].splitlines()[0])}" for c in commits]

    def _call(self, operation: str, method: str, path: str, *, ok: tuple[int, ...] = (200, 201, 204),
              log_fields: Mapping[str, Any] | None = None, **kw: Any) -> httpx.Response:
        from cmapi.core.git.oplog import Op
        from cmapi.core.observability import PLATFORM_REQUESTS

        with Op(operation, method=method, path=path, platform=self.name, **(log_fields or {})) as op:
            try:
                r = self._client.request(method, path, **kw)
            except httpx.HTTPError as exc:
                PLATFORM_REQUESTS.labels(self.name, operation, "error").inc()
                op.outcome = "retry"
                # An HTTP library's error can show the header it refused ("illegal header value b'...'"). Not chained: the
                # worker logs traceback.format_exc(), which prints the cause's own, unredacted text (#444).
                raise GitUnavailable(self.redact(f"{operation}: {type(exc).__name__}: {exc}")) from None
            PLATFORM_REQUESTS.labels(self.name, operation, f"{r.status_code // 100}xx").inc()
            op.set(http_status=r.status_code, host_request_id=r.headers.get("x-github-request-id") or r.headers.get("x-request-id"))
            if r.status_code >= 500 or r.status_code == 429:
                op.set(message=self.host_text(r))
                op.outcome = "retry"
                raise GitUnavailable(f"{operation}: the Git host answered {r.status_code}: {self.host_text(r, 200)}")
            if r.status_code not in ok:
                op.outcome = "refused"
                op.set(message=self.host_text(r))
            return r

    # ---- the Git side: a Git layer, or the host's REST API
    # How long a full object ID is on this host: 40 hex characters (SHA-1). A host with SHA-256 repositories adds 64.
    object_id_lengths: tuple[int, ...] = (40,)

    def _folder_head(self, ref: str | None) -> str:
        """An omitted ref selects the configured branch. An explicit object ID pins the read."""
        if ref and is_commit_id(ref, self.object_id_lengths):
            return ref
        branch = ref or self.default_branch
        head = self.branch_head(branch)
        if head is None:
            raise GitUnavailable(f"branch {branch} does not exist")
        return head

    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        """Files under path at ref (default branch head), keyed by repository path, and the commit sha."""
        raise NotImplementedError

    def tree_files(self, ref: str, folder: str) -> dict[str, str]:
        files, _ = self.read_folder(folder, ref)
        return files

    def list_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        """Every entry under path at ref, at any depth, that is not a folder, and the commit sha: {repository path: Git object
        type}, "blob" for a file, an executable or a symlink and "commit" for a submodule. read_folder reads cmapi's manifests
        (the .yaml files directly in the folder); this lists what a delete removes, whatever made it (#616). IncompleteList
        when the host cannot give each entry."""
        raise NotImplementedError

    def branch_head(self, branch: str) -> str | None:
        raise NotImplementedError

    def contains(self, revision: str, sha: str) -> bool:
        """Whether sha is revision or one of its ancestors."""
        raise NotImplementedError

    def changed_paths(self, head: str) -> set[str]:
        """Every path any commit on head touches since it left the default branch. IncompleteList when the host cannot
        give each one."""
        raise NotImplementedError

    def log(self, n: int = 20) -> list[str]:
        raise NotImplementedError

    def push_request_branch(self, req: BranchRequest) -> PushResult:
        """The request's branch, one commit of the plan on the default branch's head."""
        raise NotImplementedError

    def recreate_branch(self, req: BranchRequest, base: str, expected: str) -> str:
        """The branch again from its recorded base, the same sha (the reproducible commit)."""
        raise NotImplementedError

    def merge_check(self, head: str, folder: str, prev: Mapping[str, str], files: Mapping[str, str | None]) -> MergeCheck:
        """Before an apply and a merge. With no Git layer (the Gitea stand-in): the folder on the default branch compared with the
        plan's base; the host's own merge refuses a conflict. A provider with the Git layer runs git merge-tree."""
        from cmapi.core.git.oplog import Op

        with Op("merge_check", head_sha=head) as op:
            on_main, main = self.read_folder(folder)
            check = MergeCheck(main, head, (), on_main == dict(prev), True)
            op.set(main_sha=main, base_matches=check.base_matches)
            if not check.ok:
                op.outcome = "refused"
            return check

    def delete_branch(self, branch: str, expected: str) -> bool:
        """Delete the host's branch only when it is at expected. Missing is success."""
        raise NotImplementedError

    def list_branches(self, prefix: str) -> dict[str, str]:
        """{branch: sha} of the host's branches under prefix, for git_reconcile."""
        raise NotImplementedError

    def request_of(self, sha: str) -> str | None:
        """The Cmapi-Request-Id trailer of a commit: whose branch head this is. None: not cmapi's, or not known."""
        return None

    def branch_time(self, sha: str) -> int:
        """The commit time of a branch head, for git_reconcile's grace period."""
        raise NotImplementedError

    # ---- the PR: the host's API
    def find_pr(self, branch: str) -> PrRef | None:
        """The open PR from the branch into the default branch."""
        raise NotImplementedError

    def open_pr(self, branch: str, head: str, title: str, body: str) -> PrRef:
        """Open it, or return the one that exists for the branch. Its head must be head."""
        raise NotImplementedError

    def pr_status(self, pr: PrRef) -> PrStatus:
        raise NotImplementedError

    def merge(self, pr: PrRef, expected_head: str) -> str:
        """Merge only if the PR head is expected_head: the merge sha. HeadMoved, NotMergeable, PlatformRefused, GitUnavailable."""
        raise NotImplementedError

    def comment(self, pr: PrRef, text: str) -> None:
        raise NotImplementedError

    def close(self, pr: PrRef, comment: str) -> None:
        raise NotImplementedError

    def list_open(self, prefix: str) -> list[PrRef]:
        """Every open PR whose source branch starts with prefix, all pages, or it raises."""
        raise NotImplementedError

    def set_check(self, sha: str, context: str, state: CheckState, description: str, target_url: str | None = None) -> None:
        raise NotImplementedError

    # ---- this pod's working storage
    def cleanup(self, cluster_id: str, request_id: str) -> None:
        """The request's worktree on this pod. A provider with no Git layer keeps none."""

    def sweep(self, open_requests: Iterable[tuple[str, str]]):
        """The sweeper's pass, in the worker loop between jobs. A provider with no Git layer has nothing to sweep."""
        return None

    def dispose(self) -> None:
        """Release what the provider holds at shutdown. Not close(), which closes a PR."""
