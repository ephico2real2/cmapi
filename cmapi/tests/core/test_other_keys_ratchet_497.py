"""#497: the policy on the keys that no stanza declares keeps a disallowed key that Git already holds, as the policies on
the declared keys keep theirs (_same at admission, _held at plan time).

#492 keeps such a key on a change (design section 3, row 3) and lets a PATCH remove it. Before this fix, the policy for
keys outside allowOther.prefixes refused it on every change, so with Kyverno enforcing, a namespace that held one could
be changed only by removing it. Now:
- at plan time, a failure of that policy is dropped when each key it names has the same value in the previous version;
- at admission, the policy does not count a key whose value oldObject holds.

The plan-time drop reads the keys from the policy's own message (policygen.outside_keys). If the message cannot be read,
the failure stays: a false refusal at worst, never a false pass.

The CLI is the image's pin, skipped without `kyverno` on PATH (CMAPI_REQUIRE_KYVERNO=1 fails instead)."""
from __future__ import annotations

import yaml
import pytest

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import outside_keys, render_bundle
from cmapi.core.tiers import TierCatalog
from cmapi.core.validate import CliValidator
from conftest import ALL_ENVS, EX
from test_policygen import kyverno, owners_sample  # noqa: F401  (kyverno is a fixture)

DISALLOWED = "legacy.example.org/owner"           # outside allowOther.prefixes ["", "*.company.net/"], declared nowhere
FOLDER = "clusters/OCP_GF15/namespaces/abc-rnd/"


def _validator(tmp_path) -> CliValidator:
    catalog = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.company.yaml")
    enforce = PolicySettings(default_mode="enforce")
    d = tmp_path / "policies"
    d.mkdir()
    return CliValidator(d, policy=enforce, environments={"rnd"}, bundle=render_bundle(catalog, keys, enforce, {"rnd"}, "nonprod"))


def _folder(extra_labels: dict[str, str]) -> dict[str, str]:
    """The rendered folder of abc-rnd, with extra labels on its namespace.yaml as Git or the change holds them."""
    catalog = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.company.yaml")
    files = {FOLDER + k: t for k, t in owners_sample(catalog, keys).items()}
    path = FOLDER + "namespace.yaml"
    doc = yaml.safe_load(files[path])
    doc["metadata"]["labels"].update(extra_labels)
    files[path] = yaml.safe_dump(doc, sort_keys=False)
    return files


def _other_key_findings(v: CliValidator, files: dict[str, str], previous: dict[str, str] | None) -> list[str]:
    return [f.rule for f in v.validate(files, "OCP_GF15", "rnd", previous) if f.source == "kyverno" and "other-keys" in f.rule]


def test_a_disallowed_key_that_git_holds_is_kept_on_a_change(kyverno, tmp_path, monkeypatch):
    monkeypatch.setattr("cmapi.core.validate.CliValidator._kubeconform", lambda self, paths: [])
    v = _validator(tmp_path)
    previous = _folder({DISALLOWED: "ops"})
    change = _folder({DISALLOWED: "ops", "team.company.net/squad": "checkout"})   # adds an allowed key, keeps the held one
    assert _other_key_findings(v, change, previous) == []


def test_a_new_disallowed_key_is_still_refused(kyverno, tmp_path, monkeypatch):
    monkeypatch.setattr("cmapi.core.validate.CliValidator._kubeconform", lambda self, paths: [])
    v = _validator(tmp_path)
    assert _other_key_findings(v, _folder({DISALLOWED: "ops"}), _folder({})) != []
    assert _other_key_findings(v, _folder({DISALLOWED: "ops"}), None) != [], "a create holds nothing"


def test_a_disallowed_key_whose_value_changes_is_refused(kyverno, tmp_path, monkeypatch):
    monkeypatch.setattr("cmapi.core.validate.CliValidator._kubeconform", lambda self, paths: [])
    v = _validator(tmp_path)
    assert _other_key_findings(v, _folder({DISALLOWED: "ops2"}), _folder({DISALLOWED: "ops"})) != []


def test_the_parser_reads_the_keys_that_the_policys_own_message_names(kyverno, tmp_path, monkeypatch):
    """outside_keys and the message that policygen writes are one contract: this pins them together."""
    monkeypatch.setattr("cmapi.core.validate.CliValidator._kubeconform", lambda self, paths: [])
    v = _validator(tmp_path)
    findings = [f for f in v.validate(_folder({DISALLOWED: "ops", "b.example.org/x": "y"}), "OCP_GF15", "rnd")
                if f.source == "kyverno" and "other-keys" in f.rule]
    assert [outside_keys(f.message, "label") for f in findings] == [["b.example.org/x", DISALLOWED]]
    assert outside_keys("a message of another policy", "label") is None
    assert outside_keys("the label keys a, b are not declared in metadata-keys.yaml", "annotation") is None


@pytest.mark.parametrize("diagnostic", [
    "the label keys x are not declared in metadata-keys.yaml",
    "the label keys the label keys x are not declared in metadata-keys.yaml, and are outside extraLabels.allowOther.prefixes [none]",
    "the label keys x are not declared in metadata-keys.yaml, and are outside extraLabels.allowOther.prefixes [none] (report incomplete)",
])
def test_incomplete_or_concatenated_prefix_diagnostics_are_unrecognized(diagnostic):
    assert outside_keys(diagnostic, "label") is None


def test_a_key_that_holds_the_separator_keeps_the_failure():
    """An offline manifest can hold a key that Kubernetes would refuse. `env, team` reads as the two held keys `env` and `team`."""
    from cmapi.core.validate import _held_outside

    message = ("the label keys env, team are not declared in metadata-keys.yaml, and are outside "
               "extraLabels.allowOther.prefixes [none]")
    assert outside_keys(message, "label") == ["env", "team"]
    old = {"metadata": {"labels": {"env": "dev", "team": "a"}}}
    new = {"metadata": {"labels": {"env": "dev", "team": "a", "env, team": "x"}}}
    assert _held_outside("label", message, new, old) is False
    assert _held_outside("label", message, old, old) is True
