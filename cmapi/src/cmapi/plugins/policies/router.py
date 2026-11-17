"""The policies plugin, read side (#302): what Kyverno decided on each cluster, and what cmapi refused before Git.

GET /policies/results reads each cluster's policy reports from its ReportCache (core/clients/policyreports.py), never from
the cluster at request time. GET /policies/rejections reads policy_rejections (core/rejections.py). Both are on the one list
contract (docs/01, Lists): a page, a signed cursor bound to every filter, `letters`.

What a caller sees (design B of #302, adopted by the arbitration):
- only the clusters of the environments where the caller holds objects:read (results) or requests:read (rejections);
- only results on namespaces that cmapi manages (`cmapi.net/managed=true` in the watch cache), and only of the policies of
  the bundle of the cluster's environment that are on the cluster. The rest is counted in `hidden`, with no names;
- for each cluster a named state, and counts that are null, never zero, when they are not known.

There is no list of policies here: the bundle (core/policybundle.py) names them, and #333 widens it without a change here.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Mapping

from fastapi import Depends, Query

from cmapi import __version__
from cmapi.core.clients.policyreports import LISTED, VERDICTS, Snapshot
from cmapi.core.context import AppContext
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.listquery import Lister, ListQuery, Sorts
from cmapi.core.models import PolicyResultPage, RejectionPage
from cmapi.core.policybundle import BundlePolicy
from cmapi.core.policygen import ACTIONS
from cmapi.core.registry import ClusterState
from cmapi.core.rejections import RejectionRepo
from cmapi.routers import Cursor, Limit, ctx, require

# In the group of the namespaces and the expiration plugins: what the bundle checks is the metadata, the quota and the limits of
# the managed namespaces, and docs/01's six groups stay six (test_api_docs, #128).
router = DocumentedRouter("policies", prefix="/api/v1", version=__version__, group="Namespaces and metadata",
                          description="What the Kyverno bundle decided on each cluster, read from its policy reports, and the "
                                      "requests that cmapi refused before Git, with Kyverno's warnings on plans that went on.")

NAMES_MAX = 20                     # the names of missing or differing policies that one cluster lists

ClusterFilter = Annotated[str | None, Query(alias="clusterId", examples=["CRC"], description="Only this cluster.")]
EnvFilter = Annotated[str | None, Query(examples=["dev"], description="Only the clusters of this environment.")]
NamespaceFilter = Annotated[str | None, Query(examples=["orders-dev"], description="Only this namespace.")]
PolicyFilter = Annotated[str | None, Query(examples=["cmapi-metadata-dev-label-other-keys-prefix"],
                                           description="Only this policy (the policy or check of a finding, for rejections).")]
ResultFilter = Annotated[str, Query(examples=["fail,warn,error"],
                                    description="The verdicts to list, comma-separated: `fail`, `warn` and `error` (the default "
                                                "is all three). Pass and skip are counted, never listed: another value returns 422 "
                                                "`validation-failed`.")]
Text = Annotated[str, Query(examples=["orders"], description="Text that the namespace or the resource's name contains.")]
Since = Annotated[str, Query(examples=["7d"],
                             description="How far back, in days: `1d` to the instance's policy.rejections.retentionDays (90 by "
                                         "default). Another value returns 422 `validation-failed`.")]
Stage = Annotated[str | None, Query(examples=["plan"], description="Only `plan` or only `ci`.")]
Outcome = Annotated[str | None, Query(examples=["refused"], description="Only `refused` or only `warned`.")]


# --------------------------------------------------------------------------- results

def _managed(st: ClusterState) -> set[str]:
    if st.cache is None:
        return set()
    return {ns["metadata"]["name"] for ns in st.cache.all("Namespace")
            if (ns["metadata"].get("labels") or {}).get("cmapi.net/managed") == "true"}


def _iso(t: float | datetime | None) -> datetime | None:
    if t is None or isinstance(t, datetime):
        return t
    return datetime.fromtimestamp(t, tz=timezone.utc)


def _empty() -> dict[str, int]:
    return {v: 0 for v in VERDICTS}


def _bundle_view(bundle: Mapping[str, BundlePolicy], snap: Snapshot, mode: str) -> tuple[dict[str, Any] | None, list[str], bool]:
    """(the bundle on the cluster against the render, the live validationActions, drift)."""
    live = snap.policies
    if live is None:
        return None, [], False
    on = sorted(n for n in bundle if n in live)
    missing = sorted(n for n in bundle if n not in live)
    differing = [n for n in on if bundle[n].digest and live[n].digest != bundle[n].digest]
    want = ACTIONS.get(mode, [])
    actions_differ = [n for n in on if bundle[n].generated and list(live[n].actions) != want]
    view = {"expected": len(bundle), "live": len(on), "current": len(on) - len(differing),
            "ready": sum(1 for n in on if live[n].ready), "missing": missing[:NAMES_MAX], "differing": differing[:NAMES_MAX],
            "actionsDiffer": actions_differ[:NAMES_MAX]}
    actions = sorted({a for n in on for a in live[n].actions})
    return view, actions, bool(missing or differing or actions_differ)


def _cluster(c: AppContext, st: ClusterState, env: str, namespace: str | None
             ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, int]]]:
    """One cluster's view, its listed rows, and the counts of each policy (following `namespace`)."""
    mode = c.cfg.policy.mode_for(env)
    view: dict[str, Any] = {"clusterId": st.cluster_id, "env": env, "mode": mode, "liveActions": [], "state": "ok",
                            "stateDetail": None, "asOf": None, "bundle": None, "counts": None, "hidden": None, "dropped": None}

    def unknown(state: str, detail: str, as_of: Any = None):
        view.update(state=state, stateDetail=detail, asOf=_iso(as_of))
        return view, [], {}

    if c.cfg.policy.engine == "none":
        return unknown("engine-off", "policy.engine is none on this instance: no Kyverno runs and no report is read")
    if mode == "off":
        return unknown("mode-off", f"the mode of {env} is off: no policy is rendered for it and no report is read")
    if st.status != "connected":
        return unknown("unreachable", f"the cluster is {st.status}: {'; '.join(st.findings)}"[:300], st.checked_at)
    if st.reports is None:
        return unknown("loading", "the report cache has not started")
    snap = st.reports.snapshot()
    if snap.installed is None:
        return unknown("loading", snap.probe_error or "discovery has not answered yet")
    if snap.installed is False:
        return unknown("not-installed", "wgpolicyk8s.io/v1alpha2 is not served: Kyverno is not installed on the cluster")
    if snap.forbidden:
        kinds = ", ".join(k.lower() + "s" for k in snap.forbidden)
        return unknown("forbidden", f"cmapi-reader may not list {kinds}: the reader's ClusterRole needs get, list and watch on them")
    if not snap.listed:
        return unknown("loading", "the reports are being listed")

    bundle = c.bundle.for_environment(env) if c.bundle else {}
    managed, live = _managed(st), snap.policies
    counts, hidden, per_policy = _empty(), {"unmanaged": 0, "otherPolicies": 0, "stale": 0}, {}
    rows: list[dict[str, Any]] = []
    for rep in snap.reports:
        in_scope = rep.namespace is not None and rep.namespace in managed
        for (policy, verdict), n in rep.counts.items():
            if not in_scope:
                hidden["unmanaged"] += n
            elif policy not in bundle:
                hidden["otherPolicies"] += n
            elif live is not None and policy not in live:
                hidden["stale"] += n
            else:
                counts[verdict] += n
                if namespace in (None, rep.namespace):
                    per_policy.setdefault(policy, _empty())[verdict] += n
        if not in_scope:
            continue
        api_version, kind, name = rep.resource
        for row in rep.rows:
            if live is not None and row.policy not in live:
                continue
            check = bundle[row.policy].check
            rows.append({"clusterId": st.cluster_id, "env": env, "mode": mode, "namespace": rep.namespace,
                         "resource": {"apiVersion": api_version, "kind": kind, "name": name}, "policy": row.policy,
                         "rule": (check or {}).get("rule") or row.rule, "kyvernoRule": row.rule, "result": row.result,
                         "message": row.message, "process": row.process, "source": row.source, "observedAt": row.at})
    bundle_view, actions, drift = _bundle_view(bundle, snap, mode)
    view.update(liveActions=actions, asOf=_iso(snap.as_of), bundle=bundle_view, counts=counts, hidden=hidden,
                dropped=snap.dropped)
    if snap.stale:
        view.update(state="stale", stateDetail="no good read of the reports for 30 minutes: the counts are the last ones read")
    elif snap.dropped:
        view.update(state="capped", stateDetail=f"{snap.dropped} rows past policy.reports.maxResultsPerCluster "
                                                f"({c.cfg.policy.max_results_per_cluster}) are counted and not listed")
    elif drift:
        b = bundle_view or {}
        view.update(state="drift", stateDetail=f"{len(b.get('missing', []))} missing, {len(b.get('differing', []))} differ "
                                               f"from the render, {len(b.get('actionsDiffer', []))} without the actions "
                                               f"{', '.join(ACTIONS.get(mode, []))} of mode {mode}")
    return view, rows, per_policy


