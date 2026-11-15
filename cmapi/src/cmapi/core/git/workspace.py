"""The Git layer (#286): the Git protocol only, the same for every host. A platform adapter (core/git/github.py) adds the PR.

Working storage, in CMAPI_GIT_WORKDIR (an emptyDir with a sizeLimit in the worker pod; the decision and its measurements are in
docs/reviews/2026-11-15-issue-286):

    <workdir>/repo.git                   one bare partial clone per process: git init --bare, one fetch refspec
                                         +refs/heads/main:refs/remotes/origin/main, --filter=blob:none. Not clone --mirror
                                         (+refs/*:refs/*) and not clone --bare (every branch as a local one): measured, both
                                         write refs/heads/cmapi/* on fetch, the branches the worktrees hold
    <workdir>/<cluster>/<requestId>      one git worktree per request, on branch cmapi/<cluster>/<requestId>
    <workdir>/.lock                      flock: one process owns the workdir

A request's branch: fetch origin main; worktree add -b <branch> <dir> <origin/main's sha> (never a local main, never git pull);
the folder's files; one commit whose dates are the approval's, so the same plan on the same main gives the same sha on any
replica (reproducible); a push of that branch alone with a lease. Nothing here pushes to the default branch: the PR merges on
the host. A branch that exists on the remote is adopted when it passes the adoption test, replaced with a lease when it is this
request's own stale attempt, and refused when its head is anyone else's (the arbitration of #286, rows 3 and 5).

One process, one lock (the arbitration, row 7): the worker runs one job at a time, so a single lock serialises every Git
operation of the process, and the sweeper takes it without waiting.
"""
from __future__ import annotations

import fcntl
import re
import shutil
import subprocess
import tempfile
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Mapping

from cmapi.core.git.base import BranchRequest, GitUnavailable, MergeCheck, PushResult
from cmapi.core.git.oplog import Op, redact, register_secret
from cmapi.core.git.transport import Credentials, GitConfigError, Remote, check_path, git_environment, load_credentials, parse_remote
from cmapi.core.observability import GIT_WORKDIR_BYTES, GIT_WORKTREES, SWEEPER_RUNS, log

TRAILER_REQUEST = "Cmapi-Request-Id"
TRAILER_PLAN_HASH = "Cmapi-Plan-Hash"
BRANCH_PREFIX = "cmapi/"
REPO = "repo.git"
FETCHED = "refs/cmapi-fetched/"
BOT_NAME = "cmapi-git-bot"
BOT_EMAIL = "cmapi-git-bot@noreply.invalid"      # RFC 2606 .invalid: never delivered. instance.git.commitEmail names the real one
_OID = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class BranchRefused(GitUnavailable):
    """The request's branch exists and its head is not cmapi's for this request: it is never adopted or overwritten."""


class BranchMoved(GitUnavailable):
    """A lease was refused: someone wrote the ref between the read and the push. The job reads again (a retry)."""


class GitFailed(GitUnavailable):
    def __init__(self, message: str, exit_code: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.exit_code, self.stderr = exit_code, stderr


@dataclass
class SweepResult:
    result: Literal["ok", "skipped", "recloned", "error"] = "ok"
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)


def request_branch(cluster_id: str, request_id: str) -> str:
    """cmapi/<cluster>/<requestId>: the prefix keeps the bot's branches apart for host rules and the sweeper, and the cluster
    keeps the name unique across instances, whose request IDs are numbered each on its own (the coordinator, 2026-11-15)."""
    return f"{BRANCH_PREFIX}{cluster_id}/{request_id}"


