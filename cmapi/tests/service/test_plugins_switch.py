"""config/plugins.yaml (#144, docs/02 "Plugin architecture"): which plugins an instance mounts, and the environments
where an override stops a plugin's writes.

The service suite's instance is nonprod, which serves rnd and dev, and its one cluster, CRC, is dev.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.routing import APIRoute
from prometheus_client import REGISTRY

from cmapi.core.config import ConfigError, load_instance
from conftest import EXAMPLES, build_world
from test_flow import NS, OLA, auth

ADMIN = dict(roles=["cmapi-admin"], groups=["/cmapi/app-cmapi-rbac-admin"])
VIEWER = dict(roles=["cmapi-viewer"], groups=["/cmapi/app-cmapi-rbac-viewer"])
ALL = ["namespaces", "tiers", "directory", "quotas"]


def config_with(test_config: Path, tmp_path: Path, plugins: object) -> Path:
    """A copy of the suite's configuration folder with this plugins.yaml."""
    d = tmp_path / "config"
    d.mkdir()
    for f in test_config.iterdir():
        (d / f.name).write_text(f.read_text())
    (d / "plugins.yaml").write_text(plugins if isinstance(plugins, str) else yaml.safe_dump(plugins))
    return d


def load(config_dir: Path):
    return load_instance(config_dir, config_dir / "metadata-keys.yaml")


def refused(plugin: str, env: str) -> float:
    return REGISTRY.get_sample_value("cmapi_plugin_disabled_total", {"plugin": plugin, "environment": env}) or 0.0


# ---------------------------------------------------------------- the file is optional

def test_without_the_file_each_built_in_plugin_is_mounted(world):
    client, _, _, _, _, keys = world
    spec = client.get("/openapi.json").json()
    assert {t["name"] for t in spec["tags"]} == {"core", "requests", "admin", *ALL}
    listed = client.get("/api/v1/admin/plugins", headers=auth(keys, "ada", **ADMIN)).json()
    assert listed["configured"] is False and listed["instance"] == "nonprod"
    assert [(p["name"], p["core"], p["enabled"], p["disabledEnvironments"]) for p in listed["items"]] == [
        ("admin", True, True, []), ("core", True, True, []), ("requests", True, True, []),
        ("directory", False, True, []), ("namespaces", False, True, []), ("quotas", False, True, []), ("tiers", False, True, [])]
    assert all(p["version"] for p in listed["items"])


@pytest.mark.parametrize("instance", ["nonprod", "staging", "prod"])
def test_the_sample_of_each_instance_loads_and_enables_each_built_in_plugin(instance):
    folder = EXAMPLES / "instances" / instance
    cfg = load_instance(folder, EXAMPLES / "cluster-configs" / "policies" / "metadata-keys.yaml")
    assert (folder / "plugins.yaml").exists() and cfg.plugins.configured
    assert sorted(cfg.plugins.enabled) == sorted(ALL)
    assert "plugins.yaml" in cfg.hashes


# ---------------------------------------------------------------- a plugin that is not enabled

def test_a_plugin_that_is_not_enabled_has_no_route_no_tag_and_no_line_in_the_spec(test_config, tmp_path, fresh_db, keys, monkeypatch):
    d = config_with(test_config, tmp_path, {"enabled": ["namespaces", "tiers", "directory"]})
    with build_world(d, keys, monkeypatch) as (client, *_):
        h = auth(keys, "ada", **ADMIN)
        assert client.get("/api/v1/quotas", headers=h).status_code == 404
        assert client.get("/api/v1/quotas:export?format=csv", headers=h).status_code == 404
        assert client.get("/api/v1/tiers", headers=h).status_code == 200
        spec = client.get("/openapi.json").json()
        assert "quotas" not in {t["name"] for t in spec["tags"]}
        assert all("quotas" not in group["tags"] for group in spec["x-tagGroups"])
        assert not [p for p in spec["paths"] if p.startswith("/api/v1/quotas")]
        assert '"quotas_' not in json.dumps(spec), "an operationId of the plugin is still in the document"
        rows = {p["name"]: p for p in client.get("/api/v1/admin/plugins", headers=h).json()["items"]}
        assert rows["quotas"] == {"name": "quotas", "core": False, "enabled": False, "version": None, "disabledEnvironments": []}
        assert rows["tiers"]["enabled"] is True


def test_an_empty_list_leaves_the_core_only(test_config, tmp_path, fresh_db, keys, monkeypatch):
    with build_world(config_with(test_config, tmp_path, {"enabled": []}), keys, monkeypatch) as (client, *_):
        spec = client.get("/openapi.json").json()
        assert {t["name"] for t in spec["tags"]} == {"core", "requests", "admin"}
        assert client.get("/api/v1/me", headers=auth(keys, "ola", **OLA)).status_code == 200
        assert client.get("/api/v1/clusters/CRC/namespaces", headers=auth(keys, "ola", **OLA)).status_code == 404


