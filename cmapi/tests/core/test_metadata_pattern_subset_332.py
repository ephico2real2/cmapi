"""#332: a value's regex is one string that Python re (a Python client of the API document; the validator until #348, which
matches with RE2, test_metadata_linear_match_348.py), RE2 (Kyverno CEL matches) and ECMA-262 (the API document, #328) read
alike. The loader refuses a configured pattern outside that subset, metadata.anchored() anchors a
pattern in one place, and metadata.value_regex() gives each format its one regex, which the validator and the rendered
policies share. Also the owner's answer to #328 question 3: a required key needs an example that its own rule accepts.

The three-engine test runs Node (ECMA-262, the u flag that ajv uses) and the Kyverno CLI (RE2, the image's pin). Each leg
is skipped when its tool is missing, and fails instead under CMAPI_REQUIRE_NODE=1 or CMAPI_REQUIRE_KYVERNO=1, as CI sets.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import os
import random
import re
import shutil
import subprocess
import sys
import unicodedata
from urllib.parse import urlsplit

import pytest
import yaml

from cmapi.core.metadata import (_SPACE, MetadataKeys, anchored, portable_pattern_problem, value_regex)
from cmapi.core.policy import PolicySettings
from cmapi.core.policygen import cel, render_bundle
from cmapi.core.tiers import TierCatalog
from conftest import ALL_ENVS, EX

COMPANY = EX / "cluster-configs/policies/metadata-keys.company.yaml"
SHIPPED = EX / "cluster-configs/policies/metadata-keys.yaml"
SOURCES = {"namespace": "abc-rnd", "environment": "rnd", "cluster": "OCP_GF15", "instance": "nonprod"}
SENT = {"company.net/mnemonic": "abc", "company.net/lob": "amgsst", "company.net/cl": "1"}
KEY = "company.net/code"                      # an optional annotation with no example, so only its pattern is in play
URL_KEY = "company.net/mnemonic-confluence"

# Each loads on main (5a8f817): Python compiles it, and RE2 or ECMA-262 refuses it or reads it otherwise.
NOT_PORTABLE = [
    (r"^[a-z]+\Z", r"\Z (end of text)"),
    (r"(?i)^[a-z]+$", "an inline flag"),
    (r"^(?P<t>[a-z]+)$", "a named group (?P<name>...)"),
    (r"^(?=x)[a-z]+$", "a lookahead"),
    (r"^(?!x)[a-z]+$", "a negative lookahead"),
    (r"^(?<=x)[a-z]+$", "a lookbehind"),
    (r"^([a-z])\1$", r"a backreference \1"),
    (r"^[a-z]*+$", "a quantifier after a quantifier"),          # possessive: Python 3.11 and later
    (r"^(?>[a-z]+)$", "an atomic group"),                        # Python 3.11 and later
    (r"^\d{4}$", r"\d (Python also matches"),
    (r"^\w+$", r"\w"),
    (r"^\s*$", r"\s (whitespace"),
    (r"^a\b", r"\b (a word boundary)"),
    (r"\Aabc$", r"\A (start of text)"),
    (r"^a.c$", ". (any character"),
    (r"^[[:alpha:]]+$", "a POSIX class"),
    (r"^a{,3}$", "write {0,n}"),
    (r"^a{1001}$", "a count above 1000"),
    (r"^(?:a{100}){11}$", "nested counts multiplied"),
    (r"^a]$", r"an unescaped ]"),
    (r"^a}$", r"an unescaped }"),
    (r"^a{$", r"write \{ for a literal {"),
    (r"^\-$", r"\- outside a class"),
    (r"^[a-z]$x", "$ before the end"),
    (r"^a$\n?", "$ before the end"),                             # Python's $ also matches before a final newline
    (r"^a|b^", "^ after the start"),
    (r"^(^a)$", "^ inside a group"),
    (r"^[a&&b]$", "&& in a class"),
    (r"^\x41$", r"\x (a character code)"),                       # in all three, but outside the allowlist on purpose
]
# In the allowlist: the shipped patterns, and one of each construct that it admits.
PORTABLE = [r"^[a-z0-9-]{2,40}$", r"^cc-[0-9]{4}$", r"^(auto|manual)$", r"^[a-z]{3}$", r"[a-z]{3}", r"^abc$|^xyz$",
            r"(?:ab)+c?", r"[\^\]\-\\]x", r"x\.y\*\$\/", r"[^\n\r]+", "é+", r"a{2,}b{0,1000}", r"a+?", r"[-a][a-]",
            r"(a{10}){100}", r"[\t-\r]", "x|"]


def with_pattern(pattern: str) -> dict:
    raw = yaml.safe_load(COMPANY.read_text())
    raw["extraAnnotations"]["keys"][KEY] = {"pattern": pattern}
    return raw


@pytest.mark.parametrize("pattern, construct", NOT_PORTABLE)
def test_the_loader_refuses_a_pattern_outside_the_subset_and_names_the_key_and_the_construct(pattern, construct):
    with pytest.raises(ValueError) as e:
        MetadataKeys(with_pattern(pattern))
    message = str(e.value)
    assert f"extraAnnotations.{KEY}: pattern {pattern!r} is outside the subset" in message
    assert construct in message


@pytest.mark.parametrize("pattern", PORTABLE)
def test_the_loader_accepts_a_pattern_in_the_subset(pattern):
    keys = MetadataKeys(with_pattern(pattern))
    assert value_regex(keys.rules["annotation"][KEY], keys.email_domains) == f"^(?:{pattern})$" == anchored(pattern)


def test_the_space_class_is_python_isspace_over_every_code_point():
    space = re.compile(f"[{_SPACE}]")
    assert [hex(c) for c in range(sys.maxunicode + 1) if bool(space.fullmatch(chr(c))) != chr(c).isspace()] == []


def synthetic() -> MetadataKeys:
    """The company file, with a hyphenated mail domain (re.escape would write \\-, which ECMA-262 refuses)."""
    raw = yaml.safe_load(COMPANY.read_text())
    raw["emailDomains"] = ["company.net", "my-corp.example"]
    return MetadataKeys(raw)


def test_each_format_regex_is_in_the_subset_that_the_loader_admits():
    keys = synthetic()
    formats = [value_regex(r, keys.email_domains) for k in ("label", "annotation") for r in keys.rules[k].values() if r.format]
    assert len(formats) == 2 and all(portable_pattern_problem(rx) is None for rx in formats), formats


# ------------------------------------------------------------------------------------- one regex for the three readers
@pytest.mark.parametrize("value", ["\x01https://wiki.company.net/abc", "http://[x", "http://x]", "http://[x]/",
                                   "https://wiki.company.net/a b", "ftp://wiki.company.net/abc", "https://"])
def test_the_validator_refuses_a_bad_url_with_the_rule_and_never_raises(value):
    """On main the first is accepted (urlsplit strips a leading C0 control, the policy does not), and the brackets
    raise ValueError from urlsplit, which the API turned into 422 validation-failed, not the key's refusal."""
    keys = MetadataKeys.load(COMPANY)
    errs = keys.validate(SENT, {URL_KEY: value}, operator=False, sources=SOURCES)
    assert [(e["code"], e["key"], e["detail"]) for e in errs] == [("invalid_value", URL_KEY, "an http or https URL")]


