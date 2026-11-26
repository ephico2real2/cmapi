"""PR #707's review (#310): the live usage reader, the Thanos client, the sweep and the approval gate. Reviewer 1 (Codex) and
reviewer 2 (Opus). No network and no database: the Thanos Querier is an httpx MockTransport or usage_fake.FakeMetrics.

It lives in tests/service because what it tests is the service's: the Thanos client goes through core/clients/kube.py, which
logs and counts with structlog and prometheus_client, and the sweep and the plan import SQLAlchemy. tests/core runs with only
examples/local/requirements.txt (CI job reference-code, #693)."""
from __future__ import annotations

import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from cmapi.capacity import thanos, usage                    # noqa: E402
from cmapi.capacity.sweep import quota_now, row_verdict     # noqa: E402
from cmapi.capacity.verdicts import Verdict                 # noqa: E402
from cmapi.core.approvals import ApprovalRules              # noqa: E402
from cmapi.core.clients import kube                         # noqa: E402
from cmapi.core.clients.trust import Trust                  # noqa: E402
from cmapi.core.pipeline import Plan                        # noqa: E402
from cmapi.core.registry import load_policies               # noqa: E402
from usage_fake import Fake, FakeMetrics                    # noqa: E402

TOKEN = "sha256~reader-token-of-the-review-707-fixture"     # long enough for redact (8 characters or more)


