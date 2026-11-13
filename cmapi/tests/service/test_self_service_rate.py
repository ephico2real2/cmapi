"""#171 (BUG-42): the self-service rate of docs/17. An approval stores the approving group that it counted for, and the rate is
the synced requests with no approval that counted for the platform group, divided by the synced requests."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from cmapi.core.approvals import ApprovalLedger, Requirement, Slot
from cmapi.core.identity.claims import Identity
from conftest import build_world
from test_flow import AMY, NS, OLA, OPAL, auth, run_jobs

TEAM_LEAD = dict(roles=["cmapi-approver"], groups=["/cmapi/app-cmapi-rbac-approver-payments"])


def person(name: str, *groups: str) -> Identity:
    return Identity(sub=f"sub-{name}", username=name, kind="user", client_id="cmapi-portal", roles=frozenset({"cmapi-approver"}),
                    groups=frozenset(f"/cmapi/app-cmapi-rbac-{g}" for g in groups))


def test_the_ledger_says_which_group_each_approval_counts_for_and_a_later_approval_can_move_an_earlier_one():
    req = Requirement("dev-change", (Slot("approver-payments", 1, "dev change"), Slot("approver-platform", 1, "quota over 100%")),
                      self_approval=False, timeout_hours=24, reasons=())
    ledger = ApprovalLedger(req, requester_sub="sub-ola")
    assert ledger.approve(person("both", "approver-payments", "approver-platform")) is False
    assert ledger.counted_for() == {"sub-both": "approver-payments"}
    # Only the team seat fits the second person, so the first person moves to the platform seat.
    assert ledger.approve(person("lead", "approver-payments")) is True
    assert ledger.counted_for() == {"sub-both": "approver-platform", "sub-lead": "approver-payments"}


def _team_config(test_config: Path, tmp_path: Path) -> Path:
    """The suite's configuration with a team group as dev's approving group. The platform group stays defaults.group."""
    d = tmp_path / "config"
    d.mkdir()
    for f in test_config.iterdir():
        (d / f.name).write_text(f.read_text())
    rules = yaml.safe_load((d / "approval-rules.yaml").read_text())
    assert rules["defaults"]["group"] == "approver-platform"
    rules["environments"]["dev"]["group"] = "approver-payments"
    (d / "approval-rules.yaml").write_text(yaml.safe_dump(rules))
    return d


def _create(client, keys, name: str) -> dict:
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**NS, "namespace": name, "tier": "large"},
                    headers={"Authorization": f"Bearer {keys.token('ola', **OLA)}", "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 202 and r.json()["status"] == "pending_approval", r.text
    return r.json()


def _approve(client, keys, request_id: str, name: str, who: dict) -> None:
    r = client.post(f"/api/v1/requests/{request_id}:approve", json={}, headers=auth(keys, name, **who))
    assert r.status_code == 200, r.text


def _rate(client, keys) -> dict:
    body = client.get("/api/v1/admin/kpi", headers=auth(keys, "opal", **OPAL)).json()
    return next(row for row in body["kpis"] if row["id"] == "self-service-rate")


def test_the_self_service_rate_is_the_synced_requests_that_needed_no_platform_approval(test_config, tmp_path, fresh_db, keys, monkeypatch):
    with build_world(_team_config(test_config, tmp_path), keys, monkeypatch) as (client, ctx, *_):
        assert _rate(client, keys)["value"] is None, "no synced request: not measured, never 0"
        team = _create(client, keys, "ledger-dev")                 # dev create: 1 from approver-payments
        assert team["approval"]["remaining"] == [{"group": "approver-payments", "needed": 1}]
        _approve(client, keys, team["requestId"], "tess", TEAM_LEAD)
        run_jobs(ctx)
        platform = _create(client, keys, "critical-ledger")        # the pattern critical-*: 2 from approver-platform
        assert platform["approval"]["remaining"] == [{"group": "approver-platform", "needed": 2}]
        _approve(client, keys, platform["requestId"], "amy", AMY)
        _approve(client, keys, platform["requestId"], "pat", AMY)
        run_jobs(ctx)
        with ctx.db.session() as s:
            assert set(s.execute(text("SELECT status FROM change_requests")).scalars()) == {"synced"}
            stored = s.execute(text("SELECT request_id, username, counted_for FROM approvals ORDER BY id")).all()
        assert [tuple(r) for r in stored] == [(team["requestId"], "tess", "approver-payments"),
                                             (platform["requestId"], "amy", "approver-platform"),
                                             (platform["requestId"], "pat", "approver-platform")]
        row = _rate(client, keys)
        assert row["value"] == 0.5 and row["unit"] == "ratio" and "approver-platform" in row["source"]

        # An approval from before the column has no stored slot: its request is in neither part of the rate.
        with ctx.db.session() as s:
            s.execute(text("UPDATE approvals SET counted_for = NULL WHERE request_id = :r"), {"r": platform["requestId"]})
        assert _rate(client, keys)["value"] == 1.0
        with ctx.db.session() as s:
            s.execute(text("UPDATE approvals SET counted_for = NULL"))
        assert _rate(client, keys)["value"] is None
