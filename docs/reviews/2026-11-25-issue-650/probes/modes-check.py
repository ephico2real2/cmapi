"""#650: the modes check of each Containerfile, run as written, on trees made here (reviewer 1's modes-check-test.py,
extended by reviewer 2). The RUN is taken from the Containerfile; only its absolute paths are moved under a
temporary root. It runs under each shell given, as this user, who owns the tree: a mode that refuses the owner refuses this
user, as the kernel refuses a UID that owns nothing and whose group has no bit.

The check now also asserts its own premise (it runs in group 0 alone and owns nothing it checks). Run here, as the tree's
owner and in this Mac's groups, that premise is false by construction, so for every case but the two premise cases the
harness puts a UID that owns nothing (54321, no account on this Mac) for "$(id -u)" and 0 for "$(id -G)". The two premise
cases keep the real id calls and must fail. Not covered here: the canary's refusal (needs CAP_DAC_OVERRIDE) and group 0.
Each run has a 60 s timeout, so a check that loops on a link cycle fails instead of hanging.
usage: modes-check.py <worktree> [shell ...]"""
import os, re, shutil, subprocess, sys, tempfile
tree, shells = sys.argv[1], sys.argv[2:] or ["/bin/sh", "/bin/dash"]
def run_text(path):
    lines, out, take = open(os.path.join(tree, path)).read().splitlines(), [], False
    for i, l in enumerate(lines):
        if re.match(r"USER \d+:0$", l) and lines[i + 1].startswith("RUN set -eu;"):
            take = True; continue
        if take:
            out.append(l)
            if not l.rstrip().endswith("\\"):
                break
    return "\n".join(out)[len("RUN "):]
def moved(script, root, real_uid=False, real_groups=False):
    at = lambda m: m[1] + " ".join(root + p for p in m[2].split()) + m[3]
    script = re.sub(r'(paths=")([^"]+)(")', at, script)
    script = re.sub(r"(for p in )((?:/\S+ ?)+)(; do \[ -w)", at, script)
    if not real_uid:
        script = script.replace('"$(id -u)"', '"54321"')
    if not real_groups:
        script = script.replace("$(id -G)", "0")
    return script
def make(root, paths):
    for p in paths:
        full = root + p
        if p.endswith(".sh") or p.endswith(".conf"):
            os.makedirs(os.path.dirname(full), exist_ok=True); open(full, "w").write("x\n"); os.chmod(full, 0o755 if p.endswith(".sh") else 0o664)
        else:
            os.makedirs(full, exist_ok=True); open(os.path.join(full, "file.txt"), "w").write("x\n")
            os.makedirs(os.path.join(full, "sub")); open(os.path.join(full, "sub", "run"), "w").write("#!/bin/sh\n"); os.chmod(os.path.join(full, "sub", "run"), 0o755)
IMAGES = {"cmapi/Containerfile": ["/opt/app-root", "/etc/cmapi", "/usr/local/bin"],
          "cmapi-portal-ui/Containerfile": ["/usr/share/nginx/html", "/etc/nginx", "/etc/nginx/conf.d", "/etc/nginx/nginx.conf", "/docker-entrypoint.sh", "/docker-entrypoint.d"]}
# A file of another owner that its owner may run and this user may read but not run (mode rwxr--r--), for a link to point at.
# Found on this machine, not made: only its owner can set such a mode on a file this user does not own.
OTHERS_PROGRAM = subprocess.run(
    ["find", "/Library", "/usr", "/System/Library", "-maxdepth", "4", "-type", "f", "-perm", "-100", "-perm", "-004",
     "!", "-perm", "-001", "!", "-user", str(os.getuid())], capture_output=True, text=True).stdout.split("\n")[0]
def outside(root):
    out = os.path.join(root, "outside"); os.makedirs(out, exist_ok=True); return out
def case_file_000(root, d):
    os.chmod(os.path.join(root + d, "file.txt"), 0o000)
def case_dir_000(root, d):
    os.chmod(os.path.join(root + d, "sub"), 0o000)
def case_dir_no_search(root, d):
    os.chmod(os.path.join(root + d, "sub"), 0o600)
def case_dangling_link(root, d):
    os.symlink("/nowhere/at/all", os.path.join(root + d, "dangling"))
def case_link_inside(root, d):
    os.symlink("file.txt", os.path.join(root + d, "inside"))
