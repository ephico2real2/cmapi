"""The Git layer (#286): the Git protocol only, the same for every host. A platform adapter (core/git/github.py) adds the PR.

Working storage, in CMAPI_GIT_WORKDIR (an emptyDir with a sizeLimit in the pod; the decision and its measurements are in
docs/reviews/2026-11-15-issue-286):

    <workdir>/mirror.git                 one bare partial clone (--filter=blob:none) per process; blobs come when a read needs them
    <workdir>/<cluster>/<requestId>      one git worktree per request, on branch cmapi/<cluster>/<requestId>, cut from origin/main

A request's flow: fetch origin main; worktree add -b <branch> <dir> origin/main (never a local main, never git pull); write the
files of its folder; one commit whose trailers carry the request ID and the plan hash; push that branch alone, with a lease that
says it must not exist yet. Nothing here ever pushes to the default branch: the PR's merge happens on the host. Before that
merge, merge_check fetches main, runs git merge-tree --write-tree, and compares the request's folder on main with the plan's base.

One process owns a workdir (a lock file says so). Its calls are serialised by one lock, which the sweeper also takes: it runs
only when no other Git operation of this process does.
"""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import tempfile
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from cmapi.core.git.base import GitUnavailable
from cmapi.core.git.oplog import Op, redact, register_secret
from cmapi.core.observability import log
from cmapi.core.git.transport import (Credentials, GitConfigError, Remote, check_path, git_environment, load_credentials,
                                      parse_remote)