def _ca_pem(cn: str) -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _recording(monkeypatch, answer=lambda request: httpx.Response(200, json={})):
    """httpx.Client as monitoring_get builds it, over a MockTransport: the kwargs of each client and every request sent."""
    built, sent, real = [], [], httpx.Client

    def handler(request):
        sent.append(request)
        return answer(request)

    def client(**kwargs):
        built.append(kwargs)
        return real(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(kube.httpx, "Client", client)
    return built, sent


# --------------------------------------------------------------------------- the Thanos transport (kube.py)

def test_the_route_is_verified_with_the_clusters_own_trust_mode(monkeypatch):
    """docs/02, "TLS: one mode per cluster". On OpenShift the import's caData (the reader's ServiceAccount ca.crt) holds the
    default ingress CA that signs the thanos-querier Route; trusted_context() (the RHCOS bundle and proxy trustedCA) does not.
    Measured on CRC, 2026-11-25: caData verified the Route, the injected bundle failed (CERTIFICATE_VERIFY_FAILED). A guard:
    head passes it, reviewer 1's patch fails it."""
    trust = Trust("caData", ca_data=_ca_pem("ingress-operator@review-707"), server_name="api.example.test")
    client = kube.KubeClient("c", "https://api.example.test:6443", TOKEN, trust)
    built, sent = _recording(monkeypatch)
    try:
        client.monitoring_get("https://thanos-querier-openshift-monitoring.apps.example.test/api/v1/query", {}, 10)
    finally:
        client.close()
    verify = built[-1]["verify"]
    assert verify is not kube.trusted_context()
    assert [c["subject"] for c in verify.get_ca_certs()] == [((("commonName", "ingress-operator@review-707"),),)]
    assert verify.server_name is None, "the API server's tls-server-name is not the Route's"
    assert sent[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_a_url_that_is_not_https_is_refused_before_the_token_is_sent(monkeypatch):
    client = kube.KubeClient("c", "https://api.example.test", TOKEN, insecure=True)
    built, sent = _recording(monkeypatch)
    try:
        for url in ("http://thanos.example.test/api/v1/query", "https://user:pass@thanos.example.test/api/v1/query"):
            with pytest.raises(kube.ClusterUnreachable, match="https URL"):
                client.monitoring_get(url, {}, 10)
    finally:
        client.close()
    assert sent == []


def test_thanos_url_must_be_https_when_clusters_yaml_is_loaded(tmp_path):
    path = tmp_path / "clusters.yaml"
    path.write_text(yaml.safe_dump({"clusters": {"CRC": {"environment": "dev", "thanosUrl": "http://thanos.example.test"}}}))
    with pytest.raises(ValueError, match="cluster CRC: thanosUrl must be an https URL"):
        load_policies(path, {"dev"})
    path.write_text(yaml.safe_dump({"clusters": {"CRC": {"environment": "dev", "thanosUrl": "https://thanos.example.test"}}}))
    assert load_policies(path, {"dev"})["CRC"].thanos_url == "https://thanos.example.test"


def test_the_answer_is_read_up_to_a_bound(monkeypatch):
    monkeypatch.setattr(kube, "MONITORING_MAX_BYTES", 8, raising=False)
    client = kube.KubeClient("c", "https://api.example.test", TOKEN)
    _recording(monkeypatch, lambda request: httpx.Response(200, stream=httpx.ByteStream(b"x" * 9)))
    try:
        with pytest.raises(kube.ClusterUnreachable, match="over 8 bytes"):
            client.monitoring_get("https://thanos.example.test/api/v1/query", {}, 10)
    finally:
        client.close()


def test_a_closed_client_makes_no_new_monitoring_client(monkeypatch):
    client = kube.KubeClient("c", "https://api.example.test", TOKEN)
    built, sent = _recording(monkeypatch)
    client.close()
    with pytest.raises(kube.ClusterUnreachable, match="replaced"):
        client.monitoring_get("https://thanos.example.test/api/v1/query", {}, 10)
    assert built == [] and sent == []


# --------------------------------------------------------------------------- the Querier's answer (thanos.py)

def _querier(answer):
    """A ThanosQuerier over one real KubeClient whose monitoring answers `answer`, with a thanosUrl (no Route read)."""
    client = kube.KubeClient("c", "https://api.example.test", TOKEN)
    client._monitoring = httpx.Client(transport=httpx.MockTransport(answer))
    st = SimpleNamespace(client=client, status="connected", policy=SimpleNamespace(thanos_url="https://thanos.example.test"),
                         usage_findings=[])
    return thanos.ThanosQuerier(SimpleNamespace(snapshot=lambda cid: st)), client


def test_the_querier_error_is_kept_and_the_token_taken_out():
    """docs/02, "Client rules": the token "redacted from every error message before it is truncated" (#420). A proxy that
    echoes the request's Authorization header in its error must not put the token into the plan, the sweep's detail or a log."""
    body = {"status": "error", "errorType": "timeout", "error": f"query timed out; request had Authorization: Bearer {TOKEN}"}
    q, client = _querier(lambda request: httpx.Response(503, json=body))
    try:
        with pytest.raises(usage.MetricsUnavailable) as caught:
            q.query("c", "up")
    finally:
        client.close()
    text = str(caught.value)
    assert TOKEN not in text and TOKEN[:8] not in text
    assert "answered 503: timeout: query timed out" in text


def test_warnings_are_kept_and_the_token_taken_out():
    body = {"status": "success", "data": {"resultType": "vector", "result": []}, "warnings": [f"store said {TOKEN}"]}
    q, client = _querier(lambda request: httpx.Response(200, json=body))
    try:
        with pytest.raises(usage.MetricsUnavailable) as caught:
            q.query("c", "up")
    finally:
        client.close()
    assert "warned" in str(caught.value) and TOKEN not in str(caught.value)


@pytest.mark.parametrize("status,body", [
    (503, {"status": "success", "data": {"resultType": "vector", "result": []}}),
    (200, {"status": "success", "data": {"resultType": "vector", "result": [None]}}),
    (200, {"status": "success", "data": {"resultType": "vector", "result": [{"metric": []}]}}),
    (200, {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {"namespace": "ns"}}]}}),
    (200, {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {"namespace": "ns"}, "value": [0, 1]}]}}),
])
def test_only_a_2xx_and_well_formed_vector_is_an_answer(status, body):
    """The Prometheus HTTP API (read 2026-11-25): "Every successful API request returns a 2xx status code"; an instant
    vector member is {"metric": {...}, "value": [<unix_time>, "<sample_value>"]}."""
    with pytest.raises(usage.MetricsUnavailable):
        thanos.parse_answer("c", status, body)


def test_a_broken_vector_member_is_unavailable_not_a_crash():
    """Before: a member that is not an object reached _assemble, whose AttributeError the plan does not catch (a 500)."""
    class Broken:
        def query(self, cluster_id, promql, at=None):
            return thanos.parse_answer(cluster_id, 200, {"status": "success", "data": {"resultType": "vector", "result": [None]}})
    assert usage.PromUsage(Broken()).namespace("c", "ns").state == "unavailable"


