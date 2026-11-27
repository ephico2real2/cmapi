"""#746, #747 and #748: the adoption findings that CRC run 46 (2026-11-27) found, without a cluster.

- #746 (a): the opt-in label is the adoption's own. cmapi's check skips it (`adoption_findings(ignore=...)`), and the rendered
  policies now allow it too, so an adoption plan has no `policy-ratcheted` finding on it.
- #746 (b): only the findings a person should judge count towards `actionableFindingCount`, which the shipped approval rule
  reads; `findingCount` keeps every finding.
- #747: a key under a skip prefix that `kubectl create` wrote is left out of Git with a reason that is true of it.
- #748: the words of what stays unmanaged (the reader's grant is held by tests/service/test_adoption_findings_746.py).

The rendered policies are read without the Kyverno CLI, as test_platform_namespace_keys_354 reads them; the one test that runs
the CLI skips without it and fails under CMAPI_REQUIRE_KYVERNO=1 (CI).
"""
from __future__ import annotations

import json
import re

import pytest
import yaml

from cmapi.core.adoption import (INFORMATIONAL_FINDINGS, AdoptionSettings, Owner, actionable_count,
                                 adopted_files, skipped_keys, snapshot, unmanaged_phrase)
from cmapi.core.approvals import ApprovalRules
from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from cmapi.core.tiers import TierCatalog
from cmapi.tools.policies import _render
from conftest import ALL_ENVS, EX, crc_config_dir

ROOT = EX.parent
REFERENCE = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.yaml")
COMPANY = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.company.yaml")
CATALOG = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)


# --------------------------------------------------------------------------- #746 (a): the opt-in label and the policies


def _variable(bundle: dict[str, str], kind: str, rule: str, variable: str) -> str:
    """The CEL of one variable of the other-keys `prefix` or `max` policy of dev."""
    doc = next(d for d in yaml.safe_load_all(bundle["env/dev/cmapi-metadata-dev.yaml"])
               if d["metadata"]["name"] == f"cmapi-metadata-dev-{kind}-other-keys-{rule}")
    return next(v["expression"] for v in doc["spec"]["variables"] if v["name"] == variable)


def _check_selector(bundle: dict[str, str], key: str, value: str) -> None:
    """Both label policies allow the opt-in label with its value only (#750's review), and not by its key alone; the annotation
    policies do not name it."""
    for rule, suffix in [("prefix", "Outside"), ("max", "Other")]:
        expr = _variable(bundle, "label", rule, "label" + suffix)
        fixed = re.search(r"k in (\[[^\]]*\])", expr)
        assert fixed and key not in json.loads(fixed[1])
        assert f'k == "{key}" && (has(object.metadata.labels) ? object.metadata.labels : {{}})[k] == "{value}"' in expr
        assert key not in _variable(bundle, "annotation", rule, "annotation" + suffix)


@pytest.mark.parametrize("keys", [REFERENCE, COMPANY], ids=["reference", "company"])
def test_the_prefix_policy_allows_the_opt_in_label_as_the_adoption_check_skips_it(keys):
    bundle = render_bundle(CATALOG, keys, PolicySettings(), {"dev"}, "nonprod")
    _check_selector(bundle, "cmapi.net/adopt", "true")
    # cmapi's own check agrees: the adoption finds nothing on the label it ignores, and would report it otherwise.
    labels, sources = {"cmapi.net/adopt": "true"}, {"namespace": "x-dev", "environment": "dev"}
    assert [f for f in keys.adoption_findings(labels, {}, sources, ignore=frozenset({"cmapi.net/adopt"}))
            if f["key"] == "cmapi.net/adopt"] == []
    assert [f["code"] for f in keys.adoption_findings(labels, {}, sources) if f["key"] == "cmapi.net/adopt"] == ["unknown-key"]


def test_a_site_that_names_another_opt_in_label_has_that_one_allowed(tmp_path):
    """adoption.yaml's selector.label is the one the policies allow, through the same render as `cmapi-tools policies`."""
    config = crc_config_dir(tmp_path)
    (config / "adoption.yaml").write_text('selector: {label: example.org/adopt-me, value: "yes"}\n')
    rendered, _ = _render(config, config / "metadata-keys.yaml")
    _check_selector(rendered, "example.org/adopt-me", "yes")
    assert "cmapi.net/adopt" not in _variable(rendered, "label", "prefix", "labelOutside")


from cmapi.core.validate import CliValidator  # noqa: E402
from test_policygen import kyverno  # noqa: E402,F401  (the fixture: skips without the pinned CLI, fails with CMAPI_REQUIRE_KYVERNO=1)


