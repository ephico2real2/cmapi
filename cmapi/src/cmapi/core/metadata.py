"""Label and annotation keys: classes, validation, merge patch and render order.

One file, cluster-configs/policies/metadata-keys.yaml, decides every key's class, and the same file
feeds the Kyverno bundle, so plan time, CI and admission agree. Classes:

    system        set only by the renderer (cluster-id, tier, requested-by, expiry, ...)
    operatorOnly  cmapi-operator and above (cmapi.net/protected)
    reserved      Kubernetes, OpenShift and platform-controller prefixes
    governed      caller-set, pattern- or format-checked, some required (team, team-dl, cost-center)
    team          anything else under an allowed prefix, within count and size limits
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping

import yaml

from cmapi.core.errors import Problem
from cmapi.core.identity.checks import email_in_domains

_DNS1123_SUB = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")
_NAME = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")

KeyClass = str   # "system" | "operatorOnly" | "reserved" | "governed" | "team" | "disallowed"


@dataclass(frozen=True)
class Governed:
    kind: str                       # label | annotation
    required: bool = False
    pattern: str | None = None
    format: str | None = None       # email-in-domains


class MetadataKeys:
    def __init__(self, raw: Mapping[str, Any]):
        self.system = list(raw.get("system", []))
        self.operator_only = list(raw.get("operatorOnly", []))
        self.reserved_prefixes = [p.rstrip("/") for p in raw.get("reservedPrefixes", [])]
        self.governed = {k: Governed(kind=v["kind"], required=v.get("required", False),
                                     pattern=v.get("pattern"), format=v.get("format"))
                         for k, v in (raw.get("governed") or {}).items()}
        team = raw.get("team") or {}
        self.allowed_prefixes = [p.rstrip("/") for p in team.get("allowedPrefixes", [""])]
        self.max_labels = team.get("maxLabels", 50)
        self.max_annotations = team.get("maxAnnotations", 50)
        self.max_value_bytes = team.get("maxAnnotationValueBytes", 4096)
        self.max_total_bytes = team.get("maxAnnotationBytesTotal", 65536)
        self.sensitive = set(raw.get("sensitiveKeys", []))
        self.email_domains = [d.lower() for d in raw.get("emailDomains", [])]
        problems = []
        for k, g in self.governed.items():
            if g.format not in (None, "email-in-domains"):
                problems.append(f"{k}: unknown format {g.format}")
            if g.format == "email-in-domains" and not self.email_domains:
                problems.append(f"{k}: format email-in-domains needs emailDomains")
            if g.pattern:
                re.compile(g.pattern)
        if problems:
            raise ValueError("invalid metadata-keys.yaml: " + "; ".join(problems))

    @classmethod
    def load(cls, path: str | Path) -> "MetadataKeys":
        return cls(yaml.safe_load(Path(path).read_text()))

    # ---- classes
    @staticmethod
    def _prefix(key: str) -> str:
        return key.split("/", 1)[0] if "/" in key else ""

    def _prefix_in(self, prefix: str, patterns: list[str]) -> bool:
        return any(fnmatchcase(prefix, p) if p else prefix == "" for p in patterns)

    def classify(self, key: str) -> KeyClass:
        if key in self.system:
            return "system"
        if key in self.operator_only:
            return "operatorOnly"
        if key in self.governed:
            return "governed"
        prefix = self._prefix(key)
        if prefix and self._prefix_in(prefix, self.reserved_prefixes):
            return "reserved"
        if self._prefix_in(prefix, self.allowed_prefixes):
            return "team"
        return "disallowed"

    # ---- validation of what a caller sends (never the renderer's own system keys)
    def validate(self, labels: Mapping[str, str | None], annotations: Mapping[str, str | None], *,
                 operator: bool, require_governed: bool = True,
                 current_labels: Mapping[str, str] | None = None,
                 current_annotations: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        """labels/annotations: what the caller sends (a merge patch; None removes a key).
        Classes and values are checked on what is sent; required keys and limits on the result,
        so a PATCH can neither remove a required key nor slip past the caps."""
        errs: list[dict[str, Any]] = []
        merged_labels = self.merge_patch(current_labels or {}, labels)
        merged_anns = self.merge_patch(current_annotations or {}, annotations)
        for kind, items in (("label", labels), ("annotation", annotations)):
            for key, value in items.items():
                e = self._syntax(key, value, kind)
                if e:
                    errs.append(e)
                    continue
                cls = self.classify(key)
                if cls in ("system", "reserved"):
                    errs.append({"code": "reserved_key", "key": key})
                elif cls == "disallowed":
                    errs.append({"code": "invalid_key", "key": key, "detail": "prefix not allowed"})
                elif cls == "operatorOnly" and not operator:
                    errs.append({"code": "operator_only_key", "key": key})
                elif cls == "governed" and value is not None:
                    errs.extend(self._governed(key, value, kind))
        if require_governed:
            for key, g in self.governed.items():
                src = merged_labels if g.kind == "label" else merged_anns
                if g.required and not src.get(key):
                    errs.append({"code": "missing_required_key", "key": key})
        team_labels = [k for k in merged_labels if self.classify(k) == "team"]
        team_anns = {k: v for k, v in merged_anns.items() if self.classify(k) == "team"}
        if len(team_labels) > self.max_labels or len(team_anns) > self.max_annotations:
            errs.append({"code": "too_many_keys"})
        sizes = [len(v.encode()) for v in team_anns.values()]
        if any(s > self.max_value_bytes for s in sizes) or sum(sizes) > self.max_total_bytes:
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

    def _governed(self, key: str, value: str, kind: str):
        g = self.governed[key]
        if g.kind != kind:
            return [{"code": "invalid_key", "key": key, "detail": f"{key} is a {g.kind}"}]
        if g.format == "email-in-domains" and not email_in_domains(value, self.email_domains):
            code = "invalid-team-dl" if key == "cmapi.net/team-dl" else "invalid_value"
            return [{"code": code, "key": key, "detail": f"not an address in {self.email_domains}"}]
        if g.pattern and not re.fullmatch(g.pattern, value):
            return [{"code": "invalid_value", "key": key, "detail": f"must match {g.pattern}"}]
        return []

    def check(self, labels, annotations, *, operator: bool, require_governed: bool = True,
              current_labels=None, current_annotations=None) -> None:
        errs = self.validate(labels, annotations, operator=operator,
                             require_governed=require_governed, current_labels=current_labels,
                             current_annotations=current_annotations)
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
