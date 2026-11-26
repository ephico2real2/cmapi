"""Adoption of an existing namespace that cmapi does not manage (story #26).

The design is docs/reviews/2026-11-14-issue-26-adoption/README.md; each function below names the decision it builds. This
module is pure: it reads objects that the caller fetched from the cluster and returns files, findings and verdicts. The
adoption plugin (plugins/adoption) and the pipeline (Pipeline.plan_adoption) call it, and the delivery jobs call `stale`.

    standing()       D1   whether a namespace is a candidate, and the rule that skips or excludes it
    cleaned()        D3   the object minus what the API server sets
    skipped_keys()   D3a  which keys under a skip prefix may be left out of Git, from metadata.managedFields
    adopted_files()  D4, D8  the folder: the objects as they are, plus cmapi's system keys, one file for each object
    object_findings() D5, D17  the findings of the ResourceQuotas and LimitRanges, never a change
    stale()          D16  whether the live objects still are the ones the plan read

Nothing here writes to a cluster: cmapi stays read-only on the clusters, and Argo CD (or the apply delivery) takes the
namespace over after the pull request merges.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Iterable, Mapping

from cmapi.core import kube_yaml
from cmapi.core.metadata import MetadataKeys
from cmapi.core.render.manifests import folder, object_file
from cmapi.core.tiers import LIMIT_KINDS, TierCatalog, flatten_limits, qty

ADOPT_LABEL = "cmapi.net/adopt"
TRACKING_ANNOTATION = "argocd.argoproj.io/tracking-id"
INSTANCE_LABEL = "app.kubernetes.io/instance"
SYNC_OPTIONS_ANNOTATION = "argocd.argoproj.io/sync-options"
NAMESPACE_SYNC_OPTIONS = "Prune=confirm,ServerSideApply=true"   # D4: the namespace, as the renderer writes it
OBJECT_SYNC_OPTIONS = "Prune=confirm"                           # D4: each adopted ResourceQuota and LimitRange (Fable's A2)
KINDS = ("ResourceQuota", "LimitRange")

# D1: never candidates, whatever adoption.yaml says (docs/02, "Adoption plugin").
BUILT_IN_EXCLUDED = ("default", "openshift", "openshift-*", "kube-*")
# D3: the metadata that the API server sets. A Namespace's spec.finalizers ([kubernetes]) is set on each namespace too.
SERVER_FIELDS = ("uid", "resourceVersion", "generation", "creationTimestamp", "managedFields", "selfLink",
                 "deletionTimestamp", "deletionGracePeriodSeconds")
# D3: the default skip prefixes of adoption.yaml: the owner's two, and the two that the design recommends.
DEFAULT_SKIP_PREFIXES = ("openshift.io/sa.scc.", "kubectl.kubernetes.io/", "kubernetes.io/metadata.name",
                         "pod-security.kubernetes.io/")
# D3a: the manager that kubectl's client-side apply writes ("--field-manager ... Default: kubectl-client-side-apply", kubectl
# apply reference), which Argo CD's client-side apply migration takes over by default (Argo CD, "Sync Options").
CLIENT_SIDE_APPLY_MANAGER = "kubectl-client-side-apply"
# D17: the quota keys whose meaning cmapi reads; a short name is its long one ("Same as requests.cpu", Resource Quotas).
INTERPRETED = {"cpu": "requests.cpu", "requests.cpu": "requests.cpu", "memory": "requests.memory",
               "requests.memory": "requests.memory", "pods": "pods", "persistentvolumeclaims": "persistentvolumeclaims",
               "requests.storage": "requests.storage", "services.loadbalancers": "services.loadbalancers",
               "services.nodeports": "services.nodeports"}


# --------------------------------------------------------------------------- adoption.yaml


@dataclass(frozen=True)
class Exclusions:
    """Names, shell globs and label selectors that exclude a namespace. Selectors take `key`, `!key`, `key=value` and
    `key!=value`, Kubernetes' equality-based forms ("Labels and Selectors")."""
    names: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    selectors: tuple[str, ...] = ()

    def match(self, name: str, labels: Mapping[str, str]) -> str | None:
        if name in self.names:
            return f"name {name}"
        hit = next((p for p in self.patterns if fnmatchcase(name, p)), None)
        if hit:
            return f"pattern {hit}"
        hit = next((s for s in self.selectors if _selects(s, labels)), None)
        return f"label selector {hit}" if hit else None


