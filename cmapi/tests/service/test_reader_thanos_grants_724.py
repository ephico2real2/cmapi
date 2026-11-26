"""#724: the reader reads each cluster's Thanos Querier by cmapi's own grants, never by one to every user, and the import
check says when it does not.

The owner, 2026-11-26: "cmapi must grant it own permission to the pods with or without openshift coo", and "when we onboard
a cluster to cmapi. The service account must have right to the remote cluster thanos." On CRC, another project's
ClusterRoleBinding binds cluster-monitoring-view to system:authenticated; cmapi must not depend on it on any cluster.

The baseline (examples/baseline/cmapi-reader-rbac.yaml) grants, in openshift-monitoring alone: get on Route thanos-querier,
the platform's Role cluster-monitoring-metrics-api (identical on cluster-monitoring-operator release-4.18 and release-4.22),
and create localsubjectaccessreviews, which the import check uses to ask the API server whether the reader holds the first
two without system:authenticated. The clusters are real KubeClients over an httpx MockTransport. No database:

    cd cmapi && PYTHONPATH=src:tests/service python -m pytest tests/service/test_reader_thanos_grants_724.py -q -W ignore
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from cmapi.capacity import thanos, usage
from cmapi.capacity.thanos import ROUTE_PATH
from cmapi.core.clients.kube import KubeClient
from cmapi.core.registry import QUERY_READ, READER_IDENTITY, ROUTE_READ, USAGE_FIX, ClusterPolicy, ClusterRegistry
from test_cluster_import_log_456 import capture_registry_logs, import_events  # noqa: F401 - the fixture
from test_registry_survives_419 import Source, good, secret

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "examples/baseline/cmapi-reader-rbac.yaml"
READER = [{"kind": "ServiceAccount", "name": "cmapi-reader", "namespace": "cmapi-system"}]
MONITORING = "openshift-monitoring"
LSAR = f"/apis/authorization.k8s.io/v1/namespaces/{MONITORING}/localsubjectaccessreviews"
ROUTE_ROLE_RULE = {"apiGroups": ["route.openshift.io"], "resources": ["routes"], "resourceNames": ["thanos-querier"], "verbs": ["get"]}
CHECK_ROLE_RULE = {"apiGroups": ["authorization.k8s.io"], "resources": ["localsubjectaccessreviews"], "verbs": ["create"]}


def load(path: Path | str) -> list[dict]:
    text = path.read_text() if isinstance(path, Path) else path
    return [d for d in yaml.safe_load_all(text) if d]


def monitoring_grants(docs: list[dict]) -> dict[tuple[str, str], dict]:
    """The objects in openshift-monitoring, by kind and name, without labels: what they grant, not how they are tagged."""
    out = {}
    for d in docs:
        if d["metadata"].get("namespace") == MONITORING:
            d = deepcopy(d)
            d["metadata"].pop("labels", None)
            out[(d["kind"], d["metadata"]["name"])] = d
    return out


# --------------------------------------------------------------------------- the baseline (manifests)

def test_the_baseline_grants_thanos_in_openshift_monitoring_alone():
    """The reader's own least grant, and no cluster-wide cluster-monitoring-view (#724). Fails on main's baseline, which binds
    cluster-monitoring-view cluster-wide and grants the Route's name in every namespace."""
    docs = load(BASELINE)
    grants = monitoring_grants(docs)
    assert sorted(grants) == [("Role", "cmapi-reader-grant-check"), ("Role", "cmapi-reader-thanos-route"),
                              ("RoleBinding", "cmapi-reader-grant-check"), ("RoleBinding", "cmapi-reader-metrics-api"),
                              ("RoleBinding", "cmapi-reader-thanos-route")]
    _, _, group, _, _, namespace, plural, name = ROUTE_PATH.split("/")
    assert namespace == MONITORING
    assert grants[("Role", "cmapi-reader-thanos-route")]["rules"] == [
        {"apiGroups": [group], "resources": [plural], "resourceNames": [name], "verbs": ["get"]}]
    assert grants[("Role", "cmapi-reader-grant-check")]["rules"] == [CHECK_ROLE_RULE]
    refs = {n: d["roleRef"] for (k, n), d in grants.items() if k == "RoleBinding"}
    assert refs == {
        "cmapi-reader-thanos-route": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "cmapi-reader-thanos-route"},
        "cmapi-reader-metrics-api": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "cluster-monitoring-metrics-api"},
        "cmapi-reader-grant-check": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "cmapi-reader-grant-check"}}
    assert all(d["subjects"] == READER for (k, _), d in grants.items() if k == "RoleBinding")
    cluster_bindings = [d for d in docs if d["kind"] == "ClusterRoleBinding"]
    assert [d["roleRef"]["name"] for d in cluster_bindings if d["roleRef"]["name"].startswith("cluster-monitoring")] == []
    # Nothing cluster-wide reaches the monitoring stack: no Route, no prometheuses, no review of others' access.
    cluster_rules = [r for d in docs if d["kind"] == "ClusterRole" for r in d["rules"]]
    assert not [r for r in cluster_rules if {"route.openshift.io", "monitoring.coreos.com", "authorization.k8s.io"} & set(r["apiGroups"])]


