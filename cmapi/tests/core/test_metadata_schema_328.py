"""#328: MetadataKeys.json_schema() is the labels and annotations of a namespace as JSON Schema 2020-12, generated from
metadata-keys.yaml, so the API document says each key, its rule and which keys are required, not only prose.

The schema documents validate(); it never replaces it. The differential test runs one corpus (metadata_corpus.py)
through both on the shipped and on synthetic configurations:
- sound: each map that validate() accepts passes the schema (none of them may be refused by a client that checks it);
- precise: each map that the schema passes and validate() refuses is refused for a reason that JSON Schema cannot
  say (metadata_corpus.LOOSE), never for a key or a value rule that it can say.
The schema is read with each pattern as ECMA-262 reads it. The Node leg checks that reading against Node's RegExp (the
u flag, as ajv), on each (pattern, text) pair that the corpus made the schema read; it is skipped without Node, and
fails instead under CMAPI_REQUIRE_NODE=1, as CI sets.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
from fnmatch import fnmatchcase

import pytest
import yaml

from cmapi.core.metadata import (_LABEL_VALUE, KINDS, MetadataKeys, _glob_regex, _globs_meet, anchored,
                                 portable_pattern_problem, value_regex)
from conftest import EX
from metadata_corpus import SchemaReader, run

SHIPPED = EX / "cluster-configs/policies/metadata-keys.yaml"
COMPANY = EX / "cluster-configs/policies/metadata-keys.company.yaml"
OPS = ("create", "patch")
REFERENCE_SOURCES = {"namespace": "payments-dev", "environment": "dev", "cluster": "CRC", "instance": "nonprod"}
COMPANY_SOURCES = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "CRC", "instance": "nonprod"}


def raw(path) -> dict:
    return yaml.safe_load(path.read_text())


def with_allow_other(path, labels: list[str], annotations: list[str] | None = None, **extra) -> MetadataKeys:
    data = copy.deepcopy(raw(path))
    data["extraLabels"]["allowOther"]["prefixes"] = labels
    data["extraAnnotations"]["allowOther"]["prefixes"] = labels if annotations is None else annotations
    data.update(extra)
    return MetadataKeys(data)


# The shipped files, and the edges of the prefix rules: #234's F2 (a company prefix that admits the declared keys and the
# other kind's keys), #331's "*" with and without "", globs that meet the reserved prefixes, and fnmatch's ? and [...].
CONFIGS = {
    "reference": (lambda: MetadataKeys.load(SHIPPED), REFERENCE_SOURCES),
    "company": (lambda: MetadataKeys.load(COMPANY), COMPANY_SOURCES),
    "company-f2": (lambda: with_allow_other(COMPANY, ["", "company.net/"]), COMPANY_SOURCES),
    "star": (lambda: with_allow_other(SHIPPED, ["*"]), REFERENCE_SOURCES),
    "star-and-none": (lambda: with_allow_other(SHIPPED, ["", "*"]), REFERENCE_SOURCES),
    "globs": (lambda: with_allow_other(SHIPPED, ["*.io", "team[0-9].example.com", "?x.example.com", "[!a]b.example.com"],
                                       ["*.example.com"],
                                       reservedPrefixes=[*raw(SHIPPED)["reservedPrefixes"], "res[0-9].example.com/"]),
              REFERENCE_SOURCES),
}


def schemas(keys: MetadataKeys) -> dict[tuple[str, str], dict]:
    return {(kind, op): keys.json_schema(kind, op) for kind in KINDS for op in OPS}


@pytest.fixture(scope="module")
def runs():
    """One run of the corpus for each configuration, and the (pattern, text) pairs that the schemas read."""
    reader = SchemaReader()
    out = {}
    for name, (load, sources) in CONFIGS.items():
        keys = load()
        out[name] = (keys, run(keys, schemas(keys), sources, reader))
    return out, reader.pairs


@pytest.mark.parametrize("name", list(CONFIGS))
def test_the_schema_accepts_each_map_that_the_validator_accepts(runs, name):
    keys, result = runs[0][name]
    assert result.accepted > 100, result
    assert result.unsound == [], [(c.kind, c.op, dict(c.body), p) for c, p in result.unsound[:5]]


@pytest.mark.parametrize("name", list(CONFIGS))
def test_the_schema_refuses_each_map_that_the_validator_refuses_for_a_rule_that_json_schema_can_say(runs, name):
    keys, result = runs[0][name]
    assert result.unexplained == [], [(c.kind, c.op, dict(c.body), e) for c, e in result.unexplained[:5]]
    assert result.agree > result.total * 0.85, result.loose


def test_ecma_262_reads_each_pattern_of_the_schemas_as_the_test_does(runs):
    node = shutil.which("node")
    if not node:
        if os.environ.get("CMAPI_REQUIRE_NODE") == "1":
            pytest.fail("CMAPI_REQUIRE_NODE=1 and no node on PATH")
        pytest.skip("no node on PATH")
    from metadata_corpus import _compiled
    pairs = sorted(runs[1])
    script = ('const p = JSON.parse(require("fs").readFileSync(0, "utf8")); const c = new Map();'
              'process.stdout.write(JSON.stringify(p.map(([rx, s]) => { if (!c.has(rx)) c.set(rx, new RegExp(rx, "u"));'
              'return c.get(rx).test(s); })));')
    r = subprocess.run([node, "-e", script], input=json.dumps(pairs), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    differ = [(rx[:60], s[:40]) for (rx, s), got in zip(pairs, json.loads(r.stdout))
              if got != (_compiled(rx).search(s) is not None)]
    assert len(pairs) > 1000 and differ == [], differ[:10]


def _patterns(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pattern" and isinstance(v, str):
                yield v
            else:
                yield from _patterns(v)
    elif isinstance(node, list):
        for v in node:
            yield from _patterns(v)


@pytest.mark.parametrize("name", list(CONFIGS))
def test_each_pattern_is_a_value_regex_of_the_loader_or_in_the_subset(runs, name):
    """One string for the validator, Kyverno and the document: a key's value rule is metadata.value_regex (#332), and
    each pattern of the schema's own (key syntax, prefixes, label values) is in the subset the three read alike."""
    keys = runs[0][name][0]
    shared = {value_regex(r, keys.email_domains) for kind in KINDS for r in keys.rules[kind].values()} - {None}
    for kind in KINDS:
        for op in OPS:
            schema = keys.json_schema(kind, op)
            for pattern in _patterns(schema):
                assert pattern in shared or portable_pattern_problem(pattern) is None, (kind, op, pattern)
            for key, rule in keys.rules[kind].items():
                prop = schema["properties"][key]
                regex = value_regex(rule, keys.email_domains)
                syntax = _LABEL_VALUE if kind == "label" and rule.enum is None else None
                assert (prop["anyOf"][0] if "anyOf" in prop else prop).get("pattern") == (regex or syntax), (key, op)


