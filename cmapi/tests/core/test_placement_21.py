"""#21: the placement decision (core/placement.py) and the snapshot settings of capacity.yaml (core/capacity.py), pure.

The routes, the snapshots and the holds are tests/service/test_placement_21.py. docs/02, "Placement": hard filters with a named
reason; "Score, 0 to 100 ... multiplied by the cluster's weight and capped at 100. Ties go to the lower clusterId, so the same
inputs always give the same answer."
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from cmapi.core.capacity import CapacitySettings
from cmapi.core.placement import Ask, Candidate, PlacementSettings, rank

NOW = datetime(2026, 11, 26, 17, 5, tzinfo=timezone.utc)
FRESH = datetime(2026, 11, 26, 17, 0, tzinfo=timezone.utc)
GI = D(2**30)
SMALL = Ask("dev", "payments", D(8), 16 * GI, 50)


def cluster(cid: str, **kw) -> Candidate:
    base = dict(cluster_id=cid, region="us-central", labels={"region": "us-central"}, writes=True, not_connected=None,
                enabled=True, max_namespaces=None, weight=1.0, size={"cpu": D(64), "memory": 256 * GI}, basis="simulated",
                overcommit={"cpu": D(2), "memory": D("1.25")}, committed={"cpu": D(0), "memory": D(0)}, committed_detail=None,
                namespaces=0, reserved={"cpu": D(0), "memory": D(0)}, snapshot_at=FRESH, snapshot_detail=None, zones={},
                usage_p95=None, team_namespaces=0)
    return Candidate(**{**base, **kw})


def ranked(*cands: Candidate, ask: Ask = SMALL, settings: PlacementSettings | None = None):
    return rank(ask, cands, settings or PlacementSettings(None), now=NOW, stale_after=3600)


def test_the_emptier_cluster_ranks_first_and_ties_go_to_the_lower_cluster_id():
    r, x = ranked(cluster("B"), cluster("A"), cluster("C", committed={"cpu": D(96), "memory": 160 * GI}))
    assert [c.cluster_id for c in r] == ["A", "B", "C"] and x == []
    assert r[0].score == r[1].score > r[2].score


def test_each_hard_filter_names_its_reason():
    r, x = ranked(
        cluster("A1", not_connected="the cluster is unreachable: timeout"), cluster("A2", writes=False),
        cluster("A3", enabled=False), cluster("A4", region="eu-west"), cluster("A5", snapshot_at=NOW - timedelta(minutes=61)),
        cluster("A6", snapshot_at=None, snapshot_detail="Thanos did not answer: timeout"),
        cluster("A7", committed=None, committed_detail="the ResourceQuota watch is stale"), cluster("A8", size=None),
        cluster("A9", max_namespaces=2, namespaces=2), cluster("B1", committed={"cpu": D(125), "memory": D(0)}),
        cluster("B2", committed={"cpu": D(0), "memory": 310 * GI}), cluster("B3", labels={"gpu": "true"}),
        ask=Ask("dev", "payments", D(8), 16 * GI, 50, region="us-central"))
    assert [(e.cluster_id, e.reason) for e in x] == [
        ("A1", "not-connected"), ("A2", "not-writable"), ("A3", "placement-disabled"), ("A4", "outside-region"),
        ("A5", "stale-data"), ("A6", "partial-data"), ("A7", "partial-data"), ("A8", "no-size"), ("A9", "max-namespaces"),
        ("B1", "no-cpu-headroom"), ("B2", "no-memory-headroom")]
    assert [c.cluster_id for c in r] == ["B3"]
    r, x = ranked(cluster("B3", labels={"gpu": "false"}),
                  ask=Ask("dev", "payments", D(8), 16 * GI, 50, selector={"gpu": "true"}))
    assert (r, [e.reason for e in x]) == ([], ["outside-selector"])


def test_reserved_capacity_counts_against_headroom():
    """120 committed and 4 held of 128: a small namespace (8) does not fit; without the hold it does."""
    assert ranked(cluster("A", committed={"cpu": D(120), "memory": D(0)}))[0]
    r, x = ranked(cluster("A", committed={"cpu": D(116), "memory": D(0)}, reserved={"cpu": D(8), "memory": D(0)}))
    assert r == [] and x[0].reason == "no-cpu-headroom"


def test_zone_failure_headroom_applies_in_the_configured_environments_only():
    """Two equal zones: losing one halves the limit (64 cores). 60 committed: a small namespace fits the cluster, not the loss
    of a zone. One zone: nothing survives its loss."""
    two = {"a": {"cpu": D(4), "memory": 8 * GI}, "b": {"cpu": D(4), "memory": 8 * GI}}
    busy = cluster("A", zones=two, committed={"cpu": D(60), "memory": D(0)})
    assert [c.cluster_id for c in ranked(busy)[0]] == ["A"], "dev: not checked by default"
    prod = Ask("prod", "payments", D(8), 16 * GI, 50)
    r, x = ranked(busy, ask=prod)
    assert r == [] and (x[0].reason, x[0].detail) == ("zone-failure-headroom", "needs 8 cores, 4 cores left without zone a")
    r, _ = ranked(cluster("A", zones=two), ask=prod)
    assert r[0].figures["cpu"]["zoneFailureHeadroomAfter"] == 56000
    _, x = ranked(cluster("A", zones={"a": two["a"]}), ask=prod)
    assert x[0].reason == "zone-failure-headroom" and "one zone" in x[0].detail


def test_the_weight_scales_the_score_and_usage_headroom_counts_only_when_measured():
    plain = ranked(cluster("A"))[0][0]
    assert ranked(cluster("A", weight=0.5))[0][0].score == int(plain.score * 0.5 + 0.5)
    assert ranked(cluster("A", weight=2.0))[0][0].score == min(100, int(plain.score * 2 + 0.5))
    busy = ranked(cluster("A", usage_p95={"cpu": 0.9, "memory": 0.2}))[0][0]
    idle = ranked(cluster("A", usage_p95={"cpu": 0.1, "memory": 0.1}))[0][0]
    assert plain.factors["usageHeadroom"] == 0.0 and busy.factors["usageHeadroom"] == 0.1 and idle.factors["usageHeadroom"] == 0.9
    assert ranked(cluster("A", team_namespaces=2))[0][0].factors["teamAffinity"] == 1.0


@pytest.mark.parametrize("raw, problem", [
    ({"snapshotInterval": "10m"}, "15m to 60m"), ({"snapshotInterval": "2h"}, "15m to 60m"),
    ({"snapshotInterval": 30}, "minutes or hours"), ({"staleAfterIntervals": 0}, "1 or more"),
])
def test_capacity_yaml_snapshot_settings_are_checked_at_the_start(raw, problem):
    with pytest.raises(ValueError, match=problem):
        CapacitySettings(raw)


def test_capacity_yaml_snapshot_settings_and_their_defaults():
    assert (CapacitySettings(None).snapshot_seconds, CapacitySettings(None).stale_after_seconds) == (1800, 3600)
    s = CapacitySettings({"snapshotInterval": "1h", "staleAfterIntervals": 3})
    assert (s.snapshot_seconds, s.stale_after_seconds) == (3600, 10800)


@pytest.mark.parametrize("raw, problem", [
    ({"weights": {"nope": 1}}, "not one of"), ({"weights": {"balance": -1}}, "0 or more"),
    ({"reservation": "2h"}, "1m to 60m"), ({"other": 1}, "unknown keys"),
])
def test_placement_yaml_is_checked_at_the_start(raw, problem):
    with pytest.raises(ValueError, match=problem):
        PlacementSettings(raw)
