"""Story #26: the pure parts of the adoption (core/adoption.py, MetadataKeys.adoption_findings, the approval floor).

The design is docs/reviews/2026-11-14-issue-26-adoption/README.md; each test names the decision it proves. The owner's sample
(section 5) is read with the company's metadata-keys.company.yaml, as the design's test plan says.
"""
from __future__ import annotations

import pytest
import yaml

from cmapi.core.adoption import (AdoptionSettings, Owner, adopted_files, cleaned, object_findings, skipped_keys, snapshot,
                                 snapshot_hash, stale, standing, takeover_allowed)
from cmapi.core.approvals import ApprovalRules
from cmapi.core.metadata import MetadataKeys
from cmapi.core.tiers import TierCatalog
from conftest import EX

COMPANY = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.company.yaml")
CATALOG = TierCatalog.load(EX / "instances/nonprod/tiers.yaml", {"rnd", "dev"})
SETTINGS = AdoptionSettings()
SAMPLE = {"name": "aao-rnd", "company.net/app-environment": "rnd", "company.net/mnemonic": "abc", "company.net/lob": "amgsst",
          "company.net/cl": "1", "company.net/provisioner": "cluster-configs", "company.net/mnemonic-group-contact": "",
          "company.net/mnemonic-confluence": "", "cmapi.net/adopt": "true"}


def namespace(name="abc-rnd", labels=None, annotations=None, managed_fields=None, **extra):
    meta = {"name": name, "uid": f"uid-{name}", "resourceVersion": "7", "creationTimestamp": "2026-01-01T00:00:00Z",
            "labels": dict(SAMPLE if labels is None else labels),
            "annotations": dict({"company.net/app-environment": "rnd"} if annotations is None else annotations)}
    if managed_fields is not None:
        meta["managedFields"] = managed_fields
    return {"apiVersion": "v1", "kind": "Namespace", "metadata": meta, "spec": {"finalizers": ["kubernetes"]},
            "status": {"phase": "Active"}, **extra}


def quota(name, hard, scopes=None, rv="8"):
    spec = {"hard": hard, **({"scopes": scopes} if scopes is not None else {})}
    return {"metadata": {"name": name, "namespace": "abc-rnd", "uid": f"uid-{name}", "resourceVersion": rv}, "spec": spec,
            "status": {"used": {}}}


def limits(name, items):
    return {"metadata": {"name": name, "namespace": "abc-rnd", "uid": f"uid-{name}", "resourceVersion": "9"},
            "spec": {"limits": items}}


SOURCES = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "CRC", "instance": "nonprod"}


def codes(findings):
    return sorted((f["code"], f["key"]) for f in findings)


# --------------------------------------------------------------------------- D6: the keys, reported and never changed


def test_the_owner_sample_gives_the_findings_of_the_design_and_changes_nothing():
    """Section 5, the plan case: derived-mismatch on name, two labels that are annotations now, the adoption label. The
    opt-in label is the adoption's own and no finding."""
    found = COMPANY.adoption_findings(SAMPLE, {"company.net/app-environment": "rnd"}, SOURCES,
                                      ignore=frozenset({"cmapi.net/adopt"}))
    assert codes(found) == [("adoption-label", "company.net/provisioner"),
                            ("declared-as-annotation", "company.net/mnemonic-confluence"),
                            ("declared-as-annotation", "company.net/mnemonic-group-contact"),
                            ("derived-mismatch", "name")]


def test_the_correct_namespace_abd_rnd_has_no_derived_mismatch():
    labels = {**SAMPLE, "name": "abd-rnd", "company.net/mnemonic": "abd"}
    found = COMPANY.adoption_findings(labels, {"company.net/app-environment": "rnd"}, {**SOURCES, "namespace": "abd-rnd"},
                                      ignore=frozenset({"cmapi.net/adopt"}))
    assert "derived-mismatch" not in {f["code"] for f in found}


def test_a_missing_required_key_is_a_finding_and_each_broken_value_too():
    """The owner's decision 7: a missing required key is never forced, only reported. A value that breaks its rule is kept."""
    labels = {k: v for k, v in SAMPLE.items() if k != "company.net/lob"}
    labels.update({"company.net/cl": "9", "company.net/mnemonic": "xyz", "company.net/app-environment": "prod"})
    found = COMPANY.adoption_findings(labels, {}, SOURCES, ignore=frozenset({"cmapi.net/adopt"}))
    got = codes(found)
    assert ("missing-required-key", "company.net/lob") in got
    assert ("invalid-value", "company.net/cl") in got and ("invalid-value", "company.net/mnemonic") in got
    assert ("environment-mismatch", "company.net/app-environment") in got
    assert ("missing-required-key", "company.net/app-environment") in got          # the annotation of the same key


