"""Adversarial #456 checks over real clients and a fake import source, without sockets."""
import json

import httpx
import pytest

from test_cluster_import_log_456 import capture_registry_logs, import_events, refusing
from test_cluster_token_client_420 import BODIES, ODD, leaked
from test_registry_survives_419 import good, html_proxy, registry, secret


@pytest.mark.parametrize("status,handler,data", [
    ("unreachable", refusing, {}),
    ("invalid-secret", good, {"apiUrl": "https://[::1:6443"}),
    ("bad-response", html_proxy, {}),
])
def test_unchanged_problem_relists_emit_once(status, handler, data, capture_registry_logs):
    reg = registry({"TEST": handler}, [secret("TEST", **data)])
    try:
        with capture_registry_logs() as events:
            for _ in range(4):
                reg.refresh()
        found = import_events(events)
        assert len(found) == 1, found
        assert found[0]["status"] == reg.clusters["TEST"].status == status
        assert found[0]["findings"] == reg.clusters["TEST"].findings
    finally:
        reg.stop()


@pytest.mark.parametrize("shape", list(BODIES))
@pytest.mark.parametrize("status", [401, 500])
def test_echo_is_redacted_in_problem_and_recovery_events(shape, status, capture_registry_logs):
    def echo(request):
        return httpx.Response(status, text=BODIES[shape](request.headers["authorization"], ODD))

    handlers = {"TEST": echo}
    reg = registry(handlers, [secret("TEST", token=ODD)])
    try:
        with capture_registry_logs() as events:
            reg.refresh()
            reg.refresh()
            handlers["TEST"] = good
            reg.refresh()
            reg.refresh()
        found = import_events(events)
        assert len(found) == 2, found
        assert found[0]["status"] == ("auth_failed" if status == 401 else "unreachable")
        assert "***" in found[0]["findings"][0]
        assert found[1]["previous"] == found[0]["status"]
        assert found[1]["findings"] == []
        assert leaked(json.dumps(events), ODD) == []
        assert leaked(json.dumps(reg.clusters["TEST"].view(), default=str), ODD) == []
    finally:
        reg.stop()


def test_registry_generated_finding_is_redacted_before_comparison(capture_registry_logs):
    def identity(request):
        if request.url.path.endswith("/users/~"):
            return httpx.Response(200, json={"metadata": {"name": ODD}})
        return good(request)

    handlers = {"TEST": identity}
    reg = registry(handlers, [secret("TEST", token=ODD)])
    try:
        with capture_registry_logs() as events:
            reg.refresh()
            reg.refresh()
            handlers["TEST"] = good
            reg.refresh()
        found = import_events(events)
        assert len(found) == 2, found
        assert found[0]["status"] == found[1]["previous"] == "wrong-identity"
        assert "token is ***, expected" in found[0]["findings"][0]
        assert leaked(json.dumps(events), ODD) == []
    finally:
        reg.stop()
