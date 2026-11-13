#!/usr/bin/env python3
"""docs/13's run, read: what it says is what the wave's rulings and the owner's requirements say, and every path and subcommand it names exists. A runbook is run by hand, so nothing else holds it.
Then its blocks, run: each step in a plain bash, as pasted, on stubs of oc, git, sleep and every script, with each command it runs failing in turn. Each failure must end the step, leave the shell alive, write the stop
file and make the next step refuse. Then the same checks on mutants of the document: a mutant that passes is a rule this test cannot fail on. Then step 12 again with its background watch logging late (#118). No cluster. usage: doc13-test.py [<docs/13 file>]. DOC13_BASH names another bash. Exit 1 on any failure."""
import os, re, select, shutil, stat, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs/13-crc-deployment.md")
DOC = open(PATH).read()
GUARD = open(os.path.join(ROOT, "deploy/crc-guard.py")).read()
MANIFESTS = os.path.join(ROOT, "deploy/manifests")


# Stands in for every command the run calls: logs its call, fails when that call is FAIL, and answers what the blocks read.
# STUB_WATCH_DELAY holds back the log of a watch, which runs in the background, as a busy machine does (#118). /bin/sleep, since sleep here is this stub.
STUB = r'''#!/usr/bin/env bash
key="$(basename "$0") $*"
case "$key" in "crc-guard.py watch "*) [ -z "${STUB_WATCH_DELAY:-}" ] || /bin/sleep "$STUB_WATCH_DELAY";; esac
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


def run_to_the_end(cmd, timeout=120, **kwargs):
    """subprocess.run that also outlasts everything cmd left in the background, so that none of it can log once this has returned (#118).
    Every descendant inherits the pipe's write end, and the read end sees end-of-file only when the last of them has gone. `wait` in the script cannot do this: a step's job is a child of the step's subshell."""
    read_end, write_end = os.pipe()
    try:
        try:
            done = subprocess.run(cmd, pass_fds=(write_end,), timeout=timeout, **kwargs)
        finally:
            os.close(write_end)
        if not select.select([read_end], [], [], timeout)[0]:
            raise TimeoutError(f"something {cmd} began is still running {timeout} s after it ended")
        return done
    finally:
        os.close(read_end)


def run_blocks(doc, steps, only=None, watch_delay="", failing=""):
    """Each step, or those in only, run with each of its commands failing. One string per rule a failure broke. watch_delay is STUB_WATCH_DELAY.
    failing narrows the failures to the commands starting so, and leaves out the dirty checkout: the late-watch checks run on every push and need no more."""
    out = []
    prelude = re.search(r"^## The run\n.*?```bash\n(.*?)```", doc, re.S | re.M)[1]
    work = tempfile.mkdtemp(prefix="doc13-run.")
    try:
        bin_dir = os.path.join(work, "bin"); deploy = os.path.join(work, "deploy"); os.mkdir(bin_dir); os.mkdir(deploy)
        names = [os.path.join(bin_dir, n) for n in ("oc", "git", "sleep")] + [os.path.join(deploy, "crc-guard.py")]
        names += [os.path.join(work, p) for p in set(re.findall(r"\b(?:deploy|examples)/[\w./-]+\.sh", "\n".join(steps.values())))]
        for n in names:
            os.makedirs(os.path.dirname(n), exist_ok=True)
            with open(n, "w") as f:
                f.write(STUB)
            os.chmod(n, os.stat(n).st_mode | stat.S_IXUSR)
        run_dir = os.path.join(work, "deploy", "rendered", "wave1-run"); os.makedirs(run_dir)
        stop = os.path.join(run_dir, "stop"); calls = os.path.join(work, "calls"); calls_next = calls + ".next"; script = os.path.join(work, "script")
        # What the issuer must answer for each step to pass, and what it must stop on.
        passes = {4: 10, 15: 10, 18: 0}
        wrong = {4: (0, 20), 15: (0, 20), 18: (10, 20)}

        def go(n, fail="", last="watch ended rc=0", then_next=True, **env):
            for f in (stop, calls, calls_next):
                if os.path.exists(f): os.unlink(f)
            with open(os.path.join(run_dir, "watch.log"), "w") as f:
                f.write(last + "\n")
            # The prelude with nothing failing: it defines what the steps use. Then the step, and the next step, pasted later, logging elsewhere.
            # A process keeps the CALLS it was forked with, so what the step began logs as the step's however late: a mark in one file would date a call by when it logged, not by who began it (#118).
            with open(script, "w") as f:
                f.write(prelude + "\n" + 'echo prelude >>"$CALLS"\n' + steps[n] + 'echo SURVIVED; export CALLS="$CALLS.next"\n' + (steps.get(n + 1, "") if then_next else "") + "echo SURVIVED_NEXT\n")
            r = run_to_the_end([os.environ.get("DOC13_BASH", "bash"), script], cwd=work, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               env={**os.environ, "PATH": bin_dir + os.pathsep + os.environ["PATH"], "CALLS": calls, "FAIL": fail, "STUB_WATCH_DELAY": watch_delay, "STUB_ISSUER": str(env.pop("issuer", passes.get(n, 10))), **env})
            log = open(calls).read().splitlines() if os.path.exists(calls) else []
            at = log.index("prelude") if "prelude" in log else 0
            after = open(calls_next).read().splitlines() if os.path.exists(calls_next) else []
            return r, log[at + 1:], after, os.path.exists(stop)

        def stopped_right(label, n, r, step_calls, after, was_stopped, fail=""):
            alive = "SURVIVED_NEXT" in r.stdout
            if not alive: out.append(f"{label}: the shell did not survive step {n}")
            if not was_stopped: out.append(f"{label}: step {n} wrote no stop file")
            allowed = ("crc-guard.py gate ",) + (("crc-guard.py import-wait ",) if n + 1 == 16 else ())
            ran = [c for c in after if not c.startswith(allowed)]
            if ran: out.append(f"{label}: the step after {n} ran {ran[0][:80]}")
            if fail in step_calls:
                # What may still follow a failure: the same read retried, the realm sync's log, and a watch begun in the background just before, judged next.
                late = [c for c in step_calls[step_calls.index(fail) + 1:] if c != fail and c != "oc logs job/cmapi-realm-sync -n cmapi" and not c.startswith(("sleep ", "crc-guard.py watch "))]
                if late: out.append(f"{label}: step {n} ran on after it failed: {late[0][:80]}")
                # Where a watch's line falls says nothing, since it logs when it gets there. That it logged at all says it began, and only `watching`, the check on it, may fail with one begun.
                begun = [c for c in step_calls if c.startswith("crc-guard.py watch ")]
                if begun and not fail.startswith("crc-guard.py watching "): out.append(f"{label}: step {n} began the watch all the same")

        for n in sorted(only or steps):
            r, step_calls, after, was_stopped = go(n, then_next=False)
            if was_stopped or "SURVIVED_NEXT" not in r.stdout:
                out.append(f"step {n} does not pass when nothing fails: {r.stdout[-200:]} {r.stderr[-200:]}")
                continue
            for key in sorted(set(step_calls)):
                if key.startswith("crc-guard.py watch ") or not key.startswith(failing):      # a watch is in the background: `watching` is what sees it, in crc-guard-test.py
                    continue
                r2, sc, after2, st = go(n, fail=key)
                stopped_right(f"{key[:60]} failing", n, r2, sc, after2, st, fail=key)
                if n == 21 and key.startswith("oc wait job/") and "oc logs job/cmapi-realm-sync -n cmapi" not in sc:
                    out.append("a realm sync that failed lost its log")
            for bad in wrong.get(n, ()):
                r2, sc, after2, st = go(n, issuer=bad)
                stopped_right(f"the issuer answering {bad}", n, r2, sc, after2, st)
                if n == 15 and any(c.startswith("oc apply") for c in sc): out.append(f"the import was applied with the issuer answering {bad}")
            if n == 3:
                r2, sc, after2, st = go(n, STUB_LISTED="namespace/cmapi-system")
                stopped_right("something listed", n, r2, sc, after2, st)
            if n == 24:
                r2, sc, after2, st = go(n, last="watch ended rc=3")
                stopped_right("a watch that ended rc=3", n, r2, sc, after2, st)
        if not failing:
            r2, sc, after2, st = go(1, STUB_DIRTY=" M x")
            if not st or "deploy/crc-trust.sh" in " ".join(sc): out.append("a dirty checkout does not stop the run")
    finally:
        shutil.rmtree(work)
    return out


KEYCLOAK_CA = "58E4A0F4B51C06119EA25526330BEA85885B0FD8"; INGRESS_CA = "C016211CBBB5CD072C3FFAC433221C38D1374E05"


def keychain_problems(doc):
    """The owner's keychain step, run: real certificates through real openssl, a stub of security that logs. Only a CA with its fingerprint can reach add-trusted-cert (#109)."""
    out = []
    blocks = re.findall(r"```bash\n(.*?)```", doc[doc.find("Steps only the owner can take"):doc.find("## The run\n")], re.S)
    add = next((b for b in blocks if "add-trusted-cert" in b), "")
    remove = next((b for b in blocks if "delete-certificate" in b), "")
    if not add or not remove:
        return ["the keychain step has no block to add with, or none to remove with"]
    if len(re.findall(r"add-trusted-cert", add)) != 1:
        out.append("more than one add-trusted-cert")
    for fp in (KEYCLOAK_CA, INGRESS_CA):
        if fp not in add or f"delete-certificate -Z {fp} " not in remove:
            out.append(f"the fingerprint {fp} is not both added by and removed by")
    if re.search(r"crc-ca", add):
        out.append("the step reads the bundle, which has been able to hold a site's certificate")
    lines = [l for l in remove.splitlines() if l.startswith("security ")]
    for i in range(0, len(lines), 2):
        if not (lines[i].startswith("security remove-trusted-cert ") and lines[i + 1:] and lines[i + 1].startswith("security delete-certificate -Z")):
            out.append(f"removal must clear the trust setting first, then the certificate: {lines[i][:60]}")
    w = tempfile.mkdtemp(prefix="doc13-keychain.")
    try:
        def cmd(*a, **k):
            return subprocess.run(a, cwd=w, capture_output=True, text=True, **k)
        def fingerprint(pem):
            return re.sub(r".*=|:", "", cmd("openssl", "x509", "-in", pem, "-noout", "-fingerprint", "-sha1").stdout.strip())
        for ca in ("a", "b"):
            cmd("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{ca}.key", "-out", f"{ca}.pem", "-subj", f"/CN=test {ca} CA", "-days", "2")
        cmd("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key", "-out", "leaf.csr", "-subj", "/CN=*.apps-crc.testing")
        open(os.path.join(w, "ext"), "w").write("basicConstraints=critical,CA:FALSE\n")
        cmd("openssl", "x509", "-req", "-in", "leaf.csr", "-CA", "a.pem", "-CAkey", "a.key", "-CAcreateserial", "-days", "2", "-extfile", "ext", "-out", "leaf.pem")
        os.makedirs(os.path.join(w, "bin"))
        stub = os.path.join(w, "bin", "security")
        open(stub, "w").write('#!/bin/sh\necho "$*" >>"$CALLS"\nexit "${STUB_SECURITY_RC:-0}"\n'); os.chmod(stub, 0o755)
        fa, fb, fl = fingerprint("a.pem"), fingerprint("b.pem"), fingerprint("leaf.pem")
        def run(keycloak_file, ingress_file, want_a=fa, want_b=fb):
            run_dir = os.path.join(w, "run"); shutil.rmtree(run_dir, ignore_errors=True); os.makedirs(run_dir)
            shutil.copy(os.path.join(w, keycloak_file), os.path.join(run_dir, "keycloak-ca.pem")); shutil.copy(os.path.join(w, ingress_file), os.path.join(run_dir, "ingress-ca.pem"))
            calls = os.path.join(w, "calls")
            if os.path.exists(calls): os.unlink(calls)
            script = add.replace(KEYCLOAK_CA, want_a).replace(INGRESS_CA, want_b)
            subprocess.run([os.environ.get("DOC13_BASH", "bash"), "-c", script], cwd=w, capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PATH": os.path.join(w, "bin") + os.pathsep + os.environ["PATH"], "RUN": run_dir, "CALLS": calls})
            added = open(calls).read().splitlines() if os.path.exists(calls) else []
            return [os.path.basename(c.split()[-1]) for c in added]
        if run("a.pem", "b.pem") != ["keycloak-ca.pem", "ingress-ca.pem"]:
            out.append("the two right CAs were not both trusted")
        if "keycloak-ca.pem" in run("leaf.pem", "b.pem", want_a=fl):
            out.append("the loop can trust a site's certificate: CA:FALSE, with its own fingerprint given")
        if "keycloak-ca.pem" in run("b.pem", "b.pem", want_a=fa):
            out.append("a CA with another fingerprint was trusted")
        # Both orders: openssl reads the first certificate alone, so a CA ahead of a site's certificate passes every check that reads one, and add-trusted-cert would still be given the file.
        for first, second in (("leaf.pem", "a.pem"), ("a.pem", "leaf.pem")):
            with open(os.path.join(w, "bundle.pem"), "w") as f:
                f.write(open(os.path.join(w, first)).read() + open(os.path.join(w, second)).read())
            if "keycloak-ca.pem" in run("bundle.pem", "b.pem"):
                out.append(f"a file holding {first} then {second} was trusted")
    finally:
        shutil.rmtree(w)
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
    need(sorted(steps) == list(range(1, 26)), f"the steps are 1 to 25 in order: {sorted(steps)}")
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
        need(inner[0].strip().startswith('$G import-wait "$STOP"' if n == 16 else '$G gate "$STOP"'), f"step {n} does not start with the stop file: {inner[0][:60]}")
        # Under set -e, A && B carries on past a failed A, and only these forms may stand in a list.
        for line in inner:
            code = re.sub(r"\s+#.*$", "", line)
            need(not re.search(r"&&", code.replace("&& break", "")), f"step {n} hides a failure in an AND-list: {code.strip()[:70]}")
            need(not re.search(r"\|\|", re.sub(r"\|\| rc=\$\?|\] \|\| \{ .*; exit 1; \}", "", code)), f"step {n} hides a failure in an OR-list: {code.strip()[:70]}")
    # Nothing broad, and TLS on.
    for label, pattern in (("--all", r"\s--all\b"), ("a selector on a delete", r"delete[^\n]*(\s-l\s|--selector)"), ("--prune", r"--prune"), ("delete -f", r"delete[^\n]*\s-f\s"),
                           ("TLS off", r"(\s-k\s|--insecure|--tls-verify=false|verify=False|CERT_NONE)"), ("a credential on an argument", r"(\s-p\s+\"?\$|--password[= ]\"?\$)")):
        need(not re.search(pattern, run), f"{label} in the run")
    # Ruling 5 and the backup's term: image, then LDAP, then backup, then realm alone, then workloads. The import is one-shot, and it names the new groups: LDAP is settled first (#110).
    order = [("crc-image.sh", 5), ("apply-test-identities.sh", 9), ("--remove-old-groups", 10), ("crc-backup.sh", 13), ("10-realm-import.yaml", 15), ("cluster.yaml", 19), ("40-networkpolicy.yaml", 20), ("20-realm-sync.yaml", 21), ("crc-proof.sh", 23)]
    for name, n in order:
        need(name in steps.get(n, ""), f"{name} is not in step {n}")
    need("--remove-old-groups" not in steps.get(9, "") and "--remove-test-identities" not in run, "step 9 removes something, or the run deletes the test users")
    for n in (9, 10):
        names = re.findall(r"apply-test-identities\.sh(?: [^\n|]*?)?(?= \||$)", steps.get(n, ""), re.M)
        need(names == {9: ["apply-test-identities.sh"], 10: ["apply-test-identities.sh --remove-old-groups"]}[n], f"step {n} calls the script another way: {names}")
    need("--dry-run=server" in steps.get(15, ""), "step 15 lost its server dry run")
    need("--issuer" in steps.get(11, "") and "--no-issuer-check" not in run, "secrets.sh without the issuer check")
    for n in (14, 17, 18, 22, 24):
        need(re.search(r'\$G compare "\$RUN/s0\.json"', steps.get(n, "")), f"step {n} does not compare with s0")
    need("$G watch" in steps.get(12, ""), "the watch does not start at step 12")
    need('$G watching "$STOP"' in steps.get(12, ""), "nothing checks that the watch began")
    need('rm -f "$RUN/watch.log.done"' in steps.get(12, ""), "a done file left from before would end the new watch at once")
    need("--issuer https://keycloak.apps-crc.testing/realms/cmapi " in steps.get(11, ""), "step 11 does not name this Keycloak's realm cmapi")
    # Every name resolves.
    subcommands = set(re.findall(r'sub\.add_parser\("([a-z-]+)"\)', GUARD)) | set(re.findall(r'p = sub\.add_parser\("([a-z-]+)"\)', GUARD))
    for sub in set(re.findall(r"\$G ([a-z-]+)", run)):
        need(sub in subcommands, f"crc-guard.py has no {sub}")
    for path in set(re.findall(r"\b(?:deploy|examples)/[\w./-]+\.(?:sh|py)", doc)):
        need(os.path.isfile(os.path.join(ROOT, path)), f"no file {path}")
    for sub, base in (("components", "components"), ("environment", "environments/crc")):
        for path in set(re.findall(r'\$R/' + sub + r'/([\w./-]+\.yaml)', run)):
            need(os.path.isfile(os.path.join(MANIFESTS, base, path)), f"no file {base}/{path}")
    # The two steps only the owner can take, and what must never be there.
    need("security add-trusted-cert" in doc and "security delete-certificate" in doc, "the owner's keychain step, in and out")
    out.extend(keychain_problems(doc))
    need("Sign in once as `cmapi.requester`" in doc, "the owner's LDAP sign-in")
    need("jsonpath={.data.cmapi\\.requester}' \\| base64 -d \\| pbcopy" in doc, "the owner's password to the clipboard")
    need("LDAP person" not in doc, "the owner signs in as an LDAP person, whom the realm cannot read any more")
    need("Secret `cmapi-ldap-test-users`" in doc and "--remove-test-identities" in doc, "the rollback's LDAP half")
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
    "the loop trusts every certificate in the bundle again": ('trust_ca "$RUN/keycloak-ca.pem" 58E4A0F4B51C06119EA25526330BEA85885B0FD8\n', 'cd "$RUN" && awk \'/BEGIN CERTIFICATE/{n++} {print > ("crc-ca-" n ".pem")}\' crc-ca.pem && cd -\nfor pem in "$RUN"/crc-ca-*.pem; do security add-trusted-cert -r trustRoot -p ssl -k ~/Library/Keychains/login.keychain-db "$pem"; done\n'),
    "the keychain's CA check gone": ("""  case "$text" in *CA:TRUE*) ;; *) echo "STOP: $pem is not a CA"; return 1;; esac\n""", ""),
    "the keychain's fingerprint check gone": ("""  [ "$got" = "$want" ] || { echo "STOP: $pem is $got, not $want"; return 1; }\n""", ""),
    "the keychain's one-certificate check gone": ("""  [ "$(grep -c 'BEGIN CERTIFICATE' "$pem")" = 1 ] || { echo "STOP: $pem does not hold exactly one certificate"; return 1; }\n""", ""),
    "the certificate deleted without its trust setting": ('security remove-trusted-cert "$RUN/keycloak-ca.pem"\n', ""),
    "another fingerprint": ('trust_ca "$RUN/ingress-ca.pem" C016211CBBB5CD072C3FFAC433221C38D1374E05', 'trust_ca "$RUN/ingress-ca.pem" 2895AEB025C910D1375A73077E1F0DCDFD7363E8'),
    "the old groups removed in the step of the new": ('apply-test-identities.sh | tee "$RUN/ldap-identities.txt"', 'apply-test-identities.sh --remove-old-groups | tee "$RUN/ldap-identities.txt"'),
    "the test users removed by the run": ('apply-test-identities.sh --remove-old-groups | tee -a', 'apply-test-identities.sh --remove-test-identities | tee -a'),
    "the old groups' step dropped": ('  examples/cmapi-sso/ldap/apply-test-identities.sh --remove-old-groups | tee -a "$RUN/ldap-identities.txt"\n', ""),
    "the identities' step without the gate": ('  $G gate "$STOP"\n  examples/cmapi-sso/ldap/apply-test-identities.sh | tee', '  examples/cmapi-sso/ldap/apply-test-identities.sh | tee'),
    "the identities' script that does not exist": ('examples/cmapi-sso/ldap/apply-test-identities.sh | tee', 'examples/cmapi-sso/ldap/apply-identities.sh | tee'),
    "the import before the backup": ("### Step 13: the backup, immediately before the import\n\n```bash\n( set -euo pipefail\n  $G gate \"$STOP\"\n  deploy/crc-backup.sh\n", "### Step 13: the backup, immediately before the import\n\n```bash\n( set -euo pipefail\n  $G gate \"$STOP\"\n"),
    "set -e in the terminal's own shell": ("G=deploy/crc-guard.py; export", "set -euo pipefail\nG=deploy/crc-guard.py; export"),
    "a step with no errexit": ('( set -euo pipefail\n  $G gate "$STOP"\n  deploy/crc-backup.sh\n', '( set -uo pipefail\n  $G gate "$STOP"\n  deploy/crc-backup.sh\n'),
    "( ... ) || stopped, which turns set -e off inside": ("); stopped $? 13", ") || stopped $? 13"),
    "a failure that is only printed": ("); stopped $? 5", "); echo done"),
    "a step that closes the shell": ("); stopped $? 11", "); stopped $? 11 || exit 1"),
    "another step's number": ("); stopped $? 14", "); stopped $? 21"),
    "an AND-list": ('  deploy/crc-trust.sh --check\n  deploy/crc-trust.sh --mac-ca', '  deploy/crc-trust.sh --check && deploy/crc-trust.sh --mac-ca'),
    "stopped writes nothing": (' | tee -a "$STOP"; return', "; return"),
    "stopped closes the shell": ('tee -a "$STOP"; return "$1"; }', 'tee -a "$STOP"; exit "$1"; }'),
    "step 4 reads any answer as absent": ('  [ "$rc" = 10 ]\n  echo "absent: go on"', '  echo "absent: go on"'),
    "step 15 reads any answer as absent": ('  [ "$rc" = 10 ]\n  oc apply --server-side --dry-run=server', '  oc apply --server-side --dry-run=server'),
    "step 18 does not look at the realm": ('  $G issuer\n  echo "realm present"', '  echo "realm present"'),
    "something listed is only printed": ('  [ -z "$left" ] || { echo "STOP: this run did not make: $left"; exit 1; }\n', ""),
    "the realm sync's log lost": ('  rc=0; oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s || rc=$?', '  oc wait job/cmapi-realm-sync -n cmapi --for=condition=Complete --timeout=600s'),
    "the realm sync's failure forgotten": ('  [ "$rc" = 0 ]\n', ""),
    "the watch's last line not asserted": ('  case "$last" in *"watch ended rc=0") ;; *) echo "STOP: the watch did not end clean"; exit 1;; esac\n', ""),
    "nothing checks the watch began": ('  $G watching "$STOP"\n', ""),
    "a stale done file ends the new watch": ('  rm -f "$RUN/watch.log.done"\n', ""),
    "the issuer of another host": ("--issuer https://keycloak.apps-crc.testing/realms/cmapi", "--issuer https://keycloak.example/realms/cmapi"),
    "a dirty checkout is only printed": ('  [ -z "$(git status --porcelain)" ]\n', '  git status --porcelain\n'),
}

# Each must fail by the run itself, with the watch logging late: (what to replace, with what, what the failure says). run_blocks is called directly, so the document's shape cannot be what catches them.
WATCH = 'nohup $G watch "$RUN/watch.log" "$STOP" "$RUN/s0.json" >"$RUN/watch.out" 2>&1 &\n'
SNAPSHOT = '  $G snapshot "$RUN/s0.json"\n  rm -f "$RUN/watch.log.done"\n  ' + WATCH
LATE_MUTANTS = {
    "a failed snapshot still begins the watch": (SNAPSHOT, '  $G snapshot "$RUN/s0.json" || rc=$?\n  rm -f "$RUN/watch.log.done"\n  ' + WATCH + '  [ "${rc:-0}" = 0 ]\n', "step 12 began the watch all the same"),
    "the watch begun before the snapshot": (SNAPSHOT, '  rm -f "$RUN/watch.log.done"\n  ' + WATCH + '  $G snapshot "$RUN/s0.json"\n', "step 12 began the watch all the same"),
    "the step after a stop begins a watch": ('  $G gate "$STOP"\n  deploy/crc-backup.sh\n', '  $G gate "$STOP" || rc=$?\n  ' + WATCH + '  [ "${rc:-0}" = 0 ]\n  deploy/crc-backup.sh\n', "the step after 12 ran crc-guard.py watch"),
}
# 0.02 s lands after the step's end in the same case, and 0.1 and 0.3 s in later cases, measured on the shipped harness (#118).
LATE_DELAYS = ("0.02", "0.1", "0.3")

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
    twelve = steps_of(DOC)
    for delay in LATE_DELAYS:
        late = run_blocks(DOC, twelve, [12], watch_delay=delay, failing="crc-guard.py ")
        for f in late:
            print(f"  FAIL the watch logging {delay} s late: " + f)
        print(f"  {'ok  ' if not late else 'FAIL'} step 12 holds with the watch logging {delay} s late")
        fails += late
    for name, (old, new, says) in LATE_MUTANTS.items():
        assert DOC.count(old) == 1, (name, old)
        mutant = DOC.replace(old, new)
        found = [f for f in run_blocks(mutant, steps_of(mutant), [12], watch_delay=LATE_DELAYS[-1], failing="crc-guard.py snapshot ") if says in f]
        print(f"  {'killed  ' if found else 'SURVIVED'} {name}, logging {LATE_DELAYS[-1]} s late" + (f" ({found[0][:90]})" if found else ""))
        survived += 0 if found else 1
print(f"doc13 cases failed: {len(fails)}, mutants survived: {survived}")
sys.exit(1 if fails or survived else 0)
