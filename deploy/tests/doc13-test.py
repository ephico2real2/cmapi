#!/usr/bin/env python3
"""docs/13's run, read: what it says is what the wave's rulings and the owner's requirements say, and every path and subcommand it names exists. A runbook is run by hand, so nothing else holds it.
Then its blocks, run: each step in a plain bash, as pasted, on stubs of oc, git, sleep and every script, with each command it runs failing in turn. Each failure must end the step, leave the shell alive, write the stop
file and make the next step refuse. Then the same checks on mutants of the document: a mutant that passes is a rule this test cannot fail on. No cluster. usage: doc13-test.py [<docs/13 file>]. DOC13_BASH names another bash. Exit 1 on any failure."""
import os, re, shutil, stat, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs/13-crc-deployment.md")
DOC = open(PATH).read()
GUARD = open(os.path.join(ROOT, "deploy/crc-guard.py")).read()
MANIFESTS = os.path.join(ROOT, "deploy/manifests")


# Stands in for every command the run calls: logs its call, fails when that call is FAIL, and answers what the blocks read.
STUB = r'''#!/usr/bin/env bash
key="$(basename "$0") $*"
printf '%s\n' "$key" >>"$CALLS"
[ "$key" != "$FAIL" ] || exit 7
case "$key" in
  "crc-guard.py gate "*) [ ! -e "$2" ]; exit;;
  "crc-guard.py issuer") exit "$STUB_ISSUER";;
  "git status"*) printf '%s' "${STUB_DIRTY:-}";;
  "oc get sa "*) echo x;;
  "oc get ns cmapi-imports"*|"oc get clusterrole,"*) printf '%s' "${STUB_LISTED:-}";;
esac
exit 0
'''


