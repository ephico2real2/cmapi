"""C14: telemetry and logs; C10: facts that are hard-coded; C9: the cost of the list route."""
from __future__ import annotations

import re
import time

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, generate_latest
from sqlalchemy import event, text

from cmapi.core.observability import OPEN_REQUEST_AGE
from cmapi.worker import Worker
from test_flow import AMY, NS, OLA, auth, run_jobs


def route_labels():
    return {m.group(1) for m in re.finditer(r'cmapi_http_requests_total\{.*?route="([^"]*)"', generate_latest(REGISTRY).decode())}


def test_unmatched_paths_do_not_mint_metric_labels(world):
    client, *_ = world
    before = len(route_labels())
    for i in range(50):
        client.get(f"/scan/{i}/wp-admin.php")
    assert len(route_labels()) - before <= 1, f"{len(route_labels()) - before} new series from 50 unauthenticated 404s"


def test_an_unhandled_exception_is_counted_as_a_500(world):
    client, ctx, git, kube, validator, keys = world
    c = TestClient(client.app, raise_server_exceptions=False)

    def total():
        return sum(s.value for mf in REGISTRY.collect() if mf.name == "cmapi_http_requests" for s in mf.samples
                   if s.name.endswith("_total") and s.labels.get("status") == "500")
    before = total()
    real = git.read_folder
    git.read_folder = lambda *a, **k: 1 / 0
    r = c.get("/api/v1/clusters/CRC/namespaces/x", headers=auth(keys, "ola", **OLA))
    git.read_folder = real
    assert r.status_code == 500
    assert total() - before == 1, "CmapiHighErrorRate cannot see this 500"


def test_a_database_error_does_not_put_personal_data_in_the_exception_text(world):
    client, ctx, git, kube, validator, keys = world
    from cmapi.core.db.models import ChangeRequestRow
    from sqlalchemy.exc import DBAPIError
    try:
        with ctx.db.session() as s:
            s.add(ChangeRequestRow(request_id="r" * 100, instance="n", cluster_id="c", namespace="n", env="dev", plugin="p", action="a", status="s", plan={},
                                   plan_hash="h", requester={"email": "jane.personal@corp.example", "employeeId": "1001"}, requester_sub="s", requester_kind="user",
                                   requester_client="c", requester_username="jane"))
    except DBAPIError as exc:
        print("[measure] DB error text:", str(exc)[:600])
        assert "jane.personal@corp.example" not in str(exc), str(exc)[:400]
    else:
        pytest.fail("no error")


def test_healthz_says_degraded_when_the_database_is_down(world, monkeypatch):
    client, ctx, *_ = world
    monkeypatch.setattr(ctx.db, "ping", lambda: "OperationalError")
    body = client.get("/healthz").json()
    assert body["status"] != "ok", body
    assert client.get("/healthz").status_code == 200       # liveness stays up: restarting does not cure a database


def test_a_dead_worker_shows_on_healthz(world):
    client, ctx, git, kube, validator, keys = world
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    with ctx.db.session() as s:
        s.execute(text("update jobs set run_after = now() - interval '1 hour', created_at = now() - interval '1 hour'"))
    body = client.get("/healthz").json()
    assert body.get("oldestDueJobSeconds", 0) > 3000, body


def test_open_request_age_gauge_forgets_a_closed_state(world):
    client, ctx, git, kube, validator, keys = world
    OPEN_REQUEST_AGE.clear()
    rid = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": "large"}, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    w = Worker(ctx, "w")
    w.gauges()
    assert ("pending_approval", "dev") in {tuple(k) for k in OPEN_REQUEST_AGE._metrics}
    client.post(f"/api/v1/requests/{rid}:cancel", headers=auth(keys, "ola", **OLA))
    w.gauges()
    assert ("pending_approval", "dev") not in {tuple(k) for k in OPEN_REQUEST_AGE._metrics}, "CmapiSyncStuck-style alerts never clear"