def test_the_baseline_keeps_every_other_grant():
    """Only the monitoring grant changed: the reader's ClusterRole keeps each other rule, and the token renewal stays."""
    docs = load(BASELINE)
    role = next(d for d in docs if d["kind"] == "ClusterRole" and d["metadata"]["name"] == "cmapi-reader")
    groups = [g for r in role["rules"] for g in r["apiGroups"]]
    assert groups == ["", "", "rbac.authorization.k8s.io", "security.openshift.io", "user.openshift.io", "quota.openshift.io",
                      "redhatcop.redhat.io", "config.openshift.io", "argoproj.io", "wgpolicyk8s.io", "policies.kyverno.io",
                      "kyverno.io"]
    names = {(d["kind"], d["metadata"]["name"]) for d in docs}
    assert {("ClusterRoleBinding", "cmapi-reader"), ("Role", "cmapi-reader-renew"), ("RoleBinding", "cmapi-reader-renew"),
            ("ClusterRole", "cmapi-token-issuer")} <= names


def test_crc_and_the_design_grant_what_the_baseline_grants():
    """One grant in three places: the baseline, CRC's reader and docs/02's "What the baseline creates on every cluster"."""
    baseline = monitoring_grants(load(BASELINE))
    crc = monitoring_grants(load(ROOT / "deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml"))
    design = (ROOT / "docs/02-technical-design-v2.md").read_text()
    block = design.split("**What the baseline creates on every cluster.", 1)[1].split("```yaml", 1)[1].split("```", 1)[0]
    assert crc == baseline
    assert monitoring_grants(load(block)) == baseline
    assert "cluster-monitoring-view" not in block


def test_kind_has_no_openshift_monitoring_and_no_grant_for_it():
    """kind runs no OpenShift monitoring and its instance reads usage.source none (environments/kind/20-config.yaml), so its
    reader holds no monitoring grant and the import check does not run there."""
    docs = load(ROOT / "deploy/kind-import/reader.yaml")
    assert monitoring_grants(docs) == {}
    assert not [r for d in docs if d["kind"] == "ClusterRole" for r in d["rules"]
                if {"route.openshift.io", "monitoring.coreos.com"} & set(r["apiGroups"])]
    config = (ROOT / "deploy/manifests/environments/kind/20-config.yaml").read_text()
    assert '"source":"none"' in config.replace(" ", "")


def test_the_check_reviews_what_the_baseline_grants():
    """The registry's reviews name the Route the baseline's Role names, and the query's rule of the platform's Role."""
    attributes, grant = ROUTE_READ
    assert {"apiGroups": [attributes["group"]], "resources": [attributes["resource"]], "resourceNames": [attributes["name"]],
            "verbs": [attributes["verb"]]} == ROUTE_ROLE_RULE
    assert "cmapi-reader-thanos-route" in grant
    attributes, grant = QUERY_READ
    # cluster-monitoring-operator release-4.18 and release-4.22, assets/thanos-querier/kube-rbac-proxy-web-secret.yaml.
    assert attributes == {"verb": "get", "group": "monitoring.coreos.com", "resource": "prometheuses", "subresource": "api",
                          "name": "k8s"}
    assert "cluster-monitoring-metrics-api" in grant


