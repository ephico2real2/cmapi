"""The checks of the cmapi-cluster-configs repository (#157): examples/cluster-configs/.github/, the workflow that reports the
check runs cmapi's worker waits for on GitHub, and kyverno_check.py, its ci/kyverno. Run on a repository laid out as cmapi writes
it, with CRC's own configuration: the bundle that `cmapi-tools policies render` gives, and a folder that cmapi's renderer gives.

The CLI is the image's pin, v1.20.0. Skipped with no kyverno on PATH; CMAPI_REQUIRE_KYVERNO=1 (CI) fails instead."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from cmapi.core.config import load_instance
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from conftest import EX

ROOT = EX.parent
TEMPLATE = EX / "cluster-configs/.github"
CHECK = TEMPLATE / "scripts/kyverno_check.py"
NS = "abc-ci-test-dev"
# The two contexts the worker waits for on a host with its own CI, read from pr_checks.py's source: importing cmapi.jobs needs
# SQLAlchemy, which the reference-code job's environment (examples/local/requirements.txt) does not install.
PR_CHECKS = (ROOT / "cmapi/src/cmapi/jobs/pr_checks.py").read_text()
CI_CONTEXTS = [re.search(rf'^{name} = "([^"]+)"$', PR_CHECKS, re.M)[1] for name in ("CONTEXT_KUBECONFORM", "CONTEXT_KYVERNO")]
assert re.search(r"^CI_CONTEXTS = \[CONTEXT_KUBECONFORM, CONTEXT_KYVERNO\]$", PR_CHECKS, re.M), "pr_checks.py's CI_CONTEXTS changed"


@pytest.fixture(scope="module")
def kyverno() -> str:
    found = shutil.which("kyverno")
    if not found:
        if os.environ.get("CMAPI_REQUIRE_KYVERNO") == "1":
            pytest.fail("CMAPI_REQUIRE_KYVERNO=1 and no kyverno on PATH")
        pytest.skip("no kyverno on PATH")
    return found


@pytest.fixture(scope="module")
def crc(tmp_path_factory):
    """CRC's instance files, from deploy/manifests/environments/crc/20-config.yaml."""
    d = tmp_path_factory.mktemp("crc-config")
    data = next(yaml.safe_load_all((ROOT / "deploy/manifests/environments/crc/20-config.yaml").read_text()))["data"]
    for name, text in data.items():
        (d / name).write_text(text)
    return load_instance(d, d / "metadata-keys.yaml")


def repository(tmp: Path, cfg, policy: PolicySettings | None = None, **over) -> Path:
    """A cluster-configs checkout: CRC's rendered bundle under policies/ (in CRC's own mode, or `policy`), and one namespace
    folder cmapi rendered, for dev."""
    for rel, text in render_bundle(cfg.tiers, cfg.metadata, policy or cfg.policy, cfg.allowed_environments, cfg.name).items():
        f = tmp / "policies" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    spec = dict(namespace=NS, cluster_id="CRC", instance=cfg.name, env="dev", tier="small", request_id="req-1",
                requested_by_user="cmapi-automation", requested_by_email=None,
                labels={"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1",
                        "cmapi.net/team": "platform"}, annotations={"cmapi.net/team-dl": "platform@ephico2real.com"})
    spec.update(over)
    for rel, text in ManifestRenderer(cfg.tiers, cfg.metadata).render(NamespaceSpec(**spec)).items():
        if text is not None:
            f = tmp / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
    return tmp


def run(root: Path, kyverno: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CHECK), str(root), "--kyverno", kyverno], capture_output=True, text=True, timeout=300)


def edit(path: Path, change) -> None:
    doc = yaml.safe_load(path.read_text())
    change(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False))


def folder(root: Path) -> Path:
    return root / "clusters/CRC/namespaces" / NS


def test_the_workflows_job_names_are_the_check_runs_the_worker_waits_for():
    """A check run of a workflow job takes the job's name: renaming one makes every request wait for syncTimeout and fail."""
    wf = yaml.safe_load((TEMPLATE / "workflows/ci.yml").read_text())
    assert sorted(job["name"] for job in wf["jobs"].values()) == sorted(CI_CONTEXTS)
    assert wf[True]["pull_request"]["branches"] == ["main"], "on: pull_request to main (PyYAML reads the key on as True)"
    assert wf["permissions"] == {"contents": "read"}


def test_the_workflow_pins_the_clis_the_image_pins():
    text = (TEMPLATE / "workflows/ci.yml").read_text()
    containerfile = (ROOT / "cmapi/Containerfile").read_text()
    for arg in ("KYVERNO_VERSION", "KYVERNO_SHA256", "KUBECONFORM_VERSION", "KUBECONFORM_SHA256"):
        value = re.search(rf"^ARG {arg}=(\S+)$", containerfile, re.M)[1]
        assert value in text, f"{arg} {value} is not the workflow's"
    for uses in re.findall(r"uses: (\S+)", text):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", uses), f"{uses} is not pinned by commit"


