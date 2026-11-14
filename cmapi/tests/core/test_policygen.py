"""#212: the Kyverno bundle rendered from the configuration (core/policygen.py), run through the real Kyverno CLI.

The CLI is the image's pin (cmapi/Containerfile, v1.20.0). A test that needs it is skipped when no `kyverno` is on PATH,
and fails instead when CMAPI_REQUIRE_KYVERNO=1, as CI sets it, so CI never passes by skipping.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import PolicyGenError, index_of, render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from cmapi.core.tiers import TierCatalog
from cmapi.core.validate import CliValidator, PolicyEngineMissing
from cmapi.tools.policies import main as policies_tool
from conftest import ALL_ENVS, EX, INSTANCES

COMPANY = EX / "cluster-configs/policies/metadata-keys.company.yaml"
SHIPPED = EX / "cluster-configs/policies/metadata-keys.yaml"
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}
# The two optional keys are annotations, with their formats (the owner's decision on #234).
OPTIONAL = {"company.net/mnemonic-group-contact": "abc-team@company.net",
            "company.net/mnemonic-confluence": "https://wiki.company.net/abc"}
BASE = "clusters/OCP_GF15/namespaces/abc-rnd/"


@pytest.fixture(scope="module")
def kyverno() -> str:
    found = shutil.which("kyverno")
    if not found:
        if os.environ.get("CMAPI_REQUIRE_KYVERNO") == "1":
            pytest.fail("CMAPI_REQUIRE_KYVERNO=1 and no kyverno on PATH")
        pytest.skip("no kyverno on PATH")
    out = subprocess.run([found, "version"], capture_output=True, text=True, timeout=30).stdout
    assert "v1.20.0" in out, f"the image pins Kyverno v1.20.0, PATH has {out.splitlines()[:1]}"
    return found


@pytest.fixture(scope="module")
def catalog() -> TierCatalog:
    return TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)


@pytest.fixture(scope="module")
def company() -> MetadataKeys:
    return MetadataKeys.load(COMPANY)


def write(tmp: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        f = tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return tmp


def apply(kyverno: str, policies: Path, resources: list[Path]) -> dict[str, list[tuple[str, str]]]:
    """{result: [(policy, message)]} of one `kyverno apply` with a JSON report."""
    r = subprocess.run([kyverno, "apply", str(policies), "--resource", ",".join(map(str, resources)), "-p",
                        "--output-format", "json"], capture_output=True, text=True, timeout=120)
    report = json.loads(r.stdout)
    out: dict[str, list[tuple[str, str]]] = {}
    for res in report["results"]:
        out.setdefault(res["result"], []).append((res["policy"], res.get("message", "")))
    return out


def owners_sample(catalog, keys, tier="small", **over) -> dict[str, str]:
    renderer = ManifestRenderer(catalog, keys)
    spec = dict(namespace="abc-rnd", cluster_id="OCP_GF15", instance="nonprod", env="rnd", tier=tier,
                request_id="req-1", requested_by_user="ola", requested_by_email="ola@company.net", labels=SENT,
                annotations=OPTIONAL)
    spec.update(over)
    files = renderer.render(NamespaceSpec(**spec))
    return {k.removeprefix(BASE): v for k, v in files.items() if k.startswith(BASE)}


def resources(tmp: Path, docs: dict[str, dict | str]) -> list[Path]:
    out = []
    for name, doc in docs.items():
        f = tmp / name
        f.write_text(doc if isinstance(doc, str) else yaml.safe_dump(doc))
        out.append(f)
    return out


CHECKED = ("namespace.yaml", "resourcequota.yaml", "limitrange.yaml")


# ----------------------------------------------------------------------------------------------- without the CLI
def test_each_mode_renders_its_actions_and_off_renders_nothing(catalog, company):
    policy, problems = PolicySettings.parse({"mode": "enforce", "environments": {"rnd": {"mode": "audit"},
                                                                                  "qa": {"mode": "off"}}}, ALL_ENVS)
    assert problems == []
    files = render_bundle(catalog, company, policy, ALL_ENVS, "nonprod")
    actions = {}
    for rel, text in files.items():
        if rel.endswith(".yaml"):
            for doc in yaml.safe_load_all(text):
                actions.setdefault(rel.split("/")[1], set()).add(tuple(doc["spec"]["validationActions"]))
    assert actions == {"rnd": {("Audit", "Warn")}, "dev": {("Deny",)}, "uat": {("Deny",)}, "prod": {("Deny",)}}
    assert not any(rel.startswith("env/qa/") for rel in files)
    assert render_bundle(catalog, company, PolicySettings(engine="none"), ALL_ENVS, "nonprod") == {}


def test_a_tier_above_the_maximum_stops_the_render(catalog, company):
    raw = copy.deepcopy(catalog.file.model_dump())
    raw["environments"]["rnd"]["custom"]["max"]["requests.cpu"] = "16"     # large asks 32
    with pytest.raises(PolicyGenError, match="tier large in rnd: requests.cpu 32 is above the maximum 16"):
        render_bundle(TierCatalog(raw, ALL_ENVS), company, PolicySettings(), {"rnd"}, "nonprod")


def test_the_index_names_one_key_and_rule_for_each_policy(catalog, company):
    files = render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod")
    names = [doc["metadata"]["name"] for rel, t in files.items() if rel.endswith(".yaml") for doc in yaml.safe_load_all(t)]
    index = index_of(files)
    assert sorted(names) == sorted(index) and len(names) == len(set(names))
    assert index["cmapi-metadata-rnd-label-company-net-lob-enum"] == {"kind": "label", "key": "company.net/lob", "rule": "enum"}
    assert index["cmapi-quota-rnd-quota-requests-cpu-max"] == {"kind": "quota", "key": "requests.cpu", "rule": "max"}


@pytest.mark.parametrize("instance", sorted(INSTANCES))
def test_the_committed_example_bundle_is_the_render_of_each_instance(instance, capsys):
    """The agreement of the repository: examples/cluster-configs/policies/env/ is what each instance renders."""
    policies_tool(["check", "--config-dir", str(EX / "instances" / instance), "--metadata-keys", str(SHIPPED),
                   "--dir", str(EX / "cluster-configs/policies")])
    assert "match the configuration" in capsys.readouterr().out


def test_the_check_refuses_a_hand_edit_and_a_configuration_that_was_not_rendered(tmp_path):
    root = tmp_path / "policies"
    shutil.copytree(EX / "cluster-configs/policies", root)
    args = ["--config-dir", str(EX / "instances/nonprod"), "--metadata-keys", str(SHIPPED)]
    edited = root / "env/rnd/cmapi-quota-rnd.yaml"
    edited.write_text(edited.read_text().replace('quantity("32")', 'quantity("64")'))
    with pytest.raises(SystemExit, match="1 rendered policy files do not match"):
        policies_tool(["check", *args, "--dir", str(root)])
    policies_tool(["render", *args, "--out", str(root)])
    policies_tool(["check", *args, "--dir", str(root)])
    # Another instance's environments in the same folder are left alone.
    assert (root / "env/prod/deny-expiry-in-prod.yaml").read_text() == \
        (EX / "cluster-configs/policies/env/prod/deny-expiry-in-prod.yaml").read_text()


# --------------------------------------------------------------------------------------------------- with the CLI
def test_the_owners_sample_passes_its_bundle_in_each_tier(kyverno, catalog, company, tmp_path):
    bundle = write(tmp_path / "b", render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod"))
    for tier in ("small", "medium", "large"):
        files = owners_sample(catalog, company, tier=tier)
        got = apply(kyverno, bundle / "env/rnd", resources(tmp_path, {n: files[n] for n in CHECKED}))
        assert set(got) == {"pass"}, (tier, got)


def test_the_example_namespace_passes_the_committed_dev_bundle(kyverno):
    folder = EX / "cluster-configs/clusters/OCP_GF15/namespaces/payments-dev"
    got = apply(kyverno, EX / "cluster-configs/policies/env/dev", [folder / n for n in CHECKED])
    assert set(got) == {"pass"}, got


def test_each_rule_refuses_with_its_key_the_value_and_the_configured_value(kyverno, catalog, company, tmp_path):
    bundle = write(tmp_path / "b", render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod"))
    files = owners_sample(catalog, company)
    ns, rq, lr = (yaml.safe_load(files[n]) for n in CHECKED)
    labels = ns["metadata"]["labels"]
    labels.update({"name": "aao-rnd", "company.net/lob": "retail", "company.net/cl": "7", "cmapi.net/env": "prod"})
    del labels["company.net/mnemonic"]
    rq["spec"]["hard"].update({"requests.cpu": "40", "services.loadbalancers": "3"})
    container = next(i for i in lr["spec"]["limits"] if i["type"] == "Container")
    container["max"]["cpu"] = "20"
    container["default"]["memory"] = "128Mi"
    got = dict(apply(kyverno, bundle / "env/rnd", resources(tmp_path, {"ns.yaml": ns, "rq.yaml": rq, "lr.yaml": lr}))["fail"])
    assert got == {
        "cmapi-metadata-rnd-label-name-derived": 'the label name is "aao-rnd"; cmapi sets it to the namespace name',
        "cmapi-metadata-rnd-label-company-net-lob-enum": 'the label company.net/lob is "retail"; it must be: required; one of amgsst',
        "cmapi-metadata-rnd-label-company-net-cl-enum": 'the label company.net/cl is "7"; it must be: required; one of 0, 1, 2, 3',
        "cmapi-metadata-rnd-label-company-net-mnemonic-pattern":
            "the label company.net/mnemonic is missing; it must be: required; must match ^[a-z]{3}$; "
            "the start of the namespace name, before its first '-'",
        "cmapi-metadata-rnd-label-cmapi-net-env-derived":
            "the label cmapi.net/env is prod; it must be rnd, the environment of this policy",
        "cmapi-quota-rnd-quota-requests-cpu-max":
            "requests.cpu 40 is above the rnd maximum of 32; a bound of tiers.yaml, which approval does not lift",
        "cmapi-quota-rnd-quota-services-loadbalancers-max":
            "services.loadbalancers 3 is above the rnd maximum of 2; a bound of tiers.yaml, which approval does not lift",
        "cmapi-limits-rnd-limit-limitrange-container-max-cpu-max":
            "limitRange.container.max.cpu 20 is above the rnd maximum of 16; a bound of tiers.yaml, which approval does not lift",
        "cmapi-limits-rnd-limit-limitrange-container-default-memory-order":
            "container default memory 128Mi is below its defaultRequest 256Mi",
    }


@pytest.mark.parametrize("labels, annotations, key", [
    ({"company.net/lob": "retail"}, {}, "company.net/lob"),
    ({"company.net/cl": "9"}, {}, "company.net/cl"),
    ({"company.net/mnemonic": "abcd"}, {}, "company.net/mnemonic"),
    ({"company.net/mnemonic": "xyz"}, {}, "company.net/mnemonic"),
    ({"name": "aao-rnd"}, {}, "name"),
    ({"company.net/app-environment": "prod"}, {}, "company.net/app-environment"),
    ({}, {"company.net/app-environment": "dev"}, "company.net/app-environment"),
    ({}, {"company.net/mnemonic-group-contact": "abc-team@other.org"}, "company.net/mnemonic-group-contact"),
    ({}, {"company.net/mnemonic-confluence": "ftp://wiki.company.net/abc"}, "company.net/mnemonic-confluence"),
])
def test_python_and_kyverno_refuse_the_same_value(kyverno, catalog, company, tmp_path, labels, annotations, key):
    """The agreement of the two checkers: each value that cmapi's own check refuses, the rendered policy refuses too."""
    sources = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "OCP_GF15", "instance": "nonprod"}
    assert key in {e.get("key") for e in company.validate({**SENT, **labels}, annotations, operator=False, sources=sources)}
    bundle = write(tmp_path / "b", render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod"))
    ns = yaml.safe_load(owners_sample(catalog, company)["namespace.yaml"])
    ns["metadata"]["labels"].update(labels)
    ns["metadata"]["annotations"].update(annotations)
    failed = [p for p, _ in apply(kyverno, bundle / "env/rnd", resources(tmp_path, {"ns.yaml": ns})).get("fail", [])]
    index = index_of(render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod"))
    assert {index[p]["key"] for p in failed} == {key}, failed


def test_a_changed_bound_changes_the_policy_and_its_message(kyverno, catalog, company, tmp_path):
    raw = copy.deepcopy(catalog.file.model_dump())
    raw["environments"]["rnd"]["custom"]["max"]["requests.cpu"] = "40"
    files = owners_sample(catalog, company)
    rq = yaml.safe_load(files["resourcequota.yaml"])
    rq["spec"]["hard"]["requests.cpu"] = "36"
    res = resources(tmp_path, {"rq.yaml": rq})
    before = write(tmp_path / "before", render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod"))
    after = write(tmp_path / "after", render_bundle(TierCatalog(raw, ALL_ENVS), company, PolicySettings(), {"rnd"}, "nonprod"))
    assert dict(apply(kyverno, before / "env/rnd", res)["fail"]) == {
        "cmapi-quota-rnd-quota-requests-cpu-max":
            "requests.cpu 36 is above the rnd maximum of 32; a bound of tiers.yaml, which approval does not lift"}
    assert set(apply(kyverno, after / "env/rnd", res)) == {"pass"}
    # 36000m is the same amount as 36: quantities are compared, not their text.
    rq["spec"]["hard"]["requests.cpu"] = "41000m"
    assert "above the rnd maximum of 40" in apply(kyverno, after / "env/rnd", resources(tmp_path, {"rq.yaml": rq}))["fail"][0][1]


def test_prod_never_expires_as_the_hand_written_policy_did(kyverno, catalog, tmp_path):
    keys = MetadataKeys.load(SHIPPED)
    bundle = write(tmp_path / "b", render_bundle(catalog, keys, PolicySettings(), {"prod"}, "prod"))
    for kind, key in (("annotations", "cmapi.net/expires-at"), ("labels", "cmapi.net/expiry"),
                      ("labels", "cleanup.kyverno.io/ttl")):
        ns = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "x-prod", kind: {key: ""}}}
        got = apply(kyverno, bundle / "env/prod", resources(tmp_path, {"ns.yaml": ns}))
        assert ("deny-expiry-in-prod", "Production namespaces never expire: remove cmapi.net/expires-at, "
                "cmapi.net/expiry and cleanup.kyverno.io/ttl.") in got["fail"], key


def test_an_unmanaged_namespace_is_skipped_by_the_metadata_policies(kyverno, catalog, company, tmp_path):
    bundle = write(tmp_path / "b", render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod"))
    ns = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "openshift-monitoring", "labels": {"a": "b"}}}
    assert set(apply(kyverno, bundle / "env/rnd", resources(tmp_path, {"ns.yaml": ns}))) == {"skip"}


