#!/usr/bin/env python3
"""deploy/tests/realm-test.py <realm import YAML>: realm cmapi from the file that ships, on a real Keycloak, the way the RHBK operator's Job runs it (KeycloakRealmImportJobDependentResource.java:96-158):
a second process on the live server's database, --cache=local, --override=false, the placeholders in its environment. Beside it two other realms, whose public keys must not change. Then realm_sync.py, an LDAP
stand-in holding the shipped groups and test users, each test user's token against the owner's table, a person outside the users filter refused, a rerun, the issuer's own answers, and the realm deleted by its own cmapi-realm-admin. Containers cmapi-w1-rt-*, labelled, one port on 127.0.0.1 and checked to be there;
only what this run labelled is removed. Every image by digest. CONTAINER=podman on a Mac, docker in CI. Keycloak's community image: RHBK, its operator and the real directory are what the CRC run proves. Exit 1 on the first wrong answer. Needs pyyaml and httpx. Test values only."""
import base64, hashlib, importlib.util, json, os, secrets, subprocess, sys, tempfile, time
import httpx, yaml

C = os.environ.get("CONTAINER", "docker"); PORT = os.environ.get("RT_PORT", "18190")
# Keycloak 26.6.4 (quay's 26.6 tag on the day of the design): RHBK's 26.6.7 is not on quay.
KC = os.environ.get("KC_IMAGE", "quay.io/keycloak/keycloak@sha256:0aae0de7fca85525f727d3354df17896092de8bb26ae4c12d89c77e5df8cbce4")
PG = "docker.io/library/postgres@sha256:aa6cb33cf4c19c765cefcf48d96176258800870a9a1e930ad126200f9d825139"    # 16-alpine
LDAP = "docker.io/osixia/openldap@sha256:18742e9c449c9c1afe129d3f2f3ee15fb34cc43e5f940a20f3399728f41d7c28"  # 1.5.0
LABEL = "cmapi.test=realm-test"
B = f"http://127.0.0.1:{PORT}"; ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
kri = yaml.safe_load(open(sys.argv[1])); realm = kri["spec"]["realm"]
assert kri["kind"] == "KeycloakRealmImport" and realm["realm"] == "cmapi" and kri["metadata"]["namespace"] == "keycloak"
limit = kri["spec"]["resources"]["limits"]["memory"].replace("Gi", "g").replace("Mi", "m"); cpus = str(kri["spec"]["resources"]["limits"]["cpu"])
vals = {k: secrets.token_urlsafe(24) for k in kri["spec"]["placeholders"]}
LDAP_DIR = os.path.join(ROOT, "examples/cmapi-sso/ldap")
# What each token must hold comes from this table, not from the realm under test.
IDENTITIES = [l.rstrip("\n").split("\t") for l in open(os.path.join(LDAP_DIR, "test-identities.tsv")) if l.strip() and not l.startswith("#")]
TEST_PW = {uid: secrets.token_hex(24) for uid, *_ in IDENTITIES}
fails = []
def check(ok, label):
    print(("  ok   " if ok else "  FAIL ") + label, flush=True)
    if not ok: fails.append(label)
def sh(*a, **k): return subprocess.run(a, capture_output=True, text=True, **k)
def pk(n):
    r = httpx.get(f"{B}/realms/{n}", timeout=5); return r.status_code, hashlib.sha256(r.json().get("public_key", "").encode()).hexdigest() if r.status_code == 200 else r.text
