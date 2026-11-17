"""The policy engine of an instance: Kyverno or none, and a mode for each environment (#213).

instance.yaml:

    policy:
      engine: kyverno          # kyverno | none
      mode: audit              # audit | enforce | off: the mode of each environment that `environments` does not name
      environments:
        prod: {mode: enforce}
      reports:
        maxResultsPerCluster: 20000   # the rows of fail, warn and error that the Policies tab keeps per cluster (#302)
      rejections:
        retentionDays: 90             # how long a stored refusal of cmapi is kept (#302)

With no `policy` key, or no `mode`, the engine is kyverno and each environment audits (#342). The owner, 2026-11-17: "Kyverno
should be in audit mode. The core logic like we said should be in the cmapi core logic itself." cmapi's own checks refuse a
request in every mode; Kyverno reports beside them, and the rendered policies admit and record (`[Audit, Warn]`).

| Mode    | Plan time in cmapi                                                     |
|---------|------------------------------------------------------------------------|
| audit   | A Kyverno finding is a warning on the plan; the request goes to approval (the default) |
| enforce | A Kyverno finding refuses the plan (problem policy-violation)          |
| off     | No Kyverno run; kubeconform and cmapi's own checks still run            |

`engine: none` is `off` for every environment, and then cmapi needs no kyverno binary. cmapi's own checks (names, tiers,
bounds, metadata keys) never depend on Kyverno, so `off` loses only the cluster-side admission check. A finding of cmapi
about Kyverno itself (no binary, a policy it cannot evaluate, no result) is an error in every mode (#213 F2).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

ENGINES = ("kyverno", "none")
MODES = ("enforce", "audit", "off")
DEFAULT_MODE = "audit"      # #342: cmapi's own checks are the refusal; Kyverno reports
# #302. 20,000 kept rows took 9.4 MiB in CPython 3.14 (design B, M17). 90 days: the arbitration of #302, one key per instance.
DEFAULT_MAX_RESULTS = 20_000
DEFAULT_RETENTION_DAYS = 90


def _mode(value: Any) -> Any:
    """YAML 1.1 reads an unquoted `off` as the boolean false (PyYAML here, and Helm for a values file), so false is the
    mode off. True (`on`, `yes`) is no mode and stays a problem."""
    return "off" if value is False else value


@dataclass(frozen=True)
class PolicySettings:
    engine: str = "kyverno"
    default_mode: str = DEFAULT_MODE
    environments: Mapping[str, str] = field(default_factory=dict)
    max_results_per_cluster: int = DEFAULT_MAX_RESULTS
    rejection_retention_days: int = DEFAULT_RETENTION_DAYS

    def mode_for(self, environment: str) -> str:
        """The mode of one environment: off for every environment when the engine is none."""
        if self.engine == "none":
            return "off"
        return self.environments.get(environment, self.default_mode)

    def modes(self, environments: set[str]) -> dict[str, str]:
        return {e: self.mode_for(e) for e in sorted(environments)}

    def view(self, environments: set[str]) -> dict[str, Any]:
        """The `policy` object of the API (schema Policy), the same in GET /admin/integrations and GET /policies/results:
        the engine, the Kyverno CLI that the image pins (CMAPI_KYVERNO_VERSION; null outside the image) and each mode."""
        return {"engine": self.engine, "kyvernoVersion": os.environ.get("CMAPI_KYVERNO_VERSION") or None,
                "environments": self.modes(environments)}

    def needs_kyverno(self, environments: set[str]) -> bool:
        """True when some served environment runs Kyverno at plan time, so the kyverno binary must be present."""
        return any(self.mode_for(e) != "off" for e in environments)

    @classmethod
    def parse(cls, raw: Mapping[str, Any] | None, allowed: set[str]) -> tuple["PolicySettings", list[str]]:
        """The settings and the problems of instance.yaml's `policy` key. A problem stops the start."""
        problems: list[str] = []
        if raw is None:
            return cls(), problems
        if not isinstance(raw, Mapping):
            return cls(), ["instance.yaml: policy must be a mapping"]
        unknown = set(raw) - {"engine", "mode", "environments", "reports", "rejections"}
        if unknown:
            problems.append(f"instance.yaml: policy has unknown fields {sorted(unknown)}")
        engine = raw.get("engine", "kyverno")
        if engine not in ENGINES:
            problems.append(f"instance.yaml: policy.engine must be one of {list(ENGINES)}, not {engine!r}")
            engine = "kyverno"
        default = _mode(raw.get("mode", DEFAULT_MODE))
        if default not in MODES:
            problems.append(f"instance.yaml: policy.mode must be one of {list(MODES)}, not {default!r}")
            default = DEFAULT_MODE
        envs: dict[str, str] = {}
        for env, spec in (raw.get("environments") or {}).items():
            mode = _mode((spec or {}).get("mode")) if isinstance(spec, Mapping) else None
            if env not in allowed:
                problems.append(f"instance.yaml: policy.environments.{env} is not an environment this instance serves")
            elif mode not in MODES:
                problems.append(f"instance.yaml: policy.environments.{env}.mode must be one of {list(MODES)}")
            else:
                envs[env] = mode
        if engine == "none" and (envs or "mode" in raw and default != "off"):
            problems.append("instance.yaml: policy.engine none runs no policy: give no mode, or mode off")
        max_results = _count(raw, "reports", "maxResultsPerCluster", DEFAULT_MAX_RESULTS, 1, 1_000_000, problems)
        retention = _count(raw, "rejections", "retentionDays", DEFAULT_RETENTION_DAYS, 1, 3650, problems)
        return cls(engine=engine, default_mode=default, environments=envs, max_results_per_cluster=max_results,
                   rejection_retention_days=retention), problems


def _count(raw: Mapping[str, Any], block: str, key: str, default: int, low: int, high: int, problems: list[str]) -> int:
    """A whole number of `policy.<block>.<key>`, from low to high; the default when the key is absent."""
    section = raw.get(block)
    if section is None:
        return default
    if not isinstance(section, Mapping) or set(section) - {key}:
        problems.append(f"instance.yaml: policy.{block} has the one key {key}")
        return default
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        problems.append(f"instance.yaml: policy.{block}.{key} is a whole number from {low} to {high}, not {value!r}")
        return default
    return value
