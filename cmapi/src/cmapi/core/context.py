"""Everything one process holds: the loaded config and the adapters, built once at startup from
Settings and the instance files. The API keeps it on app.state.ctx; the worker builds its own."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml

from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.capacity_backend import SimulatedCapacity
from cmapi.core.config import InstanceConfig, load_instance
from cmapi.core.db import Database
from cmapi.core.db.repo import DbKeyStore, SwitchRepo
from cmapi.core.git import HostGitProvider, make_provider
from cmapi.core.identity.directory import CachedDirectory
from cmapi.core.identity.keycloak_admin import KeycloakAdminDirectory
from cmapi.core.listquery import Lister, Sorts, severity
from cmapi.core.observability import AUTO_PAUSED, CONFIG_INFO
from cmapi.core.pipeline import Pipeline
from cmapi.core.registry import ClusterRegistry, DirImportSource, HubImportSource, ImportSource, load_policies
from cmapi.core.sync import DeliveryConfig
from cmapi.core.validate import CliValidator
from cmapi.settings import Settings


@dataclass
class AppContext:
    settings: Settings
    cfg: InstanceConfig
    db: Database
    auth: Authenticator
    registry: ClusterRegistry
    git: HostGitProvider
    pipeline: Pipeline
    directory: CachedDirectory | None
    lister: Lister
    delivery: DeliveryConfig
    integrations: dict[str, Any]
    capacity_cfg: dict[str, Any]
    issuer: str
    audience: str
    deliverer_factory: Callable[[str], Any] | None = None   # tests inject a fake cluster write client

    def auto_paused(self) -> bool:
        with self.db.session() as s:
            v = SwitchRepo(s).get("auto-approval")
        paused = bool(v and v.get("paused"))
        AUTO_PAUSED.set(1 if paused else 0)
        return paused

    def shutdown(self) -> None:
        self.registry.stop()


def _yaml(path: Path) -> dict[str, Any]:
    return (yaml.safe_load(path.read_text()) if path.exists() else None) or {}


def _http_for_directory(verify: str | bool):
    def http(method: str, url: str, headers: dict[str, str], form: dict[str, str] | None):
        r = httpx.request(method, url, headers=headers, data=form, timeout=10, verify=verify)
        return r.status_code, (r.json() if r.content else None)
    return http


def build_context(settings: Settings, *, start_registry: bool = True, import_source: ImportSource | None = None) -> AppContext:
    cfg = load_instance(settings.config_dir, settings.metadata_keys_path)
    inst = cfg.raw_instance["instance"]
    issuer, audience = inst["auth"]["issuer"], inst["auth"]["audience"]
    jwks_url = settings.oidc_jwks_url or f"{issuer}/protocol/openid-connect/certs"
    db = Database(settings.database_url, settings.database_pool_size)
    auth = Authenticator(issuer, audience, Jwks(issuer, jwks_url, verify=settings.verify, store=DbKeyStore(db)),
                         leeway=settings.oidc_leeway_seconds,
                         legacy_token_type=bool(inst["auth"].get("acceptLegacyTokenType", False)))
    CONFIG_INFO.labels("|".join(f"{k}={v}" for k, v in sorted(cfg.hashes.items()))[:200]).set(1)

    policies = load_policies(settings.config_dir / "clusters.yaml", cfg.allowed_environments)
    if import_source is None:
        if settings.imports_dir:
            import_source = DirImportSource(settings.imports_dir)
        elif settings.kube_token_file.exists():
            import_source = HubImportSource(settings.kube_api_url, settings.kube_token_file, settings.kube_ca_file,
                                            settings.imports_namespace)
    registry = ClusterRegistry(policies, import_source, trusted_bundle=str(settings.ca_bundle) if settings.ca_bundle else None,
                               start_caches=start_registry)
    if start_registry:
        registry.start()

    git = make_provider(settings.git_provider, settings.git_url, inst["git"]["repository"], settings.git_token,
                        default_branch=settings.git_default_branch, verify=settings.verify,
                        web_url=inst["git"].get("webUrl"),
                        basic_auth=(settings.git_user, settings.git_password) if settings.git_user else None)
    validator = CliValidator(settings.policies_dir, schema_location=os.environ.get("CMAPI_KUBECONFORM_SCHEMAS") or None,
                             kubernetes_version=os.environ.get("CMAPI_KUBERNETES_VERSION") or None)
    capacity_cfg = _yaml(settings.config_dir / "capacity.yaml")
    capacity = SimulatedCapacity(registry, capacity_cfg.get("overcommit") or {}, capacity_cfg.get("targets") or {})

    directory = None
    ident = inst.get("identity") or {}
    if ident.get("directory", "keycloak") == "keycloak" and settings.directory_client_secret:
        realm = issuer.rsplit("/realms/", 1)[1]
        base = settings.keycloak_admin_url or issuer.rsplit("/realms/", 1)[0]
        directory = CachedDirectory(KeycloakAdminDirectory(base, realm, ident.get("adminClient", "cmapi-directory"),
                                                           settings.directory_client_secret,
                                                           _http_for_directory(settings.verify)),
                                    ttl_seconds=int(ident.get("cacheSeconds", 900)))
    integrations = _yaml(settings.config_dir / "integrations.yaml")
    ctx = AppContext(settings=settings, cfg=cfg, db=db, auth=auth, registry=registry, git=git,
                     pipeline=None, directory=directory,  # type: ignore[arg-type]
                     lister=Lister(settings.cursor_key.encode() or b"unset-cursor-key",
                                   Sorts({"used": lambda r: r["used"], "severity": lambda r: severity(r["used"]),
                                          "newest": lambda r: r.get("_created", 0.0)})),
                     delivery=DeliveryConfig.from_integrations(integrations), integrations=integrations,
                     capacity_cfg=capacity_cfg, issuer=issuer, audience=audience)
    reserved = (inst.get("namespaces") or {}).get("reservedPatterns") or []
    ctx.pipeline = Pipeline(cfg, registry, git, validator, capacity, directory, reserved, auto_paused=ctx.auto_paused)
    return ctx
