"""Label and annotation keys: classes, validation, derived values, merge patch and render order.

One file, cluster-configs/policies/metadata-keys.yaml, decides every key's class, and the same file
feeds the Kyverno bundle, so plan time, CI and admission agree (docs/02, "Labels and annotations"; #215).

    system               set only by the renderer (cluster-id, tier, requested-by, expiry, ...)
    operatorOnly         cmapi-operator and above (cmapi.net/protected)
    reservedPrefixes     Kubernetes, OpenShift and platform-controller prefixes
    requiredLabels       keys the namespace must carry, each with a rule; a key with value.from is set by cmapi
    requiredAnnotations
    extraLabels          keys: optional keys with a rule; allowOther: any other key under a prefix, within limits
    extraAnnotations
    adoptionLabels       keys read when an existing namespace is adopted (story #26), never sent by a requester

The class names that the approval rules read (keyClasses) are unchanged: a key of a required or extra stanza is
"governed", and a key that allowOther admits is "team".

Every value regex is one string that three engines read: Python re here (re.fullmatch), RE2 in the rendered Kyverno
policies (CEL matches(), core/policygen.py) and ECMA-262 in each client of the API document (JSON Schema pattern, #328).
value_regex() builds it; the loader refuses a configured pattern outside the subset that the three read alike (#332).
"""
from __future__ import annotations

import difflib
import re
import warnings
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping

import yaml

from cmapi.core.errors import Problem

# Kubernetes' key and label-value syntax (IsLabelKey, IsValidLabelValue), as text so that the API document's schema
# (json_schema, #328) reads the strings that the validator compiles.
_DNS1123_SUB_TEXT = r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*"
_NAME_TEXT = r"[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?"
_DNS1123_SUB = re.compile(f"^{_DNS1123_SUB_TEXT}$")
_NAME = re.compile(f"^{_NAME_TEXT}$")
# A mail domain: DNS labels of letters, digits and "-", as the chart's values.schema.json says (#335).
_DOMAIN = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9]*[A-Za-z0-9])?(\.[A-Za-z0-9]([-A-Za-z0-9]*[A-Za-z0-9])?)*$")

KeyClass = str   # "system" | "operatorOnly" | "reserved" | "governed" | "team" | "disallowed"
KINDS = ("label", "annotation")
# What cmapi can fill a key from. Each comes from the request's own target, never from the requester's text.
DERIVED_FROM = ("namespace", "environment", "cluster", "instance")
FORMATS = ("email-in-domains", "url")
_RULE_FIELDS = {"value", "pattern", "enum", "format", "namespacePrefix", "description", "example"}
_OLD_STANZAS = ("governed", "team")
# The stanzas of the file (#338): a list of text, or a mapping. Any other top-level key stops the start, so a misspelt
# stanza (requiredLabel) cannot load as a file with no rule in it.
_LIST_STANZAS = ("system", "operatorOnly", "reservedPrefixes", "sensitiveKeys", "emailDomains")
_MAP_STANZAS = ("requiredLabels", "requiredAnnotations", "extraLabels", "extraAnnotations", "adoptionLabels")


# ------------------------------------------------------------------------------------- the one regex of a value (#332)
# The allowlist is RFC 9485 (I-Regexp, "an interoperable regular expression format") without \p{..}, which Python re
# lacks, and without ".", which ECMA-262 reads as "not \n, \r, U+2028 or U+2029" and Python and RE2 as "not \n". It
# adds (?:...), lazy quantifiers, \$ and \/ (all three read them alike), and ^ and $ only where a whole-value match
# makes them no-ops: at the start and the end of a top-level alternative. Where Python's $ ("end, or before a final
# newline") would differ from RE2 and ECMA-262 (end only), nothing can follow it, so it is evaluated at the end.
# The decision and its sources: docs/reviews/2026-11-17-issue-332-338/README.md.
_SYNTAX = frozenset("^$\\.*+?()[]{}|/")         # escapable everywhere: ECMA-262's SyntaxCharacter and "/"
_CONTROL = {"n": "\n", "r": "\r", "t": "\t"}
# RE2 (Go regexp/syntax): "The counting forms x{n,m}, x{n,} and x{n} reject forms that create a minimum or maximum
# repetition count above 1000", nested counts multiplied (repeatIsValid).
_MAX_REPEAT = 1000
_GROUPS = (("(?P<", "a named group (?P<name>...)"), ("(?P=", "a named backreference (?P=name)"),
           ("(?<=", "a lookbehind (?<=...)"), ("(?<!", "a negative lookbehind (?<!...)"),
           ("(?<", "a named group (?<name>...)"), ("(?=", "a lookahead (?=...)"), ("(?!", "a negative lookahead (?!...)"),
           ("(?>", "an atomic group (?>...)"), ("(?#", "a comment (?#...)"), ("(?(", "a conditional group (?(...)...)"))
_ESCAPES = {
    "A": r"\A (start of text): write ^ at the start", "Z": r"\Z (end of text): write $ at the end",
    "z": r"\z (end of text): write $ at the end", "b": r"\b (a word boundary)", "B": r"\B (not a word boundary)",
    "d": r"\d (Python also matches the digits of other scripts): write [0-9]", "D": r"\D: write [^0-9]",
    "w": r"\w: write [A-Za-z0-9_]", "W": r"\W: write [^A-Za-z0-9_]",
    "s": r"\s (whitespace, a different set in each engine): write the characters in a class, as [ \t]",
    "S": r"\S (whitespace, a different set in each engine): write a class",
    "p": r"\p{...} (a Unicode property, which Python re does not read)", "P": r"\P{...} (a Unicode property)",
    "k": r"\k<name> (a named backreference)", "g": r"\g<name> (a group reference)",
    "x": r"\x (a character code): write the character itself", "u": r"\u (a character code): write the character itself",
    "U": r"\U (a character code): write the character itself", "N": r"\N{...} (a character name): write the character",
    "0": r"\0 (a character code): write the character itself", "-": r"\- outside a class: write -",
}
# Python warns on these in a class, and ECMA-262's v flag reads them as set operations.
_SET_OPERATORS = ("&&", "||", "~~", "--")


class _NotPortable(Exception):
    def __init__(self, construct: str, at: int):
        super().__init__(construct)
        self.construct, self.at = construct, at