# ------------------------------------------------------------------------------------------- the validator at plan time
def validator(catalog, keys, tmp_path, policy=PolicySettings(), envs=frozenset({"rnd"})) -> CliValidator:
    return CliValidator(tmp_path / "no-hand-written", kubeconform="true", policy=policy, environments=set(envs),
                        bundle=render_bundle(catalog, keys, policy, envs, "nonprod"))


def folder(files: dict[str, str]) -> dict[str, str]:
    return {BASE + n: files[n] for n in CHECKED}


def test_the_validator_finds_each_failed_key_with_its_file(kyverno, catalog, company, tmp_path):
    files = owners_sample(catalog, company)
    rq = yaml.safe_load(files["resourcequota.yaml"])
    rq["spec"]["hard"]["requests.cpu"] = "40"
    files["resourcequota.yaml"] = yaml.safe_dump(rq)
    found = validator(catalog, company, tmp_path).validate(folder(files), "OCP_GF15", "rnd")
    assert [(f.source, f.rule, f.path, f.severity) for f in found if f.source != "kubeconform"] == \
        [("kyverno", "cmapi-quota-rnd-quota-requests-cpu-max", BASE + "resourcequota.yaml", "error")]


def test_a_value_that_git_already_holds_is_not_refused_and_a_changed_one_is(kyverno, catalog, company, tmp_path):
    """#214 and D9: a later, lower bound does not refuse a namespace whose approved value Git holds."""
    files = owners_sample(catalog, company)
    rq = yaml.safe_load(files["resourcequota.yaml"])
    rq["spec"]["hard"]["requests.cpu"] = "40"
    files["resourcequota.yaml"] = yaml.safe_dump(rq)
    previous = folder(files)
    v = validator(catalog, company, tmp_path)
    ns = yaml.safe_load(files["namespace.yaml"])
    ns["metadata"]["labels"]["company.net/cl"] = "2"                     # a label change, the quota unchanged
    now = {**previous, BASE + "namespace.yaml": yaml.safe_dump(ns)}
    assert [f for f in v.validate(now, "OCP_GF15", "rnd", previous=previous) if f.source != "kubeconform"] == []
    rq["spec"]["hard"]["requests.cpu"] = "40000m"                        # the same amount, other text
    now[BASE + "resourcequota.yaml"] = yaml.safe_dump(rq)
    assert [f for f in v.validate(now, "OCP_GF15", "rnd", previous=previous) if f.source != "kubeconform"] == []
    rq["spec"]["hard"]["requests.cpu"] = "41"                            # a change: checked against the bound
    now[BASE + "resourcequota.yaml"] = yaml.safe_dump(rq)
    assert [f.rule for f in v.validate(now, "OCP_GF15", "rnd", previous=previous) if f.source == "kyverno"] == \
        ["cmapi-quota-rnd-quota-requests-cpu-max"]


