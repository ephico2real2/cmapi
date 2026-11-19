"""#456: import logs describe changes of status or redacted findings, once per change.

Real KubeClients over MockTransport and a fake import source; no cluster or database needed.
"""
from __future__ import annotations

from contextlib import contextmanager

import httpx
import pytest

from test_registry_survives_419 import good, registry, secret


class RegistryLogRecorder:
    def __init__(self):
        self.events = []

    def info(self, event, **kw):
        self.events.append({"event": event, "log_level": "info", **kw})

    def warning(self, event, **kw):
        self.events.append({"event": event, "log_level": "warning", **kw})

    def error(self, event, **kw):
        self.events.append({"event": event, "log_level": "error", **kw})

    def debug(self, event, **kw):
        self.events.append({"event": event, "log_level": "debug", **kw})

    exception = error


@pytest.fixture
def capture_registry_logs(monkeypatch):
    """Record the registry directly, even after app setup has cached structlog's logger."""
    @contextmanager
    def capture():
        recorder = RegistryLogRecorder()
        with monkeypatch.context() as patch:
            patch.setattr("cmapi.core.registry.log", recorder)
            yield recorder.events

    return capture


def refusing(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Connection refused", request=request)


def import_events(events):
    return [event for event in events if event["event"] == "cluster_import"]


def test_three_unreachable_relists_log_once(capture_registry_logs):
    reg = registry({"TEST": refusing}, [secret("TEST")])
    try:
        with capture_registry_logs() as events:
            for _ in range(3):
                reg.refresh()
        found = import_events(events)
        assert len(found) == 1, found
        assert found[0]["log_level"] == "warning"
        assert found[0]["cluster_id"] == "TEST"
        assert found[0]["status"] == "unreachable"
        assert found[0]["findings"] == reg.clusters["TEST"].findings
        assert "Connection refused" in found[0]["findings"][0]
    finally:
        reg.stop()


def test_recovery_logs_once_at_info_with_previous_status(capture_registry_logs):
    handlers = {"TEST": refusing}
    reg = registry(handlers, [secret("TEST")])
    try:
        for _ in range(3):
            reg.refresh()
        handlers["TEST"] = good
        with capture_registry_logs() as events:
            reg.refresh()
            reg.refresh()
        assert import_events(events) == [{
            "event": "cluster_import", "log_level": "info", "cluster_id": "TEST",
            "status": "connected", "previous": "unreachable", "findings": [],
        }]
        assert reg.clusters["TEST"].status == "connected"
    finally:
        reg.stop()


def test_changed_findings_while_unreachable_log_once_more(capture_registry_logs):
    def timed_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out", request=request)

    handlers = {"TEST": refusing}
    reg = registry(handlers, [secret("TEST")])
    try:
        with capture_registry_logs() as events:
            reg.refresh()
            reg.refresh()
            handlers["TEST"] = timed_out
            reg.refresh()
            reg.refresh()
        found = import_events(events)
        assert len(found) == 2, found
        assert [event["status"] for event in found] == ["unreachable", "unreachable"]
        assert [event["log_level"] for event in found] == ["warning", "warning"]
        assert found[1]["previous"] == "unreachable"
        assert found[1]["findings"] == reg.clusters["TEST"].findings
        assert "Connection timed out" in found[1]["findings"][0]
        assert found[0]["findings"] != found[1]["findings"]
    finally:
        reg.stop()
