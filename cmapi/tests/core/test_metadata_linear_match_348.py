"""#348: a configured pattern cannot stall the validator. Python re backtracks: (a+)+b, a pattern of the subset that the
loader admits (#332), took 1.4 s on a 25-character value and doubles with each character, so a 63-character label value
would hold a worker for longer than any request lives. The validator matches with RE2 (google-re2, RE2's own binding),
whose time is linear in the value whatever the pattern, as Kyverno's CEL matches() is (RE2, in Go).

The time test runs the validator in a child process with a wall-clock limit. The limit is far above what RE2 needs (well
under a millisecond per value, measured) and far below what backtracking needs (2^62 steps for the label case), so the
verdict does not depend on the runner's speed. The decision and its measurements: docs/reviews/2026-11-17-issue-348/.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import cmapi.core.metadata as metadata
from cmapi.core.metadata import MetadataKeys, portable_pattern_problem
from test_metadata_pattern_subset_332 import CORPUS, engine_regexes

SRC = Path(metadata.__file__).resolve().parents[2]
LIMIT = 30                                   # seconds for the child process; RE2 needs well under one
# Each is in the subset, and each backtracks in Python re: not only nested quantifiers, so refusing those at load would
# not have been enough (docs/reviews/2026-11-17-issue-348/README.md, "Rejected").
SHAPES = {
    "(a+)+b": "nested unbounded quantifiers",
    "(a|a)*b": "one quantifier over an alternation whose branches overlap",
    "(a|aa)+b": "one quantifier over an alternation whose branches overlap",
    "[a-z]*[a-z]*[a-z]*[a-z]*[a-z]*b": "no nesting: five adjacent quantifiers, polynomial",
}


def raw() -> dict:
    keys = list(SHAPES)
    return {"extraLabels": {"keys": {f"example.net/l{i}": {"pattern": p} for i, p in enumerate(keys)},
                            "allowOther": {"prefixes": [], "max": 0}},
            "extraAnnotations": {"keys": {f"example.net/a{i}": {"pattern": p} for i, p in enumerate(keys)},
                                 "allowOther": {"prefixes": [], "max": 0, "maxValueBytes": 0, "maxBytesTotal": 0}}}


def test_each_shape_is_in_the_subset_that_the_loader_admits():
    assert {p: portable_pattern_problem(p) for p in SHAPES} == {p: None for p in SHAPES}
    MetadataKeys(raw())


CHILD = """
import json, sys
from cmapi.core.metadata import MetadataKeys
raw, cases = json.loads(sys.stdin.read())
keys = MetadataKeys(raw)
out = []
for kind, key, value in cases:
    labels, annotations = ({key: value}, {}) if kind == "label" else ({}, {key: value})
    out.append([e["code"] for e in keys.validate(labels, annotations, operator=False)])
print(json.dumps(out))
"""


def test_the_validator_answers_in_linear_time_whatever_the_pattern():
    """A label value at its 63-character limit, and an annotation value of 100,000 characters: each refused and each
    accepted in time. On main the first label case alone is 2^62 backtracking steps."""
    cases, expected = [], []
    for i in range(len(SHAPES)):
        for kind, n in (("label", 62), ("annotation", 100_000)):
            key = f"example.net/{kind[0]}{i}"
            cases += [(kind, key, "a" * n + "c"), (kind, key, "a" * n + "b")]
            expected += [["invalid_value"], []]
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    try:
        r = subprocess.run([sys.executable, "-c", CHILD], input=json.dumps([raw(), cases]), capture_output=True,
                           text=True, timeout=LIMIT, env=env)
    except subprocess.TimeoutExpired:
        pytest.fail(f"the validator did not answer {len(cases)} values in {LIMIT} s: a pattern backtracks (#348)")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == expected


def test_the_validator_reads_each_regex_of_the_three_engine_corpus_as_python_re_does():
    """The #332 corpus (every shipped and company regex and each construct of the subset, on 80 strings): the validator's
    engine (RE2) gives Python re's verdict on each. With the ECMA-262 and Kyverno legs of #332, which hold Python re
    equal to those engines, the four readers agree."""
    regexes = engine_regexes()
    differ = [(name, s) for name, rx in regexes.items() for s in CORPUS
              if metadata.value_matches(rx, s) != (re.fullmatch(rx, s) is not None)]
    assert len(regexes) * len(CORPUS) > 1500 and differ == [], differ[:10]


def test_a_pattern_too_large_for_re2_stops_the_start_with_re2s_reason():
    """In the subset (100,000 repetitions, each count within 1000), but beyond RE2's 8 MiB program budget: the loader
    refuses it at start rather than the validator failing on the first request."""
    pattern = "[^a]{1000}" * 100
    assert portable_pattern_problem(pattern) is None
    config = {"extraAnnotations": {"keys": {"example.net/big": {"pattern": pattern}},
                                   "allowOther": {"prefixes": [], "max": 0, "maxValueBytes": 0, "maxBytesTotal": 0}}}
    with pytest.raises(ValueError, match=re.escape("extraAnnotations.example.net/big: pattern '[^a]{1000}[^a]") +
                       ".*" + re.escape("does not compile in RE2, the validator's engine: pattern too large - compile "
                                        "failed")):
        MetadataKeys(config)


@pytest.mark.parametrize("value", ["x\ud800", "\udfff", "a\udc00b"])
def test_a_value_with_a_lone_surrogate_is_refused_and_never_raises(value):
    """RE2 reads UTF-8, which cannot hold a lone surrogate, and Kubernetes stores a value as UTF-8 (Go's JSON decoder
    replaces one with U+FFFD, so the cluster would hold another value than Git). The key's pattern refuses it."""
    keys = MetadataKeys({"extraAnnotations": {"keys": {"example.net/any": {"pattern": "[^/]*"}},
                                              "allowOther": {"prefixes": [], "max": 0, "maxValueBytes": 0,
                                                             "maxBytesTotal": 0}}})
    assert keys.validate({}, {"example.net/any": "x"}, operator=False) == []
    errs = keys.validate({}, {"example.net/any": value}, operator=False)
    assert [(e["code"], e["key"]) for e in errs] == [("invalid_value", "example.net/any")], errs


def test_an_address_regex_too_large_for_re2_stops_the_start_and_never_raises_on_a_request():
    """The email-in-domains regex joins every emailDomains entry, and the loader compiled only configured patterns in RE2:
    20,000 domains of 62 to 66 characters (a 5 MB regex) loaded, then each value of the key raised re2.error, a 500, where
    main's re.fullmatch answered. The loader refuses it at start with RE2's reason (OB3, review of #351)."""
    domains = [f"d{i}-{'x' * 47}.example.com" for i in range(20_000)]
    config = {"emailDomains": domains,
              "extraAnnotations": {"keys": {"example.net/dl": {"format": "email-in-domains"}},
                                   "allowOther": {"prefixes": [], "max": 0, "maxValueBytes": 0, "maxBytesTotal": 0}}}
    with pytest.raises(ValueError, match=re.escape("emailDomains: the 20000 domains make an address regex that does not "
                                                   "compile in RE2, the validator's engine: pattern too large")):
        MetadataKeys(config)