def run_blocks(doc, steps, only=None):
    """Each step, or those in only, run with each of its commands failing. One string per rule a failure broke."""
    out = []
    prelude = re.search(r"^## The run\n.*?```bash\n(.*?)```", doc, re.S | re.M)[1]
    work = tempfile.mkdtemp(prefix="doc13-run.")
    try:
        bin_dir = os.path.join(work, "bin"); deploy = os.path.join(work, "deploy"); os.mkdir(bin_dir); os.mkdir(deploy)
        names = [os.path.join(bin_dir, n) for n in ("oc", "git", "sleep")] + [os.path.join(deploy, "crc-guard.py")]
        names += [os.path.join(deploy, os.path.basename(p)) for p in set(re.findall(r"\bdeploy/[\w./-]+\.sh", "\n".join(steps.values())))]
        for n in names:
            with open(n, "w") as f:
                f.write(STUB)
            os.chmod(n, os.stat(n).st_mode | stat.S_IXUSR)
        run_dir = os.path.join(work, "deploy", "rendered", "wave1-run"); os.makedirs(run_dir)
        stop = os.path.join(run_dir, "stop"); calls = os.path.join(work, "calls"); script = os.path.join(work, "script")
        # What the issuer must answer for each step to pass, and what it must stop on.
        passes = {4: 10, 13: 10, 16: 0}
        wrong = {4: (0, 20), 13: (0, 20), 16: (10, 20)}

        def go(n, fail="", last="watch ended rc=0", then_next=True, **env):
            for f in (stop, calls):
                if os.path.exists(f): os.unlink(f)
            with open(os.path.join(run_dir, "watch.log"), "w") as f:
                f.write(last + "\n")
            # The prelude with nothing failing: it defines what the steps use. Then the step, a mark, and the next step, pasted later.
            with open(script, "w") as f:
                f.write(prelude + "\n" + 'echo prelude >>"$CALLS"\n' + steps[n] + 'echo SURVIVED; echo next >>"$CALLS"\n' + (steps.get(n + 1, "") if then_next else "") + "echo SURVIVED_NEXT\n")
            r = subprocess.run([os.environ.get("DOC13_BASH", "bash"), script], cwd=work, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
                               env={**os.environ, "PATH": bin_dir + os.pathsep + os.environ["PATH"], "CALLS": calls, "FAIL": fail, "STUB_ISSUER": str(env.pop("issuer", passes.get(n, 10))), **env})
            log = open(calls).read().splitlines() if os.path.exists(calls) else []
            at = log.index("prelude") if "prelude" in log else 0
            nx = log.index("next") if "next" in log else len(log)
            return r, log[at + 1:nx], log[nx + 1:], os.path.exists(stop)

        def stopped_right(label, n, r, step_calls, after, was_stopped, fail=""):
            alive = "SURVIVED_NEXT" in r.stdout
            if not alive: out.append(f"{label}: the shell did not survive step {n}")
            if not was_stopped: out.append(f"{label}: step {n} wrote no stop file")
            allowed = ("crc-guard.py gate ",) + (("crc-guard.py import-wait ",) if n + 1 == 14 else ())
            ran = [c for c in after if not c.startswith(allowed)]
            if ran: out.append(f"{label}: the step after {n} ran {ran[0][:80]}")
            if fail in step_calls:
                # What may still follow a failure: the same read retried, the realm sync's log, and a watch begun in the background just before.
                late = [c for c in step_calls[step_calls.index(fail) + 1:] if c != fail and c != "oc logs job/cmapi-realm-sync -n cmapi" and not c.startswith(("sleep ", "crc-guard.py watch "))]
                if late: out.append(f"{label}: step {n} ran on after it failed: {late[0][:80]}")

        for n in sorted(only or steps):
            r, step_calls, after, was_stopped = go(n, then_next=False)
            if was_stopped or "SURVIVED_NEXT" not in r.stdout:
                out.append(f"step {n} does not pass when nothing fails: {r.stdout[-200:]} {r.stderr[-200:]}")
                continue
            for key in sorted(set(step_calls)):
                if key.startswith("crc-guard.py watch "):      # in the background: `watching` is what sees it, in crc-guard-test.py
                    continue
                r2, sc, after2, st = go(n, fail=key)
                stopped_right(f"{key[:60]} failing", n, r2, sc, after2, st, fail=key)
                if n == 19 and key.startswith("oc wait job/") and "oc logs job/cmapi-realm-sync -n cmapi" not in sc:
                    out.append("a realm sync that failed lost its log")
            for bad in wrong.get(n, ()):
                r2, sc, after2, st = go(n, issuer=bad)
                stopped_right(f"the issuer answering {bad}", n, r2, sc, after2, st)
                if n == 13 and any(c.startswith("oc apply") for c in sc): out.append(f"the import was applied with the issuer answering {bad}")
            if n == 3:
                r2, sc, after2, st = go(n, STUB_LISTED="namespace/cmapi-system")
                stopped_right("something listed", n, r2, sc, after2, st)
            if n == 22:
                r2, sc, after2, st = go(n, last="watch ended rc=3")
                stopped_right("a watch that ended rc=3", n, r2, sc, after2, st)
        r2, sc, after2, st = go(1, STUB_DIRTY=" M x")
        if not st or "deploy/crc-trust.sh" in " ".join(sc): out.append("a dirty checkout does not stop the run")
    finally:
        shutil.rmtree(work)
    return out


def steps_of(doc):
    steps = {}
    for m in re.finditer(r"^### Step (\d+):[^\n]*\n(.*?)(?=^##|\Z)", doc, re.S | re.M):
        steps[int(m[1])] = "\n".join(re.findall(r"```bash\n(.*?)```", m[2], re.S))
    return steps


