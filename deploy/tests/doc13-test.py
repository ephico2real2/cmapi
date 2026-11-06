#!/usr/bin/env python3
"""docs/13's run, read: what it says is what the wave's rulings and the owner's requirements say, and every path and subcommand it names exists. A runbook is run by hand, so nothing else holds it.
Then the same checks on mutants of the document: a mutant that passes is a rule this test cannot fail on. No cluster. usage: doc13-test.py [<docs/13 file>]. Exit 1 on any failure."""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs/13-crc-deployment.md")
DOC = open(PATH).read()
GUARD = open(os.path.join(ROOT, "deploy/crc-guard.py")).read()
MANIFESTS = os.path.join(ROOT, "deploy/manifests")


def problems(doc):
    """One string per broken rule."""
    out = []
    def need(ok, label):
        if not ok:
            out.append(label)
    steps = {}
    for m in re.finditer(r"^### Step (\d+):[^\n]*\n(.*?)(?=^##|\Z)", doc, re.S | re.M):
        steps[int(m[1])] = "\n".join(re.findall(r"```bash\n(.*?)```", m[2], re.S))
    need(sorted(steps) == list(range(1, 24)), f"the steps are 1 to 23 in order: {sorted(steps)}")
    run = "\n".join(steps.values())
    # Ruling 13: every apply under one field manager. Lines are joined at a trailing backslash first.
    lines = re.sub(r"\\\n\s*", " ", run).splitlines()
    applies = [piece for line in lines for piece in re.split(r"&&|;", line) if re.search(r"\boc apply\b", piece)]
    need(len(applies) >= 9, f"{len(applies)} applies in the run")
    for piece in applies:
        need("--server-side" in piece and "--field-manager=cmapi-wave1" in piece, f"an apply without --server-side --field-manager=cmapi-wave1: {piece.strip()}")
        need(not re.search(r"-R\b.*environment|environment/?\"?\s+-R", piece), f"-R on the environment: {piece.strip()}")
    # The owner's requirement: a breach stops every later step. Every step from the backup on looks at the stop file first; import-wait is given it, since it must withdraw an import on it.
    for n, body in steps.items():
        if n >= 11:
            first = next((line for line in body.splitlines() if not line.startswith("I=$R")), "")
            need(first.startswith(('$G gate "$STOP"', '$G import-wait "$STOP"')), f"step {n} does not start with the stop file: {first[:60]}")
    # Nothing broad, and TLS on.
    for label, pattern in (("--all", r"\s--all\b"), ("a selector on a delete", r"delete[^\n]*(\s-l\s|--selector)"), ("--prune", r"--prune"), ("delete -f", r"delete[^\n]*\s-f\s"),
                           ("TLS off", r"(\s-k\s|--insecure|--tls-verify=false|verify=False|CERT_NONE)"), ("a credential on an argument", r"(\s-p\s+\"?\$|--password[= ]\"?\$)")):
        need(not re.search(pattern, run), f"{label} in the run")
    # Ruling 5 and the backup's term: image, then backup, then realm alone, then workloads.
    order = [("crc-image.sh", 5), ("crc-backup.sh", 11), ("10-realm-import.yaml", 13), ("cluster.yaml", 17), ("40-networkpolicy.yaml", 18), ("20-realm-sync.yaml", 19), ("crc-proof.sh", 21)]
    for name, n in order:
        need(name in steps.get(n, ""), f"{name} is not in step {n}")
    need("--dry-run=server" in steps.get(13, ""), "step 13 lost its server dry run")
    need("--issuer" in steps.get(9, "") and "--no-issuer-check" not in run, "secrets.sh without the issuer check")
    for n in (12, 15, 16, 20, 22):
        need(re.search(r'\$G compare "\$RUN/s0\.json"', steps.get(n, "")), f"step {n} does not compare with s0")
    need("$G watch" in steps.get(10, ""), "the watch does not start at step 10")
    # Every name resolves.
    subcommands = set(re.findall(r'sub\.add_parser\("([a-z-]+)"\)', GUARD)) | set(re.findall(r'p = sub\.add_parser\("([a-z-]+)"\)', GUARD))
    for sub in set(re.findall(r"\$G ([a-z-]+)", run)):
        need(sub in subcommands, f"crc-guard.py has no {sub}")
    for path in set(re.findall(r"\bdeploy/[\w./-]+\.(?:sh|py)", doc)):
        need(os.path.isfile(os.path.join(ROOT, path)), f"no file {path}")
    for sub, base in (("components", "components"), ("environment", "environments/crc")):
        for path in set(re.findall(r'\$R/' + sub + r'/([\w./-]+\.yaml)', run)):
            need(os.path.isfile(os.path.join(MANIFESTS, base, path)), f"no file {base}/{path}")
    # The two steps only the owner can take, and what must never be there.
    need("security add-trusted-cert" in doc and "security delete-certificate" in doc, "the owner's keychain step, in and out")
    need("Sign in once as an LDAP person" in doc, "the owner's LDAP sign-in")
    need("gitea" not in doc.lower(), "Gitea in the runbook")
    need("It is the owner's decision alone" in doc and "--delete-realm --owner-approved" in doc, "the owner's two decisions")
    need("REPORT TO THE OWNER NOW" in doc and "300 s" in doc, "the bound on a restart")
    return out


