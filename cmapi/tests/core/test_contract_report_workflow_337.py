"""#337: the two workflows of the API contract report, read as data. The reusable one (api-contract-report.yml) runs a
values repository's report; this repository's caller (values-contract-report.yml) runs it on a change of the inputs of the
ConfigMap's metadata-keys.yaml.

What must hold: the report is a pull_request job at contents: read and never pull_request_target; it is not a ci/* check;
every action is pinned by commit; oasdiff is the api-contract job's version and SHA-256, never with --fail-on or --open;
no ${{ }} expression is expanded inside a shell script; cmapi-ref is checked to be a commit; and the caller's paths are the
files that the chart's templates/config.yaml reads for metadata-keys.yaml.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from conftest import EX

ROOT = EX.parent
WORKFLOWS = ROOT / ".github/workflows"
REUSABLE = WORKFLOWS / "api-contract-report.yml"
CALLER = WORKFLOWS / "values-contract-report.yml"


def load(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text())
    doc["on"] = doc.pop(True)   # PyYAML reads the key on as True
    return doc


def steps(doc: dict) -> list[dict]:
    return [s for job in doc["jobs"].values() for s in job.get("steps", [])]


def test_the_reusable_workflow_is_only_called():
    doc = load(REUSABLE)
    assert list(doc["on"]) == ["workflow_call"]
    assert set(doc["on"]["workflow_call"]["inputs"]) == {"values-files", "helm-args", "cmapi-ref", "cmapi-repository"}
    assert doc["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in doc["jobs"].values()), "no job widens the token"


def test_the_report_is_not_a_check_that_anything_waits_for():
    names = [job["name"] for job in load(REUSABLE)["jobs"].values()]
    assert names == ["report/api-contract"]
    assert not any(n.startswith("ci/") for n in names), "ci/* names are the checks cmapi's worker waits for"


def test_the_caller_runs_on_a_pull_request_that_changes_what_the_configmap_reads():
    doc = load(CALLER)
    assert list(doc["on"]) == ["pull_request"]
    paths = doc["on"]["pull_request"]["paths"]
    assert paths == ["deploy/environments/**", "deploy/helm/cmapi/config/metadata-keys.yaml",
                     "deploy/helm/cmapi/values.yaml", "deploy/helm/cmapi/templates/config.yaml"]
    template = (ROOT / "deploy/helm/cmapi/templates/config.yaml").read_text()
    assert '"metadata-keys.yaml"' in template and 'printf "config/%s"' in template, "the ConfigMap's sources moved"
    assert doc["permissions"] == {"contents": "read"}
    (job,) = doc["jobs"].values()
    assert job["uses"] == "./.github/workflows/api-contract-report.yml"
    assert job["with"]["values-files"] == "deploy/environments/*.yaml"
    assert "cmapi-ref" not in job["with"], "in this repository the report renders with the change's own chart and code"


def test_no_workflow_runs_on_pull_request_target():
    for path in WORKFLOWS.glob("*.yml"):
        assert "pull_request_target" not in load(path)["on"], path.name


def test_actions_are_pinned_by_commit_and_checkouts_keep_no_credential():
    for path in (REUSABLE, CALLER):
        for s in steps(load(path)):
            if "uses" in s:
                assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", s["uses"]), f"{path.name}: {s['uses']}"
            if s.get("uses", "").startswith("actions/checkout@"):
                assert s["with"]["persist-credentials"] is False, path.name


def test_oasdiff_is_the_api_contract_jobs_pin_and_never_gates():
    ci = (WORKFLOWS / "ci.yml").read_text()
    text = REUSABLE.read_text()
    url = re.search(r"https://github.com/oasdiff/oasdiff/releases/download/\S+", ci)[0]
    sha = re.search(r'echo "([0-9a-f]{64})  oasdiff.tar.gz"', ci)[1]
    assert url in text and f'echo "{sha}  $RUNNER_TEMP/oasdiff.tar.gz" | sha256sum -c -' in text
    report = (ROOT / "cmapi/contract/report.py").read_text()
    assert "--fail-on" not in text and "--open" not in text
    assert '"--fail-on' not in report and '"--open' not in report, "no argument of the report's oasdiff gates or uploads"
    assert '"--allow-external-refs=false"' in report


def test_no_expression_is_expanded_in_a_shell_script():
    """Inputs reach a script through env, so no value can become shell syntax (GitHub, security hardening for Actions)."""
    for path in (REUSABLE, CALLER):
        for s in steps(load(path)):
            assert "${{" not in s.get("run", ""), f"{path.name}: {s.get('name')}"


def test_cmapi_ref_must_be_a_commit():
    doc = load(REUSABLE)
    check = next(s for s in steps(doc) if s.get("name") == "cmapi-ref is a commit")
    assert check["if"] == "inputs.cmapi-ref != ''" and check["env"]["REF"] == "${{ inputs.cmapi-ref }}"
    assert '[[ "$REF" =~ ^[0-9a-f]{40}$ ]]' in check["run"]
    pinned = next(s for s in steps(doc) if s.get("with", {}).get("path") == "cmapi-src")
    assert pinned["with"]["ref"] == "${{ inputs.cmapi-ref }}"
