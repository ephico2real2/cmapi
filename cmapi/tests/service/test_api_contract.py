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
    # /docs and /redoc need the image's bundles, and no longer fall back to a CDN (#127): test_api_docs.py covers both cases.


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


def test_every_problem_code_the_code_raises_is_registered():
    """A code raised with no entry in PROBLEMS cannot be declared by a route, so no client can know it (#155)."""
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "src" / "cmapi"
    raised: dict[str, str] = {}
    for f in src.rglob("*.py"):
        text = f.read_text()
        for m in re.finditer(r'Problem(?:\.[a-z_]+)?\(\s*(?:\d{3},\s*)?"([a-z][a-z0-9-]+)"', text):
            raised.setdefault(m.group(1), f.name)
        for m in re.finditer(r'code="([a-z][a-z0-9-]+)"', text):
            raised.setdefault(m.group(1), f.name)
    assert len(raised) > 30, "the scan found too few codes to mean anything"
    assert {c: f for c, f in raised.items() if c not in PROBLEMS} == {}


def test_a_request_that_fastapi_refuses_is_an_rfc_9457_problem_like_every_other_refusal(world):
    """#164: a wrong type in a parameter or a body was FastAPI's own 422 body ({"detail": [...]}), not a problem, and the
    document described that other shape for 16 operations."""
    client, ctx, _, _, _, keys = world
    h = {"Authorization": f"Bearer {keys.token('ola', roles=['cmapi-requester'], groups=[])}"}
    for r in (client.get("/api/v1/requests?limit=abc", headers=h),
              client.post("/api/v1/clusters/CRC/namespaces", json={"namespace": 5, "nope": 1}, headers={**h, "Idempotency-Key": "k"}),
              client.get("/api/v1/directory/users?q=a", headers=h)):
        assert r.status_code == 422 and r.headers["content-type"] == "application/problem+json", r.text
        body = r.json()
        assert body["code"] == "validation-failed" and body["status"] == 422 and isinstance(body["detail"], str)
        assert body["errors"] and all({"field", "message", "code"} <= set(e) for e in body["errors"]), body
    spec = client.get("/openapi.json").json()
    assert "HTTPValidationError" not in spec["components"]["schemas"] and "ValidationError" not in spec["components"]["schemas"]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            r422 = op["responses"].get("422")
            if op.get("parameters") or op.get("requestBody"):
                assert r422 and "validation-failed" in r422["content"]["application/problem+json"]["examples"], f"{method} {path}"
                assert "application/json" not in r422["content"], f"{method} {path}"
