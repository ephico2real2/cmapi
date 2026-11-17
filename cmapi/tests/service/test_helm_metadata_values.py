"""#335: metadata-keys.yaml as structured Helm values, checked by the chart's values.schema.json before a pod starts.

Each case runs the real helm (3.19.0 in CI, 4.3.1 measured on the Mac) on the real chart, and the rendered file goes
through the real loader, MetadataKeys. The loader stays the final check at start; the schema refuses what it can earlier,
at helm install, upgrade, lint and template (https://helm.sh/docs/topics/charts/#schema-files)."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import subprocess

import pytest
import yaml

from cmapi.core import metadata
from cmapi.core.metadata import MetadataKeys

ROOT = pathlib.Path(__file__).resolve().parents[3]
CHART, CRC = ROOT / "deploy/helm/cmapi", ROOT / "deploy/environments/crc.yaml"
SCHEMA = CHART / "values.schema.json"
CHART_FILE = CHART / "config/metadata-keys.yaml"
DIG = "sha256:" + "a" * 64
REFERENCE_FILES = {
    "chart": CHART_FILE,
    "example": ROOT / "examples/cluster-configs/policies/metadata-keys.yaml",
    "company": ROOT / "examples/cluster-configs/policies/metadata-keys.company.yaml",
    "local": ROOT / "examples/local/config/metadata-keys.yaml",
}
SCHEMA_REFUSAL = "values don't meet the specifications of the schema"


def _helm(command: str, tmp_path: pathlib.Path, values: dict | None = None) -> subprocess.CompletedProcess:
    """helm template or helm lint of the chart with the CRC site file and, when given, one more values file."""
    extra = []
    if values is not None:
        # JSON is YAML that every reader types alike: PyYAML would write 1e3 bare, and Helm would read that as a number.
        path = tmp_path / "values-335.json"
        path.write_text(json.dumps(values))
        extra = ["-f", str(path)]
    release = ["cmapi"] if command == "template" else []
    return subprocess.run(["helm", command, *release, str(CHART), "-n", "cmapi", "-f", str(CRC), *extra,
                           "--set", f"cmapi.digest={DIG}", "--set", f"cmapi_portal.digest={DIG}",
                           "--set", "trustedCA.certificates=x"], capture_output=True, text=True)


def _config(stdout: str) -> dict[str, str]:
    """The data of the cmapi-config ConfigMap of a render."""
    return next(d for d in yaml.safe_load_all(stdout)
                if d and d["kind"] == "ConfigMap" and d["metadata"]["name"] == "cmapi-config")["data"]


def _rendered_keys(tmp_path, values=None) -> dict:
    r = _helm("template", tmp_path, values)
    assert r.returncode == 0, r.stderr[-600:]
    return yaml.safe_load(_config(r.stdout)["metadata-keys.yaml"])


def _chart_keys() -> dict:
    return yaml.safe_load(CHART_FILE.read_text())


def test_default_values_render_the_chart_file(tmp_path):
    """No metadata value: the ConfigMap carries the chart's config/metadata-keys.yaml, as before #335."""
    assert _rendered_keys(tmp_path) == _chart_keys()


@pytest.mark.parametrize("name", sorted(REFERENCE_FILES))
def test_each_reference_file_as_values_renders_itself_and_the_loader_takes_it(tmp_path, name):
    """The schema is not stricter than the files cmapi ships: each, given as the metadata value, passes helm template
    and helm lint, renders a file that parses equal to it, and loads."""
    source = yaml.safe_load(REFERENCE_FILES[name].read_text())
    rendered = _rendered_keys(tmp_path, {"metadata": source})
    assert rendered == source
    MetadataKeys(rendered)
    lint = _helm("lint", tmp_path, {"metadata": source})
    assert lint.returncode == 0, lint.stdout[-600:]


def test_a_custom_required_label_reaches_the_loader(tmp_path):
    """The proof the issue asks for: a site's own required label, set through values, is required by the instance."""
    keys = _chart_keys()
    keys["requiredLabels"]["acme.example/owner"] = {"pattern": "^[a-z]{2,20}$", "description": "The owning group",
                                                   "example": "payments"}
    rendered = _rendered_keys(tmp_path, {"metadata": keys})
    assert rendered == keys
    loaded = MetadataKeys(rendered)
    assert loaded.rules["label"]["acme.example/owner"].required
    errors = loaded.validate({"cmapi.net/team": "payments"}, {"cmapi.net/team-dl": "payments-team@ephico2real.com"},
                             operator=False)
    assert {"code": "missing_required_key", "key": "acme.example/owner"} in [
        {k: e[k] for k in ("code", "key")} for e in errors], errors


def test_the_example_of_docs_18_passes_the_schema_and_loads(tmp_path):
    """The example an operator copies (docs/18, "Setting the keys through the Helm values") is a block the chart takes."""
    doc = (ROOT / "docs/18-configuration.md").read_text()
    section = doc[doc.index("### Setting the keys through the Helm values"):]
    block = section[section.index("```yaml\n") + len("```yaml\n"):]
    example = yaml.safe_load(block[:block.index("```")])
    rendered = _rendered_keys(tmp_path, example)
    assert rendered == example["metadata"]
    assert MetadataKeys(rendered).rules["label"]["acme.example/owner"].required


