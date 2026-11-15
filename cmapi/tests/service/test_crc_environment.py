"""environments/crc read by the service itself, not only by a YAML parser (#94, #157): the config files and the environment variables crc's ConfigMaps hold build a
real context, and the requests deploy/crc-proof.sh makes answer what it expects. Since the full flow (#157) the one cluster takes writes, the Git host is GitHub and
delivery is apply: the provider make_provider would build is recorded and replaced by conftest's FakeGit (no test calls github.com), and the cluster, the deliverer
and the validator are the fakes of conftest."""
from __future__ import annotations

import re
import ssl
import uuid
from pathlib import Path

import certifi
import pytest
import yaml
from fastapi.testclient import TestClient

from conftest import DB_URL, FakeGit, FakeKube, FakeValidator, OneSecret
from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.context import build_context
from cmapi.main import create_app
from cmapi.settings import Settings
from test_flow import run_jobs

ROOT = Path(__file__).resolve().parents[3]
ENVIRONMENT = ROOT / "deploy/manifests/environments/crc"
ISSUER = "https://keycloak.apps-crc.testing/realms/cmapi"
AUDIENCE = "cmapi-nonprod"
PROOF = (ROOT / "deploy/crc-proof.sh").read_text()
# What CRC's image trusts for the Git host: RHEL's extracted system bundle (update-ca-trust(8)). Not on a test machine, so the
# context is built with certifi's bundle in its place, and the shipped value is asserted on its own.
SYSTEM_BUNDLE = "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"


def config_map(name):
    return next(d for f in ENVIRONMENT.glob("*.yaml") for d in yaml.safe_load_all(f.read_text()) if d["kind"] == "ConfigMap" and d["metadata"]["name"] == name)["data"]


@pytest.fixture
def crc(tmp_path, fresh_db, keys, monkeypatch):
    for name, text in config_map("cmapi-config").items():
        (tmp_path / name).write_text(text)
    env = config_map("cmapi-env")
    assert env["CMAPI_GIT_CA_BUNDLE"] == SYSTEM_BUNDLE
    fields = {k.removeprefix("CMAPI_").lower(): v for k, v in env.items()} | {"git_ca_bundle": certifi.where()}
    monkeypatch.setenv("CMAPI_DATABASE_URL", DB_URL)
    settings = Settings(**fields, config_dir=tmp_path, database_url=DB_URL, cursor_key="k", link_key="l", metrics_port=0, imports_dir=None,
                        kube_token_file=Path("/nonexistent"), kube_ca_file=Path("/nonexistent"))
    import cmapi.core.context as context_mod
    git, built = FakeGit(), {}
    git.repository = "ephico2real2/cmapi-cluster-configs"

    def provider(kind, url, repository, token, **kw):
        built.update(kind=kind, url=url, repository=repository, **kw)
        return git

    monkeypatch.setattr(context_mod, "make_provider", provider)
    monkeypatch.setattr(context_mod, "CliValidator", lambda *a, **k: FakeValidator())
    kube = FakeKube()
    ctx = build_context(settings, start_registry=False, import_source=OneSecret())
    ctx.registry.client_factory = lambda *a, **k: kube
    ctx.registry.start_caches = True
    ctx.registry.refresh()
    ctx.registry.cache("CRC").wait_ready(5)
    ctx.deliverer_factory = lambda cid: kube
    ctx.auth = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, env["CMAPI_OIDC_JWKS_URL"], fetch=lambda url: [keys.jwk]))
    bot = {"Authorization": "Bearer " + keys.token("bot-user", roles=["cmapi-onboarding"], employee_id=None, iss=ISSUER, aud=AUDIENCE, client="cmapi-automation")}
    with TestClient(create_app(settings, ctx)) as client:
        yield client, ctx, bot, git, kube, built
    ctx.registry.stop()


