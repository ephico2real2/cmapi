"""The keycloak DirectoryProvider: the only code in cmapi that calls the Keycloak admin API.

Read-only. It signs in with client credentials as cmapi-directory (realm-management roles
view-users and query-users, nothing else), keeps the access token until shortly before expiry,
and maps a UserRepresentation to a Person. The HTTP call is injected, so the API pods use httpx
and tests use a fake; there is no other dependency.

    GET /admin/realms/{realm}/users?username=<u>&exact=true
    GET /admin/realms/{realm}/users?q=employeeId:<id>&exact=true
    GET /admin/realms/{realm}/users?search=<text>&max=<n>&briefRepresentation=false

{realm} is the realm's name as one path segment (realm_segment). The name comes from the issuer (split_issuer), which
carries it percent-encoded: it is decoded once there and encoded once here (#640).
"""
from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import quote, unquote, urlencode

from cmapi.core.identity.claims import Person
from cmapi.core.identity.directory import DirectoryUnavailable

# (method, url, headers, form) -> (status, json body)
Http = Callable[[str, str, dict[str, str], dict[str, str] | None], tuple[int, Any]]


def split_issuer(issuer: str) -> tuple[str, str]:
    """A Keycloak issuer `<base>/realms/<segment>` as (base, realm name).

    Keycloak writes the realm name into `iss` as one percent-encoded path segment: Urls.realmIssuer builds it with
    UriBuilder.build, which encodes template values, "%" and "/" included (Jakarta REST UriBuilder). So the segment is a URL
    part, not the name: a realm `cmapi 640` has the issuer `.../realms/cmapi%20640`. It is decoded here, exactly once, and
    realm_segment encodes the name exactly once where it goes back into a path. RFC 3986, section 2.4: "Implementations must
    not percent-encode or decode the same string more than once". A segment that is not UTF-8 raises rather than naming
    another realm."""
    base, sep, segment = issuer.rpartition("/realms/")
    if not sep or not segment:
        raise ValueError(f"not a Keycloak issuer, <base>/realms/<realm>: {issuer!r}")
    return base, unquote(segment, errors="strict")


def realm_segment(realm: str) -> str:
    """A realm name as one URL path segment: every character outside RFC 3986's unreserved set encoded, "/" included."""
    return quote(realm, safe="")


class KeycloakAdminDirectory:
    def __init__(self, base_url: str, realm: str, client_id: str, client_secret: str, http: Http,
                 clock: Callable[[], float] = time.monotonic,
                 employee_id_attribute: str = "employeeId", middle_name_attribute: str = "middleName"):
        self.base, self.realm = base_url.rstrip("/"), realm
        self.client_id, self.secret, self.http, self.clock = client_id, client_secret, http, clock
        self.emp_attr, self.mid_attr = employee_id_attribute, middle_name_attribute
        self._token: tuple[str, float] | None = None

    def _bearer(self) -> str:
        if self._token and self.clock() < self._token[1]:
            return self._token[0]
        status, body = self._call("POST", f"{self.base}/realms/{realm_segment(self.realm)}/protocol/openid-connect/token",
                                  {}, {"grant_type": "client_credentials", "client_id": self.client_id,
                                       "client_secret": self.secret})
        if status != 200:
            raise DirectoryUnavailable(f"token request failed: {status}")
        self._token = (body["access_token"], self.clock() + max(body.get("expires_in", 60) - 30, 5))
        return self._token[0]

    def _call(self, method: str, url: str, headers: dict[str, str], form: dict[str, str] | None):
        try:
            return self.http(method, url, headers, form)
        except OSError as exc:
            raise DirectoryUnavailable(str(exc)) from exc

    def _users(self, params: dict[str, str]) -> list[dict[str, Any]]:
        url = f"{self.base}/admin/realms/{realm_segment(self.realm)}/users?{urlencode(params)}"
        status, body = self._call("GET", url, {"Authorization": f"Bearer {self._bearer()}"}, None)
        if status == 401:                       # token revoked early: one fresh try
            self._token = None
            status, body = self._call("GET", url, {"Authorization": f"Bearer {self._bearer()}"}, None)
        if status >= 500 or status in (401, 403):
            raise DirectoryUnavailable(f"admin API answered {status}")
        return body if status == 200 else []

    def _person(self, u: dict[str, Any]) -> Person:
        attrs = u.get("attributes") or {}
        first = lambda k: (attrs.get(k) or [None])[0]   # noqa: E731
        return Person(username=u["username"], email=u.get("email"), enabled=u.get("enabled", True),
                      sub=u.get("id"),
                      given_name=u.get("firstName"), family_name=u.get("lastName"),
                      middle_name=first(self.mid_attr), employee_id=first(self.emp_attr))

    def get_user(self, username: str) -> Person | None:
        users = self._users({"username": username, "exact": "true", "briefRepresentation": "false"})
        return next((self._person(u) for u in users if u["username"].lower() == username.lower()), None)

    def find_by_employee_id(self, employee_id: str) -> Person | None:
        users = self._users({"q": f"{self.emp_attr}:{employee_id}", "exact": "true",
                             "briefRepresentation": "false"})
        return self._person(users[0]) if len(users) == 1 else None    # never guess between two

    def search(self, text: str, limit: int = 10) -> list[Person]:
        users = self._users({"search": text, "max": str(limit), "briefRepresentation": "false"})
        return [self._person(u) for u in users[:limit]]
