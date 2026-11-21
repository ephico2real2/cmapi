"""#337: the API contract report of a Helm values change (cmapi/contract/report.py), on the real chart, the real helm, the real
oasdiff and the real cmapi-tools.

Base is this repository's deploy/environments/crc.yaml; each case writes the head. A required label added through the value
`metadata` shows as a new required request property and exits 0, since the report never fails on a change. A change that
leaves metadata-keys.yaml alone runs no diff. A broken or missing tool, or a head that cmapi refuses, exits 1 with an error
annotation. Skipped with no helm or oasdiff on PATH; CMAPI_REQUIRE_OASDIFF=1 (the service job) fails instead.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import ROOT

REPO = ROOT.parent
REPORT = ROOT / "contract" / "report.py"
CHART = REPO / "deploy/helm/cmapi"
CRC = "deploy/environments/crc.yaml"
DIGEST = "sha256:" + "a" * 64
HELM_ARGS = f"--set cmapi.digest={DIGEST} --set cmapi_portal.digest={DIGEST} --set trustedCA.certificates=render-only"
NEW_LABEL = {"enum": ["public", "internal", "restricted"], "title": "Data class",
             "description": "The class of data the namespace holds", "example": "internal"}


@pytest.fixture(scope="module")
def tools() -> None:
    missing = [t for t in ("helm", "oasdiff") if not shutil.which(t)]
    if missing:
        if os.environ.get("CMAPI_REQUIRE_OASDIFF") == "1":
            pytest.fail(f"CMAPI_REQUIRE_OASDIFF=1 and no {missing} on PATH")
        pytest.skip(f"no {missing} on PATH")


def cmapi_tools() -> str:
    """The console entry point with this Python; the report splits the command with shlex."""
    return shlex.join([sys.executable, "-c", "from cmapi.tools import run; run()"])


def tree(path: Path, crc_text: str | None) -> Path:
    if crc_text is not None:
        (path / "deploy/environments").mkdir(parents=True)
        (path / CRC).write_text(crc_text)
    else:
        path.mkdir(parents=True)
    return path


def crc() -> str:
    return (REPO / CRC).read_text()


def with_values(extra: dict) -> str:
    """crc.yaml with more values, as an operator adds them at its end. JSON is YAML that every reader types alike."""
    return crc() + "\n" + "".join(f"{k}: {json.dumps(v)}\n" for k, v in extra.items())


def chart_keys_with_label() -> dict:
    keys = yaml.safe_load((CHART / "config/metadata-keys.yaml").read_text())
    keys["requiredLabels"]["cmapi.net/data-class"] = NEW_LABEL
    return keys


ABSENT = None   # a side without crc.yaml


def report(tmp_path: Path, head: str | None, base: str | None = "crc", env: dict | None = None,
           values: str = "deploy/environments/*.yaml", cwd: Path | None = None,
           plant: str | None = None) -> tuple[subprocess.CompletedProcess, str]:
    base_dir = tree(tmp_path / "base", crc() if base == "crc" else base)
    head_dir = tree(tmp_path / "head", head)
    if plant is not None:
        (head_dir / ".oasdiff.yaml").write_text(plant)
    summary = tmp_path / "summary.md"
    r = subprocess.run([sys.executable, str(REPORT), "--base", str(base_dir), "--head", str(head_dir), "--values", values,
                        "--chart-base", str(CHART), "--chart-head", str(CHART), "--helm-args", HELM_ARGS,
                        "--summary", str(summary)],
                       capture_output=True, text=True, timeout=600, cwd=cwd or tmp_path,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "CMAPI_TOOLS": cmapi_tools(), **(env or {})})
    return r, summary.read_text() if summary.exists() else ""


def stub(tmp_path: Path, name: str, code: int) -> str:
    path = tmp_path / "stubs" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(f"#!/bin/sh\necho '{name} stub failed' >&2\nexit {code}\n")
    path.chmod(0o755)
    return str(path)


def test_a_required_label_shows_as_a_new_required_field_and_passes(tools, tmp_path):
    r, summary = report(tmp_path, with_values({"metadata": chart_keys_with_label()}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "- :warning: added the new required request property `labels/cmapi.net/data-class`" in summary, summary
    # oasdiff's headings sit three levels under the report's heading of the values file.
    assert "\n###### POST /api/v1/clusters/{cluster_id}/namespaces\n" in summary
    assert "\n# API Changelog" not in summary and "\n#### API Changelog" in summary
    assert ("::warning file=deploy/environments/crc.yaml,title=API contract::1 breaking (error), 0 possibly breaking "
            "(warning)") in r.stdout, r.stdout


def test_an_optional_key_is_reported_and_is_not_breaking(tools, tmp_path):
    keys = yaml.safe_load((CHART / "config/metadata-keys.yaml").read_text())
    keys["extraLabels"]["keys"]["cmapi.net/data-class"] = NEW_LABEL
    r, summary = report(tmp_path, with_values({"metadata": keys}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "added the new optional request property `labels/cmapi.net/data-class`" in summary, summary
    assert "::notice file=deploy/environments/crc.yaml,title=API contract::0 breaking (error), 0 possibly breaking" in r.stdout


def test_a_change_that_leaves_metadata_keys_alone_runs_no_diff(tools, tmp_path):
    """oasdiff is a stub that fails: the run passes only because no document was compared."""
    head = crc().replace("displayName: Non-production (CRC)", "displayName: Non-production (CRC, renamed)")
    assert head != crc()
    r, summary = report(tmp_path, head, env={"OASDIFF": stub(tmp_path, "oasdiff", 102)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "metadata-keys.yaml is the same on both sides: the API document does not change" in summary
    assert "::" not in r.stdout


def test_a_broken_oasdiff_fails_loudly(tools, tmp_path):
    r, summary = report(tmp_path, with_values({"metadata": chart_keys_with_label()}),
                        env={"OASDIFF": stub(tmp_path, "oasdiff", 102)})
    assert r.returncode == 1
    assert "**The report failed.**" in summary and "exited 102" in summary
    assert "::error file=deploy/environments/crc.yaml,title=API contract report failed::oasdiff changelog -f json exited 102" in r.stdout


def test_a_broken_cmapi_tools_fails_loudly(tools, tmp_path):
    r, _ = report(tmp_path, with_values({"metadata": chart_keys_with_label()}),
                  env={"CMAPI_TOOLS": stub(tmp_path, "cmapi-tools", 2)})
    assert r.returncode == 1
    assert "::error file=deploy/environments/crc.yaml,title=API contract report failed::cmapi-tools openapi render of the base" in r.stdout


def test_a_missing_helm_fails_loudly(tools, tmp_path):
    r, _ = report(tmp_path, with_values({"metadata": chart_keys_with_label()}), env={"HELM": str(tmp_path / "no-helm")})
    assert r.returncode == 1
    assert "is not installed" in r.stdout


def test_a_head_that_cmapi_refuses_fails_with_the_loaders_message(tools, tmp_path):
    """configFiles text passes Helm's schema unread; cmapi's loader refuses a required key with no example (#332)."""
    text = (CHART / "config/metadata-keys.yaml").read_text().replace(
        "requiredLabels:\n", 'requiredLabels:\n  cmapi.net/data-class: {pattern: "^[a-z]{2,20}$"}\n', 1)
    r, summary = report(tmp_path, with_values({"configFiles": {"metadata-keys.yaml": text}}))
    assert r.returncode == 1, r.stdout
    assert "cmapi refuses the head metadata-keys.yaml of deploy/environments/crc.yaml" in summary
    assert "cmapi.net/data-class" in summary


def test_a_planted_oasdiff_config_changes_nothing(tools, tmp_path):
    """oasdiff reads .oasdiff.* from its working directory; `fail-on: INFO` there would turn this report into exit 1."""
    work = tmp_path / "workspace"
    work.mkdir()
    (work / ".oasdiff.yaml").write_text("fail-on: INFO\n")
    r, summary = report(tmp_path, with_values({"metadata": chart_keys_with_label()}), cwd=work, plant="fail-on: INFO\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "added the new required request property" in summary


def test_a_values_file_that_the_change_adds_is_rendered_and_passes(tools, tmp_path):
    r, summary = report(tmp_path, crc(), base=ABSENT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Added by this change: no base document to compare" in summary
    assert "::notice file=deploy/environments/crc.yaml,title=API contract::Added" in r.stdout


def test_a_values_file_that_the_change_removes_passes(tools, tmp_path):
    r, summary = report(tmp_path, ABSENT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Removed by this change: no document to compare" in summary


def test_no_values_file_fails(tools, tmp_path):
    r, _ = report(tmp_path, crc(), values="deploy/nothing/*.yaml")
    assert r.returncode == 1
    assert "no values file matches" in r.stdout