def test_an_empty_required_value_is_reported_once_as_empty():
    found = COMPANY.adoption_findings({**SAMPLE, "company.net/lob": ""}, {"company.net/app-environment": "rnd"}, SOURCES,
                                      ignore=frozenset({"cmapi.net/adopt"}))
    assert [f["code"] for f in found if f["key"] == "company.net/lob"] == ["empty-value"]


# --------------------------------------------------------------------------- D1: candidates


@pytest.mark.parametrize("ns, in_git, state, rule", [
    (namespace(), False, "candidate", None),
    (namespace(labels={**SAMPLE, "cmapi.net/adopt": "false"}), False, "unlabelled", "not-labelled"),
    (namespace(labels={**SAMPLE, "cmapi.net/managed": "true"}), False, "skipped", "managed"),
    (namespace(), True, "skipped", "managed"),
    (namespace(name="kube-tools"), False, "skipped", "excluded"),
    (namespace(name="openshift-gitops"), False, "skipped", "excluded"),
    (namespace(status={"phase": "Terminating"}), False, "skipped", "terminating"),
    (namespace(annotations={"argocd.argoproj.io/tracking-id": "payments:/Namespace:/abc-rnd"}), False, "skipped",
     "tracked-elsewhere"),
    (namespace(annotations={"argocd.argoproj.io/tracking-id": "cluster-configs-crc:/Namespace:/abc-rnd"}), False,
     "candidate", None),
    (namespace(labels={**SAMPLE, "app.kubernetes.io/instance": "payments"}), False, "candidate", None),
])
def test_d1_decides_each_namespace_in_order(ns, in_git, state, rule):
    got = standing(ns, in_git=in_git, environment="rnd", cluster_id="CRC", settings=SETTINGS, keys=COMPANY,
                   own_application="cluster-configs-crc")
    assert (got.state, got.rule) == (state, rule)
    assert got.recognised == ("company.net/provisioner=cluster-configs",)


def test_the_instance_label_counts_only_under_label_tracking():
    ns = namespace(labels={**SAMPLE, "app.kubernetes.io/instance": "payments"})
    settings = AdoptionSettings.parse({"argocd": {"resourceTrackingMethod": "label"}}, ["rnd"])
    got = standing(ns, in_git=False, environment="rnd", cluster_id="CRC", settings=settings, keys=COMPANY,
                   own_application="cluster-configs-crc")
    assert (got.state, got.rule, got.application) == ("skipped", "tracked-elsewhere", "payments")


def test_exclusions_add_up_from_every_scope_and_a_bad_file_is_refused():
    settings = AdoptionSettings.parse({"exclude": {"patterns": ["legacy-*"], "labelSelectors": ["openshift.io/run-level"]},
                                       "environments": {"rnd": {"names": ["abc-rnd"]}},
                                       "clusters": {"CRC": {"labelSelectors": ["tier=gold"]}}}, ["rnd", "dev"])
    assert settings.excluded("legacy-a", {}, "dev", "X") == "pattern legacy-*"
    assert settings.excluded("x", {"openshift.io/run-level": "0"}, "dev", "X") == "label selector openshift.io/run-level"
    assert settings.excluded("abc-rnd", {}, "rnd", "X") == "name abc-rnd" and settings.excluded("abc-rnd", {}, "dev", "X") is None
    assert settings.excluded("y", {"tier": "gold"}, "dev", "CRC") == "label selector tier=gold"
    with pytest.raises(ValueError, match="environments.qa"):
        AdoptionSettings.parse({"environments": {"qa": {}}}, ["rnd"])
    with pytest.raises(ValueError, match="unknown key"):
        AdoptionSettings.parse({"exclud": {}}, ["rnd"])


# --------------------------------------------------------------------------- D3, D3a, D4, D8: the folder


def _fields(*keys):
    return {"f:metadata": {"f:labels": {f"f:{k}": {} for k in keys}}}


def test_d3a_leaves_out_a_skipped_key_only_when_no_client_side_apply_wrote_it():
    labels = {**SAMPLE, "kubernetes.io/metadata.name": "abc-rnd", "pod-security.kubernetes.io/enforce": "restricted"}
    owned = [{"manager": "kube-apiserver", "operation": "Update", "fieldsV1": _fields("kubernetes.io/metadata.name")},
             {"manager": "kubectl-client-side-apply", "operation": "Update",
              "fieldsV1": _fields("pod-security.kubernetes.io/enforce")}]
    decided = {d.key: d.kept for d in skipped_keys(namespace(labels=labels, managed_fields=owned), SETTINGS)}
    assert decided == {"kubernetes.io/metadata.name": False, "pod-security.kubernetes.io/enforce": True}
    # no managedFields in the read: nothing is proven, so the key stays
    assert all(d.kept for d in skipped_keys(namespace(labels=labels), SETTINGS))


