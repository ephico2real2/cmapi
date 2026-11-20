"""The policy bundle of an instance, as data: each policy's name, kind, environment, description, check and digest (#302).

The bundle is the hand-written policies under CMAPI_POLICIES_DIR and the policies that core/policygen.py renders from the
instance's configuration, the render winning on a clash (#212). The validator runs it at plan time; the Policies tab reads
it to name the policies that a cluster's reports may hold: no list of policies is written anywhere else (#302, the owner:
"the tab must not hard-code the policy list"). A policy under `env/<env>/` belongs to that environment only.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

import yaml

from cmapi.core.policygen import DIGEST, MARK, environment_of, family_descriptions, index_of, policy_digest

if TYPE_CHECKING:
    from cmapi.core.clients.policyreports import LivePolicy

DESCRIPTION = "policies.kyverno.io/description"
GENERATED = "cmapi.net/generated"
_GIT_POLICY = re.compile(r"(?:(?:policies/)?env/([^/]+)/)?[^/]+\.yaml")


def bundle_hash(pairs: Iterable[tuple[str, str | None]]) -> str | None:
    """Version 1 identifies a bundle by its sorted policy names and digests."""
    policies = sorted([name, digest] for name, digest in pairs)
    if not policies:
        return None
    data = json.dumps({"format": 1, "policies": policies}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()


@dataclass(frozen=True)
class GitHash:
    digest: str | None
    tampered: bool


def git_hash(files: Mapping[str, str]) -> GitHash:
    """Hash one env folder. Git paths may be relative to the repo, policies/, or the folder itself."""
    pairs = []
    tampered = False
    environments = set()
    for path, text in files.items():
        match = _GIT_POLICY.fullmatch(path)
        if not match or not text.startswith(MARK):
            continue
        if match[1]:
            environments.add(match[1])
            if len(environments) > 1:
                raise ValueError("git_hash requires the files of one environment")
        for doc in yaml.safe_load_all(text):
            if doc is None:
                continue
            meta = doc["metadata"]
            digest = policy_digest(doc)
            annotations = meta.get("annotations") or {}
            if digest != annotations.get(DIGEST):
                tampered = True
            if doc.get("kind") == "ValidatingPolicy" and annotations.get(GENERATED) == "true":
                pairs.append((meta["name"], digest))
    return GitHash(bundle_hash(pairs), tampered)


def live_hash(policies: Iterable[LivePolicy]) -> str | None:
    """Hash generated policies from an environment-scoped observation."""
    return bundle_hash((p.name, p.digest) for p in policies if p.generated)


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
    def __init__(self, files: Mapping[str, str], *, policies_dir: str | Path | None = None):
        self.files = bundle_files(policies_dir, files)
        self.index = index_of(self.files)
        self.policies: list[BundlePolicy] = []
        rendered: dict[str, list[tuple[str, str | None]]] = {}
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
                policy = BundlePolicy(
                    name=name, kind=str(doc.get("kind") or ""), environment=environment_of(path),
                    description=ann.get(DESCRIPTION), digest=ann.get(DIGEST), generated=ann.get(GENERATED) == "true",
                    check=self.index.get(name))
                self.policies.append(policy)
                if path in files and policy.environment and policy.generated and policy.kind == "ValidatingPolicy":
                    rendered.setdefault(policy.environment, []).append((name, policy.digest))
        self._rendered_names = {env: {name for name, _ in pairs} for env, pairs in rendered.items()}
        self._rendered_hashes = {env: bundle_hash(pairs) for env, pairs in rendered.items()}

    def rendered_hash(self, env: str) -> str | None:
        return self._rendered_hashes.get(env)

    def observed_hash(self, env: str, policies: Iterable[LivePolicy]) -> str | None:
        # A watch lists the entire cluster. Current names identify this render even if the description
        # is missing. The renderer's family descriptions identify obsolete members across configurations.
        names = self._rendered_names.get(env, ())
        descriptions = family_descriptions(env).values()
        return live_hash(p for p in policies if p.name in names or p.description in descriptions)

    def for_environment(self, environment: str) -> dict[str, BundlePolicy]:
        """The policies that run for one environment, by name: those outside env/, and those under env/<environment>/."""
        return {p.name: p for p in self.policies if p.environment in (None, environment)}
