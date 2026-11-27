"""#746: only the findings that a person should judge add the adoption's extra approver (the adoption design's D10).

CRC run 46 (2026-11-27) adopted `cmapi-adopt-demo`, a namespace made with `oc create` and labelled with `oc label`, with
every required key supplied: 17 findings, and the rule `plugin == "adoption" and findingCount > 0` added an approver to
every adoption. Eight of those findings were the `skipped-key` labels and annotations that OpenShift's controllers put on
every namespace, and one the `not-adopted` count, none of which anyone can act on. The shipped rule now reads
`actionableFindingCount`, every finding but core/adoption.py's INFORMATIONAL_FINDINGS; the plan still lists them all, and
`findingCount` keeps its meaning.

The namespace below is run 46's, as `oc get namespace -o yaml --show-managed-fields` returns it: the opt-in label written by
`kubectl-label`, `kubernetes.io/metadata.name` by `kubectl-create`, the four pod-security labels by OpenShift's label
synchroniser, the three `openshift.io/sa.scc.*` annotations by `cluster-policy-controller`, and the ServiceAccounts and
RoleBindings that OpenShift makes in each new project. Its quota is within the custom bounds of dev (run 46's was below the
minimum, which adds the beyondTier approver of its own).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cmapi.core.adoption import UNADOPTED_KINDS
from cmapi.core.clients.kube import RESOURCES
from test_flow import OLA, auth

ROOT = Path(__file__).resolve().parents[3]

NS = "cmapi-adopt-demo"
ADOPT = f"/api/v1/clusters/CRC/namespaces/{NS}:adopt"
# The reference metadata-keys.yaml of the test instance requires these two, and the request supplies both (#739).
SUPPLIED = {"labels": {"cmapi.net/team": "cmapi-live"}, "annotations": {"cmapi.net/team-dl": "cmapi-live-team@ephico2real.com"}}
PSA = ("pod-security.kubernetes.io/audit", "pod-security.kubernetes.io/audit-version", "pod-security.kubernetes.io/warn",
       "pod-security.kubernetes.io/warn-version")
SCC = ("openshift.io/sa.scc.mcs", "openshift.io/sa.scc.supplemental-groups", "openshift.io/sa.scc.uid-range")


def _fields(labels=(), annotations=()):
    meta = {}
    if labels:
        meta["f:labels"] = {f"f:{k}": {} for k in labels}
    if annotations:
        meta["f:annotations"] = {f"f:{k}": {} for k in annotations}
    return {"f:metadata": meta}


def run46_namespace(kube, *, extra_labels=None):
    labels = {"cmapi.net/adopt": "true", "kubernetes.io/metadata.name": NS, "pod-security.kubernetes.io/audit": "restricted",
              "pod-security.kubernetes.io/audit-version": "latest", "pod-security.kubernetes.io/warn": "restricted",
              "pod-security.kubernetes.io/warn-version": "latest", **(extra_labels or {})}
    annotations = {"openshift.io/sa.scc.mcs": "s0:c27,c19", "openshift.io/sa.scc.supplemental-groups": "1000740000/10000",
                   "openshift.io/sa.scc.uid-range": "1000740000/10000",
                   "security.openshift.io/MinimallySufficientPodSecurityStandard": "restricted"}
    kube.objects[("Namespace", "", NS)] = {
        "apiVersion": "v1", "kind": "Namespace",
        "metadata": {"name": NS, "uid": "uid-adopt-demo", "resourceVersion": "9638834", "creationTimestamp": "2026-11-27T14:49:47Z",
                     "labels": labels, "annotations": annotations,
                     "managedFields": [
                         {"manager": "kubectl-create", "operation": "Update",
                          "fieldsV1": _fields(["kubernetes.io/metadata.name", *(extra_labels or {})])},
                         {"manager": "kubectl-label", "operation": "Update", "fieldsV1": _fields(["cmapi.net/adopt"])},
                         {"manager": "pod-security-admission-label-synchronization-controller", "operation": "Update",
                          "fieldsV1": _fields(PSA, ["security.openshift.io/MinimallySufficientPodSecurityStandard"])},
                         {"manager": "cluster-policy-controller", "operation": "Update", "fieldsV1": _fields((), SCC)}]},
        "spec": {"finalizers": ["kubernetes"]}, "status": {"phase": "Active"}}
    kube.objects[("ResourceQuota", NS, f"{NS}-quota")] = {
        "metadata": {"name": f"{NS}-quota", "namespace": NS, "uid": "uid-adopt-demo-quota", "resourceVersion": "9638808"},
        "spec": {"hard": {"requests.cpu": "4", "requests.memory": "8Gi", "pods": "20"}}}
    kube.objects[("LimitRange", NS, f"{NS}-limits")] = {
        "metadata": {"name": f"{NS}-limits", "namespace": NS, "uid": "uid-adopt-demo-limits", "resourceVersion": "9638806"},
        "spec": {"limits": [{"type": "Container", "defaultRequest": {"cpu": "50m", "memory": "64Mi"},
                             "default": {"cpu": "200m", "memory": "256Mi"}, "max": {"cpu": "1", "memory": "1Gi"}}]}}
    # What OpenShift makes in every new project.
    for sa in ("builder", "default", "deployer"):
        kube.objects[("ServiceAccount", NS, sa)] = {"metadata": {"name": sa, "namespace": NS}}
    for rb in ("system:deployers", "system:image-builders", "system:image-pullers"):
        kube.objects[("RoleBinding", NS, rb)] = {"metadata": {"name": rb, "namespace": NS}}


def plan(client, keys, **body):
    r = client.post(ADOPT + "?dryRun=true", json={"justification": "Bring cmapi-adopt-demo under cmapi", **body},
                    headers=auth(keys, "ola", **OLA))
    assert r.status_code == 200, r.text
    return r.json()


def needed(p):
    return sum(s["count"] for s in p["approval"]["slots"])


def test_run_46s_namespace_with_every_required_key_needs_only_the_base_approval(world):
    client, ctx, git, kube, validator, keys = world
    run46_namespace(kube)
    p = plan(client, keys, **SUPPLIED)
    rules = sorted(f["rule"] for f in p["findings"])
    # The plan still lists every finding: the eight server-owned keys left out of Git and what stays unmanaged.
    assert rules == ["not-adopted"] + ["skipped-key"] * 8, rules
    assert [f["message"] for f in p["findings"] if f["rule"] == "not-adopted"] == [
        "3 ServiceAccounts and 3 RoleBindings stay unmanaged: adoption takes the Namespace, ResourceQuotas and LimitRanges only"]
    # One approver of approver-platform, the adoption's own (D10); the findings approver is not added.
    assert p["approval"]["slots"] == [{"group": "approver-platform", "count": 1, "reason": "Adoption of an existing namespace"}]
    assert p["approval"]["auto"] is None
    assert not any("findingCount" in r for r in p["approval"]["reasons"]), p["approval"]["reasons"]


def test_a_real_unknown_key_still_adds_the_findings_approver(world):
    client, ctx, git, kube, validator, keys = world
    # A key that no stanza declares and allowOther does not admit, written by whoever made the namespace.
    run46_namespace(kube, extra_labels={"other.example/owner": "nobody"})
    p = plan(client, keys, **SUPPLIED)
    assert [f["rule"] for f in p["findings"] if f["rule"] not in ("skipped-key", "not-adopted")] == ["unknown-key"]
    assert needed(p) == 2
    assert p["approval"]["slots"] == [{"group": "approver-platform", "count": 2,
                                       "reason": "Adoption of an existing namespace; Adoption with findings"}]


def test_a_missing_required_key_still_adds_the_findings_approver(world):
    """D20: a required key the request does not supply stays a finding, and a person judges it."""
    client, ctx, git, kube, validator, keys = world
    run46_namespace(kube)
    p = plan(client, keys, labels=SUPPLIED["labels"])
    assert [f["rule"] for f in p["findings"] if f["rule"] not in ("skipped-key", "not-adopted")] == ["missing-required-key"]
    assert needed(p) == 2


def test_a_policy_failure_the_snapshot_holds_still_adds_the_findings_approver(world):
    """A held failure of the rendered policies (policy-ratcheted, D6a) on a real key is a deviation a person judges."""
    from cmapi.core.ports import Finding
    client, ctx, git, kube, validator, keys = world
    run46_namespace(kube)
    validator.held = [Finding("kyverno", "cmapi-metadata-dev-label-cmapi-net-team-pattern",
                              f"clusters/CRC/namespaces/{NS}/namespace.yaml", "the label cmapi.net/team must match", "error")]
    p = plan(client, keys, **SUPPLIED)
    assert "policy-ratcheted" in {f["rule"] for f in p["findings"]}
    assert needed(p) == 2


# --------------------------------------------------------------------------- #750's review: what still adds the approver


def test_a_validator_finding_counts_whatever_its_policy_is_named(world):
    """The rule of a validator finding is its policy's name, which a site's hand-written policy chooses (`policies_dir`). An
    audit warning of a policy named like an informational code is still a policy's verdict, which a person judges."""
    from cmapi.core.ports import Finding
    client, ctx, git, kube, validator, keys = world
    run46_namespace(kube)
    validator.findings = [Finding("kyverno", "skipped-key", f"clusters/CRC/namespaces/{NS}/namespace.yaml",
                                  "a site policy's audit warning", "warning")]
    p = plan(client, keys, **SUPPLIED)
    assert sorted(f["rule"] for f in p["findings"]).count("skipped-key") == 9
    assert needed(p) == 2


