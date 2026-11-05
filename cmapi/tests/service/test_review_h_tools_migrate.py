"""C8 tools against a fake host; C9 migrations on real PostgreSQL; C7 the chart's config loads; C12 tests the suite lacks."""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys

import httpx
import psycopg
import pytest
import yaml

from conftest import DB_URL
from test_flow import AMY, NS, OLA, auth, run_jobs
from test_review_c_authz import rnd_only
from test_review_d_delivery import run_until, status

ROOT = pathlib.Path(__file__).resolve().parents[3]
SECRET = "s3cr3t-value-that-must-not-print"


def _schema_url(name):
    sep = "&" if "?" in DB_URL else "?"
    return f"{DB_URL}{sep}options=-csearch_path%3D{name}"


@pytest.fixture
def empty_schema():
    c = psycopg.connect(DB_URL, autocommit=True)
    c.execute("DROP SCHEMA IF EXISTS mig CASCADE")
    c.execute("CREATE SCHEMA mig")
    yield _schema_url("mig")
    c.execute("DROP SCHEMA mig CASCADE")
    c.close()


MIG = "from cmapi.core.db.migrate import run; run(sys.argv[1:])"


def migrate(url, *args):
    return subprocess.Popen([sys.executable, "-c", "import sys; " + MIG, *args], env={**os.environ, "CMAPI_DATABASE_URL": url, "PYTHONPATH": str(ROOT / "cmapi/src"), "PYTHONDONTWRITEBYTECODE": "1"},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def test_migrations_from_an_empty_database_up_down_up(empty_schema):
    for args in (["head"], ["base", "--downgrade"], ["head"]):
        p = migrate(empty_schema, *args)
        out = p.communicate()[0]
        assert p.returncode == 0, out[-800:]


def test_two_migrators_at_once_both_succeed(empty_schema, capsys):
    results = []
    for round_ in range(5):
        c = psycopg.connect(DB_URL, autocommit=True)
        c.execute("DROP SCHEMA mig CASCADE")
        c.execute("CREATE SCHEMA mig")
        c.close()
        ps = [migrate(empty_schema, "head") for _ in range(2)]
        outs = [p.communicate()[0] for p in ps]
        results.append([(p.returncode, (o.strip().splitlines() or [""])[-1][:90]) for p, o in zip(ps, outs)])
    with capsys.disabled():
        print("\n[measure] two cmapi-migrate at once, 5 rounds:", results)
    assert all(rc == 0 for r in results for rc, _ in r), results


class FakeHost:
    """Enough of Gitea or the Keycloak admin API to run a tool; records every request."""

    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def transport(self):
        def h(req):
            self.calls.append((req.method, req.url.path, req.content.decode() if req.content else ""))
            return self.handler(req)
        return httpx.MockTransport(h)


def patch_httpx(monkeypatch, host):
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real(*a, **{**{x: y for x, y in k.items() if x != "verify"}, "transport": host.transport()}))
    monkeypatch.setattr(httpx, "get", lambda url, **k: real(transport=host.transport()).get(url))


def test_git_bootstrap_seeds_a_repository_left_empty_by_a_crash(monkeypatch, tmp_path, capsys):
    """Killed between creating the repository and the seed commit, the next run must seed it, or main never exists."""
    from cmapi.settings import settings
    import importlib
    git_bootstrap = importlib.import_module("cmapi.tools.git_bootstrap")

    def handler(req):
        p, m = req.url.path, req.method
        if p.endswith("/version"):
            return httpx.Response(200, json={"version": "1.25"})
        if "/branches/" in p and "branch_protections" not in p:
            return httpx.Response(404, json={})
        if "branch_protections" in p and m == "GET":
            return httpx.Response(404, json={})
        if m == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(200, json={})
    host = FakeHost(handler)
    patch_httpx(monkeypatch, host)
    for k, v in {"CMAPI_GIT_URL": "https://git.test/api/v1", "CMAPI_GIT_ADMIN_USER": "a", "CMAPI_GIT_ADMIN_PASSWORD": SECRET, "CMAPI_GIT_PASSWORD": SECRET + "2",
                 "CMAPI_GIT_REPOSITORY": "cmapi/cfg", "CMAPI_GIT_CLUSTER_IDS": "CRC", "CMAPI_POLICIES_DIR": str(tmp_path), "CMAPI_METADATA_KEYS": str(tmp_path / "none")}.items():
        monkeypatch.setenv(k, v)
    settings.cache_clear()
    git_bootstrap.main([])
    settings.cache_clear()
    out = capsys.readouterr().out
    assert any(m == "POST" and p.endswith("/contents") for m, p, _ in host.calls), [c[:2] for c in host.calls]
    assert SECRET not in out