def _selects(selector: str, labels: Mapping[str, str]) -> bool:
    if selector.startswith("!"):
        return selector[1:] not in labels
    if "!=" in selector:
        key, _, value = selector.partition("!=")
        return labels.get(key) != value
    if "=" in selector:
        key, _, value = selector.partition("=")
        return labels.get(key) == value
    return selector in labels


@dataclass(frozen=True)
class AdoptionSettings:
    """adoption.yaml (docs/02, "Adoption plugin", Configuration). The file is optional: without it the defaults below hold."""
    label: str = ADOPT_LABEL
    value: str = "true"
    exclude: Exclusions = Exclusions()
    environments: Mapping[str, Exclusions] = field(default_factory=dict)
    clusters: Mapping[str, Exclusions] = field(default_factory=dict)
    skip_prefixes: tuple[str, ...] = DEFAULT_SKIP_PREFIXES
    migration_manager: str = CLIENT_SIDE_APPLY_MANAGER
    label_tracking: bool = False        # the hub's Argo CD uses application.resourceTrackingMethod: label (D1 step 3)

    @classmethod
    def parse(cls, raw: Mapping[str, Any] | None, allowed_environments: Iterable[str]) -> "AdoptionSettings":
        """The settings of one file, or ValueError naming each problem. Exclusions add up: an environment or a cluster can
        only exclude more (D1)."""
        if raw is None:
            return cls()
        problems: list[str] = []
        if not isinstance(raw, Mapping):
            raise ValueError("adoption.yaml is a mapping")
        known = {"selector", "exclude", "environments", "clusters", "skip", "argocd"}
        problems += [f"unknown key {k!r}: the keys are {sorted(known)}" for k in raw if k not in known]
        selector = raw.get("selector") or {}
        label, value = selector.get("label", ADOPT_LABEL), selector.get("value", "true")
        if not isinstance(label, str) or not label or not isinstance(value, str):
            problems.append("selector: label and value are strings (a label value is a string: quote \"true\")")
        exclude = cls._exclusions(raw.get("exclude"), "exclude", problems)
        envs: dict[str, Exclusions] = {}
        for env, block in (raw.get("environments") or {}).items():
            if env not in set(allowed_environments):
                problems.append(f"environments.{env}: not an environment of this instance")
            envs[env] = cls._exclusions(block, f"environments.{env}", problems)
        clusters = {cid: cls._exclusions(block, f"clusters.{cid}", problems) for cid, block in (raw.get("clusters") or {}).items()}
        skip = raw.get("skip") or {}
        prefixes = skip.get("keyPrefixes", list(DEFAULT_SKIP_PREFIXES))
        if not isinstance(prefixes, list) or not all(isinstance(p, str) and p for p in prefixes):
            problems.append("skip.keyPrefixes: a list of key prefixes")
            prefixes = list(DEFAULT_SKIP_PREFIXES)
        manager = skip.get("clientSideApplyManager", CLIENT_SIDE_APPLY_MANAGER)
        if not isinstance(manager, str) or not manager:
            problems.append("skip.clientSideApplyManager: the name of a field manager")
        tracking = (raw.get("argocd") or {}).get("resourceTrackingMethod", "annotation")
        if tracking not in ("annotation", "label", "annotation+label"):
            problems.append("argocd.resourceTrackingMethod: annotation, label or annotation+label (Argo CD, Resource Tracking)")
        if problems:
            raise ValueError("; ".join(problems))
        return cls(label, value, exclude, envs, clusters, tuple(prefixes), manager, tracking != "annotation")

    @staticmethod
    def _exclusions(block: Any, where: str, problems: list[str]) -> Exclusions:
        if block is None:
            return Exclusions()
        if not isinstance(block, Mapping):
            problems.append(f"{where}: a mapping of names, patterns and labelSelectors")
            return Exclusions()
        out: dict[str, tuple[str, ...]] = {}
        for key, attr in (("names", "names"), ("patterns", "patterns"), ("labelSelectors", "selectors")):
            items = block.get(key) or []
            if not isinstance(items, list) or not all(isinstance(i, str) and i for i in items):
                problems.append(f"{where}.{key}: a list of strings")
                items = []
            out[attr] = tuple(items)
        problems += [f"{where}: unknown key {k!r}" for k in block if k not in ("names", "patterns", "labelSelectors")]
        return Exclusions(**out)

    def excluded(self, name: str, labels: Mapping[str, str], environment: str, cluster_id: str,
                 reserved_patterns: Iterable[str] = ()) -> str | None:
        """The rule that excludes the namespace, or None: the built-in exclusions, the instance's reserved names, then
        adoption.yaml's global, environment and cluster scopes."""
        hit = next((p for p in (*BUILT_IN_EXCLUDED, *reserved_patterns) if fnmatchcase(name, p)), None)
        if hit:
            return f"built-in exclusion {hit}"
        for scope in (self.exclude, self.environments.get(environment), self.clusters.get(cluster_id)):
            why = scope.match(name, labels) if scope else None
            if why:
                return why
        return None


