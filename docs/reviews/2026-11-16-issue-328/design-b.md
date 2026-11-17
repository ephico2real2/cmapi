# #328 design B: the labels and annotations of a namespace as schema, not prose

Second, independent design (Opus, `high`). Read-only on `cmapi-design` at main `9ba33b2`; no repository edit, no push. Every
number below comes from a command in the scratch folder
`/private/tmp/claude-501/-Users-olasumbo-gitRepos-cmapi-design/f7ded52b-75f6-4c7e-b4dc-532bcd598fb3/scratchpad/design-328-b/`
(`run.sh` re-runs all of it; `run.log` is its output on 2026-11-16). What was measured, what was inferred and what was not
tested is marked in each section.

## 0. The answer in brief

- **Shape.** Each of `labels` and `annotations` becomes an object schema generated from `metadata-keys.yaml`:
  `required` (the required keys that cmapi does not derive), `properties` (one per declared key, plus the `operatorOnly`
  keys), `propertyNames` (Kubernetes qualified-name syntax, and the key classes of `classify()`), and `additionalProperties`
  (the value rule of the `allowOther` keys). `NamespaceCreate.required` gains `labels` and `annotations` when the kind has a
  required key. `NamespacePatch` keeps no `required`, and gives a required or derived key no `null` branch, so a patch can
  never remove one. Derived keys are `readOnly: true`. Every regex is one string that Python `re.fullmatch`, RE2 (Kyverno
  CEL) and ECMA-262 read the same way, produced by one function, `value_regex(rule, domains)`, which the validator, the
  Kyverno renderer and the schema all call.
- **Breaking.** Yes under oasdiff 1.37.0: 14 `ERR` lines (measured). Not a behaviour change: the server refuses every one of
  those requests today with a 422. Pre-1.0, so the 14 lines go into `accepted-breaking.txt` under `#328`; with them the gate
  exits 0 (measured).
- **Drift today.** Three hand-written implementations of each format (Python, CEL, prose), a pattern dialect that is never
  checked, a portal that hard-codes the two CRC keys, and a validator that accepts the label key `/foo`, which Kubernetes
  refuses. All are measured below.
