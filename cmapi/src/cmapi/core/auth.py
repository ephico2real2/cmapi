"""Token verification: every bearer token is checked offline against the realm's JWKS.

docs/02, "Token verification": RS256 only, iss and aud pinned, exp/nbf with 30 s leeway, keys
cached ten minutes and refetched once on an unknown kid, at most once per retry window, so forged
kids cannot drive Keycloak and a hanging Keycloak stalls one caller, not all of them. Stale-on-error: when Keycloak cannot be
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
                 clock: Callable[[], float] = time.monotonic, retry_after: float = 30.0):
        self.issuer, self.url, self.verify, self.lifespan, self.retry_after = issuer, url, verify, lifespan, retry_after
        self.store, self.clock = store, clock
        self._fetch = fetch or self._http_fetch
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = -1.0
        self._last_failure: float | None = None     # when the last refresh failed; None while Keycloak answers
        self._last_unknown: float | None = None     # when an unknown kid last caused a refetch
        self._refreshing = False
        self._cond = threading.Condition()

    def _http_fetch(self, url: str) -> list[dict[str, Any]]:
        r = httpx.get(url, timeout=5.0, verify=self.verify)
        r.raise_for_status()
        return r.json()["keys"]

    @staticmethod
    def _signing_keys(raw: list[dict[str, Any]]) -> dict[str, jwt.PyJWK]:
        # Keycloak's JWKS also holds an RSA-OAEP key with use=enc, which PyJWK cannot load.
        return {k["kid"]: jwt.PyJWK(k) for k in raw if k.get("use", "sig") == "sig" and k.get("kty") == "RSA"}

    def _refresh(self) -> bool:
        try:
            raw = self._fetch(self.url)
            keys = self._signing_keys(raw)
            if not keys:                                            # an empty answer never replaces a good set
                raise ValueError("no signing keys in the JWKS")
        except Exception:                                           # noqa: BLE001 - any transport or parse error
            JWKS_REFRESH.labels("error").inc()
            return False
        with self._cond:
            self._keys, self._fetched_at = keys, self.clock()
        JWKS_REFRESH.labels("ok").inc()
        if self.store is not None:
            try:
                self.store.save(self.issuer, raw)
            except Exception:                                       # noqa: BLE001 - persistence is best effort
                pass
        return True

    def _load_stored(self) -> None:
        if self._keys or self.store is None:
            return
        try:
            stored = self.store.load(self.issuer)
            keys = self._signing_keys(stored) if stored else {}
        except Exception:                                           # noqa: BLE001 - a bad copy is the same as no copy
            return
        with self._cond:
            self._keys = self._keys or keys

    def _due(self, kid: str, now: float) -> bool:
        """Whether this caller should fetch. After a failure nobody does until the retry window has passed."""
        if self._last_failure is not None and now - self._last_failure < self.retry_after:
            return False
        if not self._keys or now - self._fetched_at > self.lifespan:
            return True
        if kid in self._keys:
            return False
        return self._last_unknown is None or now - self._last_unknown >= self.retry_after

    def key(self, kid: str) -> jwt.PyJWK:
        now = self.clock()
        with self._cond:
            fetch = not self._refreshing and self._due(kid, now)
            if fetch:
                self._refreshing = True
                if self._keys and kid not in self._keys and now - self._fetched_at <= self.lifespan:
                    self._last_unknown = now
            elif self._refreshing and kid not in self._keys:
                self._cond.wait(timeout=6.0)                        # it may be the new key: wait for the one fetch in flight
        if fetch:
            # Outside the lock: callers whose key is cached keep verifying while this one waits on Keycloak.
            ok = False
            try:
                self._load_stored()
                ok = self._refresh()
            finally:
                with self._cond:
                    self._refreshing = False
                    self._last_failure = None if ok else self.clock()
                    self._cond.notify_all()
        with self._cond:
            k = self._keys.get(kid)
            if k is not None:
                return k
            if self._keys and self._last_failure is None:
                raise jwt.InvalidTokenError("unknown signing key")
        IDP_UNAVAILABLE.inc()
        raise Problem(503, "idp-unavailable", "Keycloak signing keys are unreachable and this key is not cached",
                      extra={"retryAfter": 30})


# RFC 9068, section 4: the resource server "MUST verify that the "typ" header value is "at+jwt" or "application/at+jwt"".
ACCESS_TOKEN_TYPES = frozenset({"at+jwt", "application/at+jwt"})


class Authenticator:
    """Verifies tokens for one instance: issuer, audience, the roles claim path, and that the token is an access token.

    An access token has the JOSE header `typ: at+jwt` (RFC 9068). Keycloak writes it for a client with the attribute
    `access.token.header.type.rfc9068`, which cmapi's realm sets on each client that gets a token for cmapi. Without that
    attribute Keycloak writes `typ: JWT` in the header of each token, and says what the token is only in its own claim
    `typ` (Bearer, ID, Refresh). `legacy_token_type` (instance.yaml `auth.acceptLegacyTokenType`) accepts that form for
    a realm that cannot set the attribute: the header `JWT` and the claim `Bearer`, both, and never a token with no claim.
    """

    def __init__(self, issuer: str, audience: str, jwks: Jwks, leeway: int = 30, legacy_token_type: bool = False):
        self.issuer, self.audience, self.jwks, self.leeway = issuer, audience, jwks, leeway
        self.legacy_token_type = legacy_token_type

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
        # An ID token or a refresh token is never a bearer credential here. The header is under the signature that was just verified.
        header_type, claim_type = str(header.get("typ") or "").lower(), claims.get("typ")
        rfc9068 = header_type in ACCESS_TOKEN_TYPES and claim_type in (None, "Bearer")
        legacy = self.legacy_token_type and header_type == "jwt" and claim_type == "Bearer"
        if not (rfc9068 or legacy):
            AUTH_FAILURES.labels("token-type").inc()
            raise Problem(401, "unauthenticated", "Token is not an access token")
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
