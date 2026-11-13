"""Routes of the namespaces plugin."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Response
from fastapi.responses import JSONResponse

from cmapi import __version__
from cmapi.core.context import AppContext
from cmapi.core.db.repo import AuditRepo, JobRepo, RequestRepo, fingerprint
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.models import (Api, ChangeRequest, NamespaceCreate, NamespaceList, NamespacePatch, NamespaceView,
                               PlanView)
from cmapi.core.pipeline import folder_etag
from cmapi.core.render.manifests import folder
from cmapi.core.views import request_view
from cmapi.routers import ClusterId, DryRun, NamespaceName, caller, ctx, idempotency_key, if_match, require
from pydantic import Field

router = DocumentedRouter("namespaces", prefix="/api/v1/clusters/{cluster_id}", version=__version__,
                          group="Namespaces and metadata",
                          description="The managed namespaces of a cluster: read them, and create, change, delete or extend "
                                      "one. Each write returns a change request and becomes a pull request after approval.")

WRITE_PROBLEMS = ["cluster-not-found", "cluster-not-writable", "environment-not-served", "environment-forbidden", "plugin-disabled",
                  "validation-failed", "policy-violation", "capacity-exceeded", "change-pending", "no-change",
                  "identity-incomplete", "unknown-user", "invalid-team-dl", "idempotency-key-required",
                  "idempotency-replay", "git-unavailable", "cluster-unreachable", "validator-unavailable",
                  "unknown-serviceaccount"]


class ExtendBody(Api):
    days: int | None = Field(default=None, description="Days to extend by, up to the environment's limit", examples=[30])
    until: str | None = Field(default=None, description="A date to extend to", examples=["2026-12-15"])
    justification: str | None = Field(default=None, description="Why", examples=["Another sprint"])


def _idem(key: str | None, dry_run: bool) -> str | None:
    if dry_run:
        return None
    if not key:
        raise Problem.bad_request("idempotency-key-required", "Idempotency-Key header is required on writes")
    if len(key) > 100:                # the column's width: past it the INSERT would be a 500
        raise Problem.bad_request("idempotency-key-required", "Idempotency-Key is at most 100 characters")
    return key


def _replay(c: AppContext, who: Identity, key: str | None, body: dict[str, Any]) -> dict | None:
    if key is None:
        return None
    with c.db.session() as s:
        repo = RequestRepo(s)
        row = repo.by_idempotency(who.sub, key)
        if row is None:
            return None
        if row.idempotency_fingerprint != fingerprint(body):
            raise Problem.conflict("idempotency-replay", "Idempotency-Key was used for a different request",
                                   requestId=row.request_id)
        return request_view(repo, row)


def _submit(c: AppContext, who: Identity, plan: Any, key: str | None, body: dict[str, Any], justification: str | None) -> dict:
    try:
        with c.db.session() as s:
            repo, jobs = RequestRepo(s), JobRepo(s)
            row = c.pipeline.submit(who, plan, repo, jobs, idempotency_key=key, body_fingerprint=fingerprint(body),
                                    justification=justification)
            AuditRepo(s).record(who, f"namespace.{plan.action}", f"{plan.cluster_id}/{plan.namespace}",
                                {"requestId": row.request_id, "status": row.status})
            return request_view(repo, row)
    except Problem as exc:
        # Lost a race to the same key: the winner's commit is visible now, and it is this caller's first response.
        replay = _replay(c, who, key, body) if exc.status == 409 else None
        if replay:
            return replay
        raise


def _namespace_view(c: AppContext, cluster_id: str, obj: dict[str, Any], open_map: dict) -> dict[str, Any]:
    m = obj["metadata"]
    labels, ann = m.get("labels") or {}, m.get("annotations") or {}
    return {"clusterId": cluster_id, "name": m["name"], "env": labels.get("cmapi.net/env"), "team": labels.get("cmapi.net/team"),
            "tier": labels.get("cmapi.net/tier"), "labels": labels, "annotations": ann,
            "managed": labels.get("cmapi.net/managed") == "true", "expiresAt": ann.get("cmapi.net/expires-at"),
            "etag": None, "openRequest": open_map.get((cluster_id, m["name"]))}


@router.read("/namespaces", summary="Managed namespaces on a cluster", permission="objects:read", response_model=NamespaceList,
             problems=["cluster-not-found", "cluster-unreachable"])
def list_namespaces(cluster_id: ClusterId, who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """Every namespace labelled cmapi.net/managed=true on the cluster, from the watch cache, with the request
    holding each one's lock. The etag is only on the single-namespace read, because it comes from Git."""
    st = c.registry.get(cluster_id)
    if st.policy:
        c.cfg.roles.require(who, "objects:read", st.policy.environment)
    cache = c.registry.cache(cluster_id)
    with c.db.session() as s:
        open_map = RequestRepo(s).open_namespaces(cluster_id)
    items = [_namespace_view(c, cluster_id, o, open_map) for o in cache.all("Namespace")
             if (o["metadata"].get("labels") or {}).get("cmapi.net/managed") == "true"]
    return {"items": sorted(items, key=lambda x: x["name"])}


