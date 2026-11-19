"""#404: a cluster that clusters.yaml names and no import Secret does is `not-imported` in every view, with a whole detail.

Measured on CRC (OB1 run 23): GET /api/v1/capacity gave such a cluster `state: unreachable` and `stateDetail: "the cluster is
not-imported: "`. Nothing was tried, so nothing is unreachable, and the registry set the finding `no import Secret` only when a
cluster *became* not-imported, so after a start the detail ended in a bare ": ". GET /api/v1/clusters and
/admin/integrations already said `not-imported`: Capacity and Policies now use the same word and the same finding.

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_not_imported_404.py -q -W ignore
"""
from __future__ import annotations

import shutil

import pytest

from cmapi.core.registry import ClusterState
from conftest import build_world
from test_flow import OLA, auth

DETAIL = "the cluster is not-imported: no import Secret"


def get(client, keys, path) -> dict:
    r = client.get(path, headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    return r.json()


def views(client, keys, cluster_id) -> tuple[dict, dict, dict, dict]:
    """The cluster in GET /clusters, /capacity and /policies/results, and its capacity group."""
    listed = next(c for c in get(client, keys, "/api/v1/clusters")["items"] if c["clusterId"] == cluster_id)
    capacity = get(client, keys, "/api/v1/capacity")
    cap = next(c for c in capacity["clusters"] if c["clusterId"] == cluster_id)
    group = next(g for g in capacity["groups"] if cluster_id in g["clusterIds"])
    pol = next(c for c in get(client, keys, "/api/v1/policies/results")["clusters"] if c["clusterId"] == cluster_id)
    return listed, cap, group, pol


def assert_not_imported(listed, cap, group, pol, cluster_id) -> None:
    assert (listed["status"], listed["findings"]) == ("not-imported", ["no import Secret"])
    assert (cap["state"], cap["stateDetail"]) == ("not-imported", DETAIL), cap
    assert (cap["nodesState"], cap["nodesDetail"]) == ("not-imported", DETAIL), cap
    assert all(cap[r][k] is None for r in ("cpu", "memory") for k in ("committed", "headroom", "commitment")), "unknown, never 0"
    assert {"clusterId": cluster_id, "reason": "not-imported", "asOf": cap["asOf"]} in group["excluded"], group
    assert (pol["state"], pol["stateDetail"], pol["counts"]) == ("not-imported", DETAIL, None), pol


@pytest.fixture
def two_clusters(test_config, fresh_db, keys, monkeypatch, tmp_path):
    """CRC imported and connected, and OCP_GF7 in clusters.yaml with no import Secret, on a fresh start."""
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    (d / "clusters.yaml").write_text((d / "clusters.yaml").read_text() + "  OCP_GF7:\n    environment: dev\n"
                                     "    gitopsPath: clusters/OCP_GF7\n    labels: {region: us-central}\n")
    with build_world(d, keys, monkeypatch) as w:
        yield w


def test_a_cluster_never_imported_reads_not_imported_with_its_finding_after_a_start(two_clusters):
    client, ctx, git, kube, validator, keys = two_clusters
    listed, cap, group, pol = views(client, keys, "OCP_GF7")
    assert_not_imported(listed, cap, group, pol, "OCP_GF7")
    assert cap["asOf"] is None and pol["asOf"] is None, "never checked: no time"


def test_a_cluster_whose_secret_is_deleted_reads_the_same(world):
    client, ctx, git, kube, validator, keys = world

    class NoSecret:
        def list(self):
            return []

    ctx.registry.source = NoSecret()
    ctx.registry.refresh()
    assert_not_imported(*views(client, keys, "CRC"), "CRC")


@pytest.mark.parametrize("status, findings, state, detail", [
    ("not-imported", ["no import Secret"], "not-imported", DETAIL),
    ("unreachable", ["CRC: ConnectError"], "unreachable", "the cluster is unreachable: CRC: ConnectError"),
    ("auth_failed", [], "unreachable", "the cluster is auth_failed"),
])
def test_the_state_of_a_cluster_not_connected_and_a_detail_with_no_empty_tail(status, findings, state, detail):
    assert ClusterState("C", None, status=status, findings=findings).not_connected() == (state, detail)


def test_a_cluster_state_starts_not_imported_with_its_finding():
    st = ClusterState("C", None)
    assert (st.status, st.findings) == ("not-imported", ["no import Secret"])
