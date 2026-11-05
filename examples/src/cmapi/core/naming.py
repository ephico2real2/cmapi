"""Which namespace names may be asked for.

With no team or name-prefix scoping, any caller with namespaces:create may pick a name, so the name
itself is checked:

- a DNS-1123 label: lowercase letters, digits and '-', 2 to 63 characters, starting and ending
  with a letter or digit;
- not reserved: the built-in names below (cannot be removed) and the instance's
  namespaces.reservedPatterns (shell globs);
- at create, not already on the cluster unless cmapi manages it (an existing, unmanaged namespace
  is brought in through adoption, never taken over by a create).
"""
from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Iterable

from cmapi.core.errors import Problem

BUILT_IN_RESERVED = ("default", "openshift", "openshift-*", "kube-*", "cmapi-system", "cmapi-imports")
_DNS1123_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


def reserved(name: str, patterns: Iterable[str] = ()) -> str | None:
    """The pattern that reserves name, or None."""
    return next((p for p in (*BUILT_IN_RESERVED, *patterns) if fnmatchcase(name, p)), None)


def check_name(name: str, patterns: Iterable[str] = ()) -> None:
    if not isinstance(name, str) or len(name) < 2 or not _DNS1123_LABEL.fullmatch(name):
        raise Problem.unprocessable("invalid-namespace-name",
                                    f"{name!r} is not a DNS-1123 label of 2 to 63 characters")
    hit = reserved(name, patterns)
    if hit:
        raise Problem.unprocessable("reserved-namespace", f"{name} is reserved ({hit})", pattern=hit)


def check_not_unmanaged(name: str, on_cluster: dict | None) -> None:
    """At create: refuse a name that exists on the cluster and is not cmapi-managed."""
    if on_cluster is None:
        return
    labels = (on_cluster.get("metadata") or {}).get("labels") or {}
    if labels.get("cmapi.net/managed") != "true":
        raise Problem.conflict("namespace-exists-unmanaged",
                               f"{name} already exists on the cluster and cmapi does not manage it; "
                               f"ask for adoption instead")
