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
downloads = re.findall(r"curl -fsSL --retry \d+ -o (\S+) (\S+)", runs)    # --retry: a transient 503 is tried again (#609)
check(len(downloads) >= 3, f"{len(downloads)} downloads")
for out, url in downloads:
    check(re.search(r'echo "[0-9a-f]{64}  ' + re.escape(out) + r'" \| sha256sum -c -', runs) is not None, f"{out} is verified by SHA-256")
check(ci.get("permissions") == {"contents": "read"} and "permissions" not in job, "contents: read, no widening in the job")
co = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
check((co.get("with") or {}).get("persist-credentials") is False, "persist-credentials: false")
check(all(re.search(r"@[0-9a-f]{40}", s["uses"]) for s in steps if "uses" in s), "actions by full SHA")
check("https://dl.k8s.io" in runs, "kubectl is pinned too: the runner's floats with the runner image")
check("deploy/render-test.sh" in runs, "render.sh's result is checked, not only the absence of the placeholder")
for script in ("deploy/tests/ldap-identities-test.sh", "deploy/secrets-test.sh", "deploy/tests/ci-guard.py", "deploy/tests/download-retry-test.py", "deploy/tests/doc12-test.py", "deploy/tests/kind-test-stubbed.sh", "deploy/tests/db-probe-test.py", "deploy/tests/mutate-secrets.py", "deploy/tests/np-reach-test.sh", "deploy/tests/crc-guard-test.py", "deploy/tests/crc-scripts-test.sh", "deploy/tests/crc-backup-test.sh", "deploy/tests/doc13-test.py", "deploy/tests/realm-test.py", "deploy/tests/oidc-login-test.py"):
    check(script in runs, f"the job runs {script}")
# #90, twice now: GNU's stat -f writes the file system's details on stdout before it fails, so "stat -f ... || stat -c ..." on Linux gives both. -c goes first, wherever a script reads a mode.
bsd_first = [f"{os.path.relpath(os.path.join(d, f), ROOT)}:{n}" for d, _, fs in os.walk(os.path.join(ROOT, "deploy")) for f in fs if f.endswith((".sh", ".py")) and f != "ci-guard.py"
             for n, line in enumerate(open(os.path.join(d, f), errors="replace"), 1) if not line.lstrip().startswith("#") and re.search(r"\bstat -f\b", line) and not re.search(r"\bstat -c\b.*\bstat -f\b", line)]
check(not bsd_first, f"stat -c before stat -f: {bsd_first}")
shellchecked = next(s["run"] for s in steps if s.get("name") == "Shellcheck")
# The chart path's two scripts leave with the charts (Wave 4), and this job has never checked them.
charts = ("deploy/baseline-crc.sh", "deploy/release-crc.sh")
scripts = [os.path.relpath(os.path.join(d, f), ROOT) for d, _, fs in os.walk(os.path.join(ROOT, "deploy")) for f in fs if f.endswith(".sh") and "helm" not in d]
check("deploy/tests/kind-test-stubs/*" in shellchecked, "shellcheck covers the kind-test stubs")
check("examples/cmapi-sso/ldap/apply-test-identities.sh" in shellchecked, "shellcheck covers the script that writes to the shared LDAP")
for f in sorted(set(scripts) - set(charts)):
    check(f in shellchecked or f.rsplit("/", 1)[0] + "/*.sh" in shellchecked, f"shellcheck covers {f}")
# The images job (#545): the only job that may write, with only what it needs; it pushes from main alone, one manifest per tag.
images = ci["jobs"].get("images") or {}
isteps = images.get("steps") or []
check(images.get("runs-on") == "ubuntu-24.04", "images: the runner is a named release")
check(images.get("permissions") == {"contents": "read", "packages": "write", "id-token": "write", "attestations": "write"}, "images: contents read; packages, id-token and attestations write; nothing else")
check([n for n, j in ci["jobs"].items() if "permissions" in j] == ["images"], "images is the only job that widens the token")
check(bool(isteps) and all(re.search(r"@[0-9a-f]{40}$", s["uses"]) for s in isteps if "uses" in s), "images: actions by full SHA")
ico = next((s for s in isteps if s.get("uses", "").startswith("actions/checkout")), {})
check((ico.get("with") or {}).get("persist-credentials") is False, "images: persist-credentials: false")
publish_if = "github.event_name == 'push' && github.ref == 'refs/heads/main' && github.repository == 'ephico2real2/cmapi'"
check(images.get("if") == publish_if, "only a main push in the upstream repository starts the write-enabled job")
pr = ci["jobs"].get("images-pr", {})
check(pr.get("if") == "github.event_name == 'pull_request'" and "permissions" not in pr, "PR builds inherit contents: read")
matrix = (images.get("strategy") or {}).get("matrix", {}).get("include", [])
check({entry["name"] for entry in matrix} == {"cmapi", "cmapi-portal"} and pr.get("strategy") == images.get("strategy"), "PR and publisher build both images")
def build_step(steps):
    return next((s for s in steps if s.get("uses", "").startswith("docker/build-push-action@")), {})
