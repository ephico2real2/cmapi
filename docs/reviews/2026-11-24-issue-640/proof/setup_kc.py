"""Set up a disposable Keycloak for the #640 proof: per realm, the clients cmapi uses and one user.

Reads the throwaway credentials from the environment only (KC_BOOTSTRAP_ADMIN_PASSWORD, CMAPI_DIR_SECRET,
CMAPI_RA_SECRET) and prints no credential. Prints one line per realm: the name, then the issuer Keycloak serves in
.well-known/openid-configuration.
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import quote

import httpx

BASE = sys.argv[1]
REALMS = json.loads(sys.argv[2])
http = httpx.Client(base_url=BASE, timeout=30)


def admin_token() -> str:
    r = http.post("/realms/master/protocol/openid-connect/token",
                  data={"grant_type": "password", "client_id": "admin-cli", "username": "admin",
                        "password": os.environ["KC_BOOTSTRAP_ADMIN_PASSWORD"]})
    r.raise_for_status()
    return r.json()["access_token"]


H = {"Authorization": f"Bearer {admin_token()}"}


def ok(r: httpx.Response) -> httpx.Response:
    if r.status_code >= 300:
        sys.exit(f"{r.request.method} {r.request.url.raw_path!r}: {r.status_code} {r.text[:300]}")
    return r


def client(seg: str, client_id: str, secret: str | None, roles: list[str] = ()) -> None:
    rep = {"clientId": client_id, "enabled": True, "publicClient": False, "standardFlowEnabled": False,
           "directAccessGrantsEnabled": False, "serviceAccountsEnabled": secret is not None}
    if secret:
        rep["secret"] = secret
    ok(http.post(f"/admin/realms/{seg}/clients", json=rep, headers=H))
    if not roles:
        return
    cid = ok(http.get(f"/admin/realms/{seg}/clients", params={"clientId": client_id}, headers=H)).json()[0]["id"]
    rm = ok(http.get(f"/admin/realms/{seg}/clients", params={"clientId": "realm-management"}, headers=H)).json()[0]["id"]
    sa = ok(http.get(f"/admin/realms/{seg}/clients/{cid}/service-account-user", headers=H)).json()["id"]
    want = [x for x in ok(http.get(f"/admin/realms/{seg}/clients/{rm}/roles", headers=H)).json() if x["name"] in roles]
    ok(http.post(f"/admin/realms/{seg}/users/{sa}/role-mappings/clients/{rm}", json=want, headers=H))


for name in REALMS:
    seg = quote(name, safe="")                       # the admin API names the realm as one path segment
    ok(http.post("/admin/realms", json={"realm": name, "enabled": True}, headers=H))
    prof = ok(http.get(f"/admin/realms/{seg}/users/profile", headers=H)).json()
    prof["unmanagedAttributePolicy"] = "ENABLED"     # keep employeeId without declaring it (realm_sync declares it later)
    ok(http.put(f"/admin/realms/{seg}/users/profile", json=prof, headers=H))
    client(seg, "cmapi-directory", os.environ["CMAPI_DIR_SECRET"], ["view-users"])
    client(seg, "cmapi-realm-admin", os.environ["CMAPI_RA_SECRET"], ["realm-admin"])
    client(seg, "cmapi-automation", os.environ["CMAPI_RA_SECRET"] + "-automation")
    client(seg, "cmapi-nonprod", None)
    aud = ok(http.get(f"/admin/realms/{seg}/clients", params={"clientId": "cmapi-nonprod"}, headers=H)).json()[0]["id"]
    ok(http.post(f"/admin/realms/{seg}/clients/{aud}/roles", json={"name": "cmapi-onboarding"}, headers=H))
    ok(http.post(f"/admin/realms/{seg}/users", headers=H, json={
        "username": "ola", "email": "ola@example.test", "firstName": "Ola", "lastName": "Adeyemi", "enabled": True,
        "emailVerified": True, "attributes": {"employeeId": ["1001"]}}))
    issuer = ok(http.get(f"/realms/{seg}/.well-known/openid-configuration")).json()["issuer"]
    print(json.dumps({"realm": name, "issuer": issuer}, ensure_ascii=False))