class _Subset:
    """A recursive-descent reader of the allowlist above. It accepts a pattern or raises _NotPortable at the first
    construct outside it."""

    def __init__(self, pattern: str):
        self.s, self.i = pattern, 0

    def read(self) -> None:
        self._alternation(top=True)
        if self.i < len(self.s):
            raise _NotPortable("an unmatched )", self.i)

    def _peek(self, n: int = 0) -> str | None:
        return self.s[self.i + n] if self.i + n < len(self.s) else None

    def _alternation(self, top: bool) -> int:
        weight = self._branch(top)
        while self._peek() == "|":
            self.i += 1
            weight = max(weight, self._branch(top))
        return weight

    def _branch(self, top: bool) -> int:
        weight = 1
        if self._peek() == "^":
            if not top:
                raise _NotPortable("^ inside a group: write ^ only at the start of the pattern or of a top-level |", self.i)
            self.i += 1
        while (c := self._peek()) is not None and c not in "|)":
            if c == "$":
                if not top or self._peek(1) not in (None, "|"):
                    raise _NotPortable("$ before the end: write $ only at the end of the pattern or of a top-level |",
                                       self.i)
                self.i += 1
                break
            if c == "^":
                raise _NotPortable("^ after the start: write ^ only at the start of the pattern or of a top-level |",
                                   self.i)
            weight = max(weight, self._piece())
        return weight

    def _piece(self) -> int:
        weight = self._atom()
        c, at = self._peek(), self.i
        if c is None or c not in "*+?{":
            return weight
        if c == "{":
            low, high = self._counts()
            if high == 0:
                weight = 1                                  # x{0}: RE2 skips what it repeats
            else:
                weight *= high if high is not None else max(low, 1)
                if weight > _MAX_REPEAT:
                    raise _NotPortable(f"a repetition of more than {_MAX_REPEAT}, nested counts multiplied (RE2's limit)",
                                       at)
        else:
            self.i += 1
        if self._peek() == "?":
            self.i += 1                                     # lazy: the same verdict on a whole-value match
        if (c := self._peek()) is not None and c in "*+?{":
            raise _NotPortable("a quantifier after a quantifier (possessive, as *+, or repeated)", self.i)
        return weight

    def _counts(self) -> tuple[int, int | None]:
        m = re.compile(r"\{([0-9]+)(,([0-9]*))?\}").match(self.s, self.i)
        if not m:
            hint = "write {0,n}" if self.s.startswith("{,", self.i) else r"write \{ for a literal {"
            raise _NotPortable(f"a {{ that is not {{n}}, {{n,}} or {{n,m}}: {hint}", self.i)
        low = int(m.group(1))
        high = low if m.group(2) is None else (int(m.group(3)) if m.group(3) else None)
        if low > _MAX_REPEAT or (high is not None and high > _MAX_REPEAT):
            raise _NotPortable(f"a count above {_MAX_REPEAT} (RE2's limit)", self.i)
        if high is not None and low > high:
            raise _NotPortable("a count {n,m} with n above m", self.i)
        self.i = m.end()
        return low, high

    def _atom(self) -> int:
        c, at = self._peek(), self.i
        assert c is not None
        if c == "(":
            return self._group()
        if c == "[":
            self._class()
        elif c == "\\":
            self._escape(in_class=False)
        elif c == ".":
            raise _NotPortable(r". (any character: ECMA-262 also leaves out \r, U+2028 and U+2029): write a class, "
                               r"as [^\n\r]", at)
        elif c in "*+?{":
            raise _NotPortable(f"{c} with nothing before it to repeat" + (r": write \{ for a literal {" if c == "{" else ""),
                               at)
        elif c in "]}":
            raise _NotPortable(f"an unescaped {c}: write \\{c}", at)
        elif 0xD800 <= ord(c) <= 0xDFFF:
            raise _NotPortable("a lone surrogate", at)
        else:
            self.i += 1
        return 1

    def _group(self) -> int:
        start = self.i
        if self._peek(1) == "?":
            if not self.s.startswith("(?:", start):
                construct = next((name for prefix, name in _GROUPS if self.s.startswith(prefix, start)),
                                 "an inline flag, as (?i)")
                raise _NotPortable(construct, start)
            self.i += 3
        else:
            self.i += 1
        weight = self._alternation(top=False)
        if self._peek() != ")":
            raise _NotPortable("an unclosed (", start)
        self.i += 1
        return weight

    def _class(self) -> None:
        start = self.i
        self.i += 1
        if self._peek() == "^":
            self.i += 1
        if self._peek() == "]":
            raise _NotPortable(r"an empty class, or a ] first in a class: write \]", self.i)
        first = True
        while (c := self._peek()) != "]":
            if c is None:
                raise _NotPortable("an unclosed [", start)
            if c == "[":
                posix = self.s[self.i:self.i + 2] in ("[:", "[=", "[.")
                raise _NotPortable("a POSIX class, as [:alpha:]" if posix else r"a [ inside a class: write \[", self.i)
            if self.s.startswith(_SET_OPERATORS, self.i) and not (first and c == "-"):
                raise _NotPortable(f"{self.s[self.i:self.i + 2]} in a class (a set operation in ECMA-262's v flag and "
                                   "a warning in Python)", self.i)
            if c == "-":
                if not first and self._peek(1) != "]":
                    raise _NotPortable(r"a - inside a class that is not a range: write - first or last, or \-", self.i)
                self.i += 1
            else:
                low = self._class_char()
                if self._peek() == "-" and self._peek(1) not in ("]", None):
                    at = self.i
                    self.i += 1
                    if ord(self._class_char()) < ord(low):
                        raise _NotPortable("a range out of order", at)
            first = False
        self.i += 1

    def _class_char(self) -> str:
        c, at = self._peek(), self.i
        if c is None:
            raise _NotPortable("an unclosed [", at)
        if c == "\\":
            return self._escape(in_class=True)
        if c in "[]-":
            raise _NotPortable(f"an unescaped {c} in a range: write \\{c}", at)
        if 0xD800 <= ord(c) <= 0xDFFF:
            raise _NotPortable("a lone surrogate", at)
        self.i += 1
        return c

    def _escape(self, in_class: bool) -> str:
        at = self.i
        c = self._peek(1)
        if c is None:
            raise _NotPortable("a \\ at the end", at)
        self.i += 2
        if c in _SYNTAX or (in_class and c == "-"):
            return c
        if c in _CONTROL:
            return _CONTROL[c]
        if c in "123456789":
            raise _NotPortable(f"a backreference \\{c}", at)
        raise _NotPortable(_ESCAPES.get(c, f"the escape \\{c}"), at)


def portable_pattern_problem(pattern: str) -> str | None:
    """None when the pattern is in the subset that Python re, RE2 and ECMA-262 read alike, or the first construct
    outside it, with its position."""
    try:
        _Subset(pattern).read()
    except _NotPortable as e:
        return f"{e.construct}, at character {e.at + 1}"
    return None


def anchored(pattern: str) -> str:
    """A configured pattern as one whole-value regex, for each engine: re.fullmatch, and RE2 and ECMA-262 that search.
    The only place that anchors a pattern (#332)."""
    return f"^(?:{pattern})$"