def proof_request():
    """The body and the query, taken from the proof itself, so the two cannot drift apart."""
    body = re.search(r"-X POST -d '(\{.*?\})' \"\$API(/api/v1/clusters/CRC/namespaces\?dryRun=true)\"", PROOF)
    assert body, "crc-proof.sh no longer makes this request"
    return body[2], body[1]


def test_crc_builds_the_github_provider_on_its_own_trust(crc):
    _, ctx, _, _, _, built = crc
    assert (built["kind"], built["url"], built["repository"]) == ("github", "https://api.github.com", "ephico2real2/cmapi-cluster-configs")
    assert built["web_url"] == "https://github.com"
    assert isinstance(built["verify"], ssl.SSLContext), "the Git host's trust is its own, not cmapi-trust (#97)"
    assert ctx.delivery.mode == "apply"
    assert ctx.registry.clusters["CRC"].policy.writes is True


def test_the_proofs_dry_run_plans_and_writes_nothing(crc):
    client, ctx, bot, git, kube, _ = crc
    assert client.get("/api/v1/me").status_code == 401
    me = client.get("/api/v1/me", headers=bot)
    assert me.status_code == 200 and me.json()["username"] == "bot-user" and "roles" in me.json()
    path, body = proof_request()
    r = client.post(path, content=body, headers={**bot, "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert r.json()["changes"], "a plan shows the files it would write"
    assert git.prs == {} and set(git.branches) == {"main"}, "a dry run opens no branch and no PR"
    assert not kube.applied, "a dry run writes nothing to the cluster"
    assert client.get("/api/v1/requests", headers=bot).json()["page"]["total"] == 0


def test_a_request_on_crcs_own_configuration_is_auto_approved_merged_and_applied(crc):
    """The whole path on CRC's files: the auto-approval policy of dev, a PR whose ci/* come from the config repository's Actions
    (GitHub: external_ci), the cmapi check, the merge, then apply delivery: the namespace, its quota and its two LimitRanges."""
    client, ctx, bot, git, kube, _ = crc
    git.external_ci = True
    ns = "cmapi-flow-test"
    path, body = proof_request()
    import json
    body = {**json.loads(body), "namespace": ns}
    r = client.post(path.split("?")[0], json=body, headers={**bot, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 202, r.text
    rid = r.json()["requestId"]
    assert r.json()["status"] == "approved" and r.json()["approval"]["auto"] == "auto:baseline-rnd-namespace", r.text
    run_jobs(ctx, limit=2)
    pr = git.prs[1]
    assert pr["state"] == "open"
    head = git.heads[pr["branch"]]
    assert "ci/kubeconform" not in git.statuses.get(head, {}), "on GitHub the worker never posts ci/*: the repository's Actions do"
    for context in ("ci/kubeconform", "ci/kyverno"):         # what the config repository's workflow reports
        git.statuses.setdefault(head, {})[context] = "success"
    run_jobs(ctx)
    view = client.get(f"/api/v1/requests/{rid}", headers=bot).json()
    assert view["status"] == "synced", view["events"]
    assert {f"Namespace//{ns}", f"ResourceQuota/{ns}/{ns}-quota", f"LimitRange/{ns}/{ns}-limits-cpu",
            f"LimitRange/{ns}/{ns}-limits-memory"} <= set(kube.applied), kube.applied
    assert not any("limits-storage" in a for a in kube.applied), "the storage switch is off on CRC"
    assert kube.objects[("Namespace", "", ns)]["metadata"]["labels"]["cmapi.net/managed"] == "true", "what the admission policy requires"


def test_the_cluster_the_config_names_is_the_one_the_reader_import_names(crc):
    client, _, bot, *_ = crc
    assert re.search(r'"cmapi.net/cluster-id":"CRC"', (ROOT / "deploy/crc-reader-import.sh").read_text())
    assert client.get("/api/v1/clusters", headers=bot).json()["items"][0]["clusterId"] == "CRC"
