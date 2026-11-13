"""core/auth.py against the design's token rules (docs/02, Token verification)."""
from __future__ import annotations

import pytest

from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.errors import Problem
from conftest import AUDIENCE, ISSUER, Keys


def make(keys: Keys, fetch=None, store=None, clock=None):
    jwks = Jwks(ISSUER, "https://keycloak.test/certs", fetch=fetch or (lambda url: [keys.jwk]), store=store,
                clock=clock or (lambda: 0.0))
    return Authenticator(ISSUER, AUDIENCE, jwks)


def test_valid_token_becomes_identity(keys):
    who = make(keys).authenticate(keys.token("ola", roles=["cmapi-requester"], groups=["/cmapi/app-cmapi-rbac-requester"]))
    assert who.username == "ola" and who.roles == {"cmapi-requester"} and who.groups == {"/cmapi/app-cmapi-rbac-requester"}
    assert who.employee_id == "1001" and who.kind == "user" and who.client_id == "cmapi-portal"


def test_service_account_token(keys):
    who = make(keys).authenticate(keys.token("service-account-svc-payments-ci", roles=["cmapi-requester"], client="svc-payments-ci"))
    assert who.kind == "service" and who.username == "svc-payments-ci"


@pytest.mark.parametrize("kw,reason", [
    ({"aud": "cmapi-prod"}, "audience"),
    ({"iss": "https://keycloak.test/realms/other"}, "issuer"),
    ({"exp_in": -120}, "expired"),
])
def test_wrong_audience_issuer_or_expired_is_401(keys, kw, reason):
    with pytest.raises(Problem) as e:
        make(keys).authenticate(keys.token("ola", **kw))
    assert e.value.status == 401 and e.value.code == "unauthenticated"


def test_alg_none_and_hs256_are_refused(keys):
    with pytest.raises(Problem) as e:
        make(keys).authenticate(keys.token("ola", alg="none"))
    assert e.value.status == 401
    import jwt as pyjwt
    hs = pyjwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "exp": 9999999999, "iat": 1}, "secret", algorithm="HS256",
                      headers={"kid": keys.kid})
    with pytest.raises(Problem) as e:
        make(keys).authenticate(hs)
    assert e.value.status == 401


def test_unknown_kid_refetches_once_then_401(keys):
    calls = []
    def fetch(url):
        calls.append(url)
        return [keys.jwk]
    a = make(keys, fetch=fetch)
    a.authenticate(keys.token("ola"))
    assert len(calls) == 1
    with pytest.raises(Problem) as e:
        a.authenticate(keys.token("ola", kid="rotated"))
    assert e.value.status == 401 and len(calls) == 2


def test_keycloak_down_with_no_cached_key_is_503(keys):
    def fetch(url):
        raise OSError("connection refused")
    with pytest.raises(Problem) as e:
        make(keys, fetch=fetch).authenticate(keys.token("ola"))
    assert e.value.status == 503 and e.value.code == "idp-unavailable"


def test_stale_on_error_keeps_verifying(keys):
    state = {"up": True, "t": 0.0}
    def fetch(url):
        if not state["up"]:
            raise OSError("down")
        return [keys.jwk]
    a = make(keys, fetch=fetch, clock=lambda: state["t"])
    a.authenticate(keys.token("ola"))
    state["up"] = False
    state["t"] = 10_000.0                 # cache expired, Keycloak down: the last good set still verifies
    assert a.authenticate(keys.token("ola")).username == "ola"


def test_persisted_keys_serve_a_fresh_process(keys):
    class Store:
        saved = None
        def load(self, issuer): return Store.saved
        def save(self, issuer, k): Store.saved = k
    make(keys, store=Store()).authenticate(keys.token("ola"))
    assert Store.saved and Store.saved[0]["kid"] == keys.kid
    def fetch(url):
        raise OSError("down")
    assert make(keys, fetch=fetch, store=Store()).authenticate(keys.token("ola")).username == "ola"


# ---------------------------------------------------------------- #184 SEC-07: the type of the token

@pytest.mark.parametrize("typ", ["at+jwt", "application/at+jwt", "AT+JWT"])
def test_an_access_token_has_the_rfc9068_header_type(keys, typ):
    assert make(keys).authenticate(keys.token("ola", typ=typ, extra={"typ": "Bearer"})).username == "ola"
    assert make(keys).authenticate(keys.token("ola", typ=typ)).username == "ola"


@pytest.mark.parametrize("what, token", [
    ("the header JWT with the claim Bearer: Keycloak without the client attribute", lambda k: k.token("ola", typ="JWT", extra={"typ": "Bearer"})),
    ("the header JWT and no claim: nothing says that it is an access token", lambda k: k.token("ola", typ="JWT")),
    ("no header type and no claim", lambda k: k.token("ola", typ=None)),
    ("an ID token: the header JWT and the claim ID", lambda k: k.token("ola", typ="JWT", extra={"typ": "ID"})),
    ("the header at+jwt with the claim ID", lambda k: k.token("ola", extra={"typ": "ID"})),
    ("the header at+jwt with the claim Refresh", lambda k: k.token("ola", extra={"typ": "Refresh"})),
    ("a logout token", lambda k: k.token("ola", typ="logout+jwt")),
    ("a header type that only starts like one", lambda k: k.token("ola", typ="at+jwt2")),
])
def test_a_token_that_is_not_an_access_token_is_401(keys, what, token):
    with pytest.raises(Problem) as e:
        make(keys).authenticate(token(keys))
    assert e.value.status == 401 and e.value.detail == "Token is not an access token", what


def test_the_legacy_setting_accepts_keycloaks_older_form_and_nothing_weaker(keys):
    """instance.yaml auth.acceptLegacyTokenType, for a realm that cannot set the client attribute: the header JWT with the claim Bearer."""
    jwks = Jwks(ISSUER, "https://keycloak.test/certs", fetch=lambda url: [keys.jwk], clock=lambda: 0.0)
    legacy = Authenticator(ISSUER, AUDIENCE, jwks, legacy_token_type=True)
    assert legacy.authenticate(keys.token("ola", typ="JWT", extra={"typ": "Bearer"})).username == "ola"
    assert legacy.authenticate(keys.token("ola")).username == "ola", "the RFC 9068 form stays accepted"
    for token in (keys.token("ola", typ="JWT"), keys.token("ola", typ=None), keys.token("ola", typ="JWT", extra={"typ": "ID"}),
                  keys.token("ola", typ="JWT", extra={"typ": "Refresh"})):
        with pytest.raises(Problem) as e:
            legacy.authenticate(token)
        assert e.value.status == 401
