"""One signing key that cannot be loaded does not take the realm's other keys with it (#656).

RFC 7517, section 5: "Implementations SHOULD ignore JWKs within a JWK Set that use "kty" (key type) values that are not
understood by them, that are missing required members, or for which values are out of the supported ranges." Before the fix,
one such key made Jwks._signing_keys raise, so no key loaded and every token was 503 idp-unavailable.
"""
from __future__ import annotations

import jwt
import pytest
import structlog
from cryptography.hazmat.primitives.asymmetric import rsa

from cmapi.core.auth import JWKS_KEYS_SKIPPED, Authenticator, Jwks
from cmapi.core.errors import Problem
from conftest import AUDIENCE, ISSUER, Keys

BAD_KEYS = {
    "n is not base64url": {"kty": "RSA", "kid": "bad-n", "use": "sig", "alg": "RS256", "n": "!!!", "e": "AQAB"},
    "n is missing": {"kty": "RSA", "kid": "no-n", "use": "sig", "alg": "RS256", "e": "AQAB"},
    "n is not a string": {"kty": "RSA", "kid": "n-int", "use": "sig", "alg": "RS256", "n": 5, "e": "AQAB"},
    "no kid": {"kty": "RSA", "use": "sig", "alg": "RS256", "n": "AQAB", "e": "AQAB"},
}
# The review of #658: members whose key material is good, so that only the named member makes them unusable. On the first
# fix a `kid` that is a list or an object raised TypeError (unhashable) past its `except (KeyError, jwt.PyJWTError)`, so
# every token was 503 again. A token's kid is a non-empty string, so a member without one can verify nothing. `absent`
# removes the member.
absent = object()
BAD_MEMBERS = {
    "kid is absent": {"kid": absent},
    "kid is a list": {"kid": ["a"]},
    "kid is an object": {"kid": {"a": 1}},
    "kid is null": {"kid": None},
    "kid is a number": {"kid": 7},
    "kid is empty": {"kid": ""},
}
# Keys for an algorithm other than RS256: passed over, as an encryption key is, and not counted. RFC 8725, section 3.1:
# "each key MUST be used with exactly one algorithm". On the first fix `alg` as a list and `alg: none` raised TypeError and
# NotImplementedError past its `except (KeyError, jwt.PyJWTError)`, so every token was 503 again, and a key for PS256 or
# RS512 verified RS256 tokens.
OTHER_ALGORITHMS = {"PS256": "PS256", "RS512": "RS512", "an alg PyJWT does not know": "RS999", "alg is none": "none",
                    "alg is an HMAC": "HS256", "alg is a list": ["RS256"], "alg is a number": 5, "alg in lower case": "rs256"}


def member(good: dict, change: dict) -> dict:
    """`good` with each member of `change` set, or removed when it is `absent`."""
    return {k: v for k, v in {**good, **change}.items() if v is not absent}


@pytest.fixture(scope="module")
def other():
    """A second key pair of the realm: its private key, and its public JWK under the kid `other`."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, {**jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True), "kid": "other", "use": "sig",
                     "alg": "RS256"}


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


@pytest.mark.parametrize("case", list(BAD_MEMBERS))
def test_a_member_that_makes_a_good_key_unusable_is_skipped_too(keys: Keys, case):
    before = JWKS_KEYS_SKIPPED._value.get()
    who = make(lambda url: [member(keys.jwk, BAD_MEMBERS[case]), keys.jwk]).authenticate(keys.token("ola"))
    assert who.username == "ola"
    assert JWKS_KEYS_SKIPPED._value.get() == before + 1


def test_a_good_key_is_not_counted_as_skipped(keys: Keys):
    before = JWKS_KEYS_SKIPPED._value.get()
    assert make(lambda url: [keys.jwk]).authenticate(keys.token("ola")).username == "ola"
    assert JWKS_KEYS_SKIPPED._value.get() == before


@pytest.mark.parametrize("order", ["the bad key first", "the good key first"])
@pytest.mark.parametrize("case", ["n is not base64url", "n is missing", "n is not a string"])
def test_a_token_that_names_a_skipped_key_is_401_and_no_other_key_verifies_it(keys: Keys, other, case, order):
    """The realm's key `test-kid-1` is published broken, beside a good key `other`. A token that names `test-kid-1` is
    refused as an unknown key, whoever signed it: the realm's real key, or the key that did load."""
    private, other_jwk = other
    jwks = [{**BAD_KEYS[case], "kid": keys.kid}, other_jwk]
    auth = make(lambda url: jwks if order == "the bad key first" else jwks[::-1])
    claims = jwt.decode(keys.token("ola"), options={"verify_signature": False})
    by_the_loaded_key = jwt.encode(claims, private, algorithm="RS256", headers={"kid": keys.kid, "typ": "at+jwt"})
    for token in (keys.token("ola"), by_the_loaded_key):
        with pytest.raises(Problem) as e:
            auth.authenticate(token)
        assert (e.value.status, e.value.detail) == (401, "Invalid token: unknown signing key")
    good = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "other", "typ": "at+jwt"})
    assert auth.authenticate(good).username == "ola"                 # the key that loaded verifies its own tokens only


@pytest.mark.parametrize("order", ["bad first", "good first"])
def test_a_bad_member_does_not_hide_a_good_key_of_the_same_kid(keys: Keys, order):
    bad = {**BAD_KEYS["n is missing"], "kid": keys.kid}
    jwks = [bad, keys.jwk] if order == "bad first" else [keys.jwk, bad]
    assert make(lambda url: jwks).authenticate(keys.token("ola")).username == "ola"