def test_the_adopted_folder_is_the_live_objects_plus_cmapi_keys_one_file_each_strings_kept():
    rq = quota("abc-rnd-quota", {"requests.cpu": "40", "count/deployments.apps": "20"}, scopes=["NotTerminating"])
    lrs = [limits("abc-rnd-limits-cpu", [{"type": "Container", "default": {"cpu": "500m"}}]),
           limits("abc-rnd-limits-memory", [{"type": "Container", "default": {"memory": "512Mi"}}])]
    snap, _ = snapshot(namespace(), [rq], lrs, SETTINGS)
    files, replaced = adopted_files(snap, Owner("CRC", "nonprod", "rnd", "custom", "req-1", "opal", "opal@x.com"), COMPANY)
    base = "clusters/CRC/namespaces/abc-rnd/"
    assert sorted(files) == [base + "limitrange-abc-rnd-limits-cpu.yaml", base + "limitrange-abc-rnd-limits-memory.yaml",
                             base + "namespace.yaml", base + "resourcequota-abc-rnd-quota.yaml"]
    text = files[base + "namespace.yaml"]
    assert "company.net/cl: '1'" in text and "company.net/mnemonic-confluence: ''" in text and "cmapi.net/adopt: 'true'" in text
    ns = yaml.safe_load(text)
    assert ns == {"apiVersion": "v1", "kind": "Namespace", "metadata": {
        "name": "abc-rnd", "labels": ns["metadata"]["labels"], "annotations": ns["metadata"]["annotations"]}}
    assert {k: v for k, v in ns["metadata"]["labels"].items() if not k.startswith("cmapi.net/") or k == "cmapi.net/adopt"} == SAMPLE
    rq_doc = yaml.safe_load(files[base + "resourcequota-abc-rnd-quota.yaml"])
    assert rq_doc["spec"] == rq["spec"] and "status" not in rq_doc and "uid" not in rq_doc["metadata"]
    assert rq_doc["metadata"]["annotations"] == {"cmapi.net/instance": "nonprod", "cmapi.net/request-id": "req-1",
                                                 "argocd.argoproj.io/sync-options": "Prune=confirm"}
    assert replaced == []


def test_a_held_sync_option_is_replaced_and_reported():
    ns = namespace(annotations={"argocd.argoproj.io/sync-options": "Prune=false"})
    snap, _ = snapshot(ns, [], [], SETTINGS)
    _, replaced = adopted_files(snap, Owner("CRC", "nonprod", "rnd", "custom", "req-1", "opal", None), COMPANY)
    assert replaced == [{"object": "Namespace/abc-rnd", "kind": "annotation", "key": "argocd.argoproj.io/sync-options",
                         "before": "Prune=false", "after": "Prune=confirm,ServerSideApply=true"}]


def test_cleaned_drops_only_what_the_api_server_sets():
    out = cleaned({"metadata": {"name": "q", "uid": "u", "resourceVersion": "1", "generation": 2, "managedFields": [],
                                "creationTimestamp": "t", "ownerReferences": [{"name": "o"}]},
                   "spec": {"hard": {"pods": "1"}}, "status": {"used": {}}}, "ResourceQuota")
    assert out == {"apiVersion": "v1", "kind": "ResourceQuota",
                   "metadata": {"name": "q", "ownerReferences": [{"name": "o"}]}, "spec": {"hard": {"pods": "1"}}}


# --------------------------------------------------------------------------- D5, D17: quotas and limits


def test_d17_findings_of_free_form_quotas_and_limits():
    rqs = [quota("a", {"cpu": "40", "count/deployments.apps": "20"}),
           quota("b", {"requests.cpu": "30", "pods": "5"}),
           quota("scoped", {"requests.memory": "8Gi"}, scopes=["BestEffort"])]
    lrs = [limits("x", [{"type": "Container", "default": {"cpu": "1"}, "max": {"cpu": "40"}}]),
           limits("y", [{"type": "Container", "default": {"cpu": "2"}}])]
    snap, _ = snapshot(namespace(), rqs, lrs, SETTINGS)
    found, beyond = object_findings(snap, cluster_id="CRC", environment="rnd", tiers=CATALOG)
    got = sorted((f.code, f.key) for f in found)
    assert ("uninterpreted-key", "count/deployments.apps") in got
    assert ("scoped-only", "requests.memory") in got
    assert ("duplicate-default", "default.cpu") in got
    # cpu 40 is above rnd's custom max of 32; pods 5 is below the custom min of 10; the LimitRange's max.cpu 40 above 16
    assert ("beyond-custom-bounds", "requests.cpu") in got and ("beyond-custom-bounds", "pods") in got
    assert ("beyond-custom-bounds", "limitRange.container.max.cpu") in got
    assert beyond["pods"] == {"bound": "10", "requested": "5"}


