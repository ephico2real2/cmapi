"""Exercise the recurring job against stub Kubernetes APIs. No database, cluster or listening socket."""
import base64
import json
import shutil
import subprocess
from copy import copy, deepcopy
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import yaml

from cmapi.core.clients.kube import KubeClient
from cmapi.core.config import ConfigError, load_instance
from cmapi.core.registry import ClusterPolicy, ClusterRegistry, HubImportSource, READER_IDENTITY, load_policies

ROOT = Path(__file__).resolve().parents[3]
START = 1_800_000_000


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def encoded(value):
    return base64.b64encode(value.encode()).decode()


def jwt(iat, exp, subject=READER_IDENTITY, signature="synthetic-signature"):
    body = json.dumps({"sub": subject, "iat": iat, "exp": exp}).encode()
    return "stub." + base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + signature


@pytest.mark.parametrize("value,seconds", [("7d", 604800), ("168h", 604800), ("90m", 5400), ("600s", 600)])
def test_duration(value, seconds):
    from cmapi.core.cluster_tokens import duration_seconds
    assert duration_seconds(value) == seconds


@pytest.mark.parametrize("value", [1, True, "1", "1w", "-1h", "3.5h", "1 d", "2hours", None])
def test_duration_refusals(value):
    from cmapi.core.cluster_tokens import duration_seconds
    with pytest.raises(ValueError):
        duration_seconds(value)


@pytest.mark.parametrize("values", [
    {"duration": "599s"}, {"duration": "1h", "renewBefore": "4m"},
    {"duration": "1h", "renewBefore": "1h"}, {"duration": "1h", "renewBeforePercentage": 8},
    {"renewBefore": "1h", "renewBeforePercentage": 20}, {"renewBeforePercentage": True},
    {"renewBeforePercentage": 0}, {"renewBeforePercentage": 100}, {"renewBeforePercentage": 50.5},
    {"unexpected": 1}, None,
])
@pytest.mark.parametrize("scope", ["instance", "cluster"])
def test_startup_refuses_invalid_policy(tmp_path, values, scope):
    config = tmp_path / "config"
    shutil.copytree(ROOT / "examples/local/config", config)
    if scope == "instance":
        path = config / "instance.yaml"
        raw = yaml.safe_load(path.read_text())
        raw["instance"]["clusterTokens"] = values
        path.write_text(yaml.safe_dump(raw))
        with pytest.raises(ConfigError, match="clusterTokens"):
            load_instance(config, config / "metadata-keys.yaml")
    else:
        path = config / "clusters.yaml"
        path.write_text(yaml.safe_dump({"clusters": {"TEST": {"environment": "rnd", "clusterTokens": values}}}))
        with pytest.raises(ConfigError, match="TEST.clusterTokens"):
            load_policies(path, {"rnd"})


def test_cluster_inheritance(tmp_path):
    from cmapi.core.cluster_tokens import TokenPolicy
    path = tmp_path / "clusters.yaml"
    path.write_text("clusters:\n  A: {environment: rnd}\n  B: {environment: rnd, clusterTokens: {renewBefore: 15m}}")
    policy = TokenPolicy().override({"duration": "1h", "renewBeforePercentage": 30})
    clusters = load_policies(path, {"rnd"}, policy)
    assert clusters["A"].cluster_tokens == policy
    assert clusters["B"].cluster_tokens.window(3600) == 900
    assert clusters["B"].cluster_tokens.duration == 3600


