"""The Validator (core/ports.py): the Kyverno CLI bundle and kubeconform on the rendered files.

Runs at plan time in the API and again in the worker's PR checks on the PR head, so the same
checks a Git host's CI would run are applied to exactly the files the PR carries. Both binaries
are baked into the image (Containerfile) with pinned versions and checksums.

Lessons kept from examples/local (docs/08): the Kyverno 1.16 CLI applied 0 rules to a
policies.kyverno.io/v1 document and reported no failure, so a check whose output says
"Applying 0 policy rule(s)" is a failure, never a vacuous pass; the guard stays with the 1.20 CLI, which applies them.
A policy under env/prod runs only for prod namespaces. A missing binary is a finding with source cmapi, so a broken image
cannot approve anything.

The mode of each environment (instance.yaml `policy`, core/policy.py; #213): off runs no Kyverno, audit turns each
Kyverno finding into a warning, enforce keeps it an error. A finding of cmapi itself (a missing binary) stays an error
in each mode. When a served environment needs Kyverno and the binary is missing, cmapi does not start.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

from cmapi.core.policy import PolicySettings
from cmapi.core.ports import Finding


class ValidatorUnavailable(RuntimeError):
    """The check could not run (a schema download failed). Not a verdict on the files: retry, never refuse."""


class PolicyEngineMissing(RuntimeError):
    """The instance's policy runs Kyverno in an environment, and the image has no kyverno binary: cmapi does not start."""


class CliValidator:
    def __init__(self, policies_dir: str | Path, *, kubeconform: str = "kubeconform", kyverno: str = "kyverno",
                 schema_location: str | None = None, kubernetes_version: str | None = None, timeout: float = 60.0,
                 policy: PolicySettings | None = None, environments: set[str] | None = None):
        self.policies = sorted(p for p in Path(policies_dir).rglob("*.yaml")) if Path(policies_dir).exists() else []
        self.kubeconform, self.kyverno, self.timeout = kubeconform, kyverno, timeout
        self.schema_location, self.kubernetes_version = schema_location, kubernetes_version
        self.policy = policy or PolicySettings()
        # A configuration error, found at the start: with enforce or audit and no binary, every plan would be refused.
        if environments and self.policy.needs_kyverno(environments) and shutil.which(self.kyverno) is None:
            needing = sorted(e for e in environments if self.policy.mode_for(e) != "off")
            raise PolicyEngineMissing(f"{self.kyverno} is not installed, and the environments {needing} run Kyverno "
                                      "(instance.yaml policy). Install it, or set their mode to off")

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
            mode = self.policy.mode_for(environment)
            if mode != "off":
                found = self._kyverno(paths, environment)
                if mode == "audit":
                    found = [replace(f, severity="warning") if f.source == "kyverno" else f for f in found]
                out.extend(found)
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
