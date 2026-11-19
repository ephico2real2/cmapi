"""Real Git servers for the Git layer's tests (#286): bare repositories, a TLS server in front of `git http-backend`
that needs Basic auth, and a throwaway non-root sshd with a pinned host key. Nothing here is a fake of Git: each test talks to
the same git and ssh binaries the image ships, over file://, https:// and ssh://."""
from __future__ import annotations

import base64
import getpass
import datetime
import ipaddress
import os
import shutil
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator, Mapping

import ssl

GIT = shutil.which("git") or "git"
SSHD = next((p for p in ("/usr/sbin/sshd", "/usr/local/sbin/sshd", shutil.which("sshd") or "") if p and os.path.exists(p)), None)


def _env(home: Path) -> dict[str, str]:
    """A person's git, isolated from this machine's configuration."""
    return {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "A Person", "GIT_AUTHOR_EMAIL": "person@example.test",
            "GIT_COMMITTER_NAME": "A Person", "GIT_COMMITTER_EMAIL": "person@example.test", "LANG": "C"}


def git(*args: str, cwd: Path, home: Path, input: bytes | None = None) -> str:
    p = subprocess.run([GIT, *args], cwd=cwd, env=_env(home), input=input, capture_output=True, check=False)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr.decode()}"
    return p.stdout.decode().strip()


def bare_repo(root: Path, files: Mapping[str, str] | None = None) -> Path:
    """A bare repository with one commit on main, as a cluster-configs repository starts."""
    bare = root / "cluster-configs.git"
    git("init", "--quiet", "--bare", "-b", "main", str(bare), cwd=root, home=root)
    # As GitHub, GitLab and Bitbucket serve a partial clone: the Git layer's mirror is --filter=blob:none.
    git("--git-dir", str(bare), "config", "uploadpack.allowFilter", "true", cwd=root, home=root)
    git("--git-dir", str(bare), "config", "uploadpack.allowAnySHA1InWant", "true", cwd=root, home=root)
    person_commit(bare, {"README.md": "cluster-configs (test)\n", **(files or {})}, "seed", root)
    return bare


def person_commit(bare: Path, files: Mapping[str, str | None], message: str, scratch: Path) -> str:
    """A person's own commit on main, pushed with the git CLI: what moves the branch under the bot."""
    work = scratch / f"person-{time.monotonic_ns()}"
    git("init", "--quiet", "-b", "main", str(work), cwd=scratch, home=scratch)
    has_main = subprocess.run([GIT, "--git-dir", str(bare), "rev-parse", "--verify", "-q", "refs/heads/main"], capture_output=True,
                              env=_env(scratch)).returncode == 0
    if has_main:
        git("fetch", "--quiet", str(bare), "main", cwd=work, home=scratch)
        git("reset", "--quiet", "--hard", "FETCH_HEAD", cwd=work, home=scratch)
    for path, text in files.items():
        target = work / path
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
    git("add", "--all", cwd=work, home=scratch)
    git("commit", "--quiet", "-m", message, cwd=work, home=scratch)
    git("push", "--quiet", str(bare), "HEAD:refs/heads/main", cwd=work, home=scratch)
    head = git("rev-parse", "HEAD", cwd=work, home=scratch)
    shutil.rmtree(work)
    return head


def main_log(bare: Path) -> list[str]:
    """The subjects on main, newest first."""
    return git("--git-dir", str(bare), "log", "--format=%s", "main", cwd=bare, home=bare.parent).splitlines()


def main_message(bare: Path, rev: str = "main") -> str:
    return git("--git-dir", str(bare), "log", "-1", "--format=%B", rev, cwd=bare, home=bare.parent)


def main_files(bare: Path, folder: str) -> dict[str, str]:
    names = git("--git-dir", str(bare), "ls-tree", "--name-only", "main", f"{folder}/", cwd=bare, home=bare.parent).splitlines()
    return {n: git("--git-dir", str(bare), "show", f"main:{n}", cwd=bare, home=bare.parent) + "\n" for n in names}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------- HTTPS: git http-backend behind TLS and Basic auth