# --------------------------------------------------------------------------- D1: candidates


@dataclass(frozen=True)
class Standing:
    """Where one namespace stands for adoption. state: candidate, skipped (labelled, and a rule stops it), managed,
    excluded or unlabelled (neither of the last two is ever adopted). rule names what stopped it."""
    name: str
    state: str
    rule: str | None = None
    detail: str = ""
    labelled: bool = False
    recognised: tuple[str, ...] = ()
    application: str | None = None


def standing(ns: Mapping[str, Any], *, in_git: bool, environment: str, cluster_id: str, settings: AdoptionSettings,
             keys: MetadataKeys, own_application: str | None, reserved_patterns: Iterable[str] = ()) -> Standing:
    """D1, in docs/02's order: not excluded and not Terminating, not managed (the label, or a folder in Git: what makes the
    kept opt-in label inert), not tracked by another Argo CD Application, and labelled. `adoptionLabels` only marks a
    namespace as made by another tool ("recognised"); it never selects one."""
    meta = ns.get("metadata") or {}
    name = meta.get("name", "")
    labels, annotations = meta.get("labels") or {}, meta.get("annotations") or {}
    labelled = labels.get(settings.label) == settings.value
    recognised = tuple(sorted(f"{k}={labels[k]}" for k, values in keys.adoption_labels.items() if labels.get(k) in values))

    def out(state: str, rule: str | None = None, detail: str = "", application: str | None = None) -> Standing:
        if state != "candidate" and labelled and state in ("excluded", "managed"):
            state = "skipped"
        return Standing(name, state, rule, detail, labelled, recognised, application)

    why = settings.excluded(name, labels, environment, cluster_id, reserved_patterns)
    if why:
        return out("excluded", "excluded", f"Excluded by {why}")
    if (ns.get("status") or {}).get("phase") == "Terminating" or meta.get("deletionTimestamp"):
        return out("excluded", "terminating", f"{name} is being deleted")
    if labels.get("cmapi.net/managed") == "true" or in_git:
        return out("managed", "managed", f"cmapi manages {name}" if not in_git else f"{name} has a folder in Git")
    app = tracked_by(labels, annotations, settings)
    if app is not None and app != own_application:
        if labelled:
            return Standing(name, "skipped", "tracked-elsewhere", f"The Argo CD Application {app} tracks {name}", True,
                            recognised, app)
        return Standing(name, "unlabelled", "tracked-elsewhere", f"The Argo CD Application {app} tracks {name}", False,
                        recognised, app)
    if not labelled:
        return Standing(name, "unlabelled", "not-labelled", f"{name} does not carry {settings.label}: \"{settings.value}\"",
                        False, recognised)
    return Standing(name, "candidate", None, "", True, recognised)


def tracked_by(labels: Mapping[str, str], annotations: Mapping[str, str], settings: AdoptionSettings) -> str | None:
    """The Argo CD Application that tracks the object: the tracking annotation `<app>:<group>/<kind>:<ns>/<name>` ("Resource
    Tracking"), or, only when the hub uses label tracking, the app.kubernetes.io/instance label."""
    tracking = annotations.get(TRACKING_ANNOTATION)
    if tracking:
        return tracking.split(":", 1)[0] or None
    if settings.label_tracking and labels.get(INSTANCE_LABEL):
        return labels[INSTANCE_LABEL]
    return None


