"""Loads one instance's configuration and checks the files against each other.

Each file is validated by its own module; this module adds the checks no single file can make:

- every environment a file names is one the instance serves (instance.yaml allowedEnvironments);
- expiration.yaml never names prod;
- every tier an auto-approval policy names exists in the tier catalog;
- the tier catalog covers exactly the served environments (expiration.yaml may leave a non-prod
  environment out: expiry is then refused there, the same as prod);
- metadata-keys.yaml has emailDomains when any governed key uses email-in-domains;
- instance.yaml's identity.groupPath can name a group;
- plugins.yaml, when the instance has one, names only plugins of this build, and its overrides for this instance name
  only served environments (core/plugins.py);
- instance.yaml's git.url is a URL the Git layer may use, git.hostChecks is a boolean, git.username one line (#286);
- instance.yaml's clusterTLS names only served environments, each with a boolean insecureSkipTLSVerify (core/clustertls.py, #434);
- instance.yaml's directory maps each name to a list of environments, an http(s) url and an optional http(s) portalUrl, the
  shape environment_not_served reads on every refusal (#674);
- instance.yaml's http.maxRequestBodyBytes is a whole number of bytes, 1 to 2**53 - 1 (core/bodylimit.py, #683).

At startup any problem stops cmapi. On reload (ConfigMap watch, content hash) the running config is
kept when the new one fails, and cmapi_config_reload_failed{file} is set.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from cmapi.core.approvals import ApprovalRules
from cmapi.core.authz import DEFAULT_GROUP_PATH, RolePolicy, check_group_path
from cmapi.core.bodylimit import DEFAULT_MAX_REQUEST_BODY_BYTES, parse_http
from cmapi.core.cluster_tokens import TokenPolicy
from cmapi.core.clustertls import ClusterTLSSettings
from cmapi.core.errors import Problem
from cmapi.core.giturl import GitConfigError, parse_remote
from cmapi.core.metadata import MetadataKeys
from cmapi.core.plugins import PluginSwitch
from cmapi.core.policy import PolicySettings
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
    plugins: PluginSwitch
    hashes: dict[str, str]
    policy: PolicySettings = field(default_factory=PolicySettings)   # instance.yaml `policy` (#213)
    cluster_tls: ClusterTLSSettings = field(default_factory=ClusterTLSSettings)   # instance.yaml `clusterTLS` (#434)
    cluster_tokens: TokenPolicy = field(default_factory=TokenPolicy)
    max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES   # instance.yaml `http.maxRequestBodyBytes` (#683)


def environment_not_served(cfg: InstanceConfig, env: str) -> Problem:
    """The 422 environment-not-served for an environment this instance does not serve (#671).

    Every refusal of one is built here, so each names the instance that serves the environment, as docs/02, "Problems", says:
    instanceUrl and portalUrl, from the entry of instance.yaml `directory` that lists it (its shape is checked at the start,
    _directory_problems). A member the entry does not give is left out, never null. RFC 9457 leaves an extension member's
    type to its problem type (section 3.2), and this type makes each one a URL string; for the standard members, section 3.1
    has a client treat a value not of the member's type "as if the member had not been present", and the same holds here.
    """
    serving = next((d for d in (cfg.raw_instance["instance"].get("directory") or {}).values()
                    if env in d.get("environments", [])), {})
    urls = {member: serving[key] for member, key in (("instanceUrl", "url"), ("portalUrl", "portalUrl")) if serving.get(key)}
    return Problem.unprocessable("environment-not-served", f"{env} is not served by the {cfg.name} instance", **urls)


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

    template = (me.get("identity") or {}).get("groupPath", DEFAULT_GROUP_PATH)
    try:
        check_group_path(template)
    except ValueError as exc:
        problems.append(f"instance.yaml: identity.groupPath: {exc}")
        template = DEFAULT_GROUP_PATH

    approvals = build("approval-rules.yaml", lambda r: ApprovalRules(r, allowed, group_path=template))
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

    # Optional: without the file each built-in plugin is enabled, as before the file was read.
    if (d / "plugins.yaml").exists():
        plugins = build("plugins.yaml", lambda r: PluginSwitch(r, me["name"], allowed))
    else:
        plugins = PluginSwitch(None, me["name"], allowed)

    if approvals and tiers:
        known = {r.name for e in tiers.environments() for r in tiers.offered(e)}
        for t in sorted(approvals.tier_names() - known):
            problems.append(f"approval-rules.yaml: auto-approval names tier {t}, not in tiers.yaml")
        missing = allowed - set(approvals.environments)
        if missing:
            problems.append(f"approval-rules.yaml: no rules for served environments {sorted(missing)}")
    if expiration and "prod" in allowed and expiration.allows("prod"):
        problems.append("expiration.yaml: prod can never expire")
    problems.extend(_git_problems(me.get("git") or {}))
    problems.extend(_directory_problems(me.get("directory")))
    policy, policy_problems = PolicySettings.parse(me.get("policy"), allowed)
    problems.extend(policy_problems)
    cluster_tls, tls_problems = ClusterTLSSettings.parse(me.get("clusterTLS"), allowed)
    problems.extend(tls_problems)
    max_request_body_bytes, http_problems = parse_http(me.get("http"))
    problems.extend(http_problems)
    try:
        cluster_tokens = TokenPolicy().override(me.get("clusterTokens", {}))
    except ValueError as exc:
        problems.append(f"instance.clusterTokens: {exc}")
    if problems:
        raise ConfigError(problems)
    return InstanceConfig(me["name"], allowed, inst, approvals, roles, tiers, expiration, metadata, plugins, hashes, policy,
                          cluster_tls, cluster_tokens, max_request_body_bytes)


def _directory_problems(directory: Any) -> list[str]:
    """instance.yaml `directory`, read by environment_not_served on every refusal: a shape that the start does not check
    would turn those 422 answers into 500 (#674)."""
    if directory is None:
        return []
    if not isinstance(directory, dict):
        return ["instance.directory must be a mapping of an instance's name to its url, environments and optional portalUrl"]
    problems = []
    for name, entry in directory.items():
        where = f"instance.directory.{name}"
        if not isinstance(entry, dict):
            problems.append(f"{where} must be a mapping with url, environments and an optional portalUrl")
            continue
        envs = entry.get("environments")
        if not isinstance(envs, list) or not all(isinstance(e, str) and e for e in envs):
            problems.append(f"{where}.environments must be a list of environment names")
        for key in ("url", "portalUrl"):
            value = entry.get(key)
            if key == "portalUrl" and value in (None, ""):
                continue                    # optional; environment_not_served leaves the member out
            parts = urlsplit(value) if isinstance(value, str) else None
            if parts is None or parts.scheme not in ("https", "http") or not parts.netloc:
                problems.append(f"{where}.{key} must be an absolute http(s) URL: {value!r}")
    return problems


def _git_problems(git: dict) -> list[str]:
    problems = []
    if git.get("url") is not None:
        try:
            parse_remote(git["url"])
        except GitConfigError as exc:
            problems.append(f"instance.yaml: {exc}")
    for key in ("hostChecks", "postStatus"):
        if not isinstance(git.get(key, False), bool):
            problems.append(f"instance.yaml: git.{key} is true or false")
    email = git.get("commitEmail")
    if email is not None and (not isinstance(email, str) or "@" not in email or any(c.isspace() or c in "<>" for c in email)):
        problems.append("instance.yaml: git.commitEmail is one address, such as the bot account's no-reply address")
    user = git.get("username")
    if user is not None and (not isinstance(user, str) or not user or any(c in user for c in "\r\n")):
        problems.append("instance.yaml: git.username is one line of text")
    return problems
