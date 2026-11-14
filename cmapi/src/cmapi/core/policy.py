"""The policy engine of an instance: Kyverno or none, and a mode for each environment (#213).

instance.yaml:

    policy:
      engine: kyverno          # kyverno | none
      mode: enforce            # enforce | audit | off: the mode of each environment that `environments` does not name
      environments:
        rnd: {mode: audit}

With no `policy` key, the engine is kyverno and each environment enforces: cmapi's behaviour before #213.

| Mode    | Plan time in cmapi                                                     |
|---------|------------------------------------------------------------------------|
| enforce | A Kyverno finding refuses the plan (problem policy-violation)          |
| audit   | A Kyverno finding is a warning on the plan; the request goes to approval |
| off     | No Kyverno run; kubeconform and cmapi's own checks still run            |

`engine: none` is `off` for every environment, and then cmapi needs no kyverno binary. cmapi's own checks (names, tiers,
bounds, metadata keys) never depend on Kyverno, so `off` loses only the cluster-side admission check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

ENGINES = ("kyverno", "none")
MODES = ("enforce", "audit", "off")


@dataclass(frozen=True)
class PolicySettings:
    engine: str = "kyverno"
    default_mode: str = "enforce"
    environments: Mapping[str, str] = field(default_factory=dict)

    def mode_for(self, environment: str) -> str:
        """The mode of one environment: off for every environment when the engine is none."""
        if self.engine == "none":
            return "off"
        return self.environments.get(environment, self.default_mode)

    def modes(self, environments: set[str]) -> dict[str, str]:
        return {e: self.mode_for(e) for e in sorted(environments)}

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
        unknown = set(raw) - {"engine", "mode", "environments"}
        if unknown:
            problems.append(f"instance.yaml: policy has unknown fields {sorted(unknown)}")
        engine = raw.get("engine", "kyverno")
        if engine not in ENGINES:
            problems.append(f"instance.yaml: policy.engine must be one of {list(ENGINES)}, not {engine!r}")
            engine = "kyverno"
        default = raw.get("mode", "enforce")
        if default not in MODES:
            problems.append(f"instance.yaml: policy.mode must be one of {list(MODES)}, not {default!r}")
            default = "enforce"
        envs: dict[str, str] = {}
        for env, spec in (raw.get("environments") or {}).items():
            mode = (spec or {}).get("mode") if isinstance(spec, Mapping) else None
            if env not in allowed:
                problems.append(f"instance.yaml: policy.environments.{env} is not an environment this instance serves")
            elif mode not in MODES:
                problems.append(f"instance.yaml: policy.environments.{env}.mode must be one of {list(MODES)}")
            else:
                envs[env] = mode
        if engine == "none" and (envs or "mode" in raw and default != "off"):
            problems.append("instance.yaml: policy.engine none runs no policy: give no mode, or mode off")
        return cls(engine=engine, default_mode=default, environments=envs), problems
