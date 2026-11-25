"""#650: each mutant of a Containerfile's modes check must fail deploy/tests/ci-guard.py. usage: guard-mutants.py <worktree> <python>"""
import os, re, shutil, subprocess, sys, tempfile
tree, python = sys.argv[1:]
CF, PF = "cmapi/Containerfile", "cmapi-portal-ui/Containerfile"
def drop_check(t):
    return re.sub(r"USER 1000690000:0\nRUN .*?\n\n", "", t, flags=re.S)
MUTANTS = {
    "cmapi: the check removed": (CF, drop_check),
    "portal: the check removed": (PF, drop_check),
    "cmapi: the check moved before COPY policies": (CF, lambda t: t.replace("COPY policies /etc/cmapi/policies\n", "").replace("\nUSER 1001\n", "\nCOPY policies /etc/cmapi/policies\nUSER 1001\n")),
    "cmapi: the check runs as root": (CF, lambda t: t.replace("USER 1000690000:0", "USER 0")),
    "cmapi: /opt/app-root not checked": (CF, lambda t: t.replace('paths="/opt/app-root ', 'paths="')),
    "portal: /usr/share/nginx/html not checked": (PF, lambda t: t.replace('paths="/usr/share/nginx/html ', 'paths="')),
    "cmapi: no canary": (CF, lambda t: re.sub(r"    canary=.*?rm -f \"\$canary\"; \\\n", "", t, flags=re.S)),
    "cmapi: the read test always passes": (CF, lambda t: t.replace('[ -r "$p" ] ||', 'true ||')),
    "cmapi: a finding does not fail the build": (CF, lambda t: t.replace('"$bad" >&2; exit 1; fi;', '"$bad" >&2; fi;')),
    "portal: no search or run check": (PF, lambda t: re.sub(r"             find \$paths \\\( -type d.*?\n", "", t)),
    "cmapi: a COPY after the check": (CF, lambda t: t.replace("\nUSER 1001\n", "\nCOPY policies /srv/policies\nUSER 1001\n")),
    "cmapi: a COPY outside the checked paths": (CF, lambda t: t.replace("COPY policies /etc/cmapi/policies", "COPY policies /etc/cmapi/policies\nCOPY policies /srv/policies")),
    "portal: a RUN after the check": (PF, lambda t: t.replace("\nUSER 101\n", "\nRUN chmod 0600 /etc/nginx/nginx.conf\nUSER 101\n")),
    "portal: the image runs as the check's user": (PF, lambda t: t.replace("\nUSER 101\n", "\n")),
}
base = tempfile.mkdtemp()
src = os.path.join(base, "src")
subprocess.run(f"git -C {tree} ls-files -z | (cd {tree} && xargs -0 tar cf -) | (mkdir -p {src} && tar xf - -C {src})", shell=True, check=True)
for f in (CF, PF, "deploy/tests/ci-guard.py"):
    shutil.copy(os.path.join(tree, f), os.path.join(src, f))
def guard(root):
    return subprocess.run([python, "deploy/tests/ci-guard.py", ".github/workflows/ci.yml"], cwd=root, capture_output=True, text=True)
r = guard(src)
print(f"unmutated: exit {r.returncode}"); survivors = int(r.returncode != 0)
for name, (f, mutate) in MUTANTS.items():
    root = os.path.join(base, re.sub(r"\W+", "-", name)); shutil.copytree(src, root)
    p = os.path.join(root, f); before = open(p).read(); after = mutate(before)
    if after == before:
        print(f"MUTANT NOT APPLIED: {name}"); survivors += 1; continue
    open(p, "w").write(after)
    r = guard(root)
    fails = [l.strip() for l in r.stdout.splitlines() if l.startswith("  FAIL")]
    print(f"{'killed  ' if r.returncode else 'SURVIVED'} {name}: {fails[0][:150] if fails else ''}")
    survivors += r.returncode == 0
shutil.rmtree(base)
print("survivors:", survivors); sys.exit(1 if survivors else 0)