def test_no_quota_and_no_limits_are_findings():
    snap, _ = snapshot(namespace(), [], [], SETTINGS)
    found, _ = object_findings(snap, cluster_id="CRC", environment="rnd", tiers=CATALOG)
    assert {f.code for f in found} == {"no-resourcequota", "no-limitrange"}


# --------------------------------------------------------------------------- D16: the reads before each step


def test_d16_a_stored_plan_holds_only_while_the_objects_are_the_ones_read():
    ns, rq = namespace(), quota("abc-rnd-quota", {"pods": "10"})
    snap, _ = snapshot(ns, [rq], [], SETTINGS)
    stored = {"identity": snap.identity}
    assert stale(stored, ns, [rq], [], SETTINGS) is None
    changed = quota("abc-rnd-quota", {"pods": "20"}, rv="99")
    assert stale(stored, ns, [changed], [], SETTINGS).code == "stale"
    assert "created after" in stale(stored, ns, [rq, quota("new", {})], [], SETTINGS).detail
    assert "deleted after" in stale(stored, ns, [], [], SETTINGS).detail
    remade = namespace()
    remade["metadata"]["uid"] = "other"
    assert "made again" in stale(stored, remade, [rq], [], SETTINGS).detail
    assert stale(stored, None, [], [], SETTINGS).code == "stale"
    withdrawn = namespace(labels={k: v for k, v in SAMPLE.items() if k != "cmapi.net/adopt"})
    assert stale(stored, withdrawn, [rq], [], SETTINGS).code == "label-removed"
    assert takeover_allowed(stored, ns) and not takeover_allowed(stored, remade) and not takeover_allowed(None, ns)


def test_the_snapshot_hash_binds_files_and_identity():
    snap, _ = snapshot(namespace(), [], [], SETTINGS)
    files = snap.files("CRC")
    assert snapshot_hash(files, snap.identity) == snapshot_hash(dict(files), list(snap.identity))
    assert snapshot_hash({**files, "x": "y"}, snap.identity) != snapshot_hash(files, snap.identity)


# --------------------------------------------------------------------------- D10: the approval


RULES = {"defaults": {"group": "approver-platform", "timeoutHours": 24}, "environments": {"rnd": {"change": 0}},
         "autoApproval": {"enabled": True, "policies": [{"name": "everything", "match": {"environments": ["*"]}}]}}


def test_an_adoption_is_never_auto_approved_and_always_has_an_approver():
    """D10: auto-approval covers an adoption only when a policy names the plugin; with no rule, one approver is added."""
    rules = ApprovalRules(RULES, {"rnd"})
    facts = {"plugin": "adoption", "action": "adopt", "environment": "rnd", "namespace": "abc-rnd", "capacity": "fits"}
    req = rules.decide(facts)
    assert req.auto is None and [(s.group, s.count) for s in req.slots] == [("approver-platform", 1)]
    # the same facts of another plugin are auto-approved by the catch-all policy: the floor is the adoption's own
    assert rules.decide({**facts, "plugin": "namespaces", "action": "update", "capacity": "fits",
                         "capacityFresh": True}).auto == "auto:everything"


def test_the_shipped_rules_ask_one_platform_approver_and_one_more_for_findings():
    rules = ApprovalRules.load(EX / "instances/nonprod/approval-rules.yaml", {"rnd", "dev"})
    facts = {"plugin": "adoption", "action": "adopt", "environment": "dev", "namespace": "abc-rnd", "findingCount": 0}
    assert [(s.group, s.count) for s in rules.decide(facts).slots] == [("approver-platform", 1)]
    assert [(s.group, s.count) for s in rules.decide({**facts, "findingCount": 3}).slots] == [("approver-platform", 2)]


# --------------------------------------------------------------------------- D6a, #248: the real Kyverno CLI in enforce

from cmapi.core.policy import PolicySettings  # noqa: E402
from cmapi.core.policygen import render_bundle  # noqa: E402
from cmapi.core.validate import CliValidator  # noqa: E402
from test_policygen import kyverno  # noqa: E402,F401  (the fixture: skips without the pinned CLI, fails with CMAPI_REQUIRE_KYVERNO=1)