def _under(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


class GitWorkspace:
    """The bot's identity on every host is a machine user account, cmapi-git-bot (the owner, 2026-11-15): commits name it as
    author and committer, with instance.git.commitEmail; the request, plan hash, approval and requester are in the trailers."""

    def __init__(self, url: str, *, default_branch: str = "main", workdir: Path | str | None = None,
                 credentials_dir: Path | str = "/etc/cmapi/git-bot", ssh_dir: Path | str | None = None,
                 known_hosts_dir: Path | str | None = None, ca_bundle: Path | str | None = None,
                 username: str | None = None, commit_email: str | None = None, timeout: float = 120.0,
                 size_limit: int = 1 << 30, git_binary: str | None = None):
        self.remote: Remote = parse_remote(url)
        self.default_branch, self.timeout, self.size_limit = default_branch, timeout, size_limit
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
            self._lockfile.close()
            raise GitConfigError(f"{self.root} is the Git workdir of another process: each process has its own") from exc
        self.mirror = self.root / REPO
        self._home = self.root / ".home"
        self._home.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._env = git_environment(self.remote, self._creds, self._home, self._ca, self.author)
        self._tracking = f"refs/remotes/origin/{default_branch}"
        self._refspec = f"+refs/heads/{default_branch}:{self._tracking}"
        if self._run("check-ref-format", "--branch", default_branch, ok=(0, 1, 128)).returncode != 0:
            raise GitConfigError(f"{default_branch!r} is not a branch name")
        self._finalizer = weakref.finalize(self, _release, self._lockfile, str(self.root) if owned else None)
        self._repair()
        log.info("git_layer", url=self.remote.url, transport=self.remote.transport, workdir=str(self.root),
                 ssh_key_fingerprint=self._creds.fingerprint, author=f"{self.author[0]} <{self.author[1]}>")

    # ---- running git
    def _run(self, *args: str, cwd: Path | None = None, input: bytes | None = None, ok: tuple[int, ...] = (0,),
             git_dir: bool = False, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
        argv = [self._binary, *((f"--git-dir={self.mirror}",) if git_dir else ()), *args]
        try:
            p = subprocess.run(argv, input=input, capture_output=True, env=dict(env or self._env), cwd=cwd or self._home,
                               timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise GitFailed(f"git {args[0]} did not finish in {self.timeout:.0f} s") from exc
        except OSError as exc:
            raise GitFailed(f"git {args[0]}: {type(exc).__name__}: {exc}") from exc
        if p.returncode not in ok:
            err = redact(p.stderr.decode(errors="replace").strip())[-2000:]
            raise GitFailed(f"git {args[0]} exited {p.returncode}: {err[-400:]}", p.returncode, err)
        return p

    def _out(self, *args: str, **kw) -> str:
        return self._run(*args, **kw).stdout.decode().strip()

    def _m(self, *args: str, **kw) -> subprocess.CompletedProcess[bytes]:
        return self._run(*args, git_dir=True, **kw)

    @staticmethod
    def _failed(op: Op, exc: GitFailed) -> None:
        op.set(exit_code=exc.exit_code, stderr=exc.stderr)

    # ---- the repository
    def _repair(self) -> None:
        """At start (a container restart keeps an emptyDir): stale lock files go, worktrees are pruned, and a repository whose
        remote or refspec is not this one's is removed, to be fetched again. This process owns the workdir (flock), so no git
        process can own those lock files."""
        if not (self.mirror / "HEAD").exists():
            return
        with Op("cleanup", scope="startup") as op:
            ok = self._m("rev-parse", "--git-dir", ok=(0, 128)).returncode == 0
            if ok:
                url = self._m("config", "--get", "remote.origin.url", ok=(0, 1)).stdout.decode().strip()
                spec = self._m("config", "--get-all", "remote.origin.fetch", ok=(0, 1)).stdout.decode().split()
                ok = url == self.remote.url and spec == [self._refspec]
            if not ok:
                shutil.rmtree(self.mirror)
                op.set(reason="not this remote or refspec: fetched again", removed=[REPO])
                return
            removed = []
            for stale in list(self.mirror.rglob("*.lock")) + list(self.mirror.glob("gc.pid")):
                stale.unlink(missing_ok=True)
                removed.append(str(stale.relative_to(self.root)))
            self._m("worktree", "prune")
            op.set(removed=removed)

    def _ensure_mirror(self) -> None:
        if (self.mirror / "HEAD").exists():
            return
        with Op("clone", url=self.remote.url, refspec=self._refspec) as op:
            try:
                self._run("init", "--quiet", "--bare", str(self.mirror))
                for key, value in (("remote.origin.url", self.remote.url), ("remote.origin.fetch", self._refspec),
                                   ("remote.origin.promisor", "true"), ("remote.origin.partialclonefilter", "blob:none"),
                                   ("remote.origin.tagOpt", "--no-tags"), ("gc.auto", "0"), ("maintenance.auto", "false")):
                    self._m("config", key, value)
                self._fetch_into(self.default_branch, self._tracking)
            except GitFailed as exc:
                self._failed(op, exc)
                shutil.rmtree(self.mirror, ignore_errors=True)
                raise

    def _fetch_into(self, branch: str, target: str) -> str | None:
        """refs/heads/<branch> of origin into target; None when the remote has no such branch."""
        with Op("fetch", ref=branch, refspec=f"+refs/heads/{branch}:{target}") as op:
            try:
                p = self._m("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--no-auto-maintenance", "--filter=blob:none",
                            "origin", f"+refs/heads/{branch}:{target}", ok=(0, 128))
            except GitFailed as exc:
                self._failed(op, exc)
                raise
            if p.returncode != 0:
                err = redact(p.stderr.decode(errors="replace").strip())
                if "couldn't find remote ref" in err:
                    self._m("update-ref", "-d", target, ok=(0, 1))
                    op.set(absent=True)
                    return None
                op.set(exit_code=p.returncode, stderr=err[-2000:])
                raise GitFailed(f"fetch {branch}: {err[-400:]}", p.returncode, err[-2000:])
            head = self._out("rev-parse", "--verify", f"{target}^{{commit}}", git_dir=True)
            op.set(**({"main_sha": head} if branch == self.default_branch else {"head_sha": head}))
            return head

    def fetch_main(self) -> str:
        with self._lock:
            self._ensure_mirror()
            head = self._fetch_into(self.default_branch, self._tracking)
        if head is None:
            raise GitUnavailable(f"branch {self.default_branch} does not exist in the repository")
        return head

    def fetch_branch(self, branch: str) -> str | None:
        """A request branch, into refs/cmapi-fetched/<cluster>/<requestId>: never into a worktree's branch."""
        with self._lock:
            self._ensure_mirror()
            return self._fetch_into(branch, FETCHED + branch[len(BRANCH_PREFIX):])

    def ls_remote(self, pattern: str) -> dict[str, str]:
        """{branch: sha} of the remote's branches that match refs/heads/<pattern>."""
        with self._lock, Op("ls_remote", pattern=pattern) as op:
            self._ensure_mirror()
            try:
                out = self._m("ls-remote", "--heads", "origin", f"refs/heads/{pattern}").stdout.decode()
            except GitFailed as exc:
                self._failed(op, exc)
                raise
            heads = {ref[len("refs/heads/"):]: sha for sha, ref in (line.split("\t", 1) for line in out.splitlines() if "\t" in line)}
            op.set(found=len(heads))
            return heads

    # ---- reads
    def _has_commit(self, sha: str) -> bool:
        return self._m("cat-file", "-e", f"{sha}^{{commit}}", ok=(0, 1, 128)).returncode == 0

    def _need(self, sha: str) -> None:
        """A commit by sha: the hosts serve a fetch by sha (uploadpack.allowAnySHA1InWant on a plain server)."""
        if not _OID.fullmatch(sha or ""):
            raise GitUnavailable(f"{sha!r} is not a commit sha")
        if self._has_commit(sha):
            return
        self._ensure_mirror()
        self._m("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--no-auto-maintenance", "--filter=blob:none", "origin", sha,
                ok=(0, 1, 128))
        if not self._has_commit(sha):
            raise GitUnavailable(f"commit {sha[:8]} is not in the repository")

    def _resolve(self, ref: str | None) -> str:
        if ref is None or ref == self.default_branch:
            return self.fetch_main()
        if _OID.fullmatch(ref):
            self._need(ref)
            return ref
        if self._m("check-ref-format", "--branch", ref, ok=(0, 1, 128)).returncode != 0:
            raise GitUnavailable(f"{ref!r} is not a branch name")
        head = self.fetch_branch(ref)
        if head is None:
            raise GitUnavailable(f"branch {ref} does not exist")
        return head

    def _folder(self, treeish: str, path: str) -> dict[str, str]:
        path = path.strip("/")
        listing = self._m("ls-tree", "-z", treeish, "--", f"{path}/" if path else ".").stdout.decode()
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
        """The remote branch's head, fetched. The default branch, or a request branch."""
        if branch == self.default_branch:
            return self.fetch_main()
        return self.fetch_branch(branch)

    def contains(self, revision: str, sha: str) -> bool:
        """Whether sha is revision or one of its ancestors. A revision this repository does not hold is False."""
        if revision == sha:
            return True
        if not (_OID.fullmatch(revision or "") and _OID.fullmatch(sha or "")):
            return False
        with self._lock:
            self.fetch_main()
            return self._m("merge-base", "--is-ancestor", sha, revision, ok=(0, 1, 128)).returncode == 0

    def changed_paths(self, head: str) -> set[str]:
        """Every path that head changes since it left the default branch: git diff main...head. Git lists each one: no host
        limit applies (GitHub's compare stops at 300, #199)."""
        with self._lock:
            main = self.fetch_main()
            self._need(head)
            out = self._m("diff", "--name-only", "--no-renames", "-z", f"{main}...{head}").stdout.decode()
        return {p for p in out.split("\0") if p}

    def log(self, n: int = 20) -> list[str]:
        with self._lock:
            head = self.fetch_main()
            out = self._out("log", f"-n{int(n)}", "--format=%H%x00%s", head, git_dir=True)
        return [f"{h[:8]} {s}" for h, s in (line.split("\0", 1) for line in out.splitlines() if line)]

    def trailers(self, sha: str) -> dict[str, list[str]]:
        out = self._out("log", "-1", f"--format=%(trailers:key={TRAILER_REQUEST},valueonly,separator=%x1f)%x00"
                                     f"%(trailers:key={TRAILER_PLAN_HASH},valueonly,separator=%x1f)", sha, git_dir=True)
        requests, _, hashes = out.partition("\0")
        return {TRAILER_REQUEST: [v for v in requests.split("\x1f") if v], TRAILER_PLAN_HASH: [v for v in hashes.split("\x1f") if v]}

    def commit_time(self, sha: str) -> int:
        with self._lock:
            self._need(sha)
            return int(self._out("log", "-1", "--format=%ct", sha, git_dir=True))

    # ---- the request's branch
    def worktree_path(self, cluster_id: str, request_id: str) -> Path:
        for part in (cluster_id, request_id):
            if not _NAME.fullmatch(part):
                raise ValueError(f"{part!r} cannot name a folder")
        return self.root / cluster_id / request_id

    def _check_files(self, req: BranchRequest) -> str:
        folder = req.folder.strip("/")
        for path in req.files:
            check_path(path)
            if not path.startswith(folder + "/"):
                raise ValueError(f"{path} is outside the request's folder {folder}")
        return folder

    def _adoptable(self, head: str, req: BranchRequest, folder: str) -> str | None:
        """Fable 2.2: one commit on its parent, the parent an ancestor of origin/main, this request's and plan's trailers, the
        changed paths inside the plan's, the folder at the head the plan's files, and at the parent the plan's prev. The reason it
        fails, or None."""
        parents = self._out("rev-list", "--parents", "-n1", head, git_dir=True).split()[1:]
        if len(parents) != 1:
            return f"{len(parents)} parents"
        parent = parents[0]
        if self._m("merge-base", "--is-ancestor", parent, self._tracking, ok=(0, 1, 128)).returncode != 0:
            return f"its parent {parent[:8]} is not on {self.default_branch}"
        t = self.trailers(head)
        if t[TRAILER_REQUEST] != [req.request_id] or t[TRAILER_PLAN_HASH] != [req.plan_hash]:
            return "its trailers are not this request's and plan's"
        changed = {p for p in self._m("diff", "--name-only", "--no-renames", "-z", parent, head).stdout.decode().split("\0") if p}
        if not changed <= set(req.files):
            return f"it changes {sorted(changed - set(req.files))[:3]}, outside the plan"
        if self._folder(head, folder) != {p: t for p, t in req.files.items() if t is not None}:
            return "its folder is not the plan's files"
        if self._folder(parent, folder) != dict(req.prev):
            return "the folder at its parent is not the plan's base"
        return None

    def _build(self, req: BranchRequest, folder: str, base: str) -> str:
        """One commit of the plan on base, in the request's worktree. Both dates are the approval's: the same plan on the same
        base gives the same sha on any replica and on any retry (Fable 2.1)."""
        branch = request_branch(req.cluster_id, req.request_id)
        path = self.worktree_path(req.cluster_id, req.request_id)
        with Op("worktree", action="add", path=str(path), base_sha=base) as op:
            try:
                self._drop(path, branch)
                path.parent.mkdir(parents=True, exist_ok=True)
                self._m("worktree", "add", "--quiet", "--no-checkout", "-b", branch, str(path), base)
                # Only the request's folder is checked out: a repository of thousands of namespaces costs one folder.
                self._run("sparse-checkout", "set", "--cone", folder, cwd=path)
                self._run("checkout", "--quiet", branch, cwd=path)
            except GitFailed as exc:
                self._failed(op, exc)
                raise
        with Op("commit", base_sha=base, plan_hash=req.plan_hash) as op:
            try:
                for rel, text in req.files.items():
                    target = path / rel
                    if text is None:
                        target.unlink(missing_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(text)
                self._run("add", "--all", "--", folder, cwd=path)
                staged = {p for p in self._run("diff", "--cached", "--name-only", "-z", cwd=path).stdout.decode().split("\0") if p}
                if not staged:
                    raise GitFailed(f"the plan changes nothing on {base[:8]}: nothing to commit")
                if not staged <= set(req.files):
                    raise GitFailed(f"the worktree stages {sorted(staged - set(req.files))[:3]}, outside the plan")
                when = f"{int(req.approved_at.timestamp())} +0000"
                env = {**self._env, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
                self._run("commit", "--quiet", "--no-verify", "-F", "-", cwd=path, input=req.message.encode(), env=env)
                head = self._out("rev-parse", "HEAD", cwd=path)
                op.set(head_sha=head, files_changed=len(staged), adopted=False)
                return head
            except GitFailed as exc:
                self._failed(op, exc)
                raise

    def _push(self, path: Path, branch: str, head: str, lease: str, result: str) -> None:
        ref = f"refs/heads/{branch}"
        with Op("push", head_sha=head, lease_sha=lease or None, forced=bool(lease)) as op:
            # From the repository itself: a worktree shares its objects, and a pod that never had this worktree can push too.
            p = self._m("push", "--porcelain", "--no-verify", f"--force-with-lease={ref}:{lease}", "origin", f"{head}:{ref}",
                        ok=(0, 1, 128))
            if p.returncode == 0:
                op.set(result=result)
                return
            report = redact((p.stdout + p.stderr).decode(errors="replace"))
            status = next((line for line in report.splitlines() if line.startswith("!\t")), report.strip()[-400:])
            op.set(exit_code=p.returncode, stderr=status[-2000:])
            if p.returncode == 1 and "stale info" in status:
                op.set(result="lease_rejected")
                op.outcome = "retry"
                raise BranchMoved(f"push {branch}: the lease on {(lease or 'no branch')[:8]} was refused: {status.strip()}")
            raise GitFailed(f"push {branch}: {status.strip()}", p.returncode, status)

    def push_branch(self, req: BranchRequest) -> PushResult:
        """The request's branch on the remote, one commit of the plan on origin/main. The caller checked, on the same fetch,
        that the folder on main is the plan's prev."""
        folder = self._check_files(req)
        branch = request_branch(req.cluster_id, req.request_id)
        with self._lock:
            main = self.fetch_main()
            existing = self.fetch_branch(branch)
            if existing is not None:
                why = self._adoptable(existing, req, folder)
                if why is None:
                    with Op("commit", head_sha=existing, adopted=True, plan_hash=req.plan_hash):
                        pass
                    return PushResult(existing, self._out("rev-parse", f"{existing}^", git_dir=True), "adopted")
                if self.trailers(existing)[TRAILER_REQUEST] != [req.request_id]:
                    with Op("push", head_sha=existing, result="foreign") as op:
                        op.outcome = "refused"
                        op.set(reason=f"the head is not cmapi's for this request: {why}")
                    raise BranchRefused(f"branch {branch} exists at {existing[:8]} and its head is not cmapi's commit for "
                                        f"{req.request_id}: it is not adopted or overwritten")
                head = self._build(req, folder, main)       # this request's own stale attempt: replaced, with a lease on it
                self._push(self.worktree_path(req.cluster_id, req.request_id), branch, head, existing, "replaced")
                return PushResult(head, main, "replaced")
            head = self._build(req, folder, main)
            self._push(self.worktree_path(req.cluster_id, req.request_id), branch, head, "", "created")
            return PushResult(head, main, "created")

    def recreate(self, req: BranchRequest, base: str, expected: str) -> str:
        """The branch again, from its recorded base: the reproducible commit gives the same sha, so a PR that a person closed
        can be opened again on exactly the applied head (Fable 1.3). Raises when the sha differs. A branch whose head is not
        cmapi's for this request is a person's work: BranchRefused, and it is left as it is (the arbitration, row 3)."""
        folder = self._check_files(req)
        branch = request_branch(req.cluster_id, req.request_id)
        with self._lock:
            current = self.fetch_branch(branch)
            if current is not None and current != expected and self.trailers(current)[TRAILER_REQUEST] != [req.request_id]:
                with Op("push", head_sha=current, result="foreign") as op:
                    op.outcome = "refused"
                    op.set(reason="re-create: the head is not cmapi's for this request")
                raise BranchRefused(f"branch {branch} is at {current[:8]}, which is not cmapi's commit for {req.request_id}: "
                                    "it is not overwritten")
            self._need(base)
            head = self._build(req, folder, base)
            if head != expected:
                raise GitUnavailable(f"the re-created commit is {head[:8]}, not the applied head {expected[:8]}")
            if current != head:
                self._push(self.worktree_path(req.cluster_id, req.request_id), branch, head, current or "", "created")
            return head

    def merge_check(self, head: str, folder: str, prev: Mapping[str, str], files: Mapping[str, str | None]) -> MergeCheck:
        """Fable 2.3 with the measured exit rule (OB1, the arbitration's row 10): git merge-tree --write-tree exits 0 on a clean
        merge, and 1 on a conflict, but also 1 on "not something we can merge" (measured on git 2.52.0 and 2.55.0). So a conflict
        is exit 1 with a tree OID as the first field; any other result is an error, raised and retried, never read as clean."""
        expected = {p: t for p, t in files.items() if t is not None}
        with self._lock:
            main = self.fetch_main()
            self._need(head)
            with Op("merge_check", main_sha=main, head_sha=head) as op:
                p = self._m("merge-tree", "--write-tree", "--name-only", "-z", main, head, ok=(0, 1, 2, 128, 129))
                fields = p.stdout.decode(errors="replace").split("\0")
                tree = fields[0].strip()
                op.set(exit_code=p.returncode)
                if p.returncode not in (0, 1) or not _OID.fullmatch(tree):
                    err = redact(p.stderr.decode(errors="replace").strip())[-2000:]
                    op.set(stderr=err)
                    op.outcome = "error"
                    raise GitFailed(f"merge-tree exited {p.returncode} with no tree: {err[-300:]}", p.returncode, err)
                conflicts: tuple[str, ...] = ()
                if p.returncode == 1:
                    names = []
                    for item in fields[1:]:      # -z --name-only: the tree, one NUL-ended name per conflicted file, an empty field
                        if not item:
                            break
                        names.append(item)
                    conflicts = tuple(sorted(set(names)))
                base_ok = self._folder(main, folder) == dict(prev)
                result_ok = not conflicts and self._folder(tree, folder) == expected
                check = MergeCheck(main, head, conflicts, base_ok, result_ok, tree if not conflicts else None)
                op.set(conflict_paths=list(conflicts), base_matches=base_ok, result_matches=result_ok, tree=check.tree,
                       reason=check.reason(self.default_branch))
                if not check.ok:
                    op.outcome = "refused"
                return check

    def delete_branch(self, branch: str, expected: str) -> bool:
        """Conditional delete: git push --force-with-lease=refs/heads/<b>:<expected> origin :refs/heads/<b>. A missing branch is
        success; a branch at another sha is left alone (False). No host's REST delete is conditional (Fable 3.2)."""
        ref = f"refs/heads/{branch}"
        with self._lock:
            current = self.ls_remote(branch).get(branch)
            with Op("branch_delete", head_sha=expected) as op:
                if current is None:
                    op.set(result="absent")
                    return True
                if current != expected:
                    op.outcome = "refused"
                    op.set(result="moved", remote_sha=current)
                    return False
                p = self._m("push", "--porcelain", "--no-verify", f"--force-with-lease={ref}:{expected}", "origin", f":{ref}",
                            ok=(0, 1, 128))
                if p.returncode != 0:
                    err = redact((p.stdout + p.stderr).decode(errors="replace"))[-2000:]
                    op.set(exit_code=p.returncode, stderr=err)
                    if p.returncode == 1 and "stale info" in err:
                        op.outcome = "refused"
                        return False
                    raise GitFailed(f"delete {branch}: {err[-300:]}", p.returncode, err)
                op.set(result="deleted")
                return True

    # ---- cleanup
    def _drop(self, path: Path, branch: str) -> None:
        """This process's worktree and local branch of a request, gone: a retry starts again from the remote."""
        if path.exists():
            self._m("worktree", "remove", "--force", "--force", str(path), ok=(0, 128))
            if path.exists():
                shutil.rmtree(path)
        self._m("worktree", "prune")
        if self._m("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", ok=(0, 1)).returncode == 0:
            self._m("branch", "--quiet", "-D", branch)

    def remove(self, cluster_id: str, request_id: str) -> None:
        """git worktree remove, when the request's PR ends on this pod. The sweeper is what guarantees it on every pod."""
        if not (self.mirror / "HEAD").exists():
            return
        branch = request_branch(cluster_id, request_id)
        with self._lock, Op("worktree", action="remove", scope="request") as op:
            try:
                self._drop(self.worktree_path(cluster_id, request_id), branch)
                self._m("update-ref", "-d", FETCHED + branch[len(BRANCH_PREFIX):], ok=(0, 1))
            except GitFailed as exc:
                self._failed(op, exc)
                raise

    def worktrees(self) -> list[tuple[str, str]]:
        return sorted((c.name, w.name) for c in self.root.iterdir() if c.is_dir() and c.name not in (REPO, ".home")
                      for w in c.iterdir() if w.is_dir())

    def sweep(self, open_requests: Iterable[tuple[str, str]]) -> SweepResult:
        """Fable 5.1, in the worker loop between jobs: the lock without waiting (busy: a Git job runs, skip); remove the worktree,
        local branch and fetched ref of each request that is not open; worktree prune; gc --auto; above 80 % of the sizeLimit,
        everything goes and the repository is fetched again at the next use."""
        result = SweepResult()
        if not self._lock.acquire(blocking=False):
            result.result = "skipped"
            with Op("cleanup", scope="sweeper") as op:
                op.outcome = "skipped"
            SWEEPER_RUNS.labels("skipped").inc()
            return result
        try:
            with Op("cleanup", scope="sweeper") as op:
                op.set(bytes_before=_under(self.root))
                if (self.mirror / "HEAD").exists():
                    keep = set(open_requests)
                    for cluster, rid in self.worktrees():
                        if (cluster, rid) in keep:
                            result.kept.append(f"{cluster}/{rid}")
                            continue
                        self._drop(self.root / cluster / rid, request_branch(cluster, rid))
                        result.removed.append(f"{cluster}/{rid}")
                    for c in [p for p in self.root.iterdir() if p.is_dir() and p.name not in (REPO, ".home")]:
                        if not any(c.iterdir()):
                            c.rmdir()
                    for ref in self._out("for-each-ref", "--format=%(refname)", f"refs/heads/{BRANCH_PREFIX}", FETCHED,
                                         git_dir=True).splitlines():
                        rest = ref[len(FETCHED):] if ref.startswith(FETCHED) else ref[len("refs/heads/" + BRANCH_PREFIX):]
                        cluster, _, rid = rest.partition("/")
                        if (cluster, rid) not in keep and not (self.root / cluster / rid).exists():
                            self._m("update-ref", "-d", ref)
                    self._m("worktree", "prune")
                    self._m("gc", "--auto", "--quiet")
                after = _under(self.root)
                if after > 0.8 * self.size_limit:
                    for cluster, rid in self.worktrees():
                        shutil.rmtree(self.root / cluster / rid, ignore_errors=True)
                    shutil.rmtree(self.mirror, ignore_errors=True)
                    result.result = "recloned"
                    after = _under(self.root)
                op.set(removed=result.removed, kept=len(result.kept), bytes_after=after, result=result.result)
                GIT_WORKDIR_BYTES.set(after)
                GIT_WORKTREES.set(len(self.worktrees()))
            SWEEPER_RUNS.labels(result.result).inc()
            return result
        except Exception:
            SWEEPER_RUNS.labels("error").inc()
            raise
        finally:
            self._lock.release()

    def dispose(self) -> None:
        """Release the workdir; a temporary one (no CMAPI_GIT_WORKDIR) is removed."""
        self._finalizer()


def _release(lockfile, root: str | None) -> None:
    try:
        lockfile.close()
    finally:
        if root:
            shutil.rmtree(root, ignore_errors=True)
