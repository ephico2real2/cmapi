"""#21 capacity snapshots and safe placement, and #303 the placement API, on the service suite's world.

The story's criteria (gh issue 21):
1. "Internal capacity service stores snapshots at configured intervals; gateway enforces scope."
2. "Placement checks CPU and memory separately, freshness, reservations and zone-failure headroom."
3. "Concurrent reservations cannot overbook; expired reservations are reclaimed." (#62, PR #725, and the placement holds here)
4. "Namespace creation makes no Thanos query."
#303: "A placement call exists (rank, and reserve on submit) ... The portal calls it, drops the Cluster field, sends placementId."

The design: docs/02, "Stored capacity", "Snapshot job", "Placement"; docs/01, "Capacity, placement and usage". The world's CRC is in
dev, region us-central, simulatedCapacity 64 cores and 256Gi; dev's overcommit 2.0 and 1.25, so a limit of 128 cores and 320Gi.
A small namespace is 8 cores, 16Gi and 50 pods; a medium one 16 cores and 32Gi. The snapshot interval is 30 minutes and a
snapshot is stale after two (capacity.yaml defaults).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from cmapi.capacity.usage import PromUsage
from cmapi.core.capacity import CapacitySettings
from cmapi.core.db.repo import JobRepo, RequestRepo, utcnow
from cmapi.core.errors import Problem
from test_capacity_ledger_302 import node
from test_capacity_reservations_62 import body, committed, holds, who
from test_flow import OLA, auth, run_jobs

GiB = 2**30
PLACE = "/api/v1/capacity:place"
VIEWER = dict(roles=["cmapi-viewer"], groups=["/cmapi/app-cmapi-rbac-viewer"])
BOT_RND = dict(roles=["cmapi-bot-rnd"], groups=[])                 # capacity:read in rnd only (authz-roles.yaml)
OPAL = dict(roles=["cmapi-operator"], groups=["/cmapi/app-cmapi-rbac-operator"])


def headers(keys, who=OLA, user="ola"):
    return auth(keys, user, **who)


def place(world, tier="small", team="payments", *, dry=False, who=OLA, user="ola", **extra):
    client, ctx, git, kube, validator, keys = world
    ask = {"environment": "dev", "tier": tier, **({"team": team} if team is not None else {}), **extra}
    return client.post(PLACE + ("?dryRun=true" if dry else ""), json=ask, headers=headers(keys, who, user))


def snapshot(world) -> list[str]:
    """One run of the recurring snapshot job, as the worker runs it: the one it queued for the next interval is made due."""
    client, ctx, *_ = world
    with ctx.db.session() as s:
        if JobRepo(s).enqueue("capacity_snapshot", payload={"every": ctx.capacity.snapshot_seconds}) is None:
            # The host's clock, as run_jobs claims by it, not the database's.
            s.execute(text("UPDATE jobs SET run_after = :t WHERE kind = 'capacity_snapshot' AND done_at IS NULL"),
                      {"t": utcnow() - timedelta(seconds=1)})
    return run_jobs(ctx)


def rows(ctx) -> list[SimpleNamespace]:
    with ctx.db.session() as s:
        return [SimpleNamespace(**r) for r in s.execute(text(
            "SELECT * FROM capacity_snapshots ORDER BY taken_at, scope")).mappings().all()]


def age_snapshots(ctx, minutes: int) -> None:
    with ctx.db.session() as s:
        s.execute(text("UPDATE capacity_snapshots SET taken_at = taken_at - make_interval(mins => :m)"), {"m": minutes})


def nodes(kube) -> None:
    """Three nodes: two workers in zones a and b, and a control-plane node with its NoSchedule taint (it does not count)."""
    for n in (node("w1", cpu="6", memory="12Gi", zone="us-central-1a"), node("w2", cpu="2", memory="4Gi", zone="us-central-1b"),
              node("m1", cpu="4", memory="16Gi", zone="us-central-1a",
                   taints=[("node-role.kubernetes.io/master", "NoSchedule")])):
        n["metadata"]["labels"][f"node-role.kubernetes.io/{'master' if n['metadata']['name'] == 'm1' else 'worker'}"] = ""
        kube.objects[("Node", "", n["metadata"]["name"])] = n


class Metrics:
    """A MetricsSource that answers the snapshot's per-node queries from figures, and records every call: a create that reached
    Thanos would show here."""

    def __init__(self, *, allocatable_cpu=8.0, fail=False):
        self.calls: list[str] = []
        self.allocatable_cpu, self.fail = allocatable_cpu, fail

    def query(self, cluster_id, promql, at=None):
        from cmapi.capacity.thanos import MetricsUnavailable
        self.calls.append(promql)
        if self.fail:
            raise MetricsUnavailable(f"{cluster_id}: the Thanos Querier warned: ['partial response']")

        def v(node, value, **labels):
            return {"metric": {"node": node, **labels}, "value": [0, str(value)]}
        if "kube_pod_container_resource_requests" in promql:
            return [v("w1", 3, resource="cpu"), v("w2", 1, resource="cpu"), v("", 0.5, resource="cpu"),
                    v("w1", 6 * GiB, resource="memory")]
        if "kube_pod_container_resource_limits" in promql:
            return [v("w1", 5, resource="cpu")]
        if "kube_node_status_allocatable" in promql:
            return [v("w1", self.allocatable_cpu - 2, resource="cpu"), v("w2", 2, resource="cpu"), v("m1", 4, resource="cpu"),
                    v("w1", 12 * GiB, resource="memory"), v("w2", 4 * GiB, resource="memory"), v("m1", 16 * GiB, resource="memory")]
        if "kube_pod_info" in promql:
            return [v("w1", 12), v("w2", 3)]
        if "container_cpu_usage_seconds_total" in promql:
            return [v("w1", 2.0 if "max_over_time" in promql else 1.5)]
        if "container_memory_working_set_bytes" in promql:
            return [v("w1", 5 * GiB if "max_over_time" in promql else 4 * GiB)]
        return []


# ---- criterion 1: snapshots at the configured interval, and the gateway's scope

def test_the_snapshot_job_stores_the_cluster_its_zones_and_roles_at_the_configured_interval(world):
    """capacity.yaml snapshotInterval 15m: the job writes one row for the cluster, one per zone and one per role, at the
    interval's boundary, and queues itself at the next one. The master's taint keeps its allocatable out; it still counts in
    the cluster's capacity and its node total. Without a usage source the figures only Thanos gives are null, never 0."""
    client, ctx, git, kube, validator, keys = world
    ctx.capacity = CapacitySettings({**ctx.capacity_cfg, "snapshotInterval": "15m"})
    nodes(kube)
    committed(ctx, 24, "48Gi")
    before = datetime.now(timezone.utc)
    assert snapshot(world) == ["capacity_snapshot"]
    got = rows(ctx)
    assert [r.scope for r in got] == ["cluster", "role:master", "role:worker", "zone:us-central-1a", "zone:us-central-1b"]
    at = got[0].taken_at
    assert {r.taken_at for r in got} == {at} and at.timestamp() % 900 == 0 and before - at < timedelta(minutes=15)
    assert {(r.interval_seconds, r.source, r.complete, r.detail) for r in got} == {(900, "api", True, None)}
    cluster = got[0]
    assert cluster.cpu == {"capacity": 12.0, "allocatable": 8.0, "requested": None, "limits": None, "usedAvg": None,
                           "usedPeak": None, "nodeUsedAvg": None, "quotaCommitted": 24.0}
    assert cluster.memory["allocatable"] == 16 * GiB and cluster.memory["quotaCommitted"] == 48 * GiB
    assert cluster.nodes == {"total": 3, "schedulable": 2, "notReady": 0, "memoryPressure": 0, "diskPressure": 0}
    assert cluster.pods == {"allocatable": 500, "running": None}
    zone_a = next(r for r in got if r.scope == "zone:us-central-1a")
    assert (zone_a.cpu["allocatable"], zone_a.cpu["quotaCommitted"], zone_a.nodes["total"]) == (6.0, None, 2)
    with ctx.db.session() as s:
        nxt = JobRepo(s).pending("capacity_snapshot")
    assert nxt is not None and nxt.payload == {"every": 900}
    assert nxt.run_after.timestamp() == pytest.approx(at.timestamp() + 900, abs=2), "the next interval's boundary"