def test_the_reference_schema_says_each_required_key_with_the_loaders_pattern():
    """The issue's proof, on the reference file: a property per key with the validator's pattern, and required."""
    keys = MetadataKeys.load(SHIPPED)
    labels, annotations = keys.json_schema("label", "create"), keys.json_schema("annotation", "create")
    assert labels["required"] == ["cmapi.net/team"] and annotations["required"] == ["cmapi.net/team-dl"]
    assert labels["properties"]["cmapi.net/team"]["pattern"] == anchored(keys.rules["label"]["cmapi.net/team"].pattern)
    assert annotations["properties"]["cmapi.net/team-dl"]["pattern"] == \
        value_regex(keys.rules["annotation"]["cmapi.net/team-dl"], keys.email_domains)
    check = SchemaReader().validator(labels)
    assert check.is_valid({"cmapi.net/team": "payments"})
    assert not check.is_valid({"cmapi.net/cost-center": "cc-4410"}), "a map without the required key"
    assert not check.is_valid({"cmapi.net/team": "-payments"}), "the label value syntax, beside the key's pattern"
    assert not check.is_valid({"cmapi.net/team": "payments", "kubernetes.io/x": "y"}), "a key that allowOther does not admit"


def test_a_patch_cannot_remove_a_required_or_derived_key_and_can_remove_any_other():
    for path, required, derived, optional in ((SHIPPED, "cmapi.net/team", None, "cmapi.net/cost-center"),
                                              (COMPANY, "company.net/mnemonic", "name", None)):
        keys = MetadataKeys.load(path)
        check = SchemaReader().validator(keys.json_schema("label", "patch"))
        assert "required" not in keys.json_schema("label", "patch")
        assert not check.is_valid({required: None})
        if derived:
            # #479 (A1): shown and not readOnly; still not removable on a patch.
            prop = keys.json_schema("label", "patch")["properties"][derived]
            assert not check.is_valid({derived: None}) and "readOnly" not in prop and prop["x-cmapi-derived-from"] == "namespace"
        if optional:
            assert check.is_valid({optional: None})
        assert check.is_valid({"owner": None}) and check.is_valid({"cmapi.net/protected": None})


