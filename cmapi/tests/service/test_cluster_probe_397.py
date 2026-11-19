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
        assert probe("CRC", "limited").json()["code"] == "environment-forbidden"
        ctx.registry.get("CRC").policy = None
        assert probe("CRC", "limited").json()["code"] == "environment-forbidden"
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
