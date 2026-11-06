#!/usr/bin/env python3
"""deploy/tests/crc-guard-test.py [<crc-guard.py>] [--no-mutants]: deploy/crc-guard.py on a stub oc and a local TLS server, each thing it claims it can stop on, then the same cases on
mutants of the guard: a mutant that survives is a claim its test cannot fail on. No cluster. Standard library and openssl only."""
import http.server, json, os, shutil, ssl, stat, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = next((a for a in sys.argv[1:] if not a.startswith("--")), os.path.join(HERE, "..", "crc-guard.py"))
W = tempfile.mkdtemp(prefix="crc-guard-test.")
STATE = os.path.join(W, "state.json")
ARGV = os.path.join(W, "argv.log")
REALMS = ("master", "corp", "inkcast-prod", "inkcast-staging", "tutorial")
OC = r'''#!/usr/bin/env python3
import json,os,sys
s=json.load(open(os.environ["STUB_STATE"])); a=sys.argv[1:]
open(os.environ["STUB_ARGV"],"a").write(" ".join(a)+"\n")
def out(o): print(json.dumps(o)); sys.exit(0)
if a[:2]==["whoami","--show-server"]: print(s["server"]); sys.exit(0)
if a==["whoami"]: print(s["user"]); sys.exit(0)
if a==["config","current-context"]: print(s["context"]); sys.exit(0)
if a[:2]==["describe","node"]: print("Allocated resources:\n  Resource  Requests  Limits\n  cpu  1m (0%%) 2m (0%%)\n  memory  %dMi (79%%)  9862Mi (50%%)"%s["requests_mi"]); sys.exit(0)
if a[:3]==["get","node","crc"]: out({"status":{"allocatable":{"memory":"%dMi"%s["allocatable_mi"]}}})
if a[:2]==["get","ns"]: sys.exit(0)
if a[:2]==["get","keycloakrealmimport"] and "cmapi" not in a: out({"items":s["imports"]})
if a[:3]==["get","keycloakrealmimport","cmapi"]:
    if s.get("our_import") is None: sys.exit(0)
    out(s["our_import"])
if a[:2]==["get","keycloak"]: out({"metadata":{"generation":s["cr_generation"]}})
if a[:2]==["get","pod"]: out(s["pods"][a[2]])
if a[:2]==["get","pods"]: out({"items":s["import_pods"]})
if a[:2]==["get","job"]: sys.exit(0)
if a[0]=="delete":
    s["our_import"]=None; json.dump(s,open(os.environ["STUB_STATE"],"w")); sys.exit(0)
print("stub: unhandled",a,file=sys.stderr); sys.exit(3)
'''


def base_state():
    pod = lambda uid: {"metadata": {"uid": uid}, "status": {"containerStatuses": [{"ready": True, "restartCount": 1, "state": {"running": {"startedAt": "2026-11-05T20:17:08Z"}}}]}}
    return {"server": "https://api.crc.testing:6443", "user": "kube:admin", "context": "default/api-crc-testing:6443/kubeadmin", "requests_mi": 15525, "allocatable_mi": 19543, "cr_generation": 4,
            "imports": [{"metadata": {"name": n, "uid": "u-" + n, "creationTimestamp": "2026-10-28T00:00:00Z", "generation": 1},
                         "spec": {"realm": {"realm": n}}, "status": {"conditions": [{"type": "Done", "status": "True"}]}} for n in REALMS[1:]],
            "pods": {"keycloak-0": pod("k0"), "postgres-0": pod("p0")}, "our_import": None, "import_pods": [],
            "http": {n: [200, json.dumps({"realm": n, "public_key": "key-" + n})] for n in REALMS} | {"cmapi": [404, '{"error":"Realm does not exist"}']}}