def make_ca_and_server_cert(root: Path, name: str) -> tuple[Path, Path, Path]:
    """A CA, and a certificate for 127.0.0.1 it signs: (ca.pem, server.pem, server.key)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{name} test CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
          .not_valid_after(now + datetime.timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                       key_encipherment=False, data_encipherment=False, key_agreement=False, encipher_only=False,
                                       decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    ca_pem, cert_pem, key_pem = root / f"{name}-ca.pem", root / f"{name}-server.pem", root / f"{name}-server.key"
    ca_pem.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return ca_pem, cert_pem, key_pem


class GitHttps:
    """https://127.0.0.1:<port>/<repo>.git, served by git http-backend, Basic auth required. Records what it was sent."""

    def __init__(self, root: Path, username: str, token: str):
        self.root, self.username, self.token = root, username, token
        self.ca, cert, key = make_ca_and_server_cert(root, "githttps")
        self.authorized = 0
        self.refused = 0
        backend = Path(subprocess.run([GIT, "--exec-path"], capture_output=True, text=True, check=True).stdout.strip()) / "git-http-backend"
        server = self
        want = "Basic " + base64.b64encode(f"{username}:{token}".encode()).decode()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):              # quiet: the request line carries no secret, but the test output stays short
                pass

            def _body(self) -> bytes:
                if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                    out = b""
                    while True:
                        size = int(self.rfile.readline().strip().split(b";")[0], 16)
                        if size == 0:
                            self.rfile.readline()
                            return out
                        out += self.rfile.read(size)
                        self.rfile.readline()
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _serve(self):
                body = self._body()
                if self.headers.get("Authorization") != want:
                    server.refused += 1
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="git"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                server.authorized += 1
                path, _, query = self.path.partition("?")
                env = {"PATH": os.environ.get("PATH", ""), "GIT_PROJECT_ROOT": str(server.root), "GIT_HTTP_EXPORT_ALL": "1",
                       "PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": self.command, "REMOTE_USER": username,
                       "REMOTE_ADDR": "127.0.0.1", "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                       "CONTENT_LENGTH": str(len(body)), "HOME": str(server.root), "GIT_CONFIG_GLOBAL": os.devnull,
                       "GIT_CONFIG_NOSYSTEM": "1"}
                if self.headers.get("Content-Encoding"):
                    env["HTTP_CONTENT_ENCODING"] = self.headers["Content-Encoding"]
                if self.headers.get("Git-Protocol"):
                    env["GIT_PROTOCOL"] = self.headers["Git-Protocol"]
                out = subprocess.run([str(backend)], input=body, env=env, capture_output=True, check=False).stdout
                head, _, payload = out.partition(b"\r\n\r\n")
                if not _:
                    head, _, payload = out.partition(b"\n\n")
                status, headers = 200, []
                for line in head.decode().splitlines():
                    k, _, v = line.partition(":")
                    if k.lower() == "status":
                        status = int(v.strip().split()[0])
                    elif k:
                        headers.append((k, v.strip()))
                self.send_response(status)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = _serve

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def url(self, repo: str = "cluster-configs.git") -> str:
        return f"https://127.0.0.1:{self.port}/{repo}"

    def __enter__(self) -> "GitHttps":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# --------------------------------------------------------------------------- SSH: a throwaway sshd as this user

