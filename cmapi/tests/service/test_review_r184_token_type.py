"""#184 (SEC-07), Codex's review: the type of an access token, on tokens that are signed here with an exact JOSE header.

Keys.token cannot write a header `typ` that is a list, a number or null, so `signed` builds the compact form itself.
"""
import base64
import json

import jwt
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from cmapi.core.auth import Authenticator
from cmapi.core.errors import Problem
from test_auth import make

ABSENT = object()


def segment(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")


def signed(keys, typ=ABSENT, claim=ABSENT, alg="RS256"):
    claims = jwt.decode(keys.token("ola"), options={"verify_signature": False})
    if claim is not ABSENT:
        claims["typ"] = claim
    header = {"alg": alg, "kid": keys.kid}
    if typ is not ABSENT:
        header["typ"] = typ
    message = segment(header) + b"." + segment(claims)
    signature = keys.private.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return (message + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


@pytest.mark.parametrize("typ", ["at+jwt", "AT+JWT", "application/at+jwt", "APPLICATION/AT+JWT"])
@pytest.mark.parametrize("claim", [ABSENT, "Bearer"])
def test_c2_access_types(keys, typ, claim):
    assert make(keys).authenticate(signed(keys, typ, claim)).username == "ola"


@pytest.mark.parametrize("typ,claim", [
    ("JWT", "ID"), ("JWT", "Refresh"), ("logout+jwt", ABSENT),
    (ABSENT, ABSENT), (ABSENT, "Bearer"), (["at+jwt"], ABSENT), (1, ABSENT),
    (None, ABSENT), ({"typ": "at+jwt"}, ABSENT),
    ("at+jwt ", ABSENT), ("application/at+jwt; charset=x", ABSENT),
    ("at+jwt", "ID"), ("at+jwt", "Refresh"),
])
def test_c2_wrong_types(keys, typ, claim):
    token = signed(keys, typ, claim)
    with pytest.raises(Problem) as caught:
        make(keys).authenticate(token)
    assert (caught.value.status, caught.value.detail) == (401, "Token is not an access token")


def test_c2_hs512_refresh_rejected_before_keys(keys):
    token = jwt.encode({"typ": "Refresh"}, "test-secret" * 8, algorithm="HS512",
                       headers={"kid": keys.kid, "typ": "JWT"})
    with pytest.raises(Problem) as caught:
        make(keys).authenticate(token)
    assert caught.value.detail == "Invalid token: unsupported algorithm"


@pytest.mark.parametrize("typ", ["JWT", "at+jwt", "logout+jwt"])
def test_c1_changing_protected_header_without_resigning_never_returns_identity(keys, typ):
    original = signed(keys, "application/at+jwt", "Bearer")
    _, payload, signature = original.split(".")
    changed_header = segment({"alg": "RS256", "kid": keys.kid, "typ": typ}).decode()
    with pytest.raises(Problem) as caught:
        make(keys).authenticate(f"{changed_header}.{payload}.{signature}")
    assert (caught.value.status, caught.value.detail) == (401, "Invalid token")


@pytest.mark.parametrize("typ", ["JWT", "jwt", "JwT"])
def test_c3_legacy_requires_bearer(keys, typ):
    default = make(keys)
    legacy = Authenticator(default.issuer, default.audience, default.jwks, legacy_token_type=True)
    assert legacy.authenticate(signed(keys, typ, "Bearer")).username == "ola"
    for claim in (ABSENT, None, "ID", "Refresh", "bearer", "BEARER"):
        with pytest.raises(Problem) as caught:
            legacy.authenticate(signed(keys, typ, claim))
        assert caught.value.detail == "Token is not an access token"


def test_e1_the_fixture_with_no_type_really_omits_the_header_and_is_rejected(keys):
    """Keys.token(typ=None) wrote PyJWT's own header JWT, so "no header type" was tested as JWT a second time."""
    token = keys.token("ola", typ=None)
    assert "typ" not in jwt.get_unverified_header(token)
    with pytest.raises(Problem) as caught:
        make(keys).authenticate(token)
    assert (caught.value.status, caught.value.detail) == (401, "Token is not an access token")
