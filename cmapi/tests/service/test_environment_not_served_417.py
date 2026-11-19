"""#417: cluster statuses describe reachable import outcomes; environment policy is configuration.

No database or socket is needed: real KubeClients use the #419 MockTransport harness.
"""
from types import SimpleNamespace

import httpx
import pytest
from prometheus_client import CollectorRegistry, Gauge

from cmapi.core import registry as registry_module
from cmapi.core.errors import Problem
from cmapi.core.pipeline import Pipeline
from cmapi.core.registry import STATUSES, load_policies
from test_registry_survives_419 import answering, good, html_proxy, registry, secret


def test_every_advertised_status_has_a_producer_and_only_those_metrics(monkeypatch):
    def disconnected(request):
        raise httpx.ConnectError("connection refused", request=request)

    def certificate_failure(request):
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED", request=request)

    # Keys are expected outcomes, not calls to _set: each import really runs through refresh and the checks.
    handlers = {
        "connected": good,
        "not-imported": good,  # policy only: no Secret, no probe
        "invalid-secret": good,  # missing token: refused before a client is built
        "unreachable": disconnected,
        "cert-verify-failed": certificate_failure,
        "auth_failed": answering("/version", httpx.Response(401, json={})),
        "wrong-identity": answering("/apis/user.openshift.io/v1/users/~",
                                    httpx.Response(200, json={"metadata": {"name": "someone-else"}})),
        "forbidden": answering("/api/v1/namespaces", httpx.Response(403, json={})),
        "bad-response": html_proxy,
    }
    metrics = CollectorRegistry()
    monkeypatch.setattr(registry_module, "CLUSTER_STATUS",
                        Gauge("cmapi_cluster_status", "Status", ["cluster_id", "status"], registry=metrics))
    imports = [secret(status, **({"token": ""} if status == "invalid-secret" else {}))
               for status in handlers if status != "not-imported"]
    reg = registry(handlers, imports)
    try:
        reg.refresh()
        produced = {cid: st.status for cid, st in reg.clusters.items()}
        assert produced == {status: status for status in handlers}
        assert set(STATUSES) == set(produced.values()), "every listed cluster status needs a reachable producer"
        samples = [sample for metric in metrics.collect() for sample in metric.samples]
        assert {sample.labels["status"] for sample in samples} == set(handlers)
        for cid in handlers.keys() - {"not-imported"}:
            series = {sample.labels["status"]: sample.value for sample in samples
                      if sample.labels["cluster_id"] == cid}
            assert series == {status: int(status == cid) for status in handlers}
        assert not any(sample.labels["cluster_id"] == "not-imported" for sample in samples)
        for status, st in reg.clusters.items():
            if status != "connected":
                projected, detail = st.not_connected()
                assert projected == ("not-imported" if status == "not-imported" else "unreachable")
                assert f"the cluster is {status}" in detail
    finally:
        reg.stop()


def test_an_unserved_policy_stops_loading_instead_of_becoming_a_cluster_status(tmp_path):
    path = tmp_path / "clusters.yaml"
    path.write_text('clusters: {OTHER: {environment: prod}}\n')
    with pytest.raises(ValueError, match="cluster OTHER: environment 'prod' is not served by this instance"):
        load_policies(path, {"rnd", "dev"})


@pytest.mark.parametrize("registered", [True, False], ids=["policy-environment", "no-policy-read-only"])
def test_a_secret_cannot_supply_its_own_environment(registered):
    reg = registry({"IMPORTED": good}, [secret("IMPORTED", environment="prod")])
    if not registered:
        reg.policies.clear()
        reg.clusters.clear()
    try:
        reg.refresh()
        st = reg.get("IMPORTED")
        assert st.status == "connected"
        assert st.environment == ("rnd" if registered else None)
        assert st.view()["environment"] == ("rnd" if registered else "")
        if registered:
            assert reg.writable("IMPORTED") is st
        else:
            with pytest.raises(Problem) as caught:
                reg.writable("IMPORTED")
            assert (caught.value.status, caught.value.code) == (422, "cluster-not-writable")
    finally:
        reg.stop()


def test_the_request_problem_environment_not_served_still_returns_422():
    cfg = SimpleNamespace(allowed_environments={"rnd", "dev"}, name="nonprod", raw_instance={
        "instance": {"directory": {"prod": {"environments": ["prod"], "url": "https://prod.example",
                                           "portalUrl": "https://portal.prod.example"}}}})
    pipeline = SimpleNamespace(cfg=cfg)
    Pipeline.check_env_served(pipeline, "rnd")
    with pytest.raises(Problem) as caught:
        Pipeline.check_env_served(pipeline, "prod")
    assert (caught.value.status, caught.value.code) == (422, "environment-not-served")
    assert caught.value.extra == {"instanceUrl": "https://prod.example", "portalUrl": "https://portal.prod.example"}