def problems(doc, only=None):
    """One string per broken rule."""
    out = []
    def need(ok, label):
        if not ok:
            out.append(label)
    steps = steps_of(doc)
    need(sorted(steps) == list(range(1, 24)), f"the steps are 1 to 23 in order: {sorted(steps)}")
    run = "\n".join(steps.values())
    # Ruling 13: every apply under one field manager. Lines are joined at a trailing backslash first.
    lines = re.sub(r"\\\n\s*", " ", run).splitlines()
    applies = [piece for line in lines for piece in re.split(r"&&|;", line) if re.search(r"\boc apply\b", piece)]
    need(len(applies) >= 9, f"{len(applies)} applies in the run")
    for piece in applies:
        need("--server-side" in piece and "--field-manager=cmapi-wave1" in piece, f"an apply without --server-side --field-manager=cmapi-wave1: {piece.strip()}")
        need(not re.search(r"-R\b.*environment|environment/?\"?\s+-R", piece), f"-R on the environment: {piece.strip()}")
    # The owner's requirement: a stop stops every later step. Each step is `( set -euo pipefail ... ); stopped $? N`: a subshell, so a failure never closes the terminal, and the stop written down,
    # so it holds for a step pasted later. Not `( ... ) || stopped`, which turns set -e off inside. Each looks at the stop file first; import-wait is given it, since it must withdraw an import on it.
    prelude = (re.search(r"^## The run\n.*?```bash\n(.*?)```", doc, re.S | re.M) or [None, ""])[1]
    need(not re.search(r"^\s*set -", prelude.split("( set -euo pipefail")[0], re.M), "set in the terminal's own shell")
    need('| tee -a "$STOP"' in prelude, "stopped does not write the stop file")
    for n, body in steps.items():
        shape = re.fullmatch(r"\( set -euo pipefail\n(.*)\n\); stopped \$\? (\d+)\n", body, re.S)
        need(shape and shape[2] == str(n), f"step {n} is not a subshell with set -euo pipefail ending in stopped $? {n}: {body[:40]!r}...{body[-30:]!r}")
        if not shape:
            continue
        inner = shape[1].splitlines()
        need(inner[0].strip().startswith('$G import-wait "$STOP"' if n == 14 else '$G gate "$STOP"'), f"step {n} does not start with the stop file: {inner[0][:60]}")
        # Under set -e, A && B carries on past a failed A, and only these forms may stand in a list.
        for line in inner:
            code = re.sub(r"\s+#.*$", "", line)
            need(not re.search(r"&&", code.replace("&& break", "")), f"step {n} hides a failure in an AND-list: {code.strip()[:70]}")
            need(not re.search(r"\|\|", re.sub(r"\|\| rc=\$\?|\] \|\| \{ .*; exit 1; \}", "", code)), f"step {n} hides a failure in an OR-list: {code.strip()[:70]}")
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
    need('$G watching "$STOP"' in steps.get(10, ""), "nothing checks that the watch began")
    need('rm -f "$RUN/watch.log.done"' in steps.get(10, ""), "a done file left from before would end the new watch at once")
    need("--issuer https://keycloak.apps-crc.testing/realms/cmapi " in steps.get(9, ""), "step 9 does not name this Keycloak's realm cmapi")
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
    # Slow next to the rest, and only worth saying once the document's shape holds.
    return out or run_blocks(doc, steps, only)


