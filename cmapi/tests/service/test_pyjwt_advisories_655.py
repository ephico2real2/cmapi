"""The PyJWT advisories that reach cmapi's token path, measured on PyJWT 2.10.1 and 2.15.1 (#655).

Two reach it: an unknown `crit` header (GHSA-752w-5fwx-jx9f) was accepted, and a header nested past CPython's JSON depth
guard let RecursionError escape `jwt.get_unverified_header` (the class of GHSA-8wjv-2p76-3863 and GHSA-42vr-xj54-vc7v), so an
unauthenticated request was HTTP 500, not 401. Both tests fail on 2.10.1 and pass on 2.15.1.

The others do not reach it, and the guards below keep it that way: cmapi refuses any alg but RS256 before PyJWT sees the
token and passes the decoder a key object with algorithms=["RS256"] (the HS/asymmetric confusion of GHSA-ffc3-869f-jxw9,
GHSA-p4g4-x82p-q773 and GHSA-xgmm-8j9v-c9wx), and its own JWKS fetch is httpx, which follows no redirect and speaks only http
and https (GHSA-9v7f-9g4p-ffgj, GHSA-993g-76c3-p5m4 are PyJWKClient's, which cmapi does not use). The guards pass on both.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.server
import json
import threading
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from cmapi.core import auth as auth_module
from cmapi.core.auth import AUTH_FAILURES, Authenticator, Jwks, caller_dependency, oauth2_scheme
from cmapi.core.errors import Problem
from conftest import AUDIENCE, ISSUER, Keys

# CPython's JSON decoder raises RecursionError from about 10,000 levels (measured: 9,997 on Python 3.12.14). 100,000 is past
# it on any build, and still refused by 2.15.1 as a DecodeError.
DEPTH = 100_000


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make(keys: Keys) -> Authenticator:
    return Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=lambda url: [keys.jwk],
                                                clock=lambda: 0.0))


def claims() -> dict:
    now = int(time.time())
    return {"iss": ISSUER, "aud": [AUDIENCE], "sub": "sub-ola", "iat": now, "exp": now + 300, "preferred_username": "ola",
            "resource_access": {AUDIENCE: {"roles": ["cmapi-requester"]}}}


def nested_header_token(kid: str) -> str:
    """No valid signature: the header is parsed before anything is verified."""
    header = b'{"alg":"RS256","kid":"' + kid.encode() + b'","x":' + b"[" * DEPTH + b"]" * DEPTH + b"}"
    return f"{b64(header)}.{b64(json.dumps(claims()).encode())}.{b64(b'not-a-signature')}"


def test_a_token_with_an_unknown_critical_extension_is_refused(keys):
    """RFC 7515, section 4.1.11: "If any of the listed extension Header Parameters are not understood and supported by the
    recipient, then the JWS is invalid." The token is signed by the realm's own key, so only the crit list is wrong."""
    token = jwt.encode(claims(), keys.pem, algorithm="RS256",
                       headers={"kid": keys.kid, "typ": "at+jwt", "crit": ["x-cmapi-unknown"], "x-cmapi-unknown": True})
    assert make(keys).authenticate(keys.token("ola")).username == "ola"     # the same key and claims, without crit, pass
    with pytest.raises(Problem) as e:
        make(keys).authenticate(token)
    assert (e.value.status, e.value.code) == (401, "unauthenticated")


def test_a_deeply_nested_header_is_401_and_no_recursion_error_escapes(keys):
    with pytest.raises(Problem) as e:
        make(keys).authenticate(nested_header_token(keys.kid))
    assert (e.value.status, e.value.code, e.value.detail) == (401, "unauthenticated", "Invalid token")


def test_a_deeply_nested_header_is_401_over_http_not_500(keys):
    """Through cmapi's bearer dependency in a FastAPI app: on PyJWT 2.10.1 this was HTTP 500 (measured, also over uvicorn
    with httptools at 26,727 bytes of Authorization header)."""
    app = FastAPI()
    app.state.auth = make(keys)

    @app.exception_handler(Problem)
    async def problem(request: Request, p: Problem):
        return JSONResponse({"code": p.code}, status_code=p.status)

    @app.get("/who")
    def who(caller=Depends(caller_dependency(oauth2_scheme(ISSUER)))):
        return {"sub": caller.sub}

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/who", headers={"Authorization": f"Bearer {nested_header_token(keys.kid)}"})
    assert (r.status_code, r.json()) == (401, {"code": "unauthenticated"})