def _literal(text: str) -> str:
    """text as a regex in the subset: ASCII letters in either case (no inline flag, which ECMA-262 lacks), a syntax
    character escaped. re.escape is not used: it escapes "-", "&", "~" and "#", and ECMA-262 refuses \\- outside a
    class in Unicode mode."""
    return "".join(f"[{c.lower()}{c.upper()}]" if c.isascii() and c.isalpha() else ("\\" + c if c in _SYNTAX else c)
                   for c in text)


# The local part of an address: one or more of these (the format email-in-domains, docs/18).
_EMAIL_LOCAL = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+"
# Python's str.isspace(), written out: RE2 reads no \u escape and ECMA-262 no \x{..}, so the characters past \r are
# literal (tests/core/test_metadata_pattern_subset_332.py holds it equal to isspace over every code point).
_SPACE = "\\t-\\r\x1c- \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
# The characters whose NFKC form holds "/", "?", "#", "@" or ":" (U+2100 ACCOUNT OF is "a/c"). urllib.parse refuses a
# netloc with one ("contains invalid characters under NFKC normalization", CVE-2019-9636), and so did the validator
# before #332, because a client that normalises the host for IDNA would split it there. Literal, as _SPACE is
# (tests/core/test_metadata_pattern_subset_332.py holds it equal to unicodedata over every code point).
_NFKC_DELIMITERS = ("\u2047\u2048\u2049\u2100\u2101\u2105\u2106\u2a74\ufe13\ufe16\ufe55\ufe56\ufe5f\ufe6b\uff03\uff0f"
                    "\uff1a\uff1f\uff20")
# The authority of a URL (RFC 3986 section 3.2): no "/", "?", "#", whitespace or NFKC delimiter. A "[" only in
# [userinfo "@"] "[" IPv6address "]" [":" port]: nothing before "[" but a userinfo and nothing after "]" but a port, as
# RFC 3986's IP-literal and urllib.parse (_check_bracketed_netloc) say; ls32 is two 16-bit pieces or an IPv4 address.
_HOST = f"[^/?#\\[\\]{_SPACE}{_NFKC_DELIMITERS}]"
_PORT = f"[^/?#@\\[\\]{_SPACE}{_NFKC_DELIMITERS}]"
_H16 = "[0-9A-Fa-f]{1,4}"
_OCTET = "(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_LS32 = f"(?:{_H16}:{_H16}|{_OCTET}(?:\\.{_OCTET}){{3}})"
_IPV6 = "|".join([f"(?:{_H16}:){{6}}{_LS32}", f"::(?:{_H16}:){{5}}{_LS32}", f"(?:{_H16})?::(?:{_H16}:){{4}}{_LS32}",
                  *(f"(?:(?:{_H16}:){{0,{n}}}{_H16})?::(?:{_H16}:){{{4 - n}}}{_LS32}" for n in (1, 2)),
                  f"(?:(?:{_H16}:){{0,3}}{_H16})?::{_H16}:{_LS32}", f"(?:(?:{_H16}:){{0,4}}{_H16})?::{_LS32}",
                  f"(?:(?:{_H16}:){{0,5}}{_H16})?::{_H16}", f"(?:(?:{_H16}:){{0,6}}{_H16})?::"])
_URL = (f"^{_literal('http')}[sS]?://(?:{_HOST}+|(?:{_HOST}*@)?\\[(?:{_IPV6})\\](?::{_PORT}*)?)"
        f"(?:[/?#][^{_SPACE}]*)?$")


def value_regex(rule: "KeyRule", domains: list[str]) -> str | None:
    """The one regex of a declared key's value, or None when its rule has none (an enum, a derived key, any value).
    The validator, the Kyverno renderer and the API document (#328) each use this string (#332)."""
    if rule.pattern is not None:
        return anchored(rule.pattern)
    if rule.format == "email-in-domains":
        return f"^{_EMAIL_LOCAL}@(?:{'|'.join(_literal(d) for d in domains)})$"
    if rule.format == "url":
        return _URL
    return None


# ------------------------------------------------------------------------- the schema of labels and annotations (#328)
# Each regex below is in the subset of _Subset (tests/core/test_metadata_schema_328.py holds it), so ECMA-262 reads it as
# the validator does. A label value: empty, or _NAME of at most 63 characters (maxLength says the 63).
_LABEL_VALUE = f"^(?:{_NAME_TEXT})?$"
# A key: an optional DNS-1123 subdomain and "/", then a name of 1 to 63 characters. The prefix's 253 characters are a
# second schema, in "not" (_LONG_PREFIX): a length bound on one part of a single regex would need a lookahead, which
# RE2 lacks. _KEY allows one "/" at most, so the text before it is the prefix that _syntax reads.
_KEY = f"^(?:{_DNS1123_SUB_TEXT}/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{{0,61}}[A-Za-z0-9])?$"
_KEY_MAX = 253 + 1 + 63
_LONG_PREFIX = "^[^/]{254}"
_OPS = ("create", "patch")


def _glob_regex(glob: str, *, exact: bool) -> str | None:
    """fnmatchcase(prefix, glob) as a regex of the prefix (a key's text before its first "/", so it holds no "/").
    A [...] class is read as fnmatch reads it; when it is not one that the subset can say exactly, exact=False gives
    any one character (a wider set, for a set of keys that are admitted) and exact=True gives None (for a set of keys
    that are refused, which must never hold more than the validator refuses)."""
    out, i, n = [], 0, len(glob)
    while i < n:
        c = glob[i]
        i += 1
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + (i < n and glob[i] == "!")
            j += j < n and glob[j] == "]"
            while j < n and glob[j] != "]":
                j += 1
            if j >= n:
                out.append("\\[")                       # fnmatch: a [ that no ] closes is the character itself
                continue
            body, i = glob[i:j], j + 1
            negate, body = body.startswith("!"), body[1:] if body.startswith("!") else body
            klass = _glob_class(body, negate)
            if klass is None:
                if exact:
                    return None
                klass = "[^/]"
            out.append(klass)
        elif c == "/":
            # A prefix holds no "/", so fnmatchcase never matches this glob: as keys that are refused it is none (None);
            # as keys that are admitted, a "/" only widens the set. The regex is read on a whole key (^(?:R)/ in
            # _key_names), where a "/" here would reach past the prefix into a key that the validator admits.
            if exact:
                return None
            out.append("\\/")
        else:
            out.append("\\" + c if c in _SYNTAX else c)
    return "".join(out)