def admin(): return httpx.post(f"{B}/realms/master/protocol/openid-connect/token", data={"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "rt-admin"}).json()["access_token"]
DB = ["-e", "KC_DB=postgres", "-e", "KC_DB_URL=jdbc:postgresql://127.0.0.1:5432/kc", "-e", "KC_DB_USERNAME=kc", "-e", "KC_DB_PASSWORD=kc"]
POD = ["--network", "container:cmapi-w1-rt-pg"]
MARK = ["--label", LABEL]
W = tempfile.mkdtemp(prefix="realm-test.")
def cleanup():
    # Only what this test labelled: a container with one of these names and no label is somebody else's, and `run` below stops on it.
    # One at a time, in rounds: the database owns the network the others join, so it refuses to go first, and ps's order differs between runtimes (podman lists it first, measured).
    for _ in range(3):
        for i in sh(C, "ps", "-a", "-q", "--filter", f"label={LABEL}").stdout.split():
            sh(C, "rm", "-f", i)
try:
    cleanup()
    # One network namespace, as a pod is: the database owns it, and only Keycloak's port is published, to 127.0.0.1.
    sh(C, "run", "-d", "--name", "cmapi-w1-rt-pg", *MARK, "-p", f"127.0.0.1:{PORT}:8080", "-e", "POSTGRES_USER=kc", "-e", "POSTGRES_PASSWORD=kc", "-e", "POSTGRES_DB=kc", PG, check=True)
    bound = sh(C, "port", "cmapi-w1-rt-pg").stdout.split()
    assert bound and all(b.startswith("127.0.0.1:") for b in bound if ":" in b), f"published beyond the loopback: {bound}"
    time.sleep(5)
    sh(C, "run", "-d", "--name", "cmapi-w1-rt-kc", *MARK, *POD, "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=admin", "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD=rt-admin", *DB, KC, "start-dev", "--hostname=https://keycloak.apps-crc.testing", "--http-enabled=true", check=True)
    sh(C, "run", "-d", "--name", "cmapi-w1-rt-ldap", *MARK, *POD, "-e", "LDAP_ORGANISATION=e", "-e", "LDAP_DOMAIN=ephico2real.com", "-e", "LDAP_ADMIN_PASSWORD=rt-ldap", "-e", "LDAP_TLS=false", LDAP, check=True)
    for _ in range(90):
        try:
            if httpx.get(f"{B}/realms/master", timeout=3).status_code == 200: break
        except httpx.HTTPError: pass
        time.sleep(2)
    time.sleep(3)
    ldif = """dn: ou=People,dc=ephico2real,dc=com
objectClass: organizationalUnit
ou: People

dn: ou=Groups,dc=ephico2real,dc=com
objectClass: organizationalUnit
ou: Groups

dn: cn=john.doe,ou=People,dc=ephico2real,dc=com
objectClass: inetOrgPerson
objectClass: posixAccount
cn: john.doe
sn: Doe
uid: john.doe
mail: john.doe@ephico2real.com
uidNumber: 10001
gidNumber: 10000
homeDirectory: /home/john.doe
userPassword: rt-john

dn: cn=app-other,ou=Groups,dc=ephico2real,dc=com
objectClass: groupOfNames
cn: app-other
member: cn=john.doe,ou=People,dc=ephico2real,dc=com
member: cn=cmapi.viewer,ou=People,dc=ephico2real,dc=com

"""
    for uid, number, _, _ in IDENTITIES:
        ldif += f"""
dn: cn={uid},ou=People,dc=ephico2real,dc=com
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: shadowAccount
cn: {uid}
sn: {uid.split(".", 1)[1]}
givenName: cmapi
uid: {uid}
mail: {uid}@ephico2real.com
uidNumber: {number}
gidNumber: 1000
homeDirectory: /home/{uid}
userPassword: {TEST_PW[uid]}
"""
    ldif += "\n" + open(os.path.join(LDAP_DIR, "cmapi-groups.ldif")).read()      # the file that ships, members and all
    r = sh(C, "exec", "-i", "cmapi-w1-rt-ldap", "ldapadd", "-x", "-H", "ldap://127.0.0.1:389", "-D", "cn=admin,dc=ephico2real,dc=com", "-w", "rt-ldap", input=ldif); check(r.returncode == 0, "the LDAP stand-in is seeded")
    for n in ("corp-rt", "inkcast-rt"):
        httpx.post(f"{B}/admin/realms", headers={"Authorization": f"Bearer {admin()}"}, json={"realm": n, "enabled": True}).raise_for_status()
    others = lambda: {n: pk(n) for n in ("master", "corp-rt", "inkcast-rt")}
    before = others(); started = sh(C, "inspect", "cmapi-w1-rt-kc", "--format", "{{.State.StartedAt}} {{.RestartCount}}").stdout
    # issuer answers, exactly what deploy/secrets.sh and crc-guard.py read as absent
    a = httpx.get(f"{B}/realms/cmapi"); check(a.status_code == 404 and a.json() == {"error": "Realm does not exist"}, f"before the import the issuer is Keycloak's own 404: {a.text}")
    path = os.path.join(W, "cmapi-realm.json"); json.dump(realm, open(path, "w")); os.chmod(W, 0o755); os.chmod(path, 0o644)
    def imp():
        return subprocess.run([C, "run", "--rm", "--name", "cmapi-w1-rt-import", *MARK, *POD, f"--memory={limit}", f"--cpus={cpus}", "-v", f"{path}:/mnt/realm-import/cmapi-realm.json:ro", *DB, "-e", "KC_CACHE=local", "-e", "KC_HOSTNAME=https://keycloak.apps-crc.testing", "-e", "KC_HTTP_MANAGEMENT_PORT=9900",
                               *sum((["-e", k] for k in vals), []), KC, "--verbose", "import", f"--file=/mnt/realm-import/cmapi-realm.json", "--override=false"], env={**os.environ, **vals}, capture_output=True, text=True, timeout=300)
    t0 = time.time(); r = imp(); log = r.stdout + r.stderr
    check(r.returncode == 0 and "Realm 'cmapi' imported" in log, f"the import succeeds under its own limits, {limit} and {cpus} CPU, in {time.time() - t0:.0f} s")
    check(not any(v in log for v in vals.values()), "no client secret in the import's log")
    a = httpx.get(f"{B}/realms/cmapi"); check(a.status_code == 200 and a.json()["realm"] == "cmapi", "the live server serves the new realm, with no restart")
    check(others() == before, "the other realms' status and public key are unchanged")
    check(sh(C, "inspect", "cmapi-w1-rt-kc", "--format", "{{.State.StartedAt}} {{.RestartCount}}").stdout == started, "the server did not restart")
    key = pk("cmapi")
    r = imp(); check(r.returncode == 0 and "already exists. Import skipped" in r.stdout + r.stderr, "a second import changes nothing: 'already exists'"); check(pk("cmapi") == key and others() == before, "and no key changed")
    # realm_sync.py: by path, so this test needs httpx and not the whole service
    spec = importlib.util.spec_from_file_location("realm_sync", os.path.join(ROOT, "cmapi/src/cmapi/tools/realm_sync.py")); rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs)
    job = yaml.safe_load(open(os.path.join(os.path.dirname(sys.argv[1]), "20-realm-sync.yaml")))
    env = {e["name"]: e.get("value") for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    ldap = json.loads(env["CMAPI_REALM_LDAP"]); check(ldap.get("requireSync") is True, "the Job requires the sync"); ldap["connectionUrl"] = "ldap://127.0.0.1:389"
    check(ldap.get("usersFilter") == "(uid=cmapi.*)" and ldap.get("expectUsers") == len(IDENTITIES), f"the Job reads only the test users, and exactly {len(IDENTITIES)}")
    env.update(CMAPI_REALM_ADMIN_URL=B, CMAPI_REALM_ADMIN_CLIENT_SECRET=vals["CMAPI_REALM_ADMIN_SECRET"], CMAPI_REALM_LDAP=json.dumps(ldap), bindDN="cn=admin,dc=ephico2real,dc=com", password="rt-ldap", ola="rt-ola", amy="rt-amy", opal="rt-opal")
    env.pop("CMAPI_CA_BUNDLE"); os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        rs.main([]); rs.main([]); check(True, "realm_sync.py twice, exit 0")
    except SystemExit as e:
        check(False, f"realm_sync.py twice, exit 0: {str(e.code)[:200]}")
    # A person signs in as a browser does: the authorization code grant with PKCE through the public client cmapi-docs, the password only to
    # Keycloak's login form (deploy/oidc-login.py). No client takes the password grant (RFC 9700, section 2.4; #181).
    spec = importlib.util.spec_from_file_location("oidc_login", os.path.join(ROOT, "deploy/oidc-login.py")); ol = importlib.util.module_from_spec(spec); spec.loader.exec_module(ol)
    PUBLIC = "https://keycloak.apps-crc.testing/realms/cmapi"
    def login(u, p):
        """The access token, or None with the reason in login.why."""
        try:
            login.why = ""; return ol.login(PUBLIC, "cmapi-docs", "https://cmapi-api.apps-crc.testing/docs/oauth2-redirect", u, p, base=B)["access_token"]
        except ol.LoginError as e:
            login.why = str(e); return None
    part = lambda t, n: json.loads(base64.urlsafe_b64decode(t.split(".")[n] + "=" * (-len(t.split(".")[n]) % 4)))
    claims = lambda t: part(t, 1)
    header = lambda t: part(t, 0)
    def token_of(u, p):
        t = login(u, p)
        return claims(t) if t else None
    def grant(**form): return httpx.post(f"{B}/realms/cmapi/protocol/openid-connect/token", data=form)
    def error_of(r):
        try: return r.json().get("error")
        except ValueError: return f"not JSON: {r.text[:60]}"
    def holds(c, groups, roles):
        return sorted(c.get("groups") or []) == sorted(groups) and sorted(((c.get("resource_access") or {}).get("cmapi-nonprod") or {}).get("roles") or []) == sorted(roles)
    # Each test user through the federation: exactly the table's groups and roles, and nothing the table does not give.
    for uid, number, groups, roles in IDENTITIES:
        want_groups = [] if groups == "-" else ["/cmapi/" + g for g in groups.split(",")]
        want_roles = [] if roles == "-" else roles.split(",")
        c = token_of(uid, TEST_PW[uid])
        check(c is not None, f"{uid} signs in through LDAP federation, by the login form: {login.why}")
        if c:
            check(holds(c, want_groups, want_roles), f"{uid}: groups {sorted(c.get('groups') or [])}, roles {sorted(((c.get('resource_access') or {}).get('cmapi-nonprod') or {}).get('roles') or [])}")
            check(c.get("employee_id") == number and c.get("preferred_username") == uid and c.get("email") == f"{uid}@ephico2real.com", f"{uid}: employee_id from uidNumber, name and mail")
    # RFC 9068: the access token of each client that calls cmapi says typ at+jwt in its JOSE header, which core/auth.py requires (#184).
    t = login("cmapi.requester", TEST_PW["cmapi.requester"])
    check(t and header(t).get("typ") == "at+jwt" and claims(t).get("typ") == "Bearer", f"a person's access token through cmapi-docs: header typ {t and header(t).get('typ')}, claim typ {t and claims(t).get('typ')}")
    c = token_of("cmapi.requester", TEST_PW["cmapi.requester"])
    check(c and c["iss"] == "https://keycloak.apps-crc.testing/realms/cmapi", "the token carries the public issuer, though it was asked for elsewhere")
    check(c and c["aud"] == "cmapi-nonprod", "audience")
    check(login("cmapi.requester", "wrong") is None and "Invalid username or password" in login.why, f"a wrong LDAP password is refused: {login.why}")
    # A person outside the filter: the right password, as LDAP itself says, and no way in.
    r = sh(C, "exec", "cmapi-w1-rt-ldap", "ldapwhoami", "-x", "-H", "ldap://127.0.0.1:389", "-D", "cn=john.doe,ou=People,dc=ephico2real,dc=com", "-w", "rt-john"); check(r.returncode == 0, "john.doe's password is right, as LDAP says")
    check(login("john.doe", "rt-john") is None, "and a person outside usersFilter cannot sign in to this realm")
    # The local users keep working with the new groups.
    for user, pw, want_groups, want_roles in (("ola", "rt-ola", ["/cmapi/app-cmapi-rbac-requester"], ["cmapi-requester"]), ("amy", "rt-amy", ["/cmapi/app-cmapi-rbac-approver-platform"], ["cmapi-approver"]),
                                              ("opal", "rt-opal", ["/cmapi/app-cmapi-rbac-operator"], ["cmapi-operator", "cmapi-approver"])):
        c = token_of(user, pw); check(c and holds(c, want_groups, want_roles), f"the local user {user} has {want_groups} and {want_roles}")
    # The automation client signs in by its service account, and holds cmapi-onboarding and nothing else. It has no group and no employee ID.
    r = grant(grant_type="client_credentials", client_id="cmapi-automation", client_secret=vals["CMAPI_AUTOMATION_SECRET"], scope="openid")
    c = claims(r.json()["access_token"]) if r.status_code == 200 else None
    check(c is not None, f"cmapi-automation signs in with client credentials: {r.status_code}")
    check(c is not None and header(r.json()["access_token"]).get("typ") == "at+jwt", "and its access token has the header typ at+jwt")
    for client, key in (("svc-payments-ci", "CMAPI_SVC_PAYMENTS_CI_SECRET"), ("cmapi-directory", "CMAPI_DIRECTORY_SECRET")):
        x = grant(grant_type="client_credentials", client_id=client, client_secret=vals[key])
        want = "at+jwt" if client == "svc-payments-ci" else "JWT"
        check(x.status_code == 200 and header(x.json()["access_token"]).get("typ") == want, f"{client}: header typ {x.status_code == 200 and header(x.json()['access_token']).get('typ')}, wanted {want}: only a client of cmapi has the attribute")
    check(c and c.get("preferred_username") == "service-account-cmapi-automation" and holds(c, [], ["cmapi-onboarding"]) and c["aud"] == "cmapi-nonprod" and "employee_id" not in c,
          f"its token is a service account's with cmapi-onboarding only: {c and (c.get('preferred_username'), c.get('groups'), c.get('resource_access'), c.get('aud'))}")
    check(grant(grant_type="client_credentials", client_id="cmapi-automation", client_secret="wrong", scope="openid").status_code == 401, "and not with a wrong client secret")
    # No client takes a password on the token endpoint: not with the right password of a real account, with the client's secret or without one.
    listed = [x["clientId"] for x in realm["clients"]]
    for client in sorted(set(listed) | {"admin-cli", "account", "account-console", "security-admin-console", "broker", "realm-management"}):
        secret = next((vals[k] for x in realm["clients"] if x["clientId"] == client and "secret" in x for k in vals if k in x["secret"]), None)
        r = grant(grant_type="password", client_id=client, username="ola", password="rt-ola", scope="openid", **({"client_secret": secret} if secret else {}))
        check(r.status_code in (400, 401) and error_of(r) in ("unauthorized_client", "invalid_client") and "access_token" not in r.text,
              f"{client} takes no password{' with its secret' if secret else ''}: {r.status_code} {error_of(r)}")
    check(not httpx.get(f"{B}/admin/realms/cmapi/users", params={"username": "bot-user", "exact": "true"}, headers={"Authorization": "Bearer " + grant(grant_type="client_credentials", client_id="cmapi-realm-admin", client_secret=vals["CMAPI_REALM_ADMIN_SECRET"]).json()["access_token"]}).json(),
          "the realm has no local account bot-user")
    for _ in range(realm["failureFactor"]):
        login("amy", "wrong")
    time.sleep(1)                      # the protector counts on its own thread
    check(login("amy", "rt-amy") is None, f"after that many wrong guesses even the right password is refused for now: {login.why}")
    check(login("ola", "rt-ola") is not None, f"and no one else is: {login.why}")
    adm = grant(grant_type="client_credentials", client_id="cmapi-realm-admin", client_secret=vals["CMAPI_REALM_ADMIN_SECRET"]).json()["access_token"]; A = {"Authorization": f"Bearer {adm}"}
    # A realm that was imported before #181: the import runs one time, so the sync must bring the change. Put the old state back, as the old
    # import and the old sync made it, then run the sync.
    # The attribute for at+jwt is set to false, not left out: an update of a client removes no attribute (RepresentationToModel.updateClientProperties,
    # Keycloak 26.6.4), and Keycloak reads false as it reads an absent one (#196).
    R = f"{B}/admin/realms/cmapi"
    auto = httpx.get(f"{R}/clients", params={"clientId": "cmapi-automation"}, headers=A).json()[0]
    check(httpx.put(f"{R}/clients/{auto['id']}", headers=A, json={**auto, "directAccessGrantsEnabled": True, "serviceAccountsEnabled": False, "attributes": {**(auto.get("attributes") or {}), "access.token.header.type.rfc9068": "false"}}).status_code == 204
          and httpx.post(f"{R}/users", headers=A, json={"username": "bot-user", "enabled": True, "emailVerified": True, "email": "bot-user@ephico2real.com", "firstName": "Onboarding", "lastName": "Bot", "credentials": [{"type": "password", "value": "rt-bot", "temporary": False}]}).status_code == 201,
          "the old state is back: cmapi-automation takes the password grant and has the at+jwt attribute off, and bot-user exists")
    old = grant(grant_type="password", client_id="cmapi-automation", client_secret=vals["CMAPI_AUTOMATION_SECRET"], username="bot-user", password="rt-bot", scope="openid")
    check(old.status_code == 200, f"and in that state the password grant gives a token, so the next check can fail: {old.status_code}")
    check(old.status_code == 200 and header(old.json()["access_token"]).get("typ") == "JWT", f"and without the attribute Keycloak writes the header typ JWT, so the check after the sync can fail: {old.status_code == 200 and header(old.json()['access_token']).get('typ')}")
    try:
        rs.main([]); check(True, "realm_sync.py on the old state, exit 0")
    except SystemExit as e:
        check(False, f"realm_sync.py on the old state, exit 0: {str(e.code)[:200]}")
    adm = grant(grant_type="client_credentials", client_id="cmapi-realm-admin", client_secret=vals["CMAPI_REALM_ADMIN_SECRET"]).json()["access_token"]; A = {"Authorization": f"Bearer {adm}"}
    old = grant(grant_type="password", client_id="cmapi-automation", client_secret=vals["CMAPI_AUTOMATION_SECRET"], username="ola", password="rt-ola", scope="openid")
    check(old.status_code == 400 and error_of(old) == "unauthorized_client", f"after the sync the password grant is refused: {old.status_code} {error_of(old)}")
    check(not httpx.get(f"{R}/users", params={"username": "bot-user", "exact": "true"}, headers=A).json(), "and bot-user is gone")
    r = grant(grant_type="client_credentials", client_id="cmapi-automation", client_secret=vals["CMAPI_AUTOMATION_SECRET"], scope="openid")
    c = claims(r.json()["access_token"]) if r.status_code == 200 else None
    check(c and holds(c, [], ["cmapi-onboarding"]), f"and the service account is back with cmapi-onboarding: {r.status_code} {c and c.get('resource_access')}")
    check(r.status_code == 200 and header(r.json()["access_token"]).get("typ") == "at+jwt", "and the sync put the header typ at+jwt back")
    check(httpx.delete(f"{B}/admin/realms/corp-rt", headers=A).status_code == 403, "cmapi-realm-admin cannot delete another realm")
    # What requireSync does with the filter, on the real answer: a filter that reads the wrong number of people fails the Job, and no filter at all reads everyone.
    def sync_fails(label):
        os.environ["CMAPI_REALM_LDAP"] = json.dumps(ldap)
        try:
            rs.main([]); check(False, label)
        except SystemExit as e:
            check(bool(e.code), f"{label}: {str(e.code)[:90]}")
    keep = dict(ldap)
    ldap["usersFilter"] = "(uid=*)"; sync_fails("a filter reading more people than the 13 fails the Job")
    ldap["usersFilter"] = "(uid=nobody.*)"; sync_fails("a filter reading nobody fails the Job")
    ldap.clear(); ldap.update(keep); del ldap["usersFilter"], ldap["expectUsers"]; os.environ["CMAPI_REALM_LDAP"] = json.dumps(ldap)
    try:
        rs.main([]); check(login("john.doe", "rt-john") is not None, f"with no usersFilter the realm reads everyone: john.doe signs in, so the filter is what kept him out: {login.why}")
    except SystemExit as e:
        check(False, f"a sync with no usersFilter: {str(e.code)[:120]}")
    # A sync that cannot reach LDAP must fail the Job.
    ldap["connectionUrl"] = "ldap://127.0.0.1:1"; os.environ["CMAPI_REALM_LDAP"] = json.dumps(ldap)
    try:
        rs.main([]); check(False, "a federation that cannot sync fails the Job")
    except SystemExit as e:
        check(bool(e.code), f"a federation that cannot sync fails the Job: {str(e.code)[:60]}")
    d = httpx.delete(f"{B}/admin/realms/cmapi", headers=A); check(d.status_code == 204, "cmapi-realm-admin deletes its own realm, with no master credential")
    a = httpx.get(f"{B}/realms/cmapi"); check(a.status_code == 404 and a.json() == {"error": "Realm does not exist"}, "and the issuer is Keycloak's own 404 again")
    check(others() == before, "the other realms' status and public key are unchanged at the end")
finally:
    cleanup()
    left = sh(C, "ps", "-a", "-q", "--filter", f"label={LABEL}").stdout.split()
    check(not left, f"no container left behind: {left}")
print(f"realm cases failed: {len(fails)}"); sys.exit(1 if fails else 0)
