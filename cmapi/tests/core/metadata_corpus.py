"""The corpus of #328: maps of labels and annotations, each with what MetadataKeys.validate() answers and what the JSON
Schema of MetadataKeys.json_schema() answers. tests/core/test_metadata_schema_328.py runs it on the shipped and on
synthetic configurations; tests/service/test_metadata_schema_328_api.py runs it on each instance's served document.

The schema is read by python-jsonschema (Draft 2020-12), with `pattern` read as ECMA-262 reads it, as a client of the
API document does (ajv, Swagger UI). Each pattern is in the subset of metadata._Subset, where Python re and ECMA-262 differ
only in "$": Python's also matches before a final newline, ECMA-262's (without the m flag) only at the end. So "$" is
read as \\Z here, and each (pattern, text) pair is kept for the Node leg of the core test to check.
"""
from __future__ import annotations

import random
import re
import string
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterator, Mapping

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError

from cmapi.core.metadata import KINDS, MetadataKeys

# Each code that a schema cannot refuse, and why (MetadataKeys.json_schema's docstring).
LOOSE = {
    "operator_only_key": "the caller's role",
    "derived_key": "the request's target",
    "namespacePrefix": "the request's namespace",
    "too_many_keys": "a count of keys",
    "annotations_too_large": "a size in bytes",
    "prefix over 253": "a length bound on one part of a key, on a patch (propertyNames checks the class only there)",
    "key syntax on a patch": "a key that Git holds can be removed whatever its name",
}

VALUES = ["", "a", "ab", "payments", "-payments", "payments-", "Payments", "pay_ments", "pay.ments", "a" * 40, "a" * 41,
          "a" * 63, "a" * 64, "payments\n", "cc-4410", "cc-441", "auto", "manual", "Auto", "1", "0", "4", "amgsst", "abc",
          "abcd", "ABC", "payments-team@ephico2real.com", "X@EPHICO2REAL.COM", ".a@ephico2real.com", "a..b@ephico2real.com",
          "a@b@ephico2real.com", "a@ephico2real.com.evil", "a@ephico2real.com\n", "abc-team@company.net",
          "abc@COMPANY.NET", "https://wiki.company.net/abc", "HTTP://x", "http://", "http:///x", "http://x y", "ftp://x",
          "http://x ", "http://[x", "\x01http://x", "http://[::1]/", "http://x/ ", " http://x", "rnd", "dev", "abc-rnd",
          "abc-dev", "payments-dev", "nonprod", "CRC", "é", "x" * 4097, "é" * 3000]
KEYS = ["/foo", "foo", "Foo_bar.baz", "-foo", "a" * 63, "a" * 64, "kubernetes.io/x", "a.kubernetes.io/x", "k8s.io/x",
        "x.ephico2real.com/y", "ephico2real.com/y", "x.company.net/y", "company.net/y", "company.net/", "cmapi.net/tier",
        "cmapi.net/foo", "cmapi.net/protected", "company.net/provisioner", "UPPER.example/x", "a/b/c",
        "x.ephico2real.com/", "argocd.argoproj.io/x", "x.kyverno.io/y", "a.io/x", "team1.example.com/x",
        "teamx.example.com/x", "ax.example.com/x", "bx.example.com/x", "ab.example.com/x", "bb.example.com/x",
        "res1.example.com/x", "x.example.com/y", "x.y.company.net/z", "", "foo/", "a" * 240 + ".ephico2real.com/x",
        "a" * 240 + ".company.net/x", "a" * 240 + ".example.com/x"]


@dataclass(frozen=True)
class Case:
    kind: str
    op: str
    body: Mapping[str, str | None]
    operator: bool = False
    held: Mapping[str, str] = field(default_factory=dict)   # what Git holds besides the required keys (patch)


@dataclass
class Result:
    total: int = 0
    accepted: int = 0                                          # by validate()
    agree: int = 0
    unsound: list[tuple[Case, list[str]]] = field(default_factory=list)       # validate() accepts, the schema refuses
    loose: dict[str, int] = field(default_factory=dict)                         # the schema accepts, validate() refuses
    unexplained: list[tuple[Case, list[dict[str, Any]]]] = field(default_factory=list)


def ecma(pattern: str) -> str:
    """A pattern of the subset, as Python re must be given it to read it as ECMA-262 does."""
    out, i, in_class = [], 0, False
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "$":
            c = r"\Z"
        out.append(c)
        i += 1
    return "".join(out)


@lru_cache(maxsize=None)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(ecma(pattern))


class SchemaReader:
    """Draft 2020-12, with each `pattern` read as ECMA-262 reads it. `pairs` keeps each (pattern, text) it read."""

    def __init__(self) -> None:
        self.pairs: set[tuple[str, str]] = set()

        def pattern(validator, pattern, instance, schema) -> Iterator[ValidationError]:
            if validator.is_type(instance, "string"):
                self.pairs.add((pattern, instance))
                if not _compiled(pattern).search(instance):
                    yield ValidationError(f"{instance!r} does not match {pattern!r}")

        self.cls = validators.extend(Draft202012Validator, {"pattern": pattern})

    def validator(self, schema: Mapping[str, Any]) -> Any:
        self.cls.check_schema(schema)
        return self.cls(schema)