def test_the_block_changes_metadata_keys_yaml_and_nothing_else_in_the_config_map(tmp_path):
    """The chart file given as the block: every other file of the ConfigMap is byte for byte the default render's."""
    default = _helm("template", tmp_path)
    block = _helm("template", tmp_path, {"metadata": _chart_keys()})
    assert default.returncode == 0 and block.returncode == 0, (default.stderr + block.stderr)[-600:]
    before, after = _config(default.stdout), _config(block.stdout)
    assert before.keys() == after.keys()
    assert {k: v for k, v in before.items() if k != "metadata-keys.yaml"} == \
           {k: v for k, v in after.items() if k != "metadata-keys.yaml"}
    assert yaml.safe_load(after["metadata-keys.yaml"]) == yaml.safe_load(before["metadata-keys.yaml"])


def test_text_that_yaml_could_read_as_another_type_stays_text(tmp_path):
    """toYaml must quote each text that a YAML 1.1 reader (PyYAML, the loader's) takes for a number, a bool or null."""
    tricky = ["0", "1", "yes", "no", "on", "off", "1.0", "0123", "1e3", "0x1F", "null", "~", "true", ""]
    keys = _chart_keys()
    keys["requiredAnnotations"]["acme.example/level"] = {"enum": tricky, "example": "0"}
    keys["requiredLabels"]["acme.example/cl"] = {"enum": ["0", "1", "on", "yes", ""], "example": "1"}
    rendered = _rendered_keys(tmp_path, {"metadata": keys})
    assert rendered["requiredAnnotations"]["acme.example/level"]["enum"] == tricky
    assert rendered == keys
    MetadataKeys(rendered)


def _mutate(change):
    keys = _chart_keys()
    change(keys)
    return keys


# Each case: the metadata value, and where the schema says it is wrong. Before #335 each rendered (no schema); several
# then loaded silently (the misspelled stanza, the text for a list, the key '/foo' (#330), the partial block).
REFUSED = {
    "a misspelled stanza": (_mutate(lambda k: k.__setitem__("requiredLabel", k.pop("requiredLabels"))),
                            "additional properties 'requiredLabel' not allowed"),
    "the old stanza governed": (_mutate(lambda k: k.__setitem__("governed", {})),
                                "additional properties 'governed' not allowed"),
    "a partial block": ({"emailDomains": ["acme.example"]}, "missing properties 'system'"),
    "text for a list": (_mutate(lambda k: k.__setitem__("emailDomains", "ephico2real.com")),
                        "at '/metadata/emailDomains': got string, want array"),
    "an unknown field of a rule": (_mutate(lambda k: k["requiredLabels"]["cmapi.net/team"].__setitem__("patern", "^x$")),
                                   "additional properties 'patern' not allowed"),
    "a limit as text": (_mutate(lambda k: k["extraLabels"]["allowOther"].__setitem__("max", "50")),
                        "at '/metadata/extraLabels/allowOther/max': got string, want integer"),
    "a negative limit": (_mutate(lambda k: k["extraLabels"]["allowOther"].__setitem__("max", -1)),
                         "at '/metadata/extraLabels/allowOther/max': minimum"),
    "an annotation limit on labels": (_mutate(lambda k: k["extraLabels"]["allowOther"].__setitem__("maxValueBytes", 10)),
                                      "additional properties 'maxValueBytes' not allowed"),
    "a format on a label": (_mutate(lambda k: k["requiredLabels"].__setitem__("cmapi.net/site", {"format": "url"})),
                            "at '/metadata/requiredLabels/cmapi.net~1site/format': false schema"),
    "pattern and enum together": (_mutate(lambda k: k["requiredLabels"]["cmapi.net/team"].__setitem__("enum", ["a"])),
                                  "at '/metadata/requiredLabels/cmapi.net~1team/enum': false schema"),
    "value.from with a pattern": (_mutate(lambda k: k["requiredLabels"].__setitem__(
                                      "cmapi.net/ns", {"value": {"from": "namespace"}, "pattern": "^a$"})),
                                  "at '/metadata/requiredLabels/cmapi.net~1ns/pattern': false schema"),
    "an unknown value.from": (_mutate(lambda k: k["requiredLabels"].__setitem__("cmapi.net/ns", {"value": {"from": "team"}})),
                              "at '/metadata/requiredLabels/cmapi.net~1ns/value/from': value must be one of"),
    "an empty prefix (#330)": (_mutate(lambda k: k["requiredLabels"].__setitem__("/foo", {})),
                               "additional properties '/foo' not allowed"),
    "a space in a key": (_mutate(lambda k: k["requiredAnnotations"].__setitem__("cmapi.net/my key", {})),
                         "additional properties 'cmapi.net/my key' not allowed"),
    "an empty enum": (_mutate(lambda k: k["requiredLabels"].__setitem__("cmapi.net/tierx", {"enum": []})),
                      "at '/metadata/requiredLabels/cmapi.net~1tierx/enum': minItems"),
    "a label enum value no label can hold": (_mutate(lambda k: k["requiredLabels"].__setitem__("cmapi.net/tierx", {"enum": ["a b"]})),
                                             "at '/metadata/requiredLabels/cmapi.net~1tierx/enum/0'"),
    "an adoption label without recognise": (_mutate(lambda k: k["adoptionLabels"].__setitem__(
                                                "company.net/provisioner", {"recognize": ["cluster-configs"]})),
                                            "missing property 'recognise'"),
    "a rule that is not a mapping": (_mutate(lambda k: k["requiredLabels"].__setitem__("cmapi.net/x", None)),
                                     "at '/metadata/requiredLabels/cmapi.net~1x': got null, want object"),
    "an example that is not text": (_mutate(lambda k: k["requiredLabels"]["cmapi.net/team"].__setitem__("example", 4410)),
                                    "at '/metadata/requiredLabels/cmapi.net~1team/example': got number, want string"),
}