def test_only_the_opt_in_label_with_its_value_passes_the_prefix_policy(kyverno, tmp_path):
    """The same key with another value, and a longer key with the value, keep the ordinary verdict: outside the prefixes."""
    from test_policygen import apply, resources, write
    label = "opt.example/take"
    rendered = render_bundle(CATALOG, REFERENCE, PolicySettings(), {"dev"}, "nonprod", label, "yes")
    policies = write(tmp_path / "bundle", rendered) / "env/dev"
    prefix = "cmapi-metadata-dev-label-other-keys-prefix"
    for key, value, allowed in [(label, "yes", True), (label, "true", False), (label + "-more", "yes", False)]:
        obj = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "abc-dev",
               "labels": {"cmapi.net/managed": "true", "cmapi.net/env": "dev", key: value}}}
        results = apply(kyverno, policies, resources(tmp_path, {"ns.yaml": obj}))
        expected = "pass" if allowed else "fail"
        assert prefix in dict(results.get(expected, [])), (key, value, results)


def test_an_adoption_plan_has_no_policy_finding_on_the_opt_in_label(tmp_path, kyverno):
    """The issue's proof: every required key with a valid value, the opt-in label, no skip-prefix key and a quota within the
    custom bounds, through the generated bundle. No held failure names cmapi.net/adopt, and none is left at all."""
    policy = PolicySettings(default_mode="enforce")
    d = tmp_path / "policies"
    d.mkdir()
    v = CliValidator(d, kyverno=kyverno, policy=policy, environments={"dev"},
                     bundle=render_bundle(CATALOG, REFERENCE, policy, {"dev"}, "nonprod"))
    ns = {"apiVersion": "v1", "kind": "Namespace",
          "metadata": {"name": "abc-dev", "uid": "u1", "resourceVersion": "1",
                       "labels": {"cmapi.net/adopt": "true", "cmapi.net/team": "abc"},
                       "annotations": {"cmapi.net/team-dl": "abc-team@ephico2real.com"}}}
    rq = {"metadata": {"name": "abc-dev-quota", "namespace": "abc-dev", "uid": "u2", "resourceVersion": "2"},
          "spec": {"hard": {"requests.cpu": "4", "requests.memory": "8Gi", "pods": "20"}}}
    snap, _ = snapshot(ns, [rq], [], AdoptionSettings())
    files, _ = adopted_files(snap, Owner("CRC", "nonprod", "dev", "custom", "req-1", "ola", "ola@ephico2real.com"), REFERENCE)
    held: list = []
    found = v.validate(files, "CRC", "dev", previous=snap.files("CRC"), held=held)
    assert [f for f in found if f.severity == "error"] == []
    assert [h.message for h in held if "cmapi.net/adopt" in h.message] == []
    assert held == []


# --------------------------------------------------------------------------- #746 (b): the count that adds the approver


def test_the_informational_codes_are_not_counted_and_every_other_code_is():
    assert INFORMATIONAL_FINDINGS == {"skipped-key", "not-adopted", "adoption-label", "scoped-only", "uninterpreted-key"}
    assert actionable_count(["skipped-key"] * 8 + ["not-adopted", "adoption-label", "scoped-only", "uninterpreted-key"]) == 0
    judged = ["unknown-key", "missing-required-key", "invalid-value", "derived-mismatch", "environment-mismatch", "empty-value",
              "declared-as-annotation", "declared-as-label", "skipped-key-kept", "sync-options-replaced", "system-key-replaced",
              "instance-label", "beyond-custom-bounds", "duplicate-default", "no-resourcequota", "no-limitrange",
              "policy-ratcheted", "cmapi-metadata-dev-label-cmapi-net-team-pattern"]
    assert actionable_count(judged) == len(judged)
    # A code that no one has named yet counts: a new finding adds the approver until it is declared informational on purpose.
    assert actionable_count(["a-code-from-a-later-release"]) == 1


NONPROD, STAGING = {"rnd", "dev"}, {"qa", "uat"}


@pytest.mark.parametrize("path, served, env", [("examples/instances/nonprod/approval-rules.yaml", NONPROD, "dev"),
                                              ("examples/instances/staging/approval-rules.yaml", STAGING, "qa"),
                                              ("examples/instances/prod/approval-rules.yaml", {"prod"}, "prod"),
                                              ("cmapi/src/cmapi/tools/reference_instance/approval-rules.yaml", NONPROD, "dev"),
                                              ("deploy/helm/cmapi/config/approval-rules.yaml", NONPROD, "dev")])
def test_the_shipped_rules_add_the_findings_approver_for_actionable_findings_only(path, served, env):
    rules = ApprovalRules.load(ROOT / path, served)
    facts = {"plugin": "adoption", "action": "adopt", "environment": env, "namespace": "abc-x", "capacity": "fits",
             "findingCount": 9, "actionableFindingCount": 0}
    base = sum(s.count for s in rules.decide(facts).slots)
    assert sum(s.count for s in rules.decide({**facts, "actionableFindingCount": 1}).slots) == base + 1
    assert sum(s.count for s in rules.decide({**facts, "findingCount": 0}).slots) == base, "findingCount alone adds nothing"