# ---------------------------------------------------------------- an override stops the writes in one environment

def test_an_override_refuses_each_write_in_that_environment_and_keeps_the_reads(test_config, tmp_path, fresh_db, keys, monkeypatch):
    d = config_with(test_config, tmp_path, {"enabled": ALL, "overrides": {"nonprod": {"dev": {"disabled": ["namespaces"]}}}})
    with build_world(d, keys, monkeypatch) as (client, ctx, git, *_):
        before = refused("namespaces", "dev")
        base = "/api/v1/clusters/CRC/namespaces"
        etag = {"If-Match": '"0000000000000000"'}
        calls = [("POST", base, NS, {}),
                 ("POST", base + "?dryRun=true", NS, {}),
                 ("PATCH", base + "/payments-dev", {"tier": "medium"}, etag),
                 ("DELETE", base + "/payments-dev", None, etag),
                 ("POST", base + "/payments-dev/expiration:extend", {"days": 7}, etag)]
        for method, path, body, extra in calls:
            r = client.request(method, path, json=body, headers={**auth(keys, "ola", **OLA), **extra})
            assert r.status_code == 422, f"{method} {path}: {r.status_code} {r.text}"
            problem = r.json()
            assert r.headers["content-type"] == "application/problem+json"
            assert (problem["code"], problem["plugin"], problem["environment"]) == ("plugin-disabled", "namespaces", "dev"), problem
            assert "plugins.yaml" in problem["detail"] and "nonprod" in problem["detail"]
        assert refused("namespaces", "dev") - before == len(calls)
        assert client.get("/api/v1/requests", headers=auth(keys, "ola", **OLA)).json()["page"]["total"] == 0
        assert git.prs == {}
        assert client.get(base, headers=auth(keys, "ola", **OLA)).status_code == 200, "an override stops the writes, not the reads"
        rows = {p["name"]: p for p in client.get("/api/v1/admin/plugins", headers=auth(keys, "ada", **ADMIN)).json()["items"]}
        assert rows["namespaces"]["enabled"] is True and rows["namespaces"]["disabledEnvironments"] == ["dev"]


def test_the_permission_is_checked_before_the_override(test_config, tmp_path, fresh_db, keys, monkeypatch):
    """A caller who cannot write learns nothing about plugins.yaml: the answer is the 403 that it was before."""
    d = config_with(test_config, tmp_path, {"enabled": ALL, "overrides": {"nonprod": {"dev": {"disabled": ["namespaces"]}}}})
    with build_world(d, keys, monkeypatch) as (client, *_):
        r = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "vic", **VIEWER))
        assert (r.status_code, r.json()["code"]) == (403, "forbidden")


def test_an_override_of_another_environment_or_another_instance_changes_nothing_here(test_config, tmp_path, fresh_db, keys, monkeypatch):
    plugins = {"enabled": ALL, "overrides": {"nonprod": {"rnd": {"disabled": ["namespaces"]}},
                                              "prod": {"prod": {"disabled": ["namespaces"]}}}}
    with build_world(config_with(test_config, tmp_path, plugins), keys, monkeypatch) as (client, *_):
        r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA))
        assert r.status_code == 200, r.text


def test_the_problem_is_registered_and_each_namespace_write_declares_it(world):
    client, *_ = world
    spec = client.get("/openapi.json").json()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if op.get("x-cmapi-plugin") == "namespaces" and method != "get":
                examples = op["responses"]["422"]["content"]["application/problem+json"]["examples"]
                assert examples["plugin-disabled"]["value"]["status"] == 422, f"{method} {path}"


# ---------------------------------------------------------------- a mistake in the file stops startup