def test_with_thanos_the_snapshot_measures_requests_and_use_per_node(world):
    """usage.source thanos: the per-node queries of docs/02 at the interval's end. A Pending pod with no node counts toward the
    cluster row only; each zone row sums its own nodes."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    metrics = Metrics()
    ctx.usage = PromUsage(metrics)
    snapshot(world)
    got = {r.scope: r for r in rows(ctx)}
    assert got["cluster"].source == "thanos" and got["cluster"].complete
    assert got["cluster"].cpu["requested"] == 4.5 and got["zone:us-central-1a"].cpu["requested"] == 3.0
    assert got["zone:us-central-1b"].cpu["requested"] == 1.0
    assert (got["cluster"].cpu["usedAvg"], got["cluster"].cpu["usedPeak"]) == (1.5, 2.0)
    assert got["cluster"].memory["usedPeak"] == 5 * GiB and got["cluster"].pods["running"] == 15
    assert any("[30m:5m]" in q for q in metrics.calls), "average and peak over the interval in 5-minute steps"


@pytest.mark.parametrize("metrics, reason, requested", [
    (Metrics(fail=True), "Thanos did not answer", None),      # never written as zero
    (Metrics(allocatable_cpu=9.0), "data-mismatch", 4.5),     # Thanos 13 cores, the API 12: 8.3% apart; kept, but incomplete
])
def test_a_failed_query_or_a_gap_over_5_percent_marks_the_snapshot_incomplete(world, metrics, reason, requested):
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    ctx.usage = PromUsage(metrics)
    snapshot(world)
    got = rows(ctx)
    assert got and all(not r.complete and reason in r.detail for r in got), [(r.scope, r.detail) for r in got]
    assert got[0].cpu["requested"] == requested


def test_the_gateway_answers_a_cluster_s_snapshot_only_within_the_caller_s_environments(world):
    """docs/02: GET /api/v1/clusters/{clusterId}/capacity needs capacity:read on that cluster. A caller whose roles cover rnd
    only gets 404 for dev's CRC, as for a cluster that does not exist; the snapshot run needs operations:run."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    r = client.get("/api/v1/clusters/CRC/capacity", headers=headers(keys, VIEWER, "vera"))
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["snapshot"]["state"] == "ok" and view["intervalSeconds"] == 1800 and view["staleAfterSeconds"] == 3600
    assert [s["scope"] for s in view["scopes"]][0] == "cluster"
    assert view["scopes"][0]["cpu"]["allocatable"] == 8000 and view["scopes"][0]["memory"]["unit"] == "bytes"
    for url in ("/api/v1/clusters/CRC/capacity", "/api/v1/clusters/NOPE/capacity"):
        r = client.get(url, headers=headers(keys, BOT_RND, "bot"))
        assert (r.status_code, r.json()["code"]) == (404, "cluster-not-found"), r.text
    r = client.post("/api/v1/clusters/CRC/capacity/snapshots:run", headers=headers(keys, VIEWER, "vera"))
    assert r.status_code == 403, r.text
    r = client.post("/api/v1/clusters/CRC/capacity/snapshots:run", headers=headers(keys, OPAL, "opal"))
    assert r.status_code == 202 and r.json() == {"clusterId": "CRC", "queued": True}, r.text
    assert run_jobs(ctx) == ["capacity_snapshot"]


