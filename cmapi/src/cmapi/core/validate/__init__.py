"""The Validator (core/ports.py): the Kyverno CLI bundle and kubeconform on the rendered files.

Runs at plan time in the API and again in the worker's PR checks on the PR head, so the same
checks a Git host's CI would run are applied to exactly the files the PR carries. Both binaries
are baked into the image (Containerfile) with pinned versions and checksums.

Lessons kept from examples/local (docs/08): the Kyverno 1.16 CLI applies 0 rules to a
policies.kyverno.io/v1 document and reports no failure, so a check whose output says
"Applying 0 policy rule(s)" is a failure, never a vacuous pass. A policy under env/prod runs
only for prod namespaces. A missing binary is a finding with source cmapi, so a broken image
cannot approve anything.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

from cmapi.core.ports import Finding


class ValidatorUnavailable(RuntimeError):
    """The check could not run (a schema download failed). Not a verdict on the files: retry, never refuse."""


class CliValidator:
    def __init__(self, policies_dir: str | Path, *, kubeconform: str = "kubeconform", kyverno: str = "kyverno",
                 schema_location: str | None = None, kubernetes_version: str | None = None, timeout: float = 60.0):
        self.policies = sorted(p for p in Path(policies_dir).rglob("*.yaml")) if Path(policies_dir).exists() else []
        self.kubeconform, self.kyverno, self.timeout = kubeconform, kyverno, timeout
        self.schema_location, self.kubernetes_version = schema_location, kubernetes_version

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)

    def validate(self, files: Mapping[str, str | None], cluster_id: str, environment: str) -> list[Finding]:
        live = {p: t for p, t in files.items() if t}
        if not live:
            return []
        out: list[Finding] = []
        with tempfile.TemporaryDirectory(prefix="cmapi-validate-") as d:
            paths: dict[str, str] = {}
            for p, t in live.items():
                f = Path(d) / p.replace("/", "__")
                f.write_text(t)
                paths[p] = str(f)
            out.extend(self._kubeconform(paths))
            out.extend(self._kyverno(paths, environment))
        return out

    def _kubeconform(self, paths: Mapping[str, str]) -> list[Finding]:
        if shutil.which(self.kubeconform) is None:
            return [Finding("cmapi", "validator", "", f"{self.kubeconform} is not installed in this image")]
        cmd = [self.kubeconform, "-strict", "-summary", "-output", "json"]
        if self.schema_location:
            cmd += ["-schema-location", self.schema_location]
        if self.kubernetes_version:
            cmd += ["-kubernetes-version", self.kubernetes_version]
        r = self._run(cmd + list(paths.values()))
        try:
            report = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            return [Finding("cmapi", "validator", "", f"kubeconform output unreadable: {(r.stderr or r.stdout)[:200]}")]
        by_file = {v: k for k, v in paths.items()}
        out = []
        for res in report.get("resources", []):
            if res.get("status") == "statusError" and "failed downloading schema" in res.get("msg", ""):
                raise ValidatorUnavailable(f"kubeconform could not fetch a schema: {res['msg'][:200]}")
            if res.get("status") in ("statusInvalid", "statusError"):
                out.append(Finding("kubeconform", "schema", by_file.get(res["filename"], res["filename"]), res.get("msg", "")))
        if r.returncode != 0 and not out:
            out.append(Finding("cmapi", "validator", "", f"kubeconform exited {r.returncode}: {(r.stderr or r.stdout)[:200]}"))
        return out

    def _kyverno(self, paths: Mapping[str, str], environment: str) -> list[Finding]:
        ns_files = {p: f for p, f in paths.items() if p.endswith("namespace.yaml")}
        if not ns_files:
            return []
        if shutil.which(self.kyverno) is None:
            return [Finding("cmapi", "validator", "", f"{self.kyverno} is not installed in this image")]
        policies = [p for p in self.policies if environment == "prod" or "env/prod" not in str(p).replace("\\", "/")]
        out = []
        for pol in policies:
            for rel, f in ns_files.items():
                r = self._run([self.kyverno, "apply", str(pol), "--resource", f])
                text = r.stdout + r.stderr
                if "Applying 0 policy rule" in text:
                    out.append(Finding("kyverno", pol.stem, rel, "policy not understood by the CLI (0 rules applied)"))
                elif r.returncode != 0 or "fail: 0" not in text:
                    last = [ln for ln in text.strip().splitlines() if ln.strip()]
                    out.append(Finding("kyverno", pol.stem, rel, (last[-1] if last else f"exit {r.returncode}")[:300]))
        return out
