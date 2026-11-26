"""#689: the rate limits of docs/01, "Operational safety": "Token buckets per caller and per team, separate for writes, :place,
:suggest and :export". Before #689 `core/ratelimit.py` held the buckets and no route called it, so no operation could answer
429 (RFC 6585, section 4: "the user has sent too many requests in a given amount of time").

Each world here takes the instance's own limits (`instance_rate_limits=True`) from instance.yaml `http.rateLimits`, and a
clock that the test moves, so no test sleeps.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from cmapi.core.docs import api_routes
from cmapi.core.observability import RATE_LIMITED
from cmapi.core.ratelimit import DEFAULTS, rate_class
from conftest import build_world
from test_custom_tier_change import URL
from test_flow import NS, OLA, auth

CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "openapi.json"
REQUESTER = dict(OLA)
VIEWER = dict(roles=["cmapi-viewer"], groups=[])


def _config(test_config: Path, tmp_path: Path, rate_limits) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    for f in test_config.iterdir():
        (d / f.name).write_text(f.read_text())
    inst = yaml.safe_load((d / "instance.yaml").read_text())
    if rate_limits is not None:
        inst["instance"]["http"] = {"rateLimits": rate_limits}
    (d / "instance.yaml").write_text(yaml.safe_dump(inst))
    return d


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def limited(request, test_config, tmp_path, fresh_db, keys, monkeypatch):
    """A world on instance.yaml http.rateLimits = the test's parameter (none: the defaults), with a clock the test moves."""
    with build_world(_config(test_config, tmp_path, getattr(request, "param", None)), keys, monkeypatch,
                     instance_rate_limits=True) as w:
        clock = Clock()
        w[1].limiter.clock = clock
        yield w, clock


def get(world, path: str, user: str = "ola", **who):
    client, *_, keys = world
    return client.get(path, headers=auth(keys, user, **(who or REQUESTER)))


def dry_run(world, body=None, user: str = "ola", **who):
    client, *_, keys = world
    return client.post(URL + "?dryRun=true", json=body if body is not None else NS,
                       headers=auth(keys, user, **(who or REQUESTER)))


def assert_rate_limited(r, retry_after: int, what: str) -> None:
    assert r.status_code == 429, r.text
    assert r.headers["content-type"] == "application/problem+json"
    problem = r.json()
    assert problem["code"] == "rate-limited" and problem["status"] == 429 and problem["title"] == "rate limited", problem
    assert problem["type"].endswith("/problems/rate-limited"), problem
    assert problem["retryAfter"] == retry_after and r.headers["Retry-After"] == str(retry_after), (problem, r.headers)
    assert what in problem["detail"], problem


# ---- a burst, then 429 with Retry-After and retryAfter

@pytest.mark.parametrize("limited", [{"read": {"perMinute": 60, "burst": 3}}], indirect=True)
def test_a_burst_over_the_limit_is_429_with_retry_after_and_another_caller_is_not_affected(limited):
    world, clock = limited
    for _ in range(3):
        assert get(world, "/api/v1/clusters").status_code == 200
    r = get(world, "/api/v1/clusters")
    # 60 a minute is one token a second: the bucket is empty, so the next token is 1 s away.
    assert_rate_limited(r, 1, "Too many read calls by this caller")
    assert r.headers["X-Request-Id"]                     # the refusal passes the request middleware like any answer
    # Another caller has a bucket of its own.
    assert get(world, "/api/v1/clusters", "amy", roles=["cmapi-approver"], groups=[]).status_code == 200
    # The same person's other token is the same caller: the bucket is the token's subject.
    client, *_, keys = world
    other_client = client.get("/api/v1/clusters", headers={"Authorization": "Bearer " + keys.token("ola", client="cmapi-cli",
                                                                                                    **REQUESTER)})
    assert other_client.status_code == 429


@pytest.mark.parametrize("limited", [{"read": {"perMinute": 60, "burst": 2}}], indirect=True)
def test_the_bucket_refills_with_time_and_a_refused_call_takes_nothing(limited):
    world, clock = limited
    assert [get(world, "/api/v1/me").status_code for _ in range(2)] == [200, 200]
    for _ in range(5):                                   # retrying at once keeps the bucket empty, and takes nothing
        assert_rate_limited(get(world, "/api/v1/me"), 1, "read")
    clock.now += 0.5
    assert_rate_limited(get(world, "/api/v1/me"), 1, "read")      # half a token: still refused, and 1 s is the whole second
    clock.now += 0.5
    assert get(world, "/api/v1/me").status_code == 200   # after Retry-After the bucket holds a token
    assert_rate_limited(get(world, "/api/v1/me"), 1, "read")
    clock.now += 600
    assert [get(world, "/api/v1/me").status_code for _ in range(3)] == [200, 200, 429]    # it refills to the burst, no more