class Endpoints:
    def __init__(self, tmp_path, monkeypatch, values, lifetime):
        from cmapi.core.cluster_tokens import TokenPolicy
        self.module = import_module("cmapi.jobs.token_renew")
        self.policy = TokenPolicy().override(values)
        self.defaults = TokenPolicy()
        self.lifetime = lifetime
        self.now = START
        self.old = jwt(START, START + lifetime)
        self.doc = {"metadata": {"name": "import-test", "resourceVersion": "1",
                                 "labels": {"cmapi.net/cluster-id": "TEST", "cmapi.net/secret-type": "cluster"},
                                 "annotations": {"cmapi.net/token-expires-at": stamp(START + lifetime),
                                                 "cmapi.net/managed-by": "cluster-baseline", "keep": "this"}},
                    "data": {"apiUrl": encoded("https://reader.invalid"), "token": encoded(self.old),
                             "extra": encoded("untouched"), "tlsServerName": encoded("cluster.invalid")}}
        self.requests, self.patches, self.grants = [], [], []
        self.trust_modes = []
        self.before_patch = None
        self.status = 201
        self.subject = READER_IDENTITY
        self.reported_skew = 0
        self.logs = Mock()
        self.hub_token = tmp_path / "hub-token"
        self.hub_token.write_text("fixture-hub-first")
        self.source = HubImportSource("https://hub.invalid", self.hub_token, tmp_path / "no-ca", "cmapi-imports")
        self.source.client.close()
        self.source.client = httpx.Client(base_url="https://hub.invalid", transport=httpx.MockTransport(self.hub))
        policy = ClusterPolicy("TEST", "rnd", "TEST", cluster_tokens=self.policy)
        self.registry = ClusterRegistry({"TEST": policy}, self.source, client_factory=self.client, start_caches=False)
        monkeypatch.setattr(self.module, "time", lambda: self.now)
        monkeypatch.setattr(self.module, "log", self.logs)

    def client(self, cid, url, token, trust, *, insecure):
        assert cid == "TEST" and url == "https://reader.invalid"
        assert trust.server_name == "cluster.invalid"
        assert insecure == (trust.source == "insecure")
        self.trust_modes.append(trust.source)
        client = KubeClient(cid, url, token, trust)
        client._client.close()
        client._client = httpx.Client(base_url=url, headers=client._client.headers, transport=httpx.MockTransport(self.spoke))
        return client

    def spoke(self, req):
        assert req.method == "POST" and req.url.path == "/api/v1/namespaces/cmapi-system/serviceaccounts/cmapi-reader/token"
        assert req.headers["Authorization"] == "Bearer " + base64.b64decode(self.doc["data"]["token"]).decode()
        body = json.loads(req.content)
        assert body == {"apiVersion": "authentication.k8s.io/v1", "kind": "TokenRequest",
                        "spec": {"expirationSeconds": self.policy.duration}}
        self.requests.append(body)
        exp = self.now + self.lifetime
        token = jwt(self.now, exp, self.subject, f"synthetic-grant-{len(self.requests)}")
        self.grants.append(token)
        if self.status != 201:
            return httpx.Response(self.status, text=self.old + token)
        return httpx.Response(201, json={"status": {"token": token, "expirationTimestamp": stamp(exp + self.reported_skew)}})

    def hub(self, req):
        assert req.headers["Authorization"] == "Bearer " + self.hub_token.read_text()
        path = "/api/v1/namespaces/cmapi-imports/secrets"
        if req.method == "GET":
            assert req.url.path == path and req.url.params["labelSelector"] == "cmapi.net/secret-type=cluster"
            return httpx.Response(200, json={"items": [self.doc]})
        assert req.method == "PATCH" and req.url.path == path + "/import-test"
        assert req.headers["content-type"] == "application/merge-patch+json"
        patch = json.loads(req.content)
        self.patches.append(patch)
        if self.before_patch:
            self.before_patch()
            self.before_patch = None
        meta = self.doc["metadata"]
        if meta["resourceVersion"] != patch["metadata"]["resourceVersion"]:
            return httpx.Response(409, text=self.old + self.grants[-1])
        self.doc["data"].update(patch["data"])
        meta["annotations"].update(patch["metadata"]["annotations"])
        meta["resourceVersion"] = str(int(meta["resourceVersion"]) + 1)
        return httpx.Response(200, json=self.doc)

    def scan(self):
        return self.module.renew_imports(self.registry, self.defaults)

    def no_credentials_logged(self):
        for call in self.logs.mock_calls:
            for token in [self.old, *self.grants]:
                assert token not in str(call) and encoded(token) not in str(call)


@pytest.fixture
def endpoints(tmp_path, monkeypatch):
    opened = []
    def make(values=None, lifetime=3600):
        api = Endpoints(tmp_path, monkeypatch, values or {}, lifetime)
        opened.append(api.source.client)
        return api
    yield make
    for client in opened:
        client.close()


@pytest.mark.parametrize("values,lifetime,window", [
    ({}, 604800, 120960), ({"duration": "1h"}, 3600, 720), ({"duration": "7d"}, 3600, 720),
    ({"duration": "1h", "renewBefore": "10m"}, 3600, 600),
])
def test_renews_exactly_when_due(endpoints, values, lifetime, window):
    api = endpoints(values, lifetime)
    original = deepcopy(api.doc)
    api.now = START + lifetime - window - 1
    assert not api.scan() and not api.requests
    api.now += 1
    api.hub_token.write_text("fixture-hub-rotated")
    assert not api.scan()
    [patch] = api.patches
    token = encoded(api.grants[0])
    expiry = stamp(api.now + lifetime)
    assert patch == {"metadata": {"resourceVersion": "1", "annotations": {"cmapi.net/token-expires-at": expiry}},
                     "data": {"token": token}}
    original["metadata"]["resourceVersion"] = "2"
    original["metadata"]["annotations"]["cmapi.net/token-expires-at"] = expiry
    original["data"]["token"] = token
    assert api.doc == original
    api.logs.info.assert_called_with("cluster_token_renewed", cluster_id="TEST", expires_at=expiry)
    assert not api.scan() and len(api.requests) == 1
    assert api.trust_modes == ["trusted"]
    api.no_credentials_logged()


