"""Process settings: what comes from the environment rather than from the instance's config files.

The config files (instance.yaml, tiers.yaml, ...) describe the instance and are mounted from
ConfigMaps; these settings say where they are and hold the few things that are secrets or
deployment-specific (database URL, Git token, CA bundle). Every name is CMAPI_<FIELD>.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CMAPI_", extra="ignore")

    config_dir: Path = Field(default=Path("/etc/cmapi/config"), description="instance.yaml and the policy files")
    metadata_keys: Path | None = Field(default=None, description="metadata-keys.yaml; default <config_dir>/metadata-keys.yaml")
    policies_dir: Path = Field(default=Path("/etc/cmapi/policies"), description="Kyverno bundle the validator runs")
    ca_bundle: Path | None = Field(default=None, description="PEM bundle trusted for Keycloak, Git and cluster calls")

    database_url: str = Field(default="", description="postgresql://user:pass@host:5432/db (any psycopg URL)")
    database_pool_size: int = 5

    oidc_jwks_url: str | None = Field(default=None, description="Where to fetch the realm JWKS; default <issuer>/protocol/openid-connect/certs")
    oidc_leeway_seconds: int = 30
    directory_client_secret: str = Field(default="", description="Secret of the read-only cmapi-directory client")
    keycloak_admin_url: str | None = Field(default=None, description="Keycloak base URL for the admin API; default from the issuer")

    git_provider: str = Field(default="gitea", description="gitea | github")
    git_url: str = Field(default="", description="Base URL of the Git host API, e.g. https://gitea.example/api/v1")
    git_token: str = Field(default="", description="Bot token with write access to the cluster-configs repository")
    git_default_branch: str = "main"

    cursor_key: str = Field(default="", description="HMAC key signing list cursors; generated per instance")
    link_key: str = Field(default="", description="HMAC key signing email approval links")

    imports_namespace: str = Field(default="cmapi-imports", description="Hub namespace holding the cluster import Secrets")
    imports_dir: Path | None = Field(default=None, description="Read import Secrets from YAML files here instead of the hub API (tests, local runs)")
    kube_token_file: Path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    kube_ca_file: Path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    kube_api_url: str = "https://kubernetes.default.svc"

    component: str = Field(default="api", description="api | worker | capacity: the cmapi_build_info component label")
    log_level: str = "INFO"
    bind_port: int = 8080
    metrics_port: int = 9090
    worker_poll_seconds: float = 2.0
    worker_id: str = Field(default="", description="Pod name; defaults to the hostname")

    @property
    def metadata_keys_path(self) -> Path:
        return self.metadata_keys or self.config_dir / "metadata-keys.yaml"

    @property
    def verify(self) -> str | bool:
        """httpx verify= value: the CA bundle when one is mounted, else the system store."""
        return str(self.ca_bundle) if self.ca_bundle else True


@lru_cache
def settings() -> Settings:
    return Settings()
