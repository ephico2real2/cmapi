#!/usr/bin/env python3
"""The manifests job: nothing floating, each download verified, render's result checked positively, and each test the review
added actually run. From the review of PR #89. Needs PyYAML in this Python. usage: ci-guard.py [<ci.yml>]. Exit 1 on any failure."""
import os, re, sys
import yaml
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".github/workflows/ci.yml")
ci = yaml.safe_load(open(path)); job = ci["jobs"]["manifests"]
steps = job["steps"]; fails = []
def check(ok, label):
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok: fails.append(label)
check(job["runs-on"] == "ubuntu-24.04", "the runner is a named release, not ubuntu-latest")
envs = [v for s in steps for v in (s.get("env") or {}).values() if "raw.githubusercontent" in v]
check(envs and not [e for e in envs if re.search(r"/(master|main)/", e)], "the schema URLs are pinned by commit, not master or main")
runs = "\n".join(s.get("run", "") for s in steps)
downloads = re.findall(r"curl -fsSL -o (\S+) (\S+)", runs)
check(len(downloads) >= 3, f"{len(downloads)} downloads")
for out, url in downloads:
    check(re.search(r'echo "[0-9a-f]{64}  ' + re.escape(out) + r'" \| sha256sum -c -', runs) is not None, f"{out} is verified by SHA-256")
check(ci.get("permissions") == {"contents": "read"} and "permissions" not in job, "contents: read, no widening in the job")
co = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
check((co.get("with") or {}).get("persist-credentials") is False, "persist-credentials: false")
check(all(re.search(r"@[0-9a-f]{40}", s["uses"]) for s in steps if "uses" in s), "actions by full SHA")
check("https://dl.k8s.io" in runs, "kubectl is pinned too: the runner's floats with the runner image")
check("deploy/render-test.sh" in runs, "render.sh's result is checked, not only the absence of the placeholder")
for script in ("deploy/secrets-test.sh", "deploy/tests/ci-guard.py", "deploy/tests/doc12-test.py", "deploy/tests/kind-test-stubbed.sh", "deploy/tests/mutate-secrets.py", "deploy/tests/np-reach-test.sh"):
    check(script in runs, f"the job runs {script}")
shellchecked = next(s["run"] for s in steps if s.get("name") == "Shellcheck")
# The chart path's two scripts leave with the charts (Wave 4), and this job has never checked them.
charts = ("deploy/baseline-crc.sh", "deploy/release-crc.sh")
scripts = [os.path.relpath(os.path.join(d, f), ROOT) for d, _, fs in os.walk(os.path.join(ROOT, "deploy")) for f in fs if f.endswith(".sh") and "helm" not in d]
check("deploy/tests/kind-test-stubs/*" in shellchecked, "shellcheck covers the kind-test stubs")
for f in sorted(set(scripts) - set(charts)):
    check(f in shellchecked or f.rsplit("/", 1)[0] + "/*.sh" in shellchecked, f"shellcheck covers {f}")
print("ci cases failed:", len(fails)); sys.exit(1 if fails else 0)