def test_the_company_schema_has_its_own_keys_and_marks_the_derived_ones_required_and_shown():
    keys = MetadataKeys.load(COMPANY)
    labels, annotations = keys.json_schema("label", "create"), keys.json_schema("annotation", "create")
    # #479 (A1): the filled-in keys are required and shown; cmapi still fills one that a create leaves out.
    assert labels["required"] == ["name", "company.net/app-environment", "company.net/mnemonic", "company.net/lob",
                                  "company.net/cl"]
    # #358, the owner: the critical level is 0 to 6, and the line of business is free text (amgsst is an example), so
    # its schema is the label-value syntax with no enum.
    assert labels["properties"]["company.net/cl"]["enum"] == ["0", "1", "2", "3", "4", "5", "6"]
    lob = labels["properties"]["company.net/lob"]
    # The mnemonic is 3 or 4 lowercase letters, anchored once as cmapi and the rendered policy match it.
    assert labels["properties"]["company.net/mnemonic"]["pattern"] == anchored("^[a-z]{3,4}$") == "^(?:^[a-z]{3,4}$)$"
    assert "enum" not in lob and lob["pattern"] == _LABEL_VALUE and lob["maxLength"] == 63 and lob["minLength"] == 1
    assert lob["examples"] == ["amgsst"]
    check = SchemaReader().validator(labels)
    filled = {"name": "abc-rnd", "company.net/app-environment": "rnd"}
    assert check.is_valid({**filled, "company.net/mnemonic": "abc", "company.net/lob": "retail", "company.net/cl": "6"})
    assert check.is_valid({**filled, "company.net/mnemonic": "abcd", "company.net/lob": "retail", "company.net/cl": "6"})
    for bad in ({"company.net/cl": "7"}, {"company.net/lob": "retail sales"}, {"company.net/lob": "a" * 64},
                {"company.net/mnemonic": "ab"}, {"company.net/mnemonic": "abcde"}):
        assert not check.is_valid({**filled, "company.net/mnemonic": "abc", "company.net/lob": "retail",
                                   "company.net/cl": "6", **bad})
    for derived in ("name", "company.net/app-environment"):
        assert "readOnly" not in labels["properties"][derived] and derived in labels["required"]
    assert annotations["required"] == ["company.net/app-environment"], "the only required annotation is filled in"
    assert labels["properties"]["company.net/mnemonic"]["x-cmapi-namespace-prefix"] is True


@pytest.mark.parametrize("glob", ["", "*", "*.ephico2real.com", "team[0-9].example.com", "?x.example.com",
                                  "[!a]b.example.com", "[]x]y", "[!]x]y", "a[b", "x[a-c-]", "a.b", "x[z-a]y", "[\\]"])