def test_the_capacity_tab_shows_each_cluster_s_snapshot(world):
    client, ctx, git, kube, validator, keys = world
    page = client.get("/api/v1/capacity", headers=headers(keys, VIEWER, "vera")).json()
    assert page["snapshotState"] == "stored" and page["snapshotIntervalSeconds"] == 1800
    assert page["clusters"][0]["snapshot"] == {"state": "none", "takenAt": None, "source": None, "detail": "no snapshot yet"}
    assert page["notMeasured"] == ["requested", "usedAvg", "usedPeak", "history"]
    nodes(kube)
    snapshot(world)
    page = client.get("/api/v1/capacity", headers=headers(keys, VIEWER, "vera")).json()
    assert page["clusters"][0]["snapshot"]["state"] == "ok" and page["clusters"][0]["snapshot"]["source"] == "api"


# ---- criterion 2: placement checks CPU and memory separately, freshness, reservations and zone-failure headroom

def test_placement_ranks_from_a_fresh_snapshot_and_holds_the_winner_for_15_minutes(world):
    """No snapshot: CRC is excluded as stale-data and nothing can be held (422 no-placement). With one, the dry run ranks CRC
    and holds nothing; the call holds 8 cores and 16Gi on CRC for 15 minutes, as a placement with no request yet."""
    client, ctx, git, kube, validator, keys = world
    r = place(world, dry=True)
    assert r.status_code == 200 and r.json()["ranked"] == [], r.text
    assert r.json()["excluded"] == [{"clusterId": "CRC", "reason": "stale-data",
                                     "detail": "no complete snapshot yet, limit 60 min"}]
    r = place(world)
    assert (r.status_code, r.json()["code"]) == (422, "no-placement"), r.text
    assert r.json()["excluded"][0]["reason"] == "stale-data"
    nodes(kube)
    snapshot(world)
    dry = place(world, dry=True).json()
    assert dry["placementId"] is None and [x["clusterId"] for x in dry["ranked"]] == ["CRC"] and holds(ctx) == []
    top = dry["ranked"][0]
    assert top["cpu"] == {"unit": "millicores", "quotaHeadroomBefore": 128000, "quotaHeadroomAfter": 120000,
                          "zoneFailureHeadroomAfter": None, "usageP95": None}
    assert top["basis"] == "simulated" and 0 < top["score"] <= 100 and top["factors"]["usageHeadroom"] == 0.0
    r = place(world)
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["placementId"].startswith("pl-") and res["clusterId"] == "CRC" and res["ranked"][0]["reserved"] is True
    [h] = holds(ctx)
    assert (h.placement_id, h.request_id, h.cluster_id, h.env, h.team) == (res["placementId"], None, "CRC", "dev", "payments")
    assert (float(h.cpu), h.memory, h.pods) == (8.0, 16 * GiB, 50)
    assert timedelta(minutes=14) < h.expires_at - h.created_at <= timedelta(minutes=15)


