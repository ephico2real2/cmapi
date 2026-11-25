#!/usr/bin/env python3
"""One installed set against OSV, for cmapi/audit.sh (#655).

    python osv_audit.py <site-packages>     exit 0: no advisory.  1: an advisory.  3: the set could not be audited.

pip-audit exits 1 for an advisory, and also for a query that failed: measured on 2.10.1, a refused connection and an HTTP
503 from OSV are a traceback and exit 1. So the answer is read from its JSON report, which pip-audit writes only after OSV
answered for every package. A run that leaves no report is tried again, ATTEMPTS times in all, and then is exit 3. An outage
therefore never passes, and is never reported as an advisory.

It runs in the audit's own environment, where pip-audit comes from its hashed lock (cmapi/audit/requirements.txt). There is
no ignore list. CMAPI_AUDIT_RETRY_SECONDS is the wait before the second attempt (10 unless set); the third waits twice that.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ATTEMPTS = 3
NO_ADVISORY, ADVISORY, NOT_AUDITED = 0, 1, 3


def report_of(site: str, path: Path) -> dict | None:
    """pip-audit's JSON report on `site`, or None when it wrote none. Its own error is then on stderr: OSV or the network
    failed, or (--strict) a package could not be read."""
    path.unlink(missing_ok=True)
    subprocess.run([sys.executable, "-m", "pip_audit", "--vulnerability-service", "osv", "--path", site, "--strict",
                    "--aliases", "on", "--desc", "off", "--progress-spinner", "off", "--format", "json", "--output", str(path)],
                   check=False)
    try:
        report = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) and isinstance(report.get("dependencies"), list) else None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    wait = float(os.environ.get("CMAPI_AUDIT_RETRY_SECONDS", "10"))
    with tempfile.TemporaryDirectory(prefix="cmapi-osv-audit.") as work:
        for attempt in range(1, ATTEMPTS + 1):
            report = report_of(argv[0], Path(work) / "report.json")
            if report is not None:
                break
            print(f"osv_audit: no report from pip-audit, attempt {attempt} of {ATTEMPTS}; its error is above", file=sys.stderr)
            if attempt < ATTEMPTS:
                time.sleep(wait * attempt)
        else:
            print("osv_audit: NOT AUDITED: pip-audit gave no answer. Nothing is known about this set: a failure, not a pass",
                  file=sys.stderr)
            return NOT_AUDITED
    packages = report["dependencies"]
    # --strict makes pip-audit stop on a package it cannot read, so a skipped one is not expected; it is never a pass.
    skipped = [f"{p.get('name')}: {p.get('skip_reason')}" for p in packages if "skip_reason" in p]
    # OSV holds an advisory once under each of its IDs (PYSEC and GHSA), so pip-audit lists it twice: one row per ID here.
    rows = sorted({(p["name"], p["version"], v["id"], ", ".join(v.get("fix_versions") or []) or "none",
                    ", ".join(sorted(v.get("aliases") or []))) for p in packages for v in p.get("vulns") or []})
    for row in rows:
        print("  ADVISORY  {} {}  {}  fixed in: {}  ({})".format(*row))
    for line in skipped:
        print(f"  NOT AUDITED  {line}")
    print(f"osv_audit: {len(packages)} packages, {len(rows)} advisories, {len(skipped)} not audited")
    if rows:
        return ADVISORY
    return NOT_AUDITED if skipped or not packages else NO_ADVISORY


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