def _glob_class(body: str, negate: bool) -> str | None:
    """One fnmatch class as a regex class in the subset, or None. Ranges as a-z; every other character is itself. A
    prefix holds no "/", so "/" is left out of the class (a range over it is split around it), as [^/ leaves it out of
    a negated one: the class is read on a whole key, and must not match the "/" that ends the prefix."""
    parts, i = [], 0
    while i < len(body):
        if i + 2 < len(body) and body[i + 1] == "-":
            low, high = body[i], body[i + 2]
            if low > high:
                return None                                 # fnmatch drops an empty range; say it as unknown
            spans = [(low, "."), ("0", high)] if low <= "/" <= high else [(low, high)]   # "." and "0" are "/" -1, +1
            parts += [_class_char(a) if a == b else _class_char(a) + "-" + _class_char(b) for a, b in spans if a <= b]
            i += 3
        else:
            if body[i] != "/":
                parts.append(_class_char(body[i]))
            i += 1
    if negate and not parts:
        return "[^/]"                                       # [!/]: any character of a prefix
    text = ("[^/" if negate else "[") + "".join(parts) + "]"
    return text if parts and portable_pattern_problem(text) is None else None


def _class_char(c: str) -> str:
    return "\\" + c if c in "\\]^[-" else c


def _glob_tokens(glob: str) -> list[str | None]:
    """A glob as "*", one character, or None for any one character (? or a [...] class, read as any character)."""
    out: list[str | None] = []
    i, n = 0, len(glob)
    while i < n:
        c = glob[i]
        i += 1
        if c == "[":
            j = i + (i < n and glob[i] == "!")
            j += j < n and glob[j] == "]"
            while j < n and glob[j] != "]":
                j += 1
            if j < n:
                out.append(None)
                i = j + 1
                continue
        out.append(None if c == "?" else c)
    return out


def _globs_meet(a: str, b: str) -> bool:
    """Whether some non-empty text matches both globs. It may answer True for two that do not meet (a class is read
    as any character); the caller only adds an exact exclusion that is then not needed."""
    x, y = _glob_tokens(a), _glob_tokens(b)
    seen: dict[tuple[int, int], bool] = {}

    def meet(i: int, j: int) -> bool:
        if (i, j) not in seen:
            seen[(i, j)] = False                        # a cycle through two "*" adds nothing
            if i == len(x) and j == len(y):
                result = True
            elif i < len(x) and x[i] == "*":
                result = meet(i + 1, j) or (j < len(y) and meet(i, j + 1))
            elif j < len(y) and y[j] == "*":
                result = meet(i, j + 1) or (i < len(x) and meet(i + 1, j))
            else:
                result = i < len(x) and j < len(y) and (x[i] is None or y[j] is None or x[i] == y[j]) and \
                    meet(i + 1, j + 1)
            seen[(i, j)] = result
        return seen[(i, j)]

    return meet(0, 0)


def _kind_of(value: Any) -> str:
    """What a value of the file is, for a message."""
    if value is None:
        return "empty"
    if isinstance(value, Mapping):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, str):
        return f"the text {value!r}"
    return f"the {type(value).__name__} {value!r}"


@dataclass(frozen=True)
class KeyRule:
    """The rule of one declared key. At most one of derived, pattern, enum and format says what a value is."""
    kind: str                           # label | annotation
    required: bool
    derived: str | None = None          # one of DERIVED_FROM: cmapi sets the value, the requester does not
    pattern: str | None = None
    enum: tuple[str, ...] | None = None
    format: str | None = None           # one of FORMATS
    namespace_prefix: bool = False      # the namespace name must start with "<value>-"
    description: str | None = None
    example: str | None = None

    def text(self, domains: list[str]) -> str:
        """The rule in words, for a refusal and for the API document."""
        parts = []
        if self.derived:
            parts.append(f"set by cmapi from the {self.derived}")
        if self.pattern:
            parts.append(f"must match {self.pattern}")
        if self.enum is not None:
            parts.append(f"one of {list(self.enum)}")
        if self.format == "email-in-domains":
            parts.append(f"an address in {domains}")
        if self.format == "url":
            parts.append("an http or https URL")
        if self.namespace_prefix:
            parts.append("the start of the namespace name, before its first '-'")
        return "; ".join(parts) or "any value"


@dataclass(frozen=True)
class AllowOther:
    """The keys of one kind that no stanza declares: under one of the prefixes, within the limits."""
    prefixes: tuple[str, ...]
    max: int
    max_value_bytes: int | None = None
    max_bytes_total: int | None = None


