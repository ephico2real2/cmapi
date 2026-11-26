"""Routes of the adoption plugin (the adoption design's D13): the candidates of a cluster, the labelled namespaces that a rule
skips, and the adoption of one namespace with its dry run.

An unmanaged namespace is never taken over silently: it must carry the opt-in label (`cmapi.net/adopt: "true"`), the request
needs a person's approval (approvals.py never auto-approves an adoption unless a policy names the plugin), and the folder
reaches the cluster only through the bot's pull request and its checks. The scan of a whole cluster (`POST .../adoption:scan`)
and the unmanaged-namespaces report are #252's admin operations and are not built here.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends
from fastapi.responses import JSONResponse

from cmapi import __version__
from cmapi.core.adoption import Standing, standing
from cmapi.core.clients.kube import BadResponse, ClusterUnreachable, KubeError
from cmapi.core.context import AppContext
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.git.base import GitUnavailable, IncompleteList
from cmapi.core.identity.claims import Identity
from cmapi.core.models import AdoptBody, AdoptionList, ChangeRequest, PlanView
from cmapi.core.rejections import refusals
from cmapi.core.sync import application_name
from cmapi.plugins.namespaces.router import WRITE_PROBLEMS, _idem, _replay, _submit
from cmapi.routers import ClusterId, DryRun, NamespaceName, ctx, idempotency_key, require

router = DocumentedRouter("adoption", prefix="/api/v1/clusters/{cluster_id}", version=__version__,
                          group="Namespaces and metadata",
                          description="Adopt a namespace that exists on a cluster and that cmapi does not manage: list the "
                                      "candidates, see why a labelled namespace is skipped, and plan or request one adoption. "
                                      "Each adoption is a change request, approved by a person, delivered by a pull request.")

LIST_PROBLEMS = ["cluster-not-found", "cluster-unreachable", "environment-forbidden", "git-unavailable"]
ADOPT_PROBLEMS = [*WRITE_PROBLEMS, "object-not-found", "namespace-not-adoptable", "policy-violation", "validator-unavailable",
                  "validator-busy"]


def _own_application(c: AppContext, cluster_id: str, ns: str) -> str:
    """The Argo CD Application that cmapi's folders are synced by: a namespace that it tracks is not tracked elsewhere."""
    return application_name(c.delivery.argocd_root_application, cluster_id, ns)


def _standings(c: AppContext, who: Identity, cluster_id: str) -> list[Standing]:
    """Where each namespace of the cluster stands (D1), read now from the cluster, with the folders of Git."""
    st = c.registry.get(cluster_id)
    env = st.policy.environment if st.policy else None
    c.cfg.roles.require(who, "adoption:write", env)
    client = c.registry.cache(cluster_id).client
    try:
        namespaces = client.list("Namespace")["items"]
    except (ClusterUnreachable, KubeError, BadResponse) as exc:
        raise Problem(503, "cluster-unreachable", f"Cannot list the namespaces of {cluster_id}: {str(exc)[:200]}",
                      extra={"retryAfter": 30}) from exc
    base = f"clusters/{cluster_id}/namespaces/"
    try:
        listed, _ = c.git.list_folder(base)
        folders: set[str] | None = {p[len(base):].split("/", 1)[0] for p in listed if p.startswith(base)}
    except IncompleteList:
        folders = None              # too large to list: the label decides here, and the plan reads the one folder again
    except GitUnavailable as exc:
        raise Problem(502, "git-unavailable", str(exc)[:300]) from exc
    out = []
    for ns in namespaces:
        name = (ns.get("metadata") or {}).get("name", "")
        out.append(standing(ns, in_git=folders is not None and name in folders, environment=env or "",
                            cluster_id=cluster_id, settings=c.cfg.adoption, keys=c.cfg.metadata,
                            own_application=_own_application(c, cluster_id, name), reserved_patterns=c.pipeline.reserved))
    return sorted(out, key=lambda s: s.name)


def _view(c: AppContext, rows: list[Standing]) -> dict[str, Any]:
    return {"items": [{"name": s.name, "state": s.state, "rule": s.rule, "detail": s.detail, "labelled": s.labelled,
                       "recognised": list(s.recognised), "application": s.application} for s in rows],
            "total": len(rows), "label": c.cfg.adoption.label}


