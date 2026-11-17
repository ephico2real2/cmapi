"""#338: the loader of metadata-keys.yaml refuses a file whose shape it would otherwise misread: an unknown stanza (a
misspelt requiredLabel: loaded with no required label), a text where a list is expected (emailDomains: x.com loaded as
its characters), and a mapping where a list is expected or the reverse. The Helm values.schema.json (#335) refuses these
for the structured metadata value only; the plain manifests, configFiles and CMAPI_METADATA_KEYS reach this loader with no
schema, so it is the final check. Every shipped copy still loads."""
from __future__ import annotations

import copy
import re

import pytest
import yaml

from cmapi.core.config import ConfigError, load_instance
from cmapi.core.metadata import MetadataKeys
from conftest import EX

COMPANY = EX / "cluster-configs/policies/metadata-keys.company.yaml"
ROOT = EX.parent
LISTS = ("system", "operatorOnly", "reservedPrefixes", "sensitiveKeys", "emailDomains")
MAPPINGS = ("requiredLabels", "requiredAnnotations", "extraLabels", "extraAnnotations", "adoptionLabels")


@pytest.fixture
def raw() -> dict:
    return copy.deepcopy(yaml.safe_load(COMPANY.read_text()))


def refused(raw, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        MetadataKeys(raw)


def test_the_measurements_of_the_issue_are_refused():
    """The three cases of #338, measured on main 9ba33b2: each loaded and changed the rules silently."""
    refused({"emailDomains": "ephico2real.com"}, "emailDomains must be a list of text, as [a, b], not the text "
                                                  "'ephico2real.com'")
    refused({"system": "cmapi.net/tier"}, "system must be a list of text, as [a, b], not the text 'cmapi.net/tier'")
    refused({"requiredLabel": {"cmapi.net/team": {}}}, "unknown stanza 'requiredLabel': did you mean requiredLabels?")


def test_an_unknown_stanza_names_the_stanzas(raw):
    raw["labels"] = {}
    refused(raw, "unknown stanza 'labels'; the stanzas are ['system', ")


@pytest.mark.parametrize("stanza", LISTS)
@pytest.mark.parametrize("value, shown", [("x.example", "the text 'x.example'"), ({"x.example": 1}, "a mapping"),
                                          (True, "the bool True")])
def test_a_list_stanza_given_as_another_type_is_refused(raw, stanza, value, shown):
    raw[stanza] = value
    refused(raw, f"{stanza} must be a list of text, as [a, b], not {shown}")


@pytest.mark.parametrize("stanza", LISTS)
def test_a_list_stanza_with_an_item_that_is_not_text_is_refused(raw, stanza):
    raw[stanza] = [*raw[stanza], 7]
    refused(raw, f"{stanza} must be a list of text; 7 is not text")


@pytest.mark.parametrize("stanza", MAPPINGS)
@pytest.mark.parametrize("value, shown", [(["x"], "a list"), ("x", "the text 'x'")])
def test_a_mapping_stanza_given_as_another_type_is_refused(raw, stanza, value, shown):
    raw[stanza] = value
    refused(raw, f"{stanza} must be a mapping, not {shown}")


@pytest.mark.parametrize("stanza, field, value", [("extraLabels", "keys", ["company.net/x"]),
                                                  ("extraAnnotations", "allowOther", ["*.company.net/"])])
def test_a_field_of_an_extra_stanza_given_as_a_list_is_refused(raw, stanza, field, value):
    raw[stanza][field] = value
    refused(raw, f"{stanza}.{field} must be a mapping, not a list")


def test_an_adoption_label_with_an_unknown_field_is_refused(raw):
    raw["adoptionLabels"]["company.net/provisioner"]["recognize"] = ["x"]
    refused(raw, "adoptionLabels.company.net/provisioner: an entry is {recognise: [values]}, not a mapping with the "
                 "fields ['recognise', 'recognize']")


def test_an_email_domain_that_is_not_a_domain_name_is_refused(raw):
    raw["emailDomains"] = ["company.net", "company net", "a@company.net"]
    refused(raw, "emailDomains: ['company net', 'a@company.net'] are not domain names")


@pytest.mark.parametrize("value, shown", [(None, "empty"), (["system"], "a list"), ("system: []", "the text")])
def test_a_file_that_is_not_a_mapping_is_refused(value, shown):
    refused(value, f"metadata-keys.yaml is a mapping of the stanzas ['system', ")
    with pytest.raises(ValueError, match=re.escape(f"not {shown}")):
        MetadataKeys(value)


def test_an_empty_stanza_is_an_empty_list_or_mapping(raw):
    for stanza in ("operatorOnly", "sensitiveKeys", "extraLabels", "adoptionLabels"):
        raw[stanza] = None
    keys = MetadataKeys(raw)
    assert keys.operator_only == [] and keys.sensitive == set() and keys.adoption_labels == {}
    assert keys.allow_other["label"].prefixes == () and keys.rules["label"]["company.net/mnemonic"].required


def shipped() -> dict[str, dict]:
    """Every metadata-keys.yaml that the repository ships: the chart's, the examples' and the ConfigMaps' copies."""
    files = {str(p.relative_to(ROOT)): yaml.safe_load(p.read_text()) for p in (
        ROOT / "deploy/helm/cmapi/config/metadata-keys.yaml", EX / "cluster-configs/policies/metadata-keys.yaml",
        EX / "cluster-configs/policies/metadata-keys.company.yaml", EX / "local/config/metadata-keys.yaml")}
    for env in ("crc", "kind"):
        path = ROOT / f"deploy/manifests/environments/{env}/20-config.yaml"
        for doc in yaml.safe_load_all(path.read_text()):
            if doc and "metadata-keys.yaml" in (doc.get("data") or {}):
                files[f"{path.relative_to(ROOT)} {doc['metadata']['name']}"] = yaml.safe_load(doc["data"]["metadata-keys.yaml"])
    return files


def test_every_shipped_copy_loads():
    files = shipped()
    assert len(files) == 6, sorted(files)
    for name, raw in files.items():
        MetadataKeys(raw)


@pytest.mark.parametrize("edit, message", [
    (lambda r: r.__setitem__("requiredLabel", r.pop("requiredLabels")), "unknown stanza 'requiredLabel'"),
    (lambda r: r.__setitem__("emailDomains", "ephico2real.com"), "emailDomains must be a list of text"),
    (lambda r: r["requiredLabels"]["cmapi.net/team"].__setitem__("pattern", r"^\d+$"), r"\d (Python also matches"),
    (lambda r: r["requiredLabels"]["cmapi.net/team"].pop("example"), "a required key needs an example"),
])
def test_the_instance_does_not_start_on_such_a_file(tmp_path, edit, message):
    """The start (load_instance, as main.py runs it) stops with the loader's message, so a pod that would run with fewer
    rules than its file says fails its start instead (#332, #338)."""
    raw = yaml.safe_load((EX / "cluster-configs/policies/metadata-keys.yaml").read_text())
    edit(raw)
    (tmp_path / "metadata-keys.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match=re.escape("metadata-keys.yaml: invalid metadata-keys.yaml: ")) as e:
        load_instance(EX / "instances/nonprod", tmp_path / "metadata-keys.yaml")
    assert message in str(e.value)
