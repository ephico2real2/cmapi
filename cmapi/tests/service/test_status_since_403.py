"""#403: disconnected views date the current import status from its first observation."""
from datetime import datetime, timedelta, timezone

import pytest

from cmapi.core import registry
from cmapi.core.clients.kube import ClusterUnreachable
from conftest import build_world
from test_not_imported_404 import views

START = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
RELIST = timedelta(minutes=5)


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        at = START

        @classmethod
        def now(cls, tz):
            return cls.at.astimezone(tz)

    monkeypatch.setattr(registry, "datetime", Clock)
    return Clock


def test_failed_relists_keep_the_first_failure_in_both_tabs(test_config, keys, monkeypatch, clock):
    with build_world(test_config, keys, monkeypatch) as (client, ctx, _, kube, _, _):
        clock.at += RELIST
        kube.unreachable = True
        first = clock.at
        ctx.registry.refresh()
        clock.at += RELIST
        ctx.registry.refresh()

        listed, cap, group, pol = views(client, keys, "CRC")
        assert cap["state"] == pol["state"] == listed["status"] == "unreachable"
        assert datetime.fromisoformat(listed["checkedAt"]) == clock.at
        assert datetime.fromisoformat(cap["asOf"]) == first
        assert group["excluded"][0]["asOf"] == cap["asOf"]
        assert datetime.fromisoformat(pol["asOf"]) == first
        assert datetime.fromisoformat(listed["statusSince"]) == first

        def timeout():
            raise ClusterUnreachable("timed out")

        with monkeypatch.context() as patch:
            patch.setattr(kube, "version", timeout)
            clock.at += RELIST
            ctx.registry.refresh()
        st = ctx.registry.get("CRC")
        assert st.findings == ["timed out"]
        assert st.status_since == first
        kube.unreachable = False
        clock.at += RELIST
        ctx.registry.refresh()
        assert st.status == "connected" and st.status_since == clock.at


def test_retirement_dates_the_missing_import_and_preserves_last_check(test_config, keys, monkeypatch, clock):
    assert registry.ClusterState("never-imported", None).view()["statusSince"] is None
    with build_world(test_config, keys, monkeypatch) as (client, ctx, *_):
        st = ctx.registry.get("CRC")
        assert st.status_since == st.checked_at == START
        monkeypatch.setattr(ctx.registry.source, "list", lambda: [])
        retired = START + RELIST + timedelta(seconds=37)
        clock.at = retired
        ctx.registry.refresh()
        clock.at += RELIST
        ctx.registry.refresh()

        listed, cap, _, pol = views(client, keys, "CRC")
        assert listed["status"] == cap["state"] == pol["state"] == "not-imported"
        assert datetime.fromisoformat(listed["checkedAt"]) == START
        assert datetime.fromisoformat(listed["statusSince"]) == retired
        assert datetime.fromisoformat(cap["asOf"]) == retired.replace(second=0)
        assert datetime.fromisoformat(pol["asOf"]) == retired
