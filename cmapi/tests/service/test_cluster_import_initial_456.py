"""#456: distinguish the first healthy import from recovery of a checked fault."""
import pytest

from test_cluster_import_log_456 import capture_registry_logs, import_events, refusing
from test_registry_survives_419 import good, html_proxy, registry, secret


@pytest.mark.parametrize("configured", [True, False])
def test_first_connected_import_does_not_log_recovery(configured, capture_registry_logs):
    reg = registry({"TEST": good}, [])
    if not configured:
        reg.clusters.clear()
        reg.policies.clear()
    try:
        with capture_registry_logs() as events:
            reg.refresh()
            reg.source.secrets = [secret("TEST")]
            reg.refresh()
            reg.refresh()
        assert reg.clusters["TEST"].status == "connected"
        assert import_events(events) == []
    finally:
        reg.stop()


@pytest.mark.parametrize("status,handler,data", [
    ("unreachable", refusing, {}),
    ("invalid-secret", good, {"apiUrl": "https://[::1:6443"}),
    ("bad-response", html_proxy, {}),
])
def test_recovery_of_each_checked_problem_logs_once(status, handler, data, capture_registry_logs):
    handlers = {"TEST": handler}
    reg = registry(handlers, [secret("TEST", **data)])
    try:
        reg.refresh()
        assert reg.clusters["TEST"].status == status
        handlers["TEST"] = good
        reg.source.secrets = [secret("TEST")]
        with capture_registry_logs() as events:
            reg.refresh()
            reg.refresh()
        assert import_events(events) == [{
            "event": "cluster_import", "log_level": "info", "cluster_id": "TEST",
            "status": "connected", "previous": status, "findings": [],
        }]
    finally:
        reg.stop()
