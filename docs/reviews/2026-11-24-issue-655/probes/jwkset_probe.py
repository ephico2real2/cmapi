"""GHSA-w6j9-cwv2-h6wq's class in cmapi's own loop (core/auth.py, Jwks._signing_keys): does one malformed signing key in
the realm's JWKS stop every other key from loading? (#655)"""
import jwt
from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.errors import Problem
from conftest import AUDIENCE, ISSUER, Keys
keys = Keys()
bad = [{"kty": "RSA", "kid": "bad-n", "use": "sig", "alg": "RS256", "n": "!!!", "e": "AQAB"},
       {"kty": "RSA", "kid": "no-n", "use": "sig", "alg": "RS256", "e": "AQAB"},
       {"kty": "RSA", "kid": "rs-unknown-alg", "use": "sig", "alg": "RS999", "n": keys.jwk["n"], "e": "AQAB"}]
print(f"PyJWT {jwt.__version__}")
for b in bad:
    a = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=lambda u, b=b: [b, keys.jwk], clock=lambda: 0.0))
    try:
        who = a.authenticate(keys.token("ola"))
        print(f"JWKS = [{b['kid']}, the good key]: the good key's token -> accepted ({who.username})")
    except Problem as p:
        print(f"JWKS = [{b['kid']}, the good key]: the good key's token -> refused {p.status} {p.code}: {p.detail}")