MUTANTS = {
    "an apply with no field manager": (' --field-manager=cmapi-wave1 -f "$R/environment/"', ' -f "$R/environment/"'),
    "an apply not server-side": ('oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/"', 'oc apply --field-manager=cmapi-wave1 -f "$R/environment/"'),
    "-R on the environment": ('--field-manager=cmapi-wave1 -f "$R/environment/"', '--field-manager=cmapi-wave1 -R -f "$R/environment/"'),
    "the backup without the gate": ('$G gate "$STOP" && deploy/crc-backup.sh\n', "deploy/crc-backup.sh\n"),
    "the workloads without the gate": ('$G gate "$STOP" && oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"', 'oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"'),
    "a broad delete": ("oc delete keycloakrealmimport cmapi -n keycloak", "oc delete keycloakrealmimport --all -n keycloak"),
    "TLS off": ('deploy/crc-trust.sh --check &&', 'curl -k x && deploy/crc-trust.sh --check &&'),
    "the issuer check skipped": ("deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca-file \"$CMAPI_CRC_CA\"", "deploy/secrets.sh --no-issuer-check"),
    "a compare dropped": ('$G compare "$RUN/s0.json" "$RUN/s3.json"', "true"),
    "a guard subcommand that does not exist": ('$G headroom --needs 672', '$G room --needs 672'),
    "a file that does not exist": ('"$R/components/database-cnpg/cluster.yaml"', '"$R/components/database-cnpg/db.yaml"'),
    "a script that does not exist": ("deploy/crc-reader-import.sh", "deploy/crc-reader.sh"),
    "the owner's keychain step gone": ("security add-trusted-cert", "something else"),
    "the import before the backup": ("### Step 11: the backup, immediately before the import\n\n```bash\n$G gate \"$STOP\" && deploy/crc-backup.sh\n", "### Step 11: the backup, immediately before the import\n\n```bash\n$G gate \"$STOP\"\n"),
}

fails = problems(DOC)
for f in fails:
    print("  FAIL " + f)
print(f"  {'ok  ' if not fails else 'FAIL'} docs/13 holds every rule")
survived = 0
if not fails:
    for name, (old, new) in MUTANTS.items():
        assert DOC.count(old) >= 1, (name, old)
        found = problems(DOC.replace(old, new))
        print(f"  {'killed  ' if found else 'SURVIVED'} {name}" + (f" ({found[0][:90]})" if found else ""))
        survived += 0 if found else 1
print(f"doc13 cases failed: {len(fails)}, mutants survived: {survived}")
sys.exit(1 if fails or survived else 0)
