"""The read that ends a request, in every delivery mode: the live cluster against the full approved plan (#751).

Pure: no client and no logging, so tests/core runs it with the reference venv. The jobs give it a Getter on the cluster's
watch cache and reader (jobs/watch_sync.py `_live`). The design and its primary sources:
docs/reviews/2026-11-27-issue-751/README.md, D2.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, Callable, Iterable, Iterator, Mapping

from cmapi.core import kube_yaml
from cmapi.core.adoption import DEFAULT_SKIP_PREFIXES
from cmapi.core.metadata import DEFAULT_LIVE_ONLY_KEYS
from cmapi.core.tiers import qty

# A read of one object: the live object, or None when it is not there. It raises Unreadable when this one object cannot be
# read, and anything else (ClusterUnreachable) when the cluster cannot be read at all, which every caller waits on.
Getter = Callable[[str, "str | None", str], "dict[str, Any] | None"]


class Unreadable(Exception):
    """One object that the reader could not read: an error answer, a body it cannot parse, a kind with no path. Never an
    absence."""


# Planned objects in this order, the Namespace first; other kinds (ServiceAccounts, RoleBindings) are not compared (D2).
_ORDER = {"Namespace": 0, "ResourceQuota": 1, "LimitRange": 2}
_LIMIT_MAPS = ("max", "min", "default", "defaultRequest", "maxLimitRequestRatio")


@dataclass(frozen=True)
class Difference:
    """One way the live cluster is not the plan. `plan` and `live` are the values, None for absent."""

    object: str                      # Namespace/payments-dev, LimitRange/payments-dev-cpu
    field: str                       # "label cmapi.net/team", "spec.limits[0].max.cpu", "" for the whole object
    plan: Any
    live: Any
    removal: bool = False            # an object the plan removes, still on the cluster (case 3)

    def __str__(self) -> str:
        where = f"{self.object} {self.field}" if self.field else self.object
        return f"{where}: plan {_shown(self.plan)}, live {_shown(self.live)}"

    def view(self) -> dict[str, Any]:
        return {"object": self.object, "field": self.field, "plan": self.plan, "live": self.live, "removal": self.removal}


def _shown(value: Any) -> str:
    return "absent" if value is None else repr(value)


@dataclass(frozen=True)
class PlanRead:
    """What read_plan found: every difference, and what was compared, for the note of a confirmation."""

    differences: tuple[Difference, ...]
    compared: str                    # "1 Namespace, 1 ResourceQuota and 2 LimitRanges match the plan", for a confirmation

    @property
    def ok(self) -> bool:
        return not self.differences

    @property
    def only_removals(self) -> bool:
        """Every difference is a removed object still there: what a deliverer that does not prune leaves (D5)."""
        return bool(self.differences) and all(d.removal for d in self.differences)

    def summary(self, first: int = 3) -> str:
        if self.ok:
            return self.compared
        shown = "; ".join(str(d) for d in self.differences[:first])
        more = len(self.differences) - first
        return f"{len(self.differences)} difference(s) from the plan: {shown}" + (f"; and {more} more" if more > 0 else "")


def _docs(files: Mapping[str, str | None]) -> Iterator[dict[str, Any]]:
    """Each named object of a folder's .yaml files, as objects_of reads them (core/render/manifests.py)."""
    for path in sorted(files):
        text = files[path]
        if text and path.endswith(".yaml"):
            for d in kube_yaml.load_all(text):
                if d.get("kind") and (d.get("metadata") or {}).get("name"):
                    yield d


def _identity(doc: Mapping[str, Any], namespace: str) -> tuple[str, str | None, str]:
    """(kind, namespace, name), with the request's namespace for a namespaced object that names none, as apply mode's
    prune reads it (jobs/watch_sync.py). A Namespace has none."""
    meta = doc["metadata"]
    if doc["kind"] == "Namespace":
        return "Namespace", None, meta["name"]
    return doc["kind"], meta.get("namespace") or namespace, meta["name"]


