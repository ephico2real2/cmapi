"""#751, D2: the read that ends a request, in every delivery mode. The live cluster against the full approved plan.

    cd cmapi && PYTHONPATH=src:tests/core python -m pytest tests/core/test_read_plan_751.py -q

The design and its sources: docs/reviews/2026-11-27-issue-751/README.md.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from cmapi.core.plan_read import Unreadable, defaulted_limit, read_plan

NS = "payments-dev"
BASE = f"clusters/CRC/namespaces/{NS}/"
NAMESPACE = {"apiVersion": "v1", "kind": "Namespace",
             "metadata": {"name": NS, "labels": {"cmapi.net/managed": "true", "cmapi.net/team": "payments"},
                          "annotations": {"cmapi.net/team-dl": "payments-team@ephico2real.com",
                                          "argocd.argoproj.io/sync-options": "Prune=confirm,ServerSideApply=true"}}}
QUOTA = {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": f"{NS}-quota", "namespace": NS},
         "spec": {"hard": {"requests.cpu": "2", "requests.memory": "5120Mi", "pods": "20"}}}
CPU = {"apiVersion": "v1", "kind": "LimitRange", "metadata": {"name": f"{NS}-limits-cpu", "namespace": NS},
       "spec": {"limits": [{"type": "Container", "max": {"cpu": "4"}}]}}
BINDING = {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
           "metadata": {"name": "cmapi-token-issuer", "namespace": NS}}


def folder(*docs):
    return {BASE + f"{d['kind'].lower()}-{d['metadata']['name']}.yaml": yaml.safe_dump(d) for d in docs}


class Cluster:
    """The live objects as the API server keeps them: each applied object, plus what the server and controllers add."""

    def __init__(self, *docs):
        self.objects = {}
        for d in docs:
            self.put(copy.deepcopy(d))

    def put(self, doc):
        meta = doc["metadata"]
        ns = None if doc["kind"] == "Namespace" else meta.get("namespace")
        self.objects[(doc["kind"], ns, meta["name"])] = doc

    def get(self, kind, ns, name):
        return self.objects.get((kind, ns, name))


def served(*docs):
    """What a real API server and OpenShift hold after a server-side apply of docs: the label SetDefaults_Namespace adds,
    the SCC annotations, Argo CD's tracking id, the quantities canonicalised and the LimitRange defaults filled in."""
    c = Cluster(*docs)
    ns = c.get("Namespace", None, NS)
    if ns:
        ns["metadata"]["labels"]["kubernetes.io/metadata.name"] = NS
        ns["metadata"]["labels"]["pod-security.kubernetes.io/audit"] = "restricted"
        ns["metadata"]["annotations"]["openshift.io/sa.scc.uid-range"] = "1000660000/10000"
        ns["metadata"]["annotations"]["argocd.argoproj.io/tracking-id"] = "cluster-configs-crc:/Namespace:/payments-dev"
    q = c.get("ResourceQuota", NS, f"{NS}-quota")
    if q:
        q["spec"]["hard"]["requests.memory"] = "5Gi"
    lr = c.get("LimitRange", NS, f"{NS}-limits-cpu")
    if lr:
        lr["spec"]["limits"] = [defaulted_limit(i) for i in lr["spec"]["limits"]]
    return c


def test_a_folder_applied_as_written_matches_whatever_the_server_added():
    files = folder(NAMESPACE, QUOTA, CPU, BINDING)
    found = read_plan(served(NAMESPACE, QUOTA, CPU, BINDING).get, NS, files)
    assert found.ok, [str(d) for d in found.differences]
    assert found.summary() == "1 Namespace, 1 ResourceQuota and 1 LimitRange match the plan, as do 1 RoleBinding"


def test_nothing_applied_names_each_object():
    found = read_plan(Cluster().get, NS, folder(NAMESPACE, QUOTA, CPU))
    assert [str(d) for d in found.differences] == [
        "Namespace/payments-dev: plan 'present', live absent",
        "ResourceQuota/payments-dev-quota: plan 'present', live absent",
        "LimitRange/payments-dev-limits-cpu: plan 'present', live absent"]
    assert not found.only_removals


def test_a_label_the_plan_writes_and_the_cluster_lacks_is_named():
    live = served(NAMESPACE)
    del live.get("Namespace", None, NS)["metadata"]["labels"]["cmapi.net/team"]
    found = read_plan(live.get, NS, folder(NAMESPACE))
    assert [str(d) for d in found.differences] == ["Namespace/payments-dev label cmapi.net/team: plan 'payments', live absent"]