def test_the_defaults_apply_when_instance_yaml_sets_none(limited):
    """No http.rateLimits: the reference limits, 60 reads at once for one caller."""
    world, clock = limited
    assert world[1].limiter.limits == DEFAULTS
    assert all(get(world, "/api/v1/me").status_code == 200 for _ in range(DEFAULTS["read"].burst))
    assert_rate_limited(get(world, "/api/v1/me"), 1, "read")      # 120 a minute: 0.5 s to a token, sent as 1


# ---- separate classes

@pytest.mark.parametrize("limited", [{"read": {"burst": 1}, "write": {"burst": 1}, "suggest": {"burst": 1},
                                      "export": {"burst": 1}}], indirect=True)
def test_writes_suggest_and_export_have_buckets_of_their_own(limited):
    world, clock = limited
    assert dry_run(world).status_code == 200
    assert_rate_limited(dry_run(world), 1, "Too many write calls")       # 60 a minute by default: a token each second
    assert get(world, "/api/v1/quotas:suggest?q=pay").status_code == 200
    assert_rate_limited(get(world, "/api/v1/quotas:suggest?q=pay"), 1, "Too many suggest calls")
    assert get(world, "/api/v1/quotas:export?format=csv").status_code == 200
    assert_rate_limited(get(world, "/api/v1/quotas:export?format=csv"), 15, "Too many export calls")   # 4 a minute
    assert get(world, "/api/v1/clusters").status_code == 200              # each of the others took nothing from reads
    assert_rate_limited(get(world, "/api/v1/clusters"), 1, "Too many read calls")
    # And a read takes nothing from the others: each is still empty, each with its own wait.
    assert dry_run(world).status_code == 429


def test_each_route_takes_from_the_class_that_its_method_and_template_name():
    assert rate_class("GET", "/api/v1/quotas:suggest") == "suggest"
    assert rate_class("GET", "/api/v1/quotas:export") == "export"
    assert rate_class("POST", "/api/v1/capacity:place") == "place"
    assert rate_class("POST", "/api/v1/clusters/{cluster_id}/namespaces") == "write"
    assert rate_class("POST", "/api/v1/requests/{request_id}:approve") == "write"
    assert rate_class("delete", "/api/v1/clusters/{cluster_id}/namespaces/{ns}") == "write"
    assert rate_class("HEAD", "/api/v1/clusters") == "read"
    # The template, not the URL: a request ID that ends in ":export" is a read of that request.
    assert rate_class("GET", "/api/v1/requests/{request_id}") == "read"


# ---- the team's bucket

@pytest.mark.parametrize("limited", [{"team": {"perMinute": 1, "burst": 1}}], indirect=True)
def test_a_team_bucket_counts_the_requests_opened_for_the_team_whoever_sends_them(limited):
    world, clock = limited
    client, ctx, *_, keys = world
    assert client.post(URL, json=NS, headers=auth(keys, "ola", **REQUESTER)).status_code == 202
    second = {**NS, "namespace": "payments-two-dev"}
    # A dry run opens no request: it is planned, and takes nothing from the team.
    assert dry_run(world, second, "bob").status_code == 200
    r = client.post(URL, json=second, headers=auth(keys, "bob", **REQUESTER))
    assert_rate_limited(r, 60, "Too many new requests for team payments")    # one a minute
    with ctx.db.session() as s:
        from cmapi.core.db.models import ChangeRequestRow
        assert [row.namespace for row in s.query(ChangeRequestRow).all()] == ["payments-dev"]   # nothing was recorded
    # Another team is not affected.
    other = {**NS, "namespace": "billing-dev", "labels": {**NS["labels"], "cmapi.net/team": "billing"}}
    assert client.post(URL, json=other, headers=auth(keys, "bob", **REQUESTER)).status_code == 202
    clock.now += 60
    assert client.post(URL, json=second, headers=auth(keys, "bob", **REQUESTER)).status_code == 202


