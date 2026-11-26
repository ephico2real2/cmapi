"""Story #22, criterion 2 (#310): "Existing-namespace changes use live 14-day usage; insufficient data is explicit".

GET /api/v1/quotas carries each namespace's usage verdict from the latest daily sweep, its attention counts and its severity;
the dry run of a quota change carries the namespace's live 14-day usage and the approval facts it gives. Thanos is
usage_fake.FakeMetrics (tests/core), which answers the real PromQL from figures; the sweep, the storage and the routes are
the real ones."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

import conftest                                                           # noqa: E402
from cmapi.capacity.sweep import VerdictRepo, run_sweep                     # noqa: E402
from cmapi.capacity.usage import EXPECTED_STEPS, PromUsage                # noqa: E402
from cmapi.core.db import Database                                         # noqa: E402
from cmapi.core.db.models import AnalysisSweepRow, NamespaceVerdictRow    # noqa: E402
from cmapi.core.db.repo import JobRepo                                    # noqa: E402
from test_flow import NS, OLA, auth, run_jobs                             # noqa: E402
from usage_fake import GiB, Fake, FakeMetrics                             # noqa: E402

ONE = f"/api/v1/clusters/CRC/namespaces/{NS['namespace']}"
NOW = datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)


def managed(kube, name: str, cpu: tuple[str, str], memory: tuple[str, str]) -> None:
    """A managed namespace on the fake cluster, with its ResourceQuota's used and hard (#310: the sweep's quota comes from
    the API)."""
    kube.objects[("Namespace", "", name)] = {"kind": "Namespace", "metadata": {"name": name, "labels": {
        "cmapi.net/managed": "true", "cmapi.net/env": "dev", "cmapi.net/team": "payments"}}}
    kube.objects[("ResourceQuota", name, f"{name}-quota")] = {
        "kind": "ResourceQuota", "metadata": {"name": f"{name}-quota", "namespace": name, "labels": {"cmapi.net/managed": "true"}},
        "spec": {"hard": {"requests.cpu": cpu[1], "requests.memory": memory[1], "pods": "50"}},
        "status": {"used": {"requests.cpu": cpu[0], "requests.memory": memory[0], "pods": "5"}}}


def relist(ctx) -> None:
    cache = ctx.registry.cache("CRC")
    cache._list("Namespace")
    cache._list("ResourceQuota")


CALM = {"cpu": (0.5, 0.05, 0.05, 0.08), "memory": (0.5, 0.0, 0.6)}
# Six namespaces, one of each verdict (dev: quota-oversized below 0.30, requests-oversized below 0.20, quota-tight at 0.95).
FLEET = {
    "alpha-tight": Fake(cpu=(3.5, 3.4, 3.6, 3.9, None), memory=(6 * GiB, 6 * GiB, 6 * GiB, 7 * GiB, None),
                        quota={"cpu": (0.97, 0.40, 1.0), "memory": (0.5, 0.0, 0.6)}),
    "bravo-idle": Fake(cpu=(0.01, 0.01, 0.02, 0.03, 0.02), memory=(64 * 2**20, 64 * 2**20, 70 * 2**20, 80 * 2**20, 70 * 2**20),
                       quota={"cpu": (0.5, 0.0, 0.6), "memory": (0.5, 0.0, 0.6)}),
    "charlie-big": Fake(cpu=(0.5, 0.5, 0.6, 0.7, None), memory=(GiB, GiB, GiB, GiB, None),
                        quota={"cpu": (0.10, 0.0, 0.12), "memory": (0.10, 0.0, 0.12)}),
    "delta-fat": Fake(cpu=(0.2, 0.2, 0.3, 0.4, None), memory=(4 * GiB, 4 * GiB, 4 * GiB, 4 * GiB, None),
                      quota={"cpu": (0.6, 0.0, 0.7), "memory": (0.5, 0.0, 0.6)}),
    "echo-fine": Fake(cpu=(2.0, 2.0, 2.5, 3.0, None), memory=(6 * GiB, 6 * GiB, 6 * GiB, 7 * GiB, None),
                      quota={"cpu": (0.5, 0.0, 0.6), "memory": (0.5, 0.0, 0.6)}),
    "foxtrot-new": Fake(steps=EXPECTED_STEPS * 0.3, quota={"cpu": (0.5, 0.0, 0.6), "memory": (0.5, 0.0, 0.6)}),
}
QUOTA_NOW = {"alpha-tight": (("7.8", "8"), ("8Gi", "16Gi")), "bravo-idle": (("1", "8"), ("2Gi", "16Gi")),
             "charlie-big": (("0.8", "8"), ("1600Mi", "16Gi")), "delta-fat": (("4.8", "8"), ("8Gi", "16Gi")),
             "echo-fine": (("4", "8"), ("8Gi", "16Gi")), "foxtrot-new": (("4", "8"), ("8Gi", "16Gi"))}


@pytest.fixture
def fleet(world):
    client, ctx, git, kube, validator, keys = world
    for name, (cpu, memory) in QUOTA_NOW.items():
        managed(kube, name, cpu, memory)
    relist(ctx)
    metrics = FakeMetrics(dict(FLEET))
    ctx.usage = ctx.pipeline.usage = PromUsage(metrics)
    return metrics


def quotas(world, query: str = "") -> dict:
    client, ctx, git, kube, validator, keys = world
    r = client.get(f"/api/v1/quotas{query}", headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    return r.json()


def sweep(world) -> list[str]:
    client, ctx, git, kube, validator, keys = world
    with ctx.db.session() as s:
        JobRepo(s).enqueue("usage_sweep")
    return run_jobs(ctx)


def test_with_no_usage_source_every_row_says_insufficient_data_and_why(world):
    client, ctx, git, kube, validator, keys = world
    managed(kube, "payments-dev", ("1", "8"), ("1Gi", "16Gi"))
    relist(ctx)
    assert ctx.usage.configured is False, "the test instance's capacity.yaml names no usage source"
    assert sweep(world) == ["usage_sweep"]
    with ctx.db.session() as s:
        assert s.query(AnalysisSweepRow).count() == 0, "with no source the sweep reads and writes nothing"
    page = quotas(world)
    row = page["items"][0]
    assert (row["verdict"], row["verdictKind"], row["verdictResources"], row["verdictDay"]) == ("insufficient-data", "info", [], None)
    assert row["verdictReason"].startswith("No usage source is configured on this instance")
    assert page["facets"] == {"quota-tight": 0, "near-limit": 0, "oversized": 0, "idle": 0, "tier-outdated": 0,
                              "open-request": 0, "needs-attention": 0}


def test_the_daily_sweep_stores_each_verdict_and_the_list_joins_it(world, fleet):
    assert sweep(world) == ["usage_sweep"]
    page = quotas(world)
    got = {r["name"]: (r["verdict"], r["verdictKind"], r["verdictResources"]) for r in page["items"]}
    assert got == {"alpha-tight": ("quota-tight", "risk", ["cpu"]), "bravo-idle": ("idle", "waste", ["cpu", "memory"]),
                   "charlie-big": ("quota-oversized", "waste", ["cpu", "memory"]),
                   "delta-fat": ("requests-oversized", "waste", ["cpu"]), "echo-fine": ("right-sized", "ok", ["cpu", "memory"]),
                   "foxtrot-new": ("insufficient-data", "info", ["cpu", "memory"])}
    rows = {r["name"]: r for r in page["items"]}
    assert all(r["verdictDay"] == datetime.now(timezone.utc).date().isoformat() for r in page["items"])
    assert "below dev's floor of 20%" in rows["delta-fat"]["verdictReason"]
    assert rows["foxtrot-new"]["verdictReason"] == ("Pods were seen in 30% of the 14-day window's 4,032 five-minute steps; "
                                                    "80% are needed.")
    # alpha-tight is also near its limit (7.8 of 8 cores); the counts are over the filters, each a state of its own.
    assert page["facets"] == {"quota-tight": 1, "near-limit": 1, "oversized": 2, "idle": 1, "tier-outdated": 0,
                              "open-request": 0, "needs-attention": 4}
    # One instant per cluster: every query of the sweep was evaluated at the same time.
    assert len({at for _, _, at in fleet.calls}) == 1


def test_the_attention_states_and_the_verdict_filter_list_their_rows(world, fleet):
    sweep(world)
    names = lambda q: [r["name"] for r in quotas(world, q)["items"]]     # noqa: E731
    assert names("?state=quota-tight") == ["alpha-tight"]
    assert names("?state=oversized") == ["charlie-big", "delta-fat"]
    assert names("?state=idle") == ["bravo-idle"]
    assert names("?state=needs-attention") == ["alpha-tight", "bravo-idle", "charlie-big", "delta-fat"]
    assert names("?verdict=right-sized") == ["echo-fine"]
    assert names("?verdict=insufficient-data") == ["foxtrot-new"]
    # Severity: quota-tight 3, then the level-1 verdicts (idle and oversized), then the rest, each level by name.
    assert names("?sort=severity") == ["alpha-tight", "bravo-idle", "charlie-big", "delta-fat", "echo-fine", "foxtrot-new"]
    client, ctx, git, kube, validator, keys = world
    bad = client.get("/api/v1/quotas?verdict=fine", headers=auth(keys, "ola", **OLA))
    assert bad.status_code == 422 and bad.json()["code"] == "validation-failed" and "quota-tight" in bad.json()["detail"]
    csv = client.get("/api/v1/quotas:export?state=oversized", headers=auth(keys, "ola", **OLA)).text.splitlines()
    assert csv[0].endswith(",verdict") and [line.rsplit(",", 1)[1] for line in csv[1:]] == ["quota-oversized", "requests-oversized"]


def test_a_failed_sweep_gives_insufficient_data_for_the_day_and_old_verdicts_expire(world, fleet):
    client, ctx, git, kube, validator, keys = world
    served = ctx.registry.connected()
    with ctx.db.session() as s:
        run_sweep(served, ctx.usage, ctx.analysis, s, now=NOW)
    fleet.fail = "the Thanos Querier warned: store gateway unavailable"
    with ctx.db.session() as s:
        run_sweep(served, ctx.usage, ctx.analysis, s, now=NOW + timedelta(days=1))
    page = quotas(world)
    assert {r["verdict"] for r in page["items"]} == {"insufficient-data"}, "a failed query is never a zero, nor yesterday's"
    assert all(r["verdictDay"] == "2026-11-26" for r in page["items"])
    assert "could not read Thanos" in page["items"][0]["verdictReason"] and "store gateway" in page["items"][0]["verdictReason"]
    with ctx.db.session() as s:
        assert {(r.day.isoformat(), r.status) for r in s.query(AnalysisSweepRow)} == {("2026-11-25", "complete"),
                                                                                       ("2026-11-26", "failed")}
        # 13 months later the retention removes both days.
        fleet.fail = None
        run_sweep(served, ctx.usage, ctx.analysis, s, now=NOW + timedelta(days=397))
        VerdictRepo(s).prune((NOW + timedelta(days=397)).date())
        assert {r.day.isoformat() for r in s.query(NamespaceVerdictRow)} == {(NOW + timedelta(days=397)).date().isoformat()}
        assert s.query(AnalysisSweepRow).count() == 1


def test_a_missed_sweep_leaves_the_last_verdicts_with_their_day(world, fleet):
    client, ctx, git, kube, validator, keys = world
    with ctx.db.session() as s:
        run_sweep(ctx.registry.connected(), ctx.usage, ctx.analysis, s, now=NOW)
        assert len(VerdictRepo(s).latest()) == 6
    rows = {r["name"]: r for r in quotas(world)["items"]}
    assert rows["alpha-tight"]["verdict"] == "quota-tight" and rows["alpha-tight"]["verdictDay"] == "2026-11-25"


# ---- the plan of a quota change

def synced_namespace(world) -> str:
    """payments-dev, created (auto-approved, tier small: 8 cores, 16Gi) and synced; returns its etag."""
    client, ctx, git, kube, validator, keys = world
    r = client.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 202 and r.json()["status"] == "approved", r.text
    run_jobs(ctx)
    return client.get(ONE, headers=auth(keys, "ola", **OLA)).json()["etag"]


def plan(world, etag: str, body: dict):
    client, ctx, git, kube, validator, keys = world
    r = client.patch(ONE + "?dryRun=true", json=body, headers={**auth(keys, "ola", **OLA), "If-Match": etag})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_quota_change_plan_carries_the_live_14_day_usage(world):
    client, ctx, git, kube, validator, keys = world
    etag = synced_namespace(world)
    metrics = FakeMetrics({"payments-dev": Fake(cpu=(1.2, 1.1, 1.8, 2.0, None), memory=(3 * GiB, 3 * GiB, 4 * GiB, 5 * GiB, None))})
    ctx.pipeline.usage = PromUsage(metrics)
    body = plan(world, etag, {"tier": "medium"})
    u = body["usage"]
    assert (u["state"], u["reason"], u["window"], u["coverage"]) == ("ok", None, "14d", 1.0)
    assert u["cpu"] == {"now": 1200, "avg7d": 1100, "p95": 1800, "peak": 2000, "quota": 8000, "newQuota": 16000, "newOverPeak": 8.0}
    assert u["memory"] == {"now": 3 * GiB, "avg7d": 3 * GiB, "p95": 4 * GiB, "peak": 5 * GiB, "quota": 16 * GiB,
                           "newQuota": 32 * GiB, "newOverPeak": 6.4}
    # 16 cores is 8x the 14-day peak: approval-rules.yaml's `requestToPeakRatio > 3` adds an approval (dev's change needs none).
    assert {"group": "approver-platform", "count": 1, "reason": "Possible over-provisioning"} in body["approval"]["slots"]
    assert all('namespace="payments-dev"' in q for _, q, _ in metrics.calls), "one namespace, never the fleet"


def test_a_plan_with_no_usage_source_says_insufficient_data_and_adds_nothing(world):
    etag = synced_namespace(world)
    body = plan(world, etag, {"tier": "medium"})
    u = body["usage"]
    assert u["state"] == "insufficient-data" and u["reason"].startswith("No usage source is configured")
    assert (u["cpu"]["peak"], u["cpu"]["quota"], u["cpu"]["newQuota"], u["cpu"]["newOverPeak"]) == (None, 8000, 16000, None)
    assert body["approval"]["slots"] == [] and body["approval"]["auto"] == "none-required"


def test_a_plan_whose_usage_read_fails_needs_a_platform_approval(world):
    client, ctx, git, kube, validator, keys = world
    etag = synced_namespace(world)
    metrics = FakeMetrics({"payments-dev": Fake()})
    metrics.fail = "ReadTimeout: timed out"
    ctx.pipeline.usage = PromUsage(metrics)
    body = plan(world, etag, {"tier": "medium"})
    assert body["usage"]["state"] == "unavailable" and "timed out" in body["usage"]["reason"]
    # docs/01: "If Thanos cannot answer within 10 seconds, the plan carries usage: unavailable and the change needs a platform
    # approval instead of failing."
    assert body["approval"]["slots"] == [{"group": "approver-platform", "count": 1, "reason": "Live usage unavailable"}]


def test_a_change_that_leaves_the_quota_and_a_create_read_no_usage(world):
    client, ctx, git, kube, validator, keys = world
    metrics = FakeMetrics({"payments-dev": Fake()})
    ctx.pipeline.usage = PromUsage(metrics)
    created = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=NS, headers=auth(keys, "ola", **OLA)).json()
    assert created["usage"] is None
    etag = synced_namespace(world)
    body = plan(world, etag, {"labels": {"cmapi.net/cost-center": "cc-9999"}})
    assert body["usage"] is None
    assert metrics.calls == [], "Thanos on onboarding: never queried; and only a change of the quota reads it"


def test_usage_follows_the_change_to_the_stored_quota(test_config, keys, monkeypatch):
    """An unchanged tier name can still change a hard limit when the catalog moved."""
    import yaml
    from conftest import build_world
    from cmapi.core.identity.claims import Identity
    from cmapi.core.pipeline import folder_etag
    from cmapi.core.ports import CapacityResult

    with build_world(test_config, keys, monkeypatch) as (_, ctx, git, *_):
        who = Identity("sub-ola", "ola", "user", "cmapi-portal", "ola@example.test", employee_id="E1",
                       roles=frozenset(OLA["roles"]), groups=frozenset(OLA["groups"]))
        monkeypatch.setattr(ctx.pipeline, "auto_paused", lambda session: False)
        monkeypatch.setattr(ctx.pipeline.capacity, "check", lambda *args: CapacityResult("fits", True, None, {}))
        created = ctx.pipeline.plan_namespace(who, "CRC", NS, action="create")
        files = dict(created.files)
        path = next(p for p, value in files.items() if yaml.safe_load(value)["kind"] == "ResourceQuota")
        quota = yaml.safe_load(files[path])
        quota["spec"]["hard"]["pods"] = "1"
        files[path] = yaml.safe_dump(quota)
        git.branches["main"].update(files)
        metrics = FakeMetrics()
        metrics.fail = "offline"
        ctx.pipeline.usage = PromUsage(metrics)
        changed = ctx.pipeline.plan_namespace(who, "CRC", {"namespace": NS["namespace"], "labels": {"cmapi.net/cost-center": "cc-9999"}},
                                              action="update", if_match=folder_etag(files))
        assert changed.usage and changed.usage["state"] == "unavailable"
        assert any(slot.group == "approver-platform" for slot in changed.requirement.slots)


def test_two_workers_run_one_sweep_a_day(world, fleet):
    """Two worker pods: each seeds the recurring jobs at start, then both claim at once. The pending-job index keeps one
    usage_sweep, FOR UPDATE SKIP LOCKED gives it to one worker, and the day has one sweep row per cluster (reviewer 2)."""
    import threading
    from cmapi.core.db.models import JobRow
    from cmapi.worker import Worker
    client, ctx, git, kube, validator, keys = world
    slow = fleet.query

    def query(*args, **kwargs):                 # long enough that the second claim comes while the first sweep runs
        time.sleep(0.05)
        return slow(*args, **kwargs)
    fleet.query = query
    workers = [Worker(ctx, "worker-a"), Worker(ctx, "worker-b")]
    start = threading.Barrier(2)
    ran: dict[str, bool] = {}
    errors: list[BaseException] = []

    def run(w):
        try:
            start.wait()
            w.ensure_recurring()
            start.wait()
            with ctx.db.session() as s:   # only the sweep is due: the other recurring jobs wait for this test
                s.query(JobRow).filter(JobRow.kind != "usage_sweep", JobRow.done_at.is_(None)).delete()
            start.wait()
            ran[w.worker_id] = w.run_one()
        except BaseException as exc:            # noqa: BLE001 - reported by the assertion below
            errors.append(exc)
    threads = [threading.Thread(target=run, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == [] and sorted(ran.values()) == [False, True], ran
    with ctx.db.session() as s:
        sweeps = s.query(AnalysisSweepRow).all()
        assert [(r.cluster_id, r.status) for r in sweeps] == [("CRC", "complete")]
        pending = s.query(JobRow).filter(JobRow.kind == "usage_sweep", JobRow.done_at.is_(None)).all()
        assert len(pending) == 1 and pending[0].run_after > datetime.now(timezone.utc) + timedelta(hours=23)
        done = s.query(JobRow).filter(JobRow.kind == "usage_sweep", JobRow.done_at.is_not(None)).all()
        assert len(done) == 1 and done[0].attempts == 1


def test_a_database_at_0009_is_behind_this_code(monkeypatch):
    """#712: the sweep and GET /api/v1/quotas read 0010's tables, so /readyz waits until the migrate initContainer has run
    0010. Before: REQUIRED_REVISION was 0009, and a 0009 schema read ok."""
    db = Database(conftest.DB_URL)
    monkeypatch.setattr(db, "schema_version", lambda: "0009")
    try:
        # Since #21 the code needs 0012 (capacity_snapshots, placement holds); a 0009 schema is still behind, now by three.
        assert db.schema_status() == "behind: at 0009, needs 0012"
    finally:
        db.engine.dispose()
