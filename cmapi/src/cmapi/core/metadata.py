"""Label and annotation keys: classes, validation, derived values, merge patch and render order.

One file, cluster-configs/policies/metadata-keys.yaml, decides every key's class, and the same file
feeds the Kyverno bundle, so plan time, CI and admission agree (docs/02, "Labels and annotations"; #215).

    system               set only by the renderer (cluster-id, tier, requested-by, expiry, ...)
    operatorOnly         an operator only, who holds namespaces:protect (cmapi.net/protected, do-not-delete)
    reservedPrefixes     Kubernetes, OpenShift and platform-controller prefixes
    requiredLabels       keys the namespace must carry, each with a rule; a key with value.from is set by cmapi
    requiredAnnotations
    extraLabels          keys: optional keys with a rule; allowOther: any other key under a prefix, within limits
    extraAnnotations
    adoptionLabels       keys read when an existing namespace is adopted (story #26), never sent by a requester
    liveOnlyKeys         keys that only the cluster writes, left out when Git is compared with the live namespace (#481)

The class names that the approval rules read (keyClasses) are unchanged: a key of a required or extra stanza is
"governed", and a key that allowOther admits is "team".

Every value regex is one string that each reader reads alike: RE2 in the validator here (value_matches, #348) and in the
rendered Kyverno policies (CEL matches(), core/policygen.py), and ECMA-262 or Python re in each client of the API document
(JSON Schema pattern, #328). value_regex() builds it; the loader refuses a configured pattern outside the subset that
these read alike (#332).
"""
from __future__ import annotations

import difflib
import functools
import re
import warnings
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping

import re2
import yaml

from cmapi.core.errors import Problem

# Kubernetes' key and label-value syntax (IsLabelKey, IsValidLabelValue), as text so that the API document's schema
# (json_schema, #328) reads the strings that the validator compiles.
_DNS1123_SUB_TEXT = r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*"
_NAME_TEXT = r"[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?"
_DNS1123_SUB = re.compile(f"^{_DNS1123_SUB_TEXT}$")
_NAME = re.compile(f"^{_NAME_TEXT}$")
# A mail domain: DNS labels of 1 to 63 letters, digits and "-" (RFC 1035, 2.3.4), as the chart's values.schema.json says
# (#335). The 63 is also the label limit of HTML's "valid e-mail address", which the portal's <input type=email> checks
# (#336): a longer label would make the browser refuse every address that cmapi accepts in that domain.
_DOMAIN = re.compile(r"^[A-Za-z0-9](?:[-A-Za-z0-9]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[-A-Za-z0-9]{0,61}[A-Za-z0-9])?)*$")

KeyClass = str   # "system" | "operatorOnly" | "reserved" | "governed" | "team" | "disallowed"
KINDS = ("label", "annotation")
# What cmapi can fill a key from. Each comes from the request's own target, never from the requester's text.
DERIVED_FROM = ("namespace", "environment", "cluster", "instance")
FORMATS = ("email-in-domains", "url")
_RULE_FIELDS = {"value", "pattern", "enum", "format", "namespacePrefix", "namespaceSuffix", "default", "title",
                "description", "example"}
_OLD_STANZAS = ("governed", "team")
# The label and the annotation that cmapi writes for expiresAt (core/render/manifests.py), and nothing else writes.
EXPIRY_KEYS = ("cmapi.net/expiry", "cmapi.net/expires-at")
# The stanzas of the file (#338): a list of text, or a mapping. Any other top-level key stops the start, so a misspelt
# stanza (requiredLabel) cannot load as a file with no rule in it.
_LIST_STANZAS = ("system", "operatorOnly", "reservedPrefixes", "sensitiveKeys", "emailDomains", "liveOnlyKeys")
_MAP_STANZAS = ("requiredLabels", "requiredAnnotations", "extraLabels", "extraAnnotations", "adoptionLabels")
# The keys that the cluster or its controllers write on a live namespace and Git never holds, when the file has no
# liveOnlyKeys: the comparison of Git with the cluster leaves them out (#481, design section 4.2). Each is an fnmatch glob.
DEFAULT_LIVE_ONLY_KEYS = ("kubernetes.io/metadata.name", "openshift.io/*", "argocd.argoproj.io/*",
                          "app.kubernetes.io/instance")
# The classes whose keys a request may name, or cmapi fills in: a change's metadataDiff and the drift of a live namespace
# are about these. A system key is the renderer's own, and a reserved or disallowed one stays as Git holds it.
NAMED_CLASSES = ("governed", "team", "operatorOnly")
# The reason that a person sees for how a key may change on an existing namespace (x-cmapi-edit, #481 design section 3).
EDIT_REASONS = {
    "system": "Managed by cmapi.",
    "expiry": "Change it with Extend, Set expiry or Make permanent.",
    "reserved": "Reserved for the platform.",
    "adoption": "Marks how the namespace was first made.",
    "disallowed": "Not allowed by this instance's rules.",
    "operatorOnly": "Needs namespaces:protect in the namespace's environment.",
    "namespace": "Copied from the namespace name.",
    "environment": "Copied from the cluster's environment.",
    "cluster": "Copied from the cluster's ID.",
    "instance": "Copied from the instance's name.",
    "name": "Part of the namespace's fixed name.",
    "required": "Required on every namespace.",
    "sensitive": "Changing this key needs one more approval.",
}


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