# --------------------------------------------------------------------------- the import check (core/registry.py)

class Cluster:
    """An OpenShift API server over MockTransport whose RBAC allows the reader `held` (route, query, check), and allows every
    review that names system:authenticated, as CRC's ClusterRoleBinding of cluster-monitoring-view to everyone does."""

    def __init__(self, held=("route", "query", "check"), monitoring=True):
        self.held, self.monitoring, self.reviews = set(held), monitoring, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p == "/apis/monitoring.coreos.com/v1":
            return httpx.Response(200 if self.monitoring else 404, json={"kind": "APIResourceList"})
        if p == LSAR and request.method == "POST":
            if "check" not in self.held:
                return httpx.Response(403, json={"kind": "Status", "reason": "Forbidden"})
            body = json.loads(request.content)
            self.reviews.append(body)
            spec, attrs = body["spec"], body["spec"]["resourceAttributes"]
            what = "route" if attrs.get("resource") == "routes" else "query"
            allowed = what in self.held or "system:authenticated" in spec["groups"]
            return httpx.Response(201, json={**body, "status": {"allowed": allowed}})
        return good(request)


def registry_for(cluster: Cluster, *, usage_grants=True, thanos_url=None) -> ClusterRegistry:
    def factory(cluster_id, api_url, token, trust, *, insecure=False):
        c = KubeClient(cluster_id, api_url, token, trust, insecure=insecure)
        c._client = httpx.Client(base_url=c.api_url, headers=c._client.headers, transport=httpx.MockTransport(cluster))
        return c
    policy = ClusterPolicy("ONE", "rnd", "clusters/ONE", thanos_url=thanos_url)
    return ClusterRegistry({"ONE": policy}, Source([secret("ONE")]), client_factory=factory, start_caches=False,
                           usage_grants=usage_grants)


def test_with_the_grants_the_cluster_has_no_finding():
    cluster = Cluster()
    reg = registry_for(cluster)
    reg.refresh()
    st = reg.get("ONE")
    assert (st.status, st.findings, st.usage_findings) == ("connected", [], [])
    # Each review is the reader's, in openshift-monitoring, with its ServiceAccount groups and never system:authenticated.
    assert [r["spec"]["resourceAttributes"] for r in cluster.reviews] == [
        {**ROUTE_READ[0], "namespace": MONITORING}, {**QUERY_READ[0], "namespace": MONITORING}]
    for r in cluster.reviews:
        assert r["kind"] == "LocalSubjectAccessReview" and r["metadata"]["namespace"] == MONITORING
        assert r["spec"]["user"] == READER_IDENTITY
        assert r["spec"]["groups"] == ["system:serviceaccounts", "system:serviceaccounts:cmapi-system"]


@pytest.mark.parametrize("held,named", [
    pytest.param(("query", "check"), ["cmapi-reader-thanos-route"], id="no Route grant"),
    pytest.param(("route", "check"), ["cluster-monitoring-metrics-api"], id="no query grant"),
    pytest.param(("check",), ["cmapi-reader-thanos-route", "cluster-monitoring-metrics-api"], id="neither"),
])
def test_a_missing_grant_is_a_finding_on_a_connected_cluster(held, named):
    """Both are allowed to every user here, as on CRC: only cmapi's own grant counts. The import is not refused: the cluster
    stays connected and read, and its usage is unavailable with the finding as the reason."""
    reg = registry_for(Cluster(held=held))
    reg.refresh()
    st = reg.get("ONE")
    assert st.status == "connected" and st.cache is not None
    assert st.findings == st.usage_findings and len(st.findings) == len(named)
    for finding, grant in zip(st.findings, named):
        assert finding.startswith("usage: missing grant in openshift-monitoring: ") and grant in finding
    view = st.view()
    assert view["status"] == "connected"
    assert view["findingDetails"] == [{"finding": f, "fix": USAGE_FIX} for f in st.findings]


def test_a_reader_that_may_not_ask_has_a_finding_not_a_pass():
    """Without create localsubjectaccessreviews the grants are unknown, and unknown is not taken as held."""
    reg = registry_for(Cluster(held=("route", "query")))
    reg.refresh()
    st = reg.get("ONE")
    assert st.status == "connected"
    assert st.usage_findings == ["usage: the reader's grants could not be checked: missing grant in openshift-monitoring: "
                                 "create localsubjectaccessreviews (Role and RoleBinding cmapi-reader-grant-check)"]


