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
from cmapi.core.capacity import CapacitySettings
from cmapi.core.capacity_backend import SimulatedCapacity
from cmapi.core.clients.kube import KubeClient
from cmapi.core.clients.nodes import NodeCache
from cmapi.core.clients.policyreports import ReportCache
from cmapi.core.config import InstanceConfig, load_instance
from cmapi.core.db import Database
from cmapi.core.db.repo import DbKeyStore, SwitchRepo
from cmapi.core.git import HostGitProvider, make_provider
from cmapi.core.identity.directory import CachedDirectory
from cmapi.core.identity.keycloak_admin import KeycloakAdminDirectory
from cmapi.core.listquery import Lister, Sorts, severity
from cmapi.core.observability import AUTO_PAUSED, CONFIG_INFO, POLICY_MODE
from cmapi.core.pipeline import Pipeline
from cmapi.core.policybundle import PolicyBundle
from cmapi.core.policygen import render_bundle
from cmapi.core.registry import ClusterRegistry, ClusterState, DirImportSource, HubImportSource, ImportSource, load_policies
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
    capacity: CapacitySettings
    issuer: str
    audience: str
    bundle: PolicyBundle | None = None                      # the policies of the bundle, by environment (#302)
    deliverer_factory: Callable[[str], Any] | None = None   # tests inject a fake cluster write client

    def auto_paused(self) -> bool:
        with self.db.session() as s:
            v = SwitchRepo(s).get("auto-approval")
        paused = bool(v and v.get("paused"))
        AUTO_PAUSED.set(1 if paused else 0)
        return paused

    def shutdown(self) -> None:
        self.registry.stop()
        dispose = getattr(self.git, "dispose", None)
        if dispose:                                     # the Git layer's workdir lock, and a temporary workdir
            dispose()


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

    # The Kyverno bundle from this instance's own configuration (#212), so plan time always checks what it configures, and
    # the Policies tab reads each cluster's reports against the same policies (#302).
    bundle = render_bundle(cfg.tiers, cfg.metadata, cfg.policy, cfg.allowed_environments, cfg.name)
    policy_bundle = PolicyBundle(bundle, policies_dir=settings.policies_dir)

    def reports_for(st: ClusterState, client: KubeClient) -> ReportCache | None:
        """A report cache for a cluster whose environment runs Kyverno; none with engine none or mode off (no call at all)."""
        env = st.environment
        if env is None or cfg.policy.mode_for(env) == "off":
            return None
        return ReportCache(client, policy_bundle.for_environment(env), max_rows=cfg.policy.max_results_per_cluster)

    capacity_cfg = _yaml(settings.config_dir / "capacity.yaml")
    capacity_settings = CapacitySettings(capacity_cfg)

    def nodes_for(st: ClusterState, client: KubeClient) -> NodeCache:
        """The nodes of every connected cluster, for its allocatable (#302): a cluster without the grant answers 403, which
        is the node part's `forbidden` state, and the commitment against a simulated size is still known."""
        return NodeCache(client, capacity_settings.count_taints)

    policies = load_policies(settings.config_dir / "clusters.yaml", cfg.allowed_environments, cfg.cluster_tokens)
    if import_source is None:
        if settings.imports_dir:
            import_source = DirImportSource(settings.imports_dir)
        elif settings.kube_token_file.exists():
            import_source = HubImportSource(settings.kube_api_url, settings.kube_token_file, settings.kube_ca_file,
                                            settings.imports_namespace)
    # Cluster trust (#434): the system store and CMAPI_TRUSTED_CA_FILE, or caData, or insecure where clusterTLS allows it.
    # CMAPI_CA_BUNDLE is Keycloak's trust (and Git's default) and no longer a cluster's.
    registry = ClusterRegistry(policies, import_source, trusted_ca_file=settings.trusted_ca_file,
                               insecure_environments=cfg.cluster_tls.insecure_environments,
                               start_caches=start_registry, reports_factory=reports_for,
                               # Only the API reads allocatable (GET /api/v1/capacity): the worker opens no Node watch.
                               nodes_factory=nodes_for if settings.component == "api" else None)
    if start_registry:
        registry.start()

    g = inst["git"]
    git = make_provider(settings.git_provider, settings.git_url, g["repository"], settings.git_token,
                        default_branch=settings.git_default_branch, verify=settings.git_verify,
                        web_url=g.get("webUrl"),
                        basic_auth=(settings.git_user, settings.git_password) if settings.git_user else None,
                        # The Git layer (#286): the clone URL, its credential files, its storage and its trust.
                        git_layer=settings.component == "worker", git_url=g.get("url"), workdir=settings.git_workdir,
                        credentials_dir=settings.git_credentials_dir, ssh_dir=settings.git_ssh_dir,
                        known_hosts_dir=settings.git_known_hosts_dir, ca_bundle=settings.git_ca_bundle or settings.ca_bundle,
                        username=g.get("username"), commit_email=g.get("commitEmail"), host_checks=bool(g.get("hostChecks", False)),
                        post_status=bool(g.get("postStatus", False)), size_limit=settings.git_workdir_limit_bytes)
    validator = CliValidator(settings.policies_dir, schema_location=os.environ.get("CMAPI_KUBECONFORM_SCHEMAS") or None,
                             kubernetes_version=os.environ.get("CMAPI_KUBERNETES_VERSION") or None,
                             policy=cfg.policy, environments=cfg.allowed_environments, bundle=bundle)
    for env, mode in cfg.policy.modes(cfg.allowed_environments).items():
        POLICY_MODE.labels(env, mode).set(1)
    capacity = SimulatedCapacity(registry, capacity_settings)

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
                     capacity_cfg=capacity_cfg, capacity=capacity_settings, issuer=issuer, audience=audience, bundle=policy_bundle)
    reserved = (inst.get("namespaces") or {}).get("reservedPatterns") or []
    ctx.pipeline = Pipeline(cfg, registry, git, validator, capacity, directory, reserved, auto_paused=ctx.auto_paused)
    return ctx
