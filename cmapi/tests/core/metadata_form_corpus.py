"""The corpus of #336: values for each field of the portal's New namespace form, each with MetadataKeys.validate()'s verdict.

The portal checks a field in the browser before it plans a request (cmapi-portal-ui/src/portal/metadataForm.ts). cmapi is
the authority, so the form must never refuse a body that validate() accepts. tests/api/direct.test.mjs runs the form's
check on every case here and fails on one that the form refuses and validate() accepts. The portal's CI job has no
Python, so the cases are a committed file (cmapi-portal-ui/tests/api/metadata-corpus.json) that
tests/core/test_metadata_form_336.py holds equal to what this module builds.

Two sources of cases, both on the shipped reference and company files:

- the create maps of the #328 corpus (metadata_corpus.cases) that the form can send: every key of the map is a field of
  the form, so a declared key of its kind that the requester sets;
- for each such field, the values of design B of #336 (fixed edge cases: Unicode, lone surrogates, control characters,
  addresses and URLs), random text and single-character edits of the rule's example, deterministic by seed.

The file holds, for each config, {namespace, environment, cases}. A case is [kind, key, value, own, accepted]: the body is
the required keys of both kinds at their examples, with `key` set to `value` (or left out when `value` is None), for the
namespace `namespace`, or `<value>-<environment>` when `own` is true (the namespacePrefix key's own name). The form fills
the other required fields with the same examples, so it reads the case as the same body.
"""
from __future__ import annotations

import random
from typing import Any

from cmapi.core.metadata import KINDS, MetadataKeys
from metadata_corpus import VALUES, cases as corpus_cases, good

SEED = 336
ALPHABET = list("abcxyzABCZ0189-_.@/:?#[] ") + ["\n", "\t", "\r", "é", "ü", "😀", " ", " ", "℀", "／", "ａ", "\u0000"]
FIXED = ["", " ", "a", "ab", "abc", "abcd", "abcde", "ABC", "Abc", "abc\n", "\nabc", "abc ", "-abc", "abc-", "a.b", "a_b",
         "a--b", "a" * 63, "a" * 64, "0", "1", "6", "7", "01", "é", "ａbc", "abc ", "😀", "\ud800", "abc\ud800",
         "auto", "manual", "AUTO", "auto\n", "cc-4410", "cc-441", "cc-44100", "CC-4410", "payments", "payments-team@ephico2real.com",
         "payments-team@EPHICO2REAL.COM", "x@ephico2real.com.evil.com", "a@b@ephico2real.com", "@ephico2real.com",
         "é@ephico2real.com", "x@ephico2real.com\n", " x@ephico2real.com", "abc-team@company.net", "abc-team@COMPANY.NET",
         "abc@company.net.evil", "a@b@company.net", "@company.net", "é@company.net", "abc-team@company.net\n", "a..b@company.net",
         ".a@company.net", "a+b@company.net", "a/b@company.net", "a\"b@company.net", "https://wiki.company.net/abc",
         "HTTPS://WIKI.company.net", "http://x", "https://", "https:///x", "https://[::1]/", "https://[::1]:8443/x",
         "https://[1:2:3:4:5:6:7:8]", "https://[::ffff:1.2.3.4]", "https://u@[::1]", "https://a b", "ftp://x", "https://x/ ",
         "https://ex.com℀x", "https://x/ok?q=1#f", "https://x\n", "https://xn--bcher-kva.example/", "https://bücher.example/",
         "https://x/😀", "https://[::1]x", "https://x]", "https://a%zz/", "https://x:abc/", "https://x:99999/",
         "https://wiki.company.net:abc/x"]
RANDOM, EDITS = 120, 60
# The #328 corpus also holds values of 3,000 and 4,097 characters, for the byte limits of other annotations. On a field of the
# form they say nothing that "a" * 64 does not (no declared property has a bound above 63 characters), and the committed
# file is read by the portal's suite: they are left out.
LONGEST = 256
ENVIRONMENT = "rnd"


def _values(rule: Any, rng: random.Random) -> list[str]:
    out = [*FIXED, *VALUES]
    if rule.example:
        out.append(rule.example)
    for v in rule.enum or ():
        out += [v, v + " ", v.upper()]
    for _ in range(RANDOM):
        out.append("".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 14))))
    for _ in range(EDITS if rule.example else 0):
        s = list(rule.example)
        i = rng.randrange(len(s) + 1)
        op = rng.choice("ids")
        if op == "i":
            s.insert(i, rng.choice(ALPHABET))
        elif s:
            if op == "d":
                s.pop(min(i, len(s) - 1))
            else:
                s[min(i, len(s) - 1)] = rng.choice(ALPHABET)
        out.append("".join(s))
    return list(dict.fromkeys(out))


def fields(keys: MetadataKeys, kind: str) -> list[str]:
    """The keys of one kind that the form shows as inputs: declared, set by the requester."""
    return [k for k, r in keys.rules[kind].items() if not r.derived]


def _namespace(keys: MetadataKeys) -> str:
    """The namespace that the form suggests from the examples: the namespacePrefix key's example, then the environment."""
    for kind in KINDS:
        for key in fields(keys, kind):
            rule = keys.rules[kind][key]
            if rule.namespace_prefix and rule.example:
                return f"{rule.example}-{ENVIRONMENT}"
    return f"payments-{ENVIRONMENT}"


def accepted(keys: MetadataKeys, kind: str, key: str, value: str | None, namespace: str) -> bool:
    """validate() on the body that the form sends for the case, as the pipeline calls it for a create."""
    body = {k: good(keys, k) for k in KINDS}
    if value is None:
        body[kind].pop(key, None)
    else:
        body[kind][key] = value
    sources = {"namespace": namespace, "environment": ENVIRONMENT, "cluster": "CRC", "instance": "nonprod"}
    return not keys.validate(body["label"], body["annotation"], operator=False, sources=sources, create=True)


def build(keys: MetadataKeys) -> dict[str, Any]:
    rng = random.Random(SEED)
    namespace = _namespace(keys)
    seen: set[tuple[str, str, str | None, bool]] = set()
    out: list[list[Any]] = []

    def add(kind: str, key: str, value: str | None, own: bool = False) -> None:
        if value is not None and len(value) > LONGEST:
            return
        if (kind, key, value, own) not in seen:
            seen.add((kind, key, value, own))
            ns = f"{value}-{ENVIRONMENT}" if own else namespace
            out.append([kind, key, value, own, accepted(keys, kind, key, value, ns)])

    # The #328 corpus: its create maps of one key beside the required ones, and the maps that leave a required key out.
    shown = {kind: set(fields(keys, kind)) for kind in KINDS}
    for case in corpus_cases(keys):
        if case.op != "create" or case.operator or not set(case.body) <= shown[case.kind]:
            continue
        base = good(keys, case.kind)
        changed = [k for k in case.body if case.body[k] != base.get(k)]
        missing = [k for k in base if k not in case.body]
        if len(changed) + len(missing) == 1:
            key = (changed or missing)[0]
            add(case.kind, key, case.body.get(key))
        elif not changed and not missing and base:
            key = next(iter(base))                  # the map of the required keys alone: the form's own body
            add(case.kind, key, base[key])
    # Each field's own values; the namespacePrefix key also with a namespace that its value starts and one that it does not.
    for kind in KINDS:
        for key in fields(keys, kind):
            rule = keys.rules[kind][key]
            for value in _values(rule, rng):
                add(kind, key, value)
                if rule.namespace_prefix:
                    add(kind, key, value, own=True)
            add(kind, key, None)
    return {"namespace": namespace, "environment": ENVIRONMENT, "cases": out}
