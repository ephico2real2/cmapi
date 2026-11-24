"""#613: the local reference app (examples/local/app.py) refuses `dryRun` on a write that has no dry run.

FastAPI ignores a query parameter that a route does not declare, so before the fix `:cancel?dryRun=true` cancelled and
`admin/prune:confirm?dryRun=true` deleted the namespace on the cluster. As the service does after #606, and as the
Kubernetes API server does on a call that cannot honour a dry run (apiserver, endpoints/handlers/rest.go: `isDryRun` is
`len(url.Query()["dryRun"]) != 0`, then `errors.NewBadRequest("dryRun is not supported")`), any `dryRun` is 400
`dry-run-not-supported`, whatever its value. The app's create and change keep their previews.
"""
from __future__ import annotations

import importlib.util
import sys
from unittest.mock import Mock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from conftest import person

OPERATOR = person("opal", roles=["cmapi-operator"])
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture
def local(ex, monkeypatch):
    """The local app with its Git and cluster replaced: nothing here reaches a repository or a cluster. Every call is
    made as an operator."""
    monkeypatch.syspath_prepend(str(ex / "local"))
    import adapters
    monkeypatch.setattr(adapters, "LocalGit", Mock())
    monkeypatch.setattr(adapters, "KubeCluster", Mock())
    spec = importlib.util.spec_from_file_location("local_app_613", ex / "local" / "app.py")
    app = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, app)    # its dataclasses look up their module while it loads
    spec.loader.exec_module(app)
    app.app.dependency_overrides[app.caller] = lambda: OPERATOR
    return app


def refused(r) -> None:
    assert r.status_code == 400, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "dry-run-not-supported", r.text


def test_a_cancel_with_dry_run_is_refused_before_the_request_is_looked_up(local):
    client = TestClient(local.app)
    for value in ("false", "true", "All", ""):
        refused(client.post(f"/api/v1/requests/missing:cancel?dryRun={value}"))
    r = client.post("/api/v1/requests/missing:cancel")
    assert (r.status_code, r.json()["code"]) == (404, "object-not-found"), r.text
    # Sign-in comes first, as in the service (#618 review): a call without a token is 401, with or without dryRun.
    local.app.dependency_overrides.clear()
    r = client.post("/api/v1/requests/missing:cancel?dryRun=true")
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated"), r.text
    assert client.post("/api/v1/requests/missing:cancel").status_code == 401


def test_a_prune_confirm_with_dry_run_deletes_nothing(local):
    """A delete that is awaiting its prune: `?dryRun=true` leaves the namespace and the request as they are."""
    r = local.Req(id="req-prune", cluster_id="OCP_LOCAL", namespace="payments-dev", env="dev", action="delete",
                  plugin="namespaces", state=local.S.AWAITING_PRUNE, spec=None, files={}, hash="h", requirement=None,
                  ledger=None, requester={"requester": {"username": "ola"}}, team=None)
    local.REQS[r.id] = r
    try:
        client = TestClient(local.app)
        refused(client.post("/api/v1/admin/prune:confirm?dryRun=true", json={"namespace": "payments-dev"}))
        local.CLUSTER.delete_namespace.assert_not_called()
        assert r.state == local.S.AWAITING_PRUNE
        # Without dryRun the call is what it was.
        assert client.post("/api/v1/admin/prune:confirm", json={"namespace": "payments-dev"}).status_code == 200
        local.CLUSTER.delete_namespace.assert_called_once_with("payments-dev")
    finally:
        local.REQS.pop(r.id, None)


def test_every_write_of_the_local_app_previews_or_refuses_dry_run(local):
    """Each write route either declares `dryRun` (a preview: create and change) or refuses it, so a new write cannot
    forget the guard silently."""
    previews, guarded = [], []
    for route in local.app.routes:
        if not isinstance(route, APIRoute) or not route.methods & WRITES:
            continue
        if "dryRun" in {p.alias for p in route.dependant.query_params}:
            previews.append(route.path)
            continue
        assert local.refuse_dry_run in [d.call for d in route.dependant.dependencies], route.path
        guarded.append(route.path)
    assert sorted(previews) == ["/api/v1/clusters/{cluster_id}/namespaces", "/api/v1/clusters/{cluster_id}/namespaces/{ns}"]
    assert len(guarded) == 6, guarded


def test_the_previews_still_answer_dry_run(local, monkeypatch):
    """The create's preview is the plan, with no request recorded."""
    plan = {"changes": {}, "files": {}}
    monkeypatch.setattr(local, "plan_namespace", lambda *a, **k: plan)
    monkeypatch.setattr(local, "plan_view", lambda p: {"preview": p is plan})
    r = TestClient(local.app).post("/api/v1/clusters/OCP_LOCAL/namespaces?dryRun=true", json={"namespace": "x"})
    assert (r.status_code, r.json()) == (200, {"preview": True}), r.text
    assert not local.REQS


AUTH_CASES = [
    ("POST", "/api/v1/clusters/OCP_LOCAL/namespaces/x/expiration:extend", {"days": 1}),
    ("DELETE", "/api/v1/clusters/OCP_LOCAL/namespaces/x", None),
    ("POST", "/api/v1/requests/missing:approve", {}),
    ("POST", "/api/v1/requests/missing:reject", {"comment": "no"}),
    ("POST", "/api/v1/requests/missing:cancel", None),
    ("POST", "/api/v1/admin/prune:confirm", {"namespace": "x"}),
]


@pytest.mark.parametrize("method,url,body", AUTH_CASES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer broken"}])
def test_sign_in_comes_before_the_dry_run_guard(local, monkeypatch, method, url, body, headers):
    """#618 review (Codex gpt-6.1-sol): without a valid token each guarded write is 401, not 400, and deletes nothing."""
    import jwt
    from unittest.mock import Mock

    local.app.dependency_overrides.clear()
    monkeypatch.setattr(local.JWKS, "get_signing_key_from_jwt", Mock(side_effect=jwt.InvalidTokenError("invalid test token")))
    r = TestClient(local.app).request(method, url + "?dryRun=true", json=body, headers=headers)
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated"), r.text
    local.CLUSTER.delete_namespace.assert_not_called()