@pytest.mark.parametrize("failure", ["issuer", "subject", "expiry", "expired", "insecure"])
def test_failure_preserves_import(endpoints, failure):
    api = endpoints()
    api.now += 3000
    if failure == "issuer":
        api.status = 403
    elif failure == "subject":
        api.subject = "system:serviceaccount:cmapi-system:other"
    elif failure == "expiry":
        api.reported_skew = 1
    elif failure == "insecure":
        api.doc["data"]["insecure"] = encoded("true")
    else:
        api.now = START + api.lifetime
    original = deepcopy(api.doc)
    from cmapi.core.observability import CLUSTER_TOKEN_RENEWALS
    failures = CLUSTER_TOKEN_RENEWALS.labels("TEST", "failure")
    before = failures._value.get()
    assert api.scan() and not api.patches and api.doc == original
    assert failures._value.get() == before + 1
    assert api.logs.warning.call_args.args == ("cluster_token_renew_failed",)
    if failure in ("expired", "insecure"):
        assert not api.requests
    api.no_credentials_logged()


@pytest.mark.parametrize("manual", [True, False], ids=["manual-renewal", "metadata-update"])
def test_conflict_discards_grant_and_rereads(endpoints, manual):
    api = endpoints()
    api.now += 3000
    replacement = jwt(api.now, api.now + 3600, signature="manual")
    def concurrent_write():
        meta = api.doc["metadata"]
        meta["resourceVersion"] = "2"
        meta["annotations"]["other-writer"] = "preserved"
        if manual:
            meta["annotations"]["cmapi.net/token-expires-at"] = stamp(api.now + 3600)
            api.doc["data"]["token"] = encoded(replacement)
    api.before_patch = concurrent_write
    assert api.scan()
    assert api.logs.warning.call_args.kwargs["http_status"] == 409
    assert not api.scan()
    assert api.doc["metadata"]["annotations"]["other-writer"] == "preserved"
    assert api.doc["data"]["token"] != encoded(api.grants[0])
    if manual:
        assert len(api.patches) == 1 and api.doc["data"]["token"] == encoded(replacement)
    else:
        assert api.patches[1]["metadata"]["resourceVersion"] == "2"
        assert api.doc["data"]["token"] == encoded(api.grants[1])
    api.no_credentials_logged()


def test_legacy_and_external_imports(endpoints):
    api = endpoints()
    api.now += 3000
    ann = api.doc["metadata"]["annotations"]
    expiry = ann.pop("cmapi.net/token-expires-at")
    ann.pop("cmapi.net/managed-by")
    assert not api.scan() and not api.requests
    api.logs.info.assert_called_once_with("cluster_token_renew_skipped", cluster_id="TEST", reason="missing expiry annotation")
    ann.update({"cmapi.net/token-expires-at": expiry, "cmapi.net/managed-by": "other"})
    assert not api.scan() and not api.requests and not api.patches


def test_recurring_job_backs_off_and_recovers(endpoints, monkeypatch):
    from cmapi.jobs import HANDLERS, RECURRING
    api = endpoints()
    api.now += 3000
    ctx = SimpleNamespace(registry=api.registry, cfg=SimpleNamespace(cluster_tokens=api.defaults))
    repo = Mock()
    monkeypatch.setattr(api.module, "JobRepo", lambda session: repo)
    job = SimpleNamespace(attempts=1)
    api.status = 503
    for attempt, delay in enumerate([5, 10, 20, 40, 60, 60], 1):
        job.attempts = attempt
        HANDLERS["token_renew"](ctx, None, job)
        assert repo.retry.call_args.args[2] == delay
    api.status = 201
    HANDLERS["token_renew"](ctx, None, job)
    repo.done.assert_called_once_with(job)
    repo.enqueue.assert_called_once_with("token_renew", delay=60, payload={"every": 60})
    assert RECURRING["token_renew"] == 60
    api.no_credentials_logged()


