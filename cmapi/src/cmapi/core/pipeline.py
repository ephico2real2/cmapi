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
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Mapping

import yaml

from cmapi.core.approvals import BEYOND_FACTS, ApprovalLedger, Requirement
from cmapi.core.capacity_backend import SimulatedCapacity
from cmapi.core.clients.kube import ClusterUnreachable, KubeError
from cmapi.core.config import InstanceConfig
from cmapi.core.db.models import ChangeRequestRow
from cmapi.core.db.repo import JobRepo, RequestRepo, fingerprint, requirement_to_json
from cmapi.core.errors import Problem
from cmapi.core.git.base import GitUnavailable, HostGitProvider
from cmapi.core.identity.checks import Requester, resolve_requester
from cmapi.core.identity.claims import Identity, label_value_of
from cmapi.core.identity.directory import CachedDirectory
from cmapi.core.lifecycle import Event as E
from cmapi.core.naming import check_name, check_not_unmanaged, is_label
from cmapi.core.observability import AUTO_APPROVALS, AUTO_FALLBACKS, CHANGE_REQUESTS, ENV_NOT_SERVED, PLUGIN_DISABLED, VALIDATION_FAILURES
from cmapi.core.ports import CapacityBackend, CapacityResult, Finding, Validator
from cmapi.core.validate import ValidatorUnavailable
from cmapi.core.registry import ClusterRegistry
from cmapi.core.render.manifests import ManifestRenderer, NamespaceSpec, diff_files, folder, plan_hash
from cmapi.core.tiers import EXPOSURE_KEYS, flatten_limits, qty
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
                "findings": [asdict(f) for f in self.findings], "beyondTier": self.beyond_tier}

    def stored(self) -> dict[str, Any]:
        """What change_requests.plan holds: enough for the worker to render and verify."""
        return {"files": self.files, "prev": self.prev, "changes": self.changes, "facts": self.facts,
                "capacity": {"status": self.capacity.status, "fresh": self.capacity.fresh, **dict(self.capacity.detail)},
                "spec": _spec_json(self.spec), "findings": [asdict(f) for f in self.findings],
                "beyondTier": self.beyond_tier}


def _spec_json(spec: NamespaceSpec | None) -> dict[str, Any] | None:
    if spec is None:
        return None
    d = asdict(spec)
    d["expires_at"] = spec.expires_at.isoformat() if spec.expires_at else None
    return d


