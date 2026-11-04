"""Request-time identity checks: who the request is for, and the email-domain rule.

- A person calling with their own token is the requester; sending onBehalfOf is refused.
- A service client (svc-..., the ServiceNow relay) must send onBehalfOf: a username or an employee
  ID, resolved through the directory to an enabled person. Both identities are recorded.
- A user token without the employee_id claim is refused (identity-incomplete) when the instance
  requires it (identity.requireEmployeeId).
- Email-valued governed keys (cmapi.net/team-dl) must be an address in one of emailDomains from
  metadata-keys.yaml. Format only: DLs are never looked up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity, Person
from cmapi.core.identity.directory import CachedDirectory, DirectoryProvider

_LOCAL = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$")


def email_in_domains(value: str, domains: Iterable[str]) -> bool:
    if value.count("@") != 1:
        return False
    local, domain = value.split("@")
    return bool(local) and bool(_LOCAL.fullmatch(local)) and \
        domain.lower() in {d.lower() for d in domains}


@dataclass(frozen=True)
class Requester:
    """Who the request is for (person) and who sent it (caller, when a service did)."""
    person: Identity | Person
    caller: Identity

    @property
    def username(self) -> str:
        return self.person.username

    @property
    def sub(self) -> str:
        """The person's Keycloak user ID: the requester_sub the approval ledger refuses as approver."""
        if not self.person.sub:
            raise Problem.unprocessable("unknown-user", f"No user ID for {self.person.username}")
        return self.person.sub

    @property
    def email(self) -> str | None:
        return self.person.email

    def record(self) -> dict:
        rec = {"requester": self.person.record()}
        if self.caller.kind == "service":
            rec["submittedByClient"] = self.caller.client_id
        return rec


def resolve_requester(caller: Identity, on_behalf_of: str | None,
                      directory: DirectoryProvider | CachedDirectory | None,
                      require_employee_id: bool = True) -> Requester:
    if caller.kind == "user":
        if on_behalf_of:
            raise Problem.unprocessable("on-behalf-of-not-allowed",
                                        "A person calls as themselves; onBehalfOf is for service clients")
        if require_employee_id and not caller.employee_id:
            raise Problem.unprocessable("identity-incomplete",
                                        "The token has no employee_id claim; check the cmapi-identity client scope")
        return Requester(person=caller, caller=caller)
    if not on_behalf_of:
        raise Problem.unprocessable("on-behalf-of-required",
                                    "A service client must name the person the request is for")
    if directory is None:
        raise Problem.unprocessable("unknown-user", "No directory is configured")
    person = directory.get_user(on_behalf_of) or directory.find_by_employee_id(on_behalf_of)
    if person is None or not person.enabled:
        raise Problem.unprocessable("unknown-user", f"{on_behalf_of} is not an enabled user",
                                    onBehalfOf=on_behalf_of)
    return Requester(person=person, caller=caller)


def check_team_dl(value: str | None, domains: Iterable[str]) -> None:
    if not value:
        raise Problem.policy_violation("cmapi.net/team-dl is required",
                                       [{"code": "missing_required_key", "key": "cmapi.net/team-dl"}])
    if not email_in_domains(value, domains):
        raise Problem.unprocessable("invalid-team-dl",
                                    f"{value} is not an address in {sorted(domains)}",
                                    emailDomains=sorted(domains))
