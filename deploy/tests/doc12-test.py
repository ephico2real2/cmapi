#!/usr/bin/env python3
"""docs/12's commands, run, and its claims, read. From the review of PR #89. No cluster: oc is a stub. Needs PyYAML in this Python.
usage: doc12-test.py [<docs/12 file>]. Exit 1 on any failure."""
import json, os, re, shlex, shutil, subprocess, sys, tempfile, urllib.parse
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
doc = open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs/12-existing-postgresql.md")).read()
fails = []
def check(ok, label):
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok: fails.append(label)
blocks = re.findall(r"```bash\n(.*?)```", doc, re.S)
secret = next(b for b in blocks if "pw.txt" in b)
pgcheck = next(b for b in blocks if "pg-check" in b)
move = next(b for b in blocks if "pg_dump" in b)

STUB = """#!/bin/sh
cat > "$STUB_OUT/stdin.$$"
echo called >> "$STUB_OUT/called"
exit ${STUB_RC:-0}
"""
def run_secret(pw, rc=0):
    t = tempfile.mkdtemp(); bindir = os.path.join(t, "bin"); os.mkdir(bindir); out = os.path.join(t, "out"); os.mkdir(out)
    p = os.path.join(bindir, "oc"); open(p, "w").write(STUB); os.chmod(p, 0o755)
    if pw is not None: open(os.path.join(t, "pw.txt"), "w").write(pw)
    r = subprocess.run(["bash", "-c", secret], cwd=t, env=dict(os.environ, PATH=bindir + ":" + os.environ["PATH"], STUB_OUT=out, STUB_RC=str(rc)), capture_output=True, text=True)
    docs = [open(os.path.join(out, f)).read() for f in os.listdir(out) if f.startswith("stdin")]
    kept = os.path.exists(os.path.join(t, "pw.txt"))
    shutil.rmtree(t)
    return r, docs, kept
PW = 'p@ss%w/rd:#&?x'
r, docs, kept = run_secret(PW)
d = yaml.safe_load(docs[0]) if docs else {}
uri = (d.get("stringData") or {}).get("uri", "")
u = urllib.parse.urlsplit(uri)
check(urllib.parse.unquote(u.password or "") == PW and u.hostname == "db.example.internal", "step 3: the password survives URI and YAML encoding")
check("sslmode=verify-full" in u.query and "sslrootcert=/etc/cmapi/ca/ca-bundle.crt" in u.query, "step 3: verify-full and sslrootcert are in the URI")
check(d.get("metadata", {}).get("name") == "cmapi-db-app" and list(d.get("stringData", {})) == ["uri"], "step 3: Secret cmapi-db-app, key uri, nothing else")
check(not kept, "step 3: pw.txt is deleted after a write")
r, docs, kept = run_secret(None)
written = [yaml.safe_load(x) for x in docs if x.strip()]
empty = [x for x in written if (urllib.parse.urlsplit(x["stringData"]["uri"]).password or "") == ""]
check(not empty, "step 3: no pw.txt writes no Secret with an empty password")
r, docs, kept = run_secret(PW, rc=1)
check(kept, "step 3: a failed oc apply keeps pw.txt, the only copy of the password")
# step 4: what the pod would really be
line = re.sub(r"^\s*#.*$", "", pgcheck, flags=re.M).replace("\\\n", " ")
argv = shlex.split(line)
assert argv[:2] == ["oc", "run"]
# kubectl's --overrides is a JSON merge patch, which replaces the containers list whole (measured on kind: the pod got the
# overrides' image and no env from --image and --env), so the pod is what the overrides say.
ov = json.loads(next(a.split("=", 1)[1] for a in argv if a.startswith("--overrides=")))
c = ov["spec"]["containers"][0]
check("@sha256:" in c["image"], f"step 4: the pod's image is pinned ({c['image'][:60]})")
check(not any(a.startswith("--env") for a in argv) or c.get("env"), "step 4: no --env that the overrides silently drop")
# section 5
check(not re.search(r"pg_dump[^\n]*-U cmapi", move), "section 5: pg_dump is not -U cmapi on the socket (measured: Peer authentication failed)")
check("PGSSLROOTCERT" in move or "sslrootcert" in move.split("pg_restore")[1].split("\n")[0], "section 5: pg_restore has a root certificate for verify-full")
# The block itself, on stubs of oc, pg_restore and psql: what reaches psql, in what order, and what stops it.
RESTORE_STUB = '''#!/bin/sh
echo "pg_restore $*" >> "$STUB_OUT/calls"
printf 'SET statement_timeout = 0;\nSET transaction_timeout = 0;\nCREATE TABLE t(x text);\nCOPY t (x) FROM stdin;\nSET transaction_timeout = 0;\n\\.\n'
exit ${STUB_RESTORE_RC:-0}
'''
PSQL_STUB = '''#!/bin/sh
echo "psql $*" >> "$STUB_OUT/calls"
case " $* " in
  *" -f - "*) cat > "$STUB_OUT/psql.stdin"; exit ${STUB_PSQL_RC:-0};;
esac
echo "${STUB_TARGET_ROWS:-7}"
'''
OC_STUB = '''#!/bin/sh
echo "oc $*" >> "$STUB_OUT/calls"
case " $* " in
  *" pg_dump "*) echo dump;;
  *" psql "*) echo 7;;
  *" wait "*) exit ${STUB_WAIT_RC:-0};;
  *" get pod "*) [ -z "${STUB_PODS:-}" ] || echo "$STUB_PODS";;
esac
'''
def run_move(**env):
    t = tempfile.mkdtemp(); bindir = os.path.join(t, "bin"); os.mkdir(bindir); out = os.path.join(t, "out"); os.mkdir(out)
    for name, body in (("oc", OC_STUB), ("pg_restore", RESTORE_STUB), ("psql", PSQL_STUB)):
        p = os.path.join(bindir, name); open(p, "w").write(body); os.chmod(p, 0o755)
    r = subprocess.run(["bash", "-c", move], cwd=t, env=dict(os.environ, PATH=bindir + ":" + os.environ["PATH"], STUB_OUT=out, **env), capture_output=True, text=True)
    def read(n):
        f = os.path.join(out, n)
        return open(f).read() if os.path.exists(f) else ""
    res = (r.returncode, read("calls"), read("psql.stdin"), r.stdout + r.stderr)
    shutil.rmtree(t)
    return res