def folder_etag(files: Mapping[str, str]) -> str:
    """The ETag of a namespace: a hash of its folder's content, stable until the folder changes."""
    return hashlib.sha256(plan_hash(files).encode()).hexdigest()[:16] if files else "0"


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
        other = next((d for d in (self.cfg.raw_instance["instance"].get("directory") or {}).values()
                      if env in d.get("environments", [])), None)
        raise Problem.unprocessable("environment-not-served", f"{env} is not served by the {self.cfg.name} instance",
                                    instanceUrl=(other or {}).get("url"), portalUrl=(other or {}).get("portalUrl"))

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
            return self.git.read_folder(folder(cluster_id, ns))
        except GitUnavailable as exc:
            raise Problem(502, "git-unavailable", str(exc)[:300]) from exc

    def workload_counts(self, cluster_id: str, ns: str) -> tuple[int, int]:
        """Pods and PVCs in a namespace, for the delete thresholds. A live read: unknown is 503, never 0."""
        client = self.registry.cache(cluster_id).client
        try:
            return (len(client.list("Pod", namespace=ns).get("items", [])),
                    len(client.list("PersistentVolumeClaim", namespace=ns).get("items", [])))
        except (ClusterUnreachable, KubeError) as exc:
            raise Problem(503, "cluster-unreachable", f"Cannot count the workloads in {ns}: {str(exc)[:200]}",
                          extra={"retryAfter": 30}) from exc

    # ---- plan a create or update
    def plan_namespace(self, who: Identity, cluster_id: str, body: Mapping[str, Any], *, action: str,
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
            # The label is only written at create; refuse here, not as a 422 from the API server at apply.
            label_value_of(requester.person.username)
        operator = "cmapi-operator" in who.roles or "cmapi-admin" in who.roles
        prev_files, base_sha = self._read_folder(cluster_id, ns)
        prev_ns = next((yaml.safe_load(t) for p, t in prev_files.items() if p.endswith("namespace.yaml")), None)
        if action == "create" and prev_ns:
            raise Problem.conflict("namespace-exists", f"{ns} is already in Git")
        if action != "create" and not prev_ns:
            raise Problem(404, "object-not-found", f"{ns} is not managed on {cluster_id}")
        etag = folder_etag(prev_files)
        if action != "create":
            if if_match is None:
                raise Problem(428, "precondition-required", "If-Match is required on a change; GET the namespace for its etag")
            if if_match.strip('"') != etag:
                raise Problem(412, "precondition-failed", "The namespace changed in Git since you read it",
                              extra={"etag": etag})
        cur_l = {k: v for k, v in (prev_ns or {}).get("metadata", {}).get("labels", {}).items()
                 if self.cfg.metadata.classify(k) in ("governed", "team")}
        cur_a = {k: v for k, v in (prev_ns or {}).get("metadata", {}).get("annotations", {}).items()
                 if self.cfg.metadata.classify(k) in ("governed", "team")}
        labels, anns = dict(body.get("labels") or {}), dict(body.get("annotations") or {})
        self.cfg.metadata.check(labels, anns, operator=operator, current_labels=cur_l, current_annotations=cur_a)
        labels = self.cfg.metadata.merge_patch(cur_l, labels)
        anns = self.cfg.metadata.merge_patch(cur_a, anns)

        old_tier = (prev_ns or {}).get("metadata", {}).get("labels", {}).get("cmapi.net/tier")
        old_exp = (prev_ns or {}).get("metadata", {}).get("annotations", {}).get("cmapi.net/expires-at")
        old_quota = _old_quota(prev_files)
        tier = body.get("tier") or old_tier or "small"
        quota, limits = body.get("quota"), body.get("limitRange")
        expires = _date(body.get("expiresAt")) if body.get("expiresAt") else (
            date.fromisoformat(old_exp) if old_exp and action != "create" else None)
        exp_facts: dict[str, Any] = {}
        if action == "create":
            p = self.cfg.expiration.plan_create(env, expires, date.today()) if expires else None
            if p:
                exp_facts = p.facts()
        elif body.get("extendDays") or body.get("expiresAt") or body.get("makePermanent"):
            info = ExpiryInfo(ns, env, created=date.today(), expires_at=date.fromisoformat(old_exp) if old_exp else None)
            if body.get("makePermanent"):
                p = self.cfg.expiration.plan_make_permanent(info)
                expires = None
            elif body.get("extendDays"):
                p = self.cfg.expiration.plan_extend(info, date.today(), days=int(body["extendDays"]))
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
                        **self.cfg.tiers.rendered_overrides(_doc(prev_files, "resourcequota.yaml"),
                                                            _doc(prev_files, "limitrange.yaml"))}
        if resolved.custom and custom_before:
            quota = {**{k: v for k, v in approved.items() if not k.startswith("limitRange.")}, **(quota or {})}
            limits = _merge_limits(approved, limits)
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
            findings = self.validator.validate(files, cluster_id, env)
        except ValidatorUnavailable as exc:
            raise Problem(503, "validator-unavailable", str(exc)[:300], extra={"retryAfter": 60}) from exc
        errors = [f for f in findings if f.severity == "error"]
        if errors:
            for f in errors:
                VALIDATION_FAILURES.labels(f.source).inc()
            raise Problem.policy_violation("Rendered files failed validation",
                                           [{"code": f.rule, "source": f.source, "path": f.path, "detail": f.message}
                                            for f in errors])
        old_hard = {}
        if old_tier:
            # A custom namespace: what Git holds, as it is. It was approved, so no bound is checked again (#214).
            old_hard = dict(old_quota or {}) if custom_before else self.cfg.tiers.quota_for(env, old_tier)
        cpu_delta = float(qty(hard["requests.cpu"]) - qty(old_hard.get("requests.cpu", "0")))
        mem_delta = float(qty(hard["requests.memory"]) - qty(old_hard.get("requests.memory", "0")))
        cap = self.capacity.check(cluster_id, env, max(cpu_delta, 0), max(mem_delta, 0))
        if cap.status == "exceeded":
            raise Problem.unprocessable("capacity-exceeded", f"{cap.binding_resource} would exceed the cluster",
                                        capacity=dict(cap.detail))
        facts = {"plugin": "namespaces", "action": action, "environment": env, "namespace": ns, "clusterId": cluster_id,
                 "team": labels.get("cmapi.net/team"), "tier": tier, "capacity": cap.status, "capacityFresh": cap.fresh,
                 "automated": requester.automated, "requesterClient": who.client_id if who.kind == "service" else None,
                 "clusterLabels": dict(st.policy.labels), "warnings": [f.message for f in findings], "reason": reason,
                 **exp_facts, **self.cfg.metadata.change_facts({**cur_l, **cur_a}, {**labels, **anns})}
        if old_tier and action != "create":
            facts.update(self.cfg.tiers.compare(env, old_tier, old_hard or hard, tier, hard).facts())
        # Beyond the tier: each overridable value that differs from the tier and from the value that Git holds. A value that
        # was approved before is not beyond the tier again.
        beyond = {k: v for k, v in self.cfg.tiers.beyond(env, tier, hard, limit_range).items()
                  if k not in approved or qty(approved[k]) != qty(v["requested"])}
        # Network exposure: the new quota has more load balancers or NodePorts than Git holds (for a new namespace: than the
        # tier gives). It does not depend on the beyond-tier keys: a change to a tier with a higher value raises it too.
        exposure_base = (old_quota or {}) if old_tier else resolved.quota
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
                    beyond_tier=beyond_view)

    def _decide(self, facts: Mapping[str, Any], team_auto_today: int = 0) -> Requirement:
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
        if not prev:
            raise Problem(404, "object-not-found", f"{ns} is not managed on {cluster_id}")
        etag = folder_etag(prev)
        if reason != "expired":
            if if_match is None:
                raise Problem(428, "precondition-required", "If-Match is required on a delete; GET the namespace for its etag")
            if if_match.strip('"') != etag:
                raise Problem(412, "precondition-failed", "The namespace changed in Git since you read it", extra={"etag": etag})
        ns_doc = yaml.safe_load(next(t for p, t in prev.items() if p.endswith("namespace.yaml")))
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
        files = self.renderer.delete(cluster_id, ns, prev)
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
            idempotency_key=idempotency_key, idempotency_fingerprint=body_fingerprint)
        auto = req.approved_at_plan
        note = req.auto or f"waiting for {[(s.group, s.count) for s in req.slots]}"
        repo.insert(row, E.PLAN_AUTO_APPROVED if auto else E.PLAN_NEEDS_APPROVAL, who.username, note)
        CHANGE_REQUESTS.labels(plan.plugin, plan.action, plan.env, row.status).inc()
        if auto:
            if req.auto and req.auto.startswith("auto:"):
                AUTO_APPROVALS.labels(req.auto.removeprefix("auto:"), plan.env).inc()
            jobs.enqueue("open_pr", request_id=rid, cluster_id=plan.cluster_id)
        else:
            jobs.enqueue("channel_notify", request_id=rid, cluster_id=plan.cluster_id, payload={"kind": "pending"})
        return row


def _date(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _doc(prev: Mapping[str, str], name: str) -> dict[str, Any] | None:
    """The one object of a file of the namespace's folder, or None when the folder has no such file."""
    text = next((t for p, t in prev.items() if p.endswith("/" + name)), None)
    return yaml.safe_load(text) if text else None


def _old_quota(prev: Mapping[str, str]) -> dict[str, str] | None:
    doc = _doc(prev, "resourcequota.yaml")
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
    return [d["metadata"]["name"] for d in yaml.safe_load_all(text) if d] if text else []


def _grants(prev: Mapping[str, str], *, scc: bool) -> list[tuple[str, str]]:
    text = next((t for p, t in prev.items() if p.endswith("/rolebindings.yaml")), None)
    out: list[tuple[str, str]] = []
    for d in (yaml.safe_load_all(text) if text else []):
        if not d:
            continue
        role = d["roleRef"]["name"]
        sa = d["subjects"][0]["name"]
        is_scc = role.startswith("system:openshift:scc:")
        if is_scc == scc:
            out.append((sa, role.removeprefix("system:openshift:scc:") if scc else role))
    return out


__all__ = ["Pipeline", "Plan", "approval_view", "folder_etag", "fingerprint"]