MISTAKES = [
    ({"enabled": ["namespaces", "netpol"]}, "enabled: unknown plugin 'netpol'"),
    ({"enabled": ["namespaces", "admin"]}, "enabled: admin is a part of the core and cannot be switched"),
    ({"enabled": ["tiers", "tiers"]}, "enabled: tiers is named 2 times"),
    ({"enabled": "namespaces"}, "enabled: must be a list of plugin names"),
    ({"overrides": {}}, "enabled: must be a list of plugin names"),
    ("", "enabled: must be a list of plugin names"),
    ({"enabled": ALL, "disabled": ["quotas"]}, "unknown key 'disabled'"),
    ({"enabled": ALL, "overrides": ["dev"]}, "overrides: must be a mapping of instance, then environment"),
    ({"enabled": ALL, "overrides": {"nonprod": {"prod": {"disabled": ["namespaces"]}}}},
     "overrides.nonprod.prod: prod is not in allowedEnvironments ['dev', 'rnd']"),
    ({"enabled": ALL, "overrides": {"nonprod": {"dev": {"disabled": ["netpol"]}}}}, "overrides.nonprod.dev.disabled: unknown plugin 'netpol'"),
    ({"enabled": ALL, "overrides": {"nonprod": {"dev": {"enabled": ["namespaces"]}}}}, "overrides.nonprod.dev: must have the one key `disabled`"),
    ({"enabled": ["tiers"], "overrides": {"nonprod": {"dev": {"disabled": ["namespaces"]}}}},
     "overrides.nonprod.dev.disabled: namespaces is not in `enabled`, so the override changes nothing"),
    ({"enabled": ALL, "overrides": {"nonprod": {"dev": {"disabled": ["quotas"]}}}},
     "overrides.nonprod.dev.disabled: quotas has no write, so the override changes nothing"),
    # The second reader's cases (Codex, C4): a value of another YAML type must not pass as "no override", and must not raise
    # an error that the loader does not collect.
    ("enabled: [namespaces]\noverrides: []", "overrides: must be a mapping of instance, then environment"),
    ("enabled: [namespaces]\noverrides: false", "overrides: must be a mapping of instance, then environment"),
    ("enabled: [namespaces]\noverrides: {nonprod: []}", "overrides.nonprod: must be a mapping of environment to `disabled`"),
    ("enabled: [namespaces]\noverrides: {nonprod: 0}", "overrides.nonprod: must be a mapping of environment to `disabled`"),
    ("enabled: [namespaces]\noverrides: {nonprod: {dev: null}}", "overrides.nonprod.dev: must have the one key `disabled`"),
    ("enabled: [namespaces]\noverrides: {nonprod: {dev: {disabled: [[namespaces]]}}}", "overrides.nonprod.dev.disabled: must be a list of plugin names"),
    ("enabled: [namespaces]\noverrides: {7: {dev: {disabled: [namespaces]}}}", "overrides.7: the name of an instance must be a text"),
    ("enabled: [namespaces]\noverrides: {nonprod: {on: {disabled: [namespaces]}}}", "overrides.nonprod.True: the name of an environment must be a text"),
    ("enabled: [1, true]", "enabled: must be a list of plugin names"),
    ("enabled: [namespaces]\n1: ignored\nextra: ignored", "unknown key 1"),
]


@pytest.mark.parametrize("plugins, message", MISTAKES, ids=[f"{n}: {m}" for n, (_, m) in enumerate(MISTAKES)])
def test_a_mistake_in_the_file_stops_startup_and_names_the_file(test_config, tmp_path, plugins, message):
    with pytest.raises(ConfigError) as caught:
        load(config_with(test_config, tmp_path, plugins))
    assert any(p.startswith("plugins.yaml: ") and message in p for p in caught.value.problems), caught.value.problems


@pytest.mark.parametrize("overrides", ["", "overrides:", "overrides: {}", "overrides: {nonprod: }", "overrides: {nonprod: {}}"])
def test_an_empty_overrides_block_is_no_override(test_config, tmp_path, overrides):
    cfg = load(config_with(test_config, tmp_path, "enabled: [namespaces]\n" + overrides))
    assert cfg.plugins.offers("namespaces", "dev") and cfg.plugins.disabled_environments("namespaces") == []


def test_each_mistake_of_the_file_is_reported_in_one_start(test_config, tmp_path):
    plugins = {"enabled": ["namespaces", "netpol"], "extra": 1, "overrides": {"nonprod": {"qa": {"disabled": []}}}}
    with pytest.raises(ConfigError) as caught:
        load(config_with(test_config, tmp_path, plugins))
    text = "\n".join(caught.value.problems)
    assert "unknown key 'extra'" in text and "unknown plugin 'netpol'" in text and "qa is not in allowedEnvironments" in text


def test_the_app_does_not_start_on_an_unknown_plugin(test_config, tmp_path, fresh_db, keys, monkeypatch):
    with pytest.raises(ConfigError, match="unknown plugin 'netpol'"):
        with build_world(config_with(test_config, tmp_path, {"enabled": ["netpol"]}), keys, monkeypatch):
            pass


# ---------------------------------------------------------------- the table of plugins is the code's

def test_the_plugins_that_the_switch_knows_are_the_routers_and_their_writes(world):
    """core/plugins.py names each built-in plugin and the ones with a write. This holds both lists to the routers, so a new
    plugin cannot be mounted without the switch, and an override cannot be accepted for a plugin that it would not stop."""
    from cmapi.core.plugins import BUILT_IN, CORE, WRITERS, PluginSwitch

    client, *_ = world
    routers = {r.plugin: r for r in PluginSwitch(None, "nonprod", {"dev"}).routers()}
    assert sorted(routers) == sorted(BUILT_IN)
    mounted = {route.openapi_extra["x-cmapi-plugin"] for route in client.app.routes
               if isinstance(route, APIRoute) and route.path.startswith("/api/")}
    assert mounted == set(BUILT_IN) | set(CORE)
    with_a_write = {name for name, r in routers.items() if any(route.methods - {"GET", "HEAD"} for route in r.routes)}
    assert with_a_write == set(WRITERS)