def good(keys: MetadataKeys, kind: str) -> dict[str, str]:
    """Each required key that the requester sends, at its example: a map that validate() accepts."""
    return {k: str(r.example) for k, r in keys.rules[kind].items() if r.required and not r.derived}


def cases(keys: MetadataKeys, seed: int = 328) -> list[Case]:
    rng = random.Random(seed)
    out: list[Case] = []
    for kind in KINDS:
        other = "annotation" if kind == "label" else "label"
        base = good(keys, kind)
        keys_of = list(dict.fromkeys([*keys.rules[kind], *keys.rules[other], *keys.operator_only, *keys.system[:3],
                                      *keys.adoption_labels, *KEYS]))
        # What Git may hold beyond the required keys, as the pipeline reads it (governed and team keys only).
        held = {k: v for k, v in {"/foo": "x", "foo": "bar", "x.ephico2real.com/held": "v", "x.company.net/held": "v",
                                  "Bad Key": "v"}.items() if keys.classify(k, kind) in ("governed", "team")}
        for op in ("create", "patch"):
            start = dict(base) if op == "create" else {}
            bodies: list[dict[str, str | None]] = [dict(start), {}]
            for key in keys_of:
                rule = keys.rules[kind].get(key)
                values = VALUES + ([rule.example] if rule and rule.example else []) + list(rule.enum or () if rule else ())
                for value in values:
                    bodies.append({**start, key: value})
                if op == "patch":
                    bodies.append({key: None})
            if op == "create":
                bodies += [{k: v for k, v in base.items() if k != key} for key in base]
            else:
                bodies += [{key: None} for key in held] + [{key: "y"} for key in held]
            # The limits: one key more than allowOther.max, and annotation values over the bytes but not the characters.
            limits = keys.allow_other[kind]
            team_key = next((k for k in ("x.ephico2real.com/k", "x.company.net/k", "k") if keys.classify(k, kind) == "team"), None)
            if team_key:
                many = {f"{team_key}{i}": "v" for i in range(limits.max + 1)}
                bodies.append({**start, **many})
                if kind == "annotation":
                    big = {f"{team_key}{i}": "é" * ((limits.max_value_bytes or 0) // 2) for i in range(40)}
                    bodies.append({**start, **big})
            for _ in range(300):
                key = rng.choice(keys_of + ["".join(rng.choice(string.ascii_letters + string.digits + "-_./")
                                                    for _ in range(rng.randint(0, 20)))])
                value = "".join(rng.choice(string.ascii_letters + string.digits + "-_.@:/ ") for _ in range(rng.randint(0, 12)))
                bodies.append({**start, key: rng.choice([value, rng.choice(VALUES)])})
            for body in bodies:
                out.append(Case(kind, op, body, held=held if op == "patch" else {}))
                if any(k in keys.operator_only for k in body):
                    out.append(Case(kind, op, body, operator=True, held=held if op == "patch" else {}))
    return out


def verdict(keys: MetadataKeys, case: Case, sources: Mapping[str, str]) -> list[dict[str, Any]]:
    """validate()'s errors for the case, as the pipeline calls it (core/pipeline.py, _metadata_refusal)."""
    other = "annotation" if case.kind == "label" else "label"
    sent = {case.kind: dict(case.body), other: good(keys, other) if case.op == "create" else {}}
    if case.op == "create":
        return keys.validate(sent["label"], sent["annotation"], operator=case.operator, sources=sources)
    current = {case.kind: {**good(keys, case.kind), **case.held}, other: good(keys, other)}
    return keys.validate(sent["label"], sent["annotation"], operator=case.operator, current_labels=current["label"],
                         current_annotations=current["annotation"], sources=sources, existing=True)


def loose_reason(keys: MetadataKeys, case: Case, errors: list[dict[str, Any]]) -> set[str] | None:
    """Why the schema could not refuse what validate() refused, or None when it should have."""
    reasons = set()
    for e in errors:
        code, key = e["code"], e.get("key", "")
        if code in LOOSE:
            reasons.add(code)
        elif code == "invalid_value" and "does not start with" in e.get("detail", ""):
            reasons.add("namespacePrefix")
        elif code == "invalid_key" and case.op == "patch" and len(key.rpartition("/")[0]) > 253:
            reasons.add("prefix over 253")
        elif code == "invalid_key" and case.op == "patch" and keys._syntax(key, None, case.kind):
            reasons.add("key syntax on a patch")
        else:
            return None
    return reasons


def run(keys: MetadataKeys, schemas: Mapping[tuple[str, str], Mapping[str, Any]], sources: Mapping[str, str],
        reader: SchemaReader | None = None) -> Result:
    """Each case through validate() and through the schema of its kind and operation."""
    reader = reader or SchemaReader()
    check = {k: reader.validator(s) for k, s in schemas.items()}
    result = Result()
    for case in cases(keys):
        errors = verdict(keys, case, sources)
        problems = [e.message for e in check[(case.kind, case.op)].iter_errors(dict(case.body))]
        result.total += 1
        result.accepted += not errors
        if not errors and problems:
            result.unsound.append((case, problems[:3]))
        elif errors and not problems:
            reasons = loose_reason(keys, case, errors)
            if reasons is None:
                result.unexplained.append((case, errors))
            for r in reasons or ():
                result.loose[r] = result.loose.get(r, 0) + 1
        else:
            result.agree += 1
    return result