def hs256_signed_with(secret: bytes, kid: str) -> str:
    header = {"alg": "HS256", "kid": kid, "typ": "at+jwt"}
    signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims()).encode())}"
    return f"{signing_input}.{b64(hmac.new(secret, signing_input.encode(), hashlib.sha256).digest())}"


def public_key_forms(keys: Keys) -> dict[str, bytes]:
    """The realm's public key, which its JWKS publishes, in the forms that PyJWT 2.10.1's HMAC guard missed (measured)."""
    pub = keys.private.public_key()
    pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {"PEM with CR-only line ends (GHSA-ffc3-869f-jxw9)": pem.replace(b"\n", b"\r"),
            "DER (GHSA-p4g4-x82p-q773)": pub.public_bytes(serialization.Encoding.DER,
                                                          serialization.PublicFormat.SubjectPublicKeyInfo),
            "JWK JSON (GHSA-xgmm-8j9v-c9wx)": json.dumps(keys.jwk).encode()}


@pytest.mark.parametrize("form", ["PEM with CR-only line ends (GHSA-ffc3-869f-jxw9)", "DER (GHSA-p4g4-x82p-q773)",
                                  "JWK JSON (GHSA-xgmm-8j9v-c9wx)"])
def test_an_hs256_token_keyed_with_the_public_key_is_refused_before_decoding(keys, form, monkeypatch):
    """Guard (passes on 2.10.1 too): the alg check refuses the forgery before PyJWT is asked to verify it."""
    decoded = []
    monkeypatch.setattr(auth_module.jwt, "decode", lambda *a, **kw: decoded.append(kw))
    before = AUTH_FAILURES.labels("algorithm")._value.get()
    with pytest.raises(Problem) as e:
        make(keys).authenticate(hs256_signed_with(public_key_forms(keys)[form], keys.kid))
    assert e.value.status == 401 and e.value.detail == "Invalid token: unsupported algorithm"
    assert AUTH_FAILURES.labels("algorithm")._value.get() == before + 1 and decoded == []


def test_the_decoder_is_given_a_key_object_and_rs256_alone(keys, monkeypatch):
    """Guard (passes on 2.10.1 too): what makes the confusion unreachable at the decoder as well: no HMAC algorithm is
    allowed, and the key is the RSA public key object, never bytes that an HMAC algorithm could take as a secret."""
    seen = {}
    real = jwt.decode

    def spy(token, key, **kw):
        seen.update(key=key, **kw)
        return real(token, key, **kw)

    monkeypatch.setattr(auth_module.jwt, "decode", spy)
    make(keys).authenticate(keys.token("ola"))
    assert seen["algorithms"] == ["RS256"]
    assert isinstance(seen["key"], type(keys.private.public_key())) and not isinstance(seen["key"], (bytes, str))


class _Keycloak(http.server.BaseHTTPRequestHandler):
    """/certs redirects to /attacker, which serves a JWKS; every path asked for is recorded."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.paths.append(self.path)
        if self.path == "/certs":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/attacker")
            self.end_headers()
            return
        body = json.dumps({"keys": [self.server.jwk]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def redirecting_keycloak(keys):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Keycloak)
    server.paths, server.jwk = [], {**keys.jwk, "kid": "attacker"}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def test_the_jwks_fetch_follows_no_redirect(keys, redirecting_keycloak):
    """Guard (passes on 2.10.1 too): GHSA-9v7f-9g4p-ffgj is PyJWKClient following redirects. cmapi's own fetch, httpx,
    follows none, so a redirected JWKS never becomes trusted key material."""
    port = redirecting_keycloak.server_port
    jwks = Jwks(ISSUER, f"http://127.0.0.1:{port}/certs", clock=lambda: 0.0)
    with pytest.raises(Problem) as e:
        jwks.key("attacker")
    assert e.value.status == 503 and redirecting_keycloak.paths == ["/certs"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://127.0.0.1/certs", 'data:application/json,{"keys":[]}'])
def test_the_jwks_fetch_speaks_only_http_and_https(url):
    """Guard (passes on 2.10.1 too): GHSA-993g-76c3-p5m4 is PyJWKClient opening any urllib scheme. httpx refuses them."""
    import httpx

    with pytest.raises(httpx.UnsupportedProtocol):
        Jwks(ISSUER, url)._http_fetch(url)
