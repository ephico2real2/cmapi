"""Process settings: what comes from the environment rather than from the instance's config files.

The config files (instance.yaml, tiers.yaml, ...) describe the instance and are mounted from
ConfigMaps; these settings say where they are and hold the few things that are secrets or
deployment-specific (database URL, Git token, CA bundle). Every name is CMAPI_<FIELD>.
"""
from __future__ import annotations

import ssl
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CMAPI_", extra="ignore")

    config_dir: Path = Field(default=Path("/etc/cmapi/config"), description="instance.yaml and the policy files")
    metadata_keys: Path | None = Field(default=None, description="metadata-keys.yaml; default <config_dir>/metadata-keys.yaml")
    policies_dir: Path = Field(default=Path("/etc/cmapi/policies"), description="Hand-written Kyverno policies, run with the bundle that cmapi renders from its configuration (#212)")
    ca_bundle: Path | None = Field(default=None, description="PEM bundle trusted for Keycloak, and for Git unless git_ca_bundle is set. "
                                   "Not a cluster's trust since #434: see trusted_ca_file")
    trusted_ca_file: str = Field(default="", description="Colon-separated PEM bundles that a cluster with no caData is verified "
                                 "against, after the image's system store: the bundle OpenShift injects and an operator's ConfigMap. "
                                 "A path that is not there is skipped and read again at the next check (#434)")

    database_url: str = Field(default="", description="postgresql://user:pass@host:5432/db (any psycopg URL)")
    database_pool_size: int = 5

    oidc_jwks_url: str | None = Field(default=None, description="Where to fetch the realm JWKS; default <issuer>/protocol/openid-connect/certs")
    oidc_leeway_seconds: int = 30
    directory_client_secret: str = Field(default="", description="Secret of the read-only cmapi-directory client")
    keycloak_admin_url: str | None = Field(default=None, description="Keycloak base URL for the admin API; default from the issuer")

    git_provider: str = Field(default="gitea", description="gitea | github")
    git_url: str = Field(default="", description="Base URL of the Git host API, e.g. https://gitea.example/api/v1")
    git_token: str = Field(default="", description="Bot token with write access to the cluster-configs repository")
    git_user: str = Field(default="", description="With git_password: basic auth instead of a token (the Gitea stand-in)")
    git_password: str = Field(default="", description="See git_user")
    git_default_branch: str = "main"
    git_credentials_dir: Path = Field(default=Path("/etc/cmapi/git-bot"), description="Secret cmapi-git-bot mounted as files: token, the "
                                      "bot account's API token, and optionally username. Git over HTTPS reads token too (#286)")
    git_ssh_dir: Path = Field(default=Path("/etc/cmapi/git-bot-ssh"), description="Secret cmapi-git-bot-ssh (kubernetes.io/ssh-auth), "
                              "worker only: ssh-privatekey and optionally ssh-publickey, for Git over SSH (#286)")
    git_workdir_limit_bytes: int = Field(default=1 << 30, description="The emptyDir sizeLimit of CMAPI_GIT_WORKDIR: above 80 % the "
                                         "sweeper removes the workdir, to be fetched again (#286)")
    git_known_hosts_dir: Path = Field(default=Path("/etc/cmapi/git-bot-known-hosts"), description="ConfigMap "
                                      "cmapi-git-bot-known-hosts mounted as a folder: known_hosts, the Git host's pinned keys (#286)")
    git_workdir: Path | None = Field(default=None, description="The Git layer's working storage: the mirror and one worktree per request. "
                                     "The pods mount an emptyDir with a sizeLimit here; unset, a temporary folder of the process (#286)")
    git_ca_bundle: Path | None = Field(default=None, description="PEM bundle trusted for the Git host alone; default: ca_bundle's trust. "
                                       "On CRC the image's system bundle, since cmapi-trust holds only Keycloak's private CA (#97)")

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

    @property
    def git_verify(self) -> ssl.SSLContext | str | bool:
        """The Git provider's verify= value. With git_ca_bundle, an SSLContext built from that file alone: httpx honours
        SSL_CERT_FILE for verify=True (httpx 0.28.1, _config.create_ssl_context), and the pods point it at cmapi-trust, so an
        explicit context is the only trust no environment variable can change (#97). A missing file raises at start."""
        if self.git_ca_bundle:
            return ssl.create_default_context(cafile=str(self.git_ca_bundle))
        return self.verify


@lru_cache
def settings() -> Settings:
    return Settings()
