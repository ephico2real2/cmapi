"""Tier catalog for cmapi: config/tiers.yaml in, ResourceQuota and LimitRange out.

Reference implementation for docs/02-technical-design-v2.md, "Tiers". The planner calls
resolve()/quota_for() and compare(); core/render/manifests.py calls render(); the tiers plugin
serves describe(); the quota view and the tiers-rerender operation call is_outdated().

Nothing here talks to a cluster, Git or Keycloak. Pure functions over one loaded catalog, so the
same answer comes back at plan time, at commit time and in tests.

A custom-tier request can also change each key of `overridable` (docs/reviews/2026-11-14-issue-211): a quota key by its
Kubernetes name, a LimitRange value as limitRange.<kind>.<part>.<resource>. A value that differs from the tier is "beyond
the tier": beyond() lists it for the approval rules, and render() records it in the annotation cmapi.net/beyond-tier.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict

# --------------------------------------------------------------------------- quantities

_SUFFIX = {
    "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"), "": Decimal(1),
    "k": Decimal(10) ** 3, "M": Decimal(10) ** 6, "G": Decimal(10) ** 9, "T": Decimal(10) ** 12,
    "P": Decimal(10) ** 15, "E": Decimal(10) ** 18,
    "Ki": Decimal(2) ** 10, "Mi": Decimal(2) ** 20, "Gi": Decimal(2) ** 30,
    "Ti": Decimal(2) ** 40, "Pi": Decimal(2) ** 50, "Ei": Decimal(2) ** 60,
}
_QTY = re.compile(r"^\+?([0-9]+(?:\.[0-9]*)?|\.[0-9]+)(Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E|[eE][+-]?[0-9]+)?$")
_NANO = Decimal("1e-9")


def qty(value: str | int | float) -> Decimal:
    """Parse a Kubernetes quantity ("500m", "16", "32Gi", "4e0") to a Decimal in base units, as the API server reads it.

    Two values that this function gives as equal are one amount for Kubernetes, and no others are: the approval of a value
    beyond the tier depends on it. So no digit is lost in the multiplication (Decimal's default is 28 digits), and a fraction
    below one nano-unit is rounded up, as apimachinery's ParseQuantity does ("2.0000000000000000000000000001" is 2000000001n).
    """
    m = _QTY.fullmatch(str(value).strip())
    if not m:
        raise ValueError(f"not a Kubernetes quantity: {value!r}")
    suffix = m.group(2) or ""
    if len(suffix) > 1 and suffix[0] in "eE" and suffix[1] != "i":          # a decimal exponent, not the suffix E or Ei
        amount = Decimal(m.group(1) + suffix)
    else:
        number, factor = Decimal(m.group(1)), _SUFFIX[suffix]
        with localcontext() as exact:
            exact.prec = max(28, len(number.as_tuple().digits) + len(factor.as_tuple().digits))
            amount = number * factor
    with localcontext() as exact:
        exact.prec = max(28, len(amount.as_tuple().digits), amount.adjusted() + 10)
        return amount.quantize(_NANO, rounding=ROUND_CEILING)


# --------------------------------------------------------------------------- limit keys

LIMIT_PREFIX = "limitRange."
LIMIT_KINDS = {"container": "Container", "pvc": "PersistentVolumeClaim"}
LIMIT_PARTS = ("min", "defaultRequest", "default", "max")       # the order that a container resource must keep
BEYOND_TIER = "cmapi.net/beyond-tier"
# A higher count of these two quota keys opens a path into the cluster (a port on each node, an external load balancer).
EXPOSURE_KEYS = frozenset({"services.loadbalancers", "services.nodeports"})

LimitRange = dict[str, dict[str, dict[str, str]]]


def is_limit_key(key: str) -> bool:
    return key.startswith(LIMIT_PREFIX)


def limit_key_parts(key: str) -> tuple[str, str, str] | None:
    """limitRange.container.max.cpu -> (container, max, cpu). None when the key does not have that form."""
    parts = key.removeprefix(LIMIT_PREFIX).split(".", 2) if is_limit_key(key) else []
    if len(parts) == 3 and parts[0] in LIMIT_KINDS and parts[1] in LIMIT_PARTS and parts[2]:
        return parts[0], parts[1], parts[2]
    return None


def flatten_limits(limits: Mapping[str, Mapping[str, Mapping[str, str]]] | None) -> dict[str, str]:
    """{"container": {"max": {"cpu": "4"}}} -> {"limitRange.container.max.cpu": "4"}."""
    return {f"{LIMIT_PREFIX}{kind}.{part}.{res}": str(v)
            for kind, parts in (limits or {}).items() for part, vals in parts.items() for res, v in vals.items()}


def _same(a: str | None, b: str | None) -> bool:
    """Two quantities are the same amount: "1" and "1000m" are, a missing value and a value are not."""
    return (a is None and b is None) or (a is not None and b is not None and qty(a) == qty(b))


def _unequal_fixed_defaults(parts: Mapping[str, Mapping[str, str]]) -> list[str]:
    """The resources of one limit kind whose default differs from its defaultRequest, and that Kubernetes does not let differ.

    ValidateLimitRange refuses the object for a resource that cannot overcommit: an extended resource (nvidia.com/gpu) or huge
    pages. IsOvercommitAllowed is true only for a native resource (no "/", or a kubernetes.io/ name) that is not hugepages-*.
    """
    defaults, requests = parts.get("default", {}), parts.get("defaultRequest", {})
    return sorted(res for res in defaults.keys() & requests.keys()
                  if (res.startswith("hugepages-") or ("/" in res and "kubernetes.io/" not in res))
                  and not _same(defaults[res], requests[res]))


# --------------------------------------------------------------------------- errors


class TierError(ValueError):
    """A request-time refusal. code becomes errors[].code in a 422 policy-violation."""

    def __init__(self, code: str, detail: str, **data: Any):
        super().__init__(detail)
        self.code, self.detail, self.data = code, detail, data


class CatalogError(ValueError):
    """The catalog file is invalid. At startup cmapi refuses to start; on reload it keeps the
    running catalog, logs every problem and sets cmapi_tier_catalog_reload_failed to 1."""

    def __init__(self, problems: list[str]):
        super().__init__("invalid tier catalog:\n  " + "\n  ".join(problems))
        self.problems = problems


# --------------------------------------------------------------------------- file schema


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TierDef(_Strict):
    order: int
    description: str = ""
    custom: bool = False
    quota: dict[str, str] = {}
    limitRange: dict[str, dict[str, dict[str, str]]] = {}


class Bounds(_Strict):
    min: dict[str, str] = {}
    max: dict[str, str] = {}
    step: dict[str, str] = {}


class EnvDef(_Strict):
    inherit: str | None = None
    offered: list[str] | None = None
    tiers: dict[str, dict[str, Any]] = {}      # partial {quota, limitRange} per tier
    custom: dict[str, dict[str, str]] = {}     # partial Bounds


class CatalogFile(_Strict):
    apiVersion: Literal["cmapi.net/v1"]
    kind: Literal["TierCatalog"]
    sizable: list[str]
    overridable: list[str] = []                # more keys that a custom-tier request can change, each with a custom.max
    defaults: dict[str, Any] = {}
    tiers: dict[str, TierDef]
    custom: Bounds = Bounds()
    environments: dict[str, EnvDef]


# --------------------------------------------------------------------------- resolved values


@dataclass(frozen=True)
class ResolvedTier:
    environment: str
    name: str
    order: int
    description: str
    custom: bool
    quota: dict[str, str]                       # for custom: only the non-sizable keys
    limit_range: dict[str, dict[str, dict[str, str]]]
    hash: str                                   # rendered as cmapi.net/tier-hash

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "order": self.order, "description": self.description,
                "custom": self.custom, "hash": self.hash, "quota": dict(self.quota),
                "limitRange": copy.deepcopy(self.limit_range)}


@dataclass(frozen=True)
class QuotaChange:
    """Facts the approval engine and the capacity check receive for a tier or quota change."""
    tier_change: Literal["up", "down", "same", "to-custom", "from-custom", "custom"]
    increase_pct: dict[str, float]               # per sizable key, negative for a decrease
    delta: dict[str, Decimal]                    # per sizable key, in base units
    below_used: list[str] = field(default_factory=list)   # keys whose new hard < what pods request now (quota used)

    @property
    def quota_increase_pct(self) -> float:      # the fact approval-rules.yaml thresholds read
        return max(self.increase_pct.values(), default=0.0)

    def facts(self) -> dict[str, Any]:
        """The approval facts, named as approval-rules.yaml reads them."""
        return {"tierChange": self.tier_change, "quotaIncreasePct": self.quota_increase_pct,
                "quotaBelowRequested": bool(self.below_used)}


# --------------------------------------------------------------------------- catalog


def _merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(base))
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, Mapping) and isinstance(out.get(k), Mapping) else copy.deepcopy(v)
    return out


def _digest(obj: Any, n: int = 12) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:n]


class TierCatalog:
    """One loaded, validated config/tiers.yaml for one instance."""

    def __init__(self, raw: Mapping[str, Any], allowed_environments: set[str]):
        self.file = CatalogFile.model_validate(raw)
        self.allowed = set(allowed_environments)
        self.catalog_hash = _digest(raw, 16)     # ETag of GET /api/v1/tiers
        self._env: dict[str, EnvDef] = {}
        self._resolved: dict[tuple[str, str], ResolvedTier] = {}
        self._bounds: dict[str, Bounds] = {}
        problems = self._build()
        if problems:
            raise CatalogError(problems)

    @classmethod
    def load(cls, path: str | Path, allowed_environments: set[str]) -> "TierCatalog":
        return cls(yaml.safe_load(Path(path).read_text()), allowed_environments)

    # ---- build and validate everything once, so requests never meet a bad catalog
    def _effective_env(self, env: str, seen: tuple[str, ...] = ()) -> EnvDef:
        if env in seen:
            raise CatalogError([f"environments: inherit loop {' -> '.join(seen + (env,))}"])
        d = self.file.environments[env]
        if not d.inherit:
            return d
        if d.inherit not in self.file.environments:
            raise CatalogError([f"environments.{env}: inherits unknown environment {d.inherit}"])
        parent = self._effective_env(d.inherit, seen + (env,))
        return EnvDef(offered=d.offered or parent.offered,
                      tiers=_merge(parent.tiers, d.tiers), custom=_merge(parent.custom, d.custom))

    def _build(self) -> list[str]:
        p: list[str] = []
        f = self.file
        sizable = set(f.sizable)
        overridable = set(f.overridable)
        bounded = sizable | overridable
        for k in f.overridable:
            if k in sizable:
                p.append(f"overridable: {k} is already sizable")
            elif is_limit_key(k) and limit_key_parts(k) is None:
                p.append(f"overridable: {k} is not limitRange.<{'|'.join(LIMIT_KINDS)}>.<{'|'.join(LIMIT_PARTS)}>.<resource>")
        if len(overridable) != len(f.overridable):
            p.append("overridable: a key is listed more than once")
        extra = set(f.environments) - self.allowed
        missing = self.allowed - set(f.environments)
        if extra:
            p.append(f"environments not served by this instance: {sorted(extra)}")
        if missing:
            p.append(f"allowedEnvironments without an entry: {sorted(missing)}")
        customs = [n for n, t in f.tiers.items() if t.custom]
        if len(customs) > 1:
            p.append(f"more than one custom tier: {customs}")
        orders = [t.order for t in f.tiers.values()]
        if len(set(orders)) != len(orders):
            p.append("tiers: order values must be unique")
        if p:
            return p

        for env in sorted(f.environments):
            try:
                e = self._effective_env(env)
            except CatalogError as exc:
                p.extend(exc.problems)
                continue
            self._env[env] = e
            offered = e.offered or list(f.tiers)
            for name in offered:
                if name not in f.tiers:
                    p.append(f"environments.{env}.offered: unknown tier {name}")
            for name in e.tiers:
                if name not in f.tiers:
                    p.append(f"environments.{env}.tiers: unknown tier {name}")

            # bounds for custom values
            b = Bounds.model_validate(_merge(f.custom.model_dump(), e.custom))
            self._bounds[env] = b
            bounds_before = len(p)
            for part in ("min", "max", "step"):
                for k, v in getattr(b, part).items():
                    if k not in bounded:
                        p.append(f"{env}: custom.{part}.{k} is not a sizable or overridable key")
                    try:
                        qty(v)
                    except ValueError as exc:
                        p.append(f"{env}: custom.{part}.{k}: {exc}")
            if len(p) > bounds_before:              # a value that is not a quantity: the comparisons below cannot run
                continue
            for k in sorted(bounded):
                if k in b.min and k in b.max and qty(b.min[k]) > qty(b.max[k]):
                    p.append(f"{env}: custom.min.{k} above custom.max.{k}")
                if k in b.step and qty(b.step[k]) > 0:
                    for part in ("min", "max"):
                        if k in getattr(b, part) and qty(getattr(b, part)[k]) % qty(b.step[k]) != 0:
                            p.append(f"{env}: custom.{part}.{k} is not a multiple of custom.step.{k}")

            # each tier, resolved
            for name in offered:
                if name not in f.tiers:
                    continue
                t = f.tiers[name]
                spec = _merge(f.defaults, {"quota": t.quota, "limitRange": t.limitRange})
                spec = _merge(spec, e.tiers.get(name, {}))
                quota, lr = spec.get("quota", {}), spec.get("limitRange", {})
                where = f"{env}/{name}"
                before = len(p)
                for k, v in quota.items():
                    try:
                        qty(v)
                    except ValueError as exc:
                        p.append(f"{where}: quota.{k}: {exc}")
                for kind, parts in lr.items():
                    if kind not in ("container", "pvc"):
                        p.append(f"{where}: limitRange.{kind} must be container or pvc")
                    for part, vals in parts.items():
                        if part not in ("min", "max", "default", "defaultRequest"):
                            p.append(f"{where}: limitRange.{kind}.{part} is not supported")
                        for k, v in vals.items():
                            try:
                                qty(v)
                            except ValueError as exc:
                                p.append(f"{where}: limitRange.{kind}.{part}.{k}: {exc}")
                if len(p) > before:
                    continue
                for kind, parts in lr.items():
                    for res in _unequal_fixed_defaults(parts):
                        p.append(f"{where}: {kind} {res} defaultRequest must equal default: the resource cannot overcommit")
                if t.custom:
                    if sizable & set(quota):
                        p.append(f"{where}: a custom tier cannot fix sizable keys {sorted(sizable & set(quota))}")
                    tier_values = {**quota, **flatten_limits(lr)}
                    for k in sorted(overridable):
                        # Without a max, each value would be valid, and the approval would be the only bound.
                        if k not in b.max:
                            p.append(f"{env}: custom.max.{k} missing: each overridable key needs a maximum")
                        elif k in tier_values and not (qty(b.min.get(k, "0")) <= qty(tier_values[k]) <= qty(b.max[k])):
                            p.append(f"{where}: the tier's own {k} ({tier_values[k]}) is outside the custom bounds")
                else:
                    for k in sizable - set(quota):
                        p.append(f"{where}: quota.{k} missing")
                c = lr.get("container", {})
                for r in ("cpu", "memory"):
                    chain = [c.get(x, {}).get(r) for x in ("min", "defaultRequest", "default", "max")]
                    vals = [qty(v) for v in chain if v is not None]
                    if vals != sorted(vals):
                        p.append(f"{where}: container {r} must be min <= defaultRequest <= default <= max")
                    mx = c.get("max", {}).get(r)
                    if mx is None:
                        continue
                    limit_key = f"requests.{r}"
                    floor = b.min.get(limit_key) if t.custom else quota.get(limit_key)
                    if floor is not None and qty(mx) > qty(floor):
                        p.append(f"{where}: container max {r} {mx} exceeds "
                                 f"{'custom.min' if t.custom else 'quota'} {limit_key} {floor}: "
                                 "one container at its limit would not fit")
                self._resolved[(env, name)] = ResolvedTier(
                    environment=env, name=name, order=t.order, description=t.description,
                    custom=t.custom, quota=dict(quota), limit_range=lr,
                    hash=_digest({"quota": quota, "limitRange": lr}))

            # sizes must grow with order, per sizable key
            ladder = sorted((r for (en, _), r in self._resolved.items() if en == env and not r.custom),
                            key=lambda r: r.order)
            for lo, hi in zip(ladder, ladder[1:]):
                for k in sizable:
                    if qty(hi.quota[k]) <= qty(lo.quota[k]):
                        p.append(f"{env}: {hi.name}.{k} ({hi.quota[k]}) not above {lo.name}.{k} ({lo.quota[k]})")
        return p

    # ---- lookups
    @property
    def sizable(self) -> list[str]:
        return list(self.file.sizable)

    @property
    def overridable_quota(self) -> list[str]:
        return [k for k in self.file.overridable if not is_limit_key(k)]

    @property
    def overridable_limits(self) -> list[str]:
        return [k for k in self.file.overridable if is_limit_key(k)]

    def environments(self) -> list[str]:
        return sorted(self._env)

    def offered(self, env: str) -> list[ResolvedTier]:
        return sorted((r for (e, _), r in self._resolved.items() if e == env), key=lambda r: r.order)

    def bounds(self, env: str) -> Bounds:
        self._need_env(env)
        return self._bounds[env]

    def resolve(self, env: str, tier: str) -> ResolvedTier:
        self._need_env(env)
        if tier not in self.file.tiers:
            raise TierError("tier-unknown", f"No tier named {tier}", tier=tier,
                            offered=[r.name for r in self.offered(env)])
        r = self._resolved.get((env, tier))
        if r is None:
            raise TierError("tier-not-offered", f"Tier {tier} is not offered in {env}", tier=tier,
                            offered=[r.name for r in self.offered(env)])
        return r

    def _need_env(self, env: str) -> None:
        if env not in self._env:
            raise TierError("environment-not-served", f"Environment {env} is not served by this instance",
                            environment=env, served=self.environments())

    # ---- request-time checks
    def _out_of_bounds(self, env: str, values: Mapping[str, str], approved: Mapping[str, str]) -> list[dict[str, Any]]:
        """The values outside the environment's bounds or off their step. A value that Git already holds (approved) is not
        checked again: a later, lower bound must not refuse a change of a label on a namespace that was approved before it."""
        b, bad = self.bounds(env), []
        for k in sorted(values):
            if k in approved and _same(values[k], approved[k]):
                continue
            v = qty(values[k])
            lo, hi, st = (qty(x) if x is not None else None for x in (b.min.get(k), b.max.get(k), b.step.get(k)))
            if (lo is not None and v < lo) or (hi is not None and v > hi) or (st and v % st != 0):
                bad.append({"key": k, "value": values[k], "min": b.min.get(k), "max": b.max.get(k), "step": b.step.get(k)})
        return bad

    def quota_for(self, env: str, tier: str, hard: Mapping[str, str] | None = None,
                  approved: Mapping[str, str] | None = None) -> dict[str, str]:
        """The full spec.hard to render. A named tier takes no hard values. A custom tier needs every sizable key and can
        send overridable quota keys; each is within the environment's bounds and on its step. approved: the values that
        the namespace has in Git, which are not checked against the bounds again."""
        r = self.resolve(env, tier)
        hard = {k: str(v) for k, v in (hard or {}).items()}
        if not r.custom:
            if hard:
                raise TierError("quota-with-named-tier",
                                f"Tier {tier} fixes its quota; send tier: custom to size it yourself",
                                tier=tier)
            return dict(r.quota)
        approved = approved or {}
        allowed = [*self.sizable, *self.overridable_quota]
        # A value that Git holds stays valid when the catalog no longer names its key: the approval stands until a change.
        not_sizable = sorted(k for k in set(hard) - set(allowed) if not _same(hard[k], approved.get(k)))
        if not_sizable:
            raise TierError("quota-key-not-sizable", f"Only {allowed} can be requested",
                            keys=not_sizable, sizable=self.sizable, overridable=self.overridable_quota)
        missing = [k for k in self.sizable if k not in hard]
        if missing:
            raise TierError("custom-quota-required", "A custom tier needs every sizable key",
                            missing=missing)
        bad = self._out_of_bounds(env, hard, approved)
        if bad:
            raise TierError("custom-out-of-bounds",
                            f"Custom quota outside {env}'s bounds", items=bad)
        return {**r.quota, **hard}

    def limits_for(self, env: str, tier: str, limits: Mapping[str, Mapping[str, Mapping[str, str]]] | None,
                   hard: Mapping[str, str], approved: Mapping[str, str] | None = None) -> LimitRange:
        """The full LimitRange values to render: the tier's, with the request's overridable values over them.

        A named tier takes no limits. On a custom tier each requested key is overridable and within the bounds; then, for
        each container resource, min <= defaultRequest <= default <= max, and max fits the requests.<resource> of hard.
        approved: the flat limit values that the namespace has in Git, which are not checked against the bounds again."""
        r = self.resolve(env, tier)
        asked = flatten_limits(limits)
        if not r.custom:
            if asked:
                raise TierError("limits-with-named-tier",
                                f"Tier {tier} fixes its container limits; send tier: custom to set them yourself", tier=tier)
            return copy.deepcopy(r.limit_range)
        approved = approved or {}
        not_overridable = sorted(k for k in set(asked) - set(self.overridable_limits)
                                 if limit_key_parts(k) is None or not _same(asked[k], approved.get(k)))
        if not_overridable:
            raise TierError("limit-key-not-overridable", f"Only {self.overridable_limits} can be requested",
                            keys=not_overridable, overridable=self.overridable_limits)
        bad = self._out_of_bounds(env, asked, approved)
        if bad:
            raise TierError("custom-out-of-bounds", f"Custom limits outside {env}'s bounds", items=bad)
        out = copy.deepcopy(r.limit_range)
        for key, value in asked.items():
            kind, part, res = limit_key_parts(key)        # type: ignore[misc]  # overridable keys were checked at load
            out.setdefault(kind, {}).setdefault(part, {})[res] = value
        for kind in sorted(out):
            unequal = _unequal_fixed_defaults(out[kind])
            if unequal:
                raise TierError("limit-order-invalid", f"{LIMIT_KINDS[kind]} {unequal} cannot overcommit: defaultRequest must "
                                "equal default", kind=kind, resources=unequal)
            for res in sorted({res for vals in out[kind].values() for res in vals}):
                chain = {part: out[kind][part][res] for part in LIMIT_PARTS if res in out[kind].get(part, {})}
                if [qty(v) for v in chain.values()] != sorted(qty(v) for v in chain.values()):
                    raise TierError("limit-order-invalid", f"{LIMIT_KINDS[kind]} {res} must be {' <= '.join(LIMIT_PARTS)}",
                                    kind=kind, resource=res, values=chain)
        container = out.get("container", {})
        for res in sorted(container.get("max", {})):
            chain = {"max": container["max"][res]}
            quota_key = f"requests.{res}"
            if quota_key in hard and qty(chain["max"]) > qty(hard[quota_key]):
                raise TierError("limit-exceeds-quota",
                                f"Container max {res} {chain['max']} is above the namespace's {quota_key} {hard[quota_key]}: "
                                "one container at its limit would not fit", resource=res, max=chain["max"],
                                quota=hard[quota_key])
        return out

    def beyond(self, env: str, tier: str, hard: Mapping[str, str],
               limit_range: Mapping[str, Mapping[str, Mapping[str, str]]]) -> dict[str, dict[str, str | None]]:
        """Each value that differs from the tier's, the sizable keys apart: key -> {"tier": the tier's value, "requested":
        the value}. In the order of `overridable`; a key that the catalog named before and Git still holds comes after.
        Empty for a named tier, which takes no value of its own."""
        r = self.resolve(env, tier)
        if not r.custom:
            return {}
        mine = {**r.quota, **flatten_limits(r.limit_range)}
        asked = {k: v for k, v in {**hard, **flatten_limits(limit_range)}.items() if k not in self.file.sizable}
        order = [*self.file.overridable, *sorted(set(asked) - set(self.file.overridable))]
        return {k: {"tier": mine.get(k), "requested": asked[k]} for k in order
                if k in asked and not _same(asked[k], mine.get(k))}

    @staticmethod
    def rendered_overrides(rq: Mapping[str, Any] | None, lr: Mapping[str, Any] | None) -> dict[str, str]:
        """The approved beyond-tier values of a namespace, from its two rendered objects: each key that the annotation
        cmapi.net/beyond-tier names, with the value that the object holds. The inverse of render() for those keys."""
        out: dict[str, str] = {}
        hard = ((rq or {}).get("spec") or {}).get("hard") or {}
        for k in _beyond_keys(rq):
            if k in hard:
                out[k] = str(hard[k])
        by_kind = {item.get("type"): item for item in ((lr or {}).get("spec") or {}).get("limits") or []}
        for k in _beyond_keys(lr):
            parts = limit_key_parts(k)
            value = parts and by_kind.get(LIMIT_KINDS[parts[0]], {}).get(parts[1], {}).get(parts[2])
            if value is not None:
                out[k] = str(value)
        return out

    def match(self, env: str, hard: Mapping[str, str], tolerance: float = 0.0) -> str | None:
        """The named tier whose sizable values equal hard (within tolerance), else None.
        tolerance 0: PATCH .../quota normalisation and adoption. 0.10: rightsizing snaps."""
        for r in self.offered(env):
            if r.custom:
                continue
            if all(k in hard and abs(qty(hard[k]) - qty(r.quota[k])) <= qty(r.quota[k]) * Decimal(str(tolerance))
                   for k in self.sizable):
                return r.name
        return None

    def normalise(self, env: str, hard: Mapping[str, str]) -> tuple[str, dict[str, str]]:
        """PATCH .../quota sends sizable values only. Equal to a named tier -> that tier;
        otherwise custom, checked against the bounds."""
        named = self.match(env, hard)
        if named:
            return named, self.quota_for(env, named)
        custom = next((r.name for r in self.offered(env) if r.custom), None)
        if custom is None:
            raise TierError("tier-not-offered", f"Custom quotas are not offered in {env}")
        return custom, self.quota_for(env, custom, hard)

    def compare(self, env: str, current_tier: str, current_hard: Mapping[str, str],
                new_tier: str, new_hard: Mapping[str, str],
                used: Mapping[str, str] | None = None) -> QuotaChange:
        pct, delta, below = {}, {}, []
        for k in self.sizable:
            old, new = qty(current_hard.get(k, "0")), qty(new_hard[k])
            delta[k] = new - old
            pct[k] = float((new - old) / old * 100) if old else (100.0 if new else 0.0)
            if used and k in used and new < qty(used[k]):
                below.append(k)
        cur_c = self.file.tiers.get(current_tier, TierDef(order=0)).custom
        new_c = self.file.tiers[new_tier].custom
        if cur_c and new_c:
            change = "custom"
        elif new_c:
            change = "to-custom"
        elif cur_c:
            change = "from-custom"
        else:
            o_old = self.file.tiers[current_tier].order if current_tier in self.file.tiers else 0
            o_new = self.file.tiers[new_tier].order
            change = "up" if o_new > o_old else "down" if o_new < o_old else "same"
        return QuotaChange(tier_change=change, increase_pct=pct, delta=delta, below_used=below)

    def is_outdated(self, env: str, tier: str, rendered_hash: str | None) -> bool:
        """True when the namespace's cmapi.net/tier-hash is not the catalog's current one."""
        return rendered_hash != self.resolve(env, tier).hash

    # ---- rendering (called by core/render/manifests.py)
    def render(self, *, namespace: str, cluster_id: str, instance: str, env: str, tier: str,
               request_id: str, hard: Mapping[str, str] | None = None,
               limits: Mapping[str, Mapping[str, Mapping[str, str]]] | None = None,
               approved: Mapping[str, str] | None = None) -> tuple[dict, dict]:
        """resourcequota.yaml and limitrange.yaml for one namespace, as dicts. Each object names its own beyond-tier keys
        in the annotation cmapi.net/beyond-tier, so a later change and a policy can tell an approved override from drift."""
        r = self.resolve(env, tier)
        spec_hard = self.quota_for(env, tier, hard, approved)
        limit_range = self.limits_for(env, tier, limits, spec_hard, approved)
        beyond = list(self.beyond(env, tier, spec_hard, limit_range))
        labels = {"cmapi.net/cluster-id": cluster_id, "cmapi.net/managed": "true", "cmapi.net/tier": tier}
        annotations = {"cmapi.net/instance": instance, "cmapi.net/request-id": request_id,
                       "cmapi.net/tier-hash": r.hash}
        rq = {"apiVersion": "v1", "kind": "ResourceQuota",
              "metadata": {"name": f"{namespace}-quota", "namespace": namespace,
                           "labels": labels, "annotations": annotations},
              "spec": {"hard": {k: spec_hard[k] for k in sorted(spec_hard, key=_quota_order)}}}
        items = []
        for kind, k8s in LIMIT_KINDS.items():
            parts = limit_range.get(kind)
            if parts:
                items.append({"type": k8s, **{p: dict(parts[p]) for p in
                                               ("defaultRequest", "default", "min", "max") if p in parts}})
        lr = {"apiVersion": "v1", "kind": "LimitRange",
              "metadata": {"name": f"{namespace}-limits", "namespace": namespace,
                           "labels": dict(labels), "annotations": dict(annotations)},
              "spec": {"limits": items}}
        for doc, keys in ((rq, [k for k in beyond if not is_limit_key(k)]), (lr, [k for k in beyond if is_limit_key(k)])):
            if keys:
                doc["metadata"]["annotations"][BEYOND_TIER] = ",".join(keys)
        return rq, lr

    def describe(self, env: str | None = None) -> dict[str, Any]:
        """Body of GET /api/v1/tiers."""
        envs = [env] if env else self.environments()
        for e in envs:
            self._need_env(e)
        return {"catalogHash": self.catalog_hash, "sizable": self.sizable, "overridable": list(self.file.overridable),
                "environments": {e: {"tiers": [r.as_dict() for r in self.offered(e)],
                                     "custom": self.bounds(e).model_dump()} for e in envs}}


def _beyond_keys(doc: Mapping[str, Any] | None) -> list[str]:
    value = (((doc or {}).get("metadata") or {}).get("annotations") or {}).get(BEYOND_TIER) or ""
    return [k for k in value.split(",") if k]


_ORDER = ["requests.cpu", "requests.memory", "pods"]


def _quota_order(k: str) -> tuple[int, str]:
    return (_ORDER.index(k), k) if k in _ORDER else (len(_ORDER), k)
