"""environments/crc read by the service itself, not only by a YAML parser (Wave 1, #94): the config files and the environment variables crc's ConfigMaps hold build a real context, with the
real GitHub provider pointing at the URL that cannot resolve, and the requests deploy/crc-proof.sh makes answer what it expects. The cluster and the validator are the fakes of conftest."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from conftest import DB_URL, FakeKube, FakeValidator, OneSecret
from cmapi.core.auth import Authenticator, Jwks
from cmapi.core.context import build_context
from cmapi.main import create_app
from cmapi.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
ENVIRONMENT = ROOT / "deploy/manifests/environments/crc"
ISSUER = "https://keycloak.apps-crc.testing/realms/cmapi"
AUDIENCE = "cmapi-nonprod"
PROOF = (ROOT / "deploy/crc-proof.sh").read_text()


def config_map(name):
    return next(d for f in ENVIRONMENT.glob("*.yaml") for d in yaml.safe_load_all(f.read_text()) if d["kind"] == "ConfigMap" and d["metadata"]["name"] == name)["data"]


@pytest.fixture(params=[False, True], ids=["as-shipped", "writes-on"])
def crc(request, tmp_path, fresh_db, keys, monkeypatch):
    for name, text in config_map("cmapi-config").items():
        if name == "clusters.yaml" and request.param:
            assert '"writes":false' in text
            text = text.replace('"writes":false', '"writes":true')
        (tmp_path / name).write_text(text)
    env = config_map("cmapi-env")
    fields = {k.removeprefix("CMAPI_").lower(): v for k, v in env.items()}
    monkeypatch.setenv("CMAPI_DATABASE_URL", DB_URL)
    settings = Settings(**fields, config_dir=tmp_path, database_url=DB_URL, cursor_key="k", link_key="l", metrics_port=0, imports_dir=None,
                        kube_token_file=Path("/nonexistent"), kube_ca_file=Path("/nonexistent"))
    # The real provider, with no credential: its only way out is the URL that cannot resolve.
    import cmapi.core.context as context_mod
    monkeypatch.setattr(context_mod, "CliValidator", lambda *a, **k: FakeValidator())
    kube = FakeKube()
    ctx = build_context(settings, start_registry=False, import_source=OneSecret())
    ctx.registry.client_factory = lambda *a, **k: kube
    ctx.registry.start_caches = True
    ctx.registry.refresh()
    ctx.registry.cache("CRC").wait_ready(5)
    ctx.deliverer_factory = lambda cid: kube
    ctx.auth = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, env["CMAPI_OIDC_JWKS_URL"], fetch=lambda url: [keys.jwk]))
    with TestClient(create_app(settings, ctx)) as client:
        yield request.param, client, ctx, {"Authorization": "Bearer " + keys.token("bot-user", roles=["cmapi-onboarding"], employee_id=None, iss=ISSUER, aud=AUDIENCE, client="cmapi-automation")}
    ctx.registry.stop()


def test_the_proofs_requests_answer_what_the_proof_reads(crc):
    writes_on, client, ctx, bot = crc
    assert ctx.delivery.mode == "argocd", "the worker must never write to a cluster in Wave 1"
    assert client.get("/api/v1/me").status_code == 401
    me = client.get("/api/v1/me", headers=bot)
    assert me.status_code == 200 and me.json()["username"] == "bot-user" and "roles" in me.json()
    # The body and the query, taken from the proof itself, so the two cannot drift apart.
    body = re.search(r"-X POST -d '(\{.*?\})' \"\$API(/api/v1/clusters/CRC/namespaces\?dryRun=true)\"", PROOF)
    assert body, "crc-proof.sh no longer makes this request"
    r = client.post(body[2], content=body[1], headers={**bot, "Content-Type": "application/json"})
    if writes_on:
        # The second stop: with the one cluster writable, the plan reaches Git, and the URL cannot resolve.
        assert (r.status_code, r.json()["code"]) == (502, "git-unavailable"), r.text
    else:
        assert r.status_code == 422 and "cluster-not-writable" in r.text, r.text


def test_the_cluster_the_config_names_is_the_one_the_reader_import_names(crc):
    _, client, _, bot = crc
    assert re.search(r'"cmapi.net/cluster-id":"CRC"', (ROOT / "deploy/crc-reader-import.sh").read_text())
    assert client.get("/api/v1/clusters", headers=bot).json()["items"][0]["clusterId"] == "CRC"