@router.read("/namespaces/{ns}", summary="One namespace, with its etag", permission="objects:read", response_model=NamespaceView,
             problems=["cluster-not-found", "object-not-found", "git-unavailable"])
def get_namespace(cluster_id: ClusterId, ns: NamespaceName, response: Response, who: Identity = Depends(require("objects:read")),
                  c: AppContext = Depends(ctx)) -> dict:
    """The live namespace and the etag of its folder in Git. Send the etag as If-Match on PATCH or DELETE."""
    st = c.registry.get(cluster_id)
    if st.policy:
        c.cfg.roles.require(who, "objects:read", st.policy.environment)
    files, _ = c.pipeline._read_folder(cluster_id, ns)
    live = None
    try:
        live = c.registry.cache(cluster_id).namespace(ns)
    except Problem:
        pass
    if not files and live is None:
        raise Problem(404, "object-not-found", f"{ns} is not on {cluster_id} and not in Git")
    with c.db.session() as s:
        open_map = RequestRepo(s).open_namespaces(cluster_id)
    obj = live or {"metadata": {"name": ns, "labels": {}, "annotations": {}}}
    view = _namespace_view(c, cluster_id, obj, open_map)
    view["etag"] = folder_etag(files)
    response.headers["ETag"] = f'"{view["etag"]}"'
    return view


@router.write("/namespaces", summary="Create a namespace", permission="namespaces:create", response_model=ChangeRequest,
              problems=WRITE_PROBLEMS + ["reserved-namespace", "invalid-namespace-name", "namespace-exists",
                                         "namespace-exists-unmanaged", "expiration-not-allowed", "expiration-in-past", "on-behalf-of-not-allowed",
                                         "on-behalf-of-required"])
def create_namespace(cluster_id: ClusterId, body: NamespaceCreate,
                     dry_run: DryRun = False,
                     key: str | None = Depends(idempotency_key), who: Identity = Depends(require("namespaces:create")),
                     c: AppContext = Depends(ctx)):
    """Plans a new namespace on the cluster and submits a change request; the bot opens a pull request once it
    is approved. `dryRun=true` answers 200 with the plan, the capacity check and the approval that would apply,
    and writes nothing. The environment is the cluster's and must be one this instance serves."""
    raw = body.model_dump(by_alias=True, exclude_none=True)
    raw["expiresAt"] = body.expires_at.isoformat() if body.expires_at else None
    raw["clusterId"] = cluster_id     # in the fingerprint: one key on two clusters is two requests, not a replay
    key = _idem(key, dry_run)
    replay = _replay(c, who, key, raw)
    if replay:
        return replay
    plan = c.pipeline.plan_namespace(who, cluster_id, raw, action="create")
    if dry_run:
        return JSONResponse(PlanView.model_validate(plan.view()).model_dump(by_alias=True), status_code=200)
    return _submit(c, who, plan, key, raw, body.justification)