def save(s):
    json.dump(s, open(STATE, "w"))


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        s = json.load(open(STATE))
        code, body = s["http"].get(self.path.rsplit("/", 1)[-1], [404, '{"error":"Realm does not exist"}'])
        if code == "short":                                 # a server going down: the answer stops before its length
            self.send_response(200); self.send_header("Content-Length", "1000"); self.end_headers(); self.wfile.write(b"{"); self.wfile.flush(); self.close_connection = True
            return
        if code == "garbage":                               # not HTTP at all
            self.wfile.write(b"not http\r\n\r\n"); self.wfile.flush(); self.close_connection = True
            return
        self.send_response(code); self.end_headers(); self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


def tls_server():
    sh = lambda *a: subprocess.run(a, check=True, capture_output=True, cwd=W)
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt", "-subj", "/CN=test CA", "-days", "2")
    sh("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "s.key", "-out", "s.csr", "-subj", "/CN=localhost")
    open(os.path.join(W, "san"), "w").write("subjectAltName=DNS:localhost\n")
    sh("openssl", "x509", "-req", "-in", "s.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-out", "s.crt", "-days", "2", "-extfile", "san")
    sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "o.key", "-out", "other.crt", "-subj", "/CN=other", "-days", "2")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(os.path.join(W, "s.crt"), os.path.join(W, "s.key"))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


PORT = tls_server()
open(os.path.join(W, "oc"), "w").write(OC); os.chmod(os.path.join(W, "oc"), 0o755)
os.mkdir(os.path.join(W, "bin"))
KIND = os.path.join(W, "bin", "kind")
open(KIND, "w").write('#!/bin/sh\n[ -z "$STUB_KIND" ] || echo "$STUB_KIND"\n'); os.chmod(KIND, 0o755)
ENV = {**os.environ, "CMAPI_OC": os.path.join(W, "oc"), "STUB_STATE": STATE, "STUB_ARGV": ARGV, "CMAPI_CRC_CA": os.path.join(W, "ca.crt"),
       "CMAPI_KEYCLOAK_URL": f"https://localhost:{PORT}", "PATH": os.path.join(W, "bin") + ":" + os.environ["PATH"],
       "CMAPI_GUARD_POLL": "0.1", "CMAPI_GUARD_REPORT_AFTER": "0.5", "CMAPI_GUARD_SCHEDULE_DEADLINE": "0.4", "CMAPI_GUARD_RUN_DEADLINE": "0.4"}


