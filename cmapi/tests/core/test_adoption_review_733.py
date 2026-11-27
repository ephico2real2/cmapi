"""PR #733's review: the planner's findings, the tracking method, the quotas a later change keeps, and D10's approval."""
import yaml

from cmapi.core.adoption import AdoptionSettings, Owner, adopted_files, object_findings, snapshot, standing
from cmapi.core.approvals import ApprovalRules
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from test_adoption_26 import CATALOG, COMPANY, EX, SAMPLE, SETTINGS, namespace, quota

FACTS = {"plugin": "adoption", "action": "adopt", "environment": "dev", "namespace": "abc-rnd", "findingCount": 0,
         "actionableFindingCount": 0, "capacity": "fits", "capacityFresh": True}


def test_a_scoped_quota_beyond_the_custom_bounds_is_a_finding_and_a_fact():
    """D5: each value outside the custom bounds is a finding and a beyondTier fact; D17 keeps a scoped quota out of the
    namespace's figures only. The owner's test namespace (section 5) has a scoped quota above the bound for rnd."""
    snap, _ = snapshot(namespace(), [quota("jobs", {"requests.cpu": "40"}, scopes=["BestEffort"])], [], SETTINGS)
    findings, beyond = object_findings(snap, cluster_id="CRC", environment="rnd", tiers=CATALOG)
    assert beyond["requests.cpu"]["requested"] == "40"
    assert {"scoped-only", "beyond-custom-bounds"} <= {f.code for f in findings}


def test_annotation_plus_label_tracks_by_the_annotation_only():
    """Argo CD, Resource Tracking: with annotation+label the label is "only for informational purposes"."""
    settings = AdoptionSettings.parse({"argocd": {"resourceTrackingMethod": "annotation+label"}}, [])
    live = namespace(labels={**SAMPLE, "app.kubernetes.io/instance": "a-helm-release"})
    where = standing(live, in_git=False, environment="rnd", cluster_id="CRC", settings=settings, keys=COMPANY,
                     own_application="cmapi")
    assert where.state == "candidate"
    label = AdoptionSettings.parse({"argocd": {"resourceTrackingMethod": "label"}}, [])
    assert standing(live, in_git=False, environment="rnd", cluster_id="CRC", settings=label, keys=COMPANY,
                    own_application="cmapi").rule == "tracked-elsewhere"


def _adopted(quotas):
    snap, _ = snapshot(namespace(), quotas, [], SETTINGS)
    return adopted_files(snap, Owner("CRC", "nonprod", "rnd", "custom", "one", "opal", None), COMPANY)[0]


def _label_change(previous):
    spec = NamespaceSpec(namespace="abc-rnd", cluster_id="CRC", instance="nonprod", env="rnd", tier="custom",
                         request_id="two", requested_by_user="opal", requested_by_email=None,
                         labels={"description": "changed"}, changes_quota=False)
    files = ManifestRenderer(CATALOG, COMPANY).render(spec, previous=previous)
    return {p: v for p, v in files.items() if "/resourcequota-" in p or "/limitrange-" in p}


def test_a_label_change_of_an_adopted_namespace_with_no_quota_adds_none():
    """D16, "No ResourceQuota": a later quota request adds the object; section 5: "an update of a label passes". D9: any other
    request leaves every object unchanged. Head rendered the custom tier and refused: "A custom tier needs every sizable key"."""
    assert _label_change(_adopted([])) == {}


def test_a_label_change_keeps_an_adopted_quota_that_already_carried_a_tier_hash():
    """A namespace once managed by cmapi and adopted again: its <ns>-quota carries a tier hash, and D4's Prune=confirm."""
    rq = quota("abc-rnd-quota", {"pods": "20"}, scopes=["BestEffort"])
    rq["metadata"]["annotations"] = {"cmapi.net/tier-hash": "from-before"}
    previous = _adopted([rq])
    assert _label_change(previous) == {p: v for p, v in previous.items() if "/resourcequota-" in p}


# D10: "Auto-approval never covers an adoption unless a rule names it." The counts are the shipped rules' defaults.


def test_d10_a_policy_that_does_not_name_adoption_never_covers_one():
    rules = {"defaults": {"group": "approver-platform", "timeoutHours": 24}, "environments": {"dev": {"change": 1}},
             "autoApproval": {"enabled": True, "policies": [{"name": "all", "match": {"environments": ["*"]}}]}}
    assert ApprovalRules(rules, {"dev"}).decide(FACTS).auto is None


def test_d10_with_the_shipped_rules_a_policy_naming_adoption_still_needs_the_platform_approvers():
    raw = yaml.safe_load((EX / "instances/nonprod/approval-rules.yaml").read_text())
    raw["autoApproval"]["policies"].append({"name": "adopt", "match": {"plugin": "adoption", "environments": ["*"]}})
    rules = ApprovalRules(raw, {"rnd", "dev"})
    req = rules.decide(FACTS)
    assert req.auto is None and [(s.group, s.count) for s in req.slots] == [("approver-platform", 1)]
    req = rules.decide({**FACTS, "findingCount": 2, "actionableFindingCount": 2, "warnings": ["a finding"]})
    assert req.auto is None and [(s.group, s.count) for s in req.slots] == [("approver-platform", 2)]


def test_d10_a_site_rule_that_names_adoption_may_auto_approve_it():
    """The site removed the shipped adoption thresholds and named the plugin in a policy: D10 lets that rule cover it."""
    rules = {"defaults": {"group": "approver-platform", "timeoutHours": 24}, "environments": {"dev": {"change": 1}},
             "autoApproval": {"enabled": True, "policies": [{"name": "adopt", "match": {"plugin": "adoption"}}]}}
    assert ApprovalRules(rules, {"dev"}).decide(FACTS).auto == "auto:adopt"
