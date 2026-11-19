"""#456: retirement clears the old finding and introduces no import Secret, once."""
from unittest.mock import Mock

import pytest

from cmapi.core.observability import CLUSTER_STATUS, CLUSTER_TLS_INSECURE
from cmapi.core.registry import NO_IMPORT_SECRET, STATUSES
from test_cluster_import_log_456 import capture_registry_logs, import_events, refusing
from test_registry_survives_419 import good, html_proxy, registry, secret


@pytest.mark.parametrize("status,handler,data", [
    ("connected", good, {}),
    ("unreachable", refusing, {}),
    ("invalid-secret", good, {"apiUrl": "https://[::1:6443"}),
    ("bad-response", html_proxy, {}),
])
def test_secret_removal_logs_one_transition_and_reimport_logs_once(status, handler, data, capture_registry_logs):
    handlers = {"TEST": handler}
    reg = registry(handlers, [secret("TEST", **data)])
    try:
        reg.refresh()
        st = reg.clusters["TEST"]
        assert st.status == status
        checked_at = st.checked_at
        old_metrics = {s: CLUSTER_STATUS.labels("TEST", s)._value.get() for s in STATUSES}
        reg.source.secrets = []
        with capture_registry_logs() as events:
            reg.refresh()
            reg.refresh()
        assert import_events(events) == [{
            "event": "cluster_import", "log_level": "warning", "cluster_id": "TEST",
            "status": "not-imported", "previous": status, "findings": [NO_IMPORT_SECRET],
        }]
        assert st.status == "not-imported" and st.findings == [NO_IMPORT_SECRET]
        assert st.checked_at == checked_at
        assert {s: CLUSTER_STATUS.labels("TEST", s)._value.get() for s in STATUSES} == old_metrics
        assert st.trust is st.client is st.cache is st.ledger is None
        handlers["TEST"] = good
        reg.source.secrets = [secret("TEST")]
        with capture_registry_logs() as events:
            reg.refresh()
            reg.refresh()
        assert import_events(events) == [{
            "event": "cluster_import", "log_level": "info", "cluster_id": "TEST",
            "status": "connected", "previous": "not-imported", "findings": [],
        }]
    finally:
        reg.stop()


def test_retirement_still_cleans_caches_and_logs_tls_downgrade_clear(capture_registry_logs):
    reg = registry({"TEST": good}, [secret("TEST", insecure="true")])
    reg.insecure_environments = frozenset({"rnd"})
    reports, nodes = Mock(), Mock()
    reg.reports_factory = lambda st, client: reports
    reg.nodes_factory = lambda st, client: nodes
    try:
        reg.refresh()
        st = reg.clusters["TEST"]
        cache = st.cache
        cache.stop = Mock(wraps=cache.stop)
        assert CLUSTER_TLS_INSECURE.labels("TEST")._value.get() == 1
        reg.source.secrets = []
        with capture_registry_logs() as events:
            reg.refresh()
            reg.refresh()
        assert len(import_events(events)) == 1
        assert [e for e in events if e["event"] == "cluster_tls_mode"] == [{
            "event": "cluster_tls_mode", "log_level": "info", "cluster_id": "TEST",
            "mode": None, "previous": "insecure", "server_name": None,
        }]
        cache.stop.assert_called_once()
        reports.stop.assert_called_once()
        nodes.stop.assert_called_once()
        assert st.reports is st.nodes is None
        assert CLUSTER_TLS_INSECURE.labels("TEST")._value.get() == 0
    finally:
        reg.stop()
