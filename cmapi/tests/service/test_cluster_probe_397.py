"""A probe checks only the held import, under the same lock and cache rules as discovery."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from cmapi.core.authz import RolePolicy
from cmapi.core.clients.kube import ClusterUnreachable
from conftest import build_world
from test_cluster_import_log_456 import capture_registry_logs, import_events
from test_registry_survives_419 import good, registry, secret


def test_probe_permissions_and_unknown_id(test_config, keys, monkeypatch):
    with build_world(test_config, keys, monkeypatch) as (client, ctx, *_):
        def probe(cid, role):
            return client.post(f"/api/v1/clusters/{cid}:probe",
                               headers={"Authorization": "Bearer " + keys.token("ada", roles=[role])})

        checked = ctx.registry.get("CRC").checked_at
        for cid in ("CRC", "UNKNOWN"):
            denied = probe(cid, "cmapi-viewer")
            assert denied.status_code == 403 and denied.json()["code"] == "forbidden"
        assert ctx.registry.get("CRC").checked_at == checked
        missing = probe("UNKNOWN", "cmapi-operator")
        assert missing.status_code == 404 and missing.json()["code"] == "cluster-not-found"
        ok = probe("CRC", "cmapi-operator")
        assert ok.status_code == 200 and ok.json()["status"] == "connected"
        assert ctx.registry.get("CRC").checked_at > checked
        ctx.cfg.roles = RolePolicy({"roles": {"limited": {"permissions": ["operations:run"], "environments": ["rnd"]}}})
        st = ctx.registry.get("CRC")
        checked = st.checked_at
        with monkeypatch.context() as patch:
            patch.delitem(ctx.registry.clusters, "CRC")
            absent = probe("CRC", "limited")
        assert absent.status_code == 404 and absent.json()["code"] == "cluster-not-found"
        for policy in (st.policy, None):
            st.policy = policy
            hidden = probe("CRC", "limited")
            assert hidden.status_code == absent.status_code
            assert hidden.content == absent.content
            assert st.checked_at == checked
        assert probe("CRC", "cmapi-operator").status_code == 200


@pytest.mark.parametrize("outcome", ["connected", "auth_failed", "forbidden", "unreachable", "cert-verify-failed"])
def test_probe_runs_relist_checks_without_rediscovery(outcome, monkeypatch, capture_registry_logs):
    calls = []
    handlers = {"ONE": good, "TWO": good}
    reg = registry(handlers, [secret("ONE"), secret("TWO")])

    def answer(request):
        path = request.url.path
        calls.append((request.method, path))
        if outcome == "auth_failed":
            return httpx.Response(401)
        if outcome in ("unreachable", "cert-verify-failed"):
            raise ClusterUnreachable("CERTIFICATE_VERIFY_FAILED" if outcome.startswith("cert") else "offline")
        if outcome == "forbidden" and path == "/api/v1/namespaces":
            return httpx.Response(403)
        return good(request)

    try:
        reg.refresh()
        cache = reg.get("ONE").cache
        other = reg.get("TWO").view()
        monkeypatch.setattr(reg.source, "list", lambda: pytest.fail("unexpected import relist"))
        handlers["ONE"] = answer
        with capture_registry_logs() as events:
            row = reg.probe("ONE")
            assert row["status"] == outcome
            paths = ["/version"]
            if outcome in ("forbidden", "connected"):
                paths += ["/apis/user.openshift.io/v1/users/~", "/api/v1/namespaces"]
            assert calls == [("GET", p) for p in paths]
            assert row["lastProbeAt"] == row["checkedAt"]
            assert reg.get("ONE").cache is (cache if outcome == "connected" else None)
            reg.probe("ONE")
        assert [e["status"] for e in import_events(events)] == ([] if outcome == "connected" else [outcome])
        assert reg.get("TWO").view() == other
    finally:
        reg.stop()


def test_probe_waits_for_removal_and_cannot_resurrect_the_import():
    reg = registry({"ONE": good}, [secret("ONE")])
    listing, contending = Event(), Event()
    lock = reg._refresh_lock

    class Lock:
        def __enter__(self):
            if listing.is_set():
                contending.set()
            lock.acquire()

        def __exit__(self, *args):
            lock.release()

    def removed():
        listing.set()
        assert contending.wait(3)
        return []

    try:
        reg.refresh()
        probe = reg.probe
        reg.source.list = removed
        reg._refresh_lock = Lock()
        with ThreadPoolExecutor(max_workers=2) as pool:
            relist = pool.submit(reg.refresh)
            assert listing.wait(3)
            result = pool.submit(probe, "ONE")
            relist.result(timeout=5)
            assert result.result(timeout=5)["status"] == "not-imported"
            assert contending.is_set() and reg.get("ONE").cache is None
    finally:
        reg.stop()


def test_probe_uses_last_successful_discovery_and_recovers_without_a_hub_read(monkeypatch):
    item = secret("ONE")
    handlers = {"ONE": lambda request: httpx.Response(401)}
    reg = registry(handlers, [item])
    try:
        reg.refresh()
        assert reg.get("ONE").status == "auth_failed"
        item["data"]["token"] = ""
        handlers["ONE"] = good

        def failed_list():
            raise OSError("hub offline")

        with monkeypatch.context() as patch:
            patch.setattr(reg.source, "list", failed_list)
            reg.refresh()
            assert reg.probe("ONE")["status"] == "connected"
            assert reg.get("ONE").cache is not None

        reg.source.secrets.append(secret("ONE"))
        reg.refresh()
        row = reg.probe("ONE")
        assert row["status"] == "invalid-secret"
        assert row["secretName"] is row["tokenExpiresAt"] is None
        assert row["findingDetails"][0]["finding"] == row["findings"][0]
        assert "exactly one" in row["findingDetails"][0]["fix"]
    finally:
        reg.stop()


def test_probe_sanitizes_unexpected_failure_before_logging_and_truncation(monkeypatch):
    import json
    import structlog

    item = secret("ONE")
    reg = registry({"ONE": good}, [item])
    events = []

    # Render exc_info just as configure_logging does, including implicit tracebacks from log.exception.
    def record(logger, method, event):
        events.append(event)
        raise structlog.DropEvent

    log = structlog.wrap_logger(structlog.ReturnLogger(), wrapper_class=structlog.stdlib.BoundLogger,
                                processors=[structlog.processors.format_exc_info, record])
    monkeypatch.setattr("cmapi.core.registry.log", log)
    try:
        reg.refresh()

        def failed_client(*args, **kwargs):
            raise RuntimeError(item["data"]["apiUrl"] + " " + "x" * 165 + item["data"]["token"])

        monkeypatch.setattr(reg, "client_factory", failed_client)
        row = reg.probe("ONE")
        assert row["status"] == "unreachable"
        assert any(e["event"] == "cluster_check_failed" for e in events)
        for diagnostic in (json.dumps(events), json.dumps(row, default=str)):
            assert item["data"]["apiUrl"] not in diagnostic
            assert item["data"]["token"][:8] not in diagnostic
    finally:
        reg.stop()


def test_probe_redacts_remote_fields_before_publishing_diagnostics(capture_registry_logs):
    from test_cluster_token_client_420 import ODD, go_escape

    item = secret("ONE", token=ODD, note="fixture-private-import-note")
    echo = go_escape(ODD) + " " + item["data"]["note"]
    handlers = {"ONE": good}
    reg = registry(handlers, [item])

    def answer(request):
        if request.url.path == "/version":
            return httpx.Response(200, json={"gitVersion": echo})
        if request.url.path.endswith("/users/~"):
            return httpx.Response(200, json={"metadata": {"name": echo}})
        return good(request)

    try:
        reg.refresh()
        handlers["ONE"] = answer
        with capture_registry_logs() as events:
            row = reg.probe("ONE")
        assert row["status"] == "wrong-identity"
        assert row["serverVersion"] == "*** ***"
        assert row["secretName"] == item["name"]
        finding = row["findings"][0]
        assert finding.startswith("token is *** ***, expected ")
        assert row["findingDetails"][0]["finding"] == finding
        assert import_events(events)[0]["findings"] == [finding]
    finally:
        reg.stop()


def test_http_client_log_does_not_publish_the_probe_target(monkeypatch):
    import io
    import logging

    from cmapi.core import observability

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    # Replace the HTTP client's module logger and the application's output handler.
    client_log = logging.Logger("httpx", level=logging.INFO)
    client_log.parent = logging.getLogger()
    monkeypatch.setattr("httpx._client.logger", client_log)
    monkeypatch.setattr(logging.getLogger(), "handlers", [handler])
    observability.configure_logging()

    item = secret("ONE")
    reg = registry({"ONE": good}, [item])
    try:
        reg.refresh()
        stream.seek(0)
        stream.truncate()
        assert reg.probe("ONE")["status"] == "connected"
        # Recovered caches open watches with the same held import.
        assert list(reg.get("ONE").client.watch("Namespace", "1"))[0]["items"] == []
        client_log.info("unrelated HTTP diagnostic")
        assert "unrelated HTTP diagnostic" in stream.getvalue()
        assert item["data"]["apiUrl"] not in stream.getvalue()
    finally:
        reg.stop()
