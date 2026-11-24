"""cmapi/audit/osv_audit.py tells an advisory from an audit that did not run (#655, the review of #658).

pip-audit 2.10.1 exits 1 for both (measured: a refused connection and an HTTP 503 from OSV are a traceback and exit 1), and
cmapi/audit.sh first reported an OSV outage as an advisory in the set, on the first failed query. The script reads
pip-audit's JSON report: no report is tried three times and is then exit 3, never a pass and never an advisory.

pip-audit is a stub here, a `pip_audit` package on PYTHONPATH that plays one outcome per call, so the test needs no network.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "audit" / "osv_audit.py"
STUB = r'''
import json, os, sys
plan, log = os.environ["STUB_PLAN"].split(","), os.environ["STUB_CALLS"]
call = len(open(log).read().splitlines()) if os.path.exists(log) else 0
open(log, "a").write(" ".join(sys.argv[1:]) + "\n")
outcome, out = plan[min(call, len(plan) - 1)], sys.argv[sys.argv.index("--output") + 1]
vuln = {"id": "PYSEC-2026-1", "fix_versions": ["2.0"], "aliases": ["GHSA-aaaa-bbbb-cccc"]}
twin = {"id": "GHSA-aaaa-bbbb-cccc", "fix_versions": ["2.0"], "aliases": ["PYSEC-2026-1"]}
reports = {"clean": {"dependencies": [{"name": "good", "version": "1.0", "vulns": []}], "fixes": []},
           "advisory": {"dependencies": [{"name": "bad", "version": "1.0", "vulns": [vuln, twin, vuln]}], "fixes": []},
           "advisory-exit-0": {"dependencies": [{"name": "bad", "version": "1.0", "vulns": [vuln]}], "fixes": []},
           "skipped": {"dependencies": [{"name": "odd", "skip_reason": "could not be read"}], "fixes": []},
           "empty": {"dependencies": [], "fixes": []}}
if outcome == "down":
    sys.exit("requests.exceptions.ConnectionError: (stub) OSV is unreachable")       # exit 1 and no report, as pip-audit does
if outcome == "garbage":
    open(out, "w").write("<html>502 Bad Gateway</html>")
    sys.exit(1)
json.dump(reports[outcome], open(out, "w"))
sys.exit(1 if outcome == "advisory" else 0)
'''


def audit(tmp_path: Path, plan: str) -> tuple[int, str, list[str]]:
    """Runs the script with pip-audit playing `plan`, one outcome per call. Returns its exit code, its output and the calls."""
    (tmp_path / "stub" / "pip_audit").mkdir(parents=True)
    (tmp_path / "stub" / "pip_audit" / "__main__.py").write_text(STUB)
    calls = tmp_path / "calls"
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "stub"), "STUB_PLAN": plan, "STUB_CALLS": str(calls),
           "CMAPI_AUDIT_RETRY_SECONDS": "0"}
    r = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "site")], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr, calls.read_text().splitlines() if calls.exists() else []


def test_no_advisory_is_exit_0_from_one_strict_query_of_osv_with_no_ignore_list(tmp_path):
    code, out, calls = audit(tmp_path, "clean")
    assert code == 0 and len(calls) == 1 and "1 packages, 0 advisories, 0 not audited" in out
    assert f"--vulnerability-service osv --path {tmp_path / 'site'} --strict" in calls[0]
    assert "ignore" not in calls[0] and "--osv-url" not in calls[0] and "--dry-run" not in calls[0]


def test_an_advisory_is_exit_1_and_is_listed_once_for_each_of_its_ids(tmp_path):
    code, out, calls = audit(tmp_path, "advisory")
    assert code == 1 and len(calls) == 1
    assert out.count("ADVISORY  bad 1.0  PYSEC-2026-1  fixed in: 2.0") == 1 and "1 packages, 2 advisories" in out


def test_the_report_decides_not_the_exit_code_of_pip_audit(tmp_path):
    assert audit(tmp_path, "advisory-exit-0")[0] == 1


@pytest.mark.parametrize("outcome", ["down", "garbage"])
def test_an_outage_is_tried_three_times_and_is_exit_3_never_a_pass_or_an_advisory(tmp_path, outcome):
    code, out, calls = audit(tmp_path, outcome)
    assert code == 3 and len(calls) == 3
    assert "attempt 3 of 3" in out and "NOT AUDITED" in out and "ADVISORY" not in out


@pytest.mark.parametrize("plan, expected, tries", [("down,clean", 0, 2), ("down,down,clean", 0, 3), ("down,advisory", 1, 2)])
def test_an_answer_after_a_failed_attempt_is_the_answer(tmp_path, plan, expected, tries):
    code, _, calls = audit(tmp_path, plan)
    assert (code, len(calls)) == (expected, tries)


@pytest.mark.parametrize("outcome", ["skipped", "empty"])
def test_a_report_that_audited_nothing_or_skipped_a_package_is_not_a_pass(tmp_path, outcome):
    code, _, calls = audit(tmp_path, outcome)
    assert code == 3 and len(calls) == 1               # OSV answered: asking again would not change it
