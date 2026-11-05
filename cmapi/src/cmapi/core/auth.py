"""Token verification: every bearer token is checked offline against the realm's JWKS.

docs/02, "Token verification": RS256 only, iss and aud pinned, exp/nbf with 30 s leeway, keys
cached ten minutes and refetched once on an unknown kid. Stale-on-error: when Keycloak cannot be
reached the last good key set keeps verifying, in memory and, through KeyStore, persisted so a
fresh pod after a restart can still verify during an outage. A token whose kid matches no cached
key while Keycloak is down is 503 idp-unavailable, never 401.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping, Protocol

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2AuthorizationCodeBearer
from prometheus_client import Counter

from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity

AUTH_FAILURES = Counter("cmapi_auth_failures_total", "Refused tokens", ["reason"])
JWKS_REFRESH = Counter("cmapi_jwks_refresh_total", "JWKS fetches", ["result"])
IDP_UNAVAILABLE = Counter("cmapi_idp_unavailable_total", "Calls refused because no signing key was available")


class KeyStore(Protocol):
    """Persists the last good JWKS so a restarted pod verifies through a Keycloak outage."""
    def load(self, issuer: str) -> list[dict[str, Any]] | None: ...
    def save(self, issuer: str, keys: list[dict[str, Any]]) -> None: ...


class Jwks:
    def __init__(self, issuer: str, url: str, *, verify: str | bool = True, lifespan: float = 600.0,
                 store: KeyStore | None = None, fetch: Callable[[str], list[dict[str, Any]]] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.issuer, self.url, self.verify, self.lifespan = issuer, url, verify, lifespan
        self.store, self.clock = store, clock
        self._fetch = fetch or self._http_fetch
        self._keys: dict[str, jwt.PyJWK] = {}
        self._raw: list[dict[str, Any]] = []
        self._fetched_at = -1.0
        self._lock = threading.Lock()

    def _http_fetch(self, url: str) -> list[dict[str, Any]]:
        r = httpx.get(url, timeout=5.0, verify=self.verify)
        r.raise_for_status()
        return r.json()["keys"]

    def _refresh(self) -> bool:
        try:
            raw = self._fetch(self.url)
        except Exception:                                           # noqa: BLE001 - any transport or parse error
            JWKS_REFRESH.labels("error").inc()
            return False
        keys = {}
        for k in raw:
            if k.get("use", "sig") == "sig" and k.get("kty") == "RSA":
                keys[k["kid"]] = jwt.PyJWK(k)
        self._keys, self._raw, self._fetched_at = keys, raw, self.clock()
        JWKS_REFRESH.labels("ok").inc()
        if self.store is not None:
            try:
                self.store.save(self.issuer, raw)
            except Exception:                                       # noqa: BLE001 - persistence is best effort
                pass
        return True

    def key(self, kid: str) -> jwt.PyJWK:
        with self._lock:
            if not self._keys and self.store is not None:
                try:
                    stored = self.store.load(self.issuer)
                except Exception:                                   # noqa: BLE001
                    stored = None
                if stored:
                    self._keys = {k["kid"]: jwt.PyJWK(k) for k in stored if k.get("kty") == "RSA"}
                    self._raw = stored
            stale = self.clock() - self._fetched_at > self.lifespan
            if kid not in self._keys or stale:
                # one refetch on an unknown kid (rotation) or an expired cache; a failure keeps the last good set
                self._refresh()
            k = self._keys.get(kid)
            if k is None:
                if self._keys:
                    raise jwt.InvalidTokenError("unknown signing key")
                IDP_UNAVAILABLE.inc()
                raise Problem(503, "idp-unavailable", "Keycloak signing keys are unreachable and none are cached",
                              extra={"retryAfter": 30})
            return k


class Authenticator:
    """Verifies tokens for one instance: issuer, audience and the roles claim path."""

    def __init__(self, issuer: str, audience: str, jwks: Jwks, leeway: int = 30):
        self.issuer, self.audience, self.jwks, self.leeway = issuer, audience, jwks, leeway

    def authenticate(self, bearer: str) -> Identity:
        try:
            header = jwt.get_unverified_header(bearer)
        except jwt.PyJWTError as exc:
            AUTH_FAILURES.labels("malformed").inc()
            raise Problem(401, "unauthenticated", "Invalid token") from exc
        if header.get("alg") != "RS256" or not header.get("kid"):
            AUTH_FAILURES.labels("algorithm").inc()
            raise Problem(401, "unauthenticated", "Invalid token: unsupported algorithm")
        try:
            key = self.jwks.key(header["kid"])
        except jwt.PyJWTError as exc:
            AUTH_FAILURES.labels("signature").inc()
            raise Problem(401, "unauthenticated", "Invalid token: unknown signing key") from exc
        try:
            claims = jwt.decode(bearer, key.key, algorithms=["RS256"], audience=self.audience, issuer=self.issuer,
                                leeway=self.leeway, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        except jwt.ExpiredSignatureError as exc:
            AUTH_FAILURES.labels("expired").inc()
            raise Problem(401, "unauthenticated", "Token expired") from exc
        except jwt.InvalidAudienceError as exc:
            AUTH_FAILURES.labels("audience").inc()
            raise Problem(401, "unauthenticated", f"Token is not for audience {self.audience}") from exc
        except jwt.InvalidIssuerError as exc:
            AUTH_FAILURES.labels("issuer").inc()
            raise Problem(401, "unauthenticated", "Token issuer is not trusted") from exc
        except jwt.PyJWTError as exc:
            AUTH_FAILURES.labels("signature").inc()
            raise Problem(401, "unauthenticated", "Invalid token") from exc
        return Identity.from_claims(claims, self.audience)


def oauth2_scheme(issuer: str) -> OAuth2AuthorizationCodeBearer:
    """Reads Authorization: Bearer and drives Swagger UI's Authorize button (PKCE through cmapi-docs)."""
    return OAuth2AuthorizationCodeBearer(
        authorizationUrl=f"{issuer}/protocol/openid-connect/auth",
        tokenUrl=f"{issuer}/protocol/openid-connect/token",
        auto_error=False, scheme_name="keycloak")


def caller_dependency(scheme: OAuth2AuthorizationCodeBearer) -> Callable[..., Identity]:
    """The FastAPI dependency: request.app.state.auth verifies the token."""

    def caller(request: Request, token: str | None = Depends(scheme)) -> Identity:
        if not token:
            AUTH_FAILURES.labels("missing").inc()
            raise Problem(401, "unauthenticated", "Bearer token required")
        who = request.app.state.auth.authenticate(token)
        request.state.caller = who
        return who

    return caller


def unauthenticated_headers(problem: Problem) -> Mapping[str, str]:
    return {"WWW-Authenticate": 'Bearer error="invalid_token"'} if problem.status == 401 else {}