TRAILER_REQUEST = "Cmapi-Request"
TRAILER_PLAN_HASH = "Cmapi-Plan-Hash"
BRANCH_PREFIX = "cmapi/"
MIRROR = "mirror.git"
_SHA = re.compile(r"[0-9a-f]{40}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class BranchRefused(GitUnavailable):
    """The request's branch exists and was not written for this request and this plan: it is never adopted or overwritten."""


class GitFailed(GitUnavailable):
    def __init__(self, message: str, exit_code: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.exit_code, self.stderr = exit_code, stderr


@dataclass(frozen=True)
class MergeCheck:
    main_sha: str
    head_sha: str
    conflicts: tuple[str, ...] = ()
    folder_moved: bool = False
    tree: str | None = None                  # the merged tree, when clean

    @property
    def ok(self) -> bool:
        return not self.conflicts and not self.folder_moved


@dataclass
class SweepResult:
    skipped: bool = False
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)


def request_branch(cluster_id: str, request_id: str) -> str:
    """cmapi/<cluster>/<requestId>: the prefix keeps the bot's branches apart for host rules and the sweeper, and the cluster
    keeps the name unique across instances, whose request IDs are numbered each on its own (the coordinator, 2026-11-15)."""
    return f"{BRANCH_PREFIX}{cluster_id}/{request_id}"


BOT_NAME = "cmapi-git-bot"
BOT_EMAIL = "cmapi-git-bot@noreply.invalid"      # RFC 2606 .invalid: never delivered. instance.git.commitEmail names the real one


class GitWorkspace:
    """The bot's identity on every host is a machine user account, cmapi-git-bot (the owner, 2026-11-15): its SSH key and its
    API token. Commits name it as author and committer, with instance.git.commitEmail; the request, plan hash, approval and
    requester are in the trailers."""

    def __init__(self, url: str, *, default_branch: str = "main", workdir: Path | str | None = None,
                 credentials_dir: Path | str = "/etc/cmapi/git-bot", ssh_dir: Path | str | None = None,
                 known_hosts_dir: Path | str | None = None, ca_bundle: Path | str | None = None,
                 username: str | None = None, commit_email: str | None = None, timeout: float = 120.0,
                 git_binary: str | None = None):
        self.remote: Remote = parse_remote(url)
        self.default_branch, self.timeout = default_branch, timeout
        self._binary = git_binary or shutil.which("git")
        if not self._binary:
            raise GitConfigError("the Git layer needs the git binary on PATH (the image installs git-core)")
        if self.remote.transport == "ssh" and not shutil.which("ssh"):
            raise GitConfigError("Git over ssh needs the ssh binary on PATH (the image installs openssh-clients)")
        self._creds: Credentials = load_credentials(Path(credentials_dir), self.remote, username,
                                                    ssh_dir=Path(ssh_dir) if ssh_dir else None,
                                                    known_hosts_dir=Path(known_hosts_dir) if known_hosts_dir else None)
        register_secret(self._creds.token())
        self.author = (BOT_NAME, commit_email or BOT_EMAIL)
        self._ca = str(ca_bundle) if ca_bundle else None
        if self._ca and not Path(self._ca).is_file():
            raise GitConfigError(f"the Git CA bundle {self._ca} is not a file")
        owned = workdir is None
        self.root = Path(tempfile.mkdtemp(prefix="cmapi-git-")) if owned else Path(workdir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lockfile = open(self.root / ".lock", "w")
        try:
            fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise GitConfigError(f"{self.root} is the Git workdir of another process: each process has its own") from exc
        self.mirror = self.root / MIRROR
        self._home = self.root / ".home"
        self._home.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._env = git_environment(self.remote, self._creds, self._home, self._ca, self.author)
        self._tracking = f"refs/remotes/origin/{default_branch}"
        if self._run("check-ref-format", "--branch", default_branch, ok=(0, 1, 128)).returncode != 0:
            raise GitConfigError(f"{default_branch!r} is not a branch name")
        self._finalizer = weakref.finalize(self, _cleanup, self._lockfile, str(self.root) if owned else None)
        log.info("git_layer", url=self.remote.url, transport=self.remote.transport, workdir=str(self.root),
                 ssh_key_fingerprint=self._creds.fingerprint, author=f"{self.author[0]} <{self.author[1]}>")

    # ---- running git
    def _run(self, *args: str, cwd: Path | None = None, input: bytes | None = None, ok: tuple[int, ...] = (0,),
             git_dir: bool = False) -> subprocess.CompletedProcess[bytes]:
        argv = [self._binary, *((f"--git-dir={self.mirror}",) if git_dir else ()), *args]
        try:
            p = subprocess.run(argv, input=input, capture_output=True, env=self._env, cwd=cwd or self._home,
                               timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise GitFailed(f"git {args[0]} did not finish in {self.timeout:.0f} s") from exc
        except OSError as exc:
            raise GitFailed(f"git {args[0]}: {type(exc).__name__}: {exc}") from exc
        if p.returncode not in ok:
            err = redact(p.stderr.decode(errors="replace").strip())[-600:]
            raise GitFailed(f"git {args[0]} exited {p.returncode}: {err}", p.returncode, err)
        return p

    def _out(self, *args: str, **kw) -> str:
        return self._run(*args, **kw).stdout.decode().strip()

    def _m(self, *args: str, **kw) -> subprocess.CompletedProcess[bytes]:
        return self._run(*args, git_dir=True, **kw)

    @staticmethod
    def _failed(op: Op, exc: GitFailed) -> None:
        op.set(exit_code=exc.exit_code, stderr=exc.stderr)

    # ---- the mirror
    def _ensure_mirror(self) -> None:
        if (self.mirror / "HEAD").exists():
            if self._run("rev-parse", "--git-dir", git_dir=True, ok=(0, 128)).returncode == 0:
                for stale in self.mirror.rglob("*.lock"):            # a process that stopped mid-operation; this one owns the dir
                    stale.unlink(missing_ok=True)
                return
            shutil.rmtree(self.mirror)                              # not a repository any more: the remote is the source of truth
        # Not clone --mirror (+refs/*:refs/*, no origin/main) and not clone --bare (every branch as a local one): an empty bare
        # repository whose one fetch refspec is main's, as a partial clone. A fetch never writes the cmapi/* branches that the
        # worktrees hold (the review's measurement, #286).
        with Op("clone", url=self.remote.url) as op:
            try:
                self._run("init", "--quiet", "--bare", str(self.mirror))
                for key, value in (("remote.origin.url", self.remote.url),
                                   ("remote.origin.fetch", f"+refs/heads/{self.default_branch}:{self._tracking}"),
                                   ("remote.origin.promisor", "true"), ("remote.origin.partialclonefilter", "blob:none"),
                                   ("remote.origin.tagOpt", "--no-tags")):
                    self._m("config", key, value)
                self._fetch(self.default_branch, ensure=False)
            except GitFailed as exc:
                self._failed(op, exc)
                shutil.rmtree(self.mirror, ignore_errors=True)
                raise

    def _fetch(self, branch: str, ensure: bool = True) -> str | None:
        """The remote branch's head, fetched to refs/remotes/origin/<branch>; None when the remote has no such branch."""
        if ensure:
            self._ensure_mirror()
        tracking = f"refs/remotes/origin/{branch}"
        with Op("fetch", ref=branch) as op:
            try:
                p = self._m("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--filter=blob:none", "origin",
                            f"+refs/heads/{branch}:{tracking}", ok=(0, 128))
            except GitFailed as exc:
                self._failed(op, exc)
                raise
            if p.returncode != 0:
                err = redact(p.stderr.decode(errors="replace").strip())
                if "couldn't find remote ref" in err:
                    self._m("update-ref", "-d", tracking, ok=(0, 1))
                    op.outcome = "absent"
                    return None
                op.set(exit_code=p.returncode, stderr=err[-600:])
                raise GitFailed(f"fetch {branch}: {err[-400:]}", p.returncode, err[-600:])
            head = self._out("rev-parse", "--verify", f"{tracking}^{{commit}}", git_dir=True)
            op.set(**({"main_sha": head} if branch == self.default_branch else {"head_sha": head}))
            return head

    def fetch_main(self) -> str:
        head = self._fetch(self.default_branch)
        if head is None:
            raise GitUnavailable(f"branch {self.default_branch} does not exist in the repository")
        return head

    # ---- reads
    def _has_commit(self, sha: str) -> bool:
        return self._m("cat-file", "-e", f"{sha}^{{commit}}", ok=(0, 1, 128)).returncode == 0

    def _resolve(self, ref: str | None) -> str:
        if ref is None or ref == self.default_branch:
            return self.fetch_main()
        if _SHA.fullmatch(ref):
            if not self._has_commit(ref):
                self.fetch_main()
            if not self._has_commit(ref):
                raise GitUnavailable(f"commit {ref[:8]} is not in the repository")
            return ref
        if self._m("check-ref-format", "--branch", ref, ok=(0, 1, 128)).returncode != 0:
            raise GitUnavailable(f"{ref!r} is not a branch name")
        head = self._fetch(ref)
        if head is None:
            raise GitUnavailable(f"branch {ref} does not exist")
        return head

    def _folder(self, commit: str, path: str) -> dict[str, str]:
        path = path.strip("/")
        listing = self._m("ls-tree", "-z", commit, "--", f"{path}/" if path else ".").stdout.decode()
        blobs: list[tuple[str, str]] = []
        for entry in filter(None, listing.split("\0")):
            meta, name = entry.split("\t", 1)
            mode, kind, sha = meta.split(" ")
            # Regular files only, as GitHub's contents API types them "file": a symlink (120000) or a submodule is not a manifest.
            if kind == "blob" and mode in ("100644", "100755") and name.endswith(".yaml"):
                blobs.append((name, sha))
        if not blobs:
            return {}
        out = self._m("cat-file", "--batch", input="".join(f"{sha}\n" for _, sha in blobs).encode()).stdout
        files: dict[str, str] = {}
        pos = 0
        for name, _ in blobs:
            header_end = out.index(b"\n", pos)
            size = int(out[pos:header_end].split(b" ")[2])
            files[name] = out[header_end + 1:header_end + 1 + size].decode()
            pos = header_end + 1 + size + 1
        return files

    def read_folder(self, path: str, ref: str | None = None) -> tuple[dict[str, str], str]:
        """The .yaml files directly in path at ref (default: origin's default branch after a fetch), and that commit's sha."""
        with self._lock:
            head = self._resolve(ref)
            return self._folder(head, path), head

    def branch_head(self, branch: str) -> str | None:
        with self._lock:
            return self._fetch(branch)

    def contains(self, revision: str, sha: str) -> bool:
        """Whether sha is revision or one of its ancestors. A revision this repository does not hold is False."""
        if revision == sha:
            return True
        if not (_SHA.fullmatch(revision or "") and _SHA.fullmatch(sha or "")):
            return False
        with self._lock:
            self.fetch_main()
            return self._m("merge-base", "--is-ancestor", sha, revision, ok=(0, 1, 128)).returncode == 0

    def changed_paths(self, head: str) -> set[str]:
        """Every path that head changes since it left the default branch: git diff main...head. Git lists each one; no host
        limit applies (GitHub's compare stops at 300, #199)."""
        with self._lock:
            main = self.fetch_main()
            if not self._has_commit(head):
                raise GitUnavailable(f"commit {head[:8]} is not in the repository")
            out = self._m("diff", "--name-only", "--no-renames", "-z", f"{main}...{head}").stdout.decode()
        return {p for p in out.split("\0") if p}

    def log(self, n: int = 20) -> list[str]:
        with self._lock:
            head = self.fetch_main()
            out = self._out("log", f"-n{int(n)}", "--format=%H%x00%s", head, git_dir=True)
        return [f"{h[:8]} {s}" for h, s in (line.split("\0", 1) for line in out.splitlines() if line)]

    def carries(self, sha: str, request_id: str, plan_hash: str) -> bool:
        """Whether the commit's trailers name this request and this plan."""
        out = self._out("log", "-1", f"--format=%(trailers:key={TRAILER_REQUEST},valueonly,separator=%x1f)%x00"
                                     f"%(trailers:key={TRAILER_PLAN_HASH},valueonly,separator=%x1f)", sha, git_dir=True)
        requests, _, hashes = out.partition("\0")
        return request_id in requests.split("\x1f") and plan_hash in hashes.split("\x1f")

    # ---- the request's branch
    def worktree_path(self, cluster_id: str, request_id: str) -> Path:
        for part in (cluster_id, request_id):
            if not _NAME.fullmatch(part):
                raise ValueError(f"{part!r} cannot name a folder")
        return self.root / cluster_id / request_id

    def prepare(self, cluster_id: str, request_id: str, folder: str, files: Mapping[str, str | None], message: str,
                plan_hash: str) -> tuple[str, bool]:
        """The request's branch on the remote, holding one commit of files on origin/main: (its head, whether it already
        existed). A branch that exists is reused only if its head carries this request's trailers and plan hash; any other is
        refused (BranchRefused) and left alone."""
        folder = folder.strip("/")
        for path in files:
            check_path(path)
            if not path.startswith(folder + "/"):
                raise ValueError(f"{path} is outside the request's folder {folder}")
        branch = request_branch(cluster_id, request_id)
        with self._lock:
            main = self.fetch_main()
            existing = self._fetch(branch)
            if existing is not None:
                with Op("worktree", branch=branch, main_sha=main, head_sha=existing) as op:
                    if self.carries(existing, request_id, plan_hash):
                        op.set(reused=True)
                        return existing, True
                    op.outcome = "refused"
                    op.set(reason="the branch's head does not carry this request's trailers and plan hash")
                raise BranchRefused(f"branch {branch} exists at {existing[:8]}, and its head was not written for {request_id} "
                                    f"with plan {plan_hash[:12]}: it is not reused or overwritten")
            path = self.worktree_path(cluster_id, request_id)
            with Op("worktree", branch=branch, main_sha=main, base_sha=main, path=str(path)) as op:
                try:
                    self._drop(path, branch)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    self._m("worktree", "add", "--quiet", "--no-checkout", "-b", branch, str(path), self._tracking)
                    # Only the request's folder is checked out, so a repository of thousands of namespaces costs one folder.
                    self._run("sparse-checkout", "set", "--cone", folder, cwd=path)
                    self._run("checkout", "--quiet", branch, cwd=path)
                except GitFailed as exc:
                    self._failed(op, exc)
                    raise
            with Op("commit", branch=branch, base_sha=main) as op:
                try:
                    for rel, text in files.items():
                        target = path / rel
                        if text is None:
                            target.unlink(missing_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_text(text)
                    self._run("add", "--all", "--", folder, cwd=path)
                    if self._run("diff", "--cached", "--quiet", cwd=path, ok=(0, 1)).returncode == 0:
                        raise GitFailed(f"the plan changes nothing on {main[:8]}: nothing to commit")
                    self._run("commit", "--quiet", "--no-verify", "-F", "-", cwd=path, input=message.encode())
                    head = self._out("rev-parse", "HEAD", cwd=path)
                    op.set(head_sha=head)
                except GitFailed as exc:
                    self._failed(op, exc)
                    raise
            with Op("push", branch=branch, base_sha=main, head_sha=head) as op:
                ref = f"refs/heads/{branch}"
                # An empty lease: the branch must not exist. A branch made between the fetch above and this push is refused.
                p = self._run("push", "--porcelain", "--no-verify", f"--force-with-lease={ref}:", "origin", f"{branch}:{ref}",
                              cwd=path, ok=(0, 1, 128))
                if p.returncode != 0:
                    report = redact((p.stdout + p.stderr).decode(errors="replace"))
                    status = next((line for line in report.splitlines() if line.startswith("!\t")), report.strip()[-400:])
                    op.outcome = "refused" if p.returncode == 1 and "stale info" in status else "failure"
                    op.set(exit_code=p.returncode, stderr=status[-600:])
                    if op.outcome == "refused":
                        raise BranchRefused(f"branch {branch} appeared on the remote while pushing: {status.strip()}")
                    raise GitFailed(f"push {branch}: {status.strip()}", p.returncode, status)
            return head, False

    def merge_check(self, head: str, folder: str, base_files: Mapping[str, str]) -> MergeCheck:
        """Before a merge: fetch main, git merge-tree --write-tree main head (exit 0 clean, 1 conflicts, anything else an error:
        git-merge-tree(1), EXIT STATUS), and the request's folder on main compared with the plan's base."""
        with self._lock:
            main = self.fetch_main()
            if not self._has_commit(head):
                self._fetch_commit(head)
            with Op("merge_check", main_sha=main, head_sha=head) as op:
                try:
                    p = self._m("merge-tree", "--write-tree", "--name-only", "-z", main, head, ok=(0, 1))
                except GitFailed as exc:
                    self._failed(op, exc)
                    raise
                parts = p.stdout.decode().split("\0")
                tree = parts[0].strip()
                conflicts: tuple[str, ...] = ()
                if p.returncode == 1:
                    # -z --name-only: the tree, then one NUL-ended name per conflicted file, then an empty field, then messages.
                    names = []
                    for item in parts[1:]:
                        if not item:
                            break
                        names.append(item)
                    conflicts = tuple(sorted(set(names)))
                moved = self._folder(main, folder) != dict(base_files)
                check = MergeCheck(main, head, conflicts, moved, tree if p.returncode == 0 else None)
                op.set(conflicts=list(conflicts), folder_moved=moved)
                if not check.ok:
                    op.outcome = "conflict"
                return check

    def _fetch_commit(self, sha: str) -> None:
        """A PR head that is not on any branch fetched yet: GitHub and the others serve a commit by sha to a fetch."""
        self._m("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "origin", sha, ok=(0, 128))
        if not self._has_commit(sha):
            raise GitUnavailable(f"commit {sha[:8]} is not in the repository")

    # ---- cleanup
    def _drop(self, path: Path, branch: str) -> None:
        """This process's worktree and local branch of a request, gone: a retry starts again from origin/main."""
        if path.exists():
            self._m("worktree", "remove", "--force", "--force", str(path), ok=(0, 128))
            if path.exists():
                shutil.rmtree(path)
        self._m("worktree", "prune", ok=(0,))
        if self._m("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", ok=(0, 1)).returncode == 0:
            self._m("branch", "--quiet", "-D", branch)

    def remove(self, cluster_id: str, request_id: str) -> None:
        """git worktree remove, when the request reaches a final state. The remote branch stays: the host deletes it on merge."""
        if not (self.mirror / "HEAD").exists():
            return
        branch = request_branch(cluster_id, request_id)
        with self._lock, Op("cleanup", branch=branch, scope="request") as op:
            try:
                self._drop(self.worktree_path(cluster_id, request_id), branch)
            except GitFailed as exc:
                self._failed(op, exc)
                raise

    def sweep(self, in_flight: Iterable[tuple[str, str]]) -> SweepResult:
        """When no Git operation of this process runs: prune worktrees, remove the folder and branch of each request not in
        flight, and gc --auto. In flight is approved or pr_open, where a request's worktree may still be needed."""
        result = SweepResult()
        if not self._lock.acquire(blocking=False):
            result.skipped = True
            with Op("cleanup", scope="sweep") as op:
                op.outcome = "skipped"
            return result
        try:
            with Op("cleanup", scope="sweep") as op:
                if not (self.mirror / "HEAD").exists():
                    op.outcome = "skipped"
                    return result
                keep = {(c, r) for c, r in in_flight}
                try:
                    self._m("worktree", "prune")
                    for cluster_dir in sorted(p for p in self.root.iterdir() if p.is_dir() and p.name not in (MIRROR, ".home")):
                        for wt in sorted(p for p in cluster_dir.iterdir() if p.is_dir()):
                            name = f"{cluster_dir.name}/{wt.name}"
                            if (cluster_dir.name, wt.name) in keep:
                                result.kept.append(name)
                                continue
                            self._drop(wt, request_branch(cluster_dir.name, wt.name))
                            result.removed.append(name)
                        if not any(cluster_dir.iterdir()):
                            cluster_dir.rmdir()
                    # A local request branch whose worktree is already gone (a folder removed by hand): it goes too.
                    for ref in self._out("for-each-ref", "--format=%(refname:short)", f"refs/heads/{BRANCH_PREFIX}", git_dir=True).splitlines():
                        cluster, _, rid = ref[len(BRANCH_PREFIX):].partition("/")
                        if (cluster, rid) not in keep and not (self.root / cluster / rid).exists():
                            self._m("branch", "--quiet", "-D", ref)
                    self._m("gc", "--auto", "--quiet")
                except GitFailed as exc:
                    self._failed(op, exc)
                    raise
                op.set(removed=result.removed, kept=len(result.kept))
            return result
        finally:
            self._lock.release()

    def dispose(self) -> None:
        """Release the workdir; a temporary one (no CMAPI_GIT_WORKDIR) is removed."""
        self._finalizer()


def _cleanup(lockfile, root: str | None) -> None:
    try:
        lockfile.close()
    finally:
        if root:
            shutil.rmtree(root, ignore_errors=True)
