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
Kyverno violation into a warning, enforce keeps it an error. A finding of cmapi itself (a missing binary, a policy that
the CLI could not evaluate or gave no result for) stays an error in each mode. When a served environment needs Kyverno
and the binary is missing, cmapi does not start.

The bundle (#212): the policies that core/policygen.py renders from this instance's own configuration, given as
`bundle`, and any hand-written policy under `policies_dir`. A policy under `env/<env>/` runs only for `<env>`. One
`kyverno apply` runs for each plan, on the Namespace, ResourceQuota and LimitRange, and cmapi reads its JSON report
(`-p --output-format json`). Each failed or errored result is a finding. A rendered policy's failure on a key whose value
the previous version of the object (Git) already holds is dropped, as the policy itself does at admission with
oldObject and as tiers.py does for the bounds. The guard against a vacuous pass: each policy that matches a kind among
the files gives a result for each file of that kind; a policy with no result is a finding.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import yaml

from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import environment_of, index_of
from cmapi.core.ports import Finding
from cmapi.core.tiers import LIMIT_KINDS, limit_key_parts, qty

# The files that the bundle checks, and the kind each one holds.
CHECKED = {"namespace.yaml": "Namespace", "resourcequota.yaml": "ResourceQuota", "limitrange.yaml": "LimitRange"}
_PLURAL = {"namespaces": "Namespace", "resourcequotas": "ResourceQuota", "limitranges": "LimitRange"}



class ValidatorUnavailable(RuntimeError):
    """The check could not run (a schema download failed). Not a verdict on the files: retry, never refuse."""


class PolicyEngineMissing(RuntimeError):
    """The instance's policy runs Kyverno in an environment, and the image has no kyverno binary: cmapi does not start."""


class CliValidator:
    def __init__(self, policies_dir: str | Path, *, kubeconform: str = "kubeconform", kyverno: str = "kyverno",
                 schema_location: str | None = None, kubernetes_version: str | None = None, timeout: float = 60.0,
                 policy: PolicySettings | None = None, environments: set[str] | None = None,
                 bundle: Mapping[str, str] | None = None):
        root = Path(policies_dir)
        # Relative path -> text: the hand-written policies first, then the rendered bundle (#212), which wins on a clash.
        self.bundle: dict[str, str] = {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.yaml"))} \
            if root.exists() else {}
        self.bundle.update(bundle or {})
        self.index = index_of(self.bundle)
        self.kubeconform, self.kyverno, self.timeout = kubeconform, kyverno, timeout
        self.schema_location, self.kubernetes_version = schema_location, kubernetes_version
        self.policy = policy or PolicySettings()
        # A configuration error, found at the start: with enforce or audit and no binary, every plan would be refused.
        if environments and self.policy.needs_kyverno(environments) and shutil.which(self.kyverno) is None:
            needing = sorted(e for e in environments if self.policy.mode_for(e) != "off")
            raise PolicyEngineMissing(f"{self.kyverno} is not installed, and the environments {needing} run Kyverno "
                                      "(instance.yaml policy). Install it, or set their mode to off")
        # The image names the CLI it pins (Containerfile, CMAPI_KYVERNO_VERSION): another binary on PATH would check the
        # rendered policies with other semantics than the clusters run (Codex's design of #212, Q8).
        pinned = os.environ.get("CMAPI_KYVERNO_VERSION")
        if pinned and environments and self.policy.needs_kyverno(environments):
            out = self._run([self.kyverno, "version"]).stdout
            if f"Version: {pinned}" not in out:
                found = next((ln for ln in out.splitlines() if ln.startswith("Version:")), "no version")
                raise PolicyEngineMissing(f"{self.kyverno} is not the pinned {pinned} ({found})")

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)

    def validate(self, files: Mapping[str, str | None], cluster_id: str, environment: str,
                 previous: Mapping[str, str | None] | None = None) -> list[Finding]:
        """previous: the folder as Git holds it before this change, so a value that it already holds is not refused."""
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
                found = self._kyverno(paths, live, environment, previous or {})
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

    def policies_for(self, environment: str) -> dict[str, str]:
        """The bundle's files that run for one environment: those outside env/, and those under env/<environment>/."""
        return {p: t for p, t in self.bundle.items() if p.endswith(".yaml") and environment_of(p) in (None, environment)}

    def _kyverno(self, paths: Mapping[str, str], files: Mapping[str, str], environment: str,
                 previous: Mapping[str, str | None]) -> list[Finding]:
        checked = {p: f for p, f in paths.items() if p.rsplit("/", 1)[-1] in CHECKED}
        policies = self.policies_for(environment)
        if not checked or not policies:
            return []
        if shutil.which(self.kyverno) is None:
            return [Finding("cmapi", "validator", "", f"{self.kyverno} is not installed in this image")]
        with tempfile.TemporaryDirectory(prefix="cmapi-policies-") as pd:
            for rel, text in policies.items():
                f = Path(pd) / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text)
            r = self._run([self.kyverno, "apply", pd, "--resource", ",".join(checked.values()),
                           "-p", "--output-format", "json"])
        try:
            report = json.loads(r.stdout)
            results = report["results"]
            if not isinstance(results, list) or not all(isinstance(res, dict) for res in results):
                raise ValueError("results must be a list of result objects")
        except (ValueError, KeyError, TypeError):
            # The CLI stops with exit 2 and no report on a fault of its own (a panic, a policy it cannot read).
            tail = [ln for ln in (r.stderr or r.stdout).strip().splitlines() if ln.strip()]
            return [Finding("cmapi", "validator", "", f"kyverno exited {r.returncode} with no report: "
                                                      f"{(tail[0] if tail else '')[:200]}")]
        docs = {rel: yaml.safe_load(files[rel]) or {} for rel in checked}
        by_object = {(d.get("kind"), (d.get("metadata") or {}).get("namespace", ""),
                      (d.get("metadata") or {}).get("name")): rel for rel, d in docs.items()}
        out: list[Finding] = []
        if r.returncode not in (0, 1):
            out.append(Finding("cmapi", "validator", "", f"kyverno exited {r.returncode}: {r.stderr[:200]}"))
        if not results:
            out.append(Finding("cmapi", "validator", "", "kyverno returned no results"))
        seen: set[tuple[str, str]] = set()
        for res in results:
            if not isinstance(res.get("policy"), str):
                out.append(Finding("cmapi", "validator", "", "kyverno result has no policy name"))
                continue
            resources = res.get("resources")
            if not isinstance(resources, list) or len(resources) != 1 or not isinstance(resources[0], dict):
                out.append(Finding("cmapi", "validator", "", "kyverno result has no unique resource"))
                continue
            obj = resources[0]
            rel = by_object.get((obj.get("kind"), obj.get("namespace", ""), obj.get("name")), "")
            if not rel:
                out.append(Finding("cmapi", "validator", "", "kyverno result refers to an unknown resource"))
                continue
            seen.add((res.get("policy", ""), rel))
            if res.get("result") == "error":
                # The policy could not be evaluated (a CEL error, a value that is not a quantity): a fault of the bundle or
                # the file, not a verdict, so source cmapi keeps it an error in audit too (Codex's design, Q2).
                out.append(Finding("cmapi", res.get("policy", ""), rel,
                                   f"kyverno could not evaluate the policy: {res.get('message') or ''}"[:300]))
                continue
            if res.get("result") in ("pass", "skip"):
                continue
            if res.get("result") != "fail":
                out.append(Finding("cmapi", res.get("policy", ""), rel,
                                   f"kyverno returned unexpected result {res.get('result')!r}: {res.get('message') or ''}"[:300]))
                continue
            check = self.index.get(res.get("policy", ""))
            if check and check.get("key") and rel and _held(check, docs[rel], _previous_doc(previous, rel)):
                continue
            out.append(Finding("kyverno", res.get("policy", ""), rel, (res.get("message") or "fail")[:300]))
        for name, kinds in _matched_kinds(policies).items():
            for rel, doc in docs.items():
                if doc.get("kind") in kinds and (name, rel) not in seen:
                    out.append(Finding("cmapi", name, rel, "policy not understood by the CLI (no result for this file)"))
        return out


