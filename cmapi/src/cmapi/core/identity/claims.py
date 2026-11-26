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

from cmapi.core.errors import Problem

# The name of cmapi's own expire_check, the requester of the delete it opens after an expiry's grace (core/pipeline.py). No
# token and no directory entry may carry it: a request's requester may cancel it by username (routers/requests.py), and the
# audit trail names the actor by username, so a person or client of that name would act as the worker and be recorded as it.
EXPIRY_NAME = "cmapi-expire-check"

_LABEL_VALUE = re.compile(r"^[a-z0-9]([-a-z0-9_.]{0,61}[a-z0-9])?$")


def label_value_of(username: str) -> str:
    """cmapi.net/requested-by-user: the username, lower-cased; refused if it cannot be a label."""
    v = username.lower()
    if not _LABEL_VALUE.fullmatch(v):
        raise ValueError(f"username {username!r} cannot be a label value")
    return v


def is_reserved(sub: str | None, username: str | None) -> bool:
    """True for the subject or the username of cmapi's own worker identity, in any case (Keycloak lower-cases usernames)."""
    return sub == EXPIRY_NAME or (username or "").casefold() == EXPIRY_NAME


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
        return label_value_of(self.username)

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
        if is_reserved(claims["sub"], username.removeprefix("service-account-")):
            raise Problem(401, "unauthenticated", f"The identity {EXPIRY_NAME} is cmapi's own and no token may carry it")
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
        """GET /api/v1/directory/users: employee ID only for an operator (namespaces:protect)."""
        out = {"username": self.username, "email": self.email,
               "name": " ".join(x for x in (self.given_name, self.middle_name, self.family_name) if x)}
        if include_employee_id:
            out["employeeId"] = self.employee_id
        return out
