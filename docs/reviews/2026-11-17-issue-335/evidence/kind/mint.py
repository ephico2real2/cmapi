"""Throwaway signing key and tokens for the #335 kind proof: writes jwks.json and key.pem into a folder, or mints a token.
Usage: mint.py keys <dir> | mint.py token <dir> <issuer> <audience> <username>"""
import json, sys, time, pathlib
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KID = "cmapi-335-kind"
if sys.argv[1] == "keys":
    d = pathlib.Path(sys.argv[2]); d.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (d / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (d / "key.pem").chmod(0o600)
    jwk = {**jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True), "kid": KID, "use": "sig", "alg": "RS256"}
    (d / "certs").write_text(json.dumps({"keys": [jwk]}))
else:
    d, iss, aud, user = pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
    now = int(time.time())
    claims = {"iss": iss, "aud": [aud, "account"], "sub": f"sub-{user}", "azp": "cmapi-portal", "iat": now, "exp": now + 600,
              "preferred_username": user, "email": f"{user}@ephico2real.com", "given_name": user.title(), "family_name": "Doe",
              "groups": ["/cmapi/app-cmapi-rbac-requester"], "resource_access": {aud: {"roles": ["cmapi-requester"]}},
              "employee_id": "1001"}
    print(jwt.encode(claims, (d / "key.pem").read_bytes(), algorithm="RS256", headers={"kid": KID, "typ": "at+jwt"}))