@pytest.mark.parametrize("value", ["https://wiki.company.net/abc", "HTTP://x", "http://[::1]:8080/a?b#c",
                                   "http://u@[fe80::1]/", "http://u:p@[::1]:/", "http://x/a\u2100b"])
def test_the_validator_accepts_a_url(value):
    keys = MetadataKeys.load(COMPANY)
    assert keys.validate(SENT, {URL_KEY: value}, operator=False, sources=SOURCES) == []


# Before #332 urlsplit raised ValueError on each, so the validator refused it (a 422): an NFKC delimiter in the netloc
# (CVE-2019-9636: U+2100 is "a/c", U+FF0F "/", U+FF1A ":", U+FE6B "@"), and text before "[" or after "]" that is not a
# userinfo or a port (_check_bracketed_netloc). The one regex must not accept what the validator refused.
@pytest.mark.parametrize("value", ["http://a\u2100b/", "http://x\uff0fy/", "https://wiki\uff1acompany.net/",
                                   "http://x\ufe6by/", "http://u\uff20x/", "http://[::1]x/", "http://a[::1]/",
                                   "http://[::1]:80@x/", "http://u@[::1]x:80/", "http://[::1]:8\u2100/"])
def test_the_validator_refuses_an_authority_that_urlsplit_refused(value):
    keys = MetadataKeys.load(COMPANY)
    errs = keys.validate(SENT, {URL_KEY: value}, operator=False, sources=SOURCES)
    assert [(e["code"], e["key"], e["detail"]) for e in errs] == [("invalid_value", URL_KEY, "an http or https URL")]