def test_a_key_the_plan_drops_must_go_and_one_that_neither_holds_is_not_the_plans():
    before = copy.deepcopy(NAMESPACE)
    before["metadata"]["labels"]["cmapi.net/cost-center"] = "cc-4410"
    live = served(before)
    live.get("Namespace", None, NS)["metadata"]["labels"]["someone.else/added"] = "x"
    found = read_plan(live.get, NS, folder(NAMESPACE), folder(before))
    assert [str(d) for d in found.differences] == ["Namespace/payments-dev label cmapi.net/cost-center: plan absent, live 'cc-4410'"]


def test_keys_of_the_cluster_are_left_out_even_when_the_plan_drops_them():
    before = copy.deepcopy(NAMESPACE)
    before["metadata"]["annotations"]["kubectl.kubernetes.io/last-applied-configuration"] = "{}"
    live = served(before)
    found = read_plan(live.get, NS, folder(NAMESPACE), folder(before))
    assert found.ok, [str(d) for d in found.differences]
    found = read_plan(live.get, NS, folder(NAMESPACE), folder(before), skip_prefixes=())
    assert [d.field for d in found.differences] == ["annotation kubectl.kubernetes.io/last-applied-configuration"]


def test_quota_hard_values_compare_by_value_in_both_directions():
    live = served(QUOTA)
    live.get("ResourceQuota", NS, f"{NS}-quota")["spec"]["hard"]["limits.cpu"] = "8"
    live.get("ResourceQuota", NS, f"{NS}-quota")["spec"]["hard"]["pods"] = "10"
    found = read_plan(live.get, NS, folder(QUOTA))
    assert [str(d) for d in found.differences] == [
        "ResourceQuota/payments-dev-quota spec.hard.limits.cpu: plan absent, live '8'",
        "ResourceQuota/payments-dev-quota spec.hard.pods: plan '20', live '10'"]


def test_a_limitrange_that_differs_is_named_by_item_and_key():
    live = served(CPU)
    live.get("LimitRange", NS, f"{NS}-limits-cpu")["spec"]["limits"][0]["max"]["cpu"] = "2"
    found = read_plan(live.get, NS, folder(CPU))
    assert "LimitRange/payments-dev-limits-cpu spec.limits[0].max.cpu: plan '4', live '2'" in [str(d) for d in found.differences]


def test_defaulted_limit_is_the_api_servers_rule_for_a_container_item_only():
    assert defaulted_limit({"type": "Container", "max": {"cpu": "4"}, "min": {"memory": "1Mi"}}) == {
        "type": "Container", "max": {"cpu": "4"}, "min": {"memory": "1Mi"}, "default": {"cpu": "4"},
        "defaultRequest": {"cpu": "4", "memory": "1Mi"}, "maxLimitRequestRatio": {}}
    pvc = defaulted_limit({"type": "PersistentVolumeClaim", "max": {"storage": "10Gi"}})
    assert pvc["default"] == {} and pvc["defaultRequest"] == {}


def test_a_removed_object_still_there_is_a_removal_and_a_rename_is_not():
    old_name = {BASE + "resourcequota.yaml": yaml.safe_dump(QUOTA)}
    renamed = folder(NAMESPACE, QUOTA)
    gone = {**folder(NAMESPACE, QUOTA, CPU)}
    live = served(NAMESPACE, QUOTA, CPU)
    assert read_plan(live.get, NS, renamed, {**old_name, **folder(NAMESPACE)}).ok
    found = read_plan(live.get, NS, renamed, gone)
    assert [str(d) for d in found.differences] == ["LimitRange/payments-dev-limits-cpu: plan absent, live 'present'"]
    assert found.only_removals
    del live.objects[("LimitRange", NS, f"{NS}-limits-cpu")]
    found = read_plan(live.get, NS, renamed, gone)
    assert found.ok and found.summary().endswith("and 1 removed object absent"), found.summary()


def test_an_object_that_cannot_be_read_is_never_absent():
    live = served(NAMESPACE)

    def get(kind, ns, name):
        if kind == "LimitRange":
            raise Unreadable("403 forbidden")
        return live.get(kind, ns, name)
    found = read_plan(get, NS, folder(NAMESPACE), folder(NAMESPACE, CPU))
    assert [str(d) for d in found.differences] == ["LimitRange/payments-dev-limits-cpu: plan 'readable', live 'cannot read: 403 forbidden'"]
    assert not found.only_removals, "a read that failed must not end a prune wait"


def test_a_cluster_that_cannot_be_read_is_the_callers_wait():
    class Down(RuntimeError):
        pass

    def get(*a):
        raise Down("unreachable")
    with pytest.raises(Down):
        read_plan(get, NS, folder(NAMESPACE))


# --------------------------------------------------------------------------- PR #752 review (reviewer 2)

