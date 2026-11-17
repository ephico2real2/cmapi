"""The Kyverno bundle, rendered from cmapi's own configuration (#212; docs/reviews/2026-11-14-issue-212/).

    render_bundle(catalog, keys, policy, environments, instance) -> {relative path: YAML or JSON text}

    env/<env>/cmapi-metadata.yaml     Namespace: the required and declared keys of metadata-keys.yaml (#215), and the keys that
                                      no stanza declares: their prefixes, count and bytes (allowOther, #333)
    env/<env>/cmapi-quota.yaml        ResourceQuota: each key at or below the environment's maximum (tiers.yaml)
    env/<env>/cmapi-limits.yaml       LimitRange: each key at or below its maximum; limits never below requests. The pvc
                                      keys only where tiers.yaml's storageLimitRange is on (#253)
    env/prod/deny-expiry-in-prod.yaml Namespace: production never expires (the hand-written policy, rendered)
    env/<env>/index.json              policy name -> the key and rule that the policy checks

Every value is written into the policy as a CEL literal, so the CLI at plan time, CI and admission give one answer with
no cluster lookup (docs/02, "Keeping it offline"). Each validation checks one key, and its message names the key, the
offending value and the configured value. Each check is its own policy, because Kyverno reports only the first failed
validation of a policy. An environment whose mode is off gets no files; audit, the default (#342), renders
`[Audit, Warn]`: admitted, recorded in a PolicyReport and returned to the client as a warning. enforce renders `[Deny]`
(#213). Deny and Warn may not be combined (the ValidatingPolicy CRD of Kyverno v1.20.0).

A value that the object already held is not checked again: at admission an UPDATE whose key keeps its oldObject value
passes, and at plan time cmapi drops a failure on a key whose value Git already holds (core/validate). The bounds of
tiers.py do the same (`_out_of_bounds`), so a later, lower bound never refuses an approved namespace.

A policy whose validation reads oldObject runs at admission only: `evaluation.background.enabled: false` (#345). A
background scan builds its request as a CREATE with no oldObject and no user (Kyverno v1.20.0,
pkg/controllers/report/utils/scanner.go), so it would report a value that the namespace keeps as a failure; the CRD
says the field "must be set to false if the policy rule uses variables that are only available in the admission review
request". Each other policy keeps the background scan. The decision and its sources: docs/reviews/2026-11-17-issue-333/.

The keys that no stanza declares (#333): for labels and for annotations, one policy refuses a key that classify() calls
disallowed, one the count of other keys over allowOther.max, and for annotations two the bytes over maxValueBytes and
maxBytesTotal. They read classify()'s own lists and its globs as metadata's regexes (`_glob_regex`), and they allow the
keys that cmapi's renderer writes on every namespace, which a request never sends. Who sent a system, operator-only or
reserved key is not on the object: those keys are allowed there, and refusing them to a requester stays cmapi's check.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping

import yaml

from cmapi.core.metadata import KINDS, KeyRule, MetadataKeys, _glob_regex, value_regex
from cmapi.core.policy import PolicySettings
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec
from cmapi.core.tiers import LIMIT_KINDS, STORAGE_KIND, TierCatalog, flatten_limits, limit_key_parts, qty

ACTIONS = {"enforce": ["Deny"], "audit": ["Audit", "Warn"]}
MANAGED = "cmapi.net/managed"
ENV_LABEL = "cmapi.net/env"
EXPIRY_KEYS = (("annotation", "cmapi.net/expires-at"), ("label", "cmapi.net/expiry"), ("label", "cleanup.kyverno.io/ttl"))
# The Namespace keys that the renderer always writes, so the bundle requires them as the hand-written
# require-team-metadata did for cmapi.net/cluster-id.
SYSTEM_REQUIRED = (("label", "cmapi.net/cluster-id"), ("label", MANAGED))
_FIELD = {"label": "labels", "annotation": "annotations"}


class PolicyGenError(ValueError):
    """The configuration cannot be rendered into a bundle that admits what cmapi itself renders."""


def cel(value: Any) -> str:
    """A CEL literal. JSON's string escapes are valid CEL escapes, and JSON lists and maps are CEL lists and maps."""
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{cel(str(k))}: {cel(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(cel(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        raise PolicyGenError("CEL strings must contain Unicode scalar values, not isolated surrogates")
    return json.dumps(text, ensure_ascii=False)


@dataclass(frozen=True)
class Check:
    """One validation: the key it checks, its rule, and its CEL."""
    kind: str                 # label | annotation | quota | limit
    key: str | None           # None: a rule over the keys that no stanza declares (#333)
    rule: str                 # required | pattern | enum | format | namespacePrefix | derived | max | min | step | order | absent
                              # | prefix | max-value-bytes | max-bytes-total
    expression: str
    message: str
    # The static message, with the key and the configured value and without the offending one. Kyverno falls back to it
    # at admission when the messageExpression fails or gives an empty or multi-line string (an annotation value may hold
    # a newline): "Kyverno falls back to the static message" (kyverno.io, ValidatingPolicy, read 2026-11-14).
    fallback: str
    variables: tuple[tuple[str, str], ...] = ()     # (name, CEL) that the expression and the message read

    @property
    def reads_old(self) -> bool:
        """The verdict depends on oldObject (the ratchet), which only an admission request has (#345). Read from the CEL
        itself, so a check cannot gain the ratchet and keep the background scan."""
        text = " ".join([self.expression, *(e for _, e in self.variables)])
        return "oldObject" in text or "variables.update" in text


def _policy(name: str, resource: str, actions: list[str], checks: list[Check], description: str,
            match: str | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"validationActions": actions}
    if any(c.reads_old for c in checks):
        # A background scan has no oldObject (#345): the policy reports at admission only.
        spec["evaluation"] = {"background": {"enabled": False}}
    spec["matchConstraints"] = {"resourceRules": [{"apiGroups": [""], "apiVersions": ["v1"],
                                                   "operations": ["CREATE", "UPDATE"], "resources": [resource]}]}
    if match:
        spec["matchConditions"] = [{"name": "cmapi-managed", "expression": match}]
    spec["variables"] = [
        # The CLI evaluates as CREATE with an empty oldObject (measured, M8), so offline every key is checked.
        {"name": "update", "expression": "request.operation == 'UPDATE' && has(oldObject.metadata)"},
        *({"name": n, "expression": e} for c in checks for n, e in c.variables),
    ]
    spec["validations"] = [{"expression": c.expression, "message": c.fallback, "messageExpression": c.message} for c in checks]
    return {"apiVersion": "policies.kyverno.io/v1", "kind": "ValidatingPolicy",
            "metadata": {"name": name, "annotations": {"policies.kyverno.io/description": description,
                                                       "cmapi.net/generated": "true"}},
            "spec": spec}


# ------------------------------------------------------------------------------------------------- Namespace metadata
def _meta(kind: str, obj: str = "object") -> str:
    f = _FIELD[kind]
    return f"(has({obj}.metadata.{f}) ? {obj}.metadata.{f} : {{}})"


def _same(kind: str, key: str) -> str:
    """The key is unchanged from oldObject on an UPDATE: present with the same value, or absent in both."""
    k, new, old = cel(key), _meta(kind), _meta(kind, "oldObject")
    return (f"(variables.update && ({k} in {new}) == ({k} in {old}) && "
            f"(!({k} in {new}) || {new}[{k}] == {old}[{k}]))")


def _value_rule(rule: KeyRule, value: str, domains: list[str]) -> tuple[str, str, str] | None:
    """(rule name, CEL that is true when the value is good, the rule in words) for a declared key's value. A pattern or
    a format is metadata.value_regex: the one string that cmapi's validator matches too, already anchored for CEL's
    matches(), which finds a match anywhere (#332)."""
    regex = value_regex(rule, domains)
    if regex is not None:
        if rule.pattern is not None:
            return "pattern", f"{value}.matches({cel(regex)})", f"must match {rule.pattern}"
        words = f"an address in {', '.join(domains)}" if rule.format == "email-in-domains" else "an http or https URL"
        return "format", f"{value}.matches({cel(regex)})", words
    if rule.enum is not None:
        return "enum", f"{value} in {cel(list(rule.enum))}", f"one of {', '.join(rule.enum)}"
    return None


def _metadata_checks(keys: MetadataKeys, env: str, instance: str) -> list[Check]:
    checks: list[Check] = []
    for kind, key in SYSTEM_REQUIRED:
        k, m = cel(key), _meta(kind)
        checks.append(Check(kind, key, "required", f"{_same(kind, key)} || ({k} in {m} && {m}[{k}] != '')",
                            cel(f"the {kind} {key} is missing: cmapi writes it on each namespace it manages"),
                            f"the {kind} {key} is missing: cmapi writes it on each namespace it manages"))
    k, m = cel(ENV_LABEL), _meta("label")
    checks.append(Check("label", ENV_LABEL, "derived", f"{_same('label', ENV_LABEL)} || ({k} in {m} && {m}[{k}] == {cel(env)})",
                        f"{cel(f'the label {ENV_LABEL} is ')} + ({k} in {m} ? {m}[{k}] : 'missing') + "
                        + cel(f"; it must be {env}, the environment of this policy"),
                        f"the label {ENV_LABEL} must be {env}, the environment of this policy"))
    constants = {"environment": env, "instance": instance}
    for kind in KINDS:
        for key, rule in keys.rules[kind].items():
            k, m = cel(key), _meta(kind)
            value = f"{m}[{k}]"
            shown = f"({k} in {m} ? '\"' + {value} + '\"' : 'missing')"
            where = f"the {kind} {key}"
            if rule.derived:
                if rule.derived == "namespace":
                    want, said = "object.metadata.name", "the namespace name"
                elif rule.derived == "cluster":
                    want, said = f"{_meta('label')}['cmapi.net/cluster-id']", "the label cmapi.net/cluster-id"
                    want = f"(('cmapi.net/cluster-id' in {_meta('label')}) ? {want} : '')"
                else:
                    want, said = cel(constants[rule.derived]), f"the {rule.derived} {constants[rule.derived]}"
                present = f"{k} in {m}"
                good = f"{present} && {value} == {want}" if rule.required else f"!({present}) || {value} == {want}"
                checks.append(Check(kind, key, "derived", f"{_same(kind, key)} || ({good})",
                                    f"{cel(where + ' is ')} + {shown} + {cel('; cmapi sets it to ' + said)}",
                                    f"{where} is not what cmapi sets it to: {said}"))
                continue
            vr = _value_rule(rule, value, keys.email_domains)
            parts = []
            if rule.required:
                parts.append(f"{k} in {m} && {value} != ''")
            if vr:
                parts.append(vr[1] if rule.required else f"(!({k} in {m}) || ({vr[1]}))")
            if rule.namespace_prefix:
                prefix = f"object.metadata.name.startsWith({value} + '-')"
                parts.append(prefix if rule.required else f"(!({k} in {m}) || {value} == '' || {prefix})")
            if not parts:
                continue
            if kind == "label":
                # The Python metadata checker enforces Kubernetes label syntax before the value rule.
                syntax = f"size({value}) <= 63 && {value}.matches({cel('^[A-Za-z0-9]([A-Za-z0-9_.-]*[A-Za-z0-9])?$')})"
                parts.append(f"(!({k} in {m}) || {value} == '' || ({syntax}))")
            words = "; ".join(w for w in ("required" if rule.required else "",
                                          vr[2] if vr else "",
                                          "the start of the namespace name, before its first '-'" if rule.namespace_prefix else "")
                              if w)
            name = "required" if rule.required and not vr and not rule.namespace_prefix else \
                (vr[0] if vr else "namespacePrefix")
            checks.append(Check(kind, key, name, f"{_same(kind, key)} || ({' && '.join(parts)})",
                                f"{cel(where + ' is ')} + {shown} + {cel('; it must be: ' + words)}",
                                f"{where} must be: {words}"))
    return checks


# ---------------------------------------------------------------------------------- the keys that no stanza declares
def _written(catalog: TierCatalog, keys: MetadataKeys, env: str, instance: str) -> dict[str, set[str]]:
    """{kind: keys} that cmapi's renderer writes on a namespace of env when the request sends none, with an expiry where
    one is allowed. validate() never sees them, so whatever class metadata-keys.yaml gives them, the policies allow them
    and never count them. Read from the renderer itself, not from a second list."""
    offered = catalog.offered(env)
    if not offered:
        return {kind: set() for kind in KINDS}
    spec = NamespaceSpec(namespace="cmapi-probe", cluster_id="cmapi-probe", instance=instance, env=env,
                         tier=offered[0].name, request_id="cmapi-probe", requested_by_user="cmapi-probe",
                         requested_by_email="cmapi-probe@example.invalid",
                         expires_at=None if env == "prod" else date(2000, 1, 1))
    files = ManifestRenderer(catalog, keys).render(spec)
    meta = yaml.safe_load(next(t for p, t in files.items() if p.endswith("/namespace.yaml") and t))["metadata"]
    return {kind: set(meta.get(_FIELD[kind]) or {}) for kind in KINDS}


def _under(globs: Iterable[str], *, exact: bool) -> str | None:
    """CEL that is true when the key k has a prefix (text before its first "/", not empty) that one of the globs matches,
    as MetadataKeys._prefix_in reads a non-empty prefix; None when no glob can match one. exact=False may match more
    keys and exact=True fewer or the same (metadata._glob_regex), so each set is bounded on the side that keeps the
    policy from refusing what cmapi accepts."""
    parts = [r for g in globs if g and (r := _glob_regex(g, exact=exact)) is not None]
    if not parts:
        return None
    return f"(!k.startsWith('/') && k.matches({cel('^(?:' + '|'.join(parts) + ')/')}))"


def _other_key_checks(keys: MetadataKeys, kind: str, written: set[str]) -> list[Check]:
    """The keys of one kind that no stanza declares (#333), as validate() reads them on the result of a request: a key
    that classify() calls disallowed, more other keys than allowOther.max, and an annotation's bytes."""
    other = keys.allow_other[kind]
    stanza = "extraLabels" if kind == "label" else "extraAnnotations"
    m = _meta(kind)
    # classify()'s order: system, operatorOnly, an adoption label, a declared key; then a reserved prefix; then allowOther.
    fixed = cel(sorted({*keys.system, *keys.operator_only, *(keys.adoption_labels if kind == "label" else ()),
                        *keys.rules[kind], *written}))
    no_prefix = "(!k.contains('/') || k.startsWith('/'))" if "" in other.prefixes else None
    shown = ", ".join(json.dumps(p + "/" if p else "") for p in other.prefixes) or "none"
    # Allowed: a wider reserved and allowOther match only admit more keys.
    allowed = " || ".join(x for x in (f"k in {fixed}", _under(keys.reserved_prefixes, exact=False),
                                       _under(other.prefixes, exact=False), no_prefix) if x)
    # Counted: allowOther exact or narrower and reserved wider, so the policy never counts a key that validate() does not.
    team = " || ".join(x for x in (_under(other.prefixes, exact=True), no_prefix) if x) or "false"
    reserved = _under(keys.reserved_prefixes, exact=False)
    counted = f"!(k in {fixed}){f' && !{reserved}' if reserved else ''} && ({team})"
    v = f"variables.{kind}Other"
    checks = [Check(kind, None, "prefix", f"size(variables.{kind}Outside) == 0",
                    f"{cel(f'the {kind} keys ')} + variables.{kind}Outside.sort().join(', ') + "
                    + cel(f" are not declared in metadata-keys.yaml, and are outside {stanza}.allowOther.prefixes "
                          f"[{shown}]"),
                    f"a {kind} key is not declared in metadata-keys.yaml, and is outside {stanza}.allowOther.prefixes "
                    f"[{shown}]",
                    ((f"{kind}Outside", f"{m}.filter(k, !({allowed}))"),)),
              Check(kind, None, "max", f"size({v}) <= {other.max}",
                    f"{cel('there are ')} + string(size({v})) + "
                    + cel(f" other {kind}s (keys under {stanza}.allowOther.prefixes); at most {other.max} "
                          f"({stanza}.allowOther.max)"),
                    f"more than {other.max} other {kind}s (keys under {stanza}.allowOther.prefixes; {stanza}.allowOther.max)",
                    ((f"{kind}Other", f"{m}.filter(k, {counted})"),))]
    if kind == "annotation":
        each, total = other.max_value_bytes or 0, other.max_bytes_total or 0
        big = f"{v}.filter(k, size(bytes({m}[k])) > {each})"
        checks.append(Check(kind, None, "max-value-bytes", f"size({big}) == 0",
                            f"{cel('the annotations ')} + {big}.sort().join(', ') + "
                            + cel(f" are over {each} bytes ({stanza}.allowOther.maxValueBytes)"),
                            f"an other annotation is over {each} bytes ({stanza}.allowOther.maxValueBytes)",
                            ((f"{kind}Other", f"{m}.filter(k, {counted})"),)))
        size_of = f"{v}.map(k, size(bytes({m}[k]))).sum()"
        checks.append(Check(kind, None, "max-bytes-total", f"{size_of} <= {total}",
                            f"{cel('the other annotations hold ')} + string({size_of}) + "
                            + cel(f" bytes; at most {total} ({stanza}.allowOther.maxBytesTotal)"),
                            f"the other annotations hold more than {total} bytes ({stanza}.allowOther.maxBytesTotal)",
                            ((f"{kind}Other", f"{m}.filter(k, {counted})"),)))
    return checks


# ------------------------------------------------------------------------------------------- ResourceQuota, LimitRange
def _quota_checks(catalog: TierCatalog, env: str) -> list[Check]:
    b = catalog.bounds(env)
    checks = []
    hard, old = "object.spec.hard", "oldObject.spec.hard"
    for key in sorted(k for k in b.max if not k.startswith("limitRange.")):
        k, mx = cel(key), cel(b.max[key])
        same = f"(variables.update && has(oldObject.spec.hard) && {k} in {old} && {k} in {hard} && quantity({hard}[{k}]).compareTo(quantity({old}[{k}])) == 0)"
        good = f"!(has(object.spec.hard) && {k} in {hard}) || quantity({hard}[{k}]).compareTo(quantity({mx})) <= 0"
        checks.append(Check("quota", key, "max", f"{same} || {good}",
                            f"{cel(key + ' ')} + (has(object.spec.hard) && {k} in {hard} ? string({hard}[{k}]) : 'missing') + "
                            + cel(f" is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift"),
                            f"{key} is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift"))
    return checks


def _limit_value(kind: str, part: str, res: str, obj: str = "object") -> str:
    """CEL for the LimitRange item of one type: its value of part.res, or '' when it has none."""
    t, items = cel(LIMIT_KINDS[kind]), f"({obj}.spec.limits)"
    return (f"has({obj}.spec.limits) && {items}.exists(i, i.type == {t} && has(i.{part}) && {cel(res)} in i.{part}) ? "
            f"{items}.filter(i, i.type == {t} && has(i.{part}) && {cel(res)} in i.{part})[0].{part}[{cel(res)}] : ''")


def _limits_checks(catalog: TierCatalog, env: str) -> list[Check]:
    b = catalog.bounds(env)
    checks = []
    storage = catalog.storage_limits(env)
    for key in sorted(k for k in b.max if k.startswith("limitRange.")):
        parts = limit_key_parts(key)
        if not parts or (parts[0] == STORAGE_KIND and not storage):
            # With the storage switch off cmapi renders no storage LimitRange, so it checks none: an adopted namespace keeps
            # its own as it is (the adoption design's D19).
            continue
        v, mx = f"({_limit_value(*parts)})", cel(b.max[key])
        was = f"(variables.update && has(oldObject.spec) ? ({_limit_value(*parts, obj='oldObject')}) : '')"
        same = f"({v} != '' && {was} != '' && quantity({v}).compareTo(quantity({was})) == 0)"
        checks.append(Check("limit", key, "max", f"{v} == '' || {same} || quantity({v}).compareTo(quantity({mx})) <= 0",
                            f"{cel(key + ' ')} + {v} + "
                            + cel(f" is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift"),
                            f"{key} is above the {env} maximum of {b.max[key]}; a bound of tiers.yaml, which approval does not lift"))
    # Limits never below requests: default not below defaultRequest, max not below default, for each container resource.
    # Structure, not a bound: never kept for a value that the object already held.
    for res in ("cpu", "memory"):
        for low, high in (("defaultRequest", "default"), ("default", "max")):
            lo, hi = f"({_limit_value('container', low, res)})", f"({_limit_value('container', high, res)})"
            key = f"limitRange.container.{high}.{res}"
            checks.append(Check("limit", key, "order",
                                f"{lo} == '' || {hi} == '' || quantity({hi}).compareTo(quantity({lo})) >= 0",
                                f"{cel(f'container {high} {res} ')} + {hi} + {cel(f' is below its {low} ')} + {lo}",
                                f"container {high} {res} is below its {low}"))
    return checks


def _expiry_checks() -> list[Check]:
    out = []
    for kind, key in EXPIRY_KEYS:
        out.append(Check(kind, key, "absent", f"!({cel(key)} in {_meta(kind)})",
                         "'Production namespaces never expire: remove cmapi.net/expires-at, cmapi.net/expiry "
                         "and cleanup.kyverno.io/ttl.'",
                         "Production namespaces never expire: remove cmapi.net/expires-at, cmapi.net/expiry "
                         "and cleanup.kyverno.io/ttl."))
    return out


# -------------------------------------------------------------------------------------------------- the bundle
_MANAGED_NS = (f"({cel(MANAGED)} in {_meta('label')} && {_meta('label')}[{cel(MANAGED)}] == 'true') || "
               f"(request.operation == 'UPDATE' && has(oldObject.metadata) && {cel(MANAGED)} in {_meta('label', 'oldObject')} && "
               f"{_meta('label', 'oldObject')}[{cel(MANAGED)}] == 'true')")
_IN_MANAGED = _MANAGED_NS     # ResourceQuota and LimitRange carry cmapi.net/managed too (tiers.render)


def _check_offered(catalog: TierCatalog, env: str) -> None:
    """A named tier above the environment's maximum would be refused at admission: refuse the configuration instead."""
    b = catalog.bounds(env)
    problems = []
    for r in catalog.offered(env):
        values = {**r.quota, **flatten_limits(r.limit_range)}
        for k, v in values.items():
            if k in b.max and qty(v) > qty(b.max[k]):
                problems.append(f"tier {r.name} in {env}: {k} {v} is above the maximum {b.max[k]}")
    if problems:
        raise PolicyGenError("the rendered policies would refuse a tier that cmapi offers: " + "; ".join(problems))


def _env_files(catalog: TierCatalog, keys: MetadataKeys, env: str, instance: str, actions: list[str]) -> dict[str, str]:
    _check_offered(catalog, env)
    written = _written(catalog, keys, env, instance)
    metadata = _metadata_checks(keys, env, instance) + [c for kind in KINDS for c in _other_key_checks(keys, kind, written[kind])]
    families = [
        (f"cmapi-metadata-{env}", "namespaces", metadata, _MANAGED_NS,
         f"The labels and annotations that metadata-keys.yaml requires of a managed namespace in {env}."),
        (f"cmapi-quota-{env}", "resourcequotas", _quota_checks(catalog, env), _IN_MANAGED,
         f"Each ResourceQuota key of a managed namespace at or below the {env} maximum of tiers.yaml."),
        (f"cmapi-limits-{env}", "limitranges", _limits_checks(catalog, env), _IN_MANAGED,
         f"Each LimitRange value of a managed namespace at or below the {env} maximum; limits never below requests."),
    ]
    if env == "prod":
        families.append(("deny-expiry-in-prod", "namespaces", _expiry_checks(), None,
                         "Production namespaces never carry expiration metadata."))
    files: dict[str, str] = {}
    index: dict[str, dict[str, str | None]] = {}
    for family, resource, checks, match, description in families:
        if not checks:
            continue
        if family == "deny-expiry-in-prod":
            # One policy, as the hand-written one was: no value is approved for it, so nothing ratchets.
            docs = [_policy(family, resource, actions, checks, description, match)]
            index[family] = {"kind": "label", "key": None, "rule": "absent"}
        else:
            # One policy for each check: Kyverno reports only the first failed validation of a policy (measured, M9),
            # and cmapi must see every failed key to drop only those whose value Git already holds.
            docs = []
            for c in checks:
                name = f"{family}-{c.kind}-{_slug(c.key) if c.key else 'other-keys'}-{c.rule.lower()}"
                if name in index:
                    raise PolicyGenError(f"two checks render the policy name {name}")
                docs.append(_policy(name, resource, actions, [c], description, match))
                index[name] = {"kind": c.kind, "key": c.key, "rule": c.rule}
        files[f"env/{env}/{family}.yaml"] = _yaml_all(docs)
    files[f"env/{env}/index.json"] = json.dumps(index, indent=2, sort_keys=True) + "\n"
    return files


def render_bundle(catalog: TierCatalog, keys: MetadataKeys, policy: PolicySettings, environments: Iterable[str],
                  instance: str) -> dict[str, str]:
    """The bundle of one instance: the files of each environment whose mode is not off, by relative path."""
    out: dict[str, str] = {}
    for env in sorted(environments):
        mode = policy.mode_for(env)
        if mode == "off":
            continue
        out.update(_env_files(catalog, keys, env, instance, ACTIONS[mode]))
    return out


_HEADER = ("# Rendered by cmapi from its configuration (core/policygen.py, #212). Do not edit: change tiers.yaml,\n"
           "# metadata-keys.yaml or instance.yaml policy, and render again (cmapi-tools policies render).\n")


def _yaml_all(docs: list[Mapping[str, Any]]) -> str:
    return _HEADER + yaml.safe_dump_all([dict(d) for d in docs], sort_keys=False, width=1000)


def _slug(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


def index_of(files: Mapping[str, str]) -> dict[str, dict[str, str | None]]:
    """Policy name -> {kind, key, rule}, from the index.json files of a bundle."""
    out: dict[str, dict[str, str | None]] = {}
    for path, text in files.items():
        if path.endswith("/index.json"):
            out.update(json.loads(text))
    return out


_ENV_PATH = re.compile(r"^env/([^/]+)/")


def environment_of(path: str) -> str | None:
    m = _ENV_PATH.match(path)
    return m.group(1) if m else None