def test_realm_sync_runs_and_prints_no_secret(monkeypatch, capsys):
    import importlib
    realm_sync = importlib.import_module("cmapi.tools.realm_sync")

    def handler(req):
        p, m = req.url.path, req.method
        if p.endswith("/sync"):
            return httpx.Response(200, json={"status": "ok"})
        if p.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok-" + SECRET, "expires_in": 300})
        if p.endswith("/users/profile"):
            return httpx.Response(200, json={"attributes": []})
        if p.endswith("/service-account-user"):
            return httpx.Response(200, json={"id": "sa"})
        if p.endswith("/clients"):
            return httpx.Response(200, json=[{"id": "c"}])
        if "/role-mappings/" in p and m == "GET":
            return httpx.Response(200, json=[])
        if p.endswith("/roles"):
            return httpx.Response(200, json=[{"name": n} for n in ("realm-admin", "view-users", "query-users", "cmapi-viewer", "cmapi-onboarding")])
        if p.endswith("/groups") and m == "GET":
            return httpx.Response(200, json=[{"name": "cmapi", "id": "g"}])
        if p.endswith("/children") and m == "GET":
            return httpx.Response(200, json=[{"name": "cmapi-viewers", "id": "v"}])
        if p.endswith("/components") and m == "GET":
            return httpx.Response(200, json=[{"name": "ldap", "id": "l"}])
        if p.endswith("/users") and m == "GET":
            return httpx.Response(200, json=[{"id": "u", "username": "x"}])
        if "/admin/realms/" in p and m == "GET":
            return httpx.Response(200, json={"id": "r"})
        return httpx.Response(204 if m in ("PUT", "DELETE") else 201 if m == "POST" else 200, json={} if m == "GET" else None)
    host = FakeHost(handler)
    patch_httpx(monkeypatch, host)
    for k, v in {"CMAPI_REALM_ISSUER": "https://kc.test/realms/cmapi", "CMAPI_REALM_ADMIN_CLIENT_SECRET": SECRET, "CMAPI_REALM_GROUPS": json.dumps({"cmapi-viewers": ["cmapi-viewer"]}),
                 "CMAPI_REALM_LDAP": json.dumps({"enabled": True, "connectionUrl": "ldaps://x", "usersDn": "ou=p", "groupsDn": "ou=g"}), "bindDN": "cn=b", "password": SECRET,
                 "CMAPI_REALM_TEST_USERS": "true", "ola": SECRET}.items():
        monkeypatch.setenv(k, v)
    realm_sync.main([])
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    paths = {p for _, p, _ in host.calls if p.startswith("/admin/realms/")}
    assert paths and all(p.startswith("/admin/realms/cmapi") for p in paths), "another realm reached"
    assert all(p.startswith(("/admin/realms/cmapi", "/realms/cmapi")) for _, p, _ in host.calls)


def test_the_charts_rendered_config_loads_with_the_real_adapters(tmp_path):
    """Every file the ConfigMap holds, through load_instance, the policies, and the real Git, validator and Keycloak classes."""
    from cmapi.core.context import build_context
    from cmapi.settings import Settings
    r = subprocess.run(["helm", "template", "cmapi", str(ROOT / "deploy/helm/cmapi"), "-n", "cmapi", "-f", str(ROOT / "deploy/environments/crc.yaml"), "--set", "cmapi.digest=sha256:" + "a" * 64,
                        "--set", "trustedCA.certificates=x"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    cm = next(d for d in yaml.safe_load_all(r.stdout) if d and d["kind"] == "ConfigMap" and d["metadata"]["name"] == "cmapi-config")
    for name, text in cm["data"].items():
        (tmp_path / name).write_text(text)
    s = Settings(config_dir=tmp_path, database_url=DB_URL, git_provider="gitea", git_url="http://x/api/v1", git_user="b", git_password="p", cursor_key="k", link_key="l", metrics_port=0,
                 directory_client_secret="d", policies_dir=ROOT / "cmapi/policies", kube_token_file=pathlib.Path("/nonexistent"), kube_ca_file=pathlib.Path("/nonexistent"))
    ctx = build_context(s, start_registry=False)
    assert ctx.delivery.mode == "argocd" and ctx.delivery.poll_seconds == 10 and ctx.delivery.sync_timeout_seconds == 600
    assert ctx.delivery.argocd_namespace == "cmapi-argocd" and ctx.delivery.argocd_root_application == "cluster-configs-{clusterId}"
    assert ctx.issuer == "https://keycloak.apps-crc.testing/realms/cmapi" and ctx.audience == "cmapi-nonprod"
    assert ctx.directory is not None and ctx.registry.policies["CRC"].environment == "dev"


def test_environment_role_cannot_create_in_another_environment(rnd_only):
    client, ctx, git, kube, validator, keys = rnd_only
    r = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "o", roles=["op-rnd"], employee_id="1"))
    assert r.status_code == 403 and r.json()["code"] == "environment-forbidden", r.text


def test_a_plan_changed_in_the_database_is_refused_before_the_pr(world):
    client, ctx, git, kube, validator, keys = world
    from sqlalchemy import text
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("""update change_requests set plan = jsonb_set(plan, '{spec,tier}', '"large"') where request_id=:r"""), {"r": rid})
    with pytest.raises(RuntimeError, match="plan hash mismatch"):
        run_jobs(ctx)
    assert git.prs == {}


def test_synced_only_after_a_read_confirms(world):
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    assert run_until(ctx, "watch_sync") == "watch_sync"
    ctx.delivery = type(ctx.delivery)(mode="apply", poll_seconds=0, sync_timeout_seconds=1800)
    real = kube.apply
    kube.apply = lambda doc, field_manager="x": None if doc["kind"] == "ResourceQuota" else real(doc, field_manager)
    run_jobs(ctx, limit=3)
    assert status(client, keys, rid)["status"] == "merged"