@pytest.mark.parametrize("manager", ["argocd-controller", "cmapi-deliverer"])
def test_a_key_that_only_a_delivery_applies_stays_in_git_and_adds_the_approver(world, manager):
    """D3a: a skip-prefix key that only argocd-controller or cmapi-deliverer owns through Apply would go on that manager's
    next apply if Git left it out ("If the field is not owned by any other field managers, it is either deleted from the
    live object or reset to its default value", Kubernetes, "Server-Side Apply"). So it stays in Git, as skipped-key-kept."""
    client, ctx, git, kube, validator, keys = world
    run46_namespace(kube)
    key = "pod-security.kubernetes.io/enforce"
    meta = kube.objects[("Namespace", "", NS)]["metadata"]
    meta["labels"][key] = "restricted"
    meta["managedFields"].append({"manager": manager, "operation": "Apply", "fieldsV1": _fields([key])})
    p = plan(client, keys, **SUPPLIED)
    kept = [f for f in p["findings"] if f["rule"] == "skipped-key-kept"]
    assert len(kept) == 1 and key in kept[0]["message"] and "stays on the cluster" not in kept[0]["message"], kept
    namespace = yaml.safe_load(p["files"][f"clusters/CRC/namespaces/{NS}/namespace.yaml"])
    assert namespace["metadata"]["labels"][key] == "restricted"
    assert needed(p) == 2