def _row_names(rows: list[dict[str, Any]]) -> None:
    """The Lister's key of each row, unique in the page set: the identity of the result, never its verdict or time, so a row
    whose verdict changes keeps its place between pages (design B, "Paging while reports change")."""
    seen: dict[str, int] = {}
    for r in rows:
        res = r["resource"]
        key = f"{r['namespace']}/{res['kind']}/{res['name']}/{r['policy']}/{r['kyvernoRule'] or ''}"
        seen[key] = seen.get(key, 0) + 1
        r["name"] = key if seen[key] == 1 else f"{key}#{seen[key]}"


@router.read("/policies/results", summary="Kyverno's results on each cluster, paged", permission="objects:read",
             response_model=PolicyResultPage, problems=["invalid-cursor", "invalid-limit", "validation-failed"])
def results(cluster_id: ClusterFilter = None, env: EnvFilter = None, namespace: NamespaceFilter = None, policy: PolicyFilter = None,
            result: ResultFilter = "fail,warn,error", q: Text = "", limit: Limit = 50, cursor: Cursor = None,
            who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """The clusters of the caller's environments with the state of their policy reports, each policy of the bundle with its
    counts, and one page of the fail, warn and error results on managed namespaces, from the watch of each cluster's reports.
    A cluster whose results are not known (Kyverno not installed, not reachable, not readable, its mode off) has a state and
    null counts, never zeros. The `policy` object is the one of GET /admin/integrations."""
    wanted = [v.strip() for v in result.split(",") if v.strip()]
    if not wanted or any(v not in LISTED for v in wanted):
        raise Problem.unprocessable("validation-failed", f"result is a comma-separated list of {list(LISTED)}, not {result!r}")
    clusters, rows, per_policy, scoped_envs = [], [], {}, set()
    for st in sorted(c.registry.clusters.values(), key=lambda s: s.cluster_id):
        cenv = st.environment
        if cenv is None or not c.cfg.roles.allowed(who, "objects:read", cenv):
            continue
        view, cluster_rows, counts = _cluster(c, st, cenv, namespace)
        clusters.append(view)
        if (cluster_id or st.cluster_id) != st.cluster_id or (env or cenv) != cenv:
            continue
        scoped_envs.add(cenv)
        rows.extend(cluster_rows)
        for name, n in counts.items():
            acc = per_policy.setdefault(name, _empty())
            for v in VERDICTS:
                acc[v] += n[v]
    policies = []
    if c.cfg.policy.engine != "none" and c.bundle:
        found: dict[str, tuple[BundlePolicy, set[str]]] = {}
        for e in sorted(scoped_envs):
            if c.cfg.policy.mode_for(e) == "off":
                continue
            for name, p in c.bundle.for_environment(e).items():
                found.setdefault(name, (p, set()))[1].add(e)
        for name in sorted(found):
            p, envs = found[name]
            policies.append({"name": name, "kind": p.kind, "description": p.description,
                             "check": dict(p.check) if p.check else None, "environments": sorted(envs),
                             "generated": p.generated, "counts": per_policy.get(name, _empty())})
    rows = [r for r in rows if r["result"] in wanted]
    _row_names(rows)
    query = ListQuery(q=q, filters={"clusterId": cluster_id or "", "env": env or "", "namespace": namespace or "",
                                    "policy": policy or ""}, sort="name", limit=limit, cursor=cursor,
                      context={"result": ",".join(sorted(wanted))})
    page = Lister(c.lister.secret).page(rows, query)
    for item in page["items"]:
        item.pop("name", None)
    return {"policy": c.cfg.policy.view(c.cfg.allowed_environments), "clusters": clusters, "policies": policies, **page}


# --------------------------------------------------------------------------- rejections

_SINCE = re.compile(r"^([0-9]{1,4})d$")
NEWEST = Sorts({"newest": lambda r: r["_first"]})


def _rejection(row: Any) -> dict[str, Any]:
    return {"id": f"rej-{row.id}", "firstAt": row.first_at, "lastAt": row.last_at, "count": row.count, "stage": row.stage,
            "outcome": row.outcome, "problem": row.problem, "clusterId": row.cluster_id, "env": row.env,
            "namespace": row.namespace, "plugin": row.plugin, "action": row.action, "requestId": row.request_id,
            "username": row.username, "automated": row.automated, "findings": row.findings,
            # the Lister's keys: newest first, then the namespace and the id, which are unique and never change
            "name": f"{row.namespace}/{row.id:012d}", "_first": row.first_at.timestamp()}


@router.read("/policies/rejections", summary="What cmapi refused before Git, paged", permission="requests:read",
             response_model=RejectionPage, problems=["invalid-cursor", "invalid-limit", "validation-failed"])
def rejections(since: Since = "7d", cluster_id: ClusterFilter = None, env: EnvFilter = None, namespace: NamespaceFilter = None,
               stage: Stage = None, outcome: Outcome = None, policy: PolicyFilter = None, q: Text = "", limit: Limit = 50,
               cursor: Cursor = None, who: Identity = Depends(require("requests:read")), c: AppContext = Depends(ctx)) -> dict:
    """The plans that cmapi refused (a 422 that never became a request), Kyverno's warnings on plans that went on to a request,
    and the pull requests that the worker's checks failed, in the environments where the caller holds requests:read, newest
    first. Each holds who asked by username only. A refusal repeated on its UTC day is one row with its `count`."""
    m = _SINCE.fullmatch(since)
    days = int(m.group(1)) if m else 0
    retention = c.cfg.policy.rejection_retention_days
    if not 1 <= days <= retention:
        raise Problem.unprocessable("validation-failed", f"since is 1d to {retention}d, not {since!r}")
    if stage not in (None, "plan", "ci"):
        raise Problem.unprocessable("validation-failed", f"stage is plan or ci, not {stage!r}")
    if outcome not in (None, "refused", "warned"):
        raise Problem.unprocessable("validation-failed", f"outcome is refused or warned, not {outcome!r}")
    envs = sorted(e for e in c.cfg.allowed_environments if c.cfg.roles.allowed(who, "requests:read", e))
    start = datetime.now(timezone.utc) - timedelta(days=days)
    with c.db.session() as s:
        found, truncated = RejectionRepo(s).since(envs, start)
        rows = [_rejection(r) for r in found]
    if policy:
        rows = [r for r in rows if any(f.get("policy") == policy for f in r["findings"])]
    query = ListQuery(q=q, filters={"clusterId": cluster_id or "", "env": env or "", "namespace": namespace or "",
                                    "stage": stage or "", "outcome": outcome or ""}, sort="newest", limit=limit, cursor=cursor,
                      context={"since": since, "policy": policy or ""})
    page = Lister(c.lister.secret, NEWEST).page(rows, query)
    for item in page["items"]:
        item.pop("name", None)
        item.pop("_first", None)
    return {"since": since, "from": start, "truncated": truncated, **page}