# --------------------------------------------------------------------------- D3, D3a: what is read and what is dropped


def cleaned(obj: Mapping[str, Any], kind: str) -> dict[str, Any]:
    """D3: the object minus what the API server sets: the server metadata, status, and a Namespace's spec.finalizers. A list
    answer's items carry no kind or apiVersion, so both are written back."""
    out = json.loads(json.dumps(obj))
    out.pop("status", None)
    meta = out.setdefault("metadata", {})
    for key in SERVER_FIELDS:
        meta.pop(key, None)
    for key in ("labels", "annotations"):
        if not meta.get(key):
            meta.pop(key, None)
    if kind == "Namespace":
        spec = out.pop("spec", None) or {}
        spec.pop("finalizers", None)
        if spec:
            out["spec"] = spec
    return {"apiVersion": out.pop("apiVersion", None) or "v1", "kind": kind, **{k: v for k, v in out.items() if k != "kind"}}


def key_managers(obj: Mapping[str, Any]) -> dict[tuple[str, str], list[dict[str, str]]]:
    """(label|annotation, key) -> each field manager that owns it, with its operation, from metadata.managedFields. The
    entries are FieldsV1: `f:metadata: {f:labels: {f:<key>: {}}}` (Kubernetes, "Server-Side Apply")."""
    out: dict[tuple[str, str], list[dict[str, str]]] = {}
    for entry in ((obj.get("metadata") or {}).get("managedFields") or []):
        fields = ((entry.get("fieldsV1") or {}).get("f:metadata") or {})
        for kind, stanza in (("label", "f:labels"), ("annotation", "f:annotations")):
            for owned in (fields.get(stanza) or {}):
                if owned.startswith("f:"):
                    out.setdefault((kind, owned[2:]), []).append({"manager": str(entry.get("manager", "")),
                                                                  "operation": str(entry.get("operation", ""))})
    return out


@dataclass(frozen=True)
class KeyDecision:
    kind: str
    key: str
    kept: bool
    managers: tuple[str, ...]
    why: str


def skipped_keys(obj: Mapping[str, Any], settings: AdoptionSettings) -> list[KeyDecision]:
    """D3a: each label and annotation under a skip prefix, and whether it stays in Git. It is left out only when its managers
    are known and none is the client-side apply manager that Argo CD's migration takes over: then leaving it out changes
    nothing on the cluster. A key that such a manager wrote, or whose managers the read did not give, stays as it is."""
    meta = obj.get("metadata") or {}
    owners = key_managers(obj)
    known = bool(meta.get("managedFields"))
    out = []
    for kind, stanza in (("label", "labels"), ("annotation", "annotations")):
        for key in sorted(meta.get(stanza) or {}):
            if not any(key.startswith(p) for p in settings.skip_prefixes):
                continue
            managers = tuple(sorted({o["manager"] for o in owners.get((kind, key), [])}))
            if not known:
                out.append(KeyDecision(kind, key, True, managers, "the read gave no field managers, so leaving it out could "
                                                                   "remove it from the cluster"))
            elif settings.migration_manager in managers:
                out.append(KeyDecision(kind, key, True, managers, f"{settings.migration_manager} wrote it, and Argo CD's "
                                                                   "client-side apply migration would remove it if Git left "
                                                                   "it out"))
            else:
                out.append(KeyDecision(kind, key, False, managers, "only server components own it" if managers
                                       else "no field manager owns it"))
    return out


def without_skipped(obj: dict[str, Any], decisions: Iterable[KeyDecision]) -> dict[str, Any]:
    meta = obj.get("metadata") or {}
    for d in decisions:
        if not d.kept:
            (meta.get("labels" if d.kind == "label" else "annotations") or {}).pop(d.key, None)
    for key in ("labels", "annotations"):
        if key in meta and not meta[key]:
            meta.pop(key)
    return obj


# --------------------------------------------------------------------------- D4, D8: the folder


@dataclass(frozen=True)
class Owner:
    """What D4 writes about the adoption: the cluster, the instance, the environment, the request and who asked."""
    cluster_id: str
    instance: str
    environment: str
    tier: str
    request_id: str
    username: str
    email: str | None