def test_the_nfkc_delimiter_class_is_every_code_point_whose_nfkc_form_holds_a_url_delimiter():
    from cmapi.core.metadata import _NFKC_DELIMITERS
    want = [hex(c) for c in range(0x80, sys.maxunicode + 1) if not 0xD800 <= c <= 0xDFFF
            and any(d in unicodedata.normalize("NFKC", chr(c)) for d in "/?#@:")]
    assert [hex(ord(c)) for c in _NFKC_DELIMITERS] == want


def _urlsplit_check(value: str) -> bool:
    """The validator's URL check before #332 (main 5a8f817), kept here as the reference that the regex must not loosen."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc) and not any(c.isspace() for c in value)


def test_the_url_regex_accepts_nothing_that_the_urlsplit_check_refused():
    """20,000 seeded authorities from the pieces where the two differ: brackets, "@", ":", "%", NFKC delimiters and
    non-ASCII letters. The regex may refuse more (a leading C0 control, IPvFuture, a zone ID), never accept more."""
    keys = MetadataKeys.load(COMPANY)
    url = re.compile(value_regex(keys.rules["annotation"][URL_KEY], keys.email_domains))
    rand = random.Random(332)
    pieces = ["a", "1", "f", ":", "@", "[", "]", ".", "%", "-", "::1", "[::1]", "fe80::1", "[fe80::1]", "\u2100",
              "\uff0f", "\uff1a", "\uff20", "\ufe56", "\xe9", ":80"]
    loosened = []
    for _ in range(20000):
        value = (rand.choice(["http://", "HTTPS://"]) + "".join(rand.choice(pieces) for _ in range(rand.randint(1, 6)))
                 + rand.choice(["", "/", "/x", "?q", "#f", "/\u2100"]))
        if url.fullmatch(value) and not _urlsplit_check(value):
            loosened.append(value)
    assert loosened == [], loosened[:10]


def test_the_url_host_reads_an_ipv6_address_as_python_ipaddress_does():
    """RFC 3986's IPv6address, written out in the subset: each address that ipaddress parses is accepted in brackets,
    and each corrupted one is refused, on 3,000 random addresses in each form (seeded, so a failure repeats)."""
    keys = MetadataKeys.load(COMPANY)
    url = re.compile(value_regex(keys.rules["annotation"][URL_KEY], keys.email_domains))
    rand = random.Random(332)
    differ = []
    for _ in range(3000):
        address = ipaddress.IPv6Address(rand.getrandbits(128) & rand.choice([(1 << 128) - 1, (1 << 64) - 1, 0xFFFF_FFFF]))
        for text in (address.compressed, address.exploded, f"::ffff:{ipaddress.IPv4Address(rand.getrandbits(32))}"):
            at = rand.randrange(len(text))
            for host in (text, text[:at] + rand.choice(":0fg.") + text[at:], text[:at] + text[at + 1:]):
                try:
                    valid = bool(ipaddress.IPv6Address(host))
                except ValueError:
                    valid = False
                if bool(url.fullmatch(f"http://[{host}]/")) != valid:
                    differ.append(host)
    assert differ == [], differ[:10]


def test_the_rendered_policy_matches_with_the_one_anchored_regex_of_each_key():
    keys = synthetic()
    catalog = TierCatalog.load(EX / "config/tiers.yaml", ALL_ENVS)
    bundle = render_bundle(catalog, keys, PolicySettings(), {"rnd"}, "nonprod")
    expressions = {doc["metadata"]["name"]: doc["spec"]["validations"][0]["expression"]
                   for rel, text in bundle.items() if rel.endswith(".yaml") for doc in yaml.safe_load_all(text)}
    checked = 0
    for kind in ("label", "annotation"):
        for key, rule in keys.rules[kind].items():
            if (regex := value_regex(rule, keys.email_domains)) is not None:
                rule_name = "pattern" if rule.pattern is not None else "format"
                name = f"cmapi-metadata-rnd-{kind}-{re.sub('[^a-z0-9]+', '-', key)}-{rule_name}"
                assert f".matches({cel(regex)})" in expressions[name], key
                checked += 1
    assert checked == 3
    assert '.matches("^(?:^[a-z]{3,4}$)$")' in expressions["cmapi-metadata-rnd-label-company-net-mnemonic-pattern"]


# ---------------------------------------------------------------------------------------- the three engines, measured
CORPUS = ["", "a", "abc", "abcd", "xyz", "ab", "abab", "ababc", "x", "x|", "payments", "-payments", "a" * 63, "a" * 64,
          "cc-4410", "cc-441", "auto", "manual", "automanual", "a\n", "x\n", "abc\n", "payments\n", "\n", "\r", "^", "]",
          "-", "\\", "x.y*$/", "x.y*$", "é", "éé", "é", "café", "1", "١", "aab", "a" * 10,
          "\t", "\x0b", "payments-team@ephico2real.com", "X@EPHICO2REAL.COM", "a@ephico2real.com\n",
          "a@b@ephico2real.com", "@ephico2real.com", "abc-team@company.net", "a@MY-CORP.EXAMPLE", "a@my-corp.example",
          "a@my_corp.example", "a@company.net.", "a@Kompany.net", "https://wiki.company.net/abc", "HTTP://x",
          "http://", "http://x y", "http://x\xa0", "http://x ", "http://x\x1c", "http://x\x85", "http://x﻿",
          "\x01http://x", "http://[::1]/", "http://[x", "http://x]", "http://[x]", "http://u@[fe80::1]:8/a",
          "http://[2001:db8::8a2e:370:7334]/", "http://[::ffff:192.0.2.1]/", "http://[1:2:3:4:5:6:7:8]",
          "http://[:::::]/", "http://[1::2::3]/", "http://[12345::]/", "http://[1.2.3.4]/", "http://[::ffff:256.0.0.1]/",
          "/foo", "a/b/c", "x.company.net/y", "\U0001F600", "\x00"]


def engine_regexes() -> dict[str, str]:
    out = {f"accepted {p!r}": anchored(p) for p in PORTABLE}
    for name, keys in (("shipped", MetadataKeys.load(SHIPPED)), ("company", synthetic())):
        for kind in ("label", "annotation"):
            for key, rule in keys.rules[kind].items():
                if (regex := value_regex(rule, keys.email_domains)) is not None:
                    out[f"{name} {kind} {key}"] = regex
    return out


def python_verdicts(regexes: dict[str, str]) -> dict[str, list[bool]]:
    return {name: [re.fullmatch(rx, s) is not None for s in CORPUS] for name, rx in regexes.items()}


def tool(name: str, require: str) -> str:
    found = shutil.which(name)
    if not found:
        if os.environ.get(require) == "1":
            pytest.fail(f"{require}=1 and no {name} on PATH")
        pytest.skip(f"no {name} on PATH")
    return found


NODE = """
const { regexes, corpus } = JSON.parse(require("fs").readFileSync(0, "utf8"));
const out = {};
for (const [name, rx] of Object.entries(regexes)) { const re = new RegExp(rx, "u"); out[name] = corpus.map((s) => re.test(s)); }
process.stdout.write(JSON.stringify(out));
"""


def test_ecma_262_reads_each_regex_as_python_does():
    node = tool("node", "CMAPI_REQUIRE_NODE")
    regexes = engine_regexes()
    r = subprocess.run([node, "-e", NODE], input=json.dumps({"regexes": regexes, "corpus": CORPUS}), capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    ecma, python = json.loads(r.stdout), python_verdicts(regexes)
    differ = [(name, CORPUS[i], python[name][i]) for name in regexes for i in range(len(CORPUS))
              if ecma[name][i] != python[name][i]]
    assert differ == [], differ[:10]


def test_re2_in_the_kyverno_cli_reads_each_regex_as_python_does(tmp_path):
    kyverno = tool("kyverno", "CMAPI_REQUIRE_KYVERNO")
    regexes = engine_regexes()
    names = dict(zip(regexes, (f"rx-{i}" for i in range(len(regexes)))))
    rules = [{"apiGroups": [""], "apiVersions": ["v1"], "operations": ["CREATE", "UPDATE"], "resources": ["namespaces"]}]
    policies = [{"apiVersion": "policies.kyverno.io/v1", "kind": "ValidatingPolicy", "metadata": {"name": names[n]},
                 "spec": {"validationActions": ["Deny"], "matchConstraints": {"resourceRules": rules},
                          "validations": [{"expression": f"object.metadata.annotations['v'].matches({cel(rx)})",
                                           "message": "no match"}]}} for n, rx in regexes.items()]
    (tmp_path / "policies.yaml").write_text(yaml.safe_dump_all(policies))
    (tmp_path / "values.yaml").write_text(yaml.safe_dump_all(
        [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": f"s-{i}", "annotations": {"v": s}}}
         for i, s in enumerate(CORPUS)]))
    r = subprocess.run([kyverno, "apply", str(tmp_path / "policies.yaml"), "--resource", str(tmp_path / "values.yaml"),
                        "-p", "--output-format", "json"], capture_output=True, text=True, timeout=300)
    results = json.loads(r.stdout)["results"]
    by_name = {v: k for k, v in names.items()}
    re2 = {(by_name[x["policy"]], int(x["resources"][0]["name"][2:])): x["result"] for x in results}
    assert len(re2) == len(regexes) * len(CORPUS) and set(re2.values()) <= {"pass", "fail"}, set(re2.values())
    python = python_verdicts(regexes)
    differ = [(name, CORPUS[i], python[name][i]) for (name, i), got in re2.items() if (got == "pass") != python[name][i]]
    assert differ == [], differ[:10]


# ---------------------------------------------------------------------- #328 question 3: a required key's example
@pytest.fixture
def raw() -> dict:
    return copy.deepcopy(yaml.safe_load(COMPANY.read_text()))


def test_a_required_key_with_no_example_stops_the_start(raw):
    del raw["requiredLabels"]["company.net/mnemonic"]["example"]
    with pytest.raises(ValueError, match=re.escape("requiredLabels.company.net/mnemonic: a required key needs an example")):
        MetadataKeys(raw)


def test_a_derived_or_optional_key_needs_no_example(raw):
    raw["extraAnnotations"]["keys"]["company.net/note"] = {"description": "free text"}
    keys = MetadataKeys(raw)
    assert keys.rules["label"]["name"].example is None and keys.rules["annotation"]["company.net/note"].example is None


@pytest.mark.parametrize("stanza, key, example, why", [
    ("requiredLabels", "company.net/mnemonic", "abcde", "must match ^[a-z]{3,4}$"),
    ("requiredLabels", "company.net/cl", "7", "one of ['0', '1', '2', '3', '4', '5', '6']"),
    ("extraAnnotations", "company.net/mnemonic-group-contact", "abc@other.org", "not an address in ['company.net']"),
    ("extraAnnotations", "company.net/mnemonic-confluence", "wiki.company.net", "an http or https URL"),
])
def test_an_example_that_its_own_rule_refuses_stops_the_start(raw, stanza, key, example, why):
    (raw[stanza]["keys"] if stanza.startswith("extra") else raw[stanza])[key]["example"] = example
    with pytest.raises(ValueError, match=re.escape(f"{stanza}.{key}: the example {example!r} breaks the key's own rule "
                                                   f"({why})")):
        MetadataKeys(raw)


def test_an_example_that_is_not_text_stops_the_start(raw):
    raw["requiredLabels"]["company.net/cl"]["example"] = 1
    with pytest.raises(ValueError, match=re.escape("requiredLabels.company.net/cl: example must be text, not the int 1")):
        MetadataKeys(raw)
