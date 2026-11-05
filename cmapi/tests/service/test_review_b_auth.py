"""C1: forged tokens against core/auth.py and a real JWKS shape."""
from __future__ import annotations

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.errors import Problem
from conftest import AUDIENCE, ISSUER, Keys
from test_auth import make


def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def enc_key():
    pub = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    return {**jwt.algorithms.RSAAlgorithm.to_jwk(pub, as_dict=True), "kid": "enc-1", "use": "enc", "alg": "RSA-OAEP"}


@pytest.mark.parametrize("name,forge", [
    ("other instance audience", lambda k: k.token("o", aud="cmapi-prod")),
    ("id token for the portal client", lambda k: jwt.encode({"iss": ISSUER, "aud": "cmapi-portal", "sub": "s", "iat": int(time.time()), "exp": int(time.time()) + 300, "typ": "ID", "azp": "cmapi-portal"}, k.pem, algorithm="RS256", headers={"kid": k.kid})),
    ("another realm", lambda k: k.token("o", iss="https://keycloak.test/realms/corp")),
    ("issuer with trailing slash", lambda k: k.token("o", iss=ISSUER + "/")),
    ("expired past leeway", lambda k: k.token("o", exp_in=-31)),
    ("nbf in the future", lambda k: k.token("o", extra={"nbf": int(time.time()) + 300})),
    ("alg none", lambda k: k.token("o", alg="none")),
    ("alg none, no signature, handmade", lambda k: f"{b64({'alg':'none','kid':k.kid})}.{b64({'iss':ISSUER,'aud':AUDIENCE,'sub':'s','iat':1,'exp':9999999999})}."),
    ("HS256 keyed with the public PEM", lambda k: None),
    ("signature from another key, same kid", lambda k: Keys().token("o")),
    ("no kid", lambda k: jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "s", "iat": 1, "exp": 9999999999}, k.pem, algorithm="RS256")),
    ("no exp", lambda k: jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "s", "iat": 1}, k.pem, algorithm="RS256", headers={"kid": k.kid})),
    ("no sub", lambda k: jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "iat": 1, "exp": 9999999999}, k.pem, algorithm="RS256", headers={"kid": k.kid})),
    ("no iat", lambda k: jwt.encode({"iss": ISSUER, "aud": AUDIENCE, "sub": "s", "exp": 9999999999}, k.pem, algorithm="RS256", headers={"kid": k.kid})),
    ("RS512 with the real key", lambda k: k.token("o", alg="RS512")),
    ("id token carrying our audience, typ ID", lambda k: k.token("o", extra={"typ": "ID"})),
    ("refresh token typ", lambda k: k.token("o", extra={"typ": "Refresh"})),
])
def test_forged_is_401(keys, name, forge):
    if name.startswith("HS256"):
        from cryptography.hazmat.primitives import serialization
        import hashlib, hmac
        pem = keys.private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        h, p = b64({"alg": "HS256", "kid": keys.kid, "typ": "JWT"}), b64({"iss": ISSUER, "aud": AUDIENCE, "sub": "s", "iat": 1, "exp": 9999999999})
        sig = base64.urlsafe_b64encode(hmac.new(pem, f"{h}.{p}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        tok = f"{h}.{p}.{sig}"
    else:
        tok = forge(keys)
    with pytest.raises(Problem) as e:
        make(keys).authenticate(tok)
    assert e.value.status == 401, name


def test_rotated_kid_while_keycloak_is_down_is_503_not_401(keys):
    """core/auth.py docstring: a token whose kid matches no cached key while Keycloak is down is 503, never 401."""
    up = {"v": True}

    def fetch(url):
        if not up["v"]:
            raise OSError("down")
        return [keys.jwk]
    a = make(keys, fetch=fetch)
    a.authenticate(keys.token("ola"))
    up["v"] = False
    with pytest.raises(Problem) as e:
        a.authenticate(keys.token("ola", kid="rotated-during-outage"))
    assert e.value.status == 503 and e.value.code == "idp-unavailable", e.value.status


def test_persisted_keys_with_keycloaks_real_jwks_shape_serve_a_fresh_process(keys):
    """Keycloak's JWKS always carries an RSA-OAEP key with use=enc beside the signing key."""
    class Store:
        saved = None
        def load(self, issuer): return Store.saved
        def save(self, issuer, k): Store.saved = k
    raw = [enc_key(), keys.jwk]
    make(keys, fetch=lambda u: raw, store=Store()).authenticate(keys.token("ola"))
    assert len(Store.saved) == 2

    def down(url):
        raise OSError("down")
    assert make(keys, fetch=down, store=Store()).authenticate(keys.token("ola")).username == "ola"


def test_unknown_kid_flood_does_not_refetch_per_token(keys):
    calls = []

    def fetch(url):
        calls.append(url)
        return [keys.jwk]
    a = make(keys, fetch=fetch)
    a.authenticate(keys.token("ola"))
    for i in range(50):
        with pytest.raises(Problem):
            a.authenticate(keys.token("x", kid=f"bogus-{i}"))
    assert len(calls) <= 2, f"50 unauthenticated bad-kid tokens made {len(calls)} JWKS fetches"


def test_outage_with_stale_cache_does_not_stall_every_request(keys, capsys):
    """Keycloak hangs (timeout 5 s in _http_fetch; 0.5 s here). A stale cache must still answer fast, in parallel."""
    state = {"t": 0.0, "up": True}
    fetches = []

    def fetch(url):
        fetches.append(1)
        if not state["up"]:
            time.sleep(0.5)
            raise OSError("timed out")
        return [keys.jwk]
    jwks = Jwks(ISSUER, "u", fetch=fetch, clock=lambda: state["t"])
    a = Authenticator(ISSUER, AUDIENCE, jwks)
    a.authenticate(keys.token("ola"))
    state["up"], state["t"] = False, 10_000.0
    fetches.clear()
    tok = keys.token("ola")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(10) as ex:
        list(ex.map(lambda _: a.authenticate(tok), range(10)))
    took = time.perf_counter() - t0
    with capsys.disabled():
        print(f"\n[measure] 10 parallel valid tokens with a stale cache and Keycloak hanging 0.5 s: {took:.2f} s, {len(fetches)} fetch attempts")
    assert len(fetches) <= 1 and took < 1.0, (took, len(fetches))


def test_empty_jwks_answer_does_not_wipe_the_last_good_keys(keys):
    state = {"t": 0.0, "raw": [keys.jwk]}
    a = make(keys, fetch=lambda u: state["raw"], clock=lambda: state["t"])
    a.authenticate(keys.token("ola"))
    state["raw"], state["t"] = [], 10_000.0
    assert a.authenticate(keys.token("ola")).username == "ola"