def test_route_discovery_follows_a_replaced_cluster_client():
    reader = thanos.ThanosQuerier(Mock())

    def client(host):
        c = Mock()
        c.get.return_value = {"spec": {"host": host}}
        return c
    first, second = client("a.example"), client("b.example")
    assert reader._base_url("c", None, first) == "https://a.example"
    assert reader._base_url("c", None, second) == "https://b.example"


# --------------------------------------------------------------------------- the live read and its deadline (usage.py)

class Slow:
    def __init__(self, seconds):
        self.seconds, self.release = seconds, threading.Event()

    def query(self, *args):
        self.release.wait(self.seconds)
        return []


def test_one_deadline_for_the_whole_live_read(monkeypatch):
    """docs/02: "one live query, with a 10-second timeout. If Thanos cannot answer, the plan carries usage: unavailable"."""
    monkeypatch.setattr(usage, "LIVE_TIMEOUT_SECONDS", 0.1)
    slow = Slow(2)
    started = time.monotonic()
    try:
        answer = usage.PromUsage(slow).namespace("c", "ns")
    finally:
        slow.release.set()
    assert answer.state == "unavailable" and "within 0.1 seconds" in answer.reason
    assert time.monotonic() - started < 1


def test_the_sweep_has_a_deadline_per_batch(monkeypatch):
    monkeypatch.setattr(usage, "SWEEP_TIMEOUT_SECONDS", 0.1)
    slow = Slow(2)
    try:
        with pytest.raises(usage.MetricsUnavailable, match="within 0.1 seconds"):
            usage.PromUsage(slow).cluster("c", idle_days=14, ceiling=.85, at=datetime.now(timezone.utc))
    finally:
        slow.release.set()


def test_the_selector_takes_a_dns_label_only():
    metrics = FakeMetrics()
    with pytest.raises(ValueError):
        usage.PromUsage(metrics).namespace("c", 'x"} or vector(1) #')
    assert metrics.calls == []


def test_a_wall_clock_step_does_not_stretch_the_cache(monkeypatch):
    wall, elapsed = [10_000.], [100.]
    monkeypatch.setattr(usage.time, "monotonic", lambda: elapsed[0])
    metrics = FakeMetrics({"ns": Fake()})
    reader = usage.PromUsage(metrics, clock=lambda: wall[0])
    assert reader.namespace("c", "ns").state == "ok"
    elapsed[0] += 600
    wall[0] -= 60
    metrics.fail = "offline"
    assert reader.namespace("c", "ns").state == "unavailable"


def test_a_namespace_with_no_pod_running_now_keeps_its_14_days():
    """A guard on reviewer 1's Medium 5, which head passes: the current figure is one figure, not the window. With p95 and
    peak known the state is ok and `now` is shown as a dash, never as zero."""
    answer = usage.PromUsage(FakeMetrics({"ns": Fake(cpu=(None, 1., 1., 1., None))})).namespace("c", "ns")
    assert answer.state == "ok" and answer.cpu.now is None
    view, _ = usage.plan_usage(answer, {"requests.cpu": "1"}, {"requests.cpu": "2"})
    assert view["cpu"]["now"] is None and view["cpu"]["peak"] == 1000


def test_the_ratio_fact_keeps_full_precision_at_the_threshold():
    answer = usage.PromUsage(FakeMetrics({"ns": Fake()})).namespace("c", "ns")
    _, facts = usage.plan_usage(answer, {"requests.cpu": "1"}, {"requests.cpu": "3.0004"})
    assert facts["requestToPeakRatio"] > 3


def test_coverage_under_80_percent_is_never_shown_as_80():
    view, _ = usage.plan_usage(usage.PromUsage(FakeMetrics({"ns": Fake(steps=3225)})).namespace("c", "ns"), {}, {})
    assert view["coverage"] < .8 and "in 80%" not in view["reason"] and "79.99%" in view["reason"]


def test_hours_near_the_quota_count_against_the_whole_window():
    """docs/03, "Hours near the quota": sum_over_time(... > bool ...)[14d:1h]; "insufficient-data: under 80% hourly coverage"."""
    expression = usage.sweep_queries(7, .95)["quota.hoursAtCeiling"]
    assert expression.startswith("(sum_over_time(") and "/ 336)" in expression
    assert "count_over_time(" in expression and ">= 269" in expression