@pytest.mark.parametrize("limited", [{"team": {"perMinute": 1, "burst": 1}}], indirect=True)
def test_a_replayed_idempotency_key_takes_no_team_token(limited):
    world, clock = limited
    client, *_, keys = world
    headers = auth(keys, "ola", **REQUESTER)
    first = client.post(URL, json=NS, headers=headers)
    assert first.status_code == 202
    again = client.post(URL, json=NS, headers=headers)
    assert again.status_code == 202 and again.json()["requestId"] == first.json()["requestId"]


# ---- refused before the body, the parameters and the permission are checked

@pytest.mark.parametrize("limited", [{"write": {"perMinute": 60, "burst": 1}}], indirect=True)
def test_a_caller_over_the_limit_is_refused_before_the_body_is_validated(limited, monkeypatch):
    world, clock = limited
    client, ctx, *_, keys = world
    planned = []
    real = ctx.pipeline.plan_namespace
    monkeypatch.setattr(ctx.pipeline, "plan_namespace", lambda *a, **k: planned.append(a) or real(*a, **k))
    assert dry_run(world).status_code == 200 and len(planned) == 1
    # Under the limit this body is 422 validation-failed (60,000 unknown members, the body of #683's measure).
    body = {**NS, **{f"x{i}": 1 for i in range(60_000)}}
    clock.now += 1
    assert dry_run(world, body).status_code == 422
    assert_rate_limited(dry_run(world, body), 1, "write")
    # A body that is not even a namespace, a bad query and a caller with no permission are refused the same way.
    assert_rate_limited(client.post(URL + "?dryRun=maybe", json={"namespace": 5}, headers=auth(keys, "ola", **REQUESTER)),
                        1, "write")
    clock.now += 1
    assert client.post(URL + "?dryRun=true", json=NS, headers=auth(keys, "vic", **VIEWER)).status_code == 403
    assert_rate_limited(client.post(URL + "?dryRun=true", json=NS, headers=auth(keys, "vic", **VIEWER)), 1, "write")
    assert len(planned) == 1                             # the route never ran for a refused call


# ---- the calls with no token