@pytest.mark.parametrize("command", ["template", "lint"])
@pytest.mark.parametrize("case", sorted(REFUSED))
def test_the_schema_refuses_a_malformed_block_before_anything_renders(tmp_path, case, command):
    values, where = REFUSED[case]
    r = _helm(command, tmp_path, {"metadata": values})
    out = r.stdout + r.stderr
    assert r.returncode != 0 and SCHEMA_REFUSAL in out and where in out, out[-900:]


def test_setting_both_the_block_and_the_text_fails_at_render(tmp_path):
    r = _helm("template", tmp_path, {"metadata": _chart_keys(),
                                     "configFiles": {"metadata-keys.yaml": CHART_FILE.read_text()}})
    assert r.returncode != 0
    assert 'metadata and configFiles."metadata-keys.yaml" both set metadata-keys.yaml' in r.stderr, r.stderr[-600:]


def test_the_text_block_alone_still_renders_as_written(tmp_path):
    """configFiles."metadata-keys.yaml" stays the full-text fallback, rendered byte for byte."""
    text = REFERENCE_FILES["company"].read_text()
    r = _helm("template", tmp_path, {"configFiles": {"metadata-keys.yaml": text}})
    assert r.returncode == 0, r.stderr[-600:]
    assert _config(r.stdout)["metadata-keys.yaml"] == text


def test_a_misspelled_config_file_name_is_refused(tmp_path):
    """Before #335 the template read five names and ignored any other: metadata-key.yaml rendered the chart's file."""
    r = _helm("template", tmp_path, {"configFiles": {"metadata-key.yaml": "requiredLabels: {}\n"}})
    assert r.returncode != 0 and "additional properties 'metadata-key.yaml' not allowed" in r.stderr, r.stderr[-600:]


def test_the_schema_names_what_the_loader_reads():
    """The schema and the loader drift apart silently otherwise: each field, source and format the loader takes."""
    schema = json.loads(SCHEMA.read_text())
    rule = schema["definitions"]["rule"]
    assert set(rule["properties"]) == metadata._RULE_FIELDS
    assert tuple(rule["properties"]["value"]["properties"]["from"]["enum"]) == metadata.DERIVED_FROM
    assert tuple(rule["properties"]["format"]["enum"]) == metadata.FORMATS
    block = schema["properties"]["metadata"]
    assert set(block["then"]["required"]) == set(block["properties"]) == set(_chart_keys())
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"


@pytest.mark.parametrize("values", ["defaults", "metadata", "configFiles"])
def test_checksum_config_is_the_hash_of_the_config_map_as_rendered(tmp_path, values):
    """The API and the worker hash the raw output of templates/config.yaml (checksum/config), while Helm prints that
    output trimmed: a stray blank line from a guard (the first version of #335's) changes the checksum and restarts both
    on an upgrade that changes no file. The checksum must be the hash of the ConfigMap exactly as rendered."""
    given = {"defaults": None, "metadata": {"metadata": _chart_keys()},
             "configFiles": {"configFiles": {"metadata-keys.yaml": CHART_FILE.read_text()}}}[values]
    r = _helm("template", tmp_path, given)
    assert r.returncode == 0, r.stderr[-600:]
    doc = r.stdout.split("# Source: cmapi/templates/config.yaml\n", 1)[1].split("\n---\n", 1)[0]
    sums = {d["metadata"]["name"]: d["spec"]["template"]["metadata"]["annotations"]["checksum/config"]
            for d in yaml.safe_load_all(r.stdout)
            if d and d["kind"] == "Deployment" and d["metadata"]["name"] in ("cmapi-api", "cmapi-worker")}
    assert sums == dict.fromkeys(("cmapi-api", "cmapi-worker"), hashlib.sha256(doc.encode()).hexdigest()), sums
