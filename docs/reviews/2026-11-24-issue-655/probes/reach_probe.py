"""Measures whether each PyJWT advisory reaches cmapi's token path (#655). Run it with each venv's python:

    PYTHONPATH=<wt>/cmapi/src:<wt>/cmapi/tests/service <venv>/bin/python reach_probe.py

Each vector goes through cmapi's own Authenticator (core/auth.py) and, where cmapi's pre-checks would hide the library's
behaviour, through the library call that cmapi makes (jwt.decode with cmapi's arguments).
"""
from __future__ import annotations

import base64
import http.server
import json
import sys
import threading
import time

import httpx
import jwt
from cryptography.hazmat.primitives import serialization

from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.errors import Problem
from conftest import AUDIENCE, ISSUER, Keys

print(f"PyJWT {jwt.__version__}, httpx {httpx.__version__}, Python {sys.version.split()[0]}")
keys = Keys()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def auth(fetch=None) -> Authenticator:
    return Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=fetch or (lambda u: [keys.jwk]),
                                                clock=lambda: 0.0))


def outcome(fn) -> str:
    try:
        r = fn()
    except Problem as p:
        return f"refused: Problem {p.status} {p.code} ({p.detail})"
    except jwt.PyJWTError as e:
        return f"refused: {type(e).__name__}: {e}"
    except Exception as e:                                  # noqa: BLE001 - the probe reports what escapes
        return f"ESCAPED {type(e).__module__}.{type(e).__name__}: {str(e)[:100]}"
    return f"ACCEPTED: {r!r}"[:160]


def claims(**extra):
    now = int(time.time())
    return {"iss": ISSUER, "aud": [AUDIENCE], "sub": "sub-ola", "iat": now, "exp": now + 300, "preferred_username": "ola",
            "resource_access": {AUDIENCE: {"roles": ["cmapi-requester"]}}, **extra}


# 1. HS/asymmetric confusion (GHSA-ffc3-869f-jxw9 critical; GHSA-p4g4-x82p-q773 DER; GHSA-xgmm-8j9v-c9wx JWK):
# the attacker HMAC-signs with the realm's public key, which the JWKS publishes, mutated so the PEM guard misses it.
pub = keys.private.public_key()
pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
mutated_pem = pem.replace(b"\n", b"\r")                    # CR-only line terminators, one of the advisory's forms


def hs_token(secret: bytes) -> str:
    header = {"alg": "HS256", "kid": keys.kid, "typ": "at+jwt"}
    signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims()).encode())}".encode()
    import hashlib
    import hmac
    return f"{signing_input.decode()}.{b64(hmac.new(secret, signing_input, hashlib.sha256).digest())}"


for name, secret in [("PEM mutated", mutated_pem), ("DER", der), ("JWK JSON", json.dumps(keys.jwk).encode())]:
    tok = hs_token(secret)
    print(f"1 HS confusion, {name}: Authenticator -> {outcome(lambda: auth().authenticate(tok))}")
    # Without cmapi's alg pre-check: the library call cmapi makes, with the key object cmapi passes
    k = auth().jwks.key(keys.kid).key
    print(f"1 HS confusion, {name}: jwt.decode(key object, algorithms=['RS256']) -> "
          f"{outcome(lambda: jwt.decode(tok, k, algorithms=['RS256'], audience=AUDIENCE, issuer=ISSUER))}")
    # The library's own guard, which cmapi never relies on: the public key as the HMAC secret, HS256 allowed
    print(f"1 HS confusion, {name}: jwt.decode(secret, algorithms=['HS256']) [library guard only, not cmapi's call] -> "
          f"{outcome(lambda: jwt.decode(tok, secret, algorithms=['HS256'], audience=AUDIENCE, issuer=ISSUER))}")

# 2. Unknown crit (GHSA-752w-5fwx-jx9f): a token signed by the realm's key whose header lists an extension nobody understands.
crit = jwt.encode(claims(), keys.pem, algorithm="RS256",
                  headers={"kid": keys.kid, "typ": "at+jwt", "crit": ["x-cmapi-unknown"], "x-cmapi-unknown": True})
print(f"2 unknown crit: Authenticator -> {outcome(lambda: auth().authenticate(crit))}")

# 3. Recursion before verification (GHSA-42vr-xj54-vc7v, GHSA-8wjv-2p76-3863): a deeply nested header or payload,
# with no valid signature. cmapi parses the header before verifying (get_unverified_header); the payload only after.
depth = 100_000
nested = b"[" * depth + b"]" * depth
nested_header = f"{b64(b'{\"alg\":\"RS256\",\"kid\":\"' + keys.kid.encode() + b'\",\"x\":' + nested + b'}')}.{b64(json.dumps(claims()).encode())}.{b64(b'sig')}"
nested_payload = f"{b64(json.dumps({'alg': 'RS256', 'kid': keys.kid, 'typ': 'at+jwt'}).encode())}.{b64(b'{\"x\":' + nested + b'}')}.{b64(b'sig')}"
print(f"3 nested header ({len(nested_header)} bytes): Authenticator -> {outcome(lambda: auth().authenticate(nested_header))}")
print(f"3 nested payload ({len(nested_payload)} bytes): Authenticator -> {outcome(lambda: auth().authenticate(nested_payload))}")
for d in (1_000, 5_000, 20_000):
    n = b"[" * d + b"]" * d
    h = f"{b64(b'{\"alg\":\"RS256\",\"kid\":\"' + keys.kid.encode() + b'\",\"x\":' + n + b'}')}.{b64(json.dumps(claims()).encode())}.{b64(b'sig')}"
    print(f"3 nested header depth {d} ({len(h)} bytes): Authenticator -> {outcome(lambda: auth().authenticate(h))}")
# The reference app (examples/local/app.py) calls PyJWKClient.get_signing_key_from_jwt before verifying
client = jwt.PyJWKClient("http://127.0.0.1:9/certs")
print(f"3 nested payload: PyJWKClient.get_signing_key_from_jwt [examples/local/app.py] -> "
      f"{outcome(lambda: client.get_signing_key_from_jwt(nested_payload))}")
print(f"3 nested header: PyJWKClient.get_signing_key_from_jwt [examples/local/app.py] -> "
      f"{outcome(lambda: client.get_signing_key_from_jwt(nested_header))}")


# 4. cmapi's own JWKS fetch (Jwks._http_fetch) against GHSA-9v7f-9g4p-ffgj (redirects) and GHSA-993g-76c3-p5m4 (schemes).
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/attacker")
            self.end_headers()
            return
        body = json.dumps({"keys": [{**keys.jwk, "kid": "attacker"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.hits.append(self.path)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
srv.hits = []
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"
j = Jwks(ISSUER, f"{base}/redirect")
print(f"4 JWKS behind a 302: Jwks._http_fetch -> {outcome(lambda: j._http_fetch(j.url))}; the redirect target was fetched: "
      f"{'/attacker' in srv.hits}")
print(f"4 JWKS behind a 302: Jwks.key -> {outcome(lambda: Jwks(ISSUER, f'{base}/redirect').key('attacker'))}")
for url in ("file:///etc/passwd", "ftp://127.0.0.1/certs", "data:application/json,{\"keys\":[]}"):
    print(f"4 JWKS at {url.split(':')[0]}://: Jwks._http_fetch -> {outcome(lambda: Jwks(ISSUER, url)._http_fetch(url))}")
srv.shutdown()