@dataclass
class Snapshot:
    """The live objects as the plan read them, after D3: the base of the policies (D6a) and of the reads of D16."""
    namespace: dict[str, Any]
    quotas: list[dict[str, Any]]
    limits: list[dict[str, Any]]
    identity: list[dict[str, str]]     # kind, name, uid and resourceVersion of each object read

    def files(self, cluster_id: str) -> dict[str, str]:
        base = folder(cluster_id, self.namespace["metadata"]["name"])
        out = {base + "namespace.yaml": kube_yaml.dump(self.namespace, sort_keys=False, default_flow_style=False)}
        for doc in (*self.quotas, *self.limits):
            out[base + object_file(doc["kind"], doc["metadata"]["name"])] = kube_yaml.dump(doc, sort_keys=False,
                                                                                         default_flow_style=False)
        return out


def identity_of(obj: Mapping[str, Any], kind: str) -> dict[str, str]:
    meta = obj.get("metadata") or {}
    return {"kind": kind, "name": str(meta.get("name", "")), "uid": str(meta.get("uid", "")),
            "resourceVersion": str(meta.get("resourceVersion", ""))}


def snapshot(ns: Mapping[str, Any], quotas: Iterable[Mapping[str, Any]], limits: Iterable[Mapping[str, Any]],
             settings: AdoptionSettings) -> tuple[Snapshot, list[KeyDecision]]:
    """The objects after D3 and D3a, and the decision on each key under a skip prefix."""
    decisions = skipped_keys(ns, settings)
    namespace = without_skipped(cleaned(ns, "Namespace"), decisions)
    rq = sorted((cleaned(q, "ResourceQuota") for q in quotas), key=lambda d: d["metadata"]["name"])
    lr = sorted((cleaned(q, "LimitRange") for q in limits), key=lambda d: d["metadata"]["name"])
    ids = [identity_of(ns, "Namespace"), *(identity_of(q, "ResourceQuota") for q in quotas),
           *(identity_of(q, "LimitRange") for q in limits)]
    order = {"Namespace": 0, "ResourceQuota": 1, "LimitRange": 2}
    return Snapshot(namespace, rq, lr, sorted(ids, key=lambda i: (order[i["kind"]], i["name"]))), decisions