def test_the_delivery_managers_are_the_ones_cmapi_applies_with():
    from cmapi.core.adoption import DELIVERY_APPLY_MANAGERS
    from cmapi.core.clients.kube import APPLY_FIELD_MANAGER
    assert DELIVERY_APPLY_MANAGERS == {"argocd-controller", APPLY_FIELD_MANAGER}


@pytest.fixture
def bounded_world(test_config, fresh_db, keys, monkeypatch, tmp_path):
    """The test instance, with a quota key that cmapi does not interpret made overridable and bounded (tiers.yaml)."""
    import shutil
    from conftest import build_world
    d = tmp_path / "config"
    shutil.copytree(test_config, d)
    tiers = yaml.safe_load((d / "tiers.yaml").read_text())
    tiers["overridable"].append("count/configmaps")
    tiers["custom"]["max"]["count/configmaps"] = "10"
    (d / "tiers.yaml").write_text(yaml.safe_dump(tiers))
    with build_world(d, keys, monkeypatch) as w:
        yield w


@pytest.mark.parametrize("value, needs", [("11", 3), ("10", 1)])
def test_a_raw_quota_key_is_checked_against_the_bound_the_site_gives_it(bounded_world, value, needs):
    """D5: "Each value outside the custom tier's bounds ... is a finding beyond-custom-bounds". A raw key that tiers.yaml
    bounds is checked as any other; within its bound it stays informational (uninterpreted-key)."""
    client, ctx, git, kube, validator, keys = bounded_world
    run46_namespace(kube)
    kube.objects[("ResourceQuota", NS, f"{NS}-quota")]["spec"]["hard"]["count/configmaps"] = value
    p = plan(client, keys, **SUPPLIED)
    beyond = [f["message"] for f in p["findings"] if f["rule"] == "beyond-custom-bounds"]
    assert "uninterpreted-key" in {f["rule"] for f in p["findings"]}
    assert len(beyond) == (1 if needs == 3 else 0), beyond
    assert needed(p) == needs, p["approval"]


# --------------------------------------------------------------------------- #748: the reader's grant


@pytest.mark.parametrize("path", ["deploy/manifests/environments/crc/reader/00-cmapi-reader.yaml", "deploy/kind-import/reader.yaml"])
def test_the_reader_may_list_each_kind_the_adoption_plan_counts_and_no_more(path):
    """D2: the plan reports how many ServiceAccounts and RoleBindings stay unmanaged. Without `list` the count is null on
    every plan (run 46). The code only lists them, so the reader gets `list` alone on each (least privilege)."""
    role = next(d for d in yaml.safe_load_all((ROOT / path).read_text()) if d and d["kind"] == "ClusterRole")
    granted = {(g, r, v) for rule in role["rules"] for g in rule["apiGroups"] for r in rule["resources"] for v in rule["verbs"]}
    for kind in UNADOPTED_KINDS:
        url = RESOURCES[kind][0]                       # /api/v1/<plural> or /apis/<group>/<version>/<plural>
        group = "" if url.startswith("/api/") else url.split("/")[2]
        plural = url.rsplit("/", 1)[1]
        assert {v for g, r, v in granted if (g, r) == (group, plural)} == {"list"}, (kind, path)
