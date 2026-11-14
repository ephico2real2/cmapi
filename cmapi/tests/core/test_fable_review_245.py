"""Fable's review of #245, F2: each rendered validation carries a static `message` next to its messageExpression.

Kyverno's ValidatingPolicy page (read 2026-11-14): "If the expression fails or produces an invalid string (empty,
whitespace-only, or multi-line), Kyverno falls back to the static message." An annotation value may hold a newline, so
without a static message the refusal at admission names neither the key nor the configured value.
"""
from __future__ import annotations

import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from cmapi.core.tiers import TierCatalog
from conftest import ALL_ENVS, EX
from test_policygen import apply, kyverno, resources, write  # noqa: F401  (the fixture)

KEYS = EX / "cluster-configs/policies/metadata-keys.yaml"


def _bundle():
    catalog = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    return catalog, render_bundle(catalog, MetadataKeys.load(KEYS), PolicySettings(), ALL_ENVS, "nonprod")


def test_each_rendered_validation_has_a_static_message_with_its_key_and_configured_value():
    catalog, bundle = _bundle()
    seen = 0
    for rel, text in bundle.items():
        if not rel.endswith(".yaml"):
            continue
        for doc in yaml.safe_load_all(text):
            for v in doc["spec"]["validations"]:
                seen += 1
                message = v.get("message", "")
                assert message.strip() and "\n" not in message, (doc["metadata"]["name"], message)
                assert v.get("messageExpression"), doc["metadata"]["name"]
    assert seen > 100
    quota = next(d for d in yaml.safe_load_all(bundle["env/rnd/cmapi-quota-rnd.yaml"])
                 if d["metadata"]["name"] == "cmapi-quota-rnd-quota-requests-cpu-max")
    bound = catalog.bounds("rnd").max["requests.cpu"]
    assert quota["spec"]["validations"][0]["message"] == \
        f"requests.cpu is above the rnd maximum of {bound}; a bound of tiers.yaml, which approval does not lift"
    meta = next(d for d in yaml.safe_load_all(bundle["env/rnd/cmapi-metadata-rnd.yaml"])
                if d["metadata"]["name"] == "cmapi-metadata-rnd-annotation-cmapi-net-team-dl-format")
    assert meta["spec"]["validations"][0]["message"] == \
        "the annotation cmapi.net/team-dl must be: required; an address in ephico2real.com"


def test_the_message_expression_still_wins_in_the_cli(kyverno, tmp_path):
    """The static message is a fallback only: the CLI's report still carries the offending value."""
    catalog, bundle = _bundle()
    policies = write(tmp_path / "p", {k: v for k, v in bundle.items() if k.startswith("env/rnd/") and k.endswith(".yaml")})
    rq = {"apiVersion": "v1", "kind": "ResourceQuota",
          "metadata": {"name": "q", "namespace": "abc-rnd", "labels": {"cmapi.net/managed": "true"}},
          "spec": {"hard": {"requests.cpu": "4000"}}}
    got = apply(kyverno, policies, resources(tmp_path, {"rq.yaml": rq}))
    bound = catalog.bounds("rnd").max["requests.cpu"]
    assert ("cmapi-quota-rnd-quota-requests-cpu-max",
            f"requests.cpu 4000 is above the rnd maximum of {bound}; a bound of tiers.yaml, which approval does not lift") in got["fail"]


# F3: the guard against a vacuous pass covers a hand-written policy of a kind that the CLI does not know.
from cmapi.core.validate import CliValidator  # noqa: E402
from test_policygen import owners_sample  # noqa: E402

HAND = """apiVersion: {api}
kind: {kind}
metadata: {{name: hand-written}}
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - {{apiGroups: [""], apiVersions: [v1], operations: [CREATE, UPDATE], resources: [namespaces]}}
  validations:
    - expression: "{expression}"
      message: the hand-written policy refuses every namespace
"""


def _validate(tmp_path, hand: str):
    catalog = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.company.yaml")
    d = tmp_path / f"hand{len(list(tmp_path.iterdir()))}"
    d.mkdir()
    (d / "hand.yaml").write_text(hand)
    v = CliValidator(d, policy=PolicySettings(), environments={"rnd"},
                     bundle=render_bundle(catalog, keys, PolicySettings(), {"rnd"}, "nonprod"))
    files = {"clusters/OCP_GF15/namespaces/abc-rnd/" + k: t for k, t in owners_sample(catalog, keys).items()}
    return [(f.source, f.rule, f.severity) for f in v.validate(files, "OCP_GF15", "rnd") if f.source != "kubeconform"]


import pytest  # noqa: E402


@pytest.mark.parametrize("api, kind", [("policies.kyverno.io/v1", "ValidatingPolicyy"), ("kyverno.io/v1", "ValidatingPolcy")])
def test_a_hand_written_policy_of_a_kind_the_cli_does_not_know_is_a_finding(kyverno, tmp_path, monkeypatch, api, kind):
    """On #240's head the CLI printed "Applying 0 policy rule(s)" for it, which was a finding. Next to the rendered
    bundle the JSON report just has no result for it."""
    monkeypatch.setattr("cmapi.core.validate.CliValidator._kubeconform", lambda self, paths: [])
    assert _validate(tmp_path, HAND.format(api=api, kind=kind, expression="false")) == [("cmapi", "hand-written", "error")]


def test_a_hand_written_policy_of_another_kind_that_the_cli_runs_is_no_finding(kyverno, tmp_path, monkeypatch):
    monkeypatch.setattr("cmapi.core.validate.CliValidator._kubeconform", lambda self, paths: [])
    hand = HAND.format(api="policies.kyverno.io/v1", kind="NamespacedValidatingPolicy", expression="true")
    assert _validate(tmp_path, hand) == []
    hand = HAND.format(api="policies.kyverno.io/v1", kind="NamespacedValidatingPolicy", expression="false")
    assert _validate(tmp_path, hand) == [("kyverno", "hand-written", "error")]
