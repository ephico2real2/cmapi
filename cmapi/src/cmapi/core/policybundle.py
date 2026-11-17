"""The policy bundle of an instance, as data: each policy's name, kind, environment, description, check and digest (#302).

The bundle is the hand-written policies under CMAPI_POLICIES_DIR and the policies that core/policygen.py renders from the
instance's configuration, the render winning on a clash (#212). The validator runs it at plan time; the Policies tab reads
it to name the policies that a cluster's reports may hold: no list of policies is written anywhere else (#302, the owner:
"the tab must not hard-code the policy list"). A policy under `env/<env>/` belongs to that environment only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from cmapi.core.policygen import DIGEST, environment_of, index_of

DESCRIPTION = "policies.kyverno.io/description"
GENERATED = "cmapi.net/generated"


def bundle_files(policies_dir: str | Path | None, rendered: Mapping[str, str] | None) -> dict[str, str]:
    """Relative path -> text: the hand-written policies first, then the rendered bundle, which wins on a clash."""
    root = Path(policies_dir) if policies_dir else None
    files = {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.yaml"))} if root and root.exists() else {}
    files.update(rendered or {})
    return files


@dataclass(frozen=True)
class BundlePolicy:
    name: str
    kind: str                                  # ValidatingPolicy for everything cmapi renders
    environment: str | None                    # None: a policy outside env/, which runs for every environment
    description: str | None
    digest: str | None                         # cmapi.net/policy-digest of a rendered policy; None for a hand-written one
    generated: bool
    check: Mapping[str, Any] | None            # index.json's {kind, key, rule}; None for a hand-written policy


class PolicyBundle:
    def __init__(self, files: Mapping[str, str]):
        self.files = dict(files)
        self.index = index_of(self.files)
        self.policies: list[BundlePolicy] = []
        for path, text in sorted(self.files.items()):
            if not path.endswith(".yaml"):
                continue
            for doc in yaml.safe_load_all(text):
                if not isinstance(doc, Mapping) or not isinstance(doc.get("metadata"), Mapping):
                    continue
                meta = doc["metadata"]
                name = meta.get("name")
                if not isinstance(name, str) or not name:
                    continue
                ann = meta.get("annotations") or {}
                self.policies.append(BundlePolicy(
                    name=name, kind=str(doc.get("kind") or ""), environment=environment_of(path),
                    description=ann.get(DESCRIPTION), digest=ann.get(DIGEST), generated=ann.get(GENERATED) == "true",
                    check=self.index.get(name)))

    def for_environment(self, environment: str) -> dict[str, BundlePolicy]:
        """The policies that run for one environment, by name: those outside env/, and those under env/<environment>/."""
        return {p.name: p for p in self.policies if p.environment in (None, environment)}