TOKEN_ISSUER = {**BINDING, "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "cmapi-token-issuer"},
                "subjects": [{"kind": "ServiceAccount", "name": "cmapi-token-issuer", "namespace": "cmapi-system"}]}
BOT = {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "ci-bot", "namespace": NS}}


def test_a_missing_rolebinding_or_serviceaccount_is_named_and_a_binding_must_grant_what_the_plan_grants():
    """The renderer writes a token-issuer RoleBinding on every create, and the requested ServiceAccounts and grants: a
    delivery that left one out has not delivered the plan."""
    files = folder(NAMESPACE, QUOTA, BOT, TOKEN_ISSUER)
    live = served(NAMESPACE, QUOTA)
    assert [str(d) for d in read_plan(live.get, NS, files).differences] == [
        "ServiceAccount/ci-bot: plan 'present', live absent", "RoleBinding/cmapi-token-issuer: plan 'present', live absent"]
    live.put(copy.deepcopy(BOT))
    live.put(copy.deepcopy(TOKEN_ISSUER))
    found = read_plan(live.get, NS, files)
    assert found.ok and found.summary().endswith("as do 1 ServiceAccount and 1 RoleBinding"), found.summary()
    live.put({**copy.deepcopy(TOKEN_ISSUER), "subjects": [{"kind": "ServiceAccount", "name": "someone", "namespace": NS}]})
    assert [d.field for d in read_plan(live.get, NS, files).differences] == ["roleRef and subjects"]


def test_the_prune_policy_is_compared_though_argo_cds_tracking_keys_are_left_out():
    """liveOnlyKeys holds argocd.argoproj.io/* for Argo CD's tracking id, and cmapi renders its own Prune=confirm under it."""
    live = served(NAMESPACE)
    assert read_plan(live.get, NS, folder(NAMESPACE)).ok
    del live.get("Namespace", None, NS)["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
    assert [d.field for d in read_plan(live.get, NS, folder(NAMESPACE)).differences] == [
        "annotation argocd.argoproj.io/sync-options"]


def test_a_planned_object_marked_for_deletion_is_not_the_plans():
    live = served(NAMESPACE, QUOTA)
    live.get("Namespace", None, NS)["metadata"]["deletionTimestamp"] = "2026-11-27T10:00:00Z"
    assert [str(d) for d in read_plan(live.get, NS, folder(NAMESPACE, QUOTA)).differences] == [
        "Namespace/payments-dev metadata.deletionTimestamp: plan absent, live '2026-11-27T10:00:00Z'"]


@pytest.mark.parametrize("doc", [QUOTA, CPU])
def test_a_sub_milli_amount_matches_the_api_servers_rounding_and_no_other(doc):
    """SetDefaults_ResourceList rounds each ResourceList value up to milli scale: a planned 100u is stored as 1m."""
    plan = copy.deepcopy(doc)
    amounts = plan["spec"]["hard"] if doc["kind"] == "ResourceQuota" else plan["spec"]["limits"][0]["max"]
    amounts["cpu"] = "100u"
    files = folder(NAMESPACE, plan)
    live = served(NAMESPACE, plan)
    stored = live.get(doc["kind"], NS, doc["metadata"]["name"])
    stored_amounts = stored["spec"]["hard"] if doc["kind"] == "ResourceQuota" else stored["spec"]["limits"][0]["max"]
    stored_amounts["cpu"] = "1m"
    if doc["kind"] == "LimitRange":
        stored["spec"]["limits"][0]["default"]["cpu"] = stored["spec"]["limits"][0]["defaultRequest"]["cpu"] = "1m"
    assert read_plan(live.get, NS, files).ok, [str(d) for d in read_plan(live.get, NS, files).differences]
    stored_amounts["cpu"] = "2m"
    assert not read_plan(live.get, NS, files).ok


def test_a_scope_selector_matches_the_form_the_api_server_returns_and_no_other():
    """The API server leaves out an empty values array (omitempty): Exists with values [] reads back without them."""
    plan = copy.deepcopy(QUOTA)
    plan["spec"]["scopeSelector"] = {"matchExpressions": [{"scopeName": "PriorityClass", "operator": "Exists", "values": []}]}
    live = served(NAMESPACE, plan)
    del live.get("ResourceQuota", NS, f"{NS}-quota")["spec"]["scopeSelector"]["matchExpressions"][0]["values"]
    assert read_plan(live.get, NS, folder(NAMESPACE, plan)).ok
    live.get("ResourceQuota", NS, f"{NS}-quota")["spec"]["scopeSelector"]["matchExpressions"][0]["operator"] = "DoesNotExist"
    assert [d.field for d in read_plan(live.get, NS, folder(NAMESPACE, plan)).differences] == ["spec.scopeSelector"]