@contextmanager
def sshd(root: Path) -> Iterator[dict[str, object]]:
    """A non-root sshd on 127.0.0.1 that knows one client key. Yields its port, the client key, a known_hosts line that pins
    its host key, and the URL base. The caller's pytest skips when no sshd binary exists."""
    assert SSHD, "no sshd"
    d = root / "sshd"
    d.mkdir()
    for name in ("host", "client"):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(d / name)], check=True)
    (d / "authorized_keys").write_text((d / "client.pub").read_text())
    os.chmod(d / "authorized_keys", 0o600)
    os.chmod(d / "client", 0o600)
    port = free_port()
    (d / "sshd_config").write_text(
        f"Port {port}\nListenAddress 127.0.0.1\nHostKey {d / 'host'}\nAuthorizedKeysFile {d / 'authorized_keys'}\n"
        "PasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\nStrictModes no\n"
        f"PidFile {d / 'sshd.pid'}\nSetEnv PATH={os.path.dirname(GIT)}:/usr/bin:/bin\n")
    proc = subprocess.Popen([SSHD, "-D", "-e", "-f", str(d / "sshd_config")], stdout=subprocess.DEVNULL, stderr=open(d / "sshd.log", "w"))
    try:
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"sshd did not listen on {port}: {(d / 'sshd.log').read_text()[-500:]}")
        assert proc.poll() is None, f"sshd exited {proc.returncode}: {(d / 'sshd.log').read_text()[-500:]}"
        host_key = " ".join((d / "host.pub").read_text().split()[:2])
        yield {"port": port, "key": d / "client", "known_hosts": f"[127.0.0.1]:{port} {host_key}\n",
               "url": f"ssh://{getpass.getuser()}@127.0.0.1:{port}", "log": d / "sshd.log"}
    finally:
        proc.terminate()
        proc.wait(5)


# --------------------------------------------------------------------------- a stub of GitHub's PR API over a real bare repository