def test_cpu_and_memory_are_checked_separately(world):
    """docs/01: "A namespace that needs only memory is never refused for CPU, and the reverse". 300Gi of 320Gi memory
    committed, 1 core of 128: a small namespace fits (16Gi of 20Gi left), a medium does not (32Gi), named as memory. Then 125
    cores committed: a small one is refused for CPU."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    committed(ctx, 1, "300Gi")
    assert [x["clusterId"] for x in place(world, dry=True).json()["ranked"]] == ["CRC"]
    medium = place(world, "medium", dry=True).json()
    assert medium["ranked"] == [] and medium["excluded"] == [{"clusterId": "CRC", "reason": "no-memory-headroom", "detail":
        "needs 32 Gi, 20 Gi left after committed quota and active reservations"}]
    committed(ctx, 125, "1Gi")
    small = place(world, dry=True).json()
    assert small["excluded"][0]["reason"] == "no-cpu-headroom" and small["excluded"][0]["detail"].startswith("needs 8 cores, 3 cores")


def test_a_stale_or_incomplete_snapshot_excludes_the_cluster(world):
    """Older than two intervals: stale-data. A newest snapshot that is incomplete and no fresh complete one: partial-data, with
    the snapshot's own reason."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    age_snapshots(ctx, 61)
    x = place(world, dry=True).json()["excluded"]
    assert x[0]["reason"] == "stale-data" and "limit 60 min" in x[0]["detail"], x
    kube.forbidden_kinds.add("Node")
    snapshot(world)
    x = place(world, dry=True).json()["excluded"]
    assert x[0]["reason"] == "partial-data" and "the nodes could not be listed" in x[0]["detail"], x


