"""#479, review of PR #488 (F03): the generated Kyverno bundle checks the end of the namespace name as cmapi does: on a
create, the name ends with "-<environment>" with or without a desired name; a change of a namespace named before the rule passes,
at plan time and at admission alike. Run through the real Kyverno CLI, as test_policygen.py does."""
from __future__ import annotations

import yaml
import pytest

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from test_policygen import COMPANY, OPTIONAL, SENT, apply, catalog, kyverno, resources, validator, write  # noqa: F401

ENV_KEY = "company.net/app-environment"


def suffix_keys() -> MetadataKeys:
    config = yaml.safe_load(COMPANY.read_text())
    config["requiredLabels"][ENV_KEY] = {"value": {"from": "environment"}, "namespaceSuffix": True}
    return MetadataKeys(config)


def rendered(catalog, keys, name: str) -> dict[str, str]:
    """The folder that cmapi renders for the namespace `name` on the rnd cluster OCP_GF15, by path."""
    spec = NamespaceSpec(namespace=name, cluster_id="OCP_GF15", instance="nonprod", env="rnd", tier="small",
                         request_id="req-1", requested_by_user="ola", requested_by_email="ola@company.net",
                         labels=SENT, annotations=OPTIONAL)
    return {p: t for p, t in ManifestRenderer(catalog, keys).render(spec).items() if t is not None}


def failures_on_create(kyverno, catalog, keys, tmp_path, name: str) -> list[str]:
    bundle = write(tmp_path / "bundle", render_bundle(catalog, keys, PolicySettings(), {"rnd"}, "nonprod"))
    doc = yaml.safe_load(rendered(catalog, keys, name)[f"clusters/OCP_GF15/namespaces/{name}/namespace.yaml"])
    results = apply(kyverno, bundle / "env/rnd", resources(tmp_path, {"namespace.yaml": doc}))
    assert results.get("pass") and not results.get("error"), results
    return [message for _, message in results.get("fail", [])]


SUFFIX_REFUSAL = (f"the namespace name must end with '-' and the value of the label {ENV_KEY}, "
                  "joined to the prefix directly or with a desired name between them "
                  "that starts and ends with a letter or digit")


def test_the_generated_policy_refuses_a_name_that_ends_with_another_environment(kyverno, catalog, tmp_path):
    keys = suffix_keys()
    assert failures_on_create(kyverno, catalog, keys, tmp_path, "abc-payments-rnd") == []
    assert failures_on_create(kyverno, catalog, keys, tmp_path, "abc-payments-dev") == [SUFFIX_REFUSAL]


def test_the_generated_policy_allows_a_team_wide_name_and_refuses_an_empty_segment(kyverno, catalog, tmp_path):
    keys = suffix_keys()
    assert failures_on_create(kyverno, catalog, keys, tmp_path, "abc-rnd") == []
    assert failures_on_create(kyverno, catalog, keys, tmp_path, "abc--rnd") == [SUFFIX_REFUSAL]


@pytest.mark.parametrize("name,accepted", [
    ("abc--x-rnd", False), ("abc-x--rnd", False), ("abc---rnd", False),
    ("abc-x-y-rnd", True), ("abc-x--y-rnd", True), ("abc-1-rnd", True),
])
def test_the_generated_policy_requires_alphanumeric_middle_ends(kyverno, catalog, tmp_path, name, accepted):
    assert failures_on_create(kyverno, catalog, suffix_keys(), tmp_path, name) == \
        ([] if accepted else [SUFFIX_REFUSAL])


def test_a_change_of_a_namespace_named_before_the_rule_passes_the_plan_time_check(kyverno, catalog, tmp_path):
    keys = suffix_keys()
    base = "clusters/OCP_GF15/namespaces/abc-legacy/"
    now = rendered(catalog, keys, "abc-legacy")
    old_ns = yaml.safe_load(now[base + "namespace.yaml"])
    del old_ns["metadata"]["labels"][ENV_KEY]                 # rendered before the file declared the key
    previous = {**now, base + "namespace.yaml": yaml.safe_dump(old_ns)}
    check = validator(catalog, keys, tmp_path)
    assert [f.message for f in check.validate(now, "OCP_GF15", "rnd") if f.source == "kyverno"] == [SUFFIX_REFUSAL]
    assert [f for f in check.validate(now, "OCP_GF15", "rnd", previous=previous) if f.source == "kyverno"] == []


def test_at_admission_an_update_passes_the_suffix_check_as_a_change_cannot_rename(catalog):
    """The CLI runs each file as a CREATE, so the UPDATE branch is read from the rendered expression itself."""
    bundle = render_bundle(catalog, suffix_keys(), PolicySettings(), {"rnd"}, "nonprod")
    docs = [d for text in bundle.values() for d in yaml.safe_load_all(text) if d and d.get("kind") == "ValidatingPolicy"]
    expressions = [v["expression"] for d in docs for v in d["spec"]["validations"] if v.get("message") == SUFFIX_REFUSAL]
    assert len(expressions) == 1 and expressions[0].startswith("variables.update || (")


@pytest.mark.parametrize("name", ["abcd-x-rnd", "abcd--x-rnd", "ab-rnd"])
def test_514_a_name_with_another_prefix_is_refused_on_the_prefix_key_only(kyverno, catalog, tmp_path, name):
    failures = failures_on_create(kyverno, catalog, suffix_keys(), tmp_path, name)
    assert len(failures) == 1 and SUFFIX_REFUSAL not in failures, failures


def test_514_the_refusal_of_a_middle_says_the_rule(kyverno, catalog, tmp_path):
    assert failures_on_create(kyverno, catalog, suffix_keys(), tmp_path, "abc--x-rnd") == [SUFFIX_REFUSAL]
    assert SUFFIX_REFUSAL.endswith("that starts and ends with a letter or digit")