class StubGitHub:
    """GitHub's REST paths that core/git/github.py calls for the PR, served over a real bare repository: a merge is a real merge
    commit on main, made with git merge-tree and refused on a conflict, as GitHub refuses an unmergeable PR (405). Shaped by
    GitHub's REST docs (2026-11). Records each request, and refuses any path the adapter must not call (the Checks API above all)."""

    def __init__(self, bare: Path, repository: str = "cmapi/cluster-configs-test"):
        import itertools

        self.bare, self.repo = bare, f"/repos/{repository}"
        self.owner = repository.split("/")[0]
        self.prs: dict[int, dict] = {}
        self.statuses: dict[str, dict[str, str]] = {}
        self.comments: list[tuple[int, str]] = []
        self.requests: list[tuple[str, str]] = []
        self.merge_hook = None
        # A named call fails: "once", "always", or "after" (it does the work, then answers 502). Keys: pr_open, merge, pr_state.
        self.fail: dict[str, str] = {}
        self.opened = 0
        self.merges: list[str] = []
        self._numbers = itertools.count(1)

    def _git(self, *args: str, ok=(0,)) -> subprocess.CompletedProcess:
        p = subprocess.run([GIT, "--git-dir", str(self.bare), *args], capture_output=True, env=_env(self.bare.parent), check=False)
        assert p.returncode in ok, f"git {args}: {p.stderr.decode()}"
        return p

    def head(self, branch: str) -> str | None:
        p = self._git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", ok=(0, 1))
        return p.stdout.decode().strip() or None

    def _pr(self, n: int) -> dict:
        p = self.prs[n]
        head = self.head(p["ref"]) or p["sha"]
        return {"number": n, "html_url": f"https://github.test/{self.repo[7:]}/pull/{n}", "state": p["state"], "merged": p["merged"],
                "merge_commit_sha": p.get("merge_sha"), "head": {"ref": p["ref"], "sha": head}, "base": {"ref": "main"}}

    def _failing(self, name: str):
        import httpx

        mode = self.fail.get(name)
        if mode == "once":
            del self.fail[name]
        if mode in ("once", "always"):
            return httpx.Response(502, json={"message": f"stub: {name} fails"})
        return None

    def __call__(self, request):
        import json as _json
        import re as _re
        from urllib.parse import unquote

        import httpx

        path = unquote(request.url.path)
        self.requests.append((request.method, path))
        assert path.startswith(self.repo), path
        path = path[len(self.repo):]
        body = _json.loads(request.content) if request.content else {}
        if "check-runs" in path or "check-suites" in path:
            raise AssertionError("the adapter must never call the Checks API (BUG-69)")
        if path == "/pulls" and request.method == "GET":
            want = request.url.params.get("head")
            return httpx.Response(200, json=[self._pr(n) for n, p in self.prs.items()
                                             if p["state"] == "open" and (want is None or f"{self.owner}:{p['ref']}" == want)])
        if path == "/pulls" and request.method == "POST":
            if (failed := self._failing("pr_open")) is not None:
                return failed
            if self.head(body["head"]) is None:
                return httpx.Response(422, json={"message": "Validation Failed", "errors": [{"field": "head", "code": "invalid"}]})
            if any(p["state"] == "open" and p["ref"] == body["head"] for p in self.prs.values()):
                return httpx.Response(422, json={"message": "A pull request already exists"})
            n = next(self._numbers)
            self.opened += 1
            self.prs[n] = {"ref": body["head"], "state": "open", "merged": False, "sha": self.head(body["head"]), "title": body["title"]}
            if self.fail.get("pr_open") == "after":
                del self.fail["pr_open"]
                return httpx.Response(502, json={"message": "stub: opened, then failed"})
            return httpx.Response(201, json=self._pr(n))
        m = _re.fullmatch(r"/pulls/(\d+)", path)
        if m and request.method == "GET":
            return httpx.Response(200, json=self._pr(int(m[1])))
        if m and request.method == "PATCH":
            self.prs[int(m[1])]["state"] = body.get("state", "open")
            return httpx.Response(200, json=self._pr(int(m[1])))
        m = _re.fullmatch(r"/pulls/(\d+)/merge", path)
        if m and request.method == "PUT":
            if (failed := self._failing("merge")) is not None:
                return failed
            n = int(m[1])
            pr = self.prs[n]
            head = self.head(pr["ref"])
            if body.get("sha") != head:
                return httpx.Response(409, json={"message": "Head branch was modified. Review and try the merge again."})
            if self.merge_hook:
                self.merge_hook(n)
            main = self.head("main")
            mt = self._git("merge-tree", "--write-tree", main, head, ok=(0, 1))
            if mt.returncode == 1:
                return httpx.Response(405, json={"message": "Pull Request is not mergeable"})
            tree = mt.stdout.decode().split()[0]
            commit = subprocess.run([GIT, "--git-dir", str(self.bare), "commit-tree", tree, "-p", main, "-p", head, "-m",
                                     body.get("commit_title") or f"Merge {pr['ref']}"], capture_output=True, check=True,
                                    env=_env(self.bare.parent)).stdout.decode().strip()
            self._git("update-ref", "refs/heads/main", commit, main)
            pr.update(state="closed", merged=True, merge_sha=commit)
            self.merges.append(commit)
            if self.fail.get("merge") == "after":
                del self.fail["merge"]
                return httpx.Response(502, json={"message": "stub: merged, then failed"})
            return httpx.Response(200, json={"sha": commit, "merged": True, "message": "Pull Request successfully merged"})
        if path.startswith("/git/refs/heads/") and request.method == "DELETE":
            branch = path[len("/git/refs/heads/"):]
            if self.head(branch) is None:
                return httpx.Response(422, json={"message": "Reference does not exist"})
            self._git("update-ref", "-d", f"refs/heads/{branch}")
            return httpx.Response(204)
        m = _re.fullmatch(r"/issues/(\d+)/comments", path)
        if m and request.method == "GET":          # one page: the adapter reads before it comments (#451)
            return httpx.Response(200, json=[{"body": text} for n, text in self.comments if n == int(m[1])])
        if m and request.method == "POST":
            self.comments.append((int(m[1]), body["body"]))
            return httpx.Response(201, json={"id": len(self.comments)})
        m = _re.fullmatch(r"/statuses/(\w+)", path)
        if m and request.method == "POST":
            self.statuses.setdefault(m[1], {})[body["context"]] = body["state"]
            return httpx.Response(201, json={})
        m = _re.fullmatch(r"/commits/(\w+)/status", path)
        if m and request.method == "GET":
            sts = [{"context": c, "state": st} for c, st in self.statuses.get(m[1], {}).items()]
            return httpx.Response(200, json={"state": "success", "statuses": sts, "total_count": len(sts)})
        raise AssertionError(f"{request.method} {path} is not a call the GitHub adapter makes")