def snapshot_hash(files: Mapping[str, str], identity: Iterable[Mapping[str, str]]) -> str:
    """The digest of the stored snapshot: the PR check finds the snapshot by the request and believes it only when its
    digest is the one the plan recorded (D6a, step 2)."""
    body = json.dumps({"files": dict(sorted(files.items())), "identity": list(identity)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def adopted_files(snap: Snapshot, owner: Owner, keys: MetadataKeys) -> tuple[dict[str, str], list[dict[str, str]]]:
    """D4 and D8: the folder of the adoption, and each system value that it writes over a value the namespace held.

    The Namespace keeps every label and annotation that D3 keeps, cmapi.net/adopt too (the owner's decision 6), and gets the
    renderer's system keys; each ResourceQuota and LimitRange keeps its content under its own name, in its own file, and gets
    cmapi.net/managed, cluster-id and tier, with Prune=confirm. No tier hash: an adopted object is no rendering of a tier."""
    replaced: list[dict[str, str]] = []
    base = folder(owner.cluster_id, snap.namespace["metadata"]["name"])

    def stamp(doc: dict[str, Any], labels: Mapping[str, str], annotations: Mapping[str, str]) -> dict[str, Any]:
        doc = json.loads(json.dumps(doc))
        meta = doc.setdefault("metadata", {})
        held_l, held_a = dict(meta.get("labels") or {}), dict(meta.get("annotations") or {})
        for kind, held, mine in (("label", held_l, labels), ("annotation", held_a, annotations)):
            for key, value in mine.items():
                if key in held and held[key] != value:
                    replaced.append({"object": f"{doc['kind']}/{meta.get('name')}", "kind": kind, "key": key,
                                     "before": held[key], "after": value})
        meta["labels"] = keys.ordered({**held_l, **labels})
        meta["annotations"] = keys.ordered({**held_a, **annotations})
        # metadata first, in the order a reader expects: name, namespace, labels, annotations, then anything else it held
        order = ["name", "namespace", "labels", "annotations"]
        doc["metadata"] = {**{k: meta[k] for k in order if k in meta}, **{k: v for k, v in meta.items() if k not in order}}
        return doc

    common = {"cmapi.net/cluster-id": owner.cluster_id, "cmapi.net/managed": "true", "cmapi.net/tier": owner.tier}
    ns_labels = {**common, "cmapi.net/env": owner.environment, "cmapi.net/requested-by-user": owner.username}
    ns_annotations = {"cmapi.net/instance": owner.instance, "cmapi.net/request-id": owner.request_id,
                      SYNC_OPTIONS_ANNOTATION: NAMESPACE_SYNC_OPTIONS}
    if owner.email:
        ns_annotations["cmapi.net/requested-by"] = owner.email
    obj_annotations = {"cmapi.net/instance": owner.instance, "cmapi.net/request-id": owner.request_id,
                       SYNC_OPTIONS_ANNOTATION: OBJECT_SYNC_OPTIONS}

    def dump(doc: Mapping[str, Any]) -> str:
        return kube_yaml.dump(doc, sort_keys=False, default_flow_style=False)

    files = {base + "namespace.yaml": dump(stamp(snap.namespace, ns_labels, ns_annotations))}
    for doc in (*snap.quotas, *snap.limits):
        files[base + object_file(doc["kind"], doc["metadata"]["name"])] = dump(stamp(doc, common, obj_annotations))
    return files, replaced


# --------------------------------------------------------------------------- D5, D17: findings of the quotas and limits


@dataclass(frozen=True)
class AdoptionFinding:
    """One finding of an adoption plan: a difference from the instance's rules, reported and never changed."""
    code: str
    path: str
    message: str
    key: str | None = None


def unscoped(quota: Mapping[str, Any]) -> bool:
    """D17: a quota with an empty `scopes` and no scopeSelector expression measures the whole namespace."""
    spec = quota.get("spec") or {}
    selector = (spec.get("scopeSelector") or {}).get("matchExpressions") or []
    return not spec.get("scopes") and not selector


def object_findings(snap: Snapshot, *, cluster_id: str, environment: str, tiers: TierCatalog
                    ) -> tuple[list[AdoptionFinding], dict[str, dict[str, str | None]]]:
    """D5 and D17: the findings of the ResourceQuotas and LimitRanges, and each value beyond the custom tier's bounds
    (key -> {"bound": ..., "requested": ...}), which the approval facts carry as beyondTier."""
    base = folder(cluster_id, snap.namespace["metadata"]["name"])
    out: list[AdoptionFinding] = []
    beyond: dict[str, dict[str, str | None]] = {}
    if not snap.quotas:
        out.append(AdoptionFinding("no-resourcequota", base, "The namespace has no ResourceQuota: none is written. A later "
                                                             "quota request adds one, and its plan shows it"))
    if not snap.limits:
        out.append(AdoptionFinding("no-limitrange", base, "The namespace has no LimitRange: none is written"))
    bounds = tiers.bounds(environment)
    held_unscoped: set[str] = set()
    held_scoped: dict[str, list[str]] = {}
    for q in snap.quotas:
        name = q["metadata"]["name"]
        path = base + object_file("ResourceQuota", name)
        scoped = not unscoped(q)
        for key, value in sorted(((q.get("spec") or {}).get("hard") or {}).items()):
            meaning = INTERPRETED.get(key)
            if meaning is None:
                out.append(AdoptionFinding("uninterpreted-key", path, f"{name} holds {key}: kept as it is, shown raw, and left "
                                                                      "out of cmapi's capacity and quota figures", key))
                continue
            if scoped:
                held_scoped.setdefault(meaning, []).append(name)
                continue
            held_unscoped.add(meaning)
            _bound(out, beyond, bounds, meaning, str(value), path, name)
    for meaning in sorted(set(held_scoped) - held_unscoped):
        out.append(AdoptionFinding("scoped-only", base, f"Only the scoped quotas {', '.join(sorted(held_scoped[meaning]))} hold "
                                                        f"{meaning}: its figure for the namespace is not known", meaning))
    defaults: dict[tuple[str, str], list[str]] = {}
    for lr in snap.limits:
        name = lr["metadata"]["name"]
        path = base + object_file("LimitRange", name)
        for key, value in sorted(flatten_limits(tiers.limits_of([lr])).items()):
            _bound(out, beyond, bounds, key, value, path, name)
        for item in ((lr.get("spec") or {}).get("limits") or []):
            for part in ("default", "defaultRequest"):
                for res in (item.get(part) or {}):
                    defaults.setdefault((str(item.get("type")), f"{part}.{res}"), []).append(name)
    for (kind, what), names in sorted(defaults.items()):
        if len(set(names)) > 1:
            out.append(AdoptionFinding("duplicate-default", base,
                                       f"The LimitRanges {', '.join(sorted(set(names)))} each set the {kind} {what}: Kubernetes "
                                       "does not say which one applies", what))
    return out, beyond


def _bound(out: list[AdoptionFinding], beyond: dict[str, dict[str, str | None]], bounds: Any, key: str, value: str, path: str,
           name: str) -> None:
    lo, hi = bounds.min.get(key), bounds.max.get(key)
    try:
        amount = qty(value)
        below, above = lo is not None and amount < qty(lo), hi is not None and amount > qty(hi)
    except ValueError:
        return
    if below or above:
        bound = lo if below else hi
        word = "below the custom minimum" if below else "above the custom maximum"
        out.append(AdoptionFinding("beyond-custom-bounds", path, f"{name}: {key} is {value}, {word} {bound}: adopted as it "
                                                                 "is; a later change of it is checked and approved as usual", key))
        beyond[key] = {"bound": bound, "requested": value}


# --------------------------------------------------------------------------- D16: the reads before each step


@dataclass(frozen=True)
class Staleness:
    """Why a stored adoption plan no longer holds: `label-removed` cancels the request (the label is the consent), and
    `stale` fails it with adoption-plan-stale. Both name what the read found."""
    code: str
    detail: str


def stale(stored: Mapping[str, Any], live_ns: Mapping[str, Any] | None, live_quotas: Iterable[Mapping[str, Any]],
          live_limits: Iterable[Mapping[str, Any]], settings: AdoptionSettings) -> Staleness | None:
    """D16: None while the live objects are the ones the plan read (the same uid and resourceVersion of each, and no other
    object of the three kinds) and the namespace still carries the opt-in label. cmapi never writes old values over new ones."""
    if live_ns is None:
        return Staleness("stale", "the namespace is no longer on the cluster")
    labels = (live_ns.get("metadata") or {}).get("labels") or {}
    if labels.get(settings.label) != settings.value:
        return Staleness("label-removed", f"{settings.label} was removed from the namespace: the label is the consent")
    want = {(i["kind"], i["name"]): i for i in stored.get("identity") or []}
    have = {(i["kind"], i["name"]): i for i in [identity_of(live_ns, "Namespace"),
                                                 *(identity_of(q, "ResourceQuota") for q in live_quotas),
                                                 *(identity_of(q, "LimitRange") for q in live_limits)]}
    for key in sorted(set(want) | set(have)):
        a, b = want.get(key), have.get(key)
        if a is None:
            return Staleness("stale", f"{key[0]} {key[1]} was created after the plan")
        if b is None:
            return Staleness("stale", f"{key[0]} {key[1]} was deleted after the plan")
        if a["uid"] != b["uid"]:
            return Staleness("stale", f"{key[0]} {key[1]} was deleted and made again after the plan")
        if a["resourceVersion"] != b["resourceVersion"]:
            return Staleness("stale", f"{key[0]} {key[1]} changed after the plan (resourceVersion {a['resourceVersion']} "
                                      f"to {b['resourceVersion']})")
    return None


def takeover_allowed(stored: Mapping[str, Any] | None, live_ns: Mapping[str, Any] | None) -> bool:
    """The delivery's guard against taking over an unmanaged namespace (jobs/apply.py, jobs/watch_sync.py) lets an approved
    adoption through only for the very namespace its plan read: the same uid."""
    if not stored or live_ns is None:
        return False
    uid = next((i["uid"] for i in stored.get("identity") or [] if i["kind"] == "Namespace"), None)
    return bool(uid) and uid == str((live_ns.get("metadata") or {}).get("uid", ""))