def _enforcing(tmp_path, kyverno):
    catalog = TierCatalog.load(EX / "config/tiers.yaml", {"rnd", "dev", "qa", "uat", "prod"})
    enforce = PolicySettings(default_mode="enforce")
    d = tmp_path / "policies"
    d.mkdir()
    return CliValidator(d, kyverno=kyverno, policy=enforce, environments={"rnd"},
                        bundle=render_bundle(catalog, COMPANY, enforce, {"rnd"}, "nonprod"))


def _adoption(labels=None, hard=None):
    rq = quota("abc-rnd-quota", hard or {"requests.cpu": "40", "requests.memory": "64Gi", "pods": "100"})
    snap, _ = snapshot(namespace(labels=labels), [rq], [], SETTINGS)
    files, _ = adopted_files(snap, Owner("OCP_GF15", "nonprod", "rnd", "custom", "req-1", "ola", "ola@company.net"), COMPANY)
    return snap.files("OCP_GF15"), files


def test_d6a_the_snapshot_holds_what_the_namespace_already_had_in_enforce(tmp_path, kyverno):
    """#248: the owner's sample, with the deliberate `name: aao-rnd` and a quota above the rnd bound, passes the rendered
    policies in enforce when the snapshot is the base, each held failure reported; with no base (Git has no folder) it is
    refused, which is the defect."""
    v = _enforcing(tmp_path, kyverno)
    base, files = _adoption()
    without = [f for f in v.validate(files, "OCP_GF15", "rnd") if f.source == "kyverno" and f.severity == "error"]
    assert without, "with no base the policies refuse the adopted values (#248)"
    held: list = []
    found = v.validate(files, "OCP_GF15", "rnd", previous=base, held=held)
    assert [f for f in found if f.source == "kyverno" and f.severity == "error"] == []
    assert {f.rule for f in held} >= {f.rule for f in without}


def test_d6a_a_value_that_the_adoption_would_change_is_still_checked(tmp_path, kyverno):
    """The base holds only what the live namespace had: a file whose value differs from the snapshot is checked."""
    v = _enforcing(tmp_path, kyverno)
    base, files = _adoption()
    path = "clusters/OCP_GF15/namespaces/abc-rnd/resourcequota-abc-rnd-quota.yaml"
    files[path] = files[path].replace("requests.cpu: '40'", "requests.cpu: '41'")
    assert "requests.cpu: '41'" in files[path]
    refused = [f for f in v.validate(files, "OCP_GF15", "rnd", previous=base) if f.source == "kyverno" and f.severity == "error"]
    assert any("requests-cpu" in f.rule for f in refused), refused


# --------------------------------------------------------------------------- #731: an adopted <ns>-quota is not the tier's


def test_731_a_label_change_keeps_an_adopted_quota_named_like_the_tiers():
    """D9: a change of a label leaves every object unchanged. An adopted quota may be named <ns>-quota (the design's own
    example, abc-rnd-quota) and carries no tier hash, so it is not cmapi's rendering and is kept with its scope."""
    from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec, quotas_kept
    rq = quota("abc-rnd-quota", {"requests.cpu": "40", "requests.memory": "64Gi", "pods": "100"}, scopes=["NotTerminating"])
    lr = limits("abc-rnd-limits-cpu", [{"type": "Container", "max": {"cpu": "2"}}])
    snap, _ = snapshot(namespace(), [rq], [lr], SETTINGS)
    files, _ = adopted_files(snap, Owner("CRC", "nonprod", "rnd", "custom", "req-1", "opal", None), COMPANY)
    assert quotas_kept([yaml.safe_load(files["clusters/CRC/namespaces/abc-rnd/resourcequota-abc-rnd-quota.yaml"])], "abc-rnd",
                       changes_quota=False)
    spec = NamespaceSpec(namespace="abc-rnd", cluster_id="CRC", instance="nonprod", env="rnd", tier="custom", request_id="req-2",
                         requested_by_user="opal", requested_by_email=None, labels={**SAMPLE, "company.net/lob": "other"},
                         annotations={"company.net/app-environment": "rnd"}, changes_quota=False)
    out = ManifestRenderer(CATALOG, COMPANY).render(spec, previous=files)
    for path in ("resourcequota-abc-rnd-quota.yaml", "limitrange-abc-rnd-limits-cpu.yaml"):
        assert out["clusters/CRC/namespaces/abc-rnd/" + path] == files["clusters/CRC/namespaces/abc-rnd/" + path], path
    assert "limitrange-abc-rnd-limits-memory.yaml" not in {p.rsplit("/", 1)[1] for p, t in out.items() if t}