def test_audit_warns_on_a_violation_but_keeps_an_evaluation_error_an_error(kyverno, catalog, company, tmp_path):
    policy = PolicySettings(default_mode="audit")
    v = validator(catalog, company, tmp_path, policy=policy)
    files = owners_sample(catalog, company)
    rq = yaml.safe_load(files["resourcequota.yaml"])
    rq["spec"]["hard"]["requests.cpu"] = "40"
    files["resourcequota.yaml"] = yaml.safe_dump(rq)
    assert [(f.rule, f.severity) for f in v.validate(folder(files), "OCP_GF15", "rnd") if f.source == "kyverno"] == \
        [("cmapi-quota-rnd-quota-requests-cpu-max", "warning")]
    rq["spec"]["hard"]["requests.cpu"] = "forty"                         # not a quantity: the policy cannot evaluate
    files["resourcequota.yaml"] = yaml.safe_dump(rq)
    errors = [f for f in v.validate(folder(files), "OCP_GF15", "rnd") if f.rule == "cmapi-quota-rnd-quota-requests-cpu-max"]
    assert [(f.source, f.severity) for f in errors] == [("cmapi", "error")]
    assert errors[0].message.startswith("kyverno could not evaluate the policy")


def test_a_policy_that_gives_no_result_for_a_file_it_matches_is_a_finding(kyverno, catalog, company, tmp_path):
    """The guard that replaces "Applying 0 policy rule(s)", which the JSON mode does not print: a policy that the CLI does
    not understand gives no result (measured with an unknown apiVersion), and with no policy that it understands the
    CLI writes no report at all. Each is a finding of cmapi, so it stays an error in audit."""
    hand = tmp_path / "hand"
    hand.mkdir()
    (hand / "unknown.yaml").write_text(yaml.safe_dump({
        "apiVersion": "policies.kyverno.io/v9", "kind": "ValidatingPolicy", "metadata": {"name": "unknown-version"},
        "spec": {"validationActions": ["Deny"],
                 "matchConstraints": {"resourceRules": [{"apiGroups": [""], "apiVersions": ["v1"],
                                                         "operations": ["CREATE", "UPDATE"], "resources": ["namespaces"]}]},
                 "validations": [{"expression": "true"}]}}))
    ns = {BASE + "namespace.yaml": owners_sample(catalog, company)["namespace.yaml"]}
    alone = CliValidator(hand, kubeconform="true", policy=PolicySettings(default_mode="audit"), environments={"rnd"})
    found = [f for f in alone.validate(ns, "OCP_GF15", "rnd") if f.source != "kubeconform"]
    assert [(f.source, f.severity) for f in found] == [("cmapi", "error")] and "with no report" in found[0].message
    mixed = CliValidator(hand, kubeconform="true", policy=PolicySettings(default_mode="audit"), environments={"rnd"},
                         bundle=render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod"))
    found = [f for f in mixed.validate(ns, "OCP_GF15", "rnd") if f.source != "kubeconform"]
    assert [(f.source, f.rule, f.severity, f.message) for f in found] == \
        [("cmapi", "unknown-version", "error", "policy not understood by the CLI (no result for this file)")]


def test_a_kyverno_that_is_not_the_pinned_version_stops_the_start(kyverno, tmp_path, monkeypatch):
    monkeypatch.setenv("CMAPI_KYVERNO_VERSION", "v1.20.0")
    CliValidator(tmp_path, kyverno=kyverno, policy=PolicySettings(), environments={"rnd"})
    monkeypatch.setenv("CMAPI_KYVERNO_VERSION", "v1.21.0")
    with pytest.raises(PolicyEngineMissing, match=r"is not the pinned v1.21.0 \(Version: v1.20.0\)"):
        CliValidator(tmp_path, kyverno=kyverno, policy=PolicySettings(), environments={"rnd"})
    CliValidator(tmp_path, kyverno=kyverno, policy=PolicySettings(default_mode="off"), environments={"rnd"})
