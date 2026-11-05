"""Builds the ephico2real realm on a local Keycloak through the admin REST API.

Mirrors examples/cmapi-sso/realm/ephico2real.yaml and the v2 "Identity claims" section, without LDAP:
the users are local, with employeeId and middleName set directly. Idempotent: run it again and it
skips what exists.

    python keycloak_setup.py            # Keycloak at http://localhost:8080, admin/admin
"""
from __future__ import annotations

import os
import sys

import httpx

KC = os.environ.get("KC_URL", "http://localhost:8080")
REALM = "ephico2real"
API = "cmapi-nonprod"                       # the instance's resource client (audience)
ROLES = ["cmapi-viewer", "cmapi-requester", "cmapi-approver", "cmapi-operator", "cmapi-admin",
         "cmapi-auditor", "cmapi-approval-relay"]
GROUPS = {"cmapi-payments-requesters": ["cmapi-requester"],
          "cmapi-platform-leads": ["cmapi-approver"],
          "cmapi-platform-operators": ["cmapi-operator", "cmapi-approver"]}
USERS = [  # username, first, middle, last, employeeId, groups
    ("ola", "Ola", "A", "Adeyemi", "1001", ["cmapi-payments-requesters"]),
    ("amy", "Amy", "B", "Lee", "1002", ["cmapi-platform-leads"]),
    ("opal", "Opal", None, "Ng", "1003", ["cmapi-platform-operators"]),
]
PASSWORD = "demo"


