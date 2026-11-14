"""Which browser origins can call the API (#206). docs/15, "The portal's origin and the API", has the decision.

The tests send what a browser sends: an Origin header, and for a call with Authorization a preflight first. They read what
a browser reads: Access-Control-Allow-Origin on the answer, or the browser hides the answer from the page.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from cmapi.core.cors import EXPOSED_HEADERS, CorsConfigError, allowed_origins
from conftest import build_world
from test_flow import NS, OLA, auth

PORTAL = "https://portal-dev.ephico2real.com"              # a portal on another origin, listed in cors.allowedOrigins below
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


@pytest.fixture
def world(test_config, tmp_path, fresh_db, keys, monkeypatch):
    """The suite's world with one listed origin. Without `cors` in instance.yaml the API sends no CORS header (see below)."""
    d = with_instance(test_config, tmp_path, lambda i: i.update({"cors": {"allowedOrigins": [PORTAL]}}))
    with build_world(d, keys, monkeypatch) as w:
        yield w


# ---- a listed origin

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

@pytest.mark.parametrize("origin", [OTHER, "null", PORTAL + ".evil.example", PORTAL.replace("https://", "http://"),
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


def test_a_call_with_no_origin_has_no_cors_header(world):
    client, ctx, git, kube, validator, keys = world
    r = client.get("/api/v1/tiers?environment=dev", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200 and ACAO not in r.headers and "access-control-expose-headers" not in r.headers


@pytest.mark.parametrize("origin", [None, OTHER])
def test_each_answer_varies_on_origin_so_a_cache_keeps_the_copies_apart(world, origin):
    """Review finding F2: Starlette adds Vary: Origin only for a listed origin. A shared cache could then give the copy with no
    CORS header to the listed origin."""
    client, *_ = world
    first = client.get("/problems", headers={"Origin": origin} if origin else {})
    assert first.status_code == 200 and ACAO not in first.headers
    assert "origin" in {v.strip().lower() for v in first.headers.get("vary", "").split(",")}
    assert client.get("/problems", headers={"Origin": PORTAL}).headers[ACAO] == PORTAL


# ---- the configuration

def test_with_no_cors_key_the_api_sends_no_cors_header(test_config, fresh_db, keys, monkeypatch):
    """One origin for the portal and the API is the design (#226), so CORS is off unless instance.yaml lists an origin. portalUrl
    does not turn it on."""
    with build_world(test_config, keys, monkeypatch) as (client, ctx, git, kube, validator, k):
        assert ctx.cfg.raw_instance["instance"].get("portalUrl") and "cors" not in ctx.cfg.raw_instance["instance"]
        origin = ctx.cfg.raw_instance["instance"]["portalUrl"]
        r = client.get("/api/v1/tiers?environment=dev", headers={**auth(k, "ola", **OLA), "Origin": origin})
        assert r.status_code == 200 and ACAO not in r.headers and "vary" not in r.headers
        assert preflight(client, origin).status_code == 405 and ACAO not in preflight(client, origin).headers


def test_each_listed_origin_is_allowed_and_no_other(test_config, tmp_path, fresh_db, keys, monkeypatch):
    listed = ["https://portal.example.com", "http://localhost:5173", "https://xn--bcher-kva.example:8443"]
    d = with_instance(test_config, tmp_path, lambda i: i.update({"cors": {"allowedOrigins": listed}}))
    with build_world(d, keys, monkeypatch) as (client, *_):
        for origin in listed:
            assert preflight(client, origin).headers[ACAO] == origin
        assert ACAO not in preflight(client, PORTAL).headers


def test_an_empty_list_is_cors_off(test_config, tmp_path, fresh_db, keys, monkeypatch):
    d = with_instance(test_config, tmp_path, lambda i: i.update({"cors": {"allowedOrigins": []}}))
    with build_world(d, keys, monkeypatch) as (client, ctx, git, kube, validator, k):
        r = client.get("/api/v1/tiers?environment=dev", headers={**auth(k, "ola", **OLA), "Origin": PORTAL})
        assert r.status_code == 200 and ACAO not in r.headers
        assert ACAO not in preflight(client, PORTAL).headers


@pytest.mark.parametrize("value,why", [
    ("*", "wildcard"), ("https://*.example.com", "wildcard"), ("null", "opaque origin"),
    ("https://portal.example.com/", "as a browser sends it"), ("https://portal.example.com/app", "as a browser sends it"),
    ("https://portal.example.com?x=1", "as a browser sends it"), ("https://user@portal.example.com", "as a browser sends it"),
    ("http://portal.example.com", "must be https"), ("http://localhost.evil.example", "must be https"),
    ("ftp://portal.example.com", "as a browser sends it"), ("portal.example.com", "as a browser sends it"),
    ("//portal.example.com", "as a browser sends it"), ("https://Portal.example.com", "as a browser sends it"),
    ("https://portal.example.com:443", "does not send"), ("http://localhost:80", "does not send"),
    ("https://portal.example.com:0", "as a browser sends it"), ("https://portal.example.com:65536", "does not send"),
    ("https://portal.example.com:port", "as a browser sends it"), ("https://portal.example.com.", "as a browser sends it"),
    # review finding F1: values that urlsplit and a browser read in two ways
    ("https://portal.example.com\\@evil.example", "as a browser sends it"), ("https://portal .example.com", "as a browser sends it"),
    ("https://portal.example.com\nhttps://evil.example", "as a browser sends it"), ("https://b\u00fccher.example", "as a browser sends it"),
    ("https://[2001:db8::1]", "as a browser sends it"), ("https://portal.example.com#x", "as a browser sends it"),
    (5173, "is not text"), ("", "is not text"), (True, "is not text"), ({"origin": "https://p.example.com"}, "is not text"),
])
def test_a_value_that_is_not_an_exact_origin_stops_the_start(value, why):
    with pytest.raises(CorsConfigError, match=why):
        allowed_origins({"cors": {"allowedOrigins": ["https://portal.example.com", value]}})


def test_the_list_is_the_only_source_of_origins():
    assert allowed_origins({}) == [] and allowed_origins({"portalUrl": "https://portal.example.com"}) == []
    assert allowed_origins({"cors": {}}) == [] and allowed_origins({"cors": None}) == []
    assert allowed_origins({"cors": {"allowedOrigins": ["http://[::1]:5173", "http://127.0.0.1:5173", "https://a.example"] * 2}}) == [
        "http://[::1]:5173", "http://127.0.0.1:5173", "https://a.example"]
    for bad in ({"cors": []}, {"cors": {"allowedOrigins": "https://p.example.com"}}, {"cors": {"allowedOrigins": None}}):
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


# ---- review finding F3 (Codex): a cancelled request and a client that went away are not failures of the service

async def asgi_call(app, path, method="GET", incoming=None):
    import asyncio
    messages = iter(incoming or [{"type": "http.request", "body": b"", "more_body": False}])
    sent = []

    async def receive():
        try:
            return next(messages)
        except StopIteration:
            await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
             "method": method, "scheme": "https", "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "headers": [(b"origin", PORTAL.encode())],
             "server": ("api.example", 443), "client": ("127.0.0.1", 1234)}
    await asyncio.wait_for(app(scope, receive, send), timeout=3)
    return sent


def test_a_client_that_goes_away_is_not_an_unhandled_500(world, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from fastapi import Request
    import cmapi.main as main
    from cmapi.core.observability import HTTP_REQUESTS
    client, *_ = world
    events = []
    monkeypatch.setattr(main, "log", SimpleNamespace(exception=lambda *a, **kw: events.append((a, kw))))

    @client.app.post("/_review/upload", include_in_schema=False)
    async def upload(request: Request):
        await request.body()
        return {"ok": True}

    counter = HTTP_REQUESTS.labels("POST", "/_review/upload", "500")
    before = counter._value.get()
    sent = asyncio.run(asgi_call(client.app, "/_review/upload", "POST", [
        {"type": "http.request", "body": b"partial", "more_body": True}, {"type": "http.disconnect"}]))
    assert not events
    assert not any(m["type"] == "http.response.start" and m["status"] == 500 for m in sent)
    assert counter._value.get() == before


def test_a_cancelled_request_goes_on_as_a_cancellation_and_is_not_a_500(world, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import cmapi.main as main
    from cmapi.core.observability import HTTP_REQUESTS
    client, *_ = world
    events = []
    monkeypatch.setattr(main, "log", SimpleNamespace(exception=lambda *a, **kw: events.append((a, kw))))

    @client.app.get("/_review/cancel", include_in_schema=False)
    async def cancel():
        raise asyncio.CancelledError()

    counter = HTTP_REQUESTS.labels("GET", "/_review/cancel", "500")
    before = counter._value.get()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(asgi_call(client.app, "/_review/cancel"))
    assert not events
    assert counter._value.get() == before
