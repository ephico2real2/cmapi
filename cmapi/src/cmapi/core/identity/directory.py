"""DirectoryProvider: looking people up. The keycloak adapter (keycloak_admin.py) is the only code
that calls the Keycloak admin API; this module holds the protocol and the cache in front of it.

The cache keeps entries 15 minutes and keeps serving an expired entry when the provider is down
(stale-on-error, as with the JWKS), so a Keycloak outage does not stop onBehalfOf requests for
people already seen. A person never seen while Keycloak is down gets DirectoryUnavailable.
"""
from __future__ import annotations

import time
from typing import Callable, Protocol, runtime_checkable

from cmapi.core.identity.claims import Person


class DirectoryUnavailable(RuntimeError):
    pass


@runtime_checkable
class DirectoryProvider(Protocol):
    def get_user(self, username: str) -> Person | None: ...
    def find_by_employee_id(self, employee_id: str) -> Person | None: ...
    def search(self, text: str, limit: int = 10) -> list[Person]: ...


class InMemoryDirectory:
    """Test and dry-run provider."""

    def __init__(self, people: list[Person]):
        self.people = {p.username: p for p in people}
        self.down = False
        self.calls = 0

    def _check(self) -> None:
        self.calls += 1
        if self.down:
            raise DirectoryUnavailable("directory down")

    def get_user(self, username: str) -> Person | None:
        self._check()
        return self.people.get(username)

    def find_by_employee_id(self, employee_id: str) -> Person | None:
        self._check()
        return next((p for p in self.people.values() if p.employee_id == employee_id), None)

    def search(self, text: str, limit: int = 10) -> list[Person]:
        self._check()
        t = text.lower()
        hits = [p for p in self.people.values()
                if t in p.username.lower() or t in (p.email or "").lower()
                or t in " ".join(x or "" for x in (p.given_name, p.family_name)).lower()]
        return sorted(hits, key=lambda p: (not p.username.lower().startswith(t), p.username))[:limit]


class CachedDirectory:
    def __init__(self, provider: DirectoryProvider, ttl_seconds: int = 900,
                 clock: Callable[[], float] = time.monotonic):
        self.provider, self.ttl, self.clock = provider, ttl_seconds, clock
        self._cache: dict[tuple[str, str], tuple[float, Person | None]] = {}

    def _get(self, kind: str, key: str, fetch: Callable[[], Person | None]) -> Person | None:
        now = self.clock()
        hit = self._cache.get((kind, key))
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        try:
            value = fetch()
        except DirectoryUnavailable:
            if hit:                      # stale-on-error
                return hit[1]
            raise
        self._cache[(kind, key)] = (now, value)
        return value

    def get_user(self, username: str) -> Person | None:
        return self._get("u", username, lambda: self.provider.get_user(username))

    def find_by_employee_id(self, employee_id: str) -> Person | None:
        return self._get("e", employee_id, lambda: self.provider.find_by_employee_id(employee_id))

    def search(self, text: str, limit: int = 10) -> list[Person]:
        return self.provider.search(text, limit)       # never cached: the picker wants live results