def test_placement_counts_the_holds_of_requests_and_of_other_placements(world):
    """104 of 128 cores committed: room for one medium (16), not two. The first placement holds it; the second is excluded,
    counting the first's hold, and the create of a third namespace that fits alone is refused at its check."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    committed(ctx, 104)
    assert place(world, "medium").status_code == 201
    second = place(world, "medium", dry=True).json()
    assert second["excluded"][0]["reason"] == "no-cpu-headroom" and "8 cores left" in second["excluded"][0]["detail"]
    r = client.post("/api/v1/clusters/CRC/namespaces", json=body("payments-c", "medium"), headers=headers(keys))
    assert (r.status_code, r.json()["code"]) == (422, "capacity-exceeded"), r.text


def test_zone_failure_headroom_excludes_a_cluster_that_would_not_survive_losing_its_largest_zone(world):
    """placement.yaml zoneFailureEnvironments [dev], for this dev-only world (prod by default). Zone a has 6 of the 8 counted
    cores: without it the limit is 64 × 0.25 × 2.0 = 32 cores. With 20 committed, a small namespace (8) still fits after a zone
    is lost, a medium one (16) does not."""
    client, ctx, git, kube, validator, keys = world
    from cmapi.core.placement import PlacementSettings          # here, so a tree without it fails this test alone
    ctx.placement = PlacementSettings({"zoneFailureEnvironments": ["dev"]})
    nodes(kube)
    snapshot(world)
    committed(ctx, 20)
    small = place(world, dry=True).json()
    assert small["ranked"][0]["cpu"]["zoneFailureHeadroomAfter"] == 4000, small
    medium = place(world, "medium", dry=True).json()
    assert medium["excluded"] == [{"clusterId": "CRC", "reason": "zone-failure-headroom",
                                   "detail": "needs 16 cores, 12 cores left without zone us-central-1a"}]


def test_a_team_holds_at_most_three_placements_in_an_environment(world):
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    assert [place(world).status_code for _ in range(3)] == [201, 201, 201]
    r = place(world)
    assert (r.status_code, r.json()["code"]) == (429, "rate-limited") and r.json()["retryAfter"] == 60, r.text
    assert place(world, team="billing").status_code == 201, "another team is not limited by this one's"


def test_with_no_team_the_cap_of_three_placements_is_the_caller_s(world):
    """An instance whose metadata keys have no team label places with no team (PlacementRequest.team left out): the hold has
    none, and its caller's own placements count toward the 3."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    assert [place(world, team=None).status_code for _ in range(3)] == [201, 201, 201]
    assert {(h.team, h.placed_by) for h in holds(ctx)} == {(None, "ola")}
    r = place(world, team=None)
    assert (r.status_code, r.json()["code"]) == (429, "rate-limited") and "ola already holds 3" in r.json()["detail"], r.text
    assert place(world, team=None, who=OPAL, user="opal").status_code == 201, "another caller's are not counted"


def test_ranking_needs_capacity_read_and_the_hold_needs_namespaces_create(world):
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    assert place(world, dry=True, who=VIEWER, user="vera").status_code == 200
    r = place(world, who=VIEWER, user="vera")
    assert (r.status_code, r.json()["code"]) == (403, "forbidden") and "namespaces:create" in r.json()["detail"], r.text
    r = place(world, who=BOT_RND, user="bot", dry=True)
    assert (r.status_code, r.json()["code"]) == (403, "environment-forbidden"), r.text