# --------------------------------------------------------------------------- the sweep and the list (sweep.py, verdicts.py)

def test_an_unpopulated_quota_status_is_no_used_quantity():
    quota = {"metadata": {"namespace": "ns"}, "spec": {"hard": {"requests.cpu": "1"}}}
    ns = {"metadata": {"name": "ns", "labels": {"cmapi.net/managed": "true"}}}
    cache = SimpleNamespace(all=lambda kind: [quota] if kind == "ResourceQuota" else [ns])
    assert quota_now(cache)["ns"][0]["cpu"] is None


def test_with_no_source_a_stored_verdict_is_not_served():
    """docs/18, usage.source none: "every Quotas row says insufficient data, and why"."""
    view = row_verdict((date.today(), [Verdict("cpu", "quota-tight", "risk", "tight")]), False)
    assert view["verdict"] == "insufficient-data" and view["verdictDay"] is None and "No usage source" in view["verdictReason"]


def test_the_retention_runs_with_no_usage_source(monkeypatch):
    from importlib import import_module
    job_module = import_module("cmapi.jobs.usage_sweep")
    repo, jobs = Mock(), Mock()
    monkeypatch.setattr(job_module, "VerdictRepo", lambda s: repo, raising=False)
    monkeypatch.setattr(job_module, "JobRepo", lambda s: jobs)
    job_module.usage_sweep(SimpleNamespace(usage=usage.NoUsage()), Mock(), SimpleNamespace(payload={}))
    repo.prune.assert_called_once_with(datetime.now(timezone.utc).date())
    jobs.enqueue.assert_called_once_with("usage_sweep", delay=86_400, payload={"every": 86_400})


# --------------------------------------------------------------------------- the plan and its approval (pipeline.py, approvals.py)

def test_the_stored_plan_holds_the_facts_and_no_usage_figures():
    """docs/01, "Is this quota change on an existing namespace justified?": "Stored? No"; "Namespace usage samples are never
    stored". The facts (usage, requestToPeakRatio) stay: the approval was decided from them."""
    plan = SimpleNamespace(files={}, prev={}, changes={}, facts={"usage": "ok", "requestToPeakRatio": 3.7},
                           capacity=SimpleNamespace(status="fits", fresh=True, detail={}), spec=None, findings=[],
                           beyond_tier=None, usage={"cpu": {"now": 123}}, adoption=None)
    stored = Plan.stored(plan)
    assert "usage" not in stored and stored["facts"] == {"usage": "ok", "requestToPeakRatio": 3.7}


def test_a_site_policy_without_the_rule_still_gets_the_platform_approval():
    rules = {"defaults": {"required": 0, "group": "approver-platform"},
             "environments": {"dev": {"change": 1, "group": "approver-dev"}}}
    result = ApprovalRules(rules).decide({"environment": "dev", "action": "update", "usage": "unavailable"})
    assert {s.group: s.count for s in result.slots} == {"approver-dev": 1, "approver-platform": 1}


def test_every_shipped_policy_adds_exactly_one_platform_approval_when_usage_is_unavailable():
    """A guard, which head passes: each of the nine shipped rule sets keeps its slots and adds one approver-platform."""
    root = Path(__file__).resolve().parents[3]
    files = [path for folder in ("cmapi/src", "examples", "deploy/helm") for path in (root / folder).rglob("approval-rules.yaml")]
    rulesets = [yaml.safe_load(f.read_text()) for f in files]
    for env in ("kind", "crc"):
        config = root / f"deploy/manifests/environments/{env}/20-config.yaml"
        rulesets.extend(yaml.safe_load(doc["data"]["approval-rules.yaml"])
                        for doc in yaml.safe_load_all(config.read_text()) if doc and "approval-rules.yaml" in doc.get("data", {}))
    assert len(rulesets) == 9
    for rules in rulesets:
        engine = ApprovalRules(rules)
        for env in rules["environments"]:
            for name in ("normal-ns", "critical-ns", "temp-ns"):
                facts = dict(environment=env, namespace=name, plugin="namespaces", action="update", quotaIncreasePct=105)
                before = {s.group: s.count for s in engine.decide(facts).slots}
                before["approver-platform"] = before.get("approver-platform", 0) + 1
                assert {s.group: s.count for s in engine.decide({**facts, "usage": "unavailable"}).slots} == before
