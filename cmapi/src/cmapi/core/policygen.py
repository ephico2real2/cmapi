"""The Kyverno bundle, rendered from cmapi's own configuration (#212; docs/reviews/2026-11-14-issue-212/).

    render_bundle(catalog, keys, policy, environments, instance) -> {relative path: YAML or JSON text}

    env/<env>/cmapi-metadata.yaml     Namespace: the required and declared keys of metadata-keys.yaml (#215)
    env/<env>/cmapi-quota.yaml        ResourceQuota: each key at or below the environment's maximum (tiers.yaml)
    env/<env>/cmapi-limits.yaml       LimitRange: each key at or below its maximum; limits never below requests
    env/prod/deny-expiry-in-prod.yaml Namespace: production never expires (the hand-written policy, rendered)
    env/<env>/index.json              policy name -> the key and rule that the policy checks

Every value is written into the policy as a CEL literal, so the CLI at plan time, CI and admission give one answer with
no cluster lookup (docs/02, "Keeping it offline"). Each validation checks one key, and its message names the key, the
offending value and the configured value. Each check is its own policy, because Kyverno reports only the first failed
validation of a policy. An environment whose mode is off gets no files; audit renders
`[Audit, Warn]`, enforce `[Deny]` (#213).

A value that the object already held is not checked again: at admission an UPDATE whose key keeps its oldObject value
passes, and at plan time cmapi drops a failure on a key whose value Git already holds (core/validate). The bounds of
tiers.py do the same (`_out_of_bounds`), so a later, lower bound never refuses an approved namespace.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import yaml

from cmapi.core.metadata import KINDS, KeyRule, MetadataKeys
from cmapi.core.policy import PolicySettings
from cmapi.core.tiers import LIMIT_KINDS, TierCatalog, flatten_limits, limit_key_parts, qty

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
    return json.dumps(str(value))


@dataclass(frozen=True)
class Check:
    """One validation: the key it checks, its rule, and its CEL."""
    kind: str                 # label | annotation | quota | limit
    key: str
    rule: str                 # required | pattern | enum | format | namespacePrefix | derived | max | min | step | order | absent
    expression: str
    message: str


def _policy(name: str, resource: str, actions: list[str], checks: list[Check], description: str,
            match: str | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "validationActions": actions,
        "matchConstraints": {"resourceRules": [{"apiGroups": [""], "apiVersions": ["v1"],
                                                "operations": ["CREATE", "UPDATE"], "resources": [resource]}]},
    }
    if match:
        spec["matchConditions"] = [{"name": "cmapi-managed", "expression": match}]
    spec["variables"] = [
        # The CLI evaluates as CREATE with an empty oldObject (measured, M8), so offline every key is checked.
        {"name": "update", "expression": "request.operation == 'UPDATE' && has(oldObject.metadata)"},
    ]
    spec["validations"] = [{"expression": c.expression, "messageExpression": c.message} for c in checks]
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
    """(rule name, CEL that is true when the value is good, the rule in words) for a declared key's value."""
    if rule.pattern is not None:
        # Python checks with re.fullmatch; CEL's matches() finds a match anywhere, so the pattern is anchored.
        return "pattern", f"{value}.matches({cel('^(?:' + rule.pattern + ')$')})", f"must match {rule.pattern}"
    if rule.enum is not None:
        return "enum", f"{value} in {cel(list(rule.enum))}", f"one of {', '.join(rule.enum)}"
    if rule.format == "email-in-domains":
        # core/identity/checks.py email_in_domains: one "@", a local part of the allowed characters, a listed domain.
        local = r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$"
        return ("format",
                f"size({value}.split('@')) == 2 && {value}.split('@')[0].matches({cel(local)}) && "
                f"{value}.split('@')[1].lowerAscii() in {cel([d.lower() for d in domains])}",
                f"an address in {', '.join(domains)}")
    if rule.format == "url":
        return ("format",
                f"isURL({value}) && url({value}).getScheme() in ['http', 'https'] && url({value}).getHost() != '' && "
                f"!{value}.matches('\\\\s')",
                "an http or https URL")
    return None


