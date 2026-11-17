"""#355: every string that cmapi writes into a manifest reads back as the same string in the readers of Kubernetes tooling.

PyYAML wrote y, Y, n and N plain, and go-yaml v2 (sigs.k8s.io/yaml: kubectl, Argo CD, the Kyverno CLI) reads them as
booleans, so a team label `flag: y` made a namespace.yaml that the API server refused and on which Kyverno failed with
`no such overload: bytes(bool)`. The renderer and the policy bundle now write through core/kube_yaml.py.

The readers are the real Go libraries (kube_readers.py, yamlread/main.go): sigs.k8s.io/yaml v1.6.0 for YAML 1.1 and
go-yaml v3 for YAML 1.2.
"""
from __future__ import annotations

import itertools
import random
import re

import pytest
import yaml

from cmapi.core.metadata import MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import render_bundle
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec, _dump
from cmapi.core.tiers import TierCatalog
from conftest import ALL_ENVS, EX
from kube_readers import READERS, read
from test_policygen import SHIPPED, apply, kyverno, write  # noqa: F401  (kyverno is a fixture)

# The implicit forms of the YAML 1.1 types (yaml.org/type: bool, int, float, null, timestamp, merge, value) and the
# plain scalars that go-yaml v2 and v3 resolve through Go's strconv and time.Parse.
FORMS = [
    "y", "Y", "n", "N", "yes", "No", "TRUE", "false", "on", "Off",                        # bool
    "~", "null", "Null", "",                                                              # null
    "0b1010", "-0b1", "0b-1", "017", "0o17", "0O17", "0o+7", "42", "-17", "+1", "1_000", "0x1F", "0X1F", "0B1",
    "190:20:30", "1:20",                                                                  # int, base 2 to 60
    "6.8523015e+5", "685.230_15e+03", "1e3", "1E3", "089", "+089", ".5", "+.5", "-.5e2", "1.", "190:20:30.15",
    ".inf", "-.Inf", "+.INF", ".NaN", "8E959",                                            # float
    "2026-11-17", "2026-1-2", "2001-12-14t21:59:43.10-05:00", "2026-1-2T1:2:3Z", "2026-1-2 1:2:3",  # timestamp
    "<<", "=",                                                                            # merge, value
]
# Values whose bytes must not change: every reader takes them plain as strings, or PyYAML quotes them already (1_).
ORDINARY = ["payments", "abc-team@company.net", "https://wiki.company.net/abc", "v1.2.3", "1.2.3", "4.18.0", "10Gi",
            "500m", "x", "t", "f", "o", ".", "0x", "0b", "1_", "2026-1-2T1:2:3", "2026-13", "yn", "nope"]
SOURCES = {"namespace": "payments-dev", "environment": "dev", "cluster": "CRC", "instance": "nonprod"}

# YAML 1.2.2, section 10.3.2, the core schema's int and float (yaml.org/spec/1.2.2).
CORE_12 = re.compile(r"[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+|[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?")


@pytest.fixture(scope="module")
def catalog() -> TierCatalog:
    return TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)


def render(catalog: TierCatalog, keys: MetadataKeys, labels: dict, annotations: dict, **over) -> dict[str, str]:
    spec = dict(namespace="payments-dev", cluster_id="CRC", instance="nonprod", env="dev", tier="small",
                request_id="req-1", requested_by_user="ola", requested_by_email="ola@ephico2real.com",
                labels={"cmapi.net/team": "payments", **labels},
                annotations={"cmapi.net/team-dl": "payments-team@ephico2real.com", **annotations})
    spec.update(over)
    files = ManifestRenderer(catalog, keys).render(NamespaceSpec(**spec))
    return {p.rsplit("/", 1)[1]: t for p, t in files.items() if t}


def documents(text: str) -> list[str]:
    """The documents of a file as written, for a reader that takes one."""
    return re.split(r"(?m)^---\n", text)


def leaves(x, path: tuple = ()) -> dict[tuple, object]:
    """{path: scalar} of a document; the keys of every mapping are in the paths."""
    if isinstance(x, dict):
        return {p: v for k, y in x.items() for p, v in leaves(y, (*path, k)).items()} or {path: "{}"}
    if isinstance(x, list):
        return {p: v for i, y in enumerate(x) for p, v in leaves(y, (*path, i)).items()} or {path: "[]"}
    return {path: x}


def short_strings() -> list[str]:
    """Every string of up to three characters over the characters the resolvers look at, and 20000 longer ones."""
    chars = "0178xXoObBeE._:+-~<=yYnNtf"
    out = [""] + ["".join(p) for n in (1, 2, 3) for p in itertools.product(chars, repeat=n)]
    rnd = random.Random(355)
    more = chars + "234569TZ: "
    out += ["".join(rnd.choice(more) for _ in range(rnd.randint(4, 12))) for _ in range(20000)]
    return list(dict.fromkeys(out + FORMS + ORDINARY))


