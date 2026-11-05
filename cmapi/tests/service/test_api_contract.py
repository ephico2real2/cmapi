"""The documentation layer's rules, enforced on the running app (docs/01, API documentation):
every /api route documented, every problem a route declares registered, the spec served."""
from __future__ import annotations

from fastapi import FastAPI

from cmapi.core.docs import PROBLEMS, check_documented


def test_openapi_lists_every_route_with_summary_permission_and_problems(world):
    client, ctx, *_ = world
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/clusters/{cluster_id}/namespaces" in paths and "/api/v1/requests/{request_id}:approve" in paths
    for path, ops in paths.items():
        if not path.startswith("/api/"):
            continue
        for method, op in ops.items():
            assert op.get("summary"), f"{method} {path} has no summary"
            assert op.get("description"), f"{method} {path} has no description"
            assert op.get("operationId"), f"{method} {path} has no operationId"
            assert "x-cmapi-plugin" in op, f"{method} {path} is not registered through DocumentedRouter"
            if op.get("x-cmapi-permission"):
                assert "401" in op["responses"] and "403" in op["responses"], f"{method} {path} lacks 401/403"
    assert client.get("/openapi.yaml").status_code == 200
    assert client.get("/docs").status_code == 200 and client.get("/redoc").status_code == 200


def test_every_declared_problem_has_a_status_and_example():
    for code, (status, detail) in PROBLEMS.items():
        assert 400 <= status < 600 and detail


def test_an_undocumented_route_stops_startup():
    from fastapi import APIRouter
    app = FastAPI()
    r = APIRouter()

    @r.get("/api/v1/oops")
    def oops():
        return {}

    app.include_router(r)
    try:
        check_documented(app)
    except RuntimeError as exc:
        assert "/api/v1/oops" in str(exc)
    else:
        raise AssertionError("an undocumented route started")


def test_version_and_health_need_no_token(world):
    client, ctx, *_ = world
    assert client.get("/healthz").json()["instance"] == "nonprod"
    assert client.get("/readyz").json()["status"] == "ok"
    v = client.get("/api/v1/version").json()
    assert v["version"] and v["component"]


def test_missing_token_is_401_with_www_authenticate(world):
    client, *_ = world
    r = client.get("/api/v1/me")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
    assert r.headers["content-type"].startswith("application/problem+json")