def test_a_member_with_private_parameters_is_skipped(keys: Keys, other):
    """A JWKS never holds a private key. PyJWK loads one as a private key object, and PyJWT's RS256 cannot verify with it:
    on the first fix a token of that kid was an AttributeError, HTTP 500. It is 401 now, and the others verify."""
    private, other_jwk = other
    published_private = {**jwt.algorithms.RSAAlgorithm.to_jwk(private, as_dict=True), "kid": "other", "use": "sig", "alg": "RS256"}
    auth = make(lambda url: [published_private, keys.jwk])
    claims = jwt.decode(keys.token("ola"), options={"verify_signature": False})
    with pytest.raises(Problem) as e:
        auth.authenticate(jwt.encode(claims, private, algorithm="RS256", headers={"kid": "other", "typ": "at+jwt"}))
    assert (e.value.status, e.value.detail) == (401, "Invalid token: unknown signing key")
    assert auth.authenticate(keys.token("ola")).username == "ola"


def test_the_log_of_a_skipped_key_has_no_key_material(other):
    """The log line has the type of the error, the kid and the names of the member's parameters, never the error's message:
    some of PyJWT's print the member ("Unable to find an algorithm for key: {...}"), and the first fix logged 200 characters
    of it, which held the start of a private exponent (the review of #658)."""
    private, _ = other
    full = jwt.algorithms.RSAAlgorithm.to_jwk(private, as_dict=True)
    bad = {"d": full["d"], "kty": "RSA", "kid": "leak", "use": "sig", "alg": "RS256", "n": full["n"], "e": ["AQAB"]}
    with structlog.testing.capture_logs() as logs:
        assert Jwks._signing_keys([bad]) == {}
    assert [{**line, "error": "?"} for line in logs] == [{"event": "jwks_key_skipped", "log_level": "warning", "kid": "leak",
                                                         "error": "?", "members": ["alg", "d", "e", "kid", "kty", "n", "use"]}]
    assert logs[0]["error"] in {"InvalidKeyError", "TypeError"}          # PyJWT 2.15.1 and 2.10.1
    assert full["d"][:16] not in repr(logs) and full["n"][:16] not in repr(logs)


@pytest.mark.parametrize("case", list(OTHER_ALGORITHMS))
def test_a_key_for_another_algorithm_is_passed_over_and_not_counted(keys: Keys, case):
    before = JWKS_KEYS_SKIPPED._value.get()
    other_alg = {**keys.jwk, "kid": "other-alg", "alg": OTHER_ALGORITHMS[case]}
    assert Jwks._signing_keys([other_alg]) == {}
    assert make(lambda url: [other_alg, keys.jwk]).authenticate(keys.token("ola")).username == "ola"
    assert JWKS_KEYS_SKIPPED._value.get() == before


def test_a_key_with_no_alg_is_a_key_for_rs256(keys: Keys):
    """RFC 7517, section 4.4: "Use of this member is OPTIONAL"."""
    no_alg = {k: v for k, v in keys.jwk.items() if k != "alg"}
    assert make(lambda url: [no_alg]).authenticate(keys.token("ola")).username == "ola"


@pytest.mark.parametrize("alg", ["PS256", "RS512"])
def test_a_key_published_for_another_algorithm_never_verifies_an_rs256_token(keys: Keys, other, alg):
    """RFC 8725, section 3.1: "each key MUST be used with exactly one algorithm". A realm key for PS256 or RS512 must not
    verify an RS256 token, even one its own private key signed. Before the review of #658 it did."""
    private, other_jwk = other
    auth = make(lambda url: [{**other_jwk, "alg": alg}, keys.jwk])
    claims = jwt.decode(keys.token("ola"), options={"verify_signature": False})
    with pytest.raises(Problem) as e:
        auth.authenticate(jwt.encode(claims, private, algorithm="RS256", headers={"kid": "other", "typ": "at+jwt"}))
    assert (e.value.status, e.value.detail) == (401, "Invalid token: unknown signing key")
    assert auth.authenticate(keys.token("ola")).username == "ola"


def test_an_encryption_key_with_no_alg_never_verifies_a_token(keys: Keys, other):
    """RFC 7517, section 4.2: "The "use" parameter is employed to indicate whether a public key is used for encrypting data or
    verifying the signature on data." An encryption key with no `alg` passes the algorithm filter; the `use` check keeps it out."""
    private, other_jwk = other
    enc = {k: v for k, v in {**other_jwk, "use": "enc"}.items() if k != "alg"}
    auth = make(lambda url: [enc, keys.jwk])
    claims = jwt.decode(keys.token("ola"), options={"verify_signature": False})
    with pytest.raises(Problem) as e:
        auth.authenticate(jwt.encode(claims, private, algorithm="RS256", headers={"kid": "other", "typ": "at+jwt"}))
    assert (e.value.status, e.value.detail) == (401, "Invalid token: unknown signing key")


def test_a_set_of_bad_keys_does_not_replace_the_keys_already_held(keys: Keys):
    """Stale-on-error, as for an unreachable Keycloak: after a good fetch, a JWKS with nothing usable is a failed refresh,
    and the last good keys keep verifying."""
    now, answers = [0.0], [[keys.jwk]]
    auth = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=lambda url: answers[-1],
                                                clock=lambda: now[0]))
    assert auth.authenticate(keys.token("ola")).username == "ola"
    now[0], _ = 601.0, answers.append(list(BAD_KEYS.values()))       # past the ten-minute lifespan: the next call refetches
    assert auth.authenticate(keys.token("ola")).username == "ola"