@pytest.mark.parametrize("path", ["deploy/manifests/environments/crc/20-config.yaml", "deploy/manifests/environments/kind/20-config.yaml"])
def test_crc_and_kind_read_the_same_fact(path):
    data = next(d for d in yaml.safe_load_all((ROOT / path).read_text()) if d and "approval-rules.yaml" in (d.get("data") or {}))
    rules = [r["when"] for r in yaml.safe_load(data["data"]["approval-rules.yaml"])["thresholds"] if "adoption" in r["when"]]
    assert rules == ['plugin == "adoption"', 'plugin == "adoption" and actionableFindingCount > 0']


# --------------------------------------------------------------------------- #747: the reason of a skipped key


def _namespace(managers: dict[str, list[str]]) -> dict:
    labels = {k: "x" for keys in managers.values() for k in keys}
    return {"metadata": {"name": "n", "labels": labels, "managedFields": [
        {"manager": m, "operation": "Update", "fieldsV1": {"f:metadata": {"f:labels": {f"f:{k}": {} for k in keys}}}}
        for m, keys in managers.items()]}}


def test_a_key_that_kubectl_create_wrote_is_left_out_with_a_reason_that_is_true_of_it():
    """kubectl create's manager is `kubectl-create` ("--field-manager ... Default: kubectl-create", kubectl create
    reference): a client, not a server component. Argo CD's migration takes over kubectl-client-side-apply only, so the key
    is left out, and the reason says so."""
    [d] = skipped_keys(_namespace({"kubectl-create": ["kubernetes.io/metadata.name"]}), AdoptionSettings())
    assert (d.key, d.kept, d.managers) == ("kubernetes.io/metadata.name", False, ("kubectl-create",))
    assert "server component" not in d.why
    assert d.why == ("none of its managers is kubectl-client-side-apply, whose fields Argo CD's client-side apply migration "
                     "takes over, so it stays on the cluster")
    # A controller's key gets the same, true, reason; a migration manager's key is still kept.
    [c] = skipped_keys(_namespace({"pod-security-admission-label-synchronization-controller": ["pod-security.kubernetes.io/warn"]}),
                       AdoptionSettings())
    assert (c.kept, c.why) == (False, d.why)
    [k] = skipped_keys(_namespace({"kubectl-client-side-apply": ["pod-security.kubernetes.io/enforce"]}), AdoptionSettings())
    assert k.kept


def test_a_key_that_only_a_delivery_applied_is_kept_and_no_other_is():
    """#750's review: a key that only argocd-controller or cmapi-deliverer owns through Apply goes on that manager's next
    apply if Git leaves it out, so it is kept. The same managers' Update, another manager beside them, or no owner at all
    leave a manager that keeps the key, so it is left out."""
    key = "pod-security.kubernetes.io/enforce"

    def decide(*entries: tuple[str, str]) -> tuple[bool, str]:
        ns = {"metadata": {"name": "n", "labels": {key: "restricted", "kubernetes.io/metadata.name": "n"}, "managedFields": [
            {"manager": m, "operation": op, "fieldsV1": {"f:metadata": {"f:labels": {f"f:{key}": {}}}}} for m, op in entries]
            + [{"manager": "kubectl-create", "operation": "Update",
                "fieldsV1": {"f:metadata": {"f:labels": {"f:kubernetes.io/metadata.name": {}}}}}]}}
        [d] = [d for d in skipped_keys(ns, AdoptionSettings()) if d.key == key]
        return d.kept, d.why

    for manager in ("argocd-controller", "cmapi-deliverer"):
        kept, why = decide((manager, "Apply"))
        assert kept and "would remove it" in why, why
    assert decide(("argocd-controller", "Apply"), ("cmapi-deliverer", "Apply"))[0]
    assert not decide(("argocd-controller", "Update"))[0]
    assert not decide(("argocd-controller", "Apply"), ("pod-security-admission-label-synchronization-controller", "Update"))[0]
    assert decide() == (False, "no field manager owns it")


# --------------------------------------------------------------------------- D2 and #748: what stays unmanaged


@pytest.mark.parametrize("counts, words", [
    ({"ServiceAccount": None, "RoleBinding": None},
     "an unknown number of ServiceAccounts and an unknown number of RoleBindings stay unmanaged"),
    ({"ServiceAccount": 3, "RoleBinding": 3}, "3 ServiceAccounts and 3 RoleBindings stay unmanaged"),
    ({"ServiceAccount": 1, "RoleBinding": 0}, "1 ServiceAccount stays unmanaged"),
    ({"ServiceAccount": 0, "RoleBinding": None}, "an unknown number of RoleBindings stay unmanaged"),
    ({"ServiceAccount": 0, "RoleBinding": 0}, None),
])
def test_what_stays_unmanaged_in_words(counts, words):
    assert unmanaged_phrase(counts) == words
