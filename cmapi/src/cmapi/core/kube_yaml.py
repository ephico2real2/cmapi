"""The YAML of the Kubernetes manifests cmapi writes and reads: one writer (dump, dump_all) and one reader (load_all).

The reader (#250). A file of a namespace's folder is a YAML stream, and a stream may hold several documents separated by
`---`. PyYAML's safe_load "Parse[s] the first YAML document in a stream" and raises ComposerError "expected a single
document in the stream" when there is another (PyYAML 6.0.2, lib/yaml/__init__.py and lib/yaml/composer.py), so one
manifest with a second object, or only a trailing `---`, made each change of its namespace answer 500. Every place that
parses a folder file calls load_all, which reads every document, and finds the objects it needs by kind. The record is
docs/reviews/2026-11-25-issue-250/README.md.

The writer: YAML text that every reader of a Kubernetes manifest takes back as the same data (#355).

PyYAML quotes a string only when its own resolver would read the plain form as something else, and that resolver is not
the one the readers of cmapi's files use:

- kubectl, Argo CD and the Kyverno CLI read YAML through sigs.k8s.io/yaml, which is go-yaml v2 (YAML 1.1). Its
  resolver (go.yaml.in/yaml/v2 resolve.go) reads a plain y, Y, n or N as a bool, which PyYAML leaves out of its bool
  set, and it reads 0o17, 0X1F, 0B1, 089, 1e3 and +.5 as numbers through Go's strconv, which PyYAML's regular
  expressions do not match.
- go-yaml v3 (YAML 1.2, kustomize's kyaml) also reads 0o17 as an int and a short date such as 2026-1-2 as a timestamp.

So a team label `flag: y` written plain reached the API server as `flag: false` and was refused, and Kyverno failed
on it with `no such overload: bytes(bool)`.

KubeSafeDumper is PyYAML's SafeDumper with one change: a string that one of those readers would resolve to another type
is written quoted. It is the rule go-yaml's own encoder follows (encode.go stringv: plain only when its resolver gives
!!str back). Every other value is written exactly as SafeDumper writes it, so the files of ordinary values keep their
bytes, and with them Git diffs and plan hashes. docs/reviews/2026-11-17-issue-355/README.md has the sources and the
options that were not taken.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import yaml

_STR = "tag:yaml.org,2002:str"
_BOOL, _INT, _FLOAT, _NULL = (f"tag:yaml.org,2002:{t}" for t in ("bool", "int", "float", "null"))
_TIMESTAMP, _MERGE = "tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:merge"

# The plain scalars go-yaml v2 resolves by table (resolveMapList). y, Y, n and N are YAML 1.1's own bool forms
# (yaml.org/type/bool.html); go-yaml v3 has the same table without them.
_TABLE: dict[str, str] = {
    **dict.fromkeys(("y", "Y", "yes", "Yes", "YES", "true", "True", "TRUE", "on", "On", "ON",
                     "n", "N", "no", "No", "NO", "false", "False", "FALSE", "off", "Off", "OFF"), _BOOL),
    **dict.fromkeys(("", "~", "null", "Null", "NULL"), _NULL),
    **dict.fromkeys((".nan", ".NaN", ".NAN", ".inf", ".Inf", ".INF", "+.inf", "+.Inf", "+.INF",
                     "-.inf", "-.Inf", "-.INF"), _FLOAT),
    "<<": _MERGE,
}
# strconv.ParseInt and ParseUint with base 0, on the text with every "_" removed (resolve.go), and go-yaml's fallbacks
# of a 0b (v2, v3) or 0o (v3) prefix parsed again in base 2 or 8, whose strconv call takes a sign after the prefix.
# Size is not checked: YAML 1.2 reads an int of any size as an int.
_INT_RE = re.compile(r"[-+]?(?:0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+|0[0-7]*|[1-9][0-9]*)"
                     r"|0b[-+]?[01]+|0o[-+]?[0-7]+")
# go-yaml's yamlStyleFloat, which is also YAML 1.2.2's core schema float (section 10.3.2).
_FLOAT_RE = re.compile(r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?")
# The shapes of go-yaml's parseTimestamp layouts: 2006-1-2, 2006-1-2T15:4:5.999999999Z07:00 (T or t), and
# 2006-1-2 15:4:5.999999999. The shape alone is matched, so a date such as 2026-13-45, which time.Parse refuses, is
# quoted too: like a number too large for 64 bits, that only adds quotes. time.Parse is looser than the layouts read:
# a fraction of a second may follow a comma as well as a period (time/format.go commaOrPeriod), and the layout's one
# space matches any run of spaces in the text (format.go skip), so 2026-1-2  1:2:3,5 is a timestamp too.
_TIME = r"[0-9]{1,2}:[0-9]{1,2}:[0-9]{1,2}(?:[.,][0-9]+)?"
_TIMESTAMP_RE = re.compile(rf"[0-9]{{4}}-[0-9]{{1,2}}-[0-9]{{1,2}}(?:[Tt]{_TIME}(?:Z|[-+][0-9]{{2}}:[0-9]{{2}})| +{_TIME})?")


def foreign_tag(value: str) -> str | None:
    """The tag go-yaml v2 or v3 gives this text as a plain scalar when that is not !!str, else None. It follows the
    hints of resolve.go: a table lookup, then by the first character a float ('.') or a timestamp, int or float (a
    digit or a sign); any other first character is always a string there."""
    tag = _TABLE.get(value)
    if tag or not value:
        return tag
    first = value[0]
    if first == ".":
        return _FLOAT if _FLOAT_RE.fullmatch(value) else None
    if first in "+-0123456789":
        if _TIMESTAMP_RE.fullmatch(value):
            return _TIMESTAMP
        plain = value.replace("_", "")
        if _INT_RE.fullmatch(plain):
            return _INT
        if _FLOAT_RE.fullmatch(plain):
            return _FLOAT
    return None


class KubeSafeDumper(yaml.SafeDumper):
    """SafeDumper that quotes every string a Kubernetes reader would read as another type (see the module)."""

    def resolve(self, kind: Any, value: Any, implicit: tuple[bool, bool]) -> str:
        tag = super().resolve(kind, value, implicit)
        # The serializer asks with implicit=(True, False) whether the plain form reads back as the node's tag. Any tag
        # but !!str makes the emitter quote a string; a non-string node never resolves to !!str here, so it is untouched.
        if kind is yaml.ScalarNode and implicit[0] and tag == _STR:
            return foreign_tag(value) or tag
        return tag


def dump(doc: Any, **kwargs: Any) -> str:
    return yaml.dump(doc, Dumper=KubeSafeDumper, **kwargs)


def dump_all(docs: Iterable[Any], **kwargs: Any) -> str:
    return yaml.dump_all(docs, Dumper=KubeSafeDumper, **kwargs)


class _KubeSafeLoader(yaml.SafeLoader):
    """SafeLoader whose value that a standard tag cannot construct fails as a YAMLError at that value (#680).

    SafeConstructor builds a scalar with Python's own types, and they raise their own errors: construct_yaml_timestamp calls
    datetime.date(year, month, day), so a plain 2026-02-30 raises ValueError "day is out of range for month"; !!int abc
    raises ValueError, !!bool maybe KeyError, !!timestamp nope AttributeError (PyYAML 6.0.2, lib/yaml/constructor.py).
    None of them is a yaml.YAMLError, so no reader would refuse the file as one that PyYAML cannot read."""

    def construct_object(self, node: yaml.Node, deep: bool = False) -> Any:
        try:
            return super().construct_object(node, deep=deep)
        except yaml.YAMLError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            # The tag's short name and the node's place only: never the value, which is the file's text.
            raise yaml.constructor.ConstructorError(None, None, f"a value that is not a valid {node.tag.rsplit(':', 1)[-1]}",
                                                    node.start_mark) from exc


def load_all(text: str | None) -> list[dict[str, Any]]:
    """Every Kubernetes object of a YAML stream, in order: each document that is a mapping. A file may hold one object or
    several. An empty document (a leading or trailing `---`, a comment alone) and a document that is not a mapping are no
    object, so no reader is handed one. Safe loading: only YAML's standard tags. A stream that is not YAML, or that holds a
    value its tag cannot construct, or that is nested deeper than Python's stack allows, raises yaml.YAMLError."""
    try:
        return [d for d in yaml.load_all(text or "", Loader=_KubeSafeLoader) if isinstance(d, dict)]
    except RecursionError as exc:
        # PyYAML's parser and composer recurse once for each level of nesting, so a file some hundreds of levels deep
        # (measured with PyYAML 6.0.2 on Python 3.12: 500) exhausts the stack. It is the file's state, as a parse error is.
        raise yaml.MarkedYAMLError(problem="a document nested deeper than the reader can read") from exc
