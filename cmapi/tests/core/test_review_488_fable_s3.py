"""Suggestion S3 of Fable's review of #488: pin what makes `variables.update ||` on the suffix check safe (M1)."""
import yaml

from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from test_policygen import catalog  # noqa: F401
from test_review_479_suffix_policy import ENV_KEY, suffix_keys


def test_an_update_that_changes_the_environment_label_is_still_refused_by_the_derived_check(catalog):
    """The suffix check passes every UPDATE, so the derived check is what stops an UPDATE to another environment: it
    passes an UPDATE only when the label is unchanged (oldObject), and otherwise wants this policy's environment."""
    bundle = render_bundle(catalog, suffix_keys(), PolicySettings(), {"rnd"}, "nonprod")
    docs = [d for text in bundle.values() for d in yaml.safe_load_all(text) if d and d.get("kind") == "ValidatingPolicy"]
    message = f"the label {ENV_KEY} is not what cmapi sets it to: the environment rnd"
    found = [v["expression"] for d in docs for v in d["spec"]["validations"] if v.get("message") == message]
    assert len(found) == 1
    same, _, value = found[0].rpartition(" || ")
    assert same.startswith("(variables.update && ") and "oldObject" in same
    assert "oldObject" not in value and '== "rnd"' in value