def test_a_prefix_glob_reads_a_prefix_as_fnmatchcase_does(glob):
    prefixes = ["", "a", "ab", "bb", "xb", "team1.example.com", "teamx.example.com", "ax.example.com", "xx.example.com",
                "bb.example.com", "ab.example.com", "]y", "xy", "a[b", "a.b", "axb", "x-", "xb", "xd", "\\", "x.ephico2real.com",
                "ephico2real.com", ".ephico2real.com", "x-y"]
    loose, exact = _glob_regex(glob, exact=False), _glob_regex(glob, exact=True)
    for prefix in prefixes:
        if exact is not None:
            assert (re.fullmatch(exact, prefix) is not None) == fnmatchcase(prefix, glob), (glob, prefix, exact)
            assert portable_pattern_problem(exact) is None, exact
        if fnmatchcase(prefix, glob):
            assert re.fullmatch(loose, prefix), (glob, prefix, loose)


@pytest.mark.parametrize("a, b, meet", [("*.io", "*.kubernetes.io", True), ("*.ephico2real.com", "*.kubernetes.io", False),
                                         ("k8s.io", "*.io", True), ("k8s.io", "*.k8s.io", False), ("?", "a", True),
                                         ("team[0-9].x", "team1.x", True), ("a*", "*b", True), ("ab", "ba", False)])
def test_two_globs_meet_when_one_prefix_matches_both(a, b, meet):
    assert _globs_meet(a, b) is meet and _globs_meet(b, a) is meet


def test_a_kind_or_an_operation_that_is_not_one_is_refused():
    keys = MetadataKeys.load(SHIPPED)
    with pytest.raises(ValueError, match="json_schema"):
        keys.json_schema("labels", "create")
    with pytest.raises(ValueError, match="json_schema"):
        keys.json_schema("label", "update")


def test_a_reserved_glob_with_a_slash_never_refuses_a_held_key_that_a_patch_may_remove():
    """A prefix holds no "/", so a reserved glob with one (literal, in a class, or in a range over it) matches no prefix.
    The schema reads the glob on a whole key (^(?:R)/), where that "/" would reach past the prefix: it refused a patch
    that removes a held key which allowOther admits and validate() accepts (OB3 on #350)."""
    data = raw(SHIPPED)
    for stanza in ("extraLabels", "extraAnnotations"):
        data[stanza]["allowOther"]["prefixes"] = ["", "a*", "x*"]
    data["reservedPrefixes"] = ["kubernetes.io/", "a/b/", "a[/]c/", "x[+-0]y/"]
    keys, reader = MetadataKeys(data), SchemaReader()
    for kind in KINDS:
        schema = reader.validator(keys.json_schema(kind, "patch"))
        for key in ("a/b/c", "a/c/d", "x/y/z"):
            sent, held = ({key: None}, {}), {"current_labels" if kind == "label" else "current_annotations": {key: "x"}}
            assert keys.validate(*(sent if kind == "label" else sent[::-1]), operator=False, existing=True, **held) == []
            assert schema.is_valid({key: None}), (kind, key)
        for key in ("x+y/k", "x.y/k", "x0y/k"):          # the class still refuses each prefix that it reads
            assert keys.classify(key, kind) == "reserved" and not schema.is_valid({key: None}), (kind, key)
    assert _glob_regex("x[+-0]y", exact=True) == "x[+-.0]y" and _glob_regex("a/b", exact=True) is None
    assert _glob_regex("a[!/]c", exact=True) == "a[^/]c"


def test_a_create_refuses_a_key_whose_prefix_is_over_253_characters():
    """JSON Schema says the 253 with a second pattern under "not", with no lookahead (OB3 on #350)."""
    keys, reader = MetadataKeys.load(SHIPPED), SchemaReader()
    for kind in KINDS:
        names = reader.validator(keys.json_schema(kind, "create")["propertyNames"])
        for length, ok in ((253, True), (254, False)):
            key = "a" * (length - len(".ephico2real.com")) + ".ephico2real.com/k"
            assert (keys._syntax(key, None, kind) is None) is ok
            assert names.is_valid(key) is ok, (kind, length)
