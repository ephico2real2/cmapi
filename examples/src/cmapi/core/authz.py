"""Roles to permissions, and scope bindings (config/authz-scopes.yaml).

Same rules as the v2 design's core/authz.py, without the FastAPI wiring: roles come from the token,
scopes come from Git, and one binding must pair a held role, the permission and the target.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Iterable

from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity

_VIEW = {"clusters:read", "objects:read", "capacity:read", "requests:read"}
_REQUEST = _VIEW | {"namespaces:write", "quotas:write", "serviceaccounts:write", "grants:write",
                    "requests:cancel"}
_OPERATE = _REQUEST | {"requests:retry", "adoption:write", "reports:read", "operations:run"}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "cmapi-viewer": frozenset(_VIEW),
    "cmapi-requester": frozenset(_REQUEST),
    "cmapi-approver": frozenset(_VIEW | {"requests:approve", "requests:reject"}),
    "cmapi-operator": frozenset(_OPERATE),
    "cmapi-admin": frozenset(_OPERATE | {"config:write", "clusters:onboard", "admin:reload",
                                         "approvals:pause"}),
    "cmapi-auditor": frozenset(_VIEW | {"events:read", "audit:export"}),
    "cmapi-approval-relay": frozenset({"requests:read", "approvals:relay"}),
}

# Approving groups in approval-rules.yaml are short names (prod-approvers); the token carries
# Keycloak group paths. One convention joins them, set per instance.
GROUP_PATH = "/cmapi/cmapi-{name}"


def group_path(name: str) -> str:
    return GROUP_PATH.format(name=name)


@dataclass(frozen=True)
class Binding:
    role: str
    clusters: tuple[str, ...]
    environments: tuple[str, ...]
    namespaces: tuple[str, ...]
    group: str | None = None
    client: str | None = None
    team: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Binding":
        return cls(role=d["role"], clusters=tuple(d["clusters"]), environments=tuple(d["environments"]),
                   namespaces=tuple(d["namespaces"]), group=d.get("group"), client=d.get("client"),
                   team=d.get("team"))

    def applies_to(self, who: Identity) -> bool:
        if self.role not in who.roles:
            return False
        return (self.group is not None and self.group in who.groups) or \
               (who.kind == "service" and self.client is not None and self.client == who.client_id)

    def covers(self, cluster_id: str, env: str, namespace: str | None) -> bool:
        def hit(value: str, patterns: Iterable[str]) -> bool:
            return any(fnmatchcase(value, p) for p in patterns)
        ns_ok = "*" in self.namespaces if namespace is None else hit(namespace, self.namespaces)
        return hit(cluster_id, self.clusters) and hit(env, self.environments) and ns_ok


def permissions(who: Identity) -> frozenset[str]:
    return frozenset().union(*(ROLE_PERMISSIONS.get(r, frozenset()) for r in who.roles))


def require(who: Identity, permission: str) -> None:
    if permission not in permissions(who):
        raise Problem.forbidden(f"Missing permission {permission}")


def allowed(who: Identity, permission: str, bindings: Iterable[Binding],
            cluster_id: str, env: str, namespace: str | None) -> bool:
    return any(b.applies_to(who) and permission in ROLE_PERMISSIONS.get(b.role, frozenset())
               and b.covers(cluster_id, env, namespace) for b in bindings)


def authorize_target(who: Identity, permission: str, bindings: Iterable[Binding],
                     cluster_id: str, env: str, namespace: str | None) -> None:
    if not allowed(who, permission, bindings, cluster_id, env, namespace):
        raise Problem.forbidden(f"No scope binding covers {cluster_id}/{env}/{namespace or '*'}",
                                code="cluster-scope-forbidden")


def teams_for(who: Identity, bindings: Iterable[Binding]) -> set[str]:
    """The cmapi.net/team values this caller may set (mustMatchBinding in metadata-keys.yaml)."""
    return {b.team for b in bindings if b.team and b.applies_to(who)}
