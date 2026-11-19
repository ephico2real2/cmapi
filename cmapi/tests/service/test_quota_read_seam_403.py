"""The plan's quota read keeps the quota_watch/cache seam (#393); no database needed."""
from cmapi.core.capacity_backend import QuotaRead, read_quotas
from cmapi.core.errors import Problem


def test_read_quotas_keeps_quota_watch_lookup():
    class StubRegistry:
        def quota_watch(self, cluster_id):
            assert cluster_id == "CRC"
            raise Problem(503, "cluster-unreachable", f"{cluster_id} is unreachable: test")

        def snapshot(self, cluster_id):
            raise AssertionError("read_quotas must keep the quota_watch/cache seam")

    read = read_quotas(StubRegistry(), "CRC")

    assert read.state == "unreachable"
    assert read == QuotaRead("unreachable", "no watch cache for this cluster: CRC is unreachable: test", None, None)