def test_concurrent_placements_cannot_overbook(world):
    """Room for one medium namespace (104 of 128 cores committed). Eight placements at once: one holds it, every other is
    refused with no-placement, and the cluster's holds stay within its limit. The per-cluster lock serializes them."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    committed(ctx, 104)
    from cmapi.plugins.capacity import placement as placing    # here, so a tree without it fails this test alone
    results: list[str] = []
    barrier = threading.Barrier(8)

    def one(i: int) -> None:
        ask = placing.ask_of(ctx, {"environment": "dev", "team": f"team-{i}", "tier": "medium"})
        barrier.wait()
        try:
            placing.place(ctx, ask, ctx.placement, reserve=True)
            results.append("placed")
        except Problem as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(results) == ["no-placement"] * 7 + ["placed"], results
    assert sum(float(h.cpu) for h in holds(ctx)) == 16.0


def test_an_expired_placement_is_reclaimed_and_holds_nothing(world):
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    committed(ctx, 104)
    assert place(world, "medium").status_code == 201
    with ctx.db.session() as s:
        s.execute(text("UPDATE capacity_reservations SET expires_at = now() - interval '1 second'"))
    assert place(world, "medium").status_code == 201, "the lapsed hold no longer counts"
    released = [h for h in holds(ctx, active=False) if h.released_why == "expired"]
    assert len(released) == 1, "reclaimed under the cluster's lock"


# ---- #303: the create claims the placement

def test_a_create_with_its_placement_turns_the_hold_into_the_request_s_own(world):
    """116 of 128 cores committed. The placement holds 8 (124). The create with its placementId is checked without the
    placement's hold, so it fits (124, warn); without that, its 8 would be counted twice (132) and refused. One hold remains:
    the placement's row, now the request's."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    committed(ctx, 116)
    pid = place(world).json()["placementId"]
    r = client.post("/api/v1/clusters/CRC/namespaces", json={**body("payments-a"), "placementId": pid}, headers=headers(keys))
    assert r.status_code == 202, r.text
    [h] = holds(ctx)
    assert (h.placement_id, h.request_id, h.namespace, float(h.cpu)) == (pid, r.json()["requestId"], "payments-a", 8.0)
    assert h.expires_at - h.created_at > timedelta(hours=1), "the request's term, no longer the placement's 15 minutes"
    again = client.post("/api/v1/clusters/CRC/namespaces", json={**body("payments-b"), "placementId": pid},
                        headers=headers(keys))
    assert (again.status_code, again.json()["code"]) == (422, "placement-not-found"), "a placement serves one create"


def test_a_placement_used_or_lapsed_between_the_plan_and_the_submit_records_nothing(world):
    """The plan finds the placement; it lapses before the submit (the window of a concurrent create that claims it). The submit
    is refused with placement-not-found and no request is recorded: a placement serves one create, and the check never leaves
    out a hold that another request owns."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    pid = place(world).json()["placementId"]
    plan = ctx.pipeline.plan_namespace(who(), "CRC", {**body("payments-a"), "placementId": pid}, action="create")
    assert plan.placement_id == pid
    with ctx.db.session() as s:
        s.execute(text("UPDATE capacity_reservations SET expires_at = now() - interval '1 second'"))
    with pytest.raises(Problem) as e:
        with ctx.db.session() as s:
            ctx.pipeline.submit(who(), plan, RequestRepo(s), JobRepo(s), idempotency_key=None, body_fingerprint="x",
                                justification=None)
    assert (e.value.status, e.value.code) == (422, "placement-not-found")
    with ctx.db.session() as s:
        assert s.execute(text("SELECT count(*) FROM change_requests")).scalar() == 0


@pytest.mark.parametrize("change, code", [
    ({"labels": {"cmapi.net/team": "billing", "cmapi.net/cost-center": "cc-4410"}}, "placement-mismatch"),
    ({"placementId": "pl-20260101-00000000"}, "placement-not-found"),
])
def test_a_create_with_a_placement_of_another_target_is_refused(world, change, code):
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    snapshot(world)
    pid = place(world).json()["placementId"]
    r = client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json={**body("payments-a"), "placementId": pid, **change},
                    headers=headers(keys))
    assert (r.status_code, r.json()["code"]) == (422, code), r.text


# ---- criterion 4: namespace creation makes no Thanos query

def test_placing_and_creating_a_namespace_make_no_thanos_query(world):
    """docs/01: "Thanos on onboarding: Never queried while creating a namespace or setting its first quota. Placement uses stored
    snapshots." The instance reads Thanos (usage.source thanos): the snapshot job queries it; then the preview, the placement,
    the create's dry run and the create itself make no query."""
    client, ctx, git, kube, validator, keys = world
    nodes(kube)
    metrics = Metrics()
    ctx.usage = ctx.pipeline.usage = PromUsage(metrics)
    snapshot(world)
    assert metrics.calls, "the snapshot job is what reads Thanos"
    metrics.calls.clear()
    assert place(world, dry=True).status_code == 200
    pid = place(world).json()["placementId"]
    create = {**body("payments-a"), "placementId": pid}
    assert client.post("/api/v1/clusters/CRC/namespaces?dryRun=true", json=create, headers=headers(keys)).status_code == 200
    r = client.post("/api/v1/clusters/CRC/namespaces", json=create, headers=headers(keys))
    assert r.status_code == 202, r.text
    run_jobs(ctx)
    assert metrics.calls == []