@pytest.mark.parametrize("mode", ["insecure", "caData"])
def test_request_uses_cluster_trust(endpoints, mode):
    from test_crc_reader_import_398 import CA
    api = endpoints()
    api.now += 3000
    if mode == "insecure":
        api.registry.insecure_environments = {"rnd"}
        api.doc["data"]["insecure"] = encoded("true")
    else:
        api.doc["data"]["caData"] = encoded(CA)
    assert not api.scan() and len(api.patches) == 1
    assert api.trust_modes == [mode]


def test_expiry_alert_uses_actual_grant(endpoints):
    from cmapi.core.observability import CLUSTER_TOKEN_EXPIRY, CLUSTER_TOKEN_LIFETIME
    api = endpoints()
    # A certificate/connection problem must not suppress the expiry alert.
    api.doc["data"]["apiUrl"] = encoded("http://invalid")
    api.registry.refresh()
    assert CLUSTER_TOKEN_LIFETIME.labels("TEST")._value.get() == 3600
    assert CLUSTER_TOKEN_EXPIRY.labels("TEST")._value.get() is not None
    del api.doc["metadata"]["annotations"]["cmapi.net/token-expires-at"]
    api.registry.refresh()
    assert not [s for m in CLUSTER_TOKEN_LIFETIME.collect() for s in m.samples if s.labels == {"cluster_id": "TEST"}]


def test_manifests_scope_the_grants_and_render_the_policy():
    chart = ROOT / "deploy/helm/cmapi"
    digest = "sha256:" + "a" * 64
    proc = subprocess.run(["helm", "template", "cmapi", str(chart), "-n", "cmapi", "-f", str(ROOT / "deploy/environments/crc.yaml"),
                           "--set", f"cmapi.digest={digest}", "--set", f"cmapi_portal.digest={digest}", "--set", "trustedCA.certificates=fixture",
                           "--set", "reader.installRenewalRole=true", "--set", "instance.clusterTokens.duration=1h",
                           "--set", "instance.clusterTokens.renewBefore=10m",
                           "--set", "clusters.CRC.clusterTokens.renewBeforePercentage=30"],
                          check=True, capture_output=True, text=True)
    chart_docs = [doc for doc in yaml.safe_load_all(proc.stdout) if doc]

    def load(path):
        return list(yaml.safe_load_all((ROOT / path).read_text()))

    for docs in (chart_docs, load("deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml"),
                 load("deploy/kind-import/reader.yaml"), load("examples/baseline/cmapi-reader-rbac.yaml")):
        role, binding = [d for d in docs if d["metadata"]["name"] == "cmapi-reader-renew"]
        assert role["metadata"]["namespace"] == binding["metadata"]["namespace"] == "cmapi-system"
        assert role["rules"] == [{"apiGroups": [""], "resourceNames": ["cmapi-reader"],
                                  "resources": ["serviceaccounts/token"], "verbs": ["create"]}]
        assert binding["roleRef"]["kind"] == "Role" and binding["roleRef"]["name"] == "cmapi-reader-renew"
        assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "cmapi-reader", "namespace": "cmapi-system"}]
    for docs in (chart_docs, load("deploy/manifests/components/cmapi/10-imports-reader.yaml")):
        role, binding = [d for d in docs if d["metadata"]["name"] == "cmapi-imports-renewer"]
        assert role["metadata"]["namespace"] == binding["metadata"]["namespace"] == "cmapi-imports"
        assert role["rules"] == [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["patch"]}]
        assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "cmapi-worker", "namespace": "cmapi"}]
    for docs in (chart_docs, load("deploy/manifests/environments/crc/50-monitoring.yaml")):
        rule = next(doc for doc in docs if doc["kind"] == "PrometheusRule")
        alert = next(r for g in rule["spec"]["groups"] for r in g["rules"] if r.get("alert") == "CmapiClusterTokenExpiring")
        assert " ".join(alert["expr"].split()) == ('cmapi_cluster_token_expiry_seconds{namespace="cmapi"} <= '
                                                   '0.1 * cmapi_cluster_token_lifetime_seconds{namespace="cmapi"}')
    config = next(doc["data"] for doc in chart_docs if doc["kind"] == "ConfigMap" and "instance.yaml" in doc["data"])
    assert yaml.safe_load(config["instance.yaml"])["instance"]["clusterTokens"] == {"duration": "1h", "renewBefore": "10m"}
    assert yaml.safe_load(config["clusters.yaml"])["clusters"]["CRC"]["clusterTokens"] == {"renewBeforePercentage": 30}