rc, calls, into_psql, printed = run_move()
check(rc == 0, f"section 5: the block runs through on a good copy (rc {rc}: {printed[-200:]})")
check("-d " not in next((c for c in calls.splitlines() if c.startswith("pg_restore")), "-d "), "section 5: pg_restore writes a script, so PostgreSQL 16's error on SET transaction_timeout is not fatal")
atomic = next((c for c in calls.splitlines() if c.startswith("psql") and c.endswith(" -f -")), "")
check("--single-transaction" in atomic and "ON_ERROR_STOP=1" in atomic, "section 5: the restore is one transaction that stops at the first error")
check(into_psql.count("SET transaction_timeout = 0;") == 1 and into_psql.index("COPY") < into_psql.index("SET transaction_timeout = 0;"), "section 5: the header's SET transaction_timeout is gone, and a table row with the same text stays")
check("SET statement_timeout = 0;" in into_psql and "CREATE TABLE" in into_psql, "section 5: nothing else is removed from the script")
order = [c.split()[3] if c.startswith("oc") else c.split()[0] for c in calls.splitlines()]
check(order[:3] == ["scale", "wait", "exec"], f"section 5: the dump waits for the old pods to go: {order[:3]}")
rc, calls, _, _ = run_move(STUB_WAIT_RC="1")
check(rc != 0 and "pg_dump" not in calls, "section 5: pods that do not go stop it before the dump")
for label, env in (("pg_restore failing", {"STUB_RESTORE_RC": "1"}), ("psql failing", {"STUB_PSQL_RC": "3"})):
    rc, calls, _, _ = run_move(**env)
    check(rc != 0 and "count(*)" not in calls, f"section 5: {label} stops it before the counts (pipefail)")
rc, _, _, _ = run_move(STUB_TARGET_ROWS="6")
check(rc != 0, "section 5: counts that differ stop it")
rc, _, _, _ = run_move(STUB_PODS="pod/cmapi-api-1")
check(rc != 0, "section 5: a workload that came back stops it")
check("Then replace `cmapi-db-app`" not in doc, "section 5: does not say to replace the Secret while the Cluster exists (measured: immutable type)")
tail = doc[doc.index("## 5."):]
check("delete cluster cmapi-db" in tail and "create the Secret (section 3" in tail and tail.find("delete cluster cmapi-db") < tail.find("create the Secret (section 3"), "section 5: the Cluster is deleted before the Secret is created")
check("on the initContainer and the main containers" not in doc, "section 1: does not claim PGSSLROOTCERT on the main containers (measured: initContainer only)")
limit = int(re.search(r"CONNECTION LIMIT (\d+);", doc).group(1))
check(limit >= 2 * 2 * 10 + 2, f"section 2: CONNECTION LIMIT {limit} holds both pods' pools through a rolling update (4 x 10) plus two migrators")
print("doc cases failed:", len(fails)); sys.exit(1 if fails else 0)
