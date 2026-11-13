"""Bring realm `cmapi` to the state the chart describes, after the operator's one-shot import
(docs/11, "Existing Keycloak"). Authenticates as the realm's own cmapi-realm-admin service
client (realm-management roles), never as the shared instance's master admin.

What it converges, each step idempotent:
  1. the user profile declares employeeId and middleName (Keycloak 24+ drops undeclared attributes);
  2. the roles the service clients need: cmapi-realm-admin -> realm-admin and cmapi-directory -> view-users
     and query-users on realm-management, and cmapi-automation -> cmapi-onboarding on the audience client;
  3. the groups under /cmapi and their client-role mappings (the import creates them; a later
     change to the mapping reaches an existing realm here);
  4. LDAP federation, read-only, with the group mapper filtered on groupsFilter under /cmapi, and on
     a shared directory only the people usersFilter names, when the bind credential Secret is present
     (CMAPI_LDAP_BIND_DN and CMAPI_LDAP_BIND_PASSWORD);
  5. local test users (ola, amy, opal) with the passwords from Secret cmapi-test-users,
     their attributes and group memberships; nothing is printed but names.

No client of the realm takes the resource owner password grant (RFC 9700, section 2.4; #181): before step 2 the
sync turns it off on each client of an existing realm, and retires the local account bot-user independently of test-user creation.
It also sets the attribute that makes Keycloak write the header `typ: at+jwt` on each client that gets a token for cmapi (#184).
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

RFC9068_HEADER = "access.token.header.type.rfc9068"      # Keycloak's client attribute, OIDCConfigAttributes (26.6.4)

TEST_USERS = [  # username, first, middle, last, employeeId, groups
    ("ola", "Ola", "A", "Adeyemi", "1001", ["app-cmapi-rbac-requester"]),
    ("amy", "Amy", "B", "Lee", "1002", ["app-cmapi-rbac-approver-platform"]),
    ("opal", "Opal", None, "Ng", "1003", ["app-cmapi-rbac-operator"]),
]


class Realm:
    def __init__(self, base: str, realm: str, client_id: str, secret: str, verify: str | bool):
        self.base, self.realm = base.rstrip("/"), realm
        self.http = httpx.Client(timeout=30, verify=verify)
        self.client_id, self.secret = client_id, secret
        self._token: tuple[str, float] | None = None

    def _bearer(self) -> str:
        if self._token and time.time() < self._token[1]:
            return self._token[0]
        r = self.http.post(f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
                           data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.secret})
        if r.status_code != 200:
            sys.exit(f"cannot sign in as {self.client_id} in realm {self.realm}: {r.status_code} {r.text[:200]}")
        body = r.json()
        self._token = (body["access_token"], time.time() + body.get("expires_in", 60) - 20)
        return self._token[0]

    def call(self, method: str, path: str, *, ok: tuple[int, ...] = (200, 201, 204), **kw: Any) -> httpx.Response:
        r = self.http.request(method, f"{self.base}/admin/realms/{self.realm}{path}",
                              headers={"Authorization": f"Bearer {self._bearer()}"}, **kw)
        if r.status_code not in ok:
            sys.exit(f"{method} {path}: {r.status_code} {r.text[:300]}")
        return r

    def get(self, path: str, **kw: Any) -> Any:
        r = self.call("GET", path, ok=(200, 404), **kw)
        return None if r.status_code == 404 else r.json()


def wait_for_realm(base: str, realm: str, verify: str | bool, attempts: int = 90) -> None:
    for i in range(attempts):
        try:
            if httpx.get(f"{base}/realms/{realm}", timeout=10, verify=verify).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(min(2 + i, 10))
    sys.exit(f"realm {realm} did not appear at {base}")


def user_profile(rm: Realm) -> None:
    prof = rm.get("/users/profile")
    names = {a["name"] for a in prof["attributes"]}
    changed = False
    for name, view in (("employeeId", ["admin"]), ("middleName", ["admin", "user"])):
        if name not in names:
            prof["attributes"].append({"name": name, "displayName": name, "multivalued": False,
                                       "permissions": {"view": view, "edit": ["admin"]}})
            changed = True
    if changed:
        rm.call("PUT", "/users/profile", json=prof)
    print(f"user profile: employeeId, middleName {'declared' if changed else 'present'}")


def service_roles(rm: Realm, audience: str) -> None:
    for client_id, role_client, wanted in (("cmapi-realm-admin", "realm-management", ["realm-admin"]),
                                           ("cmapi-directory", "realm-management", ["view-users", "query-users"]),
                                           ("cmapi-automation", audience, ["cmapi-onboarding"])):
        holder = rm.get("/clients", params={"clientId": role_client})[0]
        roles = {x["name"]: x for x in rm.get(f"/clients/{holder['id']}/roles")}
        c = rm.get("/clients", params={"clientId": client_id})
        if not c:
            print(f"client {client_id} absent: skipped")
            continue
        sa = rm.get(f"/clients/{c[0]['id']}/service-account-user")
        have = {x["name"] for x in rm.get(f"/users/{sa['id']}/role-mappings/clients/{holder['id']}") or []}
        missing = [roles[n] for n in wanted if n not in have and n in roles]
        if missing:
            rm.call("POST", f"/users/{sa['id']}/role-mappings/clients/{holder['id']}", json=missing)
        print(f"{client_id}: {role_client} {wanted} {'granted' if missing else 'present'}")


def no_password_grant(rm: Realm) -> None:
    """Turn off the password grant throughout the existing realm, including later pages."""
    changed = []
    first = 0
    while True:
        clients = rm.get("/clients", params={"first": first, "max": 500}) or []
        if not clients:
            break
        for c in clients:
            want_service = c["clientId"] == "cmapi-automation"
            if c.get("directAccessGrantsEnabled") or (want_service and not c.get("serviceAccountsEnabled")):
                c["directAccessGrantsEnabled"] = False
                if want_service:
                    c["serviceAccountsEnabled"] = True
                rm.call("PUT", f"/clients/{c['id']}", json=c)
                changed.append(c["clientId"])
        first += len(clients)
    print(f"password grant: off on each client{' (changed: ' + ', '.join(sorted(changed)) + ')' if changed else ''}")


def access_token_type(rm: Realm) -> None:
    """Each client that gets a token for cmapi writes the JOSE header `typ: at+jwt` (RFC 9068), which core/auth.py requires
    (#184). Those clients are the ones with the client scope cmapi-audience. The import sets the attribute on a new realm;
    this step brings it to a realm that was imported before, and to a client that was added by hand."""
    changed, first = [], 0
    while True:
        clients = rm.get("/clients", params={"first": first, "max": 500}) or []
        if not clients:
            break
        for c in clients:
            attributes = c.get("attributes") or {}
            if "cmapi-audience" in (c.get("defaultClientScopes") or []) and attributes.get(RFC9068_HEADER) != "true":
                c["attributes"] = {**attributes, RFC9068_HEADER: "true"}
                rm.call("PUT", f"/clients/{c['id']}", json=c)
                changed.append(c["clientId"])
        first += len(clients)
    print(f"access token type: at+jwt on each client of cmapi{' (changed: ' + ', '.join(sorted(changed)) + ')' if changed else ''}")


def retire_legacy_bot(rm: Realm) -> None:
    """Disabling a client grant does not disable an enabled local user's browser login."""
    for stale in rm.get("/users", params={"username": "bot-user", "exact": "true"}) or []:
        rm.call("DELETE", f"/users/{stale['id']}")
        print("test user bot-user: removed (the automation client signs in by its service account)")


def groups(rm: Realm, audience: str, mapping: dict[str, list[str]]) -> dict[str, str]:
    api_client = rm.get("/clients", params={"clientId": audience})[0]
    roles = {x["name"]: x for x in rm.get(f"/clients/{api_client['id']}/roles")}
    top = next((g for g in rm.get("/groups", params={"search": "cmapi", "exact": "true"}) if g["name"] == "cmapi"), None)
    if top is None:
        rm.call("POST", "/groups", json={"name": "cmapi"})
        top = next(g for g in rm.get("/groups", params={"search": "cmapi", "exact": "true"}) if g["name"] == "cmapi")
    children = {g["name"]: g["id"] for g in rm.get(f"/groups/{top['id']}/children", params={"max": 100}) or []}
    ids: dict[str, str] = {}
    for name, wanted in mapping.items():
        if name not in children:
            rm.call("POST", f"/groups/{top['id']}/children", json={"name": name})
            children = {g["name"]: g["id"] for g in rm.get(f"/groups/{top['id']}/children", params={"max": 100})}
        gid = children[name]
        ids[name] = gid
        have = {x["name"] for x in rm.get(f"/groups/{gid}/role-mappings/clients/{api_client['id']}") or []}
        missing = [roles[r] for r in wanted if r not in have and r in roles]
        if missing:
            rm.call("POST", f"/groups/{gid}/role-mappings/clients/{api_client['id']}", json=missing)
        extra = [roles[r] for r in have - set(wanted) if r in roles]
        if extra:
            rm.call("DELETE", f"/groups/{gid}/role-mappings/clients/{api_client['id']}", json=extra)
    print(f"groups under /cmapi: {len(mapping)} with their client roles")
    return ids


def _sync_read_someone(r: httpx.Response, expect: int | None = None) -> bool:
    """Read at least one user and failed on none; and with expect, read exactly that many. A users filter makes "at least one"
    too weak: a filter that was not applied reads the whole directory, and one that matches too little still reads someone."""
    if r.status_code != 200:
        return False
    try:
        counts = r.json()
    except ValueError:
        return False
    if not isinstance(counts, dict) or counts.get("failed"):
        return False
    read = counts.get("added", 0) + counts.get("updated", 0)
    return read > 0 if expect is None else read == expect


def ldap(rm: Realm, cfg: dict[str, Any]) -> None:
    bind_dn, bind_pw = os.environ.get("bindDN") or os.environ.get("CMAPI_LDAP_BIND_DN"), \
        os.environ.get("password") or os.environ.get("CMAPI_LDAP_BIND_PASSWORD")
    if not cfg.get("enabled"):
        print("LDAP federation: off in values")
        return
    if not (bind_dn and bind_pw):
        print(f"LDAP federation: NOT configured, Secret {cfg.get('bindSecret', 'cmapi-ldap-bind')} (bindDN, password) is absent")
        if cfg.get("requireSync"):
            sys.exit("LDAP federation is required here and its bind credential is absent")
        return
    realm_info = rm.get("")
    comps = rm.get("/components", params={"type": "org.keycloak.storage.UserStorageProvider"}) or []
    existing = next((c for c in comps if c["name"] == "ldap"), None)
    body = {
        "name": "ldap", "providerId": "ldap", "providerType": "org.keycloak.storage.UserStorageProvider",
        "parentId": realm_info["id"],
        "config": {
            "enabled": ["true"], "vendor": ["other"], "editMode": ["READ_ONLY"], "importEnabled": ["true"],
            "syncRegistrations": ["false"], "authType": ["simple"], "bindDn": [bind_dn], "bindCredential": [bind_pw],
            "connectionUrl": [cfg["connectionUrl"]], "usersDn": [cfg["usersDn"]], "usernameLDAPAttribute": ["uid"],
            "rdnLDAPAttribute": ["uid"], "uuidLDAPAttribute": ["entryUUID"], "userObjectClasses": ["inetOrgPerson"],
            "searchScope": ["1"], "useTruststoreSpi": ["always"], "connectionPooling": ["true"], "pagination": ["false"],
            "cachePolicy": ["MAX_LIFESPAN"], "maxLifespan": ["900000"], "changedSyncPeriod": ["900"], "fullSyncPeriod": ["86400"],
        },
    }
    if cfg.get("usersFilter"):
        body["config"]["customUserSearchFilter"] = [cfg["usersFilter"]]
    if existing is None:
        rm.call("POST", "/components", json=body)
        existing = next(c for c in rm.get("/components", params={"type": "org.keycloak.storage.UserStorageProvider"})
                        if c["name"] == "ldap")
        print("LDAP federation: created (read-only)")
    else:
        # Keycloak keeps a key a PUT leaves out, and removes one sent empty (measured on 26.6.4). So no usersFilter here has to say so, or an earlier filter would stay.
        config = {"customUserSearchFilter": [], **body["config"]}
        rm.call("PUT", f"/components/{existing['id']}", json={**body, "config": config, "id": existing["id"]})
        print("LDAP federation: updated (read-only)")
    mappers = {m["name"]: m for m in rm.get("/components", params={"parent": existing["id"],
                                                                   "type": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"}) or []}

    def mapper(name: str, provider: str, config: dict[str, list[str]]) -> None:
        body = {"name": name, "providerId": provider, "providerType": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper",
                "parentId": existing["id"], "config": config}
        if name in mappers:
            rm.call("PUT", f"/components/{mappers[name]['id']}", json={**body, "id": mappers[name]["id"]})
        else:
            rm.call("POST", "/components", json=body)

    attr = lambda ldap_attr, model, mandatory="false": {"ldap.attribute": [ldap_attr], "user.model.attribute": [model],  # noqa: E731
                                                        "read.only": ["true"], "always.read.value.from.ldap": ["true"],
                                                        "is.mandatory.in.ldap": [mandatory]}
    mapper("username", "user-attribute-ldap-mapper", {**attr("uid", "username", "true"), "always.read.value.from.ldap": ["false"]})
    mapper("email", "user-attribute-ldap-mapper", attr("mail", "email"))
    mapper("first name", "user-attribute-ldap-mapper", attr("givenName", "firstName"))
    mapper("last name", "user-attribute-ldap-mapper", attr("sn", "lastName", "true"))
    # This directory's employee number (docs/11): uidNumber here, employeeNumber in a corporate directory.
    mapper("employee-id", "user-attribute-ldap-mapper", attr(cfg.get("employeeIdAttribute", "employeeNumber"), "employeeId"))
    groups_filter = cfg.get("groupsFilter", "(cn=app-cmapi-rbac-*)")
    mapper("groups", "group-ldap-mapper", {
        "groups.dn": [cfg["groupsDn"]], "groups.ldap.filter": [groups_filter],
        "group.name.ldap.attribute": ["cn"], "group.object.classes": ["groupOfNames"], "membership.ldap.attribute": ["member"],
        "membership.attribute.type": ["DN"], "membership.user.ldap.attribute": ["uid"], "mode": ["READ_ONLY"],
        "user.roles.retrieve.strategy": ["LOAD_GROUPS_BY_MEMBER_ATTRIBUTE"], "groups.path": ["/cmapi"],
        "preserve.group.inheritance": ["false"], "ignore.missing.groups": ["false"], "drop.non.existing.groups.during.sync": ["false"]})
    print(f"LDAP mappers: username, email, first name, last name, employee-id, groups (/cmapi, {groups_filter}); users: {cfg.get('usersFilter', 'everyone in usersDn')}")
    r = rm.call("POST", f"/user-storage/{existing['id']}/sync", params={"action": "triggerFullSync"}, ok=(200, 400, 500))
    print(f"LDAP full sync: {r.status_code} {r.text[:120]}")
    # A deployment that needs federation says so (#96). The status alone is not enough: a directory Keycloak cannot reach answers
    # 200 with zero counts (measured on 26.6.4), so the Job fails unless the sync read at least one user and failed on none, and exactly expectUsers when that is set.
    if cfg.get("requireSync") and not _sync_read_someone(r, cfg.get("expectUsers")):
        sys.exit(f"LDAP full sync did not read the users it should (expected {cfg.get('expectUsers', 'at least one')}): {r.status_code} {r.text[:120]}")


def test_users(rm: Realm, audience: str, group_ids: dict[str, str]) -> None:
    api_client = rm.get("/clients", params={"clientId": audience})[0]
    roles = {x["name"]: x for x in rm.get(f"/clients/{api_client['id']}/roles")}

    def upsert(username: str, body: dict[str, Any], password: str | None, memberships: list[str]) -> None:
        found = rm.get("/users", params={"username": username, "exact": "true"})
        if not found:
            rm.call("POST", "/users", json={**body, "username": username, "enabled": True, "emailVerified": True})
            found = rm.get("/users", params={"username": username, "exact": "true"})
            print(f"user {username}: created")
        else:
            rm.call("PUT", f"/users/{found[0]['id']}", json={**found[0], **body})
            print(f"user {username}: present")
        uid = found[0]["id"]
        if password:
            rm.call("PUT", f"/users/{uid}/reset-password", json={"type": "password", "value": password, "temporary": False})
        for g in memberships:
            if g in group_ids:
                rm.call("PUT", f"/users/{uid}/groups/{group_ids[g]}")

    for username, first, middle, last, emp, memberships in TEST_USERS:
        attrs: dict[str, list[str]] = {"employeeId": [emp]}
        if middle:
            attrs["middleName"] = [middle]
        upsert(username, {"email": f"{username}@ephico2real.com", "firstName": first, "lastName": last, "attributes": attrs},
               os.environ.get(username), memberships)


def main(argv: list[str]) -> None:
    issuer = os.environ["CMAPI_REALM_ISSUER"].rstrip("/")
    base, realm = issuer.rsplit("/realms/", 1)
    admin_base = os.environ.get("CMAPI_REALM_ADMIN_URL") or base
    secret = os.environ["CMAPI_REALM_ADMIN_CLIENT_SECRET"]
    audience = os.environ.get("CMAPI_REALM_AUDIENCE", "cmapi-nonprod")
    verify: str | bool = os.environ.get("CMAPI_CA_BUNDLE") or True
    wait_for_realm(admin_base, realm, verify)
    rm = Realm(admin_base, realm, "cmapi-realm-admin", secret, verify)
    user_profile(rm)
    no_password_grant(rm)
    retire_legacy_bot(rm)
    access_token_type(rm)
    service_roles(rm, audience)
    ids = groups(rm, audience, json.loads(os.environ.get("CMAPI_REALM_GROUPS") or "{}"))
    ldap(rm, json.loads(os.environ.get("CMAPI_REALM_LDAP") or "{}"))
    if os.environ.get("CMAPI_REALM_TEST_USERS", "false") == "true":
        test_users(rm, audience, ids)
    print(f"realm {realm} at {base}: in sync")
