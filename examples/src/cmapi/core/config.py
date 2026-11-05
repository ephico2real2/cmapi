"""Loads one instance's configuration and checks the files against each other.

Each file is validated by its own module; this module adds the checks no single file can make:

- every environment a file names is one the instance serves (instance.yaml allowedEnvironments);
- expiration.yaml never names prod;
- every tier an auto-approval policy names exists in the tier catalog;
- the tier catalog covers exactly the served environments (expiration.yaml may leave a non-prod
  environment out: expiry is then refused there, the same as prod);
- metadata-keys.yaml has emailDomains when any governed key uses email-in-domains.

At startup any problem stops cmapi. On reload (ConfigMap watch, content hash) the running config is
kept when the new one fails, and cmapi_config_reload_failed{file} is set.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from cmapi.core.approvals import ApprovalRules
from cmapi.core.authz import RolePolicy
from cmapi.core.metadata import MetadataKeys
from cmapi.core.tiers import CatalogError, TierCatalog
from cmapi.plugins.expiration.rules import ExpirationRules


class ConfigError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("invalid instance configuration:\n  " + "\n  ".join(problems))
        self.problems = problems


@dataclass
class InstanceConfig:
    name: str
    allowed_environments: set[str]
    raw_instance: dict
    approvals: ApprovalRules
    roles: RolePolicy
    tiers: TierCatalog
    expiration: ExpirationRules
    metadata: MetadataKeys
    hashes: dict[str, str]


def _read(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    return yaml.safe_load(text) or {}, hashlib.sha256(text.encode()).hexdigest()[:16]


def load_instance(config_dir: str | Path, metadata_keys: str | Path) -> InstanceConfig:
    d = Path(config_dir)
    problems: list[str] = []
    inst, h_inst = _read(d / "instance.yaml")
    me = inst["instance"]
    allowed = set(me["allowedEnvironments"])
    hashes = {"instance.yaml": h_inst}

    def build(name: str, fn):
        raw, h = _read(d / name)
        hashes[name] = h
        try:
            return fn(raw)
        except (ValueError, CatalogError) as exc:
            problems.append(f"{name}: {exc}")
            return None

    approvals = build("approval-rules.yaml", lambda r: ApprovalRules(r, allowed))
    tiers = build("tiers.yaml", lambda r: TierCatalog(r, allowed))
    expiration = build("expiration.yaml", lambda r: ExpirationRules(r, allowed))
    roles = build("authz-roles.yaml", lambda r: RolePolicy(r, allowed))
    mk_raw, mk_h = _read(Path(metadata_keys))
    hashes["metadata-keys.yaml"] = mk_h
    try:
        metadata = MetadataKeys(mk_raw)
    except ValueError as exc:
        problems.append(f"metadata-keys.yaml: {exc}")
        metadata = None

    if approvals and tiers:
        known = {r.name for e in tiers.environments() for r in tiers.offered(e)}
        for t in sorted(approvals.tier_names() - known):
            problems.append(f"approval-rules.yaml: auto-approval names tier {t}, not in tiers.yaml")
        missing = allowed - set(approvals.environments)
        if missing:
            problems.append(f"approval-rules.yaml: no rules for served environments {sorted(missing)}")
    if expiration and "prod" in allowed and expiration.allows("prod"):
        problems.append("expiration.yaml: prod can never expire")
    if problems:
        raise ConfigError(problems)
    return InstanceConfig(me["name"], allowed, inst, approvals, roles, tiers, expiration, metadata, hashes)