pr_build = build_step(pr.get("steps", [])).get("with", {})
check(pr_build.get("push") is False and "outputs" not in pr_build, "PR builds have no registry export")
bw = build_step(isteps).get("with", {})
check(bw.get("outputs") == "type=image,name=${{ env.IMAGE }},push-by-digest=true,name-canonical=true,push=true"
      and "tags" not in bw, "the build exports by digest before making a deployable tag")
check(bw.get("provenance") is False and bw.get("sbom") is False, "images: no buildx attestations, so a tag is one manifest")
check(bw.get("platforms") == "linux/amd64", "images: linux/amd64, CRC's platform")
check(all(a in bw.get("build-args", "") for a in ("GIT_COMMIT=${{ steps.meta.outputs.commit }}", "BUILD_VERSION=${{ steps.meta.outputs.version }}")), "images: the build args of the revision label and the version")
check("commit=$(git rev-parse --short=10 HEAD)" in "\n".join(s.get("run", "") for s in isteps), "images: the commit is the 10-character one crc-image.sh and crc-proof.sh compare")
attest = next((s for s in isteps if s.get("uses", "").startswith("actions/attest@")), {}).get("with") or {}
check(attest.get("subject-digest") == "${{ steps.build.outputs.digest }}" and attest.get("subject-name") == "${{ env.IMAGE }}", "images: the attestation is of the pushed digest")
verify = next((s for s in isteps if "imagetools inspect" in s.get("run", "")), {})
verify_run = verify.get("run", "")
check('ref="$IMAGE@$DIGEST"' in verify_run and verify_run.count('imagetools inspect "$ref"') == 2
      and verify.get("env", {}).get("DIGEST") == "${{ steps.build.outputs.digest }}",
      "the descriptor and label are read from the same pushed digest")
sign = next((s for s in isteps if s.get("uses", "").startswith("actions/attest@")), {})
publish = next((s for s in isteps if "imagetools create" in s.get("run", "")), {})
check(bool(sign and verify and publish) and isteps.index(build_step(isteps)) < isteps.index(verify) < isteps.index(sign) < isteps.index(publish)
      and 'imagetools create --prefer-index=false --tag "$tag" "$IMAGE@$DIGEST"' in publish["run"]
      and publish.get("env", {}).get("DIGEST") == "${{ steps.build.outputs.digest }}" and "if" not in publish,
      "only a verified, successfully attested digest becomes the deployment tag")
# #655: the dependency audit runs on every change with the command a developer runs, and what the image and the service tests
# install comes from the hashed lock, so the audited set is the shipped one.
audit = ci["jobs"].get("dependency-audit") or {}
asteps = audit.get("steps") or []
check(audit.get("runs-on") == "ubuntu-24.04" and "if" not in audit and "permissions" not in audit,
      "dependency-audit: a named runner, every pull request and push, contents: read")
check(bool(asteps) and all(re.search(r"@[0-9a-f]{40}$", s["uses"]) for s in asteps if "uses" in s), "dependency-audit: actions by full SHA")
check(any(s.get("run", "").strip() == "cmapi/audit.sh python" for s in asteps), "dependency-audit: runs cmapi/audit.sh")
service_install = next((s.get("run", "") for s in ci["jobs"]["service"]["steps"] if s.get("name") == "Install"), "")
check("--require-hashes" in service_install and "-r cmapi/requirements.txt" in service_install,
      "service: the tests run on the image's hashed lock")
containerfile = open(os.path.join(ROOT, "cmapi/Containerfile")).read()
pip_lines = re.findall(r"pip install [^\n]*", containerfile)
check(any("--require-hashes" in line and "-r requirements.txt" in line for line in pip_lines)
      and all("--no-deps" in line for line in pip_lines), "the image installs the hashed lock, and nothing else resolves")
print("ci cases failed:", len(fails)); sys.exit(1 if fails else 0)
