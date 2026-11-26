"""Peak RSS of the Kyverno CLI as cmapi runs it (core/validate/__init__.py, CliValidator._kyverno), one or N at once."""
import json, os, subprocess, sys, time
res = "/m/res"
files = ",".join(f"{res}/{f}" for f in sorted(os.listdir(res)) if "rolebinding" not in f)
cmd = ["/m/dl/kyverno", "apply", "/m/pol", "--resource", files, "-p", "--output-format", "json"]
kc = ["/m/dl/kubeconform", "-strict", "-summary", "-output", "json", "-skip", "RoleBinding"] + [f"{res}/{f}" for f in sorted(os.listdir(res)) if "rolebinding" not in f]

def per_child(n, argv):
    """Each child's own peak (wait4's rusage), in MiB."""
    t0 = time.monotonic()
    procs = [subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(n)]
    peaks, rcs, cpu = [], [], []
    for p in procs:
        _, status, ru = os.wait4(p.pid, 0)
        p.returncode = os.waitstatus_to_exitcode(status)
        peaks.append(ru.ru_maxrss / 1024); rcs.append(p.returncode); cpu.append(ru.ru_utime + ru.ru_stime)
    return time.monotonic() - t0, peaks, rcs, cpu

which = sys.argv[1]
n = int(sys.argv[2])
argv = cmd if which == "kyverno" else kc
if n == 0:
    rc = subprocess.run(argv, capture_output=True, text=True)
    print(rc.returncode); print(rc.stdout[:1500]); print(rc.stderr[:500]); sys.exit()
wall, peaks, rcs, cpu = per_child(n, argv)
cg = open("/sys/fs/cgroup/memory.peak").read().strip() if os.path.exists("/sys/fs/cgroup/memory.peak") else "n/a"
print(json.dumps({"tool": which, "n": n, "wall_s": round(wall, 2), "rc": rcs, "cpu_s_each": [round(c, 2) for c in cpu], "env": {k: v for k, v in os.environ.items() if k.startswith("GO")},
                  "peak_rss_mib_each": [round(p, 1) for p in peaks], "max_mib": round(max(peaks), 1),
                  "sum_mib": round(sum(peaks), 1), "cgroup_memory_peak_mib": round(int(cg) / 2**20, 1) if cg != "n/a" else cg}))