class MetadataKeys:
    def __init__(self, raw: Mapping[str, Any]):
        if not isinstance(raw, Mapping):
            # An empty file reads as None: it has no stanza, so no key would be required (#338).
            raise ValueError(f"metadata-keys.yaml is a mapping of the stanzas {list(_LIST_STANZAS + _MAP_STANZAS)}, "
                             f"not {_kind_of(raw)}")
        problems: list[str] = []
        old = [s for s in _OLD_STANZAS if s in raw]
        if old:
            # A file of the old format must not start: its required keys would silently stop being required.
            raise ValueError(f"metadata-keys.yaml has the stanzas {old} of the old format; write requiredLabels, "
                             "requiredAnnotations, extraLabels and extraAnnotations instead (docs/02, \"Labels and annotations\")")
        for stanza in raw:
            if stanza not in _LIST_STANZAS + _MAP_STANZAS:
                # A misspelt stanza (requiredLabel) would otherwise load as a file without its rules (#338).
                near = difflib.get_close_matches(str(stanza), _LIST_STANZAS + _MAP_STANZAS, n=1)
                problems.append(f"unknown stanza {stanza!r}" + (f": did you mean {near[0]}?" if near else
                                                                 f"; the stanzas are {list(_LIST_STANZAS + _MAP_STANZAS)}"))
        self.system = self._texts(raw, "system", problems)
        self.operator_only = self._texts(raw, "operatorOnly", problems)
        self.reserved_prefixes = [p.rstrip("/") for p in self._texts(raw, "reservedPrefixes", problems)]
        self.sensitive = set(self._texts(raw, "sensitiveKeys", problems))
        domains = self._texts(raw, "emailDomains", problems)
        bad = [d for d in domains if len(d) > 253 or not _DOMAIN.fullmatch(d)]
        if bad:
            problems.append(f"emailDomains: {bad} are not domain names (labels of letters, digits and -, joined by .)")
        self.email_domains = [d.lower() for d in domains]
        # {kind: {key: KeyRule}}: a key can be a label and an annotation at once, each with its own rule.
        self.rules: dict[str, dict[str, KeyRule]] = {"label": {}, "annotation": {}}
        self.allow_other: dict[str, AllowOther] = {}
        for kind, req_name, extra_name in (("label", "requiredLabels", "extraLabels"),
                                           ("annotation", "requiredAnnotations", "extraAnnotations")):
            for key, spec in self._mapping(raw, req_name, problems).items():
                self._add(kind, key, spec, True, req_name, problems)
            extra = self._mapping(raw, extra_name, problems)
            unknown = set(extra) - {"keys", "allowOther"}
            if unknown:
                problems.append(f"{extra_name}: unknown fields {sorted(unknown)}")
            for key, spec in self._mapping(extra, "keys", problems, extra_name).items():
                self._add(kind, key, spec, False, extra_name, problems)
            self.allow_other[kind] = self._allow_other(kind, self._mapping(extra, "allowOther", problems, extra_name),
                                                       extra_name, problems)
        self.adoption_labels: dict[str, tuple[str, ...]] = {}
        for key, spec in self._mapping(raw, "adoptionLabels", problems).items():
            if not isinstance(spec, Mapping) or set(spec) - {"recognise"}:
                problems.append(f"adoptionLabels.{key}: an entry is {{recognise: [values]}}, not {_kind_of(spec)}"
                                + (f" with the fields {sorted(map(str, spec))}" if isinstance(spec, Mapping) else ""))
                continue
            values = spec.get("recognise")
            if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
                problems.append(f"adoptionLabels.{key}: recognise must be a list of values")
                continue
            if any(key in self.rules[k] for k in KINDS):
                problems.append(f"adoptionLabels.{key}: a key that a requester can set is not an adoption label")
            if self._syntax(key, None, "label") or any(v and (len(v) > 63 or not _NAME.fullmatch(v)) for v in values):
                problems.append(f"adoptionLabels.{key}: not a valid label key and values")
            if key in self.system or key in self.operator_only:
                problems.append(f"adoptionLabels.{key}: a system or operator-only key is not an adoption label")
            self.adoption_labels[key] = tuple(values)
        if problems:
            raise ValueError("invalid metadata-keys.yaml: " + "; ".join(problems))

    @staticmethod
    def _texts(raw: Mapping[str, Any], name: str, problems: list[str]) -> list[str]:
        """A stanza that is a list of text. Empty (null) is []. A text is refused: list("x.com") would read it as its
        characters (#338)."""
        value = raw.get(name)
        if value is None:
            return []
        if not isinstance(value, list):
            problems.append(f"{name} must be a list of text, as [a, b], not {_kind_of(value)}")
            return []
        odd = [v for v in value if not isinstance(v, str)]
        if odd:
            problems.append(f"{name} must be a list of text; {odd[0]!r} is not text")
            return []
        return list(value)

    @staticmethod
    def _mapping(raw: Mapping[str, Any], name: str, problems: list[str], parent: str = "") -> Mapping[str, Any]:
        """A stanza or field that is a mapping. Empty (null) is {}."""
        value = raw.get(name)
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            problems.append(f"{parent + '.' if parent else ''}{name} must be a mapping, not {_kind_of(value)}")
            return {}
        return value

    def _add(self, kind: str, key: str, spec: Any, required: bool, stanza: str, problems: list[str]) -> None:
        where = f"{stanza}.{key}"
        if not isinstance(key, str):
            problems.append(f"{stanza}: the key {key!r} is not text")
            return
        # An empty rule (key:) is a key with any value. "", 0, false and [] are not empty: `spec or {}` read each as
        # one, so a typo loaded an unrestricted key where a truthy scalar was refused (#338).
        spec = {} if spec is None else spec
        if not isinstance(spec, Mapping):
            problems.append(f"{where}: a key's rule is a mapping, not {_kind_of(spec)}")
            return
        unknown = set(spec) - _RULE_FIELDS
        if unknown:
            problems.append(f"{where}: unknown fields {sorted(unknown)}")
        key_ok = not self._syntax(key, None, kind)
        if not key_ok:
            problems.append(f"{where}: not a valid {kind} key")
        if key in self.system or key in self.operator_only or \
                ("/" in key and self._prefix_in(self._prefix(key), self.reserved_prefixes)):
            problems.append(f"{where}: a system, operator-only or reserved key cannot be set by a requester")
        if key in self.rules[kind]:
            problems.append(f"{where}: declared twice as a {kind}")
        for field, want in (("description", str), ("example", str), ("namespacePrefix", bool)):
            if spec.get(field) is not None and not isinstance(spec[field], want):
                problems.append(f"{where}: {field} must be {'text' if want is str else 'true or false'}, "
                                f"not {_kind_of(spec[field])}")
        derived = None
        if "value" in spec:
            derived = (spec["value"] or {}).get("from") if isinstance(spec["value"], Mapping) else None
            if derived not in DERIVED_FROM:
                problems.append(f"{where}: value.from must be one of {list(DERIVED_FROM)}")
        enum = spec.get("enum")
        if enum is not None and (not isinstance(enum, list) or not enum or not all(isinstance(v, str) for v in enum)):
            problems.append(f"{where}: enum must be a list of strings")
            enum = None
        if kind == "label" and enum:
            bad = [v for v in enum if v and not _NAME.fullmatch(v)]
            if bad:
                problems.append(f"{where}: enum values {bad} are not valid label values")
        fmt = spec.get("format")
        if fmt is not None and fmt not in FORMATS:
            problems.append(f"{where}: unknown format {fmt}")
        if fmt == "email-in-domains" and not self.email_domains:
            problems.append(f"{where}: format email-in-domains needs emailDomains")
        if fmt in FORMATS and kind == "label":
            # A label value is at most 63 characters of [A-Za-z0-9_.-]: it cannot hold the "@" of an address or the
            # "://" of a URL, so the key would refuse every value that its own format accepts.
            holds = "a URL" if fmt == "url" else "an address"
            problems.append(f"{where}: format {fmt} is for annotations only; a label value cannot hold {holds}")
        pattern = spec.get("pattern")
        regex_ok = self._pattern_ok(where, pattern, problems)
        if derived and (pattern is not None or enum is not None or fmt is not None or spec.get("namespacePrefix")):
            problems.append(f"{where}: a key with value.from takes no pattern, enum, format or namespacePrefix")
        if sum(x is not None for x in (pattern, enum, fmt)) > 1:
            problems.append(f"{where}: give one of pattern, enum and format")
        example = spec.get("example")
        rule = KeyRule(kind=kind, required=required, derived=derived, pattern=pattern,
                       enum=tuple(enum) if enum is not None else None, format=fmt,
                       namespace_prefix=bool(spec.get("namespacePrefix")),
                       description=spec.get("description"), example=example)
        self.rules[kind][key] = rule
        if required and not derived and example is None:
            # The owner's decision (#328, question 3): the API document shows each required key with its example, and
            # a document whose example misses a required key fails its own schema. cmapi does not invent one.
            problems.append(f"{where}: a required key needs an example, a value that its rule accepts, for the API "
                            "document")
        elif isinstance(example, str) and not derived and regex_ok and key_ok:
            refused = self._syntax(key, example, kind) or next(iter(self._governed(key, example, kind, {})), None)
            if refused:
                problems.append(f"{where}: the example {example!r} breaks the key's own rule "
                                f"({refused.get('detail', rule.text(self.email_domains))})")

    @staticmethod
    def _pattern_ok(where: str, pattern: Any, problems: list[str]) -> bool:
        """A configured pattern compiles in Python and is in the subset that RE2 and ECMA-262 read alike (#332)."""
        if pattern is None:
            return True
        if not isinstance(pattern, str) or not pattern:
            problems.append(f"{where}: pattern must be a non-empty text, not {_kind_of(pattern)}")
            return False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)     # a nested set: refused below with its name
                re.compile(pattern)
        except re.error as exc:
            problems.append(f"{where}: pattern does not compile: {exc}")
            return False
        problem = portable_pattern_problem(pattern)
        if problem:
            problems.append(f"{where}: pattern {pattern!r} is outside the subset that Python re, RE2 (Kyverno) and "
                            f"ECMA-262 (the API document) read alike: {problem} (docs/18, \"Patterns\")")
            return False
        return True

    @staticmethod
    def _allow_other(kind: str, raw: Mapping[str, Any], stanza: str, problems: list[str]) -> AllowOther:
        known = {"prefixes", "max"} | ({"maxValueBytes", "maxBytesTotal"} if kind == "annotation" else set())
        unknown = set(raw) - known
        if unknown:
            problems.append(f"{stanza}.allowOther: unknown fields {sorted(unknown)}")
        prefixes = raw.get("prefixes", [])
        if not isinstance(prefixes, list) or not all(isinstance(p, str) for p in prefixes):
            problems.append(f"{stanza}.allowOther.prefixes must be a list")
            prefixes = []
        limits = {"max": raw.get("max", 50)}
        if kind == "annotation":
            limits.update(maxValueBytes=raw.get("maxValueBytes", 4096), maxBytesTotal=raw.get("maxBytesTotal", 65536))
        for name, value in limits.items():
            # bool is an int in Python; "max: yes" is not a limit
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                problems.append(f"{stanza}.allowOther.{name} must be a whole number, zero or more")
                limits[name] = 0
        return AllowOther(prefixes=tuple(p.rstrip("/") for p in prefixes), max=limits["max"],
                          max_value_bytes=limits.get("maxValueBytes"), max_bytes_total=limits.get("maxBytesTotal"))

    @classmethod
    def load(cls, path: str | Path) -> "MetadataKeys":
        return cls(yaml.safe_load(Path(path).read_text()))

    # ---- classes
    @staticmethod
    def _prefix(key: str) -> str:
        return key.split("/", 1)[0] if "/" in key else ""

    @staticmethod
    def _prefix_in(prefix: str, patterns: list[str] | tuple[str, ...]) -> bool:
        # A pattern names a prefix, and only "" admits a key with no prefix (docs/18, allowOther). The no-prefix case is
        # not matched against the patterns, since fnmatchcase("", "*") is true (#331).
        if not prefix:
            return "" in patterns
        return any(fnmatchcase(prefix, p) for p in patterns)

    def classify(self, key: str, kind: str | None = None) -> KeyClass:
        """The class of a key. With no kind, a key is governed or team when it is so as a label or an annotation."""
        if key in self.system:
            return "system"
        if key in self.operator_only:
            return "operatorOnly"
        kinds = KINDS if kind is None else (kind,)
        if key in self.adoption_labels and "label" in kinds:
            # Another tool's mark (story #26): reserved even when allowOther admits its prefix, or a requester
            # could mark a namespace as one that the old way provisioned.
            return "reserved"
        if any(key in self.rules[k] for k in kinds):
            return "governed"
        prefix = self._prefix(key)
        if prefix and self._prefix_in(prefix, self.reserved_prefixes):
            return "reserved"
        if any(self._prefix_in(prefix, self.allow_other[k].prefixes) for k in kinds):
            return "team"
        return "disallowed"

    # ---- derived values
    def derived(self, sources: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """(labels, annotations) that cmapi sets, from the request's target: {"namespace": ..., "environment": ...}."""
        out: dict[str, dict[str, str]] = {"label": {}, "annotation": {}}
        for kind in KINDS:
            for key, rule in self.rules[kind].items():
                if rule.derived and sources.get(rule.derived):
                    out[kind][key] = sources[rule.derived]
        return out["label"], out["annotation"]

    # ---- validation of what a caller sends (never the renderer's own system keys)
    def validate(self, labels: Mapping[str, str | None], annotations: Mapping[str, str | None], *,
                 operator: bool, require_governed: bool = True,
                 current_labels: Mapping[str, str] | None = None,
                 current_annotations: Mapping[str, str] | None = None,
                 sources: Mapping[str, str] | None = None, existing: bool = False) -> list[dict[str, Any]]:
        """labels/annotations: what the caller sends (a merge patch; None removes a key).
        Classes and values are checked on what is sent; required keys and limits on the result,
        so a PATCH can neither remove a required key nor slip past the caps. sources: the request's target
        (namespace, environment, cluster, instance), from which cmapi fills each value.from key.

        existing: the namespace is in Git already. Then a required key that its current version lacks, and that the
        request does not touch, is held: not refused, as the rendered policies hold it (the owner's decision on #26: a
        missing required key is never forced, only reported). A request that sends the key must give a valid value."""
        sources = sources or {}
        errs: list[dict[str, Any]] = []
        merged = {"label": self.merge_patch(current_labels or {}, labels),
                  "annotation": self.merge_patch(current_annotations or {}, annotations)}
        for kind, items in (("label", labels), ("annotation", annotations)):
            held = (current_labels if kind == "label" else current_annotations) or {}
            for key, value in items.items():
                # Removing a key that the namespace holds writes nothing, so its syntax is not checked: a key that Git
                # holds from before #330 ("/foo") can be removed, though no request may set it now.
                e = None if value is None and key in held else self._syntax(key, value, kind)
                if e:
                    errs.append(e)
                    continue
                cls = self.classify(key, kind)
                # A key declared for the other kind only (#234: the company's contact and wiki keys are annotations)
                # is refused here even when allowOther admits its prefix, or it would pass as a team key.
                other = "annotation" if kind == "label" else "label"
                if cls in ("team", "disallowed") and key in self.rules[other]:
                    article = "an" if other == "annotation" else "a"
                    errs.append({"code": "invalid_key", "key": key, "detail": f"{key} is {article} {other}"})
                elif cls in ("system", "reserved"):
                    errs.append({"code": "reserved_key", "key": key})
                elif cls == "disallowed":
                    errs.append({"code": "invalid_key", "key": key, "detail": "prefix not allowed"})
                elif cls == "operatorOnly" and not operator:
                    errs.append({"code": "operator_only_key", "key": key})
                elif cls == "governed":
                    errs.extend(self._governed(key, value, kind, sources))
        if require_governed:
            for kind in KINDS:
                for key, rule in self.rules[kind].items():
                    if rule.required and not rule.derived and not merged[kind].get(key):
                        sent = labels if kind == "label" else annotations
                        current = (current_labels if kind == "label" else current_annotations) or {}
                        if existing and key not in sent and not current.get(key):
                            continue                # held: the namespace lacked it before, and the request leaves it
                        errs.append({"code": "missing_required_key", "key": key, "kind": kind,
                                     "detail": rule.text(self.email_domains)})
        # A value that the request does not send is the current one, which Git holds: it is not checked again (the same
        # rule as the bounds of tiers.py and the rendered policies). Each value that the request sends is checked above.
        for kind in KINDS:
            limits = self.allow_other[kind]
            team = {k: v for k, v in merged[kind].items() if self.classify(k, kind) == "team"}
            if len(team) > limits.max:
                errs.append({"code": "too_many_keys", "kind": kind, "detail": f"at most {limits.max} other {kind}s"})
            if kind == "annotation":
                sizes = [len(v.encode()) for v in team.values()]
                if any(s > (limits.max_value_bytes or 0) for s in sizes) or sum(sizes) > (limits.max_bytes_total or 0):
                    errs.append({"code": "annotations_too_large"})
        return errs

    def _syntax(self, key: str, value: str | None, kind: str) -> dict[str, Any] | None:
        # Kubernetes' IsLabelKey, which also checks annotation keys (#330): a "/" needs a prefix before it, so "/foo" has
        # an empty prefix ("prefix part must be non-empty"), not none. A second "/" stays in the prefix, which the DNS
        # subdomain check refuses.
        prefix, slash, name = key.rpartition("/")
        if (slash and (not prefix or len(prefix) > 253 or not _DNS1123_SUB.fullmatch(prefix))) or \
                len(name) > 63 or not _NAME.fullmatch(name):
            return {"code": "invalid_key", "key": key}
        if kind == "label" and value not in (None, "") and (len(value) > 63 or not _NAME.fullmatch(value)):
            return {"code": "invalid_value", "key": key, "detail": "not a valid label value"}
        return None

    def _governed(self, key: str, value: str | None, kind: str, sources: Mapping[str, str]) -> list[dict[str, Any]]:
        rule = self.rules[kind].get(key)
        if rule is None:
            other = "annotation" if kind == "label" else "label"
            return [{"code": "invalid_key", "key": key, "detail": f"{key} is a {other}"}]
        if rule.derived:
            expected = sources.get(rule.derived)
            # The same value is accepted, so a client that sends back what it read is not refused.
            if value is None or (expected is not None and value != expected):
                return [{"code": "derived_key", "key": key, "kind": kind,
                         "detail": f"cmapi sets {key} from the {rule.derived}" + (f" ({expected})" if expected else "")}]
            return []
        if value is None:
            return []
        # The regex of the pattern or the format: the string that the rendered Kyverno policy matches too (#332).
        regex = value_regex(rule, self.email_domains)
        if regex is not None and not re.fullmatch(regex, value):
            if rule.format == "email-in-domains":
                code = "invalid-team-dl" if key == "cmapi.net/team-dl" else "invalid_value"
                return [{"code": code, "key": key, "detail": f"not an address in {self.email_domains}"}]
            detail = f"must match {rule.pattern}" if rule.pattern is not None else rule.text(self.email_domains)
            return [{"code": "invalid_value", "key": key, "detail": detail}]
        if rule.enum is not None and value not in rule.enum:
            return [{"code": "invalid_value", "key": key, "detail": f"one of {list(rule.enum)}"}]
        namespace = sources.get("namespace")
        if rule.namespace_prefix and namespace and not namespace.startswith(f"{value}-"):
            return [{"code": "invalid_value", "key": key, "detail": f"{namespace} does not start with {value}-"}]
        return []

    def check(self, labels, annotations, *, operator: bool, require_governed: bool = True,
              current_labels=None, current_annotations=None, sources=None, existing: bool = False) -> None:
        errs = self.validate(labels, annotations, operator=operator,
                             require_governed=require_governed, current_labels=current_labels,
                             current_annotations=current_annotations, sources=sources, existing=existing)
        if any(e["code"] == "operator_only_key" for e in errs):
            raise Problem.forbidden("Only cmapi-operator may set " +
                                    ", ".join(e["key"] for e in errs if e["code"] == "operator_only_key"))
        if errs:
            raise Problem.policy_violation("Metadata refused", errs)

    # ---- changes and order
    @staticmethod
    def merge_patch(current: Mapping[str, str], patch: Mapping[str, str | None]) -> dict[str, str]:
        out = dict(current)
        for k, v in patch.items():
            if v is None:
                out.pop(k, None)
            else:
                out[k] = v
        return out

    def change_facts(self, before: Mapping[str, str], after: Mapping[str, str]) -> dict[str, Any]:
        """Facts for the approval engine: which classes changed, and whether a sensitive key did."""
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        # a sensitive key counts when an existing value changes or goes; setting it the first time
        # (every create sets cmapi.net/team) is not a change of ownership
        sensitive = {k for k in changed & self.sensitive if k in before}
        return {"keyClasses": sorted({self.classify(k) for k in changed}),
                "sensitiveKeyChanged": bool(sensitive)}

    def ordered(self, items: Mapping[str, str]) -> dict[str, str]:
        """Render order: system keys first, then governed, then the rest; each group sorted."""
        rank = {"system": 0, "reserved": 0, "operatorOnly": 0, "governed": 1}
        return dict(sorted(items.items(), key=lambda kv: (rank.get(self.classify(kv[0]), 2), kv[0])))

    # ---- the API document (#328)
    def json_schema(self, kind: str, op: str) -> dict[str, Any]:
        """The JSON Schema 2020-12 of the labels (kind=label) or annotations of NamespaceCreate (op=create) or of
        NamespacePatch (op=patch, the object branch of its anyOf with null), from this file, for the API document.

        It documents validate(); it never replaces it. It is sound: each map that validate() accepts passes it
        (tests/core/test_metadata_schema_328.py runs both on one corpus). What JSON Schema cannot say stays loose and is
        said in words: who the caller is (operatorOnly), the request's target (a derived value, namespacePrefix), the
        count of other keys and the sizes in bytes (allowOther), and on a patch the 253 characters of a key's prefix."""
        if kind not in KINDS or op not in _OPS:
            raise ValueError(f"json_schema: kind is one of {KINDS} and op one of {_OPS}, not {kind!r}, {op!r}")
        patch = op == "patch"
        rules, other = self.rules[kind], self.allow_other[kind]
        properties = {key: self._rule_schema(rule, patch) for key, rule in rules.items()}
        for key in self.operator_only:
            properties[key] = self._nullable(self._operator_schema(kind), patch)
        extra: dict[str, Any] = {"type": "string"}
        if kind == "label":
            extra.update(pattern=_LABEL_VALUE, maxLength=63)
        elif other.max_value_bytes is not None:
            # A character is one to four bytes in UTF-8, so a bound on bytes is at least this bound on characters.
            extra["maxLength"] = other.max_value_bytes
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        required = [key for key, rule in rules.items() if rule.required and not rule.derived]
        if required and not patch:
            schema["required"] = required
        schema["propertyNames"] = self._key_names(kind, list(properties), patch)
        schema["additionalProperties"] = {"anyOf": [extra, {"type": "null"}]} if patch else extra
        limits: dict[str, Any] = {"prefixes": [p + "/" if p else "" for p in other.prefixes], "max": other.max}
        if kind == "annotation":
            limits.update(maxValueBytes=other.max_value_bytes, maxBytesTotal=other.max_bytes_total)
        schema["x-cmapi-other-keys"] = limits
        return schema

    @staticmethod
    def _nullable(schema: dict[str, Any], patch: bool) -> dict[str, Any]:
        """On a merge patch, null removes the key. FastAPI's form, anyOf with null, so oasdiff compares like with like:
        it reads a type list [string, null] against anyOf as a narrowing (measured, docs/reviews/2026-11-16-issue-328)."""
        if not patch:
            return schema
        words = {k: schema.pop(k) for k in ("description", "examples") if k in schema}
        marks = {k: schema.pop(k) for k in list(schema) if k.startswith("x-cmapi-")}
        return {"anyOf": [schema, {"type": "null"}], **words, **marks}

    def _operator_schema(self, kind: str) -> dict[str, Any]:
        out: dict[str, Any] = {"type": "string"}
        if kind == "label":
            out.update(pattern=_LABEL_VALUE, maxLength=63)
        out["description"] = "cmapi-operator and above only: a requester gets 403 forbidden."
        out["x-cmapi-operator-only"] = True
        return out

    def _rule_schema(self, rule: KeyRule, patch: bool) -> dict[str, Any]:
        """One declared key. A required or derived key has no null branch on a patch: validate() refuses its removal
        (missing_required_key, derived_key)."""
        out: dict[str, Any] = {"type": "string"}
        if rule.derived:
            # Validation 9.4: readOnly is "managed exclusively by the owning authority". The same value is accepted
            # (_governed), so the key stays in properties and out of required, with no const: it depends on the target.
            out["readOnly"] = True
            if rule.kind == "label":
                out.update(pattern=_LABEL_VALUE, maxLength=63)
        else:
            regex = value_regex(rule, self.email_domains)
            if rule.kind == "label":
                if regex is not None:
                    out["pattern"] = regex
                    # _syntax checks the label value first; one schema object holds one pattern, so the second is in
                    # allOf. Its "type" keeps openapi-typescript at string (measured in design B, #328).
                    out["allOf"] = [{"type": "string", "pattern": _LABEL_VALUE}]
                elif rule.enum is None:
                    out["pattern"] = _LABEL_VALUE   # an enum's values are label values, checked at load (_add)
                out["maxLength"] = 63
            elif regex is not None:
                out["pattern"] = regex
            if rule.enum is not None:
                out["enum"] = list(rule.enum)
            if rule.required:
                out["minLength"] = 1                # an empty value is a missing key (validate)
        words = [rule.description] if rule.description else []
        words.append(rule.text(self.email_domains))
        if rule.derived:
            words.append("a request may send the same value, never another")
        out["description"] = " ".join(w[:1].upper() + w[1:].rstrip(".") + "." for w in words)
        if rule.example is not None and not rule.derived:
            out["examples"] = [rule.example]
        if rule.derived:
            out["x-cmapi-derived-from"] = rule.derived
        if rule.format is not None:
            out["x-cmapi-format"] = rule.format
        if rule.namespace_prefix:
            out["x-cmapi-namespace-prefix"] = True
        return self._nullable(out, patch and not rule.required and not rule.derived)

    def _key_names(self, kind: str, declared: list[str], patch: bool) -> dict[str, Any]:
        """propertyNames: the declared and operator-only keys, or a key that allowOther admits and classify() does not
        refuse first. On create, each key also has Kubernetes' syntax. On a patch it does not: a key that Git holds can
        be removed with null even when its name is not valid now ("/foo" from before #330), and JSON Schema cannot tie
        a key's name to its value, so the patch schema checks the class of a name only."""
        other = "annotation" if kind == "label" else "label"
        globs = self.allow_other[kind].prefixes
        # classify() reads the text before the first "/": "" is a key with no "/" or one that starts with "/". On create
        # the syntax pattern beside this one refuses an empty prefix, a second "/" and an empty name, so the shorter
        # form says the same there.
        rest = "(?:/[^/]*)+" if patch else "/[^/]+"
        team = (["[^/]*", rest] if patch else ["[^/]+"]) if "" in globs else []
        team += [_glob_regex(g, exact=False) + rest for g in globs if g]
        any_of: list[dict[str, Any]] = [{"enum": declared}] if declared else []
        if team:
            pattern = "^(?:" + "|".join(team) + ")$"
            admitted = re.compile(pattern)
            refused = [k for k in dict.fromkeys([*self.system, *(self.adoption_labels if kind == "label" else ()),
                                                 *(k for k in self.rules[other] if k not in self.rules[kind])])
                       if admitted.fullmatch(k)]
            # A reserved prefix is refused before allowOther is read: listed when an allowOther glob can admit one of its
            # prefixes. A glob that matches "" is left out, since classify() never reads a key with no prefix as
            # reserved; leaving one out only lets more keys through.
            reserved = [r for g in self.reserved_prefixes
                        if any(_globs_meet(g, a) for a in globs if a)
                        and (r := _glob_regex(g, exact=True)) is not None and not re.fullmatch(r, "")]
            nots: list[dict[str, Any]] = [{"enum": refused}] if refused else []
            if reserved:
                nots.append({"pattern": "^(?:" + "|".join(reserved) + ")/"})
            branch: dict[str, Any] = {"pattern": pattern}
            if nots:
                branch["not"] = {"anyOf": nots}
            any_of.append(branch)
        names: dict[str, Any] = {} if patch else {"maxLength": _KEY_MAX, "pattern": _KEY, "not": {"pattern": _LONG_PREFIX}}
        names["anyOf"] = any_of or [{"enum": []}]
        return names
