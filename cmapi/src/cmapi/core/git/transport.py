"""How the Git layer reaches a repository (#286): the URL, the credential, and the environment of each git process.

The URL's transport decides the credential, and each comes from its own mount (F2 and F4 of the design review):

    SSH    Secret cmapi-git-bot-ssh (kubernetes.io/ssh-auth), worker only, at CMAPI_GIT_SSH_DIR: ssh-privatekey, an ed25519 key
           with no passphrase, and optionally ssh-publickey, which must match it. known_hosts comes from ConfigMap
           cmapi-git-bot-known-hosts at CMAPI_GIT_KNOWN_HOSTS_DIR, every key type the host publishes. StrictHostKeyChecking=yes:
           an unknown host is refused, and nothing is ever added. The API token is never given to a git process.
    HTTPS  The key token of Secret cmapi-git-bot at CMAPI_GIT_CREDENTIALS_DIR, read by a credential helper that holds only the
           file's path; the username is the key username, else instance.git.username, else x-access-token. This gives the
           host API's token to Git, so it is the interim transport until a host's SSH key exists (CRC, 2026-11-15). Each git process gets an environment built from nothing: no CMAPI_* variable (CMAPI_GIT_TOKEN among them) and no
GIT_* setting of this process reaches it, and the token is in no URL, argv, log or git config file. TLS verification is always
on (http.sslVerify=true, http.sslCAInfo from CMAPI_GIT_CA_BUNDLE or CMAPI_CA_BUNDLE). The record and its sources:
docs/reviews/2026-11-15-issue-286.
"""
from __future__ import annotations

import os
import pwd
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from cmapi.core.giturl import GitConfigError, Remote, Transport, parse_remote  # noqa: F401  (re-exported)

DEFAULT_USERNAME = "x-access-token"
# Red Hat's fix for an arbitrary UID with no passwd entry, short of a writable /etc/passwd (which lets any process in the
# container edit it): nss_wrapper with a private passwd file (access.redhat.com/articles/4859371). The image installs it.
NSS_WRAPPER_LIBS = ("/usr/lib64/libnss_wrapper.so", "/usr/lib/x86_64-linux-gnu/libnss_wrapper.so", "/usr/lib/libnss_wrapper.so")

@dataclass(frozen=True)
class Credentials:
    token_file: Path | None = None
    username: str | None = None
    key_file: Path | None = None
    known_hosts: Path | None = None
    fingerprint: str | None = None                # SHA256:... of the SSH key, logged at start

    def token(self) -> str:
        return self.token_file.read_text().strip() if self.token_file else ""


def _filled(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def load_credentials(directory: Path, remote: Remote, username: str | None = None, *, ssh_dir: Path | None = None,
                     known_hosts_dir: Path | None = None) -> Credentials:
    """The credential the URL's transport needs, from its mount. A missing, encrypted or mismatched one stops cmapi at start."""
    token, user_file = directory / "token", directory / "username"
    key = (ssh_dir or directory) / "ssh-privatekey"
    known_hosts = (known_hosts_dir or directory) / "known_hosts"
    if remote.transport == "https":
        if not _filled(token):
            raise GitConfigError(f"Git over https needs the key token in Secret cmapi-git-bot ({directory})")
        user = user_file.read_text().strip() if _filled(user_file) else (username or DEFAULT_USERNAME)
        if not user or any(c in user for c in "\r\n"):
            raise GitConfigError("the Git username is one line of text")
        return Credentials(token_file=token, username=user)
    if remote.transport == "ssh":
        if not _filled(key):
            raise GitConfigError(f"Git over ssh needs the key ssh-privatekey in Secret cmapi-git-bot-ssh ({key.parent})")
        if not _filled(known_hosts):
            raise GitConfigError(f"Git over ssh needs known_hosts in ConfigMap cmapi-git-bot-known-hosts ({known_hosts.parent}): "
                                 "an unknown host key is refused")
        fingerprint = ssh_key_fingerprint(key, key.parent / "ssh-publickey")
        return Credentials(key_file=key, known_hosts=known_hosts, fingerprint=fingerprint)
    return Credentials()


def ssh_key_fingerprint(key: Path, public: Path) -> str:
    """The key's SHA256 fingerprint. Refused at start: a key that does not parse, one with a passphrase (BatchMode cannot type
    it), one that is not ed25519, and an ssh-publickey that is not this key's."""
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise GitConfigError("Git over ssh needs ssh-keygen (the image installs openssh-clients)")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.devnull, "LANG": "C"}
    derived = subprocess.run([keygen, "-y", "-P", "", "-f", str(key)], capture_output=True, text=True, env=env, check=False, timeout=30)
    if derived.returncode != 0:
        raise GitConfigError("ssh-privatekey does not parse, or has a passphrase: cmapi needs an ed25519 key with none "
                             f"({derived.stderr.strip()[-200:]})")
    blob = derived.stdout.split()
    if not blob or blob[0] != "ssh-ed25519":
        raise GitConfigError(f"ssh-privatekey is {blob[0] if blob else 'unknown'}, not ed25519")
    if _filled(public):
        stored = public.read_text().split()
        if stored[:2] != blob[:2]:
            raise GitConfigError("ssh-publickey is not the public key of ssh-privatekey")
    shown = subprocess.run([keygen, "-l", "-f", "-"], input=" ".join(blob[:2]) + "\n", capture_output=True, text=True, env=env,
                           check=False, timeout=30)
    if shown.returncode != 0:
        raise GitConfigError(f"ssh-keygen -l could not read the key: {shown.stderr.strip()[-200:]}")
    return shown.stdout.split()[1]