def test_a_cluster_without_openshift_monitoring_says_so():
    """The kind cluster CRC's instance imports serves no monitoring.coreos.com/v1: one finding, and no review is asked."""
    cluster = Cluster(monitoring=False)
    reg = registry_for(cluster)
    reg.refresh()
    st = reg.get("ONE")
    assert st.usage_findings == ["usage: the cluster serves no monitoring.coreos.com/v1, so it has no OpenShift monitoring"]
    assert cluster.reviews == []
    # No grant fixes it, so the fix does not ask for one.
    assert st.view()["findingDetails"][0]["fix"].startswith("No grant can fix this")


def test_with_a_thanos_url_the_route_is_not_reviewed():
    """capacity/thanos.py reads the Route only when clusters.yaml has no thanosUrl."""
    cluster = Cluster(held=("query", "check"))
    reg = registry_for(cluster, thanos_url="https://thanos.example.test")
    reg.refresh()
    assert reg.get("ONE").findings == []
    assert [r["spec"]["resourceAttributes"]["resource"] for r in cluster.reviews] == ["prometheuses"]


def test_without_live_usage_nothing_is_asked():
    """usage.source none: the import check is the six checks as before, with no call to the monitoring stack."""
    calls = []
    cluster = Cluster(held=())

    def recording(request):
        calls.append(request.url.path)
        return cluster(request)
    reg = registry_for(recording, usage_grants=False)
    reg.refresh()
    assert (reg.get("ONE").status, reg.get("ONE").findings) == ("connected", [])
    assert calls == ["/version", "/apis/user.openshift.io/v1/users/~", "/api/v1/namespaces"]


def test_a_probe_rechecks_the_grants():
    """POST /api/v1/clusters/{id}:probe runs the same check: a grant applied after the import clears the finding."""
    cluster = Cluster(held=("check",))
    reg = registry_for(cluster)
    reg.refresh()
    assert len(reg.get("ONE").usage_findings) == 2
    cluster.held |= {"route", "query"}
    row = reg.probe("ONE")
    assert (row["status"], row["findings"]) == ("connected", [])
    assert reg.get("ONE").usage_findings == []


def test_a_usage_finding_is_logged_as_a_warning_from_the_first_import(capture_registry_logs):
    """#456 logs no event for a first healthy import; a connected cluster without its grants is not healthy. Applying the grant
    logs the recovery as info, with no finding."""
    cluster = Cluster(held=("check",))
    reg = registry_for(cluster)
    with capture_registry_logs() as events:
        reg.refresh()
        reg.refresh()
        cluster.held |= {"route", "query"}
        reg.refresh()
    found = import_events(events)
    assert [(e["log_level"], e["status"], len(e["findings"])) for e in found] == [("warning", "connected", 2), ("info", "connected", 0)]


# --------------------------------------------------------------------------- the usage (capacity/thanos.py)

def test_the_usage_of_a_cluster_with_a_finding_is_unavailable_with_its_reason():
    """The plan's live usage says why, and the Querier is not asked: an answer allowed only by a grant to everyone is not
    used. docs/02: "the plan carries usage: unavailable"."""
    asked = []
    client = SimpleNamespace(monitoring_get=lambda *a: asked.append(a), get=lambda *a: asked.append(a))
    finding = "usage: missing grant in openshift-monitoring: get on prometheuses/api k8s (...)"
    st = SimpleNamespace(client=client, status="connected", policy=None, usage_findings=[finding])
    querier = thanos.ThanosQuerier(SimpleNamespace(snapshot=lambda cid: st))
    with pytest.raises(usage.MetricsUnavailable, match="missing grant in openshift-monitoring"):
        querier.query("ONE", "vector(1)")
    got = usage.PromUsage(querier).namespace("ONE", "payments-dev")
    assert got.state == "unavailable" and finding in got.reason
    assert asked == []