def main() -> None:
    tok = httpx.post(f"{KC}/realms/master/protocol/openid-connect/token",
                     data={"grant_type": "password", "client_id": "admin-cli",
                           "username": "admin", "password": "admin"}).json()["access_token"]
    c = httpx.Client(base_url=f"{KC}/admin/realms", headers={"Authorization": f"Bearer {tok}"}, timeout=30)

    def ok(r: httpx.Response) -> httpx.Response:
        if r.status_code >= 400 and r.status_code != 409:
            sys.exit(f"{r.request.method} {r.request.url}: {r.status_code} {r.text}")
        return r

    ok(c.post("", json={"realm": REALM, "enabled": True, "accessTokenLifespan": 300,
                        "displayName": "ephico2real (local)"}))
    r = f"/{REALM}"

    # User Profile: declare the LDAP-mapped attributes, or Keycloak 24+ drops them
    prof = ok(c.get(f"{r}/users/profile")).json()
    names = {a["name"] for a in prof["attributes"]}
    for name, view in (("employeeId", ["admin"]), ("middleName", ["admin", "user"])):
        if name not in names:
            prof["attributes"].append({"name": name, "displayName": name,
                                       "permissions": {"view": view, "edit": ["admin"]}, "multivalued": False})
    ok(c.put(f"{r}/users/profile", json=prof))

    # client scope cmapi-identity: employee_id, middle_name and the groups claim (full paths)
    ok(c.post(f"{r}/client-scopes", json={
        "name": "cmapi-identity", "protocol": "openid-connect",
        "attributes": {"include.in.token.scope": "false"},
        "protocolMappers": [
            {"name": "employee_id", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-attribute-mapper",
             "config": {"user.attribute": "employeeId", "claim.name": "employee_id", "jsonType.label": "String",
                        "access.token.claim": "true", "id.token.claim": "false", "userinfo.token.claim": "true"}},
            {"name": "middle_name", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-attribute-mapper",
             "config": {"user.attribute": "middleName", "claim.name": "middle_name", "jsonType.label": "String",
                        "access.token.claim": "true", "id.token.claim": "true", "userinfo.token.claim": "true"}},
            {"name": "groups", "protocol": "openid-connect", "protocolMapper": "oidc-group-membership-mapper",
             "config": {"claim.name": "groups", "full.path": "true", "access.token.claim": "true",
                        "id.token.claim": "false", "userinfo.token.claim": "true"}}]}))
    scope_id = next(s["id"] for s in ok(c.get(f"{r}/client-scopes")).json() if s["name"] == "cmapi-identity")

    def client(body: dict) -> str:
        ok(c.post(f"{r}/clients", json=body))
        cid = ok(c.get(f"{r}/clients", params={"clientId": body["clientId"]})).json()[0]["id"]
        ok(c.put(f"{r}/clients/{cid}/default-client-scopes/{scope_id}"))
        return cid

    api_id = client({"clientId": API, "bearerOnly": False, "publicClient": False, "secret": "unused",
                     "standardFlowEnabled": False, "directAccessGrantsEnabled": False})
    for role in ROLES:
        ok(c.post(f"{r}/clients/{api_id}/roles", json={"name": role}))
    roles = {x["name"]: x for x in ok(c.get(f"{r}/clients/{api_id}/roles")).json()}

    # cmapi-cli: the public client people sign in with (password grant only for this local demo)
    client({"clientId": "cmapi-cli", "publicClient": True, "directAccessGrantsEnabled": True,
            "standardFlowEnabled": False})
    # svc-payments-ci: a pipeline (client credentials) holding cmapi-requester
    svc_id = client({"clientId": "svc-payments-ci", "publicClient": False, "secret": "svc-secret",
                     "serviceAccountsEnabled": True, "standardFlowEnabled": False})
    svc_user = ok(c.get(f"{r}/clients/{svc_id}/service-account-user")).json()["id"]
    ok(c.post(f"{r}/users/{svc_user}/role-mappings/clients/{api_id}", json=[roles["cmapi-requester"]]))
    # cmapi-directory: the read-only admin client of core/identity/keycloak_admin.py
    dir_id = client({"clientId": "cmapi-directory", "publicClient": False, "secret": "dir-secret",
                     "serviceAccountsEnabled": True, "standardFlowEnabled": False})
    dir_user = ok(c.get(f"{r}/clients/{dir_id}/service-account-user")).json()["id"]
    rm = ok(c.get(f"{r}/clients", params={"clientId": "realm-management"})).json()[0]["id"]
    rm_roles = [x for x in ok(c.get(f"{r}/clients/{rm}/roles")).json() if x["name"] in ("view-users", "query-users")]
    ok(c.post(f"{r}/users/{dir_user}/role-mappings/clients/{rm}", json=rm_roles))

    # groups under /cmapi, each mapped to its client roles
    ok(c.post(f"{r}/groups", json={"name": "cmapi"}))
    parent = next(g for g in ok(c.get(f"{r}/groups")).json() if g["name"] == "cmapi")
    existing = {g["name"]: g["id"] for g in ok(c.get(f"{r}/groups/{parent['id']}/children")).json()}
    for name, rl in GROUPS.items():
        if name not in existing:
            ok(c.post(f"{r}/groups/{parent['id']}/children", json={"name": name}))
    existing = {g["name"]: g["id"] for g in ok(c.get(f"{r}/groups/{parent['id']}/children")).json()}
    for name, rl in GROUPS.items():
        ok(c.post(f"{r}/groups/{existing[name]}/role-mappings/clients/{api_id}", json=[roles[x] for x in rl]))

    for username, first, middle, last, emp, groups in USERS:
        attrs = {"employeeId": [emp]}
        if middle:
            attrs["middleName"] = [middle]
        ok(c.post(f"{r}/users", json={
            "username": username, "enabled": True, "emailVerified": True, "email": f"{username}@ephico2real.com",
            "firstName": first, "lastName": last, "attributes": attrs,
            "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}]}))
        uid = ok(c.get(f"{r}/users", params={"username": username, "exact": "true"})).json()[0]["id"]
        for g in groups:
            ok(c.put(f"{r}/users/{uid}/groups/{existing[g]}"))
    print(f"realm {REALM} ready at {KC}/realms/{REALM}")


if __name__ == "__main__":
    main()
