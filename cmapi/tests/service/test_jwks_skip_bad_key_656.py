"""One signing key that cannot be loaded does not take the realm's other keys with it (#656).

RFC 7517, section 5: "Implementations SHOULD ignore JWKs within a JWK Set that use "kty" (key type) values that are not
understood by them, that are missing required members, or for which values are out of the supported ranges." Before the fix,
one such key made Jwks._signing_keys raise, so no key loaded and every token was 503 idp-unavailable.
"""
from __future__ import annotations

import pytest

from cmapi.core.auth import JWKS_KEYS_SKIPPED, Authenticator, Jwks
from cmapi.core.errors import Problem
from conftest import AUDIENCE, ISSUER, Keys

BAD_KEYS = {
    "n is not base64url": {"kty": "RSA", "kid": "bad-n", "use": "sig", "alg": "RS256", "n": "!!!", "e": "AQAB"},
    "n is missing": {"kty": "RSA", "kid": "no-n", "use": "sig", "alg": "RS256", "e": "AQAB"},
    "an alg PyJWT does not know": {"kty": "RSA", "kid": "rs999", "use": "sig", "alg": "RS999", "n": "AQAB", "e": "AQAB"},
    "n is not a string": {"kty": "RSA", "kid": "n-int", "use": "sig", "alg": "RS256", "n": 5, "e": "AQAB"},
    "no kid": {"kty": "RSA", "use": "sig", "alg": "RS256", "n": "AQAB", "e": "AQAB"},
}


def make(fetch) -> Authenticator:
    return Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=fetch, clock=lambda: 0.0))


@pytest.mark.parametrize("case", list(BAD_KEYS))
def test_a_bad_signing_key_is_skipped_and_the_good_one_still_verifies(keys: Keys, case):
    before = JWKS_KEYS_SKIPPED._value.get()
    who = make(lambda url: [BAD_KEYS[case], keys.jwk]).authenticate(keys.token("ola"))
    assert who.username == "ola"
    assert JWKS_KEYS_SKIPPED._value.get() == before + 1


def test_a_set_of_bad_keys_alone_is_still_a_failed_refresh(keys: Keys):
    """Nothing usable is the same as an unreachable Keycloak, as before: 503, never 401."""
    with pytest.raises(Problem) as e:
        make(lambda url: list(BAD_KEYS.values())).authenticate(keys.token("ola"))
    assert (e.value.status, e.value.code) == (503, "idp-unavailable")


def test_a_member_that_is_not_an_object_is_ignored(keys: Keys):
    who = make(lambda url: ["not-a-jwk", 7, None, keys.jwk]).authenticate(keys.token("ola"))
    assert who.username == "ola"
