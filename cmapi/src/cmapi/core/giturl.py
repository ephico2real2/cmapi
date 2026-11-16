"""The Git layer's repository URL (#286), with no dependency: core/config.py checks instance.git.url at start through it, and
the reference code's tests import core/config.py with neither httpx nor structlog installed. core/git/transport.py re-exports it."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

_SCP = re.compile(r"^(?:[A-Za-z0-9._-]+@)?(?P<host>[A-Za-z0-9.-]+):(?P<path>[^/\\].*)$")     # user@host:path, Git's scp form

Transport = Literal["https", "ssh", "file"]


class GitConfigError(ValueError):
    """instance.git, or the bot's Secret or known hosts, cannot work: cmapi does not start."""


@dataclass(frozen=True)
class Remote:
    url: str
    transport: Transport


def parse_remote(url: str | None) -> Remote:
    """The repository URL, refused when it could not be used safely: no TLS, no authentication, or a password in it."""
    if not url:
        raise GitConfigError("the repository's clone URL is needed: instance.git.url, https://, ssh:// or user@host:path")
    if any(c.isspace() for c in url):
        raise GitConfigError("instance.git.url has white space")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme in ("http", "git"):
        raise GitConfigError(f"instance.git.url: {scheme}:// is refused, because it has no TLS; use https:// or ssh://")
    if scheme == "https":
        if parts.username is not None or parts.password is not None:
            raise GitConfigError("instance.git.url: no user or token in an https URL; the token is the key token of Secret cmapi-git-bot, "
                                 "and the username is instance.git.username")
        if not parts.hostname:
            raise GitConfigError("instance.git.url: an https URL needs a host")
        return Remote(url, "https")
    if scheme == "ssh":
        if parts.password is not None or not parts.hostname:
            raise GitConfigError("instance.git.url: an ssh URL is ssh://user@host[:port]/path, with no password")
        return Remote(url, "ssh")
    if scheme == "file":
        return Remote(url, "file")
    if not scheme and _SCP.match(url):
        return Remote(url, "ssh")
    raise GitConfigError(f"instance.git.url: {url!r} is not an https://, ssh://, user@host:path or file:// URL")