def _metadata_checks(keys: MetadataKeys, env: str, instance: str) -> list[Check]:
    checks: list[Check] = []
    for kind, key in SYSTEM_REQUIRED:
        k, m = cel(key), _meta(kind)
        checks.append(Check(kind, key, "required", f"{_same(kind, key)} || ({k} in {m} && {m}[{k}] != '')",
                            f"'the {kind} {key} is missing: cmapi writes it on each namespace it manages'"))
    k, m = cel(ENV_LABEL), _meta("label")
    checks.append(Check("label", ENV_LABEL, "derived", f"{_same('label', ENV_LABEL)} || ({k} in {m} && {m}[{k}] == {cel(env)})",
                        f"'the label {ENV_LABEL} is ' + ({k} in {m} ? {m}[{k}] : 'missing') + "
                        f"'; it must be {env}, the environment of this policy'"))
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
                                    f"'{where} is ' + {shown} + '; cmapi sets it to {said}'"))
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
            words = "; ".join(w for w in ("required" if rule.required else "",
                                          vr[2] if vr else "",
                                          "the start of the namespace name, before its first '-'" if rule.namespace_prefix else "")
                              if w)
            name = "required" if rule.required and not vr and not rule.namespace_prefix else \
                (vr[0] if vr else "namespacePrefix")
            checks.append(Check(kind, key, name, f"{_same(kind, key)} || ({' && '.join(parts)})",
                                f"'{where} is ' + {shown} + {cel('; it must be: ' + words)}"))
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
                            f"'{key} ' + string({hard}[{k}]) + ' is above the {env} maximum of {b.max[key]}; "
                            f"a bound of tiers.yaml, which approval does not lift'"))
    return checks


def _limit_value(kind: str, part: str, res: str, obj: str = "object") -> str:
    """CEL for the LimitRange item of one type: its value of part.res, or '' when it has none."""
    t, items = cel(LIMIT_KINDS[kind]), f"({obj}.spec.limits)"
    return (f"has({obj}.spec.limits) && {items}.exists(i, i.type == {t} && has(i.{part}) && {cel(res)} in i.{part}) ? "
            f"{items}.filter(i, i.type == {t} && has(i.{part}) && {cel(res)} in i.{part})[0].{part}[{cel(res)}] : ''")


def _limits_checks(catalog: TierCatalog, env: str) -> list[Check]:
    b = catalog.bounds(env)
    checks = []
    for key in sorted(k for k in b.max if k.startswith("limitRange.")):
        parts = limit_key_parts(key)
        if not parts:
            continue
        v, mx = f"({_limit_value(*parts)})", cel(b.max[key])
        was = f"(variables.update && has(oldObject.spec) ? ({_limit_value(*parts, obj='oldObject')}) : '')"
        same = f"({v} != '' && {was} != '' && quantity({v}).compareTo(quantity({was})) == 0)"
        checks.append(Check("limit", key, "max", f"{v} == '' || {same} || quantity({v}).compareTo(quantity({mx})) <= 0",
                            f"'{key} ' + {v} + ' is above the {env} maximum of {b.max[key]}; "
                            f"a bound of tiers.yaml, which approval does not lift'"))
    # Limits never below requests: default not below defaultRequest, max not below default, for each container resource.
    # Structure, not a bound: never kept for a value that the object already held.
    for res in ("cpu", "memory"):
        for low, high in (("defaultRequest", "default"), ("default", "max")):
            lo, hi = f"({_limit_value('container', low, res)})", f"({_limit_value('container', high, res)})"
            key = f"limitRange.container.{high}.{res}"
            checks.append(Check("limit", key, "order",
                                f"{lo} == '' || {hi} == '' || quantity({hi}).compareTo(quantity({lo})) >= 0",
                                f"'container {high} {res} ' + {hi} + ' is below its {low} ' + {lo}"))
    return checks


def _expiry_checks() -> list[Check]:
    out = []
    for kind, key in EXPIRY_KEYS:
        out.append(Check(kind, key, "absent", f"!({cel(key)} in {_meta(kind)})",
                         "'Production namespaces never expire: remove cmapi.net/expires-at, cmapi.net/expiry "
                         "and cleanup.kyverno.io/ttl.'"))
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
    families = [
        (f"cmapi-metadata-{env}", "namespaces", _metadata_checks(keys, env, instance), _MANAGED_NS,
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
                name = f"{family}-{c.kind}-{_slug(c.key)}-{c.rule.lower()}"
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
