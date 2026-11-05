"""Who is calling, from a token core/auth.py has already verified.

The requester's identity is never taken from a request body: username and email go on the
Namespace (cmapi.net/requested-by-user, cmapi.net/requested-by); names and employee ID stay in the
database with the request. Claims come from the cmapi-identity client scope (employee_id,
middle_name) and the standard OIDC claims.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

_LABEL_VALUE = re.compile(r"^[a-z0-9]([-a-z0-9_.]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class Identity:
    sub: str
    username: str                      # preferred_username, or the client ID for a service account
    kind: Literal["user", "service"]
    client_id: str                     # azp: cmapi-portal, cmapi-cli, svc-...
    email: str | None = None
    given_name: str | None = None
    middle_name: str | None = None
    family_name: str | None = None
    employee_id: str | None = None
    roles: frozenset[str] = frozenset()
    groups: frozenset[str] = frozenset()

    @property
    def label_value(self) -> str:
        """cmapi.net/requested-by-user: the username, lower-cased; refused if it cannot be a label."""
        v = self.username.lower()
        if not _LABEL_VALUE.fullmatch(v):
            raise ValueError(f"username {self.username!r} cannot be a label value")
        return v

    def record(self) -> dict[str, Any]:
        """What change_requests stores about the requester (database only, never Git)."""
        return {"sub": self.sub, "username": self.username, "email": self.email,
                "givenName": self.given_name, "middleName": self.middle_name,
                "familyName": self.family_name, "employeeId": self.employee_id,
                "kind": self.kind, "clientId": self.client_id}

    @classmethod
    def from_claims(cls, claims: Mapping[str, Any], audience: str) -> "Identity":
        username = claims.get("preferred_username", claims["sub"])
        service = username.startswith("service-account-")
        roles = claims.get("resource_access", {}).get(audience, {}).get("roles", [])
        return cls(
            sub=claims["sub"],
            username=username.removeprefix("service-account-"),
            kind="service" if service else "user",
            client_id=claims.get("azp", ""),
            email=claims.get("email"),
            given_name=claims.get("given_name"),
            middle_name=claims.get("middle_name"),
            family_name=claims.get("family_name"),
            employee_id=claims.get("employee_id"),
            roles=frozenset(roles),
            groups=frozenset(claims.get("groups", [])),
        )


@dataclass(frozen=True)
class Person:
    """A directory entry: a user cmapi looked up rather than one holding the token."""
    username: str
    email: str | None
    enabled: bool = True
    sub: str | None = None             # Keycloak user ID: the same value as the person's token sub
    given_name: str | None = None
    middle_name: str | None = None
    family_name: str | None = None
    employee_id: str | None = None
    groups: frozenset[str] = field(default_factory=frozenset)

    def record(self) -> dict[str, Any]:
        return {"sub": self.sub, "username": self.username, "email": self.email, "givenName": self.given_name,
                "middleName": self.middle_name, "familyName": self.family_name,
                "employeeId": self.employee_id, "kind": "user"}

    def public(self, include_employee_id: bool) -> dict[str, Any]:
        """GET /api/v1/directory/users: employee ID only for cmapi-operator and above."""
        out = {"username": self.username, "email": self.email,
               "name": " ".join(x for x in (self.given_name, self.middle_name, self.family_name) if x)}
        if include_employee_id:
            out["employeeId"] = self.employee_id
        return out
