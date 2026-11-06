"""Who may call what: Keycloak roles to permissions (config/authz-roles.yaml).

Roles come from the token: the client roles on this instance's client (cmapi-nonprod, cmapi-staging,
cmapi-prod). Keycloak decides who holds them, directly, through a group the role is assigned to,
or on a service-account client (a bot). cmapi maps each role to the permissions (scopes) it grants
and, optionally, to the environments it may act in.

There is no team or namespace-name scoping. Anyone holding a role with namespaces:create may ask for
any namespace name (outside the reserved ones) in the environments that role covers; approval rules decide what needs approval,
and approving groups (Keycloak groups) decide who may approve.
"""
from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Any, Iterable, Mapping

from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity

_VIEW = {"clusters:read", "objects:read", "capacity:read", "requests:read"}
# namespaces:create is asking for a new namespace; namespaces:write is changing or deleting one.
_ONBOARD = _VIEW | {"namespaces:create", "requests:cancel"}
_REQUEST = _ONBOARD | {"namespaces:write", "quotas:write", "serviceaccounts:write", "grants:write"}
_OPERATE = _REQUEST | {"requests:retry", "adoption:write", "reports:read", "operations:run"}

# The built-in roles: used when authz-roles.yaml does not define a role, and the vocabulary of
# permissions a config file may use.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "cmapi-viewer": frozenset(_VIEW),
    # Create namespaces and follow their requests, nothing else: for onboarding by people or by a
    # local automation account (bot-user, an AI agent). Cannot change or delete a namespace.
    "cmapi-onboarding": frozenset(_ONBOARD),
    "cmapi-requester": frozenset(_REQUEST),
    "cmapi-approver": frozenset(_VIEW | {"requests:approve", "requests:reject"}),
    "cmapi-operator": frozenset(_OPERATE),
    "cmapi-admin": frozenset(_OPERATE | {"config:write", "clusters:onboard", "admin:reload",
                                         "approvals:pause"}),
    "cmapi-auditor": frozenset(_VIEW | {"events:read", "audit:export"}),
    "cmapi-approval-relay": frozenset({"requests:read", "approvals:relay"}),
}
PERMISSIONS: frozenset[str] = frozenset().union(*ROLE_PERMISSIONS.values())

# Approving groups in approval-rules.yaml are short names (approver-platform); the token carries
# Keycloak group paths. instance.yaml's identity.groupPath joins them, since a site with its own
# directory has its own names (docs/11). This is the path when an instance does not set one.
DEFAULT_GROUP_PATH = "/cmapi/app-cmapi-rbac-{name}"


def check_group_path(template: Any) -> None:
    """A Keycloak full path with one plain {name}. Checked at startup: at the first approval, str.format would raise inside a request."""
    if not isinstance(template, str) or not template.startswith("/"):
        raise ValueError(f"{template!r} is not a Keycloak group path: it starts with /")
    fields = [(field, spec, conversion) for _, field, spec, conversion in Formatter().parse(template) if field is not None]
    if fields != [("name", "", None)]:
        raise ValueError(f"{template!r} must hold {{name}} once, and no other field")


def group_path(name: str, template: str = DEFAULT_GROUP_PATH) -> str:
    return template.format(name=name)


@dataclass(frozen=True)
class RoleGrant:
    role: str
    permissions: frozenset[str]
    environments: frozenset[str] | None = None        # None: every environment the instance serves

    def covers(self, env: str | None) -> bool:
        return env is None or self.environments is None or env in self.environments


class RolePolicy:
    """Keycloak role -> permissions and environments, for one instance.

    authz-roles.yaml:
        roles:
          cmapi-requester: {}                                  # built-in permissions, every environment
          cmapi-bot-rnd:                                       # a role you create in Keycloak
            inherits: [cmapi-requester]
            environments: [rnd]
          cmapi-quota-editor:
            permissions: [objects:read, quotas:write]
    Built-in roles not named in the file keep their built-in permissions.
    """

    def __init__(self, raw: Mapping[str, Any] | None = None, served: Iterable[str] | None = None):
        self.served = set(served) if served is not None else None
        roles = dict((raw or {}).get("roles") or {})
        problems: list[str] = []
        self.grants: dict[str, RoleGrant] = {}
        resolving: set[str] = set()

        def resolve(name: str) -> RoleGrant:
            if name in self.grants:
                return self.grants[name]
            if name in resolving:
                raise ValueError(f"role {name}: inherits itself")
            spec = roles.get(name)
            if spec is None:
                if name not in ROLE_PERMISSIONS:
                    raise ValueError(f"unknown role {name}")
                g = RoleGrant(name, ROLE_PERMISSIONS[name])
                self.grants[name] = g
                return g
            resolving.add(name)
            perms = set(spec.get("permissions") or [])
            if "permissions" not in spec and not spec.get("inherits") and name in ROLE_PERMISSIONS:
                perms |= ROLE_PERMISSIONS[name]
            for parent in spec.get("inherits") or []:
                perms |= resolve(parent).permissions
            unknown = perms - PERMISSIONS
            if unknown:
                problems.append(f"role {name}: unknown permissions {sorted(unknown)}")
            envs = spec.get("environments")
            if envs is not None:
                envs = frozenset(envs)
                if self.served is not None and envs - self.served:
                    problems.append(f"role {name}: environments {sorted(envs - self.served)} "
                                    f"are not served by this instance")
            resolving.discard(name)
            g = RoleGrant(name, frozenset(perms), envs)
            self.grants[name] = g
            return g

        for name in [*ROLE_PERMISSIONS, *roles]:
            try:
                resolve(name)
            except ValueError as exc:
                problems.append(str(exc))
        if problems:
            raise ValueError("; ".join(sorted(set(problems))))

    # ---- questions
    def held(self, who: Identity) -> list[RoleGrant]:
        return [self.grants[r] for r in sorted(who.roles) if r in self.grants]

    def permissions(self, who: Identity, env: str | None = None) -> frozenset[str]:
        return frozenset().union(*(g.permissions for g in self.held(who) if g.covers(env)))

    def allowed(self, who: Identity, permission: str, env: str | None = None) -> bool:
        return permission in self.permissions(who, env)

    def environments(self, who: Identity, permission: str) -> set[str] | None:
        """Where the caller holds the permission; None means every served environment."""
        envs: set[str] = set()
        for g in self.held(who):
            if permission in g.permissions:
                if g.environments is None:
                    return None if self.served is None else set(self.served)
                envs |= g.environments
        return envs

    def require(self, who: Identity, permission: str, env: str | None = None) -> None:
        if self.allowed(who, permission, env):
            return
        if env is not None and self.allowed(who, permission):
            raise Problem.forbidden(f"Your roles grant {permission} only in "
                                    f"{sorted(self.environments(who, permission) or [])}, not {env}",
                                    code="environment-forbidden")
        raise Problem.forbidden(f"Missing permission {permission}: no role in your token grants it "
                                f"(roles: {sorted(who.roles) or 'none'})")

    def describe(self, who: Identity) -> dict[str, Any]:
        """For GET /me: what the caller's roles let it do, and where."""
        return {"roles": [{"role": g.role, "permissions": sorted(g.permissions),
                           "environments": sorted(g.environments) if g.environments is not None else "all"}
                          for g in self.held(who)],
                "permissions": sorted(self.permissions(who))}


_DEFAULT = RolePolicy()


def permissions(who: Identity) -> frozenset[str]:
    """Built-in role permissions, every environment (for code that has no instance config)."""
    return _DEFAULT.permissions(who)


def require(who: Identity, permission: str) -> None:
    _DEFAULT.require(who, permission)