@router.write("/namespaces/{ns}", summary="Change a namespace", permission="namespaces:write", method="PATCH",
              response_model=ChangeRequest,
              problems=WRITE_PROBLEMS + ["object-not-found", "precondition-required", "precondition-failed"])
def update_namespace(cluster_id: ClusterId, ns: NamespaceName, body: NamespacePatch,
                     dry_run: DryRun = False,
                     key: str | None = Depends(idempotency_key), etag: str | None = Depends(if_match),
                     who: Identity = Depends(require("namespaces:write")), c: AppContext = Depends(ctx)):
    """A merge patch on the namespace: tier, custom quota, labels and annotations (null removes a key). Needs
    If-Match with the etag from GET; 412 when the folder changed since. One open request per namespace."""
    raw = {**body.model_dump(by_alias=True, exclude_none=True), "namespace": ns, "clusterId": cluster_id}
    # exclude_none also drops None inside dicts, and in a merge patch null is what removes a key
    for field in ("labels", "annotations"):
        if getattr(body, field) is not None:
            raw[field] = getattr(body, field)
    key = _idem(key, dry_run)
    replay = _replay(c, who, key, raw)
    if replay:
        return replay
    plan = c.pipeline.plan_namespace(who, cluster_id, raw, action="update", if_match=etag)
    if dry_run:
        return JSONResponse(PlanView.model_validate(plan.view()).model_dump(by_alias=True), status_code=200)
    return _submit(c, who, plan, key, raw, body.justification)


@router.write("/namespaces/{ns}", summary="Delete a namespace", permission="namespaces:write", method="DELETE",
              response_model=ChangeRequest,
              problems=WRITE_PROBLEMS + ["object-not-found", "precondition-required", "precondition-failed", "namespace-protected"])
def delete_namespace(cluster_id: ClusterId, ns: NamespaceName, key: str | None = Depends(idempotency_key), etag: str | None = Depends(if_match),
                     who: Identity = Depends(require("namespaces:write")), c: AppContext = Depends(ctx)):
    """Opens a delete request: the folder leaves Git after approval, and the namespace waits in awaiting_prune
    until an operator confirms the prune. Needs If-Match."""
    raw = {"namespace": ns, "action": "delete", "clusterId": cluster_id}
    key = _idem(key, False)
    replay = _replay(c, who, key, raw)
    if replay:
        return replay
    plan = c.pipeline.plan_delete(who, cluster_id, ns, if_match=etag)
    return _submit(c, who, plan, key, raw, None)


@router.write("/namespaces/{ns}/expiration:extend", summary="Extend a namespace's expiry", permission="namespaces:write",
              response_model=ChangeRequest,
              problems=WRITE_PROBLEMS + ["object-not-found", "expiration-not-allowed", "expiration-limit", "expiration-not-set", "expiration-in-past",
                                         "precondition-required", "precondition-failed"])
def extend(cluster_id: ClusterId, ns: NamespaceName, body: ExtendBody, key: str | None = Depends(idempotency_key),
           etag: str | None = Depends(if_match), who: Identity = Depends(require("namespaces:write")),
           c: AppContext = Depends(ctx)):
    """Extends the expiry by `days` (up to the environment's limit) or to `until`. A normal request: plan,
    approval, bot PR. Needs If-Match."""
    raw: dict[str, Any] = {"namespace": ns, "clusterId": cluster_id}
    if body.days:
        raw["extendDays"] = body.days
    elif body.until:
        raw["expiresAt"] = body.until
    else:
        raise Problem.unprocessable("validation-failed", "Send days or until")
    key = _idem(key, False)
    replay = _replay(c, who, key, raw)
    if replay:
        return replay
    plan = c.pipeline.plan_namespace(who, cluster_id, raw, action="update", if_match=etag, reason="expiration:extend")
    return _submit(c, who, plan, key, raw, body.justification)