def test_each_yaml11_form_in_a_rendered_namespace_reads_back_as_the_same_string(catalog):
    """The issue's proof, for each form as a team label value, a team annotation value and a ServiceAccount name (a
    DNS label such as y, 1e3 or 089 is a valid name): each file reads back in both readers as PyYAML reads it."""
    labels = {f"x.ephico2real.com/v{i:02d}": v for i, v in enumerate(FORMS + ORDINARY)}
    annotations = {f"x.ephico2real.com/a{i:02d}": v for i, v in enumerate(FORMS + ORDINARY)}
    names = ["y", "n", "1e3", "089", "0o17", "0x1f", "0b1", "2026-1-2", "123"]
    files = render(catalog, MetadataKeys.load(SHIPPED), labels, annotations, service_accounts=names)
    for name, text in files.items():
        for doc in documents(text):
            got = read(doc)
            assert all(got[r] == yaml.safe_load(doc) for r in READERS), (name, got)
    meta = yaml.safe_load(files["namespace.yaml"])["metadata"]
    assert labels.items() <= meta["labels"].items() and annotations.items() <= meta["annotations"].items()
    sas = [d["metadata"]["name"] for d in yaml.safe_load_all(files["serviceaccounts.yaml"])]
    assert sorted(sas) == sorted(names)


def test_every_short_string_reads_back_as_itself_as_a_key_and_as_a_value():
    """The property: the renderer's writer (_dump) gives YAML in which each string of the corpus reads back as itself
    in both readers and in PyYAML, both as a mapping key (a key y was the bool key true) and as a value."""
    corpus = short_strings()
    doc = {s: s for s in corpus}
    text = _dump([doc])
    assert yaml.safe_load(text) == doc
    got = read(text)
    for reader in READERS:
        wrong = [s for s in corpus if got[reader].get(s) != s]
        assert wrong == [], (reader, len(wrong), wrong[:20])


def test_only_a_string_that_a_reader_would_retype_gains_quotes():
    """The bytes of a safe value do not change: a string that SafeDumper wrote and both readers read back unchanged is
    written the same, except one that YAML 1.2's core schema calls a number but Go's strconv refuses for its size."""
    corpus = short_strings()
    doc = {f"k{i}": s for i, s in enumerate(corpus)}
    got = read(yaml.safe_dump(doc))
    safe = [s for i, s in enumerate(corpus) if all(got[r][f"k{i}"] == s for r in READERS)]
    changed = [s for s in safe if _dump([{"k": s}]) != yaml.safe_dump({"k": s}, sort_keys=False)]
    assert [s for s in changed if not CORE_12.fullmatch(s)] == [], changed
    assert all(_dump([{"k": s}]) == yaml.safe_dump({"k": s}, sort_keys=False) for s in ORDINARY)


def test_the_policy_bundle_writes_through_the_same_dumper(catalog):
    """policygen writes the bundle with kube_yaml, so a rendered policy reads back the same in both readers."""
    keys = MetadataKeys.load(SHIPPED)
    for rel, text in render_bundle(catalog, keys, PolicySettings(), ALL_ENVS, "nonprod").items():
        for doc in documents(text) if rel.endswith(".yaml") else []:
            want, got = leaves(yaml.safe_load(doc)), read(doc)
            for reader in READERS:
                have = leaves(got[reader])
                assert have.keys() == want.keys(), (rel, reader, have.keys() ^ want.keys())
                # a string reads back as itself; a bool or a number (validationActions, enabled: false) stays one
                assert {p: v for p, v in have.items() if isinstance(want[p], str)} == \
                    {p: v for p, v in want.items() if isinstance(v, str)}, (rel, reader)
                assert all(re.fullmatch(r"<\w+ .*>", have[p]) for p, v in want.items() if not isinstance(v, str))


def test_kyverno_evaluates_the_byte_policies_on_a_label_y_and_an_annotation_n(kyverno, catalog, tmp_path):
    """Before #355 the namespace.yaml of this request held `flag: y` and `note: n`, and the Kyverno CLI read them as
    booleans: the annotation byte policies of #333 failed with `no such overload: bytes(bool)`."""
    keys = MetadataKeys.load(SHIPPED)
    errors = keys.validate({"cmapi.net/team": "payments", "x.ephico2real.com/flag": "y"},
                           {"cmapi.net/team-dl": "payments-team@ephico2real.com", "x.ephico2real.com/note": "n"},
                           operator=False, sources=SOURCES)
    assert errors == []                                  # cmapi accepts the request
    files = render(catalog, keys, {"x.ephico2real.com/flag": "y"}, {"x.ephico2real.com/note": "n"})
    bundle = write(tmp_path / "b", render_bundle(catalog, keys, PolicySettings(), {"dev"}, "nonprod"))
    ns = tmp_path / "namespace.yaml"
    ns.write_text(files["namespace.yaml"])
    got = apply(kyverno, bundle / "env/dev", [ns])
    assert set(got) == {"pass"}, got
    assert any("bytes" in p for p, _ in got["pass"])     # the byte policies ran and passed
