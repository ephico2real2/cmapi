"""instance.yaml `clusterTLS`: which environments may read a cluster with TLS verification off (#434, docs/18).

    clusterTLS:
      environments:
        rnd: {insecureSkipTLSVerify: true}

An import Secret with `insecure: "true"` is refused unless its cluster's environment is named here with
`insecureSkipTLSVerify: true`. The default is false for every environment, prod included: the owner chose a setting over a rule
(2026-11-18), so any served environment may allow it. The name is Kubernetes' for the same meaning (APIService
`spec.insecureSkipTLSVerify`, kubeconfig `insecure-skip-tls-verify`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ClusterTLSSettings:
    insecure_environments: frozenset[str] = field(default_factory=frozenset)

    def view(self, environments: set[str]) -> dict[str, bool]:
        """insecureSkipTLSVerify for each served environment."""
        return {e: e in self.insecure_environments for e in sorted(environments)}

    @classmethod
    def parse(cls, raw: Any, allowed: set[str]) -> tuple["ClusterTLSSettings", list[str]]:
        """The settings and the problems of instance.yaml's `clusterTLS` key. A problem stops the start."""
        if raw is None:
            return cls(), []
        if not isinstance(raw, Mapping):
            return cls(), ["instance.yaml: clusterTLS must be a mapping"]
        problems: list[str] = []
        unknown = set(raw) - {"environments"}
        if unknown:
            problems.append(f"instance.yaml: clusterTLS has unknown fields {sorted(unknown)}")
        envs = raw.get("environments") or {}
        if not isinstance(envs, Mapping):
            return cls(), problems + ["instance.yaml: clusterTLS.environments must be a mapping of environment to settings"]
        allowed_insecure: set[str] = set()
        for env, spec in envs.items():
            where = f"instance.yaml: clusterTLS.environments.{env}"
            if env not in allowed:
                problems.append(f"{where} is not an environment this instance serves")
                continue
            if not isinstance(spec, Mapping) or set(spec) - {"insecureSkipTLSVerify"}:
                problems.append(f"{where} has the one key insecureSkipTLSVerify")
                continue
            value = spec.get("insecureSkipTLSVerify", False)
            if not isinstance(value, bool):
                problems.append(f"{where}.insecureSkipTLSVerify is true or false, not {value!r}")
            elif value:
                allowed_insecure.add(env)
        return cls(frozenset(allowed_insecure)), problems