def test_unreadable_claims_do_not_interrupt_registry_discovery(endpoints, monkeypatch):
    from cmapi.core import cluster_tokens
    api = endpoints()
    api.doc["data"]["apiUrl"] = encoded("http://invalid")
    # Simulate the JSON decoder's depth limit without constructing a pathological document.
    decoder = Mock(side_effect=RecursionError)
    monkeypatch.setattr(cluster_tokens, "json", SimpleNamespace(loads=decoder))
    api.registry.refresh()
    assert api.registry.get("TEST").status == "invalid-secret"
    decoder.assert_called_once()


@pytest.mark.parametrize("failure", ["timestamp", "spoke-header", "hub-header", "transport", "hub-transport"])
def test_credential_responses_have_private_diagnostics(endpoints, monkeypatch, failure):
    api = endpoints()
    api.now += 3000
    marker = "private-fixture-value"
    original = api.spoke

    def response(req):
        if failure == "timestamp":
            body = original(req).json()
            body["status"]["expirationTimestamp"] = marker
            return httpx.Response(201, json=body)
        if failure in ("transport", "hub-transport"):
            raise httpx.ReadError(marker)
        return httpx.Response(200, content=b"invalid JSON", headers={"Content-Type": marker})

    if failure.startswith("hub-"):
        monkeypatch.setattr(api.source.client, "request", lambda *a, **kw: response(None))
    else:
        monkeypatch.setattr(api, "spoke", response)
    with pytest.raises((ValueError, RuntimeError)) as error:
        secret = api.source.list()[0]
        api.module._renew(api.registry, api.source, "TEST", secret, api.defaults)
    diagnostic = error.value
    while diagnostic is not None:
        assert marker not in str(diagnostic)
        diagnostic = diagnostic.__cause__ or diagnostic.__context__
    assert not api.patches


def test_two_scans_and_relist_share_a_versioned_import(endpoints, monkeypatch):
    api = endpoints()
    api.now += 3000
    monkeypatch.setattr(api.registry, "_probe", lambda client, trust: ("connected", [], "fixture"))

    def other_worker_and_relist():
        api.before_patch = None
        api.registry.refresh()
        # Each replica has its own registry and HTTP client. Only the simulated API servers share state.
        with httpx.Client(base_url="https://hub.invalid", transport=httpx.MockTransport(api.hub)) as hub_client:
            source = copy(api.source)
            source.client = hub_client
            replica = ClusterRegistry(api.registry.policies, source, client_factory=api.client, start_caches=False)
            assert not api.module.renew_imports(replica, api.defaults)
        api.registry.refresh()

    api.before_patch = other_worker_and_relist
    try:
        assert api.scan()  # the first worker lost the version race
        assert len(api.grants) == 2
        assert [p["metadata"]["resourceVersion"] for p in api.patches] == ["1", "1"]
        assert api.doc["data"]["token"] == encoded(api.grants[1])
        assert api.registry.get("TEST").client._client.headers["Authorization"] == "Bearer " + api.grants[1]
        assert not api.scan() and len(api.patches) == 2
    finally:
        api.registry.stop()


def test_managed_namespace_binding_cannot_expand_the_readers_token_grant():
    docs = list(yaml.safe_load_all((ROOT / "examples/baseline/cmapi-reader-rbac.yaml").read_text()))
    binding = yaml.safe_load((ROOT / "examples/cluster-configs/clusters/OCP_GF15/namespaces/payments-dev/"
                             "token-issuer-rolebinding.yaml").read_text())
    assert binding["subjects"] == [{"kind": "ServiceAccount", "name": "cmapi-reader", "namespace": "cmapi-system"}]
    role = next(d for d in docs if d["kind"] == "ClusterRole" and d["metadata"]["name"] == binding["roleRef"]["name"])
    assert role["rules"] == []  # The reserved plugin binding grants no access in a workload namespace.


def test_documented_baseline_installs_renewal_and_keeps_recovery_commands():
    design = (ROOT / "docs/02-technical-design-v2.md").read_text()
    crc = (ROOT / "docs/13-crc-deployment.md").read_text()
    block = design.split("**What the baseline creates on every cluster.", 1)[1].split("```yaml", 1)[1].split("```", 1)[0]
    def renewal_objects(source):
        return [d for d in yaml.safe_load_all(source) if d and d["metadata"]["name"] == "cmapi-reader-renew"]
    baseline = renewal_objects((ROOT / "examples/baseline/cmapi-reader-rbac.yaml").read_text())
    assert len(baseline) == 2
    assert renewal_objects(block) == baseline
    assert "cmapi is read-only on the hub" not in design
    for guide in (design, crc):
        assert all(term in guide for term in ("deploy/crc-reader-import.sh", "deploy/kind-import/up.sh <checkout>",
                                              "cluster_token_renew_failed", "CmapiClusterTokenExpiring"))