MUTANTS = {
    "an apply with no field manager": (' --field-manager=cmapi-wave1 -f "$R/environment/"', ' -f "$R/environment/"'),
    "an apply not server-side": ('oc apply --server-side --field-manager=cmapi-wave1 -f "$R/environment/"', 'oc apply --field-manager=cmapi-wave1 -f "$R/environment/"'),
    "-R on the environment": ('--field-manager=cmapi-wave1 -f "$R/environment/"', '--field-manager=cmapi-wave1 -R -f "$R/environment/"'),
    "the backup without the gate": ('  $G gate "$STOP"\n  deploy/crc-backup.sh\n', "  deploy/crc-backup.sh\n"),
    "the workloads without the gate": ('  $G gate "$STOP"\n  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"', '  oc apply --server-side --field-manager=cmapi-wave1 -f "$R/components/cmapi/40-networkpolicy.yaml"'),
    "a broad delete": ("oc delete keycloakrealmimport cmapi -n keycloak", "oc delete keycloakrealmimport --all -n keycloak"),
    "TLS off": ('  deploy/crc-trust.sh --check\n', '  curl -k x\n  deploy/crc-trust.sh --check\n'),
    "the issuer check skipped": ("deploy/secrets.sh --issuer https://keycloak.apps-crc.testing/realms/cmapi --ca-file \"$CMAPI_CRC_CA\"", "deploy/secrets.sh --no-issuer-check"),
    "a compare dropped": ('$G compare "$RUN/s0.json" "$RUN/s3.json"', "true"),
    "a guard subcommand that does not exist": ('$G headroom --needs 672', '$G room --needs 672'),
    "a file that does not exist": ('"$R/components/database-cnpg/cluster.yaml"', '"$R/components/database-cnpg/db.yaml"'),
    "a script that does not exist": ("deploy/crc-reader-import.sh", "deploy/crc-reader.sh"),
    "the owner's keychain step gone": ("security add-trusted-cert", "something else"),
    "the import before the backup": ("### Step 11: the backup, immediately before the import\n\n```bash\n( set -euo pipefail\n  $G gate \"$STOP\"\n  deploy/crc-backup.sh\n", "### Step 11: the backup, immediately before the import\n\n```bash\n( set -euo pipefail\n  $G gate \"$STOP\"\n"),
    "set -e in the terminal's own shell": ("G=deploy/crc-guard.py; export", "set -euo pipefail\nG=deploy/crc-guard.py; export"),
    "a step with no errexit": ('( set -euo pipefail\n  $G gate "$STOP"\n  deploy/crc-backup.sh\n', '( set -uo pipefail\n  $G gate "$STOP"\n  deploy/crc-backup.sh\n'),
    "( ... ) || stopped, which turns set -e off inside": ("); stopped $? 11", ") || stopped $? 11"),
    "a failure that is only printed": ("); stopped $? 5", "); echo done"),
    "a step that closes the shell": ("); stopped $? 9", "); stopped $? 9 || exit 1"),
    "another step's number": ("); stopped $? 12", "); stopped $? 21"),
    "an AND-list": ('  deploy/crc-trust.sh --check\n  deploy/crc-trust.sh --mac-ca', '  deploy/crc-trust.sh --check && deploy/crc-trust.sh --mac-ca'),
    "stopped writes nothing": (' | tee -a "$STOP"; return', "; return"),
    "stopped closes the shell": ('tee -a "$STOP"; return "$1"; }', 'tee -a "$STOP"; exit "$1"; }'),
    "step 4 reads any answer as absent": ('  [ "$rc" = 10 ]\n  echo "absent: go on"', '  echo "absent: go on"'),
    "step 13 reads any answer as absent": ('  [ "$rc" = 10 ]\n  oc apply --server-side --dry-run=server', '  oc apply --server-side --dry-run=server'),
    "step 16 does not look at the realm": ('  $G issuer\n  echo "realm present"', '  echo "realm present"'),
    "something listed is only printed": ('  [ -z "$left" ] || { echo "STOP: this run did not make: $left"; exit 1; }\n', ""),
    "the realm sync's log lost": ('  rc=0; oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s || rc=$?', '  oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s'),
    "the realm sync's failure forgotten": ('  [ "$rc" = 0 ]\n', ""),
    "the watch's last line not asserted": ('  case "$last" in *"watch ended rc=0") ;; *) echo "STOP: the watch did not end clean"; exit 1;; esac\n', ""),
    "nothing checks the watch began": ('  $G watching "$STOP"\n', ""),
    "a stale done file ends the new watch": ('  rm -f "$RUN/watch.log.done"\n', ""),
    "the issuer of another host": ("--issuer https://keycloak.apps-crc.testing/realms/cmapi", "--issuer https://keycloak.example/realms/cmapi"),
    "a dirty checkout is only printed": ('  [ -z "$(git status --porcelain)" ]\n', '  git status --porcelain\n'),
}

fails = problems(DOC)
for f in fails:
    print("  FAIL " + f)
print(f"  {'ok  ' if not fails else 'FAIL'} docs/13 holds every rule")
survived = 0
if not fails:
    for name, (old, new) in MUTANTS.items():
        assert DOC.count(old) >= 1, (name, old)
        mutant = DOC.replace(old, new)
        # The blocks that changed, or two steps for a change to what they all use: the whole run has already passed, and it takes half a minute each.
        was, now = steps_of(DOC), steps_of(mutant)
        found = problems(mutant, [n for n in now if now[n] != was.get(n)] or [1, 9])
        print(f"  {'killed  ' if found else 'SURVIVED'} {name}" + (f" ({found[0][:90]})" if found else ""))
        survived += 0 if found else 1
print(f"doc13 cases failed: {len(fails)}, mutants survived: {survived}")
sys.exit(1 if fails or survived else 0)