@pytest.mark.parametrize("limited", [{"read": {"perMinute": 1, "burst": 1}}], indirect=True)
def test_calls_with_no_token_are_not_limited_and_take_no_token(limited):
    """The design limits callers (docs/01); a call with no token has none. It is 401 from the sign-in, before the limit."""
    world, clock = limited
    client, *_, keys = world
    for _ in range(5):
        assert client.get("/api/v1/version").status_code == 200
        assert client.get("/problems/rate-limited").status_code == 200
        assert client.get("/api/v1/clusters").status_code == 401
        assert client.get("/api/v1/clusters", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert get(world, "/api/v1/clusters").status_code == 200           # the 401s took nothing from anyone
    assert_rate_limited(get(world, "/api/v1/clusters"), 60, "read")
    assert client.get("/api/v1/version").status_code == 200
    assert client.get("/openapi.json").status_code == 200


# ---- what an operator sees

@pytest.mark.parametrize("limited", [{"export": {"perMinute": 4, "burst": 1}}], indirect=True)
def test_each_refusal_is_counted_and_logged_once_for_each_run(limited, capsys):
    world, clock = limited
    before = RATE_LIMITED.labels("export")._value.get()
    assert get(world, "/api/v1/quotas:export?format=csv").status_code == 200
    capsys.readouterr()
    for _ in range(3):
        assert get(world, "/api/v1/quotas:export?format=csv").status_code == 429
    out = capsys.readouterr().out
    assert RATE_LIMITED.labels("export")._value.get() - before == 3
    lines = [json.loads(line) for line in out.splitlines() if '"event": "rate_limited"' in line]
    assert len(lines) == 1, out
    assert lines[0]["limit"] == "export" and lines[0]["caller_sub"] == "sub-ola" and lines[0]["retry_after"] == 15
    assert lines[0]["level"] == "warning" and "Bearer" not in out
    # The access log has each 429.
    assert sum('"event": "http"' in line and '"status": 429' in line for line in out.splitlines()) == 3
    clock.now += 15
    assert get(world, "/api/v1/quotas:export?format=csv").status_code == 200
    capsys.readouterr()
    assert get(world, "/api/v1/quotas:export?format=csv").status_code == 429
    assert capsys.readouterr().out.count('"event": "rate_limited"') == 1          # a new run of refusals is logged again


# ---- the document

def _limited_operations(app) -> dict[tuple[str, str], str]:
    """Each operation whose served route has the rate limit among its dependencies, with its class."""
    out = {}
    for route in api_routes(app):
        stack, calls = [route.dependant], set()
        while stack:
            dep = stack.pop()
            calls.add(getattr(dep.call, "__qualname__", ""))
            stack.extend(dep.dependencies)
        if "rate_limit.<locals>.limited" in calls:
            path = route.original_route.path_format
            for method in route.methods - {"HEAD"}:
                out[(method.lower(), path)] = rate_class(method, path)
    return out


def test_429_is_declared_on_exactly_the_limited_operations(world):
    client, *_ = world
    served = client.get("/openapi.json").json()
    committed = json.loads(CONTRACT.read_text())
    limited = _limited_operations(client.app)
    assert len(limited) > 30
    for spec in (served, committed):
        declared = {(m, p): op.get("x-cmapi-rate-limit") for p, ops in spec["paths"].items() for m, op in ops.items()
                    if "429" in op.get("responses", {})}
        assert declared == limited
        for (method, path) in declared:
            response = spec["paths"][path][method]["responses"]["429"]
            assert list(response["content"]["application/problem+json"]["examples"]) == ["rate-limited"]
            assert response["headers"]["Retry-After"]["required"] is True
        assert "429" not in spec["paths"]["/api/v1/version"]["get"]["responses"]


# ---- Retry-After on the 503s that carry retryAfter (#694)

def test_a_503_with_retry_after_sends_the_header_too(world):
    """docs/02, Problems: idp-unavailable is 503 with "Retry-After set". Before #694 only the body said retryAfter."""
    from cmapi.core.auth import Authenticator, Jwks
    from conftest import AUDIENCE, ISSUER

    client, ctx, *_, keys = world

    def keycloak_down(url):
        raise OSError("Keycloak is down")

    client.app.state.auth = Authenticator(ISSUER, AUDIENCE, Jwks(ISSUER, "https://keycloak.test/certs", fetch=keycloak_down))
    r = client.get("/api/v1/clusters", headers=auth(keys, "ola", **REQUESTER))
    assert r.status_code == 503 and r.json()["code"] == "idp-unavailable"
    assert r.json()["retryAfter"] == 30 and r.headers["Retry-After"] == "30"
    spec = client.get("/openapi.json").json()
    header = spec["paths"]["/api/v1/clusters"]["get"]["responses"]["503"]["headers"]["Retry-After"]
    assert header["schema"] == {"type": "integer", "minimum": 1}


# ---- the configuration

@pytest.mark.parametrize("limits, message", [
    ({"writes": {"burst": 1}}, "http.rateLimits has unknown classes ['writes']"),
    ({"write": {"burst": 0}}, "http.rateLimits.write.burst is a whole number of calls, 1 to 9007199254740991, not 0"),
    ({"write": {"perMinute": 0}}, "http.rateLimits.write.perMinute is a number of calls a minute"),
    ({"read": {"perMinute": True}}, "not True"),
    ({"read": 5}, "http.rateLimits.read must be a mapping"),
    ({"read": {"rate": 5}}, "http.rateLimits.read has unknown fields ['rate']"),
])
def test_a_rate_limit_that_is_not_valid_stops_the_start(test_config, tmp_path, limits, message):
    from cmapi.core.config import ConfigError, load_instance

    d = _config(test_config, tmp_path, limits)
    with pytest.raises(ConfigError) as e:
        load_instance(d, d / "metadata-keys.yaml")
    assert any(message in p for p in e.value.problems), e.value.problems


def test_the_chart_writes_the_rate_limits_and_its_schema_refuses_bad_ones(tmp_path):
    from cmapi.core.ratelimit import parse_rate_limits
    from test_body_limit_683 import helm, rendered_http

    limits = {"write": {"perMinute": 30, "burst": 10}, "export": {"perMinute": 0.5, "burst": 1}}
    written = rendered_http(tmp_path, 'instance.http=' + json.dumps({"rateLimits": limits}))
    assert written == {"rateLimits": limits}
    parsed, problems = parse_rate_limits(written["rateLimits"])
    assert problems == [] and parsed["write"].burst == 10 and parsed["export"].rate_per_minute == 0.5
    for bad in ({"writes": {"burst": 1}}, {"write": {"burst": 0}}, {"write": {"perMinute": 0}}, {"write": {"rate": 1}},
                {"write": {"burst": 1.5}}):
        r = helm(tmp_path, 'instance.http=' + json.dumps({"rateLimits": bad}))
        assert r.returncode != 0 and "/instance/http" in r.stderr, (bad, r.stderr)