- **Measured effect.** Swagger UI 5.34.1 marks `labels`, `cmapi.net/team`, `annotations` and `cmapi.net/team-dl` required
  (main marks only `namespace`). openapi-typescript 7.13.0 makes them required TypeScript properties, so a client that omits
  them no longer compiles. Spectral now catches a recorded sample that breaks a key's rule. The differential test on the shipped config goes from
  4126 of 5385 cases disagreeing (main's contract) to 202, all of them the `/foo` validator bug, and to 0 with the
  validator changes of 2.3.

## 1. Where each rule is enforced today

| # | Enforcer | File:line | Source of the rule | Drift |
|---|---|---|---|---|
| E1 | Plan-time validator | `cmapi/src/cmapi/core/metadata.py:246-305` (`validate`), `:307-314` (`_syntax`), `:316-345` (`_governed`); called at `core/pipeline.py:208` | `metadata-keys.yaml` via `MetadataKeys` | Source of truth today |
| E2 | Email check | `cmapi/src/cmapi/core/identity/checks.py:26` (`_LOCAL`), `:29-34` (`email_in_domains`), from `metadata.py:331` | `emailDomains` | Re-implemented in CEL (E3) by hand |
| E3 | Kyverno bundle | `cmapi/src/cmapi/core/policygen.py:110-131` (`_value_rule`), `:134-192` (`_metadata_checks`), label syntax `:176-180` | Same `MetadataKeys` | Pattern: same string, wrapped `^(?:p)$` (`:114`). Email: copy of `_LOCAL` (`:119`). URL: a different algorithm (`:124-130`, regex) from Python's (`metadata.py:334-337`, `urlsplit`) |
| E4 | OpenAPI document | `cmapi/src/cmapi/core/docs.py:378-392` (`metadata_description`), `:395-398` (`metadata_example`), `:401-410` (`_document_metadata`), from `build_openapi` `:372-373`; served per instance at `main.py:176-179` with `ctx.cfg.metadata` | Same `MetadataKeys`, but only as prose and one example | The schema is `additionalProperties: {type: string}` (models `core/models.py:236-237`, `:250-251`); nothing machine-readable |
| E5 | Portal form | `cmapi-portal-ui/src/portal/NewNamespaceTab.tsx:145-152` (body), `:200-203` (Team), `:232-235` (Team DL) | Hard-coded `cmapi.net/team` and `cmapi.net/team-dl` | Not from config at all |
| E6 | Portal types | `cmapi-portal-ui/scripts/api-types.mjs:14,26`, from the committed contract | The service suite's config | Generic maps today |
| E7 | Committed contract | `cmapi/contract/openapi.json`, written by `tests/service/test_api_docs.py:372-380` from the test instance whose config is `examples/cluster-configs/policies/metadata-keys.yaml` (`tests/service/conftest.py:386`) | Example config | Equal to CRC, kind, Helm and local today (parsed YAML, measured: all four `True`); only CRC == kind is under test (`tests/service/test_plain_manifests.py:270-271`) |

### Drift, measured

| Finding | Evidence |
|---|---|
| D1. The validator accepts the label key `/foo` (empty prefix). Kubernetes refuses it: `IsLabelKey`, `if len(prefix) == 0 { errs = append(errs, "prefix part "+EmptyError()) }` | `keys.validate({"/foo": "x", "cmapi.net/team": "payments"}, {...}, operator=False)` returned `[]`. Cause: `metadata.py:308-309` takes `prefix, _, name = key.rpartition("/")` and checks the prefix only `if prefix`, then `classify` sees prefix `""` and `allowOther: [""]` admits it as a team key. Kyverno renders no syntax check for team keys, so it reaches Git and the API server refuses the apply |
| D2. URL: Python accepts `"\x01http://x"`, Kyverno refuses it | Python `[]` (no error). `urlsplit` strips leading C0 control characters; CEL `(?i)^https?://` does not. Python on `"http://[x"`: `ValueError: Invalid IPv6 URL`, which `main.py:160-162` turns into 422 `validation-failed`, not the `policy-violation`/`invalid_value` of every other bad value; Kyverno accepts it. *I retract my first hypothesis that this is a 500: the ValueError handler catches it.* |
| D3. The pattern dialect is never checked. A Python-valid pattern loads, then breaks Kyverno or the schema | Loader on main: `^[a-z]+\Z`, `(?i)^[a-z]+$`, `^(?P<t>[a-z]+)$`, `^(?=x)[a-z]+$`, `^([a-z])\1$` all load. RE2 (Go regexp, CEL's dialect): `\Z`, `(?=`, `\1` do not compile. ECMA-262 `u`: `\Z`, `(?i)`, `(?P<` do not compile |
| D4. Character classes differ by engine | Python `\d` matches U+0661 (`True`), ECMA `\d` does not (`false`); Python `.` matches `\r`, ECMA `.` does not. Python `re.search` with `$` matches before a trailing newline (7 of 630 verdicts differed until the Python leg used `fullmatch`) |
| D5. The portal works only on an instance whose required keys are exactly the CRC two | `NewNamespaceTab.tsx:148-149`. On the company profile (`metadata-keys.company.yaml`) the form sends `cmapi.net/team`, which has no allowed prefix there, and omits `company.net/mnemonic`, `lob`, `cl` |
| D6. The schema says nothing | Differential on main's committed schemas: 5385 cases, 1259 agree, 4126 differ, every one "server refuses, schema accepts" (`diff-main.log`) |

So: E1, E3, E4 read one config, but E2 and E3 re-implement the formats by hand and E3/E4 receive Python-dialect patterns
unchecked; E5 reads nothing. They can drift and, measured, they do.

## 2. The design

### 2.1 Principle: one rule, one regex, three readers

Add to `core/metadata.py` one function that turns a key's rule into a regex in the common subset of Python `re`, RE2 and
ECMA-262. The validator matches with it (`re.fullmatch`, `re.ASCII`), the Kyverno renderer passes it to CEL `matches()`, and
the schema puts it in `pattern`. Drift between E1, E3 and E4 is then structurally impossible for pattern and format, and a
test checks that each consumer calls it. The loader refuses a configured `pattern` outside the subset.

Measured: the 18 regexes that the prototype emits for both example configs, on 35 strings (empty, 63/64 characters,
trailing `\n`, U+00A0, U+2028, U+001C, U+0085, U+FEFF, U+0661, `/foo`, reserved prefixes...): ECMA-262 (`u`) 630 verdicts,
0 differ from Python `re.fullmatch`; RE2 (Go 1.27.3 `regexp`) 630 verdicts, 0 differ (`tri/result.txt`). The literal
whitespace class equals `str.isspace()` over all 1,114,112 code points (0 mismatches). It is written with literal
characters, because RE2 reads no `\uXXXX` and ECMA-262 no `\x{..}`.

### 2.2 The generating function

Inputs: the instance's `MetadataKeys` (from `metadata-keys.yaml`: `rules[kind]` with each `KeyRule`, `allow_other[kind]`,
`operator_only`, `system`, `reserved_prefixes`, `adoption_labels`, `email_domains`), the kind (`label`/`annotation`), and
`patch: bool`. Nothing else: no request, no instance name, no environment list. The served document is built once per
process (`main.py:176-179`), so a config change takes effect on restart, as today.

Where: `value_regex`, the constants and the dialect check in `core/metadata.py` (the rule's owner); `metadata_schema` in a new
`core/metadata_schema.py` called by `docs._document_metadata`. The prototype, run for every measurement here
(`proto/metadata_schema.py`), in full:

```python
"""The JSON Schema 2020-12 of a namespace's labels and annotations, from metadata-keys.yaml (#328).

Every regex is written in the subset that Python `re`, RE2 (Kyverno CEL `matches`) and ECMA-262 (JSON Schema `pattern`,
ajv, Swagger UI, the browser) read the same way: no lookaround, no backreference, no inline flag, no \\A/\\Z, no named
group. One function per rule (value_regex) feeds the validator, the Kyverno renderer and the schema.
"""
from __future__ import annotations

import re
from typing import Any

from cmapi.core.metadata import KeyRule, MetadataKeys

# Kubernetes (apimachinery content.IsLabelKey, labels docs): a label value is empty or at most 63 characters of
# [A-Za-z0-9_.-], starting and ending alphanumeric; a key is an optional DNS-1123 subdomain prefix of at most 253 and "/",
# then a name of the same shape, 1 to 63 characters.
NAME = r"[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?"
DNS_SUB = r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*"
LABEL_VALUE = rf"^(?:{NAME})?$"
QUALIFIED_NAME = rf"^(?:{DNS_SUB}/)?{NAME}$"
# Python str.isspace(), written out, as literal characters: RE2 reads no \u escape, ECMA-262 no \x{..}.
SPACE = "\\t-\\r\x1c- \x85\xa0  -     　"
EMAIL_LOCAL = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+"     # core/identity/checks.py _LOCAL


def anchored(pattern: str) -> str:
    """A configured pattern as re.fullmatch reads it, for an engine that searches (ECMA-262, RE2)."""
    return f"^(?:{pattern})$"


def caseless(text: str) -> str:
    """ASCII case-insensitive literal without an inline flag, which ECMA-262 before ES2025 does not read."""
    return "".join(f"[{c.lower()}{c.upper()}]" if c.isascii() and c.isalpha() else re.escape(c) for c in text)


def value_regex(rule: KeyRule, domains: list[str]) -> str | None:
    """The one regex of a declared key's value (pattern or format), or None when the rule has none."""
    if rule.pattern is not None:
        return anchored(rule.pattern)
    if rule.format == "email-in-domains":
        return rf"^{EMAIL_LOCAL}@(?:{'|'.join(caseless(d) for d in domains)})$"
    if rule.format == "url":
        return rf"^{caseless('http')}[sS]?://[^/?#{SPACE}]+(?:[/?#][^{SPACE}]*)?$"
    return None


def glob_regex(glob: str) -> str:
    """fnmatchcase of one prefix glob, as a regex of one key prefix (a prefix holds no '/')."""
    out, i = [], 0
    while i < len(glob):
        c = glob[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[" and "]" in glob[i + 1:]:
            j = glob.index("]", i + 2 if glob[i + 1:i + 2] in ("!", "]") else i + 1)
            body = glob[i + 1:j]
            out.append("[^" + body[1:] + "]" if body.startswith("!") else "[" + body + "]")
            i = j
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def key_names(keys: MetadataKeys, kind: str) -> dict[str, Any]:
    """propertyNames: the keys that validate() admits for this kind, by class (core/metadata.py classify)."""
    other = "annotation" if kind == "label" else "label"
    named = sorted(set(keys.rules[kind]) | set(keys.operator_only))
    prefixed = [glob_regex(p) for p in keys.allow_other[kind].prefixes if p]
    team = [r"[^/]+"] * ("" in keys.allow_other[kind].prefixes) + [rf"{p}/[^/]+" for p in prefixed]
    refused = sorted(set(keys.system) | (set(keys.adoption_labels) if kind == "label" else set())
                     | (set(keys.rules[other]) - set(keys.rules[kind])))
    reserved = [glob_regex(p) for p in keys.reserved_prefixes]
    any_of: list[dict[str, Any]] = [{"enum": named}] if named else []
    if team:
        not_any: list[dict[str, Any]] = [{"enum": refused}] if refused else []
        if reserved:
            not_any.append({"pattern": rf"^(?:{'|'.join(reserved)})/"})
        team_schema: dict[str, Any] = {"pattern": rf"^(?:{'|'.join(team)})$"}
        if not_any:
            team_schema["not"] = {"anyOf": not_any}
        any_of.append(team_schema)
    return {"maxLength": 317, "pattern": QUALIFIED_NAME, "anyOf": any_of or [{"enum": []}]}


def rule_schema(rule: KeyRule, keys: MetadataKeys, *, patch: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "string"}
    if rule.derived:
        out["readOnly"] = True
    regex = value_regex(rule, keys.email_domains)
    if regex is not None:
        out["pattern"] = regex
    if rule.enum is not None:
        out["enum"] = list(rule.enum)
    if rule.required and not rule.derived and regex is None and rule.enum is None:
        out["minLength"] = 1                         # an empty value is a missing key (validate, require_governed)
    if rule.kind == "label":
        out["maxLength"] = 63
        if rule.enum is None:
            # Kubernetes label syntax, checked before the key's rule (an enum is checked against it at load,
            # metadata.py _add). "type" keeps openapi-typescript at `string`.
            out["allOf"] = [{"type": "string", "pattern": LABEL_VALUE}]
    words = [rule.description] if rule.description else []
    words.append(rule.text(keys.email_domains).capitalize() + ".")
    if rule.derived:
        words.append("A request may send the same value, never another.")
    out["description"] = " ".join(w.rstrip(".") + "." for w in words)
    if rule.example is not None and not rule.derived:
        out["examples"] = [str(rule.example)]
    if patch and not rule.required and not rule.derived:
        # null removes an optional key; a required or derived key cannot be removed. anyOf, as FastAPI writes Optional,
        # so oasdiff compares like with like (a type list reads to it as a narrowing).
        return {"anyOf": [out, {"type": "null"}], "description": out.pop("description")}
    return out


def operator_schema(kind: str, patch: bool) -> dict[str, Any]:
    """An operatorOnly key (cmapi.net/protected): any value of the kind's syntax, outside the team limits."""
    out: dict[str, Any] = {"type": "string", "description": "cmapi-operator and above only (operatorOnly)."}
    if kind == "label":
        out.update(maxLength=63, pattern=LABEL_VALUE)
    return {"anyOf": [out, {"type": "null"}], "description": out.pop("description")} if patch else out


def metadata_schema(keys: MetadataKeys, kind: str, *, patch: bool) -> dict[str, Any]:
    """The labels (kind=label) or annotations of NamespaceCreate (patch=False) or NamespacePatch (patch=True)."""
    rules = keys.rules[kind]
    other = keys.allow_other[kind]
    extra: dict[str, Any] = {"type": "string"}
    if kind == "label":
        extra.update(maxLength=63, pattern=LABEL_VALUE)
    elif other.max_value_bytes is not None:
        extra["maxLength"] = other.max_value_bytes   # bytes in UTF-8 on the server; JSON Schema counts characters
    if patch:
        extra = {"anyOf": [extra, {"type": "null"}]}
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {**{k: operator_schema(kind, patch) for k in keys.operator_only},
                       **{k: rule_schema(r, keys, patch=patch) for k, r in rules.items()}},
        "propertyNames": key_names(keys, kind),
        "additionalProperties": extra,
    }
    required = sorted(k for k, r in rules.items() if r.required and not r.derived)
    if required and not patch:
        schema["required"] = required
    return schema
```

`docs._document_metadata` (`docs.py:401-410`) becomes (measured as `proto/build_head.py`):

```python
def _document_metadata(spec: dict[str, Any], keys: Any) -> None:
    """The labels and annotations of NamespaceCreate and NamespacePatch: this instance's keys and rules as schema (#328),
    with the prose description and the example of each kept for people."""
    schemas = spec.get("components", {}).get("schemas", {})
    for name, patch, prefix in (("NamespaceCreate", False, ""), ("NamespacePatch", True, "Merge patch; null removes a key. ")):
        model = schemas.get(name) or {}
        props = model.get("properties") or {}
        for field, kind in (("labels", "label"), ("annotations", "annotation")):
            if field not in props:
                continue
            old = props[field]
            new = metadata_schema(keys, kind, patch=patch)
            if patch:
                new = {"anyOf": [new, {"type": "null"}]}
            new.update(title=old.get("title", field.capitalize()), description=prefix + metadata_description(keys, kind))
            new["examples"] = [metadata_example(keys, kind)] if not patch else old.get("examples", [None])
            props[field] = new
            if not patch and new.get("required") and field not in model.setdefault("required", []):
                model["required"].append(field)
```

The schema stays inline under `properties.labels`/`properties.annotations`, not a named component: the Spectral rule
`cmapi-net-keys-only-in-labels` (`contract/spectral/functions/cmapiLabelKeys.js`) allows a `cmapi.net/` key in an example only
when the nearest owner is `labels` or `annotations`, so a component named `NamespaceCreateLabels` would trip it.

### 2.3 The changes to the enforcers (so all three read the one regex)

`core/metadata.py`: `value_regex`, `LABEL_VALUE`, `QUALIFIED_NAME`, `SPACE`, `EMAIL_LOCAL` move here (and
`metadata_schema.py` imports them). In `_add`, after the compile check at `:166-171`, the dialect check:

```python
# A pattern is read by Python here, by RE2 in the rendered Kyverno policies and by ECMA-262 in every client of the API
# document (#328). These constructs are read differently, or not at all, by one of the three (measured on 2026-11-16).
_NOT_PORTABLE = re.compile(r"\(\?(?!:)|\\[AZzbBsSpPNuUkg1-9]|\[:|\*\+|\+\+|\?\+|\}\+")

        pattern = spec.get("pattern")
        if pattern is not None:
            try:
                re.compile(pattern, re.ASCII)
            except re.error as exc:
                problems.append(f"{where}: pattern does not compile: {exc}")
            if _NOT_PORTABLE.search(pattern):
                problems.append(f"{where}: pattern uses a construct that RE2 (Kyverno) or ECMA-262 (the API document) reads "
                                "differently: no (?...) other than (?:...), no backreference, \\A, \\Z, \\b, \\s, \\p, "
                                "POSIX class or possessive quantifier")
```

`_syntax` (`metadata.py:307-314`), fixing D1 (an empty prefix):

```python
    def _syntax(self, key: str, value: str | None, kind: str) -> dict[str, Any] | None:
        if not re.fullmatch(QUALIFIED_NAME, key) or len(key.split("/", 1)[0]) > 253:
            return {"code": "invalid_key", "key": key}
        if kind == "label" and value not in (None, "") and not re.fullmatch(LABEL_VALUE, value):
            return {"code": "invalid_value", "key": key, "detail": "not a valid label value"}
        return None
```

`_governed` (`metadata.py:330-341`): the email and URL branches and the pattern branch become one, with the problem codes kept
(`invalid-team-dl` for that key, `invalid_value` otherwise):

```python
        detail = rule.text(self.email_domains)
        regex = value_regex(rule, self.email_domains)
        if regex is not None and not re.fullmatch(regex, value, re.ASCII):
            code = "invalid-team-dl" if key == "cmapi.net/team-dl" and rule.format == "email-in-domains" else "invalid_value"
            return [{"code": code, "key": key, "detail": detail}]
        if rule.enum is not None and value not in rule.enum:
            return [{"code": "invalid_value", "key": key, "detail": f"one of {list(rule.enum)}"}]
```

`core/policygen.py:110-131` (`_value_rule`) and `:176-180`:

```python
def _value_rule(rule: KeyRule, value: str, domains: list[str]) -> tuple[str, str, str] | None:
    """(rule name, CEL that is true when the value is good, the rule in words): the regex that the validator and the API
    document use too (metadata.value_regex), so the three cannot drift (#328)."""
    regex = value_regex(rule, domains)
    if regex is not None:
        return ("pattern" if rule.pattern is not None else "format", f"{value}.matches({cel(regex)})", rule.text(domains))
    if rule.enum is not None:
        return "enum", f"{value} in {cel(list(rule.enum))}", f"one of {', '.join(rule.enum)}"
    return None
...
            if kind == "label":
                syntax = f"{value}.matches({cel(LABEL_VALUE)})"
                parts.append(f"(!({k} in {m}) || {value} == '' || ({syntax}))")
```

Behaviour that changes, on purpose, and needs its own issue under `fix-defect` (named in section 8): `/foo` is refused
(`invalid_key`); `"\x01http://x"` is refused by Python as Kyverno already refuses it; `"http://[x"` becomes accepted by
Python, as Kyverno already accepts it, instead of 422 `validation-failed`. `email_in_domains` stays for its other caller
(`identity/checks.py`, the requester's address) and gets a test that it agrees with `value_regex` on the corpus.

### 2.4 Each rule, decided

| Question | Decision | Why |
|---|---|---|
| Required keys | `required` inside the map, for required keys without `value.from`; `NamespaceCreate.required` gains the map | JSON Schema `required` inside a map does nothing when the map is absent; `validate` refuses a missing map too (`metadata.py:284-293`) |
| Empty value of a required key | `minLength: 1` when no pattern/enum says more | `validate` treats `""` as missing (`not merged[kind].get(key)`, `:287`) |
| Per-key value | `pattern` = `value_regex`; `enum` as is; `maxLength: 63` for labels | One regex for all readers (2.1) |
| Label syntax on a declared key | `allOf: [{type: string, pattern: LABEL_VALUE}]`, not on an enum key | CRC's own `^[a-z0-9-]{2,40}$` admits `-payments`, which `_syntax` refuses. JSON Schema has one `pattern` per schema object. Measured: `allOf` without `type` makes openapi-typescript emit `string & unknown`; with `type` it emits `string` (`variants.ts`) |
| `format` keyword | Not emitted | Format-Annotation is the default and "MUST be disabled by default" as an assertion (2020-12 Validation 7.2.1), but a client that enables it (ajv-formats) would refuse `.a@ephico2real.com`, which the server accepts, or accept an IRI that the URL rule refuses. The pattern says the rule exactly |
| Extras (`allowOther`) | `additionalProperties` (the value rule) plus `propertyNames` (the key class) | `additionalProperties` "applies only to the child values of instance names that do not appear in the annotation results of either" `properties` or `patternProperties` (Core 10.3.2.3): exactly the undeclared keys. `propertyNames` checks "every property name in the instance" (10.3.2.4), the declared ones included |
| Kubernetes key syntax | `propertyNames.pattern` = `QUALIFIED_NAME`, `maxLength: 317` (253 + 1 + 63) | The labels doc and `IsLabelKey`; the 253 bound on the prefix alone is in the validator, not the regex (lookaround is not portable) |
| Key classes | `propertyNames.anyOf`: the declared and operatorOnly keys, or an `allowOther` prefix that is not a system key, an adoption label, the other kind's key or a reserved prefix | Mirrors `classify` (`metadata.py:215-233`) and the other-kind rule (`:270-275`). Without it, a fuzzer such as Schemathesis generates keys the server refuses |
| 63-character label value | `maxLength: 63` and the `{0,61}` of `NAME` | Kubernetes: "must be 63 characters or less (can be empty)" |
| Annotation value size | `maxLength: maxValueBytes` on extras only | `validate` limits team annotation values in UTF-8 bytes (`:301-304`); JSON Schema counts characters, so the schema bound is an upper bound, said in the description. `maxBytesTotal` and `max` (count of team keys) are not expressible: description |
| Derived keys (`value.from`) | In `properties`, `readOnly: true`, label syntax, never in `required` | 2020-12 Validation 9.4: readOnly means the value "is managed exclusively by the owning authority, and attempts by an application to modify the value of this property are expected to be ignored or rejected". `_governed` accepts the same value and refuses another (`:321-327`): the value depends on the request, so no `const` |
| `namespacePrefix` | Description only | Depends on the `namespace` field; 2020-12 has no `$data` |
| operatorOnly keys | In `properties`, outside the team limits | Without them, `cmapi.net/protected` fell to `additionalProperties` and a 4097-character value was refused by the schema and accepted by the server (found by the differential run, fixed) |
| Patch: removal | Optional declared and extra keys: `anyOf [rule, {type: null}]`. Required and derived keys: no `null` branch | `validate` refuses `null` on a required key always (`missing_required_key`: the key is in `sent`, so the "held" exception at `:290` does not apply) and on a derived key (`derived_key`, `:324`) |
| Patch: required | None | A merge patch sends only what changes; whether the merged result holds every required key depends on Git, not the body |
| Patch: `null` form | `anyOf`, not `type: ["string","null"]` | Measured: oasdiff 1.37.0 reported the type list as `request-property-list-of-types-narrowed ... removing types null` (2 false errors); the `anyOf` form, which FastAPI writes, reports none |
| Configured pattern shown wrapped | `^(?:^[a-z0-9-]{2,40}$)$` | Exactly what policygen already sends to CEL (`policygen.py:114`); always correct, whatever alternation the pattern holds. The description shows the raw pattern |

### 2.5 The schema for the CRC configuration, in full

CRC's `metadata-keys.yaml` (`deploy/manifests/environments/crc/20-config.yaml:338-371`) parses equal to the example file that
writes the committed contract, so this is what both the committed `openapi.json` and CRC's `/openapi.json` would carry.
Generated by `proto/build_head.py`, copied from `crc-schema.json`:

```json
{
 "NamespaceCreate.required": ["namespace", "labels", "annotations"],
 "NamespaceCreate.properties.labels": {
  "type": "object",
  "title": "Labels",
  "description": "Required: `cmapi.net/team` (must match ^[a-z0-9-]{2,40}$). Optional: `cmapi.net/cost-center` (must match ^cc-[0-9]{4}$); `cmapi.net/app` (must match ^[a-z0-9-]{2,40}$); `cmapi.net/rightsizing` (must match ^(auto|manual)$). Any other key with no prefix, `*.ephico2real.com/`, at most 50.",
  "examples": [{"cmapi.net/team": "payments"}],
  "required": ["cmapi.net/team"],
  "properties": {
   "cmapi.net/app": {"type": "string", "maxLength": 63, "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
    "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$"}],
    "description": "Links an app's environments. Must match ^[a-z0-9-]{2,40}$."},
   "cmapi.net/cost-center": {"type": "string", "maxLength": 63, "pattern": "^(?:^cc-[0-9]{4}$)$",
    "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$"}],
    "description": "Must match ^cc-[0-9]{4}$.", "examples": ["cc-4410"]},
   "cmapi.net/protected": {"type": "string", "maxLength": 63,
    "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$",
    "description": "cmapi-operator and above only (operatorOnly)."},
   "cmapi.net/rightsizing": {"type": "string", "maxLength": 63, "pattern": "^(?:^(auto|manual)$)$",
    "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$"}],
    "description": "Opt-in to automatic rnd and qa decreases. Must match ^(auto|manual)$."},
   "cmapi.net/team": {"type": "string", "maxLength": 63, "pattern": "^(?:^[a-z0-9-]{2,40}$)$",
    "allOf": [{"type": "string", "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$"}],
    "description": "Ownership and cost; any team, not checked against the caller. Must match ^[a-z0-9-]{2,40}$.",
    "examples": ["payments"]}
  },
  "propertyNames": {
   "maxLength": 317,
   "pattern": "^(?:[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*/)?[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?$",
   "anyOf": [
    {"enum": ["cmapi.net/app", "cmapi.net/cost-center", "cmapi.net/protected", "cmapi.net/rightsizing", "cmapi.net/team"]},
    {"pattern": "^(?:[^/]+|[^/]*\\.ephico2real\\.com/[^/]+)$",
     "not": {"anyOf": [
      {"enum": ["cmapi.net/beyond-tier", "cmapi.net/cluster-id", "cmapi.net/env", "cmapi.net/expires-at", "cmapi.net/expiry",
                "cmapi.net/instance", "cmapi.net/managed", "cmapi.net/request-id", "cmapi.net/requested-by",
                "cmapi.net/requested-by-user", "cmapi.net/team-dl", "cmapi.net/tier", "cmapi.net/tier-hash",
                "company.net/provisioner"]},
      {"pattern": "^(?:kubernetes\\.io|[^/]*\\.kubernetes\\.io|k8s\\.io|openshift\\.io|[^/]*\\.openshift\\.io|argocd\\.argoproj\\.io|[^/]*\\.kyverno\\.io|redhatcop\\.redhat\\.io)/"}]}}
   ]
  },
  "additionalProperties": {"type": "string", "maxLength": 63,
                           "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$"}
 },
 "NamespaceCreate.properties.annotations": {
  "type": "object",
  "title": "Annotations",
  "description": "Required: `cmapi.net/team-dl` (an address in ['ephico2real.com']). Optional: none. Any other key with no prefix, `*.ephico2real.com/`, at most 50.",
  "examples": [{"cmapi.net/team-dl": "payments-team@ephico2real.com"}],
  "required": ["cmapi.net/team-dl"],
  "properties": {
   "cmapi.net/protected": {"type": "string", "description": "cmapi-operator and above only (operatorOnly)."},
   "cmapi.net/team-dl": {"type": "string",
    "pattern": "^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@(?:[eE][pP][hH][iI][cC][oO]2[rR][eE][aA][lL]\\.[cC][oO][mM])$",
    "description": "The team's mail list, an address in one of emailDomains. An address in ['ephico2real.com'].",
    "examples": ["payments-team@ephico2real.com"]}
  },
  "propertyNames": {
   "maxLength": 317,
   "pattern": "<QUALIFIED_NAME, as for labels>",
   "anyOf": [
    {"enum": ["cmapi.net/protected", "cmapi.net/team-dl"]},
    {"pattern": "^(?:[^/]+|[^/]*\\.ephico2real\\.com/[^/]+)$",
     "not": {"anyOf": [
      {"enum": ["cmapi.net/app", "cmapi.net/beyond-tier", "cmapi.net/cluster-id", "cmapi.net/cost-center", "cmapi.net/env",
                "cmapi.net/expires-at", "cmapi.net/expiry", "cmapi.net/instance", "cmapi.net/managed", "cmapi.net/request-id",
                "cmapi.net/requested-by", "cmapi.net/requested-by-user", "cmapi.net/rightsizing", "cmapi.net/team",
                "cmapi.net/tier", "cmapi.net/tier-hash"]},
      {"pattern": "<the reserved-prefix pattern, as for labels>"}]}}
   ]
  },
  "additionalProperties": {"type": "string", "maxLength": 4096}
 },
 "NamespacePatch.properties.labels": {
  "title": "Labels",
  "description": "Merge patch; null removes a key. Required: `cmapi.net/team` (...). <as above>",
  "examples": [{"cmapi.net/cost-center": "cc-4410"}],
  "anyOf": [
   {"type": "object",
    "properties": {
     "cmapi.net/team": "<exactly the create schema of cmapi.net/team: no null branch>",
     "cmapi.net/app": {"anyOf": ["<the create schema of cmapi.net/app, without description>", {"type": "null"}],
                       "description": "Links an app's environments. Must match ^[a-z0-9-]{2,40}$."},
     "cmapi.net/cost-center": {"anyOf": ["<create schema>", {"type": "null"}], "description": "Must match ^cc-[0-9]{4}$."},
     "cmapi.net/rightsizing": {"anyOf": ["<create schema>", {"type": "null"}], "description": "..."},
     "cmapi.net/protected": {"anyOf": ["<create schema>", {"type": "null"}], "description": "cmapi-operator and above only (operatorOnly)."}
    },
    "propertyNames": "<as for create>",
    "additionalProperties": {"anyOf": [{"type": "string", "maxLength": 63,
                                        "pattern": "^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$"},
                                       {"type": "null"}]}},
   {"type": "null"}
  ]
 },
 "NamespacePatch.properties.annotations": {
  "title": "Annotations",
  "description": "Merge patch; null removes a key. Required: `cmapi.net/team-dl` (...). <as above>",
  "examples": [null],
  "anyOf": [
   {"type": "object",
    "properties": {
     "cmapi.net/team-dl": "<exactly the create schema: no null branch>",
     "cmapi.net/protected": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "cmapi-operator and above only (operatorOnly)."}
    },
    "propertyNames": "<as for create>",
    "additionalProperties": {"anyOf": [{"type": "string", "maxLength": 4096}, {"type": "null"}]}},
   {"type": "null"}
  ]
 }
}
```

The `<...>` placeholders above repeat a block already written out once in the same listing; the generated file with every
block expanded is `crc-schema.json` (453 lines) in the scratch folder, and the whole head document is `head.json`.

## 3. Breaking or not; committed contract and served documents; samples and docs

### 3.1 oasdiff 1.37.0 (the version `contract/README.md` pins), measured

`contract/gate.sh <main openapi.json> head.json`: exit 1, `14 changes: 14 error, 0 warning, 0 info`. The 14 lines, in the
form `accepted-breaking.txt` takes (`accepted-328.txt`):

```
# #328, accepted before the first release: the labels and annotations of a namespace become schema. Each request these lines
# name was already refused by the service with a 422 (metadata.py validate); the document now says so.
POST /api/v1/clusters/{cluster_id}/namespaces added the new required request property `annotations/cmapi.net/team-dl`
POST /api/v1/clusters/{cluster_id}/namespaces added the new required request property `labels/cmapi.net/team`
POST /api/v1/clusters/{cluster_id}/namespaces the request property `annotations` became required
POST /api/v1/clusters/{cluster_id}/namespaces the request property `labels` became required
POST /api/v1/clusters/{cluster_id}/namespaces the `annotations/additionalProperties` request property's maxLength was set to `4096`
POST /api/v1/clusters/{cluster_id}/namespaces the `labels/additionalProperties` request property's maxLength was set to `63`
POST /api/v1/clusters/{cluster_id}/namespaces added the pattern `^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$` to the request property `labels/additionalProperties`
POST /api/v1/clusters/{cluster_id}/namespaces added 'propertyNames' constraint to the request property `annotations`
POST /api/v1/clusters/{cluster_id}/namespaces added 'propertyNames' constraint to the request property `labels`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} the `annotations/anyOf[subschema #1]/additionalProperties/anyOf[subschema #1]` request property's maxLength was set to `4096`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} the `labels/anyOf[subschema #1]/additionalProperties/anyOf[subschema #1]` request property's maxLength was set to `63`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} added the pattern `^(?:[A-Za-z0-9](?:[-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?)?$` to the request property `labels/anyOf[subschema #1]/additionalProperties/anyOf[subschema #1]`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} added 'propertyNames' constraint to the request property `annotations/anyOf[subschema #1]`
PATCH /api/v1/clusters/{cluster_id}/namespaces/{ns} added 'propertyNames' constraint to the request property `labels/anyOf[subschema #1]`
```

With main's `accepted-breaking.txt` plus these lines: `oasdiff breaking --fail-on ERR --err-ignore ...`: exit 0, "No
breaking changes to report". oasdiff does not report the `pattern`, `enum` or `maxLength` of a newly declared property in
`properties` (a new optional property is not breaking to it); only the `additionalProperties` and `required` changes show.

Classification: breaking for the contract, not for behaviour. Every request the lines name is refused today by
`metadata.py` with 422 `policy-violation` (or 422 `validation-failed` for `http://[x`). Section 2.3's validator fixes are
behaviour changes, and go in their own defect issue.

### 3.2 Committed contract vs each instance's `/openapi.json`

- The committed `openapi.json` is "the document that the code serves, for the test instance of the service suite"
  (`contract/README.md`), whose config is the example file (`tests/service/conftest.py:386`). It carries the example
  config's keys, as its descriptions and examples already do today (`emailDomains: ephico2real.com` is in main's contract).
- Each instance serves its own (`main.py:178`, `ctx.cfg.metadata`). CRC, kind, Helm and local parse equal to the example
  config today (measured), so CRC's `/openapi.json` will equal the committed contract for these fields. An instance with the
  company profile serves `company.net/mnemonic`, `lob`, `cl` as required and `name`/`company.net/app-environment` as
  readOnly (measured in the sample, section 4).
- Consequence for generated clients: a client generated from the committed contract encodes the example config's keys. The
  portal is one (`scripts/api-types.mjs:14`). The docs must say: generate from the instance you call
  (`/openapi.json` of that instance), not from Git, when the instance's `metadata-keys.yaml` differs.
- The oasdiff gate only sees the example config. A config change on an instance is outside the gate by design; the guard is
  test T7 (the deployment copies equal the example) plus each instance's own Swagger UI.

### 3.3 Samples, docs/04 and other docs

- `samples.json` is unchanged: the recorded create body already carries `cmapi.net/team`, `cmapi.net/cost-center` and
  `cmapi.net/team-dl` with valid values (read from `cmapi/src/cmapi/contract/samples.json`). Swagger UI's Example Value on
  the real document is byte-identical before and after (measured, `swagger-contract.json`). So `docs/04-api-examples.md`,
  which is generated from the same samples, does not change.
- Spectral (`contract/spectral`, the contract's lock): head passes with 0 results. New coverage, measured: a recorded body
  with `cmapi.net/team: "-payments"` passes on main and fails on head with `oas3-valid-media-example ... must match pattern`;
  a body without `cmapi.net/team-dl` fails on head with `must have required property "cmapi.net/team-dl"`.
- Docs to update: `docs/18-configuration.md` "The rule of one key" (the pattern dialect, `re.ASCII`, the loader's new
  refusal; a required key without `value.from` should have an `example`, see open question 3), `docs/02` "Labels and
  annotations" (the document now carries the rules as schema), `cmapi/contract/README.md` (generate a client from the
  instance's own `/openapi.json`), and `docs/01` "API documentation" (one line on per-instance schema).

## 4. Measured rendering: Swagger UI and openapi-typescript

Versions: Swagger UI **5.34.1**, the version `cmapi/Containerfile:18-19` pins; the tarball's SHA-256
`8e7286de0230e431fc8a5a75490d28117af3d0c306413b6f9e17f7bb55045fb6` equals the pin. Configured like FastAPI 0.115.6's
`get_swagger_ui_html` (`layout: BaseLayout, deepLinking, showExtensions, showCommonExtensions`). Driven with Playwright
1.64.1 (`drive.mjs`, `drive-contract.mjs`). openapi-typescript **7.13.0** and TypeScript 5.9.3 from
`cmapi-portal-ui/tools/openapi-types/package-lock.json`.

Sample: `sample.json`, OpenAPI 3.1.0, four operations: CRC create/patch, company-profile create/patch.

| What | Main | Design B |
|---|---|---|
| Swagger required marks, real document, POST namespaces body (`json-schema-2020-12-property--required`) | `namespace` | `annotations`, `cmapi.net/team-dl`, `labels`, `cmapi.net/team`, `namespace` |
| Swagger model line for `cmapi.net/team` | none (prose only) | `string ≤ 63 characters matches ^(?:^[a-z0-9-]{2,40}$)$` plus its description and example |
| Swagger, company sample: required marks | n/a | `namespace`, `labels`, `company.net/cl`, `company.net/lob`, `company.net/mnemonic`; enum values listed |
| Swagger, derived keys (`readOnly`) | n/a | Not shown in the request model or the generated example: Swagger hides readOnly in a request body. They stay listed in the map's description |
| Swagger, the `allOf` label-syntax pattern | n/a | Not shown on the property line; the key's own pattern is |
| Swagger, `propertyNames` | n/a | Shown as "Property names" with the enum and the patterns |
| Swagger Example Value, real document | the recorded sample | identical (the media type's `example` wins over generation) |
| openapi-typescript, `NamespaceCreate.labels` | `{ [key: string]: string }` | `{ "cmapi.net/app"?: string; "cmapi.net/cost-center"?: string; "cmapi.net/protected"?: string; "cmapi.net/rightsizing"?: string; "cmapi.net/team": string } & { [key: string]: string }` |
| openapi-typescript, `NamespacePatch.labels` | `{ [key: string]: string \| null } \| null` | `({ "cmapi.net/team"?: string; "cmapi.net/cost-center"?: (string) \| null; ... } & { [key: string]: string \| null }) \| null`: `null` on `cmapi.net/team` does not type-check |
| openapi-typescript, derived keys (company sample) | n/a | `readonly name?: string; readonly "company.net/app-environment"?: string` |
| openapi-typescript, `propertyNames` | n/a | Ignored |
| `tsc --strict` on the portal's body (`NewNamespaceTab.tsx:145-152`) | compiles | compiles |
| `tsc --strict` on a body without labels/annotations | compiles | `TS2739 ... missing the following properties ... annotations, labels` |
| `tsc --strict` on maps built at run time (`Record<string, string>`) | compiles | `TS2322 Property '"cmapi.net/team"' is missing` |

The last row is the portal's tension: a form built from the served schema at run time cannot be typed by the committed
contract's literal keys. See open question 1.

Browser note for the portal, measured in Node 26: `new RegExp("^[a-z0-9-]{2,40}$", "v")` throws "Invalid character class",
as do `LABEL_VALUE` and the email local part. An HTML `pattern` attribute is compiled with the `v` flag, so the portal must
check with `new RegExp(p, "u")` (which compiles all of them, as ajv does), never with the `pattern` attribute.

## 5. Tests that fail on main and pass after

Each "fails on main" below is measured on main's code or main's contract, except where marked.

**T1. The served document requires the instance's keys** (`cmapi/tests/service/test_api_docs.py`). On main:
`create["required"] == ["namespace"]` and `labels` has no `required` (read from the committed contract), so it fails.

```python
def test_the_namespace_body_requires_each_required_key_of_this_instance(client):
    """#328: the required labels and annotations of metadata-keys.yaml are schema, not only prose."""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    create, patch = schemas["NamespaceCreate"], schemas["NamespacePatch"]
    assert {"namespace", "labels", "annotations"} <= set(create["required"])
    labels, annotations = create["properties"]["labels"], create["properties"]["annotations"]
    assert labels["required"] == ["cmapi.net/team"] and annotations["required"] == ["cmapi.net/team-dl"]
    assert labels["properties"]["cmapi.net/team"]["pattern"] == "^(?:^[a-z0-9-]{2,40}$)$"
    patched = patch["properties"]["labels"]["anyOf"][0]["properties"]
    assert "anyOf" not in patched["cmapi.net/team"], "a patch cannot remove a required key"
    assert {"type": "null"} in patched["cmapi.net/cost-center"]["anyOf"], "a patch can remove an optional key"
    assert "required" not in patch["properties"]["labels"]["anyOf"][0]
```

**T2. The company instance serves its own keys** (`cmapi/tests/service/test_metadata_stanzas_api.py`, which already starts
an instance on `metadata-keys.company.yaml`, `:27`). Fails on main (no `required`, no `properties`).

```python
def test_the_document_of_a_company_instance_names_its_keys(company_client):
    labels = company_client.get("/openapi.json").json()["components"]["schemas"]["NamespaceCreate"]["properties"]["labels"]
    assert labels["required"] == ["company.net/cl", "company.net/lob", "company.net/mnemonic"]
    assert labels["properties"]["company.net/cl"]["enum"] == ["0", "1", "2", "3"]
    for derived in ("name", "company.net/app-environment"):
        assert labels["properties"][derived]["readOnly"] is True and derived not in labels["required"]
```

**T3. Differential: the validator and the schema answer the same** (`cmapi/tests/core/test_metadata_schema.py`; ajv 8 from
`cmapi/contract/spectral/node_modules`, which CI installs for the lint; skipped without it unless `CMAPI_REQUIRE_NODE=1`, the
same rule as `CMAPI_REQUIRE_KYVERNO`). Measured on main's contract: 4126 of 5385 cases differ. With the design-B schema and
main's validator: shipped 202 differ (all `/foo`, which is how this test found D1); company 462 differ (`/foo`, the two URL
cases of D2, and the inexpressible classes). With the design-B schema and the validator of 2.3 applied by monkeypatch
(`proto/patched_validator.py`, `DESIGN_B_VALIDATOR=1`): shipped **5385 of 5385 agree**; company 5414 of 5680 agree, and every
one of the 266 that differ is a documented inexpressible class (a derived key sent with another value; `namespacePrefix`). The corpus generator is
`proto/differential.py` and the ajv leg `diff.mjs` (both in the scratch folder, both run); the test wraps them:

```python
INEXPRESSIBLE = ("derived_key", "namespacePrefix")       # depend on the request; the schema says readOnly / prose


@pytest.mark.parametrize("profile, namespace, env", [("metadata-keys.yaml", "payments-dev", "dev"),
                                                     ("metadata-keys.company.yaml", "abc-rnd", "rnd")])
def test_the_schema_refuses_exactly_what_the_validator_refuses(ajv, tmp_path, profile, namespace, env):
    keys = MetadataKeys.load(EX / "cluster-configs/policies" / profile)
    cases = corpus(keys, namespace, env)                  # differential.py: 5385 / 5680 bodies, create and patch
    verdicts = ajv(tmp_path, {f"{k}-{'patch' if p else 'create'}": metadata_schema(keys, k, patch=p)
                              for k in KINDS for p in (False, True)}, [c["body"] for c in cases], [c["schema"] for c in cases])
    differ = [c for c, ok in zip(cases, verdicts) if ok != c["python"]["ok"]
              and not any(code in INEXPRESSIBLE for code in c["python"]["codes"])]
    assert differ == [], differ[:5]
```

**T4. One regex for the three readers** (`cmapi/tests/core/test_policygen.py` and `test_metadata_stanzas.py`). Fails on
main: policygen's email and URL CEL are not `value_regex` (`policygen.py:117-130`), and the validator accepts
`"\x01http://x"` (measured `[]`).

```python
def test_the_validator_the_policy_and_the_document_read_one_regex(catalog, company):
    bundle = render_bundle(catalog, company, PolicySettings(), {"rnd"}, "nonprod")
    text = "\n".join(bundle.values())
    for kind in KINDS:
        for key, rule in company.rules[kind].items():
            if (rx := value_regex(rule, company.email_domains)) is not None:
                assert cel(rx) in text, key
                assert metadata_schema(company, kind, patch=False)["properties"][key]["pattern"] == rx


@pytest.mark.parametrize("value", ["\x01http://x", " http://x", "http://x "])
def test_python_refuses_each_url_that_the_policy_refuses(company, value):
    errs = company.validate(SENT, {"company.net/mnemonic-confluence": value}, operator=False, sources=SOURCES)
    assert [e["code"] for e in errs] == ["invalid_value"]
```

The Kyverno leg: add `"\x01http://x"` and `{"cmapi.net/team": "-payments"}` (shipped config) to the parameters of
`test_python_and_kyverno_refuse_the_same_value` (`test_policygen.py:207-227`), which CI runs with the pinned CLI.

**T5. The loader refuses a pattern that RE2 or ECMA-262 reads differently** (`test_metadata_stanzas.py`, beside the
existing refusals at `:114-122`). Fails on main: all five load (measured).

```python
@pytest.mark.parametrize("pattern", [r"^[a-z]+\Z", r"(?i)^[a-z]+$", r"^(?P<t>[a-z]+)$", r"^(?=x)[a-z]+$", r"^([a-z])\1$",
                                     r"^\s+$", r"^[[:alpha:]]+$"])
def test_a_pattern_that_is_not_portable_stops_the_start(pattern):
    raw = yaml.safe_load(COMPANY.read_text())
    raw["requiredLabels"]["company.net/mnemonic"]["pattern"] = pattern
    with pytest.raises(ValueError, match="RE2 .Kyverno. or ECMA-262"):
        MetadataKeys(raw)
```

**T6. An empty key prefix is refused** (`test_metadata_stanzas.py`). Fails on main (measured `[]`).

```python
@pytest.mark.parametrize("key", ["/foo", "a/b/c", "x.ephico2real.com/"])
def test_a_key_that_kubernetes_refuses_is_refused(key):
    keys = MetadataKeys.load(EX / "cluster-configs/policies/metadata-keys.yaml")
    errs = keys.validate({"cmapi.net/team": "payments", key: "x"}, {"cmapi.net/team-dl": "a@ephico2real.com"}, operator=False)
    assert {"code": "invalid_key", "key": key} in errs
```

(`a/b/c` and `x.ephico2real.com/` are already refused on main; they keep the fix honest.)

**T7. Guard, passes on main: every deployment copy is the contract's config** (`tests/service/test_plain_manifests.py`).
Today only CRC == kind is held (`:270-271`); all four are equal (measured). This keeps CRC's served schema equal to the
committed one.

```python
@pytest.mark.parametrize("copy", ["crc", "kind", "helm", "local"])
def test_each_metadata_keys_copy_is_the_one_the_contract_documents(copy):
    reference = yaml.safe_load((EXAMPLES / "cluster-configs/policies/metadata-keys.yaml").read_text())
    text = {"crc": lambda: config_file("crc", "metadata-keys.yaml"), "kind": lambda: config_file("kind", "metadata-keys.yaml"),
            "helm": lambda: (ROOT / "deploy/helm/cmapi/config/metadata-keys.yaml").read_text(),
            "local": lambda: (EXAMPLES / "local/config/metadata-keys.yaml").read_text()}[copy]()
    assert yaml.safe_load(text) == reference
```

**T8. Portal drift guard** (`cmapi-portal-ui/tests/contract.test.mjs`). Fails on main: the contract has no
`labels.required`. It does not make the portal work on the company profile (open question 1); it makes a change of the
example config's required keys fail the portal's suite instead of passing silently.

```js
// #328: the keys that the New namespace form sends are the contract's required keys, no more and no fewer.
const create = contract.components.schemas.NamespaceCreate.properties;
const form = readFileSync(join(app, "src/portal/NewNamespaceTab.tsx"), "utf8");
const sent = (field) => [...form.matchAll(new RegExp(`${field}: \\{ "([^"]+)"`, "g"))].map((m) => m[1]);
assert.deepEqual(sent("labels"), create.labels.required ?? [], "labels the form sends");
assert.deepEqual(sent("annotations"), create.annotations.required ?? [], "annotations the form sends");
```

Not run here: T1, T2, T7 need the service suite (PostgreSQL on 55432); T8 needs the portal's full `node_modules`
(the worktree's is incomplete: `tsc` on a copy reported missing `openapi-fetch` and `@tanstack/react-query`). Their
"fails on main" is read from main's contract and code, not executed. T3, T5, T6 and the T4 validator case are executed as
the prototype scripts listed.

## 6. Rejected alternatives

| Alternative | Why not |
|---|---|
| Keep prose, add `x-cmapi-required-keys` | Swagger UI, openapi-typescript, ajv and Spectral ignore an extension; the issue is that tools see nothing |
| A static Pydantic model with the CRC keys as fields | Keys are per instance (#215); the company profile has other keys. The model would be wrong on every other instance and need code changes per config |
| `patternProperties: {"": LabelValue}` for the label syntax | Applies to every key and gives clean TypeScript (measured `string`), but Swagger UI shows no value rule for extras and oasdiff did not report it; `additionalProperties` plus a typed `allOf` is visible in both |
| `$ref` to a `LabelValue` component beside `pattern` | openapi-typescript emits `components["schemas"]["LabelValue"]` for every key (measured), noisier than `string` |
| Combine label syntax and rule in one lookahead pattern | Unreadable, and lookahead is not in RE2, so it could not be the one regex |
| `type: ["string", "null"]` for patch values | oasdiff 1.37.0 misread it as narrowing (measured, 2 false `ERR`) |
| `format: email` / `format: uri` | See 2.4; they disagree with the server in both directions when asserted |
| `const`/`enum` for derived keys | The value is the request's namespace, environment or cluster; an enum of all environments would accept a wrong one |
| Forbid derived keys in the schema (`false`) | The server accepts the same value back (`metadata.py:323`), so a client doing read-modify-write would fail locally |
| Named components for the label maps | Trips `cmapi-net-keys-only-in-labels` (2.2) |
| A committed contract with no instance keys (neutral config) | Leaves Git's contract, the portal types and the gate as blind as today; the README defines the committed document as the test instance's |
| Strip the `^...$` of a configured pattern before wrapping | Correct only without top-level alternation; detecting that needs Python's private `re._parser`. The wrap is what CEL already gets |
| Python `jsonschema` for the differential test | Its `pattern` uses Python `re.search`, which differs from ECMA on a trailing newline (measured, D4); ajv is the ECMA engine that clients use |

## 7. Primary sources, read on 2026-11-16

- JSON Schema 2020-12 Validation, <https://json-schema.org/draft/2020-12/json-schema-validation>: 6.3.3 `pattern`: "This
  string SHOULD be a valid regular expression, according to the ECMA-262 regular expression dialect." and "Recall: regular
  expressions are not implicitly anchored." 9.4: readOnly "indicates that the value of the instance is managed exclusively by
  the owning authority, and attempts by an application to modify the value of this property are expected to be ignored or
  rejected by that owning authority." 7.2.1: format assertion "MUST be disabled by default".
- JSON Schema 2020-12 Core, <https://json-schema.org/draft/2020-12/json-schema-core>: 6.4: implementations "MUST NOT take
  regular expressions to be anchored, neither at the beginning nor at the end." 10.3.2.3 `additionalProperties` "applies
  only to the child values of instance names that do not appear in the annotation results of either" `properties` or
  `patternProperties`; 10.3.2.4 `propertyNames`: "every property name in the instance validates against the provided schema".
- OpenAPI 3.1.0, <https://spec.openapis.org/oas/v3.1.0.html>, 4.4: "Models are defined using the Schema Object, which is a
  superset of JSON Schema Specification Draft 2020-12"; the dialect requires "the OAS base vocabulary, in addition to the
  vocabularies as specified in the JSON Schema draft 2020-12".
- Kubernetes, Labels and Selectors, <https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/>: "The name
  segment is required and must be 63 characters or less, beginning and ending with an alphanumeric character ([a-z0-9A-Z])
  with dashes (-), underscores (_), dots (.), and alphanumerics between. The prefix is optional. If specified, the prefix
  must be a DNS subdomain ... not longer than 253 characters in total, followed by a slash (/)." Values: "must be 63
  characters or less (can be empty), unless empty, must begin and end with an alphanumeric character".
- Kubernetes apimachinery `pkg/api/validate/content/kube.go` (`IsLabelKey`; `validation.IsQualifiedName` is now its
  deprecated alias): `if len(prefix) == 0 { errs = append(errs, "prefix part "+EmptyError()) }`, `labelKeyMaxLength = 63`.
- oasdiff breaking-change rules, as `contract/README.md` cites (read 2026-11-13 there); the rule ids above are oasdiff
  1.37.0's own output.

## 8. Open questions for the coordinator

1. **Portal on a non-CRC instance.** `NewNamespaceTab.tsx` hard-codes two keys (D5), and the mockup (`#ns-team`, `#ns-dl`,
   parity tests) has those two fields. A form built from the served `/openapi.json` (one field per `required` key, optional
   declared keys under "More", checks with `new RegExp(p, "u")`) is the fix, but it changes the mockup contract and needs a
   `Record<string, string>` body type (measured `TS2322` against the literal keys). Proposal: its own issue, parent #328;
   #328 ships T8 as the guard.
2. **The validator fixes of 2.3** (`/foo`, the URL algorithm, the dialect check) change behaviour. Proposal: one defect
   issue under `fix-defect`, parent #328, landed first, so #328 is documentation only.
3. **A required key without `example`.** `metadata_example` leaves it out (`docs.py:395-398`), so the map's example would
   fail its own `required` and Spectral's `oas3-valid-schema-example` would fail the lint. Refuse such a config at load, or
   synthesise one (enum: the first value; email: `team@<first domain>`)? A pattern cannot be synthesised.
4. **`http://[x`.** With the shared regex it is accepted, as Kyverno accepts it today. Tighten the host class (no `[`/`]`
   outside an IPv6 literal) in the one regex, which changes Kyverno too?
5. **Generated clients outside the portal.** Say in docs/01 and the contract README that a client is generated from the
   instance's own `/openapi.json`; is a per-instance released contract (`released/<version>-<instance>.json`) wanted?

## 9. Artefacts and housekeeping

Kept in the scratch folder: `run.sh` and `run.log` (all measurements), `proto/` (generator, head and sample builders,
differential corpus, classifier, tri-engine corpus), `diff.mjs`, `drive.mjs`, `drive-contract.mjs`, `tri/` (Go and Node
legs, `result.txt`), `head.json`, `sample.json`, `crc-schema.json`, `head.ts`, `sample.ts`, `variants.ts`,
`oasdiff-gate.txt`, `accepted-328.txt`, `accepted-breaking.candidate.txt`, `spectral-head.txt`, `diff-*.log`,
`swagger-drive.log`, `swagger-contract.json`, `swagger-*.png`, `tscheck/`. Deleted at the end: the venv, the two
`node_modules`, the Go build cache, the copied Swagger bundle. To re-run, recreate them as `run.sh`'s header says.
`git status --short` of `cmapi-design` was empty before and after.