def test_delete_facts_are_measured_not_hard_coded(world):
    """approval-rules: delete with pods > 20 or pvcs > 10 adds an approver; plan_delete passes pods=0, pvcs=0."""
    client, ctx, git, kube, validator, keys = world
    h = auth(keys, "ola", **OLA)
    client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
    run_jobs(ctx)
    for i in range(25):
        kube.objects[("Pod", "payments-dev", f"p{i}")] = {"kind": "Pod", "metadata": {"name": f"p{i}", "namespace": "payments-dev"}}
    etag = client.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h).json()["etag"]
    r = client.delete("/api/v1/clusters/CRC/namespaces/payments-dev", headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 202, r.text
    slots = r.json()["approval"]["slots"]
    assert sum(s["count"] for s in slots) == 2, f"25 pods, slots {slots}"


def test_list_requests_does_not_query_per_row(world, capsys):
    client, ctx, git, kube, validator, keys = world
    with ctx.db.session() as s:
        pass
    rid = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "tier": "large"}, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    with ctx.db.session() as s:
        s.execute(text("""insert into change_requests(request_id,instance,cluster_id,namespace,env,plugin,action,status,reason,justification,team,plan,plan_hash,base_sha,requirement,requester,requester_sub,requester_kind,requester_client,requester_username,finished_at)
           select 'req-seed-'||g,instance,cluster_id,'ns-'||g,env,plugin,action,'synced',reason,justification,team,plan,plan_hash,base_sha,requirement,requester,requester_sub,requester_kind,requester_client,requester_username,now()
           from change_requests, generate_series(1,1000) g where request_id=:r"""), {"r": rid})
    n = {"v": 0}

    def count(conn, cur, stmt, params, ctxx, many):
        n["v"] += 1
    event.listen(ctx.db.engine, "before_cursor_execute", count)
    t0 = time.perf_counter()
    r = client.get("/api/v1/requests?limit=25", headers=auth(keys, "ola", **OLA))
    took = time.perf_counter() - t0
    event.remove(ctx.db.engine, "before_cursor_execute", count)
    with capsys.disabled():
        print(f"\n[measure] GET /requests?limit=25 over 1000 rows: {n['v']} SQL statements, {took*1000:.0f} ms, {len(r.json()['items'])} items, total {r.json()['page']['total']}")
    assert r.status_code == 200 and n["v"] < 100, n["v"]


def test_transient_validator_failure_keeps_the_pr_open_and_retries(world):
    from cmapi.core.validate import ValidatorUnavailable
    client, ctx, git, kube, validator, keys = world
    rid = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA)).json()["requestId"]
    from test_review_d_delivery import run_until
    assert run_until(ctx, "pr_checks") == "pr_checks"
    real = validator.validate
    validator.validate = lambda *a, **k: (_ for _ in ()).throw(ValidatorUnavailable("schema download failed"))
    w = Worker(ctx, "w")
    w.run_one()
    assert git.prs[1]["state"] == "open"
    with ctx.db.session() as s:
        assert s.execute(text("select status from change_requests where request_id=:r"), {"r": rid}).scalar() == "pr_open"
    validator.validate = real


def test_cli_validator_treats_a_schema_download_failure_as_unavailable(tmp_path, monkeypatch):
    """The real output of kubeconform 0.6.7 with no route to raw.githubusercontent.com, measured in the image."""
    import json, os, stat
    from cmapi.core.validate import CliValidator, ValidatorUnavailable
    out = {"resources": [{"filename": "x", "kind": "Namespace", "name": "a", "version": "v1", "status": "statusError",
                          "msg": "failed downloading schema at https://raw.githubusercontent.com/...: dial tcp: lookup raw.githubusercontent.com"}],
           "summary": {"valid": 0, "invalid": 0, "errors": 1, "skipped": 0}}
    b = tmp_path / "kubeconform"
    b.write_text("#!/bin/sh\ncat <<'J'\n" + json.dumps(out) + "\nJ\nexit 1\n")
    b.chmod(b.stat().st_mode | stat.S_IEXEC)
    v = CliValidator(tmp_path / "none", kubeconform=str(b), kyverno=str(b))
    with pytest.raises(ValidatorUnavailable):
        v.validate({"a/namespace.yaml": "kind: Namespace\n"}, "CRC", "dev")