def _previous_doc(previous: Mapping[str, str | None], rel: str) -> dict[str, Any] | None:
    text = previous.get(rel)
    return (yaml.safe_load(text) or {}) if text else None


def _held(check: Mapping[str, str | None], new: Mapping[str, Any], old: Mapping[str, Any] | None) -> bool:
    """True when the key that a rendered policy checks has the same value in the previous version of the object."""
    if old is None or not check.get("key") or check.get("rule") == "order":
        return False
    kind, key = check["kind"], str(check["key"])
    if kind in ("label", "annotation"):
        field = "labels" if kind == "label" else "annotations"
        a = ((new.get("metadata") or {}).get(field) or {})
        b = ((old.get("metadata") or {}).get(field) or {})
        return (key not in a and key not in b) or \
            (isinstance(a.get(key), str) and isinstance(b.get(key), str) and a[key] == b[key])
    if kind == "quota":
        a = ((new.get("spec") or {}).get("hard") or {}).get(key)
        b = ((old.get("spec") or {}).get("hard") or {}).get(key)
        return a is not None and b is not None and _same_amount(str(a), str(b))
    if kind == "limit":
        parts = limit_key_parts(key)
        if not parts:
            return False
        a, b = _limit(new, *parts), _limit(old, *parts)
        return a is not None and b is not None and _same_amount(a, b)
    return False


def _same_amount(a: str, b: str) -> bool:
    """Equivalent quantities are one amount; invalid quantities never prove equality."""
    try:
        return qty(a) == qty(b)
    except ValueError:
        return False


def _limit(doc: Mapping[str, Any], kind: str, part: str, res: str) -> str | None:
    for item in ((doc.get("spec") or {}).get("limits") or []):
        if item.get("type") == LIMIT_KINDS[kind] and res in (item.get(part) or {}):
            return str(item[part][res])
    return None


def _matched_kinds(policies: Mapping[str, str]) -> dict[str, set[str]]:
    """Policy name -> the kinds its resourceRules match, for each ValidatingPolicy of the bundle."""
    out: dict[str, set[str]] = {}
    for text in policies.values():
        for doc in yaml.safe_load_all(text):
            if not isinstance(doc, Mapping) or doc.get("kind") != "ValidatingPolicy":
                continue
            rules = (((doc.get("spec") or {}).get("matchConstraints") or {}).get("resourceRules") or [])
            kinds = {_PLURAL[r] for rule in rules for r in (rule.get("resources") or []) if r in _PLURAL}
            if any("*" in (rule.get("resources") or []) for rule in rules):
                kinds.update(CHECKED.values())
            name = (doc.get("metadata") or {}).get("name")
            if name and kinds:
                out[name] = kinds
    return out