def test_the_source_name_is_read_once_for_the_registry_and_the_source():
    assert usage.usage_source_name(None) == "none"
    assert usage.usage_source_name({"usage": {"source": "thanos"}}) == "thanos"
    with pytest.raises(ValueError, match="usage.source is one of"):
        usage.usage_source_name({"usage": {"source": "prometheus"}})


@pytest.mark.parametrize("source,asked", [("thanos", True), ("none", False)])
def test_the_instance_asks_for_the_grants_when_it_reads_usage(test_config, tmp_path, monkeypatch, source, asked):
    """build_context gives the registry usage_grants from capacity.yaml usage.source, before anything else is built on it."""
    import shutil

    import cmapi.core.context as context_mod
    from cmapi.settings import Settings
    from conftest import DB_URL

    config = tmp_path / "config"
    shutil.copytree(test_config, config)
    with (config / "capacity.yaml").open("a") as f:
        f.write(f"usage: {{source: {source}}}\n")
    seen = {}

    class Built(Exception):
        pass

    def registry(*args, **kwargs):
        seen.update(kwargs)
        raise Built
    monkeypatch.setattr(context_mod, "ClusterRegistry", registry)
    s = Settings(config_dir=config, database_url=DB_URL, git_provider="gitea", git_url="https://git.test/api/v1", git_token="t",
                 cursor_key="k", link_key="l", metrics_port=0, imports_dir=None, kube_token_file=Path("/nonexistent"),
                 kube_ca_file=Path("/nonexistent"))
    with pytest.raises(Built):
        context_mod.build_context(s, start_registry=False, import_source=Source([]))
    assert seen["usage_grants"] is asked


@pytest.mark.parametrize("mode", ["evaluation", "http", "timeout", "malformed"])
def test_inconclusive_review_preserves_reads_and_recovers(mode):
    healthy = Cluster()
    transient = True

    def answer(request):
        if transient and request.url.path == LSAR:
            if mode == "evaluation":
                return httpx.Response(201, json={"status": {"allowed": False, "evaluationError": "authorizer timeout"}})
            if mode == "timeout":
                raise httpx.ReadTimeout("authorizer timeout")
            if mode == "malformed":
                return httpx.Response(201, json={"status": {}})
            return httpx.Response(503)
        return healthy(request)

    reg = registry_for(answer)
    reg.refresh()
    row = reg.get("ONE").view()
    assert row["status"] == "connected"
    assert reg.cache("ONE") is not None and reg.writable("ONE").policy.writes
    detail, = row["findingDetails"]
    assert "could not be checked" in detail["finding"]
    assert "probe" in detail["fix"] and "Apply" not in detail["fix"]
    transient = False
    assert reg.probe("ONE")["findings"] == []


def test_explicit_allow_survives_an_unrelated_evaluation_error():
    def answer(request):
        if request.url.path == LSAR:
            return httpx.Response(201, json={"status": {"allowed": True, "evaluationError": "another Role is missing"}})
        return Cluster()(request)

    reg = registry_for(answer)
    reg.refresh()
    assert (reg.get("ONE").status, reg.get("ONE").findings) == ("connected", [])


def test_probe_finding_takes_precedence_over_cached_usage(monkeypatch):
    cluster = Cluster()
    reg = registry_for(cluster, thanos_url="https://thanos.example.test")
    reg.refresh()
    live = usage.usage_source({"usage": {"source": "thanos"}}, reg)
    calls = []

    def metrics(*args):
        calls.append(args)
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": []}})

    monkeypatch.setattr(reg.get("ONE").client, "monitoring_get", metrics)
    assert live.namespace("ONE", "payments-dev").state == "insufficient-data"
    assert calls
    calls.clear()
    cluster.held.remove("query")
    row = reg.probe("ONE")
    answer = live.namespace("ONE", "payments-dev")
    assert answer.state == "unavailable" and row["findings"][0] in answer.reason
    assert calls == []


def test_new_client_is_private_until_its_grants_are_checked():
    observed = []
    cluster = Cluster(held=("check",))

    def observe(request):
        if request.url.path == LSAR:
            observed.append(reg.snapshot("ONE").client)
        return cluster(request)

    reg = registry_for(observe)
    starting = []

    def start_nodes(st, client):
        starting.append(reg.snapshot("ONE"))
        return None

    reg.nodes_factory = start_nodes
    reg.refresh()
    assert observed == [None, None]
    assert len(starting) == 1 and starting[0].usage_findings
    st = reg.snapshot("ONE")
    assert st.client is not None and st.usage_findings