# The validator matches with RE2 (google-re2, RE2's own binding), not Python re (#348). A value is the requester's text and
# a pattern is the operator's; re backtracks, so a pattern of the subset such as (a+)+b takes time exponential in the value
# (seconds at 25 characters), and so do overlapping alternations and adjacent quantifiers that no load-time check can
# list. RE2's time is linear in the value whatever the pattern, and it is the engine that Kyverno's CEL matches() runs.
# The decision and its measurements: docs/reviews/2026-11-17-issue-348/README.md.
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False         # a pattern that RE2 refuses is a problem of the file, not a line on stderr


@functools.lru_cache(maxsize=None)      # keyed by the regexes of the loaded files, so bounded by their keys
def _linear(regex: str) -> Any:
    """The regex compiled by RE2. Raises re2.error when RE2 refuses it (the loader turns that into a problem)."""
    return re2.compile(regex, options=_RE2_OPTIONS)


def _re2_reason(exc: Exception) -> str:
    """RE2's own reason for refusing a regex: google-re2 raises it as bytes."""
    return exc.args[0].decode() if exc.args and isinstance(exc.args[0], bytes) else str(exc)


def value_matches(regex: str, value: str) -> bool:
    """value is a whole match of regex, in time linear in the value (#348). A value with a lone surrogate never
    matches: RE2 reads UTF-8, which cannot hold one, and neither can a Kubernetes string, which Go's JSON decoder would
    turn into U+FFFD, so the cluster would hold another value than the one checked."""
    matcher = _linear(regex)
    try:
        return matcher.fullmatch(value) is not None
    except UnicodeEncodeError:
        return False


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
    namespace_suffix: bool = False      # the namespace name must end with "-<value>" (#479)
    default_from: str | None = None     # a key of the same kind whose value fills this one when it is not sent (#479)
    title: str | None = None            # a short label for a form (JSON Schema title, #336); the key when absent
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
            parts.append("the namespace name starts with this value and '-'")
        if self.namespace_suffix:
            parts.append("the namespace name ends with '-' and this value")
        return "; ".join(parts) or "any value"


