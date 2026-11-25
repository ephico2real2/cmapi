"""The write pipeline (docs/01, Request lifecycle): authorize, idempotency, lock, plan, decide;
on approval, hand over to the worker.

Every write plugin plans through here. The namespace planner is the one examples/local proved;
it is kept as code here with the stand-ins replaced: the folder is read from the Git host, the
store is PostgreSQL, the lock is the partial unique index, and the capacity check is the
CapacityBackend. A plan is pure (no Git write, no row); submit() records it and the first
lifecycle event in one transaction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Mapping

import yaml

from cmapi.core import kube_yaml
from cmapi.core.approvals import BEYOND_FACTS, ApprovalLedger, Requirement
from cmapi.core.capacity_backend import SimulatedCapacity
from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeError
from cmapi.core.config import InstanceConfig, environment_not_served
from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.db.repo import JobRepo, RequestRepo, fingerprint, requirement_to_json
from cmapi.core.errors import Problem
from cmapi.core.etag import if_match_tags
from cmapi.core.git.base import GitUnavailable, HostGitProvider, NotUtf8
from cmapi.core.identity.checks import Requester, resolve_requester
from cmapi.core.identity.claims import Identity, label_value_of
from cmapi.core.identity.directory import CachedDirectory
from cmapi.core.lifecycle import Event as E
from cmapi.core.naming import check_name, check_not_unmanaged, is_label
from cmapi.core.observability import AUTO_APPROVALS, AUTO_FALLBACKS, CHANGE_REQUESTS, ENV_NOT_SERVED, PLUGIN_DISABLED, VALIDATION_FAILURES
from cmapi.core.ports import CapacityBackend, CapacityResult, Finding, Validator
from cmapi.core.validate import ValidatorUnavailable
from cmapi.core.registry import ClusterRegistry
from cmapi.core.render.manifests import (DELETED, ManifestRenderer, NamespaceSpec, diff_files, folder, objects_of, own_quota,
                                         plan_hash, quotas_kept)
from cmapi.core.tiers import EXPOSURE_KEYS, QuotaChange, flatten_limits, qty
from cmapi.plugins.expiration.rules import ExpiryInfo

SYSTEM_PREFIX = "cmapi.net/"


@dataclass
class Plan:
    cluster_id: str
    namespace: str
    env: str
    action: str
    plugin: str
    spec: NamespaceSpec | None
    files: dict[str, str | None]
    prev: dict[str, str]
    changes: dict[str, str]
    requirement: Requirement
    capacity: CapacityResult
    facts: dict[str, Any]
    requester: Requester
    findings: list[Finding]
    base_sha: str
    reason: str | None = None
    etag: str = ""
    warnings: list[str] = field(default_factory=list)
    beyond_tier: dict[str, Any] | None = None      # the new beyond-tier keys of this request and the approvals they add
    metadata: dict[str, Any] | None = None         # a create's final labels and annotations, each with its source (#479)
    metadata_diff: dict[str, Any] | None = None    # a change's effective label and annotation changes, with sources (#481)

    @property
    def hash(self) -> str:
        return plan_hash(self.files)

    def view(self) -> dict[str, Any]:
        r = self.requirement
        return {"changes": self.changes, "planHash": self.hash, "etag": self.etag,
                "requester": {k: v for k, v in self.requester.record().items() if k != "submittedBySub"},
                "capacity": {"status": self.capacity.status, "fresh": self.capacity.fresh,
                             "bindingResource": self.capacity.binding_resource, **dict(self.capacity.detail)},
                "approval": approval_view(r, None),
                "files": {k: v for k, v in self.files.items() if k in self.changes and v is not None},
                "findings": [f.view() for f in self.findings], "beyondTier": self.beyond_tier, "metadata": self.metadata,
                "metadataDiff": self.metadata_diff}

    def stored(self) -> dict[str, Any]:
        """What change_requests.plan holds: enough for the worker to render and verify."""
        return {"files": self.files, "prev": self.prev, "changes": self.changes, "facts": self.facts,
                "capacity": {"status": self.capacity.status, "fresh": self.capacity.fresh, **dict(self.capacity.detail)},
                "spec": _spec_json(self.spec), "findings": [f.view() for f in self.findings],
                "beyondTier": self.beyond_tier}


def _spec_json(spec: NamespaceSpec | None) -> dict[str, Any] | None:
    if spec is None:
        return None
    d = asdict(spec)
    d["expires_at"] = spec.expires_at.isoformat() if spec.expires_at else None
    return d


def folder_etag(files: Mapping[str, str]) -> str:
    """The ETag of a namespace: a hash of its folder's content, stable until the folder changes, and "0" for no files.

    A strong validator changes with every change of the content (RFC 9110 section 8.8.1). plan_hash writes an empty file
    as DELETED and ends each path and content with NUL, so a file holding DELETED or a NUL read as another folder (#584);
    a Git path has no NUL. Only such a folder is hashed from JSON, unambiguous for Git's strict UTF-8 (no lone surrogate).
    Every other folder keeps its tag; a tag given for such a folder before #584 still matches the folder it read as."""
    if not files:
        return "0"
    if any(text == DELETED or "\0" in text for text in files.values()):
        identity = "folder-v2:" + json.dumps(sorted(files.items()), separators=(",", ":"))
    else:
        identity = plan_hash(files)
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def require_if_match(if_match: str | None, write: str) -> None:
    """428 when a write to an existing namespace has no If-Match (RFC 6585 section 3), or has `*`. The plan checks it after
    the namespace is found (404 first, as RFC 9110 section 13.2.1 orders a precondition after the resource). The routes also
    check it on an Idempotency-Key replay, which never reaches the plan (#495). The ETag comparison is not repeated
    there, so a replay carrying its first ETag still returns the original request, in its current state, after Git moved.

    `*` departs on purpose from RFC 9110 section 13.1.1, step 1, where it holds for any resource that exists (the owner,
    #571): it proves no read, and cmapi requires If-Match so that clients "are working with the correct copies" (RFC 6585
    section 3). So it is refused here, on a replay as on a first request.

    Only SP and HTAB pad `*` (OWS, RFC 9110 section 5.6.3). str.strip() with no argument would also take U+0085 and U+00A0,
    which Starlette's latin-1 decode gives for the obs-text octets 0x85 and 0xA0, and those are opaque data (section 5.5),
    not whitespace (#581)."""
    if if_match is None:
        raise Problem(428, "precondition-required", f"If-Match is required on a {write}; GET the namespace for its etag")
    if if_match.strip(" \t") == "*":
        raise Problem(428, "precondition-required", f"If-Match must name the namespace's etag, not *, on a {write}; "
                                                    "GET the namespace for its etag")


def check_if_match(if_match: str | None, etag: str, write: str) -> None:
    """The precondition of a change or a delete of an existing namespace (RFC 9110 section 13.1.1): 428 without If-Match or
    with `*` (require_if_match), then 412 unless one strong tag it lists is the namespace's etag. Each 412 carries the
    current `etag`; its detail says whether the value listed no tag that could match, or the namespace changed."""
    require_if_match(if_match, write)
    tags = if_match_tags(if_match or "")
    if not tags:
        raise Problem(412, "precondition-failed", "If-Match lists no strong entity tag: send the namespace's etag from GET "
                                                  "in double quotes", extra={"etag": etag})
    if etag not in tags:
        raise Problem(412, "precondition-failed", "The namespace changed in Git since you read it", extra={"etag": etag})


def approval_view(req: Requirement | None, ledger: ApprovalLedger | None) -> dict[str, Any] | None:
    if req is None:
        return None
    return {"rule": req.rule, "auto": req.auto, "autoFallback": req.auto_fallback, "selfApproval": req.self_approval,
            "timeoutHours": req.timeout_hours,
            "slots": [{"group": s.group, "count": s.count, "reason": s.reason} for s in req.slots],
            "remaining": ledger.remaining() if ledger else [{"group": s.group, "needed": s.count} for s in req.slots],
            "approvals": [{"username": e["username"], "sub": e.get("sub"), "comment": e.get("comment", ""),
                           "relayedBy": e.get("relayedBy"), "at": e.get("at")} for e in (ledger.entries if ledger else [])],
            "reasons": list(req.reasons)}


class Pipeline:
    def __init__(self, cfg: InstanceConfig, registry: ClusterRegistry, git: HostGitProvider, validator: Validator,
                 capacity: CapacityBackend | SimulatedCapacity, directory: CachedDirectory | None,
                 reserved_patterns: list[str], auto_paused: Any = lambda: False):
        self.cfg, self.registry, self.git, self.validator = cfg, registry, git, validator
        self.capacity, self.directory, self.reserved = capacity, directory, reserved_patterns
        self.renderer = ManifestRenderer(cfg.tiers, cfg.metadata)
        self.auto_paused = auto_paused
        self.identity = cfg.raw_instance["instance"].get("identity", {})

    # ---- who
    def requester_for(self, who: Identity, on_behalf_of: str | None) -> Requester:
        return resolve_requester(who, on_behalf_of, self.directory, self.identity.get("requireEmployeeId", True),
                                 self.identity.get("requireOnBehalfOf", False),
                                 self.identity.get("automationRoles", ["cmapi-onboarding"]))

    def environment_of(self, cluster_id: str) -> str:
        st = self.registry.get(cluster_id)
        if st.policy is None:
            raise Problem.unprocessable("cluster-not-writable", f"{cluster_id} is imported but has no clusters.yaml entry")
        return st.policy.environment

    def check_env_served(self, env: str) -> None:
        if env in self.cfg.allowed_environments:
            return
        ENV_NOT_SERVED.labels(env).inc()
        raise environment_not_served(self.cfg, env)

    def check_plugin_offered(self, plugin: str, env: str) -> None:
        """Refuse a write of a plugin that plugins.yaml disables in this environment of this instance."""
        if self.cfg.plugins.offers(plugin, env):
            return
        PLUGIN_DISABLED.labels(plugin, env).inc()
        raise Problem.unprocessable("plugin-disabled", f"The {plugin} plugin takes no writes in {env} on the {self.cfg.name} "
                                                       "instance: plugins.yaml disables it there",
                                    plugin=plugin, environment=env)

    def _read_folder(self, cluster_id: str, ns: str) -> tuple[dict[str, str], str]:
        if not is_label(ns):              # a path parameter such as "..": never a folder, never sent to the Git host
            raise Problem(404, "object-not-found", f"{ns!r} is not a namespace name")
        try:
            files, sha = self.git.read_folder(folder(cluster_id, ns))
        except GitUnavailable as exc:
            raise Problem(502, "git-unavailable", str(exc)[:300]) from exc
        except NotUtf8 as exc:
            raise folder_not_utf8(ns, exc) from exc
        # Every reader of the folder parses it with kube_yaml.load_all; a file it cannot parse is refused once, here (#680).
        errors = {}
        for path in sorted(files):
            try:
                kube_yaml.load_all(files[path])
            except yaml.YAMLError as exc:
                errors[path] = exc
        if errors:
            raise folder_not_yaml(ns, errors)
        return files, sha

    def removable_folder(self, cluster_id: str, ns: str, ref: str) -> dict[str, str]:
        """Every path a delete of the namespace removes: each file of its folder at ref, at any depth, whatever made it (#616).
        A submodule is refused: its removal also changes .gitmodules at the repository's root, outside the folder, which the
        request branch never touches."""
        try:
            listed, _ = self.git.list_folder(folder(cluster_id, ns), ref)
        except GitUnavailable as exc:
            raise Problem(502, "git-unavailable", str(exc)[:300]) from exc
        except NotUtf8 as exc:
            raise folder_not_utf8(ns, exc) from exc
        submodules = sorted(p for p, kind in listed.items() if kind == "commit")
        if submodules:
            raise Problem.conflict("folder-holds-submodule",
                                   f"The folder of {ns} holds the submodule {submodules[0]}: cmapi removes files, not submodules. "
                                   "Remove it in Git, then delete the namespace", paths=submodules)
        return listed

    def workload_counts(self, cluster_id: str, ns: str) -> tuple[int, int]:
        """Pods and PVCs in a namespace, for the delete thresholds. A live read: unknown is 503, never 0."""
        client = self.registry.cache(cluster_id).client
        try:
            # `items` without a default: KubeClient.list refuses an answer without it (#421), so none counts as 0 workloads.
            return (len(client.list("Pod", namespace=ns)["items"]),
                    len(client.list("PersistentVolumeClaim", namespace=ns)["items"]))
        except (ClusterUnreachable, KubeError, BadResponse) as exc:
            raise Problem(503, "cluster-unreachable", f"Cannot count the workloads in {ns}: {str(exc)[:200]}",
                          extra={"retryAfter": 30}) from exc

    # ---- plan a create or update
    def plan_namespace(self, who: Identity, cluster_id: str, body: Mapping[str, Any], *, action: str,
                       if_match: str | None = None, reason: str | None = None) -> Plan:
        try:
            return self._plan_namespace(who, cluster_id, body, action=action, if_match=if_match, reason=reason)
        except Problem as exc:
            count_refusal(exc)
            raise

    def _plan_namespace(self, who: Identity, cluster_id: str, body: Mapping[str, Any], *, action: str,
                        if_match: str | None = None, reason: str | None = None) -> Plan:
        st = self.registry.writable(cluster_id)
        env = st.policy.environment
        self.check_env_served(env)
        ns = body["namespace"]
        self.cfg.roles.require(who, "namespaces:create" if action == "create" else "namespaces:write", env)
        self.check_plugin_offered("namespaces", env)
        cache = self.registry.cache(cluster_id)
        if action == "create":
            check_name(ns, self.reserved)
            check_not_unmanaged(ns, cache.namespace(ns))
        requester = self.requester_for(who, body.get("onBehalfOf"))
        if action == "create":
            # The label is only written at create; refuse here, not as a 422 from the API server at apply. The refusal is
            # explicit: a ValueError that escapes a route is the service's fault, 500 internal-error (#648).
            try:
                label_value_of(requester.person.username)
            except ValueError as exc:
                raise Problem.unprocessable("validation-failed", str(exc)[:300]) from exc
        operator = self.cfg.roles.is_operator(who, env)
        prev_files, base_sha = self._read_folder(cluster_id, ns)
        prev_ns = namespace_doc(prev_files)
        if action == "create" and prev_ns:
            raise Problem.conflict("namespace-exists", f"{ns} is already in Git")
        if action != "create" and not prev_ns:
            raise Problem(404, "object-not-found", f"{ns} is not managed on {cluster_id}")
        etag = folder_etag(prev_files)
        if action != "create":
            check_if_match(if_match, etag, "change")
        cur_l, cur_a = self._kept_metadata(prev_ns, "label"), self._kept_metadata(prev_ns, "annotation")
        labels, anns = dict(body.get("labels") or {}), dict(body.get("annotations") or {})
        sent = {"label": dict(labels), "annotation": dict(anns)}
        # The request's target: cmapi fills each value.from key of metadata-keys.yaml from it, never from the body.
        sources = {"namespace": ns, "environment": env, "cluster": cluster_id, "instance": self.cfg.name}
        # cmapi's own metadata check is the refusal in every policy mode and with no Kyverno at all (#342). A refused body is
        # still rendered and validated, so the 422 lists what the validator found beside cmapi's errors: in audit, Kyverno's
        # warning on the same value. Anything that fails after the refusal came from the refused body, and the refusal stands,
        # as it did when the check stopped the plan here.
        refusal = self._metadata_refusal(labels, anns, operator=operator, current_labels=cur_l, current_annotations=cur_a,
                                         sources=sources, existing=prev_ns is not None, create=action == "create")
        metadata_view = None
        if action == "create":
            # Steps 1 and 2 of the check (#479): what cmapi fills in is rendered, and the dry run says where each value came from.
            filled = self.cfg.metadata.filled(labels, anns, sources)
            by_kind = self.cfg.metadata.value_sources(labels, anns, filled)
            metadata_view = {"namespace": ns, "labels": by_kind["label"], "annotations": by_kind["annotation"]}
            labels, anns = filled["label"], filled["annotation"]
        labels = self.cfg.metadata.merge_patch(cur_l, labels)
        anns = self.cfg.metadata.merge_patch(cur_a, anns)

        try:
            old_tier = (prev_ns or {}).get("metadata", {}).get("labels", {}).get("cmapi.net/tier")
            old_exp = (prev_ns or {}).get("metadata", {}).get("annotations", {}).get("cmapi.net/expires-at")
            quotas = objects_of(prev_files, "ResourceQuota")
            old_rq = own_quota(quotas, ns)
            old_quota = _hard(old_rq)
            tier = body.get("tier") or old_tier or "small"
            quota, limits = body.get("quota"), body.get("limitRange")
            # D9 (#250): with several ResourceQuotas the plan cannot tell which one a request means, and when none is cmapi's
            # own it keeps them all with every LimitRange, so a change of the quota, the tier or (then) the limits is refused.
            quotas_held = quotas_kept(quotas, ns)
            if len(quotas) > 1 and (quota or (old_tier is not None and tier != old_tier) or (quotas_held and limits)):
                raise several_quotas(ns, quotas, kept=quotas_held)
            # A change that sends no expiry keeps the date that Git holds, also where expiration is off now (#479).
            kept = date.fromisoformat(old_exp) if old_exp and action != "create" else None
            expires = _date(body["expiresAt"]) if body.get("expiresAt") else kept
            exp_facts: dict[str, Any] = {}
            if action == "create":
                p = self.cfg.expiration.plan_create(env, expires, date.today()) if expires else None
                if p:
                    exp_facts = p.facts()
            elif body.get("extendDays") or body.get("extendUntil") or body.get("expiresAt") or body.get("makePermanent"):
                # maxLifetimeDays counts from the day the namespace was created on its cluster (docs/01, Namespace expiration).
                # A namespace that is not on the cluster yet counts from today, as a create does. A cluster that cannot be read
                # is a 503 from the cache, never a lifetime of zero days: that would skip approver-platform.
                created = created_day(cache.namespace(ns)) or date.today()
                info = ExpiryInfo(ns, env, created=created, expires_at=date.fromisoformat(old_exp) if old_exp else None)
                if body.get("makePermanent"):
                    p = self.cfg.expiration.plan_make_permanent(info)
                    expires = None
                elif body.get("extendDays") or body.get("extendUntil"):
                    # :extend moves the date that exists, by days or to a date; :set (expiresAt) gives a permanent one its first.
                    p = self.cfg.expiration.plan_extend(info, date.today(),
                                                        days=int(body["extendDays"]) if body.get("extendDays") else None,
                                                        until=_date(body["extendUntil"]) if body.get("extendUntil") else None)
                    expires = p.new_date
                else:
                    p = self.cfg.expiration.plan_set(info, expires, date.today())
                    expires = p.new_date
                exp_facts = p.facts()
            resolved = self.cfg.tiers.resolve(env, tier)
            custom_before = bool(old_tier) and self.cfg.tiers.resolve(env, old_tier).custom
            # The custom values that Git holds: the sizable keys, and each key that the objects name as beyond the tier.
            # A change merges the request over them, key by key, so a change of one label keeps the approved sizes (#214).
            approved: dict[str, str] = {}
            if custom_before and old_quota:
                approved = {**{k: v for k, v in old_quota.items() if k in self.cfg.tiers.sizable},
                            **self.cfg.tiers.rendered_overrides(old_rq, objects_of(prev_files, "LimitRange"))}
            if resolved.custom and custom_before:
                quota = {**{k: v for k, v in approved.items() if not k.startswith("limitRange.")}, **(quota or {})}
                limits = _merge_limits(approved, limits)
            if quotas_held:
                # Nothing of the tier is rendered (manifests.quotas_kept), so the plan has no quota or limits to size or check.
                hard, limit_range = {}, {}
            else:
                hard = self.cfg.tiers.quota_for(env, tier, quota, approved)
                limit_range = self.cfg.tiers.limits_for(env, tier, limits, hard, approved)
            spec = NamespaceSpec(namespace=ns, cluster_id=cluster_id, instance=self.cfg.name, env=env, tier=tier,
                                 request_id="(planned)", requested_by_user=requester.person.username.lower(),
                                 requested_by_email=requester.email, labels=labels, annotations=anns,
                                 quota=quota if resolved.custom else None, limit_range=limits if resolved.custom else None,
                                 approved=approved if resolved.custom else {}, expires_at=expires,
                                 service_accounts=_service_accounts(prev_files), grants=_grants(prev_files, scc=False),
                                 scc_grants=_grants(prev_files, scc=True))
            files = self.renderer.render(spec, previous=prev_files)
            changes = {p: s for p, s in diff_files(prev_files, files).items() if s != "unchanged"}
            if not changes:
                raise Problem.unprocessable("no-change", "The request changes nothing")
            try:
                findings = self.validator.validate(files, cluster_id, env, previous=prev_files)
            except ValidatorUnavailable as exc:
                raise Problem(503, "validator-unavailable", str(exc)[:300], extra={"retryAfter": 60}) from exc
        except Exception as exc:
            if refusal is None:
                raise
            raise refusal from exc
        if refusal is not None:
            refusal.extra["findings"] = [f.view() for f in findings]
            raise refusal
        errors = [f for f in findings if f.severity == "error"]
        if errors:
            raise Problem.policy_violation("Rendered files failed validation",
                                           [{"code": f.rule, "source": f.source, "path": f.path, "detail": f.message,
                                             "kyvernoRule": f.kyverno_rule} for f in errors],
                                           findings=[f.view() for f in findings if f.severity != "error"])
        metadata_diff = None
        if action != "create":
            metadata_diff = self.cfg.metadata.metadata_diff(metadata_of(prev_ns), metadata_of(namespace_doc(files)), sent)
            findings = [*findings, *self._environment_moved(cluster_id, ns, prev_ns, env)]
        if action == "update" and reason is None:
            # A PATCH, whose body can add a key: the expiry calls (reason expiration:...) cannot, so they get no finding.
            findings = [*findings, *self._held_key_findings(cluster_id, ns, labels, anns)]
        old_hard = {}
        if old_tier and not quotas_held:
            # A custom namespace: what Git holds, as it is. It was approved, so no bound is checked again (#214).
            old_hard = dict(old_quota or {}) if custom_before else self.cfg.tiers.quota_for(env, old_tier)
        cpu_delta = float(qty(hard.get("requests.cpu", "0")) - qty(old_hard.get("requests.cpu", "0")))
        mem_delta = float(qty(hard.get("requests.memory", "0")) - qty(old_hard.get("requests.memory", "0")))
        cap = self.capacity.check(cluster_id, env, max(cpu_delta, 0), max(mem_delta, 0))
        if cap.status == "exceeded":
            raise Problem.unprocessable("capacity-exceeded", f"{cap.binding_resource} would exceed the cluster",
                                        capacity=dict(cap.detail))
        facts = {"plugin": "namespaces", "action": action, "environment": env, "namespace": ns, "clusterId": cluster_id,
                 "team": labels.get("cmapi.net/team"), "tier": tier, "capacity": cap.status, "capacityFresh": cap.fresh,
                 "automated": requester.automated, "requesterClient": who.client_id if who.kind == "service" else None,
                 "clusterLabels": dict(st.policy.labels), "warnings": [f.message for f in findings], "reason": reason,
                 **exp_facts, **self.cfg.metadata.change_facts(cur_l, labels, cur_a, anns, existing=prev_ns is not None)}
        if quotas_held:
            # The tier is the one Git holds (a move is refused above) and no quota changes.
            facts.update(QuotaChange("custom" if resolved.custom else "same", {}, {}).facts())
        elif old_tier and action != "create":
            facts.update(self.cfg.tiers.compare(env, old_tier, old_hard or hard, tier, hard).facts())
        # Beyond the tier: each overridable value that differs from the tier and from the value that Git holds. A value that
        # was approved before is not beyond the tier again.
        beyond = {k: v for k, v in self.cfg.tiers.beyond(env, tier, hard, limit_range).items()
                  if k not in approved or qty(approved[k]) != qty(v["requested"])}
        # Network exposure: the new quota has more load balancers or NodePorts than Git holds (for a new namespace: than the
        # tier gives). It does not depend on the beyond-tier keys: a change to a tier with a higher value raises it too.
        exposure_base = hard if quotas_held else (old_quota or {}) if old_tier else resolved.quota
        raised = [k for k in sorted(EXPOSURE_KEYS) if qty(hard.get(k, "0")) > qty(exposure_base.get(k, "0"))]
        facts.update({"beyondTier": bool(beyond), "beyondTierKeys": sorted(beyond), "networkExposure": bool(raised)})
        requirement = self._decide(facts)
        beyond_view = None
        if beyond:
            added = self.cfg.approvals.added_for(facts, BEYOND_FACTS)
            beyond_view = {"keys": [{"key": k, **beyond[k]} for k in sorted(beyond)],
                           "approvals": [{"group": s.group, "count": s.count, "reason": s.reason} for s in added]}
        return Plan(cluster_id, ns, env, action, "namespaces", spec, files, prev_files, changes, requirement, cap, facts,
                    requester, findings, base_sha, reason=reason, etag=etag, warnings=[f.message for f in findings],
                    beyond_tier=beyond_view, metadata=metadata_view, metadata_diff=metadata_diff)

    def _kept_metadata(self, prev_ns: Mapping[str, Any] | None, kind: str) -> dict[str, str]:
        """The keys of one kind that Git holds and a change merges its patch over: every key but a system one, which the
        renderer writes again from the spec. An operator-only key (cmapi.net/protected) is kept, so a change that does not
        name it keeps it, and only an operator's patch sets or removes it (#374). A reserved, adoption or disallowed key
        is kept as Git holds it, and no request may send one (#481, design section 3)."""
        held = metadata_of(prev_ns)[kind]
        return {k: v for k, v in held.items() if self.cfg.metadata.classify(k, kind) != "system"}

    def _environment_moved(self, cluster_id: str, ns: str, prev_ns: Mapping[str, Any] | None, env: str) -> list[Finding]:
        """A warning when Git's cmapi.net/env is not the cluster's environment any more: the renderer writes the system
        label from the cluster, while each automatic key (app-environment) stays as Git holds it (#481, design section
        3, row 5), and metadataDiff lists neither, since a system key is not one that a request names."""
        held = metadata_of(prev_ns)["label"].get("cmapi.net/env")
        if not held or held == env:
            return []
        return [Finding("cmapi", "environment_moved", folder(cluster_id, ns) + "namespace.yaml",
                        f"Git holds the environment {held} and the cluster is now {env}: this change writes {env}",
                        "warning")]

    def _held_key_findings(self, cluster_id: str, ns: str, labels: Mapping[str, str],
                           annotations: Mapping[str, str]) -> list[Finding]:
        """Each required key that the namespace lacks and the change leaves out: held, not refused (#234), and reported as
        a warning (#481, design section 3, the adoption finding): that this change can add it, or, for a key that a change
        cannot set (fixed or automatic in x-cmapi-edit), that adoption must."""
        path = folder(cluster_id, ns) + "namespace.yaml"
        findings = []
        for kind, key in self.cfg.metadata.missing_required(labels, annotations):
            mode = self.cfg.metadata.edit_rule(kind, key)["mode"]
            remedy = "adoption must supply it" if mode in ("fixed", "automatic") else "this change can add it"
            findings.append(Finding("cmapi", "missing_required_key", path,
                                    f"the {kind} {key} is required and the namespace lacks it: {remedy}", "warning"))
        return findings

    def _metadata_refusal(self, labels: Mapping[str, Any], annotations: Mapping[str, Any], **kw: Any) -> Problem | None:
        """cmapi's own metadata check: the policy-violation it refuses with, or None. A key that only an operator may set
        is a 403 at once: that request is never rendered.

        A label of protected.labels (approval-rules.yaml) takes only the value that protects, or null to remove it (#366):
        another value ("false") would be stored and shown while the namespace stays deletable."""
        want = self.cfg.approvals.protected_values()
        protection = [{"code": "invalid_value", "key": k, "kind": "label",
                       "detail": f"only {want[k]!r}, the value that protects; null removes it"}
                      for k, v in labels.items() if k in want and v is not None and v != want[k]]
        try:
            self.cfg.metadata.check(labels, annotations, **kw)
        except Problem as refusal:
            if refusal.code != "policy-violation":
                raise
            refusal.errors.extend(protection)
            return refusal
        return Problem.policy_violation("Metadata refused", protection) if protection else None

    def _decide(self, facts: Mapping[str, Any], team_auto_today: int = 0) -> Requirement:
        # Refused here, before the rules, so the answer names the instance that serves the environment (#671). The revert job
        # reaches this with an environment from a stored request, which a later configuration may no longer serve.
        if facts["environment"] not in self.cfg.allowed_environments:
            raise environment_not_served(self.cfg, facts["environment"])
        req = self.cfg.approvals.decide(facts, paused=bool(self.auto_paused()), team_auto_today=team_auto_today)
        if req.auto_fallback:
            AUTO_FALLBACKS.labels(req.auto_fallback).inc()
        return req

    # ---- plan a delete
    def plan_delete(self, who: Identity, cluster_id: str, ns: str, *, if_match: str | None, reason: str | None = None,
                    extra_facts: Mapping[str, Any] | None = None) -> Plan:
        st = self.registry.writable(cluster_id)
        env = st.policy.environment
        self.check_env_served(env)
        self.cfg.roles.require(who, "namespaces:write", env)
        self.check_plugin_offered("namespaces", env)
        requester = self.requester_for(who, None)
        prev, base_sha = self._read_folder(cluster_id, ns)
        ns_doc = namespace_doc(prev)
        if ns_doc is None:
            raise Problem(404, "object-not-found", f"{ns} is not managed on {cluster_id}")
        etag = folder_etag(prev)
        if reason != "expired":
            check_if_match(if_match, etag, "delete")
        removed = self.removable_folder(cluster_id, ns, base_sha)
        labels = ns_doc["metadata"].get("labels", {})
        live = None
        try:
            live = self.registry.cache(cluster_id).namespace(ns)
        except Problem:
            pass
        age_days = 0
        if live and live.get("metadata", {}).get("creationTimestamp"):
            created = date.fromisoformat(live["metadata"]["creationTimestamp"][:10])
            age_days = (date.today() - created).days
        pods, pvcs = self.workload_counts(cluster_id, ns)
        facts = {"plugin": "namespaces", "action": "delete", "environment": env, "namespace": ns, "clusterId": cluster_id,
                 "team": labels.get("cmapi.net/team"), "automated": requester.automated,
                 "requesterClient": who.client_id if who.kind == "service" else None,
                 "protected": self.cfg.approvals.is_protected(labels), "namespaceAgeDays": age_days,
                 "pods": pods, "pvcs": pvcs, "reason": reason, "clusterLabels": dict(st.policy.labels),
                 **(extra_facts or {})}
        requirement = self._decide(facts)
        files = self.renderer.delete(cluster_id, ns, removed)
        cap = CapacityResult("fits", True, None, {"source": "delete"})
        return Plan(cluster_id, ns, env, "delete", "namespaces", None, files, prev, {p: "removed" for p in files},
                    requirement, cap, facts, requester, [], base_sha, reason=reason, etag=etag)

    # ---- record it
    def submit(self, who: Identity, plan: Plan, repo: RequestRepo, jobs: JobRepo, *, idempotency_key: str | None,
               body_fingerprint: str, justification: str | None) -> ChangeRequestRow:
        rid = repo.next_id()              # takes the day's advisory lock: submits are serial from here to the commit
        if plan.action != "delete" and plan.facts.get("team"):
            # the daily allowance is counted at submit, under that lock, against the rows already recorded
            plan.requirement = self._decide(plan.facts, team_auto_today=repo.auto_approvals_today(plan.facts["team"]))
        files = plan.files
        if plan.spec is not None:
            plan.spec.request_id = rid
            files = self.renderer.render(plan.spec, previous=plan.prev)
            plan.files = files
        req = plan.requirement
        row = ChangeRequestRow(
            request_id=rid, instance=self.cfg.name, cluster_id=plan.cluster_id, namespace=plan.namespace, env=plan.env,
            plugin=plan.plugin, action=plan.action, status="", reason=plan.reason, justification=justification,
            team=plan.facts.get("team"), plan=plan.stored(), plan_hash=plan_hash(files), base_sha=plan.base_sha,
            requirement=requirement_to_json(req), requester=plan.requester.record(), requester_sub=plan.requester.sub,
            requester_kind=who.kind, requester_client=who.client_id, requester_username=plan.requester.username,
            idempotency_key=idempotency_key, idempotency_fingerprint=body_fingerprint,
            # The key is the caller's, which `_replay` looks up (#592): the service, not the person, with onBehalfOf.
            idempotency_sub=who.sub if idempotency_key else None)
        auto = req.approved_at_plan
        note = req.auto or f"waiting for {[(s.group, s.count) for s in req.slots]}"
        repo.insert(row, E.PLAN_AUTO_APPROVED if auto else E.PLAN_NEEDS_APPROVAL, who.username, note)
        CHANGE_REQUESTS.labels(plan.plugin, plan.action, plan.env, row.status).inc()
        if auto:
            if req.auto and req.auto.startswith("auto:"):
                AUTO_APPROVALS.labels(req.auto.removeprefix("auto:"), plan.env).inc()
            jobs.enqueue("push_branch", request_id=rid, cluster_id=plan.cluster_id)
        else:
            jobs.enqueue("channel_notify", request_id=rid, cluster_id=plan.cluster_id, payload={"kind": "pending"})
        return row


# The refusals of cmapi's own checks that are a verdict on the request (#302): its names and its expiry. A policy-violation
# counts each of its errors by its source (cmapi's metadata check, or the validator's kubeconform and Kyverno).
CMAPI_REFUSALS = frozenset({"reserved-namespace", "invalid-namespace-name", "expiration-not-allowed", "expiration-limit",
                            "expiration-in-past"})


def folder_not_utf8(ns: str, exc: NotUtf8) -> Problem:
    """409: the folder in Git holds a path that no plan can carry (#626). A conflict with the folder's state that the caller can
    resolve in Git and then send again (RFC 9110, section 15.5.10), as folder-holds-submodule is. Nothing is planned."""
    shown = ", ".join(exc.paths[:3]) + (f" and {len(exc.paths) - 3} more" if len(exc.paths) > 3 else "")
    action = "Rename it" if exc.part == "name" else "Write it again as UTF-8"
    return Problem.conflict("folder-not-utf8", f"The folder of {ns} holds {shown}, whose {exc.part} {exc.rule}: cmapi carries a "
                                               f"folder's names and manifests as UTF-8 text. {action} in Git, then send the request "
                                               "again", paths=exc.paths)


def folder_not_yaml(ns: str, errors: Mapping[str, yaml.YAMLError]) -> Problem:
    """409: a manifest of the folder is not YAML (#680), so no plan can read the namespace. A conflict with the folder's state
    that the caller resolves in Git and then sends again (RFC 9110, section 15.5.10), as folder-not-utf8 is. The detail names
    the first file and where PyYAML stopped (a MarkedYAMLError's problem and mark); `paths` names each file."""
    paths = sorted(errors)
    first = errors[paths[0]]
    mark = getattr(first, "problem_mark", None)
    where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
    what = getattr(first, "problem", None) or type(first).__name__
    more = f" and {len(paths) - 1} more" if len(paths) > 1 else ""
    return Problem.conflict("folder-not-yaml", f"The folder of {ns} holds {paths[0]}{more}, which is not YAML: {what}{where}. "
                                               "Correct it in Git, then send the request again", paths=paths)


def several_quotas(ns: str, quotas: list[dict[str, Any]], *, kept: bool) -> Problem:
    """409: the folder holds several ResourceQuotas, and the request changes the quota or the tier (or, when none of them is
    cmapi's own, the limits) without naming the object it changes (the adoption design's D9, #250). A conflict with the
    folder's state that the caller can resolve and send again (RFC 9110, section 15.5.10), as folder-holds-submodule is. The
    problem names the objects. Nothing is planned."""
    names = sorted(str((q.get("metadata") or {}).get("name")) for q in quotas)
    what = (f"none is cmapi's own {ns}-quota, so a change of the quota, the tier or the limits" if kept
            else "a change of the quota or the tier")
    return Problem.conflict("several-resource-quotas",
                            f"The folder of {ns} holds {len(names)} ResourceQuotas, {', '.join(names)}: {what} must name the "
                            "object it changes, and a request cannot name one. Change only labels, annotations or the expiry, or "
                            "leave one ResourceQuota in the folder in Git, then send the request again", resourceQuotas=names)


def count_refusal(problem: Problem) -> None:
    """cmapi_validation_failures_total{source}: one for each error of a policy-violation, and one for each other refusal of
    CMAPI_REFUSALS. Before #302 only the validator's errors were counted, and cmapi's own refusals, raised first, were not."""
    if problem.code == "policy-violation":
        for error in problem.errors or [{}]:
            VALIDATION_FAILURES.labels(error.get("source") or "cmapi").inc()
    elif problem.code in CMAPI_REFUSALS:
        VALIDATION_FAILURES.labels("cmapi").inc()


def namespace_doc(files: Mapping[str, str | None]) -> dict[str, Any] | None:
    """The Namespace object of a folder's namespace.yaml, from any document of it (#250), or None when the folder has none."""
    text = next((t for p, t in files.items() if p.endswith("/namespace.yaml") and t), None)
    return next((d for d in kube_yaml.load_all(text) if d.get("kind") == "Namespace"), None)


def metadata_of(doc: Mapping[str, Any] | None) -> dict[str, dict[str, str]]:
    """{label: ..., annotation: ...} of a Namespace object; empty maps for none."""
    meta = (doc or {}).get("metadata") or {}
    return {"label": dict(meta.get("labels") or {}), "annotation": dict(meta.get("annotations") or {})}


def _date(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def created_day(obj: Mapping[str, Any] | None) -> date | None:
    """The UTC day a namespace was created on its cluster (metadata.creationTimestamp), or None when it is not known."""
    stamp = ((obj or {}).get("metadata") or {}).get("creationTimestamp")
    try:
        return date.fromisoformat(str(stamp)[:10]) if stamp else None
    except ValueError:
        return None


def _hard(doc: Mapping[str, Any] | None) -> dict[str, str] | None:
    if not doc:
        return None
    return {k: str(v) for k, v in (doc.get("spec", {}).get("hard") or {}).items()}


def _merge_limits(approved: Mapping[str, str], asked: Mapping[str, Any] | None) -> dict[str, dict[str, dict[str, str]]] | None:
    """The request's limitRange over the approved limit values of the namespace, as the nested object that a request sends."""
    flat = {**{k: v for k, v in approved.items() if k.startswith("limitRange.")}, **flatten_limits(asked)}
    out: dict[str, dict[str, dict[str, str]]] = {}
    for key, value in flat.items():
        kind, part, res = key.removeprefix("limitRange.").split(".", 2)
        out.setdefault(kind, {}).setdefault(part, {})[res] = value
    return out or None


def _service_accounts(prev: Mapping[str, str]) -> list[str]:
    text = next((t for p, t in prev.items() if p.endswith("serviceaccounts.yaml")), None)
    return [d["metadata"]["name"] for d in kube_yaml.load_all(text)]


def _grants(prev: Mapping[str, str], *, scc: bool) -> list[tuple[str, str]]:
    text = next((t for p, t in prev.items() if p.endswith("/rolebindings.yaml")), None)
    out: list[tuple[str, str]] = []
    for d in kube_yaml.load_all(text):
        role = d["roleRef"]["name"]
        sa = d["subjects"][0]["name"]
        is_scc = role.startswith("system:openshift:scc:")
        if is_scc == scc:
            out.append((sa, role.removeprefix("system:openshift:scc:") if scc else role))
    return out


__all__ = ["CMAPI_REFUSALS", "Pipeline", "Plan", "approval_view", "count_refusal", "folder_etag", "fingerprint", "metadata_of",
           "folder_not_yaml", "namespace_doc", "several_quotas"]