def test_a_cached_answer_is_hidden_by_a_finding_and_not_by_a_dropped_client():
    """The cache guard checks the grants alone (#724). A cluster whose client dropped keeps its cached answer for its 10
    minutes, as before #724; a usage finding hides it."""
    st = SimpleNamespace(client=object(), status="connected", policy=None, usage_findings=[])
    querier = thanos.ThanosQuerier(SimpleNamespace(snapshot=lambda cid: st))
    reader = usage.PromUsage(SimpleNamespace(query=lambda *args: []), check_cached=querier.check_grants)
    cached = reader.namespace("ONE", "payments-dev")
    st.client, st.status = None, "unreachable"
    assert reader.namespace("ONE", "payments-dev") is cached
    st.usage_findings = ["usage: missing grant in openshift-monitoring: get on prometheuses/api k8s (...)"]
    hidden = reader.namespace("ONE", "payments-dev")
    assert hidden.state == "unavailable" and st.usage_findings[0] in hidden.reason


def test_a_namespace_is_created_and_its_quota_changed_without_the_grants(test_config, fresh_db, keys, monkeypatch, tmp_path):
    """The whole write path on PostgreSQL, with usage.source thanos and neither grant (#724). docs/02: "Namespace creation and
    placement never call Thanos", and the cluster stays connected: the create is auto-approved and synced with no monitoring
    call. A quota change then carries usage unavailable with the finding as the reason, and the platform approval
    ("If Thanos cannot answer, the plan carries usage: unavailable and the change needs a platform approval")."""
    import shutil

    from conftest import FakeKube, build_world
    from test_flow import NS, OLA, auth, run_jobs

    config = tmp_path / "config"
    shutil.copytree(test_config, config)
    with (config / "capacity.yaml").open("a") as f:
        f.write("usage: {source: thanos}\n")
    served, monitoring = FakeKube.served, []
    monkeypatch.setattr(FakeKube, "served", lambda self, gv: gv == "monitoring.coreos.com/v1" or served(self, gv))
    monkeypatch.setattr(FakeKube, "access_review", lambda self, *args: False)
    monkeypatch.setattr(FakeKube, "monitoring_get", lambda self, *args: monitoring.append(args))
    monkeypatch.setattr(FakeKube, "get", lambda self, path: monitoring.append(path))
    with build_world(config, keys, monkeypatch) as (api, ctx, git, kube, *_):
        st = ctx.registry.get("CRC")
        assert st.status == "connected" and len(st.usage_findings) == 2
        h = auth(keys, "ola", **OLA)
        r = api.post("/api/v1/clusters/CRC/namespaces", json=NS, headers=h)
        assert r.status_code == 202, r.text
        assert r.json()["status"] == "approved"
        run_jobs(ctx)
        assert api.get(f"/api/v1/requests/{r.json()['requestId']}", headers=h).json()["status"] == "synced"
        assert "Namespace//payments-dev" in kube.applied
        assert monitoring == []
        ns = api.get("/api/v1/clusters/CRC/namespaces/payments-dev", headers=h)
        assert ns.status_code == 200, ns.text
        etag = {"If-Match": ns.json()["etag"]}
        plan = api.patch("/api/v1/clusters/CRC/namespaces/payments-dev?dryRun=true", json={"tier": "medium"},
                         headers={**auth(keys, "ola", **OLA), **etag})
        assert plan.status_code == 200, plan.text
        assert plan.json()["usage"]["state"] == "unavailable" and st.usage_findings[0] in plan.json()["usage"]["reason"]
        change = api.patch("/api/v1/clusters/CRC/namespaces/payments-dev", json={"tier": "medium"},
                           headers={**auth(keys, "ola", **OLA), **etag})
        assert change.status_code == 202, change.text
        assert change.json()["status"] == "pending_approval"
        slots = change.json()["approval"]["slots"]
        assert {"group": "approver-platform", "count": 1, "reason": "Live usage unavailable"} in slots
        assert monitoring == []