def check_path(path: str, *, removal: bool = False) -> None:
    """A repository path the renderer made: relative, no empty, '.', '..' or '.git' part, one line. A removal is a name Git
    listed (#616), which may hold a newline: git rm reads it NUL-separated and literally, so only the line rule is waived."""
    parts = path.split("/")
    if not path or path.startswith("/") or any(p in ("", ".", "..") or p.lower() == ".git" for p in parts) or \
            ("\n" in path and not removal) or "\0" in path:
        raise ValueError(f"{path!r} is not a repository path cmapi writes")


def git_environment(remote: Remote, creds: Credentials, home: Path, ca_bundle: str | None,
                    author: tuple[str, str]) -> dict[str, str]:
    """The whole environment of a git process. Nothing of this process's own environment passes but PATH."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "LANG": "C", "LC_ALL": "C",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": remote.transport,
           "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1], "GIT_COMMITTER_NAME": author[0], "GIT_COMMITTER_EMAIL": author[1]}
    # GIT_ALLOW_PROTOCOL: only the URL's own transport, so no redirect or submodule reaches another one. No hook ever runs.
    config: list[tuple[str, str]] = [("credential.helper", ""), ("core.hooksPath", os.devnull), ("gc.autoDetach", "false"),
                                     ("maintenance.auto", "false"), ("fetch.recurseSubmodules", "false"),
                                     ("advice.detachedHead", "false"), ("init.defaultBranch", "main")]
    if remote.transport == "https":
        config += [("http.sslVerify", "true")]
        if ca_bundle:
            config += [("http.sslCAInfo", ca_bundle)]
        # gitcredentials(7): a helper that starts with ! is a shell snippet. It holds a quoted path and a username, never the
        # token, and lives in the environment: not in argv, not in a file.
        helper = ("!f() { test \"$1\" = get || exit 0; "
                  f"printf 'username=%s\\n' {shlex.quote(creds.username or DEFAULT_USERNAME)}; "
                  f"printf 'password=%s\\n' \"$(cat {shlex.quote(str(creds.token_file))})\"; }}; f")
        config += [("credential.helper", helper)]
    if remote.transport == "ssh":
        env["GIT_SSH_VARIANT"] = "ssh"
        env["GIT_SSH_COMMAND"] = " ".join([
            "ssh", "-F", os.devnull, "-i", shlex.quote(str(creds.key_file)), "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
            "-o", f"UserKnownHostsFile={shlex.quote(str(creds.known_hosts))}", "-o", f"GlobalKnownHostsFile={os.devnull}",
            "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20"])
        env.update(nss_wrapper(home))
    env["GIT_CONFIG_COUNT"] = str(len(config))
    for i, (k, v) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = k, v
    return env


def nss_wrapper(home: Path, uid: int | None = None, gid: int | None = None, libs: tuple[str, ...] = NSS_WRAPPER_LIBS) -> Mapping[str, str]:
    """ssh stops with "No user exists for uid N" when the UID has no passwd entry (measured in the image as UID 1001). CRI-O on
    OpenShift 4.2 and later adds one; elsewhere an arbitrary UID has none. Then ssh, and only ssh's git processes, get
    nss_wrapper with a passwd file of this process's own: /etc/passwd stays read-only."""
    uid = os.getuid() if uid is None else uid
    gid = os.getgid() if gid is None else gid
    try:
        pwd.getpwuid(uid)
        return {}
    except KeyError:
        pass
    lib = next((p for p in libs if Path(p).exists()), None)
    if lib is None:
        raise GitConfigError(f"Git over ssh: UID {uid} has no passwd entry, and libnss_wrapper is not installed (the image installs "
                             "nss_wrapper-libs)")
    home.mkdir(parents=True, exist_ok=True)
    passwd, group = home / "nss-passwd", home / "nss-group"
    passwd.write_text(f"cmapi:x:{uid}:{gid}:cmapi:{home}:/sbin/nologin\n")
    group.write_text(f"cmapi:x:{gid}:\n")
    return {"LD_PRELOAD": lib, "NSS_WRAPPER_PASSWD": str(passwd), "NSS_WRAPPER_GROUP": str(group)}