@dataclass(frozen=True)
class AllowOther:
    """The keys of one kind that no stanza declares: under one of the prefixes, within the limits."""
    prefixes: tuple[str, ...]
    max: int
    max_value_bytes: int | None = None
    max_bytes_total: int | None = None
    example: Mapping[str, str] = field(default_factory=dict)   # extra keys that the API document's examples show (#479)


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
        for key in EXPIRY_KEYS:
            # Only expiresAt writes them (rule 7 of #479), so a file that leaves them out of system cannot let a request.
            if key not in self.system:
                self.system.append(key)
        self.operator_only = self._texts(raw, "operatorOnly", problems)
        self.reserved_prefixes = [p.rstrip("/") for p in self._texts(raw, "reservedPrefixes", problems)]
        self.sensitive = set(self._texts(raw, "sensitiveKeys", problems))
        self.live_only = self._texts(raw, "liveOnlyKeys", problems) if "liveOnlyKeys" in raw else list(DEFAULT_LIVE_ONLY_KEYS)
        domains = self._texts(raw, "emailDomains", problems)
        bad = [d for d in domains if len(d) > 253 or not _DOMAIN.fullmatch(d)]
        if bad:
            problems.append(f"emailDomains: {bad} are not domain names (labels of 1 to 63 letters, digits and -, joined by .)")
        self.email_domains = [d.lower() for d in domains]
        if self.email_domains and not bad:
            # The address regex joins every domain, so its size is the file's: compiled here in the validator's engine
            # (#348), or RE2's memory budget would refuse it on the first value of an email-in-domains key (a 500) or in
            # the example check of _add below. The file stops here, as one with a pattern that RE2 refuses does.
            try:
                _linear(value_regex(KeyRule(kind="annotation", required=False, format="email-in-domains"),
                                    self.email_domains))
            except re2.error as exc:
                problems.append(f"emailDomains: the {len(domains)} domains make an address regex that does not compile "
                                f"in RE2, the validator's engine: {_re2_reason(exc)}")
                raise ValueError("invalid metadata-keys.yaml: " + "; ".join(problems)) from None
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
        self._check_name_keys(problems)
        self._check_defaults(problems)
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
        self._check_other_examples(problems)
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
        for name, want in (("title", str), ("description", str), ("example", str), ("namespacePrefix", bool),
                           ("namespaceSuffix", bool)):
            if spec.get(name) is not None and not isinstance(spec[name], want):
                problems.append(f"{where}: {name} must be {'text' if want is str else 'true or false'}, "
                                f"not {_kind_of(spec[name])}")
        title = spec.get("title")
        if isinstance(title, str) and not title.strip():
            # A form labels the field with it (#336): an empty label would leave the field with no name.
            problems.append(f"{where}: title must be a non-empty text; leave it out to label the field with the key")
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
        default_from = self._default_from(where, spec, problems)
        if derived and (pattern is not None or enum is not None or fmt is not None or spec.get("namespacePrefix")
                        or default_from is not None):
            problems.append(f"{where}: a key with value.from takes no pattern, enum, format, namespacePrefix or default")
        if sum(x is not None for x in (pattern, enum, fmt)) > 1:
            problems.append(f"{where}: give one of pattern, enum and format")
        if spec.get("namespacePrefix") and spec.get("namespaceSuffix"):
            problems.append(f"{where}: a key starts the namespace name or ends it, not both (namespacePrefix, namespaceSuffix)")
        example = spec.get("example")
        rule = KeyRule(kind=kind, required=required, derived=derived, pattern=pattern,
                       enum=tuple(enum) if enum is not None else None, format=fmt,
                       namespace_prefix=bool(spec.get("namespacePrefix")),
                       namespace_suffix=bool(spec.get("namespaceSuffix")), default_from=default_from,
                       title=title if isinstance(title, str) else None,
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
    def _default_from(where: str, spec: Mapping[str, Any], problems: list[str]) -> str | None:
        """default: {from: <key>}, the key whose value fills this one when a create does not send it (#479)."""
        if "default" not in spec:
            return None
        value = spec["default"]
        if not isinstance(value, Mapping) or set(value) != {"from"} or not isinstance(value["from"], str):
            problems.append(f"{where}: default must be {{from: <key>}}, not {_kind_of(value)}")
            return None
        return value["from"]

    def _check_name_keys(self, problems: list[str]) -> None:
        """At most one key starts the namespace name and one ends it: the name has one start and one end (#479)."""
        prefixes = [f"{kind} {key}" for kind in KINDS for key, rule in self.rules[kind].items() if rule.namespace_prefix]
        suffixes = [f"{kind} {key}" for kind in KINDS for key, rule in self.rules[kind].items() if rule.namespace_suffix]
        for name, marked in (("namespacePrefix", prefixes), ("namespaceSuffix", suffixes)):
            if len(marked) > 1:
                problems.append(f"{name}: only one key may have it, not {marked}")

    def _check_defaults(self, problems: list[str]) -> None:
        """Each default: {from: K} names a declared key of the same kind that has no default itself, so a value is copied
        once and never through a chain (#479). K may be a filled-in key: step 1 fills it before step 2 copies it."""
        for kind in KINDS:
            other = "annotation" if kind == "label" else "label"
            for key, rule in self.rules[kind].items():
                source = rule.default_from
                if source is None:
                    continue
                where = f"the {kind} {key}: default.from {source}"
                target = self.rules[kind].get(source)
                if target is None:
                    reason = f"is {'an' if other == 'annotation' else 'a'} {other}, not a {kind}" \
                        if source in self.rules[other] else "is not a declared key"
                    problems.append(f"{where} {reason}")
                elif target.default_from is not None:
                    problems.append(f"{where} has a default itself; a default is copied once, never through a chain")

    def _check_other_examples(self, problems: list[str]) -> None:
        """Each allowOther.example is an extra key that a request may send: one that allowOther admits, with a valid
        value, within the limits. The API document puts it in the create example (#479)."""
        for kind, stanza in (("label", "extraLabels"), ("annotation", "extraAnnotations")):
            other = self.allow_other[kind]
            for key, value in other.example.items():
                where = f"{stanza}.allowOther.example.{key}"
                if self._syntax(key, value, kind) is not None:
                    problems.append(f"{where}: not a valid {kind} key and value")
                elif self.classify(key, kind) != "team" or any(key in self.rules[k] for k in KINDS):
                    problems.append(f"{where}: not a key that allowOther admits (its prefixes are {list(other.prefixes)})")
            if len(other.example) > other.max:
                problems.append(f"{stanza}.allowOther.example: more keys than max ({other.max})")
            if kind == "annotation":
                sizes = [len(v.encode()) for v in other.example.values()]
                if any(n > (other.max_value_bytes or 0) for n in sizes) or sum(sizes) > (other.max_bytes_total or 0):
                    problems.append(f"{stanza}.allowOther.example: values over maxValueBytes or maxBytesTotal")

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
        try:
            # The validator's engine (#348). Each construct of the subset compiles in it; what it refuses is a pattern
            # whose program exceeds RE2's memory budget (8 MiB by default), such as a hundred [^a]{1000} in a row.
            _linear(anchored(pattern))
        except re2.error as exc:
            problems.append(f"{where}: pattern {pattern!r} does not compile in RE2, the validator's engine: "
                            f"{_re2_reason(exc)}")
            return False
        return True

    @staticmethod
    def _allow_other(kind: str, raw: Mapping[str, Any], stanza: str, problems: list[str]) -> AllowOther:
        known = {"prefixes", "max", "example"} | ({"maxValueBytes", "maxBytesTotal"} if kind == "annotation" else set())
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
        example = raw.get("example")
        if example is None:
            example = {}                    # absent, or null: as each stanza reads null (_texts, _mapping)
        if not isinstance(example, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in example.items()):
            problems.append(f"{stanza}.allowOther.example must be a mapping of keys to text values")
            example = {}
        return AllowOther(prefixes=tuple(p.rstrip("/") for p in prefixes), max=limits["max"],
                          max_value_bytes=limits.get("maxValueBytes"), max_bytes_total=limits.get("maxBytesTotal"),
                          example=dict(example))

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

    # ---- how a key may change on an existing namespace (#481, design section 3)
    def edit_rule(self, kind: str, key: str) -> dict[str, Any]:
        """x-cmapi-edit of one key: its mode (fixed, automatic, required or optional), the reason a person sees, and
        whether a change of it adds one approval (sensitiveKeys). The same for a create's form and a change's."""
        mode, reason = self._edit_mode(kind, key)
        sensitive = key in self.sensitive
        if sensitive:
            reason = " ".join(r for r in (reason, EDIT_REASONS["sensitive"]) if r)
        return {"mode": mode, "reason": reason, "sensitive": sensitive}

    def _edit_mode(self, kind: str, key: str) -> tuple[str, str | None]:
        """The design's order, first match wins: system, reserved or adoption or not allowed, operator-only, filled in by
        cmapi (value.from), part of the name (namespacePrefix, namespaceSuffix), required, then optional."""
        cls = self.classify(key, kind)
        if cls == "system":
            return "fixed", EDIT_REASONS["expiry" if key in EXPIRY_KEYS else "system"]
        if cls in ("reserved", "disallowed"):
            adoption = kind == "label" and key in self.adoption_labels
            return "fixed", EDIT_REASONS["adoption" if adoption else cls]
        if cls == "operatorOnly":
            return "optional", EDIT_REASONS["operatorOnly"]
        rule = self.rules[kind].get(key)
        if rule is None:                    # a key that allowOther admits
            return "optional", None
        if rule.derived:
            return "automatic", EDIT_REASONS[rule.derived]
        if rule.namespace_prefix or rule.namespace_suffix:
            return "fixed", EDIT_REASONS["name"]
        if rule.required:
            return "required", EDIT_REASONS["required"]
        return "optional", None

    def mnemonic(self, labels: Mapping[str, str], annotations: Mapping[str, str]) -> str | None:
        """The value of the key that starts the namespace name (namespacePrefix), whatever the company calls it."""
        found = self.prefix_key()
        if found is None:
            return None
        kind, key = found
        return (labels if kind == "label" else annotations).get(key)

    # ---- Git against the live namespace (#481, design section 4.2)
    def is_live_only(self, key: str) -> bool:
        """A key that the cluster or a controller writes on the live namespace, never Git (liveOnlyKeys)."""
        return any(fnmatchcase(key, glob) for glob in self.live_only)

    def drifted_keys(self, git: Mapping[str, Mapping[str, str]], live: Mapping[str, Mapping[str, str]]) -> list[dict[str, Any]]:
        """Each governed, extra or operator-only key whose value differs between Git and the live namespace, by kind
        then key. A value absent on one side is null there."""
        out: list[dict[str, Any]] = []
        for kind in KINDS:
            for key in sorted(set(git[kind]) | set(live[kind])):
                if self.classify(key, kind) not in NAMED_CLASSES or self.is_live_only(key):
                    continue
                if git[kind].get(key) != live[kind].get(key):
                    out.append({"kind": kind, "key": key, "git": git[kind].get(key), "live": live[kind].get(key)})
        return out

    # ---- derived values
    def derived(self, sources: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """(labels, annotations) that cmapi sets, from the request's target: {"namespace": ..., "environment": ...}."""
        out: dict[str, dict[str, str]] = {"label": {}, "annotation": {}}
        for kind in KINDS:
            for key, rule in self.rules[kind].items():
                if rule.derived and sources.get(rule.derived):
                    out[kind][key] = sources[rule.derived]
        return out["label"], out["annotation"]

    # ---- the keys that the namespace name is made of (#479)
    def prefix_key(self) -> tuple[str, str] | None:
        """(kind, key) of the key with namespacePrefix: the name starts with its value and "-". The loader allows one."""
        for kind in KINDS:
            for key, rule in self.rules[kind].items():
                if rule.namespace_prefix:
                    return kind, key
        return None

    def suffix_key(self) -> tuple[str, str] | None:
        """(kind, key) of the key with namespaceSuffix: the name ends with "-" and its value. The loader allows one."""
        for kind in KINDS:
            for key, rule in self.rules[kind].items():
                if rule.namespace_suffix:
                    return kind, key
        return None

    # ---- steps 1 and 2 of a create: what cmapi fills in before it checks (#479)
    def filled(self, labels: Mapping[str, str | None], annotations: Mapping[str, str | None],
               sources: Mapping[str, str]) -> dict[str, dict[str, str | None]]:
        """{kind: map}: the request's maps with each filled-in key (value.from) and then each default (default.from)
        that the request leaves out. A key that the request sends keeps its value, so a wrong one is still refused."""
        out = {}
        for kind, items in (("label", labels), ("annotation", annotations)):
            out[kind] = self._fill_defaults(kind, self._fill_derived(kind, items, sources))
        return out

    def _fill_derived(self, kind: str, items: Mapping[str, str | None], sources: Mapping[str, str]) -> dict[str, str | None]:
        """Step 1: each value.from key that is not sent, from the request's target (namespace, environment, ...)."""
        out = dict(items)
        for key, rule in self.rules[kind].items():
            if rule.derived and key not in out and sources.get(rule.derived):
                out[key] = sources[rule.derived]
        return out

    def _fill_defaults(self, kind: str, items: Mapping[str, str | None]) -> dict[str, str | None]:
        """Step 2: each default.from key that is not sent, from the value of its source key (the loader forbids chains)."""
        out = dict(items)
        for key, rule in self.rules[kind].items():
            if rule.default_from and key not in out and out.get(rule.default_from):
                out[key] = out[rule.default_from]
        return out

    def value_sources(self, labels: Mapping[str, str | None], annotations: Mapping[str, str | None],
                      filled: Mapping[str, Mapping[str, str | None]]) -> dict[str, dict[str, dict[str, str]]]:
        """{kind: {key: {value, source}}} of a create's filled maps, for the dry run (#479, A7). source is request, the
        value.from target (namespace, environment, cluster, instance), or default:<key>."""
        out: dict[str, dict[str, dict[str, str]]] = {}
        for kind, sent in (("label", labels), ("annotation", annotations)):
            out[kind] = {}
            for key, value in self.ordered({k: v for k, v in filled[kind].items() if v is not None}).items():
                if key in sent:
                    source = "request"
                elif self.rules[kind][key].derived:          # only a declared key is filled in
                    source = self.rules[kind][key].derived
                else:
                    source = f"default:{self.rules[kind][key].default_from}"
                out[kind][key] = {"value": value, "source": source}
        return out

    # ---- validation of what a caller sends (never the renderer's own system keys)
    def validate(self, labels: Mapping[str, str | None], annotations: Mapping[str, str | None], *,
                 operator: bool, require_governed: bool = True,
                 current_labels: Mapping[str, str] | None = None,
                 current_annotations: Mapping[str, str] | None = None,
                 sources: Mapping[str, str] | None = None, existing: bool = False,
                 create: bool = False) -> list[dict[str, Any]]:
        """labels/annotations: what the caller sends (a merge patch; None removes a key). The steps, in order (#479):

            1, 2  on a create: fill each filled-in key, then each default, that the request leaves out (filled)
            3     the namespace name starts with the value of the namespacePrefix key and "-" (_check_prefix); on a
                  change of an existing namespace, the keys that the name is made of keep what Git holds instead
                  (_check_name_keys_kept)
            4     on a create: the namespace name ends with "-" and the value of the namespaceSuffix key (_check_suffix),
                  with a desired name between the two ends (_check_desired_name)
            5     each key sent: its syntax, its class and its rule (_check_sent_keys); each required key (_check_required)
            6     the extra keys of allowOther: their count and bytes (_check_other_keys)

        Classes and values are checked on what is sent; required keys and limits on the result, so a PATCH can neither
        remove a required key nor slip past the caps. sources: the request's target (namespace, environment, cluster,
        instance), from which cmapi fills each value.from key.

        existing: the namespace is in Git already. Then a required key that its current version lacks, and that the
        request does not touch, is held: not refused, as the rendered policies hold it (the owner's decision on #26: a
        missing required key is never forced, only reported). A request that sends the key must give a valid value."""
        sources = sources or {}
        sent = {"label": dict(labels), "annotation": dict(annotations)}
        if create:
            sent = self.filled(labels, annotations, sources)
        current = {"label": current_labels or {}, "annotation": current_annotations or {}}
        merged = {kind: self.merge_patch(current[kind], sent[kind]) for kind in KINDS}
        if existing and not create:
            # A change cannot rename, so it is not refused for a name made before the rule (#481, design section 3).
            errs = self._check_name_keys_kept(sent, current, sources)
        else:
            errs = self._check_prefix(sent, current, sources)
        if create:
            # A name is chosen once, at create.
            errs += self._check_suffix(sent, sources)
            if not errs:
                errs += self._check_desired_name(sent, sources)
        errs += self._check_sent_keys(sent, current, operator, sources)
        if require_governed:
            errs += self._check_required(sent, current, merged, existing, errs)
        errs += self._check_other_keys(merged)
        if create:
            errs = self._without_copied_faults(errs, {"label": labels, "annotation": annotations}, sent)
        return errs

    def _without_copied_faults(self, errs: list[dict[str, Any]], request: Mapping[str, Mapping[str, str | None]],
                               sent: Mapping[str, Mapping[str, str | None]]) -> list[dict[str, Any]]:
        """One fault, one error: step 2 copies a default from its source key, so a refused source value would be refused
        again on a key that the request never sent (mnemonic ABC, then team ABC). The source's error stays and the copy's
        goes. A key that got no copy (an empty source) keeps its missing_required_key."""
        refused = {(e.get("kind"), e.get("key")) for e in errs}
        kept = []
        for e in errs:
            kind, key = e.get("kind"), e.get("key")
            rule = self.rules[kind].get(key) if kind in self.rules else None
            copied = rule is not None and rule.default_from is not None and key not in request[kind] \
                and bool(sent[kind].get(key))
            if not (copied and (kind, rule.default_from) in refused):
                kept.append(e)
        return kept

    def _breaks_own_rule(self, key: str, value: str, kind: str, sources: Mapping[str, str]) -> bool:
        """The value breaks its key's syntax or rule. Step 5 reports that, so the name checks skip it: one error per key."""
        return self._syntax(key, value, kind) is not None or bool(self._governed(key, value, kind, sources))

    @staticmethod
    def _is_echo(kind: str, key: str, sent: Mapping[str, Mapping[str, str | None]],
                 current: Mapping[str, Mapping[str, str]]) -> bool:
        """The request sends back the value that Git holds (FB1 of #488): a client that returns what it read is not refused
        for a key that it may not change. The rendered policy (_same) and the plan-time check (_held) pass it too."""
        value = sent[kind].get(key)
        return value is not None and value == current[kind].get(key)

    def _check_name_keys_kept(self, sent: Mapping[str, Mapping[str, str | None]], current: Mapping[str, Mapping[str, str]],
                              sources: Mapping[str, str]) -> list[dict[str, Any]]:
        """Steps 3 and 4 of a change: the namespacePrefix and namespaceSuffix keys are fixed, since a change cannot rename.
        Sending back Git's value is accepted; another value, or a removal, is refused on that key. A filled-in key is
        checked against its source at step 5 (derived_key), and so is a value that breaks the key's own rule."""
        errs: list[dict[str, Any]] = []
        for found in (self.prefix_key(), self.suffix_key()):
            if found is None:
                continue
            kind, key = found
            if key not in sent[kind] or self.rules[kind][key].derived or self._is_echo(kind, key, sent, current):
                continue
            value, held = sent[kind][key], current[kind].get(key)
            if value is not None and self._breaks_own_rule(key, value, kind, sources):
                continue
            keeps = f"a change keeps {held!r}" if held else "a change cannot add it; adoption does (story #26)"
            errs.append({"code": "invalid_value", "key": key, "kind": kind,
                         "detail": f"{EDIT_REASONS['name'].rstrip('.').lower()}: {keeps}"})
        return errs

    def _check_prefix(self, sent: Mapping[str, Mapping[str, str | None]], current: Mapping[str, Mapping[str, str]],
                      sources: Mapping[str, str]) -> list[dict[str, Any]]:
        """Step 3: the namespace name starts with "<value>-" of the namespacePrefix key, when the request sends it."""
        found, namespace = self.prefix_key(), sources.get("namespace")
        if found is None or not namespace:
            return []
        kind, key = found
        value = sent[kind].get(key)
        if self._is_echo(kind, key, sent, current):
            return []
        # An empty value is a missing key, which step 5 reports.
        if not value or self._breaks_own_rule(key, value, kind, sources) or namespace.startswith(f"{value}-"):
            return []
        return [{"code": "invalid_value", "key": key, "kind": kind, "detail": f"{namespace} does not start with {value}-"}]

    def _check_suffix(self, sent: Mapping[str, Mapping[str, str | None]], sources: Mapping[str, str]) -> list[dict[str, Any]]:
        """Step 4: the namespace name ends with "-<value>" of the namespaceSuffix key (the cluster's environment, filled
        in at step 1), when the request has it. The refusal is on that key, as the prefix's is on its key (#479, A9)."""
        found, namespace = self.suffix_key(), sources.get("namespace")
        if found is None or not namespace:
            return []
        kind, key = found
        value = sent[kind].get(key)
        if not value or self._breaks_own_rule(key, value, kind, sources) or namespace.endswith(f"-{value}"):
            return []
        return [{"code": "invalid_value", "key": key, "kind": kind, "detail": f"{namespace} does not end with -{value}"}]

    def _check_desired_name(self, sent: Mapping[str, Mapping[str, str | None]],
                            sources: Mapping[str, str]) -> list[dict[str, Any]]:
        """Step 4, after both ends passed: the name has a desired name between "<prefix>-" and "-<suffix>", so abc-dev
        and abc--dev are refused for abc and dev (rule 1 of #479). The refusal is on the suffix key, as the end's is."""
        prefix, suffix, namespace = self.prefix_key(), self.suffix_key(), sources.get("namespace")
        if prefix is None or suffix is None or not namespace:
            return []
        start, end = sent[prefix[0]].get(prefix[1]), sent[suffix[0]].get(suffix[1])
        if not start or not end or not namespace.startswith(f"{start}-") or not namespace.endswith(f"-{end}"):
            return []                       # an end that steps 3 and 4 refused or skipped has its own error
        if self._breaks_own_rule(prefix[1], start, prefix[0], sources) or \
                self._breaks_own_rule(suffix[1], end, suffix[0], sources):
            return []                       # step 5 refuses that value on its key: no name error is built on it
        if len(namespace) > len(start) + len(end) + 2:
            return []
        return [{"code": "invalid_value", "key": suffix[1], "kind": suffix[0],
                 "detail": f"{namespace} has no desired name between {start}- and -{end}"}]

    def _check_sent_keys(self, sent: Mapping[str, Mapping[str, str | None]], current: Mapping[str, Mapping[str, str]],
                         operator: bool, sources: Mapping[str, str]) -> list[dict[str, Any]]:
        """Step 5: each key that the request sends, by its syntax, its class and the rule of its stanza."""
        errs: list[dict[str, Any]] = []
        for kind in KINDS:
            other = "annotation" if kind == "label" else "label"
            for key, value in sent[kind].items():
                rule = self.rules[kind].get(key)
                if rule is not None and rule.derived and self._is_echo(kind, key, sent, current):
                    continue                    # a filled-in key sent back as Git holds it changes nothing (#481)
                # Removing a key that the namespace holds writes nothing, so its syntax is not checked: a key that Git
                # holds from before #330 ("/foo") can be removed, though no request may set it now.
                e = None if value is None and key in current[kind] else self._syntax(key, value, kind)
                if e:
                    errs.append(e)
                    continue
                cls = self.classify(key, kind)
                # A key declared for the other kind only (#234: the company's contact and wiki keys are annotations)
                # is refused here even when allowOther admits its prefix, or it would pass as a team key.
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
        return errs

    def _check_required(self, sent: Mapping[str, Mapping[str, str | None]], current: Mapping[str, Mapping[str, str]],
                        merged: Mapping[str, Mapping[str, str]], existing: bool,
                        reported: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Step 5: each required key that the result lacks. A filled-in key is cmapi's to set, so it is never missing. A
        key that an earlier step refused already has its error (an empty mnemonic that breaks its pattern): one per key."""
        refused = {(e.get("kind"), e.get("key")) for e in reported}
        errs: list[dict[str, Any]] = []
        for kind in KINDS:
            for key, rule in self.rules[kind].items():
                if not rule.required or rule.derived or merged[kind].get(key) or (kind, key) in refused:
                    continue
                if existing and key not in sent[kind] and not current[kind].get(key):
                    continue                        # held: the namespace lacked it before, and the request leaves it
                errs.append({"code": "missing_required_key", "key": key, "kind": kind,
                             "detail": rule.text(self.email_domains)})
        return errs

    def _check_other_keys(self, merged: Mapping[str, Mapping[str, str]]) -> list[dict[str, Any]]:
        """Step 6: the extra keys of each kind (class team) within allowOther's count and, for annotations, bytes.
        A value that the request does not send is the current one, which Git holds: it is not checked again (the same
        rule as the bounds of tiers.py and the rendered policies). Each value that the request sends is checked above."""
        errs: list[dict[str, Any]] = []
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
            return {"code": "invalid_value", "key": key, "kind": kind, "detail": "not a valid label value"}
        return None

    def _governed(self, key: str, value: str | None, kind: str, sources: Mapping[str, str]) -> list[dict[str, Any]]:
        # Each refusal of a value names its kind, as missing_required_key and derived_key do: a key can be a label and an
        # annotation, each with its own rule, and a client puts the refusal on the field of that kind (#336).
        rule = self.rules[kind].get(key)
        if rule is None:
            other = "annotation" if kind == "label" else "label"
            return [{"code": "invalid_key", "key": key, "kind": kind, "detail": f"{key} is a {other}"}]
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
        if regex is not None and not value_matches(regex, value):
            if rule.format == "email-in-domains":
                code = "invalid-team-dl" if key == "cmapi.net/team-dl" else "invalid_value"
                return [{"code": code, "key": key, "kind": kind, "detail": f"not an address in {self.email_domains}"}]
            detail = f"must match {rule.pattern}" if rule.pattern is not None else rule.text(self.email_domains)
            return [{"code": "invalid_value", "key": key, "kind": kind, "detail": detail}]
        if rule.enum is not None and value not in rule.enum:
            return [{"code": "invalid_value", "key": key, "kind": kind, "detail": f"one of {list(rule.enum)}"}]
        return []

    def check(self, labels, annotations, *, operator: bool, require_governed: bool = True,
              current_labels=None, current_annotations=None, sources=None, existing: bool = False,
              create: bool = False) -> None:
        errs = self.validate(labels, annotations, operator=operator,
                             require_governed=require_governed, current_labels=current_labels,
                             current_annotations=current_annotations, sources=sources, existing=existing, create=create)
        if any(e["code"] == "operator_only_key" for e in errs):
            raise Problem.forbidden("Only an operator (namespaces:protect) may set " +
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

    def metadata_diff(self, before: Mapping[str, Mapping[str, str]], after: Mapping[str, Mapping[str, str]],
                      sent: Mapping[str, Mapping[str, str | None]]) -> dict[str, dict[str, dict[str, Any]]]:
        """A change's metadataDiff (#481, design section 4.1): {labels, annotations}, each key whose value moves between
        Git (before) and the rendered namespace (after), with its source. Only the keys that a request may name or that
        cmapi fills in (NAMED_CLASSES). before null is an added key, after null a removed one."""
        out: dict[str, dict[str, dict[str, Any]]] = {}
        for kind, field_name in (("label", "labels"), ("annotation", "annotations")):
            out[field_name] = {}
            for key in sorted(set(before[kind]) | set(after[kind])):
                old, new = before[kind].get(key), after[kind].get(key)
                if old == new or self.classify(key, kind) not in NAMED_CLASSES:
                    continue
                out[field_name][key] = {"before": old, "after": new, "source": self._change_source(kind, key, sent)}
        return out

    def _change_source(self, kind: str, key: str, sent: Mapping[str, Mapping[str, str | None]]) -> str:
        """request: the body sent the key. Otherwise the key's value.from target: on a change only the renderer's filled-in
        keys move without being sent."""
        rule = self.rules[kind].get(key)
        if key not in sent[kind] and rule is not None and rule.derived:
            return rule.derived
        return "request"

    def missing_required(self, labels: Mapping[str, str], annotations: Mapping[str, str]) -> list[tuple[str, str]]:
        """(kind, key) of each required key that the namespace lacks, other than a filled-in one. On a change that passed
        validate(), each is held (#234): the namespace lacked it before and the request leaves it out, so the plan reports
        it as a finding that the change can add."""
        maps = {"label": labels, "annotation": annotations}
        return [(kind, key) for kind in KINDS for key, rule in self.rules[kind].items()
                if rule.required and not rule.derived and not maps[kind].get(key)]

    def change_facts(self, before: Mapping[str, str], after: Mapping[str, str],
                     before_annotations: Mapping[str, str] | None = None,
                     after_annotations: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Facts for the approval engine: which classes changed, and whether a sensitive key did.

        before/after are the labels, and the annotations come apart: a key can be both (do-not-delete, any operator-only or
        team key), and one map merged over the other would hide a change in it, such as a protection label removed while an
        annotation of the same key stays (#378)."""
        changed: set[str] = set()
        sensitive: set[str] = set()
        for b, a in ((before, after), (before_annotations or {}, after_annotations or {})):
            moved = {k for k in set(b) | set(a) if b.get(k) != a.get(k)}
            changed |= moved
            # a sensitive key counts when an existing value changes or goes; setting it the first time
            # (every create sets cmapi.net/team) is not a change of ownership
            sensitive |= {k for k in moved & self.sensitive if k in b}
        return {"keyClasses": sorted({self.classify(k) for k in changed}),
                "sensitiveKeyChanged": bool(sensitive)}

    def ordered(self, items: Mapping[str, str]) -> dict[str, str]:
        """Render order: system keys first, then governed, then the rest; each group sorted."""
        rank = {"system": 0, "reserved": 0, "operatorOnly": 0, "governed": 1}
        return dict(sorted(items.items(), key=lambda kv: (rank.get(self.classify(kv[0]), 2), kv[0])))

    # ---- the API document (#328)
    def keys_view(self) -> dict[str, Any]:
        """GET /api/v1/metadata-keys (#336): the JSON Schema of NamespaceCreate's labels and annotations, the same objects
        that the API document holds there (core/docs.py, _document_metadata), without the document's words around them.
        For a client such as the portal, also when /openapi.json is off (docs.enabled: false)."""
        return {"labels": self.json_schema("label", "create"), "annotations": self.json_schema("annotation", "create")}

    def json_schema(self, kind: str, op: str) -> dict[str, Any]:
        """The JSON Schema 2020-12 of the labels (kind=label) or annotations of NamespaceCreate (op=create) or of
        NamespacePatch (op=patch, the object branch of its anyOf with null), from this file, for the API document.

        It documents validate(); it never replaces it. It is sound: each map that validate() accepts passes it
        (tests/core/test_metadata_schema_328.py runs both on one corpus). What JSON Schema cannot say stays loose and is
        said in words: who the caller is (operatorOnly), the request's target (a derived value, namespacePrefix and
        namespaceSuffix), the count of other keys and the sizes in bytes (allowOther), and on a patch the 253 characters of a
        key's prefix. One way it is stricter than validate(), on purpose (#479, A1): a create that leaves out a key that
        cmapi fills in (value.from, default.from) is accepted, and the schema lists that key as required."""
        if kind not in KINDS or op not in _OPS:
            raise ValueError(f"json_schema: kind is one of {KINDS} and op one of {_OPS}, not {kind!r}, {op!r}")
        patch = op == "patch"
        rules, other = self.rules[kind], self.allow_other[kind]
        properties = {key: self._rule_schema(rule, patch) for key, rule in rules.items()}
        for key in self.operator_only:
            properties[key] = self._nullable(self._operator_schema(kind), patch)
        for key, prop in properties.items():
            # How the key may change on an existing namespace (#481), so a form locks a fixed key with its reason.
            prop["x-cmapi-edit"] = self.edit_rule(kind, key)
        extra: dict[str, Any] = {"type": "string"}
        if kind == "label":
            extra.update(pattern=_LABEL_VALUE, maxLength=63)
        elif other.max_value_bytes is not None:
            # A character is one to four bytes in UTF-8, so a bound on bytes is at least this bound on characters.
            extra["maxLength"] = other.max_value_bytes
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        # A filled-in key is required too (#479, A1): a client sends its value or leaves it out, and cmapi fills it in.
        required = [key for key, rule in rules.items() if rule.required]
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
        words = {k: schema.pop(k) for k in ("title", "description", "examples") if k in schema}
        marks = {k: schema.pop(k) for k in list(schema) if k.startswith("x-cmapi-")}
        return {"anyOf": [schema, {"type": "null"}], **words, **marks}

    def _operator_schema(self, kind: str) -> dict[str, Any]:
        out: dict[str, Any] = {"type": "string"}
        if kind == "label":
            out.update(pattern=_LABEL_VALUE, maxLength=63)
        out["description"] = "An operator only (namespaces:protect): another caller gets 403 forbidden."
        out["x-cmapi-operator-only"] = True
        return out

    def _rule_schema(self, rule: KeyRule, patch: bool) -> dict[str, Any]:
        """One declared key. A required or derived key has no null branch on a patch: validate() refuses its removal
        (missing_required_key, derived_key)."""
        out: dict[str, Any] = {"type": "string"}
        if rule.derived:
            # Required and shown, not readOnly (#479, A1): Swagger UI hides a readOnly property of a request body. No const:
            # the value depends on the request's target; another value is refused (derived_key).
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
        if rule.derived:
            # #479 (A1): the key is required and shown, so its words say that a client may leave it out.
            words.append(f"filled in by cmapi from the {rule.derived}; you may leave it out")
            words.append("a request may send the same value, never another")
        else:
            words.append(rule.text(self.email_domains))
        if rule.default_from and not patch:
            # Only a create fills a default (steps 1 and 2 of validate); a PATCH never does.
            words.append(f"default: the value of {rule.default_from}")
        if rule.title is not None:
            out["title"] = rule.title                # Validation 9.1: the short label; the description explains
        out["description"] = " ".join(w[:1].upper() + w[1:].rstrip(".") + "." for w in words)
        # The rule in the validator's own words (the detail of missing_required_key), so that a client such as the portal
        # says what the API says (#336). An annotation: a JSON Schema validator ignores it (Core 2020-12, 6.5).
        out["x-cmapi-rule"] = rule.text(self.email_domains)
        if rule.example is not None and not rule.derived:
            out["examples"] = [rule.example]
        if rule.derived:
            out["x-cmapi-derived-from"] = rule.derived
        if rule.format is not None:
            out["x-cmapi-format"] = rule.format
        if rule.default_from and not patch:
            out["x-cmapi-default-from"] = rule.default_from
        if rule.namespace_prefix:
            out["x-cmapi-namespace-prefix"] = True
        if rule.namespace_suffix:
            out["x-cmapi-namespace-suffix"] = True
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