@router.read("/adoption/candidates", summary="List the namespaces that can be adopted",
             returns="Each namespace of the cluster that carries the opt-in label, is not excluded, is not managed and is not "
                     "tracked by another Argo CD Application, by name.",
             permission="adoption:write", response_model=AdoptionList, problems=LIST_PROBLEMS)
def candidates(cluster_id: ClusterId, who: Identity = Depends(require("adoption:write")),
               c: AppContext = Depends(ctx)) -> dict:
    """The candidates of the adoption design's D1, read now from the cluster: not a built-in or configured exclusion (adoption.yaml),
    not Terminating, not managed (`cmapi.net/managed`, or a folder in Git), not tracked by another Argo CD Application, and
    labelled `cmapi.net/adopt: "true"`. `recognised` lists the adoptionLabels of metadata-keys.yaml that a namespace carries:
    a mark of another tool, which never selects a namespace by itself."""
    return _view(c, [s for s in _standings(c, who, cluster_id) if s.state == "candidate"])


@router.read("/adoption/skipped", summary="List the labelled namespaces that a rule skips",
             returns="Each namespace that carries the opt-in label and is not a candidate, with the rule that stops it.",
             permission="adoption:write", response_model=AdoptionList, problems=LIST_PROBLEMS)
def skipped(cluster_id: ClusterId, who: Identity = Depends(require("adoption:write")), c: AppContext = Depends(ctx)) -> dict:
    """The namespaces that carry the opt-in label and are not candidates: `rule` is `excluded`, `terminating`, `managed`
    (already adopted: the label stays and is ignored) or `tracked-elsewhere` (with the Application in `application`)."""
    return _view(c, [s for s in _standings(c, who, cluster_id) if s.labelled and s.state != "candidate"])


@router.write("/namespaces/{ns}:adopt", summary="Adopt an existing namespace", permission="adoption:write",
              response_model=ChangeRequest, dry_run_model=PlanView, problems=ADOPT_PROBLEMS)
def adopt(cluster_id: ClusterId, ns: NamespaceName, body: AdoptBody | None = None, dry_run: DryRun = False,
          key: str | None = Depends(idempotency_key), who: Identity = Depends(require("adoption:write")),
          c: AppContext = Depends(ctx)):
    """Plans the adoption of a namespace that exists on the cluster and that cmapi does not manage, and submits it as a change
    request (plugin `adoption`, action `adopt`). The namespace must carry `cmapi.net/adopt: "true"`; any other is 409
    `namespace-not-adoptable`, whose `rule` says why.

    cmapi reads the live Namespace and each of its ResourceQuotas and LimitRanges, and writes them to the namespace's folder
    as they are: only what the API server sets is dropped, and each key under a skip prefix of adoption.yaml only when that
    changes nothing on the cluster. It adds its own system keys and the tier `custom`; each ResourceQuota and LimitRange keeps
    its name, in its own file. Each difference from the instance's rules is a finding of the plan, never a change: a wrong or
    missing key, a value beyond the custom bounds, a policy failure that the namespace already holds (`policy-ratcheted`).

    The request needs one approver of approver-platform, and one more when the plan has findings; no automatic approval covers
    it. After approval the bot opens the pull request. cmapi reads the objects again before it pushes the branch and in the pull
    request's check: a change since the plan fails the request (`adoption-plan-stale`), and the label removed cancels it.

    `dryRun=true` answers 200 with the plan, its files, findings and approval, and opens no request."""
    justification = body.justification if body else None
    raw = {"namespace": ns, "clusterId": cluster_id, "action": "adopt", "justification": justification}
    key = _idem(key, dry_run)
    replay = _replay(c, who, key, raw)
    if replay:
        return replay
    with refusals(c, who, cluster_id, ns, "adopt", dry_run=dry_run, plugin="adoption"):
        plan = c.pipeline.plan_adoption(who, cluster_id, ns, own_application=_own_application(c, cluster_id, ns))
    if dry_run:
        return JSONResponse(PlanView.model_validate(plan.view()).model_dump(by_alias=True), status_code=200)
    return _submit(c, who, plan, key, raw, justification)