def _same(a: Any, b: Any) -> bool:
    """One amount: quantities by value (the API server canonicalises 5120Mi to 5Gi), anything else by its text."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return qty(a) == qty(b)
    except ValueError:
        return str(a) == str(b)


def _map_differences(obj: str, prefix: str, plan: Mapping[str, Any] | None, live: Mapping[str, Any] | None
                     ) -> list[Difference]:
    """Each key of either map whose value differs, by value, in both directions: a live key the plan lacks is a difference."""
    plan, live = plan or {}, live or {}
    return [Difference(obj, f"{prefix}.{k}", plan.get(k), live.get(k)) for k in sorted(set(plan) | set(live))
            if not _same(plan.get(k), live.get(k))]


def defaulted_limit(item: Mapping[str, Any]) -> dict[str, Any]:
    """A LimitRange item as the API server stores it. SetDefaults_LimitRangeItem (kubernetes pkg/apis/core/v1/defaults.go,
    read 2026-11-27), for a Container item only: an unset default limit takes the max; an unset default request takes the
    default limit, then the min. Applied to both sides, so it is a no-op on a live item and on a plan that sets them."""
    out: dict[str, Any] = {"type": item.get("type")}
    for k in _LIMIT_MAPS:
        out[k] = dict(item.get(k) or {})
    if out["type"] == "Container":
        for k, v in out["max"].items():
            out["default"].setdefault(k, v)
        for k, v in out["default"].items():
            out["defaultRequest"].setdefault(k, v)
        for k, v in out["min"].items():
            out["defaultRequest"].setdefault(k, v)
    return out


def _quota_differences(obj: str, plan: Mapping[str, Any], live: Mapping[str, Any]) -> list[Difference]:
    ps, ls = plan.get("spec") or {}, live.get("spec") or {}
    out = _map_differences(obj, "spec.hard", ps.get("hard"), ls.get("hard"))
    if sorted(ps.get("scopes") or []) != sorted(ls.get("scopes") or []):
        out.append(Difference(obj, "spec.scopes", ps.get("scopes"), ls.get("scopes")))
    if (ps.get("scopeSelector") or None) != (ls.get("scopeSelector") or None):
        out.append(Difference(obj, "spec.scopeSelector", ps.get("scopeSelector"), ls.get("scopeSelector")))
    return out


def _limit_differences(obj: str, plan: Mapping[str, Any], live: Mapping[str, Any]) -> list[Difference]:
    """spec.limits item by item, in order: the API server keeps the list as written."""
    want = [defaulted_limit(i) for i in (plan.get("spec") or {}).get("limits") or []]
    have = [defaulted_limit(i) for i in (live.get("spec") or {}).get("limits") or []]
    out: list[Difference] = []
    for n in range(max(len(want), len(have))):
        at = f"spec.limits[{n}]"
        if n >= len(want) or n >= len(have):
            out.append(Difference(obj, at, want[n] if n < len(want) else None, have[n] if n < len(have) else None))
            continue
        if want[n]["type"] != have[n]["type"]:
            out.append(Difference(obj, f"{at}.type", want[n]["type"], have[n]["type"]))
            continue
        for k in _LIMIT_MAPS:
            out += _map_differences(obj, f"{at}.{k}", want[n][k], have[n][k])
    return out


def _namespace_differences(obj: str, plan: Mapping[str, Any], previous: Mapping[str, Any] | None, live: Mapping[str, Any],
                           skipped: Callable[[str], bool]) -> list[Difference]:
    """Each label and annotation the plan writes, with its value, and each one the previous folder held and the plan drops,
    absent. A live key that neither holds is not the plan's: the drift view (#481) covers it."""
    out: list[Difference] = []
    for field, word in (("labels", "label"), ("annotations", "annotation")):
        want = (plan.get("metadata") or {}).get(field) or {}
        had = ((previous or {}).get("metadata") or {}).get(field) or {}
        have = (live.get("metadata") or {}).get(field) or {}
        for k in sorted(want):
            if not skipped(k) and have.get(k) != want[k]:
                out.append(Difference(obj, f"{word} {k}", want[k], have.get(k)))
        for k in sorted(set(had) - set(want)):
            if not skipped(k) and k in have:
                out.append(Difference(obj, f"{word} {k}", None, have[k]))
    return out


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def read_plan(get: Getter, namespace: str, files: Mapping[str, str | None], previous: Mapping[str, str | None] | None = None,
              *, live_only: Iterable[str] = DEFAULT_LIVE_ONLY_KEYS, skip_prefixes: Iterable[str] = DEFAULT_SKIP_PREFIXES) -> PlanRead:
    """The read that ends a request, in every mode (#751, D2): the live cluster against the full approved plan.

    - The Namespace: each label and annotation of the plan, and the absence of each one the plan drops from the previous
      folder. A key that matches liveOnlyKeys (`live_only`, fnmatch) or starts with a skip prefix of adoption.yaml
      (`skip_prefixes`) is the cluster's, and left out.
    - Each ResourceQuota: spec.hard in both directions by value, spec.scopes and spec.scopeSelector.
    - Each LimitRange: spec.limits item by item, after the API server's defaults (defaulted_limit).
    - Each object the previous folder holds and the plan does not, by kind, namespace and name: absent. A file rename that
      keeps the object is no removal.

    A deliverer's report is never enough: it describes its own desired state, with its own ignore rules, and server-side
    apply keeps a field that another manager co-owns (Kubernetes, "Server-Side Apply"). A read of one object that raises
    Unreadable is a difference that names it, never an absence; anything else the Getter raises (a cluster that cannot be
    read) propagates."""
    live_only, prefixes = tuple(live_only), tuple(skip_prefixes)

    def skipped(key: str) -> bool:
        return any(fnmatchcase(key, g) for g in live_only) or any(key.startswith(p) for p in prefixes)

    def read(ident: tuple[str, str | None, str]) -> tuple[dict[str, Any] | None, Difference | None]:
        try:
            return get(*ident), None
        except Unreadable as exc:
            return None, Difference(f"{ident[0]}/{ident[2]}", "", "readable", f"cannot read: {str(exc)[:160]}")

    # The Namespace first: when it is missing, that is the difference a person needs to read first.
    planned = sorted(_docs(files), key=lambda d: (_ORDER.get(d["kind"], len(_ORDER)), d["metadata"]["name"]))
    before = {_identity(d, namespace): d for d in _docs(previous or {})}
    out: list[Difference] = []
    counts = dict.fromkeys(_ORDER, 0)
    idents = set()
    for doc in planned:
        ident = _identity(doc, namespace)
        idents.add(ident)
        kind = ident[0]
        if kind not in counts:
            continue
        counts[kind] += 1
        obj = f"{kind}/{ident[2]}"
        live, failed = read(ident)
        if failed:
            out.append(failed)
        elif live is None:
            out.append(Difference(obj, "", "present", None))
        elif kind == "Namespace":
            out += _namespace_differences(obj, doc, before.get(ident), live, skipped)
        elif kind == "ResourceQuota":
            out += _quota_differences(obj, doc, live)
        else:
            out += _limit_differences(obj, doc, live)
    removed = [i for i in before if i not in idents and i[0] != "Namespace"]
    for ident in removed:
        live, failed = read(ident)
        if failed:
            out.append(failed)
        elif live is not None:
            out.append(Difference(f"{ident[0]}/{ident[2]}", "", None, "present", removal=True))
    parts = [_count(counts["Namespace"], "Namespace"), _count(counts["ResourceQuota"], "ResourceQuota"),
             _count(counts["LimitRange"], "LimitRange")]
    compared = ", ".join(parts[:-1]) + f" and {parts[-1]} match the plan"
    if removed:
        compared += f", and {_count(len(removed), 'removed object')} absent"
    return PlanRead(tuple(out), compared)
