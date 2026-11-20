"""#336: what the portal's New namespace form reads from metadata-keys.yaml, through GET /api/v1/metadata-keys.

- `title`: an optional rule field, emitted as the property's JSON Schema title (Validation 2020-12, 9.1), so a form labels the
  field with the config's words; the reference file gives the mockup's Team and Team DL.
- `x-cmapi-rule`: the rule in the validator's own words, so the browser says what a refusal of the API says.
- The portal's fixtures: the company file's answer (tests/api/metadata-keys.company.json) and the corpus of its
  differential test (tests/api/metadata-corpus.json, metadata_form_corpus.py). The portal's CI job has no Python, so these
  are committed files, held equal here to what the code builds. To write them again: CMAPI_WRITE_FIXTURES=1 with this file.
"""
from __future__ import annotations

import copy
import json
import os

import pytest
import yaml

from cmapi.core.metadata import KINDS, MetadataKeys
from conftest import EX
from metadata_form_corpus import build

SHIPPED = EX / "cluster-configs/policies/metadata-keys.yaml"
COMPANY = EX / "cluster-configs/policies/metadata-keys.company.yaml"
PORTAL = EX.parent / "cmapi-portal-ui/tests/api"
SAMPLES = EX.parent / "cmapi/src/cmapi/contract/samples.json"
WRITE = os.environ.get("CMAPI_WRITE_FIXTURES") == "1"


def raw(path) -> dict:
    return yaml.safe_load(path.read_text())


def with_rule(**fields) -> MetadataKeys:
    data = copy.deepcopy(raw(SHIPPED))
    data["requiredLabels"]["cmapi.net/team"] = {"pattern": "^[a-z0-9-]{2,40}$", "example": "payments", **fields}
    return MetadataKeys(data)


def test_a_title_is_the_property_title_on_create_and_beside_the_null_branch_on_a_patch():
    keys = with_rule(title="Owning team")
    assert keys.rules["label"]["cmapi.net/team"].title == "Owning team"
    assert keys.json_schema("label", "create")["properties"]["cmapi.net/team"]["title"] == "Owning team"
    optional = copy.deepcopy(raw(SHIPPED))
    optional["extraLabels"]["keys"]["cmapi.net/app"]["title"] = "App"
    patch = MetadataKeys(optional).json_schema("label", "patch")["properties"]["cmapi.net/app"]
    # The words of a nullable property sit beside its anyOf, as its description does (#328).
    assert patch["title"] == "App" and "title" not in patch["anyOf"][0], patch


def test_a_key_without_a_title_has_none_and_the_reference_file_titles_the_mockups_two_fields():
    company = MetadataKeys.load(COMPANY)
    assert all("title" not in p for kind in KINDS for p in company.json_schema(kind, "create")["properties"].values())
    shipped = MetadataKeys.load(SHIPPED).keys_view()
    assert shipped["labels"]["properties"]["cmapi.net/team"]["title"] == "Team"
    assert shipped["annotations"]["properties"]["cmapi.net/team-dl"]["title"] == "Team DL"
    assert [k for k, p in shipped["labels"]["properties"].items() if "title" in p] == ["cmapi.net/team"]


@pytest.mark.parametrize("title, problem", [(3, "title must be text, not the int 3"),
                                             ("  ", "title must be a non-empty text"),
                                             (["Team"], "title must be text, not a list")])
def test_the_loader_refuses_a_title_that_is_not_a_label(title, problem):
    with pytest.raises(ValueError, match=problem):
        with_rule(title=title)


@pytest.mark.parametrize("path", [SHIPPED, COMPANY], ids=["reference", "company"])
def test_x_cmapi_rule_is_the_validators_words_for_each_declared_key(path):
    """Each declared property says its rule as validate() says it, and a missing required key is refused in those words."""
    keys = MetadataKeys.load(path)
    for kind in KINDS:
        props = keys.json_schema(kind, "create")["properties"]
        for key, rule in keys.rules[kind].items():
            assert props[key]["x-cmapi-rule"] == rule.text(keys.email_domains), (kind, key)
        required = [k for k, r in keys.rules[kind].items() if r.required and not r.derived]
        details = {e["key"]: e["detail"] for e in keys.validate({}, {}, operator=False) if e.get("kind") == kind}
        assert {k: props[k]["x-cmapi-rule"] for k in required} == {k: details[k] for k in required}, kind
        for key in keys.operator_only:
            assert "x-cmapi-rule" not in props[key], "an operator-only key is not offered, and has no rule of its own"


def _write_or_compare(path, text: str) -> None:
    if WRITE:
        path.write_text(text)
    assert path.exists(), f"{path} is missing: run this test with CMAPI_WRITE_FIXTURES=1"
    assert path.read_text() == text, f"{path.name} is not what the code builds: run this test with CMAPI_WRITE_FIXTURES=1"


def instance_view(path):
    """GET /api/v1/metadata-keys of the reference instance with the metadata-keys.yaml at path (#479: with its
    expiration rules)."""
    from cmapi.core.docs import metadata_keys_view
    from cmapi.tools.openapi import load

    cfg = load(path, None)
    return metadata_keys_view(cfg.metadata, cfg.expiration, cfg.raw_instance["instance"]["allowedEnvironments"])


def test_the_portals_company_fixture_is_the_company_files_answer():
    """The stand-in API of the portal's suite serves it as GET /api/v1/metadata-keys of a company instance."""
    _write_or_compare(PORTAL / "metadata-keys.company.json",
                      json.dumps(instance_view(COMPANY), indent=2, ensure_ascii=False) + "\n")


def test_the_recorded_sample_is_the_reference_files_answer():
    """The stand-in serves the recorded sample for a reference instance. test_api_samples compares a sample's shape only,
    so a change of a rule's words or pattern would leave the sample behind: this holds its values."""
    sample = json.loads(SAMPLES.read_text())["operations"]["core_metadata_keys"]["response"]["body"]
    assert sample == instance_view(SHIPPED)


def test_the_portals_corpus_is_the_one_this_code_builds():
    """The cases of the portal's differential test, with validate()'s verdict on each (tests/api/direct.test.mjs)."""
    data = {name: build(MetadataKeys.load(path)) for name, path in (("reference", SHIPPED), ("company", COMPANY))}
    for name, corpus in data.items():
        cases = corpus["cases"]
        assert len(cases) > 1000 and 50 < sum(c[4] for c in cases) < len(cases), (name, len(cases))
    # One case to a line, so a change reads as a diff of the cases it changes.
    lines = []
    for name, corpus in data.items():
        head = json.dumps({k: v for k, v in corpus.items() if k != "cases"})[:-1]
        body = ",\n".join(json.dumps(c, separators=(",", ":")) for c in corpus["cases"])
        lines.append(f"{json.dumps(name)}: {head}, \"cases\": [\n{body}\n]}}")
    text = "{\n" + ",\n".join(lines) + "\n}\n"
    assert json.loads(text) == json.loads(json.dumps(data)), "the file reads back as the corpus"
    _write_or_compare(PORTAL / "metadata-corpus.json", text)
