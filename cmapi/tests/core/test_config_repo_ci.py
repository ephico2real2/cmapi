"""The checks of the cmapi-cluster-configs repository (#157): examples/cluster-configs/.github/, the workflow that reports the
check runs cmapi's worker waits for on GitHub, and kyverno_check.py, its ci/kyverno. Run on a repository laid out as cmapi writes
it, with CRC's own configuration: the bundle that `cmapi-tools policies render` gives, and a folder that cmapi's renderer gives.

The CLI is the image's pin, v1.20.0. Skipped with no kyverno on PATH; CMAPI_REQUIRE_KYVERNO=1 (CI) fails instead."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from cmapi.core.config import load_instance
from cmapi.core.policygen import render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from cmapi.jobs.pr_checks import CI_CONTEXTS
from conftest import EX

ROOT = EX.parent
TEMPLATE = EX / "cluster-configs/.github"
CHECK = TEMPLATE / "scripts/kyverno_check.py"
NS = "cmapi-ci-test"


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


def repository(tmp: Path, cfg, **over) -> Path:
    """A cluster-configs checkout: CRC's rendered bundle under policies/, and one namespace folder cmapi rendered, for dev."""
    for rel, text in render_bundle(cfg.tiers, cfg.metadata, cfg.policy, cfg.allowed_environments, cfg.name).items():
        f = tmp / "policies" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    spec = dict(namespace=NS, cluster_id="CRC", instance=cfg.name, env="dev", tier="small", request_id="req-1",
                requested_by_user="cmapi-automation", requested_by_email=None,
                labels={"cmapi.net/team": "platform"}, annotations={"cmapi.net/team-dl": "platform@ephico2real.com"})
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
    root = repository(tmp_path, crc)
    rq = folder(root) / f"resourcequota-{NS}-quota.yaml"
    edit(rq, lambda d: d["spec"]["hard"].update({"requests.cpu": "999"}))
    r = run(root, kyverno)
    assert r.returncode == 1, r.stdout
    assert re.search(rf"::error file=clusters/CRC/namespaces/{NS}/resourcequota-{NS}-quota.yaml::cmapi-quota-dev-quota-requests-cpu-max: ", r.stdout), r.stdout


def test_in_audit_the_same_value_is_a_warning(kyverno, crc, tmp_path):
    """The mode is in the bundle: a rendered policy of an environment in audit has validationActions [Audit]."""
    root = repository(tmp_path, crc)
    for f in (root / "policies/env/dev").glob("*.yaml"):
        f.write_text(f.read_text().replace("  validationActions:\n  - Deny\n", "  validationActions:\n  - Audit\n"))
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