def test_a_folder_cmapi_renders_passes_its_environments_bundle(kyverno, crc, tmp_path):
    r = run(repository(tmp_path, crc), kyverno)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 namespace folders, 0 errors, 0 warnings" in r.stdout


def test_a_value_beyond_the_bound_fails_on_its_file(kyverno, crc, tmp_path):
    """In enforce the rendered policies Deny, and the check fails the PR on the file."""
    root = repository(tmp_path, crc, PolicySettings(default_mode="enforce"))
    rq = folder(root) / f"resourcequota-{NS}-quota.yaml"
    edit(rq, lambda d: d["spec"]["hard"].update({"requests.cpu": "999"}))
    r = run(root, kyverno)
    assert r.returncode == 1, r.stdout
    assert re.search(rf"::error file=clusters/CRC/namespaces/{NS}/resourcequota-{NS}-quota.yaml::cmapi-quota-dev-quota-requests-cpu-max: ", r.stdout), r.stdout


def test_in_audit_the_same_value_is_a_warning(kyverno, crc, tmp_path):
    """The mode is in the bundle: CRC sets no `policy`, so its rendered policies audit (#342) and the check reports."""
    assert crc.policy.mode_for("dev") == "audit"
    root = repository(tmp_path, crc)
    assert "  validationActions:\n  - Audit\n  - Warn\n" in (root / "policies/env/dev/cmapi-quota-dev.yaml").read_text()
    edit(folder(root) / f"resourcequota-{NS}-quota.yaml", lambda d: d["spec"]["hard"].update({"requests.cpu": "999"}))
    r = run(root, kyverno)
    assert r.returncode == 0, r.stdout
    assert "::warning file=" in r.stdout and "(audit)" in r.stdout and "0 errors, 1 warnings" in r.stdout


def test_a_folder_with_no_environment_fails(kyverno, crc, tmp_path):
    root = repository(tmp_path, crc)
    edit(folder(root) / "namespace.yaml", lambda d: d["metadata"]["labels"].pop("cmapi.net/env"))
    r = run(root, kyverno)
    assert r.returncode == 1 and "no label cmapi.net/env" in r.stdout, r.stdout


def test_a_policy_the_cli_gives_no_result_for_fails(kyverno, crc, tmp_path):
    """The vacuous pass of docs/08: a policy that matches LimitRange and answers for none of them must not read as passed."""
    root = repository(tmp_path, crc)
    f = next((root / "policies/env/dev").glob("cmapi-limits-dev.yaml"))
    # A match on a kind no checked file is, under a name the policy still claims: the CLI then answers nothing for the LimitRanges.
    text = f.read_text()
    first = text.split("\n---\n")[0]
    stray = yaml.safe_load(first)
    stray["spec"]["matchConstraints"]["resourceRules"][0]["apiGroups"] = ["example.invalid"]
    (root / "policies/env/dev/stray.yaml").write_text(yaml.safe_dump({**stray, "metadata": {**stray["metadata"], "name": "stray-limits"}}))
    r = run(root, kyverno)
    assert r.returncode == 1 and "stray-limits gave no result" in r.stdout, r.stdout


def test_an_environment_with_no_bundle_is_kyverno_off(kyverno, crc, tmp_path):
    root = repository(tmp_path, crc)
    shutil.rmtree(root / "policies/env/dev")
    r = run(root, kyverno)
    assert r.returncode == 0 and "Kyverno is off in dev" in r.stdout, r.stdout


BOT = "cmapi-git-bot"
TRAILER = "Cmapi-Request-Id: req-1"


