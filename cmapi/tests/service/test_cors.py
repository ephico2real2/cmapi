"""Which browser origins can call the API (#206). docs/15, "The portal's origin and the API", has the decision.

The tests send what a browser sends: an Origin header, and for a call with Authorization a preflight first. They read what
a browser reads: Access-Control-Allow-Origin on the answer, or the browser hides the answer from the page.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from cmapi.core.cors import EXPOSED_HEADERS, CorsConfigError, allowed_origins, origin_of
from conftest import build_world
from test_flow import NS, OLA, auth

PORTAL = "https://portal-nonprod.ephico2real.com"          # the origin of portalUrl in examples/instances/nonprod/instance.yaml
OTHER = "https://evil.example"
URL = "/api/v1/clusters/CRC/namespaces"
ACAO, ACAC = "access-control-allow-origin", "access-control-allow-credentials"


def preflight(client, origin: str, method: str = "POST", headers: str = "authorization,content-type,idempotency-key", path: str = URL):
    return client.options(path, headers={"Origin": origin, "Access-Control-Request-Method": method,
                                         "Access-Control-Request-Headers": headers})


def with_instance(test_config: Path, tmp_path: Path, change) -> Path:
    """A copy of the test configuration with instance.yaml changed by `change(instance)`."""
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    raw = yaml.safe_load((d / "instance.yaml").read_text())
    change(raw["instance"])
    (d / "instance.yaml").write_text(yaml.safe_dump(raw))
    return d


# ---- the portal's origin

def test_a_preflight_from_the_portal_passes(world):
    client, *_ = world
    r = preflight(client, PORTAL, headers="authorization,content-type,idempotency-key,if-match")
    assert r.status_code == 200, r.text
    assert r.headers[ACAO] == PORTAL and "Origin" in r.headers["vary"]
    assert {"POST", "PATCH", "DELETE", "GET"} <= set(r.headers["access-control-allow-methods"].split(", "))
    allowed = r.headers["access-control-allow-headers"].lower().split(", ")
    assert {"authorization", "content-type", "idempotency-key", "if-match"} <= set(allowed)
    assert r.headers["access-control-max-age"] == "600"
    assert ACAC not in r.headers                        # no cookie is ever read, so credentials are never allowed


def test_a_call_from_the_portal_can_read_the_answer_and_the_etag(world):
    client, ctx, git, kube, validator, keys = world
    h = {**auth(keys, "ola", **OLA), "Origin": PORTAL}
    r = client.get("/api/v1/tiers?environment=dev", headers=h)
    assert r.status_code == 200 and r.headers[ACAO] == PORTAL and "Origin" in r.headers["vary"]
    exposed = r.headers["access-control-expose-headers"].split(", ")
    assert exposed == EXPOSED_HEADERS and {"ETag", "Retry-After", "X-Request-Id"} <= set(exposed)
    assert ACAC not in r.headers
    created = client.post(URL, json=NS, headers=h)
    assert created.status_code == 202 and created.headers[ACAO] == PORTAL


@pytest.mark.parametrize("make,status,code", [
    (lambda keys: {}, 401, "unauthenticated"),
    (lambda keys: {"Authorization": f"Bearer {keys.token('vic', roles=[], groups=[])}"}, 403, "forbidden"),
    (lambda keys: {"Authorization": f"Bearer {keys.token('ola', **OLA)}"}, 400, "idempotency-key-required"),
])
def test_a_problem_carries_the_header_so_the_portal_can_read_it(world, make, status, code):
    client, ctx, git, kube, validator, keys = world
    r = client.post(URL, json=NS, headers={**make(keys), "Origin": PORTAL})
    assert r.status_code == status and r.json()["code"] == code, r.text
    assert r.headers[ACAO] == PORTAL
    if status == 401:
        assert "WWW-Authenticate" in r.headers["access-control-expose-headers"]


def test_a_validation_refusal_and_a_missing_route_carry_the_header(world):
    client, ctx, git, kube, validator, keys = world
    h = {"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Origin": PORTAL}
    bad = client.post(URL + "?dryRun=true", json={"namespace": "Not A Name"}, headers=h)
    assert bad.status_code == 422 and bad.headers[ACAO] == PORTAL
    assert client.get("/api/v1/nothing-here", headers=h).headers[ACAO] == PORTAL


# ---- each other origin

@pytest.mark.parametrize("origin", [OTHER, "null", PORTAL + ".evil.example", "http://portal-nonprod.ephico2real.com",
                                    PORTAL + ":8443", PORTAL.replace("portal-", "PORTAL-"), PORTAL + "/"])
def test_another_origin_gets_no_cors_header(world, origin):
    client, ctx, git, kube, validator, keys = world
    p = preflight(client, origin)
    assert p.status_code == 400 and ACAO not in p.headers, p.headers          # the browser stops here: the call is not sent
    r = client.get("/api/v1/tiers?environment=dev", headers={**auth(keys, "ola", **OLA), "Origin": origin})
    assert ACAO not in r.headers and ACAC not in r.headers                      # and it would hide this answer from the page


def test_a_preflight_for_a_header_or_a_method_that_is_not_listed_is_refused(world):
    client, *_ = world
    assert preflight(client, PORTAL, headers="authorization,x-evil").status_code == 400
    assert preflight(client, PORTAL, method="PUT").status_code == 400
    assert preflight(client, PORTAL, method="TRACE").status_code == 400


def test_a_call_with_no_origin_is_as_before(world):
    client, ctx, git, kube, validator, keys = world
    r = client.get("/api/v1/tiers?environment=dev", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and ACAO not in r.headers and "access-control-expose-headers" not in r.headers


# ---- the configuration

def test_cors_allowed_origins_is_the_list_when_it_is_set(test_config, tmp_path, fresh_db, keys, monkeypatch):
    listed = ["https://portal.example.com", "http://localhost:5173"]
    d = with_instance(test_config, tmp_path, lambda i: i.update({"cors": {"allowedOrigins": listed}}))
    with build_world(d, keys, monkeypatch) as (client, *_):
        for origin in listed:
            assert preflight(client, origin).headers[ACAO] == origin
        assert ACAO not in preflight(client, PORTAL).headers             # portalUrl is not added to an explicit list


def test_an_empty_list_turns_cors_off(test_config, tmp_path, fresh_db, keys, monkeypatch):
    d = with_instance(test_config, tmp_path, lambda i: i.update({"cors": {"allowedOrigins": []}}))
    with build_world(d, keys, monkeypatch) as (client, ctx, git, kube, validator, k):
        r = client.get("/api/v1/tiers?environment=dev", headers={**auth(k, "ola", **OLA), "Origin": PORTAL})
        assert r.status_code == 200 and ACAO not in r.headers
        assert ACAO not in preflight(client, PORTAL).headers


@pytest.mark.parametrize("value,why", [
    ("*", "wildcard"), ("https://*.example.com", "wildcard"), ("null", "opaque origin"),
    ("https://portal.example.com/", "no path"), ("https://portal.example.com/app", "no path"),
    ("https://portal.example.com?x=1", "no path"), ("https://user@portal.example.com", "no path"),
    ("http://portal.example.com", "must be https"), ("ftp://portal.example.com", "must be https://host"),
    ("portal.example.com", "must be https://host"), ("https://Portal.example.com", "as the browser sends it"),
    ("https://portal.example.com:443", "as the browser sends it"), ("https://portal.example.com:port", "not a URL"),
    (5173, "is not text"), ("", "is not text"),
])
def test_a_value_that_is_not_an_exact_origin_stops_the_start(value, why):
    with pytest.raises(CorsConfigError, match=why):
        allowed_origins({"cors": {"allowedOrigins": ["https://portal.example.com", value]}})


def test_the_default_is_the_origin_of_portal_url():
    assert allowed_origins({"portalUrl": "https://Portal.example.com:443/portal/"}) == ["https://portal.example.com"]
    assert allowed_origins({"portalUrl": "http://localhost:5173/"}) == ["http://localhost:5173"]
    assert allowed_origins({}) == [] and allowed_origins({"portalUrl": ""}) == []
    assert allowed_origins({"cors": {}, "portalUrl": "https://p.example.com"}) == ["https://p.example.com"]
    assert origin_of("http://[::1]:5173/x") == "http://[::1]:5173"
    with pytest.raises(CorsConfigError, match="portalUrl"):
        allowed_origins({"portalUrl": "http://portal.example.com"})        # a portal on plain http, not on localhost
    for bad in ({"cors": []}, {"cors": {"allowedOrigins": "https://p.example.com"}}):
        with pytest.raises(CorsConfigError):
            allowed_origins(bad)


def test_a_bad_origin_in_instance_yaml_stops_the_app(test_config, tmp_path, fresh_db, keys, monkeypatch):
    d = with_instance(test_config, tmp_path, lambda i: i.update({"cors": {"allowedOrigins": ["*"]}}))
    with pytest.raises(CorsConfigError, match="wildcard"):
        with build_world(d, keys, monkeypatch):
            pass


# ---- #216: an exception that no handler takes

def test_an_unhandled_exception_is_a_problem_that_the_portal_can_read(world, capsys):
    client, ctx, git, kube, validator, keys = world

    def boom(*a, **k):
        raise RuntimeError("secret detail of the failure")
    ctx.cfg.tiers.describe = boom
    r = client.get("/api/v1/tiers?environment=dev", headers={**auth(keys, "ola", **OLA), "Origin": PORTAL})
    assert r.status_code == 500 and r.headers["content-type"] == "application/problem+json", r.text
    body = r.json()
    assert body["code"] == "internal-error" and body["type"].endswith("/problems/internal-error") and body["status"] == 500
    assert "secret detail" not in r.text                               # the cause stays in the log
    assert r.headers[ACAO] == PORTAL and r.headers["x-request-id"]
    logged = capsys.readouterr().out
    assert '"event": "unhandled"' in logged and "secret detail of the failure" in logged and r.headers["x-request-id"] in logged


def test_an_unhandled_exception_is_counted_one_time_as_a_500(world):
    from cmapi.core.observability import HTTP_REQUESTS
    client, ctx, git, kube, validator, keys = world
    ctx.cfg.tiers.describe = lambda *a, **k: 1 / 0
    counter = HTTP_REQUESTS.labels("GET", "/api/v1/tiers", "500")
    before = counter._value.get()
    assert client.get("/api/v1/tiers", headers=auth(keys, "ola", **OLA)).status_code == 500
    assert counter._value.get() == before + 1
