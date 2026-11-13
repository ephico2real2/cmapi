"""The KPI contract (docs/17-kpis.md): GET /api/v1/admin/kpi serves each KPI that docs/17 marks live, by its stable ID, with the
formula that docs/17 gives. #174 (BUG-45), #173 (BUG-44)."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

import cmapi.core.kpi as kpi_mod
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs

DOC = Path(__file__).resolve().parents[3] / "docs" / "17-kpis.md"
VIEWER = dict(roles=["cmapi-viewer"], groups=[])


def documented() -> dict[str, str]:
    """{KPI ID: status} from the table of docs/17."""
    rows = re.findall(r"^\| `([a-z0-9-]+)` \|.*\| `(live|built|designed)` \|$", DOC.read_text(), flags=re.M)
    assert len(rows) >= 15, "the KPI table of docs/17 was not found: its row form changed"
    return dict(rows)


def kpis(client, keys) -> dict[str, dict]:
    r = client.get("/api/v1/admin/kpi", headers=auth(keys, "opal", **OPAL))
    assert r.status_code == 200, r.text
    return {row["id"]: row for row in r.json()["kpis"]}


def create(client, keys, name: str, tier: str = "small") -> dict:
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": name, "tier": tier},
                    headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 202, r.text
    return r.json()


def test_each_live_kpi_of_docs_17_is_in_the_response_and_no_other(world):
    client, ctx, git, kube, validator, keys = world
    live = {kpi_id for kpi_id, status in documented().items() if status == "live"}
    served = kpis(client, keys)
    assert live - set(served) == set(), "docs/17 marks these KPIs live, and the API does not serve them"
    assert set(served) - live == set(), "the API serves these KPIs, and docs/17 does not mark them live"
    for row in served.values():
        assert row["unit"] in ("seconds", "ratio") and row["target"] and row["targetStatus"] == "proposed" and row["source"]
        assert row["name"] in DOC.read_text(), f"docs/17 does not have the name {row['name']}"


def test_no_request_means_not_measured_never_zero(world):
    client, ctx, git, kube, validator, keys = world
    assert {row["value"] for row in kpis(client, keys).values()} == {None}


def test_the_formulas_of_the_live_kpis(world):
    client, ctx, git, kube, validator, keys = world
    auto = create(client, keys, "payments-dev")                       # a policy approves it
    assert auto["status"] == "approved" and auto["approval"]["auto"]
    run_jobs(ctx)
    human = create(client, keys, "ledger-dev", tier="large")          # people approve it
    assert human["status"] == "pending_approval"
    assert client.post(f"/api/v1/requests/{human['requestId']}:approve", json={}, headers=auth(keys, "amy", **AMY)).status_code == 200
    run_jobs(ctx)
    with ctx.db.session() as s:
        # Known times, set by the database's clock: the auto request took 5 minutes, the approved one 10 hours with 4 hours of waiting.
        s.execute(text("UPDATE change_requests SET created_at = finished_at - interval '5 minutes' WHERE request_id = :r"), {"r": auto["requestId"]})
        s.execute(text("UPDATE change_requests SET created_at = finished_at - interval '10 hours', approved_at = finished_at - interval '6 hours' "
                       "WHERE request_id = :r"), {"r": human["requestId"]})
        statuses = dict(s.execute(text("SELECT request_id, status FROM change_requests")).all())
    assert set(statuses.values()) == {"synced"}, statuses
    k = kpis(client, keys)
    assert k["lead-time-auto-p90"]["value"] == pytest.approx(300, abs=1)
    assert k["lead-time-approved-p90"]["value"] == pytest.approx(36000, abs=1)
    assert k["approval-turnaround-p50"]["value"] == pytest.approx(14400, abs=1) and k["approval-turnaround-p90"]["value"] == pytest.approx(14400, abs=1)
    assert k["auto-approval-rate"]["value"] == 1.0                    # one request matched a policy, and the policy approved it
    assert k["change-failure-rate"]["value"] == 0.0                   # two merged, none failed
    with ctx.db.session() as s:
        s.execute(text("UPDATE change_requests SET status = 'sync_failed' WHERE request_id = :r"), {"r": human["requestId"]})
        # A request that matched a policy and that a guard stopped: it counts below the line of the auto-approval rate only.
        s.execute(text("UPDATE change_requests SET requirement = requirement || '{\"auto\": null, \"autoFallback\": \"daily-team-cap\"}'::jsonb "
                       "WHERE request_id = :r"), {"r": human["requestId"]})
    k = kpis(client, keys)
    assert k["change-failure-rate"]["value"] == 0.5
    assert k["auto-approval-rate"]["value"] == 0.5
    assert k["lead-time-approved-p90"]["value"] is None, "a request that is not synced has no lead time"


def test_the_component_figures_come_from_the_cgroup_files(tmp_path, monkeypatch):
    """The recorded sample has null figures because a Mac has no cgroup v2 files. With the kernel's files, each figure is a number."""
    monkeypatch.setattr(kpi_mod, "CGROUP", tmp_path / "absent")
    assert {v for key, v in kpi_mod.cgroup_figures().items() if key != "component"} == {None}
    (tmp_path / "memory.current").write_text("183500800\n")
    (tmp_path / "memory.max").write_text("536870912\n")
    (tmp_path / "cpu.max").write_text("50000 100000\n")
    (tmp_path / "cpu.stat").write_text("usage_usec 412600000\nuser_usec 1\nsystem_usec 1\nnr_periods 90210\nnr_throttled 12\nthrottled_usec 800000\n")
    monkeypatch.setattr(kpi_mod, "CGROUP", tmp_path)
    assert kpi_mod.cgroup_figures() == {"component": kpi_mod.COMPONENT, "memoryBytes": 183500800, "memoryLimitBytes": 536870912,
                                        "cpuUsageSeconds": 412.6, "cpuLimitCores": 0.5, "cpuPeriods": 90210,
                                        "cpuThrottledPeriods": 12, "cpuThrottledSeconds": 0.8}
    (tmp_path / "memory.max").write_text("max\n")                     # a container with no memory limit
    (tmp_path / "cpu.max").write_text("max 100000\n")
    figures = kpi_mod.cgroup_figures()
    assert figures["memoryLimitBytes"] is None and figures["cpuLimitCores"] is None and figures["memoryBytes"] == 183500800


def test_the_database_figures_are_numbers_and_the_report_needs_its_permission(world):
    client, ctx, git, kube, validator, keys = world
    body = client.get("/api/v1/admin/kpi", headers=auth(keys, "opal", **OPAL)).json()
    for name, value in body["database"].items():
        assert value is None or isinstance(value, (int, float)), f"database.{name} is {value!r}"
    assert isinstance(body["database"]["sizeBytes"], int) and body["database"]["connectionsMax"] > 0
    assert len(body["components"]) == 1 and body["components"][0]["component"] == "api"
    refused = client.get("/api/v1/admin/kpi", headers=auth(keys, "vi", **VIEWER))
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    assert client.get("/api/v1/admin/kpi").status_code == 401
