#!/usr/bin/env python3
"""deploy/tests/realm-test.py <realm import YAML>: realm cmapi from the file that ships, on a real Keycloak, the way the RHBK operator's Job runs it (KeycloakRealmImportJobDependentResource.java:96-158):
a second process on the live server's database, --cache=local, --override=false, the placeholders in its environment. Beside it two other realms, whose public keys must not change. Then realm_sync.py, an LDAP
stand-in, a federated login and its token claims, a rerun, the issuer's own answers, and the realm deleted by its own cmapi-realm-admin. Containers cmapi-w1-rt-*, labelled, one port on 127.0.0.1 and checked to be there;
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

dn: cn=cmapi-requesters,ou=Groups,dc=ephico2real,dc=com
objectClass: groupOfNames
cn: cmapi-requesters
member: cn=john.doe,ou=People,dc=ephico2real,dc=com
"""
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
    env.update(CMAPI_REALM_ADMIN_URL=B, CMAPI_REALM_ADMIN_CLIENT_SECRET=vals["CMAPI_REALM_ADMIN_SECRET"], CMAPI_REALM_LDAP=json.dumps(ldap), bindDN="cn=admin,dc=ephico2real,dc=com", password="rt-ldap", ola="rt-ola", amy="rt-amy", opal="rt-opal", **{"bot-user": "rt-bot"})
    env.pop("CMAPI_CA_BUNDLE"); os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        rs.main([]); rs.main([]); check(True, "realm_sync.py twice, exit 0")
    except SystemExit as e:
        check(False, f"realm_sync.py twice, exit 0: {str(e.code)[:200]}")
    def login(u, p): return httpx.post(f"{B}/realms/cmapi/protocol/openid-connect/token", data={"grant_type": "password", "client_id": "cmapi-automation", "client_secret": vals["CMAPI_AUTOMATION_SECRET"], "username": u, "password": p, "scope": "openid"})
    claims = lambda t: json.loads(base64.urlsafe_b64decode(t.split(".")[1] + "=" * (-len(t.split(".")[1]) % 4)))
    r = login("john.doe", "rt-john"); check(r.status_code == 200, "a login through LDAP federation")
    if r.status_code == 200:
        c = claims(r.json()["access_token"])
        check(c["iss"] == "https://keycloak.apps-crc.testing/realms/cmapi", "the token carries the public issuer, though it was asked for elsewhere")
        check(c["aud"] == "cmapi-nonprod", "audience"); check(c.get("employee_id") == "10001", "employee_id from uidNumber")
        check(c.get("groups") == ["/cmapi/cmapi-requesters"], f"groups, filtered on cmapi-*: {c.get('groups')}"); check("cmapi-requester" in c["resource_access"]["cmapi-nonprod"]["roles"], "the group's role")
    check(login("john.doe", "wrong").status_code == 401 or login("john.doe", "wrong").status_code == 400, "a wrong LDAP password is refused")
    check(login("bot-user", "rt-bot").status_code == 200, "the local bot user signs in")
    adm = httpx.post(f"{B}/realms/cmapi/protocol/openid-connect/token", data={"grant_type": "client_credentials", "client_id": "cmapi-realm-admin", "client_secret": vals["CMAPI_REALM_ADMIN_SECRET"]}).json()["access_token"]; A = {"Authorization": f"Bearer {adm}"}
    check(httpx.delete(f"{B}/admin/realms/corp-rt", headers=A).status_code == 403, "cmapi-realm-admin cannot delete another realm")
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