def run(guard, *args, **env):
    # A guard that never returns is a wrong answer here, not a crash of the test.
    try:
        return subprocess.run([sys.executable, guard, *args], env={**ENV, **env}, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")


IMPORT_OK = """apiVersion: k8s.keycloak.org/v2beta1
kind: KeycloakRealmImport
metadata:
  name: cmapi
  namespace: keycloak
spec:
  keycloakCRName: keycloak
  realm:
    realm: cmapi
    enabled: true
"""


def cases(guard):
    """Yields (label, passed)."""
    save(base_state()); open(ARGV, "w").close()
    # the three answers of the issuer
    yield "issuer: Keycloak's 404 is absent", run(guard, "issuer").returncode == 10
    s = base_state(); s["http"]["cmapi"] = [200, '{"realm":"cmapi","public_key":"k"}']; save(s)
    yield "issuer: a 200 with the realm is present", run(guard, "issuer").returncode == 0
    for label, answer in (("a router's 503", [503, "<html>down</html>"]), ("a router's 404", [404, "<html>nope</html>"]), ("a JSON 404 that is not Keycloak's", [404, '{"error":"HTTP 404 Not Found"}']), ("a 200 for another realm", [200, '{"realm":"corp"}'])):
        s["http"]["cmapi"] = answer; save(s)
        yield f"issuer: {label} is neither", run(guard, "issuer").returncode == 20
    save(base_state())
    yield "issuer: a certificate from another CA is neither", run(guard, "issuer", CMAPI_CRC_CA=os.path.join(W, "other.crt")).returncode == 20
    yield "no CA named: it stops, TLS is never off", run(guard, "issuer", CMAPI_CRC_CA="").returncode != 0 and run(guard, "issuer", CMAPI_CRC_CA="").returncode != 10
    yield "issuer: nothing listening is neither", run(guard, "issuer", CMAPI_KEYCLOAK_URL="https://localhost:9").returncode == 20
    for label, answer in (("an answer cut short", ["short", ""]), ("an answer that is not HTTP", ["garbage", ""]), ("JSON that is not an object", [200, '["cmapi"]'])):
        s = base_state(); s["http"]["cmapi"] = answer; save(s)
        r = run(guard, "issuer"); yield f"issuer: {label} is neither, with no traceback", r.returncode == 20 and "Traceback" not in r.stderr
    save(base_state())
    # snapshot and compare, each field the owner named
    a = os.path.join(W, "a.json"); b = os.path.join(W, "b.json")
    r = run(guard, "snapshot", a)
    yield "snapshot succeeds", r.returncode == 0
    if r.returncode:
        return
    snap = json.load(open(a)); yield "snapshot names every realm", set(snap["realms"]) >= set(REALMS)
    yield "snapshot holds no key material, only its hash", "key-corp" not in open(a).read()
    run(guard, "snapshot", b); yield "two snapshots compare equal", run(guard, "compare", a, b).returncode == 0
    def changed(mut):
        s = base_state(); mut(s); save(s); r = run(guard, "snapshot", b)
        return r.returncode != 0 or run(guard, "compare", a, b).returncode == 1
    mutations = {
        "a realm's public key": lambda s: s["http"]["corp"].__setitem__(1, json.dumps({"realm": "corp", "public_key": "another"})),
        "a realm's status": lambda s: s["http"]["inkcast-prod"].__setitem__(0, 500),
        "a realm gone": lambda s: s["http"]["tutorial"].__setitem__(0, 404),
        "an import's uid": lambda s: s["imports"][0]["metadata"].__setitem__("uid", "x"),
        "an import's creationTimestamp": lambda s: s["imports"][1]["metadata"].__setitem__("creationTimestamp", "x"),
        "an import's Done": lambda s: s["imports"][2]["status"]["conditions"][0].__setitem__("status", "False"),
        "an import gone": lambda s: s["imports"].pop(),
        "keycloak-0's uid": lambda s: s["pods"]["keycloak-0"]["metadata"].__setitem__("uid", "x"),
        "keycloak-0's start": lambda s: s["pods"]["keycloak-0"]["status"]["containerStatuses"][0]["state"]["running"].__setitem__("startedAt", "x"),
        "keycloak-0's restart count": lambda s: s["pods"]["keycloak-0"]["status"]["containerStatuses"][0].__setitem__("restartCount", 2),
        "postgres-0's restart count": lambda s: s["pods"]["postgres-0"]["status"]["containerStatuses"][0].__setitem__("restartCount", 2),
        "the Keycloak CR's generation": lambda s: s.__setitem__("cr_generation", 5),
    }
    for label, m in mutations.items():
        yield f"compare stops on {label}", changed(m)
    # our own import does not count as a difference
    s = base_state(); s["imports"].append({"metadata": {"name": "cmapi", "uid": "o", "creationTimestamp": "n", "generation": 1}, "spec": {"realm": {"realm": "cmapi"}}, "status": {}}); save(s); run(guard, "snapshot", b)
    yield "our own import is not a difference", run(guard, "compare", a, b).returncode == 0
    # headroom
    save(base_state())
    yield "headroom 4018 with 768 passes", run(guard, "headroom", "--needs", "768").returncode == 0
    yield "headroom: exactly the stop line passes", run(guard, "headroom", "--needs", str(4018 - 2048)).returncode == 0
    yield "headroom: one over stops", run(guard, "headroom", "--needs", str(4018 - 2048 + 1)).returncode == 1
    s = base_state(); s["requests_mi"] = 17600; save(s)
    yield "headroom under 2 GiB stops with nothing needed", run(guard, "headroom", "--needs", "0").returncode == 1
    # preflight
    save(base_state())
    yield "preflight passes", run(guard, "preflight", "--needs", "768", STUB_KIND="").returncode == 0
    yield "preflight stops on a kind cluster", run(guard, "preflight", STUB_KIND="cmapi-test").returncode == 1
    s = base_state(); s["server"] = "https://127.0.0.1:6443"; save(s)
    yield "preflight stops on another cluster", run(guard, "preflight", STUB_KIND="").returncode == 1
    for user in ("kube:admin", "kubeadmin"):
        s = base_state(); s["user"] = user; save(s)
        yield f"preflight passes for the principal {user}", run(guard, "preflight", STUB_KIND="").returncode == 0
    for label, field, value in (("another user", "user", "system:serviceaccount:cmapi:cmapi-api"), ("a developer", "user", "developer"),
                                ("another context's user", "context", "default/api-crc-testing:6443/developer"), ("another cluster's context", "context", "kind-cmapi-test"),
                                ("a context on another server", "context", "default/api-other-testing:6443/kubeadmin")):
        s = base_state(); s[field] = value; save(s)
        yield f"preflight stops on {label}", run(guard, "preflight", STUB_KIND="").returncode == 1
    save(base_state())
    yield "preflight stops when kind cannot be run, with a reason", (lambda r: r.returncode == 1 and "STOP" in r.stderr)(run(guard, "preflight", STUB_KIND="", PATH="/nonexistent"))
    yield "preflight stops when oc cannot be run, with a reason", (lambda r: r.returncode == 1 and "STOP" in r.stderr)(run(guard, "preflight", STUB_KIND="", CMAPI_OC="/nonexistent/oc"))
    s = base_state(); s["pods"]["keycloak-0"]["status"]["containerStatuses"][0]["ready"] = False; save(s)
    yield "preflight stops on an unready Keycloak", run(guard, "preflight", STUB_KIND="").returncode == 1
    # the import file
    f = os.path.join(W, "import.yaml")
    def imp(text):
        open(f, "w").write(text); return run(guard, "check-import", f).returncode
    yield "the import file passes", imp(IMPORT_OK) == 0
    yield "the file that ships passes", run(guard, "check-import", os.path.join(HERE, "..", "manifests", "environments", "crc", "realm", "10-realm-import.yaml")).returncode == 0
    for label, text in (("realm corp", IMPORT_OK.replace("    realm: cmapi", "    realm: corp")), ("name corp", IMPORT_OK.replace("  name: cmapi", "  name: corp")),
                        ("another namespace", IMPORT_OK.replace("namespace: keycloak", "namespace: inkcast")), ("another Keycloak CR", IMPORT_OK.replace("keycloakCRName: keycloak", "keycloakCRName: other")),
                        ("a second document", IMPORT_OK + "---\napiVersion: v1\nkind: Secret\n"), ("an id of another realm", IMPORT_OK.replace("    enabled: true", "    id: corp\n    enabled: true")),
                        ("two realm lines", IMPORT_OK.replace("    enabled: true", "    realm: cmapi\n    enabled: true"))):
        yield f"the import file stops on {label}", imp(text) == 1
    # the watch
    save(base_state()); run(guard, "snapshot", a)
    log = os.path.join(W, "w.log"); stop = os.path.join(W, "stop")
    def watch(mut, seconds=1.2):
        for x in (log, log + ".done", stop):
            if os.path.exists(x): os.unlink(x)
        s = base_state(); mut(s); save(s)
        p = subprocess.Popen([sys.executable, guard, "watch", log, stop, a], env=ENV, stdout=subprocess.PIPE, text=True)
        time.sleep(seconds); open(log + ".done", "w").close(); out, _ = p.communicate(timeout=20)
        return p.returncode, open(log).read(), out
    rc, text, _ = watch(lambda s: None, 0.5)
    yield "the watch stays quiet when all is well", rc == 0 and "BREACH" not in text and not os.path.exists(stop)
    yield "the watch's lines are timestamped", text.startswith("20") and "realms {" in text
    rc, text, out = watch(lambda s: s["http"]["corp"].__setitem__(0, 503))
    yield "a realm's 503 stops the run", rc == 3 and os.path.exists(stop) and "BREACH corp=503" in text
    yield "still down at the bound: report to the owner", "REPORT TO THE OWNER NOW" in text and "REPORT TO THE OWNER NOW" in out
    # The worst moment for the watch to die: Keycloak going down, an answer cut short, oc unable to answer. It logs on, so the outage's length is on record.
    rc, text, _ = watch(lambda s: s["http"].__setitem__("corp", ["short", ""]))
    yield "an answer cut short stops the run, and the watch lives", rc == 3 and "BREACH corp=0" in text and "watch ended rc=3" in text
    rc, text, _ = watch(lambda s: s["http"].__setitem__("corp", ["garbage", ""]))
    yield "an answer that is not HTTP stops the run, and the watch lives", rc == 3 and "BREACH corp=0" in text and "watch ended rc=3" in text
    rc, text, _ = watch(lambda s: s["pods"].__setitem__("keycloak-0", {"metadata": {}}))
    yield "an unreadable keycloak-0 stops the run, and the watch lives", rc == 3 and "keycloak-0 unreadable" in text and "watch ended rc=3" in text
    rc, text, _ = watch(lambda s: s["http"]["corp"].__setitem__(1, json.dumps({"realm": "corp", "public_key": "x"})))
    yield "a changed key stops the run", rc == 3 and "public key changed" in text
    rc, text, _ = watch(lambda s: s["pods"]["keycloak-0"]["status"]["containerStatuses"][0].__setitem__("restartCount", 2))
    yield "a restart stops the run", rc == 3 and "keycloak-0 restarted" in text
    yield "gate: stopped", run(guard, "gate", stop).returncode == 1
    if os.path.exists(stop): os.unlink(stop)
    yield "gate: open", run(guard, "gate", stop).returncode == 0
    # the import's wait, and its withdrawal: only ever our own, by name
    def waits(our, pods, stop_set=False):
        open(ARGV, "w").close(); s = base_state(); s["our_import"] = our; s["import_pods"] = pods; save(s)
        if os.path.exists(stop): os.unlink(stop)
        if stop_set: open(stop, "w").close()
        r = run(guard, "import-wait", stop); deletes = [l.strip() for l in open(ARGV) if l.startswith("delete")]
        return r.returncode, deletes
    only_ours = ["delete keycloakrealmimport cmapi -n keycloak --wait=true --timeout=60s"]
    pending = {"status": {"phase": "Pending"}}; running = {"status": {"phase": "Running", "containerStatuses": [{"state": {"running": {}}}]}}
    done = {"metadata": {"name": "cmapi"}, "status": {"conditions": [{"type": "Done", "status": "True"}, {"type": "HasErrors", "status": "False"}]}}
    started = {"metadata": {"name": "cmapi"}, "status": {"conditions": [{"type": "Started", "status": "True"}, {"type": "Done", "status": "False"}, {"type": "HasErrors", "status": "False"}]}}
    errors = {"metadata": {"name": "cmapi"}, "status": {"conditions": [{"type": "HasErrors", "status": "True"}, {"type": "Done", "status": "False"}]}}
    s = base_state(); s["http"]["cmapi"] = [200, '{"realm":"cmapi","public_key":"k"}']; base_http = s["http"]
    rc, d = waits(started, [pending]); yield "not started by the deadline: withdrawn, by name only", rc == 1 and d == only_ours
    rc, d = waits(started, [], stop_set=True); yield "the run stopped, not started: withdrawn", rc == 1 and d == only_ours
    rc, d = waits(started, [running]); yield "running too long: reported, never interrupted", rc == 1 and d == []
    rc, d = waits(errors, [{"status": {"phase": "Failed", "containerStatuses": [{"state": {"terminated": {}}}]}}]); yield "failed: withdrawn, so the Job does not try again", rc == 1 and d == only_ours
    open(ARGV, "w").close(); s = base_state(); s["our_import"] = done; s["import_pods"] = [running]; s["http"]["cmapi"] = base_http["cmapi"]; save(s)
    r = run(guard, "import-wait", stop); yield "Done and the realm answers: passes, deletes nothing", r.returncode == 0 and "delete" not in open(ARGV).read()
    open(stop, "w").close()
    r = run(guard, "import-wait", stop); yield "Done, but the watch stopped the run while it ran: stops, deletes nothing", r.returncode == 1 and "delete" not in open(ARGV).read()
    os.unlink(stop)
    s["http"]["cmapi"] = [404, '{"error":"Realm does not exist"}']; save(s)
    yield "Done but no realm: stops", run(guard, "import-wait", stop).returncode == 1


def score(guard):
    return [(label, bool(ok)) for label, ok in cases(guard)]


MUTANTS = {
    "any 404 is absent": ('if status == 404 and doc == {"error": "Realm does not exist"}:', "if status == 404:"),
    "the snapshot leaves out keycloak-0's restarts": ('"restarts": cs.get("restartCount"), ', ""),
    "the snapshot drops the keys": ('"public_key_sha256": key}', '"public_key_sha256": None}'),
    "compare never differs": ("if d:\n                raise Stop", "if False:\n                raise Stop"),
    "the stop line moves": ("STOP_LINE_MI = 2048", "STOP_LINE_MI = 1024"),
    "no kind check": ("if clusters.returncode != 0 or names:", "if False:"),
    "no server check": ("if server != API_SERVER:", "if False:"),
    "no context check": ("if not context.endswith(CONTEXT_SUFFIX):", "if False:"),
    "no principal check": ("if user not in PRINCIPALS:", "if False:"),
    "an answer cut short ends the watch": ("except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):", "except (urllib.error.URLError, OSError, ValueError):"),
    "an unreadable pod ends the watch": ("except (Stop, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:", "except Stop as e:"),
    "a breach during the import does not stop the run": ("if os.path.exists(stop_file):\n                # A running", "if False:\n                # A running"),
    "the realm name is not checked": ('r"^    realm: cmapi$")', 'r"^  realm:$")'),
    "a second document is allowed": ('if re.search(r"^---", text, re.M) or re.search(r"^\\.\\.\\.", text, re.M):', "if False:"),
    "the watch ignores a restart": ('problems.append(f"keycloak-0 restarted: {kc}")', "pass"),
    "the watch never reports": ("if down and waited >= REPORT_AFTER_SECONDS and not reported:", "if False:"),
    "the watch does not stop the run": ("open(stop_file, \"a\").close()", "pass"),
    "a pending import is left to fire": ("if not started and time.monotonic() - t0 > SCHEDULE_DEADLINE:", "if False:"),
    "withdrawal deletes every import": ('oc("delete", "keycloakrealmimport", OURS, "-n", NS, "--wait=true", "--timeout=60s")', 'oc("delete", "keycloakrealmimport", "--all", "-n", NS)'),
    "a running import is killed": ('print(f"{now()} the import has run {int(RUN_DEADLINE)} s without finishing. It is not interrupted; report to the owner", flush=True)', 'withdraw("too long")'),
    "verification off": ("    return c\n", "    c.check_hostname = False; c.verify_mode = ssl.CERT_NONE\n    return c\n"),
}

try:
    rows = score(GUARD)
    bad = [l for l, ok in rows if not ok]
    for l, ok in rows:
        print(("  ok   " if ok else "  FAIL ") + l)
    wrong = 0
    if "--no-mutants" not in sys.argv and not bad:
        text = open(GUARD).read()
        for name, (old, new) in MUTANTS.items():
            assert text.count(old) == 1, (name, old, text.count(old))
            m = os.path.join(W, "mutant.py"); open(m, "w").write(text.replace(old, new))
            f = [l for l, ok in score(m) if not ok]
            print(f"  {'killed  ' if f else 'SURVIVED'} {name}" + (f" ({f[0]})" if f else ""))
            wrong += 0 if f else 1
    print(f"guard cases failed: {len(bad)}, mutants survived: {wrong}")
    sys.exit(1 if bad or wrong else 0)
finally:
    shutil.rmtree(W, ignore_errors=True)