def run_pr_step(root, kyverno, commits, *, fork=False, committer=None, committer_email="user@example.org", merge_head=False):
    """Run the template's check step on a merge checkout with GitHub's PR metadata."""
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=ci@example.org", "-c", "commit.gpgsign=false", *args],
            cwd=root, text=True,
        ).strip()

    shutil.copytree(TEMPLATE, root / ".github")
    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "base")
    branch = "cmapi/CRC/req-1"
    git("switch", "-qc", branch)
    git("add", ".")
    for author, body in commits:
        git("-c", f"user.name={committer or author}", "-c", f"user.email={committer_email}", "commit", "-q",
            "--allow-empty", "--author", f"{author} <user@example.org>", "-m", "change", "-m", body)
    if merge_head:
        # Merge the same two tips on each branch. Only the PR's merge is absent from main.
        git("switch", "-q", "main")
        git("commit", "-q", "--allow-empty", "-m", "main advanced")
        base_tip = git("rev-parse", "HEAD")
        git("merge", "--no-ff", "-qm", "integrate topic on main", branch)
        git("switch", "-q", branch)
        git("-c", f"user.name={BOT}", "merge", "--no-ff", "-qm", f"integrate main on topic\n\n{TRAILER}", base_tip)
    head = git("rev-parse", "HEAD")
    base = git("rev-parse", "main")
    count = int(git("rev-list", "--count", f"{base}..{head}"))
    if merge_head:
        assert count == 1
    git("switch", "-q", "main")
    git("merge", "--no-ff", "-qm", "synthetic merge", head)
    steps = yaml.safe_load((TEMPLATE / "workflows/ci.yml").read_text())["jobs"]["kyverno"]["steps"]
    depth = steps[0].get("with", {}).get("fetch-depth", 1)
    checkout = root.parent / "checkout"
    git("clone", "-q", *([f"--depth={depth}"] if depth else []), root.as_uri(), str(checkout))
    event = root.parent / "event.json"
    event.write_text(json.dumps({"pull_request": {
        "user": {"login": "owner"}, "commits": count,
        "base": {"sha": base, "repo": {"id": 1}}, "head": {"sha": head, "ref": branch, "repo": {"id": 2 if fork else 1}},
    }}))
    path = os.pathsep.join((str(Path(sys.executable).parent), str(Path(kyverno).parent), os.environ["PATH"]))
    return subprocess.run(["bash", "-e", "-c", steps[-1]["run"]], cwd=checkout, capture_output=True, text=True, timeout=300,
                          env={**os.environ, "PATH": path, "GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event)})


@pytest.mark.parametrize(("commits", "fork", "warn"), [
    pytest.param([("Maintainer", TRAILER)], False, False, id="hand-with-trailer"),
    pytest.param([(BOT, TRAILER)], False, True, id="bot"),
    pytest.param([(BOT, TRAILER + "\n\nbody paragraph")], False, False, id="trailer-in-body"),
    pytest.param([(BOT, "Cmapi-Request-Id: req-2")], False, False, id="another-request"),
    pytest.param([(BOT, TRAILER + "\n" + TRAILER)], False, False, id="duplicate-trailer"),
    pytest.param([("Maintainer", ""), (BOT, TRAILER)], False, False, id="mixed"),
    pytest.param([(BOT, TRAILER)], True, False, id="fork"),
])
def test_pr_audit_violation(kyverno, crc, tmp_path, commits, fork, warn):
    root = repository(tmp_path / "origin", crc)
    edit(folder(root) / "namespace.yaml", lambda d: d["metadata"]["labels"].update({"cmapi.net/team": "BAD_Team"}))
    r = run_pr_step(root, kyverno, commits, fork=fork)
    assert r.returncode == (0 if warn else 1), r.stdout + r.stderr
    severity = "warning" if warn else "error"
    assert f"::{severity} file=clusters/CRC/namespaces/{NS}/namespace.yaml::cmapi-metadata-dev-label-cmapi-net-team-pattern" in r.stdout


@pytest.mark.parametrize(("committer", "email"), [
    ("Maintainer", "user@example.org"),
    (BOT, "other@example.org"),
], ids=["different-name", "different-email"])
def test_recommitted_change_uses_hand_pr_checks(kyverno, crc, tmp_path, committer, email):
    root = repository(tmp_path / "origin", crc)
    r = run_pr_step(root, kyverno, [(BOT, TRAILER)], committer=committer, committer_email=email)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "audit violations fail the check" in r.stdout


def test_one_commit_pr_with_a_merge_head_uses_hand_pr_checks(kyverno, crc, tmp_path):
    root = repository(tmp_path / "origin", crc)
    r = run_pr_step(root, kyverno, [(BOT, TRAILER)], merge_head=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "audit violations fail the check" in r.stdout


@pytest.mark.parametrize("author", ["Maintainer", BOT])
def test_pr_uncompilable_policy_fails(kyverno, crc, tmp_path, author):
    root = repository(tmp_path / "origin", crc)
    policy = root / "policies/env/dev/broken.yaml"
    doc = next(yaml.safe_load_all((root / "policies/env/dev/cmapi-metadata-dev.yaml").read_text()))
    doc["metadata"]["name"] = "broken"
    doc["spec"]["validations"] = [{"expression": "missingFunction(object)"}]
    policy.write_text(yaml.safe_dump(doc))
    r = run_pr_step(root, kyverno, [(author, TRAILER)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::error file=" in r.stdout and "broken" in r.stdout, r.stdout
