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
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import yaml

from cmapi.core.errors import Problem
from cmapi.core.identity.checks import email_in_domains

_DNS1123_SUB = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")
_NAME = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")

KeyClass = str   # "system" | "operatorOnly" | "reserved" | "governed" | "team" | "disallowed"
KINDS = ("label", "annotation")
# What cmapi can fill a key from. Each comes from the request's own target, never from the requester's text.
DERIVED_FROM = ("namespace", "environment", "cluster", "instance")
FORMATS = ("email-in-domains", "url")
_RULE_FIELDS = {"value", "pattern", "enum", "format", "namespacePrefix", "description", "example"}
_OLD_STANZAS = ("governed", "team")


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
        problems: list[str] = []
        old = [s for s in _OLD_STANZAS if s in raw]
        if old:
            # A file of the old format must not start: its required keys would silently stop being required.
            raise ValueError(f"metadata-keys.yaml has the stanzas {old} of the old format; write requiredLabels, "
                             "requiredAnnotations, extraLabels and extraAnnotations instead (docs/02, \"Labels and annotations\")")
        self.system = list(raw.get("system", []))
        self.operator_only = list(raw.get("operatorOnly", []))
        self.reserved_prefixes = [p.rstrip("/") for p in raw.get("reservedPrefixes", [])]
        self.sensitive = set(raw.get("sensitiveKeys", []))
        self.email_domains = [d.lower() for d in raw.get("emailDomains", [])]
        # {kind: {key: KeyRule}}: a key can be a label and an annotation at once, each with its own rule.
        self.rules: dict[str, dict[str, KeyRule]] = {"label": {}, "annotation": {}}
        self.allow_other: dict[str, AllowOther] = {}
        for kind, req_name, extra_name in (("label", "requiredLabels", "extraLabels"),
                                           ("annotation", "requiredAnnotations", "extraAnnotations")):
            for key, spec in (raw.get(req_name) or {}).items():
                self._add(kind, key, spec, True, req_name, problems)
            extra = raw.get(extra_name) or {}
            unknown = set(extra) - {"keys", "allowOther"}
            if unknown:
                problems.append(f"{extra_name}: unknown fields {sorted(unknown)}")
            for key, spec in (extra.get("keys") or {}).items():
                self._add(kind, key, spec, False, extra_name, problems)
            self.allow_other[kind] = self._allow_other(kind, extra.get("allowOther") or {}, extra_name, problems)
        self.adoption_labels: dict[str, tuple[str, ...]] = {}
        for key, spec in (raw.get("adoptionLabels") or {}).items():
            values = (spec or {}).get("recognise")
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

    def _add(self, kind: str, key: str, spec: Any, required: bool, stanza: str, problems: list[str]) -> None:
        where = f"{stanza}.{key}"
        spec = spec or {}
        if not isinstance(spec, Mapping):
            problems.append(f"{where}: a key's rule is a mapping")
            return
        unknown = set(spec) - _RULE_FIELDS
        if unknown:
            problems.append(f"{where}: unknown fields {sorted(unknown)}")
        if self._syntax(key, None, kind):
            problems.append(f"{where}: not a valid {kind} key")
        if key in self.system or key in self.operator_only or \
                ("/" in key and self._prefix_in(self._prefix(key), self.reserved_prefixes)):
            problems.append(f"{where}: a system, operator-only or reserved key cannot be set by a requester")
        if key in self.rules[kind]:
            problems.append(f"{where}: declared twice as a {kind}")
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
        if pattern is not None:
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"{where}: pattern does not compile: {exc}")
        if derived and (pattern is not None or enum is not None or fmt is not None or spec.get("namespacePrefix")):
            problems.append(f"{where}: a key with value.from takes no pattern, enum, format or namespacePrefix")
        if sum(x is not None for x in (pattern, enum, fmt)) > 1:
            problems.append(f"{where}: give one of pattern, enum and format")
        self.rules[kind][key] = KeyRule(kind=kind, required=required, derived=derived, pattern=pattern,
                                        enum=tuple(enum) if enum is not None else None, format=fmt,
                                        namespace_prefix=bool(spec.get("namespacePrefix")),
                                        description=spec.get("description"), example=spec.get("example"))

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
        return any(fnmatchcase(prefix, p) if p else prefix == "" for p in patterns)

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
                 sources: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        """labels/annotations: what the caller sends (a merge patch; None removes a key).
        Classes and values are checked on what is sent; required keys and limits on the result,
        so a PATCH can neither remove a required key nor slip past the caps. sources: the request's target
        (namespace, environment, cluster, instance), from which cmapi fills each value.from key."""
        sources = sources or {}
        errs: list[dict[str, Any]] = []
        merged = {"label": self.merge_patch(current_labels or {}, labels),
                  "annotation": self.merge_patch(current_annotations or {}, annotations)}
        for kind, items in (("label", labels), ("annotation", annotations)):
            for key, value in items.items():
                e = self._syntax(key, value, kind)
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
                        errs.append({"code": "missing_required_key", "key": key, "kind": kind,
                                     "detail": rule.text(self.email_domains)})
        namespace = sources.get("namespace")
        if namespace:
            for kind in KINDS:
                for key, rule in self.rules[kind].items():
                    value = merged[kind].get(key)
                    # Checked on the result, so a key sent earlier still has to fit the namespace it is on.
                    if rule.namespace_prefix and value and not namespace.startswith(f"{value}-") \
                            and key not in (labels if kind == "label" else annotations):
                        errs.append({"code": "invalid_value", "key": key, "kind": kind,
                                     "detail": f"{namespace} does not start with {value}-"})
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
        prefix, _, name = key.rpartition("/")
        if (prefix and (len(prefix) > 253 or not _DNS1123_SUB.fullmatch(prefix))) or \
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
        detail = rule.text(self.email_domains)
        if rule.format == "email-in-domains" and not email_in_domains(value, self.email_domains):
            code = "invalid-team-dl" if key == "cmapi.net/team-dl" else "invalid_value"
            return [{"code": code, "key": key, "detail": f"not an address in {self.email_domains}"}]
        if rule.format == "url":
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.netloc or any(c.isspace() for c in value):
                return [{"code": "invalid_value", "key": key, "detail": detail}]
        if rule.pattern and not re.fullmatch(rule.pattern, value):
            return [{"code": "invalid_value", "key": key, "detail": f"must match {rule.pattern}"}]
        if rule.enum is not None and value not in rule.enum:
            return [{"code": "invalid_value", "key": key, "detail": f"one of {list(rule.enum)}"}]
        namespace = sources.get("namespace")
        if rule.namespace_prefix and namespace and not namespace.startswith(f"{value}-"):
            return [{"code": "invalid_value", "key": key, "detail": f"{namespace} does not start with {value}-"}]
        return []

    def check(self, labels, annotations, *, operator: bool, require_governed: bool = True,
              current_labels=None, current_annotations=None, sources=None) -> None:
        errs = self.validate(labels, annotations, operator=operator,
                             require_governed=require_governed, current_labels=current_labels,
                             current_annotations=current_annotations, sources=sources)
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