def case_link_to_unreadable_outside(root, d):
    f = os.path.join(outside(root), "target.js"); open(f, "w").write("x\n"); os.chmod(f, 0o000)
    os.symlink(f, os.path.join(root + d, "bundle.js"))
def case_conf_d_read_only(root, d):
    os.chmod(root + "/etc/nginx/conf.d", 0o555)
def case_link_cycle(root, d):
    os.symlink("loop-b", os.path.join(root + d, "loop-a")); os.symlink("loop-a", os.path.join(root + d, "loop-b"))
def case_link_to_readable_dir_outside(root, d):
    t = os.path.join(outside(root), "modules"); os.makedirs(t); os.symlink(t, os.path.join(root + d, "modules"))
def case_link_to_unsearchable_dir_outside(root, d):
    t = os.path.join(outside(root), "modules"); os.makedirs(t); open(os.path.join(t, "m.so"), "w").write("x\n"); os.chmod(t, 0o644)
    os.symlink(t, os.path.join(root + d, "modules"))
def case_link_to_unrunnable_program_outside(root, d):
    os.symlink(OTHERS_PROGRAM, os.path.join(root + d, "python3"))
def case_owned_by_check_uid(root, d):
    pass  # the tree is this user's, and the harness leaves "$(id -u)" in the check
def case_not_group_0_alone(root, d):
    pass  # this user's groups are not 0 alone, and the harness leaves "$(id -G)" in the check
CASES = [("a clean tree", None, 0, "image modes (#650)"),
         ("a file of mode 000", case_file_000, 1, "cannot read"),
         ("a directory of mode 000", case_dir_000, 1, "sub"),
         ("a directory of mode 0600", case_dir_no_search, 1, "cannot search or run"),
         ("a dangling link", case_dangling_link, 0, "image modes (#650)"),
         ("a link to a readable file of the tree", case_link_inside, 0, "image modes (#650)"),
         ("a link to an unreadable file outside the checked paths", case_link_to_unreadable_outside, 1, "cannot read"),
         ("portal only: conf.d of mode 0555", case_conf_d_read_only, 1, "cannot write"),
         # Reviewer 2.
         ("r2 a link cycle (no loop, no finding)", case_link_cycle, 0, "image modes (#650)"),
         ("r2 a link to a searchable directory outside", case_link_to_readable_dir_outside, 0, "image modes (#650)"),
         ("r2 a link to a directory outside that this user cannot search", case_link_to_unsearchable_dir_outside, 1, "cannot search or run"),
         ("r2 a link to a program outside that its owner may run and this user cannot", case_link_to_unrunnable_program_outside, 1, "cannot search or run"),
         ("r2 the check's UID owns the files it checks", case_owned_by_check_uid, 1, "owned by the check UID"),
         ("r2 the check runs in groups other than 0", case_not_group_0_alone, 1, "not in group 0 alone")]
print(f"program for the run case: {OTHERS_PROGRAM or 'none found'}")
failed = 0
for path, paths in IMAGES.items():
    script = run_text(path)
    for shell in shells:
        for name, mutate, want, text in CASES:
            if name.startswith("portal only") and "portal" not in path:
                continue
            if mutate is case_link_to_unrunnable_program_outside and not OTHERS_PROGRAM:
                print(f"n/a  {path} [{shell}] {name}: no such file on this machine"); continue
            root = tempfile.mkdtemp(); make(root, paths)
            if mutate: mutate(root, paths[0])
            text_run = moved(script, root, real_uid=mutate is case_owned_by_check_uid, real_groups=mutate is case_not_group_0_alone)
            try:
                r = subprocess.run([shell, "-c", text_run], capture_output=True, text=True, timeout=60)
                code, out = r.returncode, (r.stdout + r.stderr).replace(root, "")
            except subprocess.TimeoutExpired:
                code, out = "timeout", "timed out after 60 s"
            ok = code == want and text in out
            failed += not ok
            last = out.strip().splitlines()[-1][:150] if out.strip() else ""
            print(f"{'ok  ' if ok else 'FAIL'} {path} [{shell}] {name}: exit {code} (want {want}); {last}")
            subprocess.run(["chmod", "-R", "u+rwx", root]); shutil.rmtree(root)
print("cases failed:", failed); sys.exit(1 if failed else 0)
